"""Error catalogue corner cases, RBAC role separation / ownership, OCC stale
version, derived-field reconciliation, and FK-filtered listing.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    build_user_headers,
    TEST_USERS,
    make_teacher_headers,
    make_guardian_headers,
    create_draft_trip,
    create_approved_trip,
    create_teacher_guardian,
    create_guardian,
    create_student,
    create_slip,
    create_signed_slip,
    add_emergency_contact,
    pay_slip,
    create_vehicle,
    create_confirmed_booking,
    create_cleared_chaperone,
    create_scholarship_pool,
    create_scholarship_grant_payload,
    get_trip_version,
    create_field_trip_payload,
)


_PRINCIPAL = TEST_USERS["principal_headers"]
_DISTRICT = TEST_USERS["district_admin_headers"]


# ─────────────────────────────────────────────────────────────────────────────
# Corner/errors
# ─────────────────────────────────────────────────────────────────────────────
def test_guardian_email_taken_returns_conflict(api):
    """PRD §3.1: "an attempt to register a second guardian with an `email` already on file is rejected with `ERR_GUARDIAN_EMAIL_TAKEN`."

    Design: Corner/errors/guardian_email_taken_returns_conflict
    """
    validate_success(
        api.create_guardian({"full_name": "First", "email": "dup@x.com", "phone": "555-3001"},
                            _DISTRICT), 201
    )
    validate_error(
        api.create_guardian({"full_name": "Second", "email": "dup@x.com", "phone": "555-3002"},
                            _DISTRICT),
        "ERR_GUARDIAN_EMAIL_TAKEN",
    )


def test_award_exceeds_waivable_returns_error(api):
    """PRD §3.7: "and it must not exceed the slip's waivable amount — the gross fee minus the trip's `deposit_cents` — or it is rejected with `ERR_AWARD_EXCEEDS_WAIVABLE`."

    gross 2000, deposit 500 → waivable 1500; a 2000 award (pool richly funded) →
    ERR_AWARD_EXCEEDS_WAIVABLE; pool unchanged.

    Design: Corner/errors/award_exceeds_waivable_returns_error
    """
    teacher_id, trip = create_approved_trip(
        grade_band="ELEMENTARY", capacity=5, base_fee_cents=2000,
        transport_cost_cents=0, deposit_cents=500,
    )
    trip_id = trip["id"]
    g = create_guardian(full_name="G23c")
    st = create_student(teacher_id, full_name="S23c", grade_level=5)
    slip = create_signed_slip(teacher_id, trip_id, st["id"], g["id"])
    pool = create_scholarship_pool(name="P23", total_cents=100_000)
    teacher = make_teacher_headers(teacher_id)
    validate_error(
        api.create_scholarship_grant(trip_id, slip["id"],
                                     create_scholarship_grant_payload(pool["id"], 2000), teacher),
        "ERR_AWARD_EXCEEDS_WAIVABLE",
    )
    pool = get_success_data(api.get_scholarship_pool(pool["id"], teacher))
    assert pool["remaining_cents"] == 100_000


def test_student_not_found_on_slip_create(api):
    """PRD §2.6: "Foreign-key identifiers supplied in a request body are validated the same way: a missing `student_id` yields `ERR_STUDENT_NOT_FOUND..."

    Design: Corner/errors/student_not_found_on_slip_create
    """
    teacher_id = create_teacher_guardian()
    trip = create_draft_trip(teacher_id, grade_band="ELEMENTARY", capacity=5)
    g = create_guardian(full_name="G24c")
    validate_error(
        api.create_permission_slip(
            trip["id"],
            {"student_id": "00000000-0000-4000-8000-0000000000bb", "guardian_id": g["id"]},
            make_teacher_headers(teacher_id),
        ),
        "ERR_STUDENT_NOT_FOUND",
    )


def test_grant_revoke_already_revoked_returns_not_active(api):
    """PRD §3.7: "A `Teacher` or `Principal` may revoke an active grant, moving its `status` `ACTIVE → REVOKED`; revocation requires the grant to be `ACTIVE`, otherwise `ERR_GRANT_NOT_ACTIVE`."

    Revoking an already-REVOKED grant → ERR_GRANT_NOT_ACTIVE.

    Design: Corner/errors/grant_revoke_already_revoked_returns_not_active
    """
    teacher_id, trip = create_approved_trip(
        grade_band="ELEMENTARY", capacity=5, base_fee_cents=2000,
        transport_cost_cents=0, deposit_cents=0,
    )
    trip_id = trip["id"]
    g = create_guardian(full_name="G25c")
    st = create_student(teacher_id, full_name="S25c", grade_level=5)
    slip = create_signed_slip(teacher_id, trip_id, st["id"], g["id"])
    pool = create_scholarship_pool(name="P25", total_cents=100_000)
    teacher = make_teacher_headers(teacher_id)
    grant = validate_success(
        api.create_scholarship_grant(trip_id, slip["id"],
                                     create_scholarship_grant_payload(pool["id"], 1000), teacher), 201
    )
    validate_success(api.revoke_scholarship_grant(trip_id, slip["id"], grant["id"], teacher), 200)
    validate_error(api.revoke_scholarship_grant(trip_id, slip["id"], grant["id"], teacher),
                   "ERR_GRANT_NOT_ACTIVE")


# ─────────────────────────────────────────────────────────────────────────────
# Corner/rbac
# ─────────────────────────────────────────────────────────────────────────────
def test_guardian_cannot_create_field_trip(api):
    """PRD §2.1: "When the headers are valid but the role is not permitted to invoke the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §3.2: "A `Teacher` opens the lifecycle by creating a field trip, which begins in `DRAFT`."

    Creating a trip is a Teacher action; a Guardian invoking it → ERR_FORBIDDEN_ROLE.

    Design: Corner/rbac/guardian_cannot_create_field_trip
    """
    g = create_guardian(full_name="G26")
    payload = create_field_trip_payload(
        g["id"], title="Nope", grade_band="MIDDLE", capacity=5,
        base_fee_cents=0, transport_cost_cents=0,
        depart_at="2026-11-25T09:00:00Z", return_at="2026-11-25T12:00:00Z",
    )
    validate_error(api.create_field_trip(payload, make_guardian_headers(g["id"])),
                   "ERR_FORBIDDEN_ROLE")


def test_teacher_cannot_record_principal_approval(api):
    """PRD §2.1: "When the headers are valid but the role is not permitted to invoke the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §3.2: "A `Principal` records the principal step: a `PRINCIPAL`/`APPROVE` decision advances `PENDING_PRINCIPAL → PENDING_DISTRICT` and appends an approval record..."

    Recording the principal step is a Principal action; the requesting Teacher
    invoking it → ERR_FORBIDDEN_ROLE.

    Design: Corner/rbac/teacher_cannot_record_principal_approval
    """
    from test_helpers import create_pending_principal_trip
    teacher_id, trip = create_pending_principal_trip(grade_band="HIGH", capacity=5)
    validate_error(
        api.create_approval(trip["id"], {"step": "PRINCIPAL", "decision": "APPROVE"},
                            make_teacher_headers(teacher_id)),
        "ERR_FORBIDDEN_ROLE",
    )


def test_guardian_cannot_sign_other_guardians_slip(api):
    """PRD §3.3: "Signing is permitted only to the guardian named on the slip — when `X-User-ID` does not equal the slip's `guardian_id`, the request fails with `ERR_NOT_SLIP_GUARDIAN`."

    Design: Corner/rbac/guardian_cannot_sign_other_guardians_slip
    """
    teacher_id, trip = create_approved_trip(grade_band="ELEMENTARY", capacity=5)
    trip_id = trip["id"]
    g_a = create_guardian(full_name="G28a")
    g_b = create_guardian(full_name="G28b")
    st = create_student(teacher_id, full_name="S28", grade_level=5)
    slip = create_slip(teacher_id, trip_id, st["id"], g_a["id"])
    add_emergency_contact(teacher_id, trip_id, slip["id"])
    validate_error(api.sign_slip(trip_id, slip["id"], make_guardian_headers(g_b["id"])),
                   "ERR_NOT_SLIP_GUARDIAN")
    slip = get_success_data(api.get_permission_slip(slip["id"], make_teacher_headers(teacher_id)))
    assert slip["signature_status"] == "UNSIGNED"


def test_missing_user_context_header_returns_401(api):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 401)."

    A request carrying an unknown X-User-Role → that 401 error.

    Design: Corner/rbac/missing_user_context_header_returns_401
    """
    intruder = build_user_headers("intruder-1", "Intruder")
    validate_error(api.list_field_trips(intruder), "ERR_MISSING_OR_INVALID_USER_CONTEXT")


