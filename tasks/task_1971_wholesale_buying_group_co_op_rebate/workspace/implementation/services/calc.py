"""Calculation rules (PRD §2.6, §3; SCAFFOLD table 3).

All money is integer cents; all rates are basis points over 10,000; every
multiply-then-divide floors once to a whole cent (integer arithmetic only).
"""

from db import store, new_entity, touch

BPS_DENOMINATOR = 10000

# pass_through_split rates
PLATINUM_BPS = 8500
STANDARD_BPS = 7500
BUILDER_BPS = 6500
SPLIT_BPS = {"PLATINUM": PLATINUM_BPS, "STANDARD": STANDARD_BPS, "BUILDER": BUILDER_BPS}

# holdback_calculation constants
FLAT_HOLDBACK_BPS = 1000
RISK_HOLDBACK_BPS = 2500
MATERIAL_FINDING_THRESHOLD = 2

# Standing holdback lag: releases fire this many quarter-indexes after the
# quarter in which their source distribution is disbursed.
HOLDBACK_LAG_QUARTERS = 2

# Finding severity band: 0 < |delta| / self_report_cents <= 0.05 => MINOR.
MINOR_BAND_NUM = 5    # 5%
MINOR_BAND_DEN = 100


def resolve_tier(tier_schedule, eligible_qty):
    """Last tier with min_qty <= eligible_qty (inclusive). None qualifies =>
    synthetic tier {min_qty: 0, rate_bps: 0}."""
    applied_min_qty = 0
    applied_rate = 0
    for tier in tier_schedule:
        if eligible_qty >= tier["min_qty"]:
            applied_min_qty = tier["min_qty"]
            applied_rate = tier["rate_bps"]
        else:
            break
    return applied_min_qty, applied_rate


def rebate_for(eligible_qty, eligible_cents, tier_schedule):
    """rebate_tier_resolution: floor(eligible_cents * rate_bps / 10000)."""
    applied_min_qty, rate_bps = resolve_tier(tier_schedule, eligible_qty)
    rebate = (eligible_cents * rate_bps) // BPS_DENOMINATOR
    return rebate, applied_min_qty


def split_rebate(commitment_level, final_rebate_cents):
    """pass_through_split: pass = floor(final * rate / 10000);
    retained = final - pass (exact complement, no cent drift)."""
    rate = SPLIT_BPS[commitment_level]
    pass_through = (final_rebate_cents * rate) // BPS_DENOMINATOR
    retained = final_rebate_cents - pass_through
    return pass_through, retained


def finding_severity(self_report_cents, audited_cents):
    """NONE if equal; MINOR if 0 < |delta|/self_report_cents <= 5%;
    MATERIAL otherwise. Integer cross-multiplication, no floats."""
    if audited_cents == self_report_cents:
        return "NONE"
    if self_report_cents == 0:
        return "MATERIAL"
    delta = abs(audited_cents - self_report_cents)
    if delta * MINOR_BAND_DEN <= self_report_cents * MINOR_BAND_NUM:
        return "MINOR"
    return "MATERIAL"


def enrollment_of(report_or_accrual):
    return store.enrollments[report_or_accrual["enrollment_id"]]


def program_of_enrollment(enrollment):
    return store.programs[enrollment["program_id"]]


def member_of_enrollment(enrollment):
    return store.members[enrollment["member_id"]]


def live_reports(enrollment_id, quarter_index):
    """Reports carrying live figures: SUPERSEDED rows are dead history."""
    return [r for r in store.reports.values()
            if r["enrollment_id"] == enrollment_id
            and r["quarter_index"] == quarter_index
            and r["status"] != "SUPERSEDED"]


def effective_qty_cents(reports):
    """Final-variant evidence: audited figures where resolved, else self-reported."""
    qty = 0
    cents = 0
    for r in reports:
        if r["status"] == "ADJUDICATED" and r["audited_qty"] is not None:
            qty += r["audited_qty"]
            cents += r["audited_cents"]
        else:
            qty += r["self_report_qty"]
            cents += r["self_report_cents"]
    return qty, cents


def self_reported_qty_cents(reports):
    """Provisional-variant evidence: self-reported figures."""
    qty = sum(r["self_report_qty"] for r in reports)
    cents = sum(r["self_report_cents"] for r in reports)
    return qty, cents


def find_accrual(enrollment_id, quarter_index):
    for a in store.accruals.values():
        if a["enrollment_id"] == enrollment_id and a["quarter_index"] == quarter_index:
            return a
    return None


def get_or_create_accrual(enrollment_id, quarter_index):
    accrual = find_accrual(enrollment_id, quarter_index)
    if accrual is not None:
        return accrual, False
    accrual = new_entity()
    accrual.update({
        "enrollment_id": enrollment_id,
        "quarter_index": quarter_index,
        "provisional_rebate_cents": 0,
        "final_rebate_cents": 0,
        "tier_applied_min_qty": 0,
        "pass_through_cents": 0,
        "retained_cents": 0,
        "status": "OPEN",
    })
    store.accruals[accrual["id"]] = accrual
    return accrual, True


def recompute_provisional(accrual, bump_version=True):
    enrollment = enrollment_of(accrual)
    program = program_of_enrollment(enrollment)
    reports = live_reports(accrual["enrollment_id"], accrual["quarter_index"])
    qty, cents = self_reported_qty_cents(reports)
    rebate, applied = rebate_for(qty, cents, program["tier_schedule"])
    accrual["provisional_rebate_cents"] = rebate
    accrual["tier_applied_min_qty"] = applied
    if bump_version:
        touch(accrual)


def recompute_final(accrual):
    """Final variant of rebate_tier_resolution over live reports.
    Returns (new_final, applied_min_qty)."""
    enrollment = enrollment_of(accrual)
    program = program_of_enrollment(enrollment)
    reports = live_reports(accrual["enrollment_id"], accrual["quarter_index"])
    qty, cents = effective_qty_cents(reports)
    return rebate_for(qty, cents, program["tier_schedule"])


def member_distributed_accruals(member_id):
    out = []
    for a in store.accruals.values():
        if a["status"] != "DISTRIBUTED":
            continue
        enr = store.enrollments.get(a["enrollment_id"])
        if enr is not None and enr["member_id"] == member_id:
            out.append(a)
    return out


def create_clawback_case(member_id, trigger_reason):
    """clawback_amount waterfall (PRD §3.7), order load-bearing:
    1) gross = sum of pass_through_cents over the member's DISTRIBUTED accruals;
    2) forfeiture: member's SCHEDULED HoldbackReleases -> FORFEITED, summed;
    3) net = max(0, gross - forfeited). Forfeiture precedes netting."""
    compute_set = member_distributed_accruals(member_id)
    gross = sum(a["pass_through_cents"] for a in compute_set)
    forfeited = 0
    for h in store.holdbacks.values():
        if h["member_id"] == member_id and h["status"] == "SCHEDULED":
            h["status"] = "FORFEITED"
            touch(h)
            forfeited += h["release_cents"]
    net = gross - forfeited
    if net < 0:
        net = 0
    coop = store.coop
    case = new_entity()
    case.update({
        "member_id": member_id,
        "trigger_reason": trigger_reason,
        "trigger_quarter_index": coop["current_quarter_index"] if coop else 0,
        "gross_clawback_cents": gross,
        "net_clawback_cents": net,
        "recovered_cents": 0,
        "dispute_note": "",
        "status": "OPEN",
        "_compute_set": [a["id"] for a in compute_set],
    })
    store.clawbacks[case["id"]] = case
    return case
