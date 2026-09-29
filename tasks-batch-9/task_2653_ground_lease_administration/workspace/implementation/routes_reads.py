"""Every read endpoint: single-resource fetches, filtered lists, rent summary."""

from flask import Blueprint, request

import auth
import cascades
import serialize
import store
import validate as v
from response import array_response, object_response

bp = Blueprint("reads", __name__)

ALL = {"LessorAdmin", "AssetManager", "LeaseAccountant", "GroundTenant",
       "MortgageeAgent", "Arbitrator"}


def _arg(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def _first_arg(*names):
    for name in names:
        value = _arg(name)
        if value is not None:
            return value
    return None


def _listing(rows, projector, sort_key=None):
    limit, offset = v.pagination()
    ordered = store.sort_rows(rows, key=sort_key)
    page, total = v.paginate(ordered, limit, offset)
    return array_response([projector(row) for row in page], limit, offset, total)


def _owns(role, user_id, lease_id):
    if role != "GroundTenant":
        return
    auth.owns_lease(user_id, role, store.leases.get(lease_id))


# ===========================================================================
# Single-resource reads
# ===========================================================================
@bp.get("/lessees/<lessee_id>")
def get_lessee(lessee_id):
    record = cascades.fetch("lessee", lessee_id)
    auth.require(ALL - {"Arbitrator"})
    return object_response(serialize.lessee(record), 200)


@bp.get("/leases/<lease_id>")
def get_lease(lease_id):
    record = cascades.fetch("lease", lease_id)
    user_id, role = auth.require(ALL)
    auth.owns_lease(user_id, role, record)
    return object_response(serialize.lease(record), 200)


@bp.get("/leasehold-mortgages/<mortgage_id>")
def get_mortgage(mortgage_id):
    record = cascades.fetch("mortgage", mortgage_id)
    auth.require({"LessorAdmin", "AssetManager", "LeaseAccountant",
                  "MortgageeAgent"})
    return object_response(serialize.mortgage(record), 200)


@bp.get("/rent-revaluations/<revaluation_id>")
def get_revaluation(revaluation_id):
    record = cascades.fetch("revaluation", revaluation_id)
    user_id, role = auth.require({"LessorAdmin", "AssetManager", "GroundTenant",
                                  "Arbitrator"})
    _owns(role, user_id, record["lease_id"])
    return object_response(serialize.revaluation(record), 200)


@bp.get("/appraisal-submissions/<appraisal_id>")
def get_appraisal(appraisal_id):
    record = cascades.fetch("appraisal", appraisal_id)
    user_id, role = auth.require({"LessorAdmin", "GroundTenant", "Arbitrator"})
    revaluation = store.revaluations.get(record["revaluation_id"])
    if revaluation is not None:
        _owns(role, user_id, revaluation["lease_id"])
    return object_response(serialize.appraisal(record), 200)


@bp.get("/arbitrations/<arbitration_id>")
def get_arbitration(arbitration_id):
    record = cascades.fetch("arbitration", arbitration_id)
    user_id, role = auth.require({"LessorAdmin", "GroundTenant", "Arbitrator"})
    revaluation = store.revaluations.get(record["revaluation_id"])
    if revaluation is not None:
        _owns(role, user_id, revaluation["lease_id"])
    return object_response(serialize.arbitration(record), 200)


@bp.get("/percentage-rent-statements/<statement_id>")
def get_statement(statement_id):
    record = cascades.fetch("statement", statement_id)
    user_id, role = auth.require({"LessorAdmin", "LeaseAccountant",
                                  "GroundTenant"})
    _owns(role, user_id, record["lease_id"])
    return object_response(serialize.statement(record), 200)


@bp.get("/alteration-requests/<alteration_id>")
def get_alteration(alteration_id):
    record = cascades.fetch("alteration", alteration_id)
    user_id, role = auth.require({"LessorAdmin", "AssetManager", "GroundTenant"})
    _owns(role, user_id, record["lease_id"])
    return object_response(serialize.alteration(record), 200)


@bp.get("/transfer-requests/<transfer_id>")
def get_transfer(transfer_id):
    record = cascades.fetch("transfer", transfer_id)
    user_id, role = auth.require({"LessorAdmin", "AssetManager",
                                  "LeaseAccountant", "GroundTenant"})
    _owns(role, user_id, record["lease_id"])
    return object_response(serialize.transfer(record), 200)


@bp.get("/default-notices/<notice_id>")
def get_notice(notice_id):
    record = cascades.fetch("notice", notice_id)
    user_id, role = auth.require(ALL - {"Arbitrator"})
    _owns(role, user_id, record["lease_id"])
    return object_response(serialize.notice(record), 200)


@bp.get("/loss-events/<event_id>")
def get_loss_event(event_id):
    record = cascades.fetch("loss_event", event_id)
    user_id, role = auth.require(ALL - {"Arbitrator"})
    _owns(role, user_id, record["lease_id"])
    return object_response(serialize.loss_event(record), 200)


@bp.get("/reversion-assessments/<assessment_id>")
def get_assessment(assessment_id):
    record = cascades.fetch("assessment", assessment_id)
    user_id, role = auth.require({"LessorAdmin", "AssetManager",
                                  "LeaseAccountant", "GroundTenant"})
    _owns(role, user_id, record["lease_id"])
    return object_response(serialize.assessment(record), 200)


@bp.get("/estoppel-certificates/<certificate_id>")
def get_certificate(certificate_id):
    record = cascades.fetch("certificate", certificate_id)
    user_id, role = auth.require({"LessorAdmin", "AssetManager",
                                  "MortgageeAgent", "GroundTenant"})
    _owns(role, user_id, record["lease_id"])
    return object_response(serialize.certificate(record), 200)


@bp.get("/leases/<lease_id>/rent-summary")
def get_rent_summary(lease_id):
    record = cascades.fetch("lease", lease_id)
    user_id, role = auth.require(ALL - {"Arbitrator"})
    auth.owns_lease(user_id, role, record)
    return object_response(cascades.rent_summary(record), 200)


# ===========================================================================
# Collection reads
# ===========================================================================
@bp.get("/lessees")
def list_lessees():
    auth.require({"LessorAdmin", "AssetManager", "LeaseAccountant"})
    rows = list(store.lessees.values())
    code = _arg("credit_rating_code")
    if code is not None:
        rows = [r for r in rows if r["credit_rating_code"] == code]
    return _listing(rows, serialize.lessee)


@bp.get("/leases")
def list_leases():
    auth.require(ALL - {"Arbitrator"})
    rows = list(store.leases.values())
    lessee_id = _arg("lessee_id")
    if lessee_id is not None:
        rows = [r for r in rows if r["lessee_id"] == lessee_id]
    replaces = _first_arg("replaces_lease_id", "predecessor_lease_id")
    if replaces is not None:
        rows = [r for r in rows if r.get("replaces_lease_id") == replaces]
    elected = _first_arg("elected_by_mortgage_id", "origin_mortgage_id")
    if elected is not None:
        rows = [r for r in rows if r.get("elected_by_mortgage_id") == elected]
    lease_status = _arg("lease_status")
    if lease_status is not None:
        rows = [r for r in rows if r["lease_status"] == lease_status]
    rent_status = _arg("rent_status")
    if rent_status is not None:
        rows = [r for r in rows if r["rent_status"] == rent_status]
    return _listing(rows, serialize.lease)


@bp.get("/leasehold-mortgages")
def list_mortgages():
    auth.require({"LessorAdmin", "AssetManager", "LeaseAccountant",
                  "MortgageeAgent"})
    rows = list(store.mortgages.values())
    lease_id = _arg("lease_id")
    if lease_id is not None:
        rows = [r for r in rows if r["lease_id"] == lease_id]
    status = _arg("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]

    def key(row):
        return (row["priority_rank"], row["created_at"], row["_seq"])

    return _listing(rows, serialize.mortgage, sort_key=key)


@bp.get("/rent-revaluations")
def list_revaluations():
    auth.require({"LessorAdmin", "AssetManager", "GroundTenant", "Arbitrator"})
    rows = list(store.revaluations.values())
    lease_id = _arg("lease_id")
    if lease_id is not None:
        rows = [r for r in rows if r["lease_id"] == lease_id]
    status = _arg("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return _listing(rows, serialize.revaluation)


@bp.get("/appraisal-submissions")
def list_appraisals():
    auth.require({"LessorAdmin", "GroundTenant", "Arbitrator"})
    rows = list(store.appraisals.values())
    revaluation_id = _arg("revaluation_id")
    if revaluation_id is not None:
        rows = [r for r in rows if r["revaluation_id"] == revaluation_id]
    appointed_by = _arg("appointed_by")
    if appointed_by is not None:
        rows = [r for r in rows if r["appointed_by"] == appointed_by]
    round_number = _arg("round_number")
    if round_number is not None:
        rows = [r for r in rows if str(r["round_number"]) == str(round_number)]
    return _listing(rows, serialize.appraisal)


@bp.get("/arbitrations")
def list_arbitrations():
    auth.require({"LessorAdmin", "GroundTenant", "Arbitrator"})
    rows = list(store.arbitrations.values())
    revaluation_id = _arg("revaluation_id")
    if revaluation_id is not None:
        rows = [r for r in rows if r["revaluation_id"] == revaluation_id]
    status = _arg("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return _listing(rows, serialize.arbitration)


@bp.get("/percentage-rent-statements")
def list_statements():
    auth.require({"LessorAdmin", "LeaseAccountant", "GroundTenant"})
    rows = list(store.statements.values())
    lease_id = _arg("lease_id")
    if lease_id is not None:
        rows = [r for r in rows if r["lease_id"] == lease_id]
    status = _arg("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    variant = _arg("assessment_variant")
    if variant is not None:
        rows = [r for r in rows if r.get("assessment_variant") == variant]
    return _listing(rows, serialize.statement)


@bp.get("/alteration-requests")
def list_alterations():
    auth.require({"LessorAdmin", "AssetManager", "GroundTenant"})
    rows = list(store.alterations.values())
    lease_id = _arg("lease_id")
    if lease_id is not None:
        rows = [r for r in rows if r["lease_id"] == lease_id]
    status = _arg("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    scope_code = _arg("scope_code")
    if scope_code is not None:
        rows = [r for r in rows if r["scope_code"] == scope_code]
    return _listing(rows, serialize.alteration)


@bp.get("/transfer-requests")
def list_transfers():
    auth.require({"LessorAdmin", "AssetManager", "LeaseAccountant",
                  "GroundTenant"})
    rows = list(store.transfers.values())
    lease_id = _arg("lease_id")
    if lease_id is not None:
        rows = [r for r in rows if r["lease_id"] == lease_id]
    parent = _arg("parent_transfer_id")
    if parent is not None:
        rows = [r for r in rows if r.get("parent_transfer_id") == parent]
    transferee = _arg("transferee_lessee_id")
    if transferee is not None:
        rows = [r for r in rows if r["transferee_lessee_id"] == transferee]
    transfer_type = _arg("transfer_type")
    if transfer_type is not None:
        rows = [r for r in rows if r["transfer_type"] == transfer_type]
    status = _arg("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return _listing(rows, serialize.transfer)


@bp.get("/default-notices")
def list_notices():
    auth.require(ALL - {"Arbitrator"})
    rows = list(store.notices.values())
    lease_id = _arg("lease_id")
    if lease_id is not None:
        rows = [r for r in rows if r["lease_id"] == lease_id]
    status = _arg("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    default_type = _arg("default_type")
    if default_type is not None:
        rows = [r for r in rows if r["default_type"] == default_type]
    return _listing(rows, serialize.notice)


@bp.get("/loss-events")
def list_loss_events():
    auth.require(ALL - {"Arbitrator"})
    rows = list(store.loss_events.values())
    lease_id = _arg("lease_id")
    if lease_id is not None:
        rows = [r for r in rows if r["lease_id"] == lease_id]
    event_type = _arg("event_type")
    if event_type is not None:
        rows = [r for r in rows if r["event_type"] == event_type]
    status = _arg("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return _listing(rows, serialize.loss_event)


@bp.get("/reversion-assessments")
def list_assessments():
    auth.require({"LessorAdmin", "AssetManager", "LeaseAccountant",
                  "GroundTenant"})
    rows = list(store.assessments.values())
    lease_id = _arg("lease_id")
    if lease_id is not None:
        rows = [r for r in rows if r["lease_id"] == lease_id]
    status = _arg("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return _listing(rows, serialize.assessment)


@bp.get("/estoppel-certificates")
def list_certificates():
    auth.require({"LessorAdmin", "AssetManager", "MortgageeAgent",
                  "GroundTenant"})
    rows = list(store.certificates.values())
    lease_id = _arg("lease_id")
    if lease_id is not None:
        rows = [r for r in rows if r["lease_id"] == lease_id]
    mortgage_id = _first_arg("mortgage_id", "requested_by_mortgage_id")
    if mortgage_id is not None:
        rows = [r for r in rows
                if r.get("requested_by_mortgage_id") == mortgage_id]
    status = _arg("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return _listing(rows, serialize.certificate)
