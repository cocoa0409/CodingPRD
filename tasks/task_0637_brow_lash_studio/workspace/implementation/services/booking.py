"""The full appointment booking pipeline (PRD §3.5, §3.6, §3.7).

Used both by POST /appointments (direct booking) and by recurring-schedule
spawn-next. Validation ordering follows PRD §2.10 (priorities 6-14 within the
booking-specific portion; auth/existence are enforced by the route layer first).
"""
from datetime import timedelta

import errors
from clock import clock
from common import round_half_up, stamp_create
from db import store
from services import credits, derive

MIN_FILL_GAP_DAYS = 5
MAX_FILL_WINDOW_DAYS = 21
PEAK_LOAD_THRESHOLD = 3


def _same_utc_date(a, b):
    return a.date() == b.date()


def _overlaps(existing_start, existing_end, new_start, new_end):
    """Half-open overlap (PRD §3.7 / calculations.appointment_overlap):
    existing.start < new.end AND new.start < existing.end.
    Adjacency (existing.end == new.start) is allowed."""
    return existing_start < new_end and new_start < existing_end


def select_tech(studio_id, service_type, start_utc, end_utc):
    """Run the lash-tech selector (PRD §3.7 / calculations.lash_tech_assignment).

    Returns (tech_record, None) on success, or (None, error_id) where error_id
    distinguishes ERR_STATION_NOT_SANITIZED (priority 9) from ERR_NO_TECH_AVAILABLE
    (priority 10). Per PRD §3.5: if the sanitation gate is the reason no tech can
    host, the rejection is ERR_STATION_NOT_SANITIZED; otherwise ERR_NO_TECH_AVAILABLE.
    """
    is_premium = service_type["category"] == "PREMIUM"

    # Base pool: same studio, AVAILABLE, skill-qualified.
    base = []
    for t in store.lash_techs.values():
        if t["studio_id"] != studio_id:
            continue
        if t["status"] != "AVAILABLE":
            continue
        if is_premium and t["skill_level"] < 2:
            continue
        base.append(t)

    # Sanitation gate: station_sanitized_through_utc not null and start <= it
    # (closed interval). Track whether any base candidate failed ONLY on this.
    sanitized = []
    any_sanitation_block = False
    for t in base:
        through = derive.station_sanitized_through_utc(t["id"])
        if through is None or not (start_utc <= through):
            any_sanitation_block = True
            continue
        sanitized.append(t)

    # Chair overlap gate (half-open) on BOOKED appointments of the tech.
    candidates = []
    for t in sanitized:
        conflict = False
        for appt in store.appointments.values():
            if appt["lash_tech_id"] != t["id"]:
                continue
            if appt["status"] != "BOOKED":
                continue
            if _overlaps(appt["start_utc"], appt["end_utc"], start_utc, end_utc):
                conflict = True
                break
        if not conflict:
            candidates.append(t)

    if not candidates:
        # Distinguish the two rejection reasons. If the base pool was non-empty
        # but every member was eliminated by the sanitation gate (and none
        # survived to be overlap-checked), surface ERR_STATION_NOT_SANITIZED.
        if base and not sanitized and any_sanitation_block:
            return None, errors.ERR_STATION_NOT_SANITIZED
        return None, errors.ERR_NO_TECH_AVAILABLE

    # Ranking (ascending; pick smallest):
    #  1. same-UTC-date BOOKED load (fewest first)
    #  2. skill_level (lowest qualifying first)
    #  3. station_number (lowest first)
    #  4. created_at ASC (deterministic tie-break; NEVER id) -> use _seq
    def same_day_load(t):
        n = 0
        for appt in store.appointments.values():
            if appt["lash_tech_id"] != t["id"]:
                continue
            if appt["status"] != "BOOKED":
                continue
            if _same_utc_date(appt["start_utc"], start_utc):
                n += 1
        return n

    candidates.sort(key=lambda t: (
        same_day_load(t),
        t["skill_level"],
        t["station_number"],
        t["_seq"],
    ))
    return candidates[0], None


def check_fill_timing(member, start_utc, schedule_context=False):
    """Enforce the fill-timing window (PRD §3.6). Raises ApiError on violation.

    In schedule (spawn) context the three fill rejections are surfaced as the
    single ERR_FILL_WINDOW_VIOLATION (PRD §3.7); in direct-booking context the
    specific error ids are used (PRD §3.6)."""
    anchor = derive.last_premium_completed_utc(member)
    if anchor is None:
        if schedule_context:
            raise errors.ApiError(errors.ERR_FILL_WINDOW_VIOLATION, 422,
                                  "Fill requires a prior full set.")
        raise errors.ApiError(errors.ERR_FILL_REQUIRES_PRIOR_FULL_SET, 422,
                              "Fill requires a prior completed premium appointment.")
    gap_days = (start_utc - anchor).total_seconds() / 86400.0
    if gap_days < MIN_FILL_GAP_DAYS:
        if schedule_context:
            raise errors.ApiError(errors.ERR_FILL_WINDOW_VIOLATION, 422, "Fill too soon.")
        raise errors.ApiError(errors.ERR_FILL_TOO_SOON, 422, "Fill booked too soon after the anchor.")
    if gap_days > MAX_FILL_WINDOW_DAYS:
        if schedule_context:
            raise errors.ApiError(errors.ERR_FILL_WINDOW_VIOLATION, 422, "Fill window expired.")
        raise errors.ApiError(errors.ERR_FILL_WINDOW_EXPIRED, 422, "Fill window expired.")


