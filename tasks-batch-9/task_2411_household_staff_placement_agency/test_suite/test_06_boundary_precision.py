"""Off-by-one probes on the five boundaries the PRD states with strict or
inclusive wording: the half-open fee band, the 70-point presentation gate, the
eve of guarantee expiry, the expiry date itself, and the net-terms due date.

Each pair holds every other input fixed and moves the boundary quantity by the
smallest step the domain admits — one cent, one month, one day, one minute.
"""
from test_helpers import (
    BILLING,
    CONSULTANT,
    SENIOR_SCENARIO,
    api_client,
    create_onboarded_household,
    create_replacement_claim_payload,
    create_trial_engagement_payload,
    file_claim,
    find_ledger_entries,
    find_milestone,
    finalize_scope,
    invoice_and_pay,
    invoice_milestone,
    open_requisition,
    order_background_verification,
    pay_milestone,
    publish_fee_schedule,
    read_candidate,
    read_client,
    read_ledger,
    read_milestone,
    read_milestones,
    read_placement,
    read_requisition,
    record_background_result,
    record_reference,
    register_candidate,
    review_claim,
    run_scoping_round,
    set_clock,
    setup_senior_scenario,
    validate_error,
    validate_paginated,
    verify_reference,
)

KELMSCOTT = {
    "household_name": "Kelmscott House",
    "primary_contact_email": "ops@kelmscott.example",
    "region_code": "NY",
}
LYNDHURST = {
    "household_name": "Lyndhurst Villa",
    "primary_contact_email": "ops@lyndhurst.example",
    "region_code": "FL",
}


def _two_touching_estate_manager_bands():
    """Bands [0, 15,000,000) at 2000 bps and [15,000,000, 30,000,000) at 2233."""
    lower = publish_fee_schedule(
        role_type="ESTATE_MANAGER",
        comp_band_floor_cents=0,
        comp_band_ceiling_cents=15_000_000,
        fee_percent_bps=2000,
        guarantee_window_days=90,
        effective_from="2026-01-01",
    )
    upper = publish_fee_schedule(
        role_type="ESTATE_MANAGER",
        comp_band_floor_cents=15_000_000,
        comp_band_ceiling_cents=30_000_000,
        fee_percent_bps=2233,
        guarantee_window_days=90,
        effective_from="2026-01-01",
    )
    return lower, upper


def _priced_requisition(client, compensation, note):
    requisition = open_requisition(
        client,
        role_type="ESTATE_MANAGER",
        first_year_compensation_cents=compensation,
        schedule_pattern="FIVE_TWO",
        live_in_required=False,
    )
    requisition = run_scoping_round(requisition, scope_note=note)
    return finalize_scope(requisition, note="Scope agreed with the household.")


def _housekeeper_search():
    client = create_onboarded_household(**LYNDHURST)
    publish_fee_schedule(
        role_type="HOUSEKEEPER",
        comp_band_floor_cents=0,
        comp_band_ceiling_cents=15_000_000,
        fee_percent_bps=1800,
        guarantee_window_days=60,
        effective_from="2026-01-01",
    )
    requisition = open_requisition(
        client,
        role_type="HOUSEKEEPER",
        first_year_compensation_cents=6_200_000,
        schedule_pattern="FIVE_TWO",
        live_in_required=False,
    )
    requisition = run_scoping_round(
        requisition, scope_note="Beach house, seasonal cover."
    )
    return client, finalize_scope(requisition)


