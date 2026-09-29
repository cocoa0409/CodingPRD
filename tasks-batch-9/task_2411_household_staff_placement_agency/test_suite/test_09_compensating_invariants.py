"""Round trips that must land exactly where they started.

A reversal returns a household balance to its pre-invoice value, a re-pricing
around a frozen paid row keeps three amounts summing to the fee, and a cancelled
booking hands the candidate and the search back to the states they held before it.
In each case the compensating write moves the state back while the history — the
ledger rows, the version counters — only ever moves forward.
"""
from test_helpers import (
    BASE_SCENARIO,
    CONSULTANT,
    api_client,
    assert_ledger_fold,
    assert_milestone_allocation,
    book_trial,
    cancel_trial,
    confirm_start,
    find_ledger_entries,
    find_milestone,
    invoice_and_pay,
    invoice_milestone,
    read_candidate,
    read_client,
    read_ledger,
    read_milestone,
    read_milestones,
    read_placement,
    read_requisition,
    read_trial,
    reverse_milestone,
    set_clock,
    setup_scenario,
    setup_senior_scenario,
    validate_paginated,
)

# A CHEF search whose trial day is booked and then called off by the household.
ROWANMERE_OPTIONS = {
    "client": {
        "household_name": "Rowanmere Farm",
        "primary_contact_email": "ops@rowanmere.example",
        "region_code": "TX",
    },
    "signatory_name": "L. Rowanmere",
    "fee_schedules": [
        {
            "role_type": "CHEF",
            "comp_band_floor_cents": 0,
            "comp_band_ceiling_cents": None,
            "fee_percent_bps": 2000,
            "guarantee_window_days": 120,
            "effective_from": "2026-01-01",
        }
    ],
    "requisition": {
        "role_type": "CHEF",
        "first_year_compensation_cents": 8_800_000,
        "schedule_pattern": "FIVE_TWO",
        "live_in_required": False,
    },
    "scope": {"scope_note": "Seasonal produce, family of four."},
    "candidate": {
        "full_name": "O. Vandenberg",
        "contact_email": "ov@mail.example",
        "primary_role_type": "CHEF",
        "years_experience": 12,
        "live_in_willing": False,
    },
    "references": [
        {
            "principal_employer_name": "Grantham Estate",
            "relationship_type": "PRINCIPAL_EMPLOYER",
            "employment_start_month": "2022-01",
            "employment_end_month": "2022-12",
            "contact_email": "grantham@mail.example",
        },
        {
            "principal_employer_name": "Ravensworth Hall",
            "relationship_type": "PRINCIPAL_EMPLOYER",
            "employment_start_month": "2023-01",
            "employment_end_month": "2023-12",
            "contact_email": "ravensworth@mail.example",
            "chain_to_previous": True,
        },
    ],
    "background": {
        "provider_reference": "BV-1401",
        "scope_items": ["IDENTITY", "CREDENTIAL"],
    },
}

ROWANMERE_TRIAL = {
    "engagement_type": "TRIAL_DAY",
    "day_rate_cents": 55_000,
    "start_at": "2026-08-21T09:00:00Z",
    "end_at": "2026-08-21T17:00:00Z",
}


def _invoiced_engagement_fee():
    """An ACTIVE placement carrying exactly one receivable: the engagement fee."""
    scenario = setup_senior_scenario(stage="placement_active")
    assert read_client(scenario["client"])["outstanding_balance_cents"] == 0
    scenario["engagement"] = invoice_milestone(
        find_milestone(read_milestones(scenario["placement"]), "ENGAGEMENT")
    )
    return scenario


def _paid_engagement_before_confirmation():
    """A PENDING_ACCEPTANCE placement whose engagement fee is already settled,
    so the confirmation re-prices around a frozen row."""
    scenario = setup_senior_scenario(stage="placement_pending")
    set_clock("2026-09-01T00:00:00Z")
    scenario["engagement"] = invoice_and_pay(
        find_milestone(read_milestones(scenario["placement"]), "ENGAGEMENT")
    )
    scenario["placement"] = read_placement(scenario["placement"])
    return scenario


