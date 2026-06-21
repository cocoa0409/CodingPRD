"""Deal, Proposal, CommissionSplit, Comp endpoints + Deal state machine."""
from flask import Blueprint, request

from db import db, new_full_record, touch
from errors import err
from middleware import authenticate, require_role
from response import success, list_response
from serialize import serialize, serialize_many
from services.access import (resolve, resolve_fk, deal_party)
from services.calc import net_effective_rent
from services.deal_engine import (latest_pending_proposal,
                                  bubble_requirement_to_negotiating,
                                  bubble_listing_to_under_negotiation,
                                  reconcile_requirement_after_kill,
                                  compute_deal_financials, space_to_under_loi,
                                  execute_deal_cascade, kill_deal_cascade)
from services.recompute import (recompute_deal_round_count,
                                recompute_listing_open_deal_count,
                                reconcile_listing_status)
from validate import (parse_body, check_str_type, check_int_type,
                      check_number_type, parse_pagination, paginate)

bp = Blueprint("deals", __name__)


# ---------------------------------------------------------------------------
# Deal CRUD
# ---------------------------------------------------------------------------
@bp.post("/deals")
def create_deal():
    user_id, role = authenticate()
    require_role(role, ["ListingBroker", "TenantBroker"])
    body = parse_body()
    listing_id = check_str_type(body, "listing_id", required=True)
    requirement_id = check_str_type(body, "requirement_id", required=True)
    lst = resolve_fk(db.listings, listing_id)
    req = resolve_fk(db.requirements, requirement_id)
    listing_broker_id = lst["listing_broker_id"]
    procuring_broker_id = req["tenant_broker_id"]
    # Ownership / party membership (priority 4)
    if role == "ListingBroker" and listing_broker_id != user_id:
        raise err("ERR_NOT_OWNER", "Acting broker is not the listing party")
    if role == "TenantBroker" and procuring_broker_id != user_id:
        raise err("ERR_NOT_OWNER", "Acting broker is not the procuring party")
    # Listing non-terminal (priority 9)
    if lst["status"] in ("WITHDRAWN", "EXECUTED"):
        raise err("ERR_LISTING_NOT_NEGOTIABLE", "Listing is terminal")
    # Requirement active (priority 10)
    if req["status"] not in ("OPEN", "TOURING", "NEGOTIATING"):
        raise err("ERR_REQUIREMENT_NOT_ACTIVE", "Requirement not active")
    # Acting broker not suspended (priority 16)
    acting = db.brokers.get(user_id)
    if acting is not None and acting["status"] == "SUSPENDED":
        raise err("ERR_BROKER_SUSPENDED", "Acting broker is suspended")
    # is_co_broke: brokers in different brokerages
    lb = db.brokers.get(listing_broker_id)
    pb = db.brokers.get(procuring_broker_id)
    is_co_broke = (lb is not None and pb is not None and
                   lb["brokerage_id"] != pb["brokerage_id"])
    rec = new_full_record({
        "listing_id": listing_id,
        "requirement_id": requirement_id,
        "listing_broker_id": listing_broker_id,
        "procuring_broker_id": procuring_broker_id,
        "is_co_broke": is_co_broke,
        "stage": "PROSPECT",
        "round_count": 0,
        "accepted_proposal_id": None,
        "total_consideration": 0,
        "total_commission": 0,
    })
    db.deals[rec["id"]] = rec
    return success(serialize("Deal", rec), status=201)


@bp.get("/deals/<deal_id>")
def get_deal(deal_id):
    _, role = authenticate()
    require_role(role, ["BrokerageAdmin", "ListingBroker", "TenantBroker"])
    rec = resolve(db.deals, deal_id)
    return success(serialize("Deal", rec), status=200)


@bp.get("/deals")
def list_deals():
    _, role = authenticate()
    require_role(role, ["BrokerageAdmin", "ListingBroker", "TenantBroker"])
    limit, offset = parse_pagination()
    items = list(db.deals.values())
    for f in ("listing_id", "requirement_id", "listing_broker_id",
              "procuring_broker_id", "accepted_proposal_id", "stage"):
        v = request.args.get(f)
        if v is not None:
            items = [d for d in items if d.get(f) == v]
    page, total = paginate(items, limit, offset)
    return list_response(serialize_many("Deal", page), limit, offset, total)


# ---------------------------------------------------------------------------
# Proposals
# ---------------------------------------------------------------------------
def _author_side_matches(deal, role, user_id, from_side):
    """The author must be on the side they claim (PRD §3.5)."""
    if from_side == "LISTING":
        return user_id == deal["listing_broker_id"]
    if from_side == "TENANT":
        return user_id == deal["procuring_broker_id"]
    return False


