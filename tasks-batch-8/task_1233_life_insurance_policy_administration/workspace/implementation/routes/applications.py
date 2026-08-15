"""PolicyApplication endpoints and the underwriting workflow (PRD §3.2, §3.3)."""
from flask import Blueprint, request

import domain
import errors
from db import store
from middleware import require_auth, parse_pagination, json_body, require_int
from response import ok_object, ok_list
from services import calculations as calc
from services import engine

bp = Blueprint("applications", __name__)

APP_READ_ROLES = ["Agent", "Underwriter", "PolicyIssuer", "PlatformAdmin"]


def _get_application(app_id):
    app = store.applications.get(app_id)
    if app is None:
        raise errors.not_found(errors.ERR_APPLICATION_NOT_FOUND, "application")
    return app


@bp.route("/applications", methods=["POST"])
def create_application():
    require_auth(["Agent"])
    body = json_body(required=True)
    # Body references: existence (priority 3)
    insured_id = body.get("insured_person_id")
    template_id = body.get("product_template_id")
    if not isinstance(insured_id, str) or not insured_id:
        raise errors.invalid_request("insured_person_id is required")
    if not isinstance(template_id, str) or not template_id:
        raise errors.invalid_request("product_template_id is required")
    if insured_id not in store.insured_persons:
        raise errors.not_found(errors.ERR_INSURED_NOT_FOUND, "insured person")
    template = store.product_templates.get(template_id)
    if template is None:
        raise errors.not_found(errors.ERR_TEMPLATE_NOT_FOUND, "product template")
    # Field constraints (priority 8)
    face = require_int(body, "requested_face_amount_cents", minimum=0)
    if face < template["min_face_amount_cents"] or face > template["max_face_amount_cents"]:
        raise errors.invalid_request(
            "requested_face_amount_cents outside template min/max")
    mode = body.get("premium_mode")
    if mode not in domain.PREMIUM_MODES:
        raise errors.invalid_request("premium_mode must be MONTHLY | QUARTERLY | SEMI_ANNUAL | ANNUAL")
    app = domain.stamp_new({
        "insured_person_id": insured_id,
        "product_template_id": template_id,
        "requested_face_amount_cents": face,
        "premium_mode": mode,
        "underwriting_class": None,
        "substandard_extra_pct_bps": None,
        "status": "SUBMITTED",
    })
    store.applications[app["id"]] = app
    return ok_object(domain.serialize_application(app), status=201)


@bp.route("/applications", methods=["GET"])
def list_applications():
    require_auth(APP_READ_ROLES)
    records = list(store.applications.values())
    insured_id = request.args.get("insured_person_id")
    template_id = request.args.get("product_template_id")
    if insured_id is not None:
        records = [a for a in records if a["insured_person_id"] == insured_id]
    if template_id is not None:
        records = [a for a in records if a["product_template_id"] == template_id]
    limit, offset = parse_pagination()
    ordered = domain.sorted_by_creation(records)
    return ok_list([domain.serialize_application(a) for a in ordered[offset:offset + limit]],
                   limit, offset, len(ordered))


@bp.route("/applications/<app_id>", methods=["GET"])
def get_application(app_id):
    require_auth(APP_READ_ROLES)
    return ok_object(domain.serialize_application(_get_application(app_id)))


def _transition(app_id, from_states, to_state, terminal_states=domain.APP_TERMINAL):
    app = _get_application(app_id)
    if app["status"] in terminal_states:
        raise errors.already_terminal("Application is in a terminal state")
    if app["status"] not in from_states:
        raise errors.invalid_state(
            "Application in status %s cannot move to %s" % (app["status"], to_state))
    app["status"] = to_state
    domain.touch(app)
    return app


@bp.route("/applications/<app_id>/begin-review", methods=["POST"])
def begin_review(app_id):
    require_auth(["Underwriter"])
    app = _transition(app_id, {"SUBMITTED"}, "UNDER_REVIEW")
    return ok_object(domain.serialize_application(app))


@bp.route("/applications/<app_id>/request-evidence", methods=["POST"])
def request_evidence(app_id):
    require_auth(["Underwriter"])
    app = _transition(app_id, {"UNDER_REVIEW"}, "EVIDENCE_REQUIRED")
    return ok_object(domain.serialize_application(app))


@bp.route("/applications/<app_id>/submit-evidence", methods=["POST"])
def submit_evidence(app_id):
    require_auth(["Agent"])
    app = _transition(app_id, {"EVIDENCE_REQUIRED"}, "UNDER_REVIEW")
    return ok_object(domain.serialize_application(app))


