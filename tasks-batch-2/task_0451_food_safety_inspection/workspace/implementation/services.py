"""Cross-entity business services: scoring recompute, finalize cascade,
establishment status reconciliation. (PRD §3.5–§3.8)
"""
import calculations as calc
from db import store, touch


def violations_for(inspection_id):
    vs = [v for v in store.violations.values() if v["inspection_id"] == inspection_id]
    return sorted(vs, key=lambda v: v["_seq"])


def recompute_violation_points(violation):
    """Recompute observed/final demerit points for a single violation in place."""
    code = store.fda_food_codes[violation["fda_code_id"]]
    observed, final = calc.violation_points(
        code["base_demerit_points"],
        code.get("repeat_surcharge_points", 0),
        violation["repeat_offense"],
        violation["corrected_on_site"],
    )
    violation["demerit_points_observed"] = observed
    violation["demerit_points_final"] = final


def recompute_inspection_scores(inspection):
    """Recompute as_observed_score / final_score / critical_count / grade /
    placard_color for an inspection from its violations. Preview values.
    """
    vs = violations_for(inspection["id"])
    as_observed, final_score, critical_count = calc.inspection_scores(vs)
    grade, placard = calc.grade_assignment(final_score, critical_count)
    inspection["as_observed_score"] = as_observed
    inspection["final_score"] = final_score
    inspection["critical_count"] = critical_count
    inspection["grade"] = grade
    inspection["placard_color"] = placard


def recompute_open_critical_count(establishment_id):
    """Count unresolved CRITICAL violations across all FINALIZED inspections of
    this establishment.
    """
    finalized_ids = {
        i["id"]
        for i in store.inspections.values()
        if i["establishment_id"] == establishment_id and i["status"] == "FINALIZED"
    }
    count = 0
    for v in store.violations.values():
        if (
            v["inspection_id"] in finalized_ids
            and v["classification"] == "CRITICAL"
            and v["resolution_status"] == "OPEN"
        ):
            count += 1
    return count


def is_repeat_offense(establishment_id, fda_code_id):
    """True when the same code was cited on a prior FINALIZED inspection of this
    establishment and that prior citation is still unresolved (OPEN).
    """
    finalized_ids = {
        i["id"]
        for i in store.inspections.values()
        if i["establishment_id"] == establishment_id and i["status"] == "FINALIZED"
    }
    for v in store.violations.values():
        if (
            v["inspection_id"] in finalized_ids
            and v["fda_code_id"] == fda_code_id
            and v["resolution_status"] == "OPEN"
        ):
            return True
    return False


def finalize_cascade(inspection, establishment):
    """Promote scores onto establishment and fire the conditional cascades.
    Called inside finalize after the inspection is set FINALIZED.
    """
    # Promote final score/grade/placard onto the establishment.
    establishment["current_score"] = inspection["final_score"]
    establishment["current_grade"] = inspection["grade"]
    establishment["current_placard_color"] = inspection["placard_color"]
    establishment["open_critical_count"] = recompute_open_critical_count(establishment["id"])
    touch(establishment)

    grade = inspection["grade"]
    clock = store.clock_index

    # ---- Passing reinspection cascade ----
    if (
        inspection["inspection_type"] == "REINSPECTION"
        and grade in ("A", "B")
        and inspection["critical_count"] == 0
    ):
        _resolve_prior_open_violations(inspection, establishment)
        if establishment["status"] == "SUSPENDED":
            _lift_active_closure(establishment)
            establishment["status"] = "PERMITTED"
            touch(establishment)
        # open_critical_count may have changed after resolving violations.
        establishment["open_critical_count"] = recompute_open_critical_count(establishment["id"])
        touch(establishment)

    # ---- Closure cascade ----
    if grade == "CLOSED":
        reason = calc.closure_trigger(inspection["critical_count"], inspection["final_score"])
        order = _create_closure_order(
            establishment_id=establishment["id"],
            triggering_inspection_id=inspection["id"],
            reason_code=reason,
        )
        if establishment["status"] == "PERMITTED":
            establishment["status"] = "SUSPENDED"
            establishment["active_closure_order_id"] = order["id"]
        establishment["next_reinspection_due_index"] = clock + calc.REINSPECTION_GRACE_DAYS
        touch(establishment)

    # ---- Routine pass cascade ----
    if inspection["inspection_type"] == "ROUTINE" and grade in ("A", "B"):
        establishment["next_reinspection_due_index"] = clock + establishment["routine_interval_days"]
        touch(establishment)


def _resolve_prior_open_violations(inspection, establishment):
    """Mark matching prior OPEN violations RESOLVED. The reinspection clears the
    codes cited on the inspection it follows (reinspection_of_id) — and more
    generally the establishment's prior FINALIZED open violations whose codes
    were re-checked. Per PRD §3.7 we resolve the matching prior OPEN violations.
    """
    prior_finalized = {
        i["id"]
        for i in store.inspections.values()
        if i["establishment_id"] == establishment["id"]
        and i["status"] == "FINALIZED"
        and i["id"] != inspection["id"]
    }
    for v in store.violations.values():
        if v["inspection_id"] in prior_finalized and v["resolution_status"] == "OPEN":
            v["resolution_status"] = "RESOLVED"
            touch(v)


def _lift_active_closure(establishment):
    order_id = establishment.get("active_closure_order_id")
    if order_id and order_id in store.closure_orders:
        order = store.closure_orders[order_id]
        if order["status"] == "ACTIVE":
            order["status"] = "LIFTED"
            touch(order)
    establishment["active_closure_order_id"] = None


def _create_closure_order(establishment_id, triggering_inspection_id, reason_code):
    from db import stamp_new

    order = {
        "establishment_id": establishment_id,
        "triggering_inspection_id": triggering_inspection_id,
        "reason_code": reason_code,
        "issued_index": store.clock_index,
        "status": "ACTIVE",
    }
    stamp_new(order)
    store.closure_orders[order["id"]] = order
    return order
