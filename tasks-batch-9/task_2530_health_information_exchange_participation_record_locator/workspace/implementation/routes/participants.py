"""Participant onboarding endpoints (PRD 3.1, 3.6)."""
from decimal import Decimal

from flask import Blueprint, request

from db import clock, commit, create, db, fmt_dt, now_iso, snapshot, touch
from errors import ApiError, bad_request
from middleware import (
    HIE_ADMIN,
    PARTICIPANT_ADMIN,
    PRIVACY_OFFICER,
    PUBLIC_HEALTH_OFFICER,
    authenticate,
    require_action_role,
    require_scope,
)
from response import entity, entity_created, ok, paginate, pagination
from services import cascades, fees, repo, sanctions, scorecard
from services.conformance import profiles_complete

bp = Blueprint("participants", __name__)

ORG_TYPES = ("HOSPITAL", "CLINIC", "LAB", "HEALTH_PLAN", "PUBLIC_HEALTH")
ONBOARDING_STATUSES = (
    "APPLIED",
    "LEGAL_REVIEW",
    "AGREEMENT_EXECUTED",
    "CONFORMANCE_TESTING",
    "REMEDIATION",
    "CERTIFIED",
    "SUSPENDED",
    "WITHDRAWN",
    "TERMINATED",
)
TERMINAL_ONBOARDING = ("WITHDRAWN", "TERMINATED")
WITHDRAWABLE = (
    "APPLIED",
    "LEGAL_REVIEW",
    "AGREEMENT_EXECUTED",
    "CONFORMANCE_TESTING",
    "REMEDIATION",
)
DATA_CARRYING_STATUSES = (
    "CONFORMANCE_TESTING",
    "CERTIFIED",
    "SUSPENDED",
    "TERMINATED",
)
CONTRIBUTION_STATUSES = ("CONFORMANCE_TESTING", "CERTIFIED")

ONBOARDING_ACTIONS = (
    "SUBMIT_FOR_LEGAL_REVIEW",
    "EXECUTE_AGREEMENT",
    "CERTIFY",
    "REMEDIATE",
    "RESUME_CONFORMANCE",
    "SUSPEND",
    "REINSTATE",
    "TERMINATE",
    "WITHDRAW",
)

# Per-action role restrictions (PRD 2.1).
ONBOARDING_ACTION_ROLES = {
    "SUBMIT_FOR_LEGAL_REVIEW": (PARTICIPANT_ADMIN,),
    "EXECUTE_AGREEMENT": (HIE_ADMIN,),
    "CERTIFY": (HIE_ADMIN,),
    "REMEDIATE": (HIE_ADMIN,),
    "RESUME_CONFORMANCE": (PARTICIPANT_ADMIN,),
    "SUSPEND": (HIE_ADMIN,),
    "REINSTATE": (HIE_ADMIN,),
    "TERMINATE": (HIE_ADMIN,),
    "WITHDRAW": (PARTICIPANT_ADMIN,),
}


def new_participant_fields(legal_name, org_type, volume, email):
    assessment = fees.assess(
        fees.provisional_volume({"declared_annual_patient_volume": volume}),
        "UNGRADED",
        multiplier_override=Decimal("1.00"),
    )
    return {
        "legal_name": legal_name,
        "org_type": org_type,
        "declared_annual_patient_volume": volume,
        "primary_contact_email": email,
        "onboarding_status": "APPLIED",
        "agreement_version": None,
        "agreement_signed_at": None,
        "agreement_executed_by_user_id": None,
        "certified_by_user_id": None,
        "certified_at": None,
        "suspension_reason": None,
        "conformance_attempt_count": 0,
        "consecutive_failed_attempts": 0,
        "remediation_count": 0,
        "passed_profiles": [],
        "fee_tier": assessment["fee_tier"],
        "provisional_monthly_fee_cents": assessment["total_cents"],
        "quality_score": None,
        "quality_grade": "UNGRADED",
        "sanction_points_active": 0,
        "outstanding_balance_cents": 0,
        "active_subscription_count": 0,
    }


@bp.route("/hie/participants", methods=["POST"])
def register_participant():
    from validate import body, req_enum, req_int, req_str

    authenticate((HIE_ADMIN,))
    payload = body()
    legal_name = req_str(payload, "legal_name", min_len=1, max_len=200)
    org_type = req_enum(payload, "org_type", ORG_TYPES)
    volume = req_int(
        payload, "declared_annual_patient_volume", minimum=0, maximum=50000000
    )
    email = req_str(payload, "primary_contact_email")
    if "@" not in email:
        raise bad_request("primary_contact_email must contain an at sign.")
    row = create(
        db.participants,
        "Participant",
        new_participant_fields(legal_name, org_type, volume, email),
    )
    return entity_created(row)


