"""Billing-cycle cascade, hold threshold boundary, the registration-hold
enrollment gate, and hold release claims (PRD §3.8, §3.7, §2.6, §3.11)."""
from test_helpers import (
    ApiErrorId,
    add_standard_rate,
    create_enrollment_payload,
    create_open_term,
    enroll,
    list_active_holds,
    make_payment,
    make_student,
    place_manual_hold,
    read_account,
    run_billing_cycle_at,
    setup_account_with_enrollment,
    setup_plan_scenario,
    setup_term_with_rate,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestBillingCycleDefaultHoldCascade:
    """One cycle trigger: installment PAST_DUE -> plan DEFAULTED -> account
    acceleration -> AUTO holds (PRD §3.8, §3.7, §2.6)."""

    def _setup_and_cycle(self):
        ctx = setup_plan_scenario(credit_hours=9, installment_count=4,
                                  first_due_date="2026-09-01",
                                  external_ref="S-CAS")
        cycle = run_billing_cycle_at(ctx["term"]["id"], "2026-10-15T00:00:00Z")
        return ctx, cycle

    def test_cycle_summary_counts(self, api, bursar_staff_headers):
        """PRD §3.8: "The cycle's response summarizes its work as counts:
        `installments_marked_past_due`, `plans_defaulted`, `late_fees_posted`,
        `holds_placed`, and `holds_released`." and "Each flip also drives its
        parent plan `ACTIVE` → `DEFAULTED` per §3.7, with the acceleration and
        hold consequences that carries."

        Design: Difficulty/transitive_cascade/billing_cycle_default_hold_cascade
        """
        ctx, cycle = self._setup_and_cycle()
        assert cycle["installments_marked_past_due"] == 2
        assert cycle["plans_defaulted"] == 1
        assert cycle["late_fees_posted"] == 2
        assert cycle["holds_placed"] == 2
        plan = validate_success(
            api.get_payment_plan(ctx["plan"]["id"], bursar_staff_headers), 200
        )
        assert plan["status"] == "DEFAULTED"

    def test_acceleration_and_auto_holds(self, api, bursar_staff_headers):
        """PRD §3.7: "the account's debt accelerates: `past_due_cents` is
        thereafter computed as the full open balance across every charge-family
        entry, due dates ignored, for as long as any plan on the account
        remains `DEFAULTED`."
        PRD §2.6: holds are created "with `origin` set to `AUTO` and the system
        reason string `PAST_DUE_BALANCE`".

        Design: Difficulty/transitive_cascade/billing_cycle_default_hold_cascade
        """
        ctx, _cycle = self._setup_and_cycle()
        account = read_account(ctx["account_id"])
        assert account["status"] == "PAST_DUE"
        # Full open balance: 330000 charges + 2500 plan fee + 2 x 4156 late.
        assert account["past_due_cents"] == 340812
        assert account["balance_cents"] == 340812
        holds = list_active_holds(ctx["account_id"])
        assert len(holds) == 2
        assert {h["hold_type"] for h in holds} == {"REGISTRATION", "TRANSCRIPT"}
        for hold in holds:
            assert hold["origin"] == "AUTO"
            assert hold["reason"] == "PAST_DUE_BALANCE"


class TestHoldThresholdEquality:
    """The >= comparison places holds at exactly the threshold (PRD §2.6)."""

    def _setup_pair(self):
        term, _rate = setup_term_with_rate()
        s_a = make_student("S-AT", "At Thresh")
        e_a = enroll(s_a["id"], term["id"], credit_hours=1)
        acc_a = e_a["account_id"]
        make_payment(acc_a, 30000)  # leaves exactly 20000 open
        s_b = make_student("S-BT", "Below Thresh")
        e_b = enroll(s_b["id"], term["id"], credit_hours=1)
        acc_b = e_b["account_id"]
        make_payment(acc_b, 30001)  # leaves 19999 open
        cycle = run_billing_cycle_at(term["id"], "2026-10-01T00:00:00Z")
        return acc_a, acc_b, cycle

    def test_past_due_equal_to_threshold_places_holds(self, api):
        """PRD §2.6: "If the account's `past_due_cents` is greater than or
        equal to the term's `hold_threshold_cents` — the comparison is
        inclusive, so a past-due amount exactly equal to the threshold places
        holds."

        Design: Difficulty/boundary_precision_check/hold_threshold_equality
        """
        acc_a, _acc_b, cycle = self._setup_pair()
        account = read_account(acc_a)
        assert account["past_due_cents"] == 20000
        assert account["status"] == "PAST_DUE"
        holds = list_active_holds(acc_a)
        assert len(holds) == 2, "20000 >= 20000 threshold must place both holds"
        assert {h["hold_type"] for h in holds} == {"REGISTRATION", "TRANSCRIPT"}
        assert cycle["holds_placed"] == 2, "only account A crosses the line"

    def test_one_cent_below_threshold_places_none(self, api):
        """PRD §2.6: "If the account's `past_due_cents` is greater than or
        equal to the term's `hold_threshold_cents` — the comparison is
        inclusive, so a past-due amount exactly equal to the threshold places
        holds."

        Design: Difficulty/boundary_precision_check/hold_threshold_equality
        """
        _acc_a, acc_b, _cycle = self._setup_pair()
        account = read_account(acc_b)
        assert account["past_due_cents"] == 19999
        assert account["status"] == "PAST_DUE", "any positive past-due flips OPEN"
        assert list_active_holds(acc_b) == [], (
            "19999 < 20000 threshold must place no holds"
        )


class TestEnrollmentBlockedByRegistrationHold:
    """An ACTIVE REGISTRATION hold anywhere gates new enrollment (PRD §2.6)."""

    def _setup(self):
        # Fall term: student assessed 1cr (50000), aged past due with holds.
        ctx = setup_account_with_enrollment(credit_hours=1, external_ref="S-HLD")
        run_billing_cycle_at(ctx["term"]["id"], "2026-10-01T00:00:00Z")
        # Spring term, healthy and open with its own rate card.
        spring = create_open_term(
            code="SPR-27", name="Spring 2027",
            start_date="2027-01-11", end_date="2027-05-07",
            census_date="2027-02-01", full_refund_end_date="2027-02-01",
            mid_refund_end_date="2027-03-01", withdrawal_deadline="2027-04-02",
        )
        add_standard_rate(spring["id"], effective_from="2026-12-01",
                          effective_to="2027-05-31")
        return ctx, spring

    def test_enrollment_rejected_while_registration_hold_active(
        self, api, registrar_headers, bursar_staff_headers
    ):
        """PRD §2.6: "An `ACTIVE` `REGISTRATION` hold on any account belonging
        to a student blocks new enrollment creation for that student with
        `ERR_REGISTRATION_HOLD_ACTIVE` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/enrollment_blocked_by_registration_hold
        """
        ctx, spring = self._setup()
        holds = list_active_holds(ctx["account_id"])
        assert any(h["hold_type"] == "REGISTRATION" for h in holds)

        res = api.create_enrollment(
            create_enrollment_payload(ctx["student"]["id"], spring["id"],
                                      credit_hours=3,
                                      effective_date="2027-01-11"),
            registrar_headers,
        )
        validate_error(res, ApiErrorId.ERR_REGISTRATION_HOLD_ACTIVE,
                       expected_status=422)
        enrollments, _m = validate_paginated(
            api.list_enrollments(
                bursar_staff_headers,
                params={"student_id": ctx["student"]["id"],
                        "term_id": spring["id"]},
            )
        )
        assert enrollments == [], "no enrollment row may be created"

    def test_hold_gates_only_the_held_student(self, api, registrar_headers):
        """PRD §2.6: "An `ACTIVE` `REGISTRATION` hold on any account belonging
        to a student blocks new enrollment creation for that student" — the
        gate is scoped to that student's accounts.

        Design: Difficulty/cross_entity_state_dependency/enrollment_blocked_by_registration_hold
        """
        ctx, spring = self._setup()
        other = make_student("S-FREE", "Hold Free")
        enrollment = validate_success(
            api.create_enrollment(
                create_enrollment_payload(other["id"], spring["id"],
                                          credit_hours=3,
                                          effective_date="2027-01-11"),
                registrar_headers,
            ),
            201,
        )
        assert enrollment["status"] == "ENROLLED"


def test_hold_release_twice_returns_state_error(api, bursar_staff_headers):
    """PRD §3.11: "Release of an `ACTIVE` hold is explicit and unconditional —
    a manual release is permitted regardless of the account's balance — and
    records the `released_reason`; releasing a hold that is already `RELEASED`
    is rejected with `ERR_HOLD_STATE_INVALID` (HTTP 409)."

    Design: Corner/state_machines/hold_release_twice_returns_state_error
    """
    ctx = setup_account_with_enrollment(credit_hours=1, external_ref="S-H2")
    hold = place_manual_hold(ctx["account_id"], hold_type="REGISTRATION",
                             reason="Advising stop")
    released = validate_success(
        api.release_hold(hold["id"], bursar_staff_headers), 200
    )
    assert released["status"] == "RELEASED"

    res = api.release_hold(hold["id"], bursar_staff_headers)
    validate_error(res, ApiErrorId.ERR_HOLD_STATE_INVALID, expected_status=409)
