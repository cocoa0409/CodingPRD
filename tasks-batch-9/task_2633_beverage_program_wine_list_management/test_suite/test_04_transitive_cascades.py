"""Transitive cascades: one call that moves five levels of records.

Two spines carry a cascade in this API.  The *inventory* spine starts at a
controller's approval of a spoilage write-off and runs down through the lot,
its bin, the list entries that depended on the wine and the counters on the
versions those entries belong to, while the recognised cost lands on the
venue's ledger.  The *catalogue* spine starts at a new vintage naming its
predecessor and runs through the predecessor's successor count, the stale flag
on every live list entry, the owning version's stale count and reprint
obligation, and finally the pinned-version flag on a confirmed wine dinner.

Every test builds its whole chain from an empty database through published
endpoints.
"""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions, factories as f, fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ERR_PINNED_LIST_VERSION_STALE
from test_helpers.test_users import (
    BEVERAGE_DIRECTOR_HEADERS,
    CONTROLLER_HEADERS,
    CONTROLLER_ID,
    sommelier_headers,
)

CLOCK = "2026-09-01T12:00:00Z"

# RED 28.0 is the category target every entry below is priced against.
_TARGETS = f.cogs_targets(SPARKLING=30.0, WHITE=25.0, ROSE=28.0, RED=28.0,
                          DESSERT=32.0, FORTIFIED=35.0)


def _assert_instant(actual, expected_prefix, field="timestamp"):
    """Match a server-minted instant against a whole-second literal.

    Timestamps are minted with three fractional digits, so the recipe's
    ``2026-09-01T12:00:00Z`` literal is compared on its whole-second prefix.
    """
    assert actual is not None, "%s must not be null" % field
    assert str(actual).startswith(expected_prefix), (
        "%s expected the instant %sZ, got %r" % (field, expected_prefix, actual))


def _harbor_room():
    return fx.create_venue(name="Harbor Room", venue_code="HRB",
                           cogs_target_pct_by_category=dict(_TARGETS),
                           event_cogs_target_pct=28.0, priority_rank=1)


def _monte_bello(vintage_year=2019, **overrides):
    return fx.create_wine(producer="Ridge", cuvee="Monte Bello",
                          vintage_year=vintage_year, category="RED",
                          reference_cost_cents=2400, bottle_size_ml=750,
                          case_pack=6, is_allocated=False, **overrides)


def _submitted_case_write_off():
    """Venue + 48-bottle bin holding one 12-bottle lot at 2400 cents each,
    a PUBLISHED list carrying one bottle-only entry for that wine, and a
    SUBMITTED write-off of the whole case proposed by the sommelier."""
    fx.set_clock(CLOCK)
    venue = _harbor_room()
    bin_ = fx.create_bin(venue, bin_code="A1", zone="CELLAR",
                         capacity_bottles=48, temperature_controlled=True)
    wine = _monte_bello()
    lot = fx.create_lot(venue, wine, bin_, bottles_received=12,
                        unit_cost_cents=2400,
                        received_at="2026-08-10T00:00:00Z")
    wine_list = fx.create_wine_list(venue, name="Dinner List")
    draft = fx.create_draft_version(wine_list, venue)
    entry = fx.add_entry(draft, wine, venue, sort_rank=1, by_the_glass=False,
                         par_bottles=6, education_verified=False)
    version = fx.publish_version(draft, venue)
    write_off = fx.submit_write_off(
        venue, lot, bottles=12, reason_code="CORKED",
        narrative="Whole case shows TCA taint on three sample bottles.")
    return {"venue": venue, "bin": bin_, "wine": wine, "lot": lot,
            "wine_list": wine_list, "version": version, "entry": entry,
            "write_off": write_off}


def _approve(write_off):
    return validate_success(
        api_client.approve_write_off(write_off["id"], CONTROLLER_HEADERS))


