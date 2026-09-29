"""Declared edges, refused edges, and the states a caller may never observe.

Each case drives one resource across a boundary in its own lifecycle: a plan
year that may not go live without a third-party administrator on the roster, a
gag dimension that may not be cleared before it has been reviewed, a negotiation
loop with a hard round cap, and an obligation that only an operations checkpoint
can ever mark missed. A refused edge must leave the addressed row exactly where
it was, version included.
"""

from __future__ import annotations

from test_helpers import (
    COMPLIANCE_OFFICER_HEADERS,
    EXTERNAL_AUDITOR_HEADERS,
    OFFICER_PREPARER_HEADERS,
    OFFICER_PREPARER_USER_ID,
    OFFICER_SIGNER_USER_ID,
    PLATFORM_OPERATOR_HEADERS,
    SPONSOR_ADMIN_HEADERS,
    ApiClient,
    ApiErrorId,
    AMENDMENT_COUNTERED,
    AMENDMENT_PROPOSED,
    ATTESTATION_ACCEPTED,
    CYCLE_MISSED,
    CYCLE_PENDING,
    DATA_RIGHTS_NOT_SECURED,
    DATA_RIGHTS_PENDING_AMENDMENT,
    DATA_RIGHTS_SECURED,
    DEFICIENCY_MRF_REFRESH,
    ENTRY_ACCRUAL,
    GAG_IN_REVIEW,
    GAG_NOT_REVIEWED,
    LIFECYCLE_ACTIVE,
    LIFECYCLE_REPORTING_CLOSED,
    LIFECYCLE_SETUP,
    POSTURE_AT_RISK,
    POSTURE_COMPLIANT,
    POSTURE_FROZEN,
    VENDOR_TYPE_BROKER,
    VENDOR_TYPE_PBM,
    assert_instant_equals,
    factories as f,
    fixtures as fx,
    make_vendor_contact_headers,
    validate_error,
    validate_success,
)

SETUP_CLOCK = "2027-01-02T09:00:00Z"
REVIEW_CLOCK = "2027-02-01T09:00:00Z"
NEGOTIATION_CLOCK = "2027-03-01T09:00:00Z"
CYCLE_CLOCK = "2027-04-01T09:00:00Z"
FREEZE_CLOCK = "2027-06-01T09:00:00Z"
JUNE_OPEN_CLOCK = "2027-06-01T09:00:00Z"
RUN_CLOCK = "2027-07-08T09:00:00Z"
LAST_DAY_CLOCK = "2027-12-31T23:00:00Z"
DAY_AFTER_CLOCK = "2028-01-01T00:00:00Z"
ADJUDICATION_CLOCK = "2028-01-10T09:00:00Z"

FREEZE_REASON = "DOL information request pending."
AMENDMENT_EXPIRY = "2027-12-31T00:00:00Z"


def _plan_year_with_only_a_broker(api: ApiClient) -> dict:
    """A SETUP plan year whose entire roster is one broker contract."""
    fx.set_clock(api, SETUP_CLOCK)
    plan_year = fx.create_plan_year(api, covered_lives=6000)
    broker = fx.create_broker_vendor(api)
    contract = fx.create_contract(
        api,
        plan_year["id"],
        broker["id"],
        contract_type=VENDOR_TYPE_BROKER,
        annual_fee_cents=2_400_000,
    )
    return {"plan_year": plan_year, "broker_contract": contract}


def _live_plan_year(api: ApiClient, clock: str) -> str:
    """An ACTIVE plan year with one TPA contract, at the supplied clock."""
    fx.set_clock(api, clock)
    return fx.activated_plan_year(api, covered_lives=6000)["plan_year"]["id"]


def _pbm_contract_on_a_live_plan_year(api: ApiClient) -> dict:
    """An ACTIVE plan year plus a pharmacy contract at NOT_REVIEWED / NOT_SECURED."""
    fx.set_clock(api, NEGOTIATION_CLOCK)
    setup = fx.activated_plan_year(api, covered_lives=6000)
    pbm = fx.add_contract_for_vendor_type(
        api,
        setup["plan_year"]["id"],
        VENDOR_TYPE_PBM,
        annual_fee_cents=12_000_000,
    )
    return {
        "plan_year_id": setup["plan_year"]["id"],
        "vendor_id": pbm["vendor"]["id"],
        "contract_id": pbm["contract"]["id"],
    }


