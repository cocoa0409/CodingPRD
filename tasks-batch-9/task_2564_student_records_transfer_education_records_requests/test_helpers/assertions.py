"""Entity assertions and the domain's conservation-invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

COMPONENT_TYPE_ORDER = ["ACADEMIC", "HEALTH", "DISCIPLINE", "SPECIAL_EDUCATION"]
DIRECTORY_CATEGORY_ORDER = [
    "NAME",
    "ADDRESS",
    "PHONE",
    "PHOTO",
    "HONORS",
    "SPORTS_PARTICIPATION",
]


def assert_common_fields(data: dict, versioned: bool = True):
    """Every resource carries a server-minted UUID `id` and a `created_at`.
    Most also carry `updated_at` and `version`; the immutable state records rule
    and the append-only disclosure log entry carry neither."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID string, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be an ISO 8601 timestamp, got {data.get('created_at')!r}"
    )
    if versioned:
        assert is_iso8601_timestamp(data.get("updated_at", "")), (
            f"updated_at must be an ISO 8601 timestamp, got {data.get('updated_at')!r}"
        )
        assert isinstance(data.get("version"), int) and data["version"] >= 1, (
            f"version must be an integer starting at 1, got {data.get('version')!r}"
        )
    else:
        assert "updated_at" not in data or data.get("updated_at") is None, (
            "this resource must not expose updated_at"
        )
        assert "version" not in data or data.get("version") is None, (
            "this resource must not expose version"
        )


def assert_millisecond_timestamp(value: str, label: str = "timestamp"):
    """Timestamps the server mints carry exactly three fractional digits."""
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert is_iso8601_timestamp(value), f"{label} must be ISO 8601, got {value!r}"
    assert len(value) == 24 and value.endswith("Z") and value[19] == ".", (
        f"{label} must carry three fractional digits and a Z suffix, got {value!r}"
    )


def assert_state_records_rule(data: dict):
    assert_common_fields(data, versioned=False)
    assert data["state_code"] in ("CA", "TX", "NY")
    assert 1 <= data["transfer_response_days"] <= 90
    assert data["discipline_inclusion_mode"] in (
        "ALL_INCIDENTS",
        "SUSPENSIONS_AND_EXPULSIONS",
        "EXPULSIONS_ONLY",
    )
    assert isinstance(data["include_pending_investigations"], bool)
    assert isinstance(data["sped_requires_consent"], bool)
    assert 1 <= data["amendment_hearing_days"] <= 90
    assert 1 <= data["destruction_min_age_years"] <= 30
    assert 1 <= data["directory_optout_grace_days"] <= 120
    assert 0 <= data["notification_wait_days"] <= 30


