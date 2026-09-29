"""Gates that read the record's own state rather than the request's fields.

Each of these refusals depends on something already written down: how many
clauses the inventory found, whether an instrument actually grants what it was
proposed for, whether the clock has passed an expiry, how many milestones a plan
has left, or whether an auditor has already withdrawn the money once. Where the
guarded condition is satisfied the same call must succeed and score nothing.
"""

from __future__ import annotations

from test_helpers import (
    AUDITOR_USER_ID,
    COMPLIANCE_OFFICER_HEADERS,
    EXTERNAL_AUDITOR_HEADERS,
    OFFICER_PREPARER_HEADERS,
    OFFICER_SIGNER_HEADERS,
    SPONSOR_ADMIN_HEADERS,
    ApiClient,
    ApiErrorId,
    AMENDMENT_LAPSED,
    AMENDMENT_PROPOSED,
    AMENDMENT_TYPE_DATA_RIGHTS,
    ATTESTATION_DRAFT,
    DATA_RIGHTS_NOT_SECURED,
    DATA_RIGHTS_PENDING_AMENDMENT,
    DEFICIENCY_GAG_CLAUSE,
    DEFICIENCY_MRF_REFRESH,
    DISCLOSURE_RECEIVED,
    ENTRY_ACCRUAL,
    GAG_COMPLIANT,
    GAG_IN_REVIEW,
    GAG_NOT_REVIEWED,
    POSTURE_COMPLIANT,
    POSTURE_FROZEN,
    REMEDIATION_ACTIVE,
    VENDOR_TYPE_CONSULTANT,
    VENDOR_TYPE_PBM,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)

REVIEW_CLOCK = "2027-02-01T09:00:00Z"
DISCLOSURE_CLOCK = "2027-03-01T09:00:00Z"
AMENDMENT_CLOCK = "2027-03-01T09:00:00Z"
AFTER_EXPIRY_CLOCK = "2027-04-02T09:00:00Z"
FREEZE_CLOCK = "2027-04-01T09:00:00Z"
GAG_CLOCK = "2027-05-04T09:00:00Z"
ATTESTATION_CLOCK = "2028-01-10T09:00:00Z"

SHORT_EXPIRY = "2027-04-01T00:00:00Z"
LONG_EXPIRY = "2027-12-31T00:00:00Z"
FREEZE_REASON = "DOL audit hold"

FIRST_MILESTONE = "Clause removal rider drafted"
SECOND_MILESTONE = "Executed clause removal rider"
THIRD_MILESTONE = "An extra step nobody planned for"