class TestPlanYearLifecycleEdges:
    """Going live, going live twice, closing early, and coming out of a freeze."""

    def test_a_roster_without_a_third_party_administrator_cannot_go_live(
        self, api: ApiClient
    ) -> None:
        """One broker contract is a roster, but it is not the required one.

        PRD 3.1: "Activation is the sponsor's declaration that the plan year is
        live. It moves `lifecycle_status` from `SETUP` to `ACTIVE`, and it is
        refused unless the plan year is currently in `SETUP`, its
        `compliance_posture` is not `FROZEN`, and at least one service provider
        contract of that plan year has `contract_type` `TPA` — the third-party
        administrator is the counterparty through whom most transparency data
        actually flows, so a plan year with no TPA on the roster is refused with
        `ERR_TPA_CONTRACT_REQUIRED`."

        Design: Corner/state_machines/plan_year_activate_without_tpa_contract_rejected
        """
        built = _plan_year_with_only_a_broker(api)
        plan_year_id = built["plan_year"]["id"]

        response = api.activate_plan_year(plan_year_id, SPONSOR_ADMIN_HEADERS)
        validate_error(response, ApiErrorId.TPA_CONTRACT_REQUIRED, expected_status=409)

        unchanged = fx.read_plan_year(api, plan_year_id)
        assert unchanged["lifecycle_status"] == LIFECYCLE_SETUP
        assert unchanged["compliance_posture"] == POSTURE_COMPLIANT
        assert unchanged["version"] == 1

    def test_activating_an_already_live_plan_year_is_refused_not_a_no_op(
        self, api: ApiClient
    ) -> None:
        """ACTIVE is not a declared origin for the activation edge.

        PRD 2.9: "**State legality.** The addressed resource is in a state from
        which the requested transition or state-requiring action is declared,
        including any parent `lifecycle_status` precondition — otherwise
        `ERR_INVALID_STATE_TRANSITION` (409)."

        Design: Corner/state_machines/plan_year_activate_twice_rejected
        """
        fx.set_clock(api, SETUP_CLOCK)
        setup = fx.activated_plan_year(api, covered_lives=6000)
        plan_year_id = setup["plan_year"]["id"]
        version_after_activation = setup["plan_year"]["version"]
        assert setup["plan_year"]["lifecycle_status"] == LIFECYCLE_ACTIVE

        response = api.activate_plan_year(plan_year_id, SPONSOR_ADMIN_HEADERS)
        validate_error(
            response, ApiErrorId.INVALID_STATE_TRANSITION, expected_status=409
        )

        unchanged = fx.read_plan_year(api, plan_year_id)
        assert unchanged["lifecycle_status"] == LIFECYCLE_ACTIVE
        assert unchanged["version"] == version_after_activation

    def test_reporting_closes_only_once_the_final_day_is_behind_the_clock(
        self, api: ApiClient
    ) -> None:
        """On 2027-12-31 the year is still running; on 2028-01-01 it is over.

        PRD 3.1: "This is refused unless the plan year is `ACTIVE`, its posture
        is not `FROZEN`, and the logical clock date is strictly after `end_date`;
        closing on the last day of the plan year itself is refused with
        `ERR_REPORTING_PERIOD_NOT_ENDED`."

        Design: Corner/state_machines/close_reporting_before_end_date_rejected
        """
        plan_year_id = _live_plan_year(api, SETUP_CLOCK)

        fx.set_clock(api, LAST_DAY_CLOCK)
        too_early = api.close_reporting(plan_year_id, SPONSOR_ADMIN_HEADERS)
        validate_error(
            too_early, ApiErrorId.REPORTING_PERIOD_NOT_ENDED, expected_status=409
        )
        assert fx.read_plan_year(api, plan_year_id)["lifecycle_status"] == (
            LIFECYCLE_ACTIVE
        )

        fx.set_clock(api, DAY_AFTER_CLOCK)
        closed = validate_success(
            api.close_reporting(plan_year_id, SPONSOR_ADMIN_HEADERS)
        )
        assert closed["lifecycle_status"] == LIFECYCLE_REPORTING_CLOSED

        settled = fx.read_plan_year(api, plan_year_id)
        assert settled["compliance_posture"] == POSTURE_COMPLIANT
        assert settled["deficiency_points"] == 0

    def test_unfreezing_re_derives_the_posture_instead_of_restoring_it(
        self, api: ApiClient
    ) -> None:
        """Nothing is wrong with this plan year, so it lands on COMPLIANT.

        PRD 3.9: "Freezing requires `freeze_flag` to be currently false, sets
        `freeze_flag` to true and `freeze_reason` to the supplied reason, forces
        `compliance_posture` to `FROZEN` regardless of the point total — the
        declared edges are `COMPLIANT → FROZEN` and `DEFICIENT → FROZEN`, and the
        posture ladder of §2.8 places any plan year with `freeze_flag` true at
        `FROZEN` from whatever posture it held — and increments the plan year's
        `version` by 1."

        PRD 3.9: "It clears `freeze_flag` to false and `freeze_reason` to null,
        then recomputes `deficiency_points` and walks the posture ladder afresh,
        incrementing the plan year's `version` by 1."

        Design: Corner/state_machines/unfreeze_recomputes_posture_from_points
        """
        plan_year_id = _live_plan_year(api, FREEZE_CLOCK)

        frozen = validate_success(
            api.freeze_plan_year(
                plan_year_id, {"reason": FREEZE_REASON}, EXTERNAL_AUDITOR_HEADERS
            )
        )
        assert frozen["freeze_flag"] is True
        assert frozen["freeze_reason"] == FREEZE_REASON
        assert frozen["compliance_posture"] == POSTURE_FROZEN
        assert frozen["deficiency_points"] == 0

        thawed = validate_success(
            api.unfreeze_plan_year(
                plan_year_id,
                EXTERNAL_AUDITOR_HEADERS,
                {"note": "Request closed; filings resume."},
            )
        )
        assert thawed["freeze_flag"] is False
        assert thawed["freeze_reason"] is None
        assert thawed["compliance_posture"] == POSTURE_COMPLIANT
        assert thawed["lifecycle_status"] == LIFECYCLE_ACTIVE

        settled = fx.read_plan_year(api, plan_year_id)
        assert settled["penalty_exposure_cents"] == 0
        assert fx.list_ledger_entries(api, plan_year_id) == []


