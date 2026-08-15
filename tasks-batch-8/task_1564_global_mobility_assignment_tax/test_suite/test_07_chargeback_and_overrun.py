"""Chargeback posting/voiding against the program aggregate, and the overrun
posture threshold with its strictly-greater boundary and gate-ordering rule
(PRD §3.6, §3.7, §3.9)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_certificate,
    create_and_post_record,
    create_current_projection,
    create_draft_record,
    create_pending_extension,
    get_assignment,
    list_chargebacks,
    setup_active_assignment,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
BU = TEST_USERS["bu_approver_headers"]
FINANCE = TEST_USERS["finance_headers"]


def test_chargeback_post_adds_to_program_posted_total(api, finance_headers, admin_headers):
    """PRD §3.9: "A `FinanceController` posts an accrued entry (`ACCRUED` → `POSTED`),
    which adds its `amount_cents` to the program's `total_posted_chargeback_cents`."

    Design: Difficulty/compensating_invariant/chargeback_post_void_conserves_program_posted_total
    """
    ctx = setup_active_assignment(totalization=True)
    asg_id = ctx["assignment"]["id"]
    create_and_post_record(asg_id, tax_year=2026, period_month=9,
                           total_gross_cents=900000, per_diem_days=20,
                           housing_receipts_cents=310000)
    entry = list_chargebacks(asg_id)[0]

    posted = validate_success(api.post_chargeback(entry["id"], finance_headers), 200)
    assert posted["status"] == "POSTED"

    program = validate_success(api.get_program(ctx["program"]["id"], admin_headers), 200)
    assert program["total_posted_chargeback_cents"] == 1072500


def test_chargeback_void_of_posted_entry_conserves_program_total(api, finance_headers, admin_headers):
    """PRD §3.9: "Voiding compensates symmetrically and is permitted from either
    non-terminal state: voiding an `ACCRUED` entry — manually, or as the cascade from
    voiding a posted shadow payroll record — decrements the assignment's
    `ytd_chargeback_cents` by the entry's amount and re-runs the overrun posture check;
    voiding a `POSTED` entry additionally decrements the program's
    `total_posted_chargeback_cents`, again with the assignment decrement and the
    posture re-run."

    Design: Difficulty/compensating_invariant/chargeback_post_void_conserves_program_posted_total
    """
    ctx = setup_active_assignment(totalization=True)
    asg_id = ctx["assignment"]["id"]
    create_and_post_record(asg_id, tax_year=2026, period_month=9,
                           total_gross_cents=900000, per_diem_days=20,
                           housing_receipts_cents=310000)
    entry = list_chargebacks(asg_id)[0]
    validate_success(api.post_chargeback(entry["id"], finance_headers), 200)

    voided = validate_success(api.void_chargeback(entry["id"], finance_headers), 200)
    assert voided["status"] == "VOIDED"

    program = validate_success(api.get_program(ctx["program"]["id"], admin_headers), 200)
    assert program["total_posted_chargeback_cents"] == 0, (
        "the post/void pair must conserve the program posted total exactly"
    )
    assert get_assignment(asg_id)["ytd_chargeback_cents"] == 0


def _setup_overrun_assignment(employee_ref, total_gross_cents, housing_receipts_cents):
    """Activated assignment (no totalization) with a CURRENT projection whose
    monthly cost is 1186290, then one POSTED September record. The pro-rata
    threshold for one posted month is 1186290 x 110 / 100 = 1304919."""
    ctx = setup_active_assignment(
        program_overrides={"cost_overrun_threshold_pct": 110},
        employee_overrides={"employee_ref": employee_ref},
        policy_overrides={"effective_from": "2026-01-01", "effective_to": "2027-12-31"},
    )
    asg_id = ctx["assignment"]["id"]
    projection = create_current_projection(asg_id)
    assert projection["monthly_cost_cents"] == 1186290
    create_and_post_record(
        asg_id, tax_year=2026, period_month=9, total_gross_cents=total_gross_cents,
        per_diem_days=20, housing_receipts_cents=housing_receipts_cents)
    return ctx


def test_overrun_exact_threshold_equality_stays_normal(api, bu_approver_headers):
    """PRD §3.6: "Otherwise the pro-rata threshold is the projection's
    `monthly_cost_cents` multiplied by the posted-month count and by the program's
    `cost_overrun_threshold_pct`, divided by one hundred, compared as an exact rational
    with no rounding before the comparison."
    PRD §3.6: "When `ytd_chargeback_cents` strictly exceeds that threshold,
    `cost_posture` flips to `OVERRUN`; when it equals the threshold exactly, the
    posture is `NORMAL`."
    PRD §3.7: "An approved extension moves the request to `APPROVED`, records
    `decided_by_user_id`, sets the assignment's `planned_end_date` to the
    `requested_new_end_date`, refreshes the assignment's `updated_at`, and increments
    the assignment's `version` by one"

    Design: Difficulty/boundary_precision_check/overrun_threshold_exact_equality_stays_normal
    """
    # total 1193832 -> chargeback 477533 + 318355 + 36531 + 172500 + 300000
    # = 1304919, exactly the threshold: equality does not trip the posture.
    ctx = _setup_overrun_assignment("E1001", 1193832, 300000)
    asg_id = ctx["assignment"]["id"]
    assert get_assignment(asg_id)["cost_posture"] == "NORMAL"

    extension = create_pending_extension(asg_id, "2027-10-31")
    approved = validate_success(api.approve_extension(extension["id"], bu_approver_headers), 200)
    assert approved["status"] == "APPROVED"
    assert get_assignment(asg_id)["planned_end_date"] == "2027-10-31"


def test_overrun_one_cent_over_threshold_blocks_extension(api, bu_approver_headers):
    """PRD §3.6: "When `ytd_chargeback_cents` strictly exceeds that threshold,
    `cost_posture` flips to `OVERRUN`; when it equals the threshold exactly, the
    posture is `NORMAL`."
    PRD §3.7: "Approval requires the same two state conditions and then evaluates two
    further gates in a fixed order: first the coverage gate — when
    `totalization_applies` is true, an `ISSUED` certificate whose `valid_until` falls
    on or after the `requested_new_end_date` must exist, otherwise the approval is
    rejected with `ERR_COC_COVERAGE_GAP`; then the posture gate — while the
    assignment's `cost_posture` is `OVERRUN`, approval is rejected with
    `ERR_COST_OVERRUN_BLOCKED`."

    Design: Difficulty/boundary_precision_check/overrun_threshold_exact_equality_stays_normal
    """
    # total 1193834 with receipts 299999 -> chargeback 1304920: one cent over.
    ctx = _setup_overrun_assignment("E1001", 1193834, 299999)
    asg_id = ctx["assignment"]["id"]
    assert get_assignment(asg_id)["cost_posture"] == "OVERRUN"

    extension = create_pending_extension(asg_id, "2027-10-31")
    res = api.approve_extension(extension["id"], bu_approver_headers)
    validate_error(res, ApiErrorId.ERR_COST_OVERRUN_BLOCKED)


def test_coverage_gap_beats_posture_gate_on_extension_approve(api, bu_approver_headers):
    """PRD §3.7: "Approval requires the same two state conditions and then evaluates
    two further gates in a fixed order: first the coverage gate — when
    `totalization_applies` is true, an `ISSUED` certificate whose `valid_until` falls
    on or after the `requested_new_end_date` must exist, otherwise the approval is
    rejected with `ERR_COC_COVERAGE_GAP`; then the posture gate — while the
    assignment's `cost_posture` is `OVERRUN`, approval is rejected with
    `ERR_COST_OVERRUN_BLOCKED`."

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_fiscal_on_extension_approve
    """
    # Totalization-covered assignment; certificate coverage ends 2027-08-31.
    # The posted record (21 per-diem days) pushes the chargeback to 1283250,
    # strictly over the 1158750 x 110 / 100 = 1274625 threshold, so the posture is
    # OVERRUN at the same time as the coverage gate fails for a 2027-11-30 request.
    ctx = setup_active_assignment(
        totalization=True,
        program_overrides={"cost_overrun_threshold_pct": 110},
    )
    asg_id = ctx["assignment"]["id"]
    projection = create_current_projection(asg_id)
    assert projection["monthly_cost_cents"] == 1158750
    create_and_post_record(
        asg_id, tax_year=2026, period_month=9, total_gross_cents=1203188,
        per_diem_days=21, housing_receipts_cents=300000)
    assert get_assignment(asg_id)["cost_posture"] == "OVERRUN"

    extension = create_pending_extension(asg_id, "2027-11-30")
    res = api.approve_extension(extension["id"], bu_approver_headers)
    validate_error(res, ApiErrorId.ERR_COC_COVERAGE_GAP)


def test_posture_gate_isolated_when_coverage_sufficient(api, bu_approver_headers):
    """PRD §3.7: "Approval requires the same two state conditions and then evaluates
    two further gates in a fixed order: first the coverage gate — when
    `totalization_applies` is true, an `ISSUED` certificate whose `valid_until` falls
    on or after the `requested_new_end_date` must exist, otherwise the approval is
    rejected with `ERR_COC_COVERAGE_GAP`; then the posture gate — while the
    assignment's `cost_posture` is `OVERRUN`, approval is rejected with
    `ERR_COST_OVERRUN_BLOCKED`."

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_fiscal_on_extension_approve
    """
    # Certificate coverage reaches past the requested end date, so only the
    # posture gate can fail.
    ctx = setup_active_assignment(
        totalization=True,
        coc_valid_until="2028-12-31",
        program_overrides={"cost_overrun_threshold_pct": 110},
    )
    asg_id = ctx["assignment"]["id"]
    create_current_projection(asg_id)
    create_and_post_record(
        asg_id, tax_year=2026, period_month=9, total_gross_cents=1203188,
        per_diem_days=21, housing_receipts_cents=300000)
    assert get_assignment(asg_id)["cost_posture"] == "OVERRUN"

    extension = create_pending_extension(asg_id, "2027-10-31")
    res = api.approve_extension(extension["id"], bu_approver_headers)
    validate_error(res, ApiErrorId.ERR_COST_OVERRUN_BLOCKED)
