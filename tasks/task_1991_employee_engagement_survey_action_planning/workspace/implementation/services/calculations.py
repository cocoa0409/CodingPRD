"""Calculation rules (SCAFFOLD §1.3 / PRD §3):

  - engagement_score          (weighted Likert scoring, 4dp products / 2dp means)
  - response_rate             (submitted + 0.5*partial over invited, 4dp)
  - eligibility_sampling      (tenure gate + pulse floor sampling)
  - minimum_n_suppression     (unit thresholds, strict <)
  - benchmark_percentile      (below + 0.5*ties over distribution, 2dp)
  - action_progress           (floor(100 * done / total))
  - attrition_risk_index      (provisional prior 0.08; final observed ratio)

All rounding is round-half-up. Money-like numerics use Decimal.
"""

from decimal import Decimal, ROUND_HALF_UP
import math

from db import db


DIMENSIONS = {"PURPOSE", "GROWTH", "MANAGER_SUPPORT", "BELONGING", "WORKLOAD", "RECOGNITION"}

TENURE_GATE_DAYS = 30
PARTIAL_WEIGHT = Decimal("0.5")
LOW_SCORE_FLOOR = Decimal("60.00")
RISK_COEFF = Decimal("1.75")
BASE_RATE_PRIOR = Decimal("0.08")
LIKERT_STEP = Decimal("25")


