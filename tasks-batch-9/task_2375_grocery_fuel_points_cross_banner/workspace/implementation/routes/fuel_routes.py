"""Fuel redemptions at the pump and partner settlement batches."""
from decimal import Decimal

from flask import Blueprint

import clock
import db
import middleware
import response
import shape
from errors import ApiError, bad_request
from routes._helpers import invalid_state, listing
from services import calc, core, serializers

bp = Blueprint("fuel", __name__)

AUTHORIZATION_STATUSES = ("AUTHORIZED", "DISPENSED", "VOIDED", "SUPERSEDED")
SETTLEMENT_STATUSES = ("NOT_APPLICABLE", "PENDING", "BATCHED", "SETTLED")
BATCH_STATUSES = ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED")
FUEL_SITE_TYPES = ("OWNED_FUEL_CENTER", "PARTNER_STATION")


# ------------------------------------------------------------ fuel redemptions

@bp.route("/fuel-redemptions", methods=["POST"])
def create_fuel_redemption():
    ctx = middleware.require(("PumpTerminal", "ProgramAdmin"))
    payload = shape.body()
    member_id = shape.req_str(payload, "member_id")
    site_id = shape.req_str(payload, "site_id")
    alt_id_presented = shape.req_str(payload, "alt_id_presented", 1, None)
    points_committed = shape.req_int(payload, "points_committed", 0, None)
    expected_member_version = shape.req_int(payload, "expected_member_version")

    member = core.fetch("members", member_id)
    site = core.fetch("sites", site_id)

    middleware.own_site(ctx, site["id"])

    core.check_version(member, expected_member_version, "member", "ERR_STALE_MEMBER_VERSION")

    core.assert_no_frozen_household(member["id"])

    member_banner = db.banners[member["banner_id"]]
    site_banner = db.banners[site["banner_id"]]
    if member_banner["status"] != "ACTIVE":
        raise ApiError("ERR_BANNER_SUSPENDED", "banner %s is SUSPENDED" % member_banner["id"])
    if site_banner["status"] != "ACTIVE":
        raise ApiError("ERR_BANNER_SUSPENDED", "banner %s is SUSPENDED" % site_banner["id"])

    if site["status"] != "ACTIVE":
        raise ApiError("ERR_SITE_SUSPENDED", "site %s is SUSPENDED" % site["id"])

    cycle = core.require_open_cycle(member_banner["id"])

    if alt_id_presented != member["alt_id"]:
        raise ApiError("ERR_ALT_ID_MISMATCH",
                       "the presented alternate ID does not match the member's alt_id")

    if site["banner_id"] != member["banner_id"] \
            and not core.member_has_active_link_to_banner(member["id"], site["banner_id"]):
        raise ApiError("ERR_CROSS_BANNER_LINK_REQUIRED",
                       "the member holds no ACTIVE linkage to a household of the site's banner")

    if site["site_type"] not in FUEL_SITE_TYPES:
        raise ApiError("ERR_FUEL_SITE_REQUIRED",
                       "fuel may only be authorized at an OWNED_FUEL_CENTER or PARTNER_STATION")

    if points_committed < site_banner["min_points_per_redemption"]:
        raise ApiError("ERR_BELOW_MIN_REDEMPTION",
                       "points_committed is below the banner's min_points_per_redemption of %d"
                       % site_banner["min_points_per_redemption"])

    derived = calc.redemption_authorization(site, site_banner, points_committed)

    if core.available_points(member["id"]) < derived["points_debited_at_auth"]:
        raise ApiError("ERR_INSUFFICIENT_POINTS",
                       "the member's available_points is below the derived debit of %d"
                       % derived["points_debited_at_auth"])

    superseded = [r for r in db.fuel_redemptions.values()
                  if r["member_id"] == member["id"]
                  and r["authorization_status"] == "AUTHORIZED"]

    redemption = core.new_entity()
    redemption.update({
        "member_id": member["id"],
        "site_id": site["id"],
        "settlement_batch_id": None,
        "alt_id_presented": alt_id_presented,
        "points_committed": points_committed,
        "blocks_effective": derived["blocks_effective"],
        "cents_off_per_gallon": derived["cents_off_per_gallon"],
        "points_debited_at_auth": derived["points_debited_at_auth"],
        "gallons_authorized": derived["gallons_authorized"],
        "gallons_dispensed": None,
        "discount_amount_cents": None,
        "authorization_status": "AUTHORIZED",
        "settlement_status": "NOT_APPLICABLE",
        "authorized_at": clock.now(),
        "dispensed_at": None,
    })
    db.fuel_redemptions[redemption["id"]] = redemption

    entry = core.add_entry(member["id"], cycle["id"], "REDEMPTION",
                           -derived["points_debited_at_auth"],
                           "FUEL_REDEMPTION", redemption["id"])
    if entry is not None:
        core.bump(member)

    for other in core.by_created(superseded):
        core.supersede_redemption(other, member, reason_cycle_id=cycle["id"])

    return response.object_response(serializers.fuel_redemption(redemption), 201)


