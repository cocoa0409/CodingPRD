"""Instrument locker: rental-fee variants, checkout gates, the cyclic repair
loop, custody conservation, state-vs-fiscal priority, serial uniqueness, the
logical-clock OVERDUE transition, late fees, and terminal lockdown."""
from test_helpers import (
    DIRECTOR_HEADERS,
    EQUIPMENT_HEADERS,
    READER_HEADERS,
    ApiErrorId,
    advance_clock,
    assert_instrument,
    assert_instrument_assignment,
    checkout_instrument,
    complete_maintenance_payload,
    create_enrolled_student,
    create_instrument,
    create_instrument_payload,
    create_open_program,
    create_program,
    create_student,
    get_assignment,
    get_instrument,
    get_student,
    post_payment,
    return_assignment_payload,
    setup_assignment,
    validate_error,
    validate_paginated,
    validate_success,
)

DIRECTOR = DIRECTOR_HEADERS
EQUIPMENT = EQUIPMENT_HEADERS
READER = READER_HEADERS


# --- Difficulty: rental_fee_flat_vs_prorated_divergence -------------------------

def _setup_dual_fee_programs(api):
    """One PRORATED program and one FLAT program, each with an enrolled student
    and an available instrument; logical clock at the startup default."""
    prog_pro = create_open_program(season_name="Fall PRO", rental_fee_mode="PRORATED")
    student_a = create_enrolled_student(prog_pro["id"], full_name="Ann Pro")
    inst_a = create_instrument(prog_pro["id"], serial_number="SN-PRO-1",
                               instrument_type="TRUMPET",
                               replacement_value_cents=80000)
    prog_flat = create_open_program(season_name="Fall FLAT", rental_fee_mode="FLAT")
    student_b = create_enrolled_student(prog_flat["id"], full_name="Bob Flat")
    inst_b = create_instrument(prog_flat["id"], serial_number="SN-FLAT-1",
                               instrument_type="TRUMPET",
                               replacement_value_cents=80000)
    return (prog_pro, student_a, inst_a), (prog_flat, student_b, inst_b)


def test_identical_window_accrues_prorated_4000_vs_flat_15000(api, reader_headers):
    """PRD §3.3: "The two variants share inputs but diverge sharply: an identical fourteen-day window accrues 4000 cents under `PRORATED` against 15000 under `FLAT`." PRD §3.1: "Mode changes are not retroactive: `rental_fee_mode` is snapshotted onto each new instrument assignment at creation as its `fee_variant`, and `scoring_mode` is snapshotted onto each new audition at creation, so existing assignments and auditions keep the variant they were born with."

    Design: Difficulty/dual_variant_calc/rental_fee_flat_vs_prorated_divergence
    """
    (prog_pro, student_a, inst_a), (prog_flat, student_b, inst_b) = (
        _setup_dual_fee_programs(api))

    asg_a = checkout_instrument(student_a["id"], inst_a["id"],
                                "2026-08-15T00:00:00Z")
    asg_b = checkout_instrument(student_b["id"], inst_b["id"],
                                "2026-08-15T00:00:00Z")
    assert_instrument_assignment(asg_a)
    assert_instrument_assignment(asg_b)

    # 14 days -> ceil(14/7) = 2 weeks x 2000 = 4000 under PRORATED
    assert asg_a["fee_variant"] == "PRORATED"
    assert asg_a["accrued_fee_cents"] == 4000
    assert asg_b["fee_variant"] == "FLAT"
    assert asg_b["accrued_fee_cents"] == 15000
    assert asg_a["accrued_fee_cents"] != asg_b["accrued_fee_cents"], (
        "identical windows must diverge across the two variants")


