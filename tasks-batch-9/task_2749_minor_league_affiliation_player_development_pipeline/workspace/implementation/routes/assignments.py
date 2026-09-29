"""Player assignment endpoints (PRD Sections 3.6, 3.7 and 3.8)."""
from decimal import Decimal

from flask import Blueprint

import auth
import common
import config
import derive
import envelope
import flows
import serialize
import store
import validate
from errors import ApiError

bp = Blueprint("assignments", __name__)

ROSTER_TYPES = ("LEVEL", "COMPLEX")
LIVE_STATUSES = ("PENDING_CLEARANCE", "ACTIVE", "SUSPENDED")

TRANSITIONS = {
    "ACTIVATE": ("PENDING_CLEARANCE",),
    "COMPLETE": ("ACTIVE",),
    "REVOKE": ("PENDING_CLEARANCE", "ACTIVE", "SUSPENDED"),
    "SUSPEND": ("ACTIVE",),
    "RESUME": ("SUSPENDED",),
}


def window_conflict(player_id, new_type, superseded_id, start, end, exclude_id=None):
    """PRD Section 3.6: intersection, plus a transfer buffer of more than two days."""
    if new_type == "REHAB":
        return False
    for prior in derive.assignments_of_player(player_id):
        if prior["id"] == exclude_id:
            continue
        if prior["status"] not in LIVE_STATUSES:
            continue
        if prior["assignment_type"] not in ROSTER_TYPES:
            continue
        if superseded_id is not None and prior["id"] == superseded_id:
            continue
        prior_start = store.parse_date(prior["effective_date"])
        prior_end = store.parse_date(prior["end_date"])
        if prior_start is None or prior_end is None:
            continue
        if start <= prior_end and prior_start <= end:
            return True
        gap = store.days_between(prior_end, start)
        if 0 < gap <= config.TRANSFER_BUFFER_DAYS:
            return True
    return False


def current_level_rank(player_id, superseded_id=None, exclude_id=None):
    rows = store.sorted_rows(derive.assignments_of_player(player_id))
    for assignment in reversed(rows):
        if assignment["id"] == exclude_id:
            continue
        if assignment["status"] == "ACTIVE" and assignment["assignment_type"] in ROSTER_TYPES:
            return config.LEVEL_RANK.get(assignment["level_at_assignment"], 0)
    if superseded_id is not None:
        prior = store.assignments.get(superseded_id)
        if prior is not None:
            return config.LEVEL_RANK.get(prior["level_at_assignment"], 0)
    for assignment in reversed(rows):
        if assignment["id"] == exclude_id:
            continue
        if assignment["assignment_type"] in ROSTER_TYPES:
            return config.LEVEL_RANK.get(assignment["level_at_assignment"], 0)
    return 0


def promotion_admitted(player, affiliate, current_rank):
    if player["promotion_readiness"] < config.PROMOTION_READINESS_THRESHOLD:
        return False
    if player["service_days_accrued"] < config.PROMOTION_MIN_SERVICE_DAYS:
        return False
    return config.LEVEL_RANK.get(affiliate["level"], 0) > current_rank


def _require_gates(affiliate_id, promotion=False):
    """Checks 14, 15 and 16."""
    agreement = derive.active_agreement(affiliate_id)
    if agreement is None:
        raise ApiError("ERR_AGREEMENT_NOT_ACTIVE")
    if agreement["posture"] == "FROZEN":
        raise ApiError("ERR_AGREEMENT_POSTURE_FROZEN")
    if promotion and agreement["posture"] == "RESTRICTED":
        raise ApiError("ERR_AGREEMENT_POSTURE_RESTRICTED")
    return agreement


def _require_clearance(assignment, allow_expired_error=True):
    """Checks 18 and 19."""
    required = derive.CLEARANCE_FOR_TYPE[assignment["assignment_type"]]
    issued = derive.issued_clearances(assignment["player_id"], required)
    if not issued:
        raise ApiError("ERR_MEDICAL_CLEARANCE_REQUIRED")
    valid = [c for c in issued if not derive.clearance_is_expired(c)]
    if not valid:
        raise ApiError("ERR_MEDICAL_CLEARANCE_EXPIRED" if allow_expired_error
                       else "ERR_MEDICAL_CLEARANCE_REQUIRED")
    return valid[-1]


