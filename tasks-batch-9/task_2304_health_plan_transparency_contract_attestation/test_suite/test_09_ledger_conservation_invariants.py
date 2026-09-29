"""Corrections that must conserve one quantity while moving another.

Money and deficiency state are independent axes. A reversal appends a negating
entry instead of editing history; a remediation completion abates half the base
and leaves the points alone; a rejected and resubmitted data package moves the
record count without disturbing an accrual that has already been posted.
"""

from __future__ import annotations

from test_helpers import (
    AUDITOR_USER_ID,
    COMPLIANCE_OFFICER_HEADERS,
    EXTERNAL_AUDITOR_HEADERS,
    ApiClient,
    ApiErrorId,
    DEFICIENCY_GAG_CLAUSE,
    DEFICIENCY_RXDC_LATE,
    ENTRY_ABATEMENT,
    ENTRY_ACCRUAL,
    PACKAGE_RECEIVED,
    PACKAGE_VALIDATED,
    LIFECYCLE_ACTIVE,
    POSTURE_AT_RISK,
    POSTURE_DEFICIENT,
    REMEDIATION_ACTIVE,
    REMEDIATION_COMPLETED,
    RX_RECONCILED,
    SECTION_D6_RX_TOTALS,
    SECTION_D7_RX_REBATES,
    VENDOR_TYPE_PBM,
    assert_exposure_equals_ledger,
    assert_instant_equals,
    assert_non_accrual_pricing_fields,
    factories as f,
    fixtures as fx,
    make_vendor_contact_headers,
    validate_error,
    validate_success,
)

GAG_CLOCK = "2027-05-04T09:00:00Z"
RECONCILE_CLOCK = "2028-05-20T09:00:00Z"
LATE_CLOCK = "2028-06-15T09:00:00Z"

D6_FIGURES = {
    "record_count": 1200,
    "plan_paid_cents": 6_000_000,
    "member_paid_cents": 1_000_000,
    "rebate_cents": 1_800_000,
}
D7_FIGURES = {
    "record_count": 800,
    "plan_paid_cents": 3_000_000,
    "member_paid_cents": 500_000,
    "rebate_cents": 1_200_000,
}
D7_CORRECTED = {
    "record_count": 850,
    "plan_paid_cents": 3_000_000,
    "member_paid_cents": 500_000,
    "rebate_cents": 1_200_000,
}

MILESTONE_ONE = "Rider drafted and sent to vendor counsel"
MILESTONE_TWO = "Executed rider re-reviewed by compliance"


def _plan_year_with_one_gag_accrual(api: ApiClient) -> dict:
    """A DEFICIENT plan year holding exactly one 30,000-cent gag accrual."""
    fx.set_clock(api, GAG_CLOCK)
    setup = fx.plan_year_with_gag_accrual(api, covered_lives=6000)
    assert setup["accrual"]["signed_amount_cents"] == 30_000
    assert setup["plan_year"]["penalty_exposure_cents"] == 30_000
    assert setup["plan_year"]["deficiency_points"] == 6
    assert setup["plan_year"]["compliance_posture"] == POSTURE_DEFICIENT
    return setup


