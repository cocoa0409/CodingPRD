"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID without prefix"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be a positive integer"
    )


def assert_customer(data: dict):
    _assert_common(data, "Customer")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["site_code"], str) and data["site_code"]
    assert isinstance(data["credit_limit_cents"], int) and data["credit_limit_cents"] >= 0
    assert isinstance(data["open_exposure_cents"], int) and data["open_exposure_cents"] >= 0
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_packing_job(data: dict):
    _assert_common(data, "PackingJob")
    assert is_valid_uuid(data.get("customer_id", "")), "PackingJob.customer_id must be a UUID"
    assert data["mode"] in ("SHOP", "ONSITE")
    assert data["incoterm"] in ("EXW", "FOB", "DDP")
    assert data["status"] in (
        "QUOTED", "DESIGN", "PACKING", "READY_TO_LOAD", "LOADED",
        "SHIPPED", "DELIVERED", "CLOSED", "CANCELLED",
    )
    assert data["readiness_posture"] in ("READY", "BLOCKED")
    assert isinstance(data["total_board_feet"], int)
    assert isinstance(data["total_chargeable_weight_kg"], (int, float))
    assert isinstance(data["estimated_labor_hours"], int)
    assert isinstance(data["quoted_price_cents"], int)


def assert_item(data: dict):
    _assert_common(data, "Item")
    assert is_valid_uuid(data.get("packing_job_id", "")), "Item.packing_job_id must be a UUID"
    assert isinstance(data["description"], str)
    for dim in ("length_cm", "width_cm", "height_cm", "weight_kg"):
        assert isinstance(data[dim], (int, float)) and data[dim] > 0, f"{dim} must be > 0"
    assert data["fragile_class"] in ("STANDARD", "DELICATE", "HIGHLY_FRAGILE")
    assert isinstance(data["hazmat"], bool)
    assert data["battery_in_equipment"] in ("NONE", "LITHIUM_ION", "LITHIUM_METAL", "WET_CELL")
    assert isinstance(data["declared_value_cents"], int) and data["declared_value_cents"] >= 0
    assert isinstance(data["volume_m3"], (int, float))
    assert isinstance(data["dimensional_weight_kg"], (int, float))
    assert isinstance(data["chargeable_weight_kg"], (int, float))
    assert data["status"] in ("CAPTURED", "DESIGN_APPROVED", "PACKED", "SEALED")


def assert_crate_design(data: dict):
    _assert_common(data, "CrateDesign")
    assert is_valid_uuid(data.get("item_id", "")), "CrateDesign.item_id must be a UUID"
    assert isinstance(data["revision"], int) and data["revision"] >= 1
    assert data["clearance_cm"] in (5, 10, 15)
    assert data["thickness_cm"] in (1.2, 1.8, 2.5)
    assert isinstance(data["board_feet_required"], int) and data["board_feet_required"] > 0
    assert isinstance(data["tare_weight_kg"], (int, float))
    assert data["shock_indicator_g"] in (75, 50, 25)
    assert data["moisture_barrier_required"] in ("NONE", "VCI", "VACUUM_SEALED")
    assert data["status"] in ("DRAFT", "IN_REVIEW", "APPROVED", "REJECTED", "LOCKED", "SUPERSEDED")


def assert_wood_batch(data: dict):
    _assert_common(data, "WoodBatch")
    assert isinstance(data["ht_certificate_no"], str) and data["ht_certificate_no"]
    assert data["treatment_type"] in ("HT", "KD_HT")
    assert isinstance(data["received_board_feet"], int) and data["received_board_feet"] > 0
    assert isinstance(data["stamps_acquired"], int) and data["stamps_acquired"] >= 0
    for f in ("reserved_board_feet", "consumed_board_feet", "scrapped_board_feet",
              "available_board_feet", "stamps_applied", "stamps_voided", "stamps_available"):
        assert isinstance(data[f], int), f"WoodBatch.{f} must be an integer"
    assert data["status"] in ("ACTIVE", "SUSPENDED", "DEPLETED", "EXPIRED")


def assert_crate(data: dict):
    _assert_common(data, "Crate")
    assert is_valid_uuid(data.get("item_id", "")), "Crate.item_id must be a UUID"
    assert is_valid_uuid(data.get("packing_job_id", "")), "Crate.packing_job_id must be a UUID"
    assert is_valid_uuid(data.get("design_id", "")), "Crate.design_id must be a UUID"
    assert isinstance(data["tare_weight_kg"], (int, float))
    assert isinstance(data["gross_weight_kg"], (int, float))
    assert isinstance(data["external_volume_m3"], (int, float))
    assert isinstance(data["freight_density_kg_m3"], (int, float))
    assert data["freight_class"] in ("55", "60", "65", "70", "77.5", "85", "92.5", "125")
    assert isinstance(data["compliance_hold"], bool)
    assert data["status"] in (
        "PLANNED", "BUILT", "PACKED", "SEALED", "REOPENED",
        "LOADED", "SHIPPED", "DELIVERED", "VOIDED",
    )


