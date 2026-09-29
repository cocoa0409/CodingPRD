"""Member agency registration and eligibility verification (PRD 3.4)."""

from flask import Blueprint

import services
from db import (create_row, db, logical_now, ordered, serialize, set_dt)
from errors import fail
from middleware import (ROLE_AUDITOR, ROLE_COOP_ADMIN, ROLE_LEAD_AGENCY,
                        ROLE_MEMBER, actor_id, commit, require_roles, touch)
from response import created_response, object_response
from routes.common import (ANALYSIS_STATUS, DETERMINATION, MEMBER_CATEGORY,
                           REGISTRATION_STATUS, fetch, list_endpoint,
                           render_list)
from validation import (json_body, pagination, query_args, read_int, read_state_code,
                        read_str)

bp = Blueprint("member_agencies", __name__)

LIST_ROLES = (ROLE_COOP_ADMIN, ROLE_LEAD_AGENCY, ROLE_AUDITOR)
READ_ROLES = (ROLE_COOP_ADMIN, ROLE_LEAD_AGENCY, ROLE_MEMBER, ROLE_AUDITOR)

REGISTRATION_ACTIONS = ("REQUEST_DOCS", "RESUBMIT_DOCS", "VERIFY", "SUSPEND",
                        "REINSTATE", "TERMINATE")
MAX_DOCS_REQUEST_ROUNDS = 3


@bp.route("/coop/member-agencies", methods=["POST"])
@require_roles(ROLE_COOP_ADMIN)
def create_member():
    body = json_body(
        allowed=("legal_name", "state_code", "member_category",
                 "annual_spend_ceiling_cents", "governing_body_resolution_number",
                 "irs_determination_letter_number"),
        required=("legal_name", "state_code", "member_category",
                  "annual_spend_ceiling_cents"),
    )
    legal_name = read_str(body, "legal_name", required=True, min_len=1, max_len=200)
    state_code = read_state_code(body, "state_code", required=True)
    category = read_str(body, "member_category", required=True,
                        enum=MEMBER_CATEGORY)
    ceiling = read_int(body, "annual_spend_ceiling_cents", required=True, minimum=1)
    resolution = read_str(body, "governing_body_resolution_number", max_len=80)
    letter = read_str(body, "irs_determination_letter_number", max_len=80)

    # 57. global natural-key uniqueness
    for existing in db.members.values():
        if existing["legal_name"] == legal_name:
            fail("ERR_DUPLICATE_MEMBER_NAME",
                 "legal_name %s is already registered" % legal_name)

    row = create_row(
        db.members,
        legal_name=legal_name,
        state_code=state_code,
        member_category=category,
        annual_spend_ceiling_cents=ceiling,
        registration_status="PENDING_VERIFICATION",
        committed_spend_cents=0,
        governing_body_resolution_number=resolution,
        irs_determination_letter_number=letter,
        docs_request_count=0,
        verified_at=None,
        verified_by_user_id=None,
    )
    set_dt(row, "verified_at", None)
    return created_response(serialize(row))


@bp.route("/coop/member-agencies", methods=["GET"])
@require_roles(*LIST_ROLES)
def list_members():
    return list_endpoint(
        lambda: ordered(db.members),
        {"state_code": ("state_code", None),
         "member_category": ("member_category", MEMBER_CATEGORY),
         "registration_status": ("registration_status", REGISTRATION_STATUS)},
    )


@bp.route("/coop/member-agencies/<member_id>", methods=["GET"])
@require_roles(*READ_ROLES)
def read_member(member_id):
    row = fetch(db.members, member_id, "ERR_MEMBER_NOT_FOUND")
    return object_response(serialize(row))


@bp.route("/coop/member-agencies/<member_id>/piggyback-analyses", methods=["GET"])
@require_roles(*READ_ROLES)
def list_member_analyses(member_id):
    filters = {"status": ("status", ANALYSIS_STATUS),
               "determination": ("determination", DETERMINATION)}
    args = query_args(filters.keys())
    pagination()
    fetch(db.members, member_id, "ERR_MEMBER_NOT_FOUND")
    return render_list(services.analyses_of_member(member_id), args, filters)


