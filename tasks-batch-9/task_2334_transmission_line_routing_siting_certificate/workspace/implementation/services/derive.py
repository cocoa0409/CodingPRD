"""Derived counters, cascades and cross-entity recomputation (PRD §2.12)."""

import math
from datetime import timedelta
from decimal import Decimal

from db import by_created, store, touch
from services import calc


# ------------------------------------------------------------- utils ----
def update(row, **fields):
    """Apply fields; bump version/updated_at only when something changed."""
    changed = False
    for key, value in fields.items():
        if row.get(key) != value:
            row[key] = value
            changed = True
    if changed:
        touch(row)
    return changed


def set_quiet(row, **fields):
    for key, value in fields.items():
        row[key] = value


def apply(row, **fields):
    """Apply an explicit operation: always exactly one version bump."""
    for key, value in fields.items():
        row[key] = value
    touch(row)
    return row


# ------------------------------------------------------- collections ----
def segments_of_route(route_id):
    return sorted(
        [s for s in store.route_segments.values() if s["route_id"] == route_id],
        key=lambda s: s["sequence_index"],
    )


def routes_of_project(project_id):
    return by_created([r for r in store.routes.values() if r["project_id"] == project_id])


def studies_of_project(project_id):
    return by_created([s for s in store.planning_studies.values() if s["project_id"] == project_id])


def alternatives_of_study(study_id):
    return by_created([a for a in store.alternatives.values() if a["study_id"] == study_id])


def comments_of_route(route_id):
    return by_created([c for c in store.public_comments.values() if c["route_id"] == route_id])


def comments_of_segment(segment_id):
    return by_created([c for c in store.public_comments.values() if c["segment_id"] == segment_id])


def activities_of_segment(segment_id):
    return by_created([a for a in store.construction_activities.values() if a["segment_id"] == segment_id])


def activities_of_certificate(certificate_id):
    return by_created(
        [a for a in store.construction_activities.values() if a["certificate_id"] == certificate_id]
    )


def findings_of_certificate(certificate_id):
    return by_created([n for n in store.nonconformances.values() if n["certificate_id"] == certificate_id])


def findings_of_condition(condition_id):
    return by_created([n for n in store.nonconformances.values() if n["condition_id"] == condition_id])


def conditions_of_certificate(certificate_id):
    return by_created(
        [c for c in store.certificate_conditions.values() if c["certificate_id"] == certificate_id]
    )


def sessions_of_application(application_id):
    return by_created([s for s in store.hearing_sessions.values() if s["application_id"] == application_id])


def interventions_of_application(application_id):
    return by_created([i for i in store.interventions.values() if i["application_id"] == application_id])


def tracts_of_project(project_id):
    return by_created([t for t in store.easement_tracts.values() if t["project_id"] == project_id])


def tracts_of_segment(segment_id):
    return by_created([t for t in store.easement_tracts.values() if t["segment_id"] == segment_id])


def project_of_route(route):
    return store.projects.get(route["project_id"])


def route_of_segment(segment):
    return store.routes.get(segment["route_id"])


def project_of_segment(segment):
    route = route_of_segment(segment)
    return store.projects.get(route["project_id"]) if route else None


def certificate_of_project(project_id):
    """The certificate whose certified route belongs to this project."""
    found = None
    for cert in by_created(list(store.certificates.values())):
        app = store.applications.get(cert["application_id"])
        if app and app["project_id"] == project_id:
            found = cert
    return found


# -------------------------------------------------- derived counters ----
def recompute_route_counters(route):
    segments = segments_of_route(route["id"])
    update(
        route,
        segment_count=len(segments),
        total_miles=calc.total_miles_of(segments),
        unsurveyed_segment_count=sum(1 for s in segments if s["survey_status"] == "DESKTOP"),
    )


def recompute_segment_material_count(segment):
    count = sum(
        1
        for c in store.public_comments.values()
        if c["segment_id"] == segment["id"]
        and c["materiality"] == "MATERIAL"
        and c["status"] == "RECEIVED"
    )
    update(segment, material_comment_count=count)


