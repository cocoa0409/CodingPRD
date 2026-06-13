"""Dunning sequences, runs, notices, and pauses (PRD §3.7)."""
from flask import Blueprint

import db
from errors import err, ERR_INVALID_REQUEST, ERR_INVALID_ENUM, ERR_VALIDATION, ERR_PAUSE_WINDOW_CONFLICT
from middleware import get_identity, authorize
from response import success, list_response
from services import domain, lookup
from services.common import (
    stamp_create, touch, stamp_light, get_json_body, require_str, require_int,
    parse_pagination, paginate,
)
from timeutil import parse_iso_ms

bp = Blueprint("dunning", __name__)

DAY_MS = 86400000
CHANNELS = {"EMAIL", "PHONE", "LETTER", "SMS"}


# ---- DunningSequence ------------------------------------------------------
@bp.route("/ar/dunning-sequences", methods=["POST"])
def create_sequence():
    _, role = get_identity()
    authorize(role, ["AR_MANAGER"])
    body = get_json_body()
    name = require_str(body, "name")
    active = body.get("active", True)
    if not isinstance(active, bool):
        raise err(ERR_INVALID_REQUEST, "active must be a boolean")
    steps = body.get("steps")
    if steps is None:
        raise err(ERR_INVALID_REQUEST, "steps is required")
    if not isinstance(steps, list) or len(steps) == 0:
        raise err(ERR_INVALID_REQUEST, "steps must be a non-empty array")

    parsed_steps = []
    prev_days = None
    for step in steps:
        if not isinstance(step, dict):
            raise err(ERR_INVALID_REQUEST, "each step must be an object")
        if "min_days_overdue" not in step or "channel" not in step or "severity" not in step:
            raise err(ERR_INVALID_REQUEST, "step missing required keys")
        mdo = step["min_days_overdue"]
        channel = step["channel"]
        severity = step["severity"]
        if isinstance(mdo, bool) or not isinstance(mdo, int):
            raise err(ERR_INVALID_REQUEST, "min_days_overdue must be an integer")
        if isinstance(severity, bool) or not isinstance(severity, int):
            raise err(ERR_INVALID_REQUEST, "severity must be an integer")
        if not isinstance(channel, str):
            raise err(ERR_INVALID_REQUEST, "channel must be a string")
        if channel not in CHANNELS:
            raise err(ERR_INVALID_ENUM, "channel has invalid enum value: %s" % channel)
        if prev_days is not None and mdo <= prev_days:
            raise err(ERR_VALIDATION, "min_days_overdue must strictly increase")
        prev_days = mdo
        parsed_steps.append({
            "min_days_overdue": mdo,
            "channel": channel,
            "severity": severity,
        })

    s = {"name": name, "active": active, "steps": parsed_steps}
    stamp_create(s)
    db.dunning_sequences[s["id"]] = s
    return success(domain.serialize_sequence(s), status=201)


@bp.route("/ar/dunning-sequences/<sid>", methods=["GET"])
def get_sequence(sid):
    _, role = get_identity()
    authorize(role, ["AR_MANAGER", "COLLECTIONS_AGENT", "AUDITOR"])
    s = lookup.get_sequence(sid)
    return success(domain.serialize_sequence(s), status=200)


@bp.route("/ar/dunning-sequences/<sid>/notices", methods=["GET"])
def sequence_notices(sid):
    _, role = get_identity()
    authorize(role, ["AR_MANAGER", "COLLECTIONS_AGENT", "AUDITOR"])
    lookup.get_sequence(sid)
    limit, offset = parse_pagination()
    items = [n for n in db.dunning_notices.values() if n["sequence_id"] == sid]
    items.sort(key=lambda n: (n["created_at"], n["id"]))
    total = len(items)
    page = paginate(items, limit, offset)
    return list_response([domain.serialize_notice(n) for n in page], limit, offset, total)