@bp.route("/fuel-redemptions/<redemption_id>", methods=["GET"])
def get_fuel_redemption(redemption_id):
    middleware.require(("ProgramAdmin", "LoyaltyAnalyst", "LoyaltySupervisor",
                        "PumpTerminal", "SettlementClerk", "Member"))
    redemption = core.fetch("fuel_redemptions", redemption_id)
    return response.object_response(serializers.fuel_redemption(redemption))


@bp.route("/fuel-redemptions", methods=["GET"])
def list_fuel_redemptions():
    middleware.require(("ProgramAdmin", "LoyaltyAnalyst", "LoyaltySupervisor",
                        "PumpTerminal", "SettlementClerk"))
    shape.pagination()
    member_id = shape.arg_str("member_id")
    site_id = shape.arg_str("site_id")
    settlement_batch_id = shape.arg_str("settlement_batch_id")
    authorization_status = shape.arg_enum("authorization_status", AUTHORIZATION_STATUSES)
    settlement_status = shape.arg_enum("settlement_status", SETTLEMENT_STATUSES)
    rows = list(db.fuel_redemptions.values())
    if member_id is not None:
        rows = [r for r in rows if r["member_id"] == member_id]
    if site_id is not None:
        rows = [r for r in rows if r["site_id"] == site_id]
    if settlement_batch_id is not None:
        rows = [r for r in rows if r["settlement_batch_id"] == settlement_batch_id]
    if authorization_status is not None:
        rows = [r for r in rows if r["authorization_status"] == authorization_status]
    if settlement_status is not None:
        rows = [r for r in rows if r["settlement_status"] == settlement_status]
    return listing(rows, serializers.fuel_redemption, order=core.order_key)


@bp.route("/fuel-redemptions/<redemption_id>/complete", methods=["POST"])
def complete_fuel_redemption(redemption_id):
    ctx = middleware.require(("PumpTerminal", "ProgramAdmin"))
    payload = shape.body()
    gallons = shape.req_decimal(payload, "gallons_dispensed", 3)
    if gallons <= 0:
        raise bad_request("'gallons_dispensed' must be strictly greater than zero")

    redemption = core.fetch("fuel_redemptions", redemption_id)
    middleware.own_site(ctx, redemption["site_id"])

    if redemption["authorization_status"] != "AUTHORIZED":
        raise invalid_state("only an AUTHORIZED redemption may be completed (current %s)"
                            % redemption["authorization_status"])

    if gallons > redemption["gallons_authorized"]:
        raise ApiError("ERR_GALLONS_EXCEED_AUTHORIZATION",
                       "gallons_dispensed exceeds the authorized volume of %s"
                       % redemption["gallons_authorized"])

    site = db.sites[redemption["site_id"]]
    redemption["gallons_dispensed"] = clock.rhu(gallons, core.GALLON_Q)
    redemption["discount_amount_cents"] = calc.redemption_discount_amount(
        redemption, redemption["gallons_dispensed"])
    redemption["authorization_status"] = "DISPENSED"
    redemption["dispensed_at"] = clock.now()
    if site["site_type"] == "PARTNER_STATION":
        redemption["settlement_status"] = "PENDING"
    core.bump(redemption)
    if site["site_type"] == "PARTNER_STATION":
        core.bump(site)

    return response.object_response(serializers.fuel_redemption(redemption))


