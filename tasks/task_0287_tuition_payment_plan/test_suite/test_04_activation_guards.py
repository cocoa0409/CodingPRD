"""Activation preconditions, validation precedence, cross-entity state gates,
optimistic concurrency, and the enrollment window boundary.

Difficulty queue: priority_pair_validation_conflict, boundary_precision_check
(empty-set), cross_entity_state_dependency, resource_temporal_overlap (window).
Corner: errors (template retired), cross_cutting (OCC version + stale).
"""
from test_helpers import (
    validate_success,
    validate_error,
    fixtures,
    factories,
    ApiErrorId,
    TEST_USERS,
)

REGISTRAR = TEST_USERS["registrar_headers"]


# ===========================================================================
# Difficulty: priority_pair_validation_conflict (hold beats no-charges)
# ===========================================================================
def test_activate_held_student_zero_charge_returns_student_on_hold(api):
    """PRD 3.10: "the student-hold check comes before the term/window checks: an
    active hold yields `ERR_STUDENT_ON_HOLD`"
    PRD 3.4: "The student must not be on hold — `has_active_hold` must be false —
    or the attempt is rejected with `ERR_STUDENT_ON_HOLD`. The enrollment must
    have something to finance: `gross_charges_cents` must be strictly greater
    than zero, or the attempt is rejected with `ERR_NO_CHARGES_TO_FINANCE`."

    A held student activating a second, zero-charge enrollment fails both the
    hold check and the no-charges check; the hold check (earlier in priority
    order) wins -> ERR_STUDENT_ON_HOLD.

    Design: Difficulty/priority_pair_validation_conflict/hold_state_beats_fiscal_no_charges
    """
    base = fixtures.setup_delinquent_enrollment(
        charges_cents=500000, aid_cents=100000, delinquency_clock="2026-10-28T00:00:00.000Z"
    )
    student_id = base["student"]["id"]
    term_id = base["term"]["id"]
    template_id = base["template"]["id"]
    student = fixtures.get_student(student_id)
    assert student["has_active_hold"] is True, student

    # Reset clock inside the enroll window for a clean second activation attempt.
    fixtures.set_clock(base["institution"]["id"], "2026-09-15T00:00:00.000Z")
    enr2 = fixtures.create_enrollment(student_id, term_id, template_id)  # NO charges
    version = fixtures.current_version(enr2["id"])
    resp = api.activate_enrollment(
        enr2["id"], factories.activate_payload(version), REGISTRAR
    )
    validate_error(resp, ApiErrorId.ERR_STUDENT_ON_HOLD.value)


def test_activate_no_charges_without_hold_returns_no_charges(api):
    """PRD 3.4: "The student must not be on hold — `has_active_hold` must be
    false — or the attempt is rejected with `ERR_STUDENT_ON_HOLD`. The
    enrollment must have something to finance: `gross_charges_cents` must be
    strictly greater than zero, or the attempt is rejected with
    `ERR_NO_CHARGES_TO_FINANCE`."

    Control for the priority pair: with the hold violation REMOVED (a student
    with no active hold) but the zero-charge violation still present, the
    lower-priority charges check surfaces ERR_NO_CHARGES_TO_FINANCE — confirming
    ERR_STUDENT_ON_HOLD was masking it in the paired case.

    Design: Difficulty/priority_pair_validation_conflict/hold_state_beats_fiscal_no_charges
    """
    base = fixtures.setup_base()  # fresh student, no hold
    enr = fixtures.create_enrollment(
        base["student"]["id"], base["term"]["id"], base["template"]["id"]
    )  # NO charges posted
    version = fixtures.current_version(enr["id"])
    resp = api.activate_enrollment(
        enr["id"], factories.activate_payload(version), REGISTRAR
    )
    validate_error(resp, ApiErrorId.ERR_NO_CHARGES_TO_FINANCE.value)


