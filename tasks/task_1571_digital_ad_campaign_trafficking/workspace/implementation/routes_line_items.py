"""Routes: line items (CRUD, OCC-guarded PATCH, lifecycle transitions)."""
from flask import Blueprint, request

from core import (
    db, envelope_ok, paginate, sorted_items, require_role, ANY_ROLE, get_body,
    req_str, req_int, req_enum, req_date, opt_int, today,
    err_not_found, err_invalid_state, err_invalid_request, err_stale_version,
    err_fraud_hold, err_flight_window, err_flight_not_started,
    err_no_tagged_creative, err_io_not_approved, err_budget_exceeded,
    stamp_new, touch, is_int, rhu_int,
)
from domain import (
    li_view, get_li, get_io, creatives_of_li, budget_cents_of, io_booked_budget,
    activate_creative, pause_line_item, complete_line_item, cancel_line_item,
)

bp = Blueprint("line_items", __name__)

PACING_MODES = ("EVEN", "ASAP")
LI_ACTIONS = ("TRAFFIC", "LAUNCH", "PAUSE", "RESUME", "COMPLETE", "CANCEL", "CLEAR_FRAUD")


def _check_flight_window(io, start, end):
    if start < io["_flight_start"] or end > io["_flight_end"]:
        raise err_flight_window()


def _check_budget(io, extra_cents):
    if io_booked_budget(io["id"]) + extra_cents > io["total_budget_cents"]:
        raise err_budget_exceeded()


@bp.route("/line-items", methods=["POST"])
def create_line_item():
    require_role("Trafficker")
    body = get_body()
    io_id = req_str(body, "io_id")
    name = req_str(body, "name")
    goal = req_int(body, "goal_impressions", minimum=1)
    cpm = req_int(body, "cpm_rate_cents", minimum=1)
    sd_raw, sd = req_date(body, "start_date")
    ed_raw, ed = req_date(body, "end_date")
    pacing_mode = req_enum(body, "pacing_mode", PACING_MODES)
    targeting = body.get("targeting", {})
    if targeting is None:
        targeting = {}
    if not isinstance(targeting, dict):
        raise err_invalid_request("Field 'targeting' must be an object")
    fcap = opt_int(body, "frequency_cap_max_impressions", minimum=1,
                   allow_null=True, default=None)
    fwin = opt_int(body, "frequency_cap_window_hours", minimum=1, default=24)
    if ed < sd:
        raise err_invalid_request("end_date must be on or after start_date")

    io = get_io(io_id)
    if io is None:
        raise err_not_found("Insertion order not found")
    if io["status"] in ("COMPLETED", "CLOSED", "CANCELLED"):
        raise err_invalid_state("Cannot create line items under a %s insertion order" % io["status"])
    _check_flight_window(io, sd, ed)

    li = {
        "io_id": io_id,
        "name": name,
        "goal_impressions": goal,
        "cpm_rate_cents": cpm,
        "start_date": sd_raw,
        "end_date": ed_raw,
        "_start": sd,
        "_end": ed,
        "pacing_mode": pacing_mode,
        "targeting": targeting,
        "frequency_cap_max_impressions": fcap,
        "frequency_cap_window_hours": fwin,
        "status": "DRAFT",
        "fraud_posture": "CLEAR",
    }
    _check_budget(io, budget_cents_of(li))
    stamp_new(li)
    db.line_items[li["id"]] = li
    return envelope_ok(li_view(li), status=201)


@bp.route("/line-items", methods=["GET"])
def list_line_items():
    require_role(*ANY_ROLE)
    items = list(db.line_items.values())
    io_id = request.args.get("io_id")
    status = request.args.get("status")
    if io_id is not None:
        items = [li for li in items if li["io_id"] == io_id]
    if status is not None:
        items = [li for li in items if li["status"] == status]
    return paginate([li_view(li) for li in sorted_items(items)])


@bp.route("/line-items/<li_id>", methods=["GET"])
def get_one_line_item(li_id):
    require_role(*ANY_ROLE)
    li = get_li(li_id)
    if li is None:
        raise err_not_found("Line item not found")
    return envelope_ok(li_view(li), status=200)