class TestGagDimensionGates:
    """A clause inventory that must add up, and two one-sided clearance rules."""

    def test_more_prohibited_clauses_than_clauses_inventoried_is_refused(
        self, api: ApiClient
    ) -> None:
        """5 of 3 is arithmetically impossible, and nothing is written first.

        PRD 3.4: "A review that claims more prohibited clauses than clauses
        inventoried, or that supplies a negative count for either, is refused with
        `ERR_CLAUSE_COUNT_INCONSISTENT`."

        Design: Corner/validations/gag_review_clause_counts_inconsistent_rejected
        """
        fx.set_clock(api, REVIEW_CLOCK)
        setup = fx.activated_plan_year(api, covered_lives=6000)
        contract_id = setup["tpa_contract"]["id"]

        validate_error(
            api.gag_review(
                contract_id,
                f.gag_review_payload(
                    clause_inventory_count=3,
                    prohibited_clause_count=5,
                    review_note="Inventory and prohibition tallies disagree.",
                ),
                COMPLIANCE_OFFICER_HEADERS,
            ),
            ApiErrorId.CLAUSE_COUNT_INCONSISTENT,
            expected_status=422,
        )

        stored = fx.read_contract(api, contract_id)
        assert stored["gag_review_status"] == GAG_NOT_REVIEWED
        assert stored["clause_inventory_count"] == 0
        assert stored["prohibited_clause_count"] == 0
        assert stored["version"] == 1

    def test_clearance_needs_a_zero_count_and_escalation_needs_a_positive_one(
        self, api: ApiClient
    ) -> None:
        """One error id guards the rule from both sides.

        PRD 3.4: "It moves the contract `IN_REVIEW → COMPLIANT`, which is
        terminal, and it requires `prohibited_clause_count` to be exactly 0 —
        clearing a contract that still has prohibited language is refused with
        `ERR_PROHIBITED_CLAUSES_PRESENT`."

        PRD 3.4: "It is reachable from either `IN_REVIEW` or
        `REMEDIATION_REQUESTED` — both edges land on the terminal `NON_COMPLIANT`
        and both behave identically — and it requires `prohibited_clause_count` of
        at least 1, so escalating a clean contract is refused with
        `ERR_PROHIBITED_CLAUSES_PRESENT`."

        Design: Corner/validations/clear_gag_with_prohibited_clauses_present_rejected
        """
        fx.set_clock(api, REVIEW_CLOCK)
        setup = fx.activated_plan_year(api, covered_lives=6000)
        plan_year_id = setup["plan_year"]["id"]
        tpa_contract_id = setup["tpa_contract"]["id"]
        pbm = fx.add_contract_for_vendor_type(
            api, plan_year_id, VENDOR_TYPE_PBM, annual_fee_cents=12_000_000
        )
        pbm_contract_id = pbm["contract"]["id"]

        fx.open_gag_review(
            api,
            pbm_contract_id,
            clause_inventory_count=18,
            prohibited_clause_count=2,
        )
        fx.open_gag_review(
            api,
            tpa_contract_id,
            clause_inventory_count=40,
            prohibited_clause_count=0,
        )

        validate_error(
            api.clear_gag(
                pbm_contract_id, COMPLIANCE_OFFICER_HEADERS, f.clear_gag_payload()
            ),
            ApiErrorId.PROHIBITED_CLAUSES_PRESENT,
            expected_status=409,
        )
        validate_error(
            api.escalate_gag(
                tpa_contract_id, COMPLIANCE_OFFICER_HEADERS, f.escalate_gag_payload()
            ),
            ApiErrorId.PROHIBITED_CLAUSES_PRESENT,
            expected_status=409,
        )

        assert fx.read_contract(api, pbm_contract_id)["gag_review_status"] == GAG_IN_REVIEW
        assert fx.read_contract(api, tpa_contract_id)["gag_review_status"] == GAG_IN_REVIEW

        plan_year = fx.read_plan_year(api, plan_year_id)
        assert plan_year["deficiency_points"] == 0
        assert plan_year["penalty_exposure_cents"] == 0

    def test_a_clean_inventory_clears_to_compliant_and_scores_nothing(
        self, api: ApiClient
    ) -> None:
        """Forty clauses with none prohibited is a favourable outcome, not a charge.

        PRD 3.4: "Clearance sets `gag_non_compliant_since` back to null,
        increments the contract's `version` by 1, and recomputes the plan year's
        `deficiency_points` and `compliance_posture`, since a contract leaving
        `NON_COMPLIANT` (or never having reached it) removes its six-point
        weight."

        Design: Corner/validations/gag_review_with_no_prohibited_clauses_clears_to_compliant
        """
        fx.set_clock(api, REVIEW_CLOCK)
        setup = fx.activated_plan_year(api, covered_lives=6000)
        plan_year_id = setup["plan_year"]["id"]
        contract_id = setup["tpa_contract"]["id"]
        fx.open_gag_review(
            api,
            contract_id,
            clause_inventory_count=40,
            prohibited_clause_count=0,
        )

        cleared = validate_success(
            api.clear_gag(
                contract_id, COMPLIANCE_OFFICER_HEADERS, f.clear_gag_payload()
            )
        )
        assert cleared["gag_review_status"] == GAG_COMPLIANT
        assert cleared["gag_non_compliant_since"] is None
        assert cleared["remediation_round"] == 0
        assert cleared["clause_inventory_count"] == 40
        assert cleared["prohibited_clause_count"] == 0

        plan_year = fx.read_plan_year(api, plan_year_id)
        assert plan_year["deficiency_points"] == 0
        assert plan_year["compliance_posture"] == POSTURE_COMPLIANT
        assert plan_year["penalty_exposure_cents"] == 0

        _, meta = validate_paginated(
            api.list_ledger_entries(
                EXTERNAL_AUDITOR_HEADERS, params={"plan_year_id": plan_year_id}
            )
        )
        assert meta["total_count"] == 0


