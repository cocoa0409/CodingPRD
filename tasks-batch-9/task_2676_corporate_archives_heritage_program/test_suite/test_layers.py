"""The cross-cutting complexity layers, plus the immediate-consistency claim.

Every test here translates one instance of the corner-design
``cross-cutting complexity layers`` or ``consistency model`` section: the two
stale-version guards of §2.7 and their positive counterpart, the inclusive
lower bound of a display window, and the plan ledger written inside the
approving request.
"""

from test_helpers import (
    ARCHIVIST_A,
    DIRECTOR_A,
    OFFICER_A,
    OFFICER_B,
    PRESERV_A,
    PRESERV_B,
    PRESERV_B_ID,
    assert_empty,
    assert_fields,
    assert_instant,
    assert_nulls,
    assert_score_2dp,
    assert_unit_custody_identity,
    factories as f,
    failed,
    fixtures as fx,
    ok,
)
from test_helpers.api_errors import (
    ERR_STALE_ACCESS_REQUEST_VERSION,
    ERR_STALE_SERIES_VERSION,
)


def test_a_hold_round_trip_leaves_the_series_at_ACTIVE_but_makes_version_one_stale(
    client,
):
    """PRD §2.7: "To prevent that, `POST /appraisals` requires `expected_series_version` as
    a non-optional body field, carrying the `version` of the record series as the client
    last observed it."
    PRD §2.7: "If that value does not equal the series' current `version`, the create is
    rejected with `ERR_STALE_SERIES_VERSION` (HTTP 412) and nothing is written."
    PRD §2.7: "Note that the guard is against staleness, not against contention: any write
    that has advanced the parent's `version` since the client's last read — a cascade, a
    counter refresh, another operator's action — is enough to make a previously valid
    expected value stale."
    PRD §3.3: "Provided no other hold on the series remains `ACTIVE` after this release,
    the series restores `disposition_state` from `pre_hold_disposition_state` verbatim — a
    series that was `ACTIVE` before the hold returns to `ACTIVE`, one that was
    `ELIGIBLE_FOR_DISPOSITION` returns to `ELIGIBLE_FOR_DISPOSITION`, and one that was
    `PERMANENT` returns to `PERMANENT` — then `pre_hold_disposition_state` is set back to
    null and `legal_hold_active` becomes false, with the series' `version` incrementing."

    Design: Corner/cross-cutting complexity layers/layers_occ_stale_series_version_on_appraisal_create_returns_412
    """
    schedule = fx.make_schedule(
        client,
        code="CL-01",
        retention_years=60,
        disposition_action="REVIEW",
        legal_citation="Corp Policy 8.1",
        min_appraisal_score_for_permanent=30.00,
    )
    series = fx.make_series(
        client,
        schedule["id"],
        title="Litigation Support Files",
        business_unit="Legal",
        sensitivity_ceiling="CONFIDENTIAL",
        annual_volume_linear_feet=9,
        earliest_record_year=1990,
        latest_record_year=2012,
    )
    assert series["version"] == 1

    hold = fx.active_hold(
        client,
        series["id"],
        matter_number="MAT-2026-0044",
        effective_from="2026-07-01T00:00:00Z",
    )
    fx.release_hold(client, hold["id"], release_note="Matter closed.")

    failed(
        client.create_appraisal(
            f.appraisal_payload(
                series["id"],
                1,
                informational_value=3,
                evidential_value=3,
                brand_heritage_value=0,
                uniqueness_factor=3,
                provenance_verified=True,
            ),
            ARCHIVIST_A,
        ),
        ERR_STALE_SERIES_VERSION,
        412,
    )

    reloaded = fx.read_series(client, series["id"])
    assert_fields(
        reloaded, version=3, disposition_state="ACTIVE", legal_hold_active=False
    )
    assert_nulls(reloaded, "pre_hold_disposition_state", "current_appraisal_id")
    assert_empty(
        client.list_appraisals(ARCHIVIST_A, {"record_series_id": series["id"]})
    )