def _cleared_housekeeper(full_name, contact_email, second_end_month, provider):
    """Ten years of service and two chained references, the second of which ends
    in the month supplied — the only quantity that moves between the pair."""
    candidate = register_candidate(
        full_name=full_name,
        contact_email=contact_email,
        primary_role_type="HOUSEKEEPER",
        years_experience=10,
        live_in_willing=False,
    )
    first = record_reference(
        candidate,
        principal_employer_name="Cadogan Family",
        employment_start_month="2023-01",
        employment_end_month="2023-12",
        contact_email="cadogan@mail.example",
    )
    second = record_reference(
        candidate,
        prior_reference_id=first["id"],
        principal_employer_name="Latimer Family",
        employment_start_month="2024-01",
        employment_end_month=second_end_month,
        contact_email="latimer@mail.example",
    )
    verify_reference(first)
    verify_reference(second)
    record_background_result(
        order_background_verification(
            candidate,
            provider_reference=provider,
            scope_items=["IDENTITY", "CRIMINAL"],
        ),
        "CLEARED",
    )
    return read_candidate(candidate)


class TestFeeBandHalfOpenBoundary:
    def test_01_one_cent_under_the_ceiling_belongs_to_the_lower_band(self):
        """14,999,999 resolves the 2000 bps band and rounds 2999999.8 up.

        PRD §3.2: "The bands are therefore **half-open**: a compensation figure
        landing exactly on a band's floor belongs to that band, while a figure
        landing exactly on a band's ceiling belongs to the next band up."

        Design: Difficulty/boundary_precision_check/fee_band_floor_is_inclusive_and_the_ceiling_is_exclusive
        """
        client = create_onboarded_household(**KELMSCOTT)
        lower, _ = _two_touching_estate_manager_bands()

        requisition = _priced_requisition(
            client, 14_999_999, "One cent under the band boundary."
        )
        assert requisition["status"] == "SOURCING"
        assert requisition["resolved_fee_schedule_id"] == lower["id"]
        assert requisition["fee_percent_bps"] == 2000
        assert requisition["guarantee_window_days"] == 90
        assert requisition["provisional_fee_cents"] == 3_000_000

    def test_02_exactly_on_the_floor_belongs_to_the_upper_band(self):
        """One more cent of compensation moves the fee by 349,500 cents.

        PRD §3.2: "The candidate set contains every `FeeSchedule` row whose
        `status` is `ACTIVE`, whose `role_type` equals the role type being priced,
        and whose band covers the subject compensation figure — meaning
        `comp_band_floor_cents` is less than or equal to that figure, and either
        `comp_band_ceiling_cents` is null or the figure is strictly less than
        `comp_band_ceiling_cents`."

        Design: Difficulty/boundary_precision_check/fee_band_floor_is_inclusive_and_the_ceiling_is_exclusive
        """
        client = create_onboarded_household(**KELMSCOTT)
        lower, upper = _two_touching_estate_manager_bands()

        low = _priced_requisition(
            client, 14_999_999, "One cent under the band boundary."
        )
        high = _priced_requisition(
            client, 15_000_000, "Exactly on the band boundary."
        )
        assert high["status"] == "SOURCING"
        assert high["resolved_fee_schedule_id"] == upper["id"]
        assert high["fee_percent_bps"] == 2233
        assert high["guarantee_window_days"] == 90
        assert high["provisional_fee_cents"] == 3_349_500
        assert high["provisional_fee_cents"] - low["provisional_fee_cents"] == 349_500
        assert low["resolved_fee_schedule_id"] == lower["id"]

    def test_03_bands_that_merely_touch_are_both_published(self):
        """A shared 15,000,000 edge is adjacency, not an overlap.

        PRD §3.2: "Overlap is judged on half-open ranges, so bands that merely
        touch — one band's ceiling exactly equal to the next band's floor — do not
        overlap and are accepted."

        Design: Difficulty/boundary_precision_check/fee_band_floor_is_inclusive_and_the_ceiling_is_exclusive
        """
        lower, upper = _two_touching_estate_manager_bands()
        assert lower["status"] == "ACTIVE"
        assert upper["status"] == "ACTIVE"
        assert lower["id"] != upper["id"]
        assert lower["comp_band_ceiling_cents"] == upper["comp_band_floor_cents"]
        assert lower["effective_from"] == upper["effective_from"]


