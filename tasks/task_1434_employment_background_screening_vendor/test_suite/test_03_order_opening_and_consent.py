"""Order opening: initial parallel states, ban-the-box gate, duplicate-order
uniqueness, and consent capture safety checks."""
from test_helpers import (
    ApiErrorId,
    assert_order,
    create_candidate_payload,
    create_consent_payload,
    create_order_payload,
    get_success_data,
    list_order_consents,
    make_candidate_headers,
    setup_screening_config,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

HR = TEST_USERS["hr_admin_headers"]
HM = TEST_USERS["hiring_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]


class TestOrderCreation:
    def test_order_created_with_parallel_initial_states(self, api):
        """PRD section "Positions, Candidates, and Opening an Order": "A new
        order begins with `fulfillment_status` `DRAFT` and `adjudication_status`
        `NOT_STARTED`, its `order_type` set to `INITIAL`, and its
        `rescreen_of_order_id`, `vendor_id`, `dispatched_at`, `sla_due_at`, fee
        fields, and pinned snapshots all null; `escalation_level` starts at
        zero."

        Design: Corner/state_machines/order_created_with_parallel_initial_states
        """
        ctx = setup_screening_config(tag="SM1", with_matrix=False)
        candidate = get_success_data(
            api.create_candidate(
                create_candidate_payload(full_name="Sm One", email="sm1@x.com"), HR
            )
        )
        order = validate_success(
            api.create_order(
                create_order_payload(candidate["id"], ctx["position"]["id"]), HM
            ),
            expected_status=201,
        )
        assert_order(order)
        assert order["fulfillment_status"] == "DRAFT"
        assert order["adjudication_status"] == "NOT_STARTED"
        assert order["order_type"] == "INITIAL"
        assert order["rescreen_of_order_id"] is None
        assert order["vendor_id"] is None
        assert order["dispatched_at"] is None
        assert order["sla_due_at"] is None
        assert order["provisional_fee_cents"] is None
        assert order["final_fee_cents"] is None
        assert order["pinned_package_id"] is None
        assert order["pinned_matrix_id"] is None
        assert order["escalation_level"] == 0

    def test_order_create_missing_candidate_id_returns_invalid_request(self, api):
        """PRD section "Validation Ordering": "Fifth, request shape: required
        fields present ... all rejected as `ERR_INVALID_REQUEST` (HTTP 400)."
        and PRD section "Positions, Candidates, and Opening an Order": "A
        `HiringManager` opens a screening order by supplying a `candidate_id`
        and a `position_id`."

        Design: Corner/entities/order_create_missing_candidate_id_returns_invalid_request
        """
        # The position reference must resolve so that the third validation
        # stage (existence) passes and the request reaches the fifth stage
        # (required-fields shape check) that this test exercises.
        ctx = setup_screening_config(tag="ENT9", with_matrix=False)
        resp = api.create_order({"position_id": ctx["position"]["id"]}, HM)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_ban_the_box_gate_requires_conditional_offer(self, api):
        """PRD section "Positions, Candidates, and Opening an Order": "when the
        position's active jurisdiction rule declares `screening_gate_stage` of
        `POST_CONDITIONAL_OFFER`, the request must carry
        `conditional_offer_extended_at` and that timestamp must not be in the
        future; a missing or future-dated value is rejected with
        `ERR_BAN_THE_BOX_GATE` (HTTP 403)."

        Design: Corner/validations/ban_the_box_gate_requires_conditional_offer
        """
        ctx = setup_screening_config(
            tag="VL2",
            with_matrix=False,
            jurisdiction_code="US-CA-OAK",
            jurisdiction_overrides={
                "screening_gate_stage": "POST_CONDITIONAL_OFFER",
                "individualized_assessment_required": True,
            },
        )
        candidate = get_success_data(
            api.create_candidate(
                create_candidate_payload(full_name="Vl Two", email="vl2@x.com"), HR
            )
        )
        get_success_data(api.set_clock("2026-08-05T10:00:00Z"))

        # Missing conditional_offer_extended_at.
        resp1 = api.create_order(
            create_order_payload(candidate["id"], ctx["position"]["id"]), HM
        )
        validate_error(resp1, ApiErrorId.ERR_BAN_THE_BOX_GATE)

        # Future-dated offer.
        resp2 = api.create_order(
            create_order_payload(
                candidate["id"], ctx["position"]["id"],
                conditional_offer_extended_at="2026-08-06T00:00:00Z",
            ),
            HM,
        )
        validate_error(resp2, ApiErrorId.ERR_BAN_THE_BOX_GATE)

        # Past offer satisfies the gate.
        ok = validate_success(
            api.create_order(
                create_order_payload(
                    candidate["id"], ctx["position"]["id"],
                    conditional_offer_extended_at="2026-08-04T00:00:00Z",
                ),
                HM,
            ),
            expected_status=201,
        )
        assert_order(ok)
        assert ok["fulfillment_status"] == "DRAFT"

    def test_duplicate_active_order_per_candidate_position(self, api):
        """PRD section "Positions, Candidates, and Opening an Order":
        "Uniqueness constrains the pair: at most one non-terminal `INITIAL`
        order may exist per (candidate, position) combination; a duplicate is
        rejected with `ERR_DUPLICATE_ACTIVE_ORDER`."

        Design: Corner/validations/duplicate_active_order_per_candidate_position
        """
        ctx = setup_screening_config(tag="VL5", with_matrix=False)
        candidate = get_success_data(
            api.create_candidate(
                create_candidate_payload(full_name="Vl Five", email="vl5@x.com"), HR
            )
        )
        first = validate_success(
            api.create_order(
                create_order_payload(candidate["id"], ctx["position"]["id"]), HM
            ),
            expected_status=201,
        )

        resp = api.create_order(
            create_order_payload(candidate["id"], ctx["position"]["id"]), HM
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACTIVE_ORDER)

        # Cancelling the first order re-opens the slot.
        validate_success(api.cancel_order(first["id"], HM))
        second = validate_success(
            api.create_order(
                create_order_payload(candidate["id"], ctx["position"]["id"]), HM
            ),
            expected_status=201,
        )
        assert second["fulfillment_status"] == "DRAFT"


class TestConsentCapture:
    def test_consent_list_empty_before_capture(self, api):
        """PRD section "API Response Structure": "The `response_type` is either
        "object" for a single resource or "array" for a list of resources." and
        "Pagination-related fields in `meta` (`limit`, `offset`, `total_count`,
        `has_more`) are included for list endpoints."

        Design: Corner/entities/consent_list_empty_before_capture
        """
        ctx = setup_screening_config(tag="ENT7", with_matrix=False)
        candidate = get_success_data(
            api.create_candidate(
                create_candidate_payload(full_name="Ent Seven", email="ent7@x.com"),
                HR,
            )
        )
        order = get_success_data(
            api.create_order(
                create_order_payload(candidate["id"], ctx["position"]["id"]), HM
            )
        )
        data, meta = validate_paginated(api.list_consents(order["id"], HR))
        assert data == []
        assert meta["total_count"] == 0

    def test_standalone_disclosure_and_future_consent(self, api):
        """PRD section "Consent Capture": "`contains_extraneous_terms` must be
        false — a disclosure bundled with liability waivers or other terms
        violates the standalone-document requirement and is rejected with
        `ERR_DISCLOSURE_NOT_STANDALONE` (HTTP 422) — and
        `authorization_signed_at` must not lie in the future of the logical
        clock, else `ERR_CONSENT_IN_FUTURE` (HTTP 422)."

        Design: Corner/validations/standalone_disclosure_and_future_consent
        """
        ctx = setup_screening_config(tag="VL4", with_matrix=False)
        candidate = get_success_data(
            api.create_candidate(
                create_candidate_payload(full_name="Vl Four", email="vl4@x.com"), HR
            )
        )
        get_success_data(api.set_clock("2026-08-05T10:00:00Z"))
        order = get_success_data(
            api.create_order(
                create_order_payload(candidate["id"], ctx["position"]["id"]), HM
            )
        )
        cand_headers = make_candidate_headers(candidate["id"])

        resp1 = api.capture_consent(
            order["id"],
            create_consent_payload(
                disclosure_form_id="DISC-X", contains_extraneous_terms=True
            ),
            cand_headers,
        )
        validate_error(resp1, ApiErrorId.ERR_DISCLOSURE_NOT_STANDALONE)

        resp2 = api.capture_consent(
            order["id"],
            create_consent_payload(authorization_signed_at="2026-08-06T00:00:00Z"),
            cand_headers,
        )
        validate_error(resp2, ApiErrorId.ERR_CONSENT_IN_FUTURE)

        # Both failures leave the order untouched.
        order_now = validate_success(api.get_order(order["id"], HR))
        assert order_now["fulfillment_status"] == "DRAFT"


class TestConsentValidationPriority:
    def test_state_error_beats_standalone_disclosure(self, api):
        """PRD section "Consent Capture": "Two FCRA-shaped safety checks guard
        capture, evaluated after state checks" and PRD section "Validation
        Ordering": "Sixth, state preconditions: the target entity must be in the
        state the operation requires ... Seventh, business-safety rules
        (ban-the-box gating, standalone disclosure, ...)".

        Design: Difficulty/priority_pair_validation_conflict/consent_capture_state_error_beats_standalone_disclosure
        """
        ctx = setup_screening_config(tag="PP1", with_matrix=False)
        candidate = get_success_data(
            api.create_candidate(
                create_candidate_payload(full_name="Pp One", email="pp1@x.com"), HR
            )
        )
        get_success_data(api.set_clock("2026-08-05T10:00:00Z"))
        order = get_success_data(
            api.create_order(
                create_order_payload(candidate["id"], ctx["position"]["id"]), HM
            )
        )
        # Cancel while DRAFT so the state precondition fails, then submit a
        # consent payload that ALSO violates the standalone-disclosure rule.
        validate_success(api.cancel_order(order["id"], HM))

        resp = api.capture_consent(
            order["id"],
            create_consent_payload(
                disclosure_form_id="DISC-BAD", contains_extraneous_terms=True
            ),
            make_candidate_headers(candidate["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_OPEN)

    def test_state_error_leaves_no_consent_record(self, api):
        """PRD section "Consent Capture": "Capture requires the order's
        fulfillment to be `DRAFT`, or — one recovery path — `CONSENT_CAPTURED`
        whose latest consent has already flipped to `EXPIRED`; any other state
        is rejected with `ERR_ORDER_NOT_OPEN`."

        Design: Difficulty/priority_pair_validation_conflict/consent_capture_state_error_beats_standalone_disclosure
        """
        ctx = setup_screening_config(tag="PP1B", with_matrix=False)
        candidate = get_success_data(
            api.create_candidate(
                create_candidate_payload(full_name="Pp OneB", email="pp1b@x.com"),
                HR,
            )
        )
        get_success_data(api.set_clock("2026-08-05T10:00:00Z"))
        order = get_success_data(
            api.create_order(
                create_order_payload(candidate["id"], ctx["position"]["id"]), HM
            )
        )
        validate_success(api.cancel_order(order["id"], HM))

        resp = api.capture_consent(
            order["id"],
            create_consent_payload(
                disclosure_form_id="DISC-BAD", contains_extraneous_terms=True
            ),
            make_candidate_headers(candidate["id"]),
        )
        err = validate_error(resp, ApiErrorId.ERR_ORDER_NOT_OPEN)
        assert err["error_id"] != ApiErrorId.ERR_DISCLOSURE_NOT_STANDALONE

        # No consent record was persisted for the rejected capture.
        assert list_order_consents(order["id"], HR) == []
        order_now = validate_success(api.get_order(order["id"], HR))
        assert order_now["fulfillment_status"] == "CANCELLED"
