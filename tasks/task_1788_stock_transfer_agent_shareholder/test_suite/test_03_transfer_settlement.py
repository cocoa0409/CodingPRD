"""Transfer settlement: the three-hop cascade, settlement gates (stopped
certificate, freeze window), terminal lockdown, optimistic concurrency on
creation, and immediate read-after-write visibility."""
from test_helpers import (
    ApiErrorId,
    create_account,
    create_freeze_window,
    create_issuer,
    get_account,
    get_certificate_for_account,
    get_issuer,
    get_position,
    get_transfer,
    list_transfers,
    make_shareholder_headers,
    make_supervisor_headers,
    report_lost,
    seed_position,
    settle_transfer,
    setup_approved_certificated_transfer,
    setup_approved_transfer,
    transfer_request_payload,
    validate_error,
    validate_success,
    make_examiner_headers,
)


class TestSettleCascade:
    def test_settle_cancels_certificate_and_debits_source(self, api):
        """PRD §3.3: "A successful settlement moves the request `APPROVED` →
        `SETTLED` and executes three cascades in order. First, a certificated
        source certificate moves `ISSUED` → `CANCELLED`. Second, the source
        position is debited — its `certificated_shares` for a certificated
        source, its `book_entry_shares` for a DRS source"

        Design: Difficulty/transitive_cascade/settle_cascade_cert_position_issuer
        """
        ctx = setup_approved_certificated_transfer(shares_outstanding=300,
                                                   book_entry_shares=300,
                                                   cert_shares=200)
        settle_transfer(ctx["transfer"]["id"])

        cert = get_certificate_for_account(ctx["acct_a"]["id"],
                                           ctx["certificate"]["id"])
        assert cert["status"] == "CANCELLED", "hop1 cancels the source certificate"
        source = get_position(ctx["acct_a"]["id"], ctx["issuer"]["id"])
        assert source["book_entry_shares"] == 100
        assert source["certificated_shares"] == 0, (
            "hop2 debits the certificated leg (was 200)"
        )

    def test_settle_credits_transferee_and_recomputes_issuer(self, api):
        """PRD §3.3: "the transferee's position in the same issuer is credited
        in book-entry form, the position being created on the spot when the
        transferee does not already hold one, with the credited amount landing
        in its `book_entry_shares`. Third, the issuer's
        `total_book_entry_shares` and `total_certificated_shares` are
        recomputed across all positions."
        PRD §3.3: "the request's `settled_at` is stamped from the logical
        clock"

        Design: Difficulty/transitive_cascade/settle_cascade_cert_position_issuer
        """
        ctx = setup_approved_certificated_transfer(shares_outstanding=300,
                                                   book_entry_shares=300,
                                                   cert_shares=200)
        settled = settle_transfer(ctx["transfer"]["id"])
        assert settled["status"] == "SETTLED"
        assert settled["settled_at"], "settled_at is stamped at settlement"

        transferee = get_position(ctx["acct_b"]["id"], ctx["issuer"]["id"])
        assert transferee["book_entry_shares"] == 200, (
            "the transferee position is created on the spot, credited in "
            "book-entry form"
        )
        assert transferee["certificated_shares"] == 0

        issuer = get_issuer(ctx["issuer"]["id"])
        assert issuer["total_book_entry_shares"] == 300  # 100 + 200
        assert issuer["total_certificated_shares"] == 0
        assert issuer["shares_outstanding"] == 300, "share count is conserved"


