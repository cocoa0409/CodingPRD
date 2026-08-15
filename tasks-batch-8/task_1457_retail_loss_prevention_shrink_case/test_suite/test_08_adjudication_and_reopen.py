"""Adjudication: role routing, segregation of duties, demand gate, loss
posting; closure, reopen window and reversal cascade."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    adjudicate_case,
    advance_case,
    assert_case,
    attach_evidence,
    document_interview,
    draft_demand,
    get_case,
    hold_interview,
    issue_demand,
    make_analyst_headers,
    make_employee,
    make_hr_partner_headers,
    make_manager_headers,
    make_period,
    make_store,
    record_and_post_payment,
    schedule_interview,
    set_clock,
    setup_case_adjudicating,
    setup_case_closed_substantiated,
    setup_case_interviewed,
    setup_case_investigating,
    validate_error,
    validate_success,
)
from test_helpers.constants import (
    ADMIN_1,
    ANALYST_1,
    ANALYST_2,
    HR_PARTNER_1,
    MANAGER_1,
)


class TestAdjudicationPipeline:
    def test_case_adjudicate_from_investigating_returns_invalid_state(self, api):
        """PRD §4: "| POST | `/cases/{case_id}/adjudicate` | Adjudicate an
        ADJUDICATING case (HRPartner for EMPLOYEE subjects, LPManager for
        EXTERNAL) | LPManager, HRPartner |"
        PRD §2.7: "6. The target entity's own state machine must permit the
        requested transition (`ERR_INVALID_STATE_TRANSITION`, or
        `ERR_DEMAND_NOT_PAYABLE` for a payment posting against a demand that is
        not payable)."

        Design: Corner/state_machines/case_adjudicate_from_investigating_returns_invalid_state
        """
        store = make_store(store_number="S035", name="Store 35")
        ctx = setup_case_investigating(store["id"], manual_loss_cents=1000)
        resp = api.adjudicate_case(
            ctx["case"]["id"],
            {"decision": "SUBSTANTIATED", "restitution_waived": True},
            make_manager_headers(MANAGER_1),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_not_found_beats_state_on_adjudicate(self, api):
        """PRD §2.7: "Every request passes through a single ordered validation
        pipeline, and the first failing check produces the response — later
        checks are not evaluated."
        PRD §2.7: "5. Existence of every referenced resource (`ERR_NOT_FOUND`)."
        PRD §2.7: "6. The target entity's own state machine must permit the
        requested transition (`ERR_INVALID_STATE_TRANSITION`, or
        `ERR_DEMAND_NOT_PAYABLE` for a payment posting against a demand that is
        not payable)."

        A nonexistent case id fails existence (step 5) before any state check.

        Design: Corner/validations/not_found_beats_state_on_adjudicate
        """
        resp = api.adjudicate_case(
            NON_EXISTENT_UUID,
            {"decision": "SUBSTANTIATED", "restitution_waived": True},
            make_manager_headers(MANAGER_1),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_sod_case_creator_cannot_adjudicate(self, api):
        """PRD §2.9: "The operator adjudicating a case must not be the
        `interviewer_id` of any `DOCUMENTED` interview on that case
        (`ERR_SOD_INTERVIEWER_ADJUDICATOR`), and must not be the analyst
        recorded as the case's `created_by` (`ERR_SOD_CASE_CREATOR`)."

        Here the interviewer is ana-2, so the only wall the creator (ana-1,
        wearing the LPManager hat) hits is the creator wall; a different
        manager adjudicates fine.

        Design: Corner/validations/sod_case_creator_cannot_adjudicate
        """
        store = make_store(store_number="S061", name="Store 61")
        make_period(store["id"])
        ctx = setup_case_adjudicating(
            store["id"], manual_loss_cents=10000, creator_id=ANALYST_1,
            analyst_id=ANALYST_1, interviewer_id=ANALYST_2,
        )
        resp = api.adjudicate_case(
            ctx["case"]["id"],
            {"decision": "SUBSTANTIATED", "restitution_waived": True},
            make_manager_headers(ANALYST_1),
        )
        validate_error(resp, ApiErrorId.ERR_SOD_CASE_CREATOR)
        ok = api.adjudicate_case(
            ctx["case"]["id"],
            {"decision": "SUBSTANTIATED", "restitution_waived": True},
            make_manager_headers(MANAGER_1),
        )
        assert validate_success(ok)["status"] == "CLOSED_SUBSTANTIATED"

    def test_substantiated_adjudication_requires_demand_or_waiver(self, api):
        """PRD §3.5: "Unless the caller passes `restitution_waived` true, a
        civil demand for the case must already exist in `DRAFT`, `ISSUED`,
        `PARTIALLY_PAID`, or `PAID_IN_FULL` status (`ERR_DEMAND_REQUIRED`)."
        PRD §3.5: "A `decision` of UNSUBSTANTIATED applies the same role
        routing, the same two segregation walls, and the same
        documentation-staleness gate, then stamps `adjudicated_at`,
        `adjudicated_by`, and `closed_at`, cancels any `DRAFT` civil demand on
        the case, and lands the case in `CLOSED_UNSUBSTANTIATED`."

        The demand gate fires only on the SUBSTANTIATED branch.

        Design: Corner/validations/substantiated_adjudication_requires_demand_or_waiver
        """
        store = make_store(store_number="S066", name="Store 66")
        make_period(store["id"])
        ctx = setup_case_adjudicating(store["id"], manual_loss_cents=10000)
        resp = api.adjudicate_case(
            ctx["case"]["id"], {"decision": "SUBSTANTIATED"},
            make_manager_headers(MANAGER_1),
        )
        validate_error(resp, ApiErrorId.ERR_DEMAND_REQUIRED)
        ok = api.adjudicate_case(
            ctx["case"]["id"], {"decision": "UNSUBSTANTIATED"},
            make_manager_headers(MANAGER_1),
        )
        case = validate_success(ok)
        assert case["status"] == "CLOSED_UNSUBSTANTIATED"
        assert case["loss_posted_cents"] == 0

    def test_adjudicate_without_covering_period_returns_no_open_period(self, api):
        """PRD §3.5: "On success the case stamps `adjudicated_at`,
        `adjudicated_by`, and `closed_at` from the logical clock; sets
        `loss_posted_cents` — which every case carries at zero until this
        moment — equal to the current `total_loss_cents`; and posts that
        amount into the store's shrink period whose closed `[period_start,
        period_end]` interval contains the current logical date and whose
        status is `OPEN` or `COUNTED`. If no such period exists, the
        adjudication fails with `ERR_NO_OPEN_PERIOD`."

        Design: Corner/errors/adjudicate_without_covering_period_returns_no_open_period
        """
        store = make_store(store_number="S082", name="Store 82")
        ctx = setup_case_adjudicating(store["id"], manual_loss_cents=10000)
        resp = api.adjudicate_case(
            ctx["case"]["id"],
            {"decision": "SUBSTANTIATED", "restitution_waived": True},
            make_manager_headers(MANAGER_1),
        )
        validate_error(resp, ApiErrorId.ERR_NO_OPEN_PERIOD)
        assert get_case(ctx["case"]["id"])["status"] == "ADJUDICATING", (
            "no partial close when the loss cannot post"
        )

    def test_employee_terminated_blocks_new_employee_case(self, api):
        """PRD §3.1: "There is no operator-driven termination endpoint: an
        employee reaches `TERMINATED` only as a system side effect of a
        substantiated adjudication that directs `employment_action` TERMINATE,
        and this applies whether the employee was `ACTIVE` or `SUSPENDED` at
        the time. Once `TERMINATED`, the employee can no longer be the subject
        of a new employee-subject case nor be scheduled into a new interview —
        such attempts fail with `ERR_EMPLOYEE_NOT_ACTIVE`."
        PRD §3.5: "For an `EMPLOYEE` subject the employee's
        `prior_substantiated_count` increases by one, and the payload's
        `employment_action` — TERMINATE or SUSPEND — moves the employee to
        `TERMINATED` or `SUSPENDED` respectively."

        Design: Corner/errors/employee_terminated_blocks_new_employee_case
        """
        store = make_store(store_number="S080", name="Store 80")
        make_period(store["id"])
        emp = make_employee(store["id"], employee_ref="E-800", full_name="Emp 800")
        ctx = setup_case_adjudicating(
            store["id"], subject_type="EMPLOYEE", employee_id=emp["id"],
            manual_loss_cents=20000, evidence_type="TRANSACTION_LOG",
        )
        # ACTUAL_LOSS demand satisfies the demand gate (no waiver passed).
        draft_demand(ctx["case"]["id"], ANALYST_1, basis="ACTUAL_LOSS")
        case = adjudicate_case(
            ctx["case"]["id"], HR_PARTNER_1, subject_type="EMPLOYEE",
            decision="SUBSTANTIATED", employment_action="TERMINATE",
        )
        assert case["status"] == "CLOSED_SUBSTANTIATED"
        assert case["loss_posted_cents"] == 20000
        emp_after = validate_success(
            api.get_employee(emp["id"], make_hr_partner_headers(HR_PARTNER_1))
        )
        assert emp_after["status"] == "TERMINATED"
        assert emp_after["prior_substantiated_count"] == 1
        resp = api.create_case(
            {"store_id": store["id"], "subject_type": "EMPLOYEE",
             "employee_id": emp["id"], "manual_loss_cents": 5000},
            make_analyst_headers(ANALYST_1),
        )
        validate_error(resp, ApiErrorId.ERR_EMPLOYEE_NOT_ACTIVE)


class TestSoDVersusStaleDoc:
    """Priority pair: segregation-of-duties (step 9) precedes temporal rules
    (step 10) when an adjudication violates both."""

    def _setup_stale_interview_case(self, api):
        """EXTERNAL case created by ana-2, assigned to and interviewed by
        ana-1; interview documented 73 hours after conduct (stale); case at
        ADJUDICATING. The creator/interviewer split isolates the interviewer
        wall so the dual-failure call has exactly one step-9 violation."""
        store = make_store(store_number="S190", name="Store 190")
        ctx = setup_case_investigating(store["id"], manual_loss_cents=20000,
                                       creator_id=ANALYST_2, analyst_id=ANALYST_1)
        attach_evidence(ctx["case"]["id"], ANALYST_1,
                        evidence_type="WRITTEN_STATEMENT")
        ctx["case"] = advance_case(ctx["case"]["id"], ANALYST_1)
        interview = schedule_interview(ctx["case"]["id"], ANALYST_1, ANALYST_1)
        hold_interview(interview["id"], ANALYST_1, outcome="DENIED")
        # conducted_at stamped at the default clock 2026-08-01T00:00:00Z.
        set_clock("2026-08-04T00:00:01Z")  # 73h00m01s later
        interview = document_interview(interview["id"], ANALYST_1,
                                       notes="Filed 73 hours after conduct.")
        assert interview["doc_stale"] is True
        ctx["case"] = advance_case(ctx["case"]["id"], ANALYST_1)
        ctx["interview"] = interview
        return store, ctx

    def test_sod_interviewer_error_precedes_stale_doc_error(self, api):
        """PRD §2.7: "Every request passes through a single ordered validation
        pipeline, and the first failing check produces the response — later
        checks are not evaluated."
        PRD §2.7: "9. Segregation-of-duties and evidence-compliance rules
        (`ERR_SOD_INTERVIEWER_ADJUDICATOR`, `ERR_SOD_CASE_CREATOR`,
        `ERR_SOD_DEMAND_ISSUER`, `ERR_EVIDENCE_SEALED_IMMUTABLE`,
        `ERR_LEGAL_HOLD_ACTIVE`, `ERR_CUSTODY_GAP`)."
        PRD §2.7: "10. Temporal rules (`ERR_INTERVIEW_OVERLAP`,
        `ERR_PERIOD_OVERLAP`, `ERR_INTERVIEW_DOC_STALE`,
        `ERR_DEMAND_WINDOW_CLOSED`, `ERR_REOPEN_WINDOW_CLOSED`)."

        The interviewer (ana-1) adjudicating hits step 9 and step 10 at once;
        step 9 surfaces.

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_sod_interviewer_plus_stale_doc
        """
        _store, ctx = self._setup_stale_interview_case(api)
        resp = api.adjudicate_case(
            ctx["case"]["id"], {"decision": "UNSUBSTANTIATED"},
            make_manager_headers(ANALYST_1),
        )
        validate_error(resp, ApiErrorId.ERR_SOD_INTERVIEWER_ADJUDICATOR)

    def test_stale_doc_error_fires_once_sod_passes_and_override_succeeds(self, api):
        """PRD §3.5: "The latest `DOCUMENTED` interview must also be fresh —
        `doc_stale` false — unless the caller explicitly passes
        `documentation_override` true (`ERR_INTERVIEW_DOC_STALE`)."

        A non-interviewer, non-creator manager (mgr-1) on the identical state
        receives the temporal error; the explicit override then adjudicates.

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_sod_interviewer_plus_stale_doc
        """
        _store, ctx = self._setup_stale_interview_case(api)
        resp = api.adjudicate_case(
            ctx["case"]["id"], {"decision": "UNSUBSTANTIATED"},
            make_manager_headers(MANAGER_1),
        )
        validate_error(resp, ApiErrorId.ERR_INTERVIEW_DOC_STALE)
        ok = api.adjudicate_case(
            ctx["case"]["id"],
            {"decision": "UNSUBSTANTIATED", "documentation_override": True},
            make_manager_headers(MANAGER_1),
        )
        assert validate_success(ok)["status"] == "CLOSED_UNSUBSTANTIATED"
        interview = validate_success(
            api.get_interview(ctx["interview"]["id"], make_manager_headers(MANAGER_1))
        )
        assert interview["doc_stale"] is True


class TestReopen:
    def test_reopen_window_closes_30_days_after_close(self, api):
        """PRD §3.5: "Within thirty days of `closed_at` — the check passes
        when the current instant is on or before `closed_at` plus 30 days,
        else `ERR_REOPEN_WINDOW_CLOSED` — an `LPManager` may reopen a
        `CLOSED_SUBSTANTIATED` or `CLOSED_UNSUBSTANTIATED` case back to
        `INVESTIGATING`."

        Both cases closed (UNSUBSTANTIATED) at the default instant
        2026-08-01T00:00:00Z; reopen at exactly +30 days succeeds, at +30d+1s
        fails.

        Design: Corner/validations/reopen_window_closes_30_days_after_close
        """
        store = make_store(store_number="S068", name="Store 68")
        make_period(store["id"])
        cases = []
        for start, end in (("2026-08-02T09:00:00Z", "2026-08-02T10:00:00Z"),
                           ("2026-08-02T11:00:00Z", "2026-08-02T12:00:00Z")):
            ctx = setup_case_adjudicating(store["id"], manual_loss_cents=10000,
                                          scheduled_start=start, scheduled_end=end)
            case = adjudicate_case(ctx["case"]["id"], MANAGER_1,
                                   decision="UNSUBSTANTIATED")
            cases.append(case)
        set_clock("2026-08-31T00:00:00Z")  # closed_at + 30 days exactly
        resp_ok = api.reopen_case(
            cases[0]["id"], {"reason": "boundary ok"}, make_manager_headers(MANAGER_1)
        )
        assert validate_success(resp_ok)["status"] == "INVESTIGATING"
        set_clock("2026-08-31T00:00:01Z")  # one second past
        resp_late = api.reopen_case(
            cases[1]["id"], {"reason": "one second late"},
            make_manager_headers(MANAGER_1),
        )
        validate_error(resp_late, ApiErrorId.ERR_REOPEN_WINDOW_CLOSED)
        assert get_case(cases[1]["id"])["status"] == "CLOSED_UNSUBSTANTIATED"

    def test_reopen_blocked_by_posted_payment(self, api):
        """PRD §3.5: "Reopen is refused when the case's `loss_posted_period_id`
        names a period no longer `OPEN` or `COUNTED` (`ERR_PERIOD_LOCKED`), and
        when any demand of the case holds a `POSTED` payment
        (`ERR_CASE_HAS_PAYMENTS`)."

        Design: Corner/errors/reopen_blocked_by_posted_payment
        """
        store = make_store(store_number="S083", name="Store 83")
        make_period(store["id"])
        ctx = setup_case_interviewed(store["id"], manual_loss_cents=30000)
        demand = draft_demand(ctx["case"]["id"], ANALYST_1, basis="STATUTORY",
                              priors_offense_count=0)
        issue_demand(demand["id"], MANAGER_1)
        ctx["case"] = advance_case(ctx["case"]["id"], ANALYST_1)
        case = adjudicate_case(ctx["case"]["id"], MANAGER_1,
                               decision="SUBSTANTIATED")
        assert case["status"] == "CLOSED_SUBSTANTIATED"
        record_and_post_payment(demand["id"], 5000)
        resp = api.reopen_case(
            case["id"], {"reason": "new evidence"}, make_manager_headers(MANAGER_1)
        )
        validate_error(resp, ApiErrorId.ERR_CASE_HAS_PAYMENTS)
        after = get_case(case["id"])
        assert after["status"] == "CLOSED_SUBSTANTIATED"
        assert after["loss_posted_cents"] == 30000


class TestReopenCycle:
    """CLOSED_SUBSTANTIATED -> INVESTIGATING -> ... -> CLOSED_SUBSTANTIATED:
    the loss posting reverses on reopen and re-posts on re-adjudication."""

    def _setup_substantiated_150k(self, api):
        store = make_store(store_number="S150", name="Store 150")
        period = make_period(store["id"])
        ctx = setup_case_closed_substantiated(
            store["id"], manual_loss_cents=150000, evidence_type="PHOTO",
        )
        return store, period, ctx

    def _get_period(self, api, period_id):
        return validate_success(
            api.get_shrink_period(period_id, make_manager_headers(MANAGER_1))
        )

    def test_reopen_reverses_loss_posting_chain(self, api):
        """PRD §3.5: "Reopening a substantiated case unwinds the ledger: the
        period's `known_loss_posted_cents` falls by `loss_posted_cents`, the
        case-basis accrual recomputes, the store's `total_adjudicated_loss_cents`
        falls by the same amount, and the case's `loss_posted_cents` resets to
        zero."
        PRD §3.5: "Any `DRAFT` demand is cancelled, while `ISSUED` and
        `PARTIALLY_PAID` demands survive; `closed_at` is cleared and
        `restitution_status` recomputed."

        Design: Difficulty/non_linear_state_machine/case_reopen_cycle_reverses_and_reposts_loss
        """
        store, period, ctx = self._setup_substantiated_150k(api)
        assert self._get_period(api, period["id"])["known_loss_posted_cents"] == 150000
        resp = api.reopen_case(
            ctx["case"]["id"],
            {"reason": "New exculpatory claim requires re-investigation"},
            make_manager_headers(MANAGER_1),
        )
        case = validate_success(resp)
        assert case["status"] == "INVESTIGATING"
        assert case["loss_posted_cents"] == 0
        assert case["closed_at"] is None
        assert self._get_period(api, period["id"])["known_loss_posted_cents"] == 0
        store_after = validate_success(
            api.get_store(store["id"], make_manager_headers(MANAGER_1))
        )
        assert store_after["total_adjudicated_loss_cents"] == 0

    def test_readjudication_reposts_loss(self, api):
        """PRD §3.5: "On success the case stamps `adjudicated_at`,
        `adjudicated_by`, and `closed_at` from the logical clock; sets
        `loss_posted_cents` — which every case carries at zero until this
        moment — equal to the current `total_loss_cents`; and posts that
        amount into the store's shrink period whose closed `[period_start,
        period_end]` interval contains the current logical date and whose
        status is `OPEN` or `COUNTED`."

        The cycle completes: after reopen and a second full pipeline, the same
        150000 posts again into the still-OPEN period.

        Design: Difficulty/non_linear_state_machine/case_reopen_cycle_reverses_and_reposts_loss
        """
        store, period, ctx = self._setup_substantiated_150k(api)
        validate_success(api.reopen_case(
            ctx["case"]["id"], {"reason": "re-investigate"},
            make_manager_headers(MANAGER_1),
        ))
        # Second pass through the pipeline.
        case = advance_case(ctx["case"]["id"], ANALYST_1)
        assert case["status"] == "READY_FOR_INTERVIEW"
        interview = schedule_interview(
            ctx["case"]["id"], ANALYST_1, ANALYST_1,
            scheduled_start="2026-08-05T09:00:00Z",
            scheduled_end="2026-08-05T10:00:00Z",
        )
        hold_interview(interview["id"], ANALYST_1)
        document_interview(interview["id"], ANALYST_1, notes="Second interview documented.")
        case = advance_case(ctx["case"]["id"], ANALYST_1)
        assert case["status"] == "ADJUDICATING"
        case = adjudicate_case(ctx["case"]["id"], MANAGER_1,
                               decision="SUBSTANTIATED", restitution_waived=True)
        assert case["status"] == "CLOSED_SUBSTANTIATED"
        assert case["loss_posted_cents"] == 150000
        assert self._get_period(api, period["id"])["known_loss_posted_cents"] == 150000
        store_after = validate_success(
            api.get_store(store["id"], make_manager_headers(MANAGER_1))
        )
        assert store_after["total_adjudicated_loss_cents"] == 150000
