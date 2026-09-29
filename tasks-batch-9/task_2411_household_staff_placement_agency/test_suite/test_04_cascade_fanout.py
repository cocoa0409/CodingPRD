"""Single calls whose effects fan out across three, four or five entities.

Every hop is asserted separately, including the rows the request never names.
"""
from test_helpers import (
    CONSULTANT,
    add_vetted_candidate,
    adjudicate_background,
    api_client,
    assert_ledger_fold,
    book_trial,
    create_trial_engagement_payload,
    extend_offer,
    file_enforcement_case,
    finalize_scope,
    find_ledger_entries,
    find_milestone,
    investigate_case,
    invoice_milestone,
    open_requisition,
    order_background_verification,
    publish_fee_schedule,
    read_candidate,
    read_client,
    read_ledger,
    read_milestones,
    read_placement,
    read_requisition,
    read_trial,
    record_background_result,
    release_availability_payload,
    resolve_case,
    run_scoping_round,
    set_clock,
    setup_scenario,
    setup_senior_scenario,
    validate_error,
)

# An ESTATE_MANAGER search whose candidate is put on a trial day before the
# background screen comes back flagged.
ASHBY_OPTIONS = {
    "client": {
        "household_name": "Glenbrook House",
        "primary_contact_email": "ops@glenbrook.example",
        "region_code": "FL",
    },
    "signatory_name": "E. Glenbrook",
    "fee_schedules": [
        {
            "role_type": "ESTATE_MANAGER",
            "comp_band_floor_cents": 0,
            "comp_band_ceiling_cents": 15_000_000,
            "fee_percent_bps": 2100,
            "guarantee_window_days": 90,
            "effective_from": "2026-01-01",
        }
    ],
    "requisition": {
        "role_type": "ESTATE_MANAGER",
        "first_year_compensation_cents": 13_500_000,
        "schedule_pattern": "FIVE_TWO",
        "live_in_required": False,
    },
    "candidate": {
        "full_name": "L. Ashby",
        "contact_email": "la@mail.example",
        "primary_role_type": "ESTATE_MANAGER",
        "years_experience": 10,
        "live_in_willing": False,
    },
    "references": [
        {
            "principal_employer_name": "Harewood Estate",
            "relationship_type": "PRINCIPAL_EMPLOYER",
            "employment_start_month": "2022-01",
            "employment_end_month": "2022-12",
            "contact_email": "harewood@mail.example",
        },
        {
            "principal_employer_name": "Netherby Hall",
            "relationship_type": "PRINCIPAL_EMPLOYER",
            "employment_start_month": "2023-01",
            "employment_end_month": "2023-12",
            "contact_email": "netherby@mail.example",
            "chain_to_previous": True,
        },
    ],
}

ASHBY_TRIAL = {
    "engagement_type": "TRIAL_DAY",
    "day_rate_cents": 40_000,
    "start_at": "2026-08-20T09:00:00Z",
    "end_at": "2026-08-20T17:00:00Z",
}


def _flagged_candidate_on_a_scheduled_trial():
    """A candidate sitting on a SCHEDULED trial with a FLAGGED screen."""
    scenario = setup_scenario(stage="references_verified", **ASHBY_OPTIONS)
    scenario["trial"] = book_trial(
        scenario["requisition"], scenario["candidate"], **ASHBY_TRIAL
    )
    verification = order_background_verification(
        scenario["candidate"], provider_reference="BV-6001",
        scope_items=["IDENTITY", "CRIMINAL"],
    )
    scenario["background"] = record_background_result(verification, "FLAGGED")
    scenario["candidate"] = read_candidate(scenario["candidate"])
    return scenario


