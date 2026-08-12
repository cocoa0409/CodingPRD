"""Payload factories — one per entity, input fields only (PRD §3, §4)."""

DEFAULTS = {
    "TITLE_NAME": "Hamlet",
    "TITLE_AUTHOR": "Shakespeare",
    "TITLE_KIND": "PLAY",
    "ROYALTY_BASIS": "PER_PERFORMANCE",
    "BASE_FLAT_FEE_CENTS": 50000,
    "GROSS_PERCENT_BP": 0,
    "RESTRICTED_MATERIAL": False,
    "PERUSAL_FEE_CENTS": 500,
    "RENTAL_DEPOSIT_CENTS": 20000,
    "LATE_FEE_PER_DAY_CENTS": 500,
    "RESTRICTED_LATE_FEE_PER_DAY_CENTS": 1500,
    "RECORDING_ROYALTY_FLAT_CENTS": 30000,
    "ORG_LEGAL_NAME": "Community Troupe",
    "ORG_KIND": "COMMUNITY",
    "ORG_HOME_TERRITORY": "US-CA",
    "REQUESTED_TERRITORY": "US-CA",
    "REQUESTED_CLASSIFICATION": "AMATEUR",
    "VENUE_SEATING_CAPACITY": 100,
    "TICKET_TOP_PRICE_CENTS": 1000,
    "PROJECTED_GROSS_CENTS": 100000,
    "PERFORMANCE_COUNT": 1,
    "FIRST_PERFORMANCE_DATE": "2026-06-01T19:00:00Z",
    "LAST_PERFORMANCE_DATE": "2026-06-01T19:00:00Z",
    "RENTAL_DUE_DATE": "2026-06-10T00:00:00Z",
}


def create_title_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["TITLE_NAME"],
        "author": DEFAULTS["TITLE_AUTHOR"],
        "title_kind": DEFAULTS["TITLE_KIND"],
        "royalty_basis": DEFAULTS["ROYALTY_BASIS"],
        "base_flat_fee_cents": DEFAULTS["BASE_FLAT_FEE_CENTS"],
        "gross_percent_bp": DEFAULTS["GROSS_PERCENT_BP"],
        "restricted_material": DEFAULTS["RESTRICTED_MATERIAL"],
        "perusal_fee_cents": DEFAULTS["PERUSAL_FEE_CENTS"],
        "rental_deposit_cents": DEFAULTS["RENTAL_DEPOSIT_CENTS"],
        "late_fee_per_day_cents": DEFAULTS["LATE_FEE_PER_DAY_CENTS"],
        "restricted_late_fee_per_day_cents": DEFAULTS[
            "RESTRICTED_LATE_FEE_PER_DAY_CENTS"
        ],
        "recording_royalty_flat_cents": DEFAULTS["RECORDING_ROYALTY_FLAT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_restriction_payload(**overrides) -> dict:
    defaults = {
        "territory_code": "US-CA",
        "restriction_kind": "BLACKOUT",
        "window_start": "2026-06-01T00:00:00Z",
        "window_end": "2026-06-10T00:00:00Z",
        "blocks_classification": "BOTH",
    }
    defaults.update(overrides)
    return defaults


def create_organization_payload(**overrides) -> dict:
    defaults = {
        "legal_name": DEFAULTS["ORG_LEGAL_NAME"],
        "org_kind": DEFAULTS["ORG_KIND"],
        "home_territory_code": DEFAULTS["ORG_HOME_TERRITORY"],
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(title_id, organization_id, **overrides) -> dict:
    defaults = {
        "title_id": title_id,
        "organization_id": organization_id,
        "requested_territory_code": DEFAULTS["REQUESTED_TERRITORY"],
        "requested_classification": DEFAULTS["REQUESTED_CLASSIFICATION"],
        "venue_seating_capacity": DEFAULTS["VENUE_SEATING_CAPACITY"],
        "ticket_top_price_cents": DEFAULTS["TICKET_TOP_PRICE_CENTS"],
        "performers_compensated": False,
        "admission_charged": True,
        "projected_gross_cents": DEFAULTS["PROJECTED_GROSS_CENTS"],
        "performance_count": DEFAULTS["PERFORMANCE_COUNT"],
        "first_performance_date": DEFAULTS["FIRST_PERFORMANCE_DATE"],
        "last_performance_date": DEFAULTS["LAST_PERFORMANCE_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(**overrides) -> dict:
    defaults = {"amount_cents": 1000}
    defaults.update(overrides)
    return defaults


def create_performance_payload(**overrides) -> dict:
    defaults = {"performance_at": DEFAULTS["FIRST_PERFORMANCE_DATE"]}
    defaults.update(overrides)
    return defaults


def create_amendment_payload(expected_agreement_version, **overrides) -> dict:
    defaults = {
        "expected_agreement_version": expected_agreement_version,
        "amendment_note": "Amendment",
    }
    defaults.update(overrides)
    return defaults


def create_rental_payload(agreement_id, **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "scripts_qty": 5,
        "scores_qty": 0,
        "due_date": DEFAULTS["RENTAL_DUE_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_alteration_request_payload(agreement_id, **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "alteration_kind": "CUT",
        "description": "Trim scene 2",
    }
    defaults.update(overrides)
    return defaults


def create_recording_grant_payload(agreement_id, **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "grant_kind": "CAST_RECORDING_AUDIO",
        "distribution_scope": "CAST_CREW_ONLY",
    }
    defaults.update(overrides)
    return defaults


def report_performance_payload(**overrides) -> dict:
    defaults = {"reported_attendance": 100, "reported_gross_cents": 50000}
    defaults.update(overrides)
    return defaults
