"""Agreement scoping, the four uniqueness scopes, and the two timing windows.

The gates collected here are the ones whose subject is a scope or an instant
rather than a single field value: a cross-reference that leaves its delegation
agreement, a value that must be unique inside some scope, and the two clock
boundaries — the settlement window and the continuity-of-care window.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_success,
)

from test_helpers import (
    ERR_AGREEMENT_MISMATCH,
    ERR_CONTINUITY_OF_CARE_ACTIVE,
    ERR_COVERAGE_MONTH_DUPLICATE,
    ERR_DUPLICATE_MEMBER_ID,
    ERR_DUPLICATE_NPI,
    ERR_DUPLICATE_TAX_ID,
    ERR_SETTLEMENT_WINDOW_NOT_OPEN,
    IPA_ADMIN_HEADERS,
    NETWORK_MANAGER_HEADERS,
    agreement_payload,
    assert_fields,
    assert_panel_size,
    assign_enrollee,
    assignment_payload,
    build_final_scorecard,
    build_posted_file,
    close_incurral,
    create_active_agreement,
    create_active_physician,
    create_enrollee,
    create_enrollment_file,
    create_physician,
    create_pool,
    enrollee_payload,
    enrollee_version,
    enrollment_file_payload,
    give_exit_notice,
    list_pool_distributions,
    physician_payload,
    propose_settlement,
    read_agreement,
    read_assignment,
    read_enrollee,
    read_physician,
    read_pool,
    reserve_pool,
    set_clock,
    state_payload,
)


def _two_agreements_with_one_physician_each(api):
    """Two ACTIVE agreements; the member lives on the first one only."""
    set_clock(api, "2026-08-01T00:00:00Z")
    home = create_active_agreement(
        api, payer_name="Corner Mismatch A Health", payer_tax_id="94-3000063"
    )
    foreign = create_active_agreement(
        api, payer_name="Corner Mismatch B Health", payer_tax_id="94-3000064"
    )
    home_physician = create_active_physician(
        api, home["id"], npi="4900000001", full_name="Dr Mismatch Home"
    )
    foreign_physician = create_active_physician(
        api, foreign["id"], npi="4900000002", full_name="Dr Mismatch Foreign"
    )
    enrollee = create_enrollee(
        api, home["id"], external_member_id="V5-0001", risk_score_bps=10000
    )
    return home, foreign, home_physician, foreign_physician, enrollee


class TestSingleAgreementScopeOnAssignment:
    def test_an_assignment_whose_physician_lives_elsewhere_is_refused(self, api):
        """PRD §2.7: "An assignment's enrollee and physician must belong to the
        same agreement; a transfer target must belong to the source physician's
        agreement; a claim's enrollee, attributed physician and resolved pool must
        all belong to the claim's agreement; a recovery's enrollee must belong to
        the agreement that owns the recovery's pool."

        Design: Corner/validations/assignment_across_two_agreements_rejected_then_same_agreement_accepted
        """
        _home, foreign, _home_physician, foreign_physician, enrollee = (
            _two_agreements_with_one_physician_each(api)
        )

        response = api.create_assignment(
            assignment_payload(
                enrollee["id"],
                foreign_physician["id"],
                enrollee["version"],
                effective_date="2026-08-01T00:00:00Z",
            ),
            NETWORK_MANAGER_HEADERS,
        )
        validate_error(response, ERR_AGREEMENT_MISMATCH, 422)

        assert_panel_size(read_physician(api, foreign_physician["id"]), 0)
        assert read_agreement(api, foreign["id"])["total_assigned_members"] == 0

    def test_the_members_own_agreement_accepts_the_unchanged_enrollee_version(self, api):
        """PRD §2.7: "Every cross-reference in this system must stay inside a
        single `DelegationAgreement`."

        Design: Corner/validations/assignment_across_two_agreements_rejected_then_same_agreement_accepted
        """
        home, _foreign, home_physician, foreign_physician, enrollee = (
            _two_agreements_with_one_physician_each(api)
        )
        observed_version = enrollee["version"]

        api.create_assignment(
            assignment_payload(
                enrollee["id"],
                foreign_physician["id"],
                observed_version,
                effective_date="2026-08-01T00:00:00Z",
            ),
            NETWORK_MANAGER_HEADERS,
        )

        accepted = validate_success(
            api.create_assignment(
                assignment_payload(
                    enrollee["id"],
                    home_physician["id"],
                    observed_version,
                    effective_date="2026-08-01T00:00:00Z",
                ),
                NETWORK_MANAGER_HEADERS,
            ),
            201,
        )
        assert_fields(
            accepted, {"status": "ACTIVE", "physician_id": home_physician["id"]}
        )
        assert_panel_size(read_physician(api, home_physician["id"]), 1)
        assert read_agreement(api, home["id"])["total_assigned_members"] == 1


def _agreement_holding_one_of_each_unique_value(api):
    """Agreement A owns one npi, one member id and one coverage month; B is bare."""
    set_clock(api, "2026-08-01T00:00:00Z")
    first = create_active_agreement(
        api, payer_name="Corner Uniqueness A Health", payer_tax_id="94-3000070"
    )
    second = create_active_agreement(
        api, payer_name="Corner Uniqueness B Health", payer_tax_id="94-3000071"
    )
    physician = create_physician(
        api, first["id"], npi="5400000001", full_name="Dr Uniqueness"
    )
    enrollee = create_enrollee(
        api, first["id"], external_member_id="V13-0001", risk_score_bps=10000
    )
    enrollment_file = create_enrollment_file(
        api, first["id"], coverage_month="2026-07", payer_file_reference="PFR-V13-2026-07"
    )
    return first, second, physician, enrollee, enrollment_file


class TestFourUniquenessScopes:
    def test_each_uniqueness_clause_raises_its_own_error(self, api):
        """PRD §2.10: "`payer_tax_id` is unique across all agreements, raising
        `ERR_DUPLICATE_TAX_ID`; `npi` is unique among the physicians of one
        agreement, raising `ERR_DUPLICATE_NPI`; `external_member_id` is unique
        among the enrollees of one agreement, raising `ERR_DUPLICATE_MEMBER_ID`;
        and `coverage_month` is unique among the agreement's enrollment files whose
        `status` is anything other than `DISPUTED`, raising
        `ERR_COVERAGE_MONTH_DUPLICATE`."

        Design: Corner/validations/four_uniqueness_scopes_each_rejected_with_their_own_error
        """
        first, _second, _physician, _enrollee, enrollment_file = (
            _agreement_holding_one_of_each_unique_value(api)
        )

        validate_error(
            api.create_agreement(
                agreement_payload(
                    payer_name="Corner Uniqueness Clone Health",
                    payer_tax_id="94-3000070",
                ),
                IPA_ADMIN_HEADERS,
            ),
            ERR_DUPLICATE_TAX_ID,
            409,
        )
        validate_error(
            api.create_physician(
                first["id"],
                physician_payload(
                    npi="5400000001",
                    full_name="Dr Uniqueness Clone",
                    specialty="PEDIATRICS",
                ),
                NETWORK_MANAGER_HEADERS,
            ),
            ERR_DUPLICATE_NPI,
            409,
        )
        validate_error(
            api.create_enrollee(
                first["id"],
                enrollee_payload(
                    external_member_id="V13-0001",
                    age_band="SENIOR",
                    benefit_tier="POS",
                ),
                IPA_ADMIN_HEADERS,
            ),
            ERR_DUPLICATE_MEMBER_ID,
            409,
        )
        validate_error(
            api.create_enrollment_file(
                first["id"],
                enrollment_file_payload(
                    coverage_month="2026-07",
                    payer_file_reference="PFR-V13-2026-07-RESEND",
                ),
                IPA_ADMIN_HEADERS,
            ),
            ERR_COVERAGE_MONTH_DUPLICATE,
            409,
        )
        assert enrollment_file["coverage_month"] == "2026-07"

    def test_npi_and_member_id_uniqueness_are_scoped_within_one_agreement(self, api):
        """PRD §2.10: "`payer_tax_id` is unique across all agreements, raising
        `ERR_DUPLICATE_TAX_ID`; `npi` is unique among the physicians of one
        agreement, raising `ERR_DUPLICATE_NPI`; `external_member_id` is unique
        among the enrollees of one agreement, raising `ERR_DUPLICATE_MEMBER_ID`;
        and `coverage_month` is unique among the agreement's enrollment files whose
        `status` is anything other than `DISPUTED`, raising
        `ERR_COVERAGE_MONTH_DUPLICATE`."

        Design: Corner/validations/four_uniqueness_scopes_each_rejected_with_their_own_error
        """
        _first, second, physician, enrollee, _file = (
            _agreement_holding_one_of_each_unique_value(api)
        )

        twin_physician = validate_success(
            api.create_physician(
                second["id"],
                physician_payload(
                    npi="5400000001", full_name="Dr Uniqueness Other Ipa"
                ),
                NETWORK_MANAGER_HEADERS,
            ),
            201,
        )
        twin_enrollee = validate_success(
            api.create_enrollee(
                second["id"],
                enrollee_payload(external_member_id="V13-0001"),
                IPA_ADMIN_HEADERS,
            ),
            201,
        )

        assert twin_physician["npi"] == physician["npi"]
        assert twin_physician["id"] != physician["id"]
        assert twin_enrollee["external_member_id"] == enrollee["external_member_id"]
        assert twin_enrollee["id"] != enrollee["id"]


def _professional_pool_at_settlement_proposed(api):
    """A funded 2026 PROFESSIONAL pool driven to SETTLEMENT_PROPOSED."""
    set_clock(api, "2026-01-01T00:00:00Z")
    agreement = create_active_agreement(
        api,
        payer_name="Corner Settlement Window Health",
        payer_tax_id="94-3000065",
        base_pmpm_cents=20000,
        reconciliation_method="ROSTER_SNAPSHOT",
        professional_pool_share_bps=10000,
        institutional_pool_share_bps=0,
        quality_withhold_bps=700,
    )
    pool = create_pool(api, agreement["id"], pool_type="PROFESSIONAL")
    physician = create_active_physician(
        api, agreement["id"], npi="4900000003", full_name="Dr Settlement Window"
    )
    enrollee = create_enrollee(
        api, agreement["id"], external_member_id="V6-0001", risk_score_bps=10000
    )
    assign_enrollee(
        api, enrollee["id"], physician["id"], effective_date="2026-01-01T00:00:00Z"
    )

    set_clock(api, "2026-08-01T00:00:00Z")
    build_posted_file(
        api,
        agreement["id"],
        [
            {
                "external_member_id": "V6-0001",
                "physician_npi": "4900000003",
                "claimed_capitation_cents": 20000,
            }
        ],
        coverage_month="2026-07",
    )
    build_final_scorecard(
        api,
        physician["id"],
        measurement_period="2026",
        hedis_composite_bps=7000,
        access_score_bps=7000,
        patient_experience_bps=7000,
    )

    set_clock(api, "2027-01-01T00:00:00Z")
    close_incurral(api, pool["id"])
    reserve_pool(api, pool["id"])
    proposed = propose_settlement(api, pool["id"])
    return agreement, physician, pool, proposed


class TestSettlementWindowBoundary:
    def test_settling_before_the_due_date_is_refused_and_the_pool_stays_proposed(
        self, api
    ):
        """PRD §2.10: "A pool may reach `SETTLED` only once the logical clock has
        reached its `settlement_due_date`, which is `pool_year_end` plus 180 days
        for a `PROFESSIONAL` pool and `pool_year_end` plus 270 days for an
        `INSTITUTIONAL` pool."

        Design: Corner/validations/pool_settled_before_settlement_due_date_returns_422_then_allowed_after
        """
        _agreement, _physician, pool, proposed = _professional_pool_at_settlement_proposed(
            api
        )
        assert_fields(
            proposed,
            {
                "status": "SETTLEMENT_PROPOSED",
                "settlement_due_date": "2027-06-29T23:59:59Z",
                "funded_cents": 18600,
                "admin_fee_cents": 1860,
                "shared_savings_pool_cents": 10044,
            },
        )

        set_clock(api, "2027-06-29T00:00:00Z")
        response = api.set_risk_pool_state(
            pool["id"], state_payload("SETTLED"), IPA_ADMIN_HEADERS
        )
        validate_error(response, ERR_SETTLEMENT_WINDOW_NOT_OPEN, 422)
        assert read_pool(api, pool["id"])["status"] == "SETTLEMENT_PROPOSED"

    def test_the_identical_request_settles_once_the_clock_reaches_the_due_date(
        self, api
    ):
        """PRD §3.8: "The agreement's `withheld_balance_cents` then decreases by
        the sum of those distributions' `withhold_share_cents`, and the agreement's
        `forfeited_withhold_cents` increases by the sum, over those same
        distributions, of `withhold_share_cents` less `withhold_release_cents` —
        the portion of each physician's withhold share that quality performance did
        not earn back, which is what `forfeited_withhold_cents` accumulates
        whenever a `withhold_release_bps_snapshot` fell short of 10000."

        Design: Corner/validations/pool_settled_before_settlement_due_date_returns_422_then_allowed_after
        """
        agreement, _physician, pool, _proposed = _professional_pool_at_settlement_proposed(
            api
        )

        set_clock(api, "2027-06-29T00:00:00Z")
        api.set_risk_pool_state(pool["id"], state_payload("SETTLED"), IPA_ADMIN_HEADERS)

        set_clock(api, "2027-06-30T00:00:00Z")
        settled = validate_success(
            api.set_risk_pool_state(
                pool["id"], state_payload("SETTLED"), IPA_ADMIN_HEADERS
            ),
            200,
        )
        assert settled["status"] == "SETTLED"

        paid = list_pool_distributions(api, pool["id"], status="PAID")
        assert len(paid) == 1
        assert_fields(
            paid[0],
            {
                "withhold_share_cents": 1400,
                "withhold_release_bps_snapshot": 7500,
                "withhold_release_cents": 1050,
                "shared_savings_cents": 10044,
                "net_distribution_cents": 11094,
            },
        )
        assert_fields(
            read_agreement(api, agreement["id"]),
            {"withheld_balance_cents": 0, "forfeited_withhold_cents": 350},
        )


def _physician_under_notice_holding_one_member(api):
    """A member on the panel of a physician who gave notice on 1 March 2026."""
    set_clock(api, "2026-01-01T00:00:00Z")
    agreement = create_active_agreement(
        api,
        payer_name="Corner Continuity Health",
        payer_tax_id="94-3000067",
        continuity_of_care_days=90,
    )
    physician = create_active_physician(
        api, agreement["id"], npi="5100000001", full_name="Dr Continuity"
    )
    enrollee = create_enrollee(
        api, agreement["id"], external_member_id="V9-0001", risk_score_bps=10000
    )
    assignment = assign_enrollee(
        api, enrollee["id"], physician["id"], effective_date="2026-01-01T00:00:00Z"
    )

    set_clock(api, "2026-03-01T00:00:00Z")
    noticed = give_exit_notice(api, physician["id"])
    return agreement, physician, enrollee, assignment, noticed


class TestContinuityOfCareWindowBoundary:
    def test_a_termination_inside_the_live_window_is_refused(self, api):
        """PRD §2.10: "An `ACTIVE` assignment may not be terminated while the
        holding physician's `continuity_of_care_until` is set and the logical clock
        has not reached it."

        Design: Corner/validations/assignment_termination_inside_continuity_window_rejected
        """
        _agreement, _physician, _enrollee, assignment, noticed = (
            _physician_under_notice_holding_one_member(api)
        )
        assert_fields(
            noticed,
            {
                "credential_status": "NOTICE_GIVEN",
                "exit_notice_at": "2026-03-01T00:00:00Z",
                "continuity_of_care_until": "2026-05-30T00:00:00Z",
            },
        )

        set_clock(api, "2026-05-29T00:00:00Z")
        response = api.set_assignment_state(
            assignment["id"], state_payload("TERMINATED"), NETWORK_MANAGER_HEADERS
        )
        validate_error(response, ERR_CONTINUITY_OF_CARE_ACTIVE, 422)

        held = read_assignment(api, assignment["id"])
        assert_fields(held, {"status": "ACTIVE", "term_date": None})

    def test_a_termination_at_the_continuity_instant_runs_its_cascade(self, api):
        """PRD §3.4: "The transition sets `status` to `TERMINATED` and stamps
        `term_date` with the current logical clock instant; it recomputes the
        physician's `panel_size` downward by one, clears the enrollee's
        `assigned_physician_id` to null, recomputes the agreement's
        `total_assigned_members` downward by one, and advances the assignment's
        `version` by 1."

        Design: Corner/validations/assignment_termination_inside_continuity_window_rejected
        """
        agreement, physician, enrollee, assignment, _noticed = (
            _physician_under_notice_holding_one_member(api)
        )

        set_clock(api, "2026-05-29T00:00:00Z")
        api.set_assignment_state(
            assignment["id"], state_payload("TERMINATED"), NETWORK_MANAGER_HEADERS
        )

        version_before_release = enrollee_version(api, enrollee["id"])

        set_clock(api, "2026-05-30T00:00:00Z")
        terminated = validate_success(
            api.set_assignment_state(
                assignment["id"], state_payload("TERMINATED"), NETWORK_MANAGER_HEADERS
            ),
            200,
        )
        assert_fields(
            terminated,
            {"status": "TERMINATED", "term_date": "2026-05-30T00:00:00Z"},
        )
        assert read_enrollee(api, enrollee["id"])["assigned_physician_id"] is None
        assert_panel_size(read_physician(api, physician["id"]), 0)
        assert read_agreement(api, agreement["id"])["total_assigned_members"] == 0
        assert enrollee_version(api, enrollee["id"]) > version_before_release
