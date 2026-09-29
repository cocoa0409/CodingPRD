"""Who may act: the custodian's exclusive file work, the credit officer's global reach,
the four refusals that keep the roles apart, the entity-backed scope of a treasury
officer, the 401 that precedes every 403, and the two segregated pairs."""
from test_helpers import *  # noqa: F401,F403

SHARED_AUDITOR = auditor_headers(SHARED_HUMAN_USER_ID)
SHARED_CREDIT = credit_officer_headers(SHARED_HUMAN_USER_ID)
OTHER_CREDIT = credit_officer_headers("credit-officer-9")


class TestCustodianExclusiveOperations:
    """Loan files, delivery and confirmation, with no credit authority anywhere."""

    def test_the_custodian_runs_its_whole_set_end_to_end(self, api):
        """PRD §3.3: "The parent asset's `custody_location` is set to
        `FHLB_SAFEKEEPING`. That custody change re-derives the asset's
        `effective_listing_mode` — which, with a received receipt now present, becomes
        `DELIVERED` — and when the asset's `status` is `ELIGIBLE` its
        `discount_factor_bps` and `lendable_value_cents` are recomputed at the richer
        delivered factor."

        Design: Corner/rbac/custodian_performs_all_of_its_exclusive_operations
        """
        env = member_with_eligible_sf(api)
        asset_id = env.assets["sf"]["id"]

        patched = assert_envelope(
            api.patch_asset_documentation(
                asset_id,
                documentation_patch_payload(
                    documentation_status="COMPLETE",
                    custody_location="FHLB_SAFEKEEPING",
                ),
                CUSTODIAN,
            )
        )
        review_asset(api, asset_id)
        receipt = assert_envelope(
            api.create_safekeeping_receipt(
                asset_id,
                safekeeping_receipt_payload(
                    file_count=1,
                    delivery_date=CLOCK_START,
                    return_date="2026-09-01T00:00:00Z",
                ),
                CUSTODIAN,
            ),
            201,
        )
        confirmed = assert_envelope(
            api.confirm_safekeeping_receipt(
                receipt["id"], confirm_receipt_payload("RECEIVED"), CUSTODIAN
            )
        )

        assert_fields(
            patched, status="UNDER_REVIEW", custody_location="FHLB_SAFEKEEPING"
        )
        assert_fields(receipt, status="PENDING_DELIVERY", file_count=1)
        assert confirmed["status"] == "RECEIVED"
        asset = read_asset(api, asset_id)
        assert_fields(
            asset, status="ELIGIBLE", effective_listing_mode="DELIVERED"
        )
        assert_asset_valuation(asset, 9_200, 18_400_000)

    def test_the_custodian_reads_files_but_not_credit(self, api):
        """PRD §2.1: "Custodians act globally over loan-file documentation and safekeeping
        and hold no credit authority."

        Design: Corner/rbac/custodian_performs_all_of_its_exclusive_operations
        """
        env = member_with_eligible_sf(api)
        asset_id = env.assets["sf"]["id"]
        receipt = book_receipt(api, asset_id, delivery_date=CLOCK_START)
        product = create_product(api)
        advance = request_advance(
            api, env, product["id"], term_days=30, requested_net_proceeds_cents=1_000_000
        )

        assert_envelope(api.get_safekeeping_receipt(receipt["id"], CUSTODIAN))
        assert_envelope(api.get_collateral_asset(asset_id, CUSTODIAN))
        assert_total_count(api.list_collateral_assets(CUSTODIAN), 1)

        refused = api.get_advance(advance["id"], CUSTODIAN)

        validate_error(refused, "ERR_UNAUTHORIZED", 403)
        assert_error_envelope(refused)


