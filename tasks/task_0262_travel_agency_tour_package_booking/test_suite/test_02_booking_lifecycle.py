"""Booking and package lifecycle: parallel status dimensions, cross-entity confirm gating,
component confirm/reject branching, and invalid/terminal transitions.

Covers difficulty rules: non_linear_state_machine (component branch, booking parallel
status), cross_entity_state_dependency (confirm requires components, payment requires
reserved), boundary_precision_check (reserve zero travelers); plus corner state_machine
claims.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_payment_payload, reserve_payload, confirm_payload, cancel_payload,
    add_traveler_payload,
)
from test_helpers.fixtures import (
    create_agency, create_customer, create_supplier, create_published_package,
    open_draft_booking, add_travelers, request_component,
    setup_draft_booking_with_travelers, setup_reserved_booking,
    setup_reserved_deposit_settled, setup_reserved_manual_component,
    get_milestone_id, get_booking, _booking_version, pay_milestone,
    supplier_confirm_component, supplier_reject_component,
    AGENT, ADMIN,
)
from test_helpers.test_users import make_supplier_headers
from test_helpers import api_client


# ─── non_linear_state_machine: component confirm vs reject branch ────────
def test_component_confirm_and_optional_reject_branches(api):
    """PRD §3.6: "Confirming a component it owns advances that component
    `REQUESTED → CONFIRMED`; rejecting one advances it `REQUESTED → REJECTED`."
    PRD §3.6: "Rejecting a non-mandatory component, or rejecting any component while
    the booking is merely `DRAFT`, simply marks the component `REJECTED` without touching
    the booking's lifecycle."

    A DRAFT booking with a manual supplier: confirm c1 -> CONFIRMED; reject optional
    c2 -> REJECTED; booking stays DRAFT (was already DRAFT, optional reject no cascade).

    Design: Difficulty/non_linear_state_machine/nlsm_component_branch_confirm_vs_reject
    """
    agency = create_agency(clock=None)
    customer = create_customer(agency["id"])
    supplier = create_supplier(agency["id"], kind="FLIGHT", name="ManualAir", auto_confirm=False)
    package = create_published_package(agency["id"], base_price_per_person_cents=100000)
    booking = open_draft_booking(agency["id"], customer["id"], package["id"])
    add_travelers(booking["id"], 1, booking["version"])
    c1 = request_component(booking["id"], supplier["id"], kind="FLIGHT",
                           starts_at="2026-06-01T08:00:00.000Z", ends_at="2026-06-01T10:00:00.000Z",
                           is_mandatory=True)
    c2 = request_component(booking["id"], supplier["id"], kind="FLIGHT",
                           starts_at="2026-06-01T20:00:00.000Z", ends_at="2026-06-01T22:00:00.000Z",
                           is_mandatory=False)

    confirmed = validate_success(api.confirm_component(c1["id"], make_supplier_headers(supplier["id"])), 200)
    assert confirmed["status"] == "CONFIRMED"
    rejected = validate_success(api.reject_component(c2["id"], make_supplier_headers(supplier["id"])), 200)
    assert rejected["status"] == "REJECTED"

    booking_after = get_booking(booking["id"])
    assert booking_after["status"] == "DRAFT"


def test_component_reject_leaves_other_components_untouched(api):
    """PRD §3.6: "Confirming a component it owns advances that component
    `REQUESTED → CONFIRMED`; rejecting one advances it `REQUESTED → REJECTED`."
    PRD §3.6: "(Rejecting a non-mandatory component, or rejecting any component while
    the booking is merely `DRAFT`, simply marks the component `REJECTED` without touching
    the booking's lifecycle.)"

    Design: Difficulty/non_linear_state_machine/nlsm_component_branch_confirm_vs_reject
    """
    agency = create_agency(clock=None)
    customer = create_customer(agency["id"])
    supplier = create_supplier(agency["id"], kind="FLIGHT", name="ManualAir", auto_confirm=False)
    package = create_published_package(agency["id"], base_price_per_person_cents=100000)
    booking = open_draft_booking(agency["id"], customer["id"], package["id"])
    add_travelers(booking["id"], 1, booking["version"])
    c1 = request_component(booking["id"], supplier["id"], kind="FLIGHT",
                           starts_at="2026-06-01T08:00:00.000Z", ends_at="2026-06-01T10:00:00.000Z",
                           is_mandatory=True)
    c2 = request_component(booking["id"], supplier["id"], kind="FLIGHT",
                           starts_at="2026-06-01T20:00:00.000Z", ends_at="2026-06-01T22:00:00.000Z",
                           is_mandatory=False)
    validate_success(api.reject_component(c2["id"], make_supplier_headers(supplier["id"])), 200)
    c1_after = validate_success(api.get_component(c1["id"], AGENT), 200)
    assert c1_after["status"] == "REQUESTED"


# ─── non_linear_state_machine: parallel status / payment_status ──────────
def test_booking_status_and_payment_status_evolve_independently(api):
    """PRD §3.8: "The booking's `payment_status` is a parallel dimension derived purely
    from milestone settlement and evolving independently of the booking's lifecycle
    `status`."
    PRD §3.8: "otherwise, if the `DEPOSIT` milestone is `SETTLED`, it is `DEPOSIT_PAID`".

    A RESERVED booking: paying the deposit flips payment_status to DEPOSIT_PAID while
    status remains RESERVED.

    Design: Difficulty/non_linear_state_machine/nlsm_booking_parallel_status_and_payment_status
    """
    ctx = setup_reserved_booking(
        num_travelers=1, clock="2026-01-01T00:00:00.000Z",
        pkg_overrides={"base_price_per_person_cents": 100000, "deposit_pct": 20})
    validate_success(api.create_payment(
        create_payment_payload(ctx["booking_id"], ctx["deposit_ms_id"], 20000), AGENT), 201)
    booking = get_booking(ctx["booking_id"])
    assert booking["status"] == "RESERVED"
    assert booking["payment_status"] == "DEPOSIT_PAID"


def test_reserve_sets_status_reserved_payment_status_unpaid(api):
    """PRD §3.6: "Reserving a booking is the hinge of the whole workflow, and only a
    `TravelAgent` performs it, advancing the booking `DRAFT → RESERVED`."
    PRD §3.6: "Reserve also generates the two payment milestones (§3.8), recomputes
    `payment_status` to `UNPAID`, and increments the booking's `version`."

    Design: Difficulty/non_linear_state_machine/nlsm_booking_parallel_status_and_payment_status
    """
    ctx = setup_reserved_booking(
        num_travelers=1, clock="2026-01-01T00:00:00.000Z",
        pkg_overrides={"base_price_per_person_cents": 100000, "deposit_pct": 20})
    booking = get_booking(ctx["booking_id"])
    assert booking["status"] == "RESERVED"
    assert booking["payment_status"] == "UNPAID"


# ─── cross_entity_state_dependency: confirm requires components confirmed ─
def test_confirm_succeeds_after_mandatory_component_confirmed(api):
    """PRD §3.7: "every `is_mandatory` component on the booking must be `CONFIRMED`
    (else `ERR_COMPONENTS_NOT_CONFIRMED`), and the deposit milestone must be `SETTLED`
    (else `ERR_DEPOSIT_NOT_SETTLED`)."

    RESERVED booking, deposit settled, manual mandatory component: after the supplier
    confirms the component, booking confirm advances to CONFIRMED.

    Design: Difficulty/cross_entity_state_dependency/cesd_booking_confirm_requires_components_confirmed
    """
    ctx = setup_reserved_manual_component(
        num_travelers=1, clock="2026-01-01T00:00:00.000Z",
        pkg_overrides={"base_price_per_person_cents": 100000, "deposit_pct": 20})
    pay_milestone(ctx["booking_id"], ctx["deposit_ms_id"], 20000)
    supplier_confirm_component(ctx["supplier"]["id"], ctx["component_id"])
    version = _booking_version(ctx["booking_id"])
    confirmed = validate_success(api.confirm_booking(ctx["booking_id"], confirm_payload(version), AGENT), 200)
    assert confirmed["status"] == "CONFIRMED"


def test_confirm_blocked_while_mandatory_component_requested(api):
    """PRD §3.7: "every `is_mandatory` component on the booking must be `CONFIRMED`
    (else `ERR_COMPONENTS_NOT_CONFIRMED`)".

    RESERVED booking, deposit settled, but mandatory component still REQUESTED on a
    manual supplier => confirm rejected with ERR_COMPONENTS_NOT_CONFIRMED.

    Design: Difficulty/cross_entity_state_dependency/cesd_booking_confirm_requires_components_confirmed
    """
    ctx = setup_reserved_manual_component(
        num_travelers=1, clock="2026-01-01T00:00:00.000Z",
        pkg_overrides={"base_price_per_person_cents": 100000, "deposit_pct": 20})
    pay_milestone(ctx["booking_id"], ctx["deposit_ms_id"], 20000)
    version = _booking_version(ctx["booking_id"])
    res = api.confirm_booking(ctx["booking_id"], confirm_payload(version), AGENT)
    validate_error(res, "ERR_COMPONENTS_NOT_CONFIRMED")


# ─── cross_entity_state_dependency: payment requires reserved/confirmed ──
# NOTE: test_payment_against_draft_booking_rejected deleted — STEP 1b unique-derivability
# collapse (ERROR PRECEDENCE SILENCE). A DRAFT booking structurally has no milestone of its
# own (milestones generate only at reserve, §3.8), so the test had to reference another
# booking's milestone in the same agency. The PRD never states whether a payment's
# `milestone_id` must belong to its named `booking_id`; §2.4 scopes FK resolution to the
# *agency*, under which that milestone resolves and the state gate fires (ERR_INVALID_STATE),
# while an equally faithful reader that scopes the milestone FK to the named booking returns
# ERR_INVALID_REFERENCE first. The asserted error is not uniquely derivable. The §3.8 state
# gate remains positively covered by test_payment_allowed_against_reserved_booking below.


def test_payment_allowed_against_reserved_booking(api):
    """PRD §3.8: "The booking must be `RESERVED` or `CONFIRMED`, else `ERR_INVALID_STATE`."
    PRD §3.8: "A payment is born `APPLIED`".

    Design: Difficulty/cross_entity_state_dependency/cesd_payment_requires_booking_reserved_or_confirmed
    """
    ctx = setup_reserved_booking(
        num_travelers=1, clock="2026-01-01T00:00:00.000Z",
        pkg_overrides={"base_price_per_person_cents": 100000, "deposit_pct": 20})
    pay = validate_success(api.create_payment(
        create_payment_payload(ctx["booking_id"], ctx["deposit_ms_id"], 20000), AGENT), 201)
    assert pay["status"] == "APPLIED"


# ─── boundary_precision_check: reserve zero travelers ────────────────────
def test_reserve_zero_travelers_rejected(api):
    """PRD §3.6: "the booking must have at least one traveler, i.e. `traveler_count` of
    1 or more (else `ERR_NO_TRAVELERS`)".

    A DRAFT booking with a mandatory component but zero travelers => reserve rejected
    with ERR_NO_TRAVELERS.

    Design: Difficulty/boundary_precision_check/bpc_reserve_zero_travelers_empty_set
    """
    agency = create_agency(clock=None)
    customer = create_customer(agency["id"])
    supplier = create_supplier(agency["id"], kind="FLIGHT", auto_confirm=True)
    package = create_published_package(agency["id"], base_price_per_person_cents=100000)
    booking = open_draft_booking(agency["id"], customer["id"], package["id"])
    request_component(booking["id"], supplier["id"], kind="FLIGHT",
                      starts_at="2026-06-01T08:00:00.000Z", ends_at="2026-06-01T12:00:00.000Z")
    version = _booking_version(booking["id"])
    res = api.reserve_booking(booking["id"], reserve_payload(version), AGENT)
    validate_error(res, "ERR_NO_TRAVELERS")


def test_reserve_one_traveler_succeeds(api):
    """PRD §3.6: "the booking must have at least one traveler, i.e. `traveler_count` of
    1 or more (else `ERR_NO_TRAVELERS`)".

    With exactly one traveler (and a mandatory component), reserve advances to RESERVED.

    Design: Difficulty/boundary_precision_check/bpc_reserve_zero_travelers_empty_set
    """
    ctx = setup_reserved_booking(num_travelers=1, clock="2026-01-01T00:00:00.000Z")
    booking = get_booking(ctx["booking_id"])
    assert booking["status"] == "RESERVED"


# ─── Corner state_machine claims ─────────────────────────────────────────
def test_new_booking_starts_in_draft_unpaid(api):
    """PRD §3.3: "A new booking starts in `DRAFT` with `traveler_count` 0, `subtotal_cents`
    0, `insurance_premium_cents` 0, `grand_total_cents` 0, `paid_cents` 0, and a
    `payment_status` of `UNPAID`."

    Design: Corner/state_machines/new_booking_starts_in_draft
    """
    agency = create_agency(clock=None)
    customer = create_customer(agency["id"])
    package = create_published_package(agency["id"], base_price_per_person_cents=100000)
    booking = validate_success(api.create_booking(
        {"agency_id": agency["id"], "customer_id": customer["id"],
         "tour_package_id": package["id"], "departure_date": "2026-06-01T00:00:00.000Z"}, AGENT), 201)
    assert booking["status"] == "DRAFT"
    assert booking["payment_status"] == "UNPAID"


def test_retire_package_with_open_booking_rejected(api):
    """PRD §3.2: "Retiring a package advances it `PUBLISHED → RETIRED`, but only when no
    booking in `DRAFT` or `RESERVED` status still references it; a retire attempted while
    such open bookings exist is rejected with `ERR_PACKAGE_HAS_OPEN_BOOKINGS`."

    Design: Corner/state_machines/retire_package_with_open_booking_rejected
    """
    agency = create_agency(clock=None)
    customer = create_customer(agency["id"])
    package = create_published_package(agency["id"], base_price_per_person_cents=100000)
    open_draft_booking(agency["id"], customer["id"], package["id"])
    res = api.retire_tour_package(package["id"], AGENT)
    validate_error(res, "ERR_PACKAGE_HAS_OPEN_BOOKINGS")


def test_confirm_component_on_cancelled_booking_invalid_state(api):
    """PRD §3.7: "and every component not already `RELEASED` is moved to `RELEASED` (a
    confirmed, requested, or rejected component all land at `RELEASED`)."
    PRD §3.6: "Both actions require the acting supplier to own the component — its
    `supplier_id` must equal `X-User-ID`, else `ERR_FORBIDDEN_FOR_ROLE` — and require the
    parent booking to be in `DRAFT` or `RESERVED`, else `ERR_INVALID_STATE`."

    Cancelling a DRAFT booking RELEASES its REQUESTED component; a supplier confirm on
    that RELEASED component is rejected with ERR_INVALID_STATE.

    Design: Corner/state_machines/confirm_component_when_booking_cancelled_returns_invalid_state
    """
    agency = create_agency(clock=None)
    customer = create_customer(agency["id"])
    supplier = create_supplier(agency["id"], kind="FLIGHT", name="ManualAir", auto_confirm=False)
    package = create_published_package(agency["id"], base_price_per_person_cents=100000)
    booking = open_draft_booking(agency["id"], customer["id"], package["id"])
    component = request_component(booking["id"], supplier["id"], kind="FLIGHT",
                                  starts_at="2026-06-01T08:00:00.000Z",
                                  ends_at="2026-06-01T12:00:00.000Z")
    version = _booking_version(booking["id"])
    validate_success(api.cancel_booking(booking["id"], cancel_payload(version), AGENT), 200)
    res = api.confirm_component(component["id"], make_supplier_headers(supplier["id"]))
    validate_error(res, "ERR_INVALID_STATE")


def test_cancel_already_cancelled_booking_invalid_state(api):
    """PRD §3.7: "Cancellation is available to a `Customer` (only for their own booking —
    the booking's `customer_id` must equal `X-User-ID`, else `ERR_FORBIDDEN_FOR_ROLE`) or
    to a `TravelAgent`, from any of `DRAFT`, `RESERVED`, or `CONFIRMED`, driving the
    booking to the terminal `CANCELLED` state."

    CANCELLED is terminal and is not among the valid source states, so a second cancel is
    rejected with ERR_INVALID_STATE.

    Design: Corner/state_machines/cancel_already_cancelled_booking_returns_invalid_state
    """
    agency = create_agency(clock=None)
    customer = create_customer(agency["id"])
    package = create_published_package(agency["id"], base_price_per_person_cents=100000)
    booking = open_draft_booking(agency["id"], customer["id"], package["id"])
    v0 = booking["version"]
    cancelled = validate_success(api.cancel_booking(booking["id"], cancel_payload(v0), AGENT), 200)
    res = api.cancel_booking(booking["id"], cancel_payload(cancelled["version"]), AGENT)
    validate_error(res, "ERR_INVALID_STATE")


def test_reserve_zero_components_rejected(api):
    """PRD §3.6: "at least one mandatory component must exist on the booking in
    `REQUESTED` or `CONFIRMED` status (else `ERR_NO_COMPONENTS`)."

    A booking with travelers but no components => reserve rejected with ERR_NO_COMPONENTS.

    Design: Corner/state_machines/error_reserve_zero_components_returns_no_components
    """
    ctx = setup_draft_booking_with_travelers(num_travelers=1, clock=None)
    version = _booking_version(ctx["booking_id"])
    res = api.reserve_booking(ctx["booking_id"], reserve_payload(version), AGENT)
    validate_error(res, "ERR_NO_COMPONENTS")


def test_balance_payment_before_deposit_settled_rejected(api):
    """PRD §3.8: "a payment against the `BALANCE` milestone is rejected with
    `ERR_DEPOSIT_NOT_SETTLED` until the `DEPOSIT` milestone is `SETTLED`."

    Design: Corner/state_machines/balance_payment_before_deposit_settled_rejected
    """
    ctx = setup_reserved_booking(
        num_travelers=1, clock="2026-01-01T00:00:00.000Z",
        pkg_overrides={"base_price_per_person_cents": 100000, "deposit_pct": 20})
    res = api.create_payment(
        create_payment_payload(ctx["booking_id"], ctx["balance_ms_id"], 1000), AGENT)
    validate_error(res, "ERR_DEPOSIT_NOT_SETTLED")
    balance = validate_success(api.get_milestone(ctx["balance_ms_id"], AGENT), 200)
    assert balance["settled_amount_cents"] == 0


def test_reserve_response_reflects_frozen_grand_total(api):
    """PRD §3.6: "On reserve, the price is frozen — this is the **finalized quote**:
    `subtotal_cents`, `insurance_premium_cents`, and `grand_total_cents` are computed one
    final time from the current travelers and active policies and then fixed".

    Reserve response immediately shows status RESERVED and grand_total 100000.

    Design: Corner/consistency_model/immediate_consistency_reserve_reflects_in_same_response
    """
    ctx = setup_draft_booking_with_travelers(
        num_travelers=1, clock="2026-01-01T00:00:00.000Z",
        pkg_overrides={"base_price_per_person_cents": 100000, "deposit_pct": 20})
    supplier = create_supplier(ctx["agency"]["id"], kind="FLIGHT", auto_confirm=True)
    request_component(ctx["booking_id"], supplier["id"], kind="FLIGHT",
                      starts_at="2026-06-01T08:00:00.000Z", ends_at="2026-06-01T12:00:00.000Z")
    version = _booking_version(ctx["booking_id"])
    reserved = validate_success(api.reserve_booking(ctx["booking_id"], reserve_payload(version), AGENT), 200)
    assert reserved["status"] == "RESERVED"
    assert reserved["grand_total_cents"] == 100000
