"""Annual certification packages and the submission dimension (PRD 3.8)."""
from flask import Blueprint

import clock
import constants as C
import response
import validate as V
from auth import ALL_ROLES, actor, require
from db import new_record, sorted_by_created, store, touch
from errors import ApiError
from routes.common import (ensure_from_state, ensure_not_terminal, get_network,
                           get_package, get_pollutant)
from services import cascade
from services import compute as K
from services import serialize as S

bp = Blueprint("packages", __name__)

PACKAGE_TERMINAL = ("CERTIFIED",)


@bp.post("/certification-packages")
@require("ProgramManager")
def open_package():
    data = V.body()
    network_id = V.req_id(data, "network_id")
    pollutant_id = V.req_id(data, "pollutant_id")
    year = V.req_int(data, "year", lo=2000, hi=2100)
    get_network(network_id)
    get_pollutant(pollutant_id)
    for row in store.packages.values():
        if (row["network_id"] == network_id and row["pollutant_id"] == pollutant_id
                and row["year"] == year):
            V.bad("A certification package already exists for this network, pollutant and year.")
    rec = new_record()
    rec.update({
        "network_id": network_id,
        "pollutant_id": pollutant_id,
        "year": year,
        "certification_deadline": K.certification_deadline(year),
        "status": "DRAFT",
        "rejection_count": 0,
        "certified_by_user_id": None,
        "certified_at": None,
    })
    rec.update(K.certification_package_rollup(rec))
    store.packages[rec["id"]] = rec
    return response.object_response(S.package(rec), 201)


@bp.post("/certification-packages/<package_id>/submit")
@require("ProgramManager")
def submit_package(package_id):
    data = V.body()
    V.opt_string(data, "submission_note")
    pkg = get_package(package_id)
    ensure_not_terminal(pkg["status"], PACKAGE_TERMINAL, "certification package")
    ensure_from_state(pkg["status"], ("DRAFT",), "certification package")
    # The rollup is refreshed immediately before the readiness gate is applied.
    pkg.update(K.certification_package_rollup(pkg))
    if not pkg["certification_ready"]:
        raise ApiError("ERR_PACKAGE_NOT_READY",
                       "The package is not ready for submission: %d member quarters, %d eligible."
                       % (pkg["included_batch_count"], pkg["eligible_batch_count"]))
    pkg["status"] = "SUBMITTED"
    touch(pkg)
    for batch in K.package_selected_batches(pkg):
        if batch["submission_status"] == "UNSUBMITTED":
            batch["submission_status"] = "SUBMITTED"
            touch(batch)
    return response.object_response(S.package(pkg))


@bp.post("/certification-packages/<package_id>/certify")
@require("ProgramManager")
def certify_package(package_id):
    data = V.body()
    V.opt_string(data, "certification_statement")
    pkg = get_package(package_id)
    ensure_not_terminal(pkg["status"], PACKAGE_TERMINAL, "certification package")
    ensure_from_state(pkg["status"], ("SUBMITTED",), "certification package")
    scope = K.package_scope_batches(pkg["network_id"], pkg["pollutant_id"], pkg["year"])
    for batch in sorted_by_created(scope):
        if batch["submission_status"] == "SUBMITTED" and batch["validation_status"] != "VALIDATED":
            raise ApiError("ERR_MEMBER_BATCH_NOT_VALIDATED",
                           "Member quarter %s is in validation_status %s and blocks certification."
                           % (batch["id"], batch["validation_status"]))
    caller = actor()
    selected = K.package_selected_batches(pkg)
    for batch in selected:
        if batch["validated_by_user_id"] is not None and batch["validated_by_user_id"] == caller:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                           "The caller validated member quarter %s and may not certify this "
                           "package." % batch["id"])
    if not clock.now() < pkg["certification_deadline"]:
        raise ApiError("ERR_CERTIFICATION_DEADLINE_PASSED",
                       "The certification deadline has passed.")
    pkg["status"] = "CERTIFIED"
    pkg["certified_by_user_id"] = caller
    pkg["certified_at"] = clock.now()
    touch(pkg)
    for batch in selected:
        if batch["submission_status"] == "SUBMITTED":
            batch["submission_status"] = "CERTIFIED"
            touch(batch)
    return response.object_response(S.package(pkg))


@bp.post("/certification-packages/<package_id>/reject")
@require("EpaRegionalReviewer")
def reject_package(package_id):
    data = V.body()
    V.req_string(data, "rejection_reason", min_len=1, max_len=1000)
    pkg = get_package(package_id)
    ensure_not_terminal(pkg["status"], PACKAGE_TERMINAL, "certification package")
    ensure_from_state(pkg["status"], ("SUBMITTED",), "certification package")
    pkg["status"] = "DRAFT"
    pkg["rejection_count"] += 1
    touch(pkg)
    cascade.demote_submitted_batches(pkg)
    return response.object_response(S.package(pkg))


@bp.get("/certification-packages/<package_id>")
@require(*ALL_ROLES)
def read_package(package_id):
    return response.object_response(S.package(get_package(package_id)))


@bp.get("/certification-packages")
@require(*ALL_ROLES)
def list_packages():
    limit, offset = V.pagination()
    network_id = V.q_string("network_id")
    pollutant_id = V.q_string("pollutant_id")
    year = V.q_int("year")
    status = V.q_enum("status", C.PACKAGE_STATUSES)
    rows = list(store.packages.values())
    if network_id is not None:
        rows = [p for p in rows if p["network_id"] == network_id]
    if pollutant_id is not None:
        rows = [p for p in rows if p["pollutant_id"] == pollutant_id]
    if year is not None:
        rows = [p for p in rows if p["year"] == year]
    if status is not None:
        rows = [p for p in rows if p["status"] == status]
    rows = sorted_by_created(rows)
    page, meta = response.paginate(rows, limit, offset)
    return response.array_response([S.package(p) for p in page], pagination=meta)
