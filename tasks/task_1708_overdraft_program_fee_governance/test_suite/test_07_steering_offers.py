"""Education offers (PRD §3.8): the fee-count steering trigger, lazy expiry,
terminal-state lockdown, and account-scoped optimistic concurrency (§2.8)."""
from test_helpers import (
    ApiErrorId,
    assert_same_instant,
    authorize,
    create_offer,
    get_account,
    get_offer,
    list_offers,
    make_account,
    make_account_holder_headers,
    make_opted_in_account,
    make_program,
    open_batch,
    run_posting_day,
    seal_batch,
    set_clock,
    settle_batch,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import TELLER


class TestSteeringOfferAtExactFeeCountThreshold:
    def _setup(self):
        """Standard program (steering 6 per 90, sustained threshold 5).
        Funded to 300 on Mon. Tue: two fees (settled). Wed: two fees
        (settled). Thu: two fees sealed, not yet settled."""
        program = make_program(name="OD-CAL4")
        account, _ = make_opted_in_account(program["id"], holder_name="H CAL4",
                                           channel="ONLINE")
        run_posting_day(program["id"], "2026-08-03", account["id"],
                        [("CREDIT_DEPOSIT", 300)], settle=True)
        run_posting_day(program["id"], "2026-08-04", account["id"],
                        [("DEBIT_ONE_TIME", 1000), ("DEBIT_ONE_TIME", 500)],
                        settle=True, clock_times=["2026-08-04T09:00:00Z",
                                                  "2026-08-04T09:01:00Z"])
        run_posting_day(program["id"], "2026-08-05", account["id"],
                        [("DEBIT_ONE_TIME", 100), ("DEBIT_ONE_TIME", 100)],
                        settle=True)
        batch4 = open_batch(program["id"], "2026-08-06")
        authorize(account["id"], "DEBIT_ONE_TIME", 100)
        authorize(account["id"], "DEBIT_ONE_TIME", 100)
        seal_batch(batch4["id"])
        return program, account, batch4

    def test_four_fees_in_window_produce_no_offer(self, api):
        """PRD §3.5: "If that count reaches or exceeds
        `steering_fee_count_threshold`, and the account has no offer currently
        `OFFERED` and no offer of any status created within the window, the
        server auto-creates an `EducationOffer` of type
        `OVERDRAFT_LINE_OF_CREDIT` with `trigger_reason` `FEE_THRESHOLD`, born
        `OFFERED` with `expires_at` set to the settle clock plus
        `offer_expiry_days`."

        Design: Corner/calculations/steering_offer_at_exact_fee_count_threshold
        """
        _, account, _ = self._setup()
        # After the 2026-08-05 settle there are 4 posted fees in the window;
        # 4 < 6, so no offer exists.
        assert list_offers(account["id"]) == []

    def test_sixth_fee_at_settle_triggers_fee_threshold_offer(self, api):
        """PRD §3.5: "It counts fees — both `OVERDRAFT` and `SUSTAINED` — whose
        `posted_date` falls inside the window and whose `status` is `POSTED` or
        `WAIVED`; `ASSESSED` and `VOIDED` fees never count."
        PRD §3.5: "If that count reaches or exceeds
        `steering_fee_count_threshold`, and the account has no offer currently
        `OFFERED` and no offer of any status created within the window, the
        server auto-creates an `EducationOffer` of type
        `OVERDRAFT_LINE_OF_CREDIT` with `trigger_reason` `FEE_THRESHOLD`, born
        `OFFERED` with `expires_at` set to the settle clock plus
        `offer_expiry_days`."

        Design: Corner/calculations/steering_offer_at_exact_fee_count_threshold
        """
        _, account, batch4 = self._setup()
        settle_batch(batch4["id"])
        offers = list_offers(account["id"])
        assert len(offers) == 1
        # Exactly 6 >= 6 after the third settle.
        assert offers[0]["trigger_reason"] == "FEE_THRESHOLD"
        assert offers[0]["status"] == "OFFERED"
        assert offers[0]["offer_type"] == "OVERDRAFT_LINE_OF_CREDIT"
        # Sustained threshold 5 not reached: the FEE_THRESHOLD path only.
        after = get_account(account["id"])
        assert after["status"] == "ACTIVE"
        assert after["consecutive_negative_business_days"] == 3


class TestOfferAcceptAfterExpiryRejected:
    def test_late_accept_fails_and_offer_surfaces_expired(self, api):
        """PRD §3.8: "Both actions require the logical clock to be on or before
        `expires_at` — a late answer is rejected with `ERR_OFFER_EXPIRED`".
        PRD §3.8: "Expiry itself is lazy: when the clock has passed
        `expires_at`, the offer surfaces as `EXPIRED` the next time it is read
        or acted upon".
        PRD §3.8: "The new offer is born `OFFERED` with `trigger_reason`
        `MANUAL` and `expires_at` set to the creation clock plus the program's
        `offer_expiry_days`."

        Design: Corner/validations/offer_accept_after_expiry_rejected
        """
        program = make_program(name="OD-V19")
        account = make_account(program["id"], holder_name="H V19")
        set_clock("2026-08-03T09:00:00Z")
        offer = create_offer(account["id"], offer_type="LINKED_SAVINGS")
        assert_same_instant(offer["expires_at"], "2026-09-02T09:00:00Z",
                            "offer.expires_at")

        set_clock("2026-09-02T09:00:01Z")
        holder = make_account_holder_headers(account["id"])
        resp = api.accept_education_offer(offer["id"], holder)
        validate_error(resp, ApiErrorId.ERR_OFFER_EXPIRED)
        assert get_offer(offer["id"])["status"] == "EXPIRED"


class TestAcceptDeclinedOfferRejected:
    def test_declined_is_terminal_for_accept(self, api):
        """PRD §3.8: "Accepting moves `OFFERED` to `ACCEPTED`; declining moves
        `OFFERED` to `DECLINED`."
        PRD §2.10: "seventh, state-machine validity of the requested transition
        and waivability of listed fees (`ERR_INVALID_STATE_TRANSITION`,
        `ERR_FEE_NOT_WAIVABLE`)".

        Design: Corner/state_machines/accept_declined_offer_returns_invalid_state
        """
        program = make_program(name="OD-SM7")
        account = make_account(program["id"], holder_name="H SM7")
        offer = create_offer(account["id"], offer_type="COUNSELING")
        assert offer["status"] == "OFFERED"

        holder = make_account_holder_headers(account["id"])
        declined = validate_success(
            api.decline_education_offer(offer["id"], holder))
        assert declined["status"] == "DECLINED"

        resp = api.accept_education_offer(offer["id"], holder)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


class TestOccOfferCreateStaleAccountVersion:
    def test_stale_account_version_rejected_then_fresh_create_supersedes(self, api):
        """PRD §3.8: "Manual creation carries the account-scoped
        optimistic-concurrency guard of §2.8 — a request whose
        `expected_account_version` no longer matches the account's current
        `version` is rejected with `ERR_STALE_ACCOUNT_VERSION` — and it has two
        standing effects: any offer currently `OFFERED` on the account is moved
        to `SUPERSEDED`, and the account's `version` increments."

        Design: Corner/cross_cutting_complexity_layers/occ_offer_create_stale_account_version
        """
        program = make_program(name="OD-OCC2")
        account = make_account(program["id"], holder_name="H OCC2")
        observed_version = account["version"]

        offer1 = validate_success(api.create_education_offer(
            {"account_id": account["id"], "offer_type": "LINKED_SAVINGS",
             "expected_account_version": observed_version}, TELLER), 201)
        assert offer1["status"] == "OFFERED"

        stale = api.create_education_offer(
            {"account_id": account["id"], "offer_type": "COUNSELING",
             "expected_account_version": observed_version}, TELLER)
        validate_error(stale, ApiErrorId.ERR_STALE_ACCOUNT_VERSION)

        fresh_version = get_account(account["id"])["version"]
        assert fresh_version == 2
        offer3 = validate_success(api.create_education_offer(
            {"account_id": account["id"], "offer_type": "COUNSELING",
             "expected_account_version": fresh_version}, TELLER), 201)
        assert offer3["status"] == "OFFERED"
        assert offer3["trigger_reason"] == "MANUAL"
        assert get_offer(offer1["id"])["status"] == "SUPERSEDED"
