"""Wristbands + cashless wallet routes."""
from flask import request
from db import db, insert, touch
from errors import err
from response import ok_object, ok_array
from util import round2
import serialize as S
import calculations as calc
from common import (
    body, pagination, paginate, find, auth,
    as_str, as_number, recompute_wallet_liability,
)


def _log_txn(fields):
    """Wallet txns are append-only logs (no version/updated_at)."""
    return insert(db.wallet_txns, fields, common=False)


def register(app):

    # ===================== Issue =====================
    @app.route("/festivals/<fid>/wristbands", methods=["POST"])
    def issue_wristband(fid):
        auth(["BoxOffice"])
        find(db.festivals, fid)
        data = body()
        rfid_uid = as_str(data, "rfid_uid")
        # priority 15: duplicate rfid among non-VOID wristbands in same festival
        for w in db.wristbands.values():
            if (w["festival_id"] == fid and w["rfid_uid"] == rfid_uid
                    and w["lifecycle_status"] != "VOID"):
                raise err("ERR_DUPLICATE_RFID", "rfid_uid already in use")
        rec = insert(db.wristbands, {
            "festival_id": fid,
            "rfid_uid": rfid_uid,
            "lifecycle_status": "ISSUED",
            "presence_status": "OUTSIDE",
            "balance": 0.0,
            "entry_count": 0,
            "reentry_used": 0,
        })
        return ok_object(S.wristband(rec), 201)

    @app.route("/festivals/<fid>/wristbands", methods=["GET"])
    def list_festival_wristbands(fid):
        auth(["FestivalDirector", "BoxOffice", "GateAttendant"])
        find(db.festivals, fid)
        limit, offset = pagination()
        rows = [w for w in db.wristbands.values() if w["festival_id"] == fid]
        page, total = paginate(rows, limit, offset)
        return ok_array([S.wristband(r) for r in page], limit, offset, total)

    @app.route("/wristbands/<wid>", methods=["GET"])
    def get_wristband(wid):
        auth(["FestivalDirector", "BoxOffice", "GateAttendant"])
        return ok_object(S.wristband(find(db.wristbands, wid)))

    # ===================== Activate =====================
    @app.route("/wristbands/<wid>/activate", methods=["POST"])
    def activate_wristband(wid):
        auth(["BoxOffice"])
        w = find(db.wristbands, wid)
        fest = db.festivals[w["festival_id"]]
        data = body()
        ticket_id = data.get("ticket_id")
        if ticket_id is None:
            raise err("ERR_INVALID_REQUEST", "ticket_id is required")
        ticket = db.tickets.get(ticket_id)
        # priority 4: FK resolution (same festival)
        if ticket is None or ticket["festival_id"] != w["festival_id"]:
            raise err("ERR_FK_NOT_FOUND", "ticket_id does not resolve in this festival")
        # priority 6: state — wristband must be ISSUED
        if w["lifecycle_status"] != "ISSUED":
            raise err("ERR_INVALID_STATE", "wristband must be ISSUED to activate")
        # priority 7: posture must be ON_SALE or LIVE
        if fest["operational_posture"] not in ("ON_SALE", "LIVE"):
            raise err("ERR_FESTIVAL_POSTURE",
                      "activation requires ON_SALE or LIVE posture")
        # ticket must be SOLD and unlinked
        if ticket["status"] != "SOLD" or ticket.get("wristband_id") is not None:
            raise err("ERR_INVALID_STATE",
                      "ticket must be SOLD and not already linked")
        ticket["wristband_id"] = wid
        ticket["status"] = "ACTIVATED"
        touch(ticket)
        w["lifecycle_status"] = "ACTIVE"
        touch(w)
        return ok_object(S.wristband(w))

    # ===================== Top-up =====================
    @app.route("/wristbands/<wid>/topup", methods=["POST"])
    def topup_wristband(wid):
        auth(["BoxOffice"])
        w = find(db.wristbands, wid)
        fest = db.festivals[w["festival_id"]]
        data = body()
        amount = as_number(data, "amount")
        if amount <= 0:
            raise err("ERR_INVALID_REQUEST", "amount must be positive")
        amount = round2(amount)
        # priority 6: state — wristband must be ACTIVE
        if w["lifecycle_status"] != "ACTIVE":
            raise err("ERR_INVALID_STATE", "wristband must be ACTIVE to top up")
        txn = _log_txn({
            "wristband_id": wid,
            "festival_id": w["festival_id"],
            "kind": "TOPUP",
            "amount": amount,
            "booth_zone_id": None,
            "vendor_application_id": None,
        })
        w["balance"] = round2(w["balance"] + amount)
        touch(w)
        fest["total_wallet_liability"] = round2(fest["total_wallet_liability"] + amount)
        touch(fest)
        return ok_object(S.wallet_txn(txn), 201)

    # ===================== Spend =====================
    @app.route("/wristbands/<wid>/spend", methods=["POST"])
    def spend_wristband(wid):
        auth(["BoxOffice"])
        w = find(db.wristbands, wid)
        fest = db.festivals[w["festival_id"]]
        data = body()
        amount = as_number(data, "amount")
        booth_zone_id = data.get("booth_zone_id")
        if booth_zone_id is None:
            raise err("ERR_INVALID_REQUEST", "booth_zone_id is required")
        # priority 4: FK resolution of booth_zone_id (same festival)
        zone = db.zones.get(booth_zone_id)
        if zone is None or zone["festival_id"] != w["festival_id"]:
            raise err("ERR_FK_NOT_FOUND",
                      "booth_zone_id does not resolve in this festival")
        if amount <= 0:
            raise err("ERR_INVALID_REQUEST", "amount must be positive")
        amount = round2(amount)
        # priority 6: state — wristband must be ACTIVE
        if w["lifecycle_status"] != "ACTIVE":
            raise err("ERR_INVALID_STATE", "wristband must be ACTIVE to spend")
        # priority 18: insufficient balance
        if w["balance"] < amount:
            raise err("ERR_INSUFFICIENT_BALANCE", "balance is insufficient")
        # find confirmed vendor application occupying this zone (if any)
        vendor_app_id = None
        for ap in db.vendor_applications.values():
            if (ap["booth_zone_id"] == booth_zone_id
                    and ap["status"] == "CONFIRMED"):
                vendor_app_id = ap["id"]
                break
        txn = _log_txn({
            "wristband_id": wid,
            "festival_id": w["festival_id"],
            "kind": "SPEND",
            "amount": amount,
            "booth_zone_id": booth_zone_id,
            "vendor_application_id": vendor_app_id,
        })
        w["balance"] = round2(w["balance"] - amount)
        touch(w)
        fest["total_wallet_liability"] = round2(fest["total_wallet_liability"] - amount)
        touch(fest)
        return ok_object(S.wallet_txn(txn), 201)

    # ===================== Freeze / Unfreeze =====================
    @app.route("/wristbands/<wid>/freeze", methods=["POST"])
    def freeze_wristband(wid):
        auth(["FestivalDirector"])
        w = find(db.wristbands, wid)
        if w["lifecycle_status"] != "ACTIVE":
            raise err("ERR_INVALID_STATE", "wristband must be ACTIVE to freeze")
        fest = db.festivals[w["festival_id"]]
        w["lifecycle_status"] = "FROZEN"
        touch(w)
        recompute_wallet_liability(fest)
        touch(fest)
        return ok_object(S.wristband(w))

    @app.route("/wristbands/<wid>/unfreeze", methods=["POST"])
    def unfreeze_wristband(wid):
        auth(["FestivalDirector"])
        w = find(db.wristbands, wid)
        if w["lifecycle_status"] != "FROZEN":
            raise err("ERR_INVALID_STATE", "wristband must be FROZEN to unfreeze")
        fest = db.festivals[w["festival_id"]]
        # festival must not be CANCELLED
        if fest["operational_posture"] == "CANCELLED":
            raise err("ERR_FESTIVAL_POSTURE",
                      "cannot unfreeze on a cancelled festival")
        w["lifecycle_status"] = "ACTIVE"
        touch(w)
        recompute_wallet_liability(fest)
        touch(fest)
        return ok_object(S.wristband(w))

    # ===================== Cash-out =====================
    @app.route("/wristbands/<wid>/cashout", methods=["POST"])
    def cashout_wristband(wid):
        auth(["BoxOffice"])
        w = find(db.wristbands, wid)
        fest = db.festivals[w["festival_id"]]
        # priority 6: state — must be ACTIVE
        if w["lifecycle_status"] != "ACTIVE":
            raise err("ERR_INVALID_STATE", "wristband must be ACTIVE to cash out")
        # presence must be OUTSIDE
        if w["presence_status"] != "OUTSIDE":
            raise err("ERR_INVALID_STATE",
                      "wristband must be OUTSIDE to cash out")
        pre_balance = w["balance"]
        refund_amount, fee = calc.wristband_cashout(
            pre_balance, fest["wristband_cashout_pct"])
        _log_txn({
            "wristband_id": wid,
            "festival_id": w["festival_id"],
            "kind": "CASHOUT",
            "amount": refund_amount,
            "booth_zone_id": None,
            "vendor_application_id": None,
        })
        _log_txn({
            "wristband_id": wid,
            "festival_id": w["festival_id"],
            "kind": "CASHOUT_FEE",
            "amount": fee,
            "booth_zone_id": None,
            "vendor_application_id": None,
        })
        w["balance"] = 0.0
        w["lifecycle_status"] = "CLOSED"
        touch(w)
        fest["total_wallet_liability"] = round2(
            fest["total_wallet_liability"] - pre_balance)
        touch(fest)
        return ok_object(S.wristband(w))

    # ===================== Void =====================
    @app.route("/wristbands/<wid>/void", methods=["POST"])
    def void_wristband(wid):
        auth(["BoxOffice"])
        w = find(db.wristbands, wid)
        if w["lifecycle_status"] != "ISSUED":
            raise err("ERR_INVALID_STATE", "only an ISSUED wristband may be voided")
        w["lifecycle_status"] = "VOID"
        touch(w)
        return ok_object(S.wristband(w))

    # ===================== Wallet txns =====================
    @app.route("/wristbands/<wid>/wallet-txns", methods=["GET"])
    def list_wristband_txns(wid):
        auth(["FestivalDirector", "BoxOffice"])
        find(db.wristbands, wid)
        limit, offset = pagination()
        rows = [t for t in db.wallet_txns.values() if t["wristband_id"] == wid]
        page, total = paginate(rows, limit, offset)
        return ok_array([S.wallet_txn(r) for r in page], limit, offset, total)

    @app.route("/wallet-txns", methods=["GET"])
    def list_wallet_txns():
        auth(["FestivalDirector", "BoxOffice"])
        limit, offset = pagination()
        fid = request.args.get("festival_id")
        zone_id = request.args.get("booth_zone_id")
        vapp_id = request.args.get("vendor_application_id")
        rows = list(db.wallet_txns.values())
        if fid is not None:
            rows = [t for t in rows if t["festival_id"] == fid]
        if zone_id is not None:
            rows = [t for t in rows if t["booth_zone_id"] == zone_id]
        if vapp_id is not None:
            rows = [t for t in rows if t["vendor_application_id"] == vapp_id]
        page, total = paginate(rows, limit, offset)
        return ok_array([S.wallet_txn(r) for r in page], limit, offset, total)

    @app.route("/wallet-txns/<txid>", methods=["GET"])
    def get_wallet_txn(txid):
        auth(["FestivalDirector", "BoxOffice"])
        return ok_object(S.wallet_txn(find(db.wallet_txns, txid)))
