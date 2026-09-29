"""Composite fixtures that drive the API into the states the tests need.

Every fixture builds its state exclusively through documented endpoints — there
is no direct database access anywhere. The server is restarted with an empty
database before each test, so all fixtures are function-scoped and start from
nothing.

The module is organised in two layers:

* small builder functions (``new_manufacturer``, ``approve`` ...) that wrap a
  single call and return the created row; and
* pytest fixtures that chain those builders into the multi-entity states the
  suite exercises.
"""

from typing import Any, Dict, List

import pytest

from prd_bench_local_runner.testing import get_success_data, validate_success

from . import factories as f
from .types import (
    AssignmentAction,
    AssignmentRole,
    BookingAction,
    ClubTier,
    DayPart,
    EquipmentType,
    InvoiceAction,
    ProductCategory,
    ProgramTier,
    ReservationAction,
)
from .test_users import (
    ADMIN_BILLING_HEADERS,
    ADMIN_CONTROLLER_HEADERS,
    ADMIN_HQ_HEADERS,
    STAFF_OPS_HEADERS,
    make_club_headers,
    make_demonstrator_headers,
    make_manufacturer_headers,
)

# ===========================================================================
# Layer 1 — single-call builders
# ===========================================================================


def set_clock(api, to_iso8601: str) -> Dict[str, Any]:
    return get_success_data(api.set_clock(to_iso8601, ADMIN_HQ_HEADERS))


def new_manufacturer(api, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_manufacturer(f.manufacturer_payload(**overrides), ADMIN_HQ_HEADERS)
    )


def new_club(api, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_club(f.club_payload(**overrides), ADMIN_HQ_HEADERS)
    )


def new_food_product(api, manufacturer_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_product(
            f.food_product_payload(manufacturer_id, **overrides),
            make_manufacturer_headers(manufacturer_id),
        )
    )


def new_non_food_product(api, manufacturer_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_product(
            f.non_food_product_payload(manufacturer_id, **overrides),
            make_manufacturer_headers(manufacturer_id),
        )
    )


def new_baseline(api, club_id: str, product_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_baseline(
            f.baseline_payload(club_id, product_id, **overrides), ADMIN_HQ_HEADERS
        )
    )


def new_demonstrator(api, home_club_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_demonstrator(
            f.demonstrator_payload(home_club_id, **overrides), STAFF_OPS_HEADERS
        )
    )


def certify(api, demonstrator_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_certification(
            demonstrator_id, f.certification_payload(**overrides), STAFF_OPS_HEADERS
        )
    )


def new_equipment_unit(api, club_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_equipment_unit(
            f.equipment_unit_payload(club_id, **overrides), make_club_headers(club_id)
        )
    )


def new_demo_event(
    api, manufacturer_id: str, club_id: str, product_id: str, **kwargs: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_demo_event(
            f.demo_event_payload(manufacturer_id, club_id, product_id, **kwargs),
            make_manufacturer_headers(manufacturer_id),
        )
    )


def submit(api, event_id: str, manufacturer_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.demo_event_transition(
            event_id,
            {"action": BookingAction.SUBMIT},
            make_manufacturer_headers(manufacturer_id),
        )
    )


def approve(api, event_id: str, club_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.demo_event_transition(
            event_id, {"action": BookingAction.APPROVE}, make_club_headers(club_id)
        )
    )


def close_out(api, event_id: str, club_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.demo_event_transition(
            event_id, {"action": BookingAction.CLOSE_OUT}, make_club_headers(club_id)
        )
    )


def confirm_booking(api, manufacturer_id: str, club_id: str, event_id: str) -> Dict[str, Any]:
    submit(api, event_id, manufacturer_id)
    return approve(api, event_id, club_id)


def ship(
    api,
    event_id: str,
    manufacturer_id: str,
    cases_shipped: int,
    carrier_reference: str = "TRK-00001",
) -> Dict[str, Any]:
    return get_success_data(
        api.create_shipment(
            event_id,
            f.shipment_payload(cases_shipped, carrier_reference),
            make_manufacturer_headers(manufacturer_id),
        )
    )


def receive(api, shipment_id: str, club_id: str, cases_received: int) -> Dict[str, Any]:
    return get_success_data(
        api.receive_shipment(
            shipment_id, {"cases_received": cases_received}, make_club_headers(club_id)
        )
    )


def reserve(
    api,
    club_id: str,
    equipment_unit_id: str,
    demo_event_id: str,
    window_start_utc: str,
    window_end_utc: str,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_reservation(
            f.reservation_payload(
                equipment_unit_id, demo_event_id, window_start_utc, window_end_utc
            ),
            make_club_headers(club_id),
        )
    )


def activate_reservation(api, reservation_id: str, club_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.reservation_transition(
            reservation_id,
            {"action": ReservationAction.ACTIVATE},
            make_club_headers(club_id),
        )
    )


def assign(
    api, event_id: str, demonstrator_id: str, role: str, **extra: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"demonstrator_id": demonstrator_id, "role": role}
    payload.update(extra)
    return get_success_data(api.create_assignment(event_id, payload, STAFF_OPS_HEADERS))


def confirm_assignment(api, assignment_id: str, demonstrator_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.assignment_transition(
            assignment_id,
            {"action": AssignmentAction.CONFIRM},
            make_demonstrator_headers(demonstrator_id),
        )
    )


def check_in(
    api, assignment_id: str, demonstrator_id: str, occurred_at_utc: str
) -> Dict[str, Any]:
    return get_success_data(
        api.assignment_transition(
            assignment_id,
            {"action": AssignmentAction.CHECK_IN, "occurred_at_utc": occurred_at_utc},
            make_demonstrator_headers(demonstrator_id),
        )
    )


def check_out(
    api, assignment_id: str, demonstrator_id: str, occurred_at_utc: str
) -> Dict[str, Any]:
    return get_success_data(
        api.assignment_transition(
            assignment_id,
            {"action": AssignmentAction.CHECK_OUT, "occurred_at_utc": occurred_at_utc},
            make_demonstrator_headers(demonstrator_id),
        )
    )


def declare_no_show(api, assignment_id: str, note: str = "did not arrive") -> Dict[str, Any]:
    return get_success_data(
        api.assignment_transition(
            assignment_id,
            {"action": AssignmentAction.NO_SHOW, "note": note},
            STAFF_OPS_HEADERS,
        )
    )


def file_reconciliation(
    api,
    event_id: str,
    club_id: str,
    units_sampled: int,
    units_wasted: int,
    units_returned: int,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_reconciliation(
            event_id,
            f.reconciliation_payload(units_sampled, units_wasted, units_returned),
            make_club_headers(club_id),
        )
    )


