"""Bank account registration, callback verification policy, cooling-off, and
bank-gated payment-run adds."""
import pytest
from datetime import timedelta

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    assert_vendor,
    assert_bank_account,
    assert_callback_verification,
    assert_timestamp_equals,
    parse_timestamp,
    create_vendor,
    get_vendor,
    add_bank_account,
    get_callback_code,
    list_callback_verifications,
    confirm_bank_account,
    add_verified_primary_bank_account,
    onboard_vendor_to_active,
    onboard_payable_vendor,
    wrong_verification_codes,
    set_clock,
    run_vendor_sweep,
    create_matrix_rule,
    create_approved_invoice,
    create_payment_run,
    get_invoice,
    create_invoice,
    submit_invoice,
    approve_invoice_fully,
)

VS1 = TEST_USERS["vendor_specialist_headers"]
VS2 = TEST_USERS["vendor_specialist_2_headers"]
VM1 = TEST_USERS["vendor_manager_headers"]
CLERK = TEST_USERS["ap_clerk_headers"]
TA = TEST_USERS["treasury_analyst_headers"]
AUD = TEST_USERS["auditor_headers"]


class TestCallbackVerificationLifecycle:
    def test_callback_verification_code_server_minted_with_expiry(self, api):
        """Bank-account creation mints a PENDING verification: six-digit code,
        attempts 0, expires_at exactly 48h after created_at.

        PRD §3.3: "The server mints a six-digit `verification_code`, which is deemed phoned to the vendor at its pre-existing `phone` number — the callback must dial that known number, never a number supplied alongside the new account details."
        PRD §3.3: "The verification is born `PENDING` with `attempts` at zero, its `expires_at` fixed at creation to exactly 48 hours after its `created_at`, and a link to its account through `bank_account_id`."
        PRD §3.3: "The new account is born in `PENDING_VERIFICATION` with the caller recorded as `requested_by_user_id` (the SoD-3 anchor), the vendor's `version` increments by one, and a `CREATE` audit event is appended."

        Design: Corner/entities/callback_verification_code_server_minted_with_expiry
        """
        set_clock("2026-08-01T00:00:00Z")
        vendor = create_vendor(legal_name="Callback Crafts", tax_id="20-0000007")
        v0 = vendor["version"]
        account = add_bank_account(vendor["id"], requester=VS1,
                                   account_holder_name="Callback Crafts")
        assert_bank_account(account)
        assert account["status"] == "PENDING_VERIFICATION"
        assert account["requested_by_user_id"] == "u-vs-01"
        assert get_vendor(vendor["id"])["version"] == v0 + 1, \
            "adding a bank account increments the vendor's version"

        verifications, meta = validate_paginated(
            api.list_callback_verifications(account["id"], AUD))
        assert meta["total_count"] == 1
        verification = verifications[0]
        assert_callback_verification(verification)
        assert verification["status"] == "PENDING"
        assert verification["attempts"] == 0
        assert verification["bank_account_id"] == account["id"]
        code = verification["verification_code"]
        assert isinstance(code, str) and len(code) == 6 and code.isdigit(), \
            "the verification code is a server-minted six-digit string"
        assert parse_timestamp(verification["expires_at"]) == (
            parse_timestamp(verification["created_at"]) + timedelta(hours=48))
        assert_timestamp_equals(verification["expires_at"], "2026-08-03T00:00:00Z")

    def test_callback_locks_on_third_mismatch(self, api):
        """Attempts 1-2 reject with ERR_CALLBACK_CODE_MISMATCH; the 3rd locks the
        verification, rejects the account, and even the correct code then fails.

        PRD §3.3: "Finally the code itself is compared: a mismatch increments `attempts` and, while fewer than three attempts have accumulated, is rejected with `ERR_CALLBACK_CODE_MISMATCH`; the third mismatch instead locks the verification — it becomes `LOCKED`, its parent account moves from `PENDING_VERIFICATION` to `REJECTED` — and the rejection carries `ERR_CALLBACK_LOCKED`."
        PRD §3.3: "A verification already `CONFIRMED` is rejected with `ERR_INVALID_STATE_TRANSITION`; a `LOCKED` verification is rejected with `ERR_CALLBACK_LOCKED`; an `EXPIRED` verification is rejected with `ERR_CALLBACK_EXPIRED`."

        Design: Corner/validations/callback_locks_on_third_mismatch
        """
        vendor = create_vendor(legal_name="Lock Loom", tax_id="20-0000028")
        account = add_bank_account(vendor["id"], requester=VS1,
                                   account_holder_name="Lock Loom")
        real_code = get_callback_code(account["id"])
        wrong1, wrong2, wrong3 = wrong_verification_codes(real_code, 3)

        validate_error(api.confirm_bank_verification(
            account["id"], {"verification_code": wrong1}, VM1),
            ApiErrorId.ERR_CALLBACK_CODE_MISMATCH.value)
        assert list_callback_verifications(account["id"])[0]["attempts"] == 1

        validate_error(api.confirm_bank_verification(
            account["id"], {"verification_code": wrong2}, VM1),
            ApiErrorId.ERR_CALLBACK_CODE_MISMATCH.value)
        assert list_callback_verifications(account["id"])[0]["attempts"] == 2

        validate_error(api.confirm_bank_verification(
            account["id"], {"verification_code": wrong3}, VM1),
            ApiErrorId.ERR_CALLBACK_LOCKED.value)
        verification = list_callback_verifications(account["id"])[0]
        assert verification["status"] == "LOCKED"
        assert verification["attempts"] == 3
        assert get_success_data(api.get_bank_account(account["id"], AUD))["status"] == "REJECTED"

        validate_error(api.confirm_bank_verification(
            account["id"], {"verification_code": real_code}, VM1),
            ApiErrorId.ERR_CALLBACK_LOCKED.value)

    def test_sod_callback_requester_cannot_confirm(self, api):
        """SoD-3: the account's requester cannot confirm it; the SoD guard runs
        before the code comparison, so no attempt is consumed.

        PRD §2.6: "The operator confirming a callback verification must not be the operator recorded as `requested_by_user_id` on the bank account."
        PRD §2.6: "A violation is rejected with `ERR_SOD_CALLBACK_REQUESTER_CANNOT_CONFIRM`."
        PRD §3.3: "The guards fire in a fixed order."
        PRD §3.3: "SoD-3 then bars the account's requester from confirming it, yielding `ERR_SOD_CALLBACK_REQUESTER_CANNOT_CONFIRM`."

        Design: Corner/validations/sod_callback_requester_cannot_confirm_forbidden
        """
        vendor = create_vendor(legal_name="Callback Conflict", tax_id="20-0000033")
        account = add_bank_account(vendor["id"], requester=VS1,
                                   account_holder_name="Callback Conflict")
        code = get_callback_code(account["id"])

        resp = api.confirm_bank_verification(
            account["id"], {"verification_code": code}, VS1)
        validate_error(resp, ApiErrorId.ERR_SOD_CALLBACK_REQUESTER_CANNOT_CONFIRM.value)
        verification = list_callback_verifications(account["id"])[0]
        assert verification["status"] == "PENDING"
        assert verification["attempts"] == 0, "SoD fires before the code comparison"

    def test_callback_expiry_strict_greater_cascades_account_rejected(self, api):
        """Expiry uses strict >: at exactly expires_at the verification survives;
        one second later the sweep expires it and rejects the pending account.

        PRD §3.3: "And when the vendor sweep finds a verification still `PENDING` at a logical time strictly later than its `expires_at`, the verification becomes `EXPIRED` and its parent account — still `PENDING_VERIFICATION` — becomes `REJECTED`, each with a `STATUS_CHANGE` audit event."
        PRD §3.3: "A confirmation presented while the verification is still `PENDING`, with fewer than three accumulated attempts, and at a logical time no later than `expires_at` — at exactly `expires_at` the code remains confirmable — succeeds: the verification becomes `CONFIRMED` with the caller recorded as `confirmed_by_user_id`, the account becomes `VERIFIED` with `verified_at` stamped at the logical time, and a `VERIFY` audit event is appended."

        Design: Corner/state_machines/callback_expiry_strict_greater_cascades_account_rejected
        """
        set_clock("2026-08-01T00:00:00Z")
        vendor = create_vendor(legal_name="Expiry Experts", tax_id="20-0000016")
        account = add_bank_account(vendor["id"], requester=VS1,
                                   account_holder_name="Expiry Experts")

        set_clock("2026-08-03T00:00:00Z")  # exactly expires_at
        counters = run_vendor_sweep()
        assert counters["callback_verifications_expired"] == 0
        assert list_callback_verifications(account["id"])[0]["status"] == "PENDING"

        set_clock("2026-08-03T00:00:01Z")  # strictly past expires_at
        counters = run_vendor_sweep()
        assert counters["callback_verifications_expired"] == 1
        assert list_callback_verifications(account["id"])[0]["status"] == "EXPIRED"
        assert get_success_data(api.get_bank_account(account["id"], AUD))["status"] == "REJECTED"

    def test_callback_confirm_after_expiry_rejected(self, api):
        """The correct code presented after expiry still fails: EXPIRED is
        terminal, not retryable.

        PRD §3.3: "A verification already `CONFIRMED` is rejected with `ERR_INVALID_STATE_TRANSITION`; a `LOCKED` verification is rejected with `ERR_CALLBACK_LOCKED`; an `EXPIRED` verification is rejected with `ERR_CALLBACK_EXPIRED`."

        Design: Corner/errors/callback_confirm_after_expiry_rejected
        """
        set_clock("2026-08-01T00:00:00Z")
        vendor = create_vendor(legal_name="Expired Echo", tax_id="20-0000053")
        account = add_bank_account(vendor["id"], requester=VS1,
                                   account_holder_name="Expired Echo")
        code = get_callback_code(account["id"])

        set_clock("2026-08-04T00:00:00Z")
        counters = run_vendor_sweep()
        assert counters["callback_verifications_expired"] == 1

        resp = api.confirm_bank_verification(
            account["id"], {"verification_code": code}, VM1)
        validate_error(resp, ApiErrorId.ERR_CALLBACK_EXPIRED.value)
        assert list_callback_verifications(account["id"])[0]["status"] == "EXPIRED"
        assert get_success_data(api.get_bank_account(account["id"], AUD))["status"] == "REJECTED"

    def test_occ_bank_account_create_stale_version(self, api):
        """Bank-account creation is OCC-guarded on the vendor: an intervening
        PATCH makes the create fail 412 and persist nothing.

        PRD §2.8: "Three write operations on the vendor master require the client to state which version of the vendor it last observed, carried in the non-optional request field `expected_vendor_version`: editing a vendor's master data, adding a bank account to a vendor, and merging a duplicate vendor into a survivor (in the merge case the check applies to the survivor vendor's version)."
        PRD §2.8: "If `expected_vendor_version` does not equal the vendor's current `version`, the client's view of the vendor is stale — another write has legitimately advanced the record since the client last read it — and the request is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than being silently layered over the newer state."

        Design: Corner/cross_cutting_layers/occ_bank_account_create_stale_version
        """
        vendor = create_vendor(legal_name="Occ Bank Co", tax_id="20-0000062")
        v0 = vendor["version"]
        validate_success(api.patch_vendor(
            vendor["id"], {"phone": "+1-555-7001",
                           "expected_vendor_version": v0}, VS2))

        resp = api.create_bank_account(vendor["id"], {
            "account_number": "000999111777", "routing_number": "021000021",
            "account_holder_name": "Occ Bank Co", "is_primary": True,
            "expected_vendor_version": v0}, VS1)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
        accounts, meta = validate_paginated(api.list_bank_accounts(vendor["id"], AUD))
        assert meta["total_count"] == 0, "no bank account may persist from the stale write"


