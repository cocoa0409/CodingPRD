"""Vendor registration, attribute revision, offboarding trigger, vendor
contacts, and the ReassessmentSchedule audit log (PRD §3.1, §3.9, §3.8).
"""
from datetime import timedelta

from flask import Blueprint, g, request

import db
import errors
import helpers
import util
from errors import ApiError
from middleware import (body, paginate, require_roles, scope_vendor_or_403,
                        vc_vendor_id)
from response import ok, ok_list
from serializers import serialize

bp = Blueprint("vendors", __name__, url_prefix="/vsa/vendors")

SENSITIVITIES = ("PUBLIC", "INTERNAL", "CONFIDENTIAL", "REGULATED")
ACCESS_LEVELS = ("NONE", "READ_ONLY", "OPERATOR", "PRIVILEGED")
CRITICALITIES = ("LOW", "MEDIUM", "HIGH", "MISSION_CRITICAL")
POSTURES = ("ONBOARDING", "ASSESSING", "APPROVED", "CONDITIONAL",
            "SUSPENDED", "OFFBOARDING", "OFFBOARDED")
TIERS = ("TIER_1", "TIER_2", "TIER_3", "TIER_4")


@bp.post("")
@require_roles("RiskAnalyst")
def create_vendor():
    data = body()
    legal_name = data.get("legal_name")
    if not isinstance(legal_name, str) or not legal_name:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, "legal_name is required")
    sens = data.get("data_sensitivity")
    access = data.get("access_level")
    crit = data.get("criticality")
    if sens not in SENSITIVITIES:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422,
                       "data_sensitivity must be one of %s" % (SENSITIVITIES,))
    if access not in ACCESS_LEVELS:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422,
                       "access_level must be one of %s" % (ACCESS_LEVELS,))
    if crit not in CRITICALITIES:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422,
                       "criticality must be one of %s" % (CRITICALITIES,))
    vendor = {
        "legal_name": legal_name,
        "data_sensitivity": sens,
        "access_level": access,
        "criticality": crit,
        "current_tier": None,
        "posture": "ONBOARDING",
        "active_cycle_id": None,
        "risk_score": 0.0,
        "next_reassessment_due": None,
        "offboarding_deadline": None,
    }
    helpers.stamp_new("vendors", vendor)
    db.vendors[vendor["id"]] = vendor
    helpers.reassign_tier(vendor)      # tier_assignment on registration
    helpers.refresh_risk(vendor)       # vendor_risk_score baseline
    return ok(serialize("vendor", vendor), 201)


@bp.get("")
@require_roles("RiskAnalyst", "SecurityApprover", "PlatformAdmin", "VendorContact")
def list_vendors():
    items = list(db.vendors.values())
    if g.role == "VendorContact":
        scope = vc_vendor_id()
        items = [v for v in items if v["id"] == scope]
    posture = request.args.get("posture")
    tier = request.args.get("current_tier")
    active_cycle = request.args.get("active_cycle_id")
    if posture is not None:
        items = [v for v in items if v["posture"] == posture]
    if tier is not None:
        items = [v for v in items if v["current_tier"] == tier]
    if active_cycle is not None:
        items = [v for v in items if (v.get("active_cycle_id") or "") == active_cycle]
    page, limit, offset, total = paginate(items)
    return ok_list([serialize("vendor", v) for v in page], limit, offset, total)


@bp.get("/<vid>")
@require_roles("RiskAnalyst", "SecurityApprover", "PlatformAdmin", "VendorContact")
def get_vendor(vid):
    vendor = helpers.get_vendor(vid)
    scope_vendor_or_403(vid)
    return ok(serialize("vendor", vendor))


