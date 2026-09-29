"""Entity assertions and domain invariant checkers.

Every resource except the immutable guideline table carries `id`, `created_at`,
`updated_at` and `version`; `PovertyGuideline` carries only `id` and
`created_at` and neither `updated_at` nor `version` appears in its payload.
"""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# ---------------------------------------------------------------------------
# Common properties
# ---------------------------------------------------------------------------


def assert_common_fields(data: dict, entity_name: str = "resource") -> None:
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity_name}.created_at must be an ISO 8601 timestamp"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{entity_name}.updated_at must be an ISO 8601 timestamp"
    assert isinstance(
        data.get("version"), int
    ), f"{entity_name}.version must be an integer"
    assert data["version"] >= 1, f"{entity_name}.version starts at 1"


# ---------------------------------------------------------------------------
# HealthCenter
# ---------------------------------------------------------------------------


def assert_health_center(data: dict) -> None:
    assert_common_fields(data, "HealthCenter")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["grant_number"], str) and data["grant_number"]
    assert isinstance(data["pps_base_rate_cents"], int)
    assert data["pps_base_rate_cents"] > 0
    assert isinstance(data["medicare_upper_limit_cents"], int)
    assert data["medicare_upper_limit_cents"] > 0
    assert isinstance(data["nominal_fee_cap_cents"], int)
    assert data["nominal_fee_cap_cents"] > 0
    assert isinstance(data["scope_baseline_locked"], bool)
    assert data["operational_status"] in ("ACTIVE", "CONDITIONS_IMPOSED")
    assert data["scope_posture"] in ("OPEN", "CHANGE_FROZEN")
    assert data["governance_posture"] in (
        "GOVERNANCE_COMPLIANT",
        "GOVERNANCE_DEFICIENT",
    )
    for counter in (
        "open_condition_count",
        "in_scope_site_count",
        "in_scope_service_count",
        "seated_board_count",
        "wraparound_receivable_cents",
    ):
        assert isinstance(data[counter], int), f"HealthCenter.{counter} must be integer"
        assert data[counter] >= 0, f"HealthCenter.{counter} must not be negative"
    assert isinstance(data["patient_seat_pct"], (int, float))


def assert_award_posture_consistent(data: dict) -> None:
    """`operational_status` and `scope_posture` are derived from the counters."""
    expected_operational = (
        "CONDITIONS_IMPOSED" if data["open_condition_count"] > 0 else "ACTIVE"
    )
    assert data["operational_status"] == expected_operational, (
        f"operational_status must be {expected_operational} when "
        f"open_condition_count is {data['open_condition_count']}"
    )
    expected_posture = (
        "CHANGE_FROZEN" if data["operational_status"] == "CONDITIONS_IMPOSED" else "OPEN"
    )
    assert data["scope_posture"] == expected_posture, (
        f"scope_posture must be {expected_posture} when operational_status is "
        f"{data['operational_status']}"
    )


# ---------------------------------------------------------------------------
# PovertyGuideline
# ---------------------------------------------------------------------------


def assert_poverty_guideline(data: dict) -> None:
    assert is_valid_uuid(data.get("id", "")), "PovertyGuideline.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["guideline_year"], int)
    assert 2000 <= data["guideline_year"] <= 2100
    assert isinstance(data["base_amount_cents"], int) and data["base_amount_cents"] > 0
    assert isinstance(data["increment_cents"], int) and data["increment_cents"] > 0
    assert "updated_at" not in data, "PovertyGuideline carries no updated_at field"
    assert "version" not in data, "PovertyGuideline carries no version field"


# ---------------------------------------------------------------------------
# BoardMember
# ---------------------------------------------------------------------------


