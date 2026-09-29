"""Lead-agency solicitations: posting, evaluation, award and the audit file (PRD 3.2)."""

from decimal import Decimal

from flask import Blueprint

import services
from calc import num
from db import create_row, db, get_dt, logical_now, ordered, serialize, set_dt
from errors import fail
from middleware import (ROLE_AUDITOR, ROLE_COOP_ADMIN, ROLE_LEAD_AGENCY,
                        ROLE_MEMBER, ROLE_SUPPLIER, actor_id, commit,
                        require_roles, touch)
from response import created_response, object_response
from routes.common import (AUDIT_PACKAGE_STATUS, RESPONSE_STATUS,
                           SOLICITATION_STATUS, fetch, list_endpoint,
                           render_list)
from validation import (json_body, pagination, query_args, read_dec, read_dt,
                        read_state_code, read_str)

bp = Blueprint("solicitations", __name__)

READ_ROLES = (ROLE_COOP_ADMIN, ROLE_LEAD_AGENCY, ROLE_SUPPLIER, ROLE_MEMBER,
              ROLE_AUDITOR)

CREATE_FIELDS = ("title", "solicitation_number", "lead_agency_name",
                 "lead_agency_state_code", "response_due_at",
                 "technical_weight_pct", "price_weight_pct",
                 "specification_document_ref", "method_justification_ref")

LIFECYCLE_ACTIONS = ("POST_NOTICE", "OPEN_EVALUATION", "RECOMMEND_AWARD",
                     "AWARD", "FAIL", "CANCEL")
AUDIT_ACTIONS = ("ASSEMBLE", "CERTIFY")

LIVE_RESPONSE_FOR_CANCEL = ("SUBMITTED", "INFO_REQUESTED")


@bp.route("/coop/solicitations", methods=["POST"])
@require_roles(ROLE_LEAD_AGENCY)
def create_solicitation():
    body = json_body(
        allowed=CREATE_FIELDS,
        required=("title", "solicitation_number", "lead_agency_name",
                  "lead_agency_state_code", "response_due_at",
                  "technical_weight_pct", "price_weight_pct"),
    )
    title = read_str(body, "title", required=True, min_len=1, max_len=200)
    number = read_str(body, "solicitation_number", required=True, min_len=1,
                      max_len=40)
    agency_name = read_str(body, "lead_agency_name", required=True, min_len=1,
                           max_len=200)
    state_code = read_state_code(body, "lead_agency_state_code", required=True)
    due_raw, _ = read_dt(body, "response_due_at", required=True)
    technical = read_dec(body, "technical_weight_pct", required=True,
                         minimum="0", maximum="100")
    price = read_dec(body, "price_weight_pct", required=True,
                     minimum="0", maximum="100")
    if technical + price != Decimal("100"):
        from validation import bad
        bad("technical_weight_pct and price_weight_pct must sum to exactly 100")
    spec_ref = read_str(body, "specification_document_ref")
    method_ref = read_str(body, "method_justification_ref")

    for existing in db.solicitations.values():
        if existing["solicitation_number"] == number:
            fail("ERR_DUPLICATE_SOLICITATION_NUMBER",
                 "solicitation_number %s is already in use" % number)

    row = create_row(
        db.solicitations,
        title=title,
        solicitation_number=number,
        lead_agency_name=agency_name,
        lead_agency_state_code=state_code,
        status="DRAFT",
        audit_package_status="NOT_ASSEMBLED",
        response_due_at=None,
        posted_at=None,
        notice_days=None,
        technical_weight_pct=num(technical),
        price_weight_pct=num(price),
        specification_document_ref=spec_ref,
        method_justification_ref=method_ref,
        amendment_log_document_ref=None,
        addenda_count=0,
        responsive_response_count=0,
        audit_required_doc_codes=[],
        audit_present_doc_codes=[],
        audit_completeness_pct=None,
        recommended_by_user_id=None,
        awarded_by_user_id=None,
        certified_by_user_id=None,
        certified_at=None,
    )
    set_dt(row, "response_due_at", due_raw)
    set_dt(row, "posted_at", None)
    set_dt(row, "certified_at", None)
    return created_response(serialize(row))