# ─────────────────────────────────────────────────────────────────────────────
# Corner/cross_cutting_complexity_layers
# ─────────────────────────────────────────────────────────────────────────────
def test_occ_stale_lock_version_rejected(api):
    """PRD §2.7: "The server compares it against the trip's current `version`; if another writer has advanced that version since the client read it — for instance by signing or revoking a slip, which bumps the trip — the lock is rejected with `ERR_STALE_TRIP_VERSION` (HTTP 412)."
    PRD §3.8: "The supplied `expected_trip_version` must match the trip's current `version`, otherwise the lock is superseded with `ERR_STALE_TRIP_VERSION` as described in §2.7."

    Capture the version, then a sign bumps it; locking with the stale version → 412.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_lock_version_rejected
    """
    teacher_id, trip = create_approved_trip(grade_band="HIGH", capacity=5,
                                            base_fee_cents=0, transport_cost_cents=0)
    trip_id = trip["id"]
    teacher = make_teacher_headers(teacher_id)
    # Make the trip lockable: 1 signed slip, 1 cleared chaperone, confirmed transport.
    g_a = create_guardian(full_name="G29a")
    st = create_student(teacher_id, full_name="S29", grade_level=9)
    slip = create_signed_slip(teacher_id, trip_id, st["id"], g_a["id"])
    create_cleared_chaperone(teacher_id, trip_id)
    vehicle = create_vehicle(label="Bus29", seat_capacity=10)
    create_confirmed_booking(teacher_id, trip_id, vehicle["id"], 1)
    # Capture the version now, then revoke + re-sign to bump it (making the captured
    # value stale) without leaving signed_count at 0.
    stale_version = get_trip_version(teacher_id, trip_id)
    validate_success(api.revoke_slip(trip_id, slip["id"], make_guardian_headers(g_a["id"])), 200)
    validate_success(api.sign_slip(trip_id, slip["id"], make_guardian_headers(g_a["id"])), 200)
    res = api.lock_roster(trip_id, {"expected_trip_version": stale_version}, teacher)
    validate_error(res, "ERR_STALE_TRIP_VERSION")
    trip = get_success_data(api.get_field_trip(trip_id, teacher))
    assert trip["status"] == "APPROVED", f"trip should stay APPROVED, got {trip['status']}"