def _booked_then_cancelled():
    scenario = setup_scenario(stage="background_recorded", **ROWANMERE_OPTIONS)
    scenario["requisition_before"] = read_requisition(scenario["requisition"])
    scenario["candidate_before"] = read_candidate(scenario["candidate"])
    scenario["trial"] = book_trial(
        scenario["requisition"], scenario["candidate"], **ROWANMERE_TRIAL
    )
    scenario["cancelled"] = cancel_trial(scenario["trial"], "CLIENT_REQUEST")
    return scenario


class TestInvoiceThenReverse:
    def test_01_the_reversal_returns_the_balance_to_its_pre_invoice_value(self):
        """Zero before the invoice, 1,004,850 after it, zero again after reversal.

        PRD §3.7: "Because `FEE_INVOICED` and `FEE_REVERSAL` carry identical
        magnitudes with opposite signs, invoicing a milestone and then reversing it
        returns the household's balance to its exact pre-invoice value — the
        compensation is precise, not approximate."

        Design: Difficulty/compensating_invariant/invoice_then_reverse_restores_the_client_balance_exactly
        """
        scenario = _invoiced_engagement_fee()
        milestone = scenario["engagement"]
        assert milestone["invoice_status"] == "INVOICED"
        assert milestone["amount_cents"] == 1_004_850
        assert read_client(scenario["client"])["outstanding_balance_cents"] == 1_004_850

        reversed_row = reverse_milestone(milestone)
        assert reversed_row["invoice_status"] == "REVERSED"
        assert reversed_row["amount_cents"] == 1_004_850
        assert reversed_row["version"] == milestone["version"] + 1
        assert read_client(scenario["client"])["outstanding_balance_cents"] == 0

    def test_02_the_earlier_ledger_row_is_never_restamped(self):
        """Two rows, opposite signs, and the first still reads 1,004,850.

        PRD §2.12: "A `LedgerEntry` names its household through `client_id`,
        occupies a 1-based `sequence_no` that increments monotonically within that
        household, and records a `signed_amount_cents` movement, a human-readable
        `memo`, and a `balance_after_cents` snapshot stamped once at append time."

        Design: Difficulty/compensating_invariant/invoice_then_reverse_restores_the_client_balance_exactly
        """
        scenario = _invoiced_engagement_fee()
        reverse_milestone(scenario["engagement"])

        entries = read_ledger(scenario["client"])
        assert [entry["sequence_no"] for entry in entries] == [1, 2]
        assert [entry["entry_type"] for entry in entries] == [
            "FEE_INVOICED",
            "FEE_REVERSAL",
        ]
        assert [entry["signed_amount_cents"] for entry in entries] == [
            1_004_850,
            -1_004_850,
        ]
        assert [entry["balance_after_cents"] for entry in entries] == [1_004_850, 0]
        assert all(
            entry["related_ref_type"] == "FEE_MILESTONE" for entry in entries
        )
        assert find_ledger_entries(entries, "FEE_REVERSAL")[0]["related_ref_id"] == (
            scenario["engagement"]["id"]
        )
        assert assert_ledger_fold(entries) == 0

    def test_03_the_reversal_leaves_the_two_untouched_milestones_alone(self):
        """Only the reversed row moves; the other two keep their PENDING amounts.

        PRD §3.7: "The placement's `billing_status` moves `PARTIALLY_BILLED →
        REVERSED` once none of its milestones is `INVOICED`, `OVERDUE` or `PAID`
        and at least one is `REVERSED`."

        Design: Difficulty/compensating_invariant/invoice_then_reverse_restores_the_client_balance_exactly
        """
        scenario = _invoiced_engagement_fee()
        assert read_placement(scenario["placement"])["billing_status"] == (
            "PARTIALLY_BILLED"
        )

        reverse_milestone(scenario["engagement"])
        placement = read_placement(scenario["placement"])
        assert placement["billing_status"] == "REVERSED"
        assert placement["fee_cents"] == 3_349_499

        rows = assert_milestone_allocation(
            read_milestones(placement), placement["fee_cents"]
        )
        assert rows[0]["invoice_status"] == "REVERSED"
        assert [row["invoice_status"] for row in rows[1:]] == ["PENDING", "PENDING"]
        assert [row["amount_cents"] for row in rows] == [
            1_004_850,
            1_004_850,
            1_339_799,
        ]


