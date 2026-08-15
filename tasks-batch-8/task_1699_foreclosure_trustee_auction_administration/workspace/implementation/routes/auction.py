"""Auction routes: sales, postponements (OCC on sale version), bidder
registration/qualification, bids, conduct/close/void, trustee's deeds.

Orderings (PRD §3.8):
  postpone:  schema -> sale SCHEDULED -> staleness -> venue -> 3-cap -> window
  review:    schema -> sale state -> registration state -> deposit test last
  bid:       ownership -> schema -> sale CONDUCTED -> registration QUALIFIED
             -> minimum next bid
  conduct:   sale state -> case state -> hold -> ACTIVE instruction -> today
  close:     case state -> sale state -> hold
  void:      sale CONDUCTED/CLOSED -> voidability (no recorded deed, no
             surplus disbursements)
"""
from datetime import timedelta
from flask import Blueprint, request

import db
from db import stamp_new, touch, now_iso
from errors import (err_invalid_request, err_invalid_case_state,
                    err_invalid_sale_state, err_invalid_registration_state,
                    err_invalid_deed_state, err_stale_sale_version,
                    err_auction_conflict, err_postponement_limit,
                    err_postponement_window, err_active_stay,
                    err_no_active_instruction, err_sale_not_today,
                    err_bid_too_low, err_deposit_insufficient,
                    err_sale_not_voidable, err_bidder_ownership,
                    err_deed_late)
from middleware import require_roles
from response import success_object, success_list, parse_pagination
from services import calc
from services.domain import (get_case, get_sale, get_registration, get_deed,
                             view, case_sales, sale_postponements,
                             sale_registrations, sale_bids,
                             registration_bids, sale_deeds,
                             active_instruction, get_beneficiary)
from services.validate import (get_body, check_unknown, req_string, req_int,
                               req_enum, req_datetime, req_datetime_raw,
                               opt_string, opt_bool)
from services.workflow import close_sale, void_sale
from routes.notices import venue_conflict

bp = Blueprint("auction", __name__)

POSTPONEMENT_REASONS = ("BENEFICIARY_REQUEST", "TRUSTEE_DISCRETION",
                        "MUTUAL_AGREEMENT", "OPERATION_OF_LAW", "BANKRUPTCY_STAY")
ANNOUNCED_VIA = ("ADVANCE", "AT_SALE")


# ---------------------------------------------------------------------------
# AuctionSale reads
# ---------------------------------------------------------------------------

