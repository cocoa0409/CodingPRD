"""Threat cases, team seats, ballots and the decision cascade (PRD 3.7)."""


from flask import Blueprint

import calc
import constants as C
import sync
from db import fmt_dt, new_row, plus_days, store
from errors import ApiError
from middleware import authenticate
from routes.common import filtered, lookup, paged, single
from validation import (body, enum_field, id_field, qs_enum, qs_int, qs_str,
                        str_field)

bp = Blueprint("cases", __name__)

READ_CASE_ROLES = ("ThreatTeamLead", "ThreatTeamMember", "SafetyOfficer", "SecurityCoordinator",
                   "HRPartner", "ComplianceAuditor", "ProgramAdmin")
READ_SEAT_ROLES = ("ThreatTeamLead", "ThreatTeamMember", "SafetyOfficer", "ComplianceAuditor",
                   "ProgramAdmin")

VOTING_ROLES = ("LEAD", "VOTING_MEMBER")

BALLOT_FIELDS = {
    "ballot_value": None,
    "ballot_round": None,
    "ballot_weight": None,
    "ballot_share": None,
    "ballot_submitted_at": None,
    "rationale": None,
}

# The band-to-disposition mapping is one-to-one and ordered by severity.
BAND_DISPOSITION = {
    "LOW": "NO_THREAT",
    "MODERATE": "MONITOR",
    "HIGH": "ELEVATED_RISK",
    "IMMINENT": "IMMINENT_RISK",
}
DISPOSITION_RANK = {"NO_THREAT": 0, "MONITOR": 1, "ELEVATED_RISK": 2, "IMMINENT_RISK": 3}


def _voting_seats(case):
    return [
        s for s in calc.seats_of_case(case["id"])
        if s["status"] == "ASSIGNED" and s["role_on_team"] in VOTING_ROLES
    ]


def _plan_frozen(case):
    """A case with no governing plan is treated as frozen."""
    plan = store.prevention_plans.get(case.get("plan_id"))
    if plan is None:
        return True
    worksite = store.worksites.get(plan["worksite_id"])
    return calc.compliance_posture(plan, worksite) == "FROZEN"


# --------------------------------------------------------------- threat cases


@bp.post("/threat-cases")
def create_case():
    authenticate(("ThreatTeamLead", "SafetyOfficer"))
    data = body()
    incident_report_id = id_field(data, "incident_report_id", True)
    lead_employee_id = id_field(data, "lead_employee_id", True)

    report = lookup(store.incident_reports, incident_report_id, "ERR_INCIDENT_REPORT_NOT_FOUND")
    lookup(store.employees, lead_employee_id, "ERR_EMPLOYEE_NOT_FOUND")

    # Step 21 -- one live case per escalated report.
    if report["triage_status"] != "ESCALATED":
        raise ApiError("ERR_CASE_ALREADY_OPEN_FOR_REPORT",
                       "Only an ESCALATED report may open a threat case.")
    for other in store.threat_cases.values():
        if other["incident_report_id"] == incident_report_id and other["status"] != "CLOSED":
            raise ApiError("ERR_CASE_ALREADY_OPEN_FOR_REPORT",
                           "A non-CLOSED case already exists for this report.")

    plan = calc.governing_plan(report["worksite_id"])
    row = new_row({
        "incident_report_id": incident_report_id,
        "lead_employee_id": lead_employee_id,
        "plan_id": plan["id"] if plan is not None else None,
        "subject_employee_id": report.get("subject_employee_id"),
        "protected_employee_id": report.get("reporter_employee_id"),
        "status": "OPEN",
        "assessment_round": 1,
        "quorum_met": False,
        "ballot_count_current_round": 0,
        "interim_risk_score": None,
        "consensus_risk_score": None,
        "risk_band": None,
        "disposition": None,
        "override_justification": None,
        "protection_window_start": None,
        "protection_window_end": None,
        "coverage_gap_hours": 0.00,
        "protection_status": "NOT_APPLICABLE",
        "open_action_count": 0,
        "closure_summary": None,
    })
    store.threat_cases[row["id"]] = row
    sync.freeze(row)
    sync.sync_case_quorum(row)
    return single(row, 201)


