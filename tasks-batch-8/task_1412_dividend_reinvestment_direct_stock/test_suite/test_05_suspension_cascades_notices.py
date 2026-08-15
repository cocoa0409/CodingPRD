"""Plan suspension cascades, resume asymmetry, and plan notices."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_active_plan,
    create_notice,
    get_enrollment,
    get_order,
    get_plan,
    get_success_data,
    get_window,
    list_notices,
    make_participant_headers,
    register_participant,
    set_clock,
    setup_active_enrollment,
    setup_open_window_scenario,
    submit_order_ok,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def _setup_plan_with_open_order():
    """ACTIVE plan + ACTIVE enrollment + OPEN window holding one SUBMITTED
    12000-cent order. Returns (plan, participant, enrollment, window, order)."""
    plan, participant, enrollment, window = setup_open_window_scenario(
        plan_overrides={"issuer_name": "Susp Corp", "ticker": "SUS",
                        "name": "SUS DRIP"},
        participant_email="ps@x.com")
    order = submit_order_ok(window["id"], enrollment["id"], participant["id"],
                            12000)
    return plan, participant, enrollment, window, order


class TestPlanSuspendCascade:
    def test_plan_suspend_cascades_enrollment_and_order(self, api):
        """PRD §3.7: "Every `ACTIVE` enrollment of the plan moves to
        `SUSPENDED`, each such enrollment's still-`SUBMITTED` purchase orders
        move to `REJECTED`, and each rejection removes the order's amount from
        its window's `submitted_total_cents`."

        Design: Difficulty/transitive_cascade/plan_suspend_cascades_enrollment_order_window
        """
        plan, _p, enrollment, _window, order = _setup_plan_with_open_order()
        suspended = validate_success(api.suspend_plan(plan["id"], ADMIN))
        assert suspended["status"] == "SUSPENDED"
        assert get_enrollment(enrollment["id"])["status"] == "SUSPENDED", \
            "link 1: plan suspension suspends the ACTIVE enrollment"
        assert get_order(order["id"])["status"] == "REJECTED", \
            "link 2: the suspended enrollment's SUBMITTED order is rejected"

    def test_plan_suspend_reconciles_window_total(self, api):
        """PRD §3.7: "Every `ACTIVE` enrollment of the plan moves to
        `SUSPENDED`, each such enrollment's still-`SUBMITTED` purchase orders
        move to `REJECTED`, and each rejection removes the order's amount from
        its window's `submitted_total_cents`."
        PRD §3.5: "A new order starts `SUBMITTED`, and its amount is added to
        the window's `submitted_total_cents`, a derived figure reconciled on
        every order mutation."

        Design: Difficulty/transitive_cascade/plan_suspend_cascades_enrollment_order_window
        """
        plan, _p, _enrollment, window, _order = _setup_plan_with_open_order()
        assert get_window(window["id"])["submitted_total_cents"] == 12000
        get_success_data(api.suspend_plan(plan["id"], ADMIN))
        assert get_window(window["id"])["submitted_total_cents"] == 0, \
            "link 3: the rejection releases the order amount from the window total"


class TestEnrollmentSuspensionCycle:
    def test_enrollment_suspension_cycle_single_loop(self, api):
        """PRD §3.7: "Every `ACTIVE` enrollment of the plan moves to
        `SUSPENDED`, each such enrollment's still-`SUBMITTED` purchase orders
        move to `REJECTED`, and each rejection removes the order's amount from
        its window's `submitted_total_cents`."
        PRD §3.7: "Resumption moves a `SUSPENDED` plan back to `ACTIVE` and
        restores every `SUSPENDED` enrollment of the plan to `ACTIVE`."

        Design: Difficulty/non_linear_state_machine/enrollment_suspension_cycle_via_plan
        """
        plan, _participant, enrollment = setup_active_enrollment(
            plan_overrides={"issuer_name": "Loop Corp", "ticker": "LOOP",
                            "name": "LOOP DRIP"},
            participant_email="pl@x.com")
        get_success_data(api.suspend_plan(plan["id"], ADMIN))
        assert get_enrollment(enrollment["id"])["status"] == "SUSPENDED"
        get_success_data(api.resume_plan(plan["id"], ADMIN))
        assert get_enrollment(enrollment["id"])["status"] == "ACTIVE"

    def test_enrollment_suspension_cycle_two_loops(self, api):
        """PRD §3.7: "Resumption moves a `SUSPENDED` plan back to `ACTIVE` and
        restores every `SUSPENDED` enrollment of the plan to `ACTIVE`."
        PRD §3.7: "Suspension — whether invoked directly by an administrator or
        delivered through a `SUSPENSION` notice — moves an `ACTIVE` plan to
        `SUSPENDED` and cascades."

        Design: Difficulty/non_linear_state_machine/enrollment_suspension_cycle_via_plan
        """
        plan, _participant, enrollment = setup_active_enrollment(
            plan_overrides={"issuer_name": "Loop Corp", "ticker": "LOOP",
                            "name": "LOOP DRIP"},
            participant_email="pl@x.com")
        observed = []
        for _ in range(2):
            get_success_data(api.suspend_plan(plan["id"], ADMIN))
            observed.append(get_enrollment(enrollment["id"])["status"])
            get_success_data(api.resume_plan(plan["id"], ADMIN))
            observed.append(get_enrollment(enrollment["id"])["status"])
        assert observed == ["SUSPENDED", "ACTIVE", "SUSPENDED", "ACTIVE"], (
            "the enrollment cycle is driven purely by the plan cycle, twice")


class TestResumeAsymmetry:
    def test_resume_does_not_restore_rejected_orders(self, api):
        """PRD §3.7: "The compensation is deliberately asymmetric: orders
        rejected by the suspension are not restored and remain `REJECTED`."
        PRD §3.7: "Resumption moves a `SUSPENDED` plan back to `ACTIVE` and
        restores every `SUSPENDED` enrollment of the plan to `ACTIVE`."

        Design: Corner/state_machines/resume_does_not_restore_rejected_orders
        """
        plan, _p, enrollment, window, order = _setup_plan_with_open_order()
        get_success_data(api.suspend_plan(plan["id"], ADMIN))
        get_success_data(api.resume_plan(plan["id"], ADMIN))

        assert get_plan(plan["id"])["status"] == "ACTIVE"
        assert get_enrollment(enrollment["id"])["status"] == "ACTIVE"
        assert get_order(order["id"])["status"] == "REJECTED", \
            "rejected orders are not restored by resumption"
        assert get_window(window["id"])["submitted_total_cents"] == 0


class TestNoticeTakeEffect:
    def test_notice_take_effect_suspension_drives_plan(self, api):
        """PRD §3.7: "Once the clock reaches `effective_at`, the administrator
        takes the notice into effect, moving it from `PUBLISHED` to `EFFECTIVE`.
        What happens then depends on the type: a `SUSPENSION` notice drives the
        plan's `ACTIVE` → `SUSPENDED` transition with its full cascade
        (guarded — the plan must be `ACTIVE`)"

        Design: Corner/state_machines/notice_take_effect_suspension_drives_plan
        """
        plan, _participant, enrollment = setup_active_enrollment(
            plan_overrides={"issuer_name": "Note Corp", "ticker": "NTC",
                            "name": "NTC DRIP"},
            participant_email="pnt@x.com")
        notice = create_notice(plan["id"], notice_type="SUSPENSION",
                               effective_at="2026-08-15T00:00:00Z",
                               message="Plan will be suspended for maintenance")
        get_success_data(api.publish_notice(notice["id"], ADMIN))
        set_clock("2026-08-15T00:00:00Z")
        effective = validate_success(api.take_effect_notice(notice["id"], ADMIN))
        assert effective["status"] == "EFFECTIVE"
        assert get_plan(plan["id"])["status"] == "SUSPENDED", \
            "the SUSPENSION notice drives the plan transition"
        assert get_enrollment(enrollment["id"])["status"] == "SUSPENDED", \
            "the notice-driven suspension runs the enrollment cascade"


class TestNoticeLeadTime:
    def test_notice_lead_time_boundary(self, api):
        """PRD §3.7: "Publication moves a notice from `DRAFT` to `PUBLISHED` and
        stamps `published_at`, but only when at least ten full days separate
        the logical clock from `effective_at`; a shorter lead fails with
        `ERR_NOTICE_LEAD_TIME_SHORT` (HTTP 422)."

        Design: Corner/validations/notice_lead_time_boundary
        """
        plan = create_active_plan(issuer_name="Lead Corp", ticker="LED",
                                  name="LED DRIP")
        # Clock is at the startup default 2026-08-01T00:00:00Z.
        notice_a = create_notice(plan["id"], notice_type="MODIFICATION",
                                 effective_at="2026-08-11T00:00:00Z",
                                 message="Fee change in 10 days")
        notice_b = create_notice(plan["id"], notice_type="MODIFICATION",
                                 effective_at="2026-08-06T00:00:00Z",
                                 message="Too soon")
        published = validate_success(api.publish_notice(notice_a["id"], ADMIN))
        assert published["status"] == "PUBLISHED", \
            "exactly ten days of lead time satisfies the minimum"

        resp = api.publish_notice(notice_b["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOTICE_LEAD_TIME_SHORT)
        remaining = [n for n in list_notices(plan["id"]) if n["id"] == notice_b["id"]]
        assert remaining[0]["status"] == "DRAFT", \
            "five days of lead time is too short; the notice stays DRAFT"


class TestPlanSuspensionRbac:
    def test_participant_cannot_suspend_plan(self, api):
        """PRD §3.7: "Suspension — whether invoked directly by an administrator
        or delivered through a `SUSPENSION` notice — moves an `ACTIVE` plan to
        `SUSPENDED` and cascades."
        PRD §2.1: "A request whose role is not permitted on the target endpoint
        — or a `Participant`-role request that touches a resource owned by a
        different participant — is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/participant_cannot_suspend_plan
        """
        plan = create_active_plan(issuer_name="Sec Corp", ticker="SEC",
                                  name="SEC DRIP")
        participant = register_participant("Pat Sc", "psc@x.com")
        resp = api.suspend_plan(plan["id"],
                                make_participant_headers(participant["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert get_plan(plan["id"])["status"] == "ACTIVE"