@bp.post("/assignments")
def create_assignment():
    user_id, _role = auth.require(config.ROLE_FARM)
    body = validate.json_body()
    player_id = validate.id_field(body, "player_id")
    affiliate_id = validate.id_field(body, "affiliate_id")
    assignment_type = validate.enum_field(body, "assignment_type", config.ASSIGNMENT_TYPES)
    movement_reason = validate.enum_field(body, "movement_reason", config.MOVEMENT_REASONS)
    effective_date = validate.date_field(body, "effective_date")
    end_date = validate.date_field(body, "end_date")
    expected = validate.int_field(body, "expected_player_version")
    ceiling = validate.dec_field(body, "workload_ceiling_index", lo=Decimal("0.00"),
                                hi=config.WORKLOAD_INDEX_CEILING, required=False,
                                default=Decimal("12.00"), places=2, exclusive_lo=True)
    superseded_id = validate.id_field(body, "superseded_assignment_id", required=False,
                                      default=None)
    start = store.parse_date(effective_date)
    end = store.parse_date(end_date)
    if end < start:
        raise validate.bad("end_date may not be earlier than effective_date.")

    player = common.need("players", player_id)
    affiliate = common.need("affiliates", affiliate_id)
    if superseded_id is not None:
        common.need("assignments", superseded_id)

    if expected != player["version"]:
        raise ApiError("ERR_STALE_PLAYER_VERSION")

    _require_gates(affiliate_id, promotion=(movement_reason == "PROMOTION"))

    if window_conflict(player_id, assignment_type, superseded_id, start, end):
        raise ApiError("ERR_ASSIGNMENT_WINDOW_CONFLICT")

    if movement_reason == "PROMOTION":
        rank = current_level_rank(player_id, superseded_id)
        if not promotion_admitted(player, affiliate, rank):
            raise ApiError("ERR_PROMOTION_CRITERIA_NOT_MET")

    record = store.base_record()
    record.update({
        "player_id": player_id,
        "affiliate_id": affiliate_id,
        "superseded_assignment_id": superseded_id,
        "assignment_type": assignment_type,
        "movement_reason": movement_reason,
        "effective_date": effective_date,
        "end_date": end_date,
        "workload_ceiling_index": ceiling,
        "status": "PENDING_CLEARANCE",
        "initiated_by_user_id": user_id,
        "level_at_assignment": affiliate["level"],
        "projected_optional_days": store.days_between(start, end) + 1,
        "option_year_charged": False,
    })
    store.assignments[record["id"]] = record
    store.touch(player)
    common.commit()
    return envelope.object_response(serialize.assignment(record), 201)


@bp.get("/assignments")
def list_assignments():
    auth.require(config.ROLE_FARM, config.ROLE_MEDICAL, config.ROLE_COMPLIANCE)
    rows = list(store.assignments.values())
    rows = common.apply_filters(rows, (
        ("player_id", "player_id"),
        ("affiliate_id", "affiliate_id"),
        ("superseded_assignment_id", "superseded_assignment_id"),
        ("status", "status"),
        ("assignment_type", "assignment_type")))
    return envelope.paginate(rows, serialize.assignment)


@bp.get("/assignments/<assignment_id>")
def read_assignment(assignment_id):
    auth.require(config.ROLE_FARM, config.ROLE_MEDICAL, config.ROLE_COMPLIANCE,
                 config.ROLE_OPERATOR)
    record = common.need("assignments", assignment_id)
    return envelope.object_response(serialize.assignment(record))


@bp.get("/assignments/<assignment_id>/option-years")
def list_option_years(assignment_id):
    auth.require(config.ROLE_FARM, config.ROLE_COMPLIANCE)
    common.need("assignments", assignment_id)
    rows = derive.option_years_of_assignment(assignment_id)
    rows = common.apply_filters(rows, (("status", "status"),))
    return envelope.paginate(rows, serialize.option_year)


@bp.get("/assignments/<assignment_id>/transaction-reports")
def list_reports(assignment_id):
    auth.require(config.ROLE_FARM, config.ROLE_COMPLIANCE)
    common.need("assignments", assignment_id)
    rows = derive.reports_of_assignment(assignment_id)
    rows = common.apply_filters(rows, (("status", "status"),
                                       ("transaction_type", "transaction_type")))
    return envelope.paginate(rows, serialize.report)


