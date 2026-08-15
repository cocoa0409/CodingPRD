"""Disbursement lifecycle: the package-lock gate, schedule-amount validation,
posting aggregate bubbles, the DISBURSED auto-transition, returns, and the
existence-before-amount precedence (PRD §2.7, §3.7)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    SSN_NOT_SELECTED_A,
    TEST_USERS,
    ApiErrorId,
    accept_package_in_full,
    create_aid_year,
    create_disbursement_payload,
    evaluate_disbursement,
    get_package,
    get_success_data,
    lock_package,
    post_disbursement,
    schedule_disbursement,
    setup_disbursing_line,
    setup_notified_package,
    validate_error,
    validate_success,
)

OFFICER = TEST_USERS["aid_officer_headers"]

SAP_READY = {"gpa_hundredths": 300, "cumulative_attempted_credits": 30,
             "cumulative_completed_credits": 30}


def _disbursing_env(api):
    return setup_disbursing_line(ssn=SSN_NOT_SELECTED_A,
                                 student_overrides=dict(SAP_READY))


class TestBeginDisbursementGate:
    def test_begin_disbursement_rejected_until_package_locked(self, api):
        """PRD §3.7: "Once a package is `LOCKED`, an `AidOfficer` moves individual lines from `ACCEPTED` or `PARTIALLY_ACCEPTED` into `DISBURSING`; attempting this while the package is anything but `LOCKED` fails with `ERR_PARENT_STATE_BLOCKS`."

        Design: Difficulty/cross_entity_state_dependency/begin_disbursement_gated_by_package_lock
        """
        env = setup_notified_package(ssn=SSN_NOT_SELECTED_A)
        accept_package_in_full(env["package"]["id"], env["student"]["id"])
        line = env["lines"][0]

        line_now = get_success_data(api.get_award_line(line["id"], OFFICER))
        assert line_now["status"] == "ACCEPTED"
        assert get_package(env["package"]["id"])["status"] == "ACCEPTED"

        resp = api.begin_line_disbursement(line["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_PARENT_STATE_BLOCKS)
        after = get_success_data(api.get_award_line(line["id"], OFFICER))
        assert after["status"] == "ACCEPTED"

    def test_begin_disbursement_after_lock_succeeds(self, api):
        """PRD §3.7: "Once a package is `LOCKED`, an `AidOfficer` moves individual lines from `ACCEPTED` or `PARTIALLY_ACCEPTED` into `DISBURSING`; attempting this while the package is anything but `LOCKED` fails with `ERR_PARENT_STATE_BLOCKS`."

        Design: Difficulty/cross_entity_state_dependency/begin_disbursement_gated_by_package_lock
        """
        env = setup_notified_package(ssn=SSN_NOT_SELECTED_A)
        accept_package_in_full(env["package"]["id"], env["student"]["id"])
        locked = lock_package(env["package"]["id"])
        assert locked["status"] == "LOCKED"

        line = env["lines"][0]
        resp = api.begin_line_disbursement(line["id"], OFFICER)
        disbursing = validate_success(resp)
        assert disbursing["status"] == "DISBURSING"


class TestPostingCascade:
    def test_post_bubbles_disbursed_aggregates(self, api):
        """PRD §3.7: "Posting stamps the disbursement's `disbursed_cents` equal to `scheduled_cents`, adds `scheduled_cents` to the line's `disbursed_cents`, to the fund's `pool_disbursed_cents`, and to the aid year's `total_disbursed_cents`, and then evaluates the line's completion: when the line's posted total equals its `accepted_cents` (necessarily above zero, since at least one disbursement has posted), the line auto-transitions `DISBURSING` → `DISBURSED`."

        Design: Difficulty/transitive_cascade/disbursement_post_aggregate_bubble_cascade
        """
        env = _disbursing_env(api)
        disb = schedule_disbursement(env["line"]["id"], 369800)
        disb = evaluate_disbursement(disb["id"])
        assert disb["status"] == "ELIGIBILITY_PASSED"
        assert disb["failure_reasons"] == []

        posted = post_disbursement(disb["id"])
        assert posted["status"] == "POSTED"
        assert posted["disbursed_cents"] == 369800

        line = get_success_data(api.get_award_line(env["line"]["id"], OFFICER))
        assert line["disbursed_cents"] == 369800
        # 369_800 < 739_500 accepted: the completion auto-transition has not
        # fired yet.
        assert line["status"] == "DISBURSING"

        fund = get_success_data(api.get_fund_type(env["funds"]["PELL"]["id"],
                                                  OFFICER))
        assert fund["pool_disbursed_cents"] == 369800
        aid_year = get_success_data(api.get_aid_year(env["aid_year"]["id"],
                                                     OFFICER))
        assert aid_year["total_disbursed_cents"] == 369800

    def test_post_completing_accepted_amount_disburses_line(self, api):
        """PRD §3.7: "when the line's posted total equals its `accepted_cents` (necessarily above zero, since at least one disbursement has posted), the line auto-transitions `DISBURSING` → `DISBURSED`."

        Design: Difficulty/transitive_cascade/disbursement_post_aggregate_bubble_cascade
        """
        env = _disbursing_env(api)
        first = schedule_disbursement(env["line"]["id"], 369800)
        post_disbursement(evaluate_disbursement(first["id"])["id"])

        second = schedule_disbursement(env["line"]["id"], 369700)
        posted = post_disbursement(evaluate_disbursement(second["id"])["id"])
        assert posted["status"] == "POSTED"

        line = get_success_data(api.get_award_line(env["line"]["id"], OFFICER))
        # 369_800 + 369_700 = 739_500 == accepted_cents: link two fires.
        assert line["disbursed_cents"] == 739500
        assert line["status"] == "DISBURSED"


class TestPostReturnCompensation:
    def test_post_then_confirm_return_restores_aggregates(self, api):
        """PRD §3.7: "A posted disbursement can be moved `POSTED` → `RETURN_REQUESTED` and then, on confirmation, to the terminal `RETURNED`, subtracting its `disbursed_cents` from the line, the fund pool, and the aid-year total."

        Design: Difficulty/compensating_invariant/disbursement_post_return_restores_pool_disbursed
        """
        env = _disbursing_env(api)
        disb = schedule_disbursement(env["line"]["id"], 369800)
        posted = post_disbursement(evaluate_disbursement(disb["id"])["id"])

        validate_success(api.request_disbursement_return(posted["id"], OFFICER))
        returned = validate_success(
            api.confirm_disbursement_return(posted["id"], OFFICER))
        assert returned["status"] == "RETURNED"

        line = get_success_data(api.get_award_line(env["line"]["id"], OFFICER))
        assert line["disbursed_cents"] == 0
        fund = get_success_data(api.get_fund_type(env["funds"]["PELL"]["id"],
                                                  OFFICER))
        assert fund["pool_disbursed_cents"] == 0
        aid_year = get_success_data(api.get_aid_year(env["aid_year"]["id"],
                                                     OFFICER))
        assert aid_year["total_disbursed_cents"] == 0

    def test_return_requested_holds_aggregates_until_confirmation(self, api):
        """PRD §3.7: "A posted disbursement can be moved `POSTED` → `RETURN_REQUESTED` and then, on confirmation, to the terminal `RETURNED`, subtracting its `disbursed_cents` from the line, the fund pool, and the aid-year total."

        Design: Difficulty/compensating_invariant/disbursement_post_return_restores_pool_disbursed
        """
        env = _disbursing_env(api)
        disb = schedule_disbursement(env["line"]["id"], 369800)
        posted = post_disbursement(evaluate_disbursement(disb["id"])["id"])

        requested = validate_success(
            api.request_disbursement_return(posted["id"], OFFICER))
        assert requested["status"] == "RETURN_REQUESTED"
        # Money leaves the aggregates only on confirmation.
        line = get_success_data(api.get_award_line(env["line"]["id"], OFFICER))
        assert line["disbursed_cents"] == 369800
        fund = get_success_data(api.get_fund_type(env["funds"]["PELL"]["id"],
                                                  OFFICER))
        assert fund["pool_disbursed_cents"] == 369800

        returned = validate_success(
            api.confirm_disbursement_return(posted["id"], OFFICER))
        assert returned["status"] == "RETURNED"
        fund = get_success_data(api.get_fund_type(env["funds"]["PELL"]["id"],
                                                  OFFICER))
        assert fund["pool_disbursed_cents"] == 0


class TestDisbursementCreationValidation:
    def test_ghost_line_and_bad_amount_reports_reference_error(self, api):
        """PRD §2.7 (rung 4): "every foreign key in the request body, such as `fund_type_id` on award-line creation or `student_id` on ISIR import, references an existing entity — otherwise `ERR_REFERENCE_NOT_FOUND` (404)."
        PRD §2.7: "The checks are evaluated in the priority order given below, so an earlier failure masks later ones — for example, an unauthenticated caller always sees `ERR_UNAUTHENTICATED` even if the request would also have failed a downstream business rule."

        Design: Difficulty/priority_pair_validation_conflict/existence_vs_business_fiscal_on_disbursement_create
        """
        create_aid_year()
        resp = api.create_disbursement(
            create_disbursement_payload(NON_EXISTENT_UUID, scheduled_cents=-5),
            OFFICER)
        validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND)

    def test_ghost_line_reports_reference_error(self, api):
        """PRD §2.7 (rung 4): "every foreign key in the request body, such as `fund_type_id` on award-line creation or `student_id` on ISIR import, references an existing entity — otherwise `ERR_REFERENCE_NOT_FOUND` (404)."

        Design: Difficulty/priority_pair_validation_conflict/existence_vs_business_fiscal_on_disbursement_create
        """
        create_aid_year()
        resp = api.create_disbursement(
            create_disbursement_payload(NON_EXISTENT_UUID, scheduled_cents=100),
            OFFICER)
        validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND)

    def test_schedule_one_cent_over_headroom_rejected(self, api):
        """PRD §2.7 (rung 17): "`scheduled_cents` must be positive and no greater than the line's remaining headroom, the line must be `DISBURSING`, and the package must be `LOCKED` — otherwise `ERR_DISBURSEMENT_AMOUNT` (422)."
        PRD §3.7: "Scheduling validates rung 17: `scheduled_cents` must be strictly positive and no greater than the line's `accepted_cents` minus its `disbursed_cents`, the line must be `DISBURSING`, and the package must be `LOCKED` — otherwise `ERR_DISBURSEMENT_AMOUNT` (422)."

        Design: Corner/errors/error_disbursement_amount_over_headroom
        """
        env = _disbursing_env(api)
        # Accepted 739_500, nothing disbursed: 739_501 exceeds headroom by one
        # cent and must be rejected on the <= comparison.
        resp = api.create_disbursement(
            create_disbursement_payload(env["line"]["id"],
                                        scheduled_cents=739501),
            OFFICER)
        validate_error(resp, ApiErrorId.ERR_DISBURSEMENT_AMOUNT)
