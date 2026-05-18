"""Title pipeline: search, defective cascade, insurance binding, premium
calculation (PRD §3.3)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    LENDERS_MIN_PREMIUM,
    OWNERS_MIN_PREMIUM,
    TEST_USERS,
    api_client,
    assert_title_policy,
    assert_title_search,
    bind_title_policy,
    clear_title_search,
    create_emd_held,
    create_escrow_file_basic,
    order_title_search,
    quote_title_policy,
    re_get_title_policy,
    re_get_title_search,
    setup_emd_held,
    setup_owners_policy_bound,
    setup_title_cleared,
    submit_title_findings,
    title_search_findings_payload,
    title_search_payload,
    title_policy_payload,
    validate_error,
    validate_success,
    version_only_payload,
    with_idempotency,
)


# ===========================================================================
# Title search lifecycle — PRD §3.3
# ===========================================================================
class TestTitleSearchLifecycle:

    def test_order_title_search_returns_ordered(self, api):
        """PRD §3.3: "A TitleOfficer orders a TitleSearch against the
        file by supplying the escrow_file_id; the search begins in
        ORDERED."

        Claim: POST /title-searches returns 201 with status = ORDERED.
        """
        bundle = create_escrow_file_basic()
        to = with_idempotency(TEST_USERS["title_officer_headers"])
        resp = api.create_title_search(
            title_search_payload(
                escrow_file_id=bundle["escrow_file"]["id"],
            ),
            to,
        )
        data = validate_success(resp, expected_status=201)
        assert_title_search(data)
        assert data["status"] == "ORDERED"

    def test_clear_requires_clean_chain_and_zero_liens(self, api):
        """PRD §3.3: "From COMPLETED, the search reaches CLEARED only
        when both chain_of_title_clean is true and open_liens_total is
        zero."

        Claim: clearing a COMPLETED search with open_liens_total > 0 is
        rejected with ERR_INVALID_STATE (or similar — see two-reader
        rule). We use ERR_INVALID_STATE because PRD §2.8 places state-
        check at priority 5 and this is a precondition guard.
        """
        bundle = create_escrow_file_basic()
        ts = order_title_search(bundle["escrow_file"]["id"])
        ts = submit_title_findings(
            ts["id"],
            chain_of_title_clean=True,
            open_liens_total=5000.00,
            encumbrance_count=0,
            version=ts["version"],
        )
        to = with_idempotency(TEST_USERS["title_officer_headers"])
        resp = api.clear_title_search(
            ts["id"], version_only_payload(version=ts["version"]), to,
        )
        # PRD §3.3 names the precondition for CLEARED. The implementer
        # signals failure-of-precondition via ERR_INVALID_STATE
        # (priority 5 in §2.8 covers from-state and its preconditions).
        from test_helpers import validate_error_is_one_of
        validate_error_is_one_of(
            resp,
            [
                ApiErrorId.ERR_INVALID_STATE.value,
                ApiErrorId.ERR_CROSS_ENTITY_STATE.value,
            ],
        )

    def test_mark_defective_cascades_quoted_policies_to_voided(self, api):
        """PRD §3.3: "The officer alternatively marks a completed
        search DEFECTIVE, which is a terminal state and which cascades
        any TitleInsurancePolicy on the same escrow_file_id still in
        QUOTED to VOIDED."

        Claim: mark-defective voids every QUOTED policy on the same
        file.

        # difficulty: transitive_cascade/title_defective_cascade_to_quoted_void_to_escrow_advance_block
        """
        bundle = create_escrow_file_basic()
        ts = order_title_search(bundle["escrow_file"]["id"])
        ts = submit_title_findings(
            ts["id"], chain_of_title_clean=False,
            open_liens_total=5000.00, encumbrance_count=2,
            version=ts["version"],
        )
        # Quote a policy while title is COMPLETED (not yet CLEARED).
        policy = quote_title_policy(
            bundle["escrow_file"]["id"], policy_kind="OWNERS",
        )
        assert policy["status"] == "QUOTED"
        # Now mark search defective.
        to = with_idempotency(TEST_USERS["title_officer_headers"])
        resp = api.mark_title_search_defective(
            ts["id"], version_only_payload(version=ts["version"]), to,
        )
        ts_after = validate_success(resp)
        assert ts_after["status"] == "DEFECTIVE"
        policy_after = re_get_title_policy(policy["id"])
        assert policy_after["status"] == "VOIDED"


# ===========================================================================
# Title policy bind preconditions — PRD §3.3
# ===========================================================================
class TestTitlePolicyBindPreconditions:

    def test_bind_requires_title_cleared(self, api):
        """PRD §3.3: "Binding a policy moves it to BOUND but only when
        (a) a TitleSearch on the same escrow_file_id is in CLEARED —
        otherwise the request is rejected with ERR_TITLE_NOT_CLEARED".

        Claim: bind without a CLEARED title search yields
        ERR_TITLE_NOT_CLEARED.
        """
        bundle = create_escrow_file_basic()
        ts = order_title_search(bundle["escrow_file"]["id"])  # ORDERED
        policy = quote_title_policy(
            bundle["escrow_file"]["id"], policy_kind="OWNERS",
        )
        to = with_idempotency(TEST_USERS["title_officer_headers"])
        resp = api.bind_title_policy(
            policy["id"], version_only_payload(version=policy["version"]), to,
        )
        validate_error(resp, ApiErrorId.ERR_TITLE_NOT_CLEARED)

    def test_lenders_bind_without_owners_bound_rejected(self, api):
        """PRD §3.3: "if policy_kind is LENDERS, an OWNERS policy on
        the same escrow_file_id has already reached BOUND; absent such
        a peer the request is rejected with ERR_LENDERS_REQUIRES_OWNERS."

        Claim: binding a LENDERS policy with no BOUND OWNERS peer
        yields ERR_LENDERS_REQUIRES_OWNERS.

        # difficulty: cross_entity_state_dependency/lenders_policy_bind_requires_owners_bound_same_file
        """
        bundle = create_escrow_file_basic()
        ef_id = bundle["escrow_file"]["id"]
        setup_title_cleared(ef_id)
        # Quote OWNERS but DO NOT bind.
        owners = quote_title_policy(ef_id, policy_kind="OWNERS")
        lenders = quote_title_policy(
            ef_id, policy_kind="LENDERS", insured_amount=240000.00,
        )
        to = with_idempotency(TEST_USERS["title_officer_headers"])
        resp = api.bind_title_policy(
            lenders["id"],
            version_only_payload(version=lenders["version"]), to,
        )
        validate_error(resp, ApiErrorId.ERR_LENDERS_REQUIRES_OWNERS)

    def test_lenders_bind_succeeds_after_owners_bound(self, api):
        """PRD §3.3: "if policy_kind is LENDERS, an OWNERS policy on
        the same escrow_file_id has already reached BOUND".

        Claim: after OWNERS is BOUND, LENDERS bind succeeds.

        # difficulty: cross_entity_state_dependency/lenders_policy_bind_requires_owners_bound_same_file
        """
        bundle = create_escrow_file_basic()
        ef_id = bundle["escrow_file"]["id"]
        setup_title_cleared(ef_id)
        owners = quote_title_policy(ef_id, policy_kind="OWNERS")
        owners = bind_title_policy(owners["id"], version=owners["version"])
        lenders = quote_title_policy(
            ef_id, policy_kind="LENDERS", insured_amount=240000.00,
        )
        lenders_bound = bind_title_policy(
            lenders["id"], version=lenders["version"],
        )
        assert lenders_bound["status"] == "BOUND"


# ===========================================================================
# Title insurance premium calculation — PRD §3.3 (difficulty rule 2)
# ===========================================================================
class TestTitleInsurancePremiumCalculation:

    def test_owners_premium_250k_tiered(self, api):
        """PRD §3.3: "The first one hundred thousand dollars is rated
        at five dollars per thousand; the band from one hundred
        thousand and one through five hundred thousand is rated at
        four dollars per thousand".

        Claim: OWNERS policy at insured_amount=250000.00 has
        premium = 100*5 + 150*4 = 500 + 600 = 1100.00.

        # difficulty: combinatorial_formula/title_insurance_tiered_with_simultaneous_issue_branch
        """
        bundle = create_escrow_file_basic(purchase_price=250000.00)
        setup_title_cleared(bundle["escrow_file"]["id"])
        policy = quote_title_policy(
            bundle["escrow_file"]["id"],
            policy_kind="OWNERS",
            insured_amount=250000.00,
        )
        assert policy["premium"] == pytest.approx(1100.00, abs=0.01)

    def test_owners_min_premium_floor_applied(self, api):
        """PRD §3.3: "For an OWNERS policy the final premium is the
        base rounded half-up to two decimal places, then taken as the
        larger of that figure and three hundred dollars (the owner's-
        policy floor)."

        Claim: OWNERS @ insured_amount=30000 yields premium=300.00
        (base=30*5=150, clamped up to OWNERS floor).

        # difficulty: combinatorial_formula/title_insurance_tiered_with_simultaneous_issue_branch
        """
        bundle = create_escrow_file_basic(purchase_price=30000.00)
        setup_title_cleared(bundle["escrow_file"]["id"])
        policy = quote_title_policy(
            bundle["escrow_file"]["id"],
            policy_kind="OWNERS",
            insured_amount=30000.00,
        )
        assert policy["premium"] == pytest.approx(OWNERS_MIN_PREMIUM, abs=0.01)

    def test_lenders_no_simultaneous_full_tiered(self, api):
        """PRD §3.3: "For a LENDERS policy without simultaneous issue
        the final premium is the base rounded half-up to two decimal
        places, then taken as the larger of that figure and two
        hundred dollars (the lender's-policy floor)."

        Claim: LENDERS @ 200000 with simultaneous_issue=false yields
        premium=900.00 (base=100*5+100*4=900, above 200 floor).

        # difficulty: combinatorial_formula/title_insurance_tiered_with_simultaneous_issue_branch
        """
        bundle = create_escrow_file_basic()
        setup_title_cleared(bundle["escrow_file"]["id"])
        # Bind OWNERS first to allow LENDERS quote/bind later, but
        # premium itself is computed at quote time regardless.
        # Use a fresh peer file to isolate simultaneous_issue=false.
        peer = create_escrow_file_basic()
        setup_title_cleared(peer["escrow_file"]["id"])
        lenders = quote_title_policy(
            peer["escrow_file"]["id"],
            policy_kind="LENDERS",
            insured_amount=200000.00,
            simultaneous_issue=False,
        )
        assert lenders["premium"] == pytest.approx(900.00, abs=0.01)

    def test_lenders_with_simultaneous_discount(self, api):
        """PRD §3.3: "For a LENDERS policy with simultaneous_issue set
        to true — which is honored only when a peer OWNERS policy on
        the same escrow_file_id is already BOUND at the moment the
        lender's policy is created — the system first multiplies the
        base by the simultaneous-issue discount factor of 0.40, rounds
        the product half-up to two decimal places, and then takes the
        larger of that and the two-hundred-dollar lender's-policy
        floor."

        Claim: with OWNERS already BOUND on the same file, a LENDERS
        policy @ insured_amount=200000 + simultaneous_issue=true has
        premium = round_half_up(900 * 0.40) = 360.00 (above 200 floor).

        # difficulty: combinatorial_formula/title_insurance_tiered_with_simultaneous_issue_branch
        """
        bundle = create_escrow_file_basic()
        ef_id = bundle["escrow_file"]["id"]
        setup_title_cleared(ef_id)
        setup_owners_policy_bound(ef_id, insured_amount=300000.00)
        lenders = quote_title_policy(
            ef_id,
            policy_kind="LENDERS",
            insured_amount=200000.00,
            simultaneous_issue=True,
        )
        assert lenders["premium"] == pytest.approx(360.00, abs=0.01)
