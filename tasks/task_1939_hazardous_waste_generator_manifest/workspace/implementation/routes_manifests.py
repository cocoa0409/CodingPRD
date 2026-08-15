"""Manifest endpoints."""

from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, request

from core import (
    base_entity,
    bump,
    compute_tonnage_fee_cents,
    now_iso,
    recompute_report_provisional,
    refresh_partner_audit_flag,
)
from db import _parse_iso, clock, iso_utc, store
from errors import (
    ApiError,
    ERR_ALREADY_TERMINAL,
    ERR_CONTAINER_NOT_STAGED,
    ERR_CROSS_SITE_REFERENCE,
    ERR_DUPLICATE_TRACKING_NUMBER,
    ERR_LDR_NOTICE_MISSING,
    ERR_LINE_CONTAINER_MISMATCH,
    ERR_MANIFEST_NOT_DRAFT,
    ERR_OPEN_EXCEPTION_BLOCKS_MANIFEST,
    ERR_PARTNER_AUDIT_STALE,
    ERR_PARTNER_IDENTITY_MISMATCH,
    ERR_PARTNER_NOT_APPROVED,
    ERR_PARTNER_TYPE_MISMATCH,
    ERR_SOD_MANIFEST_SELF_SIGN,
    ERR_TSDF_WASTE_CODE_NOT_PERMITTED,
    already_terminal,
    invalid_request,
    invalid_state,
    not_found,
)
from middleware import require_roles
from response import success_list, success_object
from validators import (
    reject_unknown_fields,
    req_list,
    req_num,
    req_str,
    require_fields,
    require_object,
)

bp = Blueprint("manifests", __name__)

ALL_ROLES = ("EHSManager", "WasteCoordinator", "ComplianceAuditor", "TransporterAgent", "TSDFAgent")

_RETURN_WINDOW_DAYS = 45


def _parse_pagination():
    limit_s = request.args.get("limit")
    offset_s = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_s is not None:
        try:
            limit = int(limit_s)
        except (ValueError, TypeError):
            raise invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise invalid_request("limit must be between 1 and 100")
    if offset_s is not None:
        try:
            offset = int(offset_s)
        except (ValueError, TypeError):
            raise invalid_request("offset must be an integer")
        if offset < 0:
            raise invalid_request("offset must be >= 0")
    return limit, offset


def manifest_view(m: dict) -> dict:
    return dict(m)


def _validate_line_items(raw: list) -> list:
    out = []
    for line in raw:
        if not isinstance(line, dict):
            raise invalid_request("line_items entries must be objects")
        unknown = set(line.keys()) - {"waste_stream_id", "container_id", "quantity_kg"}
        if unknown:
            raise invalid_request(f"line_items entry has unknown fields: {sorted(unknown)}")
        for f in ("waste_stream_id", "container_id", "quantity_kg"):
            if f not in line:
                raise invalid_request(f"line_items entry missing field {f}")
        if not isinstance(line["waste_stream_id"], str):
            raise invalid_request("line_items.waste_stream_id must be a string")
        if not isinstance(line["container_id"], str):
            raise invalid_request("line_items.container_id must be a string")
        qty = line["quantity_kg"]
        if isinstance(qty, bool) or not isinstance(qty, (int, float)):
            raise invalid_request("line_items.quantity_kg must be a number")
        if qty <= 0:
            raise invalid_request("line_items.quantity_kg must be > 0")
        out.append(
            {
                "waste_stream_id": line["waste_stream_id"],
                "container_id": line["container_id"],
                "quantity_kg": qty,
            }
        )
    return out


