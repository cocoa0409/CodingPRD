"""Dual-variant calculations: the same inputs costed two ways.

Two families of arithmetic in this API deliberately produce two different
numbers from byte-identical inputs.  A wine-dinner settlement priced under
``FIFO`` books the actual unit costs of the oldest lots while the same draw
under ``WEIGHTED_AVERAGE`` books a single blended unit, and a pour-cost run
splits one ledger population into an *actual* percentage that counts every
reason against a *theoretical* percentage that counts only the sale reasons.

Every test here starts from an empty database and builds its whole chain
through published endpoints.
"""
from prd_bench_local_runner.testing import validate_success

from test_helpers import assertions, factories as f, fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.test_users import BEVERAGE_DIRECTOR_HEADERS, CONTROLLER_HEADERS

CLOCK = "2026-09-01T12:00:00Z"

# RED 28.0 is the category target every entry below is priced against; WHITE
# 25.0 keeps the six-key requirement satisfied with a distinguishable value.
_TARGETS = f.cogs_targets(SPARKLING=30.0, WHITE=25.0, ROSE=28.0, RED=28.0,
                          DESSERT=32.0, FORTIFIED=35.0)


def _assert_instant(actual, expected_prefix, field="timestamp"):
    """Compare a server-minted instant against a whole-second literal.

    The PRD mints timestamps with three fractional digits, so the recipe's
    ``2026-09-01T12:00:00Z`` literal is matched on its whole-second prefix.
    """
    assert actual is not None, "%s must not be null" % field
    assert str(actual).startswith(expected_prefix), (
        "%s expected the instant %sZ, got %r" % (field, expected_prefix, actual))


def _venue(costing_method="FIFO", priority_rank=1):
    return fx.create_venue(cogs_target_pct_by_category=dict(_TARGETS),
                           costing_method=costing_method,
                           event_cogs_target_pct=28.0,
                           corkage_fee_cents=3500,
                           corkage_waiver_purchase_ratio=2,
                           byo_bottle_limit_per_party=2,
                           byo_prohibited_categories=["SPARKLING"],
                           priority_rank=priority_rank)


def _red_wine():
    return fx.create_wine(producer="Ridge", cuvee="Monte Bello",
                          vintage_year=2019, category="RED",
                          reference_cost_cents=2400, bottle_size_ml=750,
                          case_pack=6, is_allocated=False)


def _confirmed_event(costing_method, priority_rank, wine):
    """Venue + two lots (6 @ 3000 then 6 @ 5000) + published list + CONFIRMED
    24-seat dinner asking 2 pours per seat of the single bottle-only entry."""
    venue = _venue(costing_method, priority_rank)
    bin_ = fx.create_bin(venue, bin_code="A1", zone="CELLAR",
                         capacity_bottles=48, temperature_controlled=True)
    lot_old = fx.create_lot(venue, wine, bin_, bottles_received=6,
                            unit_cost_cents=3000,
                            received_at="2026-08-10T00:00:00Z")
    lot_new = fx.create_lot(venue, wine, bin_, bottles_received=6,
                            unit_cost_cents=5000,
                            received_at="2026-08-20T00:00:00Z")
    draft = fx.setup_draft_version(venue)
    entry = fx.add_entry(draft["version"], wine, venue, sort_rank=1,
                         by_the_glass=False, par_bottles=6,
                         tasting_note="Cassis, graphite, long finish.",
                         education_verified=True)
    version = fx.publish_version(draft["version"], venue)
    event = fx.create_event(venue, version, [f.pour_plan_line(entry["id"], 2)],
                            name="Cabernet Dinner",
                            starts_at="2026-10-10T18:00:00Z",
                            ends_at="2026-10-10T21:00:00Z",
                            seat_count=24)
    priced = fx.price_event(event, venue)
    confirmed = fx.confirm_event(event)
    return {"venue": venue, "bin": bin_, "lot_old": lot_old, "lot_new": lot_new,
            "entry": entry, "priced": priced, "event": confirmed}


def _settle(event):
    return validate_success(api_client.settle_event(event["id"], CONTROLLER_HEADERS))


def _event_ledger(event_id, lot_id=None):
    """The EVENT ledger rows of one settlement, optionally narrowed to one lot.

    Two rows written by the same settlement can share a created_at millisecond,
    so a row is identified by the lot it drew from rather than by its position.
    """
    filters = {"event_id": event_id}
    if lot_id is not None:
        filters["lot_id"] = lot_id
    return assertions.depletion_entries_for(BEVERAGE_DIRECTOR_HEADERS, **filters)


def _only(rows, description):
    assert len(rows) == 1, (
        "expected exactly one %s, got %d" % (description, len(rows)))
    return rows[0]


