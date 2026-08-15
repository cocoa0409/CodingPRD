"""Uniform + UniformAssignment + CleaningBatch endpoints."""
from decimal import Decimal, ROUND_HALF_UP
from flask import Blueprint, request
from db import store, new_id, now, now_iso
from errors import (
    raise_err, ERR_UNIFORM_NOT_FOUND, ERR_UNIFORM_ASSIGNMENT_NOT_FOUND,
    ERR_CLEANING_BATCH_NOT_FOUND, ERR_STUDENT_NOT_FOUND,
    ERR_UNIFORM_NOT_ISSUABLE, ERR_UNIFORM_ASSIGNMENT_NOT_ISSUED,
    ERR_BATCH_NOT_OPEN, ERR_BATCH_NOT_SENT, ERR_BATCH_EMPTY,
    ERR_STUDENT_NOT_ENROLLED, ERR_GARMENT_TYPE_ALREADY_ISSUED,
    ERR_MATCHING_GARMENT_REQUIRED, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
)
from middleware import require_roles
from response import success, parse_pagination, paginate
from services.serializers import uniform_out, uniform_assignment_out, cleaning_batch_out
from services.validators import body, require, check_unknown, to_str, to_enum
from services.clock_eval import apply_time_transitions
from services.ledger import post_ledger, round_half_up_cents
from routes.programs import _get_program_or_404, _program_posture_open
from routes.students import _get_student_or_404

bp = Blueprint("uniforms", __name__)

GARMENT_TYPES = {"JACKET", "BIBBERS", "SHAKO", "PLUME", "GLOVES"}

BASE_PRICE = {
    "JACKET": 900,
    "BIBBERS": 700,
    "SHAKO": 450,
    "PLUME": 300,
    "GLOVES": 150,
}
HEAVY_SURCHARGE = 200


def _get_uniform_or_404(uid):
    u = store.uniforms.get(uid)
    if u is None:
        raise_err(ERR_UNIFORM_NOT_FOUND, f"uniform {uid} not found")
    return u


def _get_uniform_assignment_or_404(aid):
    a = store.uniform_assignments.get(aid)
    if a is None:
        raise_err(ERR_UNIFORM_ASSIGNMENT_NOT_FOUND, f"uniform assignment {aid} not found")
    return a


def _get_batch_or_404(bid):
    b = store.cleaning_batches.get(bid)
    if b is None:
        raise_err(ERR_CLEANING_BATCH_NOT_FOUND, f"cleaning batch {bid} not found")
    return b


@bp.route("/band/uniforms", methods=["POST"])
def create_uniform():
    require_roles(["EquipmentManager"])
    data = body()
    check_unknown(data, {"program_id", "garment_type", "size_label"})
    require(data, "program_id", "garment_type", "size_label")
    pid = to_str(data["program_id"], "program_id")
    garment_type = to_enum(data["garment_type"], "garment_type", GARMENT_TYPES)
    size_label = to_str(data["size_label"], "size_label")

    program = _get_program_or_404(pid)
    _program_posture_open(program)

    uid = new_id()
    now_s = now_iso()
    u = {
        "id": uid,
        "program_id": pid,
        "garment_type": garment_type,
        "size_label": size_label,
        "status": "IN_STORAGE",
        "cleaning_batch_id": None,
        "cleaning_count": 0,
        "created_at": now_s,
        "updated_at": now_s,
        "version": 1,
    }
    store.uniforms[uid] = u
    return success(uniform_out(u), status=201)


@bp.route("/band/uniforms", methods=["GET"])
def list_uniforms():
    require_roles(["Any"])
    apply_time_transitions()
    limit, offset = parse_pagination(request.args)
    items = list(store.uniforms.values())
    pid = request.args.get("program_id")
    if pid:
        items = [u for u in items if u["program_id"] == pid]
    st = request.args.get("status")
    if st:
        items = [u for u in items if u["status"] == st]
    gt = request.args.get("garment_type")
    if gt:
        items = [u for u in items if u["garment_type"] == gt]
    cb = request.args.get("cleaning_batch_id")
    if cb:
        items = [u for u in items if u.get("cleaning_batch_id") == cb]
    items.sort(key=lambda x: x["created_at"])
    page, pag = paginate(items, limit, offset)
    return success([uniform_out(u) for u in page], is_list=True, pagination=pag)


@bp.route("/band/uniforms/<uid>", methods=["GET"])
def get_uniform(uid):
    require_roles(["Any"])
    apply_time_transitions()
    u = _get_uniform_or_404(uid)
    return success(uniform_out(u))


@bp.route("/band/uniforms/<uid>/retire", methods=["POST"])
def retire_uniform(uid):
    require_roles(["EquipmentManager"])
    u = _get_uniform_or_404(uid)
    if u["status"] != "IN_STORAGE":
        raise_err(ERR_UNIFORM_NOT_ISSUABLE, "uniform is not IN_STORAGE")
    u["status"] = "RETIRED"
    u["version"] += 1
    u["updated_at"] = now_iso()
    return success(uniform_out(u))


