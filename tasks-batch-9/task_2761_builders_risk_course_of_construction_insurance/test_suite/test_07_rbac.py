"""Role and ownership behaviour of the builders risk course-of-construction service.

Identity travels in the X-User-ID and X-User-Role headers of every request, so
each scenario below reaches the same endpoint under several identities and pins
which of them the contract admits.
"""
from prd_bench_local_runner.testing import (
    build_user_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    TEST_USERS,
    factories,
    fixtures,
    make_claim_adjuster_headers,
    make_loss_payee_headers,
    make_project_contact_headers,
)
from test_helpers.constants import same_instant

UW = TEST_USERS["underwriter_headers"]
UW2 = TEST_USERS["underwriter_2_headers"]
UM = TEST_USERS["manager_headers"]
UM2 = TEST_USERS["manager_2_headers"]
RE = TEST_USERS["risk_engineer_headers"]
CA = TEST_USERS["claim_adjuster_headers"]
CA2 = TEST_USERS["claim_adjuster_2_headers"]

# A FIRE_RESISTIVE / NEW_CONSTRUCTION project in INLAND with a $4,000,000 hard
# cost: the submission-basis index reads 6, so the project screens ELIGIBLE.
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


class TestAuthenticationBeforeAuthorization:
    def test_an_unknown_role_is_401_and_a_wrong_role_is_403_before_any_state_check(self, api):
        """Every request carries X-User-ID and X-User-Role; a missing or unrecognised
        role is ERR_UNAUTHENTICATED, a role outside the endpoint's list is
        ERR_UNAUTHORIZED, and authentication is checked first, authorization second,
        and only then existence, ownership and state.

        Design: Corner/rbac/corner_authentication_precedes_authorization_which_precedes_state
        """
        account = fixtures.draft_account(
            project_overrides=CEDAR_PROJECT, with_owner=False,
            parts=(("MATERIALS_ON_SITE", 100000000),), **CEDAR_POLICY)
        policy_id = account.policy_id

        # Layer one: the caller is not one of the six declared roles at all.
        validate_error(
            api.quote_policy(policy_id, build_user_headers("aud-001", "Auditor")),
            "ERR_UNAUTHENTICATED", expected_status=401)
        validate_error(
            api.quote_policy(
                policy_id, {"X-User-ID": "uw-001", "Content-Type": "application/json"}),
            "ERR_UNAUTHENTICATED", expected_status=401)
        validate_error(
            api.quote_policy(
                policy_id,
                {"X-User-Role": "Underwriter", "Content-Type": "application/json"}),
            "ERR_UNAUTHENTICATED", expected_status=401)

        # Layer two: a declared role that this endpoint does not list. There is no
        # hierarchical override, so the manager is refused a quote.
        validate_error(
            api.quote_policy(policy_id, UM),
            "ERR_UNAUTHORIZED", expected_status=403)
        validate_error(
            api.create_coverage_part(
                factories.create_coverage_part_payload(
                    policy_id, part_type="SOFT_COST", sublimit_cents=20000000), RE),
            "ERR_UNAUTHORIZED", expected_status=403)
        validate_error(
            api.create_facility(
                factories.create_facility_payload(
                    name="Rogue Depot", distance_from_site_miles=5,
                    aggregate_capacity_cents=100000000), CA),
            "ERR_UNAUTHORIZED", expected_status=403)
        validate_error(
            api.cancel_policy(
                policy_id,
                factories.cancel_policy_payload(
                    "INSURED_REQUEST", "2027-01-01T00:00:00Z"), UW),
            "ERR_UNAUTHORIZED", expected_status=403)

        # Layer two still wins where the state machine would also have refused:
        # the project has already been screened, and the policy is only DRAFT.
        validate_error(
            api.screen_project(
                account.project_id, factories.screen_project_payload(
                    engineering_grade="B"), UW),
            "ERR_UNAUTHORIZED", expected_status=403)
        validate_error(
            api.create_claim(
                factories.create_claim_payload(
                    policy_id, peril="FIRE", loss_date="2026-11-15T00:00:00Z"), UW),
            "ERR_UNAUTHORIZED", expected_status=403)

        # Layer three: the properly authenticated and authorised caller reaches
        # the state machine. 4000 units x 80 == 320000 with no other component,
        # because the refused SOFT_COST part was never created.
        quoted = validate_success(api.quote_policy(policy_id, UW))
        assert quoted["status"] == "QUOTED", quoted
        assert quoted["quoted_premium_cents"] == 320000, quoted

        parts, parts_meta = validate_paginated(
            api.list_policy_coverage_parts(policy_id, UW))
        assert parts_meta["total_count"] == 1, parts_meta
        assert parts[0]["part_type"] == "MATERIALS_ON_SITE", parts
        project = validate_success(api.get_project(account.project_id, UW))
        assert project["engineering_grade"] == "A", project
        _, facility_meta = validate_paginated(api.list_facilities(RE))
        assert facility_meta["total_count"] == 0, facility_meta


