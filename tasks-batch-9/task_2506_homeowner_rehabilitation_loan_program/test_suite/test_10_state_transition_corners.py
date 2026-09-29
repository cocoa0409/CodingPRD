"""Lifecycle edges: opening states, one-call double transitions and dead rows."""

from test_helpers import (
    api_client,
    assert_contractor,
    assert_instant,
    assert_property_inspection,
    assert_rehab_application,
    assert_unset,
    assert_version_incremented,
    create_application_payload,
    create_contractor_payload,
    create_inspection_payload,
    record_inspection_result_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    INSPECTOR,
    INTAKE,
    PROGRAM_MANAGER,
    REHAB,
    add_work_item,
    build_applicant,
    build_write_up,
    refresh_applicant,
    refresh_application,
    refresh_bid,
    refresh_contractor,
    refresh_solicitation,
    refresh_write_up,
    set_contractor_status,
    setup_case,
)


class TestOpeningStates:
    """Every row's first state is written by the program, not left blank."""

    def test_a_new_firm_opens_on_the_approved_list_with_a_perfect_score(self):
        """The performance score is seeded at 100 rather than left null until a complaint.

        PRD: "A new firm opens with `approved_list_status` of `APPROVED` and
        `performance_score` of 100, and with `open_complaint_count`,
        `sanction_count`, `on_time_completion_count` and `active_award_count` all
        zero."

        Design: Corner/state_machines/contractor_initial_state_is_approved_with_a_perfect_performance_score
        """
        payload = create_contractor_payload(
            legal_name="Borough Builders Inc",
            lead_safe_certified=False,
            historic_qualified=False,
        )

        firm = validate_success(
            api_client.create_contractor(payload, PROGRAM_MANAGER), 201
        )

        assert_contractor(firm)
        assert firm["approved_list_status"] == "APPROVED", (
            "A new firm joins the approved list outright, got "
            f"{firm['approved_list_status']}"
        )
        assert firm["performance_score"] == 100
        assert firm["open_complaint_count"] == 0
        assert firm["sanction_count"] == 0
        assert firm["on_time_completion_count"] == 0
        assert firm["active_award_count"] == 0
        assert firm["lead_safe_certified"] is False
        assert firm["historic_qualified"] is False


class TestOneCallTwoMachines:
    """A recorded finding moves the visit and the case in the same response."""

    def test_a_failing_finding_still_carries_the_case_forward(
        self, ownership_verified_application
    ):
        """A failed standards inspection means rehabilitation is warranted, not denial.

        PRD: "When at least one deficiency was recorded,
        `initial_deficiency_count` is set to the recorded count and the case
        advances `OWNERSHIP_VERIFIED → INSPECTED`."

        PRD: "`lead_review_required` is true when `year_built` is earlier than
        1978 — pre-1978 target housing — and false otherwise."

        Design: Corner/state_machines/recording_an_initial_standards_result_completes_the_inspection_and_advances_the_application
        """
        application_id = ownership_verified_application["id"]
        before_version = ownership_verified_application["version"]
        visit = validate_success(
            api_client.create_inspection(
                create_inspection_payload(application_id), INSPECTOR
            ),
            201,
        )
        assert visit["status"] == "SCHEDULED"

        recorded = validate_success(
            api_client.record_inspection_result(
                visit["id"],
                record_inspection_result_payload(
                    result="FAIL", deficiency_count=3, xrf_reading_mg_cm2=0.2
                ),
                INSPECTOR,
            ),
            200,
        )

        assert_property_inspection(recorded)
        assert recorded["status"] == "COMPLETED"
        assert recorded["result"] == "FAIL"
        assert recorded["deficiency_count"] == 3
        case = refresh_application(application_id)
        assert_rehab_application(case)
        assert case["workflow_state"] == "INSPECTED", (
            f"A failing finding advances the case, got {case['workflow_state']}"
        )
        assert case["initial_deficiency_count"] == 3
        assert case["lead_review_required"] is False, (
            "A 1995 dwelling is not pre-1978 target housing"
        )
        assert case["compliance_posture"] == "CLEAR"
        assert_version_incremented(case["version"], before_version)


