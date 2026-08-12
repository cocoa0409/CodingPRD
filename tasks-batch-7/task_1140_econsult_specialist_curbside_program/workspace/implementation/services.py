"""Business logic: routing selector, quality scoring, ledger, sweeps (PRD section 3)."""

import uuid
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import clock
import db
from errors import ApiError, ERR_NOT_FOUND

MAX_OPEN_CONSULTS = 5
MAX_CLARIFICATION_ROUNDS = 2
EXPIRY_GRACE_HOURS = 24
QUEUE_TTL_HOURS = 72
CONVERSION_BUFFER_MINUTES = 30

TERMINAL_CONSULT_STATES = ("CLOSED", "EXPIRED", "CANCELLED")

RANKING_BASIS = "open_consult_count ASC, quality_score_bps DESC, created_at ASC"
RANKING_BASIS_SUSPENDED = "SPECIALIST_SUSPENDED"

# Quality band constants (PRD section 3.6)
BAND_EXCELLENT_BPS = 12000   # >= 9000
BAND_STANDARD_BPS = 10000    # 7500..8999
BAND_REDUCED_BPS = 8000      # 5000..7499
BAND_MINIMAL_BPS = 5000      # < 5000

# Standing thresholds (PRD section 3.7)
DEFAULT_REVIEW_COMPONENT_BPS = 8500
DEFAULT_TIMELINESS_BPS = 10000
DEMOTE_BELOW_BPS = 7000
RECOVER_AT_BPS = 7500
SUSPEND_BELOW_BPS = 5000
REBUKE_SUSPEND_COUNT = 2


def rhu(numerator, denominator):
    """Round-half-up integer division for non-negative integer inputs."""
    return int((Decimal(numerator) / Decimal(denominator)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))


def new_id():
    return str(uuid.uuid4())


def base_record():
    """Common system fields (PRD 2.4): id, created_at, updated_at, version."""
    moment = clock.now()
    return {
        "id": new_id(),
        "created_at": moment,
        "updated_at": moment,
        "version": 1,
        "_seq": db.next_seq(),
    }


def append_only_record():
    """ClarificationMessage / RoutingDecision carry only id + created_at (PRD 2.4)."""
    return {"id": new_id(), "created_at": clock.now(), "_seq": db.next_seq()}


def touch(rec):
    rec["updated_at"] = clock.now()
    rec["version"] += 1


# ---------------------------------------------------------------------------
# Existence helpers (ERR_NOT_FOUND, validated left to right by callers)
# ---------------------------------------------------------------------------

def _get(table, rid, label):
    rec = db.store[table].get(rid)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, 404, "%s not found: %s" % (label, rid))
    return rec


def get_track(rid):
    return _get("specialty_tracks", rid, "Specialty track")


def get_provider(rid):
    return _get("referring_providers", rid, "Referring provider")


def get_specialist(rid):
    return _get("specialists", rid, "Specialist")


def get_membership(rid):
    return _get("panel_memberships", rid, "Panel membership")


def get_consult(rid):
    return _get("consult_requests", rid, "Consult request")


def get_response(rid):
    return _get("consult_responses", rid, "Consult response")


def get_review(rid):
    return _get("quality_reviews", rid, "Quality review")


def get_conversion(rid):
    return _get("in_person_conversions", rid, "In-person conversion")


def get_claim(rid):
    return _get("billing_claims", rid, "Billing claim")


def get_measurement(rid):
    return _get("avoided_visit_measurements", rid, "Avoided-visit measurement")


def get_window(rid):
    return _get("availability_windows", rid, "Availability window")


def get_entry(rid):
    return _get("compensation_entries", rid, "Compensation entry")


def response_for_consult(consult_id):
    for resp in db.store["consult_responses"].values():
        if resp["consult_id"] == consult_id:
            return resp
    return None


# ---------------------------------------------------------------------------
# Routing selector (PRD 3.2)
# ---------------------------------------------------------------------------

def eligible_pool(consult):
    moment = clock.now()
    pool = []
    for membership in db.store["panel_memberships"].values():
        if membership["specialty_track_id"] != consult["specialty_track_id"]:
            continue
        if membership["standing"] != "GOOD_STANDING":
            continue
        if not membership["is_accepting"]:
            continue
        if membership["open_consult_count"] >= MAX_OPEN_CONSULTS:
            continue
        covered = any(
            w["status"] == "ACTIVE"
            and w["window_start"] <= moment < w["window_end"]
            for w in db.store["availability_windows"].values()
            if w["membership_id"] == membership["id"]
        )
        if not covered:
            continue
        pool.append(membership)
    pool.sort(key=lambda m: (
        m["open_consult_count"],
        -m["quality_score_bps"],
        m["created_at"],
        m["_seq"],
    ))
    return pool


