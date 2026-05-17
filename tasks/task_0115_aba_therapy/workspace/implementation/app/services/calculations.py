"""Calculation rules — SCAFFOLD §1.3 / PRD §2.9, §2.10, §3.6, §3.7.

Every monetary calculation uses decimal.Decimal with ROUND_HALF_UP.
Every unit calculation uses integer ceiling division.
"""
import math
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Tuple

from ..clock import add_days, diff_seconds, parse_iso
from ..store import get_store


# ---- Tiered per-unit reimbursement rates (cents per unit). PRD §3.6 ----
TIERED_RATES_CENTS = {
    "DIRECT_RBT": 3333,
    "BCBA_SUPERVISION": 6800,
    "PARENT_TRAINING": 5000,
}

PATIENT_RESPONSIBILITY_PCT_DEFAULT = Decimal("0.15")

# Per-payer overrides; the PRD describes only the default. Lookup is
# tolerant — any payer_name not in this map falls back to the default.
PATIENT_RESPONSIBILITY_BY_PAYER: dict = {}

APPEAL_HAIRCUT_PER_ROUND = Decimal("0.05")

SUPERVISION_RATIO_MIN = 0.10
SUPERVISION_WINDOW_DAYS = 30
PROGRESS_WINDOW_DAYS = 90
MINUTES_PER_UNIT = 15


# =============================================================================
# Generic conversions
# =============================================================================

def ceil_units(minutes: int) -> int:
    """Convert minutes to 15-minute units, rounding up."""
    if minutes <= 0:
        return 0
    return math.ceil(minutes / MINUTES_PER_UNIT)


