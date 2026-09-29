"""The arithmetic of the agency: fee resolution, allocation, scores, refund
proration, the poaching penalty and the ledger fold.

Every figure asserted here is pinned by the PRD to a single value, so each test
picks the inputs that separate the declared order of operations from the
plausible rearrangements of it.
"""
from test_helpers import (
    BILLING,
    CASE_RESOLVER,
    CONSULTANT,
    PRINCIPAL,
    VERIFIER,
    api_client,
    append_ledger_adjustment,
    create_placement_payload,
    file_enforcement_case,
    finalize_scope,
    finalize_scope_payload,
    investigate_case,
    ledger_adjustment_payload,
    read_candidate,
    read_client,
    read_ledger,
    read_milestones,
    read_placement,
    read_requisition,
    resolve_case_payload,
    review_claim_payload,
    set_clock,
    setup_active_placement,
    setup_claim_under_review,
    setup_investigating_case,
    setup_scenario,
    validate_error,
    validate_success,
    verify_reference,
    verify_reference_payload,
)

START_DATE_CLOCK = "2026-09-01T00:00:00Z"
SEPARATION_DATE = "2026-10-16"
DISCOVERED_ON = "2026-10-01"


class TestFeeResolution:
    def test_01_the_band_with_the_greatest_effective_from_wins(self):
        """Two bands cover the figure, so recency decides which one is stamped.

        PRD §3.2: "The winner among the candidates is the row with the greatest
        `effective_from`; when two or more share that greatest `effective_from`,
        the tie is broken by `created_at` ascending, so the earliest-created of
        the tied rows wins."

        PRD §3.2: "The winner's identifier is stamped as the subject's
        fee-schedule reference, and its `fee_percent_bps` and
        `guarantee_window_days` are copied onto the subject."

        Design: Corner/calculations/fee_resolution_picks_the_band_with_the_greatest_effective_from
        """
        scenario = setup_scenario(
            stage="scoping",
            fee_schedules=[
                {},
                {
                    "effective_from": "2026-06-01",
                    "fee_percent_bps": 2500,
                    "guarantee_window_days": 120,
                },
            ],
        )
        earlier, later = scenario["fee_schedules"]

        data = finalize_scope(scenario["requisition"])
        assert data["resolved_fee_schedule_id"] == later["id"]
        assert data["resolved_fee_schedule_id"] != earlier["id"]
        assert data["fee_percent_bps"] == 2500
        assert data["guarantee_window_days"] == 120
        assert data["provisional_fee_cents"] == 2_500_000
        assert data["status"] == "SOURCING"

    def test_02_a_band_for_another_role_type_is_not_a_candidate(self):
        """The newer band prices CHEF work, so the housekeeper band still wins.

        PRD §3.2: "The candidate set contains every `FeeSchedule` row whose
        `status` is `ACTIVE`, whose `role_type` equals the role type being priced,
        and whose band covers the subject compensation figure — meaning
        `comp_band_floor_cents` is less than or equal to that figure, and either
        `comp_band_ceiling_cents` is null or the figure is strictly less than
        `comp_band_ceiling_cents`."

        Design: Corner/calculations/fee_resolution_ignores_a_band_published_for_another_role_type
        """
        scenario = setup_scenario(
            stage="scoping",
            fee_schedules=[
                {},
                {
                    "role_type": "CHEF",
                    "effective_from": "2026-07-01",
                    "fee_percent_bps": 2500,
                    "guarantee_window_days": 120,
                },
            ],
        )
        housekeeper_band, chef_band = scenario["fee_schedules"]

        data = finalize_scope(scenario["requisition"])
        assert data["resolved_fee_schedule_id"] == housekeeper_band["id"]
        assert data["resolved_fee_schedule_id"] != chef_band["id"]
        assert data["fee_percent_bps"] == 2000
        assert data["guarantee_window_days"] == 90
        assert data["provisional_fee_cents"] == 2_000_000

    def test_03_a_compensation_on_the_only_ceiling_has_no_candidate_set(self):
        """The half-open band sends the figure to a band nobody published.

        PRD §3.2: "The bands are therefore **half-open**: a compensation figure
        landing exactly on a band's floor belongs to that band, while a figure
        landing exactly on a band's ceiling belongs to the next band up."

        PRD §3.2: "When the candidate set is empty the resolution has no result at
        all and the calling operation is refused with `ERR_NO_FEE_SCHEDULE_MATCH`
        (HTTP 422); the most common way to hit this is a compensation figure equal
        to the top band's ceiling when no unbounded band has been published above
        it."

        Design: Corner/calculations/a_compensation_on_the_top_ceiling_resolves_to_no_band
        """
        scenario = setup_scenario(
            stage="scoping",
            requisition={"first_year_compensation_cents": 15_000_000},
        )

        validate_error(
            api_client.finalize_scope(
                scenario["requisition"]["id"], finalize_scope_payload(), CONSULTANT
            ),
            "ERR_NO_FEE_SCHEDULE_MATCH",
            422,
        )

        after = read_requisition(scenario["requisition"])
        assert after["status"] == "SCOPING"
        assert after["fee_percent_bps"] is None
        assert after["provisional_fee_cents"] is None

    def test_04_the_provisional_fee_rounds_the_half_cent_upwards(self):
        """The exact product is 12500.5, the one case that separates the modes.

        PRD §3.2: "Take the requisition's `first_year_compensation_cents`,
        multiply it by the `fee_percent_bps` just resolved, divide by 10000, and
        round the result half up to a whole number of cents; that value is stamped
        as the requisition's `provisional_fee_cents`."

        PRD §3.2: "There is exactly one rounding operation, and it is applied to
        the aggregate compensation figure."

        Design: Corner/calculations/the_provisional_fee_rounds_the_aggregate_once_half_up
        """
        scenario = setup_scenario(
            stage="scoping",
            fee_schedules=[{"fee_percent_bps": 1250}],
            requisition={"first_year_compensation_cents": 100_004},
        )

        data = finalize_scope(scenario["requisition"])
        assert data["fee_percent_bps"] == 1250
        assert data["provisional_fee_cents"] == 12501

        as_billing = validate_success(
            api_client.get_requisition(scenario["requisition"]["id"], BILLING)
        )
        assert as_billing["provisional_fee_cents"] == 12501


