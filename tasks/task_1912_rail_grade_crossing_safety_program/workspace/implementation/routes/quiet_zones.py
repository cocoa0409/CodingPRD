"""Quiet zone application and membership endpoints (PRD §3.6)."""
import uuid

from flask import Blueprint

from db import now_iso, store
from errors import (
    ApiError,
    ERR_CROSSING_NOT_ACTIVE,
    ERR_CROSSING_NOT_FOUND,
    ERR_DIAGNOSTIC_REVIEW_REQUIRED,
    ERR_EMPTY_ZONE,
    ERR_FORBIDDEN_ROLE,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_LOCALITY_MISMATCH,
    ERR_LOCALITY_NOT_FOUND,
    ERR_QZ_APPLICATION_NOT_FOUND,
    ERR_QZ_MEMBER_NOT_FOUND,
    ERR_SSM_INSUFFICIENT,
    ERR_ZONE_MEMBERSHIP_CONFLICT,
)
from helpers import (
    body_or_empty,
    get_or_404,
    opt_str,
    paginate,
    query_filter,
    reject_unknown,
    req_str,
)
from middleware import auth
from response import ok, ok_list
from services import calcs, domain

bp = Blueprint("quiet_zones", __name__)

ALL_ROLES = ("ProgramAdministrator", "RailSafetyOfficer", "LocalAuthority", "RailroadMaintainer")

QZ_STATUSES = (
    "DRAFT",
    "SUBMITTED",
    "UNDER_REVIEW",
    "APPROVED",
    "SUPPLEMENT_REQUIRED",
    "REJECTED",
    "EFFECTIVE",
    "SUSPENDED",
    "WITHDRAWN",
)

SSM_CODES = (
    "FOUR_QUADRANT_GATES",
    "MEDIANS",
    "CHANNELIZATION",
    "ONE_WAY_STREET",
    "WAYSIDE_HORN",
)

EDITABLE_ZONE_STATES = ("DRAFT", "SUPPLEMENT_REQUIRED")
NON_BLOCKING_ZONE_STATES = ("REJECTED", "WITHDRAWN")


def serialize_zone(z):
    return {
        "id": z["id"],
        "locality_id": z["locality_id"],
        "notes": z["notes"],
        "riwh_pre_ssm": float(z["riwh_pre_ssm"]) if z["riwh_pre_ssm"] is not None else None,
        "riwh_post_ssm": float(z["riwh_post_ssm"]) if z["riwh_post_ssm"] is not None else None,
        "status": z["status"],
        "created_at": z["created_at"],
        "updated_at": z["updated_at"],
        "version": z["version"],
    }


def serialize_member(m):
    return {
        "id": m["id"],
        "quiet_zone_application_id": m["quiet_zone_application_id"],
        "crossing_id": m["crossing_id"],
        "ssm_codes": m["ssm_codes"],
        "membership_status": m["membership_status"],
        "created_at": m["created_at"],
    }


def _member_rows(zone_id):
    return [
        m for m in store.qz_members.values()
        if m["quiet_zone_application_id"] == zone_id and m["membership_status"] == "MEMBER"
    ]