def read_reconciliation(api, event_id: str, headers=ADMIN_HQ_HEADERS):
    """Reads the event's reconciliation back; the read is an array of length
    zero or one, so this returns the single row or None."""
    rows = validate_success(api.get_reconciliation(event_id, headers))
    assert isinstance(rows, list), "reconciliation read must be an array"
    assert len(rows) <= 1, f"expected 0 or 1 reconciliation rows, got {len(rows)}"
    return rows[0] if rows else None


def event_version(api, event_id: str) -> int:
    return validate_success(api.get_demo_event(event_id, ADMIN_HQ_HEADERS))["version"]


def draft_invoice(api, event_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.create_invoice(
            event_id,
            {"expected_demo_event_version": event_version(api, event_id)},
            ADMIN_HQ_HEADERS,
        )
    )


def issue_invoice(api, invoice_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.invoice_transition(
            invoice_id, {"action": InvoiceAction.ISSUE}, ADMIN_BILLING_HEADERS
        )
    )


def credits_for_event(api, event_id: str, **params: Any) -> List[Dict[str, Any]]:
    query = {"demo_event_id": event_id}
    query.update(params)
    return validate_success(api.list_credits(ADMIN_HQ_HEADERS, query))


# ===========================================================================
# Layer 2 — composite fixtures, one per state the suite needs
# ===========================================================================


@pytest.fixture
def lift_event_ready(api) -> Dict[str, Any]:
    """A CLOSED_OUT / COMPLETED food event with a baseline and a BALANCED
    reconciliation of 320 sampled units — the state a lift measurement needs."""
    mfr = new_manufacturer(
        api,
        legal_name="Northvale Foods LLC",
        billing_email="ap@northvale.example",
        program_tier=ProgramTier.STANDARD,
        credit_limit_cents=5_000_000,
        credit_terms_days=30,
    )
    club = new_club(
        api,
        club_number="C4101",
        name="Riverbend Club 4101",
        region_code="MW",
        club_tier=ClubTier.STANDARD,
        daily_event_capacity=6,
        food_station_count=3,
        health_permit_expires_on="2027-01-31",
    )
    product = new_food_product(
        api,
        mfr["id"],
        sku="NV-CHZ-100",
        name="Aged Cheddar Bites",
        category=ProductCategory.DAIRY,
        unit_cost_cents=210,
        samples_per_case=60,
        weekly_sample_case_pool=40,
    )
    baseline = new_baseline(
        api,
        club["id"],
        product["id"],
        baseline_weekly_units=140,
        baseline_unit_price_cents=1299,
        baseline_week_start_date="2026-09-14",
    )
    lead = new_demonstrator(api, club["id"], full_name="Dana Roth", hourly_rate_cents=2400)
    support = new_demonstrator(
        api, club["id"], full_name="Ivo Marek", hourly_rate_cents=2000
    )
    certify(api, lead["id"], certificate_number="FH-2026-0411")
    certify(api, support["id"], certificate_number="FH-2026-0412")

    event = new_demo_event(
        api,
        mfr["id"],
        club["id"],
        product["id"],
        event_date="2026-09-14",
        day_part=DayPart.MIDDAY,
        requested_sample_cases=6,
        attribution_window_days=14,
    )
    confirm_booking(api, mfr["id"], club["id"], event["id"])

    shipment = ship(api, event["id"], mfr["id"], 6, "TRK-88120")
    receive(api, shipment["id"], club["id"], 6)

    unit = new_equipment_unit(
        api,
        club["id"],
        asset_tag="EQ-4101-07",
        equipment_type=EquipmentType.REFRIGERATED_CART,
    )
    reservation = reserve(
        api,
        club["id"],
        unit["id"],
        event["id"],
        "2026-09-14T11:00:00Z",
        "2026-09-14T16:30:00Z",
    )

    lead_asg = assign(api, event["id"], lead["id"], AssignmentRole.LEAD)
    support_asg = assign(api, event["id"], support["id"], AssignmentRole.SUPPORT)

    set_clock(api, "2026-09-14T16:00:00Z")
    confirm_assignment(api, lead_asg["id"], lead["id"])
    confirm_assignment(api, support_asg["id"], support["id"])
    activate_reservation(api, reservation["id"], club["id"])
    check_in(api, lead_asg["id"], lead["id"], "2026-09-14T11:15:00Z")
    check_in(api, support_asg["id"], support["id"], "2026-09-14T11:20:00Z")
    check_out(api, support_asg["id"], support["id"], "2026-09-14T15:35:00Z")
    check_out(api, lead_asg["id"], lead["id"], "2026-09-14T15:45:00Z")
    close_out(api, event["id"], club["id"])
    recon = file_reconciliation(api, event["id"], club["id"], 320, 20, 20)

    return {
        "manufacturer": mfr,
        "club": club,
        "product": product,
        "baseline": baseline,
        "event_id": event["id"],
        "lead": lead,
        "support": support,
        "reconciliation": recon,
    }


@pytest.fixture
def reliability_seed(api) -> Dict[str, Any]:
    """Clock parked at 2026-09-01T00:00:00Z with one demonstrator and one
    never-submitted DRAFT event to host injected history rows."""
    set_clock(api, "2026-09-01T00:00:00Z")
    mfr = new_manufacturer(
        api,
        legal_name="Cedar Ridge Snacks Inc",
        billing_email="ap@cedarridge.example",
        credit_limit_cents=4_000_000,
    )
    club = new_club(
        api,
        club_number="C4202",
        name="Elmgrove Club 4202",
        region_code="NE",
        daily_event_capacity=5,
        food_station_count=2,
        health_permit_expires_on="2027-03-31",
    )
    product = new_non_food_product(
        api,
        mfr["id"],
        sku="CR-TVC-220",
        name="Countertop Blender Demo Kit",
        category=ProductCategory.HOUSEHOLD,
        unit_cost_cents=1500,
        samples_per_case=10,
        weekly_sample_case_pool=20,
    )
    dem = new_demonstrator(
        api, club["id"], full_name="Priya Nandan", hourly_rate_cents=2300
    )
    draft_event = new_demo_event(
        api,
        mfr["id"],
        club["id"],
        product["id"],
        event_date="2026-10-05",
        day_part=DayPart.MORNING,
        requested_sample_cases=3,
    )
    return {
        "manufacturer": mfr,
        "club": club,
        "product": product,
        "demonstrator": dem,
        "draft_event_id": draft_event["id"],
    }


