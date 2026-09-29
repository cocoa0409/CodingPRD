"""Derived figures: constants, input-set filtering, precision and variant choice."""

from test_helpers import (
    ARCHIVIST_A,
    COUNSEL_A,
    OFFICER_A,
    OFFICER_B,
    PRESERV_A,
    assert_cost_breakdown,
    assert_fields,
    assert_money_cents,
    assert_nulls,
    assert_one_decimal,
    assert_score_2dp,
    created,
    factories as f,
    fixtures as fx,
    ok,
)


def test_a_zone_sits_compliant_on_both_ceilings_and_slips_marginal_one_tenth_above(
    client,
):
    """PRD §2.11: "A zone is `COMPLIANT` when its temperature is at most 18.0 degrees Celsius
    **and** its relative humidity is at least 30.0 percent and at most 50.0 percent."
    PRD §2.11: "Otherwise, a zone is `MARGINAL` when its temperature is at most 21.0 degrees
    Celsius **and** its relative humidity is at least 30.0 percent and at most 55.0 percent."
    PRD §2.11: "Every one of those bounds is inclusive: a reading of 18.0 degrees at 50.0
    percent humidity is `COMPLIANT`, whereas 18.1 degrees is not, and a humidity of 29.9
    percent is `NON_COMPLIANT` no matter how cool the vault is."
    PRD §3.6: "Recording a further environment reading overwrites both `temperature_c` and
    `relative_humidity_pct`, re-derives `environmental_status` from the new pair alone, and
    increments `reading_count` by 1."

    Design: Corner/calculations/zone_status_compliant_exactly_at_18c_and_50pct_then_marginal_one_tenth_above
    """
    zone = created(client.create_storage_zone(
        f.storage_zone_payload(18.0, 50.0, 1, zone_code="Z-EDGE"), PRESERV_A))
    assert zone["environmental_status"] == "COMPLIANT"

    updated = ok(client.record_environment_reading(
        zone["id"], f.environment_reading_payload(18.1, 50.0), PRESERV_A))

    assert_fields(updated, environmental_status="MARGINAL", reading_count=2)
    assert_one_decimal(updated, "temperature_c", 18.1)
    assert_one_decimal(updated, "relative_humidity_pct", 50.0)


def test_the_at_risk_census_counts_only_shelvable_tape_and_film(client):
    """PRD §3.6: "**The at-risk census** sums `unit_count` over every archival item whose
    `storage_zone_id` matches the plan's zone, whose status is one of `UNPROCESSED`,
    `ACCESSIONED` or `IN_TREATMENT`, whose `original_format` is `MAGNETIC_TAPE` or `FILM`, and
    whose `digital_surrogate_available` is false."
    PRD §3.6: "Items in `ON_LOAN`, `PENDING_DISPOSITION`, `DEACCESSIONED` or `REJECTED_ITEM`
    are excluded outright, as are items in every format other than magnetic tape and film."
    PRD §3.6: "The result is a whole number of units and is order-independent."
    PRD §3.6: "Activation takes the plan's first at-risk census of its zone."

    Design: Corner/calculations/at_risk_unit_count_sums_only_unloaned_tape_and_film_units
    """
    zone = fx.make_zone(
        client, zone_code="Z-AR", temperature_c=16.0, relative_humidity_pct=42.0,
        max_overlapping_migration_jobs=1,
    )
    series = fx.make_series(
        client,
        title="Broadcast Masters",
        business_unit="Corporate Communications",
        sensitivity_ceiling="INTERNAL",
        annual_volume_linear_feet=30,
        earliest_record_year=1968,
        latest_record_year=2004,
    )
    shelved = fx.make_holding(
        client,
        series=series,
        zone=zone,
        stage="RECEIVED",
        declared_unit_count=53,
        item_specs=[
            {"unit_count": 5, "original_format": "MAGNETIC_TAPE",
             "condition_grade": "FAIR", "item_label": "TAPE-A"},
            {"unit_count": 8, "original_format": "FILM",
             "condition_grade": "FAIR", "item_label": "FILM-A"},
            {"unit_count": 40, "original_format": "PAPER", "item_label": "PAPER-A"},
        ],
    )
    loaned = fx.make_holding(
        client,
        series=series,
        zone=zone,
        item_specs=[{"unit_count": 7, "original_format": "MAGNETIC_TAPE",
                     "item_label": "TAPE-LOANED"}],
    )
    fx.make_loan(
        client,
        loaned.item_id,
        "2026-08-01T00:00:00Z",
        "2026-10-01T00:00:00Z",
        stage="OUT",
        units=7,
        exhibit_name="Fifty Years On Air",
    )

    plan = fx.make_plan(
        client, zone["id"], plan_name="Magnetic Media Rescue", budget_cents=500000
    )

    assert_fields(plan, status="ACTIVE", at_risk_unit_count=13)
    assert fx.read_item(client, loaned.item_id)["status"] == "ON_LOAN"
    paper = fx.read_item(client, shelved.item_ids[2])
    assert paper["status"] == "UNPROCESSED"
    assert fx.read_item(client, shelved.item_ids[0])["digital_surrogate_available"] is False