def test_rental_fee_posts_rental_fee_debit_at_creation(api, reader_headers):
    """PRD §3.3: "Either way, the resulting `accrued_fee_cents` is posted to the student's ledger as a `RENTAL_FEE_DEBIT` at creation." PRD §2.7: "A student's `account_balance_cents` is derived from the ledger alone: the sum of the amounts of all debit-kind rows (`MANUAL_DEBIT`, `RENTAL_FEE_DEBIT`, `LATE_FEE_DEBIT`, `CLEANING_FEE_DEBIT`, `TRIP_SHARE_DEBIT`), minus the sum of the amounts of all credit-kind rows (`PAYMENT`, `WAIVER`, `FUNDRAISING_CREDIT`), plus the sum of the amounts of all `REFUND` rows."

    Design: Difficulty/dual_variant_calc/rental_fee_flat_vs_prorated_divergence
    """
    (prog_pro, student_a, inst_a), (prog_flat, student_b, inst_b) = (
        _setup_dual_fee_programs(api))

    checkout_instrument(student_a["id"], inst_a["id"], "2026-08-15T00:00:00Z")
    checkout_instrument(student_b["id"], inst_b["id"], "2026-08-15T00:00:00Z")

    rows_a, meta_a = validate_paginated(api.list_payments(
        reader_headers, params={"student_id": student_a["id"],
                                "kind": "RENTAL_FEE_DEBIT"}))
    assert meta_a["total_count"] == 1
    assert rows_a[0]["amount_cents"] == 4000
    assert get_student(student_a["id"])["account_balance_cents"] == 4000

    rows_b, meta_b = validate_paginated(api.list_payments(
        reader_headers, params={"student_id": student_b["id"],
                                "kind": "RENTAL_FEE_DEBIT"}))
    assert meta_b["total_count"] == 1
    assert rows_b[0]["amount_cents"] == 15000
    assert get_student(student_b["id"])["account_balance_cents"] == 15000


# --- Difficulty: instrument_cyclic_lifecycle_loop -------------------------------

def test_instrument_full_cycle_closes_back_to_checkout(api, reader_headers):
    """PRD §3.3: "a `PASS` restores it to `AVAILABLE` with `condition_grade` unchanged, while a `FAIL` moves it to `IN_MAINTENANCE` and degrades its `condition_grade` one step down the ladder `GOOD` → `FAIR` → `POOR` → `UNPLAYABLE`, with `UNPLAYABLE` as the floor (an `EXCELLENT` instrument degrades to `GOOD`)." PRD §3.3: "On success the instrument returns to `AVAILABLE`, its `condition_grade` is restored to `GOOD` if it had degraded below `GOOD`, the program's `repair_spent_cents` increases by `repair_cost_cents`, and the instrument's `version` increments."

    Design: Difficulty/non_linear_state_machine/instrument_cyclic_lifecycle_loop
    """
    program = create_open_program(season_name="CY")
    student1 = create_enrolled_student(program["id"], full_name="C1", grade=9,
                                       section="PERCUSSION")
    student2 = create_enrolled_student(program["id"], full_name="C2", grade=10,
                                       section="PERCUSSION")
    instrument = create_instrument(program["id"], serial_number="SN-CY-1",
                                   instrument_type="SNARE",
                                   replacement_value_cents=30000)
    asg1 = checkout_instrument(student1["id"], instrument["id"],
                               "2026-08-20T00:00:00Z")

    returned = validate_success(api.return_instrument_assignment(
        asg1["id"], return_assignment_payload("FAIL"), EQUIPMENT))
    assert returned["status"] == "RETURNED"

    repaired = validate_success(api.complete_maintenance(
        instrument["id"], complete_maintenance_payload(1500), EQUIPMENT))
    assert repaired["status"] == "AVAILABLE"
    assert repaired["condition_grade"] == "GOOD", "restored from degraded FAIR"

    asg2 = checkout_instrument(student2["id"], instrument["id"],
                               "2026-08-25T00:00:00Z")
    assert asg2["status"] == "ACTIVE", "the loop closed: AVAILABLE again"

    instrument = get_instrument(instrument["id"])
    assert_instrument(instrument)
    assert instrument["status"] == "CHECKED_OUT"
    assert instrument["condition_grade"] == "GOOD"
    program = validate_success(api.get_program(program["id"], reader_headers))
    assert program["repair_spent_cents"] == 1500


