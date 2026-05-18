"""Calculation rules (SCAFFOLD §1.3).

Each function implements one calculation:
  * calc_sol_deadline           — Statute-of-limitations effective deadline
  * calc_damages_total          — Medical bills + economic + non-economic
  * calc_attorney_fee           — Contingency-tier × gross settlement
  * calc_net_disbursement       — Waterfall with two strategies
  * calc_attorney_calendar_overlap — Interval overlap with 15-min buffer
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from config import (
    COURT_BUFFER_MINUTES,
    LIEN_PRIORITY_TABLE,
    LIEN_TYPES_STATUTORY,
    MINOR_TAIL_DEFAULT_YEARS,
    MINOR_TAIL_TABLE,
    SOL_DEFAULT_BASE_YEARS,
    SOL_TABLE,
)
from utils import add_years, parse_iso_date, round_half_up_int


# ── Statute of limitations ─────────────────────────────────────────────────


def calc_sol_deadline(
    jurisdiction_state: str,
    incident_type: str,
    incident_date: date,
    is_minor_at_incident: bool,
    date_of_birth: date,
    sol_tolled_days: int,
) -> date:
    """Compute the effective `sol_deadline` per SCAFFOLD calc_sol_deadline.

    Pinned three-step order:
      1. base_deadline = incident_date + base_years
      2. if minor: base_deadline = max(base_deadline, dob + 18 + minor_tail)
      3. effective = base_deadline + sol_tolled_days calendar days
    """
    base_years = SOL_TABLE.get(
        (jurisdiction_state, incident_type), SOL_DEFAULT_BASE_YEARS,
    )
    base_deadline = add_years(incident_date, base_years)

    if is_minor_at_incident:
        minor_tail = MINOR_TAIL_TABLE.get(jurisdiction_state, MINOR_TAIL_DEFAULT_YEARS)
        minor_deadline = add_years(date_of_birth, 18 + minor_tail)
        if minor_deadline > base_deadline:
            base_deadline = minor_deadline

    effective = base_deadline + timedelta(days=int(sol_tolled_days or 0))
    return effective


def is_sol_expired(case_row, now_dt: datetime) -> bool:
    """HARD boundary: a Case is OUT-OF-STATUTE iff now() >= sol_deadline.

    `sol_deadline` is stored as a YYYY-MM-DD string. The comparison treats
    the deadline as the start of that calendar day in UTC. PRD §2.10 says
    the comparison is inclusive on the boundary.
    """
    deadline_str = case_row.get("sol_deadline")
    if not deadline_str:
        return False
    deadline_date = parse_iso_date(deadline_str)
    if deadline_date is None:
        return False
    # Treat the deadline as midnight UTC of that calendar day. A request that
    # arrives at exactly that instant is already too late.
    deadline_dt = datetime(
        deadline_date.year, deadline_date.month, deadline_date.day,
        tzinfo=now_dt.tzinfo,
    )
    return now_dt >= deadline_dt


# ── Damages ─────────────────────────────────────────────────────────────────


def calc_damages_total(damages_row: dict, received_medical_bill_cents: int) -> dict:
    """Recompute medical_bills_cents, pain_suffering_cents, total_damages_cents.

    Mutates `damages_row` in place and returns it.
    """
    damages_row["medical_bills_cents"] = int(received_medical_bill_cents)

    economic = (
        damages_row["medical_bills_cents"]
        + int(damages_row.get("lost_wages_cents", 0))
        + int(damages_row.get("property_damage_cents", 0))
    )

    method = damages_row["pain_suffering_method"]
    if method == "MULTIPLIER":
        multiplier = Decimal(str(damages_row.get("multiplier_value") or "1.5"))
        pain_suffering = round_half_up_int(Decimal(economic) * multiplier)
    elif method == "PER_DIEM":
        rate = int(damages_row.get("per_diem_rate_cents", 0))
        days = int(damages_row.get("per_diem_days", 0))
        pain_suffering = rate * days
    else:
        pain_suffering = 0

    damages_row["pain_suffering_cents"] = int(pain_suffering)
    damages_row["total_damages_cents"] = economic + int(pain_suffering)
    return damages_row


def sum_received_medical_bills(case_id: str, medical_requests: dict) -> int:
    total = 0
    for r in medical_requests.values():
        if r["case_id"] == case_id and r["status"] == "RECEIVED":
            total += int(r.get("billed_amount_cents") or 0)
    return total


# ── Attorney fee tier ──────────────────────────────────────────────────────


def select_contingency_tier_bps(case_row: dict, fee_row: dict) -> int:
    """Pinned tier selection (SCAFFOLD calc_attorney_fee)."""
    if case_row["status"] == "TRIAL_AWARDED":
        return int(fee_row["trial_rate_bps"])
    if case_row.get("filed_in_court"):
        return int(fee_row["post_suit_rate_bps"])
    return int(fee_row["pre_suit_rate_bps"])


def calc_attorney_fee(gross_settlement_cents: int, rate_bps: int) -> int:
    """attorney_fee_cents = round_half_up_int(gross × bps / 10000)."""
    if gross_settlement_cents <= 0 or rate_bps <= 0:
        return 0
    value = Decimal(int(gross_settlement_cents)) * Decimal(int(rate_bps)) / Decimal(10000)
    return round_half_up_int(value)


# ── Net disbursement waterfall ─────────────────────────────────────────────


def _lien_sort_key(lien: dict):
    """Priority by lien_type, then ascending created_at, then ascending id."""
    return (
        LIEN_PRIORITY_TABLE.get(lien["lien_type"], 999),
        lien["created_at"],
        lien["id"],
    )


def order_liens_for_disbursement(case_id: str, liens_by_id: dict) -> list[dict]:
    case_liens = [l for l in liens_by_id.values() if l["case_id"] == case_id]
    return sorted(case_liens, key=_lien_sort_key)


def calc_net_disbursement(
    case_row: dict,
    liens_ordered: list[dict],
    strategy: str,
    attorney_fee_cents: int,
) -> dict:
    """Run the waterfall. Mutates each lien row in `liens_ordered` and returns
    a dict with `attorney_fee_cents`, `total_lien_payment_cents`, `client_net_cents`.

    DISPUTED liens are excluded from payment (final_paid_amount_cents=0,
    status unchanged). NEGOTIATING liens should already have been rejected
    upstream — caller is responsible.
    """
    gross = int(case_row["gross_settlement_cents"])
    case_costs = int(case_row["case_costs_cents"])

    net_after_fee = gross - attorney_fee_cents
    lien_pool = net_after_fee - case_costs
    remaining = lien_pool

    # Assign priority_rank one-indexed in this ordered pass.
    payable_liens: list[dict] = []
    for idx, lien in enumerate(liens_ordered, start=1):
        lien["priority_rank"] = idx

    if strategy == "CHRONOLOGICAL_PRIORITY":
        for lien in liens_ordered:
            if lien["status"] == "DISPUTED":
                lien["final_paid_amount_cents"] = 0
                continue

            face = int(lien["face_amount_cents"])
            negotiated = lien.get("negotiated_amount_cents")

            is_statutory = lien["lien_type"] in LIEN_TYPES_STATUTORY
            if is_statutory and negotiated is None:
                # Statutory ratable-reduction formula.
                if gross > 0:
                    attorney_ratio = Decimal(attorney_fee_cents) / Decimal(gross)
                    cost_ratio = Decimal(case_costs) / Decimal(gross)
                else:
                    attorney_ratio = Decimal(0)
                    cost_ratio = Decimal(0)
                reduced = round_half_up_int(
                    Decimal(face) * (Decimal(1) - attorney_ratio - cost_ratio)
                )
                if reduced < 0:
                    reduced = 0
                pay = min(reduced, max(remaining, 0))
                # Auto-flip statutory ASSERTED → REDUCED on the cascade.
                if lien["status"] == "ASSERTED":
                    lien["status"] = "REDUCED"
            else:
                ceiling = int(negotiated) if negotiated is not None else face
                pay = min(ceiling, max(remaining, 0))

            lien["final_paid_amount_cents"] = int(pay)
            remaining -= int(pay)

        total_lien_payment = sum(
            int(l.get("final_paid_amount_cents") or 0) for l in liens_ordered
        )
        client_net = remaining

    elif strategy == "FORWARD_LOOKING_PRORATA":
        # In pro-rata, ALL liens (statutory or not) share lien_pool by face_amount.
        sum_face = sum(int(l["face_amount_cents"]) for l in liens_ordered)
        if sum_face <= 0 or lien_pool <= 0:
            for lien in liens_ordered:
                if lien["status"] == "DISPUTED":
                    lien["final_paid_amount_cents"] = 0
                else:
                    lien["final_paid_amount_cents"] = 0
                    # Statutory liens still flip ASSERTED→REDUCED when settled.
                    if lien["lien_type"] in LIEN_TYPES_STATUTORY and lien["status"] == "ASSERTED":
                        lien["status"] = "REDUCED"
            total_lien_payment = 0
            client_net = max(0, lien_pool)
        else:
            non_disputed = [l for l in liens_ordered if l["status"] != "DISPUTED"]
            min_pool_or_face = min(lien_pool, sum_face)

            for lien in liens_ordered:
                if lien["status"] == "DISPUTED":
                    lien["final_paid_amount_cents"] = 0
                    continue
                face = int(lien["face_amount_cents"])
                # Pro-rata share rounded half-up.
                share = round_half_up_int(
                    Decimal(face) * Decimal(min_pool_or_face) / Decimal(sum_face)
                )
                pay = min(share, max(remaining, 0))
                lien["final_paid_amount_cents"] = int(pay)
                remaining -= int(pay)
                # Statutory liens move ASSERTED → REDUCED.
                if lien["lien_type"] in LIEN_TYPES_STATUTORY and lien["status"] == "ASSERTED":
                    lien["status"] = "REDUCED"

            # Pinned residual rule: residue goes to LAST lien in ordered pass.
            if non_disputed and remaining > 0:
                last = non_disputed[-1]
                # Cap at the lien's face_amount_cents.
                face_last = int(last["face_amount_cents"])
                already_paid = int(last["final_paid_amount_cents"])
                room = max(0, face_last - already_paid)
                bump = min(remaining, room)
                last["final_paid_amount_cents"] = already_paid + int(bump)
                remaining -= int(bump)

            total_lien_payment = sum(
                int(l.get("final_paid_amount_cents") or 0) for l in liens_ordered
            )
            client_net = max(0, lien_pool - total_lien_payment)
    else:
        raise ValueError(f"Unknown strategy: {strategy}")

    return {
        "attorney_fee_cents": int(attorney_fee_cents),
        "case_costs_cents": int(case_costs),
        "total_lien_payment_cents": int(total_lien_payment),
        "client_net_cents": int(client_net),
    }


# ── Attorney calendar overlap ──────────────────────────────────────────────


def attorney_calendar_conflict(
    candidate_start: datetime,
    candidate_duration_min: int,
    other_events: list[dict],
) -> bool:
    """Two events conflict iff their buffered half-open intervals overlap.

    Buffer = 15 minutes on each side. Adjacency at the buffered edge is allowed.
    """
    cand_buf_start = candidate_start - timedelta(minutes=COURT_BUFFER_MINUTES)
    cand_buf_end = candidate_start + timedelta(
        minutes=int(candidate_duration_min) + COURT_BUFFER_MINUTES
    )
    for other in other_events:
        if other["status"] not in ("SCHEDULED", "CONTINUED"):
            continue
        other_start = other["scheduled_at"]
        other_dur = int(other["duration_minutes"])
        o_buf_start = other_start - timedelta(minutes=COURT_BUFFER_MINUTES)
        o_buf_end = other_start + timedelta(minutes=other_dur + COURT_BUFFER_MINUTES)
        # Overlap iff max(starts) < min(ends).
        if max(cand_buf_start, o_buf_start) < min(cand_buf_end, o_buf_end):
            return True
    return False


def courtroom_conflict(
    candidate_start: datetime,
    candidate_duration_min: int,
    candidate_courtroom: str,
    other_events: list[dict],
) -> bool:
    """No buffer. Touching boundaries are allowed."""
    if not candidate_courtroom:
        return False
    cand_end = candidate_start + timedelta(minutes=int(candidate_duration_min))
    for other in other_events:
        if other["status"] not in ("SCHEDULED", "CONTINUED"):
            continue
        if not other.get("courtroom") or other["courtroom"] != candidate_courtroom:
            continue
        other_start = other["scheduled_at"]
        other_end = other_start + timedelta(minutes=int(other["duration_minutes"]))
        if max(candidate_start, other_start) < min(cand_end, other_end):
            return True
    return False
