"""NutrientProfile endpoints and lifecycle."""
from flask import Blueprint, request

from db import store, new_id
from errors import (err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_DUPLICATE_CODE, ERR_NUTRIENT_RANGE_INVALID,
                    ERR_SEGREGATION_OF_DUTIES)
from middleware import authorized
from response import ok, paginate
from services import ser_profile, get_or_404, stamp_new, touch, PROFILE_CODES
from util import get_body, require_fields, check_enum, parse_datetime

bp = Blueprint("profiles", __name__)

PROFILE_ROLES = ("REGULATORY_AFFAIRS", "QA_MANAGER", "QUALITY_ANALYST")


def _check_nutrient_ranges(specs):
    for spec in specs:
        lo = spec.get("min_per_100kcal")
        hi = spec.get("max_per_100kcal")
        tgt = spec.get("target_per_100kcal")
        try:
            lo = float(lo)
            hi = float(hi)
            tgt = float(tgt)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, "Nutrient spec bounds must be numbers")
        if lo > hi:
            raise err(ERR_NUTRIENT_RANGE_INVALID,
                      "Nutrient spec min_per_100kcal exceeds max_per_100kcal")
        if not (lo <= tgt <= hi):
            raise err(ERR_NUTRIENT_RANGE_INVALID,
                      "Nutrient spec target_per_100kcal outside [min, max]")


@bp.post("/nutrient-profiles")
@authorized("REGULATORY_AFFAIRS")
def create_profile(_user_id=None, _role=None):
    body = get_body()
    code = body.get("profile_code")
    if isinstance(code, str) and code:
        # Uniqueness: a profile code may be reused only when every existing
        # profile carrying it is APPROVED or terminal (versioning flow).
        for p in store.profiles.values():
            if p["profile_code"] == code and p["status"] in ("DRAFT", "SUBMITTED"):
                raise err(ERR_DUPLICATE_CODE, "profile_code '%s' already exists" % code)
    require_fields(body, ["profile_code", "nutrient_specs", "regulation_ref", "effective_from"])
    check_enum(body["profile_code"], PROFILE_CODES, "profile_code")
    specs = body["nutrient_specs"]
    if not isinstance(specs, list) or len(specs) == 0:
        raise err(ERR_INVALID_REQUEST, "nutrient_specs must contain at least one spec")
    for spec in specs:
        if not isinstance(spec, dict) or not spec.get("nutrient_code"):
            raise err(ERR_INVALID_REQUEST, "Each nutrient_spec requires a nutrient_code")
    effective_from = parse_datetime(body["effective_from"], "effective_from")
    effective_until = None
    if body.get("effective_until") is not None:
        effective_until = parse_datetime(body["effective_until"], "effective_until")
    rec = stamp_new({
        "id": new_id(),
        "profile_code": body["profile_code"],
        "nutrient_specs": specs,
        "regulation_ref": body["regulation_ref"],
        "effective_from": effective_from,
        "effective_until": effective_until,
        "status": "DRAFT",
        "_submitted_by": None,
    })
    store.profiles[rec["id"]] = rec
    return ok(ser_profile(rec), 201)


@bp.get("/nutrient-profiles")
@authorized(*PROFILE_ROLES)
def list_profiles(_user_id=None, _role=None):
    records = list(store.profiles.values())
    status = request.args.get("status")
    code = request.args.get("profile_code")
    if status is not None:
        records = [p for p in records if p["status"] == status]
    if code is not None:
        records = [p for p in records if p["profile_code"] == code]
    return paginate(records, ser_profile)


@bp.get("/nutrient-profiles/<pid>")
@authorized(*PROFILE_ROLES)
def get_profile(pid, _user_id=None, _role=None):
    return ok(ser_profile(get_or_404(store.profiles, pid, "NutrientProfile")))


@bp.post("/nutrient-profiles/<pid>/submit")
@authorized("REGULATORY_AFFAIRS")
def submit_profile(pid, _user_id=None, _role=None):
    rec = get_or_404(store.profiles, pid, "NutrientProfile")
    if rec["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE,
                  "NutrientProfile in status %s cannot be submitted" % rec["status"])
    specs = rec["nutrient_specs"]
    if not specs:
        raise err(ERR_INVALID_REQUEST, "nutrient_specs array must be non-empty")
    _check_nutrient_ranges(specs)
    rec["status"] = "SUBMITTED"
    rec["_submitted_by"] = _user_id
    touch(rec)
    return ok(ser_profile(rec))


@bp.post("/nutrient-profiles/<pid>/approve")
@authorized("REGULATORY_AFFAIRS")
def approve_profile(pid, _user_id=None, _role=None):
    rec = get_or_404(store.profiles, pid, "NutrientProfile")
    if rec["status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE,
                  "NutrientProfile in status %s cannot be approved" % rec["status"])
    if rec.get("_submitted_by") is not None and rec["_submitted_by"] == _user_id:
        raise err(ERR_SEGREGATION_OF_DUTIES,
                  "Approver must differ from the user who submitted the profile")
    if rec["effective_from"] is None:
        from db import now as _now
        rec["effective_from"] = _now()
    rec["status"] = "APPROVED"
    touch(rec)
    # Supersede any other currently APPROVED profile with the same code.
    for other in store.profiles.values():
        if other["id"] != rec["id"] and other["profile_code"] == rec["profile_code"] \
                and other["status"] == "APPROVED":
            other["status"] = "SUPERSEDED"
            other["effective_until"] = rec["effective_from"]
            touch(other)
    return ok(ser_profile(rec))


@bp.post("/nutrient-profiles/<pid>/return-for-revision")
@authorized("REGULATORY_AFFAIRS")
def return_profile(pid, _user_id=None, _role=None):
    rec = get_or_404(store.profiles, pid, "NutrientProfile")
    if rec["status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE,
                  "NutrientProfile in status %s cannot be returned for revision" % rec["status"])
    rec["status"] = "DRAFT"
    touch(rec)
    return ok(ser_profile(rec))


@bp.post("/nutrient-profiles/<pid>/withdraw")
@authorized("REGULATORY_AFFAIRS")
def withdraw_profile(pid, _user_id=None, _role=None):
    rec = get_or_404(store.profiles, pid, "NutrientProfile")
    if rec["status"] not in ("DRAFT", "APPROVED"):
        raise err(ERR_INVALID_STATE,
                  "NutrientProfile in status %s cannot be withdrawn" % rec["status"])
    if rec["status"] == "APPROVED":
        for f in store.formulas.values():
            if f["nutrient_profile_id"] == rec["id"] and f["status"] == "ACTIVE":
                raise err(ERR_INVALID_STATE,
                          "NutrientProfile is referenced by an ACTIVE formula and "
                          "cannot be withdrawn")
    rec["status"] = "WITHDRAWN"
    touch(rec)
    return ok(ser_profile(rec))
