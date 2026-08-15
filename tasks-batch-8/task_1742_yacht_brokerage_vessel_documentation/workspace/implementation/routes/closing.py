"""Closing statements: create, build, approve, reopen, void, disburse,
tax assessments."""
from flask import Blueprint, request
from db import db, clock
from errors import (err_duplicate, err_invalid_state, err_invalid_request,
                    err_stale_version, err_offer_not_accepted,
                    err_contingency_unresolved, err_liens_outstanding,
                    err_segregation)
from middleware import (get_caller, require_roles, get_json_body, require_fields,
                        check_enum, parse_pagination, paginate)
from response import success_object, success_list
from services.calculations import (commission_split, sales_tax_for, use_tax_credit,
                                   prorations_cents, final_interest,
                                   documentation_fee)
from services.common import (new_entity, touch, get_or_404, serialize_statement,
                             serialize_tax_assessment)
from services.events import emit

bp = Blueprint("closing", __name__)

ROUNDING_MODES = {"PER_LINE_THEN_SUM", "SUM_THEN_PER_LINE"}
US_STATES = {"FL", "CA", "WA", "NY", "TX", "RI", "MD", "NC", "SC", "MA", "GA", "NJ"}


def _offer_statement(offer_id):
    """The single non-VOIDED statement for an offer, if any."""
    return next((s for s in db.statements.values()
                 if s["offer_id"] == offer_id and s["status"] != "VOIDED"), None)


def _contingencies_resolved(offer_id):
    for c in db.contingencies.values():
        if c["offer_id"] == offer_id and c["status"] not in ("SATISFIED", "WAIVED"):
            return False
    return True


