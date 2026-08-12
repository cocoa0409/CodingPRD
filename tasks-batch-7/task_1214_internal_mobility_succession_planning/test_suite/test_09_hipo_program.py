"""High-potential program: cycles, nominations, capacity, reviews, close."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS,
    setup_hrbp, setup_talent_manager, setup_manager, setup_report,
    setup_hipo_cycle, nominate, endorse_nomination, enroll_nomination,
    setup_enrolled_nomination,
    make_manager_headers, make_hrbp_headers,
)

ADMIN = TEST_USERS["admin_headers"]


class TestEnrollmentCapacity:
    def _setup_capacity_one_cycle(self, api):
        """Cycle capacity 1; N1 enrolled (seat taken); N2 endorsed and waiting."""
        hrbp, hrbp_headers = setup_hrbp()
        tm, tm_headers = setup_talent_manager()
        manager, _ = setup_manager()
        n1 = setup_report(manager["id"], performance_rating="STRONG",
                          hire_date="2023-01-15")
        n2 = setup_report(manager["id"], performance_rating="STRONG",
                          hire_date="2023-01-15")
        cycle = setup_hipo_cycle(capacity=1, cycle_name="2026-C9")
        nom1 = nominate(cycle["id"], manager["id"], n1["id"])
        endorse_nomination(nom1["id"], hrbp_headers)
        nom1 = enroll_nomination(nom1["id"], tm_headers)
        nom2 = nominate(cycle["id"], manager["id"], n2["id"])
        endorse_nomination(nom2["id"], hrbp_headers)
        return tm_headers, cycle, nom1, nom2

    def test_first_enroll_at_capacity_minus_one_succeeds(self, api):
        """PRD §3.7: "A `TalentManager` enrolls an `ENDORSED` nomination while
        the cycle is `OPEN` and its `enrolled_count` is below `capacity` — at
        capacity the enrollment is rejected with `ERR_PROGRAM_AT_CAPACITY` —
        moving the nomination to `ACTIVE`, raising `enrolled_count` by one, and
        flipping the employee's `is_high_potential` to true."

        Design: Difficulty/boundary_precision_check/hipo_enrollment_capacity_boundary
        """
        tm_headers, cycle, nom1, nom2 = self._setup_capacity_one_cycle(api)
        assert nom1["status"] == "ACTIVE"

        cycle = get_success_data(api.get_hipo_cycle(cycle["id"], tm_headers))
        assert cycle["enrolled_count"] == 1, "the first enroll (0 < 1) fills the seat"

        nom2_after = get_success_data(api.get_nomination(nom2["id"], tm_headers))
        assert nom2_after["status"] == "ENDORSED"

    def test_second_enroll_at_capacity_rejected(self, api):
        """PRD §3.7: "A `TalentManager` enrolls an `ENDORSED` nomination while
        the cycle is `OPEN` and its `enrolled_count` is below `capacity` — at
        capacity the enrollment is rejected with `ERR_PROGRAM_AT_CAPACITY`"

        Design: Difficulty/boundary_precision_check/hipo_enrollment_capacity_boundary
        """
        tm_headers, cycle, nom1, nom2 = self._setup_capacity_one_cycle(api)

        resp = api.enroll_nomination(nom2["id"], tm_headers)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_AT_CAPACITY, 409)

        nom2 = get_success_data(api.get_nomination(nom2["id"], tm_headers))
        assert nom2["status"] == "ENDORSED"
        cycle = get_success_data(api.get_hipo_cycle(cycle["id"], tm_headers))
        assert cycle["enrolled_count"] == 1


class TestReviewCycle:
    def test_hipo_review_cycle_retain_then_remove(self, api):
        """PRD §3.7: "Completing the review takes an `outcome`: `RETAIN`
        returns the nomination to `ACTIVE` and increments `review_count` by
        one; `REMOVE` moves it to `REMOVED`, likewise increments
        `review_count` — every completed review counts — frees the seat by
        lowering `enrolled_count`, and recomputes the employee's
        `is_high_potential`."
        PRD §3.7: "Starting a review moves an `ACTIVE` nomination to
        `UNDER_REVIEW`."

        Design: Corner/state_machines/hipo_review_cycle_retain_then_remove
        """
        ctx = setup_enrolled_nomination(capacity=3, hire_date="2023-01-15")
        tm_headers = ctx["tm_headers"]
        nomination = ctx["nomination"]

        under_review = validate_success(
            api.start_review_nomination(nomination["id"], tm_headers), 200,
        )
        assert under_review["status"] == "UNDER_REVIEW"

        retained = validate_success(api.complete_review_nomination(
            nomination["id"], {"outcome": "RETAIN"}, tm_headers,
        ), 200)
        assert retained["status"] == "ACTIVE"
        assert retained["review_count"] == 1

        cycle = get_success_data(api.get_hipo_cycle(ctx["cycle"]["id"], tm_headers))
        assert cycle["enrolled_count"] == 1, "RETAIN must not free the seat"

        validate_success(api.start_review_nomination(nomination["id"], tm_headers), 200)
        removed = validate_success(api.complete_review_nomination(
            nomination["id"], {"outcome": "REMOVE"}, tm_headers,
        ), 200)
        assert removed["status"] == "REMOVED"
        assert removed["review_count"] == 2

        cycle = get_success_data(api.get_hipo_cycle(ctx["cycle"]["id"], tm_headers))
        assert cycle["enrolled_count"] == 0
        member = get_success_data(api.get_employee(ctx["member"]["id"], ADMIN))
        assert member["is_high_potential"] is False


class TestCycleClose:
    def test_cycle_close_graduates_active_and_rejects_pending(self, api):
        """PRD §3.7: "Closing the cycle — `HRAdmin` only, from `OPEN`,
        otherwise `ERR_CYCLE_INVALID_STATE` — resolves every nomination at
        once: those in `ACTIVE` or `UNDER_REVIEW` graduate to `GRADUATED`,
        those still `NOMINATED` or `ENDORSED` are `REJECTED`, and
        `enrolled_count` recomputes to zero."
        PRD §3.1: "`is_high_potential` is true exactly when the employee holds
        a nomination in `ACTIVE` or `UNDER_REVIEW` status"

        Design: Corner/state_machines/cycle_close_graduates_active_and_rejects_pending
        """
        hrbp, hrbp_headers = setup_hrbp()
        tm, tm_headers = setup_talent_manager()
        manager, _ = setup_manager()
        member_a = setup_report(manager["id"], performance_rating="STRONG",
                                hire_date="2023-01-15")
        member_b = setup_report(manager["id"], performance_rating="STRONG",
                                hire_date="2023-01-15")
        cycle = setup_hipo_cycle(capacity=5, cycle_name="2026-C61")
        nom_a = nominate(cycle["id"], manager["id"], member_a["id"])
        endorse_nomination(nom_a["id"], hrbp_headers)
        enroll_nomination(nom_a["id"], tm_headers)
        nom_b = nominate(cycle["id"], manager["id"], member_b["id"])

        closed = validate_success(api.close_hipo_cycle(cycle["id"], ADMIN), 200)
        assert closed["status"] == "CLOSED"
        assert closed["enrolled_count"] == 0

        nom_a = get_success_data(api.get_nomination(nom_a["id"], ADMIN))
        assert nom_a["status"] == "GRADUATED"
        nom_b = get_success_data(api.get_nomination(nom_b["id"], ADMIN))
        assert nom_b["status"] == "REJECTED"

        member_a = get_success_data(api.get_employee(member_a["id"], ADMIN))
        assert member_a["is_high_potential"] is False, (
            "GRADUATED is neither ACTIVE nor UNDER_REVIEW, so the flag clears"
        )


class TestNominationGuards:
    def test_nominate_into_closed_cycle_returns_cycle_invalid_state(self, api):
        """PRD §3.7: "the checks run in order — the cycle must be `OPEN`
        (otherwise `ERR_CYCLE_INVALID_STATE`), the caller must be the nominee's
        `current_manager_id` (otherwise `ERR_NOT_REPORTING_MANAGER`), the
        nominee's `employment_status` must be `ACTIVE` (otherwise
        `ERR_EMPLOYEE_NOT_ACTIVE`), and the nominee must not already hold a
        non-terminal nomination in this cycle (otherwise
        `ERR_DUPLICATE_NOMINATION`)"

        Design: Corner/validations/nominate_into_closed_cycle_returns_cycle_invalid_state
        """
        manager, _ = setup_manager()
        nominee = setup_report(manager["id"], performance_rating="STRONG",
                               hire_date="2023-01-15")
        cycle = setup_hipo_cycle(capacity=5, cycle_name="2026-C104")
        validate_success(api.close_hipo_cycle(cycle["id"], ADMIN), 200)

        resp = api.create_nomination(
            cycle["id"], {"employee_id": nominee["id"]},
            make_manager_headers(manager["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CYCLE_INVALID_STATE, 409)

        nominations, meta = validate_paginated(
            api.list_nominations(ADMIN, params={"cycle_id": cycle["id"]})
        )
        assert meta["total_count"] == 0

    def test_duplicate_nomination_returns_error(self, api):
        """PRD §3.7: "and the nominee must not already hold a non-terminal
        nomination in this cycle (otherwise `ERR_DUPLICATE_NOMINATION`)"

        Design: Corner/validations/duplicate_nomination_returns_error
        """
        manager, _ = setup_manager()
        nominee = setup_report(manager["id"], performance_rating="STRONG",
                               hire_date="2023-01-15")
        cycle = setup_hipo_cycle(capacity=5, cycle_name="2026-C95")
        nominate(cycle["id"], manager["id"], nominee["id"])

        resp = api.create_nomination(
            cycle["id"], {"employee_id": nominee["id"]},
            make_manager_headers(manager["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_NOMINATION, 409)

    def test_enroll_unendorsed_nomination_returns_nomination_invalid_state(self, api):
        """PRD §3.7: "A `TalentManager` enrolls an `ENDORSED` nomination while
        the cycle is `OPEN`"
        PRD §3.7: "Both review actions require `UNDER_REVIEW` status, and any
        nomination transition attempted from the wrong status is rejected with
        `ERR_NOMINATION_INVALID_STATE`."

        Design: Corner/validations/enroll_unendorsed_nomination_returns_nomination_invalid_state
        """
        _, tm_headers = setup_talent_manager()
        manager, _ = setup_manager()
        nominee = setup_report(manager["id"], performance_rating="STRONG",
                               hire_date="2023-01-15")
        cycle = setup_hipo_cycle(capacity=5, cycle_name="2026-C105")
        nomination = nominate(cycle["id"], manager["id"], nominee["id"])
        assert nomination["status"] == "NOMINATED"

        resp = api.enroll_nomination(nomination["id"], tm_headers)
        validate_error(resp, ApiErrorId.ERR_NOMINATION_INVALID_STATE, 409)

        nomination = get_success_data(api.get_nomination(nomination["id"], tm_headers))
        assert nomination["status"] == "NOMINATED"
        cycle = get_success_data(api.get_hipo_cycle(cycle["id"], tm_headers))
        assert cycle["enrolled_count"] == 0


class TestProgramRbacAndSegregation:
    def test_manager_cannot_endorse_nomination(self, api):
        """PRD §2.1: "Access to specific operations is restricted by role: an
        attempt to perform an action outside of the caller's designated role is
        rejected with an `ERR_UNAUTHORIZED` error (HTTP 403)."
        PRD §2.8: "Every request passes through a fixed validation pipeline,
        and a request that violates several checks is rejected by the earliest
        applicable one."
        PRD §2.8: "2. Role authorization for the endpoint — failure yields
        `ERR_UNAUTHORIZED`."
        PRD §2.8: "7. Segregation-of-duties rules — failure yields
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/manager_cannot_endorse_nomination
        """
        manager, _ = setup_manager()
        nominee = setup_report(manager["id"], performance_rating="STRONG",
                               hire_date="2023-01-15")
        cycle = setup_hipo_cycle(capacity=5, cycle_name="2026-C121")
        nomination = nominate(cycle["id"], manager["id"], nominee["id"])

        resp = api.endorse_nomination(
            nomination["id"], make_manager_headers(manager["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)

    def test_hrbp_cannot_enroll_nomination(self, api):
        """PRD §2.1: "Access to specific operations is restricted by role: an
        attempt to perform an action outside of the caller's designated role is
        rejected with an `ERR_UNAUTHORIZED` error (HTTP 403)."
        PRD §3.7: "Enrollment turns endorsement into membership. A
        `TalentManager` enrolls an `ENDORSED` nomination"

        Design: Corner/rbac/hrbp_cannot_enroll_nomination
        """
        hrbp, hrbp_headers = setup_hrbp()
        manager, _ = setup_manager()
        nominee = setup_report(manager["id"], performance_rating="STRONG",
                               hire_date="2023-01-15")
        cycle = setup_hipo_cycle(capacity=5, cycle_name="2026-C122")
        nomination = nominate(cycle["id"], manager["id"], nominee["id"])
        endorse_nomination(nomination["id"], hrbp_headers)

        resp = api.enroll_nomination(nomination["id"], hrbp_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)

        nomination = get_success_data(api.get_nomination(nomination["id"], ADMIN))
        assert nomination["status"] == "ENDORSED"

    def test_hipo_endorse_by_nominator_returns_segregation_of_duties(self, api):
        """PRD §2.10: "In the high-potential program, the HR business partner
        endorsing a nomination must not be the manager who nominated the
        employee. In calibration, the facilitator ratifying an entry must not
        be the manager who proposed the rating. Either violation is rejected
        with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409)."
        PRD §3.7: "if `X-User-ID` equals `nominated_by_manager_id`, the
        endorsement is rejected with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/hipo_endorse_by_nominator_returns_segregation_of_duties
        """
        manager, _ = setup_manager()
        nominee = setup_report(manager["id"], performance_rating="STRONG",
                               hire_date="2023-01-15")
        cycle = setup_hipo_cycle(capacity=5, cycle_name="2026-C123")
        nomination = nominate(cycle["id"], manager["id"], nominee["id"])

        resp = api.endorse_nomination(
            nomination["id"], make_hrbp_headers(manager["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 409)

        nomination = get_success_data(api.get_nomination(nomination["id"], ADMIN))
        assert nomination["status"] == "NOMINATED"
        assert nomination["endorsed_by_id"] is None