class TestReallocationAroundAFrozenPaidRow:
    def test_04_the_paid_row_survives_the_repricing_byte_for_byte(self):
        """The fee drops by one cent and the settled row does not notice.

        PRD §3.7: "The **frozen** partition holds every row whose
        `invoice_status` is `INVOICED`, `OVERDUE`, `PAID` or `REVERSED`; the
        **open** partition holds every row whose `invoice_status` is `PENDING`;
        rows whose `invoice_status` is `VOIDED` are excluded from both partitions
        and take no part in the allocation at all."

        Design: Difficulty/compensating_invariant/milestone_reallocation_preserves_the_fee_sum_around_a_frozen_paid_row
        """
        scenario = _paid_engagement_before_confirmation()
        before = scenario["placement"]
        assert before["fee_cents"] == 3_349_500
        assert before["fee_variant"] == "PROVISIONAL"
        paid = scenario["engagement"]
        assert paid["invoice_status"] == "PAID"
        assert paid["amount_cents"] == 1_004_850
        assert paid["paid_on"] == "2026-09-01"
        assert paid["payment_reference"] == BASE_SCENARIO["PAYMENT_REFERENCE"]

        confirmed = confirm_start(before)
        assert confirmed["fee_cents"] == 3_349_499
        assert confirmed["fee_variant"] == "FINAL"

        after = read_milestone(paid)
        assert after["invoice_status"] == "PAID"
        assert after["amount_cents"] == 1_004_850
        assert after["paid_on"] == paid["paid_on"]
        assert after["payment_reference"] == paid["payment_reference"]

    def test_05_the_two_open_rows_absorb_the_whole_delta(self):
        """The last open row takes the remainder rather than a fourth rounding.

        PRD §3.7: "Then, walking the open rows in ascending `sequence_no` order,
        every open row **except the last** receives the remaining amount multiplied
        by that row's `weight_bps`, divided by the open weight total, rounded half
        up; the **last** open row receives the exact arithmetic remainder — the
        remaining amount less the sum of whatever has just been assigned in this
        pass."

        Design: Difficulty/compensating_invariant/milestone_reallocation_preserves_the_fee_sum_around_a_frozen_paid_row
        """
        scenario = _paid_engagement_before_confirmation()
        before = assert_milestone_allocation(
            read_milestones(scenario["placement"]), 3_349_500
        )
        assert [row["amount_cents"] for row in before] == [
            1_004_850,
            1_004_850,
            1_339_800,
        ]

        placement = confirm_start(scenario["placement"])
        rows = assert_milestone_allocation(
            read_milestones(placement), placement["fee_cents"]
        )
        assert [row["amount_cents"] for row in rows] == [
            1_004_850,
            1_004_850,
            1_339_799,
        ]
        assert [row["invoice_status"] for row in rows] == ["PAID", "PENDING", "PENDING"]
        assert sum(row["amount_cents"] for row in rows) == 3_349_499

    def test_06_reallocating_the_pending_rows_moves_no_money(self):
        """The ledger holds only the invoice and its payment, and folds to zero.

        PRD §2.12: "The invariant is exact and holds after every append: the
        household's `outstanding_balance_cents` equals the sum of
        `signed_amount_cents` across its ledger, and equals the last row's
        `balance_after_cents`."

        Design: Difficulty/compensating_invariant/milestone_reallocation_preserves_the_fee_sum_around_a_frozen_paid_row
        """
        scenario = _paid_engagement_before_confirmation()
        confirm_start(scenario["placement"])

        entries = read_ledger(scenario["client"])
        assert [entry["entry_type"] for entry in entries] == [
            "FEE_INVOICED",
            "FEE_PAYMENT",
        ]
        assert [entry["signed_amount_cents"] for entry in entries] == [
            1_004_850,
            -1_004_850,
        ]
        assert entries[-1]["balance_after_cents"] == 0
        assert assert_ledger_fold(entries) == 0
        assert read_client(scenario["client"])["outstanding_balance_cents"] == 0