@bp.post("/deals/<deal_id>/proposals")
def submit_proposal(deal_id):
    user_id, role = authenticate()
    require_role(role, ["ListingBroker", "TenantBroker"])
    deal = resolve(db.deals, deal_id)
    deal_party(user_id, role, deal)
    body = parse_body()
    from_side = check_str_type(body, "from_side", required=True)
    base_rent = check_number_type(body, "base_rent_psf_yr", required=True)
    term_months = check_int_type(body, "term_months", required=True)
    expected_version = check_int_type(body, "expected_deal_version", required=True)
    free_rent_months = check_int_type(body, "free_rent_months",
                                      required=False, default=0)
    ti_allowance = check_number_type(body, "ti_allowance_psf",
                                     required=False, default=0)
    escalation = check_number_type(body, "annual_escalation_pct",
                                   required=False, default=0.03)
    # field constraints (priority 5)
    if from_side not in ("LISTING", "TENANT"):
        raise err("ERR_INVALID_REQUEST", "Invalid from_side")
    if base_rent <= 0:
        raise err("ERR_INVALID_REQUEST", "base_rent_psf_yr must be > 0")
    if term_months < 1:
        raise err("ERR_INVALID_REQUEST", "term_months must be >= 1")
    if not (0 <= free_rent_months <= 24):
        raise err("ERR_INVALID_REQUEST", "free_rent_months out of range")
    if ti_allowance < 0:
        raise err("ERR_INVALID_REQUEST", "ti_allowance_psf must be >= 0")
    if not (0 <= escalation <= 0.20):
        raise err("ERR_INVALID_REQUEST", "annual_escalation_pct out of range")
    # OCC (priority 6)
    if expected_version != deal["version"]:
        raise err("ERR_STALE_DEAL_VERSION", "Deal version is stale")
    # state check (priority 7)
    if deal["stage"] not in ("PROSPECT", "LOI_DRAFT", "LOI_COUNTERED"):
        raise err("ERR_INVALID_STATE", "Cannot author proposal in current stage")

    lst = db.listings.get(deal["listing_id"])
    req = db.requirements.get(deal["requirement_id"])

    if deal["stage"] == "PROSPECT":
        # First proposal. Side must be the side they claim (priority 8)
        if not _author_side_matches(deal, role, user_id, from_side):
            raise err("ERR_WRONG_SIDE", "Author is not on the claimed side")
        # Listing negotiable (priority 9)
        if lst["status"] not in ("ACTIVE", "UNDER_NEGOTIATION"):
            raise err("ERR_LISTING_NOT_NEGOTIABLE", "Listing not negotiable")
        # Requirement active (priority 10)
        if req["status"] not in ("OPEN", "TOURING", "NEGOTIATING"):
            raise err("ERR_REQUIREMENT_NOT_ACTIVE", "Requirement not active")
        # Broker not suspended (priority 16)
        acting = db.brokers.get(user_id)
        if acting is not None and acting["status"] == "SUSPENDED":
            raise err("ERR_BROKER_SUSPENDED", "Acting broker is suspended")
        proposal = _create_proposal(deal, from_side, base_rent, term_months,
                                    free_rent_months, ti_allowance, escalation)
        deal["stage"] = "LOI_DRAFT"
        bubble_listing_to_under_negotiation(deal["listing_id"])
        bubble_requirement_to_negotiating(deal["requirement_id"])
        recompute_listing_open_deal_count(deal["listing_id"])
    else:
        # Counter from opposite side. Wrong-side (priority 8) before
        # broker-suspended (priority 16) per PRD §2.10.
        latest = latest_pending_proposal(deal["id"])
        if not _author_side_matches(deal, role, user_id, from_side):
            raise err("ERR_WRONG_SIDE", "Author is not on the claimed side")
        if latest is not None and from_side == latest["from_side"]:
            raise err("ERR_WRONG_SIDE", "Counter must come from the opposite side")
        acting = db.brokers.get(user_id)
        if acting is not None and acting["status"] == "SUSPENDED":
            raise err("ERR_BROKER_SUSPENDED", "Acting broker is suspended")
        # flip latest PENDING -> COUNTERED
        if latest is not None:
            latest["outcome"] = "COUNTERED"
            touch(latest)
        proposal = _create_proposal(deal, from_side, base_rent, term_months,
                                    free_rent_months, ti_allowance, escalation)
        deal["stage"] = "LOI_COUNTERED"

    recompute_deal_round_count(deal["id"])
    touch(deal)  # increments Deal.version by 1
    return success(serialize("Proposal", proposal), status=201)


