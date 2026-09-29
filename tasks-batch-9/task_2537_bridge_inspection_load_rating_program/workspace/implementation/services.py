"""Lookups, derived-field settlement and the multi-hop cascades (PRD 2.7)."""

from decimal import Decimal

import calc
import db
from calc import D, dec
from db import db as store
from errors import ApiError

# --------------------------------------------------------------------------- #
# lookups (validations priority 5 / 6)
# --------------------------------------------------------------------------- #
def _fetch(collection, record_id, error_id):
    if not isinstance(record_id, str) or record_id == "":
        raise ApiError(error_id)
    record = getattr(store, collection).get(record_id)
    if record is None:
        raise ApiError(error_id)
    return record


def get_bridge(bridge_id):
    return _fetch("bridges", bridge_id, "ERR_BRIDGE_NOT_FOUND")


def get_personnel(person_id):
    return _fetch("personnel", person_id, "ERR_PERSONNEL_NOT_FOUND")


def get_inspection(inspection_id):
    return _fetch("inspections", inspection_id, "ERR_INSPECTION_RECORD_NOT_FOUND")


def get_element_condition(element_id):
    return _fetch("element_conditions", element_id, "ERR_INSPECTION_RECORD_NOT_FOUND")


def get_critical_finding(finding_id):
    return _fetch("critical_findings", finding_id, "ERR_INSPECTION_RECORD_NOT_FOUND")


def get_notification_log(log_id):
    return _fetch("notification_logs", log_id, "ERR_INSPECTION_RECORD_NOT_FOUND")


def get_load_rating(rating_id):
    return _fetch("load_ratings", rating_id, "ERR_RATING_RECORD_NOT_FOUND")


def get_scour_evaluation(evaluation_id):
    return _fetch("scour_evaluations", evaluation_id, "ERR_RATING_RECORD_NOT_FOUND")


def get_plan_of_action(plan_id):
    return _fetch("plans_of_action", plan_id, "ERR_RATING_RECORD_NOT_FOUND")


def get_permit_application(permit_id):
    return _fetch("permit_applications", permit_id, "ERR_PERMIT_NOT_FOUND")


def get_permit_bridge_analysis(analysis_id):
    return _fetch("permit_bridge_analyses", analysis_id, "ERR_PERMIT_NOT_FOUND")


def get_program_cycle(cycle_id):
    return _fetch("program_cycles", cycle_id, "ERR_PROGRAM_RECORD_NOT_FOUND")


def get_project_candidate(candidate_id):
    return _fetch("project_candidates", candidate_id, "ERR_PROGRAM_RECORD_NOT_FOUND")


def get_federal_submission(submission_id):
    return _fetch("federal_submissions", submission_id, "ERR_PROGRAM_RECORD_NOT_FOUND")


# --------------------------------------------------------------------------- #
# child collections
# --------------------------------------------------------------------------- #
def rows(collection):
    return db.by_creation(list(getattr(store, collection).values()))


def where(collection, **filters):
    out = []
    for record in rows(collection):
        if all(record.get(key) == value for key, value in filters.items()):
            out.append(record)
    return out


def element_conditions_of(inspection_id):
    return where("element_conditions", inspection_id=inspection_id)


def inspections_of(bridge_id):
    return where("inspections", bridge_id=bridge_id)


def findings_of(bridge_id):
    return where("critical_findings", bridge_id=bridge_id)


def load_ratings_of(bridge_id):
    return where("load_ratings", bridge_id=bridge_id)


def candidates_of(cycle_id):
    return where("project_candidates", program_cycle_id=cycle_id)


def person_is_current(person):
    return calc.qualification_status(person.get("_expiry_date"), db.now().date()) == "CURRENT"


# --------------------------------------------------------------------------- #
# inspection rollups
# --------------------------------------------------------------------------- #
def recompute_inspection_rollup(inspection):
    children = element_conditions_of(inspection["id"])
    inspection["element_count"] = len(children)
    reported = D(0)
    deficient = D(0)
    photos = 0
    balanced = True
    for child in children:
        reported += dec(child["total_quantity"])
        deficient += dec(child["deficient_quantity"])
        photos += int(child["photo_count"] or 0)
        if not child["balanced"]:
            balanced = False
    inspection["reported_quantity_total"] = reported
    inspection["deficient_quantity_total"] = deficient
    inspection["photo_count_total"] = photos
    inspection["quantity_balanced"] = balanced
    return inspection


def recompute_element_condition(record):
    total = dec(record["total_quantity"])
    reported_sum = (
        dec(record["cs1_qty"]) + dec(record["cs2_qty"]) + dec(record["cs3_qty"]) + dec(record["cs4_qty"])
    )
    record["reported_sum"] = reported_sum
    record["balanced"] = reported_sum == total
    record["deficient_quantity"] = dec(record["cs3_qty"]) + dec(record["cs4_qty"])
    record["element_health_index"] = calc.element_health_index(
        record["cs1_qty"], record["cs2_qty"], record["cs3_qty"], record["cs4_qty"], total
    )
    return record


