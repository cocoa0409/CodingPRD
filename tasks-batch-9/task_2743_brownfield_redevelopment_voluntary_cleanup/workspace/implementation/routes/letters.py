"""No-further-action letters: drafting, issuance, lender reliance, re-issuance."""

from flask import Blueprint

import db
import response
import validation as V
from errors import ApiError
from middleware import actor_id, endpoint
from routes.common import apply_filter, fetch, require_owner
from services import derive
from services.constants import LETTER_SCOPES, LETTER_STATUS
from services.serialize import dump_letter

bp = Blueprint("letters", __name__)

READ_ROLES = ["Redeveloper", "StateAgencyReviewer", "Lender", "Insurer",
              "EnvironmentalConsultant"]


@bp.post("/nfa-letters")
@endpoint(["Redeveloper"])
def create_letter():
    body = V.json_body()
    site_id = V.id_field(body, "site_id", True)
    enrollment_id = V.id_field(body, "vcp_enrollment_id", True)
    scope = V.enum_field(body, "requested_scope", LETTER_SCOPES, True)

    site = fetch("sites", site_id)
    enrollment = fetch("vcp_enrollments", enrollment_id)
    require_owner(site)
    derive.assert_not_frozen(site)
    if enrollment["site_id"] != site["id"]:
        raise ApiError("ERR_PLAN_SITE_MISMATCH",
                       "The named enrollment belongs to a different parcel.")

    row = db.insert("nfa_letters", {
        "site_id": site["id"],
        "vcp_enrollment_id": enrollment["id"],
        "requested_scope": scope,
        "status": "DRAFT",
        "issued_on": None,
        "issued_by_user_id": None,
        "controls_certified_count": 0,
        "accepted_by_lender_user_id": None,
        "lender_reference": None,
        "revocation_reason": None,
        "reissue_count": 0,
    })
    return response.created(dump_letter(row))


@bp.get("/nfa-letters")
@endpoint(READ_ROLES)
def list_letters():
    rows = db.ordered(db.all_rows("nfa_letters"))
    rows = apply_filter(rows, "site_id", V.query_string("site_id"))
    rows = apply_filter(rows, "vcp_enrollment_id",
                        V.query_string("vcp_enrollment_id"))
    rows = apply_filter(rows, "status", V.query_enum("status", LETTER_STATUS))
    return response.list_response(rows, dump_letter)


@bp.get("/nfa-letters/<letter_id>")
@endpoint(READ_ROLES)
def get_letter(letter_id):
    return response.object_response(dump_letter(fetch("nfa_letters", letter_id)))


@bp.post("/nfa-letters/<letter_id>/issue")
@endpoint(["StateAgencyReviewer"])
def issue_letter(letter_id):
    letter = fetch("nfa_letters", letter_id)
    site = db.get("sites", letter["site_id"])
    enrollment = db.get("vcp_enrollments", letter["vcp_enrollment_id"])
    if site is not None:
        derive.assert_not_frozen(site)
        derive.assert_posture_open(site)
    if letter["status"] not in ("DRAFT", "REVOKED"):
        raise ApiError("ERR_INVALID_LETTER_STATE",
                       "Only a DRAFT or REVOKED letter may be issued.")

    reissue = letter["status"] == "REVOKED"
    plan = (derive.approved_plan_of_enrollment(enrollment["id"])
            if enrollment is not None else None)

    if reissue:
        if letter.get("revocation_reason") != "CONTROL_FAILURE":
            raise ApiError("ERR_LETTER_NOT_CURABLE",
                           "A letter revoked for BFPP forfeiture can never be "
                           "re-issued.")
    else:
        if enrollment is None or enrollment["status"] != "COMPLETION_REVIEW":
            raise ApiError("ERR_INVALID_ENROLLMENT_STATE",
                           "The parent enrollment must be in COMPLETION_REVIEW.")

    if plan is None:
        raise ApiError("ERR_CONTROLS_NOT_OPERATING",
                       "The enrollment has no approved remedial action plan.")
    for control in derive.controls_of_plan(plan["id"]):
        if control["status"] != "OPERATING":
            raise ApiError("ERR_CONTROLS_NOT_OPERATING",
                           "Every site control on the approved plan must be "
                           "OPERATING.")
    if actor_id() == plan.get("approved_by_user_id"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The reviewer who approved the remedy may not issue "
                       "closure.")
    if letter["requested_scope"] == "UNRESTRICTED":
        for goal in derive.goals_of_site(letter["site_id"]):
            if goal["basis"] != "UNRESTRICTED":
                raise ApiError("ERR_UNRESTRICTED_SCOPE_NOT_SUPPORTED",
                               "Cleanup goal %s relies on a credited control."
                               % goal["id"])

    letter["status"] = "ISSUED"
    letter["issued_on"] = db.today_str()
    letter["issued_by_user_id"] = actor_id()
    letter["controls_certified_count"] = len(
        [c for c in derive.controls_of_site(letter["site_id"])
         if c["status"] == "OPERATING"])
    if reissue:
        letter["reissue_count"] = int(letter["reissue_count"]) + 1
        letter["revocation_reason"] = None
    db.touch(letter)

    if not reissue and enrollment is not None:
        enrollment["status"] = "CLOSED"
        db.touch(enrollment)
    return response.object_response(dump_letter(letter))


@bp.post("/nfa-letters/<letter_id>/lender-acceptance")
@endpoint(["Lender"])
def lender_acceptance(letter_id):
    body = V.json_body()
    lender_reference = V.string_field(body, "lender_reference", True, 1, 64)

    letter = fetch("nfa_letters", letter_id)
    site = db.get("sites", letter["site_id"])
    if site is not None:
        derive.assert_not_frozen(site)
        derive.assert_posture_open(site)
    if letter["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_LETTER_STATE",
                       "Only an ISSUED letter may be accepted by a lender.")
    protection = derive.protection_for_site(letter["site_id"])
    if protection is None or protection["bfpp_status"] != "ESTABLISHED":
        raise ApiError("ERR_LETTER_NOT_CURABLE",
                       "The parcel's purchaser defence is not ESTABLISHED.")

    letter["status"] = "ACCEPTED_BY_LENDER"
    letter["accepted_by_lender_user_id"] = actor_id()
    letter["lender_reference"] = lender_reference
    db.touch(letter)
    return response.object_response(dump_letter(letter))
