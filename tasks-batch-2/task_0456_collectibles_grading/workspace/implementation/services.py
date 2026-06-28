"""Cross-entity business logic: posture re-derivation, cascades, fee finalization.

PRD §2.9, §3.2-§3.11. All mutation here happens under db.lock from routes.
"""
import db
import calculations as calc


# ---- lookups ----------------------------------------------------------------

def items_of_submission(submission_id):
    return [
        it
        for it in db.submission_items.values()
        if it["submission_id"] == submission_id
    ]


def intake_for_item(item_id):
    return [r for r in db.intake_records.values() if r["item_id"] == item_id]


def assessments_for_item(item_id):
    return [a for a in db.grade_assessments.values() if a["item_id"] == item_id]


def active_assessment(item_id):
    """The single unsuperseded grade assessment for an item, if any."""
    for a in db.grade_assessments.values():
        if a["item_id"] == item_id and not a["superseded"]:
            return a
    return None


def auth_checks_for_item(item_id):
    return [a for a in db.authentication_checks.values() if a["item_id"] == item_id]


def latest_auth_check(item_id):
    checks = auth_checks_for_item(item_id)
    if not checks:
        return None
    return sorted(checks, key=lambda c: c["created_at"])[-1]


def slabs_for_item(item_id):
    return [s for s in db.slabs.values() if s["item_id"] == item_id]


def active_slab(item_id):
    for s in db.slabs.values():
        if s["item_id"] == item_id and s["active"]:
            return s
    return None


def open_regrades_for_item(item_id):
    return [
        r
        for r in db.regrade_requests.values()
        if r["item_id"] == item_id and r["status"] in ("OPEN", "CRACKED")
    ]


def policy_for_submission(submission_id):
    for p in db.insurance_policies.values():
        if p["submission_id"] == submission_id:
            return p
    return None


# ---- submission posture re-derivation (PRD §2.9, §3) ------------------------

def recompute_submission_status(submission):
    """Re-derive a submission's posture from child item states (PRD §2.9).

    Only the system-driven postures are re-derived here:
      SUBMITTED -> RECEIVING -> IN_GRADING -> READY_TO_SHIP.
    DRAFT, SUBMITTED (entry), SHIPPED, CLOSED are set by explicit transitions.
    The posture only advances; it is never rolled backward by this function,
    except the explicit ENCAPSULATED->CRACK_PENDING crack cascade which sets
    the submission back to IN_GRADING directly.
    """
    cur = submission["status"]
    # Postures that this re-derivation governs.
    if cur not in ("SUBMITTED", "RECEIVING", "IN_GRADING", "READY_TO_SHIP"):
        return

    items = items_of_submission(submission["id"])
    if not items:
        return

    statuses = [it["status"] for it in items]

    # Determine the highest system posture justified by current item states.
    any_intake = any(s != "REGISTERED" for s in statuses)
    # CRACK_PENDING counts as active grading: a cracked item has re-entered the
    # pipeline, and the crack cascade re-derives the posture to IN_GRADING (PRD §3.7).
    any_grading = any(
        s in ("GRADING", "AUTHENTICATED", "ENCAPSULATED", "CRACK_PENDING")
        for s in statuses
    )
    all_terminal = all(s in ("ENCAPSULATED", "REJECTED_RETURNED") for s in statuses)
    no_open_regrade = not any(
        open_regrades_for_item(it["id"]) for it in items
    )

    target = cur
    if all_terminal and no_open_regrade:
        target = "READY_TO_SHIP"
    elif any_grading:
        target = "IN_GRADING"
    elif any_intake:
        target = "RECEIVING"
    else:
        target = "SUBMITTED"

    # Posture ordering for monotonic forward movement within the system band.
    order = {"SUBMITTED": 0, "RECEIVING": 1, "IN_GRADING": 2, "READY_TO_SHIP": 3}
    if order[target] != order[cur]:
        _set_status(submission, target)
        if target == "READY_TO_SHIP":
            finalize_submission_fee(submission)


def _set_status(record, new_status):
    if record["status"] != new_status:
        record["status"] = new_status
        db.touch(record)


def set_submission_status(submission, new_status):
    _set_status(submission, new_status)


# ---- fee aggregation (PRD §3.8) ---------------------------------------------

def finalize_submission_fee(submission):
    """total_final_fee_cents = sum(final_fee_cents for items ENCAPSULATED) (PRD §3.8)."""
    items = items_of_submission(submission["id"])
    total = sum(
        it["final_fee_cents"] for it in items if it["status"] == "ENCAPSULATED"
    )
    if submission["total_final_fee_cents"] != total:
        submission["total_final_fee_cents"] = total
        db.touch(submission)


# ---- insurance (PRD §3.9) ---------------------------------------------------

def recompute_covered_value(submission, service_level):
    """Recompute the policy covered_value/premium (PRD §3.9). Used on reject."""
    policy = policy_for_submission(submission["id"])
    if policy is None:
        return
    items = items_of_submission(submission["id"])
    covered, premium = calc.covered_value(items, service_level)
    changed = (
        policy["covered_value_cents"] != covered
        or policy["premium_cents"] != premium
    )
    if changed:
        policy["covered_value_cents"] = covered
        policy["premium_cents"] = premium
        db.touch(policy)


# ---- population census (PRD §3.10) ------------------------------------------

def find_or_create_bucket(grading_standard_id, title_key, grade_value):
    for b in db.population_reports.values():
        if (
            b["grading_standard_id"] == grading_standard_id
            and b["title_key"] == title_key
            and b["grade_value"] == grade_value
        ):
            return b
    bucket = db.stamp_create(
        {
            "grading_standard_id": grading_standard_id,
            "title_key": title_key,
            "grade_value": grade_value,
            "pop_count": 0,
        }
    )
    db.population_reports[bucket["id"]] = bucket
    return bucket


def find_bucket(grading_standard_id, title_key, grade_value):
    for b in db.population_reports.values():
        if (
            b["grading_standard_id"] == grading_standard_id
            and b["title_key"] == title_key
            and b["grade_value"] == grade_value
        ):
            return b
    return None


def population_bump(grading_standard_id, title_key, grade_value):
    bucket = find_or_create_bucket(grading_standard_id, title_key, grade_value)
    bucket["pop_count"] += 1
    db.touch(bucket)
    return bucket


def population_decrement(grading_standard_id, title_key, grade_value):
    bucket = find_bucket(grading_standard_id, title_key, grade_value)
    if bucket is None:
        return None
    if bucket["pop_count"] > 0:
        bucket["pop_count"] -= 1
        db.touch(bucket)
    return bucket
