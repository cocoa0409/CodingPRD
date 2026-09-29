"""Multi-level cascades (PRD 2.8): project acceptance and test decisions."""
import calc
import clock
import db
from calc import D
from services import derive


def accept_project(project, inspector_user_id):
    """The system's widest cascade (PRD 3.8)."""
    now = clock.now()
    derive.apply_updates(project, {
        "delivery_status": "ACCEPTED",
        "accepted_at": now,
        "accepting_inspector_user_id": inspector_user_id,
    })

    # Level 1 — every WORK_COMPLETE line is accepted.
    accepted_lines = []
    for line in derive.lines_of_project(project["id"]):
        if line["work_state"] == "WORK_COMPLETE":
            derive.apply_updates(line, {"work_state": "ACCEPTED"})
            accepted_lines.append(line)

    # Level 2 — each segment absorbs the new pavement and opens a moratorium.
    segments = []
    seen_segment_ids = set()
    for line in accepted_lines:
        segment = db.segments.get(line["segment_id"])
        if segment is None:
            continue
        candidate = db.candidates.get(line["candidate_id"])
        gain = D(candidate["treatment_pci_gain"]) if candidate else D(0)
        new_index = calc.num(
            min(D("100.0"), D(segment["condition_index"]) + gain), 1
        )
        derive.apply_updates(segment, {
            "last_treatment_type": line["treatment_type"],
            "last_treatment_date": now,
            "baseline_condition_index": new_index,
            "condition_index": new_index,
            "condition_index_source": "MODEL_PROJECTED",
            "condition_band": calc.condition_band(new_index),
            "moratorium_until": calc.add_calendar_years(
                now, calc.MORATORIUM_YEARS[line["treatment_type"]]
            ),
        })
        derive.recompute_segment_counters(segment)
        if segment["id"] not in seen_segment_ids:
            seen_segment_ids.add(segment["id"])
            segments.append(segment)

    # Level 3 — pending cut permits move to moratorium review and re-price.
    for segment in segments:
        for permit in derive.permits_of_segment(segment["id"]):
            if permit["permit_status"] != "PENDING":
                continue
            remaining, multiplier, fee = calc.cut_permit_fee(
                permit["cut_area_sqft"], segment["moratorium_until"],
                permit["emergency"], now,
            )
            derive.apply_updates(permit, {
                "permit_status": "MORATORIUM_REVIEW",
                "moratorium_remaining_days": remaining,
                "fee_multiplier": multiplier,
                "degradation_fee_cents": fee,
            })

    # Level 4 — complaints deferred to this project close automatically.
    for segment in segments:
        for row in derive.requests_of_segment(segment["id"]):
            if row["request_status"] == "DEFERRED_TO_CAPITAL" \
                    and row["capital_project_id"] == project["id"]:
                derive.apply_updates(row, {
                    "request_status": "CLOSED_BY_CAPITAL",
                    "closure_code": "CAPITAL_RESURFACED",
                    "closed_at": now,
                    "sla_breached": now > row["sla_due_at"],
                })
                derive.recompute_segment_counters(segment)

    contractor = db.contractors.get(project["contractor_id"])
    if contractor is not None:
        derive.apply_updates(contractor, {
            "accepted_project_count": contractor["accepted_project_count"] + 1,
            "days_late_total": contractor["days_late_total"] + project["days_late"],
        })
        derive.recompute_contractor_scores(contractor)


def bubble_quality_status(project):
    """TESTING -> QUALITY_ACCEPTED once nothing is outstanding (PRD 3.8)."""
    active = derive.active_lines_of_project(project["id"])
    if project["quality_status"] != "TESTING":
        return
    if project["open_remediation_count"] != 0:
        return
    if active and all(l["work_state"] == "WORK_COMPLETE" for l in active):
        derive.apply_updates(project, {"quality_status": "QUALITY_ACCEPTED"})
