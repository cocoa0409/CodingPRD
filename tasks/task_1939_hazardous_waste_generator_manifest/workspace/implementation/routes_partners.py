"""WastePartner and ComplianceAudit endpoints."""

from __future__ import annotations

from flask import Blueprint, request

from core import base_entity, bump, now_iso, refresh_partner_audit_flag
from db import _parse_iso, clock, store
from errors import (
    ApiError,
    ERR_ALREADY_TERMINAL,
    ERR_AUDIT_COVERAGE_OVERLAP,
    ERR_AUDIT_WINDOW_REGRESSIVE,
    ERR_DUPLICATE_EPA_ID,
    ERR_SOD_PARTNER_SELF_APPROVE,
    ERR_STALE_VERSION,
    already_terminal,
    invalid_request,
    invalid_state,
    not_found,
)
from middleware import require_roles
from response import success_list, success_object
from validators import (
    opt_str,
    reject_unknown_fields,
    req_enum,
    req_int,
    req_str,
    req_str_list,
    require_fields,
    require_object,
)

bp = Blueprint("partners", __name__)

ALL_ROLES = ("EHSManager", "WasteCoordinator", "ComplianceAuditor", "TransporterAgent", "TSDFAgent")

_PARTNER_TYPES = {"TRANSPORTER", "TSDF"}
_AUDIT_OUTCOMES = {"PASS", "FAIL"}
_TO_STATUS = {"APPROVED", "SUSPENDED", "REJECTED"}


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


def partner_view(p: dict) -> dict:
    refresh_partner_audit_flag(p)
    return dict(p)


@bp.route("/hazwaste/waste-partners", methods=["POST"])
def create_partner():
    user_id, _ = require_roles("ComplianceAuditor")
    body = require_object(request.get_json(silent=True) or {})
    allowed = {"partner_type", "name", "epa_id_number", "permitted_waste_codes"}
    reject_unknown_fields(body, allowed)
    require_fields(body, ["partner_type", "name", "epa_id_number", "permitted_waste_codes"])
    partner_type = req_enum(body, "partner_type", _PARTNER_TYPES)
    name = req_str(body, "name")
    epa = req_str(body, "epa_id_number", allow_empty=False)
    permitted = req_str_list(body, "permitted_waste_codes")

    for p in store.partners.values():
        if p["epa_id_number"] == epa:
            raise ApiError(ERR_DUPLICATE_EPA_ID, 409, "epa_id_number already registered")

    p = base_entity()
    p.update(
        {
            "partner_type": partner_type,
            "name": name,
            "epa_id_number": epa,
            "permitted_waste_codes": list(permitted),
            "status": "PENDING",
            "created_by_user_id": user_id,
            "audit_coverage_start": None,
            "audit_coverage_end": None,
            "is_audit_current": False,
        }
    )
    store.partners[p["id"]] = p
    return success_object(partner_view(p), status=201)


@bp.route("/hazwaste/waste-partners/<partnerId>", methods=["GET"])
def get_partner(partnerId: str):
    require_roles(*ALL_ROLES)
    p = store.partners.get(partnerId)
    if p is None:
        raise not_found("partner not found")
    return success_object(partner_view(p))


@bp.route("/hazwaste/waste-partners/<partnerId>", methods=["PUT"])
def update_partner(partnerId: str):
    user_id, _ = require_roles("ComplianceAuditor")
    p = store.partners.get(partnerId)
    if p is None:
        raise not_found("partner not found")
    body = require_object(request.get_json(silent=True) or {})
    allowed = {"name", "permitted_waste_codes", "expected_waste_partner_version"}
    reject_unknown_fields(body, allowed)
    require_fields(body, ["expected_waste_partner_version"])
    expected = req_int(body, "expected_waste_partner_version")
    new_name = None
    new_permitted = None
    if "name" in body and body["name"] is not None:
        new_name = req_str(body, "name")
    if "permitted_waste_codes" in body and body["permitted_waste_codes"] is not None:
        new_permitted = req_str_list(body, "permitted_waste_codes")

    if p["version"] != expected:
        raise ApiError(ERR_STALE_VERSION, 412, "expected_waste_partner_version does not match current version")

    if new_name is not None:
        p["name"] = new_name
    if new_permitted is not None:
        p["permitted_waste_codes"] = list(new_permitted)
    bump(p)
    return success_object(partner_view(p))