# -------- UniformAssignment --------

@bp.route("/band/uniform-assignments", methods=["POST"])
def create_uniform_assignment():
    require_roles(["EquipmentManager"])
    data = body()
    check_unknown(data, {"student_id", "uniform_id"})
    require(data, "student_id", "uniform_id")
    student_id = to_str(data["student_id"], "student_id")
    uniform_id = to_str(data["uniform_id"], "uniform_id")

    student = _get_student_or_404(student_id)
    uniform = _get_uniform_or_404(uniform_id)

    program = _get_program_or_404(student["program_id"])
    _program_posture_open(program)

    if student["enrollment_status"] != "ENROLLED":
        raise_err(ERR_STUDENT_NOT_ENROLLED, "student must be ENROLLED")
    if uniform["status"] != "IN_STORAGE":
        raise_err(ERR_UNIFORM_NOT_ISSUABLE, "uniform is not IN_STORAGE")

    # Uniqueness: one ISSUED garment per (student, garment_type)
    for ua in store.uniform_assignments.values():
        if ua["student_id"] == student_id and ua["status"] == "ISSUED":
            other = store.uniforms.get(ua["uniform_id"])
            if other and other["garment_type"] == uniform["garment_type"]:
                raise_err(ERR_GARMENT_TYPE_ALREADY_ISSUED,
                          f"student already holds an ISSUED {uniform['garment_type']}")

    # PLUME requires SHAKO currently ISSUED
    if uniform["garment_type"] == "PLUME":
        has_shako = False
        for ua in store.uniform_assignments.values():
            if ua["student_id"] == student_id and ua["status"] == "ISSUED":
                u = store.uniforms.get(ua["uniform_id"])
                if u and u["garment_type"] == "SHAKO":
                    has_shako = True
                    break
        if not has_shako:
            raise_err(ERR_MATCHING_GARMENT_REQUIRED,
                      "PLUME requires student to hold an ISSUED SHAKO")

    aid = new_id()
    now_s = now_iso()
    a = {
        "id": aid,
        "student_id": student_id,
        "uniform_id": uniform_id,
        "status": "ISSUED",
        "issued_at": now_s,
        "returned_at": None,
        "soiling_level": None,
        "cleaning_fee_cents": 0,
        "created_at": now_s,
        "updated_at": now_s,
        "version": 1,
    }
    store.uniform_assignments[aid] = a
    uniform["status"] = "ISSUED"
    uniform["version"] += 1
    uniform["updated_at"] = now_s
    return success(uniform_assignment_out(a), status=201)


@bp.route("/band/uniform-assignments", methods=["GET"])
def list_uniform_assignments():
    require_roles(["Any"])
    apply_time_transitions()
    limit, offset = parse_pagination(request.args)
    items = list(store.uniform_assignments.values())
    sid = request.args.get("student_id")
    if sid:
        items = [a for a in items if a["student_id"] == sid]
    uid = request.args.get("uniform_id")
    if uid:
        items = [a for a in items if a["uniform_id"] == uid]
    st = request.args.get("status")
    if st:
        items = [a for a in items if a["status"] == st]
    items.sort(key=lambda x: x["created_at"])
    page, pag = paginate(items, limit, offset)
    return success([uniform_assignment_out(a) for a in page], is_list=True, pagination=pag)


@bp.route("/band/uniform-assignments/<aid>", methods=["GET"])
def get_uniform_assignment(aid):
    require_roles(["Any"])
    apply_time_transitions()
    a = _get_uniform_assignment_or_404(aid)
    return success(uniform_assignment_out(a))


@bp.route("/band/uniform-assignments/<aid>/return", methods=["POST"])
def return_uniform_assignment(aid):
    require_roles(["EquipmentManager"])
    a = _get_uniform_assignment_or_404(aid)
    data = body()
    check_unknown(data, {"soiling_level"})
    require(data, "soiling_level")
    soiling_level = to_enum(data["soiling_level"], "soiling_level", {"NORMAL", "HEAVY"})
    if a["status"] != "ISSUED":
        raise_err(ERR_UNIFORM_ASSIGNMENT_NOT_ISSUED, "uniform assignment is not ISSUED")
    a["status"] = "RETURNED"
    a["returned_at"] = now_iso()
    a["soiling_level"] = soiling_level
    a["version"] += 1
    a["updated_at"] = now_iso()
    u = store.uniforms.get(a["uniform_id"])
    if u:
        u["status"] = "RETURNED_DIRTY"
        u["version"] += 1
        u["updated_at"] = now_iso()
    return success(uniform_assignment_out(a))


# -------- CleaningBatch --------

@bp.route("/band/cleaning-batches", methods=["POST"])
def create_batch():
    require_roles(["EquipmentManager"])
    data = body()
    check_unknown(data, {"program_id"})
    require(data, "program_id")
    pid = to_str(data["program_id"], "program_id")
    program = _get_program_or_404(pid)
    _program_posture_open(program)

    bid = new_id()
    now_s = now_iso()
    b = {
        "id": bid,
        "program_id": pid,
        "status": "OPEN",
        "garment_count": 0,
        "discount_pct": 0.0,
        "total_cost_cents": 0,
        "created_at": now_s,
        "updated_at": now_s,
        "version": 1,
    }
    store.cleaning_batches[bid] = b
    return success(cleaning_batch_out(b), status=201)


