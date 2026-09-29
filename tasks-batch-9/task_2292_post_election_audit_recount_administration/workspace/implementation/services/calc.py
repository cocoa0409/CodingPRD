"""The nine calculation rules (PRD section 3, SCAFFOLD calculations)."""

from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------

ALPHA_FACTOR = {
    Decimal("0.10"): Decimal("2.303"),
    Decimal("0.05"): Decimal("2.996"),
    Decimal("0.01"): Decimal("4.605"),
}
ALLOWED_ALPHAS = (Decimal("0.10"), Decimal("0.05"), Decimal("0.01"))
GAMMA = Decimal("1.2")
MIN_SAMPLE_BATCHES = 2
ESCALATION_MULTIPLIER = Decimal("2.0")

AUTOMATIC_THRESHOLD_CANDIDATE = Decimal("0.5000")
AUTOMATIC_THRESHOLD_MEASURE = Decimal("0.2500")
RECOUNT_REQUEST_MARGIN_CEILING_PCT = Decimal("10.0000")
RECOUNT_REQUEST_WINDOW_DAYS = 5

FULL_CONTEST_RATE_CENTS = 25
PARTIAL_BATCH_RATE_CENTS = 40
DEPOSIT_BASE_CENTS = 50000
DEPOSIT_FLOOR_CENTS = 100000
DEPOSIT_CAP_CENTS = 2000000
BALLOT_COST_CENTS_PER_BALLOT = Decimal("12.5")
LABOR_COST_CENTS_PER_HOUR = Decimal("4800")
WITHDRAWAL_RETENTION_RATE = Decimal("0.25")
STATUTORY_MARGIN_SHIFT_VOTES = 100

NET_MARGIN_SHIFT_THRESHOLD = Decimal("0.0050")
MAX_RELATIVE_OVERSTATEMENT_THRESHOLD = Decimal("1.0000")

HAND_COUNT_HOURS_PER_1000 = 6
ROUND_OVERHEAD_HOURS = 48
AT_RISK_SLACK_HOURS = Decimal("72")
MAX_EXTENSION_DAYS = 5

RESEAL_BUFFER_MINUTES = 30
OBSERVER_ROOM_CAPACITY = 2
MAX_TALLY_REOPENS = 2
MAX_INTERPRETATION_LIMIT = None
BOARD_QUORUM_MIN_VOTES = 3

LCG_MULTIPLIER = 1103515245
LCG_INCREMENT = 12345
LCG_MODULUS = 2147483648
ROUND_SEED_STRIDE = 7919


# ---------------------------------------------------------------------------
# primitives
# ---------------------------------------------------------------------------


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rhu(value, places):
    quantum = Decimal(1).scaleb(-places)
    return dec(value).quantize(quantum, rounding=ROUND_HALF_UP)


def ceil_int(value):
    return int(dec(value).to_integral_value(rounding=ROUND_CEILING))


def fnum(value):
    if value is None:
        return None
    return float(value)


# ---------------------------------------------------------------------------
# 1. contest_margin_canvass
# ---------------------------------------------------------------------------


def rank_candidates(candidate_names, votes):
    """Rank by vote count descending, then candidate name ascending."""
    return sorted(candidate_names, key=lambda name: (-int(votes.get(name, 0)), name))


def contest_margin(candidate_names, votes, ballots_cast):
    ranked = rank_candidates(candidate_names, votes)
    winner = ranked[0] if ranked else None
    runner_up = ranked[1] if len(ranked) > 1 else None
    winner_votes = int(votes.get(winner, 0)) if winner else 0
    runner_votes = int(votes.get(runner_up, 0)) if runner_up else 0
    margin_votes = winner_votes - runner_votes
    margin_pct = rhu(dec(margin_votes) / dec(ballots_cast) * Decimal(100), 4)
    return {
        "winner_name": winner,
        "runner_up_name": runner_up,
        "margin_votes": margin_votes,
        "margin_pct": margin_pct,
    }


# ---------------------------------------------------------------------------
# 2. recount_trigger_evaluation
# ---------------------------------------------------------------------------


def automatic_threshold_pct(contest_type):
    if contest_type == "CANDIDATE":
        return AUTOMATIC_THRESHOLD_CANDIDATE
    return AUTOMATIC_THRESHOLD_MEASURE


def automatic_recount_required(contest_type, margin_pct):
    if margin_pct is None:
        return False
    return dec(margin_pct) <= automatic_threshold_pct(contest_type)


def margin_recount_eligible(margin_pct):
    if margin_pct is None:
        return False
    return dec(margin_pct) <= RECOUNT_REQUEST_MARGIN_CEILING_PCT


