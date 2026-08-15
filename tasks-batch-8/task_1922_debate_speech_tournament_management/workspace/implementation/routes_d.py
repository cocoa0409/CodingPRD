"""Routes: ballots, hired-judge-contracts, logistics-orders."""
from datetime import timedelta

from flask import Blueprint, request

from core import (
    ApiError, auth_context, clock, db, get_body, new_id, now_ts, ok, paginate,
    require_role, touch, validation_error,
)
from services import (
    COMPETITION_STATUS_SET, get_or_404, hired_fee, pairing_member_ids,
    recompute_division_stats, round_pairings, school_derived, serialize_ballot,
    serialize_contract, serialize_order, tournament_divisions,
    tournament_of_school, order_live_fields, verified_ballot_of_pairing,
)

bp = Blueprint("routes_d", __name__)

TD = ["TournamentDirector"]
COACH = ["SchoolCoach"]
TAB = ["TabStaff"]
JUDGE = ["Judge"]


def _ownership_school(uid, school_id):
    if uid != school_id:
        raise ApiError("ERR_RESOURCE_OWNERSHIP_MISMATCH", 403,
                       "A SchoolCoach may only act on their own school's resources")


# ---------------------------------------------------------------------------
# Ballot content validation
# ---------------------------------------------------------------------------


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def validate_debate_ballot(pairing, winner, points, allow_lpw):
    members = pairing_member_ids(pairing["id"])
    # Low-point-win check outranks field validity when computable.
    if winner is not None and winner in members and isinstance(points, dict):
        vals = {}
        computable = True
        for m in members:
            v = points.get(m)
            if _is_int(v):
                vals[m] = v
            else:
                computable = False
        others = [m for m in members if m != winner]
        if computable and len(others) == 1:
            if vals[winner] < vals[others[0]] and not allow_lpw:
                raise ApiError("ERR_LOW_POINT_WIN_NOT_FLAGGED", 422,
                               "Winner's total speaker points are below the loser's without allow_low_point_win")
    if winner is None or winner not in members:
        raise ApiError("ERR_WINNER_NOT_IN_PAIRING", 422,
                       "winner_entry_id must be a member of the pairing")
    if not isinstance(points, dict):
        raise ApiError("ERR_SPEAKER_POINTS_OUT_OF_RANGE", 422,
                       "speaker_points must map every pairing member to an integer in [20,30]")
    for m in members:
        v = points.get(m)
        if not _is_int(v) or v < 20 or v > 30:
            raise ApiError("ERR_SPEAKER_POINTS_OUT_OF_RANGE", 422,
                           "speaker_points must map every pairing member to an integer in [20,30]")


def validate_speech_ballot(pairing, ranks):
    members = pairing_member_ids(pairing["id"])
    size = len(members)
    if not isinstance(ranks, dict):
        raise ApiError("ERR_RANK_INVALID", 422,
                       "ranks must map every section member to an integer in [1, section size]")
    for m in members:
        v = ranks.get(m)
        if not _is_int(v) or v < 1 or v > size:
            raise ApiError("ERR_RANK_INVALID", 422,
                           "ranks must map every section member to an integer in [1, section size]")
    seen = [ranks[m] for m in members]
    if len(set(seen)) != len(seen):
        raise ApiError("ERR_DUPLICATE_RANK_IN_SECTION", 422,
                       "Two section members share the same rank in one ballot")


def validate_ballot_content(pairing, body):
    if pairing["format"] == "HEAD_TO_HEAD":
        validate_debate_ballot(
            pairing,
            body.get("winner_entry_id"),
            body.get("speaker_points"),
            bool(body.get("allow_low_point_win", False)),
        )
    else:
        validate_speech_ballot(pairing, body.get("ranks"))


# ---------------------------------------------------------------------------
# Ballots
# ---------------------------------------------------------------------------


