"""Underpayment case review, withdrawal, and write-off fences (PRD §3.7)."""
from test_helpers import (
    ApiErrorId,
    create_write_off_payload,
    get_case,
    make_finance_director_headers,
    make_recovery_manager_headers,
    pick_up_case,
    setup_case,
    setup_case_under_review,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import RM


class TestCaseTerminalStates:
    def test_withdrawn_case_rejects_pick_up(self, api):
        """PRD §3.7: "Either role may withdraw a case from `QUEUED` or
        `UNDER_REVIEW`, landing it in terminal `WITHDRAWN`." PRD §2.8 rung 6:
        "the target entity must be in a valid from-state for the requested
        transition, and terminal states reject every action".

        Design: Corner/state_machines/sm_withdrawn_case_rejects_pick_up
        """
        ctx = setup_case(paid_amount_cents=100000,
                         claim_overrides={"claim_number": "CL-WD1"})
        withdrawn = validate_success(
            api.withdraw_underpayment_case(
                ctx["case"]["id"], make_recovery_manager_headers("rm-1")
            )
        )
        assert withdrawn["status"] == "WITHDRAWN"
        resp = api.pick_up_underpayment_case(
            ctx["case"]["id"], make_recovery_manager_headers("rm-2")
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)
        case_after = get_case(ctx["case"]["id"])
        assert case_after["status"] == "WITHDRAWN"
        assert case_after["claimed_by_user_id"] is None


class TestWriteOffFences:
    def test_write_off_amount_mismatch_rejected(self, api):
        """PRD §3.7: "the supplied `amount_cents` must equal the case's full
        `current_outstanding_cents` — partial write-offs do not exist
        (`ERR_WRITE_OFF_AMOUNT_MISMATCH`)".

        Design: Corner/errors/err_write_off_amount_mismatch_rejected
        """
        ctx = setup_case_under_review(
            paid_amount_cents=150000, claim_overrides={"claim_number": "CL-WM1"}
        )
        case = ctx["case"]
        assert case["current_outstanding_cents"] == 50000
        resp = api.write_off_underpayment_case(
            case["id"],
            create_write_off_payload(amount_cents=40000, reason="partial goodwill"),
            make_finance_director_headers("fd-1"),
        )
        validate_error(resp, ApiErrorId.ERR_WRITE_OFF_AMOUNT_MISMATCH.value)
        case_after = get_case(case["id"])
        assert case_after["status"] == "UNDER_REVIEW"
        assert case_after["write_off_amount_cents"] == 0

    def test_write_off_cap_exceeded_rejected(self, api):
        """PRD §3.7: "the outstanding balance must not exceed the director cap
        of 250000 cents — twenty-five hundred dollars — else
        `ERR_WRITE_OFF_CAP_EXCEEDED`."

        Design: Corner/errors/err_write_off_cap_exceeded_rejected
        """
        ctx = setup_case_under_review(
            paid_amount_cents=0,
            rate_model="CASE_RATE",
            base_rate_cents=300000,
            claim_overrides={
                "claim_number": "CL-CX1",
                "admission_date": "2026-06-01",
                "discharge_date": "2026-06-02",
                "total_billed_charges_cents": 400000,
            },
            lines=[{"charge_cents": 400000}],
            remittance_overrides={"adjustment_reason_code": "DENIAL"},
        )
        case = ctx["case"]
        assert case["current_outstanding_cents"] == 300000
        resp = api.write_off_underpayment_case(
            case["id"],
            create_write_off_payload(amount_cents=300000, reason="uncollectible"),
            make_finance_director_headers("fd-1"),
        )
        validate_error(resp, ApiErrorId.ERR_WRITE_OFF_CAP_EXCEEDED.value)
        assert get_case(case["id"])["status"] == "UNDER_REVIEW"


class TestWriteOffStateBeatsCap:
    """Priority pair state (rung 6) vs money guard (rung 11), PRD §2.8."""

    def _setup_queued_300k(self, api, number):
        return setup_case(
            paid_amount_cents=0,
            rate_model="CASE_RATE",
            base_rate_cents=300000,
            claim_overrides={
                "claim_number": number,
                "admission_date": "2026-06-01",
                "discharge_date": "2026-06-02",
                "total_billed_charges_cents": 400000,
            },
            lines=[{"charge_cents": 400000}],
            remittance_overrides={"adjustment_reason_code": "DENIAL"},
        )

    def test_write_off_from_queued_reports_state_error_not_cap(self, api):
        """PRD §2.8: "Every request passes through a fixed ladder of checks,
        and the rungs are evaluated in the order below: when several checks
        could fail on the same request, the failure on the earliest rung is
        the one reported, and later rungs are never reached once a failure has
        fired." PRD §3.7: "Write-off belongs to the `FinanceDirector`, is
        available only from `UNDER_REVIEW`".

        Design: Difficulty/priority_pair_validation_conflict/write_off_from_queued_state_error_beats_cap_error
        """
        ctx = self._setup_queued_300k(api, "CL-PP1")
        case = ctx["case"]
        assert case["status"] == "QUEUED"
        assert case["current_outstanding_cents"] == 300000
        # Violates rung 6 (not UNDER_REVIEW) AND rung 11 (300000 > 250000 cap);
        # the earlier rung's error must be the one reported.
        resp = api.write_off_underpayment_case(
            case["id"],
            create_write_off_payload(amount_cents=300000, reason="uncollectible"),
            make_finance_director_headers("fd-1"),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)
        case_after = get_case(case["id"])
        assert case_after["status"] == "QUEUED"
        assert case_after["write_off_amount_cents"] == 0

    def test_write_off_from_queued_rejected_even_within_cap(self, api):
        """PRD §3.7: "Write-off belongs to the `FinanceDirector`, is available
        only from `UNDER_REVIEW`" — the state fence fires even when the amount
        is small enough that no money guard could fire.

        Design: Difficulty/priority_pair_validation_conflict/write_off_from_queued_state_error_beats_cap_error
        """
        ctx = setup_case(
            paid_amount_cents=150000, claim_overrides={"claim_number": "CL-PP1b"}
        )
        case = ctx["case"]
        assert case["status"] == "QUEUED"
        assert case["current_outstanding_cents"] == 50000
        resp = api.write_off_underpayment_case(
            case["id"],
            create_write_off_payload(amount_cents=50000, reason="uncollectible"),
            make_finance_director_headers("fd-1"),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)
        assert get_case(case["id"])["status"] == "QUEUED"


class TestWriteOffSoDBeatsCap:
    """Priority pair segregation-of-duties (rung 7) vs money guard (rung 11)."""

    def test_self_write_off_reports_sod_error_not_cap(self, api):
        """PRD §2.9: "Symmetrically, an underpayment case may not be written
        off by the analyst who claimed it: the write-off compares `X-User-ID`
        against the case's `claimed_by_user_id` and rejects a match with
        `ERR_SOD_WRITE_OFF_SELF`. Both rejections carry HTTP 409 and sit on
        rung 7 of the validation ladder — they fire before referential,
        temporal, and uniqueness checks on the same request."

        Design: Difficulty/priority_pair_validation_conflict/write_off_self_sod_error_beats_cap_error
        """
        ctx = self._setup_under_review_300k(api, "CL-PS1", claimer="op-shared")
        case = ctx["case"]
        assert case["current_outstanding_cents"] == 300000
        # Same X-User-ID as the claimer AND over the cap: rung 7 wins.
        resp = api.write_off_underpayment_case(
            case["id"],
            create_write_off_payload(amount_cents=300000, reason="uncollectible"),
            make_finance_director_headers("op-shared"),
        )
        validate_error(resp, ApiErrorId.ERR_SOD_WRITE_OFF_SELF.value)
        case_after = get_case(case["id"])
        assert case_after["status"] == "UNDER_REVIEW"
        assert case_after["current_outstanding_cents"] == 300000

    def test_self_write_off_rejected_even_within_cap(self, api):
        """PRD §2.9: "the write-off compares `X-User-ID` against the case's
        `claimed_by_user_id` and rejects a match with
        `ERR_SOD_WRITE_OFF_SELF`."

        Design: Difficulty/priority_pair_validation_conflict/write_off_self_sod_error_beats_cap_error
        """
        ctx = setup_case_under_review(
            claimer_user_id="op-shared",
            paid_amount_cents=150000,
            claim_overrides={"claim_number": "CL-PS2"},
        )
        case = ctx["case"]
        assert case["current_outstanding_cents"] == 50000
        resp = api.write_off_underpayment_case(
            case["id"],
            create_write_off_payload(amount_cents=50000, reason="uncollectible"),
            make_finance_director_headers("op-shared"),
        )
        validate_error(resp, ApiErrorId.ERR_SOD_WRITE_OFF_SELF.value)
        assert get_case(case["id"])["status"] == "UNDER_REVIEW"

    def _setup_under_review_300k(self, api, number, claimer):
        return setup_case_under_review(
            claimer_user_id=claimer,
            paid_amount_cents=0,
            rate_model="CASE_RATE",
            base_rate_cents=300000,
            claim_overrides={
                "claim_number": number,
                "admission_date": "2026-06-01",
                "discharge_date": "2026-06-02",
                "total_billed_charges_cents": 400000,
            },
            lines=[{"charge_cents": 400000}],
            remittance_overrides={"adjustment_reason_code": "DENIAL"},
        )
