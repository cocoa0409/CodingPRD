"""Manager and FundVehicle endpoints, including diligence lifecycle."""

from flask import Blueprint, request

from db import STORE, new_entity, touch, public
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_INVALID_REQUEST,
    ERR_MANAGER_NOT_ELIGIBLE, ERR_NO_APPROVED_VEHICLE, ERR_DD_SCORE_TOO_LOW,
)
from middleware import auth_context, require_role, ALL_ROLES
from response import ok, list_response
from services import domain
from util import dec
from validate import body, req_str, req_int, req_positive_num, req_num

bp = Blueprint("managers", __name__)


def get_manager_or_404(mid):
    m = STORE.managers.get(mid)
    if m is None:
        raise_err(ERR_NOT_FOUND, "manager id does not exist")
    return m


def get_vehicle_or_404(mid, vid):
    v = STORE.vehicles.get(vid)
    if v is None or v["manager_id"] != mid:
        raise_err(ERR_NOT_FOUND, "vehicle id does not exist")
    return v


# ---------------------------------------------------------------------------
# Manager CRUD + lifecycle.
# ---------------------------------------------------------------------------

@bp.route("/fof/managers", methods=["POST"])
def create_manager():
    _, role = auth_context()
    require_role(role, ["Analyst"])
    data = body()
    legal_name = req_str(data, "legal_name")
    domicile = req_str(data, "domicile_country")
    since = req_int(data, "relationship_since_year")
    if since < 1980:
        raise_err(ERR_INVALID_REQUEST, "relationship_since_year must be >= 1980")
    for m in STORE.managers.values():
        if m["legal_name"] == legal_name:
            raise_err(ERR_INVALID_REQUEST, "legal_name must be globally unique")
    m = new_entity(STORE.managers, {
        "legal_name": legal_name,
        "domicile_country": domicile,
        "relationship_since_year": since,
        "status": "PROSPECT",
    })
    return ok(public(m), status=201)


@bp.route("/fof/managers", methods=["GET"])
def list_managers():
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    return list_response(STORE.managers.values(),
                         filters={"status": request.args.get("status")})


