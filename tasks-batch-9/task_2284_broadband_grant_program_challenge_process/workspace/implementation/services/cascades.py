"""The three multi-hop atomic cascades (PRD sections 2.7, 3.3, 3.7, 3.9)."""

from db import db
from records import assign, touch
from services import domain


def sustain_cascade(challenge, location):
    """Four hops: reclassify -> claims -> sheets/application -> program posture."""
    # hop 1 - the contested location is reclassified
    assign(location, "classification_status", challenge["asserted_classification"])
    assign(location, "classification_source", "CHALLENGE_DETERMINATION")
    if location["eligibility_state"] == "CHALLENGED":
        assign(location, "eligibility_state", "RECLASSIFIED")
    touch(location)

    # hop 2 - ineligible claims on the location become eligible again
    affected = []
    if location["classification_status"] in ("UNSERVED", "UNDERSERVED"):
        for claim in domain.claims_of_location(location["id"]):
            if claim["claim_state"] != "CLAIMED_INELIGIBLE":
                continue
            assign(claim, "claim_state", "CLAIMED_ELIGIBLE")
            touch(claim)
            application = db.applications.get(claim["application_id"])
            if application is not None and application["id"] not in [a["id"] for a in affected]:
                affected.append(application)

    # hop 3 - score sheets go stale and scored applications need a rescore
    for application in affected:
        domain.refresh_application(application)
        for sheet in domain.score_sheets_of_application(application["id"]):
            if sheet["score_state"] == "FINAL":
                assign(sheet, "score_state", "STALE")
                touch(sheet)
        if application["application_state"] == "SCORED":
            assign(application, "application_state", "RESCORE_REQUIRED")
            assign(application, "rescore_required_reason", "CHALLENGE_RECLASSIFICATION")
        touch(application)

    # hop 4 - the program posture is recomputed
    program = db.programs.get(challenge["program_id"])
    if program is not None:
        domain.refresh_program(program)


def termination_cascade(award, terminated_reason):
    """Four hops: deobligate -> balances -> claims/milestones -> locations/application."""
    application = domain.application_of_award(award)
    program = domain.program_of_award(award)
    bound_locations = domain.locations_of_award(award["id"])

    undisbursed = int(award["obligation_amount_cents"]) - int(award["disbursed_to_date_cents"])
    assign(award, "award_state", "TERMINATED")
    assign(award, "terminated_reason", terminated_reason)

    # hop 1 + hop 2 - the undisbursed balance is deobligated and balances re-derived
    if undisbursed > 0:
        domain.append_ledger(award, "DEOBLIGATION", undisbursed, terminated_reason,
                             "Deobligation of the undisbursed award balance on termination")

    # hop 3 - bound claims are released and live milestones voided
    if application is not None:
        for claim in domain.claims_of_application(application["id"]):
            if claim["claim_state"] == "AWARD_BOUND":
                assign(claim, "claim_state", "RELEASED")
                touch(claim)
    for milestone in domain.milestones_of_award(award["id"]):
        if milestone["milestone_state"] not in ("DISBURSED", "VOIDED"):
            assign(milestone, "milestone_state", "VOIDED")
            touch(milestone)

    # hop 4 - locations are freed, the application loses its award, posture recomputed
    for location in bound_locations:
        if location["eligibility_state"] == "AWARD_BOUND":
            assign(location, "eligibility_state", "AFFIRMED")
        if location["service_state"] == "UNDER_CONSTRUCTION":
            assign(location, "service_state", "NOT_BUILT")
        assign(location, "awarded_award_id", None)
        touch(location)

    if application is not None:
        if application["application_state"] == "AWARDED":
            assign(application, "application_state", "NOT_SELECTED")
        domain.refresh_application(application)
        touch(application)

    domain.refresh_award(award)
    touch(award)
    if program is not None:
        domain.refresh_program(program)


def audit_failure_cascade(audit, award):
    """Three hops: locations/award -> milestones held -> subgrantee suspended."""
    # hop 1
    for location_id in audit.get("failed_location_ids") or []:
        location = db.locations.get(location_id)
        if location is None:
            continue
        if location["service_state"] in ("SERVICE_AVAILABLE", "CERTIFIED"):
            if location["service_state"] == "CERTIFIED":
                assign(location, "certified_at", None)
            assign(location, "service_state", "AUDIT_FAILED")
            touch(location)
    if award["compliance_state"] in ("COMPLIANT", "CURED"):
        assign(award, "compliance_state", "NONCOMPLIANT")
    domain.refresh_award(award)
    touch(award)

    # hop 2
    held_any = False
    for milestone in domain.milestones_of_award(award["id"]):
        if milestone["milestone_state"] in ("EVIDENCE_SUBMITTED", "APPROVED"):
            assign(milestone, "milestone_state", "HELD")
            assign(milestone, "payable_amount_cents", 0)
            touch(milestone)
            held_any = True

    # hop 3
    subgrantee = domain.subgrantee_of_award(award)
    if subgrantee is not None:
        domain.refresh_subgrantee(subgrantee)
        if held_any and subgrantee["capability_state"] == "QUALIFIED":
            assign(subgrantee, "capability_state", "SUSPENDED")
        touch(subgrantee)


def remediation_cascade(audit, award):
    """verify-remediation: release the failed locations, milestones and subgrantee."""
    for location_id in audit.get("failed_location_ids") or []:
        location = db.locations.get(location_id)
        if location is None:
            continue
        if location["service_state"] == "AUDIT_FAILED":
            assign(location, "service_state", "SERVICE_AVAILABLE")
            touch(location)

    if award["compliance_state"] == "NONCOMPLIANT":
        assign(award, "compliance_state", "CURED")
    domain.refresh_award(award)
    touch(award)

    for milestone in domain.milestones_of_award(award["id"]):
        if milestone["milestone_state"] == "HELD":
            assign(milestone, "milestone_state", "EVIDENCE_SUBMITTED")
            assign(milestone, "payable_amount_cents", 0)
            touch(milestone)

    subgrantee = domain.subgrantee_of_award(award)
    if subgrantee is not None:
        had_open = int(subgrantee.get("open_noncompliance_count") or 0)
        domain.refresh_subgrantee(subgrantee)
        if (subgrantee["capability_state"] == "SUSPENDED"
                and had_open == 1
                and int(subgrantee["open_noncompliance_count"]) == 0):
            assign(subgrantee, "capability_state", "QUALIFIED")
        touch(subgrantee)