class TestBankGatesOnPaymentRunAdd:
    def test_run_add_without_verified_bank_rejected(self, api):
        """Only a PENDING_VERIFICATION account exists: the run add fails because
        the vendor has no primary VERIFIED bank account.

        PRD §3.6: "With the vendor cleared, its banking gates follow: the vendor must have a primary `VERIFIED` bank account, else `ERR_BANK_ACCOUNT_NOT_VERIFIED`, and at least 72 hours must have elapsed since that primary account's `verified_at` — the bank-change cooling-off, where a primary verified exactly 72 hours ago passes and a fresher one rejects with `ERR_BANK_CHANGE_COOLING_OFF`."

        Design: Corner/validations/run_add_without_verified_bank_rejected
        """
        set_clock("2026-06-01T00:00:00Z")
        create_matrix_rule()
        vendor = onboard_vendor_to_active(
            legal_name="Unverified Union", tax_id="20-0000037")
        add_bank_account(vendor["id"], requester=VS1,
                         account_holder_name="Unverified Union")  # never confirmed

        set_clock("2026-08-01T00:00:00Z")
        invoice = create_approved_invoice(vendor["id"], amount_cents=100000,
                                          invoice_number="INV-9960",
                                          received_date="2026-08-01")
        run = create_payment_run(scheduled_date="2026-08-05")
        resp = api.add_invoice_to_run(run["id"], {"invoice_id": invoice["id"]}, TA)
        validate_error(resp, ApiErrorId.ERR_BANK_ACCOUNT_NOT_VERIFIED.value)
        assert get_invoice(invoice["id"])["status"] == "APPROVED"

    def test_disable_bank_account_in_use_rejected(self, api):
        """Disable is refused while a PENDING payment references the account.

        PRD §3.3: "The manual gate refuses the disable while any payment in `PENDING` or `RELEASED` references the account, rejecting with `ERR_BANK_ACCOUNT_IN_USE`."

        Design: Corner/validations/disable_bank_account_in_use_rejected
        """
        set_clock("2026-06-01T00:00:00Z")
        create_matrix_rule()
        vendor, account = onboard_payable_vendor(
            legal_name="In Use Ivy", tax_id="20-0000039")

        set_clock("2026-08-01T00:00:00Z")
        invoice = create_approved_invoice(vendor["id"], amount_cents=100000,
                                          invoice_number="INV-9980",
                                          received_date="2026-08-01")
        run = create_payment_run(scheduled_date="2026-08-05")
        payment = get_success_data(api.add_invoice_to_run(
            run["id"], {"invoice_id": invoice["id"]}, TA))
        assert payment["bank_account_id"] == account["id"]

        resp = api.disable_bank_account(account["id"], VM1)
        validate_error(resp, ApiErrorId.ERR_BANK_ACCOUNT_IN_USE.value)
        reloaded = get_success_data(api.get_bank_account(account["id"], AUD))
        assert reloaded["status"] == "VERIFIED"
        assert get_vendor(vendor["id"])["primary_bank_account_id"] == account["id"]