@pytest.fixture
def rounding_event_ready(api) -> Dict[str, Any]:
    """A SATELLITE / MIDDAY food event closed out with two fractional-cent
    staffing lines and two add-ons, ready for its first invoice."""
    mfr = new_manufacturer(
        api,
        legal_name="Harborlight Provisions Co",
        billing_email="ap@harborlight.example",
        program_tier=ProgramTier.STANDARD,
        credit_limit_cents=9_000_000,
        credit_terms_days=45,
    )
    club = new_club(
        api,
        club_number="C4303",
        name="Satellite Club 4303",
        region_code="SW",
        club_tier=ClubTier.SATELLITE,
        daily_event_capacity=4,
        food_station_count=2,
        health_permit_expires_on="2027-06-30",
    )
    product = new_food_product(
        api,
        mfr["id"],
        sku="HL-DIP-310",
        name="Roasted Pepper Dip Cups",
        category=ProductCategory.DAIRY,
        unit_cost_cents=210,
        samples_per_case=60,
        weekly_sample_case_pool=30,
    )
    lead = new_demonstrator(
        api, club["id"], full_name="Marta Oyelaran", hourly_rate_cents=2331
    )
    support = new_demonstrator(
        api, club["id"], full_name="Kenji Abara", hourly_rate_cents=2001
    )
    certify(api, lead["id"], certificate_number="FH-2026-0501", issued_on="2026-01-15",
            expires_on="2027-01-15")
    certify(api, support["id"], certificate_number="FH-2026-0502",
            issued_on="2026-01-15", expires_on="2027-01-15")

    event = new_demo_event(
        api,
        mfr["id"],
        club["id"],
        product["id"],
        event_date="2026-09-14",
        day_part=DayPart.MIDDAY,
        requested_sample_cases=6,
        addon_services=["PREMIUM_PLACEMENT", "EXTRA_TABLE"],
    )
    confirm_booking(api, mfr["id"], club["id"], event["id"])
    shipment = ship(api, event["id"], mfr["id"], 6, "TRK-90310")
    receive(api, shipment["id"], club["id"], 6)

    unit = new_equipment_unit(
        api,
        club["id"],
        asset_tag="EQ-4303-02",
        equipment_type=EquipmentType.REFRIGERATED_CART,
    )
    reservation = reserve(
        api,
        club["id"],
        unit["id"],
        event["id"],
        "2026-09-14T11:00:00Z",
        "2026-09-14T16:30:00Z",
    )
    lead_asg = assign(api, event["id"], lead["id"], AssignmentRole.LEAD)
    support_asg = assign(api, event["id"], support["id"], AssignmentRole.SUPPORT)

    set_clock(api, "2026-09-14T16:00:00Z")
    confirm_assignment(api, lead_asg["id"], lead["id"])
    confirm_assignment(api, support_asg["id"], support["id"])
    activate_reservation(api, reservation["id"], club["id"])
    check_in(api, lead_asg["id"], lead["id"], "2026-09-14T11:15:00Z")
    check_in(api, support_asg["id"], support["id"], "2026-09-14T11:20:00Z")
    check_out(api, support_asg["id"], support["id"], "2026-09-14T15:35:00Z")
    check_out(api, lead_asg["id"], lead["id"], "2026-09-14T15:45:00Z")
    close_out(api, event["id"], club["id"])
    recon = file_reconciliation(api, event["id"], club["id"], 300, 40, 20)

    return {
        "manufacturer": mfr,
        "club": club,
        "event_id": event["id"],
        "lead_assignment_id": lead_asg["id"],
        "support_assignment_id": support_asg["id"],
        "reconciliation": recon,
    }


@pytest.fixture
def rounding_invoice(api, rounding_event_ready) -> Dict[str, Any]:
    """The DRAFT invoice minted from ``rounding_event_ready``."""
    invoice = draft_invoice(api, rounding_event_ready["event_id"])
    return {**rounding_event_ready, "invoice": invoice}


@pytest.fixture
def credit_bracket_state(api) -> Dict[str, Any]:
    """Two credits on one FLAGSHIP event: a PRODUCT_SHORT credit already
    APPLIED, then a CLUB_CANCELLED credit raised behind it."""
    mfr = new_manufacturer(
        api,
        legal_name="Glenmara Beverage Group",
        billing_email="ap@glenmara.example",
        program_tier=ProgramTier.STANDARD,
        credit_limit_cents=8_000_000,
        credit_terms_days=30,
    )
    club = new_club(
        api,
        club_number="C4404",
        name="Flagship Club 4404",
        region_code="W",
        club_tier=ClubTier.FLAGSHIP,
        daily_event_capacity=8,
        food_station_count=4,
        health_permit_expires_on="2027-08-31",
    )
    product = new_food_product(
        api,
        mfr["id"],
        sku="GM-KMB-410",
        name="Ginger Kombucha Minis",
        category=ProductCategory.BEVERAGE,
        unit_cost_cents=260,
        samples_per_case=48,
        weekly_sample_case_pool=24,
    )
    lead = new_demonstrator(
        api, club["id"], full_name="Rosa Bittner", hourly_rate_cents=2500
    )
    certify(api, lead["id"], certificate_number="FH-2026-0611", issued_on="2026-03-01",
            expires_on="2027-03-01")

    event = new_demo_event(
        api,
        mfr["id"],
        club["id"],
        product["id"],
        event_date="2026-09-14",
        day_part=DayPart.MORNING,
        requested_sample_cases=6,
    )
    confirm_booking(api, mfr["id"], club["id"], event["id"])
    shipment = ship(api, event["id"], mfr["id"], 6, "TRK-91404")
    set_clock(api, "2026-09-10T09:00:00Z")

    short_shipment = receive(api, shipment["id"], club["id"], 2)
    # Snapshot taken before the cancellation, because §3.3 resets the allocation
    # fields to zero once a CONFIRMED booking is cancelled.
    event_after_short_receipt = validate_success(
        api.get_demo_event(event["id"], ADMIN_HQ_HEADERS)
    )

    first = validate_success(
        api.list_credits(
            ADMIN_HQ_HEADERS,
            {"demo_event_id": event["id"], "credit_status": "PENDING_APPROVAL"},
        )
    )[0]
    get_success_data(
        api.decide_credit(
            first["id"],
            {"decision": "APPROVE", "note": "short shipment accepted"},
            ADMIN_CONTROLLER_HEADERS,
        )
    )
    get_success_data(
        api.demo_event_transition(
            event["id"],
            {"action": BookingAction.CANCEL, "reason": "no product on floor"},
            make_club_headers(club["id"]),
        )
    )
    second = validate_success(
        api.list_credits(
            ADMIN_HQ_HEADERS,
            {"demo_event_id": event["id"], "credit_status": "PENDING_APPROVAL"},
        )
    )[0]

    return {
        "manufacturer": mfr,
        "club": club,
        "event_id": event["id"],
        "shipment": short_shipment,
        "event_after_short_receipt": event_after_short_receipt,
        "credit_one_id": first["id"],
        "credit_two_id": second["id"],
    }