def assert_hazmat_declaration(data: dict):
    _assert_common(data, "HazmatDeclaration")
    assert is_valid_uuid(data.get("item_id", "")), "HazmatDeclaration.item_id must be a UUID"
    assert isinstance(data["un_number"], str) and data["un_number"]
    assert data["dg_class"] in ("1", "2.1", "3", "4.1", "5.1", "6.1", "8", "9")
    assert data["packing_group"] in ("I", "II", "III")
    assert data["battery_type"] in ("NONE", "LITHIUM_ION", "LITHIUM_METAL", "WET_CELL")
    assert isinstance(data["prepared_by_user_id"], str) and data["prepared_by_user_id"]
    assert isinstance(data["revision"], int) and data["revision"] >= 1
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED")


def assert_packing_list(data: dict):
    _assert_common(data, "PackingList")
    assert is_valid_uuid(data.get("packing_job_id", "")), "PackingList.packing_job_id must be a UUID"
    assert isinstance(data["lines"], list)
    assert isinstance(data["total_gross_weight_kg"], (int, float))
    assert data["status"] in ("DRAFT", "FINALIZED", "RELEASED", "AMENDING")


def assert_commercial_invoice(data: dict):
    _assert_common(data, "CommercialInvoice")
    assert is_valid_uuid(data.get("packing_job_id", "")), "CommercialInvoice.packing_job_id must be a UUID"
    assert isinstance(data["lines"], list)
    assert isinstance(data["invoice_total_cents"], int)
    assert isinstance(data["duty_total_cents"], int)
    assert data["status"] in ("DRAFT", "FINALIZED", "RELEASED", "AMENDING")


def assert_crew(data: dict):
    _assert_common(data, "Crew")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["capabilities"], list) and len(data["capabilities"]) > 0
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_labor_booking(data: dict):
    _assert_common(data, "LaborBooking")
    assert is_valid_uuid(data.get("packing_job_id", "")), "LaborBooking.packing_job_id must be a UUID"
    assert is_valid_uuid(data.get("crew_id", "")), "LaborBooking.crew_id must be a UUID"
    assert data["mode"] in ("SHOP", "ONSITE")
    assert isinstance(data["hours"], (int, float))
    assert isinstance(data["rate_cents_per_hour"], int)
    assert isinstance(data["travel_surcharge_cents"], int)
    assert isinstance(data["total_cost_cents"], int)
    assert data["status"] in ("RESERVED", "CONFIRMED", "COMPLETED", "CANCELLED")


def assert_onsite_permit(data: dict):
    _assert_common(data, "OnsitePermit")
    assert is_valid_uuid(data.get("packing_job_id", "")), "OnsitePermit.packing_job_id must be a UUID"
    assert isinstance(data["site_code"], str) and data["site_code"]
    assert data["status"] in ("REQUESTED", "CONFIRMED", "CLOSED", "CANCELLED")


def assert_container(data: dict):
    _assert_common(data, "Container")
    assert isinstance(data["container_no"], str) and data["container_no"]
    assert data["size"] in ("20FT", "40FT", "40HC")
    assert isinstance(data["max_payload_kg"], int)
    assert isinstance(data["dunnage_weight_kg"], (int, float))
    assert isinstance(data["payload_used_kg"], (int, float))
    assert data["status"] in ("PLANNING", "LOCKED", "GATED_OUT")


def assert_damage_claim(data: dict):
    _assert_common(data, "DamageClaim")
    assert is_valid_uuid(data.get("packing_job_id", "")), "DamageClaim.packing_job_id must be a UUID"
    assert is_valid_uuid(data.get("crate_id", "")), "DamageClaim.crate_id must be a UUID"
    assert data["claim_type"] in ("IMPACT", "TILT", "MOISTURE", "OTHER")
    assert isinstance(data["amount_claimed_cents"], int) and data["amount_claimed_cents"] > 0
    assert isinstance(data["appeal_used"], bool)
    assert is_iso8601_timestamp(data.get("filed_at", "")), "filed_at must be ISO 8601"
    assert data["status"] in ("FILED", "UNDER_REVIEW", "APPROVED", "DENIED", "SETTLED")


def assert_wood_ledger_invariants(batch: dict):
    """Lumber ledger conservation (PRD §3.3): available == received - reserved - consumed - scrapped."""
    assert batch["available_board_feet"] == (
        batch["received_board_feet"]
        - batch["reserved_board_feet"]
        - batch["consumed_board_feet"]
        - batch["scrapped_board_feet"]
    ), "board-feet ledger must conserve received Board feet"
    assert batch["stamps_available"] == (
        batch["stamps_acquired"] - batch["stamps_applied"] - batch["stamps_voided"]
    ), "stamp ledger must conserve acquired serials"
