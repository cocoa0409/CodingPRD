"""Resource creation defaults, computed/system fields, and body-validation
rejections (entities-section breadth from queue B).
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, NON_EXISTENT_UUID,
    create_practice, create_consultant, create_client,
    create_practice_payload, create_consult_payload, create_service_package_payload,
    TEST_USERS,
)

ADMIN = TEST_USERS["practice_admin_headers"]
FRONT_DESK = TEST_USERS["front_desk_headers"]


# ─── entities / create_practice_returns_defaults_and_system_fields ──────────

def test_create_practice_defaults_and_system_fields(api):
    """PRD §3.1: "A practice also carries `aca_preventive_enabled`, which defaults to
    true".
    PRD §2.4: "A freshly created practice begins with `now_utc` fixed at
    `2026-01-01T00:00:00Z`".
    PRD §2.5: "`version` — a system-managed integer that starts at the resource's
    creation and increments by one on every mutation."

    POST /practices with only name returns 201, aca_preventive_enabled true,
    now_utc 2026-01-01T00:00:00Z, version 1.

    Design: Corner/entities/create_practice_returns_defaults_and_system_fields
    """
    resp = api.create_practice(create_practice_payload(name="Solo Practice"), ADMIN)
    practice = validate_success(resp, 201)
    assert practice["aca_preventive_enabled"] is True
    assert practice["now_utc"][:19] == "2026-01-01T00:00:00", (
        f"expected default clock, got {practice['now_utc']}")
    assert practice["version"] == 1, f"expected version 1, got {practice['version']}"


# ─── entities / get_consult_not_found_returns_404 ───────────────────────────

def test_get_nonexistent_consult_returns_404(api):
    """PRD §2.6: "Where a path does carry a resource identifier, the system resolves
    it before doing any work; if that identifier does not name an existing resource
    the request is rejected with `ERR_RESOURCE_NOT_FOUND`."

    Design: Corner/entities/get_consult_not_found_returns_404
    """
    create_practice(name="Solo Practice")
    resp = api.get_consult(NON_EXISTENT_UUID, FRONT_DESK)
    validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value)


# ─── entities / create_consult_missing_required_field_returns_400 ───────────

def test_create_consult_missing_pay_method_returns_400(api):
    """PRD §2.7: "5. Request well-formedness — required fields present, enum values
    valid, `scheduled_end_utc` strictly after `scheduled_start_utc`, and
    `post_feed_weight_grams` not below `pre_feed_weight_grams`, else
    `ERR_INVALID_REQUEST`."

    POST /consults omitting the required pay_method is rejected ERR_INVALID_REQUEST.

    Design: Corner/entities/create_consult_missing_required_field_returns_400
    """
    prac = create_practice(name="Solo Practice")
    cons = create_consultant(prac["id"])
    client = create_client(prac["id"])
    payload = {
        "practice_id": prac["id"], "client_id": client["id"], "consultant_id": cons["id"],
        "consult_type": "TELEHEALTH",
        "scheduled_start_utc": "2026-06-10T15:00:00Z",
        "scheduled_end_utc": "2026-06-10T16:00:00Z",
    }
    resp = api.create_consult(payload, FRONT_DESK)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ─── entities / create_consult_end_before_start_returns_400 ─────────────────

def test_create_consult_end_not_after_start_returns_400(api):
    """PRD §2.7: "5. Request well-formedness — required fields present, enum values
    valid, `scheduled_end_utc` strictly after `scheduled_start_utc`, ... else
    `ERR_INVALID_REQUEST`."

    A consult whose end is before its start is rejected ERR_INVALID_REQUEST.

    Design: Corner/entities/create_consult_end_before_start_returns_400
    """
    prac = create_practice(name="Solo Practice")
    cons = create_consultant(prac["id"])
    client = create_client(prac["id"])
    resp = api.create_consult(create_consult_payload(
        prac["id"], client["id"], cons["id"],
        "2026-06-10T16:00:00Z", "2026-06-10T15:00:00Z"), FRONT_DESK)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ─── entities / service_package_per_visit_value_computed_floor ──────────────

def test_service_package_per_visit_value_is_floored(api):
    """PRD §3.1: "On creation the system computes `per_visit_value_cents` as the
    package price divided by the number of included visits, with any fractional cent
    discarded toward zero (floor); this is the credit value redeemed per consult."

    price 10000 / 3 visits = floor(3333.33) = 3333.

    Design: Corner/entities/service_package_per_visit_value_computed_floor
    """
    prac = create_practice(name="Solo Practice")
    resp = api.create_service_package(create_service_package_payload(
        prac["id"], "THREE_VISIT", included_visits=3, price_cents=10000), ADMIN)
    pkg = validate_success(resp, 201)
    assert pkg["per_visit_value_cents"] == 3333, (
        f"expected 3333, got {pkg['per_visit_value_cents']}")


# ─── entities / client_system_fields_ignored_on_create ──────────────────────

def test_client_system_fields_stamped_on_create(api):
    """PRD §3.2: "Every newly registered client starts with `status` equal to
    `ACTIVE`."
    PRD §3.2: "`no_show_strikes`, the count of this client's consults that have
    reached a no-show. Both begin at 0."
    PRD §2.5: "`version` — a system-managed integer that starts at the resource's
    creation".

    POST /clients stamps status ACTIVE, no_show_strikes 0,
    reimbursement_ledger_cents 0, version 1.

    Design: Corner/entities/client_system_fields_ignored_on_create
    """
    prac = create_practice(name="Solo Practice")
    resp = api.create_client({
        "practice_id": prac["id"], "full_name": "Parent A",
        "infant_dob": "2026-05-01T00:00:00Z", "household_income_cents": 9900000,
    }, FRONT_DESK)
    client = validate_success(resp, 201)
    assert client["status"] == "ACTIVE"
    assert client["no_show_strikes"] == 0
    assert client["reimbursement_ledger_cents"] == 0
    assert client["version"] == 1


# ─── entities / create_consult_referenced_client_not_found_returns_404 ──────

def test_create_consult_referenced_client_not_found_returns_404(api):
    """PRD §2.6: "every referenced foreign-key id in the body — among them
    `client_id`, `consultant_id`, `consult_id`, `package_id`, and
    `follow_up_plan_id` — must name an existing resource, or the request is rejected
    with `ERR_REFERENCED_RESOURCE_NOT_FOUND`."

    POST /consults with a body client_id that does not exist returns
    ERR_REFERENCED_RESOURCE_NOT_FOUND.

    Design: Corner/entities/create_consult_referenced_client_not_found_returns_404
    """
    prac = create_practice(name="Solo Practice")
    cons = create_consultant(prac["id"])
    resp = api.create_consult(create_consult_payload(
        prac["id"], NON_EXISTENT_UUID, cons["id"],
        "2026-06-10T15:00:00Z", "2026-06-10T16:00:00Z"), FRONT_DESK)
    validate_error(resp, ApiErrorId.ERR_REFERENCED_RESOURCE_NOT_FOUND.value)
