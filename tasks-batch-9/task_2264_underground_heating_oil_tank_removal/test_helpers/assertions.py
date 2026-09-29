"""Entity shape assertions and domain invariant checkers.

Every entity assertion first checks the four system-managed properties, because
the PRD states that no resource in this system omits ``updated_at`` or
``version``, then checks the fields that entity always carries and the declared
membership of every enum-valued field present.

The invariant checkers cover the properties the PRD states hold globally: the
waterfall conservation identity, blocker-list ordering and deduplication, the
per-line rounding of a change-order cost, and the half-up rounding convention.
"""
from datetime import datetime
from typing import List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    ADMIN_FEE_RATE,
    BASE_MOBILIZATION_CENTS,
    BLOCKER_CODES,
    CAP_TIER_1_CENTS,
    CAP_TIER_1_MAX_CENTS,
    CAP_TIER_2_CENTS,
    CAP_TIER_2_MAX_CENTS,
    CAP_TIER_3_CENTS,
    CUBIC_FEET_PER_CUBIC_YARD,
    DISPOSAL_MULTIPLIERS,
    GRID_CELL_SQFT,
    INCHES_PER_FOOT,
    SOIL_DENSITY_TONS_PER_CUBIC_YARD,
    STATE_DEDUCTIBLE_CENTS,
)

# --------------------------------------------------------------------------- #
# Declared enum memberships
# --------------------------------------------------------------------------- #
STATE_CODES = ["NJ", "NY", "CT"]
TANK_PROJECT_STATUSES = [
    "INTAKE", "SURVEYED", "DISCLOSED", "PERMITTED", "DECOMMISSIONING",
    "SAMPLING", "ASSESSED", "REMEDIATION_ACTIVE", "CLEARED", "CLOSED_NFA",
    "CLOSED_SETTLED", "VOID",
]
CONTAMINATION_CLASSES = ["UNCLASSIFIED", "CLEAN", "ELEVATED", "GROSS"]
SURVEY_METHODS = ["GPR", "MAGNETOMETER", "PROBE_ROD"]
TANK_MATERIALS = ["STEEL", "FIBERGLASS"]
DECOMMISSION_METHODS = ["REMOVAL", "ABANDONMENT_IN_PLACE"]
REMEDIATION_VOLUME_BASES = ["PROVISIONAL_GRID", "FINAL_SURVEYED"]
DISCLOSURE_KINDS = ["SWEEP_FINDINGS", "CONTAMINATION_FINDINGS"]
DISCLOSURE_STATUSES = ["PENDING", "ACKNOWLEDGED", "DECLINED", "EXPIRED"]
DISCLOSURE_RESPONSES = ["ACKNOWLEDGED", "DECLINED"]
RESPONSE_CHANNELS = ["EMAIL", "PORTAL", "WET_SIGNATURE"]
PERMIT_TYPES = ["MUNICIPAL_DECOMMISSION", "FIRE_MARSHAL_NOTIFICATION"]
PERMIT_STATUSES = ["SUBMITTED", "ISSUED", "DENIED", "REVOKED", "EXPIRED"]
CERT_LEVELS = ["TANK_TECH_I", "TANK_TECH_II", "LSP_SUPERVISED"]
WORK_ORDER_FIELD_STATUSES = [
    "SCHEDULED", "MOBILIZED", "IN_PROGRESS", "FIELD_COMPLETE", "ABORTED",
]
WORK_ORDER_BILLING_STATUSES = [
    "UNBILLED", "BILLABLE", "INVOICED", "RECONCILED", "WRITTEN_OFF",
]
FIELD_EVENTS = ["MOBILIZE", "START", "COMPLETE", "ABORT"]
BILLING_EVENTS = ["INVOICE", "RECONCILE", "WRITE_OFF"]
SAMPLE_POINTS = [
    "TANK_BOTTOM", "NORTH_SIDEWALL", "SOUTH_SIDEWALL", "STOCKPILE",
    "CONFIRMATION_FLOOR",
]
SAMPLE_STATUSES = [
    "COLLECTED", "IN_TRANSIT", "AT_LAB", "RESULTED", "INVALIDATED", "VOIDED",
]
CUSTODY_EVENTS = ["DISPATCH", "RECEIVE", "VOID"]
QC_FLAGS = ["NONE", "HOLDING_TIME_EXCEEDED", "RESULT_RETRACTED"]
DISPOSAL_CLASSES = ["NON_HAZARDOUS", "HAZARDOUS"]
CHANGE_ORDER_STATUSES = [
    "DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "SUPERSEDED",
]
CLAIM_VARIANTS = ["PRELIMINARY_ESTIMATE", "FINAL_SETTLEMENT"]
CLAIM_STATUSES = [
    "DRAFT", "SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED", "APPROVED",
    "DENIED", "PAID", "WITHDRAWN",
]
NFA_LETTER_STATUSES = ["DRAFT", "ISSUED", "RESCINDED"]
NOTIFICATION_KINDS = ["FIRST_PARTY", "THIRD_PARTY_LIABILITY"]
NOTIFICATION_STATUSES = ["OPEN", "RESERVED", "THIRD_PARTY_REVIEW", "CLOSED"]

