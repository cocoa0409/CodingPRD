"""Wet-bench routes: specimens (gross/reject/dispose), blocks, slides,
and stain-order start/result/cancel."""
from decimal import Decimal
from flask import Blueprint, request

from db import db
from errors import ApiError
from helpers import (
    qparam,
    auth, require_role, payload, ok, paginate,
    need_str, need_enum, need_num, now, round1,
)
import calc
from calc import new_entity, bump

bp = Blueprint("lab", __name__)


def _not_found(what="Resource"):
    raise ApiError("ERR_NOT_FOUND", 404, "%s does not exist" % what)


def _get_specimen(sid):
    s = db.specimens.get(sid)
    if s is None:
        _not_found("Specimen")
    return s


def _get_block(bid):
    b = db.blocks.get(bid)
    if b is None:
        _not_found("Block")
    return b


def _get_slide(sid):
    s = db.slides.get(sid)
    if s is None:
        _not_found("Slide")
    return s


def _get_stain(oid):
    o = db.stain_orders.get(oid)
    if o is None:
        _not_found("StainOrder")
    return o


def _check_case_not_terminal(case):
    """Priority 5 guard on child mutations under a case."""
    if case["status"] in ("CANCELLED", "FINAL"):
        raise ApiError("ERR_CASE_TERMINAL", 409,
                       "owning case is CANCELLED or FINAL")


# ---------------------------------------------------------------------------
# Specimens
# ---------------------------------------------------------------------------

@bp.get("/pathology/specimens/<sid>")
def get_specimen(sid):
    auth()
    return ok(calc.ser_specimen(_get_specimen(sid)))


