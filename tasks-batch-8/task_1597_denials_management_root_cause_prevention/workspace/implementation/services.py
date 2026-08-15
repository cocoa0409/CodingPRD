"""Business services: record factory, derived-field recomputation, the
calculation library (PRD section 3 / scaffold section 1.3), cascades, the
expiry sweep, recurrence sweep, and the append-only event trail.
"""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction

from db import new_id, next_seq, store
from errors import (
    ApiError,
    ERR_APPEAL_NOT_FOUND,
    ERR_DENIAL_NOT_FOUND,
    ERR_NOT_FOUND,
    ERR_PAYER_NOT_FOUND,
)
from util import now_iso, parse_date, today

# ---------------------------------------------------------------------------
# Constants (scaffold calculations.constants)
# ---------------------------------------------------------------------------

MAX_APPEAL_LEVEL = 3
MANAGER_APPROVAL_LIMIT_CENTS = 2500000
WRITE_OFF_CEILING_CENTS = 10000000
STANDARD_TIER_MULTIPLIER = Fraction(1, 1)
ESCALATED_TIER_MULTIPLIER = Fraction(3, 4)
APPEAL_COST_CENTS = 5000
MONITORING_DAYS = 90
AUTO_TASK_DUE_DAYS = 14
DEFAULT_RESPONSE_WINDOW_DAYS = 30
OVERTURN_RATE_FLOOR = Fraction(3, 10)  # 0.30, strict less-than
MIN_SAMPLE = 3
DEFAULT_OVERTURN_RATE = Fraction(1, 2)  # 0.50

DOLLAR_POINT_DIVISOR_CENTS = 10000
DOLLAR_COMPONENT_CAP = 50
DEADLINE_HORIZON_DAYS = 30
DEADLINE_COMPONENT_CAP = Decimal("45")
DEADLINE_DAILY_STEP = Decimal("1.5")
LEVEL_BOOST_PER_LEVEL = 5
LEVEL_BOOST_CAP_LEVELS = 2
BUCKET_CRITICAL = Decimal("70.00")
BUCKET_HIGH = Decimal("50.00")
BUCKET_MEDIUM = Decimal("25.00")

OUTCOME_STATES = ("OVERTURNED", "PARTIALLY_OVERTURNED", "UPHELD")
ACTIVE_APPEAL_STATES = ("DRAFT", "LETTER_GENERATED", "SUBMITTED")
OPEN_TASK_STATES = ("OPEN", "ACKNOWLEDGED", "FIX_IMPLEMENTED", "REOPENED")
WORKABLE_DENIAL_STATES = ("QUEUED", "IN_APPEAL")
PENDING_WRITEOFF_STATES = ("PENDING_MANAGER", "ESCALATED_DIRECTOR")

TWO_DP = Decimal("0.01")


# ---------------------------------------------------------------------------
# Record plumbing
# ---------------------------------------------------------------------------


def make_record(fields):
    rec = dict(fields)
    rec["id"] = new_id()
    rec["created_at"] = now_iso()
    rec["updated_at"] = rec["created_at"]
    rec["version"] = 1
    rec["_seq"] = next_seq()
    return rec


def touch(rec):
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 1) + 1


def public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def emit_event(denial_case_id, event_type, actor_role, actor_user_id, detail):
    ev = {
        "id": new_id(),
        "denial_case_id": denial_case_id,
        "event_type": event_type,
        "actor_role": actor_role,
        "actor_user_id": actor_user_id,
        "detail": detail,
        "created_at": now_iso(),
        "_seq": next_seq(),
    }
    store.events[ev["id"]] = ev
    return ev


# ---------------------------------------------------------------------------
# Reference resolution (PRD section 2.8 gate 4)
# ---------------------------------------------------------------------------


def find_payer(payer_id):
    payer = store.payers.get(payer_id)
    if payer is None:
        raise ApiError(ERR_PAYER_NOT_FOUND, 404, "Payer %s does not exist" % payer_id)
    return payer


