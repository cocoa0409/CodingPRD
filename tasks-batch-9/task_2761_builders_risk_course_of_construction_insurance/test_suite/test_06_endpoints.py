"""Endpoint behaviour of the builders risk course-of-construction service.

Every scenario below is assembled from an empty database through the endpoints
the contract publishes, against the pre-set logical clock of 2026-08-01.
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import TEST_USERS, factories, fixtures
from test_helpers.constants import same_instant

UW = TEST_USERS["underwriter_headers"]
UM = TEST_USERS["manager_headers"]
RE = TEST_USERS["risk_engineer_headers"]
CA = TEST_USERS["claim_adjuster_headers"]
CA2 = TEST_USERS["claim_adjuster_2_headers"]

# A FIRE_RESISTIVE / NEW_CONSTRUCTION project in INLAND with a $4,000,000 hard
# cost: construction 6 + zone 0 + value 0 + schedule 0 + kind 0 + claims 0, so
# the submission-basis index reads 6 and the project screens ELIGIBLE.
CEDAR_PROJECT = {
    "name": "Cedar Mills Warehouse",
    "site_address": "12 Mill Rd, Cedar",
    "construction_type": "FIRE_RESISTIVE",
    "project_kind": "NEW_CONSTRUCTION",
    "hard_cost_value_cents": 400000000,
    "cat_zone": "INLAND",
    "planned_start_date": "2026-09-01T00:00:00Z",
    "projected_completion_date": "2027-03-01T00:00:00Z",
    "engineering_grade": "A",
}

# The half-open term 2026-09-01 .. 2027-03-20 is 200 whole days.
CEDAR_POLICY = {
    "term_start_date": "2026-09-01T00:00:00Z",
    "term_end_date": "2027-03-20T00:00:00Z",
    "deductible_tier": "STANDARD_25K",
    "limit_cents": 200000000,
    "daily_delay_rate_cents": 0,
}


class TestCoverageScheduleEditing:
    def test_patch_is_bounded_by_the_collective_limit_and_freezes_at_quote(self, api):
        """A patch may revise sublimit_cents, condition_code, or both; the sum of
        sublimit_cents over the policy's ACTIVE parts counting the new value being
        patched must not exceed limit_cents, available_cents is recomputed as
        sublimit_cents minus eroded_cents, and the schedule is editable only while
        the policy is DRAFT or REFERRED.

        Design: Corner/endpoints/corner_patching_a_sublimit_is_bounded_by_the_limit_and_frozen_at_quote
        """
        account = fixtures.draft_account(
            project_overrides=CEDAR_PROJECT,
            parts=(("MATERIALS_ON_SITE", 100000000), ("SOFT_COST", 50000000)),
            with_owner=False, **CEDAR_POLICY)
        materials = account.part("MATERIALS_ON_SITE")
        soft_cost = account.part("SOFT_COST")

        # 150000000 + 50000000 is exactly limit_cents, which the rule admits.
        patched = validate_success(api.patch_coverage_part(
            materials["id"], {"sublimit_cents": 150000000}, UW))
        assert patched["sublimit_cents"] == 150000000, patched
        assert patched["available_cents"] == 150000000, patched

        # One cent over the collective ceiling, though individually below limit_cents.
        validate_error(
            api.patch_coverage_part(
                materials["id"], {"sublimit_cents": 150000001}, UW),
            "ERR_SUBLIMIT_EXCEEDS_LIMIT", expected_status=422)

        conditioned = validate_success(api.patch_coverage_part(
            materials["id"], {"condition_code": "APPROVED_NOTICE_REQUIRED"}, UW))
        assert conditioned["condition_code"] == "APPROVED_NOTICE_REQUIRED", conditioned
        assert conditioned["sublimit_cents"] == 150000000, conditioned

        # base 4000 units x 80 = 320000, no cat, no duration load,
        # soft cost 50000000 / 100000 x 60 = 30000, no renovation, no credit.
        quoted = validate_success(api.quote_policy(account.policy_id, UW))
        assert quoted["status"] == "QUOTED", quoted
        assert quoted["quoted_premium_cents"] == 350000, quoted

        validate_error(
            api.patch_coverage_part(
                materials["id"], {"sublimit_cents": 120000000}, UW),
            "ERR_INVALID_POLICY_STATE", expected_status=409)

        frozen = validate_success(api.get_coverage_part(materials["id"], UW))
        assert frozen["sublimit_cents"] == 150000000, frozen
        assert frozen["condition_code"] == "APPROVED_NOTICE_REQUIRED", frozen
        untouched = validate_success(api.get_coverage_part(soft_cost["id"], UW))
        assert untouched["sublimit_cents"] == 50000000, untouched
        assert untouched["condition_code"] == "NONE", untouched


class TestPremiumSummary:
    def test_summary_is_a_projection_over_the_append_only_ledger(self, api):
        """The reconciliation view reports ledger_sum_cents as the signed sum of every
        PremiumTransaction row of the policy, transaction_count as the number of those
        rows, extension_ap_total_cents as the signed sum of the EXTENSION_AP and
        EXTENSION_AP_REVERSAL rows only, return_premium_cents reading 0 for as long as
        the policy is not CANCELLED, and balanced as the statement that
        ledger_sum_cents equals written_premium_cents.

        Design: Corner/endpoints/corner_premium_summary_reconciles_the_ledger_against_the_written_premium
        """
        account = fixtures.in_force_account(
            project_overrides=CEDAR_PROJECT,
            parts=(("MATERIALS_ON_SITE", 100000000),), **CEDAR_POLICY)
        assert account.policy["quoted_premium_cents"] == 320000, account.policy

        # daily base round_half_up(320000 / 200) == 1600; the cumulative ratio
        # 20 / 200 sits exactly on the first band, so slip_factor is 1.00 and the
        # additional premium is 1600 x 20 == 32000.
        endorsement = fixtures.file_endorsement(account, 20)
        assert same_instant(
            endorsement["revised_completion_date"], "2027-03-21T00:00:00Z"), endorsement
        assert float(endorsement["slip_factor"]) == 1.0, endorsement
        assert endorsement["additional_premium_cents"] == 32000, endorsement

        decided = fixtures.decide_endorsement(account, endorsement, "APPROVE", headers=UM)
        assert decided["status"] == "APPROVED", decided

        policy = validate_success(api.get_policy(account.policy_id, UW))
        assert policy["cumulative_extension_days"] == 20, policy
        assert same_instant(policy["term_end_date"], "2027-04-09T00:00:00Z"), policy
        assert same_instant(
            policy["adjusted_completion_date"], "2027-03-21T00:00:00Z"), policy
        assert policy["written_premium_cents"] == 352000, policy

        summary = validate_success(api.get_premium_summary(account.policy_id, UM))
        assert summary["quoted_premium_cents"] == 320000, summary
        assert summary["written_premium_cents"] == 352000, summary
        assert summary["ledger_sum_cents"] == 352000, summary
        assert summary["transaction_count"] == 2, summary
        assert summary["extension_ap_total_cents"] == 32000, summary
        assert summary["return_premium_cents"] == 0, summary
        assert summary["balanced"] is True, summary

        rows, meta = validate_paginated(
            api.list_policy_premium_transactions(account.policy_id, UW))
        assert meta["total_count"] == 2, meta
        initial, extension = rows[0], rows[1]
        assert initial["sequence_no"] == 1, initial
        assert initial["txn_type"] == "INITIAL", initial
        assert initial["amount_cents"] == 320000, initial
        assert same_instant(initial["effective_date"], "2026-09-01T00:00:00Z"), initial
        assert extension["sequence_no"] == 2, extension
        assert extension["txn_type"] == "EXTENSION_AP", extension
        assert extension["amount_cents"] == 32000, extension
        # The additional premium takes effect at the pre-extension term_end_date.
        assert same_instant(extension["effective_date"], "2027-03-20T00:00:00Z"), extension

        filtered, filtered_meta = validate_paginated(
            api.list_policy_premium_transactions(
                account.policy_id, UW, params={"txn_type": "EXTENSION_AP"}))
        assert filtered_meta["total_count"] == 1, filtered_meta
        assert filtered[0]["amount_cents"] == 32000, filtered


class TestClockAdvance:
    def test_the_sweep_is_a_no_op_until_the_term_end_is_reached_and_never_repeats(self, api):
        """Expiry happens when an operator advances the clock to or past a policy's
        term_end_date: every policy that is IN_FORCE and whose term_end_date is at or
        before the new clock value moves IN_FORCE to EXPIRED, and the response reports
        expired_policy_count, closed_coverage_part_count, released_assignment_count
        and lapsed_endorsement_count.

        Design: Corner/endpoints/corner_clock_advance_reports_zero_counts_until_the_term_end_is_reached
        """
        account = fixtures.in_force_account(
            project_overrides=CEDAR_PROJECT,
            parts=(("MATERIALS_ON_SITE", 100000000),), **CEDAR_POLICY)
        part = account.part("MATERIALS_ON_SITE")
        facility = fixtures.register_facility(
            name="Northside Warehouse", distance_from_site_miles=12,
            aggregate_capacity_cents=500000000)
        assignment = fixtures.assign_storage(
            account, facility, 5000000,
            "2026-09-01T00:00:00Z", "2027-03-01T00:00:00Z", headers=RE)
        endorsement = fixtures.file_endorsement(account, 20)
        assert endorsement["status"] == "REQUESTED", endorsement

        # One day short of term_end_date the sweep must touch nothing at all.
        early = validate_success(api.set_clock("2027-03-19T00:00:00Z", UW))
        assert early["expired_policy_count"] == 0, early
        assert early["closed_coverage_part_count"] == 0, early
        assert early["released_assignment_count"] == 0, early
        assert early["lapsed_endorsement_count"] == 0, early
        assert validate_success(
            api.get_policy(account.policy_id, UW))["status"] == "IN_FORCE"
        assert validate_success(
            api.get_storage_assignment(assignment["id"], UW))["status"] == "APPROVED"
        assert validate_success(
            api.get_facility(facility["id"], RE))["committed_value_cents"] == 5000000

        # The comparison is term_end_date <= current_utc, so equality expires.
        sweep = validate_success(api.set_clock("2027-03-20T00:00:00Z", UW))
        assert sweep["expired_policy_count"] == 1, sweep
        assert sweep["closed_coverage_part_count"] == 1, sweep
        assert sweep["released_assignment_count"] == 1, sweep
        assert sweep["lapsed_endorsement_count"] == 1, sweep

        expired = validate_success(api.get_policy(account.policy_id, UW))
        assert expired["status"] == "EXPIRED", expired
        closed = validate_success(api.get_coverage_part(part["id"], UW))
        assert closed["status"] == "CLOSED", closed
        released = validate_success(api.get_storage_assignment(assignment["id"], UW))
        assert released["status"] == "RELEASED", released
        assert released["release_reason"] == "POLICY_EXPIRY", released
        assert same_instant(released["released_at"], "2027-03-20T00:00:00Z"), released
        lapsed = validate_success(
            api.get_extension_endorsement(endorsement["id"], UW))
        assert lapsed["status"] == "LAPSED", lapsed
        assert validate_success(
            api.get_facility(facility["id"], RE))["committed_value_cents"] == 0

        # Nothing is left in a sweepable state, so the repeated call reports zeros.
        again = validate_success(api.set_clock("2027-03-20T00:00:00Z", UW))
        assert again["expired_policy_count"] == 0, again
        assert again["closed_coverage_part_count"] == 0, again
        assert again["released_assignment_count"] == 0, again
        assert again["lapsed_endorsement_count"] == 0, again
        assert validate_success(
            api.get_policy(account.policy_id, UW))["status"] == "EXPIRED"
        assert validate_success(
            api.get_storage_assignment(assignment["id"], UW))["status"] == "RELEASED"


class TestFacilityReinstatement:
    def test_suspension_blocks_new_stock_and_reinstatement_restores_it(self, api):
        """A facility may only be suspended or reactivated, a new assignment requires
        the facility to be ACTIVE, and suspending a facility leaves the assignments
        already approved against it untouched.

        Design: Corner/endpoints/corner_reinstating_a_suspended_facility_restores_its_ability_to_take_stock
        """
        account = fixtures.in_force_account(
            project_overrides=CEDAR_PROJECT,
            parts=(("MATERIALS_ON_SITE", 100000000),
                   ("TEMPORARY_STORAGE", 20000000)), **CEDAR_POLICY)
        facility = fixtures.register_facility(
            name="Northside Warehouse", distance_from_site_miles=12,
            aggregate_capacity_cents=500000000)
        first = fixtures.assign_storage(
            account, facility, 5000000,
            "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z")
        assert first["status"] == "APPROVED", first
        assert validate_success(
            api.get_facility(facility["id"], RE))["committed_value_cents"] == 5000000

        suspended = fixtures.suspend_facility(facility)
        assert suspended["status"] == "SUSPENDED", suspended
        # Suspension is forward-looking: the committed value and the live
        # assignment both survive it untouched.
        assert suspended["committed_value_cents"] == 5000000, suspended
        held = validate_success(api.get_storage_assignment(first["id"], UW))
        assert held["status"] == "APPROVED", held
        assert held["stored_value_cents"] == 5000000, held

        blocked = api.create_storage_assignment(
            factories.create_storage_assignment_payload(
                account.policy_id, facility["id"], 3000000,
                "2026-10-01T00:00:00Z", "2026-11-01T00:00:00Z"), UW)
        validate_error(blocked, "ERR_FACILITY_SUSPENDED", expected_status=409)

        reinstated = fixtures.reinstate_facility(facility)
        assert reinstated["status"] == "ACTIVE", reinstated
        assert reinstated["committed_value_cents"] == 5000000, reinstated

        second = fixtures.assign_storage(
            account, facility, 3000000,
            "2026-10-01T00:00:00Z", "2026-11-01T00:00:00Z")
        assert second["status"] == "APPROVED", second
        assert validate_success(
            api.get_facility(facility["id"], RE))["committed_value_cents"] == 8000000

        data, meta = validate_paginated(
            api.list_facility_storage_assignments(facility["id"], RE))
        assert meta["total_count"] == 2, meta
        assert {row["id"] for row in data} == {first["id"], second["id"]}, data
        scoped, scoped_meta = validate_paginated(api.list_facility_storage_assignments(
            facility["id"], RE, params={"status": "APPROVED"}))
        assert scoped_meta["total_count"] == 2, scoped_meta
        assert all(row["status"] == "APPROVED" for row in scoped), scoped


class TestLossPaymentPayeeLink:
    def test_two_payees_share_one_indemnity_and_the_reverse_lookup_splits_by_link(self, api):
        """Each loss payment records the payee_interest_id it was made to, the payment
        collection may be filtered by claim_id and by payee_interest_id, and a claim
        turns PAID and CLOSED once paid_cents reaches indemnity_cents.

        Design: Corner/endpoints/corner_loss_payments_link_a_claim_to_one_payee_and_split_by_that_link
        """
        account = fixtures.draft_account(
            project_overrides=CEDAR_PROJECT, with_owner=False,
            parts=(("MATERIALS_ON_SITE", 60000000),), **CEDAR_POLICY)
        # OWNER 60 + GENERAL_CONTRACTOR 40 sum to exactly 100, which is what
        # binding demands; the lender holds a 0% interest but is still payable.
        owner = fixtures.add_interest(
            account, party_role="OWNER", insurable_interest_pct=60,
            party_name="Cedar Mills Owner LLC", loss_payee_priority=1)
        contractor = fixtures.add_interest(
            account, party_role="GENERAL_CONTRACTOR", insurable_interest_pct=40,
            party_name="Harrow Build Co", loss_payee_priority=2)
        lender = fixtures.add_interest(
            account, party_role="LENDER", insurable_interest_pct=0,
            party_name="First Cedar Bank", loss_payee_priority=3)
        for interest in (owner, contractor, lender):
            fixtures.acknowledge_interest(account, interest)
        fixtures.incept_account(fixtures.bind_account(fixtures.quote_account(account)))
        part = account.part("MATERIALS_ON_SITE")

        # 15000000 gross less the STANDARD_25K occurrence deductible of 2500000.
        claim = fixtures.adjusted_claim(
            account, [factories.loss_item("MATERIALS_ON_SITE", 15000000)],
            loss_date="2026-11-15T00:00:00Z")
        assert claim["indemnity_cents"] == 12500000, claim
        claim = fixtures.settle_claim(claim, headers=CA2)

        first = fixtures.issue_payment(
            account, claim, "MATERIALS_ON_SITE", 7500000, payee=owner)
        assert first["payee_interest_id"] == owner["id"], first
        assert first["status"] == "ISSUED", first

        midway = validate_success(api.get_claim(claim["id"], CA))
        assert midway["payment_status"] == "PARTIALLY_PAID", midway
        assert midway["paid_cents"] == 7500000, midway

        second = fixtures.issue_payment(
            account, midway, "MATERIALS_ON_SITE", 5000000, payee=lender)
        assert second["payee_interest_id"] == lender["id"], second
        assert second["status"] == "ISSUED", second

        for interest, expected_amount in ((owner, 7500000), (lender, 5000000)):
            rows, meta = validate_paginated(api.list_loss_payments(
                CA, params={"payee_interest_id": interest["id"]}))
            assert meta["total_count"] == 1, (interest["party_role"], meta)
            assert rows[0]["amount_cents"] == expected_amount, rows
        # The general contractor was never named on a payment, so its reverse
        # lookup is genuinely empty rather than sharing the owner's row.
        empty, empty_meta = validate_paginated(api.list_loss_payments(
            CA, params={"payee_interest_id": contractor["id"]}))
        assert empty_meta["total_count"] == 0, empty_meta
        assert empty == [], empty

        both, both_meta = validate_paginated(api.list_loss_payments(
            CA, params={"claim_id": claim["id"]}))
        assert both_meta["total_count"] == 2, both_meta
        assert {row["id"] for row in both} == {first["id"], second["id"]}, both
        assert all(row["status"] == "ISSUED" for row in both), both

        closed = validate_success(api.get_claim(claim["id"], CA))
        assert closed["paid_cents"] == 12500000, closed
        assert closed["outstanding_reserve_cents"] == 0, closed
        assert closed["payment_status"] == "PAID", closed
        assert closed["adjustment_status"] == "CLOSED", closed

        # Erosion is recorded against the coverage part, not against a payee.
        eroded = validate_success(api.get_coverage_part(part["id"], UW))
        assert eroded["eroded_cents"] == 12500000, eroded
        assert eroded["available_cents"] == 47500000, eroded
