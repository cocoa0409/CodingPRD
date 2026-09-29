"""Volunteers, skill claims and availability windows (PRD 3.2)."""
from flask import Blueprint

import calc
import config as C
import domain
import guards as G
import response as R
import serialize as Z
import store as S
from errors import ApiError
from guards import route

bp = Blueprint("volunteers", __name__)

VOLUNTEER_READ_ROLES = [
    C.ROLE_PROGRAM_MANAGER,
    C.ROLE_SCOPING_SPECIALIST,
    C.ROLE_VOLUNTEER,
    C.ROLE_QUALITY_REVIEWER,
]
CHILD_READ_ROLES = [
    C.ROLE_PROGRAM_MANAGER,
    C.ROLE_SCOPING_SPECIALIST,
    C.ROLE_VOLUNTEER,
]
SKILL_CODE_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")


@route(bp, "/volunteers", ["POST"], [C.ROLE_PROGRAM_MANAGER])
def create_volunteer():
    payload = G.body()
    full_name = G.v_str(payload, "full_name", min_len=1, max_len=120)
    email = G.v_str(payload, "email", min_len=1, max_len=320)
    rate = G.v_num(
        payload,
        "professional_rate_usd_per_hour",
        exclusive_min=0,
        maximum="2000.00",
        places=2,
    )
    seniority = G.v_enum(payload, "seniority", C.SENIORITIES)
    weekly_hours_cap = G.v_int(payload, "weekly_hours_cap", minimum=1, maximum=40)
    for existing in S.all_rows("volunteers"):
        if existing["email"] == email:
            raise ApiError("ERR_VALIDATION", "email must be unique")
    row = S.insert(
        "volunteers",
        {
            "full_name": full_name,
            "email": email,
            "professional_rate_usd_per_hour": rate,
            "seniority": seniority,
            "weekly_hours_cap": weekly_hours_cap,
            "credential_verified_at": None,
            "reliability_score": C.RELIABILITY_BASELINE,
            "reliability_score_lifetime": C.RELIABILITY_BASELINE,
            "lifetime_valued_usd": calc.ZERO2,
            "status": "PENDING_VETTING",
            "pause_reason": None,
        },
    )
    return R.created(Z.volunteer(row))


@route(bp, "/volunteers/<volunteer_id>", ["GET"], VOLUNTEER_READ_ROLES)
def get_volunteer(volunteer_id):
    volunteer = G.g07_volunteer(volunteer_id)
    return R.ok(Z.volunteer(volunteer))


@route(bp, "/volunteers/<volunteer_id>/vet", ["POST"], [C.ROLE_PROGRAM_MANAGER])
def vet_volunteer(volunteer_id):
    volunteer = G.g07_volunteer(volunteer_id)
    payload = G.body()
    codes = payload.get("verify_skill_codes")
    if codes is None:
        codes = []
    if not isinstance(codes, list) or any(not isinstance(c, str) for c in codes):
        raise ApiError("ERR_VALIDATION", "verify_skill_codes must be a list of strings")
    if volunteer["status"] != "PENDING_VETTING":
        raise ApiError("ERR_VOLUNTEER_NOT_ACTIVE", "volunteer is not pending vetting")
    now = S.now()
    volunteer["credential_verified_at"] = now
    volunteer["status"] = "ACTIVE"
    volunteer["pause_reason"] = None
    S.touch(volunteer)
    for claim in S.where("skill_profiles", volunteer_id=volunteer["id"]):
        if claim["skill_code"] in codes:
            claim["verified"] = True
            claim["verified_at"] = now
    return R.ok(Z.volunteer(volunteer))