def test_derived_field_collected_fees_recompute(api):
    """PRD §3.7: "On success the slip's `payment_status` becomes `PAID`, a `FeeTransaction` of `kind` `PAYMENT` and `reason` `GUARDIAN_PAYMENT` is appended with `amount_cents` equal to the positive fee, the slip's `net_paid_cents` is recomputed, and the trip's `collected_fees_cents` rises by the fee."

    A 1000 payment moves collected_fees_cents 0 → 1000 and net_paid_cents → 1000.

    Design: Corner/cross_cutting_complexity_layers/derived_field_collected_fees_recompute
    """
    teacher_id, trip = create_approved_trip(
        grade_band="ELEMENTARY", capacity=5, base_fee_cents=1000,
        transport_cost_cents=0, deposit_cents=0,
    )
    trip_id = trip["id"]
    g = create_guardian(full_name="G30c")
    st = create_student(teacher_id, full_name="S30c", grade_level=5)
    slip = create_signed_slip(teacher_id, trip_id, st["id"], g["id"])
    pay_slip(g["id"], trip_id, slip["id"], 1000)
    teacher = make_teacher_headers(teacher_id)
    trip = get_success_data(api.get_field_trip(trip_id, teacher))
    slip = get_success_data(api.get_permission_slip(slip["id"], teacher))
    assert trip["collected_fees_cents"] == 1000
    assert slip["net_paid_cents"] == 1000


def test_list_filter_by_fk_returns_subset(api):
    """PRD §2: "each resource has its own single-item read and a list read whose every foreign-key field doubles as an optional filter, so a child is always reachable by filtering its parent's identifier."
    PRD §3.3: "A slip records the `trip_id` it belongs to and exposes the derived `fee_due_cents`, `scholarship_award_cents`, `net_paid_cents`, and the `signed_at` timestamp described below."

    GET /permission-slips?trip_id=X returns only slips of trip X.

    Design: Corner/cross_cutting_complexity_layers/list_filter_by_fk_returns_subset
    """
    teacher_id = create_teacher_guardian()
    teacher = make_teacher_headers(teacher_id)
    trip1 = create_draft_trip(teacher_id, title="T1", grade_band="ELEMENTARY", capacity=5,
                              depart_at="2026-12-01T09:00:00Z", return_at="2026-12-01T12:00:00Z")
    trip2 = create_draft_trip(teacher_id, title="T2", grade_band="ELEMENTARY", capacity=5,
                              depart_at="2026-12-02T09:00:00Z", return_at="2026-12-02T12:00:00Z")
    g_a = create_guardian(full_name="G31a")
    g_b = create_guardian(full_name="G31b")
    st_a = create_student(teacher_id, full_name="S31a", grade_level=5)
    st_b = create_student(teacher_id, full_name="S31b", grade_level=5)
    slip1 = create_slip(teacher_id, trip1["id"], st_a["id"], g_a["id"])
    slip2 = create_slip(teacher_id, trip2["id"], st_b["id"], g_b["id"])
    res = api.list_permission_slips(teacher, params={"trip_id": trip1["id"]})
    data = get_success_data(res)
    ids = {s["id"] for s in data}
    assert slip1["id"] in ids, "trip1's slip must be in the filtered list"
    assert slip2["id"] not in ids, "trip2's slip must be excluded by the trip_id filter"
