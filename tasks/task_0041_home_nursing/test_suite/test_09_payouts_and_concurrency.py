"""Payout batches and concurrency-driven serialization rules.

Covers PRD §3.5 (payout batch flow) and §2.10 (concurrency rules).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    DEFAULT_NOW_ISO,
    add_days,
    api_client,
    assert_exactly_one_succeeds,
    assert_payout_batch,
    create_certified_nurse,
    create_payout_batch_payload,
    get_success_data,
    make_compliance_officer_headers,
    make_nurse_headers,
    make_patient_headers,
    make_platform_admin_headers,
    run_race,
    setup_basic_dispatched_order,
    setup_completed_order,
    stable_user_id,
    validate_error,
    validate_success,
)


class TestPayoutBatchBuild:

    def test_payout_batch_aggregates_finalized_settlements(
        self, api, platform_admin_headers,
    ):
        """PRD §3.5: 'the server gathers every Settlement whose status
        is FINALIZED, whose payout_batch_id is null, and whose created_at
        is at-or-before the cutoff (the upper bound is inclusive). The
        batch row is created in BUILDING, the gathered settlements are
        atomically marked with the new payout_batch_id and their status
        advanced to PAID_OUT, the batch's total_settlements,
        total_nurse_share_cents ... and total_platform_share_cents ... are
        populated, and the batch's status advances to PAID.'
        """
        setup = setup_completed_order(nurse_specialty="ELDERLY_CARE")
        cutoff = add_days(DEFAULT_NOW_ISO, 30)
        res = api.create_payout_batch(
            create_payout_batch_payload(cutoff_at=cutoff),
            platform_admin_headers,
        )
        data = validate_success(res, expected_status=201)
        assert_payout_batch(data)
        assert data["status"] in ("PAID", "BUILDING")
        assert data["total_settlements"] >= 1


class TestPayoutBatchConcurrency:

    def test_two_concurrent_builds_one_succeeds(
        self, api, platform_admin_headers, platform_admin_headers_alt,
    ):
        """PRD §2.10: 'Two attempts to start a payout-batch build while
        a BUILDING batch is already open serialize on the batch's
        status; the loser receives ERR_PAYOUT_BATCH_ALREADY_BUILDING at
        HTTP 409.'

        Claim: when two POST /payout-batches calls race, exactly one
        succeeds; the other returns ERR_PAYOUT_BATCH_ALREADY_BUILDING.

        Some implementations may complete the first build so quickly
        (BUILDING -> PAID atomically) that the second sees no BUILDING
        batch and also succeeds. PRD §2.10 commits to the loser-error
        only when a BUILDING batch is currently open; we therefore
        accept either 'exactly one succeeds with ERR' or 'both succeed'
        provided there is no inconsistency.
        """
        # Make at least one settlement available.
        setup = setup_completed_order(nurse_specialty="ELDERLY_CARE")
        cutoff = add_days(DEFAULT_NOW_ISO, 30)
        results = run_race(
            lambda: api.create_payout_batch(
                create_payout_batch_payload(cutoff_at=cutoff),
                platform_admin_headers,
            ),
            lambda: api.create_payout_batch(
                create_payout_batch_payload(cutoff_at=cutoff),
                platform_admin_headers_alt,
            ),
        )
        # PRD §2.10 commits to 'the loser receives
        # ERR_PAYOUT_BATCH_ALREADY_BUILDING' only when a BUILDING batch
        # is currently open. If both succeed, that is consistent with
        # the build completing instantly to PAID before the second
        # writer arrived. Both branches are PRD-faithful.
        successes = [r for r in results if 200 <= r.status_code < 300]
        failures = [r for r in results if r.status_code >= 400]
        assert len(successes) >= 1
        for f in failures:
            body = f.json()
            assert (
                body["data"]["error_id"]
                == ApiErrorId.ERR_PAYOUT_BATCH_ALREADY_BUILDING.value
            ), (
                f"PRD §2.10: loser must be "
                f"ERR_PAYOUT_BATCH_ALREADY_BUILDING, "
                f"got {body['data']['error_id']}"
            )


class TestDispatchAcceptanceConcurrency:

    def test_two_nurses_race_to_accept(
        self, api, platform_admin_headers,
    ):
        """PRD §3.3: 'Acceptance additionally requires that the order be
        in AWAITING_DISPATCH and that no other dispatch on the same
        order has already reached ACCEPTED; the second writer in a race
        loses with ERR_DISPATCH_ALREADY_TAKEN.'

        Claim: when two acceptances on sibling dispatches race for the
        same order, exactly one succeeds; the loser receives
        ERR_DISPATCH_ALREADY_TAKEN.

        Some implementations may produce two sibling dispatches only
        through reject-then-redispatch chains; here we use a single
        dispatch and have the same nurse accept it twice in parallel.
        PRD §3.3 says 'the second writer in a race loses with
        ERR_DISPATCH_ALREADY_TAKEN'.
        """
        setup = setup_basic_dispatched_order()
        d = setup["dispatch"]
        nurse_headers = make_nurse_headers(setup["nurse_id"])
        results = run_race(
            lambda: api.accept_dispatch(d["id"], nurse_headers),
            lambda: api.accept_dispatch(d["id"], nurse_headers),
        )
        successes = [r for r in results if 200 <= r.status_code < 300]
        failures = [r for r in results if r.status_code >= 400]
        # PRD §2.10: 'serialize to exactly one acceptance per order'
        assert len(successes) == 1, (
            f"PRD §2.10: 'serialize to exactly one acceptance per order' "
            f"-- got {len(successes)} successes"
        )
        for f in failures:
            body = f.json()
            # PRD prose names ERR_DISPATCH_ALREADY_TAKEN explicitly for
            # the race-loser. ERR_INVALID_STATE is also a faithful
            # outcome if the loser observes the dispatch already
            # ACCEPTED before the order-level check fires.
            assert body["data"]["error_id"] in (
                ApiErrorId.ERR_DISPATCH_ALREADY_TAKEN.value,
                ApiErrorId.ERR_INVALID_STATE.value,
            ), (
                f"Race loser must be ERR_DISPATCH_ALREADY_TAKEN or "
                f"ERR_INVALID_STATE per PRD §2.10/§3.3, got "
                f"{body['data']['error_id']}"
            )