@bp.get("/pathology/specimens")
def list_specimens():
    auth()
    items = list(db.specimens.values())
    case_id = qparam("case_id")
    if case_id is not None:
        items = [s for s in items if s["case_id"] == case_id]
    status = qparam("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    page, meta = paginate(items)
    return ok([calc.ser_specimen(s) for s in page],
              response_type="array", pagination=meta)


@bp.post("/pathology/specimens/<sid>/gross")
def gross_specimen(sid):
    _, role = auth()
    require_role(role, "PathologyAssistant")
    body = payload()
    gross_description = need_str(body, "gross_description")
    s = _get_specimen(sid)
    c = db.cases[s["case_id"]]
    _check_case_not_terminal(c)
    if s["status"] != "ACCESSIONED":
        raise ApiError("ERR_SPECIMEN_NOT_ACCESSIONED", 409,
                       "specimen is not in ACCESSIONED")
    s["gross_description"] = gross_description
    s["status"] = "GROSSING"
    bump(s)
    # first grossed specimen bubbles the case OPEN -> WORKUP
    if c["status"] == "OPEN":
        c["status"] = "WORKUP"
        bump(c)
    return ok(calc.ser_specimen(s))


@bp.post("/pathology/specimens/<sid>/reject")
def reject_specimen(sid):
    _, role = auth()
    require_role(role, "Histotech")
    body = payload()
    reason = need_str(body, "reason")
    s = _get_specimen(sid)
    c = db.cases[s["case_id"]]
    _check_case_not_terminal(c)
    # ERR_BLOCKS_EXIST fires even when the specimen has left ACCESSIONED
    # (a specimen with blocks is necessarily GROSSING/PROCESSING; the corner
    # design pins ERR_BLOCKS_EXIST for a PROCESSING specimen)
    if calc.specimen_blocks(sid):
        raise ApiError("ERR_BLOCKS_EXIST", 409,
                       "specimen already has blocks")
    if s["status"] != "ACCESSIONED":
        raise ApiError("ERR_SPECIMEN_NOT_ACCESSIONED", 409,
                       "specimen is not in ACCESSIONED")
    s["status"] = "REJECTED"
    s["reject_reason"] = reason
    bump(s)
    # all specimens REJECTED while still OPEN -> the case cancels itself
    if c["status"] == "OPEN" and all(
            x["status"] == "REJECTED" for x in calc.case_specimens(c["id"])):
        calc.cancel_case(c)
    return ok(calc.ser_specimen(s))


@bp.post("/pathology/specimens/<sid>/dispose-wet-tissue")
def dispose_wet_tissue(sid):
    _, role = auth()
    require_role(role, "Histotech")
    s = _get_specimen(sid)
    if s["status"] != "COMPLETE" or s["wet_tissue_disposed_at"] is not None:
        raise ApiError("ERR_SPECIMEN_NOT_COMPLETE", 409,
                       "specimen is not COMPLETE or already disposed")
    if now() < s["retention_until"]:
        raise ApiError("ERR_RETENTION_NOT_ELAPSED", 422,
                       "retention period has not elapsed")
    s["wet_tissue_disposed_at"] = now()
    bump(s)
    return ok(calc.ser_specimen(s))

# ---------------------------------------------------------------------------
# Blocks
# ---------------------------------------------------------------------------

@bp.post("/pathology/specimens/<sid>/blocks")
def create_block(sid):
    _, role = auth()
    require_role(role, "PathologyAssistant", "Histotech")
    body = payload()
    block_label = need_str(body, "block_label")
    s = _get_specimen(sid)
    c = db.cases[s["case_id"]]
    _check_case_not_terminal(c)
    if s["status"] not in ("GROSSING", "PROCESSING"):
        raise ApiError("ERR_GROSS_NOT_RECORDED", 409,
                       "specimen is not in GROSSING or PROCESSING")
    if any(b["block_label"] == block_label for b in calc.specimen_blocks(sid)):
        raise ApiError("ERR_DUPLICATE_BLOCK_LABEL", 409,
                       "block_label already used within the specimen")
    b = new_entity()
    b.update({
        "specimen_id": sid,
        "block_label": block_label,
        "status": "CREATED",
        "tissue_remaining_pct": Decimal("100.0"),
        "_events": [],
    })
    db.blocks[b["id"]] = b
    # first block moves the specimen GROSSING -> PROCESSING
    if s["status"] == "GROSSING":
        s["status"] = "PROCESSING"
        bump(s)
    return ok(calc.ser_block(b), status=201)


@bp.get("/pathology/blocks/<bid>")
def get_block(bid):
    auth()
    return ok(calc.ser_block(_get_block(bid)))


@bp.get("/pathology/blocks")
def list_blocks():
    auth()
    items = list(db.blocks.values())
    specimen_id = qparam("specimen_id")
    if specimen_id is not None:
        items = [b for b in items if b["specimen_id"] == specimen_id]
    status = qparam("status")
    if status is not None:
        items = [b for b in items if b["status"] == status]
    page, meta = paginate(items)
    return ok([calc.ser_block(b) for b in page],
              response_type="array", pagination=meta)


@bp.post("/pathology/blocks/<bid>/embed")
def embed_block(bid):
    _, role = auth()
    require_role(role, "Histotech")
    b = _get_block(bid)
    c = calc.case_of_block(b)
    _check_case_not_terminal(c)
    if b["status"] != "CREATED":
        raise ApiError("ERR_BLOCK_NOT_CREATED", 409,
                       "block is not in CREATED")
    b["status"] = "EMBEDDED"
    bump(b)
    return ok(calc.ser_block(b))

# ---------------------------------------------------------------------------
# Slides
# ---------------------------------------------------------------------------

@bp.post("/pathology/blocks/<bid>/slides")
def create_slide(bid):
    _, role = auth()
    require_role(role, "Histotech")
    body = payload()
    slide_label = need_str(body, "slide_label")
    stain_type = need_enum(body, "stain_type", calc.SLIDE_STAIN_TYPES) \
        if "stain_type" in body else "H_E"
    b = _get_block(bid)
    c = calc.case_of_block(b)
    _check_case_not_terminal(c)
    _require_block_embedded(b)
    if any(s["slide_label"] == slide_label for s in calc.block_slides(bid)):
        raise ApiError("ERR_DUPLICATE_SLIDE_LABEL", 409,
                       "slide_label already used within the block")
    s = new_entity()
    s.update({
        "block_id": bid,
        "slide_label": slide_label,
        "stain_type": stain_type,
        "status": "ORDERED",
        "consumption_pct": Decimal("0.0"),
        "qc_failure_reason": None,
    })
    db.slides[s["id"]] = s
    return ok(calc.ser_slide(s), status=201)


def _require_block_embedded(b):
    """Priorities 9/10: CREATED -> ERR_BLOCK_NOT_EMBEDDED; DEPLETED ->
    ERR_BLOCK_DEPLETED."""
    if b["status"] == "DEPLETED":
        raise ApiError("ERR_BLOCK_DEPLETED", 409, "block is DEPLETED")
    if b["status"] != "EMBEDDED":
        raise ApiError("ERR_BLOCK_NOT_EMBEDDED", 409,
                       "block is not EMBEDDED")


def _consume_tissue(slide, block, raw_pct):
    """Shared section/recut accounting (priority 57 budget check is last).
    Per-event round-half-up to 1 decimal BEFORE summation."""
    if raw_pct > block["tissue_remaining_pct"]:
        raise ApiError("ERR_INSUFFICIENT_TISSUE", 422,
                       "consumption exceeds the block's remaining tissue")
    rounded = round1(raw_pct)
    slide["consumption_pct"] = rounded
    slide["status"] = "SECTIONED"
    bump(slide)
    block["_events"].append(rounded)
    block["tissue_remaining_pct"] = round1(
        Decimal("100.0") - sum(block["_events"], Decimal("0.0")))
    bump(block)
    # hop 2: crossing below MIN_RECUTABLE_PCT depletes the block
    if block["tissue_remaining_pct"] < calc.MIN_RECUTABLE_PCT \
            and block["status"] == "EMBEDDED":
        block["status"] = "DEPLETED"
        bump(block)


@bp.get("/pathology/slides/<sid>")
def get_slide(sid):
    auth()
    return ok(calc.ser_slide(_get_slide(sid)))


@bp.get("/pathology/slides")
def list_slides():
    auth()
    items = list(db.slides.values())
    block_id = qparam("block_id")
    if block_id is not None:
        items = [s for s in items if s["block_id"] == block_id]
    status = qparam("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    page, meta = paginate(items)
    return ok([calc.ser_slide(s) for s in page],
              response_type="array", pagination=meta)


@bp.post("/pathology/slides/<sid>/section")
def section_slide(sid):
    _, role = auth()
    require_role(role, "Histotech")
    body = payload()
    pct = need_num(body, "consumption_pct")
    if pct <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "consumption_pct must be greater than 0")
    s = _get_slide(sid)
    c = calc.case_of_slide(s)
    _check_case_not_terminal(c)
    b = db.blocks[s["block_id"]]
    _require_block_embedded(b)
    if s["status"] != "ORDERED":
        raise ApiError("ERR_SLIDE_WRONG_STATE", 409,
                       "section requires slide status ORDERED")
    _consume_tissue(s, b, pct)
    return ok(calc.ser_slide(s))


@bp.post("/pathology/slides/<sid>/stain-complete")
def stain_complete_slide(sid):
    _, role = auth()
    require_role(role, "Histotech")
    s = _get_slide(sid)
    c = calc.case_of_slide(s)
    _check_case_not_terminal(c)
    if s["status"] != "SECTIONED":
        raise ApiError("ERR_SLIDE_WRONG_STATE", 409,
                       "stain-complete requires slide status SECTIONED")
    s["status"] = "STAINED"
    bump(s)
    return ok(calc.ser_slide(s))


@bp.post("/pathology/slides/<sid>/qc-review")
def qc_review_slide(sid):
    _, role = auth()
    require_role(role, "Histotech")
    body = payload()
    result = need_enum(body, "result", {"PASS", "FAIL"})
    reason = body.get("reason")
    if reason is not None and not isinstance(reason, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "reason must be a string")
    s = _get_slide(sid)
    c = calc.case_of_slide(s)
    _check_case_not_terminal(c)
    if s["status"] != "STAINED":
        raise ApiError("ERR_SLIDE_WRONG_STATE", 409,
                       "qc-review requires slide status STAINED")
    if result == "PASS":
        s["status"] = "QC_PASSED"
    else:
        s["status"] = "QC_FAILED"
        s["qc_failure_reason"] = reason
    bump(s)
    # a failed slide pulls a PENDING_SIGNOUT case back to WORKUP
    if result == "FAIL" and c["status"] == "PENDING_SIGNOUT":
        c["status"] = "WORKUP"
        bump(c)
    return ok(calc.ser_slide(s))


@bp.post("/pathology/slides/<sid>/recut")
def recut_slide(sid):
    _, role = auth()
    require_role(role, "Histotech")
    body = payload()
    pct = need_num(body, "consumption_pct")
    if pct <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "consumption_pct must be greater than 0")
    s = _get_slide(sid)
    c = calc.case_of_slide(s)
    _check_case_not_terminal(c)
    b = db.blocks[s["block_id"]]
    _require_block_embedded(b)
    if s["status"] != "QC_FAILED":
        raise ApiError("ERR_SLIDE_WRONG_STATE", 409,
                       "recut requires slide status QC_FAILED")
    _consume_tissue(s, b, pct)
    return ok(calc.ser_slide(s))

