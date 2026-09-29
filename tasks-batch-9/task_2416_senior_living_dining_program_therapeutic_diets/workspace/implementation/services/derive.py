"""Derived fields, denormalized counters and cascade helpers."""
from clock import clock
from constants import TEXTURE_RANK, TRIGGER_PRIORITY
from db import db, snapshot, sort_created, touch, touch_if_changed
from errors import api_error
from shape import parse_date_str
from services import calc


# ------------------------------------------------------------ community
def pending_dietitian_review_count(community_id):
    resident_ids = set(
        r["id"] for r in db.residents.values() if r["community_id"] == community_id
    )
    total = 0
    for order in db.diet_orders.values():
        if order["resident_id"] not in resident_ids:
            continue
        if order["review_status"] not in ("AWAITING_DIETITIAN", "CHANGES_REQUESTED", "REREVIEW_REQUIRED"):
            continue
        if order["clinical_status"] not in ("PENDING_REVIEW", "ACTIVE"):
            continue
        total += 1
    return total


def active_menu_cycle_id(community_id):
    today = clock.iso_date()
    for cycle in db.menu_cycles.values():
        if cycle["community_id"] != community_id:
            continue
        if cycle["status"] != "PUBLISHED":
            continue
        if cycle["effective_start_date"] <= today <= cycle["effective_end_date"]:
            return cycle["id"]
    return None


# ------------------------------------------------------------- lookups
def find_active_order(resident_id):
    for order in db.diet_orders.values():
        if order["resident_id"] == resident_id and order["clinical_status"] == "ACTIVE":
            return order
    return None


def find_verified_order(resident_id):
    order = find_active_order(resident_id)
    if order is not None and order["review_status"] == "APPROVED":
        return order
    return None


def has_open_review(resident_id):
    for review in db.reviews.values():
        if review["resident_id"] == resident_id and review["status"] == "OPEN":
            return review
    return None


def find_published_cycle(community_id, service_date_str):
    for cycle in db.menu_cycles.values():
        if cycle["community_id"] != community_id:
            continue
        if cycle["status"] != "PUBLISHED":
            continue
        if cycle["effective_start_date"] <= service_date_str <= cycle["effective_end_date"]:
            return cycle
    return None


def cycle_items(menu_cycle_id):
    return [i for i in db.menu_items.values() if i["menu_cycle_id"] == menu_cycle_id]


def item_extensions(menu_item_id):
    return [e for e in db.extensions.values() if e["menu_item_id"] == menu_item_id]


# --------------------------------------------------------- recomputes
def recompute_guest_balance(resident):
    if resident is None:
        return
    total = 0
    for ticket in db.tickets.values():
        if ticket["resident_id"] != resident["id"]:
            continue
        if ticket["ticket_type"] not in ("GUEST", "TAKEOUT"):
            continue
        if ticket["status"] not in ("ISSUED", "SERVED", "BILLED"):
            continue
        total += ticket["billed_amount_cents"]
    snap = snapshot(resident, ["guest_meal_charge_balance_cents"])
    resident["guest_meal_charge_balance_cents"] = total
    touch_if_changed(resident, snap)


def recompute_coverage(item):
    required = item["required_therapeutic_codes"]
    if not required:
        status = "NOT_REQUIRED"
    else:
        approved = set(
            e["diet_code"] for e in item_extensions(item["id"])
            if e["review_status"] == "APPROVED"
        )
        status = "COMPLETE" if all(code in approved for code in required) else "INCOMPLETE"
    snap = snapshot(item, ["extension_coverage_status"])
    item["extension_coverage_status"] = status
    touch_if_changed(item, snap)
    return status


def recompute_risk_score(resident):
    snap = snapshot(resident, ["intake_risk_score"])
    resident["intake_risk_score"] = calc.intake_risk_score(
        resident, find_active_order(resident["id"])
    )
    touch_if_changed(resident, snap)


def recompute_resident_metrics(resident):
    """Monitoring cascade hop 1."""
    rolling, baseline_pct, current_weight, avg_intake = calc.resident_weight_trend(resident)
    snap = snapshot(resident, [
        "current_weight_kg", "rolling_30d_weight_change_pct",
        "baseline_weight_change_pct", "avg_intake_pct_7d", "intake_risk_score",
    ])
    resident["current_weight_kg"] = current_weight
    resident["rolling_30d_weight_change_pct"] = rolling
    resident["baseline_weight_change_pct"] = baseline_pct
    resident["avg_intake_pct_7d"] = avg_intake
    resident["intake_risk_score"] = calc.intake_risk_score(
        resident, find_active_order(resident["id"])
    )
    touch_if_changed(resident, snap)


# ------------------------------------------------------- waitlist promotion
def promote_waitlist(venue, service_date, meal_period):
    """PRD 3.5 -- promote at most the single created_at ASC winner."""
    if venue["temp_compliance_posture"] != "COMPLIANT":
        return None
    candidates = [
        r for r in db.reservations.values()
        if r["venue_id"] == venue["id"]
        and r["service_date"] == service_date
        and r["meal_period"] == meal_period
        and r["status"] == "WAITLISTED"
    ]
    if not candidates:
        return None
    candidate = sort_created(candidates)[0]
    committed, _ = calc.venue_committed_seats(venue["id"], service_date, meal_period)
    if committed + candidate["party_size"] > venue["seat_capacity"]:
        return None
    candidate["status"] = "RESERVED"
    candidate["suspension_hold"] = False
    touch(candidate)
    touch(venue)
    return candidate