def test_fail_return_degrades_grade_one_step_and_parks_in_maintenance(
        api, reader_headers):
    """PRD §3.3: "a `FAIL` moves it to `IN_MAINTENANCE` and degrades its `condition_grade` one step down the ladder `GOOD` → `FAIR` → `POOR` → `UNPLAYABLE`, with `UNPLAYABLE` as the floor (an `EXCELLENT` instrument degrades to `GOOD`)." PRD §3.3: "On success the assignment starts `ACTIVE`, the instrument moves to `CHECKED_OUT`, and the rental fee accrues."

    Design: Difficulty/non_linear_state_machine/instrument_cyclic_lifecycle_loop
    """
    program, student, instrument, asg = setup_assignment(
        instrument_overrides={"serial_number": "SN-CY-2", "instrument_type": "SNARE",
                              "replacement_value_cents": 30000})
    assert get_instrument(instrument["id"])["status"] == "CHECKED_OUT"

    validate_success(api.return_instrument_assignment(
        asg["id"], return_assignment_payload("FAIL"), EQUIPMENT))
    instrument = get_instrument(instrument["id"])
    assert instrument["status"] == "IN_MAINTENANCE"
    assert instrument["condition_grade"] == "FAIR", "GOOD degrades one step"

    validate_success(api.complete_maintenance(
        instrument["id"], complete_maintenance_payload(800), EQUIPMENT))
    instrument = get_instrument(instrument["id"])
    assert instrument["status"] == "AVAILABLE"
    assert instrument["condition_grade"] == "GOOD"
    program = validate_success(api.get_program(program["id"], READER))
    assert program["repair_spent_cents"] == 800


# --- Difficulty: instrument_checkout_return_conserves_custody_count -------------

def _available_count(api, program_id):
    _rows, meta = validate_paginated(api.list_instruments(
        READER, params={"program_id": program_id, "status": "AVAILABLE",
                        "limit": 100}))
    return meta["total_count"]


def _total_count(api, program_id):
    _rows, meta = validate_paginated(api.list_instruments(
        READER, params={"program_id": program_id, "limit": 100}))
    return meta["total_count"]


def test_checkout_then_pass_return_conserves_available_count(api):
    """PRD §3.3: "On success the assignment starts `ACTIVE`, the instrument moves to `CHECKED_OUT`, and the rental fee accrues." PRD §3.3: "a `PASS` restores it to `AVAILABLE` with `condition_grade` unchanged, while a `FAIL` moves it to `IN_MAINTENANCE` and degrades its `condition_grade` one step down the ladder `GOOD` → `FAIR` → `POOR` → `UNPLAYABLE`, with `UNPLAYABLE` as the floor (an `EXCELLENT` instrument degrades to `GOOD`)."

    Design: Difficulty/compensating_invariant/instrument_checkout_return_conserves_custody_count
    """
    program = create_open_program(season_name="CU")
    student = create_enrolled_student(program["id"], full_name="Cust",
                                      section="WOODWIND")
    inst1 = create_instrument(program["id"], serial_number="SN-CU-1",
                              instrument_type="FLUTE", replacement_value_cents=40000)
    create_instrument(program["id"], serial_number="SN-CU-2",
                      instrument_type="CLARINET", replacement_value_cents=35000)
    assert _available_count(api, program["id"]) == 2
    assert _total_count(api, program["id"]) == 2

    asg = checkout_instrument(student["id"], inst1["id"], "2026-08-20T00:00:00Z")
    assert _available_count(api, program["id"]) == 1, "checkout holds one in custody"
    assert _total_count(api, program["id"]) == 2

    returned = validate_success(api.return_instrument_assignment(
        asg["id"], return_assignment_payload("PASS"), EQUIPMENT))
    assert returned["status"] == "RETURNED"
    assert _available_count(api, program["id"]) == 2, (
        "PASS return restores the pre-checkout custody count")
    assert _total_count(api, program["id"]) == 2
    assert get_instrument(inst1["id"])["status"] == "AVAILABLE"


