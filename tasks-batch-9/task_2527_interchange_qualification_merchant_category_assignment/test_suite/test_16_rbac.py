"""Role boundaries: exclusive write capabilities, the two-role approval chain,
entity-backed peer isolation, shared reads and the identity comparison that
segregation of duties really is.
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_client import api_client
from test_helpers.factories import (
    make_audit_payload,
    make_decision_payload,
    make_reclassification_request_payload,
    make_verify_category_payload,
)
from test_helpers.fixtures import (
    add_record,
    board_merchant,
    canonical_environment,
    create_acquirer,
    create_mcc,
    create_platform,
    create_rate_program,
    file_reclassification,
    open_batch,
    read_batch,
    read_merchant,
    read_record,
    review_reclassification,
    set_clock,
    submit_batch,
)
from test_helpers.test_users import (
    TEST_USERS,
    make_acquirer_ops_headers,
    make_category_analyst_headers,
    make_category_approver_headers,
)

NETWORK_ADMIN = TEST_USERS["network_admin_headers"]
CATEGORY_ANALYST = TEST_USERS["category_analyst_headers"]
CATEGORY_APPROVER = TEST_USERS["category_approver_headers"]
COMPLIANCE_AUDITOR = TEST_USERS["compliance_auditor_headers"]
CLOCK = "2026-09-03T00:00:00Z"
TWO_ELEMENTS = ["AUTH_CODE", "TERMINAL_ID"]


def _total_count(response):
    _rows, meta = validate_paginated(response)
    return meta["total_count"]


def _read_request(request_id):
    return validate_success(
        api_client.get_reclassification_request(request_id, NETWORK_ADMIN)
    )


def _documentation_gated_environment():
    """A grocery category that demands documentation, so its merchant really does
    open in `PENDING_VERIFICATION`."""
    set_clock(CLOCK)
    platform = create_platform()
    acquirer = create_acquirer(platform["id"])
    create_mcc(
        "5411",
        "GROCERY",
        description="Grocery Stores",
        program_eligibility=["SMALL_TICKET"],
        requires_documentation=True,
    )
    create_rate_program(
        "STANDARD_FALLBACK",
        "STANDARD",
        ["5411"],
        name="Standard",
        base_rate_bps=254,
        per_item_fee_cents=10,
        requires_data_elements=[],
        max_clearing_delay_hours=720,
    )
    merchant = board_merchant(acquirer["id"], "GROCERY", legal_name="Corner Grocer")
    assert merchant["mcc_status"] == "PENDING_VERIFICATION"
    return {"acquirer_id": acquirer["id"], "merchant": merchant}


def _reclassification_environment(standard_codes=None):
    env = canonical_environment(
        CLOCK,
        program_keys=("STANDARD",),
        eligible_mcc_codes=standard_codes or ["5411"],
    )
    create_mcc(
        "5812",
        "RESTAURANT",
        description="Eating Places and Restaurants",
        program_eligibility=[],
    )
    merchant = board_merchant(
        env["acquirer"]["id"], "GROCERY", legal_name="Corner Grocer"
    )
    return {
        "platform_id": env["platform"]["id"],
        "acquirer_id": env["acquirer"]["id"],
        "acquirer_headers": env["acquirer_headers"],
        "merchant": merchant,
    }


class TestExclusiveWriteCapabilities:
    def test_the_owning_acquirer_may_submit_a_batch_but_never_finalize_it(self):
        """Finalization is a network operation, so the acquirer that owns and submitted
        the batch is still refused, and nothing is priced.

        PRD 2.1: "Once the caller is authenticated, the acting role must appear in the
        authorized-role list of the endpoint being invoked (Section 4 carries that list
        per endpoint); a role that is absent from it is refused with
        `ERR_UNAUTHORIZED` and HTTP 403."

        PRD 2.1: "It owns the reference data — processing platforms, acquirers, the
        merchant category directory, rate programs, quarterly rate versions,
        currency-conversion rates and incentive programs — finalizes clearing batches,
        scores incentive performance, and drives the logical clock."

        PRD 2.1: "`AcquirerOps` is acquirer-side operations: it boards merchants, opens
        and submits clearing batches, files category challenges, schedules
        implementation windows and enrols merchants into incentive programs."

        Design: Corner/rbac/rbac_network_admin_exclusive_finalize_is_rejected_for_acquirer_ops
        """
        env = canonical_environment(CLOCK, program_keys=("SMALL_TICKET", "STANDARD"))
        acquirer_id = env["acquirer"]["id"]
        merchant = board_merchant(acquirer_id, "GROCERY", legal_name="Corner Grocer")
        batch = open_batch(acquirer_id, "2026-09-02", "USD")
        record = add_record(
            batch["id"],
            merchant["id"],
            1200,
            acquirer_id,
            expected_batch_version=batch["version"],
            auth_code="A00490",
            auth_timestamp="2026-09-02T00:00:00Z",
            clearing_timestamp="2026-09-02T01:00:00Z",
            data_elements=TWO_ELEMENTS,
        )
        submit_batch(batch["id"], acquirer_id)

        response = api_client.finalize_settlement_batch(
            batch["id"], env["acquirer_headers"]
        )
        assert response.status_code == 403
        validate_error(response, "ERR_UNAUTHORIZED", 403)

        after = read_batch(batch["id"])
        assert after["status"] == "SUBMITTED"
        assert after["total_assessed_cents"] == 0
        assert read_record(record["id"])["qualification_status"] == "PENDING"
        assert read_merchant(merchant["id"])["lifetime_net_assessed_cents"] == 0

    def test_network_operations_cannot_verify_a_merchant_category(self):
        """The reference-data owner is deliberately barred from the category
        verification step, so the merchant keeps its unverified posture untouched.

        PRD 2.1: "It deliberately cannot verify, review, decide or audit merchant
        categories; those powers sit with the category and compliance roles."

        PRD 3.3: "Verifying a category is a `CategoryAnalyst` action and it advances
        `mcc_status` `PENDING_VERIFICATION → VERIFIED`."

        Design: Corner/rbac/rbac_category_analyst_exclusive_verify_category_is_rejected_for_network_admin
        """
        state = _documentation_gated_environment()
        merchant = state["merchant"]

        response = api_client.verify_merchant_category(
            merchant["id"],
            make_verify_category_payload("DOC-5411-0001"),
            NETWORK_ADMIN,
        )
        assert response.status_code == 403
        validate_error(response, "ERR_UNAUTHORIZED", 403)

        after = read_merchant(merchant["id"])
        assert after["mcc_status"] == "PENDING_VERIFICATION"
        assert after["verified_by_user_id"] is None
        assert after["version"] == merchant["version"]

    def test_only_a_compliance_auditor_may_open_an_audit(self):
        """A category analyst cannot open an audit, and the failed attempt leaves the
        merchant outside review so its own category work is not blocked.

        PRD 2.1: "`ComplianceAuditor` owns the audit lifecycle end to end: opening an
        audit, performing fieldwork, sustaining or clearing findings, and closing."

        PRD 3.9: "Opening one is a `ComplianceAuditor` action and carries `merchant_id`
        plus `trigger_reason`."

        Design: Corner/rbac/rbac_compliance_auditor_exclusive_audit_creation_is_rejected_for_category_analyst
        """
        state = _documentation_gated_environment()
        merchant = state["merchant"]

        response = api_client.create_merchant_category_audit(
            make_audit_payload(merchant["id"], "COMPLAINT"),
            make_category_analyst_headers("analyst-7"),
        )
        assert response.status_code == 403
        validate_error(response, "ERR_UNAUTHORIZED", 403)

        assert read_merchant(merchant["id"])["mcc_status"] == "PENDING_VERIFICATION"
        assert (
            _total_count(api_client.list_merchant_category_audits(COMPLIANCE_AUDITOR))
            == 0
        )

    def test_network_operations_cannot_file_a_category_challenge(self):
        """Filing a challenge is an acquirer attestation, so the role that created the
        reference data behind the merchant is still refused and the merchant is not
        even versioned.

        PRD 2.1: "`AcquirerOps` is acquirer-side operations: it boards merchants, opens
        and submits clearing batches, files category challenges, schedules
        implementation windows and enrols merchants into incentive programs."

        PRD 3.4: "An acquirer that believes a merchant has been mis-categorised files a
        **reclassification request**."

        Design: Corner/rbac/rbac_acquirer_ops_exclusive_reclassification_creation_is_rejected_for_network_admin
        """
        state = _reclassification_environment()
        merchant = state["merchant"]

        response = api_client.create_reclassification_request(
            make_reclassification_request_payload(
                merchant["id"],
                "5812",
                merchant["version"],
                justification="Network-initiated reclassification.",
            ),
            NETWORK_ADMIN,
        )
        assert response.status_code == 403
        validate_error(response, "ERR_UNAUTHORIZED", 403)

        assert (
            _total_count(api_client.list_reclassification_requests(NETWORK_ADMIN)) == 0
        )
        assert read_merchant(merchant["id"])["version"] == merchant["version"]


class TestTheTwoRoleApprovalChain:
    def test_the_reviewing_role_cannot_reach_the_deciding_step_at_all(self):
        """The analyst who legitimately took the request under review is refused on
        role membership, which is a different refusal from the one a wrong-identity
        approver receives.

        PRD 2.1: "`CategoryAnalyst` verifies documentation-gated categories and works
        the review side of the reclassification cycle — taking a request under review
        and returning it for more information — but may never decide one."

        PRD 3.4: "Deciding is a `CategoryApprover` action taken from `UNDER_REVIEW`, and
        it carries `decision` — either `APPROVE` or `DENY` — plus `decision_note`."

        Design: Corner/rbac/rbac_approval_chain_analyst_cannot_perform_the_approver_step_and_is_rejected
        """
        state = _reclassification_environment()
        merchant = state["merchant"]
        request = file_reclassification(
            merchant["id"],
            "5812",
            state["acquirer_id"],
            expected_merchant_version=merchant["version"],
            justification="Storefront now trades as a restaurant",
        )
        review_reclassification(request["id"], analyst_user_id="analyst-7")

        response = api_client.decide_reclassification_request(
            request["id"],
            make_decision_payload("APPROVE", decision_note="Self-approving."),
            make_category_analyst_headers("analyst-7"),
        )
        assert response.status_code == 403
        error = validate_error(response, "ERR_UNAUTHORIZED", 403)
        assert error["error_id"] != "ERR_SEGREGATION_OF_DUTIES"

        assert _read_request(request["id"])["status"] == "UNDER_REVIEW"
        assert read_merchant(merchant["id"])["assigned_mcc"] == "5411"

    def test_a_second_approver_identity_decides_the_reviewed_request_successfully(self):
        """Segregation of duties is an identity comparison rather than a blanket block,
        so an approver who is not the reviewer completes the very call the reviewer's
        identity was refused.

        PRD 2.1: "The `CategoryApprover` deciding a reclassification request must
        present an `X-User-ID` different from the `reviewer_user_id` stored on that
        request."

        PRD 3.4: "On `APPROVE` the request advances `UNDER_REVIEW → APPROVED`,
        `decided_mcc` is set to the `requested_mcc`, and the approval must also clear
        one further hurdle: where the requested category's definition has
        `requires_documentation` true, a non-null `supporting_doc_ref` must already be
        on file."

        PRD 3.4: "**Hop one** rewrites the merchant: `assigned_mcc` becomes the
        requested code, and where the requested definition has `requires_documentation`
        true the merchant's `mcc_status` is reset to `PENDING_VERIFICATION`, while where
        it is false the `mcc_status` is left exactly as it was."

        Design: Corner/rbac/rbac_segregation_of_duties_a_second_approver_identity_can_decide_the_reviewed_request
        """
        state = _reclassification_environment(standard_codes=["5411", "5812"])
        merchant = state["merchant"]
        request = file_reclassification(
            merchant["id"],
            "5812",
            state["acquirer_id"],
            expected_merchant_version=merchant["version"],
            justification="Storefront now trades as a restaurant",
        )
        reviewed = review_reclassification(request["id"], analyst_user_id="analyst-7")
        assert reviewed["reviewer_user_id"] == "analyst-7"

        response = api_client.decide_reclassification_request(
            request["id"],
            make_decision_payload("APPROVE", decision_note="Independent approval."),
            make_category_approver_headers("approver-9"),
        )
        assert response.status_code == 200
        decided = validate_success(response)
        assert decided["status"] == "APPROVED"
        assert decided["decider_user_id"] == "approver-9"
        assert decided["decided_mcc"] == "5812"

        after = read_merchant(merchant["id"])
        assert after["assigned_mcc"] == "5812"
        assert after["version"] > merchant["version"]


class TestPeerIsolationAndSharedReads:
    def test_a_foreign_acquirer_may_read_the_merchant_but_not_challenge_it(self):
        """Both acquirers hold the same role, so the isolation is entity-backed: the
        write is a scope violation rather than a role refusal.

        PRD 2.1: "Concretely, an `AcquirerOps` caller may act only where
        `Merchant.acquirer_id`, `SettlementBatch.acquirer_id` or
        `AcquirerImplementationWindow.acquirer_id` equals its own `X-User-ID`; for a
        reclassification request or an incentive enrollment the check follows the row
        through to its merchant and compares that merchant's sponsoring acquirer; and
        where the request body itself carries an `acquirer_id`, that value must equal
        `X-User-ID`."

        PRD 2.1: "A violation is refused with `ERR_ACQUIRER_SCOPE_VIOLATION` and HTTP
        403."

        Design: Corner/rbac/rbac_peer_roles_foreign_acquirer_cannot_file_a_reclassification_and_is_rejected
        """
        state = _reclassification_environment()
        merchant = state["merchant"]
        acquirer_b = create_acquirer(
            state["platform_id"], name="Beacon Acquiring", bin_prefix="422222"
        )
        headers_b = make_acquirer_ops_headers(acquirer_b["id"])

        response = api_client.create_reclassification_request(
            make_reclassification_request_payload(
                merchant["id"],
                "5812",
                merchant["version"],
                justification="Poaching attempt.",
            ),
            headers_b,
        )
        assert response.status_code == 403
        error = validate_error(response, "ERR_ACQUIRER_SCOPE_VIOLATION", 403)
        assert error["error_id"] != "ERR_UNAUTHORIZED"

        assert (
            _total_count(api_client.list_reclassification_requests(NETWORK_ADMIN)) == 0
        )

    def test_all_five_roles_see_the_same_merchant_collection(self):
        """The merchant listing is a shared operation, so every role reads both
        merchants in recording order — reads are never acquirer-scoped even though
        writes are.

        PRD 4: "In the Authorized Role(s) column, "All roles" means all five of
        `NetworkAdmin`, `AcquirerOps`, `CategoryAnalyst`, `CategoryApprover` and
        `ComplianceAuditor`."

        PRD 4: "| GET | `/merchants` | List merchants, filterable by acquirer, category
        posture, assigned code and business type | All roles |"

        PRD 2.3: "Unless a specific collection states otherwise, results are ordered by
        `created_at` ascending, so a client paging through a collection sees rows in the
        order the network recorded them."

        Design: Corner/rbac/rbac_shared_operations_every_role_can_read_the_merchant_collection
        """
        env = canonical_environment(CLOCK, program_keys=("STANDARD",))
        acquirer_a = env["acquirer"]
        acquirer_b = create_acquirer(
            env["platform"]["id"], name="Beacon Acquiring", bin_prefix="422222"
        )
        merchant_a = board_merchant(acquirer_a["id"], "GROCERY", legal_name="Grocer A")
        merchant_b = board_merchant(acquirer_b["id"], "GROCERY", legal_name="Grocer B")
        assert merchant_b["acquirer_id"] == acquirer_b["id"]

        every_role = [
            NETWORK_ADMIN,
            make_acquirer_ops_headers(acquirer_a["id"]),
            CATEGORY_ANALYST,
            CATEGORY_APPROVER,
            COMPLIANCE_AUDITOR,
        ]
        for headers in every_role:
            response = api_client.list_merchants(
                headers, params={"limit": 10, "offset": 0}
            )
            assert response.status_code == 200
            rows, meta = validate_paginated(response)
            assert meta["total_count"] == 2
            assert meta["has_more"] is False
            assert rows[0]["id"] == merchant_a["id"]
