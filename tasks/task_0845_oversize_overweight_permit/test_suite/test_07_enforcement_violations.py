"""Enforcement: the critical-violation revoke cascade, the annual-superload vs
unpaid-fees priority pair at submit, violation adjudication state errors, the
suspend/dismiss reinstatement cycle, and the submit fiscal/standing guards.
"""
from test_helpers import (
    TEST_USERS, make_carrier_headers,
    validate_success, validate_error,
    ApiErrorId,
    new_carrier, new_permit, add_segment, submit,
    drive_overweight_permit_to_issued, drive_permit_to_issued_then_suspend,
    new_structure, cite_violation, cite_and_uphold,
)

ENFORCER = TEST_USERS["enforcement_officer_headers"]
ADMIN = TEST_USERS["dot_admin_headers"]


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade / critical_violation_revoke_segment_structure_cascade
# ---------------------------------------------------------------------------
def test_critical_uphold_revokes_permit(api):
    """PRD §3.8: "Upholding moves the violation to `UPHELD`, adds its
    `penalty_cents` to the carrier's `unpaid_fee_balance_cents`, and recomputes the
    carrier's `compliance_standing`; if the severity is `CRITICAL` and the cited
    permit is currently `SUSPENDED`, the permit moves to the terminal `REVOKED`
    state."

    Design: Difficulty/transitive_cascade/critical_violation_revoke_segment_structure_cascade
    """
    structure = new_structure(api, rated_capacity_tonnage=200, dead_load_tonnage=40)
    ctx = drive_permit_to_issued_then_suspend(api, structure, severity="CRITICAL", violation_type="OFF_ROUTE")
    upheld = validate_success(api.uphold_violation(ctx["violation"]["id"], ENFORCER), 200)
    assert upheld["status"] == "UPHELD"
    permit = validate_success(api.get_permit(ctx["permit_id"], ADMIN), 200)
    assert permit["status"] == "REVOKED"


def test_critical_uphold_releases_structure_tonnage(api):
    """PRD §3.8: "Revocation triggered by a upheld critical violation fires the
    full unwind cascade: each `RESERVED` route segment moves to `RELEASED` and its
    `load_tonnage` is subtracted from the crossed structure's `committed_tonnage`
    (with `available_tonnage` and `posture` recomputed)".

    Design: Difficulty/transitive_cascade/critical_violation_revoke_segment_structure_cascade
    """
    structure = new_structure(api, rated_capacity_tonnage=200, dead_load_tonnage=40)
    ctx = drive_permit_to_issued_then_suspend(api, structure, severity="CRITICAL", violation_type="OFF_ROUTE")
    api.uphold_violation(ctx["violation"]["id"], ENFORCER)
    data = validate_success(api.get_structure(structure["id"], ADMIN), 200)
    assert data["committed_tonnage"] == 0
    assert data["available_tonnage"] == 200


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict / submit_annual_superload_beats_unpaid_fees
# ---------------------------------------------------------------------------
def _carrier_with_unpaid_and_annual_superload(api):
    carrier = new_carrier(api)
    throwaway = new_permit(api, carrier["id"], gross_weight_lbs=120000)
    cite_and_uphold(api, throwaway["id"], violation_type="OVER_DIMENSION", severity="MINOR")
    annual = new_permit(api, carrier["id"], permit_type="ANNUAL", gross_weight_lbs=210000, num_axles=13,
                        valid_from="2026-06-01T00:00:00Z", valid_until="2026-12-31T00:00:00Z")
    add_segment(api, annual["id"], carrier["id"])
    return carrier, annual["id"]


def test_submit_annual_superload_error_wins(api):
    """PRD §3.3: "the load must not be an `ANNUAL` superload, or
    `ERR_ANNUAL_SUPERLOAD_FORBIDDEN`; and the carrier's `unpaid_fee_balance_cents`
    must be exactly 0, or `ERR_UNPAID_FEES`."

    The annual-superload check precedes the unpaid-fees check, so the annual
    error wins.

    Design: Difficulty/priority_pair_validation_conflict/submit_annual_superload_beats_unpaid_fees
    """
    carrier, annual_id = _carrier_with_unpaid_and_annual_superload(api)
    before = validate_success(api.get_carrier(carrier["id"], ADMIN), 200)
    assert before["unpaid_fee_balance_cents"] == 100000
    resp = api.submit_permit(annual_id, make_carrier_headers(carrier["id"]))
    validate_error(resp, ApiErrorId.ERR_ANNUAL_SUPERLOAD_FORBIDDEN)