def test_ninety_nine_pages_stay_below_the_first_volume_tier(client):
    """PRD §3.7: "Each line's page count is that item's `unit_count` multiplied by eleven
    pages per unit; the total page count across all lines is the request's
    `requested_page_count`."
    PRD §3.7: "A single volume tier is selected once from that total and applied to every
    line: no discount when the total is 100 pages or fewer, 7.5 percent when it lies between
    101 and 500 pages inclusive, and 12.5 percent when it is 501 pages or more."
    PRD §3.7: "Each line's gross amount is its page count multiplied by the per-page rate for
    the requester's class — 0 cents per page for `INTERNAL_BUSINESS`, 35 cents for
    `EXTERNAL_RESEARCHER` and 90 cents for `MEDIA`."
    PRD §3.7: "`service_fee_cents` is that subtotal plus a base handling charge of 2,500
    cents, plus a media licensing surcharge of 15,000 cents when and only when the requester's
    class is `MEDIA`."
    PRD §3.7: "Both branches stamp `decided_by` from `X-User-ID`, store the supplied
    `approval_scope`, and compute and store `service_fee_cents`."

    Design: Corner/calculations/access_service_fee_tier_zero_at_99_pages_external_researcher
    """
    holding = fx.make_holding(
        client,
        item_specs=[{"unit_count": 9, "sensitivity_level": "INTERNAL",
                     "item_label": "AR-1972-2008"}],
        schedule_overrides={"code": "GEN-21", "retention_years": 21,
                            "disposition_action": "REVIEW",
                            "min_appraisal_score_for_permanent": 79.00},
        series_overrides={"title": "Annual Report Files",
                          "business_unit": "Investor Relations",
                          "sensitivity_ceiling": "INTERNAL",
                          "annual_volume_linear_feet": 12,
                          "earliest_record_year": 1972,
                          "latest_record_year": 2008},
    )
    case = fx.screened_case(
        client,
        holding,
        decision="GRANT_FULL",
        redaction_required=False,
        requester_overrides={"display_name": "M. Oyelaran",
                             "requester_class": "EXTERNAL_RESEARCHER",
                             "affiliation": "School of Business History",
                             "nda_on_file": False},
        purpose="Dividend policy 1972-1990.",
    )

    approved = ok(client.approve_access_request(
        case.request_id, f.approve_request_payload("FULL"), OFFICER_B))

    assert_fields(
        approved,
        status="APPROVED",
        requested_page_count=99,
        post_screen_risk_score=45,
        approval_scope="FULL",
        decided_by="officer-b",
    )
    assert_money_cents(approved, "service_fee_cents", 5965)