# ===========================================================================
# Difficulty: priority_pair_validation_conflict (term-not-open beats autopay)
# ===========================================================================
def test_activate_locked_term_autopay_violation_returns_term_not_open(api):
    """PRD 3.10: "only then are the temporal checks evaluated, where a
    non-`OPEN` term yields `ERR_TERM_NOT_OPEN` and is itself ahead of the
    enrollment-window check" ... "the autopay-required check
    (`ERR_AUTOPAY_REQUIRED`) and the charges-to-finance check
    (`ERR_NO_CHARGES_TO_FINANCE`) follow"

    An enrollment on a LOCKED term using an autopay_required template with
    autopay_enabled false fails both checks; the term check (earlier) wins ->
    ERR_TERM_NOT_OPEN.

    Design: Difficulty/priority_pair_validation_conflict/temporal_term_not_open_beats_safety_autopay
    """
    base = fixtures.setup_base(autopay_required=True)
    enr = fixtures.create_enrollment(
        base["student"]["id"], base["term"]["id"], base["template"]["id"],
        autopay_enabled=False,
    )
    fixtures.post_charge(enr["id"], 500000)
    fixtures.get_success_data(api.lock_term(base["term"]["id"], REGISTRAR))

    version = fixtures.current_version(enr["id"])
    resp = api.activate_enrollment(
        enr["id"], factories.activate_payload(version), REGISTRAR
    )
    validate_error(resp, ApiErrorId.ERR_TERM_NOT_OPEN.value)


def test_activate_open_term_autopay_violation_returns_autopay_required(api):
    """PRD 3.4: "if the plan template's `autopay_required` is true, the
    enrollment's `autopay_enabled` must be true, or the attempt is rejected with
    `ERR_AUTOPAY_REQUIRED`."
    PRD 3.10: "the autopay-required check (`ERR_AUTOPAY_REQUIRED`) ... follow"

    Control for the priority pair: with the term-not-open violation REMOVED (the
    term left OPEN) but the autopay violation still present, the lower-priority
    autopay check surfaces ERR_AUTOPAY_REQUIRED — confirming ERR_TERM_NOT_OPEN
    was masking it in the paired case.

    Design: Difficulty/priority_pair_validation_conflict/temporal_term_not_open_beats_safety_autopay
    """
    base = fixtures.setup_base(autopay_required=True)
    enr = fixtures.create_enrollment(
        base["student"]["id"], base["term"]["id"], base["template"]["id"],
        autopay_enabled=False,
    )
    fixtures.post_charge(enr["id"], 500000)
    # term left OPEN (not locked)
    version = fixtures.current_version(enr["id"])
    resp = api.activate_enrollment(
        enr["id"], factories.activate_payload(version), REGISTRAR
    )
    validate_error(resp, ApiErrorId.ERR_AUTOPAY_REQUIRED.value)


# ===========================================================================
# Difficulty: boundary_precision_check (zero charges empty-set)
# ===========================================================================
def test_activate_with_zero_charges_rejected(api):
    """PRD 3.4: "The enrollment must have something to finance:
    `gross_charges_cents` must be strictly greater than zero, or the attempt is
    rejected with `ERR_NO_CHARGES_TO_FINANCE`."

    A PENDING enrollment with no charges posted is rejected on activate; it
    stays PENDING.

    Design: Difficulty/boundary_precision_check/activate_zero_charges_empty_set_boundary
    """
    base = fixtures.setup_base()
    enr = fixtures.create_enrollment(
        base["student"]["id"], base["term"]["id"], base["template"]["id"]
    )
    version = fixtures.current_version(enr["id"])
    resp = api.activate_enrollment(
        enr["id"], factories.activate_payload(version), REGISTRAR
    )
    validate_error(resp, ApiErrorId.ERR_NO_CHARGES_TO_FINANCE.value)
    enr = fixtures.get_enrollment(enr["id"])
    assert enr["status"] == "PENDING", enr