# ---- DunningPause ---------------------------------------------------------
@bp.route("/ar/dunning-pauses", methods=["POST"])
def create_pause():
    _, role = get_identity()
    authorize(role, ["COLLECTIONS_AGENT", "AR_MANAGER"])
    body = get_json_body()
    customer_id = require_str(body, "customer_id")
    lookup.get_customer(customer_id)
    pause_start = require_str(body, "pause_start")
    pause_end = require_str(body, "pause_end")
    start_ms = parse_iso_ms(pause_start)
    end_ms = parse_iso_ms(pause_end)
    # pause_end must be >= pause_start
    if end_ms < start_ms:
        raise err(ERR_VALIDATION, "pause_end must be >= pause_start")

    # 1-day buffer: any two windows for the same customer whose gap is <= 1 day
    # (inclusive) collide. Overlap also collides (gap negative).
    for p in db.dunning_pauses.values():
        if p["customer_id"] != customer_id:
            continue
        existing_start = p["pause_start_ms"]
        existing_end = p["pause_end_ms"]
        # gap = how far apart the two closed windows are (in ms); negative if overlapping
        if start_ms > existing_end:
            gap = start_ms - existing_end
        elif existing_start > end_ms:
            gap = existing_start - end_ms
        else:
            gap = -1  # overlapping
        if gap <= DAY_MS:
            raise err(ERR_PAUSE_WINDOW_CONFLICT, "pause window conflicts with the 1-day buffer")

    pause = {
        "customer_id": customer_id,
        "pause_start": pause_start,
        "pause_end": pause_end,
        "pause_start_ms": start_ms,
        "pause_end_ms": end_ms,
        "status": "SCHEDULED",
    }
    stamp_create(pause)
    pause["status"] = domain.pause_status(pause)
    db.dunning_pauses[pause["id"]] = pause
    return success(domain.serialize_pause(pause), status=201)


# ---- DunningRun -----------------------------------------------------------
@bp.route("/ar/dunning-runs", methods=["POST"])
def dunning_run():
    _, role = get_identity()
    authorize(role, ["COLLECTIONS_AGENT"])
    body = get_json_body()
    customer_id = require_str(body, "customer_id")
    customer = lookup.get_customer(customer_id)
    sequence_id = require_str(body, "sequence_id")
    sequence = lookup.get_sequence(sequence_id)

    now = db.now_ms()

    # candidate invoices: customer's overdue (B1_30 or worse), non-terminal,
    # not under an active pause.
    candidates = []
    for iv in db.invoices.values():
        if iv["customer_id"] != customer_id:
            continue
        if iv["status"] in ("PAID", "WRITTEN_OFF", "DISPUTED"):
            # a fully disputed invoice has dunning suspended (PRD §3.4)
            continue
        bucket = domain.aging_bucket(iv, "due")
        if bucket == "CURRENT":
            continue
        if _under_active_pause(customer_id, now):
            continue
        candidates.append(iv)

    notices = []
    emitted_any = False
    for iv in candidates:
        step_index, severity = _step_for_invoice(iv, sequence, now)
        if step_index is None:
            continue
        score = domain.collection_priority_score(iv, customer, now)
        notice = {
            "invoice_id": iv["id"],
            "sequence_id": sequence_id,
            "step_index": step_index,
            "severity": severity,
            "priority_score": score,
        }
        stamp_light(notice)
        db.dunning_notices[notice["id"]] = notice
        notices.append(notice)
        # advance the invoice's dunning_stage_index to the step reached
        iv["dunning_stage_index"] = step_index
        touch(iv)
        emitted_any = True

    # collection_stage CURRENT -> DUNNING when the first notice is emitted
    if emitted_any and customer["collection_stage"] == "CURRENT":
        customer["collection_stage"] = "DUNNING"
        touch(customer)

    return success([domain.serialize_notice(n) for n in notices],
                   status=201, response_type="array")


def _under_active_pause(customer_id, now):
    for p in db.dunning_pauses.values():
        if p["customer_id"] != customer_id:
            continue
        if p["pause_start_ms"] <= now <= p["pause_end_ms"]:
            return True
    return False


def _step_for_invoice(invoice, sequence, now):
    """Return (1-based step_index, severity) of the highest step whose
    min_days_overdue the invoice has reached on the due-date basis, or
    (None, None) if no step has fired yet."""
    days = domain.days_overdue(invoice["due_date_ms"], now)
    chosen = None
    for idx, step in enumerate(sequence["steps"], start=1):
        if days >= step["min_days_overdue"]:
            chosen = (idx, step["severity"])
        else:
            break
    if chosen is None:
        return (None, None)
    return chosen
