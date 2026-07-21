"""Claim filing: guarantee-must-be-active, state-beats-temporal precedence, quantity
boundary, notice window, ownership, OCC, and guarantee listing
(PRD §3.6, §2.6, §2.3, §2.9)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data, ApiErrorId,
    setup_active_guarantee, setup_preactivation, file_claim,
    create_portfolio, create_applicant, create_quoted_guarantee, create_landlord,
    create_claim_payload, make_underwriter_headers, make_landlord_headers, TEST_USERS,
)


def _current_version(api, guarantee_id):
    g = get_success_data(api.get_guarantee(guarantee_id, make_underwriter_headers("uw1")))
    return g["version"]


class TestClaimRequiresActiveGuarantee:
    """Claim->Guarantee: a claim can only be filed against an ACTIVE guarantee."""

    def test_file_claim_on_approved_guarantee_rejected(self, api):
        """PRD §3.6: "The guarantee must be live: a claim may only be filed against a
        guarantee in `ACTIVE`, and a filing against a guarantee in any other status is
        rejected with `ERR_GUARANTEE_NOT_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/claim_requires_guarantee_active
        """
        ctx = setup_preactivation(api, pay_fee=True, countersign=True)  # APPROVED, not active
        version = _current_version(api, ctx["g_id"])
        resp = api.create_claim(
            ctx["g_id"], create_claim_payload(version, missed_months=2, default_date="2026-09-01T00:00:00Z"),
            make_landlord_headers(ctx["ll_id"]))
        validate_error(resp, ApiErrorId.ERR_GUARANTEE_NOT_ACTIVE.value)

    def test_no_claim_created_against_approved_guarantee(self, api):
        """PRD §3.6: "a claim may only be filed against a guarantee in `ACTIVE`, and a
        filing against a guarantee in any other status is rejected with
        `ERR_GUARANTEE_NOT_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/claim_requires_guarantee_active
        """
        ctx = setup_preactivation(api, pay_fee=True, countersign=True)
        version = _current_version(api, ctx["g_id"])
        api.create_claim(ctx["g_id"],
                         create_claim_payload(version, missed_months=2, default_date="2026-09-01T00:00:00Z"),
                         make_landlord_headers(ctx["ll_id"]))
        _data, meta = validate_paginated(api.list_claims(
            TEST_USERS["claims_adjuster_headers"], params={"guarantee_id": ctx["g_id"]}))
        assert meta["total_count"] == 0, f"no claim should exist, got {meta['total_count']}"


class TestClaimStateBeatsTemporalWindow:
    """state(7) masks business_temporal(10): not-active + closed-window -> state error."""

    def _setup_approved_window_closed(self, api):
        # default_date 2026-05-01 with 60-day notice; clock 2026-09-15 => window closed too.
        ctx = setup_preactivation(api, clock="2026-09-15T00:00:00Z", pay_fee=True,
                                  countersign=True)
        return ctx

    def test_state_error_wins_over_window_error(self, api):
        """PRD §2.9: "then the target resource's own state (`ERR_INVALID_STATE`, 409, or a
        state-specific sibling), then cross-entity referential preconditions (409), then
        compliance holds (409), then temporal-window rules (409)".

        Design: Difficulty/priority_pair_validation_conflict/claim_state_beats_temporal_window
        """
        ctx = self._setup_approved_window_closed(api)
        version = _current_version(api, ctx["g_id"])
        resp = api.create_claim(
            ctx["g_id"], create_claim_payload(version, missed_months=2, default_date="2026-05-01T00:00:00Z"),
            make_landlord_headers(ctx["ll_id"]))
        validate_error(resp, ApiErrorId.ERR_GUARANTEE_NOT_ACTIVE.value)

    def test_state_masking_leaves_guarantee_approved(self, api):
        """PRD §3.6: "a claim may only be filed against a guarantee in `ACTIVE`, and a
        filing against a guarantee in any other status is rejected with
        `ERR_GUARANTEE_NOT_ACTIVE`."

        Design: Difficulty/priority_pair_validation_conflict/claim_state_beats_temporal_window
        """
        ctx = self._setup_approved_window_closed(api)
        version = _current_version(api, ctx["g_id"])
        api.create_claim(ctx["g_id"],
                         create_claim_payload(version, missed_months=2, default_date="2026-05-01T00:00:00Z"),
                         make_landlord_headers(ctx["ll_id"]))
        fetched = get_success_data(api.get_guarantee(ctx["g_id"], make_underwriter_headers("uw1")))
        assert fetched["status"] == "APPROVED"


class TestMissedMonthsQuantityBoundary:
    """missed_months must be > 0."""

    def test_missed_months_zero_rejected(self, api):
        """PRD §3.6: "the number of already-missed rent months as `missed_months` (which
        must be greater than zero)".

        Design: Difficulty/boundary_precision_check/claim_missed_months_zero_quantity_rejected
        """
        ctx = setup_active_guarantee(api)
        resp = api.create_claim(
            ctx["g_id"], create_claim_payload(ctx["g_version"], missed_months=0,
                                              default_date="2026-09-01T00:00:00Z"),
            make_landlord_headers(ctx["ll_id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_missed_months_one_accepted(self, api):
        """PRD §3.6: "the number of already-missed rent months as `missed_months` (which
        must be greater than zero)".

        Design: Difficulty/boundary_precision_check/claim_missed_months_zero_quantity_rejected
        """
        ctx = setup_active_guarantee(api)
        created = validate_success(api.create_claim(
            ctx["g_id"], create_claim_payload(ctx["g_version"], missed_months=1,
                                              default_date="2026-09-01T00:00:00Z"),
            make_landlord_headers(ctx["ll_id"])), expected_status=201)
        assert created["status"] == "SUBMITTED"


class TestClaimNoticeWindow:
    def test_claim_after_notice_window_rejected(self, api):
        """PRD §3.6: "it must arrive within the covering agreement's `notice_period_days`
        of the `default_date`, and a claim filed more than that many days after the
        default is rejected with `ERR_CLAIM_WINDOW_CLOSED`."

        Design: Corner/validations/claim_after_notice_window_returns_409
        """
        ctx = setup_active_guarantee(
            api, clock="2026-09-15T00:00:00Z",
            guarantee_overrides={"lease_start_date": "2026-06-01T00:00:00Z",
                                 "lease_end_date": "2027-06-01T00:00:00Z"})
        # default_date 2026-06-01 is >60 days before the clock 2026-09-15.
        resp = api.create_claim(
            ctx["g_id"], create_claim_payload(ctx["g_version"], missed_months=2,
                                              default_date="2026-06-01T00:00:00Z"),
            make_landlord_headers(ctx["ll_id"]))
        validate_error(resp, ApiErrorId.ERR_CLAIM_WINDOW_CLOSED.value)


class TestClaimOwnership:
    def test_non_owner_landlord_cannot_file_claim(self, api):
        """PRD §3.6: "Filing is permitted only to the landlord the guarantee is bound to
        — the acting `X-User-ID` must equal the guarantee's `landlord_id`, otherwise the
        filing is rejected as `ERR_NOT_RESOURCE_OWNER`."

        Design: Corner/validations/claim_filed_by_non_owner_landlord_returns_403
        """
        ctx = setup_active_guarantee(api)
        other_landlord = create_landlord(api)
        resp = api.create_claim(
            ctx["g_id"], create_claim_payload(ctx["g_version"], missed_months=2,
                                              default_date="2026-09-01T00:00:00Z"),
            make_landlord_headers(other_landlord["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


class TestClaimOptimisticConcurrency:
    def test_second_claim_with_stale_version_rejected(self, api):
        """PRD §2.6: "If that value does not match the guarantee's current `version` at
        the moment of filing, the request is rejected with `ERR_STALE_GUARANTEE_VERSION`
        (HTTP 412)."
        PRD §2.6: "A successful claim filing itself advances the guarantee's `version` by
        one."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_guarantee_version_on_second_claim_returns_412
        """
        ctx = setup_active_guarantee(api)
        stale_version = ctx["g_version"]
        # First filing with the observed version succeeds and advances the version.
        file_claim(api, ctx, missed_months=2, expected_version=stale_version)
        # Second filing reuses the now-stale version.
        resp = api.create_claim(
            ctx["g_id"], create_claim_payload(stale_version, missed_months=1,
                                              default_date="2026-09-01T00:00:00Z"),
            make_landlord_headers(ctx["ll_id"]))
        validate_error(resp, ApiErrorId.ERR_STALE_GUARANTEE_VERSION.value)


class TestGuaranteeListing:
    def test_list_guarantees_by_portfolio_pagination_envelope(self, api):
        """PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`, and
        `has_more` in the `meta` object of the envelope."

        Design: Corner/endpoints/list_guarantees_pagination_envelope
        """
        pf = create_portfolio(api, exposure_cap_cents=100_000_000)
        ap = create_applicant(api)
        create_quoted_guarantee(api, pf["id"], ap["id"], uw_id="uw1", unit_id="U-PG1a")
        create_quoted_guarantee(api, pf["id"], ap["id"], uw_id="uw1", unit_id="U-PG1b")
        data, meta = validate_paginated(api.list_guarantees(
            TEST_USERS["underwriter_headers"], params={"portfolio_id": pf["id"]}))
        assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
        assert meta["has_more"] is False
