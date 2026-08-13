"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, f"{entity}.version must be a positive int"


def assert_property(data: dict):
    _assert_common(data, "Property")
    assert isinstance(data.get("name"), str) and data["name"]
    assert isinstance(data.get("address"), str) and data["address"]
    assert data.get("posture") in ("STANDARD", "ELEVATED", "RESTRICTED")
    assert isinstance(data.get("open_bed_bug_case_count"), int) and data["open_bed_bug_case_count"] >= 0


def assert_contract(data: dict):
    _assert_common(data, "ServiceContract")
    assert isinstance(data.get("vendor_name"), str) and data["vendor_name"]
    assert isinstance(data.get("scope_pest_types"), list) and len(data["scope_pest_types"]) >= 1
    for pt in data["scope_pest_types"]:
        assert pt in ("ANTS", "ROACHES", "RODENTS", "BED_BUGS", "TERMITES")
    assert data.get("status") in ("DRAFT", "ACTIVE", "SUSPENDED", "TERMINATED", "EXPIRED")
    assert isinstance(data.get("monthly_budget_cents"), int)
    assert isinstance(data.get("spent_cents"), int) and data["spent_cents"] >= 0


def assert_unit(data: dict):
    _assert_common(data, "Unit")
    assert isinstance(data.get("unit_number"), str) and data["unit_number"]
    assert isinstance(data.get("floor"), int) and data["floor"] >= 1
    assert isinstance(data.get("stack_index"), int) and data["stack_index"] >= 1
    assert isinstance(data.get("bedrooms"), int) and data["bedrooms"] >= 0
    assert data.get("operational_status") in ("OCCUPIED", "VACANT", "RENOVATION")
    assert data.get("pest_flag") in ("CLEAR", "MONITORING", "INFESTED")
    assert isinstance(data.get("no_access_strikes"), int) and data["no_access_strikes"] >= 0


def assert_lease(data: dict):
    _assert_common(data, "Lease")
    assert isinstance(data.get("unit_id"), str)
    assert isinstance(data.get("pest_addendum_signed"), bool)
    assert data.get("status") in ("ACTIVE", "ENDED")
    assert isinstance(data.get("outstanding_balance_cents"), int) and data["outstanding_balance_cents"] >= 0
    assert isinstance(data.get("delinquent"), bool)
    assert data["delinquent"] == (data["outstanding_balance_cents"] > 0), (
        "delinquent must be true exactly when outstanding_balance_cents > 0"
    )


def assert_resident(data: dict):
    _assert_common(data, "Resident")
    assert isinstance(data.get("unit_id"), str)
    assert isinstance(data.get("lease_id"), str)
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("email"), str) and data["email"]


def assert_technician(data: dict):
    _assert_common(data, "Technician")
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("vendor_name"), str) and data["vendor_name"]
    assert isinstance(data.get("active"), bool)
    assert isinstance(data.get("booked_minutes"), int) and data["booked_minutes"] >= 0


def assert_inspection(data: dict):
    _assert_common(data, "Inspection")
    assert isinstance(data.get("unit_id"), str)
    assert data.get("kind") in ("ROUTINE", "INITIAL", "FOLLOW_UP")
    assert data.get("pest_type") in ("ANTS", "ROACHES", "RODENTS", "BED_BUGS", "TERMITES")
    assert data.get("status") in ("SCHEDULED", "COMPLETED", "NO_ACCESS", "CANCELLED")
    if data["status"] == "COMPLETED":
        assert data.get("severity") in ("NONE", "LOW", "MODERATE", "SEVERE")
        assert is_iso8601_timestamp(data.get("completed_at", ""))


def assert_treatment(data: dict):
    _assert_common(data, "Treatment")
    assert isinstance(data.get("unit_id"), str)
    assert isinstance(data.get("technician_id"), str)
    assert data.get("treatment_type") in ("CHEMICAL", "HEAT", "EXCLUSION", "TRAPPING")
    assert data.get("status") in (
        "SCHEDULED", "PREP_NOTIFIED", "PREP_VERIFIED", "NON_COMPLIANT", "COMPLETED", "CANCELLED",
    )
    assert isinstance(data.get("planned_minutes"), int) and data["planned_minutes"] >= 1
    assert isinstance(data.get("reschedule_count"), int) and 0 <= data["reschedule_count"] <= 2


def assert_bed_bug_case(data: dict):
    _assert_common(data, "BedBugCase")
    assert isinstance(data.get("unit_id"), str)
    assert data.get("status") in ("OPEN", "TREATING", "MONITORING", "CLEARED", "REOPENED")
    assert isinstance(data.get("consecutive_negative_count"), int) and data["consecutive_negative_count"] >= 0
    if data["status"] == "CLEARED":
        assert is_iso8601_timestamp(data.get("cleared_at", "")), "CLEARED case must carry cleared_at"


def assert_furniture_disposal(data: dict):
    _assert_common(data, "FurnitureDisposal")
    assert isinstance(data.get("bed_bug_case_id"), str)
    assert isinstance(data.get("item_description"), str) and data["item_description"]
    assert isinstance(data.get("quantity"), int) and data["quantity"] >= 1
    assert data.get("status") in ("PENDING", "VERIFIED", "REJECTED")
    if data["status"] == "VERIFIED":
        assert is_iso8601_timestamp(data.get("verified_at", "")), "VERIFIED disposal must carry verified_at"


def assert_chargeback(data: dict):
    _assert_common(data, "Chargeback")
    assert isinstance(data.get("lease_id"), str)
    assert data.get("kind") in (
        "NON_COMPLIANCE_FEE", "REPEAT_INFESTATION", "HEAT_SURCHARGE", "FURNITURE_DISPOSAL", "LATE_FEE",
    )
    assert data.get("status") in ("ASSESSED", "DISPUTED", "UPHELD", "WAIVED", "BILLED", "PAID")
    assert isinstance(data.get("provisional_amount_cents"), int) and data["provisional_amount_cents"] >= 0
    assert isinstance(data.get("assessed_by"), str) and data["assessed_by"]
    assert is_iso8601_timestamp(data.get("assessed_at", ""))
    if data["status"] in ("BILLED", "PAID"):
        assert isinstance(data.get("final_amount_cents"), int), "BILLED/PAID must carry final_amount_cents"
        assert is_iso8601_timestamp(data.get("billed_at", ""))
    if data["status"] == "PAID":
        assert is_iso8601_timestamp(data.get("paid_at", ""))


def assert_claim_packet(data: dict):
    _assert_common(data, "ClaimPacket")
    assert isinstance(data.get("property_id"), str)
    assert isinstance(data.get("claim_reference"), str) and data["claim_reference"]
    assert isinstance(data.get("pinned_references"), list)
    for ref in data["pinned_references"]:
        assert ref.get("entity_type") in ("Inspection", "Treatment", "BedBugCase")
        assert is_valid_uuid(ref.get("entity_id", ""))
        assert isinstance(ref.get("version"), int)
    assert data.get("status") in ("DRAFT", "FINALIZED", "DISCARDED")
    if data["status"] == "FINALIZED":
        assert is_iso8601_timestamp(data.get("finalized_at", ""))
