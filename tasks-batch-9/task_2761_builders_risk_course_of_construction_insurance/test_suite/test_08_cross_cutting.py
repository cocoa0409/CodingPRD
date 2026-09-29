"""Cross-cutting behaviour: version guards, derived-field reconciliation and the
immediacy of every read that follows a write.

Each scenario is assembled from an empty database against the pre-set logical
clock of 2026-08-01.
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
# cost: construction 6 and nothing else, so the submission-basis index reads 6.
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

CEDAR_POLICY = {
    "term_start_date": "2026-09-01T00:00:00Z",
    "term_end_date": "2027-03-20T00:00:00Z",
    "deductible_tier": "STANDARD_25K",
    "limit_cents": 200000000,
    "daily_delay_rate_cents": 0,
}


def _project_inputs(overrides=None):
    """The creation payload only; engineering_grade belongs to the screening."""
    fields = dict(CEDAR_PROJECT, **(overrides or {}))
    return {key: value for key, value in fields.items() if key != "engineering_grade"}


class TestOptimisticConcurrency:
    def test_all_three_version_guards_reject_a_caller_one_version_behind(self, api):
        """Creating a policy carries expected_project_version and mismatch is
        ERR_STALE_PROJECT_VERSION, filing an extension endorsement carries
        expected_policy_version and mismatch is ERR_STALE_POLICY_VERSION, and issuing a
        loss payment carries expected_claim_version and mismatch is
        ERR_STALE_CLAIM_VERSION, each with HTTP 412.

        Design: Corner/cross_cutting_complexity_layers/corner_all_three_optimistic_concurrency_guards_reject_a_view_one_version_stale
        """
        submitted = fixtures.submit_project(**_project_inputs())
        assert submitted["version"] == 1, submitted
        project = fixtures.screen_project(submitted, engineering_grade="A", headers=RE)
        assert project["version"] == 2, project
        assert project["status"] == "ELIGIBLE", project
        assert project["submission_risk_score"] == 6, project

        # Guard one: the caller still holds the pre-screening view of the project.
        validate_error(
            api.create_policy(
                factories.create_policy_payload(
                    project["id"], project["version"] - 1, **CEDAR_POLICY), UW),
            "ERR_STALE_PROJECT_VERSION", expected_status=412)
        unchanged = validate_success(api.get_project(project["id"], UW))
        assert unchanged["version"] == 2, unchanged

        account = fixtures.draft_account(
            project=project, parts=(("MATERIALS_ON_SITE", 60000000),), **CEDAR_POLICY)
        fixtures.incept_account(fixtures.bind_account(fixtures.quote_account(account)))
        policy_version = account.policy["version"]

        # Guard two: inception has already moved the policy on by a version.
        validate_error(
            api.create_extension_endorsement(
                factories.create_endorsement_payload(
                    account.policy_id, policy_version - 1, 20,
                    "2027-03-21T00:00:00Z"), UW),
            "ERR_STALE_POLICY_VERSION", expected_status=412)
        endorsement = fixtures.file_endorsement(account, 20)
        assert endorsement["status"] == "REQUESTED", endorsement
        assert endorsement["additional_premium_cents"] == 32000, endorsement

        claim = fixtures.settled_claim(
            account, [factories.loss_item("MATERIALS_ON_SITE", 15000000)],
            loss_date="2026-11-15T00:00:00Z", headers=CA)
        assert claim["indemnity_cents"] == 12500000, claim

        # Guard three: settlement bumped the claim after the payer read it.
        validate_error(
            api.create_loss_payment(
                factories.create_loss_payment_payload(
                    claim["id"], claim["version"] - 1,
                    account.owner_interest["id"], "MATERIALS_ON_SITE", 5000000), CA),
            "ERR_STALE_CLAIM_VERSION", expected_status=412)
        payment = fixtures.issue_payment(
            account, claim, "MATERIALS_ON_SITE", 5000000)
        assert payment["status"] == "ISSUED", payment

        # None of the three rejected writes left a row behind.
        _, policies_meta = validate_paginated(
            api.list_project_policies(project["id"], UW))
        assert policies_meta["total_count"] == 1, policies_meta
        endorsements, endorsements_meta = validate_paginated(
            api.list_policy_extension_endorsements(account.policy_id, UW))
        assert endorsements_meta["total_count"] == 1, endorsements_meta
        assert endorsements[0]["status"] == "REQUESTED", endorsements
        assert endorsements[0]["additional_premium_cents"] == 32000, endorsements
        payments, payments_meta = validate_paginated(
            api.list_loss_payments(CA, params={"claim_id": claim["id"]}))
        assert payments_meta["total_count"] == 1, payments_meta
        assert payments[0]["amount_cents"] == 5000000, payments
        assert payments[0]["status"] == "ISSUED", payments

        partly_paid = validate_success(api.get_claim(claim["id"], CA))
        assert partly_paid["paid_cents"] == 5000000, partly_paid
        assert partly_paid["outstanding_reserve_cents"] == 7500000, partly_paid
        assert partly_paid["payment_status"] == "PARTIALLY_PAID", partly_paid


ANNEX_PROJECT = {"name": "Cedar Mills Annex", "site_address": "14 Mill Rd, Cedar",
                 "projected_completion_date": "2026-12-01T00:00:00Z"}
ANNEX_POLICY = dict(CEDAR_POLICY, term_end_date="2026-12-31T00:00:00Z")

STORAGE_PLAN = (("MATERIALS_ON_SITE", 100000000), ("TEMPORARY_STORAGE", 20000000))


class TestFacilityCommittedValue:
    def test_committed_value_is_re_derived_after_create_release_and_expiry(self, api):
        """committed_value_cents is the sum of stored_value_cents over the facility's
        APPROVED assignments; assignments belonging to other policies and other
        projects count in full because the warehouse is a shared resource, and a
        release — whether requested or driven by policy expiry — takes the assignment
        out of that sum.

        Design: Corner/cross_cutting_complexity_layers/corner_facility_committed_value_reconciles_across_create_release_and_expiry
        """
        first = fixtures.draft_account(
            project_overrides=CEDAR_PROJECT, parts=STORAGE_PLAN, **CEDAR_POLICY)
        fixtures.bind_account(fixtures.quote_account(first))
        second = fixtures.draft_account(
            project_overrides=dict(CEDAR_PROJECT, **ANNEX_PROJECT),
            parts=STORAGE_PLAN, **ANNEX_POLICY)
        fixtures.bind_account(fixtures.quote_account(second))

        fixtures.set_clock("2026-09-01T00:00:00Z")
        for account in (first, second):
            account.policy = validate_success(
                api.incept_policy(account.policy_id, UW))
            assert account.policy["status"] == "IN_FORCE", account.policy

        facility = fixtures.register_facility(
            name="Northside Warehouse", distance_from_site_miles=12,
            aggregate_capacity_cents=500000000)
        assert facility["committed_value_cents"] == 0, facility

        long_run = fixtures.assign_storage(
            first, facility, 5000000,
            "2026-09-01T00:00:00Z", "2027-03-01T00:00:00Z", headers=RE)
        short_run = fixtures.assign_storage(
            second, facility, 3000000,
            "2026-09-01T00:00:00Z", "2026-12-01T00:00:00Z", headers=RE)
        pooled = validate_success(api.get_facility(facility["id"], RE))
        assert pooled["committed_value_cents"] == 8000000, pooled

        released = fixtures.release_storage(long_run, headers=RE)
        assert released["status"] == "RELEASED", released
        assert released["release_reason"] == "MANUAL", released
        after_release = validate_success(api.get_facility(facility["id"], RE))
        assert after_release["committed_value_cents"] == 3000000, after_release

        # 2026-12-31 is the annex policy's term_end_date; the Cedar Mills policy
        # runs to 2027-03-20 and is untouched, so only one assignment is swept.
        sweep = fixtures.set_clock("2026-12-31T00:00:00Z")
        assert sweep["expired_policy_count"] == 1, sweep
        assert sweep["released_assignment_count"] == 1, sweep
        after_expiry = validate_success(api.get_facility(facility["id"], RE))
        assert after_expiry["committed_value_cents"] == 0, after_expiry
        assert validate_success(
            api.get_policy(first.policy_id, UW))["status"] == "IN_FORCE"

        swept = validate_success(api.get_storage_assignment(short_run["id"], RE))
        assert swept["status"] == "RELEASED", swept
        assert swept["release_reason"] == "POLICY_EXPIRY", swept
        assert same_instant(swept["released_at"], "2026-12-31T00:00:00Z"), swept
        by_hand = validate_success(api.get_storage_assignment(long_run["id"], RE))
        assert by_hand["release_reason"] == "MANUAL", by_hand
        assert same_instant(by_hand["released_at"], "2026-09-01T00:00:00Z"), by_hand

        _, live_meta = validate_paginated(api.list_facility_storage_assignments(
            facility["id"], RE, params={"status": "APPROVED"}))
        assert live_meta["total_count"] == 0, live_meta
        _, all_meta = validate_paginated(
            api.list_facility_storage_assignments(facility["id"], RE))
        assert all_meta["total_count"] == 2, all_meta


class TestImmediateConsistency:
    def test_no_read_lags_the_write_that_changed_a_derived_field(self, api):
        """Every derived field is recomputed as part of the write that changes it and is
        visible in that same response: binding stamps written_premium_cents and writes
        the INITIAL ledger row, a storage assignment updates the facility's
        committed_value_cents, and a payment erodes the coverage part, raises
        paid_cents and closes the claim.

        Design: Corner/consistency_model/corner_every_derived_field_is_current_in_the_same_response_that_changed_it
        """
        account = fixtures.draft_account(
            project_overrides=CEDAR_PROJECT,
            parts=(("MATERIALS_ON_SITE", 60000000),
                   ("TEMPORARY_STORAGE", 20000000)), **CEDAR_POLICY)
        quoted = validate_success(api.quote_policy(account.policy_id, UW))
        assert quoted["quoted_premium_cents"] == 320000, quoted

        # The bind response itself carries the written premium; no second read.
        bound = validate_success(api.bind_policy(account.policy_id, UW))
        assert bound["status"] == "BOUND", bound
        assert bound["written_premium_cents"] == 320000, bound
        account.policy = bound

        rows, rows_meta = validate_paginated(
            api.list_policy_premium_transactions(account.policy_id, UW))
        assert rows_meta["total_count"] == 1, rows_meta
        assert rows[0]["txn_type"] == "INITIAL", rows
        assert rows[0]["amount_cents"] == 320000, rows

        fixtures.set_clock("2026-09-01T00:00:00Z")
        account.policy = validate_success(api.incept_policy(account.policy_id, UW))
        account.refresh_parts()
        part = account.part("MATERIALS_ON_SITE")

        facility = fixtures.register_facility(
            name="Northside Warehouse", distance_from_site_miles=12,
            aggregate_capacity_cents=500000000)
        fixtures.assign_storage(
            account, facility, 4000000,
            "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z", headers=RE)
        committed = validate_success(api.get_facility(facility["id"], RE))
        assert committed["committed_value_cents"] == 4000000, committed

        adjusted = fixtures.adjusted_claim(
            account, [factories.loss_item("MATERIALS_ON_SITE", 15000000)],
            loss_date="2026-11-15T00:00:00Z", headers=CA)
        assert adjusted["indemnity_cents"] == 12500000, adjusted
        assert adjusted["outstanding_reserve_cents"] == 12500000, adjusted
        settled = fixtures.settle_claim(adjusted, headers=CA2)

        payment = fixtures.issue_payment(
            account, settled, "MATERIALS_ON_SITE", 12500000)
        assert payment["status"] == "ISSUED", payment

        # All four cascade hops are applied before the response is returned.
        closed = validate_success(api.get_claim(settled["id"], CA))
        assert closed["paid_cents"] == 12500000, closed
        assert closed["outstanding_reserve_cents"] == 0, closed
        assert closed["payment_status"] == "PAID", closed
        assert closed["adjustment_status"] == "CLOSED", closed

        eroded = validate_success(api.get_coverage_part(part["id"], UW))
        assert eroded["eroded_cents"] == 12500000, eroded
        assert eroded["available_cents"] == 47500000, eroded

        policy = validate_success(api.get_policy(account.policy_id, UM))
        assert policy["eroded_total_cents"] == 12500000, policy
        assert policy["written_premium_cents"] == 320000, policy
