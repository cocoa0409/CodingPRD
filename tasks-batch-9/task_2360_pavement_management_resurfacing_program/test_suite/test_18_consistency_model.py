"""One award, and the reads that must already agree with it."""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import fixtures
from test_helpers.assertions import (
    assert_money,
    assert_pagination_meta,
    assert_scenario_funding,
    assert_version_advanced,
    ids_of,
)
from test_helpers.constants import (
    FUNDING_STANDARD,
    MAPLE_TOTAL,
    UNCOMMITTED_AFTER_MAPLE_AWARD,
)
from test_helpers.factories import award_payload
from test_helpers.test_users import ENGINEER, INSPECTOR_ACCEPTOR, OFFICER, OFFICER_AWARDER

# ----------------------------------------------------------------------
# Pinned literals
# ----------------------------------------------------------------------
NO_COMMITMENTS = 0
DEFAULT_LIMIT = 10
DEFAULT_OFFSET = 0


def test_the_award_is_already_visible_to_every_later_reader_of_every_shape(api):
    """No settle step exists, so the committed money is on the scenario in the next read.

    PRD: "A successful award sets `contractor_id` and `award_amount_cents` on the
    project, adds the awarded amount to the scenario's `committed_cents`, recomputes
    the scenario's `uncommitted_cents` as `funding_cents` less `committed_cents`, and
    increments the scenario's `version` by 1."

    PRD: "Counters on parents are derived, not client-supplied, and are recomputed by
    the server whenever the rows they count change."

    PRD: "`committed_cents` sums the award amounts of its awarded, in-construction,
    substantially-complete and accepted projects, and `uncommitted_cents` is the
    funding total less the committed total."

    PRD: "`funded_cost_cents` sums the allocated amounts of the funded ones"

    PRD: "Projects can be listed and filtered by `scenario_id`, `contractor_id`,
    `delivery_status`, `quality_status` and `geo_zone`."

    PRD: "Every list response reports `limit`, `offset`, `total_count` and `has_more` in
    the envelope's `meta` object."

    PRD: "| GET | `/pavement/projects` | List resurfacing projects | PavementEngineer,
    BudgetOfficer, UtilityCoordinator, Inspector, Contractor |"

    The scenario read is a different entity by a different actor than the award
    addressed, and the inspector's filtered index agrees in the same instant.

    Design: Corner/consistency_model/award_ledger_is_visible_to_the_next_reader_with_no_settlement_step
    """
    ctx = fixtures.maple_bid_ready(api)
    project_id = ctx["project"]["id"]
    scenario_id = ctx["scenario"]["id"]
    contractor_id = ctx["contractor"]["id"]

    before = validate_success(api.get_scenario(scenario_id, OFFICER))
    assert_scenario_funding(before, FUNDING_STANDARD, NO_COMMITMENTS, FUNDING_STANDARD)
    assert_money(
        fixtures.read_project(api, project_id)["project_total_estimate_cents"],
        MAPLE_TOTAL,
    )

    awarded = validate_success(
        api.award_project(
            project_id, award_payload(contractor_id, MAPLE_TOTAL), OFFICER_AWARDER
        )
    )
    assert awarded["delivery_status"] == "AWARDED"

    after = validate_success(api.get_scenario(scenario_id, OFFICER))
    assert_scenario_funding(
        after, FUNDING_STANDARD, MAPLE_TOTAL, UNCOMMITTED_AFTER_MAPLE_AWARD
    )
    assert_version_advanced(before, after)
    assert_money(after["funded_cost_cents"], before["funded_cost_cents"])

    engineer_view = validate_success(api.get_project(project_id, ENGINEER))
    assert engineer_view["delivery_status"] == "AWARDED"
    assert engineer_view["contractor_id"] == contractor_id
    assert_money(engineer_view["award_amount_cents"], MAPLE_TOTAL)

    rows, meta = validate_paginated(
        api.list_projects(
            INSPECTOR_ACCEPTOR,
            {"contractor_id": contractor_id, "delivery_status": "AWARDED"},
        )
    )
    assert_pagination_meta(meta, DEFAULT_LIMIT, DEFAULT_OFFSET, 1, False)
    assert ids_of(rows) == [project_id]