def recompute_segment_crew(segment):
    total = sum(
        a["crew_count"]
        for a in store.construction_activities.values()
        if a["segment_id"] == segment["id"] and a["status"] in ("SCHEDULED", "IN_PROGRESS", "SUSPENDED")
    )
    update(segment, committed_crew_count=total)


def recompute_study_screened_in(study):
    count = sum(
        1
        for a in store.alternatives.values()
        if a["study_id"] == study["id"] and a["screening_status"] == "SCREENED_IN"
    )
    update(study, alternatives_screened_in_count=count)


def recompute_party_count(application):
    count = sum(
        1
        for i in store.interventions.values()
        if i["application_id"] == application["id"] and i["status"] == "GRANTED"
    )
    update(application, party_count=count)


def recompute_project_committed(project):
    total = 0
    for tract in store.easement_tracts.values():
        if tract["project_id"] == project["id"] and tract["acquisition_status"] in ("AGREED", "AWARDED"):
            total += int(tract.get("committed_cents") or 0)
    update(project, easement_committed_cents=total)


# ------------------------------------------------ schedule / deadline ----
def application_deadline(application):
    return application["filed_at"] + timedelta(days=calc.FILING_PERIOD_DAYS + application["suspension_days"])


def recompute_application_deadline(application):
    update(application, decision_deadline_at=application_deadline(application))


def latest_live_application(project_id):
    candidates = [
        a
        for a in store.applications.values()
        if a["project_id"] == project_id and a["review_status"] != "DENIED"
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda a: (a["filed_at"], a["_seq"]))[-1]


def recompute_project_schedule(project):
    application = latest_live_application(project["id"])
    if application is None or application.get("decision_deadline_at") is None:
        update(project, schedule_posture="ON_TRACK", right_of_way_hold=False)
        return
    delta = project["target_energization_at"] - application["decision_deadline_at"]
    slack_days = math.trunc(delta.total_seconds() / 86400.0)
    if slack_days < 0:
        posture = "CRITICAL"
    elif slack_days < calc.AT_RISK_SLACK_DAYS:
        posture = "AT_RISK"
    else:
        posture = "ON_TRACK"
    update(
        project,
        schedule_posture=posture,
        right_of_way_hold=posture in ("AT_RISK", "CRITICAL"),
    )


def advance_project_stage(project, target):
    update(project, stage=target)


# ----------------------------------------------------- construction ----
def bubble_segment_completion(segment):
    activities = activities_of_segment(segment["id"])
    if not activities:
        return
    live = [a for a in activities if a["status"] in ("SCHEDULED", "IN_PROGRESS", "SUSPENDED")]
    completed = [a for a in activities if a["status"] == "COMPLETE"]
    if live or not completed:
        return
    if segment["construction_state"] != "ACTIVE":
        return
    update(segment, construction_state="COMPLETE", committed_crew_count=0)


def suspend_activities(activities, reason, statuses=("SCHEDULED", "IN_PROGRESS")):
    """Suspend the given activities; committed crew slots are kept."""
    touched_segments = []
    for activity in activities:
        if activity["status"] not in statuses:
            continue
        was_running = activity["status"] == "IN_PROGRESS"
        update(activity, status="SUSPENDED", suspension_reason=reason)
        segment = store.route_segments.get(activity["segment_id"])
        if segment is not None:
            touched_segments.append((segment, was_running))
    for segment, _was_running in touched_segments:
        if segment["construction_state"] == "ACTIVE":
            update(segment, construction_state="HALTED")


# ------------------------------------------------ certificate posture ----
def refresh_certificate_compliance(certificate):
    findings = findings_of_certificate(certificate["id"])
    rolling, cumulative = calc.compliance_indices(findings)
    update(
        certificate,
        compliance_index_rolling=rolling,
        compliance_index_cumulative=cumulative,
    )
    if certificate["posture"] == "REVOKED":
        # REVOKED is terminal: the cumulative index never recovers a certificate.
        return
    target = calc.derived_posture(rolling, cumulative)
    if target == certificate["posture"]:
        return
    apply_posture(certificate, target)