def test_activate_with_single_positive_charge_succeeds(api):
    """PRD 3.4: "The enrollment must have something to finance:
    `gross_charges_cents` must be strictly greater than zero, or the attempt is
    rejected with `ERR_NO_CHARGES_TO_FINANCE`."

    The just-above-empty boundary: one positive charge makes gross_charges_cents
    strictly greater than zero, so activation succeeds and the enrollment becomes
    ACTIVE — the X+1 side of the empty-set boundary.

    Design: Difficulty/boundary_precision_check/activate_zero_charges_empty_set_boundary
    """
    base = fixtures.setup_base()
    enr = fixtures.create_enrollment(
        base["student"]["id"], base["term"]["id"], base["template"]["id"]
    )
    fixtures.post_charge(enr["id"], 100000)
    version = fixtures.current_version(enr["id"])
    resp = api.activate_enrollment(
        enr["id"], factories.activate_payload(version), REGISTRAR
    )
    enr = validate_success(resp)
    assert enr["status"] == "ACTIVE", enr
    assert enr["gross_charges_cents"] == 100000, enr


# ===========================================================================
# Difficulty: cross_entity_state_dependency (activate depends on term OPEN)
# ===========================================================================
def test_activate_on_locked_term_returns_term_not_open(api):
    """PRD 3.4: "The financing term must be `OPEN`; if the `AcademicTerm` is not
    `OPEN`, activation is rejected with `ERR_TERM_NOT_OPEN`."

    Locking the term before activation flips the enrollment's valid next-state
    set; activate is rejected with ERR_TERM_NOT_OPEN and the enrollment stays
    PENDING.

    Design: Difficulty/cross_entity_state_dependency/activate_depends_on_term_open
    """
    base = fixtures.setup_base()
    enr = fixtures.create_enrollment(
        base["student"]["id"], base["term"]["id"], base["template"]["id"]
    )
    fixtures.post_charge(enr["id"], 500000)
    fixtures.get_success_data(api.lock_term(base["term"]["id"], REGISTRAR))

    version = fixtures.current_version(enr["id"])
    resp = api.activate_enrollment(
        enr["id"], factories.activate_payload(version), REGISTRAR
    )
    validate_error(resp, ApiErrorId.ERR_TERM_NOT_OPEN.value)
    enr = fixtures.get_enrollment(enr["id"])
    assert enr["status"] == "PENDING", enr


def test_activate_blocked_by_locked_term_creates_no_installments(api):
    """PRD 3.4: "The financing term must be `OPEN`; if the `AcademicTerm` is not
    `OPEN`, activation is rejected with `ERR_TERM_NOT_OPEN`." ... "When these
    checks pass, activation does several things in one atomic step. ... It then
    runs the **installment schedule** calculation to compute the down payment
    and the financed split and to lay down the installment rows"

    Because the cross-entity term gate fails, the activation's atomic side
    effects never run: the rejected enrollment has no installments laid down.

    Design: Difficulty/cross_entity_state_dependency/activate_depends_on_term_open
    """
    base = fixtures.setup_base()
    enr = fixtures.create_enrollment(
        base["student"]["id"], base["term"]["id"], base["template"]["id"]
    )
    fixtures.post_charge(enr["id"], 500000)
    fixtures.get_success_data(api.lock_term(base["term"]["id"], REGISTRAR))

    version = fixtures.current_version(enr["id"])
    resp = api.activate_enrollment(
        enr["id"], factories.activate_payload(version), REGISTRAR
    )
    validate_error(resp, ApiErrorId.ERR_TERM_NOT_OPEN.value)
    installments = fixtures.list_installments(enr["id"])
    assert installments == [], installments