def assert_board_member(data: dict) -> None:
    assert_common_fields(data, "BoardMember")
    assert is_valid_uuid(data["health_center_id"])
    assert isinstance(data["seat_number"], int) and data["seat_number"] >= 1
    assert data["seat_type"] in ("PATIENT", "NON_PATIENT")
    assert data["status"] in ("SEATED", "RESIGNED")
    assert isinstance(data["derives_over_10pct_income_from_healthcare"], bool)
    if data["seat_type"] == "PATIENT":
        assert data["patient_id"] is not None, "a PATIENT seat names its patient_id"
        assert data["expertise_category"] is None
    else:
        assert data["expertise_category"] in (
            "FINANCE",
            "LEGAL",
            "COMMUNITY",
            "HEALTH_PROFESSION",
        )
        assert data["patient_id"] is None


# ---------------------------------------------------------------------------
# ServiceSite / ServiceDefinition
# ---------------------------------------------------------------------------


def assert_service_site(data: dict) -> None:
    assert_common_fields(data, "ServiceSite")
    assert is_valid_uuid(data["health_center_id"])
    assert isinstance(data["site_name"], str) and data["site_name"]
    assert data["site_type"] in ("SERVICE_DELIVERY", "INTERMITTENT", "ADMINISTRATIVE")
    assert isinstance(data["address_line"], str)
    assert isinstance(data["weekly_service_hours"], int)
    assert data["weekly_service_hours"] >= 0
    assert data["status"] in ("PROPOSED", "IN_SCOPE", "ON_HOLD", "SUSPENDED", "REMOVED")
    assert data["hold_reason"] in (None, "SCOPE_FROZEN")


def assert_service_definition(data: dict) -> None:
    assert_common_fields(data, "ServiceDefinition")
    assert is_valid_uuid(data["health_center_id"])
    assert isinstance(data["service_code"], str) and data["service_code"]
    assert data["service_category"] in ("REQUIRED_PRIMARY", "ADDITIONAL")
    assert data["delivery_method"] in (
        "COLUMN_I_DIRECT",
        "COLUMN_II_CONTRACT",
        "COLUMN_III_REFERRAL",
    )
    assert data["status"] in ("PENDING", "IN_SCOPE", "OUT_OF_SCOPE")


# ---------------------------------------------------------------------------
# ScopeChangeRequest
# ---------------------------------------------------------------------------


def assert_scope_change_request(data: dict) -> None:
    assert_common_fields(data, "ScopeChangeRequest")
    assert is_valid_uuid(data["health_center_id"])
    assert data["request_type"] in (
        "ADD_SITE",
        "REMOVE_SITE",
        "ADD_SERVICE",
        "REMOVE_SERVICE",
    )
    assert data["status"] in (
        "DRAFT",
        "SUBMITTED",
        "UNDER_REVIEW",
        "REVISION_REQUESTED",
        "HELD",
        "APPROVED",
        "DENIED",
    )
    assert isinstance(data["revision_round"], int) and data["revision_round"] >= 0
    assert data["held_from_status"] in (None, "SUBMITTED", "UNDER_REVIEW")
    assert isinstance(data["justification"], str)
    assert isinstance(data["prepared_by_user_id"], str) and data["prepared_by_user_id"]
    if data["request_type"] in ("ADD_SITE", "REMOVE_SITE"):
        assert data["target_site_id"] is not None
        assert data["target_service_definition_id"] is None
    else:
        assert data["target_service_definition_id"] is not None
        assert data["target_site_id"] is None


# ---------------------------------------------------------------------------
# FeeSchedule / DiscountTier
# ---------------------------------------------------------------------------


def assert_fee_schedule(data: dict) -> None:
    assert_common_fields(data, "FeeSchedule")
    assert is_valid_uuid(data["health_center_id"])
    assert isinstance(data["fpg_year"], int)
    assert isinstance(data["nominal_fee_cents"], int) and data["nominal_fee_cents"] >= 0
    assert data["status"] in ("DRAFT", "ADOPTED", "SUPERSEDED", "EXPIRED")
    assert data["review_status"] in ("CURRENT", "REVIEW_DUE", "OUT_OF_DATE")
    assert data["effective_start"] < data["effective_end"]