@bp.patch("/<vid>")
@require_roles("RiskAnalyst")
def patch_vendor(vid):
    vendor = helpers.get_vendor(vid)
    data = body()
    if "legal_name" in data:
        if not isinstance(data["legal_name"], str) or not data["legal_name"]:
            raise ApiError(errors.ERR_INVALID_REQUEST, 422,
                           "legal_name must be a non-empty string")
    if "data_sensitivity" in data and data["data_sensitivity"] not in SENSITIVITIES:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422,
                       "data_sensitivity must be one of %s" % (SENSITIVITIES,))
    if "access_level" in data and data["access_level"] not in ACCESS_LEVELS:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422,
                       "access_level must be one of %s" % (ACCESS_LEVELS,))
    if "criticality" in data and data["criticality"] not in CRITICALITIES:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422,
                       "criticality must be one of %s" % (CRITICALITIES,))
    for field in ("legal_name", "data_sensitivity", "access_level", "criticality"):
        if field in data:
            vendor[field] = data[field]
    helpers.reassign_tier(vendor)      # tier_assignment on attribute revision
    helpers.refresh_risk(vendor)
    helpers.touch("vendors", vendor)
    return ok(serialize("vendor", vendor))


@bp.post("/<vid>/offboard")
@require_roles("RiskAnalyst")
def offboard_vendor(vid):
    vendor = helpers.get_vendor(vid)
    if vendor["posture"] not in ("ONBOARDING", "APPROVED", "CONDITIONAL", "SUSPENDED"):
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Vendor posture %s cannot enter offboarding" % vendor["posture"])
    if vendor["posture"] in ("ONBOARDING", "APPROVED", "CONDITIONAL"):
        if vendor.get("active_cycle_id") or helpers.non_terminal_cycle(vendor):
            raise ApiError(errors.ERR_INVALID_STATE, 409,
                           "Cannot offboard a vendor with a cycle in flight")
    vendor["posture"] = "OFFBOARDING"
    vendor["offboarding_deadline"] = util.iso(util.now() + timedelta(days=90))
    attestation = {
        "vendor_id": vendor["id"],
        "data_returned": None,
        "data_destroyed": None,
        "destruction_method": None,
        "attested_by": None,
        "status": "REQUESTED",
        "submitted_at": None,
    }
    helpers.stamp_new("attestations", attestation)
    db.attestations[attestation["id"]] = attestation
    helpers.touch("vendors", vendor)
    helpers.refresh_risk(vendor)
    return ok(serialize("vendor", vendor))


@bp.post("/<vid>/contacts")
@require_roles("RiskAnalyst")
def create_contact(vid):
    vendor = helpers.get_vendor(vid)
    data = body()
    email = data.get("email")
    full_name = data.get("full_name")
    is_primary = data.get("is_primary", False)
    if not isinstance(email, str) or not email:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, "email is required")
    if not isinstance(full_name, str) or not full_name:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, "full_name is required")
    if not isinstance(is_primary, bool):
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, "is_primary must be a boolean")
    for other in db.contacts.values():
        if other["vendor_id"] == vid and other["email"] == email:
            raise ApiError(errors.ERR_UNIQUENESS_VIOLATION, 409,
                           "email must be unique within the vendor")
    contact = {
        "vendor_id": vid,
        "email": email,
        "full_name": full_name,
        "is_primary": is_primary,
    }
    helpers.stamp_new("contacts", contact)
    db.contacts[contact["id"]] = contact
    if is_primary:
        # Exactly one primary per vendor: demote the incumbent.
        for other in db.contacts.values():
            if other["vendor_id"] == vid and other["id"] != contact["id"]:
                other["is_primary"] = False
    return ok(serialize("contact", contact), 201)


@bp.get("/<vid>/contacts")
@require_roles("RiskAnalyst", "SecurityApprover", "VendorContact")
def list_contacts(vid):
    helpers.get_vendor(vid)
    scope_vendor_or_403(vid)
    items = [c for c in db.contacts.values() if c["vendor_id"] == vid]
    page, limit, offset, total = paginate(items)
    return ok_list([serialize("contact", c) for c in page], limit, offset, total)


@bp.get("/<vid>/reassessment-schedule")
@require_roles("RiskAnalyst", "SecurityApprover", "PlatformAdmin")
def list_schedule(vid):
    helpers.get_vendor(vid)
    items = [s for s in db.schedules.values() if s["vendor_id"] == vid]
    kind = request.args.get("kind")
    if kind is not None:
        items = [s for s in items if s["kind"] == kind]
    page, limit, offset, total = paginate(items)
    return ok_list([serialize("schedule", s) for s in page], limit, offset, total)
