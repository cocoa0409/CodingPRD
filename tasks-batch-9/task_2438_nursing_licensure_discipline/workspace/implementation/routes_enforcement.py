"""Complaints, evidence holds, monitoring agreements, proceedings, and reports."""
from flask import Blueprint

import calc
import domain
import guards as G
import store
from envelope import created, listing, mark_new, ok, touch
from errors import fail
from timeutil import add_days

bp = Blueprint("enforcement", __name__)

COMPLAINANT_TYPES = ("PATIENT", "EMPLOYER", "SELF_REPORT", "BOARD_INITIATED", "OTHER_STATE_BOARD")
VIOLATION_CATEGORIES = ("PRACTICE_STANDARD", "SUBSTANCE_USE", "FRAUD", "BOUNDARY_VIOLATION",
                        "CRIMINAL_CONDUCT")
JURISDICTION_FINDINGS = ("JURISDICTION_CONFIRMED", "NO_JURISDICTION", "DUPLICATE")
RECORD_CLASSES = ("EMPLOYER_PERSONNEL", "EMPLOYER_INCIDENT", "PATIENT_CHART", "PHARMACY_DISPENSING")
PHI_CLASSES = ("PATIENT_CHART", "PHARMACY_DISPENSING")
DISPOSITIONS = ("DISMISS", "OFFER_ATD", "REFER_TO_PROCEEDING")
MONITORING_EVENTS = ("COMPLIANCE_REPORT", "MISSED_SCREEN", "BREACH", "COMPLETION")
HEARING_EVENTS = ("CONVENE", "CONTINUE", "CLOSE_HEARING", "REOPEN")
VOTE_TIERS = ("NONE",) + calc.SANCTION_TIERS
REPORT_STATUSES = ("QUEUED", "TRANSMITTED", "ACKNOWLEDGED", "VOID")
CONSOLIDATION_TARGET_STATES = ("RECEIVED", "TRIAGED", "INVESTIGATION_OPEN", "EVIDENCE_COMPLETE")
BLOCKING_AGREEMENT_STATES = ("OFFERED", "EXECUTED", "ACTIVE", "SUSPENDED_PENDING_REVIEW",
                             "COMPLETED", "BREACHED")


def _evidence_of(complaint_id):
    return sorted(
        [e for e in store.STORE.evidence_requests.values() if e["complaint_id"] == complaint_id],
        key=lambda e: e["created_at"])


# ---------------------------------------------------------------------------
# Complaint
# ---------------------------------------------------------------------------
@bp.post("/complaints")
def create_complaint():
    G.auth("Investigator")
    b = G.body()
    lic = G.find_opt("license", b.get("license_id"))
    if lic is None:
        G.req_string(b, "license_id")
    complainant_type = G.req_enum(b, "complainant_type", COMPLAINANT_TYPES)
    violation_category = G.req_enum(b, "violation_category", VIOLATION_CATEGORIES)
    incident_date = G.req_datetime(b, "incident_date")
    allegations = G.opt_str_array(b, "allegation_codes", [])
    custodians = G.opt_str_array(b, "employer_custodian_codes", [])

    rec = store.base_fields()
    rec.update({
        "license_id": lic["id"],
        "consolidated_into_complaint_id": None,
        "complainant_type": complainant_type,
        "violation_category": violation_category,
        "allegation_codes": allegations,
        "employer_custodian_codes": custodians,
        "incident_date": incident_date,
        "received_at": store.STORE.clock,
        "status": "RECEIVED",
        "jurisdiction_finding": "PENDING",
        "triaged_by_user_id": None,
        "investigator_user_id": None,
        "disposition_at": None,
    })
    store.STORE.complaints[rec["id"]] = rec
    mark_new(rec)
    return created(rec)


@bp.get("/complaints")
def list_complaints():
    G.auth(*G.ALL_STAFF)
    limit, offset = G.pagination()
    rows = G.filter_rows(store.STORE.complaints.values(), {
        "license_id": "license_id",
        "consolidated_into_complaint_id": "consolidated_into_complaint_id",
        "violation_category": "violation_category",
        "status": "status",
    })
    page, total = G.paginate(rows, limit, offset)
    return listing(page, limit, offset, total)


@bp.get("/complaints/<cid>")
def get_complaint(cid):
    G.auth(*G.ALL_STAFF)
    return ok(G.find("complaint", cid))


