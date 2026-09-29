"""Domain services: aggregate recomputation and the cascades of PRD 2.7."""

from datetime import date

import calc
from clock import clock
from db import base_record, ordered, public, store, touch
from validate import as_date

# --------------------------------------------------------------------------
# collection helpers
# --------------------------------------------------------------------------


def project_costs(project_id):
    return ordered([c for c in store.cost_line_items.values() if c["project_id"] == project_id])


def project_apps(project_id):
    return ordered([a for a in store.part_applications.values() if a["project_id"] == project_id])


def project_interests(project_id):
    return ordered([i for i in store.investor_interests.values() if i["project_id"] == project_id])


def project_claims(project_id):
    return ordered([c for c in store.credit_claims.values() if c["project_id"] == project_id])


def project_events(project_id):
    return ordered([e for e in store.recapture_events.values() if e["project_id"] == project_id])


def project_covenants(project_id):
    return ordered(
        [c for c in store.compliance_covenants.values() if c["project_id"] == project_id]
    )


def app_findings(application_id):
    return ordered([f for f in store.findings.values() if f["part_application_id"] == application_id])


def property_open_project_count(property_id):
    open_states = {"PRE_CERTIFICATION", "PART1_CERTIFIED", "PART2_APPROVED", "PART3_CERTIFIED"}
    return sum(
        1
        for p in store.projects.values()
        if p["property_id"] == property_id and p["certification_status"] in open_states
    )


# --------------------------------------------------------------------------
# serializers
# --------------------------------------------------------------------------


def property_out(prop):
    return public(prop, {"open_project_count": property_open_project_count(prop["id"])})


def out(rec):
    return public(rec)


# --------------------------------------------------------------------------
# measuring period / cost flags
# --------------------------------------------------------------------------


def measuring_period_end(start, months):
    return calc.add_months(start, months)


def in_measuring_period(project, incurred):
    start = as_date(project["measuring_period_start_date"])
    end = as_date(project["measuring_period_end_date"])
    return start <= incurred < end


def reevaluate_cost_windows(project):
    """Re-derive in_measuring_period on every cost item of the project."""
    for item in project_costs(project["id"]):
        flag = in_measuring_period(project, as_date(item["incurred_date"]))
        if item["in_measuring_period"] != flag:
            item["in_measuring_period"] = flag
            touch(item)


# --------------------------------------------------------------------------
# financial recomputation (qre_totals -> substantial test -> credit schedule)
# --------------------------------------------------------------------------


def recompute_financials(project):
    """Runs the three calculations in their normative order.

    Returns (previous_substantial_test_status, new_substantial_test_status).
    """
    items = project_costs(project["id"])
    final = calc.qre_totals(items, "FINAL")
    provisional = calc.qre_totals(items, "PROVISIONAL")

    project["qre_total_final_cents"] = final["qre_total"]
    project["qre_total_provisional_cents"] = provisional["qre_total"]
    project["nonqualified_total_cents"] = final["nonqualified_total"]
    project["classified_cost_total_cents"] = final["classified_cost_total"]
    project["developer_fee_disallowed_cents"] = final["fee_disallowed"]

    project["substantial_test_threshold_cents"] = calc.substantial_threshold(
        project["adjusted_basis_cents"]
    )
    previous = project["substantial_test_status"]
    project["substantial_test_status"] = calc.substantial_status(
        project["qre_total_final_cents"], project["substantial_test_threshold_cents"]
    )

    if not project["frozen_at_certification"]:
        annual, total = calc.ratable_credit(
            project["qre_total_final_cents"], project["substantial_test_status"]
        )
        project["annual_credit_cents"] = annual
        project["total_claimable_credit_cents"] = total

    refresh_unclaimed(project)
    return previous, project["substantial_test_status"]


def refresh_unclaimed(project):
    project["credit_unclaimed_cents"] = (
        project["total_claimable_credit_cents"]
        - project["credit_claimed_to_date_cents"]
        - project["credit_recaptured_cents"]
    )


# --------------------------------------------------------------------------
# investor risk scoring
# --------------------------------------------------------------------------


def breached_covenant_count(project_id):
    return sum(1 for c in project_covenants(project_id) if c["status"] == "BREACHED")


def unresolved_violation_total(project_id):
    return sum(
        a["unresolved_violation_count"]
        for a in project_apps(project_id)
        if a["status"] != "SUPERSEDED"
    )


def score_of(interest, variant, project_id):
    if variant == "ADMISSION":
        return calc.risk_score(interest, "ADMISSION")
    return calc.risk_score(
        interest,
        "IN_SERVICE",
        breached_covenant_count(project_id),
        unresolved_violation_total(project_id),
    )


def apply_score(interest, variant):
    """Writes the score; bumps the interest version only when something changed."""
    score = score_of(interest, variant, interest["project_id"])
    if interest["disqualification_risk_score"] == score and interest["risk_variant_applied"] == variant:
        return False
    interest["disqualification_risk_score"] = score
    interest["risk_variant_applied"] = variant
    touch(interest)
    return True


def refresh_max_risk(project):
    scores = [
        i["disqualification_risk_score"]
        for i in project_interests(project["id"])
        if i["status"] == "ADMITTED"
    ]
    value = max(scores) if scores else 0
    if project["max_investor_risk_score"] == value:
        return False
    project["max_investor_risk_score"] = value
    return True


