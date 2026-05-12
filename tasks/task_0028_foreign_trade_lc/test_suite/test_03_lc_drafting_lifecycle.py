"""Letter of Credit drafting and lifecycle (PRD §3.2 / §3.3)."""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    advise_payload,
    assert_letter_of_credit,
    cancel_lc_payload,
    create_applicant,
    create_bank,
    create_beneficiary,
    create_lc_payload,
    find_swift_message_of_type,
    get_clock,
    get_lc,
    iso_z,
    issue_lc,
    parse_iso,
    setup_active_lc,
    setup_party_bundle,
    submit_lc,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# §3.2 — Drafting and submit preconditions
# ===========================================================================
class TestLcDraftCreation:

    def test_draft_lc_starts_in_draft_with_amendment_none(self, api):
        """PRD §3.2: 'A freshly drafted LC sits in lifecycle_status DRAFT
        with amendment_consent_status NONE and confirmation_status
        NOT_REQUIRED.'"""
        bundle = setup_party_bundle()
        now = parse_iso(get_clock()["now"])
        payload = create_lc_payload(
            applicant_id=bundle["applicant"]["id"],
            beneficiary_id=bundle["beneficiary"]["id"],
            issuing_bank_id=bundle["issuing_bank"]["id"],
            advising_bank_id=bundle["advising_bank"]["id"],
            latest_shipment_date=iso_z(now + timedelta(days=30)),
            expiry_date=iso_z(now + timedelta(days=90)),
        )
        res = api.create_lc(payload, bundle["applicant_headers"])
        lc = validate_success(res, expected_status=201)
        assert_letter_of_credit(lc)
        assert lc["lifecycle_status"] == "DRAFT"
        assert lc["amendment_consent_status"] == "NONE"
        assert lc["confirmation_status"] == "NOT_REQUIRED"

    def test_draft_without_required_documents_minimum_rejected(self, api):
        """PRD §3.2: 'a draft must include both COMMERCIAL_INVOICE and
        BILL_OF_LADING at minimum, otherwise submission is rejected
        with ERR_INVALID_REQUEST.'

        We trigger the rejection at submit time; the create endpoint
        may also reject it, but submit is the unambiguous PRD-pinned
        rejection point.
        """
        bundle = setup_party_bundle()
        now = parse_iso(get_clock()["now"])
        payload = create_lc_payload(
            applicant_id=bundle["applicant"]["id"],
            beneficiary_id=bundle["beneficiary"]["id"],
            issuing_bank_id=bundle["issuing_bank"]["id"],
            advising_bank_id=bundle["advising_bank"]["id"],
            required_documents=["COMMERCIAL_INVOICE"],   # missing BILL_OF_LADING
            latest_shipment_date=iso_z(now + timedelta(days=30)),
            expiry_date=iso_z(now + timedelta(days=90)),
        )
        # Either create or submit must reject; we drive the path that
        # PRD pins. PRD §3.2 says submission enforces the bundle.
        res = api.create_lc(payload, bundle["applicant_headers"])
        # Some impls reject at create; either way the failure is
        # ERR_INVALID_REQUEST with the same human meaning. If the
        # create endpoint accepts, we follow up with submit.
        if res.status_code == 201:
            lc = validate_success(res, expected_status=201)
            sub = api.submit_lc(lc["id"], bundle["applicant_headers"])
            validate_error(sub, "ERR_INVALID_REQUEST")
        else:
            validate_error(res, "ERR_INVALID_REQUEST")