# ===========================================================================
# Difficulty: cross_entity_state_dependency (settle depends on enrollment ACTIVE)
# ===========================================================================
def test_settle_payment_on_withdrawn_enrollment_returns_not_active(api):
    """PRD 3.6: "Settling additionally requires the parent enrollment to be
    `ACTIVE`, otherwise `ERR_ENROLLMENT_NOT_ACTIVE`."

    A payment created while the enrollment was ACTIVE cannot settle once the
    enrollment has been WITHDRAWN; settle is rejected with
    ERR_ENROLLMENT_NOT_ACTIVE and the payment stays PENDING.

    Design: Difficulty/cross_entity_state_dependency/payment_settle_depends_on_enrollment_active
    """
    base = fixtures.setup_active_enrollment(charges_cents=500000, aid_cents=100000)
    enr_id = base["enrollment"]["id"]
    # Create a PENDING down payment, then withdraw before settling it.
    pay = fixtures.get_success_data(
        api.create_payment(
            factories.create_payment_payload(enr_id, "DOWN_PAYMENT", 80000),
            TEST_USERS["bursar_headers"],
        )
    )
    fixtures.withdraw(enr_id, "2026-09-15T00:00:00.000Z")

    resp = api.settle_payment(pay["id"], TEST_USERS["bursar_headers"])
    validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_ACTIVE.value)
    refetched = fixtures.get_success_data(api.get_payment(pay["id"], REGISTRAR))
    assert refetched["status"] == "PENDING", refetched


def test_settle_payment_on_completed_enrollment_returns_not_active(api):
    """PRD 3.6: "Settling additionally requires the parent enrollment to be
    `ACTIVE`, otherwise `ERR_ENROLLMENT_NOT_ACTIVE`."

    The same Payment->Enrollment gate fires when the enrollment has reached the
    other terminal state, COMPLETED: a leftover PENDING payment created before
    completion cannot settle once the plan is COMPLETED.

    Design: Difficulty/cross_entity_state_dependency/payment_settle_depends_on_enrollment_active
    """
    base = fixtures.setup_base(installment_count=1, down_payment_pct=0, plan_fee_cents=0)
    enr = fixtures.create_enrollment(
        base["student"]["id"], base["term"]["id"], base["template"]["id"]
    )
    fixtures.post_charge(enr["id"], 120000)
    fixtures.activate(enr["id"])
    inst = fixtures.list_installments(enr["id"])[0]
    # Create an extra PENDING payment, then complete the enrollment via a separate
    # settled installment payment.
    leftover = fixtures.get_success_data(
        api.create_payment(
            factories.create_payment_payload(
                enr["id"], "INSTALLMENT", 120000, installment_id=inst["id"]
            ),
            TEST_USERS["bursar_headers"],
        )
    )
    fixtures.settle_installment(enr["id"], inst["id"], 120000)
    completed = fixtures.get_enrollment(enr["id"])
    assert completed["status"] == "COMPLETED", completed

    resp = api.settle_payment(leftover["id"], TEST_USERS["bursar_headers"])
    validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_ACTIVE.value)


# ===========================================================================
# Difficulty: resource_temporal_overlap (enroll window inclusive close boundary)
# ===========================================================================
def test_activate_at_inclusive_enroll_close_boundary_accepted(api):
    """PRD 3.4: "The institution's logical clock must fall within the inclusive
    enrollment window, at or after `enroll_open` and at or before
    `enroll_close`; outside that window, activation is rejected with
    `ERR_OUTSIDE_ENROLL_WINDOW`."

    Clock exactly at enroll_close (2026-09-30) is inside the closed window, so
    activation succeeds and the enrollment becomes ACTIVE.

    Design: Difficulty/resource_temporal_overlap/enroll_window_inclusive_close_boundary
    """
    base = fixtures.setup_base(clock="2026-09-30T00:00:00.000Z")
    enr = fixtures.create_enrollment(
        base["student"]["id"], base["term"]["id"], base["template"]["id"]
    )
    fixtures.post_charge(enr["id"], 500000)
    version = fixtures.current_version(enr["id"])
    resp = api.activate_enrollment(
        enr["id"], factories.activate_payload(version), REGISTRAR
    )
    enr = validate_success(resp)
    assert enr["status"] == "ACTIVE", enr


