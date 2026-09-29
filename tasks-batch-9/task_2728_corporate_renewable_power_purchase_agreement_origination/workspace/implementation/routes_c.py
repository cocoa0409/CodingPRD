"""Execution, conditions precedent, termination, settlement, attributes, risk."""
from decimal import Decimal

from flask import Blueprint, g

import calc
import services as svc
from core import (ApiError, D0, add_days, bad_request, body, db, deal_batches,
                  deal_conditions, deal_instruments, deal_periods,
                  deal_risk_events, endpoint, filter_enum, filter_str,
                  get_batch, get_condition, get_deal, get_offtaker, get_period,
                  get_risk_event, iso_ms, now, opt_enum, opt_num, opt_str,
                  page, period_intervals, q, req_dt, req_enum, req_int,
                  req_num, req_str, require_counterparty, sort_created, touch)

bp = Blueprint("routes_c", __name__)

HOUR_SECONDS = 3600


# ------------------------------------------------------------------- execution
@bp.route("/ppa/deals/<deal_id>/execute", methods=["POST"])
@endpoint(["DealCommittee"])
def execute_deal(deal_id):
    body()
    deal = get_deal(deal_id)
    if deal["status"] != "TERMS_AGREED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "a %s deal cannot be signed" % deal["status"])
    if deal["credit_status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "credit is %s" % deal["credit_status"])
    if g.user_id == deal.get("credit_approved_by_user_id"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "the credit approver may not sign the deal")
    anchor = db.offtakers.get(deal["anchor_offtaker_id"])
    if anchor is None or anchor["qualification_status"] != "QUALIFIED":
        raise ApiError("ERR_OFFTAKER_NOT_QUALIFIED",
                       "only a fully qualified buyer may sign")
    if anchor.get("credit_tier") == "DECLINED":
        raise ApiError("ERR_CREDIT_TIER_DECLINED",
                       "the buyer's credit tier is declined")
    if Decimal(deal["confirmed_allocated_mw"]) != Decimal(deal["contracted_mw"]):
        raise ApiError("ERR_ALLOCATION_INCOMPLETE",
                       "confirmed allocation does not equal contracted_mw")
    posted = Decimal(deal.get("posted_credit_support_usd") or 0)
    required = Decimal(deal.get("credit_support_required_usd") or 0)
    if posted < required:
        raise ApiError("ERR_CREDIT_SUPPORT_SHORTFALL",
                       "posted collateral does not cover the requirement")
    project = db.projects[deal["project_id"]]
    if Decimal(project["available_mw"]) < Decimal(deal["contracted_mw"]):
        raise ApiError("ERR_PROJECT_CAPACITY_EXCEEDED",
                       "the project no longer has the headroom")

    deal["status"] = "EXECUTED"
    svc.create_conditions(deal, project, anchor)
    touch(deal)
    svc.recompute_project_capacity(project, always_touch=True)
    svc.maybe_effective(deal)
    return deal


@bp.route("/ppa/deals/<deal_id>/conditions-precedent", methods=["GET"])
@endpoint(["Originator", "DealCommittee", "OfftakerRep"])
def list_conditions(deal_id):
    status = filter_enum("status", calc.CP_STATUS)
    cp_type = filter_enum("cp_type", calc.CP_TYPE)
    deal = get_deal(deal_id)
    rows = deal_conditions(deal["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if cp_type is not None:
        rows = [r for r in rows if r["cp_type"] == cp_type]
    window, meta = page(rows)
    return window, 200, meta


@bp.route("/ppa/conditions-precedent/<condition_id>/resolution",
          methods=["POST"])
@endpoint(["Originator", "DealCommittee"])
def resolve_condition(condition_id):
    data = body()
    resolution = req_enum(data, "resolution",
                          ["SATISFY", "WAIVE", "FAIL", "RECURE"])
    evidence_ref = opt_str(data, "evidence_ref", 1, None, None)
    justification = opt_str(data, "waiver_justification", 1, None, None)
    if resolution == "SATISFY" and evidence_ref is None:
        bad_request("evidence_ref is required to satisfy a condition")
    if resolution == "WAIVE" and justification is None:
        bad_request("waiver_justification is required to waive a condition")

    cond = get_condition(condition_id)
    deal = db.deals[cond["deal_id"]]
    stamp = now()

    if resolution == "SATISFY":
        if cond["status"] != "PENDING":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "condition is not PENDING")
        if deal["status"] != "EXECUTED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "the deal is not EXECUTED")
        if stamp > cond["deadline_date"]:
            raise ApiError("ERR_CP_DEADLINE_PASSED",
                           "the condition deadline has passed")
        cond["status"] = "SATISFIED"
        cond["evidence_ref"] = evidence_ref
        cond["resolved_at"] = stamp
        cond["resolved_by_user_id"] = g.user_id
    elif resolution == "WAIVE":
        if cond["status"] != "PENDING":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "condition is not PENDING")
        if deal["status"] != "EXECUTED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "the deal is not EXECUTED")
        if not cond["is_waivable"]:
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "this condition is not waivable")
        cond["status"] = "WAIVED"
        cond["resolved_at"] = stamp
        cond["resolved_by_user_id"] = g.user_id
        cond["waiver_justification"] = justification
        deal["commercial_operation_deadline"] = add_days(
            deal["commercial_operation_deadline"],
            calc.CP_WAIVER_EXTENSION_DAYS)
    elif resolution == "FAIL":
        if cond["status"] != "PENDING":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "condition is not PENDING")
        if deal["status"] not in ("EXECUTED", "TERMINATED"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "the deal is %s" % deal["status"])
        cond["status"] = "FAILED"
        cond["resolved_at"] = stamp
        cond["resolved_by_user_id"] = g.user_id
        cond["cure_deadline"] = add_days(stamp, calc.CP_CURE_DAYS)
    else:
        if cond["status"] != "FAILED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "condition is not FAILED")
        if deal["status"] != "EXECUTED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "the deal is not EXECUTED")
        if cond.get("cure_deadline") is None or stamp > cond["cure_deadline"]:
            raise ApiError("ERR_CP_DEADLINE_PASSED",
                           "the cure deadline has passed")
        cond["status"] = "PENDING"
        cond["cure_deadline"] = None
        cond["resolved_at"] = None
        cond["deadline_date"] = add_days(stamp, calc.CP_CURE_DAYS)
    touch(cond)
    svc.recompute_cp_totals(deal)
    touch(deal)
    svc.maybe_effective(deal)
    return cond


