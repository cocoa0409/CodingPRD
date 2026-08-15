"""Draw requests: create / approve (reservation + shortfall assessment) / pay."""

from db import store, now
from errors import ApiError
from helpers import (
    get_body, check_allowed_fields, req_string, req_int, opt_bool,
    get_draw_or_404, get_holdback_or_404, file_of_holdback,
    new_entity, touch, append_ledger, rhu_half, refresh_holdback_derived,
    ser_draw,
)
from middleware import authenticate, authorize
from response import success

from . import bp

VERIFYING_PURPOSES = {"DRAW_VERIFICATION", "FINAL_VERIFICATION"}


def _mk_pledge(hb, payer_role, payer_user_id, amount):
    p = new_entity()
    p.update({
        "holdback_id": hb["id"],
        "payer_role": payer_role,
        "payer_user_id": payer_user_id,
        "amount_cents": amount,
        "status": "PLEDGED",
        "deposited_at": None,
    })
    store.pledges[p["id"]] = p
    return p


@bp.post("/escrow/draw-requests")
def create_draw():
    uid, role = authenticate()
    authorize(role, ["Contractor"])
    data = get_body()
    raw_hid = data.get("holdback_id")
    if isinstance(raw_hid, str) and raw_hid not in store.holdbacks:
        raise ApiError("ERR_NOT_FOUND", "Holdback not found: %s" % raw_hid)
    check_allowed_fields(data, {"holdback_id", "amount_cents", "description", "is_final"})
    hid = req_string(data, "holdback_id")
    hb = get_holdback_or_404(hid)
    amount = req_int(data, "amount_cents", lo=1)
    description = req_string(data, "description")
    is_final = opt_bool(data, "is_final", False)

    # Rung 5: ownership through the selection; skipped when no bid is
    # selected (the later state gate ERR_NO_SELECTED_CONTRACTOR fires).
    if hb["selected_bid_id"] is not None:
        sel = store.bids.get(hb["selected_bid_id"])
        if sel is None or uid != sel["contractor_user_id"]:
            raise ApiError("ERR_NOT_FILE_PARTY", "Only the engaged contractor may request draws")
    # Rung 8 (fixed internal order): ACTIVE, then selected contractor.
    if hb["status"] != "ACTIVE":
        raise ApiError("ERR_HOLDBACK_NOT_ACTIVE", "Draws require an ACTIVE holdback")
    if hb["selected_bid_id"] is None:
        raise ApiError("ERR_NO_SELECTED_CONTRACTOR", "No bid has been selected on the holdback")
    # Rung 10: one SUBMITTED draw at a time.
    for d in store.draws.values():
        if d["holdback_id"] == hid and d["status"] == "SUBMITTED":
            raise ApiError("ERR_DRAW_ALREADY_OPEN", "A SUBMITTED draw already exists")

    d = new_entity()
    d.update({
        "holdback_id": hid,
        "contractor_user_id": uid,
        "amount_cents": amount,
        "description": description,
        "is_final": is_final,
        "status": "SUBMITTED",
        "approved_at": None,
        "paid_at": None,
    })
    store.draws[d["id"]] = d
    return success(ser_draw(d), response_type="object", status=201)


