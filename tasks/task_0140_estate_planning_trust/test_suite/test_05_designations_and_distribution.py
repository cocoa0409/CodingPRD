"""Designations, the LOCKED cascade, the planned-distribution
waterfall calculation, distribution execution + drift, and reversal.

Coverage targets (PRD §3.6, §3.9, §3.10, §3.11, §3.12):
- Designation create over-allocation -> ERR_DESIGNATION_OVER_ALLOCATED.
- Designation create on inactive Beneficiary -> ERR_REFERENCE_NOT_FOUND.
- DELETE PROPOSED designation -> VOIDED.
- INVENTORIED -> DISTRIBUTING preconditions
  (ERR_POSTURE_BLOCKED, ERR_DESIGNATIONS_INCOMPLETE,
  ERR_NO_ACCEPTED_DISTRIBUTION_PETITION).
- PROPOSED -> LOCKED side effect.
- Distribution PLANNED -> EXECUTED requires actual=planned (drift).
- Asset APPRAISED -> DISTRIBUTED preconditions.
- Distribution REVERSED side effects.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_beneficiary,
    add_designation,
    api_client,
    asset_state_payload,
    beneficiary_state_payload,
    create_designation_payload,
    distribution_state_payload,
    estate_state_payload,
    get_success_data,
    make_beneficiary_headers,
    setup_disclaimed_beneficiary_blocks_distributing,
    setup_distributing,
    setup_executed_distribution_for_reverse,
    setup_in_probate_with_minor_no_guardian,
    setup_inventoried,
    setup_inventoried_no_designations,
    setup_inventoried_with_two_designations,
    submit_filing,
    transition_filing,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


class TestDesignationCreate:

    def test_over_allocation_rejected(self, api):
        """PRD §3.6: "the sum of share_basis_points across all
        PROPOSED and LOCKED designations targeting the same
        asset_id, including the proposed new row, must not exceed
        10000; otherwise the create is rejected with
        ERR_DESIGNATION_OVER_ALLOCATED."

        Claim: two designations on the same asset summing to 11000
        -> second create rejected.
        """
        base = setup_inventoried(
            bond_amount_cents=10_000_000,
            assets=[
                {
                    "asset_class": "FINANCIAL",
                    "declared_value_cents": 1000,
                    "appraised_value_cents": 1000,
                },
            ],
        )
        estate = base["estate"]
        exec_h = base["executor_headers"]
        asset = base["assets"][0]
        b1 = add_beneficiary(estate["id"], is_minor=False,
                             exec_headers=exec_h)
        b2 = add_beneficiary(estate["id"], is_minor=False,
                             exec_headers=exec_h)
        add_designation(
            estate["id"], asset_id=asset["id"],
            beneficiary_id=b1["id"], share_basis_points=6000,
            priority_rank=1, exec_headers=exec_h,
        )
        # Second designation 6000 → sum=12000>10000.
        resp = api_client.create_designation(
            estate["id"],
            create_designation_payload(
                asset_id=asset["id"], beneficiary_id=b2["id"],
                share_basis_points=6000, priority_rank=2,
            ),
            exec_h,
        )
        validate_error(
            resp, ApiErrorId.ERR_DESIGNATION_OVER_ALLOCATED.value,
        )

    def test_designation_on_inactive_beneficiary_rejected(self, api):
        """PRD §3.6: "Each designation supplies an asset_id, a
        beneficiary_id (which must reference a Beneficiary whose
        status is ACTIVE at creation, otherwise
        ERR_REFERENCE_NOT_FOUND)".

        Claim: creating a designation referencing a REMOVED
        beneficiary -> ERR_REFERENCE_NOT_FOUND.
        """
        base = setup_inventoried(
            bond_amount_cents=10_000_000,
            assets=[
                {
                    "asset_class": "FINANCIAL",
                    "declared_value_cents": 1000,
                    "appraised_value_cents": 1000,
                },
            ],
        )
        estate = base["estate"]
        exec_h = base["executor_headers"]
        asset = base["assets"][0]
        b = add_beneficiary(estate["id"], is_minor=False,
                            exec_headers=exec_h)
        # CourtClerk removes the beneficiary -> ACTIVE -> REMOVED.
        api_client.transition_beneficiary(
            estate["id"], b["id"],
            beneficiary_state_payload("REMOVED"),
            TEST_USERS["court_clerk_headers"],
        )
        resp = api_client.create_designation(
            estate["id"],
            create_designation_payload(
                asset_id=asset["id"], beneficiary_id=b["id"],
                share_basis_points=10000, priority_rank=1,
            ),
            exec_h,
        )
        validate_error(
            resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value,
        )


class TestDesignationDelete:

    def test_delete_proposed_voids_designation(self, api):
        """PRD §3.6: "The executor may delete (void) any PROPOSED
        designation outright, moving the row's status to VOIDED".

        Claim: DELETE /estates/.../designations/{id} -> VOIDED.
        """
        bundle = setup_inventoried_with_two_designations()
        estate = bundle["estate"]
        exec_h = bundle["executor_headers"]
        d = bundle["designations"][0]
        resp = api_client.delete_designation(
            estate["id"], d["id"], exec_h,
        )
        # Spec gives back the VOIDED row per §1.5 endpoints.
        voided = validate_success(resp)
        assert voided["status"] == "VOIDED"


class TestInventoriedToDistributing:

    def test_advance_without_accepted_distribution_petition(self, api):
        """PRD §3.11: "A ProbateFiling of filing_type
        DISTRIBUTION_PETITION and status ACCEPTED must exist, else
        ERR_NO_ACCEPTED_DISTRIBUTION_PETITION."

        Claim: shares sum to 10000, no minor, no petition -> the
        advance fails with ERR_NO_ACCEPTED_DISTRIBUTION_PETITION.
        """
        bundle = setup_inventoried_with_two_designations()
        estate = bundle["estate"]
        exec_h = bundle["executor_headers"]
        # Don't submit DISTRIBUTION_PETITION.
        resp = api_client.transition_estate(
            estate["id"], estate_state_payload("DISTRIBUTING"),
            exec_h,
        )
        validate_error(
            resp,
            ApiErrorId.ERR_NO_ACCEPTED_DISTRIBUTION_PETITION.value,
        )

    def test_advance_with_minor_guardianship_missing(self, api):
        """PRD §3.11: "Every beneficiary with is_minor true must
        have a GuardianshipDirective in status EFFECTIVE linked
        through Beneficiary.guardianship_id; missing the link yields
        ERR_GUARDIANSHIP_MISSING."

        Claim: minor beneficiary without EFFECTIVE guardianship ->
        ERR_GUARDIANSHIP_MISSING on advance.
        """
        bundle = setup_in_probate_with_minor_no_guardian()
        estate = bundle["estate"]
        exec_h = bundle["executor_headers"]
        resp = api_client.transition_estate(
            estate["id"], estate_state_payload("DISTRIBUTING"),
            exec_h,
        )
        validate_error(resp,
                       ApiErrorId.ERR_GUARDIANSHIP_MISSING.value)

    def test_advance_locks_designations(self, api):
        """PRD §3.6: "When the estate advances from INVENTORIED to
        DISTRIBUTING, every PROPOSED designation on the estate is
        system-moved to LOCKED."

        Claim: after INVENTORIED -> DISTRIBUTING, designation status
        is LOCKED.
        """
        bundle = setup_distributing()
        estate = bundle["estate"]
        exec_h = bundle["executor_headers"]
        # Fetch designations.
        list_resp = api_client.list_designations(estate["id"], exec_h)
        body = list_resp.json()
        rows = body.get("data") or []
        assert rows, "Setup failed: no designations to inspect"
        for d in rows:
            assert d["status"] == "LOCKED", (
                f"designation must be LOCKED after DISTRIBUTING, "
                f"got {d['status']!r}"
            )


class TestDistributionExecute:

    def test_execute_requires_actual_matches_planned(self, api):
        """PRD §3.11: "actual_amount_cents must equal
        planned_amount_cents exactly — there is no drift permitted
        — else ERR_DISTRIBUTION_DRIFT."

        Claim: PLANNED -> EXECUTED with actual != planned ->
        ERR_DISTRIBUTION_DRIFT.
        """
        bundle = setup_distributing()
        estate = bundle["estate"]
        exec_h = bundle["executor_headers"]
        # Fetch a Distribution.
        list_resp = api_client.list_distributions(estate["id"], exec_h)
        dist = (list_resp.json().get("data") or [])[0]
        # Supply an actual one cent less.
        resp = api_client.transition_distribution(
            estate["id"], dist["id"],
            distribution_state_payload(
                "EXECUTED",
                actual_amount_cents=dist["planned_amount_cents"] - 1,
            ),
            exec_h,
        )
        validate_error(resp, ApiErrorId.ERR_DISTRIBUTION_DRIFT.value)

    def test_execute_at_match_succeeds(self, api):
        """PRD §3.11: "On success, executed_at is set to the moment
        of the transition."

        Claim: actual = planned -> 200 with status=EXECUTED and
        executed_at set.
        """
        bundle = setup_distributing()
        estate = bundle["estate"]
        exec_h = bundle["executor_headers"]
        list_resp = api_client.list_distributions(estate["id"], exec_h)
        dist = (list_resp.json().get("data") or [])[0]
        resp = api_client.transition_distribution(
            estate["id"], dist["id"],
            distribution_state_payload(
                "EXECUTED",
                actual_amount_cents=dist["planned_amount_cents"],
            ),
            exec_h,
        )
        updated = validate_success(resp)
        assert updated["status"] == "EXECUTED"
        assert updated.get("executed_at"), (
            "executed_at must be set on EXECUTED"
        )

    def test_execute_requires_actual_amount(self, api):
        """PRD §3.11: "an actual_amount_cents non-negative integer
        to be supplied (else ERR_BAD_REQUEST)".

        Claim: PLANNED -> EXECUTED without actual_amount_cents ->
        ERR_BAD_REQUEST.
        """
        bundle = setup_distributing()
        estate = bundle["estate"]
        exec_h = bundle["executor_headers"]
        list_resp = api_client.list_distributions(estate["id"], exec_h)
        dist = (list_resp.json().get("data") or [])[0]
        resp = api_client.transition_distribution(
            estate["id"], dist["id"],
            distribution_state_payload("EXECUTED"),
            exec_h,
        )
        validate_error(resp, ApiErrorId.ERR_BAD_REQUEST.value)


class TestAssetToDistributed:

    def test_asset_distributed_requires_locked_designation_for_beneficiary(
        self, api,
    ):
        """PRD §3.11: "requires the supplied distribution to belong
        to a beneficiary that is in fact LOCKED against this asset;
        otherwise it fails with ERR_INVALID_STATE or
        ERR_DESIGNATION_MISMATCH."

        Claim: when the supplied distribution_id refers to a
        distribution whose beneficiary has no LOCKED designation on
        this asset -> ERR_DESIGNATION_MISMATCH.

        Setup: two assets A and B; B1 LOCKED on asset A only; B2
        LOCKED on asset B only. Distribution for B2 references its
        own beneficiary. Attempt to mark asset A as DISTRIBUTED
        with B2's distribution_id -> mismatch.
        """
        bundle = setup_distributing(
            bond_amount_cents=10_000_000,
            assets=[
                {"asset_class": "FINANCIAL",
                 "declared_value_cents": 1000,
                 "appraised_value_cents": 1000},
                {"asset_class": "FINANCIAL",
                 "declared_value_cents": 2000,
                 "appraised_value_cents": 2000},
            ],
            beneficiary_shares=[
                {"asset_index": 0, "is_minor": False,
                 "share_basis_points": 10000, "priority_rank": 1},
                {"asset_index": 1, "is_minor": False,
                 "share_basis_points": 10000, "priority_rank": 1},
            ],
        )
        estate = bundle["estate"]
        exec_h = bundle["executor_headers"]
        beneficiaries = bundle["beneficiaries"]
        assets = bundle["appraised_assets"]
        # List distributions.
        list_resp = api_client.list_distributions(estate["id"], exec_h)
        dists = list_resp.json().get("data") or []
        # Identify the distribution for beneficiaries[1] (the one on
        # asset[1]).
        dist_b2 = next(
            d for d in dists
            if d["beneficiary_id"] == beneficiaries[1]["id"]
        )
        # Execute it.
        api_client.transition_distribution(
            estate["id"], dist_b2["id"],
            distribution_state_payload(
                "EXECUTED",
                actual_amount_cents=dist_b2["planned_amount_cents"],
            ),
            exec_h,
        )
        # Now attempt to mark asset[0] DISTRIBUTED using dist_b2's
        # id -> the LOCKED designation on asset[0] is for
        # beneficiaries[0], not beneficiaries[1], so this is a
        # mismatch.
        resp = api_client.transition_asset(
            estate["id"], assets[0]["id"],
            asset_state_payload("DISTRIBUTED",
                                distribution_id=dist_b2["id"]),
            exec_h,
        )
        # PRD pins ERR_DESIGNATION_MISMATCH for the mismatch path;
        # ERR_INVALID_STATE is the alternative for upstream
        # preconditions. Both are PRD-faithful for this specific
        # mismatch — we tolerate both as the prose is "OR".
        validate_error_is_one_of(resp, [
            ApiErrorId.ERR_DESIGNATION_MISMATCH.value,
            ApiErrorId.ERR_INVALID_STATE.value,
        ])


class TestDistributionReverse:

    def test_reverse_executed_clears_asset_distribution_id(self, api):
        """PRD §3.11: "On reversal, any Asset whose distribution_id
        references this distribution reverts to APPRAISED and has
        its distribution_id cleared back to null."

        Claim: a REVERSED distribution reverts its target Asset to
        APPRAISED with distribution_id=null.
        """
        bundle = setup_executed_distribution_for_reverse()
        estate = bundle["estate"]
        asset = bundle["asset"]
        distribution = bundle["distribution"]
        # Reverse via CourtClerk.
        resp = api_client.transition_distribution(
            estate["id"], distribution["id"],
            distribution_state_payload("REVERSED"),
            TEST_USERS["court_clerk_headers"],
        )
        reversed_dist = validate_success(resp)
        assert reversed_dist["status"] == "REVERSED"
        # Re-read asset.
        a_after = get_success_data(
            api_client.get_asset(
                estate["id"], asset["id"],
                TEST_USERS["court_clerk_headers"],
            ),
        )
        assert a_after["status"] == "APPRAISED", (
            f"asset must revert to APPRAISED on distribution reverse, "
            f"got {a_after['status']!r}"
        )
        assert a_after.get("distribution_id") in (None, ""), (
            f"distribution_id must clear to null, got "
            f"{a_after.get('distribution_id')!r}"
        )


class TestBeneficiaryDisclaim:

    def test_disclaim_self_only(self, api):
        """PRD §2.1: "any self-only operation (such as disclaiming
        one's own interest) requires that X-User-ID match
        Beneficiary.id."

        Claim: a Beneficiary attempting to disclaim another
        Beneficiary -> ERR_FORBIDDEN (or ERR_NOT_FOUND if the
        implementation hides the row).
        """
        bundle = setup_inventoried_with_two_designations()
        estate = bundle["estate"]
        b1 = bundle["beneficiaries"][0]
        b2 = bundle["beneficiaries"][1]
        # Sign as b1, try to disclaim b2.
        h_b1 = make_beneficiary_headers(b1["id"])
        resp = api_client.transition_beneficiary(
            estate["id"], b2["id"],
            beneficiary_state_payload("DISCLAIMED"),
            h_b1,
        )
        validate_error_is_one_of(resp, [
            ApiErrorId.ERR_FORBIDDEN.value,
            ApiErrorId.ERR_NOT_FOUND.value,
        ])

    def test_disclaim_voids_proposed_designations(self, api):
        """PRD §3.9: "Disclaim cascades through
        BeneficiaryDesignation: every designation referencing this
        beneficiary in PROPOSED or LOCKED is moved to VOIDED."

        Claim: after self-disclaim, the disclaiming beneficiary's
        PROPOSED designations are VOIDED.
        """
        bundle = setup_disclaimed_beneficiary_blocks_distributing()
        estate = bundle["estate"]
        ben = bundle["beneficiary"]
        d = bundle["designation"]
        h_b = make_beneficiary_headers(ben["id"])
        # Disclaim — estate is INVENTORIED, no EXECUTED distribution
        # for this beneficiary, so disclaim is allowed.
        resp = api_client.transition_beneficiary(
            estate["id"], ben["id"],
            beneficiary_state_payload("DISCLAIMED"),
            h_b,
        )
        validate_success(resp)
        # Re-read designation.
        d_after = get_success_data(
            api_client.get_designation(
                estate["id"], d["id"],
                TEST_USERS["court_clerk_headers"],
            ),
        )
        assert d_after["status"] == "VOIDED", (
            f"designation must be VOIDED after disclaim, got "
            f"{d_after['status']!r}"
        )
