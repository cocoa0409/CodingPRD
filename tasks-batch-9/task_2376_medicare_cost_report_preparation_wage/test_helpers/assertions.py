"""Shape and invariant assertions for this domain.

Each ``assert_<entity>`` checks that a response body carries every field the
entity declares, with the right primitive kind, including the four fields every
entity in this system carries: an identifier, a creation stamp, an update stamp
and a version counter.  The invariant helpers below cover the money and FTE
conservation rules the narrative states.
"""

from datetime import datetime

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# ---------------------------------------------------------------------------
# Generic building blocks
# ---------------------------------------------------------------------------


def assert_common_fields(entity, name="entity"):
    """Every entity carries id, created_at, updated_at and version."""
    assert is_valid_uuid(entity["id"]), f"{name}.id is not a UUID: {entity['id']}"
    assert is_iso8601_timestamp(
        entity["created_at"]
    ), f"{name}.created_at is not ISO-8601: {entity['created_at']}"
    assert is_iso8601_timestamp(
        entity["updated_at"]
    ), f"{name}.updated_at is not ISO-8601: {entity['updated_at']}"
    assert isinstance(entity["version"], int), f"{name}.version is not an integer"
    assert entity["version"] >= 1, f"{name}.version must start at 1"


def assert_fields_present(entity, fields, name="entity"):
    missing = [field for field in fields if field not in entity]
    assert not missing, f"{name} is missing declared fields: {missing}"


def assert_int_fields(entity, fields, name="entity"):
    for field in fields:
        assert isinstance(
            entity[field], int
        ), f"{name}.{field} must be an integer, got {type(entity[field]).__name__}"


def assert_number_fields(entity, fields, name="entity"):
    for field in fields:
        assert isinstance(
            entity[field], (int, float)
        ), f"{name}.{field} must be numeric, got {type(entity[field]).__name__}"


def assert_enum_value(value, allowed, name="field"):
    allowed_values = [str(getattr(item, "value", item)) for item in allowed]
    assert value in allowed_values, f"{name} is {value!r}, expected one of {allowed_values}"


# ---------------------------------------------------------------------------
# Entity shapes
# ---------------------------------------------------------------------------

PROVIDER_FIELDS = [
    "id",
    "ccn",
    "name",
    "cbsa_code",
    "teaching_status",
    "fte_cap",
    "current_interim_rate_cents",
    "approved_interim_period_count",
    "created_at",
    "updated_at",
    "version",
]

COST_REPORT_FIELDS = [
    "id",
    "provider_id",
    "fiscal_year_begin",
    "fiscal_year_end",
    "filing_deadline",
    "status",
    "wage_data_status",
    "allocation_status",
    "apportionment_method",
    "medicare_utilization_ratio",
    "interim_payments_received_cents",
    "total_charges_cents",
    "medicare_discharges",
    "total_direct_cost_cents",
    "unmapped_tb_total_cents",
    "total_allowable_cost_cents",
    "cost_to_charge_ratio",
    "unweighted_fte_days_total",
    "unweighted_fte_total",
    "capped_unweighted_fte",
    "weighted_fte_total",
    "rolling_average_fte",
    "allowable_cost_per_discharge_cents",
    "filed_at",
    "amendment_count",
    "created_at",
    "updated_at",
    "version",
]

COST_CENTER_FIELDS = [
    "id",
    "cost_report_id",
    "code",
    "name",
    "center_type",
    "allocation_basis",
    "stepdown_order",
    "statistics",
    "direct_cost_cents",
    "reclassified_amount_cents",
    "adjustment_amount_cents",
    "post_reclass_direct_cost_cents",
    "post_adjustment_cost_cents",
    "allocated_in_cents",
    "allocated_out_cents",
    "allocated_total_cost_cents",
    "created_at",
    "updated_at",
    "version",
]

TRIAL_BALANCE_LINE_FIELDS = [
    "id",
    "cost_report_id",
    "gl_account",
    "description",
    "amount_cents",
    "mapped_cost_center_id",
    "status",
    "created_at",
    "updated_at",
    "version",
]

