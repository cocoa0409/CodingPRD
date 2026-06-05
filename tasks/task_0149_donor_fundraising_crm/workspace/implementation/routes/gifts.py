"""Gift endpoints + the gift state machine (acknowledge / receipt / refund)
with the full ledger cascade (PRD §3.3, §3.9)."""

from flask import Blueprint, request

import db
import errors
import lookup
import models
import response
import services
import util
from middleware import authenticate, require_role

bp = Blueprint("gifts", __name__)

ALL_ROLES = {"GiftAdmin", "CampaignManager", "DonorRelations"}
PAYMENT_METHODS = {"CARD", "CHECK", "ACH", "CASH", "STOCK"}
GIFT_STATUSES = {"RECORDED", "ACKNOWLEDGED", "RECEIPTED", "REFUNDED"}


@bp.post("/gifts")
def create_gift():
    _, role = authenticate()
    require_role(role, {"GiftAdmin"})
    with db.LOCK:
        body = util.get_json_body()
        donor_id = util.req_id(body, "donor_id")
        campaign_id = util.req_id(body, "campaign_id")
        amount_cents = util.req_int(body, "amount_cents", min_val=1)
        appeal_id = util.opt_id(body, "appeal_id", default=None)
        pledge_id = util.opt_id(body, "pledge_id", default=None)
        payment_method = util.opt_enum(body, "payment_method", PAYMENT_METHODS,
                                       default="CARD")
        benefit_value_cents = util.opt_int(body, "benefit_value_cents",
                                           default=0, min_val=0)

        # FK existence in declaration order: donor, campaign, appeal, pledge.
        donor = lookup.donor(donor_id)
        campaign = lookup.campaign(campaign_id)
        appeal = lookup.appeal(appeal_id) if appeal_id is not None else None
        pledge = lookup.pledge(pledge_id) if pledge_id is not None else None

        # donor not ARCHIVED.
        if donor["lifecycle_status"] == "ARCHIVED":
            raise errors.invalid_request("Donor is ARCHIVED and cannot receive a gift.")

        # Business rules in the PRD-mandated order:
        # appeal-campaign (p5) -> pledge attribution (p6) -> open gate (p7) -> benefit (p10).
        if appeal is not None and appeal["campaign_id"] != campaign_id:
            raise errors.ApiError(errors.ERR_APPEAL_CAMPAIGN_MISMATCH, 422,
                                  "appeal_id's campaign does not match the gift's campaign.")

        if pledge is not None:
            if pledge["donor_id"] != donor_id or pledge["campaign_id"] != campaign_id:
                raise errors.ApiError(errors.ERR_PLEDGE_ATTRIBUTION_MISMATCH, 422,
                                      "pledge_id donor/campaign does not match the gift.")

        if campaign["status"] != "OPEN":
            raise errors.ApiError(errors.ERR_CAMPAIGN_NOT_OPEN, 409,
                                  "Campaign must be OPEN to record a gift.")

        if benefit_value_cents > amount_cents:
            raise errors.ApiError(errors.ERR_BENEFIT_EXCEEDS_GIFT, 422,
                                  "benefit_value_cents must not exceed amount_cents.")

        g = models.new_record({
            "donor_id": donor_id,
            "campaign_id": campaign_id,
            "appeal_id": appeal_id,
            "pledge_id": pledge_id,
            "amount_cents": amount_cents,
            "payment_method": payment_method,
            "status": "RECORDED",
            "deductible_amount_cents": 0,
            "benefit_value_cents": benefit_value_cents,
            "acknowledged_at": None,
        }, common=True)
        db.gifts[g["id"]] = g
        return response.object_response(models.serialize(g), status=201)


@bp.get("/gifts/<gid>")
def get_gift(gid):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    with db.LOCK:
        g = lookup.gift(gid)
        return response.object_response(models.serialize(g))