class TestBankCoolingOffBoundary:
    def _setup_cooling_off_scenario(self, api):
        """Vendor activated 2026-07-01; primary bank VERIFIED 2026-08-01T00:00:00Z;
        invoice approved at 2026-08-02 (bank 24h old -> tier bump to 2)."""
        set_clock("2026-07-01T00:00:00Z")
        create_matrix_rule()
        vendor = onboard_vendor_to_active(
            legal_name="Cooling Colloids", tax_id="10-0000012")
        set_clock("2026-08-01T00:00:00Z")
        account = add_verified_primary_bank_account(
            vendor["id"], account_holder_name="Cooling Colloids")

        set_clock("2026-08-02T00:00:00Z")
        invoice = create_invoice(vendor["id"], amount_cents=100000,
                                 invoice_number="INV-8201",
                                 received_date="2026-08-02")
        submitted = submit_invoice(invoice["id"])
        assert submitted["required_tier"] == 2, \
            "recent-bank bump applies (verified 24h before submit; vendor older than 30 days)"
        approve_invoice_fully(invoice["id"])
        run = create_payment_run(scheduled_date="2026-08-10")
        return vendor, account, invoice, run

    def test_run_add_rejected_inside_cooling_off_window(self, api):
        """At verified_at + 48h the add fails ERR_BANK_CHANGE_COOLING_OFF and
        the invoice stays APPROVED.

        PRD §3.6: "With the vendor cleared, its banking gates follow: the vendor must have a primary `VERIFIED` bank account, else `ERR_BANK_ACCOUNT_NOT_VERIFIED`, and at least 72 hours must have elapsed since that primary account's `verified_at` — the bank-change cooling-off, where a primary verified exactly 72 hours ago passes and a fresher one rejects with `ERR_BANK_CHANGE_COOLING_OFF`."

        Design: Difficulty/cross_entity_state_dependency/run_add_gated_by_bank_cooling_off
        """
        vendor, account, invoice, run = self._setup_cooling_off_scenario(api)
        set_clock("2026-08-03T00:00:00Z")  # verified_at + 48h
        resp = api.add_invoice_to_run(run["id"], {"invoice_id": invoice["id"]}, TA)
        validate_error(resp, ApiErrorId.ERR_BANK_CHANGE_COOLING_OFF.value)
        assert get_invoice(invoice["id"])["status"] == "APPROVED"

    def test_run_add_succeeds_at_exactly_72h_boundary(self, api):
        """At verified_at + exactly 72h the cooling-off passes (inclusive
        boundary) and the payment snapshots the vendor's primary account.

        PRD §3.6: "With the vendor cleared, its banking gates follow: the vendor must have a primary `VERIFIED` bank account, else `ERR_BANK_ACCOUNT_NOT_VERIFIED`, and at least 72 hours must have elapsed since that primary account's `verified_at` — the bank-change cooling-off, where a primary verified exactly 72 hours ago passes and a fresher one rejects with `ERR_BANK_CHANGE_COOLING_OFF`."
        PRD §3.6: "A successful add moves the invoice from `APPROVED` to `IN_PAYMENT_RUN` and creates a `PENDING` payment that snapshots everything it needs: `payment_run_id` and `invoice_id` link it into place, `vendor_id` is denormalized from the invoice, `bank_account_id` snapshots the vendor's current primary account and `bank_account_version` that account's `version` at this instant, and `amount_cents` carries the invoice's gross at add time."

        Design: Difficulty/cross_entity_state_dependency/run_add_gated_by_bank_cooling_off
        """
        vendor, account, invoice, run = self._setup_cooling_off_scenario(api)
        set_clock("2026-08-03T00:00:00Z")  # +48h: still cooling off
        validate_error(api.add_invoice_to_run(
            run["id"], {"invoice_id": invoice["id"]}, TA),
            ApiErrorId.ERR_BANK_CHANGE_COOLING_OFF.value)

        set_clock("2026-08-04T00:00:00Z")  # exactly +72h: passes
        payment = validate_success(api.add_invoice_to_run(
            run["id"], {"invoice_id": invoice["id"]}, TA), expected_status=201)
        assert payment["status"] == "PENDING"
        assert payment["bank_account_id"] == account["id"]
        assert payment["bank_account_version"] == account["version"]
        assert get_invoice(invoice["id"])["status"] == "IN_PAYMENT_RUN"
