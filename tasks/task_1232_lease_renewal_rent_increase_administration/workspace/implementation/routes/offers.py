from datetime import timedelta

from flask import Blueprint, request

from db import store
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_LEASE_NOT_FOUND, ERR_OFFER_NOT_FOUND,
    ERR_NOT_RESOURCE_OWNER, ERR_STALE_LEASE_VERSION, ERR_LEASE_NOT_ISSUABLE,
    ERR_OFFER_NOT_DRAFT, ERR_OFFER_NOT_ISSUED, ERR_OFFER_NOT_COUNTERED,
    ERR_OFFER_NOT_WITHDRAWABLE, ERR_NOTICE_WINDOW_MISSED, ERR_RENT_CAP_EXCEEDED,
    ERR_TERM_OUTSIDE_STAGGERING_BAND, ERR_MAX_NEGOTIATION_ROUNDS,
    ERR_CONCESSION_APPROVAL_REQUIRED,
)
from middleware import require_roles, get_auth
from response import success_object, success_list
from services.calc import (
    compute_pricing, compute_notice_days_required, compute_latest_issue_date,
    staggered_term_selection, OPEN_OFFER_STATUSES,
)
from services.common import new_entity, touch
from services.lifecycle import void_pending_concessions_for_offer, lease_revert_check
from timeutil import parse_date, clock_date

bp = Blueprint("offers", __name__)