@bp.route("/ballots", methods=["POST"])
def create_ballot():
    uid, role = auth_context()
    require_role(role, JUDGE)
    body = get_body()
    pairing_id = body.get("pairing_id")
    pairing = db.pairings.get(pairing_id) if pairing_id else None
    if pairing is None:
        raise ApiError("ERR_PAIRING_NOT_FOUND", 404, "pairing_id does not exist")
    if pairing["judge_id"] != uid:
        raise ApiError("ERR_RESOURCE_OWNERSHIP_MISMATCH", 403,
                       "A Judge may only ballot pairings assigned to them")
    validate_ballot_content(pairing, body)
    b = {
        "id": new_id(),
        "pairing_id": pairing["id"],
        "judge_id": uid,
        "status": "DRAFT",
        "winner_entry_id": body.get("winner_entry_id") if pairing["format"] == "HEAD_TO_HEAD" else None,
        "speaker_points": body.get("speaker_points") if pairing["format"] == "HEAD_TO_HEAD" else None,
        "ranks": body.get("ranks") if pairing["format"] == "SECTION" else None,
        "allow_low_point_win": bool(body.get("allow_low_point_win", False)),
        "submitted_at": None,
        "created_at": now_ts(),
        "updated_at": now_ts(),
        "version": 1,
    }
    db.ballots[b["id"]] = b
    return ok(serialize_ballot(b), 201)


@bp.route("/ballots", methods=["GET"])
def list_ballots():
    auth_context()
    items = list(db.ballots.values())
    pid = request.args.get("pairing_id")
    jid = request.args.get("judge_id")
    status = request.args.get("status")
    if pid:
        items = [b for b in items if b["pairing_id"] == pid]
    if jid:
        items = [b for b in items if b["judge_id"] == jid]
    if status:
        items = [b for b in items if b["status"] == status]
    items.sort(key=lambda b: b["created_at"])
    data, meta = paginate(items, serialize_ballot)
    return ok(data, 200, meta)


@bp.route("/ballots/<bid>", methods=["GET"])
def get_ballot(bid):
    auth_context()
    return ok(serialize_ballot(get_or_404("ballots", bid, "ERR_BALLOT_NOT_FOUND")), 200)


def _load_ballot_for_judge(bid, uid):
    b = db.ballots.get(bid)
    if b is None:
        raise ApiError("ERR_BALLOT_NOT_FOUND", 404, "Ballot id does not exist")
    pairing = db.pairings.get(b["pairing_id"])
    if pairing is None or pairing["judge_id"] != uid:
        raise ApiError("ERR_RESOURCE_OWNERSHIP_MISMATCH", 403,
                       "A Judge may only act on ballots of pairings assigned to them")
    return b, pairing


@bp.route("/ballots/<bid>/submit", methods=["POST"])
def submit_ballot(bid):
    uid, role = auth_context()
    require_role(role, JUDGE)
    b, pairing = _load_ballot_for_judge(bid, uid)
    if b["status"] != "DRAFT":
        raise ApiError("ERR_BALLOT_INVALID_STATE", 409, "Ballot submit requires status DRAFT")
    if pairing["status"] != "BALLOT_RELEASED":
        raise ApiError("ERR_PAIRING_INVALID_STATE", 409,
                       "Ballot submit requires pairing status BALLOT_RELEASED")
    validate_ballot_content(
        pairing,
        {
            "winner_entry_id": b["winner_entry_id"],
            "speaker_points": b["speaker_points"],
            "ranks": b["ranks"],
            "allow_low_point_win": b["allow_low_point_win"],
        },
    )
    r = db.rounds.get(pairing["round_id"])
    if r is not None and clock.current > r["ends_at"] + timedelta(minutes=60):
        raise ApiError("ERR_BALLOT_WINDOW_CLOSED", 409,
                       "Ballot submit window closed (round ends_at + 60 minutes)")
    b["status"] = "SUBMITTED"
    b["submitted_at"] = clock.current
    pairing["status"] = "BALLOT_SUBMITTED"
    touch(b)
    touch(pairing)
    return ok(serialize_ballot(b), 200)


@bp.route("/ballots/<bid>/recall", methods=["POST"])
def recall_ballot(bid):
    uid, role = auth_context()
    require_role(role, JUDGE)
    b, pairing = _load_ballot_for_judge(bid, uid)
    if b["status"] != "SUBMITTED":
        raise ApiError("ERR_BALLOT_INVALID_STATE", 409, "Ballot recall requires status SUBMITTED")
    b["status"] = "DRAFT"
    if pairing["status"] == "BALLOT_SUBMITTED":
        pairing["status"] = "BALLOT_RELEASED"
        touch(pairing)
    touch(b)
    return ok(serialize_ballot(b), 200)