def find_denial(denial_id):
    denial = store.denials.get(denial_id)
    if denial is None:
        raise ApiError(ERR_DENIAL_NOT_FOUND, 404, "Denial %s does not exist" % denial_id)
    return denial


def find_appeal(appeal_id):
    appeal = store.appeals.get(appeal_id)
    if appeal is None:
        raise ApiError(ERR_APPEAL_NOT_FOUND, 404, "Appeal %s does not exist" % appeal_id)
    return appeal


def find_policy(policy_id):
    policy = store.policies.get(policy_id)
    if policy is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Policy %s does not exist" % policy_id)
    return policy


def find_remittance_code(code_id):
    code = store.remittance_codes.get(code_id)
    if code is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Remittance code %s does not exist" % code_id)
    return code


def find_attachment(attachment_id):
    att = store.attachments.get(attachment_id)
    if att is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Attachment %s does not exist" % attachment_id)
    return att


def find_task(task_id):
    task = store.tasks.get(task_id)
    if task is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Root-cause task %s does not exist" % task_id)
    return task


def find_writeoff(wo_id):
    wo = store.writeoffs.get(wo_id)
    if wo is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Write-off request %s does not exist" % wo_id)
    return wo


def find_scorecard(sc_id):
    sc = store.scorecards.get(sc_id)
    if sc is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Scorecard %s does not exist" % sc_id)
    return sc


def find_program(program_id):
    prog = store.programs.get(program_id)
    if prog is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Prevention program %s does not exist" % program_id)
    return prog


def find_event(event_id):
    ev = store.events.get(event_id)
    if ev is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Denial event %s does not exist" % event_id)
    return ev


# ---------------------------------------------------------------------------
# Appeal deadline schedule (calculations.appeal_deadline_schedule)
# ---------------------------------------------------------------------------


def effective_policy(payer_id, level_number, anchor_date):
    """The policy for (payer, level) whose half-open window contains anchor."""
    for pol in store.policies.values():
        if pol["payer_id"] != payer_id or pol["level_number"] != level_number:
            continue
        start = parse_date(pol["effective_from"])
        end = parse_date(pol["effective_to"]) if pol.get("effective_to") else None
        if start <= anchor_date and (end is None or anchor_date < end):
            return pol
    return None


def level1_deadline(payer, remittance_received_date_str):
    """Level-1 filing deadline: remittance date + effective level-1 policy days,
    falling back to the payer default."""
    anchor = parse_date(remittance_received_date_str)
    pol = effective_policy(payer["id"], 1, anchor)
    days = pol["timely_filing_days"] if pol else payer["default_timely_filing_days"]
    return (anchor + timedelta(days=days)).isoformat()


def next_level_deadline(payer_id, next_level, anchor_date):
    """Deadline for level N>=2: anchor + effective policy days, or None when no
    policy covers that level at the anchor date."""
    pol = effective_policy(payer_id, next_level, anchor_date)
    if pol is None:
        return None
    return (anchor_date + timedelta(days=pol["timely_filing_days"])).isoformat()


# ---------------------------------------------------------------------------
# Queue priority score (calculations.queue_priority_score)
# ---------------------------------------------------------------------------


def compute_priority(denial):
    """Return (priority_score, queue_bucket). Non-workable -> (0.00, LOW)."""
    if denial["status"] not in WORKABLE_DENIAL_STATES:
        return 0.0, "LOW"
    deadline = denial.get("next_appeal_deadline")
    if deadline:
        days_remaining = (parse_date(deadline) - today()).days
    else:
        days_remaining = 0
    if days_remaining < 0:
        days_remaining = 0
    dollar = min(
        Decimal(denial["open_balance_cents"]) / Decimal(DOLLAR_POINT_DIVISOR_CENTS),
        Decimal(DOLLAR_COMPONENT_CAP),
    )
    if days_remaining > DEADLINE_HORIZON_DAYS:
        deadline_component = Decimal("0")
    else:
        deadline_component = DEADLINE_COMPONENT_CAP - DEADLINE_DAILY_STEP * days_remaining
        if deadline_component < 0:
            deadline_component = Decimal("0")
    level_boost = LEVEL_BOOST_PER_LEVEL * min(
        denial["current_appeal_level"], LEVEL_BOOST_CAP_LEVELS
    )
    raw = dollar + deadline_component + Decimal(level_boost)
    score_dec = raw.quantize(TWO_DP, rounding=ROUND_HALF_UP)
    if score_dec >= BUCKET_CRITICAL:
        bucket = "CRITICAL"
    elif score_dec >= BUCKET_HIGH:
        bucket = "HIGH"
    elif score_dec >= BUCKET_MEDIUM:
        bucket = "MEDIUM"
    else:
        bucket = "LOW"
    return float(score_dec), bucket