def test_beginning_screening_makes_the_creation_time_request_version_stale(client):
    """PRD §2.7: "`POST /confidentiality-screenings` therefore requires
    `expected_access_request_version` as a non-optional body field, carrying the `version`
    of the access request as the client last observed it."
    PRD §2.7: "If it does not equal the request's current `version`, the create is rejected
    with `ERR_STALE_ACCESS_REQUEST_VERSION` (HTTP 412) and no screening is opened."
    PRD §3.7: "From `SUBMITTED` the request advances to `SCREENING`, and the previously
    stamped `prelim_risk_score` is retained untouched — no calculation runs."
    PRD §3.7: "`current_screening_id` always means the most recently created screening on
    that request that is in `OPEN` or `COMPLETED`, ordered by `created_at` ascending, and
    is null when no such screening exists."

    Design: Corner/cross-cutting complexity layers/layers_occ_stale_access_request_version_on_screening_create_returns_412
    """
    holding = fx.make_holding(
        client,
        item_specs=[{"unit_count": 2, "item_label": "SPONSORSHIP-FILES"}],
        schedule_overrides={"code": "CL-02", "retention_years": 61,
                            "disposition_action": "REVIEW",
                            "legal_citation": "Corp Policy 8.2",
                            "min_appraisal_score_for_permanent": 80.00},
        series_overrides={"title": "Sponsorship Agreements",
                          "business_unit": "Marketing",
                          "sensitivity_ceiling": "INTERNAL",
                          "annual_volume_linear_feet": 6,
                          "earliest_record_year": 1994,
                          "latest_record_year": 2016},
        zone_overrides={"zone_code": "Z-CL02", "temperature_c": 16.0,
                        "relative_humidity_pct": 44.0,
                        "max_overlapping_migration_jobs": 1},
    )
    case = fx.make_access_request(
        client,
        holding,
        requester_overrides={"display_name": "K. Nakamura",
                             "requester_class": "EXTERNAL_RESEARCHER",
                             "affiliation": "Sports Economics Institute",
                             "nda_on_file": True},
        purpose="Study of sponsorship economics.",
        headers=OFFICER_A,
    )
    assert case.request["version"] == 1

    fx.drive_to_screening(client, case)
    assert case.request["version"] == 2

    failed(
        client.create_screening(f.screening_payload(case.request_id, 1), OFFICER_B),
        ERR_STALE_ACCESS_REQUEST_VERSION,
        412,
    )

    reloaded = fx.read_request(client, case.request_id)
    assert_fields(reloaded, status="SCREENING", version=2)
    assert_nulls(reloaded, "current_screening_id")
    assert_empty(
        client.list_screenings(OFFICER_A, {"access_request_id": case.request_id})
    )


def test_the_correct_expected_version_succeeds_and_every_write_bumps_its_own_row(client):
    """PRD §2.7: "Creating an appraisal for a record series supersedes every earlier
    appraisal on that series."
    PRD §3.2: "The core score is the informational rating multiplied by 3, plus the
    evidential rating multiplied by 3, plus the admitted brand-heritage rating multiplied
    by 2, plus the uniqueness rating multiplied by 2."
    PRD §3.2: "The age bonus is one point for every complete five years of that span,
    discarding any remainder, capped at 10 points."
    PRD §3.2: "Finalisation writes `final_score`, sets `brand_heritage_counted`, derives
    `recommended_disposition`, sets the series' `current_appraisal_id` to this appraisal,
    and increments the series' `version`."
    PRD §3.2: "From `ACTIVE`, a recommendation of `PERMANENT` moves the series to
    `PERMANENT`."

    Design: Corner/cross-cutting complexity layers/layers_occ_correct_version_succeeds_and_version_increments_on_every_write
    """
    schedule = fx.make_schedule(
        client,
        code="CL-03",
        retention_years=62,
        disposition_action="REVIEW",
        legal_citation="Corp Policy 8.3",
        min_appraisal_score_for_permanent=30.00,
    )
    series = fx.make_series(
        client,
        schedule["id"],
        title="Executive Correspondence",
        business_unit="Office of the CEO",
        sensitivity_ceiling="CONFIDENTIAL",
        annual_volume_linear_feet=20,
        earliest_record_year=1950,
        latest_record_year=2010,
    )
    assert series["version"] == 1

    appraisal = fx.make_appraisal(
        client,
        series,
        expected_series_version=1,
        informational_value=3,
        evidential_value=3,
        brand_heritage_value=0,
        uniqueness_factor=3,
        provenance_verified=True,
    )
    assert appraisal["version"] == 1

    screened = ok(client.screen_appraisal(appraisal["id"], ARCHIVIST_A))
    assert screened["version"] == 2
    assert_score_2dp(screened, "screening_score", 34.00)

    finalized = ok(client.finalize_appraisal(appraisal["id"], DIRECTOR_A))
    assert finalized["version"] == 3
    assert_score_2dp(finalized, "final_score", 34.00)
    assert_fields(finalized, status="FINAL", recommended_disposition="PERMANENT")

    reloaded = fx.read_series(client, series["id"])
    assert_fields(
        reloaded, disposition_state="PERMANENT", current_appraisal_id=appraisal["id"]
    )


