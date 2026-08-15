"""Equipment sales pipeline and technicians (PRD sections 3.1 and 3.5)."""

from flask import Blueprint, request

import envelope
from auth import auth_and_roles, pm_owns_or_403
from calc import check_install_conflicts
from db import STORES, now
from errors import ApiError
from util import (
    add_months,
    base_record,
    body,
    fk_exists,
    fmt_ts,
    get_or_404,
    paginate,
    pub,
    sorted_default,
    touch,
    v_dt,
    v_enum,
    v_int,
    v_list,
    v_str,
)

bp = Blueprint("equipment", __name__)

SALE_READ_ROLES = [
    "DistributionAdmin",
    "SalesRep",
    "PracticeManager",
    "ServiceDispatcher",
    "FieldTechnician",
]
TECH_READ_ROLES = ["DistributionAdmin", "SalesRep", "ServiceDispatcher", "FieldTechnician"]
CERTIFICATIONS = {"INSTALL", "REPAIR", "STERILIZATION"}


# ---------------------------------------------------------------------------
# Equipment sales
# ---------------------------------------------------------------------------


@bp.post("/equipment-sales")
def create_equipment_sale():
    auth_and_roles(["SalesRep"])
    data = body()
    fk_exists(data, "practice_id", "practices")
    fk_exists(data, "product_id", "products")

    practice_id = v_str(data, "practice_id")
    product_id = v_str(data, "product_id")
    sale_price = v_int(data, "sale_price_cents", min_val=1)

    practice = STORES["practices"][practice_id]
    product = STORES["products"][product_id]
    if product["kind"] != "EQUIPMENT":
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "product_id must reference an EQUIPMENT product"
        )
    if practice["status"] != "ACTIVE":
        raise ApiError(
            "ERR_PRACTICE_SUSPENDED",
            409,
            "SUSPENDED practices may not open equipment-sale quotes",
        )

    record = base_record()
    record.update(
        {
            "practice_id": practice_id,
            "product_id": product_id,
            "sale_price_cents": sale_price,
            "status": "QUOTE",
            "installer_technician_id": None,
            "install_window_start": None,
            "install_window_end": None,
            "install_rework_count": 0,
            "training_minutes": None,
            "trade_in_id": None,
            "trade_in_credit_cents": None,
            "warranty_agreement_id": None,
            "_win_start": None,
            "_win_end": None,
        }
    )
    STORES["equipment_sales"][record["id"]] = record
    return envelope.success(pub(record), "object", 201)


@bp.get("/equipment-sales/<rid>")
def get_equipment_sale(rid):
    uid, role = auth_and_roles(SALE_READ_ROLES)
    sale = get_or_404("equipment_sales", rid)
    pm_owns_or_403(role, uid, sale["practice_id"])
    return envelope.success(pub(sale))


@bp.get("/equipment-sales")
def list_equipment_sales():
    uid, role = auth_and_roles(SALE_READ_ROLES)
    records = list(STORES["equipment_sales"].values())
    if role == "PracticeManager":
        records = [r for r in records if r["practice_id"] == uid]
    for field in (
        "practice_id",
        "product_id",
        "installer_technician_id",
        "trade_in_id",
        "warranty_agreement_id",
    ):
        value = request.args.get(field)
        if value is not None:
            records = [r for r in records if r.get(field) == value]
    records = sorted_default(records)
    page, pagination = paginate(records)
    return envelope.success([pub(r) for r in page], "array", 200, pagination)


@bp.post("/equipment-sales/<rid>/confirm")
def confirm_equipment_sale(rid):
    auth_and_roles(["SalesRep"])
    sale = get_or_404("equipment_sales", rid)
    if sale["status"] != "QUOTE":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a QUOTE sale can be confirmed")
    practice = STORES["practices"][sale["practice_id"]]
    if practice["status"] != "ACTIVE":
        raise ApiError("ERR_PRACTICE_SUSPENDED", 409, "Practice is SUSPENDED")
    sale["status"] = "CONFIRMED"
    touch(sale)
    return envelope.success(pub(sale))


@bp.post("/equipment-sales/<rid>/schedule-install")
def schedule_install(rid):
    auth_and_roles(["SalesRep"])
    sale = get_or_404("equipment_sales", rid)
    fk_exists(body(), "technician_id", "technicians")
    data = body()

    technician_id = v_str(data, "technician_id")
    _, window_start = v_dt(data, "window_start")
    _, window_end = v_dt(data, "window_end")
    if not window_end > window_start:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "window_end must be strictly after window_start"
        )

    if sale["status"] not in ("CONFIRMED", "INSTALLED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Install can be scheduled only from CONFIRMED or INSTALLED",
        )

    technician = STORES["technicians"][technician_id]
    if technician["status"] != "ACTIVE" or "INSTALL" not in technician["certifications"]:
        raise ApiError(
            "ERR_CERTIFICATION_MISSING",
            422,
            "Technician must be ACTIVE and hold the INSTALL certification",
        )

    check_install_conflicts(sale, technician, window_start, window_end)

    rework = sale["status"] == "INSTALLED"
    sale["installer_technician_id"] = technician_id
    sale["install_window_start"] = data["window_start"]
    sale["install_window_end"] = data["window_end"]
    sale["_win_start"] = window_start
    sale["_win_end"] = window_end
    if rework:
        sale["install_rework_count"] += 1
    sale["status"] = "INSTALL_SCHEDULED"
    touch(sale)
    return envelope.success(pub(sale))


