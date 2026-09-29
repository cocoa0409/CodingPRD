"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID string, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity}.created_at must be ISO 8601 UTC with three fractional digits, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{entity}.updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer starting at 1, got {data.get('version')!r}"
    )


def assert_append_only_score_shape(data: dict):
    """An observation score attempt carries only id and created_at."""
    assert is_valid_uuid(data.get("id", "")), "ObservationScore.id must be a UUID string"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert "updated_at" not in data, "score rows are append-only and carry no updated_at"
    assert "version" not in data, "score rows are append-only and carry no version"


def assert_provider(data: dict):
    _assert_common_fields(data, "Provider")
    assert data["status"] in ["APPLIED", "ENROLLED", "ACTIVE", "SUSPENDED", "WITHDRAWN"]
    assert data["region_code"] in ["URBAN", "RURAL", "FRONTIER"]
    assert isinstance(data["licensed_capacity"], int) and data["licensed_capacity"] >= 1
    assert float(data["active_staff_fte"]) > 0
    assert 0.00 <= float(data["credential_compliance_pct"]) <= 100.00, (
        "credential_compliance_pct is capped so it never exceeds 100.00"
    )
    assert isinstance(data["reimbursement_adjustment_cents"], int)
    assert isinstance(data["public_listing_visible"], bool)


def assert_standard_domain(data: dict):
    _assert_common_fields(data, "StandardDomain")
    assert data["domain_code"] in [
        "LEARNING_ENVIRONMENT",
        "STAFF_QUALIFICATIONS",
        "FAMILY_PARTNERSHIP",
        "ADMINISTRATION",
        "CHILD_ASSESSMENT",
    ]
    assert 1 <= data["block_level"] <= 3
    assert 1 <= data["max_points"] <= 100
    assert 1 <= data["block_min_points"] <= data["max_points"]
    assert 0 < float(data["weight"]) <= 1


def assert_staff_credential(data: dict):
    _assert_common_fields(data, "StaffCredential")
    assert data["role_type"] in ["DIRECTOR", "LEAD_TEACHER", "ASSISTANT"]
    assert data["registry_status"] in ["UNLINKED", "PENDING", "VERIFIED", "EXPIRED"]
    assert 1 <= data["credential_level"] <= 6
    assert 0 < float(data["fte"]) <= 1


def assert_rating_cycle(data: dict):
    _assert_common_fields(data, "RatingCycle")
    assert data["status"] in [
        "DRAFT",
        "SELF_ASSESSMENT_SUBMITTED",
        "DOCS_VERIFIED",
        "OBSERVATION_SCHEDULED",
        "OBSERVATION_FINALIZED",
        "AWARDED",
        "ACTIVE",
        "UNDER_APPEAL",
        "EXPIRED",
        "SUPERSEDED",
        "WITHDRAWN",
    ]
    assert data["publication_status"] in ["UNPUBLISHED", "PUBLISHED", "SUPPRESSED", "WITHDRAWN"]
    assert data["cycle_type"] in ["INITIAL", "RERATING", "REMAND"]


def assert_self_assessment(data: dict):
    _assert_common_fields(data, "SelfAssessment")
    assert data["status"] in ["SUBMITTED", "RETURNED", "VERIFIED"]
    assert isinstance(data["return_count"], int) and data["return_count"] >= 0


def assert_observer(data: dict):
    _assert_common_fields(data, "Observer")
    assert data["status"] in ["PROVISIONAL", "RELIABLE", "LAPSED", "RETIRED"]
    assert data["tool_code"] in ["ERS_INFANT_TODDLER", "ERS_EARLY_CHILDHOOD"]


def assert_observation_visit(data: dict):
    _assert_common_fields(data, "ObservationVisit")
    assert data["status"] in [
        "SCHEDULED",
        "IN_PROGRESS",
        "SCORES_ENTERED",
        "RELIABILITY_CHECK",
        "FINALIZED",
        "CANCELLED",
    ]
    assert isinstance(data["rescore_count"], int) and data["rescore_count"] >= 0
    if data.get("composite") is not None:
        assert 1.00 <= float(data["composite"]) <= 7.00, "composite lies between 1.00 and 7.00"


def assert_appeal(data: dict):
    _assert_common_fields(data, "Appeal")
    assert data["status"] in [
        "FILED",
        "UNDER_REVIEW",
        "INFO_REQUESTED",
        "SUSTAINED",
        "DENIED",
        "WITHDRAWN",
    ]
    assert data["grounds"] in [
        "SCORING_ERROR",
        "OBSERVER_RELIABILITY",
        "DOCUMENTATION_OMITTED",
        "PROCEDURAL",
    ]
    assert isinstance(data["info_request_count"], int) and data["info_request_count"] >= 0


