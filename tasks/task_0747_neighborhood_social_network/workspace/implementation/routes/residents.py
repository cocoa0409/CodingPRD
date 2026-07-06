"""Resident, VerificationRequest, and ResidentMembership endpoints."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, g, request

from clock import CLOCK, iso_format, parse_iso
from db import DB, stamp_new, bump
from errors import (
    InvalidRequest,
    Forbidden,
    NotFound,
    ReferenceNotFound,
    LocationOutsideGeofence,
    InvalidState,
)
from geo import point_inside
from middleware import require_roles
from paging import apply_pagination
from response import success
from services import (
    refresh_neighborhood_derived,
    refresh_resident_trust,
    REJECTION_PENALTY,
)
from validators import as_str, as_number, as_enum


bp = Blueprint("residents", __name__)


PROOF_TYPES = {"UTILITY_BILL", "LEASE", "POSTCARD_CODE", "GEOSTAMP_SELFIE"}
VERIF_STATES = {"SUBMITTED", "IN_REVIEW", "RESUBMISSION_REQUIRED", "APPROVED", "REJECTED", "EXPIRED"}
ALL_ROLES = ("Resident", "Moderator", "BusinessOwner", "AgencyOfficer", "PlatformAdmin")


def _issue_verification(resident_id: str, neighborhood_id: str, proof_type: str, proof_reference: str) -> dict:
    now = CLOCK.now()
    v = {
        "resident_id": resident_id,
        "neighborhood_id": neighborhood_id,
        "proof_type": proof_type,
        "proof_reference": proof_reference,
        "state": "SUBMITTED",
        "reviewer_moderator_id": None,
        "submitted_at": iso_format(now),
        "expires_at": iso_format(now + timedelta(days=14)),
    }
    stamp_new(v)
    DB.verification_requests[v["id"]] = v
    return v


# ------------------------------------------------------------------ Residents

@bp.post("/neighborhood/residents")
@require_roles("PlatformAdmin")
def create_resident():
    payload = request.get_json(silent=True) or {}
    email = as_str(payload, "email")
    display_name = as_str(payload, "display_name")
    home_address_line = as_str(payload, "home_address_line")
    home_lat = as_number(payload, "home_lat")
    home_lng = as_number(payload, "home_lng")
    primary_neighborhood_id = as_str(payload, "primary_neighborhood_id")

    n = DB.neighborhoods.get(primary_neighborhood_id)
    if n is None:
        raise ReferenceNotFound(f"Neighborhood {primary_neighborhood_id} not found")

    # geofence check (priority 151)
    if not point_inside(n, home_lat, home_lng):
        raise LocationOutsideGeofence("home_lat/home_lng falls outside neighborhood geofence")

    r = {
        "email": email.lower(),
        "display_name": display_name,
        "home_address_line": home_address_line,
        "home_lat": home_lat,
        "home_lng": home_lng,
        "primary_neighborhood_id": primary_neighborhood_id,
        "is_moderator": False,
        "trust_score": 100,
        "verification_status": "PENDING",
        "is_suspended": False,
    }
    stamp_new(r)
    DB.residents[r["id"]] = r

    # Auto-issue initial POSTCARD_CODE VerificationRequest
    _issue_verification(r["id"], primary_neighborhood_id, "POSTCARD_CODE", "")

    return success(r, status=201)


@bp.get("/neighborhood/residents/<rid>")
@require_roles(*ALL_ROLES)
def get_resident(rid: str):
    r = DB.residents.get(rid)
    if r is None:
        raise NotFound(f"Resident {rid} not found")
    return success(r)


@bp.get("/neighborhood/residents")
@require_roles("Moderator", "PlatformAdmin")
def list_residents():
    pnid = request.args.get("primary_neighborhood_id")
    rows = list(DB.residents.values())
    if pnid is not None:
        rows = [r for r in rows if r.get("primary_neighborhood_id") == pnid]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    page, meta = apply_pagination(rows)
    return success(page, response_type="array", pagination=meta)


@bp.post("/neighborhood/residents/<rid>/promote-moderator")
@require_roles("PlatformAdmin")
def promote_moderator(rid: str):
    r = DB.residents.get(rid)
    if r is None:
        raise NotFound(f"Resident {rid} not found")
    if not r.get("is_moderator", False):
        r["is_moderator"] = True
        bump(r)
    return success(r)


# ------------------------------------------------------ VerificationRequests

@bp.post("/neighborhood/verification-requests")
@require_roles("Resident", "PlatformAdmin")
def create_verification_request():
    payload = request.get_json(silent=True) or {}
    resident_id = as_str(payload, "resident_id")
    neighborhood_id = as_str(payload, "neighborhood_id")
    proof_type = as_enum(payload, "proof_type", PROOF_TYPES)
    proof_reference = as_str(payload, "proof_reference")

    if DB.residents.get(resident_id) is None:
        raise ReferenceNotFound(f"Resident {resident_id} not found")
    if DB.neighborhoods.get(neighborhood_id) is None:
        raise ReferenceNotFound(f"Neighborhood {neighborhood_id} not found")

    v = _issue_verification(resident_id, neighborhood_id, proof_type, proof_reference)
    return success(v, status=201)


@bp.get("/neighborhood/verification-requests/<vid>")
@require_roles("Resident", "Moderator", "PlatformAdmin")
def get_verification_request(vid: str):
    v = DB.verification_requests.get(vid)
    if v is None:
        raise NotFound(f"VerificationRequest {vid} not found")
    return success(v)


@bp.get("/neighborhood/verification-requests")
@require_roles("Moderator", "PlatformAdmin")
def list_verification_requests():
    rid = request.args.get("resident_id")
    nid = request.args.get("neighborhood_id")
    mid = request.args.get("reviewer_moderator_id")
    state = request.args.get("state")
    rows = list(DB.verification_requests.values())
    if rid is not None:
        rows = [v for v in rows if v["resident_id"] == rid]
    if nid is not None:
        rows = [v for v in rows if v["neighborhood_id"] == nid]
    if mid is not None:
        rows = [v for v in rows if v.get("reviewer_moderator_id") == mid]
    if state is not None:
        rows = [v for v in rows if v["state"] == state]
    rows.sort(key=lambda v: (v["created_at"], v["id"]))
    page, meta = apply_pagination(rows)
    return success(page, response_type="array", pagination=meta)


@bp.post("/neighborhood/verification-requests/<vid>/claim")
@require_roles("Moderator")
def claim_verification(vid: str):
    v = DB.verification_requests.get(vid)
    if v is None:
        raise NotFound(f"VerificationRequest {vid} not found")
    if v["state"] != "SUBMITTED":
        raise InvalidState(f"VerificationRequest.state is {v['state']}, expected SUBMITTED")
    now = CLOCK.now()
    if now >= parse_iso(v["expires_at"]):
        raise InvalidState("VerificationRequest has expired")
    v["state"] = "IN_REVIEW"
    v["reviewer_moderator_id"] = g.user_id
    bump(v)
    return success(v)


@bp.post("/neighborhood/verification-requests/<vid>/request-resubmission")
@require_roles("Moderator")
def request_resubmission(vid: str):
    v = DB.verification_requests.get(vid)
    if v is None:
        raise NotFound(f"VerificationRequest {vid} not found")
    if v["state"] != "IN_REVIEW":
        raise InvalidState(f"VerificationRequest.state is {v['state']}, expected IN_REVIEW")
    if v.get("reviewer_moderator_id") != g.user_id:
        raise Forbidden("Only the claiming moderator may request resubmission")
    v["state"] = "RESUBMISSION_REQUIRED"
    bump(v)
    return success(v)


@bp.post("/neighborhood/verification-requests/<vid>/resubmit")
@require_roles("Resident")
def resubmit_verification(vid: str):
    v = DB.verification_requests.get(vid)
    if v is None:
        raise NotFound(f"VerificationRequest {vid} not found")
    if v["state"] != "RESUBMISSION_REQUIRED":
        raise InvalidState(f"VerificationRequest.state is {v['state']}, expected RESUBMISSION_REQUIRED")
    if v["resident_id"] != g.user_id:
        raise Forbidden("Only the named resident may resubmit")
    now = CLOCK.now()
    if now >= parse_iso(v["expires_at"]):
        raise InvalidState("VerificationRequest has expired")
    payload = request.get_json(silent=True) or {}
    proof_reference = as_str(payload, "proof_reference")
    if "proof_type" in payload:
        pt = as_enum(payload, "proof_type", PROOF_TYPES)
        v["proof_type"] = pt
    v["proof_reference"] = proof_reference
    v["state"] = "IN_REVIEW"
    bump(v)
    return success(v)


@bp.post("/neighborhood/verification-requests/<vid>/approve")
@require_roles("Moderator")
def approve_verification(vid: str):
    v = DB.verification_requests.get(vid)
    if v is None:
        raise NotFound(f"VerificationRequest {vid} not found")
    if v["state"] != "IN_REVIEW":
        raise InvalidState(f"VerificationRequest.state is {v['state']}, expected IN_REVIEW")
    if v.get("reviewer_moderator_id") != g.user_id:
        raise Forbidden("Only the claiming moderator may approve")

    v["state"] = "APPROVED"
    bump(v)

    # Create or update ResidentMembership
    resident_id = v["resident_id"]
    neighborhood_id = v["neighborhood_id"]
    now = iso_format(CLOCK.now())
    existing = None
    for m in DB.resident_memberships.values():
        if m["resident_id"] == resident_id and m["neighborhood_id"] == neighborhood_id:
            existing = m
            break
    if existing is None:
        m = {
            "resident_id": resident_id,
            "neighborhood_id": neighborhood_id,
            "status": "VERIFIED",
            "verified_at": now,
            "source_verification_id": v["id"],
        }
        stamp_new(m)
        DB.resident_memberships[m["id"]] = m
    else:
        existing["status"] = "VERIFIED"
        existing["verified_at"] = now
        existing["source_verification_id"] = v["id"]
        bump(existing)

    r = DB.residents.get(resident_id)
    if r is not None:
        r["verification_status"] = "VERIFIED"
        bump(r)

    # Recompute neighborhood verified_resident_count
    refresh_neighborhood_derived(neighborhood_id)
    return success(v)


@bp.post("/neighborhood/verification-requests/<vid>/reject")
@require_roles("Moderator")
def reject_verification(vid: str):
    v = DB.verification_requests.get(vid)
    if v is None:
        raise NotFound(f"VerificationRequest {vid} not found")
    if v["state"] != "IN_REVIEW":
        raise InvalidState(f"VerificationRequest.state is {v['state']}, expected IN_REVIEW")
    if v.get("reviewer_moderator_id") != g.user_id:
        raise Forbidden("Only the claiming moderator may reject")

    v["state"] = "REJECTED"
    bump(v)

    r = DB.residents.get(v["resident_id"])
    if r is not None:
        r["verification_status"] = "REJECTED"
        bump(r)
        # Trust score recompute picks up the REJECTION_PENALTY
        refresh_resident_trust(r["id"])
    return success(v)


# ----------------------------------------------------- ResidentMembership

@bp.get("/neighborhood/residents/<rid>/memberships")
@require_roles("Resident", "Moderator", "PlatformAdmin")
def list_resident_memberships(rid: str):
    if DB.residents.get(rid) is None:
        raise NotFound(f"Resident {rid} not found")
    rows = [m for m in DB.resident_memberships.values() if m["resident_id"] == rid]
    rows.sort(key=lambda m: (m["created_at"], m["id"]))
    page, meta = apply_pagination(rows)
    return success(page, response_type="array", pagination=meta)


@bp.get("/neighborhood/neighborhoods/<nid>/memberships")
@require_roles("Moderator", "PlatformAdmin")
def list_neighborhood_memberships(nid: str):
    if DB.neighborhoods.get(nid) is None:
        raise NotFound(f"Neighborhood {nid} not found")
    status = request.args.get("status")
    rows = [m for m in DB.resident_memberships.values() if m["neighborhood_id"] == nid]
    if status is not None:
        rows = [m for m in rows if m["status"] == status]
    rows.sort(key=lambda m: (m["created_at"], m["id"]))
    page, meta = apply_pagination(rows)
    return success(page, response_type="array", pagination=meta)


@bp.get("/neighborhood/verification-requests/<vid>/memberships")
@require_roles("Moderator", "PlatformAdmin")
def list_verification_memberships(vid: str):
    if DB.verification_requests.get(vid) is None:
        raise NotFound(f"VerificationRequest {vid} not found")
    rows = [m for m in DB.resident_memberships.values() if m.get("source_verification_id") == vid]
    rows.sort(key=lambda m: (m["created_at"], m["id"]))
    page, meta = apply_pagination(rows)
    return success(page, response_type="array", pagination=meta)