def compute_inspection_condition(inspection):
    """Group indices, the three NBI component ratings and the bridge health index."""
    children = element_conditions_of(inspection["id"])
    for child in children:
        recompute_element_condition(child)
    by_group = {"DECK_GROUP": [], "SUPERSTRUCTURE": [], "SUBSTRUCTURE": []}
    for child in children:
        by_group[child["element_group"]].append((child["element_key"], child["element_health_index"]))
    inspection["deck_group_ehi"] = calc.weighted_group_index(by_group["DECK_GROUP"])
    inspection["superstructure_group_ehi"] = calc.weighted_group_index(by_group["SUPERSTRUCTURE"])
    inspection["substructure_group_ehi"] = calc.weighted_group_index(by_group["SUBSTRUCTURE"])
    inspection["computed_deck_rating"] = calc.rating_from_index(inspection["deck_group_ehi"])
    inspection["computed_superstructure_rating"] = calc.rating_from_index(
        inspection["superstructure_group_ehi"]
    )
    inspection["computed_substructure_rating"] = calc.rating_from_index(
        inspection["substructure_group_ehi"]
    )
    inspection["bridge_health_index"] = calc.weighted_group_index(
        [(child["element_key"], child["element_health_index"]) for child in children]
    )
    recompute_inspection_rollup(inspection)
    return inspection


def inspection_totals(inspection):
    children = element_conditions_of(inspection["id"])
    inventoried = D(0)
    deficient = D(0)
    for child in children:
        inventoried += dec(child["total_quantity"])
        deficient += dec(child["deficient_quantity"])
    return inventoried, deficient


# --------------------------------------------------------------------------- #
# bridge settlement
# --------------------------------------------------------------------------- #
def governing_rating(bridge):
    candidates = [
        rating
        for rating in load_ratings_of(bridge["id"])
        if rating["rating_status"] == "APPROVED"
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda r: (r["rating_effective_date"], r["created_at"], r["_seq"]))


def latest_final_scour(bridge_id):
    finals = [
        row
        for row in where("scour_evaluations", bridge_id=bridge_id)
        if row["status"] == "FINAL"
    ]
    if not finals:
        return None
    return max(finals, key=lambda r: (r["finalized_at"], r["created_at"], r["_seq"]))


def settle_bridge(bridge):
    """Idempotent recomputation of every derived Bridge field. Never bumps version."""
    findings = findings_of(bridge["id"])
    active = [
        finding
        for finding in findings
        if finding["finding_status"] in ("OPEN", "MITIGATED")
        and finding["restriction_action"] in ("RESTRICT", "CLOSE")
    ]
    bridge["open_critical_finding_count"] = len(
        [f for f in findings if f["finding_status"] in ("OPEN", "MITIGATED")]
    )

    evaluation = latest_final_scour(bridge["id"])
    bridge["scour_status"] = (
        evaluation["derived_scour_status"] if evaluation is not None else "NOT_EVALUATED"
    )

    governing = governing_rating(bridge)
    if governing is None:
        bridge["governing_load_rating_id"] = None
        bridge["posting_required"] = False
        bridge["posted_limit_tons"] = None
        bridge["operating_rating_tons"] = None
        bridge["inventory_rating_tons"] = None
    else:
        bridge["governing_load_rating_id"] = governing["id"]
        bridge["posting_required"] = bool(governing["posting_required"])
        bridge["posted_limit_tons"] = governing["posted_limit_tons"]
        bridge["operating_rating_tons"] = governing["operating_rating_tons"]
        bridge["inventory_rating_tons"] = governing["inventory_rating_tons"]

    if any(finding["restriction_action"] == "CLOSE" for finding in active):
        bridge["service_posture"] = "CLOSED"
    elif active:
        bridge["service_posture"] = "RESTRICTED"
    elif governing is not None and governing["posting_required"]:
        bridge["service_posture"] = "POSTED"
    else:
        bridge["service_posture"] = "OPEN"

    bridge["min_nbi_rating"] = min(
        int(bridge["deck_rating"]),
        int(bridge["superstructure_rating"]),
        int(bridge["substructure_rating"]),
    )

    if bridge["scour_status"] == "SCOUR_CRITICAL":
        approved = [
            plan
            for plan in where("plans_of_action", bridge_id=bridge["id"])
            if plan["status"] == "APPROVED"
        ]
        bridge["poa_compliant"] = bool(approved)
    else:
        bridge["poa_compliant"] = True

    bridge["inspection_interval_months"] = calc.inspection_interval_months(
        bridge["min_nbi_rating"],
        bridge["year_built"],
        bridge["adt"],
        bridge["fracture_critical"],
        bridge["scour_status"],
        bridge["service_posture"],
    )
    bridge["underwater_interval_months"] = calc.underwater_interval_months(
        bridge["underwater_elements"], bridge["scour_status"]
    )

    routine_base = bridge.get("_last_routine_date") or bridge["created_at"].date()
    bridge["next_inspection_due_date"] = calc.add_months(
        routine_base, bridge["inspection_interval_months"]
    )
    if bridge["underwater_interval_months"] is None:
        bridge["next_underwater_due_date"] = None
    else:
        underwater_base = bridge.get("_last_underwater_date") or bridge["created_at"].date()
        bridge["next_underwater_due_date"] = calc.add_months(
            underwater_base, bridge["underwater_interval_months"]
        )
    return bridge