class TestRefusedTransitions:
    """Steps that are not defined from the current state are refused, not absorbed."""

    def test_approving_a_draft_scope_is_refused(self, inspected_case):
        """Approval is reachable only from a submitted scope, so the step cannot be skipped.

        PRD: "Approval by a `ProgramManager` moves the write-up `SUBMITTED →
        APPROVED`, stamps `approved_by_user_id` with the acting `X-User-ID`, and
        drives the case `INSPECTED → WRITEUP_APPROVED`; both rows advance their
        `version` by one."

        Design: Corner/state_machines/approving_a_draft_write_up_is_rejected_with_invalid_state
        """
        write_up = build_write_up(inspected_case["application"]["id"])
        add_work_item(write_up["id"])
        assert refresh_write_up(write_up["id"])["state"] == "DRAFT"

        response = api_client.approve_write_up(write_up["id"], PROGRAM_MANAGER)

        validate_error(response, "ERR_INVALID_STATE", 409)
        unchanged = refresh_write_up(write_up["id"])
        assert unchanged["state"] == "DRAFT"
        assert_unset(unchanged, "approved_by_user_id")
        assert (
            refresh_application(inspected_case["application"]["id"])["workflow_state"]
            == "INSPECTED"
        )
        validate_error(
            api_client.request_write_up_revision(
                write_up["id"], {"revision_note": "Widen the roof scope"}, PROGRAM_MANAGER
            ),
            "ERR_INVALID_STATE",
            409,
        )
        assert refresh_write_up(write_up["id"])["state"] == "DRAFT"

    def test_certifying_income_twice_is_refused_on_the_replay(self, program_year):
        """Certification runs once; the replay is refused rather than silently redone.

        PRD: "The addressed row is in a state from which the requested transition
        is defined — otherwise `ERR_INVALID_STATE` (409)."

        Design: Corner/state_machines/verifying_income_twice_is_rejected_on_the_second_attempt
        """
        household = build_applicant(
            program_year["id"],
            wage_income_cents=7_000_000,
            household_assets_cents=5_000_000,
            dependents_count=2,
        )
        certified = validate_success(
            api_client.verify_income(household["id"], INTAKE), 200
        )
        assert certified["eligibility_status"] == "INCOME_VERIFIED"
        assert certified["annual_income_cents"] == 7_020_000, (
            "A 7,000,000 wage plus the 20,000 imputed on 5,000,000 of assets "
            f"certifies at 7,020,000, got {certified['annual_income_cents']}"
        )
        assert certified["ami_percent"] == 78.0
        assert certified["income_category"] == "LOW"

        response = api_client.verify_income(household["id"], INTAKE)

        validate_error(response, "ERR_INVALID_STATE", 409)
        unchanged = refresh_applicant(household["id"])
        assert unchanged["annual_income_cents"] == 7_020_000
        assert unchanged["version"] == certified["version"], (
            "The refused replay writes nothing, so the version stands at "
            f"{certified['version']}, got {unchanged['version']}"
        )

    def test_an_over_income_household_is_dead_for_transitions_but_still_readable(
        self, program_year
    ):
        """Over-income certification is terminal: no intake, no re-certification.

        PRD: "Over-income households are not refused at certification time — they
        are recorded and then blocked at application intake with
        `ERR_APPLICANT_OVER_INCOME`."

        Design: Corner/state_machines/an_ineligible_applicant_is_locked_down_against_further_transitions
        """
        household = build_applicant(
            program_year["id"],
            full_name="Wren Halloway",
            wage_income_cents=7_185_000,
            household_assets_cents=20_000_000,
            dependents_count=1,
        )
        certified = validate_success(
            api_client.verify_income(household["id"], INTAKE), 200
        )
        assert certified["annual_income_cents"] == 7_265_000, (
            "A 7,185,000 wage plus the 80,000 imputed on 20,000,000 of assets "
            f"certifies at 7,265,000, got {certified['annual_income_cents']}"
        )
        assert certified["ami_percent"] == 80.7
        assert certified["income_category"] == "OVER_INCOME"
        assert certified["eligibility_status"] == "INELIGIBLE"

        refused_intake = api_client.create_application(
            create_application_payload(
                household["id"],
                address_line1="4 Wexford Ct",
                year_built=1971,
                assessed_value_cents=21_000_000,
                senior_lien_balance_cents=9_000_000,
            ),
            INTAKE,
        )

        validate_error(refused_intake, "ERR_APPLICANT_OVER_INCOME", 422)
        _, meta = validate_paginated(
            api_client.list_applications(
                INTAKE, {"program_year_id": program_year["id"]}
            )
        )
        assert meta["total_count"] == 0, (
            f"No case is opened for the household, got {meta['total_count']}"
        )
        validate_error(
            api_client.verify_income(household["id"], INTAKE), "ERR_INVALID_STATE", 409
        )
        still_readable = validate_success(
            api_client.get_applicant(household["id"], INTAKE), 200
        )
        assert still_readable["eligibility_status"] == "INELIGIBLE"


