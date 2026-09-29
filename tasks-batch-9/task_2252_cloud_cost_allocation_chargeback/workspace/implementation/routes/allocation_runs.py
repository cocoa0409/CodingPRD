"""Allocation runs, their pools, compute, adjustments and lifecycle (PRD 3.5, 3.6)."""
from flask import Blueprint

from db import base_fields, db, touch
from errors import fail
from middleware import authorize, user_id
from routes.common import lookup, optional_ref, serve, serve_list
from services import derived, flows
from services.calc import MAX_RUN_REOPENS
from validation import (
    body,
    opt_enum,
    present,
    req_enum,
    req_int,
    req_interval,
    req_str,
    req_str_list,
)

bp = Blueprint("allocation_runs", __name__)

MODES = ("SHOWBACK", "CHARGEBACK")
VARIANTS = ("PROVISIONAL", "FINAL")
METHODOLOGIES = ("PROPORTIONAL", "EVEN_SPLIT")
BASES = ("SPEND", "HEADCOUNT", "REVENUE")
READERS = ("FinOpsAnalyst", "FinOpsController", "PlatformAdmin", "BusinessUnitOwner")
OPEN_DISPUTE_STATES = ("OPEN", "UNDER_REVIEW", "INFO_REQUESTED")


# --------------------------------------------------------------------------
# run creation and reads
# --------------------------------------------------------------------------
@bp.route("/finops/allocation-runs", methods=["POST"])
@authorize("FinOpsAnalyst", "FinOpsController")
def create_run():
    data = body()
    scope = None
    if present(data, "scope_business_unit_id"):
        scope = optional_ref("business_units", data.get("scope_business_unit_id"))
    mode = req_enum(data, "mode", MODES)
    (start_raw, start), (end_raw, end) = req_interval(data, "period_start", "period_end")

    scope_id = scope["id"] if scope else None
    for other in db.allocation_runs.values():
        if other["mode"] != mode or other["scope_business_unit_id"] != scope_id:
            continue
        if other["status"] == "CLOSED":
            continue
        if start < other["_period_end_dt"] and other["_period_start_dt"] < end:
            fail(
                "ERR_ALLOCATION_PERIOD_OVERLAP",
                "The requested period overlaps allocation run %s." % other["id"],
            )

    run = base_fields()
    run.update(
        {
            "mode": mode,
            "scope_business_unit_id": scope_id,
            "period_start": start_raw,
            "period_end": end_raw,
            "status": "DRAFT",
            "created_by_user_id": user_id(),
            "published_by_user_id": None,
            "variant_applied": None,
            "scoped_effective_cost_cents": 0,
            "total_allocated_cents": 0,
            "line_count": 0,
            "reopen_count": 0,
            "_period_start_dt": start,
            "_period_end_dt": end,
        }
    )
    db.allocation_runs[run["id"]] = run
    return serve(run, 201)


@bp.route("/finops/allocation-runs", methods=["GET"])
@authorize(*READERS)
def list_runs():
    return serve_list(
        db.allocation_runs.values(),
        {
            "mode": "mode",
            "scope_business_unit_id": "scope_business_unit_id",
            "status": "status",
        },
    )


@bp.route("/finops/allocation-runs/<run_id>", methods=["GET"])
@authorize(*READERS)
def get_run(run_id):
    return serve(lookup("allocation_runs", run_id))


# --------------------------------------------------------------------------
# shared cost pools nested under a run
# --------------------------------------------------------------------------
@bp.route("/finops/allocation-runs/<run_id>/shared-cost-pools", methods=["POST"])
@authorize("FinOpsAnalyst")
def attach_pool(run_id):
    run = lookup("allocation_runs", run_id)
    data = body()

    raw_participants = data.get("participant_business_unit_ids")
    if isinstance(raw_participants, list) and all(
        isinstance(p, str) and p.strip() != "" for p in raw_participants
    ):
        for participant_id in raw_participants:
            lookup("business_units", participant_id)

    name = req_str(data, "name")
    methodology = req_enum(data, "methodology", METHODOLOGIES)
    participants = req_str_list(data, "participant_business_unit_ids")
    if not participants:
        fail("ERR_INVALID_REQUEST", "participant_business_unit_ids must be non-empty.")
    basis = opt_enum(data, "proportional_basis", BASES, "SPEND")

    if run["status"] not in ("DRAFT", "REOPENED"):
        fail(
            "ERR_RUN_STATE_INVALID",
            "Pools may only be attached to a DRAFT or REOPENED allocation run.",
        )

    if run["scope_business_unit_id"]:
        allowed = derived.subtree_ids(run["scope_business_unit_id"])
        for participant_id in participants:
            if participant_id not in allowed:
                fail(
                    "ERR_PARTICIPANT_OUT_OF_SCOPE",
                    "Participant %s sits outside the run's scope subtree." % participant_id,
                )

    pool = base_fields()
    pool.update(
        {
            "allocation_run_id": run["id"],
            "name": name,
            "methodology": methodology,
            "proportional_basis": basis,
            "participant_business_unit_ids": participants,
            "status": "OPEN",
            "pooled_cost_cents": 0,
            "absorbed_record_count": 0,
        }
    )
    db.shared_cost_pools[pool["id"]] = pool
    return serve(pool, 201)


@bp.route("/finops/allocation-runs/<run_id>/shared-cost-pools", methods=["GET"])
@authorize("FinOpsAnalyst", "FinOpsController", "PlatformAdmin")
def list_run_pools(run_id):
    run = lookup("allocation_runs", run_id)
    pools = derived.run_pools(run["id"])
    for pool in pools:
        derived.pool_sync(pool, bump=False)
    return serve_list(pools, {"status": "status"})


