"""Approved sources, material certifications, special-process approvals."""

from flask import Blueprint, request

from db import db, base_record, public, touch
from errors import (
    ApiError,
    ERR_APPROVAL_WINDOW_OVERLAP,
    ERR_CERT_ALREADY_REVOKED,
    ERR_CERT_NOT_ACCEPTABLE,
    ERR_COUNTERFEIT_RISK_TOO_HIGH,
    ERR_INVALID_STATE,
    ERR_INVALID_WINDOW,
    ERR_MATERIAL_CERT_NOT_FOUND,
    ERR_PROCESS_APPROVAL_NOT_FOUND,
    ERR_SOD_VIOLATION,
    ERR_SOURCE_NOT_APPROVABLE,
    ERR_SOURCE_NOT_APPROVED,
    ERR_SOURCE_NOT_FOUND,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from services import create_escape_report, create_ncr, recompute_wo_counters
from validate import (
    json_body,
    no_unknown,
    paginate,
    req_date,
    req_enum,
    req_int,
    req_str,
)

bp = Blueprint("sourcing", __name__)

SCM = "SupplyChainManager"
QI = "QualityInspector"
QM = "QualityManager"

SCOPES = {"RAW_MATERIAL", "SPECIAL_PROCESS", "DISTRIBUTOR"}
RISK_RATINGS = {"LOW", "MEDIUM", "HIGH"}
PROCESS_CODES = {"HEAT_TREAT", "NDT", "PLATING", "WELDING", "SHOT_PEEN"}


def get_source(source_id):
    s = db.sources.get(source_id)
    if s is None:
        raise ApiError(ERR_SOURCE_NOT_FOUND, 404, "Source %s not found" % source_id)
    return s


def get_cert(cert_id):
    c = db.material_certs.get(cert_id)
    if c is None:
        raise ApiError(ERR_MATERIAL_CERT_NOT_FOUND, 404, "Material cert %s not found" % cert_id)
    return c


def get_pa(pa_id):
    pa = db.process_approvals.get(pa_id)
    if pa is None:
        raise ApiError(ERR_PROCESS_APPROVAL_NOT_FOUND, 404, "Process approval %s not found" % pa_id)
    return pa


# ---------------------------------------------------------------------------
# ApprovedSource
# ---------------------------------------------------------------------------
@bp.route("/api/sources", methods=["POST"])
def create_source():
    require_roles(SCM)
    data = json_body()
    no_unknown(data, {"supplier_code", "approval_scope", "counterfeit_risk_rating"})
    supplier_code = req_str(data, "supplier_code")
    scope = req_enum(data, "approval_scope", SCOPES)
    rating = req_enum(data, "counterfeit_risk_rating", RISK_RATINGS)

    rec = base_record(db.new_id())
    rec.update(
        {
            "supplier_code": supplier_code,
            "approval_scope": scope,
            "counterfeit_risk_rating": rating,
            "status": "PROVISIONAL",
        }
    )
    db.sources[rec["id"]] = rec
    return success_object(public(rec), 201)


@bp.route("/api/sources", methods=["GET"])
def list_sources():
    require_roles(*ALL_ROLES)
    items = list(db.sources.values())
    status = request.args.get("status")
    scope = request.args.get("approval_scope")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    if scope is not None:
        items = [s for s in items if s["approval_scope"] == scope]
    items.sort(key=lambda r: (r["_created_dt"], r["_seq"]))
    page, pagination = paginate(items, request.args)
    return success_list(page, pagination)


@bp.route("/api/sources/<sourceId>", methods=["GET"])
def get_one_source(sourceId):
    require_roles(*ALL_ROLES)
    return success_object(public(get_source(sourceId)))


@bp.route("/api/sources/<sourceId>/approve", methods=["POST"])
def approve_source(sourceId):
    require_roles(SCM)
    data = json_body()
    no_unknown(data, set())
    src = get_source(sourceId)
    if src["status"] != "PROVISIONAL":
        raise ApiError(ERR_SOURCE_NOT_APPROVABLE, 409, "Source approve requires PROVISIONAL")
    if src["approval_scope"] in ("RAW_MATERIAL", "DISTRIBUTOR") and (
        src["counterfeit_risk_rating"] == "HIGH"
    ):
        raise ApiError(
            ERR_COUNTERFEIT_RISK_TOO_HIGH,
            422,
            "HIGH counterfeit-risk source cannot be approved for material scopes",
        )
    src["status"] = "APPROVED"
    touch(src)
    return success_object(public(src))


@bp.route("/api/sources/<sourceId>/disqualify", methods=["POST"])
def disqualify_source(sourceId):
    require_roles(SCM)
    data = json_body()
    no_unknown(data, {"reason"})
    req_str(data, "reason")
    src = get_source(sourceId)
    if src["status"] == "DISQUALIFIED":
        raise ApiError(ERR_SOURCE_NOT_APPROVABLE, 409, "Source is already DISQUALIFIED")
    was_approved = src["status"] == "APPROVED"
    src["status"] = "DISQUALIFIED"
    touch(src)
    if was_approved:
        # Containment: suspend every ACTIVE special-process approval of this source
        for pa in db.process_approvals.values():
            if pa["source_id"] == src["id"] and pa["status"] == "ACTIVE":
                pa["status"] = "SUSPENDED"
                touch(pa)
    return success_object(public(src))


# ---------------------------------------------------------------------------
# SpecialProcessApproval (half-open windows [valid_from, valid_to))
# ---------------------------------------------------------------------------
def _spa_overlaps(source_id, process_code, from_d, to_d, exclude_id=None):
    for pa in db.process_approvals.values():
        if pa["id"] == exclude_id:
            continue
        if (
            pa["source_id"] == source_id
            and pa["process_code"] == process_code
            and pa["status"] == "ACTIVE"
            and from_d < pa["_to_d"]
            and pa["_from_d"] < to_d
        ):
            return True
    return False


@bp.route("/api/process-approvals", methods=["POST"])
def create_pa():
    require_roles(SCM)
    data = json_body()
    no_unknown(data, {"source_id", "process_code", "valid_from", "valid_to", "cert_reference"})
    source_id = req_str(data, "source_id")
    process_code = req_enum(data, "process_code", PROCESS_CODES)
    valid_from, from_d = req_date(data, "valid_from")
    valid_to, to_d = req_date(data, "valid_to")
    cert_reference = req_str(data, "cert_reference")

    src = db.sources.get(source_id)
    if src is None:
        raise ApiError(ERR_SOURCE_NOT_FOUND, 404, "Source %s not found" % source_id)
    if src["status"] != "APPROVED" or src["approval_scope"] != "SPECIAL_PROCESS":
        raise ApiError(
            ERR_SOURCE_NOT_APPROVED,
            422,
            "Process approval requires an APPROVED SPECIAL_PROCESS source",
        )
    if to_d <= from_d:
        raise ApiError(ERR_INVALID_WINDOW, 400, "valid_to must be later than valid_from")
    if _spa_overlaps(source_id, process_code, from_d, to_d):
        raise ApiError(
            ERR_APPROVAL_WINDOW_OVERLAP,
            409,
            "Window overlaps an ACTIVE approval for this source and process",
        )

    rec = base_record(db.new_id())
    rec.update(
        {
            "source_id": source_id,
            "process_code": process_code,
            "valid_from": valid_from,
            "valid_to": valid_to,
            "cert_reference": cert_reference,
            "status": "ACTIVE",
            "_from_d": from_d,
            "_to_d": to_d,
        }
    )
    db.process_approvals[rec["id"]] = rec
    return success_object(public(rec), 201)


@bp.route("/api/process-approvals", methods=["GET"])
def list_pas():
    require_roles(*ALL_ROLES)
    items = list(db.process_approvals.values())
    source_id = request.args.get("source_id")
    process_code = request.args.get("process_code")
    status = request.args.get("status")
    if source_id is not None:
        items = [p for p in items if p["source_id"] == source_id]
    if process_code is not None:
        items = [p for p in items if p["process_code"] == process_code]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items.sort(key=lambda r: (r["_created_dt"], r["_seq"]))
    page, pagination = paginate(items, request.args)
    return success_list(page, pagination)


@bp.route("/api/process-approvals/<paId>", methods=["GET"])
def get_one_pa(paId):
    require_roles(*ALL_ROLES)
    return success_object(public(get_pa(paId)))


@bp.route("/api/process-approvals/<paId>/suspend", methods=["POST"])
def suspend_pa(paId):
    require_roles(SCM)
    data = json_body()
    no_unknown(data, set())
    pa = get_pa(paId)
    if pa["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "Suspend requires ACTIVE")
    pa["status"] = "SUSPENDED"
    touch(pa)
    return success_object(public(pa))


@bp.route("/api/process-approvals/<paId>/reinstate", methods=["POST"])
def reinstate_pa(paId):
    require_roles(SCM)
    data = json_body()
    no_unknown(data, set())
    pa = get_pa(paId)
    if pa["status"] != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE, 409, "Reinstate requires SUSPENDED")
    if _spa_overlaps(pa["source_id"], pa["process_code"], pa["_from_d"], pa["_to_d"], pa["id"]):
        raise ApiError(
            ERR_APPROVAL_WINDOW_OVERLAP,
            409,
            "Window overlaps an ACTIVE approval for this source and process",
        )
    pa["status"] = "ACTIVE"
    touch(pa)
    return success_object(public(pa))


# ---------------------------------------------------------------------------
# MaterialCert
# ---------------------------------------------------------------------------
@bp.route("/api/material-certs", methods=["POST"])
def create_cert():
    uid = require_roles(SCM)
    data = json_body()
    no_unknown(data, {"source_id", "heat_number", "material_spec", "quantity_received"})
    source_id = req_str(data, "source_id")
    heat_number = req_str(data, "heat_number")
    material_spec = req_str(data, "material_spec")
    qty = req_int(data, "quantity_received", min_val=1)

    src = db.sources.get(source_id)
    if src is None:
        raise ApiError(ERR_SOURCE_NOT_FOUND, 404, "Source %s not found" % source_id)
    if src["status"] != "APPROVED" or src["approval_scope"] not in (
        "RAW_MATERIAL",
        "DISTRIBUTOR",
    ):
        raise ApiError(
            ERR_SOURCE_NOT_APPROVED,
            422,
            "Material cert requires an APPROVED RAW_MATERIAL or DISTRIBUTOR source",
        )

    rec = base_record(db.new_id())
    rec.update(
        {
            "source_id": source_id,
            "heat_number": heat_number,
            "material_spec": material_spec,
            "quantity_received": qty,
            "quantity_available": qty,
            "created_by_user_id": uid,
            "status": "RECEIVED",
        }
    )
    db.material_certs[rec["id"]] = rec
    return success_object(public(rec), 201)


@bp.route("/api/material-certs", methods=["GET"])
def list_certs():
    require_roles(*ALL_ROLES)
    items = list(db.material_certs.values())
    source_id = request.args.get("source_id")
    status = request.args.get("status")
    if source_id is not None:
        items = [c for c in items if c["source_id"] == source_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items.sort(key=lambda r: (r["_created_dt"], r["_seq"]))
    page, pagination = paginate(items, request.args)
    return success_list(page, pagination)


@bp.route("/api/material-certs/<certId>", methods=["GET"])
def get_one_cert(certId):
    require_roles(*ALL_ROLES)
    return success_object(public(get_cert(certId)))


@bp.route("/api/material-certs/<certId>/accept", methods=["POST"])
def accept_cert(certId):
    uid = require_roles(QI)
    data = json_body()
    no_unknown(data, set())
    cert = get_cert(certId)
    if cert["status"] != "RECEIVED":
        raise ApiError(ERR_CERT_NOT_ACCEPTABLE, 409, "Cert accept requires RECEIVED")
    if uid == cert["created_by_user_id"]:
        raise ApiError(ERR_SOD_VIOLATION, 403, "Acceptor must differ from cert creator")
    cert["status"] = "ACCEPTED"
    touch(cert)
    return success_object(public(cert))


@bp.route("/api/material-certs/<certId>/revoke", methods=["POST"])
def revoke_cert(certId):
    require_roles(QM)
    data = json_body()
    no_unknown(data, {"reason"})
    req_str(data, "reason")
    cert = get_cert(certId)
    if cert["status"] == "REVOKED":
        raise ApiError(ERR_CERT_ALREADY_REVOKED, 409, "Cert is already REVOKED")
    cert["status"] = "REVOKED"
    touch(cert)

    # --- Containment cascade C1 -------------------------------------------
    # Link 1: quarantine CREATED serials traced to this cert
    quarantined_by_wo = {}
    for s in db.serials.values():
        if s["material_cert_id"] == cert["id"] and s["status"] == "CREATED":
            s["status"] = "QUARANTINED"
            touch(s)
            quarantined_by_wo.setdefault(s["wo_id"], []).append(s["id"])

    # Link 2: their IN_PRODUCTION work orders go on QUALITY_HOLD
    held = []
    for wo_id, sids in quarantined_by_wo.items():
        wo = db.work_orders.get(wo_id)
        if wo is not None and wo["status"] == "IN_PRODUCTION":
            wo["status"] = "QUALITY_HOLD"
            touch(wo)
            held.append((wo, sids))
    held.sort(key=lambda t: t[0]["_seq"])

    # Link 3: one AUTO_COUNTERFEIT NCR per held work order
    created_ncrs = []
    for wo, sids in held:
        ncr = create_ncr(
            wo_id=wo["id"],
            defect_code="COUNTERFEIT_SUSPECT",
            description="Automatic counterfeit-suspect report from material-cert revocation",
            quantity_affected=len(sids),
            affected_serial_ids=sids,
            detected_post_shipment=False,
            origin="AUTO_COUNTERFEIT",
            discovered_by_user_id=None,
        )
        created_ncrs.append(ncr)

    # Link 4: shipped suspect units raise a DRAFT escape on the affected PO's NCR
    shipped_pos = []
    for s in db.serials.values():
        if s["material_cert_id"] == cert["id"] and s["status"] == "SHIPPED":
            wo = db.work_orders.get(s["wo_id"])
            if wo is not None and wo["po_id"] not in shipped_pos:
                shipped_pos.append(wo["po_id"])
    for po_id in shipped_pos:
        ncr = None
        for n in created_ncrs:
            wo = db.work_orders.get(n["wo_id"])
            if wo is not None and wo["po_id"] == po_id:
                ncr = n
                break
        if ncr is None:
            # No held WO under this PO: anchor a report on the first WO that
            # owns shipped serials of this cert so the escape has a home.
            anchor_wo = None
            shipped_ids = []
            for s in db.serials.values():
                if s["material_cert_id"] == cert["id"] and s["status"] == "SHIPPED":
                    w = db.work_orders.get(s["wo_id"])
                    if w is not None and w["po_id"] == po_id:
                        if anchor_wo is None or w["_seq"] < anchor_wo["_seq"]:
                            anchor_wo = w
            if anchor_wo is None:
                continue
            shipped_ids = [
                s["id"]
                for s in db.serials.values()
                if s["wo_id"] == anchor_wo["id"]
                and s["material_cert_id"] == cert["id"]
                and s["status"] == "SHIPPED"
            ]
            ncr = create_ncr(
                wo_id=anchor_wo["id"],
                defect_code="COUNTERFEIT_SUSPECT",
                description="Automatic counterfeit-suspect report from material-cert revocation",
                quantity_affected=max(1, len(shipped_ids)),
                affected_serial_ids=shipped_ids,
                detected_post_shipment=False,
                origin="AUTO_COUNTERFEIT",
                discovered_by_user_id=None,
            )
            created_ncrs.append(ncr)
        ncr["detected_post_shipment"] = True
        touch(ncr)
        create_escape_report(ncr)

    return success_object(public(cert))
