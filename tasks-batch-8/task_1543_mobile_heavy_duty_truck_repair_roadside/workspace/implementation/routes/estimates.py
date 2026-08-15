"""WorkEstimate endpoints: create (OCC), edit/revise, submit, approve, reject."""
from flask import Blueprint, request

from db import store, new_record, touch
from errors import (ApiError, err_not_found, err_invalid_state,
                    err_stale_version)
from middleware import auth, require_fleet_ownership
from response import success
from serializers import serialize, fleet_mtd
from services.cascades import append_event, wall_now
from services.pricing import estimate_total
from routes.service_calls import get_call_or_404, ensure_not_cancelled
from util import Field, validate_body, parse_pagination, paginate

bp = Blueprint("estimates", __name__)

WRITE_ROLES = ["Technician", "Dispatcher", "OpsAdmin"]
READ_ROLES = ["OpsAdmin", "Dispatcher", "Technician", "FleetManager",
              "BillingClerk"]
LIST_ROLES = ["OpsAdmin", "Dispatcher", "FleetManager"]

ESTIMATE_INPUT_FIELDS = [
    Field("labor_hours_est", "number", min_val=0),
    Field("travel_miles_est", "int", min_val=0),
    Field("parts_estimate_cents", "int", min_val=0),
    Field("includes_tow", "bool"),
    Field("tow_estimate_cents", "int", min_val=0),
]


def _get_estimate(estimate_id):
    e = store.estimates.get(estimate_id)
    if e is None:
        raise err_not_found("WorkEstimate not found")
    return e


def _recompute(call, est):
    est["total_cents"] = estimate_total(
        call, est["labor_hours_est"], est["travel_miles_est"],
        est["parts_estimate_cents"], est["includes_tow"],
        est["tow_estimate_cents"])
    fleet_id = call.get("fleet_account_id")
    requires = False
    if fleet_id:
        fleet = store.fleets.get(fleet_id)
        if fleet is not None:
            requires = (est["total_cents"]
                        > fleet["per_call_authorization_limit_cents"])
    est["requires_fleet_approval"] = requires


def _estimate_call_fleet_check(est, uid, role):
    """FleetManager ownership: estimate's call's fleet must be the actor's."""
    if role != "FleetManager":
        return
    call = store.service_calls.get(est["service_call_id"])
    require_fleet_ownership(uid, call.get("fleet_account_id") if call else None)


@bp.route("/roadside/service-calls/<serviceCallId>/estimates", methods=["POST"])
def create_estimate(serviceCallId):
    uid, role = auth(WRITE_ROLES)
    call = get_call_or_404(serviceCallId)
    fields = [
        Field("labor_hours_est", "number", required=True, min_val=0),
        Field("travel_miles_est", "int", required=True, min_val=0),
        Field("parts_estimate_cents", "int", required=True, min_val=0),
        Field("includes_tow", "bool"),
        Field("tow_estimate_cents", "int", min_val=0),
        Field("expected_service_call_version", "int", required=True),
    ]
    vals = validate_body(request.get_json(silent=True), fields)
    ensure_not_cancelled(call)
    if vals["expected_service_call_version"] != call["version"]:
        raise err_stale_version()
    # supersede prior estimates in DRAFT / SUBMITTED / APPROVED
    for e in store.estimates.values():
        if (e["service_call_id"] == call["id"]
                and e["status"] in ("DRAFT", "SUBMITTED", "APPROVED")):
            e["status"] = "SUPERSEDED"
            touch(e, wall_now())
    rec = new_record()
    now = wall_now()
    rec.update({
        "_created": now, "_updated": now,
        "service_call_id": call["id"],
        "revision": 1,
        "labor_hours_est": vals["labor_hours_est"],
        "travel_miles_est": vals["travel_miles_est"],
        "parts_estimate_cents": vals["parts_estimate_cents"],
        "includes_tow": vals.get("includes_tow", False),
        "tow_estimate_cents": vals.get("tow_estimate_cents", 0),
        "total_cents": 0,
        "requires_fleet_approval": False,
        "status": "DRAFT",
        "decided_by": None,
        "decided_at": None,
        "submitted_at": None,
        "reject_reason": None,
    })
    _recompute(call, rec)  # may raise ERR_NO_ACTIVE_RATE_CARD
    store.estimates[rec["id"]] = rec
    touch(call, now)  # estimate create increments the call's version
    append_event(call["id"], "ESTIMATE_CREATED", role, uid)
    return success(serialize("estimate", rec), status=201)


@bp.route("/roadside/estimates/<estimateId>", methods=["GET"])
def get_estimate(estimateId):
    uid, role = auth(READ_ROLES)
    est = _get_estimate(estimateId)
    _estimate_call_fleet_check(est, uid, role)
    return success(serialize("estimate", est))


