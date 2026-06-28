"""Corner-coverage tests for calculations (peak surcharge, loyalty, fill window, tech
selector) and business validations (skill floor, retired service, order mismatch, empty
lines, consent).

Design queue B (Corner): sections calculations, validations.
"""
import pytest
from test_helpers import (
    api_client, get_success_data, validate_success, validate_error, ApiErrorId,
    make_lash_tech_headers,
    create_appointment_payload, create_retail_order_payload, create_patch_test_payload,
)
from test_helpers.fixtures import (
    SM, FD, set_clock, create_studio, create_service_type, create_plan, create_tech,
    create_member, create_membership, sanitize_tech,
)


# ─── calculations ─────────────────────────────────────
def test_peak_surcharge_applies_when_load_ge_3_and_premium():
    """PRD §3.9: "When the technician's same-day load is at least 3 and the linked service is
    premium, `peak_surcharge_cents` is `subtotal_cents` multiplied by 0.15, rounded half up to
    the nearest cent; in every other case `peak_surcharge_cents` is zero."

    Design: Corner/calculations/peak_surcharge_applies_when_load_ge_3_and_premium
    """
    studio = create_studio(name="Glow")
    plan = create_plan(studio["id"], tier="PREMIER", monthly_credit_allotment=8,
                       monthly_fee_cents=9900, loyalty_discount_pct=0.10)
    full_st = create_service_type(studio["id"], code="FULL_SET", name="Full Set",
                                  duration_minutes=60, base_price_cents=12000, credit_cost=4,
                                  category="PREMIUM", requires_patch_test=False)
    tech = create_tech(studio["id"], skill_level=3, station_number=1)
    sanitize_tech(tech["id"], "2026-06-10T08:00:00Z")
    member = create_member(studio["id"])
    create_membership(member["id"], plan["id"], initial_credits=8)
    set_clock("2026-06-09T10:00:00Z")
    appt1 = get_success_data(api_client.create_appointment(
        create_appointment_payload(member["id"], full_st["id"], "2026-06-10T10:00:00Z"), FD))
    get_success_data(api_client.create_appointment(
        create_appointment_payload(member["id"], full_st["id"], "2026-06-10T11:00:00Z"), FD))
    get_success_data(api_client.create_appointment(
        create_appointment_payload(member["id"], full_st["id"], "2026-06-10T12:00:00Z"), FD))
    order = validate_success(api_client.create_retail_order(
        create_retail_order_payload(member["id"], appt1["id"],
            [{"sku": "SERUM", "unit_price_cents": 3300, "quantity": 1},
             {"sku": "GEL", "unit_price_cents": 1665, "quantity": 2}]), FD), expected_status=201)
    # per-line w/ 10% loyalty: round(3300*0.9)=2970; round(1665*2*0.9)=round(2997.0)=2997; sum 5967
    assert order["subtotal_cents"] == 5967, f"subtotal 5967, got {order['subtotal_cents']}"
    assert order["peak_surcharge_cents"] == 895, f"round(5967*0.15)=895, got {order['peak_surcharge_cents']}"
    assert order["total_cents"] == 6862


def test_retail_no_loyalty_when_member_has_no_membership():
    """PRD §3.9: "The loyalty discount fraction is the member's plan `loyalty_discount_pct` if
    the member holds an `ACTIVE` or `PAST_DUE` membership, and zero otherwise."

    Design: Corner/calculations/retail_no_loyalty_when_member_has_no_membership
    """
    studio = create_studio(name="Glow")
    tint = create_service_type(studio["id"], code="TINT", name="Tint", duration_minutes=30,
                              base_price_cents=4000, credit_cost=2, category="STANDARD",
                              requires_patch_test=False)
    tech = create_tech(studio["id"], skill_level=1, station_number=1)
    sanitize_tech(tech["id"], "2026-06-10T08:00:00Z")
    member = create_member(studio["id"])  # NO membership
    set_clock("2026-06-10T09:00:00Z")
    appt = get_success_data(api_client.create_appointment(
        create_appointment_payload(member["id"], tint["id"], "2026-06-10T13:00:00Z"), FD))
    order = validate_success(api_client.create_retail_order(
        create_retail_order_payload(member["id"], appt["id"],
            [{"sku": "SERUM", "unit_price_cents": 3300, "quantity": 1},
             {"sku": "GEL", "unit_price_cents": 1665, "quantity": 2}]), FD), expected_status=201)
    # no loyalty: 3300 + 1665*2=3330 => 6630; STANDARD => no peak
    assert order["subtotal_cents"] == 6630, f"no-discount subtotal 6630, got {order['subtotal_cents']}"
    assert order["peak_surcharge_cents"] == 0
    assert order["total_cents"] == 6630


