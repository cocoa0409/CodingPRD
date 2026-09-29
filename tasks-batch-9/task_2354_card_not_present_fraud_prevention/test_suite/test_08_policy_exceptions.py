"""Requesting policy exceptions: posture gates, tier ceilings and window hygiene."""

from __future__ import annotations

from test_helpers import (
    ADMIN,
    AccountStatus,
    ApiClient,
    ApiErrorId,
    CLOCK_EPOCH,
    CustomerTier,
    ExceptionAction,
    ExceptionScope,
    ExceptionState,
    TIER_EXCEPTION_CAP_CENTS,
    address_whitelist_exception_payload,
    assert_requested_exception_defaults,
    build_lead,
    create_address,
    create_analyst,
    create_high_value_customer,
    create_policy_exception_payload,
    decide_exception,
    exception_decision_payload,
    lock_customer,
    make_review_lead_headers,
    make_risk_analyst_headers,
    parse_instant,
    read_customer,
    request_exception,
    set_clock,
    unlock_customer,
    validate_error,
    validate_paginated,
    validate_success,
)

#: Above the 500,000-cent ceiling a HIGH_VALUE account is allowed.
ABOVE_HIGH_VALUE_CAP_CENTS = 600000

FIRST_WINDOW = ("2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z")
ADJACENT_WINDOW = ("2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z")
OVERLAPPING_WINDOW = ("2026-08-31T23:59:59Z", "2026-10-01T00:00:00Z")


def _exceptions_for(api: ApiClient, customer_id: str):
    return validate_paginated(
        api.list_policy_exceptions(ADMIN, params={"customer_id": customer_id})
    )


class TestLockedAccountOutranksTierCap:
    """A locked beneficiary masks the fiscal ceiling on the request path."""

    def test_locked_customer_masks_an_over_cap_request(self, api: ApiClient) -> None:
        """A locked HIGH_VALUE account asked for 600,000 cents reports the lock.

        PRD: "On the exception-request path, the customer-not-active check (band 4)
        **outranks** the tier-cap check (band 10): a request that both names a
        locked customer and asks for more than the tier cap reports
        `ERR_CUSTOMER_ACCOUNT_LOCKED`, not
        `ERR_EXCEPTION_AMOUNT_EXCEEDS_TIER_CAP`."

        Design: Difficulty/priority_pair_validation_conflict/locked_account_state_check_outranks_exception_tier_cap
        """
        customer = create_high_value_customer(api)
        analyst = create_analyst(api)
        locked = lock_customer(api, customer["id"], reason="fraud team hold")
        assert locked["account_status"] == AccountStatus.LOCKED

        assert ABOVE_HIGH_VALUE_CAP_CENTS > TIER_EXCEPTION_CAP_CENTS[
            CustomerTier.HIGH_VALUE
        ], "the request must genuinely breach the tier ceiling as well"

        response = api.create_policy_exception(
            create_policy_exception_payload(
                customer["id"],
                scope=ExceptionScope.AUTO_APPROVE_UNDER_AMOUNT,
                max_amount_cents=ABOVE_HIGH_VALUE_CAP_CENTS,
            ),
            make_risk_analyst_headers(analyst["id"]),
        )
        validate_error(response, ApiErrorId.ERR_CUSTOMER_ACCOUNT_LOCKED, 409)

        _rows, meta = _exceptions_for(api, customer["id"])
        assert meta["total_count"] == 0, "the rejected request must persist nothing"

        after = read_customer(api, customer["id"])
        assert after["account_status"] == AccountStatus.LOCKED
        assert after["version"] == locked["version"], (
            "a rejected exception request must not touch the customer row"
        )

    def test_tier_cap_is_reported_once_the_account_is_active(
        self, api: ApiClient
    ) -> None:
        """The same over-cap request against an ACTIVE account reports the ceiling.

        PRD: "The ceiling is **inclusive**: a request exactly equal to the cap is
        accepted, and only a request above it is rejected with
        `ERR_EXCEPTION_AMOUNT_EXCEEDS_TIER_CAP`."

        Design: Difficulty/priority_pair_validation_conflict/locked_account_state_check_outranks_exception_tier_cap
        """
        customer = create_high_value_customer(api)
        analyst = create_analyst(api)
        assert customer["account_status"] == AccountStatus.ACTIVE

        response = api.create_policy_exception(
            create_policy_exception_payload(
                customer["id"],
                scope=ExceptionScope.AUTO_APPROVE_UNDER_AMOUNT,
                max_amount_cents=ABOVE_HIGH_VALUE_CAP_CENTS,
            ),
            make_risk_analyst_headers(analyst["id"]),
        )
        validate_error(response, ApiErrorId.ERR_EXCEPTION_AMOUNT_EXCEEDS_TIER_CAP, 422)

        at_the_cap = request_exception(
            api,
            customer["id"],
            analyst["id"],
            scope=ExceptionScope.AUTO_APPROVE_UNDER_AMOUNT,
            max_amount_cents=TIER_EXCEPTION_CAP_CENTS[CustomerTier.HIGH_VALUE],
        )
        assert_requested_exception_defaults(at_the_cap)
        assert at_the_cap["max_amount_cents"] == TIER_EXCEPTION_CAP_CENTS[
            CustomerTier.HIGH_VALUE
        ], "a request exactly at the ceiling is accepted"


