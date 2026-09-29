"""Derived-field recomputation, the staffing grounding loop and the cascades.

PRD 2.4 (a change to a derived attribute is a mutation), 2.7 (multi-hop cascades),
2.8 (ledger conservation), 3.2/3.3 (staffing), 3.5/3.7/3.8 (stale-scorecard chain).
"""

import calc
from core import round2, round3
from db import ordered, store, touch


# --------------------------------------------------------------- CrewBase staffing
def recompute_base(base):
    fields = calc.pilot_staffing_shortfall(base)
    changed = any(base.get(name) != value for name, value in fields.items())
    base.update(fields)
    return changed


def _ground_or_restore(base):
    assigned = base["assigned_aircraft_count"]
    allocatable = base["allocatable_aircraft_count"]
    tails = [tail for tail in store.aircraft.values()
             if tail["assigned_base_id"] == base["id"]]
    in_service = [tail for tail in tails if tail["status"] == "IN_SERVICE"]

    if assigned > allocatable:
        # Ground exactly (assigned - allocatable) tails: created_at DESC,
        # tail_number ASC as the tie-break (PRD 3.3).
        candidates = sorted(in_service, key=lambda t: (t["tail_number"], t["id"]))
        candidates.sort(key=lambda t: t["created_at"], reverse=True)
        for tail in candidates[:assigned - allocatable]:
            tail["status"] = "GROUNDED_STAFFING"
            tail["grounded_reason"] = "STAFFING_SHORTFALL"
            touch(tail)
        return

    shortfall = allocatable - len(in_service)
    if shortfall <= 0:
        return
    grounded = [tail for tail in tails if tail["status"] == "GROUNDED_STAFFING"]
    candidates = sorted(grounded, key=lambda t: (t["created_at"], t["tail_number"],
                                                 t["id"]))
    for tail in candidates[:shortfall]:
        tail["status"] = "IN_SERVICE"
        tail["grounded_reason"] = None
        touch(tail)


def apply_base_staffing(base):
    """Recompute the base's six derived staffing figures, then ground or restore."""
    if recompute_base(base):
        touch(base)
    _ground_or_restore(base)


# ------------------------------------------------------------ ScheduleCycle ledger
CONTROLLABLE_CLAIM_STATUSES = ("OPEN", "CLASSIFIED", "DISPUTED", "FINALIZED")


def cycle_derived(cycle):
    cycle_id = cycle["id"]
    completed = 0
    open_legs = 0
    block_hours = round3(0)
    enplaned = 0
    mishandled = 0
    on_time = 0
    for leg in store.flight_legs.values():
        if leg["cycle_id"] != cycle_id:
            continue
        if leg["status"] == "COMPLETED":
            completed += 1
            if leg.get("actual_block_hours") is not None:
                block_hours += leg["actual_block_hours"]
            enplaned += leg.get("enplaned_bags") or 0
            mishandled += leg.get("mishandled_bags") or 0
            if leg.get("on_time"):
                on_time += 1
        elif leg["status"] == "SCHEDULED":
            open_legs += 1

    controllable = 0
    uncontrollable = 0
    for claim in store.cancellation_claims.values():
        if claim["cycle_id"] != cycle_id:
            continue
        if (claim["status"] in CONTROLLABLE_CLAIM_STATUSES
                and claim["effective_classification"] == "CONTROLLABLE"):
            controllable += 1
        if claim["status"] == "FINALIZED" and claim["classification"] == "UNCONTROLLABLE":
            uncontrollable += 1

    published = cycle["published_departures"]
    metric = published - controllable - uncontrollable
    _, _, settlement = calc.passthrough_settlement(cycle_id)

    return {
        "recorded_completed_legs": completed,
        "open_leg_count": open_legs,
        "cancelled_controllable_count": controllable,
        "cancelled_uncontrollable_count": uncontrollable,
        "metric_completed_departures": metric,
        "departure_ledger_total": metric + controllable + uncontrollable,
        "credited_block_hours": round3(block_hours),
        "enplaned_bags_total": enplaned,
        "mishandled_bags_total": mishandled,
        "on_time_leg_count": on_time,
        "estimated_passthrough_total_usd": calc.estimated_passthrough_total(cycle_id),
        "passthrough_settlement_usd": settlement,
    }


def recompute_cycle(cycle):
    """Returns (anything_changed, cancellation_counters_changed)."""
    fields = cycle_derived(cycle)
    changed = any(cycle.get(name) != value for name, value in fields.items())
    counters_changed = (
        cycle.get("cancelled_controllable_count") != fields["cancelled_controllable_count"]
        or cycle.get("cancelled_uncontrollable_count")
        != fields["cancelled_uncontrollable_count"]
    )
    cycle.update(fields)
    return changed, counters_changed


