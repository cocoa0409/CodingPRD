"""Payload factories — one per creatable entity, caller-input fields only (PRD §3)."""

DEFAULTS = {
    "COMPANY_NAME": "Acme Plastics",
    "CONTACT_EMAIL": "ap@x.com",
    "PART_NUMBER": "PN-1001",
    "TOOL_TYPE": "INJECTION_MOLD",
    "DIE_CLASS": "CLASS_103",
    "CAVITY_COUNT": 4,
    "DESIGN_COMPLEXITY_SCORE": 10,
    "QUOTE_KIND": "FIRM",
    "REQUESTED_LEAD_WEEKS": 12,
    "PRESS_ID": "PRESS_500T",
    "MACHINE_ID": "CNC_1",
    # Monday 2026-08-03 08:00-16:00 UTC: a machine block inside the first work week.
    "MACHINE_START": "2026-08-03T08:00:00Z",
    "MACHINE_END": "2026-08-03T16:00:00Z",
    # Press window used by tryout flows.
    "PRESS_START": "2026-08-10T08:00:00Z",
    "PRESS_END": "2026-08-10T16:00:00Z",
    "SAMPLE_QTY": 30,
    "SHOTS_USED": 500,
    "MEASURED_REPORT_REF": "LAY-1",
    "CARRIER": "OLD DOMINION",
    "TRACKING_NUMBER": "TRK-1",
    "ECO_DESCRIPTION": "add lifters",
    "AFFECTS_FROM_SEQ": 4,
    "INSERT_CODE": "INS-CAV-01",
    "UNIT_COST_CENTS": 45000,
    "DEFECT_DESCRIPTION": "cracked cavity block",
    "ESTIMATED_REPAIR_COST_CENTS": 500000,
}


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "company_name": DEFAULTS["COMPANY_NAME"],
        "contact_email": DEFAULTS["CONTACT_EMAIL"],
        "credit_limit_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_tool_design_payload(customer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "part_number": DEFAULTS["PART_NUMBER"],
        "tool_type": DEFAULTS["TOOL_TYPE"],
        "die_class": DEFAULTS["DIE_CLASS"],
        "cavity_count": DEFAULTS["CAVITY_COUNT"],
        "design_complexity_score": DEFAULTS["DESIGN_COMPLEXITY_SCORE"],
    }
    defaults.update(overrides)
    return defaults


def create_quote_payload(customer_id: str, tool_design_id: str,
                         expected_tool_design_version: int, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "tool_design_id": tool_design_id,
        "quote_kind": DEFAULTS["QUOTE_KIND"],
        "requested_lead_weeks": DEFAULTS["REQUESTED_LEAD_WEEKS"],
        "expected_tool_design_version": expected_tool_design_version,
    }
    defaults.update(overrides)
    return defaults


def create_build_job_payload(quote_id: str, **overrides) -> dict:
    defaults = {"quote_id": quote_id}
    defaults.update(overrides)
    return defaults


def create_machine_reservation_payload(build_job_id: str, **overrides) -> dict:
    defaults = {
        "build_job_id": build_job_id,
        "machine_id": DEFAULTS["MACHINE_ID"],
        "start_time": DEFAULTS["MACHINE_START"],
        "end_time": DEFAULTS["MACHINE_END"],
    }
    defaults.update(overrides)
    return defaults


def create_press_reservation_payload(build_job_id: str, **overrides) -> dict:
    defaults = {
        "build_job_id": build_job_id,
        "press_id": DEFAULTS["PRESS_ID"],
        "start_time": DEFAULTS["PRESS_START"],
        "end_time": DEFAULTS["PRESS_END"],
    }
    defaults.update(overrides)
    return defaults


def create_tryout_sample_payload(build_job_id: str, press_reservation_id: str, **overrides) -> dict:
    defaults = {
        "build_job_id": build_job_id,
        "press_reservation_id": press_reservation_id,
    }
    defaults.update(overrides)
    return defaults


def submit_tryout_sample_payload(**overrides) -> dict:
    defaults = {
        "sample_qty": DEFAULTS["SAMPLE_QTY"],
        "shots_used": DEFAULTS["SHOTS_USED"],
        "measured_report_ref": DEFAULTS["MEASURED_REPORT_REF"],
    }
    defaults.update(overrides)
    return defaults


def create_engineering_change_payload(build_job_id: str, expected_build_job_version: int,
                                      **overrides) -> dict:
    defaults = {
        "build_job_id": build_job_id,
        "requested_by": "SHOP",
        "description": DEFAULTS["ECO_DESCRIPTION"],
        "affects_from_milestone_seq": DEFAULTS["AFFECTS_FROM_SEQ"],
        "expected_build_job_version": expected_build_job_version,
    }
    defaults.update(overrides)
    return defaults


def assess_engineering_change_payload(**overrides) -> dict:
    defaults = {
        "rework_hours": 4.0,
        "scrapped_material_cost_cents": 50000,
        "lead_extension_weeks": 1,
    }
    defaults.update(overrides)
    return defaults


def record_payment_payload(amount_cents: int, expected_build_job_version: int, **overrides) -> dict:
    defaults = {
        "amount_cents": amount_cents,
        "expected_build_job_version": expected_build_job_version,
    }
    defaults.update(overrides)
    return defaults


def ship_tool_asset_payload(**overrides) -> dict:
    defaults = {
        "carrier": DEFAULTS["CARRIER"],
        "tracking_number": DEFAULTS["TRACKING_NUMBER"],
    }
    defaults.update(overrides)
    return defaults


def create_shot_report_payload(tool_asset_id: str, **overrides) -> dict:
    defaults = {
        "tool_asset_id": tool_asset_id,
        "report_period_end": "2026-08-20T00:00:00Z",
        "shots_in_period": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_warranty_claim_payload(tool_asset_id: str, **overrides) -> dict:
    defaults = {
        "tool_asset_id": tool_asset_id,
        "defect_description": DEFAULTS["DEFECT_DESCRIPTION"],
        "estimated_repair_cost_cents": DEFAULTS["ESTIMATED_REPAIR_COST_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_spare_insert_payload(tool_asset_id: str, **overrides) -> dict:
    defaults = {
        "tool_asset_id": tool_asset_id,
        "insert_code": DEFAULTS["INSERT_CODE"],
        "unit_cost_cents": DEFAULTS["UNIT_COST_CENTS"],
        "initial_on_hand": 5,
        "reorder_point": 2,
    }
    defaults.update(overrides)
    return defaults
