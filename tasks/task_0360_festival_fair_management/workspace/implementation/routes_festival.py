"""Festival lifecycle + sales report + clock routes."""
from db import db, insert, touch
from errors import err
from response import ok_object, ok_array
from util import parse_iso_date, round2, now_iso
import serialize as S
import calculations as calc
from common import (
    body, pagination, paginate, find, auth, server_today,
    as_str, as_int, as_number, recompute_wallet_liability, recompute_refund_liability,
)

ALL_ROLES = ["FestivalDirector", "BoxOffice", "VendorManager", "GateAttendant", "Vendor"]


def register(app):

    # ---- Create ----
    @app.route("/festivals", methods=["POST"])
    def create_festival():
        auth(["FestivalDirector"])
        data = body()
        name = as_str(data, "name")
        start_date = as_str(data, "start_date")
        end_date = as_str(data, "end_date")
        # parse + validate dates (shape)
        try:
            sd = parse_iso_date(start_date)
            ed = parse_iso_date(end_date)
        except Exception:
            raise err("ERR_INVALID_REQUEST", "start_date/end_date must be YYYY-MM-DD")
        total_days = (ed - sd).days + 1
        if total_days < 1:
            raise err("ERR_INVALID_REQUEST", "end_date must be on or after start_date")
        max_reentries = as_int(data, "max_reentries", required=False)
        if max_reentries is None:
            max_reentries = 1
        cashout_pct = as_number(data, "wristband_cashout_pct", required=False)
        if cashout_pct is None:
            cashout_pct = 0.03
        commission_pct = as_number(data, "vendor_commission_pct", required=False)
        if commission_pct is None:
            commission_pct = 0.08
        rec = insert(db.festivals, {
            "name": name,
            "start_date": start_date,
            "end_date": end_date,
            "total_days": total_days,
            "operational_posture": "PLANNING",
            "current_festival_day": 0,
            "max_reentries": max_reentries,
            "wristband_cashout_pct": cashout_pct,
            "vendor_commission_pct": commission_pct,
            "total_wallet_liability": 0.0,
            "total_refund_liability": 0.0,
        })
        return ok_object(S.festival(rec), 201)

    @app.route("/festivals/<fid>", methods=["GET"])
    def get_festival(fid):
        auth(ALL_ROLES)
        rec = find(db.festivals, fid)
        return ok_object(S.festival(rec))

    @app.route("/festivals", methods=["GET"])
    def list_festivals():
        auth(ALL_ROLES)
        limit, offset = pagination()
        page, total = paginate(list(db.festivals.values()), limit, offset)
        return ok_array([S.festival(r) for r in page], limit, offset, total)

    # ---- Posture transitions ----
    def _transition(fid, allowed_from, to_state):
        rec = find(db.festivals, fid)
        if rec["operational_posture"] not in allowed_from:
            raise err("ERR_INVALID_STATE", "transition not allowed from %s"
                      % rec["operational_posture"])
        return rec

    @app.route("/festivals/<fid>/open-sales", methods=["POST"])
    def open_sales(fid):
        auth(["FestivalDirector"])
        rec = _transition(fid, ["PLANNING"], "ON_SALE")
        # precondition: >=1 zone and >=1 stage
        has_zone = any(z["festival_id"] == fid for z in db.zones.values())
        has_stage = any(s["festival_id"] == fid for s in db.stages.values())
        if not (has_zone and has_stage):
            raise err("ERR_INVALID_STATE",
                      "festival requires at least one zone and one stage")
        rec["operational_posture"] = "ON_SALE"
        touch(rec)
        return ok_object(S.festival(rec))

    @app.route("/festivals/<fid>/go-live", methods=["POST"])
    def go_live(fid):
        auth(["FestivalDirector"])
        rec = _transition(fid, ["ON_SALE"], "LIVE")
        rec["operational_posture"] = "LIVE"
        rec["current_festival_day"] = 1
        touch(rec)
        return ok_object(S.festival(rec))

    @app.route("/festivals/<fid>/open-day", methods=["POST"])
    def open_day(fid):
        auth(["FestivalDirector"])
        rec = find(db.festivals, fid)
        if rec["operational_posture"] != "LIVE":
            raise err("ERR_INVALID_STATE", "open-day requires LIVE posture")
        data = body()
        day = as_int(data, "day")
        if day < 1 or day > rec["total_days"]:
            raise err("ERR_DAYCOUNT_RANGE", "day out of range 1..total_days")
        rec["current_festival_day"] = day
        touch(rec)
        return ok_object(S.festival(rec))

    @app.route("/festivals/<fid>/weather-hold", methods=["POST"])
    def weather_hold(fid):
        auth(["FestivalDirector"])
        rec = _transition(fid, ["LIVE"], "SUSPENDED")
        rec["operational_posture"] = "SUSPENDED"
        touch(rec)
        return ok_object(S.festival(rec))

    @app.route("/festivals/<fid>/resume", methods=["POST"])
    def resume(fid):
        auth(["FestivalDirector"])
        rec = _transition(fid, ["SUSPENDED"], "LIVE")
        rec["operational_posture"] = "LIVE"
        touch(rec)
        return ok_object(S.festival(rec))

    @app.route("/festivals/<fid>/close", methods=["POST"])
    def close_festival(fid):
        auth(["FestivalDirector"])
        rec = _transition(fid, ["LIVE"], "CLOSED")
        if rec["current_festival_day"] != rec["total_days"]:
            raise err("ERR_INVALID_STATE", "close requires final day reached")
        rec["operational_posture"] = "CLOSED"
        touch(rec)
        return ok_object(S.festival(rec))

    @app.route("/festivals/<fid>/cancel", methods=["POST"])
    def cancel_festival(fid):
        auth(["FestivalDirector"])
        rec = _transition(fid, ["ON_SALE", "SUSPENDED"], "CANCELLED")
        _run_cancel_cascade(rec)
        rec["operational_posture"] = "CANCELLED"
        touch(rec)
        return ok_object(S.festival(rec))

    # ---- Sales report ----
    @app.route("/festivals/<fid>/sales-report", methods=["GET"])
    def sales_report(fid):
        auth(["FestivalDirector", "BoxOffice"])
        rec = find(db.festivals, fid)
        ticket_revenue = round2(sum(
            t["face_value"] for t in db.tickets.values()
            if t["festival_id"] == fid and t["status"] in ("SOLD", "ACTIVATED")
        ))
        addon_revenue = round2(sum(
            a["price"] for a in db.addons.values()
            if a["festival_id"] == fid and a["status"] == "SOLD"
        ))
        cashless_volume = round2(sum(
            tx["amount"] for tx in db.wallet_txns.values()
            if tx["festival_id"] == fid and tx["kind"] == "SPEND"
        ))
        refunds_issued = round2(sum(
            r["amount"] for r in db.refunds.values()
            if r["festival_id"] == fid and r["status"] == "ISSUED"
        ))
        net_revenue = round2(ticket_revenue + addon_revenue - refunds_issued)
        return ok_object({
            "ticket_revenue": ticket_revenue,
            "addon_revenue": addon_revenue,
            "cashless_volume": cashless_volume,
            "refunds_issued": refunds_issued,
            "net_revenue": net_revenue,
        })

    @app.route("/festivals/<fid>/refunds", methods=["GET"])
    def list_festival_refunds(fid):
        auth(["FestivalDirector", "BoxOffice"])
        find(db.festivals, fid)
        limit, offset = pagination()
        rows = [r for r in db.refunds.values() if r["festival_id"] == fid]
        page, total = paginate(rows, limit, offset)
        return ok_array([S.refund(r) for r in page], limit, offset, total)

    @app.route("/refunds/<rid>", methods=["GET"])
    def get_refund(rid):
        auth(["FestivalDirector", "BoxOffice"])
        rec = find(db.refunds, rid)
        return ok_object(S.refund(rec))

    @app.route("/refunds", methods=["GET"])
    def list_refunds():
        auth(["FestivalDirector", "BoxOffice"])
        limit, offset = pagination()
        from flask import request
        ticket_id = request.args.get("ticket_id")
        rows = list(db.refunds.values())
        if ticket_id is not None:
            rows = [r for r in rows if r["ticket_id"] == ticket_id]
        page, total = paginate(rows, limit, offset)
        return ok_array([S.refund(r) for r in page], limit, offset, total)

    # ---- Test clock ----
    @app.route("/_clock/set_current_utc", methods=["POST"])
    def set_clock():
        auth(["FestivalDirector"])
        data = body()
        to_iso = as_str(data, "to_iso8601")
        db.clock_iso = to_iso
        return ok_object({"current_utc": to_iso})


