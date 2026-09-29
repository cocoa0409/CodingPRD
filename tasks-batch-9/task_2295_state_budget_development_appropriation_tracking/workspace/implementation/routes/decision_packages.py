"""Decision packages and the performance measures that justify them."""

from flask import Blueprint

import auth
import db
import response
from errors import fail
from services import constants as C
from services import core
from validators import (
    bad_amount,
    body_json,
    listing,
    peek_fk,
    query_enum,
    query_str,
    read_enum,
    read_id,
    read_int,
    read_number,
    read_str,
)

bp = Blueprint("decision_packages", __name__)


@bp.post("/fiscal/decision-packages")
def create_package():
    actor = auth.authenticate((auth.AGENCY_BUDGET_OFFICER,))
    body = body_json()

    request_row = peek_fk(body, "agency_request_id", core.get_request)
    prerequisite = peek_fk(body, "depends_on_package_id", core.get_package)
    if request_row is not None:
        auth.require_agency_scope(actor, request_row["agency_id"])

    read_id(body, "agency_request_id")
    package_type = read_enum(body, "package_type", C.PACKAGE_TYPES)
    priority_rank = read_int(body, "priority_rank")
    amount_cents = read_int(body, "amount_cents")
    fte_delta = read_number(body, "fte_delta", required=False, default=0)
    if priority_rank < 1:
        bad_amount("priority_rank must be at least 1.")
    if amount_cents <= 0:
        bad_amount("amount_cents must be greater than zero.")

    core.require_not_closed(core.cycle_of(request_row))

    if prerequisite is not None:
        if (
            prerequisite["agency_request_id"] != request_row["id"]
            or prerequisite["status"] == "DEFERRED"
        ):
            fail(
                "ERR_DEPENDENCY_DEFERRED",
                "depends_on_package_id must name a non-deferred package of the same request.",
            )

    for existing in core.packages_of(request_row["id"]):
        if existing["priority_rank"] == priority_rank:
            fail(
                "ERR_DUPLICATE_PRIORITY_RANK",
                "priority_rank %d is already used within this request." % priority_rank,
            )

    row = db.new_row()
    row.update(
        {
            "agency_request_id": request_row["id"],
            "depends_on_package_id": prerequisite["id"] if prerequisite else None,
            "package_type": package_type,
            "priority_rank": priority_rank,
            "amount_cents": amount_cents,
            "fte_delta": fte_delta,
            "status": "PROPOSED",
        }
    )
    db.decision_packages[row["id"]] = row
    core.recompute_request_total(request_row)
    return response.created(db.serialize(row))


@bp.get("/fiscal/decision-packages/<package_id>")
def read_package(package_id):
    auth.authenticate(auth.ANY_ROLE)
    row = core.get_package(package_id)
    return response.ok(db.serialize(row))


@bp.get("/fiscal/decision-packages")
def list_packages():
    auth.authenticate(auth.ANY_ROLE)
    request_id = query_str("agency_request_id")
    depends_on = query_str("depends_on_package_id")
    status = query_enum("status", C.PACKAGE_STATUSES)
    package_type = query_enum("package_type", C.PACKAGE_TYPES)
    rows = []
    for row in db.decision_packages.values():
        if request_id is not None and row["agency_request_id"] != request_id:
            continue
        if depends_on is not None and row["depends_on_package_id"] != depends_on:
            continue
        if status is not None and row["status"] != status:
            continue
        if package_type is not None and row["package_type"] != package_type:
            continue
        rows.append(row)
    data, meta = listing(rows)
    return response.ok_list(data, meta)


@bp.post("/fiscal/decision-packages/<package_id>/recommend")
def recommend_package(package_id):
    auth.authenticate((auth.BUDGET_ANALYST,))
    row = core.get_package(package_id)
    request_row = core.get_request(row["agency_request_id"])
    core.require_not_closed(core.cycle_of(request_row))

    if row["status"] not in ("PROPOSED", "DEFERRED"):
        fail(
            "ERR_INVALID_STATE",
            "A package in status %s may not be recommended." % row["status"],
        )
    if request_row["status"] != "ACCEPTED":
        fail("ERR_INVALID_STATE", "The owning request is not ACCEPTED.")

    if row["depends_on_package_id"]:
        prerequisite = db.decision_packages.get(row["depends_on_package_id"])
        if prerequisite is None or prerequisite["status"] != "RECOMMENDED":
            fail(
                "ERR_DEPENDENCY_NOT_RECOMMENDED",
                "The prerequisite package is not RECOMMENDED.",
            )
    if row["package_type"] == "EXPANSION":
        measures = core.measures_of(row["id"])
        if not any(m["target_value"] > m["baseline_value"] for m in measures):
            fail(
                "ERR_PERFORMANCE_MEASURE_REQUIRED",
                "An EXPANSION package needs a performance measure with an improving target.",
            )

    db.apply_changes(row, {"status": "RECOMMENDED"})
    core.recompute_request_total(request_row)
    return response.ok(db.serialize(row))


@bp.post("/fiscal/decision-packages/<package_id>/defer")
def defer_package(package_id):
    auth.authenticate((auth.BUDGET_ANALYST,))
    row = core.get_package(package_id)
    request_row = core.get_request(row["agency_request_id"])
    core.require_not_closed(core.cycle_of(request_row))
    if row["status"] != "PROPOSED":
        fail("ERR_INVALID_STATE", "Only a PROPOSED package may be deferred.")
    db.apply_changes(row, {"status": "DEFERRED"})
    core.recompute_request_total(request_row)
    return response.ok(db.serialize(row))


@bp.post("/fiscal/performance-measures")
def create_measure():
    actor = auth.authenticate((auth.AGENCY_BUDGET_OFFICER,))
    body = body_json()

    package = peek_fk(body, "decision_package_id", core.get_package)
    if package is not None:
        request_row = core.get_request(package["agency_request_id"])
        auth.require_agency_scope(actor, request_row["agency_id"])

    read_id(body, "decision_package_id")
    measure_code = read_str(body, "measure_code", min_len=1, max_len=32)
    unit = read_enum(body, "unit", C.MEASURE_UNITS)
    baseline_value = read_number(body, "baseline_value")
    target_value = read_number(body, "target_value")
    if baseline_value < 0:
        fail("ERR_INVALID_REQUEST", "baseline_value must be zero or positive.")
    if target_value <= baseline_value:
        fail(
            "ERR_PERFORMANCE_TARGET_INVALID",
            "target_value must be strictly greater than baseline_value.",
        )

    core.require_not_closed(core.cycle_of(package))

    row = db.new_row(audited=False)
    row.update(
        {
            "decision_package_id": package["id"],
            "measure_code": measure_code,
            "unit": unit,
            "baseline_value": baseline_value,
            "target_value": target_value,
        }
    )
    db.performance_measures[row["id"]] = row
    return response.created(db.serialize(row))


@bp.get("/fiscal/decision-packages/<package_id>/performance-measures")
def list_measures(package_id):
    auth.authenticate(auth.ANY_ROLE)
    package = core.get_package(package_id)
    data, meta = listing(core.measures_of(package["id"]))
    return response.ok_list(data, meta)