@bp.route("/ballots/<bid>/verify", methods=["POST"])
def verify_ballot(bid):
    _, role = auth_context()
    require_role(role, TAB)
    b = get_or_404("ballots", bid, "ERR_BALLOT_NOT_FOUND")
    if b["status"] != "SUBMITTED":
        raise ApiError("ERR_BALLOT_INVALID_STATE", 409, "Ballot verify requires status SUBMITTED")
    pairing = db.pairings.get(b["pairing_id"])
    b["status"] = "VERIFIED"
    touch(b)
    if pairing is not None:
        pairing["status"] = "VERIFIED"
        if pairing["format"] == "HEAD_TO_HEAD":
            pairing["winner_entry_id"] = b["winner_entry_id"]
        touch(pairing)
        r = db.rounds.get(pairing["round_id"])
        if r is not None:
            r["pairings_verified_count"] += 1
            touch(r)
    return ok(serialize_ballot(b), 200)


@bp.route("/ballots/<bid>/void", methods=["POST"])
def void_ballot(bid):
    _, role = auth_context()
    require_role(role, TAB)
    b = get_or_404("ballots", bid, "ERR_BALLOT_NOT_FOUND")
    if b["status"] != "VERIFIED":
        raise ApiError("ERR_BALLOT_INVALID_STATE", 409, "Ballot void requires status VERIFIED")
    pairing = db.pairings.get(b["pairing_id"])
    b["status"] = "VOIDED"
    touch(b)
    if pairing is not None:
        # Cascade link 1: pairing reverts, winner cleared.
        pairing["status"] = "BALLOT_RELEASED"
        pairing["winner_entry_id"] = None
        touch(pairing)
        r = db.rounds.get(pairing["round_id"])
        if r is not None:
            r["pairings_verified_count"] -= 1
            touch(r)
            # Cascade link 2: a TABULATED round auto-reopens.
            if r["status"] == "TABULATED":
                r["status"] = "BALLOTS_OPEN"
                touch(r)
            # Cascade link 3: entry stats recomputed excluding the VOIDED ballot.
            div = db.divisions.get(r["division_id"])
            if div is not None:
                recompute_division_stats(div)
    return ok(serialize_ballot(b), 200)


# ---------------------------------------------------------------------------
# Hired-judge contracts
# ---------------------------------------------------------------------------


@bp.route("/hired-judge-contracts", methods=["POST"])
def create_contract():
    uid, role = auth_context()
    require_role(role, COACH)
    body = get_body()
    school_id = body.get("school_id")
    _ownership_school(uid, school_id)
    school = db.schools.get(school_id) if school_id else None
    if school is None:
        raise ApiError("ERR_SCHOOL_NOT_FOUND", 404, "school_id does not exist")
    expected = body.get("expected_school_version")
    if not isinstance(expected, int) or expected != school["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_school_version does not match the school's current version")
    rounds_requested = body.get("rounds_requested")
    d = school_derived(school)
    if (not _is_int(rounds_requested) or rounds_requested < 1
            or rounds_requested > d["shortfall_rounds"]):
        raise ApiError("ERR_HIRED_ROUNDS_EXCEED_SHORTFALL", 422,
                       "rounds_requested must be in [1, school.shortfall_rounds]")
    c = {
        "id": new_id(),
        "school_id": school["id"],
        "status": "REQUESTED",
        "rounds_requested": rounds_requested,
        "rounds_released": 0,
        "hired_judge_id": None,
        "fee_quote_cents": 0,
        "final_fee_cents": None,
        "created_at": now_ts(),
        "updated_at": now_ts(),
        "version": 1,
    }
    db.contracts[c["id"]] = c
    t = tournament_of_school(school)
    c["fee_quote_cents"] = hired_fee(t["id"], c, "QUOTE")
    touch(school)
    touch(t)
    return ok(serialize_contract(c), 201)


@bp.route("/hired-judge-contracts", methods=["GET"])
def list_contracts():
    auth_context()
    items = list(db.contracts.values())
    sid = request.args.get("school_id")
    status = request.args.get("status")
    if sid:
        items = [c for c in items if c["school_id"] == sid]
    if status:
        items = [c for c in items if c["status"] == status]
    items.sort(key=lambda c: c["created_at"])
    data, meta = paginate(items, serialize_contract)
    return ok(data, 200, meta)