class TestDisclosureApplicability:
    """Only the contracts that carry the flag can carry a disclosure."""

    def test_a_disclosure_against_the_administrator_contract_is_refused(
        self, api: ApiClient
    ) -> None:
        """The consultant contract beside it takes the same payload.

        PRD 3.7: "Only contracts whose `compensation_disclosure_required` is true
        — that is, contracts whose `contract_type` is `BROKER` or `CONSULTANT` —
        can carry a disclosure; a disclosure recorded against a TPA, PBM or
        network vendor contract is refused with `ERR_DISCLOSURE_NOT_APPLICABLE`."

        Design: Corner/validations/compensation_disclosure_on_tpa_contract_rejected
        """
        fx.set_clock(api, DISCLOSURE_CLOCK)
        setup = fx.activated_plan_year(api, covered_lives=6000)
        tpa_contract_id = setup["tpa_contract"]["id"]
        consultant = fx.add_contract_for_vendor_type(
            api,
            setup["plan_year"]["id"],
            VENDOR_TYPE_CONSULTANT,
            annual_fee_cents=1_800_000,
        )
        consultant_contract_id = consultant["contract"]["id"]

        validate_error(
            api.create_compensation_disclosure(
                f.compensation_disclosure_payload(tpa_contract_id),
                SPONSOR_ADMIN_HEADERS,
            ),
            ApiErrorId.DISCLOSURE_NOT_APPLICABLE,
            expected_status=409,
        )

        accepted = validate_success(
            api.create_compensation_disclosure(
                f.compensation_disclosure_payload(consultant_contract_id),
                SPONSOR_ADMIN_HEADERS,
            ),
            expected_status=201,
        )
        assert accepted["status"] == DISCLOSURE_RECEIVED
        assert accepted["unreasonableness_score"] is None

        assert (
            fx.read_contract(api, tpa_contract_id)["compensation_disclosure_required"]
            is False
        )
        assert (
            fx.read_contract(api, consultant_contract_id)[
                "compensation_disclosure_required"
            ]
            is True
        )