def assert_discount_tier(data: dict) -> None:
    assert_common_fields(data, "DiscountTier")
    assert is_valid_uuid(data["fee_schedule_id"])
    assert isinstance(data["tier_label"], str) and data["tier_label"]
    assert data["fpg_min_pct"] >= 0
    assert data["discount_kind"] in ("NOMINAL", "PERCENT_DISCOUNT", "NONE")
    assert isinstance(data["sort_order"], int) and data["sort_order"] >= 1
    if data["discount_kind"] == "PERCENT_DISCOUNT":
        assert data["discount_pct"] is not None
        assert 0 < data["discount_pct"] < 1
    else:
        assert data["discount_pct"] is None


def assert_tier_ladder_well_formed(tiers: list) -> None:
    """The ladder has neither a gap nor an overlap on the half-open convention."""
    ordered = sorted(tiers, key=lambda t: t["sort_order"])
    assert len(ordered) >= 2, "at least two bands exist"
    assert ordered[0]["fpg_min_pct"] == 0, "the lowest band's fpg_min_pct is 0"
    for previous, current in zip(ordered, ordered[1:]):
        assert current["fpg_min_pct"] == previous["fpg_max_pct"], (
            "each subsequent band's fpg_min_pct equals the previous band's "
            "fpg_max_pct"
        )
    unbounded = [t for t in ordered if t["fpg_max_pct"] is None]
    assert len(unbounded) == 1, "exactly one band has a null fpg_max_pct"
    assert unbounded[0]["sort_order"] == ordered[-1]["sort_order"]


# ---------------------------------------------------------------------------
# Patient / IncomeVerification
# ---------------------------------------------------------------------------


def assert_patient(data: dict) -> None:
    assert_common_fields(data, "Patient")
    assert isinstance(data["mrn"], str) and data["mrn"]
    assert isinstance(data["full_name"], str)
    assert isinstance(data["household_size"], int) and data["household_size"] >= 1
    assert data["sliding_fee_status"] in ("UNVERIFIED", "VERIFIED", "EXPIRED")
    assert isinstance(data["patient_balance_cents"], int)


def assert_income_verification(data: dict) -> None:
    assert_common_fields(data, "IncomeVerification")
    assert is_valid_uuid(data["patient_id"])
    assert isinstance(data["declared_annual_income_cents"], int)
    assert data["declared_annual_income_cents"] >= 0
    assert isinstance(data["household_size"], int) and data["household_size"] >= 1
    assert data["documentation_type"] in (
        "TAX_RETURN",
        "PAY_STUBS",
        "W2",
        "SELF_DECLARATION",
        "REFUSED",
    )
    assert data["status"] in (
        "SUBMITTED",
        "VERIFIED",
        "INSUFFICIENT_DOCUMENTATION",
        "SUPERSEDED",
        "EXPIRED",
    )
    assert isinstance(data["resubmit_round"], int) and data["resubmit_round"] >= 0
    assert isinstance(data["submitted_by_user_id"], str) and data["submitted_by_user_id"]
    assert data["expires_at"] is not None, "expires_at is 365 days after effective_date"


# ---------------------------------------------------------------------------
# Encounter / InabilityToPayWaiver
# ---------------------------------------------------------------------------


