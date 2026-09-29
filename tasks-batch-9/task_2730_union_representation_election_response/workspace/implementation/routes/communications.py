"""Campaign communications: drafting, accuracy review, risk scoring, legal clearance, delivery."""

from flask import Blueprint

import auth
import calc
import clockutil
import gates
import store
import validate
from errors import ApiError
from routes import common

bp = Blueprint("communications", __name__)

BASE = "/labor-relations/campaign-communications"
LIST_ROLES = (auth.DIRECTOR, auth.COUNSEL, auth.TRAINER, auth.SUPERVISOR, auth.BOARD)
READ_ROLES = (auth.DIRECTOR, auth.COUNSEL, auth.TRAINER, auth.BOARD)


def _current_polls_open_at(petition_id):
    rnd = store.current_round(petition_id)
    if rnd is None:
        return None
    return clockutil.parse_dt(rnd.get("polls_open_at"))


@bp.route(BASE, methods=["POST"])
@auth.endpoint([auth.DIRECTOR])
def create_communication(user_id, role):
    schema = validate.Schema(validate.body())
    petition_id = schema.reference("petition_id")
    presenter_supervisor_id = schema.reference("presenter_supervisor_id", required=False)
    channel = schema.enum("channel", common.CHANNELS)
    audience_scope = schema.enum("audience_scope", common.AUDIENCE_SCOPES)
    planned_delivery_at = schema.datetime("planned_delivery_at")
    duration_minutes = schema.integer("duration_minutes", required=False, default=60, minimum=1)
    message_summary = schema.string("message_summary")
    threat_statement_count = schema.integer("threat_statement_count", required=False,
                                            default=0, minimum=0)
    contains_interrogation = schema.boolean("contains_interrogation", required=False, default=False)
    contains_promise = schema.boolean("contains_promise_of_benefit", required=False, default=False)
    contains_surveillance = schema.boolean("contains_surveillance_reference",
                                           required=False, default=False)
    material_claim_count = schema.integer("material_claim_count", required=False,
                                          default=0, minimum=0)
    unsupported_material_claim_count = schema.integer("unsupported_material_claim_count",
                                                      required=False, default=0, minimum=0)

    is_meeting = channel in calc.MEETING_CHANNELS
    if is_meeting and presenter_supervisor_id is None:
        raise validate.invalid("presenter_supervisor_id is required for a meeting channel.")
    if not is_meeting and presenter_supervisor_id is not None:
        raise validate.invalid("presenter_supervisor_id is only carried on a meeting channel.")

    petition = gates.must_exist("petitions", petition_id)
    presenter = None
    if presenter_supervisor_id is not None:
        presenter = gates.must_exist("supervisors", presenter_supervisor_id)
        gates.require_same_petition(petition_id, presenter["petition_id"])

    row = {
        "petition_id": petition_id,
        "presenter_supervisor_id": presenter_supervisor_id,
        "channel": channel,
        "audience_scope": audience_scope,
        "planned_delivery_at": planned_delivery_at,
        "duration_minutes": duration_minutes,
        "message_summary": message_summary,
        "threat_statement_count": threat_statement_count,
        "contains_interrogation": contains_interrogation,
        "contains_promise_of_benefit": contains_promise,
        "contains_surveillance_reference": contains_surveillance,
        "material_claim_count": material_claim_count,
        "unsupported_material_claim_count": unsupported_material_claim_count,
        "accuracy_reviewed_at": None,
        "risk_score": 0,
        "peerless_plywood_violation": False,
        "status": "DRAFT",
        "revision_round": 0,
        "authored_by_user_id": user_id,
        "reviewed_by_user_id": None,
        "escalation_ack": False,
        "blocked_reason": None,
        "delivered_at": None,
        "_last_reviewed_at": None,
    }

    if is_meeting:
        proposed = calc.presenter_interval(row)
        for existing in store.DB["campaign_communications"].values():
            if existing.get("presenter_supervisor_id") != presenter_supervisor_id:
                continue
            if existing["channel"] not in calc.MEETING_CHANNELS:
                continue
            if calc.closed_intervals_overlap(proposed, calc.presenter_interval(existing)):
                raise ApiError("ERR_PRESENTER_SCHEDULE_CONFLICT",
                               "The presenter's calendar already holds an overlapping meeting.")

    store.insert("campaign_communications", row)
    return common.one_created(row)