def recompute_priority(denial):
    """Recompute priority_score/queue_bucket. Returns True when values changed."""
    score, bucket = compute_priority(denial)
    if denial["priority_score"] != score or denial["queue_bucket"] != bucket:
        denial["priority_score"] = score
        denial["queue_bucket"] = bucket
        return True
    return False


# ---------------------------------------------------------------------------
# Trailing overturn rates (calculations.expected_recovery_value rate ladder
# and calculations.payer_trailing_overturn_rate)
# ---------------------------------------------------------------------------


def _rate_pair(appeals):
    """(numerator, denominator) so that rate = numerator/denominator exactly:
    numerator = 2*overturned + partial, denominator = 2*resolved."""
    overturned = sum(1 for a in appeals if a["status"] == "OVERTURNED")
    partial = sum(1 for a in appeals if a["status"] == "PARTIALLY_OVERTURNED")
    resolved = len(appeals)
    return 2 * overturned + partial, 2 * resolved


def _payer_outcome_appeals(payer_id, level=None):
    out = []
    for a in store.appeals.values():
        if a["status"] not in OUTCOME_STATES:
            continue
        denial = store.denials.get(a["denial_case_id"])
        if denial is None or denial["payer_id"] != payer_id:
            continue
        if level is not None and a["level_number"] != level:
            continue
        out.append(a)
    return out


def rate_for(payer_id, level):
    """Exact trailing overturn rate at a level with the deterministic fallback
    ladder: level -> payer-wide -> 0.50."""
    num, den = _rate_pair(_payer_outcome_appeals(payer_id, level))
    if den > 0:
        return Fraction(num, den)
    num, den = _rate_pair(_payer_outcome_appeals(payer_id, None))
    if den > 0:
        return Fraction(num, den)
    return DEFAULT_OVERTURN_RATE


def recompute_payer_review_flag(payer_id):
    payer = store.payers.get(payer_id)
    if payer is None:
        return
    num, den = _rate_pair(_payer_outcome_appeals(payer_id, None))
    resolved = den // 2
    if resolved >= MIN_SAMPLE:
        flag = Fraction(num, den) < OVERTURN_RATE_FLOOR
        if payer["appeal_policy_review_required"] != flag:
            payer["appeal_policy_review_required"] = flag
            touch(payer)


# ---------------------------------------------------------------------------
# Recovery projection (calculations.expected_recovery_value)
# ---------------------------------------------------------------------------