class TestTrialCancellationRestoresBothRows:
    def test_07_the_candidate_and_the_search_return_to_their_prior_states(self):
        """Same states as before the booking, but strictly higher versions.

        PRD §3.4: "Both paths carry the same side-effect set: the candidate is
        returned `ON_TRIAL → AVAILABLE` provided the candidate holds no other
        active engagement **and** the candidate's `vetting_status` is not
        `REJECTED`, and the requisition falls `TRIALING → SOURCING` when the
        recomputed `active_trial_count` reaches 0."

        Design: Difficulty/compensating_invariant/trial_cancellation_returns_the_candidate_and_the_requisition_to_their_prior_state
        """
        scenario = setup_scenario(stage="background_recorded", **ROWANMERE_OPTIONS)
        requisition_before = read_requisition(scenario["requisition"])
        candidate_before = read_candidate(scenario["candidate"])
        assert requisition_before["status"] == "SOURCING"
        assert requisition_before["active_trial_count"] == 0
        assert candidate_before["availability_status"] == "AVAILABLE"

        trial = book_trial(
            scenario["requisition"], scenario["candidate"], **ROWANMERE_TRIAL
        )
        assert read_requisition(requisition_before)["status"] == "TRIALING"
        assert read_requisition(requisition_before)["active_trial_count"] == 1
        assert read_candidate(candidate_before)["availability_status"] == "ON_TRIAL"

        cancelled = cancel_trial(trial, "CLIENT_REQUEST")
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancel_reason"] == "CLIENT_REQUEST"

        candidate_after = read_candidate(candidate_before)
        assert candidate_after["availability_status"] == "AVAILABLE"
        assert candidate_after["vetting_status"] == "CLEARED"
        assert candidate_after["cooling_off_until"] is None
        assert candidate_after["version"] > candidate_before["version"]

        requisition_after = read_requisition(requisition_before)
        assert requisition_after["status"] == "SOURCING"
        assert requisition_after["active_trial_count"] == 0
        assert requisition_after["version"] > requisition_before["version"]

    def test_08_the_cancelled_row_gives_its_weekly_slot_back(self):
        """The identical window is bookable again in the very same ISO week.

        PRD §3.4: "Each individual booking may be perfectly admissible on its own;
        it is the third one landing in the same ISO week that is refused."

        Design: Difficulty/compensating_invariant/trial_cancellation_returns_the_candidate_and_the_requisition_to_their_prior_state
        """
        scenario = _booked_then_cancelled()
        cancelled = scenario["cancelled"]
        assert cancelled["status"] == "CANCELLED"

        rebooked = book_trial(
            scenario["requisition"], scenario["candidate"], **ROWANMERE_TRIAL
        )
        assert rebooked["status"] == "SCHEDULED"
        assert rebooked["id"] != cancelled["id"]
        assert rebooked["iso_week_key"] == cancelled["iso_week_key"]
        assert rebooked["cancel_reason"] is None

        rows, _ = validate_paginated(
            api_client.list_trial_engagements(
                CONSULTANT, {"candidate_id": scenario["candidate"]["id"]}
            )
        )
        assert len(rows) == 2
        assert read_trial(cancelled)["status"] == "CANCELLED"
        assert read_requisition(scenario["requisition"])["active_trial_count"] == 1
