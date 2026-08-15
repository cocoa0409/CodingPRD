"""Velocity rule boundary precision (difficulty) and rule/balance decline
semantics (corner)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_and_activate_rule,
    create_approved_auth,
    create_mcc_block_rule_payload,
    create_velocity_rule_payload,
    get_success_data,
    set_clock,
    setup_active_card_scenario,
    validate_error,
    validate_success,
)

CH = TEST_USERS["cardholder_ops_headers"]
CO = TEST_USERS["compliance_officer_headers"]


class TestVelocityWindowBoundary:
    def test_velocity_window_lower_bound_inclusive_counts_boundary_event(self, api):
        """PRD §3.5: "each rule's sliding window spans from the clock minus
        `window_seconds` up to the clock — both bounds inclusive, so an event
        sitting exactly at the window's start counts."

        Design: Difficulty/boundary_precision_check/velocity_window_lower_bound_inclusive
        """
        sc = setup_active_card_scenario(
            "P-VISA-11",
            program_daily_cap_cents=10_000_000,
            account_daily_cap_cents=1_000_000,
            fund_cents=100_000,
            bin_prefix="411100",
        )
        acct_id = sc["account"]["id"]
        card_id = sc["card"]["id"]
        create_and_activate_rule(
            create_velocity_rule_payload(
                "ACCOUNT", acct_id,
                window_seconds=60, max_txn_count=2, max_amount_cents=1_000_000,
                priority_rank=1,
            ),
        )
        # Auth A at t=00:00:00, auth B at t=00:00:30 — both APPROVED.
        auth_a = create_approved_auth(card_id, amount_cents=100)
        set_clock("2026-08-01T00:00:30Z")
        auth_b = create_approved_auth(card_id, amount_cents=100)
        # At t=00:01:00 the window is [00:00:00, 00:01:00]; auth A sits exactly
        # at the inclusive lower bound and still counts → 2 in window; a third
        # attempt would make count_in_window + 1 = 3 > 2 → DECLINED_VELOCITY.
        set_clock("2026-08-01T00:01:00Z")
        resp = api.create_authorization(
            card_id, {"amount_cents": 100, "mcc": "5411", "country_code": "US"}, CH,
        )
        assert auth_a["decision"] == "APPROVED"
        assert auth_b["decision"] == "APPROVED"
        # PRD §3.5: "the attempt is rejected with ERR_VELOCITY_EXCEEDED and
        # recorded DECLINED_VELOCITY" — the HTTP response is the 409 error
        # envelope; the event is recorded and queryable separately.
        validate_error(resp, ApiErrorId.ERR_VELOCITY_EXCEEDED.value)
        events = get_success_data(api.list_card_authorizations(card_id, CO))
        declined = [e for e in events if e["decision"] == "DECLINED_VELOCITY"]
        assert len(declined) == 1, (
            f"Inclusive lower bound keeps the boundary event in-window; third auth "
            f"must be recorded DECLINED_VELOCITY, got "
            f"{[e['decision'] for e in events]}"
        )

    def test_velocity_window_event_older_than_window_not_counted(self, api):
        """PRD §3.5: "each rule's sliding window spans from the clock minus
        `window_seconds` up to the clock — both bounds inclusive, so an event
        sitting exactly at the window's start counts."

        An event strictly older than clock - window_seconds falls outside the
        window: with max_txn_count=2, after the oldest event ages out the next
        authorization must be APPROVED (2 in window + 1 = 3 would breach, but
        only 1 remains in-window → 1+1 = 2, which hits the ceiling exactly and
        approves per "hitting a ceiling exactly still approves").

        Design: Difficulty/boundary_precision_check/velocity_window_lower_bound_inclusive
        """
        sc = setup_active_card_scenario(
            "P-VISA-11B",
            program_daily_cap_cents=10_000_000,
            account_daily_cap_cents=1_000_000,
            fund_cents=100_000,
            bin_prefix="411101",
        )
        acct_id = sc["account"]["id"]
        card_id = sc["card"]["id"]
        create_and_activate_rule(
            create_velocity_rule_payload(
                "ACCOUNT", acct_id,
                window_seconds=60, max_txn_count=2, max_amount_cents=1_000_000,
                priority_rank=1,
            ),
        )
        create_approved_auth(card_id, amount_cents=100)  # t = 00:00:00
        set_clock("2026-08-01T00:00:30Z")
        create_approved_auth(card_id, amount_cents=100)  # t = 00:00:30
        # Advance to t=00:01:01 — window [00:00:01, 00:01:01]: auth A (t=00:00:00)
        # is now strictly outside; only auth B counts (1 in window). 1+1 = 2
        # hits max_txn_count exactly → APPROVED.
        set_clock("2026-08-01T00:01:01Z")
        resp = api.create_authorization(
            card_id, {"amount_cents": 100, "mcc": "5411", "country_code": "US"}, CH,
        )
        data = validate_success(resp, expected_status=201)
        assert data["decision"] == "APPROVED", (
            f"After the oldest event ages out, hitting the ceiling exactly must "
            f"approve; got {data['decision']}"
        )


class TestRuleAndBalanceDeclines:
    def test_mcc_block_rule_declines_matching_auth(self, api):
        """PRD §3.5: "`MCC_BLOCK` rules decline listed merchant categories" and
        "a rule-determined decline records `DECLINED_RULE` with the winning
        rule's id."

        Design: Corner/calculations/mcc_block_rule_declines_matching_auth
        """
        sc = setup_active_card_scenario(
            "P-MCC",
            program_daily_cap_cents=10_000_000,
            account_daily_cap_cents=100_000,
            fund_cents=100_000,
        )
        acct_id = sc["account"]["id"]
        rule = create_and_activate_rule(
            create_mcc_block_rule_payload("ACCOUNT", acct_id, mcc_list=["7995"]),
        )
        resp = api.create_authorization(
            sc["card"]["id"],
            {"amount_cents": 1000, "mcc": "7995", "country_code": "US"},
            CH,
        )
        data = validate_success(resp, expected_status=201)
        assert data["decision"] == "DECLINED_RULE", (
            f"Auth against MCC_BLOCK-listed mcc must be DECLINED_RULE, got "
            f"{data['decision']}"
        )
        assert data.get("applied_rule_id") == rule["id"], (
            f"Decline must record the winning rule's id; got {data.get('applied_rule_id')}"
        )

    def test_insufficient_funds_declines_auth(self, api):
        """PRD §3.5: "The balance check comes first: if the account's
        `available_balance_cents` is less than the authorization amount, the
        attempt is rejected with `ERR_INSUFFICIENT_FUNDS`." and "An
        insufficient-balance decline records `DECLINED_LIMIT`."

        Design: Corner/validations/insufficient_funds_declines_auth
        """
        sc = setup_active_card_scenario(
            "P-IF",
            program_daily_cap_cents=10_000_000,
            account_daily_cap_cents=100_000,
            fund_cents=5000,
        )
        resp = api.create_authorization(
            sc["card"]["id"],
            {"amount_cents": 10000, "mcc": "5411", "country_code": "US"},
            CH,
        )
        # The fiscal rejection surfaces as an error envelope carrying
        # ERR_INSUFFICIENT_FUNDS; the recorded event reads DECLINED_LIMIT.
        if resp.status_code >= 400:
            validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_FUNDS.value)
        else:
            data = validate_success(resp, expected_status=201)
            assert data["decision"] == "DECLINED_LIMIT", (
                f"Insufficient balance must record DECLINED_LIMIT, got {data['decision']}"
            )