def _create_proposal(deal, from_side, base_rent, term_months, free_rent_months,
                     ti_allowance, escalation):
    ner = net_effective_rent(base_rent, term_months, free_rent_months,
                             ti_allowance, escalation)
    rec = new_full_record({
        "deal_id": deal["id"],
        "from_side": from_side,
        "base_rent_psf_yr": base_rent,
        "term_months": term_months,
        "free_rent_months": free_rent_months,
        "ti_allowance_psf": ti_allowance,
        "annual_escalation_pct": escalation,
        "outcome": "PENDING",
        "net_effective_rent_psf_yr": ner,
    })
    db.proposals[rec["id"]] = rec
    return rec


@bp.get("/deals/<deal_id>/proposals")
def list_deal_proposals(deal_id):
    _, role = authenticate()
    require_role(role, ["BrokerageAdmin", "ListingBroker", "TenantBroker"])
    resolve(db.deals, deal_id)
    limit, offset = parse_pagination()
    items = [p for p in db.proposals.values() if p["deal_id"] == deal_id]
    page, total = paginate(items, limit, offset)
    return list_response(serialize_many("Proposal", page), limit, offset, total)


@bp.get("/proposals/<proposal_id>")
def get_proposal(proposal_id):
    _, role = authenticate()
    require_role(role, ["BrokerageAdmin", "ListingBroker", "TenantBroker"])
    rec = resolve(db.proposals, proposal_id)
    return success(serialize("Proposal", rec), status=200)


@bp.get("/proposals")
def list_proposals():
    _, role = authenticate()
    require_role(role, ["BrokerageAdmin", "ListingBroker", "TenantBroker"])
    limit, offset = parse_pagination()
    items = list(db.proposals.values())
    for f in ("deal_id", "from_side", "outcome"):
        v = request.args.get(f)
        if v is not None:
            items = [p for p in items if p.get(f) == v]
    page, total = paginate(items, limit, offset)
    return list_response(serialize_many("Proposal", page), limit, offset, total)


# ---------------------------------------------------------------------------
# Accept / lease-out / execute / kill
# ---------------------------------------------------------------------------
@bp.post("/deals/<deal_id>/accept")
def accept_deal(deal_id):
    user_id, role = authenticate()
    require_role(role, ["ListingBroker", "TenantBroker"])
    deal = resolve(db.deals, deal_id)
    deal_party(user_id, role, deal)
    body = parse_body()
    from_side = check_str_type(body, "from_side", required=True)
    expected_version = check_int_type(body, "expected_deal_version", required=True)
    if from_side not in ("LISTING", "TENANT"):
        raise err("ERR_INVALID_REQUEST", "Invalid from_side")
    # OCC (priority 6)
    if expected_version != deal["version"]:
        raise err("ERR_STALE_DEAL_VERSION", "Deal version is stale")
    # state check (priority 7)
    if deal["stage"] not in ("LOI_DRAFT", "LOI_COUNTERED"):
        raise err("ERR_INVALID_STATE", "Deal not acceptable from current stage")
    latest = latest_pending_proposal(deal["id"])
    # Acceptor must be the side that did NOT author the latest PENDING proposal,
    # and must be authoring on their own claimed side (priority 8)
    if not _author_side_matches(deal, role, user_id, from_side):
        raise err("ERR_WRONG_SIDE", "Acceptor side mismatch")
    if latest is not None and from_side == latest["from_side"]:
        raise err("ERR_WRONG_SIDE", "Acceptor authored the latest proposal")
    # Space availability (priority 11)
    sp = _deal_space(deal)
    if sp is None or sp["status"] not in ("AVAILABLE", "ON_HOLD"):
        raise err("ERR_SPACE_NOT_AVAILABLE", "Space not available to accept")
    # apply
    if latest is not None:
        latest["outcome"] = "ACCEPTED"
        touch(latest)
        deal["accepted_proposal_id"] = latest["id"]
        compute_deal_financials(deal, latest)
    deal["stage"] = "LOI_ACCEPTED"
    space_to_under_loi(deal)
    touch(deal)
    return success(serialize("Deal", deal), status=200)


def _deal_space(deal):
    lst = db.listings.get(deal["listing_id"])
    if lst is None:
        return None
    return db.spaces.get(lst["space_id"])


