"""Cleaner pay (PRD 3.8) and the conserved payout ledger (PRD 2.8)."""

from db import base_fields, db, ordered, touch
from services.money import cents, ceil_int, dec

SIZE_BASE_PAY_CENTS = {"STUDIO": 4550, "ONE_BR": 6175, "TWO_BR": 8325, "THREE_BR_PLUS": 11450}
RUSH_PCT = {"SAME_DAY": dec("0.15"), "OVERNIGHT": dec("0.05"), "VACANT_GAP": dec("0")}
TIGHT_PCT = dec("0.075")
CROSS_ZONE_PCT = dec("0.045")
LINEN_HANDLING_CENTS_PER_UNIT = 120
ON_TIME_BONUS_CENTS = 800
PHOTO_PASS_BONUS_CENTS = 500
LATE_PENALTY_CENTS_PER_BLOCK = 250
LATE_BLOCK_MINUTES = 15
LATE_PENALTY_CAP_PCT = dec("0.30")
PHOTO_REJECT_PENALTY_CENTS = 300
PHOTO_PENALTY_CAP_CENTS = 900

LEDGER_STATUSES = ("PROVISIONAL", "FINAL", "ADJUSTED")


def _provisional_linen_units(prop):
    total = 0
    for line in db.supply_lines.values():
        if line["property_id"] != prop["id"]:
            continue
        if line["category"] != "LINEN" or line["status"] != "ACTIVE":
            continue
        total += line["par_qty"]
    return total


def _final_linen_units(turnover):
    total = 0
    for task in ordered(db.checklist_tasks.values()):
        if task["turnover_id"] != turnover["id"]:
            continue
        if task["category"] != "RESTOCK" or task["status"] != "VERIFIED":
            continue
        for entry in task.get("_restock_entries") or []:
            line = db.supply_lines.get(entry["supply_line_id"])
            if line is not None and line["category"] == "LINEN":
                total += entry["qty_used"]
    return total


def compute_pay(turnover, prop, cleaner, variant, audit_adjustment_cents=0):
    """The seven normative steps of PRD 3.8."""
    # step 1 - base
    size_base = SIZE_BASE_PAY_CENTS[prop["size_tier"]]

    # step 2 - premiums, each rounded independently off the base
    rush = cents(dec(size_base) * RUSH_PCT[turnover["turn_type"]])
    tight = cents(dec(size_base) * TIGHT_PCT) if turnover["is_tight"] else 0
    if cleaner is not None and cleaner["home_zone_code"] != prop["zone_code"]:
        cross_zone = cents(dec(size_base) * CROSS_ZONE_PCT)
    else:
        cross_zone = 0

    # step 3 - linen units: the variant switch
    if variant == "PROVISIONAL":
        linen_units = _provisional_linen_units(prop)
    else:
        linen_units = _final_linen_units(turnover)
    linen_adder = LINEN_HANDLING_CENTS_PER_UNIT * linen_units

    # step 4 - gross (the cap base for the late penalty)
    gross = size_base + rush + tight + cross_zone + linen_adder

    # step 5 - penalties, capped against the gross computed in step 4
    late_minutes = 0 if variant == "PROVISIONAL" else turnover["late_minutes"]
    raw_late_penalty = LATE_PENALTY_CENTS_PER_BLOCK * ceil_int(
        dec(late_minutes) / dec(LATE_BLOCK_MINUTES))
    late_penalty = min(raw_late_penalty, cents(LATE_PENALTY_CAP_PCT * dec(gross)))
    photo_penalty = min(PHOTO_REJECT_PENALTY_CENTS * turnover["rejected_review_count"],
                        PHOTO_PENALTY_CAP_CENTS)
    penalty = late_penalty + photo_penalty

    # step 6 - bonuses
    on_time_bonus = ON_TIME_BONUS_CENTS if late_minutes == 0 else 0
    photo_pass_bonus = PHOTO_PASS_BONUS_CENTS if turnover["rejected_review_count"] == 0 else 0
    bonus = on_time_bonus + photo_pass_bonus

    # step 7 - net
    net = gross + bonus - penalty + audit_adjustment_cents

    return {
        "variant": variant,
        "size_base_cents": size_base,
        "rush_premium_cents": rush,
        "tight_window_premium_cents": tight,
        "cross_zone_premium_cents": cross_zone,
        "linen_units": linen_units,
        "linen_adder_cents": linen_adder,
        "gross_cents": gross,
        "on_time_bonus_cents": on_time_bonus,
        "photo_pass_bonus_cents": photo_pass_bonus,
        "bonus_cents": bonus,
        "late_minutes": late_minutes,
        "late_penalty_cents": late_penalty,
        "photo_penalty_cents": photo_penalty,
        "audit_adjustment_cents": audit_adjustment_cents,
        "penalty_cents": penalty,
        "net_cents": net,
    }


