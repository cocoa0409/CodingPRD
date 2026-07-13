"""Routes: logical clock, registrants, properties, maintenance standards, report."""
from flask import request

import calc
import serialize
import services
from store import db
from envelope import ApiError, success, list_response
from services import get_or_404, stamp_new, touch
from reqhelp import (
    authenticate, check_property_owner, get_body, need, need_enum, need_int,
    parse_pagination, ordered, page, READ_ROLES,
)
from util import parse_iso, format_iso, add_days

REG_STATUSES = ["ACTIVE", "SUSPENDED", "DEMOLISHED"]
FC_ORDER = ["NONE", "NOTICE_OF_DEFAULT", "LIS_PENDENS", "AUCTION_SCHEDULED", "REO"]
STANDARD_CATEGORIES = {"SECURING", "LANDSCAPING", "STRUCTURAL", "SANITATION", "POOL_SAFETY"}


def register(app):

    # --- logical clock ---------------------------------------------------
    @app.post("/registry/_clock/set_current_utc")
    def set_clock():
        authenticate({"ProgramAdmin"})
        body = get_body()
        need(body, "to_iso8601")
        try:
            db.clock = parse_iso(body["to_iso8601"])
        except (ValueError, TypeError):
            raise ApiError("ERR_VALIDATION", "to_iso8601 is not a valid instant")
        return success({}, 200)

    # --- registrants -----------------------------------------------------
    @app.post("/registry/registrants")
    def create_registrant():
        body = get_body()
        need(body, "legal_name", "party_type", "email", "contact_phone", "mailing_address")
        party_type = need_enum(body, "party_type", {"LENDER", "OWNER"})
        license_number = body.get("license_number")
        if party_type == "LENDER":
            if license_number is None:
                raise ApiError("ERR_LICENSE_REQUIRED",
                               "license_number required for LENDER party")
        else:
            license_number = None
        r = {
            "legal_name": body["legal_name"],
            "party_type": party_type,
            "email": body["email"],
            "contact_phone": body["contact_phone"],
            "mailing_address": body["mailing_address"],
            "license_number": license_number,
        }
        stamp_new(r)
        db.registrants[r["id"]] = r
        return success(serialize.registrant(r), 201)

    # --- properties ------------------------------------------------------
    @app.post("/registry/properties")
    def create_property():
        uid, role = authenticate({"Registrant"})
        body = get_body()
        # (4) body foreign key existence
        registrant = db.registrants.get(body.get("registrant_id"))
        if registrant is None:
            raise ApiError("ERR_REGISTRANT_NOT_FOUND", "registrant_id does not resolve")
        # (5) body well-formedness
        need(body, "parcel_id", "street_address", "occupancy_status", "registration_type")
        occupancy = need_enum(body, "occupancy_status", {"VACANT", "ABANDONED"})
        reg_type = need_enum(body, "registration_type", {"LENDER", "OWNER"})
        # (7) registration_type must match registrant.party_type
        if reg_type != registrant["party_type"]:
            raise ApiError("ERR_TYPE_MISMATCH",
                           "registration_type must equal registrant party_type")
        # (8) parcel_id unique
        if any(p["parcel_id"] == body["parcel_id"] for p in db.properties.values()):
            raise ApiError("ERR_DUPLICATE_PARCEL", "parcel_id already registered")
        fee = calc.registration_fee(reg_type, occupancy)
        prop = {
            "registrant_id": registrant["id"],
            "parcel_id": body["parcel_id"],
            "street_address": body["street_address"],
            "occupancy_status": occupancy,
            "registration_type": reg_type,
            "registration_status": "ACTIVE",
            "foreclosure_status": "NONE",
            "registration_fee_cents": fee,
            "registered_at": format_iso(db.clock),
            "registration_expires_at": services.registration_expiry(db.clock),
        }
        stamp_new(prop)
        db.properties[prop["id"]] = prop
        services.post_ledger(prop, "REGISTRATION_FEE", fee, "PROPERTY", prop["id"],
                             "Property registration fee")
        return success(serialize.property_(prop), 201)

    @app.get("/registry/properties/<pid>")
    def get_property(pid):
        authenticate(READ_ROLES)
        prop = get_or_404(db.properties, pid, "ERR_PROPERTY_NOT_FOUND")
        return success(serialize.property_(prop), 200)

    @app.get("/registry/properties")
    def list_properties():
        authenticate(READ_ROLES)
        limit, offset = parse_pagination()
        items = list(db.properties.values())
        args = request.args
        if "registrant_id" in args:
            items = [p for p in items if p["registrant_id"] == args.get("registrant_id")]
        if "registration_status" in args:
            items = [p for p in items if p["registration_status"] == args.get("registration_status")]
        if "foreclosure_status" in args:
            items = [p for p in items if p["foreclosure_status"] == args.get("foreclosure_status")]
        items = ordered(items)
        total = len(items)
        data = [serialize.property_(p) for p in page(items, limit, offset)]
        return list_response(data, total, limit, offset)

    @app.post("/registry/properties/<pid>/renew")
    def renew_property(pid):
        uid, role = authenticate({"Registrant"})
        prop = get_or_404(db.properties, pid, "ERR_PROPERTY_NOT_FOUND")
        check_property_owner(prop, uid, role)
        body = get_body()
        expected = need_int(body, "expected_property_version")
        if expected != prop["version"]:
            raise ApiError("ERR_STALE_PROPERTY_VERSION", "expected_property_version is stale")
        current = parse_iso(prop["registration_expires_at"])
        prop["registration_expires_at"] = format_iso(add_days(current, 365))
        touch(prop)
        return success(serialize.property_(prop), 200)

    @app.post("/registry/properties/<pid>/foreclosure")
    def foreclosure(pid):
        uid, role = authenticate({"Registrant", "ProgramAdmin"})
        prop = get_or_404(db.properties, pid, "ERR_PROPERTY_NOT_FOUND")
        check_property_owner(prop, uid, role)
        body = get_body()
        action = need_enum(body, "action", {"ADVANCE", "REDEEM"})
        fs = prop["foreclosure_status"]
        if action == "ADVANCE":
            if prop["registration_status"] == "DEMOLISHED":
                raise ApiError("ERR_INVALID_STATE", "demolished property cannot advance foreclosure")
            if fs == "REO":
                raise ApiError("ERR_FORECLOSURE_TERMINAL", "foreclosure already at REO")
            prop["foreclosure_status"] = FC_ORDER[FC_ORDER.index(fs) + 1]
            touch(prop)
        else:  # REDEEM
            if fs in ("NONE", "REO"):
                raise ApiError("ERR_FORECLOSURE_TERMINAL", "nothing to redeem")
            prop["foreclosure_status"] = "NONE"
            touch(prop)
            services.redeem_cascade(prop)
        return success(serialize.property_(prop), 200)

    @app.post("/registry/properties/<pid>/demolish")
    def demolish(pid):
        authenticate({"ProgramAdmin"})
        prop = get_or_404(db.properties, pid, "ERR_PROPERTY_NOT_FOUND")
        if prop["registration_status"] == "DEMOLISHED":
            raise ApiError("ERR_INVALID_STATE", "property already demolished")
        services.demolish_property(prop)
        return success(serialize.property_(prop), 200)

    @app.get("/registry/properties/<pid>/ledger")
    def property_ledger(pid):
        authenticate(READ_ROLES)
        get_or_404(db.properties, pid, "ERR_PROPERTY_NOT_FOUND")
        limit, offset = parse_pagination()
        items = ordered([e for e in db.ledger_entries.values() if e["property_id"] == pid])
        total = len(items)
        data = [serialize.ledger_entry(e) for e in page(items, limit, offset)]
        return list_response(data, total, limit, offset)

    # --- maintenance standards ------------------------------------------
    @app.post("/registry/maintenance-standards")
    def create_standard():
        authenticate({"ProgramAdmin"})
        body = get_body()
        need(body, "code", "category", "description", "severity_weight",
             "cure_period_days", "base_fine_cents")
        category = need_enum(body, "category", STANDARD_CATEGORIES)
        severity_weight = need_int(body, "severity_weight", 1, 10)
        cure_period_days = need_int(body, "cure_period_days", 1)
        base_fine_cents = need_int(body, "base_fine_cents", 0)
        s = {
            "code": body["code"],
            "category": category,
            "description": body["description"],
            "severity_weight": severity_weight,
            "cure_period_days": cure_period_days,
            "base_fine_cents": base_fine_cents,
        }
        stamp_new(s, versioned=False)
        db.maintenance_standards[s["id"]] = s
        return success(serialize.maintenance_standard(s), 201)

    @app.get("/registry/maintenance-standards")
    def list_standards():
        authenticate(READ_ROLES)
        limit, offset = parse_pagination()
        items = list(db.maintenance_standards.values())
        if "category" in request.args:
            items = [s for s in items if s["category"] == request.args.get("category")]
        items = ordered(items)
        total = len(items)
        data = [serialize.maintenance_standard(s) for s in page(items, limit, offset)]
        return list_response(data, total, limit, offset)

    # --- reporting -------------------------------------------------------
    @app.get("/registry/reports/registry-summary")
    def registry_summary():
        authenticate({"ProgramAdmin"})
        props = list(db.properties.values())
        args = request.args
        if "registration_status" in args:
            props = [p for p in props if p["registration_status"] == args.get("registration_status")]
        if "foreclosure_status" in args:
            props = [p for p in props if p["foreclosure_status"] == args.get("foreclosure_status")]
        by_reg = {s: 0 for s in REG_STATUSES}
        by_fc = {s: 0 for s in FC_ORDER}
        total_out = 0
        total_lien = 0
        demo_count = 0
        for p in props:
            by_reg[p["registration_status"]] = by_reg.get(p["registration_status"], 0) + 1
            by_fc[p["foreclosure_status"]] = by_fc.get(p["foreclosure_status"], 0) + 1
            total_out += services.outstanding_balance(p["id"])
            total_lien += services.lien_balance(p["id"])
            if any(d["property_id"] == p["id"] and d["status"] in ("LISTED", "SCHEDULED")
                   for d in db.demolition_listings.values()):
                demo_count += 1
        data = {
            "total_properties": len(props),
            "by_registration_status": by_reg,
            "by_foreclosure_status": by_fc,
            "total_outstanding_balance_cents": total_out,
            "total_lien_balance_cents": total_lien,
            "demolition_listed_count": demo_count,
        }
        return success(data, 200)
