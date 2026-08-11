"""Payload factories — one per entity, input fields only (PRD §3/§4)."""

DEFAULTS = {
    "SITE_NAME": "Test Site",
    "SITE_ADDRESS": "1 Industrial Way",
    "SITE_AHJ": "FM-1",
    "SITE_INSURER": "FM-001",
    "MATERIAL_NAME": "wood flour",
    "KST": 100,
    "PMAX": 8.0,
    "MIE": 10,
    "LAB_REPORT_REF": "LAB-001",
    "COLLECTOR_TAG": "DC-101",
    "DESIGN_AIRFLOW_ACFM": 5000,
    "FILTER_AREA_FT2": 1000,
    "INTERNAL_VOLUME_M3": 8,
    "INSTALLED_VENT_AREA_M2": 500,
    "DHA_TITLE": "FY2026 DHA",
    "PROGRAM_NAME": "Housekeeping Program",
    "TARGET_ACCUMULATION": 1.0,
    "FREQUENCY_HOURS": 24,
    "MEASURED_ACCUMULATION": 0.5,
    "WORK_DESCRIPTION": "Welding on ductwork",
    "FIRE_WATCH_MINUTES": 30,
    "INSPECTOR_KIND": "AHJ",
    "INSPECTOR_REF": "INSP-EXT-1",
    "FINDING_DESCRIPTION": "Finding text",
    "PROJECT_NAME": "Vent Retrofit",
    "SCOPE_BUDGET_CENTS": 100000,
    "LINE_DESCRIPTION": "Vent panel",
    "LINE_COST_CENTS": 1000,
    "LINE_RISK_TIER": "LOW",
    "INCIDENT_KIND": "NEAR_MISS",
    "INCIDENT_SEVERITY": "MINOR",
    "ROOT_CAUSE_CODE": "HOUSEKEEPING",
    "CAPA_DESCRIPTION": "Corrective action",
}


def create_site_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["SITE_NAME"],
        "address": DEFAULTS["SITE_ADDRESS"],
        "ahj_authority": DEFAULTS["SITE_AHJ"],
        "insurer_id": DEFAULTS["SITE_INSURER"],
    }
    defaults.update(overrides)
    return defaults


def create_dust_sample_payload(**overrides) -> dict:
    defaults = {
        "material_name": DEFAULTS["MATERIAL_NAME"],
        "kst_bar_m_per_s": DEFAULTS["KST"],
        "pmax_bar_g": DEFAULTS["PMAX"],
        "mie_mj": DEFAULTS["MIE"],
        "lab_report_ref": DEFAULTS["LAB_REPORT_REF"],
    }
    defaults.update(overrides)
    return defaults


def create_collector_payload(dust_sample_id: str, **overrides) -> dict:
    defaults = {
        "tag": DEFAULTS["COLLECTOR_TAG"],
        "dust_sample_id": dust_sample_id,
        "design_airflow_acfm": DEFAULTS["DESIGN_AIRFLOW_ACFM"],
        "filter_area_ft2": DEFAULTS["FILTER_AREA_FT2"],
        "internal_volume_m3": DEFAULTS["INTERNAL_VOLUME_M3"],
        "installed_vent_area_m2": DEFAULTS["INSTALLED_VENT_AREA_M2"],
    }
    defaults.update(overrides)
    return defaults


def create_dha_payload(author_id: str, **overrides) -> dict:
    defaults = {
        "title": DEFAULTS["DHA_TITLE"],
        "author_id": author_id,
    }
    defaults.update(overrides)
    return defaults


def create_housekeeping_program_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["PROGRAM_NAME"],
        "target_accumulation_g_per_m2": DEFAULTS["TARGET_ACCUMULATION"],
        "frequency_hours": DEFAULTS["FREQUENCY_HOURS"],
    }
    defaults.update(overrides)
    return defaults


def create_housekeeping_audit_payload(auditor_id: str, scheduled_for: str,
                                      **overrides) -> dict:
    defaults = {
        "auditor_id": auditor_id,
        "measured_accumulation_g_per_m2": DEFAULTS["MEASURED_ACCUMULATION"],
        "scheduled_for": scheduled_for,
    }
    defaults.update(overrides)
    return defaults


def create_hot_work_permit_payload(issuer_id: str, performer_id: str,
                                   valid_from: str, valid_to: str,
                                   **overrides) -> dict:
    defaults = {
        "work_description": DEFAULTS["WORK_DESCRIPTION"],
        "issuer_id": issuer_id,
        "performer_id": performer_id,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "fire_watch_minutes_after": DEFAULTS["FIRE_WATCH_MINUTES"],
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(**overrides) -> dict:
    defaults = {
        "inspector_kind": DEFAULTS["INSPECTOR_KIND"],
        "inspector_ref": DEFAULTS["INSPECTOR_REF"],
        "conducted_at": "2026-05-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_inspection_finding_payload(**overrides) -> dict:
    defaults = {
        "severity": "CRITICAL",
        "description": DEFAULTS["FINDING_DESCRIPTION"],
        "due_at": "2026-06-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_retrofit_project_payload(trigger_finding_id: str, **overrides) -> dict:
    defaults = {
        "name": DEFAULTS["PROJECT_NAME"],
        "trigger_finding_id": trigger_finding_id,
        "scope_budget_cents": DEFAULTS["SCOPE_BUDGET_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_line_item_payload(**overrides) -> dict:
    defaults = {
        "description": DEFAULTS["LINE_DESCRIPTION"],
        "cost_cents": DEFAULTS["LINE_COST_CENTS"],
        "risk_tier": DEFAULTS["LINE_RISK_TIER"],
    }
    defaults.update(overrides)
    return defaults


def create_incident_payload(investigation_lead_id: str, **overrides) -> dict:
    defaults = {
        "occurred_at": "2026-05-01T10:00:00Z",
        "kind": DEFAULTS["INCIDENT_KIND"],
        "description": "Incident narrative",
        "severity": DEFAULTS["INCIDENT_SEVERITY"],
        "root_cause_code": DEFAULTS["ROOT_CAUSE_CODE"],
        "investigation_lead_id": investigation_lead_id,
    }
    defaults.update(overrides)
    return defaults


def create_capa_action_payload(owner_id: str, **overrides) -> dict:
    defaults = {
        "description": DEFAULTS["CAPA_DESCRIPTION"],
        "owner_id": owner_id,
        "due_at": "2026-06-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
