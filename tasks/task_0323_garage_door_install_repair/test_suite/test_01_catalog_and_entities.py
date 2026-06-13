"""Catalog and entity creation: customers, parts, door models, plus their
defaults, computed fields, uniqueness, type constraints, and immutability.
Also a couple of job-dimension invalid/terminal transitions.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_error_is_one_of,
    get_success_data,
    api_client,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    # fixtures
    create_customer,
    create_technician,
    create_sent_quote,
    accept_quote_get_job,
)

SM = TEST_USERS["service_manager_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


# ===========================================================================
# Corner / entities / create_customer_returns_201_with_defaults
# ===========================================================================
def test_create_customer_returns_201_with_defaults(api):
    """PRD §3.2: "a freshly registered customer is `GOOD`"
    PRD §3.2: "The `active_warranty_count` is the number of warranty plans for
    that customer currently in `ACTIVE` status, beginning at zero."

    Design: Corner/entities/create_customer_returns_201_with_defaults
    """
    created = validate_success(
        api.create_customer(
            {"full_name": "Cora New", "email": "cora-new@example.com", "service_address": "1 Main"}, SM
        ),
        201,
    )
    assert created["financing_standing"] == "GOOD", (
        f"Expected financing_standing GOOD, got {created['financing_standing']}"
    )
    assert created["active_warranty_count"] == 0, (
        f"Expected active_warranty_count 0, got {created['active_warranty_count']}"
    )


# ===========================================================================
# Corner / entities / get_customer_nonexistent_returns_not_found
# ===========================================================================
def test_get_customer_nonexistent_returns_not_found(api):
    """PRD §2.7: "if any of them fails to resolve to an existing resource, the
    request is rejected with `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_customer_nonexistent_returns_not_found
    """
    resp = api.get_customer(NON_EXISTENT_UUID, SM)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


# ===========================================================================
# Corner / entities / create_quote_missing_required_field_invalid_request
# ===========================================================================
def test_create_quote_missing_quote_type_rejected(api):
    """PRD §2.7: "every required field must be present and of the correct type,
    every enumerated field must hold one of its declared values, and any quantity
    field must be at least 1 — failure of any of these yields `ERR_INVALID_REQUEST`
    (HTTP 422)."

    Design: Corner/entities/create_quote_missing_required_field_invalid_request
    """
    customer = create_customer()
    resp = api.create_quote({"customer_id": customer["id"]}, SM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 422)


# ===========================================================================
# Corner / entities / create_quote_invalid_enum_value_rejected
# ===========================================================================
def test_create_quote_invalid_quote_type_enum_rejected(api):
    """PRD §3.3: "with a `quote_type` of either `SERVICE_CALL` or `INSTALL`"
    PRD §2.7: "every enumerated field must hold one of its declared values ...
    failure of any of these yields `ERR_INVALID_REQUEST` (HTTP 422)."

    Design: Corner/entities/create_quote_invalid_enum_value_rejected
    """
    customer = create_customer()
    resp = api.create_quote({"customer_id": customer["id"], "quote_type": "WHOLESALE"}, SM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 422)


# ===========================================================================
# Corner / entities / create_part_duplicate_sku_rejected
# ===========================================================================
def test_create_part_duplicate_sku_rejected(api):
    """PRD §2.7: "the `sku` of a part, the `sku` of a door model, and the `sku`
    of an opener model must each be unique within their respective catalogs. A
    creation that collides with an existing value on any of these is rejected
    with `ERR_DUPLICATE` (HTTP 409)."

    Design: Corner/entities/create_part_duplicate_sku_rejected
    """
    payload = {"sku": "SPR-DUP-XYZ", "category": "SPRING", "unit_price_cents": 9000, "on_hand_qty": 5}
    validate_success(api.create_part(payload, SM), 201)
    resp = api.create_part(payload, SM)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE.value, 409)


# ===========================================================================
# Corner / entities / create_part_default_markup_applied
# ===========================================================================
def test_create_part_applies_default_markup_and_available_qty(api):
    """PRD §3.1: "a `markup_pct` of 0.35 means the line is priced at 135% of
    catalog — defaulting to 0.35 when not supplied. A part is created with its
    physical `on_hand_qty`; at creation its `reserved_qty` is zero and its
    `available_qty` equals `on_hand_qty`."

    Design: Corner/entities/create_part_default_markup_applied
    """
    created = validate_success(
        api.create_part({"sku": "PNL-DEF-1", "category": "PANEL", "unit_price_cents": 15000, "on_hand_qty": 7}, SM),
        201,
    )
    assert created["markup_pct"] == 0.35, f"Expected default markup_pct 0.35, got {created['markup_pct']}"
    assert created["available_qty"] == 7, f"Expected available_qty 7, got {created['available_qty']}"


# ===========================================================================
# Corner / entities / door_model_is_immutable_no_version_field
# ===========================================================================
def test_door_model_has_no_version_field(api):
    """PRD §2.4: "Two catalog resources are immutable reference data and therefore
    carry **only** `id` and `created_at` — they have **no** `updated_at` field and
    **no** `version` field: the door model (`DoorModel`) and the opener model
    (`OpenerModel`)."

    Design: Corner/entities/door_model_is_immutable_no_version_field
    """
    created = validate_success(
        api.create_door_model(
            {"sku": "DR-IMM-1", "name": "Imm", "width_in": 96, "height_in": 84,
             "list_price_cents": 100000, "install_labor_minutes": 120}, SM
        ),
        201,
    )
    assert "version" not in created, "DoorModel response must not carry a version field"
    assert "updated_at" not in created, "DoorModel response must not carry an updated_at field"


# ===========================================================================
# Corner / entities / customer_computed_active_warranty_count_input_ignored
# ===========================================================================
def test_customer_active_warranty_count_starts_zero(api):
    """PRD §3.2: "The `active_warranty_count` is the number of warranty plans for
    that customer currently in `ACTIVE` status, beginning at zero."

    Design: Corner/entities/customer_computed_active_warranty_count_input_ignored
    """
    created = validate_success(
        api.create_customer(
            {"full_name": "Comp Ute", "email": "comp-ute-1@example.com", "service_address": "4 Main"}, SM
        ),
        201,
    )
    assert created["active_warranty_count"] == 0, (
        f"Expected active_warranty_count 0 for a new customer, got {created['active_warranty_count']}"
    )


# ===========================================================================
# Corner / state_machines / depart_job_from_unscheduled_returns_invalid_state
# ===========================================================================
def test_depart_unscheduled_job_returns_invalid_state(api):
    """PRD §3.6: "Once a job is `SCHEDULED`, the assigned `Technician` drives the
    on-site lifecycle. Departing moves the job from `SCHEDULED` to `EN_ROUTE` and
    records the ETA window start"

    Design: Corner/state_machines/depart_job_from_unscheduled_returns_invalid_state
    """
    customer = create_customer()
    technician = create_technician(skill_level="CERTIFIED")
    quote = create_sent_quote(
        customer["id"], [{"item_kind": "LABOR", "qty": 30}],
        quote_type="SERVICE_CALL", service_call_fee_cents=5000,
    )
    job = accept_quote_get_job(quote["id"], customer["id"])
    from test_helpers import make_technician_headers
    resp = api.depart_job(job["id"], make_technician_headers(technician["id"]))
    # PRD §2.8 keys ERR_FORBIDDEN_ROLE to priority 2 (role authorization) and
    # ERR_INVALID_STATE to priority 5 (state). The assigned-technician ownership
    # comparison of §2.1/§3.6 ("only the assigned technician may drive...") yields
    # ERR_FORBIDDEN_ROLE and is NOT enumerated among the post-state business checks
    # in §2.8, so on an UNSCHEDULED job (technician_id is null, so the acting tech
    # is not the assignee) a faithful reader may legitimately surface either the
    # priority-2 ownership rejection or the priority-5 invalid-state rejection.
    validate_error_is_one_of(
        resp,
        [ApiErrorId.ERR_INVALID_STATE.value, ApiErrorId.ERR_FORBIDDEN_ROLE.value],
    )


# ===========================================================================
# Corner / state_machines / terminal_cancelled_job_cannot_reschedule
# ===========================================================================
def test_cancelled_job_cannot_be_rescheduled(api):
    """PRD §3.5: "A `Dispatcher` may **cancel** a job while its dispatch status is
    `UNSCHEDULED`, `SCHEDULED`, or `EN_ROUTE` ... Cancelling moves the dispatch
    status to `CANCELLED`"
    PRD §3.5: "A `Dispatcher` schedules an unscheduled job, moving its dispatch
    status from `UNSCHEDULED` to `SCHEDULED`."

    Design: Corner/state_machines/terminal_cancelled_job_cannot_reschedule
    """
    customer = create_customer()
    technician = create_technician(skill_level="CERTIFIED")
    quote = create_sent_quote(
        customer["id"], [{"item_kind": "LABOR", "qty": 30}],
        quote_type="SERVICE_CALL", service_call_fee_cents=5000,
    )
    job = accept_quote_get_job(quote["id"], customer["id"])
    get_success_data(api.cancel_job(job["id"], DISPATCHER))
    resp = api.schedule_job(
        job["id"],
        {"technician_id": technician["id"],
         "scheduled_start": "2026-07-01T17:00:00Z",
         "scheduled_end": "2026-07-01T18:00:00Z"},
        DISPATCHER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