# ------------------------------------------------------------ tray card
def tray_card_resolution(resident, service_date_str, service_date, meal_period):
    cycle = find_published_cycle(resident["community_id"], service_date_str)
    if cycle is None:
        raise api_error(
            "ERR_NO_PUBLISHED_MENU_CYCLE",
            "No PUBLISHED menu cycle of the resident's community covers %s" % service_date_str,
        )
    start = parse_date_str("effective_start_date", cycle["effective_start_date"])
    span = cycle["week_count"] * 7
    day_index = ((service_date - start).days % span) + 1

    items = [
        i for i in cycle_items(cycle["id"])
        if i["day_index"] == day_index and i["meal_period"] == meal_period
    ]
    items.sort(key=lambda i: i["item_code"])

    active = find_active_order(resident["id"])
    rules = [
        r for r in db.substitution_rules.values()
        if r["resident_id"] == resident["id"] and r["status"] == "ACTIVE"
    ]

    lines = []
    blocked = []
    for item in items:
        candidates = []
        for rule in rules:
            trigger = rule["trigger_type"]
            if trigger == "ALLERGEN":
                if rule["match_value"] in item["allergen_tags"]:
                    candidates.append(rule)
            elif trigger == "TEXTURE":
                if active is not None and (
                    TEXTURE_RANK[item["base_texture"]] < TEXTURE_RANK[active["texture_level"]]
                ):
                    candidates.append(rule)
            else:
                if (
                    rule["match_value"] == item["item_code"]
                    and resident["preference_strictness"] == "STRICT"
                ):
                    candidates.append(rule)
        candidates.sort(key=lambda r: (
            TRIGGER_PRIORITY[r["trigger_type"]], r["priority_rank"], r["created_at"], r["_seq"],
        ))
        winner = candidates[0] if candidates else None

        allergen_rule_values = set(
            r["match_value"] for r in candidates if r["trigger_type"] == "ALLERGEN"
        )
        unresolved_allergen = any(
            tag in resident["allergens"] and tag not in allergen_rule_values
            for tag in item["allergen_tags"]
        )

        extension_pending = False
        if active is not None:
            approved = set(
                e["diet_code"] for e in item_extensions(item["id"])
                if e["review_status"] == "APPROVED"
            )
            for code in active["therapeutic_codes"]:
                if code in item["required_therapeutic_codes"] and code not in approved:
                    extension_pending = True
                    break

        if unresolved_allergen:
            reason = "ALLERGEN_UNRESOLVED"
        elif extension_pending:
            reason = "EXTENSION_PENDING"
        elif winner is None:
            reason = "NONE"
        elif winner["trigger_type"] == "ALLERGEN":
            reason = "ALLERGEN_SUBSTITUTION"
        elif winner["trigger_type"] == "TEXTURE":
            reason = "TEXTURE_SUBSTITUTION"
        else:
            reason = "DISLIKE_SUBSTITUTION"

        if reason in ("ALLERGEN_UNRESOLVED", "EXTENSION_PENDING"):
            blocked.append(item["item_code"])

        lines.append({
            "menu_item_id": item["id"],
            "item_code": item["item_code"],
            "name": item["name"],
            "base_texture": item["base_texture"],
            "served_item_code": item["item_code"] if winner is None else winner["replacement_item_code"],
            "substitution_rule_id": None if winner is None else winner["id"],
            "reason": reason,
        })

    blocked.sort()
    if blocked:
        tray_status = "BLOCKED"
    elif resident["tray_card_state"] == "HOLD_PENDING_REVIEW":
        tray_status = "HOLD_PENDING_REVIEW"
    elif resident["tray_card_state"] == "BLOCKED":
        tray_status = "BLOCKED"
    else:
        tray_status = "CLEAR"

    return {
        "resident_id": resident["id"],
        "menu_cycle_id": cycle["id"],
        "service_date": service_date_str,
        "meal_period": meal_period,
        "day_index": day_index,
        "tray_status": tray_status,
        "lines": lines,
        "blocked_item_codes": blocked,
    }


# ---------------------------------------------------- temperature cascade
def suspend_venue_reservations(venue):
    """PRD 3.7 -- future RESERVED rows become WAITLISTED with suspension_hold."""
    now = clock.now
    for row in db.reservations.values():
        if row["venue_id"] != venue["id"] or row["status"] != "RESERVED":
            continue
        start, _end = calc.reservation_interval(row)
        if start >= now:
            row["status"] = "WAITLISTED"
            row["suspension_hold"] = True
            touch(row)


# --------------------------------------------------------- period closure
def finalized_period_covers(community_id, service_date_str, exclude_id=None):
    for recon in db.reconciliations.values():
        if recon["community_id"] != community_id or recon["status"] != "FINALIZED":
            continue
        if exclude_id is not None and recon["id"] == exclude_id:
            continue
        if recon["period_start_date"] <= service_date_str <= recon["period_end_date"]:
            return recon
    return None


def finalized_period_overlaps(community_id, start_str, end_str):
    for recon in db.reconciliations.values():
        if recon["community_id"] != community_id or recon["status"] != "FINALIZED":
            continue
        if recon["period_start_date"] <= end_str and start_str <= recon["period_end_date"]:
            return recon
    return None