class TestCreditOfficerGlobalScope:
    """One officer, two institutions, every credit edge available on both."""

    def test_the_credit_officer_is_not_bound_to_a_single_member(self, api):
        """PRD §2.1: "When `X-User-Role` is `CreditOfficer`, `X-User-ID` is likewise an
        opaque operator identifier not tied to any persisted entity. ... it is never matched
        against a member's `id`. A `CreditOfficer` acts across all members."

        Design: Corner/rbac/credit_officer_performs_its_exclusive_credit_operations
        """
        harbor = active_member(api)
        cascade = second_member(api)

        patched = assert_envelope(
            api.patch_member_bank_condition(
                cascade.member_id, condition_payload(credit_rating_tier=3), CREDIT_ONE
            )
        )

        assert_fields(
            patched, credit_rating_tier=3, membership_status="ACTIVE"
        )
        assert patched["community_lending_eligible"] is True
        assert patched["delivery_required"] is False
        assert_envelope(api.get_member_bank(harbor.member_id, CREDIT_ONE))
        assert_envelope(api.get_member_bank(cascade.member_id, CREDIT_ONE))
        assert harbor.refresh()["credit_rating_tier"] == 1


class TestBorrowerCannotGrantItselfCredit:
    """Approval is a credit act, even on the borrower's own advance."""

    def test_a_treasury_officer_is_refused_on_the_role_check_alone(self, api):
        """PRD §2.5: "**Authorization.** A role that is not listed for the addressed
        endpoint yields `ERR_UNAUTHORIZED` (403). This applies to every endpoint."

        Design: Corner/rbac/treasury_officer_cannot_approve_advance_unauthorized
        """
        env = member_with_eligible_sf(api)
        product = create_product(api)
        advance = request_advance(
            api, env, product["id"], term_days=30, requested_net_proceeds_cents=1_000_000
        )

        refused = api.approve_advance(advance["id"], env.treasury)

        validate_error(refused, "ERR_UNAUTHORIZED", 403)
        stalled = read_advance(api, advance["id"])
        assert_fields(
            stalled, credit_status="REQUESTED", approved_by_user_id=None
        )

        approved = validate_success(api.approve_advance(advance["id"], CREDIT_ONE))

        assert_fields(
            approved,
            credit_status="CREDIT_APPROVED",
            approved_by_user_id=CREDIT_OFFICER_ONE_USER_ID,
        )


class TestCustodianCannotDecideEligibility:
    """The custodian owns the facts of the file, not the conclusion drawn from them."""

    def test_the_documentation_patch_is_allowed_where_the_decision_is_not(self, api):
        """PRD §4: "| POST | `/fhlb/collateral-assets/{collateral_asset_id}/review-eligibility`
        | Decide an asset's eligibility and discount factor | CreditOfficer |"

        Design: Corner/rbac/custodian_cannot_review_eligibility_unauthorized
        """
        env = pledging_member(api)
        asset = pledge_asset(api, env.member_id)

        refused = api.review_asset_eligibility(asset["id"], CUSTODIAN, {})

        validate_error(refused, "ERR_UNAUTHORIZED", 403)
        stored = read_asset(api, asset["id"])
        assert_fields(
            stored, status="UNDER_REVIEW", ineligibility_reason="NONE"
        )
        assert_asset_valuation(stored, 0, 0)
        assert env.refresh()["lendable_collateral_value_cents"] == 0


class TestAuditorHoldsNoWaiverAuthority:
    """The role gate fires before the segregation-of-duties comparison."""

    def test_the_auditor_is_refused_with_403_not_409(self, api):
        """PRD §2.1: "It is recorded as `raised_by_user_id` on every `ReviewFinding` the
        auditor raises. Auditors act across all members and hold no waiver authority
        whatsoever."

        Design: Corner/rbac/auditor_cannot_waive_its_own_finding_unauthorized
        """
        env = member_with_eligible_sf(api)
        _review, findings = review_with_findings_issued(
            api,
            env,
            env.assets["sf"]["id"],
            window_start=CLOCK_START,
            window_end="2026-08-10T00:00:00Z",
            sample_size=20,
        )
        finding = findings[0]

        refused = api.waive_review_finding(finding["id"], AUDITOR)

        validate_error(refused, "ERR_UNAUTHORIZED", 403)
        stalled = get_success_data(api.get_review_finding(finding["id"], AUDITOR))
        assert_fields(
            stalled,
            status="OPEN",
            waived_by_user_id=None,
            raised_by_user_id=AUDITOR_USER_ID,
        )

        waived = validate_success(api.waive_review_finding(finding["id"], CREDIT_ONE))

        assert_fields(
            waived, status="WAIVED", waived_by_user_id=CREDIT_OFFICER_ONE_USER_ID
        )


