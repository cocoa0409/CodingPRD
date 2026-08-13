"""Campaign endpoints (PRD 3.4)."""
from flask import Blueprint, request

import calc
import db
import domain
from errors import ApiError, err_invalid_request, err_invalid_state, \
    err_insufficient
from middleware import require_roles, require_transition_role
from response import success, paginate, sort_created
from serializers import campaign_out, flight_out
from util import clock_today, req_str, parse_date

bp = Blueprint("campaigns", __name__, url_prefix="/api")


def get_campaign_or_404(cid):
    c = db.campaigns.get(cid)
    if c is None:
        raise ApiError("ERR_CAMPAIGN_NOT_FOUND", 404, "Campaign not found")
    return c


@bp.route("/campaigns", methods=["POST"])
def create_campaign():
    require_roles("SalesPlanner")
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_invalid_request("Request body must be a JSON object")

    advertiser_id = body.get("advertiser_id")
    if isinstance(advertiser_id, str) and advertiser_id not in db.advertisers:
        raise ApiError("ERR_ADVERTISER_NOT_FOUND", 404, "Advertiser not found")

    advertiser_id = req_str(body, "advertiser_id")
    name = req_str(body, "name")
    start_date = parse_date(body.get("start_date"), "start_date")
    end_date = parse_date(body.get("end_date"), "end_date")
    if end_date < start_date:
        raise err_invalid_request("end_date must not precede start_date")

    c = db.new_resource()
    c.update({
        "advertiser_id": advertiser_id,
        "name": name,
        "start_date": start_date,
        "end_date": end_date,
        "status": "DRAFT",
        "billing_status": "UNINVOICED",
        "contracted_cents": 0,
        "discount_pct": 0,
        "net_contracted_cents": 0,
        "cancellation_fees_cents": 0,
        "production_charges_cents": 0,
        "delivery_posture": "ON_TRACK",
    })
    db.campaigns[c["id"]] = c
    return success(campaign_out(c), code=201)


@bp.route("/campaigns/<cid>", methods=["GET"])
def get_campaign(cid):
    require_roles("SalesPlanner", "SalesManager", "FinanceAnalyst",
                  "OperationsAuditor")
    c = get_campaign_or_404(cid)
    return success(campaign_out(c))


def _cancel_booked_flight(f, campaign):
    """BOOKED/ART_CLEARED cancellation with tiered fee (PRD 3.5)."""
    days_before = (f["start_date"] - clock_today()).days
    fee = calc.cancellation_fee(f["gross_cents"], days_before)
    f["cancellation_fee_cents"] = fee
    f["status"] = "CANCELLED"
    db.touch(f)
    campaign["cancellation_fees_cents"] += fee


@bp.route("/campaigns/<cid>", methods=["PUT"])
def update_campaign(cid):
    user_id, role = require_roles("SalesPlanner", "SalesManager",
                                  "FinanceAnalyst")
    c = get_campaign_or_404(cid)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_invalid_request("Request body must be a JSON object")

    new_status = None
    if "status" in body and body["status"] is not None:
        if body["status"] not in ("DRAFT", "SUBMITTED", "APPROVED", "ACTIVE",
                                  "COMPLETED", "CANCELLED"):
            raise err_invalid_request("Unknown campaign status")
        new_status = body["status"]
    new_billing = None
    if "billing_status" in body and body["billing_status"] is not None:
        if body["billing_status"] not in ("UNINVOICED", "INVOICED", "SETTLED"):
            raise err_invalid_request("Unknown billing_status")
        new_billing = body["billing_status"]
    if new_status is None and new_billing is None:
        raise err_invalid_request("Nothing to update")

    advertiser = db.advertisers.get(c["advertiser_id"])

    # --- status dimension ---
    if new_status is not None and new_status != c["status"]:
        transition = (c["status"], new_status)
        actors = {
            ("DRAFT", "SUBMITTED"): ("SalesPlanner",),
            ("SUBMITTED", "APPROVED"): ("SalesManager",),
            ("SUBMITTED", "DRAFT"): ("SalesManager",),
            ("APPROVED", "CANCELLED"): ("SalesManager",),
            ("DRAFT", "CANCELLED"): ("SalesPlanner",),
        }
        if transition not in actors:
            raise err_invalid_state(
                "Campaign cannot transition %s -> %s" % transition)
        require_transition_role(role, actors[transition])

        if transition == ("DRAFT", "SUBMITTED"):
            held = [f for f in domain.campaign_flights(c["id"])
                    if f["status"] == "HELD"]
            if not held:
                raise ApiError("ERR_CAMPAIGN_EMPTY", 409,
                               "Submit requires at least one HELD flight")
        elif transition == ("SUBMITTED", "APPROVED"):
            if advertiser is None or advertiser["status"] != "ACTIVE":
                raise ApiError("ERR_ADVERTISER_NOT_BOOKABLE", 409,
                               "Advertiser is not ACTIVE")
        elif transition == ("DRAFT", "CANCELLED"):
            bad = [f for f in domain.campaign_flights(c["id"])
                   if f["status"] not in ("HELD", "EXPIRED", "RELEASED")]
            if bad:
                raise err_invalid_state(
                    "A DRAFT campaign may be cancelled only when every flight "
                    "is HELD, EXPIRED or RELEASED")

        if new_status == "CANCELLED":
            for f in domain.campaign_flights(c["id"]):
                if f["status"] == "HELD":
                    f["status"] = "RELEASED"
                    db.touch(f)
                elif c["status"] == "APPROVED" \
                        and f["status"] in ("BOOKED", "ART_CLEARED"):
                    _cancel_booked_flight(f, c)
        c["status"] = new_status
        db.touch(c)
        if new_status == "CANCELLED":
            domain.recompute_campaign_ledgers(c)
            if advertiser is not None:
                domain.recompute_exposure(advertiser)

    # --- billing dimension (parallel, PRD 3.4) ---
    if new_billing is not None and new_billing != c["billing_status"]:
        transition = (c["billing_status"], new_billing)
        if transition == ("UNINVOICED", "INVOICED"):
            require_transition_role(role, ("FinanceAnalyst",))
            if c["status"] not in ("ACTIVE", "COMPLETED"):
                raise err_invalid_state(
                    "Invoicing requires campaign status ACTIVE or COMPLETED")
        elif transition == ("INVOICED", "SETTLED"):
            require_transition_role(role, ("FinanceAnalyst",))
            unresolved = False
            for f in domain.campaign_flights(c["id"]):
                for mg in domain.flight_make_goods(f["id"]):
                    if mg["status"] in ("PROPOSED", "APPROVED"):
                        unresolved = True
                        break
                if unresolved:
                    break
            if unresolved:
                raise ApiError("ERR_UNRESOLVED_MAKE_GOODS", 409,
                               "Campaign has make-goods still in PROPOSED or "
                               "APPROVED")
        else:
            raise err_invalid_state(
                "billing_status cannot transition %s -> %s" % transition)
        c["billing_status"] = new_billing
        db.touch(c)

    return success(campaign_out(c))


@bp.route("/campaigns/<cid>/flights", methods=["GET"])
def campaign_flights(cid):
    require_roles("SalesPlanner", "SalesManager", "FinanceAnalyst")
    c = get_campaign_or_404(cid)
    items = [f for f in db.flights.values() if f["campaign_id"] == c["id"]]
    status_filter = request.args.get("status")
    if status_filter is not None:
        items = [f for f in items if f["status"] == status_filter]
    page, meta = paginate(sort_created(items))
    return success([flight_out(f) for f in page], response_type="array",
                   page_meta=meta)
