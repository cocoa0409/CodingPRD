"""Entity assertions and domain invariant checkers.

Each assert_{entity} validates the PRD-declared field surface: common fields
(id/created_at/updated_at/version per PRD §2.4) plus the entity's own fields.
Nullable fields are type-checked when present; their presence with a null
value is asserted only where the PRD states the field is carried as null.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer >= 1"
    )


def _assert_opt_str(data: dict, field: str, entity: str):
    if field in data and data[field] is not None:
        assert isinstance(data[field], str), f"{entity}.{field} must be a string or null"


def _assert_opt_int(data: dict, field: str, entity: str):
    if field in data and data[field] is not None:
        assert isinstance(data[field], int), f"{entity}.{field} must be an integer or null"


def _assert_opt_ts(data: dict, field: str, entity: str):
    if field in data and data[field] is not None:
        assert is_iso8601_timestamp(data[field]), (
            f"{entity}.{field} must be an ISO 8601 timestamp or null"
        )


def assert_boat_model(data: dict):
    _assert_common_fields(data, "BoatModel")
    assert isinstance(data["model_code"], str) and data["model_code"]
    assert isinstance(data["model_name"], str) and data["model_name"]
    assert isinstance(data["model_year"], int)
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] > 0
    assert isinstance(data["length_feet"], (int, float)) and data["length_feet"] > 0
    assert isinstance(data["production_hours"], int) and data["production_hours"] > 0
    assert data["status"] in ("ORDERABLE", "DISCONTINUED")


def assert_option_package(data: dict):
    _assert_common_fields(data, "OptionPackage")
    assert is_valid_uuid(data.get("model_id", "")), "OptionPackage.model_id must be a UUID"
    assert isinstance(data["option_code"], str) and data["option_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["price_cents"], int) and data["price_cents"] > 0
    assert isinstance(data["production_hours"], int) and data["production_hours"] >= 0
    _assert_opt_str(data, "incompatible_with_option_id", "OptionPackage")


def assert_dealer(data: dict):
    _assert_common_fields(data, "Dealer")
    assert isinstance(data["dealer_code"], str) and data["dealer_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["region"], str) and data["region"]
    assert data["standing"] in ("PREFERRED", "STANDARD", "PROBATION")
    assert isinstance(data["annual_allocation_quota"], int)
    assert data["annual_allocation_quota"] >= 0
    assert isinstance(data["allocation_used"], int) and data["allocation_used"] >= 0
    assert isinstance(data["floor_plan_limit_cents"], int)
    assert data["floor_plan_limit_cents"] > 0
    assert isinstance(data["floor_plan_utilized_cents"], int)
    assert data["floor_plan_utilized_cents"] >= 0
    assert data["current_rate_tier"] in ("TIER_STANDARD", "TIER_ELEVATED", "TIER_HIGH")


def assert_boat_show_event(data: dict):
    _assert_common_fields(data, "BoatShowEvent")
    assert isinstance(data["event_name"], str) and data["event_name"]
    assert isinstance(data["region"], str) and data["region"]
    assert isinstance(data["start_date"], str) and data["start_date"]
    assert isinstance(data["end_date"], str) and data["end_date"]
    assert data["end_date"] >= data["start_date"], "show end_date must be >= start_date"
    assert isinstance(data["surge_deposit_rate"], (int, float))
    assert isinstance(data["allocation_boost"], int)


def assert_production_run(data: dict):
    _assert_common_fields(data, "ProductionRun")
    assert isinstance(data["plant_line_code"], str) and data["plant_line_code"]
    assert data["season"] in ("PEAK", "SHOULDER", "OFF_PEAK")
    assert isinstance(data["build_week_start"], str) and data["build_week_start"]
    assert isinstance(data["build_week_end"], str) and data["build_week_end"]
    assert data["status"] in ("OPEN", "CLOSED")
    assert isinstance(data["total_carrying_actual_cents"], int)
    assert data["total_carrying_actual_cents"] >= 0
    assert isinstance(data["total_carrying_seasonal_cents"], int)
    assert data["total_carrying_seasonal_cents"] >= 0
    _assert_opt_ts(data, "closed_at", "ProductionRun")


def assert_build_slot(data: dict):
    _assert_common_fields(data, "BuildSlot")
    assert is_valid_uuid(data.get("run_id", "")), "BuildSlot.run_id must be a UUID"
    assert isinstance(data["slot_code"], str) and data["slot_code"]
    assert isinstance(data["capacity_hours"], int) and data["capacity_hours"] > 0
    assert isinstance(data["reserved_hours"], int) and data["reserved_hours"] >= 0
    assert data["reserved_hours"] <= data["capacity_hours"], (
        "reserved_hours must never exceed capacity_hours"
    )
    assert data["status"] in ("OPEN", "RELEASED")


def assert_dealer_order(data: dict):
    _assert_common_fields(data, "DealerOrder")
    assert is_valid_uuid(data.get("dealer_id", "")), "DealerOrder.dealer_id must be a UUID"
    assert is_valid_uuid(data.get("model_id", "")), "DealerOrder.model_id must be a UUID"
    _assert_opt_str(data, "slot_id", "DealerOrder")
    _assert_opt_str(data, "show_event_id", "DealerOrder")
    assert data["source"] in ("RETAIL", "FLEET", "BOAT_SHOW")
    assert data["status"] in (
        "WAITLISTED", "ALLOCATED", "COMMITTED", "IN_PRODUCTION",
        "DELIVERED", "RETAILED", "CANCELLED",
    )
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] > 0
    assert isinstance(data["options_total_cents"], int) and data["options_total_cents"] >= 0
    assert isinstance(data["surcharge_cents"], int) and data["surcharge_cents"] >= 0
    assert isinstance(data["invoice_total_cents"], int) and data["invoice_total_cents"] > 0
    assert isinstance(data["required_deposit_cents"], int)
    assert data["required_deposit_cents"] >= 0
    assert isinstance(data["deposit_paid_cents"], int) and data["deposit_paid_cents"] >= 0
    assert isinstance(data["production_hours"], int) and data["production_hours"] > 0
    _assert_opt_int(data, "cancel_fee_cents", "DealerOrder")
    _assert_opt_int(data, "refund_cents", "DealerOrder")
    # Invoice composition invariant (PRD §3.4): base + options + surcharge.
    assert (
        data["invoice_total_cents"]
        == data["base_price_cents"] + data["options_total_cents"] + data["surcharge_cents"]
    ), "invoice_total_cents must equal base + options + surcharge"


def assert_order_option_line(data: dict):
    """OrderOptionLine deviates from the common field set (PRD §2.4): only
    id and created_at are carried; updated_at and version are absent."""
    assert is_valid_uuid(data.get("id", "")), "OrderOptionLine.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "OrderOptionLine.created_at must be ISO 8601"
    )
    assert "updated_at" not in data, "OrderOptionLine must not carry updated_at"
    assert "version" not in data, "OrderOptionLine must not carry version"
    assert is_valid_uuid(data.get("order_id", "")), "OrderOptionLine.order_id must be a UUID"
    assert is_valid_uuid(data.get("option_package_id", "")), (
        "OrderOptionLine.option_package_id must be a UUID"
    )
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] > 0
    assert isinstance(data["discount_pct_applied"], (int, float))
    assert isinstance(data["line_total_cents"], int) and data["line_total_cents"] > 0


def assert_hull(data: dict):
    _assert_common_fields(data, "Hull")
    assert isinstance(data["hin"], str) and len(data["hin"]) == 12
    assert data["hin"].startswith("BRW"), "HIN must start with the manufacturer code BRW"
    assert isinstance(data["serial_no"], int) and data["serial_no"] >= 1
    assert is_valid_uuid(data.get("order_id", "")), "Hull.order_id must be a UUID"
    assert is_valid_uuid(data.get("slot_id", "")), "Hull.slot_id must be a UUID"
    assert is_valid_uuid(data.get("model_id", "")), "Hull.model_id must be a UUID"
    assert data["certification_status"] in ("UNCERTIFIED", "CERTIFIED", "RECALL_HOLD")
    assert data["delivery_status"] in ("AT_PLANT", "DELIVERED")
    assert is_iso8601_timestamp(data["completed_at"])
    _assert_opt_ts(data, "delivered_at", "Hull")
    assert isinstance(data["created_by_user_id"], str) and data["created_by_user_id"]
    assert isinstance(data["carrying_cost_cents"], int) and data["carrying_cost_cents"] >= 0


def assert_floor_plan_advance(data: dict):
    _assert_common_fields(data, "FloorPlanAdvance")
    assert is_valid_uuid(data.get("dealer_id", "")), "FloorPlanAdvance.dealer_id must be a UUID"
    assert is_valid_uuid(data.get("hull_id", "")), "FloorPlanAdvance.hull_id must be a UUID"
    assert isinstance(data["principal_cents"], int) and data["principal_cents"] > 0
    assert isinstance(data["outstanding_principal_cents"], int)
    assert 0 <= data["outstanding_principal_cents"] <= data["principal_cents"]
    assert isinstance(data["accrued_interest_cents"], int)
    assert data["accrued_interest_cents"] >= 0
    assert data["rate_tier"] in ("TIER_STANDARD", "TIER_ELEVATED", "TIER_HIGH")
    assert isinstance(data["annual_rate"], (int, float)) and data["annual_rate"] > 0
    assert is_iso8601_timestamp(data["opened_at"])
    assert isinstance(data["last_accrual_date"], str) and data["last_accrual_date"]
    assert data["status"] in ("OPEN", "PAID")


def assert_warranty_registration(data: dict):
    _assert_common_fields(data, "WarrantyRegistration")
    assert is_valid_uuid(data.get("hull_id", "")), "WarrantyRegistration.hull_id must be a UUID"
    assert is_valid_uuid(data.get("dealer_id", "")), (
        "WarrantyRegistration.dealer_id must be a UUID"
    )
    assert isinstance(data["retail_sale_date"], str) and data["retail_sale_date"]
    assert is_iso8601_timestamp(data["registered_at"])
    assert isinstance(data["coverage_end_date"], str) and data["coverage_end_date"]
    assert data["status"] == "ACTIVE"


def assert_warranty_claim(data: dict):
    _assert_common_fields(data, "WarrantyClaim")
    assert is_valid_uuid(data.get("registration_id", "")), (
        "WarrantyClaim.registration_id must be a UUID"
    )
    _assert_opt_str(data, "recall_notice_id", "WarrantyClaim")
    assert isinstance(data["defect_description"], str)
    assert isinstance(data["labor_hours"], (int, float)) and data["labor_hours"] > 0
    assert isinstance(data["parts_cents"], int) and data["parts_cents"] >= 0
    assert data["variant_applied"] in ("STANDARD", "RECALL_GOODWILL")
    _assert_opt_int(data, "labor_charge_cents", "WarrantyClaim")
    _assert_opt_int(data, "parts_credit_cents", "WarrantyClaim")
    _assert_opt_int(data, "reimbursement_cents", "WarrantyClaim")
    assert data["status"] in ("SUBMITTED", "APPROVED", "REJECTED")
    if data["status"] == "APPROVED":
        # reimbursement = labor + parts, set at approval (PRD §3.8).
        assert data["reimbursement_cents"] == (
            data["labor_charge_cents"] + data["parts_credit_cents"]
        ), "reimbursement_cents must equal labor_charge_cents + parts_credit_cents"


def assert_recall_campaign(data: dict):
    _assert_common_fields(data, "RecallCampaign")
    assert isinstance(data["campaign_code"], str) and data["campaign_code"]
    assert data["severity"] in ("SAFETY_STOP", "SAFETY_STANDARD", "EMISSIONS")
    assert isinstance(data["model_code"], str) and data["model_code"]
    assert isinstance(data["model_year"], int)
    assert isinstance(data["hin_serial_start"], int) and data["hin_serial_start"] >= 1
    assert isinstance(data["hin_serial_end"], int)
    assert data["hin_serial_end"] >= data["hin_serial_start"]
    assert data["status"] in ("DRAFT", "ISSUED", "CLOSED")
    _assert_opt_ts(data, "issued_at", "RecallCampaign")
    assert isinstance(data["notice_count"], int) and data["notice_count"] >= 0
    assert isinstance(data["open_notice_count"], int) and data["open_notice_count"] >= 0


def assert_recall_notice(data: dict):
    _assert_common_fields(data, "RecallNotice")
    assert is_valid_uuid(data.get("campaign_id", "")), "RecallNotice.campaign_id must be a UUID"
    assert is_valid_uuid(data.get("hull_id", "")), "RecallNotice.hull_id must be a UUID"
    assert data["status"] in ("NOTIFIED", "REMEDIED")
    assert is_iso8601_timestamp(data["notified_at"])
    _assert_opt_ts(data, "remedied_at", "RecallNotice")
    if data.get("remedy_path") is not None:
        assert data["remedy_path"] in ("WARRANTY_CLAIM", "PLANT_REMEDY")
