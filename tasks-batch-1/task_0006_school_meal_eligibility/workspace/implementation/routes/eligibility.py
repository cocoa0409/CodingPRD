"""EligibilityDetermination routes."""
from flask import Blueprint, request
import db
from response import success_object, success_array, iso_utc, parse_iso_utc
from middleware import require_role
from validation import (
    parse_pagination, get_json_body, enforce_keys, require_str, require_int,
)
from services import (
    common_fields_init, bump_version, get_or_404, sort_by_created_at, paginate, clean, now,
)
from errors import (
    ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_STALE_VERSION,
    ERR_ELIGIBILITY_OVERLAP, raise_err,
)

bp = Blueprint("eligibility", __name__)


VALID_TIERS = {"FREE", "REDUCED", "PAID"}
VALID_SOURCES = {"APPLICATION", "DIRECT_CERTIFICATION", "AUTO_RENEWAL"}


def _check_overlap(household_id, new_from, new_to, exclude_id=None):
    for det in db.eligibility_determinations.values():
        if exclude_id is not None and det["id"] == exclude_id:
            continue
        if det["household_id"] != household_id:
            continue
        a_from = det["_valid_from_dt"]
        a_to = det["_valid_to_dt"]
        if a_from < new_to and new_from < a_to:
            raise_err(ERR_ELIGIBILITY_OVERLAP, "eligibility window overlaps existing determination")


@bp.post("/school-meals/eligibility-determinations")
def create_determination():
    require_role({"SchoolStaff", "DistrictReviewer"})
    body = get_json_body()
    enforce_keys(
        body,
        required={"household_id", "source", "tier", "valid_from_utc", "valid_to_utc"},
        optional={"source_application_id"},
    )
    require_str(body["household_id"], "household_id")
    require_str(body["source"], "source")
    require_str(body["tier"], "tier")
    require_str(body["valid_from_utc"], "valid_from_utc")
    require_str(body["valid_to_utc"], "valid_to_utc")
    if body["source"] not in {"DIRECT_CERTIFICATION", "AUTO_RENEWAL"}:
        # Operator-created determinations may not use APPLICATION source.
        raise_err(ERR_INVALID_REQUEST, "source must be DIRECT_CERTIFICATION or AUTO_RENEWAL for direct creation")
    if body["tier"] not in VALID_TIERS:
        raise_err(ERR_INVALID_REQUEST, "invalid tier")
    try:
        vf = parse_iso_utc(body["valid_from_utc"])
        vt = parse_iso_utc(body["valid_to_utc"])
    except Exception:
        raise_err(ERR_INVALID_REQUEST, "valid_from_utc / valid_to_utc must be ISO 8601 UTC")
    if not (vf < vt):
        raise_err(ERR_INVALID_REQUEST, "valid_from_utc must be < valid_to_utc")

    get_or_404(db.households, body["household_id"], "Household")

    # AUTO_RENEWAL side effect: if prior ACTIVE determination has valid_to_utc <= server_clock_utc, expire it.
    if body["source"] == "AUTO_RENEWAL":
        n = now()
        for det in db.eligibility_determinations.values():
            if det["household_id"] != body["household_id"]:
                continue
            if det["lifecycle_status"] != "ACTIVE":
                continue
            if det["_valid_to_dt"] <= n:
                det["lifecycle_status"] = "EXPIRED"
                bump_version(det)

    _check_overlap(body["household_id"], vf, vt)

    rec = {
        **common_fields_init(),
        "household_id": body["household_id"],
        "source_application_id": body.get("source_application_id"),
        "source": body["source"],
        "tier": body["tier"],
        "lifecycle_status": "ACTIVE",
        "verification_status": "UNVERIFIED",
        "valid_from_utc": iso_utc(vf),
        "valid_to_utc": iso_utc(vt),
        "_valid_from_dt": vf,
        "_valid_to_dt": vt,
    }
    db.eligibility_determinations[rec["id"]] = rec
    return success_object(clean(rec), status=201)


@bp.get("/school-meals/eligibility-determinations/<did>")
def read_determination(did):
    require_role({"Parent", "SchoolStaff", "DistrictReviewer", "USDAAuditor"})
    rec = get_or_404(db.eligibility_determinations, did, "EligibilityDetermination")
    # Parents may only see determinations of their own household.
    from middleware import get_auth
    user_id, role = get_auth()
    if role == "Parent" and user_id != rec["household_id"]:
        from errors import ERR_NOT_RESOURCE_OWNER
        raise_err(ERR_NOT_RESOURCE_OWNER, "parent does not own this determination")
    return success_object(clean(rec))


@bp.get("/school-meals/eligibility-determinations")
def list_determinations():
    require_role({"SchoolStaff", "DistrictReviewer", "USDAAuditor"})
    limit, offset = parse_pagination()
    hh = request.args.get("household_id")
    lifecycle = request.args.get("lifecycle_status")
    src_app = request.args.get("source_application_id")
    items = list(db.eligibility_determinations.values())
    if hh is not None:
        items = [d for d in items if d["household_id"] == hh]
    if lifecycle is not None:
        items = [d for d in items if d["lifecycle_status"] == lifecycle]
    if src_app is not None:
        items = [d for d in items if d.get("source_application_id") == src_app]
    items = sort_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return success_array([clean(r) for r in page], limit=limit, offset=offset, total_count=total)


@bp.post("/school-meals/eligibility-determinations/<did>/verify")
def verify_determination(did):
    require_role({"USDAAuditor"})
    rec = get_or_404(db.eligibility_determinations, did, "EligibilityDetermination")
    body = get_json_body()
    enforce_keys(body, required=set(), optional=set())
    if rec["lifecycle_status"] != "ACTIVE" or rec["verification_status"] != "UNVERIFIED":
        raise_err(ERR_INVALID_STATE, "determination not in ACTIVE/UNVERIFIED state")
    rec["verification_status"] = "VERIFIED"
    bump_version(rec)
    return success_object(clean(rec))


@bp.post("/school-meals/eligibility-determinations/<did>/defer")
def defer_determination(did):
    require_role({"USDAAuditor"})
    rec = get_or_404(db.eligibility_determinations, did, "EligibilityDetermination")
    body = get_json_body()
    enforce_keys(body, required=set(), optional=set())
    if rec["lifecycle_status"] != "ACTIVE" or rec["verification_status"] != "UNVERIFIED":
        raise_err(ERR_INVALID_STATE, "determination not in ACTIVE/UNVERIFIED state")
    rec["verification_status"] = "DEFERRED"
    bump_version(rec)
    return success_object(clean(rec))


@bp.post("/school-meals/eligibility-determinations/<did>/revoke")
def revoke_determination(did):
    require_role({"USDAAuditor"})
    rec = get_or_404(db.eligibility_determinations, did, "EligibilityDetermination")
    body = get_json_body()
    enforce_keys(body, required={"expected_eligibilitydetermination_version"}, optional=set())
    require_int(body["expected_eligibilitydetermination_version"], "expected_eligibilitydetermination_version", min_val=0)
    if rec["lifecycle_status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "determination not in ACTIVE state")
    if body["expected_eligibilitydetermination_version"] != rec["version"]:
        raise_err(ERR_STALE_VERSION, "expected_eligibilitydetermination_version does not match")
    n = now()
    rec["lifecycle_status"] = "REVOKED"
    rec["valid_to_utc"] = iso_utc(n)
    rec["_valid_to_dt"] = n
    bump_version(rec)
    return success_object(clean(rec))