def test_the_post_screen_risk_score_clamps_at_one_hundred(client):
    """PRD §3.7: "Both passes start from the requester's class weight: 10 points for
    `INTERNAL_BUSINESS`, 30 for `EXTERNAL_RESEARCHER` and 45 for `MEDIA`."
    PRD §3.7: "Both clamp the result into the range 0 through 100 inclusive, and both work in
    whole integers with no rounding."
    PRD §3.7: "It adds the greatest sensitivity weight found across the actual items named in
    `requested_item_ids`, using each item's own `sensitivity_level` and the same four weights,
    with no filter on item status — an item that has since drifted into `PENDING_DISPOSITION`
    still contributes its sensitivity."
    PRD §3.7: "It adds the sensitivity weight of the series' `sensitivity_ceiling` as a single
    upper-bound proxy for the holdings — 0 points for `PUBLIC`, 15 for `INTERNAL`, 35 for
    `CONFIDENTIAL` and 60 for `RESTRICTED` — and it ignores legal holds and redaction
    entirely."
    PRD §3.7: "All three are stored, `completed_at` is stamped from the logical clock, and the
    post-screen risk pass runs onto the parent request's `post_screen_risk_score`."

    Design: Corner/calculations/confidentiality_risk_post_screen_clamps_at_100_for_media_on_restricted_item
    """
    holding = fx.make_holding(
        client,
        item_specs=[{"unit_count": 2, "sensitivity_level": "RESTRICTED",
                     "item_label": "EXCO-MINUTES"}],
        schedule_overrides={"code": "GEN-22", "retention_years": 22,
                            "disposition_action": "REVIEW",
                            "min_appraisal_score_for_permanent": 81.00},
        series_overrides={"title": "Executive Committee Minutes",
                          "business_unit": "Corporate Secretary",
                          "sensitivity_ceiling": "CONFIDENTIAL",
                          "annual_volume_linear_feet": 6,
                          "earliest_record_year": 1965,
                          "latest_record_year": 2003},
    )
    case = fx.make_access_request(
        client,
        holding,
        requester_overrides={"display_name": "V. Kaltenbrunner",
                             "requester_class": "MEDIA",
                             "affiliation": "National Business Daily",
                             "nda_on_file": False},
        purpose="Investigation into the 1988 restructuring.",
    )
    assert case.request["prelim_risk_score"] == 80
    fx.drive_to_screening(client, case)
    fx.open_screening(client, case)

    screening = ok(client.complete_screening(
        case.screening_id,
        f.complete_screening_payload(
            decision="GRANT_REDACTED",
            redaction_required=False,
            screening_note="Named individuals remain sensitive.",
        ),
        OFFICER_A,
    ))

    assert_fields(screening, status="COMPLETED", screened_by="officer-a")
    assert_fields(
        fx.read_request(client, case.request_id),
        post_screen_risk_score=100,
        prelim_risk_score=80,
        status="SCREENING",
    )


def test_a_package_sitting_exactly_on_both_gates_still_certifies(client):
    """PRD §3.8: "Two gates then decide the outcome, and they are evaluated strictly in this
    order."
    PRD §3.8: "First, `max_gap_years` must be at most 3 whole years."
    PRD §3.8: "Second, `continuous_use_coverage_pct` must be at least 25.00."
    PRD §3.8: "When both pass, the package moves `DRAFT → CERTIFIED` and `certified_at` is
    stamped from the logical clock."
    PRD §3.8: "The coverage span opens at `claimed_first_use_year` and closes at the calendar
    year of the logical clock read in UTC, and the span length is the closing year minus the
    opening year, plus one."
    PRD §3.8: "`continuous_use_coverage_pct` is 100 multiplied by `covered_year_count`,
    divided by the span length, rounded half up to two decimal places."

    Design: Corner/calculations/continuous_use_coverage_exactly_at_min_coverage_pct_certifies
    """
    holding = fx.make_holding(
        client,
        item_specs=[
            {"unit_count": 1, "item_label": "CATALOGUE-2019", "brand_use_year": 2019},
            {"unit_count": 1, "item_label": "CATALOGUE-2023", "brand_use_year": 2023},
        ],
        schedule_overrides={"code": "GEN-23", "retention_years": 23,
                            "disposition_action": "REVIEW",
                            "min_appraisal_score_for_permanent": 76.00},
        series_overrides={"title": "Trade Dress Files", "business_unit": "Brand",
                          "sensitivity_ceiling": "INTERNAL",
                          "annual_volume_linear_feet": 8,
                          "earliest_record_year": 2019,
                          "latest_record_year": 2024},
        zone_overrides={"zone_code": "Z-TD", "relative_humidity_pct": 45.0},
    )
    package = fx.make_package(
        client, holding.series_id, 2019, holding.item_ids, mark_name="HERITAGE BLUE"
    )

    certified = ok(client.certify_evidence_package(package["id"], COUNSEL_A))

    assert_fields(
        certified,
        status="CERTIFIED",
        qualifying_evidence_count=2,
        covered_year_count=2,
        max_gap_years=3,
    )
    assert_score_2dp(certified, "continuous_use_coverage_pct", 25.00)
    assert_nulls(certified, "rejection_code")