@bp.route("/ppa/deals/<deal_id>/terminate", methods=["POST"])
@endpoint(["DealCommittee"])
def terminate_deal(deal_id):
    data = body()
    reason = req_enum(data, "termination_reason", calc.TERMINATION_REASON)
    deal = get_deal(deal_id)
    if deal["status"] not in ("TERMS_AGREED", "EXECUTED", "EFFECTIVE"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "a %s deal cannot be terminated" % deal["status"])
    if reason == "CP_FAILURE":
        for cond in deal_conditions(deal["id"]):
            if (cond["status"] == "FAILED"
                    and cond.get("resolved_by_user_id") == g.user_id):
                raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                               "the operator who failed the condition may "
                               "not terminate on it")
    if deal["status"] == "EFFECTIVE":
        for period in deal_periods(deal["id"]):
            if period["status"] == "DISPUTED":
                raise ApiError("ERR_INVALID_STATE_TRANSITION",
                               "a disputed settlement period is outstanding")
    if not svc.termination_right_vested(deal, reason):
        raise ApiError("ERR_TERMINATION_RIGHT_NOT_VESTED",
                       "no termination right is vested for %s" % reason)

    prior = deal["status"]
    stamp = now()
    deal["status"] = "TERMINATED"
    deal["terminated_at"] = stamp
    deal["termination_reason"] = reason
    if prior == "TERMS_AGREED":
        for alloc in svc.deal_allocations(deal["id"]):
            if alloc["status"] in ("PROPOSED", "CONFIRMED"):
                alloc["status"] = "WITHDRAWN"
                touch(alloc)
        svc.recompute_alloc_totals(deal)
    else:
        svc.termination_cascade(deal)
    touch(deal)
    project = db.projects.get(deal["project_id"])
    if project is not None:
        svc.recompute_project_capacity(project, always_touch=True)
    return deal