@pytest.fixture
def two_dimension_event(api) -> Dict[str, Any]:
    """A CONFIRMED 6-case food event with a LEAD, a SUPPORT and a spare
    SUPPORT demonstrator, clock parked past the no-show grace."""
    mfr = new_manufacturer(
        api,
        legal_name="Ashgrove Dairy Partners",
        billing_email="ap@ashgrove.example",
        credit_limit_cents=5_000_000,
    )
    club = new_club(
        api,
        club_number="C4505",
        name="Ashgrove Club 4505",
        region_code="MW",
        daily_event_capacity=4,
        food_station_count=3,
        health_permit_expires_on="2027-05-31",
    )
    product = new_food_product(
        api,
        mfr["id"],
        sku="AG-YOG-505",
        name="Greek Yogurt Minis",
        category=ProductCategory.DAIRY,
        unit_cost_cents=210,
        samples_per_case=60,
        weekly_sample_case_pool=40,
    )
    lead = new_demonstrator(
        api, club["id"], full_name="Lena Ostrom", hourly_rate_cents=2400
    )
    support_one = new_demonstrator(
        api, club["id"], full_name="Sami Adeyemi", hourly_rate_cents=2000
    )
    support_two = new_demonstrator(
        api, club["id"], full_name="Tova Reinholt", hourly_rate_cents=2000
    )
    for index, dem in enumerate((lead, support_one, support_two), start=1):
        certify(
            api,
            dem["id"],
            certificate_number=f"FH-2026-070{index}",
            issued_on="2026-01-05",
            expires_on="2027-01-05",
        )

    event = new_demo_event(
        api,
        mfr["id"],
        club["id"],
        product["id"],
        event_date="2026-09-14",
        day_part=DayPart.MIDDAY,
        requested_sample_cases=6,
    )
    confirm_booking(api, mfr["id"], club["id"], event["id"])

    return {
        "manufacturer": mfr,
        "club": club,
        "event_id": event["id"],
        "lead": lead,
        "support_one": support_one,
        "support_two": support_two,
    }


@pytest.fixture
def void_redraft_invoice(api) -> Dict[str, Any]:
    """A GOLD vendor's closed-out MIDDAY food event with its first DRAFT
    invoice and the LEAD demonstrator still on the original rate."""
    mfr = new_manufacturer(
        api,
        legal_name="Brightfield Creamery",
        billing_email="ap@brightfield.example",
        program_tier=ProgramTier.GOLD,
        credit_limit_cents=5_000_000,
        credit_terms_days=30,
    )
    club = new_club(
        api,
        club_number="C4606",
        name="Brightfield Club 4606",
        region_code="SE",
        daily_event_capacity=5,
        food_station_count=3,
        health_permit_expires_on="2027-04-30",
    )
    product = new_food_product(
        api,
        mfr["id"],
        sku="BF-ICE-606",
        name="Vanilla Bean Gelato Cups",
        category=ProductCategory.FROZEN,
        unit_cost_cents=240,
        samples_per_case=60,
        weekly_sample_case_pool=30,
    )
    lead = new_demonstrator(
        api, club["id"], full_name="Cyrus Whitlock", hourly_rate_cents=2400
    )
    support = new_demonstrator(
        api, club["id"], full_name="Ines Palgrave", hourly_rate_cents=2000
    )
    certify(api, lead["id"], certificate_number="FH-2026-0801", issued_on="2026-02-10",
            expires_on="2027-02-10")
    certify(api, support["id"], certificate_number="FH-2026-0802",
            issued_on="2026-02-10", expires_on="2027-02-10")

    event = new_demo_event(
        api,
        mfr["id"],
        club["id"],
        product["id"],
        event_date="2026-09-14",
        day_part=DayPart.MIDDAY,
        requested_sample_cases=6,
        addon_services=["ALLERGEN_SIGNAGE"],
    )
    confirm_booking(api, mfr["id"], club["id"], event["id"])
    shipment = ship(api, event["id"], mfr["id"], 6, "TRK-92606")
    receive(api, shipment["id"], club["id"], 6)

    unit = new_equipment_unit(
        api,
        club["id"],
        asset_tag="EQ-4606-03",
        equipment_type=EquipmentType.REFRIGERATED_CART,
    )
    reservation = reserve(
        api,
        club["id"],
        unit["id"],
        event["id"],
        "2026-09-14T11:00:00Z",
        "2026-09-14T16:30:00Z",
    )
    lead_asg = assign(api, event["id"], lead["id"], AssignmentRole.LEAD)
    support_asg = assign(api, event["id"], support["id"], AssignmentRole.SUPPORT)

    set_clock(api, "2026-09-14T16:00:00Z")
    confirm_assignment(api, lead_asg["id"], lead["id"])
    confirm_assignment(api, support_asg["id"], support["id"])
    activate_reservation(api, reservation["id"], club["id"])
    check_in(api, lead_asg["id"], lead["id"], "2026-09-14T11:15:00Z")
    check_in(api, support_asg["id"], support["id"], "2026-09-14T11:20:00Z")
    check_out(api, support_asg["id"], support["id"], "2026-09-14T14:20:00Z")
    check_out(api, lead_asg["id"], lead["id"], "2026-09-14T15:45:00Z")
    close_out(api, event["id"], club["id"])
    recon = file_reconciliation(api, event["id"], club["id"], 300, 40, 20)
    invoice = draft_invoice(api, event["id"])

    return {
        "manufacturer": mfr,
        "club": club,
        "event_id": event["id"],
        "lead": lead,
        "lead_assignment_id": lead_asg["id"],
        "support_assignment_id": support_asg["id"],
        "reconciliation": recon,
        "invoice": invoice,
    }


