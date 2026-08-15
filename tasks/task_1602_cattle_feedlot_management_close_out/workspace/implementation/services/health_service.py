"""Health event and death loss business logic."""
from datetime import timedelta

import store
import clock
from util import new_record, bump, add_days
from errors import raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE_TRANSITION, \
    ERR_VOID_BLOCKED_BY_CLAIMS, ERR_LOT_NOT_FOUND
from . import lot_service
from . import pen_service
from . import calculations


def create_health_event(lot, treatment_date, drug_product, withdrawal_days,
                        head_treated, treatment_cost_cents):
    """Create a health event for a lot."""
    lot_service.check_lot_open(lot)

    # Validate treatment_date range
    if treatment_date < lot["arrival_date"] or treatment_date > clock.today():
        raise_err(ERR_INVALID_REQUEST,
                  "treatment_date must be within [arrival_date, current date]")

    # Validate head_treated
    if head_treated < 1 or head_treated > lot["head_count_current"]:
        raise_err(ERR_INVALID_REQUEST,
                  "head_treated must be in 1..head_count_current")

    # Compute withdrawal_end_date
    withdrawal_end_date = add_days(treatment_date, withdrawal_days)

    rec = new_record()
    rec.update({
        "lot_id": lot["id"],
        "treatment_date": treatment_date,
        "drug_product": drug_product,
        "withdrawal_days": withdrawal_days,
        "head_treated": head_treated,
        "treatment_cost_cents": treatment_cost_cents,
        "withdrawal_end_date": withdrawal_end_date,
        "status": "WITHDRAWAL_ACTIVE",
    })
    store.health_events[rec["id"]] = rec

    # Update lot
    lot["total_health_cost_cents"] += treatment_cost_cents
    lot_service.recompute_withdrawal_clear_date(lot)
    lot_service.bump_lot(lot)

    return rec


def create_death_loss(lot, loss_date, head_count, cause, insured):
    """Create a death loss for a lot with waterfall allocation to pen assignments."""
    lot_service.check_lot_open(lot)

    # Validate loss_date range
    if loss_date < lot["arrival_date"] or loss_date > clock.today():
        raise_err(ERR_INVALID_REQUEST,
                  "loss_date must be within [arrival_date, current date]")

    # Validate head_count
    if head_count < 1 or head_count > lot["head_count_current"]:
        raise_err(ERR_INVALID_REQUEST,
                  "head_count must be in 1..head_count_current")

    # Compute loss value
    loss_value_cents = calculations.compute_death_loss_value(lot, loss_date, head_count)

    # Allocate to ACTIVE pen assignments (oldest-created first, waterfall)
    active_assignments = [
        pa for pa in store.pen_assignments.values()
        if pa["lot_id"] == lot["id"] and pa["status"] == "ACTIVE"
    ]
    active_assignments.sort(key=lambda pa: pa["created_at"])

    allocations = []
    remaining = head_count
    for pa in active_assignments:
        if remaining <= 0:
            break
        alloc_count = min(remaining, pa["head_count"])
        if alloc_count > 0:
            allocations.append({
                "assignment_id": pa["id"],
                "head_count": alloc_count,
            })
            pa["head_count"] -= alloc_count
            bump(pa)
            remaining -= alloc_count

    rec = new_record()
    rec.update({
        "lot_id": lot["id"],
        "loss_date": loss_date,
        "head_count": head_count,
        "cause": cause,
        "insured": insured,
        "loss_value_cents": loss_value_cents,
        "allocations": allocations,
        "status": "RECORDED",
    })
    store.death_losses[rec["id"]] = rec

    # Update lot
    lot["head_count_current"] -= head_count
    lot["total_deaths"] += head_count
    lot["total_death_loss_cents"] += loss_value_cents

    # Recompute pen occupancies
    affected_pens = set()
    for alloc in allocations:
        pa = store.pen_assignments.get(alloc["assignment_id"])
        if pa:
            affected_pens.add(pa["pen_id"])
    for pen_id in affected_pens:
        pen = store.pens.get(pen_id)
        if pen:
            pen_service.recompute_pen_occupancy(pen)

    lot_service.bump_lot(lot)

    return rec


def void_death_loss(death_loss):
    """Void a death loss (compensating action)."""
    if death_loss["status"] != "RECORDED":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Death loss %s is not RECORDED (status=%s)"
                  % (death_loss["id"], death_loss["status"]))

    # Check no insurance claim references this loss
    for claim in store.insurance_claims.values():
        if claim["death_loss_id"] == death_loss["id"]:
            raise_err(ERR_VOID_BLOCKED_BY_CLAIMS,
                      "Death loss %s is referenced by insurance claim %s"
                      % (death_loss["id"], claim["id"]))

    lot = store.lots.get(death_loss["lot_id"])
    if lot is None:
        raise_err(ERR_LOT_NOT_FOUND, "Lot not found: %s" % death_loss["lot_id"])

    # Restore head counts to pen assignments
    affected_pens = set()
    for alloc in death_loss["allocations"]:
        pa = store.pen_assignments.get(alloc["assignment_id"])
        if pa:
            pa["head_count"] += alloc["head_count"]
            bump(pa)
            affected_pens.add(pa["pen_id"])

    # Recompute pen occupancies
    for pen_id in affected_pens:
        pen = store.pens.get(pen_id)
        if pen:
            pen_service.recompute_pen_occupancy(pen)

    # Restore lot
    lot["head_count_current"] += death_loss["head_count"]
    lot["total_deaths"] -= death_loss["head_count"]
    lot["total_death_loss_cents"] -= death_loss["loss_value_cents"]

    # Mark voided
    death_loss["status"] = "VOIDED"
    bump(death_loss)
    lot_service.bump_lot(lot)

    return death_loss