@bp.route("/roadside/estimates", methods=["GET"])
def list_estimates():
    uid, role = auth(LIST_ROLES)
    limit, offset = parse_pagination(request.args)
    call_f = request.args.get("service_call_id")
    status_f = request.args.get("status")
    items = sorted(store.estimates.values(), key=lambda r: r["_seq"])
    if role == "FleetManager":
        items = [e for e in items
                 if (store.service_calls.get(e["service_call_id"]) or {})
                 .get("fleet_account_id") == uid]
    if call_f is not None:
        items = [e for e in items if e["service_call_id"] == call_f]
    if status_f is not None:
        items = [e for e in items if e["status"] == status_f]
    page, total, has_more = paginate(items, limit, offset)
    return success([serialize("estimate", e) for e in page],
                   response_type="array",
                   pagination={"limit": limit, "offset": offset,
                               "total_count": total, "has_more": has_more})


@bp.route("/roadside/estimates/<estimateId>", methods=["PATCH"])
def patch_estimate(estimateId):
    auth(WRITE_ROLES)
    est = _get_estimate(estimateId)
    vals = validate_body(request.get_json(silent=True), ESTIMATE_INPUT_FIELDS)
    if est["status"] == "DRAFT":
        pass  # edit in place
    elif est["status"] == "REJECTED":
        est["status"] = "DRAFT"
        est["revision"] = est["revision"] + 1
    else:
        raise err_invalid_state(
            "Only a DRAFT estimate can be edited, or a REJECTED one revised")
    for k, v in vals.items():
        est[k] = v
    call = store.service_calls.get(est["service_call_id"])
    if call is not None:
        _recompute(call, est)
    touch(est, wall_now())
    return success(serialize("estimate", est))


@bp.route("/roadside/estimates/<estimateId>/submit", methods=["POST"])
def submit(estimateId):
    auth(WRITE_ROLES)
    est = _get_estimate(estimateId)
    validate_body(request.get_json(silent=True), [])
    if est["status"] != "DRAFT":
        raise err_invalid_state("Submit requires status DRAFT")
    est["status"] = "SUBMITTED"
    est["submitted_at"] = store.clock
    touch(est, wall_now())
    return success(serialize("estimate", est))


@bp.route("/roadside/estimates/<estimateId>/approve", methods=["POST"])
def approve(estimateId):
    uid, role = auth(["Dispatcher", "FleetManager", "OpsAdmin"])
    est = _get_estimate(estimateId)
    vals = validate_body(request.get_json(silent=True), [
        Field("override_cap", "bool"),
    ])
    if est["status"] != "SUBMITTED":
        raise err_invalid_state("Approve requires status SUBMITTED")
    call = store.service_calls.get(est["service_call_id"])
    fleet = None
    if call is not None and call.get("fleet_account_id"):
        fleet = store.fleets.get(call["fleet_account_id"])
    if role == "FleetManager":
        require_fleet_ownership(
            uid, fleet["id"] if fleet is not None else None)
    if fleet is not None:
        if fleet["status"] == "SUSPENDED":
            raise ApiError("ERR_FLEET_SUSPENDED",
                           "Estimate approval attempted for a SUSPENDED fleet",
                           409)
        if fleet["status"] == "CLOSED":
            raise ApiError("ERR_FLEET_CLOSED",
                           "Estimate approval attempted for a CLOSED fleet", 409)
        if est["total_cents"] > fleet["per_call_authorization_limit_cents"]:
            if role == "Dispatcher":
                raise ApiError(
                    "ERR_AUTHORIZATION_REQUIRED",
                    "Estimate total exceeds the fleet's per-call limit and the "
                    "actor is a Dispatcher", 409)
        projected = fleet_mtd(fleet["id"]) + est["total_cents"]
        if projected > fleet["monthly_spend_cap_cents"]:
            if not (role == "OpsAdmin" and vals.get("override_cap") is True):
                raise ApiError("ERR_MONTHLY_CAP_EXCEEDED",
                               "Projected month spend exceeds the fleet cap",
                               409)
    est["status"] = "APPROVED"
    est["decided_by"] = uid
    est["decided_at"] = store.clock
    touch(est, wall_now())
    if call is not None:
        append_event(call["id"], "ESTIMATE_APPROVED", role, uid)
    return success(serialize("estimate", est))


@bp.route("/roadside/estimates/<estimateId>/reject", methods=["POST"])
def reject(estimateId):
    uid, role = auth(["FleetManager", "OpsAdmin"])
    est = _get_estimate(estimateId)
    vals = validate_body(request.get_json(silent=True), [
        Field("reason", "string"),
    ])
    if est["status"] != "SUBMITTED":
        raise err_invalid_state("Reject requires status SUBMITTED")
    call = store.service_calls.get(est["service_call_id"])
    if role == "FleetManager":
        fleet_id = call.get("fleet_account_id") if call else None
        require_fleet_ownership(uid, fleet_id)
    est["status"] = "REJECTED"
    est["reject_reason"] = vals.get("reason")
    est["decided_by"] = uid
    est["decided_at"] = store.clock
    touch(est, wall_now())
    if call is not None:
        append_event(call["id"], "ESTIMATE_REJECTED", role, uid)
    return success(serialize("estimate", est))
