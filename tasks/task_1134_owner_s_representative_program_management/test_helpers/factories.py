"""Payload factories — one per entity, input fields only (per PRD)."""

DEFAULTS = {
    "PROGRAM_NAME": "Test Program",
    "OWNER_ORG": "OwnerOrg",
    "OBJECTIVES": "Deliver the capital program",
    "SCOPE_STATEMENT": "Full scope",
    "TOTAL_BUDGET_CENTS": 10_000_000,
    "CONTINGENCY_TOTAL_CENTS": 1_000_000,
    "TARGET_FINISH_DATE": "2027-03-31",
    "VENDOR_NAME": "VendorCo",
    "CONTRACT_TYPE": "CONTRACTOR",
    "SOLICITATION_ESTIMATE_CENTS": 1_000_000,
    "CO_TITLE": "Change Order",
    "CO_REASON": "scope change",
    "CO_AMOUNT_CENTS": 100_000,
    "RISK_TITLE": "Risk",
    "RISK_CATEGORY": "COST",
    "PROBABILITY_PCT": 50,
    "IMPACT_CENTS": 400_000,
    "PURPOSE": "contingency purpose",
    "PERIOD": "2026-08",
    "GROUP_NAME": "Stakeholder Group",
    "GROUP_TYPE": "USER_GROUP",
    "CONTACT_EMAIL": "group@example.com",
    "ENGAGEMENT_TITLE": "Engagement",
    "PLAN_NAME": "Occupancy Plan",
    "TARGET_MOVE_MONTH": "2026-10",
    "WAVE_NAME": "Wave",
    "DOCK_RESOURCE": "DOCK_A",
    "MOVE_START": "2026-10-01T08:00:00Z",
    "MOVE_END": "2026-10-01T12:00:00Z",
    "CRITICALITY_WEIGHT": 1,
    "ITEM_TYPE": "PUNCH_LIST",
    "ITEM_TITLE": "Closeout item",
    "LESSON_CATEGORY": "COST",
    "LESSON_TEXT": "lesson narrative",
    "RECOMMENDATION": "future recommendation",
    "ENGAGEMENT_START": "2026-09-02T09:00:00Z",
    "ENGAGEMENT_END": "2026-09-02T10:00:00Z",
}


def create_program_payload(**overrides) -> dict:
    defaults = {
        "program_name": DEFAULTS["PROGRAM_NAME"],
        "owner_organization": DEFAULTS["OWNER_ORG"],
    }
    defaults.update(overrides)
    return defaults


def create_charter_payload(program_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "objectives": DEFAULTS["OBJECTIVES"],
        "scope_statement": DEFAULTS["SCOPE_STATEMENT"],
    }
    defaults.update(overrides)
    return defaults


def create_baseline_payload(program_id, total_budget_cents=None, contingency_total_cents=None,
                             lines=None, **overrides) -> dict:
    """Build a baseline payload whose lines sum to total_budget_cents by default."""
    if total_budget_cents is None:
        total_budget_cents = DEFAULTS["TOTAL_BUDGET_CENTS"]
    if contingency_total_cents is None:
        contingency_total_cents = DEFAULTS["CONTINGENCY_TOTAL_CENTS"]
    if lines is None:
        lines = [{"cost_code": "CC-100", "amount_cents": total_budget_cents}]
    defaults = {
        "program_id": program_id,
        "total_budget_cents": total_budget_cents,
        "contingency_total_cents": contingency_total_cents,
        "target_finish_date": DEFAULTS["TARGET_FINISH_DATE"],
        "lines": lines,
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(program_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "vendor_name": DEFAULTS["VENDOR_NAME"],
        "contract_type": DEFAULTS["CONTRACT_TYPE"],
        "solicitation_estimate_cents": DEFAULTS["SOLICITATION_ESTIMATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_change_order_payload(contract_id, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "title": DEFAULTS["CO_TITLE"],
        "reason": DEFAULTS["CO_REASON"],
        "amount_cents": DEFAULTS["CO_AMOUNT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_risk_entry_payload(program_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "title": DEFAULTS["RISK_TITLE"],
        "category": DEFAULTS["RISK_CATEGORY"],
        "probability_pct": DEFAULTS["PROBABILITY_PCT"],
        "impact_cents": DEFAULTS["IMPACT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_drawdown_payload(program_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "purpose": DEFAULTS["PURPOSE"],
        "amount_cents": DEFAULTS["CO_AMOUNT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_owner_report_payload(program_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "period": DEFAULTS["PERIOD"],
    }
    defaults.update(overrides)
    return defaults


def create_stakeholder_group_payload(program_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "group_name": DEFAULTS["GROUP_NAME"],
        "group_type": DEFAULTS["GROUP_TYPE"],
        "contact_email": DEFAULTS["CONTACT_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_engagement_payload(stakeholder_group_id, **overrides) -> dict:
    defaults = {
        "stakeholder_group_id": stakeholder_group_id,
        "title": DEFAULTS["ENGAGEMENT_TITLE"],
        "scheduled_start": DEFAULTS["ENGAGEMENT_START"],
        "scheduled_end": DEFAULTS["ENGAGEMENT_END"],
    }
    defaults.update(overrides)
    return defaults


def create_occupancy_plan_payload(program_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "plan_name": DEFAULTS["PLAN_NAME"],
        "target_move_month": DEFAULTS["TARGET_MOVE_MONTH"],
    }
    defaults.update(overrides)
    return defaults


def create_move_in_wave_payload(occupancy_plan_id, stakeholder_group_id, **overrides) -> dict:
    defaults = {
        "occupancy_plan_id": occupancy_plan_id,
        "stakeholder_group_id": stakeholder_group_id,
        "wave_name": DEFAULTS["WAVE_NAME"],
        "dock_resource": DEFAULTS["DOCK_RESOURCE"],
        "move_start": DEFAULTS["MOVE_START"],
        "move_end": DEFAULTS["MOVE_END"],
        "criticality_weight": DEFAULTS["CRITICALITY_WEIGHT"],
    }
    defaults.update(overrides)
    return defaults


def create_closeout_item_payload(program_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "item_type": DEFAULTS["ITEM_TYPE"],
        "title": DEFAULTS["ITEM_TITLE"],
    }
    defaults.update(overrides)
    return defaults


def create_lesson_entry_payload(program_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "category": DEFAULTS["LESSON_CATEGORY"],
        "lesson_text": DEFAULTS["LESSON_TEXT"],
        "recommendation": DEFAULTS["RECOMMENDATION"],
    }
    defaults.update(overrides)
    return defaults