class TestPresentationScoreBoundary:
    def test_04_a_screening_score_of_exactly_seventy_is_admitted(self):
        """Sixteen coverage months put the candidate on the gate exactly.

        PRD §3.4: "**The presentation score gate** is checked after the cap: the
        candidate's `screening_score` must be at least 70 points, and a lower
        score is refused with `ERR_CANDIDATE_SCORE_BELOW_THRESHOLD` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/screening_score_of_seventy_books_the_trial_and_sixtynine_is_refused
        """
        _, requisition = _housekeeper_search()
        candidate = _cleared_housekeeper(
            "F. Adeyemi", "fa@mail.example", "2024-04", "BV-1101"
        )
        assert candidate["vetting_status"] == "CLEARED"
        assert candidate["reference_coverage_months"] == 16
        assert candidate["longest_contiguous_months"] == 16
        assert candidate["screening_score"] == 70

        response = api_client.create_trial_engagement(
            requisition["id"],
            create_trial_engagement_payload(
                candidate["id"],
                engagement_type="TRIAL_DAY",
                day_rate_cents=30_000,
                start_at="2026-08-17T09:00:00Z",
                end_at="2026-08-17T17:00:00Z",
            ),
            CONSULTANT,
        )
        assert response.status_code == 201, response.text
        assert response.json()["data"]["status"] == "SCHEDULED"
        assert read_requisition(requisition)["status"] == "TRIALING"
        assert read_candidate(candidate)["availability_status"] == "ON_TRIAL"

    def test_05_one_month_less_history_scores_sixtynine_and_is_refused(self):
        """The refused dossier differs from the admitted one by one month.

        PRD §3.3: "**Coverage points** are the candidate's
        `reference_coverage_months`, capped at 20 points, so a candidate with
        twenty or more merged verified months is at the cap."

        Design: Difficulty/boundary_precision_check/screening_score_of_seventy_books_the_trial_and_sixtynine_is_refused
        """
        _, requisition = _housekeeper_search()
        candidate = _cleared_housekeeper(
            "H. Petrov", "hp@mail.example", "2024-03", "BV-1102"
        )
        assert candidate["vetting_status"] == "CLEARED"
        assert candidate["reference_coverage_months"] == 15
        assert candidate["screening_score"] == 69

        response = api_client.create_trial_engagement(
            requisition["id"],
            create_trial_engagement_payload(
                candidate["id"],
                engagement_type="TRIAL_DAY",
                day_rate_cents=30_000,
                start_at="2026-08-19T09:00:00Z",
                end_at="2026-08-19T17:00:00Z",
            ),
            CONSULTANT,
        )
        validate_error(response, "ERR_CANDIDATE_SCORE_BELOW_THRESHOLD")

        rows, _ = validate_paginated(
            api_client.list_trial_engagements(
                CONSULTANT, {"candidate_id": candidate["id"]}
            )
        )
        assert rows == []
        assert read_requisition(requisition)["status"] == "SOURCING"
        assert read_candidate(candidate)["availability_status"] == "AVAILABLE"


