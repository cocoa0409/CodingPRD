"""Risks: registration, assessment loop, cyclic lifecycle (PRD 3.2),
plus nested mapping/plan creation and risk-scoped collections."""
from decimal import Decimal

from flask import Blueprint, request

from db import store, clock_now
from errors import ApiError
from middleware import authenticate, ALL_ROLES
from response import ok_object, ok_list
from services import (new_entity, new_event, touch, serialize_risk,
                      serialize_assessment, serialize_plan, serialize_mapping,
                      serialize_breach, recompute_residual, evaluate_breach,
                      sorted_by_creation, ACTIVE_PLAN_STATUSES,
                      OPEN_BREACH_STATUSES)
from util import (json_body, req_str, opt_str, opt_int, req_int, req_num, req_dt,
                  req_enum, paginate, band_of)

bp = Blueprint("risks", __name__)


def get_risk_or_404(rid):
    r = store["risks"].get(rid)
    if r is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Risk not found")
    return r


def check_risk_owner(risk, uid):
    if risk["owner_user_id"] != uid:
        raise ApiError("ERR_OWNER_MISMATCH", 403,
                       "X-User-ID does not match the risk's owner_user_id")


@bp.post("/risks")
def create_risk():
    authenticate(("RiskOwner",))
    data = json_body()
    category_id = req_str(data, "category_id")
    title = req_str(data, "title")
    owner_user_id = req_str(data, "owner_user_id")
    description = opt_str(data, "description")
    budget = opt_int(data, "treatment_budget_cents")
    if budget is None:
        budget = 0
    if budget < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "treatment_budget_cents must be >= 0")
    if category_id not in store["categories"]:
        raise ApiError("ERR_NOT_FOUND", 404, "category_id does not exist")
    r = new_entity()
    r.update({
        "category_id": category_id,
        "source_emerging_risk_id": None,
        "title": title,
        "description": description,
        "owner_user_id": owner_user_id,
        "treatment_budget_cents": budget,
        "status": "DRAFT",
        "likelihood": None,
        "impact": None,
        "inherent_score": None,
        "inherent_band": None,
        "residual_score": None,
        "residual_band": None,
        "reserved_treatment_cents": 0,
        "kri_alert": False,
    })
    store["risks"][r["id"]] = r
    return ok_object(serialize_risk(r), 201)


@bp.get("/risks")
def list_risks():
    authenticate(ALL_ROLES)
    items = list(store["risks"].values())
    if "category_id" in request.args:
        items = [r for r in items if r["category_id"] == request.args["category_id"]]
    if "status" in request.args:
        items = [r for r in items if r["status"] == request.args["status"]]
    if "residual_band" in request.args:
        items = [r for r in items if r["residual_band"] == request.args["residual_band"]]
    items = sorted_by_creation(items)
    page, meta = paginate(items)
    return ok_list([serialize_risk(r) for r in page], meta)


@bp.get("/risks/<rid>")
def get_risk(rid):
    authenticate(ALL_ROLES)
    return ok_object(serialize_risk(get_risk_or_404(rid)))


def _transition(rid, allowed_from, target):
    uid = authenticate(("RiskOwner",))
    r = get_risk_or_404(rid)
    check_risk_owner(r, uid)
    if r["status"] != allowed_from:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Risk in status %s cannot perform this transition" % r["status"])
    r["status"] = target
    touch(r)
    return ok_object(serialize_risk(r))


@bp.post("/risks/<rid>/submit")
def submit_risk(rid):
    return _transition(rid, "DRAFT", "IDENTIFIED")


@bp.post("/risks/<rid>/reassess")
def reassess_risk(rid):
    return _transition(rid, "MONITORING", "REASSESSMENT")


@bp.post("/risks/<rid>/reopen")
def reopen_risk(rid):
    json_body()  # optional reason; not persisted
    return _transition(rid, "CLOSED", "IDENTIFIED")


