"""The eight declared calculations (PRD 2.9, 3.3 - 3.8)."""
from decimal import Decimal, ROUND_HALF_UP

import store
from timeutil import parse_dt, whole_days

QUARTER = Decimal("0.25")
CENT_ZERO = Decimal("0")

CE_CATEGORIES = ("LIVE_CONTACT", "SELF_STUDY", "IN_SERVICE", "ACADEMIC")

SANCTION_TIERS = (
    "REPRIMAND",
    "FINE",
    "PROBATION",
    "PRACTICE_RESTRICTION",
    "SUSPENSION",
    "REVOCATION",
)

VIOLATION_BASE_TIER = {
    "PRACTICE_STANDARD": 1,
    "SUBSTANCE_USE": 3,
    "FRAUD": 3,
    "BOUNDARY_VIOLATION": 4,
    "CRIMINAL_CONDUCT": 5,
}


def rhu(value, places=2):
    """Round half up to `places` decimal places."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    exp = Decimal(1).scaleb(-places)
    return value.quantize(exp, rounding=ROUND_HALF_UP)


def tier_index(tier):
    if tier is None or tier == "NONE":
        return 0
    return SANCTION_TIERS.index(tier) + 1


def tier_at(index):
    if index <= 0:
        return "NONE"
    return SANCTION_TIERS[index - 1]


def ceil_half(net):
    """net / 2 rounded toward positive infinity, for integer net."""
    return -((-net) // 2)


# ---------------------------------------------------------------------------
# 1. ce_hour_credit_total
# ---------------------------------------------------------------------------
def credit_hours_for_minutes(minutes):
    """round_half_up(minutes / 60 / 0.25) * 0.25, carried to 2 decimals."""
    hours = Decimal(int(minutes)) / Decimal(60)
    quarters = rhu(hours / QUARTER, 0)
    return rhu(quarters * QUARTER, 2)


def ce_hour_credit_total(board, renewal, records, variant):
    """variant: 'provisional_self_reported' | 'audited_verified'."""
    admitted = []
    for rec in sorted(records, key=lambda r: r["created_at"]):
        if rec["verification_status"] == "REJECTED":
            continue
        if variant == "audited_verified":
            if rec["verification_status"] != "VERIFIED":
                continue
            if not rec.get("provider_accredited"):
                continue
            completion = rec.get("completion_date")
            start = renewal.get("period_start_on")
            end = renewal.get("period_end_on")
            if completion is None or start is None or end is None:
                continue
            if not (completion >= start and completion < end):
                continue
        admitted.append(rec)

    subtotals = dict((c, Decimal("0")) for c in CE_CATEGORIES)
    for rec in admitted:
        category = rec.get("category")
        if category in subtotals:
            subtotals[category] += rec.get("credit_hours") or Decimal("0")

    for category in CE_CATEGORIES:
        subtotals[category] = rhu(subtotals[category], 2)

    self_cap = board["ce_self_study_cap_hours"]
    in_cap = board["ce_in_service_cap_hours"]
    if subtotals["SELF_STUDY"] > self_cap:
        subtotals["SELF_STUDY"] = rhu(self_cap, 2)
    if subtotals["IN_SERVICE"] > in_cap:
        subtotals["IN_SERVICE"] = rhu(in_cap, 2)

    claimed = renewal.get("carry_over_hours_claimed") or Decimal("0")
    carry_cap = board["ce_carry_over_cap_hours"]
    allowed_carry = claimed if claimed <= carry_cap else carry_cap

    total = Decimal("0")
    for category in CE_CATEGORIES:
        total += subtotals[category]
    total += allowed_carry
    return rhu(total, 2)


# ---------------------------------------------------------------------------
# 2. multistate_privilege_determination
# ---------------------------------------------------------------------------
_EVIDENCE_WEIGHT = {"DRIVER_LICENSE": 3, "TAX_RETURN": 2, "VOTER_REGISTRATION": 1}


def evidenced_primary_state(nurse, clock):
    """Top-ranked residency evidence state, or the declared state as fallback."""
    pool = []
    evidence = nurse.get("residency_evidence") or []
    for index, entry in enumerate(evidence):
        if not isinstance(entry, dict):
            continue
        try:
            effective = parse_dt(entry.get("effective_date"))
        except Exception:
            continue
        if effective > clock:
            continue
        weight = _EVIDENCE_WEIGHT.get(entry.get("evidence_type"), 0)
        pool.append((weight, effective, -index, entry.get("state_code")))
    if not pool:
        return nurse.get("declared_primary_state")
    pool.sort(key=lambda t: (t[0], t[1], t[2]), reverse=True)
    return pool[0][3]


def multistate_privilege_determination(lic, variant):
    """Returns (status, variant, basis_state)."""
    st = store.STORE
    if lic["encumbrance_status"] in ("SUSPENDED", "REVOKED"):
        return "PRIVILEGE_REVOKED", variant, None
    if lic["license_status"] != "ACTIVE":
        return "NOT_ELIGIBLE", variant, None
    board = st.boards.get(lic["issuing_board_config_id"])
    if board is None or not board.get("compact_member"):
        return "SINGLE_STATE", variant, None
    if lic["credential_type"] in ("APRN", "NURSE_AIDE"):
        return "SINGLE_STATE", variant, None

    nurse = st.nurses.get(lic["nurse_id"])
    if nurse is None:
        return "SINGLE_STATE", variant, None

    if variant == "RESIDENCY_EVIDENCED":
        psor = evidenced_primary_state(nurse, st.clock)
    else:
        psor = nurse.get("declared_primary_state")

    if psor != board.get("state_code"):
        return "SINGLE_STATE", variant, psor

    for other in st.licenses.values():
        if other["id"] == lic["id"]:
            continue
        if other["nurse_id"] != lic["nurse_id"]:
            continue
        if other["encumbrance_status"] in ("RESTRICTED", "SUSPENDED", "REVOKED"):
            return "SINGLE_STATE", variant, psor

    return "MULTISTATE", variant, psor


# ---------------------------------------------------------------------------
# 3. sanction_severity_floor
# ---------------------------------------------------------------------------
def sanction_severity_floor(complaint, nurse, lic):
    st = store.STORE
    base = VIOLATION_BASE_TIER.get(complaint.get("violation_category"), 1)

    demands = [e for e in st.evidence_requests.values() if e["complaint_id"] == complaint["id"]]

    aggravation = 2 * int(nurse.get("prior_discipline_count") or 0)
    if lic is not None and lic.get("encumbrance_status") == "RESTRICTED":
        aggravation += 2
    if any(e.get("record_class") == "PHARMACY_DISPENSING" and e.get("status") == "PRODUCED"
           for e in demands):
        aggravation += 3
    aggravation += sum(
        1 for a in st.agreements.values()
        if a["nurse_id"] == nurse["id"] and a["status"] == "BREACHED"
    )

    mitigation = 0
    if complaint.get("complainant_type") == "SELF_REPORT":
        mitigation += 2
    if int(nurse.get("atd_participation_count") or 0) == 0:
        mitigation += 1
    if demands and all(e.get("status") == "PRODUCED" for e in demands):
        mitigation += 2

    net = aggravation - mitigation
    index = base + ceil_half(net)
    if index < 1:
        index = 1
    if index > 6:
        index = 6
    if complaint.get("status") == "ATD_ACTIVE" and index < 3:
        index = 3
    return tier_at(index)


# ---------------------------------------------------------------------------
# 4. panel_vote_tally
# ---------------------------------------------------------------------------
def seated_set(proceeding):
    recused = set(proceeding.get("recused_member_user_ids") or [])
    return [m for m in (proceeding.get("seated_member_user_ids") or []) if m not in recused]


def effective_ballots(proceeding):
    seated = set(seated_set(proceeding))
    best = {}
    for index, vote in enumerate(proceeding.get("votes") or []):
        voter = vote.get("voter_user_id")
        if voter not in seated:
            continue
        cast_at = vote.get("cast_at")
        current = best.get(voter)
        if current is None or cast_at >= current[0]:
            best[voter] = (cast_at, index, vote.get("proposed_sanction_tier"))
    return dict((voter, data[2]) for voter, data in best.items())


def panel_vote_tally(proceeding, board):
    seated = seated_set(proceeding)
    seated_count = len(seated)
    if seated_count == 0:
        return "NONE"
    ballots = effective_ballots(proceeding)
    for index in range(6, 0, -1):
        support = 0
        for member in seated:
            if tier_index(ballots.get(member)) >= index:
                support += 1
        threshold = board["revocation_vote_threshold_bp"] if index == 6 else board["majority_vote_threshold_bp"]
        if support * 10000 >= threshold * seated_count:
            return tier_at(index)
    return "NONE"


# ---------------------------------------------------------------------------
# 5. audit_sample_selection
# ---------------------------------------------------------------------------
def audit_risk_score(renewal, lic, board):
    st = store.STORE
    score = Decimal("0")
    has_open_complaint = any(
        c["license_id"] == lic["id"] and c["status"] not in ("DISMISSED", "CONSOLIDATED", "CLOSED")
        for c in st.complaints.values()
    )
    if has_open_complaint:
        score += Decimal("40")
    prior_failed = any(
        r["license_id"] == lic["id"] and r["id"] != renewal["id"] and r["audit_status"] == "FAILED"
        for r in st.renewals.values()
    )
    if prior_failed:
        score += Decimal("30")
    attested = int(renewal.get("attested_practice_hours") or 0)
    if attested * 100 < int(board["practice_hours_required"]) * 110:
        score += Decimal("20")
    if int(renewal.get("late_days") or 0) > 0:
        score += Decimal("10")
    return rhu(score, 2)


def sample_quota(rate_bp, eligible_count):
    numerator = int(rate_bp) * int(eligible_count)
    if numerator <= 0:
        return 0
    return -((-numerator) // 10000)


# ---------------------------------------------------------------------------
# 6. practice_hour_attainment
# ---------------------------------------------------------------------------
def practice_hour_attainment(renewal):
    window_start = renewal.get("period_start_on")
    window_end = renewal.get("period_end_on")
    total = 0
    for period in renewal.get("practice_hour_periods") or []:
        if not isinstance(period, dict):
            continue
        hours = period.get("hours")
        if hours is None:
            continue
        try:
            start = parse_dt(period.get("start_on"))
            end = parse_dt(period.get("end_on"))
        except Exception:
            continue
        period_days = whole_days(start, end)
        if period_days <= 0:
            continue
        overlap_start = start if start > window_start else window_start
        overlap_end = end if end < window_end else window_end
        overlap_days = whole_days(overlap_start, overlap_end)
        if overlap_days <= 0:
            continue
        total += (int(hours) * overlap_days) // period_days
    return total


# ---------------------------------------------------------------------------
# 7. renewal_fee_assessment
# ---------------------------------------------------------------------------
def renewal_fee_assessment(renewal, lic, board, late_days):
    st = store.STORE
    fee = int(board["renewal_base_fee_cents"])
    grace = int(board["renewal_grace_period_days"])
    if late_days <= 0:
        pass
    elif late_days <= 30:
        fee += int(board["late_fee_tier1_cents"])
    elif late_days <= grace:
        fee += int(board["late_fee_tier2_cents"])
    else:
        fee += int(board["reinstatement_fee_cents"])
    prior_failed = any(
        r["license_id"] == lic["id"] and r["id"] != renewal["id"] and r["audit_status"] == "FAILED"
        for r in st.renewals.values()
    )
    if prior_failed:
        fee += int(board["failed_audit_surcharge_cents"])
    return fee


# ---------------------------------------------------------------------------
# 8. license_encumbrance_reconciliation
# ---------------------------------------------------------------------------
OPEN_COMPLAINT_STATES = (
    "INVESTIGATION_OPEN",
    "EVIDENCE_COMPLETE",
    "ATD_OFFERED",
    "ATD_ACTIVE",
    "REFERRED_FOR_HEARING",
    "PROCEEDING_OPENED",
)


def open_encumbrance_count(license_id):
    st = store.STORE
    return sum(
        1 for c in st.complaints.values()
        if c["license_id"] == license_id
        and c.get("consolidated_into_complaint_id") is None
        and c["status"] in OPEN_COMPLAINT_STATES
    )