@pytest.fixture
def third_strike_state(api) -> Dict[str, Any]:
    """Two strikes already on the books and the same demonstrator leading two
    CONFIRMED events in different ISO weeks; clock past E1's grace."""
    mfr = new_manufacturer(
        api,
        legal_name="Kesterlin Foods Ltd",
        billing_email="ap@kesterlin.example",
        credit_limit_cents=5_000_000,
    )
    club = new_club(
        api,
        club_number="C4707",
        name="Kesterlin Club 4707",
        region_code="MW",
        daily_event_capacity=4,
        food_station_count=3,
        health_permit_expires_on="2027-09-30",
    )
    product = new_food_product(
        api,
        mfr["id"],
        sku="KF-SAU-707",
        name="Smoked Paprika Sausage Bites",
        category=ProductCategory.SNACK,
        unit_cost_cents=210,
        samples_per_case=60,
        weekly_sample_case_pool=40,
    )
    dem = new_demonstrator(
        api, club["id"], full_name="Odalys Brun", hourly_rate_cents=2400
    )
    certify(api, dem["id"], certificate_number="FH-2026-0901", issued_on="2026-01-20",
            expires_on="2027-01-20")

    history_host = new_demo_event(
        api,
        mfr["id"],
        club["id"],
        product["id"],
        event_date="2026-10-12",
        day_part=DayPart.MORNING,
        requested_sample_cases=3,
    )
    get_success_data(
        api.inject_assignment_history(
            {
                "demonstrator_id": dem["id"],
                "demo_event_id": history_host["id"],
                "entries": [
                    f.history_entry(
                        "2026-07-10T11:15:00Z",
                        "2026-07-10T17:15:00Z",
                        "NO_SHOW",
                        AssignmentRole.SUPPORT,
                    ),
                    f.history_entry(
                        "2026-07-17T11:15:00Z",
                        "2026-07-17T17:15:00Z",
                        "NO_SHOW",
                        AssignmentRole.SUPPORT,
                    ),
                ],
            },
            ADMIN_HQ_HEADERS,
        )
    )

    first = new_demo_event(
        api,
        mfr["id"],
        club["id"],
        product["id"],
        event_date="2026-09-14",
        day_part=DayPart.MIDDAY,
        requested_sample_cases=4,
    )
    confirm_booking(api, mfr["id"], club["id"], first["id"])
    second = new_demo_event(
        api,
        mfr["id"],
        club["id"],
        product["id"],
        event_date="2026-09-21",
        day_part=DayPart.MIDDAY,
        requested_sample_cases=4,
    )
    confirm_booking(api, mfr["id"], club["id"], second["id"])

    first_asg = assign(api, first["id"], dem["id"], AssignmentRole.LEAD)
    second_asg = assign(api, second["id"], dem["id"], AssignmentRole.LEAD)
    second_before = validate_success(api.get_demo_event(second["id"], ADMIN_HQ_HEADERS))
    set_clock(api, "2026-09-14T11:35:00Z")

    return {
        "manufacturer": mfr,
        "club": club,
        "demonstrator": dem,
        "history_host_id": history_host["id"],
        "first_event_id": first["id"],
        "second_event_id": second["id"],
        "first_assignment_id": first_asg["id"],
        "second_assignment_id": second_asg["id"],
        "second_event_before": second_before,
    }


@pytest.fixture
def credit_cascade_state(api) -> Dict[str, Any]:
    """A DRAFT invoice for 66260 cents against a 60000-cent credit limit, with
    a 33810-cent no-show credit still PENDING_APPROVAL."""
    mfr = new_manufacturer(
        api,
        legal_name="Thornbury Provisions",
        billing_email="ap@thornbury.example",
        program_tier=ProgramTier.STANDARD,
        credit_limit_cents=60_000,
        credit_terms_days=15,
    )
    club = new_club(
        api,
        club_number="C4808",
        name="Thornbury Club 4808",
        region_code="NE",
        daily_event_capacity=4,
        food_station_count=2,
        health_permit_expires_on="2027-07-31",
    )
    product = new_food_product(
        api,
        mfr["id"],
        sku="TP-CHK-808",
        name="Herb Chicken Skewers",
        category=ProductCategory.FROZEN,
        unit_cost_cents=210,
        samples_per_case=60,
        weekly_sample_case_pool=20,
    )
    lead = new_demonstrator(
        api, club["id"], full_name="Halvard Ness", hourly_rate_cents=2400
    )
    support = new_demonstrator(
        api, club["id"], full_name="Bea Curzon", hourly_rate_cents=2000
    )
    certify(api, lead["id"], certificate_number="FH-2026-1001", issued_on="2026-01-08",
            expires_on="2027-01-08")
    certify(api, support["id"], certificate_number="FH-2026-1002",
            issued_on="2026-01-08", expires_on="2027-01-08")

    event = new_demo_event(
        api,
        mfr["id"],
        club["id"],
        product["id"],
        event_date="2026-09-14",
        day_part=DayPart.MIDDAY,
        requested_sample_cases=4,
    )
    confirm_booking(api, mfr["id"], club["id"], event["id"])
    shipment = ship(api, event["id"], mfr["id"], 4, "TRK-93808")
    receive(api, shipment["id"], club["id"], 4)

    unit = new_equipment_unit(
        api,
        club["id"],
        asset_tag="EQ-4808-01",
        equipment_type=EquipmentType.REFRIGERATED_CART,
    )
    reservation = reserve(
        api,
        club["id"],
        unit["id"],
        event["id"],
        "2026-09-14T11:00:00Z",
        "2026-09-14T16:30:00Z",
    )
    lead_asg = assign(api, event["id"], lead["id"], AssignmentRole.LEAD)
    support_asg = assign(api, event["id"], support["id"], AssignmentRole.SUPPORT)

    set_clock(api, "2026-09-14T11:35:00Z")
    declare_no_show(api, support_asg["id"], note="no arrival at station")
    confirm_assignment(api, lead_asg["id"], lead["id"])
    activate_reservation(api, reservation["id"], club["id"])
    check_in(api, lead_asg["id"], lead["id"], "2026-09-14T11:15:00Z")
    set_clock(api, "2026-09-14T16:00:00Z")
    check_out(api, lead_asg["id"], lead["id"], "2026-09-14T15:45:00Z")
    close_out(api, event["id"], club["id"])
    recon = file_reconciliation(api, event["id"], club["id"], 200, 30, 10)
    invoice = draft_invoice(api, event["id"])
    credit = validate_success(
        api.list_credits(ADMIN_HQ_HEADERS, {"demo_event_id": event["id"]})
    )[0]

    return {
        "manufacturer": mfr,
        "club": club,
        "event_id": event["id"],
        "reconciliation": recon,
        "invoice": invoice,
        "credit_id": credit["id"],
    }


