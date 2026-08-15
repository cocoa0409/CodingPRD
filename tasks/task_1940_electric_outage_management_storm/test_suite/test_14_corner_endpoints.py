"""Corner tests — endpoints section.

Covers computed reads, conditional action fallbacks, and list/filter
interactions.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_and_activate_event,
    create_confirm_outage_payload,
    create_crew,
    create_feeder_record,
    create_outage_payload,
    get_success_data,
    run_work_order_to_completed,
    set_clock,
    setup_event_with_feeder,
    setup_outage_with_accepted_assessment,
    validate_error,
    validate_paginated,
)

ED = TEST_USERS["emergency_director_headers"]
DISP = TEST_USERS["dispatcher_headers"]


def test_cost_summary_computed_read(api):
    """PRD §3.8: "the event's cost-summary read exposes exactly those seven
    figures: `total_labor_cents`, `total_material_cents`,
    `total_mutual_aid_cents`, `total_lodging_cents`, `total_event_cost_cents`,
    `capital_cost_cents`, and `om_cost_cents`."

    Design: Corner/endpoints/cost_summary_computed_read
    """
    _ev, _fd, ot, cr_l, wo = None, None, None, None, None
    # Build an event with a single LABOR_INTERNAL 5001 posting.
    ev, fd, ot_pre, _cr_a, _da = setup_outage_with_accepted_assessment(
        customers_affected=5,
        cause_code="EQUIPMENT",
        estimated_repair_minutes=10,
        clock_iso="2026-08-10T00:00:00Z",
    )
    cr_l = create_crew(crew_type="LINE", hourly_rate_cents=10001)
    wo = run_work_order_to_completed(
        ot_pre["id"], cr_l["id"], complete_clock_iso="2026-08-10T00:30:00Z"
    )
    summary = get_success_data(api.get_cost_summary(ev["id"], DISP))
    assert summary["total_labor_cents"] == 5001
    assert summary["total_event_cost_cents"] == 5001
    assert summary["capital_cost_cents"] == 0
    assert summary["om_cost_cents"] == 5001
    # Matches the entity read for the same ledger state.
    event_read = get_success_data(api.get_storm_event(ev["id"], DISP))
    assert event_read["total_labor_cents"] == summary["total_labor_cents"]
    assert event_read["total_event_cost_cents"] == summary["total_event_cost_cents"]
    assert event_read["om_cost_cents"] == summary["om_cost_cents"]


def test_dispatch_next_empty_pool_returns_no_eligible_work(api):
    """PRD §3.5: "An empty eligible set is rejected with
    `ERR_NO_ELIGIBLE_WORK`."

    Design: Corner/endpoints/dispatch_next_empty_pool_returns_no_eligible_work
    """
    ev, _fd = setup_event_with_feeder(clock_iso="2026-08-10T00:00:00Z")
    cr = create_crew(crew_type="TREE")
    resp = api.dispatch_next(ev["id"], {"crew_id": cr["id"]}, DISP)
    err = validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_WORK)
    assert err["error_id"] == "ERR_NO_ELIGIBLE_WORK"
    crew_read = get_success_data(api.get_crew(cr["id"], DISP))
    assert crew_read["crew_status"] == "AVAILABLE"


def test_outage_list_filter_and_pagination_interaction(api):
    """PRD §3.3: "The outage list can be filtered by `storm_event_id`,
    `feeder_id`, `parent_outage_id`, `merged_into_outage_id`, or
    `outage_status`." PRD §2.3: "Paginated list responses include `limit`,
    `offset`, `total_count`, and `has_more` in the `meta` object".

    Design: Corner/endpoints/outage_list_filter_and_pagination_interaction
    """
    ev, fd = setup_event_with_feeder(clock_iso="2026-08-10T00:00:00Z")
    o1 = get_success_data(api.create_outage(create_outage_payload(ev["id"], fd["id"]), DISP))
    o2 = get_success_data(api.create_outage(create_outage_payload(ev["id"], fd["id"]), DISP))
    o3 = get_success_data(api.create_outage(create_outage_payload(ev["id"], fd["id"]), DISP))
    get_success_data(api.cancel_outage(o3["id"], DISP))

    filtered, meta_f = validate_paginated(
        api.list_outages(
            DISP, params={"storm_event_id": ev["id"], "outage_status": "CANCELLED"}
        )
    )
    assert meta_f["total_count"] == 1
    assert filtered[0]["id"] == o3["id"]
    unfiltered, meta_u = validate_paginated(
        api.list_outages(DISP, params={"storm_event_id": ev["id"]})
    )
    assert meta_u["total_count"] == 3
    assert meta_u["has_more"] is False


def test_fk_reverse_reachability_subresources(api):
    """PRD §3.4: "An outage's assessments can be listed as a sub-resource in
    `created_at` order" and "The full history is readable per outage, ordered
    by `revision_seq` ascending."

    Design: Corner/endpoints/fk_reverse_reachability_subresources
    """
    ev, fd = setup_event_with_feeder(clock_iso="2026-08-10T00:00:00Z")
    ot = get_success_data(api.create_outage(create_outage_payload(ev["id"], fd["id"]), DISP))
    confirmed = get_success_data(
        api.confirm_outage(
            ot["id"],
            create_confirm_outage_payload(
                customers_affected=50, cause_code="EQUIPMENT"
            ),
            DISP,
        )
    )
    cr_a = create_crew(crew_type="DAMAGE_ASSESSOR", start=False)
    from test_helpers import create_accepted_assessment
    da = create_accepted_assessment(
        ot["id"],
        cr_a["id"],
        expected_outage_version=confirmed["version"],
        damage_class="MINOR",
        estimated_repair_minutes=10,
    )
    revisions, meta_r = validate_paginated(api.list_etr_revisions(ot["id"], DISP))
    assert meta_r["total_count"] == 2
    assert revisions[0]["revision_seq"] == 1
    assert revisions[0]["revision_reason"] == "INITIAL"
    assert revisions[0]["previous_etr"] is None
    assert revisions[1]["revision_seq"] == 2
    assert revisions[1]["revision_reason"] == "DAMAGE_FOUND"

    assessments, meta_a = validate_paginated(
        api.list_outage_damage_assessments(ot["id"], DISP)
    )
    assert meta_a["total_count"] == 1
    assert assessments[0]["id"] == da["id"]
    assert assessments[0]["assessment_status"] == "ACCEPTED"
