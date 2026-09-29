"""Guards that read the state of a second entity, two hops from the endpoint."""

from test_helpers import (
    DIRECTOR_B,
    OFFICER_A,
    PRESERV_A,
    PRESERV_B,
    assert_empty,
    factories as f,
    failed,
    fixtures as fx,
    ok,
)
from test_helpers.api_errors import (
    ERR_ITEM_HAS_ACTIVE_LOAN,
    ERR_SERIES_DISPOSITION_SUSPENDED,
    ERR_ZONE_NOT_COMPLIANT,
)


def _suspended_series_with_a_fresh_request(client):
    """A held series, plus a request filed after the hold, so it is SUBMITTED."""
    holding = fx.make_holding(
        client,
        item_specs=[{"unit_count": 4, "sensitivity_level": "CONFIDENTIAL"}],
        schedule_overrides={"retention_years": 12, "disposition_action": "REVIEW",
                            "min_appraisal_score_for_permanent": 73.00},
        series_overrides={"title": "Environmental Compliance Files",
                          "business_unit": "EHS",
                          "sensitivity_ceiling": "CONFIDENTIAL",
                          "annual_volume_linear_feet": 35,
                          "earliest_record_year": 1990,
                          "latest_record_year": 2015},
    )
    hold = fx.active_hold(
        client, holding.series_id, effective_from="2026-08-01T00:00:00Z"
    )
    assert hold["suspended_access_request_count"] == 0
    case = fx.make_access_request(
        client,
        holding,
        requester_overrides={"requester_class": "EXTERNAL_RESEARCHER",
                             "nda_on_file": True},
    )
    assert case.request["status"] == "SUBMITTED"
    return holding, case


def test_begin_screening_is_refused_while_a_hold_freezes_the_governing_series(client):
    """PRD §2.6: "15. **Series not frozen** — the governing record series must not be in
    `SUSPENDED` disposition state, and its `legal_hold_active` flag must be false."
    PRD §3.7: "Both paths require the governing series not to be `SUSPENDED` and the
    requester to be in `ACTIVE` status."
    PRD §3.7: "From `SUBMITTED` the request advances to `SCREENING`, and the previously
    stamped `prelim_risk_score` is retained untouched — no calculation runs."

    Design: Difficulty/cross_entity_state_dependency/access_request_cannot_begin_screening_while_series_suspended
    """
    _holding, case = _suspended_series_with_a_fresh_request(client)

    failed(
        client.begin_screening(case.request_id, OFFICER_A),
        ERR_SERIES_DISPOSITION_SUSPENDED,
        409,
    )

    reloaded = fx.read_request(client, case.request_id)
    assert reloaded["status"] == "SUBMITTED"
    assert reloaded["legal_hold_blocked"] is False


def test_the_refused_screening_leaves_the_series_frozen_and_opens_no_screening(client):
    """PRD §3.3: "Hop one suspends the series."
    PRD §3.3: "the series moves to `SUSPENDED`, `legal_hold_active` is set true, and the
    series' `version` increments with `updated_at` refreshed."
    PRD §3.7: "A **confidentiality screening** is opened by an `AccessServicesOfficer`
    over a request that is under screening, naming the `access_request_id` and carrying
    `expected_access_request_version` per §2.7."

    Design: Difficulty/cross_entity_state_dependency/access_request_cannot_begin_screening_while_series_suspended
    """
    holding, case = _suspended_series_with_a_fresh_request(client)

    failed(
        client.begin_screening(case.request_id, OFFICER_A),
        ERR_SERIES_DISPOSITION_SUSPENDED,
        409,
    )

    series = fx.read_series(client, holding.series_id)
    assert series["disposition_state"] == "SUSPENDED"
    assert series["legal_hold_active"] is True

    assert_empty(
        client.list_screenings(OFFICER_A, {"access_request_id": case.request_id})
    )


def _approved_job_in_a_zone_gone_marginal(client):
    """An approved, funded job whose zone has just drifted to MARGINAL."""
    holding = fx.make_holding(
        client,
        item_specs=[{"unit_count": 10, "original_format": "MAGNETIC_TAPE",
                     "condition_grade": "GOOD", "sensitivity_level": "INTERNAL"}],
        zone_overrides={"temperature_c": 16.0, "relative_humidity_pct": 40.0,
                        "max_overlapping_migration_jobs": 2},
        series_overrides={"annual_volume_linear_feet": 10,
                          "earliest_record_year": 1986,
                          "latest_record_year": 1999},
    )
    assert holding.zone["environmental_status"] == "COMPLIANT"
    assert holding.zone["reading_count"] == 1

    plan = fx.make_plan(client, holding.zone_id, budget_cents=100000)
    job = fx.make_job(
        client,
        plan["id"],
        holding.item_id,
        stage="APPROVED",
        units=10,
        target_format="PRESERVATION_MKV",
        window_start="2026-09-10T00:00:00Z",
        window_end="2026-09-25T00:00:00Z",
    )
    assert job["committed_cost_cents"] == 46000

    reading = ok(
        client.record_environment_reading(
            holding.zone_id, f.environment_reading_payload(20.5, 52.0), PRESERV_A
        )
    )
    assert reading["environmental_status"] == "MARGINAL"
    return holding, plan, job