@bp.route("/hazwaste/manifests", methods=["POST"])
def create_manifest():
    user_id, _ = require_roles("WasteCoordinator")
    body = require_object(request.get_json(silent=True) or {})
    allowed = {"site_id", "transporter_id", "tsdf_id", "manifest_tracking_number", "line_items"}
    reject_unknown_fields(body, allowed)
    require_fields(body, ["site_id", "transporter_id", "tsdf_id", "manifest_tracking_number", "line_items"])
    site_id = req_str(body, "site_id")
    transporter_id = req_str(body, "transporter_id")
    tsdf_id = req_str(body, "tsdf_id")
    tracking = req_str(body, "manifest_tracking_number")
    line_items_raw = req_list(body, "line_items")
    if not line_items_raw:
        raise invalid_request("line_items must contain at least one entry")
    line_items = _validate_line_items(line_items_raw)

    # Existence left-to-right: site, then transporter, then tsdf, then line-item containers
    site = store.sites.get(site_id)
    if site is None:
        raise not_found("site not found")
    transporter = store.partners.get(transporter_id)
    if transporter is None:
        raise not_found("transporter not found")
    tsdf = store.partners.get(tsdf_id)
    if tsdf is None:
        raise not_found("tsdf not found")
    # line-item containers
    containers = []
    streams = []
    for line in line_items:
        c = store.containers.get(line["container_id"])
        if c is None:
            raise not_found(f"container {line['container_id']} not found")
        containers.append(c)
        st = store.streams.get(line["waste_stream_id"])
        if st is None:
            raise not_found(f"waste stream {line['waste_stream_id']} not found")
        streams.append(st)

    # State band
    for c in containers:
        if c["status"] != "STAGED_FOR_SHIPMENT":
            raise ApiError(ERR_CONTAINER_NOT_STAGED, 409, "every line-item container must be STAGED_FOR_SHIPMENT")

    # Business safety / referential
    if transporter["partner_type"] != "TRANSPORTER":
        raise ApiError(ERR_PARTNER_TYPE_MISMATCH, 409, "transporter_id must reference a TRANSPORTER partner")
    if tsdf["partner_type"] != "TSDF":
        raise ApiError(ERR_PARTNER_TYPE_MISMATCH, 409, "tsdf_id must reference a TSDF partner")

    # Cross-site and line integrity
    for i, c in enumerate(containers):
        if c["site_id"] != site_id:
            raise ApiError(ERR_CROSS_SITE_REFERENCE, 409, "line-item container site mismatch")
        if c["waste_stream_id"] != line_items[i]["waste_stream_id"]:
            raise ApiError(ERR_LINE_CONTAINER_MISMATCH, 400, "container stream does not match line stream")

    # Uniqueness of tracking number within site
    for m in store.manifests.values():
        if m["site_id"] == site_id and m["manifest_tracking_number"] == tracking:
            raise ApiError(ERR_DUPLICATE_TRACKING_NUMBER, 409, "manifest_tracking_number already used for this site")

    # Open exception gate
    if site.get("open_exception_count", 0) > 0:
        raise ApiError(ERR_OPEN_EXCEPTION_BLOCKS_MANIFEST, 409, "site has open manifest exceptions")

    # Partner approval
    if transporter["status"] != "APPROVED":
        raise ApiError(ERR_PARTNER_NOT_APPROVED, 409, "transporter is not APPROVED")
    if tsdf["status"] != "APPROVED":
        raise ApiError(ERR_PARTNER_NOT_APPROVED, 409, "tsdf is not APPROVED")

    # Audit currency
    refresh_partner_audit_flag(transporter)
    refresh_partner_audit_flag(tsdf)
    if not transporter.get("is_audit_current"):
        raise ApiError(ERR_PARTNER_AUDIT_STALE, 409, "transporter audit not current")
    if not tsdf.get("is_audit_current"):
        raise ApiError(ERR_PARTNER_AUDIT_STALE, 409, "tsdf audit not current")

    # TSDF permit covers every waste code of every line's stream
    permitted = set(tsdf.get("permitted_waste_codes", []))
    for st in streams:
        for code in st.get("waste_codes", []):
            if code not in permitted:
                raise ApiError(ERR_TSDF_WASTE_CODE_NOT_PERMITTED, 409, f"TSDF not permitted for waste code {code}")

    # Build manifest
    total_qty = sum(line["quantity_kg"] for line in line_items)
    tonnage = compute_tonnage_fee_cents(line_items)

    m = base_entity()
    m.update(
        {
            "site_id": site_id,
            "transporter_id": transporter_id,
            "tsdf_id": tsdf_id,
            "manifest_tracking_number": tracking,
            "line_items": line_items,
            "status": "DRAFT",
            "created_by_user_id": user_id,
            "generator_signed_by_user_id": None,
            "shipped_at": None,
            "return_due_at": None,
            "delivered_at": None,
            "returned_at": None,
            "is_return_late": False,
            "exception_note": None,
            "total_quantity_kg": total_qty,
            "tonnage_fee_cents": tonnage,
        }
    )
    store.manifests[m["id"]] = m
    return success_object(manifest_view(m), status=201)