class TestAmendmentExecutionGates:
    """What an instrument grants, and whether the clock has passed it by."""

    def test_a_data_rights_amendment_granting_nothing_may_be_proposed_but_not_executed(
        self, api: ApiClient
    ) -> None:
        """The contract sits at PENDING_AMENDMENT and never reaches SECURED.

        PRD 3.5: "Such an amendment may not be executed at all while
        `data_rights_granted` is false: the entire purpose of the instrument is to
        grant those rights, so the attempt is refused with
        `ERR_DATA_RIGHTS_NOT_GRANTED`."

        Design: Corner/validations/data_rights_amendment_without_grant_cannot_execute
        """
        fx.set_clock(api, AMENDMENT_CLOCK)
        setup = fx.activated_plan_year(api, covered_lives=6000)
        pbm = fx.add_contract_for_vendor_type(
            api, setup["plan_year"]["id"], VENDOR_TYPE_PBM, annual_fee_cents=12_000_000
        )
        contract_id = pbm["contract"]["id"]

        amendment = fx.propose_amendment(
            api,
            contract_id,
            amendment_type=AMENDMENT_TYPE_DATA_RIGHTS,
            proposed_terms_summary="Cooperation language only, no data rights yet.",
            data_rights_granted=False,
            expires_at=LONG_EXPIRY,
        )
        assert amendment["status"] == AMENDMENT_PROPOSED
        assert (
            fx.read_contract(api, contract_id)["data_rights_status"]
            == DATA_RIGHTS_PENDING_AMENDMENT
        )

        validate_error(
            api.execute_amendment(
                amendment["id"], SPONSOR_ADMIN_HEADERS, f.execute_amendment_payload()
            ),
            ApiErrorId.DATA_RIGHTS_NOT_GRANTED,
            expected_status=422,
        )

        stored = validate_success(
            api.get_amendment(amendment["id"], SPONSOR_ADMIN_HEADERS)
        )
        assert stored["status"] == AMENDMENT_PROPOSED
        assert stored["executed_at"] is None
        assert (
            fx.read_contract(api, contract_id)["data_rights_status"]
            == DATA_RIGHTS_PENDING_AMENDMENT
        )

    def test_an_expired_proposal_is_refused_on_the_action_before_any_sweep(
        self, api: ApiClient
    ) -> None:
        """It still reads PROPOSED, and only the run moves it to LAPSED.

        PRD 3.5: "Expiry is enforced on the action even while the amendment is
        still recorded as `PROPOSED` or `COUNTERED` because no compliance run has
        yet swept it."

        PRD 3.5: "Lapsing is what can walk the data-rights dimension backwards:
        once the sweep completes, if the contract has no remaining `DATA_RIGHTS`
        amendment in `PROPOSED` or `COUNTERED` and its `data_rights_status` is
        `PENDING_AMENDMENT`, that dimension reverts `PENDING_AMENDMENT →
        NOT_SECURED` and the contract's `version` increments by 1."

        Design: Corner/validations/expired_amendment_execution_rejected
        """
        fx.set_clock(api, AMENDMENT_CLOCK)
        setup = fx.activated_plan_year(api, covered_lives=6000)
        plan_year_id = setup["plan_year"]["id"]
        pbm = fx.add_contract_for_vendor_type(
            api, plan_year_id, VENDOR_TYPE_PBM, annual_fee_cents=12_000_000
        )
        contract_id = pbm["contract"]["id"]
        amendment = fx.propose_amendment(
            api,
            contract_id,
            amendment_type=AMENDMENT_TYPE_DATA_RIGHTS,
            data_rights_granted=True,
            expires_at=SHORT_EXPIRY,
        )

        fx.set_clock(api, AFTER_EXPIRY_CLOCK)
        validate_error(
            api.execute_amendment(
                amendment["id"],
                SPONSOR_ADMIN_HEADERS,
                f.execute_amendment_payload(
                    executed_terms_note="Late execution attempt."
                ),
            ),
            ApiErrorId.AMENDMENT_EXPIRED,
            expected_status=409,
        )

        still_proposed = validate_success(
            api.get_amendment(amendment["id"], SPONSOR_ADMIN_HEADERS)
        )
        assert still_proposed["status"] == AMENDMENT_PROPOSED
        assert still_proposed["round"] == 1
        assert still_proposed["executed_at"] is None
        assert (
            fx.read_contract(api, contract_id)["data_rights_status"]
            == DATA_RIGHTS_PENDING_AMENDMENT
        )

        summary = validate_success(
            api.run_compliance(plan_year_id, COMPLIANCE_OFFICER_HEADERS)
        )
        assert summary["amendments_lapsed_count"] == 1
        assert summary["accruals_posted_count"] == 0

        swept = validate_success(
            api.get_amendment(amendment["id"], SPONSOR_ADMIN_HEADERS)
        )
        assert swept["status"] == AMENDMENT_LAPSED
        assert (
            fx.read_contract(api, contract_id)["data_rights_status"]
            == DATA_RIGHTS_NOT_SECURED
        )


