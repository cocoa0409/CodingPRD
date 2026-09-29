"""Endpoint-shape coverage: the CRUD triad, action endpoints, filtered lists.

Every test here translates one instance of the corner-design ``endpoints``
section: a create-read-list round trip, two action endpoints whose conditional
guards refuse the call, a computed single-row read, and two filtered lists.
"""

from test_helpers import (
    ARCHIVIST_A,
    DIRECTOR_A,
    OFFICER_C,
    PRESERV_A,
    PRESERV_B,
    assert_common_fields,
    assert_fields,
    assert_ids_exactly,
    assert_instant,
    assert_nulls,
    assert_one_decimal,
    assert_score_2dp,
    assert_total_count,
    assert_unit_custody_identity,
    created,
    factories as f,
    failed,
    fixtures as fx,
    ok,
    page,
)
from test_helpers.api_errors import ERR_LOAN_STATE_INVALID, ERR_PLAN_STATE_INVALID


def test_a_zone_round_trips_through_create_single_read_and_filtered_list(client):
    """PRD §3.6: "A `PreservationOfficer` creates one with a `zone_code` of 2 to 32
    characters that must be unique across all zones, an initial `temperature_c` and
    `relative_humidity_pct` reading, and `max_overlapping_migration_jobs`, a whole
    number from 1 to 20 inclusive that caps how many treatment windows may cover any
    single instant inside that zone."
    PRD §3.6: "Creation derives `environmental_status` from the creation reading per
    §2.11 and sets `reading_count` to 1."
    PRD §2.3: "Storage zones accept `environmental_status`."
    PRD §2.3: "Every list response reports `limit`, `offset`, `total_count` and
    `has_more` inside the `meta` object of the envelope; `total_count` counts the rows
    matching the filters before pagination is applied."

    Design: Corner/endpoints/endpoints_storage_zone_create_read_and_list_round_trip
    """
    # PRD §4: "Resource creation endpoints return HTTP `201` on success".
    zone_a = created(
        client.create_storage_zone(
            f.storage_zone_payload(
                14.0, 36.0, 2, zone_code="Z-CRUD-1"
            ),
            PRESERV_A,
        )
    )
    zone_b = created(
        client.create_storage_zone(
            f.storage_zone_payload(
                20.0, 52.0, 1, zone_code="Z-CRUD-2"
            ),
            PRESERV_A,
        )
    )
    assert_fields(zone_a, environmental_status="COMPLIANT", reading_count=1)
    assert_fields(zone_b, environmental_status="MARGINAL", reading_count=1)

    reread = ok(client.get_storage_zone(zone_a["id"], PRESERV_A))
    assert_common_fields(reread, 1)
    assert_fields(
        reread,
        id=zone_a["id"],
        zone_code="Z-CRUD-1",
        max_overlapping_migration_jobs=2,
        environmental_status="COMPLIANT",
    )
    assert_one_decimal(reread, "temperature_c", 14.0)
    assert_one_decimal(reread, "relative_humidity_pct", 36.0)

    rows, meta = page(client.list_storage_zones(PRESERV_A))
    assert meta["total_count"] == 2, meta
    assert meta["has_more"] is False, meta
    assert len(rows) == 2

    assert_ids_exactly(
        client.list_storage_zones(PRESERV_A, {"environmental_status": "MARGINAL"}),
        [zone_b["id"]],
    )


