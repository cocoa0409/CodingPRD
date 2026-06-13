"""DistributionEvent & DistributionAllocation routes (PRD §3.5, §3.6)."""
from flask import Blueprint, request

import db
import errors
from middleware import authenticate, require_role
from response import success
from services import derive, lookup, serialize, waterfall
import validation as V

bp = Blueprint("distributions", __name__)

READ_ALL_ROLES = ["FundManager", "FundAdministrator", "ComplianceOfficer", "LimitedPartnerUser"]
READ_OPS_ROLES = ["FundManager", "FundAdministrator", "ComplianceOfficer"]
DIST_TYPES = ("RETURN_OF_CAPITAL", "CAPITAL_GAIN", "INCOME")


def _already_distributed_from(investment_id):
    """Amounts already distributed from this investment: sum gross_amount_cents
    over its events whose status is not REVERSED."""
    total = 0
    for e in db.distribution_events.values():
        if e["source_investment_id"] == investment_id and e["status"] != "REVERSED":
            total += e["gross_amount_cents"]
    return total


@bp.route("/distribution-events", methods=["POST"])
def declare_distribution():
    caller = authenticate()
    require_role(caller, ["FundManager"])
    body = V.get_json_body()
    fund_id = V.require_string(body, "fund_id")
    source_investment_id = V.require_string(body, "source_investment_id")
    gross_amount_cents = V.require_int(body, "gross_amount_cents")
    distribution_type = V.require_enum(body, "distribution_type", DIST_TYPES)
    recyclable = V.optional_bool(body, "recyclable", False)
    expected_fund_version = V.require_int(body, "expected_fund_version")

    with db.lock:
        # Existence (404) for path/FK left-to-right.
        fund = lookup.get_fund(fund_id)
        investment = lookup.get_investment(source_investment_id)

        # Range: gross_amount_cents >= 1.
        V.check_range(gross_amount_cents, "gross_amount_cents", lo=1)

        # State/fiscal checks: source must be REALIZED.
        if investment["status"] != "REALIZED":
            errors.fail(errors.ERR_SOURCE_NOT_REALIZED, "Source investment is not REALIZED.")

        # Proceeds: gross must not exceed available realized proceeds.
        available = investment["realized_proceeds_cents"] - _already_distributed_from(
            source_investment_id
        )
        if gross_amount_cents > available:
            errors.fail(
                errors.ERR_DISTRIBUTION_EXCEEDS_PROCEEDS,
                "Distribution exceeds available realized proceeds.",
            )

        # OCC on Fund.version (412).
        if expected_fund_version != fund["version"]:
            errors.fail(errors.ERR_STALE_FUND_VERSION, "Stale fund version.")

        # Waterfall.
        lp_share, gp_carry, clawback_flag = waterfall.run_waterfall(
            fund, gross_amount_cents
        )

        # Split lp_share across commitments by drawn (paid-in). Empty set ->
        # ERR_NO_PARTICIPATING_COMMITMENTS.
        eligible, amounts = waterfall.split_to_commitments(fund_id, lp_share)

        event = db.stamp_new(
            {
                "fund_id": fund_id,
                "source_investment_id": source_investment_id,
                "gross_amount_cents": gross_amount_cents,
                "distribution_type": distribution_type,
                "recyclable": recyclable,
                "lp_share_cents": lp_share,
                "gp_carry_cents": gp_carry,
                "recycled_amount_cents": 0,
                "status": "DECLARED",
            }
        )
        db.distribution_events[event["id"]] = event

        for c in eligible:
            alloc = db.stamp_new(
                {
                    "distribution_event_id": event["id"],
                    "commitment_id": c["id"],
                    "amount_cents": amounts[c["id"]],
                    "clawback_flag": clawback_flag,
                }
            )
            db.distribution_allocations[alloc["id"]] = alloc

        # Declaration increments Fund.version by 1.
        db.touch(fund)
    return success(serialize.distribution_event(event), status=201)


@bp.route("/distribution-events/<eid>", methods=["GET"])
def read_distribution_event(eid):
    caller = authenticate()
    require_role(caller, READ_ALL_ROLES)
    obj = lookup.get_distribution_event(eid)
    return success(serialize.distribution_event(obj))


