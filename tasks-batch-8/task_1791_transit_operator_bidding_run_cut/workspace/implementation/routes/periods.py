"""Sign-up period endpoints: CRUD, run cutting, lifecycle pipeline,
mid-pick schedule revisions, and period-scoped collections."""
from flask import Blueprint, request

from db import db, mint, touch, ser
from errors import (
    ApiError,
    invalid_state,
    validation,
    ERR_DUPLICATE_RUN_NUMBER,
    ERR_DATE_OUT_OF_RANGE,
    ERR_SPREAD_LIMIT_EXCEEDED,
)
from helpers import (
    body_json,
    req_str,
    req_int,
    opt_int,
    req_date,
    req_field,
    validate_piece_shape,
    check_piece_geometry,
    clean_pieces,
    compute_run_numbers,
    ceil_div_100,
    get_period_or_404,
    paginated,
)
from middleware import authenticate, require_roles, ALL_ROLES, READ_SO_OP_UR
from response import ok_obj
from services.workflow import create_assignment, withdraw_run_cascade

bp = Blueprint("periods", __name__)

SO = ["SchedulingOfficer"]


def _truthy_flag(name):
    raw = request.args.get(name)
    if raw is None:
        return False
    return str(raw).lower() in ("true", "1", "yes")


def _period_runs(pid):
    return [r for r in db.runs.values() if r["sign_up_period_id"] == pid]


def _period_bids(pid):
    return [b for b in db.bid_entries.values() if b["sign_up_period_id"] == pid]


# ---------------------------------------------------------------------------
# Periods
# ---------------------------------------------------------------------------

@bp.post("/api/sign-up-periods")
def create_period():
    auth = authenticate()
    require_roles(auth, SO)
    body = body_json()
    name = req_str(body, "name")
    start = req_date(body, "effective_start_date")
    end = req_date(body, "effective_end_date")
    if end < start:
        raise validation("effective_end_date must not precede effective_start_date")
    spread_limit = req_int(body, "spread_limit_minutes", 480, 900)
    paid_break = req_int(body, "paid_break_minutes", 0, 120)
    daily_ot = opt_int(body, "daily_ot_threshold_minutes", 480, 420, 600)
    weekly_ot = opt_int(body, "weekly_ot_threshold_minutes", 2400, 2100, 2700)
    ratio = req_int(body, "extra_board_ratio_pct", 5, 40)

    p = mint()
    p.update(
        {
            "name": name,
            "effective_start_date": start,
            "effective_end_date": end,
            "spread_limit_minutes": spread_limit,
            "paid_break_minutes": paid_break,
            "daily_ot_threshold_minutes": daily_ot,
            "weekly_ot_threshold_minutes": weekly_ot,
            "extra_board_ratio_pct": ratio,
            "schedule_revision": 1,
            "status": "DRAFT",
            "picked_through_rank": 0,
        }
    )
    db.sign_up_periods[p["id"]] = p
    return ok_obj(ser(p), 201)


@bp.get("/api/sign-up-periods")
def list_periods():
    auth = authenticate()
    require_roles(auth, ALL_ROLES)
    items = list(db.sign_up_periods.values())
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return paginated(items)


@bp.get("/api/sign-up-periods/<pid>")
def get_period(pid):
    auth = authenticate()
    require_roles(auth, ALL_ROLES)
    return ok_obj(ser(get_period_or_404(pid)))


# ---------------------------------------------------------------------------
# Runs beneath a period
# ---------------------------------------------------------------------------

