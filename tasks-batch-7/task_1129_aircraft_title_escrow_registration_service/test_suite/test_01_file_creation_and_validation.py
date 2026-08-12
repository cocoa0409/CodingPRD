"""Escrow file creation: required inputs, server defaults, initial state,
aircraft occupation interval, and the open/cancel compensating pair."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_aircraft,
    assert_escrow_file,
    assert_party,
    create_aircraft,
    create_buyer_seller,
    create_escrow_file,
    create_escrow_file_payload,
    create_party,
    get_escrow_file,
    setup_basic_file,
    validate_error,
    validate_paginated,
    validate_success,
)

OFFICER = TEST_USERS["officer_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


class TestFileCreationValidation:
    def test_create_file_missing_purchase_price_rejected(self, api, officer_headers):
        """PRD §3.2: "The commercial terms come in as `purchase_price_cents`
        (strictly positive), `annual_registration_fee_cents` (non-negative), a
        `proration_method` of `DAILY` or `MONTHLY`, and an `expected_close_date`
        in `YYYY-MM-DD` form."

        Design: Corner/entities/e_file_create_missing_required_returns_invalid_request
        """
        ctx_parties = create_buyer_seller()
        aircraft = create_aircraft(n_number="N112BB", serial_number="S-3")
        payload = create_escrow_file_payload(
            aircraft_id=aircraft["id"],
            buyer_party_id=ctx_parties[0]["id"],
            seller_party_id=ctx_parties[1]["id"],
        )
        del payload["purchase_price_cents"]
        res = api.create_escrow_file(payload, officer_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)
        data, meta = validate_paginated(api.list_escrow_files(officer_headers))
        assert meta["total_count"] == 0, "no EscrowFile may be persisted on a 400"

    def test_create_defaults_applied_when_optional_inputs_omitted(self, api, officer_headers):
        """PRD §3.1: "`is_international_registry` defaults to `false` when omitted
        and marks the airframe as eligible for Cape Town International Registry
        interests — a marker that later determines whether `IR_INTEREST` liens
        may be recorded against it."
        PRD §3.1: "The `is_citizenship_verified` flag defaults to `false` and is
        load-bearing only for trustees: a `TrustAgreement` cannot be submitted
        unless its trustee party's `is_citizenship_verified` is `true`."
        PRD §3.2: "The `requires_trust` flag defaults to `false` and must be set
        `true` when ownership will vest in an owner trustee — it gates the posture
        rule described in §2.9."

        Design: Corner/entities/e_create_defaults_applied
        """
        aircraft_res = api.create_aircraft(
            {
                "n_number": "N113CC",
                "serial_number": "S-4",
                "make_model": "Piper M350",
                "year": 2018,
            },
            officer_headers,
        )
        aircraft = validate_success(aircraft_res, 201)
        assert_aircraft(aircraft)
        assert aircraft["is_international_registry"] is False

        party_res = api.create_party(
            {"party_type": "BUYER", "legal_name": "Buyer Co"}, officer_headers
        )
        buyer = validate_success(party_res, 201)
        assert_party(buyer)
        assert buyer["is_citizenship_verified"] is False
        seller = validate_success(
            api.create_party({"party_type": "SELLER", "legal_name": "Seller Co"}, officer_headers),
            201,
        )

        file_res = api.create_escrow_file(
            create_escrow_file_payload(
                aircraft_id=aircraft["id"],
                buyer_party_id=buyer["id"],
                seller_party_id=seller["id"],
                purchase_price_cents=1_000_000,
            ),
            officer_headers,
        )
        escrow_file = validate_success(file_res, 201)
        assert_escrow_file(escrow_file)
        assert escrow_file["requires_trust"] is False
        assert escrow_file["posture"] == "READY"

    def test_initial_state_opened_ready_version_one(self, api, officer_headers):
        """PRD §3.2: "The new file starts in `OPENED`."
        PRD §2.5: "`version` (integer): starts at 1 and increments by exactly 1
        on every mutation of the resource."
        PRD §2.9: "The posture becomes `READY` only when neither condition holds."

        Design: Corner/state_machines/s_initial_state_opened_ready
        """
        ctx = setup_basic_file(clock=None)
        escrow_file = ctx["file"]
        assert_escrow_file(escrow_file)
        assert escrow_file["status"] == "OPENED"
        assert escrow_file["posture"] == "READY"
        assert escrow_file["version"] == 1


class TestAircraftOccupation:
    def test_second_file_on_occupied_aircraft_rejected(self, api, officer_headers):
        """PRD §3.2: "An aircraft may be the subject of at most one non-terminal
        file at a time. An attempt to open a file for an aircraft that already has
        another file whose status is not `CANCELLED` or `VERIFIED` is rejected
        with `ERR_AIRCRAFT_UNDER_CONTRACT`."

        Design: Difficulty/resource_temporal_overlap/t1_aircraft_escrow_occupation
        """
        ctx = setup_basic_file(clock=None)
        res = api.create_escrow_file(
            create_escrow_file_payload(
                aircraft_id=ctx["aircraft"]["id"],
                buyer_party_id=ctx["buyer"]["id"],
                seller_party_id=ctx["seller"]["id"],
                purchase_price_cents=11_000_000,
                proration_method="MONTHLY",
                expected_close_date="2026-07-31",
            ),
            officer_headers,
        )
        validate_error(res, ApiErrorId.ERR_AIRCRAFT_UNDER_CONTRACT, expected_status=409)

    def test_file_allowed_after_first_file_cancelled(self, api, officer_headers):
        """PRD §3.2: "An attempt to open a file for an aircraft that already has
        another file whose status is not `CANCELLED` or `VERIFIED` is rejected
        with `ERR_AIRCRAFT_UNDER_CONTRACT`."
        PRD §2.9: "Cancelling a file returns every `RECEIVED` deposit to
        `RETURNED`, voids every `PENDING_APPROVAL` or `APPROVED` disbursement,
        withdraws every `QUEUED` or `REJECTED` filing, voids every non-terminal
        lien release, returns any `RELEASE_PENDING` lien that no longer has an
        active release to `DISCOVERED`, and releases the aircraft for use by
        other files."

        Design: Difficulty/resource_temporal_overlap/t1_aircraft_escrow_occupation
        """
        ctx = setup_basic_file(clock=None)
        cancelled = validate_success(
            api.cancel_escrow_file(ctx["file"]["id"], officer_headers), 200
        )
        assert cancelled["status"] == "CANCELLED"
        res = api.create_escrow_file(
            create_escrow_file_payload(
                aircraft_id=ctx["aircraft"]["id"],
                buyer_party_id=ctx["buyer"]["id"],
                seller_party_id=ctx["seller"]["id"],
                purchase_price_cents=11_000_000,
                proration_method="MONTHLY",
                expected_close_date="2026-07-31",
            ),
            officer_headers,
        )
        reopened = validate_success(res, 201)
        assert reopened["status"] == "OPENED"


class TestCancelConservesAircraftAvailability:
    def test_open_then_cancel_returns_aircraft_to_available(self, api, officer_headers):
        """PRD §3.10: "An `EscrowOfficer` cancels a file in `OPENED`,
        `SEARCH_ORDERED`, `SEARCH_COMPLETE`, `CLEARED`, `FUNDED`, or `ON_HOLD`,
        moving it to `CANCELLED` and triggering the broad cascade described in §2.9."

        Design: Difficulty/compensating_invariant/i2_cancel_conserves_aircraft_availability
        """
        ctx = setup_basic_file(clock=None)
        cancelled = validate_success(
            api.cancel_escrow_file(ctx["file"]["id"], officer_headers), 200
        )
        assert cancelled["status"] == "CANCELLED"

    def test_reopen_after_cancel_succeeds(self, api, officer_headers):
        """PRD §2.9: "Cancelling a file returns every `RECEIVED` deposit to
        `RETURNED`, voids every `PENDING_APPROVAL` or `APPROVED` disbursement,
        withdraws every `QUEUED` or `REJECTED` filing, voids every non-terminal
        lien release, returns any `RELEASE_PENDING` lien that no longer has an
        active release to `DISCOVERED`, and releases the aircraft for use by
        other files."

        Design: Difficulty/compensating_invariant/i2_cancel_conserves_aircraft_availability
        """
        ctx = setup_basic_file(clock=None)
        validate_success(api.cancel_escrow_file(ctx["file"]["id"], officer_headers), 200)
        res = api.create_escrow_file(
            create_escrow_file_payload(
                aircraft_id=ctx["aircraft"]["id"],
                buyer_party_id=ctx["buyer"]["id"],
                seller_party_id=ctx["seller"]["id"],
                purchase_price_cents=9_500_000,
                proration_method="MONTHLY",
                expected_close_date="2026-08-31",
            ),
            officer_headers,
        )
        reopened = validate_success(res, 201)
        assert reopened["status"] == "OPENED"
        current = get_escrow_file(ctx["file"]["id"])
        assert current["status"] == "CANCELLED"
