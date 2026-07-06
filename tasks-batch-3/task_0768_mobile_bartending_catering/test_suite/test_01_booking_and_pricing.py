"""Event booking, provisional/final pricing, tiered service fee, and the
guest-overage threshold.

Design queues:
  A (Difficulty): dual_variant_calc, combinatorial_formula, boundary_precision_check
  B (Corner): entities creation / validation claims
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_client_payload, create_package_payload, create_event_payload,
    create_draft_event, TEST_USERS, make_client_headers, ApiErrorId,
    NON_EXISTENT_UUID, assert_event,
)

ADMIN = TEST_USERS["platform_admin_headers"]
COORD = TEST_USERS["coordinator_headers"]


def _catalog(api):
    client = get_success_data(api.create_client(create_client_payload(), ADMIN))
    package = get_success_data(api.create_package(create_package_payload(), ADMIN))
    return client, package


# ---------------------------------------------------------------------------
# Queue A — dual_variant_calc / event_charge_provisional_vs_final_diverge
# ---------------------------------------------------------------------------
def test_provisional_total_assumes_included_hours(api):
    """PRD §3.2: "In the provisional variant used at quote time, overage hours
    are treated as zero regardless of the actual duration — the provisional
    figure always assumes the event fits inside the included hours."

    Design: Difficulty/dual_variant_calc/event_charge_provisional_vs_final_diverge
    """
    client, package = _catalog(api)
    headers = make_client_headers(client["id"])
    resp = api.create_event(
        create_event_payload(client["id"], package["id"], guest_count=80,
                             event_start="2026-06-01T18:00:00Z",
                             event_end="2026-06-01T23:00:00Z"),
        headers,
    )
    ev = validate_success(resp, 201)
    assert ev["provisional_grand_total_cents"] == 277440
    assert ev["provisional_grand_total_cents"] != ev["final_grand_total_cents"]


def test_final_total_and_deposit_use_actual_hours(api):
    """PRD §3.2: "In the final variant, the overage hours are the amount by
    which billable_hours exceeds the package's included_hours, or zero
    otherwise."
    PRD §3.2: "The deposit due (deposit_due_cents) is the provisional grand
    total multiplied by 50 percent, rounded."

    Design: Difficulty/dual_variant_calc/event_charge_provisional_vs_final_diverge
    """
    client, package = _catalog(api)
    headers = make_client_headers(client["id"])
    resp = api.create_event(
        create_event_payload(client["id"], package["id"], guest_count=80,
                             event_start="2026-06-01T18:00:00Z",
                             event_end="2026-06-01T23:00:00Z"),
        headers,
    )
    ev = validate_success(resp, 201)
    assert ev["final_grand_total_cents"] == 311440
    assert ev["deposit_due_cents"] == 138720


# ---------------------------------------------------------------------------
# Queue A — combinatorial_formula / event_charge_tiered_service_fee_mode_a
# ---------------------------------------------------------------------------
def test_subtotal_composes_base_and_overages(api):
    """PRD §3.2: "The subtotal (subtotal_cents) is the package's
    base_price_cents, plus the overage guests multiplied by
    per_guest_overage_cents, plus the number of overage hours multiplied by
    per_hour_overage_cents."

    Design: Difficulty/combinatorial_formula/event_charge_tiered_service_fee_mode_a
    """
    client, package = _catalog(api)
    headers = make_client_headers(client["id"])
    ev = validate_success(api.create_event(
        create_event_payload(client["id"], package["id"], guest_count=80,
                             event_start="2026-06-01T18:00:00Z",
                             event_end="2026-06-01T23:00:00Z"), headers), 201)
    assert ev["subtotal_cents"] == 229000


def test_tiered_service_fee_and_gratuity_at_mid_tier(api):
    """PRD §3.2: "The service fee (service_fee_cents) starts as the subtotal
    multiplied by a tiered percentage selected by guest count: 20 percent when
    guest_count is 50 or fewer, 18 percent when it is between 51 and 150
    inclusive, and 15 percent when it is above 150."
    PRD §3.2: "The gratuity (gratuity_cents) is the subtotal multiplied by 18
    percent, rounded."

    Design: Difficulty/combinatorial_formula/event_charge_tiered_service_fee_mode_a
    """
    client, package = _catalog(api)
    headers = make_client_headers(client["id"])
    ev = validate_success(api.create_event(
        create_event_payload(client["id"], package["id"], guest_count=80,
                             event_start="2026-06-01T18:00:00Z",
                             event_end="2026-06-01T23:00:00Z"), headers), 201)
    assert ev["service_fee_cents"] == 41220
    assert ev["gratuity_cents"] == 41220


# ---------------------------------------------------------------------------
# Queue A — boundary_precision_check / guest_overage_threshold_at_included_count
# ---------------------------------------------------------------------------
def test_guest_count_at_included_has_no_overage(api):
    """PRD §3.2: "The number of overage guests is the amount by which
    guest_count exceeds the package's included_guest_count, or zero if it does
    not exceed it."

    Design: Difficulty/boundary_precision_check/guest_overage_threshold_at_included_count
    """
    client, package = _catalog(api)
    headers = make_client_headers(client["id"])
    ev = validate_success(api.create_event(
        create_event_payload(client["id"], package["id"], guest_count=50,
                             event_start="2026-06-01T18:00:00Z",
                             event_end="2026-06-01T22:00:00Z"), headers), 201)
    assert ev["subtotal_cents"] == 150000


def test_guest_count_one_above_included_crosses_boundary(api):
    """PRD §3.2: "The number of overage guests is the amount by which
    guest_count exceeds the package's included_guest_count, or zero if it does
    not exceed it."

    Design: Difficulty/boundary_precision_check/guest_overage_threshold_at_included_count
    """
    client, package = _catalog(api)
    headers = make_client_headers(client["id"])
    ev = validate_success(api.create_event(
        create_event_payload(client["id"], package["id"], guest_count=51,
                             event_start="2026-06-01T18:00:00Z",
                             event_end="2026-06-01T22:00:00Z"), headers), 201)
    assert ev["subtotal_cents"] == 151800


# ---------------------------------------------------------------------------
# Queue B — entities: creation, computed fields, not-found, validation
# ---------------------------------------------------------------------------
def test_create_event_success_with_computed_fields(api):
    """PRD §3.2: "On creation the event opens with `booking_status` of `DRAFT`,
    `payment_status` of `UNPAID`, and `compliance_posture` of `PENDING`."
    PRD §3.2: "The required bartender count (`required_bartender_count`) is the
    `guest_count` divided by the package's `guests_per_bartender`, rounded up to
    the next whole bartender."

    Design: Corner/entities/create_event_success_with_computed_fields
    """
    client, package = _catalog(api)
    headers = make_client_headers(client["id"])
    resp = api.create_event(
        create_event_payload(client["id"], package["id"], guest_count=80,
                             event_start="2026-06-01T18:00:00Z",
                             event_end="2026-06-01T23:00:00Z"), headers)
    ev = validate_success(resp, 201)
    assert_event(ev)
    assert ev["booking_status"] == "DRAFT"
    assert ev["payment_status"] == "UNPAID"
    assert ev["version"] == 1
    assert ev["billable_hours"] == 5
    assert ev["required_bartender_count"] == 2


def test_get_event_not_found_returns_404(api):
    """PRD §2.7: "A missing event yields `ERR_EVENT_NOT_FOUND`; a missing
    assignment `ERR_ASSIGNMENT_NOT_FOUND`".

    Design: Corner/entities/get_event_not_found_returns_404
    """
    resp = api.get_event(NON_EXISTENT_UUID, COORD)
    validate_error(resp, ApiErrorId.ERR_EVENT_NOT_FOUND.value)


def test_create_event_missing_guest_count_is_validation_error(api):
    """PRD §2.7: "Body well-formedness — required fields present, enum members
    valid, numeric ranges satisfied, and every time range strictly ordered,
    else ERR_VALIDATION (HTTP 400)."

    Design: Corner/entities/create_event_missing_required_field
    """
    client, package = _catalog(api)
    headers = make_client_headers(client["id"])
    payload = create_event_payload(client["id"], package["id"])
    del payload["guest_count"]
    resp = api.create_event(payload, headers)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_create_event_end_not_after_start_is_validation_error(api):
    """PRD §2.7: "Body well-formedness — required fields present, enum members
    valid, numeric ranges satisfied, and every time range strictly ordered,
    else ERR_VALIDATION (HTTP 400)."

    Design: Corner/entities/create_event_invalid_time_range
    """
    client, package = _catalog(api)
    headers = make_client_headers(client["id"])
    resp = api.create_event(
        create_event_payload(client["id"], package["id"],
                             event_start="2026-06-01T23:00:00Z",
                             event_end="2026-06-01T18:00:00Z"), headers)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_create_event_unknown_client_is_not_found(api):
    """PRD §2.7: "a missing `client_id` `ERR_CLIENT_NOT_FOUND`; a missing
    `package_id` `ERR_PACKAGE_NOT_FOUND`; a missing `bartender_id`
    `ERR_BARTENDER_NOT_FOUND`".

    Design: Corner/entities/create_event_client_not_found
    """
    package = get_success_data(api.create_package(create_package_payload(), ADMIN))
    bogus = NON_EXISTENT_UUID
    headers = make_client_headers(bogus)
    resp = api.create_event(
        create_event_payload(bogus, package["id"], guest_count=80), headers)
    validate_error(resp, ApiErrorId.ERR_CLIENT_NOT_FOUND.value)
