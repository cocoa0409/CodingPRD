"""Endpoint surface: reads, nested listings, bodyless actions and body FKs.

The supplier surface is create plus read plus a nested child listing, approval
is a bodyless action sub-resource, a body identifier is screened on its own rung
after the path, the campaign read is computed rather than stored, and starting a
campaign is conditional on the state securement left behind.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_INVALID_RUN_STATE,
    ERR_INVALID_WINDOW_STATE,
    ERR_NO_FEEDSTOCK_ALLOCATED,
    ERR_RUN_NOT_FOUND,
)
from test_helpers.assertions import assert_fields_null, assert_mass, assert_one_decimal
from test_helpers.test_users import OFFICER_A_HEADERS, OPERATOR_HEADERS, TRADER_HEADERS
from test_helpers.types import (
    DOC_MASS_BALANCE_STATEMENT,
    DOC_ORIGIN_ATTESTATION,
    FEEDSTOCK_UCO,
    RUN_PLANNED,
    UNIT_IDLE,
    WINDOW_APPROVED,
    WINDOW_PLANNED,
)


def test_a_supplier_reads_back_with_its_documents_under_a_nested_listing(api):
    """PRD §3.1: "The registration payload carries the supplier's `legal_name`, which must be a
    non-blank string of 1 to 120 characters; a `country_code` naming the ISO-3166 alpha-2 country
    of the collection or origin point, which must be exactly two uppercase letters"
    PRD §3.1: "That count is the number of **distinct** `doc_type` values among the supplier's
    documents whose `valid_until` is strictly after the current logical clock."
    PRD §3.1: "Documents may be listed for a supplier and optionally narrowed by `doc_type`."

    Design: Corner/endpoints/standard_crud_supplier_create_read_and_child_listing
    """
    supplier = fx.documented_supplier(
        api,
        doc_types=(DOC_ORIGIN_ATTESTATION, DOC_MASS_BALANCE_STATEMENT),
        feedstock_types=[FEEDSTOCK_UCO],
    )

    read = validate_success(api.get_supplier(supplier["id"], OFFICER_A_HEADERS))
    assert read["id"] == supplier["id"]
    assert read["legal_name"] == "Gulf Coast Renderers LLC", f"got {read['legal_name']}"
    assert read["country_code"] == "US", f"got {read['country_code']}"
    assert read["feedstock_types"] == [FEEDSTOCK_UCO], f"got {read['feedstock_types']}"
    assert read["dd_document_type_count"] == 2, f"got {read['dd_document_type_count']}"

    response = api.list_traceability_documents(
        supplier["id"], OFFICER_A_HEADERS, {"limit": 10, "offset": 0}
    )
    docs, meta = validate_paginated(response)
    assert response.json()["response_type"] == "array", response.json()["response_type"]
    assert meta["total_count"] == 2, f"got {meta['total_count']}"
    assert meta["has_more"] is False
    assert {row["doc_type"] for row in docs} == {
        DOC_ORIGIN_ATTESTATION,
        DOC_MASS_BALANCE_STATEMENT,
    }

    narrowed, narrowed_meta = validate_paginated(
        api.list_traceability_documents(
            supplier["id"], OFFICER_A_HEADERS, {"doc_type": DOC_ORIGIN_ATTESTATION}
        )
    )
    assert narrowed_meta["total_count"] == 1, f"got {narrowed_meta['total_count']}"
    assert narrowed[0]["doc_type"] == DOC_ORIGIN_ATTESTATION


def test_the_bodyless_approval_moves_the_window_and_nothing_else(api):
    """PRD §3.3: "A `PlantOperator` approves a `PLANNED` window, moving it `PLANNED → APPROVED`
    and bumping its `version`; approval is refused when any campaign on that unit whose status is
    `PLANNED`, `HYDROGEN_SECURED` or `RUNNING` has a campaign interval that intersects the
    window's interval, both compared as half-open intervals."
    PRD §2.7: "The target resource named in the path is in a state that permits the requested
    transition"

    Design: Corner/endpoints/action_endpoint_turnaround_approval_transitions_the_window
    """
    unit = fx.make_unit(api)
    window = fx.make_window(api, unit["id"])
    assert window["status"] == WINDOW_PLANNED, f"got {window['status']}"
    assert window["version"] == 1, f"got {window['version']}"

    approved = validate_success(api.approve_window(window["id"], OPERATOR_HEADERS))
    assert approved["status"] == WINDOW_APPROVED, f"got {approved['status']}"
    assert approved["version"] == 2, f"got {approved['version']}"
    assert approved["unit_id"] == unit["id"]

    untouched = validate_success(api.get_unit(unit["id"], OPERATOR_HEADERS))
    assert untouched["status"] == UNIT_IDLE, f"got {untouched['status']}"
    assert untouched["version"] == 1, (
        f"approving a window writes no unit row, got version {untouched['version']}"
    )

    validate_error(api.approve_window(window["id"], OPERATOR_HEADERS), ERR_INVALID_WINDOW_STATE)

    windows, _ = validate_paginated(api.list_turnaround_windows(unit["id"], OPERATOR_HEADERS))
    assert len(windows) == 1, f"got {len(windows)}"
    assert windows[0]["version"] == 2, f"the refusal bumped nothing, got {windows[0]['version']}"


def test_a_fabricated_run_id_in_the_body_is_screened_after_the_path(api):
    """PRD §2.7: "Every identifier supplied in the request body resolves to an existing row —
    `supplier_id`, `lot_id`, `unit_id`, `catalyst_charge_id`, `run_id`, `batch_id` and
    `pathway_id` are screened here, reporting `ERR_SUPPLIER_NOT_FOUND`, `ERR_LOT_NOT_FOUND`,
    `ERR_UNIT_NOT_FOUND`, `ERR_CATALYST_CHARGE_NOT_FOUND`, `ERR_RUN_NOT_FOUND`,
    `ERR_BATCH_NOT_FOUND` or `ERR_PATHWAY_NOT_FOUND` as appropriate, all 404."
    PRD §2.7: "This rung guards lot creation, campaign creation, allocation creation, hydrogen
    nomination creation, pathway registration creation and credit-block creation."

    Design: Corner/endpoints/nomination_with_unknown_run_id_returns_not_found
    """
    contract = fx.make_contract(api)

    validate_error(
        api.create_nomination(
            contract["id"],
            f.nomination_payload(
                NON_EXISTENT_UUID,
                start_at="2026-09-01T00:00:00Z",
                end_at="2026-09-05T00:00:00Z",
                kg_per_day=2600.0,
            ),
            OPERATOR_HEADERS,
        ),
        ERR_RUN_NOT_FOUND,
        404,
    )

    _, meta = validate_paginated(
        api.list_contract_nominations(contract["id"], OPERATOR_HEADERS)
    )
    assert meta["total_count"] == 0, f"got {meta['total_count']}"

    refreshed = validate_success(api.get_hydrogen_contract(contract["id"], TRADER_HEADERS))
    assert_one_decimal(refreshed["peak_committed_kg_per_day"], 0.0, "peak_committed_kg_per_day")


def test_reading_a_campaign_returns_the_blend_and_hydrogen_it_derives(api):
    """PRD §3.5: "Otherwise, for each counted line, multiply the line's `mass_mt` by the sum of its
    lot's `attested_ci_gco2e_per_mj` and a pretreatment carbon adder chosen by that lot's own
    `pretreatment_tier` — 0.00 for `NONE`, 1.50 for `LIGHT`, 4.00 for `HEAVY`."
    PRD §3.5: "The requirement is then the rounded daily feed rate multiplied by the unrounded
    weighted hydrogen intensity, multiplied by one plus twelve hundredths of the campaign's
    `target_saf_share_pct` expressed as a fraction — that is, aviation-fuel severity adds 0.12 of
    the SAF share, so a campaign targeting 50 percent SAF carries a 6 percent hydrogen uplift —
    with the final figure rounded half up to 1 decimal place."

    Design: Corner/endpoints/computed_read_processing_run_exposes_derived_blend_and_hydrogen
    """
    ctx = fx.baseline_campaign(api, target_saf_share_pct=10.00, secure=False)

    run = validate_success(api.get_processing_run(ctx["run"]["id"], OFFICER_A_HEADERS))
    assert run["run_days"] == 5, f"got {run['run_days']}"
    assert_mass(run["reserved_mass_mt"], 400.000, "reserved_mass_mt")
    assert run["blend_ci_gco2e_per_mj"] == 32.50, f"got {run['blend_ci_gco2e_per_mj']}"
    assert_one_decimal(run["required_h2_kg_per_day"], 2590.7, "required_h2_kg_per_day")
    assert run["version"] == 2, f"creation plus one allocation, got {run['version']}"

    response = api.list_processing_runs(
        OFFICER_A_HEADERS,
        {"unit_id": ctx["unit"]["id"], "status": RUN_PLANNED, "limit": 10, "offset": 0},
    )
    rows, meta = validate_paginated(response)
    assert response.json()["response_type"] == "array", response.json()["response_type"]
    assert meta["total_count"] == 1, f"got {meta['total_count']}"
    assert rows[0]["id"] == ctx["run"]["id"]


def test_a_planned_campaign_refuses_the_start_and_then_the_securement(api):
    """PRD §3.6: "A `PlantOperator` may start a campaign only when it is `HYDROGEN_SECURED`, the
    unit is `IDLE`, the cited catalyst charge is still `ACTIVE`, the current logical clock is at
    or after the campaign's `window_start`, and no turnaround window on that unit is
    `IN_PROGRESS`."
    PRD §3.6: "A unit that is `RUNNING` or `DOWN_TURNAROUND` yields `ERR_INVALID_UNIT_STATE`; a
    charge that has decayed to `SPENT` since securement yields `ERR_CATALYST_NOT_ACTIVE`; a
    campaign still `PLANNED` yields `ERR_INVALID_RUN_STATE`."
    PRD §3.5: "the campaign must hold at least one allocation at `RESERVED`, a zero-cardinality
    guard checked ahead of any mass threshold and reported as `ERR_NO_FEEDSTOCK_ALLOCATED`"

    Design: Corner/endpoints/conditional_action_run_start_before_securement_is_rejected
    """
    plant = fx.commissioned_unit(api)
    run = fx.make_run(
        api, plant["unit"]["id"], plant["charge"]["id"], target_saf_share_pct=0.00
    )
    fx.move_clock(api, "2026-09-01T00:00:00Z")

    validate_error(api.start_run(run["id"], OPERATOR_HEADERS), ERR_INVALID_RUN_STATE)

    still_planned = validate_success(api.get_processing_run(run["id"], OPERATOR_HEADERS))
    assert still_planned["status"] == RUN_PLANNED, f"got {still_planned['status']}"

    idle = validate_success(api.get_unit(plant["unit"]["id"], OPERATOR_HEADERS))
    assert idle["status"] == UNIT_IDLE, f"got {idle['status']}"

    validate_error(api.secure_hydrogen(run["id"], OPERATOR_HEADERS), ERR_NO_FEEDSTOCK_ALLOCATED)

    unfed = validate_success(api.get_processing_run(run["id"], OPERATOR_HEADERS))
    assert unfed["status"] == RUN_PLANNED, f"got {unfed['status']}"
    assert_fields_null(unfed, "blend_ci_gco2e_per_mj", "required_h2_kg_per_day")
