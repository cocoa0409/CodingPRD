"""Entity assertions and domain invariant checkers (PRD §2.2, §2.5)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(str(data.get("id", ""))), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(str(data.get("created_at", ""))), \
        f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(str(data.get("updated_at", ""))), \
        f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"


def assert_application(data: dict):
    _assert_common_fields(data, "VolunteerApplication")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["date_of_birth"], str) and data["date_of_birth"]
    assert data["status"] in [
        "SUBMITTED", "IN_REVIEW", "NEEDS_INFO", "APPROVED", "REJECTED", "WITHDRAWN",
    ]


def assert_volunteer(data: dict):
    _assert_common_fields(data, "Volunteer")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["date_of_birth"], str) and data["date_of_birth"]
    assert data["service_status"] in ["ONBOARDING", "ACTIVE", "SUSPENDED", "SEPARATED"]
    assert data["compliance_posture"] in ["CLEAR", "RESTRICTED", "FROZEN"]
    assert data["recognition_tier"] in ["NONE", "BRONZE", "SILVER", "GOLD", "PRESIDENT"]
    assert isinstance(data["is_junior_today"], bool)


def assert_clearance(data: dict):
    _assert_common_fields(data, "Clearance")
    assert data["clearance_type"] in ["BACKGROUND", "HEALTH_TB", "HEALTH_FLU"]
    assert data["status"] in ["SUBMITTED", "CLEARED", "REJECTED", "EXPIRED", "REVOKED"]
    assert isinstance(data["volunteer_id"], str) and data["volunteer_id"]
    assert isinstance(data["submitted_by_user_id"], str) and data["submitted_by_user_id"]


def assert_department(data: dict):
    _assert_common_fields(data, "Department")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["head_user_id"], str) and data["head_user_id"]
    assert isinstance(data["junior_allowed"], bool)


def assert_role(data: dict):
    _assert_common_fields(data, "VolunteerRole")
    assert isinstance(data["name"], str) and data["name"]
    assert data["category"] in [
        "PATIENT_FACING", "GIFT_SHOP", "CLERICAL", "FUNDRAISING", "COMMUNITY",
    ]
    assert isinstance(data["minimum_age"], int)
    assert isinstance(data["can_supervise_juniors"], bool)
    assert isinstance(data["required_training_codes"], list)


def assert_request(data: dict):
    _assert_common_fields(data, "DepartmentRequest")
    assert isinstance(data["department_id"], str) and data["department_id"]
    assert isinstance(data["role_id"], str) and data["role_id"]
    assert isinstance(data["slots_needed"], int) and data["slots_needed"] >= 1
    assert isinstance(data["slots_filled"], int) and data["slots_filled"] >= 0
    assert data["status"] in ["DRAFT", "OPEN", "FILLED", "CLOSED", "CANCELLED"]


def assert_placement(data: dict):
    _assert_common_fields(data, "Placement")
    assert isinstance(data["request_id"], str) and data["request_id"]
    assert isinstance(data["volunteer_id"], str) and data["volunteer_id"]
    assert data["status"] in ["OFFERED", "COUNTERED", "ACCEPTED", "DECLINED", "RESCINDED"]
    assert isinstance(data["counter_rounds"], int) and 0 <= data["counter_rounds"] <= 2


def assert_training_record(data: dict):
    _assert_common_fields(data, "TrainingRecord")
    assert isinstance(data["volunteer_id"], str) and data["volunteer_id"]
    assert isinstance(data["training_code"], str) and data["training_code"]
    assert data["recurrence"] in ["ONE_TIME", "ANNUAL"]
    assert data["status"] in ["PENDING", "VALID", "EXPIRED"]


def assert_shift(data: dict):
    _assert_common_fields(data, "Shift")
    assert isinstance(data["department_id"], str) and data["department_id"]
    assert isinstance(data["role_id"], str) and data["role_id"]
    assert is_iso8601_timestamp(str(data.get("start_at", "")))
    assert is_iso8601_timestamp(str(data.get("end_at", "")))
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["filled_count"], int) and data["filled_count"] >= 0
    assert data["status"] in ["SCHEDULED", "PUBLISHED", "COMPLETED", "CANCELLED"]


def assert_assignment(data: dict):
    _assert_common_fields(data, "ShiftAssignment")
    assert isinstance(data["shift_id"], str) and data["shift_id"]
    assert isinstance(data["volunteer_id"], str) and data["volunteer_id"]
    assert data["status"] in [
        "WAITLISTED", "SIGNED_UP", "CONFIRMED", "COMPLETED", "NO_SHOW", "CANCELLED",
    ]
    assert is_iso8601_timestamp(str(data.get("signed_up_at", "")))


def assert_hour_entry(data: dict):
    _assert_common_fields(data, "HourEntry")
    assert isinstance(data["volunteer_id"], str) and data["volunteer_id"]
    assert isinstance(data["service_date"], str) and data["service_date"]
    assert isinstance(data["minutes"], int) and 1 <= data["minutes"] <= 960
    assert data["service_category"] in [
        "PATIENT_FACING", "GIFT_SHOP", "CLERICAL", "FUNDRAISING", "COMMUNITY",
    ]
    assert data["status"] in ["PENDING", "APPROVED", "REJECTED", "REVERSED"]


def assert_badge(data: dict):
    _assert_common_fields(data, "Badge")
    assert isinstance(data["volunteer_id"], str) and data["volunteer_id"]
    assert isinstance(data["badge_number"], str) and data["badge_number"].startswith("BDG-")
    assert data["status"] in ["PENDING", "ISSUED", "SUSPENDED", "REVOKED"]


def assert_campaign(data: dict):
    _assert_common_fields(data, "FundraisingCampaign")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["goal_cents"], int) and data["goal_cents"] >= 0
    assert isinstance(data["promo_discount_pct"], int)
    assert data["status"] in ["DRAFT", "ACTIVE", "CLOSED", "RECONCILED"]
    for field in ("gross_receipts_cents", "raised_cents", "net_proceeds_cents",
                  "disbursed_cents"):
        assert isinstance(data[field], int), f"campaign.{field} must be integer cents"


def assert_item(data: dict):
    _assert_common_fields(data, "GiftShopItem")
    assert isinstance(data["sku"], str) and data["sku"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 0
    assert isinstance(data["unit_cost_cents"], int) and data["unit_cost_cents"] >= 0
    assert data["unit_cost_cents"] <= data["unit_price_cents"]
    assert isinstance(data["stock_on_hand"], int) and data["stock_on_hand"] >= 0
    assert isinstance(data["is_active"], bool)


def assert_sale(data: dict):
    _assert_common_fields(data, "GiftShopSale")
    assert isinstance(data["cashier_volunteer_id"], str) and data["cashier_volunteer_id"]
    assert isinstance(data["lines"], list) and len(data["lines"]) >= 1
    assert isinstance(data["total_cents"], int) and data["total_cents"] >= 0
    assert isinstance(data["discount_pct_applied"], int)
    assert isinstance(data["tendered_cents"], int)
    assert isinstance(data["change_cents"], int)
    assert data["status"] in ["COMPLETED", "VOIDED"]


def assert_recognition_event(data: dict):
    """Append-only log rows: id + created_at only, NO updated_at, NO version (PRD §2.5)."""
    assert is_valid_uuid(str(data.get("id", ""))), "RecognitionEvent.id must be a valid UUID"
    assert is_iso8601_timestamp(str(data.get("created_at", ""))), \
        "RecognitionEvent.created_at must be ISO 8601"
    assert "version" not in data, "RecognitionEvent must not carry version"
    assert "updated_at" not in data, "RecognitionEvent must not carry updated_at"
    assert isinstance(data["volunteer_id"], str) and data["volunteer_id"]
    assert data["event_type"] in ["TIER_INCREASED", "TIER_DECREASED"]
    assert data["tier"] in ["NONE", "BRONZE", "SILVER", "GOLD", "PRESIDENT"]


def assert_slot_fill_invariant(request_data: dict, accepted_count: int):
    """PRD §3.3 standing invariant: slots_filled == count of ACCEPTED placements."""
    assert request_data["slots_filled"] == accepted_count, (
        f"slots_filled {request_data['slots_filled']} != ACCEPTED count {accepted_count}"
    )
