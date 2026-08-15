"""Remittance lifecycle, the zero-variance confirm gate, escheatment, and the
REUNITED terminal state (PRD §3.6, §3.7)."""
from test_helpers import (
    TEST_USERS,
    api_client,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
    ApiErrorId,
)
from test_helpers.fixtures import (
    CO,
    READER,
    SA,
    TO,
    create_remittance,
    confirm_remittance,
    get_property,
    get_report,
    record_contact,
    setup_accepted_single_line_report,
    setup_remitted_cash_property,
    setup_under_review_claim,
)

CO_H = TEST_USERS["compliance_officer_headers"]
SA_H = TEST_USERS["state_auditor_headers"]
TO_H = TEST_USERS["treasury_ops_headers"]
AP_H = TEST_USERS["claims_approver_headers"]


class TestRemittanceCreation:
    def test_second_pending_remittance_rejected(self, api):
        """PRD §3.6: "Only one `PENDING` remittance may exist per report; a
        second attempt is refused with `ERR_REMITTANCE_ALREADY_PENDING`."

        Design: Corner/errors/remittance_already_pending_rejected
        """
        chain = setup_accepted_single_line_report(value=100000)
        create_remittance(chain["report"]["id"], 100000)
        resp = api.create_remittance(
            chain["report"]["id"], {"amount_cents": 100000}, TO_H
        )
        validate_error(resp, ApiErrorId.ERR_REMITTANCE_ALREADY_PENDING, 409)

    def test_requeue_from_pending_rejected(self, api):
        """PRD §3.6: "A `TreasuryOps` operator may then requeue a `FAILED`
        remittance — any other origin is `ERR_REMITTANCE_NOT_FAILED` —
        supplying a corrected `amount_cents`"

        Design: Corner/state_machines/remittance_requeue_from_pending_rejected
        """
        chain = setup_accepted_single_line_report(value=100000)
        remittance = create_remittance(chain["report"]["id"], 100000)
        resp = api.requeue_remittance(
            remittance["id"], {"amount_cents": 100000}, TO_H
        )
        validate_error(resp, ApiErrorId.ERR_REMITTANCE_NOT_FAILED, 409)
        still = get_success_data(api.get_remittance(remittance["id"], READER), 200)
        assert still["status"] == "PENDING"


class TestVarianceBoundary:
    def test_variance_plus_one_rejected(self, api):
        """PRD §3.6: "the `variance_cents` — the `amount_cents` minus the
        report's `total_final_cents`, evaluated at confirm time — is exactly
        zero (else `ERR_REMITTANCE_VARIANCE_NONZERO`)."

        Design: Difficulty/boundary_precision_check/remittance_variance_exactly_zero_boundary
        """
        chain = setup_accepted_single_line_report(value=100000)
        remittance = create_remittance(chain["report"]["id"], 100001)
        resp = api.confirm_remittance(remittance["id"], SA_H)
        validate_error(resp, ApiErrorId.ERR_REMITTANCE_VARIANCE_NONZERO, 422)

    def test_variance_exactly_zero_confirms(self, api):
        """PRD §3.6: "On confirmation the `confirmed_date` is stamped with the
        clock date, the report's `confirmed_remittance_cents` increases by the
        confirmed `amount_cents` with its `version` incrementing, and every
        property with an `INCLUDED` or `FINAL` line in the report advances
        `REPORTED → REMITTED`."

        Design: Difficulty/boundary_precision_check/remittance_variance_exactly_zero_boundary
        """
        chain = setup_accepted_single_line_report(value=100000)
        remittance = create_remittance(chain["report"]["id"], 100001)
        validate_error(
            api.confirm_remittance(remittance["id"], SA_H),
            ApiErrorId.ERR_REMITTANCE_VARIANCE_NONZERO,
            422,
        )
        get_success_data(
            api.fail_remittance(
                remittance["id"], {"failure_reason": "overpayment"}, SA_H
            ),
            200,
        )
        get_success_data(
            api.requeue_remittance(remittance["id"], {"amount_cents": 100000}, TO_H),
            200,
        )
        confirmed = get_success_data(
            api.confirm_remittance(remittance["id"], SA_H), 200
        )
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["variance_cents"] == 0


class TestConfirmFailedRemittancePriority:
    def _failed_mismatched_remittance(self):
        chain = setup_accepted_single_line_report(value=100000)
        remittance = create_remittance(chain["report"]["id"], 99999)
        get_success_data(
            api_client.fail_remittance(
                remittance["id"],
                {"failure_reason": "state clearinghouse reject"},
                SA_H,
            ),
            200,
        )
        return chain, remittance

    def test_state_error_masks_fiscal_variance(self, api):
        """PRD §3.6: "A `StateAuditor` confirms a remittance that is `PENDING`
        (else `ERR_REMITTANCE_NOT_PENDING`)"
        PRD §2.10: "Every request is validated in a fixed sequence of layers,
        and a failure in an earlier layer masks all later checks — the caller
        always receives the earliest applicable error."

        Design: Difficulty/priority_pair_validation_conflict/confirm_failed_remittance_state_beats_fiscal_variance
        """
        chain, remittance = self._failed_mismatched_remittance()
        # FAILED state (eighth layer) beats the variance check (twelfth layer),
        # even though the amount 99999 also mismatches the 100000 total.
        resp = api.confirm_remittance(remittance["id"], SA_H)
        validate_error(resp, ApiErrorId.ERR_REMITTANCE_NOT_PENDING, 409)

    def test_rejected_confirm_leaves_no_side_effects(self, api):
        """PRD §3.6: "On confirmation the `confirmed_date` is stamped with the
        clock date, the report's `confirmed_remittance_cents` increases by the
        confirmed `amount_cents` with its `version` incrementing"

        Design: Difficulty/priority_pair_validation_conflict/confirm_failed_remittance_state_beats_fiscal_variance
        """
        chain, remittance = self._failed_mismatched_remittance()
        validate_error(
            api.confirm_remittance(remittance["id"], SA_H),
            ApiErrorId.ERR_REMITTANCE_NOT_PENDING,
            409,
        )
        still = get_success_data(api.get_remittance(remittance["id"], READER), 200)
        assert still["status"] == "FAILED"
        assert get_report(chain["report"]["id"])["confirmed_remittance_cents"] == 0