def _d(value):
    """Coerce an int/float/str to Decimal exactly (via repr for floats)."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value, dp):
    q = Decimal(1).scaleb(-dp)  # 10^-dp
    return _d(value).quantize(q, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# response_rate
# ---------------------------------------------------------------------------

def compute_response_rate(cycle_id):
    """Recompute invited/submitted/partial counters and response_rate.

    invited_count counts invites in {INVITED, REMINDED, SUBMITTED, PARTIAL};
    EXPIRED rows remain in the denominator once frozen — since invited_count is
    frozen at close and EXPIRED invites *were* invited, the denominator is the
    count of all invites ever created for the cycle that were in a live status
    pre-close. With invited_count frozen at close, we compute it as: all
    invites of the cycle (every invite row ever created was invited), because
    EXPIRED rows remain in the denominator. Before close, INVITED/REMINDED/
    SUBMITTED/PARTIAL are precisely the live invites, and no EXPIRED rows can
    exist (expiry only happens at close), so counting {INVITED, REMINDED,
    SUBMITTED, PARTIAL} equals counting all rows at all times.
    """
    invites = [iv for iv in db.survey_invites.values() if iv["cycle_id"] == cycle_id]
    invited_count = sum(1 for iv in invites
                        if iv["status"] in ("INVITED", "REMINDED", "SUBMITTED", "PARTIAL", "EXPIRED"))
    submitted_count = sum(1 for iv in invites if iv["status"] == "SUBMITTED")
    partial_count = sum(1 for iv in invites if iv["status"] == "PARTIAL")

    if invited_count == 0:
        rate = None
    else:
        rate = float(round_half_up(
            (Decimal(submitted_count) + PARTIAL_WEIGHT * Decimal(partial_count))
            / Decimal(invited_count), 4))
    return invited_count, submitted_count, partial_count, rate


# ---------------------------------------------------------------------------
# eligibility_sampling
# ---------------------------------------------------------------------------

def run_eligibility_sweep(cycle):
    """Create SurveyInvite rows for the eligible population per cycle kind."""
    from db import stamp_new, now_iso  # local import to avoid cycles

    opens_at = cycle["_opens_at"]
    tenure_cutoff = opens_at - __import__("datetime").timedelta(days=TENURE_GATE_DAYS)

    eligible = []
    for emp in db.employees.values():
        if emp["employment_status"] != "ACTIVE":
            continue
        if emp["_hired_at"] <= tenure_cutoff:
            eligible.append(emp)

    if cycle["cycle_kind"] == "PULSE":
        target = math.floor(len(eligible) * _d(cycle["sampling_ratio"]))
        eligible.sort(key=lambda e: (e["_hired_at"], e["_created_seq"]))
        eligible = eligible[:int(target)]
    # CENSUS: invite the entire eligible population; sampling_ratio ignored.

    created = []
    for emp in eligible:
        invite = stamp_new({
            "cycle_id": cycle["id"],
            "employee_id": emp["id"],
            "unit_id_at_invite": emp["unit_id"],
            "status": "INVITED",
            "reminder_count": 0,
            "last_reminded_at": None,
            "submitted_at": None,
        })
        db.survey_invites[invite["id"]] = invite
        created.append(invite)
    return created


# ---------------------------------------------------------------------------
# engagement_score + minimum_n_suppression + benchmark_percentile
# ---------------------------------------------------------------------------

def _subtree_unit_ids(unit_id):
    """Return the set of unit ids: unit_id plus all descendant units."""
    result = {unit_id}
    changed = True
    while changed:
        changed = False
        for unit in db.org_units.values():
            pid = unit.get("parent_unit_id")
            if pid in result and unit["id"] not in result:
                result.add(unit["id"])
                changed = True
    return result


def scope_unit_ids(snapshot):
    if snapshot["scope"] == "DIRECT":
        return {snapshot["unit_id"]}
    return _subtree_unit_ids(snapshot["unit_id"])


def compute_snapshot_fields(snapshot):
    """Compute submitted_n, dimension_scores, overall_score, suppression flags
    and benchmark_percentile for a snapshot. Returns a dict of computed fields.
    """
    cycle = db.survey_cycles[snapshot["cycle_id"]]
    unit = db.org_units[snapshot["unit_id"]]
    unit_ids = scope_unit_ids(snapshot)

    cycle_items = [ci for ci in db.cycle_items.values() if ci["cycle_id"] == cycle["id"]]
    cycle_item_by_id = {ci["id"]: ci for ci in cycle_items}
    item_by_id = {ci["item_id"]: db.survey_items.get(ci["item_id"]) for ci in cycle_items}

    # Effective weights: PULSE treats every pinned weight as 1.0.
    pulse = cycle["cycle_kind"] == "PULSE"

    def eff_weight(ci):
        return Decimal("1.0") if pulse else _d(ci["pinned_weight"])

    # Submitted invites attributed to this scope via unit_id_at_invite.
    submitted = [iv for iv in db.survey_invites.values()
                 if iv["cycle_id"] == cycle["id"]
                 and iv["status"] == "SUBMITTED"
                 and iv["unit_id_at_invite"] in unit_ids]
    submitted_n = len(submitted)

    # Per-answer weighted products at 4dp.
    dim_product_sum = {}   # dimension -> Decimal sum of 4dp products
    dim_weight_sum = {}    # dimension -> Decimal weight-per-respondent * n
    total_product_sum = Decimal("0")
    total_weight_sum = Decimal("0")

    # Weight denominators are counted once per submitted respondent.
    for ci in cycle_items:
        item = item_by_id[ci["item_id"]]
        dim = item["dimension"] if item else None
        w = eff_weight(ci) * Decimal(submitted_n)
        total_weight_sum += eff_weight(ci) * Decimal(submitted_n)
        if dim is not None:
            dim_weight_sum[dim] = dim_weight_sum.get(dim, Decimal("0")) + w

    for iv in submitted:
        resp_id = db.responses_by_invite.get(iv["id"])
        if resp_id is None:
            continue
        resp = db.survey_responses.get(resp_id)
        if resp is None:
            continue
        for ans in resp["answers"]:
            ci = cycle_item_by_id.get(ans["cycle_item_id"])
            if ci is None:
                continue
            item = item_by_id.get(ci["item_id"])
            if item is None:
                continue
            scaled = (Decimal(int(ans["score"])) - Decimal(1)) * LIKERT_STEP
            product = round_half_up(scaled * eff_weight(ci), 4)
            total_product_sum += product
            dim = item["dimension"]
            dim_product_sum[dim] = dim_product_sum.get(dim, Decimal("0")) + product

    dimension_scores = {}
    for dim in sorted(dim_product_sum.keys()):
        if dim_weight_sum.get(dim, Decimal("0")) > 0:
            dimension_scores[dim] = float(
                round_half_up(dim_product_sum[dim] / dim_weight_sum[dim], 2))

    overall_score = None
    if total_weight_sum > 0:
        overall_score = float(round_half_up(total_product_sum / total_weight_sum, 2))

    # Suppression thresholds: the unit override always wins.
    eff_min_n = unit["min_n_threshold"]
    eff_verbatim_n = unit["verbatim_n_threshold"]
    numeric_suppressed = submitted_n < eff_min_n
    verbatim_suppressed = submitted_n < eff_verbatim_n

    if numeric_suppressed:
        dimension_scores = {}
        overall_score = None

    # Benchmark percentile vs the ACTIVE benchmark set, when linked.
    benchmark_percentile = None
    if not numeric_suppressed and overall_score is not None:
        active_sets = [bs for bs in db.benchmark_sets.values() if bs["status"] == "ACTIVE"]
        if active_sets:
            bs = sorted(active_sets, key=lambda b: b["_created_seq"])[0]
            dist = bs["dimension_scores"]
            below = sum(1 for v in dist if _d(v) < _d(overall_score))
            ties = sum(1 for v in dist if _d(v) == _d(overall_score))
            benchmark_percentile = float(round_half_up(
                (Decimal(below) + Decimal("0.5") * Decimal(ties))
                / Decimal(len(dist)) * Decimal(100), 2))

    return {
        "submitted_n": submitted_n,
        "dimension_scores": dimension_scores,
        "overall_score": overall_score,
        "benchmark_percentile": benchmark_percentile,
        "numeric_suppressed": numeric_suppressed,
        "verbatim_suppressed": verbatim_suppressed,
    }


# ---------------------------------------------------------------------------
# action_progress
# ---------------------------------------------------------------------------

def compute_progress_pct(plan_id):
    items = [ai for ai in db.action_items.values() if ai["plan_id"] == plan_id]
    done = sum(1 for ai in items if ai["status"] == "DONE")
    dropped = sum(1 for ai in items if ai["status"] == "DROPPED")
    open_ = sum(1 for ai in items if ai["status"] == "OPEN")
    total = done + dropped + open_
    if total == 0:
        return 0
    return int(math.floor(100 * done / total))


# ---------------------------------------------------------------------------
# attrition_risk_index
# ---------------------------------------------------------------------------

def compute_attrition_risk(cycle, provisional):
    """provisional=True uses BASE_RATE_PRIOR; otherwise the observed ratio.

    The engagement modifier uses the cycle's snapshot overall scores: low
    engagement when the snapshot overall_score is below the 60.00 floor. When
    no snapshot exists or all are suppressed, low_engagement is false.
    """
    if provisional:
        base_rate = BASE_RATE_PRIOR
    else:
        linkages = [ol for ol in db.outcome_linkages.values()
                    if ol["cycle_id"] == cycle["id"]
                    and ol["outcome_kind"] == "ATTRITION"]
        attrited = sum(1 for ol in linkages
                       if ol["outcome_value"] in ("VOLUNTARY", "INVOLUNTARY"))
        submitted_count = sum(1 for iv in db.survey_invites.values()
                              if iv["cycle_id"] == cycle["id"]
                              and iv["status"] == "SUBMITTED")
        if submitted_count == 0:
            return None
        base_rate = Decimal(attrited) / Decimal(submitted_count)

    # Low-engagement test across this cycle's snapshots.
    low_engagement = False
    for snap in db.report_snapshots.values():
        if snap["cycle_id"] != cycle["id"]:
            continue
        score = snap.get("overall_score")
        if score is not None and _d(score) < LOW_SCORE_FLOOR:
            low_engagement = True
            break

    multiplier = Decimal(1) + (RISK_COEFF if low_engagement else Decimal(0))
    return float(round_half_up(base_rate * multiplier, 4))