@bp.route(BASE, methods=["GET"])
@auth.endpoint(LIST_ROLES)
def list_communications(user_id, role):
    presenter_filter = validate.query_string("presenter_supervisor_id")
    if role == auth.SUPERVISOR:
        if presenter_filter is not None and presenter_filter != user_id:
            raise ApiError("ERR_SUPERVISOR_IDENTITY_MISMATCH",
                           "A PlantSupervisor may only filter to their own presenter id.")
        presenter_filter = user_id
    petition_id = validate.query_string("petition_id")
    status = validate.query_enum("status", common.COMMUNICATION_STATUSES)
    rows = store.ordered("campaign_communications")
    if petition_id is not None:
        rows = [r for r in rows if r["petition_id"] == petition_id]
    if presenter_filter is not None:
        rows = [r for r in rows if r.get("presenter_supervisor_id") == presenter_filter]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return common.list_response(rows)


@bp.route(BASE + "/<mid>", methods=["GET"])
@auth.endpoint(READ_ROLES)
def read_communication(user_id, role, mid):
    return common.one(gates.must_exist("campaign_communications", mid))


@bp.route(BASE + "/<mid>/accuracy-review", methods=["POST"])
@auth.endpoint([auth.DIRECTOR, auth.ANALYST])
def accuracy_review(user_id, role, mid):
    schema = validate.Schema(validate.body())
    material_claim_count = schema.integer("material_claim_count", minimum=0)
    unsupported = schema.integer("unsupported_material_claim_count", minimum=0)
    message = gates.must_exist("campaign_communications", mid)

    if unsupported > material_claim_count:
        raise ApiError("ERR_CLAIM_COUNTS_INCONSISTENT",
                       "The unsupported claim count exceeds the material claim count.")

    message["material_claim_count"] = material_claim_count
    message["unsupported_material_claim_count"] = unsupported
    message["accuracy_reviewed_at"] = clockutil.now_dt_str()
    polls_open_at = _current_polls_open_at(message["petition_id"])
    violation = calc.peerless_plywood_violation(message, polls_open_at)
    message["peerless_plywood_violation"] = violation
    message["risk_score"] = 100 if violation else calc.risk_score(message)
    store.touch(message)
    return common.one(message)


@bp.route(BASE + "/<mid>/submit-for-review", methods=["POST"])
@auth.endpoint([auth.DIRECTOR])
def submit_for_review(user_id, role, mid):
    validate.body()
    message = gates.must_exist("campaign_communications", mid)

    if message["status"] not in ("DRAFT", "REVISION_REQUIRED"):
        raise ApiError("ERR_COMMUNICATION_STATUS_INVALID",
                       "Only a DRAFT or REVISION_REQUIRED message may enter legal review.")

    reviewed_at = clockutil.parse_dt(message.get("accuracy_reviewed_at"))
    if reviewed_at is None:
        raise ApiError("ERR_ACCURACY_REVIEW_MISSING",
                       "The message has not been accuracy-reviewed.")
    if message["status"] == "REVISION_REQUIRED":
        last_review = clockutil.parse_dt(message.get("_last_reviewed_at"))
        if last_review is not None and reviewed_at < last_review:
            raise ApiError("ERR_ACCURACY_REVIEW_MISSING",
                           "The accuracy review predates the last legal review.")
    if message["channel"] in calc.MEETING_CHANNELS:
        presenter = store.get("supervisors", message.get("presenter_supervisor_id"))
        if presenter is None or presenter["training_status"] != "TRAINED":
            raise ApiError("ERR_PRESENTER_NOT_TRAINED",
                           "The presenting supervisor is not TRAINED.")
    if message["peerless_plywood_violation"]:
        raise ApiError("ERR_PEERLESS_PLYWOOD_WINDOW",
                       "The message sits inside the pre-poll captive-audience blackout.")
    if (message["risk_score"] or 0) >= calc.RISK_PROHIBITED_THRESHOLD:
        raise ApiError("ERR_RISK_SCORE_PROHIBITED",
                       "The risk score is prohibited; the message may not enter legal review.")
    if (message["status"] == "REVISION_REQUIRED"
            and message["revision_round"] >= calc.MAX_REVISION_ROUNDS):
        raise ApiError("ERR_REVISION_LIMIT_EXCEEDED",
                       "The revision ceiling has been reached.")

    message["status"] = "PENDING_LEGAL_REVIEW"
    message["reviewed_by_user_id"] = None
    store.touch(message)
    return common.one(message)


