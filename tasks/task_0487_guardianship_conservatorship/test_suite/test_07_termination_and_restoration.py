"""Case termination and restoration cascades and their guards.

Difficulty: depth-3 cascade from terminate (case -> appointment -> bond + count).
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
)
from test_helpers import factories as F
from test_helpers import fixtures as fx


# ===========================================================================
# Difficulty: terminate -> appointment REVOKED -> bond EXONERATED + count dec
# ===========================================================================
def test_terminate_revokes_appointment_and_exonerates_bond(api):
    """PRD 3.9: "every ACTIVE or SUSPENDED appointment on the case is revoked to
    REVOKED; each appointment that was ACTIVE decrements its fiduciary's
    open_appointment_count by one; each such appointment's APPROVED bond is
    exonerated to EXONERATED; every OPEN or FROZEN restricted account on the case
    is closed to CLOSED; and the protected person's active_case_id is cleared to
    null."

    Design: Difficulty/transitive_cascade/tc_terminate_revokes_appointment_then_exonerates_bond
    """
    ctx = fx.active_case(
        case_type="CONSERVATORSHIP",
        fiduciary_kind="PROFESSIONAL",
        person_overrides={"liquid_estate_cents": 8_000_000},
    )
    account = fx.open_restricted_account(ctx["case_id"], ctx["fiduciary_id"])
    terminated = validate_success(api.terminate_case(ctx["case_id"], fx.JUDGE))
    assert terminated["status"] == "TERMINATED"
    appt = get_success_data(api.get_appointment(ctx["appointment_id"], fx.JUDGE))
    assert appt["status"] == "REVOKED"
    bond = get_success_data(api.get_bond(ctx["bond_id"], fx.JUDGE))
    assert bond["status"] == "EXONERATED"
    fid = get_success_data(api.get_fiduciary(ctx["fiduciary_id"], fx.JUDGE))
    assert fid["open_appointment_count"] == 0
    acct = get_success_data(api.get_restricted_account(account["id"], fx.JUDGE))
    assert acct["status"] == "CLOSED"


def test_terminate_clears_active_case_keeps_capacity(api):
    """PRD 3.9: "Termination moves the case to TERMINATED and runs a cascade ...
    and the protected person's active_case_id is cleared to null. The person's
    capacity_status is unchanged by termination and remains
    ADJUDICATED_INCAPACITATED."

    Design: Difficulty/transitive_cascade/tc_terminate_revokes_appointment_then_exonerates_bond
    """
    ctx = fx.active_case(
        case_type="CONSERVATORSHIP",
        fiduciary_kind="PROFESSIONAL",
        person_overrides={"liquid_estate_cents": 8_000_000},
    )
    fx.open_restricted_account(ctx["case_id"], ctx["fiduciary_id"])
    api.terminate_case(ctx["case_id"], fx.JUDGE)
    person = get_success_data(api.get_protected_person(ctx["person_id"], fx.JUDGE))
    assert person["active_case_id"] is None
    assert person["capacity_status"] == "ADJUDICATED_INCAPACITATED"


# ===========================================================================
# Terminate guards
# ===========================================================================
def test_terminate_blocked_by_pending_expenditure(api):
    """PRD 3.9: "no Expenditure on the case may be in PENDING_COURT or APPROVED
    status (else ERR_PENDING_EXPENDITURES)".

    Design: Corner/state_machines/terminate_blocked_by_pending_expenditure
    """
    ctx = fx.funded_conservatorship(funding_cents=5_000_000, care_cap_cents=0, admin_cap_cents=2_000_000)
    fid = ctx["fiduciary_id"]
    exp = fx.create_expenditure(
        ctx["case_id"], ctx["budget_id"], fid,
        category="ADMIN", amount_cents=300_000, payee_name="Fee",
    )
    assert exp["status"] == "PENDING_COURT"
    validate_error(
        api.terminate_case(ctx["case_id"], fx.JUDGE), ApiErrorId.ERR_PENDING_EXPENDITURES
    )


def test_terminate_blocked_by_outstanding_accounting(api):
    """PRD 3.9: "if any AccountingReport exists, the one with the greatest
    period_year must be APPROVED (else ERR_ACCOUNTING_OUTSTANDING)."

    Design: Corner/errors/error_accounting_outstanding_blocks_terminate
    """
    ctx = fx.active_case(case_type="CONSERVATORSHIP", person_overrides={"liquid_estate_cents": 8_000_000})
    fid = ctx["fiduciary_id"]
    fx.create_and_submit_accounting(
        ctx["case_id"], fid,
        period_year=2026, opening_balance_cents=0,
        reported_income_cents=0, reported_disbursed_cents=0,
    )
    validate_error(
        api.terminate_case(ctx["case_id"], fx.JUDGE), ApiErrorId.ERR_ACCOUNTING_OUTSTANDING
    )


# ===========================================================================
# Restoration cascade (capacity_status -> RESTORED)
# ===========================================================================
def test_restore_resets_capacity_status(api):
    """PRD 3.9: "Restoration moves the case to RESTORED and runs the same
    revoke-and-close cascade as termination ... but differs in one respect: the
    protected person's capacity_status is set to RESTORED rather than left
    unchanged."

    Design: Corner/cross_cutting_complexity_layers/cascade_restore_resets_capacity_status
    """
    ctx = fx.active_case(case_type="GUARDIANSHIP", fiduciary_kind="FAMILY")
    fid = ctx["fiduciary_id"]
    cp = fx.create_active_care_plan(
        ctx["case_id"], fid,
        window_start_iso="2026-01-01T00:00:00Z", window_end_iso="2027-01-01T00:00:00Z",
    )
    api.open_review(ctx["case_id"], fx.JUDGE)
    rev = fx.schedule_review(
        ctx["case_id"], "CARE_PLAN", cp["id"],
        review_window_start_iso="2026-01-01T00:00:00Z",
        review_window_end_iso="2026-12-01T00:00:00Z",
    )
    api.hold_review(rev["id"], fx.JUDGE)
    api.dispose_review(rev["id"], F.dispose_review_payload("ACCEPTED"), fx.JUDGE)
    restored = validate_success(api.restore_case(ctx["case_id"], fx.JUDGE))
    assert restored["status"] == "RESTORED"
    appt = get_success_data(api.get_appointment(ctx["appointment_id"], fx.JUDGE))
    assert appt["status"] == "REVOKED"
    person = get_success_data(api.get_protected_person(ctx["person_id"], fx.JUDGE))
    assert person["capacity_status"] == "RESTORED"
    assert person["active_case_id"] is None
