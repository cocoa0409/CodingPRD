"""The rejection ladder, upper rungs: authentication, authorization, body id
resolution, body shape, acquirer ownership, batch state, merchant posture,
segregation of duties and clearing timing.
"""
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_client import api_client
from test_helpers.factories import (
    make_acquirer_payload,
    make_decision_payload,
    make_processing_platform_payload,
    make_standard_program_payload,
    make_transaction_record_payload,
    make_verify_category_payload,
)
from test_helpers.fixtures import (
    board_merchant,
    canonical_environment,
    clear_findings,
    create_acquirer,
    create_mcc,
    file_reclassification,
    open_audit,
    open_batch,
    read_audit,
    read_batch,
    read_merchant,
    review_reclassification,
    set_clock,
    start_fieldwork,
    submit_batch,
    sustain_findings,
)
from test_helpers.test_users import (
    TEST_USERS,
    headers_without_role,
    make_acquirer_ops_headers,
    make_category_analyst_headers,
    make_category_approver_headers,
    make_compliance_auditor_headers,
)

NETWORK_ADMIN = TEST_USERS["network_admin_headers"]
CLOCK = "2026-09-03T00:00:00Z"
TWO_ELEMENTS = ["AUTH_CODE", "TERMINAL_ID"]
FIELDWORK_START = "2026-09-03T09:00:00Z"
FIELDWORK_END = "2026-09-04T17:00:00Z"


def _read_request(request_id):
    return validate_success(
        api_client.get_reclassification_request(request_id, NETWORK_ADMIN)
    )


def _total_count(response):
    _rows, meta = validate_paginated(response)
    return meta["total_count"]


def _grocery_batch_environment():
    """One grocery merchant and one OPEN batch under a single COMPLIANT acquirer."""
    env = canonical_environment(CLOCK, program_keys=("SMALL_TICKET", "STANDARD"))
    acquirer_id = env["acquirer"]["id"]
    merchant = board_merchant(acquirer_id, "GROCERY", legal_name="Corner Grocer")
    batch = open_batch(acquirer_id, "2026-09-02", "USD")
    return {
        "platform_id": env["platform"]["id"],
        "acquirer_id": acquirer_id,
        "merchant": merchant,
        "batch": batch,
    }


