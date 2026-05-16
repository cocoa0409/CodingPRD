"""Concurrency and optimistic concurrency control (OCC).

PRD §2.6 (OCC via version), §3.12 (five concurrency scenarios).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    assert_exactly_one_succeeds,
    create_authorization_request,
    decide_authorization_payload,
    file_appeal_payload,
    iso_offset,
    make_provider_headers,
    occ_payload,
    patch_authorization_request_payload,
    re_get_authorization,
    run_race,
    schedule_peer_to_peer_payload,
    setup_denied_authorization,
    setup_reference_data,
    setup_under_review_authorization,
    submit_authorization,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


# ===========================================================================
# Optimistic concurrency on PATCH and state-change actions (PRD §2.6).
# ===========================================================================
class TestOptimisticConcurrency:
    """PRD §2.6: stale version → ERR_VERSION_MISMATCH."""

    def test_patch_with_stale_version_rejected(self, api):
        """PRD §2.6: "When the client includes version, the server
        compares it to the resource's current version; if they differ,
        the request is rejected with ERR_VERSION_MISMATCH and HTTP 409."

        Claim: PATCH on a DRAFT authorization with stale version
        returns ERR_VERSION_MISMATCH.
        """
        patient, provider, catalog_item = setup_reference_data()
        auth = create_authorization_request(
            patient=patient, provider=provider, catalog_item=catalog_item,
        )
        stale_version = auth["version"]
        # First PATCH mutates version to stale_version + 1.
        api.patch_authorization_request(
            auth["id"],
            patch_authorization_request_payload(
                clinical_justification="first revision",
                version=stale_version,
            ),
            make_provider_headers(provider["id"]),
        )
        # Second PATCH reuses the now-stale version.
        res = api.patch_authorization_request(
            auth["id"],
            patch_authorization_request_payload(
                clinical_justification="second revision",
                version=stale_version,
            ),
            make_provider_headers(provider["id"]),
        )
        validate_error(res, "ERR_VERSION_MISMATCH")

    def test_patch_without_version_skips_occ_check(self, api):
        """PRD §2.6: "When the client omits version, the server
        performs the mutation without an OCC check."

        Claim: PATCH with no version field still succeeds when the
        request is otherwise valid (DRAFT request, allowed field).
        """
        patient, provider, catalog_item = setup_reference_data()
        auth = create_authorization_request(
            patient=patient, provider=provider, catalog_item=catalog_item,
        )
        payload = patch_authorization_request_payload(
            clinical_justification="no version supplied",
        )
        # Make sure version is absent.
        payload.pop("version", None)
        res = api.patch_authorization_request(
            auth["id"], payload, make_provider_headers(provider["id"]),
        )
        validate_success(res, 200)


# ===========================================================================
# Concurrent decide on the same authorization (PRD §3.12)
# ===========================================================================
class TestConcurrentDecide:
    """PRD §3.12: two InitialReviewers race; first wins."""

    def test_two_decides_serialize_first_writer_wins(self, api):
        """PRD §3.12: "Two InitialReviewer operators attempt to decide
        the same authorization at the same time. The state machine
        guarantees that at most one transition out of UNDER_REVIEW
        succeeds; the loser, observing that the status has already
        advanced, receives ERR_INVALID_STATE with HTTP 409."

        Claim: two concurrent /decide calls produce exactly one 2xx
        and one 4xx; the failing one carries ERR_INVALID_STATE.
        """
        _, _, _, auth, _ = setup_under_review_authorization()
        payload_a = decide_authorization_payload(
            outcome="APPROVED", approved_units=1,
            version=auth["version"],
        )
        payload_b = decide_authorization_payload(
            outcome="DENIED", approved_units=0,
            denial_reason_code="NOT_MEDICALLY_NECESSARY",
            version=auth["version"],
        )
        results = run_race(
            lambda: api.decide_authorization_request(
                auth["id"], payload_a,
                TEST_USERS["initial_reviewer_headers"],
            ),
            lambda: api.decide_authorization_request(
                auth["id"], payload_b,
                TEST_USERS["initial_reviewer_headers_alt"],
            ),
        )
        outcome = assert_exactly_one_succeeds(*results)
        loser = outcome["failures"][0]
        # PRD names the loser's error_id explicitly; but the OCC path
        # could also fire (ERR_VERSION_MISMATCH). Accept either since
        # both are PRD-conforming serialization mechanisms.
        validate_error_is_one_of(
            loser, ["ERR_INVALID_STATE", "ERR_VERSION_MISMATCH"],
        )


# ===========================================================================
# Concurrent peer-to-peer scheduling on the same authorization.
# ===========================================================================
class TestConcurrentP2PScheduling:
    """PRD §3.12: capacity-1 over {SCHEDULED, COMPLETED} per
    authorization."""

    def test_two_p2p_schedules_serialize_first_writer_wins(self, api):
        """PRD §3.12: "Two providers attempt to schedule a peer-to-peer
        review for the same authorization simultaneously. The 'at most
        one in SCHEDULED or COMPLETED per authorization' invariant
        serializes them; the loser receives
        ERR_PEER_REVIEW_ALREADY_SCHEDULED with HTTP 409."

        Claim: two concurrent /peer-to-peer calls produce exactly one
        2xx and one 4xx with ERR_PEER_REVIEW_ALREADY_SCHEDULED.
        """
        _, provider, _, auth, _ = setup_under_review_authorization()
        # Slot A: 24h offset. Slot B: 48h offset (different reviewer ids).
        headers = make_provider_headers(provider["id"])
        results = run_race(
            lambda: api.schedule_peer_to_peer(
                auth["id"],
                schedule_peer_to_peer_payload(
                    scheduled_at=iso_offset(hours=24),
                    duration_minutes=30,
                    payer_reviewer_id="payer-rev-A",
                    version=auth["version"],
                ),
                headers,
            ),
            lambda: api.schedule_peer_to_peer(
                auth["id"],
                schedule_peer_to_peer_payload(
                    scheduled_at=iso_offset(hours=48),
                    duration_minutes=30,
                    payer_reviewer_id="payer-rev-B",
                    version=auth["version"],
                ),
                headers,
            ),
        )
        outcome = assert_exactly_one_succeeds(*results)
        loser = outcome["failures"][0]
        # PRD §3.12 names the loser's error_id as
        # ERR_PEER_REVIEW_ALREADY_SCHEDULED, but PRD §2.8 priority order
        # puts state-check (priority #5) before the capacity check; once
        # the first P2P succeeds, the auth's status advances from
        # UNDER_REVIEW to PEER_REVIEW so a serialized loser can also see
        # ERR_INVALID_STATE. ERR_VERSION_MISMATCH is the OCC race path.
        validate_error_is_one_of(
            loser, [
                "ERR_PEER_REVIEW_ALREADY_SCHEDULED",
                "ERR_VERSION_MISMATCH",
                "ERR_INVALID_STATE",
            ],
        )


# ===========================================================================
# Concurrent appeal filing at the same tier.
# ===========================================================================
class TestConcurrentAppealFiling:
    """PRD §3.12: at most one PENDING appeal per (auth, tier)."""

    def test_two_appeals_at_same_tier_serialize(self, api):
        """PRD §3.12: "Two providers attempt to file an appeal at the
        same tier on the same denied authorization concurrently. The
        'at most one PENDING appeal per (authorization, tier)'
        invariant serializes them; the loser receives
        ERR_APPEAL_ALREADY_FILED with HTTP 409."

        Claim: two concurrent /appeals calls produce exactly one 2xx
        and one 4xx with ERR_APPEAL_ALREADY_FILED.
        """
        _, provider, _, auth = setup_denied_authorization()
        headers = make_provider_headers(provider["id"])
        results = run_race(
            lambda: api.file_appeal(
                auth["id"], file_appeal_payload(reason="first attempt"),
                headers,
            ),
            lambda: api.file_appeal(
                auth["id"], file_appeal_payload(reason="second attempt"),
                headers,
            ),
        )
        outcome = assert_exactly_one_succeeds(*results)
        loser = outcome["failures"][0]
        validate_error(loser, "ERR_APPEAL_ALREADY_FILED")
