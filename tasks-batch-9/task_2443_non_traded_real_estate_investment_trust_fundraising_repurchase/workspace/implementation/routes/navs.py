"""Monthly valuation records and distribution declarations — PRD §3.6, §3.7."""

from flask import Blueprint

import calc
import domain
import validate as V
from auth import require_roles, require_transition_role
from errors import fail
from routes.helpers import listing, new, resolve, single
from store import DB, all_rows, logical_date, new_row, touch

bp = Blueprint("navs", __name__)

NAV_STATES = ("DRAFT", "ADVISOR_REVIEW", "ADVISOR_CONFIRMED", "PUBLISHED",
              "SUPERSEDED")
BLOCKING_NAV_STATES = ("ADVISOR_REVIEW", "ADVISOR_CONFIRMED", "PUBLISHED")
DECLARATION_STATES = ("DECLARED", "SUPERSEDED", "PAID", "CANCELLED")

NAV_STATUS_ROLES = {
    "ADVISOR_REVIEW": ("SponsorOperator",),
    "PUBLISHED": ("SponsorOperator",),
    "ADVISOR_CONFIRMED": ("IndependentValuationAdvisor",),
    "DRAFT": ("IndependentValuationAdvisor",),
}
PAYMENT_ACTION_ROLES = {
    "PAY": ("TransferAgent",),
    "CANCEL": ("BoardCommittee",),
}

NAV_READ_ROLES = ("SponsorOperator", "IndependentValuationAdvisor",
                  "ComplianceOfficer", "TransferAgent", "InvestorUser")
DECLARATION_READ_ROLES = ("SponsorOperator", "BoardCommittee", "TransferAgent",
                          "ComplianceOfficer", "InvestorUser")


# --------------------------------------------------------------------------
# NavRecord
# --------------------------------------------------------------------------

@bp.post("/nav-records")
def create_nav_record():
    require_roles("SponsorOperator")
    body = V.json_body()
    share_class_id = V.fk(body, "share_class_id")
    start_literal, start_date = V.date_field(body, "period_start_date")
    end_literal, end_date = V.date_field(body, "period_end_date")
    if end_date < start_date:
        fail("ERR_INVALID_REQUEST",
             "period_end_date may not be earlier than period_start_date.")
    gross_asset_value = V.integer(body, "gross_asset_value_cents", minimum=0)
    other_liabilities = V.integer(body, "other_liabilities_cents", minimum=0)
    expected_version = V.integer(body, "expected_share_class_version")

    cls = resolve("share_classes", share_class_id)

    # Level 6 — optimistic concurrency (PRD §2.8).
    if expected_version != cls["version"]:
        fail("ERR_STALE_SHARE_CLASS_VERSION")

    siblings = domain.nav_records_of(cls["id"])

    # Level 9 — closed-interval overlap against non-draft siblings.
    for sibling in siblings:
        if sibling["status"] in BLOCKING_NAV_STATES and calc.periods_overlap(
                start_date, end_date, sibling["_period_start"], sibling["_period_end"]):
            fail("ERR_NAV_PERIOD_OVERLAP")

    # An overlapping DRAFT sibling is superseded rather than blocking.
    for sibling in siblings:
        if sibling["status"] == "DRAFT" and calc.periods_overlap(
                start_date, end_date, sibling["_period_start"], sibling["_period_end"]):
            sibling["status"] = "SUPERSEDED"
            touch(sibling)

    offering = domain.offering_of_class(cls)
    accrued = domain.accrued_distribution_payable_cents(cls["offering_id"], end_literal)
    snapshot = cls["shares_outstanding_e4"]
    pre, post = calc.nav_per_share(
        gross_asset_value, other_liabilities, accrued, snapshot,
        offering["initial_offering_price_cents"] if offering else 0)
    prior = domain.latest_published(cls["id"])
    variance = calc.nav_variance_bps(post, prior["nav_per_share_cents"] if prior else None)

    row = new_row("nav_records", {
        "share_class_id": cls["id"],
        "period_start_date": start_literal,
        "_period_start": start_date,
        "period_end_date": end_literal,
        "_period_end": end_date,
        "gross_asset_value_cents": gross_asset_value,
        "other_liabilities_cents": other_liabilities,
        "accrued_distribution_payable_cents": accrued,
        "shares_outstanding_e4_snapshot": snapshot,
        "nav_per_share_pre_accrual_cents": pre,
        "nav_per_share_cents": post,
        "variance_bps": variance,
        "advisor_opinion_reference": None,
        "rejection_reason": None,
        "status": "DRAFT",
    })
    touch(cls)
    domain.sync_derived()
    return new(row)