@bp.post("/quiet-zone-applications")
def create_zone():
    user_id, role = auth(["LocalAuthority"])
    body = body_or_empty()
    # Priority 2: a locality may only ever apply for itself.
    if body.get("locality_id") != user_id:
        raise ApiError(ERR_FORBIDDEN_ROLE, 403,
                       "A LocalAuthority may only apply for its own locality")
    # Priority 3: locality FK existence.
    locality_id = body.get("locality_id")
    if isinstance(locality_id, str) and locality_id and locality_id not in store.localities:
        raise ApiError(ERR_LOCALITY_NOT_FOUND, 404, f"Locality {locality_id} does not exist")

    reject_unknown(body, ("locality_id", "notes"))
    locality_id = req_str(body, "locality_id")
    if locality_id not in store.localities:
        raise ApiError(ERR_LOCALITY_NOT_FOUND, 404, f"Locality {locality_id} does not exist")
    notes = opt_str(body, "notes")

    ts = now_iso()
    rec = {
        "id": str(uuid.uuid4()),
        "locality_id": locality_id,
        "notes": notes,
        "riwh_pre_ssm": None,
        "riwh_post_ssm": None,
        "status": "DRAFT",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    store.qz_applications[rec["id"]] = rec
    return ok(serialize_zone(rec), 201)


@bp.get("/quiet-zone-applications")
def list_zones():
    auth(ALL_ROLES)
    locality_f = query_filter("locality_id")
    status_f = query_filter("status")
    items = []
    for z in store.qz_applications.values():
        if locality_f is not None and z["locality_id"] != locality_f:
            continue
        if status_f is not None and z["status"] != status_f:
            continue
        items.append(z)
    items = sorted(items, key=lambda z: z["created_at"])
    page, meta = paginate([serialize_zone(z) for z in items])
    return ok_list(page, meta)


@bp.get("/quiet-zone-applications/<qz_id>")
def get_zone(qz_id):
    auth(ALL_ROLES)
    rec = get_or_404(store.qz_applications, qz_id, ERR_QZ_APPLICATION_NOT_FOUND,
                     f"Quiet zone application {qz_id} does not exist")
    return ok(serialize_zone(rec))


@bp.post("/quiet-zone-applications/<qz_id>/members")
def add_member(qz_id):
    user_id, role = auth(["LocalAuthority"])
    zone = get_or_404(store.qz_applications, qz_id, ERR_QZ_APPLICATION_NOT_FOUND,
                      f"Quiet zone application {qz_id} does not exist")
    body = body_or_empty()

    # Priority 3: body FK crossing_id.
    crossing_id = body.get("crossing_id")
    if isinstance(crossing_id, str) and crossing_id and crossing_id not in store.crossings:
        raise ApiError(ERR_CROSSING_NOT_FOUND, 404, f"Crossing {crossing_id} does not exist")

    # Priority 4: zone must be editable; the crossing must be ACTIVE.
    if zone["status"] not in EDITABLE_ZONE_STATES:
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       f"Zone is not editable in {zone['status']}")
    crossing = store.crossings.get(crossing_id) if isinstance(crossing_id, str) else None
    if crossing is not None and crossing["status"] != "ACTIVE":
        raise ApiError(ERR_CROSSING_NOT_ACTIVE, 409,
                       f"Crossing {crossing_id} is not ACTIVE (current: {crossing['status']})")

    # Priority 7: ownership, request shape, membership conflict.
    if user_id != zone["locality_id"]:
        raise ApiError(ERR_LOCALITY_MISMATCH, 403,
                       "Only the zone's owning locality may manage its members")
    reject_unknown(body, ("crossing_id", "ssm_codes"))
    crossing_id = req_str(body, "crossing_id")
    if crossing_id not in store.crossings:
        raise ApiError(ERR_CROSSING_NOT_FOUND, 404, f"Crossing {crossing_id} does not exist")
    ssm_codes = body.get("ssm_codes")
    if ssm_codes is None:
        ssm_codes = []
    if not isinstance(ssm_codes, list) or any(
        not isinstance(s, str) or s not in SSM_CODES for s in ssm_codes
    ):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       f"Field 'ssm_codes' must be a list of: {', '.join(SSM_CODES)}")

    for other in store.qz_members.values():
        if (
            other["crossing_id"] == crossing_id
            and other["quiet_zone_application_id"] != zone["id"]
            and other["membership_status"] == "MEMBER"
        ):
            other_zone = store.qz_applications.get(other["quiet_zone_application_id"])
            if other_zone is not None and other_zone["status"] not in NON_BLOCKING_ZONE_STATES:
                raise ApiError(ERR_ZONE_MEMBERSHIP_CONFLICT, 409,
                               "The crossing is already a MEMBER of another non-terminal zone")

    rec = {
        "id": str(uuid.uuid4()),
        "quiet_zone_application_id": zone["id"],
        "crossing_id": crossing_id,
        "ssm_codes": list(ssm_codes),
        "membership_status": "MEMBER",
        "created_at": now_iso(),
    }
    store.qz_members[rec["id"]] = rec
    return ok(serialize_member(rec), 201)


