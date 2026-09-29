"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_common_fields(data: dict) -> None:
    """id is a server-minted UUID with no type prefix; version starts at 1."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version starts at 1, got {data['version']}"


def assert_jurisdiction(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert isinstance(data["jurisdiction_code"], str) and 2 <= len(data["jurisdiction_code"]) <= 16
    assert data["accepted_accreditation_bodies"], "accepted_accreditation_bodies is non-empty"
    for body in data["accepted_accreditation_bodies"]:
        assert body in ("ANAB_CFP", "ANSI_LEGACY", "STATE_ONLY")
    assert data["accepted_languages"], "accepted_languages is non-empty"
    for lang in data["accepted_languages"]:
        assert lang in ("EN", "ES", "ZH", "VI")
    assert isinstance(data["accepts_remote_proctoring"], bool)
    assert data["min_passing_score_override"] is None or 0 <= data["min_passing_score_override"] <= 100
    assert isinstance(data["requires_local_registration"], bool)
    assert 1 <= data["posting_deadline_days"] <= 365
    assert 12 <= data["recert_cycle_months"] <= 120
    assert 0.0 <= data["exam_fee_surcharge_pct"] <= 0.25


def assert_training_provider(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and 1 <= len(data["legal_name"]) <= 160
    assert "@" in data["contact_email"]
    assert is_valid_uuid(data["jurisdiction_id"])
    assert_provider_ledger_identity(data)


def assert_provider_ledger_identity(data: dict) -> None:
    """credit_balance_cents is always lifetime_credited_cents minus lifetime_charged_cents."""
    for field in ("lifetime_credited_cents", "lifetime_charged_cents", "credit_balance_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer count of whole cents"
    expected = data["lifetime_credited_cents"] - data["lifetime_charged_cents"]
    assert data["credit_balance_cents"] == expected, (
        "credit_balance_cents must equal lifetime_credited_cents minus "
        f"lifetime_charged_cents: expected {expected}, got {data['credit_balance_cents']}"
    )


def assert_exam_form(data: dict) -> None:
    assert_common_fields(data)
    assert data["language"] in ("EN", "ES", "ZH", "VI")
    assert data["accreditation_body"] in ("ANAB_CFP", "ANSI_LEGACY", "STATE_ONLY")
    assert 10 <= data["scored_item_count"] <= 200
    assert 0 <= data["pretest_item_count"] <= 40
    assert 0 <= data["national_cut_score"] <= 100
    assert 30 <= data["base_minutes"] <= 240
    assert 0 <= data["translated_extra_minutes"] <= 60
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_testing_site(data: dict) -> None:
    assert_common_fields(data)
    assert 1 <= data["seat_count"] <= 50
    assert data["languages_supported"], "languages_supported is non-empty"
    assert isinstance(data["reserved_seat_minutes"], int)
    assert data["reserved_seat_minutes"] >= 0


def assert_candidate(data: dict) -> None:
    assert_common_fields(data)
    assert "@" in data["email"]
    assert data["preferred_language"] in ("EN", "ES", "ZH", "VI")
    assert isinstance(data["security_hold"], bool)
    assert data["substantiated_incident_count"] >= 0
    assert data["compliance_status"] in (
        "NOT_CERTIFIED", "CERTIFIED", "LAPSED", "NON_COMPLIANT",
    )


def assert_proctor(data: dict) -> None:
    assert_common_fields(data)
    assert "@" in data["email"]
    assert data["roles_held"], "roles_held is non-empty"
    for role in data["roles_held"]:
        assert role in ("PROCTOR", "INSTRUCTOR")
    assert data["languages_certified"], "languages_certified is non-empty"
    assert isinstance(data["remote_certified"], bool)
    assert data["registration_status"] in (
        "PENDING", "REGISTERED", "REJECTED", "UNDER_AUDIT", "SUSPENDED", "REVOKED",
    )
    assert data["suspended_reason"] in (None, "AUDIT_FAILURE", "RISK_THRESHOLD_BREACH")
    assert data["risk_variant_applied"] in ("ROLLING_WINDOW", "LIFETIME_CUMULATIVE")
    assert data["proctored_session_count"] >= 0
    assert data["substantiated_incident_weight_total"] >= 0
    assert data["reserved_minutes"] >= 0
    assert_two_decimal_places(data["risk_score"])


def assert_two_decimal_places(value) -> None:
    """risk_score is stored with exactly two decimal places, rounded half up."""
    assert round(float(value), 2) == float(value), (
        f"value {value!r} must carry at most two decimal places"
    )


def assert_access_code_batch(data: dict) -> None:
    assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "DEPLETED", "EXPIRED", "VOIDED")
    assert isinstance(data["total_price_cents"], int)
    assert_inventory_conservation(data)


def assert_inventory_conservation(data: dict) -> None:
    """available + assigned + consumed + voided always equals quantity_purchased."""
    total = (
        data["available_count"] + data["assigned_count"]
        + data["consumed_count"] + data["voided_count"]
    )
    assert total == data["quantity_purchased"], (
        "available_count plus assigned_count plus consumed_count plus voided_count must "
        f"equal quantity_purchased: {total} != {data['quantity_purchased']}"
    )


def assert_access_code(data: dict) -> None:
    assert_common_fields(data)
    assert data["status"] in ("AVAILABLE", "ASSIGNED", "CONSUMED", "VOIDED", "EXPIRED")
    assert data["bundle_type"] in ("EXAM_ONLY", "COURSE_PLUS_EXAM")
    assert isinstance(data["code"], str) and data["code"]
    assert data["assignment_release_count"] >= 0


def assert_accommodation_request(data: dict) -> None:
    assert_common_fields(data)
    assert data["accommodation_type"] in (
        "EXTRA_TIME", "READER_ASSIST", "SEPARATE_ROOM", "TRANSLATED_FORM",
    )
    assert data["status"] in ("REQUESTED", "UNDER_REVIEW", "APPROVED", "DENIED")
    assert 1.0 <= float(data["requested_multiplier"]) <= 2.0
    if data["approved_multiplier"] is not None:
        assert 1.0 <= float(data["approved_multiplier"]) <= 2.0


def assert_exam_session(data: dict) -> None:
    assert_common_fields(data)
    assert data["delivery_mode"] in ("IN_PERSON", "REMOTE")
    assert data["session_status"] in (
        "SCHEDULED", "CHECKED_IN", "IN_PROGRESS", "SUBMITTED",
        "CLOSED", "CANCELLED", "INVALIDATED",
    )
    assert data["proctoring_status"] in (
        "PENDING_ASSIGNMENT", "ASSIGNED", "PENDING_REPROCTOR", "ATTESTED",
        "INCIDENT_UNDER_REVIEW", "CLEARED", "COMPROMISED",
    )
    assert data["id_document_type"] in (None, "GOVT_PHOTO_ID", "PASSPORT", "MILITARY_ID")
    assert 1 <= data["allowed_minutes"] <= 240
    assert data["reschedule_count"] >= 0


def assert_score_report(data: dict) -> None:
    assert_common_fields(data)
    assert data["status"] in ("PROVISIONAL", "FINAL", "VOIDED")
    assert isinstance(data["provisional_scaled_score"], int)
    assert isinstance(data["effective_cut_score"], int)
    assert data["voided_item_count"] >= 0
    assert data["voided_correct_count"] >= 0


def assert_security_incident(data: dict) -> None:
    assert_common_fields(data)
    assert data["category"] in (
        "IMPERSONATION", "PROHIBITED_MATERIAL", "ROOM_SCAN_REFUSAL", "CONTENT_DISCLOSURE",
    )
    assert data["severity"] in ("MINOR", "MAJOR", "CRITICAL")
    assert data["status"] in ("OPEN", "UNDER_REVIEW", "SUBSTANTIATED", "DISMISSED")
    assert data["severity_weight"] == {"MINOR": 1, "MAJOR": 3, "CRITICAL": 5}[data["severity"]]
    assert 10 <= len(data["narrative"]) <= 2000


def assert_certificate(data: dict) -> None:
    assert_common_fields(data)
    assert data["status"] in ("ISSUED", "EXPIRED", "REVOKED", "SUPERSEDED")
    assert data["revocation_reason"] in (None, "SCORE_VOIDED", "JURISDICTION_WITHDRAWAL")
    assert isinstance(data["certificate_number"], str) and data["certificate_number"]
    assert isinstance(data["reminder_tiers_sent"], list)
    for tier in data["reminder_tiers_sent"]:
        assert tier in ("T_180", "T_90", "T_30", "T_LAPSED")
    assert isinstance(data["issuance_fee_cents"], int)


def assert_local_registration(data: dict) -> None:
    assert_common_fields(data)
    assert data["status"] in (
        "FILED", "POSTED", "VERIFIED", "REJECTED", "DELINQUENT", "WITHDRAWN",
    )
    assert data["refile_count"] >= 0


def assert_envelope_object(response) -> None:
    """A single-resource response declares response_type "object" and an api_request_id."""
    body = response.json()
    assert body["response_type"] == "object", f"expected object, got {body['response_type']}"
    assert body["meta"]["api_request_id"].startswith("req_"), (
        "api_request_id must start with req_"
    )


def assert_list_meta_omits_pagination(response) -> None:
    """Single-resource responses omit limit, offset, total_count and has_more."""
    meta = response.json()["meta"]
    for field in ("limit", "offset", "total_count", "has_more"):
        assert field not in meta, f"single-resource meta must omit {field}"
