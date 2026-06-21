"""Award endpoints (PRD §3.2)."""
from flask import Blueprint, request

import db
import errors
from middleware import require_roles
from response import success
from services import common as c
from services.award import serialize_award

bp = Blueprint("awards", __name__)

READ_ROLES = ("GrantWriter", "FinanceOfficer", "ProgramManager", "AgencyOfficer", "Auditor")


def _load(award_id):
    award = db.awards.get(award_id)
    if award is None:
        raise errors.not_found("Award not found.")
    return award


def _check_occ(award, body):
    """OCC guard (PRD §2.6, §3.9 priority 5). expected_award_version is required
    on these endpoints and must equal the award's current version."""
    expected = body.get("expected_award_version")
    if expected is None:
        raise errors.invalid_request("expected_award_version is required.")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise errors.invalid_request("expected_award_version must be an integer.")
    if expected != award["version"]:
        raise errors.stale_version()


@bp.route("/awards", methods=["GET"])
@require_roles(*READ_ROLES)
def list_awards(user_id, role):
    limit, offset = c.parse_pagination()
    application_id = request.args.get("application_id")
    status = request.args.get("status")
    with db.LOCK:
        records = list(db.awards.values())
    if application_id is not None:
        records = [r for r in records if r["application_id"] == application_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, pagination = c.paginate(records, limit, offset)
    return success([serialize_award(r) for r in page], status=200, pagination=pagination)


@bp.route("/awards/<award_id>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_award(award_id, user_id, role):
    with db.LOCK:
        award = _load(award_id)
        return success(serialize_award(award), status=200)


@bp.route("/awards/<award_id>/suspend", methods=["POST"])
@require_roles("AgencyOfficer")
def suspend_award(award_id, user_id, role):
    body = c.get_body()
    with db.LOCK:
        award = _load(award_id)
        if award["status"] != "ACTIVE":
            raise errors.invalid_state("Only an ACTIVE award may be suspended.")
        _check_occ(award, body)
        award["status"] = "SUSPENDED"
        db.touch(award)
        return success(serialize_award(award), status=200)


@bp.route("/awards/<award_id>/reinstate", methods=["POST"])
@require_roles("AgencyOfficer")
def reinstate_award(award_id, user_id, role):
    body = c.get_body()
    with db.LOCK:
        award = _load(award_id)
        if award["status"] != "SUSPENDED":
            raise errors.invalid_state("Only a SUSPENDED award may be reinstated.")
        _check_occ(award, body)
        award["status"] = "ACTIVE"
        db.touch(award)
        return success(serialize_award(award), status=200)


@bp.route("/awards/<award_id>/initiate-closeout", methods=["POST"])
@require_roles("AgencyOfficer")
def initiate_closeout(award_id, user_id, role):
    body = c.get_body()
    with db.LOCK:
        award = _load(award_id)
        if award["status"] != "ACTIVE":
            raise errors.invalid_state("Only an ACTIVE award may initiate closeout.")
        _check_occ(award, body)
        award["status"] = "PENDING_CLOSEOUT"
        db.touch(award)
        return success(serialize_award(award), status=200)


@bp.route("/awards/<award_id>/close", methods=["POST"])
@require_roles("AgencyOfficer")
def close_award(award_id, user_id, role):
    body = c.get_body()
    with db.LOCK:
        award = _load(award_id)
        # priority 4: state
        if award["status"] != "PENDING_CLOSEOUT":
            raise errors.invalid_state("Only a PENDING_CLOSEOUT award may be closed.")
        # priority 5: OCC
        _check_occ(award, body)

        # priority 8: audit-resolution guard (ERR_AUDIT_UNRESOLVED).
        # Every required SingleAudit must be RESOLVED, and no MATERIAL_WEAKNESS
        # finding may remain OPEN (PRD §3.2).
        for audit in db.single_audits.values():
            if audit["award_id"] != award["id"]:
                continue
            if audit.get("audit_required") and audit["status"] != "RESOLVED":
                raise errors.audit_unresolved()
        for audit in db.single_audits.values():
            if audit["award_id"] != award["id"]:
                continue
            for finding in db.audit_findings.values():
                if finding["single_audit_id"] != audit["id"]:
                    continue
                if finding["severity"] == "MATERIAL_WEAKNESS" and finding["status"] == "OPEN":
                    raise errors.audit_unresolved()

        # priority 9: report-and-subaward guard (ERR_CLOSEOUT_PRECONDITIONS).
        for r in db.financial_reports.values():
            if r["award_id"] == award["id"] and r["status"] in ("DRAFT", "SUBMITTED"):
                raise errors.closeout_preconditions()
        for s in db.subawards.values():
            if s["award_id"] == award["id"] and s["status"] == "ACTIVE":
                raise errors.closeout_preconditions()

        # All gates pass: close and compute unobligated balance (PRD §3.2).
        award["status"] = "CLOSED"
        closeout_unobligated_cents = award["federal_ceiling_cents"] - award["federal_drawn_cents"]
        db.touch(award)
        return success(
            serialize_award(award, extra={"closeout_unobligated_cents": closeout_unobligated_cents}),
            status=200,
        )
