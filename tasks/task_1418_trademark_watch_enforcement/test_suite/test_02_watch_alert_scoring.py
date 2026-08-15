"""Watch-alert intake scoring: provisional vs assessed variants, the
identical-presumption floor, listing pagination, schema validation, and OCC."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_version_incremented,
    assert_watch_alert,
    assess_alert,
    create_alert,
    get_alert,
    make_associate_headers,
    setup_published_record,
    triage_alert,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestProvisionalVsAssessedScore:
    def test_intake_computes_provisional_score_with_fixed_weights(
        self, api, watch_service_headers, paralegal_headers
    ):
        """PRD §3.3: "Intake computes a provisional confusion score with fixed
        weights: half the mark similarity, three-tenths the goods similarity, and
        two-tenths the channel similarity are summed, the raw sum is rounded half-up
        to two decimal places, and — because the provisional variant carries no fame
        adjustment — the result is clamped into the 0-to-100 band."
        PRD §3.3: "The result is stored on `provisional_score` and bucketed into
        `provisional_tier`: `HIGH` at 70 or above, `MEDIUM` at 40 or above, otherwise
        `LOW`."

        Design: Difficulty/dual_variant_calc/provisional_vs_assessed_confusion_score
        """
        _, record = setup_published_record(classes=(9, 25))
        res = api.create_watch_alert(
            {
                "trademark_record_id": record["id"],
                "source": "WATCH_SERVICE",
                "conflicting_mark_text": "AKME",
                "conflicting_owner": "Rival Co",
                "conflicting_classes": [9],
                "similarity_mark": 80,
                "similarity_goods": 70,
                "similarity_channels": 60,
            },
            watch_service_headers,
        )
        alert = validate_success(res, 201)
        assert_watch_alert(alert)
        assert alert["provisional_score"] == pytest.approx(73.00, abs=0.001)
        assert alert["provisional_tier"] == "HIGH"
        assert alert["status"] == "NEW"
        assert alert["assessment_round"] == 0
        assert alert["final_score"] is None
        assert alert["final_tier"] is None

    def test_assessed_variant_differs_from_provisional_on_same_inputs(
        self, api, paralegal_headers, associate_headers
    ):
        """PRD §3.3: "The assessed variant replaces the fixed weights with the
        attorney's: the weighted sum is rounded half-up to two decimal places, the
        fame adjustment is added, the result is clamped to the 0-to-100 band, the
        identical-presumption floor at 85 applies on the same dual-similarity
        condition, and the tier is bucketed with the same 70/40 cutoffs."
        PRD §3.3: "Each accepted assessment increments `assessment_round` by one,
        recomputes and stores `final_score` and `final_tier`, and increments the
        alert's `version` by one — so identical similarity triples generally yield a
        different assessed score than the provisional one."

        Design: Difficulty/dual_variant_calc/provisional_vs_assessed_confusion_score
        """
        _, record = setup_published_record(classes=(9, 25))
        alert = create_alert(record["id"], 80, 70, 60)
        alert = triage_alert(alert["id"])
        assessed = assess_alert(alert["id"], alert["version"],
                                weight_mark=0.6, weight_goods=0.3,
                                weight_channels=0.1, fame_adjustment=5,
                                rationale="famous mark in class 9")
        assert assessed["final_score"] == pytest.approx(80.00, abs=0.001)
        assert assessed["final_tier"] == "HIGH"
        assert assessed["assessment_round"] == 1
        assert assessed["provisional_score"] == pytest.approx(73.00, abs=0.001)
        assert assessed["final_score"] != pytest.approx(assessed["provisional_score"])
        assert_version_incremented(assessed["version"], alert["version"])


class TestIdenticalPresumptionFloor:
    def test_floor_lifts_score_when_mark_and_goods_at_least_90(
        self, api, watch_service_headers
    ):
        """PRD §3.3: "An identical-presumption floor then applies: when both
        `similarity_mark` and `similarity_goods` are at least 90, the score is raised
        to at least 85."

        Design: Difficulty/combinatorial_formula/confusion_score_identical_presumption_floor
        """
        _, record = setup_published_record(classes=(9, 25))
        res = api.create_watch_alert(
            {
                "trademark_record_id": record["id"],
                "source": "WATCH_SERVICE",
                "conflicting_mark_text": "ACME",
                "conflicting_owner": "Clone Co",
                "conflicting_classes": [9],
                "similarity_mark": 90,
                "similarity_goods": 90,
                "similarity_channels": 0,
            },
            watch_service_headers,
        )
        alert = validate_success(res, 201)
        # Branch-free weighted sum is 0.5*90 + 0.3*90 + 0.2*0 == 72.00; the floor
        # lifts it to 85.00.
        assert alert["provisional_score"] == pytest.approx(85.00, abs=0.001)
        assert alert["provisional_score"] != pytest.approx(72.00, abs=0.001)
        assert alert["provisional_tier"] == "HIGH"

    def test_floor_not_engaged_one_point_below_the_condition(
        self, api, watch_service_headers
    ):
        """PRD §3.3: "An identical-presumption floor then applies: when both
        `similarity_mark` and `similarity_goods` are at least 90, the score is raised
        to at least 85."
        PRD §3.3: "Intake computes a provisional confusion score with fixed weights:
        half the mark similarity, three-tenths the goods similarity, and two-tenths
        the channel similarity are summed, the raw sum is rounded half-up to two
        decimal places, and — because the provisional variant carries no fame
        adjustment — the result is clamped into the 0-to-100 band."

        Design: Difficulty/combinatorial_formula/confusion_score_identical_presumption_floor
        """
        _, record = setup_published_record(classes=(9, 25))
        res = api.create_watch_alert(
            {
                "trademark_record_id": record["id"],
                "source": "WATCH_SERVICE",
                "conflicting_mark_text": "ACME",
                "conflicting_owner": "Clone Co",
                "conflicting_classes": [9],
                "similarity_mark": 89,
                "similarity_goods": 90,
                "similarity_channels": 0,
            },
            watch_service_headers,
        )
        alert = validate_success(res, 201)
        # 0.5*89 + 0.3*90 + 0.2*0 == 71.50; similarity_mark 89 < 90, so no floor.
        assert alert["provisional_score"] == pytest.approx(71.50, abs=0.001)
        assert alert["provisional_tier"] == "HIGH"


class TestAlertListingAndValidation:
    def test_alert_list_pagination_defaults_and_envelope(
        self, api, watch_service_headers, paralegal_headers
    ):
        """PRD §2.3: "`limit` sets the maximum number of items returned; it defaults
        to 10, with a minimum of 1 and a maximum of 100. `offset` sets the number of
        items skipped and defaults to 0."
        PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`,
        `total_count`, and `has_more`."

        Design: Corner/entities/alert_list_pagination_defaults_and_envelope
        """
        _, record = setup_published_record(classes=(9,))
        for i in range(12):
            create_alert(record["id"], similarity_mark=10, similarity_goods=10,
                         similarity_channels=10,
                         conflicting_mark_text=f"M{i + 1:02d}",
                         conflicting_owner=f"O{i + 1}")

        page1_res = api.list_watch_alerts(paralegal_headers)
        assert page1_res.json()["response_type"] == "array"
        assert isinstance(page1_res.json()["meta"].get("api_request_id"), str)
        page1, meta1 = validate_paginated(page1_res)
        assert len(page1) == 10
        assert meta1["total_count"] == 12
        assert meta1["has_more"] is True
        assert meta1["limit"] == 10
        assert meta1["offset"] == 0

        page2_res = api.list_watch_alerts(paralegal_headers, params={"offset": 10})
        assert page2_res.json()["response_type"] == "array"
        page2, meta2 = validate_paginated(page2_res)
        assert len(page2) == 2
        assert meta2["total_count"] == 12
        assert meta2["has_more"] is False

    def test_assess_weights_not_summing_to_one_rejected(
        self, api, paralegal_headers, associate_headers
    ):
        """PRD §3.3: "Every assessment carries the attorney's own `weight_mark`,
        `weight_goods`, and `weight_channels` — which must sum to 1.0 within a
        tolerance of 0.0001 — an integer `fame_adjustment` between -20 and 20
        inclusive, a free-text `rationale`, and the OCC field
        `expected_watch_alert_version`."
        PRD §2.10: "the request body satisfies the endpoint's input schema: required
        fields present, no unknown fields, enum values valid, assessment weights
        summing to 1.0, `hit_index` in range, and seizure-line entries positive
        integers, else `ERR_VALIDATION`."

        Design: Corner/validations/assess_weights_not_summing_to_one_rejected
        """
        _, record = setup_published_record(classes=(9,))
        alert = create_alert(record["id"], 80, 70, 60)
        alert = triage_alert(alert["id"])
        res = api.assess_alert(
            alert["id"],
            {
                "weight_mark": 0.5,
                "weight_goods": 0.3,
                "weight_channels": 0.3,
                "fame_adjustment": 0,
                "rationale": "bad weights",
                "expected_watch_alert_version": alert["version"],
            },
            associate_headers,
        )
        validate_error(res, ApiErrorId.ERR_VALIDATION, expected_status=400)
        after = get_alert(alert["id"])
        assert after["assessment_round"] == 0
        assert after["status"] == "TRIAGED"


class TestOptimisticConcurrencyOnAssess:
    def test_occ_stale_version_on_assess_rejected(
        self, api, paralegal_headers, associate_headers
    ):
        """PRD §2.9: "Recording an assessment against a watch alert requires the
        request to carry `expected_watch_alert_version` holding the alert's `version`
        as the caller last observed it; each accepted assessment legitimately
        supersedes the current `final_score` and `final_tier` and increments the
        alert's `version` by one, so a caller working from a stale read would
        silently overwrite a newer attorney's assessment."
        PRD §2.9: "In both cases, a mismatch with the entity's current `version` is
        rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/occ_stale_version_on_assess_rejected
        """
        _, record = setup_published_record(classes=(9,))
        alert = create_alert(record["id"], 80, 70, 60)
        alert = triage_alert(alert["id"])
        stale_version = alert["version"]

        first = assess_alert(alert["id"], stale_version, weight_mark=0.6,
                             weight_goods=0.3, weight_channels=0.1,
                             fame_adjustment=5, rationale="first")
        assert first["assessment_round"] == 1
        assert first["version"] == stale_version + 1

        res = api.assess_alert(
            alert["id"],
            {
                "weight_mark": 0.5,
                "weight_goods": 0.3,
                "weight_channels": 0.2,
                "fame_adjustment": 0,
                "rationale": "stale retry",
                "expected_watch_alert_version": stale_version,
            },
            make_associate_headers("assoc_2"),
        )
        validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
        after_stale = get_alert(alert["id"])
        assert after_stale["assessment_round"] == 1

        fresh = get_alert(alert["id"])
        retried = assess_alert(alert["id"], fresh["version"], weight_mark=0.5,
                               weight_goods=0.3, weight_channels=0.2,
                               fame_adjustment=0, rationale="fresh retry",
                               user_id="assoc_2")
        assert retried["assessment_round"] == 2
        assert retried["final_score"] == pytest.approx(73.00, abs=0.001)
        assert retried["version"] == fresh["version"] + 1
