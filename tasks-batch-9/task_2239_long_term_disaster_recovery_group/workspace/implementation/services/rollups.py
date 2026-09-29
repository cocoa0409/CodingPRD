"""Derived roll-ups, status derivations and shared cascades (PRD 2.5, 2.6, 2.9)."""

import db
from constants import MAX_DEFERRALS
from services import calculations as calc


# ---------------------------------------------------------------------------
# Survivor
# ---------------------------------------------------------------------------
def recompute_survivor(survivor):
    if survivor is None:
        return
    open_count = sum(
        1
        for c in db.recovery_cases.values()
        if c["survivor_id"] == survivor["id"]
        and c["case_status"] not in ("CLOSED", "INACTIVE")
    )
    db.set_field(survivor, "open_case_count", open_count)


# ---------------------------------------------------------------------------
# RecoveryCase
# ---------------------------------------------------------------------------
def recompute_case_damage_total(case):
    db.set_field(
        case, "verified_damage_total_cents", calc.verified_damage_total(case["id"])
    )


def case_presentations(case_id):
    return db.sorted_records(
        [p for p in db.presentations.values() if p["case_id"] == case_id]
    )


def case_live_presentations(case_id):
    return [
        p
        for p in case_presentations(case_id)
        if p["status"] in ("QUEUED", "PRESENTING", "DELIBERATING")
    ]


def recompute_case_funding(case):
    """calculations.case_funding_status_derivation."""
    presentation_ids = [p["id"] for p in case_presentations(case["id"])]
    total_committed = sum(
        c["pledged_cents"]
        for c in db.commitments.values()
        if c["presentation_id"] in presentation_ids
        and c["status"] in ("CONFIRMED", "DISBURSED")
    )
    total_committed += sum(
        p["bridge_authorized_cents"]
        for p in case_presentations(case["id"])
        if p["status"] == "AWARDED"
    )
    total_net_disbursed = sum(
        d["net_cents"]
        for d in db.disbursements.values()
        if d["case_id"] == case["id"] and d["status"] == "PAID"
    )

    awarded = [p for p in case_presentations(case["id"]) if p["status"] == "AWARDED"]
    reference_unmet = 0
    if awarded:
        # greatest decided_at; ties resolved by earliest created_at (the list is
        # already ordered created_at ASC and max() keeps the first maximum).
        best = max(awarded, key=lambda p: p["decided_at"] or "")
        assessment = db.assessments.get(best["assessment_id"])
        if assessment:
            reference_unmet = assessment["unmet_need_total_cents"]

    residual = max(0, reference_unmet - total_committed)

    if total_committed == 0:
        funding_status = "UNFUNDED"
    elif total_net_disbursed >= total_committed:
        funding_status = "SATISFIED"
    elif total_net_disbursed > 0:
        funding_status = "DISBURSING"
    elif total_committed >= reference_unmet:
        funding_status = "FULLY_COMMITTED"
    else:
        funding_status = "PARTIALLY_COMMITTED"

    db.set_field(case, "total_committed_cents", total_committed)
    db.set_field(case, "total_net_disbursed_cents", total_net_disbursed)
    db.set_field(case, "reference_unmet_cents", reference_unmet)
    db.set_field(case, "residual_unmet_cents", residual)
    db.set_field(case, "funding_status", funding_status)


def rewind_presented_to_assessed(case):
    """PRESENTED -> ASSESSED once no presentation of the case is live."""
    if case["case_status"] == "PRESENTED" and not case_live_presentations(case["id"]):
        db.set_field(case, "case_status", "ASSESSED")


def rewind_closure_pending(case):
    """CLOSURE_PENDING -> ACTIVE_RECOVERY when funding falls back below closure."""
    if case["case_status"] == "CLOSURE_PENDING":
        db.set_field(case, "case_status", "ACTIVE_RECOVERY")


# ---------------------------------------------------------------------------
# MemberOrganization
# ---------------------------------------------------------------------------
def recompute_member_org(org):
    if org is None:
        return
    committed = 0
    disbursed = 0
    for commitment in db.commitments.values():
        if commitment["member_org_id"] != org["id"]:
            continue
        if commitment["status"] in ("PLEDGED", "CONFIRMED"):
            committed += commitment["pledged_cents"]
        elif commitment["status"] == "DISBURSED":
            disbursed += commitment["pledged_cents"]
    remaining = org["annual_pledge_cap_cents"] - (committed + disbursed)
    db.set_field(org, "committed_cents", committed)
    db.set_field(org, "disbursed_cents", disbursed)
    db.set_field(org, "remaining_pledge_capacity_cents", remaining)
    if org["status"] == "ACTIVE" and remaining <= 0:
        db.set_field(org, "status", "CAPPED")
    elif org["status"] == "CAPPED" and remaining > 0:
        db.set_field(org, "status", "ACTIVE")