@bp.post("/complaints/<cid>/triage")
def triage_complaint(cid):
    user_id, _role = G.auth("Investigator")
    complaint = G.find("complaint", cid)
    b = G.body()
    target = G.find_opt("complaint", b.get("target_complaint_id"))
    finding = G.req_enum(b, "jurisdiction_finding", JURISDICTION_FINDINGS)

    if complaint["status"] != "RECEIVED":
        fail("ERR_INVALID_STATE")

    lic = domain.license_of_complaint(complaint)
    if finding == "JURISDICTION_CONFIRMED":
        if lic is not None and lic["license_status"] == "LAPSED":
            fail("ERR_INVALID_STATE", "The credential complained of has lapsed.")
        complaint["status"] = "TRIAGED"
    elif finding == "NO_JURISDICTION":
        complaint["status"] = "DISMISSED"
    else:
        if target is None:
            fail("ERR_CONSOLIDATION_TARGET_INVALID")
        if target["id"] == complaint["id"]:
            fail("ERR_CONSOLIDATION_TARGET_INVALID")
        if target["license_id"] != complaint["license_id"]:
            fail("ERR_CONSOLIDATION_TARGET_INVALID")
        if target.get("consolidated_into_complaint_id") is not None:
            fail("ERR_CONSOLIDATION_TARGET_INVALID")
        if target["status"] not in CONSOLIDATION_TARGET_STATES:
            fail("ERR_CONSOLIDATION_TARGET_INVALID")
        complaint["status"] = "CONSOLIDATED"
        complaint["consolidated_into_complaint_id"] = target["id"]
        merged = False
        for field in ("allegation_codes", "employer_custodian_codes"):
            existing = list(target.get(field) or [])
            for code in complaint.get(field) or []:
                if code not in existing:
                    existing.append(code)
                    merged = True
            target[field] = existing
        if merged:
            touch(target)

    complaint["jurisdiction_finding"] = finding
    complaint["triaged_by_user_id"] = user_id
    touch(complaint)
    if lic is not None:
        domain.reconcile_license(lic)
    return ok(complaint)


@bp.post("/complaints/<cid>/investigation")
def open_investigation(cid):
    user_id, _role = G.auth("Investigator")
    complaint = G.find("complaint", cid)
    if complaint["status"] != "TRIAGED":
        fail("ERR_INVALID_STATE")
    complaint["status"] = "INVESTIGATION_OPEN"
    complaint["investigator_user_id"] = user_id
    touch(complaint)
    lic = domain.license_of_complaint(complaint)
    if lic is not None:
        domain.reconcile_license(lic)
    return ok(complaint)


@bp.post("/complaints/<cid>/evidence-requests")
def create_evidence_request(cid):
    G.auth("Investigator")
    complaint = G.find("complaint", cid)
    b = G.body()
    record_class = G.req_enum(b, "record_class", RECORD_CLASSES)
    custodian_code = G.req_string(b, "custodian_code")
    hold_start = G.req_datetime(b, "hold_start_at")
    hold_end = G.req_datetime(b, "hold_end_at")
    phi = G.opt_string(b, "phi_authorization_id")
    if not (hold_start < hold_end):
        fail("ERR_INVALID_REQUEST", "hold_start_at must be strictly before hold_end_at.")

    if complaint["status"] != "INVESTIGATION_OPEN":
        fail("ERR_INVALID_STATE")

    lic = domain.license_of_complaint(complaint)
    board = domain.board_of_license(lic) if lic else None

    if record_class in PHI_CLASSES and board is not None and board.get("phi_authorization_required"):
        if phi is None or not phi.strip():
            fail("ERR_PHI_AUTHORIZATION_REQUIRED")
    if custodian_code not in (complaint.get("employer_custodian_codes") or []):
        fail("ERR_CUSTODIAN_NOT_LINKED")

    if board is not None:
        concurrent = 0
        for other in store.STORE.evidence_requests.values():
            if other["custodian_code"] != custodian_code:
                continue
            if other["status"] not in ("REQUESTED", "PRODUCED"):
                continue
            if other["hold_start_at"] < hold_end and hold_start < other["hold_end_at"]:
                concurrent += 1
        if concurrent >= int(board["max_concurrent_custodian_holds"]):
            fail("ERR_CUSTODIAN_HOLD_CAPACITY")

    rec = store.base_fields()
    rec.update({
        "complaint_id": complaint["id"],
        "record_class": record_class,
        "custodian_code": custodian_code,
        "hold_start_at": hold_start,
        "hold_end_at": hold_end,
        "phi_authorization_id": phi,
        "status": "REQUESTED",
        "page_count": 0,
        "produced_at": None,
    })
    store.STORE.evidence_requests[rec["id"]] = rec
    mark_new(rec)
    return created(rec)