class TestMilestoneAllocation:
    def test_05_the_last_open_milestone_takes_the_indivisible_remainder(self):
        """A fee of 1000001 cannot be split by 3000/3000/4000 without a remainder.

        PRD §3.7: "Then, walking the open rows in ascending `sequence_no` order,
        every open row **except the last** receives the remaining amount
        multiplied by that row's `weight_bps`, divided by the open weight total,
        rounded half up; the **last** open row receives the exact arithmetic
        remainder — the remaining amount less the sum of whatever has just been
        assigned in this pass."

        PRD §3.7: "The invariant this guarantees, and which must hold after every
        run: the sum of `amount_cents` over all of the placement's `FeeMilestone`
        rows whose `invoice_status` is not `VOIDED` equals the placement's
        `fee_cents` exactly."

        Design: Corner/calculations/the_last_open_milestone_absorbs_the_allocation_remainder
        """
        scenario = setup_scenario(
            stage="term_accepted",
            requisition={"first_year_compensation_cents": 5_000_005},
        )
        requisition = read_requisition(scenario["requisition"])
        assert requisition["provisional_fee_cents"] == 1_000_001

        placement = validate_success(
            api_client.create_placement(
                create_placement_payload(
                    requisition["id"],
                    scenario["candidate"]["id"],
                    requisition["version"],
                    base_salary_cents=3_000_005,
                    guaranteed_bonus_cents=1_000_000,
                    accommodation_imputed_cents=0,
                    overtime_allowance_cents=1_000_000,
                ),
                CONSULTANT,
            ),
            201,
        )
        assert placement["fee_cents"] == 1_000_001
        assert placement["fee_variant"] == "PROVISIONAL"

        milestones = read_milestones(placement)
        assert [row["amount_cents"] for row in milestones] == [
            300_000,
            300_000,
            400_001,
        ]
        assert sum(row["amount_cents"] for row in milestones) == 1_000_001
        assert [row["invoice_status"] for row in milestones] == ["PENDING"] * 3

    def test_06_the_final_fee_is_spread_over_three_still_open_rows(self):
        """Nothing has been invoiced, so the whole FINAL fee is re-allocated.

        PRD §3.6: "Then the **`FINAL` fee** is computed: each of the four
        components is multiplied by the re-resolved `fee_percent_bps`, divided by
        10000 and **rounded half up individually**, in the fixed order
        `base_salary_cents`, then `guaranteed_bonus_cents`, then
        `accommodation_imputed_cents`, then `overtime_allowance_cents`; the four
        rounded results are then summed, and that sum is stored as `fee_cents`
        with `fee_variant` set to `FINAL`."

        PRD §3.6: "Then the milestone schedule is re-allocated as described in
        §3.7, freezing whatever has already been invoiced, aged or paid and
        pushing the whole delta into the still-`PENDING` rows."

        Design: Corner/calculations/the_final_fee_is_reallocated_across_the_open_milestones
        """
        scenario = setup_scenario(
            stage="placement_pending",
            placement={
                "base_salary_cents": 5_000_000,
                "guaranteed_bonus_cents": 1_000_000,
                "accommodation_imputed_cents": 0,
                "overtime_allowance_cents": 1_000_000,
            },
        )
        assert [row["amount_cents"] for row in scenario["milestones"]] == [
            600_000,
            600_000,
            800_000,
        ]
        set_clock(START_DATE_CLOCK)

        data = validate_success(
            api_client.confirm_placement_start(
                scenario["placement"]["id"],
                {"note": "Package confirmed on the start date."},
                PRINCIPAL,
            )
        )
        assert data["actual_first_year_compensation_cents"] == 7_000_000
        assert data["fee_variant"] == "FINAL"
        assert data["fee_cents"] == 1_400_000
        assert data["fee_percent_bps"] == 2000
        assert data["guarantee_expires_on"] == "2026-11-30"

        milestones = read_milestones(data)
        assert [row["amount_cents"] for row in milestones] == [
            420_000,
            420_000,
            560_000,
        ]
        assert sum(row["amount_cents"] for row in milestones) == 1_400_000
        assert [row["invoice_status"] for row in milestones] == ["PENDING"] * 3


