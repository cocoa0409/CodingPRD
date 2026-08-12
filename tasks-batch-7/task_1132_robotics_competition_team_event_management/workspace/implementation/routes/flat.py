"""Flat filtered-list and get-by-id routes for FK reverse-reachability (PRD 2.8)."""
from flask import request

from auth import require_roles
from db import store
from envelope import paginated, success
from errors import (
    ApiError,
    ERR_ALLIANCE_NOT_FOUND,
    ERR_AWARD_NOT_FOUND,
    ERR_BOOKING_NOT_FOUND,
    ERR_INSPECTION_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_MILESTONE_NOT_FOUND,
    ERR_MATCH_NOT_FOUND,
    ERR_NOT_FOUND,
    ERR_ORDER_NOT_FOUND,
    ERR_PERSON_NOT_FOUND,
    ERR_RECORD_NOT_FOUND,
    ERR_RESET_LOG_NOT_FOUND,
    ERR_SLOT_NOT_FOUND,
    ERR_TEAM_NOT_FOUND,
    ERR_VIOLATION_NOT_FOUND,
)
from util import public

ALL_ROLES_ORDERED = (
    "EventDirector", "RegistrationOfficer", "TeamLead", "Scorekeeper",
    "HeadReferee", "QueueManager", "Inspector", "LeadInspector",
    "FieldResetCrew", "TravelOfficer", "ProcurementOfficer", "JudgeAdvisor",
    "Judge", "ScreeningOfficer",
)
PERSON_ROLES = ("EventDirector", "RegistrationOfficer", "ScreeningOfficer", "TeamLead", "JudgeAdvisor")
SCREENING_ROLES = ("EventDirector", "ScreeningOfficer")
MILESTONE_ROLES = ("EventDirector", "RegistrationOfficer", "TeamLead", "ProcurementOfficer")
MATCH_ROLES = ("EventDirector", "Scorekeeper", "QueueManager", "HeadReferee", "FieldResetCrew", "TeamLead")
ORDER_ROLES = ("EventDirector", "TeamLead", "ProcurementOfficer")
INSPECTION_ROLES = ("EventDirector", "Inspector", "LeadInspector", "TeamLead")
VIOLATION_ROLES = ("EventDirector", "HeadReferee", "TeamLead")
ALLIANCE_ROLES = ("EventDirector", "HeadReferee", "TeamLead", "Scorekeeper")
ROUND_ROLES = ("EventDirector", "TeamLead")
AWARD_ROLES = ("EventDirector", "JudgeAdvisor", "Judge", "TeamLead")
BREAKDOWN_ROLES = ("EventDirector", "Scorekeeper", "HeadReferee")
SLOT_ROLES = ("EventDirector", "QueueManager", "TeamLead")
RESET_ROLES = ("EventDirector", "FieldResetCrew", "QueueManager")
BOOKING_ROLES = ("EventDirector", "TeamLead", "TravelOfficer")


def _int_filter(items, field, raw):
    try:
        v = int(raw)
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, 400, "%s must be an integer" % field)
    return [r for r in items if r.get(field) == v]


def _str_filter(items, field, raw):
    return [r for r in items if r.get(field) == raw]


def _apply_filters(items, mapping):
    """mapping: query param name -> (field, is_int)."""
    for param, (field, is_int) in mapping.items():
        raw = request.args.get(param)
        if raw is None:
            continue
        if is_int:
            items = _int_filter(items, field, raw)
        else:
            items = _str_filter(items, field, raw)
    return items


