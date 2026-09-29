"""Assessment engagements, test slots, reports, findings and deviation requests."""
from decimal import Decimal

from flask import Blueprint

import calc
import services as svc
from core import (
    AGENCY_OFFICIAL,
    ANY_ROLE,
    ASSESSOR,
    BOARD,
    LEAD,
    authenticate,
    body,
    created,
    db,
    fail,
    listing,
    lookup,
    new_record,
    now,
    ok,
    opt_enum,
    opt_int,
    opt_str,
    pagination,
    paginate,
    parse_instant,
    query_enum,
    query_str,
    req_enum,
    req_instant,
    req_money,
    req_str,
    role,
    rows,
    touch,
    uid,
)

bp = Blueprint("assessment", __name__)

ENGAGEMENT_STATUSES = (
    "DRAFT",
    "PLAN_SUBMITTED",
    "PLAN_APPROVED",
    "TESTING",
    "REPORT_DELIVERED",
    "VOIDED",
)
SLOT_STATUSES = ("SCHEDULED", "COMPLETED", "CANCELLED")
SEVERITIES = ("HIGH", "MODERATE", "LOW")
SOURCES = ("ASSESSMENT", "SCAN", "SELF_IDENTIFIED")
REMEDIATION_STATUSES = ("OPEN", "IN_REMEDIATION", "AWAITING_VERIFICATION", "CLOSED")
DISPOSITIONS = (
    "NONE",
    "DEVIATION_REQUESTED",
    "EXTENSION_GRANTED",
    "RISK_ACCEPTED",
    "FALSE_POSITIVE_ACCEPTED",
)
DEVIATION_KINDS = ("OPERATIONAL_REQUIREMENT", "FALSE_POSITIVE", "RISK_ADJUSTMENT")
DEVIATION_STATUSES = ("SUBMITTED", "BOARD_REVIEW", "AGENCY_REVIEW", "APPROVED", "DENIED")
QUEUES = ("BOARD", "AGENCY")
ACTIONS = ("START", "SUBMIT_EVIDENCE", "VERIFY_CLOSE", "REOPEN")
LEAD_ACTIONS = ("START", "SUBMIT_EVIDENCE")
ASSESSOR_ACTIONS = ("VERIFY_CLOSE", "REOPEN")
PENDING_DEVIATION_STATUSES = ("SUBMITTED", "BOARD_REVIEW", "AGENCY_REVIEW")


# ---------------------------------------------------------------------------
# Engagements
# ---------------------------------------------------------------------------


@bp.post("/assessment-engagements")
def create_engagement():
    authenticate((LEAD,))
    b = body()
    offering_id = req_str(b, "offering_id")
    org_name = req_str(b, "assessor_org_name")
    assessor_user_id = req_str(b, "assessor_user_id")
    contracted_hours = req_money(b, "contracted_hours")
    labor_cost = req_money(b, "labor_cost_usd")
    offering = lookup("offerings", offering_id)
    svc.require_offering_owner(offering, uid())
    pricing = calc.engagement_cost(offering, contracted_hours, labor_cost)
    rec = new_record()
    rec.update(
        {
            "offering_id": offering["id"],
            "assessor_org_name": org_name,
            "assessor_user_id": assessor_user_id,
            "contracted_hours": contracted_hours,
            "allocated_hours": Decimal("0.00"),
            "unallocated_hours": contracted_hours,
            "labor_cost_usd": labor_cost,
            "surcharge_rate": pricing["surcharge_rate"],
            "program_surcharge_usd": pricing["program_surcharge_usd"],
            "hour_overage_usd": pricing["hour_overage_usd"],
            "total_cost_usd": pricing["total_cost_usd"],
            "planned_test_start": None,
            "planned_test_end": None,
            "status": "DRAFT",
            "plan_revision_round": 0,
            "findings_reported_count": 0,
        }
    )
    db.engagements[rec["id"]] = rec
    return created(rec)


@bp.get("/assessment-engagements/<ident>")
def read_engagement(ident):
    authenticate(ANY_ROLE)
    return ok(lookup("engagements", ident))


