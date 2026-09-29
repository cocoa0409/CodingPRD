"""Request admission order, the two optimistic-concurrency guards, and existence checks."""
import pytest

from test_helpers import (
    ApiErrorId,
    UNKNOWN_UUIDS,
    adjust_accumulator,
    claim_line_payload,
    create_accumulator_adjustment_payload,
    create_claim_payload,
    create_contract_payload,
    create_fee_schedule_rate_payload,
    get_accumulator,
    get_claim,
    other_payer_payment_payload,
    override_payload,
    set_clock,
    setup_adjudicated_claim_for_override,
    setup_environment,
    setup_imaging_environment,
    setup_pended_auth_missing_claim,
    setup_stale_filing_environment,
    submit_claim,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    CLAIMS_EXAMINER,
    CLAIMS_INTAKE,
    NETWORK_MANAGER,
    PLAN_ADMIN,
    UTILIZATION_REVIEWER,
    OPEN_SECONDARY_COVERAGE,
)
from test_helpers.test_users import make_medical_director_headers


class TestOverrideStateOutranksSegregationOfDuties:
    def test_a_same_principal_override_on_an_unpended_claim_reports_the_state_error(
        self, api
    ):
        """PRD §2.8: "And an override attempted by the same operator who produced the pend on
        a claim that is not pended reports `ERR_CLAIM_NOT_PENDED`, because state
        admissibility precedes segregation of duties."
        PRD §2.8: "Checks are evaluated strictly in the order below, and the **first** check
        that fails determines the response:"

        Design: Difficulty/priority_pair_validation_conflict/override_state_error_outranks_segregation_of_duties_error
        """
        env = setup_adjudicated_claim_for_override(shared_user_id="u-shared-1")
        assert env["claim"]["status"] == "ADJUDICATED"

        response = api.override_claim(
            env["claim"]["id"],
            override_payload("APPROVE"),
            make_medical_director_headers("u-shared-1"),
        )
        validate_error(response, ApiErrorId.ERR_CLAIM_NOT_PENDED.value, expected_status=409)
        assert response.status_code != 403, (
            "The state check at step 9 fires before the segregation check at step 11"
        )
        assert get_claim(env["claim"]["id"])["status"] == "ADJUDICATED"

    def test_the_segregation_check_still_fires_once_the_state_is_admissible(self, api):
        """PRD §2.1: "**Segregation of duties.** The `MedicalDirector` who releases or
        converts a pended claim must not be the same principal whose adjudication pass
        produced the pend. The engine compares the overriding director's `X-User-ID` against
        the claim's `last_adjudicated_by_user_id`; when they are equal, the override is
        rejected with `ERR_SEGREGATION_OF_DUTIES` and HTTP 403."

        Design: Difficulty/priority_pair_validation_conflict/override_state_error_outranks_segregation_of_duties_error
        """
        env = setup_pended_auth_missing_claim(examiner_user_id="u-shared-1")
        assert env["claim"]["status"] == "PENDED"

        response = api.override_claim(
            env["claim"]["id"],
            override_payload("APPROVE"),
            make_medical_director_headers("u-shared-1"),
        )
        validate_error(
            response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, expected_status=403
        )
        assert get_claim(env["claim"]["id"])["status"] == "PENDED"