class TestAttestationEvidenceGate:
    """The signed statement needs at least one contract-terms document behind it."""

    def test_a_draft_with_no_contract_terms_evidence_cannot_be_submitted(
        self, api: ApiClient
    ) -> None:
        """Zero is accepted at creation and refused at submission.

        PRD 3.8: "`contract_terms_doc_count` must be at least 1, or the
        submission is refused with `ERR_CONTRACT_TERMS_DOC_REQUIRED`."

        Design: Corner/validations/attestation_submit_without_contract_terms_docs_rejected
        """
        fx.set_clock(api, REVIEW_CLOCK)
        setup = fx.activated_plan_year(api, covered_lives=6000)
        plan_year_id = setup["plan_year"]["id"]
        fx.gag_compliant_contract(api, setup["tpa_contract"]["id"])

        fx.set_clock(api, ATTESTATION_CLOCK)
        draft = fx.attestation_draft(
            api,
            plan_year_id,
            OFFICER_PREPARER_HEADERS,
            contract_terms_doc_count=0,
        )
        assert draft["status"] == ATTESTATION_DRAFT
        assert draft["contract_terms_doc_count"] == 0

        validate_error(
            api.submit_attestation(
                draft["id"], f.submit_attestation_payload(), OFFICER_SIGNER_HEADERS
            ),
            ApiErrorId.CONTRACT_TERMS_DOC_REQUIRED,
            expected_status=422,
        )

        stored = validate_success(
            api.get_attestation(draft["id"], COMPLIANCE_OFFICER_HEADERS)
        )
        assert stored["status"] == ATTESTATION_DRAFT
        assert stored["submitted_by_user_id"] is None
        assert stored["submitted_at"] is None

        plan_year = fx.read_plan_year(api, plan_year_id)
        assert plan_year["attestation_status"] == ATTESTATION_DRAFT


class TestRemediationCompletionGates:
    """A milestone ledger that must balance, and a base that must exist."""

    def test_a_short_plan_and_an_extra_milestone_share_one_error_id(
        self, api: ApiClient
    ) -> None:
        """One of two milestones is too few; three of two is too many.

        PRD 3.9: "A completion recorded beyond `milestone_count` is refused with
        `ERR_MILESTONES_INCOMPLETE`."

        PRD 2.9: "**Milestone accounting.** On remediation plan completion and
        milestone completion — two operations — completion requires
        `completed_milestone_count` equal to `milestone_count`, and a milestone
        recorded beyond `milestone_count` is refused. Either way the code is
        `ERR_MILESTONES_INCOMPLETE` (409)."

        Design: Corner/validations/remediation_completion_with_incomplete_milestones_rejected
        """
        fx.set_clock(api, GAG_CLOCK)
        setup = fx.plan_year_with_gag_accrual(api, covered_lives=6000)
        plan_year_id = setup["plan_year"]["id"]
        plan = fx.active_remediation_plan(
            api,
            plan_year_id,
            target_deficiency_type=DEFICIENCY_GAG_CLAUSE,
            milestone_count=2,
        )
        validate_success(
            api.record_milestone_completion(
                plan["id"],
                f.milestone_completion_payload(milestone_label=FIRST_MILESTONE),
                COMPLIANCE_OFFICER_HEADERS,
            )
        )

        validate_error(
            api.complete_remediation_plan(
                plan["id"],
                COMPLIANCE_OFFICER_HEADERS,
                f.complete_remediation_payload(),
            ),
            ApiErrorId.MILESTONES_INCOMPLETE,
            expected_status=409,
        )

        second = validate_success(
            api.record_milestone_completion(
                plan["id"],
                f.milestone_completion_payload(milestone_label=SECOND_MILESTONE),
                COMPLIANCE_OFFICER_HEADERS,
            )
        )
        assert second["completed_milestone_count"] == 2
        assert second["last_milestone_label"] == SECOND_MILESTONE

        validate_error(
            api.record_milestone_completion(
                plan["id"],
                f.milestone_completion_payload(milestone_label=THIRD_MILESTONE),
                COMPLIANCE_OFFICER_HEADERS,
            ),
            ApiErrorId.MILESTONES_INCOMPLETE,
            expected_status=409,
        )

        stored = validate_success(
            api.get_remediation_plan(plan["id"], COMPLIANCE_OFFICER_HEADERS)
        )
        assert stored["completed_milestone_count"] == 2
        assert stored["status"] == REMEDIATION_ACTIVE
        assert stored["abatement_posted_cents"] is None
        assert stored["completed_at"] is None

        entries = fx.list_ledger_entries(api, plan_year_id)
        assert len(entries) == 1
        assert fx.read_plan_year(api, plan_year_id)["penalty_exposure_cents"] == 30_000

    def test_a_plan_cannot_abate_a_deficiency_family_with_no_accrual(
        self, api: ApiClient
    ) -> None:
        """A gag-clause accrual is no base for a refresh-obligation plan.

        PRD 3.9: "With no such accrual the completion is refused with
        `ERR_NO_ACCRUAL_TO_REMEDIATE`."

        Design: Corner/validations/remediation_completion_without_matching_accrual_rejected
        """
        fx.set_clock(api, GAG_CLOCK)
        setup = fx.plan_year_with_gag_accrual(api, covered_lives=6000)
        plan_year_id = setup["plan_year"]["id"]
        plan = fx.remediation_plan_with_all_milestones(
            api,
            plan_year_id,
            milestone_labels=(FIRST_MILESTONE,),
            target_deficiency_type=DEFICIENCY_MRF_REFRESH,
        )
        assert plan["completed_milestone_count"] == 1

        validate_error(
            api.complete_remediation_plan(
                plan["id"],
                COMPLIANCE_OFFICER_HEADERS,
                f.complete_remediation_payload(),
            ),
            ApiErrorId.NO_ACCRUAL_TO_REMEDIATE,
            expected_status=409,
        )

        stored = validate_success(
            api.get_remediation_plan(plan["id"], COMPLIANCE_OFFICER_HEADERS)
        )
        assert stored["status"] == REMEDIATION_ACTIVE
        assert stored["completed_milestone_count"] == 1
        assert stored["abatement_posted_cents"] is None

        entries = fx.list_ledger_entries(api, plan_year_id)
        assert len(entries) == 1
        assert entries[0]["entry_type"] == ENTRY_ACCRUAL
        assert entries[0]["deficiency_type"] == DEFICIENCY_GAG_CLAUSE
        assert fx.read_plan_year(api, plan_year_id)["penalty_exposure_cents"] == 30_000