class TestAdjudicatedFailCascade:
    def test_01_one_fail_disposition_moves_four_rows(self):
        """The trial and the requisition were never named in the request.

        PRD §3.3: "`FAIL` moves the screen `FLAGGED → ADJUDICATED_FAIL` and fans
        a four-hop cascade: first the candidate's `vetting_status` moves
        `BACKGROUND_PENDING → REJECTED`; second, because the candidate is now
        rejected, every `TrialEngagement` of that candidate whose `status` is
        `SCHEDULED` or `IN_PROGRESS` moves to `CANCELLED` with `cancel_reason`
        `VETTING_FAILED`; third, because those trials have left the active set,
        every affected `RoleRequisition` sitting in `TRIALING` whose recomputed
        `active_trial_count` reaches 0 falls back to `SOURCING`; and fourth, the
        candidate's `availability_status` moves `ON_TRIAL → INACTIVE` with
        `cooling_off_until` cleared to null."

        Design: Difficulty/transitive_cascade/adjudicated_fail_cascades_through_candidate_trial_and_requisition
        """
        scenario = _flagged_candidate_on_a_scheduled_trial()
        requisition = read_requisition(scenario["requisition"])
        assert requisition["status"] == "TRIALING"
        assert requisition["active_trial_count"] == 1
        assert read_trial(scenario["trial"])["status"] == "SCHEDULED"
        candidate = scenario["candidate"]
        assert candidate["vetting_status"] == "BACKGROUND_PENDING"
        assert candidate["availability_status"] == "ON_TRIAL"

        adjudicated = adjudicate_background(
            scenario["background"], "FAIL", candidate["version"]
        )
        assert adjudicated["status"] == "ADJUDICATED_FAIL"

        after = read_candidate(candidate)
        assert after["vetting_status"] == "REJECTED"
        assert after["availability_status"] == "INACTIVE"
        assert after["cooling_off_until"] is None

        trial = read_trial(scenario["trial"])
        assert trial["status"] == "CANCELLED"
        assert trial["cancel_reason"] == "VETTING_FAILED"

        requisition = read_requisition(requisition)
        assert requisition["status"] == "SOURCING"
        assert requisition["active_trial_count"] == 0

    def test_02_a_rejected_candidate_cannot_be_released_back_to_the_pool(self):
        """INACTIVE is not a door back in while the vetting axis says REJECTED.

        PRD §3.3: "From `INACTIVE` the same operation moves `INACTIVE →
        AVAILABLE`, but only for a candidate whose `vetting_status` is `CLEARED`;
        any other vetting state is refused with `ERR_CANDIDATE_NOT_VETTED` (HTTP
        409)."

        Design: Difficulty/transitive_cascade/adjudicated_fail_cascades_through_candidate_trial_and_requisition
        """
        scenario = _flagged_candidate_on_a_scheduled_trial()
        adjudicate_background(
            scenario["background"], "FAIL", scenario["candidate"]["version"]
        )
        candidate = read_candidate(scenario["candidate"])
        assert candidate["availability_status"] == "INACTIVE"

        response = api_client.release_availability(
            candidate["id"], release_availability_payload(), CONSULTANT
        )
        validate_error(response, "ERR_CANDIDATE_NOT_VETTED")

        unchanged = read_candidate(candidate)
        assert unchanged["availability_status"] == "INACTIVE"
        assert unchanged["vetting_status"] == "REJECTED"
        assert unchanged["version"] == candidate["version"]