class TestIntakeTimelyFilingOutranksFiscalCeiling:
    def test_a_late_and_over_billed_intake_reports_the_filing_failure(self, api):
        """PRD §2.8: "15. **Timely filing** — on claim intake and on adjustment creation,
        reported as `ERR_TIMELY_FILING_EXCEEDED` (422)."
        PRD §2.8: "18. **Other-payer amount within billed charges** — on claim intake and on
        other-payer posting, reported as `ERR_OTHER_PAYER_EXCEEDS_BILLED` (422)."
        PRD §2.8: "Checks are evaluated strictly in the order below, and the **first** check
        that fails determines the response:"

        Design: Difficulty/priority_pair_validation_conflict/intake_timely_filing_error_outranks_other_payer_exceeds_billed_error
        """
        env = setup_stale_filing_environment()
        payload = create_claim_payload(
            env["member"]["id"],
            env["provider"]["id"],
            [claim_line_payload(1, "73721", 1, 60000, "2026-02-10")],
            claim_number="CLM-PRIO-2",
            other_payer_paid_cents=999999,
        )
        response = api.create_claim(payload, CLAIMS_INTAKE)
        validate_error(
            response, ApiErrorId.ERR_TIMELY_FILING_EXCEEDED.value, expected_status=422
        )

    def test_the_fiscal_ceiling_is_live_and_merely_outranked_by_the_filing_window(self, api):
        """PRD §3.4: "Separately, the reported `other_payer_paid_cents` may never exceed the
        claim's `total_billed_cents`; that fiscal ceiling is enforced both here and on every
        later posting, and a breach returns `ERR_OTHER_PAYER_EXCEEDS_BILLED` with HTTP 422."
        PRD §2.8: "When a request is malformed in more than one way, exactly one error must
        be returned, and which one is not a matter of implementation taste."

        Design: Difficulty/priority_pair_validation_conflict/intake_timely_filing_error_outranks_other_payer_exceeds_billed_error
        """
        env = setup_stale_filing_environment()
        late_and_over_billed = create_claim_payload(
            env["member"]["id"],
            env["provider"]["id"],
            [claim_line_payload(1, "73721", 1, 60000, "2026-02-10")],
            claim_number="CLM-PRIO-2",
            other_payer_paid_cents=999999,
        )
        validate_error(
            api.create_claim(late_and_over_billed, CLAIMS_INTAKE),
            ApiErrorId.ERR_TIMELY_FILING_EXCEEDED.value,
        )
        _rows, meta = validate_paginated(
            api.list_claims(CLAIMS_EXAMINER, params={"member_id": env["member"]["id"]})
        )
        assert meta["total_count"] == 0, "The refused intake persisted no claim row"

        in_window_but_over_billed = create_claim_payload(
            env["member"]["id"],
            env["provider"]["id"],
            [claim_line_payload(1, "73721", 1, 60000, "2026-07-15")],
            claim_number="CLM-PRIO-3",
            other_payer_paid_cents=999999,
        )
        validate_error(
            api.create_claim(in_window_but_over_billed, CLAIMS_INTAKE),
            ApiErrorId.ERR_OTHER_PAYER_EXCEEDS_BILLED.value,
        )


class TestOptimisticConcurrencyGuards:
    def test_a_second_cob_posting_carrying_the_first_version_is_rejected_as_stale(self, api):
        """PRD §2.7: "The first is posting an other-payer payment onto a claim: `POST
        /adjudication/claims/{id}/other-payer-payment` requires a non-optional
        `expected_claim_version` field carrying the `version` of the target claim as the
        client last observed it. If that value does not equal the claim's current `version` —
        because some other writer advanced the claim since the client read it — the request
        is rejected with `ERR_STALE_CLAIM_VERSION` and HTTP 412, and nothing is written. A
        successful posting increments the claim's `version` by one."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_claim_version_on_cob_posting_returns_stale_claim_version
        """
        env = setup_imaging_environment(
            plan_overrides={"plan_code": "CC-1", "name": "Cross Cutting Plan One"},
            provider_overrides={"npi": "6000000001", "name": "CC1 Clinic"},
            member_overrides={"member_number": "M-CC-1"},
            coverages=[OPEN_SECONDARY_COVERAGE],
        )
        claim = submit_claim(
            env["member"]["id"],
            env["provider"]["id"],
            [claim_line_payload(1, "73721", 1, 60000, "2026-02-10")],
            "CLM-CC-1",
        )
        observed_version = claim["version"]

        first = validate_success(
            api.post_other_payer_payment(
                claim["id"], other_payer_payment_payload(12000, observed_version), CLAIMS_INTAKE
            )
        )
        assert first["other_payer_paid_cents"] == 12000
        assert first["version"] == observed_version + 1

        validate_error(
            api.post_other_payer_payment(
                claim["id"], other_payer_payment_payload(19000, observed_version), CLAIMS_INTAKE
            ),
            ApiErrorId.ERR_STALE_CLAIM_VERSION.value,
            expected_status=412,
        )
        assert get_claim(claim["id"])["other_payer_paid_cents"] == 12000

        third = validate_success(
            api.post_other_payer_payment(
                claim["id"], other_payer_payment_payload(19000, first["version"]), CLAIMS_INTAKE
            )
        )
        assert third["other_payer_paid_cents"] == 19000

    def test_a_second_accumulator_delta_carrying_the_first_version_is_rejected_as_stale(
        self, api
    ):
        """PRD §2.7: "The second is posting a manual correction onto a benefit accumulator:
        `POST /adjudication/accumulators/{id}/adjustments` requires a non-optional
        `expected_accumulator_version` field carrying the `version` of the target accumulator
        as the client last observed it. A mismatch against the accumulator's current
        `version` is rejected with `ERR_STALE_ACCUMULATOR_VERSION` and HTTP 412. A successful
        posting increments the accumulator's `version` by one."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_accumulator_version_on_adjustment_returns_stale_accumulator_version
        """
        env = setup_environment(
            plan_overrides={"plan_code": "CC-2", "name": "Cross Cutting Plan Two"},
            member_overrides={"member_number": "M-CC-2"},
            coverages=None,
            with_provider=False,
        )
        accumulator = get_accumulator(env["member"]["id"])
        observed_version = accumulator["version"]

        first = adjust_accumulator(accumulator["id"], observed_version, oop_delta_cents=5000)
        assert first["oop_applied_cents"] == 5000
        assert first["version"] == observed_version + 1

        validate_error(
            api.adjust_accumulator(
                accumulator["id"],
                create_accumulator_adjustment_payload(observed_version, 0, 5000),
                PLAN_ADMIN,
            ),
            ApiErrorId.ERR_STALE_ACCUMULATOR_VERSION.value,
            expected_status=412,
        )
        assert get_accumulator(env["member"]["id"])["oop_applied_cents"] == 5000

        second = adjust_accumulator(accumulator["id"], first["version"], oop_delta_cents=5000)
        assert second["oop_applied_cents"] == 10000