def _setup_fill_anchor_for_window(fill_sanitize_at):
    """Member with COMPLETED FULL_SET anchor 2026-06-01T10:00:00Z; tech sanitized at fill date."""
    studio = create_studio(name="Glow")
    full_st = create_service_type(studio["id"], code="FULL_SET", name="Full Set",
                                  duration_minutes=120, base_price_cents=12000, credit_cost=4,
                                  category="PREMIUM", requires_patch_test=False)
    fill = create_service_type(studio["id"], code="FILL", name="Fill", duration_minutes=60,
                              base_price_cents=6000, credit_cost=1, category="STANDARD",
                              requires_patch_test=False)
    tech = create_tech(studio["id"], skill_level=3, station_number=1)
    sanitize_tech(tech["id"], "2026-06-01T09:00:00Z")
    sanitize_tech(tech["id"], fill_sanitize_at)
    member = create_member(studio["id"])
    set_clock("2026-06-01T09:00:00Z")
    full_appt = get_success_data(api_client.create_appointment(
        create_appointment_payload(member["id"], full_st["id"], "2026-06-01T10:00:00Z"), FD))
    set_clock("2026-06-01T12:30:00Z")
    get_success_data(api_client.complete_appointment(full_appt["id"],
                                                     make_lash_tech_headers(full_appt["lash_tech_id"])))
    return member, fill["id"]


def test_fill_window_expired_rejected_at_22_days():
    """PRD §3.6: "A gap of more than 21 days has let the window expire and is rejected with
    `ERR_FILL_WINDOW_EXPIRED`; a gap of exactly 21 days or fewer satisfies the upper bound."

    Design: Corner/calculations/fill_window_expired_rejected_at_22_days
    """
    member, fill_id = _setup_fill_anchor_for_window("2026-06-23T09:00:00Z")
    set_clock("2026-06-22T09:00:00Z")
    # anchor 2026-06-01T10:00; FILL 2026-06-23T10:00 => gap 22 days (> 21)
    resp = api_client.create_appointment(
        create_appointment_payload(member["id"], fill_id, "2026-06-23T10:00:00Z"), FD)
    validate_error(resp, ApiErrorId.ERR_FILL_WINDOW_EXPIRED)


def test_fill_without_anchor_rejected():
    """PRD §3.6: "If that anchor is null — the member has no prior `COMPLETED` `PREMIUM`
    appointment — the fill is rejected with `ERR_FILL_REQUIRES_PRIOR_FULL_SET`."

    Design: Corner/calculations/fill_without_anchor_rejected
    """
    studio = create_studio(name="Glow")
    fill = create_service_type(studio["id"], code="FILL", name="Fill", duration_minutes=60,
                              base_price_cents=6000, credit_cost=1, category="STANDARD",
                              requires_patch_test=False)
    tech = create_tech(studio["id"], skill_level=3, station_number=1)
    sanitize_tech(tech["id"], "2026-06-10T08:00:00Z")
    member = create_member(studio["id"])  # no completed premium
    set_clock("2026-06-10T09:00:00Z")
    resp = api_client.create_appointment(
        create_appointment_payload(member["id"], fill["id"], "2026-06-10T13:00:00Z"), FD)
    validate_error(resp, ApiErrorId.ERR_FILL_REQUIRES_PRIOR_FULL_SET)


def test_tech_selector_prefers_lowest_same_day_load():
    """PRD §3.7: "the server ranks them and picks the smallest under this ordering, applied in
    sequence: first the fewest `BOOKED` appointments the technician already has on the same
    UTC calendar date as the new appointment's `start_utc`".

    Design: Corner/calculations/tech_selector_prefers_lowest_load_then_skill
    """
    studio = create_studio(name="Glow")
    full_st = create_service_type(studio["id"], code="FULL_SET", name="Full Set",
                                  duration_minutes=60, base_price_cents=12000, credit_cost=4,
                                  category="PREMIUM", requires_patch_test=False)
    techA = create_tech(studio["id"], full_name="TechA", skill_level=2, station_number=1)
    techB = create_tech(studio["id"], full_name="TechB", skill_level=3, station_number=2)
    sanitize_tech(techA["id"], "2026-06-10T08:00:00Z")
    sanitize_tech(techB["id"], "2026-06-10T08:00:00Z")
    member = create_member(studio["id"])
    set_clock("2026-06-09T10:00:00Z")
    # Seed one BOOKED appt onto TechA by making TechB OFF_DUTY during that booking.
    get_success_data(api_client.set_lash_tech_status(techB["id"], "OFF_DUTY", SM))
    seedA = get_success_data(api_client.create_appointment(
        create_appointment_payload(member["id"], full_st["id"], "2026-06-10T10:00:00Z"), FD))
    assert seedA["lash_tech_id"] == techA["id"]
    get_success_data(api_client.set_lash_tech_status(techB["id"], "AVAILABLE", SM))
    # New booking: TechA has same-day load 1, TechB has 0 -> selector picks TechB.
    new_appt = validate_success(api_client.create_appointment(
        create_appointment_payload(member["id"], full_st["id"], "2026-06-10T14:00:00Z"), FD),
        expected_status=201)
    assert new_appt["lash_tech_id"] == techB["id"], \
        f"lowest same-day load (TechB, 0) wins, got {new_appt['lash_tech_id']}"


