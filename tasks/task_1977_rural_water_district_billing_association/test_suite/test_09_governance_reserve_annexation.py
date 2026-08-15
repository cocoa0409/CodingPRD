"""Board voting, USDA reserve covenant, and annexation petition lifecycle."""
from test_helpers import (
    CYCLE_1,
    ApiErrorId,
    api_client,
    adopt_rate_schedule,
    adopt_resolution,
    bill_cycle_with_readings,
    close_cycle,
    create_area,
    create_district,
    create_petition,
    fail_resolution,
    get_district_version,
    get_success_data,
    make_board_director_headers,
    open_cycle,
    propose_resolution,
    setup_billed_invoice,
    setup_district_with_schedule,
    setup_member_with_installed_tap,
    validate_error,
)
from test_helpers.fixtures import ADMIN, CLERK, DIRECTOR, TREASURER, advance_petition_to_vote


class TestBoardVoting:
    def test_duplicate_vote_rejected(self, api):
        """PRD section 3.9: "Voting is one `BoardDirector`, one ballot: each
        record-vote call carries a `vote` and increments the appropriate tally, a
        director who has already voted on the resolution is rejected with
        `ERR_DUPLICATE_VOTE` (HTTP 409)".

        Design: Corner/state_machines/duplicate_vote_rejected
        """
        district = create_district(district_name="DP")
        draft = get_success_data(
            api.create_rate_schedule(
                district["id"],
                {
                    "schedule_label": "S1",
                    "base_minimum_cents": 3500,
                    "included_gallons": 2000,
                    "tier2_rate_cents_per_kgal": 450,
                    "tier2_cap_gallons": 10000,
                    "tier3_rate_cents_per_kgal": 700,
                    "tap_fee_schedule": {
                        "RESIDENTIAL": 75000,
                        "COMMERCIAL": 150000,
                        "AGRICULTURAL": 120000,
                    },
                    "reconnect_fee_cents": 5000,
                },
                DIRECTOR,
            ),
            expected_status=201,
        )
        resolution = propose_resolution(district["id"], "RATE_ADOPTION", draft["id"])
        voter = make_board_director_headers("bd-1")
        first = get_success_data(api.record_vote(district["id"], resolution["id"], {"vote": "FOR"}, voter))
        assert first["votes_for"] == 1

        resp = api.record_vote(district["id"], resolution["id"], {"vote": "FOR"}, voter)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_VOTE, expected_status=409)
        after = get_success_data(api.list_board_resolutions(district["id"], DIRECTOR))
        mine = [r for r in after if r["id"] == resolution["id"]][0]
        assert mine["votes_for"] == 1, "The rejected second vote must not increment the tally"