@bp.get("/nav-records")
def list_nav_records():
    require_roles(*NAV_READ_ROLES)
    limit, offset = V.pagination()
    share_class_id = V.query_string("share_class_id")
    status = V.query_enum("status", NAV_STATES)
    period_end = V.query_date("period_end_date")
    rows = [r for r in all_rows("nav_records")
            if (share_class_id is None or r["share_class_id"] == share_class_id)
            and (status is None or r["status"] == status)
            and (period_end is None or r["period_end_date"] == period_end)]
    return listing(rows, limit, offset)


@bp.get("/nav-records/<nav_record_id>")
def get_nav_record(nav_record_id):
    require_roles(*NAV_READ_ROLES)
    return single(resolve("nav_records", nav_record_id))


@bp.post("/nav-records/<nav_record_id>/status")
def drive_nav_record(nav_record_id):
    require_roles("SponsorOperator", "IndependentValuationAdvisor")
    peek = V.json_body(silent=True)
    require_transition_role(NAV_STATUS_ROLES, peek.get("to_status"))
    body = V.json_body()
    to_status = V.enum(body, "to_status", NAV_STATES)
    opinion = V.string(body, "advisor_opinion_reference", required=False,
                       default=None, min_len=0)
    rejection = V.string(body, "rejection_reason",
                         required=(to_status == "DRAFT"), default=None, min_len=0)

    record = resolve("nav_records", nav_record_id)
    current = record["status"]

    if to_status == "ADVISOR_REVIEW":
        if current != "DRAFT":
            fail("ERR_INVALID_STATE_TRANSITION")
        if logical_date() <= record["_period_end"]:
            fail("ERR_NAV_PERIOD_NOT_ELAPSED")
        record["status"] = "ADVISOR_REVIEW"
        record["rejection_reason"] = None
        touch(record)

    elif to_status == "DRAFT":
        if current != "ADVISOR_REVIEW":
            fail("ERR_INVALID_STATE_TRANSITION")
        record["status"] = "DRAFT"
        record["rejection_reason"] = rejection
        touch(record)

    elif to_status == "ADVISOR_CONFIRMED":
        if current != "ADVISOR_REVIEW":
            fail("ERR_INVALID_STATE_TRANSITION")
        if record["variance_bps"] > calc.NAV_VARIANCE_ESCALATION_BPS and not opinion:
            fail("ERR_ADVISOR_OPINION_REQUIRED")
        record["status"] = "ADVISOR_CONFIRMED"
        record["advisor_opinion_reference"] = opinion
        touch(record)

    elif to_status == "PUBLISHED":
        if current != "ADVISOR_CONFIRMED":
            fail("ERR_INVALID_STATE_TRANSITION")
        for sibling in domain.nav_records_of(record["share_class_id"]):
            if sibling["id"] == record["id"] or sibling["status"] != "PUBLISHED":
                continue
            if calc.periods_overlap(record["_period_start"], record["_period_end"],
                                    sibling["_period_start"], sibling["_period_end"]):
                fail("ERR_NAV_PERIOD_OVERLAP")
        record["status"] = "PUBLISHED"
        touch(record)
        for sibling in domain.nav_records_of(record["share_class_id"]):
            if sibling["id"] != record["id"] and sibling["status"] == "PUBLISHED":
                sibling["status"] = "SUPERSEDED"
                touch(sibling)

    else:  # SUPERSEDED is only ever reached as a cascade.
        fail("ERR_INVALID_STATE_TRANSITION")

    domain.sync_derived()
    return single(record)


