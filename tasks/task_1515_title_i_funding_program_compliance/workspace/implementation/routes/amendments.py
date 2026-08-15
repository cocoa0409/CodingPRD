"""BudgetAmendment endpoints: net-zero drafts, SoD approval, verbatim void."""

from flask import Blueprint

import db
import errors
import middleware
import response
import validators as V
from routes.grants import get_grant_or_404
from services import calc, serializers

bp = Blueprint("amendments", __name__)

ALL_ROLES = middleware.ROLES
FILERS = {"ComplianceAnalyst", "FederalProgramsDirector"}
TARGET_TYPES = {"SCHOOL_ALLOCATION", "SET_ASIDE"}


def get_amendment_or_404(amendment_id):
    a = db.amendments.get(amendment_id)
    if a is None:
        errors.fail(errors.ERR_NOT_FOUND, "Budget amendment %s does not exist." % amendment_id)
    return a


def _resolve_target(target_type, target_id):
    if target_type == "SCHOOL_ALLOCATION":
        return db.allocations.get(target_id)
    return db.set_asides.get(target_id)


def _current_value(target_type, target):
    if target_type == "SCHOOL_ALLOCATION":
        return target["allocation_amount_cents"]
    return target["reserved_cents"]


def _apply_value(target_type, target, value):
    if target_type == "SCHOOL_ALLOCATION":
        target["allocation_amount_cents"] = value
    else:
        target["reserved_cents"] = value


@bp.post("/budget-amendments")
def create_amendment():
    _uid, role = middleware.current_user()
    middleware.require_role(role, FILERS)
    data = V.json_body()
    # Tier 3: grant FK, then line targets (for lines with a recognizable type).
    grant_ref = data.get("grant_id")
    if grant_ref is not None and isinstance(grant_ref, str):
        get_grant_or_404(grant_ref)
    lines_raw = data.get("lines")
    if isinstance(lines_raw, list):
        for line in lines_raw:
            if not isinstance(line, dict):
                continue
            ttype = line.get("target_type")
            tid = line.get("target_id")
            if ttype in TARGET_TYPES and isinstance(tid, str):
                if _resolve_target(ttype, tid) is None:
                    errors.fail(
                        errors.ERR_NOT_FOUND,
                        "Amendment target %s does not exist." % tid,
                    )
    # Tier 4: schema.
    V.check_unknown(data, {"grant_id", "expected_grant_version", "lines"})
    grant_id = V.req_str(data, "grant_id")
    grant = get_grant_or_404(grant_id)
    expected_version = V.req_int(data, "expected_grant_version")
    lines_raw = V.req_array(data, "lines")
    lines = []
    for line in lines_raw:
        if not isinstance(line, dict):
            errors.fail(errors.ERR_INVALID_REQUEST, "Each amendment line must be an object.")
        V.check_unknown(line, {"target_type", "target_id", "new_amount_cents"})
        ttype = V.req_enum(line, "target_type", TARGET_TYPES)
        tid = V.req_str(line, "target_id")
        new_amount = V.req_int(line, "new_amount_cents")
        if new_amount < 0:
            errors.fail(errors.ERR_INVALID_REQUEST, "new_amount_cents must be >= 0.")
        lines.append({"target_type": ttype, "target_id": tid, "new_amount_cents": new_amount})
    # Tier 5.5: OCC on the grant baseline.
    if expected_version != grant["version"]:
        errors.fail(
            errors.ERR_STALE_GRANT_VERSION,
            "expected_grant_version does not match the grant's current version.",
        )
    # Tier 9: every target must belong to this grant.
    for line in lines:
        target = _resolve_target(line["target_type"], line["target_id"])
        if target["grant_id"] != grant["id"]:
            errors.fail(
                errors.ERR_NOT_FOUND,
                "Amendment target %s is not resolvable within grant %s."
                % (line["target_id"], grant["id"]),
            )
    # Tier 11: money conservation — lines are absolute post-amendment values.
    delta = 0
    for line in lines:
        target = _resolve_target(line["target_type"], line["target_id"])
        delta += line["new_amount_cents"] - _current_value(line["target_type"], target)
    if delta != 0:
        errors.fail(
            errors.ERR_AMENDMENT_NOT_NET_ZERO,
            "Amendment lines must net to zero against current values.",
        )
    amendment = db.init_common({
        "grant_id": grant["id"],
        "lines": lines,
        "prior_amounts": [],
        "status": "DRAFT",
        "submitted_by_user_id": None,
        "decided_by_user_id": None,
        "decision_note": None,
    })
    db.amendments[amendment["id"]] = amendment
    # Creating a draft re-baselines the grant (advances its version).
    db.touch(grant)
    return response.success_object(serializers.amendment_view(amendment), 201)