class TestVettingScores:
    def test_07_one_missing_month_prevents_the_merge(self):
        """Coverage adds up while the longest run stays at six months.

        PRD §3.3: "The intervals are sorted by start month and then merged
        pairwise whenever two of them either overlap or are *adjacent*, where
        adjacency means the next interval's start month is the calendar month
        immediately following the previous interval's end month, leaving a gap of
        zero months."

        PRD §3.3: "A candidate advances `SCREENING → REFERENCES_VERIFIED` when the
        recomputed `verified_reference_count` is at least two **and** the
        recomputed `longest_contiguous_months` is at least twelve — one unbroken
        verified year."

        Design: Corner/calculations/disjoint_reference_periods_are_kept_apart
        """
        scenario = setup_scenario(
            stage="references_recorded",
            references=[
                {
                    "principal_employer_name": "Whitfield Residence",
                    "relationship_type": "PRINCIPAL_EMPLOYER",
                    "employment_start_month": "2022-01",
                    "employment_end_month": "2022-06",
                    "contact_email": "whitfield@mail.example",
                },
                {
                    "principal_employer_name": "Marlow Estate",
                    "relationship_type": "PRINCIPAL_EMPLOYER",
                    "employment_start_month": "2022-08",
                    "employment_end_month": "2023-01",
                    "contact_email": "marlow@mail.example",
                },
            ],
        )
        first, second = scenario["references"]
        verify_reference(first)

        data = validate_success(
            api_client.verify_reference_check(
                second["id"], verify_reference_payload("VERIFIED"), VERIFIER
            )
        )
        assert data["status"] == "VERIFIED"

        candidate = read_candidate(scenario["candidate"])
        assert candidate["verified_reference_count"] == 2
        assert candidate["reference_coverage_months"] == 12
        assert candidate["longest_contiguous_months"] == 6
        assert candidate["vetting_status"] == "SCREENING"
        assert candidate["screening_score"] == 66

    def test_08_pending_and_disputed_rows_are_outside_the_coverage_inputs(self):
        """Three rows exist and the dossier counts exactly one of them.

        PRD §3.3: "**Reference chain coverage** is computed over the candidate's
        `VERIFIED` reference rows only; `PENDING`, `UNREACHABLE` and `DISPUTED`
        rows contribute neither to the count nor to any month total."

        PRD §3.3: "**The disputed penalty** is 15 points for every
        `ReferenceCheck` of this candidate whose `status` is `DISPUTED`, and it is
        subtracted."

        Design: Corner/calculations/unverified_and_disputed_references_are_excluded_from_the_coverage_input_set
        """
        scenario = setup_scenario(
            stage="references_recorded",
            candidate={"years_experience": 4},
            references=[
                {
                    "principal_employer_name": "Whitfield Residence",
                    "relationship_type": "PRINCIPAL_EMPLOYER",
                    "employment_start_month": "2022-01",
                    "employment_end_month": "2022-12",
                    "contact_email": "whitfield@mail.example",
                },
                {
                    "principal_employer_name": "Marlow Estate",
                    "relationship_type": "PRINCIPAL_EMPLOYER",
                    "employment_start_month": "2023-01",
                    "employment_end_month": "2023-12",
                    "contact_email": "marlow@mail.example",
                },
                {
                    "principal_employer_name": "Pemberton House",
                    "relationship_type": "PRINCIPAL_EMPLOYER",
                    "employment_start_month": "2024-01",
                    "employment_end_month": "2024-06",
                    "contact_email": "pemberton@mail.example",
                },
            ],
        )
        first, _pending, third = scenario["references"]
        verify_reference(first)

        data = validate_success(
            api_client.verify_reference_check(
                third["id"], verify_reference_payload("DISPUTED"), VERIFIER
            )
        )
        assert data["status"] == "DISPUTED"

        candidate = read_candidate(scenario["candidate"])
        assert candidate["verified_reference_count"] == 1
        assert candidate["reference_coverage_months"] == 12
        assert candidate["longest_contiguous_months"] == 12
        assert candidate["screening_score"] == 36
        assert candidate["placement_ready_score"] == 21

    def test_09_all_three_point_caps_bind_at_once(self):
        """Experience, references and coverage each overshoot their own cap.

        PRD §3.3: "**Experience points** are the candidate's `years_experience`
        multiplied by three, capped at 36 points — so twelve years of service
        reaches the cap and further years add nothing."

        PRD §3.3: "**Reference points** are the sum, over the candidate's
        `VERIFIED` reference rows, of the weight of each row's
        `relationship_type` — twelve points for a `PRINCIPAL_EMPLOYER`, eight for
        an `AGENCY_SUPERVISOR`, four for a `PEER` — capped at 24 points."

        PRD §3.3: "**Coverage points** are the candidate's
        `reference_coverage_months`, capped at 20 points, so a candidate with
        twenty or more merged verified months is at the cap."

        Design: Corner/calculations/experience_reference_and_coverage_points_all_stop_at_their_caps
        """
        scenario = setup_scenario(
            stage="references_recorded",
            candidate={"years_experience": 20},
            references=[
                {
                    "principal_employer_name": "Whitfield Residence",
                    "relationship_type": "PRINCIPAL_EMPLOYER",
                    "employment_start_month": "2019-01",
                    "employment_end_month": "2019-12",
                    "contact_email": "whitfield@mail.example",
                },
                {
                    "principal_employer_name": "Marlow Estate",
                    "relationship_type": "PRINCIPAL_EMPLOYER",
                    "employment_start_month": "2020-01",
                    "employment_end_month": "2020-12",
                    "contact_email": "marlow@mail.example",
                    "chain_to_previous": True,
                },
                {
                    "principal_employer_name": "Pemberton House",
                    "relationship_type": "PRINCIPAL_EMPLOYER",
                    "employment_start_month": "2021-01",
                    "employment_end_month": "2021-12",
                    "contact_email": "pemberton@mail.example",
                    "chain_to_previous": True,
                },
            ],
        )
        first, second, third = scenario["references"]
        verify_reference(first)
        verify_reference(second)

        data = validate_success(
            api_client.verify_reference_check(
                third["id"], verify_reference_payload("VERIFIED"), VERIFIER
            )
        )
        assert data["status"] == "VERIFIED"

        candidate = read_candidate(scenario["candidate"])
        assert candidate["verified_reference_count"] == 3
        assert candidate["reference_coverage_months"] == 36
        assert candidate["longest_contiguous_months"] == 36
        assert candidate["screening_score"] == 80
        assert candidate["placement_ready_score"] == 80

    def test_10_each_relationship_type_is_weighted_on_its_own_row(self):
        """A supervisor and a peer are worth 12 points, not 24.

        PRD §3.3: "**Reference points** are the sum, over the candidate's
        `VERIFIED` reference rows, of the weight of each row's
        `relationship_type` — twelve points for a `PRINCIPAL_EMPLOYER`, eight for
        an `AGENCY_SUPERVISOR`, four for a `PEER` — capped at 24 points."

        PRD §3.3: "The gate out of `SCREENING` reads exactly those two figures."

        Design: Corner/calculations/each_referee_relationship_carries_its_own_weight
        """
        scenario = setup_scenario(
            stage="references_recorded",
            candidate={"years_experience": 5},
            references=[
                {
                    "principal_employer_name": "Whitfield Residence",
                    "relationship_type": "AGENCY_SUPERVISOR",
                    "employment_start_month": "2022-01",
                    "employment_end_month": "2022-12",
                    "contact_email": "whitfield@mail.example",
                },
                {
                    "principal_employer_name": "Marlow Estate",
                    "relationship_type": "PEER",
                    "employment_start_month": "2023-01",
                    "employment_end_month": "2023-12",
                    "contact_email": "marlow@mail.example",
                    "chain_to_previous": True,
                },
            ],
        )
        first, second = scenario["references"]
        verify_reference(first)

        data = validate_success(
            api_client.verify_reference_check(
                second["id"], verify_reference_payload("VERIFIED"), VERIFIER
            )
        )
        assert data["status"] == "VERIFIED"

        candidate = read_candidate(scenario["candidate"])
        assert candidate["screening_score"] == 47
        assert candidate["reference_coverage_months"] == 24
        assert candidate["longest_contiguous_months"] == 24
        assert candidate["vetting_status"] == "REFERENCES_VERIFIED"

    def test_11_the_placement_ready_score_is_clamped_at_zero(self):
        """Two disputes subtract 30 from a total of 5, and the field stays 0.

        PRD §3.3: "`placement_ready_score` is therefore experience points plus
        reference points plus coverage points plus background points minus the
        disputed penalty, floored at 0 so the field never goes negative."

        PRD §3.3: "`screening_score` is the sum of those three components and
        nothing else: background work is not yet expected when a candidate is
        being put in front of a household, so background points contribute zero,
        and disputed references are ignored entirely at this stage."

        Design: Corner/calculations/the_placement_ready_score_floors_at_zero
        """
        scenario = setup_scenario(
            stage="references_recorded",
            candidate={"years_experience": 0, "live_in_willing": False},
            references=[
                {
                    "principal_employer_name": "Whitfield Residence",
                    "relationship_type": "PEER",
                    "employment_start_month": "2022-01",
                    "employment_end_month": "2022-01",
                    "contact_email": "whitfield@mail.example",
                },
                {
                    "principal_employer_name": "Marlow Estate",
                    "relationship_type": "PRINCIPAL_EMPLOYER",
                    "employment_start_month": "2023-01",
                    "employment_end_month": "2023-06",
                    "contact_email": "marlow@mail.example",
                },
                {
                    "principal_employer_name": "Pemberton House",
                    "relationship_type": "PRINCIPAL_EMPLOYER",
                    "employment_start_month": "2024-01",
                    "employment_end_month": "2024-06",
                    "contact_email": "pemberton@mail.example",
                },
            ],
        )
        first, second, third = scenario["references"]
        verify_reference(first)
        verify_reference(second, "DISPUTED")

        data = validate_success(
            api_client.verify_reference_check(
                third["id"], verify_reference_payload("DISPUTED"), VERIFIER
            )
        )
        assert data["status"] == "DISPUTED"

        candidate = read_candidate(scenario["candidate"])
        assert candidate["verified_reference_count"] == 1
        assert candidate["reference_coverage_months"] == 1
        assert candidate["longest_contiguous_months"] == 1
        assert candidate["screening_score"] == 5
        assert candidate["placement_ready_score"] == 0


