"""ReducedFareCertificate routes."""
from __future__ import annotations

from flask import Blueprint

from ..auth import require_auth
from ..clock import now, parse_iso
from ..common import bump, check_occ, get_json_body, require_fields, stamp_new
from ..errors import ApiError
from ..response import respond
from ..serializers import certificate_view
from ..store import store


bp = Blueprint("certs", __name__, url_prefix="/transit/reduced-fare-certificates")


VALID_PROGRAMS = {"SENIOR", "DISABILITY", "STUDENT"}


def _windows_overlap(a_from, a_until, b_from, b_until) -> bool:
    return a_from <= b_until and b_from <= a_until


def _has_overlap(rider_id: str, program_type: str, valid_from, valid_until, exclude_id: str | None = None) -> bool:
    for cert in store.reduced_fare_certs.values():
        if cert["id"] == exclude_id:
            continue
        if cert.get("rider_id") != rider_id:
            continue
        if cert.get("program_type") != program_type:
            continue
        if cert.get("status") not in ("PENDING", "ACTIVE"):
            continue
        try:
            cf = parse_iso(cert["valid_from"])
            cu = parse_iso(cert["valid_until"])
        except Exception:
            continue
        if _windows_overlap(valid_from, valid_until, cf, cu):
            return True
    return False


@bp.post("")
@require_auth("AgencyOfficer")
def create_certificate():
    body = get_json_body()
    require_fields(body, "rider_id", "program_type", "valid_from", "valid_until")
    rider_id = body["rider_id"]
    program_type = body["program_type"]
    if program_type not in VALID_PROGRAMS:
        raise ApiError("ERR_VALIDATION", "invalid program_type")
    try:
        valid_from = parse_iso(body["valid_from"])
        valid_until = parse_iso(body["valid_until"])
    except ValueError as exc:
        raise ApiError("ERR_VALIDATION", str(exc))
    if not (valid_until > valid_from):
        raise ApiError("ERR_CERTIFICATE_WINDOW_OVERLAP", "valid_until must be strictly after valid_from")

    with store.lock:
        if rider_id not in store.riders:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "Rider not found")
        if _has_overlap(rider_id, program_type, valid_from, valid_until):
            raise ApiError("ERR_CERTIFICATE_WINDOW_OVERLAP", "Overlap with existing certificate")
        cert = {
            "rider_id": rider_id,
            "program_type": program_type,
            "valid_from": body["valid_from"],
            "valid_until": body["valid_until"],
            "status": "PENDING",
        }
        stamp_new(cert)
        store.reduced_fare_certs[cert["id"]] = cert
    return respond(certificate_view(cert), 201)


@bp.post("/<cert_id>/approve")
@require_auth("AgencyOfficer")
def approve_certificate(cert_id: str):
    body = get_json_body()
    with store.lock:
        cert = store.reduced_fare_certs.get(cert_id)
        if cert is None:
            raise ApiError("ERR_NOT_FOUND", "Certificate not found")
        if cert["status"] != "PENDING":
            raise ApiError("ERR_INVALID_STATE", "Certificate is not PENDING")
        check_occ(cert, body.get("version"))
        try:
            vu = parse_iso(cert["valid_until"])
            vf = parse_iso(cert["valid_from"])
        except ValueError:
            raise ApiError("ERR_INVALID_STATE", "Certificate has invalid date fields")
        if not (vu > now()):
            raise ApiError("ERR_INVALID_STATE", "valid_until must be strictly after now()")
        # Confirm no other ACTIVE cert of the same program_type for this rider with an overlapping window.
        for other in store.reduced_fare_certs.values():
            if other["id"] == cert_id:
                continue
            if other.get("rider_id") != cert["rider_id"]:
                continue
            if other.get("program_type") != cert["program_type"]:
                continue
            if other.get("status") != "ACTIVE":
                continue
            try:
                of = parse_iso(other["valid_from"])
                ou = parse_iso(other["valid_until"])
            except Exception:
                continue
            if _windows_overlap(vf, vu, of, ou):
                raise ApiError("ERR_CERTIFICATE_WINDOW_OVERLAP", "Overlap with another active certificate")
        cert["status"] = "ACTIVE"
        bump(cert)
    return respond(certificate_view(cert), 200)


@bp.post("/<cert_id>/revoke")
@require_auth("AgencyOfficer")
def revoke_certificate(cert_id: str):
    body = get_json_body()
    with store.lock:
        cert = store.reduced_fare_certs.get(cert_id)
        if cert is None:
            raise ApiError("ERR_NOT_FOUND", "Certificate not found")
        if cert["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", "Certificate is not ACTIVE")
        check_occ(cert, body.get("version"))
        cert["status"] = "REVOKED"
        bump(cert)
        # Cascade: downgrade REDUCED_FARE cards with no other ACTIVE certificate covering now()
        rider_id = cert["rider_id"]
        current = now()
        for card in store.cards.values():
            if card.get("rider_id") != rider_id:
                continue
            if card.get("discount_class") != "REDUCED_FARE":
                continue
            # Look for another ACTIVE certificate covering now()
            covered = False
            for other in store.reduced_fare_certs.values():
                if other["id"] == cert_id:
                    continue
                if other.get("rider_id") != rider_id:
                    continue
                if other.get("status") != "ACTIVE":
                    continue
                try:
                    of = parse_iso(other["valid_from"])
                    ou = parse_iso(other["valid_until"])
                except Exception:
                    continue
                if of <= current <= ou:
                    covered = True
                    break
            if not covered:
                card["discount_class"] = "STANDARD"
                bump(card)
    return respond(certificate_view(cert), 200)
