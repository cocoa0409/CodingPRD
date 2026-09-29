"""Quality risks, risk responses, effectiveness tests and residual evaluation (PRD 3.5)."""

from flask import Blueprint

import auth
import calc
import clock
import response as envelope
import shapes
import store
import vocab
from errors import ApiError

bp = Blueprint("sqm", __name__)

A = auth.SYSTEM_ADMIN
FMP = auth.FIRM_MANAGING_PARTNER
QCD = auth.QUALITY_CONTROL_DIRECTOR


@bp.post("/firms/<firm_id>/quality-risks")
def create_quality_risk(firm_id):
    actor = auth.authenticate((A, FMP, QCD))
    firm = shapes.need_firm(firm_id)
    body = shapes.body()
    shapes.require_present(body, ["component", "quality_objective_code",
                                  "risk_statement", "likelihood", "impact"])
    objective_code = shapes.as_str(body, "quality_objective_code", 1, 40)
    statement = shapes.as_str(body, "risk_statement", 1, 500)
    likelihood = shapes.as_int(body, "likelihood", 1, 5)
    impact = shapes.as_int(body, "impact", 1, 5)
    component = shapes.as_enum(body, "component", vocab.SQM_COMPONENT)
    auth.require_same_firm(actor, firm["id"])
    for existing in store.rows(store.QUALITY_RISKS):
        if existing["firm_id"] == firm["id"] and existing["component"] == component and \
                existing["quality_objective_code"] == objective_code:
            raise ApiError("ERR_DUPLICATE_QUALITY_OBJECTIVE")
    # Created in DRAFT and advanced to ASSESSED inside the same request, so a freshly
    # created risk is never observable in DRAFT.
    risk = store.insert(store.QUALITY_RISKS, {
        "firm_id": firm["id"],
        "component": component,
        "quality_objective_code": objective_code,
        "risk_statement": statement,
        "likelihood": likelihood,
        "impact": impact,
        "inherent_risk_score": likelihood * impact,
        "evaluation_basis": "NONE",
        "residual_risk_score": None,
        "severity_band": "NONE",
        "state": "ASSESSED",
        "response_count": 0,
        "reopen_count": 0,
    })
    return envelope.object_response(store.serialize(store.QUALITY_RISKS, risk), 201)


@bp.post("/quality-risks/<risk_id>/responses")
def create_risk_response(risk_id):
    actor = auth.authenticate((A, QCD))
    risk = shapes.need_risk(risk_id)
    body = shapes.body()
    shapes.require_present(body, ["response_type", "description"])
    description = shapes.as_str(body, "description", 1, 500)
    response_type = shapes.as_enum(body, "response_type", vocab.RESPONSE_TYPE)
    auth.require_same_firm(actor, risk["firm_id"])
    row = store.insert(store.RISK_RESPONSES, {
        "quality_risk_id": risk["id"],
        "response_type": response_type,
        "description": description,
        "design_effectiveness": "NOT_ASSESSED",
        "operating_effectiveness": "NOT_TESTED",
        "tested_on": None,
        "status": "DESIGNED",
    })
    updates = {"response_count": calc.response_count(risk["id"])}
    if risk["state"] == "ASSESSED":
        updates["state"] = "RESPONDED"
    store.mutate(risk, updates)
    return envelope.object_response(store.serialize(store.RISK_RESPONSES, row), 201)


@bp.post("/risk-responses/<response_id>/effectiveness-tests")
def record_effectiveness_test(response_id):
    actor = auth.authenticate((A, QCD))
    row = shapes.need_response(response_id)
    risk = store.get(store.QUALITY_RISKS, row["quality_risk_id"])
    body = shapes.body()
    shapes.require_present(body, ["design_effectiveness", "operating_effectiveness"])
    design = shapes.as_enum(body, "design_effectiveness", vocab.EFFECTIVENESS_INPUT)
    operating = shapes.as_enum(body, "operating_effectiveness", vocab.EFFECTIVENESS_INPUT)
    if risk is not None:
        auth.require_same_firm(actor, risk["firm_id"])
    if row["status"] != "DESIGNED":
        raise ApiError("ERR_INVALID_TRANSITION")
    store.mutate(row, {
        "design_effectiveness": design,
        "operating_effectiveness": operating,
        "tested_on": clock.now_iso(),
        "status": "TESTED",
    }, force=True)
    if risk is not None:
        store.mutate(risk, {"response_count": calc.response_count(risk["id"])})
    return envelope.object_response(store.serialize(store.RISK_RESPONSES, row))


@bp.post("/quality-risks/<risk_id>/evaluations")
def evaluate_quality_risk(risk_id):
    actor = auth.authenticate((A, QCD, FMP))
    risk = shapes.need_risk(risk_id)
    body = shapes.body()
    shapes.require_present(body, ["basis"])
    basis = shapes.as_enum(body, "basis", vocab.EVALUATION_BASIS_INPUT)
    auth.require_same_firm(actor, risk["firm_id"])
    if risk["state"] != "RESPONDED":
        raise ApiError("ERR_INVALID_TRANSITION")
    residual, band = calc.residual_risk_score(risk, basis)
    store.mutate(risk, {
        "evaluation_basis": basis,
        "residual_risk_score": float(residual),
        "severity_band": band,
        "state": "EVALUATED",
    }, force=True)
    firm = store.get(store.FIRMS, risk["firm_id"])
    if firm is not None:
        calc.recompute_posture(firm)
    return envelope.object_response(store.serialize(store.QUALITY_RISKS, risk))