def _assigned_technician_or_403(sale, uid):
    installer = sale["installer_technician_id"]
    if installer is not None and installer != uid:
        raise ApiError(
            "ERR_FORBIDDEN", 403, "Only the assigned technician may perform this step"
        )


@bp.post("/equipment-sales/<rid>/complete-install")
def complete_install(rid):
    uid, role = auth_and_roles(["FieldTechnician"])
    sale = get_or_404("equipment_sales", rid)
    _assigned_technician_or_403(sale, uid)
    if sale["status"] != "INSTALL_SCHEDULED":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Only an INSTALL_SCHEDULED sale can be completed"
        )
    sale["status"] = "INSTALLED"
    touch(sale)
    return envelope.success(pub(sale))


@bp.post("/equipment-sales/<rid>/complete-training")
def complete_training(rid):
    uid, role = auth_and_roles(["FieldTechnician"])
    sale = get_or_404("equipment_sales", rid)
    _assigned_technician_or_403(sale, uid)
    data = body()
    training_minutes = v_int(data, "training_minutes", min_val=1)
    if sale["status"] != "INSTALLED":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Only an INSTALLED sale can receive training"
        )
    sale["training_minutes"] = training_minutes
    sale["status"] = "TRAINED"
    touch(sale)
    return envelope.success(pub(sale))


@bp.post("/equipment-sales/<rid>/accept")
def accept_equipment_sale(rid):
    uid, role = auth_and_roles(["PracticeManager"])
    sale = get_or_404("equipment_sales", rid)
    pm_owns_or_403(role, uid, sale["practice_id"])
    if sale["status"] != "TRAINED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a TRAINED sale can be accepted")

    # Acceptance spawns the manufacturer warranty.
    t = now()
    product = STORES["products"][sale["product_id"]]
    warranty_months = product["warranty_months"]
    end_dt = add_months(t, warranty_months)
    agreement = base_record()
    agreement.update(
        {
            "practice_id": sale["practice_id"],
            "equipment_sale_id": sale["id"],
            "coverage_type": "WARRANTY",
            "start_date": fmt_ts(t),
            "end_date": fmt_ts(end_dt),
            "deductible_cents": 0,
            "coverage_cap_cents": None,
            "used_cents": 0,
            "status": "ACTIVE",
            "_start_dt": t,
            "_end_dt": end_dt,
        }
    )
    STORES["coverage_agreements"][agreement["id"]] = agreement

    sale["status"] = "ACCEPTED"
    sale["warranty_agreement_id"] = agreement["id"]
    touch(sale)
    return envelope.success(pub(sale))


# ---------------------------------------------------------------------------
# Technicians
# ---------------------------------------------------------------------------


@bp.post("/technicians")
def create_technician():
    auth_and_roles(["DistributionAdmin"])
    data = body()
    name = v_str(data, "name")
    region = v_str(data, "region")
    certifications = v_list(data, "certifications")
    for cert in certifications:
        if cert not in CERTIFICATIONS:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                400,
                "certifications members must be INSTALL, REPAIR, or STERILIZATION",
            )
    status = v_enum(data, "status", {"ACTIVE", "INACTIVE"}, required=False, default="ACTIVE")

    record = base_record()
    record.update(
        {
            "name": name,
            "region": region,
            "certifications": list(certifications),
            "status": status,
            "van_stock": [],
        }
    )
    STORES["technicians"][record["id"]] = record
    return envelope.success(pub(record), "object", 201)


@bp.get("/technicians/<rid>")
def get_technician(rid):
    auth_and_roles(TECH_READ_ROLES)
    return envelope.success(pub(get_or_404("technicians", rid)))


@bp.put("/technicians/<rid>/van-stock")
def upsert_van_stock(rid):
    auth_and_roles(["DistributionAdmin"])
    technician = get_or_404("technicians", rid)
    data = body()
    fk_exists(data, "product_id", "products")
    product_id = v_str(data, "product_id")
    quantity_on_van = v_int(data, "quantity_on_van", min_val=0)
    min_quantity = v_int(data, "min_quantity", min_val=0)

    for entry in technician["van_stock"]:
        if entry["product_id"] == product_id:
            entry["quantity_on_van"] = quantity_on_van
            entry["min_quantity"] = min_quantity
            break
    else:
        technician["van_stock"].append(
            {
                "product_id": product_id,
                "quantity_on_van": quantity_on_van,
                "min_quantity": min_quantity,
            }
        )
    touch(technician)
    return envelope.success(pub(technician))
