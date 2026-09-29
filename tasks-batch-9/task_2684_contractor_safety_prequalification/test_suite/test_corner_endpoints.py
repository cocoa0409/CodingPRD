"""Corner section: endpoints.

The amend endpoint, the read-only scorecard projection, the requalification
batch run, body-reference resolution on edge creation, a decision whose input
requirement attaches to one decision value, and the document review loop's
only reverse edge.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prd_bench_local_runner.testing import (  # noqa: E402
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (  # noqa: E402
    ERR_CONTRACTOR_NOT_FOUND,
    ERR_INVALID_FIELD_VALUE,
    ERR_TRANSITION_NOT_ALLOWED,
)
from test_helpers.assertions import (  # noqa: E402
    assert_certificate_state,
    assert_contractor_posture,
    assert_effective_thresholds,
    assert_instant_equals,
    assert_prequalification_state,
    assert_rate_equals,
    assert_score_equals,
    assert_versioned_row,
)
from test_helpers.constants import INITIAL_CLOCK  # noqa: E402
from test_helpers.factories import (  # noqa: E402
    link_payload,
    program_payload,
    program_resubmit_payload,
    program_review_payload,
    variance_decision_payload,
    variance_payload,
)


def test_patch_contractor_updates_scope_and_bumps_version_and_retiers(
    build, api, admin_headers
):
    """Every amendment bumps version by 1; only hazard_profile re-derives the tier.

    PRD Section 3.1: "Each amendment advances the contractor's `version` by exactly
    1, and changing `hazard_profile` recomputes `base_hazard_tier`, which in turn
    changes both the tightening factor the next grading will apply and the coverage
    multiplier every adequacy test will use."

    Design: Corner/endpoints/patch_contractor_updates_scope_and_bumps_version_and_retiers
    """
    build.set_clock(INITIAL_CLOCK)
    contractor = build.create_contractor()
    assert_contractor_posture(contractor, base_hazard_tier=1, status="ACTIVE")
    assert_versioned_row(contractor, 1)

    first = validate_success(
        api.patch_contractor(
            contractor["id"],
            {"scope_of_work": ["MECHANICAL_TRADE", "SCAFFOLDING"], "employee_count": 55},
            admin_headers,
        )
    )
    assert first["scope_of_work"] == ["MECHANICAL_TRADE", "SCAFFOLDING"]
    assert first["employee_count"] == 55
    assert_versioned_row(first, 2)
    # A scope-only edit must not move the hazard tier.
    assert_contractor_posture(first, base_hazard_tier=1)

    second = validate_success(
        api.patch_contractor(
            contractor["id"], {"hazard_profile": ["GENERAL", "HEIGHTS"]}, admin_headers
        )
    )
    assert second["hazard_profile"] == ["GENERAL", "HEIGHTS"]
    assert_contractor_posture(second, base_hazard_tier=2)
    assert_versioned_row(second, 3)

    reread = build.read_contractor(contractor["id"])
    assert_versioned_row(reread, 3)
    assert_contractor_posture(reread, status="ACTIVE", base_hazard_tier=2)


def test_prequalification_scorecard_returns_subscores_and_effective_thresholds(
    build, api
):
    """A pure projection of the last grading run, agreeing with the stored score.

    PRD Section 3.6: "It reports `prequalification_id`, `contractor_id`,
    `client_id`, `status`, `grade`, `provisional_composite_score`,
    `final_composite_score`, `governing_reporting_year`, `hazard_tier`, a
    `normalized_metrics` object holding the governing statistic's `trir`,
    `dart_rate`, `emr` and `citation_points`, the `effective_thresholds` object,
    `deficiency_codes`, `conditional_expires_at` and `expires_at`."

    Design: Corner/endpoints/prequalification_scorecard_returns_subscores_and_effective_thresholds
    """
    build.set_clock(INITIAL_CLOCK)
    scenario = build.graded_standing()
    stored = scenario["prequalification"]
    assert_prequalification_state(stored, status="APPROVED", grade="B")

    card = validate_success(
        api.get_scorecard(scenario["prequalification_id"], scenario["contractor_headers"])
    )
    assert card["prequalification_id"] == scenario["prequalification_id"]
    assert card["contractor_id"] == scenario["contractor_id"]
    assert card["client_id"] == scenario["client_id"]
    assert card["status"] == "APPROVED"
    assert card["grade"] == "B"
    assert card["governing_reporting_year"] == 2025
    assert card["hazard_tier"] == 1

    assert_score_equals(card["provisional_composite_score"], 80.51)
    assert_score_equals(card["final_composite_score"], 80.51)
    # The projection may not disagree with the stored score.
    assert_score_equals(stored["final_composite_score"], 80.51)

    metrics = card["normalized_metrics"]
    assert_rate_equals(metrics["trir"], 0.8000)
    assert_rate_equals(metrics["dart_rate"], 0.4000)
    assert_rate_equals(metrics["emr"], 0.80)
    assert metrics["citation_points"] == 1, (
        f"expected citation_points 1, got {metrics['citation_points']}"
    )

    # Tier 1 means a tightening factor of 1.00, so the client's published
    # ceilings pass through untouched.
    assert_effective_thresholds(
        card["effective_thresholds"],
        max_trir=3.0000,
        max_dart_rate=1.5000,
        max_emr=1.0000,
        max_citation_points=6.0000,
        tightening=1.00,
        hazard_tier=1,
    )
    assert card["deficiency_codes"] == []
    assert card["conditional_expires_at"] is None
    assert_instant_equals(card["expires_at"], "2027-08-01T00:00:00Z")


def test_requalification_run_expires_one_row_then_reports_all_zero_counts(build, api):
    """The sweep is inclusive at the expiry instant and idempotent at a fixed clock.

    PRD Section 3.11: "The fourth step refreshes insurance: `lifecycle_status` and
    `available_aggregate` are re-materialized on every insurance certificate held
    by every contractor that holds a prequalification with this client, and each
    such contractor's `verified_coverage_types` is recomputed."

    Design: Corner/endpoints/requalification_run_expires_one_row_then_reports_all_zero_counts
    """
    build.set_clock(INITIAL_CLOCK)
    scenario = build.graded_standing()
    manager = scenario["manager_headers"]
    approved = scenario["prequalification"]
    assert_prequalification_state(approved, status="APPROVED", grade="B")
    assert_instant_equals(approved["expires_at"], "2027-08-01T00:00:00Z")

    # One month past both certificate expirations and exactly on expires_at.
    build.set_clock("2027-08-01T00:00:00Z")

    first = validate_success(api.run_requalification(scenario["client_id"], {}, manager))
    assert first["expired_count"] == 1, (
        f"clock == expires_at must expire the row, got {first['expired_count']}"
    )
    assert first["expired_prequalification_ids"] == [scenario["prequalification_id"]]
    assert first["conditional_rejected_count"] == 0
    assert first["conditional_rejected_prequalification_ids"] == []
    assert first["overdue_plan_count"] == 0
    assert first["lapsed_certificate_count"] == 2, (
        f"both GL and WC lapsed on 2027-07-01, got {first['lapsed_certificate_count']}"
    )

    assert_prequalification_state(
        build.read_prequalification(scenario["prequalification_id"]), status="EXPIRED"
    )

    rows, meta = validate_paginated(
        api.list_certificates(scenario["contractor_id"], scenario["contractor_headers"])
    )
    assert meta["total_count"] == 2
    for row in rows:
        assert_certificate_state(row, lifecycle_status="LAPSED")
    assert_contractor_posture(
        build.read_contractor(scenario["contractor_id"]), verified_coverage_types=[]
    )

    second = validate_success(api.run_requalification(scenario["client_id"], {}, manager))
    assert second["expired_count"] == 0
    assert second["expired_prequalification_ids"] == []
    assert second["conditional_rejected_count"] == 0
    assert second["conditional_rejected_prequalification_ids"] == []
    assert second["overdue_plan_count"] == 0
    assert second["lapsed_certificate_count"] == 0, (
        "a repeated run at the same clock re-lapses nothing"
    )

    untouched = build.read_prequalification(scenario["prequalification_id"])
    assert_prequalification_state(untouched, status="EXPIRED")
    assert_score_equals(untouched["final_composite_score"], 80.51)


def test_subcontractor_link_with_an_unknown_child_contractor_is_not_found(build, api):
    """Body-reference resolution runs before every business gate on edge creation.

    PRD Section 2.9: "Body-reference resolution, in declared field order, on
    prequalification registration, site-access-grant creation, incident-report
    filing and subcontractor-edge creation — the dedicated 404 code, per Section
    2.6."

    Design: Corner/endpoints/subcontractor_link_with_an_unknown_child_contractor_is_not_found
    """
    build.set_clock(INITIAL_CLOCK)
    scenario = build.graded_standing()
    assert_prequalification_state(
        scenario["prequalification"], status="APPROVED", grade="B"
    )

    # The child clears the 500,000 flow-down floor and holds no standing of its own.
    child = build.create_contractor(
        legal_name="Cable Crew", scope_of_work=["ELECTRICAL_TRADE"], hazard_profile=["GENERAL"]
    )
    build.verified_certificate(child["id"], "GL")

    unknown = api.create_link(
        link_payload(
            scenario["contractor_id"],
            NON_EXISTENT_UUID,
            scenario["prequalification_id"],
            ["ELECTRICAL_TRADE"],
        ),
        scenario["contractor_headers"],
    )
    validate_error(unknown, ERR_CONTRACTOR_NOT_FOUND, 404)

    _rows, meta = validate_paginated(
        api.list_links(
            build.admin_headers, {"prequalification_id": scenario["prequalification_id"]}
        )
    )
    assert meta["total_count"] == 0, (
        f"the refused request must not have created an edge, got {meta['total_count']}"
    )

    edge = validate_success(
        api.create_link(
            link_payload(
                scenario["contractor_id"],
                child["id"],
                scenario["prequalification_id"],
                ["ELECTRICAL_TRADE"],
            ),
            scenario["contractor_headers"],
        ),
        201,
    )
    assert edge["status"] == "ACTIVE"
    assert edge["depth"] == 1, (
        f"an edge whose parent is the prime sits at depth 1, got {edge['depth']}"
    )
    assert edge["flow_down_status"] == "DEFICIENT", (
        "a child with no prequalification with this client is DEFICIENT"
    )

    rows, meta = validate_paginated(
        api.list_links(
            build.admin_headers, {"prequalification_id": scenario["prequalification_id"]}
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [edge["id"]]


def test_variance_approval_with_a_non_future_expiry_is_rejected(build, api):
    """The expiry requirement attaches to APPROVE only, and the test is strict.

    PRD Section 3.7: "`APPROVE` additionally requires an `expires_at` to be
    supplied and to be strictly after the logical clock; a missing or non-future
    value is `ERR_INVALID_FIELD_VALUE`."

    Design: Corner/endpoints/variance_approval_with_a_non_future_expiry_is_rejected
    """
    build.set_clock(INITIAL_CLOCK)
    client = build.create_client()
    contractor = build.create_contractor()
    contractor_headers = build.contractor_headers(contractor["id"])
    manager = build.manager_headers(client["id"])
    prequalification = build.open_prequalification(contractor["id"], client["id"])

    emr = validate_success(
        api.create_variance(
            prequalification["id"], variance_payload("EMR", 1.05), contractor_headers
        ),
        201,
    )
    trir = validate_success(
        api.create_variance(
            prequalification["id"], variance_payload("TRIR", 3.5), contractor_headers
        ),
        201,
    )
    for row in (emr, trir):
        assert row["status"] == "REQUESTED"
        assert row["expires_at"] is None

    past = api.decide_variance(
        emr["id"], variance_decision_payload("APPROVE", "2026-07-01T00:00:00Z"), manager
    )
    validate_error(past, ERR_INVALID_FIELD_VALUE, 422)
    still_open, _meta = validate_paginated(
        api.list_variances(prequalification["id"], manager, {"status": "REQUESTED"})
    )
    assert sorted(row["id"] for row in still_open) == sorted([emr["id"], trir["id"]]), (
        "the refused decision must leave both variances at REQUESTED"
    )

    # Exactly equal to the clock: the comparison is strict, so this still fails.
    on_the_clock = api.decide_variance(
        emr["id"], variance_decision_payload("APPROVE", INITIAL_CLOCK), manager
    )
    validate_error(on_the_clock, ERR_INVALID_FIELD_VALUE, 422)

    approved = validate_success(
        api.decide_variance(
            emr["id"],
            variance_decision_payload("APPROVE", "2026-12-01T00:00:00Z"),
            manager,
        )
    )
    assert approved["status"] == "APPROVED"
    assert_instant_equals(approved["expires_at"], "2026-12-01T00:00:00Z")
    assert approved["decided_by_user_id"] == client["id"]

    # DENY needs no expires_at at all.
    denied = validate_success(
        api.decide_variance(trir["id"], variance_decision_payload("DENY"), manager)
    )
    assert denied["status"] == "DENIED"
    assert denied["expires_at"] is None

    rows, meta = validate_paginated(
        api.list_variances(prequalification["id"], manager, {"status": "APPROVED"})
    )
    assert meta["total_count"] == 1, (
        f"expected only the EMR variance to be APPROVED, got {meta['total_count']}"
    )
    assert [row["id"] for row in rows] == [emr["id"]]


def test_resubmit_written_program_after_deficient_review_returns_it_to_submitted(
    build, api
):
    """The review loop's only reverse edge, legal from DEFICIENT alone.

    PRD Section 3.4: "A deficient document is not dead: its `ContractorAdmin` may
    re-tender it, supplying a fresh `document_ref` and `revision_date`, which
    returns the row from `DEFICIENT` to `SUBMITTED`, discards the previous
    `reviewer_note` and `reviewed_by_user_id`, and recomputes the dimension so that
    it climbs back out of `DEFICIENT` toward `IN_PROGRESS`."

    Design: Corner/endpoints/resubmit_written_program_after_deficient_review_returns_it_to_submitted
    """
    build.set_clock(INITIAL_CLOCK)
    client = build.create_client()
    contractor = build.create_contractor()
    contractor_headers = build.contractor_headers(contractor["id"])
    prequalification = build.open_prequalification(contractor["id"], client["id"])
    build.file_statistic(prequalification["id"], contractor["id"])

    hazcom = build.tender_program(prequalification["id"], contractor["id"], "HAZCOM")
    discipline = validate_success(
        api.create_program(
            prequalification["id"],
            program_payload("DISCIPLINE_POLICY", document_ref="DOC-DISC-1"),
            contractor_headers,
        ),
        201,
    )

    # The row leaves DRAFT, so the dimension can read IN_PROGRESS rather than
    # being pinned at NOT_STARTED by the third clause.
    submitted = build.submit_prequalification(prequalification["id"], contractor["id"])
    assert_prequalification_state(submitted, status="SUBMITTED")

    validate_success(
        api.review_program(
            hazcom["id"],
            program_review_payload("DEFICIENT", "Section 5 of the plan is missing"),
            build.manager_headers(client["id"]),
        )
    )
    validate_success(
        api.review_program(
            discipline["id"],
            program_review_payload("ACCEPT"),
            build.manager_headers(client["id"]),
        )
    )
    assert_prequalification_state(
        build.read_prequalification(prequalification["id"]),
        document_review_status="DEFICIENT",
    )

    revised = validate_success(
        api.resubmit_program(
            hazcom["id"],
            program_resubmit_payload(
                document_ref="DOC-HAZCOM-2", revision_date="2026-07-20T00:00:00Z"
            ),
            contractor_headers,
        )
    )
    assert revised["review_status"] == "SUBMITTED"
    assert revised["document_ref"] == "DOC-HAZCOM-2"
    assert_instant_equals(revised["revision_date"], "2026-07-20T00:00:00Z")
    assert revised["reviewer_note"] is None, (
        f"the stale note must be discarded, got {revised['reviewer_note']!r}"
    )
    assert revised["reviewed_by_user_id"] is None

    assert_prequalification_state(
        build.read_prequalification(prequalification["id"]),
        document_review_status="IN_PROGRESS",
    )

    # Re-tendering is permitted only from DEFICIENT.
    refused = api.resubmit_program(
        discipline["id"],
        program_resubmit_payload(document_ref="DOC-DISC-2"),
        contractor_headers,
    )
    validate_error(refused, ERR_TRANSITION_NOT_ALLOWED, 409)

    rows, _meta = validate_paginated(
        api.list_programs(prequalification["id"], contractor_headers)
    )
    intact = [row for row in rows if row["id"] == discipline["id"]][0]
    assert intact["document_ref"] == "DOC-DISC-1", (
        f"the refused resubmit must not have written the ref, got {intact['document_ref']!r}"
    )
    assert intact["review_status"] == "ACCEPTED"