@bp.route("/band/cleaning-batches", methods=["GET"])
def list_batches():
    require_roles(["Any"])
    apply_time_transitions()
    limit, offset = parse_pagination(request.args)
    items = list(store.cleaning_batches.values())
    pid = request.args.get("program_id")
    if pid:
        items = [b for b in items if b["program_id"] == pid]
    st = request.args.get("status")
    if st:
        items = [b for b in items if b["status"] == st]
    items.sort(key=lambda x: x["created_at"])
    page, pag = paginate(items, limit, offset)
    return success([cleaning_batch_out(b) for b in page], is_list=True, pagination=pag)


@bp.route("/band/cleaning-batches/<bid>", methods=["GET"])
def get_batch(bid):
    require_roles(["Any"])
    apply_time_transitions()
    b = _get_batch_or_404(bid)
    return success(cleaning_batch_out(b))


@bp.route("/band/cleaning-batches/<bid>/items", methods=["POST"])
def attach_item(bid):
    require_roles(["EquipmentManager"])
    b = _get_batch_or_404(bid)
    data = body()
    check_unknown(data, {"uniform_id"})
    require(data, "uniform_id")
    uniform_id = to_str(data["uniform_id"], "uniform_id")
    u = _get_uniform_or_404(uniform_id)

    if b["status"] != "OPEN":
        raise_err(ERR_BATCH_NOT_OPEN, "batch is not OPEN")
    if u["status"] != "RETURNED_DIRTY":
        raise_err(ERR_UNIFORM_NOT_ISSUABLE, "uniform is not RETURNED_DIRTY")
    u["cleaning_batch_id"] = bid
    u["version"] += 1
    u["updated_at"] = now_iso()
    b["garment_count"] += 1
    b["version"] += 1
    b["updated_at"] = now_iso()
    return success(cleaning_batch_out(b), status=201)


@bp.route("/band/cleaning-batches/<bid>/send", methods=["POST"])
def send_batch(bid):
    require_roles(["EquipmentManager"])
    b = _get_batch_or_404(bid)
    if b["status"] != "OPEN":
        raise_err(ERR_BATCH_NOT_OPEN, "batch is not OPEN")
    if b["garment_count"] < 1:
        raise_err(ERR_BATCH_EMPTY, "batch is empty")
    for u in store.uniforms.values():
        if u.get("cleaning_batch_id") == bid:
            u["status"] = "AT_CLEANER"
            u["version"] += 1
            u["updated_at"] = now_iso()
    b["status"] = "SENT"
    b["version"] += 1
    b["updated_at"] = now_iso()
    return success(cleaning_batch_out(b))


@bp.route("/band/cleaning-batches/<bid>/receive", methods=["POST"])
def receive_batch(bid):
    require_roles(["EquipmentManager"])
    b = _get_batch_or_404(bid)
    if b["status"] != "SENT":
        raise_err(ERR_BATCH_NOT_SENT, "batch is not SENT")
    # Tier by garment_count
    count = b["garment_count"]
    if count <= 10:
        discount_pct = 0.0
    elif count <= 30:
        discount_pct = 0.15
    else:
        discount_pct = 0.25
    b["discount_pct"] = discount_pct

    # Compute per-line cost and apply
    total = 0
    for u in store.uniforms.values():
        if u.get("cleaning_batch_id") != bid:
            continue
        base = BASE_PRICE[u["garment_type"]]
        # find the latest RETURNED uniform_assignment for this garment
        soiling = "NORMAL"
        assignment = None
        candidates = [a for a in store.uniform_assignments.values()
                      if a["uniform_id"] == u["id"] and a["status"] == "RETURNED"]
        if candidates:
            candidates.sort(key=lambda a: a["returned_at"] or "")
            assignment = candidates[-1]
            soiling = assignment.get("soiling_level") or "NORMAL"
        line = round_half_up_cents(Decimal(base) * (Decimal(1) - Decimal(str(discount_pct))))
        if soiling == "HEAVY":
            line += HEAVY_SURCHARGE
        total += line
        # Apply to assignment and post debit
        if assignment:
            assignment["cleaning_fee_cents"] = line
            assignment["version"] += 1
            assignment["updated_at"] = now_iso()
            post_ledger(assignment["student_id"], "CLEANING_FEE_DEBIT", line)
        u["status"] = "IN_STORAGE"
        u["cleaning_count"] += 1
        u["cleaning_batch_id"] = None
        u["version"] += 1
        u["updated_at"] = now_iso()
    b["total_cost_cents"] = total
    b["status"] = "RECONCILED"
    b["version"] += 1
    b["updated_at"] = now_iso()
    return success(cleaning_batch_out(b))
