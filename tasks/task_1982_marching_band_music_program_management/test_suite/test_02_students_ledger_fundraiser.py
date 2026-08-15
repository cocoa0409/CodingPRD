"""Students and the append-only ledger: delinquency boundary, withdrawal cascade,
pagination, waterfall allocation, refunds, balance reconciliation, fundraiser
credits, and immediate read-after-write consistency."""
from test_helpers import (
    DIRECTOR_HEADERS,
    EQUIPMENT_HEADERS,
    NON_EXISTENT_UUID,
    TREASURER_HEADERS,
    ApiErrorId,
    assert_student,
    checkout_instrument,
    close_fundraiser,
    confirm_enrollment,
    create_enrolled_student,
    create_fundraiser,
    create_instrument,
    create_open_program,
    create_student,
    create_uniform,
    enroll_in_trip,
    get_student,
    issue_uniform,
    post_payment,
    setup_trip_with_open_roster,
    validate_error,
    validate_paginated,
    validate_success,
)

DIRECTOR_H = DIRECTOR_HEADERS
EQUIPMENT_H = EQUIPMENT_HEADERS
TREASURER_H = TREASURER_HEADERS


# --- Corner: students listing / lookup / ledger reads --------------------------

def test_get_nonexistent_student_returns_student_not_found(api, reader_headers):
    """PRD §2.11 item 4: "Path identifiers exist, validated left to right — else the corresponding `ERR_<RESOURCE>_NOT_FOUND`."

    Design: Corner/entities/get_nonexistent_student_returns_not_found
    """
    resp = api.get_student(NON_EXISTENT_UUID, reader_headers)
    validate_error(resp, ApiErrorId.ERR_STUDENT_NOT_FOUND)


def test_students_list_pagination_envelope(api, reader_headers):
    """PRD §2.3: "The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0. All list endpoints sort by `created_at` ascending. The `meta` object of every list response carries `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/students_list_pagination_envelope
    """
    program = create_open_program(season_name="PG")
    for i in range(3):
        create_student(program["id"], full_name=f"P{i + 1}")

    page1, meta1 = validate_paginated(api.list_students(
        reader_headers, params={"program_id": program["id"], "limit": 2,
                                "offset": 0}))
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert meta1["limit"] == 2 and meta1["offset"] == 0

    page2, meta2 = validate_paginated(api.list_students(
        reader_headers, params={"program_id": program["id"], "limit": 2,
                                "offset": 2}))
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False

    ids_in_order = [row["created_at"] for row in page1 + page2]
    assert ids_in_order == sorted(ids_in_order), (
        "list endpoints sort by created_at ascending")


def test_payment_rows_carry_only_id_and_created_at(api, reader_headers):
    """PRD §2.4: "`Payment` rows and `TruckLoad` rows are append-only ledger and manifest records: they carry only `id` and `created_at`, and both `updated_at` and `version` are absent from them entirely."

    Design: Corner/entities/payment_immutable_append_only_no_update_endpoint
    """
    program = create_open_program(season_name="IM")
    student = create_enrolled_student(program["id"], full_name="Led")
    payment = post_payment(student["id"], "MANUAL_DEBIT", 700)

    fetched = validate_success(api.get_payment(payment["id"], reader_headers))
    assert "id" in fetched and "created_at" in fetched
    assert "version" not in fetched, "append-only Payment must not expose version"
    assert "updated_at" not in fetched, (
        "append-only Payment must not expose updated_at")


def test_student_ledger_lists_that_students_rows(api, reader_headers):
    """PRD §4: "GET | `/band/students/{id}/ledger` | List a student's payment ledger | Any". PRD §2.7: "A student's `account_balance_cents` is derived from the ledger alone: the sum of the amounts of all debit-kind rows (`MANUAL_DEBIT`, `RENTAL_FEE_DEBIT`, `LATE_FEE_DEBIT`, `CLEANING_FEE_DEBIT`, `TRIP_SHARE_DEBIT`), minus the sum of the amounts of all credit-kind rows (`PAYMENT`, `WAIVER`, `FUNDRAISING_CREDIT`), plus the sum of the amounts of all `REFUND` rows."

    Design: Corner/endpoints/ledger_subresource_reverse_reachability
    """
    program = create_open_program(season_name="LG")
    student = create_enrolled_student(program["id"], full_name="LG")
    other = create_enrolled_student(program["id"], full_name="Other")
    post_payment(student["id"], "MANUAL_DEBIT", 1200)
    post_payment(student["id"], "PAYMENT", 200)
    post_payment(other["id"], "MANUAL_DEBIT", 99999)

    rows, meta = validate_paginated(api.get_student_ledger(student["id"],
                                                           reader_headers))
    assert meta["total_count"] == 2, "ledger returns exactly this student's rows"
    kinds = sorted((row["kind"], row["amount_cents"]) for row in rows)
    assert kinds == [("MANUAL_DEBIT", 1200), ("PAYMENT", 200)]
    assert all(row["student_id"] == student["id"] for row in rows)
    assert get_student(student["id"])["account_balance_cents"] == 1000


