"""Single calls whose effects propagate several entities deep.

Escalating one contract's gag review reaches the ledger, the plan year's money,
its point total, its posture and finally an unrelated attestation draft.
Rejecting one validated data package reaches the submission's record count, its
reconciliation totals and — only because of the demotion those cause — the
penalty ledger.
"""

from __future__ import annotations

from test_helpers import (
    COMPLIANCE_OFFICER_HEADERS,
    OFFICER_USER_ID,
    ApiClient,
    ATTESTATION_MIRROR_NOT_STARTED,
    ATTESTATION_VOIDED,
    DEFICIENCY_GAG_CLAUSE,
    DEFICIENCY_RXDC_LATE,
    ENTRY_ACCRUAL,
    GAG_NON_COMPLIANT,
    PACKAGE_REJECTED,
    POSTURE_AT_RISK,
    POSTURE_COMPLIANT,
    POSTURE_DEFICIENT,
    RX_ASSEMBLING,
    RX_RECONCILED,
    SECTION_D6_RX_TOTALS,
    SECTION_D7_RX_REBATES,
    SECTION_D8_PREMIUM_IMPACT,
    VENDOR_TYPE_PBM,
    VOID_POSTURE_DEFICIENT,
    assert_accrual_pricing,
    assert_exposure_equals_ledger,
    factories as f,
    fixtures as fx,
    validate_success,
)

RECONCILE_CLOCK = "2028-05-20T09:00:00Z"
LATE_CLOCK = "2028-06-15T09:00:00Z"
RXDC_ONSET = "2028-06-02"

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


def _reconciled_submission(api: ApiClient) -> dict:
    """A RECONCILED submission fed by two validated PBM packages."""
    setup = fx.activated_plan_year(api, attestation_deadline_date="2028-12-31")
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
    reconciled = validate_success(
        api.reconcile_rx_submission(submission["id"], COMPLIANCE_OFFICER_HEADERS)
    )
    return {
        "plan_year_id": plan_year_id,
        "pbm_vendor_id": pbm["vendor"]["id"],
        "submission": reconciled,
        **packages,
    }