def register_flat_routes(bp):

    # --- Team ---
    @bp.route("/frc-events/teams/<teamId>", methods=["GET"], endpoint="flat_get_team")
    def flat_get_team(teamId):
        require_roles(*ALL_ROLES_ORDERED)
        t = store.teams.get(teamId)
        if t is None:
            raise ApiError(ERR_TEAM_NOT_FOUND, 404, "Team %s not found" % teamId)
        return success(public(t))

    @bp.route("/frc-events/teams", methods=["GET"], endpoint="flat_list_teams")
    def flat_list_teams():
        require_roles(*ALL_ROLES_ORDERED)
        items = list(store.teams.values())
        items = _apply_filters(items, {
            "event_id": ("event_id", False),
            "registration_status": ("registration_status", False),
            "team_number": ("team_number", True),
        })
        return paginated(items, public)

    @bp.route("/frc-events/teams-filtered", methods=["GET"], endpoint="flat_list_teams_filtered")
    def flat_list_teams_filtered():
        require_roles(*ALL_ROLES_ORDERED)
        items = list(store.teams.values())
        items = _apply_filters(items, {
            "event_id": ("event_id", False),
            "registration_status": ("registration_status", False),
            "team_number": ("team_number", True),
        })
        return paginated(items, public)

    # --- Person ---
    @bp.route("/frc-events/persons/<personId>", methods=["GET"], endpoint="flat_get_person")
    def flat_get_person(personId):
        require_roles(*PERSON_ROLES)
        p = store.persons.get(personId)
        if p is None:
            raise ApiError(ERR_PERSON_NOT_FOUND, 404, "Person %s not found" % personId)
        return success(public(p))

    @bp.route("/frc-events/persons", methods=["GET"], endpoint="flat_list_persons")
    def flat_list_persons():
        require_roles(*PERSON_ROLES)
        items = list(store.persons.values())
        items = _apply_filters(items, {
            "team_id": ("team_id", False),
            "role_kind": ("role_kind", False),
            "screening_status": ("screening_status", False),
        })
        return paginated(items, public)

    @bp.route("/frc-events/persons-filtered", methods=["GET"], endpoint="flat_list_persons_filtered")
    def flat_list_persons_filtered():
        require_roles(*PERSON_ROLES)
        items = list(store.persons.values())
        items = _apply_filters(items, {
            "team_id": ("team_id", False),
            "role_kind": ("role_kind", False),
            "screening_status": ("screening_status", False),
        })
        return paginated(items, public)

    # --- ScreeningRecord ---
    @bp.route("/frc-events/screening-records", methods=["GET"], endpoint="flat_list_records")
    def flat_list_records():
        require_roles(*SCREENING_ROLES)
        items = list(store.screening_records.values())
        items = _apply_filters(items, {"person_id": ("person_id", False)})
        return paginated(items, public)

    @bp.route("/frc-events/screening-records/<recordId>", methods=["GET"], endpoint="flat_get_record")
    def flat_get_record(recordId):
        require_roles(*SCREENING_ROLES)
        r = store.screening_records.get(recordId)
        if r is None:
            raise ApiError(ERR_RECORD_NOT_FOUND, 404, "ScreeningRecord %s not found" % recordId)
        return success(public(r))

    # --- BuildSeasonMilestone ---
    @bp.route("/frc-events/milestones-flat", methods=["GET"], endpoint="flat_list_milestones")
    def flat_list_milestones():
        require_roles(*MILESTONE_ROLES)
        items = list(store.milestones.values())
        items = _apply_filters(items, {
            "event_id": ("event_id", False),
            "kind": ("kind", False),
            "status": ("status", False),
        })
        return paginated(items, public)

    @bp.route("/frc-events/milestones-flat/<milestoneId>", methods=["GET"], endpoint="flat_get_milestone")
    def flat_get_milestone(milestoneId):
        require_roles(*MILESTONE_ROLES)
        m = store.milestones.get(milestoneId)
        if m is None:
            raise ApiError(ERR_MILESTONE_NOT_FOUND, 404, "Milestone %s not found" % milestoneId)
        return success(public(m))

    # --- Match ---
    @bp.route("/frc-events/matches-flat", methods=["GET"], endpoint="flat_list_matches")
    def flat_list_matches():
        require_roles(*MATCH_ROLES)
        items = list(store.matches.values())
        items = _apply_filters(items, {
            "event_id": ("event_id", False),
            "series": ("series", False),
            "status": ("status", False),
            "field_index": ("field_index", True),
            "red_alliance_id": ("red_alliance_id", False),
            "blue_alliance_id": ("blue_alliance_id", False),
        })
        return paginated(items, public)

    @bp.route("/frc-events/matches-flat/<matchId>", methods=["GET"], endpoint="flat_get_match")
    def flat_get_match(matchId):
        require_roles(*MATCH_ROLES)
        m = store.matches.get(matchId)
        if m is None:
            raise ApiError(ERR_MATCH_NOT_FOUND, 404, "Match %s not found" % matchId)
        return success(public(m))

    # --- PartOrder ---
    @bp.route("/frc-events/part-orders", methods=["GET"], endpoint="flat_list_orders")
    def flat_list_orders():
        require_roles(*ORDER_ROLES)
        items = list(store.part_orders.values())
        items = _apply_filters(items, {
            "team_id": ("team_id", False),
            "event_id": ("event_id", False),
            "status": ("status", False),
        })
        return paginated(items, public)

    @bp.route("/frc-events/part-orders/<orderId>", methods=["GET"], endpoint="flat_get_order")
    def flat_get_order(orderId):
        require_roles(*ORDER_ROLES)
        o = store.part_orders.get(orderId)
        if o is None:
            raise ApiError(ERR_ORDER_NOT_FOUND, 404, "PartOrder %s not found" % orderId)
        return success(public(o))

    # --- RobotInspection ---
    @bp.route("/frc-events/robot-inspections", methods=["GET"], endpoint="flat_list_inspections")
    def flat_list_inspections():
        require_roles(*INSPECTION_ROLES)
        items = list(store.robot_inspections.values())
        items = _apply_filters(items, {
            "team_id": ("team_id", False),
            "inspector_id": ("inspector_id", False),
            "status": ("status", False),
        })
        return paginated(items, public)

    @bp.route("/frc-events/robot-inspections/<inspectionId>", methods=["GET"], endpoint="flat_get_inspection")
    def flat_get_inspection(inspectionId):
        require_roles(*INSPECTION_ROLES)
        i = store.robot_inspections.get(inspectionId)
        if i is None:
            raise ApiError(ERR_INSPECTION_NOT_FOUND, 404, "RobotInspection %s not found" % inspectionId)
        return success(public(i))

    # --- ComplianceViolation ---
    @bp.route("/frc-events/violations", methods=["GET"], endpoint="flat_list_violations")
    def flat_list_violations():
        require_roles(*VIOLATION_ROLES)
        items = list(store.violations.values())
        items = _apply_filters(items, {
            "team_id": ("team_id", False),
            "opened_by_person_id": ("opened_by_person_id", False),
            "severity": ("severity", False),
            "resolution_status": ("resolution_status", False),
        })
        return paginated(items, public)

    @bp.route("/frc-events/violations/<violationId>", methods=["GET"], endpoint="flat_get_violation")
    def flat_get_violation(violationId):
        require_roles(*VIOLATION_ROLES)
        v = store.violations.get(violationId)
        if v is None:
            raise ApiError(ERR_VIOLATION_NOT_FOUND, 404, "ComplianceViolation %s not found" % violationId)
        return success(public(v))

    # --- Alliance ---
    @bp.route("/frc-events/alliances-flat", methods=["GET"], endpoint="flat_list_alliances")
    def flat_list_alliances():
        require_roles(*ALLIANCE_ROLES)
        items = list(store.alliances.values())
        items = _apply_filters(items, {
            "event_id": ("event_id", False),
            "captain_team_id": ("captain_team_id", False),
            "pick1_team_id": ("pick1_team_id", False),
            "pick2_team_id": ("pick2_team_id", False),
            "status": ("status", False),
        })
        return paginated(items, public)

    @bp.route("/frc-events/alliances-flat/<allianceId>", methods=["GET"], endpoint="flat_get_alliance")
    def flat_get_alliance(allianceId):
        require_roles(*ALLIANCE_ROLES)
        a = store.alliances.get(allianceId)
        if a is None:
            raise ApiError(ERR_ALLIANCE_NOT_FOUND, 404, "Alliance %s not found" % allianceId)
        return success(public(a))

    @bp.route("/frc-events/alliances-filtered", methods=["GET"], endpoint="flat_list_alliances_filtered")
    def flat_list_alliances_filtered():
        require_roles(*ALLIANCE_ROLES)
        items = list(store.alliances.values())
        items = _apply_filters(items, {
            "event_id": ("event_id", False),
            "captain_team_id": ("captain_team_id", False),
            "pick1_team_id": ("pick1_team_id", False),
            "pick2_team_id": ("pick2_team_id", False),
            "status": ("status", False),
        })
        return paginated(items, public)

    # --- AllianceSelectionRound ---
    @bp.route("/frc-events/alliance-selection-rounds-flat", methods=["GET"], endpoint="flat_list_rounds")
    def flat_list_rounds():
        require_roles(*ROUND_ROLES)
        items = list(store.rounds.values())
        items = _apply_filters(items, {
            "event_id": ("event_id", False),
            "status": ("status", False),
        })
        return paginated(items, public)

    @bp.route("/frc-events/alliance-selection-rounds-flat/<roundId>", methods=["GET"], endpoint="flat_get_round")
    def flat_get_round(roundId):
        require_roles(*ROUND_ROLES)
        r = store.rounds.get(roundId)
        if r is None:
            raise ApiError(ERR_NOT_FOUND, 404, "AllianceSelectionRound %s not found" % roundId)
        return success(public(r))

    @bp.route("/frc-events/alliance-selection-rounds-filtered", methods=["GET"], endpoint="flat_list_rounds_filtered")
    def flat_list_rounds_filtered():
        require_roles(*ROUND_ROLES)
        items = list(store.rounds.values())
        items = _apply_filters(items, {
            "event_id": ("event_id", False),
            "status": ("status", False),
        })
        return paginated(items, public)

    # --- Award ---
    @bp.route("/frc-events/awards-flat", methods=["GET"], endpoint="flat_list_awards")
    def flat_list_awards():
        require_roles(*AWARD_ROLES)
        items = list(store.awards.values())
        items = _apply_filters(items, {
            "event_id": ("event_id", False),
            "winner_team_id": ("winner_team_id", False),
            "status": ("status", False),
            "award_kind": ("award_kind", False),
        })
        return paginated(items, public)

    @bp.route("/frc-events/awards-flat/<awardId>", methods=["GET"], endpoint="flat_get_award")
    def flat_get_award(awardId):
        require_roles(*AWARD_ROLES)
        a = store.awards.get(awardId)
        if a is None:
            raise ApiError(ERR_AWARD_NOT_FOUND, 404, "Award %s not found" % awardId)
        return success(public(a))

    @bp.route("/frc-events/awards-filtered", methods=["GET"], endpoint="flat_list_awards_filtered")
    def flat_list_awards_filtered():
        require_roles(*AWARD_ROLES)
        items = list(store.awards.values())
        items = _apply_filters(items, {
            "event_id": ("event_id", False),
            "winner_team_id": ("winner_team_id", False),
            "status": ("status", False),
            "award_kind": ("award_kind", False),
        })
        return paginated(items, public)

    # --- MatchScoreBreakdown ---
    @bp.route("/frc-events/score-breakdowns", methods=["GET"], endpoint="flat_list_breakdowns")
    def flat_list_breakdowns():
        require_roles(*BREAKDOWN_ROLES)
        items = list(store.breakdowns.values())
        items = _apply_filters(items, {"match_id": ("match_id", False)})
        return paginated(items, public)

    @bp.route("/frc-events/score-breakdowns/<breakdownId>", methods=["GET"], endpoint="flat_get_breakdown")
    def flat_get_breakdown(breakdownId):
        require_roles(*BREAKDOWN_ROLES)
        b = store.breakdowns.get(breakdownId)
        if b is None:
            raise ApiError(ERR_NOT_FOUND, 404, "MatchScoreBreakdown %s not found" % breakdownId)
        return success(public(b))

    # --- QueueSlot ---
    @bp.route("/frc-events/queue-slots", methods=["GET"], endpoint="flat_list_queue_slots")
    def flat_list_queue_slots():
        require_roles(*SLOT_ROLES)
        items = list(store.queue_slots.values())
        items = _apply_filters(items, {
            "match_id": ("match_id", False),
            "team_id": ("team_id", False),
            "status": ("status", False),
        })
        return paginated(items, public)

    @bp.route("/frc-events/queue-slots/<slotId>", methods=["GET"], endpoint="flat_get_queue_slot")
    def flat_get_queue_slot(slotId):
        require_roles(*SLOT_ROLES)
        s = store.queue_slots.get(slotId)
        if s is None:
            raise ApiError(ERR_SLOT_NOT_FOUND, 404, "QueueSlot %s not found" % slotId)
        return success(public(s))

    # --- FieldResetLog ---
    @bp.route("/frc-events/field-reset-logs", methods=["GET"], endpoint="flat_list_reset_logs")
    def flat_list_reset_logs():
        require_roles(*RESET_ROLES)
        items = list(store.reset_logs.values())
        items = _apply_filters(items, {
            "match_id": ("match_id", False),
            "status": ("status", False),
        })
        return paginated(items, public)

    @bp.route("/frc-events/field-reset-logs/<logId>", methods=["GET"], endpoint="flat_get_reset_log")
    def flat_get_reset_log(logId):
        require_roles(*RESET_ROLES)
        l = store.reset_logs.get(logId)
        if l is None:
            raise ApiError(ERR_RESET_LOG_NOT_FOUND, 404, "FieldResetLog %s not found" % logId)
        return success(public(l))

    # --- InterviewSlot ---
    @bp.route("/frc-events/interview-slots", methods=["GET"], endpoint="flat_list_interview_slots")
    def flat_list_interview_slots():
        require_roles(*AWARD_ROLES)
        items = list(store.interview_slots.values())
        items = _apply_filters(items, {
            "award_id": ("award_id", False),
            "team_id": ("team_id", False),
            "judge_id": ("judge_id", False),
            "status": ("status", False),
        })
        return paginated(items, public)

    @bp.route("/frc-events/interview-slots/<slotId>", methods=["GET"], endpoint="flat_get_interview_slot")
    def flat_get_interview_slot(slotId):
        require_roles(*AWARD_ROLES)
        s = store.interview_slots.get(slotId)
        if s is None:
            raise ApiError(ERR_SLOT_NOT_FOUND, 404, "InterviewSlot %s not found" % slotId)
        return success(public(s))

    # --- TravelBooking ---
    @bp.route("/frc-events/travel-bookings", methods=["GET"], endpoint="flat_list_bookings")
    def flat_list_bookings():
        require_roles(*BOOKING_ROLES)
        items = list(store.travel_bookings.values())
        items = _apply_filters(items, {
            "team_id": ("team_id", False),
            "reimbursement_status": ("reimbursement_status", False),
        })
        return paginated(items, public)

    @bp.route("/frc-events/travel-bookings/<bookingId>", methods=["GET"], endpoint="flat_get_booking")
    def flat_get_booking(bookingId):
        require_roles(*BOOKING_ROLES)
        b = store.travel_bookings.get(bookingId)
        if b is None:
            raise ApiError(ERR_BOOKING_NOT_FOUND, 404, "TravelBooking %s not found" % bookingId)
        return success(public(b))