# ---------------------------------------------------------- settlement periods
@bp.route("/ppa/deals/<deal_id>/settlement-periods", methods=["POST"])
@endpoint(["SettlementAnalyst"])
def create_period(deal_id):
    data = body()
    period_start = req_dt(data, "period_start")
    period_end = req_dt(data, "period_end")
    deal = get_deal(deal_id)
    if deal["status"] != "EFFECTIVE":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "settlement requires an EFFECTIVE deal")
    if period_end <= period_start:
        raise ApiError("ERR_INVALID_WINDOW",
                       "period_end must fall after period_start")
    for other in deal_periods(deal["id"]):
        if (period_start < other["period_end"]
                and other["period_start"] < period_end):
            raise ApiError("ERR_SETTLEMENT_PERIOD_OVERLAP",
                           "the window intersects an existing period")

    row = svc.base_row()
    row.update({
        "deal_id": deal["id"],
        "period_start": period_start,
        "period_end": period_end,
        "netting_method": deal["settlement_frequency"],
        "status": "OPEN",
        "interval_count": 0,
        "total_metered_mwh": q(D0, 4),
        "total_deemed_mwh": q(D0, 4),
        "total_delivered_mwh": q(D0, 4),
        "weighted_avg_index_usd_per_mwh": None,
        "energy_settlement_usd": None,
        "basis_adjustment_usd": None,
        "net_settlement_usd": None,
        "seller_pays_usd": None,
        "buyer_pays_usd": None,
        "mintable_attributes_mwh": None,
        "calculated_at": None,
        "invoiced_at": None,
        "dispute_reason": None,
    })
    db.periods[row["id"]] = row
    return row, 201