# --- Corner: waterfall, refunds, reconciliation, fundraiser --------------------

def test_payment_waterfall_allocates_oldest_debit_first(api, reader_headers):
    """PRD §3.7: "The student's outstanding debits — debit-kind rows whose posted `amount_cents` exceeds the sum of allocations already applied to them — are walked in order of `created_at` ascending with ties broken by `amount_cents` ascending, never by identifier. The payment applies to each debit in turn the lesser of the payment's remaining amount and that debit's outstanding remainder, recording each application as an entry in the payment's `allocations` list, where each entry pairs the settled debit's identifier `debit_payment_id` with the applied amount `applied_cents`."

    Design: Corner/calculations/payment_waterfall_allocates_oldest_first
    """
    program = create_open_program(season_name="WF")
    student = create_enrolled_student(program["id"], full_name="WF")
    debit1 = post_payment(student["id"], "MANUAL_DEBIT", 3000)
    debit2 = post_payment(student["id"], "MANUAL_DEBIT", 4000)

    payment = post_payment(student["id"], "PAYMENT", 5000)
    fetched = validate_success(api.get_payment(payment["id"], reader_headers))
    assert fetched["allocations"] == [
        {"debit_payment_id": debit1["id"], "applied_cents": 3000},
        {"debit_payment_id": debit2["id"], "applied_cents": 2000},
    ], "waterfall settles the oldest debit first, then the remainder"
    assert get_student(student["id"])["account_balance_cents"] == 2000


def test_refund_cannot_exceed_net_cash_paid(api):
    """PRD §2.7: "A `REFUND` or `WAIVER` row must name the row it compensates via `reference_payment_id`, and a refund may not exceed the student's net cash paid — the sum of all `PAYMENT` rows minus the sum of all `REFUND` rows across the student's ledger — else `ERR_REFUND_EXCEEDS_PAID` (HTTP 422)."

    Design: Corner/validations/refund_exceeds_net_paid_rejected
    """
    program = create_open_program(season_name="RX")
    student = create_enrolled_student(program["id"], full_name="RX")
    payment = post_payment(student["id"], "PAYMENT", 5000)

    over = api.create_payment(
        {"student_id": student["id"], "kind": "REFUND", "amount_cents": 6000,
         "reference_payment_id": payment["id"]}, TREASURER_H)
    validate_error(over, ApiErrorId.ERR_REFUND_EXCEEDS_PAID)

    exact = post_payment(student["id"], "REFUND", 5000,
                         reference_payment_id=payment["id"])
    assert exact["amount_cents"] == 5000
    assert get_student(student["id"])["account_balance_cents"] == 0, (
        "PAYMENT 5000 then REFUND 5000 nets to zero")


def test_balance_reconciles_across_interleaved_mixed_rows(api):
    """PRD §2.7: "A student's `account_balance_cents` is derived from the ledger alone: the sum of the amounts of all debit-kind rows (`MANUAL_DEBIT`, `RENTAL_FEE_DEBIT`, `LATE_FEE_DEBIT`, `CLEANING_FEE_DEBIT`, `TRIP_SHARE_DEBIT`), minus the sum of the amounts of all credit-kind rows (`PAYMENT`, `WAIVER`, `FUNDRAISING_CREDIT`), plus the sum of the amounts of all `REFUND` rows." PRD §2.8: "a balance exactly equal to the threshold is not delinquent."

    Design: Corner/cross_cutting_layers/student_balance_reconciles_across_mixed_debits
    """
    program = create_open_program(season_name="DR")
    student = create_enrolled_student(program["id"], full_name="DR")

    post_payment(student["id"], "MANUAL_DEBIT", 3000)
    assert get_student(student["id"])["account_balance_cents"] == 3000
    payment = post_payment(student["id"], "PAYMENT", 1000)
    assert get_student(student["id"])["account_balance_cents"] == 2000
    post_payment(student["id"], "REFUND", 400, reference_payment_id=payment["id"])
    assert get_student(student["id"])["account_balance_cents"] == 2400
    post_payment(student["id"], "WAIVER", 500, reference_payment_id=payment["id"])

    student = get_student(student["id"])
    assert_student(student)
    assert student["account_balance_cents"] == 1900, (
        "3000 debit - 1000 payment + 400 refund - 500 waiver")
    assert student["is_delinquent"] is False, "1900 is not strictly above grace 2500"