def assert_data_dispute(data: dict):
    _assert_common_fields(data, "DataDispute")
    assert data["status"] in [
        "FILED",
        "TRIAGE",
        "INFO_REQUESTED",
        "ESCALATED",
        "CORRECTION_APPLIED",
        "REJECTED",
        "WITHDRAWN",
    ]
    assert data["disputed_field"] in [
        "PUBLISHED_TIER",
        "PUBLISHED_SCORE",
        "DOMAIN_POINTS",
        "LICENSED_CAPACITY",
        "COUNTY_CODE",
    ]
    assert isinstance(data["triage_round"], int) and data["triage_round"] >= 0


def assert_improvement_grant(data: dict):
    _assert_common_fields(data, "ImprovementGrant")
    assert data["status"] in ["OFFERED", "ACCEPTED", "OPEN", "FROZEN", "CLOSED", "DECLINED"]
    assert data["compliance_status"] in [
        "COMPLIANT",
        "UNDER_REVIEW",
        "FINDING_ISSUED",
        "REMEDIATED",
        "RECOVERY",
    ]
    for money in (
        "awarded_amount_cents",
        "committed_cents",
        "reimbursed_cents",
        "available_cents",
        "recovery_amount_cents",
    ):
        assert isinstance(data[money], int), f"{money} must be an integer number of cents"


def assert_grant_ledger_identity(grant: dict):
    """The awarded amount always equals committed + reimbursed + available."""
    total = grant["committed_cents"] + grant["reimbursed_cents"] + grant["available_cents"]
    assert total == grant["awarded_amount_cents"], (
        "grant ledger identity broken: committed "
        f"{grant['committed_cents']} + reimbursed {grant['reimbursed_cents']} + available "
        f"{grant['available_cents']} != awarded {grant['awarded_amount_cents']}"
    )


def assert_grant_expenditure(data: dict):
    _assert_common_fields(data, "GrantExpenditure")
    assert data["status"] in ["SUBMITTED", "APPROVED", "REJECTED", "REIMBURSED", "VOIDED"]
    assert data["category"] in ["EQUIPMENT", "PROF_DEV", "FACILITY", "ADMIN"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0


def assert_coaching_allocation(data: dict):
    _assert_common_fields(data, "CoachingAllocation")
    assert data["status"] in ["PROPOSED", "ACTIVE", "SUSPENDED", "CLOSED", "VOID"]
    assert data["funding_source"] in ["GRANT", "STATE_BASE"]
    for money in ("base_hours_cost_cents", "admin_fee_cents", "total_cost_cents", "spend_cap_cents"):
        assert isinstance(data[money], int), f"{money} must be an integer number of cents"


def assert_allocation_hours_identity(allocation: dict):
    """Allocated hours always equal scheduled + delivered + remaining."""
    total = (
        float(allocation["scheduled_hours"])
        + float(allocation["delivered_hours"])
        + float(allocation["remaining_hours"])
    )
    assert abs(total - float(allocation["allocated_hours"])) < 1e-6, (
        "allocation hours identity broken: scheduled "
        f"{allocation['scheduled_hours']} + delivered {allocation['delivered_hours']} + remaining "
        f"{allocation['remaining_hours']} != allocated {allocation['allocated_hours']}"
    )


def assert_coaching_session(data: dict):
    _assert_common_fields(data, "CoachingSession")
    assert data["status"] in ["SCHEDULED", "DELIVERED", "CANCELLED"]
    assert isinstance(data["iso_week_key"], str) and "-W" in data["iso_week_key"]


def assert_subsidy_claim(data: dict):
    _assert_common_fields(data, "SubsidyClaim")
    assert data["status"] in [
        "SUBMITTED",
        "APPROVED",
        "PAID",
        "REJECTED",
        "RECONCILE_REQUIRED",
    ]
    assert isinstance(data["base_amount_cents"], int)
    assert isinstance(data["reimbursement_cents"], int)


def assert_two_decimal_places(value, label="value"):
    assert value is not None, f"{label} must not be null"
    assert round(float(value), 2) == float(value), f"{label} must carry two decimal places, got {value}"


def assert_four_decimal_places(value, label="value"):
    assert value is not None, f"{label} must not be null"
    assert round(float(value), 4) == float(value), f"{label} must carry four decimal places, got {value}"