@bp.post("/escrow/draw-requests/<did>/approve")
def approve_draw(did):
    _uid, role = authenticate()
    authorize(role, ["EscrowOfficer"])
    d = get_draw_or_404(did)
    data = get_body()
    check_allowed_fields(data, set())
    hb = get_holdback_or_404(d["holdback_id"])

    # Rung 7: only a SUBMITTED draw can be approved.
    if d["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "Draw request is not in SUBMITTED state")
    # Rung 8: holdback ACTIVE.
    if hb["status"] != "ACTIVE":
        raise ApiError("ERR_HOLDBACK_NOT_ACTIVE", "Draw approval requires an ACTIVE holdback")
    # Rung 9: disbursement freeze.
    if hb["disbursement_frozen"]:
        raise ApiError("ERR_DISPUTE_FROZEN", "An OPEN dispute freezes draw approval")
    # Rung 13: a verifying inspection must exist (PASSED, verifying purpose,
    # reported on/after the draw's creation).
    verified = any(
        i["holdback_id"] == hb["id"]
        and i["status"] == "PASSED"
        and i["purpose"] in VERIFYING_PURPOSES
        and i["reported_at"] is not None
        and i["reported_at"] >= d["created_at"]
        for i in store.inspections.values()
    )
    if not verified:
        raise ApiError("ERR_NO_VERIFYING_INSPECTION", "No PASSED verifying inspection on/after draw creation")

    d["status"] = "APPROVED"
    d["approved_at"] = now()
    touch(d)
    hb["reserved_cents"] += d["amount_cents"]

    # Shortfall assessment: projected excess strictly greater than zero.
    projected_excess = (
        (hb["total_disbursed_cents"] + hb["reserved_cents"])
        - (hb["holdback_amount_cents"] + hb["total_shortfall_deposited_cents"])
    )
    if projected_excess > 0:
        f = file_of_holdback(hb)
        resp = hb["overrun_responsibility"]
        if resp == "BUYER":
            _mk_pledge(hb, "BUYER", f["buyer_user_id"], projected_excess)
        elif resp == "SELLER":
            _mk_pledge(hb, "SELLER", f["seller_user_id"], projected_excess)
        else:  # SPLIT_EQUAL: buyer rounded half-up first, seller residual.
            buyer_share = rhu_half(projected_excess)
            seller_share = projected_excess - buyer_share
            _mk_pledge(hb, "BUYER", f["buyer_user_id"], buyer_share)
            _mk_pledge(hb, "SELLER", f["seller_user_id"], seller_share)

    refresh_holdback_derived(hb)
    touch(hb)
    return success(ser_draw(d), response_type="object", status=200)


@bp.post("/escrow/draw-requests/<did>/pay")
def pay_draw(did):
    _uid, role = authenticate()
    authorize(role, ["EscrowOfficer"])
    d = get_draw_or_404(did)
    data = get_body()
    check_allowed_fields(data, set())
    hb = get_holdback_or_404(d["holdback_id"])

    # Rung 7: paying a terminal draw (PAID/CANCELLED) is a generic state error.
    if d["status"] in ("PAID", "CANCELLED"):
        raise ApiError("ERR_INVALID_STATE", "Draw request is already in a terminal state")
    # Rung 8 (fixed internal order): holdback ACTIVE, then draw must be APPROVED.
    if hb["status"] != "ACTIVE":
        raise ApiError("ERR_HOLDBACK_NOT_ACTIVE", "Draw payment requires an ACTIVE holdback")
    if d["status"] == "SUBMITTED":
        raise ApiError("ERR_DRAW_NOT_APPROVED", "Draw request has not been approved")
    # Rung 9: disbursement freeze.
    if hb["disbursement_frozen"]:
        raise ApiError("ERR_DISPUTE_FROZEN", "An OPEN dispute freezes draw payment")
    # Rung 15: no PLEDGED shortfall pledge may remain.
    if any(p["status"] == "PLEDGED" for p in store.pledges.values() if p["holdback_id"] == hb["id"]):
        raise ApiError("ERR_SHORTFALL_UNFUNDED", "A PLEDGED shortfall pledge has not been deposited")

    append_ledger(hb, "DRAW_DEBIT", -d["amount_cents"],
                  "Payment of approved draw %s" % d["id"])
    hb["total_disbursed_cents"] += d["amount_cents"]
    hb["reserved_cents"] -= d["amount_cents"]
    d["status"] = "PAID"
    d["paid_at"] = now()
    touch(d)
    refresh_holdback_derived(hb)
    touch(hb)
    return success(ser_draw(d), response_type="object", status=200)