class TestSettleGates:
    def test_settle_blocked_by_stopped_certificate(self, api):
        """PRD §3.3: "If the request names a `source_certificate_id`, that
        certificate must still be `ISSUED`; if a stop-transfer order has since
        been placed on it, settlement is refused with
        `ERR_CERTIFICATE_STOPPED`."

        Design: Difficulty/cross_entity_state_dependency/settle_blocked_by_stopped_certificate
        """
        ctx = setup_approved_certificated_transfer(shares_outstanding=300,
                                                   book_entry_shares=300,
                                                   cert_shares=100)
        report_lost(ctx["certificate"]["id"], "2026-08-10T00:00:00Z", "exam_2")

        resp = api.settle_transfer_request(ctx["transfer"]["id"],
                                           make_supervisor_headers("sup_1"))
        validate_error(resp, ApiErrorId.ERR_CERTIFICATE_STOPPED)
        assert get_transfer(ctx["transfer"]["id"])["status"] == "APPROVED", (
            "no rollback, no settlement"
        )

    def test_stopped_certificate_preserves_position(self, api):
        """PRD §3.4: "Reporting places the stop-transfer order: the certificate
        moves `ISSUED` → `LOST_REPORTED`, its `lost_reported_at` is stamped
        from the logical clock, and the stop remains open-ended until
        resolved."
        PRD §3.3: "if a stop-transfer order has since been placed on it,
        settlement is refused with `ERR_CERTIFICATE_STOPPED`."

        Design: Difficulty/cross_entity_state_dependency/settle_blocked_by_stopped_certificate
        """
        ctx = setup_approved_certificated_transfer(shares_outstanding=300,
                                                   book_entry_shares=300,
                                                   cert_shares=100)
        report_lost(ctx["certificate"]["id"], "2026-08-10T00:00:00Z", "exam_2")
        api.settle_transfer_request(ctx["transfer"]["id"],
                                    make_supervisor_headers("sup_1"))

        cert = get_certificate_for_account(ctx["acct_a"]["id"],
                                           ctx["certificate"]["id"])
        assert cert["status"] == "LOST_REPORTED"
        assert cert["lost_reported_at"], "the stop-transfer order is in force"
        source = get_position(ctx["acct_a"]["id"], ctx["issuer"]["id"])
        assert source["certificated_shares"] == 100, (
            "the refused settlement moves no shares"
        )

    def test_settle_inside_freeze_window_rejected(self, api):
        """PRD §3.3: "The logical clock must not fall inside any of the
        issuer's freeze windows: any window in `SCHEDULED` or `ACTIVE` status
        whose `start_date` and `end_date` bracket the current instant — both
        boundary days included — blocks settlement with
        `ERR_TRANSFER_FREEZE_CONFLICT`."

        Design: Corner/validations/transfer_settle_inside_freeze_window_rejected
        """
        ctx = setup_approved_transfer(share_quantity=10)
        create_freeze_window(ctx["issuer"], "2026-08-01T00:00:00Z",
                             "2026-08-31T00:00:00Z", "annual meeting")

        # The clock has never been set, so it reads the startup default
        # 2026-08-01T00:00:00Z — the window's first (boundary) day.
        resp = api.settle_transfer_request(ctx["transfer"]["id"],
                                           make_supervisor_headers("sup_1"))
        validate_error(resp, ApiErrorId.ERR_TRANSFER_FREEZE_CONFLICT)
        assert get_transfer(ctx["transfer"]["id"])["status"] == "APPROVED"
        source = get_position(ctx["acct_a"]["id"], ctx["issuer"]["id"])
        assert source["book_entry_shares"] == 100