class TestSupersedeCascade:
    def _superseded(self):
        scenario = setup_senior_scenario(stage="placement_pending")
        scenario["milestones"][0] = invoice_milestone(scenario["milestones"][0])
        scenario["requisition"] = read_requisition(scenario["requisition"])
        scenario["second"] = extend_offer(
            scenario["requisition"],
            scenario["candidate"],
            start_date="2026-09-15",
            base_salary_cents=13_002_500,
            guaranteed_bonus_cents=1_502_500,
            accommodation_imputed_cents=902_500,
            overtime_allowance_cents=592_500,
        )
        return scenario

    def test_03_the_new_offer_voids_the_incumbent_and_reverses_its_invoice(self):
        """PENDING rows are voided and the invoiced row is reversed, not deleted.

        PRD §3.6: "Hop two settles its billing rows: every `FeeMilestone` of that
        placement whose `invoice_status` is `PENDING` moves to `VOIDED`, and
        every one whose `invoice_status` is `INVOICED` or `OVERDUE` moves to
        `REVERSED`."

        Design: Difficulty/transitive_cascade/superseding_offer_reverses_the_invoiced_milestone_and_restores_the_balance
        """
        scenario = setup_senior_scenario(stage="placement_pending")
        invoiced = invoice_milestone(scenario["milestones"][0])
        assert invoiced["invoice_status"] == "INVOICED"
        assert invoiced["amount_cents"] == 1_004_850
        assert read_client(scenario["client"])["outstanding_balance_cents"] == 1_004_850

        second = extend_offer(
            read_requisition(scenario["requisition"]),
            scenario["candidate"],
            start_date="2026-09-15",
            base_salary_cents=13_002_500,
            guaranteed_bonus_cents=1_502_500,
            accommodation_imputed_cents=902_500,
            overtime_allowance_cents=592_500,
        )
        assert second["placement_status"] == "PENDING_ACCEPTANCE"
        assert second["id"] != scenario["placement"]["id"]

        first = read_placement(scenario["placement"])
        assert first["placement_status"] == "VOIDED"
        assert first["void_reason"] == "SUPERSEDED_BY_NEW_OFFER"
        assert first["billing_status"] == "REVERSED"

        rows = read_milestones(first)
        assert find_milestone(rows, "ENGAGEMENT")["invoice_status"] == "REVERSED"
        assert find_milestone(rows, "TRIAL_CLEARED")["invoice_status"] == "VOIDED"
        assert find_milestone(rows, "START_DATE")["invoice_status"] == "VOIDED"

    def test_04_the_reversal_returns_the_ledger_to_zero(self):
        """Two rows of equal magnitude and opposite sign fold back to nothing.

        PRD §3.6: "Hop three posts the money back: each milestone that moved to
        `REVERSED` appends a `LedgerEntry` of `entry_type` `FEE_REVERSAL` with
        `signed_amount_cents` equal to the negative of that milestone's
        `amount_cents` and `related_ref_type` `FEE_MILESTONE`."

        Design: Difficulty/transitive_cascade/superseding_offer_reverses_the_invoiced_milestone_and_restores_the_balance
        """
        scenario = self._superseded()
        entries = read_ledger(scenario["client"])
        assert [entry["entry_type"] for entry in entries] == [
            "FEE_INVOICED",
            "FEE_REVERSAL",
        ]
        assert [entry["signed_amount_cents"] for entry in entries] == [
            1_004_850,
            -1_004_850,
        ]
        assert [entry["balance_after_cents"] for entry in entries] == [1_004_850, 0]
        assert find_ledger_entries(entries, "FEE_REVERSAL")[0][
            "related_ref_type"
        ] == "FEE_MILESTONE"
        assert assert_ledger_fold(entries) == 0
        assert read_client(scenario["client"])["outstanding_balance_cents"] == 0

    def test_05_the_requisition_and_candidate_hold_their_offer_states(self):
        """The self-loops keep both rows where the incumbent offer had put them.

        PRD §3.6: "Fifth, the requisition moves `TRIALING → OFFER_PENDING`, or
        takes the `OFFER_PENDING → OFFER_PENDING` self-loop on the supersede
        path, and its `version` is incremented."

        Design: Difficulty/transitive_cascade/superseding_offer_reverses_the_invoiced_milestone_and_restores_the_balance
        """
        scenario = setup_senior_scenario(stage="placement_pending")
        invoice_milestone(scenario["milestones"][0])
        before = read_requisition(scenario["requisition"])
        assert before["status"] == "OFFER_PENDING"

        extend_offer(
            before,
            scenario["candidate"],
            start_date="2026-09-15",
            base_salary_cents=13_002_500,
            guaranteed_bonus_cents=1_502_500,
            accommodation_imputed_cents=902_500,
            overtime_allowance_cents=592_500,
        )

        after = read_requisition(before)
        assert after["status"] == "OFFER_PENDING"
        assert after["version"] == before["version"] + 1
        assert read_candidate(scenario["candidate"])["availability_status"] == "OFFER_HELD"


