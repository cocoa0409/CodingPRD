"""Composite publication: supersession cascade, one-published invariant,
derived-field reconciliation, OCC freshness, and publish guards (PRD §3.6)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_active_strategy,
    add_successor_strategy,
    bootstrap_org,
    create_recomputed_composite,
    get_composite,
    get_job,
    get_success_data,
    mgr_headers,
    propose_match,
    publish_composite,
    review_and_approve_match,
    setup_accepted_survey,
    setup_published_job,
    validate_error,
    validate_paginated,
    validate_success,
)

VENDOR_ADMIN = TEST_USERS["vendor_admin_headers"]


def _second_recomputed_composite(api, bundle):
    """Second recomputed DRAFT composite, pinned to a fresh ACTIVE strategy.

    PRD §3.6 rejects a publish while another PUBLISHED composite for the same
    job shares this composite's `strategy_policy_id` (ERR_ALREADY_PUBLISHED),
    so a publish meant to cascade the prior PUBLISHED composite to SUPERSEDED
    must pin a different strategy.
    """
    strategy2 = add_successor_strategy(bundle)
    return create_recomputed_composite(bundle, bundle["job"], strategy2)


class TestPublishSupersessionCascade:
    def test_new_publish_repoints_job_and_publishes(self, api):
        """PRD §3.6: "On success the composite becomes `PUBLISHED` and its
        `published_at` — null until this moment — is stamped, the job's
        `current_market_composite_id` is repointed to the new composite and
        the job's `version` increments".

        Design: Difficulty/transitive_cascade/composite_publish_cascade_depth2
        """
        bundle = setup_published_job()
        c2 = _second_recomputed_composite(api, bundle)
        published = publish_composite(bundle, bundle["job"]["id"], c2["id"])
        assert published["status"] == "PUBLISHED"
        assert published["published_at"] is not None
        job_after = get_job(bundle, bundle["job"]["id"])
        assert job_after["current_market_composite_id"] == c2["id"], (
            "Job must repoint to the newly published composite")

    def test_prior_published_composite_superseded(self, api):
        """PRD §3.6: "the job's previously `PUBLISHED` composite cascades to
        `SUPERSEDED` (the only terminal state)".

        Design: Difficulty/transitive_cascade/composite_publish_cascade_depth2
        """
        bundle = setup_published_job()
        first_id = bundle["composite"]["id"]
        c2 = _second_recomputed_composite(api, bundle)
        publish_composite(bundle, bundle["job"]["id"], c2["id"])
        first_after = get_composite(bundle, first_id)
        assert first_after["status"] == "SUPERSEDED", (
            f"Prior PUBLISHED composite must cascade to SUPERSEDED, got "
            f"{first_after['status']}")


class TestPublishedCountInvariant:
    def test_publish_supersedes_prior_statuses(self, api):
        """PRD §3.6: "the job's previously `PUBLISHED` composite cascades to
        `SUPERSEDED` (the only terminal state), and a `COMPOSITE_PUBLISH`
        audit event is emitted. Supersession is therefore automatic".

        Design: Difficulty/compensating_invariant/published_composite_count_invariant
        """
        bundle = setup_published_job()
        first_id = bundle["composite"]["id"]
        c2 = _second_recomputed_composite(api, bundle)
        publish_composite(bundle, bundle["job"]["id"], c2["id"])
        assert get_composite(bundle, first_id)["status"] == "SUPERSEDED"
        assert get_composite(bundle, c2["id"])["status"] == "PUBLISHED"

    def test_exactly_one_published_composite_per_job(self, api):
        """PRD §3.6: "no other `PUBLISHED` composite for the same job may
        share this composite's `strategy_policy_id` (`ERR_ALREADY_PUBLISHED`)"
        and "the job's previously `PUBLISHED` composite cascades to
        `SUPERSEDED`".

        Design: Difficulty/compensating_invariant/published_composite_count_invariant
        """
        bundle = setup_published_job()
        c2 = _second_recomputed_composite(api, bundle)
        publish_composite(bundle, bundle["job"]["id"], c2["id"])
        composites, meta = validate_paginated(api.list_job_composites(
            bundle["job"]["id"], mgr_headers(bundle)))
        published = [c for c in composites if c["status"] == "PUBLISHED"]
        assert len(published) == 1, (
            f"Exactly one PUBLISHED composite per job must survive; got "
            f"{len(published)}")
        assert published[0]["id"] == c2["id"]


class TestDerivedFieldAndOcc:
    def test_current_market_composite_id_null_then_repointed(self, api):
        """PRD §3.2: "A job's `current_market_composite_id` is
        system-maintained: it starts null and is repointed to the job's latest
        `PUBLISHED` composite each time one is published (§3.6)."

        Design: Corner/cross_cutting_complexity_layers/derived_field_current_market_composite_id_after_publish
        """
        bundle = bootstrap_org()
        bundle["strategy"] = add_active_strategy(bundle)
        chain = setup_accepted_survey(bundle)
        bundle.update(chain)
        match = propose_match(bundle, bundle["survey"], bundle["job"],
                              bundle["benchmark"])
        review_and_approve_match(bundle, match["id"])
        composite = create_recomputed_composite(bundle, bundle["job"],
                                                bundle["strategy"])
        before = get_job(bundle, bundle["job"]["id"])
        assert before["current_market_composite_id"] is None

        publish_composite(bundle, bundle["job"]["id"], composite["id"])

        after = get_job(bundle, bundle["job"]["id"])
        assert after["current_market_composite_id"] == composite["id"], (
            "Publish must repoint current_market_composite_id to the new "
            "composite")

    def test_publish_increments_job_version_by_one(self, api):
        """PRD §2.5: "The `version` field is an integer that increments by one
        on every mutation, including mutations performed by the server itself
        as side effects of operations on related resources."
        PRD §3.6: "the job's `current_market_composite_id` is repointed to the
        new composite and the job's `version` increments".

        Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_every_mutation
        """
        bundle = bootstrap_org()
        bundle["strategy"] = add_active_strategy(bundle)
        chain = setup_accepted_survey(bundle)
        bundle.update(chain)
        match = propose_match(bundle, bundle["survey"], bundle["job"],
                              bundle["benchmark"])
        review_and_approve_match(bundle, match["id"])
        composite = create_recomputed_composite(bundle, bundle["job"],
                                                bundle["strategy"])
        v0 = get_job(bundle, bundle["job"]["id"])["version"]
        # A read is not a mutation and must not move the version.
        v_after_get = get_job(bundle, bundle["job"]["id"])["version"]
        assert v_after_get == v0, "Read-only GET must not change Job.version"

        publish_composite(bundle, bundle["job"]["id"], composite["id"])

        v1 = get_job(bundle, bundle["job"]["id"])["version"]
        assert v1 == v0 + 1, (
            f"Publish must increment Job.version by exactly one: {v0} -> {v1}")


class TestPublishGuards:
    def test_publish_without_sources_rejected(self, api):
        """PRD §3.6: "at least one approved contributing source must exist,
        meaning `source_count` is at least 1 (`ERR_NO_SOURCES`)".

        Design: Corner/errors/error_no_sources_on_publish
        """
        bundle = bootstrap_org()
        bundle["strategy"] = add_active_strategy(bundle)
        composite = get_success_data(api.create_composite(
            bundle["job"]["id"],
            {"strategy_policy_id": bundle["strategy"]["id"],
             "job_geo_code": "US-SF"},
            mgr_headers(bundle)))
        job = get_job(bundle, bundle["job"]["id"])
        resp = api.publish_composite(
            composite["id"], {"expected_job_version": job["version"]},
            mgr_headers(bundle))
        validate_error(resp, ApiErrorId.ERR_NO_SOURCES)

    def test_publish_with_stale_job_version_rejected(self, api):
        """PRD §2.8: "Publishing a market composite requires the request to
        carry `expected_job_version`, the client's last observed `version` of
        the parent Job; if the Job's current `version` has advanced past that
        value, the publish is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/errors/error_stale_version_on_publish
        """
        bundle = setup_published_job()
        # Publishing C1 already advanced the job's version once; the value a
        # client observed before that publish is now stale.
        current_version = get_job(bundle, bundle["job"]["id"])["version"]
        stale_version = current_version - 1
        c2 = _second_recomputed_composite(api, bundle)
        resp = api.publish_composite(
            c2["id"], {"expected_job_version": stale_version},
            mgr_headers(bundle))
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