@bp.route(BASE + "/<mid>/review", methods=["POST"])
@auth.endpoint([auth.COUNSEL])
def review_communication(user_id, role, mid):
    # Segregation of duties (step 4) precedes schema (5) and path existence (6).
    candidate = store.get("campaign_communications", mid)
    if candidate is not None and candidate.get("authored_by_user_id") == user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The author of a message may never disposition its legal review.")

    schema = validate.Schema(validate.body())
    disposition = schema.enum("disposition", common.REVIEW_DISPOSITIONS)
    escalation_ack = schema.boolean("escalation_ack", required=False, default=None)
    schema.string("review_note", required=False, allow_empty=True)

    message = gates.must_exist("campaign_communications", mid)
    if message["status"] != "PENDING_LEGAL_REVIEW":
        raise ApiError("ERR_COMMUNICATION_STATUS_INVALID",
                       "Only a message in PENDING_LEGAL_REVIEW may be dispositioned.")
    if message["peerless_plywood_violation"]:
        raise ApiError("ERR_PEERLESS_PLYWOOD_WINDOW",
                       "The message sits inside the pre-poll captive-audience blackout.")

    if disposition == "APPROVE":
        if ((message["risk_score"] or 0) >= calc.RISK_ESCALATION_THRESHOLD
                and not escalation_ack):
            raise ApiError("ERR_ESCALATION_ACK_REQUIRED",
                           "An elevated risk score requires escalation_ack.")
        if escalation_ack is not None:
            message["escalation_ack"] = escalation_ack
        message["status"] = "APPROVED"
        message["reviewed_by_user_id"] = user_id
    else:
        if message["revision_round"] >= calc.MAX_REVISION_ROUNDS:
            raise ApiError("ERR_REVISION_LIMIT_EXCEEDED",
                           "The revision ceiling has been reached.")
        if escalation_ack is not None:
            message["escalation_ack"] = escalation_ack
        message["status"] = "REVISION_REQUIRED"
        message["revision_round"] += 1
        message["reviewed_by_user_id"] = user_id

    message["_last_reviewed_at"] = clockutil.now_dt_str()
    store.touch(message)
    return common.one(message)


@bp.route(BASE + "/<mid>/deliver", methods=["POST"])
@auth.endpoint([auth.DIRECTOR])
def deliver_communication(user_id, role, mid):
    validate.body()
    message = gates.must_exist("campaign_communications", mid)
    petition = store.petition(message["petition_id"])

    gates.require_open_posture(petition)
    if message["status"] != "APPROVED":
        raise ApiError("ERR_COMMUNICATION_STATUS_INVALID",
                       "Only an APPROVED message may be delivered.")

    rnd = store.current_round(message["petition_id"])
    polls_open_at = clockutil.parse_dt(rnd.get("polls_open_at")) if rnd else None
    now = clockutil.now()
    if message["peerless_plywood_violation"]:
        raise ApiError("ERR_PEERLESS_PLYWOOD_WINDOW",
                       "The message carries a per-se blackout violation.")
    # The per-se rule is re-evaluated against the round in force at delivery: a
    # captive-audience message whose planned delivery sits inside the blackout is
    # refused here even when the polls have since closed (PRD 2.11 collision 1).
    if calc.peerless_plywood_violation(message, polls_open_at):
        raise ApiError("ERR_PEERLESS_PLYWOOD_WINDOW",
                       "The message's planned delivery sits inside the pre-poll blackout.")
    if (message["channel"] == "CAPTIVE_AUDIENCE_MEETING"
            and calc.in_peerless_window(now, polls_open_at)):
        raise ApiError("ERR_PEERLESS_PLYWOOD_WINDOW",
                       "The logical clock sits inside the pre-poll captive-audience blackout.")

    polls_close_at = clockutil.parse_dt(rnd.get("polls_close_at")) if rnd else None
    if (rnd is None or rnd["status"] not in ("SCHEDULED", "POLLS_OPEN")
            or polls_close_at is None or not now < polls_close_at):
        raise ApiError("ERR_CAMPAIGN_PERIOD_CLOSED", "The lawful campaign period has closed.")

    message["status"] = "DELIVERED"
    message["delivered_at"] = clockutil.fmt_dt(now)
    store.touch(message)
    return common.one(message)
