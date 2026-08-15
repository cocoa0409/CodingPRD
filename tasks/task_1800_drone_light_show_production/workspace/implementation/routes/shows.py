"""ShowEvent endpoints and actions."""

from datetime import timedelta
from flask import Blueprint, request

import errors
import validate as V
from db import DB, new_id, wall_created_at, clock_now, parse_dt, fmt_dt
from middleware import require_role, get_auth
from response import success_object, success_list
from services import calc
from services.show import (
    serialize_show, touch, recompute_posture, compute_posture, readiness_gates,
    perimeter_containment_planned, auth_covers_show, void_assignment,
    certified_go_evaluation_fresh,
)

bp = Blueprint("shows", __name__)


def _get_show(show_id):
    show = DB.show_events.get(show_id)
    if show is None:
        raise errors.not_found("ERR_SHOW_NOT_FOUND", "show not found")
    return show


# --------------------------------------------------------------------------
# CRUD

@bp.route("/api/show-events", methods=["POST"])
def create_show():
    body = V.get_body()
    V.reject_system_fields(body)
    V.req_fields(body, ["site_id", "name", "window_start", "window_end",
                        "drone_count_planned"])
    require_role("ProductionPlanner")

    site_id = body["site_id"]
    if not isinstance(site_id, str):
        raise errors.validation("site_id must be a string")
    name = V.req_string(body, "name")
    ws_raw, ws = V.req_dt(body, "window_start")
    we_raw, we = V.req_dt(body, "window_end")
    n = V.req_int(body, "drone_count_planned")
    if n < 1:
        raise errors.validation("drone_count_planned must be >= 1")
    if not (we > ws):
        raise errors.validation("window_end must be after window_start")

    bws_pair = V.opt_dt(body, "backup_window_start")
    bwe_pair = V.opt_dt(body, "backup_window_end")
    if (bws_pair is None) != (bwe_pair is None):
        raise errors.validation("backup window fields must be supplied together")
    bws_raw = bwe_raw = None
    bws = bwe = None
    if bws_pair is not None:
        bws_raw, bws = bws_pair
        bwe_raw, bwe = bwe_pair
        if bws < we + timedelta(hours=24):
            raise errors.validation("backup window must start >= 24h after window_end")
        if not (bwe > bws):
            raise errors.validation("backup_window_end must be after backup_window_start")

    site = DB.sites.get(site_id)
    if site is None:
        raise errors.not_found("ERR_SITE_NOT_FOUND", "site not found")

    now = clock_now()
    # within priority-8 (temporal), the catalog lists CONFLICT before IN_PAST
    if calc.show_window_conflict(site_id, ws, we):
        raise errors.conflict("ERR_SHOW_WINDOW_CONFLICT", "show window violates turnaround buffer")
    if not (ws > now):
        raise errors.conflict("ERR_SHOW_WINDOW_IN_PAST", "window_start must be strictly after the logical clock")

    contract, deposit, balance = calc.show_contract_pricing(n)
    sid = new_id()
    ts = wall_created_at()
    show = {
        "id": sid, "site_id": site_id, "name": name,
        "window_start": ws_raw, "window_end": we_raw,
        "drone_count_planned": n,
        "backup_window_start": bws_raw,
        "backup_window_end": bwe_raw,
        "backup_consumed": False,
        "lifecycle_status": "PLANNING",
        "payment_status": "DEPOSIT_DUE",
        "contract_value_cents": contract,
        "deposit_cents": deposit, "balance_cents": balance,
        "paid_total_cents": 0, "refunded_total_cents": 0,
        "cancellation_status": "NONE",
        "cancelled_at": None, "cancellation_tier": None,
        "refund_due_cents": None,
        "pinned_design_id": None, "pinned_safety_config_id": None,
        "pinned_authorization_id": None,
        "assigned_count": 0,
        "readiness_posture": "NOT_READY",
        "created_at": ts, "updated_at": ts, "version": 1,
    }
    DB.show_events[sid] = show
    DB.insertion_order["show_events"].append(sid)
    return success_object(serialize_show(show), 201)


@bp.route("/api/show-events/<showEventId>", methods=["GET"])
def get_show(showEventId):
    get_auth()
    return success_object(serialize_show(_get_show(showEventId)))


