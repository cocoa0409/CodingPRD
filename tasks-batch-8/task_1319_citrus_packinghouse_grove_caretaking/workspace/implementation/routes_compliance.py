"""Routes: quarantine orders (+ cascade), export lots, phytosanitary certificates."""
from datetime import timedelta

from flask import Blueprint, request

from core import (
    DB, D, cents, now, err, ok_object, ok_list, require_roles, body,
    req_field, as_int, as_str, as_enum, opt_int, paginate, new_entity, touch,
    get_or_404, sort_asc, STAFF_ROLES,
    ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_DUPLICATE_ENTITY,
    ERR_INVALID_STATE_TRANSITION, ERR_GROVE_QUARANTINED,
    ERR_SEGREGATION_OF_DUTIES, ERR_FRUIT_FLY_PROTOCOL_BLOCK,
    ERR_COLD_TREATMENT_INSUFFICIENT, ERR_QUARANTINE_RELEASE_REQUIREMENTS,
    ERR_CERT_EXPIRED, ERR_CHANNEL_CAPACITY_EXCEEDED, ERR_POOL_NOT_ACCEPTING,
    ERR_CHANNEL_MISMATCH, ERR_NO_JUICE_CHANNEL,
)
from domain import (
    VARIETIES, PEST_TYPES, EXPORT_MARKETS, LOT_GRADES, COLD_TREATMENT_MIN_HOURS,
    CERT_VALIDITY_DAYS, grove_posture, active_fruit_fly_covers,
    find_pool_by_variety_week, find_juice_channel, recompute_provisional,
    channel_posted_boxes, channel_reserved_boxes, ser_quarantine,
    ser_export_lot, ser_cert,
)

bp = Blueprint("compliance", __name__)
ALL_READ = STAFF_ROLES


# ---------------------------------------------------------------------------
# Quarantine orders
# ---------------------------------------------------------------------------
def _covered_groves(order):
    if order["scope_type"] == "GROVE":
        g = DB["groves"].get(order["grove_id"])
        return [g] if g is not None else []
    return [g for g in DB["groves"].values() if g["county_code"] == order["county_code"]]


def _fire_quarantine_cascade(order):
    """Activation cascade (PRD §3.8), atomic within the create request."""
    for g in _covered_groves(order):
        touch(g)  # posture recomputed (derived); affected grove version bumps
        for a in DB["assignments"].values():
            if a["grove_id"] == g["id"] and a["status"] == "SCHEDULED":
                a["status"] = "CANCELLED"
                touch(a)
        for d in DB["deliveries"].values():
            if d["grove_id"] == g["id"] and d["regulatory_status"] == "CLEAR":
                d["regulatory_status"] = "HELD"
                d["hold_cause"] = "quarantine"
                touch(d)


@bp.post("/packinghouse/quarantine-orders")
def create_quarantine():
    uid, _role = require_roles(["ComplianceOfficer"])
    b = body()
    scope = as_enum(req_field(b, "scope_type"), "scope_type", {"GROVE", "COUNTY_ZONE"})
    pest = as_enum(req_field(b, "pest_type"), "pest_type", PEST_TYPES)
    grove_id = b.get("grove_id")
    county_code = b.get("county_code")
    if scope == "GROVE":
        if grove_id is None:
            err(ERR_INVALID_REQUEST, 400, "grove_id is required for GROVE scope")
        if county_code is not None:
            err(ERR_INVALID_REQUEST, 400, "county_code must be null for GROVE scope")
        grove_id = as_str(grove_id, "grove_id")
        if grove_id not in DB["groves"]:
            err(ERR_NOT_FOUND, 404, f"Grove not found: {grove_id}")
    else:
        if county_code is None:
            err(ERR_INVALID_REQUEST, 400, "county_code is required for COUNTY_ZONE scope")
        if grove_id is not None:
            err(ERR_INVALID_REQUEST, 400, "grove_id must be null for COUNTY_ZONE scope")
        county_code = as_str(county_code, "county_code")
    o = new_entity()
    o.update(
        scope_type=scope,
        grove_id=grove_id if scope == "GROVE" else None,
        county_code=county_code if scope == "COUNTY_ZONE" else None,
        pest_type=pest,
        status="ACTIVE",
        issued_at=now(),
        issued_by=uid,
        released_at=None,
        released_by=None,
    )
    DB["quarantines"][o["id"]] = o
    _fire_quarantine_cascade(o)
    return ok_object(ser_quarantine(o), 201)


@bp.get("/packinghouse/quarantine-orders")
def list_quarantines():
    require_roles(ALL_READ)
    items = sort_asc(DB["quarantines"].values())
    for f in ("grove_id", "county_code", "status", "pest_type"):
        v = request.args.get(f)
        if v is not None:
            items = [o for o in items if o[f] == v]
    page, pag = paginate(items)
    return ok_list([ser_quarantine(o) for o in page], pag)


