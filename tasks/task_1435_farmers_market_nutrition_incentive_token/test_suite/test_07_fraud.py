"""Fraud signaling, case adjudication, and quarantine cascades (PRD §3.5, §3.7)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS,
    create_program, create_market, create_shopper_payload,
    setup_booth_scenario, setup_submitted_claim, issue_tokens,
    redeem_serials, close_day,
    create_fraud_case_payload,
    make_vendor_headers,
    assert_fraud_case,
)

ADMIN = TEST_USERS["program_admin_headers"]
BOOTH = TEST_USERS["booth_operator_headers"]
MANAGER = TEST_USERS["market_manager_headers"]
AUDITOR = TEST_USERS["auditor_headers"]

_VENDOR_CASCADE_QUOTE = (
    "When the case names a vendor, the cascade runs three hops: first the "
    "vendor transitions `ACTIVE → SUSPENDED`; then every claim of that vendor "
    "still `SUBMITTED` or `DISPUTED` transitions to `REJECTED`; then each "
    "rejected claim's attached tokens transition `REDEEMED → FLAGGED` and are "
    "detached, with each affected token's market-day totals recomputed."
)


class TestDoubleSpendDefense:
    def test_double_spend_auto_flags_token_and_opens_case(self, api):
        """PRD §3.5: "A token already `REDEEMED` or `SETTLED` triggers the
        double-spend defense: the attempt is rejected with
        `ERR_TOKEN_ALREADY_REDEEMED`, the held token immediately transitions
        `REDEEMED → FLAGGED`, and the platform opens a fraud case with `origin`
        `AUTO_DOUBLE_SPEND` whose `reason` records the attempting vendor's
        identity."
        PRD §3.2: "Because `FLAGGED` and `CONFISCATED` tokens count toward
        neither redeemed nor voided value, flagging a previously redeemed token
        raises the day's variance — quarantined value sits outside the ledger
        until its case resolves."

        Design: Corner/errors/c_err_double_spend_auto_flags_token_and_opens_case
        """
        sc = setup_booth_scenario()
        issuance, tokens = issue_tokens(sc["shopper"]["id"], sc["market_day"]["id"], 100)
        vend_id = sc["vendor"]["id"]
        t0 = tokens[0]
        redeem_serials(vend_id, [200001])

        second = api.redeem_token(200001, make_vendor_headers(vend_id))
        validate_error(second, ApiErrorId.ERR_TOKEN_ALREADY_REDEEMED)

        token = get_success_data(api.get_token(t0["id"], ADMIN))
        assert token["status"] == "FLAGGED", "held token quarantined by the defense"

        cases, meta = validate_paginated(
            api.list_fraud_cases(AUDITOR, params={"token_id": t0["id"]}))
        assert meta["total_count"] == 1, "exactly one case opened for the token"
        case = cases[0]
        assert_fraud_case(case)
        assert case["origin"] == "AUTO_DOUBLE_SPEND"
        assert case["status"] == "OPEN"

        day = get_success_data(api.get_market_day(sc["market_day"]["id"], MANAGER))
        assert day["redeemed_value_cents"] == 0, "flagged value leaves the redeemed ledger"


class TestFlagClearCycle:
    def _setup_flagged_token(self, api):
        """Charge 500 (1x500 base serial 100001); redeem it; Auditor opens a
        token case -> token FLAGGED."""
        sc = setup_booth_scenario()
        issuance, tokens = issue_tokens(sc["shopper"]["id"], sc["market_day"]["id"], 500)
        t0 = tokens[0]
        assert t0["serial_number"] == 100001
        redeem_serials(sc["vendor"]["id"], [100001])
        case = get_success_data(api.create_fraud_case(
            create_fraud_case_payload(reason="suspect", token_id=t0["id"]), AUDITOR))
        return sc, t0, case

    def test_flag_clear_cycle_restores_token(self, api):
        """PRD §3.7: "When a case targets a token, opening it immediately moves
        a `REDEEMED` token to `FLAGGED`."
        PRD §3.7: "When the cleared case names a token that currently sits
        `FLAGGED`, the token returns `FLAGGED → REDEEMED` and its market day's
        totals and variance recompute — the token's value counts toward
        `redeemed_value_cents` once more."

        Design: Difficulty/non_linear_state_machine/token_flag_clear_cycle_restores_redeemed
        """
        sc, t0, case = self._setup_flagged_token(api)
        flagged = get_success_data(api.get_token(t0["id"], ADMIN))
        assert flagged["status"] == "FLAGGED"

        cleared = validate_success(api.clear_fraud_case(case["id"], ADMIN))
        assert cleared["status"] == "CLEARED"
        token = get_success_data(api.get_token(t0["id"], ADMIN))
        assert token["status"] == "REDEEMED", "clearance returns the token to REDEEMED"
        assert token["redeemed_vendor_id"] == sc["vendor"]["id"]

    def test_flag_clear_cycle_restores_day_ledger(self, api):
        """PRD §3.7: "When the cleared case names a token that currently sits
        `FLAGGED`, the token returns `FLAGGED → REDEEMED` and its market day's
        totals and variance recompute — the token's value counts toward
        `redeemed_value_cents` once more."
        PRD §3.2: "Because `FLAGGED` and `CONFISCATED` tokens count toward
        neither redeemed nor voided value, flagging a previously redeemed token
        raises the day's variance — quarantined value sits outside the ledger
        until its case resolves."

        Design: Difficulty/non_linear_state_machine/token_flag_clear_cycle_restores_redeemed
        """
        sc, t0, case = self._setup_flagged_token(api)
        day_id = sc["market_day"]["id"]

        mid = get_success_data(api.get_market_day(day_id, MANAGER))
        assert mid["redeemed_value_cents"] == 0, "flagged token excluded from redeemed ledger"

        validate_success(api.clear_fraud_case(case["id"], ADMIN))
        day = get_success_data(api.get_market_day(day_id, MANAGER))
        assert day["redeemed_value_cents"] == 500, "ledger restored with no drift"
        assert day["variance_cents"] == 500, "issued 1000 - voided 0 - redeemed 500"


class TestVendorConfirmCascade:
    def _setup_vendor_case(self, api):
        """Charge 300 (3x100 base); vendor redeems serial 200001; claim [t0]
        SUBMITTED; Auditor opens a case on the VENDOR."""
        sc = setup_submitted_claim(charge=300, redeem_count=1)
        case = get_success_data(api.create_fraud_case(
            create_fraud_case_payload(reason="vendor under investigation",
                                      vendor_id=sc["vendor"]["id"]),
            AUDITOR))
        sc["case"] = case
        return sc

    def test_fraud_confirm_suspends_vendor_and_rejects_claim(self, api):
        """PRD §3.7: "When the case names a vendor, the cascade runs three
        hops: first the vendor transitions `ACTIVE → SUSPENDED`; then every
        claim of that vendor still `SUBMITTED` or `DISPUTED` transitions to
        `REJECTED`; then each rejected claim's attached tokens transition
        `REDEEMED → FLAGGED` and are detached, with each affected token's
        market-day totals recomputed."

        Design: Difficulty/transitive_cascade/fraud_confirm_vendor_cascade_depth4
        """
        sc = self._setup_vendor_case(api)
        confirmed = validate_success(api.confirm_fraud_case(sc["case"]["id"], ADMIN))
        assert confirmed["status"] == "CONFIRMED"

        vendor = get_success_data(api.get_vendor(sc["vendor"]["id"], ADMIN))
        assert vendor["status"] == "SUSPENDED", "hop 1: vendor suspended"
        submission = get_success_data(api.get_submission(sc["submission"]["id"], ADMIN))
        assert submission["status"] == "REJECTED", "hop 2: open claim rejected"

    def test_fraud_confirm_flags_tokens_and_recomputes_day(self, api):
        """PRD §3.7: "When the case names a vendor, the cascade runs three
        hops: first the vendor transitions `ACTIVE → SUSPENDED`; then every
        claim of that vendor still `SUBMITTED` or `DISPUTED` transitions to
        `REJECTED`; then each rejected claim's attached tokens transition
        `REDEEMED → FLAGGED` and are detached, with each affected token's
        market-day totals recomputed."
        PRD §3.2: "The day's `variance_cents` is what remains unaccounted:
        issued minus voided minus redeemed."

        Design: Difficulty/transitive_cascade/fraud_confirm_vendor_cascade_depth4
        """
        sc = self._setup_vendor_case(api)
        t0 = sc["claimed_tokens"][0]
        validate_success(api.confirm_fraud_case(sc["case"]["id"], ADMIN))

        token = get_success_data(api.get_token(t0["id"], ADMIN))
        assert token["status"] == "FLAGGED", "hop 3: attached token quarantined"
        assert token["submission_id"] is None, "token detached from the rejected claim"

        day = get_success_data(api.get_market_day(sc["market_day"]["id"], MANAGER))
        assert day["redeemed_value_cents"] == 0, "hop 4: flagged value excluded"
        assert day["variance_cents"] == 600, "issued 600 - voided 0 - redeemed 0"


class TestFraudCaseLifecycle:
    def test_fraud_case_terminal_lockdown(self, api):
        """PRD §3.7: "Adjudication belongs to the `ProgramAdmin` and comes in
        two terminal verdicts, `CONFIRMED` and `CLEARED`; the auditor who
        opened the case cannot issue either."
        PRD §2.10: "State gates come next: first the generic rule that any
        transition attempted from a state that does not permit it is rejected
        with `ERR_INVALID_STATE`, then the specific gates in their relative
        order — shopper eligibility (`ERR_SHOPPER_NOT_ELIGIBLE`), vendor
        standing (`ERR_VENDOR_NOT_ACTIVE`), market-day openness
        (`ERR_MARKET_DAY_NOT_OPEN`), and market-day closedness
        (`ERR_MARKET_DAY_NOT_CLOSED`)."

        Design: Corner/state_machines/c_sm_fraud_case_terminal_lockdown
        """
        program = create_program(pool_cents=50000)
        market = create_market(program["id"])
        vendor = get_success_data(api.create_vendor(
            {"market_id": market["id"], "legal_name": "V", "stall_number": "S1"}, ADMIN))
        case = get_success_data(api.create_fraud_case(
            create_fraud_case_payload(reason="audit", vendor_id=vendor["id"]), AUDITOR))
        confirmed = validate_success(api.confirm_fraud_case(case["id"], ADMIN))
        assert confirmed["status"] == "CONFIRMED"

        resp = api.clear_fraud_case(case["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        after = get_success_data(api.get_fraud_case(case["id"], ADMIN))
        assert after["status"] == "CONFIRMED", "CONFIRMED is terminal"

    def test_fraud_case_requires_exactly_one_subject(self, api):
        """PRD §3.7: "An `Auditor` opens a case with a free-text `reason` and
        exactly one of `vendor_id`, `shopper_id`, or `token_id`; supplying none
        of them or more than one is rejected with `ERR_SUBJECT_AMBIGUOUS`."
        PRD §3.7: "Cases opened through the API carry `origin` `MANUAL`, while
        the platform itself raises cases of `origin` `AUTO_DOUBLE_SPEND` after
        the double-spend defense of §3.5 fires; `AUTO_COUNTERFEIT_SERIAL`
        identifies cases rooted in the counterfeit-serial signal — a serial
        inside a live batch range that has never been minted, whose
        presentation is refused with `ERR_TOKEN_NOT_MINTED`."

        Design: Corner/validations/c_val_fraud_case_requires_exactly_one_subject
        """
        program = create_program(pool_cents=50000)
        market = create_market(program["id"])
        vendor = get_success_data(api.create_vendor(
            {"market_id": market["id"], "legal_name": "V", "stall_number": "S1"}, ADMIN))
        shopper = get_success_data(api.create_shopper(
            create_shopper_payload(program_id=program["id"]), BOOTH))

        none_set = api.create_fraud_case({"reason": "no subject"}, AUDITOR)
        validate_error(none_set, ApiErrorId.ERR_SUBJECT_AMBIGUOUS)

        two_set = api.create_fraud_case(
            {"reason": "two subjects", "vendor_id": vendor["id"],
             "shopper_id": shopper["id"]}, AUDITOR)
        validate_error(two_set, ApiErrorId.ERR_SUBJECT_AMBIGUOUS)

        ok = validate_success(api.create_fraud_case(
            {"reason": "ok", "vendor_id": vendor["id"]}, AUDITOR), expected_status=201)
        assert_fraud_case(ok)
        assert ok["origin"] == "MANUAL"
        assert ok["status"] == "OPEN"

    def test_auditor_cannot_confirm_own_fraud_case(self, api):
        """PRD §3.7: "Adjudication belongs to the `ProgramAdmin` and comes in
        two terminal verdicts, `CONFIRMED` and `CLEARED`; the auditor who
        opened the case cannot issue either."
        PRD §2.1: "An attempt to perform an operation outside the caller's
        designated role is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/c_rbac_auditor_cannot_confirm_own_fraud_case
        """
        program = create_program(pool_cents=50000)
        market = create_market(program["id"])
        vendor = get_success_data(api.create_vendor(
            {"market_id": market["id"], "legal_name": "V", "stall_number": "S1"}, ADMIN))
        case = get_success_data(api.create_fraud_case(
            create_fraud_case_payload(reason="audit trail", vendor_id=vendor["id"]), AUDITOR))

        resp = api.confirm_fraud_case(case["id"], AUDITOR)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

        after = get_success_data(api.get_fraud_case(case["id"], ADMIN))
        assert after["status"] == "OPEN", "case stays OPEN"


class TestQuarantinePriority:
    def test_flagged_token_blocked_from_submission_window_open(self, api):
        """PRD §3.6: "Each listed token then passes the strict attachment
        ladder used everywhere tokens are claimed: the token must exist
        (`ERR_REFERENCE_NOT_FOUND`), must not be `FLAGGED` (`ERR_TOKEN_FLAGGED`
        — quarantine outranks even an expired submission window), must have
        been redeemed by the submitting vendor (`ERR_TOKEN_VENDOR_MISMATCH`),
        and must not already be attached to another claim still in a
        non-terminal status — `SUBMITTED`, `VERIFIED`, `DISPUTED`, or
        `APPROVED` (`ERR_TOKEN_ALREADY_SUBMITTED`)."

        Design: Corner/validations/c_val_flagged_token_blocked_from_submission_window_open
        """
        sc = setup_booth_scenario()
        issuance, tokens = issue_tokens(sc["shopper"]["id"], sc["market_day"]["id"], 100)
        vend_id = sc["vendor"]["id"]
        t0 = tokens[0]
        redeem_serials(vend_id, [200001])
        get_success_data(api.create_fraud_case(
            create_fraud_case_payload(reason="suspect", token_id=t0["id"]), AUDITOR))

        resp = api.create_submission(
            {"market_day_id": sc["market_day"]["id"], "token_ids": [t0["id"]]},
            make_vendor_headers(vend_id))
        validate_error(resp, ApiErrorId.ERR_TOKEN_FLAGGED)

        subs, meta = validate_paginated(
            api.list_submissions(ADMIN, params={"vendor_id": vend_id}))
        assert meta["total_count"] == 0, "no submission created"

    def test_flagged_beats_expired_window(self, api):
        """PRD §2.10: "Fraud quarantine is evaluated after the state gates and
        deliberately outranks every remaining business rule, including
        submission-window expiry: a flagged token presented at redemption,
        claim creation, or claim resubmission is rejected with
        `ERR_TOKEN_FLAGGED` regardless of what else is wrong with the request."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_flagged_token_after_window
        """
        sc = setup_booth_scenario()
        issuance, tokens = issue_tokens(sc["shopper"]["id"], sc["market_day"]["id"], 300)
        vend_id = sc["vendor"]["id"]
        t0 = tokens[0]
        redeem_serials(vend_id, [t0["serial_number"]])
        get_success_data(api.create_fraud_case(
            create_fraud_case_payload(reason="suspect", token_id=t0["id"]), AUDITOR))
        close_day(sc["market_day"]["id"])
        # past the seven-day post-close window (closed 2026-08-01T14:00:00Z)
        validate_success(api.set_clock("2026-08-09T12:00:00Z", ADMIN))

        resp = api.create_submission(
            {"market_day_id": sc["market_day"]["id"], "token_ids": [t0["id"]]},
            make_vendor_headers(vend_id))
        validate_error(resp, ApiErrorId.ERR_TOKEN_FLAGGED)

    def test_flagged_beats_expired_window_no_submission_created(self, api):
        """PRD §2.10: "Fraud quarantine is evaluated after the state gates and
        deliberately outranks every remaining business rule, including
        submission-window expiry: a flagged token presented at redemption,
        claim creation, or claim resubmission is rejected with
        `ERR_TOKEN_FLAGGED` regardless of what else is wrong with the request."
        PRD §3.6: "The claim is also temporal: it may be lodged while the
        market day is still `OPEN`, or after close within a grace of seven days
        measured from the day's `closes_at`; outside that window the attempt is
        rejected with `ERR_SUBMISSION_WINDOW_CLOSED`."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_flagged_token_after_window
        """
        sc = setup_booth_scenario()
        issuance, tokens = issue_tokens(sc["shopper"]["id"], sc["market_day"]["id"], 300)
        vend_id = sc["vendor"]["id"]
        t0 = tokens[0]
        redeem_serials(vend_id, [t0["serial_number"]])
        get_success_data(api.create_fraud_case(
            create_fraud_case_payload(reason="suspect", token_id=t0["id"]), AUDITOR))
        close_day(sc["market_day"]["id"])
        validate_success(api.set_clock("2026-08-09T12:00:00Z", ADMIN))

        resp = api.create_submission(
            {"market_day_id": sc["market_day"]["id"], "token_ids": [t0["id"]]},
            make_vendor_headers(vend_id))
        err = validate_error(resp, ApiErrorId.ERR_TOKEN_FLAGGED)
        assert err["error_id"] != "ERR_SUBMISSION_WINDOW_CLOSED", (
            "quarantine outranks window expiry")

        subs, meta = validate_paginated(
            api.list_submissions(ADMIN, params={"vendor_id": vend_id}))
        assert meta["total_count"] == 0, "rejected claim leaves no submission row"