class TestEventSettlementCostingMethod:
    """One 24-seat dinner drawing 8 bottles across two lots of unequal unit
    cost, settled once in a FIFO venue and once in a WEIGHTED_AVERAGE venue."""

    def test_fifo_settlement_books_the_actual_unit_costs_of_the_lots_it_walks(self):
        """A FIFO venue books 28000 cents for 6 bottles at 3000 plus 2 at 5000.

        "Under `FIFO`, walk that order taking from each lot the smaller of what it has available and what remains to be drawn, and the cost of goods is the sum over the lots touched of bottles taken from that lot multiplied by that lot's `unit_cost_cents`; no rounding is needed."

        Design: Difficulty/dual_variant_calc/fifo_vs_weighted_average_event_settlement_cogs
        """
        fx.set_clock(CLOCK)
        wine = _red_wine()
        chain = _confirmed_event("FIFO", 1, wine)
        assert chain["priced"]["final_ticket_price_cents"] == 3000

        settled = _settle(chain["event"])

        assert settled["state"] == "SETTLED"
        assert settled["settled_cogs_cents"] == 28000
        assert settled["settled_revenue_cents"] == 72000

        venue = fx.get_venue(chain["venue"])
        assert venue["cogs_ledger_cents"] == 28000
        assert venue["revenue_ledger_cents"] == 72000

        old_lot = fx.get_success_data(
            api_client.get_inventory_lot(chain["lot_old"]["id"],
                                         BEVERAGE_DIRECTOR_HEADERS))
        new_lot = fx.get_success_data(
            api_client.get_inventory_lot(chain["lot_new"]["id"],
                                         BEVERAGE_DIRECTOR_HEADERS))
        assert old_lot["bottles_on_hand"] == 0
        assert old_lot["state"] == "DEPLETED"
        assert new_lot["bottles_on_hand"] == 4
        assert new_lot["state"] == "ON_HAND"

        entries = _event_ledger(chain["event"]["id"])
        assert len(entries) == 2, (
            "expected one EVENT entry per consumed lot, got %d" % len(entries))
        assert [row["reason"] for row in entries] == ["EVENT", "EVENT"]
        oldest = _only(_event_ledger(chain["event"]["id"],
                                    chain["lot_old"]["id"]),
                       "EVENT entry against the 3000-cent lot")
        newest = _only(_event_ledger(chain["event"]["id"],
                                    chain["lot_new"]["id"]),
                       "EVENT entry against the 5000-cent lot")
        assert (oldest["bottles"], oldest["cogs_cents"]) == (6, 18000)
        assert (newest["bottles"], newest["cogs_cents"]) == (2, 10000)
        # The whole settled revenue is booked on the first entry only, and the
        # first entry is the one drawn from the earliest received lot.
        assert oldest["revenue_cents"] == 72000
        assert newest["revenue_cents"] == 0

    def test_weighted_average_settlement_books_one_blended_unit_for_every_bottle(self):
        """A WEIGHTED_AVERAGE venue blends 3000 and 5000 into 4000 and books 32000.

        "Under `WEIGHTED_AVERAGE`, first compute a blended unit cost over the whole candidate set *before* any bottle is drawn — the sum over candidates of available bottles multiplied by that lot's `unit_cost_cents`, divided by the total available bottles, rounded half up to whole cents — and then charge the number of bottles consumed at that single blended unit."

        Design: Difficulty/dual_variant_calc/fifo_vs_weighted_average_event_settlement_cogs
        """
        fx.set_clock(CLOCK)
        wine = _red_wine()
        chain = _confirmed_event("WEIGHTED_AVERAGE", 2, wine)
        assert chain["priced"]["final_ticket_price_cents"] == 3000

        settled = _settle(chain["event"])

        assert settled["settled_cogs_cents"] == 32000
        assert settled["settled_revenue_cents"] == 72000

        venue = fx.get_venue(chain["venue"])
        assert venue["cogs_ledger_cents"] == 32000
        assert venue["revenue_ledger_cents"] == 72000

        old_lot = fx.get_success_data(
            api_client.get_inventory_lot(chain["lot_old"]["id"],
                                         BEVERAGE_DIRECTOR_HEADERS))
        new_lot = fx.get_success_data(
            api_client.get_inventory_lot(chain["lot_new"]["id"],
                                         BEVERAGE_DIRECTOR_HEADERS))
        assert old_lot["bottles_on_hand"] == 0
        assert new_lot["bottles_on_hand"] == 4

        entries = _event_ledger(chain["event"]["id"])
        assert len(entries) == 2
        oldest = _only(_event_ledger(chain["event"]["id"],
                                    chain["lot_old"]["id"]),
                       "EVENT entry against the 3000-cent lot")
        newest = _only(_event_ledger(chain["event"]["id"],
                                    chain["lot_new"]["id"]),
                       "EVENT entry against the 5000-cent lot")
        # Both draws are charged at the single blended unit of 4000 cents.
        assert (oldest["bottles"], oldest["cogs_cents"]) == (6, 24000)
        assert (newest["bottles"], newest["cogs_cents"]) == (2, 8000)

    def test_costing_method_alone_moves_the_settled_cogs_by_four_thousand_cents(self):
        """Two venues with identical cellars and identical dinners diverge by 4000 cents.

        "The physical draw still follows the same `received_at` ascending order in both variants; only the costing differs, so whenever the candidate lots disagree on `unit_cost_cents` the two methods produce different figures for the same draw."

        Design: Difficulty/dual_variant_calc/fifo_vs_weighted_average_event_settlement_cogs
        """
        fx.set_clock(CLOCK)
        wine = _red_wine()
        fifo = _confirmed_event("FIFO", 1, wine)
        weighted = _confirmed_event("WEIGHTED_AVERAGE", 2, wine)

        fifo_settled = _settle(fifo["event"])
        weighted_settled = _settle(weighted["event"])

        assert fifo_settled["settled_revenue_cents"] == 72000
        assert weighted_settled["settled_revenue_cents"] == 72000
        assert (weighted_settled["settled_cogs_cents"]
                - fifo_settled["settled_cogs_cents"]) == 4000
        assert fifo_settled["settled_cogs_cents"] == 28000
        assert weighted_settled["settled_cogs_cents"] == 32000


