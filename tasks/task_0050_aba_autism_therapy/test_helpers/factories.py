"""Payload factories — one per entity, input fields only.

Each factory returns the input-field payload an endpoint expects, with sensible
defaults that callers override via **overrides.
"""
import itertools

# Monotonic NPI generator so each created provider gets a distinct identifier.
_npi_counter = itertools.count(9000000001)


def next_npi() -> str:
    return str(next(_npi_counter))


def create_payer_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Payer ABA",
        "allowed_rate_cents": 2800,
        "coinsurance_pct": 0.20,
        "supervision_ratio_pct": 0.10,
    }
    defaults.update(overrides)
    return defaults


def create_client_payload(insurance_payer_id, **overrides) -> dict:
    defaults = {
        "full_name": "Test Child",
        "date_of_birth": "2018-01-01",
        "caregiver_user_id": "cg-test",
        "insurance_payer_id": insurance_payer_id,
    }
    defaults.update(overrides)
    return defaults


def create_provider_payload(credential="BCBA", **overrides) -> dict:
    defaults = {
        "full_name": "Test Provider",
        "credential": credential,
        "npi": next_npi(),
    }
    defaults.update(overrides)
    return defaults


def create_evaluation_payload(client_id, evaluator_bcba_id, assessment_score=70,
                              **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "evaluator_bcba_id": evaluator_bcba_id,
        "assessment_score": assessment_score,
    }
    defaults.update(overrides)
    return defaults


def create_plan_payload(client_id, evaluation_id, author_bcba_id,
                        requested_direct_units=100,
                        requested_supervision_units=20,
                        requested_parent_training_units=8, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "evaluation_id": evaluation_id,
        "author_bcba_id": author_bcba_id,
        "requested_direct_units": requested_direct_units,
        "requested_supervision_units": requested_supervision_units,
        "requested_parent_training_units": requested_parent_training_units,
    }
    defaults.update(overrides)
    return defaults


def create_authorization_payload(treatment_plan_id, payer_id,
                                 authorized_direct_units=100,
                                 authorized_supervision_units=20,
                                 authorized_parent_training_units=8,
                                 period_start="2026-01-01",
                                 period_end="2026-12-31", **overrides) -> dict:
    defaults = {
        "treatment_plan_id": treatment_plan_id,
        "payer_id": payer_id,
        "authorized_direct_units": authorized_direct_units,
        "authorized_supervision_units": authorized_supervision_units,
        "authorized_parent_training_units": authorized_parent_training_units,
        "period_start": period_start,
        "period_end": period_end,
    }
    defaults.update(overrides)
    return defaults


def renew_authorization_payload(expected_authorization_version,
                                authorized_direct_units=100,
                                authorized_supervision_units=20,
                                authorized_parent_training_units=8,
                                period_start="2027-01-01",
                                period_end="2027-12-31", **overrides) -> dict:
    defaults = {
        "expected_authorization_version": expected_authorization_version,
        "authorized_direct_units": authorized_direct_units,
        "authorized_supervision_units": authorized_supervision_units,
        "authorized_parent_training_units": authorized_parent_training_units,
        "period_start": period_start,
        "period_end": period_end,
    }
    defaults.update(overrides)
    return defaults


def create_session_payload(authorization_id, provider_id,
                           service_line="DIRECT_THERAPY",
                           scheduled_start="2026-02-02T09:00:00Z",
                           scheduled_end="2026-02-02T11:00:00Z",
                           scheduled_units=8, **overrides) -> dict:
    defaults = {
        "authorization_id": authorization_id,
        "provider_id": provider_id,
        "service_line": service_line,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "scheduled_units": scheduled_units,
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(session_id, **overrides) -> dict:
    defaults = {"session_id": session_id}
    defaults.update(overrides)
    return defaults
