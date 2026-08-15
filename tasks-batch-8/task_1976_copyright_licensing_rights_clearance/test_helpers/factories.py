"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "HOLDER_LEGAL_NAME": "Test Holder",
    "HOLDER_KIND": "LABEL",
    "MFN_FLOOR_CENTS": 100,
    "ASSET_TITLE": "Test Asset",
    "WORK_KIND": "FILM_CLIP",
    "PERMITTED_MEDIA": ["STREAMING"],
    "CLAIMANT_NAME": "Test Claimant",
}


def create_rights_holder_payload(**overrides) -> dict:
    defaults = {
        "legal_name": DEFAULTS["HOLDER_LEGAL_NAME"],
        "holder_kind": DEFAULTS["HOLDER_KIND"],
        "mfn_floor_cents": DEFAULTS["MFN_FLOOR_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_asset_payload(**overrides) -> dict:
    defaults = {
        "title": DEFAULTS["ASSET_TITLE"],
        "work_kind": DEFAULTS["WORK_KIND"],
        "permitted_media": list(DEFAULTS["PERMITTED_MEDIA"]),
    }
    defaults.update(overrides)
    return defaults


def create_clearance_request_payload(**overrides) -> dict:
    defaults = {
        "media": "STREAMING",
        "territory": "NA",
        "use_start_at": "2026-09-01T00:00:00Z",
        "use_end_at": "2026-11-01T00:00:00Z",
        "requested_units": 1,
    }
    defaults.update(overrides)
    return defaults


def create_round_payload(**overrides) -> dict:
    defaults = {"offered_fee_cents": 1000}
    defaults.update(overrides)
    return defaults


def create_reservation_payload(**overrides) -> dict:
    defaults = {"units": 1}
    defaults.update(overrides)
    return defaults


def create_usage_event_payload(**overrides) -> dict:
    defaults = {
        "units": 1,
        "used_at": "2026-09-15T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(**overrides) -> dict:
    defaults = {"amount_cents": 1000}
    defaults.update(overrides)
    return defaults


def create_diligence_log_payload(**overrides) -> dict:
    defaults = {
        "search_channel": "COPYRIGHT_OFFICE",
        "outcome": "NO_RESULT",
        "notes": "diligence pass",
    }
    defaults.update(overrides)
    return defaults


def create_takedown_payload(**overrides) -> dict:
    defaults = {"claimant_name": DEFAULTS["CLAIMANT_NAME"]}
    defaults.update(overrides)
    return defaults


def create_fair_use_assessment_payload(**overrides) -> dict:
    defaults = {
        "factor_scores": {"purpose": 3, "nature": 2, "amount": 2, "market": 3},
    }
    defaults.update(overrides)
    return defaults