@pytest.fixture
def capacity_precedence_setup(api) -> Dict[str, Any]:
    """A one-slot club whose only slot is taken, plus a second event left in
    DRAFT so a state failure and a capacity failure are both live."""
    mfr = new_manufacturer(
        api,
        legal_name="Verrow Housewares",
        billing_email="ap@verrow.example",
        credit_limit_cents=3_000_000,
    )
    club = new_club(
        api,
        club_number="C4909",
        name="Verrow Club 4909",
        region_code="W",
        daily_event_capacity=1,
        food_station_count=2,
        health_permit_expires_on="2027-10-31",
    )
    product = new_non_food_product(
        api,
        mfr["id"],
        sku="VW-PAN-909",
        name="Ceramic Saute Pan",
        category=ProductCategory.HOUSEHOLD,
        unit_cost_cents=3400,
        samples_per_case=4,
        weekly_sample_case_pool=20,
    )
    first = new_demo_event(
        api,
        mfr["id"],
        club["id"],
        product["id"],
        event_date="2026-09-14",
        day_part=DayPart.MORNING,
        requested_sample_cases=2,
    )
    confirm_booking(api, mfr["id"], club["id"], first["id"])
    second = new_demo_event(
        api,
        mfr["id"],
        club["id"],
        product["id"],
        event_date="2026-09-14",
        day_part=DayPart.AFTERNOON,
        requested_sample_cases=2,
    )
    return {
        "manufacturer": mfr,
        "club": club,
        "product": product,
        "confirmed_event_id": first["id"],
        "draft_event_id": second["id"],
    }


@pytest.fixture
def cert_precedence_setup(api) -> Dict[str, Any]:
    """A CONFIRMED food event at club A and an uncertified demonstrator homed
    at club B, so the certification gate and the home-club gate both fail."""
    mfr = new_manufacturer(
        api,
        legal_name="Saltmarsh Kitchens",
        billing_email="ap@saltmarsh.example",
        credit_limit_cents=3_000_000,
    )
    host = new_club(
        api,
        club_number="C5010",
        name="Saltmarsh Host Club 5010",
        region_code="SE",
        daily_event_capacity=4,
        food_station_count=2,
        health_permit_expires_on="2027-11-30",
    )
    home = new_club(
        api,
        club_number="C5011",
        name="Saltmarsh Home Club 5011",
        region_code="SE",
        daily_event_capacity=4,
        food_station_count=2,
        health_permit_expires_on="2027-11-30",
    )
    product = new_food_product(
        api,
        mfr["id"],
        sku="SM-SOU-010",
        name="Roasted Tomato Soup Shots",
        category=ProductCategory.DAIRY,
        unit_cost_cents=190,
        samples_per_case=60,
        weekly_sample_case_pool=20,
    )
    dem = new_demonstrator(
        api, home["id"], full_name="Ronan Vasquez", hourly_rate_cents=2200
    )
    event = new_demo_event(
        api,
        mfr["id"],
        host["id"],
        product["id"],
        event_date="2026-09-14",
        day_part=DayPart.MIDDAY,
        requested_sample_cases=3,
    )
    confirm_booking(api, mfr["id"], host["id"], event["id"])
    return {
        "manufacturer": mfr,
        "host_club": host,
        "home_club": home,
        "demonstrator": dem,
        "event_id": event["id"],
    }


@pytest.fixture
def capacity_boundary_setup(api) -> Dict[str, Any]:
    """A two-slot club with one approval already banked and two more SUBMITTED
    events queued behind it."""
    mfr = new_manufacturer(
        api,
        legal_name="Ambrose Goods Co",
        billing_email="ap@ambrose.example",
        credit_limit_cents=4_000_000,
    )
    club = new_club(
        api,
        club_number="C5112",
        name="Ambrose Club 5112",
        region_code="MW",
        daily_event_capacity=2,
        food_station_count=1,
        health_permit_expires_on="2027-12-31",
    )
    household = new_non_food_product(
        api,
        mfr["id"],
        sku="AG-MOP-112",
        name="Spin Mop System",
        category=ProductCategory.HOUSEHOLD,
        unit_cost_cents=2900,
        samples_per_case=4,
        weekly_sample_case_pool=30,
    )
    electronics = new_non_food_product(
        api,
        mfr["id"],
        sku="AG-SPK-113",
        name="Portable Speaker",
        category=ProductCategory.ELECTRONICS,
        unit_cost_cents=6900,
        samples_per_case=2,
        weekly_sample_case_pool=30,
    )
    events = {}
    for key, product_id, day_part in (
        ("a", household["id"], DayPart.MORNING),
        ("b", household["id"], DayPart.MIDDAY),
        ("c", electronics["id"], DayPart.AFTERNOON),
    ):
        event = new_demo_event(
            api,
            mfr["id"],
            club["id"],
            product_id,
            event_date="2026-09-14",
            day_part=day_part,
            requested_sample_cases=2,
        )
        submit(api, event["id"], mfr["id"])
        events[key] = event["id"]
    approve(api, events["a"], club["id"])
    return {"manufacturer": mfr, "club": club, "events": events}


@pytest.fixture
def zero_delivery_event(api) -> Dict[str, Any]:
    """A closed-out NON_FOOD_DEMO event whose only shipment was refused
    outright, so no case was ever delivered."""
    mfr = new_manufacturer(
        api,
        legal_name="Halden Electronics",
        billing_email="ap@halden.example",
        credit_limit_cents=4_000_000,
    )
    club = new_club(
        api,
        club_number="C5213",
        name="Halden Club 5213",
        region_code="NW",
        daily_event_capacity=3,
        food_station_count=1,
        health_permit_expires_on="2027-12-31",
    )
    product = new_non_food_product(
        api,
        mfr["id"],
        sku="HE-EAR-213",
        name="Noise Cancelling Earbuds",
        category=ProductCategory.ELECTRONICS,
        unit_cost_cents=6900,
        samples_per_case=4,
        weekly_sample_case_pool=30,
    )
    dem = new_demonstrator(
        api, club["id"], full_name="Iker Solano", hourly_rate_cents=2100
    )
    event = new_demo_event(
        api,
        mfr["id"],
        club["id"],
        product["id"],
        event_date="2026-09-14",
        day_part=DayPart.MORNING,
        requested_sample_cases=3,
    )
    confirm_booking(api, mfr["id"], club["id"], event["id"])
    shipment = ship(api, event["id"], mfr["id"], 3, "TRK-55213")
    rejected = receive(api, shipment["id"], club["id"], 0)
    asg = assign(api, event["id"], dem["id"], AssignmentRole.LEAD)
    set_clock(api, "2026-09-14T14:00:00Z")
    confirm_assignment(api, asg["id"], dem["id"])
    check_in(api, asg["id"], dem["id"], "2026-09-14T08:15:00Z")
    check_out(api, asg["id"], dem["id"], "2026-09-14T13:45:00Z")
    close_out(api, event["id"], club["id"])
    return {
        "manufacturer": mfr,
        "club": club,
        "event_id": event["id"],
        "assignment_id": asg["id"],
        "shipment": rejected,
    }


