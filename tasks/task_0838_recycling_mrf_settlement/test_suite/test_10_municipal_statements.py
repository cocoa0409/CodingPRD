"""Municipal statements: finalize aggregation, OCC on create, supersede."""
from test_helpers import validate_success, validate_error, ApiErrorId, TEST_USERS
from test_helpers.fixtures import (
    create_municipality, create_sort_line, create_load, audit_load, close_load,
    create_statement, finalize_statement, get_municipality,
)

CLERK = TEST_USERS["settlement_clerk_headers"]


def test_finalize_already_finalized_statement_rejected(api):
    """PRD §3.8: "Finalizing a statement is permitted only from `OPEN`, else
    `ERR_STATEMENT_NOT_OPEN`."

    Design: Corner/state_machines/corner_finalize_statement_not_open_rejected
    """
    muni = create_municipality(api)
    stmt = create_statement(api, muni["id"], muni["version"])
    finalize_statement(api, stmt["id"])
    resp = api.finalize_municipal_statement(stmt["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_STATEMENT_NOT_OPEN.value)


def test_statement_totals_penalty_only(api):
    """PRD §3.8: "`total_penalty_cents` is the sum of the magnitudes of `PENALTY`
    postings (each stored positive). Finally `net_payable_cents` is
    `total_revenue_share_cents` plus `total_rebate_cents` minus
    `total_penalty_cents`."

    Design: Corner/calculations/corner_statement_totals_penalty_only
    """
    muni = create_municipality(api, revenue_share_pct=0.50)
    line = create_sort_line(api)
    load = create_load(api, muni["id"], line["id"], gross_tons=20, tare_tons=0)
    audit_load(api, load["id"], 15.0, [{"commodity": "OCC", "pct": 85}])
    close_load(api, load["id"], residual_tons=3.0)  # penalty -9000 posted
    current = get_municipality(api, muni["id"])
    stmt = create_statement(api, muni["id"], current["version"],
                            period_start="2026-03-01T00:00:00Z",
                            period_end="2026-04-01T00:00:00Z")
    finalized = finalize_statement(api, stmt["id"])
    assert finalized["total_penalty_cents"] == 9000
    assert finalized["total_revenue_share_cents"] == 0
    assert finalized["net_payable_cents"] == -9000


def test_stale_municipality_version_on_second_create_rejected(api):
    """PRD §2.7: "Before creating the statement, the server compares
    `expected_municipality_version` to the municipality's current `version`; if they
    differ, the client's view is stale ... and the create is rejected with
    `ERR_STALE_MUNICIPALITY_VERSION` at HTTP 412."

    Design: Corner/cross_cutting/corner_occ_stale_municipality_version_on_statement_create
    """
    muni = create_municipality(api, revenue_share_pct=0.50)
    create_statement(api, muni["id"], muni["version"])  # advances version to 2
    resp = api.create_municipal_statement(
        {"municipality_id": muni["id"], "period_start": "2026-03-01T00:00:00Z",
         "period_end": "2026-04-01T00:00:00Z",
         "expected_municipality_version": muni["version"]}, CLERK)
    validate_error(resp, ApiErrorId.ERR_STALE_MUNICIPALITY_VERSION.value)


def test_second_statement_supersedes_prior_open(api):
    """PRD §3.8: "a successful create supersedes the municipality's prior `OPEN`
    statement — driving that earlier statement from `OPEN` to `SUPERSEDED` — and
    advances the municipality's `version` by one."

    Design: Corner/cross_cutting/corner_statement_create_supersedes_prior_open
    """
    muni = create_municipality(api, revenue_share_pct=0.50)
    stmt1 = create_statement(api, muni["id"], muni["version"])
    current = get_municipality(api, muni["id"])
    stmt2 = create_statement(api, muni["id"], current["version"])
    first = validate_success(api.get_municipal_statement(stmt1["id"], CLERK))
    second = validate_success(api.get_municipal_statement(stmt2["id"], CLERK))
    assert first["status"] == "SUPERSEDED"
    assert second["status"] == "OPEN"
