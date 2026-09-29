"""Deals, negotiation rounds, allocations and credit support."""
from decimal import Decimal

from flask import Blueprint, g

import calc
import services as svc
from core import (ApiError, D0, add_days, bad_request, body, db,
                  deal_allocations, deal_instruments, deal_rounds, endpoint,
                  filter_enum, filter_str, floor_days_between, get_allocation,
                  get_deal, get_instrument, get_offtaker, get_pricing_node,
                  get_project, get_round, now, opt_bool, opt_enum, opt_list,
                  opt_num, opt_str, page, q, req_dt, req_enum, req_int,
                  req_num, req_str, require_counterparty, sort_created, touch)

bp = Blueprint("routes_b", __name__)

ALL_ROLES = ["Originator", "CreditOfficer", "DealCommittee",
             "SettlementAnalyst", "RegistryAgent", "OfftakerRep"]
NEGOTIABLE = ("TERM_SHEET_ISSUED", "UNDER_NEGOTIATION", "TERMS_AGREED")


def price_deal(deal):
    price, tier, _base = calc.deal_contract_price(
        deal["base_fixed_price_usd_per_mwh"], deal["escalation_pct_per_year"],
        deal["first_delivery_year"], deal["shape_product"],
        deal["basis_responsibility"])
    deal["contract_price_usd_per_mwh"] = price
    deal["price_tier"] = tier


# ---------------------------------------------------------------------- deals
@bp.route("/ppa/deals", methods=["POST"])
@endpoint(["Originator"])
def create_deal():
    data = body()
    project_id = req_str(data, "project_id", 1, None)
    anchor_id = req_str(data, "anchor_offtaker_id", 1, None)
    node_id = req_str(data, "settlement_point_id", 1, None)
    product_type = req_enum(data, "product_type", calc.PRODUCT_TYPE)
    contracted = req_num(data, "contracted_mw", minimum=0, exclusive_min=True)
    term_years = req_int(data, "term_years", 1, 25)
    first_year = req_int(data, "first_delivery_year", 2026, 2040)
    cod_deadline = req_dt(data, "commercial_operation_deadline")
    frequency = req_enum(data, "settlement_frequency",
                         calc.SETTLEMENT_FREQUENCY)
    base_price = req_num(data, "base_fixed_price_usd_per_mwh", minimum=0,
                         exclusive_min=True)
    escalation = req_num(data, "escalation_pct_per_year", minimum=0,
                         maximum=10)
    shape_product = req_enum(data, "shape_product", calc.SHAPE_PRODUCT)
    basis = req_enum(data, "basis_responsibility", calc.BASIS_RESPONSIBILITY)

    project = get_project(project_id)
    anchor = get_offtaker(anchor_id)
    get_pricing_node(node_id)

    if anchor["qualification_status"] not in ("QUALIFIED", "CONDITIONAL"):
        raise ApiError("ERR_OFFTAKER_NOT_QUALIFIED",
                       "the anchor buyer is not qualified")
    if cod_deadline <= now():
        raise ApiError("ERR_INVALID_WINDOW",
                       "commercial_operation_deadline must be in the future")
    contracted = q(contracted, 3)
    if contracted > Decimal(project["available_mw"]):
        raise ApiError("ERR_PROJECT_CAPACITY_EXCEEDED",
                       "contracted_mw exceeds the project's available capacity")

    row = svc.base_row()
    row.update({
        "project_id": project_id,
        "anchor_offtaker_id": anchor_id,
        "settlement_point_id": node_id,
        "product_type": product_type,
        "contracted_mw": contracted,
        "term_years": term_years,
        "first_delivery_year": first_year,
        "commercial_operation_deadline": cod_deadline,
        "settlement_frequency": frequency,
        "base_fixed_price_usd_per_mwh": q(base_price, 2),
        "escalation_pct_per_year": escalation,
        "shape_product": shape_product,
        "basis_responsibility": basis,
        "status": "DRAFT",
        "credit_status": "NOT_SUBMITTED",
        "contract_price_usd_per_mwh": None,
        "price_tier": None,
        "expected_annual_mwh": None,
        "exposure_usd": None,
        "unsecured_credit_limit_usd": None,
        "credit_support_required_usd": None,
        "posted_credit_support_usd": q(D0, 2),
        "released_credit_support_usd": q(D0, 2),
        "drawn_credit_support_usd": q(D0, 2),
        "collateral_threshold_usd": None,
        "credit_approved_by_user_id": None,
        "support_cure_deadline": None,
        "round_count": 0,
        "confirmed_allocated_mw": q(D0, 3),
        "unallocated_mw": contracted,
        "cp_total_count": 0,
        "cp_completion_pct": None,
        "attributes_minted_mwh": 0,
        "attributes_transferred_mwh": 0,
        "attributes_retired_mwh": 0,
        "effective_at": None,
        "terminated_at": None,
        "termination_reason": None,
        "created_by_user_id": g.user_id,
    })
    price_deal(row)
    db.deals[row["id"]] = row
    svc.resize_deal_credit(row, anchor)
    svc.recompute_project_capacity(project, always_touch=True)
    return row, 201