class TestRefundProration:
    def test_12_the_retention_tier_is_keyed_on_the_prorated_gross(self):
        """The gross lands on 1000000, the inclusive edge of the middle tier.

        PRD §3.8: "Step three: `gross_refund_cents` is the placement's `fee_cents`
        multiplied by `unused_days`, divided by `guarantee_window_days`, rounded
        half up."

        PRD §3.8: "Step four: the administrative retention rate is selected by
        tier **keyed on `gross_refund_cents`** — not on `fee_cents` and not on the
        amount invoiced — at 500 basis points when `gross_refund_cents` is below
        1,000,000, at 750 basis points when it is from 1,000,000 up to but
        excluding 3,000,000, and at 1000 basis points when it is 3,000,000 or
        more; `retained_admin_fee_cents` is `gross_refund_cents` multiplied by
        that rate, divided by 10000, rounded half up."

        PRD §3.8: "Step five: `net_refund_cents` is `gross_refund_cents` less
        `retained_admin_fee_cents`, an exact subtraction with no rounding."

        Design: Corner/calculations/the_admin_retention_tier_is_keyed_on_the_prorated_gross_at_its_boundary
        """
        scenario = setup_claim_under_review("REFUND", SEPARATION_DATE)
        assert scenario["placement"]["fee_cents"] == 2_000_000

        data = validate_success(
            api_client.review_replacement_claim(
                scenario["claim"]["id"],
                review_claim_payload("APPROVE_REFUND"),
                PRINCIPAL,
            )
        )
        assert data["status"] == "APPROVED_REFUND"
        assert data["elapsed_days"] == 45
        assert data["unused_days"] == 45
        assert data["gross_refund_cents"] == 1_000_000
        assert data["retained_admin_fee_cents"] == 75_000
        assert data["net_refund_cents"] == 925_000

        placement = read_placement(scenario["placement"])
        assert placement["placement_status"] == "TERMINATED_REFUNDED"
        assert placement["billing_status"] == "REFUNDED"

        client = read_client(scenario["client"])
        assert client["outstanding_balance_cents"] == -925_000

        milestones = read_milestones(scenario["placement"])
        assert milestones[0]["milestone_type"] == "ENGAGEMENT"
        assert milestones[0]["invoice_status"] == "PAID"
        assert [row["invoice_status"] for row in milestones[1:]] == [
            "VOIDED",
            "VOIDED",
        ]