@bp.get("/quiet-zone-crossings")
def list_members():
    auth(ALL_ROLES)
    zone_f = query_filter("quiet_zone_application_id")
    crossing_f = query_filter("crossing_id")
    items = []
    for m in store.qz_members.values():
        if zone_f is not None and m["quiet_zone_application_id"] != zone_f:
            continue
        if crossing_f is not None and m["crossing_id"] != crossing_f:
            continue
        items.append(m)
    items = sorted(items, key=lambda m: m["created_at"])
    page, meta = paginate([serialize_member(m) for m in items])
    return ok_list(page, meta)


@bp.get("/quiet-zone-crossings/<member_id>")
def get_member(member_id):
    auth(ALL_ROLES)
    rec = get_or_404(store.qz_members, member_id, ERR_QZ_MEMBER_NOT_FOUND,
                     f"Quiet zone membership {member_id} does not exist")
    return ok(serialize_member(rec))


@bp.delete("/quiet-zone-crossings/<member_id>")
def delete_member(member_id):
    user_id, role = auth(["LocalAuthority"])
    rec = get_or_404(store.qz_members, member_id, ERR_QZ_MEMBER_NOT_FOUND,
                     f"Quiet zone membership {member_id} does not exist")
    zone = store.qz_applications.get(rec["quiet_zone_application_id"])
    # Priority 4: manual removal requires a MEMBER row in an editable zone.
    if rec["membership_status"] != "MEMBER" or zone is None or zone["status"] not in EDITABLE_ZONE_STATES:
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "Members may be removed only while the zone is DRAFT or SUPPLEMENT_REQUIRED")
    # Priority 7: ownership.
    if user_id != zone["locality_id"]:
        raise ApiError(ERR_LOCALITY_MISMATCH, 403,
                       "Only the zone's owning locality may remove members")
    # Removal does not recompute the parent application's pinned risk indices.
    rec["membership_status"] = "REMOVED"
    return "", 204


