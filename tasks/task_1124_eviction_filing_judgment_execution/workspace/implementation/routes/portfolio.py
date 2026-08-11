from flask import Blueprint

import db
from db import LOCK, STORE
from errors import ApiError
from middleware import auth, require_owner
from response import ok_list, ok_object
from services import serialize as ser
from services.resolution import get_landlord, get_unit, get_tenancy
from utils import body_json, pagination, v_date, v_enum, v_int, v_str

bp = Blueprint("portfolio", __name__)


@bp.post("/api/landlords")
@auth({"PlatformAdmin"})
def create_landlord(_uid, _role):
    with LOCK:
        b = body_json()
        legal_name = v_str(b, "legal_name")
        contact_email = v_str(b, "contact_email")
        r = db.new_record({"legal_name": legal_name, "contact_email": contact_email})
        STORE.landlords[r["id"]] = r
        return ok_object(ser.landlord(r), 201)


@bp.get("/api/landlords/<lid>")
@auth({"PlatformAdmin", "Landlord", "CourtClerk"})
def read_landlord(lid, _uid, _role):
    with LOCK:
        return ok_object(ser.landlord(get_landlord(lid)))


@bp.get("/api/landlords")
@auth({"PlatformAdmin", "CourtClerk"})
def list_landlords(_uid, _role):
    with LOCK:
        limit, offset = pagination()
        items = db.sorted_items(STORE.landlords)
        page = items[offset : offset + limit]
        return ok_list([ser.landlord(r) for r in page], len(items), limit, offset)


@bp.post("/api/units")
@auth({"Landlord"})
def create_unit(_uid, _role):
    with LOCK:
        b = body_json()
        landlord_id = v_str(b, "landlord_id")
        jurisdiction = v_enum(b, "jurisdiction_code", {"CA", "TX", "OH"})
        street_address = v_str(b, "street_address")
        unit_label = v_str(b, "unit_label")
        get_landlord(landlord_id)  # body-referenced existence
        require_owner(_uid, landlord_id)
        r = db.new_record(
            {
                "landlord_id": landlord_id,
                "jurisdiction_code": jurisdiction,
                "street_address": street_address,
                "unit_label": unit_label,
                "status": "VACANT",
            }
        )
        STORE.units[r["id"]] = r
        return ok_object(ser.unit(r), 201)


@bp.get("/api/units/<uid>")
@auth({"Landlord", "CourtClerk", "SheriffDeputy", "PlatformAdmin"})
def read_unit(uid, _uid, _role):
    with LOCK:
        return ok_object(ser.unit(get_unit(uid)))


@bp.get("/api/landlords/<lid>/units")
@auth({"Landlord", "CourtClerk", "PlatformAdmin"})
def list_landlord_units(lid, _uid, _role):
    with LOCK:
        get_landlord(lid)
        limit, offset = pagination()
        items = [u for u in db.sorted_items(STORE.units) if u["landlord_id"] == lid]
        page = items[offset : offset + limit]
        return ok_list([ser.unit(r) for r in page], len(items), limit, offset)


@bp.post("/api/tenancies")
@auth({"Landlord"})
def create_tenancy(_uid, _role):
    with LOCK:
        b = body_json()
        unit_id = v_str(b, "unit_id")
        tenant_full_name = v_str(b, "tenant_full_name")
        monthly_rent_cents = v_int(b, "monthly_rent_cents", min_exclusive=0)
        lease_start_date = v_date(b, "lease_start_date")
        lease_end_date = v_date(b, "lease_end_date", required=False)
        unit = get_unit(unit_id)
        require_owner(_uid, unit["landlord_id"])
        for t in STORE.tenancies.values():
            if t["unit_id"] == unit_id and t["status"] == "ACTIVE":
                raise ApiError(
                    "ERR_UNIT_OCCUPIED", 409, "Unit already has an ACTIVE tenancy"
                )
        r = db.new_record(
            {
                "unit_id": unit_id,
                "tenant_full_name": tenant_full_name,
                "monthly_rent_cents": monthly_rent_cents,
                "lease_start_date": lease_start_date.isoformat(),
                "lease_end_date": lease_end_date.isoformat() if lease_end_date else None,
                "status": "ACTIVE",
                "ended_at": None,
            }
        )
        STORE.tenancies[r["id"]] = r
        unit["status"] = "OCCUPIED"
        db.bump(unit)
        return ok_object(ser.tenancy(r), 201)


@bp.get("/api/tenancies/<tid>")
@auth({"Landlord", "CourtClerk", "SheriffDeputy", "PlatformAdmin"})
def read_tenancy(tid, _uid, _role):
    with LOCK:
        return ok_object(ser.tenancy(get_tenancy(tid)))


@bp.get("/api/units/<uid>/tenancies")
@auth({"Landlord", "CourtClerk", "PlatformAdmin"})
def list_unit_tenancies(uid, _uid, _role):
    with LOCK:
        get_unit(uid)
        limit, offset = pagination()
        items = [t for t in db.sorted_items(STORE.tenancies) if t["unit_id"] == uid]
        page = items[offset : offset + limit]
        return ok_list([ser.tenancy(r) for r in page], len(items), limit, offset)