class TestSingleFailureValidations:
    def test_an_over_billed_other_payer_amount_alone_returns_the_fiscal_error(self, api):
        """PRD §3.4: "Separately, the reported `other_payer_paid_cents` may never exceed the
        claim's `total_billed_cents`; that fiscal ceiling is enforced both here and on every
        later posting, and a breach returns `ERR_OTHER_PAYER_EXCEEDS_BILLED` with HTTP 422."

        Design: Corner/validations/other_payer_over_billed_alone_returns_the_fiscal_error_when_filing_window_passes
        """
        env = setup_imaging_environment(
            plan_overrides={"plan_code": "VAL-9", "name": "Validation Plan Nine"},
            provider_overrides={"npi": "3000000009", "name": "VAL9 Clinic"},
            member_overrides={"member_number": "M-VAL-9"},
        )
        payload = create_claim_payload(
            env["member"]["id"],
            env["provider"]["id"],
            [claim_line_payload(1, "73721", 1, 60000, "2026-02-10")],
            claim_number="CLM-VAL-9",
            other_payer_paid_cents=999999,
        )
        validate_error(
            api.create_claim(payload, CLAIMS_INTAKE),
            ApiErrorId.ERR_OTHER_PAYER_EXCEEDS_BILLED.value,
            expected_status=422,
        )
        _rows, meta = validate_paginated(
            api.list_claims(CLAIMS_EXAMINER, params={"member_id": env["member"]["id"]})
        )
        assert meta["total_count"] == 0

    def test_a_correction_that_would_drive_a_balance_below_zero_is_refused(self, api):
        """PRD §3.2: "A correction that would drive either balance below zero is rejected
        with `ERR_ACCUMULATOR_NEGATIVE` and HTTP 422, and neither balance moves."
        PRD §3.2: "A correction that succeeds increments the accumulator's `version` by one."

        Design: Corner/validations/accumulator_adjustment_below_zero_returns_accumulator_negative
        """
        env = setup_environment(
            plan_overrides={"plan_code": "VAL-6", "name": "Validation Plan Six"},
            member_overrides={"member_number": "M-VAL-6"},
            coverages=None,
            with_provider=False,
        )
        accumulator = get_accumulator(env["member"]["id"])
        validate_error(
            api.adjust_accumulator(
                accumulator["id"],
                create_accumulator_adjustment_payload(accumulator["version"], 0, -1),
                PLAN_ADMIN,
            ),
            ApiErrorId.ERR_ACCUMULATOR_NEGATIVE.value,
            expected_status=422,
        )
        after = get_accumulator(env["member"]["id"])
        assert after["deductible_applied_cents"] == 0
        assert after["oop_applied_cents"] == 0
        assert after["version"] == accumulator["version"], (
            "A refused correction is not a mutation, so the version does not move"
        )

    def test_a_limit_above_one_hundred_returns_invalid_pagination(self, api):
        """PRD §2.3: "`limit` controls page size: it defaults to `10`, may not be smaller
        than `1`, and may not be larger than `100`. `offset` controls the starting position:
        it defaults to `0` and may not be negative. A `limit` outside the inclusive range
        from 1 to 100, or a negative `offset`, or a non-integer value for either, is rejected
        with `ERR_INVALID_PAGINATION` and HTTP 400."

        Design: Corner/validations/pagination_limit_above_the_maximum_returns_invalid_pagination
        """
        set_clock()
        validate_error(
            api.list_claims(CLAIMS_EXAMINER, params={"limit": 101, "offset": 0}),
            ApiErrorId.ERR_INVALID_PAGINATION.value,
            expected_status=400,
        )


