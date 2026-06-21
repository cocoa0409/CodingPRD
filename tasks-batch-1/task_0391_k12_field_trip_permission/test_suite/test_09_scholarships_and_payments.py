"""Scholarship fee reduction, pool-fund conservation, and the fiscal / capacity /
temporal validation rules at the slip and trip level.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    make_teacher_headers,
    make_guardian_headers,
    create_draft_trip,
    create_approved_trip,
    create_teacher_guardian,
    create_guardian,
    create_student,
    create_signed_slip,
    create_slip,
    add_emergency_contact,
    sign_slip,
    create_scholarship_pool,
    create_scholarship_grant_payload,
)


_PRINCIPAL = TEST_USERS["principal_headers"]


# ─────────────────────────────────────────────────────────────────────────────
# Corner/calculations
# ─────────────────────────────────────────────────────────────────────────────
def test_scholarship_reduces_fee_due_correctly(api):
    """PRD §3.7: "Because the deposit is never waivable, the effective scholarship is the smaller of that scholarship sum and the waivable amount, where the waivable amount is the gross minus the trip's `deposit_cents` but never less than zero. The fee owed, `fee_due_cents`, is the gross minus the effective scholarship."

    gross 2000, deposit 500, waivable 1500, grant 1000 → effective 1000,
    fee_due = 2000 - 1000 = 1000; scholarship_award_cents = 1000.

    Design: Corner/calculations/scholarship_reduces_fee_due_correctly
    """
    teacher_id, trip = create_approved_trip(
        grade_band="ELEMENTARY", capacity=5, base_fee_cents=2000,
        transport_cost_cents=0, deposit_cents=500,
    )
    trip_id = trip["id"]
    g = create_guardian(full_name="G17c")
    st = create_student(teacher_id, full_name="S17c", grade_level=5)
    slip = create_signed_slip(teacher_id, trip_id, st["id"], g["id"])
    pool = create_scholarship_pool(name="P17", total_cents=100_000)
    teacher = make_teacher_headers(teacher_id)
    validate_success(
        api.create_scholarship_grant(trip_id, slip["id"],
                                     create_scholarship_grant_payload(pool["id"], 1000), teacher), 201
    )
    slip = get_success_data(api.get_permission_slip(slip["id"], teacher))
    assert slip["scholarship_award_cents"] == 1000
    assert slip["fee_due_cents"] == 1000, (
        f"fee_due should be gross 2000 - min(1000, waivable 1500) = 1000, got {slip['fee_due_cents']}"
    )


def test_scholarship_pool_conserved_on_grant_revoke(api):
    """PRD §2.9: "A `ScholarshipPool`'s `granted_cents` always equals the sum of `award_cents` over that pool's `ACTIVE` grants, and its `remaining_cents` is the pool's `total_cents` minus `granted_cents`; granting an award draws the pool down and revoking that award returns the funds, leaving the pool whole."

    100000 → 99000 after a 1000 grant → 100000 after revoke.

    Design: Corner/calculations/scholarship_pool_conserved_on_grant_revoke
    """
    teacher_id, trip = create_approved_trip(
        grade_band="ELEMENTARY", capacity=5, base_fee_cents=2000,
        transport_cost_cents=0, deposit_cents=500,
    )
    trip_id = trip["id"]
    g = create_guardian(full_name="G18c")
    st = create_student(teacher_id, full_name="S18c", grade_level=5)
    slip = create_signed_slip(teacher_id, trip_id, st["id"], g["id"])
    pool = create_scholarship_pool(name="P18", total_cents=100_000)
    teacher = make_teacher_headers(teacher_id)
    grant = validate_success(
        api.create_scholarship_grant(trip_id, slip["id"],
                                     create_scholarship_grant_payload(pool["id"], 1000), teacher), 201
    )
    pool_mid = get_success_data(api.get_scholarship_pool(pool["id"], teacher))
    assert pool_mid["remaining_cents"] == 99_000, (
        f"remaining should drop to 99000 after grant, got {pool_mid['remaining_cents']}"
    )
    validate_success(api.revoke_scholarship_grant(trip_id, slip["id"], grant["id"], teacher), 200)
    pool_after = get_success_data(api.get_scholarship_pool(pool["id"], teacher))
    assert pool_after["remaining_cents"] == 100_000, (
        f"remaining should return to 100000 after revoke, got {pool_after['remaining_cents']}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Corner/validations
# ─────────────────────────────────────────────────────────────────────────────
def test_payment_amount_mismatch_returns_error(api):
    """PRD §3.7: "requires the submitted `amount_cents` to equal the slip's current `fee_due_cents` exactly (`ERR_PAYMENT_AMOUNT_MISMATCH`)."

    Paying 999 when fee_due is 1000 → ERR_PAYMENT_AMOUNT_MISMATCH; payment stays
    UNPAID.

    Design: Corner/validations/payment_amount_mismatch_returns_error
    """
    teacher_id, trip = create_approved_trip(
        grade_band="ELEMENTARY", capacity=5, base_fee_cents=1000,
        transport_cost_cents=0, deposit_cents=0,
    )
    trip_id = trip["id"]
    g = create_guardian(full_name="G19c")
    st = create_student(teacher_id, full_name="S19c", grade_level=5)
    slip = create_signed_slip(teacher_id, trip_id, st["id"], g["id"])
    validate_error(
        api.pay_slip(trip_id, slip["id"], {"amount_cents": 999}, make_guardian_headers(g["id"])),
        "ERR_PAYMENT_AMOUNT_MISMATCH",
    )
    slip = get_success_data(api.get_permission_slip(slip["id"], make_teacher_headers(teacher_id)))
    assert slip["payment_status"] == "UNPAID"


def test_scholarship_pool_exhausted_returns_error(api):
    """PRD §3.7: "The award is bounded twice: it must not exceed the pool's `remaining_cents`, or it is rejected with `ERR_SCHOLARSHIP_POOL_EXHAUSTED..."

    Granting 600 from a pool with only 500 remaining → ERR_SCHOLARSHIP_POOL_EXHAUSTED;
    pool unchanged.

    Design: Corner/validations/scholarship_pool_exhausted_returns_error
    """
    teacher_id, trip = create_approved_trip(
        grade_band="ELEMENTARY", capacity=5, base_fee_cents=2000,
        transport_cost_cents=0, deposit_cents=0,
    )
    trip_id = trip["id"]
    g = create_guardian(full_name="G20c")
    st = create_student(teacher_id, full_name="S20c", grade_level=5)
    slip = create_signed_slip(teacher_id, trip_id, st["id"], g["id"])
    pool = create_scholarship_pool(name="P20", total_cents=500)
    teacher = make_teacher_headers(teacher_id)
    validate_error(
        api.create_scholarship_grant(trip_id, slip["id"],
                                     create_scholarship_grant_payload(pool["id"], 600), teacher),
        "ERR_SCHOLARSHIP_POOL_EXHAUSTED",
    )
    pool = get_success_data(api.get_scholarship_pool(pool["id"], teacher))
    assert pool["remaining_cents"] == 500


def test_trip_at_capacity_blocks_sign(api):
    """PRD §3.3: "The trip must have room: if the trip's `signed_count` has already reached `capacity`, a further sign is rejected with `ERR_TRIP_AT_CAPACITY`."

    Capacity 1, one slip already SIGNED; signing a second → ERR_TRIP_AT_CAPACITY;
    signed_count stays 1.

    Design: Corner/validations/trip_at_capacity_blocks_sign
    """
    teacher_id, trip = create_approved_trip(grade_band="ELEMENTARY", capacity=1)
    trip_id = trip["id"]
    g_a = create_guardian(full_name="G21a")
    st_a = create_student(teacher_id, full_name="S21a", grade_level=5)
    create_signed_slip(teacher_id, trip_id, st_a["id"], g_a["id"])
    g_b = create_guardian(full_name="G21b")
    st_b = create_student(teacher_id, full_name="S21b", grade_level=5)
    slip_b = create_slip(teacher_id, trip_id, st_b["id"], g_b["id"])
    add_emergency_contact(teacher_id, trip_id, slip_b["id"])
    validate_error(api.sign_slip(trip_id, slip_b["id"], make_guardian_headers(g_b["id"])),
                   "ERR_TRIP_AT_CAPACITY")
    trip = get_success_data(api.get_field_trip(trip_id, make_teacher_headers(teacher_id)))
    assert trip["signed_count"] == 1


def test_invalid_time_window_on_submit(api):
    """PRD §3.2: "Submission also revalidates the trip's bones: `return_at` must be strictly after `depart_at`, or the request fails with `ERR_INVALID_TIME_WINDOW..."

    Submitting a trip whose return_at equals depart_at → ERR_INVALID_TIME_WINDOW;
    trip stays DRAFT.

    Design: Corner/validations/invalid_time_window_on_submit
    """
    teacher_id = create_teacher_guardian()
    trip = create_draft_trip(
        teacher_id, grade_band="HIGH", capacity=5,
        depart_at="2026-11-21T09:00:00Z", return_at="2026-11-21T09:00:00Z",
    )
    teacher = make_teacher_headers(teacher_id)
    validate_error(api.submit_trip(trip["id"], teacher), "ERR_INVALID_TIME_WINDOW")
    trip = get_success_data(api.get_field_trip(trip["id"], teacher))
    assert trip["status"] == "DRAFT"
