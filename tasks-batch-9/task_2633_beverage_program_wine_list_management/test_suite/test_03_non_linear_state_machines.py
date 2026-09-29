"""Non-linear state machines: a bounded cycle and two parallel dimensions.

A ListVersion's DRAFT <-> IN_REVIEW loop is genuinely cyclic and is bounded by
an accumulated counter rather than by a state, so the fourth bounce is refused
while the state itself is still a perfectly legal IN_REVIEW.  An AllocationOffer
instead carries two orthogonal dimensions: a compliance review drives
compliance_state CLEARED -> BLOCKED -> CLEARED while fulfillment_state stays
pinned at ALLOCATED and the granted claim never moves.
"""
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f, fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import (
    ERR_LIST_VERSION_NOT_IN_REVIEW,
    ERR_REVISION_LIMIT_REACHED,
)
from test_helpers.test_users import (
    BEVERAGE_DIRECTOR_HEADERS,
    COMPLIANCE_OFFICER_HEADERS,
)

CLOCK = "2026-09-01T12:00:00Z"

_TARGETS = f.cogs_targets(SPARKLING=30.0, WHITE=25.0, ROSE=28.0, RED=28.0,
                          DESSERT=32.0, FORTIFIED=35.0)

_ROUND_NOTES = (
    "Round 1: reorder the Burgundies.",
    "Round 2: fix the vintage column.",
    "Round 3: tighten the tasting notes.",
)


def _venue():
    return fx.create_venue(name="Harbor Room",
                           cogs_target_pct_by_category=dict(_TARGETS),
                           priority_rank=1)


def _version(version_id):
    return get_success_data(
        api_client.get_list_version(version_id, BEVERAGE_DIRECTOR_HEADERS))


def _wine_list(wine_list_id):
    return get_success_data(
        api_client.get_wine_list(wine_list_id, BEVERAGE_DIRECTOR_HEADERS))


def _version_at_the_revision_ceiling():
    """A one-entry ListVersion bounced back three times and re-submitted, so its
    revision_round is 3 and its state is IN_REVIEW."""
    fx.set_clock(CLOCK)
    venue = _venue()
    wine = fx.create_wine(producer="Ridge", cuvee="Monte Bello",
                          vintage_year=2019, category="RED",
                          reference_cost_cents=2400, bottle_size_ml=750,
                          case_pack=6, is_allocated=False)
    draft = fx.setup_draft_version(venue)
    version = draft["version"]
    entry = fx.add_entry(version, wine, venue, sort_rank=1, by_the_glass=False,
                         par_bottles=6, education_verified=False)
    for note in _ROUND_NOTES:
        fx.submit_version(version, venue)
        get_success_data(api_client.request_changes_list_version(
            version["id"], f.note_payload(note), BEVERAGE_DIRECTOR_HEADERS))
    fx.submit_version(version, venue)
    return {"venue": venue, "wine": wine, "wine_list": draft["wine_list"],
            "version": version, "entry": entry}


