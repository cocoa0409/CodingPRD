"""Bill endpoints: issue (split + estimate refresh), read, splits list, record-payment
(parallel payment_status x reminder_status) (PRD §3.4)."""
from flask import Blueprint, request

import models
import response
import validate
from db import db
from errors import err
from middleware import authenticate, require_roles, parse_pagination, paginate
from services import household as hh

bp = Blueprint("bills", __name__)

ALL_ROLES = {"Roommate", "DisputeMediator", "PlatformOperator"}
BILL_TYPE = {"RENT", "UTILITIES"}


def _rent_periods_overlap(a_start, a_end, b_start, b_end):
    # closed-interval overlap: a_start <= b_end AND b_start <= a_end
    return a_start.date() <= b_end.date() and b_start.date() <= a_end.date()


@bp.route("/bills", methods=["POST"])
def create_bill():
    with db.lock:
        p = authenticate()
        require_roles(p, {"Roommate"})
        body = validate.get_json_body()
        household_id = validate.require_str(body, "household_id")
        bill_type = validate.require_enum(body, "bill_type", BILL_TYPE)
        total = validate.require_int(body, "total_amount_cents", minimum=1)
        period_start = validate.require_datetime(body, "period_start")
        period_end = validate.require_datetime(body, "period_end")
        household = db.households.get(household_id)
        if not household:
            raise err("ERR_NOT_FOUND", "household_id does not exist.")
        # priority 11: RENT period overlap (closed interval) checked before period validity? PRD §2.11
        # ordering: existence -> state -> frozen -> business. Both are business_temporal;
        # scaffold lists overlap (p11) before invalid-period (p12).
        if bill_type == "RENT":
            for b in db.bills.values():
                if b["household_id"] == household_id and b["bill_type"] == "RENT":
                    if _rent_periods_overlap(period_start, period_end, b["period_start"], b["period_end"]):
                        raise err("ERR_BILL_PERIOD_OVERLAP", "RENT bill period overlaps an existing RENT bill.")
        # priority 12: period_end strictly after period_start
        if not (period_end.date() > period_start.date() or period_end > period_start):
            raise err("ERR_INVALID_PERIOD", "period_end must be strictly after period_start.")

        bill = {
            "household_id": household_id,
            "bill_type": bill_type,
            "total_amount_cents": total,
            "period_start": period_start,
            "period_end": period_end,
            "split_policy_used": household["split_policy"],
            "payment_status": "UNPAID",
            "reminder_status": "NONE",
        }
        models.stamp_create(bill)
        db.bills[bill["id"]] = bill
        # distribute across ACTIVE members
        hh.build_bill_splits(bill, household)
        # for a RENT bill, refresh occupied_days_estimate for each ACTIVE member
        if bill_type == "RENT":
            for m in hh.active_memberships(household_id):
                m["occupied_days_estimate"] = _estimate_for(m, bill)
                models.touch(m)
        return response.ok(models.serialize(bill), 201)


def _estimate_for(membership, bill):
    from services import calc
    return calc.occupied_days(
        membership["move_in_date"], membership["planned_move_out_date"],
        bill["period_start"], bill["period_end"],
    )


@bp.route("/bills/<bid>", methods=["GET"])
def get_bill(bid):
    with db.lock:
        p = authenticate()
        require_roles(p, ALL_ROLES)
        bill = db.bills.get(bid)
        if not bill:
            raise err("ERR_NOT_FOUND", "Bill not found.")
        return response.ok(models.serialize(bill))


@bp.route("/bills/<bid>/splits", methods=["GET"])
def list_bill_splits(bid):
    with db.lock:
        p = authenticate()
        require_roles(p, ALL_ROLES)
        if bid not in db.bills:
            raise err("ERR_NOT_FOUND", "Bill not found.")
        limit, offset = parse_pagination()
        items = [s for s in db.bill_splits.values() if s["bill_id"] == bid]
        items = models.sort_by_created(items)
        page, meta = paginate(items, limit, offset)
        return response.ok_list(models.serialize_list(page), pagination=meta)


@bp.route("/bills/<bid>/record-payment", methods=["POST"])
def record_payment(bid):
    with db.lock:
        p = authenticate()
        require_roles(p, {"Roommate"})
        bill = db.bills.get(bid)
        if not bill:
            raise err("ERR_NOT_FOUND", "Bill not found.")
        body = validate.get_json_body()
        profile_id = validate.require_str(body, "profile_id")
        if profile_id not in db.roommate_profiles:
            raise err("ERR_NOT_FOUND", "profile_id does not exist.")
        household = db.households.get(bill["household_id"])
        # ownership: acting roommate must be an ACTIVE member of the bill's household
        if not hh.is_active_member(household["id"], p.user_id):
            raise err("ERR_NOT_RESOURCE_OWNER", "Acting roommate is not an active member.")
        # frozen gate (priority 7)
        if household["status"] == "FROZEN":
            raise err("ERR_HOUSEHOLD_FROZEN", "Household is frozen.")
        # locate the payer's split
        splits = hh.splits_of_bill(bid)
        target = None
        for s in splits:
            if s["profile_id"] == profile_id:
                target = s
                break
        if target is None:
            raise err("ERR_NOT_HOUSEHOLD_MEMBER", "No split for this profile on the bill.")
        # state: already-paid split cannot pay again
        if target["paid"]:
            raise err("ERR_INVALID_STATE", "This split is already paid.")
        if bill["payment_status"] == "PAID":
            raise err("ERR_INVALID_STATE", "Bill is already PAID.")

        target["paid"] = True
        all_paid = all(s["paid"] for s in splits)
        some_paid = any(s["paid"] for s in splits)
        if all_paid:
            bill["payment_status"] = "PAID"
            # cancel any SCHEDULED reminder for this bill
            for r in db.payment_reminders.values():
                if r.get("bill_id") == bid and r["status"] == "SCHEDULED":
                    r["status"] = "CANCELLED"
                    models.touch(r)
        elif some_paid:
            bill["payment_status"] = "PARTIALLY_PAID"
        models.touch(bill)
        # paying an unpaid bill split changes the ledger obligations -> recompute net balances
        hh.recompute_net_balances(household)
        return response.ok(models.serialize(bill))