class TestContractDimensionsAndNegotiation:
    """Two independent axes on one row, and the loop that drives one of them."""

    def test_a_contract_cannot_be_cleared_before_anyone_reviewed_it(
        self, api: ApiClient
    ) -> None:
        """A default count of zero prohibited clauses is not a finding of zero.

        PRD 3.4: "Clearing ends the review favourably. It moves the contract
        `IN_REVIEW → COMPLIANT`, which is terminal, and it requires
        `prohibited_clause_count` to be exactly 0 — clearing a contract that
        still has prohibited language is refused with
        `ERR_PROHIBITED_CLAUSES_PRESENT`."

        PRD 2.9: "No later check may pre-empt an earlier one, and the ordering is
        total across the whole service."

        Design: Corner/state_machines/clear_gag_from_not_reviewed_rejected
        """
        fx.set_clock(api, REVIEW_CLOCK)
        setup = fx.activated_plan_year(api, covered_lives=6000)
        contract_id = setup["tpa_contract"]["id"]
        before = fx.read_contract(api, contract_id)
        assert before["gag_review_status"] == GAG_NOT_REVIEWED
        assert before["prohibited_clause_count"] == 0

        response = api.clear_gag(
            contract_id,
            COMPLIANCE_OFFICER_HEADERS,
            f.clear_gag_payload(clearance_note="Assuming clean without a review."),
        )
        body = validate_error(
            response, ApiErrorId.INVALID_STATE_TRANSITION, expected_status=409
        )
        assert body["error_id"] != ApiErrorId.PROHIBITED_CLAUSES_PRESENT

        unchanged = fx.read_contract(api, contract_id)
        assert unchanged["gag_review_status"] == GAG_NOT_REVIEWED
        assert unchanged["clause_inventory_count"] == 0

    def test_the_gag_axis_and_the_data_rights_axis_never_disturb_each_other(
        self, api: ApiClient
    ) -> None:
        """The contract reaches SECURED while its review is still open.

        PRD 3.4: "Every service provider contract carries two entirely
        independent status dimensions."

        PRD 3.4: "Neither dimension constrains the other's transitions; a
        contract can be gag-`COMPLIANT` while its data rights are still
        `NOT_SECURED`, and vice versa."

        Design: Corner/state_machines/contract_parallel_dimensions_move_independently
        """
        built = _pbm_contract_on_a_live_plan_year(api)
        contract_id = built["contract_id"]

        fx.open_gag_review(
            api, contract_id, clause_inventory_count=18, prohibited_clause_count=2
        )
        after_review = fx.read_contract(api, contract_id)
        assert after_review["gag_review_status"] == GAG_IN_REVIEW
        assert after_review["prohibited_clause_count"] == 2
        assert after_review["data_rights_status"] == DATA_RIGHTS_NOT_SECURED

        amendment = fx.propose_amendment(
            api,
            contract_id,
            proposed_terms_summary="Grant claim-level data rights.",
            expires_at=AMENDMENT_EXPIRY,
        )
        after_proposal = fx.read_contract(api, contract_id)
        assert after_proposal["data_rights_status"] == DATA_RIGHTS_PENDING_AMENDMENT
        assert after_proposal["gag_review_status"] == GAG_IN_REVIEW
        assert after_proposal["prohibited_clause_count"] == 2

        validate_success(
            api.execute_amendment(
                amendment["id"],
                SPONSOR_ADMIN_HEADERS,
                f.execute_amendment_payload(executed_terms_note="Rider executed."),
            )
        )
        after_execution = fx.read_contract(api, contract_id)
        assert after_execution["data_rights_status"] == DATA_RIGHTS_SECURED
        assert after_execution["gag_review_status"] == GAG_IN_REVIEW

        plan_year = fx.read_plan_year(api, built["plan_year_id"])
        assert plan_year["deficiency_points"] == 0
        assert plan_year["compliance_posture"] == POSTURE_COMPLIANT

    def test_the_third_sponsor_revision_exhausts_the_negotiation(
        self, api: ApiClient
    ) -> None:
        """Rounds are counted from one, so round three is the last position.

        PRD 3.5: "The sponsor answers a counter by revising, supplying a fresh
        `proposed_terms_summary` and a fresh `data_rights_granted`; the amendment
        moves `COUNTERED → PROPOSED`, both fields are replaced from the request,
        `round` increments by 1, and `version` increments by 1. Revision is
        refused once `round` has reached 3 — `ERR_NEGOTIATION_ROUNDS_EXHAUSTED` —
        so a single amendment supports at most three sponsor positions before it
        must be executed, abandoned, or superseded by a fresh proposal."

        Design: Corner/state_machines/amendment_negotiation_cycle_exhausts_at_round_three
        """
        built = _pbm_contract_on_a_live_plan_year(api)
        vendor_headers = make_vendor_contact_headers(built["vendor_id"])
        amendment = fx.propose_amendment(
            api,
            built["contract_id"],
            proposed_terms_summary="Round 1 terms.",
            expires_at=AMENDMENT_EXPIRY,
        )
        amendment_id = amendment["id"]
        assert amendment["round"] == 1

        validate_success(
            api.counter_amendment(
                amendment_id,
                f.counter_amendment_payload(
                    counter_terms_summary=(
                        "Vendor counter 1: data rights limited to aggregate extracts."
                    )
                ),
                vendor_headers,
            )
        )
        second_round = validate_success(
            api.revise_proposal(
                amendment_id,
                f.revise_proposal_payload(proposed_terms_summary="Round 2 terms."),
                SPONSOR_ADMIN_HEADERS,
            )
        )
        assert second_round["status"] == AMENDMENT_PROPOSED
        assert second_round["round"] == 2

        validate_success(
            api.counter_amendment(
                amendment_id,
                f.counter_amendment_payload(counter_terms_summary="Vendor counter 2."),
                vendor_headers,
            )
        )
        third_round = validate_success(
            api.revise_proposal(
                amendment_id,
                f.revise_proposal_payload(proposed_terms_summary="Round 3 terms."),
                SPONSOR_ADMIN_HEADERS,
            )
        )
        assert third_round["round"] == 3

        validate_success(
            api.counter_amendment(
                amendment_id,
                f.counter_amendment_payload(counter_terms_summary="Vendor counter 3."),
                vendor_headers,
            )
        )
        refused = api.revise_proposal(
            amendment_id,
            f.revise_proposal_payload(proposed_terms_summary="Round 4 terms."),
            SPONSOR_ADMIN_HEADERS,
        )
        validate_error(
            refused, ApiErrorId.NEGOTIATION_ROUNDS_EXHAUSTED, expected_status=409
        )

        stalled = validate_success(
            api.get_amendment(amendment_id, SPONSOR_ADMIN_HEADERS)
        )
        assert stalled["status"] == AMENDMENT_COUNTERED
        assert stalled["round"] == 3
        assert stalled["counter_terms_summary"] == "Vendor counter 3."
        assert stalled["executed_at"] is None
        assert (
            fx.read_contract(api, built["contract_id"])["data_rights_status"]
            == DATA_RIGHTS_PENDING_AMENDMENT
        )


