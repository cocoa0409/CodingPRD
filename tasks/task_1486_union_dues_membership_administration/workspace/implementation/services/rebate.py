"""objector_rebate calculation (scaffold calculations[5]) — actual and
projected variants, plus per_capita_tax and election_eligibility helpers.

Rounding: per assessment line, agency_fee = round_half_up(assessed * pct / 100)
(exact integer round-half-up: (assessed * pct + 50) // 100 for non-negative
values), line_rebate = max(0, min(paid, assessed) - agency_fee); sum the
rounded lines — never sum-then-round.
"""
import db
import utils
from services import dues as dues_svc
from services import ledger as ledger_svc


def _line_rebate(assessed, paid, pct):
    agency_fee = (assessed * pct + 50) // 100
    line = min(paid, assessed) - agency_fee
    return line if line > 0 else 0


def actual_rebate(member, case, period_filter):
    """Sum line rebates over the member's FINAL assessments passing
    period_filter(period) with paid_cents > 0. Returns (rebate, periods)."""
    pct = case["chargeable_share_pct"]
    if pct is None:
        return 0, []
    _, _, paid, _ = ledger_svc.waterfall(member["id"])
    total = 0
    periods = []
    rows = [a for a in db.store.assessments.values()
            if a["member_id"] == member["id"] and a["status"] == "FINAL"]
    rows.sort(key=lambda a: (a["period"], a["_seq"]))
    for a in rows:
        if not period_filter(a["period"]):
            continue
        p = paid.get(a["id"], 0)
        if p <= 0:
            continue
        total += _line_rebate(a["assessed_cents"], p, pct)
        periods.append(a["period"])
    return total, periods


def issue_rebate_filter(case):
    """Actual variant (issue): period > last_rebated_period, or >= period of
    rate_set_at when never rebated."""
    last = case.get("last_rebated_period")
    if last:
        return lambda p: p > last
    rate_period = utils.parse_datetime(case["rate_set_at"])
    start = "%04d-%02d" % (rate_period.year, rate_period.month)
    return lambda p: p >= start


def projection(member, case):
    """Computed read: (actual_rebate_to_date_cents, projected_year_rebate_cents).

    actual_to_date: lifetime line-rebate sum over FINAL paid assessments with
    period <= current clock period, ignoring last_rebated_period.
    projected: actual_to_date + sum over each remaining calendar period of the
    current clock's calendar year after the latest FINAL assessment period of
    (floor_assessed - round_half_up(floor_assessed * pct / 100)).
    """
    pct = case["chargeable_share_pct"]
    if pct is None:
        return 0, 0
    cur_period = db.current_period()
    actual, _ = actual_rebate(member, case, lambda p: p <= cur_period)

    finals = [a for a in db.store.assessments.values()
              if a["member_id"] == member["id"] and a["status"] == "FINAL"]
    if finals:
        start = utils.period_add(max(a["period"] for a in finals), 1)
    else:
        start = cur_period
    year_end = "%04d-12" % db.now().year
    local, classification = dues_svc.member_config(member)
    floor = dues_svc.floor_dues(local, classification)
    per_period = floor - ((floor * pct + 50) // 100)

    projected = actual
    p = start
    while p <= year_end:
        projected += per_period
        p = utils.period_add(p, 1)
    return actual, projected


# ---------------------------------------------------------------------------
# per_capita_tax (scaffold calculations[6])
# ---------------------------------------------------------------------------

def per_capita_count(local, period):
    """Countable headcount for report (local, period).

    base = members with m.local_id == local  UNION  members with a COMPLETED
           transfer out of the local with effective_period > period.
    countable = base members in {ACTIVE, DELINQUENT}, classification not
                per_capita_exempt, without a COMPLETED transfer into the local
                with effective_period > period. Boundary: effective_period ==
                period counts at the target (condition is strict >).
    """
    out_ids = set()
    in_ids = set()
    for t in db.store.transfers.values():
        if t["status"] != "COMPLETED":
            continue
        if t["from_local_id"] == local["id"] and t["effective_period"] > period:
            out_ids.add(t["member_id"])
        if t["to_local_id"] == local["id"] and t["effective_period"] > period:
            in_ids.add(t["member_id"])

    base = [m for m in db.store.members.values()
            if m["local_id"] == local["id"] or m["id"] in out_ids]
    count = 0
    for m in base:
        if m["status"] not in ("ACTIVE", "DELINQUENT"):
            continue
        if m["id"] in in_ids:
            continue
        cls = db.store.classifications.get(m["classification_id"])
        if cls is not None and cls.get("per_capita_exempt"):
            continue
        count += 1
    return count


# ---------------------------------------------------------------------------
# election_eligibility (scaffold calculations[7])
# ---------------------------------------------------------------------------

def evaluate_eligibility(member, election):
    """Reasons in pinned order: NOT_ACTIVE, ARREARS_OUTSTANDING,
    INSUFFICIENT_STANDING_MONTHS. The standing window is inclusive at date
    granularity: suspension ended exactly required months before the cutoff
    date satisfies the requirement."""
    reasons = []
    if member["status"] != "ACTIVE":
        reasons.append("NOT_ACTIVE")
    arrears, _ = ledger_svc.balances(member["id"])
    if arrears != 0:
        reasons.append("ARREARS_OUTSTANDING")
    lse = member.get("last_suspension_ended_at")
    if lse is not None:
        ended = utils.parse_datetime(lse).date()
        cutoff = utils.parse_datetime(election["eligibility_cutoff_at"]).date()
        if utils.add_months(ended, election["required_good_standing_months"]) > cutoff:
            reasons.append("INSUFFICIENT_STANDING_MONTHS")
    return reasons, arrears