class TestWriteOffApprovalCascade:
    """One POST to /spoilage-write-offs/{id}/approve run down the inventory
    spine: write-off state and cost, lot, bin, list entry, list version, venue
    ledger and the single immutable ledger row the approval appends."""

    def test_approval_prices_the_whole_case_out_of_the_nominated_lot(self):
        """Approving the case write-off stamps the acting controller and books
        12 bottles at 2400 cents each as 28800 cents of recognised cost.

        "On approval the write-off moves `SUBMITTED → APPROVED`, records `approved_by_user_id` as the acting `X-User-ID`, and computes `cogs_cents` by pricing the written-off bottles out of that one nominated lot under the venue's costing method."

        Design: Difficulty/transitive_cascade/write_off_approval_cascades_lot_bin_entry_and_list_version
        """
        chain = _submitted_case_write_off()

        approved = _approve(chain["write_off"])

        assertions.assert_fields_equal(approved, {
            "state": "APPROVED",
            "approved_by_user_id": CONTROLLER_ID,
            "cogs_cents": 28800,
        }, "SpoilageWriteOff")

    def test_approval_empties_the_lot_the_bin_and_charges_the_venue_ledger(self):
        """The approval drops the lot to zero bottles, releases the bin's
        stored count to 0 and 0.00 per cent utilisation, and raises the
        venue's cost ledger by exactly the recognised 28800 cents.

        "Then the cascade: the lot's `bottles_on_hand` falls by that many bottles; the bin's `bottles_stored` falls by the same amount, its `utilization_pct` is recomputed and a bin that was `FULL` returns to `ACTIVE`; and the venue's `cogs_ledger_cents` rises by the recognised cost."

        Design: Difficulty/transitive_cascade/write_off_approval_cascades_lot_bin_entry_and_list_version
        """
        chain = _submitted_case_write_off()

        _approve(chain["write_off"])

        lot = validate_success(
            api_client.get_inventory_lot(chain["lot"]["id"],
                                         BEVERAGE_DIRECTOR_HEADERS))
        assert lot["bottles_on_hand"] == 0, (
            "the whole case left the cellar, so bottles_on_hand must be 0")

        bin_ = validate_success(
            api_client.get_cellar_bin(chain["bin"]["id"],
                                      BEVERAGE_DIRECTOR_HEADERS))
        assert bin_["bottles_stored"] == 0, "the bin gave up all 12 bottles"
        assertions.assert_decimal_equals(bin_["utilization_pct"], 0.00,
                                         "CellarBin.utilization_pct")
        assert bin_["bin_state"] == "ACTIVE", (
            "an empty 48-bottle bin is ACTIVE, not FULL")

        venue = fx.get_venue(chain["venue"])
        assertions.assert_fields_equal(venue, {
            "cogs_ledger_cents": 28800,
            "revenue_ledger_cents": 0,
        }, "Venue")

    def test_depleting_the_last_lot_flips_the_live_entry_out_of_stock(self):
        """With no lot of that wine left on hand, the published entry moves to
        OUT_OF_STOCK and its version's out-of-stock counter rises to 1 while
        the version itself stays PUBLISHED.

        "And when no lot at all for that venue-and-wine pair is left in `ON_HAND` with bottles on hand, every list entry for that venue and wine on a version that is `PUBLISHED` or `REPRINT_PENDING` moves `availability_state` from `AVAILABLE` to `OUT_OF_STOCK`, which in turn increments each owning version's `out_of_stock_entry_count`."

        Design: Difficulty/transitive_cascade/write_off_approval_cascades_lot_bin_entry_and_list_version
        """
        chain = _submitted_case_write_off()

        _approve(chain["write_off"])

        lot = validate_success(
            api_client.get_inventory_lot(chain["lot"]["id"],
                                         BEVERAGE_DIRECTOR_HEADERS))
        assert lot["state"] == "DEPLETED", (
            "a CORKED write-off that empties a lot leaves it DEPLETED, "
            "not terminally WRITTEN_OFF")

        entry = validate_success(
            api_client.get_list_entry(chain["entry"]["id"],
                                      BEVERAGE_DIRECTOR_HEADERS))
        assert entry["availability_state"] == "OUT_OF_STOCK", (
            "no bottles remain for this venue-and-wine pair")

        version = validate_success(
            api_client.get_list_version(chain["version"]["id"],
                                        BEVERAGE_DIRECTOR_HEADERS))
        assertions.assert_fields_equal(version, {
            "out_of_stock_entry_count": 1,
            "state": "PUBLISHED",
        }, "ListVersion")

    def test_approval_appends_exactly_one_spoilage_ledger_row(self):
        """The cascade writes one immutable SPOILAGE row for 12 bottles and
        28800 cents of cost, no revenue, stamped with the logical clock.

        "One ledger entry is appended with reason `SPOILAGE`, a positive `bottles` equal to the write-off's bottle count, a positive `cogs_cents` equal to the figure just computed, zero `revenue_cents`, and `write_off_id` naming the write-off."

        Design: Difficulty/transitive_cascade/write_off_approval_cascades_lot_bin_entry_and_list_version
        """
        chain = _submitted_case_write_off()

        _approve(chain["write_off"])

        entries = assertions.depletion_entries_for(
            BEVERAGE_DIRECTOR_HEADERS, write_off_id=chain["write_off"]["id"])
        assert len(entries) == 1, (
            "expected exactly 1 ledger row for the approval, got %d"
            % len(entries))
        assertions.assert_append_only_fields(entries[0])
        assertions.assert_fields_equal(entries[0], {
            "reason": "SPOILAGE",
            "bottles": 12,
            "cogs_cents": 28800,
            "revenue_cents": 0,
            "write_off_id": chain["write_off"]["id"],
        }, "DepletionEntry")
        _assert_instant(entries[0]["occurred_at"], "2026-09-01T12:00:00",
                        "DepletionEntry.occurred_at")

    def test_spoilage_row_names_no_listing_so_contest_points_stay_zero(self):
        """A write-off row names the write-off rather than the listing, so the
        entry's sales-contest score is untouched at 0.00.

        "Four nullable references say what caused the entry: `list_entry_id` is set for by-the-glass and bottle sales, `btg_slot_id` for slot closures, `event_id` for event settlements and their voids, and `write_off_id` for write-off approvals and reversals."

        Design: Difficulty/transitive_cascade/write_off_approval_cascades_lot_bin_entry_and_list_version
        """
        chain = _submitted_case_write_off()

        _approve(chain["write_off"])

        entries = assertions.depletion_entries_for(
            BEVERAGE_DIRECTOR_HEADERS, write_off_id=chain["write_off"]["id"])
        assertions.assert_null_fields(entries[0], "list_entry_id",
                                      "btg_slot_id", "event_id")

        entry = validate_success(
            api_client.get_list_entry(chain["entry"]["id"],
                                      BEVERAGE_DIRECTOR_HEADERS))
        assertions.assert_decimal_equals(entry["contest_points"], 0.00,
                                         "ListEntry.contest_points")