def rescore_in_service(project):
    """Re-scores every ADMITTED interest under the IN_SERVICE variant."""
    changed = False
    for interest in project_interests(project["id"]):
        if interest["status"] == "ADMITTED":
            changed = apply_score(interest, "IN_SERVICE") or changed
    changed = refresh_max_risk(project) or changed
    return changed


def disqualify_master_lessees(project):
    changed = False
    for interest in project_interests(project["id"]):
        if interest["status"] == "ADMITTED" and interest["kind"] == "MASTER_LEASE_LESSEE":
            interest["status"] = "DISQUALIFIED"
            touch(interest)
            changed = True
    if changed:
        refresh_max_risk(project)
    return changed


# --------------------------------------------------------------------------
# findings counters
# --------------------------------------------------------------------------


def recompute_finding_counts(application):
    findings = app_findings(application["id"])
    application["unresolved_condition_count"] = sum(
        1 for f in findings if f["severity"] == "CONDITION" and f["resolution_state"] == "UNRESOLVED"
    )
    application["unresolved_violation_count"] = sum(
        1 for f in findings if f["severity"] == "VIOLATION" and f["resolution_state"] == "UNRESOLVED"
    )


# --------------------------------------------------------------------------
# certification cascade
# --------------------------------------------------------------------------

_CERT_STEPS = {
    1: ("PRE_CERTIFICATION", "PART1_CERTIFIED"),
    2: ("PART1_CERTIFIED", "PART2_APPROVED"),
    3: ("PART2_APPROVED", "PART3_CERTIFIED"),
}


def advance_certification(project, part_number):
    """Cascade hop: advance the certification dimension for an approved part."""
    origin, target = _CERT_STEPS[part_number]
    if project["certification_status"] != origin:
        return False
    project["certification_status"] = target
    if part_number == 3:
        project["frozen_at_certification"] = True
        lock_cost_items(project)
    touch(project)
    return True


def lock_cost_items(project):
    for item in project_costs(project["id"]):
        if item["classification"] == "QRE":
            item["classification"] = "LOCKED_QRE"
            touch(item)
        elif item["classification"] == "NON_QRE":
            item["classification"] = "LOCKED_NON_QRE"
            touch(item)


def decertify(project, prop):
    """Part 1 denial cascade: property NON_CERTIFIED, project DECERTIFIED."""
    if project["certification_status"] != "PRE_CERTIFICATION":
        return False
    prop["evaluation_status"] = "NON_CERTIFIED"
    touch(prop)
    project["certification_status"] = "DECERTIFIED"
    touch(project)
    return True


def certify_property(prop):
    prop["evaluation_status"] = "CERTIFIED_HISTORIC"
    prop["certified_at"] = clock.now_iso()
    touch(prop)


# --------------------------------------------------------------------------
# recapture
# --------------------------------------------------------------------------


def assess_recapture(project, event_type, event_date, source):
    """Creates a RecaptureEvent row and raises the project's recapture balance."""
    full_years, pct, amount = calc.recapture_assessment(
        as_date(project["placed_in_service_date"]),
        event_date,
        event_type,
        project["credit_claimed_to_date_cents"],
    )
    event = base_record()
    event.update(
        {
            "project_id": project["id"],
            "event_type": event_type,
            "event_date": event_date.isoformat(),
            "full_years_elapsed": full_years,
            "recapture_pct": float(pct),
            "recapture_amount_cents": amount,
            "status": "ASSESSED",
            "source": source,
        }
    )
    store.recapture_events[event["id"]] = event
    project["recapture_balance_cents"] += amount
    return event


def settle_recapture_events(project):
    """An ASSESSED event settles once the balance has been driven back to zero."""
    if project["recapture_balance_cents"] != 0:
        return False
    changed = False
    for event in project_events(project["id"]):
        if event["status"] == "ASSESSED":
            event["status"] = "SETTLED"
            touch(event)
            changed = True
    return changed


def substantial_failure_cascade(project):
    """The one situation in which the system raises its own recapture event."""
    assess_recapture(project, "SUBSTANTIAL_TEST_FAILURE", clock.today(), "SYSTEM_DERIVED")
    if project["compliance_status"] == "IN_SERVICE_MONITORING":
        project["compliance_status"] = "CURE_PENDING"
        rescore_in_service(project)
    for claim in project_claims(project["id"]):
        if claim["status"] == "FILED":
            claim["status"] = "ADJUSTED"
            touch(claim)
    refresh_unclaimed(project)


def enter_cure_pending(project):
    """IN_SERVICE_MONITORING -> CURE_PENDING with its re-scoring hops."""
    if project["compliance_status"] != "IN_SERVICE_MONITORING":
        return False
    project["compliance_status"] = "CURE_PENDING"
    rescore_in_service(project)
    return True


def leave_cure_pending(project):
    """CURE_PENDING -> IN_SERVICE_MONITORING when nothing is outstanding."""
    if project["compliance_status"] != "CURE_PENDING":
        return False
    if project["recapture_balance_cents"] != 0:
        return False
    if breached_covenant_count(project["id"]) > 0:
        return False
    project["compliance_status"] = "IN_SERVICE_MONITORING"
    settle_recapture_events(project)
    return True


def monitoring_end_date(project):
    return calc.add_days(
        as_date(project["placed_in_service_date"]),
        calc.COMPLIANCE_PERIOD_YEARS * calc.DAYS_PER_YEAR,
    )