@bp.get("/gifts")
def list_gifts():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    with db.LOCK:
        limit, offset = util.parse_pagination()
        donor_id = request.args.get("donor_id")
        campaign_id = request.args.get("campaign_id")
        appeal_id = request.args.get("appeal_id")
        pledge_id = request.args.get("pledge_id")
        status = request.args.get("status")
        rows = list(db.gifts.values())
        if donor_id is not None:
            rows = [g for g in rows if g["donor_id"] == donor_id]
        if campaign_id is not None:
            rows = [g for g in rows if g["campaign_id"] == campaign_id]
        if appeal_id is not None:
            rows = [g for g in rows if g.get("appeal_id") == appeal_id]
        if pledge_id is not None:
            rows = [g for g in rows if g.get("pledge_id") == pledge_id]
        if status is not None:
            rows = [g for g in rows if g["status"] == status]
        rows = util.sort_by_created(rows)
        page, total = util.paginate(rows, limit, offset)
        return response.array_response(models.serialize_list(page), limit, offset, total)


# ---------------------------------------------------------------------------
# Gift state machine
# ---------------------------------------------------------------------------
@bp.post("/gifts/<gid>/acknowledge")
def acknowledge_gift(gid):
    _, role = authenticate()
    require_role(role, {"DonorRelations"})
    with db.LOCK:
        g = lookup.gift(gid)
        donor = db.donors[g["donor_id"]]
        # State gate: gift RECORDED and donor not ARCHIVED.
        if g["status"] != "RECORDED":
            raise errors.invalid_state("Gift must be RECORDED to acknowledge.")
        if donor["lifecycle_status"] == "ARCHIVED":
            raise errors.invalid_state("Donor is ARCHIVED; cannot acknowledge gift.")

        # --- atomic cascade ---
        g["status"] = "ACKNOWLEDGED"
        g["acknowledged_at"] = db.clock_iso()  # §3.4: "the current clock"
        g["deductible_amount_cents"] = services.compute_deductible(
            g["amount_cents"], g["benefit_value_cents"])
        models.touch(g)

        # Acknowledgement(kind=ACKNOWLEDGEMENT)
        ack = models.new_record({
            "gift_id": g["id"],
            "donor_id": g["donor_id"],
            "template_code": "STANDARD",
            "kind": "ACKNOWLEDGEMENT",
            "receipt_number": None,
        }, common=True)
        db.acknowledgements[ack["id"]] = ack

        # Donor aggregates (lifetime -> giving_status -> last_gift_at).
        services.recompute_donor_aggregates(donor)
        # PROSPECT -> ACTIVE on first acknowledgement (last_gift_at now set).
        if donor["lifecycle_status"] == "PROSPECT" and donor["last_gift_at"] is not None:
            donor["lifecycle_status"] = "ACTIVE"
            models.touch(donor)

        # Campaign raised figures.
        campaign = db.campaigns[g["campaign_id"]]
        services.recompute_campaign_raised(campaign)

        # Appeal count.
        if g.get("appeal_id"):
            appeal = db.appeals.get(g["appeal_id"])
            if appeal is not None:
                services.recompute_appeal_count(appeal)

        # Household soft credit.
        if donor.get("household_id"):
            household = db.households.get(donor["household_id"])
            if household is not None:
                services.create_soft_credits(g, donor, household)

        # Pledge allocation.
        if g.get("pledge_id"):
            pledge = db.pledges.get(g["pledge_id"])
            if pledge is not None:
                services.allocate_gift_to_pledge(g, pledge)

        return response.object_response(models.serialize(g))


