"""Logical clock control and the periodic obligation evaluation pass."""
from flask import Blueprint

from calc import (LIVE_DISPUTE_STATUSES, OBLIGATION_WARNING_DAYS, continuous_dev_deadline,
                  db, expire_lease, has_live_dispute, lease_allocations,
                  new_counters, open_obligation_date, shut_in_next_due)
from common import add_days, clock, dec, fmt_ts, now_ts, ok, parse_datetime, q2, today, touch
from errors import fail
from store import by_created, rows
from validate import (ROLE_COMPLIANCE, ROLE_JIA, ROLE_LAND, authenticate,
                      authorize, body, require)

clock_bp = Blueprint("clock", __name__)
bp = Blueprint("system", __name__)


@clock_bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authenticate()
    authorize(ROLE_LAND, ROLE_JIA, ROLE_COMPLIANCE)
    data = body()
    require(data, ["current_utc"])
    moment = parse_datetime(data.get("current_utc"))
    if moment is None:
        fail("ERR_VALIDATION")
    if moment < clock.now():
        fail("ERR_CLOCK_MOVED_BACKWARD")
    clock.set(moment)
    return ok({"current_utc": fmt_ts(clock.now())})


# ---------------------------------------------------------------- lease posture

def committed_wells(lease):
    found = []
    for alloc in lease_allocations(lease["id"], committed_only=True):
        well = db.wells.get(alloc["well_id"])
        if well is not None:
            found.append(well)
    return found


def feeds_producing_pooled(wells):
    return any(w["well_status"] == "PRODUCING" and w["pooling_status"] == "POOLED_EFFECTIVE"
               for w in wells)


def feeds_shut_in_pooled(wells):
    return any(w["well_status"] == "SHUT_IN" and w["pooling_status"] == "POOLED_EFFECTIVE"
               for w in wells)


def feeds_producing(wells):
    return any(w["well_status"] == "PRODUCING" for w in wells)


def all_shut_in(wells):
    return bool(wells) and all(w["well_status"] == "SHUT_IN" for w in wells)


def shut_in_chain_current(lease):
    due = lease.get("shut_in_next_due_date")
    return (int(lease["shut_in_payments_made"]) >= 1 and due is not None
            and today() <= due)


def refresh_held_acres(lease):
    value = min(dec(lease["gross_acres"]), dec(lease["committed_acres_total"]))
    lease["held_acres"] = q2(value)


def refresh_deadlines(lease):
    lease["shut_in_next_due_date"] = shut_in_next_due(lease)
    lease["continuous_dev_deadline"] = continuous_dev_deadline(lease)


def evaluate_tenure(lease, counters):
    """Tenure maintenance and the three expiry paths (PRD 3.1)."""
    refresh_deadlines(lease)
    wells = committed_wells(lease)
    now_date = today()
    tenure = lease["tenure_status"]

    if tenure == "PRIMARY_TERM":
        if now_date <= lease["primary_term_end_date"]:
            return
        if feeds_producing_pooled(wells):
            lease["tenure_status"] = "HELD_BY_PRODUCTION"
            refresh_held_acres(lease)
            lease["obligation_status"] = "COMPLIANT"
            touch(lease)
            return
        if feeds_shut_in_pooled(wells) and shut_in_chain_current(lease):
            lease["tenure_status"] = "SHUT_IN_HELD"
            refresh_held_acres(lease)
            touch(lease)
            return
        carried_by_shut_in = (any(w["well_status"] == "SHUT_IN" for w in wells)
                              and shut_in_chain_current(lease))
        deadline = lease.get("continuous_dev_deadline")
        if not carried_by_shut_in and (deadline is None or now_date > deadline):
            expire_lease(lease, counters)
        return

    if tenure == "HELD_BY_PRODUCTION":
        if all_shut_in(wells) and shut_in_chain_current(lease):
            lease["tenure_status"] = "SHUT_IN_HELD"
            touch(lease)
        return

    if tenure == "SHUT_IN_HELD":
        if feeds_producing_pooled(wells):
            lease["tenure_status"] = "HELD_BY_PRODUCTION"
            lease["shut_in_start_date"] = None
            lease["shut_in_next_due_date"] = None
            lease["shut_in_payments_made"] = 0
            lease["obligation_status"] = "COMPLIANT"
            touch(lease)
            return
        due = lease.get("shut_in_next_due_date")
        if due is not None and now_date > due and not feeds_producing(wells):
            expire_lease(lease, counters)
        return

    if tenure == "CONTINUOUS_DEV_HELD":
        if feeds_producing_pooled(wells):
            lease["tenure_status"] = "HELD_BY_PRODUCTION"
            lease["obligation_status"] = "COMPLIANT"
            touch(lease)
            return
        deadline = lease.get("continuous_dev_deadline")
        if (deadline is not None and now_date > deadline
                and now_date > lease["primary_term_end_date"]
                and not feeds_producing(wells)):
            expire_lease(lease, counters)
        return