class TestExceptionWindowExclusivity:
    """Same customer, same scope: touching windows are fine, overlapping ones are not."""

    def test_exactly_adjacent_windows_are_both_accepted(self, api: ApiClient) -> None:
        """A second window starting at the first one's expiry is allowed.

        PRD: "Exact adjacency, where the candidate's `effective_from` equals the
        other's `expires_at`, is explicitly **allowed**; rows in `REJECTED` or
        `REVOKED` never block."

        Design: Difficulty/resource_temporal_overlap/exception_window_adjacency_allowed_overlap_rejected
        """
        customer = create_high_value_customer(api)
        analyst = create_analyst(api)

        first = request_exception(
            api,
            customer["id"],
            analyst["id"],
            scope=ExceptionScope.AUTO_APPROVE_UNDER_AMOUNT,
            effective_from=FIRST_WINDOW[0],
            expires_at=FIRST_WINDOW[1],
        )
        second = request_exception(
            api,
            customer["id"],
            analyst["id"],
            scope=ExceptionScope.AUTO_APPROVE_UNDER_AMOUNT,
            effective_from=ADJACENT_WINDOW[0],
            expires_at=ADJACENT_WINDOW[1],
        )

        assert first["state"] == ExceptionState.REQUESTED
        assert second["state"] == ExceptionState.REQUESTED
        assert second["effective_from"] == first["expires_at"], (
            "the two windows must touch exactly for this to be the adjacency case"
        )
        assert_requested_exception_defaults(second)

        _rows, meta = _exceptions_for(api, customer["id"])
        assert meta["total_count"] == 2

    def test_a_window_overlapping_by_one_second_is_rejected(
        self, api: ApiClient
    ) -> None:
        """Starting one second before the first window expires collides with it.

        PRD: "Then window exclusivity: no other exception for the **same customer
        with the same scope** whose state is `REQUESTED` or `APPROVED` may overlap
        the candidate's half-open window — overlap means the candidate's
        `expires_at` is after the other's `effective_from` *and* the other's
        `expires_at` is after the candidate's `effective_from`."

        Design: Difficulty/resource_temporal_overlap/exception_window_adjacency_allowed_overlap_rejected
        """
        customer = create_high_value_customer(api)
        analyst = create_analyst(api)

        request_exception(
            api,
            customer["id"],
            analyst["id"],
            scope=ExceptionScope.AUTO_APPROVE_UNDER_AMOUNT,
            effective_from=FIRST_WINDOW[0],
            expires_at=FIRST_WINDOW[1],
        )
        request_exception(
            api,
            customer["id"],
            analyst["id"],
            scope=ExceptionScope.AUTO_APPROVE_UNDER_AMOUNT,
            effective_from=ADJACENT_WINDOW[0],
            expires_at=ADJACENT_WINDOW[1],
        )

        response = api.create_policy_exception(
            create_policy_exception_payload(
                customer["id"],
                scope=ExceptionScope.AUTO_APPROVE_UNDER_AMOUNT,
                effective_from=OVERLAPPING_WINDOW[0],
                expires_at=OVERLAPPING_WINDOW[1],
            ),
            make_risk_analyst_headers(analyst["id"]),
        )
        validate_error(response, ApiErrorId.ERR_EXCEPTION_WINDOW_OVERLAP, 409)

        _rows, meta = _exceptions_for(api, customer["id"])
        assert meta["total_count"] == 2, (
            "the collision must leave exactly the two accepted rows behind"
        )


