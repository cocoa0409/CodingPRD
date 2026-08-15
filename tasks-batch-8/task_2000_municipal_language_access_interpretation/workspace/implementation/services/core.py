"""Business logic: derivational ledgers, chronological scoring replays,
pricing with pinned rounding order, the dispatch selector, and cascades.

Ledger money fields (contract committed/spent, department spent, document
translated_language_codes, interpreter minutes_current_month) are DERIVED
from source records at read time so they can never drift; `version` bumps and
`updated_at` refreshes are applied explicitly via touch() to every entity an
accepted mutation or cascade affects (PRD §2.4).
"""
from datetime import timedelta

from db import db
from util import CLOCK, parse_iso, round_half_up_div

CONFIDENTIALITY_TTL_DAYS = 365
IN_PERSON_BUFFER_MIN = 30
IN_PERSON_LEAD = timedelta(hours=2)
REMEDIATION_WINDOW = timedelta(days=30)

MIN_MINUTES = {"PHONE": 15, "VIDEO": 15, "IN_PERSON": 60}
RATE_FIELD = {
    "PHONE": "phone_per_minute_cents",
    "VIDEO": "video_per_minute_cents",
    "IN_PERSON": "in_person_per_minute_cents",
}
TIER_MULT = {"PROVISIONAL": (85, 100), "REGISTERED": (1, 1), "CERTIFIED": (115, 100)}
AFTER_HOURS_NUM, AFTER_HOURS_DEN = 3, 2  # x1.5

SUBSTANTIATED_PENALTY = 150
UNFULFILLED_PENALTY = 50
ON_TIME_RESOLUTION_BONUS = 100
COMPLETION_BONUS = 5
SUBSTANTIATED_LINKED_PENALTY = 200
SUSPENSION_THRESHOLD = 600

JOB_COMMITTED_STATES = ("QUEUED", "IN_TRANSLATION", "QUALITY_REVIEW")
JOB_SPENT_STATES = ("APPROVED", "SUPERSEDED")


def touch(rec):
    """PRD §2.4: version increments on every accepted mutation (including
    cascade-driven ones); updated_at refreshes from the logical clock."""
    rec["version"] += 1
    rec["updated_at"] = CLOCK.now_iso()


# ---------------------------------------------------------------------------
# Derivational ledger: VendorContract (calculations.vendor_contract_commitment)
# ---------------------------------------------------------------------------

def contract_committed(contract_id) -> int:
    total = 0
    for j in db["translation_jobs"].values():
        if j["vendor_contract_id"] == contract_id and j["status"] in JOB_COMMITTED_STATES:
            total += j["provisional_cost_cents"]
    for r in db["interpretation_requests"].values():
        if r["_contract_id"] == contract_id and r["status"] == "ASSIGNED":
            total += r["estimated_cost_cents"]
    return total


def contract_spent(contract_id) -> int:
    total = 0
    for j in db["translation_jobs"].values():
        if j["vendor_contract_id"] == contract_id and j["status"] in JOB_SPENT_STATES:
            total += j["final_cost_cents"]
    for r in db["interpretation_requests"].values():
        if (r["_contract_id"] == contract_id and r["status"] == "COMPLETED"
                and not r["refund_clawed_back"]):
            total += r["final_cost_cents"]
    return total


def contract_available(contract_id) -> int:
    c = db["vendor_contracts"][contract_id]
    return c["ceiling_cents"] - contract_spent(contract_id) - contract_committed(contract_id)


def maybe_exhaust_contract(contract):
    """ACTIVE -> EXHAUSTED whenever spent recomputes to >= 90% of ceiling.
    Cascade: every QUEUED job on the contract is CANCELLED (its provisional
    commitment releases derivationally). EXHAUSTED is terminal; a later REFUND
    never revives it. Returns True when the transition fired."""
    if contract["status"] != "ACTIVE":
        return False
    if contract_spent(contract["id"]) * 10 < contract["ceiling_cents"] * 9:
        return False
    contract["status"] = "EXHAUSTED"
    for job in db["translation_jobs"].values():
        if job["vendor_contract_id"] == contract["id"] and job["status"] == "QUEUED":
            job["status"] = "CANCELLED"
            touch(job)
    return True


# ---------------------------------------------------------------------------
# Derivational ledger: Department (§3.1)
# ---------------------------------------------------------------------------

def department_spent(dept_id) -> int:
    total = 0
    for r in db["interpretation_requests"].values():
        if (r["department_id"] == dept_id and r["status"] == "COMPLETED"
                and not r["refund_clawed_back"]):
            total += r["final_cost_cents"]
    doc_ids = {d["id"] for d in db["vital_documents"].values() if d["department_id"] == dept_id}
    for j in db["translation_jobs"].values():
        if j["document_id"] in doc_ids and j["status"] in JOB_SPENT_STATES:
            total += j["final_cost_cents"]
    return total