WORKPAPER_ENTRY_FIELDS = [
    "id",
    "cost_report_id",
    "entry_type",
    "code",
    "description",
    "legs",
    "source",
    "is_non_allowable",
    "status",
    "source_audit_adjustment_id",
    "reversed_at",
    "created_at",
    "updated_at",
    "version",
]

STEPDOWN_RUN_FIELDS = [
    "id",
    "cost_report_id",
    "method",
    "status",
    "total_allocated_cents",
    "residual_unallocated_cents",
    "allocation_lines",
    "failure_reason",
    "stale_reason",
    "completed_at",
    "created_at",
    "updated_at",
    "version",
]

WAGE_INDEX_SUBMISSION_FIELDS = [
    "id",
    "cost_report_id",
    "status",
    "revision_number",
    "total_salaries_cents",
    "total_paid_hours",
    "wage_related_costs_cents",
    "contract_labor_cents",
    "contract_labor_hours",
    "excluded_area_salaries_cents",
    "excluded_area_hours",
    "allowed_wage_related_costs_cents",
    "unadjusted_ahw_cents",
    "occ_mix_adjusted_ahw_cents",
    "occ_mix_category_count",
    "effective_ahw_cents",
    "reported_hours_total",
    "review_note",
    "created_at",
    "updated_at",
    "version",
]

OCC_MIX_RESPONSE_FIELDS = [
    "id",
    "wage_index_submission_id",
    "category",
    "reported_hours",
    "reported_salaries_cents",
    "category_ahw_cents",
    "created_at",
    "updated_at",
    "version",
]

RESIDENT_FIELDS = [
    "id",
    "provider_id",
    "full_name",
    "program",
    "irp_status",
    "assigned_fte_days",
    "created_at",
    "updated_at",
    "version",
]

ROTATION_ASSIGNMENT_FIELDS = [
    "id",
    "resident_id",
    "cost_center_id",
    "start_date",
    "end_date",
    "fte_fraction",
    "status",
    "overlap_days",
    "fte_days",
    "created_at",
    "updated_at",
    "version",
]

UCC_DATA_SET_FIELDS = [
    "id",
    "cost_report_id",
    "medicaid_non_medicare_days",
    "total_inpatient_days",
    "ssi_days",
    "medicare_part_a_days",
    "charity_care_charges_cents",
    "non_medicare_bad_debt_cents",
    "medicaid_fraction",
    "ssi_fraction",
    "dsh_patient_percentage",
    "dsh_eligible",
    "cost_to_charge_ratio",
    "uncompensated_care_cost_cents",
    "ucc_payment_cents",
    "recompute_required",
    "created_at",
    "updated_at",
    "version",
]

SETTLEMENT_FIELDS = [
    "id",
    "cost_report_id",
    "stage",
    "status",
    "basis_method",
    "basis_allowable_cost_cents",
    "reimbursable_cost_cents",
    "ucc_payment_cents",
    "prior_tentative_paid_cents",
    "amount_due_provider_cents",
    "recompute_required",
    "issued_at",
    "created_at",
    "updated_at",
    "version",
]

AUDIT_ADJUSTMENT_FIELDS = [
    "id",
    "settlement_id",
    "target_cost_center_id",
    "code",
    "rationale",
    "proposed_amount_cents",
    "status",
    "proposed_by_user_id",
    "resolved_by_user_id",
    "provider_response_note",
    "created_at",
    "updated_at",
    "version",
]

APPEAL_CASE_FIELDS = [
    "id",
    "cost_report_id",
    "settlement_id",
    "kind",
    "issue_description",
    "amount_at_issue_cents",
    "status",
    "decided_at",
    "decision_note",
    "created_at",
    "updated_at",
    "version",
]