class TestScopeCoherence:
    """One scope requires the whitelisted address; the other forbids it."""

    def test_the_address_field_flips_from_mandatory_to_illegal_with_the_scope(
        self, api: ApiClient
    ) -> None:
        """Each mismatched pairing has its own code, and only the coherent one persists.

        PRD: "Scope coherence follows: `ADDRESS_WHITELIST` requires a non-null
        `whitelisted_address_id`, or `ERR_EXCEPTION_SCOPE_ADDRESS_REQUIRED`;
        `AUTO_APPROVE_UNDER_AMOUNT` requires `whitelisted_address_id` to be null, or
        `ERR_EXCEPTION_ADDRESS_NOT_ALLOWED`."
        PRD: "The `ADDRESS_WHITELIST` scope is open to every tier and still honours the
        tier ceiling."

        Design: Corner/validations/exception_scope_requires_matching_address_field
        """
        customer = create_high_value_customer(api)
        analyst = create_analyst(api)
        address = create_address(api, line1="30 Whitelist Way")
        headers = make_risk_analyst_headers(analyst["id"])

        missing_address = api.create_policy_exception(
            create_policy_exception_payload(
                customer["id"], scope=ExceptionScope.ADDRESS_WHITELIST
            ),
            headers,
        )
        validate_error(
            missing_address, ApiErrorId.ERR_EXCEPTION_SCOPE_ADDRESS_REQUIRED, 422
        )

        surplus_address = api.create_policy_exception(
            create_policy_exception_payload(
                customer["id"],
                scope=ExceptionScope.AUTO_APPROVE_UNDER_AMOUNT,
                whitelisted_address_id=address["id"],
            ),
            headers,
        )
        validate_error(
            surplus_address, ApiErrorId.ERR_EXCEPTION_ADDRESS_NOT_ALLOWED, 422
        )

        accepted = validate_success(
            api.create_policy_exception(
                address_whitelist_exception_payload(customer["id"], address["id"]),
                headers,
            ),
            201,
        )
        assert_requested_exception_defaults(accepted)
        assert accepted["scope"] == ExceptionScope.ADDRESS_WHITELIST
        assert accepted["whitelisted_address_id"] == address["id"]
        assert accepted["requested_by_analyst_id"] == analyst["id"]

        _rows, meta = _exceptions_for(api, customer["id"])
        assert meta["total_count"] == 1, "the two rejected requests persisted nothing"


