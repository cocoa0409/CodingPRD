"""ActuarialOpinion endpoints."""
from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_FILING_DEADLINE_PASSED,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_OPINION_NO_STUDIES,
    ERR_SOD_SIGNER_CONFLICT,
    ERR_STUDY_ATTACHED,
    ERR_STUDY_NOT_APPROVED,
)
from middleware import authorized
from response import success_object
from routes.helpers import new_common_record, touch
from services.serializers import opinion_view
from util import add_days, parse_date, CLOCK
from validate import (
    get_body,
    reject_server_managed,
    req_date,
    req_enum,
    req_str,
    require_path_resource,
)

bp = Blueprint("opinions", __name__)

OPINION_COMPUTED = [
    "status", "created_by_user_id", "signed_by_user_id", "signed_at",
    "filing_deadline_date",
]

SCOPES = ["REASONABLE", "DEFICIENT", "REDUNDANT", "NO_OPINION"]


@bp.post("/actuarial/opinions")
def create_opinion():
    caller = authorized(["AppointedActuary"])
    body = get_body()
    reject_server_managed(body, OPINION_COMPUTED)
    statement_date = req_date(body, "statement_date")
    scope = req_enum(body, "opinion_scope", SCOPES)

    deadline = add_days(parse_date(statement_date), 60).isoformat()

    rec = new_common_record({
        "statement_date": statement_date,
        "opinion_scope": scope,
        "status": "DRAFT",
        "created_by_user_id": caller.user_id,
        "signed_by_user_id": None,
        "signed_at": None,
        "filing_deadline_date": deadline,
    })
    db["opinions"][rec["id"]] = rec
    return success_object(opinion_view(rec), status=201)


@bp.get("/actuarial/opinions/<oid>")
def get_opinion(oid):
    authorized(["ActuarialAnalyst", "PeerReviewer", "AppointedActuary"])
    rec = require_path_resource("opinions", oid)
    return success_object(opinion_view(rec))


@bp.post("/actuarial/opinions/<oid>/attach-study")
def attach_study(oid):
    authorized(["AppointedActuary"])
    body = get_body()
    reject_server_managed(body)
    opinion = require_path_resource("opinions", oid)
    if opinion["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, "only DRAFT opinions can accept attachments")

    study_id = req_str(body, "study_id")
    study = db["studies"].get(study_id)
    if study is None:
        raise_error(ERR_NOT_FOUND, "study_id does not resolve")

    if study["status"] != "APPROVED":
        raise_error(ERR_STUDY_NOT_APPROVED, "attached study must be APPROVED")
    if study.get("opinion_id") is not None:
        raise_error(ERR_STUDY_ATTACHED, "study already attached to an opinion")

    study["opinion_id"] = opinion["id"]
    touch(study)
    touch(opinion)
    return success_object(opinion_view(opinion))


@bp.post("/actuarial/opinions/<oid>/sign")
def sign_opinion(oid):
    caller = authorized(["AppointedActuary"])
    opinion = require_path_resource("opinions", oid)
    if opinion["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, "only DRAFT opinions can be signed")

    attached = [s for s in db["studies"].values() if s.get("opinion_id") == opinion["id"]]

    # SoD first (tier 7): signer != opinion drafter AND != any attached study's
    # creator or reviewer.
    if caller.user_id == opinion["created_by_user_id"]:
        raise_error(ERR_SOD_SIGNER_CONFLICT,
                    "signer equals the opinion's drafter")
    for s in attached:
        if caller.user_id == s.get("created_by_user_id"):
            raise_error(ERR_SOD_SIGNER_CONFLICT,
                        "signer equals an attached study's creator")
        if s.get("reviewed_by_user_id") is not None and caller.user_id == s.get("reviewed_by_user_id"):
            raise_error(ERR_SOD_SIGNER_CONFLICT,
                        "signer equals an attached study's reviewer")

    # Attachment checks (tier 8).
    if not attached:
        raise_error(ERR_OPINION_NO_STUDIES, "opinion has no attached studies")
    for s in attached:
        if s["status"] != "APPROVED":
            raise_error(ERR_STUDY_NOT_APPROVED, "every attached study must be APPROVED")

    # Temporal check (tier 10): logical clock date <= filing_deadline_date.
    today = CLOCK.today()
    deadline = parse_date(opinion["filing_deadline_date"])
    if today > deadline:
        raise_error(ERR_FILING_DEADLINE_PASSED, "signing after filing_deadline_date")

    opinion["status"] = "SIGNED"
    opinion["signed_by_user_id"] = caller.user_id
    opinion["signed_at"] = CLOCK.now_iso()
    touch(opinion)

    for s in attached:
        s["status"] = "LOCKED"
        touch(s)

    return success_object(opinion_view(opinion))
