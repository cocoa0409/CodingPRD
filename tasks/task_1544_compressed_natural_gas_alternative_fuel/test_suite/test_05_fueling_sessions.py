"""Fueling sessions: GGE dual-variant metering, price resolution, holds and
credit/daily gates, idempotency, ownership, voids, settlement lockdown, and
OCC on the account (PRD §2.9, §3.4)."""
import pytest

from test_helpers import (
    ApiErrorId,
    authorize_and_complete,
    authorize_session,
    authorize_session_ok,
    calibrate,
    complete_session_ok,
    create_active_contract,
    create_active_station,
    create_fleet_account,
    create_fleet_card,
    create_pricing_policy,
    get_account,
    get_account_version,
    get_station,
    get_success_data,
    make_fleet_account_manager_headers,
    make_fleet_driver_headers,
    set_clock,
    setup_fueling_ready,
    validate_error,
    validate_paginated,
    validate_success,
    void_session_ok,
)

HOLD_20_GGE_AT_289 = 5780  # round_half_up(20.0 * 289)


def _complete(env, session_id, mass_kg):
    return complete_session_ok(session_id, env["card"]["id"], mass_kg)


class TestDualVariantSessionGge:
    """Difficulty instance: session_gge_provisional_vs_settled_divergence (two tests)."""

    def _setup(self):
        # ACTIVE DUAL station; DSP-C calibrated at +0.50% -> PASS, factor 0.995.
        env = setup_fueling_ready(
            station_name="Alpha", station_code="ST-ALPHA", calibrate_error_pct=0.50
        )
        session = authorize_session_ok(
            env["card"]["id"], env["dispenser"]["id"], "CR-DV1", 20.0
        )
        return env, session

    def test_provisional_and_settled_gge_diverge_after_calibration(self, api):
        """PRD §3.4: "Completion computes two volumes from the constant 2.567
        kilograms per GGE: `provisional_gge` is the metered mass divided by
        2.567, rounded half-up to three decimals, ignoring calibration
        entirely; `settled_gge` multiplies the metered mass by
        `correction_factor_applied` — a snapshot of the dispenser's
        `correction_factor` taken at completion — before dividing by 2.567 and
        rounding half-up to three decimals."

        Design: Difficulty/dual_variant_calc/session_gge_provisional_vs_settled_divergence
        """
        env, session = self._setup()
        completed = _complete(env, session["id"], 25.0)
        assert completed["correction_factor_applied"] == pytest.approx(0.995, abs=1e-9)
        assert completed["provisional_gge"] == pytest.approx(9.739, abs=1e-9)
        assert completed["settled_gge"] == pytest.approx(9.690, abs=1e-9)
        assert completed["unit_price_cents"] == 289

    def test_billing_uses_settled_gge_not_provisional(self, api):
        """PRD §3.4: "`total_amount_cents` is `settled_gge` multiplied by the
        snapshot unit price, rounded half-up to a whole cent. For private
        sessions the account's balance rises by exactly the difference between
        `total_amount_cents` and the already-posted `hold_amount_cents`, the
        account `version` increments, and the card's `current_day_gge` rises by
        `settled_gge` with the card's `version` incrementing."

        Design: Difficulty/dual_variant_calc/session_gge_provisional_vs_settled_divergence
        """
        env, session = self._setup()
        completed = _complete(env, session["id"], 25.0)
        # settled 9.690 x 289 = 2800.41 -> 2800; provisional-based would give 2815.
        assert completed["total_amount_cents"] == 2800
        account = get_account(env["account"]["id"])
        assert account["outstanding_balance_cents"] == 2800, (
            "5780 hold replaced by 2800 actual"
        )


class TestGgeConstantAndPrecision:
    def test_gge_constant_and_precision_applied(self, api, network_operator_headers):
        """PRD §2.6: "The conversion constant for CNG is 2.567 kilograms per
        GGE: dividing a metered mass in kilograms by 2.567 yields the
        uncorrected GGE volume. Every GGE quantity the system computes —
        session volumes, daily card usage, settlement volumes, claim volumes —
        is rounded half-up to three decimal places, where "half-up" means a
        discarded fraction of exactly one-half rounds away from zero."

        Design: Corner/calculations/gge_constant_and_precision_applied
        """
        env = setup_fueling_ready(
            station_name="Prec", station_code="ST-PREC", credit_limit_cents=100000,
            daily_gge_limit=100.0,
        )
        session = authorize_session_ok(
            env["card"]["id"], env["dispenser"]["id"], "CR-PR1", 5.0
        )
        completed = _complete(env, session["id"], 5.135)
        assert completed["provisional_gge"] == pytest.approx(2.000, abs=1e-9)
        assert completed["total_amount_cents"] == 578  # 2.000 x 289
        assert get_account(env["account"]["id"])["outstanding_balance_cents"] == 578, (
            "hold round(5.0 x 289) = 1445 replaced by actual 578"
        )


