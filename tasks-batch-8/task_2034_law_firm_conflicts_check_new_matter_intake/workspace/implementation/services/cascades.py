"""Cross-aggregate cascades: lateral activation + auto-walls (PRD 3.2),
waiver approve/revoke chains (PRD 3.6), retainer deposit stand-up (PRD 3.7)."""

import db
from db import stamp_new, bump, now_iso
from services.clearance import recompute_clearance
from services import matching, money


def maybe_activate_lateral(attorney_id):
    """After a lateral-sweep hit review: when zero PENDING sweep hits remain
    for the attorney, flip LATERAL_PENDING -> ACTIVE (version +1) and run the
    imputation wall cascade over each CONFIRMED sweep hit's matter."""
    attorney = db.store.attorneys.get(attorney_id)
    if attorney is None or attorney["status"] != "LATERAL_PENDING":
        return
    if matching.pending_sweep_hits(attorney_id) != 0:
        return
    attorney["status"] = "ACTIVE"
    bump(attorney)

    # Distinct matters carrying a CONFIRMED sweep hit of this attorney,
    # in matter creation order (dicts preserve insertion order).
    seen = set()
    matters = []
    for h in db.store.conflict_hits.values():
        if (h["lateral_attorney_id"] == attorney_id
                and h["review_status"] == "CONFIRMED"
                and h["matched_matter_id"] not in seen):
            seen.add(h["matched_matter_id"])
            matters.append(h["matched_matter_id"])
    for matter_id in matters:
        active_wall = None
        for w in db.store.ethical_walls.values():
            if w["matter_id"] == matter_id and w["status"] == "ACTIVE":
                active_wall = w
                break
        if active_wall is not None:
            if attorney_id not in active_wall["excluded_attorney_ids"]:
                active_wall["excluded_attorney_ids"].append(attorney_id)
                bump(active_wall)
        else:
            wall = stamp_new({
                "matter_id": matter_id,
                "reason": "LATERAL_IMPUTATION",
                "memo": "",
                "excluded_attorney_ids": [attorney_id],
                "status": "ACTIVE",
                "lifted_at": None,
            })
            db.store.ethical_walls[wall["id"]] = wall


def waiver_approved(waiver):
    """APPROVE cascade hop 1: referenced hit CONFIRMED -> WAIVED; hop 2:
    matter clearance recompute (may yield WAIVED)."""
    hit = db.store.conflict_hits.get(waiver["conflict_hit_id"])
    if hit is not None and hit["review_status"] == "CONFIRMED":
        hit["review_status"] = "WAIVED"
        bump(hit)
    matter = db.store.matters.get(waiver["matter_id"])
    if matter is not None:
        recompute_clearance(matter)


def waiver_revoked(waiver, prior_status):
    """REVOKE cascade. From CONSENTED: no hit change. From APPROVED: hit
    WAIVED -> CONFIRMED (hop 1), clearance recompute -> BLOCKED (hop 2),
    every ISSUED letter of the matter -> VOID (hop 3; DRAFT/COUNTERSIGNED
    letters unaffected)."""
    if prior_status != "APPROVED":
        return
    hit = db.store.conflict_hits.get(waiver["conflict_hit_id"])
    if hit is not None and hit["review_status"] == "WAIVED":
        hit["review_status"] = "CONFIRMED"
        bump(hit)
    matter = db.store.matters.get(waiver["matter_id"])
    if matter is not None:
        recompute_clearance(matter)
    for letter in db.store.engagement_letters.values():
        if letter["matter_id"] == waiver["matter_id"] and letter["status"] == "ISSUED":
            letter["status"] = "VOID"
            bump(letter)


def stand_up_deposit(matter):
    """Letter ISSUE side effect: create the matter's single RetainerDeposit
    if none exists (required_cents per retainer_required_amount, PENDING);
    otherwise recompute its required_cents against the newly issued letter
    and re-derive its status."""
    deposit = money.deposit_for_matter(matter["id"])
    if deposit is None:
        deposit = stamp_new({
            "matter_id": matter["id"],
            "required_cents": 0,
            "funded_total_cents": 0,
            "refunded_total_cents": 0,
            "received_cents": 0,
            "status": "PENDING",
        })
        db.store.retainer_deposits[deposit["id"]] = deposit
        deposit["required_cents"] = money.retainer_required_amount(matter["id"])
        deposit["status"] = money.derive_deposit_status(deposit)
    else:
        money.refresh_deposit(deposit)
    return deposit


def countersign(letter, matter):
    """Successful COUNTERSIGN: letter -> COUNTERSIGNED; matter INTAKE -> OPEN
    in the same transaction with matter_number assigned exactly once
    ('M' + zero-padded 6-digit counter in completion order) and opened_at."""
    letter["status"] = "COUNTERSIGNED"
    letter["countersigned_at"] = now_iso()
    bump(letter)
    matter["lifecycle_status"] = "OPEN"
    matter["matter_number"] = db.next_matter_number()
    matter["opened_at"] = now_iso()
    bump(matter)
