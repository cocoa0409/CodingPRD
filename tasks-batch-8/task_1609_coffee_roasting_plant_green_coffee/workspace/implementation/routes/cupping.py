"""Cupping sessions: open, finalize, verdict cascades (PRD §3.5)."""

from flask import Blueprint

from db import DB
from errors import (
    ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_NOT_CUPPABLE, ERR_NOT_FOUND,
    ERR_PANEL_TOO_SMALL, ERR_SEGREGATION_OF_DUTIES, err,
)
from middleware import (
    COMMON_SYS, D, base_fields, check_unknown_fields, get_json_body,
    is_number, pub, q1, require_fields, require_role, touch, v_enum, v_int,
)
from response import success_object
from services import (
    SCORE_FIELDS, compute_final_score, recompute_position, verdict_for,
)

bp = Blueprint("cupping", __name__)

CUPPING_ALLOWED = (
    {"subject_kind", "subject_id", "panelist_count", "defects_subtracted",
     "final_score", "session_verdict", "reviewed_by_qa_id"}
    | set(SCORE_FIELDS) | COMMON_SYS
)

READ_ROLES = ("QAGrader", "HeadRoaster", "Trader")


def _resolve_subject(subject_kind, subject_id):
    """Resolve the polymorphic subject. Returns (kind, lot_or_batch).

    For GREEN_LOT the caller may pass the GreenLot id OR the parent
    Shipment id (resolved to the shipment's single GreenLot child).
    """
    if subject_kind == "GREEN_LOT":
        lot = DB.green_lots.get(subject_id)
        if lot is not None:
            return lot
        shipment = DB.shipments.get(subject_id)
        if shipment is not None:
            lot = next(
                (l for l in DB.green_lots.values()
                 if l["shipment_id"] == shipment["id"]), None)
            if lot is not None:
                return lot
        raise err(ERR_NOT_FOUND, "subject_id does not resolve to a green lot")
    else:  # ROAST_BATCH
        batch = DB.roast_batches.get(subject_id)
        if batch is None:
            raise err(ERR_NOT_FOUND, "subject_id does not resolve to a roast batch")
        return batch


def _check_cuppable(session_kind, subject):
    """Priority 27: the subject must be in a cuppable state."""
    if session_kind == "GREEN_LOT":
        if subject["lot_status"] != "QUARANTINE":
            raise err(ERR_NOT_CUPPABLE, "Green lot is cuppable only in QUARANTINE")
    else:
        if subject["qc_status"] != "PENDING_QC":
            raise err(ERR_NOT_CUPPABLE, "Roast batch is cuppable only in PENDING_QC")


def _validate_score(body, name):
    v = body.get(name)
    if v is None:
        raise err(ERR_INVALID_REQUEST, f"Missing required field: {name}")
    if not is_number(v):
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be a number")
    if not (D(v) >= 0 and D(v) <= 10):
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be between 0 and 10")
    if (D(v) * 4) != int(D(v) * 4):
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be in 0.25 steps")
    return v


@bp.post("/roastery/cupping-sessions")
def create_cupping_session():
    require_role("QAGrader")
    body = get_json_body()

    kind_raw = body.get("subject_kind")
    subject_raw = body.get("subject_id")
    # Priority 5: body FK existence (resolution requires a usable kind first).
    if kind_raw in ("GREEN_LOT", "ROAST_BATCH") and isinstance(subject_raw, str):
        subject = _resolve_subject(kind_raw, subject_raw)
    else:
        subject = None

    # Priorities 22/23: structural.
    check_unknown_fields(body, CUPPING_ALLOWED)
    require_fields(body, ["subject_kind", "subject_id", "panelist_count",
                          *SCORE_FIELDS, "defects_subtracted"])
    kind = v_enum(body, "subject_kind", {"GREEN_LOT", "ROAST_BATCH"})
    sid = body.get("subject_id")
    if not isinstance(sid, str):
        raise err(ERR_INVALID_REQUEST, "Field subject_id must be a string")
    panelists = v_int(body, "panelist_count", ge=1)
    scores = {f: _validate_score(body, f) for f in SCORE_FIELDS}
    defects = v_int(body, "defects_subtracted", ge=0)
    if subject is None:
        subject = _resolve_subject(kind, sid)

    # Priority 27: cuppable-state check at session open.
    _check_cuppable(kind, subject)

    s = base_fields()
    s.update({
        "subject_kind": kind,
        "subject_id": subject["id"],  # resolved id, never the client alias
        "panelist_count": panelists,
        **scores,
        "defects_subtracted": defects,
        "final_score": None,
        "session_verdict": "PENDING_REVIEW",
        "reviewed_by_qa_id": None,
    })
    DB.cupping_sessions[s["id"]] = s
    return success_object(pub(s), status=201)


