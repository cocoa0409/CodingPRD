"""Waiver agreement endpoints: create, get (derived status + recoverable
balance), list, recoupments (waterfall), ledger listing."""
from decimal import Decimal
from flask import Blueprint

import db
from db import store
from errors import ApiError
from middleware import ALL_ROLES, get_context, require_roles
from response import created, filter_arg, ok, paginate
from services import navmath
from services.navmath import D
from validation import parse_body, require_fk, require_path_entity

bp = Blueprint("waivers", __name__)

AGREEMENT_SCHEMA = {
    "share_class_id": ("string", True, None),
    "cap_bps": ("posnumber", True, None),
    "effective_from": ("date", True, None),
    "effective_to": ("date", True, None),
    "recovery_window_months": ("int_range", True, (1, 36)),
}

RECOUPMENT_SCHEMA = {
    "amount": ("posnumber", True, None),
    "recoup_date": ("date", True, None),
}


def _with_derived(agreement):
    """Serialize an agreement with its derived (never stored) fields."""
    view = dict(agreement)
    view["status"] = navmath.agreement_status(agreement)
    view["recoverable_balance"] = navmath.recoverable_balance(agreement["id"])
    return view


@bp.post("/waiver-agreements")
def create_waiver_agreement():
    get_context()
    require_roles(["FundController"])
    body = parse_body(AGREEMENT_SCHEMA)
    cls = require_fk(store.share_classes, body["share_class_id"], "share_class_id")
    if body["effective_to"] < body["effective_from"]:
        raise ApiError("ERR_VALIDATION", 400,
                       "effective_to must not precede effective_from")
    # Closed-interval overlap against the class's other ACTIVE agreements.
    for other in store.waiver_agreements.values():
        if other["share_class_id"] != cls["id"]:
            continue
        if navmath.agreement_status(other) != "ACTIVE":
            continue
        if body["effective_from"] <= other["effective_to"] \
                and other["effective_from"] <= body["effective_to"]:
            raise ApiError("ERR_CAP_AGREEMENT_OVERLAP", 409,
                           "The interval overlaps another ACTIVE agreement of the class")
    agreement = {
        "id": db.new_id(),
        "share_class_id": cls["id"],
        "cap_bps": D(body["cap_bps"]),
        "effective_from": body["effective_from"],
        "effective_to": body["effective_to"],
        "recovery_window_months": body["recovery_window_months"],
    }
    db.new_common(agreement)
    store.waiver_agreements[agreement["id"]] = agreement
    return created(_with_derived(agreement))


@bp.get("/waiver-agreements")
def list_waiver_agreements():
    get_context()
    require_roles(ALL_ROLES)
    rows = filter_arg(list(store.waiver_agreements.values()), "share_class_id")
    page, meta = paginate(rows)
    return ok([_with_derived(a) for a in page], rtype="array", pagination=meta)


@bp.get("/waiver-agreements/<waiver_agreement_id>")
def get_waiver_agreement(waiver_agreement_id):
    get_context()
    agreement = require_path_entity(store.waiver_agreements, waiver_agreement_id)
    require_roles(ALL_ROLES)
    return ok(_with_derived(agreement))


@bp.get("/waiver-agreements/<waiver_agreement_id>/ledger")
def list_waiver_ledger(waiver_agreement_id):
    get_context()
    agreement = require_path_entity(store.waiver_agreements, waiver_agreement_id)
    require_roles(ALL_ROLES)
    rows = [e for e in store.waiver_ledger_entries.values()
            if e["waiver_agreement_id"] == agreement["id"]]
    page, meta = paginate(rows)
    return ok(page, rtype="array", pagination=meta)


@bp.post("/waiver-agreements/<waiver_agreement_id>/recoupments")
def create_recoupment(waiver_agreement_id):
    get_context()
    agreement = require_path_entity(store.waiver_agreements, waiver_agreement_id)
    require_roles(["FundController"])
    body = parse_body(RECOUPMENT_SCHEMA)

    # State (priority 5): the agreement's derived status must be ACTIVE.
    if navmath.agreement_status(agreement) != "ACTIVE":
        raise ApiError("ERR_AGREEMENT_NOT_ACTIVE", 409,
                       "The agreement is EXPIRED")

    # Temporal (priority 8): at least one unexpired WAIVER entry with balance;
    # the window is inclusive of expires_at.
    eligible = [e for e in store.waiver_ledger_entries.values()
                if e["waiver_agreement_id"] == agreement["id"]
                and e["entry_type"] == "WAIVER"
                and D(e["remaining_amount"]) > 0
                and e["expires_at"] >= body["recoup_date"]]
    if not eligible:
        raise ApiError("ERR_RECOUP_WINDOW_EXPIRED", 422,
                       "No unexpired WAIVER entry with remaining balance")

    # Fiscal (priority 10): the amount must fit the eligible balance.
    amount = D(body["amount"])
    total_remaining = sum((D(e["remaining_amount"]) for e in eligible), Decimal("0"))
    if amount > total_remaining:
        raise ApiError("ERR_RECOUP_AMOUNT_EXCEEDS_BALANCE", 422,
                       "Recoupment amount exceeds the eligible unexpired balance")

    # Oldest-first waterfall: entry_date ascending, then created_at ascending.
    eligible.sort(key=lambda e: (e["entry_date"], e["created_at"], e["_seq"]))
    left = amount
    for entry in eligible:
        take = min(D(entry["remaining_amount"]), left)
        entry["remaining_amount"] = D(entry["remaining_amount"]) - take
        left -= take
        if left <= 0:
            break

    recoupment = {
        "id": db.new_id(),
        "waiver_agreement_id": agreement["id"],
        "entry_type": "RECOUPMENT",
        "amount": amount,
        "entry_date": body["recoup_date"],
        "expires_at": None,
        "remaining_amount": Decimal("0"),
    }
    db.new_ledger_row(recoupment)
    store.waiver_ledger_entries[recoupment["id"]] = recoupment

    db.touch(agreement)  # recoupment bumps the agreement's version by one
    return created(recoupment)