@bp.route("/coop/solicitations", methods=["GET"])
@require_roles(*READ_ROLES)
def list_solicitations():
    return list_endpoint(
        lambda: ordered(db.solicitations),
        {"lead_agency_state_code": ("lead_agency_state_code", None),
         "status": ("status", SOLICITATION_STATUS),
         "audit_package_status": ("audit_package_status", AUDIT_PACKAGE_STATUS)},
    )


@bp.route("/coop/solicitations/<solicitation_id>", methods=["GET"])
@require_roles(*READ_ROLES)
def read_solicitation(solicitation_id):
    row = fetch(db.solicitations, solicitation_id, "ERR_SOLICITATION_NOT_FOUND")
    return object_response(serialize(row))


@bp.route("/coop/solicitations/<solicitation_id>/responses", methods=["GET"])
@require_roles(ROLE_COOP_ADMIN, ROLE_LEAD_AGENCY, ROLE_AUDITOR)
def list_solicitation_responses(solicitation_id):
    filters = {"status": ("status", RESPONSE_STATUS)}
    args = query_args(filters.keys())
    pagination()
    fetch(db.solicitations, solicitation_id, "ERR_SOLICITATION_NOT_FOUND")
    rows = services.responses_of_solicitation(solicitation_id)
    return render_list(rows, args, filters)


# =========================================================================
# competitive lifecycle
# =========================================================================

