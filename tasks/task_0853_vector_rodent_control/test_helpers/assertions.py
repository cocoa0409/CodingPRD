"""Entity assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

TIMESTAMP_HINT = "timestamps are ISO 8601 UTC with exactly three fractional digits"


def assert_common_record(data: dict, *, versioned: bool = True):
    """Every persisted record carries a UUID id and a created_at."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    if versioned:
        assert isinstance(data.get("version"), int) and data["version"] >= 1, (
            f"version must be a positive integer, got {data.get('version')!r}"
        )
        assert is_iso8601_timestamp(data.get("updated_at", "")), (
            f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
        )


def assert_append_only_record(data: dict):
    """Assessments and surveillance readings carry no updated_at and no version."""
    assert_common_record(data, versioned=False)
    assert "version" not in data, "append-only records must not expose version"
    assert "updated_at" not in data, "append-only records must not expose updated_at"


def assert_zone(data: dict):
    assert_common_record(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["code"], str) and data["code"]
    assert data["posture"] in ("NORMAL", "ELEVATED", "HOTSPOT")
    assert isinstance(data["rodent_index"], (int, float))
    assert data["open_complaint_count"] >= 0
    assert data["chronic_property_count"] >= 0
    assert data["active_station_count"] >= 0


def assert_property_owner(data: dict):
    assert_common_record(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["notice_preference"] in (
        "FIRST_CLASS_MAIL", "CERTIFIED_MAIL", "PERSONAL_SERVICE"
    )
    assert isinstance(data["hardship_certified"], bool)
    assert data["outstanding_balance_cents"] >= 0
    assert data["lifetime_paid_cents"] >= 0


def assert_property(data: dict):
    assert_common_record(data)
    assert is_valid_uuid(data["zone_id"])
    assert is_valid_uuid(data["owner_id"])
    assert data["property_type"] in (
        "RESIDENTIAL_SINGLE", "RESIDENTIAL_MULTI", "COMMERCIAL_FOOD",
        "COMMERCIAL_OTHER", "VACANT_LOT",
    )
    assert data["unit_count"] >= 1
    assert 0.0 <= data["chronic_score"] <= 100.0
    assert 0.0 <= data["provisional_chronic_score"] <= 100.0
    assert isinstance(data["chronic_flag"], bool)
    assert data["open_order_count"] >= 0
    assert isinstance(data["lien_encumbered"], bool)


def assert_officer(data: dict):
    assert_common_record(data)
    assert data["rank"] in ("FIELD_INSPECTOR", "SUPERVISOR")
    assert data["active_assignment_count"] >= 0


def assert_complaint(data: dict):
    assert_common_record(data)
    assert is_valid_uuid(data["property_id"])
    assert is_valid_uuid(data["zone_id"])
    assert data["complaint_type"] in (
        "RODENT_SIGHTING", "HARBORAGE", "GARBAGE_ACCUMULATION",
        "DEAD_ANIMAL", "MOSQUITO_BREEDING",
    )
    assert data["reporter_type"] in ("RESIDENT", "OWNER", "AGENCY", "ANONYMOUS")
    assert data["severity"] in ("ROUTINE", "HIGH", "CRITICAL")
    assert data["status"] in (
        "RECEIVED", "TRIAGED", "INSPECTION_SCHEDULED", "INSPECTED",
        "ABATEMENT_ORDERED", "CLOSED_NO_VIOLATION", "CLOSED_RESOLVED",
        "CLOSED_WITHDRAWN", "CLOSED_DUPLICATE",
    )
    assert 0.0 <= data["priority_score"] <= 100.0
    assert is_iso8601_timestamp(data["response_due_at"]), TIMESTAMP_HINT


def assert_inspection(data: dict):
    assert_common_record(data)
    assert data["kind"] in ("INITIAL", "REINSPECTION")
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "COMPLETED")
    assert is_valid_uuid(data["property_id"])
    assert is_valid_uuid(data["officer_id"])
    if data["kind"] == "INITIAL":
        assert data.get("abatement_order_id") is None, (
            "an INITIAL visit carries abatement_order_id null"
        )
        assert is_valid_uuid(data.get("complaint_id") or "")
    else:
        assert data.get("complaint_id") is None, (
            "a REINSPECTION carries complaint_id null"
        )
        assert is_valid_uuid(data.get("abatement_order_id") or "")


def assert_assessment(data: dict):
    assert_append_only_record(data)
    assert is_valid_uuid(data["inspection_id"])
    for field in ("harborage_score", "attractant_score", "sanitation_score"):
        assert 0 <= data[field] <= 10, f"{field} must be within 0-10"
    assert data["burrow_count"] >= 0
    assert 0.0 <= data["infestation_index"] <= 100.0
    assert data["infestation_tier"] in ("LOW", "MODERATE", "SEVERE")