def recovery_projection(denial, variant):
    open_balance = denial["open_balance_cents"]
    next_level = denial["current_appeal_level"] + 1
    remaining_levels = MAX_APPEAL_LEVEL - denial["current_appeal_level"]
    rate = rate_for(denial["payer_id"], next_level)
    product = Decimal(open_balance * rate.numerator) / Decimal(rate.denominator)
    gross = int(product.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if variant == "net":
        expected = max(0, gross - APPEAL_COST_CENTS * remaining_levels)
    else:
        expected = gross
    return {
        "variant": variant,
        "expected_recovery_cents": expected,
        "rate_applied": float(rate),
        "remaining_levels": remaining_levels,
    }


# ---------------------------------------------------------------------------
# Write-off economics (calculations.writeoff_net_exposure)
# ---------------------------------------------------------------------------


def writeoff_economics(denial, requested_amount_cents):
    """Pinned evaluation order: gross -> tier (keyed on gross) -> tier
    multiplier -> rate at next level -> projected -> recommended."""
    gross = requested_amount_cents
    tier = "STANDARD" if gross <= MANAGER_APPROVAL_LIMIT_CENTS else "ESCALATED"
    multiplier = (
        STANDARD_TIER_MULTIPLIER if tier == "STANDARD" else ESCALATED_TIER_MULTIPLIER
    )
    rate = rate_for(denial["payer_id"], denial["current_appeal_level"] + 1)
    product_num = gross * rate.numerator * multiplier.numerator
    product_den = rate.denominator * multiplier.denominator
    product = Decimal(product_num) / Decimal(product_den)
    projected = int(product.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    recommended = gross - projected
    return tier, projected, recommended


def initial_writeoff_status(tier):
    return "PENDING_MANAGER" if tier == "STANDARD" else "ESCALATED_DIRECTOR"


def create_writeoff_record(denial, requested_amount_cents, reason_code, requester_id,
                           actor_role):
    """Shared by POST /rcm/write-off-requests and the expiry sweep. Assumes the
    amount gates have already been checked by the caller when applicable."""
    tier, projected, recommended = writeoff_economics(denial, requested_amount_cents)
    wo = make_record(
        {
            "denial_case_id": denial["id"],
            "requested_amount_cents": requested_amount_cents,
            "reason_code": reason_code,
            "requested_by_user_id": requester_id,
            "status": initial_writeoff_status(tier),
            "approval_tier": tier,
            "projected_recovery_cents": projected,
            "recommended_writeoff_cents": recommended,
            "decided_by_user_id": None,
            "decided_at": None,
            "denial_status_before": None,
            "decision_reason": "",
        }
    )
    store.writeoffs[wo["id"]] = wo
    emit_event(
        denial["id"],
        "WRITE_OFF_REQUESTED",
        actor_role,
        requester_id,
        "write_off_request_id=%s;requested_amount_cents=%d;approval_tier=%s;status=%s"
        % (wo["id"], requested_amount_cents, tier, wo["status"]),
    )
    return wo


def has_pending_writeoff(denial_id):
    return any(
        w["denial_case_id"] == denial_id and w["status"] in PENDING_WRITEOFF_STATES
        for w in store.writeoffs.values()
    )


# ---------------------------------------------------------------------------
# Scorecard helpers
# ---------------------------------------------------------------------------


def matching_scorecard(department, on_date):
    """The earliest-created OPEN scorecard for the department whose half-open
    period contains the date; None when no scorecard covers it."""
    if department is None:
        return None
    best = None
    for sc in store.scorecards.values():
        if sc["department"] != department or sc["status"] != "OPEN":
            continue
        start = parse_date(sc["period_start_date"])
        end = parse_date(sc["period_end_date"])
        if start <= on_date < end:
            if best is None or (sc["created_at"], sc["_seq"]) < (
                best["created_at"],
                best["_seq"],
            ):
                best = sc
    return best


def bump_scorecard(sc, **deltas):
    for key, delta in deltas.items():
        sc[key] = sc.get(key, 0) + delta
    touch(sc)


# ---------------------------------------------------------------------------
# Appeal letter (deterministic template)
# ---------------------------------------------------------------------------


def compose_letter(denial, appeal):
    types = sorted(
        a["document_type"]
        for a in store.attachments.values()
        if a["appeal_id"] == appeal["id"] and a["status"] == "ACTIVE"
    )
    lines = [
        "APPEAL LETTER",
        "claim_number=%s" % denial["claim_number"],
        "category=%s" % denial["category"],
        "level_number=%d" % appeal["level_number"],
        "denied_amount_cents=%d" % denial["denied_amount_cents"],
        "attachments=%s" % ",".join(types),
    ]
    return "\n".join(lines)
