"""Issuance gates: day-open, shopper eligibility, OCC, fiscal ladder, batch supply (PRD §3.4)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    create_market_day,
    setup_booth_scenario, issue_tokens, minted_tokens, redeem_serials,
    create_issuance_payload,
)

ADMIN = TEST_USERS["program_admin_headers"]
BOOTH = TEST_USERS["booth_operator_headers"]
MANAGER = TEST_USERS["market_manager_headers"]


def _issue_attempt(api, shopper_id, day_id, charge, expected_version):
    return api.create_issuance(
        create_issuance_payload(shopper_id=shopper_id, market_day_id=day_id,
                                benefit_charged_cents=charge,
                                expected_shopper_version=expected_version),
        BOOTH)


def _no_issuance_for_shopper(api, shopper_id):
    data, meta = validate_paginated(api.list_issuances(BOOTH, params={"shopper_id": shopper_id}))
    assert meta["total_count"] == 0, "no issuance row created"


class TestMarketDayGate:
    def test_issuance_on_scheduled_day_rejected(self, api):
        """PRD §3.4: "Three gates precede any minting: the shopper must be
        `ACTIVE` (`ERR_SHOPPER_NOT_ELIGIBLE`), the market day must be `OPEN`
        (`ERR_MARKET_DAY_NOT_OPEN`), and the charge itself must respect
        whole-dollar scrip — below one dollar the request is rejected with
        `ERR_CHARGE_TOO_SMALL`, and a charge that is not a multiple of 100
        cents is rejected with `ERR_FRACTIONAL_CHARGE`."

        Design: Difficulty/cross_entity_state_dependency/issuance_gated_by_market_day_open
        """
        sc = setup_booth_scenario(with_vendor=False, open_day=False)
        sc["market_day"] = create_market_day(sc["market"]["id"])  # stays SCHEDULED
        resp = _issue_attempt(api, sc["shopper"]["id"], sc["market_day"]["id"],
                              500, sc["shopper"]["version"])
        validate_error(resp, ApiErrorId.ERR_MARKET_DAY_NOT_OPEN)

    def test_issuance_on_scheduled_day_no_side_effects(self, api):
        """PRD §3.4: "Three gates precede any minting: the shopper must be
        `ACTIVE` (`ERR_SHOPPER_NOT_ELIGIBLE`), the market day must be `OPEN`
        (`ERR_MARKET_DAY_NOT_OPEN`), and the charge itself must respect
        whole-dollar scrip — below one dollar the request is rejected with
        `ERR_CHARGE_TOO_SMALL`, and a charge that is not a multiple of 100
        cents is rejected with `ERR_FRACTIONAL_CHARGE`."
        PRD §3.4: "Recording it raises the shopper's
        `season_match_used_cents` by the minted match, draws the program's
        `match_pool_remaining_cents` down by the same amount, and raises the
        market day's `issued_value_cents` by base plus match; the shopper, the
        program, and the market day each increment their `version`."

        Design: Difficulty/cross_entity_state_dependency/issuance_gated_by_market_day_open
        """
        sc = setup_booth_scenario(with_vendor=False, open_day=False)
        day = create_market_day(sc["market"]["id"])
        resp = _issue_attempt(api, sc["shopper"]["id"], day["id"],
                              500, sc["shopper"]["version"])
        validate_error(resp, ApiErrorId.ERR_MARKET_DAY_NOT_OPEN)

        _no_issuance_for_shopper(api, sc["shopper"]["id"])
        program = get_success_data(api.get_program(sc["program"]["id"], ADMIN))
        assert program["match_pool_remaining_cents"] == 100000, "pool untouched by rejected issuance"


class TestStateGateBeatsFiscal:
    def _suspended_shopper_scenario(self, api):
        sc = setup_booth_scenario(with_vendor=False)
        suspended = get_success_data(api.suspend_shopper(sc["shopper"]["id"], ADMIN))
        assert suspended["status"] == "SUSPENDED"
        return sc, suspended

    def test_state_gate_beats_fiscal_on_suspended_shopper(self, api):
        """PRD §2.10: "State gates come next: first the generic rule that any
        transition attempted from a state that does not permit it is rejected
        with `ERR_INVALID_STATE`, then the specific gates in their relative
        order — shopper eligibility (`ERR_SHOPPER_NOT_ELIGIBLE`), vendor
        standing (`ERR_VENDOR_NOT_ACTIVE`), market-day openness
        (`ERR_MARKET_DAY_NOT_OPEN`), and market-day closedness
        (`ERR_MARKET_DAY_NOT_CLOSED`)."
        PRD §2.10: "The fiscal rules close the ladder, in this relative order:
        batch-serial sufficiency (`ERR_BATCH_SERIALS_INSUFFICIENT`), the charge
        floor (`ERR_CHARGE_TOO_SMALL`), the whole-dollar multiple
        (`ERR_FRACTIONAL_CHARGE`), batch availability
        (`ERR_NO_ACTIVE_TOKEN_BATCH`), voidability (`ERR_ISSUANCE_NOT_VOIDABLE`),
        and reconciliation variance (`ERR_RECONCILIATION_VARIANCE`)."
        PRD §3.3: "Any attempt to issue tokens to a shopper who is not
        `ACTIVE`, whether still `ENROLLED` or already `SUSPENDED`, is rejected
        with `ERR_SHOPPER_NOT_ELIGIBLE`."

        Design: Difficulty/priority_pair_validation_conflict/state_gate_beats_fiscal_on_suspended_shopper_fractional_charge
        """
        sc, suspended = self._suspended_shopper_scenario(api)
        # charge 150 violates the whole-dollar rule; shopper suspension must win
        resp = _issue_attempt(api, sc["shopper"]["id"], sc["market_day"]["id"],
                              150, suspended["version"])
        validate_error(resp, ApiErrorId.ERR_SHOPPER_NOT_ELIGIBLE)

    def test_state_gate_beats_fiscal_no_side_effects(self, api):
        """PRD §3.3: "Any attempt to issue tokens to a shopper who is not
        `ACTIVE`, whether still `ENROLLED` or already `SUSPENDED`, is rejected
        with `ERR_SHOPPER_NOT_ELIGIBLE`."
        PRD §2.10: "The fiscal rules close the ladder, in this relative order:
        batch-serial sufficiency (`ERR_BATCH_SERIALS_INSUFFICIENT`), the charge
        floor (`ERR_CHARGE_TOO_SMALL`), the whole-dollar multiple
        (`ERR_FRACTIONAL_CHARGE`), batch availability
        (`ERR_NO_ACTIVE_TOKEN_BATCH`), voidability (`ERR_ISSUANCE_NOT_VOIDABLE`),
        and reconciliation variance (`ERR_RECONCILIATION_VARIANCE`)."

        Design: Difficulty/priority_pair_validation_conflict/state_gate_beats_fiscal_on_suspended_shopper_fractional_charge
        """
        sc, suspended = self._suspended_shopper_scenario(api)
        resp = _issue_attempt(api, sc["shopper"]["id"], sc["market_day"]["id"],
                              150, suspended["version"])
        validate_error(resp, ApiErrorId.ERR_SHOPPER_NOT_ELIGIBLE)

        _no_issuance_for_shopper(api, sc["shopper"]["id"])
        program = get_success_data(api.get_program(sc["program"]["id"], ADMIN))
        assert program["match_pool_remaining_cents"] == 100000


class TestOptimisticConcurrency:
    def test_stale_shopper_version_rejected(self, api):
        """PRD §2.8: "Creating an issuance (`POST /issuances`) requires a
        non-optional `expected_shopper_version` carrying the shopper `version`
        the client last observed. If the shopper's current `version` has since
        advanced — because another issuance, a void, or a suspension
        legitimately moved the row — the create is rejected with
        `ERR_STALE_VERSION` (HTTP 412), so a booth operator can never mint
        against a stale view of the shopper's match ledger."

        Design: Corner/validations/c_val_occ_stale_shopper_version_rejected
        """
        sc = setup_booth_scenario(with_vendor=False)
        stale_version = sc["shopper"]["version"] - 1
        resp = _issue_attempt(api, sc["shopper"]["id"], sc["market_day"]["id"],
                              500, stale_version)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        _no_issuance_for_shopper(api, sc["shopper"]["id"])
        program = get_success_data(api.get_program(sc["program"]["id"], ADMIN))
        assert program["match_pool_remaining_cents"] == 100000, "pool untouched"

    def test_fresh_version_issuance_bumps_exactly_once(self, api):
        """PRD §2.8: "Creating an issuance (`POST /issuances`) requires a
        non-optional `expected_shopper_version` carrying the shopper `version`
        the client last observed. If the shopper's current `version` has since
        advanced — because another issuance, a void, or a suspension
        legitimately moved the row — the create is rejected with
        `ERR_STALE_VERSION` (HTTP 412), so a booth operator can never mint
        against a stale view of the shopper's match ledger."
        PRD §3.4: "Recording it raises the shopper's
        `season_match_used_cents` by the minted match, draws the program's
        `match_pool_remaining_cents` down by the same amount, and raises the
        market day's `issued_value_cents` by base plus match; the shopper, the
        program, and the market day each increment their `version`."

        Design: Corner/validations/c_val_occ_fresh_version_succeeds_and_bumps_exactly_once
        """
        sc = setup_booth_scenario(with_vendor=False)
        before = sc["shopper"]["version"]
        assert before == 2, "enroll 1, verify 2"
        issuance = validate_success(
            _issue_attempt(api, sc["shopper"]["id"], sc["market_day"]["id"], 100, before),
            expected_status=201)
        assert issuance["status"] == "ACTIVE"

        shopper = get_success_data(api.get_shopper(sc["shopper"]["id"], BOOTH))
        assert shopper["version"] == before + 1, "exactly one version bump per mutation"


class TestChargeFiscalRules:
    def test_charge_floor_and_fractional_lattice(self, api):
        """PRD §3.4: "Three gates precede any minting: the shopper must be
        `ACTIVE` (`ERR_SHOPPER_NOT_ELIGIBLE`), the market day must be `OPEN`
        (`ERR_MARKET_DAY_NOT_OPEN`), and the charge itself must respect
        whole-dollar scrip — below one dollar the request is rejected with
        `ERR_CHARGE_TOO_SMALL`, and a charge that is not a multiple of 100
        cents is rejected with `ERR_FRACTIONAL_CHARGE`."
        PRD §2.10: "The fiscal rules close the ladder, in this relative order:
        batch-serial sufficiency (`ERR_BATCH_SERIALS_INSUFFICIENT`), the charge
        floor (`ERR_CHARGE_TOO_SMALL`), the whole-dollar multiple
        (`ERR_FRACTIONAL_CHARGE`), batch availability
        (`ERR_NO_ACTIVE_TOKEN_BATCH`), voidability (`ERR_ISSUANCE_NOT_VOIDABLE`),
        and reconciliation variance (`ERR_RECONCILIATION_VARIANCE`)."

        Design: Corner/validations/c_val_charge_too_small_and_fractional_lattice
        """
        sc = setup_booth_scenario(with_vendor=False)
        shop_id, day_id = sc["shopper"]["id"], sc["market_day"]["id"]
        version = sc["shopper"]["version"]

        too_small = _issue_attempt(api, shop_id, day_id, 50, version)
        validate_error(too_small, ApiErrorId.ERR_CHARGE_TOO_SMALL)

        fractional = _issue_attempt(api, shop_id, day_id, 250, version)
        validate_error(fractional, ApiErrorId.ERR_FRACTIONAL_CHARGE)

        _no_issuance_for_shopper(api, shop_id)
        program = get_success_data(api.get_program(sc["program"]["id"], ADMIN))
        assert program["match_pool_remaining_cents"] == 100000
        shopper = get_success_data(api.get_shopper(shop_id, BOOTH))
        assert shopper["season_match_used_cents"] == 0


class TestBodyReferenceValidation:
    def test_body_reference_not_found(self, api):
        """PRD §2.9: "Identifiers referenced inside a request body —
        `shopper_id`, `market_day_id`, `program_id`, `market_id`, the elements
        of `token_ids`, and the fraud-case subject fields `vendor_id`,
        `shopper_id`, and `token_id` — are validated after the path resolves; a
        body reference to a missing resource is rejected with
        `ERR_REFERENCE_NOT_FOUND`."

        Design: Corner/validations/c_val_body_reference_not_found
        """
        sc = setup_booth_scenario(with_vendor=False, open_day=False)
        resp = _issue_attempt(api, sc["shopper"]["id"], NON_EXISTENT_UUID,
                              500, sc["shopper"]["version"])
        validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND)


class TestBatchSupplyFailures:
    def test_issuance_without_active_match_batch_rejected(self, api):
        """PRD §3.4: "If no `ACTIVE` batch exists at all for a needed
        combination the issuance fails with `ERR_NO_ACTIVE_TOKEN_BATCH`; if
        active batches exist but none can cover the needed count on its own, it
        fails with `ERR_BATCH_SERIALS_INSUFFICIENT`."

        Design: Corner/validations/c_val_issuance_without_active_match_batch_rejected
        """
        sc = setup_booth_scenario(with_vendor=False, match_batch_active=False)
        resp = _issue_attempt(api, sc["shopper"]["id"], sc["market_day"]["id"],
                              500, sc["shopper"]["version"])
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_TOKEN_BATCH)

        tokens, meta = validate_paginated(api.list_tokens(BOOTH, params={"limit": 100}))
        assert meta["total_count"] == 0, "failed issuance mints nothing"
        program = get_success_data(api.get_program(sc["program"]["id"], ADMIN))
        assert program["match_pool_remaining_cents"] == 100000

    def test_batch_serials_insufficient_atomic_rejection(self, api):
        """PRD §3.4: "If no `ACTIVE` batch exists at all for a needed
        combination the issuance fails with `ERR_NO_ACTIVE_TOKEN_BATCH`; if
        active batches exist but none can cover the needed count on its own, it
        fails with `ERR_BATCH_SERIALS_INSUFFICIENT`."
        PRD §3.4: "Eligible batches belong to the issuance's market, carry the
        needed `kind` and `denomination_cents`, are `ACTIVE`, and hold enough
        unminted serials — the count of serials from `next_serial` through
        `serial_end` inclusive must be at least the number of tokens needed,
        because a denomination's mint is atomic and never splits across
        batches."

        Design: Corner/validations/c_val_batch_serials_insufficient_atomic_rejection
        """
        # MATCH batch with only 2 serials cannot supply a 500-cent match (5 tokens)
        sc = setup_booth_scenario(with_vendor=False, match_serial_end=300002)
        resp = _issue_attempt(api, sc["shopper"]["id"], sc["market_day"]["id"],
                              500, sc["shopper"]["version"])
        validate_error(resp, ApiErrorId.ERR_BATCH_SERIALS_INSUFFICIENT)

        tokens, meta = validate_paginated(api.list_tokens(BOOTH, params={"limit": 100}))
        assert meta["total_count"] == 0, "no partial mint"
        bm = get_success_data(api.get_token_batch(sc["batch_match"]["id"], ADMIN))
        assert bm["next_serial"] == 300001, "match batch cursor unmoved"
        b5 = get_success_data(api.get_token_batch(sc["batch_base500"]["id"], ADMIN))
        assert b5["next_serial"] == 100001, "base batch cursor unmoved"


class TestIssuanceVoid:
    def test_void_blocked_once_token_redeemed(self, api):
        """PRD §3.4: "The issuance must still be `ACTIVE`; its market day must
        still be `OPEN`, because voids are same-day reversals only — otherwise
        the attempt is rejected with `ERR_MARKET_DAY_NOT_OPEN`; and every token
        the issuance minted must still sit in `ISSUED` status — once any one of
        them has been redeemed, settled, voided, flagged, or confiscated, the
        issuance is no longer voidable and the attempt is rejected with
        `ERR_ISSUANCE_NOT_VOIDABLE`."

        Design: Corner/state_machines/c_sm_issuance_void_blocked_once_token_redeemed
        """
        sc = setup_booth_scenario()
        issuance, tokens = issue_tokens(sc["shopper"]["id"], sc["market_day"]["id"], 200)
        redeem_serials(sc["vendor"]["id"], [200001])

        resp = api.void_issuance(issuance["id"], BOOTH)
        validate_error(resp, ApiErrorId.ERR_ISSUANCE_NOT_VOIDABLE)

        after = get_success_data(api.get_issuance(issuance["id"], BOOTH))
        assert after["status"] == "ACTIVE", "issuance untouched"
        program = get_success_data(api.get_program(sc["program"]["id"], ADMIN))
        assert program["match_pool_remaining_cents"] == 99800, "no compensating credit on rejection"

    def test_void_restores_match_pool_exactly(self, api):
        """PRD §3.4: "A successful void moves the issuance `ACTIVE → VOIDED`
        and every one of its tokens `ISSUED → VOIDED`, subtracts the issuance's
        match from the shopper's `season_match_used_cents`, returns the same
        match amount to the program's `match_pool_remaining_cents` as a
        compensating credit, and recomputes the day's `issued_value_cents` with
        the voided issuance excluded."

        Design: Difficulty/compensating_invariant/issuance_void_restores_match_pool_exactly
        """
        sc = setup_booth_scenario(with_vendor=False)
        issuance, _tokens = issue_tokens(sc["shopper"]["id"], sc["market_day"]["id"], 1200)
        assert issuance["match_cents"] == 1200
        mid = get_success_data(api.get_program(sc["program"]["id"], ADMIN))
        assert mid["match_pool_remaining_cents"] == 98800

        voided = validate_success(api.void_issuance(issuance["id"], BOOTH))
        assert voided["status"] == "VOIDED"
        program = get_success_data(api.get_program(sc["program"]["id"], ADMIN))
        assert program["match_pool_remaining_cents"] == 100000, "compensating credit restores budget"

    def test_void_restores_shopper_usage_and_day_ledger(self, api):
        """PRD §3.4: "A successful void moves the issuance `ACTIVE → VOIDED`
        and every one of its tokens `ISSUED → VOIDED`, subtracts the issuance's
        match from the shopper's `season_match_used_cents`, returns the same
        match amount to the program's `match_pool_remaining_cents` as a
        compensating credit, and recomputes the day's `issued_value_cents` with
        the voided issuance excluded."

        Design: Difficulty/compensating_invariant/issuance_void_restores_match_pool_exactly
        """
        sc = setup_booth_scenario(with_vendor=False)
        issuance, tokens = issue_tokens(sc["shopper"]["id"], sc["market_day"]["id"], 1200)
        validate_success(api.void_issuance(issuance["id"], BOOTH))

        shopper = get_success_data(api.get_shopper(sc["shopper"]["id"], BOOTH))
        assert shopper["season_match_used_cents"] == 0
        day = get_success_data(api.get_market_day(sc["market_day"]["id"], MANAGER))
        assert day["issued_value_cents"] == 0, "voided issuance excluded from the day's ledger"
        for token in minted_tokens(issuance["id"]):
            assert token["status"] == "VOIDED", "every token of the issuance is voided"