@bp.get("/threat-cases/<threat_case_id>")
def get_case(threat_case_id):
    authenticate(READ_CASE_ROLES)
    return single(lookup(store.threat_cases, threat_case_id, "ERR_THREAT_CASE_NOT_FOUND"))


@bp.get("/threat-cases")
def list_cases():
    authenticate(READ_CASE_ROLES)
    filters = {
        "incident_report_id": qs_str("incident_report_id"),
        "plan_id": qs_str("plan_id"),
        "lead_employee_id": qs_str("lead_employee_id"),
        "subject_employee_id": qs_str("subject_employee_id"),
        "protected_employee_id": qs_str("protected_employee_id"),
        "status": qs_enum("status", C.CASE_STATUSES),
        "risk_band": qs_enum("risk_band", C.RISK_BANDS),
        "protection_status": qs_enum("protection_status", C.PROTECTION_STATUSES),
    }
    return paged(filtered(list(store.threat_cases.values()), filters))


# ------------------------------------------------------------- team seating


@bp.post("/threat-cases/<threat_case_id>/team-assignments")
def create_team_assignment(threat_case_id):
    authenticate(("ThreatTeamLead",))
    data = body()
    member_employee_id = id_field(data, "member_employee_id", True)
    discipline = enum_field(data, "discipline", C.TEAM_DISCIPLINES, True)
    role_on_team = enum_field(data, "role_on_team", C.TEAM_ROLES, True)

    case = lookup(store.threat_cases, threat_case_id, "ERR_THREAT_CASE_NOT_FOUND")
    lookup(store.employees, member_employee_id, "ERR_EMPLOYEE_NOT_FOUND")

    report = store.incident_reports.get(case["incident_report_id"])

    # Step 15 -- nobody evaluates their own case.
    conflicts = [case.get("subject_employee_id"), case.get("protected_employee_id")]
    if report is not None:
        conflicts.append(report.get("reporter_employee_id"))
    if member_employee_id in [c for c in conflicts if c is not None]:
        raise ApiError("ERR_SUBJECT_CONFLICT_OF_INTEREST",
                       "This employee is a party to the case and cannot be seated.")

    # Step 21 -- one ASSIGNED seat per employee, one ASSIGNED LEAD per case.
    seats = calc.seats_of_case(case["id"])
    for seat in seats:
        if seat["status"] == "ASSIGNED" and seat["member_employee_id"] == member_employee_id:
            raise ApiError("ERR_DUPLICATE_TEAM_ASSIGNMENT",
                           "This employee already holds an ASSIGNED seat on the case.")
    if role_on_team == "LEAD":
        for seat in seats:
            if seat["status"] == "ASSIGNED" and seat["role_on_team"] == "LEAD":
                raise ApiError("ERR_DUPLICATE_TEAM_LEAD",
                               "The case already holds an ASSIGNED LEAD seat.")

    row = new_row({
        "case_id": case["id"],
        "member_employee_id": member_employee_id,
        "discipline": discipline,
        "role_on_team": role_on_team,
        "status": "ASSIGNED",
        "ballot_value": None,
        "ballot_round": None,
        "ballot_weight": None,
        "ballot_share": None,
        "ballot_submitted_at": None,
        "rationale": None,
    })
    store.team_assignments[row["id"]] = row

    sync.sync_case_quorum(case)
    return single(row, 201)


@bp.get("/team-assignments/<team_assignment_id>")
def get_team_assignment(team_assignment_id):
    authenticate(READ_SEAT_ROLES)
    return single(lookup(store.team_assignments, team_assignment_id, "ERR_TEAM_ASSIGNMENT_NOT_FOUND"))


