"""PRD 3.7 -- capital programs, the equity gate and the recomputed ledger."""

from flask import Blueprint

import calc
import cascades
import envelope
import lookup
import serialize
import store
import validate
from auth import ROLE_REGIONAL_ADMINISTRATOR, guard
from errors import fail

bp = Blueprint("programs", __name__)


@bp.post("/resilience/capital-programs")
@guard(ROLE_REGIONAL_ADMINISTRATOR)
def create_program():
    body = validate.json_body()
    fiscal_year = validate.int_field(
        body, "fiscal_year", required=True, minimum=2026, maximum=2040
    )
    authorized = validate.int_field(body, "authorized_cents", required=True, minimum=1)
    equity_target = validate.int_field(
        body, "equity_target_bps", default=4000, minimum=0, maximum=10000
    )

    record = store.insert(store.programs, {
        "fiscal_year": fiscal_year,
        "authorized_cents": authorized,
        "committed_cents": 0,
        "available_cents": authorized,
        "equity_target_bps": equity_target,
        "equity_committed_cents": 0,
        "equity_achieved_bps": 0,
        "funding_posture": "OPEN",
    })
    return envelope.created(serialize.capital_program(record))


@bp.get("/resilience/capital-programs")
@guard()
def list_programs():
    rows = envelope.match(
        store.ordered(store.programs),
        fiscal_year=envelope.int_filter("fiscal_year"),
        funding_posture=envelope.str_filter("funding_posture"),
    )
    return envelope.listing(rows, serialize.capital_program)


@bp.get("/resilience/capital-programs/<program_id>")
@guard()
def get_program(program_id):
    row = lookup.need("program", program_id)
    return envelope.ok(serialize.capital_program(row))


@bp.post("/resilience/capital-programs/<program_id>/allocations")
@guard(ROLE_REGIONAL_ADMINISTRATOR)
def allocate(program_id):
    program = lookup.need("program", program_id)
    body = validate.json_body()
    project = lookup.need_ref("project", body, "project_id")
    if project is None:
        validate.bad("project_id", "is required.")
    allocated = validate.int_field(body, "allocated_cents", required=True, minimum=0)
    expected_version = validate.int_field(
        body, "expected_capital_program_version", required=True, minimum=0
    )

    # the seven guards, in exactly this order
    if project["program_status"] != "UNPROGRAMMED":
        fail("ERR_PROJECT_ALREADY_PROGRAMMED", "The project is not UNPROGRAMMED.")
    if expected_version != program["version"]:
        fail(
            "ERR_STALE_PROGRAM_VERSION",
            "expected_capital_program_version does not match the program's current version.",
        )

    links = lookup.links_of(project["id"])
    equity_share = calc.equity_benefit_share_bps(links)
    if not (
        equity_share >= int(program["equity_target_bps"])
        or bool(project["equity_waiver_granted"])
    ):
        fail("ERR_EQUITY_FLOOR_NOT_MET", "The project does not meet the equity benefit floor.")

    for link in links:
        asset = store.assets.get(link["asset_id"])
        if asset is None or asset["criticality_status"] != "RANKED":
            fail("ERR_ASSET_RANKING_REQUIRED", "Every linked lifeline asset must be RANKED.")

    if project["analysis_status"] != "BCA_CERTIFIED":
        fail("ERR_BCA_NOT_CERTIFIED", "The project's analysis is not BCA_CERTIFIED.")

    project_cost = project["total_program_cost_cents"] or 0
    if allocated > int(project_cost):
        fail(
            "ERR_ALLOCATION_EXCEEDS_PROJECT_COST",
            "allocated_cents may not exceed the project's total program cost.",
        )
    if allocated > int(program["available_cents"]):
        fail("ERR_PROGRAM_FUNDS_EXCEEDED", "allocated_cents exceeds the program's available funds.")

    analysis = lookup.certified_analysis(project["id"])
    tiers = []
    for link in links:
        asset = store.assets.get(link["asset_id"])
        if asset is not None:
            tiers.append(asset["criticality_tier"])

    project["capital_program_id"] = program["id"]
    project["allocated_cents"] = allocated
    project["program_status"] = "PROGRAMMED"
    project["equity_benefit_share_bps"] = equity_share
    project["priority_score"] = calc.priority_score(
        analysis["bcr"] if analysis else 0, tiers, equity_share
    )

    # the allocated project takes exactly one version bump even when the ledger
    # recomputation also puts it on grant hold
    cascades.recompute_program_ledger(program, skip_touch=(project["id"],))
    store.touch(program)
    store.touch(project)
    return envelope.ok(serialize.project(project))
