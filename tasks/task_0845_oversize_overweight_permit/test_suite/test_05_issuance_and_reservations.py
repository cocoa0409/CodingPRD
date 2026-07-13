"""Issuance: the issue->bond->carrier cascade, structure clearance-buffer and
capacity/closed/travel-time guards, insufficient escrow, escort requirement, and
the {state, fiscal} priority-pair conflict.
"""
from test_helpers import (
    TEST_USERS,
    validate_success, validate_error,
    ApiErrorId,
    new_carrier, new_structure, new_permit, add_segment, submit, begin_review,
    approve, issue, first_bridge_analysis_id, review_bridge,
    drive_overweight_permit_to_issued, drive_superload_permit_to_approved,
)

OFFICER = TEST_USERS["permit_officer_headers"]
ADMIN = TEST_USERS["dot_admin_headers"]


def _approved_permit_crossing(api, structure, cross_start, cross_end, gross=120000, method="LRFR"):
    carrier = new_carrier(api)
    permit = new_permit(api, carrier["id"], gross_weight_lbs=gross)
    add_segment(api, permit["id"], carrier["id"], structure_id=structure["id"],
                planned_cross_start_utc=cross_start, planned_cross_end_utc=cross_end)
    submit(api, permit["id"], carrier["id"])
    begin_review(api, permit["id"], actor="officer")
    ba_id = first_bridge_analysis_id(api, permit["id"])
    review_bridge(api, ba_id, method=method)
    approve(api, permit["id"], actor="officer")
    return carrier["id"], permit["id"]


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade / issue_permit_bond_carrier_cascade
# ---------------------------------------------------------------------------
def test_issue_superload_debits_escrow(api):
    """PRD §3.6: "For a superload, the bond moves from `DRAFT` to `ACTIVE`: the
    carrier's `escrow_balance_cents` is reduced by the bond `amount_cents`, the
    carrier's `active_bond_amount_cents` is increased by the same amount, and the
    carrier's `compliance_standing` is recomputed."

    Design: Difficulty/transitive_cascade/issue_permit_bond_carrier_cascade
    """
    ctx = drive_superload_permit_to_approved(api, escrow_cents=10_000_000, gross_weight_lbs=210000)
    issued = issue(api, ctx["permit"]["id"])
    assert issued["status"] == "ISSUED"
    carrier = validate_success(api.get_carrier(ctx["carrier"]["id"], ADMIN), 200)
    assert carrier["escrow_balance_cents"] == 4000000


def test_issue_superload_credits_active_bond(api):
    """PRD §3.6: "the carrier's `active_bond_amount_cents` is increased by the same
    amount" [as the bond amount_cents debited from escrow on activation].

    Design: Difficulty/transitive_cascade/issue_permit_bond_carrier_cascade
    """
    ctx = drive_superload_permit_to_approved(api, escrow_cents=10_000_000, gross_weight_lbs=210000)
    issue(api, ctx["permit"]["id"])
    carrier = validate_success(api.get_carrier(ctx["carrier"]["id"], ADMIN), 200)
    assert carrier["active_bond_amount_cents"] == 6000000


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap / structure_crossing_buffer_conflict
# ---------------------------------------------------------------------------
def _buffer_conflict(api):
    structure = new_structure(api, rated_capacity_tonnage=400, dead_load_tonnage=40)
    p1 = drive_overweight_permit_to_issued(api, structure=structure, gross_weight_lbs=120000,
                                           cross_start="2026-06-05T10:00:00Z",
                                           cross_end="2026-06-05T10:30:00Z", method="LFR")
    _c2, p2_id = _approved_permit_crossing(api, structure,
                                           "2026-06-05T10:40:00Z", "2026-06-05T11:10:00Z", method="LFR")
    return structure, p1["permit"]["id"], p2_id


