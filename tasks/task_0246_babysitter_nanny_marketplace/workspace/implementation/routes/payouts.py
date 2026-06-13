"""Payout endpoints (PRD §3.9)."""

from flask import Blueprint, request

import errors
from db import store
from errors import err
from middleware import authenticate, require_roles, get_json, parse_pagination, paginate
from response import ok
from services import validate as v
from services.calc import compute_payout_withholding
from services.common import base_record, touch
from services.ledger import recompute_w2_obligation
from services.lookup import (get_caregiver, get_family, get_payout, get_session,
                             sorted_by_created)
from services.serialize import payout_out

bp = Blueprint("payouts", __name__)


def _session_in_non_reversed_payout(session_id):
    for p in store.payouts.values():
        if p["status"] == "REVERSED":
            continue
        if session_id in p["session_ids"]:
            return True
    return False


@bp.route("/marketplace/payouts", methods=["POST"])
def create_payout():
    auth = authenticate()
    require_roles(auth, {"PlatformAdmin"})
    body = get_json()
    caregiver_id = v.req_str(body, "caregiver_id")
    family_id = v.req_str(body, "family_id")
    session_ids = v.req_str_list(body, "session_ids")

    # Existence (priority 3): body FKs left to right, then session ids.
    get_caregiver(caregiver_id)
    get_family(family_id)
    sessions = [get_session(sid) for sid in session_ids]

    # Payout session validity (priority 16): all COMPLETED, same caregiver+family,
    # none already in a non-REVERSED payout.
    for s in sessions:
        if s["status"] != "COMPLETED":
            raise err(errors.ERR_PAYOUT_SESSION_INVALID, "Session not COMPLETED")
        if s["caregiver_id"] != caregiver_id:
            raise err(errors.ERR_PAYOUT_SESSION_INVALID, "Session caregiver mismatch")
        booking = store.bookings.get(s["booking_id"])
        if booking is None or booking["family_id"] != family_id:
            raise err(errors.ERR_PAYOUT_SESSION_INVALID, "Session family mismatch")
        if _session_in_non_reversed_payout(s["id"]):
            raise err(errors.ERR_PAYOUT_SESSION_INVALID, "Session already paid")

    # Sweep order: window_start ASC, then created_at ASC.
    ordered = sorted(sessions, key=lambda s: (s["window_start_iso"], s["created_at"]))
    gross, fica, fee, net = compute_payout_withholding(
        [s["gross_pay_cents"] for s in ordered]
    )

    rec = base_record()
    rec.update({
        "caregiver_id": caregiver_id,
        "family_id": family_id,
        "session_ids": [s["id"] for s in ordered],
        "gross_pay_cents": gross,
        "fica_withheld_cents": fica,
        "platform_fee_cents": fee,
        "net_pay_cents": net,
        "status": "PENDING",
    })
    store.payouts[rec["id"]] = rec
    return ok(payout_out(rec), status=201)


@bp.route("/marketplace/payouts/<pid>", methods=["GET"])
def get_one_payout(pid):
    auth = authenticate()
    require_roles(auth, {"PlatformAdmin", "Caregiver"})
    p = get_payout(pid)
    if auth.is_caregiver and auth.user_id != p["caregiver_id"]:
        raise err(errors.ERR_FORBIDDEN, "Caregiver may only read its own payouts")
    return ok(payout_out(p), status=200)


@bp.route("/marketplace/payouts", methods=["GET"])
def list_payouts():
    auth = authenticate()
    require_roles(auth, {"PlatformAdmin", "Caregiver"})
    limit, offset = parse_pagination()
    caregiver_id = request.args.get("caregiver_id")
    family_id = request.args.get("family_id")
    status = request.args.get("status")

    items = list(store.payouts.values())
    if auth.is_caregiver:
        items = [p for p in items if p["caregiver_id"] == auth.user_id]
    if caregiver_id is not None:
        items = [p for p in items if p["caregiver_id"] == caregiver_id]
    if family_id is not None:
        items = [p for p in items if p["family_id"] == family_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items = sorted_by_created(items)
    page, meta = paginate(items, limit, offset)
    return ok([payout_out(p) for p in page], status=200, pagination=meta)


@bp.route("/marketplace/payouts/<pid>/pay", methods=["POST"])
def pay_payout(pid):
    auth = authenticate()
    require_roles(auth, {"PlatformAdmin"})
    p = get_payout(pid)
    if p["status"] != "PENDING":
        raise err(errors.ERR_INVALID_STATE, "Payout not PENDING")

    caregiver = get_caregiver(p["caregiver_id"])
    family = get_family(p["family_id"])

    p["status"] = "PAID"
    touch(p)

    caregiver["pending_earnings_cents"] -= p["net_pay_cents"]
    caregiver["lifetime_paid_cents"] += p["net_pay_cents"]
    touch(caregiver)

    family["tax_withheld_ytd_cents"] += p["fica_withheld_cents"]
    touch(family)

    return ok(payout_out(p), status=200)


@bp.route("/marketplace/payouts/<pid>/reverse", methods=["POST"])
def reverse_payout(pid):
    auth = authenticate()
    require_roles(auth, {"PlatformAdmin"})
    p = get_payout(pid)
    if p["status"] != "PAID":
        raise err(errors.ERR_INVALID_STATE, "Payout not PAID")

    caregiver = get_caregiver(p["caregiver_id"])
    family = get_family(p["family_id"])

    p["status"] = "REVERSED"
    touch(p)

    # Exact compensating reversal (§3.9).
    caregiver["lifetime_paid_cents"] -= p["net_pay_cents"]
    touch(caregiver)

    family["tax_withheld_ytd_cents"] -= p["fica_withheld_cents"]
    family["cash_wages_ytd_cents"] -= p["gross_pay_cents"]
    recompute_w2_obligation(family)
    touch(family)

    return ok(payout_out(p), status=200)
