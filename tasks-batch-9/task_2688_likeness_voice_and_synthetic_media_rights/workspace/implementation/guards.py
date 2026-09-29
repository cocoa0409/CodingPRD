"""Reusable rungs of the global rejection-precedence ladder (PRD 2.10)."""

import calc
import services
from core import db, fail, now


# ---------------------------------------------------- existence rung helpers

def need_talent(talent_id):
    row = db.talents.get(talent_id)
    if row is None:
        fail("ERR_TALENT_NOT_FOUND", "no talent %s" % talent_id)
    return row


def need_estate_authority(authority_id):
    row = db.estate_authorities.get(authority_id)
    if row is None:
        fail("ERR_ESTATE_AUTHORITY_NOT_FOUND", "no estate authority %s" % authority_id)
    return row


def need_grant(grant_id):
    row = db.consent_grants.get(grant_id)
    if row is None:
        fail("ERR_CONSENT_GRANT_NOT_FOUND", "no consent grant %s" % grant_id)
    return row


def need_asset(asset_id):
    row = db.biometric_assets.get(asset_id)
    if row is None:
        fail("ERR_BIOMETRIC_ASSET_NOT_FOUND", "no biometric asset %s" % asset_id)
    return row


def need_replica(replica_id):
    row = db.digital_replicas.get(replica_id)
    if row is None:
        fail("ERR_DIGITAL_REPLICA_NOT_FOUND", "no digital replica %s" % replica_id)
    return row


def need_performance(performance_id):
    row = db.generated_performances.get(performance_id)
    if row is None:
        fail("ERR_GENERATED_PERFORMANCE_NOT_FOUND",
             "no generated performance %s" % performance_id)
    return row


def need_license(license_id):
    row = db.usage_licenses.get(license_id)
    if row is None:
        fail("ERR_USAGE_LICENSE_NOT_FOUND", "no usage license %s" % license_id)
    return row


def need_case(case_id):
    row = db.infringement_cases.get(case_id)
    if row is None:
        fail("ERR_INFRINGEMENT_CASE_NOT_FOUND", "no infringement case %s" % case_id)
    return row


def need_entry(entry_id):
    row = db.compensation_entries.get(entry_id)
    if row is None:
        fail("ERR_COMPENSATION_ENTRY_NOT_FOUND", "no compensation entry %s" % entry_id)
    return row


# ------------------------------------------------------ reference data rung

def need_profile(state_code):
    profile = calc.profile_for(state_code)
    if profile is None:
        fail("ERR_STATE_LAW_PROFILE_MISSING",
             "no state law profile registered for %s" % state_code)
    return profile


def need_union_initial_floor(grant):
    row, floor = calc.initial_floor(grant)
    if floor is None:
        fail("ERR_UNION_SCHEDULE_MISSING",
             "no applicable union minimum row for this grant")
    return floor


def need_union_per_use_floor(grant, media_type):
    row, floor = calc.per_use_floor(grant, media_type)
    if floor is None:
        fail("ERR_UNION_SCHEDULE_MISSING",
             "no applicable union minimum row for media type %s" % media_type)
    return floor


# ------------------------------------------------------------- ownership rung

def talent_side_ownership(talent, role, user_id):
    """Ownership for replica approval and performance review."""
    if role == "TalentRepresentative":
        if user_id != talent["id"]:
            fail("ERR_NOT_TALENT_REPRESENTATIVE",
                 "caller does not represent this talent")
    elif role == "EstateRepresentative":
        authority = db.estate_authorities.get(user_id)
        if authority is None or authority["status"] != "VERIFIED" \
                or authority["talent_id"] != talent["id"]:
            fail("ERR_NOT_ESTATE_REPRESENTATIVE",
                 "caller does not hold a verified estate authority for this talent")


def countersign_ownership(grant, talent, role, user_id):
    if role == "TalentRepresentative":
        if grant["grantor_kind"] != "TALENT" or talent["life_status"] != "LIVING" \
                or user_id != grant["talent_id"]:
            fail("ERR_NOT_TALENT_REPRESENTATIVE",
                 "this grant is not the caller's to countersign")
    elif role == "EstateRepresentative":
        if grant["grantor_kind"] != "ESTATE" or user_id != grant.get("estate_authority_id"):
            fail("ERR_NOT_ESTATE_REPRESENTATIVE",
                 "this grant is not the caller's to countersign")
        authority = db.estate_authorities.get(user_id)
        if authority is None or authority["status"] != "VERIFIED" \
                or authority["talent_id"] != grant["talent_id"]:
            fail("ERR_NOT_ESTATE_REPRESENTATIVE",
                 "the named estate authority is not verified for this talent")


def revoke_ownership(grant, role, user_id):
    if grant["grantor_kind"] == "TALENT":
        required = grant["talent_id"]
    else:
        required = grant.get("estate_authority_id")
    if role == "TalentRepresentative":
        if user_id != required:
            fail("ERR_NOT_TALENT_REPRESENTATIVE",
                 "this grant is not the caller's to revoke")
    elif role == "EstateRepresentative":
        if user_id != required:
            fail("ERR_NOT_ESTATE_REPRESENTATIVE",
                 "this grant is not the caller's to revoke")
        authority = db.estate_authorities.get(user_id)
        if authority is None or authority["status"] != "VERIFIED" \
                or authority["talent_id"] != grant["talent_id"]:
            fail("ERR_NOT_ESTATE_REPRESENTATIVE",
                 "the caller's estate authority is not verified for this talent")


def licensee_ownership(recorded_user_id, user_id):
    if user_id != recorded_user_id:
        fail("ERR_NOT_LICENSEE_OWNER", "caller is not the recorded licensee")


# --------------------------------------------------------------- posture rungs

def block_frozen(talent):
    if talent["rights_posture"] == "FROZEN":
        fail("ERR_TALENT_RIGHTS_FROZEN", "this talent's rights posture is FROZEN")


def block_restricted(talent):
    if talent["rights_posture"] == "RESTRICTED":
        fail("ERR_TALENT_RIGHTS_RESTRICTED", "this talent's rights posture is RESTRICTED")


def need_verified_estate(talent):
    if talent["life_status"] == "DECEASED" and services.verified_authority(talent["id"]) is None:
        fail("ERR_ESTATE_AUTHORITY_UNVERIFIED",
             "a deceased talent needs a VERIFIED estate authority")


# ----------------------------------------------------------------- safety rungs

def need_postmortem_registration(talent, profile):
    if talent["life_status"] != "DECEASED":
        return
    if profile is not None and profile["postmortem_requires_registration"] \
            and not talent.get("postmortem_registration_number"):
        fail("ERR_POSTMORTEM_REGISTRATION_MISSING",
             "this state requires a post-mortem rights registration number")


def need_live_postmortem_term(talent):
    if talent["life_status"] != "DECEASED":
        return
    expiry = talent.get("postmortem_rights_until")
    if expiry is None or expiry < now():
        fail("ERR_POSTMORTEM_RIGHTS_EXPIRED",
             "the domicile-law post-mortem term is not live")