def evaluate_obligation(lease, counters):
    """Warning window, breach and the cure cycle (PRD 3.1)."""
    if lease["tenure_status"] == "EXPIRED":
        return
    refresh_deadlines(lease)
    open_date = open_obligation_date(lease)
    now_date = today()
    in_window = (open_date is not None
                 and add_days(open_date, -OBLIGATION_WARNING_DAYS) <= now_date <= open_date)
    status = lease["obligation_status"]

    if status == "COMPLIANT":
        if in_window:
            lease["obligation_status"] = "OBLIGATION_DUE"
            touch(lease)
            counters["leases_flagged_obligation_due"] += 1
        return

    if status == "OBLIGATION_DUE":
        if open_date is not None and now_date > open_date:
            lease["obligation_status"] = "IN_BREACH"
            touch(lease)
            counters["leases_in_breach"] += 1
            expire_lease(lease, counters)
        return

    if status == "CURED":
        if in_window:
            lease["obligation_status"] = "OBLIGATION_DUE"
            touch(lease)
            counters["leases_flagged_obligation_due"] += 1
        else:
            lease["obligation_status"] = "COMPLIANT"
            touch(lease)
        return


# ---------------------------------------------------------------- deemed outcomes

def evaluate_disputes(counters):
    now_date = today()
    for dispute in by_created(rows("disputes")):
        status = dispute["dispute_status"]
        if status == "OPEN":
            due = dispute.get("response_due_date")
            if due is not None and now_date > due:
                dispute["dispute_status"] = "ESCALATED"
                dispute["deemed_in_favor_of_partner"] = True
                touch(dispute)
                counters["disputes_escalated"] += 1
        elif status == "OPERATOR_RESPONDED":
            due = dispute.get("rebuttal_due_date")
            if due is not None and now_date > due:
                dispute["dispute_status"] = "EXPIRED"
                dispute["adjustment_amount_cents"] = 0
                touch(dispute)
                counters["disputes_expired"] += 1
                statement = db.statements.get(dispute["statement_id"])
                if (statement is not None
                        and statement["statement_status"] == "DISPUTED"
                        and not has_live_dispute(statement["id"])):
                    statement["statement_status"] = "ISSUED"
                    touch(statement)


def evaluate_statements():
    """Deemed settlement: an ISSUED statement with no live dispute whose
    payment_due_date the clock has passed settles (PRD 3.7)."""
    now_date = today()
    for statement in by_created(rows("statements")):
        if statement["statement_status"] != "ISSUED":
            continue
        due = statement.get("payment_due_date")
        if due is None or now_date <= due:
            continue
        if has_live_dispute(statement["id"]):
            continue
        statement["statement_status"] = "SETTLED"
        touch(statement)


def evaluate_transfers(counters):
    now_date = today()
    for transfer in by_created(rows("transfers")):
        if transfer["transfer_status"] != "NOTICED":
            continue
        if now_date > transfer["ppr_deadline_date"]:
            transfer["transfer_status"] = "PPR_WAIVED"
            touch(transfer)
            counters["transfers_deemed_waived"] += 1


@bp.route("/obligation-runs", methods=["POST"])
def obligation_run():
    authenticate()
    authorize(ROLE_COMPLIANCE)
    counters = new_counters()
    leases = by_created(rows("leases"))
    for lease in leases:
        if lease["tenure_status"] == "EXPIRED":
            continue
        evaluate_tenure(lease, counters)
    for lease in leases:
        evaluate_obligation(lease, counters)
    evaluate_disputes(counters)
    evaluate_statements()
    evaluate_transfers(counters)
    payload = {"evaluated_at": fmt_ts(now_ts())}
    payload.update(counters)
    return ok(payload)
