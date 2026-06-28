"""Validation rules, boundary precision, precedence conflicts, and temporal overlaps.

Covers the boundary, priority-pair, and resource-overlap difficulty instances plus the
validation corner instances. Each validation is exercised in isolation so exactly one
check can fire (no priority-ordering test unless PRD names the precedence explicitly).
"""
from test_helpers import (
    api_client, get_success_data, validate_success, validate_error,
    ApiErrorId,
    setup_private_case_cremated, setup_received_case_with_cooler,
    setup_communal_batch_fired,
    create_clinic, create_owner, create_retort, create_case, create_batch,
    drive_case_to_received, store_case, stage_load_fire_private,
    set_clock, get_case_version, TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
OPERATOR = TEST_USERS["operator_headers"]


def _case(case_id):
    return get_success_data(api_client.get_case(case_id, ADMIN))


# =========================================================================== #
# boundary_precision_check
# =========================================================================== #
def test_cooler_full_rejected_at_capacity_boundary(api):
    """PRD §3.4: "A store against a cooler whose occupied count has already reached its
    total capacity is rejected with `ERR_COOLER_FULL` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/boundary_cooler_capacity_at_full
    """
    set_clock("2026-03-12T00:00:00Z")
    from test_helpers import create_cooler
    cooler = create_cooler(total_capacity=1)
    owner = create_owner()

    c1 = create_case(owner["id"], service_type="PRIVATE", weight_lbs=10,
                     bill_to="OWNER", pickup_kind="CLINIC", species="CAT")
    drive_case_to_received(c1["id"], origin_kind="CLINIC", origin_label="V", driver_name="T")
    store_case(c1["id"], cooler["id"])  # occupied 0 -> 1 (FULL)

    c2 = create_case(owner["id"], service_type="PRIVATE", weight_lbs=10,
                     bill_to="OWNER", pickup_kind="CLINIC", species="CAT")
    drive_case_to_received(c2["id"], origin_kind="CLINIC", origin_label="V", driver_name="T")

    validate_error(api_client.store_case(c2["id"], cooler["id"], OPERATOR),
                   ApiErrorId.ERR_COOLER_FULL.value)
    assert get_success_data(api_client.get_cooler(cooler["id"], ADMIN))["occupied_count"] == 1
    assert _case(c2["id"])["custody_status"] == "RECEIVED"


def test_load_empty_batch_zero_members_rejected(api):
    """PRD §3.6: "A load on a batch with no members is rejected with `ERR_BATCH_EMPTY`
    (HTTP 409)"

    Design: Difficulty/boundary_precision_check/boundary_empty_batch_fire_zero_members
    """
    set_clock("2026-03-13T00:00:00Z")
    retort = create_retort(max_load_lbs=300)
    batch = create_batch(retort["id"], "COMMUNAL",
                         "2026-03-13T08:00:00Z", "2026-03-13T10:00:00Z")

    validate_error(api_client.load_batch(batch["id"], OPERATOR),
                   ApiErrorId.ERR_BATCH_EMPTY.value)
    fetched = get_success_data(api_client.get_batch(batch["id"], ADMIN))
    assert fetched["status"] == "OPEN"
    assert fetched["member_count"] == 0


# =========================================================================== #
# priority_pair_validation_conflict (precedence is explicitly named in PRD §2.10)
# =========================================================================== #
def test_cancel_cremated_case_state_check_beats_fiscal(api):
    """PRD §3.13: "An attempt to cancel a case outside these custody states is rejected
    with `ERR_INVALID_STATE`."
    PRD §2.10: "the optimistic-concurrency version check, which is checked before the
    target's state is checked for transition validity, which in turn precedes the domain
    safety, capacity, scheduling, and fiscal checks."

    Design: Difficulty/priority_pair_validation_conflict/priority_state_beats_fiscal_on_cancel_after_complete
    """
    # Clinic over credit (limit 10000, charge 18000) and case CREMATED. State check wins.
    ctx = setup_private_case_cremated(clock="2026-04-03T00:00:00Z", weight_lbs=50,
                                      bill_to="CLINIC_ACCOUNT", credit_limit_cents=10000)
    case_id = ctx["case"]["id"]
    validate_error(api_client.cancel_case(case_id, ADMIN),
                   ApiErrorId.ERR_INVALID_STATE.value)
    assert _case(case_id)["custody_status"] == "CREMATED"


def test_assign_service_type_mismatch_safety_beats_referential(api):
    """PRD §3.5: "A case whose service type differs from the batch's, or an attempt to add
    a second member to a `PRIVATE` batch that already holds one, is rejected with
    `ERR_SERVICE_TYPE_MISMATCH` (HTTP 409)."
    PRD §2.10: "Existence of every path-referenced resource and every body foreign-key
    target is checked third, failing with `ERR_NOT_FOUND`."

    Design: Difficulty/priority_pair_validation_conflict/priority_safety_beats_referential_on_assign_mismatch
    """
    # A real (existing) COMMUNAL case assigned to a PRIVATE batch: existence passes,
    # service-type safety check fires.
    set_clock("2026-03-11T00:00:00Z")
    retort = create_retort(max_load_lbs=300)
    owner = create_owner()
    case = create_case(owner["id"], service_type="COMMUNAL", weight_lbs=10,
                       bill_to="OWNER", pickup_kind="CLINIC", species="CAT")
    drive_case_to_received(case["id"], origin_kind="CLINIC", origin_label="V", driver_name="T")
    batch = create_batch(retort["id"], "PRIVATE",
                         "2026-03-11T08:00:00Z", "2026-03-11T10:00:00Z")

    validate_error(api_client.assign_case(batch["id"], case["id"], OPERATOR),
                   ApiErrorId.ERR_SERVICE_TYPE_MISMATCH.value)
    assert _case(case["id"])["custody_status"] == "RECEIVED"


# =========================================================================== #
# resource_temporal_overlap
# =========================================================================== #
def test_retort_firing_window_overlap_rejected(api):
    """PRD §3.6: "Firing also requires that no other batch on the same retort already
    occupy an overlapping firing window while in the `FIRING` status. Two windows are
    treated as half-open intervals `[scheduled_start, scheduled_end)`: they conflict when
    they overlap, but windows that merely touch at an endpoint (one ending exactly when
    another begins) do not conflict. A fire that would overlap another firing batch on the
    same retort is rejected with `ERR_RETORT_WINDOW_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/overlap_retort_firing_window_halfopen
    """
    set_clock("2026-03-16T00:00:00Z")
    retort = create_retort(max_load_lbs=400)
    owner = create_owner()

    # Batch X fired, window 08:00-10:00.
    x1 = create_case(owner["id"], service_type="PRIVATE", weight_lbs=30,
                     bill_to="OWNER", pickup_kind="HOME")
    drive_case_to_received(x1["id"])
    batchX = create_batch(retort["id"], "PRIVATE",
                          "2026-03-16T08:00:00Z", "2026-03-16T10:00:00Z")
    get_success_data(api_client.assign_case(batchX["id"], x1["id"], OPERATOR))
    get_success_data(api_client.load_batch(batchX["id"], OPERATOR))
    get_success_data(api_client.fire_batch(batchX["id"], OPERATOR))

    # Batch Y loaded, overlapping window 09:00-11:00 on same retort.
    y1 = create_case(owner["id"], service_type="PRIVATE", weight_lbs=30,
                     bill_to="OWNER", pickup_kind="HOME")
    drive_case_to_received(y1["id"])
    batchY = create_batch(retort["id"], "PRIVATE",
                          "2026-03-16T09:00:00Z", "2026-03-16T11:00:00Z")
    get_success_data(api_client.assign_case(batchY["id"], y1["id"], OPERATOR))
    get_success_data(api_client.load_batch(batchY["id"], OPERATOR))

    validate_error(api_client.fire_batch(batchY["id"], OPERATOR),
                   ApiErrorId.ERR_RETORT_WINDOW_CONFLICT.value)
    assert get_success_data(api_client.get_batch(batchY["id"], ADMIN))["status"] == "LOADED"


def test_viewing_room_buffered_window_conflict(api):
    """PRD §3.12: "Booking a viewing session also enforces room scheduling: the requested
    viewing window, extended by a viewing buffer of fifteen minutes, must not collide with
    any other non-cancelled viewing session already booked in the same `viewing_room_code`.
    A booking whose buffered window collides with another viewing in the same room is
    rejected with `ERR_VIEWING_ROOM_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/overlap_viewing_room_buffered_window
    """
    set_clock("2026-03-17T00:00:00Z")
    owner = create_owner()
    a1 = create_case(owner["id"], service_type="PRIVATE", weight_lbs=20,
                     bill_to="OWNER", pickup_kind="HOME")
    get_success_data(api_client.create_memorial_addon(a1["id"], {
        "addon_type": "VIEWING_SESSION", "viewing_room_code": "ROOM-1",
        "viewing_start": "2026-03-17T10:00:00Z", "viewing_end": "2026-03-17T11:00:00Z",
    }, OPERATOR))

    a2 = create_case(owner["id"], service_type="PRIVATE", weight_lbs=20,
                     bill_to="OWNER", pickup_kind="HOME")
    # 11:15 start is within the 15-min buffer after the prior 11:00 end.
    validate_error(api_client.create_memorial_addon(a2["id"], {
        "addon_type": "VIEWING_SESSION", "viewing_room_code": "ROOM-1",
        "viewing_start": "2026-03-17T11:05:00Z", "viewing_end": "2026-03-17T12:00:00Z",
    }, OPERATOR), ApiErrorId.ERR_VIEWING_ROOM_CONFLICT.value)


# =========================================================================== #
# Corner: validations
# =========================================================================== #
def test_retort_overloaded_on_load(api):
    """PRD §3.6: "a load whose `loaded_weight_lbs` exceeds the retort's `max_load_lbs` is
    rejected with `ERR_RETORT_OVERLOADED` (HTTP 409)."

    Design: Corner/validations/val_retort_overloaded_on_load
    """
    ctx = setup_communal_batch_overloaded()
    validate_error(api_client.load_batch(ctx["batch_id"], OPERATOR),
                   ApiErrorId.ERR_RETORT_OVERLOADED.value)
    assert get_success_data(api_client.get_batch(ctx["batch_id"], ADMIN))["status"] == "OPEN"


def setup_communal_batch_overloaded():
    """Retort max_load 150; one COMMUNAL 200-lb case received and staged (OPEN batch)."""
    set_clock("2026-05-11T00:00:00Z")
    retort = create_retort(max_load_lbs=150)
    owner = create_owner()
    case = create_case(owner["id"], service_type="COMMUNAL", weight_lbs=200,
                       bill_to="OWNER", pickup_kind="HOME", species="OTHER")
    drive_case_to_received(case["id"])
    batch = create_batch(retort["id"], "COMMUNAL",
                         "2026-05-11T08:00:00Z", "2026-05-11T10:00:00Z")
    get_success_data(api_client.assign_case(batch["id"], case["id"], OPERATOR))
    return {"batch_id": batch["id"], "case_id": case["id"]}


def test_clinic_required_for_account_billing(api):
    """PRD §3.2: "If `bill_to` is `CLINIC_ACCOUNT`, the case must carry a `clinic_id`; an
    account-billed intake without a clinic is rejected with
    `ERR_CLINIC_REQUIRED_FOR_ACCOUNT_BILLING` (HTTP 422)."

    Design: Corner/validations/val_clinic_required_for_account_billing
    """
    owner = create_owner()
    payload = {
        "owner_id": owner["id"], "pet_name": "Nr", "species": "DOG", "weight_lbs": 40,
        "service_type": "PRIVATE", "pickup_kind": "HOME", "bill_to": "CLINIC_ACCOUNT",
    }
    validate_error(api_client.create_case(payload, OPERATOR),
                   ApiErrorId.ERR_CLINIC_REQUIRED_FOR_ACCOUNT_BILLING.value)


def test_clinic_credit_exceeded_on_invoice(api):
    """PRD §3.10: "Issuing an invoice that would push a clinic-account clinic's outstanding
    balance above its credit limit is rejected with `ERR_CLINIC_CREDIT_EXCEEDED` (HTTP
    409)."

    Design: Corner/validations/val_clinic_credit_exceeded_on_invoice
    """
    ctx = setup_private_case_cremated(clock="2026-05-12T00:00:00Z", weight_lbs=50,
                                      bill_to="CLINIC_ACCOUNT", credit_limit_cents=10000)
    case_id = ctx["case"]["id"]
    clinic_id = ctx["clinic_id"]
    version = get_case_version(case_id)
    validate_error(api_client.create_invoice(case_id, version, ADMIN),
                   ApiErrorId.ERR_CLINIC_CREDIT_EXCEEDED.value)
    assert get_success_data(api_client.get_clinic(clinic_id, ADMIN))["outstanding_balance_cents"] == 0


def test_viewing_fields_required(api):
    """PRD §3.12: "a viewing session missing any of these fields, or whose viewing end is
    at or before its viewing start, is rejected with `ERR_VIEWING_FIELDS_REQUIRED` (HTTP
    422)."

    Design: Corner/validations/val_viewing_fields_required
    """
    owner = create_owner()
    case = create_case(owner["id"], service_type="PRIVATE", weight_lbs=40,
                       bill_to="OWNER", pickup_kind="HOME")
    validate_error(api_client.create_memorial_addon(case["id"],
                   {"addon_type": "VIEWING_SESSION"}, OPERATOR),
                   ApiErrorId.ERR_VIEWING_FIELDS_REQUIRED.value)


def test_schedule_window_invalid_on_batch_create(api):
    """PRD §3.5: "the end must be strictly after the start; a window whose end is at or
    before its start is rejected with `ERR_SCHEDULE_WINDOW_INVALID` (HTTP 422)."

    Design: Corner/validations/val_schedule_window_invalid_on_batch_create
    """
    retort = create_retort(max_load_lbs=300)
    payload = {
        "retort_id": retort["id"], "service_type": "COMMUNAL",
        "scheduled_start": "2026-05-13T10:00:00Z", "scheduled_end": "2026-05-13T09:00:00Z",
    }
    validate_error(api_client.create_batch(payload, OPERATOR),
                   ApiErrorId.ERR_SCHEDULE_WINDOW_INVALID.value)


def test_pagination_invalid_limit_below_min(api):
    """PRD §2.3: "A `limit` outside the range 1 through 100, or an `offset` below 0, is
    rejected with `ERR_PAGINATION_INVALID` (HTTP 422)."

    Design: Corner/validations/val_pagination_invalid_limit
    """
    validate_error(api_client.list_cases(OPERATOR, params={"limit": 0}),
                   ApiErrorId.ERR_PAGINATION_INVALID.value)
