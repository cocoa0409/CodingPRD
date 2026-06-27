"""Composite setup helpers.

Every test runs against a freshly-restarted, empty server, so each fixture
builds its preconditions from scratch using only PRD-declared endpoints.
Setup calls use get_success_data() (lenient) so setup failures surface as
clear "Setup failed" errors rather than confusing assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS
from .factories import (
    create_herd_payload,
    create_parlor_payload,
    create_ration_payload,
    create_price_sheet_payload,
    create_animal_payload,
    create_breeding_event_payload,
    create_calving_event_payload,
    create_test_day_record_payload,
    create_health_treatment_payload,
    create_milk_check_payload,
    create_milking_shift_payload,
)

HM = TEST_USERS["herd_manager_headers"]
PT = TEST_USERS["parlor_tech_headers"]
VET = TEST_USERS["veterinarian_headers"]
COOP = TEST_USERS["coop_agent_headers"]
AUD = TEST_USERS["auditor_headers"]


# ---------------------------------------------------------------------------
# Clock control
# ---------------------------------------------------------------------------
def set_clock(instant_iso: str):
    """Set the server logical clock to an absolute UTC instant."""
    return get_success_data(api_client.set_clock(instant_iso, HM))


# ---------------------------------------------------------------------------
# Tier 1/2: bare entities
# ---------------------------------------------------------------------------
def create_herd(name="Test Dairy", **overrides):
    """Create a herd. Returns the herd object."""
    return get_success_data(
        api_client.create_herd(create_herd_payload(name=name, **overrides), HM)
    )


def create_parlor(herd_id, turnaround_minutes=0, **overrides):
    """Create a parlor under a herd. Returns the parlor object."""
    return get_success_data(
        api_client.create_parlor(
            create_parlor_payload(herd_id, turnaround_minutes=turnaround_minutes, **overrides),
            HM,
        )
    )


def create_ration(herd_id, **overrides):
    """Create a ration under a herd (computes daily_feed_cost_per_cow). Returns it."""
    return get_success_data(
        api_client.create_ration(create_ration_payload(herd_id, **overrides), HM)
    )


def create_price_sheet(herd_id, settlement_month="2026-06", **overrides):
    """Register an FMMO price sheet. Returns it."""
    return get_success_data(
        api_client.create_price_sheet(
            create_price_sheet_payload(herd_id, settlement_month=settlement_month, **overrides),
            COOP,
        )
    )


def create_animal(herd_id, ear_tag="A-001", birth_date="2023-01-01", **overrides):
    """Register an animal (starts HEIFER). Returns it."""
    return get_success_data(
        api_client.create_animal(
            create_animal_payload(herd_id, ear_tag=ear_tag, birth_date=birth_date, **overrides),
            HM,
        )
    )


# ---------------------------------------------------------------------------
# Tier 1/3: breeding / calving lifecycle shortcuts
# ---------------------------------------------------------------------------
def create_bred_event(animal_id, service_date, sire_code="S-1"):
    """Log an AI service (status BRED). Returns the breeding event."""
    return get_success_data(
        api_client.create_breeding_event(
            create_breeding_event_payload(animal_id, service_date, sire_code), VET
        )
    )


def create_confirmed_breeding(animal_id, service_date, sire_code="S-1"):
    """Log + confirm a breeding event (status CONFIRMED_PREGNANT). Returns it."""
    be = create_bred_event(animal_id, service_date, sire_code)
    return get_success_data(api_client.confirm_breeding_event(be["id"], VET))


def calve(animal_id, breeding_event_id, calving_date):
    """Record a calving. Returns the calving event (carries opened/closed lactation ids)."""
    return get_success_data(
        api_client.create_calving_event(
            create_calving_event_payload(animal_id, breeding_event_id, calving_date), HM
        )
    )


def setup_open_lactation(
    herd_name="Lactation Dairy",
    ear_tag="LA-001",
    birth_date="2023-01-01",
    service_date="2026-01-10",
    calving_date="2026-02-01",
    calving_clock="2026-02-01T00:00:00Z",
    federal_order_number="30",
):
    """
    Build a herd + animal + confirmed breeding + first calving so the animal is
    ACTIVE with one OPEN lactation. Returns (herd, animal, lactation, calving_event).
    The clock is set to calving_clock before the calving.
    """
    set_clock(calving_clock)
    herd = create_herd(name=herd_name, federal_order_number=federal_order_number)
    animal = create_animal(herd["id"], ear_tag=ear_tag, birth_date=birth_date)
    be = create_confirmed_breeding(animal["id"], service_date)
    calving = calve(animal["id"], be["id"], calving_date)
    lactation = get_success_data(
        api_client.get_lactation(calving["opened_lactation_id"], HM)
    )
    return herd, animal, lactation, calving


# ---------------------------------------------------------------------------
# Tier 1/3: test-day records on a lactation
# ---------------------------------------------------------------------------
def add_test_day(lactation_id, test_date, milk_weight_lbs=85.0, fat_pct=3.8,
                 protein_pct=3.1, scc_thousands=150, clock=None):
    """Add a test-day record to a lactation. Optionally set the clock first. Returns the record."""
    if clock is not None:
        set_clock(clock)
    return get_success_data(
        api_client.create_test_day_record(
            create_test_day_record_payload(
                lactation_id, test_date,
                milk_weight_lbs=milk_weight_lbs, fat_pct=fat_pct,
                protein_pct=protein_pct, scc_thousands=scc_thousands,
            ),
            PT,
        )
    )


# ---------------------------------------------------------------------------
# Tier 3/4: milk-check pool ready to finalize
# ---------------------------------------------------------------------------
def setup_provisional_milk_check_single_record(
    scc_thousands=180,
    milk_weight_lbs=1000,
    fat_pct=3.8,
    protein_pct=3.1,
    herd_name="Milk Check Dairy",
    settlement_month="2026-06",
    test_clock="2026-06-10T00:00:00Z",
    test_date="2026-06-10",
    **price_sheet_overrides,
):
    """
    Full chain to a PROVISIONAL MilkCheck with exactly one eligible pooled record:
    herd -> animal -> confirmed breeding -> calving (OPEN lactation) ->
    one test-day record -> price sheet -> milk check.
    Returns (herd, animal, lactation, milk_check, price_sheet, test_day_record).
    """
    herd, animal, lactation, _ = setup_open_lactation(
        herd_name=herd_name, ear_tag="MC-001",
        service_date="2026-01-10", calving_date="2026-02-01",
        calving_clock="2026-02-01T00:00:00Z",
    )
    tdr = add_test_day(
        lactation["id"], test_date,
        milk_weight_lbs=milk_weight_lbs, fat_pct=fat_pct,
        protein_pct=protein_pct, scc_thousands=scc_thousands,
        clock=test_clock,
    )
    price_sheet = create_price_sheet(
        herd["id"], settlement_month=settlement_month, **price_sheet_overrides
    )
    milk_check = get_success_data(
        api_client.create_milk_check(
            create_milk_check_payload(herd["id"], price_sheet["id"]), COOP
        )
    )
    return herd, animal, lactation, milk_check, price_sheet, tdr


def setup_empty_provisional_milk_check(
    herd_name="Empty Check Dairy",
    settlement_month="2026-06",
):
    """
    A PROVISIONAL MilkCheck with no pooled records (price sheet + check only).
    Returns (herd, milk_check, price_sheet).
    """
    herd = create_herd(name=herd_name)
    price_sheet = get_success_data(
        api_client.create_price_sheet(
            create_price_sheet_payload(
                herd["id"], settlement_month=settlement_month, hauling_rate_per_cwt=0,
            ),
            COOP,
        )
    )
    milk_check = get_success_data(
        api_client.create_milk_check(
            create_milk_check_payload(herd["id"], price_sheet["id"]), COOP
        )
    )
    return herd, milk_check, price_sheet


# ---------------------------------------------------------------------------
# Tier 1: parlor with one logged shift (for overlap / void tests)
# ---------------------------------------------------------------------------
def setup_parlor_with_logged_shift(
    turnaround_minutes=30,
    herd_name="Parlor Dairy",
    start_at="2026-06-01T04:00:00Z",
    end_at="2026-06-01T07:00:00Z",
    cows_milked=24,
):
    """
    Herd + parlor (given turnaround) + one LOGGED shift. Returns (herd, parlor, shift).
    """
    herd = create_herd(name=herd_name)
    parlor = create_parlor(herd["id"], turnaround_minutes=turnaround_minutes, name="North D-12")
    shift = get_success_data(
        api_client.create_milking_shift(
            create_milking_shift_payload(parlor["id"], start_at, end_at, cows_milked), PT
        )
    )
    return herd, parlor, shift


# ---------------------------------------------------------------------------
# Tier 1: active cow with a health treatment in force
# ---------------------------------------------------------------------------
def setup_active_cow_with_treatment(
    herd_name="Treatment Dairy",
    ear_tag="TX-001",
    administered_at="2026-06-09T08:00:00Z",
    milk_withhold_hours=96,
    meat_withdrawal_hours=240,
    treatment_clock="2026-06-10T00:00:00Z",
):
    """
    Active cow (first calving) + one ACTIVE health treatment recorded at treatment_clock.
    Returns (herd, animal, treatment).
    """
    herd, animal, _lact, _calving = setup_open_lactation(
        herd_name=herd_name, ear_tag=ear_tag,
        service_date="2026-01-10", calving_date="2026-02-01",
        calving_clock="2026-02-01T00:00:00Z",
    )
    set_clock(treatment_clock)
    treatment = get_success_data(
        api_client.create_health_treatment(
            create_health_treatment_payload(
                animal["id"], administered_at,
                milk_withhold_hours=milk_withhold_hours,
                meat_withdrawal_hours=meat_withdrawal_hours,
            ),
            VET,
        )
    )
    return herd, animal, treatment