INTERIM_RATE_REQUEST_FIELDS = [
    "id",
    "provider_id",
    "basis_cost_report_id",
    "projected_discharges",
    "trend_factor",
    "effective_from",
    "effective_to",
    "status",
    "projected_cost_per_discharge_cents",
    "variance_ratio",
    "approved_rate_cents",
    "adjustment_amount_cents",
    "decision_note",
    "created_at",
    "updated_at",
    "version",
]

GME_SUMMARY_FIELDS = [
    "cost_report_id",
    "period_days",
    "unweighted_fte_days_total",
    "unweighted_fte_total",
    "capped_unweighted_fte",
    "weighted_fte_total",
    "rolling_average_fte",
    "prior_period_count",
]


def assert_provider(provider):
    assert_fields_present(provider, PROVIDER_FIELDS, "Provider")
    assert_common_fields(provider, "Provider")
    assert_int_fields(
        provider,
        ["current_interim_rate_cents", "approved_interim_period_count"],
        "Provider",
    )
    assert_number_fields(provider, ["fte_cap"], "Provider")
    assert_enum_value(
        provider["teaching_status"],
        ["TEACHING", "NON_TEACHING"],
        "Provider.teaching_status",
    )


def assert_cost_report(report):
    assert_fields_present(report, COST_REPORT_FIELDS, "CostReport")
    assert_common_fields(report, "CostReport")
    assert is_valid_uuid(report["provider_id"])
    assert_int_fields(
        report,
        [
            "interim_payments_received_cents",
            "total_charges_cents",
            "medicare_discharges",
            "total_direct_cost_cents",
            "unmapped_tb_total_cents",
            "total_allowable_cost_cents",
            "allowable_cost_per_discharge_cents",
            "amendment_count",
        ],
        "CostReport",
    )
    assert_number_fields(
        report,
        [
            "medicare_utilization_ratio",
            "cost_to_charge_ratio",
            "unweighted_fte_days_total",
            "unweighted_fte_total",
            "capped_unweighted_fte",
            "weighted_fte_total",
            "rolling_average_fte",
        ],
        "CostReport",
    )
    assert_enum_value(
        report["status"],
        [
            "DRAFT",
            "FILED",
            "TENTATIVE_SETTLED",
            "FINAL_SETTLED",
            "REOPENED",
            "AMENDED_FILED",
            "CLOSED",
        ],
        "CostReport.status",
    )
    assert_enum_value(
        report["wage_data_status"],
        [
            "NOT_STARTED",
            "COLLECTED",
            "UNDER_REVIEW",
            "VERIFIED",
            "REVISION_REQUESTED",
            "REJECTED",
        ],
        "CostReport.wage_data_status",
    )
    assert_enum_value(
        report["allocation_status"],
        ["NOT_RUN", "CURRENT", "STALE"],
        "CostReport.allocation_status",
    )


def assert_cost_center(center):
    assert_fields_present(center, COST_CENTER_FIELDS, "CostCenter")
    assert_common_fields(center, "CostCenter")
    assert is_valid_uuid(center["cost_report_id"])
    assert isinstance(center["statistics"], dict), "CostCenter.statistics must be an object"
    assert_int_fields(
        center,
        [
            "direct_cost_cents",
            "reclassified_amount_cents",
            "adjustment_amount_cents",
            "post_reclass_direct_cost_cents",
            "post_adjustment_cost_cents",
            "allocated_in_cents",
            "allocated_out_cents",
            "allocated_total_cost_cents",
        ],
        "CostCenter",
    )
    assert_enum_value(
        center["center_type"],
        ["GENERAL_SERVICE", "ANCILLARY", "ROUTINE", "NONREIMBURSABLE"],
        "CostCenter.center_type",
    )
    assert_enum_value(
        center["allocation_basis"],
        ["SQUARE_FEET", "MEALS_SERVED", "POUNDS_LAUNDRY", "NURSING_HOURS", "NONE"],
        "CostCenter.allocation_basis",
    )