class TestMtdTierThreshold:
    """Difficulty instance: mtd_tier_threshold_excludes_current_session (two tests)."""

    def _setup(self):
        env = setup_fueling_ready(
            station_name="Echo", station_code="ST-ECHO", access_mode="PRIVATE"
        )
        # Replace the plain policy with a tiered one (supersede same key).
        create_pricing_policy(
            env["station"]["id"],
            price_per_gge_cents=300,
            tier_threshold_gge=20.0,
            tier_price_cents=250,
        )
        card_id = env["card"]["id"]
        dispenser_id = env["dispenser"]["id"]
        # Two completed sessions of 20.536 kg -> 8.000 GGE each; MTD == 16.000.
        authorize_and_complete(card_id, dispenser_id, "CR-T1", 20.536, 10.0)
        authorize_and_complete(card_id, dispenser_id, "CR-T2", 20.536, 10.0)
        return env, card_id, dispenser_id

    def test_crossing_session_priced_at_base_rate(self, api):
        """PRD §3.4: "When a private session is priced from a policy carrying
        `tier_threshold_gge`, the account's month-to-date volume at that
        station — the sum of `settled_gge` over the account's non-voided
        COMPLETED and SETTLED private sessions there whose `completed_at` falls
        inside the current UTC calendar month, excluding the session being
        authorized — is compared against the threshold: at or above it,
        `tier_price_cents` applies; below it, `price_per_gge_cents`."

        Design: Difficulty/combinatorial_formula/mtd_tier_threshold_excludes_current_session
        """
        _env, card_id, dispenser_id = self._setup()
        s3 = authorize_session_ok(card_id, dispenser_id, "CR-T3", 10.0)
        assert s3["unit_price_cents"] == 300, (
            "MTD at authorize was 16.000 < 20.0; the crossing session itself does not count"
        )
        completed = complete_session_ok(s3["id"], card_id, 20.536)
        assert completed["total_amount_cents"] == 2400  # 8.000 x 300

    def test_next_session_after_threshold_priced_at_tier_rate(self, api):
        """PRD §3.4: "When a private session is priced from a policy carrying
        `tier_threshold_gge`, the account's month-to-date volume at that
        station — the sum of `settled_gge` over the account's non-voided
        COMPLETED and SETTLED private sessions there whose `completed_at` falls
        inside the current UTC calendar month, excluding the session being
        authorized — is compared against the threshold: at or above it,
        `tier_price_cents` applies; below it, `price_per_gge_cents`."

        Design: Difficulty/combinatorial_formula/mtd_tier_threshold_excludes_current_session
        """
        _env, card_id, dispenser_id = self._setup()
        authorize_and_complete(card_id, dispenser_id, "CR-T3", 20.536, 10.0)
        s4 = authorize_session_ok(card_id, dispenser_id, "CR-T4", 10.0)
        assert s4["unit_price_cents"] == 250, "MTD at authorize was 24.000 >= 20.0"
        completed = complete_session_ok(s4["id"], card_id, 20.536)
        assert completed["total_amount_cents"] == 2000  # 8.000 x 250


class TestCreditLimitBoundary:
    """Difficulty instance: credit_limit_exact_equality_authorized (two tests)."""

    def _station_env(self):
        env = create_active_station(station_name="Lima", station_code="ST-LIMA")
        create_pricing_policy(env["station"]["id"], price_per_gge_cents=289)
        return env

    def test_credit_limit_exact_equality_authorized(self, api):
        """PRD §3.4: "The account's `outstanding_balance_cents` plus the new
        hold must not exceed `credit_limit_cents` — equality is allowed, so an
        account may sit exactly at its limit — else the authorization is
        rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402)."

        Design: Difficulty/boundary_precision_check/credit_limit_exact_equality_authorized
        """
        env = self._station_env()
        a1 = create_fleet_account(account_name="Lima Exact", credit_limit_cents=5780)
        c1 = create_fleet_card(a1["id"])
        session = authorize_session_ok(c1["id"], env["dispensers"][0]["id"], "CR-B1", 20.0)
        assert session["status"] == "AUTHORIZED"
        assert session["hold_amount_cents"] == HOLD_20_GGE_AT_289
        assert get_account(a1["id"])["outstanding_balance_cents"] == HOLD_20_GGE_AT_289

    def test_one_cent_below_credit_limit_rejected(self, api):
        """PRD §3.4: "The account's `outstanding_balance_cents` plus the new
        hold must not exceed `credit_limit_cents` — equality is allowed, so an
        account may sit exactly at its limit — else the authorization is
        rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402)."

        Design: Difficulty/boundary_precision_check/credit_limit_exact_equality_authorized
        """
        env = self._station_env()
        a2 = create_fleet_account(account_name="Lima Short", credit_limit_cents=5779)
        c2 = create_fleet_card(a2["id"])
        resp = authorize_session(c2["id"], env["dispensers"][0]["id"], "CR-B2", 20.0)
        validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED, 402)


