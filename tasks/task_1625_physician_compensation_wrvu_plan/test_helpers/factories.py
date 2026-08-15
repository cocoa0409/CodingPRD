"""Payload factories — one per entity, input fields only (PRD §3)."""

_OMIT = object()

DEFAULTS = {
    "NPI": "1000000001",
    "FULL_NAME": "Dr Test",
    "SPECIALTY": "IM",
    "PROVIDER_TYPE": "PHYSICIAN",
    "FTE": 1.0,
    "HIRE_DATE": "2019-01-01",
    "PLAN_NAME": "FY2026 Productivity Plan",
    "FISCAL_YEAR_START": "2026-01-01",
    "FISCAL_YEAR_END": "2026-12-31",
    "QUALITY_POOL_CENTS": 100000,
    "FMV_CAP_CENTS": 90000000,
    "CPT_CODE": "99213",
    "WRVU_VALUE": 0.97,
    "RATE_FROM": "2026-01-01",
    "RATE_TO": "2027-01-01",
    "BASE_SALARY_CENTS": 24000000,
    "PERIOD_DRAW_CENTS": 1000000,
    "EFFECTIVE_DATE": "2026-01-01",
    "UNITS": 10,
    "SERVICE_DATE": "2026-02-10",
    "POSTING_DATE": "2026-02-10",
    "CREDIT_PCT": 0.5,
    "SUPERVISED_FTE": 0.5,
    "PERIOD": "2026-02",
    "STMT_YEAR": 2026,
    "STMT_MONTH": 2,
    "AS_OF_PERIOD": "2026-06",
    "REASON": "dispute reason",
    "SUMMARY": "plan change summary",
    "PCR_EFFECTIVE_DATE": "2026-03-01",
}

TIER_T1 = {"tier_code": "T1", "threshold_wrvu": 0, "conversion_factor_cents": 4500,
           "tier_bonus_cents": 0}


def create_physician_payload(**overrides) -> dict:
    defaults = {
        "npi": DEFAULTS["NPI"],
        "full_name": DEFAULTS["FULL_NAME"],
        "specialty": DEFAULTS["SPECIALTY"],
        "provider_type": DEFAULTS["PROVIDER_TYPE"],
        "fte": DEFAULTS["FTE"],
        "hire_date": DEFAULTS["HIRE_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_comp_plan_payload(**overrides) -> dict:
    """Optional enum/FK fields are omitted unless explicitly supplied."""
    defaults = {
        "name": DEFAULTS["PLAN_NAME"],
        "fiscal_year_start": DEFAULTS["FISCAL_YEAR_START"],
        "fiscal_year_end": DEFAULTS["FISCAL_YEAR_END"],
        "tiers": [dict(TIER_T1)],
        "quality_pool_cents": DEFAULTS["QUALITY_POOL_CENTS"],
        "fmv_cap_cents": DEFAULTS["FMV_CAP_CENTS"],
    }
    optional = {}
    for key in ("credit_attribution_mode", "quality_model", "supersedes_plan_id"):
        value = overrides.pop(key, _OMIT)
        if value is not _OMIT:
            optional[key] = value
    defaults.update(overrides)
    defaults.update(optional)
    return defaults


def create_cpt_rate_payload(**overrides) -> dict:
    defaults = {
        "cpt_code": DEFAULTS["CPT_CODE"],
        "wrvu_value": DEFAULTS["WRVU_VALUE"],
        "effective_from": DEFAULTS["RATE_FROM"],
        "effective_to": DEFAULTS["RATE_TO"],
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(**overrides) -> dict:
    defaults = {
        "base_salary_cents": DEFAULTS["BASE_SALARY_CENTS"],
        "period_draw_cents": DEFAULTS["PERIOD_DRAW_CENTS"],
        "effective_date": DEFAULTS["EFFECTIVE_DATE"],
    }
    defaults.update(overrides)  # physician_id / plan_id are mandatory overrides
    return defaults


def create_capture_payload(**overrides) -> dict:
    defaults = {
        "cpt_code": DEFAULTS["CPT_CODE"],
        "units": DEFAULTS["UNITS"],
        "service_date": DEFAULTS["SERVICE_DATE"],
    }
    posting_date = overrides.pop("posting_date", _OMIT)
    if posting_date is not _OMIT:
        defaults["posting_date"] = posting_date
    defaults.update(overrides)
    return defaults


def create_supervision_assignment_payload(**overrides) -> dict:
    defaults = {
        "start_date": "2026-01-01",
        "end_date": "2026-12-31",
        "credit_pct": DEFAULTS["CREDIT_PCT"],
        "supervised_fte": DEFAULTS["SUPERVISED_FTE"],
    }
    defaults.update(overrides)  # supervisor_physician_id / app_physician_id mandatory
    return defaults


def create_scorecard_payload(**overrides) -> dict:
    defaults = {
        "period": DEFAULTS["PERIOD"],
        "measures": [
            {"measure_code": "M1", "weight": 50, "threshold_score": 80, "score": 85},
        ],
    }
    defaults.update(overrides)
    return defaults


def create_statement_payload(**overrides) -> dict:
    defaults = {
        "period_year": DEFAULTS["STMT_YEAR"],
        "period_month": DEFAULTS["STMT_MONTH"],
    }
    defaults.update(overrides)
    return defaults


def create_trueup_run_payload(**overrides) -> dict:
    defaults = {"as_of_period": DEFAULTS["AS_OF_PERIOD"]}
    defaults.update(overrides)
    return defaults


def create_dispute_payload(**overrides) -> dict:
    defaults = {
        "subject_type": "CAPTURE",
        "reason": DEFAULTS["REASON"],
    }
    defaults.update(overrides)
    return defaults


def create_pcr_payload(**overrides) -> dict:
    defaults = {
        "effective_date": DEFAULTS["PCR_EFFECTIVE_DATE"],
        "summary": DEFAULTS["SUMMARY"],
    }
    defaults.update(overrides)  # plan_id / successor_plan_id / expected_comp_plan_version
    return defaults


def fmv_review_payload(decision="APPROVED", benchmark_percentile=55) -> dict:
    return {"decision": decision, "benchmark_percentile": benchmark_percentile}


def review_decision_payload(decision="APPROVED") -> dict:
    return {"decision": decision}


def resolve_payload(resolution="ACCEPTED") -> dict:
    return {"resolution": resolution}


def clock_payload(to_iso8601="2026-01-01T00:00:00Z") -> dict:
    return {"to_iso8601": to_iso8601}
