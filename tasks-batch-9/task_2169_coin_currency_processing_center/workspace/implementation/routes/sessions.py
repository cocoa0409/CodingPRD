"""CountSession routes: scheduling, start, the completion cascade, fitness lots."""

from datetime import timedelta

from flask import Blueprint

import calc
from core import (
    LOT_CATEGORIES,
    LOT_STATUSES,
    MACHINE_CLEANING_BUFFER_MINUTES,
    MACHINE_TYPE_ACCEPTS,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_VAULT_MANAGER,
    ROLE_VAULT_TELLER,
    SESSION_STATUSES,
    VARIANCE_MATERIALITY_CENTS,
    authorize,
    bags_of_ticket,
    body_json,
    clock_now,
    db,
    fail,
    fmt_dt,
    get_bag,
    get_machine,
    get_pagination,
    get_session,
    lots_of_session,
    make_row,
    ordered,
    paginate,
    parse_dt,
    query_enum,
    query_str,
    req_datetime,
    req_int,
    req_list,
    req_str,
    respond,
    sessions_of_bag,
    touch,
    vault_of_session,
)
from serializers import lot_out, session_out

bp = Blueprint("sessions", __name__)

BUFFER = timedelta(minutes=MACHINE_CLEANING_BUFFER_MINUTES)