def test_issue_blocked_by_structure_window_buffer(api):
    """PRD §3.6: "no other `RESERVED` route segment on the same structure may lie
    within 30 minutes of this segment's crossing window
    `[planned_cross_start_utc, planned_cross_end_utc]` (the interval closed and
    extended by the 30-minute clearance buffer on each side), or
    `ERR_STRUCTURE_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/structure_crossing_buffer_conflict
    """
    _structure, _p1_id, p2_id = _buffer_conflict(api)
    resp = api.issue_permit(p2_id, OFFICER)
    validate_error(resp, ApiErrorId.ERR_STRUCTURE_WINDOW_CONFLICT)


def test_buffer_conflict_leaves_only_first_reserved(api):
    """PRD §3.6: "for a crossing segment, its `load_tonnage` is added to the
    structure's `committed_tonnage` and that structure's `available_tonnage` and
    `posture` are recomputed."

    Only permit1 reserved (60t); the rejected permit2 issue commits nothing.

    Design: Difficulty/resource_temporal_overlap/structure_crossing_buffer_conflict
    """
    structure, _p1_id, p2_id = _buffer_conflict(api)
    api.issue_permit(p2_id, OFFICER)
    data = validate_success(api.get_structure(structure["id"], ADMIN), 200)
    assert data["committed_tonnage"] == 60


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict / issue_state_beats_insufficient_escrow
# ---------------------------------------------------------------------------
def _superload_submitted_zero_escrow(api):
    carrier = new_carrier(api)
    permit = new_permit(api, carrier["id"], gross_weight_lbs=210000, num_axles=13)
    add_segment(api, permit["id"], carrier["id"])
    submit(api, permit["id"], carrier["id"])
    return permit["id"]


def test_issue_state_error_wins_over_escrow(api):
    """PRD §2.10: "the state-machine precondition that the target is in a state
    from which the transition is defined (`ERR_INVALID_PERMIT_STATE`, ...); and
    finally the domain-specific business rules".

    A SUBMITTED (not APPROVED) superload with zero escrow fails the state check
    before the fiscal escrow check.

    Design: Difficulty/priority_pair_validation_conflict/issue_state_beats_insufficient_escrow
    """
    permit_id = _superload_submitted_zero_escrow(api)
    resp = api.issue_permit(permit_id, OFFICER)
    validate_error(resp, ApiErrorId.ERR_INVALID_PERMIT_STATE)


def test_issue_state_error_returns_409_not_402(api):
    """PRD §2.10: "the state-machine precondition that the target is in a state
    from which the transition is defined (`ERR_INVALID_PERMIT_STATE`, ...); and
    finally the domain-specific business rules".

    Design: Difficulty/priority_pair_validation_conflict/issue_state_beats_insufficient_escrow
    """
    permit_id = _superload_submitted_zero_escrow(api)
    resp = api.issue_permit(permit_id, OFFICER)
    assert resp.status_code == 409, f"expected 409, got {resp.status_code}"


# ---------------------------------------------------------------------------
# Corner: validations — issuance safety checks
# ---------------------------------------------------------------------------
def test_issue_structure_capacity_exceeded(api):
    """PRD §3.6: "the structure's `available_tonnage` must be at least the
    segment's `load_tonnage`, or `ERR_STRUCTURE_CAPACITY_EXCEEDED`".

    Design: Corner/validations/error_structure_capacity_exceeded_on_issue
    """
    structure = new_structure(api, rated_capacity_tonnage=120, dead_load_tonnage=0)
    drive_overweight_permit_to_issued(api, structure=structure, gross_weight_lbs=120000,
                                      cross_start="2026-06-05T10:00:00Z",
                                      cross_end="2026-06-05T10:30:00Z", method="LRFR")
    before = validate_success(api.get_structure(structure["id"], ADMIN), 200)
    assert before["available_tonnage"] == 60
    _c2, p2_id = _approved_permit_crossing(api, structure,
                                           "2026-06-05T14:00:00Z", "2026-06-05T14:30:00Z",
                                           gross=130000, method="LRFR")
    resp = api.issue_permit(p2_id, OFFICER)
    validate_error(resp, ApiErrorId.ERR_STRUCTURE_CAPACITY_EXCEEDED)


