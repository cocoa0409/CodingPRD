"""Payload factories — one per entity, input fields only (PRD §3)."""
from .constants import TS

DEFAULTS = {
    "LEGAL_NAME": "Acme Widgets",
    "PAYROLL": 1_000_000_000,
    "TPA_NAME": "ClaimShield Partners",
    "STATE_CODE": "XX",
    "WEEKLY_BENEFIT": 40_000,
    "MAX_BENEFIT": 1_000_000,
    "NARRATIVE": "Facts of the separation are documented.",
    "GROUNDS": "The determination misapplied the facts.",
    "REFEREE": "ref-1",
    "LOCATION": "Room 1",
    "HEARING_START": "2026-08-20T14:00:00Z",
    "HEARING_END": "2026-08-20T15:00:00Z",
    "WITNESS_FROM": "2026-08-20T13:00:00Z",
    "WITNESS_TO": "2026-08-20T16:00:00Z",
    "MODEL_YEAR": 2027,
}

_fein_counter = [0]


def next_fein() -> str:
    """Globally unique 9-digit FEIN strings, distinct per call."""
    _fein_counter[0] += 1
    return f"88{_fein_counter[0]:07d}"


def create_state_rule_payload(state_code="XX", response_window_days=10,
                              window_basis="CALENDAR", appeal_window_days=30,
                              protest_window_days=30, weekend_shift="NONE",
                              **overrides) -> dict:
    payload = {
        "state_code": state_code,
        "response_window_days": response_window_days,
        "window_basis": window_basis,
        "appeal_window_days": appeal_window_days,
        "protest_window_days": protest_window_days,
        "weekend_shift": weekend_shift,
    }
    payload.update(overrides)
    return payload


def create_employer_payload(legal_name=DEFAULTS["LEGAL_NAME"], fein=None,
                            merit_rating_method="RESERVE_RATIO",
                            taxable_payroll_cents=DEFAULTS["PAYROLL"],
                            reserve_balance_cents=None, **overrides) -> dict:
    payload = {
        "legal_name": legal_name,
        "fein": fein or next_fein(),
        "merit_rating_method": merit_rating_method,
        "taxable_payroll_cents": taxable_payroll_cents,
    }
    if reserve_balance_cents is not None:
        payload["reserve_balance_cents"] = reserve_balance_cents
    payload.update(overrides)
    return payload


def create_tpa_engagement_payload(employer_id, tpa_name=DEFAULTS["TPA_NAME"],
                                  authority_scope="FULL",
                                  effective_from=TS["ENGAGEMENT_FROM"],
                                  effective_to=TS["ENGAGEMENT_TO"],
                                  **overrides) -> dict:
    payload = {
        "employer_id": employer_id,
        "tpa_name": tpa_name,
        "authority_scope": authority_scope,
        "effective_from": effective_from,
        "effective_to": effective_to,
    }
    payload.update(overrides)
    return payload


def create_separation_payload(employer_id, claimant_name="Pat Claimant",
                              ssn_last4="1111",
                              last_day_worked=TS["LAST_DAY_WORKED"],
                              separation_reason="LAYOFF", **overrides) -> dict:
    payload = {
        "employer_id": employer_id,
        "claimant_name": claimant_name,
        "ssn_last4": ssn_last4,
        "last_day_worked": last_day_worked,
        "separation_reason": separation_reason,
    }
    payload.update(overrides)
    return payload


_claim_number_counter = [0]


def next_claim_number(state_code="XX") -> str:
    _claim_number_counter[0] += 1
    return f"{state_code}-{_claim_number_counter[0]:05d}"


def create_claim_payload(employer_id, separation_id, state_code="XX",
                         state_claim_number=None,
                         notice_received_at=TS["NOTICE"],
                         benefit_year_begin=TS["BENEFIT_YEAR_BEGIN"],
                         weekly_benefit_amount_cents=DEFAULTS["WEEKLY_BENEFIT"],
                         max_benefit_cents=DEFAULTS["MAX_BENEFIT"],
                         **overrides) -> dict:
    payload = {
        "employer_id": employer_id,
        "separation_id": separation_id,
        "state_code": state_code,
        "state_claim_number": state_claim_number or next_claim_number(state_code),
        "notice_received_at": notice_received_at,
        "benefit_year_begin": benefit_year_begin,
        "weekly_benefit_amount_cents": weekly_benefit_amount_cents,
        "max_benefit_cents": max_benefit_cents,
    }
    payload.update(overrides)
    return payload