def test_disposing_a_series_withdraws_the_published_finding_aid_under_it(client):
    """PRD §3.1: "The base instant is the last moment of the series' latest record year
    — the ISO 8601 UTC instant whose date is 31 December of `latest_record_year` and
    whose time is 23:59:59.000."
    PRD §3.1: "The series' `retention_expiry_utc` is that base instant advanced by
    `retention_years` whole calendar years, meaning the year field is incremented while
    the month, day and time-of-day are preserved verbatim."
    PRD §3.2: "When the rounded `final_score` is greater than or equal to the governing
    schedule's `min_appraisal_score_for_permanent`, `recommended_disposition` is
    `PERMANENT`; otherwise it is the schedule's `disposition_action`, so one of
    `DESTROY`, `REVIEW` or `TRANSFER`."
    PRD §3.1: "Disposal also has one cascade: every finding aid whose accession belongs
    to this series and whose status is `PUBLISHED` transitions to `WITHDRAWN`, from
    which no further transition is possible."

    Design: Corner/endpoints/endpoints_dispose_series_withdraws_published_finding_aid
    """
    holding = fx.make_holding(
        client,
        item_specs=[{"unit_count": 2, "item_label": "PO-1995-2020"}],
        schedule_overrides={"code": "EP-01", "retention_years": 2,
                            "disposition_action": "REVIEW",
                            "legal_citation": "Corp Policy 5.1",
                            "min_appraisal_score_for_permanent": 90.00},
        series_overrides={"title": "Routine Purchase Orders",
                          "business_unit": "Procurement",
                          "sensitivity_ceiling": "INTERNAL",
                          "annual_volume_linear_feet": 20,
                          "earliest_record_year": 1995,
                          "latest_record_year": 2020},
    )
    assert_instant(holding.series, "retention_expiry_utc", "2022-12-31T23:59:59.000Z")

    aid = fx.published_finding_aid(
        client,
        holding.accession_id,
        title="Purchase Orders, 1995-2020",
        version_label="v1.0",
    )
    assert aid["status"] == "PUBLISHED"

    series = fx.read_series(client, holding.series_id)
    appraisal = fx.make_appraisal(
        client,
        series,
        informational_value=3,
        evidential_value=3,
        brand_heritage_value=2,
        uniqueness_factor=2,
        provenance_verified=False,
    )
    screened = ok(client.screen_appraisal(appraisal["id"], ARCHIVIST_A))
    assert_score_2dp(screened, "screening_score", 31.00)

    finalized = ok(client.finalize_appraisal(appraisal["id"], DIRECTOR_A))
    assert_score_2dp(finalized, "final_score", 21.60)
    assert_fields(finalized, recommended_disposition="REVIEW")
    assert fx.read_series(client, holding.series_id)["disposition_state"] == (
        "ELIGIBLE_FOR_DISPOSITION"
    )

    disposed = ok(
        client.dispose_record_series(
            holding.series_id, f.dispose_payload("DISP-2026-0007"), DIRECTOR_A
        )
    )
    assert_fields(
        disposed,
        disposition_state="DISPOSED",
        disposition_certificate_reference="DISP-2026-0007",
    )
    assert fx.read_finding_aid(client, aid["id"])["status"] == "WITHDRAWN"
    assert fx.read_item(client, holding.item_id)["status"] == "ACCESSIONED"


def test_the_loan_list_filters_down_to_the_one_loan_on_the_named_item(client):
    """PRD §2.3: "Beyond `limit` and `offset`, most list endpoints accept optional
    equality filters that stand in for the URL nesting this API deliberately avoids."
    PRD §2.3: "Trademark evidence packages accept `record_series_id` and `status`;
    exhibit loans accept `archival_item_id` and `status`; deaccession proposals accept
    `archival_item_id`, `status` and `route`."
    PRD §2.3: "Unless a specific endpoint states otherwise, list results are sorted by
    `created_at` in ascending order."
    PRD §3.8: "The loan is created in `status` `REQUESTED` with
    `returned_condition_grade`, `checked_out_at` and `returned_at` null, and its
    `recovery_until` derived as `window_end` plus a 45-day light-recovery buffer — the
    effective end of this loan's occupation of the item, during which the material rests
    out of the light."

    Design: Corner/endpoints/endpoints_exhibit_loan_list_filtered_by_archival_item_id
    """
    holding = fx.make_holding(
        client,
        item_specs=[
            {"unit_count": 2, "original_format": "PHOTO",
             "sensitivity_level": "PUBLIC", "item_label": "OBJECT-A"},
            {"unit_count": 2, "original_format": "PHOTO",
             "sensitivity_level": "PUBLIC", "item_label": "OBJECT-B"},
        ],
        schedule_overrides={"code": "EP-02", "retention_years": 30,
                            "disposition_action": "REVIEW",
                            "legal_citation": "Corp Policy 5.2",
                            "min_appraisal_score_for_permanent": 85.00},
        series_overrides={"title": "Anniversary Exhibit Pool",
                          "business_unit": "Heritage",
                          "sensitivity_ceiling": "PUBLIC",
                          "annual_volume_linear_feet": 6,
                          "earliest_record_year": 1926,
                          "latest_record_year": 1976},
        accession_overrides={"donor_name": "Heritage Office"},
    )
    item_a_id, item_b_id = holding.item_ids

    loan_a = fx.make_loan(
        client,
        item_a_id,
        "2026-08-10T00:00:00Z",
        "2026-09-10T00:00:00Z",
        units=2,
        exhibit_name="Centenary Hall",
    )
    loan_b = fx.make_loan(
        client,
        item_b_id,
        "2026-08-15T00:00:00Z",
        "2026-09-15T00:00:00Z",
        units=2,
        exhibit_name="Regional Tour",
    )

    assert_ids_exactly(
        client.list_exhibit_loans(PRESERV_A, {"archival_item_id": item_a_id}),
        [loan_a["id"]],
    )
    assert_total_count(client.list_exhibit_loans(PRESERV_A), 2)

    assert_fields(
        fx.read_loan(client, loan_b["id"]),
        archival_item_id=item_b_id,
        status="REQUESTED",
    )
    assert_fields(fx.read_loan(client, loan_a["id"]), status="REQUESTED")