# --------------------------------------------------------------------------
# compute
# --------------------------------------------------------------------------
@bp.route("/finops/allocation-runs/<run_id>/compute", methods=["POST"])
@authorize("FinOpsAnalyst")
def compute(run_id):
    run = lookup("allocation_runs", run_id)
    data = body()
    variant = req_enum(data, "variant", VARIANTS)

    status = run["status"]
    admissible = (
        (status == "DRAFT")
        or (status == "COMPUTED_PROVISIONAL" and variant == "FINAL")
        or (status == "REOPENED" and variant == "FINAL")
    )
    if not admissible:
        fail(
            "ERR_RUN_STATE_INVALID",
            "A %s run may not be computed on the %s variant." % (status, variant),
        )

    flows.compute_run(run, variant)
    return serve(run)


# --------------------------------------------------------------------------
# manual adjustments
# --------------------------------------------------------------------------
@bp.route("/finops/allocation-runs/<run_id>/manual-adjustments", methods=["POST"])
@authorize("FinOpsController")
def manual_adjustment(run_id):
    run = lookup("allocation_runs", run_id)
    data = body()
    bu = optional_ref("business_units", req_str(data, "business_unit_id"))
    expected = req_int(data, "expected_allocation_run_version")
    allocated = req_int(data, "allocated_cents")
    memo = req_str(data, "memo")

    if expected != run["version"]:
        fail(
            "ERR_STALE_VERSION",
            "expected_allocation_run_version %s does not match the run version %s."
            % (expected, run["version"]),
        )
    if run["status"] not in ("COMPUTED_PROVISIONAL", "COMPUTED_FINAL"):
        fail(
            "ERR_RUN_STATE_INVALID",
            "Manual adjustments require a computed allocation run.",
        )

    current = derived.bu_line_total(run["id"], bu["id"])
    if current + allocated < 0:
        fail(
            "ERR_ADJUSTMENT_WOULD_GO_NEGATIVE",
            "The adjustment would drive the business unit's line total below zero.",
        )

    line = flows.manual_adjustment_line(run, bu["id"], allocated, memo)
    return serve(line, 201)


# --------------------------------------------------------------------------
# publish / reopen / close
# --------------------------------------------------------------------------
@bp.route("/finops/allocation-runs/<run_id>/publish", methods=["POST"])
@authorize("FinOpsController")
def publish(run_id):
    run = lookup("allocation_runs", run_id)
    if run["status"] != "COMPUTED_FINAL" or run["variant_applied"] != "FINAL":
        fail(
            "ERR_RUN_STATE_INVALID",
            "Only a run computed on the FINAL variant may be published.",
        )
    if user_id() == run["created_by_user_id"]:
        fail(
            "ERR_SEGREGATION_OF_DUTIES",
            "The publishing user must differ from the run's creator.",
        )

    lines = derived.run_lines(run["id"])
    if run["mode"] == "CHARGEBACK":
        seen = []
        for line in lines:
            if line["business_unit_id"] in seen:
                continue
            seen.append(line["business_unit_id"])
            bu = db.business_units.get(line["business_unit_id"])
            if bu is None or not bu["chargeback_enabled"]:
                fail(
                    "ERR_BU_NOT_CHARGEBACK_ENABLED",
                    "Business unit %s is not chargeback enabled." % line["business_unit_id"],
                )

    for pool in derived.run_pools(run["id"]):
        if pool["status"] != "SEALED":
            fail("ERR_POOL_NOT_SEALED", "Shared cost pool %s is still OPEN." % pool["id"])

    flows.publish_run(run, user_id())
    return serve(run)


@bp.route("/finops/allocation-runs/<run_id>/reopen", methods=["POST"])
@authorize("FinOpsController")
def reopen(run_id):
    run = lookup("allocation_runs", run_id)
    data = body()
    req_str(data, "reason")

    if run["status"] != "PUBLISHED":
        fail("ERR_RUN_STATE_INVALID", "Only a PUBLISHED run may be reopened.")
    for invoice in derived.run_invoices(run["id"]):
        if invoice["settlement_status"] == "SETTLED":
            fail(
                "ERR_RUN_REOPEN_BLOCKED",
                "Invoice %s has already been settled." % invoice["id"],
            )
    if run["reopen_count"] >= MAX_RUN_REOPENS:
        fail("ERR_RUN_REOPEN_BLOCKED", "The run has already been reopened twice.")

    flows.reopen_run(run)
    return serve(run)


@bp.route("/finops/allocation-runs/<run_id>/close", methods=["POST"])
@authorize("FinOpsController")
def close(run_id):
    run = lookup("allocation_runs", run_id)
    if run["status"] != "PUBLISHED":
        fail("ERR_RUN_STATE_INVALID", "Only a PUBLISHED run may be closed.")

    invoices = derived.run_invoices(run["id"])
    if run["mode"] == "CHARGEBACK":
        for invoice in invoices:
            if invoice["settlement_status"] not in ("SETTLED", "WRITTEN_OFF"):
                fail(
                    "ERR_RUN_NOT_FULLY_SETTLED",
                    "Invoice %s is neither settled nor written off." % invoice["id"],
                )
    for invoice in invoices:
        for dispute in derived.invoice_disputes(invoice["id"]):
            if dispute["status"] in OPEN_DISPUTE_STATES:
                fail(
                    "ERR_RUN_NOT_FULLY_SETTLED",
                    "Dispute %s is still unresolved." % dispute["id"],
                )

    run["status"] = "CLOSED"
    touch(run)
    for bu_id in {line["business_unit_id"] for line in derived.run_lines(run["id"])}:
        derived.bu_sync_id(bu_id)
    return serve(run)
