"""Certificate profiles and their revocation-list publications (PRD 3.1, 3.8)."""

import datetime

from flask import Blueprint

from db import db, make_record, public, sort_records, touch
from errors import fail
from filters import apply_filters
from middleware import ALL_ROLES, authenticate, json_body, read_only
from response import created, ok, paginated
from services import cascade
from services.lookup import get_profile
from validation import (DCV_METHODS, VALIDATION_TYPES, enum_value, in_range, req_int,
                        req_list, req_str, req_ts, opt_int)

bp = Blueprint("profiles", __name__)

REQUIRED_VETTING_LEVEL = {"DV": "NONE", "OV": "OV", "EV": "EV"}
CRL_OVERLAP = datetime.timedelta(minutes=30)


@bp.route("/ca/certificate-profiles", methods=["POST"])
def create_profile():
    authenticate(("POLICY_ADMIN",))
    body = json_body()
    name = req_str(body, "name", 1, 80)
    validation_type = req_str(body, "validation_type")
    max_validity_days = req_int(body, "max_validity_days")
    dcv_reuse_days = req_int(body, "dcv_reuse_days")
    max_dcv_reuse_count = req_int(body, "max_dcv_reuse_count")
    org_vetting_reuse_days = opt_int(body, "org_vetting_reuse_days", 0)
    allowed = req_list(body, "allowed_dcv_methods")
    required_sct_count = req_int(body, "required_sct_count")
    base_fee_cents = req_int(body, "base_fee_cents")
    crl_trigger_threshold = req_int(body, "crl_trigger_threshold")
    max_crl_validity_hours = req_int(body, "max_crl_validity_hours")

    enum_value(validation_type, VALIDATION_TYPES, "validation_type")
    for method in allowed:
        enum_value(method, DCV_METHODS, "allowed_dcv_methods")

    in_range(max_validity_days, 1, 398, "max_validity_days")
    in_range(dcv_reuse_days, 1, 398, "dcv_reuse_days")
    in_range(max_dcv_reuse_count, 1, 50, "max_dcv_reuse_count")
    if validation_type == "DV":
        in_range(org_vetting_reuse_days, 0, 0, "org_vetting_reuse_days")
    else:
        in_range(org_vetting_reuse_days, 1, 825, "org_vetting_reuse_days")
    in_range(required_sct_count, 0, 5, "required_sct_count")
    in_range(base_fee_cents, 1, 10000000, "base_fee_cents")
    in_range(crl_trigger_threshold, 1, 1000, "crl_trigger_threshold")
    in_range(max_crl_validity_hours, 1, 240, "max_crl_validity_hours")

    if len(allowed) < 1 or len(allowed) > 4 or len(set(allowed)) != len(allowed):
        fail(
            "ERR_INVALID_ARRAY_CONTENT",
            "allowed_dcv_methods must hold between one and four distinct methods.",
        )

    for existing in db.profiles.values():
        if existing["name"].casefold() == name.casefold():
            fail("ERR_PROFILE_NAME_DUPLICATE", "A profile named '%s' already exists." % name)

    record = make_record({
        "name": name,
        "validation_type": validation_type,
        "status": "DRAFT",
        "status_service_posture": "NOMINAL",
        "max_validity_days": max_validity_days,
        "dcv_reuse_days": dcv_reuse_days,
        "max_dcv_reuse_count": max_dcv_reuse_count,
        "org_vetting_reuse_days": org_vetting_reuse_days,
        "allowed_dcv_methods": list(allowed),
        "required_sct_count": required_sct_count,
        "required_vetting_level": REQUIRED_VETTING_LEVEL[validation_type],
        "base_fee_cents": base_fee_cents,
        "crl_trigger_threshold": crl_trigger_threshold,
        "max_crl_validity_hours": max_crl_validity_hours,
        "pending_crl_entry_count": 0,
        "revoked_certificate_count": 0,
        "total_crl_entries_published": 0,
        "last_crl_number": 0,
        "last_crl_this_update": None,
        "last_crl_next_update": None,
        "activated_at": None,
        "retired_at": None,
    })
    db.profiles[record["id"]] = record
    return created(public(record))


