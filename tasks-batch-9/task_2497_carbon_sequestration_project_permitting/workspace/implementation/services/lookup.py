"""Existence resolution (PRD Section 2.6 rank 6) in the fixed canonical order."""

import db
from errors import ApiError


def _get(store, key, error_id, label):
    if not isinstance(key, str):
        raise ApiError(error_id, "%s not found" % label)
    row = store.get(key)
    if row is None:
        raise ApiError(error_id, "%s not found" % label)
    return row


def project(project_id):
    return _get(db.projects, project_id, "ERR_PROJECT_NOT_FOUND", "storage project")


def model(model_id):
    return _get(db.geologic_models, model_id, "ERR_GEOLOGIC_MODEL_NOT_FOUND", "geologic model")


def wellbore(wellbore_id):
    return _get(db.legacy_wellbores, wellbore_id, "ERR_WELLBORE_NOT_FOUND", "legacy wellbore")


def tract(tract_id):
    return _get(db.pore_space_tracts, tract_id, "ERR_TRACT_NOT_FOUND", "pore space tract")


def permit(permit_id):
    return _get(
        db.injection_well_permits, permit_id, "ERR_PERMIT_NOT_FOUND", "injection well permit"
    )


def plan(plan_id):
    return _get(db.monitoring_plans, plan_id, "ERR_MONITORING_PLAN_NOT_FOUND", "monitoring plan")


def method(method_id):
    return _get(
        db.monitoring_methods, method_id, "ERR_MONITORING_METHOD_NOT_FOUND", "monitoring method"
    )


def instrument(instrument_id):
    return _get(
        db.financial_instruments, instrument_id, "ERR_INSTRUMENT_NOT_FOUND", "financial instrument"
    )


def period(period_id):
    return _get(
        db.injection_periods, period_id, "ERR_INJECTION_PERIOD_NOT_FOUND", "injection period record"
    )


def claim(claim_id):
    return _get(db.tax_credit_claims, claim_id, "ERR_CLAIM_NOT_FOUND", "tax credit claim")


def order(order_id):
    return _get(
        db.remediation_orders, order_id, "ERR_REMEDIATION_ORDER_NOT_FOUND", "remediation order"
    )


def maybe_project(project_id):
    return db.projects.get(project_id) if isinstance(project_id, str) else None


def maybe_tract(tract_id):
    return db.pore_space_tracts.get(tract_id) if isinstance(tract_id, str) else None


def maybe_claim(claim_id):
    return db.tax_credit_claims.get(claim_id) if isinstance(claim_id, str) else None
