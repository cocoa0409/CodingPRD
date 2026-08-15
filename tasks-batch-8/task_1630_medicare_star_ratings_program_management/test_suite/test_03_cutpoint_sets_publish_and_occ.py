"""Cut point set drafting, row replacement, publish cascade, and OCC rules."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_active_measure,
    create_cycle,
    create_draft_set,
    create_measure,
    cutpoint_row,
    get_cutpoint_set,
    get_cycle,
    get_performance,
    publish_set,
    setup_collecting_measure,
    setup_cycle_in_cutpoint_review,
    transition_cycle,
    validate_error,
    validate_success,
)


class TestCutPointRowRules:
    def test_nonmonotonic_cutpoints_rejected_both_directions(
            self, api, stars_analyst_headers):
        """PRD §3.3: "Floors must be strictly monotonic in the direction of their
        measure: for a `HIGHER_BETTER` measure the second-band floor must be
        strictly below the third, the third strictly below the fourth, and the
        fourth strictly below the fifth; for a `LOWER_BETTER` measure the order
        inverts, with the fifth-band floor strictly below the fourth, and so on
        down to the second."
        PRD §3.3: "A non-monotonic row is rejected with
        `ERR_CUTPOINTS_NON_MONOTONIC` (HTTP 400)."

        Design: Corner/validations/nonmonotonic_cutpoints_rejected_both_directions
        """
        cycle = create_cycle()
        higher = create_measure(cycle["id"], code="BCS",
                                measure_type="PROCESS", direction="HIGHER_BETTER",
                                data_source="HEDIS")
        lower = create_measure(cycle["id"], code="CMP", title="Complaints Rate",
                               domain="MEMBER_COMPLAINTS", measure_type="OUTCOME",
                               direction="LOWER_BETTER", data_source="COMPLAINTS")

        # HIGHER_BETTER violation: band_2_floor 0.70 is not below band_3_floor 0.60.
        resp = api.create_cutpoint_set(
            {"rating_cycle_id": cycle["id"], "label": "bad-higher",
             "rows": [cutpoint_row(higher["id"], 0.70, 0.60, 0.80, 0.90)]},
            stars_analyst_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CUTPOINTS_NON_MONOTONIC)

        # LOWER_BETTER violation: band_5_floor 0.60 is not below band_4_floor 0.50.
        resp = api.create_cutpoint_set(
            {"rating_cycle_id": cycle["id"], "label": "bad-lower",
             "rows": [cutpoint_row(lower["id"], 1.50, 0.90, 0.50, 0.60)]},
            stars_analyst_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CUTPOINTS_NON_MONOTONIC)

    def test_cutpoint_row_cycle_mismatch_rejected(self, api, stars_analyst_headers):
        """PRD §3.3: "Every row's measure must belong to the set's cycle, else
        `ERR_CUTPOINT_MEASURE_CYCLE_MISMATCH`."

        Design: Corner/validations/cutpoint_row_cycle_mismatch_rejected
        """
        cycle_a = create_cycle()
        cycle_b = create_cycle(measurement_year=2025, rating_year=2027,
                               benchmark_pmpm=900.0)
        measure_b = create_measure(cycle_b["id"], code="BCS")

        resp = api.create_cutpoint_set(
            {"rating_cycle_id": cycle_a["id"], "label": "cross-cycle",
             "rows": [cutpoint_row(measure_b["id"], 0.60, 0.70, 0.80, 0.90)]},
            stars_analyst_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CUTPOINT_MEASURE_CYCLE_MISMATCH)


class TestPublishCycleStateGate:
    def test_publish_in_data_collection_rejected(self, api, stars_admin_headers,
                                                 stars_analyst_headers):
        """PRD §3.3: "The cycle must be in `CUTPOINT_REVIEW` — publishing at any
        other cycle state is rejected with `ERR_CYCLE_STATE_FORBIDS` — and the set
        itself must be `DRAFT`, else `ERR_CUTPOINT_SET_IMMUTABLE`."

        Design: Difficulty/cross_entity_state_dependency/cutpoint_publish_requires_review_state
        """
        cycle = create_cycle()
        measure = create_active_measure(cycle["id"])
        cutpoint_set = create_draft_set(
            cycle["id"], [cutpoint_row(measure["id"], 0.62, 0.75, 0.90, 0.95)],
            label="official-2028")
        cycle = transition_cycle(cycle["id"], "DATA_COLLECTION")

        resp = api.publish_cutpoint_set(cutpoint_set["id"], cycle["version"],
                                        stars_admin_headers)
        validate_error(resp, ApiErrorId.ERR_CYCLE_STATE_FORBIDS)
        fetched = validate_success(api.get_cutpoint_set(cutpoint_set["id"],
                                                        stars_analyst_headers))
        assert fetched["status"] == "DRAFT", "Rejected publish leaves the set DRAFT"

    def test_publish_in_setup_rejected(self, api, stars_admin_headers,
                                       stars_analyst_headers):
        """PRD §3.3: "The cycle must be in `CUTPOINT_REVIEW` — publishing at any
        other cycle state is rejected with `ERR_CYCLE_STATE_FORBIDS` — and the set
        itself must be `DRAFT`, else `ERR_CUTPOINT_SET_IMMUTABLE`."

        SETUP is one of the 'any other cycle state' cases: the same gate fires.

        Design: Difficulty/cross_entity_state_dependency/cutpoint_publish_requires_review_state
        """
        cycle = create_cycle()
        measure = create_active_measure(cycle["id"])
        cutpoint_set = create_draft_set(
            cycle["id"], [cutpoint_row(measure["id"], 0.62, 0.75, 0.90, 0.95)],
            label="official-2028")
        cycle = get_cycle(cycle["id"])

        resp = api.publish_cutpoint_set(cutpoint_set["id"], cycle["version"],
                                        stars_admin_headers)
        validate_error(resp, ApiErrorId.ERR_CYCLE_STATE_FORBIDS)
        fetched = validate_success(api.get_cutpoint_set(cutpoint_set["id"],
                                                        stars_analyst_headers))
        assert fetched["status"] == "DRAFT"


class TestPublishCascade:
    def test_second_publish_supersedes_previous_set(self, api, stars_admin_headers):
        """PRD §3.3: "On a successful publish, five things happen atomically: the
        set becomes `PUBLISHED`; any previously `PUBLISHED` set of the same cycle
        automatically becomes `SUPERSEDED`; the cycle's `published_cutpoint_set_id`
        is re-pointed to the newly published set; every measure performance of the
        cycle recomputes its `published_star` against the new set's floors; and
        each such recompute refreshes the cycle's `live_weighted_stars`."

        Design: Difficulty/transitive_cascade/cutpoint_publish_cascade_depth2
        """
        sc = setup_cycle_in_cutpoint_review(17, 20)
        cycle_id = sc["cycle"]["id"]
        measure_id = sc["measure"]["id"]

        set_p1 = create_draft_set(
            cycle_id, [cutpoint_row(measure_id, 0.62, 0.75, 0.90, 0.95)],
            label="official-a")
        publish_set(cycle_id, set_p1["id"])

        set_p2 = create_draft_set(
            cycle_id, [cutpoint_row(measure_id, 0.60, 0.72, 0.85, 0.94)],
            label="official-b")
        publish_set(cycle_id, set_p2["id"])

        p1 = validate_success(api.get_cutpoint_set(set_p1["id"], stars_admin_headers))
        p2 = validate_success(api.get_cutpoint_set(set_p2["id"], stars_admin_headers))
        assert p1["status"] == "SUPERSEDED", (
            "The previously PUBLISHED set becomes SUPERSEDED on the second publish"
        )
        assert p2["status"] == "PUBLISHED"
        cycle = validate_success(api.get_rating_cycle(cycle_id, stars_admin_headers))
        assert cycle["published_cutpoint_set_id"] == set_p2["id"], (
            "published_cutpoint_set_id is re-pointed to the newly published set"
        )

    def test_publish_recomputes_stars_and_live_preview(self, api, stars_admin_headers):
        """PRD §3.3: "On a successful publish, five things happen atomically: the
        set becomes `PUBLISHED`; any previously `PUBLISHED` set of the same cycle
        automatically becomes `SUPERSEDED`; the cycle's `published_cutpoint_set_id`
        is re-pointed to the newly published set; every measure performance of the
        cycle recomputes its `published_star` against the new set's floors; and
        each such recompute refreshes the cycle's `live_weighted_stars`."
        PRD §2.7: "The cycle's `live_weighted_stars` is the continuously refreshed
        preview of the overall rating: a weighted mean over the cycle's `ACTIVE`
        measures whose performance status is `VALIDATED` or `LOCKED` and whose
        basis star is non-null, using the best-available basis — the
        `published_star` when the cycle has a `PUBLISHED` set, otherwise the
        `draft_star`."

        Raw 0.85 bands to 3 against the first set (band_4_floor 0.90) and to 4
        against the second set (band_4_floor 0.85).

        Design: Difficulty/transitive_cascade/cutpoint_publish_cascade_depth2
        """
        sc = setup_cycle_in_cutpoint_review(17, 20)
        cycle_id = sc["cycle"]["id"]
        measure_id = sc["measure"]["id"]
        perf_id = sc["performance"]["id"]

        set_p1 = create_draft_set(
            cycle_id, [cutpoint_row(measure_id, 0.62, 0.75, 0.90, 0.95)],
            label="official-a")
        publish_set(cycle_id, set_p1["id"])
        perf = get_performance(perf_id)
        assert perf["published_star"] == 3
        assert get_cycle(cycle_id)["live_weighted_stars"] == pytest.approx(3.0)

        set_p2 = create_draft_set(
            cycle_id, [cutpoint_row(measure_id, 0.60, 0.72, 0.85, 0.94)],
            label="official-b")
        publish_set(cycle_id, set_p2["id"])

        perf = validate_success(api.get_measure_performance(perf_id, stars_admin_headers))
        assert perf["published_star"] == 4, (
            f"publish recomputes published_star against the new floors; got "
            f"{perf['published_star']}"
        )
        cycle = validate_success(api.get_rating_cycle(cycle_id, stars_admin_headers))
        assert cycle["live_weighted_stars"] == pytest.approx(4.0), (
            "each star recompute refreshes live_weighted_stars"
        )


class TestOptimisticConcurrency:
    def test_stale_cycle_version_on_second_publish(self, api, stars_admin_headers,
                                                   stars_analyst_headers):
        """PRD §2.9: "Publishing a cut point set requires the request to carry
        `expected_rating_cycle_version`, the client-side view of the owning cycle's
        `version`."
        PRD §2.9: "If the cycle's current `version` does not match — because
        another writer has advanced the cycle since the client last read it — the
        publish is rejected with `ERR_STALE_VERSION` (HTTP 412), and the client
        must re-read the cycle before publishing again."

        Design: Corner/cross_cutting_layers/stale_cycle_version_on_second_publish
        """
        cycle = create_cycle()
        measure = create_active_measure(cycle["id"])
        transition_cycle(cycle["id"], "DATA_COLLECTION")
        cycle = transition_cycle(cycle["id"], "CUTPOINT_REVIEW")
        pre_publish_version = cycle["version"]

        s1 = create_draft_set(cycle["id"], [cutpoint_row(measure["id"], 0.62, 0.75,
                                                         0.90, 0.95)], label="s1")
        s2 = create_draft_set(cycle["id"], [cutpoint_row(measure["id"], 0.60, 0.72,
                                                         0.85, 0.94)], label="s2")

        first = api.publish_cutpoint_set(s1["id"], pre_publish_version,
                                         stars_admin_headers)
        validate_success(first)
        assert get_cutpoint_set(s1["id"])["status"] == "PUBLISHED"

        resp = api.publish_cutpoint_set(s2["id"], pre_publish_version,
                                        stars_admin_headers)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        fetched = validate_success(api.get_cutpoint_set(s2["id"], stars_analyst_headers))
        assert fetched["status"] == "DRAFT", "Stale publish leaves the set DRAFT"

    def test_stale_set_version_on_row_replace(self, api, stars_analyst_headers):
        """PRD §2.9: "Replacing the rows of a draft cut point set requires the
        request to carry `expected_cutpoint_set_version` matching the set's current
        `version`; a mismatch is likewise rejected with `ERR_STALE_VERSION`
        (HTTP 412), forcing the client to re-read the set and rebase its row edits."
        PRD §3.3: "A successful replace bumps the set's `version` by 1."

        Design: Corner/cross_cutting_layers/stale_set_version_on_row_replace
        """
        cycle = create_cycle()
        measure = create_measure(cycle["id"])
        cutpoint_set = create_draft_set(
            cycle["id"], [cutpoint_row(measure["id"], 0.60, 0.70, 0.80, 0.90)],
            label="draft-2028")
        observed_version = cutpoint_set["version"]

        first = api.replace_cutpoint_rows(
            cutpoint_set["id"],
            {"rows": [cutpoint_row(measure["id"], 0.61, 0.71, 0.81, 0.91)],
             "expected_cutpoint_set_version": observed_version},
            stars_analyst_headers,
        )
        replaced = validate_success(first)
        assert replaced["version"] == observed_version + 1, (
            "A successful replace bumps the set's version by 1"
        )

        resp = api.replace_cutpoint_rows(
            cutpoint_set["id"],
            {"rows": [cutpoint_row(measure["id"], 0.62, 0.72, 0.82, 0.92)],
             "expected_cutpoint_set_version": observed_version},
            stars_analyst_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_row_replace_on_published_set_immutable(self, api, stars_analyst_headers):
        """PRD §3.3: "Attempting a row replace on a set that is no longer `DRAFT`
        is rejected with `ERR_CUTPOINT_SET_IMMUTABLE`."

        The request carries the set's current version (re-read after publish), so
        the OCC check passes and the state gate is what fires.

        Design: Corner/cross_cutting_layers/row_replace_on_published_set_immutable
        """
        sc = setup_collecting_measure(performance=False)
        cycle_id = sc["cycle"]["id"]
        measure_id = sc["measure"]["id"]
        cutpoint_set = create_draft_set(
            cycle_id, [cutpoint_row(measure_id, 0.62, 0.75, 0.90, 0.95)],
            label="official-2028")
        transition_cycle(cycle_id, "CUTPOINT_REVIEW")
        publish_set(cycle_id, cutpoint_set["id"])
        published = get_cutpoint_set(cutpoint_set["id"])
        assert published["status"] == "PUBLISHED"

        resp = api.replace_cutpoint_rows(
            cutpoint_set["id"],
            {"rows": [cutpoint_row(measure_id, 0.61, 0.71, 0.81, 0.91)],
             "expected_cutpoint_set_version": published["version"]},
            stars_analyst_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CUTPOINT_SET_IMMUTABLE)


class TestPublishRbac:
    def test_qualityops_cannot_publish_cutpoints(self, api, stars_analyst_headers,
                                                 quality_ops_headers):
        """PRD §2.1: "If the headers are present but the role named in
        `X-User-Role` is not one of the declared roles, or the role is not
        permitted for the endpoint being called, the request is rejected with
        `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §2.11: "2. **Auth permission** — role declared and permitted for the
        endpoint, else `ERR_UNAUTHORIZED_ROLE` (HTTP 403). Applies to every
        endpoint."
        PRD §4: the publish endpoint row names only StarsAdmin as authorized.

        Design: Corner/rbac/qualityops_cannot_publish_cutpoints
        """
        cycle = create_cycle()
        measure = create_active_measure(cycle["id"])
        cutpoint_set = create_draft_set(
            cycle["id"], [cutpoint_row(measure["id"], 0.62, 0.75, 0.90, 0.95)],
            label="official-2028")
        transition_cycle(cycle["id"], "DATA_COLLECTION")
        cycle = transition_cycle(cycle["id"], "CUTPOINT_REVIEW")

        resp = api.publish_cutpoint_set(cutpoint_set["id"], cycle["version"],
                                        quality_ops_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        fetched = validate_success(api.get_cutpoint_set(cutpoint_set["id"],
                                                        stars_analyst_headers))
        assert fetched["status"] == "DRAFT", "A denied publish leaves the set DRAFT"
