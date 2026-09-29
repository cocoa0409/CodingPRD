"""Payload factories - one per resource, input fields only."""
import itertools

_bic_counter = itertools.count(1)
_code_counter = itertools.count(0)

_ALPHA = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def next_jurisdiction_code() -> str:
    """A fresh two-character uppercase ASCII jurisdiction code."""
    n = next(_code_counter)
    return _ALPHA[(n // 26) % 26] + _ALPHA[n % 26]


def next_swift_bic() -> str:
    """A fresh 11-character uppercase alphanumeric SWIFT BIC."""
    return "TSTBANK{:04d}".format(next(_bic_counter))[:11]


def jurisdiction_profile_payload(**overrides) -> dict:
    payload = {
        "jurisdiction_code": overrides.pop("jurisdiction_code", next_jurisdiction_code()),
        "name": "Test Jurisdiction",
        "basel_aml_index": 4.00,
        "corridor_risk_weight": 1.00,
    }
    payload.update(overrides)
    return payload


def respondent_payload(home_jurisdiction_code: str, **overrides) -> dict:
    payload = {
        "legal_name": "Test Respondent Bank",
        "swift_bic": overrides.pop("swift_bic", next_swift_bic()),
        "home_jurisdiction_code": home_jurisdiction_code,
        "relationship_manager_user_id": "user-rm-01",
        "expected_monthly_volume_usd": 4500000.00,
        "expected_monthly_count": 300,
    }
    payload.update(overrides)
    return payload


def licensing_payload(**overrides) -> dict:
    payload = {"license_status": "ACTIVE", "regulator_standing": "GOOD_STANDING"}
    payload.update(overrides)
    return payload


def beneficial_owner_payload(country_of_residence: str, **overrides) -> dict:
    payload = {
        "owner_name": "Test Owner",
        "owner_type": "NATURAL_PERSON",
        "ownership_pct": 100.00,
        "country_of_residence": country_of_residence,
    }
    payload.update(overrides)
    return payload


def questionnaire_payload(expected_respondent_version: int, **overrides) -> dict:
    payload = {
        "questionnaire_version": "WOLFSBERG_V1_4",
        "expected_respondent_version": expected_respondent_version,
    }
    payload.update(overrides)
    return payload


def control_assessment_payload(control_domain: str, self_rating: int = 3, **overrides) -> dict:
    payload = {"control_domain": control_domain, "self_rating": self_rating}
    payload.update(overrides)
    return payload


def nested_relationship_payload(downstream_jurisdiction_code: str, **overrides) -> dict:
    payload = {
        "downstream_institution_name": "Downstream Institution",
        "downstream_jurisdiction_code": downstream_jurisdiction_code,
        "relationship_type": "DOWNSTREAM_CORRESPONDENT",
        "discovery_source": "QUESTIONNAIRE",
    }
    payload.update(overrides)
    return payload


def corridor(jurisdiction_code: str, expected_monthly_usd=2000000.00, expected_monthly_count=400):
    return {
        "jurisdiction_code": jurisdiction_code,
        "expected_monthly_usd": expected_monthly_usd,
        "expected_monthly_count": expected_monthly_count,
    }


def monitoring_profile_payload(expected_respondent_version: int, corridors, **overrides) -> dict:
    payload = {
        "effective_from": "2026-07-01T00:00:00Z",
        "effective_to": "2026-12-31T23:59:59Z",
        "expected_corridors": corridors,
        "expected_respondent_version": expected_respondent_version,
    }
    payload.update(overrides)
    return payload


def observation_payload(period_month: str, corridor_jurisdiction_code: str, **overrides) -> dict:
    payload = {
        "period_month": period_month,
        "corridor_jurisdiction_code": corridor_jurisdiction_code,
        "aggregate_usd": 1000000.00,
        "txn_count": 100,
    }
    payload.update(overrides)
    return payload


def monitoring_alert_payload(**overrides) -> dict:
    payload = {"alert_type": "VOLUME_BREACH", "severity": "MEDIUM"}
    payload.update(overrides)
    return payload


def information_request_payload(**overrides) -> dict:
    payload = {"request_topic": "OWNERSHIP_EVIDENCE", "severity": "HIGH"}
    payload.update(overrides)
    return payload


def adverse_media_payload(**overrides) -> dict:
    payload = {
        "headline": "Regulator opens inquiry into respondent",
        "category": "REGULATORY_ACTION",
        "severity_tier": "TIER_2",
        "source_reliability": "B",
        "event_date": "2026-07-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def periodic_refresh_payload(window_start: str, scheduled_due_date: str, **overrides) -> dict:
    payload = {
        "trigger_reason": "CADENCE",
        "window_start": window_start,
        "scheduled_due_date": scheduled_due_date,
    }
    payload.update(overrides)
    return payload


def payment_instruction_payload(
    ordering_jurisdiction_code: str, beneficiary_jurisdiction_code: str, **overrides
) -> dict:
    payload = {
        "ordering_jurisdiction_code": ordering_jurisdiction_code,
        "beneficiary_jurisdiction_code": beneficiary_jurisdiction_code,
        "amount_usd": 10000.00,
        "purpose_code": "TRADE_SETTLEMENT",
    }
    payload.update(overrides)
    return payload


def closure_plan_payload(**overrides) -> dict:
    payload = {
        "termination_reason": "COMMERCIAL",
        "cap_basis": "FORWARD_PROJECTED",
        "original_obligation_cents": 100000,
    }
    payload.update(overrides)
    return payload