@bp.route("/distribution-events", methods=["GET"])
def list_distribution_events():
    caller = authenticate()
    require_role(caller, READ_OPS_ROLES)
    limit, offset = V.parse_pagination()
    fund_id = request.args.get("fund_id")
    source_investment_id = request.args.get("source_investment_id")
    status = request.args.get("status")
    items = list(db.distribution_events.values())
    if fund_id is not None:
        items = [e for e in items if e["fund_id"] == fund_id]
    if source_investment_id is not None:
        items = [e for e in items if e["source_investment_id"] == source_investment_id]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    items = V.sort_by_created(items)
    page, meta = V.paginate(items, limit, offset)
    return success([serialize.distribution_event(o) for o in page], pagination=meta)


@bp.route("/distribution-events/<eid>/pay", methods=["POST"])
def pay_distribution(eid):
    caller = authenticate()
    require_role(caller, ["FundAdministrator"])
    with db.lock:
        event = lookup.get_distribution_event(eid)
        if event["status"] != "DECLARED":
            errors.fail(errors.ERR_INVALID_STATE, "Event is not DECLARED.")
        event["status"] = "PAID"
        db.touch(event)
        # Recompute distributed_cents on each commitment named by an allocation;
        # recompute fund total_distributed (both derived). Bump affected rows.
        affected = set()
        for a in db.distribution_allocations.values():
            if a["distribution_event_id"] == eid:
                affected.add(a["commitment_id"])
        for cid in affected:
            c = db.commitments.get(cid)
            if c:
                db.touch(c)
        fund = db.funds.get(event["fund_id"])
        if fund:
            db.touch(fund)
    return success(serialize.distribution_event(event))


@bp.route("/distribution-events/<eid>/recall", methods=["POST"])
def recall_distribution(eid):
    caller = authenticate()
    require_role(caller, ["FundManager"])
    with db.lock:
        event = lookup.get_distribution_event(eid)
        if event["status"] != "PAID":
            errors.fail(errors.ERR_INVALID_STATE, "Event is not PAID.")
        if not event["recyclable"]:
            errors.fail(errors.ERR_INVALID_STATE, "Event is not recyclable.")
        fund = db.funds[event["fund_id"]]
        recallable = waterfall.recycle(fund, event)
        event["status"] = "RECALLED"
        event["recycled_amount_cents"] = recallable
        db.touch(event)
        # Fund.recycled_to_date_cents recomputed (derived); bump fund.
        db.touch(fund)
    return success(serialize.distribution_event(event))


@bp.route("/distribution-events/<eid>/reverse", methods=["POST"])
def reverse_distribution(eid):
    caller = authenticate()
    require_role(caller, ["FundManager"])
    with db.lock:
        event = lookup.get_distribution_event(eid)
        if event["status"] != "DECLARED":
            errors.fail(errors.ERR_INVALID_STATE, "Event is not DECLARED.")
        event["status"] = "REVERSED"
        db.touch(event)
        # Zero amount_cents on all of its allocations.
        for a in db.distribution_allocations.values():
            if a["distribution_event_id"] == eid:
                a["amount_cents"] = 0
                db.touch(a)
    return success(serialize.distribution_event(event))


# ---- DistributionAllocation ----
@bp.route("/distribution-allocations/<aid>", methods=["GET"])
def read_distribution_allocation(aid):
    caller = authenticate()
    require_role(caller, READ_ALL_ROLES)
    obj = lookup.get_distribution_allocation(aid)
    return success(serialize.distribution_allocation(obj))


@bp.route("/distribution-allocations", methods=["GET"])
def list_distribution_allocations():
    caller = authenticate()
    require_role(caller, READ_ALL_ROLES)
    limit, offset = V.parse_pagination()
    commitment_id = request.args.get("commitment_id")
    distribution_event_id = request.args.get("distribution_event_id")
    items = list(db.distribution_allocations.values())
    if commitment_id is not None:
        items = [a for a in items if a["commitment_id"] == commitment_id]
    if distribution_event_id is not None:
        items = [a for a in items if a["distribution_event_id"] == distribution_event_id]
    items = V.sort_by_created(items)
    page, meta = V.paginate(items, limit, offset)
    return success([serialize.distribution_allocation(o) for o in page], pagination=meta)