def test_reading_one_access_request_shows_its_page_count_and_preliminary_risk(client):
    """PRD §3.7: "`requested_page_count` is eleven pages for every unit in the requested
    items — that is, eleven multiplied by the sum of `unit_count` across the items named
    in `requested_item_ids`."
    PRD §3.7: "Both passes start from the requester's class weight: 10 points for
    `INTERNAL_BUSINESS`, 30 for `EXTERNAL_RESEARCHER` and 45 for `MEDIA`."
    PRD §3.7: "It adds the sensitivity weight of the series' `sensitivity_ceiling` as a
    single upper-bound proxy for the holdings — 0 points for `PUBLIC`, 15 for
    `INTERNAL`, 35 for `CONFIDENTIAL` and 60 for `RESTRICTED` — and it ignores legal
    holds and redaction entirely."
    PRD §3.7: "The new request enters `status` `SUBMITTED` with `legal_hold_blocked`
    false, `revision_round` 0, `current_screening_id` null, and `post_screen_risk_score`,
    `service_fee_cents`, `decided_by`, `approval_scope` and `deny_reason` all null."

    Design: Corner/endpoints/endpoints_access_request_get_returns_computed_page_count_and_prelim_risk
    """
    holding = fx.make_holding(
        client,
        item_specs=[
            {"unit_count": 3, "item_label": "PRESS-1971-1989"},
            {"unit_count": 4, "item_label": "PRESS-1990-2007"},
        ],
        schedule_overrides={"code": "EP-03", "retention_years": 31,
                            "disposition_action": "REVIEW",
                            "legal_citation": "Corp Policy 5.3",
                            "min_appraisal_score_for_permanent": 85.00},
        series_overrides={"title": "Press Releases",
                          "business_unit": "Corporate Communications",
                          "sensitivity_ceiling": "INTERNAL",
                          "annual_volume_linear_feet": 11,
                          "earliest_record_year": 1971,
                          "latest_record_year": 2007},
    )
    case = fx.make_access_request(
        client,
        holding,
        requester_overrides={"display_name": "J. Okonkwo",
                             "requester_class": "MEDIA",
                             "affiliation": "Weekly Review",
                             "nda_on_file": False},
        purpose="Retrospective on company announcements.",
    )

    row = ok(client.get_access_request(case.request_id, OFFICER_C))
    assert_fields(
        row,
        id=case.request_id,
        requested_page_count=77,
        prelim_risk_score=60,
        status="SUBMITTED",
        revision_round=0,
    )
    assert_nulls(row, "post_screen_risk_score", "service_fee_cents")