def assert_district(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert 2 <= len(data["district_code"]) <= 12
    assert data["state_code"] in ("CA", "TX", "NY")
    assert isinstance(data["open_request_count"], int) and data["open_request_count"] >= 0


def assert_inspection_room(data: dict):
    assert_common_fields(data)
    assert 2 <= len(data["room_code"]) <= 12
    assert isinstance(data["site_name"], str) and data["site_name"]
    assert 1 <= data["seats"] <= 40
    assert data["status"] in ("ACTIVE", "CLOSED")


def assert_hearing_officer(data: dict):
    assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["credential"] in (
        "ADMINISTRATIVE_LAW_JUDGE",
        "DISTRICT_DESIGNEE",
        "EXTERNAL_CONTRACTOR",
    )
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_student(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["district_id"])
    assert isinstance(data["first_name"], str) and data["first_name"]
    assert isinstance(data["last_name"], str) and data["last_name"]
    assert 0 <= data["grade_level"] <= 12
    assert isinstance(data["has_iep"], bool)
    assert data["enrollment_status"] in (
        "ENROLLED",
        "WITHDRAWAL_PENDING",
        "WITHDRAWN",
        "TRANSFERRED_OUT",
    )
    assert isinstance(data["is_eligible_student"], bool)
    assert isinstance(data["directory_optout_effective"], bool)
    assert isinstance(data["directory_optout_categories"], list)
    assert_millisecond_timestamp(
        data["directory_optout_deadline_at"], "directory_optout_deadline_at"
    )


def assert_cumulative_file(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["student_id"])
    assert data["assembly_status"] in ("NOT_STARTED", "IN_ASSEMBLY", "COMPLETE")
    assert isinstance(data["required_component_types"], list)
    for ctype in data["required_component_types"]:
        assert ctype in COMPONENT_TYPE_ORDER
    assert_page_custody_identity(data)
    assert isinstance(data["certified_component_count"], int)
    assert isinstance(data["completeness_pct"], (int, float))


def assert_page_custody_identity(data: dict):
    """total_page_count always equals included_page_count plus
    excluded_page_count on every cumulative file after every mutation."""
    total = data["total_page_count"]
    included = data["included_page_count"]
    excluded = data["excluded_page_count"]
    assert total == included + excluded, (
        f"page custody broken: total_page_count {total} != "
        f"included_page_count {included} + excluded_page_count {excluded}"
    )
    assert data["disclosable_page_count"] <= included, (
        "disclosable_page_count may never exceed included_page_count"
    )


def assert_file_component(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["cumulative_file_id"])
    assert data["component_type"] in COMPONENT_TYPE_ORDER
    assert data["status"] in ("PENDING", "COLLECTED", "CERTIFIED", "EXCLUDED")
    assert isinstance(data["is_required"], bool)
    assert 0 <= data["page_count"] <= 5000
    assert 0 <= data["redacted_page_count"] <= data["page_count"]
    assert data["disclosable_page_count"] == data["page_count"] - data["redacted_page_count"], (
        "a component's disclosable_page_count is its page_count minus its redacted_page_count"
    )
    assert isinstance(data["amendment_count"], int)
    assert isinstance(data["statement_of_disagreement_present"], bool)
    if data["status"] == "PENDING":
        assert data["page_count"] == 0, "a PENDING component always holds a page_count of 0"


def assert_components_in_fixed_order(components: list):
    """The components listing returns the four rows in the fixed order
    ACADEMIC, HEALTH, DISCIPLINE, SPECIAL_EDUCATION."""
    actual = [c["component_type"] for c in components]
    assert actual == COMPONENT_TYPE_ORDER, (
        f"components must be listed in the fixed order {COMPONENT_TYPE_ORDER}, got {actual}"
    )


def assert_withdrawal(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["student_id"])
    assert data["status"] in ("CLEARED", "HOLD", "COMPLETED")
    assert data["withdrawal_reason"] in ("TRANSFER_OUT", "MOVED", "HOMESCHOOL", "OTHER")
    assert isinstance(data["active_hold_types"], list)
    assert data["hold_count"] == len(data["active_hold_types"]), (
        "hold_count is the number of entries in active_hold_types"
    )
    assert data["active_hold_types"] == sorted(data["active_hold_types"]), (
        "active_hold_types is kept sorted ascending by enum name"
    )


def assert_discipline_incident(data: dict):
    assert_common_fields(data)
    assert data["action_type"] in ("SUSPENSION", "EXPULSION", "DETENTION", "BEHAVIOR_PLAN")
    assert data["incident_status"] in ("SUSTAINED", "PENDING_INVESTIGATION", "DISMISSED")
    assert 0 <= data["days_removed"] <= 365
    assert isinstance(data["adjudicated_by_court"], bool)
    assert data["transfer_inclusion_state"] in ("NOT_EVALUATED", "INCLUDED", "WITHHELD")


def assert_records_request(data: dict):
    assert_common_fields(data)
    assert data["status"] in (
        "RECEIVED",
        "VALIDATED",
        "ASSEMBLING",
        "READY_FOR_RELEASE",
        "RELEASED",
        "DENIED",
    )
    assert data["packet_status"] in ("NONE", "SNAPSHOT", "VOID")
    assert data["request_priority"] in ("STANDARD", "UNACCOMPANIED_YOUTH")
    assert isinstance(data["authorization_verified"], bool)
    assert isinstance(data["is_overdue"], bool)
    assert isinstance(data["reopen_count"], int) and data["reopen_count"] >= 0
    assert_millisecond_timestamp(data["received_at"], "received_at")
    assert_millisecond_timestamp(data["statutory_due_at"], "statutory_due_at")
    assert data["statutory_due_at"].endswith("T23:59:59.999Z"), (
        "the statutory window resolves to a calendar date at 23:59:59.999Z"
    )


def assert_incident_counts_partition(data: dict, total_incidents: int):
    """included_incident_count and withheld_incident_count always sum to the
    student's incident count."""
    assert data["included_incident_count"] + data["withheld_incident_count"] == total_incidents, (
        f"included {data['included_incident_count']} + withheld "
        f"{data['withheld_incident_count']} must equal {total_incidents}"
    )


def assert_inspection_request(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("SUBMITTED", "SCHEDULED", "COMPLETED", "EXPIRED")
    assert data["requester_role"] in ("PARENT", "ELIGIBLE_STUDENT")
    assert isinstance(data["requested_categories"], list) and data["requested_categories"]
    assert isinstance(data["copies_requested"], bool)
    assert_millisecond_timestamp(
        data["statutory_inspection_due_at"], "statutory_inspection_due_at"
    )
    assert_fee_custody_identity(data)


def assert_fee_custody_identity(data: dict):
    """fee_assessed_cents always equals fee_collected_cents plus
    fee_waived_cents plus fee_outstanding_cents."""
    for field in (
        "fee_assessed_cents",
        "fee_collected_cents",
        "fee_waived_cents",
        "fee_outstanding_cents",
        "base_copy_fee_cents",
        "certification_fee_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer number of cents"
    assert data["fee_assessed_cents"] == (
        data["fee_collected_cents"] + data["fee_waived_cents"] + data["fee_outstanding_cents"]
    ), (
        f"fee custody broken: assessed {data['fee_assessed_cents']} != collected "
        f"{data['fee_collected_cents']} + waived {data['fee_waived_cents']} + outstanding "
        f"{data['fee_outstanding_cents']}"
    )
    assert data["fee_assessed_cents"] == (
        data["base_copy_fee_cents"] + data["certification_fee_cents"]
    ), "fee_assessed_cents is base_copy_fee_cents plus certification_fee_cents"


def assert_review_appointment(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["inspection_request_id"])
    assert data["status"] in ("SCHEDULED", "ATTENDED", "SUPERSEDED", "EXPIRED")
    assert isinstance(data["duration_minutes"], int) and data["duration_minutes"] > 0


def assert_amendment_request(data: dict):
    assert_common_fields(data)
    assert data["status"] in (
        "SUBMITTED",
        "DENIED",
        "AMENDED",
        "HEARING_REQUESTED",
        "HEARING_SCHEDULED",
        "UPHELD",
        "STATEMENT_FILED",
    )
    assert is_valid_uuid(data["contested_component_id"])
    assert isinstance(data["contested_field"], str) and data["contested_field"]


def assert_legal_demand(data: dict):
    assert_common_fields(data)
    assert data["demand_type"] in (
        "JUDICIAL_SUBPOENA",
        "GRAND_JURY_SUBPOENA",
        "LAW_ENFORCEMENT_REQUEST",
        "EX_PARTE_ORDER",
    )
    assert data["status"] in ("RECEIVED", "NOTIFIED", "PRODUCED")
    assert isinstance(data["production_scope"], list) and data["production_scope"]
    assert isinstance(data["notification_waived"], bool)
    assert_millisecond_timestamp(data["received_at"], "received_at")


def assert_retention_schedule(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["cumulative_file_id"])
    assert data["status"] in ("ACTIVE", "DESTRUCTION_ELIGIBLE", "DESTROYED")
    assert_millisecond_timestamp(data["exit_anchor_at"], "exit_anchor_at")
    assert_millisecond_timestamp(data["last_activity_at"], "last_activity_at")
    assert_millisecond_timestamp(data["destruction_eligible_at"], "destruction_eligible_at")
    assert_millisecond_timestamp(
        data["exit_anchored_eligible_at"], "exit_anchored_eligible_at"
    )
    assert data["exit_anchored_eligible_at"] <= data["destruction_eligible_at"], (
        "the advisory eligibility date is always at or before the governing one"
    )


def assert_disclosure_log_entry(data: dict):
    assert_common_fields(data, versioned=False)
    assert data["disclosure_type"] in (
        "INTERDISTRICT_TRANSFER",
        "DIRECTORY_INFORMATION",
        "LEGAL_DEMAND",
        "PARENT_INSPECTION",
    )
    assert data["source_type"] in (
        "RECORDS_REQUEST",
        "LEGAL_DEMAND",
        "STUDENT_DIRECTORY",
        "INSPECTION_REQUEST",
    )
    assert isinstance(data["page_count"], int) and data["page_count"] >= 0
    assert_millisecond_timestamp(data["disclosed_at"], "disclosed_at")


def assert_error_envelope_shape(response):
    """Error bodies carry response_type 'error' and a non-empty message."""
    body = response.json()
    assert body.get("response_type") == "error", (
        f"expected response_type 'error', got {body.get('response_type')!r}"
    )
    data = body.get("data", {})
    assert isinstance(data.get("error_id"), str) and data["error_id"]
    assert isinstance(data.get("message"), str) and data["message"].strip()
    return data
