"""Named calculations from the PRD, each with its own pinned evaluation order."""

from datetime import timedelta
from decimal import Decimal

from core import (
    clock,
    date_at_midnight,
    floor_pct,
    parse_date,
    round_half_up,
    store,
)

# --------------------------------------------------------------------------
# constants
# --------------------------------------------------------------------------

EFL_BANDS = {
    "CASAS_R_900": {1: 0, 2: 201, 3: 211, 4: 221, 5: 236, 6: 246},
    "CASAS_M_900": {1: 0, 2: 194, 3: 203, 4: 214, 5: 227, 6: 236},
    "BEST_PLUS": {1: 0, 2: 401, 3: 418, 4: 439, 5: 473, 6: 507},
}

TEST_FORMS = tuple(EFL_BANDS.keys())
TEST_PURPOSES = ("PRE_TEST", "POST_TEST")

SUBTESTS = ("MATH", "RLA", "SCIENCE", "SOCIAL_STUDIES")
REQUIRED_SUBTESTS = ("MATH", "RLA", "SCIENCE", "SOCIAL_STUDIES")
SUBTEST_FEE_CENTS = {"MATH": 3000, "RLA": 3400, "SCIENCE": 3000, "SOCIAL_STUDIES": 3000}
ALT_FORMAT_SURCHARGE_CENTS = 1200
RETAKE_BASE = Decimal("1.25")
RETAKE_EXPONENT_CAP = 2
SURCHARGED_FORMATS = ("LARGE_PRINT", "BRAILLE", "AUDIO")

FORMATS = ("STANDARD", "EXTRA_TIME", "LARGE_PRINT", "BRAILLE", "AUDIO")
REQUESTABLE_FORMATS = ("EXTRA_TIME", "LARGE_PRINT", "BRAILLE", "AUDIO")

PASS_SCORE_PER_SUBTEST = 145
COMPOSITE_MIN = 580

MIN_POST_TEST_HOURS = Decimal("40.00")
MIN_POST_TEST_DAY_INTERVAL = 30

COPY_FEE_CENTS = 1500
RUSH_FEE_CENTS = 2500

MEASURE_WEIGHT = {
    "EFL_GAIN": Decimal("1.00"),
    "CREDENTIAL_ATTAINMENT": Decimal("1.50"),
    "EMPLOYMENT_Q2": Decimal("1.25"),
    "POSTSECONDARY_ENROLLMENT": Decimal("1.40"),
}
MEASURE_TYPES = tuple(MEASURE_WEIGHT.keys())
ALLOCATION_STATUS_FILTER = {
    "PROVISIONAL": ("RECORDED", "CERTIFIED"),
    "FINAL": ("CERTIFIED",),
}
ALLOCATION_VARIANTS = ("PROVISIONAL", "FINAL")
MSG_VARIANTS = ("BEST_POST", "LATEST_POST")

PROGRAM_TRACKS = ("LITERACY", "HSE_PREP", "ESL")
INTAKE_STATUSES = ("INTAKE_STARTED", "ORIENTED", "PLACED", "ENROLLED", "EXITED")
CREDENTIAL_STATUSES = ("NONE", "ISSUED", "REVOKED")


# --------------------------------------------------------------------------
# efl_placement_level
# --------------------------------------------------------------------------

def efl_level_for(test_form, scale_score):
    bands = EFL_BANDS[test_form]
    level = 1
    for candidate in sorted(bands.keys()):
        if scale_score >= bands[candidate]:
            level = candidate
    return level


# --------------------------------------------------------------------------
# post_test_eligibility
# --------------------------------------------------------------------------

def hours_gate_ok(enrollment):
    return enrollment["_posted_hours"] >= MIN_POST_TEST_HOURS


def earliest_scored_pre_test(student_id):
    events = [
        e for e in store.test_events.values()
        if e["student_id"] == student_id
        and e["purpose"] == "PRE_TEST"
        and e["status"] == "SCORED"
        and e.get("_test_date") is not None
    ]
    if not events:
        return None
    events.sort(key=lambda e: (e["_test_date"], e["_seq"]))
    return events[0]


