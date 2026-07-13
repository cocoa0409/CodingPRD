"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_common_fields(data: dict):
    """id + created_at + updated_at + version for a standard resource."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_applicant(data: dict):
    assert_common_fields(data)
    assert isinstance(data["company_name"], str) and data["company_name"]
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]


def assert_street_segment(data: dict):
    assert_common_fields(data)
    assert data["zone_class"] in ("RESIDENTIAL", "COMMERCIAL", "ARTERIAL")
    assert isinstance(data["active_lane_closure_count"], int)
    assert data["active_lane_closure_count"] >= 0


def assert_sidewalk_span(data: dict):
    assert_common_fields(data)
    assert data["side"] in ("NORTH", "SOUTH", "EAST", "WEST")


def assert_permit(data: dict):
    assert_common_fields(data)
    assert data["status"] in (
        "DRAFT", "UNDER_REVIEW", "RETURNED_FOR_REVISION", "APPROVED",
        "ISSUED", "CLOSED_OUT", "EXPIRED", "REVOKED",
    )
    assert data["primary_obstruction_type"] in ("LANE", "FULL_ROAD", "SIDEWALK")
    assert isinstance(data["cumulative_penalty_cents"], int)


def assert_traffic_control_plan(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("SUBMITTED", "APPROVED", "REJECTED")


def assert_restoration_bond(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("POSTED", "RELEASED", "FORFEITED")


def assert_bond_money_conserved(data: dict):
    """§3.3 invariant: held + refunded + forfeited == posted."""
    total = data["held_cents"] + data["refunded_cents"] + data["forfeited_cents"]
    assert total == data["posted_cents"], (
        f"held+refunded+forfeited ({total}) must equal posted_cents ({data['posted_cents']})"
    )


def assert_lane_closure(data: dict):
    assert_common_fields(data)
    assert data["status"] in (
        "PLANNED", "ACTIVE", "RESTORATION_PENDING", "RESTORED",
        "RESTORATION_REJECTED", "VOIDED",
    )


def assert_sidewalk_obstruction(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "RESTORED", "VOIDED")


def assert_encroachment_agreement(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("PROPOSED", "EXECUTED")


def assert_violation_notice(data: dict):
    """Append-only record: only id + created_at (no updated_at / version)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["penalty_cents"], int)