@bp.route("/api/show-events", methods=["GET"])
def list_shows():
    get_auth()
    limit, offset = V.pagination_params()
    site_id = request.args.get("site_id")
    lifecycle = request.args.get("lifecycle_status")
    items = [DB.show_events[i] for i in DB.insertion_order["show_events"]]
    if site_id is not None:
        items = [s for s in items if s["site_id"] == site_id]
    if lifecycle is not None:
        items = [s for s in items if s["lifecycle_status"] == lifecycle]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_show(s) for s in page], limit, offset, total)


# --------------------------------------------------------------------------
# actions

@bp.route("/api/show-events/<showEventId>/authorize", methods=["POST"])
def authorize_show(showEventId):
    body = V.get_body()
    V.reject_system_fields(body)
    V.req_fields(body, ["authorization_id"])
    require_role("ProductionPlanner")
    show = _get_show(showEventId)
    auth_id = body["authorization_id"]
    if not isinstance(auth_id, str):
        raise errors.validation("authorization_id must be a string")
    auth = DB.authorizations.get(auth_id)
    if auth is None or auth["show_event_id"] != show["id"]:
        raise errors.not_found("ERR_AUTHORIZATION_NOT_FOUND", "authorization not found for this show")

    # state
    if show["lifecycle_status"] != "DESIGN_LOCKED":
        raise errors.conflict("ERR_INVALID_STATE", "show must be DESIGN_LOCKED to authorize")

    # safety config gate
    config = DB.safety_configs.get(show.get("pinned_safety_config_id") or "")
    if config is None or config["status"] != "APPROVED":
        raise errors.conflict("ERR_SAFETY_CONFIG_NOT_APPROVED", "no APPROVED pinned safety configuration")

    # authorization approved
    if auth["status"] != "APPROVED":
        raise errors.conflict("ERR_AUTHORIZATION_NOT_APPROVED", "authorization is not APPROVED")

    # coverage
    if not auth_covers_show(auth, show):
        raise errors.conflict("ERR_AUTHORIZATION_WINDOW_INSUFFICIENT", "authorization window does not cover show window")

    # perimeter containment (PLANNED)
    if perimeter_containment_planned(show) != "VALID":
        raise errors.conflict("ERR_PERIMETER_INSUFFICIENT", "site cannot contain the required crowd distance")

    show["lifecycle_status"] = "AUTHORIZED"
    show["pinned_authorization_id"] = auth["id"]
    # grid may already be complete (e.g. after postpone->reschedule->re-authorize);
    # auto-advance AUTHORIZED -> READY when the pinned design's count is met and
    # perimeter containment holds.
    design = DB.designs.get(show.get("pinned_design_id") or "")
    if (design is not None and show["assigned_count"] == design["drone_count"]
            and perimeter_containment_planned(show) == "VALID"):
        show["lifecycle_status"] = "READY"
    recompute_posture(show)
    touch(show)
    return success_object(serialize_show(show))


@bp.route("/api/show-events/<showEventId>/certify-go", methods=["POST"])
def certify_go(showEventId):
    body = V.get_body()
    V.reject_system_fields(body)
    V.req_fields(body, ["evaluation_id"])
    require_role("SafetyOfficer")
    show = _get_show(showEventId)
    ev_id = body["evaluation_id"]
    if not isinstance(ev_id, str):
        raise errors.validation("evaluation_id must be a string")
    ev = DB.evaluations.get(ev_id)
    if ev is None or ev["show_event_id"] != show["id"]:
        raise errors.not_found("ERR_EVALUATION_NOT_FOUND", "evaluation not found for this show")

    if show["lifecycle_status"] != "READY":
        raise errors.conflict("ERR_INVALID_STATE", "show must be READY to certify go")

    if ev["status"] != "CERTIFIED":
        raise errors.conflict("ERR_EVALUATION_NOT_CERTIFIED", "evaluation is not CERTIFIED")
    if ev["verdict"] != "GO":
        raise errors.conflict("ERR_NO_GO_IN_EFFECT", "evaluation verdict is NO_GO")
    now = clock_now()
    if ev["certified_at"] is None or (now - parse_dt(ev["certified_at"])) > timedelta(minutes=calc.GO_VALIDITY_MINUTES):
        raise errors.conflict("ERR_EVALUATION_STALE", "certified GO evaluation is stale")

    show["lifecycle_status"] = "GO_CERTIFIED"
    show["readiness_posture"] = "GO"
    touch(show)
    return success_object(serialize_show(show))


