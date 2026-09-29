"""Entity assertions and domain invariant checkers for the plan API."""
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

TERRITORIES = ["T01", "T02", "T03"]

CARRIER_STATUSES = ["ACTIVE", "EXIT_NOTICED", "EXIT_COMPLETE"]
CARRIER_POSTURES = ["OPEN", "RESTRICTED", "SUSPENDED"]
APPLICATION_STATUSES = [
    "SUBMITTED", "RETURNED_FOR_CURE", "REJECTED", "CERTIFIED_AWAITING_ASSIGNMENT",
    "ASSIGNED", "DEFERRED_NO_CARRIER", "POLICY_ISSUED", "CLOSED_CANCELLED", "CLOSED_EXITED",
]
ASSIGNMENT_STATUSES = [
    "PENDING_ACCEPTANCE", "ACCEPTED", "POLICY_ISSUED", "RESCINDED", "REASSIGNED", "CLOSED",
]
POLICY_STATUSES = [
    "IN_FORCE", "NON_RENEWAL_PENDING", "NON_RENEWED", "REASSIGNMENT_PENDING",
    "CANCELLED", "EXITED_TO_VOLUNTARY",
]
PREMIUM_SETTLEMENT_STATUSES = [
    "PREMIUM_OUTSTANDING", "PAID_IN_FULL", "REFUND_ISSUED", "BALANCE_DUE_AT_CANCELLATION",
]
CLAIM_STATUSES = ["OPEN", "ACKNOWLEDGED", "CLOSED_PAID", "CLOSED_DENIED"]
COMPLAINT_STATUSES = ["OPEN", "FINDINGS_RECORDED", "RESOLVED_UPHELD", "RESOLVED_NOT_UPHELD"]
PLAN_PERIOD_STATUSES = ["OPEN", "RECONCILING", "CLOSED"]
CYCLE_STATUSES = ["SCHEDULED", "COMPLETED"]
RECONCILIATION_STATUSES = ["FINAL", "SUPERSEDED"]


