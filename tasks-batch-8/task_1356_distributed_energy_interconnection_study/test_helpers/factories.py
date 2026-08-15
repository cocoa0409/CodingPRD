"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    "LEGAL_NAME": "Acme Renewables LLC",
    "CONTACT_EMAIL": "queue@acme.example",
    "DEVELOPER_TYPE": "IPP",
    "CLUSTER_NAME": "Cluster 2026-A",
    "REGION": "WEST",
    "WINDOW_OPEN": "2026-08-01T00:00:00Z",
    "WINDOW_CLOSE": "2026-09-01T00:00:00Z",
    "CLUSTER_CAPACITY_MW": 200,
    "PROJECT_NAME": "P1",
    "TECHNOLOGY": "SOLAR",
    "PROJECT_CAPACITY_MW": 10,
    "SERVICE_TYPE": "ENERGY_ONLY",
    "POINT_OF_INTERCONNECTION": "SUB-1",
    "EVIDENCE_URI": "s3://ev/site.pdf",
    "TARGET_COD": "2027-06-01T00:00:00Z",
    "CURTAILMENT_HOURS_CAP": 0,
    "TOTAL_COST_CENTS": 1000000,
    "LIMIT_TYPE": "SEASONAL",
    "EFFECTIVE_START": "2027-06-01T00:00:00Z",
    "EFFECTIVE_END": "2027-08-31T00:00:00Z",
    "CURTAILMENT_HOURS_PER_YEAR": 200,
    "REPORTING_PERIOD": "2026-Q3",
}


def create_developer_payload(**overrides) -> dict:
    defaults = {
        "legal_name": DEFAULTS["LEGAL_NAME"],
        "contact_email": DEFAULTS["CONTACT_EMAIL"],
        "developer_type": DEFAULTS["DEVELOPER_TYPE"],
    }
    defaults.update(overrides)
    return defaults


def create_cluster_group_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["CLUSTER_NAME"],
        "region": DEFAULTS["REGION"],
        "application_window_open": DEFAULTS["WINDOW_OPEN"],
        "application_window_close": DEFAULTS["WINDOW_CLOSE"],
        "capacity_mw": DEFAULTS["CLUSTER_CAPACITY_MW"],
    }
    defaults.update(overrides)
    return defaults


def create_project_payload(developer_id, cluster_group_id, **overrides) -> dict:
    defaults = {
        "developer_id": developer_id,
        "cluster_group_id": cluster_group_id,
        "project_name": DEFAULTS["PROJECT_NAME"],
        "technology": DEFAULTS["TECHNOLOGY"],
        "capacity_mw": DEFAULTS["PROJECT_CAPACITY_MW"],
        "service_type": DEFAULTS["SERVICE_TYPE"],
        "point_of_interconnection": DEFAULTS["POINT_OF_INTERCONNECTION"],
    }
    defaults.update(overrides)
    return defaults


def create_deposit_payload(amount_cents, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_milestone_submission_payload(**overrides) -> dict:
    defaults = {
        "milestone_type": "SITE_CONTROL",
        "evidence_uri": DEFAULTS["EVIDENCE_URI"],
    }
    defaults.update(overrides)
    return defaults


def create_review_payload(decision, review_note=None, **overrides) -> dict:
    defaults = {"decision": decision}
    if review_note is not None:
        defaults["review_note"] = review_note
    defaults.update(overrides)
    return defaults


def create_resubmit_payload(evidence_uri, **overrides) -> dict:
    defaults = {"evidence_uri": evidence_uri}
    defaults.update(overrides)
    return defaults


def create_study_payload(total_cost_cents=DEFAULTS["TOTAL_COST_CENTS"], **overrides) -> dict:
    defaults = {"total_cost_cents": total_cost_cents}
    defaults.update(overrides)
    return defaults


def create_agreement_payload(expected_project_version, **overrides) -> dict:
    defaults = {
        "target_cod": DEFAULTS["TARGET_COD"],
        "max_injection_mw": DEFAULTS["PROJECT_CAPACITY_MW"],
        "curtailment_hours_cap": DEFAULTS["CURTAILMENT_HOURS_CAP"],
        "expected_project_version": expected_project_version,
    }
    defaults.update(overrides)
    return defaults


def create_extension_payload(new_target_cod, **overrides) -> dict:
    defaults = {"new_target_cod": new_target_cod}
    defaults.update(overrides)
    return defaults


def create_curtailment_limit_payload(**overrides) -> dict:
    defaults = {
        "limit_type": DEFAULTS["LIMIT_TYPE"],
        "max_output_mw": 8,
        "effective_start": DEFAULTS["EFFECTIVE_START"],
        "effective_end": DEFAULTS["EFFECTIVE_END"],
        "curtailment_hours_per_year": DEFAULTS["CURTAILMENT_HOURS_PER_YEAR"],
    }
    defaults.update(overrides)
    return defaults


def create_transparency_report_payload(**overrides) -> dict:
    defaults = {"reporting_period": DEFAULTS["REPORTING_PERIOD"]}
    defaults.update(overrides)
    return defaults
