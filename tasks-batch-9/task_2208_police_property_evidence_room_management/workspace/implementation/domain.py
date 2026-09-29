"""Domain services: lookups, gates, derived-quantity reconciliation, the chain
of custody ledger and retention determinations."""

from decimal import Decimal

import calc
from errors import ApiError
from store import db, mark, new_entity, now, sort_rows

OPEN_DISCREPANCY_STATUSES = ("OPEN", "UNDER_INVESTIGATION")
OPEN_TRANSFER_STATUSES = ("REQUESTED", "RELEASED", "OVERDUE")
OCCUPYING_CUSTODY_STATES = ("STORED", "CHECKED_OUT")
DISPOSAL_READY_STATES = ("DISPOSAL_ELIGIBLE", "UNCLAIMED_ELIGIBLE")


# --------------------------------------------------------------------------
# lookups
# --------------------------------------------------------------------------

def find(collection, identifier, error_id):
    if not isinstance(identifier, str):
        raise ApiError(error_id)
    row = collection.get(identifier)
    if row is None:
        raise ApiError(error_id)
    return row


def case_of_item(item):
    return db.cases.get(item["case_id"])


def statute_of_case(case):
    return db.statutes.get(case["offense_statute_id"])


def room_of_case(case):
    return db.rooms.get(case["property_room_id"]) if case else None


def room_of_item(item):
    return room_of_case(case_of_item(item))


def room_of_location(location):
    return db.rooms.get(location["property_room_id"]) if location else None


def room_of_session(session):
    location = db.locations.get(session["storage_location_id"])
    return room_of_location(location)


def location_of_item(item):
    if item["storage_location_id"] is None:
        return None
    return db.locations.get(item["storage_location_id"])


def items_of_case(case_id):
    return sort_rows([i for i in db.items.values() if i["case_id"] == case_id])


def items_of_room(room_id):
    rows = []
    for item in db.items.values():
        case = case_of_item(item)
        if case is not None and case["property_room_id"] == room_id:
            rows.append(item)
    return sort_rows(rows)


def discrepancies_of_room(room_id):
    rows = []
    for discrepancy in db.discrepancies.values():
        item = db.items.get(discrepancy["evidence_item_id"])
        if item is None:
            continue
        case = case_of_item(item)
        if case is not None and case["property_room_id"] == room_id:
            rows.append(discrepancy)
    return sort_rows(rows)


def discrepancies_of_session(session_id):
    return sort_rows(
        [d for d in db.discrepancies.values() if d["audit_session_id"] == session_id]
    )


def transfers_of_room(room_id):
    rows = []
    for transfer in db.transfers.values():
        item = db.items.get(transfer["evidence_item_id"])
        if item is None:
            continue
        case = case_of_item(item)
        if case is not None and case["property_room_id"] == room_id:
            rows.append(transfer)
    return sort_rows(rows)


# --------------------------------------------------------------------------
# gates (validation stages 8 and 9)
# --------------------------------------------------------------------------

def gate_locked_down(room):
    if room is not None and room["posture"] == "LOCKED_DOWN":
        raise ApiError("ERR_ROOM_LOCKED_DOWN")


def gate_restricted(room):
    if room is not None and room["posture"] == "RESTRICTED":
        raise ApiError("ERR_ROOM_RESTRICTED")


# --------------------------------------------------------------------------
# derived quantities
# --------------------------------------------------------------------------

def _assign(entity, field, value):
    if entity[field] != value:
        entity[field] = value
        mark(entity)


def refresh_location(location):
    """calculations.location_occupied_slots (PRD 2.7)."""
    if location is None:
        return
    occupied = len(
        [
            i
            for i in db.items.values()
            if i["storage_location_id"] == location["id"]
            and i["custody_state"] in OCCUPYING_CUSTODY_STATES
        ]
    )
    _assign(location, "occupied_slots", occupied)


def refresh_all_locations(room_id):
    for location in db.locations.values():
        if location["property_room_id"] == room_id:
            refresh_location(location)


def refresh_custodian(custodian):
    if custodian is None:
        return
    open_escorts = len(
        [
            t
            for t in db.transfers.values()
            if t["to_custodian_id"] == custodian["id"]
            and t["status"] in OPEN_TRANSFER_STATUSES
        ]
    )
    _assign(custodian, "open_escort_count", open_escorts)


def refresh_item_transfer_count(item):
    if item is None:
        return
    count = len(
        [
            t
            for t in db.transfers.values()
            if t["evidence_item_id"] == item["id"] and t["status"] in OPEN_TRANSFER_STATUSES
        ]
    )
    _assign(item, "open_transfer_count", count)