class TestOutermostRungsOfTheLadder:
    def test_a_well_formed_body_sent_without_a_role_header_is_unauthenticated(self):
        """A perfectly well formed platform creation is refused for the missing role
        header alone, so neither a body-shape nor an authorization error surfaces
        first and no platform row is left behind.

        PRD 2.9: "Both authentication headers are present and `X-User-Role` names one
        of the five roles — otherwise `ERR_UNAUTHENTICATED` (401). Applies to every
        endpoint."

        PRD 2.2: "The `api_request_id` is a server-generated unique identifier for the
        request that starts with `req_`."

        Design: Corner/validations/validation_p1_request_without_the_role_header_returns_401_unauthenticated
        """
        set_clock(CLOCK)

        response = api_client.create_processing_platform(
            make_processing_platform_payload(), headers_without_role()
        )
        assert response.status_code == 401
        validate_error(response, "ERR_UNAUTHENTICATED", 401)

        body = response.json()
        assert body["response_type"] == "error"
        request_id = body["meta"]["api_request_id"]
        assert isinstance(request_id, str)
        assert request_id.startswith("req_")

        assert _total_count(api_client.list_processing_platforms(NETWORK_ADMIN)) == 0

    def test_a_role_outside_the_endpoints_list_is_refused_before_the_body_is_read(self):
        """A `CategoryApprover` posting a syntactically valid rate program is turned
        away on role membership alone, so no rate program is created.

        PRD 2.9: "The acting role appears in the target endpoint's authorized-role
        list — otherwise `ERR_UNAUTHORIZED` (403). Applies to every endpoint."

        Design: Corner/validations/validation_p2_category_approver_calling_a_network_admin_endpoint_is_rejected
        """
        set_clock(CLOCK)

        response = api_client.create_rate_program(
            make_standard_program_payload(
                ["5411"],
                name="Standard",
                base_rate_bps=254,
                per_item_fee_cents=10,
                max_clearing_delay_hours=720,
            ),
            TEST_USERS["category_approver_headers"],
        )
        assert response.status_code == 403
        validate_error(response, "ERR_UNAUTHORIZED", 403)

        assert _total_count(api_client.list_rate_programs(NETWORK_ADMIN)) == 0

    def test_a_body_id_naming_no_stored_platform_is_a_not_found(self):
        """The acquirer body is otherwise valid, but its `platform_id` resolves to
        nothing, so the acquirer is refused rather than created with a dangling
        reference.

        PRD 2.9: "Every identifier supplied in the request body resolves to a stored
        row, checked in the order the endpoint declares its input fields — otherwise
        the matching 404 not-found code."

        Design: Corner/validations/validation_p4_body_id_naming_an_unknown_platform_returns_404_not_found
        """
        set_clock(CLOCK)

        response = api_client.create_acquirer(
            make_acquirer_payload(NON_EXISTENT_UUID), NETWORK_ADMIN
        )
        assert response.status_code == 404
        validate_error(response, "ERR_PLATFORM_NOT_FOUND", 404)

        assert _total_count(api_client.list_acquirers(NETWORK_ADMIN)) == 0

    def test_a_zero_amount_record_is_a_body_shape_violation_not_a_floor_priced_row(
        self,
    ):
        """`amount_cents` of 0 is refused as malformed rather than admitted and
        priced up to the eight-cent assessment floor, and the batch is untouched.

        PRD 2.9: "The request body is well formed — otherwise `ERR_INVALID_REQUEST`
        (400). Applies to every POST endpoint."

        PRD 2.9: "Well formed means: every required field is present and not null;
        every enum-valued field holds a value inside its declared domain (which is
        why `DOWNGRADE_THRESHOLD` supplied as `trigger_reason` on a manual audit
        creation is refused here); integer money and basis-point fields are not
        negative; `amount_cents` is at least 1; `committed_volume_cents` is at least
        1; timestamps parse as ISO 8601; currency codes are exactly three uppercase
        letters; a supplied merchant category code is exactly four digits;
        `window_start` is strictly earlier than `window_end`; `effective_from` is
        strictly earlier than `effective_to`; `fieldwork_start` is at or before
        `fieldwork_end`; `data_elements` is a list of unique uppercase tokens drawn
        from the declared element vocabulary; and `decision` is either `APPROVE` or
        `DENY`."

        Design: Corner/validations/validation_p5_zero_amount_transaction_record_is_rejected_with_400
        """
        state = _grocery_batch_environment()
        batch = state["batch"]

        response = api_client.add_transaction_record(
            batch["id"],
            make_transaction_record_payload(
                state["merchant"]["id"],
                0,
                batch["version"],
                auth_code="A00400",
                auth_timestamp="2026-09-02T00:00:00Z",
                clearing_timestamp="2026-09-02T01:00:00Z",
                data_elements=TWO_ELEMENTS,
            ),
            make_acquirer_ops_headers(state["acquirer_id"]),
        )
        assert response.status_code == 400
        validate_error(response, "ERR_INVALID_REQUEST", 400)

        after = read_batch(batch["id"])
        assert after["record_count"] == 0
        assert after["version"] == batch["version"]


