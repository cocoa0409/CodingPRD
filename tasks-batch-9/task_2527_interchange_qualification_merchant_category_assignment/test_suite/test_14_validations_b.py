"""The rejection ladder, lower rungs: natural-key uniqueness, category
resolution, programme eligibility, candidate emptiness, currency conversion,
documentation gating, enrollment fiscal rules — and the happy path that clears
every rung at once.
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_client import api_client
from test_helpers.factories import (
    make_acquirer_payload,
    make_incentive_enrollment_payload,
    make_merchant_payload,
    make_sustain_findings_payload,
    make_transaction_record_payload,
    make_verify_category_payload,
)
from test_helpers.fixtures import (
    add_record,
    board_merchant,
    canonical_environment,
    create_fx_rate,
    create_incentive_program,
    create_mcc,
    finalize_batch,
    open_audit,
    open_batch,
    read_audit,
    read_batch,
    read_incentive_program,
    read_merchant,
    read_record,
    start_fieldwork,
    submit_batch,
)
from test_helpers.test_users import (
    TEST_USERS,
    make_acquirer_ops_headers,
    make_category_analyst_headers,
    make_compliance_auditor_headers,
)

NETWORK_ADMIN = TEST_USERS["network_admin_headers"]
CLOCK = "2026-09-03T00:00:00Z"
TWO_ELEMENTS = ["AUTH_CODE", "TERMINAL_ID"]
FIELDWORK_START = "2026-09-03T09:00:00Z"
FIELDWORK_END = "2026-09-04T17:00:00Z"


def _total_count(response):
    _rows, meta = validate_paginated(response)
    return meta["total_count"]


def _grocery_environment(program_keys=("SMALL_TICKET", "STANDARD")):
    env = canonical_environment(CLOCK, program_keys=program_keys)
    acquirer_id = env["acquirer"]["id"]
    merchant = board_merchant(acquirer_id, "GROCERY", legal_name="Corner Grocer")
    return {
        "platform_id": env["platform"]["id"],
        "acquirer_id": acquirer_id,
        "acquirer_headers": env["acquirer_headers"],
        "programs": env["programs"],
        "merchant": merchant,
    }


class TestNaturalKeyUniqueness:
    def test_a_global_key_and_a_batch_scoped_key_both_report_the_same_conflict(self):
        """A duplicate `bin_prefix` is a conflict across the whole network while a
        duplicate `auth_code` is a conflict only inside its own batch, and both are
        reported identically.

        PRD 2.9: "Natural-key uniqueness holds — otherwise `ERR_DUPLICATE_RESOURCE`
        (409)."

        PRD 2.9: "The natural keys are: `MccDefinition.mcc_code` globally unique;
        `RateProgram.program_code` globally unique; `Acquirer.bin_prefix` globally
        unique; a rate version unique on the combination of its `rate_program_id` and
        `publication_quarter`; a settlement batch unique on the combination of
        `acquirer_id`, `batch_date` and `currency_code`; a currency-conversion row
        unique on the combination of `base_currency`, `quote_currency` and
        `effective_from`; and `TransactionRecord.auth_code` unique within a single
        settlement batch."

        Design: Corner/validations/validation_p23_duplicate_bin_prefix_and_duplicate_auth_code_are_both_rejected
        """
        state = _grocery_environment()
        batch = open_batch(state["acquirer_id"], "2026-09-02", "USD")
        add_record(
            batch["id"],
            state["merchant"]["id"],
            1200,
            state["acquirer_id"],
            expected_batch_version=batch["version"],
            auth_code="A00450",
            auth_timestamp="2026-09-02T00:00:00Z",
            clearing_timestamp="2026-09-02T01:00:00Z",
            data_elements=TWO_ELEMENTS,
        )
        version_after_first_record = read_batch(batch["id"])["version"]

        duplicate_bin = api_client.create_acquirer(
            make_acquirer_payload(
                state["platform_id"], name="Copycat Acquiring", bin_prefix="411111"
            ),
            NETWORK_ADMIN,
        )
        assert duplicate_bin.status_code == 409
        validate_error(duplicate_bin, "ERR_DUPLICATE_RESOURCE", 409)

        duplicate_auth = api_client.add_transaction_record(
            batch["id"],
            make_transaction_record_payload(
                state["merchant"]["id"],
                1300,
                version_after_first_record,
                auth_code="A00450",
                auth_timestamp="2026-09-02T02:00:00Z",
                clearing_timestamp="2026-09-02T03:00:00Z",
                data_elements=TWO_ELEMENTS,
            ),
            state["acquirer_headers"],
        )
        assert duplicate_auth.status_code == 409
        validate_error(duplicate_auth, "ERR_DUPLICATE_RESOURCE", 409)

        assert _total_count(api_client.list_acquirers(NETWORK_ADMIN)) == 1
        after = read_batch(batch["id"])
        assert after["record_count"] == 1
        assert after["version"] == version_after_first_record


class TestCategoryResolutionRungs:
    def test_a_business_type_with_no_category_definition_cannot_be_boarded(self):
        """The assignment selector has no candidate definition to rank for the
        declared business type, so the merchant is refused rather than created with
        no category at all.

        PRD 2.9: "At least one `MccDefinition` exists whose `business_type_key` equals
        the merchant's declared `business_type_key`, so that a category can be
        resolved — otherwise `ERR_MCC_NOT_DEFINED` (422). Applies to `POST
        /merchants`."

        Design: Corner/validations/validation_p26_merchant_whose_business_type_has_no_mcc_definition_is_rejected_with_422
        """
        env = canonical_environment(CLOCK, program_keys=("STANDARD",))
        acquirer_id = env["acquirer"]["id"]

        response = api_client.create_merchant(
            make_merchant_payload(
                acquirer_id, "TAXIDERMY", legal_name="Hollow Pines Taxidermy"
            ),
            make_acquirer_ops_headers(acquirer_id),
        )
        assert response.status_code == 422
        validate_error(response, "ERR_MCC_NOT_DEFINED", 422)

        assert _total_count(api_client.list_merchants(NETWORK_ADMIN)) == 0

    def test_sustaining_findings_on_an_undefined_category_leaves_the_audit_open(self):
        """`correct_mcc` names no stored category definition, so the sustaining branch
        is refused before any penalty is assessed and both the audit and the merchant
        stay exactly where they were.

        PRD 2.9: "A supplied `requested_mcc` or `correct_mcc` names an existing
        `MccDefinition.mcc_code` — otherwise `ERR_MCC_NOT_DEFINED` (422). Applies to
        `POST /reclassification-requests` and `POST
        /merchant-category-audits/{id}/sustain-findings`."

        PRD 3.9: "The supplied code must name an existing category definition, failing
        which the request is refused with `ERR_MCC_NOT_DEFINED`."

        Design: Corner/validations/validation_p25_sustaining_findings_on_an_undefined_correct_mcc_is_rejected_with_422
        """
        state = _grocery_environment(program_keys=("STANDARD",))
        audit = open_audit(
            state["merchant"]["id"], "COMPLAINT", auditor_user_id="auditor-1"
        )
        in_fieldwork = start_fieldwork(
            audit["id"], FIELDWORK_START, FIELDWORK_END, auditor_user_id="auditor-1"
        )
        assert in_fieldwork["status"] == "FIELDWORK"

        response = api_client.sustain_audit_findings(
            audit["id"],
            make_sustain_findings_payload(
                "9999", findings_note="Believed to be a different category."
            ),
            make_compliance_auditor_headers("auditor-1"),
        )
        assert response.status_code == 422
        validate_error(response, "ERR_MCC_NOT_DEFINED", 422)

        after = read_audit(audit["id"])
        assert after["status"] == "FIELDWORK"
        assert after["correct_mcc"] is None
        assert after["penalty_assessed_cents"] == 0

        merchant = read_merchant(state["merchant"]["id"])
        assert merchant["mcc_status"] == "UNDER_REVIEW"
        assert merchant["assigned_mcc"] == "5411"


class TestPricingInputRungs:
    def test_a_merchant_outside_the_programmes_category_list_cannot_enrol(self):
        """The commitment clears the minimum and the pool is ample, but the merchant's
        assigned category is not one the programme admits, so the pool is untouched.

        PRD 2.9: "The merchant's `assigned_mcc` appears in the incentive program's
        `eligible_mcc_codes` — otherwise `ERR_MCC_NOT_ELIGIBLE_FOR_PROGRAM` (422).
        Applies to `POST /incentive-enrollments`."

        Design: Corner/validations/validation_p27_merchant_mcc_outside_the_incentive_program_list_is_rejected_with_422
        """
        state = _grocery_environment(program_keys=("STANDARD",))
        create_mcc(
            "5812",
            "RESTAURANT",
            description="Eating Places and Restaurants",
            program_eligibility=[],
        )
        assert state["merchant"]["mcc_status"] == "VERIFIED"
        program = create_incentive_program(
            program_name="Restaurant Volume Incentive 2026",
            eligible_mcc_codes=["5812"],
            min_commitment_cents=5000000,
            total_capacity_cents=1000000000,
        )

        response = api_client.create_incentive_enrollment(
            make_incentive_enrollment_payload(
                program["id"], state["merchant"]["id"], 6000000, program["version"]
            ),
            state["acquirer_headers"],
        )
        assert response.status_code == 422
        validate_error(response, "ERR_MCC_NOT_ELIGIBLE_FOR_PROGRAM", 422)

        after = read_incentive_program(program["id"])
        assert after["enrolled_count"] == 0
        assert after["uncommitted_capacity_cents"] == 1000000000
        assert after["version"] == program["version"]

    def test_an_empty_candidate_set_is_refused_rather_than_priced_at_zero(self):
        """With no fallback tier defined and the only tier demanding four data
        elements the record carries one of, nothing survives the filter, so the
        addition is refused outright.

        PRD 2.9: "At least one rate program is selectable for the record under the
        qualification rules, which in practice means the mandatory `STANDARD` fallback
        program exists — otherwise `ERR_NO_QUALIFYING_RATE_PROGRAM` (422). Applies to
        `POST /settlement-batches/{id}/transaction-records` and `POST
        /settlement-batches/{id}/finalize`."

        PRD 3.5: "If that filter leaves no candidate at all, the addition is refused
        with `ERR_NO_QUALIFYING_RATE_PROGRAM`; in practice this can only happen if the
        mandatory `STANDARD` fallback program is absent from the reference data."

        Design: Corner/validations/validation_p28_record_with_no_selectable_rate_program_is_rejected_with_422
        """
        state = _grocery_environment(program_keys=("CPS_RETAIL",))
        batch = open_batch(state["acquirer_id"], "2026-09-02", "USD")

        response = api_client.add_transaction_record(
            batch["id"],
            make_transaction_record_payload(
                state["merchant"]["id"],
                1200,
                batch["version"],
                auth_code="A00460",
                auth_timestamp="2026-09-02T00:00:00Z",
                clearing_timestamp="2026-09-02T01:00:00Z",
                data_elements=["AUTH_CODE"],
            ),
            state["acquirer_headers"],
        )
        assert response.status_code == 422
        validate_error(response, "ERR_NO_QUALIFYING_RATE_PROGRAM", 422)

        after = read_batch(batch["id"])
        assert after["record_count"] == 0
        assert after["version"] == batch["version"]

    def test_a_foreign_currency_record_with_no_effective_conversion_row_is_refused(self):
        """A conversion row for the pair exists but only becomes effective a week
        later, so the pool the evaluation gathers is empty and the addition is
        refused.

        PRD 2.9: "When `transaction_currency` differs from the batch's
        `currency_code`, a currency-conversion row exists for that pair and is already
        effective — otherwise `ERR_FX_RATE_UNAVAILABLE` (422). Applies to `POST
        /settlement-batches/{id}/transaction-records` and `POST
        /settlement-batches/{id}/finalize`."

        Design: Corner/validations/validation_p29_foreign_currency_record_without_an_fx_rate_is_rejected_with_422
        """
        state = _grocery_environment()
        create_fx_rate("EUR", "USD", "2026-09-10T00:00:00Z")
        batch = open_batch(state["acquirer_id"], "2026-09-02", "USD")

        response = api_client.add_transaction_record(
            batch["id"],
            make_transaction_record_payload(
                state["merchant"]["id"],
                1200,
                batch["version"],
                auth_code="A00470",
                auth_timestamp="2026-09-02T00:00:00Z",
                clearing_timestamp="2026-09-02T01:00:00Z",
                data_elements=TWO_ELEMENTS,
                transaction_currency="EUR",
            ),
            state["acquirer_headers"],
        )
        assert response.status_code == 422
        validate_error(response, "ERR_FX_RATE_UNAVAILABLE", 422)

        after = read_batch(batch["id"])
        assert after["record_count"] == 0
        assert after["version"] == batch["version"]


class TestDocumentationAndEnrollmentRungs:
    def test_a_documentation_gated_category_refuses_an_empty_reference(self):
        """The category definition demands documentation, so an empty reference is
        refused and the merchant keeps its unverified posture and its version.

        PRD 2.9: "When the target `MccDefinition` has `requires_documentation` set to
        true, a non-empty documentation reference accompanies the request —
        `documentation_ref` on category verification, `supporting_doc_ref` on a
        resubmission — otherwise `ERR_DOCUMENTATION_REQUIRED` (422). Applies to `POST
        /merchants/{id}/verify-category` and `POST
        /reclassification-requests/{id}/resubmit`."

        Design: Corner/validations/validation_p30_documentation_gated_mcc_verified_with_an_empty_reference_is_rejected_with_422
        """
        env = canonical_environment(
            CLOCK, mcc_codes=("4900",), program_keys=("STANDARD",)
        )
        merchant = board_merchant(
            env["acquirer"]["id"], "UTILITY_SERVICE", legal_name="City Water Company"
        )
        assert merchant["mcc_status"] == "PENDING_VERIFICATION"

        response = api_client.verify_merchant_category(
            merchant["id"],
            make_verify_category_payload(""),
            make_category_analyst_headers(),
        )
        assert response.status_code == 422
        validate_error(response, "ERR_DOCUMENTATION_REQUIRED", 422)

        after = read_merchant(merchant["id"])
        assert after["mcc_status"] == "PENDING_VERIFICATION"
        assert after["documentation_ref"] is None
        assert after["version"] == merchant["version"]

    def test_the_minimum_commitment_and_the_duplicate_guard_are_independent(self):
        """The same programme refuses a commitment below its minimum, admits one at
        the minimum, and then refuses a second enrollment for the same merchant on
        duplication alone while capacity is still ample.

        PRD 2.9: "`committed_volume_cents` is at least the program's
        `min_commitment_cents` — otherwise `ERR_COMMITMENT_BELOW_MINIMUM` (422).
        Applies to `POST /incentive-enrollments`."

        PRD 2.9: "The merchant holds no enrollment in status `PENDING`, `ENROLLED`,
        `WAITLISTED` or `PROBATION` on the same incentive program — otherwise
        `ERR_DUPLICATE_ENROLLMENT` (409). Applies to `POST /incentive-enrollments`."

        Design: Corner/validations/validation_p31_and_p32_below_minimum_commitment_and_a_second_enrollment_are_both_rejected
        """
        state = _grocery_environment(program_keys=("STANDARD",))
        assert state["merchant"]["mcc_status"] == "VERIFIED"
        program = create_incentive_program(
            eligible_mcc_codes=["5411"],
            min_commitment_cents=5000000,
            reopen_threshold_cents=5000000,
            total_capacity_cents=1000000000,
            performance_threshold_pct=80.00,
        )

        below_minimum = api_client.create_incentive_enrollment(
            make_incentive_enrollment_payload(
                program["id"], state["merchant"]["id"], 1000000, program["version"]
            ),
            state["acquirer_headers"],
        )
        assert below_minimum.status_code == 422
        validate_error(below_minimum, "ERR_COMMITMENT_BELOW_MINIMUM", 422)

        admitted = api_client.create_incentive_enrollment(
            make_incentive_enrollment_payload(
                program["id"], state["merchant"]["id"], 5000000, program["version"]
            ),
            state["acquirer_headers"],
        )
        assert admitted.status_code == 201
        assert validate_success(admitted, 201)["status"] == "ENROLLED"

        after_admission = read_incentive_program(program["id"])
        assert after_admission["uncommitted_capacity_cents"] == 995000000

        duplicate = api_client.create_incentive_enrollment(
            make_incentive_enrollment_payload(
                program["id"],
                state["merchant"]["id"],
                5000000,
                after_admission["version"],
            ),
            state["acquirer_headers"],
        )
        assert duplicate.status_code == 409
        validate_error(duplicate, "ERR_DUPLICATE_ENROLLMENT", 409)

        final = read_incentive_program(program["id"])
        assert final["enrolled_count"] == 1
        assert final["uncommitted_capacity_cents"] == 995000000
        assert final["enrollment_state"] == "OPEN"


class TestTheHappyPathClearsEveryRung:
    def test_board_clear_finalize_and_enrol_all_succeed_in_sequence(self):
        """A single well-formed sequence walks the whole domain — a verified grocery
        merchant, a small-ticket record priced at 24 cents, a finalized batch and an
        admitted enrollment — with no rung firing spuriously anywhere.

        PRD 3.6: "If the selected program's `category` is anything other than
        `STANDARD`, the record advances `PENDING → QUALIFIED`,
        `qualified_rate_program_id` and `assessed_interchange_cents` and
        `mcc_at_qualification` are written, `downgrade_reason` stays null, and
        `authorization_status` is not touched."

        PRD 3.6: "Step one is the ad-valorem component: multiply the record's
        `amount_cents` by the program's `base_rate_bps`, divide by ten thousand, round
        half up to whole cents, and then add the program's `per_item_fee_cents`."

        PRD 3.6: "Once every member record has been assessed, the batch's
        `total_assessed_cents` is re-derived as the sum of `assessed_interchange_cents`
        over the batch's records whose `qualification_status` is `QUALIFIED` or
        `DOWNGRADED`, traversed in ascending `created_at` order; records still in
        `PENDING` and records in `REVERSED` are excluded."

        Design: Corner/validations/validation_satisfaction_the_full_happy_path_clears_every_declared_rule
        """
        state = _grocery_environment()
        merchant = state["merchant"]
        assert merchant["assigned_mcc"] == "5411"
        assert merchant["mcc_status"] == "VERIFIED"

        program = create_incentive_program(
            eligible_mcc_codes=["5411"],
            min_commitment_cents=5000000,
            total_capacity_cents=1000000000,
        )
        batch = open_batch(state["acquirer_id"], "2026-09-02", "USD")
        record = add_record(
            batch["id"],
            merchant["id"],
            1200,
            state["acquirer_id"],
            expected_batch_version=batch["version"],
            auth_code="A00480",
            auth_timestamp="2026-09-02T00:00:00Z",
            clearing_timestamp="2026-09-02T01:00:00Z",
            data_elements=TWO_ELEMENTS,
        )
        submit_batch(batch["id"], state["acquirer_id"])
        finalized = finalize_batch(batch["id"])
        assert finalized["status"] == "FINALIZED"
        assert finalized["record_count"] == 1
        assert finalized["total_assessed_cents"] == 24

        priced = read_record(record["id"])
        assert priced["qualification_status"] == "QUALIFIED"
        assert priced["qualified_rate_program_id"] == state["programs"]["SMALL_TICKET"]["id"]
        assert priced["assessed_interchange_cents"] == 24

        settled = read_merchant(merchant["id"])
        assert settled["lifetime_net_assessed_cents"] == 24
        assert settled["downgrade_count_current_quarter"] == 0

        enrollment = api_client.create_incentive_enrollment(
            make_incentive_enrollment_payload(
                program["id"], merchant["id"], 5000000, program["version"]
            ),
            state["acquirer_headers"],
        )
        assert enrollment.status_code == 201
        assert validate_success(enrollment, 201)["status"] == "ENROLLED"
        assert read_incentive_program(program["id"])["uncommitted_capacity_cents"] == 995000000
