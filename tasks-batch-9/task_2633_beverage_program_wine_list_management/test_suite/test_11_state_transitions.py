"""State-machine behaviour of the beverage program.

This file pins the declared state machines themselves: the initial state a
record is born in, the transitions that are defined, the transitions that are
not, the refusals a terminal state issues, the side effects a transition fires
on its neighbours, and the states that are derived from a child count rather
than driven by an endpoint of their own.

Every test builds its whole world through published endpoints, because the
runner restarts the API against an empty database before each test.
"""
from prd_bench_local_runner.testing import (
    assert_timestamp_format,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import (
    ERR_CLAIM_NOT_GRANTED,
    ERR_EVENT_INVALID_STATE,
    ERR_LIST_VERSION_NOT_DRAFT,
    ERR_LIST_VERSION_NOT_IN_REVIEW,
    ERR_LOT_NOT_ON_HAND,
)
from test_helpers.assertions import (
    assert_fields_equal,
    assert_null_fields,
    depletion_entries_for,
    get_all,
)
from test_helpers.test_users import (
    BEVERAGE_DIRECTOR_HEADERS,
    BEVERAGE_DIRECTOR_ID,
    COMPLIANCE_OFFICER_HEADERS,
    CONTROLLER_HEADERS,
    sommelier_headers,
)

# The cost-of-goods targets used by every design instance in this section.
TARGETS = f.cogs_targets(30.0, WHITE=25.0, ROSE=28.0, RED=28.0,
                         DESSERT=32.0, FORTIFIED=35.0)


def _venue(**overrides):
    """The section's Harbor Room venue: RED target 28.0, priority rank 1."""
    overrides.setdefault("cogs_target_pct_by_category", dict(TARGETS))
    overrides.setdefault("priority_rank", 1)
    return fx.create_venue(**overrides)


def _red_wine(**overrides):
    """The section's RED wine: 750 ml, 2400 cents catalogue cost."""
    overrides.setdefault("category", "RED")
    overrides.setdefault("reference_cost_cents", 2400)
    overrides.setdefault("bottle_size_ml", 750)
    overrides.setdefault("case_pack", 6)
    return fx.create_wine(**overrides)


def _published_version(venue, wine, entry_overrides=None):
    """A wine list whose only version is PUBLISHED and carries one entry."""
    wine_list = fx.create_wine_list(venue)
    version = fx.create_draft_version(wine_list, venue)
    entry = fx.add_entry(version, wine, venue, sort_rank=1,
                         **(entry_overrides or {}))
    published = fx.publish_version(version, venue)
    return {"wine_list": wine_list, "version": published, "entry": entry}


def _btg_entry_overrides(pour_size_ml=177, par_bottles=6):
    return {"by_the_glass": True, "pour_size_ml": pour_size_ml,
            "par_bottles": par_bottles, "education_verified": False}


class TestDistributorComplianceReviewCascade:
    """A CLEARED review moves the distributor and drags its offers' compliance
    dimension along, leaving every fulfilment dimension where it stood."""

    def test_clearing_a_pending_review_distributor_clears_all_of_its_offers(self):
        """A CLEARED review moves PENDING_REVIEW -> CLEARED, stores the note and
        pulls every PENDING_LICENSE_CHECK offer of that distributor to CLEARED
        without touching fulfillment_state.

        "When a review leaves the distributor in `CLEARED`, every offer of that distributor whose compliance dimension reads `BLOCKED` moves `BLOCKED → CLEARED`, and every offer reading `PENDING_LICENSE_CHECK` moves `PENDING_LICENSE_CHECK → CLEARED`, again with `version` incremented by 1 and again without touching the fulfilment dimension."

        Design: Corner/state_machines/distributor_compliance_review_clears_pending_review_and_cascades_to_offers
        """
        fx.set_clock("2026-08-01T00:00:00Z")
        distributor = fx.create_distributor(name="Coastal Selections",
                                            allocation_tier="A",
                                            on_time_delivery_pct=96.5)
        assert distributor["compliance_state"] == "PENDING_REVIEW"
        assert distributor["last_review_note"] is None

        wine_one = _red_wine(producer="Ridge", cuvee="Monte Bello",
                             is_allocated=True)
        wine_two = _red_wine(producer="Ridge", cuvee="Geyserville",
                             is_allocated=True)
        offer_one = fx.create_offer(distributor, wine_one, offered_bottles=6,
                                    unit_cost_cents=4500,
                                    response_deadline="2026-09-30T00:00:00Z")
        offer_two = fx.create_offer(distributor, wine_two, offered_bottles=6,
                                    unit_cost_cents=4500,
                                    response_deadline="2026-09-30T00:00:00Z")
        for offer in (offer_one, offer_two):
            assert offer["compliance_state"] == "PENDING_LICENSE_CHECK"
            assert offer["fulfillment_state"] == "OPEN"

        response = api_client.create_compliance_review(
            distributor["id"], f.compliance_review_payload(
                "CLEARED", note="Licence verified 2026-08."),
            COMPLIANCE_OFFICER_HEADERS)
        reviewed = validate_success(response, 200)

        assert_fields_equal(reviewed, {
            "id": distributor["id"],
            "compliance_state": "CLEARED",
            "last_review_note": "Licence verified 2026-08.",
        }, "Distributor")

        for offer in (offer_one, offer_two):
            after = get_success_data(
                api_client.get_allocation_offer(offer["id"],
                                                BEVERAGE_DIRECTOR_HEADERS))
            assert_fields_equal(after, {
                "compliance_state": "CLEARED",
                "fulfillment_state": "OPEN",
                "unallocated_bottles": 6,
            }, "AllocationOffer")
            assert after["version"] == offer["version"] + 1, (
                "the cascade must increment the offer's version by exactly 1")

        rows, meta = validate_paginated(api_client.list_allocation_offers(
            BEVERAGE_DIRECTOR_HEADERS,
            params={"distributor_id": distributor["id"],
                    "compliance_state": "CLEARED"}))
        assert meta["total_count"] == 2, (
            "both offers must now answer the CLEARED compliance filter")
        assert {row["id"] for row in rows} == {offer_one["id"], offer_two["id"]}


class TestWineDinnerEventInitialState:
    """A wine dinner is born PLANNED, already pinned to the list version it was
    drawn from, with every pricing figure still unwritten."""

    def test_new_event_starts_planned_with_the_pinned_version_no_resolved(self):
        """Creating a dinner against a PUBLISHED version yields state PLANNED,
        pinned_version_no equal to that version's version_no, pinned_version_stale
        false and all five pricing fields null.

        "A new event starts in state `PLANNED` with `pinned_version_no` set to the referenced version's `version_no`, `pinned_version_stale` false, and all five pricing fields — `beverage_cost_per_seat_cents`, `provisional_gross_cents`, `tier_discount_pct`, `final_ticket_price_cents` and `projected_pour_cost_pct` — null."

        Design: Corner/state_machines/wine_dinner_event_starts_in_planned_with_pinned_version
        """
        fx.set_clock("2026-09-01T12:00:00Z")
        venue = _venue(name="Harbor Room", event_cogs_target_pct=28.0)
        wine = _red_wine(producer="Ridge", cuvee="Monte Bello",
                         is_allocated=False)
        chain = _published_version(venue, wine,
                                   entry_overrides=_btg_entry_overrides())
        assert chain["version"]["version_no"] == 1

        response = api_client.create_wine_dinner_event(
            f.wine_dinner_event_payload(
                venue["id"], chain["version"]["id"],
                [f.pour_plan_line(chain["entry"]["id"], 2)],
                name="Ridge Vertical",
                starts_at="2026-10-10T18:00:00Z",
                ends_at="2026-10-10T21:00:00Z",
                seat_count=24),
            sommelier_headers(venue["id"]))
        event = validate_success(response, 201)

        assert_fields_equal(event, {
            "state": "PLANNED",
            "pinned_version_no": 1,
            "pinned_version_stale": False,
            "seat_count": 24,
            "version": 1,
        }, "WineDinnerEvent")
        assert_null_fields(event,
                           "beverage_cost_per_seat_cents",
                           "provisional_gross_cents",
                           "tier_discount_pct",
                           "final_ticket_price_cents",
                           "projected_pour_cost_pct")

    def test_new_event_carries_no_settlement_figures_before_it_is_settled(self):
        """The settlement figures a void returns to null are null from the start,
        before any settlement has run.

        "Both venue ledgers return to their pre-settlement values, and `settled_cogs_cents` and `settled_revenue_cents` are reset to null."

        Design: Corner/state_machines/wine_dinner_event_starts_in_planned_with_pinned_version
        """
        fx.set_clock("2026-09-01T12:00:00Z")
        venue = _venue(name="Harbor Room", event_cogs_target_pct=28.0)
        wine = _red_wine(producer="Ridge", cuvee="Monte Bello")
        chain = _published_version(venue, wine,
                                   entry_overrides=_btg_entry_overrides())

        event = fx.create_event(venue, chain["version"],
                                [f.pour_plan_line(chain["entry"]["id"], 2)],
                                name="Ridge Vertical",
                                starts_at="2026-10-10T18:00:00Z",
                                ends_at="2026-10-10T21:00:00Z",
                                seat_count=24)

        assert event["state"] == "PLANNED"
        assert_null_fields(event, "settled_cogs_cents", "settled_revenue_cents")


class TestArchivedListVersionLockdown:
    """ARCHIVED is terminal: each trigger is refused with the error naming the
    state family that trigger expected, and none of them succeeds."""

    @staticmethod
    def _archived_version():
        fx.set_clock("2026-08-01T00:00:00Z")
        venue = _venue(name="Harbor Room")
        wine_list = fx.create_wine_list(venue)
        draft = fx.create_draft_version(wine_list, venue)
        archived = get_success_data(
            api_client.archive_list_version(draft["id"],
                                            BEVERAGE_DIRECTOR_HEADERS))
        assert archived["state"] == "ARCHIVED"
        assert archived["version"] == draft["version"] + 1
        return venue, wine_list, archived

    def test_archived_version_refuses_submit_with_not_draft(self):
        """Submitting an ARCHIVED version is refused because submit is defined
        only from DRAFT.

        "It requires the version to be in `DRAFT` (`ERR_LIST_VERSION_NOT_DRAFT`) and to carry at least one entry, an empty version being refused with `ERR_EMPTY_LIST_VERSION` (HTTP 422)."

        Design: Corner/state_machines/archived_list_version_cannot_be_submitted_or_published
        """
        venue, wine_list, archived = self._archived_version()

        validate_error(
            api_client.submit_list_version(archived["id"],
                                           sommelier_headers(venue["id"])),
            ERR_LIST_VERSION_NOT_DRAFT)

        still = get_success_data(
            api_client.get_list_version(archived["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert still["state"] == "ARCHIVED"
        assert still["version"] == archived["version"], (
            "a refused submit must not mutate the version")

    def test_archived_version_refuses_publish_with_not_in_review(self):
        """Publishing an ARCHIVED version is refused because publication is
        defined only from IN_REVIEW, and the container stays unpublished.

        "The version must be in `IN_REVIEW`, otherwise `ERR_LIST_VERSION_NOT_IN_REVIEW`."

        Design: Corner/state_machines/archived_list_version_cannot_be_submitted_or_published
        """
        venue, wine_list, archived = self._archived_version()

        validate_error(
            api_client.publish_list_version(archived["id"],
                                            BEVERAGE_DIRECTOR_HEADERS),
            ERR_LIST_VERSION_NOT_IN_REVIEW)

        still = get_success_data(
            api_client.get_list_version(archived["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert still["state"] == "ARCHIVED"
        container = get_success_data(
            api_client.get_wine_list(wine_list["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert container["published_version_no"] is None, (
            "a refused publication must leave the container with no live version")

    def test_archiving_an_already_archived_version_is_not_idempotent(self):
        """Archiving an ARCHIVED version is refused rather than treated as a
        no-op, because archiving is defined only from DRAFT.

        "Archiving is director-exclusive, requires the version to be in `DRAFT`, moves it `DRAFT → ARCHIVED`, and increments the version's `version` by 1."

        Design: Corner/state_machines/archived_list_version_cannot_be_submitted_or_published
        """
        venue, wine_list, archived = self._archived_version()

        validate_error(
            api_client.archive_list_version(archived["id"],
                                            BEVERAGE_DIRECTOR_HEADERS),
            ERR_LIST_VERSION_NOT_DRAFT)

        still = get_success_data(
            api_client.get_list_version(archived["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert still["state"] == "ARCHIVED"
        assert still["version"] == archived["version"], (
            "the refused second archive must not increment version again")


class TestSettleFromNonConfirmedEvent:
    """settle is defined only from CONFIRMED and void-settlement only from
    SETTLED; firing either early is a state refusal, not a stock refusal."""

    @staticmethod
    def _planned_event_without_stock():
        fx.set_clock("2026-09-01T12:00:00Z")
        venue = _venue(name="Harbor Room", event_cogs_target_pct=28.0)
        wine = _red_wine(producer="Ridge", cuvee="Monte Bello",
                         is_allocated=False)
        chain = _published_version(venue, wine,
                                   entry_overrides=_btg_entry_overrides())
        event = fx.create_event(venue, chain["version"],
                                [f.pour_plan_line(chain["entry"]["id"], 2)],
                                name="Ridge Vertical",
                                starts_at="2026-10-10T18:00:00Z",
                                ends_at="2026-10-10T21:00:00Z",
                                seat_count=24)
        assert event["state"] == "PLANNED"
        # The venue holds no inventory at all, so the stock check would also
        # fail if it were reached.
        lots, lot_meta = validate_paginated(api_client.list_inventory_lots(
            BEVERAGE_DIRECTOR_HEADERS, params={"venue_id": venue["id"]}))
        assert lot_meta["total_count"] == 0
        return venue, event

    def test_settle_from_planned_reports_invalid_state_not_insufficient_bottles(self):
        """Settling a PLANNED event is refused for its state even though the
        venue holds no bottles at all, because the event-state precondition is
        evaluated before the sufficient-bottles fiscal gate.

        "Settlement is controller-exclusive and requires the event to be in `CONFIRMED` (`ERR_EVENT_INVALID_STATE`) with `pinned_version_stale` false; a pinned version that has left `PUBLISHED` since confirmation — because it went to `REPRINT_PENDING`, was superseded or was archived — blocks settlement with `ERR_PINNED_LIST_VERSION_STALE` (HTTP 409)."

        Design: Corner/state_machines/settle_from_planned_event_rejected_as_invalid_transition
        """
        venue, event = self._planned_event_without_stock()

        validate_error(api_client.settle_event(event["id"], CONTROLLER_HEADERS),
                       ERR_EVENT_INVALID_STATE)

        after = get_success_data(
            api_client.get_wine_dinner_event(event["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert after["state"] == "PLANNED"
        assert_null_fields(after, "settled_cogs_cents", "settled_revenue_cents")

        ledgers = fx.get_venue(venue)
        assert_fields_equal(ledgers, {"cogs_ledger_cents": 0,
                                      "revenue_ledger_cents": 0}, "Venue")
        rows, meta = validate_paginated(api_client.list_depletion_entries(
            BEVERAGE_DIRECTOR_HEADERS, params={"event_id": event["id"]}))
        assert meta["total_count"] == 0 and rows == [], (
            "a refused settlement must write no ledger entry")

    def test_settle_from_priced_is_still_an_invalid_transition(self):
        """A PRICED event is not yet CONFIRMED, so settlement is refused again
        and the event stays PRICED.

        "Pricing moves the event `PLANNED → PRICED`, and it may be repeated: a `PRICED` event re-priced stays `PRICED → PRICED`, recomputing all five fields against current entry data."

        Design: Corner/state_machines/settle_from_planned_event_rejected_as_invalid_transition
        """
        venue, event = self._planned_event_without_stock()
        priced = fx.price_event(event, venue)
        assert priced["state"] == "PRICED"

        validate_error(api_client.settle_event(event["id"], CONTROLLER_HEADERS),
                       ERR_EVENT_INVALID_STATE)

        after = get_success_data(
            api_client.get_wine_dinner_event(event["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert after["state"] == "PRICED"
        assert_null_fields(after, "settled_cogs_cents", "settled_revenue_cents")

    def test_void_settlement_from_priced_is_an_invalid_transition(self):
        """Voiding a settlement that never happened is refused, because
        void-settlement is defined only from SETTLED.

        "It requires the event to be in `SETTLED` (`ERR_EVENT_INVALID_STATE`) and moves it `SETTLED → SETTLEMENT_VOIDED`."

        Design: Corner/state_machines/settle_from_planned_event_rejected_as_invalid_transition
        """
        venue, event = self._planned_event_without_stock()
        fx.price_event(event, venue)

        validate_error(
            api_client.void_event_settlement(
                event["id"], f.note_payload("Nothing to void."),
                CONTROLLER_HEADERS),
            ERR_EVENT_INVALID_STATE)

        after = get_success_data(
            api_client.get_wine_dinner_event(event["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert after["state"] == "PRICED"
        ledgers = fx.get_venue(venue)
        assert_fields_equal(ledgers, {"cogs_ledger_cents": 0,
                                      "revenue_ledger_cents": 0}, "Venue")


class TestSubmitIsNotAnIdempotentUpsert:
    """submit is a DRAFT -> IN_REVIEW transition, so replaying it from
    IN_REVIEW is refused rather than absorbed as a silent no-op."""

    def test_second_submit_on_an_in_review_version_is_rejected(self):
        """Submitting an already IN_REVIEW version is refused, and the replay
        moves neither revision_round, nor submitted_by_user_id, nor version.

        "It requires the version to be in `DRAFT` (`ERR_LIST_VERSION_NOT_DRAFT`) and to carry at least one entry, an empty version being refused with `ERR_EMPTY_LIST_VERSION` (HTTP 422)."

        Design: Corner/state_machines/second_submit_on_in_review_version_rejected_as_non_idempotent
        """
        fx.set_clock("2026-08-01T00:00:00Z")
        venue = _venue(name="Harbor Room")
        wine = _red_wine(producer="Ridge", cuvee="Monte Bello")
        wine_list = fx.create_wine_list(venue)
        draft = fx.create_draft_version(wine_list, venue)
        fx.add_entry(draft, wine, venue, sort_rank=1, by_the_glass=False,
                     par_bottles=6)

        submitted = get_success_data(
            api_client.submit_list_version(draft["id"],
                                           sommelier_headers(venue["id"])))
        assert_fields_equal(submitted, {
            "state": "IN_REVIEW",
            "revision_round": 0,
            "submitted_by_user_id": venue["id"],
        }, "ListVersion")

        validate_error(
            api_client.submit_list_version(draft["id"],
                                           sommelier_headers(venue["id"])),
            ERR_LIST_VERSION_NOT_DRAFT)

        after = get_success_data(
            api_client.get_list_version(draft["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert_fields_equal(after, {
            "state": "IN_REVIEW",
            "revision_round": 0,
            "submitted_by_user_id": venue["id"],
            "version": submitted["version"],
        }, "ListVersion")
        assert after["updated_at"] == submitted["updated_at"], (
            "the rejected replay must not re-stamp updated_at")


class TestReceiveBeforeGrant:
    """receive is defined only from GRANTED / PARTIALLY_GRANTED, so a
    REQUESTED claim is refused before any lot or bin movement happens."""

    def test_receiving_a_requested_claim_is_refused_and_creates_no_lot(self):
        """A claim still in REQUESTED cannot be received even though the bin,
        the receipt instant and the distributor's licence are all valid.

        "Six checks guard it: the claim must be in `GRANTED` or `PARTIALLY_GRANTED` (`ERR_CLAIM_NOT_GRANTED`, HTTP 409); the offer's compliance dimension must not be `BLOCKED` (`ERR_OFFER_COMPLIANCE_BLOCKED`); the distributor must not stand in `HOLD` (`ERR_DISTRIBUTOR_COMPLIANCE_HOLD`); `received_at` must not be later than the logical clock (`ERR_RECEIVED_AT_IN_FUTURE`, HTTP 422); the nominated bin must belong to the claiming venue (`ERR_LOT_VENUE_MISMATCH`, HTTP 422); the bin's zone must not be `RESERVE` unless the wine is flagged allocated (`ERR_BIN_ZONE_MISMATCH`); and the bin's `bottles_stored` plus the incoming bottles must not exceed its `capacity_bottles` (`ERR_BIN_CAPACITY_EXCEEDED`, HTTP 409)."

        Design: Corner/state_machines/allocation_claim_receive_before_grant_rejected_by_precondition
        """
        fx.set_clock("2026-09-01T12:00:00Z")
        venue = _venue(name="Harbor Room")
        bin_ = fx.create_bin(venue, bin_code="A1", zone="CELLAR",
                             capacity_bottles=48, temperature_controlled=True)
        distributor = fx.create_cleared_distributor(name="Coastal Selections",
                                                    allocation_tier="A",
                                                    on_time_delivery_pct=96.5)
        wine = _red_wine(producer="Ridge", cuvee="Monte Bello", is_allocated=True)
        offer = fx.create_offer(distributor, wine, offered_bottles=6,
                                unit_cost_cents=4500,
                                response_deadline="2026-09-30T00:00:00Z")
        claim = fx.file_claim(offer, venue, 6)
        assert_fields_equal(claim, {"state": "REQUESTED", "granted_bottles": 0},
                            "AllocationClaim")

        validate_error(
            api_client.receive_claim(
                claim["id"],
                f.receive_claim_payload(bin_["id"], "2026-09-01T12:00:00Z"),
                sommelier_headers(venue["id"])),
            ERR_CLAIM_NOT_GRANTED)

        after_claim = get_success_data(
            api_client.get_allocation_claim(claim["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert_fields_equal(after_claim, {"state": "REQUESTED",
                                          "granted_bottles": 0},
                            "AllocationClaim")

        after_bin = get_success_data(
            api_client.get_cellar_bin(bin_["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert after_bin["bottles_stored"] == 0
        assert float(after_bin["utilization_pct"]) == 0.0
        assert after_bin["bin_state"] == "ACTIVE"

        lots, lot_meta = validate_paginated(api_client.list_inventory_lots(
            BEVERAGE_DIRECTOR_HEADERS, params={"source_claim_id": claim["id"]}))
        assert lot_meta["total_count"] == 0 and lots == [], (
            "the refused receipt must create no InventoryLot")

        after_offer = get_success_data(
            api_client.get_allocation_offer(offer["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert_fields_equal(after_offer, {"fulfillment_state": "OPEN",
                                          "unallocated_bottles": 6},
                            "AllocationOffer")


class TestSupersessionOnPublication:
    """Publishing a successor fires the predecessor's PUBLISHED -> SUPERSEDED
    transition inside the same request and re-points the container."""

    @staticmethod
    def _two_versions():
        fx.set_clock("2026-08-01T00:00:00Z")
        venue = _venue(name="Harbor Room")
        wine = _red_wine(producer="Ridge", cuvee="Monte Bello")
        wine_list = fx.create_wine_list(venue)
        first = fx.create_draft_version(wine_list, venue)
        entry_one = fx.add_entry(first, wine, venue, sort_rank=1,
                                 by_the_glass=False, par_bottles=6)
        live = fx.publish_version(first, venue)
        assert live["state"] == "PUBLISHED" and live["version_no"] == 1

        second = fx.create_draft_version(wine_list, venue,
                                         supersedes_version_id=first["id"])
        fx.add_entry(second, wine, venue, sort_rank=1, by_the_glass=False,
                     par_bottles=12)
        fx.submit_version(second, venue)
        return {"venue": venue, "wine_list": wine_list, "first": first,
                "second": second, "entry_one": entry_one}

    def test_publishing_the_successor_supersedes_the_predecessor(self):
        """Publishing version 2, which names version 1 in supersedes_version_id,
        moves version 1 PUBLISHED -> SUPERSEDED and re-points the container's
        published_version_no in the same request.

        "And when this draft named a `supersedes_version_id`, the version it named moves `PUBLISHED → SUPERSEDED` if it was live, or `REPRINT_PENDING → SUPERSEDED` if it was awaiting a reprint; either transition sets `pinned_version_stale` to true on every wine dinner event in state `PLANNED`, `PRICED` or `CONFIRMED` that pins the superseded version, which is what eventually blocks that event's settlement."

        Design: Corner/state_machines/publishing_successor_version_supersedes_predecessor_side_effect
        """
        world = self._two_versions()

        published = validate_success(
            api_client.publish_list_version(world["second"]["id"],
                                            BEVERAGE_DIRECTOR_HEADERS), 200)
        assert_fields_equal(published, {
            "state": "PUBLISHED",
            "version_no": 2,
            "published_by_user_id": BEVERAGE_DIRECTOR_ID,
        }, "ListVersion")
        assert_timestamp_format(published["published_at"])
        assert published["published_at"].startswith("2026-08-01T00:00:00"), (
            "published_at must be stamped from the logical clock, got %r"
            % (published["published_at"],))
        assert published["printed_at"].startswith("2026-08-01T00:00:00")

        predecessor = get_success_data(api_client.get_list_version(
            world["first"]["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert predecessor["state"] == "SUPERSEDED", (
            "the predecessor must not stay PUBLISHED alongside its successor")

        container = get_success_data(api_client.get_wine_list(
            world["wine_list"]["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert_fields_equal(container, {"published_version_no": 2,
                                        "next_version_no": 3}, "WineList")

    def test_superseding_a_version_leaves_its_entries_in_place(self):
        """The superseded version keeps its entries: supersession retires the
        printed list, it does not delete or re-write the listings on it.

        "Whenever a resource changes as part of such a cascade, its own `updated_at` is refreshed and its own `version` increments by 1 — a parent whose counters move because a child was written is itself a mutation."

        Design: Corner/state_machines/publishing_successor_version_supersedes_predecessor_side_effect
        """
        world = self._two_versions()
        before = get_success_data(api_client.get_list_entry(
            world["entry_one"]["id"], BEVERAGE_DIRECTOR_HEADERS))

        get_success_data(api_client.publish_list_version(
            world["second"]["id"], BEVERAGE_DIRECTOR_HEADERS))

        after = get_success_data(api_client.get_list_entry(
            world["entry_one"]["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert_fields_equal(after, {
            "id": before["id"],
            "par_bottles": 6,
            "bottle_price_cents": before["bottle_price_cents"],
            "version": before["version"],
        }, "ListEntry")

    def test_the_supersession_chain_leaves_exactly_one_live_version(self):
        """After the successor is published the container has exactly one
        PUBLISHED version, and the supersedes_version_id filter exposes the
        chain link from the successor back to its predecessor.

        "At most one version per list is live at any moment, meaning at most one sits in `PUBLISHED` or `REPRINT_PENDING`."

        Design: Corner/state_machines/publishing_successor_version_supersedes_predecessor_side_effect
        """
        world = self._two_versions()
        get_success_data(api_client.publish_list_version(
            world["second"]["id"], BEVERAGE_DIRECTOR_HEADERS))

        live = get_all(api_client.list_list_versions, BEVERAGE_DIRECTOR_HEADERS,
                       params={"wine_list_id": world["wine_list"]["id"],
                               "state": "PUBLISHED"})
        assert [row["id"] for row in live] == [world["second"]["id"]]

        successors = get_all(api_client.list_list_versions,
                             BEVERAGE_DIRECTOR_HEADERS,
                             params={"supersedes_version_id":
                                     world["first"]["id"]})
        assert [row["id"] for row in successors] == [world["second"]["id"]]


class TestInventoryLotDerivedState:
    """An InventoryLot has no transition endpoint: ON_HAND and DEPLETED are
    re-derived from bottles_on_hand by whichever cascade touched it."""

    @staticmethod
    def _two_bottle_rail():
        fx.set_clock("2026-09-01T12:00:00Z")
        venue = _venue(name="Harbor Room")
        bin_ = fx.create_bin(venue, bin_code="A1", zone="CELLAR",
                             capacity_bottles=48, temperature_controlled=True)
        wine = _red_wine(producer="Ridge", cuvee="Monte Bello",
                         is_allocated=False)
        lot = fx.create_lot(venue, wine, bin_, bottles_received=2,
                            unit_cost_cents=2400,
                            received_at="2026-08-10T00:00:00Z")
        assert lot["state"] == "ON_HAND" and lot["bottles_on_hand"] == 2
        chain = _published_version(venue, wine,
                                   entry_overrides=_btg_entry_overrides())
        assert chain["entry"]["effective_pours"] == 3, (
            "a 750 ml bottle at a 177 ml pour must yield 3 saleable glasses")
        assert chain["entry"]["glass_price_cents"] == 2875
        return {"venue": venue, "bin": bin_, "wine": wine, "lot": lot,
                "version": chain["version"], "entry": chain["entry"]}

    def test_two_single_bottle_closes_derive_on_hand_then_depleted(self):
        """Draining a 2-bottle lot one slot at a time leaves it ON_HAND after the
        first close and DEPLETED after the second, with no lot endpoint ever
        being called.

        "The lot's `bottles_committed` falls by 1 and its `bottles_on_hand` falls by 1; a lot that reaches zero on hand moves `ON_HAND → DEPLETED`, with the bin and availability cascade of Section 3.8."

        Design: Corner/state_machines/inventory_lot_compound_state_derives_from_bottle_count
        """
        world = self._two_bottle_rail()
        venue, lot = world["venue"], world["lot"]

        first = fx.open_slot(venue, world["entry"], lot, slot_index=1,
                             preservation_method="ARGON")
        fx.close_slot(first, venue, pours_sold=3)
        after_one = get_success_data(
            api_client.get_inventory_lot(lot["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert_fields_equal(after_one, {"bottles_on_hand": 1,
                                        "bottles_committed": 0,
                                        "state": "ON_HAND"}, "InventoryLot")

        second = fx.open_slot(venue, world["entry"], lot, slot_index=2,
                              preservation_method="ARGON")
        fx.close_slot(second, venue, pours_sold=3)
        after_two = get_success_data(
            api_client.get_inventory_lot(lot["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert_fields_equal(after_two, {"bottles_on_hand": 0,
                                        "bottles_committed": 0,
                                        "state": "DEPLETED"}, "InventoryLot")

        after_bin = get_success_data(
            api_client.get_cellar_bin(world["bin"]["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert after_bin["bottles_stored"] == 0
        assert float(after_bin["utilization_pct"]) == 0.0

        entry = get_success_data(api_client.get_list_entry(
            world["entry"]["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert entry["availability_state"] == "OUT_OF_STOCK"
        version = get_success_data(api_client.get_list_version(
            world["version"]["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert version["out_of_stock_entry_count"] == 1

        entries = depletion_entries_for(BEVERAGE_DIRECTOR_HEADERS,
                                        lot_id=lot["id"])
        assert len(entries) == 2, (
            "one SALE_BTG row per closed slot, got %d" % len(entries))
        for row in entries:
            assert_fields_equal(row, {"reason": "SALE_BTG", "bottles": 1,
                                      "pours": 3, "cogs_cents": 2400,
                                      "revenue_cents": 8625}, "DepletionEntry")

    def test_a_depleted_lot_refuses_the_next_rail_slot(self):
        """The derived DEPLETED state is what gates the next slot: opening a
        third slot on the emptied lot is refused.

        "The nominated lot must be `ON_HAND`; a depleted or written-off lot is `ERR_LOT_NOT_ON_HAND` (HTTP 409)."

        Design: Corner/state_machines/inventory_lot_compound_state_derives_from_bottle_count
        """
        world = self._two_bottle_rail()
        venue, lot = world["venue"], world["lot"]
        for index in (1, 2):
            slot = fx.open_slot(venue, world["entry"], lot, slot_index=index,
                                preservation_method="ARGON")
            fx.close_slot(slot, venue, pours_sold=3)

        validate_error(
            api_client.create_btg_slot(
                f.btg_slot_payload(venue["id"], world["entry"]["id"], lot["id"],
                                   slot_index=3, preservation_method="ARGON"),
                sommelier_headers(venue["id"])),
            ERR_LOT_NOT_ON_HAND)


class TestBtgCloseSyncsVenueLedgers:
    """OPEN -> CLOSED splits the bottle three ways and posts every bucket to the
    venue's two running ledgers in the same request."""

    @staticmethod
    def _open_slot_on_a_full_case():
        fx.set_clock("2026-09-01T12:00:00Z")
        venue = _venue(name="Harbor Room")
        assert venue["cogs_ledger_cents"] == 0
        assert venue["revenue_ledger_cents"] == 0
        bin_ = fx.create_bin(venue, bin_code="A1", zone="CELLAR",
                             capacity_bottles=48, temperature_controlled=True)
        wine = _red_wine(producer="Ridge", cuvee="Monte Bello",
                         is_allocated=False)
        lot = fx.create_lot(venue, wine, bin_, bottles_received=12,
                            unit_cost_cents=2400,
                            received_at="2026-08-10T00:00:00Z")
        chain = _published_version(venue, wine,
                                   entry_overrides=_btg_entry_overrides())
        assert chain["entry"]["effective_pours"] == 3
        assert chain["entry"]["glass_price_cents"] == 2875
        slot = fx.open_slot(venue, chain["entry"], lot, slot_index=1,
                            preservation_method="ARGON")
        assert slot["state"] == "OPEN" and slot["effective_pours"] == 3
        return {"venue": venue, "lot": lot, "entry": chain["entry"],
                "slot": slot}

    def test_closing_the_slot_posts_the_cost_split_to_both_venue_ledgers(self):
        """Two sold pours and one education pour out of a 2400-cent bottle move
        cogs_ledger_cents to the whole bottle cost and revenue_ledger_cents to
        two glasses of revenue.

        "Every created entry's `cogs_cents` is added to the venue's `cogs_ledger_cents` and every `revenue_cents` to its `revenue_ledger_cents`."

        Design: Corner/state_machines/btg_slot_close_syncs_venue_ledgers_from_cost_split
        """
        world = self._open_slot_on_a_full_case()

        closed = validate_success(api_client.close_btg_slot(
            world["slot"]["id"],
            f.close_slot_payload(2, staff_education_pours=1),
            sommelier_headers(world["venue"]["id"])), 200)
        assert_fields_equal(closed, {"state": "CLOSED", "pours_sold": 2,
                                     "staff_education_pours": 1,
                                     "spoiled_pours": 0}, "BtgSlot")

        venue = fx.get_venue(world["venue"])
        assert_fields_equal(venue, {"cogs_ledger_cents": 2400,
                                    "revenue_ledger_cents": 5750}, "Venue")

        lot = get_success_data(api_client.get_inventory_lot(
            world["lot"]["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert_fields_equal(lot, {"bottles_on_hand": 11,
                                  "bottles_committed": 0,
                                  "state": "ON_HAND"}, "InventoryLot")

    def test_the_three_buckets_reconcile_to_the_whole_bottle_cost(self):
        """The sale and education buckets are written as their own ledger rows
        summing to exactly the bottle cost, and the zero-pour spoilage bucket
        writes no row at all.

        "The closure then appends one ledger entry per bucket, in the pinned order sale, then education, then spoilage, and a bucket whose pour count is zero produces no entry at all."

        Design: Corner/state_machines/btg_slot_close_syncs_venue_ledgers_from_cost_split
        """
        world = self._open_slot_on_a_full_case()
        fx.close_slot(world["slot"], world["venue"], pours_sold=2,
                      staff_education_pours=1)

        rows = depletion_entries_for(BEVERAGE_DIRECTOR_HEADERS,
                                     btg_slot_id=world["slot"]["id"])
        assert len(rows) == 2, (
            "expected a SALE_BTG row and a STAFF_EDUCATION row only, got %r"
            % ([row["reason"] for row in rows],))
        by_reason = {row["reason"]: row for row in rows}
        assert set(by_reason) == {"SALE_BTG", "STAFF_EDUCATION"}, (
            "the 0-pour spoilage bucket must not produce a SPOILAGE row")

        assert_fields_equal(by_reason["SALE_BTG"], {
            "bottles": 1, "pours": 2, "cogs_cents": 1600,
            "revenue_cents": 5750, "list_entry_id": world["entry"]["id"],
            "btg_slot_id": world["slot"]["id"], "lot_id": world["lot"]["id"],
        }, "DepletionEntry(SALE_BTG)")
        assert_fields_equal(by_reason["STAFF_EDUCATION"], {
            "bottles": 0, "pours": 1, "cogs_cents": 800,
            "revenue_cents": 0, "list_entry_id": world["entry"]["id"],
            "btg_slot_id": world["slot"]["id"], "lot_id": world["lot"]["id"],
        }, "DepletionEntry(STAFF_EDUCATION)")

        assert sum(row["cogs_cents"] for row in rows) == 2400, (
            "the buckets must absorb the rounding drift and sum to the bottle cost")