def test_fail_return_holds_custody_until_maintenance_completes(api):
    """PRD §3.3: "a `FAIL` moves it to `IN_MAINTENANCE` and degrades its `condition_grade` one step down the ladder `GOOD` → `FAIR` → `POOR` → `UNPLAYABLE`, with `UNPLAYABLE` as the floor (an `EXCELLENT` instrument degrades to `GOOD`)." PRD §3.3: "On success the instrument returns to `AVAILABLE`, its `condition_grade` is restored to `GOOD` if it had degraded below `GOOD`, the program's `repair_spent_cents` increases by `repair_cost_cents`, and the instrument's `version` increments."

    Design: Difficulty/compensating_invariant/instrument_checkout_return_conserves_custody_count
    """
    program = create_open_program(season_name="CU2")
    student = create_enrolled_student(program["id"], full_name="Cust2",
                                      section="WOODWIND")
    inst1 = create_instrument(program["id"], serial_number="SN-CU-3",
                              instrument_type="FLUTE", replacement_value_cents=40000)
    create_instrument(program["id"], serial_number="SN-CU-4",
                      instrument_type="CLARINET", replacement_value_cents=35000)

    asg = checkout_instrument(student["id"], inst1["id"], "2026-08-20T00:00:00Z")
    validate_success(api.return_instrument_assignment(
        asg["id"], return_assignment_payload("FAIL"), EQUIPMENT))
    assert _available_count(api, program["id"]) == 1, (
        "IN_MAINTENANCE holds the instrument out of the available pool")
    assert _total_count(api, program["id"]) == 2, "no instrument is lost"

    validate_success(api.complete_maintenance(
        inst1["id"], complete_maintenance_payload(1200), EQUIPMENT))
    assert _available_count(api, program["id"]) == 2, (
        "maintenance completion conserves the custody count")
    assert _total_count(api, program["id"]) == 2


# --- Difficulty: instrument_assignment_requires_enrolled_student -----------------

def test_checkout_to_applied_student_rejected(api, equipment_headers):
    """PRD §3.3: "The student must be `ENROLLED` — an `APPLIED`, `SUSPENDED`, or `WITHDRAWN` student is rejected with `ERR_STUDENT_NOT_ENROLLED` — and must not be delinquent, else `ERR_STUDENT_DELINQUENT_FEES`."

    Design: Difficulty/cross_entity_state_dependency/instrument_assignment_requires_enrolled_student
    """
    program = create_open_program(season_name="XS")
    applicant = create_student(program["id"], full_name="Applicant",
                               section="WOODWIND")
    assert applicant["enrollment_status"] == "APPLIED"
    instrument = create_instrument(program["id"], serial_number="SN-XS-1",
                                   instrument_type="FLUTE",
                                   replacement_value_cents=40000)

    resp = api.create_instrument_assignment(
        {"student_id": applicant["id"], "instrument_id": instrument["id"],
         "due_date": "2026-08-20T00:00:00Z"}, equipment_headers)
    validate_error(resp, ApiErrorId.ERR_STUDENT_NOT_ENROLLED)
    assert get_instrument(instrument["id"])["status"] == "AVAILABLE", (
        "a rejected checkout fires no side effects")


def test_checkout_to_suspended_student_rejected(api, director_headers,
                                                equipment_headers):
    """PRD §3.3: "The student must be `ENROLLED` — an `APPLIED`, `SUSPENDED`, or `WITHDRAWN` student is rejected with `ERR_STUDENT_NOT_ENROLLED` — and must not be delinquent, else `ERR_STUDENT_DELINQUENT_FEES`."

    Design: Difficulty/cross_entity_state_dependency/instrument_assignment_requires_enrolled_student
    """
    program = create_open_program(season_name="XS2")
    student = create_enrolled_student(program["id"], full_name="Susp",
                                      section="WOODWIND")
    validate_success(api.suspend_student(student["id"], director_headers))
    instrument = create_instrument(program["id"], serial_number="SN-XS-2",
                                   instrument_type="OBOE",
                                   replacement_value_cents=40000)

    resp = api.create_instrument_assignment(
        {"student_id": student["id"], "instrument_id": instrument["id"],
         "due_date": "2026-08-20T00:00:00Z"}, equipment_headers)
    validate_error(resp, ApiErrorId.ERR_STUDENT_NOT_ENROLLED)
    assert get_instrument(instrument["id"])["status"] == "AVAILABLE"


# --- Difficulty: state_error_beats_fiscal_error_on_assignment_create -------------

