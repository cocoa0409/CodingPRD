"""Permit lifecycle: acceptance gates and side effects, suspension,
reinstatement, revocation, and terminal-state lockdown."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    accept_permit,
    apply_for_permit,
    assert_instant_equals,
    create_employee,
    get_cycle,
    get_employee,
    get_lot,
    issue_violations,
    make_appeals_officer_headers,
    make_employee_headers,
    permit_fee_entries,
    put_employee_on_billing_hold,
    set_logical_clock,
    setup_active_permit,
    setup_offered_permit,
    setup_program_lot_cycle,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["parking_admin_headers"]


def test_accept_response_is_immediately_consistent(api):
    """PRD section 3.4: "Activation stamps `activated_at`, sets `term_end` to the
    activation date plus 12 months, releases the reservation and increases the
    lot's derived occupancy by one, and freezes the permit's gross monthly fee."
    PRD section 3.4: "The gross fee — stored as `monthly_fee_cents` — is the tier
    base rate multiplied by the shift multiplier of the permit's
    `queue_shift_pattern`, rounded half-up to integer cents. Base rates are 12000
    cents per month for a `CORE` lot and 6000 cents for a `REMOTE` lot;
    multipliers are 1.0 for `DAY`, 0.75 for `NIGHT`, 0.85 for `ROTATING`, and 1.1
    for `SPLIT`."

    Design: Corner/consistency_model/immediate_consistency_accept_response
    """
    set_logical_clock("2026-08-01T00:00:00Z")
    bundle = setup_offered_permit(
        shift_pattern="DAY",
        program_overrides={"monthly_subsidy_pool_cents": 0},
        lot_overrides={"capacity": 2},
    )

    resp = accept_permit(bundle["permit"], bundle["employee"])
    assert resp["status"] == "ACTIVE"
    assert_instant_equals(resp["activated_at"], "2026-08-01T00:00:00Z",
                          label="activated_at")
    assert resp["term_end"] == "2027-08-01", "activation date plus 12 months"
    assert resp["monthly_fee_cents"] == 12000, "CORE base 12000 x DAY 1.0"

    reread = validate_success(api.get_permit(bundle["permit"]["id"], ADMIN), 200)
    assert reread["status"] == "ACTIVE"
    lot = get_lot(bundle["lot"]["id"])
    assert lot["occupied_slots"] == 1
    assert lot["reserved_slots"] == 0


def test_permit_second_accept_rejected(api):
    """PRD section 3.4: "Following the global validation order of §2.8, acceptance
    checks, in sequence: the permit must currently be `OFFERED`
    (`ERR_PERMIT_NOT_OFFERED`); the employee's `employment_status` must be
    `ACTIVE` (`ERR_EMPLOYEE_NOT_ACTIVE`); the current logical time must not be
    past `offer_expires_at` — the expiry instant itself remains acceptable
    (`ERR_OFFER_EXPIRED`); the employee's `standing` must be `GOOD_STANDING`
    (`ERR_BILLING_HOLD`, HTTP 402); and an `OPEN` billing cycle must exist for the
    program (`ERR_NO_OPEN_BILLING_CYCLE`)."

    Design: Corner/state_machines/permit_second_accept_rejected
    """
    set_logical_clock("2026-08-01T00:00:00Z")
    bundle = setup_active_permit(
        program_overrides={"monthly_subsidy_pool_cents": 0},
        lot_overrides={"capacity": 2},
    )

    res = api.permit_event(
        bundle["permit"]["id"], {"event_type": "ACCEPT"},
        make_employee_headers(bundle["employee"]["id"]),
    )
    validate_error(res, "ERR_PERMIT_NOT_OFFERED", expected_status=409)

    fees = permit_fee_entries(bundle["permit"]["id"])
    assert len(fees) == 1, "a failed accept posts no additional PERMIT_FEE"
    assert fees[0]["amount_cents"] == 12000
    assert fees[0]["status"] == "PENDING"


def test_accept_on_unknown_permit_returns_not_found(api):
    """PRD section 2.9: "Identifiers embedded in a URL path are validated in
    left-to-right order: the first identifier that does not correspond to an
    existing resource yields `ERR_NOT_FOUND` (HTTP 404) before any further
    processing."

    Design: Corner/validations/accept_on_unknown_permit_returns_not_found
    """
    res = api.permit_event(
        NON_EXISTENT_UUID, {"event_type": "ACCEPT"},
        make_employee_headers(NON_EXISTENT_UUID),
    )
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_accept_without_open_cycle_rejected(api):
    """PRD section 3.4: "Following the global validation order of §2.8, acceptance
    checks, in sequence: the permit must currently be `OFFERED`
    (`ERR_PERMIT_NOT_OFFERED`); the employee's `employment_status` must be
    `ACTIVE` (`ERR_EMPLOYEE_NOT_ACTIVE`); the current logical time must not be
    past `offer_expires_at` — the expiry instant itself remains acceptable
    (`ERR_OFFER_EXPIRED`); the employee's `standing` must be `GOOD_STANDING`
    (`ERR_BILLING_HOLD`, HTTP 402); and an `OPEN` billing cycle must exist for the
    program (`ERR_NO_OPEN_BILLING_CYCLE`)."
    PRD section 3.2: "`occupied_slots` counts the lot's permits in `ACTIVE`
    status; `reserved_slots` counts the lot's permits in `OFFERED` status whose
    `offer_expires_at` has not yet passed relative to the logical clock — expired
    offers are excluded from the reservation."

    Design: Corner/validations/accept_without_open_cycle_rejected
    """
    set_logical_clock("2026-08-01T00:00:00Z")
    bundle = setup_offered_permit(with_cycle=False, lot_overrides={"capacity": 2})

    res = api.permit_event(
        bundle["permit"]["id"], {"event_type": "ACCEPT"},
        make_employee_headers(bundle["employee"]["id"]),
    )
    validate_error(res, "ERR_NO_OPEN_BILLING_CYCLE", expected_status=409)

    permit = validate_success(api.get_permit(bundle["permit"]["id"], ADMIN), 200)
    assert permit["status"] == "OFFERED"
    lot = get_lot(bundle["lot"]["id"])
    assert lot["reserved_slots"] == 1, (
        "a failed accept leaves the OFFERED permit — and its reservation — intact"
    )


def test_billing_hold_blocks_accept_pure(api):
    """PRD section 3.4: "Following the global validation order of §2.8, acceptance
    checks, in sequence: the permit must currently be `OFFERED`
    (`ERR_PERMIT_NOT_OFFERED`); the employee's `employment_status` must be
    `ACTIVE` (`ERR_EMPLOYEE_NOT_ACTIVE`); the current logical time must not be
    past `offer_expires_at` — the expiry instant itself remains acceptable
    (`ERR_OFFER_EXPIRED`); the employee's `standing` must be `GOOD_STANDING`
    (`ERR_BILLING_HOLD`, HTTP 402); and an `OPEN` billing cycle must exist for the
    program (`ERR_NO_OPEN_BILLING_CYCLE`)."
    PRD section 3.6: "Marking `DEDUCTION_FAILED` raises the employee's
    `balance_due_cents` by the entry's `amount_cents` and recomputes `standing`,
    which flips to `BILLING_HOLD` once the balance exceeds zero; permits are not
    auto-suspended as a consequence."

    Design: Corner/validations/billing_hold_blocks_accept_pure
    """
    set_logical_clock("2026-08-01T00:00:00Z")
    bundle = setup_offered_permit(
        program_overrides={"monthly_subsidy_pool_cents": 0},
        lot_overrides={"capacity": 2},
    )
    put_employee_on_billing_hold(bundle["cycle"]["id"], bundle["employee"]["id"],
                                 amount_cents=5000)

    res = api.permit_event(
        bundle["permit"]["id"], {"event_type": "ACCEPT"},
        make_employee_headers(bundle["employee"]["id"]),
    )
    validate_error(res, "ERR_BILLING_HOLD", expected_status=402)

    permit = validate_success(api.get_permit(bundle["permit"]["id"], ADMIN), 200)
    assert permit["status"] == "OFFERED"


class TestAcceptStateBeatsBillingHold:
    """State gate (priority 6) vs fiscal gate (priority 10): both violated, the
    state error wins."""

    def _setup(self, api):
        set_logical_clock("2026-08-01T00:00:00Z")
        bundle = setup_active_permit(
            program_overrides={"monthly_subsidy_pool_cents": 0},
            lot_overrides={"capacity": 2},
        )
        put_employee_on_billing_hold(bundle["cycle"]["id"],
                                     bundle["employee"]["id"], amount_cents=5000)
        return bundle

    def test_state_error_returned_when_both_gates_fail(self, api):
        """PRD section 2.8: "When several checks could reject the same request, the
        server evaluates them in a fixed order, and an earlier failure masks all
        later ones."
        PRD section 3.4: "Following the global validation order of §2.8, acceptance
        checks, in sequence: the permit must currently be `OFFERED`
        (`ERR_PERMIT_NOT_OFFERED`); the employee's `employment_status` must be
        `ACTIVE` (`ERR_EMPLOYEE_NOT_ACTIVE`); the current logical time must not be
        past `offer_expires_at` — the expiry instant itself remains acceptable
        (`ERR_OFFER_EXPIRED`); the employee's `standing` must be `GOOD_STANDING`
        (`ERR_BILLING_HOLD`, HTTP 402); and an `OPEN` billing cycle must exist for
        the program (`ERR_NO_OPEN_BILLING_CYCLE`)."

        Design: Difficulty/priority_pair_validation_conflict/accept_state_beats_billing_hold
        """
        bundle = self._setup(api)

        res = api.permit_event(
            bundle["permit"]["id"], {"event_type": "ACCEPT"},
            make_employee_headers(bundle["employee"]["id"]),
        )
        validate_error(res, "ERR_PERMIT_NOT_OFFERED", expected_status=409)

    def test_fiscal_failure_is_real_and_permit_untouched(self, api):
        """PRD section 3.6: "Marking `DEDUCTION_FAILED` raises the employee's
        `balance_due_cents` by the entry's `amount_cents` and recomputes
        `standing`, which flips to `BILLING_HOLD` once the balance exceeds zero;
        permits are not auto-suspended as a consequence."
        PRD section 2.8: "When several checks could reject the same request, the
        server evaluates them in a fixed order, and an earlier failure masks all
        later ones."

        Design: Difficulty/priority_pair_validation_conflict/accept_state_beats_billing_hold
        """
        bundle = self._setup(api)

        res = api.permit_event(
            bundle["permit"]["id"], {"event_type": "ACCEPT"},
            make_employee_headers(bundle["employee"]["id"]),
        )
        validate_error(res, "ERR_PERMIT_NOT_OFFERED", expected_status=409)

        employee = get_employee(bundle["employee"]["id"])
        assert employee["standing"] == "BILLING_HOLD"
        assert employee["balance_due_cents"] == 5000, (
            "the fiscal failure was real and remains — it was merely masked"
        )
        permit = validate_success(api.get_permit(bundle["permit"]["id"], ADMIN), 200)
        assert permit["status"] == "ACTIVE", "no side effects fired"


class TestAcceptRequiresActiveEmployee:
    """Permit -> Employee dependency: a TERMINATED employee cannot accept."""

    def _setup(self, api):
        set_logical_clock("2026-08-01T00:00:00Z")
        bundle = setup_offered_permit(
            program_overrides={"monthly_subsidy_pool_cents": 0},
            lot_overrides={"capacity": 2},
        )
        set_logical_clock("2026-08-02T09:00:00Z")
        validate_success(api.terminate_employee(bundle["employee"]["id"], ADMIN), 200)
        return bundle

    def test_terminated_employee_accept_rejected(self, api):
        """PRD section 3.4: "Following the global validation order of §2.8,
        acceptance checks, in sequence: the permit must currently be `OFFERED`
        (`ERR_PERMIT_NOT_OFFERED`); the employee's `employment_status` must be
        `ACTIVE` (`ERR_EMPLOYEE_NOT_ACTIVE`); the current logical time must not be
        past `offer_expires_at` — the expiry instant itself remains acceptable
        (`ERR_OFFER_EXPIRED`); the employee's `standing` must be `GOOD_STANDING`
        (`ERR_BILLING_HOLD`, HTTP 402); and an `OPEN` billing cycle must exist for
        the program (`ERR_NO_OPEN_BILLING_CYCLE`)."

        Design: Difficulty/cross_entity_state_dependency/accept_requires_active_employee
        """
        bundle = self._setup(api)
        res = api.permit_event(
            bundle["permit"]["id"], {"event_type": "ACCEPT"},
            make_employee_headers(bundle["employee"]["id"]),
        )
        validate_error(res, "ERR_EMPLOYEE_NOT_ACTIVE", expected_status=409)

    def test_termination_alone_does_not_sweep_permit(self, api):
        """PRD section 3.1: "When a `ParkingAdmin` terminates an employee,
        `employment_status` becomes `TERMINATED` and `terminated_at` is stamped
        with the current logical time; the employee's permits are not revoked at
        that moment."

        Design: Difficulty/cross_entity_state_dependency/accept_requires_active_employee
        """
        bundle = self._setup(api)
        res = api.permit_event(
            bundle["permit"]["id"], {"event_type": "ACCEPT"},
            make_employee_headers(bundle["employee"]["id"]),
        )
        validate_error(res, "ERR_EMPLOYEE_NOT_ACTIVE", expected_status=409)

        permit = validate_success(api.get_permit(bundle["permit"]["id"], ADMIN), 200)
        assert permit["status"] == "OFFERED", (
            "termination alone does not sweep; only run-ops revokes"
        )
        employee = get_employee(bundle["employee"]["id"])
        assert employee["employment_status"] == "TERMINATED"


class TestOfferAcceptAtExactExpiry:
    """Time boundary on ACCEPT: valid while now <= offer_expires_at (inclusive)."""

    def _setup(self, api):
        set_logical_clock("2026-08-01T09:00:00Z")
        bundle = setup_program_lot_cycle(
            program_overrides={"monthly_subsidy_pool_cents": 100000,
                               "waitlist_offer_ttl_hours": 72},
            lot_overrides={"capacity": 2},
        )
        e1 = create_employee(bundle["program"]["id"], badge_number="B001")
        e2 = create_employee(bundle["program"]["id"], badge_number="B002")
        p1 = apply_for_permit(e1, bundle["lot"], vehicle_plate="P001")
        p2 = apply_for_permit(e2, bundle["lot"], vehicle_plate="P002")
        assert p1["status"] == "OFFERED" and p2["status"] == "OFFERED"
        return bundle, e1, e2, p1, p2

    def test_accept_at_exact_expiry_second_succeeds(self, api):
        """PRD section 3.3: "An offer stamps `offered_at` with the current logical
        time, sets `offer_expires_at` to `offered_at` plus the program's
        `waitlist_offer_ttl_hours`, and raises the lot's derived reservation count
        by one."
        PRD section 3.4: "Following the global validation order of §2.8, acceptance
        checks, in sequence: the permit must currently be `OFFERED`
        (`ERR_PERMIT_NOT_OFFERED`); the employee's `employment_status` must be
        `ACTIVE` (`ERR_EMPLOYEE_NOT_ACTIVE`); the current logical time must not be
        past `offer_expires_at` — the expiry instant itself remains acceptable
        (`ERR_OFFER_EXPIRED`); the employee's `standing` must be `GOOD_STANDING`
        (`ERR_BILLING_HOLD`, HTTP 402); and an `OPEN` billing cycle must exist for
        the program (`ERR_NO_OPEN_BILLING_CYCLE`)."
        PRD section 3.4: "Under `CALENDAR_DAY`, the amount is the full-month net
        fee multiplied by the active-day count and divided by the period length,
        rounded half-up to integer cents."

        Design: Difficulty/boundary_precision_check/offer_accept_at_exact_expiry
        """
        bundle, e1, _e2, p1, _p2 = self._setup(api)
        assert_instant_equals(p1["offer_expires_at"], "2026-08-04T09:00:00Z",
                              label="offer_expires_at (offered 08-01T09:00 + 72h)")

        set_logical_clock("2026-08-04T09:00:00Z")
        accepted = accept_permit(p1, e1)
        assert accepted["status"] == "ACTIVE", "the expiry instant remains acceptable"

        fees = permit_fee_entries(p1["id"])
        assert len(fees) == 1
        entry = fees[0]
        assert entry["span_start"] == "2026-08-04"
        assert entry["span_end"] == "2026-08-31"
        # net = 12000 - 1200 = 10800 over 28 active days of a 31-day period.
        assert entry["amount_cents"] == 9755, "round_half_up(10800 * 28/31)"

    def test_accept_one_second_after_expiry_rejected(self, api):
        """PRD section 3.4: "Following the global validation order of §2.8,
        acceptance checks, in sequence: the permit must currently be `OFFERED`
        (`ERR_PERMIT_NOT_OFFERED`); the employee's `employment_status` must be
        `ACTIVE` (`ERR_EMPLOYEE_NOT_ACTIVE`); the current logical time must not be
        past `offer_expires_at` — the expiry instant itself remains acceptable
        (`ERR_OFFER_EXPIRED`); the employee's `standing` must be `GOOD_STANDING`
        (`ERR_BILLING_HOLD`, HTTP 402); and an `OPEN` billing cycle must exist for
        the program (`ERR_NO_OPEN_BILLING_CYCLE`)."

        Design: Difficulty/boundary_precision_check/offer_accept_at_exact_expiry
        """
        bundle, e1, e2, p1, p2 = self._setup(api)

        set_logical_clock("2026-08-04T09:00:00Z")
        accept_permit(p1, e1)

        set_logical_clock("2026-08-04T09:00:01Z")
        res = api.permit_event(
            p2["id"], {"event_type": "ACCEPT"}, make_employee_headers(e2["id"])
        )
        validate_error(res, "ERR_OFFER_EXPIRED", expected_status=409)

        permit = validate_success(api.get_permit(p2["id"], ADMIN), 200)
        assert permit["status"] == "OFFERED", "a failed accept mutates nothing"


class TestPermitSuspendReinstateCycle:
    """Cyclic ACTIVE -> SUSPENDED -> ACTIVE with span-truncating billing on
    both arcs."""

    def _setup(self, api):
        set_logical_clock("2026-08-01T00:00:00Z")
        bundle = setup_active_permit(
            program_overrides={"monthly_subsidy_pool_cents": 100000},
            lot_overrides={"capacity": 2},
        )
        return bundle

    def _drive(self, api, bundle):
        p1 = bundle["permit"]
        set_logical_clock("2026-08-16T09:00:00Z")
        validate_success(
            api.permit_event(p1["id"], {"event_type": "SUSPEND"}, ADMIN), 200
        )
        set_logical_clock("2026-08-21T09:00:00Z")
        reinstated = validate_success(
            api.permit_event(p1["id"], {"event_type": "REINSTATE"}, ADMIN), 200
        )
        return reinstated

    def test_entries_reversed_truncated_and_reposted(self, api):
        """PRD section 3.5: "The permit's `PENDING` `PERMIT_FEE` entry in the
        program's `OPEN` cycle whose span contains the suspension date is
        reversed, and a truncated `PENDING` repost is created covering the span
        start through the suspension date, priced per §3.4."
        PRD section 3.5: "Reinstatement clears the `suspension_reason`, increases
        the lot's derived occupancy by one, and posts a fresh `PENDING`
        `PERMIT_FEE` spanning the reinstate date through the cycle's
        `period_end`."

        Design: Difficulty/non_linear_state_machine/permit_suspend_reinstate_cycle
        """
        bundle = self._setup(api)
        reinstated = self._drive(api, bundle)
        assert reinstated["status"] == "ACTIVE"
        assert reinstated["suspension_reason"] is None

        fees = permit_fee_entries(bundle["permit"]["id"])
        by_span = {(f["span_start"], f["span_end"]): f for f in fees}
        assert len(fees) == 3, f"expected A/B/C entries, got {fees}"

        original = by_span[("2026-08-01", "2026-08-31")]
        truncated = by_span[("2026-08-01", "2026-08-16")]
        reinstate_span = by_span[("2026-08-21", "2026-08-31")]
        assert original["amount_cents"] == 10800
        assert original["status"] == "REVERSED"
        # net = 12000 - 1200 = 10800; 16 active days of 31.
        assert truncated["amount_cents"] == 5574
        assert truncated["status"] == "PENDING"
        # 11 active days of 31.
        assert reinstate_span["amount_cents"] == 3832
        assert reinstate_span["status"] == "PENDING"

    def test_cycle_total_and_occupancy_after_loop(self, api):
        """PRD section 2.6: "Every charge entry amount is rounded half-up to
        integer cents at posting time, and a billing cycle's total is the plain
        integer sum of its non-reversed entries — never re-rounded after
        summation."
        PRD section 3.5: "Reinstatement clears the `suspension_reason`, increases
        the lot's derived occupancy by one, and posts a fresh `PENDING`
        `PERMIT_FEE` spanning the reinstate date through the cycle's
        `period_end`."

        Design: Difficulty/non_linear_state_machine/permit_suspend_reinstate_cycle
        """
        bundle = self._setup(api)
        reinstated = self._drive(api, bundle)
        assert reinstated["status"] == "ACTIVE"

        cycle = get_cycle(bundle["cycle"]["id"])
        assert cycle["total_charges_cents"] == 9406, (
            "5574 + 3832; days 2026-08-17..2026-08-20 are billed to nobody"
        )
        lot = get_lot(bundle["lot"]["id"])
        assert lot["occupied_slots"] == 1


def test_reinstate_blocked_until_violations_cleared(api):
    """PRD section 3.5: "After a `VIOLATION_THRESHOLD` suspension, the permit's
    unpaid violation count must have fallen strictly below the program's
    `violation_suspension_threshold`. After a `LOT_CLOSURE` suspension, the lot
    must be bookable. After a `BILLING_HOLD` or `ADMIN` suspension, the
    employee's `standing` must be `GOOD_STANDING`. An unmet gate is rejected with
    `ERR_REINSTATE_BLOCKED`, and in every case an `OPEN` billing cycle must exist
    for the program (`ERR_NO_OPEN_BILLING_CYCLE`)."
    PRD section 3.7: "A `DISMISSED` decision flips `payment_status` to `REVERSED`
    and compensates the ledger: the linked `VIOLATION_FINE` entry is reversed when
    it is still `PENDING`, while an entry that has already advanced to `APPLIED`
    or `EXPORTED` is left in place and an `ADJUSTMENT_CREDIT` for the fine amount
    is posted instead into the program's current `OPEN` cycle, if one exists."

    Design: Corner/validations/reinstate_blocked_until_violations_cleared
    """
    bundle = setup_active_permit(
        program_overrides={"monthly_subsidy_pool_cents": 0,
                           "violation_suspension_threshold": 3},
        lot_overrides={"capacity": 5},
    )
    p1 = bundle["permit"]
    set_logical_clock("2026-08-16T09:00:00Z")
    violations = issue_violations(p1, "WRONG_LOT", count=3, officer_id="officer-1")
    assert validate_success(api.get_permit(p1["id"], ADMIN), 200)["status"] == "SUSPENDED"

    blocked = api.permit_event(p1["id"], {"event_type": "REINSTATE"}, ADMIN)
    validate_error(blocked, "ERR_REINSTATE_BLOCKED", expected_status=409)

    # Dismissing the third violation drops the unpaid count to 2 < 3.
    v3 = violations[2]
    set_logical_clock("2026-08-17T09:00:00Z")
    validate_success(
        api.violation_event(v3["id"], {"event_type": "APPEAL"},
                            make_employee_headers(bundle["employee"]["id"])),
        200,
    )
    set_logical_clock("2026-08-18T09:00:00Z")
    dismissed = validate_success(
        api.violation_event(v3["id"],
                            {"event_type": "DECIDE_APPEAL", "decision": "DISMISSED"},
                            make_appeals_officer_headers("officer-2")),
        200,
    )
    assert dismissed["appeal_status"] == "DISMISSED"
    assert dismissed["payment_status"] == "REVERSED"

    set_logical_clock("2026-08-18T10:00:00Z")
    reinstated = validate_success(
        api.permit_event(p1["id"], {"event_type": "REINSTATE"}, ADMIN), 200
    )
    assert reinstated["status"] == "ACTIVE"

    cycle = get_cycle(bundle["cycle"]["id"])
    # 6194 truncated fee + 3500 + 5250 surviving fines + 5419 reinstate span;
    # the dismissed 7000 fine and the original 12000 fee are REVERSED.
    assert cycle["total_charges_cents"] == 20363


def test_permit_cancel_from_revoked_rejected(api):
    """PRD section 3.3: "`REVOKED`, `DECLINED`, `EXPIRED`, and `CANCELLED` are the
    terminal states of a permit."
    PRD section 2.8: "The target resource must be in the exact from-state of the
    requested transition, and program posture must permit the operation
    (`ERR_PROGRAM_FROZEN`, `ERR_PERMIT_NOT_OFFERED`, `ERR_INVALID_STATE`,
    `ERR_LOT_NOT_BOOKABLE`, `ERR_ROUTE_NOT_ACTIVE`, `ERR_CYCLE_NOT_OPEN`)."

    Design: Corner/state_machines/permit_cancel_from_revoked_rejected
    """
    set_logical_clock("2026-08-01T00:00:00Z")
    bundle = setup_active_permit(lot_overrides={"capacity": 2})
    validate_success(
        api.permit_event(bundle["permit"]["id"], {"event_type": "REVOKE"}, ADMIN), 200
    )

    res = api.permit_event(bundle["permit"]["id"], {"event_type": "CANCEL"}, ADMIN)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)

    permit = validate_success(api.get_permit(bundle["permit"]["id"], ADMIN), 200)
    assert permit["status"] == "REVOKED"