def test_activate_one_day_past_enroll_close_rejected(api):
    """PRD 3.4: "The institution's logical clock must fall within the inclusive
    enrollment window, at or after `enroll_open` and at or before
    `enroll_close`; outside that window, activation is rejected with
    `ERR_OUTSIDE_ENROLL_WINDOW`."

    One day past the close boundary (2026-10-01) is outside the window -> reject.

    Design: Difficulty/resource_temporal_overlap/enroll_window_inclusive_close_boundary
    """
    base = fixtures.setup_base(clock="2026-10-01T00:00:00.000Z")
    enr = fixtures.create_enrollment(
        base["student"]["id"], base["term"]["id"], base["template"]["id"]
    )
    fixtures.post_charge(enr["id"], 500000)
    version = fixtures.current_version(enr["id"])
    resp = api.activate_enrollment(
        enr["id"], factories.activate_payload(version), REGISTRAR
    )
    validate_error(resp, ApiErrorId.ERR_OUTSIDE_ENROLL_WINDOW.value)


# ===========================================================================
# Corner: errors / template retired blocks activation
# ===========================================================================
def test_retired_template_blocks_activation(api):
    """PRD 3.4: "The referenced plan template must be `ACTIVE`, or the attempt
    is rejected with `ERR_TEMPLATE_RETIRED`."

    Design: Corner/errors/template_retired_blocks_activation
    """
    base = fixtures.setup_base()
    enr = fixtures.create_enrollment(
        base["student"]["id"], base["term"]["id"], base["template"]["id"]
    )
    fixtures.post_charge(enr["id"], 500000)
    fixtures.get_success_data(api.retire_plan_template(base["template"]["id"], REGISTRAR))

    version = fixtures.current_version(enr["id"])
    resp = api.activate_enrollment(
        enr["id"], factories.activate_payload(version), REGISTRAR
    )
    validate_error(resp, ApiErrorId.ERR_TEMPLATE_RETIRED.value)


# ===========================================================================
# Corner: cross_cutting / OCC version increments on activate
# ===========================================================================
def test_activate_increments_enrollment_version(api):
    """PRD 3.4: "It then runs the **installment schedule** calculation ... and
    increments the enrollment's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_activate
    """
    base = fixtures.setup_pending_enrollment(charges_cents=500000, aid_cents=100000)
    enr_id = base["enrollment"]["id"]
    v_before = fixtures.current_version(enr_id)
    enr = fixtures.activate(enr_id, expected_version=v_before)
    assert enr["status"] == "ACTIVE", enr
    assert enr["version"] == v_before + 1, enr


# ===========================================================================
# Corner: cross_cutting / OCC stale version on activate rejected
# ===========================================================================
def test_activate_with_stale_version_rejected(api):
    """PRD 2.7: "Activating an enrollment requires the request to carry
    `expected_enrollment_version`, an integer that must equal the target
    enrollment's current `version`. If another writer has advanced the
    enrollment's version since the client last read it ... the activation is
    rejected with `ERR_STALE_VERSION` (HTTP 412)."

    A charge posted after the client captured the version bumps Enrollment.version;
    activating with the stale (pre-charge) version is rejected ERR_STALE_VERSION.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_activate_rejected
    """
    base = fixtures.setup_base()
    enr = fixtures.create_enrollment(
        base["student"]["id"], base["term"]["id"], base["template"]["id"]
    )
    fixtures.post_charge(enr["id"], 500000)
    stale_version = fixtures.current_version(enr["id"])
    # A second charge bumps the version past the captured snapshot.
    fixtures.post_charge(enr["id"], 20000, kind="FEE")

    resp = api.activate_enrollment(
        enr["id"], factories.activate_payload(stale_version), REGISTRAR
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
