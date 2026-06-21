"""RxAuthorization endpoints (PRD 3.10)."""
from flask import Blueprint, g, request

from common import (as_int, as_str, get_body, init_common, parse_pagination,
                    require, sort_by_creation, touch)
from db import db
from errors import (ERR_BMI_BELOW_RX_THRESHOLD, ERR_ELIGIBILITY_NOT_APPROVED,
                    ERR_ENROLLMENT_ACTIVE_RX_LOCKED, ERR_INVALID_STATE,
                    ERR_STALE_ENROLLMENT_VERSION, raise_error)
from lookups import get_eligibility, get_enrollment, get_rx
from middleware import require_roles
from response import paginated, success
from serializers import serialize
import calculations as calc

bp = Blueprint("rx", __name__)

ALL_READ = ("ProgramAdmin", "Clinician", "Member")


def _approved_intake_for_member(member_id):
    approved = [a for a in db.intake_assessments.values()
                if a["member_id"] == member_id and a["status"] == "APPROVED"]
    approved.sort(key=lambda a: a["_seq"])
    return approved[-1] if approved else None


@bp.route("/wm/rx-authorizations", methods=["POST"])
@require_roles("ProgramAdmin", "Clinician")
def request_rx():
    body = get_body()
    enrollment_id = as_str(require(body, "enrollment_id"), "enrollment_id")
    determination_id = as_str(
        require(body, "eligibility_determination_id"), "eligibility_determination_id")

    enrollment = get_enrollment(enrollment_id)
    get_eligibility(determination_id)  # ERR_ELIGIBILITY_NOT_FOUND

    rx = {
        "enrollment_id": enrollment_id,
        "member_id": enrollment["member_id"],
        "eligibility_determination_id": determination_id,
        "clinician_user_id": None,
        "qualifying_bmi": None,
        "status": "REQUESTED",
    }
    init_common(rx)
    db.rx_authorizations[rx["id"]] = rx
    return success(serialize(rx), 201)


@bp.route("/wm/rx-authorizations", methods=["GET"])
@require_roles(*ALL_READ)
def list_rx():
    limit, offset = parse_pagination()
    items = list(db.rx_authorizations.values())
    enrollment_id = request.args.get("enrollment_id")
    member_id = request.args.get("member_id")
    determination_id = request.args.get("eligibility_determination_id")
    status = request.args.get("status")
    if enrollment_id is not None:
        items = [r for r in items if r["enrollment_id"] == enrollment_id]
    if member_id is not None:
        items = [r for r in items if r["member_id"] == member_id]
    if determination_id is not None:
        items = [r for r in items if r["eligibility_determination_id"] == determination_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items = sort_by_creation(items)
    total = len(items)
    page = items[offset:offset + limit]
    return paginated([serialize(r) for r in page], limit, offset, total)


@bp.route("/wm/rx-authorizations/<rx_id>", methods=["GET"])
@require_roles(*ALL_READ)
def get_one_rx(rx_id):
    return success(serialize(get_rx(rx_id)), 200)


@bp.route("/wm/rx-authorizations/<rx_id>/issue", methods=["POST"])
@require_roles("Clinician")
def issue_rx(rx_id):
    rx = get_rx(rx_id)
    body = get_body()
    expected_version = as_int(
        require(body, "expected_enrollment_version"), "expected_enrollment_version")

    enrollment = get_enrollment(rx["enrollment_id"])

    # OCC check after existence, before business logic (PRD 2.7)
    if expected_version != enrollment["version"]:
        raise_error(ERR_STALE_ENROLLMENT_VERSION,
                    "expected_enrollment_version does not match enrollment.version")

    # state gate
    if rx["status"] != "REQUESTED":
        raise_error(ERR_INVALID_STATE, "Issue allowed only from REQUESTED")

    determination = get_eligibility(rx["eligibility_determination_id"])
    if determination["status"] != "APPROVED":
        raise_error(ERR_ELIGIBILITY_NOT_APPROVED,
                    "EligibilityDetermination must be APPROVED")

    # BMI gate: BMI >= 30.0, OR BMI >= 27.0 with >=1 comorbidity (approved intake)
    intake = _approved_intake_for_member(rx["member_id"])
    bmi = intake["bmi"] if intake else None
    comorbidity = intake["comorbidity_count"] if intake else 0
    if bmi is None or not _bmi_gate_ok(bmi, comorbidity):
        raise_error(ERR_BMI_BELOW_RX_THRESHOLD, "Member BMI below RX threshold")

    rx["status"] = "ISSUED"
    rx["qualifying_bmi"] = bmi
    rx["clinician_user_id"] = g.user_id
    touch(rx)
    # issuance advances enrollment version (PRD 2.7)
    touch(enrollment)
    return success(serialize(rx), 200)


def _bmi_gate_ok(bmi, comorbidity_count):
    from decimal import Decimal
    b = Decimal(str(bmi))
    if b >= calc.RX_BMI_MIN:
        return True
    if b >= calc.RX_BMI_COMORBID_MIN and comorbidity_count >= 1:
        return True
    return False


@bp.route("/wm/rx-authorizations/<rx_id>/deny", methods=["POST"])
@require_roles("Clinician")
def deny_rx(rx_id):
    rx = get_rx(rx_id)
    if rx["status"] != "REQUESTED":
        raise_error(ERR_INVALID_STATE, "Deny allowed only from REQUESTED")
    rx["status"] = "DENIED"
    touch(rx)
    return success(serialize(rx), 200)


@bp.route("/wm/rx-authorizations/<rx_id>/revoke", methods=["POST"])
@require_roles("Clinician")
def revoke_rx(rx_id):
    rx = get_rx(rx_id)
    if rx["status"] != "ISSUED":
        raise_error(ERR_INVALID_STATE, "Revoke allowed only from ISSUED")
    enrollment = get_enrollment(rx["enrollment_id"])
    if enrollment["clinical_status"] == "ACTIVE":
        raise_error(ERR_ENROLLMENT_ACTIVE_RX_LOCKED,
                    "Cannot revoke while enrollment is clinically ACTIVE")
    rx["status"] = "REVOKED"
    touch(rx)
    return success(serialize(rx), 200)
