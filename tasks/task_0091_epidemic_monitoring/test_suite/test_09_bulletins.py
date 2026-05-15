"""Bulletins and public disclosure — PRD §3.9."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock,
    api_client,
    assert_bulletin,
    create_bulletin_payload,
    iso_utc_midnight,
    validate_error,
    validate_success,
)


# ===========================================================================
# Draft creation — PRD §3.9
# ===========================================================================
class TestBulletinDraft:

    def test_create_draft_with_valid_channels(self, api, press_officer_headers):
        """PRD §3.9: "A PressOfficer drafts a daily Bulletin by
        submitting bulletin_date (midnight UTC) and a non-empty subset
        of channels drawn from WEBSITE, APP, and PRESS. ... status
        enters DRAFT and rumor_corrections initializes empty."

        Claim: a valid draft creation enters DRAFT and initializes
        rumor_corrections as an empty list.
        """
        payload = create_bulletin_payload(
            bulletin_date=iso_utc_midnight(
                datetime(2026, 1, 1, tzinfo=timezone.utc),
            ),
            channels=["WEBSITE", "APP"],
        )
        bulletin = validate_success(
            api.create_bulletin(payload, press_officer_headers), 201,
        )
        assert_bulletin(bulletin)
        assert bulletin["status"] == "DRAFT"
        assert bulletin["channels"] == ["WEBSITE", "APP"]
        assert bulletin["rumor_corrections"] == []

    def test_empty_channels_rejected(self, api, press_officer_headers):
        """PRD §3.9: "an empty list or a value outside that set is
        rejected with ERR_INVALID_CHANNELS."

        Claim: POST /epi/bulletins with channels=[] →
        ERR_INVALID_CHANNELS.
        """
        payload = create_bulletin_payload(
            bulletin_date=iso_utc_midnight(
                datetime(2026, 1, 2, tzinfo=timezone.utc),
            ),
            channels=[],
        )
        resp = api.create_bulletin(payload, press_officer_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_CHANNELS.value)

    def test_invalid_channel_value_rejected(self, api, press_officer_headers):
        """PRD §3.9: "an empty list or a value outside that set is
        rejected with ERR_INVALID_CHANNELS."

        Claim: a channel value outside {WEBSITE, APP, PRESS} →
        ERR_INVALID_CHANNELS.
        """
        payload = create_bulletin_payload(
            bulletin_date=iso_utc_midnight(
                datetime(2026, 1, 3, tzinfo=timezone.utc),
            ),
            channels=["EMAIL"],
        )
        resp = api.create_bulletin(payload, press_officer_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_CHANNELS.value)


# ===========================================================================
# Bulletin-date uniqueness — PRD §3.9
# ===========================================================================
class TestBulletinUniqueness:

    def test_duplicate_bulletin_date_rejected(self, api, press_officer_headers):
        """PRD §3.9: "Each bulletin_date is unique — a second draft for
        the same date is rejected with ERR_DUPLICATE_BULLETIN."

        Claim: second draft for the same bulletin_date →
        ERR_DUPLICATE_BULLETIN.
        """
        date = iso_utc_midnight(datetime(2026, 1, 4, tzinfo=timezone.utc))
        payload = create_bulletin_payload(
            bulletin_date=date, channels=["WEBSITE"],
        )
        validate_success(api.create_bulletin(payload, press_officer_headers), 201)
        # Second draft for same date.
        dup = api.create_bulletin(payload, press_officer_headers)
        validate_error(dup, ApiErrorId.ERR_DUPLICATE_BULLETIN.value)


# ===========================================================================
# Publish / Retract / Archive — PRD §3.9
# ===========================================================================
class TestPublishRetractArchive:

    def test_publish_then_retract_then_republish(self, api, press_officer_headers):
        """PRD §3.9: "Publishing the bulletin (DRAFT → PUBLISHED)
        re-snapshots total_new_cases and tier_summary at publish time,
        and requires that channels remains non-empty. A published
        bulletin may be retracted (PUBLISHED → RETRACTED) with an
        optional reason body field; if a reason is supplied, a
        rumor-correction stub is appended to rumor_corrections. A
        retracted bulletin may be republished (RETRACTED → PUBLISHED),
        again requiring non-empty channels."

        Claim: DRAFT → PUBLISHED → RETRACTED (with reason appending a
        rumor-correction stub) → PUBLISHED works as documented.
        """
        date = iso_utc_midnight(datetime(2026, 1, 5, tzinfo=timezone.utc))
        bulletin = validate_success(api.create_bulletin(
            create_bulletin_payload(bulletin_date=date, channels=["WEBSITE"]),
            press_officer_headers,
        ), 201)
        published = validate_success(api.publish_bulletin(
            bulletin["id"], press_officer_headers,
        ))
        assert published["status"] == "PUBLISHED"
        retracted = validate_success(api.retract_bulletin(
            bulletin["id"], press_officer_headers,
            payload={"reason": "Numbers revised — initial figure overcounted."},
        ))
        assert retracted["status"] == "RETRACTED"
        assert len(retracted["rumor_corrections"]) >= 1, (
            "PRD §3.9: 'if a reason is supplied, a rumor-correction stub "
            "is appended to rumor_corrections'"
        )
        republished = validate_success(api.publish_bulletin(
            bulletin["id"], press_officer_headers,
        ))
        assert republished["status"] == "PUBLISHED"

    def test_archive_before_delay_rejected(self, api, press_officer_headers):
        """PRD §3.9: "After the configured archive delay has elapsed
        since bulletin_date, the bulletin may be archived (PUBLISHED →
        ARCHIVED); archiving before the delay is rejected as an invalid
        state transition."

        Claim: archiving a freshly-published bulletin (without
        advancing the clock past the delay) is rejected with
        ERR_INVALID_STATE.
        """
        date = iso_utc_midnight(datetime.now(timezone.utc))
        bulletin = validate_success(api.create_bulletin(
            create_bulletin_payload(bulletin_date=date, channels=["WEBSITE"]),
            press_officer_headers,
        ), 201)
        validate_success(api.publish_bulletin(
            bulletin["id"], press_officer_headers,
        ))
        # Without advancing the clock past the archive delay, archive
        # must be rejected.
        resp = api.archive_bulletin(bulletin["id"], press_officer_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
