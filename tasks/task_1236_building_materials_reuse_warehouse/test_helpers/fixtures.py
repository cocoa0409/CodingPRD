"""Composite setup helpers (PRD §3 workflows).

Each helper drives a multi-step workflow through the public API and returns
the persisted resources. All helpers build their preconditions from scratch —
the server is restarted before every test, so nothing carries over.

Identity threading: entity-backed roles (Donor / Contractor / HazmatTechnician
/ CrewLead) always go through the make_*_headers builders with the real entity
id; opaque roles use the shared TEST_USERS constants or make_*_headers with an
arbitrary operator id (relevant for the receipt receiver/issuer segregation
check in §3.3).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .factories import (
    create_bulk_agreement_payload,
    create_category_payload,
    create_contractor_account_payload,
    create_crew_assignment_payload,
    create_crew_member_payload,
    create_deconstruction_job_payload,
    create_diversion_report_payload,
    create_donation_offer_payload,
    create_donor_payload,
    create_hazmat_screening_payload,
    create_item_payload,
    create_pickup_appointment_payload,
    create_salvage_batch_payload,
    create_store_zone_payload,
    create_vehicle_payload,
)
from .test_users import (
    TEST_USERS,
    make_hazmat_technician_headers,
    make_intake_staff_headers,
)

ADMIN = TEST_USERS["warehouse_admin_headers"]
MANAGER = TEST_USERS["store_manager_headers"]
INTAKE = TEST_USERS["intake_staff_headers"]
COORD = TEST_USERS["crew_coordinator_headers"]
CASHIER = TEST_USERS["cashier_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation helpers
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock (PRD §2.4)."""
    return get_success_data(api.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def create_category(**overrides) -> dict:
    return get_success_data(api.create_category(create_category_payload(**overrides), MANAGER))


def create_donor(**overrides) -> dict:
    return get_success_data(api.create_donor(create_donor_payload(**overrides), INTAKE))


def create_zone(**overrides) -> dict:
    return get_success_data(api.create_store_zone(create_store_zone_payload(**overrides), MANAGER))


def create_vehicle(**overrides) -> dict:
    return get_success_data(api.create_vehicle(create_vehicle_payload(**overrides), COORD))


def create_crew_member(**overrides) -> dict:
    return get_success_data(api.create_crew_member(create_crew_member_payload(**overrides), COORD))


def create_technician(**overrides) -> dict:
    """Hazmat-certified crew member (PRD §3.4 screening prerequisite)."""
    overrides.setdefault("hazmat_certified", True)
    overrides.setdefault("full_name", "Tech Cert")
    return create_crew_member(**overrides)


def create_lead_member(**overrides) -> dict:
    """Lead-certified crew member (PRD §3.4 scheduling prerequisite)."""
    overrides.setdefault("lead_certified", True)
    overrides.setdefault("hourly_rate_cents", 5000)
    overrides.setdefault("full_name", "Lead Cert")
    return create_crew_member(**overrides)


def create_report(period: str) -> dict:
    return get_success_data(api.create_diversion_report(create_diversion_report_payload(period), ADMIN))


def create_account(approve: bool = True, **overrides) -> dict:
    """Contractor account; approved to ACTIVE by default (PRD §3.9)."""
    account = get_success_data(
        api.create_contractor_account(create_contractor_account_payload(**overrides), ADMIN)
    )
    if approve:
        account = get_success_data(api.approve_account(account["id"], ADMIN))
    return account


# ---------------------------------------------------------------------------
# Tier 2: donation offer pipeline (PRD §3.2, §3.3)
# ---------------------------------------------------------------------------

def create_offer(donor_id: str, category_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_donation_offer(create_donation_offer_payload(donor_id, category_id, **overrides), INTAKE)
    )


def create_accepted_offer(donor_id: str, category_id: str, **overrides) -> dict:
    """Offer walked OFFERED -> UNDER_REVIEW -> ACCEPTED."""
    offer = create_offer(donor_id, category_id, **overrides)
    offer = get_success_data(api.review_offer(offer["id"], INTAKE))
    offer = get_success_data(api.accept_offer(offer["id"], INTAKE))
    return offer


def create_received_offer(donor_id: str, category_id: str,
                          receiver_id: str = "staff-recv-1", **overrides) -> dict:
    """Offer walked to RECEIVED; received_by_user_id records the receiver (§3.3)."""
    offer = create_accepted_offer(donor_id, category_id, **overrides)
    offer = get_success_data(api.receive_offer(offer["id"], make_intake_staff_headers(receiver_id)))
    return offer


def add_offer_item(offer_id: str, category_id: str, price_cents: int, **overrides) -> dict:
    """Item linked to a RECEIVED offer, then priced (override or engine)."""
    item = get_success_data(
        api.create_item(create_item_payload(category_id, offer_id=offer_id, **overrides), INTAKE)
    )
    payload = {} if price_cents is None else {"price_override_cents": price_cents}
    return get_success_data(api.price_item(item["id"], payload, MANAGER))


def draft_receipt(offer_id: str) -> dict:
    return get_success_data(api.create_tax_receipt({"offer_id": offer_id}, INTAKE))


def issue_receipt(receipt_id: str, issuer_id: str = "staff-issue-1",
                  appraisal_reference=None, appraisal_value_cents=None) -> dict:
    payload = {}
    if appraisal_reference is not None:
        payload["appraisal_reference"] = appraisal_reference
    if appraisal_value_cents is not None:
        payload["appraisal_value_cents"] = appraisal_value_cents
    return get_success_data(api.issue_receipt(receipt_id, payload, make_intake_staff_headers(issuer_id)))


def setup_offer_with_priced_items(item_prices, receiver_id: str = "staff-recv-1",
                                  category_overrides=None, offer_overrides=None):
    """Donor + category + RECEIVED offer + one priced item per entry of
    ``item_prices``. Returns dict with donor/category/offer/items.

    Offer defaults: DROPOFF, grade A, quantity == len(item_prices) UNIT.
    """
    category_overrides = category_overrides or {}
    offer_overrides = offer_overrides or {}
    category = create_category(**category_overrides)
    donor = create_donor()
    offer_overrides.setdefault("estimated_quantity", max(1, len(item_prices)))
    offer = create_received_offer(donor["id"], category["id"],
                                  receiver_id=receiver_id, **offer_overrides)
    items = [add_offer_item(offer["id"], category["id"], price) for price in item_prices]
    return {"category": category, "donor": donor, "offer": offer, "items": items}


def setup_issued_receipt(item_prices, receiver_id: str = "staff-recv-1",
                         issuer_id: str = "staff-issue-1",
                         appraisal_reference=None, appraisal_value_cents=None,
                         **kwargs):
    """Full §3.3 flow: RECEIVED offer with priced items + DRAFT receipt + ISSUED.
    Returns dict adding receipt to the setup_offer_with_priced_items result.
    """
    ctx = setup_offer_with_priced_items(item_prices, receiver_id=receiver_id, **kwargs)
    receipt = draft_receipt(ctx["offer"]["id"])
    receipt = issue_receipt(receipt["id"], issuer_id=issuer_id,
                            appraisal_reference=appraisal_reference,
                            appraisal_value_cents=appraisal_value_cents)
    ctx["receipt"] = receipt
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: items, zones, floor placement (PRD §3.7, §3.8)
# ---------------------------------------------------------------------------

def create_item(category_id: str, **overrides) -> dict:
    return get_success_data(api.create_item(create_item_payload(category_id, **overrides), INTAKE))


def price_item(item_id: str, price_override_cents=None) -> dict:
    payload = {} if price_override_cents is None else {"price_override_cents": price_override_cents}
    return get_success_data(api.price_item(item_id, payload, MANAGER))


def create_priced_item(category_id: str, price_cents, **overrides) -> dict:
    """Item in BACKROOM with pricing_status PRICED (override when price_cents given)."""
    item = create_item(category_id, **overrides)
    return price_item(item["id"], price_cents)


def create_placed_item(category_id: str, zone_id: str, price_cents, **overrides) -> dict:
    """PRICED item placed ON_FLOOR into the zone (PRD §3.8)."""
    item = create_priced_item(category_id, price_cents, **overrides)
    return get_success_data(api.place_item(item["id"], {"zone_id": zone_id}, MANAGER))


# ---------------------------------------------------------------------------
# Tier 3: deconstruction job lifecycle (PRD §3.4)
# ---------------------------------------------------------------------------

def create_job(**overrides) -> dict:
    return get_success_data(api.create_deconstruction_job(create_deconstruction_job_payload(**overrides), COORD))


def record_screening(job_id: str, tech_id: str,
                     lead_result: str = "NEGATIVE", asbestos_result: str = "NEGATIVE") -> dict:
    """Screening recorded by the technician as themselves (entity-backed role)."""
    return get_success_data(api.create_hazmat_screening(
        create_hazmat_screening_payload(job_id, lead_result=lead_result, asbestos_result=asbestos_result),
        make_hazmat_technician_headers(tech_id),
    ))


def create_cleared_job(tech_id: str = None, **job_overrides):
    """Job walked REQUESTED -> SCREENING_PENDING -> CLEARED.
    Returns (job, technician, clearing_screening)."""
    tech = create_technician() if tech_id is None else get_success_data(
        api.get_crew_member(tech_id, COORD))
    job = create_job(**job_overrides)
    get_success_data(api.request_screening(job["id"], COORD))
    screening = record_screening(job["id"], tech["id"])
    job = get_success_data(api.get_deconstruction_job(job["id"], COORD))
    return job, tech, screening


def schedule_job(job_id: str, lead_id: str, vehicle_id: str,
                 start: str, end: str) -> dict:
    return get_success_data(api.schedule_job(
        job_id,
        {"lead_crew_member_id": lead_id, "vehicle_id": vehicle_id,
         "scheduled_start": start, "scheduled_end": end},
        COORD,
    ))


def create_scheduled_job(lead_id: str = None, vehicle_id: str = None,
                         start: str = "2026-06-10T08:00:00Z",
                         end: str = "2026-06-10T16:00:00Z", **job_overrides):
    """Job CLEARED then SCHEDULED with lead + vehicle + window.
    Returns dict: job, tech, lead, vehicle, screening."""
    job, tech, screening = create_cleared_job(**job_overrides)
    lead = create_lead_member() if lead_id is None else get_success_data(
        api.get_crew_member(lead_id, COORD))
    vehicle = create_vehicle() if vehicle_id is None else get_success_data(
        api.get_vehicle(vehicle_id, COORD))
    job = schedule_job(job["id"], lead["id"], vehicle["id"], start, end)
    return {"job": job, "tech": tech, "lead": lead, "vehicle": vehicle, "screening": screening}


def add_assignment(job_id: str, crew_member_id: str, start_at: str, end_at: str,
                   role_on_job: str = "WORKER") -> dict:
    return get_success_data(api.create_crew_assignment(
        create_crew_assignment_payload(job_id, crew_member_id, start_at, end_at,
                                       role_on_job=role_on_job),
        COORD,
    ))


def create_in_progress_job(start: str = "2026-06-10T08:00:00Z",
                           end: str = "2026-06-10T16:00:00Z",
                           lead_as_assignment: bool = True, **job_overrides):
    """Job walked to IN_PROGRESS: cleared, scheduled, one ASSIGNED assignment,
    started (PRD §3.4 start gate ERR_NO_CREW_ASSIGNED).
    Returns dict: job, tech, lead, vehicle, screening, assignment."""
    ctx = create_scheduled_job(start=start, end=end, **job_overrides)
    assignee = ctx["lead"] if lead_as_assignment else create_crew_member()
    assignment = add_assignment(
        ctx["job"]["id"], assignee["id"], start,
        # A half-day assignment sits inside the scheduled window.
        _midpoint(start, end),
        role_on_job="LEAD" if lead_as_assignment else "WORKER",
    )
    ctx["assignment"] = assignment
    ctx["job"] = get_success_data(api.start_job(ctx["job"]["id"], COORD))
    return ctx


def _midpoint(start: str, end: str) -> str:
    """Half-way instant between two ISO hour-aligned timestamps (same day)."""
    date_part = start[:10]
    start_hour = int(start[11:13])
    end_hour = int(end[11:13])
    mid_hour = (start_hour + end_hour) // 2
    return f"{date_part}T{mid_hour:02d}:00:00Z"


def create_manifested_batch(job_id: str, category_id: str, **overrides) -> dict:
    return get_success_data(api.create_salvage_batch(
        create_salvage_batch_payload(job_id, category_id, **overrides), COORD))


def setup_job_with_weighed_batch(scale_weight_lbs: float = 480,
                                 contamination_weight_lbs: float = 30,
                                 estimated_weight_lbs: float = 500,
                                 start: str = "2026-06-10T08:00:00Z",
                                 end: str = "2026-06-10T16:00:00Z",
                                 **category_overrides):
    """IN_PROGRESS job with one batch already WEIGHED. Returns ctx with
    job/batch/category plus the job readback after the weigh."""
    ctx = create_in_progress_job(start=start, end=end)
    category = create_category(**category_overrides)
    batch = create_manifested_batch(ctx["job"]["id"], category["id"],
                                    estimated_weight_lbs=estimated_weight_lbs)
    batch = get_success_data(api.weigh_batch(
        batch["id"],
        {"scale_weight_lbs": scale_weight_lbs, "contamination_weight_lbs": contamination_weight_lbs},
        COORD,
    ))
    ctx.update({"category": category, "batch": batch})
    ctx["job"] = get_success_data(api.get_deconstruction_job(ctx["job"]["id"], COORD))
    return ctx


# ---------------------------------------------------------------------------
# Tier 3/4: sales, accounts, agreements (PRD §3.9)
# ---------------------------------------------------------------------------

def get_account(account_id: str) -> dict:
    return get_success_data(api.get_contractor_account(account_id, ADMIN))


def create_agreement(account_id: str, category_id: str, **overrides) -> dict:
    """OCC-guarded create: reads the account's current version first (PRD §2.7)."""
    account = get_account(account_id)
    payload = create_bulk_agreement_payload(
        account_id, category_id, expected_account_version=account["version"], **overrides)
    return get_success_data(api.create_bulk_agreement(payload, ADMIN))


def create_sale(sale_channel: str = "WALK_IN", contractor_id=None, agreement_id=None,
                as_role: str = "Cashier", as_user_id: str = None) -> dict:
    payload = {"sale_channel": sale_channel}
    if contractor_id is not None:
        payload["contractor_id"] = contractor_id
    if agreement_id is not None:
        payload["agreement_id"] = agreement_id
    if as_role == "Contractor":
        from .test_users import make_contractor_headers
        headers = make_contractor_headers(as_user_id or contractor_id)
    else:
        headers = TEST_USERS[f"{as_role.lower()}_headers"] if as_role != "Cashier" else CASHIER
    return get_success_data(api.create_sale(payload, headers))


def add_line(sale_id: str, item_id: str, quantity=None, headers=None) -> dict:
    payload = {"item_id": item_id}
    if quantity is not None:
        payload["quantity"] = quantity
    return get_success_data(api.add_sale_line(sale_id, payload, headers or CASHIER))


def finalize_sale(sale_id: str, payment_amount_cents=None, headers=None) -> dict:
    payload = {}
    if payment_amount_cents is not None:
        payload["payment_amount_cents"] = payment_amount_cents
    return get_success_data(api.finalize_sale(sale_id, payload, headers or CASHIER))


def setup_contractor_sale_with_line(price_cents: int = 50000, credit_limit_cents: int = 100000000,
                                    with_agreement: bool = False, category_overrides=None):
    """ACTIVE account + PRICED ON_FLOOR item + OPEN contractor sale with one
    line (item RESERVED). Returns dict with account/category/zone/item/sale/line."""
    category = create_category(**(category_overrides or {}))
    account = create_account(credit_limit_cents=credit_limit_cents)
    agreement = None
    if with_agreement:
        agreement = create_agreement(account["id"], category["id"])
    zone = create_zone()
    item = create_placed_item(category["id"], zone["id"], price_cents)
    sale = create_sale("CONTRACTOR_ACCOUNT", contractor_id=account["id"],
                       agreement_id=agreement["id"] if agreement else None)
    line = add_line(sale["id"], item["id"])
    return {"account": account, "category": category, "zone": zone,
            "item": item, "sale": sale, "line": line, "agreement": agreement}


def setup_walk_in_sale_with_line(price_cents: int = 5000, category_overrides=None):
    """PRICED ON_FLOOR item + OPEN walk-in sale with one line."""
    category = create_category(**(category_overrides or {}))
    zone = create_zone()
    item = create_placed_item(category["id"], zone["id"], price_cents)
    sale = create_sale("WALK_IN")
    line = add_line(sale["id"], item["id"])
    return {"category": category, "zone": zone, "item": item, "sale": sale, "line": line}


def push_trailing_volume(account_id: str, category_id: str, zone_id: str, prices):
    """Finalize one contractor sale per price entry so the account's trailing
    volume grows by each sale's total (PRD §3.9). Returns list of sales."""
    sales = []
    for price in prices:
        item = create_placed_item(category_id, zone_id, price)
        sale = create_sale("CONTRACTOR_ACCOUNT", contractor_id=account_id)
        add_line(sale["id"], item["id"])
        sales.append(finalize_sale(sale["id"]))
    return sales


# ---------------------------------------------------------------------------
# Tier 2: pickup logistics (PRD §3.5)
# ---------------------------------------------------------------------------

def book_appointment(subject_type: str, subject_id: str, vehicle_id: str,
                     window_start: str, window_end: str, as_intake: bool = True) -> dict:
    return get_success_data(api.create_pickup_appointment(
        create_pickup_appointment_payload(subject_type, subject_id, vehicle_id,
                                          window_start, window_end),
        INTAKE if as_intake else COORD,
    ))


def setup_accepted_pickup_offer(donor_id: str = None, category_id: str = None, **overrides):
    """ACCEPTED offer of source_type PICKUP (bookable subject, §3.5)."""
    category = create_category() if category_id is None else get_success_data(
        api.get_category(category_id, MANAGER))
    donor = create_donor() if donor_id is None else get_success_data(
        api.get_donor(donor_id, INTAKE))
    overrides.setdefault("source_type", "PICKUP")
    offer = create_accepted_offer(donor["id"], category["id"], **overrides)
    return {"category": category, "donor": donor, "offer": offer}
