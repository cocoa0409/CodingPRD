"""Quote acceptance preconditions, the financing limit, expiry-vs-fiscal precedence, and
the accept/cancel financing-balance invariant (PRD §3.4, §3.6, §2.10)."""
from test_helpers import (
    validate_success,
    validate_error,
    setup_sent_quote,
    setup_accepted_job,
    set_clock,
    make_customer_headers,
    api_client,
    OPS,
    ApiErrorId,
)

# A scope priced above the financing ceiling: pier_count=20, depth 26 (tier3 210000),
# UNSTABLE(1.30), HARD(1.25) -> per_pier 341250 -> subtotal 6825000 -> financed 6483750.
_OVER_LIMIT_SCOPE = dict(
    soil_class="UNSTABLE", financing_plan="CASH", pier_count=20,
    anchor_count=0, avg_pier_depth_ft=26, access_difficulty="HARD",
    supplemental_engineering=True,
)


class TestScopeEngineeredPrecondition:
    def test_accept_with_draft_scope_rejected(self, api):
        """PRD §3.4: "Second, the quote's referenced `EngineeringScope` must be in
        `ENGINEERED` status, otherwise the accept is rejected with
        `ERR_SCOPE_NOT_ENGINEERED`."

        Design: Difficulty/cross_entity_state_dependency/quote_accept_requires_scope_engineered
        """
        ctx = setup_sent_quote(financing_plan="CASH", finalize_scope=False)
        headers = make_customer_headers(ctx["lead"]["id"])
        res = api.accept_quote(ctx["quote"]["id"], headers)
        validate_error(res, ApiErrorId.ERR_SCOPE_NOT_ENGINEERED.value)

    def test_accept_with_engineered_scope_succeeds(self, api):
        """PRD §3.4: "A `Customer` accepts a sent quote, transitioning it from `SENT` to
        `ACCEPTED`"

        Design: Difficulty/cross_entity_state_dependency/quote_accept_requires_scope_engineered
        """
        ctx = setup_sent_quote(financing_plan="CASH")  # scope finalized -> ENGINEERED
        headers = make_customer_headers(ctx["lead"]["id"])
        accepted = validate_success(api.accept_quote(ctx["quote"]["id"], headers), 200)
        assert accepted["status"] == "ACCEPTED", accepted


class TestExpiredBeatsFinancingLimit:
    def test_expired_and_over_limit_returns_expired(self, api):
        """PRD §3.4: "First, the current logical clock must be at or before the quote's
        `expires_at`, otherwise the accept is rejected with `ERR_QUOTE_EXPIRED`."

        Design: Difficulty/priority_pair_validation_conflict/expired_state_beats_financing_fiscal
        """
        ctx = setup_sent_quote(**_OVER_LIMIT_SCOPE)  # financed_principal 6483750 > 5,000,000
        set_clock("2026-07-01T00:00:00Z")  # past the 30-day validity window
        headers = make_customer_headers(ctx["lead"]["id"])
        res = api.accept_quote(ctx["quote"]["id"], headers)
        validate_error(res, ApiErrorId.ERR_QUOTE_EXPIRED.value)

    def test_expired_status_precedes_financing_status(self, api):
        """PRD §2.10: "the domain-specific business rules in this order: (7) quote-not-expired
        `ERR_QUOTE_EXPIRED`, ... and (21) financing-limit-exceeded
        `ERR_FINANCING_LIMIT_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/expired_state_beats_financing_fiscal
        """
        ctx = setup_sent_quote(**_OVER_LIMIT_SCOPE)
        set_clock("2026-07-01T00:00:00Z")
        headers = make_customer_headers(ctx["lead"]["id"])
        res = api.accept_quote(ctx["quote"]["id"], headers)
        # Expiry (409) is reported, not the lower-priority financing check (402).
        assert res.status_code == 409, res.text
        assert res.json()["data"]["error_id"] == "ERR_QUOTE_EXPIRED", res.text


class TestFinancingLimit:
    def test_accept_over_financing_limit_rejected(self, api):
        """PRD §3.4: "Third, the financed principal derived from the quote's pricing must not
        exceed 5,000,000 cents (`FINANCING_LIMIT_CENTS`); a financed principal above that
        ceiling is rejected with `ERR_FINANCING_LIMIT_EXCEEDED` at HTTP 402."

        Design: Corner/validations/accept_over_financing_limit_returns_error
        """
        ctx = setup_sent_quote(**_OVER_LIMIT_SCOPE)  # not expired (clock untouched)
        headers = make_customer_headers(ctx["lead"]["id"])
        res = api.accept_quote(ctx["quote"]["id"], headers)
        validate_error(res, ApiErrorId.ERR_FINANCING_LIMIT_EXCEEDED.value)


class TestFinancingBalanceInvariant:
    _SMALL = dict(pier_count=1, avg_pier_depth_ft=10, soil_class="STABLE",
                  access_difficulty="EASY", financing_plan="CASH")

    def test_accept_debits_financing_balance(self, api):
        """PRD §3.4: "Acceptance also increases the lead's `financing_balance_cents` by the
        quote's `total_cents` and increments the lead's `version` by one."

        Design: Difficulty/compensating_invariant/accept_then_cancel_conserves_financing_balance
        """
        ctx = setup_accepted_job(**self._SMALL)  # CASH total 120000
        lead = validate_success(api.get_lead(ctx["lead"]["id"], OPS), 200)
        assert lead["financing_balance_cents"] == 120000, lead

    def test_cancel_credits_financing_balance_back(self, api):
        """PRD §3.6: "Cancelling from `UNSCHEDULED`: if the job carries a `quote_id`, the
        lead's `financing_balance_cents` is decreased by that accepted quote's `total_cents`."

        Design: Difficulty/compensating_invariant/accept_then_cancel_conserves_financing_balance
        """
        ctx = setup_accepted_job(**self._SMALL)  # UNSCHEDULED job, balance 120000
        validate_success(api.cancel_job(ctx["job"]["id"], OPS), 200)
        lead = validate_success(api.get_lead(ctx["lead"]["id"], OPS), 200)
        assert lead["financing_balance_cents"] == 0, lead

    def test_financing_balance_reflects_accepted_quote(self, api):
        """PRD §3.4: "Acceptance also increases the lead's `financing_balance_cents` by the
        quote's `total_cents` and increments the lead's `version` by one."

        Design: Corner/entities/lead_financing_balance_reflects_accepted_quote
        """
        ctx = setup_accepted_job(**self._SMALL)  # CASH total 120000
        lead = validate_success(api.get_lead(ctx["lead"]["id"], OPS), 200)
        assert lead["financing_balance_cents"] == 120000, lead
