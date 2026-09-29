"""Transitions whose blocking state lives on a different entity.

Two shapes appear here.  A wine dinner reaches `PRICED` while its venue is
`OPEN`, an unrelated by-the-glass closure plus a pour-cost run flips the venue
to `FROZEN`, and only then does confirmation fail -- the event's own state
machine still permits the move, so the refusal is decided entirely by the
venue.  A by-the-glass slot names a list entry, and the gate is on that entry's
list version being live -- a dependency two hops up the tree.  In both cases the
identical, unmodified request succeeds once the other entity reaches its
enabling state, which is what proves the gate reads live state.
"""
from datetime import datetime

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import (
    ERR_LIST_VERSION_NOT_PUBLISHED,
    ERR_VENUE_PROGRAM_FROZEN,
)
from test_helpers.assertions import (
    assert_decimal_equals,
    assert_fields_equal,
    depletion_entries_for,
)
from test_helpers.test_users import (
    BEVERAGE_DIRECTOR_HEADERS,
    CONTROLLER_HEADERS,
    sommelier_headers,
)

_CATEGORY_TARGETS = f.cogs_targets(
    30.0, WHITE=25.0, ROSE=28.0, RED=28.0, DESSERT=32.0, FORTIFIED=35.0)

_PERIOD_START = "2026-09-01T00:00:00Z"
_PERIOD_END = "2026-09-02T00:00:00Z"


def _instant(value):
    """Parse a server-minted ISO 8601 instant, tolerating the fractional digits."""
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _harbor_room(**overrides):
    fx.set_clock("2026-09-01T12:00:00Z")
    return fx.create_venue(name="Harbor Room", venue_code="HRB",
                           cogs_target_pct_by_category=_CATEGORY_TARGETS,
                           priority_rank=1, **overrides)


def _red_wine():
    return fx.create_wine(producer="Ridge", cuvee="Monte Bello", vintage_year=2019,
                          category="RED", reference_cost_cents=2400,
                          bottle_size_ml=750, case_pack=6, is_allocated=False)


def _slot_response(venue, entry, lot, slot_index=1):
    """POST a by-the-glass slot and return the raw response (refusals included)."""
    venue_id = venue["id"]
    payload = f.btg_slot_payload(venue_id, entry["id"], lot["id"], slot_index,
                                 "ARGON")
    return api_client.create_btg_slot(payload, sommelier_headers(venue_id))


def _priced_dinner_at_an_open_venue():
    """Published by-the-glass RED entry plus a 24-seat dinner priced while OPEN."""
    venue = _harbor_room(event_cogs_target_pct=28.0)
    chain = fx.setup_published_entry(
        venue=venue, wine=_red_wine(), by_the_glass=True, pour_size_ml=177,
        bottles_received=12, unit_cost_cents=2400,
        received_at="2026-08-10T00:00:00Z",
        entry_overrides={"par_bottles": 6, "education_verified": False})
    event = fx.create_event(
        venue, chain["version"], [f.pour_plan_line(chain["entry"]["id"], 2)],
        name="Ridge Vertical", starts_at="2026-10-10T18:00:00Z",
        ends_at="2026-10-10T21:00:00Z", seat_count=24)
    chain["event"] = fx.price_event(event, venue)
    return chain


def _freeze_the_venue_through_a_pour_cost_run(chain):
    """Sell two glasses and pour one education glass, then run the variance."""
    venue = chain["venue"]
    slot = fx.open_slot(venue, chain["entry"], chain["lot"])
    fx.close_slot(slot, venue, pours_sold=2, staff_education_pours=1)
    return fx.run_pour_cost(venue, _PERIOD_START, _PERIOD_END)