@bp.route("/api/show-events/<showEventId>/execute", methods=["POST"])
def execute_show(showEventId):
    body = V.get_body()
    V.reject_system_fields(body)
    require_role("ProductionPlanner")
    show = _get_show(showEventId)

    if show["lifecycle_status"] != "GO_CERTIFIED":
        raise errors.conflict("ERR_INVALID_STATE", "show must be GO_CERTIFIED to execute")

    now = clock_now()
    ws = parse_dt(show["window_start"])
    we = parse_dt(show["window_end"])
    if not (ws <= now < we):
        raise errors.conflict("ERR_OUTSIDE_SHOW_WINDOW", "logical clock is outside the show window")

    if not certified_go_evaluation_fresh(show["id"]):
        raise errors.conflict("ERR_EVALUATION_STALE", "no fresh CERTIFIED GO evaluation")

    if show["payment_status"] != "PAID_IN_FULL":
        raise errors.conflict("ERR_SHOW_NOT_PAID_IN_FULL", "show is not PAID_IN_FULL")

    show["lifecycle_status"] = "EXECUTED"
    for aid in DB.insertion_order["assignments"]:
        a = DB.assignments[aid]
        if a["show_event_id"] == show["id"] and a["status"] == "ASSIGNED":
            a["status"] = "FLOWN"
            touch(a)
    recompute_posture(show)
    touch(show)
    return success_object(serialize_show(show))


@bp.route("/api/show-events/<showEventId>/postpone", methods=["POST"])
def postpone_show(showEventId):
    body = V.get_body()
    V.reject_system_fields(body)
    if "reason" in body and body["reason"] is not None and not isinstance(body["reason"], str):
        raise errors.validation("reason must be a string")
    require_role("ProductionPlanner")
    show = _get_show(showEventId)
    if show["lifecycle_status"] not in ("AUTHORIZED", "READY", "GO_CERTIFIED"):
        raise errors.conflict("ERR_INVALID_STATE", "show cannot be postponed from its current state")
    show["lifecycle_status"] = "POSTPONED"
    show["readiness_posture"] = "NOT_READY"
    touch(show)
    return success_object(serialize_show(show))


def _post_move_recompute(show):
    """PLANNING -> DESIGN_LOCKED auto-advance when pinned design still LOCKED."""
    design = DB.designs.get(show.get("pinned_design_id") or "")
    if design is not None and design["status"] == "LOCKED":
        show["lifecycle_status"] = "DESIGN_LOCKED"
    recompute_posture(show)


@bp.route("/api/show-events/<showEventId>/reschedule", methods=["POST"])
def reschedule_show(showEventId):
    body = V.get_body()
    V.reject_system_fields(body)
    V.req_fields(body, ["window_start", "window_end"])
    ws_raw, ws = V.req_dt(body, "window_start")
    we_raw, we = V.req_dt(body, "window_end")
    if not (we > ws):
        raise errors.validation("window_end must be after window_start")
    require_role("ProductionPlanner")
    show = _get_show(showEventId)
    if show["lifecycle_status"] != "POSTPONED":
        raise errors.conflict("ERR_INVALID_STATE", "show must be POSTPONED to reschedule")
    now = clock_now()
    if calc.show_window_conflict(show["site_id"], ws, we, exclude_show_id=show["id"]):
        raise errors.conflict("ERR_SHOW_WINDOW_CONFLICT", "show window violates turnaround buffer")
    if not (ws > now):
        raise errors.conflict("ERR_SHOW_WINDOW_IN_PAST", "window_start must be strictly after the logical clock")
    show["window_start"] = ws_raw
    show["window_end"] = we_raw
    show["lifecycle_status"] = "PLANNING"
    _post_move_recompute(show)
    touch(show)
    return success_object(serialize_show(show))