class TestSuspensionCascade:
    def _household_with_a_second_open_search(self):
        scenario = setup_senior_scenario(stage="placement_active")
        publish_fee_schedule(
            role_type="HOUSEKEEPER",
            comp_band_floor_cents=0,
            comp_band_ceiling_cents=15_000_000,
            fee_percent_bps=1800,
            guarantee_window_days=60,
        )
        second = open_requisition(
            scenario["client"],
            role_type="HOUSEKEEPER",
            first_year_compensation_cents=6_800_000,
            schedule_pattern="FIVE_TWO",
            live_in_required=False,
        )
        second = run_scoping_round(
            second, scope_note="Second role for the same household."
        )
        scenario["second_requisition"] = finalize_scope(second)
        scenario["second_candidate"] = add_vetted_candidate(
            full_name="V. Okafor",
            contact_email="vo@mail.example",
            reference_prefix="Pemberton",
            primary_role_type="HOUSEKEEPER",
            years_experience=12,
            live_in_willing=False,
        )
        scenario["second_trial"] = book_trial(
            scenario["second_requisition"],
            scenario["second_candidate"],
            engagement_type="WORKING_INTERVIEW",
            day_rate_cents=0,
            start_at="2026-09-25T09:00:00Z",
            end_at="2026-09-25T17:00:00Z",
        )
        return scenario

    def _substantiated(self, scenario):
        set_clock("2026-10-01T00:00:00Z")
        case = file_enforcement_case(
            scenario["client"],
            scenario["candidate"],
            "2026-09-28",
            source_placement=scenario["placement"],
            allegation_note="The household hired the estate manager directly.",
        )
        return resolve_case(investigate_case(case), "SUBSTANTIATE")

    def test_06_substantiation_assesses_the_penalty_and_suspends_the_household(self):
        """Hops one to four run on the household named in the case.

        PRD §3.9: "Hop four moves the household `ONBOARDED → SUSPENDED`, which by
        itself blocks new searches, new scoping rounds, scope finalisation, new
        trial bookings and new offers."

        Design: Difficulty/transitive_cascade/substantiated_case_suspends_the_household_and_empties_its_open_requisition
        """
        scenario = self._household_with_a_second_open_search()
        before = read_client(scenario["client"])
        assert before["status"] == "ONBOARDED"
        assert before["outstanding_balance_cents"] == 0
        assert before["non_solicitation_expires_on"] == "2028-08-31"

        case = self._substantiated(scenario)
        assert case["status"] == "SUBSTANTIATED"
        assert case["penalty_cents"] == 2_512_124

        entries = read_ledger(scenario["client"])
        assessed = find_ledger_entries(entries, "PENALTY_ASSESSED")
        assert len(assessed) == 1
        assert assessed[0]["signed_amount_cents"] == 2_512_124
        assert assessed[0]["related_ref_type"] == "NON_SOLICITATION_CASE"

        after = read_client(before)
        assert after["outstanding_balance_cents"] == 2_512_124
        assert after["status"] == "SUSPENDED"

    def test_07_hop_five_empties_a_second_search_the_case_never_named(self):
        """Only SCHEDULED trials are swept, so the placed candidate is untouched.

        PRD §3.9: "Hop five cancels the consequences of the suspension: every
        `SCHEDULED` `TrialEngagement` of that household moves to `CANCELLED` with
        `cancel_reason` `CLIENT_SUSPENDED`, and every `TRIALING`
        `RoleRequisition` of that household whose recomputed `active_trial_count`
        reaches 0 falls back to `SOURCING`."

        Design: Difficulty/transitive_cascade/substantiated_case_suspends_the_household_and_empties_its_open_requisition
        """
        scenario = self._household_with_a_second_open_search()
        assert read_requisition(scenario["second_requisition"])["status"] == "TRIALING"
        assert read_trial(scenario["second_trial"])["status"] == "SCHEDULED"

        self._substantiated(scenario)

        trial = read_trial(scenario["second_trial"])
        assert trial["status"] == "CANCELLED"
        assert trial["cancel_reason"] == "CLIENT_SUSPENDED"

        requisition = read_requisition(scenario["second_requisition"])
        assert requisition["status"] == "SOURCING"
        assert requisition["active_trial_count"] == 0

        released = read_candidate(scenario["second_candidate"])
        assert released["availability_status"] == "AVAILABLE"
        assert released["vetting_status"] == "CLEARED"
        assert read_candidate(scenario["candidate"])["availability_status"] == "PLACED"

    def test_08_a_suspended_household_cannot_book_another_trial(self):
        """The suspension keeps the emptied search closed to new bookings.

        PRD §3.4: "The requisition must be in `SOURCING` or `TRIALING`, and any
        other state is refused with `ERR_INVALID_STATE_TRANSITION`; the household
        must not be `SUSPENDED`, or the booking is refused with
        `ERR_CLIENT_SUSPENDED`."

        Design: Difficulty/transitive_cascade/substantiated_case_suspends_the_household_and_empties_its_open_requisition
        """
        scenario = self._household_with_a_second_open_search()
        self._substantiated(scenario)
        assert read_client(scenario["client"])["status"] == "SUSPENDED"

        response = api_client.create_trial_engagement(
            scenario["second_requisition"]["id"],
            create_trial_engagement_payload(
                scenario["second_candidate"]["id"],
                engagement_type="WORKING_INTERVIEW",
                day_rate_cents=0,
                start_at="2026-10-08T09:00:00Z",
                end_at="2026-10-08T17:00:00Z",
            ),
            CONSULTANT,
        )
        validate_error(response, "ERR_CLIENT_SUSPENDED")
        assert read_requisition(scenario["second_requisition"])["active_trial_count"] == 0