def test_fundraiser_close_largest_remainder_is_lossless(api, reader_headers):
    """PRD §3.7: "The close allocates `raised_cents` across participants by largest remainder: each participant's raw share is `raised_cents` multiplied by their hours divided by the total hours across all participants; each base share is that raw share floored to whole cents; the leftover cents — `raised_cents` minus the sum of base shares — are distributed one cent at a time to participants in descending order of fractional remainder, ties broken by the participant student's `created_at` ascending, never by identifier." PRD §3.7: "The allocation is lossless: the fundraiser's `allocated_credit_cents` always equals `raised_cents` exactly, and the fundraiser moves to `CREDITED`."

    Design: Corner/calculations/fundraiser_largest_remainder_lossless_allocation
    """
    program = create_open_program(season_name="FR")
    student_a = create_enrolled_student(program["id"], full_name="FA")
    student_b = create_enrolled_student(program["id"], full_name="FB")
    student_c = create_enrolled_student(program["id"], full_name="FC")
    fundraiser = create_fundraiser(program["id"], name="Car Wash")

    closed = close_fundraiser(
        fundraiser["id"], 10001,
        [{"student_id": student_a["id"], "hours": 1},
         {"student_id": student_b["id"], "hours": 1},
         {"student_id": student_c["id"], "hours": 1}])
    assert closed["status"] == "CREDITED"
    assert closed["raised_cents"] == 10001
    assert closed["allocated_credit_cents"] == 10001, "allocation is lossless"

    # 10001 / 3 -> floor 3333 each, remainder 2 to the two earliest-created
    assert get_student(student_a["id"])["account_balance_cents"] == -3334
    assert get_student(student_b["id"])["account_balance_cents"] == -3334
    assert get_student(student_c["id"])["account_balance_cents"] == -3333

    credits, meta = validate_paginated(api.list_payments(
        reader_headers, params={"fundraiser_id": fundraiser["id"],
                                "kind": "FUNDRAISING_CREDIT"}))
    assert meta["total_count"] == 3
    assert sum(row["amount_cents"] for row in credits) == 10001


# --- Corner: reinstate gate + immediate consistency ----------------------------

def test_reinstate_blocked_while_balance_above_grace(api, director_headers,
                                                     treasurer_headers):
    """PRD §3.2: "Reinstatement additionally requires the student's `account_balance_cents` to be no greater than the program's `delinquency_grace_cents` — a balance strictly above the grace blocks reinstatement with `ERR_STUDENT_DELINQUENT_FEES`."

    Design: Corner/validations/reinstate_blocked_while_delinquent
    """
    program = create_open_program(season_name="RI")
    student = create_enrolled_student(program["id"], full_name="RI")
    post_payment(student["id"], "MANUAL_DEBIT", 3000)
    validate_success(api.suspend_student(student["id"], director_headers))

    blocked = api.reinstate_student(student["id"], director_headers)
    validate_error(blocked, ApiErrorId.ERR_STUDENT_DELINQUENT_FEES)
    assert get_student(student["id"])["enrollment_status"] == "SUSPENDED"

    post_payment(student["id"], "PAYMENT", 500)  # balance == 2500 == grace
    reinstated = validate_success(api.reinstate_student(student["id"],
                                                        director_headers))
    assert reinstated["enrollment_status"] == "ENROLLED"


def test_assignment_side_effects_visible_immediately(api, reader_headers):
    """PRD §2.12: "Derived aggregates — `music_spent_cents`, `repair_spent_cents`, `garment_count`, `registered_count`, `confirmed_count`, `loaded_weight_lb`, `loaded_volume_cuft`, `allocated_credit_cents`, and the student's `account_balance_cents` and `is_delinquent` — are recomputed from their source rows on every mutation that touches them, never patched incrementally in a way that could drift." PRD §3.3: "On success the assignment starts `ACTIVE`, the instrument moves to `CHECKED_OUT`, and the rental fee accrues."

    Design: Corner/consistency_model/immediate_consistency_post_then_get
    """
    program = create_open_program(season_name="IC")
    student = create_enrolled_student(program["id"], full_name="IC")
    instrument = create_instrument(program["id"], serial_number="SN-IC-1",
                                   instrument_type="HORN")

    assignment = checkout_instrument(student["id"], instrument["id"],
                                     "2026-08-20T00:00:00Z")
    assert assignment["status"] == "ACTIVE"

    student = get_student(student["id"])
    assert student["account_balance_cents"] == 15000, (
        "FLAT default rental fee is visible on the very next read")
    fetched = validate_success(api.get_instrument(instrument["id"], reader_headers))
    assert fetched["status"] == "CHECKED_OUT"


