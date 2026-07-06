"""Payload factories — one per entity, input fields only."""


def create_client_payload(**overrides) -> dict:
    defaults = {
        "org_name": "Mercy Hosp",
        "org_type": "HOSPITAL",
        "contact_email": "h@x.com",
    }
    defaults.update(overrides)
    return defaults


def create_rate_plan_payload(**overrides) -> dict:
    defaults = {
        "client_id": None,
        "certification_tier": "MEDICAL",
        "modality": "PHONE",
        "billing_mode": "PER_MINUTE",
        "rate_cents": 195,
        "min_block_units": 10,
    }
    defaults.update(overrides)
    return defaults


def create_language_pair_payload(**overrides) -> dict:
    defaults = {"source_lang": "en", "target_lang": "es"}
    defaults.update(overrides)
    return defaults


def create_interpreter_payload(**overrides) -> dict:
    defaults = {"full_name": "Med I"}
    defaults.update(overrides)
    return defaults


def create_certification_payload(**overrides) -> dict:
    defaults = {"tier": "MEDICAL", "expires_at": "2027-01-01T00:00:00Z"}
    defaults.update(overrides)
    return defaults


def create_language_grant_payload(**overrides) -> dict:
    defaults = {"language_pair_id": None}
    defaults.update(overrides)
    return defaults


def create_request_payload(**overrides) -> dict:
    defaults = {
        "client_id": None,
        "language_pair_id": None,
        "modality": "PHONE",
        "required_tier": "MEDICAL",
        "scheduling_mode": "ON_DEMAND",
    }
    defaults.update(overrides)
    return defaults


def dispatch_payload(expected_request_version, **overrides) -> dict:
    defaults = {"expected_request_version": expected_request_version}
    defaults.update(overrides)
    return defaults


def mark_no_show_payload(party, **overrides) -> dict:
    defaults = {"party": party}
    defaults.update(overrides)
    return defaults


def reconcile_payload(corrected_billed_units, **overrides) -> dict:
    defaults = {"corrected_billed_units": corrected_billed_units}
    defaults.update(overrides)
    return defaults


def rating_payload(score, **overrides) -> dict:
    defaults = {"score": score}
    defaults.update(overrides)
    return defaults


def encounter_payload(**overrides) -> dict:
    defaults = {"subject_ref": "CASE-001", "summary": "Encounter notes."}
    defaults.update(overrides)
    return defaults


def complaint_payload(session_id, category, **overrides) -> dict:
    defaults = {"session_id": session_id, "category": category}
    defaults.update(overrides)
    return defaults


def resolve_payload(disposition, **overrides) -> dict:
    defaults = {"disposition": disposition}
    defaults.update(overrides)
    return defaults


def invoice_payload(client_id, **overrides) -> dict:
    defaults = {"client_id": client_id}
    defaults.update(overrides)
    return defaults


def clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}
