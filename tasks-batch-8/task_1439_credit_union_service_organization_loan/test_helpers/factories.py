"""Payload factories — one per entity, input fields only (PRD §3, §4)."""

DEFAULTS = {
    "CU_TOTAL_ASSETS": 20_000_000_000,
    "CU_NET_WORTH": 2_000_000_000,
    "ORIG_TOTAL_ASSETS": 50_000_000_000,
    "ORIG_NET_WORTH": 5_000_000_000,
    "SERVICING_FEE_BPS": 25,
    "REMITTANCE_DUE_DAY": 15,
    "DAY_COUNT": "THIRTY_360",
    "POOL_PRINCIPAL": 100_000_000,
    "MIN_SHARE_PCT": 0.01,
    "YIELD_BPS": 600,
    "OPEN_AT": "2026-08-01T00:00:00Z",
    "CLOSE_AT": "2026-12-01T00:00:00Z",
    "COMMIT_AMOUNT": 10_000_000,
    "PERIOD_START": "2026-08-01T00:00:00Z",
    "PERIOD_END": "2026-08-31T00:00:00Z",
    "REMEDIATION_DUE": "2026-10-01T00:00:00Z",
}


def create_credit_union_payload(**overrides) -> dict:
    defaults = {
        "charter_number": "CU-1",
        "legal_name": "Test Credit Union",
        "cu_type": "BUYER",
        "total_assets_cents": DEFAULTS["CU_TOTAL_ASSETS"],
        "net_worth_cents": DEFAULTS["CU_NET_WORTH"],
    }
    defaults.update(overrides)
    return defaults


def create_cuso_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "CUSO One",
        "service_line": "LENDING",
    }
    defaults.update(overrides)
    return defaults


def create_investment_payload(credit_union_id: str, cuso_id: str, **overrides) -> dict:
    defaults = {
        "credit_union_id": credit_union_id,
        "cuso_id": cuso_id,
        "amount_cents": 1_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(cuso_id: str, originator_id: str, **overrides) -> dict:
    defaults = {
        "cuso_id": cuso_id,
        "originator_id": originator_id,
        "servicing_fee_bps": DEFAULTS["SERVICING_FEE_BPS"],
        "remittance_due_day": DEFAULTS["REMITTANCE_DUE_DAY"],
        "day_count_convention": DEFAULTS["DAY_COUNT"],
    }
    defaults.update(overrides)
    return defaults


def create_offering_payload(servicing_agreement_id: str, **overrides) -> dict:
    defaults = {
        "servicing_agreement_id": servicing_agreement_id,
        "pool_name": "Pool A",
        "pool_principal_cents": DEFAULTS["POOL_PRINCIPAL"],
        "min_share_pct": DEFAULTS["MIN_SHARE_PCT"],
        "yield_rate_bps": DEFAULTS["YIELD_BPS"],
        "open_at": DEFAULTS["OPEN_AT"],
        "close_at": DEFAULTS["CLOSE_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_commitment_payload(offering_id: str, **overrides) -> dict:
    defaults = {
        "offering_id": offering_id,
        "committed_amount_cents": DEFAULTS["COMMIT_AMOUNT"],
    }
    defaults.update(overrides)
    return defaults


def create_exception_payload(certificate_id: str, **overrides) -> dict:
    defaults = {
        "certificate_id": certificate_id,
        "exception_type": "MISSING_NOTE",
        "description": "Documentation gap",
    }
    defaults.update(overrides)
    return defaults


def create_remittance_payload(certificate_id: str, **overrides) -> dict:
    defaults = {
        "certificate_id": certificate_id,
        "period_start": DEFAULTS["PERIOD_START"],
        "period_end": DEFAULTS["PERIOD_END"],
        "collections_cents": 100_000,
    }
    defaults.update(overrides)
    return defaults


def create_surveillance_report_payload(servicing_agreement_id: str,
                                       expected_servicing_agreement_version: int,
                                       **overrides) -> dict:
    defaults = {
        "servicing_agreement_id": servicing_agreement_id,
        "period_start": DEFAULTS["PERIOD_START"],
        "period_end": DEFAULTS["PERIOD_END"],
        "expected_servicing_agreement_version": expected_servicing_agreement_version,
    }
    defaults.update(overrides)
    return defaults


def create_exam_payload(cuso_id: str, **overrides) -> dict:
    defaults = {
        "cuso_id": cuso_id,
        "start_date": "2026-08-01T00:00:00Z",
        "end_date": "2026-08-15T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_finding_payload(exam_id: str, **overrides) -> dict:
    defaults = {
        "exam_id": exam_id,
        "severity": "CRITICAL",
        "description": "Finding description",
        "remediation_due_date": DEFAULTS["REMEDIATION_DUE"],
    }
    defaults.update(overrides)
    return defaults


def create_loss_event_payload(offering_id: str, **overrides) -> dict:
    defaults = {
        "offering_id": offering_id,
        "loss_amount_cents": 1_000,
        "defaulted_at": "2026-08-10T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_repurchase_case_payload(certificate_id: str, **overrides) -> dict:
    defaults = {
        "certificate_id": certificate_id,
        "trigger_reason": "MATERIAL_BREACH",
    }
    defaults.update(overrides)
    return defaults