def test_start_is_refused_when_a_marginal_reading_moves_the_zone_out_of_compliance(
    client,
):
    """PRD §3.6: "It requires the item to be in `ACCESSIONED` status and the item's zone
    to be in `COMPLIANT` environmental status; a `MARGINAL` or `NON_COMPLIANT` zone is
    refused with `ERR_ZONE_NOT_COMPLIANT`."
    PRD §2.11: "Otherwise, a zone is `MARGINAL` when its temperature is at most 21.0
    degrees Celsius **and** its relative humidity is at least 30.0 percent and at most
    55.0 percent."
    PRD §3.6: "Recording a further environment reading overwrites both `temperature_c`
    and `relative_humidity_pct`, re-derives `environmental_status` from the new pair
    alone, and increments `reading_count` by 1."

    Design: Difficulty/cross_entity_state_dependency/migration_job_cannot_start_while_zone_environment_marginal
    """
    holding, _plan, job = _approved_job_in_a_zone_gone_marginal(client)

    failed(
        client.start_migration_job(job["id"], PRESERV_B),
        ERR_ZONE_NOT_COMPLIANT,
        422,
    )

    zone = fx.read_zone(client, holding.zone_id)
    assert zone["environmental_status"] == "MARGINAL"
    assert zone["reading_count"] == 2


def test_the_refused_start_leaves_the_job_approved_and_its_money_committed(client):
    """PRD §3.6: "Starting a job is declared only from `APPROVED`."
    PRD §3.6: "On success the job moves to `IN_PROGRESS` and the item moves `ACCESSIONED
    → IN_TREATMENT`, with no unit movement at all — the item stays shelved in its zone
    while under treatment."
    PRD §3.6: "On success, `approved_by` is stamped from `X-User-ID` and the job's
    `committed_cost_cents` is added to the plan's `budget_committed_cents`."

    Design: Difficulty/cross_entity_state_dependency/migration_job_cannot_start_while_zone_environment_marginal
    """
    holding, plan, job = _approved_job_in_a_zone_gone_marginal(client)

    failed(
        client.start_migration_job(job["id"], PRESERV_B),
        ERR_ZONE_NOT_COMPLIANT,
        422,
    )

    assert fx.read_job(client, job["id"])["status"] == "APPROVED"
    assert fx.read_item(client, holding.item_id)["status"] == "ACCESSIONED"
    assert fx.read_plan(client, plan["id"])["budget_committed_cents"] == 46000


def _dually_cleared_proposal_over_a_confirmed_loan(client):
    """A join-state proposal on an item a confirmed exhibit loan still holds."""
    holding = fx.make_holding(
        client,
        item_specs=[{"unit_count": 5, "condition_grade": "FAIR",
                     "sensitivity_level": "PUBLIC"}],
        schedule_overrides={"retention_years": 6, "disposition_action": "DESTROY",
                            "min_appraisal_score_for_permanent": 64.00},
        series_overrides={"title": "Anniversary Display Props",
                          "business_unit": "HERITAGE",
                          "sensitivity_ceiling": "PUBLIC",
                          "annual_volume_linear_feet": 9,
                          "earliest_record_year": 1975,
                          "latest_record_year": 2001},
        accession_overrides={"transfer_instrument": "DEED_OF_GIFT"},
    )
    loan = fx.make_loan(
        client,
        holding.item_id,
        "2026-10-01T00:00:00Z",
        "2026-10-31T00:00:00Z",
        stage="CONFIRMED",
        units=2,
        exhibit_name="Centenary Gallery",
    )
    proposal = fx.make_proposal(
        client, holding.item_id, stage="DUALLY_CLEARED", units=5, route="DESTRUCTION"
    )
    return holding, loan, proposal


def test_deaccession_approval_is_refused_while_a_confirmed_loan_holds_the_item(client):
    """PRD §3.9: "And no exhibit loan on the item may be in `REQUESTED`, `CONFIRMED` or
    `OUT` status, refusing otherwise with `ERR_ITEM_HAS_ACTIVE_LOAN` — material promised
    to an exhibit cannot simultaneously be promised to a skip."
    PRD §2.6: "29. **No live loan on the item** — no exhibit loan on the item may be in
    `REQUESTED`, `CONFIRMED` or `OUT`."
    PRD §3.9: "**Approval is the join point** and belongs to the `ArchivesDirector`."

    Design: Difficulty/cross_entity_state_dependency/deaccession_cannot_be_approved_while_item_has_confirmed_loan
    """
    _holding, _loan, proposal = _dually_cleared_proposal_over_a_confirmed_loan(client)

    failed(
        client.approve_deaccession_proposal(proposal["id"], DIRECTOR_B),
        ERR_ITEM_HAS_ACTIVE_LOAN,
        409,
    )

    reloaded = fx.read_proposal(client, proposal["id"])
    assert reloaded["status"] == "DUALLY_CLEARED"
    assert reloaded["approved_by"] is None


def test_the_blocking_loan_is_merely_confirmed_and_has_moved_no_units(client):
    """PRD §3.8: "No units move at confirmation."
    PRD §3.8: "Confirmation is the `PreservationOfficer`'s conservation review, declared
    only from `REQUESTED`."
    PRD §3.9: "The proposal is created in `status` `SUBMITTED` with `legal_cleared_by`,
    `heritage_cleared_by`, `approved_by`, `clearance_note` and `transfer_reference` all
    null, and `stale_finding_aid_count` and `revalidated_request_count` both 0."

    Design: Difficulty/cross_entity_state_dependency/deaccession_cannot_be_approved_while_item_has_confirmed_loan
    """
    holding, loan, proposal = _dually_cleared_proposal_over_a_confirmed_loan(client)

    failed(
        client.approve_deaccession_proposal(proposal["id"], DIRECTOR_B),
        ERR_ITEM_HAS_ACTIVE_LOAN,
        409,
    )

    assert fx.read_loan(client, loan["id"])["status"] == "CONFIRMED"
    item = fx.read_item(client, holding.item_id)
    assert item["status"] == "ACCESSIONED"
    assert item["units_on_shelf"] == 5
    assert item["units_deaccessioned"] == 0
