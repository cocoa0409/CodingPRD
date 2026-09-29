"""Entity-shape assertions and domain invariant checkers."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    AT_RISK_THRESHOLD_POINTS,
    DEFICIENT_THRESHOLD_POINTS,
    FROZEN_THRESHOLD_POINTS,
    NON_ACCRUAL_DAILY_RATE_CENTS,
    NON_ACCRUAL_DAYS_OPEN,
    NON_ACCRUAL_SIZE_MULTIPLIER,
    PENALTY_CAP_CENTS,
    SCORE_TOLERANCE,
    SIZE_MULTIPLIER_LARGE,
    SIZE_MULTIPLIER_MEDIUM,
    SIZE_MULTIPLIER_SMALL,
    SIZE_TIER_LARGE_FLOOR,
    SIZE_TIER_MEDIUM_FLOOR,
)
from .types import (
    ENTRY_ACCRUAL,
    POSTURE_AT_RISK,
    POSTURE_COMPLIANT,
    POSTURE_DEFICIENT,
    POSTURE_FROZEN,
)

JsonDict = Mapping[str, Any]


# ---------------------------------------------------------------------------
# Common identity block
# ---------------------------------------------------------------------------


def assert_identity_fields(entity: JsonDict) -> None:
    """Every resource carries a UUID ``id`` and an ISO 8601 ``created_at``."""
    assert is_valid_uuid(entity["id"]), f"id is not a bare UUID: {entity['id']!r}"
    assert is_iso8601_timestamp(
        entity["created_at"]
    ), f"created_at is not ISO 8601: {entity['created_at']!r}"


def assert_versioned_entity(entity: JsonDict) -> None:
    """Resources other than ledger entries also carry ``updated_at`` and ``version``."""
    assert_identity_fields(entity)
    assert is_iso8601_timestamp(
        entity["updated_at"]
    ), f"updated_at is not ISO 8601: {entity['updated_at']!r}"
    assert isinstance(entity["version"], int), "version must be an integer"
    assert entity["version"] >= 1, "version starts at 1"


def assert_no_version_discipline(entity: JsonDict) -> None:
    """A ledger entry carries neither ``updated_at`` nor ``version``."""
    assert "updated_at" not in entity, "a ledger entry has no updated_at"
    assert "version" not in entity, "a ledger entry has no version"


# ---------------------------------------------------------------------------
# Per-entity shape assertions
# ---------------------------------------------------------------------------


def assert_plan_year(plan_year: JsonDict) -> None:
    """Shape check for a plan year."""
    assert_versioned_entity(plan_year)
    for field in (
        "sponsor_name",
        "plan_year_label",
        "start_date",
        "end_date",
        "covered_lives",
        "attestation_deadline_date",
        "rxdc_deadline_date",
        "lifecycle_status",
        "compliance_posture",
        "deficiency_points",
        "penalty_exposure_cents",
        "tool_sla_breach_count",
        "attestation_status",
        "freeze_flag",
    ):
        assert field in plan_year, f"plan year is missing {field}"
    assert plan_year["lifecycle_status"] in (
        "SETUP",
        "ACTIVE",
        "REPORTING_CLOSED",
    )
    assert plan_year["compliance_posture"] in (
        POSTURE_COMPLIANT,
        POSTURE_AT_RISK,
        POSTURE_DEFICIENT,
        POSTURE_FROZEN,
    )
    assert isinstance(plan_year["deficiency_points"], int)
    assert isinstance(plan_year["penalty_exposure_cents"], int)
    assert isinstance(plan_year["tool_sla_breach_count"], int)
    assert isinstance(plan_year["freeze_flag"], bool)
    assert plan_year["covered_lives"] >= 1


def assert_vendor(vendor: JsonDict) -> None:
    """Shape check for a vendor."""
    assert_versioned_entity(vendor)
    for field in ("legal_name", "vendor_type", "contact_email"):
        assert field in vendor, f"vendor is missing {field}"
    assert vendor["vendor_type"] in (
        "TPA",
        "PBM",
        "BROKER",
        "CONSULTANT",
        "NETWORK_VENDOR",
    )


def assert_contract(contract: JsonDict) -> None:
    """Shape check for a service provider contract."""
    assert_versioned_entity(contract)
    for field in (
        "plan_year_id",
        "vendor_id",
        "contract_type",
        "term_start",
        "term_end",
        "annual_fee_cents",
        "gag_review_status",
        "data_rights_status",
        "clause_inventory_count",
        "prohibited_clause_count",
        "remediation_round",
        "gag_non_compliant_since",
        "compensation_disclosure_required",
    ):
        assert field in contract, f"contract is missing {field}"
    assert contract["gag_review_status"] in (
        "NOT_REVIEWED",
        "IN_REVIEW",
        "REMEDIATION_REQUESTED",
        "COMPLIANT",
        "NON_COMPLIANT",
    )
    assert contract["data_rights_status"] in (
        "NOT_SECURED",
        "PENDING_AMENDMENT",
        "SECURED",
    )
    assert isinstance(contract["compensation_disclosure_required"], bool)
    assert isinstance(contract["annual_fee_cents"], int)


def assert_amendment(amendment: JsonDict) -> None:
    """Shape check for a contract amendment."""
    assert_versioned_entity(amendment)
    for field in (
        "contract_id",
        "amendment_type",
        "status",
        "round",
        "proposed_terms_summary",
        "counter_terms_summary",
        "data_rights_granted",
        "expires_at",
        "executed_at",
        "executed_terms_note",
        "withdrawal_reason",
    ):
        assert field in amendment, f"amendment is missing {field}"
    assert amendment["amendment_type"] in (
        "DATA_RIGHTS",
        "GAG_CLAUSE_REMOVAL",
        "COOPERATION_SLA",
    )
    assert amendment["status"] in (
        "PROPOSED",
        "COUNTERED",
        "EXECUTED",
        "WITHDRAWN",
        "LAPSED",
    )
    assert isinstance(amendment["data_rights_granted"], bool)
    assert amendment["round"] >= 1


def assert_compensation_disclosure(disclosure: JsonDict) -> None:
    """Shape check for a compensation disclosure."""
    assert_versioned_entity(disclosure)
    for field in (
        "contract_id",
        "status",
        "direct_comp_cents",
        "indirect_comp_cents",
        "benchmark_median_cents",
        "services_scope_score",
        "disclosure_completeness_score",
        "variant_applied",
        "component_price_score",
        "component_scope_score",
        "component_disclosure_score",
        "unreasonableness_score",
        "assessed_at",
        "assessed_by_user_id",
    ):
        assert field in disclosure, f"disclosure is missing {field}"
    assert disclosure["status"] in ("RECEIVED", "REASONABLE", "UNREASONABLE")
    assert isinstance(disclosure["direct_comp_cents"], int)
    assert isinstance(disclosure["indirect_comp_cents"], int)
    assert isinstance(disclosure["benchmark_median_cents"], int)


def assert_machine_readable_file(mrf: JsonDict) -> None:
    """Shape check for a machine-readable file."""
    assert_versioned_entity(mrf)
    for field in (
        "plan_year_id",
        "file_type",
        "posting_month",
        "public_url",
        "row_count",
        "schema_version",
        "status",
        "validation_error_count",
        "published_at",
        "superseded_at",
    ):
        assert field in mrf, f"file is missing {field}"
    assert mrf["file_type"] in ("IN_NETWORK_RATES", "ALLOWED_AMOUNTS")
    assert mrf["status"] in (
        "DRAFT",
        "VALIDATING",
        "PUBLISHED",
        "REJECTED",
        "SUPERSEDED",
    )
    assert mrf["row_count"] >= 1


def assert_refresh_cycle(cycle: JsonDict) -> None:
    """Shape check for a refresh cycle."""
    assert_versioned_entity(cycle)
    for field in (
        "plan_year_id",
        "period_month",
        "period_start",
        "period_end",
        "deadline_at",
        "status",
        "certified_at",
        "certified_by_user_id",
        "certification_note",
        "on_time",
    ):
        assert field in cycle, f"refresh cycle is missing {field}"
    assert cycle["status"] in ("PENDING", "CERTIFIED", "LATE_CERTIFIED", "MISSED")


def assert_price_comparison_tool(tool: JsonDict) -> None:
    """Shape check for a price comparison tool."""
    assert_versioned_entity(tool)
    for field in (
        "plan_year_id",
        "tool_name",
        "covered_items_count",
        "sla_target_uptime_pct",
        "status",
        "launched_at",
        "outage_windows",
        "last_evaluated_month",
        "last_uptime_pct",
        "last_downtime_minutes",
        "sla_breach_open",
        "breach_onset_date",
    ):
        assert field in tool, f"tool is missing {field}"
    assert tool["status"] in ("PENDING_LAUNCH", "LIVE")
    assert isinstance(tool["outage_windows"], list)
    assert isinstance(tool["sla_breach_open"], bool)


def assert_outage_window_shape(window: JsonDict) -> None:
    """Each stored outage window holds exactly ``window_start``/``window_end``/``cause``."""
    assert set(window.keys()) == {
        "window_start",
        "window_end",
        "cause",
    }, f"outage window holds unexpected keys: {sorted(window.keys())}"


def assert_rx_submission(submission: JsonDict) -> None:
    """Shape check for a prescription-drug data submission."""
    assert_versioned_entity(submission)
    for field in (
        "plan_year_id",
        "reference_year",
        "status",
        "assembled_record_count",
        "gross_spend_cents",
        "rebate_reported_cents",
        "rebate_cap_pct",
        "rebate_credit_cents",
        "net_plan_spend_cents",
        "reconciled_at",
        "submitted_at",
    ):
        assert field in submission, f"submission is missing {field}"
    assert submission["status"] in ("OPEN", "ASSEMBLING", "RECONCILED", "SUBMITTED")
    assert isinstance(submission["assembled_record_count"], int)


def assert_vendor_data_package(package: JsonDict) -> None:
    """Shape check for a vendor data package."""
    assert_versioned_entity(package)
    for field in (
        "rx_submission_id",
        "vendor_id",
        "data_section",
        "expected_record_count",
        "status",
        "record_count",
        "plan_paid_cents",
        "member_paid_cents",
        "rebate_cents",
        "delivery_round",
        "rejection_reason",
        "validated_at",
    ):
        assert field in package, f"package is missing {field}"
    assert package["data_section"] in (
        "D2_SPENDING",
        "D6_RX_TOTALS",
        "D7_RX_REBATES",
        "D8_PREMIUM_IMPACT",
    )
    assert package["status"] in ("EXPECTED", "RECEIVED", "VALIDATED", "REJECTED")
    assert isinstance(package["delivery_round"], int)


def assert_attestation(attestation: JsonDict) -> None:
    """Shape check for an attestation."""
    assert_versioned_entity(attestation)
    for field in (
        "plan_year_id",
        "attestation_type",
        "status",
        "contract_terms_doc_count",
        "prepared_by_user_id",
        "submitted_by_user_id",
        "submitted_at",
        "signature_statement",
        "rejection_reason",
        "void_reason",
        "revision_round",
    ):
        assert field in attestation, f"attestation is missing {field}"
    assert attestation["attestation_type"] == "GAG_CLAUSE_CEE"
    assert attestation["status"] in (
        "DRAFT",
        "SUBMITTED",
        "ACCEPTED",
        "REJECTED",
        "VOIDED",
    )
    assert isinstance(attestation["revision_round"], int)


def assert_penalty_ledger_entry(entry: JsonDict) -> None:
    """Shape check for a penalty ledger entry, which is immutable."""
    assert_identity_fields(entry)
    assert_no_version_discipline(entry)
    for field in (
        "plan_year_id",
        "entry_type",
        "deficiency_type",
        "signed_amount_cents",
        "daily_rate_cents",
        "days_open",
        "size_multiplier",
        "onset_date",
        "reverses_entry_id",
        "remediation_plan_id",
        "reason",
        "posted_by_user_id",
    ):
        assert field in entry, f"ledger entry is missing {field}"
    assert entry["entry_type"] in ("ACCRUAL", "ABATEMENT")
    assert entry["deficiency_type"] in (
        "MRF_REFRESH",
        "TOOL_SLA",
        "RXDC_LATE",
        "GAG_CLAUSE",
        "ATTESTATION_LATE",
    )
    assert isinstance(entry["signed_amount_cents"], int)
    assert isinstance(entry["daily_rate_cents"], int)
    assert isinstance(entry["days_open"], int)
    if entry["entry_type"] == ENTRY_ACCRUAL:
        assert entry["signed_amount_cents"] > 0, "accruals carry a positive amount"
    else:
        assert entry["signed_amount_cents"] < 0, "abatements carry a negative amount"
    assert abs(entry["signed_amount_cents"]) <= PENALTY_CAP_CENTS


def assert_remediation_plan(plan: JsonDict) -> None:
    """Shape check for a remediation plan."""
    assert_versioned_entity(plan)
    for field in (
        "plan_year_id",
        "target_deficiency_type",
        "status",
        "milestone_count",
        "completed_milestone_count",
        "last_milestone_label",
        "plan_summary",
        "abatement_posted_cents",
        "completed_at",
    ):
        assert field in plan, f"remediation plan is missing {field}"
    assert plan["status"] in ("ACTIVE", "COMPLETED")
    assert plan["milestone_count"] >= 1


def assert_compliance_run_summary(summary: JsonDict) -> None:
    """The compliance run returns its own summary object, not the plan year."""
    for field in (
        "run_id",
        "cycles_missed_count",
        "amendments_lapsed_count",
        "accruals_posted_count",
        "posture_before",
        "posture_after",
        "deficiency_points",
        "penalty_exposure_cents",
    ):
        assert field in summary, f"run summary is missing {field}"
    for absent in ("lifecycle_status", "sponsor_name", "plan_year_label"):
        assert absent not in summary, f"run summary must not echo {absent}"
    assert isinstance(summary["cycles_missed_count"], int)
    assert isinstance(summary["amendments_lapsed_count"], int)
    assert isinstance(summary["accruals_posted_count"], int)


def assert_penalty_projection(projection: JsonDict) -> None:
    """The projection returns its own object with both variants."""
    for field in (
        "statutory_maximum_cents",
        "accrued_to_date_cents",
        "open_deficiency_count",
        "size_multiplier",
    ):
        assert field in projection, f"projection is missing {field}"
    assert isinstance(projection["statutory_maximum_cents"], int)
    assert isinstance(projection["accrued_to_date_cents"], int)
    assert isinstance(projection["open_deficiency_count"], int)
    assert projection["statutory_maximum_cents"] <= PENALTY_CAP_CENTS
    assert projection["accrued_to_date_cents"] <= PENALTY_CAP_CENTS


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------


def expected_size_multiplier(covered_lives: int) -> float:
    """The size multiplier selected from the plan year's enrolled headcount."""
    if covered_lives >= SIZE_TIER_LARGE_FLOOR:
        return SIZE_MULTIPLIER_LARGE
    if covered_lives >= SIZE_TIER_MEDIUM_FLOOR:
        return SIZE_MULTIPLIER_MEDIUM
    return SIZE_MULTIPLIER_SMALL