class TestSharedOperations:
    def test_each_shared_operation_admits_its_named_partner_and_nobody_else(self, api):
        """Several operations are shared between two roles: a project may be submitted
        by an Underwriter or an UnderwritingManager, the logical clock is open to any
        operator role, a storage assignment may be raised and released by an
        Underwriter or a RiskEngineer, a testing notice may be scheduled by a
        RiskEngineer or the owning ProjectContact, and settlement is open to a
        ClaimAdjuster or an UnderwritingManager.

        Design: Corner/rbac/corner_shared_operations_admit_both_partners_and_only_those_two
        """
        submitted = fixtures.submit_project(headers=UM, **{
            key: value for key, value in CEDAR_PROJECT.items()
            if key != "engineering_grade"})
        assert submitted["status"] == "SUBMITTED", submitted
        project = fixtures.screen_project(submitted, engineering_grade="A", headers=RE)
        account = fixtures.draft_account(
            project=project,
            parts=(("MATERIALS_ON_SITE", 100000000),
                   ("TEMPORARY_STORAGE", 20000000)), **CEDAR_POLICY)
        fixtures.bind_account(fixtures.quote_account(account))

        # The clock is an operational endpoint open to every operator role.
        clock = fixtures.set_clock("2026-09-01T00:00:00Z", CA)
        assert same_instant(clock["current_utc"], "2026-09-01T00:00:00Z"), clock
        account.policy = validate_success(api.incept_policy(account.policy_id, UW))
        account.refresh_parts()

        facility = fixtures.register_facility(
            name="Northside Warehouse", distance_from_site_miles=12,
            aggregate_capacity_cents=500000000)
        claim = fixtures.adjusted_claim(
            account, [factories.loss_item("MATERIALS_ON_SITE", 15000000)],
            loss_date="2026-11-15T00:00:00Z", headers=CA)
        assert claim["indemnity_cents"] == 12500000, claim

        assignment = fixtures.assign_storage(
            account, facility, 5000000,
            "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z", headers=UW)
        assert assignment["status"] == "APPROVED", assignment
        released = fixtures.release_storage(assignment, headers=RE)
        assert released["status"] == "RELEASED", released

        notice = fixtures.schedule_notice(
            account, "2026-10-05T08:00:00Z", "2026-10-05T17:00:00Z",
            system_type="HVAC",
            headers=make_project_contact_headers(account.project_id))
        assert notice["status"] == "SCHEDULED", notice
        # A ClaimAdjuster is neither partner on the notice endpoint.
        validate_error(
            api.create_testing_notice(
                factories.create_testing_notice_payload(
                    account.project_id, "2026-10-08T08:00:00Z",
                    "2026-10-08T17:00:00Z", system_type="ELEVATOR"), CA),
            "ERR_UNAUTHORIZED", expected_status=403)

        settled = validate_success(api.settle_claim(claim["id"], UM))
        assert settled["adjustment_status"] == "SETTLED", settled
        readable = validate_success(api.get_policy(account.policy_id, RE))
        assert readable["status"] == "IN_FORCE", readable

        notices, notices_meta = validate_paginated(
            api.list_project_testing_notices(account.project_id, RE))
        assert notices_meta["total_count"] == 1, notices_meta
        assert notices[0]["id"] == notice["id"], notices


ANNEX_PROJECT = dict(
    CEDAR_PROJECT, name="Cedar Mills Annex", site_address="14 Mill Rd, Cedar")