@bp.route("/fof/managers/<mid>", methods=["GET"])
def get_manager(mid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    return ok(public(get_manager_or_404(mid)))


@bp.route("/fof/managers/<mid>/approve", methods=["POST"])
def approve_manager(mid):
    _, role = auth_context()
    require_role(role, ["CIO"])
    m = get_manager_or_404(mid)
    if m["status"] != "PROSPECT":
        raise_err(ERR_INVALID_STATE, "manager is not in PROSPECT")
    if not any(v["manager_id"] == mid and v["status"] == "APPROVED"
               for v in STORE.vehicles.values()):
        raise_err(ERR_NO_APPROVED_VEHICLE,
                  "manager has no APPROVED vehicle")
    m["status"] = "APPROVED"
    touch(m)
    return ok(public(m))


@bp.route("/fof/managers/<mid>/suspend", methods=["POST"])
def suspend_manager(mid):
    _, role = auth_context()
    require_role(role, ["ComplianceOfficer"])
    m = get_manager_or_404(mid)
    if m["status"] != "APPROVED":
        raise_err(ERR_INVALID_STATE, "manager is not APPROVED")
    m["status"] = "SUSPENDED"
    vehicle_ids = [v["id"] for v in STORE.vehicles.values()
                   if v["manager_id"] == mid]
    for v in STORE.vehicles.values():
        if v["manager_id"] == mid and v["status"] == "IN_DILIGENCE":
            v["status"] = "DECLINED"
            touch(v)
    for r in STORE.dd_reviews.values():
        if (r["vehicle_id"] in vehicle_ids
                and r["status"] in ("DRAFT", "SUBMITTED", "INFO_REQUESTED")):
            r["status"] = "WITHDRAWN"
            touch(r)
    for p in STORE.proposals.values():
        if (p["vehicle_id"] in vehicle_ids
                and p["status"] in ("DRAFT", "RECOMMENDED")):
            p["status"] = "WITHDRAWN"
            touch(p)
    touch(m)
    return ok(public(m))


@bp.route("/fof/managers/<mid>/reinstate", methods=["POST"])
def reinstate_manager(mid):
    _, role = auth_context()
    require_role(role, ["ComplianceOfficer"])
    m = get_manager_or_404(mid)
    if m["status"] != "SUSPENDED":
        raise_err(ERR_INVALID_STATE, "manager is not SUSPENDED")
    m["status"] = "APPROVED"
    touch(m)
    return ok(public(m))


@bp.route("/fof/managers/<mid>/exit", methods=["POST"])
def exit_manager(mid):
    _, role = auth_context()
    require_role(role, ["CIO"])
    m = get_manager_or_404(mid)
    if m["status"] != "APPROVED":
        raise_err(ERR_INVALID_STATE, "manager is not APPROVED")
    vehicle_ids = {v["id"] for v in STORE.vehicles.values()
                   if v["manager_id"] == mid}
    for c in STORE.commitments.values():
        if c["vehicle_id"] not in vehicle_ids:
            continue
        if c["status"] == "PENDING_DOCS":
            raise_err(ERR_NO_APPROVED_VEHICLE,
                      "a live commitment (PENDING_DOCS) exists")
        if c["status"] == "EXECUTED" and dec(c["unfunded_amount"]) > 0:
            raise_err(ERR_NO_APPROVED_VEHICLE,
                      "a live commitment (EXECUTED with unfunded) exists")
    m["status"] = "EXITED"
    for v in STORE.vehicles.values():
        if v["manager_id"] == mid and v["status"] != "CLOSED_TO_NEW":
            v["status"] = "CLOSED_TO_NEW"
            touch(v)
    touch(m)
    return ok(public(m))


# ---------------------------------------------------------------------------
# FundVehicle CRUD + lifecycle.
# ---------------------------------------------------------------------------

@bp.route("/fof/managers/<mid>/vehicles", methods=["POST"])
def create_vehicle(mid):
    _, role = auth_context()
    require_role(role, ["Analyst"])
    get_manager_or_404(mid)
    data = body()
    fund_name = req_str(data, "fund_name")
    strategy = data.get("strategy")
    if strategy not in domain.STRATEGIES:
        raise_err(ERR_INVALID_REQUEST, "strategy must be one of %s"
                  % sorted(domain.STRATEGIES))
    vintage_year = req_int(data, "vintage_year")
    if vintage_year < 2000:
        raise_err(ERR_INVALID_REQUEST, "vintage_year must be >= 2000")
    fund_size_target = req_positive_num(data, "fund_size_target")
    early = req_num(data, "mgmt_fee_rate_early")
    late = req_num(data, "mgmt_fee_rate_late")
    for f, v in (("mgmt_fee_rate_early", early), ("mgmt_fee_rate_late", late)):
        if not (0 < v <= 0.05):
            raise_err(ERR_INVALID_REQUEST, "%s must be in (0, 0.05]" % f)
    inv_period = req_int(data, "investment_period_years")
    if inv_period < 1:
        raise_err(ERR_INVALID_REQUEST, "investment_period_years must be >= 1")
    carry = req_num(data, "carry_rate")
    if not (0 <= carry <= 0.30):
        raise_err(ERR_INVALID_REQUEST, "carry_rate must be in [0, 0.30]")
    hurdle = req_num(data, "hurdle_rate")
    if not (0 <= hurdle <= 0.15):
        raise_err(ERR_INVALID_REQUEST, "hurdle_rate must be in [0, 0.15]")
    for v in STORE.vehicles.values():
        if v["manager_id"] == mid and v["fund_name"] == fund_name:
            raise_err(ERR_INVALID_REQUEST,
                      "fund_name must be unique within the manager")
    v = new_entity(STORE.vehicles, {
        "manager_id": mid,
        "fund_name": fund_name,
        "strategy": strategy,
        "vintage_year": vintage_year,
        "fund_size_target": fund_size_target,
        "mgmt_fee_rate_early": early,
        "mgmt_fee_rate_late": late,
        "investment_period_years": inv_period,
        "carry_rate": carry,
        "hurdle_rate": hurdle,
        "status": "SCREENING",
    })
    return ok(public(v), status=201)


@bp.route("/fof/managers/<mid>/vehicles", methods=["GET"])
def list_vehicles(mid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    get_manager_or_404(mid)
    rows = [v for v in STORE.vehicles.values() if v["manager_id"] == mid]
    return list_response(rows, filters={
        "status": request.args.get("status"),
        "strategy": request.args.get("strategy"),
        "vintage_year": request.args.get("vintage_year"),
    })


@bp.route("/fof/managers/<mid>/vehicles/<vid>", methods=["GET"])
def get_vehicle(mid, vid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    get_manager_or_404(mid)
    return ok(public(get_vehicle_or_404(mid, vid)))


@bp.route("/fof/managers/<mid>/vehicles/<vid>/begin-diligence", methods=["POST"])
def begin_diligence(mid, vid):
    _, role = auth_context()
    require_role(role, ["Analyst"])
    m = get_manager_or_404(mid)
    v = get_vehicle_or_404(mid, vid)
    if v["status"] != "SCREENING":
        raise_err(ERR_INVALID_STATE, "vehicle is not in SCREENING")
    if m["status"] not in ("PROSPECT", "APPROVED"):
        raise_err(ERR_MANAGER_NOT_ELIGIBLE,
                  "manager must be PROSPECT or APPROVED")
    v["status"] = "IN_DILIGENCE"
    touch(v)
    new_entity(STORE.dd_reviews, {
        "vehicle_id": vid,
        "round_index": 1,
        "score_strategy_fit": None,
        "score_track_record": None,
        "score_operations": None,
        "score_compliance": None,
        "composite_score": None,
        "status": "DRAFT",
    })
    return ok(public(v))


@bp.route("/fof/managers/<mid>/vehicles/<vid>/approve-vehicle", methods=["POST"])
def approve_vehicle(mid, vid):
    _, role = auth_context()
    require_role(role, ["InvestmentCommittee"])
    m = get_manager_or_404(mid)
    v = get_vehicle_or_404(mid, vid)
    if v["status"] != "IN_DILIGENCE":
        raise_err(ERR_INVALID_STATE, "vehicle is not IN_DILIGENCE")
    reviews = [r for r in STORE.dd_reviews.values() if r["vehicle_id"] == vid]
    latest = max(reviews, key=lambda r: r["round_index"]) if reviews else None
    if (latest is None or latest["status"] != "COMPLETED"
            or latest["composite_score"] is None
            or dec(latest["composite_score"]) < domain.DD_APPROVAL_THRESHOLD):
        raise_err(ERR_DD_SCORE_TOO_LOW,
                  "latest review must be COMPLETED with composite >= 70")
    v["status"] = "APPROVED"
    touch(v)
    if m["status"] == "PROSPECT":
        m["status"] = "APPROVED"
        touch(m)
    return ok(public(v))


@bp.route("/fof/managers/<mid>/vehicles/<vid>/decline-vehicle", methods=["POST"])
def decline_vehicle(mid, vid):
    _, role = auth_context()
    require_role(role, ["InvestmentCommittee"])
    get_manager_or_404(mid)
    v = get_vehicle_or_404(mid, vid)
    if v["status"] != "IN_DILIGENCE":
        raise_err(ERR_INVALID_STATE, "vehicle is not IN_DILIGENCE")
    v["status"] = "DECLINED"
    touch(v)
    for r in STORE.dd_reviews.values():
        if (r["vehicle_id"] == vid
                and r["status"] in ("DRAFT", "SUBMITTED", "INFO_REQUESTED")):
            r["status"] = "WITHDRAWN"
            touch(r)
    return ok(public(v))


@bp.route("/fof/managers/<mid>/vehicles/<vid>/close-to-new", methods=["POST"])
def close_vehicle_to_new(mid, vid):
    _, role = auth_context()
    require_role(role, ["InvestmentCommittee"])
    get_manager_or_404(mid)
    v = get_vehicle_or_404(mid, vid)
    if v["status"] != "APPROVED":
        raise_err(ERR_INVALID_STATE, "vehicle is not APPROVED")
    for p in STORE.proposals.values():
        if p["vehicle_id"] == vid and p["status"] in ("DRAFT", "RECOMMENDED"):
            raise_err(ERR_INVALID_STATE,
                      "a proposal on this vehicle is still DRAFT or RECOMMENDED")
    v["status"] = "CLOSED_TO_NEW"
    touch(v)
    return ok(public(v))


# ---------------------------------------------------------------------------
# Flat vehicle forms.
# ---------------------------------------------------------------------------

@bp.route("/fof/vehicles/<vid>", methods=["GET"])
def get_vehicle_flat(vid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    v = STORE.vehicles.get(vid)
    if v is None:
        raise_err(ERR_NOT_FOUND, "vehicle id does not exist")
    return ok(public(v))


@bp.route("/fof/vehicles/<vid>/commitments", methods=["GET"])
def list_vehicle_commitments(vid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    if STORE.vehicles.get(vid) is None:
        raise_err(ERR_NOT_FOUND, "vehicle id does not exist")
    rows = [c for c in STORE.commitments.values() if c["vehicle_id"] == vid]
    return list_response(rows, filters={"status": request.args.get("status")})


@bp.route("/fof/vehicles/<vid>/secondary-bids", methods=["GET"])
def list_vehicle_bids(vid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    if STORE.vehicles.get(vid) is None:
        raise_err(ERR_NOT_FOUND, "vehicle id does not exist")
    rows = [b for b in STORE.secondary_bids.values() if b["vehicle_id"] == vid]
    return list_response(rows, filters={"status": request.args.get("status")})


@bp.route("/fof/vehicles/<vid>/snapshots", methods=["GET"])
def list_vehicle_snapshots(vid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    if STORE.vehicles.get(vid) is None:
        raise_err(ERR_NOT_FOUND, "vehicle id does not exist")
    rows = [s for s in STORE.snapshots.values() if s["vehicle_id"] == vid]
    return list_response(rows, filters={
        "status": request.args.get("status"),
        "as_of_quarter": request.args.get("as_of_quarter"),
    })
