"""Administrative test-driving endpoints: clock + auto-renewal."""
from flask import Blueprint
import db
from response import success_object, iso_utc, parse_iso_utc
from middleware import require_role
from validation import get_json_body, enforce_keys, require_str
from services import (
    common_fields_init, bump_version, now,
)
from errors import ERR_INVALID_REQUEST, ERR_ELIGIBILITY_OVERLAP, raise_err

bp = Blueprint("admin", __name__)


@bp.post("/school-meals/_clock/set_current_utc")
def set_clock():
    require_role({"PlatformAdmin"})
    body = get_json_body()
    enforce_keys(body, required={"to_iso8601"}, optional=set())
    require_str(body["to_iso8601"], "to_iso8601")
    try:
        dt = parse_iso_utc(body["to_iso8601"])
    except Exception:
        raise_err(ERR_INVALID_REQUEST, "to_iso8601 must be ISO 8601 UTC")
    db.set_clock(dt)
    return success_object({"current_utc": iso_utc(dt)})


@bp.post("/school-meals/_clock/advance_and_expire")
def advance_and_expire():
    require_role({"PlatformAdmin"})
    body = get_json_body()
    enforce_keys(body, required={"to_iso8601"}, optional=set())
    require_str(body["to_iso8601"], "to_iso8601")
    try:
        dt = parse_iso_utc(body["to_iso8601"])
    except Exception:
        raise_err(ERR_INVALID_REQUEST, "to_iso8601 must be ISO 8601 UTC")
    db.set_clock(dt)
    expired_count = 0
    for det in db.eligibility_determinations.values():
        if det["lifecycle_status"] == "ACTIVE" and det["_valid_to_dt"] <= dt:
            det["lifecycle_status"] = "EXPIRED"
            bump_version(det)
            expired_count += 1
    return success_object({"current_utc": iso_utc(dt), "expired_count": expired_count})


@bp.post("/school-meals/_renewal/run_auto_renewal")
def run_auto_renewal():
    require_role({"PlatformAdmin"})
    body = get_json_body()
    enforce_keys(body, required={"school_year", "valid_from_utc", "valid_to_utc"}, optional=set())
    require_str(body["school_year"], "school_year")
    require_str(body["valid_from_utc"], "valid_from_utc")
    require_str(body["valid_to_utc"], "valid_to_utc")
    try:
        vf = parse_iso_utc(body["valid_from_utc"])
        vt = parse_iso_utc(body["valid_to_utc"])
    except Exception:
        raise_err(ERR_INVALID_REQUEST, "valid_from_utc / valid_to_utc must be ISO 8601 UTC")
    if not (vf < vt):
        raise_err(ERR_INVALID_REQUEST, "valid_from_utc must be < valid_to_utc")

    school_year = body["school_year"]

    # Identify candidate households: held an ACTIVE or SUPERSEDED determination
    # in the prior school year AND have no DENIED MealApplication for the
    # supplied school_year. PRD §3.8 says "held ... in the prior school year"
    # — past tense + temporal qualifier — so a determination that was ACTIVE
    # in the prior year but has since transitioned to EXPIRED via the
    # natural expiry sweep still qualifies. (Without this inclusivity the
    # auto-renewal sweep cannot serve its stated operational purpose of
    # renewing households at the START of a new school year, after the prior
    # year's windows have closed.)
    households_with_prior = {}
    for det in db.eligibility_determinations.values():
        if det["lifecycle_status"] in ("ACTIVE", "SUPERSEDED", "EXPIRED"):
            hid = det["household_id"]
            # Track most-recent prior det (latest valid_from) per household.
            prior = households_with_prior.get(hid)
            if prior is None or det["_valid_from_dt"] > prior["_valid_from_dt"]:
                households_with_prior[hid] = det

    denied_in_year = {
        a["household_id"]
        for a in db.meal_applications.values()
        if a["status"] == "DENIED" and a.get("school_year") == school_year
    }

    renewed_ids = []
    for hid, prior_det in households_with_prior.items():
        if hid in denied_in_year:
            continue
        # Overlap check.
        try:
            _check_overlap(hid, vf, vt)
        except Exception:
            # Skip households whose window overlaps — alternatively could raise;
            # PRD says: "subject to validation priority 8 (overlap)". We treat each
            # household independently — overlap on one does not abort the sweep,
            # but the failing household is not renewed.
            continue
        new_det = {
            **common_fields_init(),
            "household_id": hid,
            "source_application_id": None,
            "source": "AUTO_RENEWAL",
            "tier": prior_det["tier"],
            "lifecycle_status": "ACTIVE",
            "verification_status": "UNVERIFIED",
            "valid_from_utc": iso_utc(vf),
            "valid_to_utc": iso_utc(vt),
            "_valid_from_dt": vf,
            "_valid_to_dt": vt,
        }
        db.eligibility_determinations[new_det["id"]] = new_det
        renewed_ids.append(hid)

    return success_object({
        "renewed_count": len(renewed_ids),
        "renewed_household_ids": renewed_ids,
    })


def _check_overlap(household_id, new_from, new_to):
    for det in db.eligibility_determinations.values():
        if det["household_id"] != household_id:
            continue
        a_from = det["_valid_from_dt"]
        a_to = det["_valid_to_dt"]
        if a_from < new_to and new_from < a_to:
            raise_err(ERR_ELIGIBILITY_OVERLAP, "eligibility window overlaps existing determination")