# ---------------------------------------------------------------------------
# Stain orders (bench actions)
# ---------------------------------------------------------------------------

@bp.get("/pathology/stain-orders/<oid>")
def get_stain_order(oid):
    auth()
    return ok(calc.ser_stain_order(_get_stain(oid)))


@bp.get("/pathology/stain-orders")
def list_stain_orders():
    auth()
    items = list(db.stain_orders.values())
    for param, field in (("case_id", "case_id"), ("block_id", "block_id"),
                         ("reflex_rule_id", "reflex_rule_id"),
                         ("parent_stain_order_id", "parent_stain_order_id"),
                         ("ordered_by_pathologist_id",
                          "ordered_by_pathologist_id"),
                         ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            items = [o for o in items if o[field] == v]
    page, meta = paginate(items)
    return ok([calc.ser_stain_order(o) for o in page],
              response_type="array", pagination=meta)


@bp.post("/pathology/stain-orders/<oid>/start")
def start_stain_order(oid):
    _, role = auth()
    require_role(role, "Histotech")
    o = _get_stain(oid)
    c = db.cases[o["case_id"]]
    _check_case_not_terminal(c)
    if o["status"] != "ORDERED":
        raise ApiError("ERR_STAIN_WRONG_STATE", 409,
                       "start requires stain order status ORDERED")
    o["status"] = "IN_PROGRESS"
    bump(o)
    return ok(calc.ser_stain_order(o))


@bp.post("/pathology/stain-orders/<oid>/result")
def result_stain_order(oid):
    _, role = auth()
    require_role(role, "Histotech")
    body = payload()
    result_value = need_enum(body, "result_value", calc.RESULT_VALUES)
    o = _get_stain(oid)
    c = db.cases[o["case_id"]]
    _check_case_not_terminal(c)
    if o["status"] != "IN_PROGRESS":
        raise ApiError("ERR_STAIN_WRONG_STATE", 409,
                       "result requires stain order status IN_PROGRESS")
    o["status"] = "RESULTED"
    o["result_value"] = result_value
    o["resulted_at"] = now()
    bump(o)
    calc.reflex_evaluate(o)
    return ok(calc.ser_stain_order(o))


@bp.post("/pathology/stain-orders/<oid>/cancel")
def cancel_stain_order(oid):
    _, role = auth()
    require_role(role, "Pathologist")
    o = _get_stain(oid)
    if o["status"] not in ("ORDERED", "IN_PROGRESS"):
        raise ApiError("ERR_STAIN_WRONG_STATE", 409,
                       "cancel requires stain order status ORDERED or "
                       "IN_PROGRESS")
    o["status"] = "CANCELLED"
    bump(o)
    return ok(calc.ser_stain_order(o))
