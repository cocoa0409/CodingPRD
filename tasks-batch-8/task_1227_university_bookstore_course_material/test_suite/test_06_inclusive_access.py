"""Inclusive access: lock-time charge creation, opt-out cycle, census billing,
drop cascades, and the billed-charge priority conflict."""
from test_helpers import (
    CLOCK_AT_CENSUS,
    CLOCK_PAST_ADD_DROP,
    ApiErrorId,
    assert_ia_charge,
    create_faculty,
    create_section,
    create_student,
    create_term,
    drive_term_to_sales_open,
    enroll_student,
    get_ia_charge_for_enrollment,
    get_success_data,
    make_student_headers,
    open_section,
    open_term_adoption,
    reset_clock,
    run_census,
    set_clock,
    setup_ia_pending_charge,
    validate_error,
    validate_success,
)
from test_helpers import MANAGER


def test_section_lock_creates_pending_charges(api):
    """PRD §3.3: "If the section has `ia_enabled`, locking generates one
    inclusive-access charge per `ENROLLED` enrollment: each charge is created
    in `PENDING`, tied to its `enrollment_id` (at most one charge per
    enrollment), stamped with the section, student, and term, and with its
    `fee_cents` locked from the section's `ia_material_fee_cents` at that
    moment."

    Design: Corner/state_machines/section_lock_creates_pending_charges
    """
    reset_clock()
    term = create_term()
    faculty = create_faculty()
    stu1 = create_student(email="stu1@uni.edu")
    stu2 = create_student(full_name="Stu Two", email="stu2@uni.edu")
    stu3 = create_student(full_name="Stu Three", email="stu3@uni.edu")
    sec_ia = create_section(
        term["id"], faculty["id"], course_code="BIO200",
        ia_enabled=True, ia_material_fee_cents=4900,
    )
    sec_plain = create_section(term["id"], faculty["id"], course_code="BIO201")
    open_term_adoption(term["id"])
    open_section(sec_ia["id"])
    open_section(sec_plain["id"])
    enroll_student(sec_ia["id"], stu1["id"])
    enroll_student(sec_ia["id"], stu2["id"])
    enroll_student(sec_plain["id"], stu3["id"])
    drive_term_to_sales_open(term["id"])

    validate_success(api.lock_section(sec_ia["id"], MANAGER))
    validate_success(api.lock_section(sec_plain["id"], MANAGER))

    charges_ia = get_success_data(
        api.list_ia_charges(MANAGER, params={"section_id": sec_ia["id"]})
    )
    assert len(charges_ia) == 2
    for charge in charges_ia:
        assert_ia_charge(charge)
        assert charge["status"] == "PENDING"
        assert charge["fee_cents"] == 4900

    charges_plain = get_success_data(
        api.list_ia_charges(MANAGER, params={"section_id": sec_plain["id"]})
    )
    assert charges_plain == []


def test_enrollment_drop_cancels_pending_charge(api):
    """PRD §3.8: "Dropping an enrollment whose charge is still `PENDING` or
    `OPTED_OUT` instead moves the charge to terminal `CANCELLED`."
    PRD §3.3: "A `BookstoreManager` may drop any enrollment."

    Design: Corner/state_machines/enrollment_drop_cancels_pending_charge
    """
    base = setup_ia_pending_charge()
    dropped = validate_success(
        api.drop_enrollment(base["enrollment"]["id"], MANAGER)
    )
    assert dropped["status"] == "DROPPED"

    charge = get_success_data(api.get_ia_charge(base["charge"]["id"], MANAGER))
    assert charge["status"] == "CANCELLED"

    student = get_success_data(api.get_student(base["student"]["id"], MANAGER))
    assert student["aid_balance_cents"] == 100000


def test_ia_opt_out_revoke_cycle(api):
    """PRD §3.8: "Opting out stamps `opted_out_at` and moves the charge to
    `OPTED_OUT`. A student who changes their mind may revoke the opt-out before
    the same deadline, clearing `opted_out_at` and returning the charge to
    `PENDING`."
    PRD §3.8: "Census billing, fired from the term lifecycle of §3.1 once
    `census_at` has been reached, bills every `PENDING` charge in a `LOCKED`
    section."

    Design: Difficulty/non_linear_state_machine/ia_opt_out_revoke_cycle
    """
    base = setup_ia_pending_charge()  # clock 2026-08-25 <= opt-out deadline
    student_headers = make_student_headers(base["student"]["id"])
    charge_id = base["charge"]["id"]

    opted = validate_success(api.opt_out_ia_charge(charge_id, student_headers))
    assert opted["status"] == "OPTED_OUT"
    assert opted["opted_out_at"] is not None

    revoked = validate_success(
        api.revoke_opt_out_ia_charge(charge_id, student_headers)
    )
    assert revoked["status"] == "PENDING"
    assert revoked["opted_out_at"] is None

    # Cycle a second time; only the final PENDING state is billed.
    validate_success(api.opt_out_ia_charge(charge_id, student_headers))
    validate_success(api.revoke_opt_out_ia_charge(charge_id, student_headers))

    set_clock(CLOCK_AT_CENSUS)
    run_census(base["term"]["id"])

    charge = get_success_data(api.get_ia_charge(charge_id, MANAGER))
    assert charge["status"] == "BILLED"
    assert charge["aid_applied_cents"] == 4900
    assert charge["balance_due_cents"] == 0

    student = get_success_data(api.get_student(base["student"]["id"], MANAGER))
    assert student["aid_balance_cents"] == 95100


