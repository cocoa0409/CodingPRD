"""Tickets, Add-ons, voluntary Refunds."""
from flask import request
from db import db, insert, touch
from errors import err
from response import ok_object, ok_array
from util import round2
import serialize as S
import calculations as calc
from common import (
    body, pagination, paginate, find, auth, server_today,
    as_str, as_int, as_number, as_enum,
)


def register(app):

    # ===================== Tickets =====================
    @app.route("/festivals/<fid>/tickets", methods=["POST"])
    def sell_ticket(fid):
        auth(["BoxOffice"])
        fest = find(db.festivals, fid)
        data = body()
        # priority 7: posture gate (sell requires ON_SALE)
        if fest["operational_posture"] != "ON_SALE":
            raise err("ERR_FESTIVAL_POSTURE", "ticket sales require ON_SALE posture")
        ticket_type = as_enum(data, "ticket_type", ("GA", "VIP"))
        day_count = as_int(data, "day_count")
        purchaser_email = as_str(data, "purchaser_email")
        # priority 20: daycount range
        if day_count < 1 or day_count > fest["total_days"]:
            raise err("ERR_DAYCOUNT_RANGE", "day_count out of range 1..total_days")
        face_value = calc.ticket_face_value(ticket_type, day_count)
        rec = insert(db.tickets, {
            "festival_id": fid,
            "wristband_id": None,
            "ticket_type": ticket_type,
            "day_count": day_count,
            "face_value": face_value,
            "status": "SOLD",
            "purchaser_email": purchaser_email,
        })
        return ok_object(S.ticket(rec), 201)

    @app.route("/festivals/<fid>/tickets", methods=["GET"])
    def list_festival_tickets(fid):
        auth(["FestivalDirector", "BoxOffice"])
        find(db.festivals, fid)
        limit, offset = pagination()
        rows = [t for t in db.tickets.values() if t["festival_id"] == fid]
        page, total = paginate(rows, limit, offset)
        return ok_array([S.ticket(r) for r in page], limit, offset, total)

    @app.route("/tickets/<tid>", methods=["GET"])
    def get_ticket(tid):
        auth(["FestivalDirector", "BoxOffice"])
        return ok_object(S.ticket(find(db.tickets, tid)))

    @app.route("/tickets", methods=["GET"])
    def list_tickets():
        auth(["FestivalDirector", "BoxOffice"])
        limit, offset = pagination()
        wid = request.args.get("wristband_id")
        rows = list(db.tickets.values())
        if wid is not None:
            rows = [t for t in rows if t["wristband_id"] == wid]
        page, total = paginate(rows, limit, offset)
        return ok_array([S.ticket(r) for r in page], limit, offset, total)

    # ===================== Voluntary refund =====================
    @app.route("/tickets/<tid>/refund", methods=["POST"])
    def refund_ticket(tid):
        auth(["BoxOffice"])
        ticket = find(db.tickets, tid)
        # priority 6: state — only a SOLD ticket may be voluntarily refunded
        if ticket["status"] != "SOLD":
            raise err("ERR_INVALID_STATE",
                      "only a SOLD ticket may be refunded voluntarily")
        fest = db.festivals[ticket["festival_id"]]
        from util import parse_iso_date
        start_date = parse_iso_date(fest["start_date"])
        today = server_today()
        amount, fee = calc.voluntary_tiered_refund(ticket["face_value"], today, start_date)
        refund = insert(db.refunds, {
            "festival_id": fest["id"],
            "ticket_id": tid,
            "refund_kind": "VOLUNTARY_TIERED",
            "amount": amount,
            "fee_withheld": fee,
            "status": "ISSUED",
        })
        ticket["status"] = "REFUNDED"
        touch(ticket)
        fest["total_refund_liability"] = round2(fest["total_refund_liability"] + amount)
        touch(fest)
        return ok_object(S.refund(refund), 201)

    # ===================== Add-ons =====================
    @app.route("/tickets/<tid>/add-ons", methods=["POST"])
    def sell_addon(tid):
        auth(["BoxOffice"])
        ticket = find(db.tickets, tid)
        fest = db.festivals[ticket["festival_id"]]
        fid = fest["id"]
        data = body()
        kind = as_enum(data, "kind", ("PARKING", "CAMPING"))

        if kind == "PARKING":
            # priority 4: FK resolution for parking_lot_id
            lot_id = data.get("parking_lot_id")
            if lot_id is None:
                # p21 missing required field (kind-specific combo)
                raise err("ERR_INVALID_REQUEST",
                          "PARKING add-on requires parking_lot_id")
            lot = db.parking_lots.get(lot_id)
            if lot is None or lot["festival_id"] != fid:
                raise err("ERR_FK_NOT_FOUND",
                          "parking_lot_id does not resolve in this festival")
            # priority 9: OCC on lot version (mandatory for PARKING)
            expected = data.get("expected_lot_version")
            if expected is None:
                raise err("ERR_INVALID_REQUEST",
                          "expected_lot_version is required for PARKING add-ons")
            if expected != lot["version"]:
                raise err("ERR_STALE_LOT_VERSION",
                          "expected_lot_version does not match lot version")
            # priority 17: capacity full
            if lot["sold_count"] >= lot["capacity"]:
                raise err("ERR_CAPACITY_FULL", "parking lot is full")
            price = round2(lot["price_per_pass"])
            rec = insert(db.addons, {
                "festival_id": fid,
                "ticket_id": tid,
                "kind": "PARKING",
                "parking_lot_id": lot_id,
                "camping_area_id": None,
                "nights": None,
                "price": price,
                "status": "SOLD",
            })
            lot["sold_count"] += 1
            touch(lot)
            return ok_object(S.addon(rec), 201)

        else:  # CAMPING
            area_id = data.get("camping_area_id")
            nights = data.get("nights")
            if area_id is None or nights is None:
                raise err("ERR_INVALID_REQUEST",
                          "CAMPING add-on requires camping_area_id and nights")
            area = db.camping_areas.get(area_id)
            if area is None or area["festival_id"] != fid:
                raise err("ERR_FK_NOT_FOUND",
                          "camping_area_id does not resolve in this festival")
            if isinstance(nights, bool) or not isinstance(nights, int):
                raise err("ERR_INVALID_REQUEST", "nights must be an integer")
            # priority 20: nights range
            if nights < 1 or nights > fest["total_days"]:
                raise err("ERR_DAYCOUNT_RANGE", "nights out of range 1..total_days")
            # priority 17: capacity full
            if area["sold_count"] >= area["capacity"]:
                raise err("ERR_CAPACITY_FULL", "camping area is full")
            price = round2(area["price_per_night"] * nights)
            rec = insert(db.addons, {
                "festival_id": fid,
                "ticket_id": tid,
                "kind": "CAMPING",
                "parking_lot_id": None,
                "camping_area_id": area_id,
                "nights": nights,
                "price": price,
                "status": "SOLD",
            })
            area["sold_count"] += 1
            touch(area)
            return ok_object(S.addon(rec), 201)

    @app.route("/tickets/<tid>/add-ons", methods=["GET"])
    def list_ticket_addons(tid):
        auth(["FestivalDirector", "BoxOffice"])
        find(db.tickets, tid)
        limit, offset = pagination()
        rows = [a for a in db.addons.values() if a["ticket_id"] == tid]
        page, total = paginate(rows, limit, offset)
        return ok_array([S.addon(r) for r in page], limit, offset, total)

    @app.route("/add-ons", methods=["GET"])
    def list_addons():
        auth(["FestivalDirector", "BoxOffice"])
        limit, offset = pagination()
        fid = request.args.get("festival_id")
        lot_id = request.args.get("parking_lot_id")
        area_id = request.args.get("camping_area_id")
        rows = list(db.addons.values())
        if fid is not None:
            rows = [a for a in rows if a["festival_id"] == fid]
        if lot_id is not None:
            rows = [a for a in rows if a["parking_lot_id"] == lot_id]
        if area_id is not None:
            rows = [a for a in rows if a["camping_area_id"] == area_id]
        page, total = paginate(rows, limit, offset)
        return ok_array([S.addon(r) for r in page], limit, offset, total)

    @app.route("/add-ons/<aid>", methods=["GET"])
    def get_addon(aid):
        auth(["FestivalDirector", "BoxOffice"])
        return ok_object(S.addon(find(db.addons, aid)))