@bp.get("/team-assignments")
def list_team_assignments():
    authenticate(READ_SEAT_ROLES)
    filters = {
        "case_id": qs_str("case_id"),
        "member_employee_id": qs_str("member_employee_id"),
        "discipline": qs_enum("discipline", C.TEAM_DISCIPLINES),
        "role_on_team": qs_enum("role_on_team", C.TEAM_ROLES),
        "status": qs_enum("status", C.TEAM_SEAT_STATUSES),
        "ballot_round": qs_int("ballot_round"),
    }
    return paged(filtered(list(store.team_assignments.values()), filters))


# ------------------------------------------------------------------- convene


@bp.post("/threat-cases/<threat_case_id>/convene")
def convene_case(threat_case_id):
    authenticate(("ThreatTeamLead",))
    data = body()
    str_field(data, "convene_note", False)

    case = lookup(store.threat_cases, threat_case_id, "ERR_THREAT_CASE_NOT_FOUND")

    # Step 9 -- the state check precedes the posture and quorum gates.
    if case["status"] != "OPEN":
        raise ApiError("ERR_CASE_INVALID_STATE", "Only an OPEN case may be convened.")

    # Step 11 -- the governing plan must not be frozen.
    if _plan_frozen(case):
        raise ApiError("ERR_PLAN_POSTURE_FROZEN", "The governing prevention plan is FROZEN.")

    report = store.incident_reports.get(case["incident_report_id"])

    # Step 22 -- quorum.
    quorum = calc.team_quorum(case, report)
    if not quorum["quorum_met"]:
        raise ApiError("ERR_QUORUM_NOT_MET",
                       "Quorum is not met; missing disciplines: %s."
                       % (", ".join(quorum["missing_disciplines"]) or "none"))

    interim = calc.interim_risk_score(case, report)
    sync.assign(case, {
        "status": "ASSESSING",
        "assessment_round": 1,
        "quorum_met": True,
        "interim_risk_score": calc.num(interim),
        "risk_band": calc.risk_band(interim),
    })
    sync.sync_case_quorum(case)
    return single(case)


# ------------------------------------------------------------------- ballots


@bp.post("/threat-cases/<threat_case_id>/ballots")
def cast_ballot(threat_case_id):
    caller = authenticate(("ThreatTeamMember", "ThreatTeamLead"))
    data = body()
    ballot_value = enum_field(data, "ballot_value", C.BALLOT_VALUES, True)
    rationale = str_field(data, "rationale", True, 1)

    case = lookup(store.threat_cases, threat_case_id, "ERR_THREAT_CASE_NOT_FOUND")

    # A caller with no seat at all on the case does not resolve.
    seat = None
    for candidate in calc.seats_of_case(case["id"]):
        if candidate["member_employee_id"] == caller.user_id:
            if seat is None or candidate["status"] == "ASSIGNED":
                seat = candidate
    if seat is None:
        raise ApiError("ERR_TEAM_ASSIGNMENT_NOT_FOUND", "The caller holds no seat on this case.")

    # Step 9 -- a case that has never reached ASSESSING declares no ballot.
    if case["status"] == "OPEN":
        raise ApiError("ERR_CASE_INVALID_STATE", "The case has not been convened.")

    # Step 23 -- ballot eligibility for the current round.
    if case["status"] != "ASSESSING":
        raise ApiError("ERR_BALLOT_ROUND_CLOSED", "The case has left ASSESSING.")
    if seat["status"] != "ASSIGNED":
        raise ApiError("ERR_BALLOT_ROUND_CLOSED", "The seat is RECUSED.")
    if seat["role_on_team"] not in VOTING_ROLES:
        raise ApiError("ERR_BALLOT_ROUND_CLOSED", "An ADVISOR seat does not vote.")
    if seat.get("ballot_round") == case["assessment_round"] and seat.get("ballot_value") is not None:
        raise ApiError("ERR_BALLOT_ROUND_CLOSED", "This seat has already balloted in this round.")

    sync.assign(seat, {
        "ballot_value": ballot_value,
        "rationale": rationale,
        "ballot_round": case["assessment_round"],
        "ballot_submitted_at": store.clock_raw,
    })

    # The case's state is a function of its seats.
    cast = calc.ballot_count_current_round(case)
    voting = _voting_seats(case)
    values = {"ballot_count_current_round": cast}
    if len(voting) > 0 and cast >= len(voting):
        values["status"] = "DELIBERATION"
    sync.assign(case, values)
    return single(seat)


