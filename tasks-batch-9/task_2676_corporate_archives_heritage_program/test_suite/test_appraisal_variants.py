"""The two appraisal scoring variants and the two confidentiality risk passes."""

from test_helpers import (
    ARCHIVIST_A,
    DIRECTOR_A,
    OFFICER_A,
    assert_score_2dp,
    factories as f,
    fixtures as fx,
    ok,
)


def _founder_correspondence(client):
    """A series scoring 70.00 at screening and 46.40 at finalisation."""
    schedule = fx.make_schedule(
        client,
        retention_years=10,
        disposition_action="DESTROY",
        min_appraisal_score_for_permanent=70.00,
    )
    series = fx.make_series(
        client,
        schedule["id"],
        title="Founder Correspondence",
        business_unit="CORP",
        sensitivity_ceiling="INTERNAL",
        annual_volume_linear_feet=120,
        earliest_record_year=1901,
        latest_record_year=1980,
    )
    appraisal = fx.make_appraisal(
        client,
        series,
        informational_value=8,
        evidential_value=7,
        brand_heritage_value=6,
        uniqueness_factor=5,
        provenance_verified=False,
    )
    return schedule, series, appraisal


def test_screening_and_final_scores_diverge_on_one_appraisal(client):
    """PRD §3.2: "The core score is the informational rating multiplied by 3, plus
    the evidential rating multiplied by 3, plus the admitted brand-heritage rating
    multiplied by 2, plus the uniqueness rating multiplied by 2."
    PRD §3.2: "On the admitted brand-heritage rating: the screening variant admits
    `brand_heritage_value` unconditionally, whereas the final variant admits it only
    when a trademark evidence package for the same series stands in `CERTIFIED`
    status at the moment of finalisation, and otherwise substitutes zero."
    PRD §3.2: "On the provenance multiplier: the screening variant always uses 1.00,
    even when `provenance_verified` is false, whereas the final variant uses 1.00
    when `provenance_verified` is true and 0.80 when it is false."

    Design: Difficulty/dual_variant_calc/appraisal_score_screening_vs_final_diverge_on_one_appraisal
    """
    _, _, appraisal = _founder_correspondence(client)

    screened = ok(client.screen_appraisal(appraisal["id"], ARCHIVIST_A))
    assert_score_2dp(screened, "screening_score", 70.00)
    assert screened["final_score"] is None

    finalized = ok(client.finalize_appraisal(appraisal["id"], DIRECTOR_A))
    assert_score_2dp(finalized, "screening_score", 70.00)
    assert_score_2dp(finalized, "final_score", 46.40)
    assert finalized["status"] == "FINAL"


def test_final_variant_recommendation_drives_the_series_out_of_active(client):
    """PRD §3.2: "When the rounded `final_score` is greater than or equal to the
    governing schedule's `min_appraisal_score_for_permanent`, `recommended_disposition`
    is `PERMANENT`; otherwise it is the schedule's `disposition_action`, so one of
    `DESTROY`, `REVIEW` or `TRANSFER`."
    PRD §3.2: "From `ACTIVE`, a recommendation of `DESTROY`, `REVIEW` or `TRANSFER`
    moves the series to `ELIGIBLE_FOR_DISPOSITION` — but only if the logical clock
    already stands at or after the series' `retention_expiry_utc`."
    PRD §3.2: "When the final variant does admit the rating it sets
    `brand_heritage_counted` to true, otherwise false."

    Design: Difficulty/dual_variant_calc/appraisal_score_screening_vs_final_diverge_on_one_appraisal
    """
    _, series, appraisal = _founder_correspondence(client)
    ok(client.screen_appraisal(appraisal["id"], ARCHIVIST_A))

    finalized = ok(client.finalize_appraisal(appraisal["id"], DIRECTOR_A))
    assert finalized["brand_heritage_counted"] is False
    assert finalized["recommended_disposition"] == "DESTROY"

    reloaded = fx.read_series(client, series["id"])
    assert reloaded["disposition_state"] == "ELIGIBLE_FOR_DISPOSITION"
    assert reloaded["current_appraisal_id"] == appraisal["id"]


def _media_request_under_screening(client):
    """A MEDIA request over an INTERNAL item inside a CONFIDENTIAL series."""
    holding = fx.make_holding(
        client,
        item_specs=[{"unit_count": 3, "original_format": "PHOTO",
                     "sensitivity_level": "INTERNAL"}],
        series_overrides={"sensitivity_ceiling": "CONFIDENTIAL",
                          "annual_volume_linear_feet": 40,
                          "earliest_record_year": 1975,
                          "latest_record_year": 1999},
    )
    requester = fx.make_requester(
        client, requester_class="MEDIA", nda_on_file=False
    )
    case = fx.make_access_request(client, holding, requester=requester)
    fx.drive_to_screening(client, case)
    fx.open_screening(client, case)
    return holding, case


def test_prelim_risk_uses_the_series_ceiling_as_a_proxy(client):
    """PRD §3.7: "Both passes start from the requester's class weight: 10 points for
    `INTERNAL_BUSINESS`, 30 for `EXTERNAL_RESEARCHER` and 45 for `MEDIA`."
    PRD §3.7: "It adds the sensitivity weight of the series' `sensitivity_ceiling` as
    a single upper-bound proxy for the holdings — 0 points for `PUBLIC`, 15 for
    `INTERNAL`, 35 for `CONFIDENTIAL` and 60 for `RESTRICTED` — and it ignores legal
    holds and redaction entirely."

    Design: Difficulty/dual_variant_calc/confidentiality_risk_prelim_vs_post_screen_diverge_on_one_request
    """
    _, case = _media_request_under_screening(client)

    request = fx.read_request(client, case.request_id)
    assert request["prelim_risk_score"] == 80
    assert request["post_screen_risk_score"] is None
    assert case.screening["max_item_sensitivity"] == "INTERNAL"


def test_post_screen_risk_replaces_the_proxy_with_the_item_sensitivities(client):
    """PRD §3.7: "The post-screen pass runs when a screening completes and replaces
    the proxy with reality. It adds the greatest sensitivity weight found across the
    actual items named in `requested_item_ids`, using each item's own
    `sensitivity_level` and the same four weights, with no filter on item status — an
    item that has since drifted into `PENDING_DISPOSITION` still contributes its
    sensitivity."
    PRD §3.7: "When and only when the decision is `CHANGES_REQUESTED`, the parent
    request moves `SCREENING → CHANGES_REQUESTED`."

    Design: Difficulty/dual_variant_calc/confidentiality_risk_prelim_vs_post_screen_diverge_on_one_request
    """
    _, case = _media_request_under_screening(client)

    screening = ok(
        client.complete_screening(
            case.screening_id,
            f.complete_screening_payload(
                decision="GRANT_FULL",
                redaction_required=False,
                screening_note="No restricted material identified",
            ),
            OFFICER_A,
        )
    )
    assert screening["status"] == "COMPLETED"
    assert screening["max_item_sensitivity"] == "INTERNAL"

    request = fx.read_request(client, case.request_id)
    assert request["prelim_risk_score"] == 80
    assert request["post_screen_risk_score"] == 60
    assert request["status"] == "SCREENING"