def _setup_maintenance_vs_delinquent(api):
    """Instrument stuck IN_MAINTENANCE; a second student delinquent at 2501."""
    program = create_open_program(season_name="PV1")  # grace defaults to 2500
    delinquent = create_enrolled_student(program["id"], full_name="Delq")
    post_payment(delinquent["id"], "MANUAL_DEBIT", 2501)
    holder = create_enrolled_student(program["id"], full_name="Holder")
    instrument = create_instrument(program["id"], serial_number="SN-PV-1",
                                   instrument_type="TROMBONE",
                                   replacement_value_cents=60000)
    holder_asg = checkout_instrument(holder["id"], instrument["id"],
                                     "2026-08-20T00:00:00Z")
    validate_success(api.return_instrument_assignment(
        holder_asg["id"], return_assignment_payload("FAIL"), EQUIPMENT))
    assert get_instrument(instrument["id"])["status"] == "IN_MAINTENANCE"
    return program, delinquent, holder, instrument


def test_dual_failure_surfaces_state_error_not_fiscal(api, equipment_headers):
    """PRD §2.8: "Fiscal checks are always evaluated last in the validation order — after authentication, existence, state, and constraint checks — so a request that fails both a state rule and a fiscal rule surfaces the state error, never the fiscal one." PRD §2.11: "This ordering is observable: when two rules fail simultaneously, the response always carries the earlier-priority error."

    Design: Difficulty/priority_pair_validation_conflict/state_error_beats_fiscal_error_on_assignment_create
    """
    _program, delinquent, _holder, instrument = (
        _setup_maintenance_vs_delinquent(api))

    resp = api.create_instrument_assignment(
        {"student_id": delinquent["id"], "instrument_id": instrument["id"],
         "due_date": "2026-08-25T00:00:00Z"}, equipment_headers)
    validate_error(resp, ApiErrorId.ERR_INSTRUMENT_NOT_AVAILABLE)

    assert get_student(delinquent["id"])["is_delinquent"] is True
    assert get_instrument(instrument["id"])["status"] == "IN_MAINTENANCE"


def test_each_arm_of_the_pair_fires_in_isolation(api, equipment_headers):
    """PRD §3.3: "The instrument must be `AVAILABLE`, else `ERR_INSTRUMENT_NOT_AVAILABLE`, and must not be `UNPLAYABLE`, else `ERR_INSTRUMENT_UNPLAYABLE` (HTTP 422)." PRD §2.8: "Delinquency has teeth in three places: creating a new financial obligation for the student (checking out an instrument, or enrolling in a trip) is rejected with `ERR_STUDENT_DELINQUENT_FEES` (HTTP 402), and reinstating a suspended student is likewise rejected with `ERR_STUDENT_DELINQUENT_FEES` while the balance remains strictly above the grace amount."

    Design: Difficulty/priority_pair_validation_conflict/state_error_beats_fiscal_error_on_assignment_create
    """
    program, delinquent, _holder, instrument = (
        _setup_maintenance_vs_delinquent(api))

    # fiscal arm alone: delinquent student + an AVAILABLE instrument
    clean_instrument = create_instrument(program["id"], serial_number="SN-PV-2",
                                         instrument_type="FLUTE",
                                         replacement_value_cents=40000)
    fiscal = api.create_instrument_assignment(
        {"student_id": delinquent["id"], "instrument_id": clean_instrument["id"],
         "due_date": "2026-08-25T00:00:00Z"}, equipment_headers)
    validate_error(fiscal, ApiErrorId.ERR_STUDENT_DELINQUENT_FEES)

    # state arm alone: solvent student + the IN_MAINTENANCE instrument
    solvent = create_enrolled_student(program["id"], full_name="Solvent")
    state = api.create_instrument_assignment(
        {"student_id": solvent["id"], "instrument_id": instrument["id"],
         "due_date": "2026-08-25T00:00:00Z"}, equipment_headers)
    validate_error(state, ApiErrorId.ERR_INSTRUMENT_NOT_AVAILABLE)


# --- Corner: terminal lockdown, serial uniqueness, safety, type, due date -------

