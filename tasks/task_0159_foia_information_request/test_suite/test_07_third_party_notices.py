"""Reverse-FOIA third-party notices: consent, object, expire, override — PRD §3.7."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_clock_by_days,
    advance_clock_by_seconds,
    assert_third_party_notice,
    close_search,
    consent_third_party_notice,
    create_responsive_record,
    create_third_party_notice,
    get_third_party_notice,
    make_third_party_headers,
    object_third_party_notice,
    object_third_party_payload,
    parse_iso,
    run_sweep,
    setup_request_in_search,
    setup_request_with_third_party_notice,
    unique_third_party_id,
    validate_error,
    validate_success,
)


# ===========================================================================
# Notice creation — PRD §3.7
# ===========================================================================
class TestThirdPartyNoticeCreate:

    def test_create_notice_copies_third_party_id_and_sets_pending(self, api):
        """PRD §3.7: "The notice is created with `status` of
        `PENDING_RESPONSE`; its `third_party_id` is copied from the
        linked record (a notice's `third_party_id` must equal the linked
        record's `third_party_id`)".

        Claim: a new notice carries the record's third_party_id and
        status=PENDING_RESPONSE; response_deadline is non-null.
        """
        _r, _req, rec, notice = setup_request_with_third_party_notice(
            third_party_id="tp_alpha_001",
        )
        assert_third_party_notice(notice)
        assert notice["status"] == "PENDING_RESPONSE"
        assert notice["third_party_id"] == "tp_alpha_001"
        assert notice["third_party_id"] == rec["third_party_id"]
        assert notice["response_deadline"] is not None


# ===========================================================================
# Consent — PRD §3.7
# ===========================================================================
class TestThirdPartyConsent:

    def test_consent_by_correct_third_party_transitions_to_consented(self, api):
        """PRD §3.7: "They may consent to release, transitioning the
        notice from `PENDING_RESPONSE` to `CONSENTED`."
        PRD §3.7: "For both consent and object actions, the calling
        `X-User-ID` must equal the notice's `third_party_id`, and the
        action must arrive strictly before the deadline".

        Claim: /consent by X-User-ID == notice.third_party_id transitions
        to CONSENTED.
        """
        tp_id = unique_third_party_id()
        _r, _req, _rec, notice = setup_request_with_third_party_notice(
            third_party_id=tp_id,
        )
        consented = consent_third_party_notice(notice["id"], tp_id)
        assert consented["status"] == "CONSENTED"

    def test_consent_by_wrong_third_party_rejected(self, api):
        """PRD §3.7: "the calling `X-User-ID` must equal the notice's
        `third_party_id`".

        Claim: /consent with X-User-ID != notice.third_party_id fails
        with ERR_FORBIDDEN.
        """
        tp_id = unique_third_party_id("tp-real")
        _r, _req, _rec, notice = setup_request_with_third_party_notice(
            third_party_id=tp_id,
        )
        resp = api.consent_third_party_notice(
            notice["id"], make_third_party_headers("tp-impostor"),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Object — PRD §3.7
# ===========================================================================
class TestThirdPartyObject:

    def test_object_with_grounds_transitions_to_objected(self, api):
        """PRD §3.7: "They may object, supplying non-empty
        `objection_grounds` and transitioning the notice from
        `PENDING_RESPONSE` to `OBJECTED`".

        Claim: /object with non-empty objection_grounds and a matching
        X-User-ID transitions to OBJECTED.
        """
        tp_id = unique_third_party_id()
        _r, _req, _rec, notice = setup_request_with_third_party_notice(
            third_party_id=tp_id,
        )
        objected = object_third_party_notice(
            notice["id"], tp_id, objection_grounds="trade secret",
        )
        assert objected["status"] == "OBJECTED"

    def test_object_with_empty_grounds_rejected(self, api):
        """PRD §3.7: "supplying non-empty `objection_grounds`".

        Claim: /object with objection_grounds='' fails with
        ERR_INVALID_INPUT.
        """
        tp_id = unique_third_party_id()
        _r, _req, _rec, notice = setup_request_with_third_party_notice(
            third_party_id=tp_id,
        )
        resp = api.object_third_party_notice(
            notice["id"], {"objection_grounds": ""},
            make_third_party_headers(tp_id),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_INPUT.value)

    def test_consent_after_consent_rejected_notice_already_closed(self, api):
        """PRD §3.7: "Symmetrically, a consent or object on a notice
        that is already in any terminal state (a race lost to the sweep,
        or any second-writer scenario) is rejected with
        `ERR_NOTICE_ALREADY_CLOSED` and HTTP 409."

        Claim: a second /consent on an already-CONSENTED notice fails
        with ERR_NOTICE_ALREADY_CLOSED.
        """
        tp_id = unique_third_party_id()
        _r, _req, _rec, notice = setup_request_with_third_party_notice(
            third_party_id=tp_id,
        )
        consent_third_party_notice(notice["id"], tp_id)
        resp = api.consent_third_party_notice(
            notice["id"], make_third_party_headers(tp_id),
        )
        validate_error(resp, ApiErrorId.ERR_NOTICE_ALREADY_CLOSED.value)


# ===========================================================================
# Expiration / sweep — PRD §3.7
# ===========================================================================
class TestThirdPartyExpire:

    def test_expired_after_clock_advance_past_deadline(self, api):
        """PRD §3.7: "Or they may simply let the deadline pass: when
        the logical clock advances to or past `response_deadline` and
        the sweep runs, a still-`PENDING_RESPONSE` notice is transitioned
        to `EXPIRED`".

        Claim: advancing the clock past response_deadline transitions
        the notice to EXPIRED via the auto-sweep.
        """
        tp_id = unique_third_party_id()
        _r, _req, _rec, notice = setup_request_with_third_party_notice(
            third_party_id=tp_id,
        )
        deadline_iso = notice["response_deadline"]
        # Advance clock to one second after the deadline.
        from test_helpers import add_seconds, advance_clock_to_iso
        target = add_seconds(deadline_iso, 60)
        advance_clock_to_iso(target)
        refreshed = get_third_party_notice(notice["id"])
        assert refreshed["status"] == "EXPIRED"


# ===========================================================================
# Override — PRD §3.7
# ===========================================================================
class TestThirdPartyOverride:

    def test_override_objected_after_upheld_appeal(self, api):
        """PRD §3.7: "Override from `OBJECTED` to `OVERRIDDEN` requires
        the upheld-against-third-party outcome specifically."

        Claim: an Appeal with appellant_role=THIRD_PARTY that is
        UPHELD against the third party allows the AppealAuthority to
        override an OBJECTED notice to OVERRIDDEN.

        PRD §3.9 requires the underlying request to be in DENIED,
        PARTIAL_RELEASE, or GLOMAR_ISSUED before a third-party appeal
        can be filed; so the lawful sequence here is: object the
        notice, claim B4 on the record (forcing redaction or
        withholding per PRD §3.7), patch disposition to WITHHELD_FULL,
        close-search, determine to DENIED, file the THIRD_PARTY
        appeal, accept-for-review with a distinct AppealAuthority,
        decide UPHELD, then override.
        """
        from test_helpers import (
            file_appeal,
            accept_appeal_for_review,
            decide_appeal,
            make_appeal_authority_headers,
            create_exemption_claim,
            patch_record_disposition,
            determine_request,
            OFFICER_SHARED_ID,
            APPEAL_AUTHORITY_SHARED_ID,
        )
        tp_id = unique_third_party_id("tp_override")
        requester, request, rec, notice = (
            setup_request_with_third_party_notice(third_party_id=tp_id)
        )
        # Third party objects.
        object_third_party_notice(
            notice["id"], tp_id, objection_grounds="trade secret",
        )
        # Walk the request to DENIED so a third-party appeal can be
        # filed (PRD §3.9).
        create_exemption_claim(
            record_id=rec["id"], exemption_code="B4",
            redaction_scope="FULL",
        )
        rec_after = patch_record_disposition(
            rec["id"], disposition="WITHHELD_FULL", version=rec["version"],
        )
        close_search(request["id"])
        determined = determine_request(request["id"])
        assert determined["status"] == "DENIED"
        # Now file the third-party appeal on the denied request.
        auth_h = make_appeal_authority_headers(APPEAL_AUTHORITY_SHARED_ID)
        appeal = file_appeal(
            request=request, appellant_id=tp_id,
            appellant_role="THIRD_PARTY",
        )
        accept_appeal_for_review(appeal["id"], auth_h)
        decide_appeal(
            appeal["id"], decision="UPHELD", appeal_authority_headers=auth_h,
        )
        # Now override the OBJECTED notice to OVERRIDDEN.
        resp = api.override_third_party_notice(notice["id"], auth_h)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "OVERRIDDEN"


# ===========================================================================
# close-search precondition — PRD §3.8
# ===========================================================================
class TestCloseSearchThirdPartyGate:

    def test_close_search_with_pending_third_party_notice_rejected(self, api):
        """PRD §3.8: "The precondition is that every responsive record
        marked with `contains_third_party_info` of true has an associated
        `ThirdPartyNotice` whose `status` is one of `CONSENTED`,
        `OBJECTED`, `EXPIRED`, or `OVERRIDDEN` ... When this precondition
        fails ... the close-search call is rejected with
        `ERR_MISSING_THIRD_PARTY_NOTICE` and HTTP 422".

        Claim: /close-search while a linked notice is still
        PENDING_RESPONSE fails with ERR_MISSING_THIRD_PARTY_NOTICE.
        """
        tp_id = unique_third_party_id()
        _r, request, _rec, _notice = (
            setup_request_with_third_party_notice(third_party_id=tp_id)
        )
        resp = api.close_search(
            request["id"], TEST_USERS["officer_headers"],
        )
        validate_error(
            resp, ApiErrorId.ERR_MISSING_THIRD_PARTY_NOTICE.value,
        )

    def test_close_search_after_third_party_consent_succeeds(self, api):
        """PRD §3.8: "every responsive record marked with
        `contains_third_party_info` of true has an associated
        `ThirdPartyNotice` whose `status` is one of `CONSENTED`,
        `OBJECTED`, `EXPIRED`, or `OVERRIDDEN`".

        Claim: after the third party consents, /close-search succeeds.
        """
        tp_id = unique_third_party_id()
        _r, request, _rec, notice = (
            setup_request_with_third_party_notice(third_party_id=tp_id)
        )
        consent_third_party_notice(notice["id"], tp_id)
        closed = close_search(request["id"])
        assert closed["status"] == "DETERMINATION_PENDING"