def test_check_out_at_the_exact_window_start_succeeds_and_moves_the_units(client):
    """PRD §2.6: "20. **Display window open** — the logical clock must be at or after the
    loan's `window_start`."
    PRD §2.5: "Before any operator sets it, it reads exactly `2026-08-01T00:00:00Z`."
    PRD §3.8: "On success the loan moves to `OUT`, `checked_out_at` is stamped from the
    logical clock, and the item moves `ACCESSIONED → ON_LOAN` with the loan's `units`
    subtracted from `units_on_shelf` and the same number added to `units_on_loan`,
    preserving the conservation identity of §2.10 exactly."
    PRD §3.8: "Creation also refreshes the item's `last_loan_window_end`, which always
    holds the `window_end` of the most recently created loan on that item whose status is
    `REQUESTED`, `CONFIRMED`, `OUT` or `RETURNED`, ordered by `created_at` ascending, and
    is null when no such loan exists."

    Design: Corner/cross-cutting complexity layers/layers_temporal_windowing_check_out_exactly_at_window_start_succeeds
    """
    holding = fx.make_holding(
        client,
        item_specs=[{"unit_count": 2, "original_format": "PHOTO",
                     "sensitivity_level": "PUBLIC",
                     "item_label": "CENTENARY-OBJECTS"}],
        schedule_overrides={"code": "CL-04", "retention_years": 63,
                            "disposition_action": "REVIEW",
                            "legal_citation": "Corp Policy 8.4",
                            "min_appraisal_score_for_permanent": 80.00},
        series_overrides={"title": "Centenary Objects",
                          "business_unit": "Heritage",
                          "sensitivity_ceiling": "PUBLIC",
                          "annual_volume_linear_feet": 3,
                          "earliest_record_year": 1926,
                          "latest_record_year": 1966},
        zone_overrides={"zone_code": "Z-CL04", "temperature_c": 16.0,
                        "relative_humidity_pct": 44.0,
                        "max_overlapping_migration_jobs": 1},
        accession_overrides={"donor_name": "Heritage Office"},
    )
    loan = fx.make_loan(
        client,
        holding.item_id,
        "2026-08-01T00:00:00Z",
        "2026-08-31T00:00:00Z",
        stage="CONFIRMED",
        units=2,
        exhibit_name="Centenary Opening",
    )

    out = ok(client.check_out_exhibit_loan(loan["id"], ARCHIVIST_A))
    assert out["status"] == "OUT"
    assert_instant(out, "checked_out_at", "2026-08-01T00:00:00.000Z")

    item = fx.read_item(client, holding.item_id)
    assert_fields(item, status="ON_LOAN", units_on_loan=2, units_on_shelf=0)
    assert_instant(item, "last_loan_window_end", "2026-08-31T00:00:00.000Z")
    assert_unit_custody_identity(item)


def test_approving_a_job_shows_the_plan_ledger_moved_in_the_same_request(client):
    """PRD §2.8: "Nothing is deferred, queued or reconciled later; by the time the response
    is written every derived field named below already holds its post-cascade value."
    PRD §3.6: "The plan is created in `status` `DRAFT` with `budget_committed_cents`,
    `budget_spent_cents` and `at_risk_unit_count` all 0 and `satisfied_at` null."
    PRD §3.6: "On success, `approved_by` is stamped from `X-User-ID` and the job's
    `committed_cost_cents` is added to the plan's `budget_committed_cents`."
    PRD §3.6: "Step four selects `handling_fee_cents` from the step-three output: 1,500
    cents when `discounted_cents` is 25,000 or less, 4,000 cents when it lies between
    25,001 and 100,000 inclusive, and 9,000 cents when it is 100,001 or more."

    Design: Corner/consistency model/consistency_migration_approve_reflects_plan_ledger_in_the_same_request
    """
    holding = fx.make_holding(
        client,
        item_specs=[
            {"unit_count": 10, "item_label": "INSPECTIONS-1985-2011"},
            {"unit_count": 1, "original_format": "FILM",
             "item_label": "INSPECTIONS-REELS"},
        ],
        schedule_overrides={"code": "CM-01", "retention_years": 64,
                            "disposition_action": "REVIEW",
                            "legal_citation": "Corp Policy 9.1",
                            "min_appraisal_score_for_permanent": 80.00},
        series_overrides={"title": "Safety Inspection Records",
                          "business_unit": "Operations",
                          "sensitivity_ceiling": "INTERNAL",
                          "annual_volume_linear_feet": 13,
                          "earliest_record_year": 1985,
                          "latest_record_year": 2011},
        zone_overrides={"zone_code": "Z-CM01", "temperature_c": 15.0,
                        "relative_humidity_pct": 42.0,
                        "max_overlapping_migration_jobs": 2},
    )
    draft_plan = fx.make_plan(
        client,
        holding.zone_id,
        activate=False,
        plan_name="Inspection Record Digitisation",
        budget_cents=500000,
    )
    assert_fields(
        draft_plan,
        status="DRAFT",
        budget_committed_cents=0,
        budget_spent_cents=0,
        at_risk_unit_count=0,
    )
    plan = ok(client.activate_preservation_plan(draft_plan["id"], PRESERV_A))
    assert plan["status"] == "ACTIVE"

    job = fx.make_job(
        client,
        plan["id"],
        holding.item_ids[0],
        units=10,
        target_format="PRESERVATION_TIFF",
        window_start="2026-09-02T00:00:00Z",
        window_end="2026-09-12T00:00:00Z",
    )
    assert job["committed_cost_cents"] == 10500

    approved = ok(client.approve_migration_job(job["id"], PRESERV_B))
    assert_fields(approved, status="APPROVED", approved_by=PRESERV_B_ID)

    reloaded = fx.read_plan(client, plan["id"])
    assert_fields(
        reloaded,
        status="ACTIVE",
        budget_committed_cents=10500,
        budget_spent_cents=0,
    )