@bp.post("/risks/<rid>/enter-treatment")
def enter_treatment(rid):
    uid = authenticate(("RiskOwner",))
    r = get_risk_or_404(rid)
    check_risk_owner(r, uid)
    if r["status"] != "ASSESSED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Risk in status %s cannot enter treatment" % r["status"])
    if r["residual_score"] is None:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "A residual assessment is required before entering treatment")
    if not any(p for p in store["plans"].values()
               if p["risk_id"] == r["id"] and p["status"] == "APPROVED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "At least one APPROVED treatment plan is required")
    r["status"] = "TREATMENT"
    touch(r)
    return ok_object(serialize_risk(r))


@bp.post("/risks/<rid>/monitor")
def monitor_risk(rid):
    uid = authenticate(("RiskOwner",))
    r = get_risk_or_404(rid)
    check_risk_owner(r, uid)
    if r["status"] != "TREATMENT":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Risk in status %s cannot move to monitoring" % r["status"])
    # PRD 3.2 order: breach guard first, then plan guard
    if any(b for b in store["breaches"].values()
           if b["risk_id"] == r["id"] and b["status"] in OPEN_BREACH_STATUSES):
        raise ApiError("ERR_OPEN_BREACH_BLOCKING", 409,
                       "An OPEN or ACKNOWLEDGED tolerance breach blocks monitoring")
    if any(p for p in store["plans"].values()
           if p["risk_id"] == r["id"] and p["status"] in ACTIVE_PLAN_STATUSES):
        raise ApiError("ERR_ACTIVE_PLAN_BLOCKING", 409,
                       "A non-terminal treatment plan blocks monitoring")
    r["status"] = "MONITORING"
    touch(r)
    return ok_object(serialize_risk(r))


@bp.post("/risks/<rid>/close")
def close_risk(rid):
    uid = authenticate(("RiskOwner",))
    r = get_risk_or_404(rid)
    check_risk_owner(r, uid)
    if r["status"] not in ("IDENTIFIED", "ASSESSED", "MONITORING", "REASSESSMENT"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Risk in status %s cannot be closed" % r["status"])
    # PRD 3.2 order for close: plan guard first, then breach guard
    if any(p for p in store["plans"].values()
           if p["risk_id"] == r["id"] and p["status"] in ACTIVE_PLAN_STATUSES):
        raise ApiError("ERR_ACTIVE_PLAN_BLOCKING", 409,
                       "A non-terminal treatment plan blocks closure")
    if any(b for b in store["breaches"].values()
           if b["risk_id"] == r["id"] and b["status"] in OPEN_BREACH_STATUSES):
        raise ApiError("ERR_OPEN_BREACH_BLOCKING", 409,
                       "An OPEN or ACKNOWLEDGED tolerance breach blocks closure")
    r["status"] = "CLOSED"
    touch(r)
    return ok_object(serialize_risk(r))


@bp.post("/risks/<rid>/assessments")
def create_assessment(rid):
    uid = authenticate(("RiskOwner",))
    data = json_body()
    kind = req_enum(data, "kind", ("INHERENT", "RESIDUAL"))
    expected = req_int(data, "expected_risk_version")
    notes = opt_str(data, "notes")
    likelihood = impact = None
    if kind == "INHERENT":
        # missing likelihood/impact is a malformed body (ERR_INVALID_REQUEST)
        likelihood = req_int(data, "likelihood")
        impact = req_int(data, "impact")
    # existence -> ownership -> OCC -> state -> domain ranges
    r = get_risk_or_404(rid)
    check_risk_owner(r, uid)
    if expected != r["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_risk_version does not match the risk's current version")
    breach_created = False
    if kind == "INHERENT":
        if r["status"] not in ("IDENTIFIED", "REASSESSMENT"):
            raise ApiError("ERR_ASSESSMENT_KIND_NOT_ALLOWED", 409,
                           "INHERENT assessment requires status IDENTIFIED or REASSESSMENT")
        if not (1 <= likelihood <= 5) or not (1 <= impact <= 5):
            raise ApiError("ERR_SCORE_OUT_OF_RANGE", 422,
                           "likelihood and impact must be integers in 1..5")
        r["likelihood"] = likelihood
        r["impact"] = impact
        r["inherent_score"] = likelihood * impact
        r["inherent_band"] = band_of(r["inherent_score"])
        if r["status"] == "IDENTIFIED":
            r["status"] = "ASSESSED"
        else:  # REASSESSMENT -> MONITORING with residual recompute on the new base
            r["status"] = "MONITORING"
            recompute_residual(r)
            breach_created = evaluate_breach(r)
    else:  # RESIDUAL self-transition; likelihood/impact ignored
        if r["status"] not in ("ASSESSED", "TREATMENT", "MONITORING", "REASSESSMENT"):
            raise ApiError("ERR_ASSESSMENT_KIND_NOT_ALLOWED", 409,
                           "RESIDUAL assessment not permitted from status %s" % r["status"])
        recompute_residual(r)
        breach_created = evaluate_breach(r)
    a = new_event()
    a.update({
        "risk_id": r["id"],
        "kind": kind,
        "likelihood": likelihood,
        "impact": impact,
        "notes": notes,
        "inherent_score": r["inherent_score"],
        "residual_score": r["residual_score"] if kind == "RESIDUAL" else None,
        "breach_created": breach_created,
    })
    store["assessments"][a["id"]] = a
    touch(r)
    return ok_object(serialize_assessment(a), 201)


@bp.get("/risks/<rid>/assessments")
def list_assessments(rid):
    authenticate(ALL_ROLES)
    get_risk_or_404(rid)
    items = sorted_by_creation(
        a for a in store["assessments"].values() if a["risk_id"] == rid)
    page, meta = paginate(items)
    return ok_list([serialize_assessment(a) for a in page], meta)


@bp.post("/risks/<rid>/control-mappings")
def create_mapping(rid):
    uid = authenticate(("RiskOwner",))
    data = json_body()
    control_id = req_str(data, "control_id")
    coverage = req_num(data, "coverage_weight")
    # PRD 2.6: coverage_weight outside (0, 1.00] is a malformed body
    if coverage <= 0 or coverage > 1:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "coverage_weight must be > 0 and <= 1.00")
    r = get_risk_or_404(rid)
    if control_id not in store["controls"]:
        raise ApiError("ERR_NOT_FOUND", 404, "control_id does not exist")
    check_risk_owner(r, uid)
    if r["status"] not in ("IDENTIFIED", "ASSESSED", "TREATMENT", "MONITORING",
                           "REASSESSMENT"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Mappings cannot be proposed while the risk is %s" % r["status"])
    if any(m for m in store["mappings"].values()
           if m["risk_id"] == r["id"] and m["control_id"] == control_id
           and m["status"] in ("PROPOSED", "ACTIVE")):
        raise ApiError("ERR_MAPPING_EXISTS", 409,
                       "A PROPOSED or ACTIVE mapping already exists for this (risk, control)")
    m = new_entity()
    m.update({"risk_id": r["id"], "control_id": control_id,
              "coverage_weight": coverage, "status": "PROPOSED"})
    store["mappings"][m["id"]] = m
    return ok_object(serialize_mapping(m), 201)


@bp.post("/risks/<rid>/treatment-plans")
def create_plan(rid):
    uid = authenticate(("RiskOwner",))
    data = json_body()
    title = req_str(data, "title")
    budget_cents = req_int(data, "budget_cents")
    if budget_cents <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "budget_cents must be > 0")
    due_date = req_dt(data, "due_date")
    plan_owner = req_str(data, "owner_user_id")
    expected = req_int(data, "expected_risk_version")
    r = get_risk_or_404(rid)
    check_risk_owner(r, uid)
    if expected != r["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_risk_version does not match the risk's current version")
    if r["status"] not in ("ASSESSED", "TREATMENT", "MONITORING", "REASSESSMENT"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Plans cannot be proposed while the risk is %s" % r["status"])
    if not due_date > clock_now():
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "due_date must be after the current logical clock")
    p = new_entity()
    p.update({
        "risk_id": r["id"],
        "title": title,
        "budget_cents": budget_cents,
        "due_date": due_date,
        "owner_user_id": plan_owner,
        "proposer_user_id": uid,
        "status": "PROPOSED",
        "priority": "STANDARD",
        "extension_count": 0,
        "progress_pct": Decimal("0.00"),
    })
    store["plans"][p["id"]] = p
    touch(r)  # plan creation increments the parent risk's version
    return ok_object(serialize_plan(p), 201)


@bp.get("/risks/<rid>/treatment-plans")
def list_risk_plans(rid):
    authenticate(ALL_ROLES)
    get_risk_or_404(rid)
    items = sorted_by_creation(
        p for p in store["plans"].values() if p["risk_id"] == rid)
    page, meta = paginate(items)
    return ok_list([serialize_plan(p) for p in page], meta)


@bp.get("/risks/<rid>/control-mappings")
def list_risk_mappings(rid):
    authenticate(ALL_ROLES)
    get_risk_or_404(rid)
    items = sorted_by_creation(
        m for m in store["mappings"].values() if m["risk_id"] == rid)
    page, meta = paginate(items)
    return ok_list([serialize_mapping(m) for m in page], meta)


@bp.get("/risks/<rid>/tolerance-breaches")
def list_risk_breaches(rid):
    authenticate(ALL_ROLES)
    get_risk_or_404(rid)
    items = sorted_by_creation(
        b for b in store["breaches"].values() if b["risk_id"] == rid)
    page, meta = paginate(items)
    return ok_list([serialize_breach(b) for b in page], meta)
