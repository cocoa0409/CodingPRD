"""Derivation cascades: visit -> location -> franchisee -> brand (PRD 2.7),
the append-only escalation ledger (PRD 2.11) and the brand risk index.
"""

from decimal import Decimal

import db
from common import dec, q2, set_if_changed, touch
from services import calc

OPEN_ACTION_STATUSES = ("ASSIGNED", "SUBMITTED", "REJECTED", "OVERDUE")
OPEN_CRITICAL_STATUSES = ("ASSIGNED", "SUBMITTED", "REJECTED", "OVERDUE", "ESCALATED")
POSITIVE_EVENTS = ("REPEAT_CRITICAL", "OVERDUE_CRITICAL")


# --------------------------------------------------------------------------
# Escalation ledger
# --------------------------------------------------------------------------

def _ledger_of(location_id):
    events = [
        e for e in db.store.escalation_events.values()
        if e["location_id"] == location_id
    ]
    events.sort(key=lambda e: (e["occurred_at"], e["created_at"], e["_seq"]))
    return events


def project_escalation(location):
    """Re-run the ledger projection: escalation_level then agreement status."""
    total = 0
    for event in _ledger_of(location["id"]):
        total += event["level_delta"]
    level = total if total > 0 else 0

    if level == 0:
        status = "GOOD_STANDING"
    elif level == 1:
        status = "NOTICE_OF_DEFAULT"
    elif level == 2:
        status = "CURE_PERIOD"
    else:
        status = "TERMINATION_RECOMMENDED"

    previous_status = location["franchise_agreement_status"]
    set_if_changed(location, "escalation_level", level)
    set_if_changed(location, "franchise_agreement_status", status)

    if status == "CURE_PERIOD":
        if previous_status != "CURE_PERIOD":
            set_if_changed(location, "cure_period_started_at", db.store.clock)
    else:
        set_if_changed(location, "cure_period_started_at", None)


def append_escalation_event(location, event_type, corrective_action_id=None, audit_visit_id=None):
    event = db.new_record(light=True)
    event.update({
        "location_id": location["id"],
        "corrective_action_id": corrective_action_id,
        "audit_visit_id": audit_visit_id,
        "event_type": event_type,
        "level_delta": 1 if event_type in POSITIVE_EVENTS else -1,
        "occurred_at": db.store.clock,
        "resulting_escalation_level": location["escalation_level"],
        "resulting_agreement_status": location["franchise_agreement_status"],
    })
    db.store.escalation_events[event["id"]] = event
    project_escalation(location)
    event["resulting_escalation_level"] = location["escalation_level"]
    event["resulting_agreement_status"] = location["franchise_agreement_status"]
    return event


def repeat_critical_events_of_visit(visit_id):
    return [
        e for e in db.store.escalation_events.values()
        if e["audit_visit_id"] == visit_id and e["event_type"] == "REPEAT_CRITICAL"
    ]


# --------------------------------------------------------------------------
# Counters
# --------------------------------------------------------------------------

def corrective_actions_of_location(location_id):
    return [
        ca for ca in db.store.corrective_actions.values()
        if ca["location_id"] == location_id
    ]


def recompute_open_action_count(location):
    count = 0
    for action in corrective_actions_of_location(location["id"]):
        if action["status"] in OPEN_ACTION_STATUSES:
            count += 1
    set_if_changed(location, "open_corrective_action_count", count)
    return count


def recompute_evidence_photo_count(action):
    count = 0
    for photo in db.store.evidence_photos.values():
        if photo["corrective_action_id"] == action["id"]:
            count += 1
    set_if_changed(action, "evidence_photo_count", count)
    return count


def recompute_auditor_finalized_count(auditor):
    count = 0
    for visit in db.store.audit_visits.values():
        if visit["auditor_id"] == auditor["id"] and visit["status"] == "FINALIZED":
            count += 1
    set_if_changed(auditor, "finalized_visit_count", count)
    return count


def recompute_rubric_version_counts(rubric_version):
    items = calc.rubric_items_of(rubric_version["id"])
    set_if_changed(rubric_version, "item_count", len(items))
    set_if_changed(
        rubric_version,
        "critical_item_count",
        sum(1 for item in items if item["is_critical"]),
    )


def locations_of_franchisee(franchisee_id):
    return [
        loc for loc in db.store.locations.values()
        if loc["franchisee_id"] == franchisee_id
    ]


def locations_of_brand(brand_id):
    return [
        loc for loc in db.store.locations.values()
        if loc["brand_id"] == brand_id
    ]


def recompute_franchisee(franchisee):
    locations = locations_of_franchisee(franchisee["id"])
    open_default = sum(
        1 for loc in locations
        if loc["franchise_agreement_status"] != "GOOD_STANDING"
    )
    termination = any(
        loc["franchise_agreement_status"] == "TERMINATION_RECOMMENDED"
        for loc in locations
    )
    set_if_changed(franchisee, "open_default_location_count", open_default)
    set_if_changed(franchisee, "termination_recommended", termination)


def recompute_brand_counts(brand):
    locations = locations_of_brand(brand["id"])
    set_if_changed(brand, "location_count", len(locations))
    set_if_changed(
        brand,
        "default_location_count",
        sum(1 for loc in locations if loc["franchise_agreement_status"] != "GOOD_STANDING"),
    )