class TestListVersionReviewCycleCeiling:
    """Three bounces are legal, the fourth is not, and the counter — not the
    state — is what refuses it."""

    def test_fourth_request_changes_is_refused_by_the_accumulated_round_count(self):
        """The fourth bounce is ERR_REVISION_LIMIT_REACHED although IN_REVIEW is a
        legal origin for the transition.

        "Requesting changes is director-exclusive, carries a mandatory `note`, requires the version to be in `IN_REVIEW` (`ERR_LIST_VERSION_NOT_IN_REVIEW`, HTTP 409), and requires `revision_round` to be strictly less than three."

        Design: Difficulty/non_linear_state_machine/list_version_review_cycle_revision_round_ceiling
        """
        setup = _version_at_the_revision_ceiling()
        before = _version(setup["version"]["id"])
        assert before["revision_round"] == 3
        assert before["state"] == "IN_REVIEW"

        response = api_client.request_changes_list_version(
            setup["version"]["id"], f.note_payload("Round 4: one more pass."),
            BEVERAGE_DIRECTOR_HEADERS)

        validate_error(response, ERR_REVISION_LIMIT_REACHED)
        after = _version(setup["version"]["id"])
        assert after["revision_round"] == 3, (
            "a refused bounce must not consume a revision round")
        assert after["state"] == "IN_REVIEW"
        assert after["submitted_by_user_id"] == setup["venue"]["id"]

    def test_version_at_the_revision_ceiling_may_still_be_published(self):
        """The ceiling bounds the loop, not the exit: the version publishes as
        version_no 1.

        "The owning container's `published_version_no` is set to this version's `version_no`."

        Design: Difficulty/non_linear_state_machine/list_version_review_cycle_revision_round_ceiling
        """
        setup = _version_at_the_revision_ceiling()
        validate_error(
            api_client.request_changes_list_version(
                setup["version"]["id"],
                f.note_payload("Round 4: one more pass."),
                BEVERAGE_DIRECTOR_HEADERS),
            ERR_REVISION_LIMIT_REACHED)

        published = validate_success(api_client.publish_list_version(
            setup["version"]["id"], BEVERAGE_DIRECTOR_HEADERS))

        assert published["state"] == "PUBLISHED"
        assert published["version_no"] == 1
        assert published["revision_round"] == 3
        container = _wine_list(setup["wine_list"]["id"])
        assert container["published_version_no"] == 1

    def test_request_changes_after_publication_reports_the_state_not_the_ceiling(self):
        """Once the version is PUBLISHED the state precondition is reported, not
        the revision ceiling.

        "State preconditions on the target record, in the order they are introduced in Section 3: list-version state, offer fulfilment state, claim state, lot state, slot state, write-off state, event state, investigation state, the revision-round ceiling, and the non-empty-version requirement."

        Design: Difficulty/non_linear_state_machine/list_version_review_cycle_revision_round_ceiling
        """
        setup = _version_at_the_revision_ceiling()
        published = validate_success(api_client.publish_list_version(
            setup["version"]["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert published["state"] == "PUBLISHED"

        response = api_client.request_changes_list_version(
            setup["version"]["id"], f.note_payload("Round 4: one more pass."),
            BEVERAGE_DIRECTOR_HEADERS)

        validate_error(response, ERR_LIST_VERSION_NOT_IN_REVIEW)
        after = _version(setup["version"]["id"])
        assert after["state"] == "PUBLISHED"
        assert after["revision_round"] == 3


def _allocated_cleared_offer():
    """A 6-bottle offer of a CLEARED distributor, fully granted to one venue, so
    fulfillment_state is ALLOCATED and compliance_state is CLEARED."""
    fx.set_clock(CLOCK)
    venue = _venue()
    distributor = fx.create_cleared_distributor(
        name="Coastal Selections", license_number="LIC-88120",
        allocation_tier="A", on_time_delivery_pct=96.5)
    wine = fx.create_wine(producer="Domaine Leflaive", cuvee="Puligny",
                          vintage_year=2021, category="RED",
                          reference_cost_cents=4500, bottle_size_ml=750,
                          case_pack=6, is_allocated=True)
    offer = fx.create_offer(distributor, wine, offered_bottles=6,
                            unit_cost_cents=4500,
                            response_deadline="2026-09-30T00:00:00Z")
    claim = fx.file_claim(offer, venue, 6)
    allocated = fx.allocate(offer)
    assert allocated["fulfillment_state"] == "ALLOCATED"
    assert allocated["compliance_state"] == "CLEARED"
    return {"venue": venue, "distributor": distributor, "wine": wine,
            "offer": allocated, "claim": claim}


def _review(distributor_id, decision, note):
    return validate_success(api_client.create_compliance_review(
        distributor_id, f.compliance_review_payload(decision, note=note),
        COMPLIANCE_OFFICER_HEADERS))


def _offer_row(offer_id):
    return get_success_data(
        api_client.get_allocation_offer(offer_id, BEVERAGE_DIRECTOR_HEADERS))


def _claim_row(claim_id):
    return get_success_data(
        api_client.get_allocation_claim(claim_id, BEVERAGE_DIRECTOR_HEADERS))


class TestOfferComplianceDimensionIsOrthogonal:
    """A compliance review moves an ALLOCATED offer's compliance dimension twice
    over while its fulfilment dimension never budges."""

    def test_hold_review_blocks_an_allocated_offer_without_moving_fulfilment(self):
        """The offer becomes BLOCKED and stays ALLOCATED.

        "When a review leaves the distributor in `HOLD`, every offer of that distributor whose compliance dimension reads `PENDING_LICENSE_CHECK` moves `PENDING_LICENSE_CHECK → BLOCKED` and every offer reading `CLEARED` moves `CLEARED → BLOCKED`; each such offer's `version` increments by 1 and its `updated_at` is refreshed, and no offer's `fulfillment_state` changes — an offer that has already allocated its bottles stays `ALLOCATED` while becoming `BLOCKED`."

        Design: Difficulty/non_linear_state_machine/allocation_offer_compliance_dimension_moves_without_fulfillment
        """
        setup = _allocated_cleared_offer()
        before = _offer_row(setup["offer"]["id"])

        distributor = _review(setup["distributor"]["id"], "HOLD",
                              "State licence suspended pending audit.")

        assert distributor["compliance_state"] == "HOLD"
        assert distributor["last_review_note"] == (
            "State licence suspended pending audit.")
        offer = _offer_row(setup["offer"]["id"])
        assert offer["compliance_state"] == "BLOCKED"
        assert offer["fulfillment_state"] == "ALLOCATED"
        assert offer["unallocated_bottles"] == 0
        assert offer["version"] == before["version"] + 1, (
            "the blocked offer's version must increment by exactly 1")

    def test_clearing_review_restores_the_compliance_dimension_only(self):
        """A second review moves BLOCKED back to CLEARED and leaves ALLOCATED alone.

        "When a review leaves the distributor in `CLEARED`, every offer of that distributor whose compliance dimension reads `BLOCKED` moves `BLOCKED → CLEARED`, and every offer reading `PENDING_LICENSE_CHECK` moves `PENDING_LICENSE_CHECK → CLEARED`, again with `version` incremented by 1 and again without touching the fulfilment dimension."

        Design: Difficulty/non_linear_state_machine/allocation_offer_compliance_dimension_moves_without_fulfillment
        """
        setup = _allocated_cleared_offer()
        _review(setup["distributor"]["id"], "HOLD",
                "State licence suspended pending audit.")
        blocked = _offer_row(setup["offer"]["id"])
        assert blocked["compliance_state"] == "BLOCKED"

        distributor = _review(setup["distributor"]["id"], "CLEARED",
                              "Audit closed, licence reinstated.")

        assert distributor["compliance_state"] == "CLEARED"
        offer = _offer_row(setup["offer"]["id"])
        assert offer["compliance_state"] == "CLEARED"
        assert offer["fulfillment_state"] == "ALLOCATED"
        assert offer["unallocated_bottles"] == 0
        assert offer["version"] == blocked["version"] + 1

    def test_granted_claim_survives_both_reviews_untouched(self):
        """The claim stays GRANTED with all six bottles across BLOCKED and CLEARED.

        "An offer is the one record in this system that carries two state dimensions at once, and they never move each other."

        Design: Difficulty/non_linear_state_machine/allocation_offer_compliance_dimension_moves_without_fulfillment
        """
        setup = _allocated_cleared_offer()

        _review(setup["distributor"]["id"], "HOLD",
                "State licence suspended pending audit.")
        after_hold = _claim_row(setup["claim"]["id"])
        assert after_hold["state"] == "GRANTED"
        assert after_hold["granted_bottles"] == 6

        _review(setup["distributor"]["id"], "CLEARED",
                "Audit closed, licence reinstated.")
        after_clear = _claim_row(setup["claim"]["id"])
        assert after_clear["state"] == "GRANTED"
        assert after_clear["granted_bottles"] == 6
        assert _offer_row(setup["offer"]["id"])["unallocated_bottles"] == 0

    def test_the_two_state_filters_are_independent_of_each_other(self):
        """After the offer is cleared again nothing matches compliance BLOCKED while
        the fulfilment filter still returns it.

        "Offers may be listed filtered by `distributor_id`, by `wine_id`, by `fulfillment_state` and by `compliance_state`, and the two state filters are independent of each other."

        Design: Difficulty/non_linear_state_machine/allocation_offer_compliance_dimension_moves_without_fulfillment
        """
        setup = _allocated_cleared_offer()
        _review(setup["distributor"]["id"], "HOLD",
                "State licence suspended pending audit.")
        blocked, _meta = validate_paginated(api_client.list_allocation_offers(
            BEVERAGE_DIRECTOR_HEADERS, params={"compliance_state": "BLOCKED"}))
        assert [row["id"] for row in blocked] == [setup["offer"]["id"]]

        _review(setup["distributor"]["id"], "CLEARED",
                "Audit closed, licence reinstated.")

        blocked_after, _meta = validate_paginated(api_client.list_allocation_offers(
            BEVERAGE_DIRECTOR_HEADERS, params={"compliance_state": "BLOCKED"}))
        assert blocked_after == [], (
            "no offer should remain BLOCKED after the clearing review")
        allocated, _meta = validate_paginated(api_client.list_allocation_offers(
            BEVERAGE_DIRECTOR_HEADERS, params={"fulfillment_state": "ALLOCATED"}))
        assert [row["id"] for row in allocated] == [setup["offer"]["id"]]
