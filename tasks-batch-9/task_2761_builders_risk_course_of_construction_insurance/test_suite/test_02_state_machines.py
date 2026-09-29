"""State-machine tests for the Builders Risk Course Of Construction API.

Every test here starts from an empty database and a logical clock reading
2026-08-01T00:00:00Z, and drives the lifecycles through the endpoints the PRD
publishes: project screening, the policy walk from draft to in force, the two
claim axes, endorsements, storage and the cancellation cascade.
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ApiErrorId, api_client
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    MANAGER_ID,
    TEST_USERS,
    UNDERWRITER_2_ID,
    UNDERWRITER_ID,
    make_project_contact_headers,
)

UW = TEST_USERS["underwriter_headers"]
UW2 = TEST_USERS["underwriter_2_headers"]
UM = TEST_USERS["manager_headers"]
UM2 = TEST_USERS["manager_2_headers"]
RE = TEST_USERS["risk_engineer_headers"]
CA = TEST_USERS["claim_adjuster_headers"]
CA2 = TEST_USERS["claim_adjuster_2_headers"]

HARBORLINE = {
    "name": "Harborline Terminal Expansion",
    "site_address": "410 Dock Rd, Newport",
    "construction_type": "NON_COMBUSTIBLE",
    "project_kind": "NEW_CONSTRUCTION",
    "hard_cost_value_cents": 2000000000,
    "cat_zone": "WIND_TIER_2",
    "planned_start_date": "2026-09-01T00:00:00Z",
    "projected_completion_date": "2027-06-01T00:00:00Z",
}


class TestInitialStates:
    def test_every_stateful_row_is_created_in_its_own_starting_state(self):
        """A project is submitted into SUBMITTED, a policy lands in DRAFT, a
        coverage part is ACTIVE on creation, an insured interest starts PENDING, a
        newly registered facility is ACTIVE, a storage commitment is raised
        APPROVED, a testing notice lands in SCHEDULED and a filed endorsement lands
        in REQUESTED.

        Design: Corner/state_machines/corner_every_entity_starts_in_its_declared_initial_state
        """
        project = validate_success(
            api_client.create_project(f.create_project_payload(**HARBORLINE), UW),
            expected_status=201)
        assert project["status"] == "SUBMITTED"
        assert validate_success(
            api_client.get_project(project["id"], UW))["status"] == "SUBMITTED"

        screened = fx.screen_project(project, engineering_grade="B")
        account = fx.Account(project=screened)

        policy = validate_success(api_client.create_policy(
            f.create_policy_payload(screened["id"], screened["version"]), UW),
            expected_status=201)
        assert policy["status"] == "DRAFT"
        assert validate_success(
            api_client.get_policy(policy["id"], UW))["status"] == "DRAFT"
        account.policy = policy

        part = validate_success(api_client.create_coverage_part(
            f.create_coverage_part_payload(
                policy["id"], part_type="MATERIALS_ON_SITE",
                sublimit_cents=1000000000), UW), expected_status=201)
        assert part["status"] == "ACTIVE"
        assert validate_success(
            api_client.get_coverage_part(part["id"], UW))["status"] == "ACTIVE"

        interest = validate_success(api_client.create_named_insured_interest(
            f.create_interest_payload(
                policy["id"], party_name="Harborline Owner LLC",
                party_role="OWNER", insurable_interest_pct=100), UW),
            expected_status=201)
        assert interest["acknowledgment_status"] == "PENDING"
        assert validate_success(api_client.get_named_insured_interest(
            interest["id"], UW))["acknowledgment_status"] == "PENDING"
        account.interests.append(interest)

        facility = validate_success(api_client.create_facility(
            f.create_facility_payload(
                name="Northgate Yard", site_code="NGY-01",
                distance_from_site_miles=22, aggregate_capacity_cents=900000000,
                protection_class="SPRINKLERED"), RE), expected_status=201)
        assert facility["status"] == "ACTIVE"
        assert validate_success(
            api_client.get_facility(facility["id"], RE))["status"] == "ACTIVE"

        notice = validate_success(api_client.create_testing_notice(
            f.create_testing_notice_payload(
                project["id"], "2027-01-05T00:00:00Z", "2027-01-08T00:00:00Z",
                system_type="SPRINKLER_HYDROSTATIC", water_charged=True,
                mitigation_plan_ref="MIT-1"), RE), expected_status=201)
        assert notice["status"] == "SCHEDULED"
        assert validate_success(
            api_client.get_testing_notice(notice["id"], RE))["status"] == "SCHEDULED"

        # Storage may only be committed once the policy is bound.
        fx.acknowledge_interest(account, interest)
        fx.quote_account(account)
        fx.bind_account(account)

        assignment = validate_success(api_client.create_storage_assignment(
            f.create_storage_assignment_payload(
                policy["id"], facility["id"], 100000000,
                "2026-10-01T00:00:00Z", "2026-11-01T00:00:00Z"), RE),
            expected_status=201)
        assert assignment["status"] == "APPROVED"
        assert validate_success(api_client.get_storage_assignment(
            assignment["id"], RE))["status"] == "APPROVED"

        # An endorsement may only be filed against a policy that is in force.
        fx.incept_account(account)
        endorsement = validate_success(api_client.create_extension_endorsement(
            f.create_endorsement_payload(
                policy["id"], account.policy["version"], 30,
                "2027-07-01T00:00:00Z"), UW), expected_status=201)
        assert endorsement["status"] == "REQUESTED"
        assert validate_success(api_client.get_extension_endorsement(
            endorsement["id"], UW))["status"] == "REQUESTED"


class TestOneShotTransitionsAreNotReplayable:
    def test_a_second_screen_and_a_second_acknowledgement_are_refused(self):
        """Screening moves a project SUBMITTED to ELIGIBLE or INELIGIBLE and a
        project in any other status is refused with ERR_INVALID_PROJECT_STATE;
        acknowledgement moves an interest PENDING to ACKNOWLEDGED and a second
        acknowledgement is refused with ERR_INVALID_INTEREST_STATE.

        Design: Corner/state_machines/corner_screening_twice_and_acknowledging_twice_are_rejected
        """
        account = fx.draft_account(parts=None, project_overrides=HARBORLINE)
        screened = account.project
        interest = account.owner_interest
        assert interest["acknowledgment_status"] == "ACKNOWLEDGED"

        # A replay is an error, not a no-op, and it does not re-score the project.
        validate_error(
            api_client.screen_project(
                screened["id"], f.screen_project_payload(engineering_grade="A"),
                RE),
            ApiErrorId.ERR_INVALID_PROJECT_STATE.value, expected_status=409)

        again = validate_success(api_client.get_project(screened["id"], RE))
        assert again["status"] == "ELIGIBLE"
        assert again["engineering_grade"] == "B"
        assert again["submission_risk_score"] == 28
        # The refused replay left the version exactly where the policy draft put it.
        assert again["version"] == screened["version"]

        validate_error(
            api_client.acknowledge_interest(
                interest["id"], fx.make_loss_payee_headers(interest["id"])),
            ApiErrorId.ERR_INVALID_INTEREST_STATE.value, expected_status=409)

        held = validate_success(
            api_client.get_named_insured_interest(interest["id"], UW))
        a.assert_named_insured_interest(held, acknowledgment_status="ACKNOWLEDGED")
        assert held["version"] == interest["version"]
        assert held["acknowledged_at"] == interest["acknowledged_at"]

class TestUnderwritingWalk:
    def test_quote_then_bind_then_incept_each_move_exactly_one_step(self):
        """Rating stores quoted_premium_cents and leaves written_premium_cents at 0;
        a successful bind moves QUOTED to BOUND, sets written_premium_cents equal to
        quoted_premium_cents and opens the ledger with sequence_no 1, txn_type
        INITIAL, amount_cents equal to quoted_premium_cents and effective_date equal
        to term_start_date; inception moves BOUND to IN_FORCE, moves the project to
        UNDER_CONSTRUCTION and raises its in_force_policy_count to 1.

        Design: Corner/state_machines/corner_policy_walks_draft_quoted_bound_in_force_with_each_stamp
        """
        account = fx.draft_account(
            parts=(("MATERIALS_ON_SITE", 1000000000),
                   ("SOFT_COST", 300000000),
                   ("DELAY_IN_COMPLETION", 250000000)),
            project_overrides=HARBORLINE)
        fx.set_clock("2026-09-01T00:00:00Z")

        fx.quote_account(account)
        a.assert_policy(account.policy, status="QUOTED")
        # base 2200000 + cat 396000 + duration 0 + soft 330000 == 2926000, less the
        # ELEVATED_100K credit of 175560.
        assert account.policy["quoted_premium_cents"] == 2750440
        assert account.policy["written_premium_cents"] == 0
        assert account.policy["quoted_by_user_id"] == UNDERWRITER_ID
        _, meta = validate_paginated(
            api_client.list_policy_premium_transactions(account.policy_id, UW))
        assert meta["total_count"] == 0

        fx.bind_account(account)
        assert account.policy["status"] == "BOUND"
        assert account.policy["written_premium_cents"] == 2750440
        rows, meta = validate_paginated(
            api_client.list_policy_premium_transactions(account.policy_id, UW))
        assert meta["total_count"] == 1
        a.assert_premium_transaction(rows[0], txn_type="INITIAL")
        assert rows[0]["sequence_no"] == 1
        assert rows[0]["amount_cents"] == 2750440
        assert rows[0]["effective_date"] == "2026-09-01T00:00:00Z"

        fx.incept_account(account)
        assert account.policy["status"] == "IN_FORCE"
        # Inception moves no money.
        assert account.policy["written_premium_cents"] == 2750440
        assert account.policy["quoted_premium_cents"] == 2750440
        _, meta = validate_paginated(
            api_client.list_policy_premium_transactions(account.policy_id, UW))
        assert meta["total_count"] == 1

        assert account.project["status"] == "UNDER_CONSTRUCTION"
        assert account.project["in_force_policy_count"] == 1

    def test_bind_is_refused_while_an_insured_interest_is_unacknowledged(self):
        """Binding requires every NamedInsuredInterest on the policy to be
        ACKNOWLEDGED, and an unacknowledged payee is refused with
        ERR_INTERESTS_NOT_ACKNOWLEDGED.

        Design: Corner/state_machines/corner_quote_and_bind_preconditions_each_fail_with_their_own_error
        """
        account = fx.draft_account(
            parts=(("SOFT_COST", 300000000),), with_owner=False,
            project_overrides=HARBORLINE)
        interest = fx.add_interest(account, party_role="OWNER",
                                   insurable_interest_pct=100)
        assert interest["acknowledgment_status"] == "PENDING"

        fx.schedule_part(account, "MATERIALS_ON_SITE", 1000000000)
        fx.quote_account(account)
        assert account.policy["status"] == "QUOTED"
        # base 2200000 + cat 396000 + duration 0 + soft 180000 == 2776000, less the
        # ELEVATED_100K credit of 166560.
        assert account.policy["quoted_premium_cents"] == 2609440

        validate_error(api_client.bind_policy(account.policy_id, UW),
                       ApiErrorId.ERR_INTERESTS_NOT_ACKNOWLEDGED.value,
                       expected_status=409)

        account.refresh_policy()
        assert account.policy["status"] == "QUOTED"
        assert account.policy["bound_at"] is None
        assert account.policy["written_premium_cents"] == 0
        # A failed bind appends no ledger row.
        _, meta = validate_paginated(
            api_client.list_policy_premium_transactions(account.policy_id, UW))
        assert meta["total_count"] == 0

class TestInceptionSideEffects:
    def test_inception_is_the_only_path_into_under_construction(self):
        """Inception moves the policy BOUND to IN_FORCE, moves its project ELIGIBLE
        to UNDER_CONSTRUCTION and raises in_force_policy_count by 1; substantial
        completion may only be declared on a project that is UNDER_CONSTRUCTION.

        Design: Corner/state_machines/corner_inception_bubbles_the_project_from_eligible_to_under_construction
        """
        account = fx.bound_account(
            parts=(("MATERIALS_ON_SITE", 1000000000),),
            project_overrides=HARBORLINE)
        before = account.refresh_project()
        assert before["status"] == "ELIGIBLE"
        assert before["in_force_policy_count"] == 0

        fx.set_clock("2026-10-15T00:00:00Z")
        site = make_project_contact_headers(account.project_id)

        # An ELIGIBLE project has not started construction.
        validate_error(
            api_client.declare_substantial_completion(
                account.project_id,
                f.substantial_completion_payload("2026-10-10T00:00:00Z"), site),
            ApiErrorId.ERR_INVALID_PROJECT_STATE.value, expected_status=409)
        assert account.refresh_project()["status"] == "ELIGIBLE"

        incepted = validate_success(
            api_client.incept_policy(account.policy_id, UW))
        assert incepted["status"] == "IN_FORCE"

        after = account.refresh_project()
        # Both figures are set by the inception, not by any direct project call.
        assert after["status"] == "UNDER_CONSTRUCTION"
        assert after["in_force_policy_count"] == 1

        done = validate_success(api_client.declare_substantial_completion(
            account.project_id,
            f.substantial_completion_payload("2026-10-10T00:00:00Z"), site))
        assert done["status"] == "SUBSTANTIALLY_COMPLETE"
        assert done["actual_substantial_completion_date"] == "2026-10-10T00:00:00Z"

        # Substantial completion does not end the policy.
        assert account.refresh_policy()["status"] == "IN_FORCE"


class TestTriggersOutsideTheCurrentState:
    def test_four_triggers_absent_from_the_current_state_are_each_refused(self):
        """A referral decision requires the policy to be REFERRED, settlement
        requires the claim to be ADJUSTED, reopening requires a CLOSED or DENIED
        claim and a resubmission requires the endorsement to be RETURNED_FOR_INFO;
        each refusal carries that entity's own state error.

        Design: Corner/state_machines/corner_triggers_absent_from_the_current_state_are_all_rejected
        """
        account = fx.in_force_account(
            parts=(("MATERIALS_ON_SITE", 1000000000),),
            project_overrides=HARBORLINE)
        claim = fx.report_claim(
            account, peril="FIRE", loss_date="2026-11-15T00:00:00Z",
            description="Formwork fire on level 3")
        endorsement = fx.file_endorsement(account, 30)
        assert endorsement["status"] == "REQUESTED"

        # The policy priced below the referral threshold, so it never was REFERRED.
        validate_error(
            api_client.referral_decision(
                account.policy_id,
                {"decision": "APPROVE", "referral_load_pct": 0.10}, UM),
            ApiErrorId.ERR_INVALID_POLICY_STATE.value, expected_status=409)

        validate_error(api_client.settle_claim(claim["id"], CA2),
                       ApiErrorId.ERR_INVALID_CLAIM_STATE.value,
                       expected_status=409)
        validate_error(api_client.reopen_claim(claim["id"], CA),
                       ApiErrorId.ERR_INVALID_CLAIM_STATE.value,
                       expected_status=409)

        validate_error(
            api_client.resubmit_endorsement(
                endorsement["id"],
                f.resubmit_endorsement_payload(20, "2027-06-21T00:00:00Z"), UW),
            ApiErrorId.ERR_INVALID_ENDORSEMENT_STATE.value, expected_status=409)

        held_policy = account.refresh_policy()
        assert held_policy["status"] == "IN_FORCE"
        assert held_policy["referral_load_pct"] == 0

        held_claim = validate_success(api_client.get_claim(claim["id"], CA))
        assert held_claim["adjustment_status"] == "REPORTED"
        assert held_claim["payment_status"] == "UNPAID"
        assert held_claim["reopen_count"] == 0
        assert held_claim["version"] == claim["version"]

        held_endorsement = validate_success(
            api_client.get_extension_endorsement(endorsement["id"], UW))
        assert held_endorsement["status"] == "REQUESTED"
        assert held_endorsement["requested_extension_days"] == 30
        assert held_endorsement["resubmission_count"] == 0
        assert held_endorsement["version"] == endorsement["version"]

        # None of the four rejections appended a ledger row.
        _, meta = validate_paginated(
            api_client.list_policy_premium_transactions(account.policy_id, UM))
        assert meta["total_count"] == 1

class TestDeclinedEndorsementLockdown:
    def test_a_declined_endorsement_admits_no_further_trigger(self):
        """DECLINED is terminal for an endorsement, the declined price stays on file,
        and a decline moves neither the policy term nor the premium ledger.

        Design: Corner/state_machines/corner_declined_endorsement_is_locked_against_every_further_trigger
        """
        account = fx.in_force_account(
            parts=(("MATERIALS_ON_SITE", 1000000000),
                   ("SOFT_COST", 300000000),
                   ("DELAY_IN_COMPLETION", 250000000)),
            project_overrides=HARBORLINE)
        endorsement = fx.file_endorsement(account, 30)
        # daily base round_half_up(2750440 / 302) == 9107; 30 / 302 == 0.0993 so the
        # slip factor is 1.00; round_half_up(9107 * 30) == 273210.
        assert endorsement["additional_premium_cents"] == 273210

        declined = fx.decide_endorsement(
            account, endorsement, decision="DECLINE", headers=UM)
        a.assert_extension_endorsement(declined, status="DECLINED")
        assert declined["decided_by_user_id"] == MANAGER_ID
        # The declined price remains on file.
        assert declined["additional_premium_cents"] == 273210

        validate_error(
            api_client.return_endorsement_for_info(
                endorsement["id"],
                {"info_request_note": "Send the revised programme"}, UM),
            ApiErrorId.ERR_INVALID_ENDORSEMENT_STATE.value, expected_status=409)
        validate_error(
            api_client.decide_endorsement(
                endorsement["id"], {"decision": "APPROVE"}, UM),
            ApiErrorId.ERR_INVALID_ENDORSEMENT_STATE.value, expected_status=409)
        validate_error(
            api_client.rescind_endorsement(endorsement["id"], UM2),
            ApiErrorId.ERR_INVALID_ENDORSEMENT_STATE.value, expected_status=409)

        held = validate_success(
            api_client.get_extension_endorsement(endorsement["id"], UW))
        assert held["status"] == "DECLINED"
        assert held["version"] == declined["version"]
        assert held["additional_premium_cents"] == 273210

        policy = account.refresh_policy()
        assert policy["term_end_date"] == "2027-06-30T00:00:00Z"
        assert policy["cumulative_extension_days"] == 0
        assert policy["adjusted_completion_date"] == "2027-06-01T00:00:00Z"
        assert policy["written_premium_cents"] == 2750440
        rows, meta = validate_paginated(
            api_client.list_policy_premium_transactions(account.policy_id, UM))
        assert meta["total_count"] == 1
        assert rows[0]["txn_type"] == "INITIAL"


class TestReopenCycle:
    def test_the_quote_reopen_quote_loop_clears_and_reprices_the_premium(self):
        """Reopening moves the policy QUOTED to DRAFT, clears quoted_premium_cents
        and quoted_by_user_id back to null, preserves referral_load_pct and makes
        the coverage schedule editable again, and the policy is rated from scratch on
        the next pass.

        Design: Corner/state_machines/corner_quoted_to_draft_reopen_cycle_clears_and_reprices_the_premium
        """
        account = fx.draft_account(
            parts=(("MATERIALS_ON_SITE", 1000000000), ("SOFT_COST", 300000000)),
            with_owner=False, project_overrides=HARBORLINE)
        opening_version = account.policy["version"]

        fx.quote_account(account, headers=UW2)
        assert account.policy["status"] == "QUOTED"
        # soft-cost load 300000000 / 100000 * 60 == 180000.
        assert account.policy["quoted_premium_cents"] == 2609440
        assert account.policy["quoted_by_user_id"] == UNDERWRITER_2_ID

        reopened = validate_success(api_client.reopen_policy(account.policy_id, UW))
        account.policy = reopened
        assert reopened["status"] == "DRAFT"
        assert reopened["quoted_premium_cents"] is None
        assert reopened["quoted_by_user_id"] is None
        assert reopened["referral_load_pct"] == 0
        assert reopened["written_premium_cents"] == 0

        # The schedule is editable again.
        fx.schedule_part(account, "DELAY_IN_COMPLETION", 250000000)
        fx.quote_account(account, headers=UW)
        assert account.policy["status"] == "QUOTED"
        # The extra 250000000 of soft-cost units adds 150000 gross, 141000 net of the
        # 6 per cent deductible credit: 2609440 + 141000 == 2750440.
        assert account.policy["quoted_premium_cents"] == 2750440
        # The second rating re-stamps the field the reopen cleared.
        assert account.policy["quoted_by_user_id"] == UNDERWRITER_ID

        parts, meta = validate_paginated(
            api_client.list_policy_coverage_parts(account.policy_id, UW))
        assert meta["total_count"] == 3
        assert {part["status"] for part in parts} == {"ACTIVE"}

        # The loop is not free: quote, reopen, part, quote.
        assert account.policy["version"] == opening_version + 4

CEDAR_MILLS = {
    "name": "Cedar Mills Warehouse",
    "site_address": "12 Mill Rd, Cedar",
    "construction_type": "FIRE_RESISTIVE",
    "project_kind": "NEW_CONSTRUCTION",
    "hard_cost_value_cents": 400000000,
    "cat_zone": "INLAND",
    "planned_start_date": "2026-09-01T00:00:00Z",
    "projected_completion_date": "2027-03-01T00:00:00Z",
}


class TestCrossEntityGuards:
    def test_the_state_of_another_entity_blocks_payment_and_storage(self):
        """A loss payment requires the claim to be ADJUSTED or SETTLED, so a claim
        still REPORTED pays nothing; a storage commitment is only admissible against
        a policy that is BOUND or IN_FORCE, so a DRAFT policy is refused. Neither
        refusal moves any money.

        Design: Corner/state_machines/corner_cross_entity_guards_block_payment_and_storage_before_any_money_check
        """
        live = fx.in_force_account(
            parts=(("MATERIALS_ON_SITE", 1000000000),),
            project_overrides=HARBORLINE)
        claim = fx.report_claim(
            live, peril="FIRE", loss_date="2026-11-15T00:00:00Z",
            description="Formwork fire on level 3")
        assert claim["adjustment_status"] == "REPORTED"

        draft = fx.draft_account(
            parts=(("TEMPORARY_STORAGE", 100000000),), with_owner=False,
            project_overrides=CEDAR_MILLS,
            term_end_date="2027-03-20T00:00:00Z",
            deductible_tier="STANDARD_25K", limit_cents=400000000,
            daily_delay_rate_cents=0)
        assert draft.policy["status"] == "DRAFT"

        facility = fx.register_facility(
            name="Northgate Yard", site_code="NGY-01",
            distance_from_site_miles=18, aggregate_capacity_cents=900000000,
            protection_class="SPRINKLERED")

        # The version declaration, the payee and the amount are all valid; the
        # claim's own state is what blocks the payment.
        validate_error(
            api_client.create_loss_payment(f.create_loss_payment_payload(
                claim["id"], claim["version"], live.owner_interest["id"],
                "MATERIALS_ON_SITE", 1000000), CA),
            ApiErrorId.ERR_INVALID_CLAIM_STATE.value, expected_status=409)

        held_claim = validate_success(api_client.get_claim(claim["id"], CA))
        assert held_claim["paid_cents"] == 0
        assert held_claim["payment_status"] == "UNPAID"
        assert held_claim["version"] == claim["version"]
        live.refresh_parts()
        assert live.part("MATERIALS_ON_SITE")["eroded_cents"] == 0
        assert live.refresh_policy()["eroded_total_cents"] == 0

        # The facility passes distance, capacity and status; the policy does not.
        validate_error(
            api_client.create_storage_assignment(
                f.create_storage_assignment_payload(
                    draft.policy_id, facility["id"], 50000000,
                    "2026-10-01T00:00:00Z", "2026-11-01T00:00:00Z"), UW),
            ApiErrorId.ERR_INVALID_POLICY_STATE.value, expected_status=409)

        assert validate_success(api_client.get_facility(
            facility["id"], RE))["committed_value_cents"] == 0
        _, meta = validate_paginated(
            api_client.list_facility_storage_assignments(facility["id"], RE))
        assert meta["total_count"] == 0


class TestCancellationCascade:
    def test_the_cascade_touches_only_the_non_terminal_children(self):
        """Cancellation closes every ACTIVE coverage part, releases every APPROVED
        storage assignment with release_reason POLICY_CANCELLATION, recomputes each
        affected facility's committed_value_cents and returns the project's
        in_force_policy_count to 0, while a row that is already terminal is left
        exactly as it stands.

        Design: Corner/state_machines/corner_cancellation_cascade_touches_only_non_terminal_children
        """
        account = fx.in_force_account(
            parts=(("MATERIALS_ON_SITE", 1000000000),
                   ("TEMPORARY_STORAGE", 400000000)),
            project_overrides=HARBORLINE)
        # base 2200000 + cat 396000, no soft-cost units at all, less the 155760 credit.
        assert account.policy["quoted_premium_cents"] == 2440240
        assert account.policy["written_premium_cents"] == 2440240

        facility = fx.register_facility(
            name="Northgate Yard", site_code="NGY-01",
            distance_from_site_miles=18, aggregate_capacity_cents=900000000,
            protection_class="SPRINKLERED")
        first = fx.assign_storage(account, facility, 120000000,
                                  "2026-10-01T00:00:00Z", "2026-11-01T00:00:00Z")
        second = fx.assign_storage(account, facility, 150000000,
                                   "2027-01-01T00:00:00Z", "2027-02-01T00:00:00Z")
        released = fx.release_storage(first)
        assert released["status"] == "RELEASED"
        assert released["release_reason"] == "MANUAL"

        cancelled = fx.cancel_account(
            account, cancel_reason="PROJECT_ABANDONED",
            cancel_effective_date="2027-01-01T00:00:00Z", headers=UM)
        assert cancelled["status"] == "CANCELLED"
        # total term 302, earned 122, unearned 180; PROJECT_ABANDONED is not an
        # insured request, so the full pro-rata figure is returned.
        assert cancelled["return_premium_cents"] == 1454448
        assert cancelled["written_premium_cents"] == 985792
        assert cancelled["cancel_reason"] == "PROJECT_ABANDONED"
        assert cancelled["cancel_effective_date"] == "2027-01-01T00:00:00Z"

        rows, meta = validate_paginated(
            api_client.list_policy_premium_transactions(account.policy_id, UM))
        assert meta["total_count"] == 2
        ledger = sorted(rows, key=lambda row: row["sequence_no"])
        assert ledger[0]["txn_type"] == "INITIAL"
        assert ledger[0]["amount_cents"] == 2440240
        a.assert_premium_transaction(ledger[1], txn_type="RETURN_PREMIUM")
        assert ledger[1]["sequence_no"] == 2
        assert ledger[1]["amount_cents"] == -1454448
        assert ledger[1]["effective_date"] == "2027-01-01T00:00:00Z"
        a.assert_ledger_balances(ledger, cancelled["written_premium_cents"])

        # The already-released row is untouched by the cascade.
        held_first = validate_success(
            api_client.get_storage_assignment(first["id"], UW))
        assert held_first["status"] == "RELEASED"
        assert held_first["release_reason"] == "MANUAL"
        assert held_first["version"] == released["version"]

        held_second = validate_success(
            api_client.get_storage_assignment(second["id"], UW))
        assert held_second["status"] == "RELEASED"
        assert held_second["release_reason"] == "POLICY_CANCELLATION"
        # released_at is the logical clock, not the cancellation effective date.
        assert held_second["released_at"] == "2026-09-01T00:00:00Z"

        for part in account.refresh_parts().values():
            a.assert_coverage_part(part, status="CLOSED")
            assert part["eroded_cents"] == 0

        assert validate_success(api_client.get_facility(
            facility["id"], RE))["committed_value_cents"] == 0
        assert account.refresh_project()["in_force_policy_count"] == 0
