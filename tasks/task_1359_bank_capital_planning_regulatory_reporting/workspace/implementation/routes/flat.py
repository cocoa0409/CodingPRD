"""Flat top-level GET endpoints — reverse-reachability for every FK (SCAFFOLD 1.5)."""

from __future__ import annotations

from flask import Blueprint

from db import (
    reporting_periods, capital_instruments, risk_exposures, capital_plans,
    stress_scenarios, call_reports, edit_exceptions, distribution_requests,
    sub_debt_issuances, pca_threshold_events, icaap_documents,
)
from errors import raise_err, ERR_NOT_FOUND
from middleware import require_roles
from response import success_object, success_list
from services.core import (
    ser_period, ser_instrument, ser_exposure, ser_plan, ser_scenario,
    ser_report, ser_edit, ser_distribution, ser_issuance, ser_pca_event, ser_icaap,
)
from util import apply_filters, sorted_page

bp = Blueprint("flat", __name__)


def _get(store: dict, entity_id: str, label: str) -> dict:
    e = store.get(entity_id)
    if e is None:
        raise_err(ERR_NOT_FOUND, f"{label} not found")
    return e


def _list(store: dict, filters: dict[str, str], ser):
    items = apply_filters(list(store.values()), filters)
    page, limit, offset, total = sorted_page(items)
    return success_list([ser(e) for e in page], limit, offset, total)


@bp.route("/reporting-periods/<periodId>", methods=["GET"])
@require_roles("Any")
def flat_period(periodId: str, _user_id: str, _role: str):
    return success_object(ser_period(_get(reporting_periods, periodId, "ReportingPeriod")))


@bp.route("/reporting-periods", methods=["GET"])
@require_roles("Any")
def flat_periods(_user_id: str, _role: str):
    return _list(reporting_periods, {
        "bank_id": "bank_id", "status": "status", "period_year": "period_year",
    }, ser_period)


@bp.route("/capital-instruments/<instrumentId>", methods=["GET"])
@require_roles("Any")
def flat_instrument(instrumentId: str, _user_id: str, _role: str):
    return success_object(ser_instrument(_get(capital_instruments, instrumentId, "CapitalInstrument")))


@bp.route("/capital-instruments", methods=["GET"])
@require_roles("Any")
def flat_instruments(_user_id: str, _role: str):
    return _list(capital_instruments, {
        "bank_id": "bank_id", "instrument_class": "instrument_class", "status": "status",
    }, ser_instrument)


@bp.route("/risk-exposures/<exposureId>", methods=["GET"])
@require_roles("Any")
def flat_exposure(exposureId: str, _user_id: str, _role: str):
    return success_object(ser_exposure(_get(risk_exposures, exposureId, "RiskExposure")))


@bp.route("/risk-exposures", methods=["GET"])
@require_roles("Any")
def flat_exposures(_user_id: str, _role: str):
    return _list(risk_exposures, {
        "bank_id": "bank_id", "reporting_period_id": "reporting_period_id",
        "exposure_class": "exposure_class", "obligor_grade": "obligor_grade",
    }, ser_exposure)


@bp.route("/capital-plans/<planId>", methods=["GET"])
@require_roles("Any")
def flat_plan(planId: str, _user_id: str, _role: str):
    return success_object(ser_plan(_get(capital_plans, planId, "CapitalPlan")))


@bp.route("/capital-plans", methods=["GET"])
@require_roles("Any")
def flat_plans(_user_id: str, _role: str):
    return _list(capital_plans, {
        "bank_id": "bank_id", "baseline_period_id": "baseline_period_id",
        "stress_scenario_id": "stress_scenario_id", "status": "status", "plan_year": "plan_year",
    }, ser_plan)


@bp.route("/stress-scenarios/<scenarioId>", methods=["GET"])
@require_roles("Any")
def flat_scenario(scenarioId: str, _user_id: str, _role: str):
    return success_object(ser_scenario(_get(stress_scenarios, scenarioId, "StressScenario")))