@bp.route("/hazwaste/manifests", methods=["GET"])
def list_manifests():
    require_roles(*ALL_ROLES)
    limit, offset = _parse_pagination()
    site_id = request.args.get("site_id")
    transporter_id = request.args.get("transporter_id")
    tsdf_id = request.args.get("tsdf_id")
    items = list(store.manifests.values())
    if site_id is not None:
        items = [m for m in items if m["site_id"] == site_id]
    if transporter_id is not None:
        items = [m for m in items if m["transporter_id"] == transporter_id]
    if tsdf_id is not None:
        items = [m for m in items if m["tsdf_id"] == tsdf_id]
    items.sort(key=lambda m: m["created_at"])
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([manifest_view(m) for m in page], limit, offset, total)


@bp.route("/hazwaste/manifests/<manifestId>", methods=["GET"])
def get_manifest(manifestId: str):
    require_roles(*ALL_ROLES)
    m = store.manifests.get(manifestId)
    if m is None:
        raise not_found("manifest not found")
    return success_object(manifest_view(m))


@bp.route("/hazwaste/manifests/<manifestId>/ldr-notifications", methods=["POST"])
def create_ldr(manifestId: str):
    user_id, _ = require_roles("EHSManager")
    m = store.manifests.get(manifestId)
    if m is None:
        raise not_found("manifest not found")
    body = require_object(request.get_json(silent=True) or {})
    allowed = {"treatment_standard_codes", "certification_statement"}
    reject_unknown_fields(body, allowed)
    require_fields(body, ["treatment_standard_codes", "certification_statement"])
    codes = req_list(body, "treatment_standard_codes")
    for c in codes:
        if not isinstance(c, str):
            raise invalid_request("treatment_standard_codes must be an array of strings")
    cert = req_str(body, "certification_statement", allow_empty=False)

    # LDR notice may only be attached to a DRAFT manifest
    if m["status"] != "DRAFT":
        raise invalid_state("LDR notice may only be attached to a DRAFT manifest")

    nid = base_entity()
    # LDRNotification has only id + created_at per PRD §2.4
    ldr = {
        "id": nid["id"],
        "created_at": nid["created_at"],
        "manifest_id": manifestId,
        "treatment_standard_codes": list(codes),
        "certification_statement": cert,
        "notified_at": now_iso(),
    }
    store.ldr_notifications[ldr["id"]] = ldr
    return success_object(dict(ldr), status=201)


@bp.route("/hazwaste/manifests/<manifestId>/ldr-notifications", methods=["GET"])
def list_ldr(manifestId: str):
    require_roles(*ALL_ROLES)
    m = store.manifests.get(manifestId)
    if m is None:
        raise not_found("manifest not found")
    items = [l for l in store.ldr_notifications.values() if l["manifest_id"] == manifestId]
    items.sort(key=lambda l: l["created_at"])
    return success_list([dict(l) for l in items], 10, 0, len(items))