# ------------------------------------------------------------------ reassess


@bp.post("/threat-cases/<threat_case_id>/reassess")
def reassess_case(threat_case_id):
    authenticate(("ThreatTeamLead",))
    data = body()
    str_field(data, "reassess_reason", True, 1)

    case = lookup(store.threat_cases, threat_case_id, "ERR_THREAT_CASE_NOT_FOUND")

    if case["status"] != "DELIBERATION":
        raise ApiError("ERR_CASE_INVALID_STATE", "Only a DELIBERATION case may be reassessed.")

    # Step 24 -- the round ceiling is what stops the cycle running forever.
    if case["assessment_round"] >= C.MAX_ASSESSMENT_ROUNDS:
        raise ApiError("ERR_MAX_ASSESSMENT_ROUNDS", "The case has exhausted its assessment rounds.")

    for seat in calc.seats_of_case(case["id"]):
        sync.assign(seat, dict(BALLOT_FIELDS))

    sync.assign(case, {
        "status": "ASSESSING",
        "assessment_round": case["assessment_round"] + 1,
        "ballot_count_current_round": 0,
    })
    return single(case)


# -------------------------------------------------------------------- decide


@bp.post("/threat-cases/<threat_case_id>/decide")
def decide_case(threat_case_id):
    authenticate(("ThreatTeamLead",))
    data = body()
    disposition = enum_field(data, "disposition", C.DISPOSITIONS, True)
    override_justification = str_field(data, "override_justification", False)

    case = lookup(store.threat_cases, threat_case_id, "ERR_THREAT_CASE_NOT_FOUND")

    if case["status"] != "DELIBERATION":
        raise ApiError("ERR_CASE_INVALID_STATE", "Only a DELIBERATION case may be decided.")

    consensus, band, shares = calc.consensus_risk_score(case)
    required = BAND_DISPOSITION[band]

    # Step 25 -- band mapping, unless an override is offered.
    if disposition != required and not override_justification:
        raise ApiError("ERR_DISPOSITION_BAND_MISMATCH",
                       "The %s band requires a disposition of %s." % (band, required))

    # Step 26 -- override legitimacy: escalation by at most one step, in writing.
    if override_justification:
        steps = DISPOSITION_RANK[disposition] - DISPOSITION_RANK[required]
        if len(override_justification) < C.OVERRIDE_JUSTIFICATION_MIN_LENGTH:
            raise ApiError("ERR_OVERRIDE_NOT_PERMITTED",
                           "An override justification must be at least %d characters."
                           % C.OVERRIDE_JUSTIFICATION_MIN_LENGTH)
        if steps < 0:
            raise ApiError("ERR_OVERRIDE_NOT_PERMITTED",
                           "An override may never lower the computed disposition.")
        if steps > 1:
            raise ApiError("ERR_OVERRIDE_NOT_PERMITTED",
                           "An override may raise the disposition by at most one step.")

    # The counted seats keep their pinned weight and rounded share.
    for seat, weight, share in shares:
        sync.assign(seat, {
            "ballot_weight": float(weight),
            "ballot_share": calc.num(share),
        })

    values = {
        "consensus_risk_score": calc.num(consensus),
        "risk_band": band,
        "disposition": disposition,
        "override_justification": override_justification,
    }

    if disposition == "NO_THREAT":
        values["status"] = "CLOSED"
        values["coverage_gap_hours"] = 0.00
        values["protection_status"] = "NOT_APPLICABLE"
        sync.assign(case, values)

        report = store.incident_reports.get(case["incident_report_id"])
        if report is not None:
            sync.assign(report, {"triage_status": "CLOSED_NO_ACTION"})
        return single(case)

    values["status"] = "MONITORING"
    values["protection_window_start"] = store.clock_raw
    values["protection_window_end"] = fmt_dt(plus_days(store.clock, C.PROTECTION_WINDOW_DAYS))
    sync.assign(case, values)

    # The window is brand new, so nothing covers it yet.
    sync.sync_case_coverage(case, allow_auto_action=False)

    # Link 1 -- the report becomes substantiated.
    report = store.incident_reports.get(case["incident_report_id"])
    if report is None:
        return single(case)
    sync.assign(report, {"triage_status": "SUBSTANTIATED"})

    # Link 2 -- exactly one log entry, carrying six of the eight elements.
    if report.get("log_required"):
        sync.append_log_entry(case, report)

    # Link 3 -- the worksite's rolling count and high-risk flag.
    worksite = store.worksites.get(report["worksite_id"])
    sync.sync_worksite_risk(worksite)

    # Link 4 -- the ACTIVE plan falls due for review at the flag threshold.
    if worksite is not None and worksite.get("high_risk_flag"):
        for plan in calc.plans_of_worksite(worksite["id"]):
            if plan["status"] == "ACTIVE":
                sync.assign(plan, {"status": "REVIEW_DUE"})
    sync.sync_plans_of_worksite(report["worksite_id"])
    return single(case)


