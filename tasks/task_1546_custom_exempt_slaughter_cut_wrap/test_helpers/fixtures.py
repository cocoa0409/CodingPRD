"""Composite setup helpers.

Every helper builds its preconditions from scratch against a freshly restarted
server (logical clock at the default 2026-08-01T00:00:00Z, PRD §2.4). Clock
movement inside any single flow is monotonic: the logical clock is only ever
moved forward, matching the manager-only capability of PRD §2.4.

Ownership threading (PRD §2.1): any call whose success depends on the caller
owning the resource chain is made with make_customer_headers(<Customer.id>).
Staff calls use the opaque operator/manager headers.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    add_share_payload,
    create_appointment_payload,
    create_capacity_day_payload,
    create_cut_sheet_payload,
    create_customer_payload,
    pay_deposit_payload,
    payment_payload,
    receive_animal_payload,
    reschedule_payload,
    revise_cut_sheet_payload,
    set_clock_payload,
    weigh_animal_payload,
)
from .test_users import TEST_USERS, make_customer_headers

OP = TEST_USERS["operator_headers"]
MGR = TEST_USERS["manager_headers"]


# ---------------------------------------------------------------------------
# Tier 1: basic entity creation / reads
# ---------------------------------------------------------------------------

def create_customer(name="Ann Orr", phone="555-0101", email="ann@x.com") -> dict:
    resp = api_client.create_customer(create_customer_payload(name, phone, email), OP)
    return get_success_data(resp)


def create_capacity_day(date, capacity_head) -> dict:
    resp = api_client.create_capacity_day(create_capacity_day_payload(date, capacity_head), MGR)
    return get_success_data(resp)


def set_logical_clock(to_iso8601) -> dict:
    resp = api_client.set_clock(set_clock_payload(to_iso8601), MGR)
    return get_success_data(resp)


def get_appointment(appointment_id) -> dict:
    return get_success_data(api_client.get_appointment(appointment_id, OP))


def get_customer(customer_id) -> dict:
    return get_success_data(api_client.get_customer(customer_id, OP))


def get_animal(animal_id) -> dict:
    return get_success_data(api_client.get_animal(animal_id, OP))


def get_share(share_id) -> dict:
    return get_success_data(api_client.get_share(share_id, OP))


def get_cut_sheet(cut_sheet_id) -> dict:
    return get_success_data(api_client.get_cut_sheet(cut_sheet_id, OP))


def get_invoice(invoice_id) -> dict:
    return get_success_data(api_client.get_invoice(invoice_id, OP))


def get_storage_record(record_id) -> dict:
    return get_success_data(api_client.get_storage_record(record_id, OP))


def get_label(label_id) -> dict:
    return get_success_data(api_client.get_label(label_id, OP))


def get_capacity_day_by_date(date) -> dict:
    data = get_success_data(
        api_client.list_capacity_days(OP, params={"date_from": date, "date_to": date})
    )
    matches = [d for d in data if d["date"] == date]
    assert len(matches) == 1, f"expected exactly one CapacityDay for {date}"
    return matches[0]


def list_appointment_animals(appointment_id) -> list:
    return get_success_data(api_client.list_appointment_animals(appointment_id, OP))


def get_share_invoice(share_id) -> dict:
    data = get_success_data(api_client.list_invoices(OP, params={"share_id": share_id}))
    assert len(data) == 1, f"expected exactly one invoice for share {share_id}"
    return data[0]


def get_share_storage_record(share_id) -> dict:
    data = get_success_data(
        api_client.list_storage_records(OP, params={"share_id": share_id})
    )
    assert len(data) == 1, f"expected exactly one storage record for share {share_id}"
    return data[0]


def get_share_label(share_id) -> dict:
    data = get_success_data(api_client.list_labels(OP, params={"share_id": share_id}))
    assert len(data) == 1, f"expected exactly one label record for share {share_id}"
    return data[0]


def get_share_cut_sheet(share_id) -> dict:
    data = get_success_data(api_client.list_cut_sheets(OP, params={"share_id": share_id}))
    assert len(data) == 1, f"expected exactly one cut sheet for share {share_id}"
    return data[0]


# ---------------------------------------------------------------------------
# Tier 2: booking flows
# ---------------------------------------------------------------------------

def book_appointment(customer_id, capacity_day_id, species="BEEF", head_count=1,
                     as_customer_id=None) -> dict:
    """Book as the customer themselves (default) or as a staff-specified caller.
    Returns the created appointment (PENDING_DEPOSIT)."""
    caller = as_customer_id or customer_id
    resp = api_client.create_appointment(
        create_appointment_payload(customer_id, capacity_day_id, species, head_count),
        make_customer_headers(caller),
    )
    return get_success_data(resp)


def pay_full_deposit(appointment_id, as_customer_id) -> dict:
    """Pay exactly the remaining deposit due; returns the CONFIRMED appointment."""
    appointment = get_appointment(appointment_id)
    remaining = appointment["deposit_amount_cents"] - appointment["deposit_paid_cents"]
    resp = api_client.pay_deposit(
        appointment_id, pay_deposit_payload(remaining), make_customer_headers(as_customer_id)
    )
    return get_success_data(resp)


def book_and_confirm(customer_id, capacity_day_id, species="BEEF", head_count=1) -> tuple:
    """Book + pay in full. Returns (confirmed appointment, animals list)."""
    appointment = book_appointment(customer_id, capacity_day_id, species, head_count)
    confirmed = pay_full_deposit(appointment["id"], customer_id)
    animals = list_appointment_animals(appointment["id"])
    assert len(animals) == head_count, (
        f"expected {head_count} EXPECTED animals after deposit payment"
    )
    return confirmed, animals


# ---------------------------------------------------------------------------
# Tier 3: animal lifecycle
# ---------------------------------------------------------------------------

def process_animal_to_hanging(animal_id, tag_id, live_weight_lbs,
                              hanging_weight_lbs) -> dict:
    """receive -> slaughter -> weigh. Returns the HANGING animal."""
    get_success_data(
        api_client.receive_animal(animal_id, receive_animal_payload(tag_id, live_weight_lbs), OP)
    )
    get_success_data(api_client.slaughter_animal(animal_id, OP))
    return get_success_data(
        api_client.weigh_animal(animal_id, weigh_animal_payload(hanging_weight_lbs), OP)
    )


def add_share(animal_id, owner_customer_id, share_fraction, intended_use="OWNER_USE",
              as_customer_id=None) -> dict:
    """Add a PENDING share. When the caller is a Customer it must be the booking
    customer (pass as_customer_id); staff may add shares via operator headers."""
    if as_customer_id is None:
        headers = OP
    else:
        headers = make_customer_headers(as_customer_id)
    resp = api_client.add_share(
        animal_id,
        add_share_payload(owner_customer_id, share_fraction, intended_use),
        headers,
    )
    return get_success_data(resp)


def finalize_split(animal_id) -> list:
    return get_success_data(api_client.finalize_shares(animal_id, OP))


def create_cut_sheet(share_id, owner_customer_id, grind_pct=30,
                     package_weight_lbs=2.0, **optional) -> dict:
    resp = api_client.create_cut_sheet(
        share_id,
        create_cut_sheet_payload(grind_pct, package_weight_lbs, **optional),
        make_customer_headers(owner_customer_id),
    )
    return get_success_data(resp)


def submit_cut_sheet(cut_sheet_id, owner_customer_id) -> dict:
    resp = api_client.submit_cut_sheet(cut_sheet_id, make_customer_headers(owner_customer_id))
    return get_success_data(resp)


def create_and_submit_cut_sheet(share_id, owner_customer_id, grind_pct=30,
                                package_weight_lbs=2.0, **optional) -> dict:
    sheet = create_cut_sheet(share_id, owner_customer_id, grind_pct,
                             package_weight_lbs, **optional)
    return submit_cut_sheet(sheet["id"], owner_customer_id)


def start_and_complete_fabrication(animal_id) -> dict:
    """HANGING -> CUTTING -> READY. Caller must have moved the logical clock
    past the minimum hang first. Returns the READY animal."""
    get_success_data(api_client.start_fabrication(animal_id, OP))
    return get_success_data(api_client.complete_fabrication(animal_id, OP))


# ---------------------------------------------------------------------------
# Tier 4: full scenario builders
# ---------------------------------------------------------------------------

def setup_hanging_animal(species="HOG", live_weight_lbs=280.0,
                         hanging_weight_lbs=200.0, day_date="2026-08-20",
                         capacity_head=1, head_count=1, tag_id="TAG-H1",
                         customer_name="Ann Orr", customer_email="ann@x.com",
                         customer_phone="555-0101") -> dict:
    """Customer + capacity day + confirmed appointment + one animal walked to
    HANGING. Runs entirely at the default clock. Returns a scenario dict."""
    customer = create_customer(customer_name, customer_phone, customer_email)
    day = create_capacity_day(day_date, capacity_head)
    appointment, animals = book_and_confirm(
        customer["id"], day["id"], species, head_count
    )
    animal = process_animal_to_hanging(
        animals[0]["id"], tag_id, live_weight_lbs, hanging_weight_lbs
    )
    return {
        "customer": customer,
        "day": day,
        "appointment": appointment,
        "animals": animals,
        "animal": animal,
    }


def setup_finalized_single_share(species="HOG", live_weight_lbs=280.0,
                                 hanging_weight_lbs=200.0,
                                 day_date="2026-08-20", tag_id="TAG-H1",
                                 intended_use="OWNER_USE",
                                 customer_name="Ann Orr",
                                 customer_email="ann@x.com",
                                 customer_phone="555-0101") -> dict:
    """Hanging animal + one 1.0 share + finalized split (invoice + label exist).
    Cut sheet NOT created. Clock untouched (default)."""
    scenario = setup_hanging_animal(
        species, live_weight_lbs, hanging_weight_lbs, day_date,
        1, 1, tag_id, customer_name, customer_email, customer_phone,
    )
    customer = scenario["customer"]
    share = add_share(
        scenario["animal"]["id"], customer["id"], 1.0, intended_use,
        as_customer_id=customer["id"],
    )
    finalize_split(scenario["animal"]["id"])
    scenario["share"] = get_share(share["id"])
    scenario["invoice"] = get_share_invoice(share["id"])
    scenario["label"] = get_share_label(share["id"])
    return scenario


def setup_ready_share(species="HOG", live_weight_lbs=280.0,
                      hanging_weight_lbs=200.0, day_date="2026-08-20",
                      tag_id="TAG-H1", intended_use="OWNER_USE",
                      fabrication_instant="2026-08-04T00:00:00Z") -> dict:
    """Full flow through complete-fabrication: one customer, one animal
    (weighed at the default clock), one 1.0 OWNER_USE share finalized, cut
    sheet submitted, clock advanced to fabrication_instant (>= weigh + 3
    days), fabrication started and completed. The share is READY with a STORED
    storage record whose ready_at is fabrication_instant. The logical clock
    remains at fabrication_instant on return."""
    scenario = setup_finalized_single_share(
        species, live_weight_lbs, hanging_weight_lbs, day_date, tag_id, intended_use,
    )
    customer = scenario["customer"]
    sheet = create_and_submit_cut_sheet(scenario["share"]["id"], customer["id"])
    set_logical_clock(fabrication_instant)
    animal = start_and_complete_fabrication(scenario["animal"]["id"])
    scenario["cut_sheet"] = sheet
    scenario["animal"] = animal
    scenario["share"] = get_share(scenario["share"]["id"])
    scenario["invoice"] = get_share_invoice(scenario["share"]["id"])
    scenario["storage_record"] = get_share_storage_record(scenario["share"]["id"])
    scenario["label"] = get_share_label(scenario["share"]["id"])
    return scenario


def earn_no_show_strike(customer_id, day_date, species="BEEF", head_count=1,
                        capacity_head=1) -> dict:
    """Give a customer one no-show strike: book a day >= 14 days out, pay the
    quoted deposit, advance the clock to the appointment date, staff-mark the
    no-show. The logical clock ends at day_dateT00:00:00Z, so callers must
    schedule any later activity on days at least 14 beyond that date.
    Returns the NO_SHOW appointment."""
    day = create_capacity_day(day_date, capacity_head)
    appointment, _ = book_and_confirm(customer_id, day["id"], species, head_count)
    set_logical_clock(f"{day_date}T00:00:00Z")
    resp = api_client.mark_no_show(appointment["id"], OP)
    return get_success_data(resp)


def setup_customer_with_collections(customer_name="Ann Orr",
                                    customer_email="ann@x.com",
                                    customer_phone="555-0101") -> dict:
    """Full abandoned-meat scenario: confirmed HOG appointment -> animal ->
    finalized 1.0 share -> submitted cut sheet -> fabrication completed with
    ready_at 2026-08-04 -> clock to 2026-08-26 (days_stored 22 > 21) ->
    run-daily sweep. The customer ends with one Invoice in COLLECTIONS and one
    strike (ELEVATED_DEPOSIT). Clock ends at 2026-08-26T00:00:00Z."""
    scenario = setup_ready_share(tag_id="TAG-AB1")
    set_logical_clock("2026-08-26T00:00:00Z")
    sweep = get_success_data(api_client.run_daily(OP))
    scenario["sweep"] = sweep
    scenario["share"] = get_share(scenario["share"]["id"])
    scenario["invoice"] = get_share_invoice(scenario["share"]["id"])
    scenario["storage_record"] = get_share_storage_record(scenario["share"]["id"])
    scenario["customer"] = get_customer(scenario["customer"]["id"])
    return scenario