@bp.route("/coop/member-agencies/<member_id>/registration", methods=["POST"])
@require_roles(ROLE_COOP_ADMIN)
def registration(member_id):
    body = json_body(
        allowed=("action", "governing_body_resolution_number",
                 "irs_determination_letter_number", "note"),
        required=("action",),
    )
    action = read_str(body, "action", required=True, enum=REGISTRATION_ACTIONS)
    resolution = read_str(body, "governing_body_resolution_number", max_len=80)
    letter = read_str(body, "irs_determination_letter_number", max_len=80)
    read_str(body, "note")

    member = fetch(db.members, member_id, "ERR_MEMBER_NOT_FOUND")

    # 6. verification resolves the member state's configuration row
    rule = None
    if action == "VERIFY":
        rule = services.rule_for_state(member["state_code"])
        if rule is None:
            fail("ERR_STATE_LAW_RULE_NOT_FOUND",
                 "no configuration row for state_code %s" % member["state_code"])

    # 18. from-state on the registration dimension
    status = member["registration_status"]
    expected = {
        "REQUEST_DOCS": ("PENDING_VERIFICATION",),
        "RESUBMIT_DOCS": ("DOCS_REQUESTED",),
        "VERIFY": ("PENDING_VERIFICATION",),
        "SUSPEND": ("ACTIVE",),
        "REINSTATE": ("SUSPENDED",),
        "TERMINATE": ("PENDING_VERIFICATION", "DOCS_REQUESTED", "ACTIVE",
                      "SUSPENDED"),
    }[action]
    if status not in expected:
        fail("ERR_MEMBER_INVALID_STATE",
             "%s is not a declared transition out of %s" % (action, status))

    # Evidence numbers may be supplied at registration or later.
    supplied = False
    if resolution is not None:
        member["governing_body_resolution_number"] = resolution
        supplied = True
    if letter is not None:
        member["irs_determination_letter_number"] = letter
        supplied = True

    if action == "VERIFY":
        # 27. evidence matching the asserted category
        if member["member_category"] == "NONPROFIT_501C3":
            if member["irs_determination_letter_number"] is None:
                fail("ERR_NONPROFIT_EVIDENCE_MISSING",
                     "an IRS determination letter number is required")
        elif member["governing_body_resolution_number"] is None:
            fail("ERR_GOVERNING_RESOLUTION_MISSING",
                 "a governing body resolution number is required")
        # 28. the state must permit nonprofit participation
        if member["member_category"] == "NONPROFIT_501C3" and not rule[
                "allows_nonprofit_participation"]:
            fail("ERR_NONPROFIT_NOT_PERMITTED",
                 "state %s does not permit nonprofit participation"
                 % member["state_code"])

    # 53. bounded document-request rounds
    if action == "REQUEST_DOCS":
        if int(member["docs_request_count"]) >= MAX_DOCS_REQUEST_ROUNDS:
            fail("ERR_DOCS_REQUEST_ROUNDS_EXHAUSTED",
                 "the document-request allowance is exhausted")

    if action == "REQUEST_DOCS":
        member["registration_status"] = "DOCS_REQUESTED"
    elif action == "RESUBMIT_DOCS":
        member["registration_status"] = "PENDING_VERIFICATION"
        member["docs_request_count"] = int(member["docs_request_count"]) + 1
    elif action == "VERIFY":
        member["registration_status"] = "ACTIVE"
        set_dt(member, "verified_at", logical_now())
        member["verified_by_user_id"] = actor_id()
    elif action == "SUSPEND":
        member["registration_status"] = "SUSPENDED"
        touch(member)
        services.void_analyses(
            [a for a in services.analyses_of_member(member_id)
             if a["status"] == "DETERMINED"],
            "MEMBER_SUSPENDED",
        )
    elif action == "REINSTATE":
        member["registration_status"] = "ACTIVE"
    else:  # TERMINATE
        member["registration_status"] = "TERMINATED"
        touch(member)
        services.void_analyses(
            [a for a in services.analyses_of_member(member_id)
             if a["status"] in ("PENDING", "DETERMINED")],
            "MEMBER_TERMINATED",
        )

    del supplied
    touch(member)
    commit()
    return object_response(serialize(member))
