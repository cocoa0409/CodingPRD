"""MatchClaim endpoints + state machine (§3.6)."""

from flask import Blueprint, request

import db
import errors
import lookup
import models
import response
import services
import util
from middleware import authenticate, require_role

bp = Blueprint("match_claims", __name__)

ALL_ROLES = {"GiftAdmin", "CampaignManager", "DonorRelations"}
HARD_STATUSES = {"ACKNOWLEDGED", "RECEIPTED"}


@bp.post("/match-claims")
def create_match_claim():
    _, role = authenticate()
    require_role(role, {"GiftAdmin"})
    with db.LOCK:
        body = util.get_json_body()
        gift_id = util.req_id(body, "gift_id")
        # FK existence.
        gift = lookup.gift(gift_id)

        # State gate: gift must be ACKNOWLEDGED or RECEIPTED.
        if gift["status"] not in HARD_STATUSES:
            raise errors.invalid_state("Gift must be ACKNOWLEDGED or RECEIPTED for a match claim.")

        donor = db.donors[gift["donor_id"]]
        employer_id = donor.get("employer_id")
        # Eligibility (priority 12): donor has employer + amount >= min_gift_cents.
        if employer_id is None:
            raise errors.ApiError(errors.ERR_GIFT_INELIGIBLE_FOR_MATCH, 422,
                                  "Donor has no matching-gift employer.")
        employer = db.employers.get(employer_id)
        if employer is None:
            raise errors.ApiError(errors.ERR_GIFT_INELIGIBLE_FOR_MATCH, 422,
                                  "Donor's employer no longer exists.")
        if gift["amount_cents"] < employer["min_gift_cents"]:
            raise errors.ApiError(errors.ERR_GIFT_INELIGIBLE_FOR_MATCH, 422,
                                  "Gift amount is below the employer's minimum for matching.")

        requested = services.compute_requested_match(gift, employer)
        mc = models.new_record({
            "gift_id": gift_id,
            "employer_id": employer_id,
            "requested_amount_cents": requested,
            "matched_amount_cents": 0,
            "status": "SUBMITTED",
        }, common=True)
        db.match_claims[mc["id"]] = mc
        return response.object_response(models.serialize(mc), status=201)


@bp.get("/match-claims/<mid>")
def get_match_claim(mid):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    with db.LOCK:
        mc = lookup.match_claim(mid)
        return response.object_response(models.serialize(mc))


@bp.get("/match-claims")
def list_match_claims():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    with db.LOCK:
        limit, offset = util.parse_pagination()
        gift_id = request.args.get("gift_id")
        employer_id = request.args.get("employer_id")
        status = request.args.get("status")
        rows = list(db.match_claims.values())
        if gift_id is not None:
            rows = [m for m in rows if m["gift_id"] == gift_id]
        if employer_id is not None:
            rows = [m for m in rows if m["employer_id"] == employer_id]
        if status is not None:
            rows = [m for m in rows if m["status"] == status]
        rows = util.sort_by_created(rows)
        page, total = util.paginate(rows, limit, offset)
        return response.array_response(models.serialize_list(page), limit, offset, total)


@bp.post("/match-claims/<mid>/approve")
def approve_match_claim(mid):
    _, role = authenticate()
    require_role(role, {"GiftAdmin"})
    with db.LOCK:
        mc = lookup.match_claim(mid)
        if mc["status"] != "SUBMITTED":
            raise errors.invalid_state("Claim must be SUBMITTED to approve.")
        gift = db.gifts[mc["gift_id"]]
        if gift["status"] not in HARD_STATUSES:
            raise errors.invalid_state("Claim's gift must be ACKNOWLEDGED or RECEIPTED.")
        mc["status"] = "APPROVED"
        models.touch(mc)
        return response.object_response(models.serialize(mc))


@bp.post("/match-claims/<mid>/deny")
def deny_match_claim(mid):
    _, role = authenticate()
    require_role(role, {"GiftAdmin"})
    with db.LOCK:
        mc = lookup.match_claim(mid)
        if mc["status"] not in ("SUBMITTED", "APPROVED"):
            raise errors.invalid_state("Claim must be SUBMITTED or APPROVED to deny.")
        mc["status"] = "DENIED"
        models.touch(mc)
        return response.object_response(models.serialize(mc))


@bp.post("/match-claims/<mid>/pay")
def pay_match_claim(mid):
    _, role = authenticate()
    require_role(role, {"GiftAdmin"})
    with db.LOCK:
        mc = lookup.match_claim(mid)
        if mc["status"] != "APPROVED":
            raise errors.invalid_state("Claim must be APPROVED to pay.")
        gift = db.gifts[mc["gift_id"]]
        if gift["status"] not in HARD_STATUSES:
            raise errors.invalid_state("Claim's gift must be ACKNOWLEDGED or RECEIPTED to pay.")
        employer = db.employers[mc["employer_id"]]

        matched = services.compute_matched_amount(mc, gift, employer)
        mc["matched_amount_cents"] = matched
        mc["status"] = "PAID"
        models.touch(mc)

        # Recompute campaign with-match total (adds matched dollars).
        campaign = db.campaigns.get(gift["campaign_id"])
        if campaign is not None:
            services.recompute_campaign_raised(campaign)

        return response.object_response(models.serialize(mc))
