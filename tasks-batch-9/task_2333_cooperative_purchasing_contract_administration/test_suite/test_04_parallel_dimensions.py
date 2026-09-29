"""Bounded cycles and two dimensions on one row that advance independently."""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import (
    ADMIN_REVIEW,
    ADMIN_REVIEW_ID,
    ApiErrorId,
    assert_cents,
    assert_instant,
    assert_score,
    make_supplier_headers,
)
from test_helpers.constants import CLOCK_OCT_01, CLOCK_REGISTRY
from test_helpers.factories import TX_RULE
from test_helpers.fixtures import (
    accept_report,
    create_member,
    open_report,
    read_contract,
    read_report,
    reconcile_report,
    remit_fee,
    seed_state_law_rules,
    set_clock,
    setup_confirmed_usage_world,
)


def _registration(api, member_id, payload):
    return api.member_registration(member_id, payload, ADMIN_REVIEW)


def _run_docs_rounds(api, member_id, rounds):
    counts = []
    for index in range(rounds):
        get_success_data(
            _registration(api, member_id, {"action": "REQUEST_DOCS", "note": f"round {index + 1}"})
        )
        row = get_success_data(
            _registration(
                api,
                member_id,
                {
                    "action": "RESUBMIT_DOCS",
                    "governing_body_resolution_number": f"RES-SV-2026-001-{index}",
                },
            )
        )
        counts.append(row["docs_request_count"])
    return counts


def _sandia(api):
    """A Texas special district registered while the clock sits on the registry instant."""
    seed_state_law_rules(api, rules=(TX_RULE,))
    set_clock(api, CLOCK_REGISTRY)
    return create_member(
        api,
        legal_name="Sandia Valley Water District",
        state_code="TX",
        member_category="SPECIAL_DISTRICT",
        governing_body_resolution_number="RES-SV-2026-001",
    )


def _reportable_world(api):
    """One confirmed September order and an open report over that closed period."""
    world = setup_confirmed_usage_world(api, order_count=1)
    world["report"] = open_report(api, world)
    set_clock(api, CLOCK_OCT_01)
    return world


def _submit(api, world):
    return api.report_submission(
        world["report"]["id"],
        {"action": "SUBMIT"},
        make_supplier_headers(world["contract"]["supplier_id"]),
    )