def test_undated_and_out_of_span_evidence_drops_out_and_duplicate_years_collapse(client):
    """PRD §3.8: "An evidence item qualifies only when all four conditions hold: it is named in
    `evidence_item_ids`, its `brand_use_year` is not null, its status is not `DEACCESSIONED`,
    and its `brand_use_year` falls inside the closed span, meaning at or after the opening year
    and at or before the closing year."
    PRD §3.8: "`qualifying_evidence_count` is the number of items that qualify."
    PRD §3.8: "With at least one qualifying item, take the distinct `brand_use_year` values of
    the qualifying items in ascending order — duplicate years collapse into a single covered
    year — and let `covered_year_count` be how many there are."
    PRD §3.8: "`continuous_use_coverage_pct` is 100 multiplied by `covered_year_count`,
    divided by the span length, rounded half up to two decimal places."

    Design: Corner/calculations/continuous_use_coverage_drops_null_and_out_of_span_years_and_collapses_duplicates
    """
    holding = fx.make_holding(
        client,
        item_specs=[
            {"unit_count": 1, "item_label": "USAGE-2020-A", "original_format": "PHOTO",
             "brand_use_year": 2020},
            {"unit_count": 1, "item_label": "USAGE-2020-B", "original_format": "PHOTO",
             "brand_use_year": 2020},
            {"unit_count": 1, "item_label": "USAGE-2024", "original_format": "PHOTO",
             "brand_use_year": 2024},
            {"unit_count": 1, "item_label": "USAGE-UNDATED", "original_format": "PHOTO"},
            {"unit_count": 1, "item_label": "USAGE-2016", "original_format": "PHOTO",
             "brand_use_year": 2016},
        ],
        schedule_overrides={"code": "GEN-24", "retention_years": 24,
                            "disposition_action": "REVIEW",
                            "min_appraisal_score_for_permanent": 77.00},
        series_overrides={"title": "Logo Usage Files", "business_unit": "Brand",
                          "sensitivity_ceiling": "INTERNAL",
                          "annual_volume_linear_feet": 5,
                          "earliest_record_year": 2016,
                          "latest_record_year": 2024},
        zone_overrides={"zone_code": "Z-LOGO", "relative_humidity_pct": 45.0},
    )
    assert fx.read_item(client, holding.item_ids[3])["brand_use_year"] is None
    package = fx.make_package(
        client, holding.series_id, 2020, holding.item_ids, mark_name="ROUNDEL MARK"
    )

    certified = ok(client.certify_evidence_package(package["id"], COUNSEL_A))

    assert_fields(
        certified,
        status="CERTIFIED",
        qualifying_evidence_count=3,
        covered_year_count=2,
        max_gap_years=3,
    )
    assert_score_2dp(certified, "continuous_use_coverage_pct", 28.57)