#: Work-order field states that still occupy a crew's calendar.
CALENDAR_OCCUPYING_FIELD_STATUSES = ["SCHEDULED", "MOBILIZED", "IN_PROGRESS"]
#: Sample states that keep a confirmation round open.
ROUND_OPEN_SAMPLE_STATUSES = ["COLLECTED", "IN_TRANSIT", "AT_LAB"]
#: Notification states the waterfall rewrites.
WATERFALL_LIVE_NOTIFICATION_STATUSES = ["OPEN", "RESERVED", "THIRD_PARTY_REVIEW"]
#: Change-order states that keep OPEN_CHANGE_ORDER on the blocker list.
OPEN_CHANGE_ORDER_STATUSES = ["DRAFT", "SUBMITTED"]


# --------------------------------------------------------------------------- #
# Shared field checks
# --------------------------------------------------------------------------- #
def _assert_system_fields(data: dict, label: str) -> None:
    """The four properties every resource in this system carries."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{label}.id must be a server-minted UUID, got {data.get('id')!r}"
    )
    assert "_" not in str(data.get("id", "")), (
        f"{label}.id carries no type prefix, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 UTC timestamp, got "
        f"{data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be an ISO 8601 UTC timestamp, got "
        f"{data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version is an integer starting at 1, got {data.get('version')!r}"
    )


def _assert_enum(data: dict, field: str, members: List[str], label: str) -> None:
    """Check a present enum-valued field against its declared members."""
    if data.get(field) is not None:
        assert data[field] in members, (
            f"{label}.{field} must be one of {members}, got {data[field]!r}"
        )


def _assert_optional_timestamp(data: dict, field: str, label: str) -> None:
    value = data.get(field)
    if value is not None:
        assert is_iso8601_timestamp(value), (
            f"{label}.{field} must be an ISO 8601 UTC timestamp when set, got "
            f"{value!r}"
        )


def _assert_integer_cents(data: dict, field: str, label: str) -> None:
    """Money is carried exclusively as integer cents."""
    value = data.get(field)
    if value is not None:
        assert isinstance(value, int) and not isinstance(value, bool), (
            f"{label}.{field} is money and must be an integer number of cents, got "
            f"{value!r}"
        )


# --------------------------------------------------------------------------- #
# Entity assertions
# --------------------------------------------------------------------------- #
def assert_property(data: dict, label: str = "Property") -> dict:
    _assert_system_fields(data, label)
    for field in (
        "street_address", "state_code", "county_code", "homeowner_name",
        "homeowner_email", "insurance_carrier_code",
    ):
        assert isinstance(data.get(field), str) and data[field], (
            f"{label}.{field} must be a non-empty string, got {data.get(field)!r}"
        )
    _assert_enum(data, "state_code", STATE_CODES, label)
    for field in (
        "first_party_coverage_limit_cents", "third_party_sublimit_cents",
        "trust_fund_deductible_cents",
    ):
        _assert_integer_cents(data, field, label)
        assert data.get(field, 0) >= 0, (
            f"{label}.{field} may not be negative, got {data.get(field)!r}"
        )
    assert isinstance(data.get("open_project_count"), int), (
        f"{label}.open_project_count must be an integer, got "
        f"{data.get('open_project_count')!r}"
    )
    assert data["open_project_count"] >= 0, (
        f"{label}.open_project_count may not go below zero, got "
        f"{data['open_project_count']}"
    )
    assert data["trust_fund_deductible_cents"] == STATE_DEDUCTIBLE_CENTS[
        data["state_code"]
    ], (
        f"{label}.trust_fund_deductible_cents must come from the statutory schedule "
        f"for {data['state_code']}: expected "
        f"{STATE_DEDUCTIBLE_CENTS[data['state_code']]}, got "
        f"{data['trust_fund_deductible_cents']}"
    )
    return data


def assert_tank_project(data: dict, label: str = "TankProject") -> dict:
    _assert_system_fields(data, label)
    assert is_valid_uuid(data.get("property_id", "")), (
        f"{label}.property_id must reference a property row, got "
        f"{data.get('property_id')!r}"
    )
    _assert_enum(data, "status", TANK_PROJECT_STATUSES, label)
    _assert_enum(data, "contamination_class", CONTAMINATION_CLASSES, label)
    _assert_enum(data, "survey_method", SURVEY_METHODS, label)
    _assert_enum(data, "tank_material", TANK_MATERIALS, label)
    _assert_enum(data, "recommended_method", DECOMMISSION_METHODS, label)
    _assert_enum(data, "decommission_method", DECOMMISSION_METHODS, label)
    _assert_enum(data, "remediation_volume_basis", REMEDIATION_VOLUME_BASES, label)
    _assert_optional_timestamp(data, "survey_completed_at", label)
    _assert_integer_cents(data, "remediation_cost_cents", label)

    for field in ("baseline_scope_cubic_yards", "excavation_limit_cubic_yards"):
        assert isinstance(data.get(field), (int, float)) and data[field] > 0, (
            f"{label}.{field} must be strictly greater than zero, got "
            f"{data.get(field)!r}"
        )
    assert isinstance(data.get("sampling_round"), int), (
        f"{label}.sampling_round must be an integer, got "
        f"{data.get('sampling_round')!r}"
    )
    for field in ("remediation_started", "contamination_disclosure_required"):
        assert isinstance(data.get(field), bool), (
            f"{label}.{field} is a latch and must be a boolean, got "
            f"{data.get(field)!r}"
        )
    assert_blocker_list(data.get("nfa_blockers"), f"{label}.nfa_blockers")

    if data.get("method_score") is not None:
        assert 0.0 <= data["method_score"] <= 100.0, (
            f"{label}.method_score is clamped into the closed range 0.00 to 100.00, "
            f"got {data['method_score']}"
        )
        assert round(data["method_score"], 2) == data["method_score"], (
            f"{label}.method_score is rounded to two decimal places, got "
            f"{data['method_score']}"
        )
    if data.get("remediation_volume_cubic_yards") is not None:
        volume = data["remediation_volume_cubic_yards"]
        assert round(volume, 2) == volume, (
            f"{label}.remediation_volume_cubic_yards is rounded to two decimal "
            f"places, got {volume}"
        )
    return data


def assert_tank_project_summary(data: dict, label: str = "summary") -> dict:
    """The computed posture snapshot carries no system fields of its own."""
    for field in (
        "status", "contamination_class", "approved_scope_cubic_yards",
        "remediation_cost_cents", "nfa_blockers", "version",
        "open_change_order_count", "current_round_sample_count",
    ):
        assert field in data, f"{label} must report {field}"
    _assert_enum(data, "status", TANK_PROJECT_STATUSES, label)
    _assert_enum(data, "contamination_class", CONTAMINATION_CLASSES, label)
    _assert_enum(data, "remediation_volume_basis", REMEDIATION_VOLUME_BASES, label)
    _assert_integer_cents(data, "remediation_cost_cents", label)
    assert_blocker_list(data.get("nfa_blockers"), f"{label}.nfa_blockers")
    for field in ("version", "open_change_order_count", "current_round_sample_count"):
        assert isinstance(data.get(field), int) and data[field] >= 0, (
            f"{label}.{field} must be a non-negative integer, got "
            f"{data.get(field)!r}"
        )
    return data


def assert_homeowner_disclosure(data: dict, label: str = "HomeownerDisclosure") -> dict:
    _assert_system_fields(data, label)
    assert is_valid_uuid(data.get("tank_project_id", "")), (
        f"{label}.tank_project_id must reference a project row, got "
        f"{data.get('tank_project_id')!r}"
    )
    _assert_enum(data, "disclosure_kind", DISCLOSURE_KINDS, label)
    _assert_enum(data, "status", DISCLOSURE_STATUSES, label)
    _assert_enum(data, "response", DISCLOSURE_RESPONSES, label)
    _assert_enum(data, "response_channel", RESPONSE_CHANNELS, label)
    assert is_iso8601_timestamp(data.get("sent_at", "")), (
        f"{label}.sent_at is stamped from the logical clock, got "
        f"{data.get('sent_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("expires_at", "")), (
        f"{label}.expires_at is derived from sent_at, got "
        f"{data.get('expires_at')!r}"
    )
    _assert_optional_timestamp(data, "responded_at", label)
    return data


def assert_permit(data: dict, label: str = "Permit") -> dict:
    _assert_system_fields(data, label)
    assert is_valid_uuid(data.get("tank_project_id", "")), (
        f"{label}.tank_project_id must reference a project row, got "
        f"{data.get('tank_project_id')!r}"
    )
    _assert_enum(data, "permit_type", PERMIT_TYPES, label)
    _assert_enum(data, "status", PERMIT_STATUSES, label)
    assert is_iso8601_timestamp(data.get("submitted_at", "")), (
        f"{label}.submitted_at is stamped from the logical clock, got "
        f"{data.get('submitted_at')!r}"
    )
    for field in ("issued_at", "expires_at", "notice_effective_at"):
        _assert_optional_timestamp(data, field, label)
    return data


def assert_crew(data: dict, label: str = "Crew") -> dict:
    _assert_system_fields(data, label)
    assert isinstance(data.get("crew_name"), str) and data["crew_name"], (
        f"{label}.crew_name must be a non-empty string, got "
        f"{data.get('crew_name')!r}"
    )
    _assert_enum(data, "cert_level", CERT_LEVELS, label)
    buffer_minutes = data.get("mobilization_buffer_minutes")
    assert isinstance(buffer_minutes, int) and buffer_minutes >= 0, (
        f"{label}.mobilization_buffer_minutes may not be negative, got "
        f"{buffer_minutes!r}"
    )
    return data


def assert_work_order(data: dict, label: str = "DecommissionWorkOrder") -> dict:
    _assert_system_fields(data, label)
    for field in ("tank_project_id", "crew_id"):
        assert is_valid_uuid(data.get(field, "")), (
            f"{label}.{field} must reference a real row, got {data.get(field)!r}"
        )
    _assert_enum(data, "method", DECOMMISSION_METHODS, label)
    _assert_enum(data, "field_status", WORK_ORDER_FIELD_STATUSES, label)
    _assert_enum(data, "billing_status", WORK_ORDER_BILLING_STATUSES, label)
    for field in ("scheduled_start_at", "scheduled_end_at"):
        assert is_iso8601_timestamp(data.get(field, "")), (
            f"{label}.{field} must be an ISO 8601 UTC timestamp, got "
            f"{data.get(field)!r}"
        )
    assert data["scheduled_start_at"] < data["scheduled_end_at"], (
        f"{label}.scheduled_end_at must be strictly later than scheduled_start_at, "
        f"got {data['scheduled_start_at']} .. {data['scheduled_end_at']}"
    )
    return data


def assert_laboratory(data: dict, label: str = "Laboratory") -> dict:
    _assert_system_fields(data, label)
    assert isinstance(data.get("lab_name"), str) and data["lab_name"], (
        f"{label}.lab_name must be a non-empty string, got {data.get('lab_name')!r}"
    )
    assert isinstance(data.get("accredited"), bool), (
        f"{label}.accredited must be a boolean, got {data.get('accredited')!r}"
    )
    for field in ("committed_turnaround_hours", "holding_time_hours"):
        assert isinstance(data.get(field), int) and data[field] > 0, (
            f"{label}.{field} must be strictly greater than zero, got "
            f"{data.get(field)!r}"
        )
    assert (
        isinstance(data.get("max_concurrent_analyses"), int)
        and data["max_concurrent_analyses"] >= 1
    ), (
        f"{label}.max_concurrent_analyses must be at least 1, got "
        f"{data.get('max_concurrent_analyses')!r}"
    )
    return data


def assert_soil_sample(data: dict, label: str = "SoilSample") -> dict:
    _assert_system_fields(data, label)
    for field in ("tank_project_id", "work_order_id", "laboratory_id"):
        assert is_valid_uuid(data.get(field, "")), (
            f"{label}.{field} must reference a real row, got {data.get(field)!r}"
        )
    _assert_enum(data, "sample_point", SAMPLE_POINTS, label)
    _assert_enum(data, "status", SAMPLE_STATUSES, label)
    _assert_enum(data, "qc_flag", QC_FLAGS, label)
    assert isinstance(data.get("depth_inches"), int) and data["depth_inches"] > 0, (
        f"{label}.depth_inches must be strictly greater than zero, got "
        f"{data.get('depth_inches')!r}"
    )
    assert isinstance(data.get("sampling_round"), int), (
        f"{label}.sampling_round must be an integer, got "
        f"{data.get('sampling_round')!r}"
    )
    assert is_iso8601_timestamp(data.get("collected_at", "")), (
        f"{label}.collected_at is stamped from the logical clock, got "
        f"{data.get('collected_at')!r}"
    )
    assert isinstance(data.get("collected_by_user_id"), str), (
        f"{label}.collected_by_user_id is set from X-User-ID, got "
        f"{data.get('collected_by_user_id')!r}"
    )
    for field in ("dispatched_at", "received_at", "reported_at"):
        _assert_optional_timestamp(data, field, label)
    for field in ("tph_mg_kg", "benzene_mg_kg"):
        if data.get(field) is not None:
            assert data[field] >= 0, (
                f"{label}.{field} may not be negative, got {data[field]}"
            )
    for field in ("holding_time_elapsed_hours", "turnaround_hours"):
        if data.get(field) is not None:
            assert round(data[field], 2) == data[field], (
                f"{label}.{field} is rounded to two decimal places before it is "
                f"compared to its threshold, got {data[field]}"
            )
    if data.get("turnaround_breach") is not None:
        assert isinstance(data["turnaround_breach"], bool), (
            f"{label}.turnaround_breach must be a boolean, got "
            f"{data['turnaround_breach']!r}"
        )
    return data


def assert_change_order(data: dict, label: str = "RemediationChangeOrder") -> dict:
    _assert_system_fields(data, label)
    assert is_valid_uuid(data.get("tank_project_id", "")), (
        f"{label}.tank_project_id must reference a project row, got "
        f"{data.get('tank_project_id')!r}"
    )
    _assert_enum(data, "disposal_class", DISPOSAL_CLASSES, label)
    _assert_enum(data, "status", CHANGE_ORDER_STATUSES, label)
    assert (
        isinstance(data.get("additional_cubic_yards"), (int, float))
        and data["additional_cubic_yards"] > 0
    ), (
        f"{label}.additional_cubic_yards must be strictly greater than zero, got "
        f"{data.get('additional_cubic_yards')!r}"
    )
    _assert_integer_cents(data, "unit_rate_cents", label)
    assert data["unit_rate_cents"] > 0, (
        f"{label}.unit_rate_cents must be strictly greater than zero, got "
        f"{data['unit_rate_cents']}"
    )
    _assert_integer_cents(data, "line_amount_cents", label)
    assert isinstance(data.get("requested_by_user_id"), str), (
        f"{label}.requested_by_user_id is set from X-User-ID, got "
        f"{data.get('requested_by_user_id')!r}"
    )
    _assert_optional_timestamp(data, "decided_at", label)
    return data


def assert_trust_fund_claim(data: dict, label: str = "TrustFundClaim") -> dict:
    _assert_system_fields(data, label)
    assert is_valid_uuid(data.get("tank_project_id", "")), (
        f"{label}.tank_project_id must reference a project row, got "
        f"{data.get('tank_project_id')!r}"
    )
    _assert_enum(data, "variant", CLAIM_VARIANTS, label)
    _assert_enum(data, "status", CLAIM_STATUSES, label)
    _assert_enum(data, "state_code", STATE_CODES, label)
    for field in (
        "claimed_costs_cents", "deductible_cents", "cap_cents", "admin_fee_cents",
        "eligible_amount_cents", "reimbursed_amount_cents",
        "unreimbursed_balance_cents",
    ):
        _assert_integer_cents(data, field, label)
    assert data["claimed_costs_cents"] > 0, (
        f"{label}.claimed_costs_cents must be strictly greater than zero, got "
        f"{data['claimed_costs_cents']}"
    )
    assert data["eligible_amount_cents"] >= 0, (
        f"{label}.eligible_amount_cents is floored at zero, got "
        f"{data['eligible_amount_cents']}"
    )
    assert isinstance(data.get("info_request_count"), int), (
        f"{label}.info_request_count must be an integer, got "
        f"{data.get('info_request_count')!r}"
    )
    assert isinstance(data.get("eligibility_findings"), list), (
        f"{label}.eligibility_findings must be a list, got "
        f"{data.get('eligibility_findings')!r}"
    )
    assert data["eligibility_findings"] == sorted(data["eligibility_findings"]), (
        f"{label}.eligibility_findings is kept sorted ascending, got "
        f"{data['eligibility_findings']}"
    )
    for field in ("submitted_at", "decided_at", "paid_at"):
        _assert_optional_timestamp(data, field, label)
    assert data["deductible_cents"] == STATE_DEDUCTIBLE_CENTS[data["state_code"]], (
        f"{label}.deductible_cents comes from the statutory schedule for the "
        f"snapshotted {data['state_code']}: expected "
        f"{STATE_DEDUCTIBLE_CENTS[data['state_code']]}, got "
        f"{data['deductible_cents']}"
    )
    assert (
        data["unreimbursed_balance_cents"]
        == data["eligible_amount_cents"] - data["reimbursed_amount_cents"]
    ), (
        f"{label}.unreimbursed_balance_cents is eligible less reimbursed: "
        f"{data['eligible_amount_cents']} - {data['reimbursed_amount_cents']} "
        f"!= {data['unreimbursed_balance_cents']}"
    )
    return data


def assert_nfa_letter(data: dict, label: str = "NFALetter") -> dict:
    _assert_system_fields(data, label)
    assert is_valid_uuid(data.get("tank_project_id", "")), (
        f"{label}.tank_project_id must reference a project row, got "
        f"{data.get('tank_project_id')!r}"
    )
    _assert_enum(data, "status", NFA_LETTER_STATUSES, label)
    assert isinstance(data.get("drafted_by_user_id"), str), (
        f"{label}.drafted_by_user_id is set from X-User-ID, got "
        f"{data.get('drafted_by_user_id')!r}"
    )
    for field in ("issued_at", "rescinded_at"):
        _assert_optional_timestamp(data, field, label)
    if data.get("issued_by_user_id") is not None:
        assert data["issued_by_user_id"] != data["drafted_by_user_id"], (
            f"{label} must be signed by a principal different from its drafter, "
            f"but both read {data['drafted_by_user_id']!r}"
        )
    return data


def assert_insurance_notification(
    data: dict, label: str = "InsuranceNotification"
) -> dict:
    _assert_system_fields(data, label)
    assert is_valid_uuid(data.get("tank_project_id", "")), (
        f"{label}.tank_project_id must reference a project row, got "
        f"{data.get('tank_project_id')!r}"
    )
    _assert_enum(data, "notification_kind", NOTIFICATION_KINDS, label)
    _assert_enum(data, "status", NOTIFICATION_STATUSES, label)
    assert isinstance(data.get("carrier_code"), str) and data["carrier_code"], (
        f"{label}.carrier_code is snapshotted from the property, got "
        f"{data.get('carrier_code')!r}"
    )
    assert is_iso8601_timestamp(data.get("notified_at", "")), (
        f"{label}.notified_at is stamped from the logical clock, got "
        f"{data.get('notified_at')!r}"
    )
    for field in (
        "first_party_allocated_cents", "third_party_allocated_cents",
        "homeowner_out_of_pocket_cents", "reserve_amount_cents",
    ):
        _assert_integer_cents(data, field, label)
    assert (
        data["reserve_amount_cents"]
        == data["first_party_allocated_cents"] + data["third_party_allocated_cents"]
    ), (
        f"{label}.reserve_amount_cents is the first-party plus third-party share: "
        f"{data['first_party_allocated_cents']} + "
        f"{data['third_party_allocated_cents']} != {data['reserve_amount_cents']}"
    )
    return data


# --------------------------------------------------------------------------- #
# Domain invariant checkers
# --------------------------------------------------------------------------- #
def assert_blocker_list(blockers, label: str = "nfa_blockers") -> None:
    """The blocker list is deduplicated, sorted ascending and drawn from seven codes."""
    assert isinstance(blockers, list), (
        f"{label} must be a list, got {blockers!r}"
    )
    for code in blockers:
        assert code in BLOCKER_CODES, (
            f"{label} may only carry the seven declared codes {BLOCKER_CODES}, got "
            f"{code!r}"
        )
    assert len(blockers) == len(set(blockers)), (
        f"{label} is deduplicated, got {blockers}"
    )
    assert blockers == sorted(blockers), (
        f"{label} is sorted lexicographically ascending — never by creation time or "
        f"identifier — got {blockers}"
    )


def assert_waterfall_conserved(notification: dict, remediation_cost_cents: int) -> None:
    """The three allocation parts sum exactly to the project's remediation cost."""
    total = (
        notification["first_party_allocated_cents"]
        + notification["third_party_allocated_cents"]
        + notification["homeowner_out_of_pocket_cents"]
    )
    assert total == remediation_cost_cents, (
        "the waterfall performs no rounding, so first-party plus third-party plus "
        f"homeowner must equal the project's remediation_cost_cents exactly: "
        f"{notification['first_party_allocated_cents']} + "
        f"{notification['third_party_allocated_cents']} + "
        f"{notification['homeowner_out_of_pocket_cents']} = {total}, expected "
        f"{remediation_cost_cents}"
    )


