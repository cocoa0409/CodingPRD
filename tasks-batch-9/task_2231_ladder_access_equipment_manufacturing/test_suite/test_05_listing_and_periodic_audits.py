"""Certification listing, retail release and periodic-audit escalation."""

from test_helpers import (
    ApiErrorId,
    api_client,
    approve_mandated_documents,
    assert_instant_equals,
    create_audit_campaign_payload,
    create_draft_revision,
    create_listing_body,
    create_product,
    create_test_bench,
    create_test_campaign_payload,
    file_listing_record,
    get_listing_record_data,
    get_product_data,
    open_lot,
    plan_audit_campaign,
    run_audit_campaign,
    setup_frozen_product,
    setup_listed_product,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

TECHNICIAN = TEST_USERS["test_lab_technician_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]

FIRST_WINDOW = ("2026-08-05T00:00:00Z", "2026-08-09T00:00:00Z")


def _audit_setup():
    """A model with a filed (still `APPLIED`) listing record and one lot, which
    is all an audit campaign needs to be planned against."""
    product = create_product()
    revision = create_draft_revision(product["id"])
    bench = create_test_bench()
    body = create_listing_body()
    record = file_listing_record(product["id"], body["id"])
    lot = open_lot(product, revision["id"])
    return {
        "product": product,
        "revision": revision,
        "bench": bench,
        "listing_body": body,
        "listing_record": record,
        "lot": lot,
    }


class TestAuditEscalationFromPriorFailureRate:
    def _failed_first_audit(self):
        ctx = _audit_setup()
        first = run_audit_campaign(
            ctx, ctx["lot"]["id"], *FIRST_WINDOW, failing_tests=1
        )
        return ctx, first

    def test_first_audit_has_no_prior_and_therefore_the_base_sample_size(self):
        """PRD §3.5: "It is `TIER_0` when there is no prior audit or when
        `prior_failure_rate_pct` is exactly 0.00."
        PRD §3.5: "it is the base audit sample of 5 units plus the tier adder —
        nothing for `TIER_0`, three more units for `TIER_1`, eight more for
        `TIER_2`, and fifteen more for `TIER_3`."

        Design: Difficulty/combinatorial_formula/audit_sample_size_keyed_on_prior_audit_failure_rate
        """
        _, first = self._failed_first_audit()

        assert first["escalation_tier"] == "TIER_0"
        assert first["prior_failure_rate_pct"] is None
        assert first["audit_sample_size"] == 5
        assert first["status"] == "FAILED"
        assert first["load_test_count"] == 5
        assert first["failed_test_count"] == 1

    def test_second_audit_escalates_on_the_prior_audits_own_sample_size(self):
        """PRD §3.5: "Otherwise it is the prior campaign's `failed_test_count`
        divided by the prior campaign's `audit_sample_size`, expressed as a
        percentage, rounded half up to two decimal places."
        PRD §3.5: "Otherwise it is `TIER_1` when `prior_failure_rate_pct` is
        20.00 or less, `TIER_2` when it is 40.00 or less, and `TIER_3` above
        that."

        Design: Difficulty/combinatorial_formula/audit_sample_size_keyed_on_prior_audit_failure_rate
        """
        ctx, _ = self._failed_first_audit()

        second = plan_audit_campaign(
            ctx, ctx["lot"]["id"], "2026-08-10T00:00:00Z", "2026-08-14T00:00:00Z"
        )

        # One failure out of the prior audit's own five units is exactly 20.00.
        assert float(second["prior_failure_rate_pct"]) == 20.00
        assert second["escalation_tier"] == "TIER_1"
        assert second["audit_sample_size"] == 8
        assert second["status"] == "PLANNED"

    def test_non_audit_campaign_leaves_all_three_escalation_fields_null(self):
        """PRD §3.5: "For campaigns of any purpose other than `PERIODIC_AUDIT`,
        all three of `audit_sample_size`, `escalation_tier`, and
        `prior_failure_rate_pct` remain null."

        Design: Difficulty/combinatorial_formula/audit_sample_size_keyed_on_prior_audit_failure_rate
        """
        ctx, first = self._failed_first_audit()

        qualification = validate_success(
            api_client.create_test_campaign(
                create_test_campaign_payload(
                    ctx["product"]["id"],
                    ctx["revision"]["id"],
                    "DESIGN_QUALIFICATION",
                ),
                TECHNICIAN,
            ),
            201,
        )

        assert qualification["audit_sample_size"] is None
        assert qualification["escalation_tier"] is None
        assert qualification["prior_failure_rate_pct"] is None
        assert first["audit_sample_size"] == 5, (
            "the audit campaign keeps its own escalation figures"
        )


class TestAuditWindowClosedIntervals:
    def _first_planned_audit(self):
        ctx = _audit_setup()
        first = plan_audit_campaign(ctx, ctx["lot"]["id"], *FIRST_WINDOW)
        assert first["status"] == "PLANNED"
        return ctx, first

    def _plan(self, ctx, start, end, revision_id=None):
        payload = create_audit_campaign_payload(
            ctx["product"]["id"],
            revision_id or ctx["revision"]["id"],
            ctx["listing_record"]["id"],
            ctx["lot"]["id"],
            start,
            end,
        )
        return api_client.create_test_campaign(payload, TECHNICIAN)

    def test_window_starting_exactly_on_the_incumbents_end_instant_collides(self):
        """PRD §3.5: "A new audit campaign is rejected with
        `ERR_AUDIT_WINDOW_OVERLAP` when the same `listing_record_id` already
        carries an audit campaign in `PLANNED`, `IN_PROGRESS`, `PASSED`, or
        `FAILED` such that the new `sample_window_start` is earlier than **or
        equal to** that campaign's `sample_window_end` and the new
        `sample_window_end` is later than **or equal to** that campaign's
        `sample_window_start`."

        Design: Difficulty/resource_temporal_overlap/audit_window_closed_interval_touching_endpoints_collide
        """
        ctx, _ = self._first_planned_audit()

        response = self._plan(ctx, "2026-08-09T00:00:00Z", "2026-08-12T00:00:00Z")
        validate_error(response, ApiErrorId.ERR_AUDIT_WINDOW_OVERLAP.value, 409)

    def test_window_starting_a_day_after_the_incumbents_end_is_accepted(self):
        """PRD §3.5: "Audit sample windows on the same listing record must not
        overlap, and here the interval arithmetic is **closed on both ends with
        no buffer applied**, unlike bench occupancy."
        PRD §3.5: "Touching endpoints therefore do collide."

        Design: Difficulty/resource_temporal_overlap/audit_window_closed_interval_touching_endpoints_collide
        """
        ctx, _ = self._first_planned_audit()

        accepted = validate_success(
            self._plan(ctx, "2026-08-10T00:00:00Z", "2026-08-12T00:00:00Z"), 201
        )

        assert accepted["status"] == "PLANNED"
        assert accepted["escalation_tier"] == "TIER_0", (
            "no concluded prior audit exists, so no escalation applies"
        )
        assert accepted["prior_failure_rate_pct"] is None
        assert accepted["audit_sample_size"] == 5

        rows, meta = validate_paginated(
            api_client.list_test_campaigns(
                TECHNICIAN, {"listing_record_id": ctx["listing_record"]["id"]}
            )
        )
        assert meta["total_count"] == 2
        assert len(rows) == 2


class TestCampaignErrorPrecedence:
    def test_revision_product_mismatch_outranks_the_audit_window_overlap(self):
        """PRD §2.5: "32. through 35. Referential-scope checks:
        `ERR_REVISION_PRODUCT_MISMATCH`, `ERR_AUDIT_SCOPE_MISMATCH`,
        `ERR_AUDIT_FIELDS_MISMATCH`, `ERR_SUPERSEDE_TARGET_MISMATCH`."
        PRD §3.2: "When the revision named by `design_revision_id` — or by
        `frozen_revision_id` at design freeze — belongs to a different model than
        the one in the request, the operation is rejected with
        `ERR_REVISION_PRODUCT_MISMATCH`."

        Design: Difficulty/priority_pair_validation_conflict/campaign_referential_error_outranks_window_overlap_error
        """
        ctx = _audit_setup()
        plan_audit_campaign(ctx, ctx["lot"]["id"], *FIRST_WINDOW)
        other_product = create_product()
        foreign_revision = create_draft_revision(other_product["id"])

        payload = create_audit_campaign_payload(
            ctx["product"]["id"],
            foreign_revision["id"],
            ctx["listing_record"]["id"],
            ctx["lot"]["id"],
            "2026-08-09T00:00:00Z",
            "2026-08-12T00:00:00Z",
        )
        response = api_client.create_test_campaign(payload, TECHNICIAN)
        validate_error(response, ApiErrorId.ERR_REVISION_PRODUCT_MISMATCH.value, 409)

        rows, meta = validate_paginated(
            api_client.list_test_campaigns(
                TECHNICIAN, {"product_id": ctx["product"]["id"]}
            )
        )
        assert meta["total_count"] == 1, "the rejected plan persisted nothing"
        assert rows[0]["status"] == "PLANNED"

    def test_the_same_window_with_the_models_own_revision_reports_the_overlap(self):
        """PRD §2.5: "55. and 56. Temporal collision checks: bench occupancy
        (`ERR_BENCH_WINDOW_CONFLICT`) and audit-window overlap
        (`ERR_AUDIT_WINDOW_OVERLAP`)."
        PRD §2.5: "Requests are evaluated against a fixed priority ladder, and the
        **first** failing check determines the response. Later checks never mask
        an earlier one."

        Design: Difficulty/priority_pair_validation_conflict/campaign_referential_error_outranks_window_overlap_error
        """
        ctx = _audit_setup()
        plan_audit_campaign(ctx, ctx["lot"]["id"], *FIRST_WINDOW)

        # Identical touching window, but now the revision belongs to the model,
        # so the referential check no longer fires ahead of the overlap check.
        payload = create_audit_campaign_payload(
            ctx["product"]["id"],
            ctx["revision"]["id"],
            ctx["listing_record"]["id"],
            ctx["lot"]["id"],
            "2026-08-09T00:00:00Z",
            "2026-08-12T00:00:00Z",
        )
        response = api_client.create_test_campaign(payload, TECHNICIAN)
        validate_error(response, ApiErrorId.ERR_AUDIT_WINDOW_OVERLAP.value, 409)


class TestRetailReleaseGatedOnListingState:
    def test_release_to_retail_is_rejected_while_the_listing_is_only_applied(self):
        """PRD §3.7: "Finally, at least one listing record of the model must be in
        `LISTED`, or the release is rejected with `ERR_NO_ACTIVE_LISTING`."

        Design: Difficulty/cross_entity_state_dependency/retail_release_gated_on_listing_record_state
        """
        ctx = setup_frozen_product()
        body = create_listing_body()
        record = file_listing_record(ctx["product"]["id"], body["id"])
        approve_mandated_documents(ctx["product"]["id"])
        assert record["status"] == "APPLIED"

        response = api_client.release_to_retail(ctx["product"]["id"], OFFICER)
        validate_error(response, ApiErrorId.ERR_NO_ACTIVE_LISTING.value, 422)

        reread = get_product_data(ctx["product"]["id"])
        assert reread["design_status"] == "DESIGN_FROZEN", (
            "the design and label gates were both satisfied"
        )
        assert reread["market_status"] == "NOT_RELEASED"
        assert reread["market_status_changed_at"] is None

    def test_granting_the_listing_stamps_its_three_instants(self):
        """PRD §3.5: "On success three instants are stamped: `listed_at` at the
        logical clock, `audit_due_at` at the logical clock advanced by the owning
        body's `audit_interval_days`, and `listing_expires_at` at the logical
        clock advanced by the listing term of 1825 days — five 365-day years."

        Design: Difficulty/cross_entity_state_dependency/retail_release_gated_on_listing_record_state
        """
        ctx = setup_listed_product()

        record = get_listing_record_data(ctx["listing_record"]["id"])
        assert record["status"] == "LISTED"
        assert_instant_equals(record["listed_at"], "2026-08-01T00:00:00Z", "listed_at")
        # The owning body's audit interval is 180 days from the clock start.
        assert_instant_equals(
            record["audit_due_at"], "2027-01-28T00:00:00Z", "audit_due_at"
        )
        assert_instant_equals(
            record["listing_expires_at"], "2031-07-31T00:00:00Z", "listing_expires_at"
        )

    def test_release_to_retail_succeeds_once_the_same_record_reaches_listed(self):
        """PRD §3.7: "Releasing a model to the retail channel belongs to a
        `ComplianceOfficer` and moves `market_status` `NOT_RELEASED` →
        `RETAIL_RELEASED`, stamping `market_status_changed_at` with the logical
        clock and incrementing the model's `version`."

        Design: Difficulty/cross_entity_state_dependency/retail_release_gated_on_listing_record_state
        """
        ctx = setup_listed_product()
        approve_mandated_documents(ctx["product"]["id"])

        released = validate_success(
            api_client.release_to_retail(ctx["product"]["id"], OFFICER)
        )

        assert released["market_status"] == "RETAIL_RELEASED"
        assert_instant_equals(
            released["market_status_changed_at"],
            "2026-08-01T00:00:00Z",
            "market_status_changed_at",
        )
        assert released["design_status"] == "DESIGN_FROZEN", (
            "retail release never touches the design dimension"
        )
