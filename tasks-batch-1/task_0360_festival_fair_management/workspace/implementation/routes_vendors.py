"""Vendors + booth application lifecycle + settlement."""
from flask import request
from db import db, insert, touch
from errors import err
from response import ok_object, ok_array
from util import round2
import serialize as S
import calculations as calc
from common import (
    body, pagination, paginate, find, auth,
    as_str, as_int, as_number, as_enum, as_bool,
)


def register(app):

    # ===================== Vendors =====================
    @app.route("/vendors", methods=["POST"])
    def create_vendor():
        auth(["VendorManager", "Vendor"])
        data = body()
        company_name = as_str(data, "company_name")
        contact_email = as_str(data, "contact_email")
        rec = insert(db.vendors, {
            "company_name": company_name,
            "contact_email": contact_email,
            "payout_total": 0.0,
        })
        return ok_object(S.vendor(rec), 201)

    @app.route("/vendors/<vid>", methods=["GET"])
    def get_vendor(vid):
        auth(["FestivalDirector", "VendorManager", "Vendor"])
        return ok_object(S.vendor(find(db.vendors, vid)))

    # ===================== Applications =====================
    @app.route("/festivals/<fid>/vendor-applications", methods=["POST"])
    def submit_application(fid):
        auth(["Vendor", "VendorManager"])
        fest = find(db.festivals, fid)
        data = body()
        vendor_id = data.get("vendor_id")
        booth_zone_id = data.get("booth_zone_id")
        if vendor_id is None or booth_zone_id is None:
            raise err("ERR_INVALID_REQUEST",
                      "vendor_id and booth_zone_id are required")
        # priority 4: FK resolution
        vendor = db.vendors.get(vendor_id)
        if vendor is None:
            raise err("ERR_FK_NOT_FOUND", "vendor_id does not resolve")
        zone = db.zones.get(booth_zone_id)
        if zone is None or zone["festival_id"] != fid:
            raise err("ERR_FK_NOT_FOUND",
                      "booth_zone_id does not resolve in this festival")
        booth_tier = as_enum(data, "booth_tier", ("STANDARD", "PREMIUM", "FOOD"))
        day_count = as_int(data, "day_count")
        power_addon = as_bool(data, "power_addon", default=False)
        # priority 20: daycount range
        if day_count < 1 or day_count > fest["total_days"]:
            raise err("ERR_DAYCOUNT_RANGE", "day_count out of range 1..total_days")
        rec = insert(db.vendor_applications, {
            "festival_id": fid,
            "vendor_id": vendor_id,
            "booth_zone_id": booth_zone_id,
            "booth_tier": booth_tier,
            "day_count": day_count,
            "power_addon": power_addon,
            "status": "SUBMITTED",
            "booth_fee": None,
            "fee_paid": 0.0,
        })
        return ok_object(S.vendor_application(rec), 201)

    @app.route("/festivals/<fid>/vendor-applications", methods=["GET"])
    def list_festival_applications(fid):
        auth(["FestivalDirector", "VendorManager"])
        find(db.festivals, fid)
        limit, offset = pagination()
        rows = [a for a in db.vendor_applications.values()
                if a["festival_id"] == fid]
        page, total = paginate(rows, limit, offset)
        return ok_array([S.vendor_application(r) for r in page], limit, offset, total)

    @app.route("/vendor-applications/<aid>", methods=["GET"])
    def get_application(aid):
        auth(["FestivalDirector", "VendorManager", "Vendor"])
        return ok_object(S.vendor_application(find(db.vendor_applications, aid)))

    @app.route("/vendor-applications", methods=["GET"])
    def list_applications():
        auth(["FestivalDirector", "VendorManager", "Vendor"])
        limit, offset = pagination()
        vendor_id = request.args.get("vendor_id")
        booth_zone_id = request.args.get("booth_zone_id")
        rows = list(db.vendor_applications.values())
        if vendor_id is not None:
            rows = [a for a in rows if a["vendor_id"] == vendor_id]
        if booth_zone_id is not None:
            rows = [a for a in rows if a["booth_zone_id"] == booth_zone_id]
        page, total = paginate(rows, limit, offset)
        return ok_array([S.vendor_application(r) for r in page], limit, offset, total)

    # ---- Transitions ----
    @app.route("/vendor-applications/<aid>/start-review", methods=["POST"])
    def start_review(aid):
        auth(["VendorManager"])
        ap = find(db.vendor_applications, aid)
        if ap["status"] != "SUBMITTED":
            raise err("ERR_INVALID_STATE", "start-review requires SUBMITTED")
        fest = db.festivals[ap["festival_id"]]
        if fest["operational_posture"] not in ("PLANNING", "ON_SALE"):
            raise err("ERR_FESTIVAL_POSTURE",
                      "review requires PLANNING or ON_SALE posture")
        ap["status"] = "UNDER_REVIEW"
        touch(ap)
        return ok_object(S.vendor_application(ap))

    @app.route("/vendor-applications/<aid>/approve", methods=["POST"])
    def approve_application(aid):
        auth(["VendorManager"])
        ap = find(db.vendor_applications, aid)
        data = body()
        # priority 6: state
        if ap["status"] != "UNDER_REVIEW":
            raise err("ERR_INVALID_STATE", "approve requires UNDER_REVIEW")
        zone = db.zones[ap["booth_zone_id"]]
        # priority 9: OCC on zone version (mandatory)
        expected = data.get("expected_zone_version")
        if expected is None:
            raise err("ERR_INVALID_REQUEST",
                      "expected_zone_version is required on approve")
        if expected != zone["version"]:
            raise err("ERR_STALE_ZONE_VERSION",
                      "expected_zone_version does not match zone version")
        # priority 16: zone full
        if zone["allocated_count"] >= zone["slot_capacity"]:
            raise err("ERR_ZONE_FULL", "zone has no free slot")
        fest = db.festivals[ap["festival_id"]]
        zone_rec = db.zones[ap["booth_zone_id"]]
        fee = calc.booth_fee_calc(
            ap["booth_tier"], ap["day_count"], zone_rec["code"], ap["power_addon"])
        ap["booth_fee"] = fee
        ap["status"] = "APPROVED"
        touch(ap)
        zone["allocated_count"] += 1
        touch(zone)
        return ok_object(S.vendor_application(ap))

    @app.route("/vendor-applications/<aid>/reject", methods=["POST"])
    def reject_application(aid):
        auth(["VendorManager"])
        ap = find(db.vendor_applications, aid)
        if ap["status"] != "UNDER_REVIEW":
            raise err("ERR_INVALID_STATE", "reject requires UNDER_REVIEW")
        fest = db.festivals[ap["festival_id"]]
        if fest["operational_posture"] not in ("PLANNING", "ON_SALE"):
            raise err("ERR_FESTIVAL_POSTURE",
                      "reject requires PLANNING or ON_SALE posture")
        ap["status"] = "REJECTED"
        touch(ap)
        return ok_object(S.vendor_application(ap))

    @app.route("/vendor-applications/<aid>/return-for-revision", methods=["POST"])
    def return_for_revision(aid):
        auth(["VendorManager"])
        ap = find(db.vendor_applications, aid)
        if ap["status"] != "APPROVED":
            raise err("ERR_INVALID_STATE", "return-for-revision requires APPROVED")
        if ap["fee_paid"] != 0:
            raise err("ERR_INVALID_STATE",
                      "cannot revise once any fee has been paid")
        zone = db.zones[ap["booth_zone_id"]]
        ap["status"] = "UNDER_REVIEW"
        ap["booth_fee"] = None
        touch(ap)
        zone["allocated_count"] -= 1
        touch(zone)
        return ok_object(S.vendor_application(ap))

    @app.route("/vendor-applications/<aid>/pay-fee", methods=["POST"])
    def pay_fee(aid):
        user_id, role = auth(["Vendor"])
        ap = find(db.vendor_applications, aid)
        # priority 5: ownership
        if ap["vendor_id"] != user_id:
            raise err("ERR_NOT_OWNER", "vendor does not own this application")
        data = body()
        amount = as_number(data, "amount")
        if amount <= 0:
            raise err("ERR_INVALID_REQUEST", "amount must be positive")
        ap["fee_paid"] = round2(ap["fee_paid"] + amount)
        touch(ap)
        return ok_object(S.vendor_application(ap))

    @app.route("/vendor-applications/<aid>/confirm", methods=["POST"])
    def confirm_application(aid):
        user_id, role = auth(["Vendor"])
        ap = find(db.vendor_applications, aid)
        # priority 5: ownership
        if ap["vendor_id"] != user_id:
            raise err("ERR_NOT_OWNER", "vendor does not own this application")
        # priority 6: state
        if ap["status"] != "APPROVED":
            raise err("ERR_INVALID_STATE", "confirm requires APPROVED")
        fest = db.festivals[ap["festival_id"]]
        # festival must not be CANCELLED (posture gate)
        if fest["operational_posture"] == "CANCELLED":
            raise err("ERR_FESTIVAL_POSTURE",
                      "cannot confirm on a cancelled festival")
        # priority 19: fee unpaid
        if ap["fee_paid"] < (ap["booth_fee"] or 0):
            raise err("ERR_FEE_UNPAID", "fee not paid in full")
        ap["status"] = "CONFIRMED"
        touch(ap)
        return ok_object(S.vendor_application(ap))

    @app.route("/vendor-applications/<aid>/withdraw", methods=["POST"])
    def withdraw_application(aid):
        user_id, role = auth(["Vendor"])
        ap = find(db.vendor_applications, aid)
        # priority 5: ownership
        if ap["vendor_id"] != user_id:
            raise err("ERR_NOT_OWNER", "vendor does not own this application")
        # priority 6: state
        if ap["status"] != "APPROVED":
            raise err("ERR_INVALID_STATE", "withdraw requires APPROVED")
        if ap["fee_paid"] != 0:
            raise err("ERR_INVALID_STATE",
                      "cannot withdraw once any fee has been paid")
        zone = db.zones[ap["booth_zone_id"]]
        ap["status"] = "WITHDRAWN"
        touch(ap)
        zone["allocated_count"] -= 1
        touch(zone)
        return ok_object(S.vendor_application(ap))

    @app.route("/vendor-applications/<aid>/settle", methods=["POST"])
    def settle_application(aid):
        auth(["FestivalDirector"])
        ap = find(db.vendor_applications, aid)
        fest = db.festivals[ap["festival_id"]]
        # posture must be CLOSED
        if fest["operational_posture"] != "CLOSED":
            raise err("ERR_FESTIVAL_POSTURE", "settlement requires CLOSED posture")
        # must be a confirmed booth
        if ap["status"] != "CONFIRMED":
            raise err("ERR_INVALID_STATE", "settle requires CONFIRMED application")
        spend_amounts = [
            tx["amount"] for tx in db.wallet_txns.values()
            if tx["kind"] == "SPEND" and tx["vendor_application_id"] == aid
        ]
        payout = calc.vendor_settlement_payout(
            spend_amounts, fest["vendor_commission_pct"],
            ap["booth_fee"], ap["fee_paid"])
        vendor = db.vendors[ap["vendor_id"]]
        vendor["payout_total"] = round2(vendor["payout_total"] + payout)
        touch(vendor)
        touch(ap)
        return ok_object(S.vendor_application(ap))
