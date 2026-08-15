"""Cancellation, consent revocation, candidate withdrawal, and consent expiry."""
from test_helpers import (
    ApiErrorId,
    create_candidate_payload,
    create_consent_payload,
    create_order_payload,
    finding,
    get_success_data,
    list_order_assessments,
    list_order_consents,
    make_candidate_headers,
    setup_pre_adverse_case,
    setup_screening_config,
    validate_error,
    validate_success,
    TEST_USERS,
)

HR = TEST_USERS["hr_admin_headers"]
HM = TEST_USERS["hiring_manager_headers"]

ADVERSE_FINDINGS = [finding()]


class TestCancelTerminalLockdown:
    def test_cancel_terminal_lockdown(self, api):
        """PRD section "Cancellation, Revocation, and Withdrawal Cascades": "A
        `HiringManager` may cancel an order while its fulfillment is `DRAFT`,
        `CONSENT_CAPTURED`, or `DISPATCHED`; any other state rejects with
        `ERR_ORDER_NOT_CANCELLABLE`."

        Design: Corner/state_machines/cancel_terminal_lockdown
        """
        ctx = setup_screening_config(tag="SM4", with_matrix=False)
        candidate = get_success_data(
            api.create_candidate(
                create_candidate_payload(full_name="Sm Four", email="sm4@x.com"), HR
            )
        )
        order = get_success_data(
            api.create_order(
                create_order_payload(candidate["id"], ctx["position"]["id"]), HM
            )
        )
        cancelled = validate_success(api.cancel_order(order["id"], HM))
        assert cancelled["fulfillment_status"] == "CANCELLED"
        assert cancelled["adjudication_status"] == "VOIDED"

        resp = api.cancel_order(order["id"], HM)
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_CANCELLABLE)
        order_now = get_success_data(api.get_order(order["id"], HR))
        assert order_now["fulfillment_status"] == "CANCELLED"
        assert order_now["adjudication_status"] == "VOIDED"


class TestCandidateWithdrawal:
    def test_candidate_withdraw_cascades_to_all_orders(self, api):
        """PRD section "Cancellation, Revocation, and Withdrawal Cascades": "the
        candidate's status becomes `WITHDRAWN` and every non-terminal order they
        hold (any fulfillment other than `CLOSED` or `CANCELLED`, including
        `REPORT_RECEIVED`) is cancelled with the same compensation." and
        "requiring the candidate to be `ACTIVE`, else
        `ERR_CANDIDATE_NOT_ACTIVE`"."

        Design: Corner/state_machines/candidate_withdraw_cascades_to_all_orders
        """
        ctx = setup_screening_config(tag="SM11", with_matrix=False)
        position2 = get_success_data(
            api.create_position(
                {
                    "title": "T2",
                    "department": "D",
                    "risk_tier": "TIER_1_STANDARD",
                    "package_id": ctx["package"]["id"],
                    "jurisdiction_code": "US-CA",
                    "annual_salary_cents": 9000000,
                },
                HR,
            )
        )
        candidate = get_success_data(
            api.create_candidate(
                create_candidate_payload(full_name="Sm Eleven", email="sm11@x.com"),
                HR,
            )
        )
        order1 = get_success_data(
            api.create_order(
                create_order_payload(candidate["id"], ctx["position"]["id"]), HM
            )
        )
        order2 = get_success_data(
            api.create_order(
                create_order_payload(candidate["id"], position2["id"]), HM
            )
        )

        cand_headers = make_candidate_headers(candidate["id"])
        withdrawn = validate_success(api.withdraw_candidate(candidate["id"], cand_headers))
        assert withdrawn["status"] == "WITHDRAWN"

        for order in (order1, order2):
            now = get_success_data(api.get_order(order["id"], HR))
            assert now["fulfillment_status"] == "CANCELLED"
            assert now["adjudication_status"] == "VOIDED"

        # A second withdrawal fails: the candidate is no longer ACTIVE.
        resp = api.withdraw_candidate(candidate["id"], cand_headers)
        validate_error(resp, ApiErrorId.ERR_CANDIDATE_NOT_ACTIVE)


class TestConsentRevokeCascade:
    def _setup(self, api, tag):
        """IA-required jurisdiction; order REPORT_RECEIVED (ADVERSE_ELIGIBLE);
        DECIDED PROCEED_ADVERSE IA; INITIATE_ADVERSE creates the case."""
        return setup_pre_adverse_case(
            tag=tag,
            adjudicator_id="adj-tc2",
            jurisdiction_overrides={"individualized_assessment_required": True},
            findings=ADVERSE_FINDINGS,
            ia_first=True,
            ia_overrides={
                "green_factor_nature_gravity": "HIGH",
                "green_factor_time_elapsed": "LOW",
                "green_factor_job_relatedness": "HIGH",
                "evidence_considered": True,
                "decision": "PROCEED_ADVERSE",
            },
            consent_signed_at="2026-08-03T09:00:00Z",
            dispatch_at="2026-08-03T09:00:00Z",
            deliver_at="2026-08-04T10:00:00Z",
            initiate_at="2026-08-05T10:00:00Z",
        )

    def test_consent_revoke_cancels_order(self, api):
        """PRD section "Cancellation, Revocation, and Withdrawal Cascades":
        "When a candidate revokes their consent — moving the consent record from
        `CAPTURED` to `REVOKED` — the parent order is cancelled with the full
        chain: capacity released if dispatched, provisional fee voided, case
        aborted, assessment voided, adjudication `VOIDED`."

        Design: Difficulty/transitive_cascade/consent_revoke_cancel_case_ia_chain
        """
        ctx = self._setup(api, "TC2")
        revoked = validate_success(
            api.revoke_consent(
                ctx["consent"]["id"],
                make_candidate_headers(ctx["candidate"]["id"]),
            )
        )
        assert revoked["status"] == "REVOKED"

        order = get_success_data(api.get_order(ctx["order"]["id"], HR))
        assert order["fulfillment_status"] == "CANCELLED"
        assert order["adjudication_status"] == "VOIDED"

    def test_consent_revoke_aborts_case_and_voids_assessment(self, api):
        """PRD section "Parallel State Dimensions and Hierarchical Cascades":
        "cancelling an order aborts any non-terminal adverse-action case, voids
        any decided individualized assessment, and — when the order was
        `DISPATCHED` — decrements the vendor's `active_order_count` and voids
        the provisional fee."

        Design: Difficulty/transitive_cascade/consent_revoke_cancel_case_ia_chain
        """
        ctx = self._setup(api, "TC2B")
        validate_success(
            api.revoke_consent(
                ctx["consent"]["id"],
                make_candidate_headers(ctx["candidate"]["id"]),
            )
        )
        case = get_success_data(api.get_case(ctx["case"]["id"], HR))
        assert case["status"] == "ABORTED"

        assessments = list_order_assessments(ctx["order"]["id"], HR)
        assert len(assessments) == 1
        assert assessments[0]["status"] == "VOID"


