"""Permit state machine: the return/resubmit cycle, vacuous approval when no
structures are crossed, and invalid/terminal/idempotency transition errors.
"""
from test_helpers import (
    TEST_USERS, make_carrier_headers,
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    new_carrier, new_permit, add_segment, submit, begin_review,
)

OFFICER = TEST_USERS["permit_officer_headers"]


def _submitted_overweight(api, gross=120000):
    carrier = new_carrier(api)
    permit = new_permit(api, carrier["id"], gross_weight_lbs=gross)
    add_segment(api, permit["id"], carrier["id"])
    submit(api, permit["id"], carrier["id"])
    return carrier, permit["id"]


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / permit_return_resubmit_cycle
# ---------------------------------------------------------------------------
def test_return_moves_permit_to_returned_for_correction(api):
    """PRD §3.6: "A reviewer may return the permit for correction — optionally
    recording a `reason` — sending it to `RETURNED_FOR_CORRECTION`, from which the
    carrier revises and resubmits."

    Design: Difficulty/non_linear_state_machine/permit_return_resubmit_cycle
    """
    _c, permit_id = _submitted_overweight(api)
    begin_review(api, permit_id, actor="officer")
    returned = validate_success(api.return_permit(permit_id, OFFICER, {"reason": "fix overhang"}), 200)
    assert returned["status"] == "RETURNED_FOR_CORRECTION"


def test_resubmit_from_returned_closes_cycle(api):
    """PRD §3.3: "Submitting an application — whether the first submission from
    `DRAFT` or a resubmission from `RETURNED_FOR_CORRECTION` after corrections —
    is a carrier action that moves the permit to `SUBMITTED` and recomputes its
    derived attributes."

    Design: Difficulty/non_linear_state_machine/permit_return_resubmit_cycle
    """
    carrier, permit_id = _submitted_overweight(api)
    begin_review(api, permit_id, actor="officer")
    api.return_permit(permit_id, OFFICER, {"reason": "fix overhang"})
    resubmitted = submit(api, permit_id, carrier["id"])
    assert resubmitted["status"] == "SUBMITTED"


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / empty_bridge_analyses_vacuous_approve
# ---------------------------------------------------------------------------
def test_no_structure_produces_empty_bridge_analyses(api):
    """PRD §3.3: "it creates a `BridgeAnalysis` in `REQUESTED` status for each
    route segment that names a structure".

    A route crossing zero structures spawns no analyses.

    Design: Difficulty/boundary_precision_check/empty_bridge_analyses_vacuous_approve
    """
    _c, permit_id = _submitted_overweight(api)
    _data, meta = validate_paginated(api.list_bridge_analyses(OFFICER, params={"permit_id": permit_id}))
    assert meta["total_count"] == 0


def test_approve_succeeds_with_no_bridges(api):
    """PRD §3.6: "Next, every bridge analysis must be `CLEARED` — none may still
    be `REQUESTED` or `CONDITIONAL` (that is, pending) — or approval is refused
    with `ERR_BRIDGE_ANALYSIS_INCOMPLETE`."

    With zero analyses the all-cleared check passes vacuously and approval moves
    the permit to APPROVED.

    Design: Difficulty/boundary_precision_check/empty_bridge_analyses_vacuous_approve
    """
    _c, permit_id = _submitted_overweight(api)
    begin_review(api, permit_id, actor="officer")
    approved = validate_success(api.approve_permit(permit_id, OFFICER), 200)
    assert approved["status"] == "APPROVED"


# ---------------------------------------------------------------------------
# Corner: state_machines
# ---------------------------------------------------------------------------
def test_approve_from_draft_rejected(api):
    """PRD §3.6: "Approval from a state where it is undefined yields
    `ERR_INVALID_PERMIT_STATE`."

    Design: Corner/state_machines/error_approve_from_draft_invalid_transition
    """
    carrier = new_carrier(api)
    permit = new_permit(api, carrier["id"])
    resp = api.approve_permit(permit["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_INVALID_PERMIT_STATE)


def test_resubmit_rejected_permit_locked(api):
    """PRD §3.6: "A reviewer may also reject the permit outright — again optionally
    recording a `reason` — moving it to the terminal `REJECTED` state."
    PRD §3.3: "submission must be a defined transition from the current state or it
    is refused with `ERR_INVALID_PERMIT_STATE`."

    Design: Corner/state_machines/error_submit_from_rejected_terminal_lockdown
    """
    carrier, permit_id = _submitted_overweight(api)
    begin_review(api, permit_id, actor="officer")
    api.reject_permit(permit_id, OFFICER, {"reason": "unsafe"})
    resp = api.submit_permit(permit_id, make_carrier_headers(carrier["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_PERMIT_STATE)


def test_submit_empty_route_rejected(api):
    """PRD §3.3: "the permit must have at least one route segment, or
    `ERR_ROUTE_EMPTY`".

    Design: Corner/validations/error_route_empty_on_submit
    """
    carrier = new_carrier(api)
    permit = new_permit(api, carrier["id"])
    resp = api.submit_permit(permit["id"], make_carrier_headers(carrier["id"]))
    validate_error(resp, ApiErrorId.ERR_ROUTE_EMPTY)


def test_double_submit_rejected(api):
    """PRD §3.3: "submission must be a defined transition from the current state or
    it is refused with `ERR_INVALID_PERMIT_STATE`."

    Design: Corner/state_machines/error_double_submit_idempotency
    """
    carrier, permit_id = _submitted_overweight(api)
    resp = api.submit_permit(permit_id, make_carrier_headers(carrier["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_PERMIT_STATE)