def create_response_payload(response_type="PROTEST", separation_reason_code="LAYOFF",
                            narrative=DEFAULTS["NARRATIVE"], filed_by_tpa_id=None,
                            amendment_of=None, **overrides) -> dict:
    payload = {
        "response_type": response_type,
        "separation_reason_code": separation_reason_code,
        "narrative": narrative,
    }
    if filed_by_tpa_id is not None:
        payload["filed_by_tpa_id"] = filed_by_tpa_id
    if amendment_of is not None:
        payload["amendment_of"] = amendment_of
    payload.update(overrides)
    return payload


def create_evidence_payload(doc_category="FINAL_INCIDENT_REPORT",
                            doc_date=TS["DOC_PRE_NOTICE"], authenticated=True,
                            response_id=None, **overrides) -> dict:
    payload = {
        "doc_category": doc_category,
        "doc_date": doc_date,
        "authenticated": authenticated,
    }
    if response_id is not None:
        payload["response_id"] = response_id
    payload.update(overrides)
    return payload


def create_determination_payload(outcome="ALLOWED", mailed_at=TS["MAILED"],
                                 disqualification_weeks=None, **overrides) -> dict:
    payload = {"outcome": outcome, "mailed_at": mailed_at}
    if disqualification_weeks is not None:
        payload["disqualification_weeks"] = disqualification_weeks
    payload.update(overrides)
    return payload


def create_appeal_payload(appellant="EMPLOYER", grounds=DEFAULTS["GROUNDS"],
                          **overrides) -> dict:
    payload = {"appellant": appellant, "grounds": grounds}
    payload.update(overrides)
    return payload


def create_hearing_payload(claim_id, scheduled_start=DEFAULTS["HEARING_START"],
                           scheduled_end=DEFAULTS["HEARING_END"],
                           referee_id=DEFAULTS["REFEREE"],
                           location=DEFAULTS["LOCATION"], **overrides) -> dict:
    payload = {
        "claim_id": claim_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "referee_id": referee_id,
        "location": location,
    }
    payload.update(overrides)
    return payload


def create_witness_payload(full_name="Witness One", witness_role="DIRECT_SUPERVISOR",
                           availability_start=DEFAULTS["WITNESS_FROM"],
                           availability_end=DEFAULTS["WITNESS_TO"],
                           **overrides) -> dict:
    payload = {
        "full_name": full_name,
        "witness_role": witness_role,
        "availability_start": availability_start,
        "availability_end": availability_end,
    }
    payload.update(overrides)
    return payload


def create_charge_statement_payload(employer_id, state_code="XX",
                                    quarter=TS["QUARTER"],
                                    issued_at=TS["STMT_ISSUED"],
                                    **overrides) -> dict:
    payload = {
        "employer_id": employer_id,
        "state_code": state_code,
        "quarter": quarter,
        "issued_at": issued_at,
    }
    payload.update(overrides)
    return payload


def post_line_item_payload(claim_id, amount_cents, benefit_weeks=2,
                           erroneous_reason=None, **overrides) -> dict:
    payload = {
        "claim_id": claim_id,
        "amount_cents": amount_cents,
        "benefit_weeks": benefit_weeks,
    }
    if erroneous_reason is not None:
        payload["erroneous_reason"] = erroneous_reason
    payload.update(overrides)
    return payload


def create_model_payload(model_year=DEFAULTS["MODEL_YEAR"],
                         variant="RESERVE_RATIO", kind="OFFICIAL",
                         **overrides) -> dict:
    payload = {"model_year": model_year, "variant": variant, "kind": kind}
    payload.update(overrides)
    return payload
