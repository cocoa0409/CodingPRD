from decimal import Decimal

from flask import Blueprint

from db import DB, stamp_new, touch
from errors import (
    ERR_CERTIFICATION_NOT_APPLICABLE,
    ERR_SET_PRESSURE_OUT_OF_TOLERANCE,
    ERR_SOD_VIOLATION,
    invalid_state,
    not_found,
    raise_err,
    validation,
)
from middleware import (
    as_enum,
    as_number,
    as_string,
    authenticate,
    get_json_body,
    require_customer_ownership,
    require_roles,
)
from response import success_list, success_object
from routes.repair_orders import get_ro_or_404

bp = Blueprint("certifications", __name__)

SEAT_LEAKAGE_CLASSES = ["CLASS_IV", "CLASS_V", "CLASS_VI"]


@bp.route("/repair-orders/<rid>/certifications", methods=["POST"])
def create_certification(rid):
    caller = authenticate()
    body = get_json_body()
    require_roles(caller, ["Certifier"])
    ro = get_ro_or_404(rid)
    set_pressure_psig = as_number(body, "set_pressure_psig")
    seat_leakage_class = as_enum(body, "seat_leakage_class", SEAT_LEAKAGE_CLASSES)

    # Permanent applicability gate first within state-validity tier.
    if not ro.get("requires_certification"):
        raise_err(
            ERR_CERTIFICATION_NOT_APPLICABLE,
            "Repair order's asset is not a SAFETY_RELIEF_VALVE",
        )
    if ro["status"] != "READY_FOR_CERT":
        invalid_state("Repair order is not in READY_FOR_CERT")

    # Business-safety tier: SoD then set-pressure tolerance.
    if caller.user_id is not None and caller.user_id == ro.get("assembled_by_id"):
        raise_err(ERR_SOD_VIOLATION, "Certifier may not be the technician who assembled the valve")
    asset = DB.assets.get(ro["asset_id"])
    nameplate = Decimal(str(asset["set_pressure_psig"])) if asset else None
    if nameplate is None or nameplate == 0:
        raise_err(ERR_SET_PRESSURE_OUT_OF_TOLERANCE, "Asset nameplate set pressure unavailable")
    deviation = abs(Decimal(str(set_pressure_psig)) - nameplate) / nameplate
    if deviation > Decimal("0.03"):
        raise_err(
            ERR_SET_PRESSURE_OUT_OF_TOLERANCE,
            "Set pressure deviates more than 3% from nameplate",
        )

    DB.cert_tag_seq += 1
    tag_number = f"SVT-{DB.cert_tag_seq:06d}"

    cert = stamp_new(
        {
            "repair_order_id": ro["id"],
            "tag_number": tag_number,
            "set_pressure_psig": set_pressure_psig,
            "seat_leakage_class": seat_leakage_class,
            "certified_by_id": caller.user_id,
            "cert_status": "ISSUED",
            "void_reason": None,
        }
    )
    DB.certifications[cert["id"]] = cert

    ro["status"] = "COMPLETE"
    touch(ro)
    return success_object(cert, status=201)


@bp.route("/repair-orders/<rid>/certifications", methods=["GET"])
def list_certifications(rid):
    caller = authenticate()
    ro = get_ro_or_404(rid)
    require_customer_ownership(caller, ro["customer_id"])
    items = sorted(
        (c for c in DB.certifications.values() if c["repair_order_id"] == ro["id"]),
        key=lambda c: (c["created_at"], c["id"]),
    )
    return success_list(items, limit=len(items) if items else 10, offset=0, total_count=len(items))


@bp.route("/certifications/<cid>/void", methods=["POST"])
def void_certification(cid):
    caller = authenticate()
    body = get_json_body()
    require_roles(caller, ["ServiceManager"])
    cert = DB.certifications.get(cid)
    if cert is None:
        not_found("Certification not found")
    void_reason = as_string(body, "void_reason")
    if cert["cert_status"] != "ISSUED":
        invalid_state("Certification is not ISSUED")
    cert["cert_status"] = "VOIDED"
    cert["void_reason"] = void_reason
    touch(cert)
    # Compensation revert: RO COMPLETE -> READY_FOR_CERT.
    ro = DB.repair_orders.get(cert["repair_order_id"])
    if ro is not None and ro["status"] == "COMPLETE":
        ro["status"] = "READY_FOR_CERT"
        touch(ro)
    return success_object(cert)