@bp.route("/hazwaste/waste-partners/<partnerId>/status", methods=["POST"])
def partner_status(partnerId: str):
    user_id, _ = require_roles("ComplianceAuditor")
    p = store.partners.get(partnerId)
    if p is None:
        raise not_found("partner not found")
    body = require_object(request.get_json(silent=True) or {})
    allowed = {"to_status"}
    reject_unknown_fields(body, allowed)
    require_fields(body, ["to_status"])
    to_status = req_enum(body, "to_status", _TO_STATUS)

    current = p["status"]

    if current == "REJECTED":
        raise already_terminal("partner is rejected")

    if to_status == "APPROVED":
        if current not in ("PENDING", "SUSPENDED"):
            raise invalid_state(f"cannot approve from {current}")
        if user_id == p.get("created_by_user_id"):
            raise ApiError(ERR_SOD_PARTNER_SELF_APPROVE, 403, "approver must differ from registrar")
        p["status"] = "APPROVED"
    elif to_status == "SUSPENDED":
        if current != "APPROVED":
            raise invalid_state(f"cannot suspend from {current}")
        p["status"] = "SUSPENDED"
    elif to_status == "REJECTED":
        if current != "PENDING":
            raise invalid_state(f"cannot reject from {current}")
        p["status"] = "REJECTED"

    bump(p)
    return success_object(partner_view(p))


@bp.route("/hazwaste/waste-partners/<partnerId>/audits", methods=["POST"])
def create_audit(partnerId: str):
    user_id, _ = require_roles("ComplianceAuditor")
    p = store.partners.get(partnerId)
    if p is None:
        raise not_found("partner not found")
    body = require_object(request.get_json(silent=True) or {})
    allowed = {"coverage_from", "coverage_to", "outcome"}
    reject_unknown_fields(body, allowed)
    require_fields(body, ["coverage_from", "coverage_to", "outcome"])
    coverage_from_s = req_str(body, "coverage_from")
    coverage_to_s = req_str(body, "coverage_to")
    outcome = req_enum(body, "outcome", _AUDIT_OUTCOMES)

    try:
        coverage_from = _parse_iso(coverage_from_s)
    except Exception:
        raise invalid_request("coverage_from must be ISO 8601")
    try:
        coverage_to = _parse_iso(coverage_to_s)
    except Exception:
        raise invalid_request("coverage_to must be ISO 8601")

    if not (coverage_to > coverage_from):
        raise invalid_request("coverage_to must be strictly greater than coverage_from")

    # Window merge / validation per audit_currency calculation
    cur_start_s = p.get("audit_coverage_start")
    cur_end_s = p.get("audit_coverage_end")
    if cur_start_s is not None and cur_end_s is not None:
        cur_start = _parse_iso(cur_start_s)
        cur_end = _parse_iso(cur_end_s)

        overlaps_or_abuts = coverage_from <= cur_end and coverage_to >= cur_start
        strict_interior_overlap = cur_start < coverage_to and coverage_from < cur_end

        if outcome == "FAIL":
            if strict_interior_overlap:
                raise ApiError(
                    ERR_AUDIT_COVERAGE_OVERLAP,
                    409,
                    "FAIL audit window overlaps existing coverage",
                )
            # FAIL disjoint windows: must not be entirely earlier
            if coverage_to <= cur_start:
                raise ApiError(
                    ERR_AUDIT_WINDOW_REGRESSIVE,
                    409,
                    "audit window is entirely earlier than current coverage",
                )
            # disjoint and later: replace
            p["audit_coverage_start"] = coverage_from_s
            p["audit_coverage_end"] = coverage_to_s
        else:
            # PASS
            if overlaps_or_abuts:
                new_start = min(cur_start, coverage_from)
                new_end = max(cur_end, coverage_to)
                p["audit_coverage_start"] = _iso(new_start)
                p["audit_coverage_end"] = _iso(new_end)
            else:
                # disjoint
                if coverage_to <= cur_start:
                    raise ApiError(
                        ERR_AUDIT_WINDOW_REGRESSIVE,
                        409,
                        "audit window is entirely earlier than current coverage",
                    )
                # disjoint and later: replace
                p["audit_coverage_start"] = coverage_from_s
                p["audit_coverage_end"] = coverage_to_s
    else:
        # No current window: accept new window as-is
        p["audit_coverage_start"] = coverage_from_s
        p["audit_coverage_end"] = coverage_to_s

    refresh_partner_audit_flag(p)
    bump(p)

    a = base_entity()
    a.update(
        {
            "waste_partner_id": partnerId,
            "auditor_user_id": user_id,
            "audited_at": now_iso(),
            "coverage_from": coverage_from_s,
            "coverage_to": coverage_to_s,
            "outcome": outcome,
        }
    )
    store.audits[a["id"]] = a
    return success_object(dict(a), status=201)


def _iso(dt):
    from db import iso_utc

    return iso_utc(dt)


@bp.route("/hazwaste/waste-partners/<partnerId>/audits", methods=["GET"])
def list_audits(partnerId: str):
    require_roles(*ALL_ROLES)
    p = store.partners.get(partnerId)
    if p is None:
        raise not_found("partner not found")
    limit, offset = _parse_pagination()
    items = [a for a in store.audits.values() if a["waste_partner_id"] == partnerId]
    items.sort(key=lambda a: a["created_at"])
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([dict(a) for a in page], limit, offset, total)