@bp.route("/fuel-redemptions/<redemption_id>/void", methods=["POST"])
def void_fuel_redemption(redemption_id):
    ctx = middleware.require(("PumpTerminal", "ProgramAdmin"))
    redemption = core.fetch("fuel_redemptions", redemption_id)
    middleware.own_site(ctx, redemption["site_id"])

    if redemption["authorization_status"] != "AUTHORIZED":
        raise invalid_state("only an AUTHORIZED redemption may be voided (current %s)"
                            % redemption["authorization_status"])

    member = db.members[redemption["member_id"]]
    core.void_redemption(redemption, member)
    return response.object_response(serializers.fuel_redemption(redemption))


# --------------------------------------------------------- settlement batches

_ZERO_TOTALS = {
    "redemption_count": 0,
    "gallons_total": Decimal("0.000"),
    "gross_discount_cents": 0,
    "tier_rate_pct": 0,
    "pre_fee_reimbursement_cents": 0,
    "admin_fee_cents": 0,
    "reimbursement_cents": 0,
}


@bp.route("/settlement-batches", methods=["POST"])
def create_settlement_batch():
    ctx = middleware.require(("SettlementClerk", "ProgramAdmin"))
    payload = shape.body()
    site_id = shape.req_str(payload, "site_id")
    period_start = shape.req_ts(payload, "period_start")
    period_end = shape.req_ts(payload, "period_end")
    if period_start > period_end:
        raise bad_request("'period_start' must be no later than 'period_end'")
    expected_site_version = shape.req_int(payload, "expected_site_version")

    site = core.fetch("sites", site_id)

    middleware.own_site(ctx, site["id"])

    core.check_version(site, expected_site_version, "site", "ERR_STALE_SITE_VERSION")

    if site["status"] != "ACTIVE":
        raise ApiError("ERR_SITE_SUSPENDED", "site %s is SUSPENDED" % site["id"])

    blocking = core.batch_period_overlap(site["id"], period_start, period_end,
                                         statuses=("SUBMITTED", "APPROVED"))
    if blocking:
        raise ApiError("ERR_BATCH_PERIOD_OVERLAP",
                       "batch %s already covers an overlapping period" % blocking[0]["id"])

    # DRAFT batches never block: they are superseded. The open-batch limit is
    # counted AFTER that hypothetical supersession has been applied.
    to_supersede = core.batch_period_overlap(site["id"], period_start, period_end,
                                             statuses=("DRAFT",))
    superseded_ids = set(batch["id"] for batch in to_supersede)
    open_batches = [b for b in db.settlement_batches.values()
                    if b["site_id"] == site["id"]
                    and b["status"] in ("DRAFT", "SUBMITTED")
                    and b["id"] not in superseded_ids]
    if len(open_batches) >= 2:
        raise ApiError("ERR_OPEN_BATCH_LIMIT",
                       "site %s already carries %d open settlement batches"
                       % (site["id"], len(open_batches)))

    if site["site_type"] != "PARTNER_STATION" or not site["partner_code"]:
        raise ApiError("ERR_PARTNER_SITE_REQUIRED",
                       "settlement batches exist only for a PARTNER_STATION with a partner_code")

    for batch in to_supersede:
        batch["status"] = "REJECTED"
        batch["decided_at"] = clock.now()
        core.bump(batch)

    batch = core.new_entity()
    batch.update({
        "site_id": site["id"],
        "period_start": period_start,
        "period_end": period_end,
        "status": "DRAFT",
        "submitted_by_user_id": None,
        "approved_by_user_id": None,
        "submitted_at": None,
        "decided_at": None,
    })
    batch.update(dict(_ZERO_TOTALS))
    db.settlement_batches[batch["id"]] = batch
    core.bump(site)

    return response.object_response(serializers.settlement_batch(batch), 201)


@bp.route("/settlement-batches/<batch_id>", methods=["GET"])
def get_settlement_batch(batch_id):
    middleware.require(("ProgramAdmin", "LoyaltyAnalyst", "LoyaltySupervisor",
                        "SettlementClerk"))
    batch = core.fetch("settlement_batches", batch_id)
    return response.object_response(serializers.settlement_batch(batch))