class TestPenaltyComputation:
    def test_13_the_rate_tier_is_keyed_on_the_source_fee(self):
        """A base of exactly 2000000 buys the 7500 bps tier, not 10000 bps.

        PRD §3.9: "Step two: the rate is selected by a deliberately
        **regressive** tier keyed on that base — 10000 basis points, a full 100
        percent, when the base is below 2,000,000; 7500 basis points when the base
        is from 2,000,000 up to but excluding 5,000,000; and 5000 basis points
        when the base is 5,000,000 or more."

        PRD §3.9: "Step four: the rated amount is multiplied by one plus
        `prior_substantiated_count`, so a first offence is taken once, a first
        repeat twice, a second repeat three times; this multiplication is exact
        with no rounding."

        Design: Corner/calculations/the_poaching_rate_tier_is_keyed_on_the_base_at_its_boundary
        """
        scenario = setup_investigating_case(DISCOVERED_ON)
        assert scenario["placement"]["fee_cents"] == 2_000_000

        data = validate_success(
            api_client.resolve_non_solicitation_case(
                scenario["case"]["id"],
                resolve_case_payload("SUBSTANTIATE"),
                CASE_RESOLVER,
            )
        )
        assert data["status"] == "SUBSTANTIATED"
        assert data["prior_substantiated_count"] == 0
        assert data["penalty_cents"] == 1_500_000

        client = read_client(scenario["client"])
        assert client["status"] == "SUSPENDED"
        assert client["outstanding_balance_cents"] == 1_500_000

        entries = read_ledger(scenario["client"])
        assert len(entries) == 1
        assert entries[0]["entry_type"] == "PENALTY_ASSESSED"
        assert entries[0]["signed_amount_cents"] == 1_500_000
        assert entries[0]["balance_after_cents"] == 1_500_000

    def test_14_an_unnamed_source_placement_falls_back_to_the_floor(self):
        """With no source placement the base is the 750000 floor.

        PRD §3.9: "Step one: the base amount is the `fee_cents` of the placement
        named by `source_placement_id` when that field is set, and otherwise the
        penalty floor of 750,000 cents — $7,500."

        PRD §3.9: "Step five: the result is clamped, first raised to the floor of
        750,000 cents and then trimmed to the cap of 7,500,000 cents — $75,000 —
        and stored as `penalty_cents`."

        Design: Corner/calculations/the_penalty_floor_supplies_the_base_when_no_source_placement_is_named
        """
        scenario = setup_active_placement()
        set_clock(f"{DISCOVERED_ON}T00:00:00Z")
        case = file_enforcement_case(
            scenario["client"], scenario["candidate"], DISCOVERED_ON
        )
        assert case["source_placement_id"] is None
        investigate_case(case)

        data = validate_success(
            api_client.resolve_non_solicitation_case(
                case["id"], resolve_case_payload("SUBSTANTIATE"), CASE_RESOLVER
            )
        )
        assert data["status"] == "SUBSTANTIATED"
        assert data["penalty_cents"] == 750_000
        assert data["source_placement_id"] is None

        client = read_client(scenario["client"])
        assert client["outstanding_balance_cents"] == 750_000