def settle_and_touch(bridge):
    settle_bridge(bridge)
    db.touch(bridge)
    return bridge


# --------------------------------------------------------------------------- #
# program cycle settlement
# --------------------------------------------------------------------------- #
def settle_cycle(cycle):
    candidates = candidates_of(cycle["id"])
    identified = [c for c in candidates if c["status"] == "IDENTIFIED"]
    programmed = [c for c in candidates if c["status"] == "PROGRAMMED"]
    deferred = [c for c in candidates if c["status"] == "DEFERRED"]
    cycle["identified_count"] = len(identified)
    cycle["programmed_count"] = len(programmed)
    cycle["deferred_count"] = len(deferred)
    cycle["committed_cents"] = sum(int(c["estimated_cost_cents"]) for c in programmed)
    cycle["unprogrammed_cost_cents"] = sum(int(c["estimated_cost_cents"]) for c in identified)
    cycle["remaining_cents"] = int(cycle["available_cents"]) - int(cycle["committed_cents"])
    return cycle


def settle_cycle_and_touch(cycle):
    settle_cycle(cycle)
    db.touch(cycle)
    return cycle


# --------------------------------------------------------------------------- #
# project candidate creation (API path and acceptance cascade HOP 4)
# --------------------------------------------------------------------------- #
def create_candidate(cycle, bridge, source_inspection, origin, justification=None):
    cost = calc.estimated_repair_cost_cents(element_conditions_of(source_inspection["id"]))
    record = db.new_record(
        {
            "bridge_id": bridge["id"],
            "program_cycle_id": cycle["id"],
            "source_inspection_id": source_inspection["id"],
            "work_type": calc.candidate_work_type(bridge["min_nbi_rating"]),
            "estimated_cost_cents": cost,
            "priority_score": calc.candidate_priority_score(bridge, cycle["ranking_policy"]),
            "ranking_policy_applied": cycle["ranking_policy"],
            "status": "IDENTIFIED",
            "origin": origin,
            "programmed_at": None,
            "withdrawn_at": None,
            "deferred_at": None,
            "justification": justification,
        }
    )
    # A new candidate supersedes any prior IDENTIFIED one for the same bridge and cycle.
    for prior in candidates_of(cycle["id"]):
        if prior["bridge_id"] == bridge["id"] and prior["status"] == "IDENTIFIED":
            prior["status"] = "WITHDRAWN"
            prior["withdrawn_at"] = db.now()
            db.touch(prior)
    store.project_candidates[record["id"]] = record
    settle_cycle_and_touch(cycle)
    return record


def latest_accepted_inspection(bridge_id):
    accepted = [row for row in inspections_of(bridge_id) if row["status"] == "ACCEPTED"]
    if not accepted:
        return None
    return max(accepted, key=lambda r: (r["accepted_at"], r["created_at"], r["_seq"]))


# --------------------------------------------------------------------------- #
# cascade: inspection acceptance (5 hops)
# --------------------------------------------------------------------------- #
def accept_inspection(inspection):
    bridge = get_bridge(inspection["bridge_id"])
    # HOP 1
    inspection["status"] = "ACCEPTED"
    inspection["accepted_at"] = db.now()
    db.touch(inspection)

    # HOP 2 - publish condition data to the inventory
    if inspection["computed_deck_rating"] is not None:
        bridge["deck_rating"] = inspection["computed_deck_rating"]
    if inspection["computed_superstructure_rating"] is not None:
        bridge["superstructure_rating"] = inspection["computed_superstructure_rating"]
    if inspection["computed_substructure_rating"] is not None:
        bridge["substructure_rating"] = inspection["computed_substructure_rating"]
    bridge["bridge_health_index"] = inspection["bridge_health_index"]
    inventoried, deficient = inspection_totals(inspection)
    bridge["inventoried_quantity_total"] = inventoried
    bridge["deficiency_pct"] = calc.deficiency_pct(inventoried, deficient)

    # HOP 3 - inspection frequency and due dates
    if inspection["inspection_type"] == "ROUTINE":
        bridge["last_routine_inspection_date"] = inspection["inspection_date"]
        bridge["_last_routine_date"] = inspection["_inspection_date"].date()
    elif inspection["inspection_type"] == "UNDERWATER":
        bridge["last_underwater_inspection_date"] = inspection["inspection_date"]
        bridge["_last_underwater_date"] = inspection["_inspection_date"].date()
    settle_and_touch(bridge)

    # HOP 4 / HOP 5 - automatic programming candidate
    if int(bridge["min_nbi_rating"]) <= 5:
        planning = [cycle for cycle in rows("program_cycles") if cycle["status"] == "PLANNING"]
        if len(planning) == 1:
            create_candidate(planning[0], bridge, inspection, "AUTO_FROM_INSPECTION")
    return inspection


