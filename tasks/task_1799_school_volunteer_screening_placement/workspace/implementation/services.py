"""Business logic: calculations, state transitions, cascades.

All calculations follow the scaffold §1.3 and PRD §2.6, §2.9, §3 exactly.
"""

from datetime import timedelta, date
from decimal import Decimal, ROUND_HALF_UP

import db
import clock


# --- constants per scaffold §1.3 ---
LEVEL_RANK = {"BASIC": 1, "ENHANCED": 2}
VALIDITY_DAYS = {"BASIC": 730, "ENHANCED": 365}
POINTS_MULTIPLIER = {
    "STANDARD": Decimal("1.0"),
    "TUTORING": Decimal("1.5"),
    "MENTORING": Decimal("2.0"),
}
BRONZE_MIN = Decimal("20.0")
SILVER_MIN = Decimal("50.0")
GOLD_MIN = Decimal("100.0")

REQUIRED_LEVEL_FOR_CONTACT = {"SUPERVISED": "BASIC", "UNSUPERVISED": "ENHANCED"}

RESTRICTION_BLOCKS = {
    "TRANSPORT": "NO_TRANSPORT",
    "ONE_ON_ONE": "NO_ONE_ON_ONE",
}


def level_adequate(held_level, required_level) -> bool:
    return LEVEL_RANK[held_level] >= LEVEL_RANK[required_level]


def touch(entity):
    """Refresh updated_at and bump version on a mutable resource."""
    entity["updated_at"] = clock.now_iso()
    entity["version"] = entity.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Volunteer derived-field reconciliation
# ---------------------------------------------------------------------------

def adequate_cleared_checks(volunteer):
    """Checks with status in {CLEARED, CLEARED_WITH_FLAGS} and adequate level."""
    req = volunteer["required_check_level"]
    out = []
    for c in db.background_checks.values():
        if c["volunteer_id"] != volunteer["id"]:
            continue
        if c["status"] not in ("CLEARED", "CLEARED_WITH_FLAGS"):
            continue
        if not level_adequate(c["level"], req):
            continue
        out.append(c)
    return out


def latest_cleared_check(volunteer):
    """The volunteer's latest cleared check (status CLEARED or
    CLEARED_WITH_FLAGS): latest decided_at wins, ties break in favor of the
    later-created check. None when the volunteer holds no cleared check.
    Backs the §2.6 opportunity-gating rule: "the volunteer's latest cleared
    check level must be adequate for the level implied by the opportunity's
    required_contact_type"."""
    cleared = [
        c for c in db.background_checks.values()
        if c["volunteer_id"] == volunteer["id"]
        and c["status"] in ("CLEARED", "CLEARED_WITH_FLAGS")
    ]
    if not cleared:
        return None
    return max(
        cleared,
        key=lambda c: (clock.parse_iso(c["decided_at"]),
                       clock.parse_iso(c["created_at"])),
    )


def recompute_clearance_expires_at(volunteer):
    """Per calculations.clearance_validity_window.

    Among adequate cleared checks: max decided_at, tie-break created_at DESC.
    Selected check's expires_at is the value. If the selected check is EXPIRED
    or the set is empty -> null.
    """
    cands = adequate_cleared_checks(volunteer)
    if not cands:
        volunteer["clearance_expires_at"] = None
        return
    # max decided_at, tie-break created_at DESC (later-created wins)
    def key(c):
        return (clock.parse_iso(c["decided_at"]), clock.parse_iso(c["created_at"]))
    selected = max(cands, key=key)
    if selected["status"] == "EXPIRED":
        volunteer["clearance_expires_at"] = None
        return
    volunteer["clearance_expires_at"] = selected["expires_at"]


def volunteer_hours_entries(volunteer_id):
    return [h for h in db.hour_entries.values() if h["volunteer_id"] == volunteer_id]