def test_issue_structure_closed(api):
    """PRD §3.6: "the structure's `posture` must not be `CLOSED`, or issuance
    fails with `ERR_STRUCTURE_CLOSED`".

    Design: Corner/validations/error_structure_closed_on_issue
    """
    structure = new_structure(api, rated_capacity_tonnage=120, dead_load_tonnage=0)
    drive_overweight_permit_to_issued(api, structure=structure, gross_weight_lbs=120000,
                                      cross_start="2026-06-05T10:00:00Z",
                                      cross_end="2026-06-05T10:30:00Z", method="LRFR")
    drive_overweight_permit_to_issued(api, structure=structure, gross_weight_lbs=120000,
                                      cross_start="2026-06-05T12:00:00Z",
                                      cross_end="2026-06-05T12:30:00Z", method="LRFR")
    closed = validate_success(api.get_structure(structure["id"], ADMIN), 200)
    assert closed["posture"] == "CLOSED"
    _c3, p3_id = _approved_permit_crossing(api, structure,
                                           "2026-06-05T15:00:00Z", "2026-06-05T15:30:00Z", method="LRFR")
    resp = api.issue_permit(p3_id, OFFICER)
    validate_error(resp, ApiErrorId.ERR_STRUCTURE_CLOSED)


def test_issue_travel_time_restricted(api):
    """PRD §3.6: "no route segment's crossing window may intersect a
    travel-restriction window applicable to the permit's `classification` (a
    restriction whose `applies_to_classification` is `ALL` or matches the
    classification), or issuance fails with `ERR_TRAVEL_TIME_RESTRICTED`."

    Design: Corner/validations/error_travel_time_restricted_on_issue
    """
    from test_helpers import new_travel_restriction
    structure = new_structure(api, rated_capacity_tonnage=200, dead_load_tonnage=40)
    new_travel_restriction(api, restriction_type="CURFEW", start_utc="2026-06-05T09:00:00Z",
                           end_utc="2026-06-05T11:00:00Z", applies_to_classification="ALL")
    _c, p_id = _approved_permit_crossing(api, structure,
                                         "2026-06-05T10:00:00Z", "2026-06-05T10:30:00Z", method="LFR")
    resp = api.issue_permit(p_id, OFFICER)
    validate_error(resp, ApiErrorId.ERR_TRAVEL_TIME_RESTRICTED)


def test_issue_insufficient_escrow(api):
    """PRD §3.6: "Finally, for a superload, a `DRAFT` bond must exist and the
    carrier's `escrow_balance_cents` must be at least the bond's `amount_cents`,
    or issuance fails with `ERR_INSUFFICIENT_ESCROW`."

    Design: Corner/validations/error_insufficient_escrow_on_issue
    """
    ctx = drive_superload_permit_to_approved(api, escrow_cents=0, gross_weight_lbs=210000)
    resp = api.issue_permit(ctx["permit"]["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_ESCROW)


def test_approve_escort_requirement_unmet(api):
    """PRD §3.6: "Then the count of `CONFIRMED` escort assignments must be at least
    the permit's `required_escort_count`, or approval is refused with
    `ERR_ESCORT_REQUIREMENT_UNMET`."

    Design: Corner/validations/error_escort_requirement_unmet_on_approve
    """
    from test_helpers import TEST_USERS as _TU
    carrier = new_carrier(api)
    permit = new_permit(api, carrier["id"], gross_weight_lbs=210000, num_axles=13)
    add_segment(api, permit["id"], carrier["id"])
    submit(api, permit["id"], carrier["id"])
    begin_review(api, permit["id"], actor="engineer")
    resp = api.approve_permit(permit["id"], _TU["bridge_engineer_headers"])
    validate_error(resp, ApiErrorId.ERR_ESCORT_REQUIREMENT_UNMET)