@bp.route("/api/auction-sales", methods=["GET"], strict_slashes=False)
@require_roles("TrusteeAdmin", "CaseManager", "Auctioneer", "ThirdPartyBidder")
def list_sales(user_id, role):
    items = list(db.auction_sales.values())
    nots_id = request.args.get("notice_of_trustee_sale_id")
    case_id = request.args.get("foreclosure_case_id")
    status = request.args.get("status")
    if nots_id is not None:
        items = [s for s in items if s["notice_of_trustee_sale_id"] == nots_id]
    if case_id is not None:
        items = [s for s in items if s["foreclosure_case_id"] == case_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    limit, offset = parse_pagination(request.args)
    page = [view(s) for s in items[offset:offset + limit]]
    return success_list(page, limit, offset, len(items))


@bp.route("/api/auction-sales/<sale_id>", methods=["GET"], strict_slashes=False)
@require_roles("TrusteeAdmin", "CaseManager", "Auctioneer", "ThirdPartyBidder")
def read_sale(user_id, role, sale_id):
    return success_object(view(get_sale(sale_id)))


# ---------------------------------------------------------------------------
# Postponements (self-loop; max 3 per NOTS; +30d window; OCC on sale version)
# ---------------------------------------------------------------------------

@bp.route("/api/auction-sales/<sale_id>/postponements", methods=["POST"], strict_slashes=False)
@require_roles("Auctioneer")
def postpone_sale(user_id, role, sale_id):
    sale = get_sale(sale_id)
    body = get_body()
    check_unknown(body, {"new_sale_start_at", "reason", "announced_via",
                         "expected_auction_sale_version"})
    new_start_raw, new_start = req_datetime_raw(body, "new_sale_start_at")
    reason = req_enum(body, "reason", POSTPONEMENT_REASONS)
    announced_via = req_enum(body, "announced_via", ANNOUNCED_VIA)
    expected = req_int(body, "expected_auction_sale_version")
    # state, then staleness, then business rules in order (PRD §3.8)
    if sale["status"] != "SCHEDULED":
        raise err_invalid_sale_state("only a SCHEDULED sale may be postponed")
    if expected != sale["version"]:
        raise err_stale_sale_version()
    if venue_conflict(sale["venue_name"], new_start, exclude_sale_id=sale["id"]):
        raise err_auction_conflict()
    nots = db.notices_of_trustee_sale.get(sale["notice_of_trustee_sale_id"])
    if nots is not None and nots["postponement_count"] >= calc.MAX_POSTPONEMENTS_PER_NOTS:
        # the third postponement is allowed; the fourth is rejected
        raise err_postponement_limit()
    current_start = db._parse_iso(sale["scheduled_sale_start_at"])
    if not (new_start > current_start
            and new_start <= current_start + timedelta(days=calc.POSTPONEMENT_MAX_DAYS_PER_EVENT)):
        # exactly 30 days out is permitted
        raise err_postponement_window()
    post = {
        "auction_sale_id": sale["id"],
        "prior_sale_start_at": sale["scheduled_sale_start_at"],
        "new_sale_start_at": new_start_raw,
        "reason": reason,
        "announced_via": announced_via,
    }
    stamp_new(post, common=False)  # Postponement: immutable; no updated_at/version
    db.postponements[post["id"]] = post
    sale["scheduled_sale_start_at"] = post["new_sale_start_at"]
    touch(sale)
    if nots is not None:
        nots["postponement_count"] += 1
        touch(nots)
    return success_object(view(post), status=201)


@bp.route("/api/auction-sales/<sale_id>/postponements", methods=["GET"], strict_slashes=False)
@require_roles("TrusteeAdmin", "CaseManager", "Auctioneer")
def list_postponements(user_id, role, sale_id):
    get_sale(sale_id)
    items = sale_postponements(sale_id)
    limit, offset = parse_pagination(request.args)
    page = [view(p) for p in items[offset:offset + limit]]
    return success_list(page, limit, offset, len(items))


# ---------------------------------------------------------------------------
# Bidder registrations
# ---------------------------------------------------------------------------

@bp.route("/api/auction-sales/<sale_id>/bidder-registrations", methods=["POST"], strict_slashes=False)
@require_roles("Auctioneer")
def register_bidder(user_id, role, sale_id):
    sale = get_sale(sale_id)
    body = get_body()
    check_unknown(body, {"bidder_name", "bidder_email", "deposit_cents"})
    bidder_name = req_string(body, "bidder_name")
    bidder_email = req_string(body, "bidder_email")
    deposit = req_int(body, "deposit_cents", minimum=1)
    if sale["status"] not in ("SCHEDULED", "CONDUCTED"):
        raise err_invalid_sale_state("registrations require a SCHEDULED or CONDUCTED sale")
    reg = {
        "auction_sale_id": sale["id"],
        "bidder_name": bidder_name,
        "bidder_email": bidder_email,
        "deposit_cents": deposit,
        "required_deposit_cents": None,  # computed at review time
        "status": "PENDING",
        "disqualification_reason": None,
    }
    stamp_new(reg)
    db.bidder_registrations[reg["id"]] = reg
    return success_object(view(reg), status=201)


@bp.route("/api/auction-sales/<sale_id>/bidder-registrations", methods=["GET"], strict_slashes=False)
@require_roles("TrusteeAdmin", "CaseManager", "Auctioneer")
def list_registrations(user_id, role, sale_id):
    get_sale(sale_id)
    items = sale_registrations(sale_id)
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    limit, offset = parse_pagination(request.args)
    page = [view(r) for r in items[offset:offset + limit]]
    return success_list(page, limit, offset, len(items))


@bp.route("/api/bidder-registrations/<registration_id>", methods=["GET"], strict_slashes=False)
@require_roles("TrusteeAdmin", "CaseManager", "Auctioneer", "ThirdPartyBidder")
def read_registration(user_id, role, registration_id):
    reg = get_registration(registration_id)
    # a ThirdPartyBidder may read only its own registration record
    if role == "ThirdPartyBidder" and reg["id"] != user_id:
        raise err_bidder_ownership()
    return success_object(view(reg))


@bp.route("/api/bidder-registrations/<registration_id>/review", methods=["POST"], strict_slashes=False)
@require_roles("Auctioneer")
def review_registration(user_id, role, registration_id):
    reg = get_registration(registration_id)
    body = get_body()
    check_unknown(body, {"decision", "reason"})
    decision = req_enum(body, "decision", ("QUALIFY", "DISQUALIFY"))
    reason = opt_string(body, "reason")
    sale = get_sale(reg["auction_sale_id"])
    # the sale-state check runs before the registration-state check (PRD §3.8)
    if sale["status"] not in ("SCHEDULED", "CONDUCTED"):
        raise err_invalid_sale_state("review requires a SCHEDULED or CONDUCTED sale")
    if decision == "QUALIFY":
        if reg["status"] != "PENDING":
            raise err_invalid_registration_state("qualification requires PENDING")
        # deposit gate, computed at review time: opening reference is the
        # ACTIVE instruction's opening bid if one exists, else the case UPB
        case = get_case(sale["foreclosure_case_id"])
        ins = active_instruction(case["id"])
        opening_reference = (ins["opening_bid_cents"] if ins is not None
                             else case["unpaid_principal_balance_cents"])
        required = calc.required_bidder_deposit(opening_reference)
        if reg["deposit_cents"] < required:
            # meeting the requirement exactly qualifies
            raise err_deposit_insufficient()
        reg["required_deposit_cents"] = required
        reg["status"] = "QUALIFIED"
        touch(reg)
    else:  # DISQUALIFY
        if reg["status"] == "PENDING":
            pass  # unconditional from PENDING
        elif reg["status"] == "QUALIFIED":
            # only while the registration has placed no bid and the sale has
            # not closed (the sale-state gate above already excludes CLOSED)
            if registration_bids(reg["id"]):
                raise err_invalid_registration_state("cannot disqualify a registration that has bid")
        else:
            raise err_invalid_registration_state("disqualification requires PENDING or QUALIFIED")
        if reason is None or reason.strip() == "":
            raise err_invalid_request("reason must be non-empty for DISQUALIFY")
        reg["status"] = "DISQUALIFIED"
        reg["disqualification_reason"] = reason
        touch(reg)
    return success_object(view(reg))


@bp.route("/api/bidder-registrations/<registration_id>/refund", methods=["POST"], strict_slashes=False)
@require_roles("Auctioneer")
def refund_registration(user_id, role, registration_id):
    reg = get_registration(registration_id)
    body = get_body()
    check_unknown(body, set())
    if reg["status"] != "REFUND_PENDING":
        raise err_invalid_registration_state("refund requires REFUND_PENDING")
    reg["status"] = "REFUNDED"  # deposit released; no other field changes
    touch(reg)
    return success_object(view(reg))


# ---------------------------------------------------------------------------
# Bids
# ---------------------------------------------------------------------------

@bp.route("/api/auction-sales/<sale_id>/bids", methods=["POST"], strict_slashes=False)
@require_roles("ThirdPartyBidder")
def place_bid(user_id, role, sale_id):
    body = get_body()
    check_unknown(body, {"bidder_registration_id", "amount_cents"})
    registration_id = body.get("bidder_registration_id")
    if not isinstance(registration_id, str) or registration_id.strip() == "":
        raise err_invalid_request("missing or invalid field: bidder_registration_id")
    # entity-backed identity: the caller bids only through its own
    # registration (priority 4, before existence)
    if registration_id != user_id:
        raise err_bidder_ownership()
    sale = get_sale(sale_id)
    amount = req_int(body, "amount_cents", minimum=1)
    # sale state -> registration state -> minimum next bid (PRD §3.8)
    if sale["status"] != "CONDUCTED":
        raise err_invalid_sale_state("bids require a CONDUCTED sale")
    reg = db.bidder_registrations.get(registration_id)
    if reg is None or reg["auction_sale_id"] != sale["id"] or reg["status"] != "QUALIFIED":
        raise err_invalid_registration_state("bidding registration is not QUALIFIED for this sale")
    existing = [b["amount_cents"] for b in sale_bids(sale["id"])]
    required_min = calc.minimum_next_bid(sale["opening_bid_cents"], existing)
    if amount < required_min:
        # a bid exactly at required_min is accepted
        raise err_bid_too_low()
    bid = {
        "auction_sale_id": sale["id"],
        "bidder_registration_id": registration_id,
        "amount_cents": amount,
        "placed_at": now_iso(),
    }
    stamp_new(bid, common=False)  # Bid: immutable; no updated_at/version
    db.bids[bid["id"]] = bid
    return success_object(view(bid), status=201)


@bp.route("/api/auction-sales/<sale_id>/bids", methods=["GET"], strict_slashes=False)
@require_roles("TrusteeAdmin", "CaseManager", "Auctioneer", "ThirdPartyBidder")
def list_sale_bids(user_id, role, sale_id):
    get_sale(sale_id)
    items = sale_bids(sale_id)  # placed_at ASC
    limit, offset = parse_pagination(request.args)
    page = [view(b) for b in items[offset:offset + limit]]
    return success_list(page, limit, offset, len(items))


@bp.route("/api/bidder-registrations/<registration_id>/bids", methods=["GET"], strict_slashes=False)
@require_roles("TrusteeAdmin", "CaseManager", "Auctioneer", "ThirdPartyBidder")
def list_registration_bids(user_id, role, registration_id):
    reg = get_registration(registration_id)
    if role == "ThirdPartyBidder" and reg["id"] != user_id:
        raise err_bidder_ownership()
    items = registration_bids(registration_id)
    limit, offset = parse_pagination(request.args)
    page = [view(b) for b in items[offset:offset + limit]]
    return success_list(page, limit, offset, len(items))


# ---------------------------------------------------------------------------
# Conduct / close / void
# ---------------------------------------------------------------------------

@bp.route("/api/auction-sales/<sale_id>/conduct", methods=["POST"], strict_slashes=False)
@require_roles("Auctioneer")
def conduct_sale(user_id, role, sale_id):
    sale = get_sale(sale_id)
    body = get_body()
    check_unknown(body, set())
    case = get_case(sale["foreclosure_case_id"])
    # order: sale state, then (case state), then hold, then instruction, then
    # the calendar match (PRD §3.8)
    if sale["status"] != "SCHEDULED":
        raise err_invalid_sale_state("conduct requires a SCHEDULED sale")
    if case["lifecycle_status"] != "SALE_SCHEDULED":
        raise err_invalid_case_state("conduct requires the case in SALE_SCHEDULED")
    if case["hold_status"] != "CLEAR":
        raise err_active_stay()
    ins = active_instruction(case["id"])
    if ins is None:
        raise err_no_active_instruction()
    sale_date = db._parse_iso(sale["scheduled_sale_start_at"]).date()
    if db.CLOCK.now_date() != sale_date:
        raise err_sale_not_today()
    # snapshot the opening bid at conduct time — fixed even if the
    # instruction is later superseded
    sale["opening_bid_cents"] = ins["opening_bid_cents"]
    sale["status"] = "CONDUCTED"
    touch(sale)
    return success_object(view(sale))


@bp.route("/api/auction-sales/<sale_id>/close", methods=["POST"], strict_slashes=False)
@require_roles("Auctioneer")
def close_sale_route(user_id, role, sale_id):
    sale = get_sale(sale_id)
    body = get_body()
    check_unknown(body, set())
    case = get_case(sale["foreclosure_case_id"])
    # case-state, sale-state, hold — in that order (PRD §3.8)
    if case["lifecycle_status"] != "SALE_SCHEDULED":
        raise err_invalid_case_state("close requires the case in SALE_SCHEDULED")
    if sale["status"] != "CONDUCTED":
        raise err_invalid_sale_state("close requires a CONDUCTED sale")
    if case["hold_status"] != "CLEAR":
        raise err_active_stay()
    close_sale(case, sale)
    return success_object(view(sale))


@bp.route("/api/auction-sales/<sale_id>/void", methods=["POST"], strict_slashes=False)
@require_roles("Auctioneer")
def void_sale_route(user_id, role, sale_id):
    sale = get_sale(sale_id)
    body = get_body()
    check_unknown(body, {"reason"})
    reason = req_string(body, "reason")
    case = get_case(sale["foreclosure_case_id"])
    if sale["status"] not in ("CONDUCTED", "CLOSED"):
        raise err_invalid_sale_state("only a CONDUCTED or CLOSED sale may be voided")
    # un-voidable when a RECORDED deed exists for the sale, or surplus
    # distribution (CLAIMANT / BORROWER_RESIDUE disbursement) has begun
    if any(d["status"] == "RECORDED" for d in sale_deeds(sale["id"])):
        raise err_sale_not_voidable("a recorded trustee's deed exists for the sale")
    if any(d["recipient_type"] in ("CLAIMANT", "BORROWER_RESIDUE")
           for d in db.disbursements.values()
           if d["foreclosure_case_id"] == case["id"]):
        raise err_sale_not_voidable("surplus distribution has begun for the case")
    void_sale(case, sale, reason)
    return success_object(view(sale))


# ---------------------------------------------------------------------------
# TrusteesDeed
# ---------------------------------------------------------------------------

@bp.route("/api/auction-sales/<sale_id>/trustees-deeds", methods=["POST"], strict_slashes=False)
@require_roles("CaseManager")
def draft_deed(user_id, role, sale_id):
    sale = get_sale(sale_id)
    body = get_body()
    check_unknown(body, set())
    if sale["status"] != "CLOSED":
        raise err_invalid_sale_state("deed drafting requires a CLOSED sale")
    # a sale carries at most one live deed
    if any(d["status"] != "VOIDED" for d in sale_deeds(sale["id"])):
        raise err_invalid_deed_state("a non-VOIDED deed already exists for the sale")
    if sale["winner_type"] == "THIRD_PARTY":
        reg = db.bidder_registrations.get(sale["winning_bidder_registration_id"])
        grantee = reg["bidder_name"] if reg is not None else None
    else:
        case = get_case(sale["foreclosure_case_id"])
        ben = get_beneficiary(case["beneficiary_id"])
        grantee = ben["name"]
    deed = {
        "auction_sale_id": sale["id"],
        "grantee_name": grantee,
        "status": "DRAFTED",
        "recorded_at": None,
    }
    stamp_new(deed)
    db.trustees_deeds[deed["id"]] = deed
    return success_object(view(deed), status=201)


@bp.route("/api/auction-sales/<sale_id>/trustees-deeds", methods=["GET"], strict_slashes=False)
@require_roles("TrusteeAdmin", "CaseManager")
def list_deeds(user_id, role, sale_id):
    get_sale(sale_id)
    items = sale_deeds(sale_id)
    limit, offset = parse_pagination(request.args)
    page = [view(d) for d in items[offset:offset + limit]]
    return success_list(page, limit, offset, len(items))


@bp.route("/api/trustees-deeds/<deed_id>/record", methods=["POST"], strict_slashes=False)
@require_roles("CaseManager")
def record_deed(user_id, role, deed_id):
    deed = get_deed(deed_id)
    body = get_body()
    check_unknown(body, {"court_order_extension"})
    extension = opt_bool(body, "court_order_extension", default=False)
    sale = get_sale(deed["auction_sale_id"])
    case = get_case(sale["foreclosure_case_id"])
    # deed state first: a DRAFTED deed exists iff its case is SOLD, so the
    # case-state check is reachable only for non-DRAFTED deeds — and the
    # suite pins ERR_INVALID_DEED_STATE for a twice-recorded deed (the case is
    # already DEED_RECORDED then). Both state checks precede the deadline.
    if deed["status"] != "DRAFTED":
        raise err_invalid_deed_state("deed is not DRAFTED")
    if case["lifecycle_status"] != "SOLD":
        raise err_invalid_case_state("deed recording requires the case in SOLD")
    if not extension:
        deadline = db._parse_iso(sale["closed_at"]) + timedelta(days=calc.DEED_RECORDING_DEADLINE_DAYS)
        if db.now_dt() > deadline:
            raise err_deed_late()
    deed["status"] = "RECORDED"
    deed["recorded_at"] = now_iso()
    touch(deed)
    case["lifecycle_status"] = "DEED_RECORDED"
    touch(case)
    return success_object(view(deed))