PERIOD_START = "2026-09-01T00:00:00Z"
PERIOD_END = "2026-09-02T00:00:00Z"


def _two_closed_slots():
    """A venue whose ledger carries three entries from two closed rail bottles:
    SALE_BTG 3 pours, SALE_BTG 2 pours and STAFF_EDUCATION 1 pour."""
    fx.set_clock(CLOCK)
    venue = _venue("FIFO", 1)
    wine = _red_wine()
    chain = fx.setup_published_entry(
        venue=venue, wine=wine, by_the_glass=True, pour_size_ml=177,
        bottles_received=12, unit_cost_cents=2400,
        received_at="2026-08-10T00:00:00Z",
        bin_overrides={"bin_code": "A1", "zone": "CELLAR",
                       "capacity_bottles": 48},
        entry_overrides={"par_bottles": 6,
                         "tasting_note": "Cassis and graphite.",
                         "education_verified": False})
    first = fx.open_slot(venue, chain["entry"], chain["lot"], slot_index=1)
    fx.close_slot(first, venue, pours_sold=3, staff_education_pours=0)
    second = fx.open_slot(venue, chain["entry"], chain["lot"], slot_index=2)
    fx.close_slot(second, venue, pours_sold=2, staff_education_pours=1)
    chain["first_slot"] = first
    chain["second_slot"] = second
    return chain


def _slot_ledger(slot_id, reason=None):
    """The ledger rows of one slot closure, optionally narrowed to one reason.

    A closure appends its buckets within a single millisecond, so a row is
    identified by its reason rather than by its position in the collection.
    """
    filters = {"btg_slot_id": slot_id}
    if reason is not None:
        filters["reason"] = reason
    return assertions.depletion_entries_for(BEVERAGE_DIRECTOR_HEADERS, **filters)