def expected_posture(deficiency_points: int, freeze_flag: bool = False) -> str:
    """Walk the posture ladder top down; both thresholds are inclusive."""
    if freeze_flag or deficiency_points >= FROZEN_THRESHOLD_POINTS:
        return POSTURE_FROZEN
    if deficiency_points >= DEFICIENT_THRESHOLD_POINTS:
        return POSTURE_DEFICIENT
    if deficiency_points >= AT_RISK_THRESHOLD_POINTS:
        return POSTURE_AT_RISK
    return POSTURE_COMPLIANT


def assert_posture_matches_points(plan_year: JsonDict) -> None:
    """The posture is always the ladder's verdict on the stored point total."""
    assert plan_year["compliance_posture"] == expected_posture(
        plan_year["deficiency_points"], plan_year["freeze_flag"]
    ), (
        f"posture {plan_year['compliance_posture']} disagrees with "
        f"{plan_year['deficiency_points']} points "
        f"(freeze_flag={plan_year['freeze_flag']})"
    )


def assert_exposure_equals_ledger(
    plan_year: JsonDict, entries: Sequence[JsonDict]
) -> None:
    """Exposure is the exact integer sum of every entry's signed amount."""
    ledger_total = sum(entry["signed_amount_cents"] for entry in entries)
    assert plan_year["penalty_exposure_cents"] == ledger_total, (
        f"penalty_exposure_cents {plan_year['penalty_exposure_cents']} does not "
        f"equal the ledger sum {ledger_total}"
    )