class TestSubmit:

    def test_submit_advances_lifecycle_to_under_review(self, api):
        """PRD §3.2: 'When the applicant is satisfied with the draft,
        submission advances lifecycle_status from DRAFT to UNDER_REVIEW.'"""
        bundle = setup_party_bundle()
        now = parse_iso(get_clock()["now"])
        payload = create_lc_payload(
            applicant_id=bundle["applicant"]["id"],
            beneficiary_id=bundle["beneficiary"]["id"],
            issuing_bank_id=bundle["issuing_bank"]["id"],
            advising_bank_id=bundle["advising_bank"]["id"],
            latest_shipment_date=iso_z(now + timedelta(days=30)),
            expiry_date=iso_z(now + timedelta(days=90)),
        )
        lc = validate_success(
            api.create_lc(payload, bundle["applicant_headers"]),
            expected_status=201,
        )
        res = api.submit_lc(lc["id"], bundle["applicant_headers"])
        after = validate_success(res)
        assert after["lifecycle_status"] == "UNDER_REVIEW"

    def test_submit_with_expiry_in_past_rejected(self, api):
        """PRD §3.2: 'expiry_date must be strictly later than the
        current server clock, otherwise ERR_EXPIRY_IN_PAST is returned'."""
        bundle = setup_party_bundle()
        now = parse_iso(get_clock()["now"])
        payload = create_lc_payload(
            applicant_id=bundle["applicant"]["id"],
            beneficiary_id=bundle["beneficiary"]["id"],
            issuing_bank_id=bundle["issuing_bank"]["id"],
            advising_bank_id=bundle["advising_bank"]["id"],
            latest_shipment_date=iso_z(now - timedelta(days=10)),
            expiry_date=iso_z(now - timedelta(days=5)),
        )
        # Create may accept; rejection happens at submit per PRD §3.2.
        cr = api.create_lc(payload, bundle["applicant_headers"])
        if cr.status_code == 201:
            lc = validate_success(cr, expected_status=201)
            res = api.submit_lc(lc["id"], bundle["applicant_headers"])
            validate_error(res, "ERR_EXPIRY_IN_PAST")
        else:
            validate_error(cr, "ERR_EXPIRY_IN_PAST")

    def test_submit_with_shipment_after_expiry_rejected(self, api):
        """PRD §3.2: 'latest_shipment_date must be on or before
        expiry_date, otherwise ERR_SHIPMENT_AFTER_EXPIRY is returned.'"""
        bundle = setup_party_bundle()
        now = parse_iso(get_clock()["now"])
        payload = create_lc_payload(
            applicant_id=bundle["applicant"]["id"],
            beneficiary_id=bundle["beneficiary"]["id"],
            issuing_bank_id=bundle["issuing_bank"]["id"],
            advising_bank_id=bundle["advising_bank"]["id"],
            latest_shipment_date=iso_z(now + timedelta(days=120)),
            expiry_date=iso_z(now + timedelta(days=60)),
        )
        cr = api.create_lc(payload, bundle["applicant_headers"])
        if cr.status_code == 201:
            lc = validate_success(cr, expected_status=201)
            res = api.submit_lc(lc["id"], bundle["applicant_headers"])
            validate_error(res, "ERR_SHIPMENT_AFTER_EXPIRY")
        else:
            validate_error(cr, "ERR_SHIPMENT_AFTER_EXPIRY")

    def test_submit_with_confirming_required_but_no_confirming_bank_rejected(self, api):
        """PRD §3.2: 'if confirmation_required is true the
        confirming_bank_id must be set ... — failing this raises
        ERR_CONFIRMING_BANK_REQUIRED'."""
        bundle = setup_party_bundle()
        now = parse_iso(get_clock()["now"])
        payload = create_lc_payload(
            applicant_id=bundle["applicant"]["id"],
            beneficiary_id=bundle["beneficiary"]["id"],
            issuing_bank_id=bundle["issuing_bank"]["id"],
            advising_bank_id=bundle["advising_bank"]["id"],
            confirmation_required=True,
            confirming_bank_id=None,    # explicitly missing
            latest_shipment_date=iso_z(now + timedelta(days=30)),
            expiry_date=iso_z(now + timedelta(days=90)),
        )
        cr = api.create_lc(payload, bundle["applicant_headers"])
        if cr.status_code == 201:
            lc = validate_success(cr, expected_status=201)
            res = api.submit_lc(lc["id"], bundle["applicant_headers"])
            validate_error(res, "ERR_CONFIRMING_BANK_REQUIRED")
        else:
            validate_error(cr, "ERR_CONFIRMING_BANK_REQUIRED")

    def test_submit_with_invalid_usance_tenor_rejected(self, api):
        """PRD §3.2: 'an optional usance_tenor_days (mandatory when
        lc_type is USANCE and required to be one of 30, 60, 90, 120, or
        180)'."""
        bundle = setup_party_bundle()
        now = parse_iso(get_clock()["now"])
        payload = create_lc_payload(
            applicant_id=bundle["applicant"]["id"],
            beneficiary_id=bundle["beneficiary"]["id"],
            issuing_bank_id=bundle["issuing_bank"]["id"],
            advising_bank_id=bundle["advising_bank"]["id"],
            lc_type="USANCE",
            usance_tenor_days=45,    # not in {30,60,90,120,180}
            latest_shipment_date=iso_z(now + timedelta(days=30)),
            expiry_date=iso_z(now + timedelta(days=90)),
        )
        cr = api.create_lc(payload, bundle["applicant_headers"])
        if cr.status_code == 201:
            lc = validate_success(cr, expected_status=201)
            res = api.submit_lc(lc["id"], bundle["applicant_headers"])
            validate_error(res, "ERR_INVALID_REQUEST")
        else:
            validate_error(cr, "ERR_INVALID_REQUEST")