@bp.post("/assignments/<assignment_id>/disposition")
def dispose_assignment(assignment_id):
    _user_id, role = auth.require(config.ROLE_FARM)
    raw = auth.raw_body()
    auth.check_action_role(raw.get("action"), role, config.ASSIGNMENT_ACTION_ROLES)
    assignment = common.need("assignments", assignment_id)
    body = validate.json_body()
    action = auth.require_action(body, config.ASSIGNMENT_ACTION_ROLES)
    validate.str_field(body, "note", required=False, default=None, allow_blank=True)

    if assignment["status"] not in TRANSITIONS[action]:
        raise ApiError("ERR_INVALID_ASSIGNMENT_STATE",
                       "An assignment in status %s does not accept %s."
                       % (assignment["status"], action))

    affiliate = store.affiliates.get(assignment["affiliate_id"])
    player = store.players.get(assignment["player_id"])
    assignment_type = assignment["assignment_type"]

    if action == "ACTIVATE":
        _require_gates(assignment["affiliate_id"])
        _require_clearance(assignment)
        if affiliate is not None and affiliate["facility_status"] == "DEFICIENT":
            raise ApiError("ERR_FACILITY_DEFICIENCY_BLOCKING")
        if assignment["movement_reason"] == "PROMOTION":
            rank = current_level_rank(player["id"],
                                     assignment.get("superseded_assignment_id"),
                                     exclude_id=assignment["id"])
            if not promotion_admitted(player, affiliate, rank):
                raise ApiError("ERR_PROMOTION_CRITERIA_NOT_MET")
        if assignment_type in ROSTER_TYPES:
            if affiliate["active_roster_count"] >= affiliate["roster_limit"]:
                raise ApiError("ERR_ROSTER_LIMIT_EXCEEDED")
        else:
            if affiliate["rehab_assignment_count"] >= config.REHAB_SLOT_LIMIT:
                raise ApiError("ERR_REHAB_SLOT_LIMIT_EXCEEDED")
        if (player["is_on_domestic_reserve_list"]
                and assignment_type in ROSTER_TYPES
                and player["current_affiliate_id"] != affiliate["id"]):
            if affiliate["reserve_list_count"] >= affiliate["reserve_slots"]:
                raise ApiError("ERR_DOMESTIC_RESERVE_LIST_FULL")
        charges_option_year = (assignment_type in ROSTER_TYPES
                               and assignment["projected_optional_days"]
                               >= config.OPTION_YEAR_MIN_DAYS)
        if charges_option_year and player["option_years_remaining"] < 1:
            raise ApiError("ERR_OPTION_YEARS_EXHAUSTED")

        store.touch(assignment)
        assignment["status"] = "ACTIVE"
        if charges_option_year:
            flows.create_option_year(assignment)
            assignment["option_year_charged"] = True
        if assignment_type in ROSTER_TYPES:
            player["roster_status"] = "ACTIVE"
        superseded_id = assignment.get("superseded_assignment_id")
        if superseded_id:
            prior = store.assignments.get(superseded_id)
            if prior is not None and prior["status"] == "ACTIVE":
                flows.complete_assignment(prior)
        flows.create_report(
            assignment,
            flows.TRANSACTION_TYPE_FOR_REASON[assignment["movement_reason"]])

    elif action == "COMPLETE":
        if assignment_type == "REHAB":
            issued = derive.issued_clearances(assignment["player_id"], "REHAB_COMPLETE")
            if not issued:
                raise ApiError("ERR_MEDICAL_CLEARANCE_REQUIRED")
        flows.complete_assignment(assignment)

    elif action == "SUSPEND":
        flows.suspend_assignment(assignment)

    elif action == "RESUME":
        _require_gates(assignment["affiliate_id"])
        _require_clearance(assignment, allow_expired_error=False)
        if assignment_type in ROSTER_TYPES:
            if affiliate["active_roster_count"] >= affiliate["roster_limit"]:
                raise ApiError("ERR_ROSTER_LIMIT_EXCEEDED")
        store.touch(assignment)
        assignment["status"] = "ACTIVE"
        player["roster_status"] = "ACTIVE"
        flows.create_report(assignment, "RECALL")

    elif action == "REVOKE":
        flows.revoke_assignment(assignment)

    common.commit()
    return envelope.object_response(serialize.assignment(assignment))