class TestPourCostActualVersusTheoretical:
    """One ledger population of three entries, split into the all-reason actual
    population and the sale-only theoretical population."""

    def test_actual_population_counts_the_staff_education_cost_against_no_revenue(self):
        """The actual side totals 4800 cents of cost over 14375 of revenue, 33.39 percent.

        "The **actual** population is every ledger entry for the venue in the window, whatever its reason, taken with its signed values — so spoilage, staff education and reversal entries all count, the last of them negatively."

        Design: Difficulty/dual_variant_calc/actual_vs_theoretical_pour_cost_variance
        """
        chain = _two_closed_slots()
        entry = fx.get_success_data(
            api_client.get_list_entry(chain["entry"]["id"],
                                      BEVERAGE_DIRECTOR_HEADERS))
        assert entry["effective_pours"] == 3
        assert entry["glass_price_cents"] == 2875

        report = fx.pour_cost_report(chain["venue"], PERIOD_START, PERIOD_END)

        assert report["actual_cogs_cents"] == 4800
        assert report["actual_revenue_cents"] == 14375
        assertions.assert_decimal_equals(report["actual_pour_cost_pct"], 33.39,
                                        "actual_pour_cost_pct")
        assert report["entry_count"] == 3

        ledger = assertions.depletion_entries_for(
            BEVERAGE_DIRECTOR_HEADERS, list_entry_id=chain["entry"]["id"])
        assert len(ledger) == 3, (
            "expected three ledger entries for the listing, got %d" % len(ledger))
        first_sale = _only(_slot_ledger(chain["first_slot"]["id"]),
                           "ledger row for the first slot")
        assert (first_sale["reason"], first_sale["pours"],
                first_sale["cogs_cents"], first_sale["revenue_cents"]) == (
            "SALE_BTG", 3, 2400, 8625)
        assert len(_slot_ledger(chain["second_slot"]["id"])) == 2
        second_sale = _only(
            _slot_ledger(chain["second_slot"]["id"], "SALE_BTG"),
            "SALE_BTG row for the second slot")
        assert (second_sale["pours"], second_sale["cogs_cents"],
                second_sale["revenue_cents"]) == (2, 1600, 5750)
        education = _only(
            _slot_ledger(chain["second_slot"]["id"], "STAFF_EDUCATION"),
            "STAFF_EDUCATION row for the second slot")
        assert (education["pours"], education["cogs_cents"],
                education["revenue_cents"]) == (1, 800, 0)

        lot = fx.get_success_data(
            api_client.get_inventory_lot(chain["lot"]["id"],
                                         BEVERAGE_DIRECTOR_HEADERS))
        assert lot["bottles_on_hand"] == 10
        assert lot["bottles_committed"] == 0
        assert lot["state"] == "ON_HAND"

    def test_theoretical_population_drops_the_staff_education_entry(self):
        """The theoretical side keeps only the two SALE_BTG entries, 4000 over 14375.

        "The **theoretical** population is the same window restricted to entries whose reason is `SALE_BTG`, `SALE_BOTTLE` or `EVENT`, which is what the recorded sales should have cost."

        Design: Difficulty/dual_variant_calc/actual_vs_theoretical_pour_cost_variance
        """
        chain = _two_closed_slots()

        report = fx.pour_cost_report(chain["venue"], PERIOD_START, PERIOD_END)

        assert report["theoretical_cogs_cents"] == 4000
        assert report["theoretical_revenue_cents"] == 14375
        assertions.assert_decimal_equals(report["theoretical_pour_cost_pct"],
                                        27.83, "theoretical_pour_cost_pct")
        assert report["theoretical_revenue_cents"] == report["actual_revenue_cents"]

    def test_variance_is_the_difference_of_the_two_rounded_percentages(self):
        """33.39 less 27.83 is a 5.56-point spread, which restricts the venue and
        opens an investigation.

        "The variance is then the theoretical percentage subtracted from the actual percentage and rounded half up to two decimals again — computed from the two **already-rounded** percentages, not from the raw ratios."

        Design: Difficulty/dual_variant_calc/actual_vs_theoretical_pour_cost_variance
        """
        chain = _two_closed_slots()
        report = fx.pour_cost_report(chain["venue"], PERIOD_START, PERIOD_END)
        assertions.assert_decimal_equals(report["variance_pct"], 5.56,
                                        "variance_pct")

        venue = fx.run_pour_cost(chain["venue"], PERIOD_START, PERIOD_END)

        assertions.assert_decimal_equals(venue["last_variance_pct"], 5.56,
                                        "last_variance_pct")
        assert venue["program_posture"] == "RESTRICTED"
        _assert_instant(venue["last_pour_cost_run_at"], "2026-09-01T12:00:00",
                        "last_pour_cost_run_at")
        assert venue["cogs_ledger_cents"] == 4800
        assert venue["revenue_ledger_cents"] == 14375

        investigations = fx.open_investigations(chain["venue"])
        assert len(investigations) == 1, (
            "expected exactly one variance investigation, got %d"
            % len(investigations))
        opened = investigations[0]
        assert opened["state"] == "OPEN"
        assertions.assert_decimal_equals(opened["triggered_variance_pct"], 5.56,
                                        "triggered_variance_pct")
        _assert_instant(opened["period_start"], "2026-09-01T00:00:00",
                        "period_start")
        _assert_instant(opened["period_end"], "2026-09-02T00:00:00", "period_end")

    def test_realised_cost_above_target_clamps_the_contest_margin_factor_to_zero(self):
        """The listing scores 5.00 — one point per pour sold and no margin credit.

        "When total revenue is greater than zero, express realised cost of goods as a percentage — total cost multiplied by 100, divided by total revenue, rounded half up to two decimals — then take the venue's category target for this wine, subtract the realised percentage from it, divide the difference by that same target, clamp the result to no less than 0.0 and no more than 1.0, and round half up to four decimals; that clamped figure is the margin factor."

        Design: Difficulty/dual_variant_calc/actual_vs_theoretical_pour_cost_variance
        """
        chain = _two_closed_slots()

        entry = fx.get_success_data(
            api_client.get_list_entry(chain["entry"]["id"],
                                      BEVERAGE_DIRECTOR_HEADERS))

        assertions.assert_decimal_equals(entry["contest_points"], 5.00,
                                        "contest_points")
        assertions.assert_two_decimal_places(entry["contest_points"],
                                            "contest_points")
