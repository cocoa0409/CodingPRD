"""EndOfTermElection endpoints — PRD §3.11, §4.

ELECTED -> {EXERCISED, CANCELLED}. Election value (RENEW/RETURN/BUYOUT) drives
the quote and the exercise side effects.
"""
from flask import Blueprint, request

import db
import errors
from middleware import get_user_context, require_roles, ALL_ROLES
from response import object_response, array_response
from services.common import (
    get_json_body, require_enum, require_int, optional_positive_int,
    serialize, paginate, sort_by_created, parse_iso8601, to_iso, add_months,
)
from services import domain
from services import calculations as calc

bp = Blueprint("eot_elections", __name__)

ELECTIONS = {"RENEW", "RETURN", "BUYOUT"}


@bp.post("/lessors/<lessor_id>/leases/<lease_id>/eot-elections")
def create_election(lessor_id, lease_id):
    user_id, role = get_user_context()
    require_roles(role, ["Servicer"])
    with db.LOCK:
        domain.get_lessor_or_404(lessor_id)
        lease = domain.get_lease(lessor_id, lease_id)
        body = get_json_body()
        election = require_enum(body, "election", ELECTIONS)
        renewal_months = body.get("renewal_months")
        # renewal_months required iff RENEW, forbidden otherwise; > 0.
        if election == "RENEW":
            renewal_months = require_int(body, "renewal_months")
            if renewal_months <= 0:
                raise errors.invalid_request("renewal_months must be positive")
        else:
            if renewal_months is not None:
                raise errors.invalid_request("renewal_months forbidden unless RENEW")

        # Compute quoted_amount_cents.
        if election == "RETURN":
            quoted = 0
        elif election == "BUYOUT":
            quoted = calc.buyout_quote(lease)
        else:  # RENEW: quote is the renewal monthly rent (= monthly_payment).
            quoted = lease["monthly_payment_cents"]

        rec = db.init_record({
            "lessor_id": lessor_id,
            "lease_id": lease_id,
            "election": election,
            "renewal_months": renewal_months if election == "RENEW" else None,
            "quoted_amount_cents": quoted,
            "status": "ELECTED",
        })
        db.eot_elections[rec["id"]] = rec
        return object_response(serialize(rec), 201)


@bp.get("/lessors/<lessor_id>/eot-elections/<election_id>")
def get_election(lessor_id, election_id):
    user_id, role = get_user_context()
    require_roles(role, ALL_ROLES)
    with db.LOCK:
        domain.get_lessor_or_404(lessor_id)
        rec = domain.get_eot_election(lessor_id, election_id)
        return object_response(serialize(rec), 200)


@bp.get("/lessors/<lessor_id>/leases/<lease_id>/eot-elections")
def list_elections(lessor_id, lease_id):
    user_id, role = get_user_context()
    require_roles(role, ALL_ROLES)
    with db.LOCK:
        domain.get_lessor_or_404(lessor_id)
        domain.get_lease(lessor_id, lease_id)
        items = domain.elections_for_lease(lease_id)
        status = request.args.get("status")
        if status is not None and status != "":
            items = [e for e in items if e["status"] == status]
        items = sort_by_created(items)
        page, limit, offset, total = paginate(items)
        return array_response([serialize(r) for r in page], limit, offset, total, 200)


@bp.post("/lessors/<lessor_id>/leases/<lease_id>/eot-elections/<election_id>/exercise")
def exercise_election(lessor_id, lease_id, election_id):
    user_id, role = get_user_context()
    require_roles(role, ["Servicer"])
    with db.LOCK:
        domain.get_lessor_or_404(lessor_id)
        lease = domain.get_lease(lessor_id, lease_id)
        rec = domain.get_eot_election(lessor_id, election_id)
        if rec["lease_id"] != lease_id:
            raise errors.not_found("Election not found on this lease")
        if rec["status"] != "ELECTED":
            raise errors.invalid_state("Election is not ELECTED")
        # Lease must be END_OF_TERM.
        if lease["lifecycle_status"] != "END_OF_TERM":
            raise errors.conflict(errors.ERR_LEASE_NOT_END_OF_TERM,
                                  "lease is not END_OF_TERM")
        # BUYOUT requires buyout_payment_cents == quoted_amount_cents.
        if rec["election"] == "BUYOUT":
            body = get_json_body()
            payment = body.get("buyout_payment_cents")
            if payment is None or isinstance(payment, bool) or not isinstance(payment, int) \
                    or payment != rec["quoted_amount_cents"]:
                raise errors.conflict(errors.ERR_BUYOUT_NOT_PAID,
                                      "buyout_payment_cents must equal quoted_amount_cents")
        rec["status"] = "EXERCISED"
        db.touch(rec)

        if rec["election"] == "RENEW":
            # Append renewal_months new ScheduleLine rows; term_months += renewal_months.
            booked = lease.get("booked_clock_utc")
            base_dt = parse_iso8601(booked) if booked else parse_iso8601(
                db.lessors[lessor_id]["clock_utc"])
            old_term = lease["term_months"]
            for i in range(1, rec["renewal_months"] + 1):
                n = old_term + i
                sl = db.init_record({
                    "lessor_id": lessor_id,
                    "lease_id": lease_id,
                    "installment_number": n,
                    "due_clock_utc": to_iso(add_months(base_dt, n)),
                    "base_rent_cents": lease["monthly_payment_cents"],
                    "is_advance": False,
                    "status": "SCHEDULED",
                })
                db.schedule_lines[sl["id"]] = sl
            lease["term_months"] = old_term + rec["renewal_months"]
            db.touch(lease)
        elif rec["election"] == "BUYOUT":
            # Split quoted_amount across units (integer split; remainder to the
            # unit with the earliest created_at).
            units = sort_by_created(domain.units_for_lease(lease_id))
            n = len(units)
            if n > 0:
                quoted = rec["quoted_amount_cents"]
                share = quoted // n
                remainder = quoted - share * n
                for idx, u in enumerate(units):
                    proceeds = share + (remainder if idx == 0 else 0)
                    u["status"] = "SOLD"
                    u["sale_proceeds_cents"] = proceeds
                    db.touch(u)
                lessor = db.lessors[lessor_id]
                domain.recompute_lessor_portfolio(lessor)
        return object_response(serialize(rec), 200)


@bp.post("/lessors/<lessor_id>/leases/<lease_id>/eot-elections/<election_id>/cancel")
def cancel_election(lessor_id, lease_id, election_id):
    user_id, role = get_user_context()
    require_roles(role, ["Servicer"])
    with db.LOCK:
        domain.get_lessor_or_404(lessor_id)
        domain.get_lease(lessor_id, lease_id)
        rec = domain.get_eot_election(lessor_id, election_id)
        if rec["lease_id"] != lease_id:
            raise errors.not_found("Election not found on this lease")
        if rec["status"] != "ELECTED":
            raise errors.invalid_state("Election is not ELECTED")
        rec["status"] = "CANCELLED"
        db.touch(rec)
        return object_response(serialize(rec), 200)