@bp.route("/coop/solicitations/<solicitation_id>/lifecycle", methods=["POST"])
@require_roles(ROLE_LEAD_AGENCY)
def lifecycle(solicitation_id):
    body = json_body(allowed=("action", "note"), required=("action",))
    action = read_str(body, "action", required=True, enum=LIFECYCLE_ACTIONS)
    read_str(body, "note")

    solicitation = fetch(db.solicitations, solicitation_id,
                         "ERR_SOLICITATION_NOT_FOUND")
    now = logical_now()

    # 6. the state law configuration row a posting must resolve
    if action == "POST_NOTICE":
        if services.rule_for_state(solicitation["lead_agency_state_code"]) is None:
            fail("ERR_STATE_LAW_RULE_NOT_FOUND",
                 "no configuration row for state_code %s"
                 % solicitation["lead_agency_state_code"])

    # 8. segregation of duties
    if action == "AWARD":
        recommender = solicitation["recommended_by_user_id"]
        if recommender is not None and actor_id() == recommender:
            fail("ERR_SEGREGATION_OF_DUTIES",
                 "the recommending officer may not sign the award")

    # 13. from-state
    status = solicitation["status"]
    expected = {
        "POST_NOTICE": ("DRAFT",),
        "OPEN_EVALUATION": ("POSTED",),
        "RECOMMEND_AWARD": ("EVALUATION",),
        "AWARD": ("AWARD_PENDING",),
        "FAIL": ("EVALUATION",),
        "CANCEL": ("DRAFT", "POSTED", "EVALUATION"),
    }[action]
    if status not in expected:
        fail("ERR_SOLICITATION_INVALID_STATE",
             "%s is not a declared transition out of %s" % (action, status))
    if action == "FAIL" and int(solicitation["responsive_response_count"]) >= 2:
        fail("ERR_SOLICITATION_INVALID_STATE",
             "FAIL is only available while the responsive count is below two")
    if action == "CANCEL" and services.contracts_of_solicitation(solicitation_id):
        fail("ERR_SOLICITATION_INVALID_STATE",
             "a master contract already references this solicitation")

    # 25. the rank-1 supplier must still be QUALIFIED to sign
    if action == "AWARD":
        winner = services.rank_one_response(solicitation_id)
        if winner is not None:
            supplier = db.suppliers.get(winner["supplier_id"])
            if supplier is None or supplier["qualification_status"] != "QUALIFIED":
                fail("ERR_SUPPLIER_NOT_QUALIFIED",
                     "the rank-1 supplier is no longer QUALIFIED")

    if action == "POST_NOTICE":
        due = get_dt(solicitation, "response_due_at")
        if not due > now:
            fail("ERR_RESPONSE_DUE_IN_PAST",
                 "response_due_at must be strictly after the logical clock")
        solicitation["status"] = "POSTED"
        set_dt(solicitation, "posted_at", now)
        elapsed = (due - now).total_seconds()
        solicitation["notice_days"] = int(elapsed // 86400)
        solicitation["addenda_count"] = 0

    elif action == "OPEN_EVALUATION":
        due = get_dt(solicitation, "response_due_at")
        if now < due:
            fail("ERR_RESPONSE_WINDOW_OPEN",
                 "the response window has not closed yet")
        solicitation["status"] = "EVALUATION"

    elif action == "RECOMMEND_AWARD":
        responsive = [r for r in services.responses_of_solicitation(solicitation_id)
                      if r["status"] == "RESPONSIVE"]
        if len(responsive) < 2:
            fail("ERR_INSUFFICIENT_RESPONSIVE_RESPONSES",
                 "at least two responsive responses are required")
        if any(r["technical_score"] is None for r in responsive):
            fail("ERR_TECHNICAL_SCORE_MISSING",
                 "every responsive response must carry a technical_score")
        services.score_solicitation(solicitation)
        solicitation["status"] = "AWARD_PENDING"
        solicitation["recommended_by_user_id"] = actor_id()

    elif action == "AWARD":
        solicitation["status"] = "AWARDED"
        solicitation["awarded_by_user_id"] = actor_id()

    elif action == "FAIL":
        for response in services.responses_of_solicitation(solicitation_id):
            if response["status"] in LIVE_RESPONSE_FOR_CANCEL:
                response["status"] = "NON_RESPONSIVE"
                touch(response)
        solicitation["status"] = "FAILED"

    else:  # CANCEL
        if status in ("POSTED", "EVALUATION"):
            for response in services.responses_of_solicitation(solicitation_id):
                if response["status"] in LIVE_RESPONSE_FOR_CANCEL:
                    response["status"] = "WITHDRAWN"
                    touch(response)
        solicitation["status"] = "CANCELLED"

    touch(solicitation)
    services.mark_audit_stale(solicitation)
    commit()
    return object_response(serialize(solicitation))


# =========================================================================
# documentation package
# =========================================================================

@bp.route("/coop/solicitations/<solicitation_id>/audit-package", methods=["POST"])
@require_roles(ROLE_LEAD_AGENCY)
def audit_package(solicitation_id):
    body = json_body(allowed=("action", "amendment_log_document_ref"),
                     required=("action",))
    action = read_str(body, "action", required=True, enum=AUDIT_ACTIONS)
    log_ref = read_str(body, "amendment_log_document_ref")

    solicitation = fetch(db.solicitations, solicitation_id,
                         "ERR_SOLICITATION_NOT_FOUND")
    package = solicitation["audit_package_status"]

    # 13. from-state on the documentation dimension
    if action == "ASSEMBLE":
        if package not in ("NOT_ASSEMBLED", "ASSEMBLED", "STALE"):
            fail("ERR_SOLICITATION_INVALID_STATE",
                 "ASSEMBLE is not a declared transition out of %s" % package)
        if solicitation["posted_at"] is None:
            fail("ERR_SOLICITATION_INVALID_STATE",
                 "the solicitation has not been posted yet")
    else:  # CERTIFY
        if package in ("NOT_ASSEMBLED", "STALE"):
            fail("ERR_AUDIT_PACKAGE_NOT_ASSEMBLED",
                 "the package must be assembled before certification")
        if package != "ASSEMBLED":
            fail("ERR_SOLICITATION_INVALID_STATE",
                 "CERTIFY is not a declared transition out of %s" % package)
        if solicitation["status"] not in ("AWARDED", "FAILED"):
            fail("ERR_SOLICITATION_INVALID_STATE",
                 "the competitive dimension must have reached AWARDED or FAILED")
        # 33. full completeness
        if solicitation["audit_completeness_pct"] != 100.0:
            fail("ERR_AUDIT_PACKAGE_INCOMPLETE",
                 "audit_completeness_pct must be exactly 100.00")

    if action == "ASSEMBLE":
        if log_ref is not None:
            solicitation["amendment_log_document_ref"] = log_ref
        services.assemble_audit_package(solicitation)
        solicitation["audit_package_status"] = "ASSEMBLED"
    else:
        if log_ref is not None:
            solicitation["amendment_log_document_ref"] = log_ref
        solicitation["audit_package_status"] = "CERTIFIED"
        set_dt(solicitation, "certified_at", logical_now())
        solicitation["certified_by_user_id"] = actor_id()

    touch(solicitation)
    commit()
    return object_response(serialize(solicitation))