@bp.post("/count-sessions")
def create_session():
    actor = authorize(ROLE_VAULT_TELLER)
    body = body_json()
    sealed_bag_id = req_str(body, "sealed_bag_id")
    counting_machine_id = req_str(body, "counting_machine_id")
    window_start_raw, window_start = req_datetime(body, "window_start")
    window_end_raw, window_end = req_datetime(body, "window_end")
    expected_version = req_int(body, "expected_sealed_bag_version")
    if window_end <= window_start:
        fail("ERR_INVALID_REQUEST", "'window_end' must be strictly after 'window_start'.")

    # ladder 6 - body references in declared field order
    bag = get_bag(sealed_bag_id)
    machine = get_machine(counting_machine_id)

    # ladder 8 - optimistic concurrency against the parent bag
    if expected_version != bag["version"]:
        fail("ERR_STALE_VERSION", "expected_sealed_bag_version does not match the bag version.")

    # ladder 10 - bag custody readiness
    if bag["custody_status"] not in ("VAULT_RECEIVED", "OPENED"):
        fail("ERR_BAG_NOT_RECEIVED", "The bag has not reached the vault.")

    # ladder 19 - machine type accepts bag type
    if bag["bag_type"] not in MACHINE_TYPE_ACCEPTS[machine["machine_type"]]:
        fail(
            "ERR_MACHINE_TYPE_MISMATCH",
            "A %s cannot process a %s bag." % (machine["machine_type"], bag["bag_type"]),
        )

    # ladder 23 - machine occupancy window (half-open, cleaning buffer on the end)
    new_start = window_start
    new_end = window_end + BUFFER
    for other in db.sessions.values():
        if other["counting_machine_id"] != counting_machine_id:
            continue
        if other["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        other_start = other["_window_start_dt"]
        other_end = other["_window_end_dt"] + BUFFER
        if new_start < other_end and other_start < new_end:
            fail("ERR_MACHINE_WINDOW_CONFLICT", "The machine is already occupied in that window.")

    # ladder 24 - counting window not in the past
    if window_start < clock_now():
        fail("ERR_WINDOW_IN_PAST", "'window_start' is earlier than the current logical clock.")

    # supersede any prior SCHEDULED session on the same bag
    for prior in sessions_of_bag(sealed_bag_id):
        if prior["status"] == "SCHEDULED":
            prior["status"] = "SUPERSEDED"
            touch(prior)

    row = make_row()
    row.update({
        "sealed_bag_id": sealed_bag_id,
        "counting_machine_id": counting_machine_id,
        "operator_user_id": actor.user_id,
        "verifier_user_id": None,
        "window_start": window_start_raw,
        "window_end": window_end_raw,
        "_window_start_dt": window_start,
        "_window_end_dt": window_end,
        "status": "SCHEDULED",
        "counted_amount_cents": 0,
        "counted_note_count": 0,
        "counted_coin_weight_grams": 0,
        "seized_face_value_cents": 0,
        "completed_at": None,
    })
    db.sessions[row["id"]] = row

    touch(bag)
    return respond(session_out(row), 201)


@bp.get("/count-sessions/<session_id>")
def read_session(session_id):
    authorize(ROLE_VAULT_MANAGER, ROLE_VAULT_TELLER)
    return respond(session_out(get_session(session_id)))


@bp.get("/count-sessions")
def list_sessions():
    authorize(ROLE_VAULT_MANAGER, ROLE_VAULT_TELLER)
    limit, offset = get_pagination()
    sealed_bag_id = query_str("sealed_bag_id")
    counting_machine_id = query_str("counting_machine_id")
    status = query_enum("status", SESSION_STATUSES)

    rows = ordered(db.sessions.values())
    if sealed_bag_id is not None:
        rows = [r for r in rows if r["sealed_bag_id"] == sealed_bag_id]
    if counting_machine_id is not None:
        rows = [r for r in rows if r["counting_machine_id"] == counting_machine_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, limit, offset, session_out)


@bp.post("/count-sessions/<session_id>/start")
def start_session(session_id):
    authorize(ROLE_VAULT_TELLER)
    session = get_session(session_id)

    if session["status"] != "SCHEDULED":
        fail("ERR_INVALID_STATE", "Session is not in SCHEDULED.")

    bag = db.bags.get(session["sealed_bag_id"])
    if bag is None or bag["count_status"] != "PENDING":
        fail("ERR_INVALID_STATE", "The bag's counting axis is not PENDING.")

    # ladder 10 - the bag has to be cut open to be counted
    if bag["custody_status"] != "OPENED":
        fail("ERR_BAG_NOT_RECEIVED", "The bag has not been opened.")

    # ladder 13 - a FROZEN vault blocks counting; RESTRICTED still permits it
    vault = vault_of_session(session)
    if vault is not None and vault["posture"] == "FROZEN":
        fail("ERR_VAULT_FROZEN", "The vault is FROZEN.")

    # ladder 15 - counting machine availability
    machine = db.machines.get(session["counting_machine_id"])
    if machine is None or machine["status"] != "AVAILABLE":
        fail("ERR_MACHINE_UNAVAILABLE", "The counting machine is not AVAILABLE.")

    session["status"] = "IN_PROGRESS"
    touch(session)

    bag["count_status"] = "COUNTING"
    touch(bag)
    return respond(session_out(session))


def _validate_lots(body):
    entries = req_list(body, "lots", allow_empty=False)
    parsed = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            fail("ERR_INVALID_REQUEST", "lots[%d] must be an object." % index)
        category = entry.get("category")
        if not isinstance(category, str) or category not in LOT_CATEGORIES:
            fail("ERR_INVALID_REQUEST", "lots[%d].category is invalid." % index)
        denomination_cents = entry.get("denomination_cents")
        if isinstance(denomination_cents, bool) or not isinstance(denomination_cents, int):
            fail("ERR_INVALID_REQUEST", "lots[%d].denomination_cents must be an integer." % index)
        if denomination_cents < 0:
            fail("ERR_INVALID_REQUEST", "lots[%d].denomination_cents must be non-negative." % index)
        note_count = entry.get("note_count")
        if isinstance(note_count, bool) or not isinstance(note_count, int):
            fail("ERR_INVALID_REQUEST", "lots[%d].note_count must be an integer." % index)
        if note_count < 1:
            fail("ERR_INVALID_REQUEST", "lots[%d].note_count must be at least 1." % index)
        parsed.append({
            "category": category,
            "denomination_cents": denomination_cents,
            "note_count": note_count,
        })
    return parsed


@bp.post("/count-sessions/<session_id>/complete")
def complete_session(session_id):
    actor = authorize(ROLE_VAULT_TELLER)
    body = body_json()
    counted_amount_cents = req_int(body, "counted_amount_cents", minimum=0)
    counted_note_count = req_int(body, "counted_note_count", minimum=0)
    counted_coin_weight_grams = req_int(body, "counted_coin_weight_grams", minimum=0)
    lots = _validate_lots(body)

    session = get_session(session_id)

    if session["status"] != "IN_PROGRESS":
        fail("ERR_INVALID_STATE", "Session is not in IN_PROGRESS.")

    # ladder 16 - dual control
    if actor.user_id == session["operator_user_id"]:
        fail(
            "ERR_DUAL_CONTROL_VIOLATION",
            "The operator who opened the session may not complete it.",
        )

    # ladder 33 - the reported breakdown must reconcile with the reported totals
    lot_value = sum(l["denomination_cents"] * l["note_count"] for l in lots)
    lot_notes = sum(l["note_count"] for l in lots)
    if lot_value != counted_amount_cents or lot_notes != counted_note_count:
        fail("ERR_LOT_TOTAL_MISMATCH", "The lot breakdown does not reconcile with the totals.")

    now = clock_now()
    now_iso = fmt_dt(now)

    session["status"] = "COMPLETED"
    session["verifier_user_id"] = actor.user_id
    session["completed_at"] = now_iso
    session["counted_amount_cents"] = counted_amount_cents
    session["counted_note_count"] = counted_note_count
    session["counted_coin_weight_grams"] = counted_coin_weight_grams
    touch(session)

    for entry in lots:
        lot = make_row()
        lot.update({
            "count_session_id": session["id"],
            "fed_deposit_id": None,
            "category": entry["category"],
            "denomination_cents": entry["denomination_cents"],
            "note_count": entry["note_count"],
            "face_value_cents": entry["denomination_cents"] * entry["note_count"],
            "status": "PENDING_REVIEW" if entry["category"] == "COUNTERFEIT_SUSPECT"
            else "PENDING_DEPOSIT",
        })
        db.lots[lot["id"]] = lot

    # ---- cascade hop 1: the bag
    bag = db.bags.get(session["sealed_bag_id"])
    if bag is not None:
        bag["counted_amount_cents"] = counted_amount_cents
        bag["counted_note_count"] = counted_note_count
        bag["counted_coin_weight_grams"] = counted_coin_weight_grams
        bag["counted_at"] = now_iso
        bag["variance_cents"] = counted_amount_cents - bag["declared_amount_cents"]
        bag["materiality_flag"] = abs(bag["variance_cents"]) >= VARIANCE_MATERIALITY_CENTS
        bag["processing_fee_cents"] = calc.bag_processing_fee_cents(bag)
        bag["count_status"] = "COUNTED"
        calc.recompute_bag_settlement(bag)
        touch(bag)

        # ---- cascade hop 2: the deposit ticket
        ticket = db.tickets.get(bag["deposit_ticket_id"])
        if ticket is not None:
            calc.recompute_ticket_counted_total(ticket)
            calc.recompute_ticket_processing_fee_total(ticket)
            if bag["materiality_flag"]:
                ticket["material_variance_open_count"] += 1

            # ---- cascade hop 3: the ticket's own automatic transition
            siblings = bags_of_ticket(ticket["id"])
            if siblings and all(b["count_status"] in ("COUNTED", "ADJUSTED") for b in siblings):
                if ticket["status"] in ("VERIFIED", "PROVISIONAL_CREDITED", "HELD"):
                    ticket["status"] = "SETTLEMENT_READY"
            touch(ticket)

    return respond(session_out(session))


@bp.get("/count-sessions/<session_id>/fitness-lots")
def list_session_lots(session_id):
    authorize(ROLE_VAULT_MANAGER, ROLE_VAULT_TELLER, ROLE_COMPLIANCE_OFFICER)
    limit, offset = get_pagination()
    category = query_enum("category", LOT_CATEGORIES)
    status = query_enum("status", LOT_STATUSES)
    get_session(session_id)

    rows = lots_of_session(session_id)
    if category is not None:
        rows = [r for r in rows if r["category"] == category]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, limit, offset, lot_out)