def create_pay_line(assignment, turnover, prop, cleaner):
    numbers = compute_pay(turnover, prop, cleaner, "PROVISIONAL")
    pay_line = base_fields()
    pay_line.update({
        "assignment_id": assignment["id"],
        "cleaner_id": cleaner["id"],
        "turnover_id": turnover["id"],
        "status": "PROVISIONAL",
    })
    pay_line.update(numbers)
    db.pay_lines[pay_line["id"]] = pay_line
    return pay_line


def turnover_pay_lines(turnover_id):
    return [p for p in ordered(db.pay_lines.values()) if p["turnover_id"] == turnover_id]


def find_pay_line(turnover_id, statuses):
    for pay_line in turnover_pay_lines(turnover_id):
        if pay_line["status"] in statuses:
            return pay_line
    return None


def recompute_pay_line(pay_line, turnover, prop, cleaner, variant):
    numbers = compute_pay(turnover, prop, cleaner, variant,
                          pay_line.get("audit_adjustment_cents", 0))
    pay_line.update(numbers)
    touch(pay_line)
    return pay_line


def sync_cleaner(cleaner, force=False):
    """Re-establish the cleaner's derived figures and touch it at most once.

    pending_payout_cents is a conserved ledger recomputed from the pay-line set
    (PRD 2.8), never nudged; completed_turnover_count and decline_count are
    likewise counted off the assignment set.
    """
    if cleaner is None:
        return
    changed = bool(force)

    total = 0
    for pay_line in db.pay_lines.values():
        if pay_line["cleaner_id"] == cleaner["id"] and pay_line["status"] in LEDGER_STATUSES:
            total += pay_line["net_cents"]
    if cleaner["pending_payout_cents"] != total:
        cleaner["pending_payout_cents"] = total
        changed = True

    completed = 0
    declined = 0
    for assignment in db.assignments.values():
        if assignment["cleaner_id"] != cleaner["id"]:
            continue
        if assignment["status"] == "COMPLETED":
            completed += 1
        elif assignment["status"] == "DECLINED":
            declined += 1
    if cleaner["completed_turnover_count"] != completed:
        cleaner["completed_turnover_count"] = completed
        changed = True
    if cleaner["decline_count"] != declined:
        cleaner["decline_count"] = declined
        changed = True

    if changed:
        touch(cleaner)


def sync_cleaners(cleaner_ids):
    for cleaner_id in sorted(set(cleaner_ids)):
        sync_cleaner(db.cleaners.get(cleaner_id))


def sync_open_issue_count(prop, force=False):
    if prop is None:
        return
    changed = bool(force)
    count = 0
    for issue in db.issue_reports.values():
        if issue["property_id"] == prop["id"] and issue["status"] != "RESOLVED":
            count += 1
    if prop["open_issue_count"] != count:
        prop["open_issue_count"] = count
        changed = True
    if changed:
        touch(prop)