def _submission_with_rejected_package(api: ApiClient) -> dict:
    """A reconciled submission unwound by one late rejection, with its accrual."""
    fx.set_clock(api, RECONCILE_CLOCK)
    setup = fx.activated_plan_year(
        api, covered_lives=6000, attestation_deadline_date="2028-12-31"
    )
    plan_year_id = setup["plan_year"]["id"]
    pbm = fx.add_contract_for_vendor_type(
        api, plan_year_id, VENDOR_TYPE_PBM, annual_fee_cents=12_000_000
    )
    fx.contract_with_secured_data_rights(
        api, pbm["contract"]["id"], expires_at="2028-06-30T00:00:00Z"
    )
    submission = fx.open_rx_submission(api, plan_year_id, reference_year=2027)
    packages = {}
    for key, section, figures in (
        ("pk_d6", SECTION_D6_RX_TOTALS, D6_FIGURES),
        ("pk_d7", SECTION_D7_RX_REBATES, D7_FIGURES),
    ):
        package = fx.request_package(
            api,
            submission["id"],
            pbm["vendor"]["id"],
            data_section=section,
            expected_record_count=figures["record_count"],
        )
        fx.validated_package(api, package["id"], pbm["vendor"]["id"], **figures)
        packages[key] = package
    validate_success(
        api.reconcile_rx_submission(submission["id"], COMPLIANCE_OFFICER_HEADERS)
    )

    fx.set_clock(api, LATE_CLOCK)
    validate_success(
        api.reject_package(
            packages["pk_d7"]["id"],
            f.reject_package_payload(),
            COMPLIANCE_OFFICER_HEADERS,
        )
    )
    return {
        "plan_year_id": plan_year_id,
        "vendor_headers": make_vendor_contact_headers(pbm["vendor"]["id"]),
        "submission_id": submission["id"],
        **packages,
    }


def _read_submission(api: ApiClient, submission_id: str) -> dict:
    return validate_success(
        api.get_rx_submission(submission_id, COMPLIANCE_OFFICER_HEADERS)
    )


class TestReversalConservesTheLedger:
    """A reversal appends a negation; it never edits or deletes the original."""

    def test_reversal_appends_a_negating_entry_and_leaves_the_points_alone(
        self, api: ApiClient
    ) -> None:
        """Exposure falls to zero while the six points and the posture stand.

        PRD 3.9: "The reversal appends a *new* entry whose `signed_amount_cents`
        is the arithmetic negation of the original's, whose `reverses_entry_id` is
        the original's `id`, whose `plan_year_id` and `deficiency_type` copy the
        original's, whose `entry_type` is `ABATEMENT`, and whose
        `daily_rate_cents`, `days_open`, `size_multiplier` and `onset_date` take
        the non-accrual values of 0, 0, 1.0 and null; `posted_by_user_id` records
        the auditor and `remediation_plan_id` stays null."

        Design: Difficulty/compensating_invariant/ledger_reversal_conserves_balance_without_touching_deficiency_points
        """
        setup = _plan_year_with_one_gag_accrual(api)
        plan_year_id = setup["plan_year"]["id"]
        accrual_id = setup["accrual"]["id"]

        reversal = validate_success(
            api.reverse_ledger_entry(
                accrual_id,
                f.reverse_entry_payload(
                    reason=(
                        "Accrual priced before the DOL grace bulletin; "
                        "withdrawn on audit review."
                    )
                ),
                EXTERNAL_AUDITOR_HEADERS,
            ),
        )
        assert reversal["entry_type"] == ENTRY_ABATEMENT
        assert reversal["deficiency_type"] == DEFICIENCY_GAG_CLAUSE
        assert reversal["signed_amount_cents"] == -30_000
        assert reversal["reverses_entry_id"] == accrual_id
        assert reversal["remediation_plan_id"] is None
        assert reversal["posted_by_user_id"] == AUDITOR_USER_ID
        assert_non_accrual_pricing_fields(reversal)

        original = validate_success(
            api.get_ledger_entry(accrual_id, COMPLIANCE_OFFICER_HEADERS)
        )
        assert original["entry_type"] == ENTRY_ACCRUAL
        assert original["signed_amount_cents"] == 30_000

        entries = fx.list_ledger_entries(api, plan_year_id)
        assert len(entries) == 2
        assert sum(entry["signed_amount_cents"] for entry in entries) == 0

        plan_year = fx.read_plan_year(api, plan_year_id)
        assert_exposure_equals_ledger(plan_year, entries)
        assert plan_year["penalty_exposure_cents"] == 0
        assert plan_year["deficiency_points"] == 6
        assert plan_year["compliance_posture"] == POSTURE_DEFICIENT

    def test_an_accrual_cannot_be_reversed_twice(self, api: ApiClient) -> None:
        """A second withdrawal would unbalance the compensating pair.

        PRD 3.9: "And an accrual may be reversed at most once — if any entry
        already carries a `reverses_entry_id` equal to this entry's `id`, the
        request is refused with `ERR_ENTRY_ALREADY_REVERSED`."

        Design: Difficulty/compensating_invariant/ledger_reversal_conserves_balance_without_touching_deficiency_points
        """
        setup = _plan_year_with_one_gag_accrual(api)
        plan_year_id = setup["plan_year"]["id"]
        accrual_id = setup["accrual"]["id"]
        fx.reversed_accrual(api, accrual_id)

        response = api.reverse_ledger_entry(
            accrual_id,
            f.reverse_entry_payload(reason="Duplicate withdrawal attempt."),
            EXTERNAL_AUDITOR_HEADERS,
        )
        validate_error(response, ApiErrorId.ENTRY_ALREADY_REVERSED)

        entries = fx.list_ledger_entries(api, plan_year_id)
        assert len(entries) == 2
        assert sum(entry["signed_amount_cents"] for entry in entries) == 0

    def test_a_reversal_is_not_itself_reversible(self, api: ApiClient) -> None:
        """Only accruals carry money that can be withdrawn.

        PRD 3.9: "Only accruals are reversible: reversing an abatement, or
        reversing an entry that is itself a reversal, is refused with
        `ERR_NOT_REVERSIBLE_ENTRY`."

        Design: Difficulty/compensating_invariant/ledger_reversal_conserves_balance_without_touching_deficiency_points
        """
        setup = _plan_year_with_one_gag_accrual(api)
        plan_year_id = setup["plan_year"]["id"]
        reversal = fx.reversed_accrual(api, setup["accrual"]["id"])

        response = api.reverse_ledger_entry(
            reversal["id"],
            f.reverse_entry_payload(reason="Attempt to reverse the reversal."),
            EXTERNAL_AUDITOR_HEADERS,
        )
        validate_error(response, ApiErrorId.NOT_REVERSIBLE_ENTRY)

        assert len(fx.list_ledger_entries(api, plan_year_id)) == 2


