"""State machines whose next move is not determined by the current state alone.

A contract sitting in gag review looks eligible for another remediation request
until the round counter is consulted. Two edges out of a submitted attestation
are shape-identical but have opposite ledger consequences. And one validation
endpoint forks on a payload figure rather than on the row it is called against.
"""

from __future__ import annotations

from test_helpers import (
    COMPLIANCE_OFFICER_HEADERS,
    EXTERNAL_AUDITOR_HEADERS,
    OFFICER_PREPARER_HEADERS,
    OFFICER_PREPARER_USER_ID,
    OFFICER_SIGNER_HEADERS,
    OFFICER_SIGNER_USER_ID,
    SPONSOR_ADMIN_HEADERS,
    ApiClient,
    ApiErrorId,
    ATTESTATION_ACCEPTED,
    ATTESTATION_DRAFT,
    ATTESTATION_REJECTED,
    DEFICIENCY_ATTESTATION_LATE,
    ENTRY_ACCRUAL,
    FILE_TYPE_IN_NETWORK_RATES,
    GAG_IN_REVIEW,
    GAG_NON_COMPLIANT,
    GAG_REMEDIATION_REQUESTED,
    MRF_DRAFT,
    MRF_PUBLISHED,
    MRF_REJECTED,
    MRF_SUPERSEDED,
    POSTURE_AT_RISK,
    POSTURE_COMPLIANT,
    assert_accrual_pricing,
    assert_instant_equals,
    factories as f,
    fixtures as fx,
    make_vendor_contact_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

REVISED_URL = "https://transparency.meridian.example/2027-06/in-network-rates-v2.json"
POSTING_MONTH = "2027-06"


class TestGagRemediationCycleClosesOnRoundCount:
    """The cycle edge is traversable exactly twice, then the loop closes."""

    def test_third_remediation_request_is_refused_from_a_legal_looking_state(
        self, api: ApiClient
    ) -> None:
        """Two rounds are the whole allowance, whatever the status field says.

        PRD 3.4: "The sponsor gets two remediation loops per contract and no
        more; a third request is refused with
        `ERR_REMEDIATION_ROUNDS_EXHAUSTED`, at which point the officer must
        either clear the contract or escalate it."

        Design: Difficulty/non_linear_state_machine/gag_remediation_cycle_third_request_rejected
        """
        fx.set_clock(api, "2027-03-15T09:00:00Z")
        setup = fx.activated_plan_year(api)
        contract_id = setup["tpa_contract"]["id"]
        exhausted = fx.contract_with_remediation_rounds_exhausted(
            api, contract_id, setup["tpa_vendor"]["id"]
        )

        assert exhausted["gag_review_status"] == GAG_IN_REVIEW
        assert exhausted["remediation_round"] == 2

        response = api.request_remediation(
            contract_id, COMPLIANCE_OFFICER_HEADERS, f.request_remediation_payload()
        )
        validate_error(response, ApiErrorId.REMEDIATION_ROUNDS_EXHAUSTED)

        after = fx.read_contract(api, contract_id)
        assert after["gag_review_status"] == GAG_IN_REVIEW
        assert after["remediation_round"] == 2
        assert after["prohibited_clause_count"] == 1

        plan_year = fx.read_plan_year(api, setup["plan_year"]["id"])
        assert plan_year["deficiency_points"] == 0
        assert plan_year["compliance_posture"] == POSTURE_COMPLIANT

    def test_each_vendor_submission_re_enters_in_review_and_advances_the_round(
        self, api: ApiClient
    ) -> None:
        """The same status is reached twice with a different round each time.

        PRD 3.4: "This is the cycle edge: `REMEDIATION_REQUESTED → IN_REVIEW →
        REMEDIATION_REQUESTED` may repeat until `remediation_round` reaches 2."

        Design: Difficulty/non_linear_state_machine/gag_remediation_cycle_third_request_rejected
        """
        fx.set_clock(api, "2027-03-15T09:00:00Z")
        setup = fx.activated_plan_year(api)
        contract_id = setup["tpa_contract"]["id"]
        vendor_headers = make_vendor_contact_headers(setup["tpa_vendor"]["id"])
        fx.open_gag_review(
            api, contract_id, clause_inventory_count=40, prohibited_clause_count=3
        )

        observed: list[tuple[str, int, int]] = []
        for restated in (2, 1):
            requested = validate_success(
                api.request_remediation(
                    contract_id,
                    COMPLIANCE_OFFICER_HEADERS,
                    f.request_remediation_payload(),
                )
            )
            assert requested["gag_review_status"] == GAG_REMEDIATION_REQUESTED
            answered = validate_success(
                api.submit_remediation(
                    contract_id,
                    f.submit_remediation_payload(prohibited_clause_count=restated),
                    vendor_headers,
                )
            )
            observed.append(
                (
                    answered["gag_review_status"],
                    answered["remediation_round"],
                    answered["prohibited_clause_count"],
                )
            )

        assert observed == [(GAG_IN_REVIEW, 1, 2), (GAG_IN_REVIEW, 2, 1)]

    def test_exhausted_contract_can_still_be_escalated(self, api: ApiClient) -> None:
        """Escalation remains reachable from the exhausted review state.

        PRD 3.4: "It is reachable from either `IN_REVIEW` or
        `REMEDIATION_REQUESTED` — both edges land on the terminal
        `NON_COMPLIANT` and both behave identically — and it requires
        `prohibited_clause_count` of at least 1, so escalating a clean contract
        is refused with `ERR_PROHIBITED_CLAUSES_PRESENT`."

        Design: Difficulty/non_linear_state_machine/gag_remediation_cycle_third_request_rejected
        """
        fx.set_clock(api, "2027-03-15T09:00:00Z")
        setup = fx.activated_plan_year(api)
        contract_id = setup["tpa_contract"]["id"]
        fx.contract_with_remediation_rounds_exhausted(
            api, contract_id, setup["tpa_vendor"]["id"]
        )

        escalated = validate_success(
            api.escalate_gag(
                contract_id, COMPLIANCE_OFFICER_HEADERS, f.escalate_gag_payload()
            )
        )

        assert escalated["gag_review_status"] == GAG_NON_COMPLIANT
        assert escalated["gag_non_compliant_since"] == "2027-03-15"
        assert escalated["remediation_round"] == 2


class TestAttestationBranchDivergence:
    """Rejection posts a ledger accrual; acceptance posts nothing at all."""

    def test_rejection_posts_one_lateness_accrual_and_acceptance_posts_none(
        self, api: ApiClient
    ) -> None:
        """One row walks SUBMITTED to REJECTED to DRAFT to SUBMITTED to ACCEPTED.

        PRD 3.8: "Acceptance posts **no** ledger entry of any kind."

        Design: Difficulty/non_linear_state_machine/attestation_reject_and_accept_branch_side_effect_divergence
        """
        fx.set_clock(api, "2027-04-10T09:00:00Z")
        setup = fx.submittable_attestation_setup(api, covered_lives=6000)
        plan_year_id = setup["plan_year"]["id"]
        attestation_id = setup["attestation"]["id"]

        validate_success(
            api.submit_attestation(
                attestation_id, f.submit_attestation_payload(), OFFICER_SIGNER_HEADERS
            )
        )
        rejected = validate_success(
            api.reject_attestation(
                attestation_id,
                f.reject_attestation_payload(),
                EXTERNAL_AUDITOR_HEADERS,
            )
        )
        assert rejected["status"] == ATTESTATION_REJECTED

        after_rejection = fx.list_ledger_entries(api, plan_year_id)
        assert len(after_rejection) == 1
        entry = after_rejection[0]
        assert entry["entry_type"] == ENTRY_ACCRUAL
        assert entry["deficiency_type"] == DEFICIENCY_ATTESTATION_LATE
        assert entry["onset_date"] == "2027-04-10"
        assert_accrual_pricing(entry, 12_000, 1, 2.0)
        assert entry["signed_amount_cents"] == 24_000

        plan_year = fx.read_plan_year(api, plan_year_id)
        assert plan_year["penalty_exposure_cents"] == 24_000
        assert plan_year["deficiency_points"] == 5
        assert plan_year["compliance_posture"] == POSTURE_AT_RISK

        # Salvage the record and take the other edge out of SUBMITTED.
        validate_success(
            api.revise_attestation(
                attestation_id, f.revise_attestation_payload(), OFFICER_SIGNER_HEADERS
            )
        )
        validate_success(
            api.submit_attestation(
                attestation_id, f.submit_attestation_payload(), OFFICER_PREPARER_HEADERS
            )
        )
        accepted = validate_success(
            api.accept_attestation(
                attestation_id, EXTERNAL_AUDITOR_HEADERS, f.accept_attestation_payload()
            )
        )
        assert accepted["status"] == ATTESTATION_ACCEPTED

        after_acceptance = fx.list_ledger_entries(api, plan_year_id)
        assert len(after_acceptance) == 1
        assert after_acceptance[0]["id"] == entry["id"]

        closed = fx.read_plan_year(api, plan_year_id)
        assert closed["penalty_exposure_cents"] == 24_000
        assert closed["deficiency_points"] == 0
        assert closed["compliance_posture"] == POSTURE_COMPLIANT
        assert closed["attestation_status"] == ATTESTATION_ACCEPTED

    def test_revision_rewrites_the_preparer_so_the_same_row_changes_who_may_submit(
        self, api: ApiClient
    ) -> None:
        """Re-entering DRAFT moves the segregation-of-duties anchor.

        PRD 3.8: "One further effect is easy to overlook and changes who may
        submit next: `prepared_by_user_id` is **replaced** with the revising
        officer's `X-User-ID`, so segregation of duties on the next submission
        is evaluated against the reviser rather than the original author."

        Design: Difficulty/non_linear_state_machine/attestation_reject_and_accept_branch_side_effect_divergence
        """
        fx.set_clock(api, "2027-04-10T09:00:00Z")
        setup = fx.submittable_attestation_setup(api, covered_lives=6000)
        attestation_id = setup["attestation"]["id"]
        assert setup["attestation"]["prepared_by_user_id"] == OFFICER_PREPARER_USER_ID

        validate_success(
            api.submit_attestation(
                attestation_id, f.submit_attestation_payload(), OFFICER_SIGNER_HEADERS
            )
        )
        validate_success(
            api.reject_attestation(
                attestation_id,
                f.reject_attestation_payload(),
                EXTERNAL_AUDITOR_HEADERS,
            )
        )
        revised = validate_success(
            api.revise_attestation(
                attestation_id, f.revise_attestation_payload(), OFFICER_SIGNER_HEADERS
            )
        )

        assert revised["status"] == ATTESTATION_DRAFT
        assert revised["revision_round"] == 1
        assert revised["contract_terms_doc_count"] == 4
        assert revised["submitted_at"] is None
        assert revised["submitted_by_user_id"] is None
        assert revised["rejection_reason"] is None
        assert revised["prepared_by_user_id"] == OFFICER_SIGNER_USER_ID

        # The reviser has disqualified themselves from submitting.
        refused = api.submit_attestation(
            attestation_id, f.submit_attestation_payload(), OFFICER_SIGNER_HEADERS
        )
        validate_error(refused, ApiErrorId.SEGREGATION_OF_DUTIES)


class TestMrfValidationForksOnPayload:
    """The validate endpoint's landing state comes from the request figure."""

    def test_error_count_decides_rejected_or_published_from_the_same_state(
        self, api: ApiClient
    ) -> None:
        """A draft validated with errors is rejected; revised and clean, it publishes.

        PRD 3.2: "When `validation_error_count` is 1 or more the file continues
        `VALIDATING → REJECTED`, `published_at` stays null, and `version`
        increments by 1."

        Design: Difficulty/non_linear_state_machine/mrf_validating_fork_reject_revise_publish_supersede
        """
        fx.set_clock(api, "2027-01-05T09:00:00Z")
        setup = fx.activated_plan_year(api)
        plan_year_id = setup["plan_year"]["id"]

        staged = fx.stage_mrf(
            api,
            plan_year_id,
            file_type=FILE_TYPE_IN_NETWORK_RATES,
            posting_month=POSTING_MONTH,
        )
        assert staged["status"] == MRF_DRAFT

        rejected = validate_success(
            api.validate_mrf(
                staged["id"],
                f.validate_mrf_payload(validation_error_count=3),
                SPONSOR_ADMIN_HEADERS,
            )
        )
        assert rejected["status"] == MRF_REJECTED
        assert rejected["validation_error_count"] == 3
        assert rejected["published_at"] is None

        revised = validate_success(
            api.revise_mrf(
                staged["id"],
                f.revise_mrf_payload(public_url=REVISED_URL, row_count=131_500),
                SPONSOR_ADMIN_HEADERS,
            )
        )
        assert revised["status"] == MRF_DRAFT
        assert revised["public_url"] == REVISED_URL
        assert revised["validation_error_count"] is None

        published = validate_success(
            api.validate_mrf(
                staged["id"],
                f.validate_mrf_payload(validation_error_count=0),
                SPONSOR_ADMIN_HEADERS,
            )
        )
        assert published["status"] == MRF_PUBLISHED
        assert_instant_equals(published["published_at"], "2027-01-05T09:00:00Z")

    def test_publishing_a_sibling_supersedes_the_incumbent_posting(
        self, api: ApiClient
    ) -> None:
        """The transition target depends on sibling state, not the source row alone.

        PRD 3.2: "Reaching `PUBLISHED` displaces the incumbent: any *other*
        machine-readable file sharing the same `plan_year_id`, the same
        `file_type` and the same `posting_month` and currently in `PUBLISHED`
        transitions `PUBLISHED → SUPERSEDED`, has its `superseded_at` stamped
        with the same logical clock instant, and has its own `version`
        incremented by 1."

        Design: Difficulty/non_linear_state_machine/mrf_validating_fork_reject_revise_publish_supersede
        """
        fx.set_clock(api, "2027-01-05T09:00:00Z")
        setup = fx.activated_plan_year(api)
        plan_year_id = setup["plan_year"]["id"]

        incumbent = fx.rejected_mrf(
            api,
            plan_year_id,
            FILE_TYPE_IN_NETWORK_RATES,
            POSTING_MONTH,
            validation_error_count=3,
        )
        validate_success(
            api.revise_mrf(
                incumbent["id"],
                f.revise_mrf_payload(public_url=REVISED_URL, row_count=131_500),
                SPONSOR_ADMIN_HEADERS,
            )
        )
        validate_success(
            api.validate_mrf(
                incumbent["id"],
                f.validate_mrf_payload(validation_error_count=0),
                SPONSOR_ADMIN_HEADERS,
            )
        )

        challenger = fx.published_mrf(
            api,
            plan_year_id,
            FILE_TYPE_IN_NETWORK_RATES,
            POSTING_MONTH,
            public_url="https://transparency.meridian.example/2027-06/in-network-rates-v3.json",
        )
        assert challenger["status"] == MRF_PUBLISHED
        assert_instant_equals(challenger["published_at"], "2027-01-05T09:00:00Z")

        displaced = validate_success(
            api.get_mrf(incumbent["id"], SPONSOR_ADMIN_HEADERS)
        )
        assert displaced["status"] == MRF_SUPERSEDED
        assert_instant_equals(displaced["superseded_at"], "2027-01-05T09:00:00Z")
        # The revision survives the supersede.
        assert displaced["public_url"] == REVISED_URL
        assert displaced["validation_error_count"] == 0

    def test_only_one_published_posting_survives_per_month_and_file_type(
        self, api: ApiClient
    ) -> None:
        """The published set for one key holds exactly the newest row.

        PRD 3.2: "`SUPERSEDED` is terminal; a superseded posting is history and
        cannot be revived."

        Design: Difficulty/non_linear_state_machine/mrf_validating_fork_reject_revise_publish_supersede
        """
        fx.set_clock(api, "2027-01-05T09:00:00Z")
        setup = fx.activated_plan_year(api)
        plan_year_id = setup["plan_year"]["id"]

        fx.published_mrf(
            api, plan_year_id, FILE_TYPE_IN_NETWORK_RATES, POSTING_MONTH
        )
        newest = fx.published_mrf(
            api,
            plan_year_id,
            FILE_TYPE_IN_NETWORK_RATES,
            POSTING_MONTH,
            public_url="https://transparency.meridian.example/2027-06/in-network-rates-v3.json",
        )

        response = api.list_mrfs(
            SPONSOR_ADMIN_HEADERS,
            params={
                "plan_year_id": plan_year_id,
                "file_type": FILE_TYPE_IN_NETWORK_RATES,
                "posting_month": POSTING_MONTH,
                "status": MRF_PUBLISHED,
            },
        )
        rows, meta = validate_paginated(response)
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [newest["id"]]