class TestEntityBackedOwnership:
    def test_a_valid_entity_backed_caller_may_not_act_on_a_sibling_row(self, api):
        """When X-User-Role is ProjectContact, X-User-ID is the id of the acting
        project and that contact may schedule a notice only when the payload's
        project_id equals X-User-ID and may read only that project's notices; when it
        is LossPayee, X-User-ID is the id of the acting interest and that payee may
        acknowledge only the interest whose id equals X-User-ID. Any attempt by an
        entity-backed role to act on or read a resource it does not own is rejected
        with ERR_NOT_RESOURCE_OWNER.

        Design: Corner/rbac/corner_entity_backed_roles_cannot_reach_across_to_a_sibling_row
        """
        account = fixtures.draft_account(
            project_overrides=CEDAR_PROJECT, with_owner=False, parts=(),
            **CEDAR_POLICY)
        sibling_project = fixtures.eligible_project(
            engineering_grade="A", **{
                key: value for key, value in ANNEX_PROJECT.items()
                if key != "engineering_grade"})
        owner = fixtures.add_interest(
            account, party_role="OWNER", insurable_interest_pct=60,
            party_name="Cedar Mills Owner LLC", loss_payee_priority=1)
        contractor = fixtures.add_interest(
            account, party_role="GENERAL_CONTRACTOR", insurable_interest_pct=40,
            party_name="Harrow Build Co", loss_payee_priority=2)

        # A well-formed LossPayee header is still the wrong holder for this row.
        validate_error(
            api.acknowledge_interest(
                contractor["id"], make_loss_payee_headers(owner["id"])),
            "ERR_NOT_RESOURCE_OWNER", expected_status=403)
        # Both projects exist and are ELIGIBLE; only the owning contact may act.
        validate_error(
            api.create_testing_notice(
                factories.create_testing_notice_payload(
                    account.project_id, "2026-10-05T08:00:00Z",
                    "2026-10-05T17:00:00Z", system_type="HVAC"),
                make_project_contact_headers(sibling_project["id"])),
            "ERR_NOT_RESOURCE_OWNER", expected_status=403)
        # The scoping covers the reverse-lookup read as well as the write.
        validate_error(
            api.list_project_testing_notices(
                sibling_project["id"],
                make_project_contact_headers(account.project_id)),
            "ERR_NOT_RESOURCE_OWNER", expected_status=403)

        acknowledged = validate_success(api.acknowledge_interest(
            contractor["id"], make_loss_payee_headers(contractor["id"])))
        assert acknowledged["acknowledgment_status"] == "ACKNOWLEDGED", acknowledged
        # Nothing has moved the clock, so the stamp is the initial logical time.
        assert same_instant(
            acknowledged["acknowledged_at"], "2026-08-01T00:00:00Z"), acknowledged

        notice = fixtures.schedule_notice(
            account, "2026-10-05T08:00:00Z", "2026-10-05T17:00:00Z",
            system_type="HVAC",
            headers=make_project_contact_headers(account.project_id))
        assert notice["status"] == "SCHEDULED", notice

        # The refused cross-row acknowledgement left the owner row alone.
        untouched = validate_success(api.get_named_insured_interest(owner["id"], UW))
        assert untouched["acknowledgment_status"] == "PENDING", untouched
        assert untouched["acknowledged_at"] is None, untouched
        notices, notices_meta = validate_paginated(
            api.list_project_testing_notices(account.project_id, RE))
        assert notices_meta["total_count"] == 1, notices_meta
        assert notices[0]["id"] == notice["id"], notices