@bp.post("/api/sign-up-periods/<pid>/runs")
def create_run(pid):
    auth = authenticate()
    require_roles(auth, SO)
    period = get_period_or_404(pid)
    body = body_json()
    run_number = req_str(body, "run_number")
    service_date = req_date(body, "service_date")
    pieces = req_field(body, "pieces")
    validate_piece_shape(pieces)

    if period["status"] != "DRAFT":
        raise invalid_state("Runs may be cut only beneath a DRAFT sign-up period")
    # 1. piece geometry
    check_piece_geometry(pieces)
    # 2. run_number unique within (sign_up_period_id, schedule_revision)
    for r in _period_runs(pid):
        if (
            r["schedule_revision"] == period["schedule_revision"]
            and r["run_number"] == run_number
        ):
            raise ApiError(
                ERR_DUPLICATE_RUN_NUMBER,
                "run_number already exists within this sign-up period and schedule revision",
                409,
            )
    # 3. service_date within the effective window
    if not (period["effective_start_date"] <= service_date <= period["effective_end_date"]):
        raise ApiError(
            ERR_DATE_OUT_OF_RANGE,
            "service_date outside the sign-up effective window",
            422,
        )

    spread, platform, paid = compute_run_numbers(period, pieces)
    if _truthy_flag("strict") and spread > period["spread_limit_minutes"]:
        raise ApiError(
            ERR_SPREAD_LIMIT_EXCEEDED,
            "run spread exceeds spread_limit_minutes under strict creation",
            422,
        )

    run = mint()
    run.update(
        {
            "sign_up_period_id": pid,
            "schedule_revision": period["schedule_revision"],
            "run_number": run_number,
            "service_date": service_date,
            "pieces": clean_pieces(pieces),
            "spread_minutes": spread,
            "platform_minutes": platform,
            "paid_minutes": paid,
            "status": "CUT",
            "awarded_operator_id": None,
        }
    )
    db.runs[run["id"]] = run
    touch(period)  # creating a run advances the parent period version
    return ok_obj(ser(run), 201)


@bp.get("/api/sign-up-periods/<pid>/runs")
def list_runs(pid):
    auth = authenticate()
    require_roles(auth, ALL_ROLES)
    get_period_or_404(pid)
    items = _period_runs(pid)
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    rev = request.args.get("schedule_revision")
    if rev is not None:
        try:
            rev = int(rev)
        except (TypeError, ValueError):
            raise validation("Query parameter schedule_revision must be an integer")
        items = [r for r in items if r["schedule_revision"] == rev]
    return paginated(items)


# ---------------------------------------------------------------------------
# Lifecycle: cut -> post -> open picking -> adjudicate -> lock -> implement
# ---------------------------------------------------------------------------

@bp.post("/api/sign-up-periods/<pid>/cut-runs")
def cut_runs(pid):
    auth = authenticate()
    require_roles(auth, SO)
    period = get_period_or_404(pid)
    if period["status"] != "DRAFT":
        raise invalid_state("cut-runs requires the period to be DRAFT")
    current = [
        r for r in _period_runs(pid) if r["schedule_revision"] == period["schedule_revision"]
    ]
    if not current:
        raise invalid_state("No runs exist under the period's current schedule revision")
    for r in current:
        if r["status"] == "CUT":
            r["status"] = (
                "VALIDATED"
                if r["spread_minutes"] <= period["spread_limit_minutes"]
                else "WITHDRAWN"
            )
            touch(r)
    period["status"] = "RUNS_CUT"
    touch(period)
    return ok_obj(ser(period))


@bp.post("/api/sign-up-periods/<pid>/post-runs")
def post_runs(pid):
    auth = authenticate()
    require_roles(auth, SO)
    period = get_period_or_404(pid)
    if period["status"] != "RUNS_CUT":
        raise invalid_state("post-runs requires the period to be RUNS_CUT")
    validated = [r for r in _period_runs(pid) if r["status"] == "VALIDATED"]
    if not validated:
        raise invalid_state("At least one VALIDATED run is required to post")
    for r in validated:
        r["status"] = "POSTED"
        touch(r)
    posted_count = len([r for r in _period_runs(pid) if r["status"] == "POSTED"])
    slot_count = ceil_div_100(posted_count * period["extra_board_ratio_pct"])
    for i in range(1, slot_count + 1):
        slot = mint()
        slot.update(
            {
                "sign_up_period_id": pid,
                "operator_id": None,
                "slot_index": i,
                "status": "OPEN",
            }
        )
        db.extra_board_slots[slot["id"]] = slot
    period["status"] = "OPEN"
    touch(period)
    return ok_obj(ser(period))


@bp.post("/api/sign-up-periods/<pid>/open-picking")
def open_picking(pid):
    auth = authenticate()
    require_roles(auth, SO)
    period = get_period_or_404(pid)
    if period["status"] != "OPEN":
        raise invalid_state("open-picking requires the period to be OPEN")
    if any(b["status"] == "AWARDED" for b in _period_bids(pid)):
        raise invalid_state("Picking cannot be opened while awarded bids exist")
    period["picked_through_rank"] = 0
    period["status"] = "PICKING"
    touch(period)
    return ok_obj(ser(period))