def test_submit_annual_superload_returns_422_not_402(api):
    """PRD §3.3: "the load must not be an `ANNUAL` superload, or
    `ERR_ANNUAL_SUPERLOAD_FORBIDDEN`; and the carrier's `unpaid_fee_balance_cents`
    must be exactly 0, or `ERR_UNPAID_FEES`."

    Design: Difficulty/priority_pair_validation_conflict/submit_annual_superload_beats_unpaid_fees
    """
    carrier, annual_id = _carrier_with_unpaid_and_annual_superload(api)
    resp = api.submit_permit(annual_id, make_carrier_headers(carrier["id"]))
    assert resp.status_code == 422, f"expected 422, got {resp.status_code}"


# ---------------------------------------------------------------------------
# Corner: state_machines
# ---------------------------------------------------------------------------
def test_contest_upheld_violation_rejected(api):
    """PRD §3.8: "The carrier may contest an `OPEN` violation it is cited under,
    moving it to `CONTESTED`."
    PRD §2.10: "the state-machine precondition that the target is in a state from
    which the transition is defined (... `ERR_INVALID_VIOLATION_STATE` ...)".

    Design: Corner/state_machines/error_contest_upheld_violation
    """
    carrier = new_carrier(api)
    permit = new_permit(api, carrier["id"])
    v = cite_and_uphold(api, permit["id"], violation_type="OVER_DIMENSION", severity="MINOR")
    resp = api.contest_violation(v["id"], make_carrier_headers(carrier["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_VIOLATION_STATE)


def test_dismiss_reinstates_suspended_permit(api):
    """PRD §3.8: "Dismissing moves the violation to `DISMISSED`; if the cited
    permit is `SUSPENDED` and no other non-`DISMISSED` violation remains for that
    permit, the permit is reinstated from `SUSPENDED` back to `ISSUED`."

    Design: Corner/state_machines/violation_dismiss_reinstates_suspended_permit
    """
    ctx = drive_overweight_permit_to_issued(api, structure=None, gross_weight_lbs=120000)
    permit_id = ctx["permit"]["id"]
    v = cite_violation(api, permit_id, violation_type="OFF_SCHEDULE", severity="MAJOR")
    dismissed = validate_success(api.dismiss_violation(v["id"], ENFORCER), 200)
    assert dismissed["status"] == "DISMISSED"
    permit = validate_success(api.get_permit(permit_id, ADMIN), 200)
    assert permit["status"] == "ISSUED"


# ---------------------------------------------------------------------------
# Corner: validations — submit fiscal / standing guards
# ---------------------------------------------------------------------------
def test_submit_unpaid_fees(api):
    """PRD §3.3: "the carrier's `unpaid_fee_balance_cents` must be exactly 0, or
    `ERR_UNPAID_FEES`."

    Design: Corner/validations/error_unpaid_fees_on_submit
    """
    carrier = new_carrier(api)
    throwaway = new_permit(api, carrier["id"], gross_weight_lbs=120000)
    cite_and_uphold(api, throwaway["id"], violation_type="OVER_DIMENSION", severity="MINOR")
    permit = new_permit(api, carrier["id"], gross_weight_lbs=120000)
    add_segment(api, permit["id"], carrier["id"])
    resp = api.submit_permit(permit["id"], make_carrier_headers(carrier["id"]))
    validate_error(resp, ApiErrorId.ERR_UNPAID_FEES)


def test_submit_carrier_suspended(api):
    """PRD §3.3: "the carrier's `compliance_standing` must not be `SUSPENDED`, or
    the request is rejected with `ERR_CARRIER_SUSPENDED`".
    PRD §2.9: "`SUSPENDED` once the count reaches 5 or more."

    Design: Corner/validations/error_carrier_suspended_on_submit
    """
    carrier = new_carrier(api)
    throwaway = new_permit(api, carrier["id"], gross_weight_lbs=120000)
    for _ in range(5):
        cite_and_uphold(api, throwaway["id"], violation_type="OVER_DIMENSION", severity="MINOR")
    before = validate_success(api.get_carrier(carrier["id"], ADMIN), 200)
    assert before["compliance_standing"] == "SUSPENDED"
    permit = new_permit(api, carrier["id"], gross_weight_lbs=120000)
    add_segment(api, permit["id"], carrier["id"])
    resp = api.submit_permit(permit["id"], make_carrier_headers(carrier["id"]))
    validate_error(resp, ApiErrorId.ERR_CARRIER_SUSPENDED)