class TestSettledLockdown:
    def test_settled_transfer_cannot_be_cancelled(self, api):
        """PRD §3.3: "the transferor may cancel it from `UNDER_REVIEW` or
        `DEFICIENT`, moving it to the terminal `CANCELLED` state"
        PRD §2.8: "any other transition attempted from an impermissible state
        fails with the generic `ERR_INVALID_STATE`."

        Design: Corner/state_machines/settled_transfer_cannot_be_cancelled
        """
        ctx = setup_approved_transfer(share_quantity=40)
        settle_transfer(ctx["transfer"]["id"])

        resp = api.cancel_transfer_request(
            ctx["transfer"]["id"],
            make_shareholder_headers(ctx["acct_a"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_transfer(ctx["transfer"]["id"])["status"] == "SETTLED"
        transferee = get_position(ctx["acct_b"]["id"], ctx["issuer"]["id"])
        assert transferee["book_entry_shares"] == 40, (
            "no compensation fired for the refused cancel"
        )


class TestTransferCreationGuards:
    def test_zero_quantity_transfer_rejected(self, api):
        """PRD §3.3: "A `share_quantity` below one is refused with
        `ERR_ZERO_SHARE_QUANTITY`."
        PRD §3.3: "Opening the request increments the transferor account's
        `pending_transfer_count` by one"

        Design: Corner/validations/zero_quantity_transfer_rejected
        """
        issuer = create_issuer(name="Sigma Zero", cusip="000000042",
                               ticker="SZER")
        acct_a = create_account(holder_name="Zero Zach", postal_code="74120",
                                tax_id="412-12-1212")
        acct_b = create_account(holder_name="Zero Zara", postal_code="74121",
                                tax_id="422-12-1212")
        seed_position(acct_a["id"], issuer["id"], 100)

        resp = api.create_transfer_request(
            transfer_request_payload(acct_a["id"], acct_b["id"], issuer["id"], 0,
                                     expected_account_version=acct_a["version"]),
            make_examiner_headers("exam_1"),
        )
        validate_error(resp, ApiErrorId.ERR_ZERO_SHARE_QUANTITY)
        assert get_account(acct_a["id"])["pending_transfer_count"] == 0

    def test_occ_stale_account_version_transfer_create(self, api):
        """PRD §2.7: "Creating a transfer request requires the client to supply
        `expected_account_version`, carrying the `version` of the transferor's
        `ShareholderAccount` as the client last observed it. If the account's
        current `version` no longer matches — for example because another
        transfer was opened against the same account, or an earlier transfer
        reached a terminal state, in each case moving `pending_transfer_count`
        and advancing the account's `version` — the creation is rejected with
        `ERR_STALE_ACCOUNT_VERSION` (HTTP 412). The client must re-read the
        account and resubmit with the current version."

        Design: Corner/cross_cutting_layers/occ_stale_account_version_transfer_create
        """
        issuer = create_issuer(name="Eta Occ", cusip="000000050", ticker="EOCC")
        acct_a = create_account(holder_name="Occ Otto", postal_code="74134",
                                tax_id="552-12-1212", tin_status="CERTIFIED")
        acct_b = create_account(holder_name="Occ Olga", postal_code="74135",
                                tax_id="562-12-1212", tin_status="CERTIFIED")
        seed_position(acct_a["id"], issuer["id"], 100)
        observed_version = acct_a["version"]

        first = validate_success(api.create_transfer_request(
            transfer_request_payload(acct_a["id"], acct_b["id"], issuer["id"],
                                     10, observed_version),
            make_examiner_headers("exam_1")), 201)
        assert first["status"] == "UNDER_REVIEW"

        # The first create advanced the account version 1 -> 2.
        resp = api.create_transfer_request(
            transfer_request_payload(acct_a["id"], acct_b["id"], issuer["id"],
                                     5, observed_version),
            make_examiner_headers("exam_1"),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_ACCOUNT_VERSION)
        assert len(list_transfers(from_account_id=acct_a["id"])) == 1, (
            "the stale creation persists no transfer row"
        )

        # The documented recovery: re-read, resubmit with the current version.
        current = get_account(acct_a["id"])["version"]
        second = validate_success(api.create_transfer_request(
            transfer_request_payload(acct_a["id"], acct_b["id"], issuer["id"],
                                     5, current),
            make_examiner_headers("exam_1")), 201)
        assert second["status"] == "UNDER_REVIEW"
        assert get_account(acct_a["id"])["version"] == 3, (
            "two successful creates advanced the account version 1 -> 3"
        )


class TestImmediateConsistency:
    def test_settle_read_after_write_immediate(self, api):
        """PRD §3.3: "A successful settlement moves the request `APPROVED` →
        `SETTLED` and executes three cascades in order."
        PRD §3.3: "the source position is debited — its `certificated_shares`
        for a certificated source, its `book_entry_shares` for a DRS source —
        and the transferee's position in the same issuer is credited in
        book-entry form"
        PRD §3.3: "the request's `settled_at` is stamped from the logical
        clock"
        PRD §2.4: "Before the clock has ever been set, its value is exactly
        `2026-08-01T00:00:00Z`"

        Design: Corner/consistency_model/settle_read_after_write_immediate
        """
        ctx = setup_approved_transfer(share_quantity=25)
        settle_transfer(ctx["transfer"]["id"])

        # The very next reads already show the settled balances.
        transferee = get_position(ctx["acct_b"]["id"], ctx["issuer"]["id"])
        assert transferee["book_entry_shares"] == 25
        source = get_position(ctx["acct_a"]["id"], ctx["issuer"]["id"])
        assert source["book_entry_shares"] == 75
        settled = get_transfer(ctx["transfer"]["id"])
        assert settled["status"] == "SETTLED"
        assert settled["settled_at"] == "2026-08-01T00:00:00.000Z"