def refresh_cycle(cycle, cascade=False):
    """Recompute the cycle; when cascade, a counter move stales the scorecard."""
    changed, counters_changed = recompute_cycle(cycle)
    if changed:
        touch(cycle)
    if cascade and counters_changed:
        stale_scorecards_of_cycle(cycle)
    return counters_changed


# -------------------------------------------------------------- Agreement counters
def agreement_derived(agreement):
    cycle_ids = set(cycle["id"] for cycle in store.schedule_cycles.values()
                    if cycle["agreement_id"] == agreement["id"])
    settled = round2(0)
    open_invoices = 0
    for invoice in store.invoices.values():
        if invoice["cycle_id"] not in cycle_ids:
            continue
        if invoice["status"] == "ISSUED":
            settled += invoice["total_usd"]
        elif invoice["status"] == "DRAFT":
            open_invoices += 1
    return {
        "settled_to_date_usd": round2(settled),
        "open_invoice_count": open_invoices,
    }


def refresh_agreement(agreement):
    fields = agreement_derived(agreement)
    changed = any(agreement.get(name) != value for name, value in fields.items())
    agreement.update(fields)
    if changed:
        touch(agreement)
    return changed


def agreement_of_cycle(cycle):
    return store.agreements[cycle["agreement_id"]]


def agreement_of_base(base):
    return store.agreements[base["agreement_id"]]


# ---------------------------------------------------------------------- Scorecard
def scorecard_figures(cycle):
    agreement = agreement_of_cycle(cycle)
    completion_factor_pct = calc.completion_factor(
        cycle["published_departures"],
        cycle["cancelled_uncontrollable_count"],
        cycle["cancelled_controllable_count"],
    )
    on_time_arrival_pct = calc.on_time_arrival(
        cycle["on_time_leg_count"], cycle["recorded_completed_legs"])
    mishandled_bags_per_1000 = calc.mishandled_bag_rate(
        cycle["mishandled_bags_total"], cycle["enplaned_bags_total"])
    points = calc.performance_incentive_penalty(
        completion_factor_pct, on_time_arrival_pct, mishandled_bags_per_1000,
        agreement, cycle)
    figures = {
        "completion_factor_pct": completion_factor_pct,
        "on_time_arrival_pct": on_time_arrival_pct,
        "mishandled_bags_per_1000": mishandled_bags_per_1000,
        "brand_penalty_usd": calc.brand_consistency_penalty(agreement["id"]),
    }
    figures.update(points)
    return figures


def scorecards_of_cycle(cycle_id):
    return ordered([card for card in store.scorecards.values()
                    if card["cycle_id"] == cycle_id])


def stale_scorecards_of_cycle_exist(cycle_id):
    """True when any scorecard of the month is sitting in STALE (PRD 3.8)."""
    return any(card["status"] == "STALE" for card in scorecards_of_cycle(cycle_id))


def stale_scorecards_of_cycle(cycle):
    for card in scorecards_of_cycle(cycle["id"]):
        if card["status"] == "PUBLISHED":
            make_scorecard_stale(card)


def stale_scorecards_of_agreement(agreement_id):
    """A brand audit entering or leaving the exposure set stales every published
    scorecard of a settlement month of the same agreement (PRD 3.7)."""
    cycle_ids = set(cycle["id"] for cycle in store.schedule_cycles.values()
                    if cycle["agreement_id"] == agreement_id)
    for card in ordered([c for c in store.scorecards.values()
                         if c["cycle_id"] in cycle_ids]):
        if card["status"] == "PUBLISHED":
            make_scorecard_stale(card)


def make_scorecard_stale(card):
    card["status"] = "STALE"
    touch(card)
    cycle = store.schedule_cycles[card["cycle_id"]]
    victims = ordered([invoice for invoice in store.invoices.values()
                       if invoice["cycle_id"] == cycle["id"]
                       and invoice["status"] in ("DRAFT", "ISSUED")])
    for invoice in victims:
        void_invoice(invoice, "AUTO_SCORECARD_STALE")


# ------------------------------------------------------------------------ Invoice
def void_invoice(invoice, reason):
    was_issued = invoice["status"] == "ISSUED"
    invoice["status"] = "VOIDED"
    invoice["void_reason"] = reason
    touch(invoice)
    cycle = store.schedule_cycles[invoice["cycle_id"]]
    if was_issued and cycle["status"] == "SETTLED":
        cycle["status"] = "CLOSED"
    recompute_cycle(cycle)
    # PRD 3.8: voiding moves the invoice's, the month's and the agreement's version.
    touch(cycle)
    refresh_agreement(agreement_of_cycle(cycle))