def assert_encounter(data: dict) -> None:
    assert_common_fields(data, "Encounter")
    assert is_valid_uuid(data["patient_id"])
    assert is_valid_uuid(data["service_site_id"])
    assert is_valid_uuid(data["service_definition_id"])
    assert is_valid_uuid(data["fee_schedule_id"]), "the pinned schedule is permanent"
    assert data["payer_type"] in (
        "SELF_PAY",
        "MEDICAID_MCO",
        "MEDICAID_FFS",
        "MEDICARE",
        "PRIVATE",
    )
    assert isinstance(data["gross_charge_cents"], int) and data["gross_charge_cents"] > 0
    assert isinstance(data["patient_charge_cents"], int)
    assert data["charge_basis"] in (
        "SLIDING_FEE_TIER",
        "FULL_CHARGE_UNVERIFIED",
        "THIRD_PARTY",
    )
    assert isinstance(data["sliding_fee_applied"], bool)
    assert data["sliding_fee_applied"] == (data["charge_basis"] == "SLIDING_FEE_TIER")
    assert data["pps_claim_status"] in (
        "UNBILLED",
        "BILLED",
        "PAID",
        "PENDING_ADJUSTMENT",
        "RECONCILED",
        "VOID",
    )
    assert data["wraparound_status"] in (
        "NOT_APPLICABLE",
        "PENDING",
        "CLAIMED",
        "REBILL_REQUIRED",
        "RECEIVED",
    )
    assert data["void_reason"] in (
        None,
        "DUPLICATE",
        "CODING_ERROR",
        "NONPAYMENT",
        "SITE_OUT_OF_SCOPE",
    )
    for money in (
        "charge_adjustment_cents",
        "waived_amount_cents",
        "pps_encounter_rate_cents",
        "mco_paid_cents",
        "wraparound_due_cents",
    ):
        assert isinstance(data[money], int), f"Encounter.{money} must be an integer"
    assert data["wraparound_due_cents"] >= 0, "the residual is floored at zero"
    if data["charge_basis"] != "SLIDING_FEE_TIER":
        assert data["pinned_discount_tier_id"] is None


def assert_waiver(data: dict) -> None:
    assert_common_fields(data, "InabilityToPayWaiver")
    assert is_valid_uuid(data["encounter_id"])
    assert data["waiver_reason"] in ("HOMELESS", "NO_INCOME", "HARDSHIP_ATTESTATION")
    assert data["status"] in ("REQUESTED", "GRANTED", "DENIED")
    assert isinstance(data["requested_by_user_id"], str) and data["requested_by_user_id"]
    assert isinstance(data["waived_amount_cents"], int)
    if data["status"] != "GRANTED":
        assert data["waived_amount_cents"] == 0


# ---------------------------------------------------------------------------
# UDSReport / QualityMeasureResult
# ---------------------------------------------------------------------------


def assert_uds_report(data: dict) -> None:
    assert_common_fields(data, "UDSReport")
    assert is_valid_uuid(data["health_center_id"])
    assert isinstance(data["reporting_year"], int)
    assert data["status"] in ("DRAFT", "SUBMITTED", "ACCEPTED", "RETURNED")
    for counter in (
        "total_patient_count",
        "patients_at_or_below_100_count",
        "patients_101_to_150_count",
        "patients_151_to_200_count",
        "patients_over_200_count",
        "unverified_patient_count",
        "included_measure_count",
        "return_round",
    ):
        assert isinstance(data[counter], int), f"UDSReport.{counter} must be an integer"
        assert data[counter] >= 0


def assert_income_distribution_conserved(data: dict) -> None:
    """Every reported patient lands in exactly one band or in the unverified tally."""
    banded = (
        data["patients_at_or_below_100_count"]
        + data["patients_101_to_150_count"]
        + data["patients_151_to_200_count"]
        + data["patients_over_200_count"]
        + data["unverified_patient_count"]
    )
    assert banded == data["total_patient_count"], (
        f"income bands plus unverified ({banded}) must equal total_patient_count "
        f"({data['total_patient_count']})"
    )


def assert_quality_measure_result(data: dict) -> None:
    assert_common_fields(data, "QualityMeasureResult")
    assert is_valid_uuid(data["uds_report_id"])
    assert isinstance(data["measure_code"], str) and data["measure_code"]
    assert isinstance(data["numerator"], int) and data["numerator"] >= 0
    assert isinstance(data["denominator"], int) and data["denominator"] >= 0
    assert 0 <= data["benchmark_pct"] <= 100
    assert data["inclusion_status"] in ("INCLUDED", "EXCLUDED_ZERO_DENOMINATOR")
    if data["inclusion_status"] == "EXCLUDED_ZERO_DENOMINATOR":
        assert data["rate_pct"] is None
        assert data["meets_benchmark"] is None