@bp.route("/api/show-events/<showEventId>/activate-backup", methods=["POST"])
def activate_backup(showEventId):
    body = V.get_body()
    V.reject_system_fields(body)
    require_role("ProductionPlanner")
    show = _get_show(showEventId)
    if show["lifecycle_status"] != "POSTPONED":
        raise errors.conflict("ERR_INVALID_STATE", "show must be POSTPONED to activate backup")
    now = clock_now()
    if (show["backup_window_start"] is None or show["backup_window_end"] is None
            or show["backup_consumed"]):
        raise errors.conflict("ERR_BACKUP_WINDOW_UNAVAILABLE", "no unconsumed backup window")
    bws = parse_dt(show["backup_window_start"])
    bwe = parse_dt(show["backup_window_end"])
    if not (bws > now):
        raise errors.conflict("ERR_BACKUP_WINDOW_UNAVAILABLE", "backup window start is not in the future")
    if calc.show_window_conflict(show["site_id"], bws, bwe, exclude_show_id=show["id"]):
        raise errors.conflict("ERR_SHOW_WINDOW_CONFLICT", "backup window violates turnaround buffer")
    show["window_start"] = show["backup_window_start"]
    show["window_end"] = show["backup_window_end"]
    show["backup_consumed"] = True
    show["backup_window_start"] = None
    show["backup_window_end"] = None
    show["lifecycle_status"] = "PLANNING"
    _post_move_recompute(show)
    touch(show)
    return success_object(serialize_show(show))


@bp.route("/api/show-events/<showEventId>/cancel", methods=["POST"])
def cancel_show(showEventId):
    body = V.get_body()
    V.reject_system_fields(body)
    if "reason" in body and body["reason"] is not None and not isinstance(body["reason"], str):
        raise errors.validation("reason must be a string")
    require_role("ProductionPlanner")
    show = _get_show(showEventId)
    if show["lifecycle_status"] in ("EXECUTED", "CANCELLED"):
        raise errors.conflict("ERR_INVALID_STATE", "show cannot be cancelled from a terminal state")

    now = clock_now()
    show["cancelled_at"] = fmt_dt(now)
    tier, refund = calc.cancellation_refund(show, now)
    show["cancellation_tier"] = tier
    show["refund_due_cents"] = refund
    if show["cancellation_status"] == "NONE":
        show["cancellation_status"] = "FILED"
    show["lifecycle_status"] = "CANCELLED"
    show["readiness_posture"] = "NOT_READY"

    # cascade: void ASSIGNED grid slots, release their drones
    from services.show import drone_release_if_unassigned
    for aid in DB.insertion_order["assignments"]:
        a = DB.assignments[aid]
        if a["show_event_id"] == show["id"] and a["status"] == "ASSIGNED":
            a["status"] = "VOIDED"
            touch(a)
            drone = DB.drones.get(a["drone_id"])
            if drone is not None:
                drone_release_if_unassigned(drone)
    show["assigned_count"] = 0
    touch(show)
    return success_object(serialize_show(show))


@bp.route("/api/show-events/<showEventId>/settle-cancellation", methods=["POST"])
def settle_cancellation(showEventId):
    body = V.get_body()
    V.reject_system_fields(body)
    require_role("ProductionPlanner")
    show = _get_show(showEventId)
    if not (show["lifecycle_status"] == "CANCELLED" and show["cancellation_status"] == "FILED"):
        raise errors.conflict("ERR_INVALID_STATE", "show must be CANCELLED with cancellation FILED")
    show["refunded_total_cents"] = show["refund_due_cents"]
    show["cancellation_status"] = "SETTLED"
    show["payment_status"] = "REFUNDED"
    touch(show)
    return success_object(serialize_show(show))


@bp.route("/api/show-events/<showEventId>/void-cancellation", methods=["POST"])
def void_cancellation(showEventId):
    body = V.get_body()
    V.reject_system_fields(body)
    require_role("ProductionPlanner")
    show = _get_show(showEventId)
    if not (show["lifecycle_status"] == "CANCELLED" and show["cancellation_status"] == "SETTLED"):
        raise errors.conflict("ERR_INVALID_STATE", "show must be CANCELLED with cancellation SETTLED")
    show["refunded_total_cents"] = 0
    show["cancellation_status"] = "VOIDED"
    paid = show["paid_total_cents"]
    if paid == 0:
        show["payment_status"] = "DEPOSIT_DUE"
    elif paid == show["deposit_cents"]:
        show["payment_status"] = "DEPOSIT_PAID"
    elif paid == show["contract_value_cents"]:
        show["payment_status"] = "PAID_IN_FULL"
    else:
        # amounts between defined anchors fall back conservatively
        if paid < show["deposit_cents"]:
            show["payment_status"] = "DEPOSIT_DUE"
        elif paid < show["contract_value_cents"]:
            show["payment_status"] = "DEPOSIT_PAID"
        else:
            show["payment_status"] = "PAID_IN_FULL"
    touch(show)
    return success_object(serialize_show(show))