class TestBalanceConservation:
    """Difficulty instance: authorize_void_balance_conservation (two tests)."""

    def _env(self):
        return setup_fueling_ready(station_name="Romeo", station_code="ST-ROMEO")

    def test_authorize_then_void_restores_balance(self, api):
        """PRD §3.4: "Voiding an AUTHORIZED private session releases its hold:
        the balance falls by `hold_amount_cents` and the account `version`
        increments."
        PRD §3.3: "That balance is always derivable as the sum of three
        components: the holds on the account's AUTHORIZED sessions, the
        `total_amount_cents` of its non-voided COMPLETED and SETTLED sessions,
        and any settlement penalties posted by month-close contract settlement."

        Design: Difficulty/compensating_invariant/authorize_void_balance_conservation
        """
        env = self._env()
        card_id = env["card"]["id"]
        session = authorize_session_ok(card_id, env["dispenser"]["id"], "CR-V1", 20.0)
        assert get_account(env["account"]["id"])["outstanding_balance_cents"] == 5780
        void_session_ok(session["id"], make_fleet_driver_headers(card_id), "CUSTOMER_REQUEST")
        assert get_account(env["account"]["id"])["outstanding_balance_cents"] == 0, (
            "authorize+void leaves the conserved balance unchanged"
        )

    def test_complete_then_void_refunds_balance_and_daily_usage(self, api):
        """PRD §3.4: "Voiding a COMPLETED private session refunds it: the
        balance falls by `total_amount_cents` — the hold having already been
        netted out at completion — the account `version` increments, and the
        card's `current_day_gge` falls by `settled_gge`, never below zero."

        Design: Difficulty/compensating_invariant/authorize_void_balance_conservation
        """
        env = self._env()
        card_id = env["card"]["id"]
        session = authorize_session_ok(card_id, env["dispenser"]["id"], "CR-V2", 20.0)
        completed = complete_session_ok(session["id"], card_id, 25.0)
        # uncalibrated dispenser (factor 1.0): settled 9.739 x 289 = 2814.571 -> 2815.
        assert completed["total_amount_cents"] == 2815
        assert get_account(env["account"]["id"])["outstanding_balance_cents"] == 2815
        void_session_ok(session["id"], make_fleet_driver_headers(card_id), "CUSTOMER_REQUEST")
        assert get_account(env["account"]["id"])["outstanding_balance_cents"] == 0, (
            "complete+void refund leaves the conserved balance unchanged"
        )
        card = validate_success(
            api.get_fleet_card(
                card_id, make_fleet_account_manager_headers(env["account"]["id"])
            ),
            200,
        )
        assert card["current_day_gge"] == pytest.approx(0, abs=1e-9), (
            "the voided completion's 9.739 GGE was backed out of the daily rollup"
        )


class TestDispenserDependency:
    """Difficulty instance: authorize_requires_dispenser_in_service (two tests)."""

    def _setup(self):
        env = setup_fueling_ready(
            station_name="November", station_code="ST-NOV", num_dispensers=2
        )
        d1, d2 = env["dispensers"]
        calibrate(d1["id"], 0.51)  # FAIL -> OUT_OF_SERVICE
        return env, d1, d2

    def test_out_of_service_dispenser_rejects_authorize(self, api):
        """PRD §3.4: "The card must be ACTIVE (`ERR_CARD_NOT_ACTIVE`, HTTP 409)
        and its account ACTIVE (`ERR_ACCOUNT_NOT_ACTIVE`); the dispenser must
        be IN_SERVICE (`ERR_DISPENSER_NOT_IN_SERVICE`, HTTP 409); the station
        must be ACTIVE (`ERR_STATION_NOT_ACTIVE`); the station's posture must
        not be OUTAGE (`ERR_STATION_OUTAGE`); and the station's `access_mode`
        must serve the requested access type — PUBLIC stations serve public
        sessions, PRIVATE stations private sessions, DUAL stations both — else
        `ERR_ACCESS_MODE_MISMATCH` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/authorize_requires_dispenser_in_service
        """
        env, d1, _d2 = self._setup()
        resp = authorize_session(env["card"]["id"], d1["id"], "CR-X1", 20.0)
        validate_error(resp, ApiErrorId.ERR_DISPENSER_NOT_IN_SERVICE, 409)
        station = get_station(env["station"]["id"])
        assert station["uptime_posture"] == "OPERATIONAL", (
            "one IN_SERVICE dispenser keeps the station OPERATIONAL"
        )

    def test_healthy_dispenser_at_same_station_authorizes(self, api):
        """PRD §3.4: "The unit price is resolved exactly once, at
        authorization, and frozen into `unit_price_cents`; completion reuses
        the snapshot rather than re-resolving."
        PRD §2.7: "Otherwise the posture is OPERATIONAL."

        Design: Difficulty/cross_entity_state_dependency/authorize_requires_dispenser_in_service
        """
        env, _d1, d2 = self._setup()
        session = validate_success(
            authorize_session(env["card"]["id"], d2["id"], "CR-X2", 20.0), 201
        )
        assert session["status"] == "AUTHORIZED"
        assert session["unit_price_cents"] == 289