class TestObligationsOpenAndTerminate:
    """What a fresh obligation looks like, what closes it, and what locks it."""

    def test_a_fresh_refresh_cycle_is_pending_with_a_derived_grace_deadline(
        self, api: ApiClient
    ) -> None:
        """Never certified is null, which is not the same as certified late.

        PRD 3.2: "The service derives `deadline_at` on creation rather than
        accepting it: it is the instant five days after `period_end`, at
        23:59:59.999Z on that fifth day — a five-day grace window on top of the
        period itself. A cycle opens in `PENDING` with `certified_at`,
        `certified_by_user_id`, `certification_note` and `on_time` all null."

        Design: Corner/state_machines/refresh_cycle_initial_state_pending_with_derived_deadline
        """
        plan_year_id = _live_plan_year(api, CYCLE_CLOCK)

        opened = validate_success(
            api.create_refresh_cycle(
                f.refresh_cycle_payload(
                    plan_year_id,
                    period_month="2027-03",
                    period_start="2027-03-01",
                    period_end="2027-03-31",
                ),
                COMPLIANCE_OFFICER_HEADERS,
            ),
            expected_status=201,
        )
        assert opened["status"] == CYCLE_PENDING
        assert_instant_equals(opened["deadline_at"], "2027-04-05T23:59:59.999Z")
        assert opened["on_time"] is None
        assert opened["certified_at"] is None
        assert opened["certified_by_user_id"] is None
        assert opened["certification_note"] is None

        stored = validate_success(
            api.get_refresh_cycle(opened["id"], COMPLIANCE_OFFICER_HEADERS)
        )
        assert stored["period_month"] == "2027-03"
        assert stored["version"] == 1

    def test_only_the_operations_checkpoint_marks_an_obligation_missed(
        self, api: ApiClient
    ) -> None:
        """Three days past a five-day grace window prices at 60,000 cents.

        PRD 3.9: "First it sweeps refresh cycles. Every cycle of the plan year
        still in `PENDING` whose `deadline_at` is strictly earlier than the
        logical clock moves `PENDING → MISSED` with its `version` incremented by
        1. Each newly missed cycle then posts one ledger accrual with
        `entry_type` `ACCRUAL`, `deficiency_type` `MRF_REFRESH` and `onset_date`
        equal to the day after that cycle's `deadline_at` date, priced by the
        accrual formula above — unless an unreversed `MRF_REFRESH` accrual
        already exists for that cycle's `period_month`, in which case no second
        accrual is posted."

        Design: Corner/state_machines/compliance_run_sweeps_pending_cycle_to_missed
        """
        plan_year_id = _live_plan_year(api, JUNE_OPEN_CLOCK)
        cycle = fx.open_refresh_cycle(
            api,
            plan_year_id,
            period_month="2027-06",
            period_start="2027-06-01",
            period_end="2027-06-30",
        )
        assert cycle["status"] == CYCLE_PENDING

        fx.set_clock(api, RUN_CLOCK)
        summary = validate_success(
            api.run_compliance(plan_year_id, PLATFORM_OPERATOR_HEADERS)
        )
        assert summary["run_id"] is not None
        assert summary["cycles_missed_count"] == 1
        assert summary["accruals_posted_count"] == 1
        assert summary["amendments_lapsed_count"] == 0
        assert summary["posture_before"] == POSTURE_COMPLIANT
        assert summary["posture_after"] == POSTURE_AT_RISK
        assert summary["deficiency_points"] == 3
        assert summary["penalty_exposure_cents"] == 60_000

        swept = validate_success(
            api.get_refresh_cycle(cycle["id"], COMPLIANCE_OFFICER_HEADERS)
        )
        assert swept["status"] == CYCLE_MISSED
        assert swept["on_time"] is None
        assert swept["certified_at"] is None

        entries = fx.list_ledger_entries(api, plan_year_id)
        assert len(entries) == 1
        accrual = entries[0]
        assert accrual["entry_type"] == ENTRY_ACCRUAL
        assert accrual["deficiency_type"] == DEFICIENCY_MRF_REFRESH
        assert accrual["onset_date"] == "2027-07-06"
        assert accrual["days_open"] == 3
        assert accrual["daily_rate_cents"] == 10_000
        assert accrual["size_multiplier"] == 2.0
        assert accrual["signed_amount_cents"] == 60_000
        assert accrual["posted_by_user_id"] is None

        plan_year = fx.read_plan_year(api, plan_year_id)
        assert plan_year["deficiency_points"] == 3
        assert plan_year["compliance_posture"] == POSTURE_AT_RISK
        assert plan_year["penalty_exposure_cents"] == 60_000
        assert_instant_equals(plan_year["last_compliance_run_at"], RUN_CLOCK)

    def test_an_accepted_attestation_can_never_be_reopened(
        self, api: ApiClient
    ) -> None:
        """Revision is declared from REJECTED, and acceptance is the end of the road.

        PRD 3.8: "Acceptance, optionally annotated with an `acceptance_note`,
        moves the attestation `SUBMITTED → ACCEPTED`, which is terminal. The plan
        year's `attestation_status` becomes `ACCEPTED`, its `deficiency_points`
        are recomputed because reaching `ACCEPTED` is exactly what closes the
        `ATTESTATION_LATE` deficiency, and both the attestation's `version` and
        the plan year's `version` increment by 1 each. Acceptance posts **no**
        ledger entry of any kind."

        Design: Corner/state_machines/accepted_attestation_is_terminal
        """
        fx.set_clock(api, ADJUDICATION_CLOCK)
        setup = fx.accepted_attestation(api, covered_lives=6000)
        plan_year_id = setup["plan_year"]["id"]
        attestation_id = setup["attestation"]["id"]
        assert setup["attestation"]["status"] == ATTESTATION_ACCEPTED

        response = api.revise_attestation(
            attestation_id,
            f.revise_attestation_payload(contract_terms_doc_count=4),
            OFFICER_PREPARER_HEADERS,
        )
        validate_error(
            response, ApiErrorId.INVALID_STATE_TRANSITION, expected_status=409
        )

        unchanged = validate_success(
            api.get_attestation(attestation_id, COMPLIANCE_OFFICER_HEADERS)
        )
        assert unchanged["status"] == ATTESTATION_ACCEPTED
        assert unchanged["revision_round"] == 0
        assert unchanged["contract_terms_doc_count"] == 3
        assert unchanged["submitted_by_user_id"] == OFFICER_SIGNER_USER_ID
        assert unchanged["prepared_by_user_id"] == OFFICER_PREPARER_USER_ID

        plan_year = fx.read_plan_year(api, plan_year_id)
        assert plan_year["attestation_status"] == ATTESTATION_ACCEPTED
        assert plan_year["deficiency_points"] == 0
        assert plan_year["penalty_exposure_cents"] == 0
        assert fx.list_ledger_entries(api, plan_year_id) == []