class TestFailRequeueCompensation:
    def test_requeue_restores_pending_and_clears_failure(self, api):
        """PRD §3.6: "the requeue replaces the amount, clears the
        `failure_reason` to null, returns the remittance to `PENDING`, and
        leaves the `variance_cents` to be recomputed lazily at the next
        confirmation."

        Design: Difficulty/compensating_invariant/remittance_fail_requeue_conserves_confirmed_total
        """
        chain = setup_accepted_single_line_report(value=100000)
        remittance = create_remittance(chain["report"]["id"], 100000)
        get_success_data(
            api.fail_remittance(
                remittance["id"], {"failure_reason": "ACH return"}, SA_H
            ),
            200,
        )
        requeued = get_success_data(
            api.requeue_remittance(remittance["id"], {"amount_cents": 100000}, TO_H),
            200,
        )
        assert requeued["status"] == "PENDING"
        assert requeued["failure_reason"] is None
        assert requeued["amount_cents"] == 100000

    def test_fail_requeue_conserves_fulfillment_progress(self, api):
        """PRD §3.6: "On confirmation the `confirmed_date` is stamped with the
        clock date, the report's `confirmed_remittance_cents` increases by the
        confirmed `amount_cents` with its `version` incrementing, and every
        property with an `INCLUDED` or `FINAL` line in the report advances
        `REPORTED → REMITTED`."

        Design: Difficulty/compensating_invariant/remittance_fail_requeue_conserves_confirmed_total
        """
        chain = setup_accepted_single_line_report(value=100000)
        remittance = create_remittance(chain["report"]["id"], 100000)
        get_success_data(
            api.fail_remittance(
                remittance["id"], {"failure_reason": "ACH return"}, SA_H
            ),
            200,
        )
        get_success_data(
            api.requeue_remittance(remittance["id"], {"amount_cents": 100000}, TO_H),
            200,
        )
        # Nothing was ever confirmed, so progress counters stay at zero.
        assert get_report(chain["report"]["id"])["confirmed_remittance_cents"] == 0
        assert get_property(chain["property"]["id"])["status"] == "REPORTED"
        remittances, meta = validate_paginated(
            api.list_remittances(chain["report"]["id"], READER)
        )
        assert meta["total_count"] == 1


class TestCustodyAndTerminalState:
    def test_escheat_once_then_rejected(self, api):
        """PRD §3.6: "Once a property stands `REMITTED`, a `StateAuditor`
        escheats it — the formal taking of custody — moving it `REMITTED →
        ESCHEATED` and stamping `escheated_date` with the clock date; a
        property in any other state is refused with
        `ERR_PROPERTY_NOT_REMITTED`."

        Design: Corner/state_machines/escheat_valid_then_invalid
        """
        chain = setup_remitted_cash_property(original_value_cents=100000)
        resp = api.escheat_property(chain["property"]["id"], SA_H)
        escheated = validate_success(resp, 200)
        assert escheated["status"] == "ESCHEATED"
        assert escheated["escheated_date"] == "2026-09-01"
        again = api.escheat_property(chain["property"]["id"], SA_H)
        validate_error(again, ApiErrorId.ERR_PROPERTY_NOT_REMITTED, 409)
        assert get_property(chain["property"]["id"])["status"] == "ESCHEATED"

    def test_reunited_is_terminal(self, api):
        """PRD §3.1: "From there its `status` walks the statutory pipeline —
        `ACTIVE`, `DORMANT`, `DUE_DILIGENCE`, `REPORTABLE`, `REPORTED`,
        `REMITTED`, `ESCHEATED` — and may leave it at the end for `REUNITED`,
        the terminal state, when a paid claim returns the property to its
        owner."
        PRD §3.3: "The property must be `DORMANT`, `DUE_DILIGENCE`, or
        `REPORTABLE`, else `ERR_PROPERTY_NOT_REACTIVATABLE`"

        Design: Corner/state_machines/property_terminal_reunited_lockdown
        """
        chain = setup_under_review_claim(original_value_cents=100000)
        claim = chain["claim"]
        get_success_data(api.approve_claim(claim["id"], AP_H), 200)
        get_success_data(api.pay_claim(claim["id"], TO_H), 200)
        reunited = get_property(chain["property"]["id"])
        assert reunited["status"] == "REUNITED"
        assert reunited["reunited_date"] == "2026-09-01"
        ev = record_contact(chain["property"]["id"], contact_type="WITHDRAWAL",
                            contact_date="2026-09-02", evidence_ref="wd-late")
        resp = api.reactivate_property(
            chain["property"]["id"],
            {"evidence_contact_event_id": ev["id"]},
            CO_H,
        )
        validate_error(resp, ApiErrorId.ERR_PROPERTY_NOT_REACTIVATABLE, 409)
        esc = api.escheat_property(chain["property"]["id"], SA_H)
        validate_error(esc, ApiErrorId.ERR_PROPERTY_NOT_REMITTED, 409)
        assert get_property(chain["property"]["id"])["status"] == "REUNITED"