def check_patch_test(member, service_type):
    """Patch-test safety gate (PRD §3.3, priority 7). Raises ERR_NO_VALID_PATCH_TEST."""
    if not service_type["requires_patch_test"]:
        return
    now = clock.now()
    for pt in store.consent_patch_tests.values():
        if pt["member_id"] != member["id"]:
            continue
        # Must be VALID status, valid_through_utc at/after clock, consent signed.
        if derive.effective_patch_test_status(pt) != "VALID":
            continue
        if not pt["consent_signed"]:
            continue
        if pt["valid_through_utc"] >= now:
            return
    raise errors.ApiError(errors.ERR_NO_VALID_PATCH_TEST, 422,
                          "Member has no valid, unexpired, signed patch test.")


def run_booking(member, service_type, start_utc, pay_with_credits, membership,
                expected_membership_version, recurring_schedule_id=None,
                schedule_context=False):
    """Execute the booking pipeline gates 6-14 (PRD §2.10 ordering) and create
    the BOOKED appointment. `membership` is the resolved Membership record (or
    None for cash). Returns the created appointment record.

    Caller (route) has already done: auth (1-2), path/body existence (3-4),
    request-shape parse, and resolved member/service_type/membership.
    """
    studio = store.studios[member["studio_id"]]

    # Priority 6 — business referential: retired service type.
    if not service_type["active"]:
        raise errors.ApiError(errors.ERR_SERVICE_TYPE_RETIRED, 409, "Service type is retired.")

    # Priority 7 — patch-test safety.
    check_patch_test(member, service_type)

    # Priority 8 — fill-timing window (only for FILL services).
    if service_type["code"] == "FILL":
        check_fill_timing(member, start_utc, schedule_context=schedule_context)

    end_utc = start_utc + timedelta(minutes=service_type["duration_minutes"])

    # Priority 9 + 10 — sanitation coverage then chair overlap (selector).
    tech, sel_err = select_tech(member["studio_id"], service_type, start_utc, end_utc)
    if tech is None:
        if sel_err == errors.ERR_STATION_NOT_SANITIZED:
            raise errors.ApiError(errors.ERR_STATION_NOT_SANITIZED, 422,
                                  "No technician with a sanitized station can host this appointment.")
        raise errors.ApiError(errors.ERR_NO_TECH_AVAILABLE, 409,
                              "No eligible, non-overlapping technician is available.")

    deposit_cents = 0
    credits_charged = 0

    if pay_with_credits:
        # Priority 11 — membership-bookable state: must be ACTIVE.
        if membership["status"] != "ACTIVE":
            raise errors.ApiError(errors.ERR_MEMBERSHIP_NOT_BOOKABLE, 409,
                                  "Membership is not bookable.")
        # Priority 12 — OCC version check.
        if expected_membership_version != membership["version"]:
            raise errors.ApiError(errors.ERR_STALE_MEMBERSHIP_VERSION, 412,
                                  "Stale membership version.")
        # Priority 13 — sufficient credits (gate BEFORE the consuming append).
        balance = credits.credit_balance(membership["id"])
        required = service_type["credit_cost"]
        if balance < required:
            raise errors.ApiError(errors.ERR_INSUFFICIENT_CREDITS, 402,
                                  "Insufficient membership credits.")
        credits_charged = required
        deposit_cents = 0
    else:
        # Cash booking: deposit derived from base price * deposit_rate_pct.
        deposit_cents = round_half_up(service_type["base_price_cents"] * studio["deposit_rate_pct"])
        credits_charged = 0

    # All gates passed — commit. Create the appointment.
    appt = {
        "studio_id": member["studio_id"],
        "member_id": member["id"],
        "service_type_id": service_type["id"],
        "membership_id": membership["id"] if (pay_with_credits and membership) else None,
        "lash_tech_id": tech["id"],
        "recurring_schedule_id": recurring_schedule_id,
        "start_utc": start_utc,
        "end_utc": end_utc,
        "pay_with_credits": pay_with_credits,
        "deposit_cents": deposit_cents,
        "credits_charged": credits_charged,
        "deposit_forfeited_cents": 0,
        "status": "BOOKED",
    }
    stamp_create(appt)
    store.appointments[appt["id"]] = appt

    if pay_with_credits:
        # Append CONSUME ledger entry and bump membership version.
        credits.append_ledger_entry(membership["id"], -credits_charged, "CONSUME", appt["id"])
        from common import touch
        touch(membership)

    return appt