def test_optout_billed_charge_past_deadline(api):
    """PRD §2.8: "State: the target resource is in a valid from-state for the
    requested transition (`ERR_INVALID_STATE`), including the specific case of
    opt-out or revoke attempted on an already-billed inclusive-access charge
    (`ERR_CHARGE_ALREADY_BILLED`), and the optimistic-concurrency check
    (`ERR_STALE_VERSION`) — all three evaluated after existence and before any
    business rule."
    PRD §3.8: "Either action attempted on a charge already `BILLED` is rejected
    with `ERR_CHARGE_ALREADY_BILLED`."

    Design: Difficulty/priority_pair_validation_conflict/optout_billed_charge_past_deadline
    """
    base = setup_ia_pending_charge(clock_after_lock=None)
    set_clock(CLOCK_AT_CENSUS)
    run_census(base["term"]["id"])
    charge = get_success_data(api.get_ia_charge(base["charge"]["id"], MANAGER))
    assert charge["status"] == "BILLED"

    # Move past the opt-out deadline; both the state rule and the temporal
    # rule are violated, and the state error must win.
    set_clock(CLOCK_PAST_ADD_DROP)
    resp = api.opt_out_ia_charge(
        base["charge"]["id"], make_student_headers(base["student"]["id"])
    )
    validate_error(resp, ApiErrorId.ERR_CHARGE_ALREADY_BILLED)

    charge = get_success_data(api.get_ia_charge(base["charge"]["id"], MANAGER))
    assert charge["status"] == "BILLED"


def test_revoke_on_billed_charge_rejected_same_rule(api):
    """PRD §3.8: "Either action attempted on a charge already `BILLED` is
    rejected with `ERR_CHARGE_ALREADY_BILLED`."

    Design: Difficulty/priority_pair_validation_conflict/optout_billed_charge_past_deadline
    """
    base = setup_ia_pending_charge(clock_after_lock=None)
    set_clock(CLOCK_AT_CENSUS)
    run_census(base["term"]["id"])

    resp = api.revoke_opt_out_ia_charge(
        base["charge"]["id"], make_student_headers(base["student"]["id"])
    )
    validate_error(resp, ApiErrorId.ERR_CHARGE_ALREADY_BILLED)
    charge = get_success_data(api.get_ia_charge(base["charge"]["id"], MANAGER))
    assert charge["status"] == "BILLED"


def test_opt_out_after_deadline_rejected(api):
    """PRD §3.8: "While a charge is `PENDING`, the owning student may opt out —
    the charge's `student_id` must equal `X-User-ID`, otherwise
    `ERR_NOT_OWNER` — provided now is on or before the term's
    `ia_opt_out_deadline_at`; a late opt-out is rejected with
    `ERR_OPT_OUT_WINDOW_CLOSED`."

    Design: Corner/validations/opt_out_after_deadline_rejected
    """
    base = setup_ia_pending_charge(clock_after_lock=CLOCK_PAST_ADD_DROP)
    resp = api.opt_out_ia_charge(
        base["charge"]["id"], make_student_headers(base["student"]["id"])
    )
    validate_error(resp, ApiErrorId.ERR_OPT_OUT_WINDOW_CLOSED)
    charge = get_success_data(api.get_ia_charge(base["charge"]["id"], MANAGER))
    assert charge["status"] == "PENDING"