def interval_gate_ok(student_id):
    pre = earliest_scored_pre_test(student_id)
    if pre is None:
        return False
    elapsed = int((clock() - pre["_test_date"]).total_seconds() // 86400)
    return elapsed >= MIN_POST_TEST_DAY_INTERVAL


# --------------------------------------------------------------------------
# msg_determination
# --------------------------------------------------------------------------

def _in_window(event, period):
    if period is None:
        return True
    start = date_at_midnight(parse_date(period["start_date"]))
    end = date_at_midnight(parse_date(period["end_date"]))
    stamp = event["_test_date"]
    return start <= stamp < end


def msg_determination(student_id, variant, period):
    events = [
        e for e in store.test_events.values()
        if e["student_id"] == student_id
        and e["status"] == "SCORED"
        and e.get("_test_date") is not None
    ]
    pres = [e for e in events if e["purpose"] == "PRE_TEST" and _in_window(e, period)]
    posts = [e for e in events if e["purpose"] == "POST_TEST" and _in_window(e, period)]

    pres.sort(key=lambda e: (e["_test_date"], e["_seq"]))
    pre = pres[0] if pres else None

    best_post = None
    latest_post = None
    if posts:
        best_post = sorted(
            posts, key=lambda e: (-e["efl_level"], e["_test_date"], e["_seq"])
        )[0]
        latest_post = sorted(
            posts, key=lambda e: (e["_test_date"], e["_seq"]), reverse=True
        )[0]

    selected = best_post if variant == "BEST_POST" else latest_post

    entry_level = pre["efl_level"] if pre else None
    post_level = selected["efl_level"] if selected else None
    achieved = bool(pre is not None and selected is not None
                    and selected["efl_level"] > pre["efl_level"])
    levels_gained = None
    if entry_level is not None and post_level is not None:
        levels_gained = post_level - entry_level

    return {
        "student_id": student_id,
        "variant": variant,
        "entry_efl_level": entry_level,
        "post_efl_level": post_level,
        "best_post_scale_score": best_post["scale_score"] if best_post else None,
        "latest_post_scale_score": latest_post["scale_score"] if latest_post else None,
        "levels_gained": levels_gained,
        "msg_achieved": achieved,
    }


# --------------------------------------------------------------------------
# exam_fee_assessment
# --------------------------------------------------------------------------

def prior_scored_attempts(student_id, subtest):
    count = 0
    for reg in store.registrations.values():
        if reg["student_id"] != student_id:
            continue
        if reg["registration_status"] not in ("SCORED", "RESULT_INVALIDATED"):
            continue
        session = store.sessions.get(reg["exam_session_id"])
        if session is not None and session["subtest"] == subtest:
            count += 1
    return count


def discount_tier_pct(total_hours):
    if total_hours < Decimal("12.00"):
        return 0
    if total_hours < Decimal("40.00"):
        return 25
    if total_hours < Decimal("100.00"):
        return 50
    return 75


def exam_fee_assessment(subtest, attempts, granted_format, total_hours, voucher_balance):
    base = SUBTEST_FEE_CENTS[subtest]
    multiplier = RETAKE_BASE ** min(attempts, RETAKE_EXPONENT_CAP)
    gross = round_half_up(Decimal(base) * multiplier)
    surcharge = ALT_FORMAT_SURCHARGE_CENTS if granted_format in SURCHARGED_FORMATS else 0
    billable = gross + surcharge
    discount = floor_pct(billable, discount_tier_pct(total_hours))
    net = billable - discount
    applied = min(net, voucher_balance)
    fee_due = net - applied
    return {
        "prior_scored_attempts": attempts,
        "gross_fee_cents": gross,
        "accommodation_surcharge_cents": surcharge,
        "discount_cents": discount,
        "voucher_applied_cents": applied,
        "fee_due_cents": fee_due,
    }


# --------------------------------------------------------------------------
# transcript_charge
# --------------------------------------------------------------------------

def transcript_charge(copies, delivery):
    base = COPY_FEE_CENTS * copies + (RUSH_FEE_CENTS if delivery == "RUSH" else 0)
    if base < 3000:
        waiver_pct = 0
    elif base < 6000:
        waiver_pct = 10
    else:
        waiver_pct = 20
    waiver = floor_pct(base, waiver_pct)
    net = base - waiver
    if net == 0:
        records_fee = 0
    elif net < 3000:
        records_fee = 200
    else:
        records_fee = 500
    return {
        "base_charge_cents": base,
        "waiver_cents": waiver,
        "state_records_fee_cents": records_fee,
        "total_charge_cents": net + records_fee,
    }


# --------------------------------------------------------------------------
# credential_eligibility
# --------------------------------------------------------------------------

def credential_eligibility(student_id):
    scores = {}
    picks = {}
    for subtest in REQUIRED_SUBTESTS:
        pool = []
        for reg in store.registrations.values():
            if reg["student_id"] != student_id:
                continue
            if reg["registration_status"] != "SCORED":
                continue
            session = store.sessions.get(reg["exam_session_id"])
            if session is None or session["subtest"] != subtest:
                continue
            if reg.get("scale_score") is None:
                continue
            pool.append(reg)
        if pool:
            pool.sort(key=lambda r: (-r["scale_score"], r["_seq"]))
            picks[subtest] = pool[0]
            scores[subtest] = pool[0]["scale_score"]
        else:
            picks[subtest] = None
            scores[subtest] = None

    all_passed = all(
        scores[s] is not None and scores[s] >= PASS_SCORE_PER_SUBTEST
        for s in REQUIRED_SUBTESTS
    )
    composite = sum(scores[s] for s in REQUIRED_SUBTESTS) if all_passed else None
    eligible = bool(all_passed and composite is not None and composite >= COMPOSITE_MIN)
    qualifying = [picks[s]["id"] for s in REQUIRED_SUBTESTS] if all_passed else []
    return {
        "subtest_scores": scores,
        "composite_score": composite,
        "eligible": eligible,
        "qualifying_registration_ids": qualifying,
    }


# --------------------------------------------------------------------------
# funding_allocation
# --------------------------------------------------------------------------

def allocation_candidates(period, variant):
    allowed = ALLOCATION_STATUS_FILTER[variant]
    rows = [
        o for o in store.outcomes.values()
        if o["funding_period_id"] == period["id"]
        and o["allocation_status"] == "UNALLOCATED"
        and o["status"] in allowed
    ]
    rows.sort(key=lambda o: o["_seq"])
    return rows


def allocation_line_cents(period, outcome):
    weight = MEASURE_WEIGHT[outcome["measure_type"]]
    return round_half_up(Decimal(period["rate_cents_per_weight"]) * weight)


def allocation_walk(period, variant):
    """Pure walk: returns (lines, committed_total, deferred_count, total_weight)."""
    running = period["available_cents"]
    committed_total = 0
    deferred = 0
    total_weight = Decimal("0")
    lines = []
    for outcome in allocation_candidates(period, variant):
        total_weight += MEASURE_WEIGHT[outcome["measure_type"]]
        line = allocation_line_cents(period, outcome)
        if line <= running:
            running -= line
            committed_total += line
            lines.append((outcome, line, "COMMITTED"))
        else:
            deferred += 1
            lines.append((outcome, 0, "DEFERRED"))
    return lines, committed_total, deferred, total_weight


# --------------------------------------------------------------------------
# scheduling conflicts
# --------------------------------------------------------------------------

def duration_hours(starts_at, ends_at):
    seconds = Decimal(str((ends_at - starts_at).total_seconds()))
    return (seconds / Decimal("3600"))


def room_occupation_conflict(room, starts_at, ends_at):
    buffer_delta = timedelta(minutes=room["turnaround_buffer_minutes"])
    for session in store.sessions.values():
        if session["testing_room_id"] != room["id"]:
            continue
        if session["status"] not in ("DRAFT", "SCHEDULED", "IN_PROGRESS", "COMPLETED"):
            continue
        existing_start = session["_starts_at"]
        existing_end = session["_ends_at"]
        if (starts_at < existing_end + buffer_delta
                and existing_start < ends_at + buffer_delta):
            return True
    return False


def proctor_interval_conflict(proctor_id, starts_at, ends_at, skip_session_id=None):
    for session in store.sessions.values():
        if session.get("proctor_id") != proctor_id:
            continue
        if session["id"] == skip_session_id:
            continue
        if session["status"] not in ("SCHEDULED", "IN_PROGRESS", "COMPLETED"):
            continue
        if starts_at < session["_ends_at"] and session["_starts_at"] < ends_at:
            return True
    return False


def proctor_daily_projection(proctor_id, candidate, skip_session_id=None):
    target = candidate["_starts_at"].date()
    total = Decimal("0")
    for session in store.sessions.values():
        if session.get("proctor_id") != proctor_id:
            continue
        if session["id"] == skip_session_id:
            continue
        if session["status"] not in ("SCHEDULED", "IN_PROGRESS", "COMPLETED"):
            continue
        if session["_starts_at"].date() != target:
            continue
        total += session["_duration_hours"]
    return total + candidate["_duration_hours"]