@bp.get("/roastery/cupping-sessions/<session_id>")
def get_cupping_session(session_id):
    require_role(*READ_ROLES)
    s = DB.cupping_sessions.get(session_id)
    if s is None:
        raise err(ERR_NOT_FOUND, "Cupping session id does not exist")
    return success_object(pub(s))


@bp.post("/roastery/cupping-sessions/<session_id>/finalize")
def finalize_cupping_session(session_id):
    user_id, _ = require_role("QAGrader")
    s = DB.cupping_sessions.get(session_id)
    if s is None:
        raise err(ERR_NOT_FOUND, "Cupping session id does not exist")
    get_json_body()

    # Priority 6: a finalized session cannot be finalized again.
    if s["session_verdict"] != "PENDING_REVIEW":
        raise err(ERR_INVALID_STATE, "Cupping session is already finalized")

    # Priority 9: segregation of duties — the finalizer must not be the
    # RoastOperator who ran the batch.
    if s["subject_kind"] == "ROAST_BATCH":
        batch = DB.roast_batches.get(s["subject_id"])
        if batch is not None and user_id in batch.get("_operator_ids", set()):
            raise err(ERR_SEGREGATION_OF_DUTIES,
                      "The QAGrader finalizing a roast batch must differ from its RoastOperator")

    # Priority 27: subject must still be cuppable.
    subject = _resolve_subject(s["subject_kind"], s["subject_id"])
    _check_cuppable(s["subject_kind"], subject)

    # Priority 28: decisive panel size.
    if s["panelist_count"] < 3:
        raise err(ERR_PANEL_TOO_SMALL, "panelist_count must be >= 3 for a decisive session")

    final_score = compute_final_score(s)
    verdict = verdict_for(s, final_score)
    s["final_score"] = final_score
    s["session_verdict"] = verdict
    s["reviewed_by_qa_id"] = user_id
    touch(s)

    if s["subject_kind"] == "GREEN_LOT":
        lot = subject
        lot["cup_score"] = q1(final_score)
        shipment = DB.shipments.get(lot["shipment_id"])
        if verdict == "PASS":
            lot["lot_status"] = "RELEASED"
            if shipment is not None and shipment["qc_status"] == "PENDING_CUP":
                shipment["qc_status"] = "CUP_PASSED"
        else:
            lot["lot_status"] = "REJECTED"
            if shipment is not None:
                if shipment["qc_status"] == "PENDING_CUP":
                    shipment["qc_status"] = "CUP_FAILED"
                if shipment["dispute_status"] == "NONE":
                    shipment["dispute_status"] = "DISPUTED"
        touch(lot)
        if shipment is not None:
            touch(shipment)
        recompute_position()
    else:  # ROAST_BATCH
        batch = subject
        if verdict == "PASS":
            batch["qc_status"] = "QC_PASSED"
        else:
            batch["qc_status"] = "QC_FAILED"
            # Defensive recall cascade for any finished goods already packed.
            for fg in DB.finished_goods_lots.values():
                if fg["roast_batch_id"] == batch["id"] and fg["lot_status"] in ("FRESH", "STALE"):
                    fg["lot_status"] = "RECALLED"
                    touch(fg)
                    for line in DB.fulfillment_lines.values():
                        if (line["finished_goods_lot_id"] == fg["id"]
                                and line["line_status"] == "ACTIVE"):
                            line["line_status"] = "RELEASED"
                            touch(line)
        touch(batch)

    return success_object(pub(s))