def _compliance_events(dept_id):
    """(event_at, source created_at, source seq, delta) tuples, chronological."""
    evts = []
    for c in db["complaints"].values():
        if c["department_id"] != dept_id:
            continue
        if c["status"] in ("SUBSTANTIATED", "RESOLVED"):
            evts.append((parse_iso(c["adjudicated_at"]), parse_iso(c["created_at"]),
                         c["_seq"], -SUBSTANTIATED_PENALTY))
            if (c["status"] == "RESOLVED" and c["closed_at"] and c["remediation_due_at"]
                    and parse_iso(c["closed_at"]) <= parse_iso(c["remediation_due_at"])):
                evts.append((parse_iso(c["closed_at"]), parse_iso(c["created_at"]),
                             c["_seq"], ON_TIME_RESOLUTION_BONUS))
    for r in db["interpretation_requests"].values():
        if r["department_id"] == dept_id and r["status"] == "UNFULFILLED":
            evts.append((parse_iso(r["created_at"]), parse_iso(r["created_at"]),
                         r["_seq"], -UNFULFILLED_PENALTY))
    evts.sort(key=lambda e: (e[0], e[1], e[2]))
    return evts


def department_compliance(dept_id) -> int:
    """Chronological replay with stepwise clamping (calculations.department_compliance_score)."""
    score = 1000
    for _, _, _, delta in _compliance_events(dept_id):
        score = min(1000, max(0, score + delta))
    return score


def department_posture(dept_id) -> str:
    score = department_compliance(dept_id)
    if score >= 800:
        return "GOOD_STANDING"
    if score >= 600:
        return "WATCH"
    return "NONCOMPLIANT"


# ---------------------------------------------------------------------------
# Interpreter derivations (calculations.interpreter_quality_rating, minutes)
# ---------------------------------------------------------------------------

def interpreter_minutes_current_month(interp_id) -> int:
    now = CLOCK.now()
    total = 0
    for r in db["interpretation_requests"].values():
        if (r["interpreter_id"] == interp_id and r["status"] == "COMPLETED"
                and not r["refund_clawed_back"] and r["completed_at"]):
            ca = parse_iso(r["completed_at"])
            if (ca.year, ca.month) == (now.year, now.month):
                total += r["actual_minutes"]
    return total


def interpreter_rating_replay(interp_id) -> int:
    """Full chronological replay: +5 per completion (at completed_at), -200 per
    SUBSTANTIATED/RESOLVED complaint linked to one of the interpreter's requests
    (at adjudicated_at); stepwise clamped to [0, 1000]."""
    evts = []
    for r in db["interpretation_requests"].values():
        if r["interpreter_id"] == interp_id and r["status"] == "COMPLETED":
            evts.append((parse_iso(r["completed_at"]), parse_iso(r["created_at"]),
                         r["_seq"], COMPLETION_BONUS))
    for c in db["complaints"].values():
        if c["status"] in ("SUBSTANTIATED", "RESOLVED") and c["interpretation_request_id"]:
            r = db["interpretation_requests"].get(c["interpretation_request_id"])
            if r is not None and r["interpreter_id"] == interp_id:
                evts.append((parse_iso(c["adjudicated_at"]), parse_iso(c["created_at"]),
                             c["_seq"], -SUBSTANTIATED_LINKED_PENALTY))
    evts.sort(key=lambda e: (e[0], e[1], e[2]))
    rating = 1000
    for _, _, _, delta in evts:
        rating = min(1000, max(0, rating + delta))
    return rating


def recompute_interpreter_rating(interp):
    """Store the replayed rating; auto-suspend (with the cancellation cascade)
    when the recomputation lands below 600 on an ACTIVE interpreter."""
    interp["quality_rating"] = interpreter_rating_replay(interp["id"])
    if interp["quality_rating"] < SUSPENSION_THRESHOLD and interp["status"] == "ACTIVE":
        interp["status"] = "SUSPENDED"
        for r in db["interpretation_requests"].values():
            if r["interpreter_id"] == interp["id"] and r["status"] == "ASSIGNED":
                r["status"] = "CANCELLED"
                touch(r)
                contract = db["vendor_contracts"].get(r["_contract_id"])
                if contract is not None:
                    touch(contract)


def confidentiality_current(interp) -> bool:
    """Current iff confidentiality_signed_at >= now - 365 days (boundary inclusive)."""
    sig = interp["confidentiality_signed_at"]
    if sig is None:
        return False
    return parse_iso(sig) >= CLOCK.now() - timedelta(days=CONFIDENTIALITY_TTL_DAYS)


# ---------------------------------------------------------------------------
# VitalDocument derivation
# ---------------------------------------------------------------------------

