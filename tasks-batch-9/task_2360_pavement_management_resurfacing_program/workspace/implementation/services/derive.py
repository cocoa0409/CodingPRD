"""Derived counters, aggregates and stored derived fields (PRD 2.8)."""
import calc
import clock
import db
from middleware import touch

OPEN_LINE_STATES = ("PLANNED", "IN_PROGRESS", "WORK_COMPLETE", "REMEDIATION_REQUIRED")
OPEN_REQUEST_STATES = ("NEW", "TRIAGED_PATCH", "DEFERRED_TO_CAPITAL")
COMMITTED_DELIVERY_STATES = (
    "AWARDED", "IN_CONSTRUCTION", "SUBSTANTIALLY_COMPLETE", "ACCEPTED",
)


# ------------------------------------------------------------------ children

def observations_of(survey_id):
    return [o for o in db.observations.values() if o["survey_id"] == survey_id]


def candidates_of_survey(survey_id):
    return [c for c in db.candidates.values() if c["survey_id"] == survey_id]


def allocations_of_scenario(scenario_id):
    return [a for a in db.allocations.values() if a["scenario_id"] == scenario_id]


def allocations_of_candidate(candidate_id):
    return [a for a in db.allocations.values() if a["candidate_id"] == candidate_id]


def scenarios_of_survey(survey_id):
    return [s for s in db.scenarios.values() if s["survey_id"] == survey_id]


def lines_of_project(project_id):
    return db.ordered(
        [l for l in db.project_segments.values() if l["project_id"] == project_id]
    )


def active_lines_of_project(project_id):
    return [l for l in lines_of_project(project_id) if l["work_state"] != "REMOVED"]


def lines_of_segment(segment_id):
    return db.ordered(
        [l for l in db.project_segments.values() if l["segment_id"] == segment_id]
    )


def coordinations_of_project(project_id):
    return db.ordered(
        [c for c in db.coordinations.values() if c["project_id"] == project_id]
    )


def tests_of_line(line_id):
    return db.ordered(
        [t for t in db.acceptance_tests.values()
         if t["project_segment_id"] == line_id]
    )


def tests_of_project(project_id):
    line_ids = {l["id"] for l in lines_of_project(project_id)}
    return db.ordered(
        [t for t in db.acceptance_tests.values()
         if t["project_segment_id"] in line_ids]
    )


def projects_of_scenario(scenario_id):
    return db.ordered(
        [p for p in db.projects.values() if p["scenario_id"] == scenario_id]
    )


def projects_of_contractor(contractor_id):
    return db.ordered(
        [p for p in db.projects.values() if p["contractor_id"] == contractor_id]
    )


def requests_of_segment(segment_id):
    return db.ordered(
        [r for r in db.service_requests.values() if r["segment_id"] == segment_id]
    )


def permits_of_segment(segment_id):
    return db.ordered(
        [p for p in db.cut_permits.values() if p["segment_id"] == segment_id]
    )


# ------------------------------------------------------------------- helpers

def apply_updates(entity, updates):
    """Write changed fields and bump the resource's audit fields once."""
    changed = False
    for key, value in updates.items():
        if entity.get(key) != value:
            entity[key] = value
            changed = True
    if changed:
        touch(entity)
    return changed


def segment_has_active_construction(segment_id):
    return any(
        l["work_state"] in ("IN_PROGRESS", "REMEDIATION_REQUIRED")
        for l in lines_of_segment(segment_id)
    )


# ------------------------------------------------------- derived recomputes

def recompute_survey_counters(survey):
    rows = observations_of(survey["id"])
    apply_updates(survey, {
        "observation_count": len(rows),
        "accepted_observation_count":
            len([o for o in rows if o["qc_status"] == "ACCEPTED"]),
    })


def recompute_segment_counters(segment):
    lines = lines_of_segment(segment["id"])
    apply_updates(segment, {
        "active_project_count":
            len([l for l in lines if l["work_state"] in OPEN_LINE_STATES]),
        "open_service_request_count": len([
            r for r in requests_of_segment(segment["id"])
            if r["request_status"] in OPEN_REQUEST_STATES
        ]),
    })


def set_segment_condition(segment, index, source):
    apply_updates(segment, {
        "condition_index": index,
        "condition_index_source": source,
        "condition_band": calc.condition_band(index),
    })


def recompute_project_counters(project):
    lines = lines_of_project(project["id"])
    active = [l for l in lines if l["work_state"] != "REMOVED"]
    area = calc.D(0)
    for line in active:
        area += calc.D(line["line_area_sy"])
    coords = coordinations_of_project(project["id"])
    apply_updates(project, {
        "segment_count": len(active),
        "planned_area_sy": calc.num(area, 2),
        "clearance_outstanding_count": len([
            c for c in coords
            if c["coordination_status"] not in ("CLEARED", "CLEARED_AFTER_WORK")
        ]),
        "open_remediation_count": len([
            l for l in lines if l["work_state"] == "REMEDIATION_REQUIRED"
        ]),
    })


