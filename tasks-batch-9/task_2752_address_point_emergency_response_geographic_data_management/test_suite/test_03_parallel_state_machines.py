"""Rule non_linear_state_machine — cyclic and parallel-dimension lifecycles.

Two entities are covered. The DiscrepancyCase re-enters a state it already
left, walking OPEN -> PROPOSAL_PENDING -> COUNTERED -> PROPOSAL_PENDING, and
the AddressAssignmentRequest carries three parallel dimensions where a utility
hold demotes the derived join without disturbing the review dimension.
"""

from test_helpers import (
    ANALYST_HEADERS,
    CLOCK_STARTUP_INPUT,
    assert_assignment_request,
    assert_discrepancy_case,
    assert_discrepancy_proposal,
    assert_road_centerline,
    assert_slot_counters,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx


# ===========================================================================
# Instance discrepancy_case_proposal_counter_cycle_two_rounds
# ===========================================================================
def _open_case_and_file_three_rounds(api):
    """LARCO, LAW/FIRE, a DRAFT road, then rounds 1, 2 and 3 of a negotiation."""
    jurisdiction = fx.setup_jurisdiction(api)
    j_id = jurisdiction["id"]
    parties = fx.setup_two_agencies(api, j_id)
    law_id = parties["opener_id"]
    fire_id = parties["counterparty_id"]

    road = fx.setup_road(api, j_id, primary_name="N MAPLE STREET")
    road_id = road["id"]

    case = fx.setup_discrepancy_case(
        api,
        road_id,
        law_id,
        fire_id,
        description="Sheriff CAD carries N MAPLE ST, fire RMS carries N MAPLE AVE",
    )
    case_id = case["id"]
    assert_discrepancy_case(case, status="OPEN", round_count=0)
    assert case["current_proposal_id"] is None, "a fresh case has no current proposal"

    p1 = fx.file_proposal(
        api, case_id, law_id, "N MAPLE STREET", rationale="Round 1 filed by the opener"
    )
    p2 = fx.file_proposal(
        api,
        case_id,
        fire_id,
        "N MAPLE AVE",
        rationale="Round 2 counter filed by the counterparty",
    )
    p3 = fx.file_proposal(
        api,
        case_id,
        law_id,
        "N MAPLE STREET",
        rationale="Round 3 re-filed by the opener",
    )
    return {
        "j_id": j_id,
        "law_id": law_id,
        "fire_id": fire_id,
        "road_id": road_id,
        "case_id": case_id,
        "p1": p1,
        "p2": p2,
        "p3": p3,
    }


def test_third_filing_re_enters_proposal_pending_at_round_three(api):
    """Round 3 walks COUNTERED back to PROPOSAL_PENDING rather than to a new stage.

    The first filing on an `OPEN` case advances it `OPEN → PROPOSAL_PENDING`; the next filing, necessarily by the other side, advances it `PROPOSAL_PENDING → COUNTERED`; the one after that advances it `COUNTERED → PROPOSAL_PENDING`; and the cycle continues.

    Design: Difficulty/non_linear_state_machine/discrepancy_case_proposal_counter_cycle_two_rounds
    """
    fx.set_clock(api, CLOCK_STARTUP_INPUT)
    built = _open_case_and_file_three_rounds(api)

    case = fx.read_case(api, built["case_id"])
    assert_discrepancy_case(case, status="PROPOSAL_PENDING", round_count=3)
    assert case["current_proposal_id"] == built["p3"]["id"], (
        "the newest filing becomes the case's current proposal"
    )


def test_proposal_log_projects_two_countered_rounds_and_one_pending_round(api):
    """The append-only log projects rounds 1 and 2 to COUNTERED and round 3 to PENDING.

    For a proposal on a case: if the case's `status` is `ADOPTED` and this proposal is the case's `current_proposal_id`, the proposal projects to `ADOPTED`; otherwise, if the case's `status` is `ESCALATED` or `ARBITRATED`, it projects to `VOIDED`; otherwise, if some proposal on the same case has a greater `round_number`, it projects to `COUNTERED`; otherwise it projects to `PENDING`.

    Design: Difficulty/non_linear_state_machine/discrepancy_case_proposal_counter_cycle_two_rounds
    """
    fx.set_clock(api, CLOCK_STARTUP_INPUT)
    built = _open_case_and_file_three_rounds(api)

    rows = fx.read_proposals(api, built["case_id"])
    assert len(rows) == 3, "three filings were recorded on this case"
    by_id = {row["id"]: row for row in rows}

    first = by_id[built["p1"]["id"]]
    assert_discrepancy_proposal(
        first, round_number=1, proposed_by_side="OPENER", status="COUNTERED"
    )
    second = by_id[built["p2"]["id"]]
    assert_discrepancy_proposal(
        second, round_number=2, proposed_by_side="COUNTERPARTY", status="COUNTERED"
    )
    third = by_id[built["p3"]["id"]]
    assert_discrepancy_proposal(
        third, round_number=3, proposed_by_side="OPENER", status="PENDING"
    )
    assert [row["round_number"] for row in rows] == [1, 2, 3], (
        "the proposal log is emitted oldest filing first"
    )


def test_third_filing_does_not_escalate_the_case_or_lift_the_road_freeze(api):
    """Reaching three rounds is not exceeding them, so escalated_at stays null.

    Filing is permitted while `round_count` is strictly below three.

    Design: Difficulty/non_linear_state_machine/discrepancy_case_proposal_counter_cycle_two_rounds
    """
    fx.set_clock(api, CLOCK_STARTUP_INPUT)
    built = _open_case_and_file_three_rounds(api)

    case = fx.read_case(api, built["case_id"])
    assert_discrepancy_case(case, status="PROPOSAL_PENDING", round_count=3)
    assert case["escalated_at"] is None, (
        "round_count reached the three-round limit but did not exceed it"
    )

    road = fx.read_road(api, built["road_id"])
    assert_road_centerline(road, open_discrepancy_case_count=1)


# ===========================================================================
# Instance assignment_request_parallel_review_and_utility_dimensions
# ===========================================================================
def _cleared_but_unreviewed_request(api):
    """A VALIDATED road plus a two-unit request whose utilities are already CLEAR."""
    jurisdiction = fx.setup_jurisdiction(api)
    j_id = jurisdiction["id"]
    cell = fx.setup_coverage_cell(api, j_id, "C001")
    road = fx.setup_road(api, j_id, primary_name="N MAPLE STREET")
    road_id = road["id"]
    fx.validate_road(api, road_id)

    validated_road = fx.read_road(api, road_id)
    assert_road_centerline(validated_road, status="VALIDATED")
    assert_slot_counters(validated_road, 50, 50)

    request = fx.setup_assignment_request(
        api, road_id, parcel_id="8712300045", requested_unit_count=2
    )
    assert_assignment_request(
        request,
        review_status="PENDING_REVIEW",
        utility_status="PENDING_UTILITY",
        fulfillment_status="OPEN",
        requested_unit_count=2,
        minted_point_count=0,
    )
    cleared = fx.utility_clearance(
        api,
        request["id"],
        "CLEAR",
        utility_note="Water and sewer taps confirmed available",
    )
    assert_assignment_request(
        cleared,
        review_status="PENDING_REVIEW",
        utility_status="UTILITY_CLEARED",
        fulfillment_status="OPEN",
    )
    return {
        "j_id": j_id,
        "cell_id": cell["id"],
        "road_id": road_id,
        "request_id": request["id"],
    }


def test_utility_hold_demotes_fulfillment_while_review_stays_gis_approved(api):
    """The re-imposed hold pushes READY_TO_ASSIGN back to OPEN and leaves the review alone.

    Re-imposing a hold, `UTILITY_CLEARED → UTILITY_HELD`, increments the `version` by 1 and **demotes** `fulfillment_status` from `READY_TO_ASSIGN` back to `OPEN` when it was sitting there.

    Design: Difficulty/non_linear_state_machine/assignment_request_parallel_review_and_utility_dimensions
    """
    fx.set_clock(api, CLOCK_STARTUP_INPUT)
    built = _cleared_but_unreviewed_request(api)
    request_id = built["request_id"]

    approved = fx.gis_review(
        api,
        request_id,
        "APPROVE",
        review_note="Parcel fronts the LEFT side; range has capacity",
    )
    assert_assignment_request(
        approved,
        review_status="GIS_APPROVED",
        utility_status="UTILITY_CLEARED",
        fulfillment_status="READY_TO_ASSIGN",
    )

    held = fx.utility_clearance(
        api,
        request_id,
        "HOLD",
        utility_note="Dry-utility conflict discovered after approval",
    )
    assert_assignment_request(
        held,
        review_status="GIS_APPROVED",
        utility_status="UTILITY_HELD",
        fulfillment_status="OPEN",
        version=approved["version"] + 1,
    )
    assert held["assigned_address_point_id"] is None, (
        "a demoted request has minted nothing"
    )
    assert held["minted_point_count"] == 0, "no points were minted before the assign"


def test_second_clearance_re_promotes_the_request_and_the_mint_fulfills_it(api):
    """Lifting the hold restores READY_TO_ASSIGN, and the assign mints one base plus two units.

    The request records `assigned_address_point_id` as the base point's identifier and `minted_point_count` as one plus `requested_unit_count` — a count that stands regardless of what happens to those points later.

    Design: Difficulty/non_linear_state_machine/assignment_request_parallel_review_and_utility_dimensions
    """
    fx.set_clock(api, CLOCK_STARTUP_INPUT)
    built = _cleared_but_unreviewed_request(api)
    request_id = built["request_id"]

    fx.gis_review(
        api,
        request_id,
        "APPROVE",
        review_note="Parcel fronts the LEFT side; range has capacity",
    )
    held = fx.utility_clearance(
        api,
        request_id,
        "HOLD",
        utility_note="Dry-utility conflict discovered after approval",
    )
    recleared = fx.utility_clearance(
        api, request_id, "CLEAR", utility_note="Conflict resolved; hold lifted"
    )
    assert_assignment_request(
        recleared,
        review_status="GIS_APPROVED",
        utility_status="UTILITY_CLEARED",
        fulfillment_status="READY_TO_ASSIGN",
        version=held["version"] + 1,
    )

    fulfilled = validate_success(
        api.assign_assignment_request(request_id, {}, ANALYST_HEADERS), 200
    )
    assert_assignment_request(
        fulfilled,
        review_status="GIS_APPROVED",
        utility_status="UTILITY_CLEARED",
        fulfillment_status="FULFILLED",
        assigned_house_number=100,
        minted_point_count=3,
    )
    assert fulfilled["assigned_address_point_id"] is not None, (
        "the base point's identifier is recorded on the request"
    )


def test_minted_base_point_and_two_units_consume_exactly_one_assignable_slot(api):
    """Three points are minted, yet only the base point spends a slot on the LEFT range.

    The centerline's slot counters are refreshed, the base point consuming exactly one slot while the units consume none, and the request's `version` increments by 1.

    Design: Difficulty/non_linear_state_machine/assignment_request_parallel_review_and_utility_dimensions
    """
    fx.set_clock(api, CLOCK_STARTUP_INPUT)
    built = _cleared_but_unreviewed_request(api)
    request_id = built["request_id"]
    road_id = built["road_id"]

    fx.gis_review(
        api,
        request_id,
        "APPROVE",
        review_note="Parcel fronts the LEFT side; range has capacity",
    )
    fx.utility_clearance(
        api,
        request_id,
        "HOLD",
        utility_note="Dry-utility conflict discovered after approval",
    )
    ready = fx.utility_clearance(
        api, request_id, "CLEAR", utility_note="Conflict resolved; hold lifted"
    )
    fulfilled = validate_success(
        api.assign_assignment_request(request_id, {}, ANALYST_HEADERS), 200
    )
    assert fulfilled["version"] == ready["version"] + 1, (
        "the assign increments the request's version exactly once"
    )

    road = fx.read_road(api, road_id)
    assert_slot_counters(road, 49, 50)

    rows, meta = validate_paginated(
        api.list_address_points(
            {"road_centerline_id": road_id, "limit": 100}, ANALYST_HEADERS
        )
    )
    assert meta["total_count"] == 3, "one base point and two unit points were minted"
    assert len(rows) == 3, "all three minted points are listed on this centerline"
    assert sorted(row["house_number"] for row in rows) == [100, 100, 100], (
        "the units share the base point's house number 100"
    )