@bp.get("/complaints/<cid>/evidence-requests")
def list_evidence_requests(cid):
    G.auth("SystemAdmin", "LicensureAnalyst", "Investigator", "BoardMember")
    complaint = G.find("complaint", cid)
    limit, offset = G.pagination()
    rows = _evidence_of(complaint["id"])
    rows = G.filter_rows(rows, {"status": "status", "record_class": "record_class",
                               "custodian_code": "custodian_code"})
    page, total = G.paginate(rows, limit, offset)
    return listing(page, limit, offset, total)


@bp.get("/evidence-requests/<eid>")
def get_evidence_request(eid):
    G.auth("SystemAdmin", "LicensureAnalyst", "Investigator", "BoardMember")
    return ok(G.find("evidence_request", eid))


@bp.post("/evidence-requests/<eid>/production")
def evidence_production(eid):
    G.auth("Investigator")
    demand = G.find("evidence_request", eid)
    b = G.body()
    page_count = G.req_int(b, "page_count", minimum=0)
    if demand["status"] != "REQUESTED":
        fail("ERR_INVALID_STATE")
    demand["status"] = "PRODUCED"
    demand["page_count"] = page_count
    demand["produced_at"] = store.STORE.clock
    touch(demand)
    return ok(demand)


@bp.post("/complaints/<cid>/evidence-completion")
def evidence_completion(cid):
    G.auth("Investigator")
    complaint = G.find("complaint", cid)
    if complaint["status"] != "INVESTIGATION_OPEN":
        fail("ERR_INVALID_STATE")
    demands = _evidence_of(complaint["id"])
    if not demands or any(d["status"] not in ("PRODUCED", "WITHDRAWN") for d in demands):
        fail("ERR_INVALID_STATE", "Every records demand must stand at PRODUCED or WITHDRAWN.")
    complaint["status"] = "EVIDENCE_COMPLETE"
    touch(complaint)
    lic = domain.license_of_complaint(complaint)
    if lic is not None:
        domain.reconcile_license(lic)
    return ok(complaint)


@bp.post("/complaints/<cid>/disposition")
def dispose_complaint(cid):
    G.auth("Investigator")
    complaint = G.find("complaint", cid)
    b = G.body()
    disposition = G.req_enum(b, "disposition", DISPOSITIONS)

    if complaint["status"] not in ("INVESTIGATION_OPEN", "EVIDENCE_COMPLETE"):
        fail("ERR_INVALID_STATE")

    lic = domain.license_of_complaint(complaint)
    nurse = domain.nurse_of_license(lic) if lic else None

    if disposition == "OFFER_ATD":
        if complaint["violation_category"] != "SUBSTANCE_USE":
            fail("ERR_ATD_INELIGIBLE")
        if nurse is None:
            fail("ERR_ATD_INELIGIBLE")
        if any(a["nurse_id"] == nurse["id"] and a["status"] == "BREACHED"
               for a in store.STORE.agreements.values()):
            fail("ERR_ATD_INELIGIBLE")
        if int(nurse.get("prior_discipline_count") or 0) != 0:
            fail("ERR_ATD_INELIGIBLE")
        complaint["status"] = "ATD_OFFERED"
    elif disposition == "REFER_TO_PROCEEDING":
        complaint["status"] = "REFERRED_FOR_HEARING"
    else:
        complaint["status"] = "DISMISSED"
        for demand in _evidence_of(complaint["id"]):
            if demand["status"] == "REQUESTED":
                demand["status"] = "WITHDRAWN"
                touch(demand)

    complaint["disposition_at"] = store.STORE.clock
    touch(complaint)
    if lic is not None:
        domain.reconcile_license(lic)
    return ok(complaint)