class TestOwnershipAndBatchStateRungs:
    def test_another_acquirers_operator_cannot_add_to_this_acquirers_batch(self):
        """Acquirer B holds the `AcquirerOps` role and every id in the request
        resolves, but B does not own the batch, so the addition is a scope violation
        and the batch stays empty.

        PRD 2.9: "When the acting role is `AcquirerOps`, `X-User-ID` equals the
        acquirer that owns the target resource — otherwise
        `ERR_ACQUIRER_SCOPE_VIOLATION` (403). Applies to every endpoint whose
        authorized-role list includes `AcquirerOps`."

        Design: Corner/validations/validation_p6_acquirer_ops_adding_a_record_to_another_acquirers_batch_is_rejected
        """
        state = _grocery_batch_environment()
        acquirer_b = create_acquirer(
            state["platform_id"], name="Beacon Acquiring", bin_prefix="422222"
        )
        batch = state["batch"]

        response = api_client.add_transaction_record(
            batch["id"],
            make_transaction_record_payload(
                state["merchant"]["id"],
                1200,
                batch["version"],
                auth_code="A00410",
                auth_timestamp="2026-09-02T00:00:00Z",
                clearing_timestamp="2026-09-02T01:00:00Z",
                data_elements=TWO_ELEMENTS,
            ),
            make_acquirer_ops_headers(acquirer_b["id"]),
        )
        assert response.status_code == 403
        validate_error(response, "ERR_ACQUIRER_SCOPE_VIOLATION", 403)

        assert read_batch(batch["id"])["record_count"] == 0

    def test_a_closed_batch_masks_the_stale_version_it_was_also_handed(self):
        """The addition violates both the batch-state rung and the optimistic
        concurrency rung at once; the batch-state rung sits higher, so the version
        check never gets to speak.

        PRD 2.9: "The service reports exactly one error, and which one it reports is
        fixed: checks are evaluated in the strict priority order below, from 1
        downward, and the first check that fails ends the request."

        PRD 2.9: "Lower numbers therefore mask higher ones."

        PRD 2.9: "The settlement batch receiving a clearing record is in status
        `OPEN` — otherwise `ERR_BATCH_NOT_OPEN` (409). Applies to `POST
        /settlement-batches/{id}/transaction-records`."

        PRD 2.9: "`expected_batch_version` equals the stored
        `SettlementBatch.version` — otherwise `ERR_STALE_VERSION` (412). Applies to
        `POST /settlement-batches/{id}/transaction-records`."

        Design: Corner/validations/validation_priority_ordering_batch_not_open_outranks_stale_version_and_is_rejected_with_409
        """
        state = _grocery_batch_environment()
        batch = state["batch"]
        version_before_submission = batch["version"]
        submitted = submit_batch(batch["id"], state["acquirer_id"])
        assert submitted["status"] == "SUBMITTED"
        assert submitted["version"] != version_before_submission

        response = api_client.add_transaction_record(
            batch["id"],
            make_transaction_record_payload(
                state["merchant"]["id"],
                1200,
                version_before_submission - 1,
                auth_code="A00420",
                auth_timestamp="2026-09-02T00:00:00Z",
                clearing_timestamp="2026-09-02T01:00:00Z",
                data_elements=TWO_ELEMENTS,
            ),
            make_acquirer_ops_headers(state["acquirer_id"]),
        )
        assert response.status_code == 409
        error = validate_error(response, "ERR_BATCH_NOT_OPEN", 409)
        assert error["error_id"] != "ERR_STALE_VERSION"

        after = read_batch(batch["id"])
        assert after["status"] == "SUBMITTED"
        assert after["record_count"] == 0


