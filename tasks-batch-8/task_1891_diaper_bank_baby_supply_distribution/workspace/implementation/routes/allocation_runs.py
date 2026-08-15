"""Allocation run endpoints: the monthly waterfall (PRD §3.4)."""

from db import store, base_fields, touch, now, current_month
from errors import (ERR_NOT_FOUND, ERR_DUPLICATE_PERIOD, ERR_PERIOD_IN_PAST,
                    ERR_VALIDATION, ERR_RUN_NOT_DRAFT, ERR_RUN_NOT_COMPUTED,
                    ERR_RUN_NOT_PUBLISHED, ERR_INSUFFICIENT_STOCK, raise_err)
from middleware import authenticate, require_role
from response import success_object, get_body, paginate
from serialize import run_json, line_json
from services.calc import compute_allocation_run
from validate import parse_period
from . import make_blueprint

bp = make_blueprint("allocation_runs")

READ_ROLES = ["BankAdmin", "AgencyCoordinator"]
VARIANTS = ["NEED_WEIGHTED", "EQUAL_SPLIT"]


def _get_run_or_404(run_id):
    r = store.allocation_runs.get(run_id)
    if r is None:
        raise_err(ERR_NOT_FOUND, "Allocation run not found.")
    return r


def _run_lines(run_id):
    return [ln for ln in store.allocation_lines.values()
            if ln["allocation_run_id"] == run_id]


@bp.route("/allocation-runs", methods=["POST"])
def create_run():
    _, role = authenticate()
    require_role(role, ["BankAdmin"])
    body = get_body()
    year, month = parse_period(body.get("period"), "period")
    period = "%04d-%02d" % (year, month)
    # Uniqueness (category 6) then temporal (category 7) then the rest (10).
    if any(r["period"] == period for r in store.allocation_runs.values()):
        raise_err(ERR_DUPLICATE_PERIOD, "An allocation run already exists for %s." % period)
    cy, cm = current_month().split("-")
    if (year, month) < (int(cy), int(cm)):
        raise_err(ERR_PERIOD_IN_PAST,
                  "period must not be earlier than the current month.")
    variant = body.get("formula_variant", "NEED_WEIGHTED")
    if variant is None:
        variant = "NEED_WEIGHTED"
    if variant not in VARIANTS:
        raise_err(ERR_VALIDATION, "formula_variant must be one of %s." % VARIANTS)
    r = base_fields()
    r.update({
        "period": period,
        "formula_variant": variant,
        "status": "DRAFT",
        "computed_at": None,
        "published_at": None,
    })
    store.allocation_runs[r["id"]] = r
    return success_object(run_json(r), status=201)


@bp.route("/allocation-runs/<run_id>", methods=["GET"])
def get_run(run_id):
    _, role = authenticate()
    require_role(role, READ_ROLES)
    return success_object(run_json(_get_run_or_404(run_id)))


@bp.route("/allocation-runs/<run_id>/lines", methods=["GET"])
def list_run_lines(run_id):
    _, role = authenticate()
    require_role(role, READ_ROLES)
    run = _get_run_or_404(run_id)
    lines = _run_lines(run["id"])

    def sort_key(ln):
        a = store.partner_agencies.get(ln["agency_id"])
        csm = a["children_served_monthly"] if a else 0
        created = a["created_at"] if a else ln["created_at"]
        # size_code ASC, children_served_monthly DESC, agency created_at ASC
        return (ln["size_code"], -csm, created)

    lines.sort(key=sort_key)
    return paginate([line_json(ln) for ln in lines])


@bp.route("/allocation-runs/<run_id>/compute", methods=["POST"])
def compute_run(run_id):
    _, role = authenticate()
    require_role(role, ["BankAdmin"])
    run = _get_run_or_404(run_id)
    if run["status"] != "DRAFT":
        raise_err(ERR_RUN_NOT_DRAFT, "Only a DRAFT run can be computed.")
    compute_allocation_run(run)
    run["computed_at"] = now()
    touch(run)
    return success_object(run_json(run))


@bp.route("/allocation-runs/<run_id>/publish", methods=["POST"])
def publish_run(run_id):
    _, role = authenticate()
    require_role(role, ["BankAdmin"])
    run = _get_run_or_404(run_id)
    if run["status"] != "DRAFT":
        raise_err(ERR_RUN_NOT_DRAFT, "Only a DRAFT run can be published.")
    if run["computed_at"] is None:
        raise_err(ERR_RUN_NOT_COMPUTED,
                  "Run must be computed before it can be published.")
    lines = _run_lines(run["id"])
    inv = store.inventory
    # Final stock gate: per size, allocated total must not exceed on_hand.
    per_size = {}
    for ln in lines:
        per_size[ln["size_code"]] = per_size.get(ln["size_code"], 0) + ln["allocated_units"]
    if inv is not None:
        for size, total in per_size.items():
            if total > inv["sizes"][size]["on_hand_units"]:
                raise_err(ERR_INSUFFICIENT_STOCK,
                          "Allocated total for %s exceeds on-hand stock." % size)
    elif per_size:
        raise_err(ERR_INSUFFICIENT_STOCK, "Inventory has not been initialized.")
    for ln in lines:
        ln["status"] = "ALLOCATED"
        touch(ln)
    if inv is not None:
        for size, total in per_size.items():
            inv["sizes"][size]["reserved_units"] += total
        touch(inv)
    run["status"] = "PUBLISHED"
    run["published_at"] = now()
    touch(run)
    return success_object(run_json(run))


@bp.route("/allocation-runs/<run_id>/finalize", methods=["POST"])
def finalize_run(run_id):
    _, role = authenticate()
    require_role(role, ["BankAdmin"])
    run = _get_run_or_404(run_id)
    if run["status"] != "PUBLISHED":
        raise_err(ERR_RUN_NOT_PUBLISHED, "Only a PUBLISHED run can be finalized.")
    inv = store.inventory
    for ln in _run_lines(run["id"]):
        if ln["status"] in ("ALLOCATED", "PARTIALLY_FULFILLED"):
            released = ln["allocated_units"] - ln["fulfilled_units"]
            ln["released_units"] = released
            ln["status"] = "RELEASED"
            touch(ln)
            if inv is not None:
                inv["sizes"][ln["size_code"]]["reserved_units"] -= released
    run["status"] = "FINALIZED"
    touch(run)
    if inv is not None:
        touch(inv)
    return success_object(run_json(run))


@bp.route("/allocation-runs/<run_id>/retract", methods=["POST"])
def retract_run(run_id):
    _, role = authenticate()
    require_role(role, ["BankAdmin"])
    run = _get_run_or_404(run_id)
    if run["status"] != "PUBLISHED":
        raise_err(ERR_RUN_NOT_PUBLISHED, "Only a PUBLISHED run can be retracted.")
    lines = _run_lines(run["id"])
    if any(ln["fulfilled_units"] > 0 for ln in lines):
        raise_err(ERR_RUN_NOT_PUBLISHED,
                  "A run with consumption cannot be retracted.")
    inv = store.inventory
    per_size = {}
    for ln in lines:
        per_size[ln["size_code"]] = per_size.get(ln["size_code"], 0) + ln["allocated_units"]
    for ln in lines:
        ln["status"] = "PROJECTED"
        touch(ln)
    if inv is not None:
        for size, total in per_size.items():
            inv["sizes"][size]["reserved_units"] -= total
        touch(inv)
    run["status"] = "DRAFT"
    run["published_at"] = None
    touch(run)
    return success_object(run_json(run))
