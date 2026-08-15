"""Logic models and indicators."""
from flask import Blueprint, request

from db import db, new_entity, now_iso
from errors import ApiError
from middleware import require_roles
from response import ok_object, ok_list
from util import (
    get_body,
    req_str,
    req_str_nonempty,
    opt_str,
    req_enum,
    opt_enum,
    req_number,
    opt_number,
    req_int,
    get_or_404,
    page_of,
    serialize,
    touch,
)
import services

bp = Blueprint("models", __name__)

MODEL_READ_ROLES = ("ProgramDirector", "EvaluationLead", "DataSteward", "PrivacyOfficer")
INDICATOR_READ_ROLES = MODEL_READ_ROLES + ("FieldCollector",)

LEVELS = ("OUTPUT", "OUTCOME", "IMPACT")
UNITS = ("COUNT", "PERCENT", "SCORE")
DIRECTIONS = ("HIGHER_IS_BETTER", "LOWER_IS_BETTER")
FREQUENCIES = ("PER_EVENT", "MONTHLY", "END_OF_CYCLE")


# ------------------------------------------------------------ logic models
@bp.post("/programs/<pid>/logic-models")
@require_roles("EvaluationLead")
def create_logic_model(pid):
    get_or_404(db.programs, pid)
    body = get_body()
    title = req_str(body, "title")
    description = opt_str(body, "description", "") or ""
    version_no = max(
        [m["version_no"] for m in db.logic_models.values() if m["program_id"] == pid],
        default=0,
    ) + 1
    ent = new_entity(
        db.logic_models,
        {
            "program_id": pid,
            "title": title,
            "description": description,
            "version_no": version_no,
            "status": "DRAFT",
            "approved_at": None,
        },
    )
    return ok_object(serialize(ent), 201)


@bp.get("/programs/<pid>/logic-models")
@require_roles(*MODEL_READ_ROLES)
def list_logic_models(pid):
    get_or_404(db.programs, pid)
    items = [m for m in db.logic_models.values() if m["program_id"] == pid]
    status = request.args.get("status")
    if status is not None:
        items = [m for m in items if m["status"] == status]
    data, limit, offset, total = page_of(items)
    return ok_list(data, limit, offset, total)


@bp.get("/logic-models/<mid>")
@require_roles(*MODEL_READ_ROLES)
def get_logic_model(mid):
    return ok_object(serialize(get_or_404(db.logic_models, mid)))


def _model_transition(mid, allowed_from, to):
    model = get_or_404(db.logic_models, mid)
    if model["status"] not in allowed_from:
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            f"Logic model in state {model['status']} cannot transition to {to}.",
        )
    return model


@bp.post("/logic-models/<mid>/submit")
@require_roles("EvaluationLead")
def submit_logic_model(mid):
    model = _model_transition(mid, ("DRAFT",), "SUBMITTED")
    indicators = [i for i in db.indicators.values() if i["logic_model_id"] == mid]
    if len(indicators) < 1:
        raise ApiError(
            "ERR_INVALID_STATE", 409, "A logic model with no indicators cannot be submitted."
        )
    model["status"] = "SUBMITTED"
    touch(db.logic_models, model)
    return ok_object(serialize(model))


@bp.post("/logic-models/<mid>/approve")
@require_roles("EvaluationLead")
def approve_logic_model(mid):
    model = get_or_404(db.logic_models, mid)
    # Body well-formedness (priority 6) precedes the state check (priority 7).
    body = get_body()
    expected = req_int(body, "expected_program_version")
    if model["status"] != "SUBMITTED":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            f"Logic model in state {model['status']} cannot transition to APPROVED.",
        )
    program = get_or_404(db.programs, model["program_id"])
    # OCC is the last check in the validation order (SCAFFOLD 1.4 priority 23).
    if expected != program["version"]:
        raise ApiError(
            "ERR_STALE_PROGRAM_VERSION",
            412,
            "expected_program_version does not match the program's current version.",
        )
    # Atomic approval act (PRD 3.2).
    prior = None
    for m in db.logic_models.values():
        if m["program_id"] == program["id"] and m["status"] == "APPROVED" and m["id"] != mid:
            prior = m
            break
    if prior is not None:
        prior["status"] = "SUPERSEDED"
        touch(db.logic_models, prior)
        for ind in db.indicators.values():
            if ind["logic_model_id"] == prior["id"] and ind["status"] == "ACTIVE":
                ind["status"] = "RETIRED"
                touch(db.indicators, ind)
    for ind in db.indicators.values():
        if ind["logic_model_id"] == mid and ind["status"] == "DRAFT":
            ind["status"] = "ACTIVE"
            touch(db.indicators, ind)
    program["current_logic_model_id"] = mid
    touch(db.programs, program)
    model["status"] = "APPROVED"
    model["approved_at"] = now_iso()
    touch(db.logic_models, model)
    return ok_object(serialize(model))


@bp.post("/logic-models/<mid>/reject")
@require_roles("EvaluationLead")
def reject_logic_model(mid):
    model = _model_transition(mid, ("SUBMITTED",), "REJECTED")
    get_body()  # optional reason; accepted and ignored
    model["status"] = "REJECTED"
    touch(db.logic_models, model)
    return ok_object(serialize(model))


@bp.post("/logic-models/<mid>/revise")
@require_roles("EvaluationLead")
def revise_logic_model(mid):
    model = _model_transition(mid, ("REJECTED",), "DRAFT")
    model["status"] = "DRAFT"
    touch(db.logic_models, model)
    return ok_object(serialize(model))