def assert_notification_status_derived(notification: dict) -> None:
    """Status re-derives from the freshly written figures with no memory."""
    if notification["status"] == "CLOSED":
        return
    if notification["third_party_allocated_cents"] > 0:
        expected = "THIRD_PARTY_REVIEW"
    elif notification["reserve_amount_cents"] > 0:
        expected = "RESERVED"
    else:
        expected = "OPEN"
    assert notification["status"] == expected, (
        "a notification re-derives its status from its own allocation: with "
        f"third_party_allocated_cents {notification['third_party_allocated_cents']} "
        f"and reserve_amount_cents {notification['reserve_amount_cents']} the status "
        f"must be {expected}, got {notification['status']}"
    )


def round_half_up(value: float, places: int = 0):
    """Half-up rounding, which is the only rounding mode this system uses."""
    from decimal import Decimal, ROUND_HALF_UP

    quantum = Decimal(1).scaleb(-places)
    rounded = Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)
    return int(rounded) if places == 0 else float(rounded)


def expected_line_amount_cents(
    additional_cubic_yards: float, unit_rate_cents: int, disposal_class: str
) -> int:
    """One change-order line, rounded half up to whole cents before any summation."""
    multiplier = DISPOSAL_MULTIPLIERS[disposal_class]
    return round_half_up(additional_cubic_yards * unit_rate_cents * multiplier, 0)