class TestMerchantPostureRungs:
    def test_a_misrepresented_merchant_is_frozen_out_of_the_money_path(self):
        """After an audit sustains its findings the merchant is terminal, so a new
        clearing record is refused instead of being priced under the corrected
        category.

        PRD 2.9: "The referenced merchant's `mcc_status` is not `MISREPRESENTED` —
        otherwise `ERR_MERCHANT_MISREPRESENTED` (409)."

        PRD 2.9: "A merchant proven to have misrepresented its category is frozen out
        of every downstream money or category operation, so this guard covers four
        operations: `POST /reclassification-requests`, `POST
        /settlement-batches/{id}/transaction-records`, `POST /incentive-enrollments`
        and `POST /merchants/{id}/verify-category`."

        Design: Corner/validations/validation_p13_misrepresented_merchant_cannot_take_a_new_clearing_record_and_is_rejected
        """
        env = canonical_environment(
            CLOCK, mcc_codes=("5411", "7995"), program_keys=("SMALL_TICKET", "STANDARD")
        )
        acquirer_id = env["acquirer"]["id"]
        merchant = board_merchant(acquirer_id, "GROCERY", legal_name="Corner Grocer")
        audit = open_audit(merchant["id"], "COMPLAINT", auditor_user_id="auditor-1")
        start_fieldwork(
            audit["id"], FIELDWORK_START, FIELDWORK_END, auditor_user_id="auditor-1"
        )
        sustain_findings(
            audit["id"],
            "7995",
            auditor_user_id="auditor-1",
            findings_note="Observed wagering activity at the outlet",
        )
        assert read_merchant(merchant["id"])["mcc_status"] == "MISREPRESENTED"

        batch = open_batch(acquirer_id, "2026-09-02", "USD")
        response = api_client.add_transaction_record(
            batch["id"],
            make_transaction_record_payload(
                merchant["id"],
                1200,
                batch["version"],
                auth_code="A00430",
                auth_timestamp="2026-09-02T00:00:00Z",
                clearing_timestamp="2026-09-02T01:00:00Z",
                data_elements=TWO_ELEMENTS,
            ),
            make_acquirer_ops_headers(acquirer_id),
        )
        assert response.status_code == 409
        validate_error(response, "ERR_MERCHANT_MISREPRESENTED", 409)

        assert read_merchant(merchant["id"])["mcc_status"] == "MISREPRESENTED"
        after = read_batch(batch["id"])
        assert after["record_count"] == 0
        assert after["total_assessed_cents"] == 0

    def test_a_merchant_under_category_review_cannot_be_verified_at_all(self):
        """A valid documentation reference is supplied and the category definition
        demands one, but the open audit outranks the documentation rung, so
        verification is refused and no verification fields are written.

        PRD 2.9: "The referenced merchant's `mcc_status` is not `UNDER_REVIEW` —
        otherwise `ERR_MERCHANT_UNDER_CATEGORY_REVIEW` (409)."

        PRD 2.9: "While a category audit is open the merchant's category may not be
        re-litigated and it may not take on new incentive commitments, so this guard
        covers three operations: `POST /reclassification-requests`, `POST
        /incentive-enrollments` and `POST /merchants/{id}/verify-category`."

        Design: Corner/validations/validation_p14_merchant_under_category_review_cannot_be_verified_and_is_rejected
        """
        env = canonical_environment(
            CLOCK, mcc_codes=("4900",), program_keys=("STANDARD",)
        )
        acquirer_id = env["acquirer"]["id"]
        merchant = board_merchant(
            acquirer_id, "UTILITY_SERVICE", legal_name="City Water Company"
        )
        assert merchant["mcc_status"] == "PENDING_VERIFICATION"

        audit = open_audit(merchant["id"], "PERIODIC", auditor_user_id="auditor-1")
        assert read_merchant(merchant["id"])["mcc_status"] == "UNDER_REVIEW"

        response = api_client.verify_merchant_category(
            merchant["id"],
            make_verify_category_payload("DOC-4900-0001"),
            make_category_analyst_headers(),
        )
        assert response.status_code == 409
        validate_error(response, "ERR_MERCHANT_UNDER_CATEGORY_REVIEW", 409)

        after = read_merchant(merchant["id"])
        assert after["mcc_status"] == "UNDER_REVIEW"
        assert after["documentation_ref"] is None
        assert after["verified_by_user_id"] is None
        assert read_audit(audit["id"])["status"] == "SCHEDULED"


