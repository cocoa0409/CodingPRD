"""SimulationRun endpoints (PRD 3.4): synchronous NII/EVE computation, policy
limit evaluation with breach creation, and publication into the ALCO pack."""

import store
from decimal import Decimal as _Decimal

D_ZERO = _Decimal("0")

from calc import (
    eve_projection,
    limit_applies,
    limit_is_breached,
    nii_delta_pct,
    nii_projection_cents,
    rate_deltas,
)
from envelope import list_response, object_response
from errors import ApiError
from serializers import run_json
from services import (
    active_positions,
    make_breach,
    stamp_new,
    touch,
    upsert_report_on_event,
)
from timeutil import clock
from validate import opt_num, req_enum, req_int, req_num, req_str

from routes.common import READ_ROLES, endpoint, get_or_404

CONVENTIONS = ("STATIC", "DYNAMIC")

# Pinned assumption slots and the domain each must carry.
PIN_DOMAINS = (
    ("prepayment_set_id", "PREPAYMENT"),
    ("decay_set_id", "DEPOSIT_DECAY"),
    ("beta_set_id", "DEPOSIT_BETA"),
)


@endpoint("POST", "/books/<book_id>/simulation-runs", roles=["TreasuryAnalyst"])
def create_run(ctx):
    book = get_or_404(store.books, ctx.param("book_id"))  # rung 3
    body = ctx.body
    # Rung 4: body shape - required fields, enums, DYNAMIC growth requirement,
    # and the non-optional OCC field.
    scenario_id = req_str(body, "scenario_id")
    prepayment_set_id = req_str(body, "prepayment_set_id")
    decay_set_id = req_str(body, "decay_set_id")
    beta_set_id = req_str(body, "beta_set_id")
    convention = req_enum(body, "balance_sheet_convention", CONVENTIONS)
    if convention == "DYNAMIC":
        annual_growth = req_num(body, "annual_growth_pct")
    else:
        annual_growth = opt_num(body, "annual_growth_pct", default=None)
    expected = req_int(body, "expected_book_version")
    # Rung 5: optimistic concurrency on the book version.
    if expected != book["version"]:
        raise ApiError("ERR_STALE_VERSION")
    # Rung 6: the book must be ACTIVE to host runs.
    if book["status"] != "ACTIVE":
        raise ApiError("ERR_BOOK_NOT_ACTIVE")
    # Referenced bodies must exist.
    scenario = get_or_404(store.scenarios, scenario_id)
    pinned = {}
    for field, domain in PIN_DOMAINS:
        aset = get_or_404(store.assumption_sets, body[field])
        pinned[field] = aset
    # Rung 11: cross-entity state - scenario ACTIVE; each pinned set belongs
    # to its matching domain, is APPROVED, and is free of OPEN BREACH reviews.
    if scenario["status"] != "ACTIVE":
        raise ApiError("ERR_SCENARIO_NOT_ACTIVE")
    for field, domain in PIN_DOMAINS:
        aset = pinned[field]
        if aset["domain"] != domain or aset["status"] != "APPROVED":
            raise ApiError("ERR_ASSUMPTION_NOT_APPROVED")
    for field, _domain in PIN_DOMAINS:
        aset = pinned[field]
        for review in store.backtests.values():
            if (
                review["assumption_set_id"] == aset["id"]
                and review["status"] == "OPEN"
                and review["outcome"] == "BREACH"
            ):
                raise ApiError("ERR_ASSUMPTION_UNDER_REVIEW")

    # --- Synchronous computation -------------------------------------------
    positions = active_positions(book["id"])
    delta_y1, terminal_shock = rate_deltas(scenario)
    prepay_params = pinned["prepayment_set_id"]["params"]
    decay_params = pinned["decay_set_id"]["params"]
    beta_params = pinned["beta_set_id"]["params"]

    nii_base = nii_projection_cents(
        book, positions, D_ZERO, scenario["kind"],
        prepay_params, decay_params, beta_params, convention, annual_growth,
    )
    nii_scenario = nii_projection_cents(
        book, positions, delta_y1, scenario["kind"],
        prepay_params, decay_params, beta_params, convention, annual_growth,
    )
    nii_delta = nii_delta_pct(nii_base, nii_scenario)
    eve_base, eve_scenario, eve_delta = eve_projection(book, positions, terminal_shock)

    # Policy limit evaluation on the rounded 2dp delta values.
    breached_limits = []
    for limit in store.policy_limits.values():
        if limit["book_id"] != book["id"] or limit["status"] != "ACTIVE":
            continue
        if not limit_applies(limit, scenario["kind"]):
            continue
        if limit_is_breached(limit, nii_delta, eve_delta):
            breached_limits.append(limit)
    breached_limits.sort(key=lambda lim: (lim["_created_dt"], lim["_seq"]))
    nii_hit = any(lim["metric"] == "NII_DELTA_PCT" for lim in breached_limits)
    eve_hit = any(lim["metric"] == "EVE_DELTA_PCT" for lim in breached_limits)
    if nii_hit and eve_hit:
        summary = "BOTH"
    elif nii_hit:
        summary = "NII"
    elif eve_hit:
        summary = "EVE"
    else:
        summary = "NONE"

    run = {
        "book_id": book["id"],
        "scenario_id": scenario_id,
        "prepayment_set_id": prepayment_set_id,
        "decay_set_id": decay_set_id,
        "beta_set_id": beta_set_id,
        "balance_sheet_convention": convention,
        "annual_growth_pct": annual_growth,
        "book_version_pinned": book["version"],  # OCC-pinned snapshot
        "status": "COMPLETED",
        "period_month": clock.period_month(),
        "nii_base_cents": nii_base,
        "nii_scenario_cents": nii_scenario,
        "nii_delta_pct": float(nii_delta),
        "eve_base_cents": eve_base,
        "eve_scenario_cents": eve_scenario,
        "eve_delta_pct": float(eve_delta),
        "breach_summary": summary,
    }
    stamp_new(run)
    store.runs[run["id"]] = run

    # Every breached active limit opens a LimitBreach in OPEN status.
    for limit in breached_limits:
        observed = run["nii_delta_pct"] if limit["metric"] == "NII_DELTA_PCT" else run["eve_delta_pct"]
        make_breach(
            book["id"], run["id"], limit["id"], limit["metric"],
            observed, limit["threshold_pct"],
        )

    # Run creation advances the book version (PRD 2.8) - after the snapshot.
    touch(book)
    return object_response(run_json(run), 201)


@endpoint("GET", "/simulation-runs", roles=READ_ROLES)
def list_runs(ctx):
    rows = list(store.runs.values())
    for field in (
        "book_id", "scenario_id", "prepayment_set_id",
        "decay_set_id", "beta_set_id", "status",
    ):
        value = ctx.args.get(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    return list_response(rows, ctx.args, run_json)


@endpoint("GET", "/simulation-runs/<run_id>", roles=READ_ROLES)
def get_run(ctx):
    run = get_or_404(store.runs, ctx.param("run_id"))
    return object_response(run_json(run))


@endpoint("POST", "/simulation-runs/<run_id>/publish", roles=["TreasuryAnalyst"])
def publish_run(ctx):
    run = get_or_404(store.runs, ctx.param("run_id"))
    if run["status"] != "COMPLETED":  # rung 6
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    run["status"] = "PUBLISHED"
    touch(run)
    # Upsert the period ALCO report, recompute aggregates, and auto-revert a
    # SUBMITTED report to DRAFT.
    upsert_report_on_event(run["book_id"], run["period_month"])
    return object_response(run_json(run))