class TestResubmissionMovesRecordsWithoutMovingMoney:
    """The record count is a running total; the posted accrual is history."""

    def test_the_record_count_falls_out_and_the_corrected_count_comes_back_in(
        self, api: ApiClient
    ) -> None:
        """1200 plus 850 replaces 1200 plus 800 only on re-validation.

        PRD 3.6: "Validation moves a package `RECEIVED → VALIDATED`, stamps
        `validated_at` with the logical clock, increments the package's `version`
        by 1, and — this is the conserved quantity in this domain — increases the
        parent submission's `assembled_record_count` by exactly this package's
        `record_count`."

        Design: Difficulty/compensating_invariant/package_rejection_and_resubmission_conserves_money_while_record_count_moves
        """
        built = _submission_with_rejected_package(api)
        assert _read_submission(api, built["submission_id"])["assembled_record_count"] == 1200

        resubmitted = validate_success(
            api.resubmit_package(
                built["pk_d7"]["id"],
                f.resubmit_package_payload(**D7_CORRECTED),
                built["vendor_headers"],
            )
        )
        assert resubmitted["status"] == PACKAGE_RECEIVED
        assert resubmitted["delivery_round"] == 2
        assert resubmitted["record_count"] == 850
        # Received is not yet counted in.
        assert _read_submission(api, built["submission_id"])["assembled_record_count"] == 1200

        validated = validate_success(
            api.validate_package(built["pk_d7"]["id"], COMPLIANCE_OFFICER_HEADERS)
        )
        assert validated["status"] == PACKAGE_VALIDATED
        assert _read_submission(api, built["submission_id"])["assembled_record_count"] == 2050

    def test_re_reconciliation_lands_on_the_same_money_from_the_same_figures(
        self, api: ApiClient
    ) -> None:
        """The two axes are recomputed independently of one another.

        PRD 3.6: "`gross_spend_cents` is the sum of every validated package's
        `plan_paid_cents` plus the sum of every validated package's
        `member_paid_cents`. `rebate_reported_cents` is the sum of every
        validated package's `rebate_cents`."

        Design: Difficulty/compensating_invariant/package_rejection_and_resubmission_conserves_money_while_record_count_moves
        """
        built = _submission_with_rejected_package(api)
        validate_success(
            api.resubmit_package(
                built["pk_d7"]["id"],
                f.resubmit_package_payload(**D7_CORRECTED),
                built["vendor_headers"],
            )
        )
        validate_success(
            api.validate_package(built["pk_d7"]["id"], COMPLIANCE_OFFICER_HEADERS)
        )

        reconciled = validate_success(
            api.reconcile_rx_submission(
                built["submission_id"], COMPLIANCE_OFFICER_HEADERS
            )
        )
        assert reconciled["status"] == RX_RECONCILED
        assert reconciled["gross_spend_cents"] == 10_500_000
        assert reconciled["rebate_reported_cents"] == 3_000_000
        assert reconciled["rebate_cap_pct"] == 0.20
        assert reconciled["rebate_credit_cents"] == 2_100_000
        assert reconciled["net_plan_spend_cents"] == 8_400_000
        assert_instant_equals(reconciled["reconciled_at"], LATE_CLOCK)
        assert reconciled["assembled_record_count"] == 2050

    def test_the_already_posted_lateness_accrual_survives_the_repair(
        self, api: ApiClient
    ) -> None:
        """Curing the data does not refund money the ledger has already taken.

        PRD 3.9: "Conversely, a deficiency that has since been cured contributes
        neither points nor projected exposure while its posted accrual remains on
        the ledger forever."

        Design: Difficulty/compensating_invariant/package_rejection_and_resubmission_conserves_money_while_record_count_moves
        """
        built = _submission_with_rejected_package(api)
        validate_success(
            api.resubmit_package(
                built["pk_d7"]["id"],
                f.resubmit_package_payload(**D7_CORRECTED),
                built["vendor_headers"],
            )
        )
        validate_success(
            api.validate_package(built["pk_d7"]["id"], COMPLIANCE_OFFICER_HEADERS)
        )
        validate_success(
            api.reconcile_rx_submission(
                built["submission_id"], COMPLIANCE_OFFICER_HEADERS
            )
        )

        entries = fx.list_ledger_entries(api, built["plan_year_id"])
        assert len(entries) == 1
        assert entries[0]["deficiency_type"] == DEFICIENCY_RXDC_LATE
        assert entries[0]["signed_amount_cents"] == 560_000

        plan_year = fx.read_plan_year(api, built["plan_year_id"])
        assert plan_year["penalty_exposure_cents"] == 560_000
        assert plan_year["deficiency_points"] == 5
        assert plan_year["compliance_posture"] == POSTURE_AT_RISK


