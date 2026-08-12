"""Payload factories — one per entity, input fields only (PRD §3)."""
import itertools

from .constants import CONFIG_DEFAULTS

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


def create_rule_config_payload(expected_active_config_version=None, **overrides) -> dict:
    defaults = {
        "config_name": f"cfg-{_seq()}",
        "dependent_primacy_rule": CONFIG_DEFAULTS["dependent_primacy_rule"],
        "msp_employer_size_threshold": CONFIG_DEFAULTS["msp_employer_size_threshold"],
        "esrd_coordination_months": CONFIG_DEFAULTS["esrd_coordination_months"],
        "retroactive_lookback_months": CONFIG_DEFAULTS["retroactive_lookback_months"],
        "recovery_window_days": CONFIG_DEFAULTS["recovery_window_days"],
        "savings_period_length_days": CONFIG_DEFAULTS["savings_period_length_days"],
    }
    defaults.update(overrides)
    if expected_active_config_version is not None:
        defaults["expected_active_config_version"] = expected_active_config_version
    return defaults


def create_provider_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "npi": f"{1000000000 + n}",
        "legal_name": f"Provider {n}",
        "tin": f"TIN-{n}",
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "member_external_id": f"EXT-{n}",
        "full_name": f"Member {n}",
        "date_of_birth": "1980-01-01",
        "gender": "FEMALE",
        "relation_to_subscriber": "SELF",
        "employment_status": "ACTIVE",
        "employer_size": 50,
    }
    defaults.update(overrides)
    return defaults


def create_coverage_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "payer_id": f"PAYER-{n}",
        "plan_name": f"Plan {n}",
        "coverage_kind": "GROUP_HEALTH",
        "subscriber_relationship": "SPOUSE",
        "policy_holder_dob": "1978-01-01",
        "effective_from": "2026-01-01",
        "verification_source": "DATA_MATCH_CMS",
    }
    defaults.update(overrides)
    return defaults


def create_lead_payload(**overrides) -> dict:
    defaults = {
        "source": "DATA_MATCH_CMS",
        "raw_payload": "cms match row",
    }
    defaults.update(overrides)
    return defaults


def create_msp_questionnaire_payload(**overrides) -> dict:
    defaults = {
        "respondent_role": "SELF",
        "has_employer_group_health": False,
        "employer_size": 0,
        "disability_flag": False,
        "esrd_flag": False,
    }
    defaults.update(overrides)
    return defaults


def create_primacy_determination_payload(as_of_service_date, expected_member_version,
                                         msp_questionnaire_id=None, **overrides) -> dict:
    payload = {
        "as_of_service_date": as_of_service_date,
        "expected_member_version": expected_member_version,
    }
    if msp_questionnaire_id is not None:
        payload["msp_questionnaire_id"] = msp_questionnaire_id
    payload.update(overrides)
    return payload


def create_claim_payload(member_id, provider_id, **overrides) -> dict:
    n = _seq()
    defaults = {
        "member_id": member_id,
        "provider_id": provider_id,
        "claim_external_id": f"CLM-{n}",
        "service_date": "2026-02-10",
        "received_date": "2026-02-12",
        "total_billed_cents": 50000,
    }
    defaults.update(overrides)
    return defaults


def create_claim_line_payload(**overrides) -> dict:
    defaults = {
        "line_number": 1,
        "procedure_code": "99213",
        "billed_cents": 50000,
        "allowed_cents": 40000,
        "primary_paid_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_adjustment_payload(cause="NEW_COVERAGE_DISCOVERED",
                              triggering_determination_id=None, **overrides) -> dict:
    payload = {"cause": cause}
    if triggering_determination_id is not None:
        payload["triggering_determination_id"] = triggering_determination_id
    payload.update(overrides)
    return payload


def create_recovery_request_payload(provider_id, amount_cents, **overrides) -> dict:
    payload = {"provider_id": provider_id, "amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def create_reimbursement_payload(amount_cents, method="PROVIDER_REFUND_CHECK", **overrides) -> dict:
    payload = {"amount_cents": amount_cents, "method": method}
    payload.update(overrides)
    return payload


def create_savings_period_payload(**overrides) -> dict:
    defaults = {
        "period_start_date": "2026-01-01",
        "period_end_date": "2026-01-31",
    }
    defaults.update(overrides)
    return defaults