# ---------------------------------------------------------------------------
# 3. audit_sample_size
# ---------------------------------------------------------------------------


def planned_sample_size(audit, margin_votes, ballots_cast, total_batches):
    if margin_votes is None or ballots_cast in (None, 0):
        return None
    if total_batches <= 0:
        return 0

    audit_type = audit["audit_type"]
    if audit_type == "FIXED_PERCENTAGE":
        pct = dec(audit["fixed_percentage_pct"])
        raw_batches = ceil_int(dec(total_batches) * pct / Decimal(100))
    else:
        margin_fraction = dec(margin_votes) / dec(ballots_cast)
        avg_batch = ceil_int(dec(ballots_cast) / dec(total_batches))
        if margin_fraction <= 0 or avg_batch <= 0:
            raw_batches = total_batches
        else:
            alpha = _alpha_factor(audit["risk_limit_alpha"])
            if audit_type == "RISK_LIMITING":
                raw_ballots = ceil_int(
                    Decimal(2) * alpha / (margin_fraction * margin_fraction)
                )
            else:  # COMPARISON
                prior = dec(audit.get("prior_error_rate") or 0)
                raw_ballots = ceil_int(
                    alpha * (Decimal(1) + prior) / (GAMMA * margin_fraction)
                )
            raw_batches = ceil_int(dec(raw_ballots) / dec(avg_batch))
    return min(total_batches, max(MIN_SAMPLE_BATCHES, raw_batches))


def _alpha_factor(alpha):
    key = dec(alpha).quantize(Decimal("0.01"))
    return ALPHA_FACTOR[key]


def escalation_target(planned):
    if planned is None:
        return 0
    return ceil_int(dec(planned) * ESCALATION_MULTIPLIER)


# ---------------------------------------------------------------------------
# 4. batch_selection_sequence
# ---------------------------------------------------------------------------


def draw_batches(pool, random_seed, round_number, sample_size):
    """Deterministic LCG draw without replacement.

    ``pool`` must already be ordered by batch_label ascending.
    """
    remaining = list(pool)
    drawn = []
    x = (int(random_seed) + (round_number - 1) * ROUND_SEED_STRIDE) % LCG_MODULUS
    for _ in range(sample_size):
        if not remaining:
            break
        x = (LCG_MULTIPLIER * x + LCG_INCREMENT) % LCG_MODULUS
        idx = x % len(remaining)
        drawn.append(remaining.pop(idx))
    return drawn


# ---------------------------------------------------------------------------
# 5. tally_discrepancy_measure
# ---------------------------------------------------------------------------


def relative_taint(net_error_votes, contest_margin_votes, batch_ballot_count):
    if not batch_ballot_count:
        return rhu(0, 4)
    return rhu(
        dec(net_error_votes) * dec(contest_margin_votes or 0)
        / (Decimal(2) * dec(batch_ballot_count)),
        4,
    )


def measure_threshold(measure_variant):
    if measure_variant == "MAX_RELATIVE_OVERSTATEMENT":
        return MAX_RELATIVE_OVERSTATEMENT_THRESHOLD
    return NET_MARGIN_SHIFT_THRESHOLD


def discrepancy_measure(measure_variant, counted_ballots, net_error_votes, taints):
    if counted_ballots is None or counted_ballots == 0:
        return rhu(0, 4)
    if measure_variant == "MAX_RELATIVE_OVERSTATEMENT":
        best = max([dec(t) for t in taints], default=Decimal(0))
        return rhu(max(Decimal(0), best), 4)
    return rhu(abs(dec(net_error_votes)) / dec(counted_ballots), 4)


def escalates(measure_variant, measure):
    return dec(measure) >= measure_threshold(measure_variant)


# ---------------------------------------------------------------------------
# 6. recount_deposit_assessment
# ---------------------------------------------------------------------------


def deposit_assessment(trigger_type, scope, ballots_in_scope):
    if trigger_type in ("AUTOMATIC_MARGIN", "AUDIT_ESCALATION"):
        return 0, "NOT_REQUIRED"
    rate = (
        FULL_CONTEST_RATE_CENTS
        if scope == "FULL_CONTEST"
        else PARTIAL_BATCH_RATE_CENTS
    )
    raw = DEPOSIT_BASE_CENTS + rate * int(ballots_in_scope)
    required = min(DEPOSIT_CAP_CENTS, max(DEPOSIT_FLOOR_CENTS, raw))
    return required, "PENDING"