class TestReserveCovenant:
    def test_monthly_deposit_rounds_up_to_next_cent(self, api):
        """PRD section 3.8: "a `MONTHLY_DEPOSIT` entry posts in the amount of
        one-tenth of one year's debt service per month: the annual debt service
        divided by 120, rounded up to the next whole cent." Annual 100000 ->
        ceil(100000/120) = 834. PRD section 3.3: closing "increments
        `current_billing_epoch` by 1".

        Design: Corner/calculations/reserve_monthly_deposit_ceil_rounding
        """
        ctx = setup_billed_invoice(usage_gallons=500, annual_debt_service_cents=100_000)
        district = ctx["district"]
        close_cycle(district["id"], ctx["cycle"]["id"], master_gallons=500)

        entries = get_success_data(api.list_reserve_entries(district["id"], TREASURER))
        deposits = [e for e in entries if e["entry_type"] == "MONTHLY_DEPOSIT"]
        assert len(deposits) == 1
        assert deposits[0]["amount_cents"] == 834
        assert deposits[0]["resulting_balance_cents"] == 834

        after = get_success_data(api.get_district(district["id"], TREASURER))
        assert after["reserve_balance_cents"] == 834
        assert after["reserve_target_cents"] == 100_000
        assert after["reserve_deficit_cents"] == 99_166
        assert after["current_billing_epoch"] == 1

    def _setup_amended_tiny_target(self, api):
        """District amended to annual 1000 (target 1000), one close deposits 9."""
        ctx = setup_member_with_installed_tap()
        district = ctx["district"]
        adopt_resolution(
            district["id"], "LOAN_AMENDMENT", district["id"],
            payload={"new_annual_debt_service_cents": 1000},
        )
        cycle = open_cycle(district["id"], **CYCLE_1)
        bill_cycle_with_readings(district["id"], cycle["id"], [(ctx["tap"]["id"], 3000)])
        close_cycle(district["id"], cycle["id"], master_gallons=3000)
        after = get_success_data(api.get_district(district["id"], TREASURER))
        return ctx, after

    def test_loan_amendment_resizes_target_and_deposit(self, api):
        """PRD section 3.8: "A `LOAN_AMENDMENT` resolution, on adoption, sets
        `annual_debt_service_cents` to the payload's `new_annual_debt_service_cents`,
        recomputes the reserve target, and recomputes covenant status." and "the
        annual debt service divided by 120, rounded up to the next whole cent."
        After amendment to 1000, one close posts ceil(1000/120) = 9.

        Design: Difficulty/combinatorial_formula/reserve_covenant_threshold_formula
        """
        _, after = self._setup_amended_tiny_target(api)
        assert after["annual_debt_service_cents"] == 1000
        assert after["reserve_target_cents"] == 1000
        assert after["reserve_balance_cents"] == 9

    def test_withdrawal_below_floor_rejected_at_adoption(self, api):
        """PRD section 3.8: "A `RESERVE_WITHDRAWAL` resolution, on adoption, posts a
        `WITHDRAWAL_AUTH` entry for the negated `withdrawal_amount_cents` from the
        resolution's payload — but only if the balance after withdrawal remains at
        or above 75 percent of the target; a breach is rejected with
        `ERR_RESERVE_COVENANT_BREACH` (HTTP 409)." Balance 9, target 1000: a 1-cent
        withdrawal leaves 8, below the 750 floor.

        Design: Difficulty/combinatorial_formula/reserve_covenant_threshold_formula
        """
        ctx, before = self._setup_amended_tiny_target(api)
        district = ctx["district"]
        assert before["reserve_balance_cents"] == 9

        resolution = propose_resolution(
            district["id"], "RESERVE_WITHDRAWAL", district["id"],
            payload={"withdrawal_amount_cents": 1},
        )
        for uid in ("op-director-v1", "op-director-v2"):
            get_success_data(
                api.record_vote(
                    district["id"], resolution["id"], {"vote": "FOR"},
                    make_board_director_headers(uid),
                )
            )
        resp = api.record_vote(
            district["id"], resolution["id"], {"vote": "FOR"},
            make_board_director_headers("op-director-v3"),
        )
        validate_error(resp, ApiErrorId.ERR_RESERVE_COVENANT_BREACH, expected_status=409)

        after = get_success_data(api.get_district(district["id"], TREASURER))
        assert after["reserve_balance_cents"] == 9, "A rejected adoption must not move the reserve"
        entries = get_success_data(api.list_reserve_entries(district["id"], TREASURER))
        assert not [e for e in entries if e["entry_type"] == "WITHDRAWAL_AUTH"]

    def test_withdrawal_landing_exactly_on_floor_succeeds(self, api):
        """PRD section 3.8: "but only if the balance after withdrawal remains at or
        above 75 percent of the target; a breach is rejected with
        `ERR_RESERVE_COVENANT_BREACH` (HTTP 409)." Balance 1000, target 1200: a
        100-cent withdrawal leaves 900, exactly at the 900 floor, and is adopted.

        Design: Corner/validations/reserve_withdrawal_at_exact_floor_succeeds
        """
        ctx = setup_billed_invoice(usage_gallons=500)  # annual 120000
        district = ctx["district"]
        close_cycle(district["id"], ctx["cycle"]["id"], master_gallons=500)  # deposits 1000
        adopt_resolution(
            district["id"], "LOAN_AMENDMENT", district["id"],
            payload={"new_annual_debt_service_cents": 1200},
        )
        mid = get_success_data(api.get_district(district["id"], TREASURER))
        assert mid["reserve_balance_cents"] == 1000
        assert mid["reserve_target_cents"] == 1200

        version = get_district_version(district["id"])
        resolution = propose_resolution(
            district["id"], "RESERVE_WITHDRAWAL", district["id"],
            payload={"withdrawal_amount_cents": 100},
            expected_district_version=version,
        )
        adopted = None
        for uid in ("op-director-v1", "op-director-v2", "op-director-v3"):
            adopted = get_success_data(
                api.record_vote(
                    district["id"], resolution["id"], {"vote": "FOR"},
                    make_board_director_headers(uid),
                )
            )
        assert adopted["status"] == "ADOPTED"
        after = get_success_data(api.get_district(district["id"], TREASURER))
        assert after["reserve_balance_cents"] == 900
        assert after["reserve_target_cents"] == 1200
        entries = get_success_data(api.list_reserve_entries(district["id"], TREASURER))
        withdrawals = [e for e in entries if e["entry_type"] == "WITHDRAWAL_AUTH"]
        assert len(withdrawals) == 1
        assert withdrawals[0]["amount_cents"] == -100
        assert withdrawals[0]["resulting_balance_cents"] == 900