def refresh_case(case):
    if case is None:
        return
    items = [i for i in db.items.values() if i["case_id"] == case["id"]]
    _assign(case, "item_count", len(items))
    _assign(
        case,
        "undisposed_item_count",
        len([i for i in items if i["disposition_state"] != "DISPOSED"]),
    )


def refresh_session_counts(session):
    if session is None:
        return
    rows = discrepancies_of_session(session["id"])
    _assign(session, "missing_count", len([d for d in rows if d["kind"] == "MISSING"]))
    _assign(session, "misplaced_count", len([d for d in rows if d["kind"] == "MISPLACED"]))


def refresh_session_risk(session):
    """calculations.audit_risk_index.  The index stays 0.00 until the session has
    been reconciled; afterwards it is re-derived from the still-open rows."""
    if session is None:
        return
    refresh_session_counts(session)
    if session["reconciled_at"] is None:
        _assign(session, "risk_index", Decimal("0.00"))
        return
    location = db.locations.get(session["storage_location_id"])
    location_category = location["category"] if location else "GENERAL"
    total = Decimal("0.00")
    for discrepancy in discrepancies_of_session(session["id"]):
        if discrepancy["status"] not in OPEN_DISCREPANCY_STATUSES:
            continue
        item = db.items.get(discrepancy["evidence_item_id"])
        appraised = item["appraised_value_cents"] if item else 0
        contribution = calc.weight_contribution(
            discrepancy["kind"], appraised, location_category
        )
        if discrepancy["weight_contribution"] != contribution:
            discrepancy["weight_contribution"] = contribution
            mark(discrepancy)
        total += contribution
    _assign(session, "risk_index", calc.rhu2(total))


def unresolved_risk_sum(room_id):
    total = Decimal("0.00")
    for session in db.sessions.values():
        if session["status"] != "RECONCILED":
            continue
        location = db.locations.get(session["storage_location_id"])
        if location is None or location["property_room_id"] != room_id:
            continue
        rows = discrepancies_of_session(session["id"])
        if not any(d["status"] in OPEN_DISCREPANCY_STATUSES for d in rows):
            continue
        total += Decimal(session["risk_index"])
    return total


def refresh_room(room):
    """Recomputes every derived counter of the room, then the posture (PRD 2.6).

    Entering LOCKED_DOWN denies every REQUESTED custody transfer in the room.
    """
    if room is None:
        return
    room_id = room["id"]
    items = items_of_room(room_id)
    open_discrepancies = [
        d for d in discrepancies_of_room(room_id) if d["status"] in OPEN_DISCREPANCY_STATUSES
    ]
    open_count = len(open_discrepancies)
    missing_high_risk = 0
    for discrepancy in open_discrepancies:
        if discrepancy["kind"] != "MISSING":
            continue
        item = db.items.get(discrepancy["evidence_item_id"])
        if item is not None and item["category"] in calc.HIGH_RISK_CATEGORIES:
            missing_high_risk += 1
    sealed = len(
        [
            l
            for l in db.locations.values()
            if l["property_room_id"] == room_id and l["status"] == "SEALED_FOR_AUDIT"
        ]
    )
    disposal_eligible = len([i for i in items if i["disposition_state"] in DISPOSAL_READY_STATES])
    item_ids = set(i["id"] for i in items)
    escrow = 0
    for order in db.orders.values():
        if order["settlement_status"] == "HELD" and order["evidence_item_id"] in item_ids:
            escrow += order["settled_net_proceeds_cents"] or 0
    risk_sum = unresolved_risk_sum(room_id)

    if (
        missing_high_risk >= calc.HIGH_RISK_MISSING_LIMIT
        or open_count >= calc.OPEN_DISCREPANCY_LOCKDOWN_LIMIT
        or risk_sum >= calc.RISK_INDEX_LOCKDOWN_THRESHOLD
    ):
        posture = "LOCKED_DOWN"
    elif open_count >= 1 or sealed >= 1:
        posture = "RESTRICTED"
    else:
        posture = "OPEN"

    previous = room["posture"]
    _assign(room, "open_discrepancy_count", open_count)
    _assign(room, "missing_high_risk_count", missing_high_risk)
    _assign(room, "sealed_location_count", sealed)
    _assign(room, "disposal_eligible_count", disposal_eligible)
    _assign(room, "escrow_balance_cents", escrow)
    _assign(room, "posture", posture)

    if posture == "LOCKED_DOWN" and previous != "LOCKED_DOWN":
        for transfer in transfers_of_room(room_id):
            if transfer["status"] != "REQUESTED":
                continue
            transfer["status"] = "DENIED"
            transfer["denial_reason"] = "ROOM_LOCKED_DOWN"
            mark(transfer)
            refresh_custodian(db.custodians.get(transfer["to_custodian_id"]))
            refresh_item_transfer_count(db.items.get(transfer["evidence_item_id"]))


