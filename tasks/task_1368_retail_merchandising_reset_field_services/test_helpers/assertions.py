"""Entity assertions and domain invariant checkers (PRD sections 2.4 and 3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, entity: str):
    """Primary resources carry id/created_at/updated_at/version (PRD 2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int), f"{entity}.version must be int"


def assert_client(data: dict):
    _assert_common_fields(data, "Client")
    assert isinstance(data["name"], str) and data["name"]
    assert data["status"] in ("ACTIVE", "SUSPENDED", "TERMINATED")
    if data.get("billing_model") is not None:
        assert data["billing_model"] in ("PER_STORE", "HOURLY")


def assert_project(data: dict):
    _assert_common_fields(data, "Project")
    assert isinstance(data["client_id"], str)
    assert data["scope_type"] in ("RESET", "NEW_ITEM_CUTOVER", "AUDIT", "FIXTURE_INSTALL")
    assert data["status"] in (
        "DRAFT", "SCOPED", "IN_FIELD", "RECONCILING", "COMPLETED", "CANCELLED",
    )
    if data.get("effective_billing_model") is not None:
        assert data["effective_billing_model"] in ("PER_STORE", "HOURLY")
    assert isinstance(data.get("rework_penalty_score"), int)
    assert data.get("posture") in ("NORMAL", "WATCH", "ESCALATED")
    assert isinstance(data.get("completed_store_count"), int)


def assert_store(data: dict):
    _assert_common_fields(data, "Store")
    assert isinstance(data["store_number"], str)
    assert isinstance(data["name"], str)
    assert isinstance(data["timezone"], str)


def assert_project_store(data: dict):
    _assert_common_fields(data, "ProjectStore")
    assert data["status"] in (
        "PENDING", "ASSIGNED", "IN_PROGRESS", "COMPLETED",
        "REWORK_REQUIRED", "DROPPED",
    )
    assert isinstance(data["project_id"], str)
    assert isinstance(data["store_id"], str)


def assert_field_rep(data: dict):
    _assert_common_fields(data, "FieldRep")
    assert data["employment_type"] in ("W2", "C1099")
    assert data["mileage_policy"] in ("HOME_BASED", "FIRST_STOP")
    assert data["status"] in ("ACTIVE", "SUSPENDED", "TERMINATED")
    assert data["home_base_commute_miles"] >= 0
    assert data["mileage_rate_cents"] >= 0
    assert data["travel_minute_rate_cents"] >= 0


def assert_assignment(data: dict):
    _assert_common_fields(data, "Assignment")
    assert data["status"] in (
        "SCHEDULED", "EN_ROUTE", "ON_SITE", "SUBMITTED",
        "VERIFIED", "REJECTED", "CANCELLED",
    )
    assert isinstance(data["project_id"], str)
    assert isinstance(data["project_store_id"], str)
    assert isinstance(data["rep_id"], str)
    assert isinstance(data.get("is_rework"), bool)


def assert_store_visit(data: dict):
    _assert_common_fields(data, "StoreVisit")
    assert data["verification_status"] in ("PENDING_REVIEW", "VERIFIED", "REJECTED")
    assert is_iso8601_timestamp(data.get("check_in_at", ""))
    if data.get("check_out_at") is not None:
        assert is_iso8601_timestamp(data["check_out_at"])
    assert isinstance(data.get("on_site_minutes"), int)
    assert isinstance(data.get("is_rework"), bool)


def assert_photo_evidence(data: dict):
    """PhotoEvidence is immutable once filed: only id + created_at are
    system-managed; updated_at and version are absent (PRD 2.4)."""
    assert is_valid_uuid(data.get("id", "")), "PhotoEvidence.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "updated_at" not in data, "PhotoEvidence must not carry updated_at"
    assert "version" not in data, "PhotoEvidence must not carry version"
    assert data["photo_type"] in ("BEFORE", "AFTER", "POG_LABEL", "FIXTURE", "VOID_AREA")
    assert isinstance(data["image_url"], str)


def assert_exception_report(data: dict):
    """ExceptionReport carries only id + created_at as system fields (PRD 2.4)."""
    assert is_valid_uuid(data.get("id", "")), "ExceptionReport.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "updated_at" not in data, "ExceptionReport must not carry updated_at"
    assert "version" not in data, "ExceptionReport must not carry version"
    assert data["exception_type"] in (
        "OUT_OF_STOCK", "VOID", "FIXTURE_MISSING", "POG_MISSING", "PRICE_MISMATCH",
    )
    assert data["sku_count"] >= 1
    assert data["severity"] in ("LOW", "MEDIUM", "HIGH")
    assert data["resolution"] in ("OPEN", "RESOLVED", "WAIVED")


def assert_fixture_shipment(data: dict):
    _assert_common_fields(data, "FixtureShipment")
    assert data["status"] in (
        "LABEL_CREATED", "IN_TRANSIT", "DELIVERED", "DELIVERY_EXCEPTION", "LOST",
    )
    assert isinstance(data["carrier"], str)
    assert isinstance(data["tracking_number"], str)


def assert_rework_authorization(data: dict):
    _assert_common_fields(data, "ReworkAuthorization")
    assert data["status"] in ("REQUESTED", "APPROVED", "CONSUMED", "DENIED", "EXPIRED")
    assert isinstance(data["project_id"], str)
    assert isinstance(data["project_store_id"], str)
    assert isinstance(data["rejected_store_visit_id"], str)


def assert_mileage_log(data: dict):
    _assert_common_fields(data, "MileageLog")
    assert data["status"] in ("SUBMITTED", "APPROVED", "REJECTED", "PAID")
    assert data["round_trip_miles"] >= 0
    assert data["drive_minutes"] >= 0
    assert isinstance(data.get("mileage_pay_cents"), int)
    assert isinstance(data.get("travel_time_pay_cents"), int)


def assert_invoice(data: dict):
    _assert_common_fields(data, "Invoice")
    assert data["status"] in ("OPEN", "FINALIZED", "VOID")
    assert isinstance(data.get("line_total_cents"), int)
    assert isinstance(data.get("adjustment_cents"), int)


def assert_project_posture_invariants(project: dict):
    """Posture derives from rework_penalty_score thresholds (PRD 2.9):
    NORMAL below 20, WATCH at 20..39, ESCALATED at 40+."""
    score = project["rework_penalty_score"]
    posture = project["posture"]
    expected = (
        "ESCALATED" if score >= 40 else "WATCH" if score >= 20 else "NORMAL"
    )
    assert posture == expected, (
        f"posture {posture} inconsistent with score {score}; expected {expected}"
    )