@bp.post("/api/sign-up-periods/<pid>/adjudicate-next")
def adjudicate_next(pid):
    auth = authenticate()
    require_roles(auth, SO)
    period = get_period_or_404(pid)
    if period["status"] != "PICKING":
        raise invalid_state("adjudicate-next requires the period to be PICKING")

    submitted = [b for b in _period_bids(pid) if b["status"] == "SUBMITTED"]
    bidder_ids = {b["operator_id"] for b in submitted}
    candidates = [
        o
        for o in db.operators.values()
        if o["status"] == "ACTIVE"
        and o["id"] in bidder_ids
        and o["seniority_rank"] > period["picked_through_rank"]
    ]
    if not candidates:
        raise invalid_state("No eligible operator remains to be adjudicated")
    op = min(candidates, key=lambda o: o["seniority_rank"])

    sheet = sorted(
        [b for b in submitted if b["operator_id"] == op["id"]],
        key=lambda b: b["preference_rank"],
    )
    winner = None
    for b in sheet:
        run = db.runs.get(b["run_id"])
        if run is not None and run["status"] == "POSTED":
            winner = (b, run)
            break

    if winner is not None:
        bid, run = winner
        bid["status"] = "AWARDED"
        touch(bid)
        run["status"] = "AWARDED"
        run["awarded_operator_id"] = op["id"]
        touch(run)
    else:
        # Demotion to the extra board: fill the lowest OPEN slot if one exists
        op["status"] = "EXTRA_BOARD"
        open_slots = sorted(
            (
                s
                for s in db.extra_board_slots.values()
                if s["sign_up_period_id"] == pid and s["status"] == "OPEN"
            ),
            key=lambda s: s["slot_index"],
        )
        if open_slots:
            slot = open_slots[0]
            slot["status"] = "FILLED"
            slot["operator_id"] = op["id"]
            touch(slot)
            op["board_position"] = slot["slot_index"]
        touch(op)

    for b in sheet:
        if b["status"] == "SUBMITTED":
            b["status"] = "PASSED"
            touch(b)

    period["picked_through_rank"] = op["seniority_rank"]
    touch(period)
    return ok_obj(ser(period))


@bp.post("/api/sign-up-periods/<pid>/lock")
def lock_period(pid):
    auth = authenticate()
    require_roles(auth, SO)
    period = get_period_or_404(pid)
    if period["status"] != "PICKING":
        raise invalid_state("lock requires the period to be PICKING")
    submitted = [b for b in _period_bids(pid) if b["status"] == "SUBMITTED"]
    bidder_ids = {b["operator_id"] for b in submitted}
    pending = [
        o
        for o in db.operators.values()
        if o["status"] == "ACTIVE"
        and o["id"] in bidder_ids
        and o["seniority_rank"] > period["picked_through_rank"]
    ]
    if pending:
        raise invalid_state("Unadjudicated bidders remain beyond picked_through_rank")
    for r in _period_runs(pid):
        if r["status"] == "POSTED":
            r["status"] = "EXTRA_BOARD_HELD"
            touch(r)
    for s in db.extra_board_slots.values():
        if s["sign_up_period_id"] == pid and s["status"] == "OPEN":
            s["status"] = "EXHAUSTED"
            touch(s)
    period["status"] = "LOCKED"
    touch(period)
    return ok_obj(ser(period))


@bp.post("/api/sign-up-periods/<pid>/implement")
def implement_period(pid):
    auth = authenticate()
    require_roles(auth, SO)
    period = get_period_or_404(pid)
    if period["status"] != "LOCKED":
        raise invalid_state("implement requires the period to be LOCKED")
    bad = [
        r
        for r in _period_runs(pid)
        if r["status"] not in ("AWARDED", "EXTRA_BOARD_HELD", "WITHDRAWN")
    ]
    if bad:
        raise invalid_state("All runs must be AWARDED, EXTRA_BOARD_HELD, or WITHDRAWN")

    awarded = sorted(
        (r for r in _period_runs(pid) if r["status"] == "AWARDED"),
        key=lambda r: (r["created_at"], r["_seq"]),
    )
    for r in awarded:
        if period["effective_start_date"] <= r["service_date"] <= period["effective_end_date"]:
            create_assignment(
                period,
                r["awarded_operator_id"],
                r["id"],
                r["service_date"],
                "BID_AWARD",
                r["paid_minutes"],
            )
    filled = sorted(
        (
            s
            for s in db.extra_board_slots.values()
            if s["sign_up_period_id"] == pid and s["status"] == "FILLED"
        ),
        key=lambda s: s["slot_index"],
    )
    for s in filled:
        create_assignment(
            period,
            s["operator_id"],
            None,
            period["effective_start_date"],
            "EXTRA_BOARD_FILL",
            0,
        )
        s["status"] = "EXHAUSTED"
        touch(s)
    period["status"] = "IMPLEMENTED"
    touch(period)
    return ok_obj(ser(period))