@bp.post("/deals/<deal_id>/lease-out")
def lease_out_deal(deal_id):
    user_id, role = authenticate()
    require_role(role, ["ListingBroker"])
    deal = resolve(db.deals, deal_id)
    deal_party(user_id, role, deal)
    body = parse_body()
    expected_version = check_int_type(body, "expected_deal_version", required=True)
    if expected_version != deal["version"]:
        raise err("ERR_STALE_DEAL_VERSION", "Deal version is stale")
    if deal["stage"] != "LOI_ACCEPTED":
        raise err("ERR_INVALID_STATE", "Deal not in LOI_ACCEPTED")
    sp = _deal_space(deal)
    if sp is None or sp["status"] != "UNDER_LOI":
        raise err("ERR_SPACE_NOT_AVAILABLE", "Space not UNDER_LOI")
    deal["stage"] = "LEASE_OUT"
    touch(deal)
    return success(serialize("Deal", deal), status=200)


@bp.post("/deals/<deal_id>/execute")
def execute_deal(deal_id):
    user_id, role = authenticate()
    require_role(role, ["ListingBroker"])
    deal = resolve(db.deals, deal_id)
    deal_party(user_id, role, deal)
    body = parse_body()
    expected_version = check_int_type(body, "expected_deal_version", required=True)
    if expected_version != deal["version"]:
        raise err("ERR_STALE_DEAL_VERSION", "Deal version is stale")
    if deal["stage"] != "LEASE_OUT":
        raise err("ERR_INVALID_STATE", "Deal not in LEASE_OUT")
    sp = _deal_space(deal)
    if sp is None or sp["status"] != "UNDER_LOI":
        raise err("ERR_SPACE_NOT_AVAILABLE", "Space not UNDER_LOI")
    deal["stage"] = "EXECUTED"
    execute_deal_cascade(deal)
    touch(deal)
    return success(serialize("Deal", deal), status=200)


@bp.post("/deals/<deal_id>/kill")
def kill_deal(deal_id):
    user_id, role = authenticate()
    require_role(role, ["ListingBroker", "TenantBroker"])
    deal = resolve(db.deals, deal_id)
    deal_party(user_id, role, deal)
    body = parse_body()
    expected_version = check_int_type(body, "expected_deal_version", required=True)
    if expected_version != deal["version"]:
        raise err("ERR_STALE_DEAL_VERSION", "Deal version is stale")
    if deal["stage"] not in ("PROSPECT", "LOI_DRAFT", "LOI_COUNTERED", "LOI_ACCEPTED"):
        raise err("ERR_INVALID_STATE", "Deal cannot be killed from current stage")
    kill_deal_cascade(deal, reconcile_parents=True)
    return success(serialize("Deal", deal), status=200)


# ---------------------------------------------------------------------------
# CommissionSplit (read-only)
# ---------------------------------------------------------------------------
@bp.get("/commission-splits/<split_id>")
def get_commission_split(split_id):
    _, role = authenticate()
    require_role(role, ["BrokerageAdmin", "ListingBroker", "TenantBroker"])
    rec = resolve(db.commission_splits, split_id)
    return success(serialize("CommissionSplit", rec), status=200)


@bp.get("/commission-splits")
def list_commission_splits():
    _, role = authenticate()
    require_role(role, ["BrokerageAdmin", "ListingBroker", "TenantBroker"])
    limit, offset = parse_pagination()
    items = list(db.commission_splits.values())
    for f in ("deal_id", "broker_id"):
        v = request.args.get(f)
        if v is not None:
            items = [s for s in items if s.get(f) == v]
    page, total = paginate(items, limit, offset)
    return list_response(serialize_many("CommissionSplit", page), limit, offset, total)


# ---------------------------------------------------------------------------
# Comp (read-only)
# ---------------------------------------------------------------------------
@bp.get("/comps/<comp_id>")
def get_comp(comp_id):
    _, role = authenticate()
    require_role(role, ["BrokerageAdmin", "ListingBroker", "TenantBroker"])
    rec = resolve(db.comps, comp_id)
    return success(serialize("Comp", rec), status=200)


@bp.get("/comps")
def list_comps():
    _, role = authenticate()
    require_role(role, ["BrokerageAdmin", "ListingBroker", "TenantBroker"])
    limit, offset = parse_pagination()
    items = list(db.comps.values())
    for f in ("space_id", "deal_id", "market"):
        v = request.args.get(f)
        if v is not None:
            items = [c for c in items if c.get(f) == v]
    page, total = paginate(items, limit, offset)
    return list_response(serialize_many("Comp", page), limit, offset, total)
