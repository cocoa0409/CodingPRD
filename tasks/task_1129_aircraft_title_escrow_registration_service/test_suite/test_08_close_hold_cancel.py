"""Close gates (documents, posture, search freshness, OCC), hold/resume
roundtrip, terminal lockdown, and close-time visibility (PRD §3.10, §2.7)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_trust_agreement,
    close_escrow_file,
    create_document,
    create_sent_document,
    create_trust_agreement,
    get_escrow_file,
    is_iso8601_timestamp,
    send_document,
    set_clock,
    setup_basic_file,
    setup_cleared_file,
    setup_funded_file,
    sign_document,
    submit_trust_agreement,
    validate_error,
    validate_success,
)

OFFICER = TEST_USERS["officer_headers"]


class TestCloseDocumentGate:
    def test_close_with_partially_signed_document_rejected(self, api):
        """PRD §3.10: "Every `ClosingDocument` on the file must be in
        `FULLY_SIGNED` — a file with zero documents trivially satisfies this; any
        document short of `FULLY_SIGNED` yields `ERR_DOCUMENTS_INCOMPLETE`."

        Design: Corner/errors/er_documents_incomplete_on_close
        """
        ctx = setup_funded_file()
        doc = create_sent_document(ctx["file"]["id"], "PURCHASE_AGREEMENT",
                                   [ctx["buyer"]["id"], ctx["seller"]["id"]])
        sign_document(doc["id"], ctx["buyer"]["id"])  # -> PARTIALLY_SIGNED

        version = get_escrow_file(ctx["file"]["id"])["version"]
        res = api.close_escrow_file(
            ctx["file"]["id"], {"expected_escrow_file_version": version}, OFFICER
        )
        validate_error(res, ApiErrorId.ERR_DOCUMENTS_INCOMPLETE, expected_status=409)
        after = get_escrow_file(ctx["file"]["id"])
        assert after["status"] == "FUNDED"
        assert after["closed_at"] is None


class TestClosePostureGate:
    def test_trust_expiry_blocks_close_with_posture_not_ready(self, api):
        """PRD §3.10: "The file's `posture` must be `READY`; otherwise the close
        is rejected with `ERR_POSTURE_NOT_READY`."
        PRD §3.7: "An `ACCEPTED` agreement whose `expiry_date` falls strictly
        behind the logical date is swept to `EXPIRED` by the clock, and the
        posture of every affected file is recomputed — a file relying on that
        trust becomes `TRUST_BLOCKED` at that moment."

        Design: Corner/errors/er_posture_not_ready_on_close
        """
        # Build aircraft/parties/trustee WITHOUT opening a file first: PRD §3.2
        # allows at most one non-terminal file per aircraft, so the trust must be
        # accepted before the single file is opened.
        from test_helpers import (
            complete_title_search,
            create_aircraft,
            create_buyer_seller,
            create_escrow_file,
            create_party,
            fund_file_to_due,
            order_title_search,
        )

        set_clock()  # 2026-06-01T00:00:00Z, inside the trust term below
        aircraft = create_aircraft(n_number="N610TP", serial_number="S-610")
        buyer, seller = create_buyer_seller()
        trustee = create_party("TRUSTEE", "Trustee Co", is_citizenship_verified=True)
        trust = create_trust_agreement(
            aircraft["id"], trustee["id"],
            effective_date="2026-01-01", expiry_date="2026-06-15",
        )
        submit_trust_agreement(trust["id"])
        accept_trust_agreement(trust["id"])

        escrow_file = create_escrow_file(
            aircraft["id"], buyer["id"], seller["id"],
            trustee_party_id=trustee["id"], requires_trust=True,
            purchase_price_cents=10_000_000,
        )
        search = order_title_search(escrow_file["id"])
        complete_title_search(search["id"], [])
        ready_file = get_escrow_file(escrow_file["id"])
        assert ready_file["posture"] == "READY"

        fund_file_to_due(escrow_file["id"], buyer["id"])
        assert get_escrow_file(escrow_file["id"])["status"] == "FUNDED"

        set_clock("2026-06-16T00:00:00Z")
        blocked = get_escrow_file(escrow_file["id"])
        assert blocked["posture"] == "TRUST_BLOCKED"

        res = api.close_escrow_file(
            escrow_file["id"],
            {"expected_escrow_file_version": blocked["version"]},
            OFFICER,
        )
        validate_error(res, ApiErrorId.ERR_POSTURE_NOT_READY, expected_status=409)
        assert get_escrow_file(escrow_file["id"])["status"] == "FUNDED"


class TestCloseSearchFreshnessBoundary:
    def test_close_at_exactly_thirty_days_succeeds(self, api):
        """PRD §3.10: "The file's latest `TitleSearch` must be in `COMPLETED` and
        still fresh, meaning the current logical date is on or before
        `effective_at` plus 30 days, inclusive; a stale or missing search is
        rejected with `ERR_SEARCH_STALE`."

        A search completed at 2026-06-01T00:00:00Z is fresh at exactly
        2026-07-01T00:00:00Z.

        Design: Difficulty/boundary_precision_check/b2_search_freshness_exact_second
        """
        ctx = setup_funded_file()  # search completed at 2026-06-01T00:00:00Z
        set_clock("2026-07-01T00:00:00Z")
        closed = close_escrow_file(ctx["file"]["id"])
        assert closed["status"] == "CLOSED"

    def test_close_one_second_past_thirty_days_rejected(self, api):
        """PRD §2.4: "A `TitleSearch` in `COMPLETED` whose `effective_at` lies
        strictly more than 30 days in the past transitions to `STALE`."
        PRD §3.10: "The file's latest `TitleSearch` must be in `COMPLETED` and
        still fresh, meaning the current logical date is on or before
        `effective_at` plus 30 days, inclusive; a stale or missing search is
        rejected with `ERR_SEARCH_STALE`."

        At 2026-07-01T00:00:01Z the search is strictly more than 30 days old.

        Design: Difficulty/boundary_precision_check/b2_search_freshness_exact_second
        """
        ctx = setup_funded_file()
        set_clock("2026-07-01T00:00:01Z")
        version = get_escrow_file(ctx["file"]["id"])["version"]
        res = api.close_escrow_file(
            ctx["file"]["id"], {"expected_escrow_file_version": version}, OFFICER
        )
        validate_error(res, ApiErrorId.ERR_SEARCH_STALE, expected_status=409)
        assert get_escrow_file(ctx["file"]["id"])["status"] == "FUNDED"


class TestCloseOcc:
    def test_close_with_stale_version_rejected_then_fresh_close_succeeds(self, api):
        """PRD §2.7: "In each case, the presented value is compared against the
        file's current `version`; if another writer has advanced the file since
        the client last read it, the request is rejected with `ERR_STALE_VERSION`
        (HTTP 412), and no mutation is applied."
        PRD §3.8: "Adding a document increments the file's `version` by 1."

        Design: Corner/cross_cutting_complexity_layers/x_occ_close_stale_version_412
        """
        ctx = setup_funded_file()
        file_id = ctx["file"]["id"]
        stale_version = get_escrow_file(file_id)["version"]

        doc = create_document(file_id, "CLOSING_STATEMENT", [ctx["buyer"]["id"]])

        stale_close = api.close_escrow_file(
            file_id, {"expected_escrow_file_version": stale_version}, OFFICER
        )
        validate_error(stale_close, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

        send_document(doc["id"])
        sign_document(doc["id"], ctx["buyer"]["id"])  # -> FULLY_SIGNED

        closed = close_escrow_file(file_id)
        assert closed["status"] == "CLOSED"


class TestCloseImmediateVisibility:
    def test_close_response_carries_closed_state_and_logical_instant(self, api):
        """PRD §3.10: "A successful close stamps `closed_at` to the logical
        instant, freezes the live money figures, transitions the file from
        `FUNDED` to `CLOSED`, and increments the file's `version` by 1."
        PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."

        The close response itself reports CLOSED with closed_at equal to the
        logical instant 2026-06-01T00:00:00Z, and a follow-up read agrees.

        Design: Corner/consistency_model/k_close_response_immediate
        """
        ctx = setup_funded_file()
        closed = close_escrow_file(ctx["file"]["id"])
        assert closed["status"] == "CLOSED"
        assert is_iso8601_timestamp(closed["closed_at"])
        assert closed["closed_at"][:19] == "2026-06-01T00:00:00"

        reread = get_escrow_file(ctx["file"]["id"])
        assert reread["status"] == "CLOSED"
        assert reread["closed_at"] == closed["closed_at"]


class TestHoldResume:
    def test_hold_stores_return_state_and_resume_restores_it(self, api):
        """PRD §3.10: "An `EscrowOfficer` places a file in `OPENED`,
        `SEARCH_ORDERED`, `SEARCH_COMPLETE`, `CLEARED`, or `FUNDED` on hold; the
        prior status is stored in `hold_return_state` and the file moves to
        `ON_HOLD`."
        PRD §3.10: "An `EscrowOfficer` resumes an `ON_HOLD` file, which restores
        the status stored in `hold_return_state` and clears that field back to
        null."

        Design: Corner/state_machines/s_hold_resume_roundtrip
        """
        ctx = setup_basic_file(clock=None)
        held = validate_success(api.hold_escrow_file(ctx["file"]["id"], OFFICER), 200)
        assert held["status"] == "ON_HOLD"
        assert held["hold_return_state"] == "OPENED"

        resumed = validate_success(api.resume_escrow_file(ctx["file"]["id"], OFFICER), 200)
        assert resumed["status"] == "OPENED"
        assert resumed["hold_return_state"] is None

    def test_resume_without_hold_rejected(self, api):
        """PRD §3.10: "An `EscrowOfficer` resumes an `ON_HOLD` file, which
        restores the status stored in `hold_return_state` and clears that field
        back to null."

        Resume is defined only from ON_HOLD; on an OPENED file the transition
        does not exist and the request is rejected as an invalid transition with
        no state change.

        Design: Corner/state_machines/s_resume_without_hold_returns_invalid_transition
        """
        ctx = setup_basic_file(clock=None)
        res = api.resume_escrow_file(ctx["file"]["id"], OFFICER)
        validate_error(res, ApiErrorId.ERR_INVALID_TRANSITION, expected_status=409)
        assert get_escrow_file(ctx["file"]["id"])["status"] == "OPENED"


class TestTerminalLockdown:
    def test_cancel_twice_rejected_already_terminal(self, api):
        """PRD §3.10: "Once a file reaches `CANCELLED` or `VERIFIED`, every
        mutation against it or anything scoped beneath it — including hold,
        resume, cancel, and close — is rejected with `ERR_ALREADY_TERMINAL`."

        Design: Corner/state_machines/s_cancel_twice_returns_already_terminal
        """
        ctx = setup_basic_file(clock=None)
        first = validate_success(api.cancel_escrow_file(ctx["file"]["id"], OFFICER), 200)
        assert first["status"] == "CANCELLED"
        res = api.cancel_escrow_file(ctx["file"]["id"], OFFICER)
        validate_error(res, ApiErrorId.ERR_ALREADY_TERMINAL, expected_status=409)
        assert get_escrow_file(ctx["file"]["id"])["status"] == "CANCELLED"