@bp.get("/budget-amendments")
def list_amendments():
    _uid, role = middleware.current_user()
    middleware.require_role(role, ALL_ROLES)
    filters = [
        ("grant_id", V.query_filter("grant_id")),
        ("status", V.query_filter("status")),
    ]
    page, limit, offset, total = V.sorted_page(list(db.amendments.values()), filters)
    return response.success_list(
        [serializers.amendment_view(a) for a in page], limit, offset, total
    )


@bp.get("/budget-amendments/<amendment_id>")
def get_amendment(amendment_id):
    _uid, role = middleware.current_user()
    middleware.require_role(role, ALL_ROLES)
    return response.success_object(serializers.amendment_view(get_amendment_or_404(amendment_id)))


@bp.post("/budget-amendments/<amendment_id>/submit")
def submit_amendment(amendment_id):
    uid, role = middleware.current_user()
    middleware.require_role(role, FILERS)
    amendment = get_amendment_or_404(amendment_id)
    data = V.json_body()
    V.check_unknown(data, set())
    if amendment["status"] != "DRAFT":
        errors.fail(
            errors.ERR_AMENDMENT_INVALID_STATE,
            "Only a DRAFT amendment may be submitted.",
        )
    amendment["status"] = "SUBMITTED"
    amendment["submitted_by_user_id"] = uid
    db.touch(amendment)
    return response.success_object(serializers.amendment_view(amendment))


@bp.post("/budget-amendments/<amendment_id>/approve")
def approve_amendment(amendment_id):
    uid, role = middleware.current_user()
    middleware.require_role(role, {"FederalProgramsDirector"})
    amendment = get_amendment_or_404(amendment_id)
    data = V.json_body()
    V.check_unknown(data, {"decision_note"})
    decision_note = V.opt_str(data, "decision_note")
    # Tier 5: amendment state, then grant state.
    if amendment["status"] != "SUBMITTED":
        errors.fail(
            errors.ERR_AMENDMENT_INVALID_STATE,
            "Only a SUBMITTED amendment may be approved.",
        )
    grant = db.grants[amendment["grant_id"]]
    if grant["status"] != "ALLOCATED":
        errors.fail(
            errors.ERR_GRANT_INVALID_STATE,
            "Amendment approval requires the grant to be ALLOCATED.",
        )
    # Tier 7: segregation of duties against the submitter.
    if uid == amendment["submitted_by_user_id"]:
        errors.fail(
            errors.ERR_SEGREGATION_OF_DUTIES,
            "The approver must differ from the amendment's submitter.",
        )
    # Tier 11: floors re-validated against current reality, all lines checked
    # before any line is applied (atomic).
    for line in amendment["lines"]:
        target = _resolve_target(line["target_type"], line["target_id"])
        new_amount = line["new_amount_cents"]
        if line["target_type"] == "SET_ASIDE":
            if new_amount < target["minimum_cents"]:
                errors.fail(
                    errors.ERR_SET_ASIDE_BELOW_MINIMUM,
                    "Amendment would leave a set-aside below its minimum.",
                )
            if new_amount < target["liquidated_cents"]:
                errors.fail(
                    errors.ERR_AMENDMENT_BELOW_LIQUIDATED,
                    "Amendment would leave a set-aside below its liquidated amount.",
                )
        else:
            floor = target["liquidated_cents"] + target["pending_cents"]
            if new_amount < floor:
                errors.fail(
                    errors.ERR_AMENDMENT_BELOW_LIQUIDATED,
                    "Amendment would leave an allocation below its liquidated + pending floor.",
                )
    prior_amounts = []
    touched_pe = False
    for line in amendment["lines"]:
        target = _resolve_target(line["target_type"], line["target_id"])
        prior_amounts.append({
            "target_id": line["target_id"],
            "prior_amount_cents": _current_value(line["target_type"], target),
        })
    for line in amendment["lines"]:
        target = _resolve_target(line["target_type"], line["target_id"])
        _apply_value(line["target_type"], target, line["new_amount_cents"])
        if line["target_type"] == "SET_ASIDE" and target["category"] == "PARENT_ENGAGEMENT":
            touched_pe = True
        db.touch(target)
    if touched_pe:
        for sa in db.set_asides.values():
            if sa["grant_id"] == grant["id"] and sa["category"] == "PARENT_ENGAGEMENT":
                sa["school_distributed_minimum_cents"] = calc.pe_school_distributed_minimum(
                    sa["reserved_cents"]
                )
                db.touch(sa)
    amendment["prior_amounts"] = prior_amounts
    amendment["status"] = "APPROVED"
    amendment["decided_by_user_id"] = uid
    if decision_note is not None:
        amendment["decision_note"] = decision_note
    db.touch(amendment)
    db.touch(grant)
    return response.success_object(serializers.amendment_view(amendment))