@bp.route("/hazwaste/manifests/<manifestId>/sign-generator", methods=["POST"])
def sign_generator(manifestId: str):
    user_id, _ = require_roles("EHSManager")
    m = store.manifests.get(manifestId)
    if m is None:
        raise not_found("manifest not found")
    body = request.get_json(silent=True) or {}
    if body:
        require_object(body)
        reject_unknown_fields(body, set())

    if m["status"] == "RETURNED":
        raise already_terminal("manifest already returned")
    if m["status"] != "DRAFT":
        raise ApiError(ERR_MANIFEST_NOT_DRAFT, 409, "manifest must be DRAFT to sign")
    if user_id == m["created_by_user_id"]:
        raise ApiError(ERR_SOD_MANIFEST_SELF_SIGN, 403, "generator signer must differ from creator")

    # LDR notice required
    has_ldr = any(l["manifest_id"] == manifestId for l in store.ldr_notifications.values())
    if not has_ldr:
        raise ApiError(ERR_LDR_NOTICE_MISSING, 409, "LDR notice required before generator signature")

    # All containers still STAGED
    containers = []
    streams = []
    for line in m["line_items"]:
        c = store.containers.get(line["container_id"])
        if c is None:
            raise not_found(f"container {line['container_id']} not found")
        containers.append(c)
        st = store.streams.get(line["waste_stream_id"])
        streams.append(st)
    for c in containers:
        if c["status"] != "STAGED_FOR_SHIPMENT":
            raise ApiError(ERR_CONTAINER_NOT_STAGED, 409, "every container must be STAGED_FOR_SHIPMENT")

    transporter = store.partners[m["transporter_id"]]
    tsdf = store.partners[m["tsdf_id"]]
    if transporter["status"] != "APPROVED":
        raise ApiError(ERR_PARTNER_NOT_APPROVED, 409, "transporter not APPROVED")
    if tsdf["status"] != "APPROVED":
        raise ApiError(ERR_PARTNER_NOT_APPROVED, 409, "tsdf not APPROVED")
    refresh_partner_audit_flag(transporter)
    refresh_partner_audit_flag(tsdf)
    if not transporter.get("is_audit_current"):
        raise ApiError(ERR_PARTNER_AUDIT_STALE, 409, "transporter audit stale")
    if not tsdf.get("is_audit_current"):
        raise ApiError(ERR_PARTNER_AUDIT_STALE, 409, "tsdf audit stale")

    permitted = set(tsdf.get("permitted_waste_codes", []))
    for st in streams:
        if st is None:
            continue
        for code in st.get("waste_codes", []):
            if code not in permitted:
                raise ApiError(ERR_TSDF_WASTE_CODE_NOT_PERMITTED, 409, f"TSDF not permitted for {code}")

    m["status"] = "GENERATOR_SIGNED"
    m["generator_signed_by_user_id"] = user_id
    bump(m)
    return success_object(manifest_view(m))


@bp.route("/hazwaste/manifests/<manifestId>/sign-transporter", methods=["POST"])
def sign_transporter(manifestId: str):
    user_id, _ = require_roles("TransporterAgent")
    m = store.manifests.get(manifestId)
    if m is None:
        raise not_found("manifest not found")
    body = request.get_json(silent=True) or {}
    if body:
        require_object(body)
        reject_unknown_fields(body, set())

    # Ownership
    if user_id != m["transporter_id"]:
        raise ApiError(ERR_PARTNER_IDENTITY_MISMATCH, 403, "agent must match manifest transporter_id")

    if m["status"] != "GENERATOR_SIGNED":
        raise invalid_state(f"cannot sign-transporter from {m['status']}")

    now = clock.now()
    m["status"] = "IN_TRANSIT"
    m["shipped_at"] = iso_utc(now)
    m["return_due_at"] = iso_utc(now + timedelta(days=_RETURN_WINDOW_DAYS))
    bump(m)

    # Cascade: containers STAGED_FOR_SHIPMENT -> SHIPPED
    for line in m["line_items"]:
        c = store.containers.get(line["container_id"])
        if c is None:
            continue
        if c["status"] == "STAGED_FOR_SHIPMENT":
            c["status"] = "SHIPPED"
            c["shipped_manifest_id"] = m["id"]
            bump(c)

    return success_object(manifest_view(m))


@bp.route("/hazwaste/manifests/<manifestId>/receive", methods=["POST"])
def receive(manifestId: str):
    user_id, _ = require_roles("TSDFAgent")
    m = store.manifests.get(manifestId)
    if m is None:
        raise not_found("manifest not found")
    body = request.get_json(silent=True) or {}
    if body:
        require_object(body)
        reject_unknown_fields(body, set())

    if user_id != m["tsdf_id"]:
        raise ApiError(ERR_PARTNER_IDENTITY_MISMATCH, 403, "agent must match manifest tsdf_id")
    if m["status"] != "IN_TRANSIT":
        raise invalid_state(f"cannot receive from {m['status']}")

    m["status"] = "DELIVERED"
    m["delivered_at"] = now_iso()
    bump(m)

    for line in m["line_items"]:
        c = store.containers.get(line["container_id"])
        if c is None:
            continue
        if c["status"] == "SHIPPED":
            c["status"] = "EMPTIED"
            bump(c)

    return success_object(manifest_view(m))