@bp.get("/packinghouse/quarantine-orders/<rid>")
def get_quarantine(rid):
    require_roles(ALL_READ)
    o = get_or_404("quarantines", rid, "QuarantineOrder")
    return ok_object(ser_quarantine(o))


@bp.post("/packinghouse/quarantine-orders/<rid>/release")
def release_quarantine(rid):
    uid, _role = require_roles(["ComplianceOfficer"])
    o = get_or_404("quarantines", rid, "QuarantineOrder")
    if o["status"] != "ACTIVE":
        err(ERR_INVALID_STATE_TRANSITION, 409, "Quarantine order is not ACTIVE")
    b = body()
    if b.get("inspection_passed") is not True:
        err(
            ERR_QUARANTINE_RELEASE_REQUIREMENTS,
            422,
            "Release requires inspection_passed == true",
        )
    if uid == o["issued_by"]:
        err(ERR_SEGREGATION_OF_DUTIES, 403, "Releasing officer must differ from issuer")
    o["status"] = "RELEASED"
    o["released_at"] = now()
    o["released_by"] = uid
    touch(o)
    # recompute posture of every affected grove; release cascade-held deliveries
    for g in _covered_groves(o):
        touch(g)
        if grove_posture(g) == "CLEAR":
            for d in DB["deliveries"].values():
                if (
                    d["grove_id"] == g["id"]
                    and d["regulatory_status"] == "HELD"
                    and d.get("hold_cause") == "quarantine"
                ):
                    d["regulatory_status"] = "RELEASED"
                    d["hold_cause"] = None
                    touch(d)
    return ok_object(ser_quarantine(o))


# ---------------------------------------------------------------------------
# Export lots
# ---------------------------------------------------------------------------
@bp.post("/packinghouse/export-lots")
def create_export_lot():
    require_roles(["ComplianceOfficer"])
    b = body()
    dest = as_enum(req_field(b, "destination_market"), "destination_market", EXPORT_MARKETS)
    variety = as_enum(req_field(b, "variety"), "variety", VARIETIES)
    grade = as_enum(req_field(b, "grade"), "grade", LOT_GRADES)
    boxes = as_int(req_field(b, "boxes"), "boxes")
    if boxes <= 0:
        err(ERR_INVALID_REQUEST, 400, "boxes must be > 0")
    source_channel_id = as_str(req_field(b, "source_channel_id"), "source_channel_id")
    channel = DB["channels"].get(source_channel_id)
    if channel is None:
        err(ERR_NOT_FOUND, 404, f"AllocationChannel not found: {source_channel_id}")
    source_grove_id = as_str(req_field(b, "source_grove_id"), "source_grove_id")
    grove = DB["groves"].get(source_grove_id)
    if grove is None:
        err(ERR_NOT_FOUND, 404, f"Grove not found: {source_grove_id}")
    cold = opt_int(b, "cold_treatment_hours", 0)
    if cold < 0:
        err(ERR_INVALID_REQUEST, 400, "cold_treatment_hours must be >= 0")
    # tier 7: source grove posture
    if grove_posture(grove) == "QUARANTINED":
        err(ERR_GROVE_QUARANTINED, 422, "Source grove is quarantined")
    # channel coherence (type/variety/market + resolvable pool week) is checked
    # before the posted-allocation capacity gate so a mismatched channel never
    # reports phantom capacity errors
    if (
        channel["channel_type"] != "EXPORT"
        or channel["variety"] != variety
        or channel["destination_market"] != dest
    ):
        err(ERR_CHANNEL_MISMATCH, 422, "Channel type/variety/market does not match the lot")
    pool = find_pool_by_variety_week(channel["variety"], channel["week_start"])
    if pool is None:
        err(ERR_CHANNEL_MISMATCH, 422, "No pool matches the channel's variety + week")
    # capacity: posted-allocation boxes of this grade not already reserved
    posted = channel_posted_boxes(source_channel_id, grade)
    reserved = channel_reserved_boxes(source_channel_id, grade)
    if boxes > posted - reserved:
        err(
            ERR_CHANNEL_CAPACITY_EXCEEDED,
            422,
            "Lot boxes exceed the channel's unreserved posted allocation",
        )
    lot = new_entity()
    lot.update(
        destination_market=dest,
        variety=variety,
        grade=grade,
        boxes=boxes,
        source_channel_id=source_channel_id,
        source_grove_id=source_grove_id,
        cold_treatment_hours=cold,
        pool_id=pool["id"],
        inspection_requested_by=None,
        phyto_certificate_id=None,
        diverted_to=None,
        status="BUILDING",
    )
    DB["export_lots"][lot["id"]] = lot
    return ok_object(ser_export_lot(lot), 201)