class TestBiddingCycle:
    """The bidding leg is a loop, and an award takes a bid out of the cascade's reach."""

    def test_a_failed_solicitation_reopens_with_a_fresh_cutoff(self):
        """Rebidding rejects the stale bid, resets both counts and raises the cycle counter.

        PRD: "The solicitation moves `FAILED → OPEN`, its `bid_due_at` is
        replaced by the supplied instant, `reopen_count` increases by one, every
        bid of that solicitation in `RESPONSIVE` or `NON_RESPONSIVE` moves to
        `REJECTED`, both bid counts reset to zero, and the case moves
        `BID_FAILED → BID_OPEN`."

        Design: Corner/state_machines/a_failed_solicitation_reopens_and_the_cycle_counter_advances
        """
        case = setup_case(stage="bids_placed", bid_amount_cents=3_000_000)
        solicitation_id = case["solicitation"]["id"]
        bid_id = case["bid"]["id"]

        failed = validate_success(
            api_client.tabulate_solicitation(solicitation_id, REHAB), 200
        )

        assert failed["status"] == "FAILED", (
            "A single 3,000,000 bid is above the 2,420,000 ceiling, so no bid "
            f"survives tabulation, got {failed['status']}"
        )
        assert failed["bid_count"] == 1
        assert failed["responsive_bid_count"] == 0
        rejected_bid = refresh_bid(bid_id)
        assert rejected_bid["status"] == "NON_RESPONSIVE"
        assert rejected_bid["non_responsive_reason"] == "OVER_CEILING"
        assert (
            refresh_application(case["application"]["id"])["workflow_state"]
            == "BID_FAILED"
        )

        reopened = validate_success(
            api_client.reopen_solicitation(
                solicitation_id,
                {"new_bid_due_at": "2026-09-20T00:00:00Z"},
                PROGRAM_MANAGER,
            ),
            200,
        )

        assert reopened["status"] == "OPEN"
        assert reopened["reopen_count"] == 1
        assert_instant(reopened, "bid_due_at", "2026-09-20T00:00:00Z")
        assert reopened["bid_count"] == 0
        assert reopened["responsive_bid_count"] == 0
        assert refresh_bid(bid_id)["status"] == "REJECTED", (
            "The stale bid is not carried into the second round"
        )
        assert (
            refresh_application(case["application"]["id"])["workflow_state"]
            == "BID_OPEN"
        )

    def test_suspension_spares_a_bid_that_is_already_awarded(self, awarded_case):
        """The withdrawal cascade reaches live bids only, and an award is past it.

        PRD: "Hop two withdraws its live bids: every bid of that firm whose
        status is `SUBMITTED` or `RESPONSIVE` and whose solicitation is in `OPEN`
        or `TABULATED` moves to `WITHDRAWN_BY_PROGRAM`."

        Design: Corner/state_machines/suspending_a_contractor_spares_a_bid_that_has_already_been_awarded
        """
        case = awarded_case
        assert refresh_bid(case["bid"]["id"])["status"] == "AWARDED"
        assert case["solicitation"]["status"] == "AWARDED"
        assert case["solicitation"]["award_bid_id"] == case["bid"]["id"]
        assert case["application"]["workflow_state"] == "AWARDED"
        assert case["application"]["awarded_contractor_id"] == case["contractor"]["id"]

        suspended = set_contractor_status(
            case["contractor"]["id"], "SUSPENDED", "Unrelated licensing audit"
        )

        assert suspended["approved_list_status"] == "SUSPENDED"
        assert refresh_bid(case["bid"]["id"])["status"] == "AWARDED", (
            "An awarded bid is not withdrawn by the suspension cascade"
        )
        solicitation = refresh_solicitation(case["solicitation"]["id"])
        assert solicitation["status"] == "AWARDED"
        assert solicitation["responsive_bid_count"] == 1
        assert (
            refresh_application(case["application"]["id"])["workflow_state"]
            == "AWARDED"
        ), "The case is not pushed to BID_FAILED behind an award"
        assert refresh_contractor(case["contractor"]["id"])["active_award_count"] == 1