# -------------------------------------------------------------- indicators
def _validate_indicator_fields(body, partial=False):
    """Validate indicator input fields; returns a dict of validated values.

    partial=True (PATCH): only supplied keys are validated and returned.
    """
    out = {}

    def _want(key):
        return not partial or key in body

    if _want("code"):
        out["code"] = req_str_nonempty(body, "code")
    if _want("level"):
        out["level"] = req_enum(body, "level", LEVELS)
    if _want("unit"):
        out["unit"] = req_enum(body, "unit", UNITS)
    if _want("direction"):
        out["direction"] = req_enum(body, "direction", DIRECTIONS)
    if _want("baseline_value"):
        out["baseline_value"] = req_number(body, "baseline_value")
    if _want("target_value"):
        out["target_value"] = req_number(body, "target_value")
    if _want("weight") and body.get("weight") is not None:
        out["weight"] = req_number(body, "weight")
    if "weight" in out and out["weight"] <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field 'weight' must be greater than zero.")
    if _want("measurement_frequency"):
        out["measurement_frequency"] = req_enum(body, "measurement_frequency", FREQUENCIES)
    return out


@bp.post("/logic-models/<mid>/indicators")
@require_roles("EvaluationLead")
def create_indicator(mid):
    model = get_or_404(db.logic_models, mid)
    body = get_body()
    vals = _validate_indicator_fields(body, partial=False)
    if model["status"] != "DRAFT":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Indicators can be created only while the model is DRAFT."
        )
    if any(
        i["logic_model_id"] == mid and i["code"] == vals["code"]
        for i in db.indicators.values()
    ):
        raise ApiError(
            "ERR_DUPLICATE_CODE", 409, f"Indicator code already used in this model: {vals['code']}"
        )
    ent = new_entity(
        db.indicators,
        {
            "logic_model_id": mid,
            "code": vals["code"],
            "level": vals["level"],
            "unit": vals["unit"],
            "direction": vals["direction"],
            "baseline_value": vals["baseline_value"],
            "target_value": vals["target_value"],
            "weight": vals.get("weight") if vals.get("weight") is not None else 1.0,
            "measurement_frequency": vals["measurement_frequency"],
            "status": "DRAFT",
        },
    )
    return ok_object(serialize(ent), 201)


@bp.get("/logic-models/<mid>/indicators")
@require_roles(*INDICATOR_READ_ROLES)
def list_indicators(mid):
    get_or_404(db.logic_models, mid)
    items = [i for i in db.indicators.values() if i["logic_model_id"] == mid]
    status = request.args.get("status")
    if status is not None:
        items = [i for i in items if i["status"] == status]
    data, limit, offset, total = page_of(items)
    return ok_list(data, limit, offset, total)


@bp.get("/indicators/<iid>")
@require_roles(*INDICATOR_READ_ROLES)
def get_indicator(iid):
    return ok_object(serialize(get_or_404(db.indicators, iid)))


@bp.patch("/indicators/<iid>")
@require_roles("EvaluationLead")
def patch_indicator(iid):
    indicator = get_or_404(db.indicators, iid)
    body = get_body()
    vals = _validate_indicator_fields(body, partial=True)
    model = get_or_404(db.logic_models, indicator["logic_model_id"])
    if model["status"] != "DRAFT":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Indicators can be edited only while the model is DRAFT."
        )
    if "code" in vals and vals["code"] != indicator["code"]:
        if any(
            i["logic_model_id"] == indicator["logic_model_id"]
            and i["code"] == vals["code"]
            and i["id"] != iid
            for i in db.indicators.values()
        ):
            raise ApiError(
                "ERR_DUPLICATE_CODE",
                409,
                f"Indicator code already used in this model: {vals['code']}",
            )
    for k, v in vals.items():
        indicator[k] = v
    touch(db.indicators, indicator)
    return ok_object(serialize(indicator))


@bp.post("/indicators/<iid>/retire")
@require_roles("EvaluationLead")
def retire_indicator(iid):
    indicator = get_or_404(db.indicators, iid)
    if indicator["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Only an ACTIVE indicator can be retired.")
    indicator["status"] = "RETIRED"
    touch(db.indicators, indicator)
    return ok_object(serialize(indicator))


@bp.get("/indicators/<iid>/attainment")
@require_roles("ProgramDirector", "EvaluationLead", "DataSteward", "FieldCollector")
def get_attainment(iid):
    indicator = get_or_404(db.indicators, iid)
    cycle_id = request.args.get("program_cycle_id")
    if not cycle_id:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Query parameter 'program_cycle_id' is required.")
    variant = request.args.get("variant", "FINAL")
    if variant not in ("FINAL", "PROVISIONAL"):
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "Query parameter 'variant' must be FINAL or PROVISIONAL."
        )
    cycle = get_or_404(db.cycles, cycle_id)
    agg, att, band, count = services.indicator_attainment(indicator, cycle, variant)
    return ok_object(
        {
            "aggregated_value": agg,
            "attainment_pct": att,
            "band": band,
            "observation_count": count,
        }
    )


@bp.get("/indicators/<iid>/milestones")
@require_roles("ProgramDirector", "EvaluationLead", "DataSteward", "FieldCollector")
def list_indicator_milestones(iid):
    get_or_404(db.indicators, iid)
    items = [m for m in db.milestones.values() if m["indicator_id"] == iid]
    status = request.args.get("status")
    if status is not None:
        items = [m for m in items if m["status"] == status]
    data, limit, offset, total = page_of(items)
    return ok_list(data, limit, offset, total)
