"""
Immediate consistency: the read that follows each write already carries every
figure that write moved — the zone's recomputed signage fields, the deployment's
sample counters, the rider's citation counter and the encounter's outcome, and
the analytics aggregate over all of them — with no recompute call anywhere.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories, fixtures
from test_helpers.assertions import assert_instant_equals, assert_rate_equals
from test_helpers.constants import (
    CLOCK_EPOCH,
    DEPLOYMENT_STATUS_ACTIVE,
    GROUP_BY_GEO_TRACT,
    OUTCOME_CITATION_ISSUED,
    ZONE_STATUS_DESIGNATED,
    ZONE_STATUS_PENDING_SIGNAGE,
)
from test_helpers.fixtures import ENCOUNTER_AT, OBSERVATION_AT
from test_helpers.test_users import ANALYST_HEADERS, PLANNER_HEADERS

REPORT_WINDOW_END = "2026-09-01T00:00:00Z"
GEO_TRACT = "T-001"


def test_the_read_after_each_write_already_carries_everything_that_write_moved(api):
    """
    Filing an audit immediately recomputes the zone's two derived signage fields
    ... The same recomputation happens when a single zone is read, so a zone's
    compliance figure is always current with its audit history.  Sample adequacy
    is the gate on closing, and it is computed continuously rather than only at
    close: after every encounter created under a deployment ... Issuance also
    flips the source encounter's `outcome` to `CITATION_ISSUED` ... and recomputes
    the rider's `prior_citation_count` and the inspector's
    `citations_issued_count` — both of which rise by one as the new citation joins
    the live set.

    Design: Corner/consistency_model/every_derived_field_is_readable_immediately_after_the_write_that_moved_it
    """
    env = fixtures.build_environment(api, designate=False)
    zone_id = env["zone"]["id"]
    inspector_id = env["inspector"]["id"]
    rider_id = env["rider"]["id"]

    queued = validate_success(api.submit_zone_for_signage(zone_id, PLANNER_HEADERS))
    assert queued["designation_status"] == ZONE_STATUS_PENDING_SIGNAGE

    fixtures.file_audit(api, zone_id, 9)
    after_audit = validate_success(api.get_fare_zone(zone_id, ANALYST_HEADERS))
    assert after_audit["verified_sign_count"] == 9
    assert_rate_equals(
        after_audit["signage_compliance_pct"], 0.9000, "zone.signage_compliance_pct"
    )

    designated = validate_success(api.designate_zone(zone_id, PLANNER_HEADERS))
    assert designated["designation_status"] == ZONE_STATUS_DESIGNATED

    deployment = fixtures.plan_deployment(api, env["line"]["id"], zone_id)
    fixtures.move_clock(api, OBSERVATION_AT)
    activated = validate_success(api.activate_deployment(deployment["id"], PLANNER_HEADERS))
    assert activated["status"] == DEPLOYMENT_STATUS_ACTIVE

    encounter = fixtures.build_pending_encounter(api, env, deployment)
    after_encounter = validate_success(api.get_deployment(deployment["id"], ANALYST_HEADERS))
    assert after_encounter["achieved_sample_count"] == 1
    assert after_encounter["voided_encounter_count"] == 0
    assert_rate_equals(
        after_encounter["sample_adequacy_ratio"], 0.2000, "deployment.sample_adequacy_ratio"
    )

    fixtures.issue_citation(api, encounter["id"], inspector_id)
    after_citation = validate_success(api.get_rider(rider_id, ANALYST_HEADERS))
    assert after_citation["prior_citation_count"] == 1
    cited_encounter = validate_success(api.get_encounter(encounter["id"], ANALYST_HEADERS))
    assert cited_encounter["outcome"] == OUTCOME_CITATION_ISSUED
    assert validate_success(api.get_inspector(inspector_id, ANALYST_HEADERS))[
        "citations_issued_count"
    ] == 1

    report = validate_success(
        api.get_equity_distribution_report(
            factories.equity_report_params(
                window_start=CLOCK_EPOCH,
                window_end=REPORT_WINDOW_END,
                group_by=GROUP_BY_GEO_TRACT,
            ),
            ANALYST_HEADERS,
        )
    )
    assert report["encounter_pool_count"] == 1
    assert report["citation_count"] == 1
    assert report["groups_evaluated"] == 1
    assert_rate_equals(
        report["systemwide_citation_rate"], 1.0000, "report.systemwide_citation_rate"
    )
    assert [group["group_key"] for group in report["groups"]] == [GEO_TRACT]

    # The encounter the report counted is the one recorded inside the window.
    assert_instant_equals(
        cited_encounter["occurred_at"], ENCOUNTER_AT, "encounter.occurred_at"
    )