def test_retired_instrument_is_terminal_and_never_assignable(
        api, equipment_headers, reader_headers):
    """PRD §3.3: "Retirement is terminal and irreversible: the `EquipmentManager` may retire an instrument from `AVAILABLE` or `IN_MAINTENANCE`; retiring one that is `CHECKED_OUT` is rejected with `ERR_INSTRUMENT_CHECKED_OUT`, and a `RETIRED` instrument is excluded from all further operations — a second retire attempt yields `ERR_INSTRUMENT_RETIRED`." PRD §3.3: "The instrument must be `AVAILABLE`, else `ERR_INSTRUMENT_NOT_AVAILABLE`, and must not be `UNPLAYABLE`, else `ERR_INSTRUMENT_UNPLAYABLE` (HTTP 422)."

    Design: Corner/state_machines/retired_instrument_is_terminal_and_negative_space
    """
    program = create_open_program(season_name="RT")
    student = create_enrolled_student(program["id"], full_name="R")
    instrument = create_instrument(program["id"], serial_number="SN-RT-1",
                                   instrument_type="TUBA",
                                   replacement_value_cents=90000)
    retired = validate_success(api.retire_instrument(instrument["id"],
                                                     equipment_headers))
    assert retired["status"] == "RETIRED"

    again = api.retire_instrument(instrument["id"], equipment_headers)
    validate_error(again, ApiErrorId.ERR_INSTRUMENT_RETIRED)

    checkout = api.create_instrument_assignment(
        {"student_id": student["id"], "instrument_id": instrument["id"],
         "due_date": "2026-08-20T00:00:00Z"}, equipment_headers)
    validate_error(checkout, ApiErrorId.ERR_INSTRUMENT_NOT_AVAILABLE)
    instrument = validate_success(api.get_instrument(instrument["id"],
                                                     reader_headers))
    assert instrument["status"] == "RETIRED"


def test_serial_number_unique_within_program_only(api, equipment_headers):
    """PRD §3.3: "The `EquipmentManager` stocks the locker by creating instruments with a `program_id`, a `serial_number` unique within the program (duplicates rejected with `ERR_SERIAL_NUMBER_TAKEN`), an `instrument_type` such as `TRUMPET`, `SNARE`, or `SOUSAPHONE`, a declared `replacement_value_cents`, and an optional `condition_grade` — one of `EXCELLENT`, `GOOD`, `FAIR`, `POOR`, or `UNPLAYABLE` — defaulting to `GOOD`."

    Design: Corner/entities/instrument_serial_unique_per_program
    """
    program1 = create_open_program(season_name="S1")
    program2 = create_open_program(season_name="S2")
    create_instrument(program1["id"], serial_number="SN-DUP",
                      instrument_type="FLUTE", replacement_value_cents=40000)

    dup = api.create_instrument(
        create_instrument_payload(program1["id"], serial_number="SN-DUP",
                                  instrument_type="OBOE",
                                  replacement_value_cents=90000),
        equipment_headers)
    validate_error(dup, ApiErrorId.ERR_SERIAL_NUMBER_TAKEN)

    other = validate_success(api.create_instrument(
        create_instrument_payload(program2["id"], serial_number="SN-DUP",
                                  instrument_type="OBOE",
                                  replacement_value_cents=90000),
        equipment_headers), 201)
    assert other["program_id"] == program2["id"], (
        "uniqueness is scoped to the owning program")


def test_unplayable_instrument_cannot_be_checked_out(api, equipment_headers):
    """PRD §3.3: "The instrument must be `AVAILABLE`, else `ERR_INSTRUMENT_NOT_AVAILABLE`, and must not be `UNPLAYABLE`, else `ERR_INSTRUMENT_UNPLAYABLE` (HTTP 422)."

    Design: Corner/validations/unplayable_instrument_cannot_be_assigned
    """
    program = create_open_program(season_name="UP")
    student = create_enrolled_student(program["id"], full_name="UP")
    instrument = create_instrument(program["id"], serial_number="SN-UP-1",
                                   instrument_type="HORN",
                                   replacement_value_cents=50000,
                                   condition_grade="UNPLAYABLE")
    assert instrument["status"] == "AVAILABLE"

    resp = api.create_instrument_assignment(
        {"student_id": student["id"], "instrument_id": instrument["id"],
         "due_date": "2026-08-20T00:00:00Z"}, equipment_headers)
    validate_error(resp, ApiErrorId.ERR_INSTRUMENT_UNPLAYABLE)
    assert get_instrument(instrument["id"])["status"] == "AVAILABLE"


