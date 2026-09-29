"""
Read-your-writes: the population run's own response already carries the derived
counters, and the reads issued straight after it agree with it field for field.
"""

from test_helpers import (
    CampaignStatus,
    VehicleRemedyStatus,
    fixtures as fx,
    read_list,
    validate_success,
)
from test_helpers.test_users import OPERATIONS_MANAGER


def test_population_run_response_reflects_the_new_counters_immediately(api):
    """
    The matching pass answers with the five figures it just computed, and a campaign
    read and a population read issued next — with no intervening write — return the same
    figures plus the newly created row, so nothing about the match is deferred to a
    later recomputation.

    PRD §3.2: "The run answers with `matched_count`, `excluded_count`, `removed_count`,
    `affected_vehicle_count` and `recall_population_count`."

    PRD §3.2: "The run then refreshes the campaign's `affected_vehicle_count` to the
    total number of affected-vehicle rows in any status, sets `recall_population_count`
    to that total minus the number of rows in `REMOVED_FROM_POPULATION`, recomputes
    `completion_rate_pct`, increments the campaign's `version` by 1, and refreshes every
    rule's `matched_vehicle_count`."

    Design: Corner/consistency_model/population_run_response_reflects_the_new_counters_immediately
    """
    state = fx.draft_campaign(api, campaign_number="26V-346")
    campaign_id = state["campaign_id"]
    vehicle = fx.create_vehicle(api)
    fx.add_population_rule(api, campaign_id)
    determined = fx.determine_defect(api, campaign_id)
    assert determined["campaign_status"] == CampaignStatus.DEFECT_DETERMINED

    run = validate_success(api.run_population(campaign_id, {}, OPERATIONS_MANAGER), 201)

    assert run["matched_count"] == 1
    assert run["excluded_count"] == 0
    assert run["removed_count"] == 0
    assert run["affected_vehicle_count"] == 1
    assert run["recall_population_count"] == 1

    campaign = fx.read_campaign(api, campaign_id, OPERATIONS_MANAGER)
    assert campaign["affected_vehicle_count"] == 1
    assert campaign["recall_population_count"] == 1
    assert campaign["remedied_count"] == 0
    assert campaign["completion_rate_pct"] == 0.00

    rows, _ = read_list(
        api.list_affected_vehicles(OPERATIONS_MANAGER, {"campaign_id": campaign_id}),
        expected_total=1,
    )
    assert rows[0]["vehicle_id"] == vehicle["id"]
    assert rows[0]["remedy_status"] == VehicleRemedyStatus.UNREPAIRED
    assert rows[0]["notice_count"] == 0
    assert rows[0]["outreach_attempt_count"] == 0