@bp.route("/hired-judge-contracts/<cid>", methods=["GET"])
def get_contract(cid):
    auth_context()
    return ok(serialize_contract(get_or_404("contracts", cid, "ERR_CONTRACT_NOT_FOUND")), 200)


def _contract_and_school(cid):
    c = get_or_404("contracts", cid, "ERR_CONTRACT_NOT_FOUND")
    return c, db.schools.get(c["school_id"])


@bp.route("/hired-judge-contracts/<cid>/fill", methods=["POST"])
def fill_contract(cid):
    _, role = auth_context()
    require_role(role, TD)
    c, school = _contract_and_school(cid)
    if c["status"] != "REQUESTED":
        raise ApiError("ERR_CONTRACT_INVALID_STATE", 409, "fill requires contract status REQUESTED")
    body = get_body()
    judge_name = body.get("judge_name")
    if not isinstance(judge_name, str) or not judge_name:
        raise validation_error("judge_name is required")
    t = tournament_of_school(school)
    j = {
        "id": new_id(),
        "tournament_id": t["id"],
        "school_id": None,
        "name": judge_name,
        "judge_type": "HIRED",
        "status": "COMMITTED",
        "commitment_rounds": c["rounds_requested"],
        "created_at": now_ts(),
        "updated_at": now_ts(),
        "version": 1,
    }
    db.judges[j["id"]] = j
    c["hired_judge_id"] = j["id"]
    c["status"] = "FILLED"
    touch(c)
    touch(school)
    touch(t)
    return ok(serialize_contract(c), 200)


@bp.route("/hired-judge-contracts/<cid>/accept", methods=["POST"])
def accept_contract(cid):
    uid, role = auth_context()
    require_role(role, COACH)
    c, school = _contract_and_school(cid)
    _ownership_school(uid, c["school_id"])
    if c["status"] != "FILLED":
        raise ApiError("ERR_CONTRACT_INVALID_STATE", 409, "accept requires contract status FILLED")
    t = tournament_of_school(school)
    c["final_fee_cents"] = hired_fee(t["id"], c, "FINAL")
    c["status"] = "CONFIRMED"
    touch(c)
    touch(school)
    touch(t)
    return ok(serialize_contract(c), 200)


@bp.route("/hired-judge-contracts/<cid>/dispute", methods=["POST"])
def dispute_contract(cid):
    uid, role = auth_context()
    require_role(role, COACH)
    c, school = _contract_and_school(cid)
    _ownership_school(uid, c["school_id"])
    if c["status"] != "CONFIRMED":
        raise ApiError("ERR_CONTRACT_INVALID_STATE", 409, "dispute requires contract status CONFIRMED")
    c["status"] = "DISPUTED"
    touch(c)
    touch(school)
    return ok(serialize_contract(c), 200)


@bp.route("/hired-judge-contracts/<cid>/resolve-dispute", methods=["POST"])
def resolve_dispute_contract(cid):
    _, role = auth_context()
    require_role(role, TD)
    c, school = _contract_and_school(cid)
    if c["status"] != "DISPUTED":
        raise ApiError("ERR_CONTRACT_INVALID_STATE", 409,
                       "resolve-dispute requires contract status DISPUTED")
    c["status"] = "CONFIRMED"
    touch(c)
    touch(school)
    return ok(serialize_contract(c), 200)


@bp.route("/hired-judge-contracts/<cid>/pay", methods=["POST"])
def pay_contract(cid):
    uid, role = auth_context()
    require_role(role, COACH)
    c, school = _contract_and_school(cid)
    _ownership_school(uid, c["school_id"])
    if c["status"] != "CONFIRMED":
        raise ApiError("ERR_CONTRACT_INVALID_STATE", 409, "pay requires contract status CONFIRMED")
    c["status"] = "PAID"
    touch(c)
    touch(school)
    t = tournament_of_school(school)
    touch(t)
    return ok(serialize_contract(c), 200)