# ===========================================================================
# §3.2 — Issue / re-issue idempotency
# ===========================================================================
class TestIssue:

    def test_issue_advances_to_issued_and_assigns_lc_number(self, api):
        """PRD §3.2: 'Issuing the LC advances it from UNDER_REVIEW to
        ISSUED, assigns the immutable lc_number (formatted
        LC-YYYY-NNNNNN and unique across the platform), and emits an
        MT700 SWIFT message.'"""
        bundle = setup_party_bundle()
        now = parse_iso(get_clock()["now"])
        payload = create_lc_payload(
            applicant_id=bundle["applicant"]["id"],
            beneficiary_id=bundle["beneficiary"]["id"],
            issuing_bank_id=bundle["issuing_bank"]["id"],
            advising_bank_id=bundle["advising_bank"]["id"],
            latest_shipment_date=iso_z(now + timedelta(days=30)),
            expiry_date=iso_z(now + timedelta(days=90)),
        )
        lc = validate_success(
            api.create_lc(payload, bundle["applicant_headers"]),
            expected_status=201,
        )
        submit_lc(lc["id"], bundle["applicant_headers"])
        res = api.issue_lc(lc["id"], bundle["issuing_bank_headers"])
        after = validate_success(res)
        assert after["lifecycle_status"] == "ISSUED"
        assert after["lc_number"], "PRD §3.2: 'assigns the immutable lc_number'"

    def test_reissue_idempotent_returns_existing_lc_number(self, api):
        """PRD §3.2: 'Issuance is idempotent: re-issuing an already-ISSUED
        LC returns the existing lc_number rather than creating a second
        one.'"""
        bundle = setup_party_bundle()
        now = parse_iso(get_clock()["now"])
        payload = create_lc_payload(
            applicant_id=bundle["applicant"]["id"],
            beneficiary_id=bundle["beneficiary"]["id"],
            issuing_bank_id=bundle["issuing_bank"]["id"],
            advising_bank_id=bundle["advising_bank"]["id"],
            latest_shipment_date=iso_z(now + timedelta(days=30)),
            expiry_date=iso_z(now + timedelta(days=90)),
        )
        lc = validate_success(
            api.create_lc(payload, bundle["applicant_headers"]),
            expected_status=201,
        )
        submit_lc(lc["id"], bundle["applicant_headers"])
        first = issue_lc(lc["id"], bundle["issuing_bank_headers"])
        second = api.issue_lc(lc["id"], bundle["issuing_bank_headers"])
        re = validate_success(second)
        assert re["lc_number"] == first["lc_number"], (
            "PRD §3.2: 're-issuing an already-ISSUED LC returns the "
            "existing lc_number rather than creating a second one'"
        )

    def test_issue_emits_mt700(self, api):
        """PRD §3.2: 'Issuing the LC ... emits an MT700 SWIFT message.'"""
        bundle = setup_party_bundle()
        now = parse_iso(get_clock()["now"])
        payload = create_lc_payload(
            applicant_id=bundle["applicant"]["id"],
            beneficiary_id=bundle["beneficiary"]["id"],
            issuing_bank_id=bundle["issuing_bank"]["id"],
            advising_bank_id=bundle["advising_bank"]["id"],
            latest_shipment_date=iso_z(now + timedelta(days=30)),
            expiry_date=iso_z(now + timedelta(days=90)),
        )
        lc = validate_success(
            api.create_lc(payload, bundle["applicant_headers"]),
            expected_status=201,
        )
        submit_lc(lc["id"], bundle["applicant_headers"])
        issue_lc(lc["id"], bundle["issuing_bank_headers"])
        res = api.list_swift_messages(lc["id"], bundle["issuing_bank_headers"])
        msgs, _meta = validate_paginated(res)
        mt700 = find_swift_message_of_type(msgs, "MT700")
        assert mt700 is not None, "PRD §3.2: MT700 must be emitted on issuance"