# ---------------------------------------------------------------------------
# Mid-pick service change
# ---------------------------------------------------------------------------

@bp.post("/api/sign-up-periods/<pid>/schedule-revisions")
def schedule_revision(pid):
    auth = authenticate()
    require_roles(auth, SO)
    period = get_period_or_404(pid)
    body = body_json()
    new_runs = req_field(body, "new_runs")
    if not isinstance(new_runs, list) or len(new_runs) == 0:
        raise validation("new_runs must be a non-empty list")
    shaped = []
    for entry in new_runs:
        if not isinstance(entry, dict):
            raise validation("each new_runs entry must be an object")
        rn = req_str(entry, "run_number")
        sd = req_date(entry, "service_date")
        pcs = req_field(entry, "pieces")
        validate_piece_shape(pcs)
        shaped.append((rn, sd, pcs))

    if period["status"] != "PICKING":
        raise invalid_state("schedule revisions require the period to be PICKING")
    for _, _, pcs in shaped:
        check_piece_geometry(pcs)

    prior_revision = period["schedule_revision"]
    period["schedule_revision"] = prior_revision + 1

    # Withdraw prior-revision runs still POSTED (AWARDED runs untouched),
    # cascading to their SUBMITTED bids and any SCHEDULED assignments.
    for r in _period_runs(pid):
        if r["schedule_revision"] == prior_revision and r["status"] == "POSTED":
            r["status"] = "WITHDRAWN"
            touch(r)
            withdraw_run_cascade(r)

    # Cut the replacement runs under the new revision, validate by the spread
    # rule, and post every VALIDATED one immediately.
    for rn, sd, pcs in shaped:
        spread, platform, paid = compute_run_numbers(period, pcs)
        run = mint()
        run.update(
            {
                "sign_up_period_id": pid,
                "schedule_revision": period["schedule_revision"],
                "run_number": rn,
                "service_date": sd,
                "pieces": clean_pieces(pcs),
                "spread_minutes": spread,
                "platform_minutes": platform,
                "paid_minutes": paid,
                "status": (
                    "VALIDATED"
                    if spread <= period["spread_limit_minutes"]
                    else "WITHDRAWN"
                ),
                "awarded_operator_id": None,
            }
        )
        if run["status"] == "VALIDATED":
            run["status"] = "POSTED"
        db.runs[run["id"]] = run

    period["picked_through_rank"] = 0
    period["status"] = "RUNS_CUT"
    touch(period)
    return ok_obj(ser(period), 201)


@bp.post("/api/sign-up-periods/<pid>/cancel")
def cancel_period(pid):
    auth = authenticate()
    require_roles(auth, SO)
    period = get_period_or_404(pid)
    if period["status"] != "DRAFT":
        raise invalid_state("Only a DRAFT sign-up period may be cancelled")
    for r in _period_runs(pid):
        if r["status"] in ("CUT", "VALIDATED"):
            r["status"] = "WITHDRAWN"
            touch(r)
    period["status"] = "CANCELLED"
    touch(period)
    return ok_obj(ser(period))


# ---------------------------------------------------------------------------
# Period-scoped collections: bid entries, board slots, vacation slots
# ---------------------------------------------------------------------------

@bp.get("/api/sign-up-periods/<pid>/bid-entries")
def list_period_bids(pid):
    auth = authenticate()
    require_roles(auth, READ_SO_OP_UR)
    get_period_or_404(pid)
    items = _period_bids(pid)
    op = request.args.get("operator_id")
    if op is not None:
        items = [b for b in items if b["operator_id"] == op]
    status = request.args.get("status")
    if status is not None:
        items = [b for b in items if b["status"] == status]
    return paginated(items)


@bp.get("/api/sign-up-periods/<pid>/extra-board-slots")
def list_period_board_slots(pid):
    auth = authenticate()
    require_roles(auth, READ_SO_OP_UR)
    get_period_or_404(pid)
    items = [s for s in db.extra_board_slots.values() if s["sign_up_period_id"] == pid]
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    return paginated(items)