class TestMakerChecker:
    def test_the_adjusting_and_requesting_users_are_refused_their_own_check(self, api):
        """Settlement is a checker step, so the acting X-User-ID must differ from the
        claim's adjusted_by_user_id, and an endorsement decision must be taken by a
        different X-User-ID than the requested_by_user_id; either breach is refused
        with ERR_SEGREGATION_OF_DUTIES.

        Design: Corner/rbac/corner_the_maker_may_not_check_its_own_settlement_or_endorsement
        """
        account = fixtures.in_force_account(
            project_overrides=CEDAR_PROJECT,
            parts=(("MATERIALS_ON_SITE", 100000000),), **CEDAR_POLICY)
        claim = fixtures.adjusted_claim(
            account, [factories.loss_item("MATERIALS_ON_SITE", 15000000)],
            loss_date="2026-11-15T00:00:00Z", headers=CA)
        assert claim["adjusted_by_user_id"] == "ca-001", claim
        assert claim["indemnity_cents"] == 12500000, claim
        endorsement = fixtures.file_endorsement(account, 20, headers=UW)
        assert endorsement["requested_by_user_id"] == "uw-001", endorsement
        # 32000 sits below the 500000 manager-only authority limit, so the
        # Underwriter role is itself permitted to decide this endorsement.
        assert endorsement["additional_premium_cents"] == 32000, endorsement

        validate_error(
            api.settle_claim(claim["id"], CA),
            "ERR_SEGREGATION_OF_DUTIES", expected_status=403)
        validate_error(
            api.decide_endorsement(endorsement["id"], {"decision": "APPROVE"}, UW),
            "ERR_SEGREGATION_OF_DUTIES", expected_status=403)

        settled = validate_success(api.settle_claim(claim["id"], CA2))
        assert settled["adjustment_status"] == "SETTLED", settled
        decided = validate_success(api.decide_endorsement(
            endorsement["id"], {"decision": "APPROVE"}, UW2))
        assert decided["status"] == "APPROVED", decided
        assert decided["decided_by_user_id"] == "uw-002", decided

        policy = validate_success(api.get_policy(account.policy_id, UW))
        assert policy["cumulative_extension_days"] == 20, policy
        assert same_instant(policy["term_end_date"], "2027-04-09T00:00:00Z"), policy
        assert same_instant(
            policy["adjusted_completion_date"], "2027-03-21T00:00:00Z"), policy
        assert policy["written_premium_cents"] == 352000, policy

        summary = validate_success(api.get_premium_summary(account.policy_id, UW))
        assert summary["transaction_count"] == 2, summary
        assert summary["extension_ap_total_cents"] == 32000, summary
        assert summary["balanced"] is True, summary


class TestVoidSegregation:
    def test_the_issuing_user_cannot_void_its_own_payment_even_as_a_manager(self, api):
        """A void must be taken by a different X-User-ID than the payment's
        created_by_user_id, refused with ERR_SEGREGATION_OF_DUTIES otherwise, and a
        void reverses the erosion it caused and returns the amount to the claim's
        outstanding reserve.

        Design: Corner/rbac/corner_void_is_refused_to_the_user_who_issued_the_payment
        """
        account = fixtures.in_force_account(
            project_overrides=CEDAR_PROJECT,
            parts=(("MATERIALS_ON_SITE", 60000000),), **CEDAR_POLICY)
        part = account.part("MATERIALS_ON_SITE")
        claim = fixtures.settled_claim(
            account, [factories.loss_item("MATERIALS_ON_SITE", 15000000)],
            loss_date="2026-11-15T00:00:00Z", headers=CA)
        assert claim["indemnity_cents"] == 12500000, claim

        # Roles are header-borne and identities are opaque, so the same physical
        # user may issue as a ClaimAdjuster and later present as a manager.
        payment = fixtures.issue_payment(
            account, claim, "MATERIALS_ON_SITE", 12500000,
            headers=make_claim_adjuster_headers("um-002"))
        assert payment["created_by_user_id"] == "um-002", payment
        assert payment["status"] == "ISSUED", payment

        validate_error(
            api.void_loss_payment(payment["id"], UM2),
            "ERR_SEGREGATION_OF_DUTIES", expected_status=403)
        still_issued = validate_success(api.get_loss_payment(payment["id"], UM))
        assert still_issued["status"] == "ISSUED", still_issued
        still_eroded = validate_success(api.get_coverage_part(part["id"], UW))
        assert still_eroded["eroded_cents"] == 12500000, still_eroded

        voided = validate_success(api.void_loss_payment(payment["id"], UM))
        assert voided["status"] == "VOIDED", voided
        assert voided["voided_by_user_id"] == "um-001", voided

        restored = validate_success(api.get_coverage_part(part["id"], UW))
        assert restored["eroded_cents"] == 0, restored
        assert restored["available_cents"] == 60000000, restored
        reopened_reserve = validate_success(api.get_claim(claim["id"], CA))
        assert reopened_reserve["paid_cents"] == 0, reopened_reserve
        assert reopened_reserve["outstanding_reserve_cents"] == 12500000, reopened_reserve
        assert reopened_reserve["payment_status"] == "UNPAID", reopened_reserve
        assert reopened_reserve["adjustment_status"] == "SETTLED", reopened_reserve