@bp.route("/hired-judge-contracts/<cid>/cancel", methods=["POST"])
def cancel_contract(cid):
    _, role = auth_context()
    require_role(role, TD)
    c, school = _contract_and_school(cid)
    if c["status"] != "REQUESTED":
        raise ApiError("ERR_CONTRACT_INVALID_STATE", 409, "cancel requires contract status REQUESTED")
    c["status"] = "CANCELLED"
    touch(c)
    touch(school)
    t = tournament_of_school(school)
    touch(t)
    return ok(serialize_contract(c), 200)


# ---------------------------------------------------------------------------
# Logistics orders
# ---------------------------------------------------------------------------


@bp.route("/logistics-orders", methods=["POST"])
def create_order():
    _, role = auth_context()
    require_role(role, TD)
    body = get_body()
    tournament_id = body.get("tournament_id")
    t = db.tournaments.get(tournament_id) if tournament_id else None
    if t is None:
        raise ApiError("ERR_TOURNAMENT_NOT_FOUND", 404, "tournament_id does not exist")
    kind = body.get("kind")
    if kind not in ("CATERING", "AWARDS"):
        raise validation_error("kind must be CATERING or AWARDS")
    for o in db.orders.values():
        if o["tournament_id"] == t["id"] and o["kind"] == kind and o["status"] != "FULFILLED":
            raise ApiError("ERR_ORDER_KIND_EXISTS", 409,
                           "A non-FULFILLED order of this kind already exists for the tournament")
    o = {
        "id": new_id(),
        "tournament_id": t["id"],
        "kind": kind,
        "status": "DRAFT",
        "frozen_meal_count": None,
        "frozen_awards_count": None,
        "created_at": now_ts(),
        "updated_at": now_ts(),
        "version": 1,
    }
    db.orders[o["id"]] = o
    return ok(serialize_order(o), 201)


@bp.route("/logistics-orders", methods=["GET"])
def list_orders():
    auth_context()
    items = list(db.orders.values())
    tid = request.args.get("tournament_id")
    kind = request.args.get("kind")
    if tid:
        items = [o for o in items if o["tournament_id"] == tid]
    if kind:
        items = [o for o in items if o["kind"] == kind]
    items.sort(key=lambda o: o["created_at"])
    data, meta = paginate(items, serialize_order)
    return ok(data, 200, meta)


@bp.route("/logistics-orders/<oid>", methods=["GET"])
def get_order(oid):
    auth_context()
    return ok(serialize_order(get_or_404("orders", oid, "ERR_ORDER_NOT_FOUND")), 200)


@bp.route("/logistics-orders/<oid>/submit", methods=["POST"])
def submit_order(oid):
    _, role = auth_context()
    require_role(role, TD)
    o = get_or_404("orders", oid, "ERR_ORDER_NOT_FOUND")
    if o["status"] != "DRAFT":
        raise ApiError("ERR_ORDER_INVALID_STATE", 409, "submit requires order status DRAFT")
    t = db.tournaments.get(o["tournament_id"])
    if o["kind"] == "AWARDS":
        if not t or t["status"] not in ("ELIMS_ACTIVE", "COMPLETED"):
            raise ApiError("ERR_BREAKS_NOT_DETERMINED", 409,
                           "AWARDS submit requires tournament ELIMS_ACTIVE or COMPLETED")
        for div in tournament_divisions(t["id"]):
            competing = sum(
                1 for e in db.entries.values()
                if e["division_id"] == div["id"] and e["status"] in COMPETITION_STATUS_SET
            )
            if competing >= 2 and not div["bracket_size"]:
                raise ApiError("ERR_BREAKS_NOT_DETERMINED", 409,
                               "Every competing division must have bracket_size set")
    live = order_live_fields(o)
    o["frozen_meal_count"] = live["meal_count"]
    o["frozen_awards_count"] = live["awards_count"]
    o["status"] = "SUBMITTED"
    touch(o)
    return ok(serialize_order(o), 200)


@bp.route("/logistics-orders/<oid>/fulfill", methods=["POST"])
def fulfill_order(oid):
    _, role = auth_context()
    require_role(role, TD)
    o = get_or_404("orders", oid, "ERR_ORDER_NOT_FOUND")
    if o["status"] != "SUBMITTED":
        raise ApiError("ERR_ORDER_INVALID_STATE", 409, "fulfill requires order status SUBMITTED")
    o["status"] = "FULFILLED"
    touch(o)
    return ok(serialize_order(o), 200)
