"""Cross-entity default triggers and cascade behavior.

Covers PRD §3.6 (bankruptcy / insurance lapse / senior-lien default
cascades into HELOC DEFAULT), §2.8 (sticky DEFAULT, no auto-
reactivation), and §2.9 (default-trigger priority).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    assert_bankruptcy_event,
    assert_default_event,
    assert_insurance_event,
    assert_senior_lien_default_event,
    create_insurance_event_payload,
    get_heloc,
    make_borrower_headers,
    post_bankruptcy_event,
    post_insurance_event,
    post_senior_lien_default_event,
    setup_active_heloc,
    setup_borrower_with_two_helocs,
    setup_heloc_default_via_bankruptcy,
    setup_heloc_default_via_insurance_lapse,
    setup_heloc_default_via_senior_lien,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# §3.6 Bankruptcy: cascade DRAW/REPAY → DEFAULT with BANKRUPTCY trigger
# ===========================================================================
class TestBankruptcyCascade:

    def test_bankruptcy_event_flips_borrower_flag(
        self, api, servicer_headers,
    ):
        """PRD §3.6: "The borrower's bankruptcy_flag is flipped to
        true, the bankruptcy_filed_at timestamp is set to the server
        clock".
        """
        borrower, _, _, _ = setup_active_heloc()
        event_resp = api.create_bankruptcy_event(
            borrower["id"], servicer_headers,
        )
        event = validate_success(event_resp, 201)
        assert_bankruptcy_event(event)
        b2 = validate_success(
            api.get_borrower(borrower["id"], servicer_headers), 200,
        )
        assert b2["bankruptcy_flag"] is True
        assert b2["bankruptcy_filed_at"] is not None

    def test_bankruptcy_cascades_active_heloc_to_default(
        self, api, servicer_headers,
    ):
        """PRD §3.6: "every HELOC with that borrower_id whose status
        is in DRAW or REPAY is cascaded into DEFAULT with
        default_trigger of BANKRUPTCY and a DefaultEvent whose
        source_event_id is the id of the BankruptcyEvent just
        recorded."
        """
        borrower, _, _, heloc, event = (
            setup_heloc_default_via_bankruptcy()
        )
        assert heloc["status"] == "DEFAULT"
        assert heloc["default_trigger"] == "BANKRUPTCY"
        # Verify a DefaultEvent exists with source_event_id ==
        # BankruptcyEvent.id.
        de_resp = api.list_default_events(
            heloc["id"], servicer_headers,
        )
        events, _ = validate_paginated(de_resp)
        assert len(events) >= 1
        e = events[-1]
        assert_default_event(e)
        assert e["trigger"] == "BANKRUPTCY"
        assert e["source_event_id"] == event["id"]

    def test_bankruptcy_cascades_to_multiple_helocs(
        self, api, servicer_headers,
    ):
        """PRD §3.6: "every HELOC with that borrower_id whose status
        is in DRAW or REPAY is cascaded into DEFAULT".
        """
        borrower, _, _, heloc_a, _, _, heloc_b = (
            setup_borrower_with_two_helocs()
        )
        post_bankruptcy_event(borrower["id"])
        h_a = get_heloc(heloc_a["id"], servicer_headers)
        h_b = get_heloc(heloc_b["id"], servicer_headers)
        assert h_a["status"] == "DEFAULT"
        assert h_a["default_trigger"] == "BANKRUPTCY"
        assert h_b["status"] == "DEFAULT"
        assert h_b["default_trigger"] == "BANKRUPTCY"

    def test_bankruptcy_already_bankrupt_rejected(
        self, api, servicer_headers,
    ):
        """PRD §3.6: "A Servicer records a bankruptcy filing against a
        borrower whose bankruptcy_flag is currently false (attempts
        against a borrower already flagged bankrupt are rejected with
        ERR_ALREADY_BANKRUPT)."
        """
        borrower, _, _, _ = setup_active_heloc()
        # First event ok.
        validate_success(
            api.create_bankruptcy_event(
                borrower["id"], servicer_headers,
            ), 201,
        )
        # Second event rejected.
        resp = api.create_bankruptcy_event(
            borrower["id"], servicer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_ALREADY_BANKRUPT.value)


# ===========================================================================
# §3.6 Insurance: LAPSE / REINSTATE
# ===========================================================================
class TestInsuranceCascade:

    def test_lapse_event_flips_property_and_cascades_heloc(
        self, api, servicer_headers,
    ):
        """PRD §3.6: "A LAPSE flips the property's insurance_status to
        LAPSED, sets insurance_lapsed_at to the server clock, and
        cascades every HELOC on that property whose status is in
        DRAW or REPAY into DEFAULT with default_trigger of
        INSURANCE_LAPSE and a DefaultEvent.source_event_id pointing
        at the InsuranceEvent."
        """
        _, prop, _, heloc, event = (
            setup_heloc_default_via_insurance_lapse()
        )
        assert event["event_type"] == "LAPSE"
        assert heloc["status"] == "DEFAULT"
        assert heloc["default_trigger"] == "INSURANCE_LAPSE"
        # Re-fetch property to assert property side-effects.
        p2 = validate_success(
            api.get_property(prop["id"], servicer_headers), 200,
        )
        assert p2["insurance_status"] == "LAPSED"
        assert p2["insurance_lapsed_at"] is not None
        # Verify DefaultEvent with source_event_id == InsuranceEvent.id.
        de_resp = api.list_default_events(
            heloc["id"], servicer_headers,
        )
        events, _ = validate_paginated(de_resp)
        last = events[-1]
        assert last["trigger"] == "INSURANCE_LAPSE"
        assert last["source_event_id"] == event["id"]

    def test_reinstate_clears_property_state_but_does_not_un_default_heloc(
        self, api, servicer_headers,
    ):
        """PRD §2.8: "If the same property's insurance is subsequently
        reinstated, the insurance_status returns to ACTIVE and
        insurance_lapsed_at is cleared to null, but any HELOC that was
        already cascaded to DEFAULT because of the lapse is not
        automatically reactivated: once a HELOC enters DEFAULT, that
        state is sticky regardless of the underlying trigger being
        subsequently cured."
        """
        _, prop, _, heloc, _ = setup_heloc_default_via_insurance_lapse()
        assert heloc["status"] == "DEFAULT"
        # Now REINSTATE.
        api.create_insurance_event(
            prop["id"],
            create_insurance_event_payload(event_type="REINSTATE"),
            servicer_headers,
        )
        p2 = validate_success(
            api.get_property(prop["id"], servicer_headers), 200,
        )
        assert p2["insurance_status"] == "ACTIVE"
        assert p2["insurance_lapsed_at"] is None
        # HELOC stays DEFAULT (sticky).
        h2 = get_heloc(heloc["id"], servicer_headers)
        assert h2["status"] == "DEFAULT"
        assert h2["default_trigger"] == "INSURANCE_LAPSE"

    def test_lapse_on_already_lapsed_property_rejected(
        self, api, servicer_headers,
    ):
        """PRD §3.6: "A LAPSE event is only valid when the property's
        insurance_status is ACTIVE; a REINSTATE event is only valid
        when insurance_status is LAPSED; either mismatch is rejected
        with ERR_INVALID_STATE."
        """
        _, prop, _, _, _ = setup_heloc_default_via_insurance_lapse()
        resp = api.create_insurance_event(
            prop["id"],
            create_insurance_event_payload(event_type="LAPSE"),
            servicer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_reinstate_on_active_property_rejected(
        self, api, servicer_headers,
    ):
        """PRD §3.6: "a REINSTATE event is only valid when
        insurance_status is LAPSED; either mismatch is rejected with
        ERR_INVALID_STATE."
        """
        _, prop, _, _ = setup_active_heloc()
        resp = api.create_insurance_event(
            prop["id"],
            create_insurance_event_payload(event_type="REINSTATE"),
            servicer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# §3.6 Senior-lien default
# ===========================================================================
class TestSeniorLienDefaultCascade:

    def test_senior_lien_default_flips_lien_and_cascades(
        self, api, servicer_headers,
    ):
        """PRD §3.6: "The senior lien's status flips to DEFAULTED, its
        defaulted_at is set, and every HELOC on the same property
        whose status is in DRAW or REPAY is cascaded into DEFAULT
        with default_trigger of SENIOR_LIEN_DEFAULT and
        DefaultEvent.source_event_id pointing at the
        senior-lien-default event."
        """
        _, _, sl, heloc, event = (
            setup_heloc_default_via_senior_lien()
        )
        sl2 = validate_success(
            api.get_senior_lien(sl["id"], servicer_headers), 200,
        )
        assert sl2["status"] == "DEFAULTED"
        assert sl2["defaulted_at"] is not None
        assert heloc["status"] == "DEFAULT"
        assert heloc["default_trigger"] == "SENIOR_LIEN_DEFAULT"
        de_resp = api.list_default_events(
            heloc["id"], servicer_headers,
        )
        events, _ = validate_paginated(de_resp)
        last = events[-1]
        assert last["trigger"] == "SENIOR_LIEN_DEFAULT"
        assert last["source_event_id"] == event["id"]

    def test_senior_lien_default_on_already_defaulted_rejected(
        self, api, servicer_headers,
    ):
        """PRD §3.6: "A Servicer records a senior-lien default against
        a senior lien whose status is CURRENT (any other state yields
        ERR_INVALID_STATE)."
        """
        _, _, sl, _, _ = setup_heloc_default_via_senior_lien()
        resp = api.create_senior_lien_default_event(
            sl["id"], servicer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# §3.6 / §2.8 Default also suppresses future Draw creation
# ===========================================================================
class TestDefaultIsSticky:

    def test_default_blocks_further_draws(self, api):
        """PRD §3.6: "Once a HELOC is in DEFAULT, no further Draw may
        be created against it — attempts return ERR_HELOC_DEFAULTED."
        """
        borrower, _, _, heloc, _ = setup_heloc_default_via_bankruptcy()
        resp = api.create_draw(
            heloc["id"], {"amount_cents": 50_000},
            make_borrower_headers(borrower["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_HELOC_DEFAULTED.value)


# ===========================================================================
# §3.6 DELINQUENCY_90 source_event_id is null
# ===========================================================================
class TestDelinquencySourceEventIdNull:

    def test_delinquency_90_default_event_has_null_source(
        self, api, platform_admin_headers,
    ):
        """PRD §3.6: "For a DefaultEvent produced by the delinquency
        sweep, the source_event_id is null because there is no source
        event to point at — the trigger is sweep-derived."
        """
        from test_helpers import setup_heloc_at_delinquency_days
        # Drive a HELOC to 90 days delinquency. Setup defaults to
        # draw_amount_cents=1_000_000, so the borrower must pay
        # minimum to avoid delinquency; we skip payment so each cycle
        # increments delinquency_days by 30.
        borrower, _, _, h = setup_heloc_at_delinquency_days(
            target_days=90,
        )
        assert h["status"] == "DEFAULT"
        assert h["default_trigger"] == "DELINQUENCY_90"
        de_resp = api.list_default_events(
            h["id"], platform_admin_headers,
        )
        events, _ = validate_paginated(de_resp)
        last = events[-1]
        assert last["trigger"] == "DELINQUENCY_90"
        assert last["source_event_id"] is None