@bp.get("/complaints/<cid>/disciplinary-proceedings")
def list_complaint_proceedings(cid):
    G.auth("SystemAdmin", "LicensureAnalyst", "Investigator", "BoardMember")
    complaint = G.find("complaint", cid)
    limit, offset = G.pagination()
    rows = [p for p in store.STORE.proceedings.values() if p["complaint_id"] == complaint["id"]]
    rows = G.filter_rows(rows, {"status": "status"})
    page, total = G.paginate(rows, limit, offset)
    return listing(page, limit, offset, total)


# ---------------------------------------------------------------------------
# MonitoringAgreement
# ---------------------------------------------------------------------------
@bp.post("/monitoring-agreements")
def create_agreement():
    user_id, _role = G.auth("BoardMember")
    b = G.body()
    nurse = G.find_opt("nurse", b.get("nurse_id"))
    complaint = G.find_opt("complaint", b.get("complaint_id"))
    if nurse is None:
        G.req_string(b, "nurse_id")
    if complaint is None:
        G.req_string(b, "complaint_id")
    start_date = G.req_datetime(b, "start_date")
    end_date = G.req_datetime(b, "end_date")
    if start_date > end_date:
        fail("ERR_INVALID_REQUEST", "start_date must be at or before end_date.")
    narcotic = G.opt_bool(b, "narcotic_access_restricted", True)
    screens = G.opt_int(b, "required_screens_per_quarter", 4, minimum=0)
    worksite = G.opt_bool(b, "worksite_approval_required", True)

    if complaint["status"] != "ATD_OFFERED":
        fail("ERR_INVALID_STATE")

    lic = domain.license_of_complaint(complaint)
    board = domain.board_of_license(lic) if lic else None
    if board is None:
        board = store.STORE.boards.get(nurse["home_board_config_id"])
    gap = int(board["monitoring_clearance_gap_days"]) if board else 0

    for other in store.STORE.agreements.values():
        if other["nurse_id"] != nurse["id"]:
            continue
        if other["status"] not in BLOCKING_AGREEMENT_STATES:
            continue
        if start_date <= other["end_date"] and other["start_date"] <= end_date:
            fail("ERR_MONITORING_PERIOD_CONFLICT")
        if other["end_date"] < start_date and start_date <= add_days(other["end_date"], gap):
            fail("ERR_MONITORING_PERIOD_CONFLICT")

    rec = store.base_fields()
    rec.update({
        "nurse_id": nurse["id"],
        "complaint_id": complaint["id"],
        "approved_by_user_id": user_id,
        "start_date": start_date,
        "end_date": end_date,
        "narcotic_access_restricted": narcotic,
        "required_screens_per_quarter": screens,
        "worksite_approval_required": worksite,
        "status": "OFFERED",
        "compliance_report_count": 0,
        "missed_screen_count": 0,
        "executed_at": None,
    })
    store.STORE.agreements[rec["id"]] = rec
    mark_new(rec)
    return created(rec)


@bp.get("/monitoring-agreements")
def list_agreements():
    G.auth(*G.ALL_STAFF)
    limit, offset = G.pagination()
    rows = G.filter_rows(store.STORE.agreements.values(), {
        "nurse_id": "nurse_id",
        "complaint_id": "complaint_id",
        "status": "status",
    })
    page, total = G.paginate(rows, limit, offset)
    return listing(page, limit, offset, total)


@bp.get("/monitoring-agreements/<aid>")
def get_agreement(aid):
    user_id, role = G.auth(*G.ROLES)
    agreement = G.find("agreement", aid)
    G.own_nurse(role, user_id, agreement["nurse_id"])
    return ok(agreement)


@bp.post("/monitoring-agreements/<aid>/execution")
def execute_agreement(aid):
    user_id, role = G.auth("Applicant")
    agreement = G.find("agreement", aid)
    G.own_nurse(role, user_id, agreement["nurse_id"])

    complaint = store.STORE.complaints.get(agreement["complaint_id"])
    if agreement["status"] != "OFFERED":
        fail("ERR_INVALID_STATE")
    if complaint is None or complaint["status"] != "ATD_OFFERED":
        fail("ERR_INVALID_STATE")

    agreement["executed_at"] = store.STORE.clock
    agreement["status"] = "EXECUTED"
    if agreement["start_date"] <= store.STORE.clock:
        agreement["status"] = "ACTIVE"
    touch(agreement)

    complaint["status"] = "ATD_ACTIVE"
    touch(complaint)

    nurse = store.STORE.nurses.get(agreement["nurse_id"])
    if nurse is not None:
        nurse["atd_participation_count"] = int(nurse["atd_participation_count"]) + 1
        touch(nurse)
    lic = domain.license_of_complaint(complaint)
    if lic is not None:
        domain.reconcile_license(lic)
    return ok(agreement)