# --- Difficulty: delinquency_grace_strict_greater_boundary ----------------------

def _setup_delinquency_boundary_trip():
    program = create_open_program(season_name="DG", delinquency_grace_cents=2500)
    _program, _event, trip = setup_trip_with_open_roster(
        program_id=program["id"], capacity=5, estimated_cost_cents=5000,
        departure_at="2026-09-15T06:00:00Z")
    student_edge = create_enrolled_student(program["id"], full_name="Edge")
    post_payment(student_edge["id"], "MANUAL_DEBIT", 2500)
    student_over = create_enrolled_student(program["id"], full_name="Over")
    post_payment(student_over["id"], "MANUAL_DEBIT", 2501)
    return program, trip, student_edge, student_over


def test_delinquency_boundary_trip_enrollment_gate(api):
    """PRD §2.8: "A student whose `account_balance_cents` is strictly greater than this threshold is delinquent, surfaced as the derived boolean `is_delinquent`; a balance exactly equal to the threshold is not delinquent." PRD §2.8: "Delinquency has teeth in three places: creating a new financial obligation for the student (checking out an instrument, or enrolling in a trip) is rejected with `ERR_STUDENT_DELINQUENT_FEES` (HTTP 402), and reinstating a suspended student is likewise rejected with `ERR_STUDENT_DELINQUENT_FEES` while the balance remains strictly above the grace amount."

    Design: Difficulty/boundary_precision_check/delinquency_grace_strict_greater_boundary
    """
    _program, trip, student_edge, student_over = _setup_delinquency_boundary_trip()

    assert get_student(student_edge["id"])["is_delinquent"] is False
    assert get_student(student_over["id"])["is_delinquent"] is True

    enrolled = enroll_in_trip(trip["id"], student_edge["id"])
    assert enrolled["attendance_status"] == "REGISTERED", (
        "balance exactly at grace is not delinquent; enrollment succeeds")

    rejected = api.create_trip_enrollment(
        {"trip_id": trip["id"], "student_id": student_over["id"]}, DIRECTOR_H)
    validate_error(rejected, ApiErrorId.ERR_STUDENT_DELINQUENT_FEES)


def test_delinquency_boundary_instrument_checkout_gate(api):
    """PRD §2.8: "Delinquency has teeth in three places: creating a new financial obligation for the student (checking out an instrument, or enrolling in a trip) is rejected with `ERR_STUDENT_DELINQUENT_FEES` (HTTP 402), and reinstating a suspended student is likewise rejected with `ERR_STUDENT_DELINQUENT_FEES` while the balance remains strictly above the grace amount." PRD §2.8: "A student whose `account_balance_cents` is strictly greater than this threshold is delinquent, surfaced as the derived boolean `is_delinquent`; a balance exactly equal to the threshold is not delinquent."

    Design: Difficulty/boundary_precision_check/delinquency_grace_strict_greater_boundary
    """
    program, _trip, student_edge, student_over = _setup_delinquency_boundary_trip()
    inst_edge = create_instrument(program["id"], serial_number="SN-DG-1",
                                  instrument_type="HORN")
    inst_over = create_instrument(program["id"], serial_number="SN-DG-2",
                                  instrument_type="TUBA")

    accepted = checkout_instrument(student_edge["id"], inst_edge["id"],
                                   "2026-08-20T00:00:00Z")
    assert accepted["status"] == "ACTIVE", "2500 == grace: not delinquent"

    rejected = api.create_instrument_assignment(
        {"student_id": student_over["id"], "instrument_id": inst_over["id"],
         "due_date": "2026-08-20T00:00:00Z"}, EQUIPMENT_H)
    validate_error(rejected, ApiErrorId.ERR_STUDENT_DELINQUENT_FEES)


# --- Difficulty: student_withdraw_cascades_assets_and_enrollment ----------------