@bp.route("/ca/certificate-profiles", methods=["GET"])
def list_profiles():
    read_only(ALL_ROLES)
    records = apply_filters(
        db.profiles.values(),
        {"status": "str", "validation_type": "str", "status_service_posture": "str"},
    )
    return paginated(sort_records(records))


@bp.route("/ca/certificate-profiles/<profile_id>", methods=["GET"])
def get_one_profile(profile_id):
    read_only(ALL_ROLES)
    return ok(public(get_profile(profile_id)))


@bp.route("/ca/certificate-profiles/<profile_id>/activate", methods=["POST"])
def activate_profile(profile_id):
    authenticate(("POLICY_ADMIN",))
    profile = get_profile(profile_id)
    if profile["status"] != "DRAFT":
        fail("ERR_PROFILE_NOT_DRAFT", "Only a DRAFT profile may be activated.")
    profile["status"] = "ACTIVE"
    profile["activated_at"] = db.now()
    touch(profile)
    return ok(public(profile))


@bp.route("/ca/certificate-profiles/<profile_id>/crl-publications", methods=["POST"])
def publish_crl(profile_id):
    user_id, _role = authenticate(("REVOCATION_OFFICER",))
    body = json_body()
    this_update = req_ts(body, "this_update")
    next_update = req_ts(body, "next_update")
    expected_version = req_int(body, "expected_profile_version")

    profile = get_profile(profile_id)

    if expected_version != profile["version"]:
        fail(
            "ERR_STALE_PROFILE_VERSION",
            "Expected profile version %s but found %s."
            % (expected_version, profile["version"]),
        )

    if profile["status"] != "ACTIVE":
        fail("ERR_PROFILE_NOT_ACTIVE", "The profile must be ACTIVE to publish.")

    if next_update <= this_update:
        fail("ERR_INVALID_CRL_WINDOW", "next_update must be strictly after this_update.")
    previous = profile["last_crl_next_update"]
    if previous is not None:
        if this_update > previous - CRL_OVERLAP:
            fail(
                "ERR_CRL_COVERAGE_GAP",
                "this_update must be at or before the previous next_update minus 30 minutes.",
            )
        if next_update <= previous:
            fail(
                "ERR_CRL_WINDOW_NOT_ADVANCING",
                "next_update must be strictly after the previous next_update.",
            )
    span = next_update - this_update
    if span > datetime.timedelta(hours=profile["max_crl_validity_hours"]):
        fail(
            "ERR_CRL_VALIDITY_TOO_LONG",
            "The window may not exceed %s hours." % profile["max_crl_validity_hours"],
        )

    now = db.now()
    drain = [
        c for c in db.certificates.values()
        if c["profile_id"] == profile["id"]
        and c["revocation_status"] == "REVOKED"
        and c["crl_published_at"] is None
    ]
    drain = sorted(drain, key=lambda c: (c["revoked_at"], c["serial_number"]))
    crl_number = profile["last_crl_number"] + 1
    for cert in drain:
        cert["crl_published_at"] = now
        cert["crl_number"] = crl_number
        touch(cert)

    publication = make_record({
        "profile_id": profile["id"],
        "crl_number": crl_number,
        "this_update": this_update,
        "next_update": next_update,
        "entry_count": len(drain),
        "revoked_serials": [c["serial_number"] for c in drain],
        "published_by_user_id": user_id,
    }, versioned=False)
    db.crl_publications[publication["id"]] = publication

    profile["total_crl_entries_published"] += len(drain)
    profile["pending_crl_entry_count"] = 0
    profile["last_crl_number"] = crl_number
    profile["last_crl_this_update"] = this_update
    profile["last_crl_next_update"] = next_update
    touch(profile)
    if profile["status_service_posture"] == "CRL_OVERDUE":
        profile["status_service_posture"] = "NOMINAL"
        touch(profile)
        cascade.release_blocked_requests(profile)

    return created(public(publication))


@bp.route("/ca/certificate-profiles/<profile_id>/crl-publications", methods=["GET"])
def list_crl_publications(profile_id):
    read_only(ALL_ROLES)
    profile = get_profile(profile_id)
    records = [p for p in db.crl_publications.values() if p["profile_id"] == profile["id"]]
    records = sorted(records, key=lambda p: p["crl_number"])
    return paginated(records)
