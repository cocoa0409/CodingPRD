"""Inclusive boundaries: a permanence threshold, a set cardinality, an instant."""

from test_helpers import (
    ARCHIVIST_A,
    COUNSEL_A,
    DIRECTOR_A,
    assert_score_2dp,
    factories as f,
    failed,
    fixtures as fx,
    ok,
)
from test_helpers.api_errors import (
    ERR_NO_QUALIFYING_EVIDENCE,
    ERR_RETENTION_PERIOD_NOT_ELAPSED,
)


def test_final_score_exactly_at_the_permanence_threshold_designates_permanent(client):
    """PRD §3.1: "That last figure is the inclusive score at or above which appraisal
    designates a series permanent instead of following `disposition_action`."
    PRD §2.10: "Appraisal scores are rounded half up to 2 decimal places, and the
    threshold comparison that derives a disposition recommendation is made against the
    rounded value, not the unrounded one."
    PRD §3.2: "From `ACTIVE`, a recommendation of `PERMANENT` moves the series to
    `PERMANENT`."
    PRD §3.2: "When the final variant does admit the rating it sets
    `brand_heritage_counted` to true, otherwise false."

    Design: Difficulty/boundary_precision_check/appraisal_permanent_threshold_inclusive_at_and_one_cent_below
    """
    holding = fx.make_holding(
        client,
        item_specs=[
            {"unit_count": 1, "brand_use_year": 2018},
            {"unit_count": 1, "brand_use_year": 2022},
            {"unit_count": 1, "brand_use_year": 2026},
        ],
        schedule_overrides={"retention_years": 10, "disposition_action": "DESTROY",
                            "min_appraisal_score_for_permanent": 70.00},
        series_overrides={"annual_volume_linear_feet": 120,
                          "earliest_record_year": 1946,
                          "latest_record_year": 2025},
    )
    package = fx.certified_package(
        client, holding.series_id, 2018, holding.item_ids
    )
    assert package["status"] == "CERTIFIED"
    assert package["max_gap_years"] == 3
    assert_score_2dp(package, "continuous_use_coverage_pct", 33.33)

    appraisal = fx.make_appraisal(
        client,
        fx.read_series(client, holding.series_id),
        informational_value=8,
        evidential_value=7,
        brand_heritage_value=6,
        uniqueness_factor=5,
        provenance_verified=True,
    )
    ok(client.screen_appraisal(appraisal["id"], ARCHIVIST_A))
    finalized = ok(client.finalize_appraisal(appraisal["id"], DIRECTOR_A))

    assert_score_2dp(finalized, "final_score", 70.00)
    assert finalized["brand_heritage_counted"] is True
    assert finalized["recommended_disposition"] == "PERMANENT"

    series = fx.read_series(client, holding.series_id)
    assert series["disposition_state"] == "PERMANENT"
    assert series["current_appraisal_id"] == appraisal["id"]


def test_final_score_one_hundredth_below_the_threshold_follows_the_schedule(client):
    """PRD §3.2: "When the rounded `final_score` is greater than or equal to the
    governing schedule's `min_appraisal_score_for_permanent`, `recommended_disposition`
    is `PERMANENT`; otherwise it is the schedule's `disposition_action`, so one of
    `DESTROY`, `REVIEW` or `TRANSFER`."
    PRD §3.2: "the final variant admits it only when a trademark evidence package for
    the same series stands in `CERTIFIED` status at the moment of finalisation, and
    otherwise substitutes zero."

    Design: Difficulty/boundary_precision_check/appraisal_permanent_threshold_inclusive_at_and_one_cent_below
    """
    schedule = fx.make_schedule(
        client,
        retention_years=10,
        disposition_action="REVIEW",
        min_appraisal_score_for_permanent=58.01,
    )
    series = fx.make_series(
        client,
        schedule["id"],
        annual_volume_linear_feet=120,
        earliest_record_year=1915,
        latest_record_year=1994,
    )
    appraisal = fx.make_appraisal(
        client,
        series,
        informational_value=8,
        evidential_value=7,
        brand_heritage_value=6,
        uniqueness_factor=5,
        provenance_verified=True,
    )
    screened = ok(client.screen_appraisal(appraisal["id"], ARCHIVIST_A))
    assert_score_2dp(screened, "screening_score", 70.00)

    finalized = ok(client.finalize_appraisal(appraisal["id"], DIRECTOR_A))
    assert_score_2dp(finalized, "final_score", 58.00)
    assert finalized["brand_heritage_counted"] is False
    assert finalized["recommended_disposition"] == "REVIEW"

    assert fx.read_series(client, series["id"])["disposition_state"] == (
        "ELIGIBLE_FOR_DISPOSITION"
    )


def _brand_evidence_holding(client):
    """One item with no brand year and one evidencing use in 2026."""
    return fx.make_holding(
        client,
        item_specs=[{"unit_count": 1}, {"unit_count": 1, "brand_use_year": 2026}],
    )


def test_certify_refuses_a_package_with_zero_qualifying_items(client):
    """PRD §3.8: "An evidence item qualifies only when all four conditions hold: it is
    named in `evidence_item_ids`, its `brand_use_year` is not null, its status is not
    `DEACCESSIONED`, and its `brand_use_year` falls inside the closed span, meaning at or
    after the opening year and at or before the closing year."
    PRD §3.8: "If that count is zero the arithmetic stops right there, before any gap or
    coverage figure is computed: the request is refused with `ERR_NO_QUALIFYING_EVIDENCE`
    and the package remains in `DRAFT`, untransitioned."

    Design: Difficulty/boundary_precision_check/trademark_certify_rejects_zero_qualifying_evidence_then_accepts_one
    """
    holding = _brand_evidence_holding(client)
    package = fx.make_package(
        client, holding.series_id, 2026, [holding.items[0]["id"]]
    )

    failed(
        client.certify_evidence_package(package["id"], COUNSEL_A),
        ERR_NO_QUALIFYING_EVIDENCE,
        422,
    )

    reloaded = fx.read_package(client, package["id"])
    assert reloaded["status"] == "DRAFT"
    assert reloaded["rejection_code"] is None
    assert reloaded["certified_at"] is None