@pytest.fixture
def restricted_club_events(api) -> Dict[str, Any]:
    """One food and one non-food event, both SUBMITTED at a club that has been
    moved to RESTRICTED without touching either event."""
    mfr = new_manufacturer(
        api,
        legal_name="Merrivale Brands",
        billing_email="ap@merrivale.example",
        credit_limit_cents=4_000_000,
    )
    club = new_club(
        api,
        club_number="C5314",
        name="Merrivale Club 5314",
        region_code="SE",
        daily_event_capacity=4,
        food_station_count=2,
        health_permit_expires_on="2027-12-31",
    )
    food = new_food_product(
        api,
        mfr["id"],
        sku="MB-CRO-314",
        name="Butter Croissant Bites",
        category=ProductCategory.BAKERY,
        unit_cost_cents=175,
        samples_per_case=60,
        weekly_sample_case_pool=24,
    )
    non_food = new_non_food_product(
        api,
        mfr["id"],
        sku="MB-BIN-315",
        name="Stackable Storage Bin",
        category=ProductCategory.HOUSEHOLD,
        unit_cost_cents=1900,
        samples_per_case=4,
        weekly_sample_case_pool=24,
    )
    food_event = new_demo_event(
        api,
        mfr["id"],
        club["id"],
        food["id"],
        event_date="2026-09-14",
        day_part=DayPart.MIDDAY,
        requested_sample_cases=4,
    )
    submit(api, food_event["id"], mfr["id"])
    non_food_event = new_demo_event(
        api,
        mfr["id"],
        club["id"],
        non_food["id"],
        event_date="2026-09-14",
        day_part=DayPart.MORNING,
        requested_sample_cases=2,
    )
    submit(api, non_food_event["id"], mfr["id"])
    restricted = get_success_data(
        api.update_club(club["id"], {"club_status": "RESTRICTED"}, ADMIN_HQ_HEADERS)
    )
    return {
        "manufacturer": mfr,
        "club": club,
        "restricted_club": restricted,
        "food_event_id": food_event["id"],
        "non_food_event_id": non_food_event["id"],
    }


@pytest.fixture
def variance_blocked_invoice(api) -> Dict[str, Any]:
    """A well-formed DRAFT invoice sitting behind a VARIANCE_FLAGGED
    reconciliation on the same event."""
    mfr = new_manufacturer(
        api,
        legal_name="Larkfield Bakehouse",
        billing_email="ap@larkfield.example",
        credit_limit_cents=5_000_000,
    )
    club = new_club(
        api,
        club_number="C5415",
        name="Larkfield Club 5415",
        region_code="MW",
        daily_event_capacity=3,
        food_station_count=2,
        health_permit_expires_on="2027-12-31",
    )
    product = new_food_product(
        api,
        mfr["id"],
        sku="LB-SCO-415",
        name="Cranberry Scone Halves",
        category=ProductCategory.BAKERY,
        unit_cost_cents=210,
        samples_per_case=60,
        weekly_sample_case_pool=20,
    )
    dem = new_demonstrator(
        api, club["id"], full_name="Marisol Freen", hourly_rate_cents=2500
    )
    certify(api, dem["id"], certificate_number="FH-2026-1201", issued_on="2026-02-11",
            expires_on="2027-02-11")
    event = new_demo_event(
        api,
        mfr["id"],
        club["id"],
        product["id"],
        event_date="2026-09-14",
        day_part=DayPart.MORNING,
        requested_sample_cases=4,
    )
    confirm_booking(api, mfr["id"], club["id"], event["id"])
    shipment = ship(api, event["id"], mfr["id"], 4, "TRK-66415")
    receive(api, shipment["id"], club["id"], 4)
    unit = new_equipment_unit(
        api,
        club["id"],
        asset_tag="EQ-5415-01",
        equipment_type=EquipmentType.DISPLAY_TABLE,
    )
    reservation = reserve(
        api,
        club["id"],
        unit["id"],
        event["id"],
        "2026-09-14T08:00:00Z",
        "2026-09-14T13:30:00Z",
    )
    asg = assign(api, event["id"], dem["id"], AssignmentRole.LEAD)
    set_clock(api, "2026-09-14T13:00:00Z")
    confirm_assignment(api, asg["id"], dem["id"])
    activate_reservation(api, reservation["id"], club["id"])
    check_in(api, asg["id"], dem["id"], "2026-09-14T08:15:00Z")
    check_out(api, asg["id"], dem["id"], "2026-09-14T12:45:00Z")
    close_out(api, event["id"], club["id"])
    recon = file_reconciliation(api, event["id"], club["id"], 200, 20, 10)
    invoice = draft_invoice(api, event["id"])
    return {
        "manufacturer": mfr,
        "club": club,
        "event_id": event["id"],
        "reconciliation": recon,
        "invoice": invoice,
    }


@pytest.fixture
def equipment_buffer_setup(api) -> Dict[str, Any]:
    """One TV cart already HELD for a MORNING event until 13:30Z, with a
    CONFIRMED AFTERNOON event waiting for the same unit."""
    mfr = new_manufacturer(
        api,
        legal_name="Norsted Audio",
        billing_email="ap@norsted.example",
        credit_limit_cents=4_000_000,
    )
    club = new_club(
        api,
        club_number="C5516",
        name="Norsted Club 5516",
        region_code="W",
        daily_event_capacity=4,
        food_station_count=1,
        health_permit_expires_on="2027-12-31",
    )
    product = new_non_food_product(
        api,
        mfr["id"],
        sku="NA-SND-516",
        name="Compact Soundbar",
        category=ProductCategory.ELECTRONICS,
        unit_cost_cents=8900,
        samples_per_case=2,
        weekly_sample_case_pool=30,
    )
    unit = new_equipment_unit(
        api, club["id"], asset_tag="EQ-5516-TV1", equipment_type=EquipmentType.TV_CART
    )
    morning = new_demo_event(
        api,
        mfr["id"],
        club["id"],
        product["id"],
        event_date="2026-09-14",
        day_part=DayPart.MORNING,
        requested_sample_cases=2,
    )
    confirm_booking(api, mfr["id"], club["id"], morning["id"])
    afternoon = new_demo_event(
        api,
        mfr["id"],
        club["id"],
        product["id"],
        event_date="2026-09-14",
        day_part=DayPart.AFTERNOON,
        requested_sample_cases=2,
    )
    confirm_booking(api, mfr["id"], club["id"], afternoon["id"])
    held = reserve(
        api,
        club["id"],
        unit["id"],
        morning["id"],
        "2026-09-14T08:00:00Z",
        "2026-09-14T13:30:00Z",
    )
    return {
        "manufacturer": mfr,
        "club": club,
        "unit": unit,
        "morning_event_id": morning["id"],
        "afternoon_event_id": afternoon["id"],
        "held_reservation": held,
    }