def test_withdraw_forces_asset_returns(api, director_headers, reader_headers):
    """PRD §3.2: "Each instrument assignment in `ACTIVE` or `OVERDUE` is forced to `RETURNED`, with any late fee computed against the assignment's `due_date` as of the logical clock posted as a `LATE_FEE_DEBIT`, and the instrument itself moved to `RETURN_PENDING_INSPECTION`. Each uniform assignment still `ISSUED` is forced to `RETURNED` with `soiling_level` recorded as `NORMAL`, moving the garment to `RETURNED_DIRTY`."

    Design: Difficulty/transitive_cascade/student_withdraw_cascades_assets_and_enrollment
    """
    program = create_open_program(season_name="WD")
    student = create_enrolled_student(program["id"], full_name="WD", grade=11,
                                      section="PERCUSSION")
    instrument = create_instrument(program["id"], serial_number="SN-WD-1",
                                   instrument_type="SNARE",
                                   replacement_value_cents=30000)
    assignment = checkout_instrument(student["id"], instrument["id"],
                                     "2026-08-20T00:00:00Z")
    uniform = create_uniform(program["id"], garment_type="JACKET", size_label="M")
    uniform_assignment = issue_uniform(student["id"], uniform["id"])

    withdrawn = validate_success(api.withdraw_student(student["id"],
                                                      director_headers))
    assert withdrawn["enrollment_status"] == "WITHDRAWN"

    assignment = validate_success(
        api.get_instrument_assignment(assignment["id"], reader_headers))
    assert assignment["status"] == "RETURNED"
    assert assignment["late_fee_cents"] == 0, "not overdue at the default clock"

    instrument = validate_success(api.get_instrument(instrument["id"],
                                                     reader_headers))
    assert instrument["status"] == "RETURN_PENDING_INSPECTION"

    uniform_assignment = validate_success(
        api.get_uniform_assignment(uniform_assignment["id"], reader_headers))
    assert uniform_assignment["status"] == "RETURNED"
    assert uniform_assignment["soiling_level"] == "NORMAL"
    uniform = validate_success(api.get_uniform(uniform["id"], reader_headers))
    assert uniform["status"] == "RETURNED_DIRTY"

    student = get_student(student["id"])
    assert student["account_balance_cents"] == 15000, (
        "the FLAT rental debit survives withdrawal; no refund applies")


def test_withdraw_excuses_trip_seat_with_tiered_refund_and_promotion(
        api, director_headers, reader_headers):
    """PRD §3.2: "Each trip enrollment whose attendance is `REGISTERED` or `CONFIRMED` is moved to `EXCUSED`, with a refund computed under the tiered withdrawal policy of §3.6 posted as a `REFUND` payment, and each freed seat triggers the waitlist promotion of §3.6." PRD §3.6: "at least 14 days out, the full net paid amount is refunded; from 7 up to but not including 14 days, half; under 7 days, nothing."

    Design: Difficulty/transitive_cascade/student_withdraw_cascades_assets_and_enrollment
    """
    program, _event, trip = setup_trip_with_open_roster(
        capacity=1, estimated_cost_cents=8000,
        departure_at="2026-09-15T06:00:00Z")
    student_a = create_enrolled_student(program["id"], full_name="WA")
    student_b = create_enrolled_student(program["id"], full_name="WB")
    enrollment_a = enroll_in_trip(trip["id"], student_a["id"])
    enrollment_b = enroll_in_trip(trip["id"], student_b["id"])
    assert enrollment_b["attendance_status"] == "WAITLISTED"
    post_payment(student_a["id"], "PAYMENT", 8000,
                 trip_enrollment_id=enrollment_a["id"])
    confirm_enrollment(enrollment_a["id"])

    validate_success(api.withdraw_student(student_a["id"], director_headers))

    enrollment_a = validate_success(
        api.get_trip_enrollment(enrollment_a["id"], reader_headers))
    assert enrollment_a["attendance_status"] == "EXCUSED"
    assert enrollment_a["payment_status"] == "REFUNDED"
    assert enrollment_a["refunded_cents"] == 8000, (
        "45 days to departure is the 100-percent tier")
    assert get_student(student_a["id"])["account_balance_cents"] == 0

    enrollment_b = validate_success(
        api.get_trip_enrollment(enrollment_b["id"], reader_headers))
    assert enrollment_b["attendance_status"] == "REGISTERED", (
        "the freed seat promotes the waitlisted enrollment")
    assert enrollment_b["provisional_share_cents"] == 8000, (
        "sole registrant: estimated 8000 over a roster count of 1")