def test_certify_accepts_exactly_one_qualifying_year(client):
    """PRD §3.8: "With at least one qualifying item, take the distinct `brand_use_year`
    values of the qualifying items in ascending order — duplicate years collapse into a
    single covered year — and let `covered_year_count` be how many there are."
    PRD §3.8: "`continuous_use_coverage_pct` is 100 multiplied by `covered_year_count`,
    divided by the span length, rounded half up to two decimal places."
    PRD §3.8: "When both pass, the package moves `DRAFT → CERTIFIED` and `certified_at`
    is stamped from the logical clock."

    Design: Difficulty/boundary_precision_check/trademark_certify_rejects_zero_qualifying_evidence_then_accepts_one
    """
    holding = _brand_evidence_holding(client)
    package = fx.make_package(client, holding.series_id, 2026, holding.item_ids)

    certified = ok(client.certify_evidence_package(package["id"], COUNSEL_A))
    assert certified["qualifying_evidence_count"] == 1
    assert certified["covered_year_count"] == 1
    assert certified["max_gap_years"] == 0
    assert_score_2dp(certified, "continuous_use_coverage_pct", 100.00)
    assert certified["status"] == "CERTIFIED"
    assert certified["certified_at"] is not None


EXPIRY_INSTANT = "2025-12-31T23:59:59.000Z"
ONE_MS_EARLIER = "2025-12-31T23:59:58.999Z"


def _series_eligible_at_its_expiry_instant(client):
    """A series driven to ELIGIBLE_FOR_DISPOSITION at the exact expiry instant."""
    schedule = fx.make_schedule(
        client,
        retention_years=5,
        disposition_action="DESTROY",
        min_appraisal_score_for_permanent=75.00,
    )
    series = fx.make_series(
        client,
        schedule["id"],
        annual_volume_linear_feet=60,
        earliest_record_year=1990,
        latest_record_year=2020,
    )
    assert series["retention_expiry_utc"] == EXPIRY_INSTANT

    fx.set_clock(client, EXPIRY_INSTANT)
    appraisal = fx.make_appraisal(
        client,
        series,
        informational_value=5,
        evidential_value=5,
        brand_heritage_value=0,
        uniqueness_factor=3,
        provenance_verified=True,
    )
    ok(client.screen_appraisal(appraisal["id"], ARCHIVIST_A))
    finalized = ok(client.finalize_appraisal(appraisal["id"], DIRECTOR_A))
    assert_score_2dp(finalized, "final_score", 41.00)
    assert finalized["recommended_disposition"] == "DESTROY"
    assert fx.read_series(client, series["id"])["disposition_state"] == (
        "ELIGIBLE_FOR_DISPOSITION"
    )
    return series


def test_dispose_one_millisecond_before_the_expiry_instant_is_refused(client):
    """PRD §3.1: "The base instant is the last moment of the series' latest record year
    — the ISO 8601 UTC instant whose date is 31 December of `latest_record_year` and
    whose time is 23:59:59.000."
    PRD §2.6: "19. **Retention elapsed** — the logical clock must be at or after the
    series' `retention_expiry_utc`. Failure: `ERR_RETENTION_PERIOD_NOT_ELAPSED` (422).
    Applies to `POST /record-series/{id}/dispose`."
    PRD §2.10: "Instant comparisons are made at millisecond resolution on ISO 8601 UTC
    values."

    Design: Difficulty/boundary_precision_check/retention_expiry_instant_inclusive_to_the_millisecond
    """
    series = _series_eligible_at_its_expiry_instant(client)

    fx.set_clock(client, ONE_MS_EARLIER)
    failed(
        client.dispose_record_series(
            series["id"], f.dispose_payload("CERT-2025-0001"), DIRECTOR_A
        ),
        ERR_RETENTION_PERIOD_NOT_ELAPSED,
        422,
    )

    reloaded = fx.read_series(client, series["id"])
    assert reloaded["disposition_state"] == "ELIGIBLE_FOR_DISPOSITION"
    assert reloaded["disposition_certificate_reference"] is None


def test_dispose_at_the_exact_expiry_instant_succeeds(client):
    """PRD §3.1: "A series is retention-elapsed once the logical clock stands at or
    after `retention_expiry_utc`; the comparison is inclusive, so the expiry instant
    itself counts as elapsed."
    PRD §3.1: "The director supplies `disposition_certificate_reference`, the certificate
    of destruction or transfer, which is stored on the series."
    PRD §3.1: "Disposal is the `ArchivesDirector`'s act and the only route to the
    terminal `DISPOSED` state."

    Design: Difficulty/boundary_precision_check/retention_expiry_instant_inclusive_to_the_millisecond
    """
    series = _series_eligible_at_its_expiry_instant(client)

    fx.set_clock(client, EXPIRY_INSTANT)
    disposed = ok(
        client.dispose_record_series(
            series["id"], f.dispose_payload("CERT-2025-0001"), DIRECTOR_A
        )
    )
    assert disposed["disposition_state"] == "DISPOSED"
    assert disposed["disposition_certificate_reference"] == "CERT-2025-0001"