class TestPathAndBodyExistence:
    def test_reading_an_unknown_claim_id_returns_claim_not_found(self, api):
        """PRD §2.8: "3. **Path existence** — every resource identifier embedded in the URL
        path is resolved **left to right**, and the first identifier that resolves to nothing
        determines the error: `ERR_PLAN_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`,
        `ERR_COVERAGE_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`,
        `ERR_AUTHORIZATION_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_CLAIM_LINE_NOT_FOUND` or
        `ERR_ACCUMULATOR_NOT_FOUND`, each with HTTP 404."

        Design: Corner/entities/get_claim_with_unknown_uuid_returns_claim_not_found
        """
        set_clock()
        response = api.get_claim(UNKNOWN_UUIDS[0], CLAIMS_EXAMINER)
        validate_error(response, ApiErrorId.ERR_CLAIM_NOT_FOUND.value, expected_status=404)
        body = response.json()
        assert body["response_type"] == "error"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert isinstance(body["meta"]["api_request_timestamp"], str)

    def test_revoking_an_unknown_authorization_id_returns_authorization_not_found(self, api):
        """PRD §2.8: "3. **Path existence** — every resource identifier embedded in the URL
        path is resolved **left to right**, and the first identifier that resolves to nothing
        determines the error: `ERR_PLAN_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`,
        `ERR_COVERAGE_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`,
        `ERR_AUTHORIZATION_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_CLAIM_LINE_NOT_FOUND` or
        `ERR_ACCUMULATOR_NOT_FOUND`, each with HTTP 404."

        Design: Corner/errors/revoke_with_an_unknown_authorization_id_returns_authorization_not_found
        """
        set_clock()
        validate_error(
            api.revoke_authorization(UNKNOWN_UUIDS[2], UTILIZATION_REVIEWER),
            ApiErrorId.ERR_AUTHORIZATION_NOT_FOUND.value,
            expected_status=404,
        )

    def test_adjusting_an_unknown_accumulator_id_returns_accumulator_not_found(self, api):
        """PRD §2.8: "3. **Path existence** — every resource identifier embedded in the URL
        path is resolved **left to right**, and the first identifier that resolves to nothing
        determines the error: `ERR_PLAN_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`,
        `ERR_COVERAGE_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`,
        `ERR_AUTHORIZATION_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_CLAIM_LINE_NOT_FOUND` or
        `ERR_ACCUMULATOR_NOT_FOUND`, each with HTTP 404."
        PRD §2.8: "10. **Optimistic concurrency** — the supplied `expected_claim_version` or
        `expected_accumulator_version` matches the parent row's current `version`, per §2.7;
        otherwise `ERR_STALE_CLAIM_VERSION` or `ERR_STALE_ACCUMULATOR_VERSION` with HTTP 412."

        Design: Corner/errors/accumulator_adjustment_with_an_unknown_id_returns_accumulator_not_found
        """
        env = setup_environment(
            plan_overrides={"plan_code": "ERR-2", "name": "Error Plan Two"},
            member_overrides={"member_number": "M-ERR-2"},
            coverages=None,
            with_provider=False,
        )
        real_version = get_accumulator(env["member"]["id"])["version"]
        response = api.adjust_accumulator(
            UNKNOWN_UUIDS[3],
            create_accumulator_adjustment_payload(real_version, 100, 100),
            PLAN_ADMIN,
        )
        validate_error(
            response, ApiErrorId.ERR_ACCUMULATOR_NOT_FOUND.value, expected_status=404
        )
        assert response.status_code != 412, (
            "Path existence at step 3 outranks the concurrency guard at step 10"
        )

    def test_reading_an_unknown_claim_line_id_returns_claim_line_not_found(self, api):
        """PRD §2.8: "3. **Path existence** — every resource identifier embedded in the URL
        path is resolved **left to right**, and the first identifier that resolves to nothing
        determines the error: `ERR_PLAN_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`,
        `ERR_COVERAGE_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`,
        `ERR_AUTHORIZATION_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_CLAIM_LINE_NOT_FOUND` or
        `ERR_ACCUMULATOR_NOT_FOUND`, each with HTTP 404."

        Design: Corner/errors/get_claim_line_with_an_unknown_id_returns_claim_line_not_found
        """
        set_clock()
        validate_error(
            api.get_claim_line(UNKNOWN_UUIDS[4], CLAIMS_EXAMINER),
            ApiErrorId.ERR_CLAIM_LINE_NOT_FOUND.value,
            expected_status=404,
        )

    def test_publishing_a_rate_under_an_unknown_plan_returns_plan_not_found(self, api):
        """PRD §2.8: "3. **Path existence** — every resource identifier embedded in the URL
        path is resolved **left to right**, and the first identifier that resolves to nothing
        determines the error: `ERR_PLAN_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`,
        `ERR_COVERAGE_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`,
        `ERR_AUTHORIZATION_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_CLAIM_LINE_NOT_FOUND` or
        `ERR_ACCUMULATOR_NOT_FOUND`, each with HTTP 404."
        PRD §3.1: "The plan the rate belongs to is taken from the URL, never from the body,
        and is stored as the rate's `plan_id`."

        Design: Corner/errors/publish_fee_rate_under_an_unknown_plan_returns_plan_not_found
        """
        set_clock()
        validate_error(
            api.create_fee_schedule_rate(
                UNKNOWN_UUIDS[5], create_fee_schedule_rate_payload(), NETWORK_MANAGER
            ),
            ApiErrorId.ERR_PLAN_NOT_FOUND.value,
            expected_status=404,
        )

    def test_drafting_a_contract_for_an_unknown_provider_returns_provider_not_found(
        self, api
    ):
        """PRD §2.8: "4. **Body foreign-key existence** — every foreign key supplied in a
        request body resolves to an existing row, reported as `ERR_PLAN_NOT_FOUND`,
        `ERR_MEMBER_NOT_FOUND` or `ERR_PROVIDER_NOT_FOUND` with HTTP 404. This applies to
        member enrolment, contract drafting, authorization issuance and claim intake."

        Design: Corner/errors/create_contract_with_an_unknown_provider_id_returns_provider_not_found
        """
        env = setup_environment(
            plan_overrides={"plan_code": "ERR-5", "name": "Error Plan Five"},
            with_member=False,
            with_provider=False,
            coverages=None,
        )
        validate_error(
            api.create_contract(
                create_contract_payload(
                    UNKNOWN_UUIDS[6],
                    env["plan"]["id"],
                    effective_date="2026-01-01",
                    term_date="2026-06-30",
                    pricing_method="PCT_OF_FEE_SCHEDULE",
                    contract_pct=0.900,
                ),
                NETWORK_MANAGER,
            ),
            ApiErrorId.ERR_PROVIDER_NOT_FOUND.value,
            expected_status=404,
        )

    def test_terminating_an_unknown_coverage_id_returns_coverage_not_found(self, api):
        """PRD §2.8: "3. **Path existence** — every resource identifier embedded in the URL
        path is resolved **left to right**, and the first identifier that resolves to nothing
        determines the error: `ERR_PLAN_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`,
        `ERR_COVERAGE_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`,
        `ERR_AUTHORIZATION_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_CLAIM_LINE_NOT_FOUND` or
        `ERR_ACCUMULATOR_NOT_FOUND`, each with HTTP 404."

        Design: Corner/errors/terminate_with_an_unknown_coverage_id_returns_coverage_not_found
        """
        set_clock()
        validate_error(
            api.terminate_coverage(UNKNOWN_UUIDS[7], {"term_date": "2026-04-01"}, PLAN_ADMIN),
            ApiErrorId.ERR_COVERAGE_NOT_FOUND.value,
            expected_status=404,
        )

    def test_activating_an_unknown_contract_id_returns_contract_not_found(self, api):
        """PRD §2.8: "3. **Path existence** — every resource identifier embedded in the URL
        path is resolved **left to right**, and the first identifier that resolves to nothing
        determines the error: `ERR_PLAN_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`,
        `ERR_COVERAGE_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`,
        `ERR_AUTHORIZATION_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_CLAIM_LINE_NOT_FOUND` or
        `ERR_ACCUMULATOR_NOT_FOUND`, each with HTTP 404."

        Design: Corner/errors/error_contract_not_found_on_activate
        """
        set_clock()
        validate_error(
            api.activate_contract(UNKNOWN_UUIDS[8], NETWORK_MANAGER),
            ApiErrorId.ERR_CONTRACT_NOT_FOUND.value,
            expected_status=404,
        )