class TestLedgerFold:
    def test_15_every_row_carries_the_balance_as_at_that_row(self):
        """Three mixed-sign movements are folded in sequence order.

        PRD §2.12: "A household's `outstanding_balance_cents` is the running fold
        of its ledger. Starting from zero, each row in ascending `sequence_no`
        order adds its `signed_amount_cents` to the running total, and the total
        after each row is what that row's `balance_after_cents` preserves; the
        household's `outstanding_balance_cents` is the total after the last row."

        PRD §3.7: "The append creates a `LedgerEntry` with the next `sequence_no`
        for that household, `related_ref_type` `NONE` and a null
        `related_ref_id`, stamps `balance_after_cents` with the running total as
        of that row, recomputes the household's `outstanding_balance_cents` and
        increments `Client.version`."

        Design: Corner/calculations/the_ledger_fold_stamps_a_running_balance_on_every_row
        """
        scenario = setup_scenario(stage="onboarded")
        append_ledger_adjustment(
            scenario["client"], 500_000, memo="Retainer received."
        )
        append_ledger_adjustment(
            scenario["client"], -200_000, memo="Partial credit applied."
        )

        data = validate_success(
            api_client.create_ledger_adjustment(
                scenario["client"]["id"],
                ledger_adjustment_payload(
                    100_000, memo="Late-cancellation charge."
                ),
                BILLING,
            ),
            201,
        )
        assert data["sequence_no"] == 3
        assert data["balance_after_cents"] == 400_000

        entries = read_ledger(scenario["client"])
        assert [row["sequence_no"] for row in entries] == [1, 2, 3]
        assert [row["balance_after_cents"] for row in entries] == [
            500_000,
            300_000,
            400_000,
        ]

        client = read_client(scenario["client"])
        assert client["outstanding_balance_cents"] == 400_000
