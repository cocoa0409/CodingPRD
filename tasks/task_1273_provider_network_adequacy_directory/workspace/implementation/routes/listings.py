"""DirectoryListing endpoints: create (DRAFT), publish, OCC-guarded status PATCH."""

from flask import Blueprint

import db
import errors
import helpers
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from services.cascades import remove_listing_cascade

bp = Blueprint("listings", __name__)

LISTING_STATUSES = {"DRAFT", "LISTED", "UNDER_REVIEW", "SUPPRESSED", "REMOVED"}


def _find_standard(specialty, geo_class):
    for s in db.standards.values():
        if s["specialty"] == specialty and s["geo_class"] == geo_class:
            return s
    return None


@bp.route("/network/listings", methods=["POST"])
@require_roles("NetworkManager")
def create_listing(user_id, role):
    body = helpers.get_body()
    provider_id = helpers.req_str(body, "provider_id")
    location_id = helpers.req_str(body, "location_id")
    specialty = helpers.req_enum(body, "specialty", helpers.SPECIALTIES)
    display_name = helpers.req_str(body, "display_name")
    phone = helpers.req_str(body, "phone")
    accepts = helpers.req_bool(body, "accepts_new_patients")
    office_hours_note = helpers.opt_str(body, "office_hours_note")
    # existence, left-to-right
    if provider_id not in db.providers:
        raise errors.err_provider_not_found()
    if location_id not in db.locations:
        raise errors.err_location_not_found()
    # referential coherence: location.provider_id must equal provider_id
    if db.locations[location_id]["provider_id"] != provider_id:
        raise errors.err_location_provider_mismatch()
    rec = {
        "provider_id": provider_id, "location_id": location_id,
        "specialty": specialty, "display_name": display_name, "phone": phone,
        "accepts_new_patients": accepts, "office_hours_note": office_hours_note,
        "status": "DRAFT", "suppress_reason": "NONE",
        "ghost_strike_count": 0, "has_confirmed_data_error": False,
        "listed_at": None, "suppressed_at": None,
    }
    helpers.stamp_new(rec)
    db.listings[rec["id"]] = rec
    return success_object(helpers.ser_listing(rec), 201)