class TestRemediationAbatesHalfTheBase:
    """Completion halves the money and leaves the deficiency exactly where it was."""

    def test_completion_before_every_milestone_is_refused_and_posts_nothing(
        self, api: ApiClient
    ) -> None:
        """A short plan cannot buy an abatement.

        PRD 3.9: "Completing the plan moves it `ACTIVE → COMPLETED`, which is
        terminal, and requires two things: `completed_milestone_count` must equal
        `milestone_count` — a short plan is refused with
        `ERR_MILESTONES_INCOMPLETE` — and at least one unreversed `ACCRUAL` of the
        plan's `target_deficiency_type` must exist on the plan year, because there
        must be money to abate."

        Design: Difficulty/compensating_invariant/remediation_completion_abates_half_the_accrual_without_clearing_points
        """
        setup = _plan_year_with_one_gag_accrual(api)
        plan_year_id = setup["plan_year"]["id"]
        plan = fx.active_remediation_plan(
            api,
            plan_year_id,
            target_deficiency_type=DEFICIENCY_GAG_CLAUSE,
            milestone_count=2,
        )
        assert plan["status"] == REMEDIATION_ACTIVE
        assert plan["completed_milestone_count"] == 0

        response = api.complete_remediation_plan(
            plan["id"],
            COMPLIANCE_OFFICER_HEADERS,
            f.complete_remediation_payload(completion_note="Premature closure attempt."),
        )
        validate_error(response, ApiErrorId.MILESTONES_INCOMPLETE)

        unchanged = validate_success(
            api.get_remediation_plan(plan["id"], COMPLIANCE_OFFICER_HEADERS)
        )
        assert unchanged["status"] == REMEDIATION_ACTIVE
        assert unchanged["abatement_posted_cents"] is None
        assert len(fx.list_ledger_entries(api, plan_year_id)) == 1

    def test_completion_posts_half_the_unreversed_gag_accrual(
        self, api: ApiClient
    ) -> None:
        """30,000 cents of accrual yields a 15,000-cent abatement.

        PRD 3.9: "A single unreversed gag-clause accrual of 30,000 cents therefore
        yields an abatement of 15,000 cents and a resulting ledger balance of
        15,000 cents while the contract remains `NON_COMPLIANT` and its six points
        remain."

        Design: Difficulty/compensating_invariant/remediation_completion_abates_half_the_accrual_without_clearing_points
        """
        setup = _plan_year_with_one_gag_accrual(api)
        plan_year_id = setup["plan_year"]["id"]
        plan = fx.remediation_plan_with_all_milestones(
            api,
            plan_year_id,
            milestone_labels=(MILESTONE_ONE, MILESTONE_TWO),
            target_deficiency_type=DEFICIENCY_GAG_CLAUSE,
        )
        assert plan["completed_milestone_count"] == 2
        assert plan["last_milestone_label"] == MILESTONE_TWO

        completed = validate_success(
            api.complete_remediation_plan(
                plan["id"],
                COMPLIANCE_OFFICER_HEADERS,
                f.complete_remediation_payload(
                    completion_note="Both milestones evidenced."
                ),
            )
        )
        assert completed["status"] == REMEDIATION_COMPLETED
        assert completed["abatement_posted_cents"] == 15_000
        assert_instant_equals(completed["completed_at"], GAG_CLOCK)

        abatements = fx.list_ledger_entries(
            api, plan_year_id, entry_type=ENTRY_ABATEMENT
        )
        assert len(abatements) == 1
        abatement = abatements[0]
        assert abatement["signed_amount_cents"] == -15_000
        assert abatement["deficiency_type"] == DEFICIENCY_GAG_CLAUSE
        assert abatement["remediation_plan_id"] == plan["id"]
        assert abatement["reverses_entry_id"] is None
        assert_non_accrual_pricing_fields(abatement)

    def test_the_abatement_moves_money_but_not_deficiency_state(
        self, api: ApiClient
    ) -> None:
        """Half the exposure is written off; all six points remain owed.

        PRD 3.9: "Crucially, `deficiency_points` are **not** reduced by a
        remediation completion: an abatement moves money, not deficiency state,
        and the underlying obligation must still be cured through its own
        workflow."

        Design: Difficulty/compensating_invariant/remediation_completion_abates_half_the_accrual_without_clearing_points
        """
        setup = _plan_year_with_one_gag_accrual(api)
        plan_year_id = setup["plan_year"]["id"]
        fx.completed_remediation_plan(
            api, plan_year_id, target_deficiency_type=DEFICIENCY_GAG_CLAUSE
        )

        entries = fx.list_ledger_entries(api, plan_year_id)
        assert len(entries) == 2
        assert sum(entry["signed_amount_cents"] for entry in entries) == 15_000

        plan_year = fx.read_plan_year(api, plan_year_id)
        assert_exposure_equals_ledger(plan_year, entries)
        assert plan_year["penalty_exposure_cents"] == 15_000
        assert plan_year["deficiency_points"] == 6
        assert plan_year["compliance_posture"] == POSTURE_DEFICIENT
        assert plan_year["lifecycle_status"] == LIFECYCLE_ACTIVE
