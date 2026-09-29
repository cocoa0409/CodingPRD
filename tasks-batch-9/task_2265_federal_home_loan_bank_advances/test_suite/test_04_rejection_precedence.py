"""When one request breaks two rules, the ladder decides which failure is reported."""
from test_helpers import *  # noqa: F401,F403


class TestTermRangeBeatsCapacity:
    """A product-range violation is reported before any capacity arithmetic."""

    def _member_with_five_hundred_thousand_of_capacity(self, api):
        """One eligible HELOC, so provisional capacity is exactly 500,000."""
        env = pledging_member(api)
        add_heloc(api, env)
        product = create_product(api)
        return env, product

    def _advance_body(self, env, product, version, term_days):
        return advance_payload(
            env.member_id,
            product["id"],
            version,
            term_days=term_days,
            requested_net_proceeds_cents=5_000_000,
            fund_stock_from_advance=False,
        )

    def test_term_out_of_range_is_reported_ahead_of_the_capacity_shortfall(self, api):
        """PRD §3.5: "Before any money is checked, the request must be internally
        coherent. `term_days` must fall within the product's `min_term_days` and
        `max_term_days` inclusive, else `ERR_TERM_OUT_OF_RANGE`."

        Design: Difficulty/priority_pair_validation_conflict/term_out_of_range_beats_insufficient_capacity_rejected
        """
        env, product = self._member_with_five_hundred_thousand_of_capacity(api)

        response = api.create_advance(
            self._advance_body(env, product, env.version, 2_000), env.treasury
        )

        validate_error(response, "ERR_TERM_OUT_OF_RANGE", 409)

    def test_the_refused_request_leaves_no_advance_and_no_version_bump(self, api):
        """PRD §2.5: "The order in which candidate rejections are evaluated is fixed,
        so that a caller always receives the most fundamental reason rather than an
        incidental one. Checks are applied in the following thirteen tiers, and the
        first tier that produces a rejection ends the request."

        Design: Difficulty/priority_pair_validation_conflict/term_out_of_range_beats_insufficient_capacity_rejected
        """
        env, product = self._member_with_five_hundred_thousand_of_capacity(api)
        version_before = env.version

        api.create_advance(
            self._advance_body(env, product, version_before, 2_000), env.treasury
        )

        assert_total_count(
            api.list_advances(CREDIT_ONE, {"member_bank_id": env.member_id}), 0
        )
        member = env.refresh()
        assert_fields(member, version=version_before, committed_advances_cents=0)

    def test_the_masked_capacity_rule_was_genuinely_violated(self, api):
        """PRD §3.5: "Advance creation is gated on the **provisional** variant, because
        the request being created is not yet a commitment: if `gross_principal_cents`
        exceeds the member's provisional capacity, the request is rejected with
        `ERR_INSUFFICIENT_BORROWING_CAPACITY`."

        Design: Difficulty/priority_pair_validation_conflict/term_out_of_range_beats_insufficient_capacity_rejected
        """
        env, product = self._member_with_five_hundred_thousand_of_capacity(api)

        response = api.create_advance(
            self._advance_body(env, product, env.version, 360), env.treasury
        )

        validate_error(response, "ERR_INSUFFICIENT_BORROWING_CAPACITY", 409)


class TestMemberScopeBeatsStaleVersion:
    """A caller must never learn from a 412 that another member's row moved."""

    def _two_members_and_a_staled_version(self, api):
        """M1 holds the collateral; its version is staled by a condition amendment."""
        first = member_with_eligible_sf(api)
        second = second_member(api)
        product = create_product(api)
        stale_version = first.version
        amend_condition(api, first.member_id, credit_rating_tier=2)
        return first, second, product, stale_version

    def _advance_body(self, first, product, version):
        return advance_payload(
            first.member_id,
            product["id"],
            version,
            term_days=360,
            requested_net_proceeds_cents=5_000_000,
            fund_stock_from_advance=False,
        )

    def test_scope_violation_is_reported_instead_of_the_stale_version(self, api):
        """PRD §2.5: "**Member scope.** On every endpoint whose role list includes
        `TreasuryOfficer`, a `TreasuryOfficer` caller whose `X-User-ID` differs from
        the owning member of the addressed resource — or from a `member_bank_id`
        supplied in the request body — is rejected with `ERR_MEMBER_SCOPE_VIOLATION`
        (403)."

        Design: Difficulty/priority_pair_validation_conflict/member_scope_beats_stale_version_returns_4XX
        """
        first, second, product, stale_version = self._two_members_and_a_staled_version(api)

        response = api.create_advance(
            self._advance_body(first, product, stale_version), second.treasury
        )

        validate_error(response, "ERR_MEMBER_SCOPE_VIOLATION", 403)

    def test_the_refused_request_creates_nothing_and_moves_no_version(self, api):
        """PRD §2.7: "If the value does not equal the member's current `version`, the
        request is rejected with `ERR_STALE_MEMBER_VERSION` and HTTP 412, and nothing
        is written."

        Design: Difficulty/priority_pair_validation_conflict/member_scope_beats_stale_version_returns_4XX
        """
        first, second, product, stale_version = self._two_members_and_a_staled_version(api)
        version_after_patch = first.version

        api.create_advance(
            self._advance_body(first, product, stale_version), second.treasury
        )

        assert_total_count(
            api.list_advances(CREDIT_ONE, {"member_bank_id": first.member_id}), 0
        )
        member = first.refresh()
        assert_fields(member, version=version_after_patch, credit_rating_tier=2)

    def test_the_masked_concurrency_rule_was_genuinely_violated(self, api):
        """PRD §2.5: "**Optimistic concurrency.** Where an
        `expected_member_bank_version` is required, a value that does not equal the
        member's current `version` yields `ERR_STALE_MEMBER_VERSION` (412)."

        Design: Difficulty/priority_pair_validation_conflict/member_scope_beats_stale_version_returns_4XX
        """
        first, _second, product, stale_version = self._two_members_and_a_staled_version(api)

        stale = api.create_advance(
            self._advance_body(first, product, stale_version), first.treasury
        )
        validate_error(stale, "ERR_STALE_MEMBER_VERSION", 412)

        fresh = api.create_advance(
            self._advance_body(first, product, first.version), first.treasury
        )
        validate_success(fresh, 201)
