"""Payload factories — one per entity, input fields only.

Only fields the client supplies (source: input) appear here. System- and
computed-source fields (status, ledger fields, billable_cents, etc.) are minted
by the server and never sent.
"""

DEFAULTS = {
    "STUDIO_NAME": "Test Studio",
    "COMPANY_NAME": "Test Co",
    "CONTACT_EMAIL": "contact@test.com",
    "PROJECT_TITLE": "Test Project",
    "MOODBOARD_TITLE": "Test Moodboard",
    "CONCEPT_LABEL": "Route A",
    "MILESTONE_NAME": "Test Milestone",
}


def create_studio_payload(**overrides) -> dict:
    """name is required; tax_rate and license_markup_pct are optional (default 0.0)."""
    defaults = {"name": DEFAULTS["STUDIO_NAME"]}
    defaults.update(overrides)
    return defaults


def create_client_payload(**overrides) -> dict:
    defaults = {
        "company_name": DEFAULTS["COMPANY_NAME"],
        "contact_email": DEFAULTS["CONTACT_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_project_payload(client_id, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "title": DEFAULTS["PROJECT_TITLE"],
        "service_type": "LOGO",
        "deposit_pct": 0.30,
    }
    defaults.update(overrides)
    return defaults


def create_moodboard_payload(**overrides) -> dict:
    defaults = {"title": DEFAULTS["MOODBOARD_TITLE"]}
    defaults.update(overrides)
    return defaults


def create_concept_payload(**overrides) -> dict:
    """label is required; revision_limit is optional (default 3)."""
    defaults = {"label": DEFAULTS["CONCEPT_LABEL"]}
    defaults.update(overrides)
    return defaults


def create_milestone_payload(amount_cents, sequence_index, **overrides) -> dict:
    defaults = {
        "name": DEFAULTS["MILESTONE_NAME"],
        "amount_cents": amount_cents,
        "sequence_index": sequence_index,
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(milestone_id, due_date, **overrides) -> dict:
    defaults = {"milestone_id": milestone_id, "due_date": due_date}
    defaults.update(overrides)
    return defaults


def create_deliverable_payload(asset_type, **overrides) -> dict:
    """asset_type is required; is_required_for_handoff is optional (default true)."""
    defaults = {"asset_type": asset_type}
    defaults.update(overrides)
    return defaults


def create_license_payload(project_id, valid_from, valid_until, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "kind": "STOCK",
        "cost_cents": 1000,
        "valid_from": valid_from,
        "valid_until": valid_until,
    }
    defaults.update(overrides)
    return defaults


def create_change_order_payload(project_id, delta_cents, expected_project_version, **overrides) -> dict:
    """project_id, reason, delta_cents, expected_project_version are required;
    concept_id and extra_revisions are optional."""
    defaults = {
        "project_id": project_id,
        "reason": "SCOPE_ADD",
        "delta_cents": delta_cents,
        "expected_project_version": expected_project_version,
    }
    defaults.update(overrides)
    return defaults


def create_retainer_payload(client_id, **overrides) -> dict:
    """client_id, monthly_fee_cents, tier1_rate_cents, tier2_rate_cents required;
    included_hours optional (default 10)."""
    defaults = {
        "client_id": client_id,
        "monthly_fee_cents": 100000,
        "tier1_rate_cents": 5000,
        "tier2_rate_cents": 8000,
    }
    defaults.update(overrides)
    return defaults


def create_care_cycle_payload(period_start, period_end, **overrides) -> dict:
    """period_start, period_end required; hours_used optional (default 0)."""
    defaults = {"period_start": period_start, "period_end": period_end}
    defaults.update(overrides)
    return defaults