@bp.post("/monitoring-agreements/<aid>/monitoring-events")
def monitoring_event(aid):
    G.auth("MonitoringCoordinator")
    agreement = G.find("agreement", aid)
    b = G.body()
    event_type = G.req_enum(b, "event_type", MONITORING_EVENTS)
    missed = G.opt_int(b, "missed_screens", 1, minimum=0)
    G.opt_string(b, "note")

    complaint = store.STORE.complaints.get(agreement["complaint_id"])
    lic = domain.license_of_complaint(complaint) if complaint else None
    nurse = store.STORE.nurses.get(agreement["nurse_id"])

    if event_type == "COMPLIANCE_REPORT":
        if agreement["status"] not in ("ACTIVE", "SUSPENDED_PENDING_REVIEW"):
            fail("ERR_INVALID_STATE")
        agreement["compliance_report_count"] = int(agreement["compliance_report_count"]) + 1
        agreement["missed_screen_count"] = 0
        if agreement["status"] == "SUSPENDED_PENDING_REVIEW":
            agreement["status"] = "ACTIVE"
        touch(agreement)

    elif event_type == "MISSED_SCREEN":
        if agreement["status"] not in ("ACTIVE", "SUSPENDED_PENDING_REVIEW"):
            fail("ERR_INVALID_STATE")
        agreement["missed_screen_count"] = int(agreement["missed_screen_count"]) + missed
        if agreement["missed_screen_count"] >= 3 and agreement["status"] == "ACTIVE":
            agreement["status"] = "SUSPENDED_PENDING_REVIEW"
        touch(agreement)

    elif event_type == "COMPLETION":
        if agreement["status"] != "ACTIVE":
            fail("ERR_INVALID_STATE")
        if not (store.STORE.clock > agreement["end_date"]):
            fail("ERR_INVALID_STATE", "Completion before the closing day is premature.")
        if int(agreement["compliance_report_count"]) < 1:
            fail("ERR_INVALID_STATE", "At least one compliance report is required.")
        agreement["status"] = "COMPLETED"
        touch(agreement)
        if complaint is not None and complaint["status"] == "ATD_ACTIVE":
            complaint["status"] = "CLOSED"
            touch(complaint)
        if lic is not None:
            domain.reconcile_license(lic)

    else:  # BREACH
        if agreement["status"] not in ("ACTIVE", "SUSPENDED_PENDING_REVIEW"):
            fail("ERR_INVALID_STATE")
        agreement["status"] = "BREACHED"
        touch(agreement)
        if complaint is not None and complaint["status"] == "ATD_ACTIVE":
            complaint["status"] = "PROCEEDING_OPENED"
            touch(complaint)
        if lic is not None:
            if lic["encumbrance_status"] in ("INVESTIGATION_PENDING", "RESTRICTED"):
                lic["encumbrance_status"] = "SUSPENDED"
            lic["multistate_privilege_status"] = "PRIVILEGE_REVOKED"
            touch(lic)
            domain.queue_report(agreement["nurse_id"], "MONITORING_AGREEMENT", agreement["id"],
                                "NPDB", "ATD_BREACH",
                                "Alternative-to-discipline breach on agreement %s." % agreement["id"])
        if nurse is not None and nurse.get("status") != "ENCUMBERED":
            nurse["status"] = "ENCUMBERED"
            touch(nurse)
    return ok(agreement)


