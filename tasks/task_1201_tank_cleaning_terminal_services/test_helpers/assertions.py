"""Entity assertions and domain invariant checkers (PRD §2.2-§2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict, with_version: bool = True):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601 UTC"
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), \
            "updated_at must be ISO 8601 UTC"
        assert isinstance(data.get("version"), int), "version must be an integer"


def assert_terminal(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["wastewater_daily_capacity_liters"], int)
    assert isinstance(data["safety_score_threshold"], (int, float))
    assert data["score_variant"] in ("ROLLING_12MO", "LIFETIME")
    assert isinstance(data["mass_balance_tolerance_pct"], (int, float))


def assert_product(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str) and data["code"]
    assert data["family"] in (
        "GASOLINE", "DISTILLATE", "JET", "CRUDE", "CHEMICAL", "VEGOIL")
    assert data["viscosity_class"] in ("LOW", "MEDIUM", "HIGH")
    assert isinstance(data["compatibility_group"], str)
    assert isinstance(data["flash_point_c"], (int, float))


def assert_tank(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("terminal_id", ""))
    assert isinstance(data["tank_number"], str) and data["tank_number"]
    assert isinstance(data["capacity_m3"], int)
    assert is_valid_uuid(data.get("current_product_id", ""))
    assert data["status"] in ("IN_SERVICE", "OUT_OF_SERVICE")


def assert_contractor(data: dict):
    _assert_common(data)
    assert isinstance(data["company_name"], str) and data["company_name"]
    assert data["status"] in ("APPLICANT", "QUALIFIED", "SUSPENDED", "BARRED")
    assert isinstance(data["safety_score"], (int, float))


def assert_safety_event(data: dict):
    # Append-only: only id + created_at from the common set (PRD §2.4).
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601 UTC"
    assert "updated_at" not in data, "safety events carry no updated_at"
    assert "version" not in data, "safety events carry no version"
    assert is_valid_uuid(data.get("contractor_id", ""))
    assert data["kind"] in ("INCIDENT", "VIOLATION", "NEAR_MISS", "TRAINING_CREDIT")
    assert isinstance(data["severity_weight"], int)
    assert 1 <= data["severity_weight"] <= 10
    assert is_iso8601_timestamp(data.get("occurred_at", ""))


def assert_cleaning_job(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("terminal_id", ""))
    assert is_valid_uuid(data.get("tank_id", ""))
    assert is_valid_uuid(data.get("contractor_id", ""))
    assert is_valid_uuid(data.get("from_product_id", ""))
    assert is_valid_uuid(data.get("to_product_id", ""))
    assert isinstance(data["heel_volume_liters_sounding"], int)
    assert isinstance(data["base_service_fee_cents"], int)
    assert data["status"] in (
        "DRAFT", "SCHEDULED", "TANK_OOS", "HEEL_REMOVED", "SLUDGE_REMOVED",
        "GAS_FREE_PENDING", "GAS_FREE_CERTIFIED", "ENTRY_IN_PROGRESS",
        "ENTRY_COMPLETE", "INSPECTION_IN_PROGRESS", "INSPECTION_ACCEPTED",
        "REWORK_CLEANING", "FLUSH_IN_PROGRESS", "FLUSH_VERIFIED", "RTS_PENDING",
        "RETURNED_TO_SERVICE", "PAUSED", "CANCELLED",
    )
    if data.get("changeover_class") is not None:
        assert data["changeover_class"] in (
            "COMPATIBLE_DIRECT", "REQUIRES_FLUSH", "REQUIRES_FULL_STRIP",
            "FORBIDDEN")
    if data.get("paused_from") is not None:
        assert data["paused_from"] in (
            "GAS_FREE_CERTIFIED", "ENTRY_IN_PROGRESS", "ENTRY_COMPLETE")
    if data.get("pause_reason") is not None:
        assert data["pause_reason"] in ("CERT_REVOKED", "CERT_EXPIRED", "MANUAL")


def assert_service_window(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("tank_id", ""))
    assert is_iso8601_timestamp(data.get("planned_start", ""))
    assert is_iso8601_timestamp(data.get("planned_end", ""))
    assert data["status"] in ("PLANNED", "ACTIVE", "COMPLETED", "CANCELLED", "OVERRUN")


def assert_waste_profile(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("job_id", ""))
    assert isinstance(data["waste_code"], str) and data["waste_code"]
    assert data["hazard_class"] in ("NON_HAZARDOUS", "HAZARDOUS")
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED")


def assert_waste_shipment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("job_id", ""))
    assert is_valid_uuid(data.get("profile_id", ""))
    assert isinstance(data["manifested_kg"], int)
    assert isinstance(data["disposal_cost_cents"], int)
    assert data["status"] in ("BOOKED", "IN_TRANSIT", "DELIVERED", "RECONCILED",
                              "VOIDED")


def assert_gas_free_certificate(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("job_id", ""))
    assert isinstance(data["lel_pct"], (int, float))
    assert isinstance(data["o2_pct"], (int, float))
    assert isinstance(data["h2s_ppm"], (int, float))
    assert isinstance(data["benzene_ppm"], (int, float))
    assert is_iso8601_timestamp(data.get("issued_at", ""))
    assert is_iso8601_timestamp(data.get("expires_at", ""))
    assert data["status"] in ("VALID", "EXPIRED", "REVOKED", "SUPERSEDED")


def assert_entry_permit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("job_id", ""))
    assert is_valid_uuid(data.get("cert_id", ""))
    assert isinstance(data["max_entrants"], int) and data["max_entrants"] >= 1
    assert data["status"] in ("REQUESTED", "ISSUED", "ACTIVE", "SUSPENDED",
                              "CLOSED", "VOIDED")
    assert data["atmosphere"] in ("CLEAR", "ALARM", "RETEST_REQUIRED")


def assert_inspector(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["certification_level"] in ("API653", "API650", "BOTH")


def assert_inspection(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("job_id", ""))
    assert is_valid_uuid(data.get("inspector_id", ""))
    assert is_iso8601_timestamp(data.get("scheduled_start", ""))
    assert is_iso8601_timestamp(data.get("scheduled_end", ""))
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "REPORTED", "ACCEPTED",
                              "REJECTED", "CANCELLED")


def assert_inspection_finding(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("inspection_id", ""))
    assert data["severity"] in ("CRITICAL", "MAJOR", "MINOR")
    assert isinstance(data["description"], str)
    assert isinstance(data["requires_repair"], bool)
    assert data["status"] in ("OPEN", "REPAIR_ORDERED", "RESOLVED", "ACCEPTED_RISK")


def assert_repair_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("finding_id", ""))
    assert is_valid_uuid(data.get("job_id", ""))
    assert isinstance(data["description"], str)
    assert data["status"] in ("OPEN", "IN_PROGRESS", "COMPLETED", "VERIFIED")


def assert_wastewater_batch(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("terminal_id", ""))
    assert is_valid_uuid(data.get("job_id", ""))
    assert isinstance(data["volume_liters"], int) and data["volume_liters"] > 0
    assert data["status"] in ("COLLECTED", "LAB_TESTED", "AUTHORIZED",
                              "DISCHARGED", "REJECTED")


def assert_mass_balance_holds(job: dict, tolerance_pct: float):
    """PRD §3.8 invariant: |shipped - expected| <= expected * tolerance/100."""
    expected = job.get("expected_solids_kg")
    shipped = job.get("shipped_solids_kg")
    if expected is None or shipped is None:
        return
    bound = round(expected * tolerance_pct / 100, 2)
    assert abs(shipped - expected) <= bound + 1e-9, (
        f"mass balance violated: |{shipped} - {expected}| > {bound}")