def assert_non_accrual_pricing_fields(entry: JsonDict) -> None:
    """Entries that are not accruals carry the fixed non-accrual pricing block."""
    assert entry["daily_rate_cents"] == NON_ACCRUAL_DAILY_RATE_CENTS
    assert entry["days_open"] == NON_ACCRUAL_DAYS_OPEN
    assert entry["size_multiplier"] == NON_ACCRUAL_SIZE_MULTIPLIER
    assert entry["onset_date"] is None


def assert_accrual_pricing(
    entry: JsonDict,
    expected_daily_rate_cents: int,
    expected_days_open: int,
    expected_size_multiplier_value: float,
) -> None:
    """The accrual's stored inputs and its priced amount agree."""
    assert entry["daily_rate_cents"] == expected_daily_rate_cents
    assert entry["days_open"] == expected_days_open
    assert entry["size_multiplier"] == expected_size_multiplier_value
    raw = expected_daily_rate_cents * expected_days_open
    expected_amount = min(
        round_half_up_to_cents(raw * expected_size_multiplier_value),
        PENALTY_CAP_CENTS,
    )
    assert entry["signed_amount_cents"] == expected_amount, (
        f"signed_amount_cents {entry['signed_amount_cents']} does not equal "
        f"{expected_daily_rate_cents} x {expected_days_open} x "
        f"{expected_size_multiplier_value} = {expected_amount}"
    )


