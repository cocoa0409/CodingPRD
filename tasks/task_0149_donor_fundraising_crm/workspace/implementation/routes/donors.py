"""Donor endpoints + donor lifecycle action endpoints (§3.7)."""

from flask import Blueprint, request

import db
import errors
import lookup
import models
import response
import services
import util
from middleware import authenticate, require_role

bp = Blueprint("donors", __name__)

ALL_ROLES = {"GiftAdmin", "CampaignManager", "DonorRelations"}
LIFECYCLE_STATES = {"PROSPECT", "ACTIVE", "LAPSED", "REACTIVATED", "ARCHIVED"}
GIVING_STATES = {"NONE", "ENTRY", "MID", "MAJOR"}


def _email_exists(email):
    low = email.lower()
    return any(d["email"].lower() == low for d in db.donors.values())


@bp.post("/donors")
def create_donor():
    _, role = authenticate()
    require_role(role, {"CampaignManager", "GiftAdmin"})
    with db.LOCK:
        body = util.get_json_body()
        full_name = util.req_string(body, "full_name", min_len=1, max_len=120)
        email = util.req_string(body, "email", min_len=1, max_len=320)
        household_id = util.opt_id(body, "household_id", default=None)
        employer_id = util.opt_id(body, "employer_id", default=None)
        lapse_threshold_days = util.opt_int(body, "lapse_threshold_days",
                                            default=365, min_val=30, max_val=3650)

        # Existence of body FKs (left-to-right declaration order): household, employer.
        household = None
        if household_id is not None:
            household = lookup.household(household_id)
        if employer_id is not None:
            lookup.employer(employer_id)

        # Uniqueness of email (case-insensitive) — business constraint (p8).
        if _email_exists(email):
            raise errors.ApiError(errors.ERR_DUPLICATE_EMAIL, 409,
                                  "A donor with this email already exists.")

        d = models.new_record({
            "full_name": full_name,
            "email": email,
            "household_id": household_id,
            "employer_id": employer_id,
            "lifecycle_status": "PROSPECT",
            "giving_status": "NONE",
            "lifetime_hard_credit_cents": 0,
            "last_gift_at": None,
            "lapse_threshold_days": lapse_threshold_days,
        }, common=True)
        db.donors[d["id"]] = d

        if household is not None:
            services.recompute_household_member_count(household)

        return response.object_response(models.serialize(d), status=201)


@bp.get("/donors/<did>")
def get_donor(did):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    with db.LOCK:
        d = lookup.donor(did)
        return response.object_response(models.serialize(d))


@bp.get("/donors")
def list_donors():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    with db.LOCK:
        limit, offset = util.parse_pagination()
        household_id = request.args.get("household_id")
        employer_id = request.args.get("employer_id")
        lifecycle_status = request.args.get("lifecycle_status")
        giving_status = request.args.get("giving_status")

        rows = list(db.donors.values())
        if household_id is not None:
            rows = [d for d in rows if d.get("household_id") == household_id]
        if employer_id is not None:
            rows = [d for d in rows if d.get("employer_id") == employer_id]
        if lifecycle_status is not None:
            rows = [d for d in rows if d["lifecycle_status"] == lifecycle_status]
        if giving_status is not None:
            rows = [d for d in rows if d["giving_status"] == giving_status]

        rows = util.sort_by_created(rows)
        page, total = util.paginate(rows, limit, offset)
        return response.array_response(models.serialize_list(page), limit, offset, total)


# ---------------------------------------------------------------------------
# Lifecycle action endpoints (DonorRelations)
# ---------------------------------------------------------------------------
@bp.post("/donors/<did>/flag-lapsed")
def flag_lapsed(did):
    _, role = authenticate()
    require_role(role, {"DonorRelations"})
    with db.LOCK:
        d = lookup.donor(did)
        # State gate (priority 4): must be ACTIVE.
        if d["lifecycle_status"] != "ACTIVE":
            raise errors.invalid_state("Donor must be ACTIVE to be flagged LAPSED.")
        # Business temporal (priority 14): inactivity window met.
        last = d.get("last_gift_at")
        if last is None:
            raise errors.ApiError(errors.ERR_LAPSE_WINDOW_NOT_MET, 409,
                                  "Lapse window not met.")
        last_dt = util.parse_iso_string(last)
        clock = db.logical_now()
        elapsed = clock - last_dt
        if elapsed < util.timedelta_days(d["lapse_threshold_days"]):
            raise errors.ApiError(errors.ERR_LAPSE_WINDOW_NOT_MET, 409,
                                  "Inactivity window not yet met for lapse.")
        # Record the last_gift_at observed at the moment of lapse for the
        # reactivation predicate.
        d["_lapsed_last_gift_at"] = last
        d["lifecycle_status"] = "LAPSED"
        models.touch(d)
        return response.object_response(models.serialize(d))


@bp.post("/donors/<did>/reactivate")
def reactivate(did):
    _, role = authenticate()
    require_role(role, {"DonorRelations"})
    with db.LOCK:
        d = lookup.donor(did)
        if d["lifecycle_status"] != "LAPSED":
            raise errors.invalid_state("Donor must be LAPSED to reactivate.")
        # Qualifying post-lapse gift (priority 16): an ACKNOWLEDGED/RECEIPTED
        # gift created after the last_gift_at recorded at lapse time.
        lapse_marker = d.get("_lapsed_last_gift_at")
        qualifies = False
        for g in db.gifts.values():
            if g["donor_id"] != did:
                continue
            if g["status"] not in services.HARD_STATUSES:
                continue
            if lapse_marker is None or g["created_at"] > lapse_marker:
                qualifies = True
                break
        if not qualifies:
            raise errors.ApiError(errors.ERR_NO_REACTIVATION_GIFT, 409,
                                  "No qualifying post-lapse reactivation gift.")
        d["lifecycle_status"] = "REACTIVATED"
        models.touch(d)
        return response.object_response(models.serialize(d))


@bp.post("/donors/<did>/flag-active")
def flag_active(did):
    _, role = authenticate()
    require_role(role, {"DonorRelations"})
    with db.LOCK:
        d = lookup.donor(did)
        if d["lifecycle_status"] != "REACTIVATED":
            raise errors.invalid_state("Donor must be REACTIVATED to promote to ACTIVE.")
        d["lifecycle_status"] = "ACTIVE"
        models.touch(d)
        return response.object_response(models.serialize(d))


@bp.post("/donors/<did>/archive")
def archive(did):
    _, role = authenticate()
    require_role(role, {"DonorRelations"})
    with db.LOCK:
        d = lookup.donor(did)
        # State gate (priority 4): PROSPECT or LAPSED.
        if d["lifecycle_status"] not in ("PROSPECT", "LAPSED"):
            raise errors.invalid_state("Donor must be PROSPECT or LAPSED to archive.")
        # Business constraint (priority 15): no ACTIVE/DELINQUENT pledge.
        for p in db.pledges.values():
            if p["donor_id"] == did and p["status"] in ("ACTIVE", "DELINQUENT"):
                raise errors.ApiError(errors.ERR_DONOR_HAS_ACTIVE_PLEDGE, 409,
                                      "Donor has an ACTIVE or DELINQUENT pledge.")
        d["lifecycle_status"] = "ARCHIVED"
        models.touch(d)
        return response.object_response(models.serialize(d))