def recompute_volunteer_hours(volunteer):
    """Per calculations.volunteer_service_hours — 2 decimal places, half-up."""
    entries = volunteer_hours_entries(volunteer["id"])
    verified = sum(
        (Decimal(str(e["hours"])) for e in entries if e["status"] == "VERIFIED"),
        Decimal("0"),
    )
    provisional = sum(
        (Decimal(str(e["hours"])) for e in entries if e["status"] in ("PENDING", "VERIFIED")),
        Decimal("0"),
    )
    volunteer["total_verified_hours"] = float(verified.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    volunteer["total_provisional_hours"] = float(provisional.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def recompute_recognition_points(volunteer):
    """Per calculations.recognition_points — exact sum of per-entry rounded points."""
    entries = volunteer_hours_entries(volunteer["id"])
    total = sum(
        (Decimal(str(e["points"])) for e in entries if e["status"] == "VERIFIED"),
        Decimal("0"),
    )
    volunteer["recognition_points"] = float(total)


def compute_tier(total_verified_hours) -> str:
    """Per calculations.recognition_tier — inclusive boundaries at 2-decimal precision."""
    th = Decimal(str(total_verified_hours)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if th >= GOLD_MIN:
        return "GOLD"
    if th >= SILVER_MIN:
        return "SILVER"
    if th >= BRONZE_MIN:
        return "BRONZE"
    return "NONE"


TIER_ORDER = {"NONE": 0, "BRONZE": 1, "SILVER": 2, "GOLD": 3}


def auto_award_on_tier_increase(volunteer, old_tier, new_tier):
    """On tier increase, auto-create RecognitionAward source AUTO for the new tier
    when none exists."""
    if TIER_ORDER[new_tier] > TIER_ORDER[old_tier]:
        for t in ("BRONZE", "SILVER", "GOLD"):
            if TIER_ORDER[t] <= TIER_ORDER[old_tier]:
                continue
            if TIER_ORDER[t] > TIER_ORDER[new_tier]:
                continue
            exists = any(
                a["volunteer_id"] == volunteer["id"] and a["tier"] == t
                for a in db.recognition_awards.values()
            )
            if not exists:
                award = {
                    "id": db.new_id(),
                    "created_at": clock.now_iso(),
                    "volunteer_id": volunteer["id"],
                    "tier": t,
                    "source": "AUTO",
                    "note": "",
                }
                db.recognition_awards[award["id"]] = award


def recompute_recognition_tier(volunteer, allow_auto_award=True):
    old = volunteer["recognition_tier"]
    new = compute_tier(volunteer["total_verified_hours"])
    if allow_auto_award and TIER_ORDER[new] > TIER_ORDER[old]:
        auto_award_on_tier_increase(volunteer, old, new)
    volunteer["recognition_tier"] = new


def training_compliance(volunteer) -> bool:
    """Per calculations.training_compliance_check.

    required_modules = modules whose required_contact_types contains the
    volunteer's contact_type. Compliant iff every required module has a
    TrainingRecord with validity_days null OR expires_at strictly > now.
    """
    ct = volunteer["contact_type"]
    required = [
        m for m in db.training_modules.values()
        if ct in m["required_contact_types"]
    ]
    now = clock.now()
    for m in required:
        ok = False
        for r in db.training_records.values():
            if r["volunteer_id"] != volunteer["id"] or r["module_id"] != m["id"]:
                continue
            if m["validity_days"] is None:
                ok = True
                break
            if r["expires_at"] is not None and clock.parse_iso(r["expires_at"]) > now:
                ok = True
                break
        if not ok:
            return False
    return True


def recompute_opportunity_counts(opportunity):
    """Per calculations.opportunity_fill."""
    pls = [p for p in db.placements.values() if p["opportunity_id"] == opportunity["id"]]
    opportunity["committed_count"] = sum(1 for p in pls if p["status"] == "CONFIRMED")
    opportunity["projected_count"] = sum(1 for p in pls if p["status"] in ("REQUESTED", "CONFIRMED"))


def flags_block_category(flags, restricted_category) -> bool:
    """Whether volunteer's restriction flags block the opportunity category."""
    if restricted_category == "NONE":
        return False
    blocker = RESTRICTION_BLOCKS.get(restricted_category)
    return blocker in (flags or [])


def half_open_overlap(a_start, a_end, b_start, b_end) -> bool:
    """Half-open [start, end) overlap. Adjacency (end == start) allowed."""
    return a_start < b_end and b_start < a_end


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def cancel_placement(pl, reason):
    """Cancel a placement with a reason; recompute opportunity counts."""
    pl["status"] = "CANCELLED"
    pl["cancel_reason"] = reason
    touch(pl)
    opp = db.opportunities.get(pl["opportunity_id"])
    if opp is not None:
        recompute_opportunity_counts(opp)
        touch(opp)


def force_close_checkin(ci, reason):
    ci["status"] = "CLOSED"
    ci["checked_out_at"] = clock.now_iso()
    ci["close_reason"] = reason
    touch(ci)


def removal_cascade(volunteer):
    """Full removal cascade: cancel REQUESTED+CONFIRMED placements (SYSTEM_REMOVAL),
    force-close OPEN check-ins (SYSTEM_REMOVAL)."""
    for pl in list(db.placements.values()):
        if pl["volunteer_id"] == volunteer["id"] and pl["status"] in ("REQUESTED", "CONFIRMED"):
            cancel_placement(pl, "SYSTEM_REMOVAL")
    for ci in list(db.check_ins.values()):
        if ci["volunteer_id"] == volunteer["id"] and ci["status"] == "OPEN":
            force_close_checkin(ci, "SYSTEM_REMOVAL")


def suspension_cascade(volunteer):
    """Suspension cascade: cancel only CONFIRMED placements (SYSTEM_SUSPENSION);
    force-close OPEN check-ins (SYSTEM_SUSPENSION). Requests left in place."""
    for pl in list(db.placements.values()):
        if pl["volunteer_id"] == volunteer["id"] and pl["status"] == "CONFIRMED":
            cancel_placement(pl, "SYSTEM_SUSPENSION")
    for ci in list(db.check_ins.values()):
        if ci["volunteer_id"] == volunteer["id"] and ci["status"] == "OPEN":
            force_close_checkin(ci, "SYSTEM_SUSPENSION")


def restriction_cascade(volunteer):
    """After new restriction_flags: cancel CONFIRMED placements whose opportunity's
    restricted_category is now blocked (SYSTEM_RESTRICTION)."""
    for pl in list(db.placements.values()):
        if pl["volunteer_id"] != volunteer["id"] or pl["status"] != "CONFIRMED":
            continue
        opp = db.opportunities.get(pl["opportunity_id"])
        if opp is None:
            continue
        if flags_block_category(volunteer["restriction_flags"], opp["restricted_category"]):
            cancel_placement(pl, "SYSTEM_RESTRICTION")


# ---------------------------------------------------------------------------
# Screening decision matrix (calculations.screening_decision_matrix)
# ---------------------------------------------------------------------------

def adjudicate_check(check, findings):
    """Resolve a PENDING check per the decision matrix and drive volunteer branches.

    Preconditions (status == PENDING) are enforced by the route. Returns nothing;
    mutates check and volunteer.
    """
    volunteer = db.volunteers[check["volunteer_id"]]
    now = clock.now()

    check["findings"] = findings
    check["decided_at"] = clock.now_iso()

    if findings == "DISQUALIFYING":
        check["status"] = "DENIED"
        check["expires_at"] = None
        touch(check)
        # volunteer -> DENIED with full removal cascade
        volunteer["status"] = "DENIED"
        removal_cascade(volunteer)
        touch(volunteer)
        return

    # Non-denied: decision per matrix
    if findings == "NONE":
        check["status"] = "CLEARED"
        new_flags = []
    else:  # MINOR
        check["status"] = "CLEARED_WITH_FLAGS"
        new_flags = ["NO_TRANSPORT"]
        if volunteer["contact_type"] == "UNSUPERVISED":
            new_flags.append("NO_ONE_ON_ONE")
        new_flags = sorted(new_flags)

    check["expires_at"] = clock.to_iso(now + timedelta(days=VALIDITY_DAYS[check["level"]]))
    touch(check)

    adequate = level_adequate(check["level"], volunteer["required_check_level"])
    vstatus = volunteer["status"]

    if vstatus in ("UNDER_SCREENING", "RESCREEN_REQUIRED"):
        if not adequate:
            # stays in current screening state; check recorded but does not
            # advance clearance, flags, or expiry. Still bumps version.
            touch(volunteer)
            return
        # adequate: write flags + expiry, branch by training compliance
        volunteer["restriction_flags"] = new_flags
        recompute_clearance_expires_at(volunteer)
        if training_compliance(volunteer):
            volunteer["status"] = "ACTIVE"
        else:
            volunteer["status"] = "CLEARANCE_GRANTED"
        touch(volunteer)
        return

    if vstatus == "ACTIVE":
        # self-loop: status unchanged, recompute expiry, overwrite flags
        volunteer["restriction_flags"] = new_flags
        recompute_clearance_expires_at(volunteer)
        # new flags may cancel blocked CONFIRMED placements
        restriction_cascade(volunteer)
        touch(volunteer)
        return

    # Other statuses (shouldn't normally reach here given route preconditions)
    touch(volunteer)


# ---------------------------------------------------------------------------
# Badge code (calculations.badge_code_assignment)
# ---------------------------------------------------------------------------

def assign_badge_code(campus, checked_in_at_iso):
    """badge_code = badge_prefix + '-' + zero-padded seq (per campus per UTC day)."""
    day = clock.parse_iso(checked_in_at_iso).date()
    same = [
        c for c in db.check_ins.values()
        if c["campus_id"] == campus["id"]
        and clock.parse_iso(c["checked_in_at"]).date() == day
    ]
    seq = 1 + len(same)
    return f"{campus['badge_prefix']}-{seq:04d}"
