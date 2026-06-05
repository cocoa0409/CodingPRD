"""E-Verify case endpoints: submit, list, get, result, refer."""

from flask import Blueprint, request

from errors import err
from db import db, stamp_create, touch
from middleware import require_roles, require_read_role, parse_pagination
from response import object_response
from listing import sorted_collection, paginate_and_respond
from validation import get_json_body, require_str, require_enum, optional_str
from clock import now, format_iso8601, parse_iso8601, add_gov_business_days
import serializers
from services import audit, lifecycle

bp = Blueprint("everify_cases", __name__)

NON_TERMINAL = lambda s: s not in ("EMPLOYMENT_AUTHORIZED", "FINAL_NONCONFIRMATION")
RESULT_DOMAIN = {"AUTHORIZED", "TNC", "NO_ACTION", "FINAL_NONCONFIRMATION"}
AGENCY_DOMAIN = {"SSA", "DHS"}


def _get_case_or_404(case_id):
    case = db.everify_cases.get(case_id)
    if case is None:
        raise err("ERR_NOT_FOUND", "EVerifyCase not found")
    return case


# ---------------------------------------------------------------------------
# POST /everify-cases
# ---------------------------------------------------------------------------
@bp.route("/everify-cases", methods=["POST"])
def submit_case():
    user_id, role = require_roles({"EVerifyOperator"})
    body = get_json_body()

    onboarding_id = require_str(body, "onboarding_id")
    i9_form_id = require_str(body, "i9_form_id")

    # priority 4: existence, left-to-right (onboarding, then i9-form).
    onboarding = db.onboardings.get(onboarding_id)
    if onboarding is None:
        raise err("ERR_NOT_FOUND", "Onboarding not found")
    form = db.i9_forms.get(i9_form_id)
    if form is None:
        raise err("ERR_NOT_FOUND", "I9Form not found")

    # priority 5: state guard — onboarding in {SECTION2_COMPLETE, EVERIFY_PENDING}
    # (EVERIFY_PENDING admitted only so the duplicate guard rejects a 2nd create).
    if onboarding.get("status") not in ("SECTION2_COMPLETE", "EVERIFY_PENDING"):
        raise err("ERR_INVALID_STATE",
                  "E-Verify submission requires SECTION2_COMPLETE")

    # priority 6: no non-terminal case already exists for this onboarding.
    for c in db.everify_cases.values():
        if c.get("onboarding_id") == onboarding_id and NON_TERMINAL(c.get("status")):
            raise err("ERR_EVERIFY_CASE_EXISTS",
                      "A non-terminal E-Verify case already exists")

    # Compute lateness against everify_deadline (= onboarding.section2_deadline).
    clock = now()
    everify_deadline_iso = onboarding.get("section2_deadline")
    was_late = parse_iso8601(everify_deadline_iso) < clock  # submitted_at > deadline
    late_reason = optional_str(body, "late_reason", None)

    # priority 13: a late submission must carry a non-empty late_reason.
    if was_late and (late_reason is None or late_reason.strip() == ""):
        raise err("ERR_LATE_REASON_REQUIRED",
                  "Late E-Verify submission requires a non-empty late_reason")

    # priority 14: OCC.
    expected = body.get("expected_onboarding_version")
    if expected is None:
        raise err("ERR_INVALID_REQUEST",
                  "expected_onboarding_version is required")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err("ERR_INVALID_REQUEST",
                  "expected_onboarding_version must be an integer")
    if expected != onboarding.get("version"):
        raise err("ERR_STALE_ONBOARDING_VERSION",
                  "expected_onboarding_version does not match current version")

    # --- mint the case in SUBMITTED ---
    case = {
        "onboarding_id": onboarding_id,
        "i9_form_id": i9_form_id,
        "submitted_at": format_iso8601(clock),
        "everify_deadline": everify_deadline_iso,
        "was_late": was_late,
        "late_reason": late_reason,
        "tnc_type": "NONE",
        "tnc_issued_at": None,
        "referral_deadline": None,
        "status": "SUBMITTED",
    }
    stamp_create(case)
    db.everify_cases[case["id"]] = case

    # cascade: onboarding SECTION2_COMPLETE -> EVERIFY_PENDING, version++.
    onboarding["status"] = "EVERIFY_PENDING"
    touch(onboarding)
    audit.append(onboarding_id, role, user_id, "EVERIFY_SUBMITTED",
                 "E-Verify case submitted")

    return object_response(serializers.everify_case(case), status=201)


# ---------------------------------------------------------------------------
# GET /everify-cases
# ---------------------------------------------------------------------------
@bp.route("/everify-cases", methods=["GET"])
def list_cases():
    require_read_role()
    limit, offset = parse_pagination()
    records = sorted_collection(db.everify_cases)
    onboarding_id = request.args.get("onboarding_id")
    i9_form_id = request.args.get("i9_form_id")
    status = request.args.get("status")
    if onboarding_id is not None:
        records = [r for r in records if r.get("onboarding_id") == onboarding_id]
    if i9_form_id is not None:
        records = [r for r in records if r.get("i9_form_id") == i9_form_id]
    if status is not None:
        records = [r for r in records if r.get("status") == status]
    return paginate_and_respond(records, limit, offset, serializers.everify_case)