# --------------------------------------------------------------------------
# brand_risk_index
# --------------------------------------------------------------------------

def brand_risk_components(brand):
    locations = locations_of_brand(brand["id"])
    rated = [loc for loc in locations if loc["latest_grade"] is not None]

    open_critical = 0
    location_ids = set(loc["id"] for loc in locations)
    for action in db.store.corrective_actions.values():
        if action["location_id"] in location_ids \
                and action["severity"] == "CRITICAL" \
                and action["status"] in OPEN_CRITICAL_STATUSES:
            open_critical += 1

    default_count = brand["default_location_count"]
    fail_applied = any(loc["latest_grade"] == "FAIL" for loc in rated)

    if not rated:
        return {
            "brand_risk_index": Decimal("0.00"),
            "brand_risk_tier": "BASELINE",
            "average_standing_score": Decimal("0.00"),
            "rated_location_count": 0,
            "open_critical_action_count": open_critical,
            "default_location_count": default_count,
            "fail_grade_surcharge_applied": False,
        }

    total = Decimal(0)
    for loc in rated:
        total += dec(loc["standing_score"])
    average = q2(total / Decimal(len(rated)))
    deficit = Decimal("100.00") - average

    critical_part = Decimal("6.00") * Decimal(open_critical)
    if critical_part > Decimal("40.00"):
        critical_part = Decimal("40.00")
    default_part = Decimal("10.00") * Decimal(default_count)
    if default_part > Decimal("30.00"):
        default_part = Decimal("30.00")
    fail_part = Decimal("15.00") if fail_applied else Decimal("0.00")

    index = q2(Decimal("0.60") * deficit + critical_part + default_part + fail_part)
    if index > Decimal("100.00"):
        index = Decimal("100.00")

    if index >= Decimal("60.00"):
        tier = "SEVERE"
    elif index >= Decimal("35.00"):
        tier = "ELEVATED"
    else:
        tier = "BASELINE"

    return {
        "brand_risk_index": index,
        "brand_risk_tier": tier,
        "average_standing_score": average,
        "rated_location_count": len(rated),
        "open_critical_action_count": open_critical,
        "default_location_count": default_count,
        "fail_grade_surcharge_applied": fail_applied,
    }


def recompute_brand_risk(brand):
    components = brand_risk_components(brand)
    set_if_changed(brand, "brand_risk_index", components["brand_risk_index"])
    set_if_changed(brand, "brand_risk_tier", components["brand_risk_tier"])
    return components


# --------------------------------------------------------------------------
# Composite cascades
# --------------------------------------------------------------------------

def cascade_location(location, recompute_repeat=True, recompute_standing=True):
    """Location -> franchisee -> brand, in the pinned outward order."""
    recompute_open_action_count(location)
    if recompute_repeat:
        calc.recompute_repeat_violation_count(location)
    if recompute_standing:
        calc.recompute_standing_score(location)
    franchisee = db.store.franchisees.get(location["franchisee_id"])
    if franchisee is not None:
        recompute_franchisee(franchisee)
    brand = db.store.brands.get(location["brand_id"])
    if brand is not None:
        recompute_brand_counts(brand)
        recompute_brand_risk(brand)


# --------------------------------------------------------------------------
# Corrective action reversals
# --------------------------------------------------------------------------

def void_corrective_action(action, location):
    """Drive a non-terminal corrective action to VOIDED as a system cascade."""
    if action["status"] in ("VERIFIED", "VOIDED"):
        return
    was_escalated = action["status"] == "ESCALATED"
    action["status"] = "VOIDED"
    touch(action)
    if was_escalated:
        # The escalation had already been ledgered: compensate it.
        append_escalation_event(
            location,
            "VOID_REVERSAL",
            corrective_action_id=action["id"],
            audit_visit_id=None,
        )
    recompute_open_action_count(location)


def escalate_corrective_action(action, location):
    """OVERDUE -> ESCALATED system cascade for a CRITICAL action."""
    action["status"] = "ESCALATED"
    action["escalated_at"] = db.store.clock
    touch(action)
    recompute_open_action_count(location)
    append_escalation_event(
        location,
        "OVERDUE_CRITICAL",
        corrective_action_id=action["id"],
        audit_visit_id=None,
    )


# --------------------------------------------------------------------------
# Auditor suspension cascade
# --------------------------------------------------------------------------

def suspend_auditor(auditor, reason):
    auditor["status"] = "SUSPENDED"
    auditor["suspension_reason"] = reason
    touch(auditor)
    for visit in sorted(db.store.audit_visits.values(), key=db.sort_key):
        if visit["auditor_id"] == auditor["id"] and visit["status"] == "IN_PROGRESS":
            visit["status"] = "VOIDED"
            visit["void_reason"] = "AUDITOR_SUSPENDED"
            touch(visit)


def apply_rolling_reliability(auditor):
    score = calc.rolling_reliability(auditor["id"])
    set_if_changed(auditor, "reliability_score", score)
    if auditor["status"] == "CERTIFIED" and score < calc.SUSPENSION_FLOOR:
        suspend_auditor(auditor, "RELIABILITY_BELOW_FLOOR")
    return score