def expected_remediation_cost_cents(lines: List[int], remediation_started: bool) -> int:
    """Mobilization plus the already-rounded integer line total, once started."""
    if not remediation_started:
        return 0
    return BASE_MOBILIZATION_CENTS + sum(lines)


def expected_provisional_grid_volume(
    impacted_count: int, max_depth_inches: Optional[int]
) -> float:
    """The PROVISIONAL_GRID variant over the impacted samples of the current round."""
    if impacted_count == 0 or max_depth_inches is None:
        return 0.00
    cubic_feet = (
        impacted_count * GRID_CELL_SQFT * (max_depth_inches / INCHES_PER_FOOT)
    )
    return round_half_up(cubic_feet / CUBIC_FEET_PER_CUBIC_YARD, 2)


def expected_final_surveyed_volume(hauled_tons: float) -> float:
    """The FINAL_SURVEYED variant, which reads only the reported tonnage."""
    return round_half_up(hauled_tons / SOIL_DENSITY_TONS_PER_CUBIC_YARD, 2)


def expected_cap_cents(gross_cents: int) -> int:
    """The reimbursement ceiling the gross figure selects across three tiers."""
    if gross_cents <= CAP_TIER_1_MAX_CENTS:
        return CAP_TIER_1_CENTS
    if gross_cents <= CAP_TIER_2_MAX_CENTS:
        return CAP_TIER_2_CENTS
    return CAP_TIER_3_CENTS