def document_translated_language_codes(doc_id):
    """Sorted unique target languages of the document's APPROVED jobs
    (SUPERSEDED jobs excluded)."""
    return sorted({
        j["target_language_code"]
        for j in db["translation_jobs"].values()
        if j["document_id"] == doc_id and j["status"] == "APPROVED"
    })


# ---------------------------------------------------------------------------
# Pricing (calculations.interpretation_cost / translation_cost)
# ---------------------------------------------------------------------------

def interpretation_cost_cents(modality, minutes, tier, rate_card, after_hours) -> int:
    """Pinned five-step order; round half up after the tier step and again
    after the after-hours step. `rate_card` carries the three per-minute rates
    and in_person_travel_flat_cents."""
    billable = max(MIN_MINUTES[modality], ((minutes + 5) // 6) * 6)
    base = billable * rate_card[RATE_FIELD[modality]]
    num, den = TIER_MULT[tier]
    tiered = round_half_up_div(base * num, den)
    timed = round_half_up_div(tiered * AFTER_HOURS_NUM, AFTER_HOURS_DEN) if after_hours else tiered
    if modality == "IN_PERSON":
        return timed + rate_card["in_person_travel_flat_cents"]
    return timed


def translation_final_cost_cents(submitted_word_count, revision_count, rush, rate) -> int:
    """base + capped revision surcharge (10% per cycle, cap 30%), then the
    x1.25 rush multiplier; round half up after each pinned step."""
    base = submitted_word_count * rate
    revision_pct = min(revision_count * 10, 30)
    surcharged = base + round_half_up_div(base * revision_pct, 100)
    if rush:
        return round_half_up_div(surcharged * 5, 4)
    return surcharged


def is_after_hours(scheduled_start_iso) -> bool:
    """After-hours := scheduled_start's UTC hour < 8 or >= 18. Evaluated only
    for sessions with an explicitly supplied scheduled_start."""
    return parse_iso(scheduled_start_iso).hour < 8 or parse_iso(scheduled_start_iso).hour >= 18


# ---------------------------------------------------------------------------
# Dispatch selector (calculations.interpreter_dispatch_selection)
# ---------------------------------------------------------------------------

def dispatch_candidates(req):
    """Eligible pool for a new InterpretationRequest, ranked by
    minutes_current_month ASC, created_at ASC, full_name ASC.
    Returns a list of (interpreter, estimated_cost_cents_against_own_contract)."""
    now = CLOCK.now()
    new_start = parse_iso(req["scheduled_start"])
    new_end = new_start + timedelta(minutes=req["scheduled_duration_minutes"])
    cands = []
    for it in db["interpreters"].values():
        # (a) ACTIVE
        if it["status"] != "ACTIVE":
            continue
        # (b) confidentiality current
        if not confidentiality_current(it):
            continue
        # (c) language coverage
        if req["language_code"] not in it["language_codes"]:
            continue
        # (d) modality served
        if req["modality"] not in it["modalities"]:
            continue
        # (e) tier rule
        if req["encounter_setting"] in ("COURT", "MEDICAL") and it["tier"] != "CERTIFIED":
            continue
        # (f) buffered in-person overlap
        if req["modality"] == "IN_PERSON":
            conflict = False
            for s in db["interpretation_requests"].values():
                if (s["interpreter_id"] == it["id"] and s["status"] == "ASSIGNED"
                        and s["modality"] == "IN_PERSON"):
                    s_start = parse_iso(s["scheduled_start"])
                    s_end = s_start + timedelta(minutes=s["scheduled_duration_minutes"])
                    if (new_start < s_end + timedelta(minutes=IN_PERSON_BUFFER_MIN)
                            and s_start - timedelta(minutes=IN_PERSON_BUFFER_MIN) < new_end):
                        conflict = True
                        break
            if conflict:
                continue
        # (g) billing contract ACTIVE with room for this candidate's estimate
        contract = db["vendor_contracts"].get(it["vendor_contract_id"])
        if contract is None or contract["status"] != "ACTIVE":
            continue
        est = interpretation_cost_cents(
            req["modality"], req["scheduled_duration_minutes"], it["tier"],
            contract, req["_after_hours"])
        if contract_available(contract["id"]) < est:
            continue
        cands.append((it, est))
    cands.sort(key=lambda p: (
        interpreter_minutes_current_month(p[0]["id"]),
        parse_iso(p[0]["created_at"]),
        p[0]["full_name"],
        p[0]["_seq"],
    ))
    return cands


def cancel_assigned_request(req):
    """ASSIGNED -> CANCELLED; the estimated commitment releases derivationally."""
    req["status"] = "CANCELLED"
    touch(req)
    contract = db["vendor_contracts"].get(req["_contract_id"])
    if contract is not None:
        touch(contract)