class TestPriorityStateBeatsFiscal:
    """Difficulty instance: authorize_dispenser_down_over_credit_state_beats_fiscal
    (two tests)."""

    def _setup(self):
        env = create_active_station(station_name="Juliett", station_code="ST-JUL")
        dispenser = env["dispensers"][0]
        record = calibrate(dispenser["id"], 0.51)  # FAIL -> OUT_OF_SERVICE
        account = create_fleet_account(account_name="Juliett Freight", credit_limit_cents=100)
        card = create_fleet_card(account["id"])
        return env, record, account, card

    def test_state_error_beats_fiscal_error(self, api):
        """PRD §2.8: "The stages run in the order given below, and when several
        checks would fail, the caller receives the error produced by the
        earliest applicable stage — later failures are masked, never reported
        alongside."
        PRD §2.8: "6. **State preconditions.** The station must be ACTIVE where
        required; the dispenser must be IN_SERVICE at authorization; the card
        and account must be ACTIVE where required ..."

        Design: Difficulty/priority_pair_validation_conflict/authorize_dispenser_down_over_credit_state_beats_fiscal
        """
        env, record, account, card = self._setup()
        assert record["result"] == "FAIL"
        resp = authorize_session(card["id"], env["dispensers"][0]["id"], "CR-P1", 20.0)
        validate_error(resp, ApiErrorId.ERR_DISPENSER_NOT_IN_SERVICE, 409)

    def test_rejected_authorize_posts_no_hold(self, api):
        """PRD §3.4: "On success the hold posts: `outstanding_balance_cents`
        rises by `hold_amount_cents` and the account's `version` increments by
        one."
        PRD §2.8: "10. **Fiscal gates, last.** Credit limit
        (`ERR_CREDIT_LIMIT_EXCEEDED`, HTTP 402), daily card GGE limit
        (`ERR_DAILY_LIMIT_EXCEEDED`, HTTP 409), resolvable unit price
        (`ERR_NO_ACTIVE_PRICE`, HTTP 422), zero-balance requirement on account
        close (`ERR_OUTSTANDING_BALANCE_NONZERO`, HTTP 409), non-empty eligible
        set on claim finalize (`ERR_NO_ELIGIBLE_VOLUME`, HTTP 422), and backup
        draw within commitment (`ERR_BACKUP_DRAW_EXCEEDED`, HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/authorize_dispenser_down_over_credit_state_beats_fiscal
        """
        env, _record, account, card = self._setup()
        version_before = account["version"]
        resp = authorize_session(card["id"], env["dispensers"][0]["id"], "CR-P2", 20.0)
        validate_error(resp, ApiErrorId.ERR_DISPENSER_NOT_IN_SERVICE, 409)
        after = get_account(account["id"])
        assert after["outstanding_balance_cents"] == 0
        assert after["version"] == version_before, "a rejected authorize mutates nothing"


class TestOutageGate:
    def test_posture_outage_blocks_authorize(self, api, station_manager_headers):
        """PRD §2.7: "New authorization attempts at a station whose posture is
        OUTAGE are rejected with `ERR_STATION_OUTAGE` (HTTP 409)."

        Design: Corner/calculations/posture_outage_blocks_authorize
        """
        env = setup_fueling_ready(
            station_name="Out", station_code="ST-OUT", credit_limit_cents=100000,
            daily_gge_limit=100.0,
        )
        validate_success(
            api.report_compressor_condition(
                env["compressor"]["id"], {"condition": "OFFLINE"}, station_manager_headers
            ),
            200,
        )
        resp = authorize_session(env["card"]["id"], env["dispenser"]["id"], "CR-OU1", 5.0)
        validate_error(resp, ApiErrorId.ERR_STATION_OUTAGE, 409)
        assert get_station(env["station"]["id"])["uptime_posture"] == "OUTAGE"


class TestNoActivePrice:
    def test_no_active_price_rejects_authorize(self, api):
        """PRD §3.4: "At most one such policy can exist, since creation
        supersedes same-key predecessors; if none matches, authorization fails
        with `ERR_NO_ACTIVE_PRICE` (HTTP 422)."

        Design: Corner/calculations/no_active_price_rejects_authorize
        """
        env = create_active_station(station_name="NoPrice", station_code="ST-NOPR")
        account = create_fleet_account(account_name="NoPrice Co", credit_limit_cents=100000)
        card = create_fleet_card(account["id"], daily_gge_limit=100.0)
        resp = authorize_session(card["id"], env["dispensers"][0]["id"], "CR-NP1", 5.0)
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_PRICE, 422)
        assert get_account(account["id"])["outstanding_balance_cents"] == 0


class TestContractPriceOverride:
    def test_contract_price_overrides_policy_price(self, api):
        """PRD §3.4: "First, for a private session only: if an ACTIVE supply
        contract covers the session's account and station and the current
        calendar month falls between the contract's `start_month` and
        `end_month` inclusive, the price is the contract's
        `contract_price_per_gge_cents` and resolution stops — a contract
        overrides all policy pricing."

        Design: Corner/calculations/contract_price_overrides_policy_price
        """
        env = setup_fueling_ready(
            station_name="Ovr", station_code="ST-OVR", access_mode="PRIVATE",
            price_per_gge_cents=289, credit_limit_cents=100000, daily_gge_limit=100.0,
        )
        create_active_contract(
            env["account"]["id"],
            env["station"]["id"],
            committed_monthly_gge=50.0,
            contract_price_per_gge_cents=275,
            start_month="2026-08",
            end_month="2026-12",
        )
        session = authorize_session_ok(
            env["card"]["id"], env["dispenser"]["id"], "CR-OV1", 10.0
        )
        assert session["unit_price_cents"] == 275, "contract overrides policy 289"
        assert session["hold_amount_cents"] == 2750  # 10.0 x 275