def expected_admin_fee_cents(capped_cents: int) -> int:
    """The administrative rate applied to the capped figure, rounded half up."""
    return round_half_up(capped_cents * ADMIN_FEE_RATE, 0)


def expected_eligible_amount_cents(
    gross_cents: int, state_code: str, variant: str
) -> int:
    """The eight eligibility steps run once, in the order the PRD pins them."""
    deductible = STATE_DEDUCTIBLE_CENTS[state_code]
    cap = expected_cap_cents(gross_cents)
    capped = min(gross_cents, cap)
    admin_fee = expected_admin_fee_cents(capped)
    if variant == "PRELIMINARY_ESTIMATE":
        net = max(0, capped - deductible) - admin_fee
    else:
        net = max(0, min(gross_cents - deductible, cap)) - admin_fee
    return max(0, net)


def expected_method_score(
    depth_inches: int,
    distance_inches: int,
    under_structure: bool,
    capacity_gallons: int,
    material: str,
) -> float:
    """The five factors, each clamped on its own, summed, capped, then rounded."""
    from .constants import (
        CAPACITY_LARGE_GALLONS,
        CAPACITY_LARGE_POINTS,
        CAPACITY_MEDIUM_GALLONS,
        CAPACITY_MEDIUM_POINTS,
        DEPTH_FACTOR_MAX,
        DEPTH_FREE_INCHES,
        DEPTH_POINTS_PER_INCH,
        FOUNDATION_CONCERN_INCHES,
        METHOD_SCORE_MAX,
        PROXIMITY_FACTOR_MAX,
        PROXIMITY_POINTS_PER_INCH,
        STEEL_MATERIAL_POINTS,
        UNDER_STRUCTURE_POINTS,
    )

    depth_factor = min(
        DEPTH_FACTOR_MAX,
        max(0.0, (depth_inches - DEPTH_FREE_INCHES) * DEPTH_POINTS_PER_INCH),
    )
    proximity_factor = min(
        PROXIMITY_FACTOR_MAX,
        max(
            0.0,
            (FOUNDATION_CONCERN_INCHES - distance_inches)
            * PROXIMITY_POINTS_PER_INCH,
        ),
    )
    structure_factor = UNDER_STRUCTURE_POINTS if under_structure else 0.0
    if capacity_gallons >= CAPACITY_LARGE_GALLONS:
        capacity_factor = CAPACITY_LARGE_POINTS
    elif capacity_gallons >= CAPACITY_MEDIUM_GALLONS:
        capacity_factor = CAPACITY_MEDIUM_POINTS
    else:
        capacity_factor = 0.0
    material_factor = STEEL_MATERIAL_POINTS if material == "STEEL" else 0.0

    raw = (
        depth_factor
        + proximity_factor
        + structure_factor
        + capacity_factor
        + material_factor
    )
    return round_half_up(min(METHOD_SCORE_MAX, raw), 2)