# ---------------------------------------------------------------------------
# GET /everify-cases/{id}
# ---------------------------------------------------------------------------
@bp.route("/everify-cases/<case_id>", methods=["GET"])
def get_case(case_id):
    require_read_role()
    case = _get_case_or_404(case_id)
    return object_response(serializers.everify_case(case))


# ---------------------------------------------------------------------------
# POST /everify-cases/{id}/result
# ---------------------------------------------------------------------------
@bp.route("/everify-cases/<case_id>/result", methods=["POST"])
def record_result(case_id):
    user_id, role = require_roles({"EVerifyOperator"})
    case = _get_case_or_404(case_id)
    body = get_json_body()

    result = require_enum(body, "result", RESULT_DOMAIN)
    onboarding = db.onboardings.get(case.get("onboarding_id"))

    status = case.get("status")
    clock = now()

    if result == "AUTHORIZED":
        # Defined from SUBMITTED or REFERRED.
        if status == "SUBMITTED":
            case["status"] = "EMPLOYMENT_AUTHORIZED"
            touch(case)
            _cascade_authorized(onboarding, role, user_id, "AUTHORIZED")
        elif status == "REFERRED":
            case["status"] = "EMPLOYMENT_AUTHORIZED"
            touch(case)
            _cascade_authorized(onboarding, role, user_id, "AUTHORIZED_AFTER_REFERRAL")
        else:
            raise err("ERR_INVALID_STATE",
                      "AUTHORIZED result not defined from %s" % status)

    elif result == "TNC":
        # Defined only from SUBMITTED.
        agency = require_enum(body, "agency", AGENCY_DOMAIN)
        if status != "SUBMITTED":
            raise err("ERR_INVALID_STATE",
                      "TNC result not defined from %s" % status)
        case["status"] = "TNC_ISSUED"
        case["tnc_type"] = "SSA_TNC" if agency == "SSA" else "DHS_TNC"
        case["tnc_issued_at"] = format_iso8601(clock)
        case["referral_deadline"] = format_iso8601(
            add_gov_business_days(clock, 10))
        touch(case)
        audit.append(case.get("onboarding_id"), role, user_id, "TNC_ISSUED",
                     "Tentative Nonconfirmation issued by %s" % agency)
        # Onboarding stays EVERIFY_PENDING during TNC handling.

    elif result == "NO_ACTION":
        # From TNC_ISSUED -> FINAL_NONCONFIRMATION (explicit no-action close).
        if status != "TNC_ISSUED":
            raise err("ERR_INVALID_STATE",
                      "NO_ACTION result not defined from %s" % status)
        case["status"] = "FINAL_NONCONFIRMATION"
        touch(case)
        _cascade_terminated(onboarding, role, user_id)

    elif result == "FINAL_NONCONFIRMATION":
        # Defined from REFERRED.
        if status != "REFERRED":
            raise err("ERR_INVALID_STATE",
                      "FINAL_NONCONFIRMATION result not defined from %s" % status)
        case["status"] = "FINAL_NONCONFIRMATION"
        touch(case)
        _cascade_terminated(onboarding, role, user_id)

    return object_response(serializers.everify_case(case))


# ---------------------------------------------------------------------------
# POST /everify-cases/{id}/refer
# ---------------------------------------------------------------------------
@bp.route("/everify-cases/<case_id>/refer", methods=["POST"])
def refer_case(case_id):
    user_id, role = require_roles({"EVerifyOperator"})
    case = _get_case_or_404(case_id)

    # priority 5: state guard — only from TNC_ISSUED.
    if case.get("status") != "TNC_ISSUED":
        raise err("ERR_INVALID_STATE", "Refer not defined from %s" % case.get("status"))

    # priority 12: referral must be on or before referral_deadline (clock <= deadline).
    clock = now()
    deadline_iso = case.get("referral_deadline")
    if deadline_iso is not None and clock > parse_iso8601(deadline_iso):
        raise err("ERR_REFERRAL_WINDOW_CLOSED",
                  "TNC referral attempted after referral_deadline")

    case["status"] = "REFERRED"
    touch(case)
    audit.append(case.get("onboarding_id"), role, user_id, "TNC_REFERRED",
                 "Employee referral/contest of TNC recorded")
    return object_response(serializers.everify_case(case))


# ---------------------------------------------------------------------------
# cascade helpers
# ---------------------------------------------------------------------------
def _cascade_authorized(onboarding, role, user_id, action):
    if onboarding is not None and onboarding.get("status") == "EVERIFY_PENDING":
        onboarding["status"] = "AUTHORIZED"
        touch(onboarding)
        audit.append(onboarding["id"], role, user_id, action,
                     "E-Verify employment authorized")


def _cascade_terminated(onboarding, role, user_id):
    if onboarding is not None and onboarding.get("status") == "EVERIFY_PENDING":
        onboarding["status"] = "TERMINATED_NONCONFIRMED"
        touch(onboarding)
    audit.append(onboarding["id"] if onboarding else None, role, user_id,
                 "FINAL_NONCONFIRMATION", "E-Verify final nonconfirmation")