def assert_abatement_order(data: dict):
    assert_common_record(data)
    assert is_valid_uuid(data["property_id"])
    assert is_valid_uuid(data["inspection_id"])
    assert data["status"] in (
        "ISSUED", "SERVED", "REINSPECTION_SCHEDULED", "ESCALATED",
        "CITY_ABATED", "COMPLIED", "CLOSED",
    )
    assert isinstance(data["required_actions"], list) and data["required_actions"]
    assert data["infestation_tier_at_issue"] in ("LOW", "MODERATE", "SEVERE")
    assert 0 <= data["escalation_level"] <= 2
    assert 0 <= data["extension_count"] <= 1


def assert_owner_notice(data: dict):
    assert_common_record(data)
    assert is_valid_uuid(data["abatement_order_id"])
    assert data["notice_type"] in (
        "ABATEMENT_ORDER", "EDUCATIONAL_ADVISORY", "FINAL_WARNING", "LIEN_INTENT"
    )
    assert data["delivery_method"] in (
        "FIRST_CLASS_MAIL", "CERTIFIED_MAIL", "PERSONAL_SERVICE", "POSTING"
    )
    assert data["status"] in ("PENDING_SERVICE", "SERVED", "UNDELIVERABLE")
    assert is_iso8601_timestamp(data["sent_at"]), TIMESTAMP_HINT


def assert_bait_station(data: dict):
    assert_common_record(data)
    assert is_valid_uuid(data["property_id"])
    assert is_valid_uuid(data["zone_id"])
    assert data["bait_type"] in (
        "ANTICOAGULANT", "SNAP_TRAP", "GLUE_BOARD", "BAIT_BLOCK"
    )
    assert data["status"] in ("ACTIVE", "DAMAGED", "REMOVED")
    assert data["reading_count"] >= 0
    assert data["cumulative_take_pct"] >= 0


def assert_surveillance_reading(data: dict):
    assert_append_only_record(data)
    assert is_valid_uuid(data["bait_station_id"])
    assert 0 <= data["take_pct"] <= 100
    assert data["activity_sign_count"] >= 0
    assert data["station_condition"] in ("INTACT", "DAMAGED", "MISSING")
    assert is_iso8601_timestamp(data["reading_at"]), TIMESTAMP_HINT


def assert_cost_recovery_invoice(data: dict):
    assert_common_record(data)
    assert is_valid_uuid(data["abatement_order_id"])
    assert is_valid_uuid(data["property_id"])
    assert is_valid_uuid(data["owner_id"])
    assert data["billing_status"] in (
        "DRAFT", "APPROVED", "PARTIALLY_PAID", "PAID", "VOID"
    )
    assert data["lien_status"] in ("NONE", "FILED", "RELEASED")
    assert isinstance(data["estimated_total_cents"], int)
    assert data["amount_paid_cents"] >= 0
    assert data["balance_due_cents"] >= 0


# ---------------------------------------------------------------- invariants


def assert_owner_balance_matches_invoices(owner: dict, invoices: list):
    """outstanding_balance_cents and lifetime_paid_cents are recomputed from
    scratch over the owner's invoices (PRD 3.7)."""
    outstanding = sum(
        inv["balance_due_cents"] for inv in invoices
        if inv["billing_status"] in ("APPROVED", "PARTIALLY_PAID")
    )
    lifetime = sum(
        inv["amount_paid_cents"] for inv in invoices
        if inv["billing_status"] in ("APPROVED", "PARTIALLY_PAID", "PAID")
    )
    assert owner["outstanding_balance_cents"] == outstanding, (
        f"outstanding_balance_cents {owner['outstanding_balance_cents']} "
        f"should equal {outstanding}"
    )
    assert owner["lifetime_paid_cents"] == lifetime, (
        f"lifetime_paid_cents {owner['lifetime_paid_cents']} should equal {lifetime}"
    )


def assert_zone_open_complaint_count(zone: dict, complaints: list):
    """open_complaint_count counts complaints outside the four closed statuses."""
    closed = {
        "CLOSED_NO_VIOLATION", "CLOSED_RESOLVED",
        "CLOSED_WITHDRAWN", "CLOSED_DUPLICATE",
    }
    expected = sum(1 for c in complaints if c["status"] not in closed)
    assert zone["open_complaint_count"] == expected, (
        f"open_complaint_count {zone['open_complaint_count']} should equal {expected}"
    )


def assert_posture_matches_index(zone_like: dict):
    """posture follows directly from rodent_index (PRD 3.8)."""
    index = zone_like["rodent_index"]
    if index >= 70.00:
        expected = "HOTSPOT"
    elif index >= 40.00:
        expected = "ELEVATED"
    else:
        expected = "NORMAL"
    assert zone_like["posture"] == expected, (
        f"posture {zone_like['posture']} should be {expected} at index {index}"
    )