def test_one_active_assignment_per_instrument_type(api, equipment_headers):
    """PRD §3.3: "One student may hold at most one active assignment per instrument type: a second checkout of the same `instrument_type` while an `ACTIVE` or `OVERDUE` assignment exists for that student is rejected with `ERR_INSTRUMENT_TYPE_ALREADY_ASSIGNED`."

    Design: Corner/validations/one_active_assignment_per_instrument_type
    """
    # High grace keeps the student solvent after the first FLAT-fee checkout
    # (15000 > the 2500 default would make the student delinquent, and PRD §2.8
    # would then rightly reject the clarinet checkout with
    # ERR_STUDENT_DELINQUENT_FEES — the uniqueness rule is what is under test).
    program = create_open_program(season_name="TA", delinquency_grace_cents=100000)
    student = create_enrolled_student(program["id"], full_name="TA")
    trumpet1 = create_instrument(program["id"], serial_number="SN-TA-1",
                                 instrument_type="TRUMPET")
    trumpet2 = create_instrument(program["id"], serial_number="SN-TA-2",
                                 instrument_type="TRUMPET")
    clarinet = create_instrument(program["id"], serial_number="SN-TA-3",
                                 instrument_type="CLARINET")
    checkout_instrument(student["id"], trumpet1["id"], "2026-08-20T00:00:00Z")

    dup = api.create_instrument_assignment(
        {"student_id": student["id"], "instrument_id": trumpet2["id"],
         "due_date": "2026-08-20T00:00:00Z"}, equipment_headers)
    validate_error(dup, ApiErrorId.ERR_INSTRUMENT_TYPE_ALREADY_ASSIGNED)

    ok = checkout_instrument(student["id"], clarinet["id"], "2026-08-20T00:00:00Z")
    assert ok["status"] == "ACTIVE", "a different instrument type is permitted"
    assert get_instrument(trumpet2["id"])["status"] == "AVAILABLE"


def test_due_date_must_be_strictly_after_checkout(api, equipment_headers):
    """PRD §3.3: "The `due_date` must be strictly after the checkout instant recorded as `checkout_at`, else `ERR_DUE_DATE_INVALID` (HTTP 422)." PRD §2.6: "Before any such call, the logical clock starts at exactly 2026-08-01T00:00:00Z and never falls back to the wall clock."

    Design: Corner/validations/due_date_not_after_checkout_rejected
    """
    program = create_open_program(season_name="DD")
    student = create_enrolled_student(program["id"], full_name="DD")
    instrument = create_instrument(program["id"], serial_number="SN-DD-1",
                                   instrument_type="HORN")

    resp = api.create_instrument_assignment(
        {"student_id": student["id"], "instrument_id": instrument["id"],
         "due_date": "2026-07-15T00:00:00Z"}, equipment_headers)
    validate_error(resp, ApiErrorId.ERR_DUE_DATE_INVALID)
    assert get_instrument(instrument["id"])["status"] == "AVAILABLE"


def test_retire_checked_out_instrument_rejected(api, equipment_headers):
    """PRD §3.3: "Retirement is terminal and irreversible: the `EquipmentManager` may retire an instrument from `AVAILABLE` or `IN_MAINTENANCE`; retiring one that is `CHECKED_OUT` is rejected with `ERR_INSTRUMENT_CHECKED_OUT`, and a `RETIRED` instrument is excluded from all further operations — a second retire attempt yields `ERR_INSTRUMENT_RETIRED`."

    Design: Corner/endpoints/retire_checked_out_instrument_rejected
    """
    _program, _student, instrument, _asg = setup_assignment(
        instrument_overrides={"serial_number": "SN-RC-1",
                              "instrument_type": "HORN"})
    assert get_instrument(instrument["id"])["status"] == "CHECKED_OUT"

    resp = api.retire_instrument(instrument["id"], equipment_headers)
    validate_error(resp, ApiErrorId.ERR_INSTRUMENT_CHECKED_OUT)
    assert get_instrument(instrument["id"])["status"] == "CHECKED_OUT"


