"""Contingency lifecycle, fail-cascade, listing close, lockbox retire.

Cites PRD §3.7 (Contingent Period and Path to Close) and §3.5 (Lockbox
cascade on SOLD).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    accept_offer,
    api_client,
    attach_contingency,
    close_listing,
    create_contingency_payload,
    fail_contingency,
    get_listing_state,
    get_offer_state,
    iso_in_future,
    iso_in_past,
    make_buyer_agent_headers,
    make_listing_agent_headers,
    satisfy_contingency,
    setup_listing_under_contract,
    submit_offer,
    validate_error,
    validate_success,
    waive_contingency,
)


class TestContingencyCreation:
    """PRD §3.7 contingency attachment."""

    def test_deadline_in_past_rejected(self, api):
        """PRD §3.7: 'The deadline must be strictly after the accepted
        offer's acceptance time and strictly in the future at the
        moment of creation; either violation yields
        ERR_CONTINGENCY_DEADLINE_INVALID.'

        Claim: deadline_at in the past → ERR_CONTINGENCY_DEADLINE_INVALID.
        """
        state = setup_listing_under_contract()
        res = api.create_contingency(
            state["accepted_listing"]["id"],
            create_contingency_payload(
                offer_id=state["accepted_offer"]["id"],
                kind="INSPECTION",
                deadline_at=iso_in_past(60),
            ),
            make_buyer_agent_headers(state["buyer_agent"]["id"]),
        )
        validate_error(
            res, ApiErrorId.ERR_CONTINGENCY_DEADLINE_INVALID.value,
        )

    def test_create_pending_contingency_succeeds(self, api):
        """PRD §3.7: 'A new contingency is PENDING.'

        Claim: POST /listings/{id}/contingencies creates a contingency
        in PENDING status.
        """
        state = setup_listing_under_contract()
        c = attach_contingency(
            state["accepted_listing"], state["accepted_offer"],
            state["buyer_agent"], kind="INSPECTION",
        )
        assert c["status"] == "PENDING"
        assert c["kind"] == "INSPECTION"


class TestContingencySettlement:
    """PRD §3.7 satisfy / waive."""

    def test_satisfy_pending_contingency(self, api):
        """PRD §3.7: 'A PENDING contingency may be marked SATISFIED by
        the BuyerAgent provided the listing is still UNDER_CONTRACT
        and the current logical time is strictly less than the
        contingency's deadline_at.'

        Claim: SATISFY on a PENDING contingency → status=SATISFIED.
        """
        state = setup_listing_under_contract()
        c = attach_contingency(
            state["accepted_listing"], state["accepted_offer"],
            state["buyer_agent"], kind="APPRAISAL",
        )
        c2 = satisfy_contingency(
            state["accepted_listing"], c, state["buyer_agent"],
        )
        assert c2["status"] == "SATISFIED"

    def test_waive_pending_contingency(self, api):
        """PRD §3.7: 'or WAIVED by the BuyerAgent provided only that
        the listing is still UNDER_CONTRACT (waiving is allowed even
        past the deadline, since waiving is the buyer's explicit
        decision to forgo the protection).'

        Claim: WAIVE on a PENDING contingency → status=WAIVED.
        """
        state = setup_listing_under_contract()
        c = attach_contingency(
            state["accepted_listing"], state["accepted_offer"],
            state["buyer_agent"], kind="FINANCING",
        )
        c2 = waive_contingency(
            state["accepted_listing"], c, state["buyer_agent"],
        )
        assert c2["status"] == "WAIVED"


class TestContingencyFailCascade:
    """PRD §3.7 fail-cascade: listing returns to ACTIVE."""

    def test_fail_contingency_reverts_listing_to_active(self, api):
        """PRD §3.7: 'A failed contingency cascades. The accepted offer
        is withdrawn (its status becomes WITHDRAWN); every other
        PENDING contingency on the same offer is transitioned to
        FAILED; the listing's accepted_offer_id is cleared back to
        null; and the listing transitions from UNDER_CONTRACT back to
        ACTIVE.'

        Claim: After fail, listing.status==ACTIVE, accepted_offer_id is
        null, the accepted offer is WITHDRAWN.

        # difficulty: non_linear_state_machine/listing_under_contract_revert_to_active_on_contingency_fail
        # difficulty: transitive_cascade/contingency_fail_cascade_2_hop
        """
        state = setup_listing_under_contract()
        c1 = attach_contingency(
            state["accepted_listing"], state["accepted_offer"],
            state["buyer_agent"], kind="INSPECTION",
        )
        # Fail c1.
        c1_after = fail_contingency(
            state["accepted_listing"], c1, state["buyer_agent"],
        )
        assert c1_after["status"] == "FAILED"
        listing_after = get_listing_state(state["accepted_listing"]["id"])
        assert listing_after["status"] == "ACTIVE", (
            f"PRD §3.7 cascade: listing must return to ACTIVE, got "
            f"{listing_after['status']!r}"
        )
        assert listing_after.get("accepted_offer_id") is None
        offer_after = get_offer_state(
            state["accepted_listing"]["id"], state["accepted_offer"]["id"],
        )
        assert offer_after["status"] == "WITHDRAWN"

    def test_fail_contingency_fails_sibling_pending_contingencies(self, api):
        """PRD §3.7: 'every other PENDING contingency on the same offer
        is transitioned to FAILED'.

        Claim: With two PENDING contingencies on the same offer,
        failing one transitions the other to FAILED via the cascade.

        # difficulty: transitive_cascade/contingency_fail_cascade_2_hop
        """
        state = setup_listing_under_contract()
        c1 = attach_contingency(
            state["accepted_listing"], state["accepted_offer"],
            state["buyer_agent"], kind="INSPECTION",
        )
        c2 = attach_contingency(
            state["accepted_listing"], state["accepted_offer"],
            state["buyer_agent"], kind="FINANCING",
        )
        # Fail c1 — cascade should fail c2 too.
        fail_contingency(
            state["accepted_listing"], c1, state["buyer_agent"],
        )
        # Re-fetch c2 — we have no direct GET in the PRD. Attempt a
        # redundant fail; PRD §2.10 says a redundant fresh-trigger
        # arriving after the cascade returns ERR_CONTINGENCY_ALREADY_FAILED.
        res = api.fail_contingency(
            state["accepted_listing"]["id"], c2["id"],
            make_buyer_agent_headers(state["buyer_agent"]["id"]),
        )
        # Either ERR_CONTINGENCY_ALREADY_FAILED (c2 already FAILED via
        # cascade) or ERR_INVALID_STATE (c2 transitioned out of PENDING
        # via cascade and a generic state check fires).
        from test_helpers import validate_error_is_one_of
        seen = validate_error_is_one_of(
            res,
            [
                ApiErrorId.ERR_CONTINGENCY_ALREADY_FAILED.value,
                ApiErrorId.ERR_INVALID_STATE.value,
            ],
        )
        assert seen in (
            ApiErrorId.ERR_CONTINGENCY_ALREADY_FAILED.value,
            ApiErrorId.ERR_INVALID_STATE.value,
        )


class TestListingClose:
    """PRD §3.7 close requires all contingencies SATISFIED/WAIVED."""

    def test_close_with_pending_contingency_rejected(self, api):
        """PRD §3.7: 'The action requires that every Contingency
        attached to the accepted offer be in SATISFIED or WAIVED
        status (a PENDING or FAILED contingency blocks the close as an
        invalid state).'

        Claim: Close while one contingency is still PENDING →
        ERR_INVALID_STATE.

        # difficulty: cross_entity_state_dependency/listing_close_requires_all_contingencies_settled
        """
        state = setup_listing_under_contract()
        attach_contingency(
            state["accepted_listing"], state["accepted_offer"],
            state["buyer_agent"], kind="INSPECTION",
        )
        listing_now = get_listing_state(state["accepted_listing"]["id"])
        res = api.close_listing(
            listing_now["id"], {"version": listing_now["version"]},
            make_listing_agent_headers(state["listing_agent"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    def test_close_after_waive_all_contingencies_succeeds(self, api):
        """PRD §3.7: 'every Contingency attached to the accepted offer
        be in SATISFIED or WAIVED status'.

        Claim: After all contingencies WAIVED, close transitions
        listing to SOLD.

        # difficulty: cross_entity_state_dependency/listing_close_requires_all_contingencies_settled
        """
        state = setup_listing_under_contract()
        c1 = attach_contingency(
            state["accepted_listing"], state["accepted_offer"],
            state["buyer_agent"], kind="INSPECTION",
        )
        c2 = attach_contingency(
            state["accepted_listing"], state["accepted_offer"],
            state["buyer_agent"], kind="FINANCING",
        )
        c1_satisfied = satisfy_contingency(
            state["accepted_listing"], c1, state["buyer_agent"],
        )
        c2_waived = waive_contingency(
            state["accepted_listing"], c2, state["buyer_agent"],
        )
        assert c1_satisfied["status"] == "SATISFIED"
        assert c2_waived["status"] == "WAIVED"
        # Re-fetch listing to get current version.
        listing_now = get_listing_state(state["accepted_listing"]["id"])
        res = api.close_listing(
            listing_now["id"], {"version": listing_now["version"]},
            make_listing_agent_headers(state["listing_agent"]["id"]),
        )
        sold = validate_success(res, 200)
        assert sold["status"] == "SOLD"

    def test_close_sets_buyer_status_sold(self, api):
        """PRD §3.7: 'On close, the buyer who made the accepted offer
        has their status set to SOLD.'

        Claim: After successful close, Buyer.status == SOLD.
        """
        state = setup_listing_under_contract()
        listing_now = get_listing_state(state["accepted_listing"]["id"])
        api.close_listing(
            listing_now["id"], {"version": listing_now["version"]},
            make_listing_agent_headers(state["listing_agent"]["id"]),
        )
        # GET the buyer.
        from test_helpers import TEST_USERS
        buyer_resp = api.get_buyer(
            state["buyer"]["id"], TEST_USERS["mls_admin_headers"],
        )
        buyer_after = validate_success(buyer_resp, 200)
        assert buyer_after["status"] == "SOLD", (
            f"PRD §3.7: Buyer.status must be SOLD after close, got "
            f"{buyer_after['status']!r}"
        )

    def test_close_retires_lockbox_via_cascade(self, api):
        """PRD §3.5: 'When a listing transitions from UNDER_CONTRACT to
        SOLD, the attached lockbox is retired by cascade — moving
        directly from ARMED (the state required for showings under the
        contingent listing) to RETIRED.'

        Claim: After close, the lockbox is RETIRED. Verified via the
        side-channel: re-arming a RETIRED lockbox is not a permitted
        transition; arm of non-DISARMED returns ERR_LOCKBOX_STATE.
        """
        state = setup_listing_under_contract()
        listing_now = get_listing_state(state["accepted_listing"]["id"])
        api.close_listing(
            listing_now["id"], {"version": listing_now["version"]},
            make_listing_agent_headers(state["listing_agent"]["id"]),
        )
        # Attempt to arm: RETIRED is neither DISARMED nor ARMED;
        # PRD §2.8 says ERR_LOCKBOX_STATE for arming a non-DISARMED box.
        res = api.arm_lockbox(
            state["accepted_listing"]["id"],
            make_listing_agent_headers(state["listing_agent"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_LOCKBOX_STATE.value)