def parse_instant(value: str) -> datetime:
    """An ISO 8601 UTC timestamp as a comparable instant.

    Timestamps are ISO 8601 UTC, and the audit fields carry three fractional
    digits, so instants are compared as moments in time rather than as strings.
    """
    assert isinstance(value, str), f"expected an ISO 8601 timestamp, got {value!r}"
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(text)


def assert_same_instant(actual, expected: str, message: str) -> None:
    """The two timestamps name the same moment, whatever precision each carries."""
    assert actual is not None, f"{message} — expected {expected}, got no timestamp"
    assert parse_instant(actual) == parse_instant(expected), (
        f"{message} — expected the instant {expected}, got {actual}"
    )


def assert_envelope_has_only_meta_and_data(body: dict) -> None:
    """A single-resource envelope carries meta, response_type and data alone."""
    assert set(body.keys()) == {"meta", "response_type", "data"}, (
        "the success envelope carries exactly meta, response_type and data, got "
        f"{sorted(body.keys())}"
    )


def assert_request_id_prefixed(meta: dict) -> None:
    assert isinstance(meta.get("api_request_id"), str), (
        f"meta.api_request_id must be a string, got {meta.get('api_request_id')!r}"
    )
    assert meta["api_request_id"].startswith("req_"), (
        "meta.api_request_id is a server-generated identifier that starts with "
        f"req_, got {meta['api_request_id']!r}"
    )
