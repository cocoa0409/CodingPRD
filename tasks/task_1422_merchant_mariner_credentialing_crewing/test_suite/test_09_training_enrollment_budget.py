"""Training courses, enrollment lifecycle, budget reservation arithmetic,
no-show strikes, and reimbursement settlement."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    approve_enrollment,
    budget_rows,
    create_activated_mariner,
    create_course,
    create_union_hall,
    create_union_registration_payload,
    enroll_enrollment,
    first_budget_row,
    get_course,
    get_enrollment,
    get_mariner,
    make_fleet_admin_headers,
    make_mariner_headers,
    make_union_dispatcher_headers,
    request_enrollment,
    setup_enrolled_enrollment,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["fleet_admin_headers"]
CREWING = TEST_USERS["crewing_headers"]


class TestReimbursementDualVariant:

    def _setup_completed(self, *, cost_cents=250_000, hire_channel="DIRECT",
                         mariner_overrides=None, course_overrides=None):
        overrides = {"cost_cents": cost_cents}
        overrides.update(course_overrides or {})
        ctx = setup_enrolled_enrollment(
            course_overrides=overrides,
            mariner_overrides={"hire_channel": hire_channel,
                               **(mariner_overrides or {})})
        completed = validate_success(
            api_client.record_enrollment_completion(
                ctx["enrollment"]["id"], {"outcome": "COMPLETED"}, ADMIN))
        return {**ctx, "enrollment": completed}

    def test_reimbursement_provisional_vs_final_receipt_amounts(self):
        """PRD section 3.9: "The provisional reservation is computed in a
        pinned order: the course's `cost_cents` is first capped at the
        per-course maximum of 200,000 cents (two thousand dollars); the
        channel percentage is then applied — 100 percent for a `UNION_HALL`
        `channel_snapshot`, 80 percent for `DIRECT`; and the product is
        rounded half-up to whole cents as `provisional_amount_cents`."
        PRD section 3.9: "The final `reimbursed_amount_cents` is the lesser of
        the supplied `receipt_amount_cents` and the `provisional_amount_cents`"

        Design: Difficulty/dual_variant_calc/training_reimbursement_provisional_vs_final_receipt
        """
        ctx = self._setup_completed()
        enrollment = ctx["enrollment"]
        assert enrollment["provisional_amount_cents"] == 160000, \
            "provisional: min(250000, 200000) x 0.80 DIRECT"

        reimbursed = validate_success(
            api_client.reimburse_enrollment(
                enrollment["id"], {"receipt_amount_cents": 150000},
                make_fleet_admin_headers("fa-900")))
        assert reimbursed["reimbursed_amount_cents"] == 150000, \
            "final: min(receipt 150000, provisional 160000)"

        budget = first_budget_row(ctx["mariner"]["id"])
        assert budget["used_cents"] == 150000
        assert budget["reserved_cents"] == 0, \
            "full 160000 reservation released; the 10000 delta is returned"
        assert budget["available_cents"] == 350000, \
            "500000 - 150000 used - 0 reserved"

    def test_reimbursement_provisional_caps_receipt_above_it(self):
        """PRD section 3.9: "The final `reimbursed_amount_cents` is the lesser
        of the supplied `receipt_amount_cents` and the
        `provisional_amount_cents`; the budget's `used_cents` grows by the
        reimbursed amount while `reserved_cents` is reduced by the full
        provisional amount, releasing any unreimbursed remainder."

        Design: Difficulty/dual_variant_calc/training_reimbursement_provisional_vs_final_receipt
        """
        ctx = self._setup_completed()
        enrollment = ctx["enrollment"]
        assert enrollment["provisional_amount_cents"] == 160000

        reimbursed = validate_success(
            api_client.reimburse_enrollment(
                enrollment["id"], {"receipt_amount_cents": 200000},
                make_fleet_admin_headers("fa-900")))
        assert reimbursed["reimbursed_amount_cents"] == 160000, \
            "a receipt above the provisional settles at the provisional"

        budget = first_budget_row(ctx["mariner"]["id"])
        assert budget["used_cents"] == 160000
        assert budget["reserved_cents"] == 0
        assert budget["available_cents"] == 340000


class TestChannelBranchNesting:

    def _setup_pair(self):
        """UNION_HALL and DIRECT mariners, both ENROLLED on the same
        180000-cent course (below the per-course cap)."""
        course = create_course(cost_cents=180_000)
        mu = create_activated_mariner(hire_channel="UNION_HALL")
        md = create_activated_mariner(hire_channel="DIRECT")
        eu = request_enrollment(course["id"], mu["id"])
        ed = request_enrollment(course["id"], md["id"])
        approve_enrollment(eu["id"], approver_id="cm-400")
        approve_enrollment(ed["id"], approver_id="cm-400")
        return course, mu, md, enroll_enrollment(eu["id"]), \
            enroll_enrollment(ed["id"])

    def test_channel_snapshot_drives_provisional_amount(self):
        """PRD section 3.9: "the channel percentage is then applied — 100
        percent for a `UNION_HALL` `channel_snapshot`, 80 percent for
        `DIRECT`; and the product is rounded half-up to whole cents as
        `provisional_amount_cents`."
        PRD section 3.9: "it snapshots the mariner's current `hire_channel`
        into `channel_snapshot`, which later drives the reimbursement
        percentage"

        Design: Difficulty/combinatorial_formula/reimbursement_min_nesting_with_channel_branch
        """
        _, _, _, eu, ed = self._setup_pair()
        assert eu["channel_snapshot"] == "UNION_HALL"
        assert ed["channel_snapshot"] == "DIRECT"
        assert eu["provisional_amount_cents"] == 180000, \
            "min(180000, 200000) x 1.00 UNION_HALL"
        assert ed["provisional_amount_cents"] == 144000, \
            "min(180000, 200000) x 0.80 DIRECT"

    def test_channel_branch_bites_again_at_reimbursement(self):
        """PRD section 3.9: "The final `reimbursed_amount_cents` is the lesser
        of the supplied `receipt_amount_cents` and the
        `provisional_amount_cents`"

        Design: Difficulty/combinatorial_formula/reimbursement_min_nesting_with_channel_branch
        """
        _, _, _, eu, ed = self._setup_pair()
        for enrollment in (eu, ed):
            validate_success(
                api_client.record_enrollment_completion(
                    enrollment["id"], {"outcome": "COMPLETED"}, ADMIN))
        # Identical receipt above both provisionals: the channel branch is
        # the sole reason the settlements diverge.
        ru = validate_success(
            api_client.reimburse_enrollment(
                eu["id"], {"receipt_amount_cents": 190000},
                make_fleet_admin_headers("fa-901")))
        rd = validate_success(
            api_client.reimburse_enrollment(
                ed["id"], {"receipt_amount_cents": 190000},
                make_fleet_admin_headers("fa-901")))
        assert ru["reimbursed_amount_cents"] == 180000, \
            "min(190000 receipt, 180000 provisional) — the provisional cap bites"
        assert rd["reimbursed_amount_cents"] == 144000, \
            "min(190000, 144000) — the channel branch bites twice"


class TestCourseFullBoundary:

    def _setup_one_seat_course(self):
        course = create_course(seat_capacity=1)
        m1 = create_activated_mariner()
        m2 = create_activated_mariner()
        e1 = request_enrollment(course["id"], m1["id"])
        approve_enrollment(e1["id"], approver_id="cm-410")
        e2 = request_enrollment(course["id"], m2["id"])
        approve_enrollment(e2["id"], approver_id="cm-410")
        return course, m1, m2, e1, e2

    def test_course_full_at_zero_open_seats(self):
        """PRD section 3.9: "Enrollment proper — a `FleetAdmin` action moving
        `APPROVED` to `ENROLLED` (else `ERR_INVALID_STATE`) — requires the
        course still `SCHEDULED` (else `ERR_COURSE_NOT_SCHEDULED`), the
        mariner's posture not `BLOCKED` (else `ERR_MARINER_NOT_CLEAR`), at
        least one open seat (else `ERR_COURSE_FULL`), and budget headroom."
        PRD section 3.9: "its `seats_open` is the `seat_capacity` minus
        `seats_reserved`"

        Design: Difficulty/boundary_precision_check/course_full_at_zero_open_seats
        """
        course, _, _, e1, e2 = self._setup_one_seat_course()
        enroll_enrollment(e1["id"])
        probed = get_course(course["id"])
        assert probed["seats_reserved"] == 1 and probed["seats_open"] == 0, \
            "exactly zero open seats after the first enroll"

        resp = api_client.enroll_enrollment(e2["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_COURSE_FULL)

    def test_seat_release_reopens_enroll(self):
        """PRD section 3.9: "cancelling from `ENROLLED` releases both the seat
        (`seats_reserved` reduced by one) and the budget reservation
        (`reserved_cents` reduced by `provisional_amount_cents`)"

        Design: Difficulty/boundary_precision_check/course_full_at_zero_open_seats
        """
        course, _, _, e1, e2 = self._setup_one_seat_course()
        enroll_enrollment(e1["id"])
        validate_success(api_client.cancel_enrollment(e1["id"], CREWING))
        probed = get_course(course["id"])
        assert probed["seats_reserved"] == 0 and probed["seats_open"] == 1

        enrolled = enroll_enrollment(e2["id"])
        assert enrolled["status"] == "ENROLLED", \
            "the released seat admits the waiting enrollment"


class TestSeatLedgerConservation:

    def _setup_two_seat_course(self):
        course = create_course(seat_capacity=2)
        m1, m2, m3 = (create_activated_mariner() for _ in range(3))
        e1 = request_enrollment(course["id"], m1["id"])
        approve_enrollment(e1["id"], approver_id="cm-420")
        e2 = request_enrollment(course["id"], m2["id"])
        approve_enrollment(e2["id"], approver_id="cm-420")
        return course, m1, m2, m3, e1, e2

    def test_enroll_cancel_pair_restores_seat_ledger(self):
        """PRD section 3.9: "A course is created `SCHEDULED` with
        `seats_reserved` zero; its `seats_open` is the `seat_capacity` minus
        `seats_reserved`, where `seats_reserved` counts enrollments in
        `ENROLLED`, `COMPLETED`, `NO_SHOW`, or `REIMBURSED` status."
        PRD section 3.9: "cancelling from `ENROLLED` releases both the seat
        (`seats_reserved` reduced by one) and the budget reservation
        (`reserved_cents` reduced by `provisional_amount_cents`)"

        Design: Difficulty/compensating_invariant/seat_ledger_enroll_cancel_conservation
        """
        course, _, m2, _, e1, e2 = self._setup_two_seat_course()
        enroll_enrollment(e1["id"])
        enroll_enrollment(e2["id"])
        probed = get_course(course["id"])
        assert probed["seats_reserved"] == 2 and probed["seats_open"] == 0, \
            "invariant: 2 + 0 == seat_capacity 2"

        cancelled = validate_success(
            api_client.cancel_enrollment(e2["id"], CREWING))
        assert cancelled["status"] == "CANCELLED"
        probed = get_course(course["id"])
        assert probed["seats_reserved"] == 1 and probed["seats_open"] == 1, \
            "the forward/compensating pair returns the ledger to its pre-pair value"
        budget = first_budget_row(m2["id"])
        assert budget["reserved_cents"] == 0, \
            "M2's 80000 provisional reservation fully released"

    def test_replacement_enroll_refills_seat(self):
        """PRD section 3.9: "at which point `reserved_cents` grows by the
        provisional amount and the course's `seats_reserved` grows by one."

        Design: Difficulty/compensating_invariant/seat_ledger_enroll_cancel_conservation
        """
        course, _, _, m3, e1, e2 = self._setup_two_seat_course()
        enroll_enrollment(e1["id"])
        enroll_enrollment(e2["id"])
        validate_success(api_client.cancel_enrollment(e2["id"], CREWING))

        e3 = request_enrollment(course["id"], m3["id"])
        approve_enrollment(e3["id"], approver_id="cm-420")
        enroll_enrollment(e3["id"])
        probed = get_course(course["id"])
        assert probed["seats_reserved"] == 2 and probed["seats_open"] == 0, \
            "the replacement enroll re-fills the seat; the invariant holds again"


class TestBudgetReserveReleaseConservation:

    def test_no_show_restores_available_exactly(self):
        """PRD section 3.9: "A no-show releases the budget reservation
        (`reserved_cents` reduced by `provisional_amount_cents`) but
        deliberately does not release the seat — `seats_reserved` is unchanged"

        Design: Difficulty/compensating_invariant/budget_reserve_release_conservation
        """
        ctx = setup_enrolled_enrollment(course_overrides={"cost_cents": 250_000})
        enrollment = ctx["enrollment"]
        assert enrollment["provisional_amount_cents"] == 160000
        budget = first_budget_row(ctx["mariner"]["id"])
        assert budget["reserved_cents"] == 160000
        assert budget["available_cents"] == 340000, \
            "forward action: 500000 - 160000 reserved"

        no_show = validate_success(
            api_client.record_enrollment_completion(
                enrollment["id"], {"outcome": "NO_SHOW"}, ADMIN))
        assert no_show["status"] == "NO_SHOW"

        budget = first_budget_row(ctx["mariner"]["id"])
        assert budget["reserved_cents"] == 0
        assert budget["used_cents"] == 0
        assert budget["available_cents"] == 500000, \
            "available restored EXACTLY to the cap — no drift"

    def test_no_show_keeps_seat_and_adds_strike(self):
        """PRD section 3.9: "A no-show releases the budget reservation
        (`reserved_cents` reduced by `provisional_amount_cents`) but
        deliberately does not release the seat — `seats_reserved` is unchanged
        — and increments the mariner's `no_show_strike_count` by one"

        Design: Difficulty/compensating_invariant/budget_reserve_release_conservation
        """
        ctx = setup_enrolled_enrollment(course_overrides={"cost_cents": 250_000})
        validate_success(
            api_client.record_enrollment_completion(
                ctx["enrollment"]["id"], {"outcome": "NO_SHOW"}, ADMIN))

        course = get_course(ctx["course"]["id"])
        assert course["seats_reserved"] == 1, \
            "asymmetry: the NO_SHOW seat is retained while budget is compensated"
        mariner = get_mariner(ctx["mariner"]["id"])
        assert mariner["no_show_strike_count"] == 1


class TestNoShowStrikeCascade:

    def _setup_strikes(self):
        """Mariner with: eD ENROLLED then NO_SHOW (strike 1); eA ENROLLED;
        eB REQUESTED; eC APPROVED."""
        mariner = create_activated_mariner()
        cd = create_course(course_code="STRIKE-D")
        ca = create_course(course_code="STRIKE-A",
                           start_date="2026-09-10T00:00:00Z",
                           end_date="2026-09-12T00:00:00Z")
        cb = create_course(course_code="STRIKE-B",
                           start_date="2026-10-01T00:00:00Z",
                           end_date="2026-10-03T00:00:00Z")
        cc = create_course(course_code="STRIKE-C",
                           start_date="2026-10-10T00:00:00Z",
                           end_date="2026-10-12T00:00:00Z")

        ed = request_enrollment(cd["id"], mariner["id"])
        approve_enrollment(ed["id"], approver_id="cm-430")
        enroll_enrollment(ed["id"])
        first = validate_success(
            api_client.record_enrollment_completion(
                ed["id"], {"outcome": "NO_SHOW"}, ADMIN))
        assert first["status"] == "NO_SHOW", "first strike applied"

        ea = request_enrollment(ca["id"], mariner["id"])
        approve_enrollment(ea["id"], approver_id="cm-430")
        ea = enroll_enrollment(ea["id"])
        eb = request_enrollment(cb["id"], mariner["id"])
        ec = request_enrollment(cc["id"], mariner["id"])
        approve_enrollment(ec["id"], approver_id="cm-430")
        return {"mariner": mariner, "ca": ca, "ea": ea, "eb": eb, "ec": ec}

    def test_first_no_show_releases_reservation_keeps_seat(self):
        """PRD section 3.9: "A no-show releases the budget reservation
        (`reserved_cents` reduced by `provisional_amount_cents`) but
        deliberately does not release the seat — `seats_reserved` is unchanged
        — and increments the mariner's `no_show_strike_count` by one"

        Design: Difficulty/transitive_cascade/no_show_strike_privileges_cascade
        """
        mariner = create_activated_mariner()
        course = create_course()
        enrollment = request_enrollment(course["id"], mariner["id"])
        approve_enrollment(enrollment["id"], approver_id="cm-430")
        enrolled = enroll_enrollment(enrollment["id"])
        assert enrolled["provisional_amount_cents"] == 80000, \
            "min(100000, 200000) x 0.80 DIRECT"

        no_show = validate_success(
            api_client.record_enrollment_completion(
                enrolled["id"], {"outcome": "NO_SHOW"}, ADMIN))
        assert no_show["status"] == "NO_SHOW"

        probed_mariner = get_mariner(mariner["id"])
        assert probed_mariner["no_show_strike_count"] == 1
        assert probed_mariner["training_privileges"] == "ENABLED", \
            "one strike does not yet suspend privileges"
        budget = first_budget_row(mariner["id"])
        assert budget["reserved_cents"] == 0 and budget["used_cents"] == 0
        assert get_course(course["id"])["seats_reserved"] == 1

    def test_second_strike_suspends_privileges_and_cascades(self):
        """PRD section 3.9: "at two strikes, the mariner's
        `training_privileges` flip to `SUSPENDED`, and all of the mariner's
        `REQUESTED` enrollments cascade to `REJECTED` while all `APPROVED`
        enrollments cascade to `CANCELLED`."

        Design: Difficulty/transitive_cascade/no_show_strike_privileges_cascade
        """
        ctx = self._setup_strikes()
        ea_status = validate_success(
            api_client.record_enrollment_completion(
                ctx["ea"]["id"], {"outcome": "NO_SHOW"}, ADMIN))
        assert ea_status["status"] == "NO_SHOW"

        mariner = get_mariner(ctx["mariner"]["id"])
        assert mariner["no_show_strike_count"] == 2
        assert mariner["training_privileges"] == "SUSPENDED", \
            "the strike threshold at 2 suspends privileges"

        eb = get_enrollment(ctx["eb"]["id"])
        ec = get_enrollment(ctx["ec"]["id"])
        assert eb["status"] == "REJECTED", "REQUESTED cascades to REJECTED"
        assert ec["status"] == "CANCELLED", "APPROVED cascades to CANCELLED"

        budget = first_budget_row(ctx["mariner"]["id"])
        assert budget["reserved_cents"] == 0 and budget["used_cents"] == 0, \
            "both NO_SHOW reservations fully released; nothing reimbursed"
        assert get_course(ctx["ca"]["id"])["seats_reserved"] == 1, \
            "the NO_SHOW course keeps its seat"


class TestEnrollmentCreationGates:

    def test_enrollment_privileges_suspended_rejected(self):
        """PRD section 3.9: "Creation requires the course to be `SCHEDULED`
        (else `ERR_COURSE_NOT_SCHEDULED`), the mariner's `status` to be
        `ACTIVE` (else `ERR_MARINER_NOT_ACTIVE`), the mariner's
        `training_privileges` to be `ENABLED` (else
        `ERR_TRAINING_PRIVILEGES_SUSPENDED`)"

        Design: Corner/state_machines/enrollment_privileges_suspended_rejected
        """
        mariner = create_activated_mariner()
        for code in ("PRIV-P1", "PRIV-P2"):
            course = create_course(course_code=code, cost_cents=50_000)
            enrollment = request_enrollment(course["id"], mariner["id"])
            approve_enrollment(enrollment["id"], approver_id="cm-440")
            enroll_enrollment(enrollment["id"])
            validate_success(
                api_client.record_enrollment_completion(
                    enrollment["id"], {"outcome": "NO_SHOW"}, ADMIN))
        mariner = get_mariner(mariner["id"])
        assert mariner["no_show_strike_count"] == 2
        assert mariner["training_privileges"] == "SUSPENDED"

        p3 = create_course(course_code="PRIV-P3", cost_cents=50_000,
                           start_date="2026-10-01T00:00:00Z",
                           end_date="2026-10-02T00:00:00Z")
        resp = api_client.request_enrollment(
            p3["id"], make_mariner_headers(mariner["id"]))
        validate_error(resp, ApiErrorId.ERR_TRAINING_PRIVILEGES_SUSPENDED)

    def test_enrollment_on_cancelled_course_rejected(self):
        """PRD section 3.9: "Creation requires the course to be `SCHEDULED`
        (else `ERR_COURSE_NOT_SCHEDULED`)"

        Design: Corner/errors/enrollment_on_cancelled_course_rejected
        """
        mariner = create_activated_mariner()
        course = create_course()
        validate_success(api_client.cancel_course(course["id"], ADMIN))
        resp = api_client.request_enrollment(
            course["id"], make_mariner_headers(mariner["id"]))
        validate_error(resp, ApiErrorId.ERR_COURSE_NOT_SCHEDULED)

    def test_enrollment_by_suspended_mariner_rejected(self):
        """PRD section 3.9: "the mariner's `status` to be `ACTIVE` (else
        `ERR_MARINER_NOT_ACTIVE`)"

        Design: Corner/errors/enrollment_by_suspended_mariner_rejected
        """
        mariner = create_activated_mariner()
        validate_success(api_client.suspend_mariner(mariner["id"], ADMIN))
        course = create_course()
        resp = api_client.request_enrollment(
            course["id"], make_mariner_headers(mariner["id"]))
        validate_error(resp, ApiErrorId.ERR_MARINER_NOT_ACTIVE)

    def test_duplicate_enrollment_rejected(self):
        """PRD section 3.9: "no other open enrollment for the same mariner and
        course in `REQUESTED`, `APPROVED`, `ENROLLED`, or `COMPLETED` status
        (else `ERR_DUPLICATE_ENROLLMENT`)"

        Design: Corner/errors/duplicate_enrollment_rejected
        """
        mariner = create_activated_mariner()
        course = create_course()
        first = request_enrollment(course["id"], mariner["id"])
        assert first["status"] == "REQUESTED"
        resp = api_client.request_enrollment(
            course["id"], make_mariner_headers(mariner["id"]))
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ENROLLMENT)


class TestBudgetExceedanceAndCourseCancel:

    def test_budget_exceeded_pure_fiscal_rejected(self):
        """PRD section 3.9: "`available_cents` must be at least the
        `provisional_amount_cents`, else `ERR_TRAINING_BUDGET_EXCEEDED`
        (HTTP 402). The budget row is persisted only on a successful enroll —
        auto-created when absent with `annual_cap_cents` copied from the
        mariner's `annual_training_cap_cents`"

        Design: Corner/errors/budget_exceeded_pure_fiscal_rejected
        """
        mariner = create_activated_mariner(annual_training_cap_cents=1000)
        course = create_course(cost_cents=250_000)
        enrollment = request_enrollment(course["id"], mariner["id"])
        approve_enrollment(enrollment["id"], approver_id="cm-450")

        resp = api_client.enroll_enrollment(enrollment["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_TRAINING_BUDGET_EXCEEDED)

        assert budget_rows(mariner["id"]) == [], \
            "no budget row may be persisted on a failed enroll"
        assert get_enrollment(enrollment["id"])["status"] == "APPROVED"
        assert get_course(course["id"])["seats_reserved"] == 0

    def test_course_cancel_cascades_enrollments(self):
        """PRD section 3.9: "Cancelling a course — a `FleetAdmin` action
        requiring `SCHEDULED` (else `ERR_COURSE_NOT_SCHEDULED`) — moves it to
        the terminal `CANCELLED` and cascades: `REQUESTED` enrollments move to
        `REJECTED`, `APPROVED` enrollments move to `CANCELLED` with no budget
        effect, and `ENROLLED` enrollments move to `CANCELLED`, each releasing
        its budget reservation (the budget's `reserved_cents` reduced by that
        enrollment's `provisional_amount_cents`) and its seat
        (`seats_reserved` reduced by one)."

        Design: Corner/state_machines/course_cancel_cascades_enrollments
        """
        course = create_course(seat_capacity=3)
        m1, m2, m3 = (create_activated_mariner() for _ in range(3))
        e1 = request_enrollment(course["id"], m1["id"])
        approve_enrollment(e1["id"], approver_id="cm-460")
        enroll_enrollment(e1["id"])
        e2 = request_enrollment(course["id"], m2["id"])
        approve_enrollment(e2["id"], approver_id="cm-460")
        e3 = request_enrollment(course["id"], m3["id"])

        cancelled = validate_success(api_client.cancel_course(course["id"],
                                                              ADMIN))
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["seats_reserved"] == 0, "the ENROLLED seat released"

        assert get_enrollment(e1["id"])["status"] == "CANCELLED"
        assert first_budget_row(m1["id"])["reserved_cents"] == 0, \
            "the ENROLLED budget reservation released"
        assert get_enrollment(e2["id"])["status"] == "CANCELLED", \
            "APPROVED branch"
        assert get_enrollment(e3["id"])["status"] == "REJECTED", \
            "REQUESTED branch"


class TestDuplicateRegistration:

    def test_duplicate_registration_rejected(self):
        """PRD section 3.7: "The registration is created `REGISTERED` with
        `dues_current_until` initialized to the `seniority_date`, and a second
        non-`SUSPENDED` registration for the same hall and mariner is
        `ERR_DUPLICATE_REGISTRATION`."

        Design: Corner/errors/duplicate_registration_rejected
        """
        hall = create_union_hall()
        mariner = create_activated_mariner(hire_channel="UNION_HALL")
        dispatcher = make_union_dispatcher_headers(hall["id"])
        first = validate_success(
            api_client.create_union_registration(
                hall["id"],
                create_union_registration_payload(mariner["id"]),
                dispatcher),
            expected_status=201)
        assert first["status"] == "REGISTERED"

        resp = api_client.create_union_registration(
            hall["id"],
            create_union_registration_payload(
                mariner["id"], seniority_date="2026-02-01T00:00:00Z"),
            dispatcher)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_REGISTRATION)
