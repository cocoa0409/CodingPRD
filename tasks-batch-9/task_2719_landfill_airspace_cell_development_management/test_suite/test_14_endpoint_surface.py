"""Breadth over the endpoint surface: the wellfield reads, the posture action, certification."""
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import fixtures
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_amount, assert_common_fields
from test_helpers.factories import gas_well_payload
from test_helpers.test_users import TEST_USERS

PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]
ENV_MANAGER = TEST_USERS["environmental_manager_headers"]
FINANCE_FILER = TEST_USERS["finance_filer_headers"]
FINANCE_CERTIFIER = TEST_USERS["finance_certifier_headers"]

FIRST_CELL = {
    "cell_code": "C-1",
    "design_airspace_cy": 1000000,
    "design_area_sf": 120001,
    "liner_type": "DOUBLE_COMPOSITE",
}
SECOND_CELL = {
    "cell_code": "C-2",
    "design_airspace_cy": 200,
    "design_area_sf": 45001,
    "liner_type": "DOUBLE_COMPOSITE",
}


def _site_with_two_design_cells(**landfill_overrides):
    landfill = fixtures.create_landfill(**landfill_overrides)
    first = fixtures.create_cell(landfill["id"], **FIRST_CELL)
    second = fixtures.create_cell(landfill["id"], **SECOND_CELL)
    return landfill, first, second