@pytest.fixture
def touching_shift_setup(api) -> Dict[str, Any]:
    """A MORNING and an AFTERNOON event at one club, with D1 already leading
    the MORNING shift that ends exactly when the AFTERNOON shift starts."""
    mfr = new_manufacturer(
        api,
        legal_name="Wexley Apparel",
        billing_email="ap@wexley.example",
        credit_limit_cents=4_000_000,
    )
    club = new_club(
        api,
        club_number="C5617",
        name="Wexley Club 5617",
        region_code="NE",
        daily_event_capacity=4,
        food_station_count=1,
        health_permit_expires_on="2027-12-31",
    )
    product = new_non_food_product(
        api,
        mfr["id"],
        sku="WX-FLC-617",
        name="Merino Fleece Pullover",
        category=ProductCategory.APPAREL,
        unit_cost_cents=4200,
        samples_per_case=6,
        weekly_sample_case_pool=30,
    )
    first_dem = new_demonstrator(
        api,
        club["id"],
        full_name="Priya Manthei",
        hourly_rate_cents=2300,
        max_weekly_events=5,
    )
    second_dem = new_demonstrator(
        api,
        club["id"],
        full_name="Ewan Tolbert",
        hourly_rate_cents=2300,
        max_weekly_events=5,
    )
    morning = new_demo_event(
        api,
        mfr["id"],
        club["id"],
        product["id"],
        event_date="2026-09-14",
        day_part=DayPart.MORNING,
        requested_sample_cases=2,
    )
    confirm_booking(api, mfr["id"], club["id"], morning["id"])
    afternoon = new_demo_event(
        api,
        mfr["id"],
        club["id"],
        product["id"],
        event_date="2026-09-14",
        day_part=DayPart.AFTERNOON,
        requested_sample_cases=2,
    )
    confirm_booking(api, mfr["id"], club["id"], afternoon["id"])
    morning_asg = assign(api, morning["id"], first_dem["id"], AssignmentRole.LEAD)
    return {
        "manufacturer": mfr,
        "club": club,
        "first_demonstrator": first_dem,
        "second_demonstrator": second_dem,
        "morning_event_id": morning["id"],
        "afternoon_event_id": afternoon["id"],
        "morning_assignment": morning_asg,
    }


@pytest.fixture
def pool_revocation_setup(api) -> Dict[str, Any]:
    """A 10-case weekly pool with 6 cases consumed by an approved Monday event
    and a 10-case Wednesday event queued in the same ISO week."""
    mfr = new_manufacturer(
        api,
        legal_name="Corbell Home Supply",
        billing_email="ap@corbell.example",
        program_tier=ProgramTier.STANDARD,
        credit_limit_cents=4_000_000,
    )
    club = new_club(
        api,
        club_number="C5718",
        name="Corbell Club 5718",
        region_code="SW",
        daily_event_capacity=3,
        food_station_count=1,
        health_permit_expires_on="2027-12-31",
    )
    product = new_non_food_product(
        api,
        mfr["id"],
        sku="CB-BRM-718",
        name="Silicone Broom Head",
        category=ProductCategory.HOUSEHOLD,
        unit_cost_cents=1600,
        samples_per_case=4,
        weekly_sample_case_pool=10,
        emergency_reserve_cases=5,
    )
    monday = new_demo_event(
        api,
        mfr["id"],
        club["id"],
        product["id"],
        event_date="2026-09-14",
        day_part=DayPart.MORNING,
        requested_sample_cases=6,
    )
    submit(api, monday["id"], mfr["id"])
    approved_monday = approve(api, monday["id"], club["id"])
    wednesday = new_demo_event(
        api,
        mfr["id"],
        club["id"],
        product["id"],
        event_date="2026-09-16",
        day_part=DayPart.MIDDAY,
        requested_sample_cases=10,
    )
    submit(api, wednesday["id"], mfr["id"])
    capacity = validate_success(
        api.get_club_capacity(
            club["id"],
            make_club_headers(club["id"]),
            event_date="2026-09-14",
            product_id=product["id"],
        )
    )
    return {
        "manufacturer": mfr,
        "club": club,
        "product": product,
        "monday_event": approved_monday,
        "wednesday_event_id": wednesday["id"],
        "capacity_before": capacity,
    }


@pytest.fixture
def void_receivable_invoice(api) -> Dict[str, Any]:
    """A 49790-cent DRAFT invoice against a 40000-cent credit limit on a
    closed-out AFTERNOON non-food event."""
    mfr = new_manufacturer(
        api,
        legal_name="Ashgrove Outfitters",
        billing_email="ap@ashgrove-outfitters.example",
        program_tier=ProgramTier.GOLD,
        credit_limit_cents=40_000,
        credit_terms_days=30,
    )
    club = new_club(
        api,
        club_number="C5819",
        name="Ashgrove Club 5819",
        region_code="NE",
        club_tier=ClubTier.FLAGSHIP,
        daily_event_capacity=4,
        food_station_count=2,
        health_permit_expires_on="2027-12-31",
    )
    product = new_non_food_product(
        api,
        mfr["id"],
        sku="AO-VST-819",
        name="Packable Down Vest",
        category=ProductCategory.APPAREL,
        unit_cost_cents=5200,
        samples_per_case=4,
        weekly_sample_case_pool=20,
    )
    dem = new_demonstrator(
        api, club["id"], full_name="Signe Halloran", hourly_rate_cents=2200
    )
    event = new_demo_event(
        api,
        mfr["id"],
        club["id"],
        product["id"],
        event_date="2026-09-14",
        day_part=DayPart.AFTERNOON,
        requested_sample_cases=3,
    )
    confirm_booking(api, mfr["id"], club["id"], event["id"])
    shipment = ship(api, event["id"], mfr["id"], 3, "TRK-77819")
    receive(api, shipment["id"], club["id"], 3)
    asg = assign(api, event["id"], dem["id"], AssignmentRole.LEAD)
    set_clock(api, "2026-09-14T19:00:00Z")
    confirm_assignment(api, asg["id"], dem["id"])
    check_in(api, asg["id"], dem["id"], "2026-09-14T14:15:00Z")
    check_out(api, asg["id"], dem["id"], "2026-09-14T18:45:00Z")
    close_out(api, event["id"], club["id"])
    recon = file_reconciliation(api, event["id"], club["id"], 12, 0, 0)
    invoice = draft_invoice(api, event["id"])
    vendor_before = validate_success(api.get_manufacturer(mfr["id"], ADMIN_HQ_HEADERS))
    return {
        "manufacturer": mfr,
        "club": club,
        "event_id": event["id"],
        "assignment_id": asg["id"],
        "reconciliation": recon,
        "invoice": invoice,
        "vendor_before": vendor_before,
    }