def _serialize(o):
    return {
        "id": o["id"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
        "lease_id": o["lease_id"],
        "rate_strategy": o["rate_strategy"],
        "offer_round": o["offer_round"],
        "base_rent_cents": o["base_rent_cents"],
        "proposed_rent_cents": o["proposed_rent_cents"],
        "proposed_increase_bps": o["proposed_increase_bps"],
        "cap_bps_snapshot": o["cap_bps_snapshot"],
        "offered_term_months": o["offered_term_months"],
        "notice_days_required": o["notice_days_required"],
        "latest_issue_date": o["latest_issue_date"],
        "issued_on_date": o.get("issued_on_date"),
        "issued_by_user_id": o.get("issued_by_user_id"),
        "response_deadline_date": o.get("response_deadline_date"),
        "counter_rent_cents": o.get("counter_rent_cents"),
        "counter_term_months": o.get("counter_term_months"),
        "accepted_on_date": o.get("accepted_on_date"),
        "execution_deadline_date": o.get("execution_deadline_date"),
        "executed_rent_cents": o.get("executed_rent_cents"),
        "supersedes_offer_id": o.get("supersedes_offer_id"),
        "status": o["status"],
    }


def _get_pagination():
    try:
        limit = int(request.args.get("limit", "10"))
        offset = int(request.args.get("offset", "0"))
    except ValueError:
        raise_err(ERR_INVALID_REQUEST, "limit/offset must be integers")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def _get_lease_or_404(lease_id):
    l = store.leases.get(lease_id)
    if l is None:
        raise_err(ERR_LEASE_NOT_FOUND, "lease not found")
    return l


def _get_offer_or_404(offer_id):
    o = store.renewal_offers.get(offer_id)
    if o is None:
        raise_err(ERR_OFFER_NOT_FOUND, "offer not found")
    return o


def _get_policy_for_lease(lease):
    prop = store.properties.get(lease["property_id"])
    if prop is None:
        return None
    return store.rent_cap_policies.get(prop["rent_cap_policy_id"])


def _recompute_pricing_fields(offer, lease, policy, unit):
    """Recompute notice/latest fields after pricing changes."""
    offer["notice_days_required"] = compute_notice_days_required(
        offer["proposed_increase_bps"], policy)
    offer["latest_issue_date"] = compute_latest_issue_date(
        lease, offer["notice_days_required"])


@bp.route("/leases/<lease_id>/renewal-offers", methods=["POST"])
def create_offer(lease_id):
    user_id, role = require_roles("LeasingAgent", "PropertyManager", "RegionalDirector")
    body = request.get_json(silent=True) or {}
    rate_strategy = body.get("rate_strategy", "BALANCED")
    if rate_strategy not in ("AGGRESSIVE", "BALANCED", "CONSERVATIVE"):
        raise_err(ERR_INVALID_REQUEST, "rate_strategy invalid")
    expected_lease_version = body.get("expected_lease_version")
    if expected_lease_version is None or not isinstance(expected_lease_version, int) or isinstance(expected_lease_version, bool):
        raise_err(ERR_INVALID_REQUEST, "expected_lease_version required int")

    lease = _get_lease_or_404(lease_id)

    # OCC
    if expected_lease_version != lease["version"]:
        raise_err(ERR_STALE_LEASE_VERSION, "stale lease version")

    # State: lease must be issuable (not ENDED or NON_RENEWAL_NOTICED)
    if lease["status"] not in ("ACTIVE", "MTM", "RENEWAL_PENDING"):
        raise_err(ERR_LEASE_NOT_ISSUABLE, "lease not issuable")

    unit = store.units.get(lease["unit_id"])
    prop = store.properties.get(lease["property_id"])
    policy = _get_policy_for_lease(lease)
    if policy is None or unit is None or prop is None:
        raise_err(ERR_INVALID_REQUEST, "lease missing property/unit/policy chain")

    # Supersede open sibling offers
    open_siblings = [o for o in store.renewal_offers.values()
                     if o["lease_id"] == lease["id"] and o["status"] in ("DRAFT", "ISSUED", "COUNTERED")]
    open_siblings.sort(key=lambda o: o["created_at"])
    superseded_most_recent_id = None
    for s in open_siblings:
        s["status"] = "SUPERSEDED"
        touch(s)
        void_pending_concessions_for_offer(s["id"])
        superseded_most_recent_id = s["id"]

    # Compute staggered term + pricing
    offered_term = staggered_term_selection(lease, prop)
    cap_snapshot = int(policy["effective_cap_bps"])
    proposed_rent, proposed_increase_bps = compute_pricing(
        lease["monthly_rent_cents"], unit["current_market_rent_cents"],
        offered_term, rate_strategy, cap_snapshot)

    rec = new_entity()
    rec.update({
        "lease_id": lease["id"],
        "rate_strategy": rate_strategy,
        "offer_round": 1,
        "base_rent_cents": lease["monthly_rent_cents"],
        "proposed_rent_cents": proposed_rent,
        "proposed_increase_bps": proposed_increase_bps,
        "cap_bps_snapshot": cap_snapshot,
        "offered_term_months": offered_term,
        "notice_days_required": 0,
        "latest_issue_date": None,
        "issued_on_date": None,
        "issued_by_user_id": None,
        "response_deadline_date": None,
        "counter_rent_cents": None,
        "counter_term_months": None,
        "accepted_on_date": None,
        "execution_deadline_date": None,
        "executed_rent_cents": None,
        "supersedes_offer_id": superseded_most_recent_id,
        "status": "DRAFT",
    })
    _recompute_pricing_fields(rec, lease, policy, unit)
    store.renewal_offers[rec["id"]] = rec

    # Lease version increments
    touch(lease)

    return success_object(_serialize(rec), status_code=201)


@bp.route("/renewal-offers", methods=["GET"])
def list_offers():
    user_id, role = get_auth()
    if role not in ("PlatformAdmin", "RegionalDirector", "PropertyManager", "LeasingAgent", "Resident"):
        from errors import ERR_FORBIDDEN_ROLE
        raise_err(ERR_FORBIDDEN_ROLE, "forbidden")
    limit, offset = _get_pagination()
    lease_id = request.args.get("lease_id")
    status = request.args.get("status")
    supersedes = request.args.get("supersedes_offer_id")
    items = list(store.renewal_offers.values())
    if role == "Resident":
        items = [o for o in items
                 if store.leases.get(o["lease_id"]) and
                 store.leases[o["lease_id"]]["resident_id"] == user_id]
    if lease_id:
        items = [o for o in items if o["lease_id"] == lease_id]
    if status:
        items = [o for o in items if o["status"] == status]
    if supersedes:
        items = [o for o in items if o.get("supersedes_offer_id") == supersedes]
    items.sort(key=lambda o: o["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([_serialize(o) for o in page], limit, offset, total)


@bp.route("/renewal-offers/<oid>", methods=["GET"])
def get_offer(oid):
    user_id, role = get_auth()
    if role not in ("PlatformAdmin", "RegionalDirector", "PropertyManager", "LeasingAgent", "Resident"):
        from errors import ERR_FORBIDDEN_ROLE
        raise_err(ERR_FORBIDDEN_ROLE, "forbidden")
    o = _get_offer_or_404(oid)
    if role == "Resident":
        lease = store.leases.get(o["lease_id"])
        if lease is None or lease["resident_id"] != user_id:
            raise_err(ERR_NOT_RESOURCE_OWNER, "not owner")
    return success_object(_serialize(o))


@bp.route("/renewal-offers/<oid>/issue", methods=["POST"])
def issue_offer(oid):
    user_id, role = require_roles("LeasingAgent", "PropertyManager", "RegionalDirector")
    o = _get_offer_or_404(oid)
    lease = store.leases.get(o["lease_id"])
    if lease is None:
        raise_err(ERR_LEASE_NOT_FOUND, "lease not found")
    # State
    if o["status"] != "DRAFT":
        raise_err(ERR_OFFER_NOT_DRAFT, "offer not DRAFT")
    if lease["status"] not in ("ACTIVE", "MTM", "RENEWAL_PENDING"):
        raise_err(ERR_LEASE_NOT_ISSUABLE, "lease not issuable")
    # Notice window
    if o["latest_issue_date"] is not None:
        if clock_date() > parse_date(o["latest_issue_date"]):
            raise_err(ERR_NOTICE_WINDOW_MISSED, "notice window missed")

    now = clock_date()
    o["issued_on_date"] = now.strftime("%Y-%m-%d")
    o["issued_by_user_id"] = user_id
    if lease["status"] == "MTM":
        o["response_deadline_date"] = (now + timedelta(days=14)).strftime("%Y-%m-%d")
    else:
        term_end = parse_date(lease["term_end_date"])
        candidate = now + timedelta(days=14)
        o["response_deadline_date"] = min(candidate, term_end).strftime("%Y-%m-%d")
    o["status"] = "ISSUED"
    touch(o)

    # Lease ACTIVE/MTM -> RENEWAL_PENDING
    if lease["status"] in ("ACTIVE", "MTM"):
        if lease.get("status_before_offer") is None:
            lease["status_before_offer"] = lease["status"]
        lease["status"] = "RENEWAL_PENDING"
        touch(lease)

    return success_object(_serialize(o))


@bp.route("/renewal-offers/<oid>/respond", methods=["POST"])
def respond_offer(oid):
    user_id, role = require_roles("Resident")
    body = request.get_json(silent=True) or {}
    response_type = body.get("response_type")
    if response_type not in ("ACCEPT", "DECLINE", "COUNTER"):
        raise_err(ERR_INVALID_REQUEST, "response_type must be ACCEPT, DECLINE, COUNTER")
    counter_rent = body.get("counter_rent_cents")
    counter_term = body.get("counter_term_months")
    if response_type == "COUNTER":
        if counter_rent is None or not isinstance(counter_rent, int) or isinstance(counter_rent, bool) or counter_rent <= 0:
            raise_err(ERR_INVALID_REQUEST, "counter_rent_cents > 0 required for COUNTER")
        if counter_term is not None and (not isinstance(counter_term, int) or isinstance(counter_term, bool)):
            raise_err(ERR_INVALID_REQUEST, "counter_term_months must be int")

    o = _get_offer_or_404(oid)
    lease = store.leases.get(o["lease_id"])
    if lease is None:
        raise_err(ERR_LEASE_NOT_FOUND, "lease not found")

    # Ownership
    if lease["resident_id"] != user_id:
        raise_err(ERR_NOT_RESOURCE_OWNER, "not owner")

    # State
    if o["status"] != "ISSUED":
        raise_err(ERR_OFFER_NOT_ISSUED, "offer not ISSUED")

    # Domain constraint sub-order: (a) term band, (d) round cap
    prop = store.properties.get(lease["property_id"])
    if response_type == "COUNTER":
        if counter_term is not None:
            if counter_term < prop["min_term_months"] or counter_term > prop["max_term_months"]:
                raise_err(ERR_TERM_OUTSIDE_STAGGERING_BAND, "counter term outside band")
        if o["offer_round"] >= 3:
            raise_err(ERR_MAX_NEGOTIATION_ROUNDS, "max negotiation rounds")

    now = clock_date()
    if response_type == "ACCEPT":
        o["accepted_on_date"] = now.strftime("%Y-%m-%d")
        o["execution_deadline_date"] = (now + timedelta(days=10)).strftime("%Y-%m-%d")
        o["status"] = "ACCEPTED"
        touch(o)
        # Create RenewalDocument GENERATED
        doc = new_entity()
        doc.update({
            "offer_id": o["id"],
            "lease_id": lease["id"],
            "status": "GENERATED",
            "executed_rent_cents": None,
            "countersigned_on_date": None,
            "rescind_deadline_date": None,
            "prior_lease_status": None,
            "prior_monthly_rent_cents": None,
            "prior_term_start_date": None,
            "prior_term_end_date": None,
            "prior_term_months": None,
        })
        store.renewal_documents[doc["id"]] = doc
    elif response_type == "DECLINE":
        o["status"] = "DECLINED"
        touch(o)
        lease_revert_check(lease)
    else:  # COUNTER
        o["counter_rent_cents"] = counter_rent
        if counter_term is not None:
            o["counter_term_months"] = counter_term
        o["status"] = "COUNTERED"
        touch(o)

    return success_object(_serialize(o))


@bp.route("/renewal-offers/<oid>/revise", methods=["POST"])
def revise_offer(oid):
    user_id, role = require_roles("LeasingAgent", "PropertyManager", "RegionalDirector")
    body = request.get_json(silent=True) or {}
    revised_rent = body.get("revised_rent_cents")
    revised_term = body.get("revised_term_months")
    if revised_rent is not None and (not isinstance(revised_rent, int) or isinstance(revised_rent, bool)):
        raise_err(ERR_INVALID_REQUEST, "revised_rent_cents must be int")
    if revised_term is not None and (not isinstance(revised_term, int) or isinstance(revised_term, bool)):
        raise_err(ERR_INVALID_REQUEST, "revised_term_months must be int")

    o = _get_offer_or_404(oid)
    lease = store.leases.get(o["lease_id"])
    if lease is None:
        raise_err(ERR_LEASE_NOT_FOUND, "lease not found")

    # State
    if o["status"] != "COUNTERED":
        raise_err(ERR_OFFER_NOT_COUNTERED, "offer not COUNTERED")

    # Defaults
    final_rent = revised_rent if revised_rent is not None else o.get("counter_rent_cents")
    final_term = revised_term if revised_term is not None else o["offered_term_months"]
    if final_rent is None:
        raise_err(ERR_INVALID_REQUEST, "no revised rent available")

    prop = store.properties.get(lease["property_id"])
    policy = _get_policy_for_lease(lease)
    unit = store.units.get(lease["unit_id"])

    # PRD §2.9 stage 8 — statutory rent cap (current policy) runs before
    # stage 9 temporal windows and stage 10 domain constraints.
    base = o["base_rent_cents"]
    if base <= 0:
        increase_bps = 0
    else:
        from decimal import Decimal, ROUND_HALF_UP
        increase_bps = int(((Decimal(final_rent) - Decimal(base)) / Decimal(base) * Decimal(10000)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP))
    if increase_bps > policy["effective_cap_bps"]:
        raise_err(ERR_RENT_CAP_EXCEEDED, "rent cap exceeded")

    # PRD §2.9 stage 9 — high-tier notice window
    if increase_bps > policy["high_increase_threshold_bps"]:
        # High tier -> check clock date <= term_end - notice_days_high
        if lease["status"] != "MTM":
            term_end = parse_date(lease["term_end_date"])
            deadline = term_end - timedelta(days=int(policy["notice_days_high"]))
            if clock_date() > deadline:
                raise_err(ERR_NOTICE_WINDOW_MISSED, "notice window missed")

    # PRD §2.9 stage 10(a) — term band
    if final_term < prop["min_term_months"] or final_term > prop["max_term_months"]:
        raise_err(ERR_TERM_OUTSIDE_STAGGERING_BAND, "term outside band")

    # PRD §2.9 stage 10(h) — approved-concession gate on below-strategy revisions
    consumed_concession = None
    if final_rent < o["proposed_rent_cents"]:
        for c in store.concession_approvals.values():
            if (c["offer_id"] == o["id"] and c["status"] == "APPROVED"
                    and c["requested_rent_cents"] == final_rent):
                consumed_concession = c
                break
        if consumed_concession is None:
            raise_err(ERR_CONCESSION_APPROVAL_REQUIRED, "approved concession required")

    # Apply
    o["offer_round"] = o["offer_round"] + 1
    o["proposed_rent_cents"] = final_rent
    o["proposed_increase_bps"] = increase_bps if increase_bps >= 0 else 0
    o["offered_term_months"] = final_term
    now = clock_date()
    o["issued_on_date"] = now.strftime("%Y-%m-%d")
    if lease["status"] == "MTM":
        o["response_deadline_date"] = (now + timedelta(days=14)).strftime("%Y-%m-%d")
    else:
        term_end = parse_date(lease["term_end_date"])
        candidate = now + timedelta(days=14)
        o["response_deadline_date"] = min(candidate, term_end).strftime("%Y-%m-%d")
    o["notice_days_required"] = compute_notice_days_required(o["proposed_increase_bps"], policy)
    o["latest_issue_date"] = compute_latest_issue_date(lease, o["notice_days_required"])
    o["status"] = "ISSUED"
    touch(o)

    if consumed_concession is not None:
        consumed_concession["status"] = "APPLIED"
        touch(consumed_concession)

    return success_object(_serialize(o))


@bp.route("/renewal-offers/<oid>/withdraw", methods=["POST"])
def withdraw_offer(oid):
    user_id, role = require_roles("LeasingAgent", "PropertyManager", "RegionalDirector")
    o = _get_offer_or_404(oid)
    if o["status"] not in ("DRAFT", "ISSUED", "COUNTERED"):
        raise_err(ERR_OFFER_NOT_WITHDRAWABLE, "offer not withdrawable")
    from services.lifecycle import withdraw_offer_cascade
    withdraw_offer_cascade(o)
    return success_object(_serialize(o))