class TestDailyCardUsage:
    def test_daily_usage_rollup_accumulates_across_sessions(self, api):
        """PRD §3.3: "The card's `current_day_gge` is a running total of
        `settled_gge` across the card's non-voided COMPLETED and SETTLED
        sessions whose completion falls on `current_day_date`. It is maintained
        incrementally — incremented by `settled_gge` at completion, decremented
        by `settled_gge` (never below zero) when a COMPLETED session is
        voided — and the epoch sweep resets it to zero and re-dates it whenever
        the logical date has rolled past `current_day_date`."

        Design: Corner/calculations/daily_usage_rollup_accumulates_across_sessions
        """
        env = setup_fueling_ready(
            station_name="Roll", station_code="ST-ROLL", credit_limit_cents=100000,
            daily_gge_limit=100.0,
        )
        card_id = env["card"]["id"]
        dispenser_id = env["dispenser"]["id"]
        authorize_and_complete(card_id, dispenser_id, "CR-RO1", 25.0, 20.0)
        authorize_and_complete(card_id, dispenser_id, "CR-RO2", 1.0, 5.0)
        card = validate_success(
            api.get_fleet_card(
                card_id, make_fleet_account_manager_headers(env["account"]["id"])
            ),
            200,
        )
        assert card["current_day_gge"] == pytest.approx(10.129, abs=1e-9)  # 9.739 + 0.390
        assert card["current_day_date"] == "2026-08-01"

    def test_daily_limit_equality_allowed_then_exceeded(self, api):
        """PRD §3.4: "The card's `current_day_gge` plus `estimated_gge` must
        not exceed `daily_gge_limit`, equality again allowed, else
        `ERR_DAILY_LIMIT_EXCEEDED` (HTTP 409)."

        Design: Corner/validations/daily_limit_equality_allowed_then_exceeded
        """
        env = setup_fueling_ready(
            station_name="DL", station_code="ST-DL", daily_gge_limit=20.0
        )
        card_id = env["card"]["id"]
        dispenser_id = env["dispenser"]["id"]
        session = authorize_session_ok(card_id, dispenser_id, "CR-DL1", 20.0)
        completed = complete_session_ok(session["id"], card_id, 51.34)
        assert completed["status"] == "COMPLETED", (
            "estimate exactly at the daily limit was allowed"
        )
        assert completed["settled_gge"] == pytest.approx(20.000, abs=1e-9)
        resp = authorize_session(card_id, dispenser_id, "CR-DL2", 0.001)
        validate_error(resp, ApiErrorId.ERR_DAILY_LIMIT_EXCEEDED, 409)


class TestClientRefIdempotency:
    def test_idempotent_authorize_same_ref_same_card_returns_original(self, api):
        """PRD §3.4: "It is unique per station among non-VOIDED sessions:
        retrying an authorization with the same `client_ref` and the same card
        returns the originally created session rather than duplicating it,
        while a `client_ref` already used at that station by a different card
        or access type is rejected with `ERR_DUPLICATE_CLIENT_REF` (HTTP 409)."

        Design: Corner/validations/idempotent_authorize_same_ref_same_card_returns_original
        """
        env = setup_fueling_ready(
            station_name="Idem", station_code="ST-IDEM", credit_limit_cents=100000,
            daily_gge_limit=100.0,
        )
        card_id = env["card"]["id"]
        dispenser_id = env["dispenser"]["id"]
        s1 = authorize_session_ok(card_id, dispenser_id, "CR-IDEM", 20.0)
        replay = get_success_data(
            authorize_session(card_id, dispenser_id, "CR-IDEM", 20.0)
        )
        assert replay["id"] == s1["id"], "same session returned on idempotent replay"
        assert get_account(env["account"]["id"])["outstanding_balance_cents"] == 5780, (
            "exactly one hold posted"
        )

    def test_duplicate_client_ref_different_card_rejected(self, api):
        """PRD §3.4: "It is unique per station among non-VOIDED sessions:
        retrying an authorization with the same `client_ref` and the same card
        returns the originally created session rather than duplicating it,
        while a `client_ref` already used at that station by a different card
        or access type is rejected with `ERR_DUPLICATE_CLIENT_REF` (HTTP 409)."

        Design: Corner/validations/duplicate_client_ref_different_card_rejected
        """
        env = setup_fueling_ready(
            station_name="DupRef", station_code="ST-DREF", credit_limit_cents=100000,
            daily_gge_limit=100.0,
        )
        account_id = env["account"]["id"]
        c1 = env["card"]
        c2 = create_fleet_card(account_id, daily_gge_limit=100.0)
        authorize_session_ok(c1["id"], env["dispenser"]["id"], "CR-DUP", 20.0)
        resp = authorize_session(c2["id"], env["dispenser"]["id"], "CR-DUP", 20.0)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CLIENT_REF, 409)


