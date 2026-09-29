"""PRD 3.2 enrollment, capacity and the conservation of subsidy slots."""
from flask import Blueprint, request

import auth
import db
import response
import services
import validators as v
from errors import ApiError

bp = Blueprint("enrollments", __name__)

NON_TERMINAL = ("ENROLLED", "TRANSITION_PENDING")


def _enrollment(actor, enrollment_id):
    row = services.enrollment_or_404(enrollment_id)
    auth.scope_provider(actor, row["provider_id"])
    return row


def _commit_subsidy_slot(enrollment, provider):
    contract = services.active_contract(provider["id"])
    if contract is None or contract["available_slots"] < 1:
        raise ApiError(
            "ERR_SUBSIDY_SLOTS_EXHAUSTED",
            "The provider's active subsidy contract has no available slot.",
        )
    services.commit_slot(enrollment, contract)


@bp.post("/fccn/enrollments")
def create_enrollment():
    actor = auth.require_auth(("Provider",))
    body = v.get_body()
    provider_id = v.req_str(body, "provider_id")
    auth.scope_provider(actor, provider_id)
    provider = services.provider_or_404(provider_id)

    child_ref = v.req_str(body, "child_ref")
    family_name = v.req_str(body, "family_name")
    days_per_week = v.req_int(body, "days_per_week", 1, 5)
    private_monthly_tuition_cents = v.opt_int(body, "private_monthly_tuition_cents", 0, 0)
    subsidy_certified = v.opt_bool(body, "subsidy_certified", False)
    start_on = v.req_instant(body, "start_on")
    v.reject_unversioned(body)

    services.check_posture(provider, restricted_blocks=True)
    services.check_license_current(provider)

    siblings = services.provider_children(db.enrollments, provider["id"])
    occupied = len([e for e in siblings if e["status"] in NON_TERMINAL])
    capacity = provider["capacity_slots"] or 0
    if occupied >= capacity:
        raise ApiError(
            "ERR_CAPACITY_EXCEEDED",
            "The provider's licensed capacity of %d children is full." % capacity,
        )
    if any(e["child_ref"] == child_ref and e["status"] in NON_TERMINAL for e in siblings):
        raise ApiError(
            "ERR_DUPLICATE_CHILD_REF",
            "child_ref '%s' is already in use by a non-terminal enrollment." % child_ref,
        )

    row = db.make_row(
        provider_id=provider["id"],
        predecessor_enrollment_id=None,
        child_ref=child_ref,
        family_name=family_name,
        days_per_week=days_per_week,
        private_monthly_tuition_cents=private_monthly_tuition_cents,
        subsidy_certified=subsidy_certified,
        start_on=start_on,
        status="ENROLLED",
        slot_committed=False,
        exit_on=None,
    )
    row["_slot_contract_id"] = None
    services.register_new(row)
    if subsidy_certified:
        _commit_subsidy_slot(row, provider)
    db.enrollments[row["id"]] = row
    services.recompute_revenue(provider)
    return response.created(row)


@bp.post("/fccn/enrollments/<enrollment_id>/withdraw")
def withdraw_enrollment(enrollment_id):
    actor = auth.require_auth(("Provider",))
    enrollment = _enrollment(actor, enrollment_id)
    body = v.get_body()
    v.reject_unversioned(body)
    exit_on = v.req_instant(body, "exit_on")

    if enrollment["status"] not in NON_TERMINAL:
        raise ApiError(
            "ERR_INVALID_ENROLLMENT_STATE",
            "Only an ENROLLED or TRANSITION_PENDING enrollment may be withdrawn.",
        )

    enrollment["status"] = "WITHDRAWN"
    enrollment["exit_on"] = exit_on
    services.release_slot(enrollment)
    services.touch(enrollment)
    services.recompute_revenue(db.providers[enrollment["provider_id"]])
    return response.ok(enrollment)


@bp.post("/fccn/enrollments/<enrollment_id>/transfer")
def transfer_enrollment(enrollment_id):
    auth.require_auth(("NetworkAdmin",))
    source = services.enrollment_or_404(enrollment_id)
    body = v.get_body()
    receiving_provider_id = v.req_str(body, "receiving_provider_id")
    receiving = services.provider_or_404(receiving_provider_id)
    transfer_on = v.req_instant(body, "transfer_on")
    v.reject_unversioned(body)

    if source["status"] != "TRANSITION_PENDING":
        raise ApiError(
            "ERR_INVALID_ENROLLMENT_STATE",
            "Only a TRANSITION_PENDING enrollment may be placed with another provider.",
        )

    ineligible = None
    if receiving["id"] == source["provider_id"]:
        ineligible = "The receiving provider must be a different home."
    elif receiving["membership_status"] != "ACTIVE" or receiving["network_posture"] != "OPEN":
        ineligible = "The receiving provider must be ACTIVE with an OPEN network posture."
    else:
        enrolled = len([
            e for e in services.provider_children(db.enrollments, receiving["id"])
            if e["status"] == "ENROLLED"
        ])
        if enrolled >= (receiving["capacity_slots"] or 0):
            ineligible = "The receiving provider has no licensed capacity left."
        elif source["subsidy_certified"]:
            contract = services.active_contract(receiving["id"])
            if contract is None or contract["available_slots"] < 1:
                ineligible = "The receiving provider holds no subsidy slot for this child."
    if ineligible is not None:
        raise ApiError("ERR_RECEIVING_PROVIDER_INELIGIBLE", ineligible)

    source["status"] = "TRANSFERRED"
    source["exit_on"] = transfer_on
    services.release_slot(source)
    services.touch(source)

    row = db.make_row(
        provider_id=receiving["id"],
        predecessor_enrollment_id=source["id"],
        child_ref=source["child_ref"],
        family_name=source["family_name"],
        days_per_week=source["days_per_week"],
        private_monthly_tuition_cents=source["private_monthly_tuition_cents"],
        subsidy_certified=source["subsidy_certified"],
        start_on=transfer_on,
        status="ENROLLED",
        slot_committed=False,
        exit_on=None,
    )
    row["_slot_contract_id"] = None
    services.register_new(row)
    if row["subsidy_certified"]:
        _commit_subsidy_slot(row, receiving)
    db.enrollments[row["id"]] = row

    services.recompute_revenue(db.providers[source["provider_id"]])
    services.recompute_revenue(receiving)
    return response.created(row)


@bp.get("/fccn/enrollments")
def list_enrollments():
    actor = auth.require_auth(("NetworkAdmin", "FiscalOfficer", "Provider"))
    if actor.is_provider:
        wanted = request.args.get("provider_id")
        if wanted not in (None, "", actor.user_id):
            raise ApiError("ERR_PROVIDER_SCOPE_VIOLATION")
    limit, offset = v.pagination()
    rows = v.filtered(
        db.enrollments.values(),
        provider_id="provider_id",
        predecessor_enrollment_id="predecessor_enrollment_id",
        status="status",
    )
    if actor.is_provider:
        rows = [r for r in rows if r["provider_id"] == actor.user_id]
    page, total = v.paginate(rows, limit, offset)
    return response.ok_list(page, limit, offset, total)


@bp.get("/fccn/enrollments/<enrollment_id>")
def read_enrollment(enrollment_id):
    actor = auth.require_auth(("NetworkAdmin", "FiscalOfficer", "Provider"))
    return response.ok(_enrollment(actor, enrollment_id))