@bp.post("/quiet-zone-applications/<qz_id>/transition")
def transition_zone(qz_id):
    user_id, role = auth(["LocalAuthority", "RailSafetyOfficer"])
    body = body_or_empty()
    to_status = body.get("to_status")

    # Fixed per-target role admission (priority 2).
    if to_status in ("SUBMITTED", "WITHDRAWN") and role != "LocalAuthority":
        raise ApiError(ERR_FORBIDDEN_ROLE, 403, "Only the owning LocalAuthority may perform this action")
    if to_status in ("UNDER_REVIEW", "SUSPENDED") and role != "RailSafetyOfficer":
        raise ApiError(ERR_FORBIDDEN_ROLE, 403, "Only a RailSafetyOfficer may perform this action")

    zone = get_or_404(store.qz_applications, qz_id, ERR_QZ_APPLICATION_NOT_FOUND,
                      f"Quiet zone application {qz_id} does not exist")
    reject_unknown(body, ("to_status",))
    if not isinstance(to_status, str) or to_status not in QZ_STATUSES:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       f"to_status must be one of: {', '.join(QZ_STATUSES)}")

    if to_status == "SUBMITTED":
        if zone["status"] not in ("DRAFT", "SUPPLEMENT_REQUIRED"):
            raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                           f"Cannot submit from {zone['status']}")
        members = _member_rows(zone["id"])
        for m in members:
            crossing = store.crossings.get(m["crossing_id"])
            if crossing is None or crossing["status"] != "ACTIVE":
                raise ApiError(ERR_CROSSING_NOT_ACTIVE, 409,
                               "Every member crossing must be ACTIVE at submission")
        if user_id != zone["locality_id"]:
            raise ApiError(ERR_LOCALITY_MISMATCH, 403,
                           "Only the zone's owning locality may submit it")
        if len(members) == 0:
            raise ApiError(ERR_EMPTY_ZONE, 422,
                           "A quiet zone may not be submitted with zero member crossings")
        for m in members:
            has_accepted = any(
                r["crossing_id"] == m["crossing_id"] and r["status"] == "ACCEPTED"
                for r in store.reviews.values()
            )
            if not has_accepted:
                raise ApiError(ERR_DIAGNOSTIC_REVIEW_REQUIRED, 409,
                               "Every member crossing must have an ACCEPTED diagnostic review")
        # Risk-pinning moment: compute and pin both indices.
        pre, post = domain.compute_zone_riwh(zone)
        zone["riwh_pre_ssm"] = pre
        zone["riwh_post_ssm"] = post
        zone["status"] = "SUBMITTED"
    elif to_status == "UNDER_REVIEW":
        if zone["status"] != "SUBMITTED":
            raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                           f"Cannot move to UNDER_REVIEW from {zone['status']}")
        zone["status"] = "UNDER_REVIEW"
    elif to_status == "EFFECTIVE":
        if zone["status"] == "APPROVED":
            # Activation by the owning locality.
            if role != "LocalAuthority":
                raise ApiError(ERR_FORBIDDEN_ROLE, 403,
                               "Only the owning LocalAuthority may activate the zone")
            if user_id != zone["locality_id"]:
                raise ApiError(ERR_LOCALITY_MISMATCH, 403,
                               "Only the zone's owning locality may activate it")
            zone["status"] = "EFFECTIVE"
        elif zone["status"] == "SUSPENDED":
            # Reinstatement by an officer after a live risk recompute.
            if role != "RailSafetyOfficer":
                raise ApiError(ERR_FORBIDDEN_ROLE, 403,
                               "Only a RailSafetyOfficer may reinstate the zone")
            recomputed = domain.compute_zone_riwh(zone)
            if recomputed is None or recomputed[1] > calcs.NSRT:
                raise ApiError(ERR_SSM_INSUFFICIENT, 409,
                               "Recomputed riwh_post_ssm exceeds the NSRT or no members remain")
            zone["riwh_pre_ssm"] = recomputed[0]
            zone["riwh_post_ssm"] = recomputed[1]
            zone["status"] = "EFFECTIVE"
        else:
            raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                           f"Cannot move to EFFECTIVE from {zone['status']}")
    elif to_status == "SUSPENDED":
        if zone["status"] != "EFFECTIVE":
            raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                           f"Cannot suspend from {zone['status']}")
        zone["status"] = "SUSPENDED"
    elif to_status == "WITHDRAWN":
        if zone["status"] not in ("DRAFT", "SUBMITTED"):
            raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                           f"Cannot withdraw from {zone['status']}")
        if user_id != zone["locality_id"]:
            raise ApiError(ERR_LOCALITY_MISMATCH, 403,
                           "Only the zone's owning locality may withdraw it")
        zone["status"] = "WITHDRAWN"
    else:
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       f"Cannot move to {to_status} from {zone['status']}")

    zone["version"] += 1
    zone["updated_at"] = now_iso()
    return ok(serialize_zone(zone))


@bp.post("/quiet-zone-applications/<qz_id>/decide")
def decide_zone(qz_id):
    auth(["RailSafetyOfficer"])
    zone = get_or_404(store.qz_applications, qz_id, ERR_QZ_APPLICATION_NOT_FOUND,
                      f"Quiet zone application {qz_id} does not exist")
    body_or_empty()
    if zone["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       f"Decide requires UNDER_REVIEW (current: {zone['status']})")
    # The decision is server-computed from the pinned values, never chosen by
    # the officer.
    zone["status"] = calcs.quiet_zone_decision(zone["riwh_pre_ssm"], zone["riwh_post_ssm"])
    zone["version"] += 1
    zone["updated_at"] = now_iso()
    return ok(serialize_zone(zone))