# ---------------------------------------------------------------------------
# DisciplinaryProceeding
# ---------------------------------------------------------------------------
@bp.post("/disciplinary-proceedings")
def create_proceeding():
    user_id, _role = G.auth("BoardMember")
    b = G.body()
    complaint = G.find_opt("complaint", b.get("complaint_id"))
    if complaint is None:
        G.req_string(b, "complaint_id")
    expected = G.req_int(b, "expected_complaint_version")
    seated = G.req_str_array(b, "seated_member_user_ids")
    hearing_date = G.req_datetime(b, "hearing_date")
    notice_days = G.opt_int(b, "notice_period_days", 30, minimum=0)

    if expected != int(complaint["version"]):
        fail("ERR_STALE_VERSION")
    if complaint["status"] != "REFERRED_FOR_HEARING":
        fail("ERR_INVALID_STATE")

    noticed_at = store.STORE.clock
    if hearing_date < add_days(noticed_at, notice_days):
        fail("ERR_NOTICE_PERIOD_NOT_MET")

    panel = [m for m in seated if m != user_id]
    lic = domain.license_of_complaint(complaint)
    nurse = domain.nurse_of_license(lic) if lic else None
    recused = _recused_members(panel, nurse)

    rec = store.base_fields()
    rec.update({
        "complaint_id": complaint["id"],
        "presiding_member_user_id": user_id,
        "seated_member_user_ids": panel,
        "recused_member_user_ids": recused,
        "notice_period_days": notice_days,
        "hearing_date": hearing_date,
        "noticed_at": noticed_at,
        "votes": [],
        "continuance_count": 0,
        "sanction_floor_tier": "NONE",
        "adopted_sanction_tier": "NONE",
        "ordered_restriction_codes": [],
        "status": "NOTICED",
        "order_issued_at": None,
    })
    store.STORE.proceedings[rec["id"]] = rec
    mark_new(rec)

    complaint["status"] = "PROCEEDING_OPENED"
    touch(complaint)
    if lic is not None:
        domain.reconcile_license(lic)
    return created(rec)


def _recused_members(panel, nurse):
    if nurse is None:
        return []
    approvers = set(
        a.get("approved_by_user_id") for a in store.STORE.agreements.values()
        if a["nurse_id"] == nurse["id"])
    return [m for m in panel if m in approvers]


@bp.get("/disciplinary-proceedings/<pid>")
def get_proceeding(pid):
    G.auth("SystemAdmin", "LicensureAnalyst", "Investigator", "BoardMember")
    return ok(G.find("proceeding", pid))


@bp.post("/disciplinary-proceedings/<pid>/hearing-events")
def hearing_event(pid):
    G.auth("BoardMember")
    proceeding = G.find("proceeding", pid)
    b = G.body()
    event_type = G.req_enum(b, "event_type", HEARING_EVENTS)
    new_hearing_date = G.opt_datetime(b, "new_hearing_date")

    complaint = store.STORE.complaints.get(proceeding["complaint_id"])
    lic = domain.license_of_complaint(complaint) if complaint else None
    nurse = domain.nurse_of_license(lic) if lic else None
    board = domain.board_of_license(lic) if lic else None

    if event_type == "CONVENE":
        if proceeding["status"] not in ("NOTICED", "CONTINUED"):
            fail("ERR_INVALID_STATE")
        if proceeding["hearing_date"] < add_days(proceeding["noticed_at"],
                                                int(proceeding["notice_period_days"])):
            fail("ERR_NOTICE_PERIOD_NOT_MET")
        recused = _recused_members(proceeding["seated_member_user_ids"], nurse)
        if len(proceeding["seated_member_user_ids"]) - len(recused) < 3:
            fail("ERR_QUORUM_NOT_MET")
        proceeding["recused_member_user_ids"] = recused
        proceeding["sanction_floor_tier"] = calc.sanction_severity_floor(complaint, nurse, lic)
        proceeding["status"] = "HEARING_CONVENED"
        touch(proceeding)

    elif event_type == "CONTINUE":
        if proceeding["status"] != "HEARING_CONVENED":
            fail("ERR_INVALID_STATE")
        if int(proceeding["continuance_count"]) >= 3:
            fail("ERR_CONTINUANCE_LIMIT_REACHED")
        if new_hearing_date is None:
            fail("ERR_INVALID_REQUEST", "new_hearing_date is required for a CONTINUE event.")
        proceeding["status"] = "CONTINUED"
        proceeding["hearing_date"] = new_hearing_date
        proceeding["noticed_at"] = store.STORE.clock
        proceeding["continuance_count"] = int(proceeding["continuance_count"]) + 1
        touch(proceeding)

    elif event_type == "REOPEN":
        if proceeding["status"] != "DELIBERATION":
            fail("ERR_INVALID_STATE")
        if int(proceeding["continuance_count"]) >= 3:
            fail("ERR_CONTINUANCE_LIMIT_REACHED")
        proceeding["status"] = "HEARING_CONVENED"
        proceeding["adopted_sanction_tier"] = "NONE"
        proceeding["votes"] = []
        proceeding["continuance_count"] = int(proceeding["continuance_count"]) + 1
        touch(proceeding)

    else:  # CLOSE_HEARING
        if proceeding["status"] != "HEARING_CONVENED":
            fail("ERR_INVALID_STATE")
        if not calc.effective_ballots(proceeding):
            fail("ERR_INVALID_STATE", "At least one seated, non-recused vote is required.")
        adopted = calc.panel_vote_tally(proceeding, board)
        proceeding["adopted_sanction_tier"] = adopted
        proceeding["status"] = "DELIBERATION"
        touch(proceeding)
        if adopted == "NONE":
            proceeding["status"] = "DISMISSED_BY_PANEL"
            touch(proceeding)
            if complaint is not None and complaint["status"] == "PROCEEDING_OPENED":
                complaint["status"] = "DISMISSED"
                touch(complaint)
            if lic is not None:
                domain.reconcile_license(lic)
    return ok(proceeding)