def test_clock_advance_flips_active_assignment_to_overdue(api, director_headers,
                                                          reader_headers):
    """PRD §2.6: "Two transitions are driven this way: an `InstrumentAssignment` whose `due_date` has passed while still `ACTIVE` flips to `OVERDUE`, and a `MusicArrangement` whose `rights_end` has passed while still `LICENSED_ACTIVE` flips to `EXPIRED`." PRD §3.3: "When the logical clock passes an assignment's `due_date` while it is still `ACTIVE`, the assignment flips to `OVERDUE` — evaluated lazily when the clock is set and whenever the assignment is read."

    Design: Corner/state_machines/assignment_auto_overdue_on_clock_advance
    """
    _program, _student, _instrument, asg = setup_assignment(
        due_date="2026-08-10T00:00:00Z",
        instrument_overrides={"serial_number": "SN-OD-1",
                              "instrument_type": "HORN"})
    assert asg["status"] == "ACTIVE"

    advance_clock("2026-08-11T00:00:00Z")
    fetched = validate_success(api.get_instrument_assignment(asg["id"],
                                                             reader_headers))
    assert fetched["status"] == "OVERDUE"


def test_overdue_return_posts_weekly_late_fee(api, reader_headers):
    """PRD §3.3: "If the assignment was `OVERDUE` — that is, `returned_at` is strictly after `due_date` — a late fee accrues: the number of days from `due_date` to `returned_at`, rounded up to whole days and then to whole weeks, at 500 cents per week, recorded as `late_fee_cents` and posted as a `LATE_FEE_DEBIT`; a return on or before `due_date` leaves `late_fee_cents` at zero."

    Design: Corner/state_machines/overdue_return_posts_late_fee
    """
    program, student, instrument, asg = setup_assignment(
        due_date="2026-08-10T00:00:00Z",
        instrument_overrides={"serial_number": "SN-LF-1",
                              "instrument_type": "HORN"})
    advance_clock("2026-08-31T00:00:00Z")  # 21 days past due -> 3 weeks

    returned = validate_success(api.return_instrument_assignment(
        asg["id"], return_assignment_payload("PASS"), EQUIPMENT))
    assert returned["status"] == "RETURNED"
    assert returned["late_fee_cents"] == 1500, "ceil(21/7) = 3 weeks x 500"

    ledger, meta = validate_paginated(api.get_student_ledger(student["id"],
                                                             reader_headers))
    assert meta["total_count"] == 2
    amounts = sorted((row["kind"], row["amount_cents"]) for row in ledger)
    assert amounts == [("LATE_FEE_DEBIT", 1500), ("RENTAL_FEE_DEBIT", 15000)]
    assert get_student(student["id"])["account_balance_cents"] == 16500
    assert get_instrument(instrument["id"])["status"] == "AVAILABLE", (
        "PASS inspection restores availability")
    _ = program


def test_return_twice_rejected_without_double_posting(api, equipment_headers,
                                                      reader_headers):
    """PRD §3.3: "The `EquipmentManager` returns an assignment in `ACTIVE` or `OVERDUE` (else `ERR_ASSIGNMENT_NOT_ACTIVE`), supplying an `inspection_result`."

    Design: Corner/state_machines/invalid_from_state_return_twice_rejected
    """
    _program, student, _instrument, asg = setup_assignment(
        due_date="2026-08-20T00:00:00Z",
        instrument_overrides={"serial_number": "SN-IT-1",
                              "instrument_type": "HORN"})
    validate_success(api.return_instrument_assignment(
        asg["id"], return_assignment_payload("PASS"), equipment_headers))

    again = api.return_instrument_assignment(
        asg["id"], return_assignment_payload("PASS"), equipment_headers)
    validate_error(again, ApiErrorId.ERR_ASSIGNMENT_NOT_ACTIVE)

    ledger, meta = validate_paginated(api.get_student_ledger(student["id"],
                                                             reader_headers))
    assert meta["total_count"] == 1, "the rejected return posts nothing"
    assert ledger[0]["kind"] == "RENTAL_FEE_DEBIT"
    assert get_student(student["id"])["account_balance_cents"] == 15000