def test_an_exact_half_cent_surcharge_rounds_up_and_not_down(client):
    """PRD §3.6: "Step one sets `subtotal_cents` to the per-unit rate for the item's
    `original_format` multiplied by the job's `units`."
    PRD §3.6: "The rates are 900 cents per unit for `PAPER`, 1,800 for `PHOTO`, 3,600 for
    `FILM`, 4,200 for `MAGNETIC_TAPE` and 600 for `BORN_DIGITAL`; the rate is keyed on the
    carrier being migrated *from*, never on `target_format`."
    PRD §3.6: "Step five sets `condition_surcharge_cents` to the sum of `discounted_cents` and
    `handling_fee_cents`, multiplied by the surcharge rate for the item's `condition_grade` —
    0.00 for `GOOD`, 0.05 for `FAIR`, 0.12 for `POOR` and 0.20 for `UNSTABLE` — rounded half
    up to whole cents."
    PRD §3.6: "Step six sets `committed_cost_cents` to `discounted_cents` plus
    `handling_fee_cents` plus `condition_surcharge_cents`."
    PRD §2.10: "All monetary amounts are integer counts of cents; there are no fractional
    cents anywhere in the API, and every rounding step named in §3 uses the round-half-up
    convention."

    Design: Corner/calculations/migration_job_cost_step5_surcharge_rounds_half_cent_up
    """
    holding = fx.make_holding(
        client,
        item_specs=[{"unit_count": 95, "condition_grade": "FAIR",
                     "original_format": "PAPER", "sensitivity_level": "INTERNAL",
                     "item_label": "DRAWINGS-1955-1998"}],
        schedule_overrides={"code": "GEN-25", "retention_years": 25,
                            "disposition_action": "REVIEW",
                            "min_appraisal_score_for_permanent": 84.00},
        series_overrides={"title": "Engineering Drawings",
                          "business_unit": "Engineering",
                          "sensitivity_ceiling": "INTERNAL",
                          "annual_volume_linear_feet": 44,
                          "earliest_record_year": 1955,
                          "latest_record_year": 1998},
        zone_overrides={"zone_code": "Z-ENG", "temperature_c": 17.0,
                        "relative_humidity_pct": 46.0,
                        "max_overlapping_migration_jobs": 2},
    )
    plan = fx.make_plan(
        client, holding.zone_id, plan_name="Drawing Digitisation", budget_cents=400000
    )

    job = created(client.create_migration_job(
        f.migration_job_payload(
            plan["id"], holding.item_id, units=95,
            target_format="PRESERVATION_TIFF",
            window_start="2026-09-01T00:00:00Z",
            window_end="2026-09-30T00:00:00Z",
        ),
        PRESERV_A,
    ))

    assert job["status"] == "PENDING_APPROVAL"
    assert_cost_breakdown(
        job,
        subtotal=85500,
        discount_pct=0.06,
        discounted=80370,
        handling=4000,
        surcharge=4219,
        committed=88589,
    )


def test_screening_scores_the_series_and_leaves_the_final_pass_untouched(client):
    """PRD §3.2: "Screening writes `screening_score`."
    PRD §3.2: "The age bonus is one point for every complete five years of that span,
    discarding any remainder, capped at 10 points."
    PRD §3.2: "The volume penalty is zero when the series accrues 50 linear feet per year or
    less; above that floor it is one point for every complete 10 linear feet by which the
    annual volume exceeds 50, again discarding any remainder, capped at 15 points and never
    negative."
    PRD §3.2: "The core score is the informational rating multiplied by 3, plus the evidential
    rating multiplied by 3, plus the admitted brand-heritage rating multiplied by 2, plus the
    uniqueness rating multiplied by 2."
    PRD §3.2: "On the admitted brand-heritage rating: the screening variant admits
    `brand_heritage_value` unconditionally, whereas the final variant admits it only when a
    trademark evidence package for the same series stands in `CERTIFIED` status at the moment
    of finalisation, and otherwise substitutes zero."
    PRD §3.2: "On the provenance multiplier: the screening variant always uses 1.00, even when
    `provenance_verified` is false, whereas the final variant uses 1.00 when
    `provenance_verified` is true and 0.80 when it is false."
    PRD §3.2: "Disposition derivation runs only in the final pass."

    Design: Corner/calculations/appraisal_screening_variant_selected_at_screen_leaves_final_fields_null
    """
    series = fx.make_series(
        client,
        schedule_overrides={"code": "GEN-26", "retention_years": 26,
                            "disposition_action": "REVIEW",
                            "min_appraisal_score_for_permanent": 70.00},
        title="Product Launch Files",
        business_unit="Marketing",
        sensitivity_ceiling="INTERNAL",
        annual_volume_linear_feet=40,
        earliest_record_year=1980,
        latest_record_year=2010,
    )
    appraisal = fx.make_appraisal(
        client,
        series,
        informational_value=8,
        evidential_value=7,
        brand_heritage_value=5,
        uniqueness_factor=6,
        provenance_verified=False,
    )

    screened = ok(client.screen_appraisal(appraisal["id"], ARCHIVIST_A))

    assert screened["status"] == "SCREENED"
    assert_score_2dp(screened, "screening_score", 73.00)
    assert_nulls(screened, "final_score", "recommended_disposition")
    assert fx.read_series(client, series["id"])["disposition_state"] == "ACTIVE"