# ===========================================================================
# §3.3 — Advising and confirmation
# ===========================================================================
class TestAdvising:

    def test_advise_unswifted_lc_rejected(self, api):
        """PRD §3.3: 'The advising step is gated by a SWIFT-prerequisite
        check: an MT700 for the LC must already exist, otherwise the
        request is rejected with ERR_SWIFT_NOT_DELIVERED.'

        We construct the precondition by trying to advise an LC that
        has not yet been issued. Without an MT700 the advise call
        cannot succeed.
        """
        bundle = setup_party_bundle()
        now = parse_iso(get_clock()["now"])
        payload = create_lc_payload(
            applicant_id=bundle["applicant"]["id"],
            beneficiary_id=bundle["beneficiary"]["id"],
            issuing_bank_id=bundle["issuing_bank"]["id"],
            advising_bank_id=bundle["advising_bank"]["id"],
            latest_shipment_date=iso_z(now + timedelta(days=30)),
            expiry_date=iso_z(now + timedelta(days=90)),
        )
        lc = validate_success(
            api.create_lc(payload, bundle["applicant_headers"]),
            expected_status=201,
        )
        # Before issuance, the LC is in DRAFT/UNDER_REVIEW. Advise must
        # be rejected — the rule firing here is the absence of an MT700,
        # but PRD §2.11 prioritises state-transition legality before
        # SWIFT-prerequisite. Either rejection is faithful.
        # PRD §3.3 names ERR_SWIFT_NOT_DELIVERED for the SWIFT precondition;
        # PRD §1.2 (state machine) names ERR_INVALID_STATE_TRANSITION for
        # advise when LC is not in ISSUED. Accept either — PRD does not
        # pin which precondition fires first when both fail.
        from test_helpers import validate_error_is_one_of  # noqa: WPS433
        res = api.advise_lc(lc["id"], bundle["advising_bank_headers"])
        validate_error_is_one_of(
            res,
            ["ERR_INVALID_STATE_TRANSITION", "ERR_SWIFT_NOT_DELIVERED"],
        )

    def test_advise_after_issue_advances_to_advised(self, api):
        """PRD §3.3: 'The AdvisingBank named on the LC advances the
        lifecycle from ISSUED to ADVISED ...'."""
        bundle = setup_party_bundle()
        now = parse_iso(get_clock()["now"])
        payload = create_lc_payload(
            applicant_id=bundle["applicant"]["id"],
            beneficiary_id=bundle["beneficiary"]["id"],
            issuing_bank_id=bundle["issuing_bank"]["id"],
            advising_bank_id=bundle["advising_bank"]["id"],
            latest_shipment_date=iso_z(now + timedelta(days=30)),
            expiry_date=iso_z(now + timedelta(days=90)),
        )
        lc = validate_success(
            api.create_lc(payload, bundle["applicant_headers"]),
            expected_status=201,
        )
        submit_lc(lc["id"], bundle["applicant_headers"])
        issue_lc(lc["id"], bundle["issuing_bank_headers"])
        res = api.advise_lc(lc["id"], bundle["advising_bank_headers"])
        after = validate_success(res)
        # PRD §3.3: 'If confirmation_required is false, the system
        # automatically transitions the LC from ADVISED to ACTIVE'.
        assert after["lifecycle_status"] in {"ADVISED", "ACTIVE"}, (
            f"expected ADVISED or auto-ACTIVE, got {after['lifecycle_status']}"
        )

    def test_advise_with_downstream_emits_mt710(self, api):
        """PRD §3.3: 'optionally naming a downstream_advising_bank_bic
        when the advice is being routed onward to a third bank — in that
        case an MT710 SWIFT message is generated (idempotent on its
        (subject_type, subject_id, message_type) triplet).'"""
        bundle = setup_party_bundle()
        now = parse_iso(get_clock()["now"])
        payload = create_lc_payload(
            applicant_id=bundle["applicant"]["id"],
            beneficiary_id=bundle["beneficiary"]["id"],
            issuing_bank_id=bundle["issuing_bank"]["id"],
            advising_bank_id=bundle["advising_bank"]["id"],
            latest_shipment_date=iso_z(now + timedelta(days=30)),
            expiry_date=iso_z(now + timedelta(days=90)),
        )
        lc = validate_success(
            api.create_lc(payload, bundle["applicant_headers"]),
            expected_status=201,
        )
        submit_lc(lc["id"], bundle["applicant_headers"])
        issue_lc(lc["id"], bundle["issuing_bank_headers"])
        api.advise_lc(
            lc["id"], bundle["advising_bank_headers"],
            advise_payload(downstream_advising_bank_bic="BNPAFRPP"),
        )
        res = api.list_swift_messages(lc["id"], bundle["issuing_bank_headers"])
        msgs, _meta = validate_paginated(res)
        mt710 = find_swift_message_of_type(msgs, "MT710")
        assert mt710 is not None, (
            "PRD §3.3: MT710 must be emitted when downstream bank is named"
        )