def round_half_up_to_cents(value: float) -> int:
    """Round half up to a whole cent — a tie rounds away from zero."""
    from decimal import Decimal, ROUND_HALF_UP

    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_to_two_places(value: float) -> float:
    """Round half up to exactly two decimal places."""
    from decimal import Decimal, ROUND_HALF_UP

    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def assert_two_decimal_places(value: float) -> None:
    """Uptime percentages and score components carry two decimal places."""
    assert value == round_half_up_to_two_places(
        value
    ), f"{value} is not held to two decimal places"


def assert_score_close(actual: float, expected: float) -> None:
    """Compare a two-decimal score to its expected value."""
    assert (
        abs(actual - expected) < SCORE_TOLERANCE
    ), f"score {actual} does not match expected {expected}"


def assert_unreasonableness_is_sum_of_components(disclosure: JsonDict) -> None:
    """The score is the sum of the three already-rounded components."""
    component_sum = (
        disclosure["component_price_score"]
        + disclosure["component_scope_score"]
        + disclosure["component_disclosure_score"]
    )
    assert_score_close(disclosure["unreasonableness_score"], component_sum)


def normalize_instant(value: str) -> str:
    """Render a UTC instant with exactly three fractional digits."""
    assert isinstance(value, str) and value.endswith(
        "Z"
    ), f"not a UTC instant: {value!r}"
    body = value[:-1]
    if "." in body:
        head, fraction = body.split(".", 1)
        fraction = (fraction + "000")[:3]
    else:
        head, fraction = body, "000"
    return f"{head}.{fraction}Z"


def assert_instant_equals(actual: Any, expected: str) -> None:
    """Two UTC instants name the same millisecond."""
    assert actual is not None, f"expected the instant {expected}, found null"
    assert normalize_instant(actual) == normalize_instant(
        expected
    ), f"expected the instant {expected}, found {actual!r}"


def assert_created_at_ascending(entries: Sequence[JsonDict]) -> None:
    """List results are ordered by ``created_at`` ascending — oldest row first."""
    stamps = [entry["created_at"] for entry in entries]
    assert stamps == sorted(stamps), f"rows are not in created_at order: {stamps}"


def assert_ids_unique(entities: Sequence[JsonDict]) -> None:
    """No identifier repeats within one collection read."""
    ids = [entity["id"] for entity in entities]
    assert len(ids) == len(set(ids)), f"duplicate identifiers returned: {ids}"
