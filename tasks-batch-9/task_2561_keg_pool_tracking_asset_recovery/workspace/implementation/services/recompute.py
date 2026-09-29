"""Derived state.  Every link of the cascade chain fires inside the mutating
request: keg custody -> pool census -> available_pct -> posture -> every
ACTIVE agreement's float_posture."""
import clock
import db
import util
from services import calc

# ------------------------------------------------------------- lookups -------


def active_agreements_of_pool(pool_id):
    return [row for row in db.agreements.values()
            if row["pool_id"] == pool_id and row["status"] == "ACTIVE"]


def active_agreements_of_brewer(brewer_id):
    return [row for row in db.agreements.values()
            if row["brewer_id"] == brewer_id and row["status"] == "ACTIVE"]


def active_agreement(brewer_id, pool_id):
    for row in db.agreements.values():
        if (row["brewer_id"] == brewer_id and row["pool_id"] == pool_id
                and row["status"] == "ACTIVE"):
            return row
    return None


def kegs_of_pool(pool_id):
    return [row for row in db.kegs.values() if row["pool_id"] == pool_id]


def orders_of_agreement(agreement_id):
    return [row for row in db.orders.values()
            if row["agreement_id"] == agreement_id]


# ------------------------------------------------------ pool census ----------


def pool_posture(pool, available_pct):
    if pool["kegs_total"] > 0 and available_pct >= pool["restrict_threshold_pct"]:
        return "OPEN"
    if pool["kegs_total"] > 0 and available_pct >= pool["freeze_threshold_pct"]:
        return "RESTRICTED"
    return "FROZEN"


def recompute_pool(pool):
    kegs = kegs_of_pool(pool["id"])
    total = len(kegs)
    available = 0
    circulating = 0
    servicing = 0
    held = 0
    written_off = 0
    for keg in kegs:
        state = keg["custody_state"]
        if state == "IN_FLOAT":
            available += 1
        elif state in calc.CIRCULATING_STATES:
            circulating += 1
        elif state in calc.SERVICING_STATES:
            servicing += 1
        elif state == "EVIDENCE_HOLD":
            held += 1
        elif state in calc.WRITTEN_OFF_STATES:
            written_off += 1
    if total == 0:
        available_pct = 0.00
    else:
        available_pct = util.rhu2(util.dec(100) * util.dec(available)
                                  / util.dec(total))
    changes = {
        "kegs_total": total,
        "kegs_available": available,
        "kegs_circulating": circulating,
        "kegs_servicing": servicing,
        "kegs_held": held,
        "kegs_written_off": written_off,
        "available_pct": available_pct,
    }
    merged = dict(pool)
    merged.update(changes)
    changes["posture"] = pool_posture(merged, available_pct)
    util.apply_changes(pool, changes)
    return pool


# -------------------------------------------------- agreement posture --------


def agreement_counters(agreement):
    at_brewer = 0
    for keg in db.kegs.values():
        if (keg["current_brewer_id"] == agreement["brewer_id"]
                and keg["pool_id"] == agreement["pool_id"]
                and keg["custody_state"] in ("ISSUED_TO_BREWER", "FILLED")):
            at_brewer += 1
    live_order_ids = set()
    for order in orders_of_agreement(agreement["id"]):
        if order["status"] in ("ALLOCATED", "PARTIALLY_ALLOCATED",
                               "DISPATCHED"):
            live_order_ids.add(order["id"])
    issued = 0
    for keg in db.kegs.values():
        if keg["issuance_order_id"] in live_order_ids:
            issued += 1
    return at_brewer, issued


def float_posture(agreement, at_brewer):
    pool = db.pools.get(agreement["pool_id"])
    brewer = db.brewers.get(agreement["brewer_id"])
    if pool is not None and pool["posture"] == "FROZEN":
        return "SUSPENDED"
    if brewer is not None and brewer["status"] in ("PROBATION", "SUSPENDED"):
        return "SUSPENDED"
    ceiling = (agreement["float_size_kegs"]
               * agreement["replenishment_threshold_pct"]) // 100
    if at_brewer <= ceiling:
        return "TIGHT"
    return "HEALTHY"


def recompute_agreement(agreement):
    """Only ACTIVE agreements are recomputed at all; DRAFT and TERMINATED
    agreements keep their last posture value and gate nothing."""
    if agreement["status"] != "ACTIVE":
        return agreement
    at_brewer, issued = agreement_counters(agreement)
    posture = float_posture(agreement, at_brewer)
    pending = max(0, agreement["float_size_kegs"] - at_brewer) \
        if posture == "TIGHT" else 0
    util.apply_changes(agreement, {
        "kegs_at_brewer_count": at_brewer,
        "kegs_issued_count": issued,
        "float_posture": posture,
        "pending_replenishment_kegs": pending,
    })
    return agreement


def cascade_pool(pool):
    if pool is None:
        return
    recompute_pool(pool)
    for agreement in active_agreements_of_pool(pool["id"]):
        recompute_agreement(agreement)