@bp.post("/disciplinary-proceedings/<pid>/votes")
def cast_vote(pid):
    user_id, _role = G.auth("BoardMember")
    proceeding = G.find("proceeding", pid)
    b = G.body()
    tier = G.req_enum(b, "proposed_sanction_tier", VOTE_TIERS)

    if proceeding["status"] in ("ORDER_ISSUED", "DISMISSED_BY_PANEL"):
        fail("ERR_INVALID_STATE")
    if user_id == proceeding["presiding_member_user_id"]:
        fail("ERR_PRESIDING_MEMBER_CANNOT_VOTE")

    complaint = store.STORE.complaints.get(proceeding["complaint_id"])
    lic = domain.license_of_complaint(complaint) if complaint else None
    nurse = domain.nurse_of_license(lic) if lic else None
    approvers = set()
    if nurse is not None:
        approvers = set(a.get("approved_by_user_id") for a in store.STORE.agreements.values()
                        if a["nurse_id"] == nurse["id"])
    if user_id in approvers or user_id not in (proceeding["seated_member_user_ids"] or []):
        fail("ERR_VOTER_CONFLICT_OF_INTEREST")

    proceeding["votes"] = list(proceeding.get("votes") or []) + [{
        "voter_user_id": user_id,
        "proposed_sanction_tier": tier,
        "cast_at": store.STORE.clock,
    }]
    touch(proceeding)
    return ok(proceeding)