@bp.route("/ppa/deals", methods=["GET"])
@endpoint(["Originator", "CreditOfficer", "DealCommittee", "SettlementAnalyst"])
def list_deals():
    project_id = filter_str("project_id")
    anchor_id = filter_str("anchor_offtaker_id")
    node_id = filter_str("settlement_point_id")
    status = filter_enum("status", calc.DEAL_STATUS)
    credit_status = filter_enum("credit_status", calc.CREDIT_STATUS)
    rows = sort_created(list(db.deals.values()))
    if project_id is not None:
        rows = [r for r in rows if r["project_id"] == project_id]
    if anchor_id is not None:
        rows = [r for r in rows if r["anchor_offtaker_id"] == anchor_id]
    if node_id is not None:
        rows = [r for r in rows if r["settlement_point_id"] == node_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if credit_status is not None:
        rows = [r for r in rows if r["credit_status"] == credit_status]
    window, meta = page(rows)
    return window, 200, meta


@bp.route("/ppa/deals/<deal_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def read_deal(deal_id):
    deal = get_deal(deal_id)
    require_counterparty(deal)
    return deal


# --------------------------------------------------------------------- rounds
@bp.route("/ppa/deals/<deal_id>/rounds", methods=["POST"])
@endpoint(["Originator"])
def create_round(deal_id):
    data = body()
    proposed_by = req_enum(data, "proposed_by", calc.PROPOSED_BY)
    price = req_num(data, "proposed_fixed_price_usd_per_mwh", minimum=0,
                    exclusive_min=True)
    escalation = req_num(data, "proposed_escalation_pct_per_year", minimum=0,
                         maximum=10)
    shape_product = req_enum(data, "proposed_shape_product",
                             calc.SHAPE_PRODUCT)
    basis = req_enum(data, "proposed_basis_responsibility",
                     calc.BASIS_RESPONSIBILITY)
    deadline = req_dt(data, "response_deadline")
    redlines = opt_list(data, "redline_items", [])

    deal = get_deal(deal_id)
    if proposed_by != "DEVELOPER":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "only a DEVELOPER round may be tabled here")
    status = deal["status"]
    if status not in ("DRAFT", "UNDER_NEGOTIATION", "TERMS_AGREED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "cannot table a round on a %s deal" % status)
    if status == "DRAFT":
        anchor = db.offtakers.get(deal["anchor_offtaker_id"])
        if (anchor is None
                or anchor["qualification_status"] not in ("QUALIFIED",
                                                          "CONDITIONAL")):
            raise ApiError("ERR_OFFTAKER_NOT_QUALIFIED",
                           "the anchor buyer is not qualified")
    if status == "TERMS_AGREED" and deal["credit_status"] == "APPROVED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "agreed terms cannot be re-opened after credit approval")

    stamp = now()
    for existing in deal_rounds(deal["id"]):
        if existing["status"] != "OPEN":
            continue
        if existing["response_deadline"] < stamp:
            existing["status"] = "EXPIRED"
        else:
            # The sweep names only responded_by_user_id; responded_at stays
            # as it stood (null on a round that was never answered).
            existing["status"] = "COUNTERED"
            existing["responded_by_user_id"] = g.user_id
        touch(existing)

    if status == "TERMS_AGREED":
        deal["contract_price_usd_per_mwh"] = None
        deal["price_tier"] = None
        deal["status"] = "UNDER_NEGOTIATION"
    else:
        deal["status"] = "TERM_SHEET_ISSUED"

    row = svc.base_row()
    row.update({
        "deal_id": deal["id"],
        "round_number": int(deal["round_count"]) + 1,
        "proposed_by": proposed_by,
        "proposed_fixed_price_usd_per_mwh": q(price, 2),
        "proposed_escalation_pct_per_year": escalation,
        "proposed_shape_product": shape_product,
        "proposed_basis_responsibility": basis,
        "redline_items": list(redlines),
        "response_deadline": deadline,
        "status": "OPEN",
        "responded_at": None,
        "responded_by_user_id": None,
    })
    db.rounds[row["id"]] = row
    deal["round_count"] = int(deal["round_count"]) + 1
    touch(deal)
    return row, 201


@bp.route("/ppa/deals/<deal_id>/rounds", methods=["GET"])
@endpoint(["Originator", "OfftakerRep", "DealCommittee"])
def list_rounds(deal_id):
    status = filter_enum("status", calc.ROUND_STATUS)
    proposed_by = filter_enum("proposed_by", calc.PROPOSED_BY)
    deal = get_deal(deal_id)
    rows = deal_rounds(deal["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if proposed_by is not None:
        rows = [r for r in rows if r["proposed_by"] == proposed_by]
    window, meta = page(rows)
    return window, 200, meta


@bp.route("/ppa/rounds/<round_id>/respond", methods=["POST"])
@endpoint(["OfftakerRep"])
def respond_round(round_id):
    data = body()
    response = req_enum(data, "response", ["ACCEPT", "COUNTER"])
    counter_price = opt_num(data, "counter_fixed_price_usd_per_mwh", minimum=0,
                            exclusive_min=True)
    counter_escalation = opt_num(data, "counter_escalation_pct_per_year",
                                 minimum=0, maximum=10)
    counter_shape = opt_enum(data, "counter_shape_product", calc.SHAPE_PRODUCT)
    counter_basis = opt_enum(data, "counter_basis_responsibility",
                             calc.BASIS_RESPONSIBILITY)
    redlines = opt_list(data, "redline_items", [])

    row = get_round(round_id)
    deal = db.deals[row["deal_id"]]
    require_counterparty(deal, anchor_only=(response == "ACCEPT"))

    if row["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "round is not open")
    if deal["status"] != "TERM_SHEET_ISSUED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "deal is not awaiting a response")
    stamp = now()
    if row["response_deadline"] < stamp:
        raise ApiError("ERR_ROUND_EXPIRED", "the response deadline has passed")

    row["responded_at"] = stamp
    row["responded_by_user_id"] = g.user_id
    if response == "ACCEPT":
        row["status"] = "ACCEPTED"
        touch(row)
        deal["base_fixed_price_usd_per_mwh"] = \
            row["proposed_fixed_price_usd_per_mwh"]
        deal["escalation_pct_per_year"] = \
            row["proposed_escalation_pct_per_year"]
        deal["shape_product"] = row["proposed_shape_product"]
        deal["basis_responsibility"] = row["proposed_basis_responsibility"]
        price_deal(deal)
        deal["status"] = "TERMS_AGREED"
        touch(deal)
        return row

    row["status"] = "COUNTERED"
    touch(row)
    successor = svc.base_row()
    successor.update({
        "deal_id": deal["id"],
        "round_number": int(deal["round_count"]) + 1,
        "proposed_by": "OFFTAKER",
        "proposed_fixed_price_usd_per_mwh": q(
            counter_price if counter_price is not None
            else row["proposed_fixed_price_usd_per_mwh"], 2),
        "proposed_escalation_pct_per_year": (
            counter_escalation if counter_escalation is not None
            else row["proposed_escalation_pct_per_year"]),
        "proposed_shape_product": (counter_shape or
                                   row["proposed_shape_product"]),
        "proposed_basis_responsibility": (counter_basis or
                                          row["proposed_basis_responsibility"]),
        "redline_items": list(redlines),
        "response_deadline": add_days(stamp, calc.ROUND_RESPONSE_DAYS),
        "status": "OPEN",
        "responded_at": None,
        "responded_by_user_id": None,
    })
    db.rounds[successor["id"]] = successor
    deal["round_count"] = int(deal["round_count"]) + 1
    deal["status"] = "UNDER_NEGOTIATION"
    touch(deal)
    return successor


# ---------------------------------------------------------------- allocations
@bp.route("/ppa/deals/<deal_id>/allocations", methods=["POST"])
@endpoint(["Originator"])
def create_allocation(deal_id):
    data = body()
    offtaker_id = req_str(data, "offtaker_id", 1, None)
    allocated = req_num(data, "allocated_mw", minimum=0, exclusive_min=True)
    expected_version = req_int(data, "expected_deal_version", None, None)
    joint = opt_bool(data, "joint_and_several", False)

    deal = get_deal(deal_id)
    buyer = get_offtaker(offtaker_id)

    if deal["status"] not in NEGOTIABLE:
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "cannot allocate on a %s deal" % deal["status"])
    if expected_version != deal["version"]:
        raise ApiError("ERR_STALE_VERSION", "the deal has moved on")
    if buyer["qualification_status"] not in ("QUALIFIED", "CONDITIONAL"):
        raise ApiError("ERR_OFFTAKER_NOT_QUALIFIED",
                       "the named buyer is not qualified")
    for existing in deal_allocations(deal["id"]):
        if (existing["offtaker_id"] == offtaker_id
                and existing["status"] in ("PROPOSED", "CONFIRMED")):
            raise ApiError("ERR_DUPLICATE_ALLOCATION",
                           "that buyer already holds a live slice")

    allocated = q(allocated, 3)
    row = svc.base_row()
    row.update({
        "deal_id": deal["id"],
        "offtaker_id": offtaker_id,
        "allocated_mw": allocated,
        "allocation_share_pct": calc.allocation_share_pct(
            allocated, deal["contracted_mw"]),
        "joint_and_several": bool(joint),
        "status": "PROPOSED",
        "confirmed_at": None,
        "created_by_user_id": g.user_id,
    })
    db.allocations[row["id"]] = row
    svc.recompute_alloc_totals(deal)
    touch(deal)
    return row, 201


@bp.route("/ppa/deals/<deal_id>/allocations", methods=["GET"])
@endpoint(["Originator", "CreditOfficer", "DealCommittee", "OfftakerRep"])
def list_deal_allocations(deal_id):
    status = filter_enum("status", calc.ALLOCATION_STATUS)
    offtaker_id = filter_str("offtaker_id")
    deal = get_deal(deal_id)
    rows = deal_allocations(deal["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if offtaker_id is not None:
        rows = [r for r in rows if r["offtaker_id"] == offtaker_id]
    window, meta = page(rows)
    return window, 200, meta


@bp.route("/ppa/allocations/<alloc_id>/decision", methods=["POST"])
@endpoint(["OfftakerRep"])
def allocation_decision(alloc_id):
    data = body()
    decision = req_enum(data, "decision", ["CONFIRM", "WITHDRAW"])
    alloc = get_allocation(alloc_id)
    deal = db.deals[alloc["deal_id"]]
    if g.user_id != alloc["offtaker_id"]:
        raise ApiError("ERR_NOT_DEAL_COUNTERPARTY",
                       "only the holding buyer may decide this slice")

    if decision == "CONFIRM":
        if alloc["status"] != "PROPOSED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "slice is not PROPOSED")
        if deal["status"] not in NEGOTIABLE:
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "deal is not open for allocation")
        buyer = db.offtakers.get(alloc["offtaker_id"])
        if (buyer is None
                or buyer["qualification_status"] not in ("QUALIFIED",
                                                         "CONDITIONAL")):
            raise ApiError("ERR_OFFTAKER_NOT_QUALIFIED",
                           "the holding buyer is not qualified")
        confirmed = Decimal(alloc["allocated_mw"])
        for other in deal_allocations(deal["id"]):
            if other["id"] != alloc["id"] and other["status"] == "CONFIRMED":
                confirmed += Decimal(other["allocated_mw"])
        if confirmed > Decimal(deal["contracted_mw"]):
            raise ApiError("ERR_ALLOCATION_EXCEEDS_CONTRACTED_MW",
                           "confirming would exceed the contracted capacity")
        alloc["status"] = "CONFIRMED"
        alloc["confirmed_at"] = now()
    else:
        if alloc["status"] not in ("PROPOSED", "CONFIRMED"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "slice is not live")
        if (alloc["status"] == "CONFIRMED"
                and deal["status"] not in NEGOTIABLE):
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "deal is not open for allocation")
        alloc["status"] = "WITHDRAWN"
    touch(alloc)
    svc.recompute_alloc_totals(deal)
    touch(deal)
    return alloc


# --------------------------------------------------------------------- credit
@bp.route("/ppa/deals/<deal_id>/submit-credit", methods=["POST"])
@endpoint(["Originator"])
def submit_credit(deal_id):
    body()
    deal = get_deal(deal_id)
    prior = deal["credit_status"]
    if prior not in ("NOT_SUBMITTED", "DECLINED", "SUPPORT_SHORTFALL"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "credit is already %s" % prior)
    if deal.get("contract_price_usd_per_mwh") is None:
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "an unpriced deal cannot be underwritten")
    anchor = db.offtakers.get(deal["anchor_offtaker_id"])
    if (prior == "NOT_SUBMITTED"
            and (anchor is None
                 or anchor["qualification_status"] not in ("QUALIFIED",
                                                          "CONDITIONAL"))):
        raise ApiError("ERR_OFFTAKER_NOT_QUALIFIED",
                       "the anchor buyer is not qualified")
    if anchor is not None and anchor.get("credit_tier") == "DECLINED":
        raise ApiError("ERR_CREDIT_TIER_DECLINED",
                       "a declined tier has no eligible support path")

    stamp = now()
    for inst in deal_instruments(deal["id"]):
        if inst["status"] == "POSTED" and inst["expiry_date"] <= stamp:
            inst["status"] = "EXPIRED"
            inst["closed_at"] = stamp
            touch(inst)
    svc.resize_deal_credit(deal, anchor)
    svc.recompute_support_totals(deal)
    if prior == "SUPPORT_SHORTFALL":
        deal["support_cure_deadline"] = None
    deal["credit_status"] = "SUBMITTED"
    touch(deal)
    return deal


@bp.route("/ppa/deals/<deal_id>/credit-decision", methods=["POST"])
@endpoint(["CreditOfficer"])
def credit_decision(deal_id):
    data = body()
    decision = req_enum(data, "decision", ["APPROVE", "DECLINE"])
    opt_str(data, "decision_note", 0, None, None)
    deal = get_deal(deal_id)
    if deal["credit_status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "credit is not awaiting a decision")
    if g.user_id == deal.get("created_by_user_id"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "the originator may not underwrite their own deal")
    if decision == "APPROVE":
        posted = Decimal(deal.get("posted_credit_support_usd") or 0)
        required = Decimal(deal.get("credit_support_required_usd") or 0)
        if posted < required:
            raise ApiError("ERR_CREDIT_SUPPORT_SHORTFALL",
                           "posted collateral does not cover the requirement")
        deal["credit_status"] = "APPROVED"
        deal["credit_approved_by_user_id"] = g.user_id
    else:
        deal["credit_status"] = "DECLINED"
        deal["credit_approved_by_user_id"] = None
    touch(deal)
    return deal


# ------------------------------------------------------------ credit support
@bp.route("/ppa/deals/<deal_id>/credit-support", methods=["POST"])
@endpoint(["Originator", "CreditOfficer"])
def create_instrument(deal_id):
    data = body()
    instrument_type = req_enum(data, "instrument_type", calc.INSTRUMENT_TYPE)
    purpose = req_enum(data, "purpose", calc.INSTRUMENT_PURPOSE)
    face = req_num(data, "face_amount_usd", minimum=0, exclusive_min=True)
    effective_date = req_dt(data, "effective_date")
    expiry_date = req_dt(data, "expiry_date")
    issuer_name = opt_str(data, "issuer_name", 1, 128, None)
    issuer_rating = opt_enum(data, "issuer_rating", calc.CREDIT_RATING)
    guarantor_id = opt_str(data, "guarantor_offtaker_id", 1, None, None)

    deal = get_deal(deal_id)
    if guarantor_id is not None:
        get_offtaker(guarantor_id)
    if expiry_date <= effective_date:
        raise ApiError("ERR_INVALID_WINDOW",
                       "expiry_date must fall after effective_date")

    row = svc.base_row()
    row.update({
        "deal_id": deal["id"],
        "instrument_type": instrument_type,
        "purpose": purpose,
        "face_amount_usd": q(face, 2),
        "effective_date": effective_date,
        "expiry_date": expiry_date,
        "issuer_name": issuer_name,
        "issuer_rating": issuer_rating,
        "guarantor_offtaker_id": guarantor_id,
        "status": "PROPOSED",
        "haircut_pct": None,
        "eligible_credit_usd": None,
        "posted_at": None,
        "closed_at": None,
        "created_by_user_id": g.user_id,
    })
    db.instruments[row["id"]] = row
    return row, 201


@bp.route("/ppa/deals/<deal_id>/credit-support", methods=["GET"])
@endpoint(["CreditOfficer", "Originator", "DealCommittee"])
def list_instruments(deal_id):
    status = filter_enum("status", calc.INSTRUMENT_STATUS)
    purpose = filter_enum("purpose", calc.INSTRUMENT_PURPOSE)
    instrument_type = filter_enum("instrument_type", calc.INSTRUMENT_TYPE)
    deal = get_deal(deal_id)
    rows = deal_instruments(deal["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if purpose is not None:
        rows = [r for r in rows if r["purpose"] == purpose]
    if instrument_type is not None:
        rows = [r for r in rows if r["instrument_type"] == instrument_type]
    window, meta = page(rows)
    return window, 200, meta


@bp.route("/ppa/credit-support/<instrument_id>/post", methods=["POST"])
@endpoint(["CreditOfficer"])
def post_instrument(instrument_id):
    data = body()
    expected_version = req_int(data, "expected_deal_version", None, None)
    inst = get_instrument(instrument_id)
    deal = db.deals[inst["deal_id"]]

    if inst["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "instrument is not PROPOSED")
    if deal["credit_status"] not in ("SUBMITTED", "APPROVED",
                                    "SUPPORT_SHORTFALL", "DECLINED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "credit is %s" % deal["credit_status"])
    if expected_version != deal["version"]:
        raise ApiError("ERR_STALE_VERSION", "the deal has moved on")

    anchor = db.offtakers.get(deal["anchor_offtaker_id"])
    guarantor = None
    kind = inst["instrument_type"]
    if kind == "LETTER_OF_CREDIT":
        if (inst.get("issuer_name") is None
                or inst.get("issuer_rating") not in calc.LC_HAIRCUT_PCT):
            raise ApiError("ERR_INELIGIBLE_ISSUER",
                           "the issuing bank is not eligible")
    elif kind == "PARENT_GUARANTEE":
        guarantor_id = inst.get("guarantor_offtaker_id")
        expected_parent = (anchor or {}).get("parent_guarantor_offtaker_id")
        guarantor = db.offtakers.get(guarantor_id) if guarantor_id else None
        if (guarantor_id is None or expected_parent is None
                or guarantor_id != expected_parent or guarantor is None
                or guarantor.get("credit_tier") == "DECLINED"
                or guarantor.get("credit_tier") is None):
            raise ApiError("ERR_INELIGIBLE_ISSUER",
                           "the named guarantor is not eligible")
    if kind != "CASH_COLLATERAL":
        if floor_days_between(now(), inst["expiry_date"]) < calc.MIN_TENOR_DAYS:
            raise ApiError("ERR_INSTRUMENT_TENOR_TOO_SHORT",
                           "less than 365 whole days of tenor remain")

    computed = calc.eligible_credit_support(inst, guarantor)
    if computed is None:
        raise ApiError("ERR_INELIGIBLE_ISSUER",
                       "no haircut row applies to this instrument")
    inst["haircut_pct"], inst["eligible_credit_usd"] = computed
    inst["status"] = "POSTED"
    inst["posted_at"] = now()
    touch(inst)

    svc.recompute_support_totals(deal)
    if deal["credit_status"] == "SUPPORT_SHORTFALL":
        posted = Decimal(deal["posted_credit_support_usd"])
        required = Decimal(deal.get("credit_support_required_usd") or 0)
        if posted >= required:
            deal["credit_status"] = "APPROVED"
            deal["support_cure_deadline"] = None
    touch(deal)
    return inst


@bp.route("/ppa/credit-support/<instrument_id>/release", methods=["POST"])
@endpoint(["CreditOfficer"])
def release_instrument(instrument_id):
    body()
    inst = get_instrument(instrument_id)
    deal = db.deals[inst["deal_id"]]
    if inst["status"] != "POSTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "instrument is not POSTED")
    if deal["status"] == "TERMINATED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "the deal is terminated")
    if deal["credit_status"] == "APPROVED":
        remaining = (Decimal(deal["posted_credit_support_usd"])
                     - Decimal(inst.get("eligible_credit_usd") or 0))
        if remaining < Decimal(deal.get("credit_support_required_usd") or 0):
            raise ApiError("ERR_RELEASE_BREACHES_COVERAGE",
                           "the release would breach the coverage requirement")
    inst["status"] = "RELEASED"
    inst["closed_at"] = now()
    touch(inst)
    svc.recompute_support_totals(deal)
    touch(deal)
    return inst
