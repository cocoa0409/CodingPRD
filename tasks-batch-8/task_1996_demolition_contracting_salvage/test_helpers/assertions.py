"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_iso8601_instant(actual: str, expected_iso: str):
    """Assert two ISO 8601 UTC timestamps denote the same instant.

    PRD §2.4 pins the *instant* of server-stamped timestamps ("always taken
    from this logical clock") but pins the three-fractional-digit string form
    only for `created_at`/`updated_at` (§2.4) and `api_request_timestamp`
    (§2.2). Stamped fields (`activated_at`, `expires_at`, `delivered_at`,
    `recorded_at`, ...) may therefore legitimately serialize as
    `2026-08-01T09:00:00Z` or `2026-08-01T09:00:00.000Z`; only the instant is
    asserted here.
    """

    def _parse(value):
        assert isinstance(value, str), f"expected ISO 8601 string, got {value!r}"
        text = value.strip()
        if text.endswith(("Z", "z")):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        assert dt.tzinfo is not None, f"timestamp lacks timezone: {value!r}"
        return dt.astimezone(timezone.utc)

    assert _parse(actual) == _parse(expected_iso), (
        f"instant mismatch: {actual!r} != {expected_iso!r}"
    )

PROJECT_STATUSES = [
    "DRAFT", "SURVEY_PHASE", "PRECONDITIONS_PENDING", "RELEASED",
    "DEMOLITION_ACTIVE", "DEBRIS_CLEARANCE", "BACKFILL_PHASE",
    "FINAL_REVIEW", "CLOSED",
]


def assert_project(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert isinstance(data.get("name"), str) and len(data["name"]) > 0
    assert data.get("status") in PROJECT_STATUSES
    assert data.get("work_posture") in ["WORKABLE", "STOPPED"]
    assert data.get("diversion_tier") in ["STANDARD", "SILVER", "GOLD"]
    for counter in ("in_transit_tons", "landfill_tons", "diverted_tons", "removed_tons"):
        assert data.get(counter) is not None, f"{counter} must be present"


def assert_structure_survey(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert data.get("status") in ["IN_PROGRESS", "COMPLETE"]
    assert isinstance(data.get("structure_label"), str)


def assert_abatement(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data.get("status") in [
        "IDENTIFIED", "ABATEMENT_ACTIVE", "CLEARANCE_PENDING",
        "CLEARANCE_CERTIFIED", "CLEARANCE_FAILED",
    ]
    assert data.get("material_type") in ["ASBESTOS", "LEAD_PAINT", "PCB", "MERCURY", "OTHER"]


def assert_utility_disconnect(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data.get("disconnect_status") in ["SCHEDULED", "REPORTED_DISCONNECTED"]
    assert data.get("verification_status") in [
        "UNVERIFIED", "FIELD_VERIFIED", "VERIFICATION_REJECTED", "CONFIRMED",
    ]


def assert_permit(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data.get("status") in [
        "DRAFT", "UNDER_REVIEW", "REVISION_REQUIRED", "APPROVED",
        "ACTIVE", "REJECTED", "EXPIRED",
    ]
    assert isinstance(data.get("fee_cents"), int), "fee_cents must be integer cents"


def assert_engineering_survey(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data.get("status") in ["DRAFT", "SUBMITTED", "CERTIFIED"]
    assert isinstance(data.get("revision_number"), int) and data["revision_number"] >= 1


def assert_salvage_manifest(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data.get("status") in ["DRAFT", "FINALIZED", "AMENDED"]
    assert data.get("valuation_policy") in ["OPTIMISTIC", "CONSERVATIVE"]
    assert isinstance(data.get("optimistic_total_cents"), int)
    assert isinstance(data.get("conservative_total_cents"), int)
    assert isinstance(data.get("net_credit_cents"), int)


def assert_salvage_item(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data.get("material") in ["STEEL", "COPPER", "BRICK", "TIMBER", "CONCRETE", "FIXTURES"]
    assert isinstance(data.get("extended_value_cents"), int)


def assert_notification(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data.get("status") in ["PENDING_DELIVERY", "DELIVERED", "VOIDED"]


def assert_dust_log(data: dict):
    """Append-only event: id + created_at only; NO updated_at, NO version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only event must not carry updated_at"
    assert "version" not in data, "append-only event must not carry version"
    assert data.get("reading_type") in ["PM25", "PM10", "NOISE_DB"]
    assert isinstance(data.get("is_exceedance"), bool)


def assert_debris_ticket(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data.get("status") in [
        "MANIFESTED", "RECEIVED", "DISPUTED", "RECONCILED", "VOIDED", "CANCELLED",
    ]


def assert_backfill_plan(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data.get("status") in [
        "DRAFT", "APPROVED", "COMPACTION_VERIFIED", "EROSION_VERIFIED", "COMPLETE",
    ]


def assert_final_inspection(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data.get("status") in ["SCHEDULED", "PASSED", "FAILED", "CANCELLED"]


def assert_mass_invariant(project: dict, total_gross_ever_created: float):
    """PRD §3.8 mass invariant: in_transit + landfill + diverted + removed
    always equals the sum of gross_tons over every ticket ever created."""
    accounted = (
        project["in_transit_tons"]
        + project["landfill_tons"]
        + project["diverted_tons"]
        + project["removed_tons"]
    )
    assert accounted == total_gross_ever_created, (
        f"Mass invariant violated: accounted {accounted} != created {total_gross_ever_created}"
    )
