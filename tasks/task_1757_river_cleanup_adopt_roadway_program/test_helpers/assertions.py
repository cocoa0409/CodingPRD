"""Entity assertions and domain invariant checkers (PRD §2.4, §2.7, §3)."""
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be a positive integer"
    )


def assert_adopter_group(data: dict):
    _assert_common(data, "AdopterGroup")
    assert isinstance(data["name"], str) and data["name"]
    assert data["org_type"] in {"CIVIC", "BUSINESS", "SCHOOL", "FAITH", "OTHER"}
    assert isinstance(data["contact_name"], str) and data["contact_name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]


def assert_road_segment(data: dict):
    _assert_common(data, "RoadSegment")
    assert isinstance(data["route_name"], str) and data["route_name"]
    assert isinstance(data["mile_marker_start"], (int, float))
    assert isinstance(data["mile_marker_end"], (int, float))
    assert data["mile_marker_end"] > data["mile_marker_start"]
    assert data["segment_type"] in {"ROADWAY", "RIVERBANK"}
    assert isinstance(data["water_adjacent"], bool)
    assert data["status"] in {"AVAILABLE", "ADOPTED"}
    # mile_length is the 2dp half-up difference between the markers (PRD §2.8)
    assert abs(
        data["mile_length"] - round(data["mile_marker_end"] - data["mile_marker_start"] + 1e-9, 2)
    ) < 0.005, "mile_length must equal the 2dp difference of the markers"


def assert_adoption_agreement(data: dict):
    _assert_common(data, "AdoptionAgreement")
    assert is_valid_uuid(data.get("group_id", "")), "group_id must be a UUID"
    assert is_valid_uuid(data.get("segment_id", "")), "segment_id must be a UUID"
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert data["status"] in {
        "PENDING_REVIEW", "ACTIVE", "SUSPENDED", "RENEWAL_REVIEW",
        "EXPIRED", "TERMINATED", "REJECTED",
    }
    assert data["standing"] in {"NOT_EVALUATED", "COMPLIANT", "NON_COMPLIANT"}
    assert isinstance(data["renewal_count"], int) and data["renewal_count"] >= 0
    assert isinstance(data["cleanups_completed_in_window"], int)


def assert_cleanup_event(data: dict):
    _assert_common(data, "CleanupEvent")
    assert is_valid_uuid(data.get("agreement_id", "")), "agreement_id must be a UUID"
    assert isinstance(data["scheduled_date"], str) and data["scheduled_date"]
    assert isinstance(data["expected_volunteers"], int) and data["expected_volunteers"] >= 1
    assert data["status"] in {
        "SCHEDULED", "BRIEFING_DONE", "POSTPONED",
        "COMPLETED", "CANCELLED", "NO_SHOW",
    }
    assert isinstance(data["briefing_attendee_count"], int)
    assert isinstance(data["postpone_count"], int) and data["postpone_count"] >= 0


def assert_volunteer_waiver(data: dict):
    _assert_common(data, "VolunteerWaiver")
    assert is_valid_uuid(data.get("agreement_id", "")), "agreement_id must be a UUID"
    assert isinstance(data["volunteer_full_name"], str) and data["volunteer_full_name"]
    assert isinstance(data["dob"], str) and data["dob"]
    assert isinstance(data["is_minor"], bool)
    assert isinstance(data["guardian_consent"], bool)
    assert data["status"] in {"ACTIVE", "EXPIRED", "REVOKED"}
    assert isinstance(data["signed_date"], str) and data["signed_date"]
    assert isinstance(data["expiry_date"], str) and data["expiry_date"]


def assert_supply_depot(data: dict):
    _assert_common(data, "SupplyDepot")
    assert isinstance(data["name"], str) and data["name"]
    for field in (
        "bags_on_hand", "vests_on_hand", "grabbers_on_hand",
        "vests_pool_total", "grabbers_pool_total",
        "lost_vests_total", "lost_grabbers_total",
    ):
        assert isinstance(data[field], int) and data[field] >= 0, (
            f"SupplyDepot.{field} must be a non-negative integer"
        )


def assert_supply_distribution(data: dict):
    _assert_common(data, "SupplyDistribution")
    assert is_valid_uuid(data.get("event_id", "")), "event_id must be a UUID"
    assert is_valid_uuid(data.get("depot_id", "")), "depot_id must be a UUID"
    assert data["status"] in {"ISSUED", "PARTIALLY_RETURNED", "RECONCILED"}
    for field in (
        "vests_issued", "grabbers_issued", "bags_issued",
        "vests_returned", "grabbers_returned", "lost_vests", "lost_grabbers",
    ):
        assert isinstance(data[field], int) and data[field] >= 0, (
            f"SupplyDistribution.{field} must be a non-negative integer"
        )


def assert_debris_report(data: dict):
    """Debris reports are immutable: only id + created_at common fields (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "DebrisReport.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "DebrisReport.created_at must be ISO 8601"
    )
    assert "version" not in data, "DebrisReport must not carry a version field"
    assert "updated_at" not in data, "DebrisReport must not carry an updated_at field"
    assert data["weight_method"] in {"MEASURED", "ESTIMATED"}
    assert isinstance(data["official_weight_lbs"], (int, float))
    assert isinstance(data["material_breakdown"], list) and data["material_breakdown"]
    for line in data["material_breakdown"]:
        assert line["material_type"] in {
            "GENERAL_TRASH", "RECYCLABLES", "METALS", "YARD_WASTE", "OTHER",
        }
        assert isinstance(line["line_weight_lbs"], (int, float))


def assert_hazard_report(data: dict):
    _assert_common(data, "HazardReport")
    assert is_valid_uuid(data.get("segment_id", "")), "segment_id must be a UUID"
    assert data["hazard_type"] in {
        "CHEMICAL_CONTAINER", "SYRINGES", "PROPANE_TANK", "ASBESTOS", "OTHER",
    }
    assert isinstance(data["description"], str) and data["description"]
    assert isinstance(data["location_note"], str) and data["location_note"]
    assert data["status"] in {"REPORTED", "ACKNOWLEDGED", "RESOLVED"}


def assert_sign_recognition(data: dict):
    _assert_common(data, "SignRecognition")
    assert is_valid_uuid(data.get("agreement_id", "")), "agreement_id must be a UUID"
    assert isinstance(data["sign_text"], str) and 1 <= len(data["sign_text"]) <= 60
    assert data["status"] in {"REQUESTED", "INSTALLED", "REMOVED"}


def assert_program_metrics(data: dict):
    assert isinstance(data["active_agreements"], int) and data["active_agreements"] >= 0
    assert isinstance(data["adopted_miles"], (int, float))
    assert isinstance(data["available_miles"], (int, float))
    assert isinstance(data["total_debris_lbs"], (int, float))
    assert isinstance(data["completed_cleanups"], int) and data["completed_cleanups"] >= 0
    assert isinstance(data["open_hazards"], int) and data["open_hazards"] >= 0


def assert_depot_returnables_conserved(depot: dict, distributions: list):
    """PRD §2.7 conservation invariant:
    on_hand + outstanding (over ISSUED/PARTIALLY_RETURNED) + lost == pool_total,
    per returnable item (vests, grabbers)."""
    for item in ("vests", "grabbers"):
        outstanding = sum(
            d[f"{item}_issued"] - d[f"{item}_returned"] - d[f"lost_{item}"]
            for d in distributions
            if d.get("status") in ("ISSUED", "PARTIALLY_RETURNED")
        )
        lhs = depot[f"{item}_on_hand"] + outstanding + depot[f"lost_{item}_total"]
        assert lhs == depot[f"{item}_pool_total"], (
            f"Returnable conservation broken for {item}: "
            f"{depot[f'{item}_on_hand']} + {outstanding} + "
            f"{depot[f'lost_{item}_total']} != {depot[f'{item}_pool_total']}"
        )
