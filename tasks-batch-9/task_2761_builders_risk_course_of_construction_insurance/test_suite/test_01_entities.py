"""Entity-level contract tests for the Builders Risk Course Of Construction API.

Every test here starts from an empty database and a logical clock reading
2026-08-01T00:00:00Z, and assembles whatever state it needs from the endpoints
the PRD publishes.
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
    RISK_ENGINEER_ID,
    TEST_USERS,
    UNDERWRITER_2_ID,
)

UW = TEST_USERS["underwriter_headers"]
UW2 = TEST_USERS["underwriter_2_headers"]
UM = TEST_USERS["manager_headers"]
RE = TEST_USERS["risk_engineer_headers"]
CA = TEST_USERS["claim_adjuster_headers"]

# Well-formed UUIDs that no row carries.
UNKNOWN_PROJECT_ID = "00000000-0000-4000-8000-000000000001"
UNKNOWN_POLICY_ID = "00000000-0000-4000-8000-0000000000aa"
UNKNOWN_FACILITY_ID = "00000000-0000-4000-8000-0000000000bb"
UNKNOWN_PROJECT_FK = "00000000-0000-4000-8000-0000000000cc"

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


class TestConstructionProjectRecord:
    def test_submission_lands_in_submitted_with_system_defaults(self):
        """A newly submitted project lands in SUBMITTED with version 1, no risk
        scores at all, engineering_grade, loss_control_report_ref,
        screened_by_user_id and actual_substantial_completion_date all null, and
        in_force_policy_count at 0.

        Design: Corner/entities/corner_project_creation_returns_submitted_row_with_system_defaults
        """
        payload = f.create_project_payload(
            existing_structure_value_cents=0, **HARBORLINE)
        response = api_client.create_project(payload, UW)
        project = validate_success(response, expected_status=201)

        a.assert_project(project, status="SUBMITTED")
        assert project["name"] == "Harborline Terminal Expansion"
        assert project["site_address"] == "410 Dock Rd, Newport"
        assert project["construction_type"] == "NON_COMBUSTIBLE"
        assert project["project_kind"] == "NEW_CONSTRUCTION"
        assert project["cat_zone"] == "WIND_TIER_2"
        assert project["hard_cost_value_cents"] == 2000000000
        assert project["planned_start_date"] == "2026-09-01T00:00:00Z"
        assert project["projected_completion_date"] == "2027-06-01T00:00:00Z"
        assert project["version"] == 1
        assert project["submission_risk_score"] is None
        assert project["audit_risk_score"] is None
        assert project["engineering_grade"] is None
        assert project["loss_control_report_ref"] is None
        assert project["screened_by_user_id"] is None
        assert project["actual_substantial_completion_date"] is None
        assert project["in_force_policy_count"] == 0

        # The standard success envelope of the contract.
        body = response.json()
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert isinstance(body["meta"]["api_request_timestamp"], str)

    def test_read_returns_the_post_screen_values_not_the_creation_snapshot(self):
        """Screening records engineering_grade, attaches loss_control_report_ref,
        stamps screened_by_user_id and stores submission_risk_score; a score below
        90 with a grade other than D makes the project ELIGIBLE.

        Design: Corner/entities/corner_project_retrieval_returns_the_stored_row
        """
        project = fx.submit_project(**HARBORLINE)
        fx.screen_project(project, engineering_grade="B",
                          loss_control_report_ref="LC-2761-A")

        # The read is open to the ClaimAdjuster as well as the underwriting roles.
        got = validate_success(api_client.get_project(project["id"], CA))

        assert got["id"] == project["id"]
        assert got["status"] == "ELIGIBLE"
        assert got["engineering_grade"] == "B"
        # 12 (NON_COMBUSTIBLE) + 12 (WIND_TIER_2) + 4 (value) + 0 (schedule).
        assert got["submission_risk_score"] == 28
        assert got["version"] == 2
        assert got["loss_control_report_ref"] == "LC-2761-A"
        assert got["screened_by_user_id"] == RISK_ENGINEER_ID
        # The audit basis is only evaluated by an extension or an adjustment.
        assert got["audit_risk_score"] is None

    def test_existing_structure_value_defaults_to_zero_and_feeds_the_score(self):
        """On a renovation the actual cash value of the building that is already
        standing is supplied as existing_structure_value_cents; the field is
        optional, defaults to 0 when omitted.

        Design: Corner/entities/corner_project_existing_structure_value_defaults_to_zero
        """
        project = fx.submit_project(**HARBORLINE)
        assert project["existing_structure_value_cents"] == 0

        screened = fx.screen_project(project, engineering_grade="B")
        # Value points are min(20, floor(2000000000 / 500000000)) == 4, so the
        # defaulted zero contributed nothing: 12 + 12 + 4 + 0 == 28.
        assert screened["submission_risk_score"] == 28
        assert screened["loss_control_report_ref"] is None

    def test_listing_paginates_and_filters_on_cat_zone_and_project_kind(self):
        """limit caps the rows returned and defaults to 10, offset skips rows,
        total_count is the number of matching rows before pagination and has_more
        states whether any matching rows remain; projects may be filtered by
        cat_zone and project_kind.

        Design: Corner/entities/corner_project_listing_paginates_with_total_count_and_has_more
        """
        fx.submit_project(**HARBORLINE)
        cedar = fx.submit_project(
            name="Cedar Mills Warehouse", site_address="12 Mill Rd, Cedar",
            construction_type="FIRE_RESISTIVE", project_kind="NEW_CONSTRUCTION",
            hard_cost_value_cents=400000000, cat_zone="INLAND",
            planned_start_date="2026-09-01T00:00:00Z",
            projected_completion_date="2027-03-01T00:00:00Z")
        fifth = fx.submit_project(
            name="Fifth Avenue Renovation", site_address="5 Fifth Ave, Rockvale",
            construction_type="JOISTED_MASONRY", project_kind="RENOVATION",
            hard_cost_value_cents=1500000000,
            existing_structure_value_cents=500000000, cat_zone="INLAND",
            planned_start_date="2026-10-01T00:00:00Z",
            projected_completion_date="2027-04-15T00:00:00Z")

        first = api_client.list_projects(UM, params={"limit": 2, "offset": 0})
        rows, meta = validate_paginated(first)
        assert first.json()["response_type"] == "array"
        assert len(rows) == 2
        assert meta["limit"] == 2
        assert meta["offset"] == 0
        assert meta["total_count"] == 3
        assert meta["has_more"] is True

        rows, meta = validate_paginated(
            api_client.list_projects(UM, params={"limit": 2, "offset": 2}))
        assert len(rows) == 1
        assert meta["offset"] == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is False

        rows, meta = validate_paginated(
            api_client.list_projects(UM, params={"cat_zone": "INLAND"}))
        assert meta["total_count"] == 2
        assert {row["id"] for row in rows} == {cedar["id"], fifth["id"]}

        rows, meta = validate_paginated(
            api_client.list_projects(UM, params={"project_kind": "RENOVATION"}))
        assert meta["total_count"] == 1
        assert rows[0]["id"] == fifth["id"]

        # limit is omitted here, so the declared default of 10 applies.
        rows, meta = validate_paginated(api_client.list_projects(UM))
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 3
        assert len(rows) == 3

    def test_unknown_project_id_is_not_found_on_read_and_on_screen(self):
        """Each collection has its own not-found code, ERR_PROJECT_NOT_FOUND for
        projects, and existence of every identifier in the request path is checked
        before the target record's own state.

        Design: Corner/entities/corner_project_get_with_unknown_uuid_returns_project_not_found
        """
        project = fx.submit_project(**HARBORLINE)

        response = api_client.get_project(UNKNOWN_PROJECT_ID, UW)
        validate_error(response, ApiErrorId.ERR_PROJECT_NOT_FOUND.value,
                       expected_status=404)
        assert response.json()["response_type"] == "error"

        validate_error(
            api_client.screen_project(
                UNKNOWN_PROJECT_ID, f.screen_project_payload(), RE),
            ApiErrorId.ERR_PROJECT_NOT_FOUND.value, expected_status=404)

        untouched = validate_success(api_client.get_project(project["id"], UW))
        assert untouched["status"] == "SUBMITTED"
        assert untouched["version"] == 1

    def test_submission_missing_a_required_field_is_rejected(self):
        """Request-body schema conformance requires every non-optional field to be
        present, and a violation is refused with ERR_INVALID_REQUEST.

        Design: Corner/entities/corner_project_creation_missing_required_fields_is_rejected
        """
        no_zone = {
            "name": "No Zone Project", "site_address": "1 Nowhere St",
            "construction_type": "NON_COMBUSTIBLE",
            "project_kind": "NEW_CONSTRUCTION",
            "hard_cost_value_cents": 2000000000,
            "planned_start_date": "2026-09-01T00:00:00Z",
            "projected_completion_date": "2027-06-01T00:00:00Z",
        }
        validate_error(api_client.create_project(no_zone, UW),
                       ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)

        no_value = {
            "name": "No Value Project", "site_address": "2 Nowhere St",
            "construction_type": "NON_COMBUSTIBLE",
            "project_kind": "NEW_CONSTRUCTION", "cat_zone": "INLAND",
            "planned_start_date": "2026-09-01T00:00:00Z",
            "projected_completion_date": "2027-06-01T00:00:00Z",
        }
        validate_error(api_client.create_project(no_value, UW),
                       ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)

        # existing_structure_value_cents declares a default, so omitting it works.
        validate_success(
            api_client.create_project(f.create_project_payload(**HARBORLINE), UW),
            expected_status=201)
        _, meta = validate_paginated(api_client.list_projects(UW))
        assert meta["total_count"] == 1

class TestBuildersRiskPolicyRecord:
    def test_creation_derives_term_days_tiv_deductible_and_completion_date(self):
        """original_term_days is the whole number of days in the half-open interval
        from term_start_date to term_end_date, insured_tiv_cents is the project's
        hard_cost_value_cents plus the existing structure only when
        includes_existing_structure is true, occurrence_deductible_cents is read
        straight off deductible_tier, adjusted_completion_date starts equal to the
        project's projected_completion_date and cumulative_extension_days starts at 0.

        Design: Corner/entities/corner_policy_computed_fields_derive_term_days_tiv_and_deductible
        """
        project = fx.eligible_project(**HARBORLINE)
        assert project["version"] == 2

        payload = f.create_policy_payload(project["id"], project["version"])
        # None of the four derived figures is an input field.
        for derived in ("original_term_days", "insured_tiv_cents",
                        "occurrence_deductible_cents", "adjusted_completion_date"):
            assert derived not in payload
        policy = validate_success(
            api_client.create_policy(payload, UW), expected_status=201)

        a.assert_policy(policy, status="DRAFT")
        assert policy["project_id"] == project["id"]
        # 2026-09-01 to 2027-06-30 exclusive is 302 days.
        assert policy["original_term_days"] == 302
        # hard_cost only, because includes_existing_structure is false.
        assert policy["includes_existing_structure"] is False
        assert policy["insured_tiv_cents"] == 2000000000
        assert policy["occurrence_deductible_cents"] == 10000000
        a.assert_deductible_for_tier(policy)
        assert policy["adjusted_completion_date"] == "2027-06-01T00:00:00Z"
        assert policy["cumulative_extension_days"] == 0
        assert policy["quoted_premium_cents"] is None
        assert policy["referral_load_pct"] == 0
        assert policy["written_premium_cents"] == 0
        assert policy["eroded_total_cents"] == 0
        assert policy["return_premium_cents"] is None
        assert policy["quoted_by_user_id"] is None
        assert policy["bound_at"] is None
        assert policy["cancel_reason"] is None
        assert policy["cancel_effective_date"] is None
        assert policy["version"] == 1

        # A different term and a different tier derive different figures.
        second = fx.eligible_project(
            engineering_grade="A", name="Cedar Mills Warehouse",
            site_address="12 Mill Rd, Cedar", construction_type="FIRE_RESISTIVE",
            project_kind="NEW_CONSTRUCTION", hard_cost_value_cents=400000000,
            cat_zone="INLAND", planned_start_date="2026-09-01T00:00:00Z",
            projected_completion_date="2027-03-01T00:00:00Z")
        short = validate_success(api_client.create_policy(
            f.create_policy_payload(
                second["id"], second["version"],
                term_end_date="2026-12-01T00:00:00Z",
                deductible_tier="HIGH_250K", limit_cents=500000000,
                daily_delay_rate_cents=0), UW), expected_status=201)
        # September 30 + October 31 + November 30 == 91 days.
        assert short["original_term_days"] == 91
        assert short["insured_tiv_cents"] == 400000000
        assert short["occurrence_deductible_cents"] == 25000000
        assert short["adjusted_completion_date"] == "2027-03-01T00:00:00Z"

    def test_status_quoting_user_and_bound_at_are_stamped_by_the_server(self):
        """A new policy lands in DRAFT with quoted_by_user_id and bound_at null;
        rating stamps quoted_by_user_id from the acting user and a successful bind
        moves the policy to BOUND and stamps bound_at from the logical clock.

        Design: Corner/entities/corner_policy_system_fields_are_server_stamped_not_client_supplied
        """
        account = fx.draft_account(
            parts=(("MATERIALS_ON_SITE", 1000000000),),
            project_overrides=HARBORLINE)
        assert account.policy["status"] == "DRAFT"
        assert account.policy["quoted_by_user_id"] is None
        assert account.policy["bound_at"] is None
        # create, coverage part, insured interest.
        assert account.policy["version"] == 3

        fx.set_clock("2026-09-01T00:00:00Z")

        # The rating call is made by the second underwriter, not the creator.
        fx.quote_account(account, headers=UW2)
        assert account.policy["status"] == "QUOTED"
        assert account.policy["quoted_by_user_id"] == UNDERWRITER_2_ID
        assert account.policy["bound_at"] is None
        assert account.policy["version"] == 4

        fx.bind_account(account, headers=UW2)
        assert account.policy["status"] == "BOUND"
        assert account.policy["quoted_by_user_id"] == UNDERWRITER_2_ID
        # Taken from the logical clock, never from wall-clock time.
        assert account.policy["bound_at"] == "2026-09-01T00:00:00Z"
        assert account.policy["version"] == 5

    def test_out_of_enum_and_negative_money_are_rejected_at_the_edge(self):
        """Every enum value must be within its declared set and money amounts must
        be non-negative where declared, and any such shape violation is refused
        with ERR_INVALID_REQUEST while the legal member of the same field list is
        accepted.

        Design: Corner/entities/corner_enum_and_numeric_type_constraints_are_rejected_at_the_edge
        """
        project = fx.eligible_project(**HARBORLINE)
        policy = validate_success(
            api_client.create_policy(
                f.create_policy_payload(project["id"], project["version"]), UW),
            expected_status=201)

        # STEEL_FRAME is not one of the four ISO construction classes.
        validate_error(
            api_client.create_project(f.create_project_payload(
                name="Bad Type", site_address="9 Bad St",
                construction_type="STEEL_FRAME", project_kind="NEW_CONSTRUCTION",
                hard_cost_value_cents=100000000, cat_zone="INLAND",
                planned_start_date="2026-09-01T00:00:00Z",
                projected_completion_date="2027-01-01T00:00:00Z"), UW),
            ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)

        validate_error(
            api_client.create_project(f.create_project_payload(
                name="Negative Value", site_address="9 Bad St",
                construction_type="FIRE_RESISTIVE",
                project_kind="NEW_CONSTRUCTION", hard_cost_value_cents=-1,
                cat_zone="INLAND", planned_start_date="2026-09-01T00:00:00Z",
                projected_completion_date="2027-01-01T00:00:00Z"), UW),
            ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)

        # MEGA_500K is not one of the three deductible tiers.
        validate_error(
            api_client.create_policy(f.create_policy_payload(
                project["id"], project["version"] + 1,
                deductible_tier="MEGA_500K"), UW),
            ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)

        # The legal member of the same enum list is accepted.
        part = validate_success(api_client.create_coverage_part(
            f.create_coverage_part_payload(
                policy["id"], part_type="MATERIALS_ON_SITE",
                sublimit_cents=1000000000), UW), expected_status=201)
        assert part["sublimit_cents"] == 1000000000

        _, meta = validate_paginated(
            api_client.list_policy_coverage_parts(policy["id"], UW))
        assert meta["total_count"] == 1
        # The refused drafts left nothing behind: one project, one policy.
        _, meta = validate_paginated(
            api_client.list_project_policies(project["id"], UW))
        assert meta["total_count"] == 1
        _, meta = validate_paginated(api_client.list_projects(UW))
        assert meta["total_count"] == 1

class TestPremiumLedgerRow:
    def test_ledger_rows_are_append_only_and_carry_no_version(self):
        """A rescission appends an EXTENSION_AP_REVERSAL row with amount_cents equal
        to the negative of the endorsement's additional_premium_cents and
        reverses_sequence_no pointing at that endorsement's own EXTENSION_AP row;
        the ledger is append-only and its rows carry only id and created_at from the
        common block.

        Design: Corner/entities/corner_premium_transaction_ledger_rows_are_immutable_and_have_no_version
        """
        account = fx.in_force_account(project_overrides=HARBORLINE)
        assert account.policy["quoted_premium_cents"] == 2750440

        rows, meta = validate_paginated(
            api_client.list_policy_premium_transactions(account.policy_id, UM))
        assert meta["total_count"] == 1

        endorsement = fx.approved_endorsement(account, 45)
        # daily base round_half_up(2750440 / 302) == 9107; 45 / 302 == 0.1490 so the
        # slip factor is 1.15; round_half_up(9107 * 45 * 1.15) == 471287.
        assert endorsement["additional_premium_cents"] == 471287

        rows, meta = validate_paginated(
            api_client.list_policy_premium_transactions(account.policy_id, UM))
        assert meta["total_count"] == 2
        before = sorted(rows, key=lambda row: row["sequence_no"])
        ap_row_before = before[1]
        assert ap_row_before["amount_cents"] == 471287

        validate_success(
            api_client.rescind_endorsement(endorsement["id"], UM))

        rows, meta = validate_paginated(
            api_client.list_policy_premium_transactions(account.policy_id, UM))
        assert meta["total_count"] == 3
        after = sorted(rows, key=lambda row: row["sequence_no"])
        a.assert_ledger_sequence(after)

        initial, ap_row, reversal = after
        a.assert_premium_transaction(initial, txn_type="INITIAL")
        assert initial["sequence_no"] == 1
        assert initial["amount_cents"] == 2750440
        assert initial["effective_date"] == "2026-09-01T00:00:00Z"
        assert initial["reverses_sequence_no"] is None
        assert initial["policy_id"] == account.policy_id

        a.assert_premium_transaction(ap_row, txn_type="EXTENSION_AP")
        assert ap_row["sequence_no"] == 2
        assert ap_row["amount_cents"] == 471287
        # The AP is effective at the pre-extension expiry date.
        assert ap_row["effective_date"] == "2027-06-30T00:00:00Z"
        assert ap_row["reverses_sequence_no"] is None
        # The reversal appended a row instead of editing this one.
        assert ap_row == ap_row_before

        a.assert_premium_transaction(reversal, txn_type="EXTENSION_AP_REVERSAL")
        assert reversal["sequence_no"] == 3
        assert reversal["amount_cents"] == -471287
        assert reversal["reverses_sequence_no"] == 2

        # written_premium_cents is recomputed from the ledger, so it is back to the
        # pre-approval figure.
        account.refresh_policy()
        assert account.policy["written_premium_cents"] == 2750440
        a.assert_ledger_balances(after, account.policy["written_premium_cents"])


class TestForeignParentReferences:
    def test_children_named_against_an_unknown_policy_are_not_found(self):
        """Existence of every referenced parent is checked before the target
        record's own state, so a coverage part, a claim and an insured interest that
        each name a policy_id belonging to no policy are all refused with
        ERR_POLICY_NOT_FOUND.

        Design: Corner/entities/corner_child_creation_against_a_foreign_parent_is_not_found
        """
        account = fx.draft_account(
            parts=None, with_owner=False, project_overrides=HARBORLINE)

        validate_error(
            api_client.create_coverage_part(f.create_coverage_part_payload(
                UNKNOWN_POLICY_ID, part_type="MATERIALS_ON_SITE",
                sublimit_cents=1000000000), UW),
            ApiErrorId.ERR_POLICY_NOT_FOUND.value, expected_status=404)

        # The not-found answer wins over the in-force precondition on claims.
        validate_error(
            api_client.create_claim(f.create_claim_payload(
                UNKNOWN_POLICY_ID, peril="FIRE",
                loss_date="2026-10-01T00:00:00Z",
                description="Ghost policy claim"), CA),
            ApiErrorId.ERR_POLICY_NOT_FOUND.value, expected_status=404)

        validate_error(
            api_client.create_named_insured_interest(f.create_interest_payload(
                UNKNOWN_POLICY_ID, party_name="Nobody LLC", party_role="OWNER",
                insurable_interest_pct=100), UW),
            ApiErrorId.ERR_POLICY_NOT_FOUND.value, expected_status=404)

        # Nothing was attached to the real policy either.
        _, meta = validate_paginated(
            api_client.list_policy_coverage_parts(account.policy_id, UW))
        assert meta["total_count"] == 0
        _, meta = validate_paginated(
            api_client.list_policy_claims(account.policy_id, UW))
        assert meta["total_count"] == 0
        _, meta = validate_paginated(
            api_client.list_policy_named_insured_interests(account.policy_id, UW))
        assert meta["total_count"] == 0

class TestCrossReferenceIntegrity:
    def test_each_foreign_key_of_a_row_is_resolved_on_its_own(self):
        """A storage assignment names both a covering policy_id and a holding
        facility_id, and a testing notice names a project_id; each reference is
        resolved separately, with ERR_FACILITY_NOT_FOUND for the warehouse and
        ERR_PROJECT_NOT_FOUND for the project.

        Design: Corner/entities/corner_flat_topology_cross_reference_integrity_on_facility_and_project_fks
        """
        account = fx.bound_account(
            parts=(("MATERIALS_ON_SITE", 1000000000),
                   ("TEMPORARY_STORAGE", 400000000)),
            project_overrides=HARBORLINE)
        facility = fx.register_facility(
            name="Northgate Yard", site_code="NGY-01",
            distance_from_site_miles=22, aggregate_capacity_cents=900000000,
            protection_class="SPRINKLERED")
        assert facility["committed_value_cents"] == 0

        # The good policy_id does not rescue the bad facility_id.
        validate_error(
            api_client.create_storage_assignment(
                f.create_storage_assignment_payload(
                    account.policy_id, UNKNOWN_FACILITY_ID, 100000000,
                    "2026-10-01T00:00:00Z", "2026-11-01T00:00:00Z"), UW),
            ApiErrorId.ERR_FACILITY_NOT_FOUND.value, expected_status=404)

        validate_error(
            api_client.create_testing_notice(f.create_testing_notice_payload(
                UNKNOWN_PROJECT_FK, "2027-01-05T00:00:00Z",
                "2027-01-08T00:00:00Z", system_type="SPRINKLER_HYDROSTATIC",
                water_charged=True, mitigation_plan_ref="MIT-1"), RE),
            ApiErrorId.ERR_PROJECT_NOT_FOUND.value, expected_status=404)

        assignment = validate_success(api_client.create_storage_assignment(
            f.create_storage_assignment_payload(
                account.policy_id, facility["id"], 100000000,
                "2026-10-01T00:00:00Z", "2026-11-01T00:00:00Z"), UW),
            expected_status=201)
        a.assert_storage_assignment(assignment, status="APPROVED")
        # Both foreign keys are echoed and resolvable.
        assert assignment["policy_id"] == account.policy_id
        assert assignment["facility_id"] == facility["id"]
        assert assignment["stored_value_cents"] == 100000000
        assert assignment["released_at"] is None
        assert assignment["release_reason"] is None

        held = validate_success(api_client.get_facility(facility["id"], RE))
        assert held["committed_value_cents"] == 100000000
        rows, meta = validate_paginated(
            api_client.list_facility_storage_assignments(facility["id"], RE))
        assert meta["total_count"] == 1
        assert rows[0]["id"] == assignment["id"]


class TestClaimRecord:
    def test_first_notice_of_loss_defaults_the_whole_adjustment_side(self):
        """A new claim lands with adjustment_status REPORTED, payment_status UNPAID,
        reported_at stamped from the logical clock, reopen_count 0,
        adjustment_basis and adjusted_by_user_id null, continuing_pm_weeks at 0,
        allocation_lines empty and every money figure at 0.

        Design: Corner/entities/corner_claim_creation_defaults_and_initial_derived_totals
        """
        account = fx.in_force_account(
            parts=(("MATERIALS_ON_SITE", 1000000000),),
            project_overrides=HARBORLINE)

        # 2026-11-15 sits inside the term 2026-09-01 .. 2027-06-30.
        claim = validate_success(api_client.create_claim(
            f.create_claim_payload(
                account.policy_id, peril="FIRE",
                loss_date="2026-11-15T00:00:00Z",
                description="Formwork fire on level 3"), CA),
            expected_status=201)

        # The two axes both start at their own initial state.
        a.assert_claim(claim, adjustment_status="REPORTED", payment_status="UNPAID")
        assert claim["policy_id"] == account.policy_id
        assert claim["peril"] == "FIRE"
        assert claim["loss_date"] == "2026-11-15T00:00:00Z"
        assert claim["description"] == "Formwork fire on level 3"
        assert claim["reported_at"] == "2026-09-01T00:00:00Z"
        assert claim["adjustment_basis"] is None
        assert claim["adjusted_by_user_id"] is None
        assert claim["continuing_pm_weeks"] == 0
        assert claim["allocation_lines"] == []
        assert claim["indemnity_cents"] == 0
        assert claim["uncovered_cents"] == 0
        assert claim["delay_days_indemnified"] == 0
        assert claim["paid_cents"] == 0
        assert claim["outstanding_reserve_cents"] == 0
        assert claim["total_incurred_cents"] == 0
        assert claim["reopen_count"] == 0
        assert claim["version"] == 1

        # The notice moves no money on the parent policy.
        account.refresh_policy()
        assert account.policy["eroded_total_cents"] == 0
        assert account.policy["status"] == "IN_FORCE"
