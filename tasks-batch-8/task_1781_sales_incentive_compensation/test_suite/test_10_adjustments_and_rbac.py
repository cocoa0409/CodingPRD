"""Manual adjustments: amount sanity, segregation of duties on approval,
terminal-state lockdown; plus cross-endpoint role denials."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_adjustment,
    close_period_payload,
    create_manual_adjustment,
    create_program,
    create_rep,
    get_success_data,
    make_comp_manager_headers,
    make_rep_headers,
    setup_accepted_assignment,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["comp_admin_headers"]
ANALYST = TEST_USERS["comp_analyst_headers"]
MANAGER = TEST_USERS["comp_manager_headers"]


class TestAdjustmentGuards:
    def test_adjustment_zero_amount_rejected(self, api):
        """PRD §3.5: "A `CompAnalyst` drafts one with the target
        `assignment_id`, a signed `amount_cents` — positive for a top-up,
        negative for a clawback-style reduction, but never zero
        (`ERR_ADJUSTMENT_AMOUNT_INVALID`) — and a free-text `reason`."

        Design: Corner/validations/adjustment_zero_amount_returns_400
        """
        sc = setup_accepted_assignment(program_name="Prog AZ",
                                       plan_name="Plan AZ", rep_name="Rep AZ",
                                       employee_ref="AZ-R1", accept=False)
        resp = api.create_adjustment(
            {"assignment_id": sc["assignment"]["id"], "amount_cents": 0,
             "reason": "noop"},
            ANALYST)
        validate_error(resp, ApiErrorId.ERR_ADJUSTMENT_AMOUNT_INVALID, 400)

    def test_adjustment_approval_by_creator_forbidden(self, api):
        """PRD §2.8: "The same wall stands between a manual adjustment and its
        adjudication: the `CompAnalyst` who drafted an `Adjustment` may not
        approve it, and an approval attempted by the drafting operator is
        rejected with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/roles/adjustment_approve_by_creator_forbidden
        """
        sc = setup_accepted_assignment(program_name="Prog SA",
                                       plan_name="Plan SA", rep_name="Rep SA",
                                       employee_ref="SA-R1", accept=False)
        # Drafted by analyst operator "ops-1".
        adjustment = create_manual_adjustment(sc["assignment"]["id"], 7000,
                                              "fix", analyst_user_id="ops-1")
        assert_adjustment(adjustment)
        assert adjustment["status"] == "PENDING_APPROVAL"
        assert adjustment["created_by_user_id"] == "ops-1"

        # A CompManager carrying the SAME X-User-ID as the drafter.
        same_user = api.approve_adjustment(
            adjustment["id"], make_comp_manager_headers("ops-1"))
        validate_error(same_user, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)
        after = get_success_data(api.get_adjustment(adjustment["id"], ADMIN))
        assert after["status"] == "PENDING_APPROVAL"

        # A different manager approves.
        ok = api.approve_adjustment(adjustment["id"],
                                    make_comp_manager_headers("mgr-1"))
        assert validate_success(ok, 200)["status"] == "APPROVED"

    def test_approve_rejected_adjustment_rejected(self, api):
        """PRD §3.5: "Adjudication belongs to a `CompManager`, and only ever
        moves `PENDING_APPROVAL` adjustments — acting on an adjustment in any
        other state is an invalid transition."

        Design: Corner/state_machines/adjustment_approve_after_reject_rejected
        """
        sc = setup_accepted_assignment(program_name="Prog AR",
                                       plan_name="Plan AR", rep_name="Rep AR",
                                       employee_ref="AR-R1", accept=False)
        adjustment = create_manual_adjustment(sc["assignment"]["id"], 5000,
                                              "correction")
        validate_success(api.reject_adjustment(adjustment["id"], MANAGER), 200)

        resp = api.approve_adjustment(adjustment["id"], MANAGER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)
        after = get_success_data(api.get_adjustment(adjustment["id"], ADMIN))
        assert after["status"] == "REJECTED"


class TestRoleDenials:
    def test_rep_cannot_close_period(self, api):
        """PRD §2.1: "Furthermore, access to specific operations is restricted
        by role; an attempt to perform an action outside of the caller's
        designated role will be rejected with an `ERR_FORBIDDEN_FOR_ROLE`
        error."
        PRD §3.7: "Period close is the system's ops-run checkpoint, executed by
        a `CompAdmin` against a program."

        Design: Corner/roles/rep_cannot_close_period
        """
        program = create_program("Prog RC")
        rep = create_rep(program["id"], "Rep RC", "RC-R1")
        resp = api.close_period(
            program["id"], close_period_payload(program["version"]),
            make_rep_headers(rep["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, 403)
        assert (get_success_data(api.get_program(program["id"], ADMIN))
                ["current_period_index"] == 1)

    def test_manager_cannot_create_transaction(self, api):
        """PRD §2.1: "Furthermore, access to specific operations is restricted
        by role; an attempt to perform an action outside of the caller's
        designated role will be rejected with an `ERR_FORBIDDEN_FOR_ROLE`
        error."
        PRD §3.4: "A `CompAnalyst` books a sale by submitting the
        `program_id`, an `external_ref`, the total `amount_cents` to be
        credited, the business `transaction_date`, and a `splits` array pairing
        each credited `rep_id` with a `split_bps` share."

        Design: Corner/roles/manager_cannot_create_transaction
        """
        sc = setup_accepted_assignment(program_name="Prog MC",
                                       plan_name="Plan MC", rep_name="Rep MC",
                                       employee_ref="MC-R1", accept=False)
        resp = api.create_transaction(
            {"program_id": sc["program"]["id"], "external_ref": "MC-T1",
             "amount_cents": 200000, "transaction_date": "2026-02-01",
             "splits": [{"rep_id": sc["rep"]["id"], "split_bps": 10000}]},
            MANAGER)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, 403)