class TestLedgerReversalGates:
    """The compensating entry is not itself a candidate for compensation."""

    def test_the_compensating_entry_cannot_be_reversed_in_turn(
        self, api: ApiClient
    ) -> None:
        """A reversal chain would re-inflate exposure without any new deficiency.

        PRD 3.9: "Only accruals are reversible: reversing an abatement, or
        reversing an entry that is itself a reversal, is refused with
        `ERR_NOT_REVERSIBLE_ENTRY`."

        Design: Corner/validations/reversal_entry_is_not_itself_reversible_rejected
        """
        fx.set_clock(api, GAG_CLOCK)
        setup = fx.plan_year_with_gag_accrual(api, covered_lives=6000)
        plan_year_id = setup["plan_year"]["id"]
        accrual_id = setup["accrual"]["id"]
        reversal = fx.reversed_accrual(api, accrual_id)

        validate_error(
            api.reverse_ledger_entry(
                reversal["id"],
                f.reverse_entry_payload(reason="Undo the withdrawal."),
                EXTERNAL_AUDITOR_HEADERS,
            ),
            ApiErrorId.NOT_REVERSIBLE_ENTRY,
            expected_status=409,
        )

        entries = fx.list_ledger_entries(api, plan_year_id)
        assert len(entries) == 2
        assert fx.read_plan_year(api, plan_year_id)["penalty_exposure_cents"] == 0

        stored = validate_success(
            api.get_ledger_entry(reversal["id"], EXTERNAL_AUDITOR_HEADERS)
        )
        assert stored["signed_amount_cents"] == -30_000
        assert stored["reverses_entry_id"] == accrual_id
        assert stored["posted_by_user_id"] == AUDITOR_USER_ID

    def test_the_same_accrual_cannot_be_withdrawn_a_second_time(
        self, api: ApiClient
    ) -> None:
        """The second attempt names the already-reversed accrual, not its kind.

        PRD 3.9: "And an accrual may be reversed at most once — if any entry
        already carries a `reverses_entry_id` equal to this entry's `id`, the
        request is refused with `ERR_ENTRY_ALREADY_REVERSED`."

        Design: Corner/validations/accrual_reversed_twice_rejected
        """
        fx.set_clock(api, GAG_CLOCK)
        setup = fx.plan_year_with_gag_accrual(api, covered_lives=6000)
        plan_year_id = setup["plan_year"]["id"]
        accrual_id = setup["accrual"]["id"]
        fx.reversed_accrual(api, accrual_id)

        validate_error(
            api.reverse_ledger_entry(
                accrual_id,
                f.reverse_entry_payload(reason="Second withdrawal of one accrual."),
                EXTERNAL_AUDITOR_HEADERS,
            ),
            ApiErrorId.ENTRY_ALREADY_REVERSED,
            expected_status=409,
        )

        entries = fx.list_ledger_entries(api, plan_year_id)
        assert len(entries) == 2
        assert fx.read_plan_year(api, plan_year_id)["penalty_exposure_cents"] == 0

        original = validate_success(
            api.get_ledger_entry(accrual_id, EXTERNAL_AUDITOR_HEADERS)
        )
        assert original["signed_amount_cents"] == 30_000
        assert original["entry_type"] == ENTRY_ACCRUAL