@bp.route("/api/show-events/<showEventId>/record-payment", methods=["POST"])
def record_payment(showEventId):
    body = V.get_body()
    V.reject_system_fields(body)
    V.req_fields(body, ["kind", "amount_cents"])
    require_role("ProductionPlanner")
    show = _get_show(showEventId)
    kind = V.req_enum(body, "kind", {"DEPOSIT", "BALANCE"})
    amount = V.req_int(body, "amount_cents")
    if amount < 0:
        raise errors.validation("amount_cents must be >= 0")

    if kind == "DEPOSIT":
        if show["payment_status"] != "DEPOSIT_DUE":
            raise errors.conflict("ERR_INVALID_STATE", "deposit already recorded")
        if amount != show["deposit_cents"]:
            raise errors.conflict("ERR_PAYMENT_AMOUNT_MISMATCH", "amount must equal deposit_cents exactly")
        show["payment_status"] = "DEPOSIT_PAID"
    else:
        if show["payment_status"] != "DEPOSIT_PAID":
            raise errors.conflict("ERR_INVALID_STATE", "balance requires DEPOSIT_PAID")
        if amount != show["balance_cents"]:
            raise errors.conflict("ERR_PAYMENT_AMOUNT_MISMATCH", "amount must equal balance_cents exactly")
        show["payment_status"] = "PAID_IN_FULL"
    show["paid_total_cents"] += amount
    touch(show)
    return success_object(serialize_show(show))


# --------------------------------------------------------------------------
# computed reads

@bp.route("/api/show-events/<showEventId>/readiness", methods=["GET"])
def readiness(showEventId):
    get_auth()
    show = _get_show(showEventId)
    gates = readiness_gates(show)
    design = DB.designs.get(show.get("pinned_design_id") or "")
    data = {
        "posture": compute_posture(show),
        "gates": gates,
        "assigned_count": show["assigned_count"],
        "required_drone_count": design["drone_count"] if design else None,
    }
    return success_object(data)


@bp.route("/api/show-events/<showEventId>/perimeter-assessment", methods=["GET"])
def perimeter_assessment(showEventId):
    get_auth()
    show = _get_show(showEventId)
    from flask import request
    variant = request.args.get("variant", "PLANNED")
    if variant not in ("PLANNED", "AS_FLOWN"):
        raise errors.validation("variant must be PLANNED or AS_FLOWN")
    site = DB.sites.get(show["site_id"])
    if site is None:
        raise errors.not_found("ERR_SITE_NOT_FOUND", "site not found")

    if variant == "PLANNED":
        design = DB.designs.get(show.get("pinned_design_id") or "")
        if design is None:
            raise errors.conflict("ERR_DESIGN_NOT_LOCKED", "no pinned design for PLANNED variant")
        altitude = design["max_altitude_ft"]
        count = design["drone_count"]
    else:
        logs = [DB.flight_logs[fid] for fid in DB.insertion_order["flight_logs"]
                if DB.flight_logs[fid]["show_event_id"] == show["id"]]
        if not logs:
            raise errors.conflict("ERR_NO_FLIGHT_DATA", "show has no flight logs")
        altitude = max(l["max_altitude_reached_ft"] for l in logs)
        count = len(logs)

    req = calc.crowd_required_radius(altitude, count)
    half = calc.site_min_half_dim(site)
    from decimal import Decimal
    containment = "VALID" if (Decimal(str(req)) + Decimal(calc.CROWD_BUFFER_M)) <= Decimal(str(half)) else "INSUFFICIENT"
    data = {
        "variant": variant,
        "required_radius_m": req,
        "buffer_m": calc.CROWD_BUFFER_M,
        "site_min_half_dim_m": half,
        "containment": containment,
    }
    return success_object(data)