def line_cost_cents(line):
    segment = db.segments[line["segment_id"]]
    candidate = db.candidates.get(line["candidate_id"])
    snapshot = candidate["selection_condition_index"] if candidate else \
        segment["condition_index"]
    return calc.construction_cost_cents(
        line["line_area_sy"], line["treatment_type"],
        segment["functional_class"], segment["width_ft"], snapshot,
    )


def recompute_project_estimate(project):
    active = active_lines_of_project(project["id"])
    if not active:
        apply_updates(project, {
            "bundle_base_cents": 0,
            "contingency_cents": 0,
            "utility_share_cents": 0,
            "project_total_estimate_cents": 0,
        })
        return
    construction = sum(l["line_cost_cents"] for l in active)
    if all(l["treatment_type"] == "CRACK_SEAL" for l in active):
        mobilization = calc.MOBILIZATION_CENTS["CRACK_SEAL"]
    else:
        mobilization = calc.MOBILIZATION_CENTS["MILL_AND_OVERLAY"]
    base = construction + mobilization
    contingency = calc.cents(calc.D(base) * calc.contingency_pct(base))
    after_work = any(
        c["coordination_status"] == "CLEARED_AFTER_WORK"
        for c in coordinations_of_project(project["id"])
    )
    utility_share = calc.cents(calc.D(base) * calc.D("0.03")) if after_work else 0
    apply_updates(project, {
        "bundle_base_cents": base,
        "contingency_cents": contingency,
        "utility_share_cents": utility_share,
        "project_total_estimate_cents": base + contingency + utility_share,
    })


def recompute_line_test_count(line):
    apply_updates(line, {"test_count": len(tests_of_line(line["id"]))})


def recompute_scenario_totals(scenario):
    rows = allocations_of_scenario(scenario["id"])
    funded = [a for a in rows if a["allocation_status"] == "FUNDED"]
    deferred = [a for a in rows if a["allocation_status"] == "DEFERRED"]
    backlog = 0
    for alloc in deferred:
        candidate = db.candidates.get(alloc["candidate_id"])
        if candidate:
            backlog += candidate["estimated_cost_cents"]
    committed = 0
    for project in projects_of_scenario(scenario["id"]):
        if project["delivery_status"] in COMMITTED_DELIVERY_STATES \
                and project["award_amount_cents"] is not None:
            committed += project["award_amount_cents"]
    apply_updates(scenario, {
        "allocation_count": len(funded) + len(deferred),
        "funded_cost_cents": sum(a["allocated_cents"] for a in funded),
        "backlog_cents": backlog,
        "committed_cents": committed,
        "uncommitted_cents": scenario["funding_cents"] - committed,
    })


# --------------------------------------------------------- service requests

def request_sla_breached(request_row):
    reference = request_row["closed_at"] or clock.now()
    return reference > request_row["sla_due_at"]


def refresh_request_breach(request_row):
    """Evaluated on every read; a read never mutates the resource."""
    request_row["sla_breached"] = request_sla_breached(request_row)
    return request_row


# ----------------------------------------------------- contractor scoring

def _decided_tests(project_ids):
    passed = 0
    failed = 0
    for test in db.acceptance_tests.values():
        line = db.project_segments.get(test["project_segment_id"])
        if line is None or line["project_id"] not in project_ids:
            continue
        if test.get("_decision") == "PASS":
            passed += 1
        elif test.get("_decision") == "FAIL":
            failed += 1
    return passed, failed


def scorecard(contractor):
    projects = projects_of_contractor(contractor["id"])
    interim_days_late = sum(
        p["days_late"] for p in projects
        if p["delivery_status"] in ("SUBSTANTIALLY_COMPLETE", "ACCEPTED")
    )
    interim = calc.score_components(
        contractor["passed_test_count"], contractor["failed_test_count"],
        interim_days_late, contractor["remediation_event_count"],
    )
    accepted_ids = {
        p["id"] for p in projects if p["delivery_status"] == "ACCEPTED"
    }
    final_passed, final_failed = _decided_tests(accepted_ids)
    final = calc.score_components(
        final_passed, final_failed, contractor["days_late_total"], final_failed,
    )
    return interim, final


def recompute_contractor_scores(contractor):
    interim, final = scorecard(contractor)
    final_score = None if contractor["accepted_project_count"] == 0 \
        else final["composite"]
    apply_updates(contractor, {
        "interim_performance_score": interim["composite"],
        "final_performance_score": final_score,
        "standing": calc.standing_for(interim["composite"]),
    })