class TestEventConfirmationReadsLiveVenuePosture:
    """The dinner is priced while the venue is `OPEN`; a later variance run
    freezes the venue and the same confirmation is refused, then permitted again
    once an adjusted resolution thaws the venue."""

    def test_confirmation_is_refused_once_a_variance_run_freezes_the_venue(self):
        """A dinner priced at an OPEN venue cannot be confirmed after the venue freezes.

        "It requires the event to be in `PRICED` (`ERR_EVENT_INVALID_STATE`), the `final_ticket_price_cents` to be present rather than null, the pinned list version to be in `PUBLISHED` or `REPRINT_PENDING` (`ERR_LIST_VERSION_NOT_PUBLISHED`), and the venue's posture not to be `FROZEN` (`ERR_VENUE_PROGRAM_FROZEN`)."

        Design: Difficulty/cross_entity_state_dependency/event_confirm_blocked_by_venue_posture_frozen_after_pricing
        """
        chain = _priced_dinner_at_an_open_venue()
        event = chain["event"]
        assert_fields_equal(event, {"state": "PRICED",
                                    "final_ticket_price_cents": 3000},
                            name="priced event")
        assert_decimal_equals(event["projected_pour_cost_pct"], 26.67,
                              field="projected_pour_cost_pct")
        assert fx.get_venue(chain["venue"])["program_posture"] == "OPEN", (
            "the venue must be OPEN at pricing time")

        frozen_venue = _freeze_the_venue_through_a_pour_cost_run(chain)
        assert frozen_venue["program_posture"] == "FROZEN", (
            "the variance run must freeze the venue, got %r"
            % (frozen_venue["program_posture"],))

        validate_error(api_client.confirm_event(event["id"],
                                               BEVERAGE_DIRECTOR_HEADERS),
                       ERR_VENUE_PROGRAM_FROZEN)

        after = validate_success(api_client.get_wine_dinner_event(
            event["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert_fields_equal(after, {"state": "PRICED",
                                    "final_ticket_price_cents": 3000},
                            name="event after the refusal")

    def test_the_freezing_run_pins_the_variance_and_opens_one_investigation(self):
        """The closure's own ledger drives the variance to 13.91 points and opens one file.

        "The variance is then the theoretical percentage subtracted from the actual percentage and rounded half up to two decimals again — computed from the two **already-rounded** percentages, not from the raw ratios."

        Design: Difficulty/cross_entity_state_dependency/event_confirm_blocked_by_venue_posture_frozen_after_pricing
        """
        chain = _priced_dinner_at_an_open_venue()
        venue = chain["venue"]
        slot = fx.open_slot(venue, chain["entry"], chain["lot"])
        fx.close_slot(slot, venue, pours_sold=2, staff_education_pours=1)

        entries = depletion_entries_for(CONTROLLER_HEADERS, venue_id=venue["id"])
        assert [row["reason"] for row in entries] == ["SALE_BTG", "STAFF_EDUCATION"], (
            "a zero spoilage bucket writes no entry: %r"
            % ([row["reason"] for row in entries],))
        assert_fields_equal(entries[0], {"bottles": 1, "pours": 2,
                                         "cogs_cents": 1600,
                                         "revenue_cents": 5750},
                            name="SALE_BTG entry")
        assert_fields_equal(entries[1], {"bottles": 0, "pours": 1,
                                         "cogs_cents": 800,
                                         "revenue_cents": 0},
                            name="STAFF_EDUCATION entry")

        report = fx.pour_cost_report(venue, _PERIOD_START, _PERIOD_END)
        assert_decimal_equals(report["actual_pour_cost_pct"], 41.74,
                              field="actual_pour_cost_pct")
        assert_decimal_equals(report["theoretical_pour_cost_pct"], 27.83,
                              field="theoretical_pour_cost_pct")
        assert_decimal_equals(report["variance_pct"], 13.91, field="variance_pct")

        updated = fx.run_pour_cost(venue, _PERIOD_START, _PERIOD_END)
        assert_decimal_equals(updated["last_variance_pct"], 13.91,
                              field="last_variance_pct")
        assert updated["program_posture"] == "FROZEN"

        files = fx.open_investigations(venue)
        assert len(files) == 1, (
            "the run must open exactly one investigation, got %d" % (len(files),))
        assert files[0]["state"] == "OPEN"
        assert_decimal_equals(files[0]["triggered_variance_pct"], 13.91,
                              field="triggered_variance_pct")

    def test_an_adjusted_resolution_thaws_the_venue_and_the_same_confirm_succeeds(self):
        """The identical confirmation succeeds once the file is resolved as adjusted.

        "An `ADJUSTED` resolution declares the variance an accounting artefact: `last_variance_pct` is reset to 0.00 and the posture is recomputed, which returns the venue to `OPEN` provided no other escalated investigation for that venue remains."

        Design: Difficulty/cross_entity_state_dependency/event_confirm_blocked_by_venue_posture_frozen_after_pricing
        """
        chain = _priced_dinner_at_an_open_venue()
        event = chain["event"]
        venue = chain["venue"]
        _freeze_the_venue_through_a_pour_cost_run(chain)
        validate_error(api_client.confirm_event(event["id"],
                                               BEVERAGE_DIRECTOR_HEADERS),
                       ERR_VENUE_PROGRAM_FROZEN)

        files = fx.open_investigations(venue)
        resolved = fx.resolve_investigation(
            files[-1], "ADJUSTED",
            "Education pours recoded to the training budget.")
        assert resolved["state"] == "RESOLVED_ADJUSTED"

        thawed = fx.get_venue(venue)
        assert thawed["program_posture"] == "OPEN", (
            "an adjusted resolution must return the venue to OPEN, got %r"
            % (thawed["program_posture"],))
        assert_decimal_equals(thawed["last_variance_pct"], 0.00,
                              field="last_variance_pct")

        confirmed = validate_success(api_client.confirm_event(
            event["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert_fields_equal(confirmed, {"state": "CONFIRMED",
                                        "final_ticket_price_cents": 3000},
                            name="confirmed event")


def _draft_entry_with_stock():
    """A by-the-glass RED entry on a DRAFT version, with a 12-bottle lot behind it."""
    venue = _harbor_room()
    wine = _red_wine()
    bin_ = fx.create_bin(venue, bin_code="A1", zone="CELLAR",
                         capacity_bottles=48, temperature_controlled=True)
    lot = fx.create_lot(venue, wine, bin_, bottles_received=12,
                        unit_cost_cents=2400, received_at="2026-08-10T00:00:00Z")
    drafted = fx.setup_draft_version(venue)
    entry = fx.add_entry(drafted["version"], wine, venue, sort_rank=1,
                         by_the_glass=True, pour_size_ml=177, par_bottles=6,
                         education_verified=False)
    return {"venue": venue, "wine": wine, "bin": bin_, "lot": lot,
            "version": drafted["version"], "entry": entry}


class TestBtgSlotRequiresALiveGrandparentVersion:
    """A slot names a list entry, and the enabling state sits on that entry's
    list version.  Nothing about the slot payload is wrong, so the refusal is
    purely relational -- and the same payload is accepted once the ancestor is
    published."""

    def test_a_slot_against_a_draft_parent_version_is_refused(self):
        """A rail slot cannot be opened while the entry's version is still a draft.

        "The list version behind the entry must be live, meaning in `PUBLISHED` or `REPRINT_PENDING`; anything else is `ERR_LIST_VERSION_NOT_PUBLISHED` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/btg_slot_creation_requires_published_parent_list_version
        """
        chain = _draft_entry_with_stock()
        validate_error(_slot_response(chain["venue"], chain["entry"], chain["lot"]),
                       ERR_LIST_VERSION_NOT_PUBLISHED)

        _rows, meta = validate_paginated(api_client.list_btg_slots(
            BEVERAGE_DIRECTOR_HEADERS, params={"venue_id": chain["venue"]["id"]}))
        assert meta["total_count"] == 0, (
            "a refused slot must leave no row: total_count %r"
            % (meta["total_count"],))
        lot = validate_success(api_client.get_inventory_lot(
            chain["lot"]["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert lot["bottles_committed"] == 0, (
            "a refused slot must commit no bottle, got %r"
            % (lot["bottles_committed"],))

    def test_a_slot_against_an_in_review_parent_version_is_refused(self):
        """Submitting the version for review is not a partial pass for the rail.

        "The list version behind the entry must be live, meaning in `PUBLISHED` or `REPRINT_PENDING`; anything else is `ERR_LIST_VERSION_NOT_PUBLISHED` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/btg_slot_creation_requires_published_parent_list_version
        """
        chain = _draft_entry_with_stock()
        submitted = fx.submit_version(chain["version"], chain["venue"])
        assert submitted["state"] == "IN_REVIEW"

        validate_error(_slot_response(chain["venue"], chain["entry"], chain["lot"]),
                       ERR_LIST_VERSION_NOT_PUBLISHED)

        _rows, meta = validate_paginated(api_client.list_btg_slots(
            BEVERAGE_DIRECTOR_HEADERS, params={"venue_id": chain["venue"]["id"]}))
        assert meta["total_count"] == 0, (
            "a refused slot must leave no row: total_count %r"
            % (meta["total_count"],))
        lot = validate_success(api_client.get_inventory_lot(
            chain["lot"]["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert lot["bottles_committed"] == 0

    def test_the_identical_slot_payload_is_accepted_once_the_version_is_published(self):
        """Publishing the grandparent version makes the byte-identical slot request legal.

        "The list version behind the entry must be live, meaning in `PUBLISHED` or `REPRINT_PENDING`; anything else is `ERR_LIST_VERSION_NOT_PUBLISHED` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/btg_slot_creation_requires_published_parent_list_version
        """
        chain = _draft_entry_with_stock()
        validate_error(_slot_response(chain["venue"], chain["entry"], chain["lot"]),
                       ERR_LIST_VERSION_NOT_PUBLISHED)
        published = fx.publish_version(chain["version"], chain["venue"])
        assert published["state"] == "PUBLISHED"

        slot = validate_success(
            _slot_response(chain["venue"], chain["entry"], chain["lot"]), 201)
        assert_fields_equal(slot, {"state": "OPEN", "slot_index": 1},
                            name="accepted slot")
        assert _instant(slot["preservation_expires_at"]) == _instant(
            "2026-09-09T12:00:00Z"), (
            "RED at 96 base hours doubled by ARGON expires 192 hours after"
            " 2026-09-01T12:00:00Z, got %r" % (slot["preservation_expires_at"],))

        entry = validate_success(api_client.get_list_entry(
            chain["entry"]["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert_fields_equal(entry, {"glass_price_cents": 2875,
                                    "availability_state": "AVAILABLE"},
                            name="entry after the refusal")