class TestGagEscalationCascade:
    """One escalation call, five observable links, four entities touched."""

    def test_escalation_reaches_the_attestation_draft_through_the_posture_flip(
        self, api: ApiClient
    ) -> None:
        """The draft is destroyed only because the point total moved the posture.

        PRD 3.4: "Fifth, the posture flip itself voids every attestation of that
        plan year still in `DRAFT`, moving each `DRAFT → VOIDED` with
        `void_reason` set to `POSTURE_DEFICIENT` and each attestation's
        `version` incremented by 1, and refreshes the plan year's
        `attestation_status` from its latest attestation by `created_at`."

        Design: Difficulty/transitive_cascade/gag_escalation_cascade_five_links_to_voided_attestation
        """
        fx.set_clock(api, "2027-05-04T09:00:00Z")
        setup = fx.activated_plan_year(api, covered_lives=6000)
        plan_year_id = setup["plan_year"]["id"]
        contract_id = setup["tpa_contract"]["id"]
        fx.open_gag_review(
            api, contract_id, clause_inventory_count=40, prohibited_clause_count=4
        )
        draft = fx.attestation_draft(api, plan_year_id, contract_terms_doc_count=2)

        escalated = validate_success(
            api.escalate_gag(
                contract_id, COMPLIANCE_OFFICER_HEADERS, f.escalate_gag_payload()
            )
        )
        assert escalated["gag_review_status"] == GAG_NON_COMPLIANT
        assert escalated["gag_non_compliant_since"] == "2027-05-04"

        entries = fx.list_ledger_entries(api, plan_year_id)
        assert len(entries) == 1
        entry = entries[0]
        assert entry["entry_type"] == ENTRY_ACCRUAL
        assert entry["deficiency_type"] == DEFICIENCY_GAG_CLAUSE
        assert entry["onset_date"] == "2027-05-04"
        assert_accrual_pricing(entry, 15_000, 1, 2.0)
        assert entry["signed_amount_cents"] == 30_000

        plan_year = fx.read_plan_year(api, plan_year_id)
        assert plan_year["penalty_exposure_cents"] == 30_000
        assert plan_year["deficiency_points"] == 6
        assert plan_year["compliance_posture"] == POSTURE_DEFICIENT
        assert plan_year["attestation_status"] == ATTESTATION_VOIDED

        voided = validate_success(
            api.get_attestation(draft["id"], COMPLIANCE_OFFICER_HEADERS)
        )
        assert voided["status"] == ATTESTATION_VOIDED
        assert voided["void_reason"] == VOID_POSTURE_DEFICIENT

    def test_first_four_links_hold_even_with_no_draft_to_void(
        self, api: ApiClient
    ) -> None:
        """The money and posture links do not depend on an attestation existing.

        PRD 3.4: "Third, the newly posted entry triggers recomputation of the
        plan year's `penalty_exposure_cents` from the ledger and of its
        `deficiency_points` from live child state."

        Design: Difficulty/transitive_cascade/gag_escalation_cascade_five_links_to_voided_attestation
        """
        fx.set_clock(api, "2027-05-04T09:00:00Z")
        setup = fx.activated_plan_year(api, covered_lives=6000)
        plan_year_id = setup["plan_year"]["id"]
        contract_id = setup["tpa_contract"]["id"]

        before = fx.read_plan_year(api, plan_year_id)
        assert before["compliance_posture"] == POSTURE_COMPLIANT
        assert before["attestation_status"] == ATTESTATION_MIRROR_NOT_STARTED

        fx.gag_non_compliant_contract(api, contract_id, prohibited_clause_count=4)

        entries = fx.list_ledger_entries(api, plan_year_id)
        plan_year = fx.read_plan_year(api, plan_year_id)
        assert len(entries) == 1
        assert_exposure_equals_ledger(plan_year, entries)
        assert plan_year["deficiency_points"] == 6
        assert plan_year["compliance_posture"] == POSTURE_DEFICIENT
        # No draft ever existed, so the mirror has nothing to move to.
        assert plan_year["attestation_status"] == ATTESTATION_MIRROR_NOT_STARTED

    def test_cascade_accrual_records_the_escalating_officer(
        self, api: ApiClient
    ) -> None:
        """The posted entry names the actor whose call caused it.

        PRD 3.9: "a `posted_by_user_id` holding the `X-User-ID` of the actor
        whose call caused the posting — null when the posting came from a
        compliance run rather than a person's action on a specific record."

        Design: Difficulty/transitive_cascade/gag_escalation_cascade_five_links_to_voided_attestation
        """
        fx.set_clock(api, "2027-05-04T09:00:00Z")
        setup = fx.activated_plan_year(api, covered_lives=6000)
        plan_year_id = setup["plan_year"]["id"]
        fx.gag_non_compliant_contract(
            api, setup["tpa_contract"]["id"], prohibited_clause_count=4
        )

        entry = fx.list_ledger_entries(api, plan_year_id)[0]
        assert entry["posted_by_user_id"] == OFFICER_USER_ID
        assert entry["remediation_plan_id"] is None
        assert entry["reverses_entry_id"] is None


