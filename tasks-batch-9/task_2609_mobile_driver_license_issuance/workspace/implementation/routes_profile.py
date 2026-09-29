"""Interoperability profile, trust-list snapshots and the logical clock."""

from flask import Blueprint

import derive
import lookup
import serialize
import validate as v
from auth import endpoint
from envelope import ok, ok_list
from errors import ApiError, bad_request
from store import base_row, db, iso, now, set_clock, touch

bp = Blueprint("profile", __name__, url_prefix="/mdl")

STANDARD_VERSIONS = ("ISO_18013_5_2021", "ISO_18013_5_2024", "ISO_18013_7_2024")
IAL_LEVELS = ("IAL1", "IAL1_5", "IAL2")
DEFAULT_AGE_ONLY = ["age_over_18", "age_over_21", "portrait"]


@endpoint(bp, "/interop-profiles", ["POST"], ["SystemAdmin"])
def create_interop_profile():
    body = v.body()
    profile_code = v.req_str(body, "profile_code", min_len=3, max_len=24)
    standard_version = v.req_enum(body, "standard_version", STANDARD_VERSIONS)
    accepted_issuer_states = v.opt_array_str(body, "accepted_issuer_states", [])
    required_assurance_level = v.opt_enum(
        body, "required_assurance_level", IAL_LEVELS, "IAL2"
    )
    max_devices = v.opt_int(body, "max_devices_per_holder", 2, minimum=1)
    max_active = v.opt_int(body, "max_active_credentials_per_holder", 2, minimum=1)
    proofing_validity_days = v.opt_int(body, "proofing_validity_days", 180, minimum=1)
    revocation_freshness_seconds = v.opt_int(
        body, "revocation_freshness_seconds", 300, minimum=0
    )
    age_only = v.opt_array_str(body, "age_only_allowed_elements", DEFAULT_AGE_ONLY)

    for existing in db.interop_profiles.values():
        if existing["profile_code"] == profile_code:
            raise bad_request("profile_code must be unique across all profiles.")

    row = base_row("InteropProfile")
    row["profile_code"] = profile_code
    row["standard_version"] = standard_version
    row["accepted_issuer_states"] = accepted_issuer_states
    row["required_assurance_level"] = required_assurance_level
    row["max_devices_per_holder"] = max_devices
    row["max_active_credentials_per_holder"] = max_active
    row["proofing_validity_days"] = proofing_validity_days
    row["revocation_freshness_seconds"] = revocation_freshness_seconds
    row["age_only_allowed_elements"] = age_only
    row["pending_republish_count"] = 0
    row["is_active"] = True
    db.interop_profiles[row["id"]] = row
    return ok(serialize.dump(row), 201)


@endpoint(bp, "/interop-profiles/<profile_id>", ["GET"],
          ["SystemAdmin", "CredentialAdjudicator", "VerifierOperator", "PrivacyAuditor"])
def read_interop_profile(profile_id):
    row = lookup.profile(profile_id)
    return ok(serialize.dump(row))


@endpoint(bp, "/interop-profiles/<profile_id>/trust-list-snapshots", ["GET"],
          ["SystemAdmin", "VerifierOperator", "PrivacyAuditor"])
def list_trust_list_snapshots(profile_id):
    limit, offset = v.pagination()
    stale = v.q_bool("revocation_pointer_stale")
    row = lookup.profile(profile_id)
    rows = [s for s in db.snapshots.values() if s["interop_profile_id"] == row["id"]]
    if stale is not None:
        rows = [s for s in rows if s["revocation_pointer_stale"] is stale]
    rows = sorted(rows, key=lambda s: s["snapshot_sequence"])
    return ok_list(serialize.dump_many(rows), limit, offset)


@endpoint(bp, "/trust-list-snapshots", ["POST"], ["SystemAdmin"])
def publish_trust_list_snapshot():
    body = v.body()
    profile_id = v.req_str(body, "interop_profile_id")
    effective_from = v.req_dt(body, "effective_from")
    effective_until = v.req_dt(body, "effective_until")
    v.interval(effective_from, effective_until, "effective_from", "effective_until")
    expected_version = v.req_int(body, "expected_interop_profile_version")

    profile = lookup.profile(profile_id)

    if expected_version != profile["version"]:
        raise ApiError("ERR_STALE_INTEROP_VERSION")

    siblings = [s for s in db.snapshots.values()
                if s["interop_profile_id"] == profile["id"]]
    if siblings:
        newest = sorted(siblings, key=lambda s: s["snapshot_sequence"])[-1]
        boundary = newest["effective_until"]
        if effective_from < boundary:
            raise ApiError("ERR_TRUST_LIST_WINDOW_OVERLAP")
        if effective_from > boundary:
            raise ApiError("ERR_TRUST_LIST_WINDOW_GAP")
        sequence = newest["snapshot_sequence"] + 1
    else:
        sequence = 1

    row = base_row("TrustListSnapshot")
    row["interop_profile_id"] = profile["id"]
    row["snapshot_sequence"] = sequence
    row["effective_from"] = effective_from
    row["effective_until"] = effective_until
    row["listed_reader_app_count"] = derive.listed_reader_app_count()
    row["revocation_pointer_sequence"] = len(db.revocation_entries)
    row["revocation_pointer_stale"] = False
    row["pending_delta_count"] = 0
    row["standard_version"] = profile["standard_version"]
    row["published_at"] = now()
    db.snapshots[row["id"]] = row

    for entry in db.revocation_entries.values():
        entry["published"] = True

    profile["pending_republish_count"] = 0
    touch(profile)
    return ok(serialize.dump(row), 201)


@endpoint(bp, "/_clock/set_current_utc", ["POST"], ["SystemAdmin"])
def set_current_utc():
    body = v.body()
    value = v.req_dt(body, "to_iso8601")
    set_clock(value)
    return ok({"current_utc": iso(value)})