# --------------------------------------------------------------------------
# DistributionDeclaration
# --------------------------------------------------------------------------

@bp.post("/distribution-declarations")
def create_declaration():
    require_roles("SponsorOperator", "BoardCommittee")
    body = V.json_body()
    offering_id = V.fk(body, "offering_id")
    record_literal, record_date = V.date_field(body, "record_date")
    payment_literal, payment_date = V.date_field(body, "payment_date")
    if payment_date < record_date:
        fail("ERR_INVALID_REQUEST", "payment_date may not precede record_date.")
    declared_per_share = V.integer(body, "declared_per_share_cents", minimum=1)
    gaap = V.integer(body, "gaap_net_income_cents")
    cash_flow = V.integer(body, "adjusted_cash_flow_cents")
    acknowledgement = V.boolean(body, "board_uncovered_acknowledgement",
                                required=False, default=False)
    expected_version = V.integer(body, "expected_offering_version")

    offering = resolve("offerings", offering_id)

    # Level 6 — optimistic concurrency (PRD §2.8).
    if expected_version != offering["version"]:
        fail("ERR_STALE_OFFERING_VERSION")

    classes = domain.classes_of(offering["id"])
    total = calc.declaration_total_cents(
        declared_per_share, [c["shares_outstanding_e4"] for c in classes])
    coverage_gaap = calc.coverage_bps(gaap, total)
    coverage_cash = calc.coverage_bps(cash_flow, total)

    # Level 10 — only the cash-flow basis gates the declaration.
    if coverage_cash < calc.FULL_COVERAGE_BPS and not acknowledgement:
        fail("ERR_UNCOVERED_DISTRIBUTION_UNACKNOWLEDGED")

    siblings = [d for d in domain.declarations_of(offering["id"])
                if d["record_date"] == record_literal]

    # Level 12 — a paid declaration may not be superseded.
    for sibling in siblings:
        if sibling["status"] == "PAID":
            fail("ERR_DECLARATION_ALREADY_PAID")

    for sibling in siblings:
        if sibling["status"] == "DECLARED":
            sibling["status"] = "SUPERSEDED"
            touch(sibling)

    row = new_row("distribution_declarations", {
        "offering_id": offering["id"],
        "record_date": record_literal,
        "_record_date": record_date,
        "payment_date": payment_literal,
        "_payment_date": payment_date,
        "declared_per_share_cents": declared_per_share,
        "gaap_net_income_cents": gaap,
        "adjusted_cash_flow_cents": cash_flow,
        "board_uncovered_acknowledgement": acknowledgement,
        "total_declared_cents": total,
        "coverage_ratio_gaap_bps": coverage_gaap,
        "coverage_ratio_cash_bps": coverage_cash,
        "return_of_capital_bps": calc.return_of_capital_bps(coverage_cash),
        "gaap_return_of_capital_bps": calc.return_of_capital_bps(coverage_gaap),
        "total_distribution_fee_accrued_cents": 0,
        "status": "DECLARED",
    })
    touch(offering)
    domain.sync_derived()
    return new(row)


@bp.get("/distribution-declarations")
def list_declarations():
    require_roles(*DECLARATION_READ_ROLES)
    limit, offset = V.pagination()
    offering_id = V.query_string("offering_id")
    status = V.query_enum("status", DECLARATION_STATES)
    record_date = V.query_date("record_date")
    rows = [d for d in all_rows("distribution_declarations")
            if (offering_id is None or d["offering_id"] == offering_id)
            and (status is None or d["status"] == status)
            and (record_date is None or d["record_date"] == record_date)]
    return listing(rows, limit, offset)


@bp.get("/distribution-declarations/<distribution_declaration_id>")
def get_declaration(distribution_declaration_id):
    require_roles(*DECLARATION_READ_ROLES)
    return single(resolve("distribution_declarations", distribution_declaration_id))