class TestConfirmationFlow:

    def test_unconfirmed_lc_auto_active_after_advise(self, api):
        """PRD §3.3: 'If confirmation_required is false, the system
        automatically transitions the LC from ADVISED to ACTIVE because
        confirmation_status is NOT_REQUIRED.'"""
        lc, bundle = setup_active_lc(confirmation_required=False)
        assert lc["lifecycle_status"] == "ACTIVE"
        assert lc["confirmation_status"] == "NOT_REQUIRED"

    def test_confirmation_required_lc_stays_in_advised_until_confirm(self, api):
        """PRD §3.3: 'If confirmation_required is true, the LC remains
        in ADVISED until the named ConfirmingBank performs confirmation,
        which flips confirmation_status from PENDING to CONFIRMED; the
        system then automatically transitions lifecycle_status from
        ADVISED to ACTIVE.'"""
        bundle = setup_party_bundle(with_confirming=True)
        now = parse_iso(get_clock()["now"])
        payload = create_lc_payload(
            applicant_id=bundle["applicant"]["id"],
            beneficiary_id=bundle["beneficiary"]["id"],
            issuing_bank_id=bundle["issuing_bank"]["id"],
            advising_bank_id=bundle["advising_bank"]["id"],
            confirming_bank_id=bundle["confirming_bank"]["id"],
            confirmation_required=True,
            latest_shipment_date=iso_z(now + timedelta(days=30)),
            expiry_date=iso_z(now + timedelta(days=90)),
        )
        lc = validate_success(
            api.create_lc(payload, bundle["applicant_headers"]),
            expected_status=201,
        )
        submit_lc(lc["id"], bundle["applicant_headers"])
        issue_lc(lc["id"], bundle["issuing_bank_headers"])
        api.advise_lc(lc["id"], bundle["advising_bank_headers"])
        # While confirmation_status is PENDING, lifecycle stays ADVISED.
        snapshot = get_lc(lc["id"], bundle["applicant_headers"])
        assert snapshot["lifecycle_status"] == "ADVISED", (
            "PRD §3.3: 'the LC remains in ADVISED until the named "
            "ConfirmingBank performs confirmation'"
        )
        assert snapshot["confirmation_status"] == "PENDING"
        # Confirm.
        api.confirm_lc(lc["id"], bundle["confirming_bank_headers"])
        snapshot = get_lc(lc["id"], bundle["applicant_headers"])
        assert snapshot["confirmation_status"] == "CONFIRMED"
        assert snapshot["lifecycle_status"] == "ACTIVE", (
            "PRD §3.3: 'the system then automatically transitions "
            "lifecycle_status from ADVISED to ACTIVE'"
        )


# ===========================================================================
# §3.3 — Cancellation guards
# ===========================================================================
class TestCancellation:

    def test_cancel_unused_lc_succeeds(self, api):
        """PRD §3.3: 'Cancellation is available out of ISSUED, ADVISED,
        or ACTIVE, but only when the LC has truly seen no use.'"""
        lc, bundle = setup_active_lc()
        res = api.cancel_lc(
            lc["id"], cancel_lc_payload(cancelled_reason="test"),
            bundle["issuing_bank_headers"],
        )
        after = validate_success(res)
        assert after["lifecycle_status"] == "CANCELLED"
        assert after["cancelled_reason"] == "test", (
            "PRD §3.3: 'On success the LC moves to CANCELLED, the "
            "cancelled_reason is stored'"
        )

    def test_cancel_lc_with_drawings_rejected(self, api):
        """PRD §3.3: 'drawn_amount_minor_units must be 0, otherwise
        ERR_LC_HAS_DRAWINGS'."""
        from test_helpers import setup_paid_sight_settlement  # noqa: WPS433
        lc_after, bundle, _, _ = setup_paid_sight_settlement(
            amount_minor_units=10_000,
            drawing_amount_minor_units=10_000,
        )
        res = api.cancel_lc(
            lc_after["id"], cancel_lc_payload(),
            bundle["issuing_bank_headers"],
        )
        validate_error(res, "ERR_LC_HAS_DRAWINGS")

    def test_cancel_lc_with_open_presentation_rejected(self, api):
        """PRD §3.3: 'no Presentation may be in any of the non-terminal
        states SUBMITTED, UNDER_EXAMINATION, EXAMINED_CLEAN,
        EXAMINED_DISCREPANT, or ACCEPTED_BY_APPLICANT, otherwise
        ERR_LC_HAS_OPEN_PRESENTATIONS'."""
        from test_helpers import setup_examined_clean_presentation  # noqa: WPS433
        lc, bundle, _pres, _ex = setup_examined_clean_presentation(
            amount_minor_units=10_000,
            drawing_amount_minor_units=5_000,
        )
        res = api.cancel_lc(
            lc["id"], cancel_lc_payload(),
            bundle["issuing_bank_headers"],
        )
        validate_error(res, "ERR_LC_HAS_OPEN_PRESENTATIONS")