def _confirmed_dinner_on_two_entry_list():
    """Venue + two lots + a PUBLISHED version carrying one bottle-only entry
    per wine + a 24-seat dinner pinned to that version, PRICED and CONFIRMED."""
    fx.set_clock(CLOCK)
    venue = _harbor_room()
    bin_ = fx.create_bin(venue, bin_code="A1", zone="CELLAR",
                         capacity_bottles=48, temperature_controlled=True)
    wine_a = _monte_bello()
    wine_b = fx.create_wine(producer="Kistler", cuvee="Les Noisetiers",
                            vintage_year=2019, category="WHITE",
                            reference_cost_cents=6000, bottle_size_ml=750,
                            case_pack=6, is_allocated=False)
    lot_a = fx.create_lot(venue, wine_a, bin_, bottles_received=12,
                          unit_cost_cents=2400,
                          received_at="2026-08-10T00:00:00Z")
    lot_b = fx.create_lot(venue, wine_b, bin_, bottles_received=6,
                          unit_cost_cents=6000,
                          received_at="2026-08-10T00:00:00Z")
    wine_list = fx.create_wine_list(venue, name="Dinner List")
    draft = fx.create_draft_version(wine_list, venue)
    entry_a = fx.add_entry(draft, wine_a, venue, sort_rank=1,
                           by_the_glass=False, par_bottles=6,
                           education_verified=False)
    entry_b = fx.add_entry(draft, wine_b, venue, sort_rank=2,
                           by_the_glass=False, par_bottles=6,
                           education_verified=False)
    version = fx.publish_version(draft, venue)
    event = fx.create_event(venue, version,
                            [f.pour_plan_line(entry_a["id"], 2)],
                            name="Library Dinner",
                            starts_at="2026-10-10T18:00:00Z",
                            ends_at="2026-10-10T21:00:00Z",
                            seat_count=24)
    fx.price_event(event, venue)
    confirmed = fx.confirm_event(event)
    return {"venue": venue, "bin": bin_, "wine_a": wine_a, "wine_b": wine_b,
            "lot_a": lot_a, "lot_b": lot_b, "wine_list": wine_list,
            "version": version, "entry_a": entry_a, "entry_b": entry_b,
            "event": confirmed}