def append_decision(consult_id, outcome, candidate_count, selected_membership_id, basis):
    rec = append_only_record()
    rec.update({
        "consult_id": consult_id,
        "outcome": outcome,
        "candidate_count": candidate_count,
        "selected_membership_id": selected_membership_id,
        "ranking_basis": basis,
    })
    db.store["routing_decisions"][rec["id"]] = rec
    return rec


def assign_consult(consult, pool):
    """Full assignment side effects of PRD 3.2 (selector, decision, counters)."""
    winner = pool[0]
    consult["assigned_specialist_id"] = winner["specialist_id"]
    consult["assigned_membership_id"] = winner["id"]
    track = db.store["specialty_tracks"][consult["specialty_track_id"]]
    hours = (track["urgent_target_hours"] if consult["urgency"] == "URGENT"
             else track["response_time_target_hours"])
    consult["sla_due_at"] = consult["created_at"] + timedelta(hours=hours)
    consult["status"] = "ASSIGNED"
    append_decision(consult["id"], "ASSIGNED", len(pool), winner["id"], RANKING_BASIS)
    winner["open_consult_count"] += 1
    touch(winner)


def route_consult(consult):
    """Inline routing pass at consult creation: ASSIGNED or QUEUED + version bump."""
    pool = eligible_pool(consult)
    if pool:
        assign_consult(consult, pool)
    else:
        consult["status"] = "QUEUED"
        append_decision(consult["id"], "QUEUED", 0, None, RANKING_BASIS)
    touch(consult)


# ---------------------------------------------------------------------------
# Compensation ledger (PRD 2.6)
# ---------------------------------------------------------------------------

def append_entry(membership_id, consult_id, entry_type, amount_cents):
    rec = base_record()
    rec.update({
        "membership_id": membership_id,
        "consult_id": consult_id,
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "posture": "PROVISIONAL",
        "period_key": clock.now().strftime("%Y-%m"),
    })
    db.store["compensation_entries"][rec["id"]] = rec
    return rec


def reverse_provisional_entries(consult_id):
    for entry in db.store["compensation_entries"].values():
        if entry["consult_id"] == consult_id and entry["posture"] == "PROVISIONAL":
            entry["posture"] = "REVERSED"
            touch(entry)
            membership = db.store["panel_memberships"].get(entry["membership_id"])
            if membership is not None:
                membership["provisional_balance_cents"] -= entry["amount_cents"]
                touch(membership)


def provisional_response_base(track, disposition):
    if disposition == "CONVERT_TO_VISIT":
        return track["conversion_response_fee_cents"]
    return track["base_response_fee_cents"]


def final_response_amount(track, membership, resp):
    """Final-variant compensation (PRD 3.6): band x base minus late penalty, floored at 0."""
    base = provisional_response_base(track, resp["disposition"])
    score = membership["quality_score_bps"]
    if score >= 9000:
        band = BAND_EXCELLENT_BPS
    elif score >= 7500:
        band = BAND_STANDARD_BPS
    elif score >= 5000:
        band = BAND_REDUCED_BPS
    else:
        band = BAND_MINIMAL_BPS
    gross = rhu(base * band, 10000)
    penalty = 0 if resp["on_time"] else track["late_penalty_cents"]
    return max(0, gross - penalty)


# ---------------------------------------------------------------------------
# Quality scoring and standing (PRD 3.7) — pinned evaluation order
# ---------------------------------------------------------------------------

def recompute_quality(membership):
    responded = membership["responded_count"]
    if responded == 0:
        timeliness = DEFAULT_TIMELINESS_BPS
    else:
        timeliness = rhu(10000 * membership["on_time_count"], responded)
    reviews = membership["reviews_count"]
    if reviews == 0:
        review_component = DEFAULT_REVIEW_COMPONENT_BPS
    else:
        review_component = rhu(membership["reviews_score_sum"], reviews)
    score = rhu(6 * review_component + 4 * timeliness, 10)
    membership["quality_score_bps"] = score

    standing = membership["standing"]
    new_standing = standing
    if standing == "GOOD_STANDING":
        if score < SUSPEND_BELOW_BPS:
            new_standing = "SUSPENDED"
        elif score < DEMOTE_BELOW_BPS:
            new_standing = "PROBATION"
    elif standing == "PROBATION":
        if score < SUSPEND_BELOW_BPS or membership["rebuke_count"] >= REBUKE_SUSPEND_COUNT:
            new_standing = "SUSPENDED"
        elif score >= RECOVER_AT_BPS:
            new_standing = "GOOD_STANDING"
    # SUSPENDED: no automatic transition

    if new_standing != standing:
        membership["standing"] = new_standing
        if new_standing == "SUSPENDED":
            membership["is_accepting"] = False
            suspend_cascade(membership)
    touch(membership)