@bp.route("/hie/participants/<pid>/onboarding-transitions", methods=["POST"])
def onboarding_transition(pid):
    from validate import body, opt_str, req_dt, req_enum, req_str

    actor = authenticate((HIE_ADMIN, PARTICIPANT_ADMIN))
    payload = body()
    require_action_role(actor, payload.get("action"), ONBOARDING_ACTION_ROLES)
    action = req_enum(payload, "action", ONBOARDING_ACTIONS)

    agreement_version = None
    signed_at = None
    reason = None
    if action == "EXECUTE_AGREEMENT":
        agreement_version = req_str(payload, "agreement_version")
        signed_at, _parsed = req_dt(payload, "signed_at")
    if action in ("REMEDIATE", "SUSPEND", "TERMINATE"):
        reason = req_str(payload, "reason")

    participant = repo.must("participants", pid)
    status = participant["onboarding_status"]

    if status in TERMINAL_ONBOARDING:
        raise ApiError("ERR_TERMINAL_STATE")

    def invalid():
        return ApiError("ERR_INVALID_STATE_TRANSITION")

    if action == "SUBMIT_FOR_LEGAL_REVIEW":
        if status != "APPLIED" or actor.user_id != participant["id"]:
            raise invalid()
    elif action == "EXECUTE_AGREEMENT":
        if status != "LEGAL_REVIEW":
            raise invalid()
    elif action == "CERTIFY":
        if status != "CONFORMANCE_TESTING":
            raise invalid()
        if (
            participant["agreement_executed_by_user_id"] is not None
            and actor.user_id == participant["agreement_executed_by_user_id"]
        ):
            raise ApiError("ERR_SOD_CERTIFIER_IS_SIGNATORY")
        if repo.has_delinquent_invoice(participant["id"]):
            raise ApiError("ERR_PARTICIPATION_FEE_DELINQUENT")
        if not profiles_complete(participant["passed_profiles"]):
            raise ApiError("ERR_CERTIFICATION_PROFILES_INCOMPLETE")
    elif action == "REMEDIATE":
        if status != "CONFORMANCE_TESTING":
            raise invalid()
    elif action == "RESUME_CONFORMANCE":
        if status != "REMEDIATION" or actor.user_id != participant["id"]:
            raise invalid()
    elif action == "SUSPEND":
        if status != "CERTIFIED":
            raise invalid()
    elif action == "REINSTATE":
        if status != "SUSPENDED":
            raise invalid()
        if (
            int(sanctions.recompute(participant) or 0)
            >= sanctions.SANCTION_SUSPENSION_THRESHOLD
        ):
            raise invalid()
        if repo.has_delinquent_invoice(participant["id"]):
            raise ApiError("ERR_PARTICIPATION_FEE_DELINQUENT")
    elif action == "TERMINATE":
        if status != "SUSPENDED":
            raise invalid()
    elif action == "WITHDRAW":
        if status not in WITHDRAWABLE or actor.user_id != participant["id"]:
            raise invalid()

    if action == "SUBMIT_FOR_LEGAL_REVIEW":
        participant["onboarding_status"] = "LEGAL_REVIEW"
    elif action == "EXECUTE_AGREEMENT":
        participant["agreement_version"] = agreement_version
        participant["agreement_signed_at"] = signed_at
        participant["agreement_executed_by_user_id"] = actor.user_id
        participant["onboarding_status"] = "AGREEMENT_EXECUTED"
        # The system advances to CONFORMANCE_TESTING inside the same request.
        participant["onboarding_status"] = "CONFORMANCE_TESTING"
        participant["consecutive_failed_attempts"] = 0
    elif action == "CERTIFY":
        participant["onboarding_status"] = "CERTIFIED"
        participant["certified_by_user_id"] = actor.user_id
        participant["certified_at"] = now_iso()
    elif action == "REMEDIATE":
        participant["onboarding_status"] = "REMEDIATION"
        participant["remediation_count"] = (
            int(participant["remediation_count"] or 0) + 1
        )
    elif action == "RESUME_CONFORMANCE":
        participant["onboarding_status"] = "CONFORMANCE_TESTING"
        participant["consecutive_failed_attempts"] = 0
    elif action == "SUSPEND":
        cascades.suspend_participant(participant, reason)
    elif action == "REINSTATE":
        participant["onboarding_status"] = "CERTIFIED"
        participant["suspension_reason"] = None
        cascades.restore_feeds(participant)
        scorecard.apply_to_participant(participant)
        cascades.reactivate_subscriptions(participant)
    elif action == "TERMINATE":
        participant["onboarding_status"] = "TERMINATED"
        participant["suspension_reason"] = reason
        cascades.withdraw_records_and_recount(participant)
        cascades.terminate_subscriptions(participant)
    elif action == "WITHDRAW":
        participant["onboarding_status"] = "WITHDRAWN"
        for test in repo.where(
            "conformance_tests", participant_id=participant["id"], status="RUNNING"
        ):
            before_test = snapshot(test)
            test["status"] = "FAILED"
            test["failure_categories"] = ["TRANSPORT"]
            commit(test, before_test)

    # Every onboarding step increments the participant's version by exactly one.
    touch(participant)
    return entity(participant)


@bp.route("/hie/participants/<pid>", methods=["GET"])
def read_participant(pid):
    authenticate(
        (HIE_ADMIN, PARTICIPANT_ADMIN, PRIVACY_OFFICER, PUBLIC_HEALTH_OFFICER)
    )
    participant = repo.must("participants", pid)
    # PRD 3.8: the sanction window is anchored on the logical clock, so moving the
    # clock alone can change the total; the read reports the live sum.
    sanctions.recompute(participant)
    return entity(participant)


@bp.route("/hie/participants", methods=["GET"])
def list_participants():
    authenticate((HIE_ADMIN, PRIVACY_OFFICER))
    limit, offset = pagination()
    rows = repo.all_rows("participants")
    for row in rows:
        sanctions.recompute(row)
    onboarding_status = request.args.get("onboarding_status")
    org_type = request.args.get("org_type")
    fee_tier = request.args.get("fee_tier")
    if onboarding_status:
        rows = [r for r in rows if r["onboarding_status"] == onboarding_status]
    if org_type:
        rows = [r for r in rows if r["org_type"] == org_type]
    if fee_tier:
        rows = [r for r in rows if r["fee_tier"] == fee_tier]
    return paginate(rows, limit, offset)


@bp.route("/hie/participants/<pid>/scorecard", methods=["GET"])
def read_scorecard(pid):
    actor = authenticate((HIE_ADMIN, PARTICIPANT_ADMIN, PRIVACY_OFFICER))
    require_scope(actor, pid)
    participant = repo.must("participants", pid)
    return ok(scorecard.compute(participant["id"]))