@bp.route("/applications/<app_id>/approve", methods=["POST"])
def approve(app_id):
    ctx = require_auth(["Underwriter"])
    app = _get_application(app_id)
    if app["status"] in domain.APP_TERMINAL:
        raise errors.already_terminal("Application is in a terminal state")
    if app["status"] != "UNDER_REVIEW":
        raise errors.invalid_state("Application must be UNDER_REVIEW to approve")
    body = json_body(required=True)
    uw_class = body.get("underwriting_class")
    if uw_class not in domain.UNDERWRITING_CLASSES:
        raise errors.invalid_request("invalid underwriting_class")
    insured = store.insured_persons[app["insured_person_id"]]
    if uw_class in domain.NON_TOBACCO_CLASSES and insured["tobacco_user"]:
        raise errors.class_tobacco_mismatch()
    if uw_class in domain.TOBACCO_CLASSES and not insured["tobacco_user"]:
        raise errors.class_tobacco_mismatch()
    app["underwriting_class"] = uw_class
    app["substandard_extra_pct_bps"] = domain.SUBSTANDARD_EXTRA_BPS.get(uw_class, 0)
    app["status"] = "APPROVED"
    app["_approved_by"] = ctx.user_id
    domain.touch(app)
    return ok_object(domain.serialize_application(app))


@bp.route("/applications/<app_id>/decline", methods=["POST"])
def decline(app_id):
    require_auth(["Underwriter"])
    app = _transition(app_id, {"UNDER_REVIEW"}, "DECLINED")
    return ok_object(domain.serialize_application(app))


@bp.route("/applications/<app_id>/issue", methods=["POST"])
def issue(app_id):
    ctx = require_auth(["PolicyIssuer"])
    app = _get_application(app_id)
    if app["status"] in domain.APP_TERMINAL:
        raise errors.already_terminal("Application is in a terminal state")
    if app["status"] != "APPROVED":
        raise errors.invalid_state("Application must be APPROVED to issue")
    # Segregation of duties: issuer != approving underwriter (priority 5)
    if app.get("_approved_by") is not None and app["_approved_by"] == ctx.user_id:
        raise errors.segregation(
            "Issuing PolicyIssuer must differ from the approving underwriter")

    template = store.product_templates[app["product_template_id"]]
    insured = store.insured_persons[app["insured_person_id"]]
    today = store.current_date()

    uw_class = app["underwriting_class"]
    extra_bps = app["substandard_extra_pct_bps"] or 0
    modal = calc.modal_premium(app["requested_face_amount_cents"],
                               template["base_monthly_premium_rate_per_thousand_cents"],
                               uw_class, extra_bps, app["premium_mode"])
    from util import age_years
    policy = domain.stamp_new({
        "application_id": app["id"],
        "insured_person_id": app["insured_person_id"],
        "product_template_id": app["product_template_id"],
        "policy_number": store.next_policy_number(),
        "issue_date": today,
        "face_amount_cents": app["requested_face_amount_cents"],
        "premium_mode": app["premium_mode"],
        "modal_premium_cents": modal,
        "underwriting_class": uw_class,
        "premium_payment_status": "CURRENT",
        "form_status": "IN_FORCE",
        "grace_period_end_date": None,
        "cash_value_cents": 0,
        "outstanding_loan_principal_cents": 0,
        "accrued_loan_interest_cents": 0,
        "dividend_accumulation_cents": 0,
        "dividend_option": "CASH",
        "paid_to_date": None,
        "attained_age_at_issue": age_years(insured["date_of_birth"], today),
        "_substandard_extra_pct_bps": extra_bps,
        "_lapsed_date": None,
    })
    store.policies[policy["id"]] = policy

    # First cycle: first modal premium received at issuance -> PAID
    cycle = engine.create_cycle(policy, 1, today)
    cycle["paid_amount_cents"] = cycle["due_amount_cents"]
    cycle["status"] = "PAID"
    domain.touch(cycle)
    policy["paid_to_date"] = cycle["period_end_date"]

    # Initial PREMIUM_CREDIT for the first modal premium
    builds = domain.policy_builds_cash_value(policy)
    engine.post_ledger(policy, domain.ENTRY_PREMIUM_CREDIT, modal,
                       change_cents=(modal if builds else 0))

    app["status"] = "ISSUED"
    domain.touch(app)
    return ok_object(domain.serialize_policy(policy), status=201)