def _new_vintage_of_a(wine_a):
    return _monte_bello(vintage_year=2020, predecessor_wine_id=wine_a["id"])


def _new_vintage_of_b(wine_b):
    return fx.create_wine(producer="Kistler", cuvee="Les Noisetiers",
                          vintage_year=2023, category="WHITE",
                          reference_cost_cents=6000, bottle_size_ml=750,
                          case_pack=6, is_allocated=False,
                          predecessor_wine_id=wine_b["id"])


def _read(getter, entity_id):
    return validate_success(getter(entity_id, BEVERAGE_DIRECTOR_HEADERS))


class TestVintageChangeCascade:
    """A new catalogue vintage run down the catalogue spine: successor count,
    entry staleness, the version's stale count and reprint obligation, the
    threshold that flips a live version to REPRINT_PENDING, and the pinned
    flag that blocks a confirmed dinner's settlement for good."""

    def test_first_new_vintage_stales_one_entry_and_stops_below_the_threshold(self):
        """One superseded vintage on a live list is an errata: the entry goes
        stale and the version counts it, but reprint_required stays false, the
        version stays PUBLISHED and the pinned dinner is unaffected.

        "Each affected version recounts its `stale_entry_count` and rewrites `reprint_required`, which is true exactly when the stale count has reached two entries and false below that."

        Design: Difficulty/transitive_cascade/vintage_change_cascades_stale_entries_to_reprint_and_pinned_event
        """
        chain = _confirmed_dinner_on_two_entry_list()

        _new_vintage_of_a(chain["wine_a"])

        wine_a = _read(api_client.get_wine, chain["wine_a"]["id"])
        assert wine_a["successor_count"] == 1, (
            "the predecessor must count its one successor")
        entry_a = _read(api_client.get_list_entry, chain["entry_a"]["id"])
        assert entry_a["vintage_stale"] is True, (
            "the live entry for the predecessor wine is now stale")

        version = _read(api_client.get_list_version, chain["version"]["id"])
        assertions.assert_fields_equal(version, {
            "stale_entry_count": 1,
            "reprint_required": False,
            "state": "PUBLISHED",
        }, "ListVersion")

        event = _read(api_client.get_wine_dinner_event, chain["event"]["id"])
        assert event["pinned_version_stale"] is False, (
            "a version that never left PUBLISHED cannot stale a pinned event")

    def test_second_new_vintage_forces_a_reprint_and_stales_the_pinned_dinner(self):
        """The second superseded vintage reaches the two-entry threshold, so
        the live version moves PUBLISHED -> REPRINT_PENDING and that transition
        stales the confirmed dinner pinned to it.

        "A version that is currently `PUBLISHED` and whose `reprint_required` has just become true moves `PUBLISHED → REPRINT_PENDING`, and that transition sets `pinned_version_stale` to true on every wine dinner event in state `PLANNED`, `PRICED` or `CONFIRMED` that pins it."

        Design: Difficulty/transitive_cascade/vintage_change_cascades_stale_entries_to_reprint_and_pinned_event
        """
        chain = _confirmed_dinner_on_two_entry_list()

        _new_vintage_of_a(chain["wine_a"])
        _new_vintage_of_b(chain["wine_b"])

        wine_b = _read(api_client.get_wine, chain["wine_b"]["id"])
        assert wine_b["successor_count"] == 1, (
            "the second predecessor must count its one successor")
        entry_b = _read(api_client.get_list_entry, chain["entry_b"]["id"])
        assert entry_b["vintage_stale"] is True, (
            "the second live entry is now stale too")

        version = _read(api_client.get_list_version, chain["version"]["id"])
        assertions.assert_fields_equal(version, {
            "stale_entry_count": 2,
            "reprint_required": True,
            "state": "REPRINT_PENDING",
        }, "ListVersion")

        event = _read(api_client.get_wine_dinner_event, chain["event"]["id"])
        assertions.assert_fields_equal(event, {
            "pinned_version_stale": True,
            "state": "CONFIRMED",
        }, "WineDinnerEvent")

    def test_stale_pin_blocks_settlement_and_draws_no_bottles(self):
        """Settling the dinner whose pinned version slipped to REPRINT_PENDING
        is refused, and the refusal leaves the lot and both venue ledgers
        exactly where they were.

        "Settlement is controller-exclusive and requires the event to be in `CONFIRMED` (`ERR_EVENT_INVALID_STATE`) with `pinned_version_stale` false; a pinned version that has left `PUBLISHED` since confirmation — because it went to `REPRINT_PENDING`, was superseded or was archived — blocks settlement with `ERR_PINNED_LIST_VERSION_STALE` (HTTP 409)."

        Design: Difficulty/transitive_cascade/vintage_change_cascades_stale_entries_to_reprint_and_pinned_event
        """
        chain = _confirmed_dinner_on_two_entry_list()
        _new_vintage_of_a(chain["wine_a"])
        _new_vintage_of_b(chain["wine_b"])

        response = api_client.settle_event(chain["event"]["id"],
                                          CONTROLLER_HEADERS)

        validate_error(response, ERR_PINNED_LIST_VERSION_STALE)
        event = _read(api_client.get_wine_dinner_event, chain["event"]["id"])
        assert event["state"] == "CONFIRMED", (
            "a refused settlement leaves the event CONFIRMED")
        lot_a = _read(api_client.get_inventory_lot, chain["lot_a"]["id"])
        assert lot_a["bottles_on_hand"] == 12, (
            "no bottle may be drawn by a refused settlement")
        venue = fx.get_venue(chain["venue"])
        assertions.assert_fields_equal(venue, {
            "cogs_ledger_cents": 0,
            "revenue_ledger_cents": 0,
        }, "Venue")

    def test_marking_the_reprint_clears_every_entry_and_both_counters(self):
        """Acknowledging the new paper returns the version to PUBLISHED and
        wipes the staleness it accumulated: both entries clean, stale count 0,
        reprint_required false.

        "It stamps `printed_at` with the logical clock, clears `vintage_stale` to false on every entry of the version, resets `stale_entry_count` to 0 and sets `reprint_required` back to false."

        Design: Difficulty/transitive_cascade/vintage_change_cascades_stale_entries_to_reprint_and_pinned_event
        """
        chain = _confirmed_dinner_on_two_entry_list()
        _new_vintage_of_a(chain["wine_a"])
        _new_vintage_of_b(chain["wine_b"])

        reprinted = validate_success(api_client.mark_reprinted_list_version(
            chain["version"]["id"], sommelier_headers(chain["venue"]["id"])))

        assertions.assert_fields_equal(reprinted, {
            "state": "PUBLISHED",
            "stale_entry_count": 0,
            "reprint_required": False,
        }, "ListVersion")
        _assert_instant(reprinted["printed_at"], "2026-09-01T12:00:00",
                        "ListVersion.printed_at")
        for key in ("entry_a", "entry_b"):
            entry = _read(api_client.get_list_entry, chain[key]["id"])
            assert entry["vintage_stale"] is False, (
                "%s must be clean after the reprint acknowledgement" % key)

    def test_reprint_never_un_stales_the_pinned_dinner(self):
        """The dinner's pinned promise was made about one printed list at one
        moment, so reprinting the list leaves the flag set and settlement
        refused for good.

        "Any wine dinner whose `pinned_version_stale` was already set to true keeps that flag, and its settlement stays blocked, even after the list itself returns to `PUBLISHED`."

        Design: Difficulty/transitive_cascade/vintage_change_cascades_stale_entries_to_reprint_and_pinned_event
        """
        chain = _confirmed_dinner_on_two_entry_list()
        _new_vintage_of_a(chain["wine_a"])
        _new_vintage_of_b(chain["wine_b"])
        validate_success(api_client.mark_reprinted_list_version(
            chain["version"]["id"], sommelier_headers(chain["venue"]["id"])))

        response = api_client.settle_event(chain["event"]["id"],
                                          CONTROLLER_HEADERS)

        validate_error(response, ERR_PINNED_LIST_VERSION_STALE)
        event = _read(api_client.get_wine_dinner_event, chain["event"]["id"])
        assert event["pinned_version_stale"] is True, (
            "the reprint acknowledgement must not clear a pinned event's flag")
        assert event["state"] == "CONFIRMED", (
            "the event stays CONFIRMED behind the blocked settlement")