@bp.get("/packinghouse/export-lots")
def list_export_lots():
    require_roles(ALL_READ)
    items = sort_asc(DB["export_lots"].values())
    for f in (
        "destination_market",
        "status",
        "variety",
        "source_grove_id",
        "source_channel_id",
        "pool_id",
        "phyto_certificate_id",
    ):
        v = request.args.get(f)
        if v is not None:
            items = [l for l in items if l[f] == v]
    page, pag = paginate(items)
    return ok_list([ser_export_lot(l) for l in page], pag)


@bp.get("/packinghouse/export-lots/<rid>")
def get_export_lot(rid):
    require_roles(ALL_READ)
    lot = get_or_404("export_lots", rid, "ExportLot")
    return ok_object(ser_export_lot(lot))


@bp.post("/packinghouse/export-lots/<rid>/request-inspection")
def request_inspection(rid):
    uid, _role = require_roles(["ComplianceOfficer"])
    lot = get_or_404("export_lots", rid, "ExportLot")
    if lot["status"] != "BUILDING":
        err(ERR_INVALID_STATE_TRANSITION, 409, "Lot is not BUILDING")
    grove = DB["groves"][lot["source_grove_id"]]
    # tier 7 (export protocol): cold treatment; then fruit-fly BEFORE generic posture
    if lot["destination_market"] == "JAPAN" and lot["cold_treatment_hours"] < COLD_TREATMENT_MIN_HOURS:
        err(ERR_COLD_TREATMENT_INSUFFICIENT, 422, "JAPAN lots require >= 24 cold-treatment hours")
    if lot["destination_market"] == "JAPAN" and active_fruit_fly_covers(grove):
        err(ERR_FRUIT_FLY_PROTOCOL_BLOCK, 422, "ACTIVE FRUIT_FLY quarantine covers the source grove/county")
    if grove_posture(grove) == "QUARANTINED":
        err(ERR_GROVE_QUARANTINED, 422, "Source grove is quarantined")
    lot["inspection_requested_by"] = uid
    lot["status"] = "INSPECTION_READY"
    touch(lot)
    return ok_object(ser_export_lot(lot))


@bp.post("/packinghouse/export-lots/<rid>/rework")
def rework_lot(rid):
    require_roles(["ComplianceOfficer"])
    lot = get_or_404("export_lots", rid, "ExportLot")
    if lot["status"] != "REJECTED":
        err(ERR_INVALID_STATE_TRANSITION, 409, "Lot is not REJECTED")
    b = body()
    cold = opt_int(b, "cold_treatment_hours", None)
    if cold is not None:
        if cold < 0:
            err(ERR_INVALID_REQUEST, 400, "cold_treatment_hours must be >= 0")
        lot["cold_treatment_hours"] = cold
    lot["inspection_requested_by"] = None
    lot["status"] = "BUILDING"
    touch(lot)
    return ok_object(ser_export_lot(lot))


@bp.post("/packinghouse/export-lots/<rid>/divert")
def divert_lot(rid):
    require_roles(["ComplianceOfficer"])
    lot = get_or_404("export_lots", rid, "ExportLot")
    if lot["status"] not in {"BUILDING", "INSPECTION_READY", "CERTIFIED"}:
        err(ERR_INVALID_STATE_TRANSITION, 409, "Lot cannot be diverted from its current state")
    pool = DB["pools"].get(lot["pool_id"])
    if pool is None or pool["status"] not in {"OPEN", "INTAKE_CLOSED"}:
        err(ERR_POOL_NOT_ACCEPTING, 409, "Lot's pool is not OPEN or INTAKE_CLOSED")
    juice_channel = find_juice_channel(lot["variety"], pool["week_start"])
    if juice_channel is None:
        err(ERR_NO_JUICE_CHANNEL, 422, "No JUICE channel for the lot's variety + week")
    # export_diversion_credit: proceeds adjusted by boxes * (juice price - export price)
    source_channel = DB["channels"][lot["source_channel_id"]]
    delta = lot["boxes"] * (
        juice_channel["price_cents_per_box"] - source_channel["price_cents_per_box"]
    )
    pool["posted_proceeds_cents"] += delta
    recompute_provisional(pool)  # posted_ge_boxes unchanged: ge measures fruit, not destination
    touch(pool)
    if lot["status"] == "CERTIFIED" and lot["phyto_certificate_id"]:
        cert = DB["certs"].get(lot["phyto_certificate_id"])
        if cert is not None and cert["status"] == "ISSUED":
            cert["status"] = "REVOKED"
            touch(cert)
    lot["diverted_to"] = "JUICE"
    lot["status"] = "DIVERTED"
    touch(lot)
    return ok_object(ser_export_lot(lot))


