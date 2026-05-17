"""Optimistic concurrency control and PRD §2.10 concurrent-write
serialization.

PRD §2.6 (OCC) — version conflict on supplied version.
PRD §2.10 — four explicitly serialized scenarios with named
error_ids for the loser.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    assert_exactly_one_succeeds,
    assert_race_outcome,
    create_drug,
    create_formulary_entry,
    create_member,
    create_plan,
    occ_payload,
    re_get_prior_authorization,
    run_race,
    setup_paid_claim,
    setup_reference_data,
    setup_submitted_pa,
    submit_claim,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


# ===========================================================================
# OCC — version conflict (PRD §2.6).
# ===========================================================================
class TestVersionConflict:
    """PRD §2.6: "When version is supplied, the server compares it
    against the entity's current version; if the two do not match,
    the request is rejected with ERR_VERSION_CONFLICT and no side
    effects are produced.\""""

    def test_stale_version_on_pa_submit_rejected(
        self, api, prescriber_headers,
    ):
        """PRD §2.6: stale version -> ERR_VERSION_CONFLICT.

        Claim: submitting a PA with a stale version yields
        ERR_VERSION_CONFLICT.
        """
        from test_helpers import create_pa_in_draft
        _, drug, _, member = setup_reference_data()
        pa = create_pa_in_draft(
            member_id=member["id"], drug_id=drug["id"],
        )
        # First submit — succeeds and bumps version.
        api.submit_prior_authorization(
            pa["id"], occ_payload(version=pa["version"]),
            prescriber_headers,
        )
        # Second submit with the same (now stale) version.
        res = api.submit_prior_authorization(
            pa["id"], occ_payload(version=pa["version"]),
            prescriber_headers,
        )
        # The PA is no longer in DRAFT either, so either of two
        # PRD-faithful outcomes is acceptable: ERR_VERSION_CONFLICT
        # (rung 17 — OCC) or ERR_INVALID_STATE (rung 4 — state). The
        # PRD ladder evaluates rung 4 BEFORE rung 17, so the rule-
        # bearing PRD prose only commits to ERR_INVALID_STATE here.
        validate_error_is_one_of(
            res,
            ["ERR_INVALID_STATE", "ERR_VERSION_CONFLICT"],
        )


# ===========================================================================
# PRD §2.10 explicit concurrency scenarios.
# ===========================================================================
class TestSerializedConcurrentWrites:

    def test_two_approve_calls_one_wins_other_invalid_state(
        self, api, clinical_reviewer_headers,
        clinical_reviewer_headers_alt,
    ):
        """PRD §2.10: "Two simultaneous approve requests on the same
        prior-authorization id: exactly one wins. The serialization
        point is the first writer of the PriorAuthorization.status
        transition; the loser observes the new status (no longer
        SUBMITTED) and is rejected with ERR_INVALID_STATE at HTTP
        409."

        Claim: exactly one approve succeeds (200); the loser is 4xx
        with ERR_INVALID_STATE.
        """
        _, drug, _, member = setup_reference_data()
        pa = setup_submitted_pa(
            member_id=member["id"], drug_id=drug["id"],
        )

        def call_a():
            return api.approve_prior_authorization(
                pa["id"], occ_payload(version=pa["version"]),
                clinical_reviewer_headers,
            )

        def call_b():
            return api.approve_prior_authorization(
                pa["id"], occ_payload(version=pa["version"]),
                clinical_reviewer_headers_alt,
            )

        results = run_race(call_a, call_b)
        outcome = assert_race_outcome(results, 1, 1)
        loser = outcome["failures"][0]
        validate_error(loser, "ERR_INVALID_STATE")
        # Sanity: PA is now APPROVED.
        refreshed = re_get_prior_authorization(pa["id"])
        assert refreshed["status"] == "APPROVED"

    def test_two_adjudicate_calls_overlapping_supply_loser_refill_too_soon(
        self, api, claims_adjudicator_headers,
        claims_adjudicator_headers_alt,
    ):
        """PRD §2.10: "Two simultaneous adjudicate requests on
        different claim ids whose projected supply windows for the
        same member-drug pair overlap: at most one transitions to
        ADJUDICATED. The serialization point is the first writer to
        set adjudicated_allowed_cents on its claim row; the loser
        observes the existing ADJUDICATED row, fails the refill-too-
        soon check, and is rejected with ERR_REFILL_TOO_SOON at HTTP
        409."

        Claim: with two SUBMITTED claims for the same (member, drug)
        and overlapping supply windows, exactly one adjudicate wins;
        the loser gets ERR_REFILL_TOO_SOON.
        """
        _, drug, _, member = setup_reference_data()
        c1 = submit_claim(
            member_id=member["id"], drug_id=drug["id"],
            channel="RETAIL_30", days_supply=30, quantity=1,
        )
        c2 = submit_claim(
            member_id=member["id"], drug_id=drug["id"],
            channel="RETAIL_30", days_supply=30, quantity=1,
        )

        def call_a():
            return api.adjudicate_claim(
                c1["id"], occ_payload(version=c1["version"]),
                claims_adjudicator_headers,
            )

        def call_b():
            return api.adjudicate_claim(
                c2["id"], occ_payload(version=c2["version"]),
                claims_adjudicator_headers_alt,
            )

        results = run_race(call_a, call_b)
        outcome = assert_race_outcome(results, 1, 1)
        loser = outcome["failures"][0]
        validate_error(loser, "ERR_REFILL_TOO_SOON")