def assert_trial_balance_line(line):
    assert_fields_present(line, TRIAL_BALANCE_LINE_FIELDS, "TrialBalanceLine")
    assert_common_fields(line, "TrialBalanceLine")
    assert_int_fields(line, ["amount_cents"], "TrialBalanceLine")
    assert_enum_value(
        line["status"], ["UNMAPPED", "MAPPED"], "TrialBalanceLine.status"
    )


def assert_workpaper_entry(entry):
    assert_fields_present(entry, WORKPAPER_ENTRY_FIELDS, "WorkpaperEntry")
    assert_common_fields(entry, "WorkpaperEntry")
    assert isinstance(entry["legs"], list), "WorkpaperEntry.legs must be an array"
    for leg in entry["legs"]:
        assert is_valid_uuid(leg["cost_center_id"])
        assert isinstance(leg["amount_cents"], int)
    assert isinstance(entry["is_non_allowable"], bool)
    assert_enum_value(
        entry["entry_type"],
        ["RECLASSIFICATION", "ADJUSTMENT"],
        "WorkpaperEntry.entry_type",
    )
    assert_enum_value(entry["source"], ["MANUAL", "AUDIT"], "WorkpaperEntry.source")
    assert_enum_value(
        entry["status"], ["ACTIVE", "REVERSED"], "WorkpaperEntry.status"
    )


def assert_stepdown_run(run):
    assert_fields_present(run, STEPDOWN_RUN_FIELDS, "StepdownRun")
    assert_common_fields(run, "StepdownRun")
    assert_int_fields(
        run, ["total_allocated_cents", "residual_unallocated_cents"], "StepdownRun"
    )
    assert isinstance(
        run["allocation_lines"], list
    ), "StepdownRun.allocation_lines must be an array"
    assert_enum_value(
        run["method"],
        ["SINGLE_APPORTIONMENT", "DOUBLE_APPORTIONMENT"],
        "StepdownRun.method",
    )
    assert_enum_value(
        run["status"], ["QUEUED", "COMPLETED", "FAILED", "STALE"], "StepdownRun.status"
    )


def assert_wage_index_submission(submission):
    assert_fields_present(
        submission, WAGE_INDEX_SUBMISSION_FIELDS, "WageIndexSubmission"
    )
    assert_common_fields(submission, "WageIndexSubmission")
    assert_int_fields(
        submission,
        [
            "revision_number",
            "total_salaries_cents",
            "wage_related_costs_cents",
            "contract_labor_cents",
            "excluded_area_salaries_cents",
            "allowed_wage_related_costs_cents",
            "unadjusted_ahw_cents",
            "occ_mix_category_count",
            "effective_ahw_cents",
        ],
        "WageIndexSubmission",
    )
    assert_number_fields(
        submission,
        [
            "total_paid_hours",
            "contract_labor_hours",
            "excluded_area_hours",
            "reported_hours_total",
        ],
        "WageIndexSubmission",
    )
    assert_enum_value(
        submission["status"],
        ["DRAFT", "SUBMITTED", "UNDER_REVIEW", "CHANGE_REQUESTED", "ACCEPTED", "REJECTED"],
        "WageIndexSubmission.status",
    )


def assert_occ_mix_response(response):
    assert_fields_present(response, OCC_MIX_RESPONSE_FIELDS, "OccMixResponse")
    assert_common_fields(response, "OccMixResponse")
    assert_int_fields(response, ["reported_salaries_cents"], "OccMixResponse")
    assert_number_fields(response, ["reported_hours"], "OccMixResponse")
    assert_enum_value(
        response["category"],
        ["RN", "LPN", "NURSE_AIDE", "MEDICAL_ASSISTANT", "NURSE_PRACTITIONER"],
        "OccMixResponse.category",
    )


def assert_resident(resident):
    assert_fields_present(resident, RESIDENT_FIELDS, "Resident")
    assert_common_fields(resident, "Resident")
    assert_number_fields(resident, ["assigned_fte_days"], "Resident")
    assert_enum_value(
        resident["irp_status"], ["WITHIN_IRP", "BEYOND_IRP"], "Resident.irp_status"
    )


