"""GoNoGoEvaluation endpoints."""

from flask import Blueprint

import errors
import validate as V
from db import DB, new_id, wall_created_at, clock_now, fmt_dt
from middleware import require_role, get_auth
from response import success_object, success_list
from services import calc
from services.show import serialize_evaluation, touch, recompute_posture

bp = Blueprint("evaluations", __name__)


def _get_evaluation(eval_id):
    e = DB.evaluations.get(eval_id)
    if e is None:
        raise errors.not_found("ERR_EVALUATION_NOT_FOUND", "evaluation not found")
    return e


@bp.route("/api/go-no-go-evaluations", methods=["POST"])
def create_evaluation():
    body = V.get_body()
    V.reject_system_fields(body)
    V.req_fields(body, ["show_event_id"])
    require_role("SafetyOfficer")
    show_id = body["show_event_id"]
    if not isinstance(show_id, str):
        raise errors.validation("show_event_id must be a string")
    show = DB.show_events.get(show_id)
    if show is None:
        raise errors.not_found("ERR_SHOW_NOT_FOUND", "show not found")

    if show["lifecycle_status"] not in ("AUTHORIZED", "READY", "GO_CERTIFIED"):
        raise errors.conflict("ERR_INVALID_STATE", "show must be AUTHORIZED, READY, or GO_CERTIFIED")

    design = DB.designs.get(show.get("pinned_design_id") or "")
    if design is None or design["status"] != "LOCKED":
        raise errors.conflict("ERR_DESIGN_NOT_LOCKED", "show must hold a pinned LOCKED design")

    site = DB.sites.get(show["site_id"])
    if site is None:
        raise errors.not_found("ERR_SITE_NOT_FOUND", "site not found")

    now = clock_now()
    verdict, reasons, eff_wind, eff_gust = calc.go_no_go_verdict(site, design, now)

    eid = new_id()
    ts = wall_created_at()
    evaluation = {
        "id": eid, "show_event_id": show_id,
        "evaluated_at": fmt_dt(now),
        "verdict": verdict, "reason_codes": reasons,
        "effective_wind_limit_kt": eff_wind,
        "effective_gust_limit_kt": eff_gust,
        "status": "PROVISIONAL",
        "certified_at": None, "certified_by_user_id": None,
        "created_at": ts, "updated_at": ts, "version": 1,
    }
    DB.evaluations[eid] = evaluation
    DB.insertion_order["evaluations"].append(eid)
    # posture may change (g6 unaffected until certification, but recompute anyway)
    recompute_posture(show)
    return success_object(serialize_evaluation(evaluation), 201)


@bp.route("/api/go-no-go-evaluations/<evaluationId>", methods=["GET"])
def get_evaluation(evaluationId):
    get_auth()
    return success_object(serialize_evaluation(_get_evaluation(evaluationId)))


@bp.route("/api/go-no-go-evaluations", methods=["GET"])
def list_evaluations():
    get_auth()
    limit, offset = V.pagination_params()
    from flask import request
    show_id = V.opt_string(request.args, "show_event_id")
    verdict = V.opt_string(request.args, "verdict")
    status = V.opt_string(request.args, "status")
    items = [DB.evaluations[i] for i in DB.insertion_order["evaluations"]]
    if show_id is not None:
        items = [e for e in items if e["show_event_id"] == show_id]
    if verdict is not None:
        items = [e for e in items if e["verdict"] == verdict]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_evaluation(e) for e in page], limit, offset, total)


@bp.route("/api/go-no-go-evaluations/<evaluationId>/certify", methods=["POST"])
def certify_evaluation(evaluationId):
    body = V.get_body()
    V.reject_system_fields(body)
    uid, _ = require_role("SafetyOfficer")
    evaluation = _get_evaluation(evaluationId)
    show = DB.show_events.get(evaluation["show_event_id"])
    if show is None:
        raise errors.not_found("ERR_SHOW_NOT_FOUND", "show not found")

    if evaluation["status"] != "PROVISIONAL":
        raise errors.conflict("ERR_INVALID_STATE", "evaluation must be PROVISIONAL to certify")

    # SoD: caller != approved_by_user_id of pinned safety config
    config = DB.safety_configs.get(show.get("pinned_safety_config_id") or "")
    if config is not None and config.get("approved_by_user_id") is not None \
            and uid == config["approved_by_user_id"]:
        raise errors.sod("certifier must differ from the pinned configuration approver")

    evaluation["status"] = "CERTIFIED"
    evaluation["certified_at"] = fmt_dt(clock_now())
    evaluation["certified_by_user_id"] = uid
    touch(evaluation)
    recompute_posture(show)
    return success_object(serialize_evaluation(evaluation))