def test_a_drilled_well_reads_back_by_id_by_filter_and_through_its_cell():
    """One row, three routes, and the sibling cell's sub-resource stays empty.

    PRD: "The four sub-resource listings — a landfill's cells, a cell's liner packages, a
    cell's gas wells, an operating day's waste loads and an agreement's leachate shipments —
    accept the same `limit` and `offset` plus the state filter appropriate to the child
    resource."

    Design: Corner/endpoints/gas_well_crud_surface_reads_back_what_the_writes_stored
    """
    _landfill, first, second = _site_with_two_design_cells()

    w1 = validate_success(
        api_client.create_gas_well(
            gas_well_payload(first["id"], well_code="W-1", depth_ft=85), ENV_MANAGER
        ),
        201,
    )
    w2 = validate_success(
        api_client.create_gas_well(
            gas_well_payload(first["id"], well_code="W-2", depth_ft=90), ENV_MANAGER
        ),
        201,
    )

    for well in (w1, w2):
        assert well["status"] == "DRILLED"
        assert well["last_tuned_at"] is None
        assert_common_fields(well, expected_version=1)
    assert_amount(w1["depth_ft"], 85, "well depth")

    by_id = get_success_data(api_client.get_gas_well(w1["id"], ENV_MANAGER))
    assert by_id["well_code"] == "W-1"
    assert by_id["cell_id"] == first["id"]

    rows, meta = validate_paginated(
        api_client.list_gas_wells(ENV_MANAGER, {"cell_id": first["id"], "limit": 10, "offset": 0})
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {w1["id"], w2["id"]}

    sibling_rows, sibling_meta = validate_paginated(
        api_client.list_cell_gas_wells(second["id"], ENV_MANAGER)
    )
    assert sibling_meta["total_count"] == 0
    assert sibling_rows == []


def test_a_well_code_collides_across_the_cells_of_one_site_only():
    """The wellfield designation is unique site-wide, not cell-wide.

    PRD: "An `EnvironmentalManager` records a new extraction well by naming the `cell_id` it is
    drilled into, its `well_code` wellfield designation (1 to 20 characters, unique across
    every cell of the owning landfill — a collision anywhere on the site is refused with
    `ERR_DUPLICATE_WELL_CODE`), and its drilled `depth_ft` in feet, which must be greater than
    zero."

    Design: Corner/endpoints/gas_well_crud_surface_reads_back_what_the_writes_stored
    """
    _landfill, first, second = _site_with_two_design_cells()
    fixtures.drill_gas_well(first["id"], well_code="W-1", depth_ft=85)

    validate_error(
        api_client.create_gas_well(
            gas_well_payload(second["id"], well_code="W-1", depth_ft=70), ENV_MANAGER
        ),
        ApiErrorId.ERR_DUPLICATE_WELL_CODE.value,
        409,
    )

    other_site, other_cell, _spare = _site_with_two_design_cells(
        name="Eastbank MSW", permit_number="MSW-9902"
    )
    elsewhere = validate_success(
        api_client.create_gas_well(
            gas_well_payload(other_cell["id"], well_code="W-1", depth_ft=70), ENV_MANAGER
        ),
        201,
    )
    assert elsewhere["well_code"] == "W-1"
    assert elsewhere["cell_id"] == other_cell["id"]
    _rows, meta = validate_paginated(
        api_client.list_cell_gas_wells(second["id"], ENV_MANAGER)
    )
    assert meta["total_count"] == 0, "the refused well must not have been stored"
    assert other_site["id"] != _landfill["id"]


def test_the_site_cannot_be_retired_while_a_cell_is_still_in_flight():
    """One UNDER_CONSTRUCTION cell blocks the administrative close outright.

    PRD: "It requires that the site is not already `CLOSED`, and that every cell of the site
    has reached `CLOSED`, `REJECTED` or has never left `DESIGN`; a cell anywhere in between
    means construction or filling is still in flight and the move is refused with
    `ERR_INVALID_STATE_TRANSITION`."

    Design: Corner/endpoints/the_operating_status_action_closes_the_site_and_then_locks_it
    """
    landfill, _first, second = _site_with_two_design_cells()
    fixtures.begin_construction(landfill["id"], second["id"])

    validate_error(
        api_client.set_operating_status(
            landfill["id"], {"operating_status": "CLOSED"}, PLATFORM_ADMIN
        ),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        409,
    )

    site = fixtures.read_landfill(landfill["id"])
    assert site["operating_status"] == "OPEN"
    _rows, meta = validate_paginated(
        api_client.list_cells(
            PLATFORM_ADMIN, {"landfill_id": landfill["id"], "status": "UNDER_CONSTRUCTION"}
        )
    )
    assert meta["total_count"] == 1, "the refused close changed nothing"


def test_the_same_endpoint_still_accepts_the_open_edge_from_open():
    """The body value picks the edge, and the lift-a-restriction edge is legal from OPEN.

    PRD: "The first lifts a restriction back to normal operation, taking a site from
    `RESTRICTED_AIRSPACE` to `OPEN`; it is also the way out of `SUSPENDED_NO_AIRSPACE` and
    `SUSPENDED_FINANCIAL`, so the request is accepted when the site currently sits in any of
    `OPEN`, `RESTRICTED_AIRSPACE`, `SUSPENDED_NO_AIRSPACE` or `SUSPENDED_FINANCIAL`."

    Design: Corner/endpoints/the_operating_status_action_closes_the_site_and_then_locks_it
    """
    landfill, _first, second = _site_with_two_design_cells()
    fixtures.begin_construction(landfill["id"], second["id"])
    before = fixtures.read_landfill(landfill["id"])

    reopened = validate_success(
        api_client.set_operating_status(
            landfill["id"], {"operating_status": "OPEN"}, PLATFORM_ADMIN
        )
    )

    assert reopened["operating_status"] == "OPEN"
    assert int(reopened["version"]) == int(before["version"]) + 1

    validate_error(
        api_client.set_operating_status(
            landfill["id"], {"operating_status": "CLOSED"}, PLATFORM_ADMIN
        ),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        409,
    )
    after = fixtures.read_landfill(landfill["id"])
    assert after["operating_status"] == "OPEN"
    assert int(after["version"]) == int(reopened["version"])


def test_retiring_a_site_whose_cells_never_left_design_is_terminal():
    """The close is taken once and the same endpoint then refuses to take it again.

    PRD: "On success the posture becomes `CLOSED` and the landfill's `version` is incremented
    by 1."

    Design: Corner/endpoints/the_operating_status_action_closes_the_site_and_then_locks_it
    """
    landfill, _first, _second = _site_with_two_design_cells()
    before = fixtures.read_landfill(landfill["id"])

    closed = validate_success(
        api_client.set_operating_status(
            landfill["id"], {"operating_status": "CLOSED"}, PLATFORM_ADMIN
        )
    )

    assert closed["operating_status"] == "CLOSED"
    assert int(closed["version"]) == int(before["version"]) + 1

    validate_error(
        api_client.set_operating_status(
            landfill["id"], {"operating_status": "CLOSED"}, PLATFORM_ADMIN
        ),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        409,
    )
    assert fixtures.read_landfill(landfill["id"])["operating_status"] == "CLOSED"


def test_the_filer_of_an_estimate_may_not_certify_it():
    """Authorisation here reads the row's stored actor, not the acting role.

    PRD: "Certification is the segregation-of-duties checkpoint of the finance workflow: the
    `FinanceOfficer` who certifies an update may not be the one who filed it, else
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/endpoints/estimate_certification_by_its_own_filer_is_rejected
    """
    landfill = fixtures.create_landfill()
    estimate = fixtures.file_closure_estimate(landfill["id"])
    assert estimate["status"] == "DRAFT"

    response = api_client.certify_closure_cost_estimate(estimate["id"], FINANCE_FILER)

    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
    unchanged = get_success_data(
        api_client.get_closure_cost_estimate(estimate["id"], FINANCE_FILER)
    )
    assert unchanged["status"] == "DRAFT"
    assert int(unchanged["version"]) == int(estimate["version"])
    assert fixtures.read_landfill(landfill["id"])["financial_assurance_status"] == "UNFUNDED"


def test_a_second_finance_officer_certifies_the_same_row():
    """The identical request from a different finance user is accepted.

    PRD: "Certification moves it `DRAFT → CERTIFIED`, recomputes all four money fields against
    the site's **current** certified cell set rather than reusing the figures computed at
    filing, and increments its `version` by 1."

    Design: Corner/endpoints/estimate_certification_by_its_own_filer_is_rejected
    """
    landfill = fixtures.create_landfill()
    estimate = fixtures.file_closure_estimate(landfill["id"])

    certified = validate_success(
        api_client.certify_closure_cost_estimate(estimate["id"], FINANCE_CERTIFIER)
    )

    assert certified["status"] == "CERTIFIED"
    assert int(certified["version"]) == int(estimate["version"]) + 1
    assert_amount(certified["closure_cost_total"], 0.00, "closure cost total")
    assert_amount(certified["required_assurance_amount"], 4519664.50, "required assurance")
