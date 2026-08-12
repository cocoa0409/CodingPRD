"""Optimistic concurrency control on the three version-guarded write
endpoints: stale expected versions are rejected with 412, fresh ones proceed."""

import test_helpers as fx
from test_helpers import (
    PM,
    ApiErrorId,
    create_assessment_payload,
    create_quote_payload,
    create_trade_in_offer_payload,
    make_assessor_headers,
    validate_error,
    validate_success,
)

ASSESSOR_1 = "assessor-1"


def test_occ_assessment_create_stale_version(api):
    """PRD §2.6: "Creating an assessment via `POST /api/machines/{id}/assessments` requires the request body to carry `expected_machine_version` equal to the target machine's current `version`. If another write has advanced the machine's version since the client last observed it, the create is rejected with `ERR_STALE_MACHINE_VERSION` (HTTP 412)."
    PRD §3.2: "First, any prior assessment of the same machine sitting in `DRAFT`, `SUBMITTED`, or `RETURNED` is moved to the terminal `SUPERSEDED`, so at most one non-terminal assessment exists per machine at a time."
    PRD §3.2: "Second, the machine's `version` increments by one; on the very first filing for a machine, the machine additionally transitions from `REGISTERED` to `UNDER_ASSESSMENT` — subsequent filings leave the machine's `status` untouched while still bumping its version."

    Design: Corner/cross_cutting_layers/occ_assessment_create_stale_version
    """
    customer = fx.create_customer()
    machine = fx.create_machine(customer["id"])
    observed_version = machine["version"]

    first = fx.create_assessment(machine["id"], assessor_id=ASSESSOR_1, scope_notes="first")
    assert first["status"] == "DRAFT"

    machine_after_first = fx.get_machine(machine["id"])
    assert machine_after_first["version"] == observed_version + 1

    stale = api.create_assessment(
        machine["id"],
        create_assessment_payload(observed_version, scope_notes="stale retry"),
        make_assessor_headers(ASSESSOR_1),
    )
    validate_error(stale, ApiErrorId.ERR_STALE_MACHINE_VERSION.value)

    fresh = api.create_assessment(
        machine["id"],
        create_assessment_payload(machine_after_first["version"], scope_notes="fresh retry"),
        make_assessor_headers(ASSESSOR_1),
    )
    second = validate_success(fresh, 201)
    assert second["status"] == "DRAFT"

    first_after = validate_success(api.get_assessment(first["id"], PM), 200)
    assert first_after["status"] == "SUPERSEDED"


def test_occ_trade_in_offer_create_stale_version(api):
    """PRD §2.6: "Creating a trade-in offer via `POST /api/machines/{id}/trade-in-offers` likewise requires `expected_machine_version` matching the machine's current `version`, with a mismatch rejected as `ERR_STALE_MACHINE_VERSION` (HTTP 412), because offer creation supersedes the machine's prior `OFFERED` offer and increments `Machine.version`."
    PRD §3.9: "Creation also supersedes the machine's prior offer: any existing `OFFERED` offer of the same machine moves to the terminal `SUPERSEDED`, and the machine's `version` increments by one."

    Design: Corner/cross_cutting_layers/occ_trade_in_offer_create_stale_version
    """
    customer = fx.create_customer()
    machine = fx.create_machine(
        customer["id"], machine_type="GRINDER", year_of_manufacture=2011, spindle_hours=85_000
    )
    observed_version = machine["version"]

    first = fx.create_offer(machine["id"], valuation_variant="MARKET_COMPARABLE")
    assert first["status"] == "OFFERED"

    stale = api.create_trade_in_offer(
        machine["id"],
        create_trade_in_offer_payload(observed_version, valuation_variant="COST_APPROACH"),
        PM,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_MACHINE_VERSION.value)

    fresh_version = fx.get_machine(machine["id"])["version"]
    assert fresh_version == observed_version + 1
    second = validate_success(
        api.create_trade_in_offer(
            machine["id"],
            create_trade_in_offer_payload(fresh_version, valuation_variant="COST_APPROACH"),
            PM,
        ),
        201,
    )
    assert second["status"] == "OFFERED"

    first_after = validate_success(api.get_trade_in_offer(first["id"], PM), 200)
    assert first_after["status"] == "SUPERSEDED"


def test_occ_quote_recompute_stale_version(api):
    """PRD §2.6: "Recomputing a quote via `POST /api/projects/{id}/quote` requires `expected_project_version` matching the project's current `version`. Each recomputation produces a new quote revision that supersedes the prior one and increments `RebuildProject.version`; a recompute carrying a previously observed version is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412), preventing the client from overwriting a quote it has not observed."
    PRD §3.3: "Every computation increments `quote_revision` by one, clears `quote_stale` to `false`, snapshots all six money fields, and increments the project's `version` by one."

    Design: Corner/cross_cutting_layers/occ_quote_recompute_stale_version
    """
    ctx = fx.setup_project_decided()
    project_id = ctx.project["id"]
    observed_version = fx.get_project(project_id)["version"]

    first = validate_success(
        api.compute_quote(project_id, create_quote_payload(observed_version), PM), 200
    )
    assert first["quote_revision"] == 1

    stale = api.compute_quote(project_id, create_quote_payload(observed_version), PM)
    validate_error(stale, ApiErrorId.ERR_STALE_PROJECT_VERSION.value)

    fresh_version = fx.get_project(project_id)["version"]
    assert fresh_version == observed_version + 1
    second = validate_success(
        api.compute_quote(project_id, create_quote_payload(fresh_version), PM), 200
    )
    assert second["quote_revision"] == 2
    assert second["quote_stale"] is False