# --------------------------------------------------------------------- close


@bp.post("/threat-cases/<threat_case_id>/close")
def close_case(threat_case_id):
    authenticate(("ThreatTeamLead",))
    data = body()
    closure_summary = str_field(data, "closure_summary", True, 1)

    case = lookup(store.threat_cases, threat_case_id, "ERR_THREAT_CASE_NOT_FOUND")

    if case["status"] != "MONITORING":
        raise ApiError("ERR_CASE_INVALID_STATE", "Only a MONITORING case may be closed.")

    # Step 34 -- the open-action gate runs first.
    open_actions = [
        a for a in calc.actions_of_case(case["id"])
        if a["action_class"] == "POST_INCIDENT" and a["status"] in ("PENDING", "OVERDUE")
    ]
    if len(open_actions) > 0:
        raise ApiError("ERR_OPEN_ACTIONS_BLOCK_CLOSE",
                       "%d post-incident action(s) are still open." % len(open_actions))

    # Step 35 -- every live log entry of the case must be regulatorily complete.
    for entry in store.log_entries.values():
        if entry.get("case_id") != case["id"]:
            continue
        if calc.is_superseded_entry(entry):
            continue
        if entry["required_element_count_present"] < C.REQUIRED_LOG_ELEMENTS:
            raise ApiError("ERR_LOG_ENTRY_REQUIRED_ELEMENT_MISSING",
                           "A live log entry carries only %d of %d required elements."
                           % (entry["required_element_count_present"], C.REQUIRED_LOG_ELEMENTS))

    sync.assign(case, {"status": "CLOSED", "closure_summary": closure_summary})

    for action in calc.actions_of_case(case["id"]):
        if action["action_class"] != "PROTECTIVE":
            continue
        if action["status"] not in C.COVERED_STATUSES:
            continue
        sync.release_protective(action, "REVOKED", "Case closed.")

    sync.sync_case_coverage(case, allow_auto_action=False)
    sync.assign(case, {"protection_status": "NOT_APPLICABLE"})
    plan = store.prevention_plans.get(case.get("plan_id"))
    if plan is not None and plan["status"] != "SUPERSEDED":
        sync.sync_plan(plan)
    return single(case)