def _run_pipeline(stmt, offer, listing, vessel):
    """Run all five calculations in pinned order and write computed fields."""
    # 1. commission_split (depends on gross only)
    stmt["gross_price_cents"] = offer["offer_price_cents"]
    tier = listing.get("commission_tier_code")
    if not tier:
        brokerage = db.brokerages.get(listing["brokerage_id"])
        tier = brokerage["default_commission_tier_code"] if brokerage else "STANDARD"
    selling_agent = db.agents.get(offer["selling_agent_id"])
    same_house = (selling_agent is not None
                  and selling_agent["brokerage_id"] == listing["brokerage_id"])
    commission, listing_side, selling_side = commission_split(
        stmt["gross_price_cents"], tier, same_house)
    stmt["commission_cents"] = commission
    stmt["listing_side_cents"] = listing_side
    stmt["selling_side_cents"] = selling_side

    # 2. sales_use_tax (depends on gross; NOT on commission)
    # Void any prior assessments from a previous build/reopen, then recreate.
    for t in list(db.tax_assessments.values()):
        if t["closing_statement_id"] == stmt["id"]:
            del db.tax_assessments[t["id"]]
    buyer = db.clients.get(offer["buyer_id"])
    if offer.get("offshore_delivery"):
        # Offshore delivery exemption: basis and amount zero; assessment EXEMPT
        stmt["tax_cents"] = 0
        t = new_entity()
        t["closing_statement_id"] = stmt["id"]
        t["assessment_kind"] = "SALES_TAX"
        t["situs_state_code"] = offer["settlement_state_code"]
        t["basis_cents"] = 0
        t["amount_cents"] = 0
        t["exemption_code"] = "OFFSHORE_DELIVERY"
        t["status"] = "EXEMPT"
        db.tax_assessments[t["id"]] = t
    else:
        situs = offer["settlement_state_code"]
        basis, amount = sales_tax_for(stmt["gross_price_cents"], situs)
        stmt["tax_cents"] = amount
        t = new_entity()
        t["closing_statement_id"] = stmt["id"]
        t["assessment_kind"] = "SALES_TAX"
        t["situs_state_code"] = situs
        t["basis_cents"] = basis
        t["amount_cents"] = amount
        t["exemption_code"] = "NONE"
        t["status"] = "ASSESSED"
        db.tax_assessments[t["id"]] = t
        # Use-tax credit: buyer residency differs from situs and home state grants credit
        if buyer is not None:
            home = buyer["residency_state_code"]
            if home != situs and home in US_STATES:
                credit_due = use_tax_credit(basis, home, amount)
                if credit_due > 0:
                    u = new_entity()
                    u["closing_statement_id"] = stmt["id"]
                    u["assessment_kind"] = "USE_TAX"
                    u["situs_state_code"] = home
                    u["basis_cents"] = basis
                    u["amount_cents"] = credit_due
                    u["exemption_code"] = "NONE"
                    u["status"] = "ASSESSED"
                    db.tax_assessments[u["id"]] = u

    # 3. proration_aggregator (depends on clock)
    stmt["prorations_cents"] = prorations_cents()

    # 4. lien_payoff_waterfall — pool = gross - commission - tax + prorations
    pool = (stmt["gross_price_cents"] - stmt["commission_cents"]
            - stmt["tax_cents"] + stmt["prorations_cents"])
    if pool < 0:
        pool = 0
    # Reset prior waterfall effects so a rebuild/reopen re-derives from scratch:
    # liens satisfied or partially satisfied by an earlier build return to
    # RECORDED with zero payoff; RELEASED liens stay released.
    for l in db.liens.values():
        if l["vessel_id"] == vessel["id"] and l["status"] in ("SATISFIED", "PARTIALLY_SATISFIED"):
            l["status"] = "RECORDED"
            l["payoff_amount_cents"] = 0
            touch(l)
    liens = sorted(
        [l for l in db.liens.values()
         if l["vessel_id"] == vessel["id"] and l["status"] == "RECORDED"],
        key=lambda x: (x["priority_rank"], x["created_at"]))
    remaining = pool
    lien_payoff_total = 0
    for lien in liens:
        alloc = min(remaining, lien["amount_cents"])
        if alloc < 0:
            alloc = 0
        lien["payoff_amount_cents"] = alloc
        remaining -= alloc
        if alloc == lien["amount_cents"] and lien["amount_cents"] > 0:
            lien["status"] = "SATISFIED"
            lien_payoff_total += alloc
        elif alloc == 0 and lien["amount_cents"] == 0:
            lien["status"] = "SATISFIED"
        elif alloc > 0:
            lien["status"] = "PARTIALLY_SATISFIED"
        else:
            lien["status"] = "RECORDED"
        touch(lien)
    # Also count liens already SATISFIED/RELEASED toward payoff totals only if
    # they were satisfied by this waterfall (payoff set above).
    stmt["lien_payoff_total_cents"] = lien_payoff_total

    # Recompute vessel liens_status
    open_liens = [l for l in db.liens.values()
                  if l["vessel_id"] == vessel["id"]
                  and l["status"] in ("RECORDED", "PARTIALLY_SATISFIED")]
    vessel["liens_status"] = "ENCUMBERED" if open_liens else "CLEAN"

    # 5. closing_total
    stmt["escrow_applied_cents"] = sum(
        e["amount_cents"] for e in db.escrow_entries.values()
        if e["offer_id"] == offer["id"] and e["entry_type"] == "DEPOSIT"
        and e["status"] == "CLEARED")
    stmt["seller_net_cents"] = (stmt["gross_price_cents"] - stmt["commission_cents"]
                                - stmt["tax_cents"] - stmt["lien_payoff_total_cents"]
                                + stmt["prorations_cents"])
    stmt["buyer_due_cents"] = (stmt["gross_price_cents"] + stmt["tax_cents"]
                               - stmt["escrow_applied_cents"])
    # Documentation fee (final variant uses statement gross price)
    stmt["documentation_fee_cents"] = documentation_fee(
        vessel["documentation_mode"], vessel["length_overall_ft"],
        stmt["gross_price_cents"], offer["settlement_state_code"])
    # Final escrow interest accrual (supersedes provisional) — informational
    stmt["escrow_interest_final_cents"] = sum(
        final_interest(e["amount_cents"], e["value_date"])
        for e in db.escrow_entries.values()
        if e["offer_id"] == offer["id"] and e["entry_type"] == "DEPOSIT"
        and e["status"] == "CLEARED")


@bp.route("/yacht/closing-statements", methods=["POST"])
def create_statement():
    caller = get_caller()
    require_roles(caller, ["ClosingOfficer"])
    body = get_json_body()
    require_fields(body, ["offer_id", "rounding_mode"])
    offer = get_or_404(db.offers, body["offer_id"], "Offer")
    check_enum(body, "rounding_mode", ROUNDING_MODES)
    # Priority 9: one statement per offer
    if _offer_statement(offer["id"]) is not None:
        raise err_duplicate("A closing statement already exists for this offer")
    # Offer must be ACCEPTED
    if offer["status"] != "ACCEPTED":
        raise err_offer_not_accepted()

    s = new_entity()
    s["offer_id"] = offer["id"]
    s["gross_price_cents"] = 0
    s["commission_cents"] = 0
    s["listing_side_cents"] = 0
    s["selling_side_cents"] = 0
    s["tax_cents"] = 0
    s["prorations_cents"] = 0
    s["escrow_applied_cents"] = 0
    s["lien_payoff_total_cents"] = 0
    s["seller_net_cents"] = 0
    s["buyer_due_cents"] = 0
    s["rounding_mode"] = body["rounding_mode"]
    s["status"] = "DRAFT"
    s["built_by_role"] = None
    s["documentation_fee_cents"] = 0
    db.statements[s["id"]] = s
    return success_object(serialize_statement(s), 201)