def assert_rotation_assignment(assignment):
    assert_fields_present(assignment, ROTATION_ASSIGNMENT_FIELDS, "RotationAssignment")
    assert_common_fields(assignment, "RotationAssignment")
    assert_int_fields(assignment, ["overlap_days"], "RotationAssignment")
    assert_number_fields(assignment, ["fte_fraction", "fte_days"], "RotationAssignment")
    assert_enum_value(
        assignment["status"], ["ACTIVE", "VOID"], "RotationAssignment.status"
    )


def assert_ucc_data_set(data_set):
    assert_fields_present(data_set, UCC_DATA_SET_FIELDS, "UccDataSet")
    assert_common_fields(data_set, "UccDataSet")
    assert_int_fields(
        data_set,
        [
            "medicaid_non_medicare_days",
            "total_inpatient_days",
            "ssi_days",
            "medicare_part_a_days",
            "charity_care_charges_cents",
            "non_medicare_bad_debt_cents",
            "uncompensated_care_cost_cents",
            "ucc_payment_cents",
        ],
        "UccDataSet",
    )
    assert_number_fields(
        data_set,
        ["medicaid_fraction", "ssi_fraction", "dsh_patient_percentage", "cost_to_charge_ratio"],
        "UccDataSet",
    )
    assert isinstance(data_set["dsh_eligible"], bool)
    assert isinstance(data_set["recompute_required"], bool)


def assert_settlement(settlement):
    assert_fields_present(settlement, SETTLEMENT_FIELDS, "Settlement")
    assert_common_fields(settlement, "Settlement")
    assert_int_fields(
        settlement,
        [
            "basis_allowable_cost_cents",
            "reimbursable_cost_cents",
            "ucc_payment_cents",
            "prior_tentative_paid_cents",
            "amount_due_provider_cents",
        ],
        "Settlement",
    )
    assert isinstance(settlement["recompute_required"], bool)
    assert is_iso8601_timestamp(settlement["issued_at"])
    assert_enum_value(settlement["stage"], ["TENTATIVE", "FINAL"], "Settlement.stage")
    assert_enum_value(
        settlement["status"],
        ["ISSUED", "APPEALED", "SUPERSEDED", "RESETTLED"],
        "Settlement.status",
    )


def assert_audit_adjustment(adjustment):
    assert_fields_present(adjustment, AUDIT_ADJUSTMENT_FIELDS, "AuditAdjustment")
    assert_common_fields(adjustment, "AuditAdjustment")
    assert_int_fields(adjustment, ["proposed_amount_cents"], "AuditAdjustment")
    assert_enum_value(
        adjustment["status"],
        ["PROPOSED", "ACCEPTED_BY_PROVIDER", "PROTESTED", "INCORPORATED", "WITHDRAWN"],
        "AuditAdjustment.status",
    )


def assert_appeal_case(case):
    assert_fields_present(case, APPEAL_CASE_FIELDS, "AppealCase")
    assert_common_fields(case, "AppealCase")
    assert_int_fields(case, ["amount_at_issue_cents"], "AppealCase")
    assert_enum_value(case["kind"], ["REOPENING", "PRRB_APPEAL"], "AppealCase.kind")
    assert_enum_value(
        case["status"],
        [
            "REQUESTED",
            "GRANTED",
            "DENIED",
            "HEARD",
            "DECIDED_FOR_PROVIDER",
            "DECIDED_FOR_CONTRACTOR",
        ],
        "AppealCase.status",
    )


def assert_interim_rate_request(request):
    assert_fields_present(request, INTERIM_RATE_REQUEST_FIELDS, "InterimRateRequest")
    assert_common_fields(request, "InterimRateRequest")
    assert_int_fields(
        request,
        [
            "projected_discharges",
            "projected_cost_per_discharge_cents",
            "approved_rate_cents",
            "adjustment_amount_cents",
        ],
        "InterimRateRequest",
    )
    assert_number_fields(request, ["trend_factor", "variance_ratio"], "InterimRateRequest")
    assert_enum_value(
        request["status"],
        ["PENDING", "APPROVED", "DENIED", "SUPERSEDED"],
        "InterimRateRequest.status",
    )