class TestAnnexationLifecycle:
    def _setup_rejected_petition(self, api):
        district = create_district(district_name="D6")
        area = create_area(district["id"])
        petition = create_petition(district["id"], area["id"], deposit_cents=100_000)
        advance_petition_to_vote(district["id"], petition["id"])
        resolution = fail_resolution(district["id"], "ANNEXATION_RATIFICATION", petition["id"])
        petition_after = get_success_data(
            api.list_annexation_petitions(district["id"], CLERK)
        )[0]
        return district, petition, resolution, petition_after

    def test_failed_ratification_cascades_petition_to_rejected(self, api):
        """PRD section 3.9: "failure happens the moment `votes_against` reaches 3
        with `votes_against` at least equal to `votes_for`" and "a failed
        ratification cascades the petition `APPROVED_PENDING_VOTE → REJECTED`."

        Design: Difficulty/non_linear_state_machine/annexation_petition_rejection_resubmission_cycle
        """
        _, _, resolution, petition_after = self._setup_rejected_petition(api)
        assert resolution["status"] == "FAILED"
        assert resolution["votes_against"] == 3
        assert petition_after["status"] == "REJECTED"

    def test_resubmission_reopens_cycle_with_topped_up_deposit(self, api):
        """PRD section 3.10: "A failed ratification leaves the petition `REJECTED`,
        from which a clerk may resubmit it back to `SUBMITTED` with a top-up: the
        request carries `additional_deposit_cents` (zero or more), which is added
        to `deposit_cents` — so a later fee split computes against the topped-up
        total."

        Design: Difficulty/non_linear_state_machine/annexation_petition_rejection_resubmission_cycle
        """
        district, petition, _, _ = self._setup_rejected_petition(api)
        resubmitted = get_success_data(
            api.resubmit_petition(district["id"], petition["id"], {"additional_deposit_cents": 50_000}, CLERK)
        )
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["deposit_cents"] == 150_000

    def test_withdrawal_fee_split_floor_leg_conserves_deposit(self, api):
        """PRD section 3.10: "the district retains a `feasibility_fee_cents` equal
        to the larger of 25,000 cents and one-fifth of the cumulative deposit — the
        percentage leg computed on the full `deposit_cents` including any
        resubmission top-ups and rounded half-up to integer cents before the
        maximum is taken — and releases the remainder as `refund_cents`." Deposit
        100000 -> fee 25000 (floor leg), refund 75000; 25000 + 75000 == 100000.

        Design: Difficulty/compensating_invariant/annexation_withdrawal_conserves_deposit_split
        """
        district = create_district(district_name="D18")
        area = create_area(district["id"])
        petition = create_petition(district["id"], area["id"], deposit_cents=100_000)
        get_success_data(api.begin_petition_review(district["id"], petition["id"], CLERK))
        withdrawn = get_success_data(api.withdraw_petition(district["id"], petition["id"], CLERK))
        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["feasibility_fee_cents"] == 25_000
        assert withdrawn["refund_cents"] == 75_000
        assert withdrawn["feasibility_fee_cents"] + withdrawn["refund_cents"] == withdrawn["deposit_cents"]

    def test_withdrawal_fee_split_percentage_leg_conserves_deposit(self, api):
        """PRD section 3.10: "the district retains a `feasibility_fee_cents` equal
        to the larger of 25,000 cents and one-fifth of the cumulative deposit —
        the percentage leg computed on the full `deposit_cents` including any
        resubmission top-ups and rounded half-up to integer cents before the
        maximum is taken — and releases the remainder as `refund_cents`." Deposit
        200000 -> fee 40000 (percentage leg), refund 160000.

        Design: Difficulty/compensating_invariant/annexation_withdrawal_conserves_deposit_split
        """
        district = create_district(district_name="D18b")
        area = create_area(district["id"])
        petition = create_petition(district["id"], area["id"], deposit_cents=200_000)
        get_success_data(api.begin_petition_review(district["id"], petition["id"], CLERK))
        withdrawn = get_success_data(api.withdraw_petition(district["id"], petition["id"], CLERK))
        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["feasibility_fee_cents"] == 40_000
        assert withdrawn["refund_cents"] == 160_000
        assert withdrawn["feasibility_fee_cents"] + withdrawn["refund_cents"] == withdrawn["deposit_cents"]