def suspend_cascade(membership):
    """Re-queue every ASSIGNED / CLARIFICATION_REQUESTED consult of the membership."""
    targets = [
        c for c in db.store["consult_requests"].values()
        if c["assigned_membership_id"] == membership["id"]
        and c["status"] in ("ASSIGNED", "CLARIFICATION_REQUESTED")
    ]
    targets.sort(key=lambda c: (c["created_at"], c["_seq"]))
    for consult in targets:
        consult["assigned_specialist_id"] = None
        consult["assigned_membership_id"] = None
        consult["status"] = "QUEUED"
        membership["open_consult_count"] -= 1
        append_decision(consult["id"], "QUEUED", 0, None, RANKING_BASIS_SUSPENDED)
        touch(consult)


# ---------------------------------------------------------------------------
# Expiry sweep (PRD 2.5 / 3.3)
# ---------------------------------------------------------------------------

def run_expiry_sweep():
    moment = clock.now()
    consults = sorted(
        db.store["consult_requests"].values(),
        key=lambda c: (c["created_at"], c["_seq"]),
    )
    for consult in consults:
        status = consult["status"]
        if status in ("ASSIGNED", "CLARIFICATION_REQUESTED"):
            due = consult["sla_due_at"]
            if due is not None and moment > due + timedelta(hours=EXPIRY_GRACE_HOURS):
                consult["status"] = "EXPIRED"
                consult["sla_breached"] = True
                membership = db.store["panel_memberships"].get(consult["assigned_membership_id"])
                if membership is not None:
                    membership["expired_count"] += 1
                    membership["open_consult_count"] -= 1
                    touch(membership)
                if status == "CLARIFICATION_REQUESTED":
                    reverse_provisional_entries(consult["id"])
                consult["billing_status"] = "VOID"
                touch(consult)
        elif status == "QUEUED":
            if moment > consult["created_at"] + timedelta(hours=QUEUE_TTL_HOURS):
                consult["status"] = "EXPIRED"
                consult["billing_status"] = "VOID"
                touch(consult)


# ---------------------------------------------------------------------------
# Billing claim amount (PRD 3.9) — pinned rounding order
# ---------------------------------------------------------------------------

def claim_amount_and_code(consult, track, resp):
    urgency_bps = 15000 if consult["urgency"] == "URGENT" else 10000
    professional = rhu(track["base_response_fee_cents"] * urgency_bps, 10000)
    has_live_conversion = any(
        conv["consult_id"] == consult["id"] and conv["status"] in ("SCHEDULED", "COMPLETED")
        for conv in db.store["in_person_conversions"].values()
    )
    addon_pct_bps = 1000 if has_live_conversion else 500
    addon = rhu(professional * addon_pct_bps, 10000)
    amount = professional + addon
    code = "ECONSULT-%s-%s" % (
        "URG" if consult["urgency"] == "URGENT" else "RUT",
        "CONV" if resp["disposition"] == "CONVERT_TO_VISIT" else "ANSW",
    )
    return amount, code


# ---------------------------------------------------------------------------
# Avoided-visit measurement variants (PRD 3.9)
# ---------------------------------------------------------------------------

def period_bounds(period_key):
    year = int(period_key[0:4])
    month = int(period_key[5:7])
    from datetime import datetime, timezone
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return start, end


def measurement_counts(track_id, period_key):
    start, end = period_bounds(period_key)
    responded = []
    for consult in db.store["consult_requests"].values():
        if consult["specialty_track_id"] != track_id:
            continue
        if not (start <= consult["created_at"] < end):
            continue
        if consult["status"] in ("ANSWERED", "CLOSED"):
            responded.append(consult)

    def live_conversion(consult_id):
        return any(
            conv["consult_id"] == consult_id and conv["status"] in ("SCHEDULED", "COMPLETED")
            for conv in db.store["in_person_conversions"].values()
        )

    def any_conversion(consult_id):
        return any(
            conv["consult_id"] == consult_id
            for conv in db.store["in_person_conversions"].values()
        )

    responded_count = len(responded)
    conversions_count = sum(1 for c in responded if live_conversion(c["id"]))
    attributed = responded_count - conversions_count

    conservative = 0
    for consult in responded:
        if consult["status"] != "CLOSED":
            continue
        resp = response_for_consult(consult["id"])
        if resp is None or resp["disposition"] != "MANAGE_IN_PRIMARY_CARE":
            continue
        if any_conversion(consult["id"]):
            continue
        conservative += 1

    return {
        "responded_count": responded_count,
        "conversions_count": conversions_count,
        "avoided_attributed_count": attributed,
        "avoided_conservative_count": conservative,
    }