@bp.route("/yacht/closing-statements/<sid>", methods=["GET"])
def get_statement(sid):
    caller = get_caller()
    require_roles(caller, ["PlatformAdmin", "ListingAgent", "SellingAgent",
                           "ClosingOfficer", "EscrowOfficer"])
    s = get_or_404(db.statements, sid, "ClosingStatement")
    return success_object(serialize_statement(s))


@bp.route("/yacht/closing-statements", methods=["GET"])
def list_statements():
    caller = get_caller()
    require_roles(caller, ["PlatformAdmin", "ListingAgent", "SellingAgent",
                           "ClosingOfficer", "EscrowOfficer"])
    limit, offset = parse_pagination()
    items = sorted(db.statements.values(), key=lambda x: x["created_at"])
    for f in ("offer_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [s for s in items if s[f] == v]
    page, total = paginate(items, limit, offset)
    return success_list([serialize_statement(s) for s in page], limit, offset, total)


@bp.route("/yacht/closing-statements/<sid>/build", methods=["POST"])
def build_statement(sid):
    caller = get_caller()
    require_roles(caller, ["ClosingOfficer"])
    s = get_or_404(db.statements, sid, "ClosingStatement")
    body = get_json_body()
    if s["status"] != "DRAFT":
        raise err_invalid_state("Statement must be DRAFT to build")
    offer = get_or_404(db.offers, s["offer_id"], "Offer")
    # OCC on the offer (priority 6)
    expected = body.get("expected_offer_version")
    if expected is None:
        raise err_invalid_request("expected_offer_version is required")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise err_invalid_request("expected_offer_version must be an integer")
    if expected != offer["version"]:
        raise err_stale_version()
    if offer["status"] != "ACCEPTED":
        raise err_offer_not_accepted()
    if not _contingencies_resolved(offer["id"]):
        raise err_contingency_unresolved()

    listing = db.listings.get(offer["listing_id"])
    vessel = db.vessels.get(listing["vessel_id"]) if listing else None
    _run_pipeline(s, offer, listing, vessel)
    s["status"] = "BALANCED"
    s["built_by_role"] = caller.role
    touch(s)
    emit("ClosingStatement", s["id"], "CLOSING_BALANCED", caller.role, caller.user_id,
         {"status": "BALANCED", "seller_net_cents": s["seller_net_cents"],
          "buyer_due_cents": s["buyer_due_cents"]})
    return success_object(serialize_statement(s))


@bp.route("/yacht/closing-statements/<sid>/approve", methods=["POST"])
def approve_statement(sid):
    caller = get_caller()
    require_roles(caller, ["ListingAgent"])
    s = get_or_404(db.statements, sid, "ClosingStatement")
    body = get_json_body()
    if s["status"] != "BALANCED":
        raise err_invalid_state("Statement must be BALANCED to approve")
    # OCC on statement (priority 6) precedes segregation check (priority 8)
    expected = body.get("expected_statement_version")
    if expected is None:
        raise err_invalid_request("expected_statement_version is required")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise err_invalid_request("expected_statement_version must be an integer")
    if expected != s["version"]:
        raise err_stale_version()
    # Segregation of duties: builder role may not approve
    if s.get("built_by_role") is not None and s["built_by_role"] == caller.role:
        raise err_segregation()
    s["status"] = "APPROVED"
    touch(s)
    emit("ClosingStatement", s["id"], "CLOSING_APPROVED", caller.role, caller.user_id,
         {"status": "APPROVED"})
    return success_object(serialize_statement(s))


@bp.route("/yacht/closing-statements/<sid>/reopen", methods=["POST"])
def reopen_statement(sid):
    caller = get_caller()
    require_roles(caller, ["ClosingOfficer"])
    s = get_or_404(db.statements, sid, "ClosingStatement")
    get_json_body()
    if s["status"] != "APPROVED":
        raise err_invalid_state("Statement must be APPROVED to reopen")
    # Allowed only while no escrow entry on the offer has been DISBURSED
    for e in db.escrow_entries.values():
        if e["offer_id"] == s["offer_id"] and e["status"] == "DISBURSED":
            raise err_invalid_state("An escrow entry has already been disbursed")
    offer = db.offers.get(s["offer_id"])
    listing = db.listings.get(offer["listing_id"]) if offer else None
    vessel = db.vessels.get(listing["vessel_id"]) if listing else None
    _run_pipeline(s, offer, listing, vessel)
    s["status"] = "BALANCED"
    touch(s)
    return success_object(serialize_statement(s))


@bp.route("/yacht/closing-statements/<sid>/void", methods=["POST"])
def void_statement(sid):
    caller = get_caller()
    require_roles(caller, ["ClosingOfficer"])
    s = get_or_404(db.statements, sid, "ClosingStatement")
    get_json_body()
    if s["status"] not in ("DRAFT", "BALANCED"):
        raise err_invalid_state("Only DRAFT or BALANCED statements may be voided")
    was_balanced = s["status"] == "BALANCED"
    s["status"] = "VOIDED"
    touch(s)
    if was_balanced:
        for t in db.tax_assessments.values():
            if t["closing_statement_id"] == s["id"]:
                t["status"] = "VOIDED"
                touch(t)
    return success_object(serialize_statement(s))


@bp.route("/yacht/closing-statements/<sid>/disburse", methods=["POST"])
def disburse_statement(sid):
    caller = get_caller()
    require_roles(caller, ["ClosingOfficer"])
    s = get_or_404(db.statements, sid, "ClosingStatement")
    get_json_body()
    if s["status"] != "APPROVED":
        raise err_invalid_state("Statement must be APPROVED to disburse")
    offer = get_or_404(db.offers, s["offer_id"], "Offer")
    listing = db.listings.get(offer["listing_id"])
    vessel = db.vessels.get(listing["vessel_id"]) if listing else None

    # Contingency gate
    if not _contingencies_resolved(offer["id"]):
        raise err_contingency_unresolved()
    # Liens gate (priority 18)
    if vessel is not None and vessel["liens_status"] != "CLEAN":
        # Distinguish a waterfall shortfall from a never-computed payoff
        partial = any(l["vessel_id"] == vessel["id"] and l["status"] == "PARTIALLY_SATISFIED"
                      for l in db.liens.values())
        if partial:
            from errors import err_waterfall_shortfall
            raise err_waterfall_shortfall()
        raise err_liens_outstanding()
    # Every CLEARED DEPOSIT on the offer must have been released to DISBURSED
    for e in db.escrow_entries.values():
        if e["offer_id"] == offer["id"] and e["entry_type"] == "DEPOSIT" \
                and e["status"] == "CLEARED":
            raise err_invalid_state("A CLEARED deposit has not been released")
    # Title transfer must be EXECUTED
    transfer = next((t for t in db.title_transfers.values()
                     if t["closing_statement_id"] == s["id"]
                     and t["status"] in ("DRAFT", "EXECUTED", "RECORDED")), None)
    if transfer is None or transfer["status"] != "EXECUTED":
        raise err_invalid_state("Title transfer must be EXECUTED")

    # Fan-out cascade
    s["status"] = "DISBURSED"
    touch(s)
    offer["status"] = "CLOSED"
    touch(offer)
    if listing is not None:
        listing["status"] = "CLOSED"
        touch(listing)
    transfer["status"] = "RECORDED"
    touch(transfer)
    for d in db.doc_records.values():
        if d["vessel_id"] == transfer["vessel_id"] and d["status"] == "VALID":
            d["status"] = "TRANSFERRED"
            touch(d)
    for t in db.tax_assessments.values():
        if t["closing_statement_id"] == s["id"] and t["status"] == "ASSESSED":
            t["status"] = "FILED"
            touch(t)
    emit("ClosingStatement", s["id"], "CLOSING_DISBURSED", caller.role, caller.user_id,
         {"status": "DISBURSED"})
    return success_object(serialize_statement(s))


@bp.route("/yacht/closing-statements/<sid>/tax-assessments", methods=["GET"])
def list_tax_assessments(sid):
    caller = get_caller()
    require_roles(caller, ["PlatformAdmin", "ListingAgent", "SellingAgent",
                           "ClosingOfficer", "EscrowOfficer"])
    s = get_or_404(db.statements, sid, "ClosingStatement")
    items = sorted([t for t in db.tax_assessments.values()
                    if t["closing_statement_id"] == s["id"]],
                   key=lambda x: x["created_at"])
    return success_list([serialize_tax_assessment(t) for t in items],
                        len(items) or 10, 0, len(items))