# --------------------------------------------------------------------------
# chain of custody ledger (PRD 2.12)
# --------------------------------------------------------------------------

def append_chain_event(item, event_type, actor_role, actor_custodian_id=None,
                       signature_ref=None, detail=""):
    event = new_entity(
        "ChainEvent",
        {
            "evidence_item_id": item["id"],
            "actor_custodian_id": actor_custodian_id,
            "event_type": event_type,
            "sequence_no": 0,
            "occurred_at": now(),
            "actor_role": actor_role,
            "signature_ref": signature_ref,
            "detail": detail,
        },
        common_fields=False,
    )
    db.chain_events[event["id"]] = event
    _renumber_chain(item["id"])
    return event


def _renumber_chain(item_id):
    events = sorted(
        [e for e in db.chain_events.values() if e["evidence_item_id"] == item_id],
        key=lambda e: (e["occurred_at"], e["created_at"], e["_seq"]),
    )
    for index, event in enumerate(events, start=1):
        event["sequence_no"] = index


# --------------------------------------------------------------------------
# retention determinations (PRD 3.4)
# --------------------------------------------------------------------------

def determinations_of_item(item_id):
    return sort_rows(
        [d for d in db.determinations.values() if d["evidence_item_id"] == item_id]
    )


def create_determination(item, requested_basis, actor_role, actor_custodian_id,
                         mark_item=True, append_event=True):
    case = case_of_item(item)
    statute = statute_of_case(case)
    resolved_basis, anchor_at, days, release_at = calc.retention(
        item, case, statute, requested_basis
    )
    for previous in determinations_of_item(item["id"]):
        if not previous["superseded"]:
            previous["superseded"] = True
            mark(previous)
    determination = new_entity(
        "RetentionDetermination",
        {
            "evidence_item_id": item["id"],
            "basis": requested_basis,
            "resolved_basis": resolved_basis,
            "anchor_at": anchor_at,
            "statute_days_applied": days,
            "computed_release_at": release_at,
            "superseded": False,
        },
    )
    db.determinations[determination["id"]] = determination
    item["retention_release_at"] = release_at
    item["retention_basis"] = resolved_basis
    if mark_item:
        mark(item)
    if append_event:
        append_chain_event(
            item,
            "RETENTION_SET",
            actor_role,
            actor_custodian_id,
            None,
            "Retention determination recorded with basis %s." % resolved_basis,
        )
    return determination


def mature_if_due(item):
    """RETAINED -> DISPOSAL_ELIGIBLE when retention has matured and the item is
    physically stored."""
    if (
        item["disposition_state"] == "RETAINED"
        and item["custody_state"] == "STORED"
        and item["retention_release_at"] is not None
        and item["retention_release_at"] <= now()
    ):
        item["disposition_state"] = "DISPOSAL_ELIGIBLE"
        mark(item)
        return True
    return False


# --------------------------------------------------------------------------
# custodian eligibility (validation stages 12 and 13)
# --------------------------------------------------------------------------

def gate_active(*custodians):
    for custodian in custodians:
        if custodian is not None and custodian["status"] != "ACTIVE":
            raise ApiError("ERR_CUSTODIAN_SUSPENDED")


def gate_certified(*custodians):
    for custodian in custodians:
        if custodian is None:
            continue
        if custodian["certification_expires_at"] is None or custodian[
            "certification_expires_at"
        ] <= now():
            raise ApiError("ERR_CUSTODIAN_NOT_CERTIFIED")


# --------------------------------------------------------------------------
# missing-item bookkeeping shared by report-lost and reconciliation
# --------------------------------------------------------------------------

def raise_missing_discrepancy(item, audit_session_id, actor_role, actor_custodian_id):
    location = location_of_item(item)
    item["custody_state"] = "MISSING"
    mark(item)
    discrepancy = new_entity(
        "Discrepancy",
        {
            "evidence_item_id": item["id"],
            "audit_session_id": audit_session_id,
            "kind": "MISSING",
            "status": "OPEN",
            "weight_contribution": Decimal("0.00"),
            "resolution_note": None,
            "resolved_at": None,
        },
    )
    db.discrepancies[discrepancy["id"]] = discrepancy
    refresh_location(location)
    append_chain_event(
        item,
        "DISCREPANCY_RAISED",
        actor_role,
        actor_custodian_id,
        None,
        "Missing-item discrepancy raised.",
    )
    return discrepancy
