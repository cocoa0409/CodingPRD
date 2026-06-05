"""PlannedGift endpoints + state machine (§3.8)."""

from flask import Blueprint, request

import db
import errors
import lookup
import models
import response
import util
from middleware import authenticate, require_role

bp = Blueprint("planned_gifts", __name__)

ALL_ROLES = {"GiftAdmin", "CampaignManager", "DonorRelations"}
VEHICLES = {"BEQUEST", "CHARITABLE_TRUST", "LIFE_INSURANCE", "IRA_ROLLOVER"}


@bp.post("/planned-gifts")
def create_planned_gift():
    _, role = authenticate()
    require_role(role, {"DonorRelations"})
    with db.LOCK:
        body = util.get_json_body()
        donor_id = util.req_id(body, "donor_id")
        vehicle = util.req_enum(body, "vehicle", VEHICLES)
        expected_amount_cents = util.req_int(body, "expected_amount_cents", min_val=1)

        lookup.donor(donor_id)

        pg = models.new_record({
            "donor_id": donor_id,
            "vehicle": vehicle,
            "expected_amount_cents": expected_amount_cents,
            "status": "INTENT",
            "realized_gift_id": None,
        }, common=True)
        db.planned_gifts[pg["id"]] = pg
        return response.object_response(models.serialize(pg), status=201)


@bp.get("/planned-gifts/<pid>")
def get_planned_gift(pid):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    with db.LOCK:
        pg = lookup.planned_gift(pid)
        return response.object_response(models.serialize(pg))


@bp.get("/planned-gifts")
def list_planned_gifts():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    with db.LOCK:
        limit, offset = util.parse_pagination()
        donor_id = request.args.get("donor_id")
        realized_gift_id = request.args.get("realized_gift_id")
        status = request.args.get("status")
        rows = list(db.planned_gifts.values())
        if donor_id is not None:
            rows = [p for p in rows if p["donor_id"] == donor_id]
        if realized_gift_id is not None:
            rows = [p for p in rows if p.get("realized_gift_id") == realized_gift_id]
        if status is not None:
            rows = [p for p in rows if p["status"] == status]
        rows = util.sort_by_created(rows)
        page, total = util.paginate(rows, limit, offset)
        return response.array_response(models.serialize_list(page), limit, offset, total)


@bp.post("/planned-gifts/<pid>/confirm")
def confirm_planned_gift(pid):
    _, role = authenticate()
    require_role(role, {"DonorRelations"})
    with db.LOCK:
        pg = lookup.planned_gift(pid)
        if pg["status"] != "INTENT":
            raise errors.invalid_state("Planned gift must be INTENT to confirm.")
        pg["status"] = "CONFIRMED"
        models.touch(pg)
        return response.object_response(models.serialize(pg))


@bp.post("/planned-gifts/<pid>/realize")
def realize_planned_gift(pid):
    _, role = authenticate()
    require_role(role, {"DonorRelations"})
    with db.LOCK:
        pg = lookup.planned_gift(pid)
        body = util.get_json_body()
        campaign_id = util.req_id(body, "campaign_id")
        realized_amount_cents = util.req_int(body, "realized_amount_cents", min_val=1)

        # FK existence (campaign) — path id pg already resolved above.
        campaign = lookup.campaign(campaign_id)

        # State gate (priority 4): must be CONFIRMED.
        if pg["status"] != "CONFIRMED":
            raise errors.invalid_state("Planned gift must be CONFIRMED to realize.")

        # Campaign must be OPEN (priority 7).
        if campaign["status"] != "OPEN":
            raise errors.ApiError(errors.ERR_CAMPAIGN_NOT_OPEN, 409,
                                  "Realizing campaign must be OPEN.")

        # Create a Gift (RECORDED, STOCK) for the donor against the campaign.
        g = models.new_record({
            "donor_id": pg["donor_id"],
            "campaign_id": campaign_id,
            "appeal_id": None,
            "pledge_id": None,
            "amount_cents": realized_amount_cents,
            "payment_method": "STOCK",
            "status": "RECORDED",
            "deductible_amount_cents": 0,
            "benefit_value_cents": 0,
            "acknowledged_at": None,
        }, common=True)
        db.gifts[g["id"]] = g

        pg["realized_gift_id"] = g["id"]
        pg["status"] = "REALIZED"
        models.touch(pg)
        return response.object_response(models.serialize(pg))


@bp.post("/planned-gifts/<pid>/lapse")
def lapse_planned_gift(pid):
    _, role = authenticate()
    require_role(role, {"DonorRelations"})
    with db.LOCK:
        pg = lookup.planned_gift(pid)
        if pg["status"] not in ("INTENT", "CONFIRMED"):
            raise errors.invalid_state("Planned gift must be INTENT or CONFIRMED to lapse.")
        pg["status"] = "LAPSED"
        models.touch(pg)
        return response.object_response(models.serialize(pg))