# ---------------------------------------------------------------------------
# SiteVisitFinding / CorrectiveActionPlan
# ---------------------------------------------------------------------------


def assert_site_visit_finding(data: dict) -> None:
    assert_common_fields(data, "SiteVisitFinding")
    assert is_valid_uuid(data["health_center_id"])
    assert isinstance(data["requirement_code"], str) and data["requirement_code"]
    assert data["severity"] in ("CONDITION", "PROGRESS_REPORT_ONLY")
    assert isinstance(data["finding_summary"], str)
    assert isinstance(data["cap_due_days"], int) and data["cap_due_days"] >= 1
    assert data["cap_due_at"] is not None
    assert data["status"] in ("OPEN", "CAP_SUBMITTED", "RESOLVED", "ESCALATED")
    assert isinstance(data["issued_by_user_id"], str) and data["issued_by_user_id"]


def assert_corrective_action_plan(data: dict) -> None:
    assert_common_fields(data, "CorrectiveActionPlan")
    assert is_valid_uuid(data["site_visit_finding_id"])
    assert isinstance(data["narrative"], str)
    assert isinstance(data["milestone_count"], int) and data["milestone_count"] >= 1
    assert data["target_completion_date"] is not None
    assert data["status"] in ("DRAFT", "SUBMITTED", "ACCEPTED", "REJECTED")
    assert isinstance(data["submit_round"], int) and data["submit_round"] >= 0
    assert isinstance(data["prepared_by_user_id"], str) and data["prepared_by_user_id"]


# ---------------------------------------------------------------------------
# Conserved-quantity checkers (PRD §2.8)
# ---------------------------------------------------------------------------


def assert_counters_match_recount(
    health_center: dict,
    *,
    in_scope_sites: int = None,
    in_scope_services: int = None,
    seated_board: int = None,
    open_conditions: int = None,
    wraparound_receivable_cents: int = None,
) -> None:
    """Each stored counter must equal a fresh recount, with zero drift."""
    if in_scope_sites is not None:
        assert health_center["in_scope_site_count"] == in_scope_sites
    if in_scope_services is not None:
        assert health_center["in_scope_service_count"] == in_scope_services
    if seated_board is not None:
        assert health_center["seated_board_count"] == seated_board
    if open_conditions is not None:
        assert health_center["open_condition_count"] == open_conditions
    if wraparound_receivable_cents is not None:
        assert (
            health_center["wraparound_receivable_cents"] == wraparound_receivable_cents
        )


def assert_patient_ledger(patient: dict, expected_cents: int) -> None:
    assert patient["patient_balance_cents"] == expected_cents, (
        f"patient_balance_cents must be exactly {expected_cents}, got "
        f"{patient['patient_balance_cents']} — the ledger tolerates zero drift"
    )


def same_instant(value):
    """Normalise a stamped instant so a zero millisecond suffix is not load-bearing.

    An instant stamped from the logical clock may be rendered either as
    `2026-08-01T00:00:00Z` or as `2026-08-01T00:00:00.000Z`; both name the same
    instant, and no rule in the PRD turns on which rendering is used.
    """
    if isinstance(value, str) and value.endswith(".000Z"):
        return value[:-5] + "Z"
    return value


def assert_governance_summary(data: dict) -> None:
    for field in (
        "health_center_id",
        "seated_board_count",
        "qualified_patient_seat_count",
        "non_patient_seat_count",
        "healthcare_industry_seat_count",
        "patient_seat_pct",
        "governance_posture",
        "version",
    ):
        assert field in data, f"the governance summary must expose {field}"
    assert data["governance_posture"] in (
        "GOVERNANCE_COMPLIANT",
        "GOVERNANCE_DEFICIENT",
    )
