"""Rollup recomputation and the server-initiated propagation families (2.8)."""

from store import db, sort_key, stamp_new, touch, touch_time_only


# ---------------------------------------------------------------------------
# lookups
# ---------------------------------------------------------------------------

def rows(collection):
    return sorted(getattr(db, collection).values(), key=sort_key)


def period_shifts(period_id):
    return [s for s in rows("shifts") if s["pay_period_id"] == period_id]


def period_lines(period_id):
    return [p for p in rows("pay_lines") if p["pay_period_id"] == period_id]


def live_lines(period_id):
    return [p for p in period_lines(period_id) if p["status"] != "SUPERSEDED"]


def line_corrections(pay_line_id):
    return [c for c in rows("corrections") if c["pay_line_id"] == pay_line_id]


def period_covering(location_id, business_date):
    """The pay period of a unit whose inclusive date interval holds a day."""
    for period in rows("pay_periods"):
        if period["location_id"] != location_id:
            continue
        if period["start_date"] <= business_date <= period["end_date"]:
            return period
    return None


def date_in_period(period, business_date):
    return period["start_date"] <= business_date <= period["end_date"]


def net_pool_tips_by_shift(employee_id, period):
    """Net allocated cents per shift for one employee inside a period."""
    totals = {}
    for row in rows("allocations"):
        if row["employee_id"] != employee_id:
            continue
        if not date_in_period(period, row["business_date"]):
            continue
        totals[row["shift_id"]] = totals.get(row["shift_id"], 0) + row["allocated_cents"]
    return totals


# ---------------------------------------------------------------------------
# rollup recomputation
# ---------------------------------------------------------------------------

def recompute_location_pending(location):
    total = 0
    for pool in db.pools.values():
        if pool["location_id"] != location["id"]:
            continue
        if (
            pool["contribution_status"] == "CONTRIBUTED"
            and pool["distribution_status"] == "PENDING"
        ):
            total += pool["total_contributed_cents"] + pool["service_charge_tips_cents"]
    if location["pending_pool_cents"] != total:
        location["pending_pool_cents"] = total
    touch_time_only(location)


def recompute_employee_trailing(employee):
    total = 0
    for row in db.allocations.values():
        if row["employee_id"] == employee["id"]:
            total += row["allocated_cents"]
    employee["trailing_pool_receipts_cents"] = total
    touch(employee)


def recompute_period_shift_rollups(period):
    minutes = 0
    receipts = 0
    for shift in period_shifts(period["id"]):
        if shift["time_status"] == "CLOSED":
            minutes += shift["scheduled_minutes"]
            receipts += shift["gross_sales_cents"]
    period["total_credited_minutes"] = minutes
    period["gross_receipts_cents"] = receipts
    touch(period)


def recompute_period_line_rollups(period):
    tip_credit = 0
    topup = 0
    reported = 0
    for line in live_lines(period["id"]):
        tip_credit += line["tip_credit_cents"]
        topup += line["topup_cents"]
        reported += line["reported_tips_cents"]
    period["total_tip_credit_cents"] = tip_credit
    period["total_topup_cents"] = topup
    period["reported_tips_cents"] = reported
    touch(period)


def recompute_period_corrections(period):
    ids = set(line["id"] for line in period_lines(period["id"]))
    total = 0
    for correction in db.corrections.values():
        if correction["pay_line_id"] in ids and correction["status"] in (
            "PENDING",
            "APPLIED",
        ):
            total += correction["amount_cents"]
    period["total_correction_cents"] = total
    touch(period)


def recompute_line_corrections(line):
    pending = 0
    applied = 0
    for correction in line_corrections(line["id"]):
        if correction["status"] == "PENDING":
            pending += correction["amount_cents"]
        elif correction["status"] == "APPLIED":
            applied += correction["amount_cents"]
    line["pending_correction_cents"] = pending
    line["correction_applied_cents"] = applied


# ---------------------------------------------------------------------------
# pay-line invalidation and server-initiated reopening
# ---------------------------------------------------------------------------

def supersede_period_lines(period_id):
    for line in period_lines(period_id):
        if line["status"] in ("DRAFT", "FINAL"):
            line["status"] = "SUPERSEDED"
            touch(line)


def server_reopen(period):
    """Drive a COMPUTED or APPROVED period back to OPEN with no client request."""
    supersede_period_lines(period["id"])
    period["compute_variant"] = None
    period["computed_by_user_id"] = None
    period["approved_by_user_id"] = None
    period["total_tip_credit_cents"] = 0
    period["total_topup_cents"] = 0
    period["allocation_shortfall_cents"] = 0
    period["reported_tips_cents"] = 0
    period["status"] = "OPEN"
    touch(period)
    recompute_period_shift_rollups(period)


def invalidate_period(period):
    if period is not None and period["status"] in ("COMPUTED", "APPROVED"):
        server_reopen(period)


# ---------------------------------------------------------------------------
# pool reversal (3.7), used by the endpoint and by policy supersession
# ---------------------------------------------------------------------------

def reverse_pool(pool):
    was_distributed = pool["distribution_status"] == "DISTRIBUTED"

    pool["contribution_status"] = "REVERSED"
    pool["reversed_at"] = db.now()
    pool["total_contributed_cents"] = 0
    pool["service_charge_tips_cents"] = 0
    pool["cc_fee_deducted_cents"] = 0
    pool["net_pool_cents"] = 0

    touched_employees = set()
    if was_distributed:
        originals = [
            r
            for r in rows("allocations")
            if r["shift_tip_pool_id"] == pool["id"] and r["entry_type"] == "DISTRIBUTION"
        ]
        for row in originals:
            reversal = {
                "shift_tip_pool_id": pool["id"],
                "employee_id": row["employee_id"],
                "shift_id": row["shift_id"],
                "entry_type": "REVERSAL",
                "share_weight": row["share_weight"],
                "allocated_cents": -row["allocated_cents"],
                "remainder_cent_awarded": row["remainder_cent_awarded"],
                "business_date": row["business_date"],
            }
            stamp_new(reversal, with_version=False)
            db.allocations[reversal["id"]] = reversal
            touched_employees.add(row["employee_id"])
        pool["distribution_status"] = "REVERSED"
        pool["distributed_cents"] = 0
    else:
        pool["distribution_status"] = "REVERSED"
        pool["distributed_cents"] = 0
    touch(pool)

    affected_periods = {}
    for shift in rows("shifts"):
        if shift["shift_tip_pool_id"] != pool["id"]:
            continue
        shift["shift_tip_pool_id"] = None
        shift["pool_contribution_cents"] = 0
        shift["retained_tips_cents"] = (
            shift["declared_cash_tips_cents"] + shift["declared_charged_tips_cents"]
        )
        touch(shift)
        period = db.pay_periods.get(shift["pay_period_id"])
        if period is not None:
            affected_periods[period["id"]] = period

    for employee_id in touched_employees:
        employee = db.employees.get(employee_id)
        if employee is not None:
            recompute_employee_trailing(employee)

    for period in affected_periods.values():
        if period["status"] in ("COMPUTED", "APPROVED"):
            server_reopen(period)
        else:
            recompute_period_shift_rollups(period)

    location = db.locations.get(pool["location_id"])
    if location is not None:
        recompute_location_pending(location)
    return pool