class TestValidatedPackageRejectionCascade:
    """Rejecting validated data unwinds the reconciliation and prices lateness."""

    def test_rejection_demotes_the_submission_and_posts_a_lateness_accrual(
        self, api: ApiClient
    ) -> None:
        """The accrual is a consequence of the demotion, not of the rejection.

        PRD 3.6: "Finally, if the logical clock date is strictly after the plan
        year's `rxdc_deadline_date` and no unreversed `RXDC_LATE` accrual
        already exists for that plan year, the demotion posts one penalty ledger
        accrual with `entry_type` `ACCRUAL`, `deficiency_type` `RXDC_LATE` and
        `onset_date` equal to the day after `rxdc_deadline_date`; that posting
        recomputes the plan year's `penalty_exposure_cents`, its
        `deficiency_points` — a submission short of `SUBMITTED` past the
        deadline carries five points — and its `compliance_posture`."

        Design: Difficulty/transitive_cascade/validated_package_rejection_cascade_to_rxdc_accrual
        """
        fx.set_clock(api, RECONCILE_CLOCK)
        built = _reconciled_submission(api)
        plan_year_id = built["plan_year_id"]
        assert built["submission"]["status"] == RX_RECONCILED
        assert built["submission"]["assembled_record_count"] == 2000

        fx.set_clock(api, LATE_CLOCK)
        rejected = validate_success(
            api.reject_package(
                built["pk_d7"]["id"],
                f.reject_package_payload(),
                COMPLIANCE_OFFICER_HEADERS,
            )
        )
        assert rejected["status"] == PACKAGE_REJECTED

        submission = validate_success(
            api.get_rx_submission(
                built["submission"]["id"], COMPLIANCE_OFFICER_HEADERS
            )
        )
        assert submission["status"] == RX_ASSEMBLING
        assert submission["assembled_record_count"] == 1200
        for nulled in (
            "gross_spend_cents",
            "rebate_reported_cents",
            "rebate_cap_pct",
            "rebate_credit_cents",
            "net_plan_spend_cents",
            "reconciled_at",
        ):
            assert submission[nulled] is None, f"{nulled} should be back to null"

        entries = fx.list_ledger_entries(api, plan_year_id)
        assert len(entries) == 1
        entry = entries[0]
        assert entry["deficiency_type"] == DEFICIENCY_RXDC_LATE
        assert entry["onset_date"] == RXDC_ONSET
        assert_accrual_pricing(entry, 20_000, 14, 2.0)
        assert entry["signed_amount_cents"] == 560_000

        plan_year = fx.read_plan_year(api, plan_year_id)
        assert plan_year["penalty_exposure_cents"] == 560_000
        assert plan_year["deficiency_points"] == 5
        assert plan_year["compliance_posture"] == POSTURE_AT_RISK

    def test_no_accrual_when_the_clock_has_not_passed_the_filing_deadline(
        self, api: ApiClient
    ) -> None:
        """The demotion happens; the money does not, because nothing is late yet.

        PRD 3.6: "That decrement leaves the submission without a fully validated
        package set, so a submission sitting in `RECONCILED` demotes `RECONCILED
        → ASSEMBLING`, its `version` increments by 1, and `gross_spend_cents`,
        `rebate_reported_cents`, `rebate_cap_pct`, `rebate_credit_cents`,
        `net_plan_spend_cents` and `reconciled_at` are all set back to null,
        because the reconciliation is no longer supported by validated data."

        Design: Difficulty/transitive_cascade/validated_package_rejection_cascade_to_rxdc_accrual
        """
        fx.set_clock(api, RECONCILE_CLOCK)
        built = _reconciled_submission(api)
        plan_year_id = built["plan_year_id"]

        validate_success(
            api.reject_package(
                built["pk_d7"]["id"],
                f.reject_package_payload(),
                COMPLIANCE_OFFICER_HEADERS,
            )
        )

        submission = validate_success(
            api.get_rx_submission(
                built["submission"]["id"], COMPLIANCE_OFFICER_HEADERS
            )
        )
        assert submission["status"] == RX_ASSEMBLING
        assert submission["assembled_record_count"] == 1200
        assert submission["gross_spend_cents"] is None

        assert fx.list_ledger_entries(api, plan_year_id) == []
        plan_year = fx.read_plan_year(api, plan_year_id)
        assert plan_year["penalty_exposure_cents"] == 0

    def test_rejection_from_received_leaves_the_record_count_untouched(
        self, api: ApiClient
    ) -> None:
        """Only a package that had been counted in can be counted back out.

        PRD 3.6: "From `RECEIVED` it is cheap: `assembled_record_count` is
        unchanged, because a merely received package was never counted into it."

        Design: Difficulty/transitive_cascade/validated_package_rejection_cascade_to_rxdc_accrual
        """
        fx.set_clock(api, RECONCILE_CLOCK)
        built = _reconciled_submission(api)
        plan_year_id = built["plan_year_id"]
        third = fx.request_package(
            api,
            built["submission"]["id"],
            built["pbm_vendor_id"],
            data_section=SECTION_D8_PREMIUM_IMPACT,
            expected_record_count=300,
        )
        fx.delivered_package(
            api,
            third["id"],
            built["pbm_vendor_id"],
            record_count=300,
            plan_paid_cents=100_000,
            member_paid_cents=20_000,
            rebate_cents=5_000,
        )

        fx.set_clock(api, LATE_CLOCK)
        rejected = validate_success(
            api.reject_package(
                third["id"], f.reject_package_payload(), COMPLIANCE_OFFICER_HEADERS
            )
        )
        assert rejected["status"] == PACKAGE_REJECTED

        submission = validate_success(
            api.get_rx_submission(
                built["submission"]["id"], COMPLIANCE_OFFICER_HEADERS
            )
        )
        assert submission["assembled_record_count"] == 2000
        assert fx.list_ledger_entries(api, plan_year_id) == []