@bp.route("/line-items/<li_id>", methods=["PATCH"])
def patch_line_item(li_id):
    require_role("Trafficker")
    body = get_body()
    # Schema: expected_line_item_version is required
    if "expected_line_item_version" not in body or not is_int(body.get("expected_line_item_version")):
        raise err_invalid_request("Field 'expected_line_item_version' is required and must be an integer")
    expected = body["expected_line_item_version"]

    new_goal = new_cpm = None
    new_pacing = None
    new_sd_raw = new_sd = new_ed_raw = new_ed = None
    fcap_given = False
    new_fcap = None
    new_fwin = None

    if "goal_impressions" in body and body["goal_impressions"] is not None:
        new_goal = req_int(body, "goal_impressions", minimum=1)
    if "cpm_rate_cents" in body and body["cpm_rate_cents"] is not None:
        new_cpm = req_int(body, "cpm_rate_cents", minimum=1)
    if "pacing_mode" in body and body["pacing_mode"] is not None:
        new_pacing = req_enum(body, "pacing_mode", PACING_MODES)
    if "start_date" in body and body["start_date"] is not None:
        new_sd_raw, new_sd = req_date(body, "start_date")
    if "end_date" in body and body["end_date"] is not None:
        new_ed_raw, new_ed = req_date(body, "end_date")
    if "frequency_cap_max_impressions" in body:
        fcap_given = True
        new_fcap = opt_int(body, "frequency_cap_max_impressions", minimum=1,
                           allow_null=True, default=None)
    if "frequency_cap_window_hours" in body and body["frequency_cap_window_hours"] is not None:
        new_fwin = req_int(body, "frequency_cap_window_hours", minimum=1)

    li = get_li(li_id)
    if li is None:
        raise err_not_found("Line item not found")

    # OCC check (priority 5) precedes the state check (priority 6)
    if expected != li["version"]:
        raise err_stale_version()
    if li["status"] not in ("LIVE", "PAUSED"):
        raise err_invalid_state("PATCH is allowed only while the line item is LIVE or PAUSED")

    merged_sd = new_sd if new_sd is not None else li["_start"]
    merged_ed = new_ed if new_ed is not None else li["_end"]
    if merged_ed < merged_sd:
        raise err_invalid_request("end_date must be on or after start_date")

    io = get_io(li["io_id"])
    _check_flight_window(io, merged_sd, merged_ed)

    merged_goal = new_goal if new_goal is not None else li["goal_impressions"]
    merged_cpm = new_cpm if new_cpm is not None else li["cpm_rate_cents"]
    new_budget = rhu_int(merged_goal * merged_cpm, 1000)
    _check_budget(io, new_budget - budget_cents_of(li))

    # Apply
    if new_goal is not None:
        li["goal_impressions"] = new_goal
    if new_cpm is not None:
        li["cpm_rate_cents"] = new_cpm
    if new_pacing is not None:
        li["pacing_mode"] = new_pacing
    if new_sd is not None:
        li["start_date"] = new_sd_raw
        li["_start"] = new_sd
    if new_ed is not None:
        li["end_date"] = new_ed_raw
        li["_end"] = new_ed
    if fcap_given:
        li["frequency_cap_max_impressions"] = new_fcap
    if new_fwin is not None:
        li["frequency_cap_window_hours"] = new_fwin
    touch(li)
    return envelope_ok(li_view(li), status=200)


@bp.route("/line-items/<li_id>/transition", methods=["POST"])
def line_item_transition(li_id):
    require_role("Trafficker")
    body = get_body()
    action = req_enum(body, "action", LI_ACTIONS)
    li = get_li(li_id)
    if li is None:
        raise err_not_found("Line item not found")
    status = li["status"]

    if action == "TRAFFIC":
        if status != "DRAFT":
            raise err_invalid_state("TRAFFIC requires status DRAFT")
        if not any(c["status"] == "TAGGED" for c in creatives_of_li(li["id"])):
            raise err_no_tagged_creative("TRAFFIC requires at least one TAGGED creative")
        li["status"] = "TRAFFICKED"
        touch(li)

    elif action == "LAUNCH":
        if status != "TRAFFICKED":
            raise err_invalid_state("LAUNCH requires status TRAFFICKED")
        if li["fraud_posture"] != "CLEAR":
            raise err_fraud_hold()
        cur = today()
        if cur < li["_start"] or cur > li["_end"]:
            raise err_flight_not_started("LAUNCH requires the current date within [start_date, end_date]")
        if not any(c["status"] in ("TAGGED", "LIVE") for c in creatives_of_li(li["id"])):
            raise err_no_tagged_creative("LAUNCH requires at least one TAGGED or LIVE creative")
        io = get_io(li["io_id"])
        if io["status"] not in ("APPROVED", "ACTIVE"):
            raise err_io_not_approved()
        for c in creatives_of_li(li["id"]):
            if c["status"] == "TAGGED":
                activate_creative(c)
        li["status"] = "LIVE"
        touch(li)

    elif action == "PAUSE":
        if status != "LIVE":
            raise err_invalid_state("PAUSE requires status LIVE")
        pause_line_item(li)

    elif action == "RESUME":
        if status != "PAUSED":
            raise err_invalid_state("RESUME requires status PAUSED")
        if li["fraud_posture"] != "CLEAR":
            raise err_fraud_hold()
        if today() > li["_end"]:
            raise err_flight_not_started("RESUME requires the current date on or before end_date")
        for c in creatives_of_li(li["id"]):
            if c["status"] == "PAUSED":
                activate_creative(c)
        li["status"] = "LIVE"
        touch(li)

    elif action == "COMPLETE":
        if status not in ("LIVE", "PAUSED"):
            raise err_invalid_state("COMPLETE requires status LIVE or PAUSED")
        if not (today() > li["_end"]):
            raise err_invalid_state("COMPLETE requires the current date to be after end_date")
        complete_line_item(li)

    elif action == "CANCEL":
        if status not in ("DRAFT", "TRAFFICKED", "LIVE", "PAUSED"):
            raise err_invalid_state("CANCEL not allowed from status %s" % status)
        cancel_line_item(li)

    elif action == "CLEAR_FRAUD":
        if status not in ("LIVE", "PAUSED"):
            raise err_invalid_state("CLEAR_FRAUD requires status LIVE or PAUSED")
        if li["fraud_posture"] != "BREACH":
            raise err_invalid_state("CLEAR_FRAUD requires fraud_posture BREACH")
        li["fraud_posture"] = "CLEAR"
        touch(li)

    return envelope_ok(li_view(li), status=200)