@bp.route("/settlement-batches", methods=["GET"])
def list_settlement_batches():
    middleware.require(("ProgramAdmin", "LoyaltyAnalyst", "LoyaltySupervisor",
                        "SettlementClerk"))
    shape.pagination()
    site_id = shape.arg_str("site_id")
    status = shape.arg_enum("status", BATCH_STATUSES)
    rows = list(db.settlement_batches.values())
    if site_id is not None:
        rows = [b for b in rows if b["site_id"] == site_id]
    if status is not None:
        rows = [b for b in rows if b["status"] == status]
    return listing(rows, serializers.settlement_batch, order=core.order_key)


@bp.route("/settlement-batches/<batch_id>/submit", methods=["POST"])
def submit_settlement_batch(batch_id):
    ctx = middleware.require(("SettlementClerk", "ProgramAdmin"))
    batch = core.fetch("settlement_batches", batch_id)
    middleware.own_site(ctx, batch["site_id"])

    site = db.sites[batch["site_id"]]
    banner = db.banners[site["banner_id"]]

    if banner["status"] != "ACTIVE":
        raise ApiError("ERR_BANNER_SUSPENDED", "banner %s is SUSPENDED" % banner["id"])
    if site["status"] != "ACTIVE":
        raise ApiError("ERR_SITE_SUSPENDED", "site %s is SUSPENDED" % site["id"])
    if batch["status"] != "DRAFT":
        raise invalid_state("only a DRAFT batch may be submitted (current %s)" % batch["status"])

    claimed = core.settleable_redemptions(site["id"], batch["period_start"],
                                          batch["period_end"])
    if not claimed:
        raise ApiError("ERR_NO_SETTLEABLE_GALLONS",
                       "no PENDING redemption of this site was dispensed inside the period")

    for redemption in claimed:
        redemption["settlement_status"] = "BATCHED"
        redemption["settlement_batch_id"] = batch["id"]
        core.bump(redemption)

    totals = calc.settlement_batch_reimbursement(claimed)
    batch.update(totals)
    batch["status"] = "SUBMITTED"
    batch["submitted_by_user_id"] = ctx.user_id
    batch["submitted_at"] = clock.now()
    core.bump(batch)
    core.bump(site)

    return response.object_response(serializers.settlement_batch(batch))


@bp.route("/settlement-batches/<batch_id>/approve", methods=["POST"])
def approve_settlement_batch(batch_id):
    ctx = middleware.require(("ProgramAdmin",))
    batch = core.fetch("settlement_batches", batch_id)

    if batch["submitted_by_user_id"] is not None \
            and ctx.user_id == batch["submitted_by_user_id"]:
        raise ApiError("ERR_SELF_APPROVAL_FORBIDDEN",
                       "the submitter of a batch may not decide it")
    if batch["status"] != "SUBMITTED":
        raise invalid_state("only a SUBMITTED batch may be approved (current %s)"
                            % batch["status"])

    batch["status"] = "APPROVED"
    batch["approved_by_user_id"] = ctx.user_id
    batch["decided_at"] = clock.now()
    core.bump(batch)

    for redemption in core.batch_claimed_redemptions(batch["id"]):
        if redemption["settlement_status"] == "BATCHED":
            redemption["settlement_status"] = "SETTLED"
            core.bump(redemption)

    core.bump(db.sites[batch["site_id"]])
    return response.object_response(serializers.settlement_batch(batch))


@bp.route("/settlement-batches/<batch_id>/reject", methods=["POST"])
def reject_settlement_batch(batch_id):
    ctx = middleware.require(("ProgramAdmin",))
    batch = core.fetch("settlement_batches", batch_id)

    if batch["submitted_by_user_id"] is not None \
            and ctx.user_id == batch["submitted_by_user_id"]:
        raise ApiError("ERR_SELF_APPROVAL_FORBIDDEN",
                       "the submitter of a batch may not decide it")
    if batch["status"] != "SUBMITTED":
        raise invalid_state("only a SUBMITTED batch may be rejected (current %s)"
                            % batch["status"])

    for redemption in core.batch_claimed_redemptions(batch["id"]):
        if redemption["settlement_status"] == "BATCHED":
            redemption["settlement_status"] = "PENDING"
            redemption["settlement_batch_id"] = None
            core.bump(redemption)

    batch["status"] = "REJECTED"
    batch["decided_at"] = clock.now()
    batch.update(dict(_ZERO_TOTALS))
    core.bump(batch)
    core.bump(db.sites[batch["site_id"]])

    return response.object_response(serializers.settlement_batch(batch))