# ---------------------------------------------------------------------------
# FundingSource
# ---------------------------------------------------------------------------
def recompute_funding_source(source):
    available = (
        source["total_cents"]
        - source["committed_cents"]
        - source["disbursed_cents"]
        - source["admin_retained_cents"]
    )
    db.set_field(source, "available_cents", available)
    if source["status"] != "EXPIRED":
        db.set_field(source, "status", "EXHAUSTED" if available <= 0 else "OPEN")


# ---------------------------------------------------------------------------
# CasePresentation / TableSession
# ---------------------------------------------------------------------------
def pinned_unmet(presentation):
    assessment = db.assessments.get(presentation["assessment_id"])
    return assessment["unmet_need_total_cents"] if assessment else 0


def recompute_presentation_pledged(presentation):
    db.set_field(
        presentation,
        "pledged_total_cents",
        calc.presentation_pledged_sum(
            presentation["id"], ("PLEDGED", "CONFIRMED", "DISBURSED")
        ),
    )


def recompute_presentation_award(presentation):
    """awarded_cents = live pledged total + bridge authorization (AWARDED only)."""
    if presentation["status"] != "AWARDED":
        return
    awarded = presentation["pledged_total_cents"] + presentation[
        "bridge_authorized_cents"
    ]
    db.set_field(presentation, "awarded_cents", awarded)
    db.set_field(
        presentation,
        "shortfall_cents",
        max(0, pinned_unmet(presentation) - awarded),
    )


def recompute_queue(session_id):
    if session_id is None:
        return
    rows = db.sorted_records(
        [p for p in db.presentations.values() if p["session_id"] == session_id]
    )
    queued = [p for p in rows if p["status"] == "QUEUED"]
    queued.sort(
        key=lambda p: (
            -p["priority_score_snapshot"],
            -pinned_unmet(p),
            p["created_at"],
            p["_seq"],
        )
    )
    for index, presentation in enumerate(queued, start=1):
        db.set_field(presentation, "queue_position", index)
    for presentation in rows:
        if presentation["status"] != "QUEUED":
            db.set_field(presentation, "queue_position", 0)
    session = db.table_sessions.get(session_id)
    if session is not None:
        db.set_field(session, "queued_count", len(queued))


def recompute_session_totals(session):
    awarded_total = sum(
        p["awarded_cents"]
        for p in db.presentations.values()
        if p["session_id"] == session["id"] and p["status"] == "AWARDED"
    )
    db.set_field(session, "awarded_total_cents", awarded_total)


def session_has_active_presentation(session_id):
    return any(
        p["session_id"] == session_id
        and p["status"] in ("PRESENTING", "DELIBERATING")
        for p in db.presentations.values()
    )


# ---------------------------------------------------------------------------
# Construction / volunteers / lodging
# ---------------------------------------------------------------------------
def project_deployments(project_id):
    return db.sorted_records(
        [d for d in db.deployments.values() if d["project_id"] == project_id]
    )


def recompute_project_counts(project):
    if project is None:
        return
    count = sum(
        1
        for d in db.deployments.values()
        if d["project_id"] == project["id"]
        and d["status"] in ("REQUESTED", "CONFIRMED")
    )
    db.set_field(project, "confirmed_deployment_count", count)


def recompute_group_counts(group):
    if group is None:
        return
    count = sum(
        1
        for d in db.deployments.values()
        if d["group_id"] == group["id"] and d["status"] in ("REQUESTED", "CONFIRMED")
    )
    db.set_field(group, "active_deployment_count", count)