# ─── validations ──────────────────────────────────────
def test_premium_service_excludes_junior_tech():
    """PRD §3.7: "a `PREMIUM` service requires a `skill_level` of at least 2, while a
    `STANDARD` service has no skill floor ... If the candidate pool is empty the booking is
    rejected with `ERR_NO_TECH_AVAILABLE`."

    Design: Corner/validations/premium_service_excludes_junior_tech
    """
    studio = create_studio(name="Glow")
    full_st = create_service_type(studio["id"], code="FULL_SET", name="Full Set",
                                  duration_minutes=120, base_price_cents=12000, credit_cost=4,
                                  category="PREMIUM", requires_patch_test=False)
    tech = create_tech(studio["id"], full_name="Junior", skill_level=1, station_number=1)
    sanitize_tech(tech["id"], "2026-06-10T09:00:00Z")
    member = create_member(studio["id"])
    set_clock("2026-06-10T10:00:00Z")
    resp = api_client.create_appointment(
        create_appointment_payload(member["id"], full_st["id"], "2026-06-10T20:00:00Z"), FD)
    validate_error(resp, ApiErrorId.ERR_NO_TECH_AVAILABLE)


def test_retired_service_type_cannot_be_booked():
    """PRD §3.5: "a retired service type (`active` false) is rejected with
    `ERR_SERVICE_TYPE_RETIRED`."

    Design: Corner/validations/retired_service_type_cannot_be_booked
    """
    studio = create_studio(name="Glow")
    full_st = create_service_type(studio["id"], code="FULL_SET", name="Full Set",
                                  duration_minutes=120, base_price_cents=12000, credit_cost=4,
                                  category="PREMIUM", requires_patch_test=False)
    retired = get_success_data(api_client.retire_service_type(full_st["id"], SM))
    assert retired["active"] is False
    tech = create_tech(studio["id"], skill_level=3, station_number=1)
    sanitize_tech(tech["id"], "2026-06-10T09:00:00Z")
    member = create_member(studio["id"])
    set_clock("2026-06-10T10:00:00Z")
    resp = api_client.create_appointment(
        create_appointment_payload(member["id"], full_st["id"], "2026-06-10T20:00:00Z"), FD)
    validate_error(resp, ApiErrorId.ERR_SERVICE_TYPE_RETIRED)


def test_retail_order_appointment_mismatch_other_member():
    """PRD §3.9: "The referenced appointment must be a `BOOKED` appointment belonging to the
    same member, otherwise the order is rejected with `ERR_ORDER_APPOINTMENT_MISMATCH`."

    Design: Corner/validations/retail_order_appointment_mismatch_other_member
    """
    studio = create_studio(name="Glow")
    tint = create_service_type(studio["id"], code="TINT", name="Tint", duration_minutes=30,
                              base_price_cents=4000, credit_cost=2, category="STANDARD",
                              requires_patch_test=False)
    tech = create_tech(studio["id"], skill_level=1, station_number=1)
    sanitize_tech(tech["id"], "2026-06-10T08:00:00Z")
    member_a = create_member(studio["id"], full_name="Ada", email="ada@x.com")
    member_b = create_member(studio["id"], full_name="Bea", email="bea@x.com")
    set_clock("2026-06-10T09:00:00Z")
    appt_b = get_success_data(api_client.create_appointment(
        create_appointment_payload(member_b["id"], tint["id"], "2026-06-10T13:00:00Z"), FD))
    resp = api_client.create_retail_order(
        create_retail_order_payload(member_a["id"], appt_b["id"],
            [{"sku": "SERUM", "unit_price_cents": 3300, "quantity": 1}]), FD)
    validate_error(resp, ApiErrorId.ERR_ORDER_APPOINTMENT_MISMATCH)


def test_retail_order_empty_lines_invalid_request():
    """PRD §3.9: "Each line is an object with a `sku`, a positive `unit_price_cents`, and a
    positive `quantity`; an empty line list or a non-positive unit price or quantity is an
    invalid request."

    Design: Corner/validations/retail_order_empty_lines_invalid_request
    """
    studio = create_studio(name="Glow")
    tint = create_service_type(studio["id"], code="TINT", name="Tint", duration_minutes=30,
                              base_price_cents=4000, credit_cost=2, category="STANDARD",
                              requires_patch_test=False)
    tech = create_tech(studio["id"], skill_level=1, station_number=1)
    sanitize_tech(tech["id"], "2026-06-10T08:00:00Z")
    member = create_member(studio["id"])
    set_clock("2026-06-10T09:00:00Z")
    appt = get_success_data(api_client.create_appointment(
        create_appointment_payload(member["id"], tint["id"], "2026-06-10T13:00:00Z"), FD))
    resp = api_client.create_retail_order(
        create_retail_order_payload(member["id"], appt["id"], []), FD)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_patch_test_create_without_consent_rejected():
    """PRD §3.3: "if `consent_signed` is not true the creation is rejected as an invalid
    request."

    Design: Corner/validations/patch_test_create_without_consent_rejected
    """
    studio = create_studio(name="Glow")
    member = create_member(studio["id"])
    resp = api_client.create_patch_test(
        create_patch_test_payload(member["id"], "2026-06-01T00:00:00Z", consent_signed=False), FD)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