def apply_posture(certificate, target):
    previous = certificate["posture"]
    update(certificate, posture=target)
    if target == "STOP_WORK":
        suspend_activities(
            activities_of_certificate(certificate["id"]),
            "CERTIFICATE_STOP_WORK",
        )
    elif target == "REVOKED":
        suspend_activities(
            activities_of_certificate(certificate["id"]),
            "CERTIFICATE_REVOKED",
        )
    elif target == "ACTIVE" and previous == "STOP_WORK":
        # Suspended activities remain suspended until individually restarted.
        pass


def refresh_condition_status(condition):
    if condition["status"] == "WAIVED":
        return
    open_findings = [f for f in findings_of_condition(condition["id"]) if f["status"] == "OPEN"]
    if open_findings:
        update(condition, status="VIOLATED")
    elif condition["status"] == "VIOLATED":
        update(condition, status="ACTIVE")


# ------------------------------------------------------------ escrow ----
def escrow_deposit(project, amount_cents):
    update(
        project,
        escrow_funded_cents=project["escrow_funded_cents"] + amount_cents,
        escrow_balance_cents=project["escrow_balance_cents"] + amount_cents,
    )


def escrow_disburse(project, amount_cents):
    update(
        project,
        escrow_balance_cents=project["escrow_balance_cents"] - amount_cents,
        escrow_disbursed_cents=project["escrow_disbursed_cents"] + amount_cents,
    )


def escrow_restore(project, amount_cents):
    update(
        project,
        escrow_balance_cents=project["escrow_balance_cents"] + amount_cents,
        escrow_disbursed_cents=project["escrow_disbursed_cents"] - amount_cents,
    )


def escrow_release(project):
    released = project["escrow_balance_cents"]
    update(
        project,
        escrow_balance_cents=0,
        escrow_funded_cents=project["escrow_funded_cents"] - released,
    )
    return released


# ----------------------------------------------- blackout / crew help ----
def window_calendar_days(start, end):
    """Calendar days touched by the half-open window [start, end)."""
    first = start.date()
    last = end.date()
    if end.time().hour == 0 and end.time().minute == 0 and end.time().second == 0 and end.microsecond == 0:
        if last > first:
            last = last - timedelta(days=1)
    days = []
    cursor = first
    truncated = False
    while cursor <= last:
        days.append(cursor)
        if len(days) >= 800:
            truncated = cursor < last
            break
        cursor = cursor + timedelta(days=1)
    return days, truncated


def _mmdd(value):
    parts = str(value).split("-")
    return int(parts[0]), int(parts[1])


def mmdd_in_range(day, start_mmdd, end_mmdd):
    current = (day.month, day.day)
    start = _mmdd(start_mmdd)
    end = _mmdd(end_mmdd)
    if start <= end:
        return start <= current <= end
    return current >= start or current <= end


def blackout_violation(certificate, segment, window_start, window_end):
    if not segment.get("habitat_blackout"):
        return False
    conditions = [
        c
        for c in conditions_of_certificate(certificate["id"])
        if c["constraint_kind"] == "SEASONAL_BLACKOUT" and c["status"] == "ACTIVE"
    ]
    if not conditions:
        return False
    days, truncated = window_calendar_days(window_start, window_end)
    if truncated:
        return True
    for condition in conditions:
        if not condition.get("blackout_start_mmdd") or not condition.get("blackout_end_mmdd"):
            continue
        for day in days:
            if mmdd_in_range(day, condition["blackout_start_mmdd"], condition["blackout_end_mmdd"]):
                return True
    return False


def effective_crew_limit(certificate, segment):
    limit = segment["crew_capacity"]
    active_limits = [
        c["crew_limit"]
        for c in conditions_of_certificate(certificate["id"])
        if c["constraint_kind"] == "CREW_LIMIT" and c["status"] == "ACTIVE" and c.get("crew_limit") is not None
    ]
    if active_limits:
        limit = min(limit, min(active_limits))
    return limit


def overlapping_crew(segment_id, window_start, window_end, exclude_id=None):
    total = 0
    for activity in store.construction_activities.values():
        if activity["segment_id"] != segment_id:
            continue
        if exclude_id is not None and activity["id"] == exclude_id:
            continue
        if activity["status"] not in ("SCHEDULED", "IN_PROGRESS", "SUSPENDED"):
            continue
        if activity["window_start_at"] < window_end and window_start < activity["window_end_at"]:
            total += activity["crew_count"]
    return total