def cascade_pool_id(pool_id):
    cascade_pool(db.pools.get(pool_id))


def cascade_brewer(brewer):
    for agreement in active_agreements_of_brewer(brewer["id"]):
        recompute_agreement(agreement)


# ------------------------------------------------------ brewer ledger --------


def chargeback_balance(brewer_id):
    total = 0
    for row in db.assessments.values():
        if row["brewer_id"] == brewer_id and \
                row["chargeback_status"] in ("ISSUED", "SETTLED"):
            total += row["net_chargeback_cents"]
    return total


def recompute_brewer_balance(brewer):
    util.apply_changes(brewer,
                       {"chargeback_balance_cents":
                        chargeback_balance(brewer["id"])})


def recompute_brewer_loss_counters(brewer):
    upheld = 0
    for row in db.assessments.values():
        if row["brewer_id"] == brewer["id"] and \
                row["assessment_status"] == "UPHELD":
            upheld += 1
    fills = 0
    for scan in db.scan_events.values():
        if scan["scan_point"] == "FILL" and scan["brewer_id"] == brewer["id"]:
            fills += 1
    util.apply_changes(brewer, {"upheld_loss_count": upheld,
                                "lifetime_fill_count": fills})
    recompute_brewer_rates(brewer)


def recompute_brewer_rates(brewer):
    trailing = calc.loss_rate(brewer, "TRAILING_90D")["loss_rate_bp"]
    lifetime = calc.loss_rate(brewer, "LIFETIME")["loss_rate_bp"]
    util.apply_changes(brewer, {"loss_rate_bp_trailing_90d": trailing,
                                "loss_rate_bp_lifetime": lifetime})


def run_probation_gates(brewer):
    """The balance gate runs first and claims the transition; the loss-rate
    gate then finds the status is no longer ACTIVE and does not overwrite the
    reason."""
    if brewer["chargeback_balance_cents"] >= calc.CHARGEBACK_PROBATION_CENTS \
            and brewer["status"] == "ACTIVE":
        util.apply_changes(brewer, {
            "status": "PROBATION",
            "status_reason": "CHARGEBACK_BALANCE_THRESHOLD"})
    if brewer["loss_rate_bp_trailing_90d"] >= calc.LOSS_RATE_PROBATION_BP \
            and brewer["status"] == "ACTIVE":
        util.apply_changes(brewer, {
            "status": "PROBATION",
            "status_reason": "LOSS_RATE_THRESHOLD"})


def lift_balance_probation(brewer):
    """A reversal only undoes the gate it tripped."""
    if (brewer["status"] == "PROBATION"
            and brewer["status_reason"] == "CHARGEBACK_BALANCE_THRESHOLD"
            and brewer["chargeback_balance_cents"]
            < calc.CHARGEBACK_PROBATION_CENTS):
        util.apply_changes(brewer, {"status": "ACTIVE", "status_reason": None})


# ------------------------------------------------- distributor ledger --------


def return_accruals(distributor_id):
    return [row for row in db.accruals.values()
            if row["distributor_id"] == distributor_id
            and row["accrual_type"] == "RETURN_DWELL"
            and row["status"] in ("ACCRUED", "PAID", "CLAWED_BACK")]


def incentive_ledger(distributor_id):
    total = 0
    for row in db.accruals.values():
        if row["distributor_id"] == distributor_id and \
                row["status"] in ("ACCRUED", "PAID"):
            total += row["incentive_cents"]
    return total


def recompute_distributor_ledger(distributor):
    util.apply_changes(distributor, {
        "incentive_accrual_cents": incentive_ledger(distributor["id"])})


def recompute_distributor_stats(distributor):
    rows = return_accruals(distributor["id"])
    total = len(rows)
    on_time = len([row for row in rows
                   if row["dwell_days"] <= calc.DWELL_DISTRIBUTOR_LIMIT_DAYS])
    if total == 0:
        pct = 0.00
        avg = 0.00
    else:
        pct = util.rhu2(util.dec(100) * util.dec(on_time) / util.dec(total))
        avg = util.rhu2(util.dec(sum(row["dwell_days"] for row in rows))
                        / util.dec(total))
    util.apply_changes(distributor, {
        "total_returns_count": total,
        "on_time_returns_count": on_time,
        "on_time_return_pct": pct,
        "avg_dwell_days": avg,
        "incentive_accrual_cents": incentive_ledger(distributor["id"]),
    })


def maybe_promote_tier(distributor):
    """At most one step up the ladder, no step skipped, no auto-demotion."""
    tier = distributor["cooperation_tier"]
    total = distributor["total_returns_count"]
    pct = distributor["on_time_return_pct"]
    if tier == "BRONZE" and total >= 3 and pct >= 90.00:
        promoted = "SILVER"
    elif tier == "SILVER" and total >= 5 and pct >= 96.00:
        promoted = "GOLD"
    else:
        return
    util.apply_changes(distributor, {
        "cooperation_tier": promoted,
        "cooperation_effective_date": clock.now().date()})
