"""Domestic recruitment: the preference-period window, hire ceilings, the visa
ceiling they feed, and the state-vs-safety validation priority."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_application,
    create_grower,
    create_petition,
    create_recruiting_order,
    create_wage_determination,
    decide_application,
    get_success_data,
    set_clock,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["contractor_admin_headers"]
REVIEWER = TEST_USERS["program_reviewer_headers"]


def _recruiting_j1(**order_overrides):
    grower = create_grower()
    wd = create_wage_determination()
    order = create_recruiting_order(grower["id"], wd["id"], **order_overrides)
    return grower, wd, order


class TestPreferenceWindowBoundary:
    def test_reject_qualified_applied_on_cutoff_blocked(self, api):
        """PRD 3.3: "Rejection moves the application to `REJECTED`, but the
        domestic-worker preference rule guards it: an applicant whose `applied_on`
        falls on or before the order's `recruitment_cutoff_date` is inside the
        preference window, and rejecting such an applicant whom the contractor has
        just marked `QUALIFIED` is forbidden — the decision is rejected with
        `ERR_DOMESTIC_PREFERENCE_VIOLATION` (HTTP 422). The boundary is inclusive:
        an application filed exactly on the cutoff date is still inside the window,
        while one filed the day after the cutoff is outside it."

        Design: Difficulty/boundary_precision_check/recruitment_cutoff_on_date_blocked_next_day_allowed
        """
        _, _, jo = _recruiting_j1()
        # recruitment_cutoff_date for the 50-day J1 window is 2026-09-25.
        set_clock("2026-09-25T00:00:00Z")
        app_in = create_application(jo["id"], applicant_name="In Window", contact_phone="555-0101")
        assert app_in["applied_on"] == "2026-09-25"

        resp = api.decide_domestic_application(
            app_in["id"], {"decision": "REJECT", "qualification": "QUALIFIED"}, ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_DOMESTIC_PREFERENCE_VIOLATION)

        current = get_success_data(api.list_domestic_applications(jo["id"], ADMIN))
        assert current[0]["status"] == "APPLIED", "rejected decision must not partially mutate"

    def test_reject_qualified_applied_day_after_cutoff_allowed(self, api):
        """PRD 3.3: "The boundary is inclusive: an application filed exactly on the
        cutoff date is still inside the window, while one filed the day after the
        cutoff is outside it."
        PRD 3.3: "A successful decision stamps `decided_on` with the clock date and
        records the supplied `qualification`."

        Design: Difficulty/boundary_precision_check/recruitment_cutoff_on_date_blocked_next_day_allowed
        """
        _, _, jo = _recruiting_j1()
        set_clock("2026-09-26T00:00:00Z")
        app_out = create_application(jo["id"], applicant_name="Out Window", contact_phone="555-0102")
        assert app_out["applied_on"] == "2026-09-26"

        decided = validate_success(
            api.decide_domestic_application(
                app_out["id"], {"decision": "REJECT", "qualification": "QUALIFIED"}, ADMIN
            ),
            200,
        )
        assert decided["status"] == "REJECTED"
        assert decided["qualification"] == "QUALIFIED"
        assert decided["decided_on"] == "2026-09-26"


class TestCeilings:
    def test_domestic_hires_zero_visa_ceiling_blocks_file(self, api):
        """PRD 3.4: "Filing requires the parent order to have reached `PETITIONING`
        (else `ERR_JOB_ORDER_INVALID_STATE`) and requires `requested_worker_count`
        to fit within the order's `visa_worker_ceiling` — the count fixed by
        domestic hiring when recruitment closed — else the filing is rejected with
        `ERR_PETITION_EXCEEDS_VISA_CEILING`."
        PRD 3.2: "`domestic_hired_count` counts the order's domestic applications
        currently in `HIRED` status, and `visa_worker_ceiling` is
        `workers_requested` minus that count — the upper bound on beneficiaries a
        petition may request at filing time."

        Design: Corner/validations/domestic_hires_zero_visa_ceiling_blocks_file
        """
        _, _, jo = _recruiting_j1(workers_requested=2)
        app1 = create_application(jo["id"], applicant_name="Dom One", contact_phone="555-0101")
        decide_application(app1["id"], "HIRE", "QUALIFIED")
        app2 = create_application(jo["id"], applicant_name="Dom Two", contact_phone="555-0102")
        decide_application(app2["id"], "HIRE", "QUALIFIED")
        get_success_data(api.close_recruitment(jo["id"], ADMIN))
        petition = create_petition(jo["id"], receipt_code="RCPT-1", requested_worker_count=1)

        resp = api.file_visa_petition(petition["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_PETITION_EXCEEDS_VISA_CEILING)

        current = get_success_data(api.get_job_order(jo["id"], ADMIN))
        assert current["domestic_hired_count"] == 2
        assert current["visa_worker_ceiling"] == 0

    def test_domestic_hire_beyond_workers_requested_rejected(self, api):
        """PRD 3.3: "Hiring moves the application to `HIRED`, but only while the
        order's `domestic_hired_count` is still below its `workers_requested`;
        hiring when the count has already reached that ceiling is rejected with
        `ERR_WORKER_CEILING_EXCEEDED`."

        Design: Corner/validations/domestic_hire_beyond_workers_requested_rejected
        """
        _, _, jo = _recruiting_j1(workers_requested=1)
        app1 = create_application(jo["id"], applicant_name="Dom One", contact_phone="555-0101")
        decide_application(app1["id"], "HIRE", "QUALIFIED")
        app2 = create_application(jo["id"], applicant_name="Dom Two", contact_phone="555-0102")

        resp = api.decide_domestic_application(
            app2["id"], {"decision": "HIRE", "qualification": "QUALIFIED"}, ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_WORKER_CEILING_EXCEEDED)

        current = get_success_data(api.list_domestic_applications(jo["id"], ADMIN))
        by_name = {a["applicant_name"]: a["status"] for a in current}
        assert by_name == {"Dom One": "HIRED", "Dom Two": "APPLIED"}


class TestStateVersusSafetyPriority:
    def _hired_qualified_application(self, api):
        """J1 RECRUITING, clock 2026-09-01 (inside the preference window), with
        one application already decided HIRE/QUALIFIED."""
        _, _, jo = _recruiting_j1()
        set_clock("2026-09-01T00:00:00Z")
        app = create_application(jo["id"])
        decide_application(app["id"], "HIRE", "QUALIFIED")
        return jo, app

    def test_decide_on_decided_application_reports_state_error(self, api):
        """PRD 2.9: "When a request would violate several rules at once, the server
        evaluates checks in a fixed priority order and reports the earliest
        failure."
        PRD 2.9: "Fifth, the target entity must be in a state that permits the
        operation — the `ERR_JOB_ORDER_INVALID_STATE`, `ERR_PETITION_INVALID_STATE`,
        `ERR_WORKER_INVALID_STATE`, `ERR_ASSIGNMENT_INVALID_STATE`,
        `ERR_APPLICATION_INVALID_STATE`, `ERR_APPOINTMENT_INVALID_STATE`,
        `ERR_TRANSFER_INVALID_STATE`, `ERR_AUDIT_CASE_INVALID_STATE`,
        `ERR_RECONCILIATION_INVALID_STATE`, `ERR_HOUSING_UNIT_INVALID_STATE`, and
        `ERR_HOUSING_ASSIGNMENT_INVALID_STATE` family, together with
        `ERR_GROWER_NOT_ACTIVE` and `ERR_WAGE_DETERMINATION_NOT_PUBLISHED`. Sixth,
        the safety rules of the program run: the domestic-worker preference guard
        (`ERR_DOMESTIC_PREFERENCE_VIOLATION`) and the housing-certification gate
        (`ERR_HOUSING_NOT_CERTIFIED`)."
        PRD 3.3: "The application must still be `APPLIED`; deciding an already
        decided or withdrawn application is rejected with
        `ERR_APPLICATION_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/decide_state_vs_preference_safety_priority
        """
        _, app = self._hired_qualified_application(api)

        # The REJECT of a QUALIFIED in-window applicant would violate the
        # preference guard, but the state check (already decided) runs first.
        resp = api.decide_domestic_application(
            app["id"], {"decision": "REJECT", "qualification": "QUALIFIED"}, ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_APPLICATION_INVALID_STATE)

    def test_decide_on_decided_application_leaves_state_unchanged(self, api):
        """PRD 3.3: "The application must still be `APPLIED`; deciding an already
        decided or withdrawn application is rejected with
        `ERR_APPLICATION_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/decide_state_vs_preference_safety_priority
        """
        jo, app = self._hired_qualified_application(api)
        validate_error(
            api.decide_domestic_application(
                app["id"], {"decision": "REJECT", "qualification": "QUALIFIED"}, ADMIN
            ),
            ApiErrorId.ERR_APPLICATION_INVALID_STATE,
        )
        current = get_success_data(api.list_domestic_applications(jo["id"], ADMIN))
        assert current[0]["id"] == app["id"]
        assert current[0]["status"] == "HIRED"
        assert current[0]["qualification"] == "QUALIFIED"
        assert current[0]["decided_on"] == "2026-09-01"