@bp.post("/budget-amendments/<amendment_id>/reject")
def reject_amendment(amendment_id):
    uid, role = middleware.current_user()
    middleware.require_role(role, {"FederalProgramsDirector"})
    amendment = get_amendment_or_404(amendment_id)
    data = V.json_body()
    V.check_unknown(data, {"decision_note"})
    decision_note = V.opt_str(data, "decision_note")
    if not decision_note:
        errors.fail(errors.ERR_INVALID_REQUEST, "decision_note is required on reject.")
    if amendment["status"] != "SUBMITTED":
        errors.fail(
            errors.ERR_AMENDMENT_INVALID_STATE,
            "Only a SUBMITTED amendment may be rejected.",
        )
    if uid == amendment["submitted_by_user_id"]:
        errors.fail(
            errors.ERR_SEGREGATION_OF_DUTIES,
            "The rejecter must differ from the amendment's submitter.",
        )
    amendment["status"] = "REJECTED"
    amendment["decided_by_user_id"] = uid
    amendment["decision_note"] = decision_note
    db.touch(amendment)
    return response.success_object(serializers.amendment_view(amendment))


@bp.post("/budget-amendments/<amendment_id>/void")
def void_amendment(amendment_id):
    uid, role = middleware.current_user()
    middleware.require_role(role, {"FederalProgramsDirector"})
    amendment = get_amendment_or_404(amendment_id)
    data = V.json_body()
    V.check_unknown(data, {"decision_note"})
    decision_note = V.opt_str(data, "decision_note")
    if amendment["status"] != "APPROVED":
        errors.fail(
            errors.ERR_AMENDMENT_INVALID_STATE,
            "Only an APPROVED amendment may be voided.",
        )
    grant = db.grants[amendment["grant_id"]]
    if grant["status"] != "ALLOCATED":
        errors.fail(
            errors.ERR_GRANT_INVALID_STATE,
            "Voiding an amendment requires the grant to be ALLOCATED.",
        )
    if uid == amendment["submitted_by_user_id"]:
        errors.fail(
            errors.ERR_SEGREGATION_OF_DUTIES,
            "The voider must differ from the amendment's submitter.",
        )
    # Compensating action: restore prior_amounts verbatim (money conservation).
    line_type = {line["target_id"]: line["target_type"] for line in amendment["lines"]}
    touched_pe = False
    for prior in amendment["prior_amounts"]:
        ttype = line_type[prior["target_id"]]
        target = _resolve_target(ttype, prior["target_id"])
        _apply_value(ttype, target, prior["prior_amount_cents"])
        if ttype == "SET_ASIDE" and target["category"] == "PARENT_ENGAGEMENT":
            touched_pe = True
        db.touch(target)
    if touched_pe:
        for sa in db.set_asides.values():
            if sa["grant_id"] == grant["id"] and sa["category"] == "PARENT_ENGAGEMENT":
                sa["school_distributed_minimum_cents"] = calc.pe_school_distributed_minimum(
                    sa["reserved_cents"]
                )
                db.touch(sa)
    amendment["status"] = "VOIDED"
    amendment["decided_by_user_id"] = uid
    if decision_note is not None:
        amendment["decision_note"] = decision_note
    db.touch(amendment)
    db.touch(grant)
    return response.success_object(serializers.amendment_view(amendment))