@bp.post("/gifts/<gid>/receipt")
def receipt_gift(gid):
    _, role = authenticate()
    require_role(role, {"DonorRelations"})
    with db.LOCK:
        g = lookup.gift(gid)
        # State gate: ACKNOWLEDGED.
        if g["status"] != "ACKNOWLEDGED":
            raise errors.invalid_state("Gift must be ACKNOWLEDGED to receipt.")
        # Business rule (p13): deductible must be >= 1.
        if g["deductible_amount_cents"] < 1:
            raise errors.ApiError(errors.ERR_ZERO_DEDUCTIBLE, 422,
                                  "A zero-deductible gift cannot be tax-receipted.")

        g["status"] = "RECEIPTED"
        models.touch(g)

        receipt_number = services.next_receipt_number()
        rcpt = models.new_record({
            "gift_id": g["id"],
            "donor_id": g["donor_id"],
            "template_code": "STANDARD",
            "kind": "RECEIPT",
            "receipt_number": receipt_number,
        }, common=True)
        db.acknowledgements[rcpt["id"]] = rcpt

        return response.object_response(models.serialize(g))


@bp.post("/gifts/<gid>/refund")
def refund_gift(gid):
    _, role = authenticate()
    require_role(role, {"GiftAdmin"})
    with db.LOCK:
        g = lookup.gift(gid)
        body = util.get_json_body()
        # expected_gift_version is non-optional on refund (§2.10).
        expected = util.req_int(body, "expected_gift_version", min_val=0)

        # State gate (priority 4): ACKNOWLEDGED or RECEIPTED.
        if g["status"] not in ("ACKNOWLEDGED", "RECEIPTED"):
            raise errors.invalid_state("Gift must be ACKNOWLEDGED or RECEIPTED to refund.")

        # Business safety (priority 11): no PAID match claim against this gift.
        for mc in db.match_claims.values():
            if mc["gift_id"] == gid and mc["status"] == "PAID":
                raise errors.ApiError(errors.ERR_MATCH_PAID_BLOCKS_REFUND, 409,
                                      "A PAID match claim blocks refund.")

        # OCC (priority 20): expected_gift_version must match.
        if expected != g["version"]:
            raise errors.stale_version("expected_gift_version does not match.")

        # --- compensating cascade ---
        g["status"] = "REFUNDED"
        models.touch(g)

        donor = db.donors[g["donor_id"]]
        services.recompute_donor_aggregates(donor)

        campaign = db.campaigns[g["campaign_id"]]
        services.recompute_campaign_raised(campaign)

        if g.get("appeal_id"):
            appeal = db.appeals.get(g["appeal_id"])
            if appeal is not None:
                services.recompute_appeal_count(appeal)

        if donor.get("household_id"):
            household = db.households.get(donor["household_id"])
            if household is not None:
                services.reverse_soft_credits(g, household)

        if g.get("pledge_id"):
            pledge = db.pledges.get(g["pledge_id"])
            if pledge is not None:
                services.reverse_gift_from_pledge(g, pledge)

        # Cascade unpaid match claims to DENIED.
        for mc in db.match_claims.values():
            if mc["gift_id"] == gid and mc["status"] in ("SUBMITTED", "APPROVED"):
                mc["status"] = "DENIED"
                models.touch(mc)

        return response.object_response(models.serialize(g))


# ---------------------------------------------------------------------------
# Sub-resource reads
# ---------------------------------------------------------------------------
@bp.get("/gifts/<gid>/acknowledgements")
def list_gift_acknowledgements(gid):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    with db.LOCK:
        lookup.gift(gid)
        limit, offset = util.parse_pagination()
        rows = [a for a in db.acknowledgements.values() if a["gift_id"] == gid]
        rows = util.sort_by_created(rows)
        page, total = util.paginate(rows, limit, offset)
        return response.array_response(models.serialize_list(page), limit, offset, total)


@bp.get("/gifts/<gid>/soft-credits")
def list_gift_soft_credits(gid):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    with db.LOCK:
        lookup.gift(gid)
        limit, offset = util.parse_pagination()
        rows = [sc for sc in db.soft_credits.values() if sc["gift_id"] == gid]
        rows = util.sort_by_created(rows)
        page, total = util.paginate(rows, limit, offset)
        return response.array_response(models.serialize_list(page), limit, offset, total)