@bp.post("/disciplinary-proceedings/<pid>/order")
def issue_order(pid):
    G.auth("BoardMember")
    proceeding = G.find("proceeding", pid)
    b = G.body()
    codes = G.opt_str_array(b, "ordered_restriction_codes", [])

    if proceeding["status"] != "DELIBERATION":
        fail("ERR_INVALID_STATE")
    adopted = proceeding.get("adopted_sanction_tier") or "NONE"
    if adopted == "NONE":
        fail("ERR_SANCTION_BELOW_FLOOR")
    if calc.tier_index(adopted) < calc.tier_index(proceeding.get("sanction_floor_tier")):
        fail("ERR_SANCTION_BELOW_FLOOR")

    st = store.STORE
    complaint = st.complaints.get(proceeding["complaint_id"])
    lic = domain.license_of_complaint(complaint) if complaint else None
    nurse = domain.nurse_of_license(lic) if lic else None

    proceeding["status"] = "ORDER_ISSUED"
    proceeding["order_issued_at"] = st.clock
    proceeding["ordered_restriction_codes"] = codes
    touch(proceeding)

    encumbered = []
    if lic is not None:
        if adopted in ("PROBATION", "PRACTICE_RESTRICTION"):
            if lic["encumbrance_status"] in ("INVESTIGATION_PENDING", "SUSPENDED"):
                lic["encumbrance_status"] = "RESTRICTED"
            lic["practice_restriction_codes"] = list(codes)
            touch(lic)
            domain.run_privilege(lic, "RESIDENCY_DECLARED")
            encumbered.append(lic)
        elif adopted == "SUSPENSION":
            if lic["encumbrance_status"] in ("INVESTIGATION_PENDING", "RESTRICTED"):
                lic["encumbrance_status"] = "SUSPENDED"
            lic["multistate_privilege_status"] = "PRIVILEGE_REVOKED"
            touch(lic)
            encumbered.append(lic)
        elif adopted == "REVOCATION":
            if lic["encumbrance_status"] in ("INVESTIGATION_PENDING", "RESTRICTED", "SUSPENDED"):
                lic["encumbrance_status"] = "REVOKED"
            lic["license_status"] = "SURRENDERED"
            lic["multistate_privilege_status"] = "PRIVILEGE_REVOKED"
            touch(lic)
            encumbered.append(lic)
            for other in sorted(st.licenses.values(), key=lambda r: r["created_at"]):
                if other["id"] == lic["id"] or other["nurse_id"] != lic["nurse_id"]:
                    continue
                if other.get("base_license_id") != lic["id"]:
                    continue
                other["license_status"] = "SURRENDERED"
                other["encumbrance_status"] = "REVOKED"
                other["multistate_privilege_status"] = "PRIVILEGE_REVOKED"
                touch(other)
                encumbered.append(other)
            for agreement in sorted(st.agreements.values(), key=lambda r: r["created_at"]):
                if agreement["nurse_id"] != lic["nurse_id"]:
                    continue
                if agreement["status"] in ("OFFERED", "EXECUTED", "ACTIVE",
                                           "SUSPENDED_PENDING_REVIEW"):
                    agreement["status"] = "TERMINATED"
                    touch(agreement)

    if complaint is not None and complaint["status"] == "PROCEEDING_OPENED":
        complaint["status"] = "CLOSED"
        touch(complaint)
    if lic is not None:
        count = calc.open_encumbrance_count(lic["id"])
        if lic.get("open_encumbrance_count") != count:
            lic["open_encumbrance_count"] = count
            touch(lic)
    if nurse is not None:
        domain.recompute_prior_discipline_count(nurse)
        domain.recompute_nurse_status(nurse)

    for target in encumbered:
        channel = "NURSE_AIDE_REGISTRY" if target["credential_type"] == "NURSE_AIDE" else "NPDB"
        domain.queue_report(target["nurse_id"], "DISCIPLINARY_PROCEEDING", proceeding["id"],
                            channel, adopted,
                            "Board order at tier %s on credential %s."
                            % (adopted, target["license_number"]))
    if encumbered:
        domain.queue_report(encumbered[0]["nurse_id"], "DISCIPLINARY_PROCEEDING", proceeding["id"],
                            "INTERSTATE_COMPACT", "PRIVILEGE_LOSS",
                            "Compact privilege loss following board order %s." % proceeding["id"])
    return ok(proceeding)


# ---------------------------------------------------------------------------
# NotificationReport
# ---------------------------------------------------------------------------
@bp.get("/notification-reports")
def list_reports():
    G.auth("SystemAdmin", "LicensureAnalyst", "Investigator", "BoardMember")
    limit, offset = G.pagination()
    rows = G.filter_rows(store.STORE.reports.values(), {
        "subject_nurse_id": "subject_nurse_id",
        "source_entity_type": "source_entity_type",
        "source_entity_id": "source_entity_id",
        "channel": "channel",
        "report_kind": "report_kind",
        "status": "status",
    })
    page, total = G.paginate(rows, limit, offset)
    return listing(page, limit, offset, total)


@bp.get("/notification-reports/<rid>")
def get_report(rid):
    G.auth("SystemAdmin", "LicensureAnalyst", "Investigator", "BoardMember")
    return ok(G.find("report", rid))


@bp.post("/notification-reports/<rid>/status")
def report_status(rid):
    G.auth("SystemAdmin")
    report = G.find("report", rid)
    b = G.body()
    to_status = G.req_enum(b, "to_status", REPORT_STATUSES)

    if to_status == "TRANSMITTED":
        if report["status"] != "QUEUED":
            fail("ERR_INVALID_STATE")
        report["status"] = "TRANSMITTED"
        report["transmitted_at"] = store.STORE.clock
    elif to_status == "ACKNOWLEDGED":
        if report["status"] != "TRANSMITTED":
            fail("ERR_INVALID_STATE")
        report["status"] = "ACKNOWLEDGED"
        report["acknowledged_at"] = store.STORE.clock
    elif to_status == "VOID":
        if report["status"] not in ("QUEUED", "TRANSMITTED"):
            fail("ERR_INVALID_STATE")
        report["status"] = "VOID"
        report["report_kind"] = "VOID"
    else:
        fail("ERR_INVALID_STATE", "QUEUED is not a reachable target status.")
    touch(report)
    return ok(report)