class TestCommunityManagerHoldsNoAdmissionAuthority:
    """The pool manager's one exclusive operation is the pool itself."""

    def test_membership_admission_is_reserved_to_the_administrator(self, api):
        """PRD §4: "| POST | `/fhlb/member-banks` | Register a member institution |
        SystemAdmin |"

        Design: Corner/rbac/community_manager_cannot_create_member_bank_unauthorized
        """
        pin_clock(api)

        refused = api.create_member_bank(
            member_bank_payload(
                name="Rogue Bank",
                charter_type="CREDIT_UNION",
                total_assets_cents=1_000_000_000,
                credit_rating_tier=2,
            ),
            COMMUNITY,
        )

        validate_error(refused, "ERR_UNAUTHORIZED", 403)
        allocation = assert_envelope(
            api.create_community_program_allocation(allocation_payload(), COMMUNITY), 201
        )
        assert_fields(
            allocation, program_code="CIP", fiscal_year=2026, status="OPEN"
        )


class TestTreasuryOfficerScope:
    """An allowed role on the endpoint, and still the wrong institution."""

    def test_scope_is_enforced_on_reads_as_well_as_writes(self, api):
        """PRD §2.5: "**Member scope.** On every endpoint whose role list includes
        `TreasuryOfficer`, a `TreasuryOfficer` caller whose `X-User-ID` differs from the
        owning member of the addressed resource — or from a `member_bank_id` supplied in the
        request body — is rejected with `ERR_MEMBER_SCOPE_VIOLATION` (403)."

        Design: Corner/rbac/treasury_officer_reading_another_members_bank_rejected
        """
        harbor = applicant_member(api)
        cascade = second_member(api, activate=False)

        refused = api.get_member_bank(cascade.member_id, harbor.treasury)

        validate_error(refused, "ERR_MEMBER_SCOPE_VIOLATION", 403)
        own = assert_envelope(api.get_member_bank(harbor.member_id, harbor.treasury))
        assert own["id"] == harbor.member_id
        foreign = assert_envelope(api.get_member_bank(cascade.member_id, CREDIT_ONE))
        assert foreign["id"] == cascade.member_id


class TestAuthenticationPrecedesEverything:
    """Three ways to be unauthenticated, none of which reach a role check."""

    def test_a_missing_or_unknown_role_header_is_a_401(self, api):
        """PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying the
        acting user, and `X-User-Role`, declaring the capacity in which they act. If either
        header is absent, or if `X-User-Role` is not one of the six role names below, the
        request is rejected with `ERR_UNAUTHENTICATED` (401)."

        Design: Corner/rbac/request_without_role_header_unauthenticated
        """
        env = applicant_member(api)

        no_role = api.get_member_bank(
            env.member_id, {"X-User-ID": env.member_id, "Content-Type": "application/json"}
        )
        unknown_role = api.get_member_bank(
            env.member_id, build_user_headers("teller-1", "BranchTeller")
        )
        no_user_id = api.get_member_bank(
            env.member_id,
            {"X-User-Role": "CollateralCustodian", "Content-Type": "application/json"},
        )

        validate_error(no_role, "ERR_UNAUTHENTICATED", 401)
        validate_error(unknown_role, "ERR_UNAUTHENTICATED", 401)
        validate_error(no_user_id, "ERR_UNAUTHENTICATED", 401)
        assert_error_envelope(unknown_role)


