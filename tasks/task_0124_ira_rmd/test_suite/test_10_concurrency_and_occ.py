"""Concurrency: race conditions and optimistic concurrency control.

Coverage targets (PRD §2.5, §3.3, §3.5, §3.7):
- Contribution-cap race on the same Account: first wins, second
  observes cap (ERR_CONTRIBUTION_CAP_EXCEEDED).
- Approve vs reject race on the same PENDING ConversionRequest:
  exactly one transitions; loser observes ERR_INVALID_STATE.
- Two simultaneous RMD-coded distributions for the same Account in
  the same tax_year: one wins, other gets ERR_RMD_ALREADY_TAKEN.
- OCC: stale version on PATCH /participants -> ERR_VERSION_CONFLICT.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_year,
    assert_exactly_one_succeeds,
    assert_race_outcome,
    create_contribution_payload,
    create_distribution_payload,
    create_participant_born,
    open_account,
    post_contribution,
    run_race,
    setup_owner_rmd_eligible,
    setup_pending_conversion,
    update_participant_payload,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


# ===========================================================================
# Contribution cap race — PRD §3.3
# ===========================================================================
class TestContributionCapRace:

    def test_concurrent_contributions_exceeding_cap_serialize(
        self, api, custodian_headers,
    ):
        """PRD §3.3: "When two contributions arrive simultaneously for
        the same account and the second would push the year-to-date
        total above the applicable cap, the two requests are
        serialized on the account's id. Whichever order persists, the
        first writer's ContributionEvent is accepted in POSTED status,
        and the second writer receives ERR_CONTRIBUTION_CAP_EXCEEDED."

        Claim: two concurrent 500_000 contributions to a 700_000-cap
        account (empty ytd) -> exactly one POSTED, the other
        ERR_CONTRIBUTION_CAP_EXCEEDED.
        """
        p = create_participant_born(1990)  # under-50, cap = 700_000
        a = open_account(p["id"])
        payload = create_contribution_payload(
            amount_cents=500_000, contribution_type="REGULAR",
        )
        results = run_race(
            lambda: api.create_contribution(a["id"], payload,
                                            custodian_headers),
            lambda: api.create_contribution(a["id"], payload,
                                            custodian_headers),
        )
        outcome = assert_race_outcome(results, 1, 1)
        loser = outcome["failures"][0]
        validate_error(loser,
                       ApiErrorId.ERR_CONTRIBUTION_CAP_EXCEEDED.value)


# ===========================================================================
# Conversion request approve/reject race — PRD §3.7
# ===========================================================================
class TestConversionRace:

    def test_approve_reject_race_exactly_one_succeeds(
        self, api, custodian_headers,
    ):
        """PRD §3.7: "When approve and reject fire simultaneously
        against the same pending conversion, exactly one wins the race
        on the request's status and the loser is rejected with
        ERR_INVALID_STATE."

        Claim: concurrent approve + reject -> exactly one succeeds,
        loser gets ERR_INVALID_STATE.
        """
        p, trad, roth, cr = setup_pending_conversion()
        results = run_race(
            lambda: api.approve_conversion_request(cr["id"],
                                                   custodian_headers),
            lambda: api.reject_conversion_request(cr["id"],
                                                  custodian_headers),
        )
        outcome = assert_race_outcome(results, 1, 1)
        loser = outcome["failures"][0]
        validate_error(loser, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# RMD already-taken race — PRD §3.5
# ===========================================================================
class TestRmdRace:

    def test_two_simultaneous_rmds_one_wins(self, api,
                                            custodian_headers):
        """PRD §3.5: "At most one RMD-coded distribution may exist per
        account per tax year; a second simultaneous RMD attempt on the
        same account in the same tax year is rejected with
        ERR_RMD_ALREADY_TAKEN (serialization is on the tuple of
        account id, tax_year, and RMD reason; first writer wins)."

        Claim: two simultaneous RMD distributions on the same Account
        in the same tax_year -> exactly one wins, the other gets
        ERR_RMD_ALREADY_TAKEN.
        """
        p, a = setup_owner_rmd_eligible(
            target_age_on_dec31=73,
            prior_year_end_balance_cents=10_000_000,
        )
        payload = create_distribution_payload(
            gross_amount_cents=377_358, distribution_reason="RMD",
        )
        results = run_race(
            lambda: api.create_distribution(a["id"], payload,
                                            custodian_headers),
            lambda: api.create_distribution(a["id"], payload,
                                            custodian_headers),
        )
        outcome = assert_race_outcome(results, 1, 1)
        loser = outcome["failures"][0]
        validate_error(loser, ApiErrorId.ERR_RMD_ALREADY_TAKEN.value)


# ===========================================================================
# OCC version conflict — PRD §2.5
# ===========================================================================
class TestVersionConflict:

    def test_concurrent_patches_one_wins_with_version_conflict(
        self, api, custodian_headers,
    ):
        """PRD §2.5: "If version is supplied but does not match the
        current value (because another writer has advanced it), the
        request is rejected with ERR_VERSION_CONFLICT."

        Claim: two concurrent PATCH /participants both supplying the
        same starting version -> exactly one succeeds, the other gets
        ERR_VERSION_CONFLICT.
        """
        from test_helpers import create_participant
        p = create_participant()
        payload_a = update_participant_payload(
            full_name="Writer A", version=p["version"],
        )
        payload_b = update_participant_payload(
            full_name="Writer B", version=p["version"],
        )
        results = run_race(
            lambda: api.update_participant(p["id"], payload_a,
                                           custodian_headers),
            lambda: api.update_participant(p["id"], payload_b,
                                           custodian_headers),
        )
        outcome = assert_race_outcome(results, 1, 1)
        loser = outcome["failures"][0]
        validate_error(loser, ApiErrorId.ERR_VERSION_CONFLICT.value)