class TestDecisionSegregation:
    """A lead who filed an exception cannot be the lead who approves it."""

    def test_the_requester_cannot_approve_their_own_exception_but_a_peer_can(
        self, api: ApiClient
    ) -> None:
        """The refusal moves nothing; the peer's identical request moves both versions.

        PRD: "A policy exception may not be approved or rejected by the analyst recorded
        as its `requested_by_analyst_id`. Violation:
        `ERR_DECISION_SEGREGATION_VIOLATION`."
        PRD: "`REQUESTED → APPROVED` records the deciding lead's `X-User-ID` as
        `approved_by_analyst_id`, stamps `decided_at` and stores `decision_note`. Because
        the customer's policy surface has changed, the customer's `version` increments by
        one alongside the exception's own."

        Design: Corner/errors/exception_decided_by_its_own_requester_rejected
        """
        set_clock(api)
        customer = create_high_value_customer(api, email="sod@example.com")
        assert int(customer["version"]) == 1
        first_lead = build_lead(api, display_name="LEAD1")
        second_lead = build_lead(api, display_name="LEAD2")

        exception = request_exception(api, customer["id"], first_lead["id"])
        assert exception["state"] == ExceptionState.REQUESTED
        assert exception["requested_by_analyst_id"] == first_lead["id"]
        assert int(read_customer(api, customer["id"])["version"]) == 1, (
            "filing a request does not touch the customer's policy surface"
        )

        self_approval = api.decide_policy_exception(
            exception["id"],
            exception_decision_payload(
                ExceptionAction.APPROVE, 1, decision_note="self approval attempt"
            ),
            make_review_lead_headers(first_lead["id"]),
        )
        validate_error(
            self_approval, ApiErrorId.ERR_DECISION_SEGREGATION_VIOLATION, 409
        )

        refused = validate_success(
            api.get_policy_exception(exception["id"], ADMIN), 200
        )
        assert refused["state"] == ExceptionState.REQUESTED
        assert refused["approved_by_analyst_id"] is None
        assert refused["decided_at"] is None
        assert int(read_customer(api, customer["id"])["version"]) == 1, (
            "a refused decision leaves the customer's version alone"
        )

        approved = decide_exception(
            api,
            exception["id"],
            second_lead["id"],
            ExceptionAction.APPROVE,
            1,
            decision_note="peer approved",
        )
        assert approved["state"] == ExceptionState.APPROVED
        assert approved["approved_by_analyst_id"] == second_lead["id"], (
            "the deciding lead is recorded, not the requester"
        )
        assert parse_instant(approved["decided_at"]) == parse_instant(CLOCK_EPOCH)
        assert int(read_customer(api, customer["id"])["version"]) == 2, (
            "the accepted decision changes the customer's policy surface"
        )


class TestStaleCustomerVersionOnDecision:
    """The decision token guards the beneficiary customer's policy surface."""

    def test_two_unrelated_posture_writes_invalidate_the_token_the_lead_holds(
        self, api: ApiClient
    ) -> None:
        """Version 1 is two writes behind, so only version 3 approves the exception.

        PRD: "`POST /fraud/policy-exceptions/{id}/decision` requires
        `expected_customer_version` as a non-optional field of the request body, carrying
        the client's last observed `version` of the beneficiary `Customer`. If it does not
        equal that customer's current `version`, the decision is rejected with
        `ERR_STALE_CUSTOMER_VERSION` (HTTP 412)."
        PRD: "`LOCKED → ACTIVE` clears `locked_reason` back to null, recomputes
        `good_customer_flag`, and increments `version` — making the account-status axis
        cyclic."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_customer_version_on_exception_decision
        """
        set_clock(api)
        customer = create_high_value_customer(api, email="occ@example.com")
        observed_version = int(customer["version"])
        assert observed_version == 1
        analyst = create_analyst(api, display_name="AN1")
        lead = build_lead(api, display_name="LEAD1")

        lock_customer(api, customer["id"], reason="manual hold during review")
        reopened = unlock_customer(api, customer["id"])
        assert reopened["account_status"] == AccountStatus.ACTIVE
        assert reopened["locked_reason"] is None
        assert int(reopened["version"]) == observed_version + 2, (
            "each posture write advances the customer's version by one"
        )

        exception = request_exception(api, customer["id"], analyst["id"])
        assert exception["state"] == ExceptionState.REQUESTED
        assert int(read_customer(api, customer["id"])["version"]) == (
            observed_version + 2
        ), "filing a request does not itself move the customer's version"

        stale = api.decide_policy_exception(
            exception["id"],
            exception_decision_payload(
                ExceptionAction.APPROVE, observed_version, decision_note="stale token"
            ),
            make_review_lead_headers(lead["id"]),
        )
        validate_error(stale, ApiErrorId.ERR_STALE_CUSTOMER_VERSION, 412)

        refused = validate_success(
            api.get_policy_exception(exception["id"], ADMIN), 200
        )
        assert refused["state"] == ExceptionState.REQUESTED
        assert int(read_customer(api, customer["id"])["version"]) == (
            observed_version + 2
        ), "the refused decision moved nothing"

        approved = decide_exception(
            api,
            exception["id"],
            lead["id"],
            ExceptionAction.APPROVE,
            observed_version + 2,
            decision_note="current token",
        )
        assert approved["state"] == ExceptionState.APPROVED
        assert approved["approved_by_analyst_id"] == lead["id"]
        assert int(read_customer(api, customer["id"])["version"]) == (
            observed_version + 3
        )