# --------------------------------------------------------------------------- #
# cascade: bridge closure flips permit analyses (HOP 3 / HOP 4)
# --------------------------------------------------------------------------- #
def cascade_bridge_closed(bridge):
    affected = set()
    for analysis in where("permit_bridge_analyses", bridge_id=bridge["id"]):
        application = store.permit_applications.get(analysis["permit_application_id"])
        if application is None:
            continue
        if application["status"] not in ("ANALYZED", "APPROVED", "APPROVED_WITH_CONDITIONS"):
            continue
        analysis["analysis_result"] = "DENIED"
        analysis["result_reason"] = "BRIDGE_CLOSED"
        db.touch(analysis)
        affected.add(application["id"])
    for application_id in affected:
        application = store.permit_applications[application_id]
        siblings = where("permit_bridge_analyses", permit_application_id=application_id)
        application["recommended_decision"] = calc.permit_recommended_decision(
            [row["analysis_result"] for row in siblings]
        )
        factors = [
            row["rating_factor_permit"]
            for row in siblings
            if row["rating_factor_permit"] is not None
        ]
        application["governing_analysis_min_rf"] = min(factors) if factors else None
        if application["status"] in ("APPROVED", "APPROVED_WITH_CONDITIONS"):
            application["status"] = "REVOKED"
            application["revoked_at"] = db.now()
        db.touch(application)


# --------------------------------------------------------------------------- #
# cascade: scour finalize (4 hops)
# --------------------------------------------------------------------------- #
def finalize_scour(evaluation):
    bridge = get_bridge(evaluation["bridge_id"])
    # HOP 1
    evaluation["status"] = "FINAL"
    evaluation["finalized_at"] = db.now()
    db.touch(evaluation)
    # HOP 2 - scour status and interval floor
    settle_bridge(bridge)
    # HOP 3 - the plan of action the structure now owes
    if bridge["scour_status"] == "SCOUR_CRITICAL":
        existing = [
            plan
            for plan in where("plans_of_action", bridge_id=bridge["id"])
            if plan["status"] in ("REQUIRED", "DRAFT", "SUBMITTED", "APPROVED")
        ]
        if not existing:
            plan = db.new_record(
                {
                    "bridge_id": bridge["id"],
                    "scour_evaluation_id": evaluation["id"],
                    "status": "REQUIRED",
                    "monitoring_frequency_months": None,
                    "closure_trigger_stage_m": None,
                    "countermeasure_type": "NONE",
                    "approved_by_id": None,
                    "revision_count": 0,
                    "submitted_at": None,
                    "approved_at": None,
                    "return_note": None,
                }
            )
            store.plans_of_action[plan["id"]] = plan
    # HOP 4 - poa_compliant follows from the plan set
    settle_and_touch(bridge)
    return evaluation


# --------------------------------------------------------------------------- #
# statewide compliance snapshot
# --------------------------------------------------------------------------- #
def compliance_snapshot():
    bridges = rows("bridges")
    today = db.now().date()
    overdue = 0
    for bridge in bridges:
        due = bridge.get("next_inspection_due_date")
        if due is not None and due < today:
            overdue += 1
    poa_noncompliant = len([b for b in bridges if not b["poa_compliant"]])
    open_immediate = len(
        [
            finding
            for finding in rows("critical_findings")
            if finding["severity"] == "IMMEDIATE"
            and finding["finding_status"] in ("OPEN", "MITIGATED")
        ]
    )
    return {
        "total_bridge_count": len(bridges),
        "overdue_inspection_count": overdue,
        "inspection_compliance_pct": calc.inspection_compliance_pct(len(bridges), overdue),
        "poa_noncompliant_count": poa_noncompliant,
        "open_immediate_finding_count": open_immediate,
        "error_count": poa_noncompliant + open_immediate,
    }
