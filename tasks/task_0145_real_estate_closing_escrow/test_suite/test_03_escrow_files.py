"""EscrowFile lifecycle and the diamond of contingencies (PRD §3.9)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    advance_escrow,
    assert_escrow_file,
    assert_emd,
    cancel_escrow,
    create_escrow_file_basic,
    create_party,
    create_property_entity,
    escrow_file_payload,
    re_get_emd,
    re_get_escrow_file,
    re_get_title_policy,
    setup_emd_held,
    setup_escrow_in_contingent_cd,
    setup_escrow_in_contingent_wire,
    setup_escrow_ready_to_close,
    setup_owners_policy_bound,
    setup_title_cleared,
    TEST_USERS,
    quote_title_policy,
    order_title_search,
    validate_error,
    validate_success,
    with_idempotency,
)


# ===========================================================================
# Open file — PRD §3.2
# ===========================================================================
class TestOpenEscrowFile:

    def test_open_file_returns_open_status(
        self, api, escrow_officer_headers,
    ):
        """PRD §3.2: "The file's status begins at OPEN."

        Claim: POST /escrow-files yields 201 with status == OPEN.
        """
        bundle = create_escrow_file_basic()
        ef = bundle["escrow_file"]
        assert_escrow_file(ef)
        assert ef["status"] == "OPEN", (
            f"expected OPEN at create, got {ef['status']}"
        )
        assert ef["version"] == 1

    def test_open_file_default_loan_amount_zero(
        self, api, escrow_officer_headers,
    ):
        """PRD §3.2: "an optional loan_amount that defaults to zero".

        Claim: omitting loan_amount yields loan_amount == 0.
        """
        headers = with_idempotency(escrow_officer_headers)
        buyer = create_party("BUYER")
        seller = create_party("SELLER")
        prop = create_property_entity()
        payload = {
            "property_id": prop["id"],
            "buyer_party_id": buyer["id"],
            "seller_party_id": seller["id"],
            "purchase_price": 250000.00,
            "closing_date_planned": "2026-06-01T00:00:00.000Z",
        }
        resp = api.create_escrow_file(payload, headers)
        data = validate_success(resp, expected_status=201)
        assert data["loan_amount"] == 0 or data["loan_amount"] == pytest.approx(0.0)

    def test_open_file_with_missing_buyer_party_id_404(
        self, api, escrow_officer_headers,
    ):
        """PRD §2.8: "existence of every entity referenced by a path
        parameter or body foreign key, evaluated left-to-right against
        the URL (ERR_NOT_FOUND)".

        Claim: unresolved FK yields ERR_NOT_FOUND.
        """
        headers = with_idempotency(escrow_officer_headers)
        prop = create_property_entity()
        seller = create_party("SELLER")
        payload = escrow_file_payload(
            property_id=prop["id"],
            buyer_party_id=NON_EXISTENT_UUID,
            seller_party_id=seller["id"],
        )
        resp = api.create_escrow_file(payload, headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


# ===========================================================================
# Advance — PRD §3.9
# ===========================================================================
class TestAdvanceEscrowFile:

    def test_advance_open_to_contingent_title_with_emd_held(
        self, api, escrow_officer_headers,
    ):
        """PRD §3.9: "the system advances the file to CONTINGENT_TITLE
        once an EarnestMoneyDeposit for the file has reached HELD".

        Claim: with EMD HELD, advance moves OPEN → CONTINGENT_TITLE.
        """
        bundle = setup_emd_held()
        ef_id = bundle["escrow_file"]["id"]
        # File is still OPEN until first advance.
        ef = re_get_escrow_file(ef_id)
        assert ef["status"] == "OPEN"
        ef = advance_escrow(ef_id)
        assert ef["status"] == "CONTINGENT_TITLE"

    def test_advance_to_contingent_cd_requires_ccr(
        self, api, escrow_officer_headers,
    ):
        """PRD §3.9: "Advancing past CONTINGENT_TITLE without a
        CCRDisclosure is rejected with ERR_CCR_NOT_ACKNOWLEDGED".

        Claim: missing CCR blocks advance with ERR_CCR_NOT_ACKNOWLEDGED.
        """
        # Setup an escrow up through OWNERS BOUND + title CLEARED but
        # NO CCR — then attempt to advance past CONTINGENT_TITLE.
        bundle = setup_emd_held()
        ef_id = bundle["escrow_file"]["id"]
        advance_escrow(ef_id)  # OPEN → CONTINGENT_TITLE
        setup_title_cleared(ef_id)
        setup_owners_policy_bound(ef_id)
        # Now attempt to advance without CCR.
        headers = with_idempotency(escrow_officer_headers)
        resp = api.advance_escrow_file(ef_id, headers)
        validate_error(resp, ApiErrorId.ERR_CCR_NOT_ACKNOWLEDGED)

    def test_advance_reaches_contingent_cd_when_all_preconditions_met(
        self, api,
    ):
        """PRD §3.9: "From CONTINGENT_TITLE it advances to CONTINGENT_CD
        once three preconditions hold simultaneously: a TitleSearch on
        the file is in CLEARED, a TitleInsurancePolicy with policy_kind
        equal to OWNERS is in BOUND, and a CCRDisclosure exists for the
        file."

        Claim: with all three preconditions met, the file reaches
        CONTINGENT_CD.

        # difficulty: non_linear_state_machine/escrow_file_branching_advance_with_revert_to_cancelled
        """
        bundle = setup_escrow_in_contingent_cd()
        assert bundle["escrow_file"]["status"] == "CONTINGENT_CD"


# ===========================================================================
# Cancel — PRD §3.9 + cascades
# ===========================================================================
class TestCancelEscrowFile:

    @pytest.mark.parametrize(
        "cancel_reason,expected_emd_status,expected_refund,expected_forfeit",
        [
            ("BUYER_DEFAULT", "RELEASED_TO_SELLER", 0.0, 3000.0),
            ("SELLER_DEFAULT", "RELEASED_TO_BUYER", 3000.0, 0.0),
            ("TITLE_DEFECT", "RELEASED_TO_BUYER", 3000.0, 0.0),
        ],
    )
    def test_cancel_disposes_emd_per_reason(
        self, api, cancel_reason, expected_emd_status,
        expected_refund, expected_forfeit,
    ):
        """PRD §3.2: "When the file cancels under buyer default ... the
        entire deposit forfeits to the seller. When the file cancels
        because the seller failed to deliver clear title or violated
        the CC&R disclosure obligation, the deposit refunds to the
        buyer in full".

        Claim: cancel dispatches EMD per cancel_reason.

        # difficulty: dual_variant_calc/emd_disposition_buyer_vs_seller_default
        """
        bundle = setup_emd_held(emd_amount=3000.00)
        ef_id = bundle["escrow_file"]["id"]
        ef = re_get_escrow_file(ef_id)
        cancel_escrow(ef_id, cancel_reason, version=ef["version"])
        emd_after = re_get_emd(bundle["emd"]["id"])
        assert emd_after["status"] == expected_emd_status
        assert emd_after["refunded_amount"] == pytest.approx(expected_refund)
        assert emd_after["forfeited_amount"] == pytest.approx(expected_forfeit)

    def test_cancel_voids_quoted_title_policies(self, api):
        """PRD §2.5: "every TitleInsurancePolicy still in QUOTED is
        voided".

        Claim: cancel from any pre-close status voids QUOTED policies.

        # difficulty: transitive_cascade/title_defective_cascade_to_quoted_void_to_escrow_advance_block
        """
        bundle = setup_emd_held()
        ef_id = bundle["escrow_file"]["id"]
        advance_escrow(ef_id)
        ts = setup_title_cleared(ef_id)
        policy = quote_title_policy(ef_id, policy_kind="OWNERS")
        # Sanity: policy is QUOTED.
        assert policy["status"] == "QUOTED"
        ef = re_get_escrow_file(ef_id)
        cancel_escrow(ef_id, "BUYER_DEFAULT", version=ef["version"])
        policy_after = re_get_title_policy(policy["id"])
        assert policy_after["status"] == "VOIDED"

    def test_cancel_from_contingent_title_branches_to_cancelled(
        self, api,
    ):
        """PRD §3.9: "The officer can also cancel the file from any
        non-terminal status — OPEN, CONTINGENT_TITLE, CONTINGENT_CD, or
        CONTINGENT_WIRE".

        Claim: cancel from CONTINGENT_TITLE moves file to CANCELLED.

        # difficulty: non_linear_state_machine/escrow_file_branching_advance_with_revert_to_cancelled
        """
        bundle = setup_emd_held()
        ef_id = bundle["escrow_file"]["id"]
        ef = advance_escrow(ef_id)  # OPEN → CONTINGENT_TITLE
        assert ef["status"] == "CONTINGENT_TITLE"
        ef = re_get_escrow_file(ef_id)
        cancel_escrow(ef_id, "SELLER_DEFAULT", version=ef["version"])
        ef_after = re_get_escrow_file(ef_id)
        assert ef_after["status"] == "CANCELLED"
        emd_after = re_get_emd(bundle["emd"]["id"])
        assert emd_after["status"] == "RELEASED_TO_BUYER"


# ===========================================================================
# Close — PRD §3.9 cascade EMD HELD → RELEASED_TO_SELLER
# ===========================================================================
class TestCloseEscrowFile:

    def test_close_cascades_held_emd_to_released_to_seller(self, api):
        """PRD §3.9: "The close cascades any EarnestMoneyDeposit still
        in HELD to RELEASED_TO_SELLER and appends the corresponding
        audit events."
        PRD §3.2: "When the file closes successfully, any deposit still
        HELD automatically transitions to RELEASED_TO_SELLER and its
        forfeited_amount is written to the deposit's full amount".

        Claim: close cascades EMD HELD → RELEASED_TO_SELLER with
        forfeited_amount = amount.
        """
        # Build through READY_TO_CLOSE, then settle the seller wire and
        # close.
        bundle = setup_escrow_ready_to_close()
        ef = bundle["escrow_file"]
        # Settle the seller wire's disbursement so close-preconds hold.
        seller_wire = bundle["seller_wire"]
        from test_helpers import setup_disbursement_settled
        disb = setup_disbursement_settled(
            ef["id"], seller_wire["id"], 1000.00,
        )
        assert disb["status"] == "SETTLED"
        # Close.
        from test_helpers import api_client, version_only_payload
        eo = TEST_USERS["escrow_officer_headers"]
        ef_after = api_client.close_escrow_file(
            ef["id"],
            version_only_payload(version=ef["version"]),
            with_idempotency(eo),
        )
        ef_data = validate_success(ef_after)
        assert ef_data["status"] == "CLOSED"
        emd_after = re_get_emd(bundle["emd"]["id"])
        assert emd_after["status"] == "RELEASED_TO_SELLER"
        assert emd_after["forfeited_amount"] == pytest.approx(
            bundle["emd"]["amount"],
        )
        assert emd_after["refunded_amount"] == pytest.approx(0.0)


# ===========================================================================
# Read / list — PRD §3.10
# ===========================================================================
class TestListEscrowFiles:

    def test_list_filter_by_status(self, api, escrow_officer_headers):
        """PRD §3.10: "Listing escrow files accepts three optional query
        filters — status, buyer_party_id, and seller_party_id".

        Claim: filter by status=OPEN returns only OPEN rows.
        """
        from test_helpers import validate_paginated
        # Seed an OPEN file.
        bundle = create_escrow_file_basic()
        resp = api.list_escrow_files(
            escrow_officer_headers, params={"status": "OPEN", "limit": 50},
        )
        data, meta = validate_paginated(resp)
        # All returned rows must have status == OPEN.
        for row in data:
            assert row["status"] == "OPEN"
        ids = [r["id"] for r in data]
        assert bundle["escrow_file"]["id"] in ids