class TestDocumentChaseCycle:
    def test_01_the_counter_advances_on_the_resubmission_leg(self, api):
        """PRD §3.4: "`RESUBMIT_DOCS` closes the cycle `DOCS_REQUESTED →
        PENDING_VERIFICATION`, increments `docs_request_count` by 1, and stores whichever
        of the two evidence numbers the request supplied — so the document-chase loop can
        run at most three times."

        Design: Difficulty/non_linear_state_machine/member_docs_request_cycle_exhausts_at_three_rounds_yet_verify_remains_open
        """
        member = _sandia(api)
        assert member["registration_status"] == "PENDING_VERIFICATION"
        assert member["docs_request_count"] == 0

        counts = _run_docs_rounds(api, member["id"], 2)

        assert counts == [1, 2]

    def test_02_the_third_round_leaves_the_member_awaiting_verification(self, api):
        """PRD §3.4: "The registration dimension takes the values
        `PENDING_VERIFICATION`, `DOCS_REQUESTED`, `ACTIVE`, `SUSPENDED` and the terminal
        `TERMINATED`, and it cycles twice over: `PENDING_VERIFICATION → DOCS_REQUESTED →
        PENDING_VERIFICATION`, and `ACTIVE → SUSPENDED → ACTIVE`."

        Design: Difficulty/non_linear_state_machine/member_docs_request_cycle_exhausts_at_three_rounds_yet_verify_remains_open
        """
        member = _sandia(api)

        _run_docs_rounds(api, member["id"], 3)

        row = validate_success(api.get_member_agency(member["id"], ADMIN_REVIEW))
        assert row["registration_status"] == "PENDING_VERIFICATION"
        assert row["docs_request_count"] == 3

    def test_03_a_fourth_request_is_refused_and_moves_nothing(self, api):
        """PRD §3.4: "`REQUEST_DOCS` moves `PENDING_VERIFICATION → DOCS_REQUESTED` and
        requires `docs_request_count` to be strictly below three; a fourth request is
        `ERR_DOCS_REQUEST_ROUNDS_EXHAUSTED`."

        Design: Difficulty/non_linear_state_machine/member_docs_request_cycle_exhausts_at_three_rounds_yet_verify_remains_open
        """
        member = _sandia(api)
        _run_docs_rounds(api, member["id"], 3)

        response = _registration(
            api, member["id"], {"action": "REQUEST_DOCS", "note": "round 4 must be refused"}
        )

        validate_error(response, ApiErrorId.ERR_DOCS_REQUEST_ROUNDS_EXHAUSTED, 409)
        row = validate_success(api.get_member_agency(member["id"], ADMIN_REVIEW))
        assert row["registration_status"] == "PENDING_VERIFICATION"
        assert row["docs_request_count"] == 3

    def test_04_exhausting_the_cycle_does_not_close_the_door_on_verification(self, api):
        """PRD §3.4: "On success `verified_at` is stamped with the current logical instant
        and `verified_by_user_id` with the acting `X-User-ID`."

        Design: Difficulty/non_linear_state_machine/member_docs_request_cycle_exhausts_at_three_rounds_yet_verify_remains_open
        """
        member = _sandia(api)
        _run_docs_rounds(api, member["id"], 3)
        validate_error(
            _registration(api, member["id"], {"action": "REQUEST_DOCS"}),
            ApiErrorId.ERR_DOCS_REQUEST_ROUNDS_EXHAUSTED,
            409,
        )

        verified = validate_success(_registration(api, member["id"], {"action": "VERIFY"}))

        assert verified["registration_status"] == "ACTIVE"
        assert_instant(verified["verified_at"], "2026-06-01T00:00:00Z", "verified_at")
        assert verified["verified_by_user_id"] == ADMIN_REVIEW_ID