@route(bp, "/volunteers/<volunteer_id>/status", ["PATCH"], [C.ROLE_PROGRAM_MANAGER])
def patch_volunteer_status(volunteer_id):
    volunteer = G.g07_volunteer(volunteer_id)
    payload = G.body()
    to_status = G.v_enum(payload, "to_status", ("ACTIVE", "PAUSED", "DEACTIVATED"))
    pause_reason = G.v_enum(
        payload, "pause_reason", C.VOLUNTEER_PAUSE_REASONS, required=False
    )
    if volunteer["status"] == "PENDING_VETTING":
        raise ApiError("ERR_CREDENTIAL_NOT_VERIFIED", "volunteer is not vetted")
    if volunteer["status"] == "DEACTIVATED":
        raise ApiError("ERR_VOLUNTEER_NOT_ACTIVE", "DEACTIVATED is terminal")
    volunteer["status"] = to_status
    if to_status in ("PAUSED", "DEACTIVATED"):
        volunteer["pause_reason"] = pause_reason or "ADMIN"
    else:
        volunteer["pause_reason"] = None
    S.touch(volunteer)
    if to_status in ("PAUSED", "DEACTIVATED"):
        domain.withdraw_open_offers_of_volunteer(
            volunteer["id"], "VOLUNTEER_PAUSED", bump_failed=True
        )
    return R.ok(Z.volunteer(volunteer))


# --------------------------------------------------------------------------- #
# skill claims
# --------------------------------------------------------------------------- #
@route(
    bp, "/volunteers/<volunteer_id>/skill-profiles", ["POST"], [C.ROLE_VOLUNTEER]
)
def create_skill_profile(volunteer_id):
    volunteer = G.g07_volunteer(volunteer_id)
    G.g15_owns_volunteer(volunteer["id"])
    payload = G.body()
    skill_code = G.v_str(
        payload, "skill_code", min_len=2, max_len=32, charset=SKILL_CODE_CHARS
    )
    proficiency = G.v_int(payload, "proficiency", minimum=1, maximum=5)
    years = G.v_num(payload, "years_experience", minimum=0, maximum=60, places=1)
    G.g46_unique_skill(volunteer["id"], skill_code)
    row = S.insert(
        "skill_profiles",
        {
            "volunteer_id": volunteer["id"],
            "skill_code": skill_code,
            "proficiency": proficiency,
            "years_experience": years,
            "verified": False,
            "verified_at": None,
        },
        versioned=False,
    )
    return R.created(Z.skill_profile(row))


@route(bp, "/volunteers/<volunteer_id>/skill-profiles", ["GET"], CHILD_READ_ROLES)
def list_skill_profiles(volunteer_id):
    volunteer = G.g07_volunteer(volunteer_id)
    rows = S.where("skill_profiles", volunteer_id=volunteer["id"])
    return R.paginate(rows, Z.skill_profile)


# --------------------------------------------------------------------------- #
# availability windows
# --------------------------------------------------------------------------- #
@route(
    bp,
    "/volunteers/<volunteer_id>/availability-windows",
    ["POST"],
    [C.ROLE_VOLUNTEER],
)
def create_availability_window(volunteer_id):
    volunteer = G.g07_volunteer(volunteer_id)
    G.g15_owns_volunteer(volunteer["id"])
    payload = G.body()
    starts_at = G.v_dt(payload, "starts_at")
    ends_at = G.v_dt(payload, "ends_at")
    window_kind = G.v_enum(payload, "window_kind", C.WINDOW_KINDS)
    hours_offered = G.v_num(
        payload, "hours_offered", minimum=0, maximum="400.00", places=2
    )
    G.g19_positive(hours_offered, "hours_offered")
    G.g32_credential_verified(volunteer)
    G.g39_window_inside_cycle(starts_at, ends_at)
    G.g43_no_window_overlap(volunteer["id"], starts_at, ends_at)
    row = S.insert(
        "availability_windows",
        {
            "volunteer_id": volunteer["id"],
            "starts_at": starts_at,
            "ends_at": ends_at,
            "window_kind": window_kind,
            "hours_offered": hours_offered,
        },
        versioned=False,
    )
    return R.created(Z.availability_window(row))


@route(
    bp, "/volunteers/<volunteer_id>/availability-windows", ["GET"], CHILD_READ_ROLES
)
def list_availability_windows(volunteer_id):
    volunteer = G.g07_volunteer(volunteer_id)
    rows = S.where("availability_windows", volunteer_id=volunteer["id"])
    return R.paginate(rows, Z.availability_window)
