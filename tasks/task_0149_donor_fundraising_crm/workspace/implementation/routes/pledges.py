"""Pledge + PledgeInstallment endpoints (GiftAdmin owns mutations; all read)."""

from flask import Blueprint, request

import db
import errors
import lookup
import models
import response
import services
import util
from middleware import authenticate, require_role

bp = Blueprint("pledges", __name__)

ALL_ROLES = {"GiftAdmin", "CampaignManager", "DonorRelations"}
FREQUENCIES = {"ONE_TIME", "MONTHLY", "QUARTERLY", "ANNUAL"}
SCHEDULE_BASES = {"FRONT_LOADED", "BACK_LOADED"}


def _serialize_pledge(p):
    services.recompute_pledge_paid_balance(p)
    services.recompute_installments_due_count(p)
    return models.serialize(p)


@bp.post("/pledges")
def create_pledge():
    _, role = authenticate()
    require_role(role, {"GiftAdmin"})
    with db.LOCK:
        body = util.get_json_body()
        donor_id = util.req_id(body, "donor_id")
        campaign_id = util.req_id(body, "campaign_id")
        total_amount_cents = util.req_int(body, "total_amount_cents", min_val=1)
        installment_count = util.req_int(body, "installment_count", min_val=1, max_val=60)
        frequency = util.req_enum(body, "frequency", FREQUENCIES)
        schedule_basis = util.opt_enum(body, "schedule_basis", SCHEDULE_BASES,
                                       default="FRONT_LOADED")

        # FK existence (donor, then campaign) in declaration order.
        donor = lookup.donor(donor_id)
        campaign = lookup.campaign(campaign_id)

        # Business rules. donor not ARCHIVED.
        if donor["lifecycle_status"] == "ARCHIVED":
            # An archived donor cannot be the donor of record. Treated as a
            # business-referential failure; the spec routes archived-donor
            # gift/pledge creation through INVALID_REQUEST body semantics is not
            # declared, so use ERR_INVALID_REQUEST per the donor-archived note.
            raise errors.invalid_request("Donor is ARCHIVED and cannot pledge.")

        # ONE_TIME requires installment_count == 1 (priority 18).
        if frequency == "ONE_TIME" and installment_count != 1:
            raise errors.ApiError(errors.ERR_INSTALLMENT_FREQUENCY_MISMATCH, 422,
                                  "installment_count must be 1 when frequency is ONE_TIME.")

        # Campaign must be OPEN at pledge creation (priority 7).
        if campaign["status"] != "OPEN":
            raise errors.ApiError(errors.ERR_CAMPAIGN_NOT_OPEN, 409,
                                  "Campaign must be OPEN to create a pledge.")

        p = models.new_record({
            "donor_id": donor_id,
            "campaign_id": campaign_id,
            "total_amount_cents": total_amount_cents,
            "installment_count": installment_count,
            "frequency": frequency,
            "schedule_basis": schedule_basis,
            "status": "ACTIVE",
            "paid_cents": 0,
            "balance_cents": total_amount_cents,
            "installments_due_count": 0,
        }, common=True)
        db.pledges[p["id"]] = p

        # Cascade: mint installments.
        services.mint_installments(p)
        services.recompute_installments_due_count(p)

        return response.object_response(models.serialize(p), status=201)


@bp.get("/pledges/<pid>")
def get_pledge(pid):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    with db.LOCK:
        p = lookup.pledge(pid)
        return response.object_response(_serialize_pledge(p))


@bp.get("/pledges")
def list_pledges():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    with db.LOCK:
        limit, offset = util.parse_pagination()
        donor_id = request.args.get("donor_id")
        campaign_id = request.args.get("campaign_id")
        rows = list(db.pledges.values())
        if donor_id is not None:
            rows = [p for p in rows if p["donor_id"] == donor_id]
        if campaign_id is not None:
            rows = [p for p in rows if p["campaign_id"] == campaign_id]
        rows = util.sort_by_created(rows)
        page, total = util.paginate(rows, limit, offset)
        for p in page:
            services.recompute_pledge_paid_balance(p)
            services.recompute_installments_due_count(p)
        return response.array_response(models.serialize_list(page), limit, offset, total)


@bp.get("/pledges/<pid>/installments")
def list_pledge_installments(pid):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    with db.LOCK:
        lookup.pledge(pid)
        limit, offset = util.parse_pagination()
        rows = [i for i in db.pledge_installments.values() if i["pledge_id"] == pid]
        rows = util.sort_by_created(rows)
        page, total = util.paginate(rows, limit, offset)
        return response.array_response(models.serialize_list(page), limit, offset, total)


@bp.post("/pledges/<pid>/evaluate-delinquency")
def evaluate_delinquency(pid):
    _, role = authenticate()
    require_role(role, {"GiftAdmin"})
    with db.LOCK:
        p = lookup.pledge(pid)
        # State gate: only ACTIVE pledges can move to DELINQUENT.
        if p["status"] != "ACTIVE":
            raise errors.invalid_state("Pledge must be ACTIVE to evaluate delinquency.")
        services.recompute_installments_due_count(p)
        if p["installments_due_count"] >= 1:
            p["status"] = "DELINQUENT"
            models.touch(p)
        return response.object_response(_serialize_pledge(p))


@bp.post("/pledges/<pid>/cancel")
def cancel_pledge(pid):
    _, role = authenticate()
    require_role(role, {"GiftAdmin"})
    with db.LOCK:
        p = lookup.pledge(pid)
        body = util.get_json_body()
        # expected_pledge_version is non-optional on this endpoint (§2.10).
        expected = util.req_int(body, "expected_pledge_version", min_val=0)

        # State gate (priority 4): ACTIVE or DELINQUENT.
        if p["status"] not in ("ACTIVE", "DELINQUENT"):
            raise errors.invalid_state("Pledge must be ACTIVE or DELINQUENT to cancel.")

        # OCC (priority 20): expected must equal current version.
        if expected != p["version"]:
            raise errors.stale_version("expected_pledge_version does not match.")

        # Mark all DUE installments WAIVED.
        for inst in db.pledge_installments.values():
            if inst["pledge_id"] == pid and inst["status"] == "DUE":
                inst["status"] = "WAIVED"
                models.touch(inst)

        p["status"] = "CANCELLED"
        models.touch(p)  # increments version by 1
        return response.object_response(_serialize_pledge(p))


# ---------------------------------------------------------------------------
# PledgeInstallment reads
# ---------------------------------------------------------------------------
@bp.get("/pledge-installments/<iid>")
def get_pledge_installment(iid):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    with db.LOCK:
        inst = lookup.pledge_installment(iid)
        return response.object_response(models.serialize(inst))


@bp.get("/pledge-installments")
def list_all_pledge_installments():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    with db.LOCK:
        limit, offset = util.parse_pagination()
        pledge_id = request.args.get("pledge_id")
        paid_by_gift_id = request.args.get("paid_by_gift_id")
        rows = list(db.pledge_installments.values())
        if pledge_id is not None:
            rows = [i for i in rows if i["pledge_id"] == pledge_id]
        if paid_by_gift_id is not None:
            rows = [i for i in rows if i.get("paid_by_gift_id") == paid_by_gift_id]
        rows = util.sort_by_created(rows)
        page, total = util.paginate(rows, limit, offset)
        return response.array_response(models.serialize_list(page), limit, offset, total)