@bp.route("/network/listings", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_listings(user_id, role):
    limit, offset = helpers.get_pagination()
    provider_id = helpers.query_str("provider_id")
    location_id = helpers.query_str("location_id")
    status = helpers.query_enum("status", LISTING_STATUSES)
    items = list(db.listings.values())
    if provider_id is not None:
        items = [l for l in items if l["provider_id"] == provider_id]
    if location_id is not None:
        items = [l for l in items if l["location_id"] == location_id]
    if status is not None:
        items = [l for l in items if l["status"] == status]
    page, total = helpers.paginate(items, limit, offset)
    return success_list([helpers.ser_listing(l) for l in page], limit, offset, total)


@bp.route("/network/listings/<lid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_listing(user_id, role, lid):
    rec = db.listings.get(lid)
    if rec is None:
        raise errors.err_listing_not_found()
    return success_object(helpers.ser_listing(rec))


@bp.route("/network/listings/<lid>/publish", methods=["POST"])
@require_roles("NetworkManager")
def publish_listing(user_id, role, lid):
    rec = db.listings.get(lid)
    if rec is None:
        raise errors.err_listing_not_found()
    if rec["status"] != "DRAFT":
        raise errors.err_listing_invalid_transition()
    provider = db.providers.get(rec["provider_id"])
    if provider is None:
        raise errors.err_provider_not_found()
    # provider EFFECTIVE check precedes referential checks (PRD §3.2)
    if provider["status"] != "EFFECTIVE":
        raise errors.err_provider_not_effective()
    location = db.locations.get(rec["location_id"])
    if location is None:
        raise errors.err_location_not_found()
    if location["provider_id"] != rec["provider_id"]:
        raise errors.err_location_provider_mismatch()
    region = db.regions.get(location["region_id"])
    if region is None:
        raise errors.err_region_not_found()
    if _find_standard(rec["specialty"], region["geo_class"]) is None:
        raise errors.err_specialty_standard_missing()
    for other in db.listings.values():
        if other["id"] == rec["id"]:
            continue
        if (other["status"] == "LISTED" and other["location_id"] == rec["location_id"]
                and other["specialty"] == rec["specialty"]):
            raise errors.err_listing_already_listed()
    rec["status"] = "LISTED"
    rec["listed_at"] = helpers.now_iso()
    helpers.touch(rec)
    return success_object(helpers.ser_listing(rec))


@bp.route("/network/listings/<lid>", methods=["PATCH"])
@require_roles("NetworkManager")
def patch_listing(user_id, role, lid):
    rec = db.listings.get(lid)
    if rec is None:
        raise errors.err_listing_not_found()
    body = helpers.get_body()
    # OCC check runs before any business logic
    expected = helpers.req_int(body, "expected_listing_version")
    if expected != rec["version"]:
        raise errors.err_stale_listing()
    to_status = helpers.req_enum(body, "to_status", {"LISTED", "SUPPRESSED", "REMOVED"})
    reason = helpers.opt_enum(body, "suppress_reason",
                              {"MANUAL", "ATTESTATION_FAILURE", "GHOST_CONFIRMED", "PROVIDER_SUSPENDED"})
    cur = rec["status"]

    if to_status == "REMOVED":
        if cur not in ("DRAFT", "LISTED", "UNDER_REVIEW", "SUPPRESSED"):
            raise errors.err_listing_invalid_transition()
        rec["status"] = "REMOVED"
        helpers.touch(rec)
        remove_listing_cascade(rec)
        return success_object(helpers.ser_listing(rec))

    if to_status == "SUPPRESSED":
        if cur == "LISTED" and reason == "MANUAL":
            rec["status"] = "SUPPRESSED"
            rec["suppress_reason"] = "MANUAL"
            rec["suppressed_at"] = helpers.now_iso()
            helpers.touch(rec)
            return success_object(helpers.ser_listing(rec))
        if cur == "UNDER_REVIEW" and reason == "GHOST_CONFIRMED":
            rec["status"] = "SUPPRESSED"
            rec["suppress_reason"] = "GHOST_CONFIRMED"
            rec["suppressed_at"] = helpers.now_iso()
            helpers.touch(rec)
            return success_object(helpers.ser_listing(rec))
        raise errors.err_listing_invalid_transition()

    # to_status == "LISTED"
    provider = db.providers.get(rec["provider_id"])
    if cur == "UNDER_REVIEW":
        if reason is not None:
            raise errors.err_listing_invalid_transition()
        if provider is None or provider["status"] != "EFFECTIVE":
            raise errors.err_provider_not_effective()
        rec["status"] = "LISTED"
        rec["ghost_strike_count"] = 0
        helpers.touch(rec)
        return success_object(helpers.ser_listing(rec))
    if cur == "SUPPRESSED":
        if reason is not None:
            raise errors.err_listing_invalid_transition()
        if rec["suppress_reason"] == "PROVIDER_SUSPENDED":
            # not manually reinstatable — restoration happens only via the
            # provider-reinstate cascade (PRD §3.2, unconditional)
            raise errors.err_listing_invalid_transition()
        if provider is None or provider["status"] != "EFFECTIVE":
            raise errors.err_provider_not_effective()
        if rec["suppress_reason"] == "ATTESTATION_FAILURE":
            ok = False
            for r in db.records.values():
                if (r["listing_id"] == rec["id"]
                        and r["status"] in ("ATTESTED", "CORRECTION_REQUESTED")
                        and r["responded_at"] is not None
                        and rec["suppressed_at"] is not None
                        and r["responded_at"] > rec["suppressed_at"]):
                    ok = True
                    break
            if not ok:
                raise errors.err_listing_attestation_unresolved()
        elif rec["suppress_reason"] == "GHOST_CONFIRMED":
            ok = False
            for p in db.probes.values():
                if (p["listing_id"] == rec["id"] and p["status"] == "RECORDED"
                        and p["result"] == "PASS"
                        and p["recorded_at"] is not None
                        and rec["suppressed_at"] is not None
                        and p["recorded_at"] > rec["suppressed_at"]):
                    ok = True
                    break
            if not ok:
                raise errors.err_listing_ghost_unresolved()
        # MANUAL (or NONE): directly reinstatable
        rec["status"] = "LISTED"
        rec["suppress_reason"] = "NONE"
        helpers.touch(rec)
        return success_object(helpers.ser_listing(rec))
    raise errors.err_listing_invalid_transition()
