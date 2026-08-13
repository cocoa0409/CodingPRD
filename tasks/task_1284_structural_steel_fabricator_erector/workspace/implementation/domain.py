"""Domain logic: derived aggregates, calculation rules, cascades, and the
compound job-completion check.

Job aggregates are computed live from the underlying records on every read and
at every point of use, so they can never drift; job.version is bumped (touch)
at every declared side-effect point per PRD 2.4.
"""

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from store import public, store, touch

# Calculation constants (SCAFFOLD calculations table)
RETAINAGE_RATE_HIGH = Decimal("0.10")
RETAINAGE_RATE_LOW = Decimal("0.05")
RETAINAGE_THRESHOLD = Decimal("0.5000")
MILL_TOLERANCE_NUM = 1  # abs(received-ordered)*10 <= ordered*1
MILL_TOLERANCE_DEN = 10
BACKCHARGE_MARKUP = Decimal("0.15")
WELDER_CONTINUITY_DAYS = 183
LAYDOWN_BUFFER_DAYS = 2


def rhu(value):
    """Round half up to whole cents (integer)."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def pieces_of_job(job_id):
    return [p for p in store.pieces.values() if p["job_id"] == job_id]


def billings_of_job(job_id):
    return [b for b in store.billings.values() if b["job_id"] == job_id]


def backcharges_of_job(job_id):
    return [b for b in store.backcharges.values() if b["job_id"] == job_id]


def booked_billings(job_id):
    """Billings counted in aggregates: APPROVED or PAID only."""
    return [b for b in billings_of_job(job_id) if b["status"] in ("APPROVED", "PAID")]


def billed_to_date(job_id):
    return sum(b["net_due_cents"] for b in booked_billings(job_id))


def retainage_held(job_id):
    return sum(b["retainage_booked_cents"] for b in booked_billings(job_id))


def pending_backcharge(job_id):
    return sum(
        b["amount_cents"]
        for b in backcharges_of_job(job_id)
        if b["status"] in ("PENDING", "ACCEPTED", "DISPUTED")
    )


def settled_backcharge(job_id):
    return sum(
        (b["settled_amount_cents"] or 0)
        for b in backcharges_of_job(job_id)
        if b["status"] == "SETTLED"
    )


# ---------------------------------------------------------------------------
# Calculation: piece_percent_complete (4 dp, round half up)
# ---------------------------------------------------------------------------

def compute_pct(job, pieces=None):
    if pieces is None:
        pieces = pieces_of_job(job["id"])
    if not pieces:
        return Decimal("0.0000")
    if job["billing_basis"] == "WEIGHT":
        denom = sum(p["weight_lbs"] for p in pieces)
        numer = sum(p["weight_lbs"] for p in pieces if p["status"] == "ERECTED")
        if denom == 0:
            return Decimal("0.0000")
        ratio = Decimal(numer) / Decimal(denom)
    else:  # COUNT
        numer = sum(1 for p in pieces if p["status"] == "ERECTED")
        ratio = Decimal(numer) / Decimal(len(pieces))
    return ratio.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def job_view(job):
    pieces = pieces_of_job(job["id"])
    total_w = sum(p["weight_lbs"] for p in pieces)
    erected_w = sum(p["weight_lbs"] for p in pieces if p["status"] == "ERECTED")
    view = public(job)
    view["total_weight_lbs"] = total_w
    view["erected_weight_lbs"] = erected_w
    view["pct_complete"] = float(compute_pct(job, pieces))
    view["billed_to_date_cents"] = billed_to_date(job["id"])
    view["retainage_held_cents"] = retainage_held(job["id"])
    view["pending_backcharge_cents"] = pending_backcharge(job["id"])
    view["settled_backcharge_cents"] = settled_backcharge(job["id"])
    return view


# ---------------------------------------------------------------------------
# Calculation: net_progress_billing (snapshot frozen on the billing row)
# ---------------------------------------------------------------------------

def compute_billing_snapshot(job):
    pct = compute_pct(job)
    earned_cum = rhu(Decimal(job["contract_value_cents"]) * pct)
    rate = RETAINAGE_RATE_LOW if pct >= RETAINAGE_THRESHOLD else RETAINAGE_RATE_HIGH
    retainage_cum = rhu(Decimal(earned_cum) * rate)
    prior = booked_billings(job["id"])
    prev_net = sum(b["net_due_cents"] for b in prior)
    prev_ret_cum = sum(b["retainage_cum_cents"] for b in prior)
    net_due = earned_cum - retainage_cum - settled_backcharge(job["id"]) - prev_net
    retainage_booked = retainage_cum - prev_ret_cum
    return {
        "pct_complete_snapshot": float(pct),
        "earned_cum_cents": earned_cum,
        "retainage_cum_cents": retainage_cum,
        "retainage_booked_cents": retainage_booked,
        "net_due_cents": net_due,
    }


# ---------------------------------------------------------------------------
# Calculation: mill_order_invoice
# ---------------------------------------------------------------------------

def within_mill_tolerance(ordered_weight_lbs, received_weight_lbs):
    # abs(received - ordered) <= 0.10 * ordered; exactly +/-10% is accepted.
    return abs(received_weight_lbs - ordered_weight_lbs) * MILL_TOLERANCE_DEN <= (
        ordered_weight_lbs * MILL_TOLERANCE_NUM
    )


def mill_order_invoice(order):
    price = Decimal(order["unit_price_per_cwt_cents"])
    if order["billing_mode"] == "NOMINAL":
        weight = Decimal(order["ordered_weight_lbs"])
    else:  # ACTUAL
        weight = Decimal(order["received_weight_lbs"])
    return rhu(weight / Decimal(100) * price)


# ---------------------------------------------------------------------------
# Calculation: backcharge_amount (pinned rounding: per-line labor, then markup)
# ---------------------------------------------------------------------------

def backcharge_amount(repair_lines):
    subtotal = 0
    for line in repair_lines:
        labor = rhu(Decimal(str(line["labor_hours"])) * Decimal(line["labor_rate_cents"]))
        subtotal += labor + line["material_cents"]
    markup = rhu(Decimal(subtotal) * BACKCHARGE_MARKUP)
    return subtotal + markup


# ---------------------------------------------------------------------------
# Calculation: load_weight
# ---------------------------------------------------------------------------

def load_lines(load_id):
    return [p for p in store.pieces.values() if p["load_id"] == load_id]


def load_total_weight(load_id):
    return sum(p["weight_lbs"] for p in load_lines(load_id))


def recompute_load(load):
    lines = load_lines(load["id"])
    load["total_weight_lbs"] = sum(p["weight_lbs"] for p in lines)
    if load["status"] == "LOADING" and len(lines) == 0:
        load["status"] = "STAGING"
    touch(load)


# ---------------------------------------------------------------------------
# Calculation: welder_continuity / qualification
# ---------------------------------------------------------------------------

def welder_qualified(welder, process, current_date):
    if welder["status"] != "ACTIVE":
        return False
    if welder["qual_process"] != process:
        return False
    if current_date > date.fromisoformat(welder["qual_expires_on"]):
        return False
    priors = [
        w
        for w in store.welds.values()
        if w["welder_id"] == welder["id"] and w["process"] == process
    ]
    if not priors:
        return True
    max_weld_date = max(date.fromisoformat(w["weld_date"]) for w in priors)
    return max_weld_date >= current_date - timedelta(days=WELDER_CONTINUITY_DAYS)


# ---------------------------------------------------------------------------
# Calculation: welder_window_overlap (half-open)
# ---------------------------------------------------------------------------

def welder_window_conflict(welder_id, new_start, new_end):
    for w in store.welds.values():
        if w["welder_id"] != welder_id:
            continue
        ex_start = w["_window_start_dt"]
        ex_end = w["_window_end_dt"]
        if not (new_end <= ex_start or new_start >= ex_end):
            return True
    return False


# ---------------------------------------------------------------------------
# Calculation: laydown_slot_conflict (buffered closed semantics)
# ---------------------------------------------------------------------------

def laydown_slot_conflict(slot, delivery_date):
    for load in store.loads.values():
        if load["laydown_slot"] != slot:
            continue
        if load["status"] not in ("STAGING", "LOADING"):
            continue  # SHIPPED frees the slot
        existing = date.fromisoformat(load["delivery_date"])
        if abs((delivery_date - existing).days) <= LAYDOWN_BUFFER_DAYS:
            return True
    return False


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def supersede_cascade(new_drawing):
    """Drawing-approval cascade: supersede predecessor, stale its pieces, pull
    stale pieces off loads."""
    src_id = new_drawing["supersedes_id"]
    if not src_id:
        return
    src = store.drawings.get(src_id)
    if src is None or src["status"] != "APPROVED":
        return
    src["status"] = "SUPERSEDED"
    touch(src)
    affected_loads = []
    for piece in store.pieces.values():
        if piece["drawing_id"] != src["id"]:
            continue
        if piece["status"] in ("SHIPPED", "ERECTED"):
            continue  # grandfathered
        piece["stale_revision"] = True
        if piece["load_id"]:
            load = store.loads.get(piece["load_id"])
            piece["load_id"] = None
            if load is not None and load not in affected_loads:
                affected_loads.append(load)
        touch(piece)
    for load in affected_loads:
        recompute_load(load)


def erect_cascade(piece):
    """Erection cascade: refresh job erected weight, auto-complete the
    sequence, run the compound completion check."""
    job = store.jobs.get(piece["job_id"])
    if job is not None:
        touch(job)  # erected_weight_lbs recomputed (derived live; version bump)
    seq = store.sequences.get(piece["sequence_id"])
    if seq is not None and seq["status"] == "RELEASED":
        seq_pieces = [p for p in store.pieces.values() if p["sequence_id"] == seq["id"]]
        if seq_pieces and all(p["status"] == "ERECTED" for p in seq_pieces):
            seq["status"] = "ERECTED"
            touch(seq)
    if job is not None:
        compound_completion_check(job)


def compound_completion_check(job):
    """The only route to COMPLETE. Re-evaluated after every piece erect,
    sequence auto-completion, billing pay/void, and backcharge settle."""
    if job["status"] != "ERECTING":
        return
    seqs = [s for s in store.sequences.values() if s["job_id"] == job["id"]]
    if not seqs or any(s["status"] != "ERECTED" for s in seqs):
        return
    billings = billings_of_job(job["id"])
    if not billings or any(b["status"] not in ("PAID", "VOIDED") for b in billings):
        return
    if any(b["status"] != "SETTLED" for b in backcharges_of_job(job["id"])):
        return
    job["status"] = "COMPLETE"
    job["retainage_releasable_cents"] = retainage_held(job["id"])
    touch(job)
