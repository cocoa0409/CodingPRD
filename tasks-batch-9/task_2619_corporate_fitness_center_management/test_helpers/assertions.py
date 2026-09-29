"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# --------------------------------------------------------------------------
# Shared record-identity helpers
# --------------------------------------------------------------------------
def assert_versioned_record(data: dict):
    """Records that carry id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a server-minted UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be an ISO 8601 UTC instant: {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be an ISO 8601 UTC instant: {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer starting at 1, got {data.get('version')!r}"
    )


def assert_append_only_record(data: dict):
    """Append-only events carry only id and created_at — never updated_at or
    version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a server-minted UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be an ISO 8601 UTC instant: {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, "append-only record must not expose updated_at"
    assert "version" not in data, "append-only record must not expose version"


def assert_three_fractional_digits(timestamp: str):
    """PRD timestamps are ISO 8601 UTC instants with exactly three fractional
    digits."""
    assert isinstance(timestamp, str) and timestamp, f"expected a timestamp, got {timestamp!r}"
    body = timestamp[:-1] if timestamp.endswith("Z") else timestamp
    assert "." in body, f"timestamp {timestamp!r} must carry fractional seconds"
    fraction = body.split(".")[-1]
    assert len(fraction) == 3 and fraction.isdigit(), (
        f"timestamp {timestamp!r} must carry exactly three fractional digits"
    )


def assert_no_type_prefix(identifier: str):
    assert is_valid_uuid(identifier), f"{identifier!r} must be a bare UUID"
    assert "_" not in identifier, f"{identifier!r} must not carry a type prefix"


# --------------------------------------------------------------------------
# Per-entity assertions
# --------------------------------------------------------------------------
def assert_client_contract(data: dict):
    assert_versioned_record(data)
    assert isinstance(data["client_name"], str) and 1 <= len(data["client_name"]) <= 120
    assert isinstance(data["site_code"], str) and data["site_code"]
    assert data["fee_structure"] in ("MANAGEMENT_FEE", "COST_PLUS")
    assert data["staffing_model"] in ("OPERATOR_EMPLOYED", "CLIENT_EMPLOYED", "HYBRID")
    assert data["status"] in (
        "DRAFT", "PENDING_CLIENT_APPROVAL", "ACTIVE", "SUSPENDED", "TERMINATED", "WITHDRAWN",
    )
    assert isinstance(data["revision_round"], int) and data["revision_round"] >= 0
    for counter in (
        "ytd_billed_cents",
        "pending_penalty_cents",
        "uncovered_session_count",
        "eligible_member_count",
    ):
        assert isinstance(data[counter], int), f"{counter} must be an integer"
    assert isinstance(data["participation_target_pct"], int)
    assert 1 <= data["participation_target_pct"] <= 100
    assert data["budgeted_staff_fte"] > 0
    if data["fee_structure"] == "MANAGEMENT_FEE":
        assert data["not_to_exceed_cents"] is None, (
            "a MANAGEMENT_FEE contract must leave not_to_exceed_cents null"
        )
        assert data["management_fee_cents"] is not None
    else:
        assert data["management_fee_cents"] is None, (
            "a COST_PLUS contract must leave management_fee_cents null"
        )
        assert data["not_to_exceed_cents"] > 0


def assert_staff_member(data: dict):
    assert_versioned_record(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["role_type"] in (
        "SITE_MANAGER", "GROUP_EX_INSTRUCTOR", "PERSONAL_TRAINER", "WELLNESS_COORDINATOR",
    )
    assert data["employment_type"] in ("OPERATOR_EMPLOYED", "CLIENT_EMPLOYED")
    assert isinstance(data["hourly_cost_cents"], int) and data["hourly_cost_cents"] > 0
    assert data["duty_status"] in ("ACTIVE_DUTY", "SUSPENDED_FROM_DUTY", "OFFBOARDED")
    assert isinstance(data["readiness_index"], int)
    assert 0 <= data["readiness_index"] <= 100, "readiness_index is an integer 0-100"
    assert isinstance(data["committed_minutes_current_period"], int)
    assert data["committed_minutes_current_period"] >= 0
    assert isinstance(data["required_credential_types"], list)


def assert_staff_credential(data: dict):
    assert_versioned_record(data)
    assert data["credential_type"] in ("CPR_AED", "FIRST_AID", "GROUP_EX_CERT", "PT_CERT")
    assert data["status"] in (
        "PENDING_VERIFICATION", "VERIFIED", "EXPIRING_SOON", "EXPIRED", "REJECTED",
    )
    assert isinstance(data["issuer"], str) and data["issuer"]
    assert isinstance(data["credential_number"], str) and data["credential_number"]
    assert isinstance(data["renewal_count"], int) and data["renewal_count"] >= 0


def assert_facility_room(data: dict):
    assert_versioned_record(data)
    assert data["room_type"] in ("STUDIO", "WEIGHT_FLOOR", "CARDIO_FLOOR", "WELLNESS_SUITE")
    assert data["room_state"] in ("OPEN", "RESTRICTED", "CLOSED")
    assert isinstance(data["max_occupancy"], int) and data["max_occupancy"] > 0
    assert isinstance(data["open_deficiency_count"], int)
    assert data["open_deficiency_count"] >= 0


def assert_facility_asset(data: dict):
    assert_versioned_record(data)
    assert data["asset_type"] in ("AED", "CARDIO", "STRENGTH")
    assert data["status"] in ("IN_SERVICE", "MAINTENANCE_DUE", "OUT_OF_SERVICE")
    assert data["readiness_status"] in ("READY", "PADS_EXPIRING", "NOT_READY", "NOT_APPLICABLE")
    assert 1 <= data["service_interval_days"] <= 365
    assert isinstance(data["out_of_service_days_current_period"], int)
    if data["asset_type"] != "AED":
        assert data["readiness_status"] == "NOT_APPLICABLE", (
            "readiness_status is always NOT_APPLICABLE on a non-defibrillator asset"
        )
        assert data["pad_expiry_on"] is None and data["battery_expiry_on"] is None


def assert_program_offering(data: dict):
    assert_versioned_record(data)
    assert data["program_type"] in ("GROUP_EXERCISE", "PERSONAL_TRAINING", "WELLNESS_CHALLENGE")
    assert data["status"] in ("DRAFT", "ACTIVE", "PAUSED", "CLOSED")
    assert data["participation_target"] > 0
    assert data["max_participants_per_session"] > 0
    assert data["required_credential_type"] in (
        "CPR_AED", "FIRST_AID", "GROUP_EX_CERT", "PT_CERT",
    )
    assert isinstance(data["eligible_member_classes"], list)
    for member_class in data["eligible_member_classes"]:
        assert member_class in ("EMPLOYEE", "DEPENDENT", "RETIREE")
    assert isinstance(data["counted_participation_total"], int)
    assert isinstance(data["coverage_gap_count"], int)


def assert_program_session(data: dict):
    assert_versioned_record(data)
    assert data["status"] in (
        "SCHEDULED", "STAFFED", "STAFFING_AT_RISK", "IN_PROGRESS", "COMPLETED",
        "CANCELLED_NO_COVER", "CANCELLED_CLIENT", "CANCELLED_FACILITY",
    )
    assert isinstance(data["scheduled_minutes"], int) and data["scheduled_minutes"] > 0
    assert isinstance(data["forecast_attendance"], int) and data["forecast_attendance"] >= 0
    assert isinstance(data["actual_attendance"], int) and data["actual_attendance"] >= 0
    assert data["cancel_reason"] in (None, "NO_COVER", "CLIENT_REQUEST", "FACILITY")
    assert isinstance(data["direct_supply_cost_cents"], int)
    assert data["direct_supply_cost_cents"] >= 0


def assert_staff_assignment(data: dict):
    assert_versioned_record(data)
    assert data["role_on_session"] in ("LEAD", "SUPPORT")
    assert data["status"] in (
        "ASSIGNED", "CONFIRMED", "VACANT_NEEDS_COVER", "RELEASED", "COMPLETED",
    )
    assert isinstance(data["paid_minutes"], int) and data["paid_minutes"] > 0
    assert isinstance(data["labor_cost_cents"], int) and data["labor_cost_cents"] >= 0


def assert_member(data: dict):
    assert_versioned_record(data)
    assert data["member_class"] in ("EMPLOYEE", "DEPENDENT", "RETIREE")
    assert data["eligibility_status"] in (
        "PENDING_VERIFICATION", "ELIGIBLE", "LAPSED", "TERMINATED",
    )
    assert data["access_status"] in ("NO_BADGE", "ACTIVE", "REVOKED")
    assert isinstance(data["health_data_consent"], bool)
    assert isinstance(data["incentive_points_balance"], int)
    assert data["incentive_points_balance"] >= 0
    if data["member_class"] == "EMPLOYEE":
        assert data["employee_number"] is not None, "an EMPLOYEE must carry employee_number"
        assert data["sponsor_member_id"] is None
    else:
        assert data["employee_number"] is None
    if data["member_class"] == "DEPENDENT":
        assert data["sponsor_member_id"] is not None


def assert_liability_waiver(data: dict):
    assert_versioned_record(data)
    assert data["status"] in ("SIGNED", "EXPIRED", "SUPERSEDED", "REVOKED")
    assert isinstance(data["waiver_version_code"], str) and data["waiver_version_code"]
    assert data["acknowledged_health_disclosure"] is True


def assert_participation_record(data: dict):
    assert_append_only_record(data)
    assert data["status"] in ("COUNTED", "VOIDED")
    assert data["recorded_by_role"] in ("MEMBER", "FITNESS_STAFF")
    assert isinstance(data["points_awarded"], int) and data["points_awarded"] >= 0
    assert isinstance(data["points_capped"], bool)
    assert isinstance(data["streak_bonus_applied"], bool)
    assert is_iso8601_timestamp(data["check_in_utc"])


def assert_incident_report(data: dict):
    assert_versioned_record(data)
    assert data["severity"] in ("MINOR", "MODERATE", "SERIOUS")
    assert data["cause_category"] in ("EQUIPMENT", "MEDICAL", "SLIP_FALL", "OTHER")
    assert data["status"] in (
        "REPORTED", "UNDER_REVIEW", "CLAIM_FILED", "CLOSED_NO_CLAIM", "CLAIM_CLOSED",
    )
    assert isinstance(data["aed_deployed"], bool)
    assert isinstance(data["return_count"], int) and data["return_count"] >= 0
    assert isinstance(data["narrative"], str) and data["narrative"]


def assert_monthly_invoice(data: dict):
    assert_versioned_record(data)
    assert data["fee_structure_snapshot"] in ("MANAGEMENT_FEE", "COST_PLUS")
    assert data["status"] in ("DRAFT", "ISSUED", "DISPUTED", "PAID", "SUPERSEDED")
    for money in (
        "labor_subtotal_cents",
        "program_direct_cost_cents",
        "admin_markup_cents",
        "volume_credit_cents",
        "downtime_credit_cents",
        "coverage_penalty_cents",
        "gross_amount_cents",
        "net_amount_cents",
    ):
        assert isinstance(data[money], int), (
            f"{money} must be an integer number of cents, got {data[money]!r}"
        )
    assert isinstance(data["nte_capped"], bool)
    assert isinstance(data["rebill_count"], int)


# --------------------------------------------------------------------------
# Conserved-counter invariants (PRD §2.9)
# --------------------------------------------------------------------------
def assert_committed_minutes_invariant(staff: dict, assignments: list):
    """committed_minutes_current_period equals the sum of paid_minutes over the
    person's assignments in ASSIGNED, CONFIRMED or COMPLETED status."""
    expected = sum(
        a["paid_minutes"]
        for a in assignments
        if a["staff_member_id"] == staff["id"]
        and a["status"] in ("ASSIGNED", "CONFIRMED", "COMPLETED")
    )
    assert staff["committed_minutes_current_period"] == expected, (
        f"committed_minutes_current_period is {staff['committed_minutes_current_period']}, "
        f"expected {expected} from the person's live assignments"
    )


def assert_incentive_points_invariant(member: dict, records: list):
    """incentive_points_balance equals the sum of points_awarded over the
    member's participation records still in COUNTED status."""
    expected = sum(
        r["points_awarded"]
        for r in records
        if r["member_id"] == member["id"] and r["status"] == "COUNTED"
    )
    assert member["incentive_points_balance"] == expected, (
        f"incentive_points_balance is {member['incentive_points_balance']}, "
        f"expected {expected} from surviving COUNTED records"
    )


def assert_ytd_billed_invariant(contract: dict, invoices: list):
    """ytd_billed_cents equals the sum of net_amount_cents over the contract's
    invoices in ISSUED or PAID status."""
    expected = sum(
        i["net_amount_cents"]
        for i in invoices
        if i["contract_id"] == contract["id"] and i["status"] in ("ISSUED", "PAID")
    )
    assert contract["ytd_billed_cents"] == expected, (
        f"ytd_billed_cents is {contract['ytd_billed_cents']}, expected {expected}"
    )


def assert_eligible_member_count_invariant(contract: dict, members: list):
    """eligible_member_count equals the number of the contract's members whose
    eligibility_status is ELIGIBLE."""
    expected = sum(
        1
        for m in members
        if m["contract_id"] == contract["id"] and m["eligibility_status"] == "ELIGIBLE"
    )
    assert contract["eligible_member_count"] == expected, (
        f"eligible_member_count is {contract['eligible_member_count']}, expected {expected}"
    )
