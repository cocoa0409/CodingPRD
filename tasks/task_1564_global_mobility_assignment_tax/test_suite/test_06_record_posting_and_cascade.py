"""Shadow payroll posting: idempotent-state protection, period uniqueness, the
post cascade into the chargeback ledger and assignment aggregates, the
compensating void, and the cumulative per-diem annual cap (PRD §3.3, §3.6)."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_and_post_record,
    create_current_projection,
    create_draft_record,
    create_pending_extension,
    create_record_payload,
    get_assignment,
    list_chargebacks,
    setup_active_assignment,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_double_post_record_returns_invalid_state(api, payroll_headers, admin_headers):
    """PRD §2.10: "The target must be in a from-state of the invoked transition, and
    terminal states accept no further transitions; state-gated creations require their
    parent state — a shadow payroll record requires an `ACTIVE` assignment, a
    settlement requires an assignment that is `ACTIVE`, `REPATRIATION_PENDING`, or
    `REPATRIATED`, and an extension request requires an `ACTIVE` assignment — else
    `ERR_INVALID_STATE` (409)."
    PRD §3.3: "Posting, performed by a `PayrollSpecialist`, moves the record `DRAFT` →
    `POSTED` and is where the ledger comes alive."

    Design: Corner/state_machines/double_post_record_returns_invalid_state
    """
    ctx = setup_active_assignment()
    record = create_and_post_record(ctx["assignment"]["id"], tax_year=2026, period_month=9)
    assert record["status"] == "POSTED"

    res = api.post_record(record["id"], payroll_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    assignment = get_assignment(ctx["assignment"]["id"])
    assert assignment["ytd_gross_cents"] == 900000, "gross must be counted exactly once"


def test_duplicate_payroll_period_rejected_in_draft_and_posted(api, payroll_headers):
    """PRD §3.3: "at most one record per assignment, tax year, and period month may
    exist in `DRAFT` or `POSTED` status — a `VOIDED` record frees the slot — else
    `ERR_DUPLICATE_PAYROLL_PERIOD`"

    Design: Corner/validations/duplicate_payroll_period_rejected_in_draft_and_posted
    """
    ctx = setup_active_assignment()
    asg_id = ctx["assignment"]["id"]
    first = create_draft_record(
        asg_id, tax_year=2026, period_month=9, total_gross_cents=900000,
        per_diem_days=0, housing_receipts_cents=0)

    res = api.create_record(
        create_record_payload(asg_id, tax_year=2026, period_month=9,
                              total_gross_cents=800000, per_diem_days=0,
                              housing_receipts_cents=0),
        payroll_headers)
    validate_error(res, ApiErrorId.ERR_DUPLICATE_PAYROLL_PERIOD)

    validate_success(api.post_record(first["id"], payroll_headers), 200)
    res = api.create_record(
        create_record_payload(asg_id, tax_year=2026, period_month=9,
                              total_gross_cents=800000, per_diem_days=0,
                              housing_receipts_cents=0),
        payroll_headers)
    validate_error(res, ApiErrorId.ERR_DUPLICATE_PAYROLL_PERIOD)


def test_record_post_creates_period_cost_chargeback(api, payroll_headers, admin_headers):
    """PRD §3.3: "The first cascade hop creates a chargeback entry of `entry_type`
    `PERIOD_COST` in `ACCRUED` status, whose `amount_cents` is the sum of the record's
    five frozen fields — `host_gross_cents`, `employer_host_tax_cents`,
    `employer_socsec_cents`, `per_diem_cents`, and `housing_cents` — with
    `business_unit` copied from the assignment's `host_business_unit` and
    `source_record_id` pointing back at the record."

    Design: Difficulty/transitive_cascade/record_post_cascade_to_overrun_gate
    """
    # No totalization: the social-security field contributes 36818.
    # round half up on the home share pins host to 481275, so the entry amount is
    # 481275 + 320850 + 36818 + 172500 + 300000 = 1311443.
    ctx = setup_active_assignment(program_overrides={"cost_overrun_threshold_pct": 110})
    asg_id = ctx["assignment"]["id"]
    create_current_projection(asg_id)

    record = create_and_post_record(
        asg_id, tax_year=2026, period_month=9, total_gross_cents=1203188,
        per_diem_days=20, housing_receipts_cents=300000)

    entries = list_chargebacks(asg_id)
    assert len(entries) == 1
    entry = entries[0]
    assert entry["entry_type"] == "PERIOD_COST"
    assert entry["status"] == "ACCRUED"
    assert entry["amount_cents"] == 1311443
    assert entry["business_unit"] == "BU-TOKYO"
    assert entry["source_record_id"] == record["id"]


def test_record_post_updates_aggregates_and_flips_overrun(api, payroll_headers, admin_headers):
    """PRD §3.3: "The second hop adds the entry amount to the assignment's
    `ytd_chargeback_cents`, adds `total_gross_cents` to `ytd_gross_cents`,
    `hypothetical_tax_cents` to `ytd_hypo_withheld_cents`, and `per_diem_days` to
    `ytd_per_diem_days`, refreshing the assignment's `updated_at`."
    PRD §3.6: "When `ytd_chargeback_cents` strictly exceeds that threshold,
    `cost_posture` flips to `OVERRUN`; when it equals the threshold exactly, the
    posture is `NORMAL`."

    Design: Difficulty/transitive_cascade/record_post_cascade_to_overrun_gate
    """
    ctx = setup_active_assignment(program_overrides={"cost_overrun_threshold_pct": 110})
    asg_id = ctx["assignment"]["id"]
    projection = create_current_projection(asg_id)
    assert projection["monthly_cost_cents"] == 1186290

    create_and_post_record(
        asg_id, tax_year=2026, period_month=9, total_gross_cents=1203188,
        per_diem_days=20, housing_receipts_cents=300000)

    assignment = get_assignment(asg_id)
    assert assignment["ytd_chargeback_cents"] == 1311443
    # Threshold: 1186290 x 1 posted month x 110 / 100 = 1304919; 1311443 exceeds it.
    assert assignment["cost_posture"] == "OVERRUN"


def test_post_then_void_compensates_assignment_aggregates(api, payroll_headers, admin_headers):
    """PRD §3.3: "Voiding a posted record compensates: its `PERIOD_COST` chargeback
    entry transitions to `VOIDED` with the entry-void compensation rules of §3.9, the
    assignment's `ytd_gross_cents`, `ytd_hypo_withheld_cents`, `ytd_per_diem_days`, and
    `ytd_chargeback_cents` are each decremented by the record's frozen amounts, and the
    overrun posture check re-runs, so the posture may flip back from `OVERRUN` to
    `NORMAL`."

    Design: Difficulty/compensating_invariant/record_post_void_repost_conserves_assignment_ytd_gross
    """
    ctx = setup_active_assignment(totalization=True)
    asg_id = ctx["assignment"]["id"]
    record = create_and_post_record(
        asg_id, tax_year=2026, period_month=9, total_gross_cents=900000,
        per_diem_days=20, housing_receipts_cents=310000)

    after_post = get_assignment(asg_id)
    assert after_post["ytd_gross_cents"] == 900000
    assert after_post["ytd_chargeback_cents"] == 1072500

    voided = validate_success(api.void_record(record["id"], payroll_headers), 200)
    assert voided["status"] == "VOIDED"

    after_void = get_assignment(asg_id)
    assert after_void["ytd_gross_cents"] == 0
    assert after_void["ytd_chargeback_cents"] == 0
    assert after_void["ytd_hypo_withheld_cents"] == 0
    assert after_void["ytd_per_diem_days"] == 0

    entries = list_chargebacks(asg_id)
    assert len(entries) == 1
    assert entries[0]["status"] == "VOIDED", (
        "the compensating cascade must void the record's PERIOD_COST entry"
    )


def test_repost_after_void_restores_aggregates_exactly(api, payroll_headers, admin_headers):
    """PRD §3.3: "at most one record per assignment, tax year, and period month may
    exist in `DRAFT` or `POSTED` status — a `VOIDED` record frees the slot — else
    `ERR_DUPLICATE_PAYROLL_PERIOD`"
    PRD §2.9: "Program-level and assignment-level totals are maintained as signed
    running aggregates — voiding compensates them — so the ledger always reflects the
    live state of its source documents."

    Design: Difficulty/compensating_invariant/record_post_void_repost_conserves_assignment_ytd_gross
    """
    ctx = setup_active_assignment(totalization=True)
    asg_id = ctx["assignment"]["id"]
    first = create_and_post_record(
        asg_id, tax_year=2026, period_month=9, total_gross_cents=900000,
        per_diem_days=20, housing_receipts_cents=310000)
    validate_success(api.void_record(first["id"], payroll_headers), 200)

    # The VOIDED record left the uniqueness set, so the same period reposts.
    second = create_and_post_record(
        asg_id, tax_year=2026, period_month=9, total_gross_cents=900000,
        per_diem_days=20, housing_receipts_cents=310000)
    assert second["status"] == "POSTED"

    final = get_assignment(asg_id)
    assert final["ytd_gross_cents"] == 900000
    assert final["ytd_chargeback_cents"] == 1072500, (
        "forward + compensate + reapply must conserve the aggregates exactly"
    )

    entries = list_chargebacks(asg_id)
    by_source = {e["source_record_id"]: e for e in entries}
    assert by_source[first["id"]]["status"] == "VOIDED"
    assert by_source[second["id"]]["status"] == "ACCRUED"


def _setup_cap50_assignment():
    return setup_active_assignment(
        program_overrides={"per_diem_annual_day_cap": 50},
        assignment_overrides={"start_date": "2027-01-01", "planned_end_date": "2027-12-31"},
    )


def test_per_diem_cap_exact_boundary_accepted(api, payroll_headers, admin_headers):
    """PRD §3.3: "The split must be `ACTIVE` (`ERR_SPLIT_NOT_ACTIVE`), and the
    cumulative per-diem cap is enforced: the sum of `per_diem_days` over `POSTED`
    records of the assignment for the same `tax_year`, plus this record's days, must
    not strictly exceed the program's `per_diem_annual_day_cap` — exactly reaching the
    cap is accepted, one day beyond it is rejected with
    `ERR_PER_DIEM_ANNUAL_CAP_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/per_diem_annual_cap_exact_boundary
    """
    ctx = _setup_cap50_assignment()
    asg_id = ctx["assignment"]["id"]
    create_and_post_record(asg_id, tax_year=2027, period_month=1,
                           total_gross_cents=900000, per_diem_days=30,
                           housing_receipts_cents=0)
    # Cumulative 30 + 20 == cap 50 exactly: the inclusive boundary posts.
    february = create_and_post_record(asg_id, tax_year=2027, period_month=2,
                                      total_gross_cents=900000, per_diem_days=20,
                                      housing_receipts_cents=0)
    assert february["status"] == "POSTED"
    assert get_assignment(asg_id)["ytd_per_diem_days"] == 50


def test_per_diem_cap_exceeded_by_one_day_rejected(api, payroll_headers, admin_headers):
    """PRD §3.3: "The split must be `ACTIVE` (`ERR_SPLIT_NOT_ACTIVE`), and the
    cumulative per-diem cap is enforced: the sum of `per_diem_days` over `POSTED`
    records of the assignment for the same `tax_year`, plus this record's days, must
    not strictly exceed the program's `per_diem_annual_day_cap` — exactly reaching the
    cap is accepted, one day beyond it is rejected with
    `ERR_PER_DIEM_ANNUAL_CAP_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/per_diem_annual_cap_exact_boundary
    """
    ctx = _setup_cap50_assignment()
    asg_id = ctx["assignment"]["id"]
    create_and_post_record(asg_id, tax_year=2027, period_month=1,
                           total_gross_cents=900000, per_diem_days=30,
                           housing_receipts_cents=0)
    create_and_post_record(asg_id, tax_year=2027, period_month=2,
                           total_gross_cents=900000, per_diem_days=20,
                           housing_receipts_cents=0)
    march = create_draft_record(asg_id, tax_year=2027, period_month=3,
                                total_gross_cents=900000, per_diem_days=1,
                                housing_receipts_cents=0)

    res = api.post_record(march["id"], payroll_headers)
    validate_error(res, ApiErrorId.ERR_PER_DIEM_ANNUAL_CAP_EXCEEDED)

    fetched = validate_success(api.get_record(march["id"], payroll_headers), 200)
    assert fetched["status"] == "DRAFT", "the rejected record must stay DRAFT"
    assert get_assignment(asg_id)["ytd_per_diem_days"] == 50, (
        "the failed post must not move the cumulative day counter"
    )


def test_shadow_record_list_filters_by_assignment_and_status(api, admin_headers):
    """PRD §2.3: "Beyond pagination, each list endpoint accepts optional equality
    filters matching its resource's reference and status fields. Assignments filter by
    `program_id`, `employee_id`, `policy_id`, or `status`; allowance policies by
    `host_country_code`; compensation packages, payroll splits, and certificates of
    coverage by `assignment_id`; shadow payroll records by `assignment_id`, `tax_year`,
    or `status`; settlements by `assignment_id`, `tax_year`, `status`, or
    `vendor_engagement_id`; vendor engagements by `assignment_id`, `tax_year`, or
    `status`; cost projections and extension requests by `assignment_id` or `status`;
    chargeback entries by `assignment_id`, `entry_type`, `status`, `source_record_id`,
    or `source_settlement_id`."

    Design: Corner/endpoints/shadow_record_list_filters_by_assignment_and_status
    """
    first = setup_active_assignment(
        employee_overrides={"employee_ref": "E1001", "full_name": "A One"})
    a1 = first["assignment"]["id"]
    a1_posted = create_and_post_record(
        a1, tax_year=2026, period_month=9, total_gross_cents=900000,
        per_diem_days=0, housing_receipts_cents=0)
    a1_draft = create_draft_record(
        a1, tax_year=2026, period_month=10, total_gross_cents=900000,
        per_diem_days=0, housing_receipts_cents=0)

    second = setup_active_assignment(
        employee_overrides={"employee_ref": "E1002", "full_name": "B Two"},
        policy_overrides={"effective_from": "2028-01-01", "effective_to": "2029-12-31"},
        assignment_overrides={"host_business_unit": "BU-OSAKA"})
    a2 = second["assignment"]["id"]
    a2_posted = create_and_post_record(
        a2, tax_year=2026, period_month=9, total_gross_cents=700000,
        per_diem_days=0, housing_receipts_cents=0)

    rows, meta = validate_paginated(api.list_records(
        admin_headers, params={"assignment_id": a1, "status": "POSTED"}))
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [a1_posted["id"]], (
        "only the POSTED record of the filtered assignment may be returned"
    )
    assert a1_draft["id"] not in [row["id"] for row in rows]
    assert a2_posted["id"] not in [row["id"] for row in rows]
