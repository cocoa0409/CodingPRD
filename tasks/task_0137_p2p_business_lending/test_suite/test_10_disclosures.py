"""Disclosure lifecycle: draft emission, publish freeze, lock,
staleness.

PRD §3.7, §2.10, §2.11.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    advance_clock,
    assert_disclosure,
    create_compliance_officer,
    find_disclosure,
    get_disclosure,
    get_loan,
    make_compliance_officer_headers,
    publish_disclosure,
    setup_disclosure_in_draft,
    setup_loan_in_default,
    setup_open_listing,
    setup_originated_loan,
    setup_platform_with_officer,
    validate_error,
    validate_success,
)


# ===========================================================================
# Disclosure emission — PRD §3.7
# ===========================================================================
class TestDisclosureEmission:

    def test_listing_open_emits_listing_opened_disclosure(self, api):
        """PRD §3.7: "opening a listing emits LISTING_OPENED".

        Claim: an OPEN listing has an associated DRAFT LISTING_OPENED
        disclosure.
        """
        platform, officer, b, listing = setup_open_listing()
        d = find_disclosure(
            platform["id"], subject_type="LISTING",
            subject_id=listing["id"], kind="LISTING_OPENED",
            published=False,
        )
        assert d is not None
        assert d["published"] is False

    def test_disclosure_payload_is_dict(self, api):
        """PRD §3.7: "The payload is assembled at transition time as a
        by-value snapshot of the subject's then-current public-facing
        fields, and subsequent changes to the underlying entity do not
        mutate the disclosure."

        Claim: disclosure.payload is a dict (object snapshot).
        """
        platform, officer, b, listing = setup_open_listing()
        d = find_disclosure(
            platform["id"], subject_type="LISTING",
            subject_id=listing["id"], kind="LISTING_OPENED",
        )
        assert d is not None
        assert_disclosure(d)
        assert isinstance(d["payload"], dict) and d["payload"]


# ===========================================================================
# Publication — PRD §3.7
# ===========================================================================
class TestDisclosurePublication:

    def test_publish_by_platform_operator_rejected_as_segregation(
        self, api, platform_operator_headers,
    ):
        """PRD §3.7: "Publication is reserved for a ComplianceOfficer;
        a PlatformOperator attempting to publish receives
        ERR_SEGREGATION_VIOLATION."

        Claim: PlatformOperator -> publish -> ERR_SEGREGATION_VIOLATION.
        """
        platform, officer, b, listing = setup_open_listing()
        d = find_disclosure(
            platform["id"], subject_type="LISTING",
            subject_id=listing["id"], kind="LISTING_OPENED",
            published=False,
        )
        assert d is not None
        resp = api.publish_disclosure(
            platform["id"], d["id"], platform_operator_headers,
        )
        validate_error(resp, "ERR_SEGREGATION_VIOLATION")

    def test_publish_by_compliance_officer_freezes_disclosure(self, api):
        """PRD §3.7: "On a successful publish, published is set to true
        and published_on_day_index is set to the platform's current
        clock_day_index."

        Claim: after publish, published == true and
        published_on_day_index is the current clock.
        """
        platform, officer, b, listing = setup_open_listing()
        d = find_disclosure(
            platform["id"], subject_type="LISTING",
            subject_id=listing["id"], kind="LISTING_OPENED",
            published=False,
        )
        assert d is not None
        published = publish_disclosure(
            platform["id"], d["id"], officer["id"],
        )
        assert published["published"] is True
        assert published["published_on_day_index"] == 0


# ===========================================================================
# Lockdown — PRD §2.10, §3.7
# ===========================================================================
class TestDisclosureLock:

    def test_double_publish_returns_disclosure_locked(self, api):
        """PRD §2.10: "Two compliance officers racing to publish the
        same draft serialize first-writer-wins on the published flag;
        the loser receives ERR_DISCLOSURE_LOCKED."

        Claim: publishing an already-PUBLISHED disclosure ->
        ERR_DISCLOSURE_LOCKED.
        """
        platform, officer, b, listing = setup_open_listing()
        d = find_disclosure(
            platform["id"], subject_type="LISTING",
            subject_id=listing["id"], kind="LISTING_OPENED",
            published=False,
        )
        assert d is not None
        publish_disclosure(platform["id"], d["id"], officer["id"])
        # Second attempt by the same officer.
        resp = api.publish_disclosure(
            platform["id"], d["id"],
            make_compliance_officer_headers(officer["id"]),
        )
        validate_error(resp, "ERR_DISCLOSURE_LOCKED")


# ===========================================================================
# Staleness — PRD §3.7
# ===========================================================================
class TestDisclosureStale:

    def test_publish_stale_default_notice_after_charge_off(self, api):
        """PRD §3.7: "publish capability moves the disclosure DRAFT ->
        PUBLISHED only if payload is non-empty and the subject is still
        in the state that produced the draft — for example, a
        LISTING_FUNDED draft cannot be published if the listing has
        since moved to WITHDRAWN or EXPIRED. Either failure mode yields
        ERR_DISCLOSURE_STALE."

        Claim: a DRAFT DEFAULT_NOTICE disclosure for a loan that
        progressed to CHARGED_OFF before publish -> ERR_DISCLOSURE_STALE.
        """
        from test_helpers import (
            INSTALLMENT_GRACE_DAYS, INSTALLMENT_PERIOD_DAYS,
        )
        # 1. Reach DEFAULT — DEFAULT_NOTICE draft is emitted.
        (platform, officer, b, loan, default_disclosure) = (
            setup_disclosure_in_draft("DEFAULT_NOTICE")
        )
        assert default_disclosure["kind"] == "DEFAULT_NOTICE"
        # 2. Advance further to CHARGED_OFF — subject state has now
        #    changed from DEFAULT to CHARGED_OFF, so the DEFAULT_NOTICE
        #    is stale relative to its subject's current state.
        advance_clock(
            platform["id"],
            2 * INSTALLMENT_PERIOD_DAYS + INSTALLMENT_GRACE_DAYS + 1,
        )
        refreshed_loan = get_loan(platform["id"], loan["id"])
        assert refreshed_loan["status"] == "CHARGED_OFF"
        # 3. Publishing the now-stale DEFAULT_NOTICE must fail.
        resp = api.publish_disclosure(
            platform["id"], default_disclosure["id"],
            make_compliance_officer_headers(officer["id"]),
        )
        validate_error(resp, "ERR_DISCLOSURE_STALE")