@bp.route("/hazwaste/manifests/<manifestId>/raise-discrepancy", methods=["POST"])
def raise_discrepancy(manifestId: str):
    user_id, _ = require_roles("TSDFAgent")
    m = store.manifests.get(manifestId)
    if m is None:
        raise not_found("manifest not found")
    body = request.get_json(silent=True) or {}
    if body:
        require_object(body)
        reject_unknown_fields(body, set())

    if user_id != m["tsdf_id"]:
        raise ApiError(ERR_PARTNER_IDENTITY_MISMATCH, 403, "agent must match manifest tsdf_id")
    if m["status"] != "DELIVERED":
        raise invalid_state(f"cannot raise discrepancy from {m['status']}")

    m["status"] = "DISCREPANCY_RAISED"
    bump(m)
    site = store.sites.get(m["site_id"])
    if site:
        site["open_discrepancy_count"] = site.get("open_discrepancy_count", 0) + 1
        bump(site)
    return success_object(manifest_view(m))


@bp.route("/hazwaste/manifests/<manifestId>/resolve-discrepancy", methods=["POST"])
def resolve_discrepancy(manifestId: str):
    user_id, _ = require_roles("ComplianceAuditor")
    m = store.manifests.get(manifestId)
    if m is None:
        raise not_found("manifest not found")
    body = request.get_json(silent=True) or {}
    if body:
        require_object(body)
        reject_unknown_fields(body, set())

    if m["status"] != "DISCREPANCY_RAISED":
        raise invalid_state(f"cannot resolve discrepancy from {m['status']}")

    m["status"] = "DELIVERED"
    bump(m)
    site = store.sites.get(m["site_id"])
    if site:
        site["open_discrepancy_count"] = site.get("open_discrepancy_count", 0) - 1
        bump(site)
    return success_object(manifest_view(m))


@bp.route("/hazwaste/manifests/<manifestId>/confirm-return", methods=["POST"])
def confirm_return(manifestId: str):
    user_id, _ = require_roles("EHSManager")
    m = store.manifests.get(manifestId)
    if m is None:
        raise not_found("manifest not found")
    body = request.get_json(silent=True) or {}
    if body:
        require_object(body)
        reject_unknown_fields(body, set())

    if m["status"] == "RETURNED":
        raise already_terminal("manifest already returned")
    if m["status"] not in ("DELIVERED", "EXCEPTION_REQUIRED", "EXCEPTION_REPORT_FILED"):
        raise invalid_state(f"cannot confirm-return from {m['status']}")

    now = clock.now()
    m["returned_at"] = iso_utc(now)
    due = m.get("return_due_at")
    m["is_return_late"] = bool(due) and now > _parse_iso(due)
    prev = m["status"]
    m["status"] = "RETURNED"
    bump(m)

    if prev in ("EXCEPTION_REQUIRED", "EXCEPTION_REPORT_FILED"):
        site = store.sites.get(m["site_id"])
        if site:
            site["open_exception_count"] = site.get("open_exception_count", 0) - 1
            bump(site)

    # Recompute covering DRAFT reports for the site
    shipped_at = m.get("shipped_at")
    if shipped_at:
        for rep in store.reports.values():
            if rep["site_id"] != m["site_id"]:
                continue
            if rep["status"] != "DRAFT":
                continue
            ps = _parse_iso(rep["period_start"])
            pe = _parse_iso(rep["period_end"])
            sdt = _parse_iso(shipped_at)
            if ps <= sdt < pe:
                recompute_report_provisional(rep)

    return success_object(manifest_view(m))


@bp.route("/hazwaste/manifests/<manifestId>/file-exception-report", methods=["POST"])
def file_exception_report(manifestId: str):
    user_id, _ = require_roles("ComplianceAuditor")
    m = store.manifests.get(manifestId)
    if m is None:
        raise not_found("manifest not found")
    body = require_object(request.get_json(silent=True) or {})
    allowed = {"exception_note"}
    reject_unknown_fields(body, allowed)
    require_fields(body, ["exception_note"])
    note = req_str(body, "exception_note")

    if m["status"] != "EXCEPTION_REQUIRED":
        raise invalid_state(f"cannot file exception report from {m['status']}")

    m["exception_note"] = note
    m["status"] = "EXCEPTION_REPORT_FILED"
    bump(m)
    return success_object(manifest_view(m))