@bp.post("/packinghouse/export-lots/<rid>/ship")
def ship_lot(rid):
    require_roles(["ComplianceOfficer"])
    lot = get_or_404("export_lots", rid, "ExportLot")
    if lot["status"] != "CERTIFIED":
        err(ERR_INVALID_STATE_TRANSITION, 409, "Lot is not CERTIFIED")
    cert = DB["certs"].get(lot["phyto_certificate_id"])
    if cert is None or cert["status"] != "ISSUED":
        err(ERR_INVALID_STATE_TRANSITION, 409, "Lot's certificate is not ISSUED")
    if now() >= cert["expires_at"]:
        err(ERR_CERT_EXPIRED, 422, "Certificate has expired")
    lot["status"] = "SHIPPED"
    touch(lot)
    cert["status"] = "CONSUMED"
    touch(cert)
    return ok_object(ser_export_lot(lot))


# ---------------------------------------------------------------------------
# Phytosanitary certificates
# ---------------------------------------------------------------------------
@bp.post("/packinghouse/export-lots/<lot_id>/phytosanitary-certificates")
def create_cert(lot_id):
    uid, _role = require_roles(["ComplianceOfficer"])
    lot = get_or_404("export_lots", lot_id, "ExportLot")  # left-to-right path validation
    b = body()
    number = as_str(req_field(b, "certificate_number"), "certificate_number")
    result = as_enum(req_field(b, "inspection_result"), "inspection_result", {"PASS", "FAIL"})
    if lot["status"] != "INSPECTION_READY":
        err(ERR_INVALID_STATE_TRANSITION, 409, "Lot is not INSPECTION_READY")
    if uid == lot["inspection_requested_by"]:
        err(
            ERR_SEGREGATION_OF_DUTIES,
            403,
            "Certificate issuer must differ from the inspection requester",
        )
    if result == "PASS":
        grove = DB["groves"][lot["source_grove_id"]]
        if grove_posture(grove) == "QUARANTINED":
            err(ERR_GROVE_QUARANTINED, 422, "Source grove is quarantined")
    for c in DB["certs"].values():
        if c["certificate_number"] == number:
            err(ERR_DUPLICATE_ENTITY, 409, f"certificate_number already exists: {number}")
    issued_at = now()
    c = new_entity()
    c.update(
        export_lot_id=lot_id,
        certificate_number=number,
        inspection_result=result,
        issued_at=issued_at,
        issued_by=uid,
        expires_at=issued_at + timedelta(days=CERT_VALIDITY_DAYS),
        status="ISSUED" if result == "PASS" else "REVOKED",
    )
    DB["certs"][c["id"]] = c
    if result == "PASS":
        lot["status"] = "CERTIFIED"
        lot["phyto_certificate_id"] = c["id"]
    else:
        lot["status"] = "REJECTED"
    touch(lot)
    return ok_object(ser_cert(c), 201)


@bp.get("/packinghouse/export-lots/<lot_id>/phytosanitary-certificates")
def list_certs(lot_id):
    require_roles(ALL_READ)
    get_or_404("export_lots", lot_id, "ExportLot")
    items = [c for c in DB["certs"].values() if c["export_lot_id"] == lot_id]
    items = sort_asc(items)
    page, pag = paginate(items)
    return ok_list([ser_cert(c) for c in page], pag)


@bp.get("/packinghouse/phytosanitary-certificates/<rid>")
def get_cert(rid):
    require_roles(ALL_READ)
    c = get_or_404("certs", rid, "PhytosanitaryCertificate")
    return ok_object(ser_cert(c))


@bp.post("/packinghouse/phytosanitary-certificates/<rid>/revoke")
def revoke_cert(rid):
    require_roles(["ComplianceOfficer"])
    c = get_or_404("certs", rid, "PhytosanitaryCertificate")
    if c["status"] != "ISSUED":
        err(ERR_INVALID_STATE_TRANSITION, 409, "Certificate is not ISSUED")
    lot = DB["export_lots"].get(c["export_lot_id"])
    if lot is not None and lot["status"] == "SHIPPED":
        err(ERR_INVALID_STATE_TRANSITION, 409, "Cannot revoke a shipped lot's certificate")
    c["status"] = "REVOKED"
    touch(c)
    if lot is not None and lot["status"] == "CERTIFIED":
        lot["status"] = "INSPECTION_READY"
        lot["phyto_certificate_id"] = None
        touch(lot)
    return ok_object(ser_cert(c))