def assert_gme_summary(summary):
    assert_fields_present(summary, GME_SUMMARY_FIELDS, "GmeSummary")
    assert_int_fields(summary, ["period_days", "prior_period_count"], "GmeSummary")
    assert_number_fields(
        summary,
        [
            "unweighted_fte_days_total",
            "unweighted_fte_total",
            "capped_unweighted_fte",
            "weighted_fte_total",
            "rolling_average_fte",
        ],
        "GmeSummary",
    )


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------


def assert_allocation_lines_sum(run, expected_total_cents):
    """The allocation lines must add up to the reported allocated total."""
    line_total = sum(line["amount_cents"] for line in run["allocation_lines"])
    assert line_total == expected_total_cents, (
        f"allocation lines total {line_total} but expected {expected_total_cents}"
    )
    assert run["total_allocated_cents"] == expected_total_cents, (
        f"total_allocated_cents is {run['total_allocated_cents']}, "
        f"expected {expected_total_cents}"
    )


def assert_direct_cost_conserved(centers, expected_total_cents):
    """Reclassification moves cost between centers without creating any."""
    total = sum(center["post_reclass_direct_cost_cents"] for center in centers)
    assert total == expected_total_cents, (
        f"post-reclassification cost totals {total} but the mapped ledger "
        f"total is {expected_total_cents}"
    )


def assert_money_equals(actual_cents, expected_cents, label="amount"):
    assert isinstance(actual_cents, int), f"{label} must be an integer number of cents"
    assert actual_cents == expected_cents, (
        f"{label} is {actual_cents} cents, expected {expected_cents} cents"
    )


def assert_ratio_equals(actual, expected, label="ratio", places=6):
    assert round(float(actual), places) == round(float(expected), places), (
        f"{label} is {actual}, expected {expected}"
    )


def assert_fte_equals(actual, expected, label="fte", places=4):
    assert round(float(actual), places) == round(float(expected), places), (
        f"{label} is {actual}, expected {expected}"
    )


def assert_instant_equals(actual, expected, label="timestamp"):
    """Compare two ISO 8601 UTC strings as *instants*.

    PRD 2.5 pins the logical clock to an instant ("On a fresh database the clock
    reads `2026-08-01T00:00:00Z`") and PRD 2.4 pins timestamp fields to three
    fractional digits, so ``2026-08-01T00:00:00Z`` and
    ``2026-08-01T00:00:00.000Z`` denote the same PRD-required value.  Only the
    instant is asserted here; the rendering is not.
    """
    assert isinstance(actual, str), f"{label} must be an ISO 8601 string, got {actual!r}"
    parsed = datetime.fromisoformat(actual.replace("Z", "+00:00"))
    wanted = datetime.fromisoformat(str(expected).replace("Z", "+00:00"))
    assert parsed == wanted, f"{label} is {actual}, expected the instant {expected}"


def assert_unchanged(before, after, fields, name="entity"):
    for field in fields:
        assert before[field] == after[field], (
            f"{name}.{field} changed from {before[field]} to {after[field]}"
        )


def find_allocation_line(run, from_cost_center_id, to_cost_center_id, allocation_pass=None):
    """Return the single allocation line matching the given leg."""
    matches = [
        line
        for line in run["allocation_lines"]
        if line["from_cost_center_id"] == from_cost_center_id
        and line["to_cost_center_id"] == to_cost_center_id
        and (allocation_pass is None or line["pass"] == allocation_pass)
    ]
    assert len(matches) == 1, (
        f"expected exactly one allocation line from {from_cost_center_id} to "
        f"{to_cost_center_id} (pass={allocation_pass}), found {len(matches)}"
    )
    return matches[0]