def round_half_up_to_cents(dollar_amount: Decimal) -> int:
    """Round a Decimal dollar amount to whole cents with ROUND_HALF_UP."""
    cents = (dollar_amount * Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(cents)


def round_half_up_cents_to_cents(cents: Decimal) -> int:
    return int(cents.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2dp(value) -> float:
    """Round a numeric value to 2 decimal places with ROUND_HALF_UP."""
    d = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(d)


# =============================================================================
# Authorization unit balance (provisional + adjudicated)
# =============================================================================

def authorization_consumption(authorization_id: str) -> Tuple[int, int]:
    """Return (provisional_units_consumed, adjudicated_units_consumed).

    SCAFFOLD §1.3 calculations.authorization_unit_balance. For both subsets the
    consumption figure is `-sum(units_delta)` over the matching ledger entries.
    """
    store = get_store()
    prov = 0
    adj = 0
    for entry in store.ledger_entries.values():
        if entry["authorization_id"] != authorization_id:
            continue
        et = entry["entry_type"]
        d = entry["units_delta"]
        if et in ("PROVISIONAL_DEBIT", "PROVISIONAL_CREDIT"):
            prov += -d
        elif et in ("ADJUDICATED_DEBIT", "ADJUDICATED_CREDIT"):
            adj += -d
    return prov, adj


def provisional_balance(authorization: dict) -> int:
    prov, _ = authorization_consumption(authorization["id"])
    return authorization["approved_units"] - prov


def adjudicated_balance(authorization: dict) -> int:
    _, adj = authorization_consumption(authorization["id"])
    return authorization["approved_units"] - adj


def recompute_authorization_consumption(authorization: dict) -> None:
    """Refresh the two computed fields on the Authorization in-place."""
    prov, adj = authorization_consumption(authorization["id"])
    authorization["provisional_units_consumed"] = prov
    authorization["adjudicated_units_consumed"] = adj


# =============================================================================
# Supervision ratio (PRD §2.10)
# =============================================================================

def _session_in_window(session: dict, window_start_iso: str, window_end_iso: str) -> bool:
    """Open-closed: (window_start, window_end]."""
    if not session.get("actual_end"):
        return False
    ae = parse_iso(session["actual_end"])
    ws = parse_iso(window_start_iso)
    we = parse_iso(window_end_iso)
    return (ae > ws) and (ae <= we)


def compute_supervision_ratio(patient_id: str, now_ts_iso: str) -> dict:
    """Return {ratio, compliant, rbt_minutes, bcba_supervision_minutes, window_start, window_end}.

    Window is the trailing 30 days ending at now_ts. Sessions in COMPLETED or
    BILLED whose actual_end falls in the open-closed (window_start, window_end]
    window are aggregated by session_type.
    """
    store = get_store()
    window_start = add_days(now_ts_iso, -SUPERVISION_WINDOW_DAYS)
    window_end = now_ts_iso

    rbt_minutes = 0.0
    bcba_minutes = 0.0
    for s in store.sessions.values():
        if s["patient_id"] != patient_id:
            continue
        if s["status"] not in ("COMPLETED", "BILLED"):
            continue
        if not s.get("actual_start") or not s.get("actual_end"):
            continue
        if not _session_in_window(s, window_start, window_end):
            continue
        minutes = diff_seconds(s["actual_start"], s["actual_end"]) / 60.0
        if s["session_type"] == "DIRECT_RBT":
            rbt_minutes += minutes
        elif s["session_type"] == "BCBA_SUPERVISION":
            bcba_minutes += minutes

    if rbt_minutes == 0:
        ratio = 1.0
    else:
        ratio = bcba_minutes / rbt_minutes
    compliant = ratio >= SUPERVISION_RATIO_MIN
    return {
        "ratio": ratio,
        "compliant": compliant,
        "rbt_minutes": rbt_minutes,
        "bcba_supervision_minutes": bcba_minutes,
        "window_start": window_start,
        "window_end": window_end,
    }


# =============================================================================
# Patient clinical progress scores (PRD §3.7)
# =============================================================================

def recompute_patient_progress_scores(patient: dict, now_ts_iso: str) -> None:
    """Refresh both progress score fields on the patient."""
    store = get_store()
    window_start = add_days(now_ts_iso, -PROGRESS_WINDOW_DAYS)
    window_end = now_ts_iso

    prov_num = 0
    prov_den = 0
    adj_num = 0
    adj_den = 0

    # Build the set of session IDs referenced by any PAID claim for this patient.
    paid_session_ids = set()
    for c in store.claims.values():
        if c["patient_id"] != patient["id"]:
            continue
        if c["status"] == "PAID":
            for sid in c["session_ids"]:
                paid_session_ids.add(sid)

    for s in store.sessions.values():
        if s["patient_id"] != patient["id"]:
            continue
        if not _session_in_window(s, window_start, window_end):
            continue
        if s.get("billed_units") is None or s.get("progress_rating") is None:
            continue

        # Provisional: COMPLETED or BILLED, DIRECT_RBT or BCBA_SUPERVISION.
        if s["status"] in ("COMPLETED", "BILLED") and s["session_type"] in ("DIRECT_RBT", "BCBA_SUPERVISION"):
            prov_num += s["billed_units"] * s["progress_rating"]
            prov_den += s["billed_units"]

        # Adjudicated: only BCBA_SUPERVISION AND referenced by a PAID claim.
        if s["session_type"] == "BCBA_SUPERVISION" and s["id"] in paid_session_ids:
            adj_num += s["billed_units"] * s["progress_rating"]
            adj_den += s["billed_units"]

    if prov_den == 0:
        prov_score = 0.0
    else:
        prov_score = round_half_up_2dp(Decimal(prov_num) / Decimal(prov_den))

    if adj_den == 0:
        adj_score = 0.0
    else:
        adj_score = round_half_up_2dp(Decimal(adj_num) / Decimal(adj_den))

    patient["clinical_progress_score_provisional"] = prov_score
    patient["clinical_progress_score_adjudicated"] = adj_score


# =============================================================================
# Claim totals
# =============================================================================

def _patient_responsibility_pct(payer_name: str) -> Decimal:
    return PATIENT_RESPONSIBILITY_BY_PAYER.get(payer_name, PATIENT_RESPONSIBILITY_PCT_DEFAULT)


def _per_line_submitted_cents(session: dict, payer_name: str) -> int:
    """Compute one line's submitted cents per PRD §3.6 / SCAFFOLD claim_total_submitted.

    raw_line_dollars = (billed_units * rate_cents_per_unit / 100) * (1 - patient_resp_pct)
    line_cents       = round_half_up(raw_line_dollars * 100)
    """
    rate_cents_per_unit = TIERED_RATES_CENTS[session["session_type"]]
    billed_units = session["billed_units"]
    patient_pct = _patient_responsibility_pct(payer_name)
    # Use Decimal throughout to avoid float drift.
    raw_dollars = (Decimal(billed_units) * Decimal(rate_cents_per_unit) / Decimal(100)) * (Decimal(1) - patient_pct)
    return round_half_up_to_cents(raw_dollars)


def _ordered_sessions_for_claim(claim: dict) -> List[dict]:
    """Sessions for a claim sorted by TherapySession.id ascending."""
    store = get_store()
    ids = sorted(claim["session_ids"])
    return [store.sessions[sid] for sid in ids if sid in store.sessions]


def compute_submitted_amount_cents(claim: dict, authorization: dict) -> int:
    """Sum of per-line submitted cents in TherapySession.id ascending order."""
    total = 0
    for s in _ordered_sessions_for_claim(claim):
        total += _per_line_submitted_cents(s, authorization["payer_name"])
    return total


def compute_reimbursed_amount_cents(claim: dict, authorization: dict) -> int:
    """Sum of per-line reimbursed cents in TherapySession.id ascending order.

    appeal_round == 0:  reimbursed_line == submitted_line
    appeal_round >= 1:  reimbursed_line == round_half_up(submitted_line * (1 - 0.05)^appeal_round)
    Per PRD §3.6: per-line round, then sum.
    """
    appeal_round = claim.get("appeal_round", 0)
    if appeal_round == 0:
        return compute_submitted_amount_cents(claim, authorization)
    factor = (Decimal(1) - APPEAL_HAIRCUT_PER_ROUND) ** appeal_round
    total = 0
    for s in _ordered_sessions_for_claim(claim):
        base = _per_line_submitted_cents(s, authorization["payer_name"])
        line = (Decimal(base) * factor).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        total += int(line)
    return total