@bp.route("/ppa/deals/<deal_id>/settlement-periods", methods=["GET"])
@endpoint(["SettlementAnalyst", "Originator", "OfftakerRep"])
def list_periods(deal_id):
    status = filter_enum("status", calc.PERIOD_STATUS)
    netting_method = filter_enum("netting_method", calc.SETTLEMENT_FREQUENCY)
    deal = get_deal(deal_id)
    rows = deal_periods(deal["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if netting_method is not None:
        rows = [r for r in rows if r["netting_method"] == netting_method]
    window, meta = page(rows)
    return window, 200, meta


@bp.route("/ppa/settlement-periods/<period_id>", methods=["GET"])
@endpoint(["SettlementAnalyst", "Originator", "OfftakerRep", "RegistryAgent"])
def read_period(period_id):
    return get_period(period_id)


@bp.route("/ppa/settlement-periods/<period_id>/intervals", methods=["POST"])
@endpoint(["SettlementAnalyst"])
def create_interval(period_id):
    data = body()
    hour_start = req_dt(data, "hour_start")
    metered = req_num(data, "metered_mwh", minimum=0)
    node_price = req_num(data, "node_price_usd_per_mwh")
    hub_price = req_num(data, "hub_price_usd_per_mwh")
    expected_version = req_int(data, "expected_settlement_period_version",
                               None, None)
    flag = opt_enum(data, "curtailment_flag", calc.CURTAILMENT_FLAG, "NONE")

    period = get_period(period_id)
    if period["status"] not in ("OPEN", "CALCULATED", "DISPUTED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "period is %s" % period["status"])
    if expected_version != period["version"]:
        raise ApiError("ERR_STALE_VERSION", "the period has moved on")
    if (hour_start.minute or hour_start.second or hour_start.microsecond):
        raise ApiError("ERR_HOUR_OUTSIDE_PERIOD",
                       "hour_start must land exactly on the hour")
    if not (period["period_start"] <= hour_start < period["period_end"]):
        raise ApiError("ERR_HOUR_OUTSIDE_PERIOD",
                       "hour_start falls outside the period window")
    for other in period_intervals(period["id"]):
        if other["hour_start"] == hour_start:
            raise ApiError("ERR_DUPLICATE_METER_HOUR",
                           "that hour is already loaded")

    row = svc.base_row()
    row.update({
        "settlement_period_id": period["id"],
        "hour_start": hour_start,
        "metered_mwh": q(metered, 4),
        "node_price_usd_per_mwh": q(node_price, 2),
        "hub_price_usd_per_mwh": q(hub_price, 2),
        "curtailment_flag": flag,
        "expected_mwh": None,
        "deemed_mwh": q(D0, 4),
        "delivered_mwh": None,
        "posted_by_user_id": g.user_id,
    })
    db.intervals[row["id"]] = row
    period["interval_count"] = int(period["interval_count"]) + 1
    touch(period)
    return row, 201


@bp.route("/ppa/settlement-periods/<period_id>/intervals", methods=["GET"])
@endpoint(["SettlementAnalyst", "Originator", "OfftakerRep"])
def list_intervals(period_id):
    flag = filter_enum("curtailment_flag", calc.CURTAILMENT_FLAG)
    period = get_period(period_id)
    rows = period_intervals(period["id"])
    if flag is not None:
        rows = [r for r in rows if r["curtailment_flag"] == flag]
    window, meta = page(rows)
    return window, 200, meta


@bp.route("/ppa/settlement-periods/<period_id>/calculate", methods=["POST"])
@endpoint(["SettlementAnalyst"])
def calculate_period(period_id):
    body()
    period = get_period(period_id)
    deal = db.deals[period["deal_id"]]
    if period["status"] not in ("OPEN", "CALCULATED", "DISPUTED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "period is %s" % period["status"])
    if int(period["interval_count"]) < 1:
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "the period carries no metered hours")
    if deal["status"] != "EFFECTIVE":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "the deal is not EFFECTIVE")
    was = period["status"]
    svc.recompute_period(period)
    period["status"] = "CALCULATED"
    if was == "DISPUTED":
        period["invoiced_at"] = None
        period["dispute_reason"] = None
    touch(period)
    return period


@bp.route("/ppa/settlement-periods/<period_id>/advance", methods=["POST"])
@endpoint(["SettlementAnalyst", "OfftakerRep"])
def advance_period(period_id):
    data = body()
    action = req_enum(data, "action", ["INVOICE", "SETTLE", "DISPUTE"])
    dispute_reason = opt_str(data, "dispute_reason", 1, None, None)
    if action == "DISPUTE" and g.role != "OfftakerRep":
        raise ApiError("ERR_ROLE_NOT_PERMITTED",
                       "only the buyer may dispute an invoice")
    if action != "DISPUTE" and g.role != "SettlementAnalyst":
        raise ApiError("ERR_ROLE_NOT_PERMITTED",
                       "only a SettlementAnalyst may %s" % action.lower())
    if action == "DISPUTE" and dispute_reason is None:
        bad_request("dispute_reason is required to dispute an invoice")

    period = get_period(period_id)
    deal = db.deals[period["deal_id"]]
    if action == "DISPUTE":
        require_counterparty(deal, anchor_only=True)

    stamp = now()
    if action == "INVOICE":
        if period["status"] != "CALCULATED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "period is %s" % period["status"])
        for event in deal_risk_events(deal["id"]):
            if (event["status"] == "CLAIMED"
                    and event["window_start"] < period["period_end"]
                    and event["window_end"] >= period["period_start"]):
                raise ApiError("ERR_OPEN_RISK_CLAIM",
                               "an undecided risk claim covers this period")
        period["status"] = "INVOICED"
        period["invoiced_at"] = stamp
    elif action == "SETTLE":
        if period["status"] != "INVOICED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "period is %s" % period["status"])
        period["status"] = "SETTLED"
    else:
        if period["status"] != "INVOICED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "period is %s" % period["status"])
        period["status"] = "DISPUTED"
        period["dispute_reason"] = dispute_reason
    touch(period)
    return period


# ------------------------------------------------------- environmental attributes
def minted_from_period(period_id):
    total = 0
    for batch in db.batches.values():
        if (batch.get("_period_id") == period_id
                and batch["status"] in ("MINTED", "TRANSFERRED", "RETIRED")):
            total += int(batch["quantity_mwh"])
    return total


@bp.route("/ppa/settlement-periods/<period_id>/mint-attributes",
          methods=["POST"])
@endpoint(["RegistryAgent"])
def mint_attributes(period_id):
    data = body()
    quantity = req_int(data, "quantity_mwh", 1, None)
    registry = req_enum(data, "registry", calc.REGISTRY)
    period = get_period(period_id)
    deal = db.deals[period["deal_id"]]
    if period["status"] not in ("CALCULATED", "INVOICED", "SETTLED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "period is %s" % period["status"])
    mintable = int(period.get("mintable_attributes_mwh") or 0)
    remaining = mintable - minted_from_period(period["id"])
    if quantity > remaining:
        raise ApiError("ERR_ATTRIBUTE_QUANTITY_EXCEEDS_MINTABLE",
                       "only %d MWh remain mintable from this period"
                       % max(0, remaining))

    start = period["period_start"]
    row = svc.base_row()
    row.update({
        "deal_id": deal["id"],
        "_period_id": period["id"],
        "vintage_month": "%04d-%02d" % (start.year, start.month),
        "quantity_mwh": quantity,
        "registry": registry,
        "registry_serial_range": None,
        "status": "MINTED",
        "claim_substantiation_status": "UNSUBSTANTIATED",
        "allocation_breakdown": [],
        "transferred_to_offtaker_id": None,
        "claim_year": None,
        "transferred_at": None,
        "retired_at": None,
        "minted_by_user_id": g.user_id,
    })
    db.batches[row["id"]] = row
    svc.recompute_attribute_totals(deal)
    touch(deal)
    return row, 201


@bp.route("/ppa/deals/<deal_id>/attribute-batches", methods=["GET"])
@endpoint(["RegistryAgent", "Originator", "OfftakerRep"])
def list_deal_batches(deal_id):
    status = filter_enum("status", calc.BATCH_STATUS)
    vintage_month = filter_str("vintage_month")
    deal = get_deal(deal_id)
    rows = deal_batches(deal["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if vintage_month is not None:
        rows = [r for r in rows if r["vintage_month"] == vintage_month]
    window, meta = page(rows)
    return window, 200, meta


@bp.route("/ppa/attribute-batches/<batch_id>/transfer", methods=["POST"])
@endpoint(["RegistryAgent"])
def transfer_batch(batch_id):
    data = body()
    recipient_id = req_str(data, "transferred_to_offtaker_id", 1, None)
    serial_range = req_str(data, "registry_serial_range", 1, None)
    batch = get_batch(batch_id)
    recipient = get_offtaker(recipient_id)
    deal = db.deals[batch["deal_id"]]
    if batch["status"] != "MINTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "batch is %s" % batch["status"])
    confirmed = [a for a in svc.deal_allocations(deal["id"])
                 if a["status"] == "CONFIRMED"]
    if not any(a["offtaker_id"] == recipient_id for a in confirmed):
        raise ApiError("ERR_NO_CONFIRMED_ALLOCATION",
                       "the recipient holds no confirmed slice on this deal")
    if recipient.get("registry_account_id") is None:
        raise ApiError("ERR_REGISTRY_ACCOUNT_MISSING",
                       "the recipient holds no registry account")

    batch["status"] = "TRANSFERRED"
    batch["transferred_to_offtaker_id"] = recipient_id
    batch["registry_serial_range"] = serial_range
    batch["transferred_at"] = now()
    batch["allocation_breakdown"] = calc.attribute_allocation(
        batch["quantity_mwh"], confirmed)
    touch(batch)
    svc.recompute_attribute_totals(deal)
    touch(deal)
    return batch


@bp.route("/ppa/attribute-batches/<batch_id>/cancel-transfer",
          methods=["POST"])
@endpoint(["RegistryAgent"])
def cancel_transfer(batch_id):
    body()
    batch = get_batch(batch_id)
    deal = db.deals[batch["deal_id"]]
    if batch["status"] != "TRANSFERRED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "batch is %s" % batch["status"])
    batch["status"] = "MINTED"
    batch["transferred_to_offtaker_id"] = None
    batch["registry_serial_range"] = None
    batch["transferred_at"] = None
    batch["allocation_breakdown"] = []
    touch(batch)
    svc.recompute_attribute_totals(deal)
    touch(deal)
    return batch


@bp.route("/ppa/attribute-batches/<batch_id>/retire", methods=["POST"])
@endpoint(["RegistryAgent"])
def retire_batch(batch_id):
    data = body()
    claim_year = req_int(data, "claim_year", None, None)
    batch = get_batch(batch_id)
    deal = db.deals[batch["deal_id"]]
    if batch["status"] != "TRANSFERRED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "batch is %s" % batch["status"])
    if batch["claim_substantiation_status"] != "UNSUBSTANTIATED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "the claim is already substantiated")
    vintage_year = int(str(batch["vintage_month"])[:4])
    if not (vintage_year <= claim_year
            <= vintage_year + calc.REC_CLAIM_WINDOW_YEARS):
        raise ApiError("ERR_CLAIM_YEAR_OUT_OF_WINDOW",
                       "claim_year falls outside the vintage window")

    batch["status"] = "RETIRED"
    batch["retired_at"] = now()
    batch["claim_year"] = claim_year
    batch["claim_substantiation_status"] = "SUBSTANTIATED"
    recipient = db.offtakers.get(batch["transferred_to_offtaker_id"])
    if recipient is not None:
        recipient["claimed_attributes_mwh"] = (
            int(recipient.get("claimed_attributes_mwh") or 0)
            + int(batch["quantity_mwh"]))
        touch(recipient)
    touch(batch)
    svc.recompute_attribute_totals(deal)
    touch(deal)
    return batch


# ---------------------------------------------------------------- risk events
@bp.route("/ppa/deals/<deal_id>/risk-events", methods=["POST"])
@endpoint(["Originator", "OfftakerRep"])
def create_risk_event(deal_id):
    data = body()
    event_type = req_enum(data, "event_type", calc.EVENT_TYPE)
    claimed_by = req_enum(data, "claimed_by", calc.PROPOSED_BY)
    window_start = req_dt(data, "window_start")
    window_end = req_dt(data, "window_end")
    description = opt_str(data, "description", 1, 512, None)

    deal = get_deal(deal_id)
    require_counterparty(deal)
    if deal["status"] not in ("EFFECTIVE", "EXECUTED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "a %s deal carries no risk claims" % deal["status"])
    if window_end < window_start:
        raise ApiError("ERR_INVALID_WINDOW",
                       "window_end must fall at or after window_start")
    for other in deal_risk_events(deal["id"]):
        if (other["event_type"] == event_type
                and other["status"] in ("CLAIMED", "ACCEPTED")
                and window_start <= other["window_end"]
                and other["window_start"] <= window_end):
            raise ApiError("ERR_RISK_WINDOW_OVERLAP",
                           "the window collides with a live claim")

    row = svc.base_row()
    row.update({
        "deal_id": deal["id"],
        "event_type": event_type,
        "claimed_by": claimed_by,
        "window_start": window_start,
        "window_end": window_end,
        "description": description,
        "status": "CLAIMED",
        "allocation_outcome": None,
        "price_adjustment_usd_per_mwh": None,
        "duration_days": None,
        "excused_hours": 0,
        "reviewed_by_user_id": None,
        "reviewed_at": None,
    })
    db.risk_events[row["id"]] = row
    return row, 201


@bp.route("/ppa/deals/<deal_id>/risk-events", methods=["GET"])
@endpoint(["Originator", "DealCommittee", "OfftakerRep", "SettlementAnalyst"])
def list_risk_events(deal_id):
    event_type = filter_enum("event_type", calc.EVENT_TYPE)
    status = filter_enum("status", calc.RISK_STATUS)
    deal = get_deal(deal_id)
    rows = deal_risk_events(deal["id"])
    if event_type is not None:
        rows = [r for r in rows if r["event_type"] == event_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    window, meta = page(rows)
    return window, 200, meta


ADJUSTMENT_MIN = Decimal("-10.00")
ADJUSTMENT_MAX = Decimal("10.00")


@bp.route("/ppa/risk-events/<event_id>/review", methods=["POST"])
@endpoint(["DealCommittee"])
def review_risk_event(event_id):
    data = body()
    decision = req_enum(data, "decision", ["ACCEPT", "REJECT"])
    outcome = opt_enum(data, "allocation_outcome", calc.ALLOCATION_OUTCOME)
    adjustment = opt_num(data, "price_adjustment_usd_per_mwh")
    if decision == "ACCEPT" and outcome is None:
        bad_request("allocation_outcome is required to accept a claim")

    event = get_risk_event(event_id)
    deal = db.deals[event["deal_id"]]
    if event["status"] != "CLAIMED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "claim is %s" % event["status"])

    stamp = now()
    if decision == "REJECT":
        event["status"] = "REJECTED"
        event["reviewed_by_user_id"] = g.user_id
        event["reviewed_at"] = stamp
        touch(event)
        return event

    reprice = event["event_type"] == "CHANGE_IN_LAW"
    new_price = None
    if reprice:
        if adjustment is None:
            raise ApiError("ERR_PRICE_ADJUSTMENT_INVALID",
                           "a change-in-law acceptance must carry a "
                           "price adjustment")
        adjustment = q(adjustment, 2)
        if adjustment < ADJUSTMENT_MIN or adjustment > ADJUSTMENT_MAX:
            raise ApiError("ERR_PRICE_ADJUSTMENT_INVALID",
                           "the adjustment must lie between -10.00 and 10.00")
        new_price = q(Decimal(deal["contract_price_usd_per_mwh"] or 0)
                      + adjustment, 2)
        if new_price <= 0:
            raise ApiError("ERR_PRICE_ADJUSTMENT_INVALID",
                           "the resulting contract price must stay positive")

    event["status"] = "ACCEPTED"
    event["allocation_outcome"] = outcome
    if reprice:
        event["price_adjustment_usd_per_mwh"] = adjustment
    event["reviewed_by_user_id"] = g.user_id
    event["reviewed_at"] = stamp
    svc.apply_risk_impact(event)
    touch(event)

    if reprice:
        deal["contract_price_usd_per_mwh"] = new_price
        svc.resize_deal_credit(deal, None, snapshot=False)
        touch(deal)
        svc.open_shortfall(deal)
    return event