def test_ia_billing_requires_section_locked(api):
    """PRD §3.8: "Census billing, fired from the term lifecycle of §3.1 once
    `census_at` has been reached, bills every `PENDING` charge in a `LOCKED`
    section."
    PRD §3.8: "when now falls inside the aid charge window (both boundaries
    inclusive), `aid_applied_cents` is the smaller of the charge's `fee_cents`
    and the student's current `aid_balance_cents`; outside the window it is 0."

    Design: Difficulty/cross_entity_state_dependency/ia_billing_requires_section_locked
    """
    reset_clock()
    term = create_term()
    faculty = create_faculty()
    stu1 = create_student(email="stu1@uni.edu")
    stu2 = create_student(full_name="Stu Two", email="stu2@uni.edu")
    sec1 = create_section(
        term["id"], faculty["id"], course_code="BIO200",
        ia_enabled=True, ia_material_fee_cents=4900,
    )
    sec2 = create_section(
        term["id"], faculty["id"], course_code="BIO201",
        ia_enabled=True, ia_material_fee_cents=4900,
    )
    open_term_adoption(term["id"])
    open_section(sec1["id"])
    open_section(sec2["id"])
    enr1 = enroll_student(sec1["id"], stu1["id"])
    enroll_student(sec2["id"], stu2["id"])
    drive_term_to_sales_open(term["id"])
    # Only sec1 is locked; sec2 stays OPEN, so its charge is never created.
    validate_success(api.lock_section(sec1["id"], MANAGER))
    charge1 = get_ia_charge_for_enrollment(enr1["id"])

    set_clock(CLOCK_AT_CENSUS)
    run_census(term["id"])

    billed = get_success_data(api.get_ia_charge(charge1["id"], MANAGER))
    assert billed["status"] == "BILLED"
    assert billed["aid_applied_cents"] == 4900
    assert billed["balance_due_cents"] == 0

    # The OPEN section never generated a charge at lock, and the census run
    # leaves it that way.
    charges_sec2 = get_success_data(
        api.list_ia_charges(MANAGER, params={"section_id": sec2["id"]})
    )
    assert charges_sec2 == []

    student1 = get_success_data(api.get_student(stu1["id"], MANAGER))
    student2 = get_success_data(api.get_student(stu2["id"], MANAGER))
    assert student1["aid_balance_cents"] == 95100
    assert student2["aid_balance_cents"] == 100000


def test_ia_billing_split_outside_aid_window_applies_zero_aid(api):
    """PRD §3.8: "For each charge, the aid split is computed: when now falls
    inside the aid charge window (both boundaries inclusive),
    `aid_applied_cents` is the smaller of the charge's `fee_cents` and the
    student's current `aid_balance_cents`; outside the window it is 0. The
    `balance_due_cents` is the fee minus the aid applied."

    Design: Difficulty/cross_entity_state_dependency/ia_billing_requires_section_locked
    """
    # Census instant (2026-09-10) sits outside the aid charge window
    # [2026-08-01, 2026-09-15] only if moved; keep the calendar but push the
    # clock past the window end while still >= census_at.
    base = setup_ia_pending_charge(clock_after_lock=None)
    set_clock("2026-09-16T00:00:00Z")  # >= census_at, past aid window end
    run_census(base["term"]["id"])

    charge = get_success_data(api.get_ia_charge(base["charge"]["id"], MANAGER))
    assert charge["status"] == "BILLED"
    assert charge["aid_applied_cents"] == 0
    assert charge["balance_due_cents"] == 4900

    student = get_success_data(api.get_student(base["student"]["id"], MANAGER))
    assert student["aid_balance_cents"] == 100000


def test_census_run_before_census_at_rejected(api):
    """PRD §3.1: "From `SALES_OPEN`, the manager runs census billing, but only
    once now has reached the term's `census_at`; an earlier attempt is rejected
    with `ERR_CENSUS_NOT_REACHED`."

    Design: Corner/errors/census_run_before_census_at_rejected
    """
    reset_clock()
    term = create_term()
    open_term_adoption(term["id"])
    drive_term_to_sales_open(term["id"])
    set_clock("2026-09-05T00:00:00Z")

    resp = api.run_census_billing(term["id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_CENSUS_NOT_REACHED)
    term_after = get_success_data(api.get_term(term["id"], MANAGER))
    assert term_after["status"] == "SALES_OPEN"


def test_ia_revoke_after_deadline_rejected(api):
    """PRD §3.8: "A student who changes their mind may revoke the opt-out
    before the same deadline, clearing `opted_out_at` and returning the charge
    to `PENDING`."
    PRD §3.8: "While a charge is `PENDING`, the owning student may opt out —
    the charge's `student_id` must equal `X-User-ID`, otherwise
    `ERR_NOT_OWNER` — provided now is on or before the term's
    `ia_opt_out_deadline_at`; a late opt-out is rejected with
    `ERR_OPT_OUT_WINDOW_CLOSED`."

    Design: Difficulty/non_linear_state_machine/ia_opt_out_revoke_cycle
    """
    base = setup_ia_pending_charge()  # clock 2026-08-25 <= deadline
    student_headers = make_student_headers(base["student"]["id"])
    charge_id = base["charge"]["id"]

    opted = validate_success(api.opt_out_ia_charge(charge_id, student_headers))
    assert opted["status"] == "OPTED_OUT"

    # Past the opt-out deadline, the return leg of the cycle is closed too.
    set_clock(CLOCK_PAST_ADD_DROP)
    resp = api.revoke_opt_out_ia_charge(charge_id, student_headers)
    validate_error(resp, ApiErrorId.ERR_OPT_OUT_WINDOW_CLOSED)
    charge = get_success_data(api.get_ia_charge(charge_id, MANAGER))
    assert charge["status"] == "OPTED_OUT"