class TestConsentExpiryAndReconsent:
    def test_dispatch_at_exactly_ninety_days_succeeds(self, api):
        """PRD section "Dispatch, the SLA Clock, and Vendor Capacity": "for an
        `INITIAL` order, the order's latest consent record must be `CAPTURED`
        with the current logical time no later than ninety days after
        `authorization_signed_at`."

        Design: Corner/calculations/consent_expiry_boundary_and_reconsent_cycle
        """
        # Signed 2026-06-01T00:00:00Z; exactly +90 days is 2026-08-30T00:00:00Z.
        ctx = setup_screening_config(tag="CC8", with_matrix=False)
        candidate = get_success_data(
            api.create_candidate(
                create_candidate_payload(full_name="Cc EightA", email="cc8a@x.com"),
                HR,
            )
        )
        get_success_data(api.set_clock("2026-06-01T00:00:00Z"))
        order = get_success_data(
            api.create_order(
                create_order_payload(candidate["id"], ctx["position"]["id"]), HM
            )
        )
        get_success_data(
            api.capture_consent(
                order["id"],
                create_consent_payload(
                    authorization_signed_at="2026-06-01T00:00:00Z"
                ),
                make_candidate_headers(candidate["id"]),
            )
        )
        get_success_data(api.set_clock("2026-08-30T00:00:00Z"))
        dispatched = validate_success(
            api.dispatch_order(order["id"], ctx["vendor"]["id"], HM)
        )
        assert dispatched["fulfillment_status"] == "DISPATCHED"

    def test_expired_consent_blocks_dispatch_then_reconsent_recovers(self, api):
        """PRD section "Dispatch, the SLA Clock, and Vendor Capacity": "A stale
        consent flips to `EXPIRED` as a side effect of the check itself, and the
        dispatch is rejected with `ERR_CONSENT_EXPIRED`; the order remains
        `CONSENT_CAPTURED` and may capture a fresh consent." and PRD section
        "Consent Capture": "Capture requires the order's fulfillment to be
        `DRAFT`, or — one recovery path — `CONSENT_CAPTURED` whose latest
        consent has already flipped to `EXPIRED`"."

        Design: Corner/calculations/consent_expiry_boundary_and_reconsent_cycle
        """
        ctx = setup_screening_config(tag="CC8B", with_matrix=False)
        candidate = get_success_data(
            api.create_candidate(
                create_candidate_payload(full_name="Cc EightB", email="cc8b@x.com"),
                HR,
            )
        )
        cand_headers = make_candidate_headers(candidate["id"])
        get_success_data(api.set_clock("2026-06-01T00:00:00Z"))
        order = get_success_data(
            api.create_order(
                create_order_payload(candidate["id"], ctx["position"]["id"]), HM
            )
        )
        stale = get_success_data(
            api.capture_consent(
                order["id"],
                create_consent_payload(
                    authorization_signed_at="2026-06-01T00:00:00Z"
                ),
                cand_headers,
            )
        )

        # One second past signed_at + 90 days: the stale consent flips EXPIRED.
        get_success_data(api.set_clock("2026-08-30T00:00:01Z"))
        resp = api.dispatch_order(order["id"], ctx["vendor"]["id"], HM)
        validate_error(resp, ApiErrorId.ERR_CONSENT_EXPIRED)
        consents = list_order_consents(order["id"], HR)
        assert len(consents) == 1
        assert consents[0]["id"] == stale["id"]
        assert consents[0]["status"] == "EXPIRED"
        order_now = get_success_data(api.get_order(order["id"], HR))
        assert order_now["fulfillment_status"] == "CONSENT_CAPTURED"

        # The recovery path: a fresh consent is accepted on the same order.
        fresh = validate_success(
            api.capture_consent(
                order["id"],
                create_consent_payload(
                    disclosure_form_id="DISC-2",
                    authorization_signed_at="2026-08-29T00:00:00Z",
                ),
                cand_headers,
            ),
            expected_status=201,
        )
        assert fresh["status"] == "CAPTURED"

        dispatched = validate_success(
            api.dispatch_order(order["id"], ctx["vendor"]["id"], HM)
        )
        assert dispatched["fulfillment_status"] == "DISPATCHED"

        consents = list_order_consents(order["id"], HR)
        assert len(consents) == 2
        captured = [c for c in consents if c["status"] == "CAPTURED"]
        assert len(captured) == 1
        assert captured[0]["id"] == fresh["id"]