class TestFreezeScope:
    """A lockdown that still lets the sponsor dig out from under it."""

    def test_a_frozen_plan_year_refuses_a_new_file_but_allows_remediation_work(
        self, api: ApiClient
    ) -> None:
        """Staging is blocked while opening a plan and recording a milestone are not.

        PRD 2.8: "Five operations are exempt, because the whole point of a freeze
        is to allow the sponsor to dig out from under it: unfreezing the plan year,
        reversing a penalty ledger entry, creating a remediation plan, recording a
        milestone completion on a remediation plan, and completing a remediation
        plan."

        Design: Corner/validations/mrf_create_on_frozen_plan_year_rejected
        """
        fx.set_clock(api, FREEZE_CLOCK)
        setup = fx.activated_plan_year(api, covered_lives=6000)
        plan_year_id = setup["plan_year"]["id"]
        frozen = fx.frozen_plan_year(api, plan_year_id, reason=FREEZE_REASON)
        assert frozen["compliance_posture"] == POSTURE_FROZEN
        assert frozen["freeze_reason"] == FREEZE_REASON

        validate_error(
            api.create_mrf(f.mrf_payload(plan_year_id), SPONSOR_ADMIN_HEADERS),
            ApiErrorId.PLAN_YEAR_FROZEN,
            expected_status=409,
        )

        plan = validate_success(
            api.create_remediation_plan(
                f.remediation_plan_payload(
                    plan_year_id,
                    target_deficiency_type=DEFICIENCY_GAG_CLAUSE,
                    milestone_count=2,
                ),
                COMPLIANCE_OFFICER_HEADERS,
            ),
            expected_status=201,
        )
        assert plan["status"] == REMEDIATION_ACTIVE

        recorded = validate_success(
            api.record_milestone_completion(
                plan["id"],
                f.milestone_completion_payload(milestone_label=FIRST_MILESTONE),
                COMPLIANCE_OFFICER_HEADERS,
            )
        )
        assert recorded["completed_milestone_count"] == 1

        _, meta = validate_paginated(
            api.list_mrfs(SPONSOR_ADMIN_HEADERS, params={"plan_year_id": plan_year_id})
        )
        assert meta["total_count"] == 0
        assert (
            fx.read_plan_year(api, plan_year_id)["compliance_posture"] == POSTURE_FROZEN
        )