class TestSegregationOfDutiesRungs:
    def test_the_reviewing_analyst_may_not_also_decide_the_request(self):
        """The approver call carries the same operator identifier as the recorded
        reviewer, so the decision is refused and the request stays open with no
        decision written.

        PRD 2.9: "The deciding approver's `X-User-ID` differs from the request's
        `reviewer_user_id` — otherwise `ERR_SEGREGATION_OF_DUTIES` (403). Applies to
        `POST /reclassification-requests/{id}/decide`."

        Design: Corner/validations/validation_p17_the_reviewing_analyst_cannot_also_decide_and_is_rejected
        """
        env = canonical_environment(CLOCK, program_keys=("STANDARD",))
        acquirer_id = env["acquirer"]["id"]
        create_mcc(
            "5812",
            "RESTAURANT",
            description="Eating Places and Restaurants",
            program_eligibility=[],
        )
        merchant = board_merchant(acquirer_id, "GROCERY", legal_name="Corner Grocer")
        request = file_reclassification(
            merchant["id"],
            "5812",
            acquirer_id,
            expected_merchant_version=merchant["version"],
            justification="Storefront now trades as a restaurant",
        )
        review_reclassification(request["id"], analyst_user_id="analyst-7")

        under_review = _read_request(request["id"])
        assert under_review["reviewer_user_id"] == "analyst-7"
        assert under_review["status"] == "UNDER_REVIEW"

        response = api_client.decide_reclassification_request(
            request["id"],
            make_decision_payload("APPROVE", decision_note="Looks fine to me."),
            make_category_approver_headers("analyst-7"),
        )
        assert response.status_code == 403
        validate_error(response, "ERR_SEGREGATION_OF_DUTIES", 403)

        after = _read_request(request["id"])
        assert after["status"] == "UNDER_REVIEW"
        assert after["decider_user_id"] is None
        assert after["decided_mcc"] is None
        assert read_merchant(merchant["id"])["assigned_mcc"] == "5411"

    def test_the_fieldwork_auditor_may_not_close_their_own_audit(self):
        """The operator recorded as the audit's auditor is barred from the closing
        step, so the audit stays at its finding and no closer is stamped.

        PRD 2.9: "The closing auditor's `X-User-ID` differs from the audit's
        `auditor_user_id` — otherwise `ERR_SEGREGATION_OF_DUTIES` (403). Applies to
        `POST /merchant-category-audits/{id}/close`."

        PRD 3.9: "The acting operator is recorded as `closed_by_user_id` and must be a
        different `X-User-ID` from the `auditor_user_id` who reached the finding; the
        auditor who worked the case may not ratify their own conclusion, and an
        attempt to do so is refused with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/validation_p18_the_fieldwork_auditor_cannot_close_their_own_audit_and_is_rejected
        """
        env = canonical_environment(CLOCK, program_keys=("STANDARD",))
        acquirer_id = env["acquirer"]["id"]
        merchant = board_merchant(acquirer_id, "GROCERY", legal_name="Corner Grocer")
        audit = open_audit(merchant["id"], "COMPLAINT", auditor_user_id="auditor-1")
        start_fieldwork(
            audit["id"], FIELDWORK_START, FIELDWORK_END, auditor_user_id="auditor-1"
        )
        cleared = clear_findings(
            audit["id"],
            auditor_user_id="auditor-1",
            findings_note="Category confirmed correct, no misrepresentation",
        )
        assert cleared["auditor_user_id"] == "auditor-1"
        assert cleared["status"] == "FINDINGS_CLEARED"

        response = api_client.close_merchant_category_audit(
            audit["id"], make_compliance_auditor_headers("auditor-1")
        )
        assert response.status_code == 403
        validate_error(response, "ERR_SEGREGATION_OF_DUTIES", 403)

        after = read_audit(audit["id"])
        assert after["status"] == "FINDINGS_CLEARED"
        assert after["closed_by_user_id"] is None


class TestClearingTimingRung:
    def test_clearing_before_authorization_is_refused_rather_than_absolute_valued(self):
        """A clearing instant one hour before the authorization instant is refused
        outright, so no record is created carrying a negative or absolute-valued
        clearing delay.

        PRD 2.9: "`clearing_timestamp` is at or after `auth_timestamp` — otherwise
        `ERR_CLEARING_BEFORE_AUTH` (422). Equality is legal and yields a clearing
        delay of zero hours. Applies to `POST
        /settlement-batches/{id}/transaction-records`."

        Design: Corner/validations/validation_p19_clearing_timestamp_before_auth_timestamp_is_rejected_with_422
        """
        state = _grocery_batch_environment()
        batch = state["batch"]

        response = api_client.add_transaction_record(
            batch["id"],
            make_transaction_record_payload(
                state["merchant"]["id"],
                1200,
                batch["version"],
                auth_code="A00440",
                auth_timestamp="2026-09-02T05:00:00Z",
                clearing_timestamp="2026-09-02T04:00:00Z",
                data_elements=TWO_ELEMENTS,
            ),
            make_acquirer_ops_headers(state["acquirer_id"]),
        )
        assert response.status_code == 422
        validate_error(response, "ERR_CLEARING_BEFORE_AUTH", 422)

        after = read_batch(batch["id"])
        assert after["record_count"] == 0
        assert after["version"] == batch["version"]