def site_peak_beds(site_id):
    """Maximum beds committed on any single night by ACTIVE assignments."""
    events = []
    for assignment in db.housing_assignments.values():
        if assignment["lodging_site_id"] != site_id:
            continue
        if assignment["status"] != "ACTIVE":
            continue
        check_in = calc.to_date(assignment["check_in_date"])
        check_out = calc.to_date(assignment["check_out_date"])
        if check_out <= check_in:
            continue
        events.append((check_in, 1, assignment["beds_requested"]))
        events.append((check_out, 0, -assignment["beds_requested"]))
    if not events:
        return 0
    events.sort(key=lambda e: (e[0], e[1]))
    running = 0
    peak = 0
    for _, _, delta in events:
        running += delta
        peak = max(peak, running)
    return peak


def recompute_lodging_site(site):
    if site is None:
        return
    peak = site_peak_beds(site["id"])
    db.set_field(site, "peak_committed_beds", peak)
    db.set_field(site, "available_beds", max(0, site["bed_capacity"] - peak))
    db.set_field(site, "status", "FULL" if peak >= site["bed_capacity"] else "OPEN")


def release_housing_assignment(assignment, reason):
    db.set_field(assignment, "status", "RELEASED")
    db.set_field(assignment, "released_at", db.clock_iso())
    db.set_field(assignment, "release_reason", reason)
    recompute_lodging_site(db.lodging_sites.get(assignment["lodging_site_id"]))


def group_active_assignments(group_id):
    return db.sorted_records(
        [
            a
            for a in db.housing_assignments.values()
            if a["group_id"] == group_id and a["status"] == "ACTIVE"
        ]
    )


def cancel_deployment(deployment, cancellation_reason):
    """Deployment REQUESTED/CONFIRMED -> CANCELLED with the housing cascade."""
    was_confirmed = deployment["status"] == "CONFIRMED"
    db.set_field(deployment, "status", "CANCELLED")
    db.set_field(deployment, "cancellation_reason", cancellation_reason)
    if was_confirmed:
        arrival = calc.to_date(deployment["arrival_date"])
        departure = calc.to_date(deployment["departure_date"])
        for assignment in group_active_assignments(deployment["group_id"]):
            check_in = calc.to_date(assignment["check_in_date"])
            check_out = calc.to_date(assignment["check_out_date"])
            # half-open night interval intersecting [arrival, departure)
            if check_in < departure and arrival < check_out:
                release_housing_assignment(assignment, "DEPLOYMENT_CANCELLED")
    recompute_group_counts(db.volunteer_groups.get(deployment["group_id"]))
    recompute_project_counts(db.projects.get(deployment["project_id"]))


def cancel_live_deployments(project, cancellation_reason):
    for deployment in project_deployments(project["id"]):
        if deployment["status"] in ("REQUESTED", "CONFIRMED"):
            cancel_deployment(deployment, cancellation_reason)


# ---------------------------------------------------------------------------
# Commitment rescission helper (shared by the table cascade and the endpoint)
# ---------------------------------------------------------------------------
def rescind_commitment(commitment, reason):
    db.set_field(commitment, "status", "RESCINDED")
    db.set_field(commitment, "rescission_reason", reason)
    recompute_member_org(db.member_orgs.get(commitment["member_org_id"]))


def adjourn_queue_cascade(session):
    """Defer every still-queued presentation, denying those out of deferrals."""
    queued = [
        p
        for p in db.sorted_records(list(db.presentations.values()))
        if p["session_id"] == session["id"] and p["status"] == "QUEUED"
    ]
    queued.sort(key=lambda p: (p["queue_position"], p["created_at"], p["_seq"]))
    denied_cases = []
    for presentation in queued:
        if presentation["deferral_count"] < MAX_DEFERRALS:
            # Deferral branch: the case's case_status stays PRESENTED.
            db.set_field(presentation, "status", "DEFERRED")
            db.set_field(
                presentation, "deferral_count", presentation["deferral_count"] + 1
            )
            continue
        db.set_field(presentation, "status", "DENIED")
        db.set_field(presentation, "awarded_cents", 0)
        for commitment in db.sorted_records(list(db.commitments.values())):
            if (
                commitment["presentation_id"] == presentation["id"]
                and commitment["status"] == "PLEDGED"
            ):
                rescind_commitment(commitment, "MAX_DEFERRALS_REACHED")
        recompute_presentation_pledged(presentation)
        case = db.recovery_cases.get(presentation["case_id"])
        if case is not None and all(c is not case for c in denied_cases):
            denied_cases.append(case)
    recompute_queue(session["id"])
    for case in denied_cases:
        rewind_presented_to_assessed(case)
    recompute_session_totals(session)