def _run_cancel_cascade(fest):
    """Refund every SOLD/ACTIVATED ticket via weather pro-rata, freeze active
    linked wristbands, refund add-ons, cancel performances (PRD §3.1)."""
    fid = fest["id"]
    elapsed = fest["current_festival_day"]
    total_days = fest["total_days"]

    for t in list(db.tickets.values()):
        if t["festival_id"] != fid:
            continue
        if t["status"] in ("SOLD", "ACTIVATED"):
            amount, fee = calc.weather_prorata_refund(t["face_value"], elapsed, total_days)
            refund = insert(db.refunds, {
                "festival_id": fid,
                "ticket_id": t["id"],
                "refund_kind": "WEATHER_PRORATA",
                "amount": amount,
                "fee_withheld": fee,
                "status": "ISSUED",
            })
            t["status"] = "REFUNDED"
            touch(t)
            fest["total_refund_liability"] = round2(
                fest["total_refund_liability"] + amount)
            # depth-3 chain: refund -> freeze linked ACTIVE wristband -> recompute liability
            wid = t.get("wristband_id")
            if wid:
                w = db.wristbands.get(wid)
                if w and w["lifecycle_status"] == "ACTIVE":
                    w["lifecycle_status"] = "FROZEN"
                    touch(w)
                    recompute_wallet_liability(fest)
                    touch(fest)

    for p in db.performances.values():
        if p["festival_id"] == fid and p["status"] == "SCHEDULED":
            p["status"] = "CANCELLED"
            touch(p)

    for a in db.addons.values():
        if a["festival_id"] == fid and a["status"] == "SOLD":
            a["status"] = "REFUNDED"
            touch(a)