class TestGuaranteeEve:
    def _refund_approved_on_the_eve(self):
        scenario = setup_senior_scenario(stage="placement_active")
        scenario["milestones"][0] = invoice_and_pay(scenario["milestones"][0])
        set_clock("2026-11-29T09:00:00Z")
        scenario["placement"] = read_placement(scenario["placement"])
        claim = file_claim(
            scenario["placement"], scenario["client_headers"], "REFUND", "2026-11-29"
        )
        scenario["claim"] = review_claim(
            review_claim(claim, "OPEN_REVIEW"), "APPROVE_REFUND"
        )
        return scenario

    def test_06_the_day_before_expiry_admits_a_claim_worth_one_unused_day(self):
        """89 of the 90 days are elapsed and exactly one remains unused.

        PRD §3.8: "Because the window is half-open, a claim filed on the day
        immediately before `guarantee_expires_on` is admissible and yields exactly
        one unused day, while a claim filed on `guarantee_expires_on` itself is
        refused."

        Design: Difficulty/boundary_precision_check/guarantee_expiry_eve_admits_a_claim_worth_one_unused_day
        """
        scenario = setup_senior_scenario(stage="placement_active")
        set_clock("2026-11-29T09:00:00Z")
        placement = read_placement(scenario["placement"])
        assert placement["guarantee_expires_on"] == "2026-11-30"
        assert placement["guarantee_window_days"] == 90
        assert placement["placement_status"] == "ACTIVE"

        claim = file_claim(
            placement, scenario["client_headers"], "REFUND", "2026-11-29"
        )
        assert claim["status"] == "SUBMITTED"
        assert claim["unused_days"] is None

        decided = review_claim(review_claim(claim, "OPEN_REVIEW"), "APPROVE_REFUND")
        assert decided["status"] == "APPROVED_REFUND"
        assert decided["elapsed_days"] == 89
        assert decided["unused_days"] == 1

    def test_07_one_unused_day_prorates_into_the_lowest_retention_tier(self):
        """A gross under 1,000,000 retains 500 bps, not 750 or 1000.

        PRD §3.8: "Step three: `gross_refund_cents` is the placement's `fee_cents`
        multiplied by `unused_days`, divided by `guarantee_window_days`, rounded
        half up."

        Design: Difficulty/boundary_precision_check/guarantee_expiry_eve_admits_a_claim_worth_one_unused_day
        """
        scenario = self._refund_approved_on_the_eve()
        claim = scenario["claim"]
        assert read_placement(scenario["placement"])["fee_cents"] == 3_349_499
        assert claim["gross_refund_cents"] == 37_217
        assert claim["gross_refund_cents"] < 1_000_000
        assert claim["retained_admin_fee_cents"] == 1_861
        assert claim["net_refund_cents"] == 35_356

        entries = read_ledger(scenario["client"])
        refunds = find_ledger_entries(entries, "REFUND_ISSUED")
        assert len(refunds) == 1
        assert refunds[0]["signed_amount_cents"] == -35_356
        assert read_client(scenario["client"])["outstanding_balance_cents"] == -35_356


class TestGuaranteeExpiryDate:
    def test_08_the_sweep_expires_the_guarantee_on_the_expiry_date_itself(self):
        """One hour before midnight the placement is still ACTIVE.

        PRD §2.6: "Second, every `Placement` whose `placement_status` is `ACTIVE`
        and whose `guarantee_expires_on` is on or before the new clock date moves
        to `GUARANTEE_EXPIRED`."

        Design: Difficulty/boundary_precision_check/guarantee_expiry_day_of_sweep_locks_the_window
        """
        scenario = setup_senior_scenario(stage="placement_active")
        set_clock("2026-11-29T23:00:00Z")
        eve = read_placement(scenario["placement"])
        assert eve["placement_status"] == "ACTIVE"
        assert eve["guarantee_expires_on"] == SENIOR_SCENARIO["GUARANTEE_EXPIRES_ON"]

        sweep = set_clock("2026-11-30T00:00:00Z")
        assert sweep["placements_guarantee_expired"] == 1
        assert sweep["milestones_marked_overdue"] == 0

        after = read_placement(eve)
        assert after["placement_status"] == "GUARANTEE_EXPIRED"
        assert after["version"] == eve["version"] + 1

    def test_09_a_claim_on_the_expiry_date_is_refused(self):
        """The OCC token is current, so only the window rule can refuse this.

        PRD §3.8: "The window must still be open: a logical-clock date on or after
        `guarantee_expires_on`, or a placement whose `placement_status` is already
        `GUARANTEE_EXPIRED`, is refused with `ERR_GUARANTEE_WINDOW_EXPIRED` (HTTP
        409)."

        Design: Difficulty/boundary_precision_check/guarantee_expiry_day_of_sweep_locks_the_window
        """
        scenario = setup_senior_scenario(stage="placement_active")
        set_clock("2026-11-29T23:00:00Z")
        set_clock("2026-11-30T00:00:00Z")
        placement = read_placement(scenario["placement"])
        assert placement["placement_status"] == "GUARANTEE_EXPIRED"

        response = api_client.create_replacement_claim(
            placement["id"],
            create_replacement_claim_payload(
                "REFUND", "2026-11-30", placement["version"]
            ),
            scenario["client_headers"],
        )
        validate_error(response, "ERR_GUARANTEE_WINDOW_EXPIRED")

        rows, _ = validate_paginated(
            api_client.list_placement_replacement_claims(
                placement["id"], scenario["client_headers"]
            )
        )
        assert rows == []
        assert read_placement(placement)["version"] == placement["version"]


