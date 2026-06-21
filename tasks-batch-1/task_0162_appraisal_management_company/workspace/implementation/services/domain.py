"""Shared domain helpers: recompute computed fields, fee splits, rotation."""
import clock
import db
import errors
from services import calculations as calc

# Active assignment statuses (NOT in {DECLINED, CANCELLED, COMPLETED})
ACTIVE_ASSIGNMENT_STATUSES = {"OFFERED", "ACCEPTED", "REVISION"}


# ---------------------------------------------------------------------------
# Appraiser counters & panel score
# ---------------------------------------------------------------------------
def recompute_appraiser(appraiser):
    """Recompute active_assignment_count, completed_count, on_time_count,
    last_assigned_at, and panel_score from the appraiser's assignments."""
    aid = appraiser["id"]
    own = [a for a in db.assignments.values() if a.get("appraiser_id") == aid]

    active = [a for a in own if a["status"] in ACTIVE_ASSIGNMENT_STATUSES]
    completed = [a for a in own if a["status"] == "COMPLETED"]
    on_time = [
        a for a in completed
        if a.get("actual_turnaround_hours") is not None
        and a["actual_turnaround_hours"] <= a.get("sla_hours", 0)
    ]

    appraiser["active_assignment_count"] = len(active)
    appraiser["completed_count"] = len(completed)
    appraiser["on_time_count"] = len(on_time)

    # last_assigned_at = created_at of the most recent assignment this appraiser
    # accepted. "Accepted" assignments are those that have an accepted_at set.
    accepted = [a for a in own if a.get("accepted_at") is not None]
    if accepted:
        latest = max(accepted, key=lambda a: a["_created_dt"])
        appraiser["last_assigned_at"] = latest["created_at"]
        appraiser["_last_assigned_dt"] = latest["_created_dt"]
    else:
        appraiser["last_assigned_at"] = None
        appraiser["_last_assigned_dt"] = None

    appraiser["panel_score"] = calc.compute_panel_score(
        appraiser["status"],
        appraiser["completed_count"],
        appraiser["active_assignment_count"],
        appraiser["on_time_count"],
    )


def recompute_panel_score_only(appraiser):
    appraiser["panel_score"] = calc.compute_panel_score(
        appraiser["status"],
        appraiser["completed_count"],
        appraiser["active_assignment_count"],
        appraiser["on_time_count"],
    )


# ---------------------------------------------------------------------------
# Lender committed fee
# ---------------------------------------------------------------------------
def recompute_committed_fee(lender):
    """Sum order_fee_cents over this lender's non-CANCELLED orders whose
    placed_at falls in the current calendar month (UTC)."""
    lid = lender["id"]
    now = clock.now()
    total = 0
    for o in db.orders.values():
        if o.get("lender_id") != lid:
            continue
        if o["status"] == "CANCELLED":
            continue
        placed_dt = o.get("_placed_dt")
        if placed_dt is None:
            continue
        if placed_dt.year == now.year and placed_dt.month == now.month:
            total += o["order_fee_cents"]
    lender["committed_fee_cents"] = total


# ---------------------------------------------------------------------------
# Fee split
# ---------------------------------------------------------------------------
def fee_split_for_order(order_id):
    for fs in db.fee_splits.values():
        if fs.get("order_id") == order_id:
            return fs
    return None


def recompute_fee_split(order, fee_split, variant):
    """Recompute appraiser/amc/penalty for the order's accepted (or active)
    assignment, and set the variant."""
    appraiser, assignment = _scoring_assignment(order)
    revision_round = assignment["revision_round"] if assignment else 0
    if appraiser is None:
        # No appraiser assigned yet: provisional with base only requires the
        # appraiser's share; without an appraiser there is no base. This path
        # is only hit at placement before assignment, where the split is still
        # PROVISIONAL but no appraiser exists. Per PRD the FeeSplit is created
        # at placement; with no appraiser we leave a 0/order split until an
        # appraiser is known. In practice recompute is always called after an
        # appraiser exists for non-provisional variants.
        fee_split["appraiser_fee_cents"] = 0
        fee_split["amc_fee_cents"] = order["order_fee_cents"]
        fee_split["revision_penalty_cents"] = 0
        fee_split["variant"] = variant
        return

    appraiser_fee, amc_fee, penalty = calc.compute_fee_split(
        order["order_fee_cents"],
        appraiser["base_fee_share_pct"],
        order["rush"],
        revision_round,
    )
    fee_split["appraiser_fee_cents"] = appraiser_fee
    fee_split["amc_fee_cents"] = amc_fee
    fee_split["revision_penalty_cents"] = penalty
    fee_split["variant"] = variant


def _scoring_assignment(order):
    """Return (appraiser, assignment) for the order's operative assignment:
    the live one whose appraiser is doing the work. Prefers an accepted/
    revision/completed assignment (the worker), else the latest OFFERED one
    (so the PROVISIONAL split at assignment time knows the chosen appraiser)."""
    oid = order["id"]
    own = [a for a in db.assignments.values() if a.get("order_id") == oid]
    worked = [a for a in own if a["status"] in ("ACCEPTED", "REVISION", "COMPLETED")]
    if worked:
        assignment = max(worked, key=lambda a: a["_created_dt"])
    else:
        offered = [a for a in own if a["status"] == "OFFERED"]
        if not offered:
            return None, None
        assignment = max(offered, key=lambda a: a["_created_dt"])
    appraiser = db.appraisers.get(assignment.get("appraiser_id"))
    return appraiser, assignment


# ---------------------------------------------------------------------------
# Rotation selector (SCAFFOLD calculations.rotation_selector / PRD §3.2)
# ---------------------------------------------------------------------------
def select_appraiser(order, prop, lender):
    """Return the selected appraiser dict or raise ERR_NO_ELIGIBLE_APPRAISER."""
    oid = order["id"]
    panel = set(lender.get("approved_panel_appraiser_ids") or [])

    # appraisers already DECLINED on this order
    declined_ids = set()
    for a in db.assignments.values():
        if a.get("order_id") == oid and a["status"] == "DECLINED":
            declined_ids.add(a.get("appraiser_id"))

    candidates = []
    for ap in db.appraisers.values():
        if ap["status"] != "ACTIVE":
            continue
        if ap["license_state"] != prop["state_code"]:
            continue
        if ap["id"] not in panel:
            continue
        if ap["id"] in declined_ids:
            continue
        if ap["active_assignment_count"] >= calc.MAX_ACTIVE_LOAD:
            continue
        candidates.append(ap)

    if not candidates:
        raise errors.err(errors.ERR_NO_ELIGIBLE_APPRAISER,
                         "No eligible appraiser for this order.")

    # Ranking: panel_score DESC, active_assignment_count ASC,
    # last_assigned_at ASC NULLS FIRST, created_at ASC. Never id.
    import datetime as _dt
    EPOCH = _dt.datetime(1, 1, 1, tzinfo=_dt.timezone.utc)

    def sort_key(ap):
        last = ap.get("_last_assigned_dt")
        # nulls first => use a sentinel earlier than any real datetime
        last_key = (1, last) if last is not None else (0, EPOCH)
        return (
            -ap["panel_score"],
            ap["active_assignment_count"],
            last_key,
            ap["_created_dt"],
        )

    candidates.sort(key=sort_key)
    return candidates[0]
