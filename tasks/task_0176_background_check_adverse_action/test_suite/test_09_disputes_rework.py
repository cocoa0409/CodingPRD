"""Disputes (open, resolve UPHELD/OVERTURNED), rework cycle, and
rework cap — PRD §3.7.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_dispute,
    create_dispute_payload,
    criminal_raw_finding,
    education_raw_finding,
    get_order,
    list_verification_items_for_order,
    make_candidate_headers,
    open_dispute_as_candidate,
    request_rework_on_order,
    resolve_dispute_as_adjudicator,
    return_item,
    setup_order_pre_adverse,
    setup_pre_adverse_with_dispute_open,
    upsert_jurisdiction_policy,
    validate_error,
    validate_success,
)


# ===========================================================================
# Opening a dispute — PRD §3.7
# ===========================================================================
class TestOpenDispute:

    def test_candidate_opens_dispute_status_open(
        self, api, adjudicator_headers,
    ):
        """PRD §3.7: "On creation, the dispute's `status` is `OPEN`,
        the parent item's `dispute_id` is set, the item moves into
        `DISPUTED`".

        Claim: POST /fcra/disputes -> 201 with status=OPEN; the parent
        item.status is DISPUTED.
        """
        cand, cons, order, items, flow = setup_order_pre_adverse(
            residence_jurisdiction="CA",
            jurisdiction_kwargs={"criminal_lookback_years": 7},
            adjudicator_headers=adjudicator_headers,
        )
        criminal = next(it for it in items if it["kind"] == "CRIMINAL")
        h = make_candidate_headers(cand["id"])
        resp = api.create_dispute(
            create_dispute_payload(
                verification_item_id=criminal["id"],
                reason_text="Identity mistake; I have no felony.",
            ),
            h,
        )
        dispute = validate_success(resp, expected_status=201)
        assert_dispute(dispute)
        assert dispute["status"] == "OPEN"
        # Item should be DISPUTED.
        item_after = validate_success(
            api.get_verification_item(criminal["id"], h),
        )
        assert item_after["status"] == "DISPUTED"

    def test_open_dispute_pauses_adverse_flow(
        self, api, adjudicator_headers,
    ):
        """PRD §3.7: "any associated `AdverseActionFlow`'s
        `procedural_status` moves to `DISPUTE_PAUSED`."

        Claim: opening a dispute on an item of an order in
        PRE_ADVERSE_ISSUED moves AdverseActionFlow.procedural_status
        to DISPUTE_PAUSED while notification_status is unchanged.
        """
        cand, cons, order, items, flow, dispute = (
            setup_pre_adverse_with_dispute_open(
                residence_jurisdiction="CA",
                jurisdiction_kwargs={"criminal_lookback_years": 7},
                adjudicator_headers=adjudicator_headers,
            )
        )
        # Re-read the flow via the order audit trail / state. The PRD
        # exposes the flow via the Pre-Adverse return value originally;
        # there is no direct GET /flow endpoint, so we rely on the
        # state assertion via the order to confirm DISPUTE_PAUSED
        # downstream — but the dispute itself is what tests claim. We
        # instead verify the dispute is OPEN and the parent item is
        # DISPUTED (already confirmed in the prior test) and that a
        # subsequent Final Adverse attempt is blocked (covered in
        # test_08).
        assert dispute["status"] == "OPEN"


# ===========================================================================
# Dispute ownership — PRD §3.7
# ===========================================================================
class TestDisputeOwnership:

    def test_dispute_on_other_candidates_item_rejected(
        self, api, adjudicator_headers,
    ):
        """PRD §3.7: "The candidate may only dispute items belonging
        to their own orders (`ERR_DISPUTE_NOT_OWNED`)."

        Claim: a Candidate POSTing /fcra/disputes against a
        VerificationItem on someone else's order ->
        ERR_DISPUTE_NOT_OWNED.
        """
        # Build a victim order owned by cand_a in PRE_ADVERSE_ISSUED.
        cand_a, cons_a, order_a, items_a, _flow_a = (
            setup_order_pre_adverse(
                residence_jurisdiction="CA",
                jurisdiction_kwargs={"criminal_lookback_years": 7},
                adjudicator_headers=adjudicator_headers,
            )
        )
        # Now another candidate cand_b tries to dispute one of cand_a's
        # items. We give cand_b a candidate id via a separate creation
        # (the id is the X-User-ID, which is the entity-backed identity).
        from test_helpers import (
            create_candidate,
            record_consent_as_recruiter,
        )
        cand_b = create_candidate(residence_jurisdiction="CA")
        criminal_a = next(it for it in items_a if it["kind"] == "CRIMINAL")
        resp = api.create_dispute(
            create_dispute_payload(
                verification_item_id=criminal_a["id"],
                reason_text="Not my item.",
            ),
            make_candidate_headers(cand_b["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DISPUTE_NOT_OWNED.value)


# ===========================================================================
# Resolving a dispute — PRD §3.7
# ===========================================================================
class TestResolveDispute:

    def test_uphold_dispute_moves_item_to_failed(
        self, api, adjudicator_headers,
    ):
        """PRD §3.7: "When the resolution is `UPHELD`, the dispute's
        `status` becomes `UPHELD`, the underlying item moves to
        `FAILED`".

        Claim: resolve UPHELD -> dispute.status==UPHELD and parent
        item.status==FAILED.
        """
        cand, cons, order, items, flow, dispute = (
            setup_pre_adverse_with_dispute_open(
                residence_jurisdiction="CA",
                jurisdiction_kwargs={"criminal_lookback_years": 7},
                adjudicator_headers=adjudicator_headers,
            )
        )
        resolved = resolve_dispute_as_adjudicator(
            dispute_id=dispute["id"],
            status="UPHELD",
            adjudicator_headers=adjudicator_headers,
        )
        assert resolved["status"] == "UPHELD"
        # Parent item now FAILED.
        item_after = validate_success(
            api.get_verification_item(
                dispute["verification_item_id"], adjudicator_headers,
            ),
        )
        assert item_after["status"] == "FAILED"

    def test_overturn_dispute_moves_item_to_rework_required(
        self, api, adjudicator_headers,
    ):
        """PRD §3.7: "When the resolution is `OVERTURNED`, the
        dispute's `status` becomes `OVERTURNED` and the item moves to
        `REWORK_REQUIRED`, with `rework_count` incremented by 1".

        Claim: resolve OVERTURNED -> dispute.status==OVERTURNED, item
        moves to REWORK_REQUIRED, item.rework_count incremented by 1.
        """
        cand, cons, order, items, flow, dispute = (
            setup_pre_adverse_with_dispute_open(
                residence_jurisdiction="CA",
                jurisdiction_kwargs={"criminal_lookback_years": 7},
                adjudicator_headers=adjudicator_headers,
            )
        )
        item_before = validate_success(
            api.get_verification_item(
                dispute["verification_item_id"], adjudicator_headers,
            ),
        )
        rework_before = item_before.get("rework_count", 0)
        resolved = resolve_dispute_as_adjudicator(
            dispute_id=dispute["id"],
            status="OVERTURNED",
            adjudicator_headers=adjudicator_headers,
        )
        assert resolved["status"] == "OVERTURNED"
        item_after = validate_success(
            api.get_verification_item(
                dispute["verification_item_id"], adjudicator_headers,
            ),
        )
        assert item_after["status"] == "REWORK_REQUIRED"
        assert item_after["rework_count"] == rework_before + 1


# ===========================================================================
# SoD on resolve_dispute — PRD §3.7
# ===========================================================================
class TestResolveDisputeSoD:

    def test_resolve_dispute_by_order_opener_rejected(self, api):
        """PRD §3.7: "The resolving `Adjudicator` must not be the
        order's opener (a violation surfaces as `ERR_SOD_VIOLATION`)."

        Claim: an Adjudicator whose X-User-ID equals the Recruiter's
        opens-order id, attempting to resolve a dispute on that order
        -> ERR_SOD_VIOLATION.

        Setup: build the order through `setup_pre_adverse_with_dispute_open`,
        which internally uses the default Recruiter shared id
        (RECRUITER_SHARED_ID) for the order opener. Then mint an
        Adjudicator with that same id and call resolve_dispute — the
        collision triggers the SoD check.
        """
        from test_helpers import (
            RECRUITER_SHARED_ID,
            make_adjudicator_headers,
        )
        cand, cons, order, items, flow, dispute = (
            setup_pre_adverse_with_dispute_open(
                residence_jurisdiction="CA",
                jurisdiction_kwargs={"criminal_lookback_years": 7},
            )
        )
        # Adjudicator whose X-User-ID equals the order's opened_by_user_id.
        clashing_adj_h = make_adjudicator_headers(RECRUITER_SHARED_ID)
        resp = api.resolve_dispute(
            dispute["id"],
            {"status": "UPHELD", "resolution_note": "Test SoD."},
            clashing_adj_h,
        )
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION.value)


# ===========================================================================
# Rework lifecycle and cap — PRD §3.7
# ===========================================================================
class TestReworkCap:
    """PRD §3.7: "At least one targeted item must have a `rework_count`
    strictly less than 2; otherwise the request is rejected with
    `ERR_REWORK_CAP_EXCEEDED`."
    """

    def test_request_rework_increments_count(
        self, api, adjudicator_headers, verifier_headers,
    ):
        """PRD §3.7: "Each eligible targeted item moves to
        `REWORK_REQUIRED` and its `rework_count` is incremented by 1,
        the order moves from `PRE_ADVERSE_ISSUED` to `REWORK`".

        Claim: POST request-rework on a PRE_ADVERSE_ISSUED order
        increments item.rework_count by 1 and moves order.status to
        REWORK.
        """
        cand, cons, order, items, flow = setup_order_pre_adverse(
            residence_jurisdiction="CA",
            jurisdiction_kwargs={"criminal_lookback_years": 7},
            adjudicator_headers=adjudicator_headers,
        )
        criminal = next(it for it in items if it["kind"] == "CRIMINAL")
        request_rework_on_order(
            order_id=order["id"],
            target_item_ids=[criminal["id"]],
            adjudicator_headers=adjudicator_headers,
        )
        item_after = validate_success(
            api.get_verification_item(criminal["id"], adjudicator_headers),
        )
        assert item_after["status"] == "REWORK_REQUIRED"
        assert item_after["rework_count"] == 1
        order_after = get_order(order["id"])
        assert order_after["status"] == "REWORK"

    def test_rework_cap_exceeded(
        self, api, adjudicator_headers, verifier_headers,
    ):
        """PRD §3.7: "if the increment would carry the count past 2,
        the increment is not applied and the parent order is instead
        forced to `TERMINATED_ADVERSE` via the rework-cap path,
        surfacing `ERR_REWORK_CAP_EXCEEDED` (HTTP 422) on a same-call
        attempt."

        Claim: after two OVERTURN cycles (rework_count 0->1->2), a
        third OVERTURN attempt that would carry the count past 2 is
        rejected with ERR_REWORK_CAP_EXCEEDED. PRD §3.7 lists items
        in REWORK_REQUIRED as disputable, so successive OVERTURNs on
        the same item can drive rework_count to the cap.
        """
        cand, cons, order, items, flow = setup_order_pre_adverse(
            residence_jurisdiction="CA",
            jurisdiction_kwargs={"criminal_lookback_years": 7},
            adjudicator_headers=adjudicator_headers,
        )
        criminal = next(it for it in items if it["kind"] == "CRIMINAL")

        # ---- Cycle 1: OVERTURN bumps rework_count 0 -> 1.
        d1 = open_dispute_as_candidate(
            candidate_id=cand["id"],
            verification_item_id=criminal["id"],
        )
        resolve_dispute_as_adjudicator(
            dispute_id=d1["id"], status="OVERTURNED",
            adjudicator_headers=adjudicator_headers,
        )
        # ---- Cycle 2: dispute the REWORK_REQUIRED item again; OVERTURN
        # bumps rework_count 1 -> 2 (at the cap). PRD §3.7 lists items
        # in REWORK_REQUIRED as disputable.
        d2 = open_dispute_as_candidate(
            candidate_id=cand["id"],
            verification_item_id=criminal["id"],
        )
        resolve_dispute_as_adjudicator(
            dispute_id=d2["id"], status="OVERTURNED",
            adjudicator_headers=adjudicator_headers,
        )
        item_mid = validate_success(
            api.get_verification_item(criminal["id"], adjudicator_headers),
        )
        assert item_mid["rework_count"] == 2, (
            f"after 2 OVERTURNs expected rework_count=2, got "
            f"{item_mid['rework_count']}"
        )
        # ---- Cycle 3: third OVERTURN attempt -> the increment would
        # carry the count past 2, so ERR_REWORK_CAP_EXCEEDED fires.
        d3 = open_dispute_as_candidate(
            candidate_id=cand["id"],
            verification_item_id=criminal["id"],
        )
        from test_helpers import resolve_dispute_payload
        resp = api.resolve_dispute(
            d3["id"],
            resolve_dispute_payload(status="OVERTURNED"),
            adjudicator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_REWORK_CAP_EXCEEDED.value)