# ---------------------------------------------------------------------------
# 7. recount_cost_and_refund
# ---------------------------------------------------------------------------


def recount_actual_cost(scope_batches, team_hours):
    """scope_batches must be ordered by batch_label ascending."""
    ballot_cost = 0
    for batch in scope_batches:
        line = rhu(BALLOT_COST_CENTS_PER_BALLOT * dec(batch["ballot_count"]), 0)
        ballot_cost += int(line)
    labor_cost = int(rhu(dec(team_hours) * LABOR_COST_CENTS_PER_HOUR, 0))
    return ballot_cost + labor_cost


def completion_settlement(deposit_paid_cents, actual_cost_cents, outcome_changed,
                          margin_change_votes):
    if outcome_changed or abs(int(margin_change_votes)) >= STATUTORY_MARGIN_SHIFT_VOTES:
        return {
            "refund_variant": "STATUTORY_REFUND",
            "refunded_cents": deposit_paid_cents,
            "forfeited_cents": 0,
            "admin_retained_cents": 0,
            "deposit_status": "REFUNDED_FULL",
        }
    forfeited = min(deposit_paid_cents, actual_cost_cents)
    refunded = deposit_paid_cents - forfeited
    return {
        "refund_variant": "PRORATED_COST_RECOVERY",
        "refunded_cents": refunded,
        "forfeited_cents": forfeited,
        "admin_retained_cents": 0,
        "deposit_status": "FORFEITED" if refunded == 0 else "PARTIALLY_REFUNDED",
    }


def withdrawal_settlement(deposit_paid_cents):
    retained = int(rhu(dec(deposit_paid_cents) * WITHDRAWAL_RETENTION_RATE, 0))
    return {
        "refund_variant": "WITHDRAWAL_RETENTION",
        "refunded_cents": deposit_paid_cents - retained,
        "forfeited_cents": 0,
        "admin_retained_cents": retained,
        "deposit_status": "PARTIALLY_REFUNDED",
    }


def denial_settlement(deposit_paid_cents):
    return {
        "refund_variant": "STATUTORY_REFUND",
        "refunded_cents": deposit_paid_cents,
        "forfeited_cents": 0,
        "admin_retained_cents": 0,
        "deposit_status": "REFUNDED_FULL",
    }


# ---------------------------------------------------------------------------
# 8. certification_timeline_projection helpers
# ---------------------------------------------------------------------------


def hours_between(later, earlier):
    seconds = dec((later - earlier).total_seconds())
    return rhu(seconds / Decimal(3600), 2)


def hand_count_hours(hand_count_ballots):
    return ceil_int(
        dec(hand_count_ballots) * Decimal(HAND_COUNT_HOURS_PER_1000) / Decimal(1000)
    )


def extension_days_for(slack_hours):
    if dec(slack_hours) >= 0:
        return 0
    return min(MAX_EXTENSION_DAYS, ceil_int(-dec(slack_hours) / Decimal(24)))


def timeline_status_for(effective_slack_hours):
    slack = dec(effective_slack_hours)
    if slack < 0:
        return "BREACHED"
    if slack <= AT_RISK_SLACK_HOURS:
        return "AT_RISK"
    return "ON_TRACK"


TIMELINE_RANK = {"ON_TRACK": 0, "AT_RISK": 1, "BREACHED": 2}


def worst_timeline(statuses):
    worst = "ON_TRACK"
    for status in statuses:
        if TIMELINE_RANK.get(status, 0) > TIMELINE_RANK[worst]:
            worst = status
    return worst


# ---------------------------------------------------------------------------
# 9. board_quorum_adjudication
# ---------------------------------------------------------------------------


def board_outcome(board_votes, proposed_determination):
    votes_cast = len(board_votes)
    accept_count = sum(1 for v in board_votes if v["vote"] == "ACCEPT")
    reject_count = sum(1 for v in board_votes if v["vote"] == "REJECT")
    parties = set(v["party"] for v in board_votes)
    quorum_met = (
        votes_cast >= BOARD_QUORUM_MIN_VOTES and "DEM" in parties and "REP" in parties
    )
    if not quorum_met:
        status = "PENDING"
        final = None
    elif accept_count == reject_count:
        status = "DEADLOCKED"
        final = None
    elif accept_count > reject_count:
        status = "ADJUDICATED"
        final = proposed_determination
    else:
        status = "ADJUDICATED"
        final = "NO_VOTE"
    return {
        "votes_cast": votes_cast,
        "accept_count": accept_count,
        "reject_count": reject_count,
        "quorum_met": quorum_met,
        "status": status,
        "final_determination": final,
    }