# --------------------------------------------------------------------------
# Common audit-field checks
# --------------------------------------------------------------------------
def assert_identity_fields(data: Dict[str, Any]) -> None:
    """Every resource carries a server-minted UUID id and a created_at timestamp."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a server-minted UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be an ISO 8601 UTC timestamp, got {data.get('created_at')!r}"


def assert_versioned_audit_fields(data: Dict[str, Any]) -> None:
    """Most resources also carry updated_at and an integer version starting at 1."""
    assert_identity_fields(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be an ISO 8601 UTC timestamp, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be an integer starting at 1, got {data.get('version')!r}"


def assert_no_updated_at_and_no_version(data: Dict[str, Any]) -> None:
    """A market rejection has no updated_at field and no version field at all."""
    assert "updated_at" not in data, "a market-rejection filing must not carry updated_at"
    assert "version" not in data, "a market-rejection filing must not carry version"


# --------------------------------------------------------------------------
# Entity assertions
# --------------------------------------------------------------------------
def assert_carrier(data: Dict[str, Any]) -> None:
    assert_versioned_audit_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["naic_code"], str) and data["naic_code"]
    assert isinstance(data["voluntary_market_share_bps"], int)
    assert isinstance(data["licensed_territories"], list) and data["licensed_territories"]
    assert all(t in TERRITORIES for t in data["licensed_territories"]), \
        f"licensed_territories must draw from {TERRITORIES}"
    assert len(set(data["licensed_territories"])) == len(data["licensed_territories"]), \
        "licensed_territories must contain no duplicates"
    assert isinstance(data["enrollment_sequence"], int) and data["enrollment_sequence"] >= 1
    assert data["status"] in CARRIER_STATUSES
    assert data["posture"] in CARRIER_POSTURES
    assert 0 <= data["performance_score"] <= 100, \
        f"performance_score is clamped to 0 through 100, got {data['performance_score']}"
    for field in ("breach_count_current_period", "upheld_complaint_count",
                  "non_renewal_count_current_period", "assigned_risk_count",
                  "quota_target_units", "penalty_balance_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert isinstance(data["voluntary_credit_units"], (int, float))
    assert isinstance(data["quota_variance_units"], (int, float))
    assert isinstance(data["overallocated"], bool)


def assert_producer(data: Dict[str, Any]) -> None:
    assert_versioned_audit_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert isinstance(data["appointed_territories"], list) and data["appointed_territories"]
    assert all(t in TERRITORIES for t in data["appointed_territories"])
    assert data["status"] in ["ACTIVE", "SUSPENDED"]


def assert_applicant(data: Dict[str, Any]) -> None:
    assert_versioned_audit_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["driver_license_number"], str) and data["driver_license_number"]
    assert data["territory_code"] in TERRITORIES
    assert data["driver_class"] in ["ADULT", "SENIOR", "YOUTHFUL_OPERATOR"]
    assert is_iso8601_timestamp(data["first_licensed_date"])
    assert isinstance(data["clean_years_credited"], int)
    assert 0 <= data["clean_years_credited"] <= 5, \
        f"clean_years_credited is capped at 5, got {data['clean_years_credited']}"
    assert isinstance(data["voluntary_market_eligible"], bool)


def assert_vehicle(data: Dict[str, Any]) -> None:
    assert_versioned_audit_fields(data)
    assert is_valid_uuid(data["applicant_id"])
    assert isinstance(data["vin"], str) and data["vin"]
    assert data["vehicle_class_code"] in ["PLEASURE", "WORK_LT10", "WORK_GE10", "BUSINESS"]
    assert data["garaging_territory_code"] in TERRITORIES
    assert isinstance(data["model_year"], int)


def assert_application(data: Dict[str, Any]) -> None:
    assert_versioned_audit_fields(data)
    for fk in ("applicant_id", "producer_id", "vehicle_id"):
        assert is_valid_uuid(data[fk]), f"{fk} must be a UUID"
    assert isinstance(data["intake_sequence"], int) and data["intake_sequence"] >= 1
    assert is_iso8601_timestamp(data["requested_effective_date"])
    assert isinstance(data["declared_violations"], list)
    assert data["status"] in APPLICATION_STATUSES
    for field in ("cure_count", "distinct_rejection_count", "surcharge_points_estimated",
                  "estimated_annual_premium_cents", "estimated_expense_charge_cents",
                  "estimated_total_charge_cents", "required_deposit_cents",
                  "deposit_paid_total_cents", "deposit_balance_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_market_rejection(data: Dict[str, Any]) -> None:
    assert_identity_fields(data)
    assert_no_updated_at_and_no_version(data)
    assert is_valid_uuid(data["application_id"])
    assert isinstance(data["rejecting_carrier_naic_code"], str)
    assert is_iso8601_timestamp(data["rejection_date"])
    assert data["reason_code"] in ["UNACCEPTABLE_DRIVING_RECORD", "UNDERWRITING_GUIDELINES",
                                  "NO_APPETITE_TERRITORY", "PRIOR_CANCELLATION"]
    assert isinstance(data["document_reference"], str) and data["document_reference"]


def assert_plan_period(data: Dict[str, Any]) -> None:
    assert_versioned_audit_fields(data)
    assert isinstance(data["period_code"], str) and data["period_code"]
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert isinstance(data["underserved_territories"], list)
    assert all(t in TERRITORIES for t in data["underserved_territories"])
    assert data["status"] in PLAN_PERIOD_STATUSES
    assert isinstance(data["total_assignable_units"], int)
    assert isinstance(data["total_assignable_car_years"], (int, float))


def assert_assignment_cycle(data: Dict[str, Any]) -> None:
    assert_versioned_audit_fields(data)
    assert is_valid_uuid(data["plan_period_id"])
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert data["status"] in CYCLE_STATUSES
    assert isinstance(data["assigned_count"], int) and data["assigned_count"] >= 0
    assert isinstance(data["deferred_count"], int) and data["deferred_count"] >= 0


def assert_assignment(data: Dict[str, Any]) -> None:
    assert_versioned_audit_fields(data)
    assert is_valid_uuid(data["application_id"])
    assert is_valid_uuid(data["carrier_id"])
    assert data["assignment_kind"] in ["INITIAL", "REASSIGNMENT"]
    assert data["status"] in ASSIGNMENT_STATUSES
    assert isinstance(data["batch_sequence"], int) and data["batch_sequence"] >= 1
    assert is_iso8601_timestamp(data["acceptance_deadline"])
    assert isinstance(data["deficit_score_at_selection"], (int, float))
    assert isinstance(data["provisional_premium_cents"], int)
    if data.get("rescission_reason_code") is not None:
        assert data["rescission_reason_code"] in [
            "ISSUANCE_DEADLINE_MISSED", "CARRIER_INELIGIBLE", "ASSIGNMENT_ERROR"]


def assert_policy(data: Dict[str, Any]) -> None:
    assert_versioned_audit_fields(data)
    assert is_valid_uuid(data["assignment_id"])
    assert is_valid_uuid(data["carrier_id"])
    assert isinstance(data["policy_number"], str) and data["policy_number"]
    assert is_iso8601_timestamp(data["effective_date"])
    assert is_iso8601_timestamp(data["expiration_date"])
    assert data["policy_status"] in POLICY_STATUSES
    assert data["premium_settlement_status"] in PREMIUM_SETTLEMENT_STATUSES
    assert isinstance(data["premium_lines"], dict)
    assert set(data["premium_lines"].keys()) == {"BI", "PD", "UM"}, \
        "premium_lines must carry exactly the BI, PD and UM coverage lines"
    for field in ("surcharge_points_applied", "final_premium_cents", "plan_expense_charge_cents",
                  "total_annual_charge_cents", "premium_credited_cents",
                  "additional_premium_due_cents", "refund_paid_cents", "balance_due_cents",
                  "earned_premium_cents", "non_renewal_notice_count", "rating_revision",
                  "open_complaint_count"):
        assert isinstance(data[field], int), f"{field} must be an integer number of cents or a count"
    assert isinstance(data["surcharge_factor_applied"], (int, float))
    assert isinstance(data["reassignment_required"], bool)
    assert isinstance(data["complaint_freeze_active"], bool)
    assert isinstance(data["exposure_car_years_current_period"], (int, float))
    if data.get("refund_basis") is not None:
        assert data["refund_basis"] in ["PRO_RATA", "SHORT_RATE"]


def assert_claim(data: Dict[str, Any]) -> None:
    assert_versioned_audit_fields(data)
    assert is_valid_uuid(data["policy_id"])
    assert is_iso8601_timestamp(data["loss_date"])
    assert isinstance(data["at_fault"], bool)
    assert data["coverage_line"] in ["BI", "PD", "UM"]
    assert isinstance(data["reserve_cents"], int) and data["reserve_cents"] >= 0
    assert is_iso8601_timestamp(data["reported_at"])
    assert is_iso8601_timestamp(data["acknowledgement_deadline"])
    assert data["status"] in CLAIM_STATUSES
    assert isinstance(data["standard_breach"], bool)
    assert isinstance(data["paid_cents"], int) and data["paid_cents"] >= 0


def assert_complaint(data: Dict[str, Any]) -> None:
    assert_versioned_audit_fields(data)
    assert is_valid_uuid(data["policy_id"])
    assert is_valid_uuid(data["carrier_id"])
    assert data["complaint_type"] in ["CLAIM_HANDLING_DELAY", "RATING_DISPUTE",
                                     "CANCELLATION_DISPUTE", "SERVICE_STANDARD"]
    assert isinstance(data["narrative"], str) and 1 <= len(data["narrative"]) <= 2000
    assert data["status"] in COMPLAINT_STATUSES
    assert isinstance(data["review_round"], int) and data["review_round"] >= 1
    if data.get("disposition") is not None:
        assert data["disposition"] in ["UPHELD", "NOT_UPHELD", "RETURNED_FOR_FURTHER_REVIEW"]


def assert_quota_reconciliation(data: Dict[str, Any]) -> None:
    assert_versioned_audit_fields(data)
    assert is_valid_uuid(data["carrier_id"])
    assert is_valid_uuid(data["plan_period_id"])
    assert data["basis"] in ["POLICY_COUNT", "CAR_YEAR_EXPOSURE"]
    for field in ("obligation_units", "credited_units", "variance_units",
                  "voluntary_credit_units_applied"):
        assert isinstance(data[field], (int, float)), f"{field} must be numeric"
    assert isinstance(data["penalty_cents"], int) and data["penalty_cents"] >= 0
    assert data["status"] in RECONCILIATION_STATUSES


# --------------------------------------------------------------------------
# Domain invariants
# --------------------------------------------------------------------------
def assert_deposit_ledger_conserved(application: Dict[str, Any],
                                    policies: Optional[List[Dict[str, Any]]] = None) -> None:
    """No cent is created and no cent vanishes: the cumulative deposit equals the
    uncredited balance plus every cent credited to premium plus every cent refunded."""
    policies = policies or []
    credited = sum(p["premium_credited_cents"] for p in policies)
    refunded = sum(p["refund_paid_cents"] for p in policies)
    total = application["deposit_paid_total_cents"]
    assert total == application["deposit_balance_cents"] + credited + refunded, (
        f"deposit ledger broken: deposit_paid_total_cents={total} but "
        f"deposit_balance_cents={application['deposit_balance_cents']} + "
        f"premium_credited_cents={credited} + refund_paid_cents={refunded}"
    )


def assert_premium_lines_sum_to_final_premium(policy: Dict[str, Any]) -> None:
    """The final premium is the sum of the three rounded per-coverage-line premiums."""
    lines = policy["premium_lines"]
    total = lines["BI"] + lines["PD"] + lines["UM"]
    assert total == policy["final_premium_cents"], (
        f"premium_lines {lines} sum to {total} but final_premium_cents is "
        f"{policy['final_premium_cents']}"
    )


def assert_total_annual_charge(policy: Dict[str, Any]) -> None:
    """The term charge is the final premium plus the plan expense charge."""
    expected = policy["final_premium_cents"] + policy["plan_expense_charge_cents"]
    assert policy["total_annual_charge_cents"] == expected, (
        f"total_annual_charge_cents should be {expected}, got "
        f"{policy['total_annual_charge_cents']}"
    )


def assert_posture_ladder(carrier: Dict[str, Any]) -> None:
    """The posture ladder is ordered and the first matching rule wins."""
    if carrier["status"] != "ACTIVE":
        expected = "SUSPENDED"
    elif carrier["performance_score"] < 70:
        expected = "SUSPENDED"
    elif carrier["performance_score"] <= 84:
        expected = "RESTRICTED"
    elif carrier["breach_count_current_period"] >= 3:
        expected = "RESTRICTED"
    elif carrier["overallocated"]:
        expected = "RESTRICTED"
    else:
        expected = "OPEN"
    assert carrier["posture"] == expected, (
        f"posture should be {expected} for status={carrier['status']}, "
        f"performance_score={carrier['performance_score']}, "
        f"breach_count_current_period={carrier['breach_count_current_period']}, "
        f"overallocated={carrier['overallocated']}, got {carrier['posture']}"
    )


def assert_quota_variance(carrier: Dict[str, Any]) -> None:
    """Variance is the live headcount plus applied credit less the target, and the
    overallocated flag follows its sign."""
    assert carrier["overallocated"] == (carrier["quota_variance_units"] > 0), (
        f"overallocated should follow the sign of quota_variance_units="
        f"{carrier['quota_variance_units']}, got {carrier['overallocated']}"
    )


def assert_targets_sum_to_assignable_total(carriers: List[Dict[str, Any]],
                                           plan_period: Dict[str, Any]) -> None:
    """Largest-remainder apportionment distributes the assignable total exactly."""
    total = sum(c["quota_target_units"] for c in carriers)
    assert total == plan_period["total_assignable_units"], (
        f"quota_target_units sum to {total} but total_assignable_units is "
        f"{plan_period['total_assignable_units']}"
    )


def assert_pagination_meta(meta: Dict[str, Any], expected_total: Optional[int] = None,
                           expected_limit: Optional[int] = None,
                           expected_offset: Optional[int] = None) -> None:
    for field in ("limit", "offset", "total_count", "has_more"):
        assert field in meta, f"list responses must report {field} inside meta"
    if expected_total is not None:
        assert meta["total_count"] == expected_total, \
            f"total_count should be {expected_total}, got {meta['total_count']}"
    if expected_limit is not None:
        assert meta["limit"] == expected_limit
    if expected_offset is not None:
        assert meta["offset"] == expected_offset


def assert_ordered_by_created_at(rows: List[Dict[str, Any]], tie_break_field: Optional[str] = None
                                 ) -> None:
    """List results are ordered by created_at ascending, with an optional ordinal
    tie-break within the same created_at."""
    keys = []
    for row in rows:
        keys.append((row["created_at"], row[tie_break_field] if tie_break_field else 0))
    assert keys == sorted(keys), f"rows are not ordered by created_at ascending: {keys}"