class TestAccessMode:
    def test_public_session_at_private_only_station_rejected(self, api, anonymous_headers):
        """PRD §3.4: "The card must be ACTIVE (`ERR_CARD_NOT_ACTIVE`, HTTP 409)
        and its account ACTIVE (`ERR_ACCOUNT_NOT_ACTIVE`); the dispenser must
        be IN_SERVICE (`ERR_DISPENSER_NOT_IN_SERVICE`, HTTP 409); the station
        must be ACTIVE (`ERR_STATION_NOT_ACTIVE`); the station's posture must
        not be OUTAGE (`ERR_STATION_OUTAGE`); and the station's `access_mode`
        must serve the requested access type — PUBLIC stations serve public
        sessions, PRIVATE stations private sessions, DUAL stations both — else
        `ERR_ACCESS_MODE_MISMATCH` (HTTP 409)."

        Design: Corner/validations/public_session_at_private_only_station_rejected
        """
        env = create_active_station(
            station_name="PrivOnly", station_code="ST-PRV", access_mode="PRIVATE"
        )
        create_pricing_policy(env["station"]["id"], access_scope="PUBLIC",
                              price_per_gge_cents=319)
        resp = api.authorize_public_session(
            {
                "dispenser_id": env["dispensers"][0]["id"],
                "client_ref": "CR-PUB1",
                "estimated_gge": 5.0,
            },
            anonymous_headers,
        )
        validate_error(resp, ApiErrorId.ERR_ACCESS_MODE_MISMATCH, 409)

    def test_private_session_at_public_only_station_rejected(self, api):
        """PRD §3.4: "The card must be ACTIVE (`ERR_CARD_NOT_ACTIVE`, HTTP 409)
        and its account ACTIVE (`ERR_ACCOUNT_NOT_ACTIVE`); the dispenser must
        be IN_SERVICE (`ERR_DISPENSER_NOT_IN_SERVICE`, HTTP 409); the station
        must be ACTIVE (`ERR_STATION_NOT_ACTIVE`); the station's posture must
        not be OUTAGE (`ERR_STATION_OUTAGE`); and the station's `access_mode`
        must serve the requested access type — PUBLIC stations serve public
        sessions, PRIVATE stations private sessions, DUAL stations both — else
        `ERR_ACCESS_MODE_MISMATCH` (HTTP 409)."

        Design: Corner/validations/private_session_at_public_only_station_rejected
        """
        env = create_active_station(
            station_name="PubOnly", station_code="ST-PUB", access_mode="PUBLIC"
        )
        account = create_fleet_account(account_name="Pub Co", credit_limit_cents=100000)
        card = create_fleet_card(account["id"], daily_gge_limit=100.0)
        resp = authorize_session(card["id"], env["dispensers"][0]["id"], "CR-PU1", 5.0)
        validate_error(resp, ApiErrorId.ERR_ACCESS_MODE_MISMATCH, 409)

    def test_public_authorize_with_card_field_rejected(self, api, anonymous_headers):
        """PRD §3.4: "An `Anonymous` customer authorizes a public session with
        just `dispenser_id`, `client_ref`, and `estimated_gge`; sending
        `fleet_card_id` to the public door is `ERR_INVALID_REQUEST`, and on a
        public session `fleet_card_id` and `fleet_account_id` remain null and
        the hold is zero."

        Design: Corner/validations/public_authorize_with_card_field_rejected
        """
        env = create_active_station(station_name="PubFld", station_code="ST-PFLD")
        create_pricing_policy(env["station"]["id"], access_scope="PUBLIC",
                              price_per_gge_cents=319)
        resp = api.authorize_public_session(
            {
                "dispenser_id": env["dispensers"][0]["id"],
                "client_ref": "CR-PF1",
                "estimated_gge": 5.0,
                "fleet_card_id": "00000000-0000-4000-8000-0000000000bb",
            },
            anonymous_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


class TestOwnership:
    def test_driver_cannot_use_anothers_card(self, api):
        """PRD §3.4: "A `FleetDriver` authorizes a private session by
        presenting the `fleet_card_id` they hold — their `X-User-ID` must equal
        it, else `ERR_CARD_OWNERSHIP_MISMATCH` — together with the
        `dispenser_id` they intend to fuel from, a `client_ref` idempotency
        reference, a positive `estimated_gge` used to size the hold, and
        `expected_fleet_account_version` per §2.9."

        Design: Corner/validations/driver_cannot_use_anothers_card
        """
        env = create_active_station(station_name="Own", station_code="ST-OWN")
        create_pricing_policy(env["station"]["id"])
        a = create_fleet_account(account_name="Owner A", credit_limit_cents=100000)
        card_a = create_fleet_card(a["id"], daily_gge_limit=100.0)
        b = create_fleet_account(account_name="Owner B", credit_limit_cents=100000)
        card_b = create_fleet_card(b["id"], daily_gge_limit=100.0)
        resp = api.authorize_session(
            {
                "fleet_card_id": card_b["id"],
                "dispenser_id": env["dispensers"][0]["id"],
                "client_ref": "CR-OW1",
                "estimated_gge": 5.0,
                "expected_fleet_account_version": b["version"],
            },
            make_fleet_driver_headers(card_a["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CARD_OWNERSHIP_MISMATCH, 403)

    def test_fam_cannot_manage_other_accounts_cards(self, api):
        """PRD §3.3: "Cards are issued against an account by a
        `FleetAccountManager` acting on their own account or by a
        `NetworkOperator`; a manager reaching for another account is stopped
        with `ERR_ACCOUNT_OWNERSHIP_MISMATCH`."

        Design: Corner/validations/fam_cannot_manage_other_accounts_cards
        """
        a = create_fleet_account(account_name="FAM A", credit_limit_cents=100000)
        b = create_fleet_account(account_name="FAM B", credit_limit_cents=100000)
        resp = api.create_fleet_card(
            {
                "fleet_account_id": b["id"],
                "card_number": "FC-XO02",
                "vehicle_plate": "1OOO015",
                "daily_gge_limit": 100.0,
            },
            make_fleet_account_manager_headers(a["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_OWNERSHIP_MISMATCH, 403)


class TestAuthorizeValidationOrder:
    def test_existence_precedes_state_on_authorize(self, api, network_operator_headers):
        """PRD §2.8: "The stages run in the order given below, and when several
        checks would fail, the caller receives the error produced by the
        earliest applicable stage — later failures are masked, never reported
        alongside."
        PRD §2.8: "4. **Resource existence.** Path identifiers are validated
        left to right, then body foreign keys such as `dispenser_id`,
        `fleet_card_id`, `station_id`, `fleet_account_id`, and
        `compressor_id`."

        Design: Corner/validations/existence_precedes_state_on_authorize
        """
        env = create_active_station(station_name="Ord", station_code="ST-ORD")
        account = create_fleet_account(account_name="Ord Co", credit_limit_cents=100000)
        card = create_fleet_card(account["id"], daily_gge_limit=100.0)
        validate_success(api.suspend_fleet_account(account["id"], network_operator_headers), 200)
        resp = api.authorize_session(
            {
                "fleet_card_id": card["id"],
                "dispenser_id": "00000000-0000-4000-8000-0000000000aa",
                "client_ref": "CR-OR1",
                "estimated_gge": 5.0,
                "expected_fleet_account_version": get_account_version(account["id"]),
            },
            make_fleet_driver_headers(card["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DISPENSER_NOT_FOUND, 404)


class TestOccOnAuthorize:
    def test_occ_stale_account_version_on_authorize_returns_412(self, api):
        """PRD §2.9: "Authorizing a private fueling session through
        `POST /cng/fueling-sessions/authorize` requires the request to carry
        `expected_fleet_account_version`, holding the client's last observed
        `version` of the card's fleet account. If the account's current
        `version` no longer matches, the authorization is rejected with
        `ERR_STALE_ACCOUNT_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_account_version_on_authorize_returns_412
        """
        env = setup_fueling_ready(
            station_name="OCC2", station_code="ST-OCC2", credit_limit_cents=100000,
            daily_gge_limit=100.0,
        )
        card_id = env["card"]["id"]
        account_id = env["account"]["id"]
        observed_version = env["account"]["version"]
        s1 = authorize_session_ok(
            card_id, env["dispenser"]["id"], "CR-OCC1", 5.0
        )
        assert s1["status"] == "AUTHORIZED"
        # The first hold bumped FleetAccount.version, so the observed version is stale.
        from test_helpers.factories import authorize_session_payload

        resp = api.authorize_session(
            authorize_session_payload(
                card_id, env["dispenser"]["id"], "CR-OCC2", 5.0, observed_version
            ),
            make_fleet_driver_headers(card_id),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_ACCOUNT_VERSION, 412)
        assert get_account_version(account_id) == observed_version + 1


class TestSuspendedCard:
    def test_authorize_with_suspended_card_rejected(self, api):
        """PRD §3.4: "Authorization is gated in pipeline order. The card must
        be ACTIVE (`ERR_CARD_NOT_ACTIVE`, HTTP 409) and its account ACTIVE
        (`ERR_ACCOUNT_NOT_ACTIVE`); the dispenser must be IN_SERVICE
        (`ERR_DISPENSER_NOT_IN_SERVICE`, HTTP 409); the station must be ACTIVE
        (`ERR_STATION_NOT_ACTIVE`); the station's posture must not be OUTAGE
        (`ERR_STATION_OUTAGE`); and the station's `access_mode` must serve the
        requested access type — PUBLIC stations serve public sessions, PRIVATE
        stations private sessions, DUAL stations both — else
        `ERR_ACCESS_MODE_MISMATCH` (HTTP 409)."

        Design: Corner/validations/authorize_with_suspended_card_rejected
        """
        env = setup_fueling_ready(
            station_name="CardS", station_code="ST-CARDS", credit_limit_cents=100000,
            daily_gge_limit=100.0,
        )
        account_id = env["account"]["id"]
        card_id = env["card"]["id"]
        validate_success(
            api.set_fleet_card_status(
                card_id, {"to_status": "SUSPENDED"},
                make_fleet_account_manager_headers(account_id),
            ),
            200,
        )
        resp = authorize_session(card_id, env["dispenser"]["id"], "CR-CS1", 5.0)
        validate_error(resp, ApiErrorId.ERR_CARD_NOT_ACTIVE, 409)


class TestSettledSessionLockdown:
    def test_session_settled_terminal_lockdown(self, api):
        """PRD §3.4: "A session in AUTHORIZED or COMPLETED may be voided —
        anything else, including the terminal SETTLED and VOIDED states, draws
        `ERR_SESSION_NOT_VOIDABLE` (HTTP 409)."
        PRD §3.4: "The session must still be AUTHORIZED, else
        `ERR_SESSION_NOT_COMPLETABLE` (HTTP 409)."
        PRD §3.4: "SETTLED is terminal and immutable — never voidable — and is
        exactly the population the final tax-credit computation draws on."

        Design: Corner/state_machines/session_settled_terminal_lockdown
        """
        env = setup_fueling_ready(
            station_name="Lock", station_code="ST-LOCK", credit_limit_cents=100000,
            daily_gge_limit=100.0,
        )
        card_id = env["card"]["id"]
        set_clock("2026-07-15T12:00:00Z")
        session = authorize_and_complete(card_id, env["dispenser"]["id"], "CR-L1", 25.0)
        assert session["total_amount_cents"] == 2815  # 9.739 x 289 at factor 1.0
        set_clock("2026-08-01T00:00:00Z")
        settled = validate_success(
            api.get_fueling_session(session["id"], make_fleet_driver_headers(card_id)), 200
        )
        assert settled["status"] == "SETTLED", "sweep settled the July session"

        resp_void = api.void_session(
            session["id"], {"reason": "CUSTOMER_REQUEST"}, make_fleet_driver_headers(card_id)
        )
        validate_error(resp_void, ApiErrorId.ERR_SESSION_NOT_VOIDABLE, 409)
        resp_complete = api.complete_session(
            session["id"], {"metered_mass_kg": 25.0}, make_fleet_driver_headers(card_id)
        )
        validate_error(resp_complete, ApiErrorId.ERR_SESSION_NOT_COMPLETABLE, 409)
        after = validate_success(
            api.get_fueling_session(session["id"], make_fleet_driver_headers(card_id)), 200
        )
        assert after["total_amount_cents"] == 2815, "unchanged by the rejected operations"


class TestSessionListFilters:
    def test_session_list_filters_by_status(self, api, station_manager_headers):
        """PRD §3.4: "Session collections support filtering by `station_id`,
        `fleet_account_id`, `fleet_card_id`, `dispenser_id`, `status`, and
        `month`."

        Design: Corner/endpoints/session_list_filters_by_status
        """
        env = setup_fueling_ready(
            station_name="Filt", station_code="ST-FILT", credit_limit_cents=100000,
            daily_gge_limit=100.0,
        )
        card_id = env["card"]["id"]
        dispenser_id = env["dispenser"]["id"]
        s1 = authorize_and_complete(card_id, dispenser_id, "CR-FI1", 25.0)
        s2 = authorize_session_ok(card_id, dispenser_id, "CR-FI2", 20.0)
        station_id = env["station"]["id"]

        rows, meta = validate_paginated(
            api.list_fueling_sessions(
                station_manager_headers,
                params={"station_id": station_id, "status": "COMPLETED"},
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == s1["id"]
        rows, meta = validate_paginated(
            api.list_fueling_sessions(
                station_manager_headers,
                params={"station_id": station_id, "status": "AUTHORIZED"},
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == s2["id"]


class TestDriverSessionScoping:
    def test_fleet_driver_session_list_scoped_to_own_card(self, api):
        """PRD §2.10: "`FleetDriver` views are scoped to their own card, that
        card's sessions, and their own account. Requesting a detail resource
        outside the caller's scope is rejected with
        `ERR_ACCOUNT_OWNERSHIP_MISMATCH` or `ERR_CARD_OWNERSHIP_MISMATCH`
        (HTTP 403) as applicable."

        Design: Corner/rbac/fleet_driver_session_list_scoped_to_own_card
        """
        env = create_active_station(station_name="ScopeS", station_code="ST-SCPS")
        create_pricing_policy(env["station"]["id"])
        dispenser_id = env["dispensers"][0]["id"]
        a = create_fleet_account(account_name="Drv A", credit_limit_cents=100000)
        card_a = create_fleet_card(a["id"], daily_gge_limit=100.0)
        b = create_fleet_account(account_name="Drv B", credit_limit_cents=100000)
        card_b = create_fleet_card(b["id"], daily_gge_limit=100.0)
        sess_a = authorize_session_ok(card_a["id"], dispenser_id, "CR-SCA", 5.0)
        authorize_session_ok(card_b["id"], dispenser_id, "CR-SCB", 5.0)
        rows, meta = validate_paginated(
            api.list_fueling_sessions(make_fleet_driver_headers(card_a["id"]))
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == sess_a["id"], "card B's session is invisible"