class TestNetTermsBoundary:
    def _invoiced_engagement(self):
        scenario = setup_senior_scenario(stage="placement_active")
        milestone = invoice_milestone(
            find_milestone(read_milestones(scenario["placement"]), "ENGAGEMENT")
        )
        scenario["engagement"] = milestone
        return scenario

    def test_10_a_clock_landing_on_the_due_date_leaves_the_row_invoiced(self):
        """23:59 on the due date is still not strictly after it.

        PRD §2.6: "First, every `FeeMilestone` whose `invoice_status` is
        `INVOICED` and whose `due_date` falls strictly before the new clock date
        moves to `OVERDUE`; a clock landing exactly on `due_date` leaves the
        milestone `INVOICED`."

        Design: Difficulty/boundary_precision_check/milestone_becomes_overdue_only_after_the_due_date_has_passed
        """
        scenario = self._invoiced_engagement()
        milestone = scenario["engagement"]
        assert milestone["invoiced_on"] == "2026-09-01"
        assert milestone["due_date"] == "2026-09-15"
        assert milestone["invoice_status"] == "INVOICED"

        sweep = set_clock("2026-09-15T23:59:00Z")
        assert sweep["milestones_marked_overdue"] == 0
        assert read_milestone(milestone)["invoice_status"] == "INVOICED"

    def test_11_the_first_minute_past_the_due_date_ages_the_row(self):
        """One minute later the same row is counted once and moves.

        PRD §3.7: "Advancing the logical clock ages every `INVOICED` row whose
        `due_date` is **strictly before** the new clock date to `OVERDUE`; a clock
        landing exactly on `due_date` leaves the row `INVOICED`."

        Design: Difficulty/boundary_precision_check/milestone_becomes_overdue_only_after_the_due_date_has_passed
        """
        scenario = self._invoiced_engagement()
        milestone = scenario["engagement"]
        set_clock("2026-09-15T23:59:00Z")

        sweep = set_clock("2026-09-16T00:00:00Z")
        assert sweep["milestones_marked_overdue"] == 1

        aged = read_milestone(milestone)
        assert aged["invoice_status"] == "OVERDUE"
        assert aged["amount_cents"] == 1_004_850
        assert aged["version"] == milestone["version"] + 1
        assert read_client(scenario["client"])["outstanding_balance_cents"] == 1_004_850

    def test_12_an_overdue_row_still_accepts_its_exact_payment(self):
        """Ageing moves no money and closes no door.

        PRD §3.7: "The row must be `INVOICED` or `OVERDUE`, and any other
        non-terminal state is refused with `ERR_MILESTONE_NOT_INVOICED` (HTTP 409)
        while a terminal row is refused with `ERR_ENTITY_TERMINAL`."

        Design: Difficulty/boundary_precision_check/milestone_becomes_overdue_only_after_the_due_date_has_passed
        """
        scenario = self._invoiced_engagement()
        set_clock("2026-09-16T00:00:00Z")
        aged = read_milestone(scenario["engagement"])
        assert aged["invoice_status"] == "OVERDUE"

        paid = pay_milestone(aged, 1_004_850)
        assert paid["invoice_status"] == "PAID"
        assert paid["paid_on"] == "2026-09-16"
        assert read_client(scenario["client"])["outstanding_balance_cents"] == 0
        assert api_client.get_fee_milestone(aged["id"], BILLING).status_code == 200
