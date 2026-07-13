"""Prescription capture, optician verification, the rejection loop, and expiry."""

from test_helpers import (
    ApiErrorId,
    assert_prescription,
    assert_same_instant,
    create_prescription_payload,
    list_lab_orders_for,
    make_customer_headers,
    new_customer,
    new_prescription,
    read_order,
    read_prescription,
    reject_prescription,
    resubmit_prescription_payload,
    set_clock,
    setup_order_scenario,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ADMIN, LOW_POWER_RX, OPTICIAN


# ═════════════════════════════════════════════════════════════════════════════
# The Order↔Prescription cross-entity state dependency
# ═════════════════════════════════════════════════════════════════════════════

def test_confirming_against_an_unverified_prescription_is_refused(api):
    """PRD §3.6: "The referenced prescription's `status` must be `VERIFIED`, or the
    confirm is refused with `ERR_PRESCRIPTION_NOT_VERIFIED`."

    Design: Difficulty/cross_entity_state_dependency/order_confirm_depends_on_prescription_verified_state
    """
    scenario = setup_order_scenario(
        frame={"price_cents": 9500, "min_pd_mm": 54.0, "max_pd_mm": 70.0},
        material={"code": "M150", "base_price_cents": 0, "material_index": 1.50},
        prescription=dict(LOW_POWER_RX),
        verify_rx=False,  # the prescription stays SUBMITTED
    )
    order = scenario["order"]

    resp = api.confirm_order(order["id"], {}, scenario["headers"])
    validate_error(resp, ApiErrorId.ERR_PRESCRIPTION_NOT_VERIFIED.value)

    after = read_order(order["id"])
    assert after["fulfillment_status"] == "DRAFT", "the refused confirm left the order in DRAFT"
    assert after["payment_status"] == "UNPAID"
    assert list_lab_orders_for(order["id"]) == [], "no lab order is minted by a refused confirm"


def test_confirm_succeeds_once_the_optician_verifies_the_prescription(api):
    """PRD §3.6: "Confirmation advances the order's two parallel dimensions together
    on this one trigger: `fulfillment_status` moves `DRAFT → CONFIRMED` and
    `payment_status` moves `UNPAID → AUTHORIZED`."
    PRD §3.6: "That produces a lab order for this order in `QUEUED`, with
    `remake_count` zero and `is_remake` false."

    The identical confirm call flips from refused to accepted purely because a third
    party — the OpticianVerifier — moved the *prescription's* state.

    Design: Difficulty/cross_entity_state_dependency/order_confirm_depends_on_prescription_verified_state
    """
    scenario = setup_order_scenario(
        frame={"price_cents": 9500, "min_pd_mm": 54.0, "max_pd_mm": 70.0},
        material={"code": "M150", "base_price_cents": 0, "material_index": 1.50},
        prescription=dict(LOW_POWER_RX),
        verify_rx=False,
    )
    order = scenario["order"]

    first = api.confirm_order(order["id"], {}, scenario["headers"])
    validate_error(first, ApiErrorId.ERR_PRESCRIPTION_NOT_VERIFIED.value)

    validate_success(
        api.verify_prescription(
            scenario["prescription"]["id"], {"decision": "VERIFIED"}, OPTICIAN
        )
    )

    second = api.confirm_order(order["id"], {}, scenario["headers"])
    confirmed = validate_success(second, 200)

    assert confirmed["fulfillment_status"] == "CONFIRMED"
    assert confirmed["payment_status"] == "AUTHORIZED"

    lab_orders = list_lab_orders_for(order["id"])
    assert len(lab_orders) == 1, "confirmation produces exactly one lab order"
    assert lab_orders[0]["status"] == "QUEUED"
    assert lab_orders[0]["remake_count"] == 0
    assert lab_orders[0]["is_remake"] is False


# ═════════════════════════════════════════════════════════════════════════════
# Capture, rejection loop, expiry
# ═════════════════════════════════════════════════════════════════════════════

def test_rejected_prescription_resubmits_back_to_submitted(api):
    """PRD §3.2: "Resubmission overwrites **all** the measurement fields from the
    payload (`od_sphere`, `od_cylinder`, `os_sphere`, `os_cylinder`, `pd_mm`,
    `issued_at`, `expires_at`, and the optional `prism_diopters`), increments
    `resubmit_count` by one, clears `rejection_reason` back to null, and increments
    `version`."
    PRD §3.2: "The owning customer, and only the owning customer, may correct a
    `REJECTED` prescription and resubmit it, driving it `REJECTED → SUBMITTED`."

    Design: Corner/state_machines/rejected_prescription_resubmits_back_to_submitted
    """
    customer = new_customer(full_name="Rea Submit", email="rea@example.com")
    rx = new_prescription(customer["id"], **LOW_POWER_RX)
    reject_prescription(rx["id"], "PD looks transposed")

    resp = api.resubmit_prescription(
        rx["id"],
        resubmit_prescription_payload(
            od_sphere=-1.25,
            od_cylinder=-0.25,
            os_sphere=-1.00,
            os_cylinder=0.00,
            pd_mm=64.0,
            issued_at="2026-04-05T00:00:00Z",
            expires_at="2027-04-05T00:00:00Z",
        ),
        make_customer_headers(customer["id"]),
    )
    data = validate_success(resp, 200)

    assert_prescription(data)
    assert data["status"] == "SUBMITTED"
    assert data["resubmit_count"] == 1
    assert data["rejection_reason"] is None
    assert data["pd_mm"] == 64.0, "resubmission overwrites pd_mm from the payload"
    assert data["od_sphere"] == -1.25, "resubmission overwrites od_sphere from the payload"


def test_clock_advance_expires_a_verified_prescription_at_its_expiry_instant(api):
    """PRD §2.5: "First, every `VERIFIED` prescription whose `expires_at` is at or
    before the new clock value transitions to `EXPIRED`, incrementing that
    prescription's `version`."
    PRD §2.5: "The response reports the new `current_utc`, plus two lists that name
    every resource the move re-stated: `expired_prescription_ids` and
    `overdue_kit_ids`."

    The clock lands exactly ON `expires_at`, so the "at or before" reading — not a
    strict "before" — is what decides.

    Design: Corner/state_machines/clock_advance_expires_a_verified_prescription
    """
    scenario = setup_order_scenario(
        prescription=dict(
            LOW_POWER_RX,
            issued_at="2025-09-01T00:00:00Z",
            expires_at="2026-09-01T00:00:00Z",
        ),
        build_order=False,
    )
    rx = scenario["prescription"]
    assert rx["status"] == "VERIFIED"

    resp = api.set_clock({"to_iso8601": "2026-09-01T00:00:00Z"}, ADMIN)
    clock = validate_success(resp, 200)

    assert_same_instant(clock["current_utc"], "2026-09-01T00:00:00Z", "current_utc")
    assert rx["id"] in clock["expired_prescription_ids"]
    assert read_prescription(rx["id"])["status"] == "EXPIRED"


def test_verifying_a_lapsed_prescription_at_the_default_clock_is_refused(api):
    """PRD §3.2: "A decision of `VERIFIED` advances the prescription
    `SUBMITTED → VERIFIED`, but only if the prescription's `expires_at` is strictly
    after the logical clock at the moment of the ruling — an optician cannot bless a
    lapsed prescription, and the attempt is refused with `ERR_PRESCRIPTION_EXPIRED`."
    PRD §2.5: "The server does not read wall-clock time. It reads a **logical clock**
    whose value, before any client has touched it, is exactly `2026-05-01T00:00:00Z`."

    No clock call is made: the prescription lapsed on 2026-04-30, which is already
    behind the untouched default clock.

    Design: Corner/endpoints/verifying_an_already_expired_prescription_at_the_default_clock
    """
    customer = new_customer(full_name="Def Ault", email="defclock@example.com")
    rx = new_prescription(
        customer["id"],
        **dict(
            LOW_POWER_RX,
            issued_at="2025-04-30T00:00:00Z",
            expires_at="2026-04-30T00:00:00Z",
        ),
    )

    resp = api.verify_prescription(rx["id"], {"decision": "VERIFIED"}, OPTICIAN)
    validate_error(resp, ApiErrorId.ERR_PRESCRIPTION_EXPIRED.value)

    after = read_prescription(rx["id"])
    assert after["status"] == "SUBMITTED", "the refused ruling left the prescription SUBMITTED"
    assert after["verified_by"] is None


def test_pd_below_the_capture_range_is_refused_and_the_boundary_is_accepted(api):
    """PRD §3.2: "The `pd_mm` value must be at least 45.0 millimetres and at most 80.0
    millimetres; anything outside that closed range is refused with
    `ERR_PD_OUT_OF_RANGE`."

    Design: Corner/validations/pd_below_range_on_capture_returns_pd_out_of_range
    """
    customer = new_customer(full_name="Pip Dee", email="pip@example.com")
    headers = make_customer_headers(customer["id"])

    below = api.create_prescription(
        create_prescription_payload(customer["id"], **dict(LOW_POWER_RX, pd_mm=44.9)),
        headers,
    )
    validate_error(below, ApiErrorId.ERR_PD_OUT_OF_RANGE.value)

    at_boundary = api.create_prescription(
        create_prescription_payload(customer["id"], **dict(LOW_POWER_RX, pd_mm=45.0)),
        headers,
    )
    data = validate_success(at_boundary, 201)
    assert data["pd_mm"] == 45.0, "45.0 is inside the closed range"
    assert data["status"] == "SUBMITTED"
