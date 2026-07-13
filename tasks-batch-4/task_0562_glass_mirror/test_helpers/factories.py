"""Payload factories — one per entity, input fields only (PRD §4 input columns)."""


def create_contractor_account_payload(**overrides) -> dict:
    payload = {
        "company_name": "Acme Glazing",
        "tier": "SILVER",
        "credit_limit_cents": 100_000_000,
    }
    payload.update(overrides)
    return payload


def create_quote_payload(contractor_account_id: str, **overrides) -> dict:
    payload = {"contractor_account_id": contractor_account_id}
    payload.update(overrides)
    return payload


def create_line_item_payload(**overrides) -> dict:
    """Default: a SHOWER_ENCLOSURE TEMPERED 10mm 30x72 single pane.
    Required inputs: product_type, glass_type, thickness_mm, width_in, height_in,
    quantity. Optional: edge_work (default NONE), requires_safety_glazing (default
    false) — per PRD §3.2; omit them unless a test needs them."""
    payload = {
        "product_type": "SHOWER_ENCLOSURE",
        "glass_type": "TEMPERED",
        "thickness_mm": 10,
        "width_in": 30,
        "height_in": 72,
        "quantity": 1,
    }
    payload.update(overrides)
    return payload


def create_furnace_payload(**overrides) -> dict:
    payload = {"name": "F1", "max_batch_sqft": 500, "cooldown_minutes": 60}
    payload.update(overrides)
    return payload


def create_tempering_batch_payload(job_id, furnace_id, scheduled_start, scheduled_end, **overrides) -> dict:
    payload = {
        "job_id": job_id,
        "furnace_id": furnace_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    payload.update(overrides)
    return payload


def create_install_crew_payload(**overrides) -> dict:
    payload = {"name": "Crew1", "certified_products": ["SHOWER_ENCLOSURE"]}
    payload.update(overrides)
    return payload


def create_install_appointment_payload(job_id, crew_id, window_start, window_end, **overrides) -> dict:
    payload = {
        "job_id": job_id,
        "crew_id": crew_id,
        "window_start": window_start,
        "window_end": window_end,
    }
    payload.update(overrides)
    return payload


def create_claim_report_payload(job_id, line_item_id, claim_type, cause="test cause", **overrides) -> dict:
    payload = {
        "job_id": job_id,
        "line_item_id": line_item_id,
        "claim_type": claim_type,
        "cause": cause,
    }
    payload.update(overrides)
    return payload
