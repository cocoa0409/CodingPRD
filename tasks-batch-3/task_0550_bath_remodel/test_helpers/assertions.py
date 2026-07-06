"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["referral_credit_cents"], int)
    assert data["referral_credit_cents"] >= 0, "referral_credit_cents is floored at 0"


def assert_designer(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["active"], bool)


def assert_crew(data: dict):
    _assert_common(data)
    assert isinstance(data["crew_name"], str) and data["crew_name"]
    assert isinstance(data["max_installs_per_day"], int) and data["max_installs_per_day"] >= 1
    assert isinstance(data["accessibility_certified"], bool)
    assert isinstance(data["active"], bool)


def assert_project(data: dict):
    _assert_common(data)
    assert isinstance(data["customer_id"], str) and data["customer_id"]
    assert data["bathroom_type"] in ("FULL_BATH", "SHOWER_ONLY", "TUB_ONLY")
    assert data["status"] in (
        "LEAD", "DESIGN_SCHEDULED", "DESIGN_COMPLETE", "QUOTED", "SOLD",
        "PERMIT_PENDING", "INSTALL_READY", "INSTALL_SCHEDULED", "INSTALLED", "CANCELLED",
    )
    assert data["permit_status"] in ("NOT_APPLICABLE", "PENDING", "APPROVED", "REJECTED")
    assert data["warranty_status"] in ("NONE", "ACTIVE")


def assert_design_appointment(data: dict):
    _assert_common(data)
    assert isinstance(data["project_id"], str) and data["project_id"]
    assert isinstance(data["designer_id"], str) and data["designer_id"]
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED")


def assert_quote(data: dict):
    _assert_common(data)
    assert isinstance(data["project_id"], str) and data["project_id"]
    assert data["wall_system"] in ("SMOOTH_ACRYLIC", "TILE_LOOK_ACRYLIC", "STONE_LOOK_ACRYLIC")
    assert data["color"] in ("WHITE", "BONE", "GREY", "SANDSTONE")
    assert data["accessibility_addon"] in ("NONE", "GRAB_BARS", "BARRIER_FREE_SHOWER", "WALK_IN_TUB")
    assert data["status"] in ("DRAFT", "PRESENTED", "REVISION_REQUESTED", "ACCEPTED", "SUPERSEDED")
    assert data["financing_status"] in ("NONE", "REQUESTED", "APPROVED", "DECLINED")
    for money in ("system_price_cents", "addon_price_cents", "discount_cents", "net_price_cents"):
        assert isinstance(data[money], int), f"{money} must be an integer count of whole cents"


def assert_install_booking(data: dict):
    _assert_common(data)
    assert isinstance(data["project_id"], str) and data["project_id"]
    assert isinstance(data["crew_id"], str) and data["crew_id"]
    assert data["status"] in ("BOOKED", "COMPLETED", "CANCELLED")


def assert_warranty_claim(data: dict):
    _assert_common(data)
    assert isinstance(data["project_id"], str) and data["project_id"]
    assert data["defect_type"] in ("CRACK", "LEAK", "DISCOLORATION", "HARDWARE_FAILURE")
    assert data["status"] in ("SUBMITTED", "APPROVED", "REJECTED")


def assert_referral(data: dict):
    _assert_common(data)
    assert isinstance(data["referrer_customer_id"], str) and data["referrer_customer_id"]
    assert isinstance(data["referral_code"], str) and data["referral_code"]
    assert data["program_tier"] in ("STANDARD", "PREMIUM")
    assert data["status"] in ("ISSUED", "REGISTERED", "REWARDED", "VOID")
    assert isinstance(data["reward_cents"], int)