@bp.get("/offerings/<ident>/assessment-engagements")
def list_engagements(ident):
    authenticate(ANY_ROLE)
    status = query_enum("status", ENGAGEMENT_STATUSES)
    limit, offset = pagination()
    offering = lookup("offerings", ident)
    result = [e for e in rows("engagements") if e["offering_id"] == offering["id"]]
    if status is not None:
        result = [e for e in result if e["status"] == status]
    page, total = paginate(result, limit, offset)
    return listing(page, limit, offset, total)


@bp.post("/assessment-engagements/<ident>/plan")
def submit_plan(ident):
    authenticate((ASSESSOR,))
    b = body()
    start = req_instant(b, "planned_test_start")
    end = req_instant(b, "planned_test_end")
    engagement = lookup("engagements", ident)
    svc.require_engagement_assessor(engagement, uid())
    if engagement["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "Plan submission requires the engagement to be in DRAFT.")
    if not start < end:
        fail("ERR_WINDOW_INVALID", "planned_test_start must be strictly before planned_test_end.")
    engagement["planned_test_start"] = start
    engagement["planned_test_end"] = end
    engagement["status"] = "PLAN_SUBMITTED"
    touch(engagement)
    return ok(engagement)


@bp.post("/assessment-engagements/<ident>/plan-approval")
def plan_approval(ident):
    actor_role = authenticate((BOARD, AGENCY_OFFICIAL))[1]
    engagement = db.engagements.get(ident)
    offering = db.offerings.get(engagement["offering_id"]) if engagement else None
    if engagement is not None and offering is not None:
        _require_path_queue(offering.get("authorization_path"), actor_role)
    b = body()
    decision = req_enum(b, "decision", ("APPROVE", "REJECT"))
    if engagement is None:
        fail("ERR_ENGAGEMENT_NOT_FOUND")
    if engagement["status"] != "PLAN_SUBMITTED":
        fail("ERR_INVALID_STATE", "Plan approval requires the engagement to be PLAN_SUBMITTED.")
    if decision == "APPROVE" and (offering is None or offering["status"] != "PATH_SELECTED"):
        fail("ERR_INVALID_STATE", "Plan approval requires the offering to be PATH_SELECTED.")
    _require_sponsor(offering, actor_role)
    if decision == "APPROVE":
        engagement["status"] = "PLAN_APPROVED"
        touch(engagement)
        offering["status"] = "IN_ASSESSMENT"
        touch(offering)
    else:
        engagement["status"] = "DRAFT"
        engagement["plan_revision_round"] = int(engagement["plan_revision_round"]) + 1
        engagement["planned_test_start"] = None
        engagement["planned_test_end"] = None
        touch(engagement)
    return ok(engagement)


def _require_path_queue(authorization_path, actor_role):
    """Validation tier 4: the acting role owns the path that owns the decision."""
    if authorization_path == "PROGRAM_BOARD" and actor_role != BOARD:
        fail("ERR_WRONG_REVIEW_QUEUE", "This decision belongs to a ProgramBoardReviewer.")
    if authorization_path == "AGENCY_SPONSORED" and actor_role != AGENCY_OFFICIAL:
        fail("ERR_WRONG_REVIEW_QUEUE", "This decision belongs to the sponsoring agency official.")


def _require_sponsor(offering, actor_role):
    """Validation tier 34."""
    if actor_role != AGENCY_OFFICIAL or offering is None:
        return
    if offering.get("sponsor_agency_id") != uid():
        fail("ERR_SPONSOR_AGENCY_MISMATCH", "The acting official is not the offering's sponsor.")


# ---------------------------------------------------------------------------
# Test slots
# ---------------------------------------------------------------------------


@bp.post("/test-slots")
def create_test_slot():
    authenticate((ASSESSOR,))
    b = body()
    engagement_id = req_str(b, "engagement_id")
    family_code = req_str(b, "family_code")
    start = req_instant(b, "start_at")
    end = req_instant(b, "end_at")
    hours = req_money(b, "hours")
    engagement = lookup("engagements", engagement_id)
    svc.require_engagement_assessor(engagement, uid())
    if engagement["status"] not in ("PLAN_APPROVED", "TESTING"):
        fail("ERR_INVALID_STATE", "Slots may only be scheduled on an approved engagement.")
    if not start < end:
        fail("ERR_WINDOW_INVALID", "start_at must be strictly before end_at.")
    for other in calc.slots_of(engagement["id"]):
        if other["status"] not in ("SCHEDULED", "COMPLETED"):
            continue
        if calc.slots_overlap(start, end, other["start_at"], other["end_at"]):
            fail("ERR_TEST_SLOT_OVERLAP", "The slot overlaps an existing slot of this engagement.")
    if hours > engagement["unallocated_hours"]:
        fail("ERR_ENGAGEMENT_HOURS_EXHAUSTED", "The engagement has insufficient unallocated hours.")
    rec = new_record()
    rec.update(
        {
            "engagement_id": engagement["id"],
            "family_code": family_code,
            "start_at": start,
            "end_at": end,
            "hours": hours,
            "status": "SCHEDULED",
        }
    )
    db.test_slots[rec["id"]] = rec
    if engagement["status"] == "PLAN_APPROVED":
        engagement["status"] = "TESTING"
    svc.sync_engagement_hours(engagement)
    touch(engagement)
    return created(rec)


@bp.post("/test-slots/<ident>/cancel")
def cancel_test_slot(ident):
    authenticate((ASSESSOR,))
    body()
    slot = lookup("test_slots", ident)
    engagement = db.engagements.get(slot["engagement_id"])
    if engagement is not None:
        svc.require_engagement_assessor(engagement, uid())
    if slot["status"] != "SCHEDULED":
        fail("ERR_ALREADY_TERMINAL", "Only a SCHEDULED slot may be cancelled.")
    slot["status"] = "CANCELLED"
    touch(slot)
    if engagement is not None:
        svc.sync_engagement_hours(engagement)
        touch(engagement)
    return ok(slot)


@bp.get("/assessment-engagements/<ident>/test-slots")
def list_test_slots(ident):
    authenticate(ANY_ROLE)
    status = query_enum("status", SLOT_STATUSES)
    limit, offset = pagination()
    engagement = lookup("engagements", ident)
    result = calc.slots_of(engagement["id"])
    if status is not None:
        result = [s for s in result if s["status"] == status]
    page, total = paginate(result, limit, offset)
    return listing(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Assessment report
# ---------------------------------------------------------------------------


@bp.post("/assessment-engagements/<ident>/report")
def deliver_report(ident):
    authenticate((ASSESSOR,))
    b = body()
    raw = b.get("findings")
    if raw is None:
        fail("ERR_INVALID_REQUEST", "Field 'findings' is required.")
    if not isinstance(raw, list):
        fail("ERR_INVALID_REQUEST", "Field 'findings' must be an array.")
    findings = []
    for element in raw:
        if not isinstance(element, dict):
            fail("ERR_INVALID_REQUEST", "Each 'findings' element must be an object.")
        findings.append(
            {
                "control_id": req_str(element, "control_id"),
                "severity": req_enum(element, "severity", SEVERITIES),
                "detected_at": req_instant(element, "detected_at"),
            }
        )
    engagement = lookup("engagements", ident)
    svc.require_engagement_assessor(engagement, uid())
    if engagement["status"] != "TESTING":
        fail("ERR_INVALID_STATE", "Report delivery requires the engagement to be TESTING.")
    clock = now()
    for element in findings:
        if element["detected_at"] > clock:
            fail("ERR_DETECTION_DATE_IN_FUTURE", "detected_at must not be after the logical clock.")
    for element in findings:
        svc.create_poam_item(
            engagement["offering_id"],
            element["control_id"],
            element["severity"],
            element["detected_at"],
            "ASSESSMENT",
        )
    engagement["findings_reported_count"] = len(findings)
    svc.complete_scheduled_slots(engagement)
    engagement["status"] = "REPORT_DELIVERED"
    touch(engagement)
    return ok(engagement)


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------


@bp.post("/poam-items")
def create_poam_item():
    authenticate((LEAD,))
    b = body()
    offering_id = req_str(b, "offering_id")
    control_id = req_str(b, "control_id")
    severity = req_enum(b, "severity", SEVERITIES)
    detected_at = req_instant(b, "detected_at")
    source = opt_enum(b, "source", SOURCES, "SELF_IDENTIFIED")
    supersedes_id = opt_str(b, "supersedes_item_id", None)
    offering = lookup("offerings", offering_id)
    target = None
    if supersedes_id is not None:
        target = lookup("poam_items", supersedes_id)
    svc.require_offering_owner(offering, uid())
    if target is not None and target["remediation_status"] == "CLOSED":
        fail("ERR_ALREADY_TERMINAL", "The superseded finding is already CLOSED.")
    if detected_at > now():
        fail("ERR_DETECTION_DATE_IN_FUTURE", "detected_at must not be after the logical clock.")
    if target is not None and target["offering_id"] != offering["id"]:
        fail("ERR_SUPERSEDED_ITEM_MISMATCH", "The superseded finding belongs to another offering.")
    item = svc.create_poam_item(
        offering["id"], control_id, severity, detected_at, source, supersedes_id
    )
    if target is not None:
        target["remediation_status"] = "CLOSED"
        target["closure_reason"] = "SUPERSEDED"
        touch(target)
    svc.refresh_authorization_for_offering(offering["id"])
    return created(item)


@bp.get("/poam-items/<ident>")
def read_poam_item(ident):
    authenticate(ANY_ROLE)
    return ok(lookup("poam_items", ident))


@bp.get("/poam-items")
def list_poam_items():
    authenticate(ANY_ROLE)
    offering_id = query_str("offering_id")
    supersedes_id = query_str("supersedes_item_id")
    remediation_status = query_enum("remediation_status", REMEDIATION_STATUSES)
    disposition = query_enum("risk_disposition", DISPOSITIONS)
    severity = query_enum("severity", SEVERITIES)
    source = query_enum("source", SOURCES)
    limit, offset = pagination()
    result = rows("poam_items")
    if offering_id is not None:
        result = [i for i in result if i["offering_id"] == offering_id]
    if supersedes_id is not None:
        result = [i for i in result if i["supersedes_item_id"] == supersedes_id]
    if remediation_status is not None:
        result = [i for i in result if i["remediation_status"] == remediation_status]
    if disposition is not None:
        result = [i for i in result if i["risk_disposition"] == disposition]
    if severity is not None:
        result = [i for i in result if i["severity"] == severity]
    if source is not None:
        result = [i for i in result if i["source"] == source]
    page, total = paginate(result, limit, offset)
    return listing(page, limit, offset, total)


@bp.post("/poam-items/<ident>/remediation")
def remediation(ident):
    actor_role = authenticate((LEAD, ASSESSOR))[1]
    b = body()
    raw_action = b.get("action")
    if isinstance(raw_action, str) and raw_action in ACTIONS:
        if raw_action in LEAD_ACTIONS and actor_role != LEAD:
            fail("ERR_ACTION_ROLE_MISMATCH", "Action %s requires a CspComplianceLead." % raw_action)
        if raw_action in ASSESSOR_ACTIONS and actor_role != ASSESSOR:
            fail("ERR_ACTION_ROLE_MISMATCH", "Action %s requires a ThirdPartyAssessor." % raw_action)
    action = req_enum(b, "action", ACTIONS)
    item = lookup("poam_items", ident)
    offering = db.offerings.get(item["offering_id"])
    if actor_role == LEAD and offering is not None:
        svc.require_offering_owner(offering, uid())
    status = item["remediation_status"]
    refresh = False
    if action == "START":
        if status != "OPEN":
            fail("ERR_INVALID_STATE", "START requires remediation_status OPEN.")
        item["remediation_status"] = "IN_REMEDIATION"
        refresh = True
    elif action == "SUBMIT_EVIDENCE":
        if status != "IN_REMEDIATION":
            fail("ERR_INVALID_STATE", "SUBMIT_EVIDENCE requires remediation_status IN_REMEDIATION.")
        item["remediation_status"] = "AWAITING_VERIFICATION"
    elif action == "VERIFY_CLOSE":
        if status != "AWAITING_VERIFICATION":
            fail(
                "ERR_INVALID_STATE",
                "VERIFY_CLOSE requires remediation_status AWAITING_VERIFICATION.",
            )
        for deviation in svc.deviations_of(item["id"]):
            if deviation["status"] in PENDING_DEVIATION_STATUSES:
                fail("ERR_DEVIATION_PENDING_ON_ITEM", "A deviation on this finding is still open.")
        item["remediation_status"] = "CLOSED"
        item["closure_reason"] = "REMEDIATED"
        refresh = True
    else:
        if status == "AWAITING_VERIFICATION":
            item["remediation_status"] = "IN_REMEDIATION"
            item["reopen_count"] = int(item["reopen_count"]) + 1
        elif status == "CLOSED" and item["closure_reason"] == "REMEDIATED":
            item["remediation_status"] = "IN_REMEDIATION"
            item["closure_reason"] = None
            item["reopen_count"] = int(item["reopen_count"]) + 1
            refresh = True
        else:
            fail("ERR_INVALID_STATE", "REOPEN is not legal from the current state.")
    touch(item)
    if refresh:
        svc.refresh_authorization_for_offering(item["offering_id"])
    return ok(item)


# ---------------------------------------------------------------------------
# Deviation requests
# ---------------------------------------------------------------------------


@bp.post("/deviation-requests")
def create_deviation():
    authenticate((LEAD,))
    b = body()
    poam_item_id = req_str(b, "poam_item_id")
    kind = req_enum(b, "kind", DEVIATION_KINDS)
    justification = req_str(b, "justification")
    extension_days = opt_int(b, "requested_extension_days", 0, minimum=0, maximum=180)
    item = lookup("poam_items", poam_item_id)
    offering = db.offerings.get(item["offering_id"])
    if item["remediation_status"] == "CLOSED":
        fail("ERR_ALREADY_TERMINAL", "A closed finding cannot carry a deviation request.")
    if item["risk_disposition"] != "NONE":
        fail("ERR_INVALID_STATE", "The finding's risk_disposition must be NONE.")
    if offering is None or offering.get("owner_user_id") != uid():
        fail("ERR_POAM_OFFERING_MISMATCH", "The finding belongs to another provider's offering.")
    rec = new_record()
    rec.update(
        {
            "poam_item_id": item["id"],
            "kind": kind,
            "requested_extension_days": extension_days,
            "justification": justification,
            "status": "SUBMITTED",
            "review_queue": None,
            "submitted_by_user_id": uid(),
            "routed_by_user_id": None,
            "decided_by_user_id": None,
            "granted_extension_days": 0,
        }
    )
    db.deviations[rec["id"]] = rec
    item["risk_disposition"] = "DEVIATION_REQUESTED"
    touch(item)
    return created(rec)


@bp.post("/deviation-requests/<ident>/route")
def route_deviation(ident):
    authenticate((BOARD,))
    b = body()
    deviation = db.deviations.get(ident)
    raw_queue = b.get("review_queue")
    if deviation is not None and isinstance(raw_queue, str) and raw_queue in QUEUES:
        item = db.poam_items.get(deviation["poam_item_id"])
        offering = db.offerings.get(item["offering_id"]) if item else None
        if raw_queue == "BOARD" and deviation["kind"] == "RISK_ADJUSTMENT":
            fail("ERR_WRONG_REVIEW_QUEUE", "A RISK_ADJUSTMENT may not be routed to the board.")
        if raw_queue == "AGENCY":
            if deviation["kind"] == "OPERATIONAL_REQUIREMENT":
                fail(
                    "ERR_WRONG_REVIEW_QUEUE",
                    "An OPERATIONAL_REQUIREMENT may not be routed to the agency queue.",
                )
            if (
                offering is None
                or offering.get("authorization_path") != "AGENCY_SPONSORED"
                or not offering.get("sponsor_agency_id")
            ):
                fail(
                    "ERR_WRONG_REVIEW_QUEUE",
                    "The agency queue requires an agency-sponsored offering.",
                )
    queue = req_enum(b, "review_queue", QUEUES)
    if deviation is None:
        fail("ERR_DEVIATION_NOT_FOUND")
    if deviation["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", "Only a SUBMITTED deviation request may be routed.")
    deviation["review_queue"] = queue
    deviation["routed_by_user_id"] = uid()
    deviation["status"] = "BOARD_REVIEW" if queue == "BOARD" else "AGENCY_REVIEW"
    touch(deviation)
    return ok(deviation)


@bp.post("/deviation-requests/<ident>/decision")
def decide_deviation(ident):
    actor_role = authenticate((BOARD, AGENCY_OFFICIAL))[1]
    deviation = db.deviations.get(ident)
    if deviation is not None:
        if deviation["status"] == "BOARD_REVIEW" and actor_role != BOARD:
            fail("ERR_WRONG_REVIEW_QUEUE", "A board-queue deviation is decided by the board.")
        if deviation["status"] == "AGENCY_REVIEW" and actor_role != AGENCY_OFFICIAL:
            fail(
                "ERR_WRONG_REVIEW_QUEUE",
                "An agency-queue deviation is decided by an agency official.",
            )
    b = body()
    decision = req_enum(b, "decision", ("APPROVE", "DENY"))
    if deviation is None:
        fail("ERR_DEVIATION_NOT_FOUND")
    if deviation["status"] not in ("BOARD_REVIEW", "AGENCY_REVIEW"):
        fail("ERR_INVALID_STATE", "Only a routed deviation request may be decided.")
    if deviation["status"] == "BOARD_REVIEW" and uid() == deviation["routed_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES", "The router of a deviation may not decide it.")
    item = db.poam_items.get(deviation["poam_item_id"])
    offering = db.offerings.get(item["offering_id"]) if item else None
    if actor_role == AGENCY_OFFICIAL:
        if offering is None or offering.get("sponsor_agency_id") != uid():
            fail(
                "ERR_POAM_OFFERING_MISMATCH",
                "The finding's offering is not one this official may act on.",
            )
    deviation["decided_by_user_id"] = uid()
    if decision == "APPROVE":
        deviation["status"] = "APPROVED"
        if deviation["kind"] == "FALSE_POSITIVE":
            item["risk_disposition"] = "FALSE_POSITIVE_ACCEPTED"
            item["remediation_status"] = "CLOSED"
            item["closure_reason"] = "FALSE_POSITIVE"
        elif deviation["kind"] == "OPERATIONAL_REQUIREMENT":
            days = int(deviation["requested_extension_days"])
            deviation["granted_extension_days"] = days
            item["granted_extension_days"] = days
            calc.recompute_deadline(item)
            item["risk_disposition"] = "EXTENSION_GRANTED"
        else:
            item["risk_disposition"] = "RISK_ACCEPTED"
    else:
        deviation["status"] = "DENIED"
        item["risk_disposition"] = "NONE"
        item["granted_extension_days"] = 0
        calc.recompute_deadline(item)
    touch(deviation)
    touch(item)
    svc.refresh_authorization_for_offering(item["offering_id"])
    return ok(deviation)


@bp.get("/deviation-requests/<ident>")
def read_deviation(ident):
    authenticate(ANY_ROLE)
    return ok(lookup("deviations", ident))


@bp.get("/deviation-requests")
def list_deviations():
    authenticate(ANY_ROLE)
    poam_item_id = query_str("poam_item_id")
    status = query_enum("status", DEVIATION_STATUSES)
    queue = query_enum("review_queue", QUEUES)
    kind = query_enum("kind", DEVIATION_KINDS)
    limit, offset = pagination()
    result = rows("deviations")
    if poam_item_id is not None:
        result = [d for d in result if d["poam_item_id"] == poam_item_id]
    if status is not None:
        result = [d for d in result if d["status"] == status]
    if queue is not None:
        result = [d for d in result if d["review_queue"] == queue]
    if kind is not None:
        result = [d for d in result if d["kind"] == kind]
    page, total = paginate(result, limit, offset)
    return listing(page, limit, offset, total)