class TestReportAndFeeDimensions:
    def test_05_the_fee_dimension_stays_not_due_while_the_report_is_only_submitted(self, api):
        """PRD §3.7: "A remittance against a `NOT_DUE` or `PAID` report, or an acceptance
        of a report whose `fee_status` is not `NOT_DUE`, is `ERR_FEE_STATUS_INVALID`."

        Design: Difficulty/non_linear_state_machine/usage_report_status_and_fee_status_dimensions_advance_independently
        """
        world = _reportable_world(api)

        report = validate_success(_submit(api, world))
        assert report["status"] == "SUBMITTED"
        assert report["fee_status"] == "NOT_DUE"
        assert_cents(report["reported_fee_cents"], 180, "reported_fee_cents")

        premature = api.report_fee_remittance(
            world["report"]["id"],
            {"action": "REMIT", "amount_cents": 180},
            make_supplier_headers(world["contract"]["supplier_id"]),
        )
        validate_error(premature, ApiErrorId.ERR_FEE_STATUS_INVALID, 409)

    def test_06_a_rejection_folds_the_acceptance_dimension_back_without_touching_the_fee(self, api):
        """PRD §3.7: "`REJECT` moves `SUBMITTED → REJECTED`, clears `usage_report_id` on
        every order this report had swept, zeroes `swept_usage_count`,
        `reported_chargeable_cents`, `reported_usage_cents` and `reported_fee_cents`, and
        stores the `rejection_reason`."

        Design: Difficulty/non_linear_state_machine/usage_report_status_and_fee_status_dimensions_advance_independently
        """
        world = _reportable_world(api)
        validate_success(_submit(api, world))

        rejected = validate_success(
            api.report_review(
                world["report"]["id"],
                {"action": "REJECT", "rejection_reason": "period totals require re-attestation"},
                ADMIN_REVIEW,
            )
        )

        assert rejected["status"] == "REJECTED"
        assert rejected["fee_status"] == "NOT_DUE"
        assert rejected["swept_usage_count"] == 0
        assert_cents(rejected["reported_fee_cents"], 0, "reported_fee_cents")

    def test_07_resubmission_re_sweeps_the_period_and_the_fee_stays_not_due(self, api):
        """PRD §3.7: "The acceptance dimension runs `DRAFT`, `SUBMITTED`, `ACCEPTED` and
        the terminal `RECONCILED`, with `REJECTED` folding back to `SUBMITTED` so a
        rejected report can be fixed and resubmitted."

        Design: Difficulty/non_linear_state_machine/usage_report_status_and_fee_status_dimensions_advance_independently
        """
        world = _reportable_world(api)
        validate_success(_submit(api, world))
        validate_success(
            api.report_review(
                world["report"]["id"],
                {"action": "REJECT", "rejection_reason": "period totals require re-attestation"},
                ADMIN_REVIEW,
            )
        )

        resubmitted = validate_success(_submit(api, world))

        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["fee_status"] == "NOT_DUE"
        assert resubmitted["swept_usage_count"] == 1
        assert_cents(resubmitted["reported_fee_cents"], 180, "reported_fee_cents")

    def test_08_acceptance_of_the_one_dimension_drives_the_other_to_due(self, api):
        """PRD §3.7: "`ACCEPT` moves `SUBMITTED → ACCEPTED`, stamps `accepted_at` with the
        current logical instant, sets `fee_due_at` to thirty days after `accepted_at`,
        moves the parallel `fee_status` from `NOT_DUE` to `DUE`, and adds
        `reported_fee_cents` to both the contract's and the supplier's
        `fee_assessed_cents_total` before recomputing the contract's
        `fee_outstanding_cents`."

        Design: Difficulty/non_linear_state_machine/usage_report_status_and_fee_status_dimensions_advance_independently
        """
        world = _reportable_world(api)
        validate_success(_submit(api, world))

        accepted = accept_report(api, world["report"]["id"])

        assert accepted["status"] == "ACCEPTED"
        assert accepted["fee_status"] == "DUE"
        assert_instant(accepted["fee_due_at"], "2026-10-31T00:00:00Z", "fee_due_at")

    def test_09_the_fee_dimension_reaches_its_terminal_value_first(self, api):
        """PRD §3.7: "A successful remittance adds `amount_cents` to the report's
        `remitted_cents`, to the contract's `fee_remitted_cents_total` and to the
        supplier's `fee_remitted_cents_total`, then recomputes the contract's
        `fee_outstanding_cents`."

        Design: Difficulty/non_linear_state_machine/usage_report_status_and_fee_status_dimensions_advance_independently
        """
        world = _reportable_world(api)
        validate_success(_submit(api, world))
        accept_report(api, world["report"]["id"])

        remitted = remit_fee(api, world, world["report"]["id"], 180)

        assert remitted["fee_status"] == "PAID"
        assert_cents(remitted["remitted_cents"], 180, "remitted_cents")
        assert remitted["status"] == "ACCEPTED"
        contract = read_contract(api, world["contract"]["id"])
        assert_cents(contract["fee_remitted_cents_total"], 180, "fee_remitted_cents_total")
        assert_cents(contract["fee_outstanding_cents"], 0, "fee_outstanding_cents")

    def test_10_reconciliation_advances_only_the_acceptance_dimension(self, api):
        """PRD §3.7: "The remittance dimension advances `NOT_DUE`, `DUE`, `PAID`, with
        `DUE → DELINQUENT` when the sweep finds an overdue report and `DELINQUENT → PAID`
        when it is finally settled; `PAID` is terminal."

        Design: Difficulty/non_linear_state_machine/usage_report_status_and_fee_status_dimensions_advance_independently
        """
        world = _reportable_world(api)
        validate_success(_submit(api, world))
        accept_report(api, world["report"]["id"])
        remit_fee(api, world, world["report"]["id"], 180)

        reconciled = reconcile_report(api, world["report"]["id"])

        assert reconciled["status"] == "RECONCILED"
        assert reconciled["fee_status"] == "PAID"
        assert_cents(reconciled["audited_fee_cents"], 180, "audited_fee_cents")
        assert_cents(reconciled["fee_true_up_cents"], 0, "fee_true_up_cents")
        assert_score(reconciled["variance_pct"], 0.00, "variance_pct")
        assert read_report(api, world["report"]["id"])["variance_flagged"] is False
