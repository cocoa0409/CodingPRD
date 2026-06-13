"""Entity assertions and domain invariant checkers (PRD 2.4, 3.7, 3.9).

Field names are exactly as named in the PRD.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Common mutable-resource fields (PRD 2.4): id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version must begin at 1+, got {data['version']}"


def assert_clinic(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["room_concurrency_limit"], int) and data["room_concurrency_limit"] >= 1
    assert is_iso8601_timestamp(data.get("current_clock_utc", "")), "current_clock_utc must be ISO 8601"


def assert_package(data: dict):
    _assert_common(data)
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] >= 0
    assert 0.0 <= data["coverage_pct"] <= 1.0
    assert isinstance(data["lifetime_coverage_cap_cents"], int) and data["lifetime_coverage_cap_cents"] >= 0
    assert isinstance(data["annual_cryo_storage_cents"], int) and data["annual_cryo_storage_cents"] >= 0
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_patient(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_donor(data: dict):
    _assert_common(data)
    assert data["donor_type"] in ("EGG", "SPERM")
    assert data["status"] in ("AVAILABLE", "RESERVED", "CONSUMED")


def assert_surrogate(data: dict):
    _assert_common(data)
    assert data["status"] in ("AVAILABLE", "MATCHED")


def assert_consent_form(data: dict):
    _assert_common(data)
    assert isinstance(data["form_key"], str) and data["form_key"]
    assert isinstance(data["required_for"], list)
    assert data["status"] in ("DRAFT", "PUBLISHED", "SUPERSEDED")


def assert_patient_consent(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "REVOKED", "STALE")
    assert isinstance(data["pinned_form_version"], int)


def assert_tank(data: dict):
    _assert_common(data)
    assert isinstance(data["capacity_slots"], int) and data["capacity_slots"] >= 1
    assert isinstance(data["reserved_slots"], int) and data["reserved_slots"] >= 0
    assert data["status"] in ("ONLINE", "MAINTENANCE")
    assert_tank_slot_invariants(data)


def assert_tank_slot_invariants(data: dict):
    """Tank slot accounting invariants (PRD 3.7)."""
    assert data["reserved_slots"] >= 0, "reserved_slots must be non-negative"
    assert data["reserved_slots"] <= data["capacity_slots"], "reserved_slots must not exceed capacity"
    # committed_free_slots = capacity - STORED count = capacity - reserved_slots
    assert data["committed_free_slots"] == data["capacity_slots"] - data["reserved_slots"], (
        "committed_free_slots must equal capacity_slots - reserved_slots"
    )
    # projected_free_slots reserves a slot per PENDING + STORED, so never above committed
    assert data["projected_free_slots"] <= data["committed_free_slots"], (
        "projected_free_slots must not exceed committed_free_slots"
    )


def assert_cycle(data: dict):
    _assert_common(data)
    assert data["protocol_status"] in (
        "DRAFT", "STIM", "RETRIEVAL", "FERTILIZATION",
        "FRESH_TRANSFER", "FREEZE_ALL", "COMPLETED", "CANCELLED",
    )
    assert data["billing_status"] in ("UNBILLED", "ESTIMATED", "SETTLED", "WRITTEN_OFF")
    assert isinstance(data["oocytes_retrieved"], int)
    assert isinstance(data["embryos_fertilized"], int)


def assert_medication(data: dict):
    _assert_common(data)
    assert isinstance(data["line_total_cents"], int) and data["line_total_cents"] >= 0
    assert data["status"] in ("SCHEDULED", "ADMINISTERED", "CANCELLED")


def assert_appointment(data: dict):
    _assert_common(data)
    assert data["appointment_type"] in ("BLOODWORK", "ULTRASOUND", "CONSULT")
    assert data["status"] in ("CONFIRMED", "RESCHEDULED", "COMPLETED", "NO_SHOW", "CANCELLED")
    assert isinstance(data["room_capacity_weight"], int) and data["room_capacity_weight"] >= 1


def assert_specimen(data: dict):
    _assert_common(data)
    assert data["specimen_type"] in ("EMBRYO", "OOCYTE", "SPERM")
    assert data["status"] in ("PENDING", "STORED", "THAWED", "DISCARDED", "TRANSFERRED_OUT")
    assert isinstance(data["storage_years_accrued"], int) and data["storage_years_accrued"] >= 0


def assert_invoice(data: dict):
    _assert_common(data)
    assert data["status"] in ("ISSUED", "VOID")
    assert isinstance(data["line_items"], list)
    assert data["patient_total_cents"] == data["gross_total_cents"] - data["insurer_total_cents"], (
        "patient_total_cents must equal gross_total_cents - insurer_total_cents"
    )


def assert_outcome(data: dict):
    _assert_common(data)
    assert data["pregnancy_test_result"] in ("POSITIVE", "NEGATIVE", "INCONCLUSIVE")


def assert_billing_conservation(cycle: dict):
    """PRD 3.9: gross_charge_cents == insurer_paid_cents + final_patient_owed_cents."""
    assert cycle["gross_charge_cents"] == cycle["insurer_paid_cents"] + cycle["final_patient_owed_cents"], (
        f"Conservation broken: gross {cycle['gross_charge_cents']} != "
        f"insurer {cycle['insurer_paid_cents']} + patient {cycle['final_patient_owed_cents']}"
    )