@bp.post("/distribution-declarations/<distribution_declaration_id>/payment")
def pay_declaration(distribution_declaration_id):
    require_roles("TransferAgent", "BoardCommittee")
    peek = V.json_body(silent=True)
    peeked_action = peek.get("action")
    require_transition_role(PAYMENT_ACTION_ROLES,
                            "PAY" if peeked_action is None else peeked_action)
    body = V.json_body()
    action = V.enum(body, "action", ("PAY", "CANCEL"), required=False, default="PAY")

    declaration = resolve("distribution_declarations", distribution_declaration_id)
    offering = DB["offerings"].get(declaration["offering_id"])

    if declaration["status"] != "DECLARED":
        fail("ERR_INVALID_STATE_TRANSITION")

    if action == "CANCEL":
        declaration["status"] = "CANCELLED"
        touch(declaration)
        domain.sync_derived()
        return single(declaration)

    if offering is None or offering["escrow_status"] != "BROKEN":
        fail("ERR_INVALID_STATE_TRANSITION",
             "A declaration may be paid only once the offering's escrow has broken.")
    if logical_date() < declaration["_payment_date"]:
        fail("ERR_PAYMENT_DATE_NOT_REACHED")

    _apply_payment(declaration, offering)
    domain.sync_derived()
    return single(declaration)


def _apply_payment(declaration, offering):
    """PRD §3.7 — credit holders, accrue the capped monthly trail fee, then
    convert every lot that has reached its cap."""
    class_ids = {c["id"] for c in domain.classes_of(offering["id"])}
    record_date = declaration["_record_date"]
    lots = [l for l in DB["share_lots"].values()
            if l["status"] == "OPEN" and l["share_class_id"] in class_ids
            and l["_issued_at"].date() <= record_date]
    lots = domain.lots_fifo(lots)

    # First: the distribution credit, per lot, rounded on its own.
    for lot in lots:
        credit = calc.round_half_up(
            declaration["declared_per_share_cents"] * lot["remaining_shares_e4"],
            calc.SHARE_UNIT_SCALE)
        investor = DB["investors"].get(lot["investor_id"])
        if investor is not None and credit:
            investor["cumulative_distributions_received_cents"] += credit
            touch(investor)

    # Second: the capped monthly trail fee.
    total_fee = 0
    for lot in lots:
        cls = DB["share_classes"].get(lot["share_class_id"])
        if cls is None:
            continue
        price = domain.transaction_price_cents(cls)
        value = calc.lot_value_cents(price, lot["remaining_shares_e4"])
        full_fee = calc.monthly_distribution_fee_cents(
            value, cls["annual_distribution_fee_bps"])
        headroom = max(0, lot["distribution_fee_cap_cents"]
                       - lot["cumulative_distribution_fee_cents"])
        applied = min(full_fee, headroom)
        if applied:
            lot["cumulative_distribution_fee_cents"] += applied
            touch(lot)
        total_fee += applied

    # Third: conversion, only after the capped accrual has been booked.
    for lot in lots:
        cls = DB["share_classes"].get(lot["share_class_id"])
        if cls is None or not cls["converts_to_class_code"]:
            continue
        if lot["cumulative_distribution_fee_cents"] < lot["distribution_fee_cap_cents"]:
            continue
        destination = None
        for candidate in domain.classes_of(cls["offering_id"]):
            if candidate["class_code"] == cls["converts_to_class_code"]:
                destination = candidate
                break
        if destination is None:
            continue
        from_price = domain.transaction_price_cents(cls)
        to_price = domain.transaction_price_cents(destination)
        new_shares = calc.converted_shares_e4(
            lot["remaining_shares_e4"], from_price, to_price)
        lot["converted_from_share_class_id"] = cls["id"]
        lot["share_class_id"] = destination["id"]
        lot["original_shares_e4"] = new_shares
        lot["remaining_shares_e4"] = new_shares
        touch(lot)

    declaration["status"] = "PAID"
    declaration["total_distribution_fee_accrued_cents"] = total_fee
    touch(declaration)