@bp.route("/stress-scenarios", methods=["GET"])
@require_roles("Any")
def flat_scenarios(_user_id: str, _role: str):
    return _list(stress_scenarios, {"bank_id": "bank_id", "status": "status"}, ser_scenario)


@bp.route("/call-reports/<reportId>", methods=["GET"])
@require_roles("Any")
def flat_report(reportId: str, _user_id: str, _role: str):
    return success_object(ser_report(_get(call_reports, reportId, "CallReport")))


@bp.route("/call-reports", methods=["GET"])
@require_roles("Any")
def flat_reports(_user_id: str, _role: str):
    return _list(call_reports, {
        "bank_id": "bank_id", "reporting_period_id": "reporting_period_id",
        "supersedes_call_report_id": "supersedes_call_report_id", "status": "status",
    }, ser_report)


@bp.route("/edit-exceptions/<editId>", methods=["GET"])
@require_roles("Any")
def flat_edit(editId: str, _user_id: str, _role: str):
    return success_object(ser_edit(_get(edit_exceptions, editId, "EditException")))


@bp.route("/edit-exceptions", methods=["GET"])
@require_roles("Any")
def flat_edits(_user_id: str, _role: str):
    return _list(edit_exceptions, {
        "call_report_id": "call_report_id", "status": "status", "severity": "severity",
    }, ser_edit)


@bp.route("/distribution-requests/<requestId>", methods=["GET"])
@require_roles("Any")
def flat_distribution(requestId: str, _user_id: str, _role: str):
    return success_object(ser_distribution(_get(distribution_requests, requestId, "CapitalDistributionRequest")))


@bp.route("/distribution-requests", methods=["GET"])
@require_roles("Any")
def flat_distributions(_user_id: str, _role: str):
    return _list(distribution_requests, {
        "bank_id": "bank_id", "capital_plan_id": "capital_plan_id",
        "reporting_period_id": "reporting_period_id", "status": "status",
        "distribution_kind": "distribution_kind",
    }, ser_distribution)


@bp.route("/sub-debt-issuances/<issuanceId>", methods=["GET"])
@require_roles("Any")
def flat_issuance(issuanceId: str, _user_id: str, _role: str):
    return success_object(ser_issuance(_get(sub_debt_issuances, issuanceId, "SubordinatedDebtIssuance")))


@bp.route("/sub-debt-issuances", methods=["GET"])
@require_roles("Any")
def flat_issuances(_user_id: str, _role: str):
    return _list(sub_debt_issuances, {
        "bank_id": "bank_id", "capital_instrument_id": "capital_instrument_id", "status": "status",
    }, ser_issuance)


@bp.route("/pca-threshold-events/<eventId>", methods=["GET"])
@require_roles("Any")
def flat_pca_event(eventId: str, _user_id: str, _role: str):
    return success_object(ser_pca_event(_get(pca_threshold_events, eventId, "PCAThresholdEvent")))


@bp.route("/pca-threshold-events", methods=["GET"])
@require_roles("Any")
def flat_pca_events(_user_id: str, _role: str):
    return _list(pca_threshold_events, {
        "bank_id": "bank_id", "call_report_id": "call_report_id",
        "metric": "metric", "breached": "breached",
    }, ser_pca_event)


@bp.route("/icaap-documents/<docId>", methods=["GET"])
@require_roles("Any")
def flat_icaap(docId: str, _user_id: str, _role: str):
    return success_object(ser_icaap(_get(icaap_documents, docId, "ICAAPDocument")))


@bp.route("/icaap-documents", methods=["GET"])
@require_roles("Any")
def flat_icaaps(_user_id: str, _role: str):
    return _list(icaap_documents, {
        "bank_id": "bank_id", "governing_capital_plan_id": "governing_capital_plan_id",
        "status": "status", "document_year": "document_year",
    }, ser_icaap)