class TestApproverIsNotFunder:
    """Same role, same authority, and still two people are required."""

    def _approved_advance_of_one_million(self, api):
        env = member_with_eligible_sf(api)
        subscribe_and_issue(api, env.member_id, 50_000, "ACTIVITY")
        product = create_product(api)
        advance = request_advance(
            api, env, product["id"], term_days=30, requested_net_proceeds_cents=1_000_000
        )
        validate_success(api.approve_advance(advance["id"], CREDIT_ONE))
        return env, advance

    def test_the_approving_officer_may_not_release_the_money(self, api):
        """PRD §3.6: "**Funding** is where segregation of duties bites. A `CreditOfficer`
        funds a `CREDIT_APPROVED` advance, and the acting `X-User-ID` must differ from the
        recorded `approved_by_user_id`; the same person attempting both halves is rejected
        with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/same_officer_approving_and_funding_rejected
        """
        env, advance = self._approved_advance_of_one_million(api)

        refused = api.fund_advance(advance["id"], CREDIT_ONE)

        validate_error(refused, "ERR_SEGREGATION_OF_DUTIES", 409)
        stalled = read_advance(api, advance["id"])
        assert_fields(
            stalled,
            credit_status="CREDIT_APPROVED",
            approved_by_user_id=CREDIT_OFFICER_ONE_USER_ID,
            funded_at=None,
            outstanding_principal_cents=0,
        )

        funded = validate_success(api.fund_advance(advance["id"], CREDIT_TWO))

        assert_fields(
            funded,
            credit_status="FUNDED",
            funded_by_user_id=CREDIT_OFFICER_TWO_USER_ID,
            outstanding_principal_cents=1_000_000,
        )
        assert env.refresh()["total_outstanding_advances_cents"] == 1_000_000


class TestRaiserIsNotWaiver:
    """One human wearing both hats is exactly what the rule is there to catch."""

    def _finding_raised_by_the_shared_human(self, api):
        env = member_with_eligible_sf(api)
        review = review_in_field_work(
            api,
            env,
            window_start=CLOCK_START,
            window_end="2026-08-10T00:00:00Z",
            sample_size=20,
        )
        finding = raise_finding(
            api,
            review["id"],
            env.assets["sf"]["id"],
            severity="MAJOR",
            headers=SHARED_AUDITOR,
        )
        issue_findings(api, review["id"])
        return env, review, finding

    def test_the_identity_comparison_ignores_the_role(self, api):
        """PRD §3.8: "Waiving carries the second segregation-of-duties rule: the acting
        `X-User-ID` must differ from the finding's `raised_by_user_id`, else
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/same_user_raising_and_waiving_a_finding_rejected
        """
        _env, _review, finding = self._finding_raised_by_the_shared_human(api)

        refused = api.waive_review_finding(finding["id"], SHARED_CREDIT)

        validate_error(refused, "ERR_SEGREGATION_OF_DUTIES", 409)
        stalled = get_success_data(api.get_review_finding(finding["id"], AUDITOR))
        assert_fields(
            stalled,
            status="OPEN",
            waived_by_user_id=None,
            raised_by_user_id=SHARED_HUMAN_USER_ID,
        )

        waived = validate_success(api.waive_review_finding(finding["id"], OTHER_CREDIT))

        assert_fields(
            waived, status="WAIVED", waived_by_user_id="credit-officer-9"
        )

    def test_a_waived_finding_leaves_the_scorecard_clean(self, api):
        """PRD §3.8: "**Level one — scoring the review.** `weighted_exception_score` is a
        weighted count over the findings of this review whose `status` is `OPEN` or
        `UNRESOLVED` at the moment of close ... Findings that were `REMEDIATED` or `WAIVED`
        are excluded entirely."

        Design: Corner/rbac/same_user_raising_and_waiving_a_finding_rejected
        """
        env, review, finding = self._finding_raised_by_the_shared_human(api)
        validate_success(api.waive_review_finding(finding["id"], OTHER_CREDIT))

        closed = assert_envelope(api.close_review(review["id"], AUDITOR))

        assert_fields(
            closed, status="CLOSED", haircut_bps=0, outcome="PASS"
        )
        assert_weighted_score(closed, 0.0)
        assert_exception_rate(closed, 0.0)
        assert env.refresh()["verification_haircut_bps"] == 0
        assert_asset_valuation(read_asset(api, env.assets["sf"]["id"]), 7_800, 15_600_000)
