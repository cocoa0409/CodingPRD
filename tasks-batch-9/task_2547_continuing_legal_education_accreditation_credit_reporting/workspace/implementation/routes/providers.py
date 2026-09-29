"""Provider accreditation lifecycle (PRD 3.1)."""
from flask import Blueprint

import constants as C
import db
import middleware
import response
import util
from errors import fail
from services import cascades

bp = Blueprint("providers", __name__)

PROVIDER_TYPES = ["BAR_ASSOCIATION", "LAW_SCHOOL", "GOVERNMENT", "COMMERCIAL", "LAW_FIRM"]
PRESUMPTIVE_TYPES = ["BAR_ASSOCIATION", "LAW_SCHOOL", "GOVERNMENT"]
ACTIONS = ["GRANT_FULL", "GRANT_PROBATIONARY", "DENY", "RENEW", "SUSPEND", "REINSTATE"]


def load_provider(provider_id):
    provider = db.get("providers", provider_id)
    if provider is None:
        fail("ERR_PROVIDER_NOT_FOUND", "No provider matches that identifier.")
    return provider


@bp.route("/cle/providers", methods=["POST"])
def create_provider():
    middleware.require_roles([C.ROLE_BOARD_ADMIN])
    body = middleware.body_json()
    name = middleware.req_str(body, "name", 1, 200)
    provider_type = middleware.req_enum(body, "provider_type", PROVIDER_TYPES)
    annual_fee = middleware.opt_int(body, "annual_fee_cents", 0, None, None)
    if annual_fee is None:
        annual_fee = C.DEFAULT_PROVIDER_ANNUAL_FEE_CENTS
    provider = db.insert(
        "providers",
        {
            "name": name,
            "provider_type": provider_type,
            "annual_fee_cents": annual_fee,
            "accreditation_status": "APPLIED",
            "self_certification_enabled": False,
            "risk_score": 0.0,
            "risk_score_variant": "REVIEWED_WEIGHTING",
            "accreditation_term_start": None,
            "accreditation_term_end": None,
            "probation_reason": None,
            "courses_total_count": 0,
            "courses_self_certified_count": 0,
            "attendance_reports_total_count": 0,
            "attendance_reports_late_count": 0,
            "substantiated_complaint_count": 0,
            "audit_findings_count": 0,
            "courses_sampled_lifetime": 0,
            "last_audit_closed_at": None,
        },
    )
    return response.success(db.serialize(provider), 201)


@bp.route("/cle/providers/<provider_id>", methods=["GET"])
def read_provider(provider_id):
    middleware.require_roles(
        [C.ROLE_BOARD_ADMIN, C.ROLE_REVIEWER, C.ROLE_PANELIST, C.ROLE_PROVIDER_ADMIN]
    )
    provider = load_provider(provider_id)
    return response.success(db.serialize(provider), 200)


def _has_cleared_audit(provider):
    for audit in db.all_rows("provider_audits"):
        if audit.get("provider_id") == provider["id"] and audit.get("status") == "CLEARED":
            return True
    return False


def _start_term(provider):
    now = util.now_dt()
    cascades.set_fields(
        provider,
        {
            "accreditation_term_start": util.iso(now),
            "accreditation_term_end": util.iso(util.add_months(now, C.ACCREDITATION_TERM_MONTHS)),
        },
    )


@bp.route("/cle/providers/<provider_id>/accreditation-actions", methods=["POST"])
def accreditation_action(provider_id):
    middleware.require_roles([C.ROLE_BOARD_ADMIN])
    provider = load_provider(provider_id)
    body = middleware.body_json()
    action = middleware.req_enum(body, "action", ACTIONS)
    expected = middleware.req_int(body, "expected_provider_version")
    note = middleware.opt_str(body, "probation_reason", 1, None, None)

    if expected != provider.get("version"):
        fail("ERR_STALE_VERSION", "expected_provider_version does not match the provider's version.")

    status = provider.get("accreditation_status")

    if action == "GRANT_FULL":
        if status == "APPLIED":
            if provider.get("provider_type") not in PRESUMPTIVE_TYPES:
                fail(
                    "ERR_INVALID_STATE_TRANSITION",
                    "A %s sponsor cannot be granted full accreditation from APPLIED."
                    % provider.get("provider_type"),
                )
            cascades.move_provider_status(provider, "ACCREDITED")
            _start_term(provider)
            cascades.assess_fee(
                "PROVIDER_ANNUAL", provider.get("annual_fee_cents") or 0, provider=provider
            )
        elif status == "PROBATIONARY":
            if not _has_cleared_audit(provider):
                fail("ERR_NO_CLEARED_AUDIT", "No audit of this provider has reached CLEARED.")
            cascades.move_provider_status(provider, "ACCREDITED")
        else:
            fail("ERR_INVALID_STATE_TRANSITION", "GRANT_FULL is not declared from %s." % status)
    elif action == "GRANT_PROBATIONARY":
        if status != "APPLIED":
            fail("ERR_INVALID_STATE_TRANSITION", "GRANT_PROBATIONARY is not declared from %s." % status)
        cascades.move_provider_status(provider, "PROBATIONARY")
        _start_term(provider)
        cascades.assess_fee(
            "PROVIDER_ANNUAL", provider.get("annual_fee_cents") or 0, provider=provider
        )
    elif action == "DENY":
        if status != "APPLIED":
            fail("ERR_INVALID_STATE_TRANSITION", "DENY is not declared from %s." % status)
        cascades.move_provider_status(provider, "DENIED")
    elif action == "RENEW":
        if status == "ACCREDITED":
            if cascades.provider_has_open_fee(provider, "PROVIDER_ANNUAL"):
                fail(
                    "ERR_INVALID_STATE_TRANSITION",
                    "The prior term's annual fee is still ASSESSED.",
                )
            _start_term(provider)
            cascades.assess_fee(
                "PROVIDER_ANNUAL", provider.get("annual_fee_cents") or 0, provider=provider
            )
        elif status == "LAPSED":
            cascades.move_provider_status(provider, "PROBATIONARY")
            _start_term(provider)
            cascades.assess_fee(
                "PROVIDER_ANNUAL", provider.get("annual_fee_cents") or 0, provider=provider
            )
            cascades.restore_suspended_courses(provider)
        else:
            fail("ERR_INVALID_STATE_TRANSITION", "RENEW is not declared from %s." % status)
    elif action == "SUSPEND":
        if status not in ("ACCREDITED", "PROBATIONARY"):
            fail("ERR_INVALID_STATE_TRANSITION", "SUSPEND is not declared from %s." % status)
        cascades.move_provider_status(provider, "SUSPENDED")
        cascades.suspend_self_certified_courses(provider)
    else:  # REINSTATE
        if status != "SUSPENDED":
            fail("ERR_INVALID_STATE_TRANSITION", "REINSTATE is not declared from %s." % status)
        if cascades.provider_has_open_fee(provider, "AUDIT_SANCTION"):
            fail("ERR_INVALID_STATE_TRANSITION", "An audit sanction fee is still ASSESSED.")
        cascades.move_provider_status(provider, "PROBATIONARY")
        cascades.restore_suspended_courses(provider)

    if note is not None:
        cascades.set_fields(provider, {"probation_reason": note})
    cascades.refresh_risk(provider)
    db.touch(provider)
    return response.success(db.serialize(provider), 200)