def test_a_loan_already_out_cannot_be_cancelled_and_keeps_its_units_off_the_shelf(
    client,
):
    """PRD §3.8: "Cancellation is available to the `ArchivesDirector` and to the
    `Archivist` and is declared from `REQUESTED` and equally from `CONFIRMED`; both paths
    land the loan in the terminal `CANCELLED`, move no units, and free the item's
    occupation window including its recovery buffer so that later loans may be scheduled
    over it."
    PRD §3.8: "A loan already `OUT`, `RETURNED` or `CANCELLED` cannot be cancelled, and
    the attempt yields `ERR_LOAN_STATE_INVALID`."
    PRD §3.8: "On success the loan moves to `OUT`, `checked_out_at` is stamped from the
    logical clock, and the item moves `ACCESSIONED → ON_LOAN` with the loan's `units`
    subtracted from `units_on_shelf` and the same number added to `units_on_loan`,
    preserving the conservation identity of §2.10 exactly."

    Design: Corner/endpoints/endpoints_loan_cancel_from_out_returns_loan_state_invalid
    """
    holding = fx.make_holding(
        client,
        item_specs=[{"unit_count": 2, "original_format": "PHOTO",
                     "sensitivity_level": "PUBLIC", "item_label": "PORTRAITS"}],
        schedule_overrides={"code": "EP-04", "retention_years": 32,
                            "disposition_action": "REVIEW",
                            "legal_citation": "Corp Policy 5.4",
                            "min_appraisal_score_for_permanent": 85.00},
        series_overrides={"title": "Founder Portraits",
                          "business_unit": "Heritage",
                          "sensitivity_ceiling": "PUBLIC",
                          "annual_volume_linear_feet": 2,
                          "earliest_record_year": 1928,
                          "latest_record_year": 1959},
        accession_overrides={"donor_name": "Heritage Office"},
    )
    loan = fx.make_loan(
        client,
        holding.item_id,
        "2026-08-01T00:00:00Z",
        "2026-09-01T00:00:00Z",
        stage="OUT",
        units=2,
        exhibit_name="Boardroom Faces",
    )
    assert loan["status"] == "OUT"

    failed(
        client.cancel_exhibit_loan(loan["id"], DIRECTOR_A),
        ERR_LOAN_STATE_INVALID,
        409,
    )

    assert fx.read_loan(client, loan["id"])["status"] == "OUT"
    item = fx.read_item(client, holding.item_id)
    assert_fields(item, status="ON_LOAN", units_on_loan=2, units_on_shelf=0)
    assert_unit_custody_identity(item)


def test_a_plan_with_a_job_still_awaiting_approval_cannot_be_closed(client):
    """PRD §3.6: "Closing a plan is declared from `ACTIVE` and from `SATISFIED`, and both
    paths carry the identical additional condition: no migration job on the plan may
    still be in `PENDING_APPROVAL`, `APPROVED` or `IN_PROGRESS`."
    PRD §3.6: "A plan with any such open job is refused with `ERR_PLAN_STATE_INVALID`."
    PRD §3.6: "The job is created in `status` `PENDING_APPROVAL` with `requested_by`
    stamped from `X-User-ID`, `approved_by` and `cancel_reason` null."
    PRD §3.6: "**The at-risk census** sums `unit_count` over every archival item whose
    `storage_zone_id` matches the plan's zone, whose status is one of `UNPROCESSED`,
    `ACCESSIONED` or `IN_TREATMENT`, whose `original_format` is `MAGNETIC_TAPE` or
    `FILM`, and whose `digital_surrogate_available` is false."

    Design: Corner/endpoints/endpoints_plan_close_with_open_job_returns_plan_state_invalid
    """
    holding = fx.make_holding(
        client,
        item_specs=[{"unit_count": 6, "condition_grade": "FAIR",
                     "original_format": "FILM", "sensitivity_level": "INTERNAL",
                     "item_label": "MICROFILM-REELS"}],
        schedule_overrides={"code": "EP-05", "retention_years": 33,
                            "disposition_action": "REVIEW",
                            "legal_citation": "Corp Policy 5.5",
                            "min_appraisal_score_for_permanent": 85.00},
        series_overrides={"title": "Microfilm Holdings",
                          "business_unit": "Corporate Archives",
                          "sensitivity_ceiling": "INTERNAL",
                          "annual_volume_linear_feet": 15,
                          "earliest_record_year": 1966,
                          "latest_record_year": 1993},
        zone_overrides={"zone_code": "Z-EP05", "temperature_c": 15.0,
                        "relative_humidity_pct": 39.0,
                        "max_overlapping_migration_jobs": 2},
    )
    plan = fx.make_plan(
        client,
        holding.zone_id,
        plan_name="Microfilm Reformatting",
        budget_cents=300000,
    )
    assert_fields(plan, status="ACTIVE", at_risk_unit_count=6)

    job = fx.make_job(
        client,
        plan["id"],
        holding.item_id,
        target_format="PRESERVATION_TIFF",
        units=6,
        window_start="2026-09-05T00:00:00Z",
        window_end="2026-09-25T00:00:00Z",
    )
    assert job["status"] == "PENDING_APPROVAL"

    failed(
        client.close_preservation_plan(plan["id"], PRESERV_B),
        ERR_PLAN_STATE_INVALID,
        409,
    )

    reloaded = fx.read_plan(client, plan["id"])
    assert_fields(reloaded, status="ACTIVE", budget_committed_cents=0)
    assert fx.read_job(client, job["id"])["status"] == "PENDING_APPROVAL"
