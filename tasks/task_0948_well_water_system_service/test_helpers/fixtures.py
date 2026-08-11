"""Composite setup helpers.

Three shapes in this domain are easy to get wrong when hand-rolled, so they
live here once:

1.  **Cascade-created children are never returned by the call that creates
    them.**  A ``WarrantyCoverage``, the confirmatory child ``WaterTest``, an
    ``Invoice`` and a ``MaintenanceVisit`` all appear only as side effects of
    some other request.  Their ids come from a filtered or sub-resource list
    read; :func:`invoices_of`, :func:`coverage_of`, :func:`visits_of_plan` and
    :func:`child_water_tests` are the only way to reach them.

2.  **Adding a quote line returns the line, not the parent.**  Any chain that
    adds a second line must re-read the quote to learn the version the next
    add has to quote.  :func:`add_quote_line` does the read for you and hands
    back the refreshed parent.  A salt delivery against a maintenance plan has
    the same shape; :func:`deliver_salt` re-reads the plan first.

3.  **Identity is per resource.**  A ``Technician`` presents its own row id and
    a ``CustomerContact`` presents its own account id, so every ownership-gated
    call in here threads the real id through ``make_technician_headers`` /
    ``make_customer_headers``.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    OFFICER_ALPHA,
    TEST_USERS,
    make_customer_headers,
    make_technician_headers,
    make_compliance_officer_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
ESTIMATOR = TEST_USERS["estimator_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]


def _ok(response):
    """Lenient success extraction for setup calls."""
    return get_success_data(response)


# --- Logical clock -----------------------------------------------------------


def set_clock(to_iso8601: str) -> dict:
    return _ok(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def read_clock() -> dict:
    return _ok(api_client.get_clock(ADMIN))


# --- Register ----------------------------------------------------------------


def new_account(
    legal_name: str = "Test Account",
    billing_jurisdiction_code: str = "JUR_ALPHA",
    contact_email: str = "ap@test.example",
    membership_tier=None,
) -> dict:
    payload = {
        "legal_name": legal_name,
        "billing_jurisdiction_code": billing_jurisdiction_code,
        "contact_email": contact_email,
    }
    if membership_tier is not None:
        payload["membership_tier"] = membership_tier
    return _ok(api_client.create_account(payload, ADMIN))


def new_property(
    account_id: str,
    address_line: str = "1 Test Way",
    jurisdiction_code: str = "JUR_ALPHA",
    distance_miles: float = 10.0,
    household_size: int = 3,
    has_vulnerable_occupant=None,
) -> dict:
    payload = {
        "account_id": account_id,
        "address_line": address_line,
        "jurisdiction_code": jurisdiction_code,
        "distance_miles": distance_miles,
        "household_size": household_size,
    }
    if has_vulnerable_occupant is not None:
        payload["has_vulnerable_occupant"] = has_vulnerable_occupant
    return _ok(api_client.create_property(payload, ADMIN))


def new_well(
    property_id: str,
    jurisdiction_code: str = "JUR_ALPHA",
    well_type: str = "DRILLED",
    depth_feet: float = 200.0,
    pressure_tank_drawdown_gallons=None,
) -> dict:
    payload = {
        "property_id": property_id,
        "jurisdiction_code": jurisdiction_code,
        "well_type": well_type,
        "depth_feet": depth_feet,
    }
    if pressure_tank_drawdown_gallons is not None:
        payload["pressure_tank_drawdown_gallons"] = pressure_tank_drawdown_gallons
    return _ok(api_client.create_well_profile(payload, ADMIN))


def new_technician(
    full_name: str = "Test Technician",
    tier: str = "JOURNEYMAN",
    home_jurisdiction_code: str = "JUR_ALPHA",
    status: str = "AVAILABLE",
) -> dict:
    return _ok(
        api_client.create_technician(
            {
                "full_name": full_name,
                "tier": tier,
                "home_jurisdiction_code": home_jurisdiction_code,
                "status": status,
            },
            ADMIN,
        )
    )


def new_part(
    part_number: str,
    category: str = "CONTROL",
    unit_cost_cents: int = 5000,
    on_hand_qty: int = 10,
    status: str = "ACTIVE",
    media_kind: str = "NONE",
    **extra,
) -> dict:
    payload = {
        "part_number": part_number,
        "category": category,
        "unit_cost_cents": unit_cost_cents,
        "media_kind": media_kind,
        "on_hand_qty": on_hand_qty,
        "status": status,
    }
    payload.update(extra)
    return _ok(api_client.create_part_catalog_item(payload, ADMIN))


def new_shared_well_agreement(well_profile_id: str, account_id: str, split_pct: float):
    return _ok(
        api_client.create_shared_well_agreement(
            {
                "well_profile_id": well_profile_id,
                "account_id": account_id,
                "split_pct": split_pct,
            },
            BILLING,
        )
    )


def new_maintenance_plan(well_profile_id: str, account_id: str) -> dict:
    return _ok(
        api_client.create_maintenance_plan(
            {"well_profile_id": well_profile_id, "account_id": account_id}, ADMIN
        )
    )


def base_world(
    account_name: str = "Test Account",
    email: str = "ap@test.example",
    membership_tier=None,
    account_jurisdiction: str = "JUR_ALPHA",
    property_jurisdiction: str = "JUR_ALPHA",
    well_jurisdiction: str = "JUR_ALPHA",
    distance_miles: float = 10.0,
    household_size: int = 3,
    has_vulnerable_occupant=None,
    drawdown=None,
    depth_feet: float = 200.0,
    technician_tier: str = "JOURNEYMAN",
    technician_name: str = "Test Technician",
    address_line: str = "1 Test Way",
) -> dict:
    """Account + property + well + one technician: the preamble of most chains."""
    account = new_account(account_name, account_jurisdiction, email, membership_tier)
    prop = new_property(
        account["id"],
        address_line,
        property_jurisdiction,
        distance_miles,
        household_size,
        has_vulnerable_occupant,
    )
    well = new_well(prop["id"], well_jurisdiction, "DRILLED", depth_feet, drawdown)
    technician = new_technician(
        technician_name, technician_tier, well_jurisdiction, "AVAILABLE"
    )
    return {
        "account": account,
        "account_id": account["id"],
        "property": prop,
        "property_id": prop["id"],
        "well": well,
        "well_id": well["id"],
        "technician": technician,
        "technician_id": technician["id"],
        "customer_headers": make_customer_headers(account["id"]),
        "technician_headers": make_technician_headers(technician["id"]),
    }


# --- Inspections -------------------------------------------------------------


def schedule_inspection(
    well_profile_id: str, technician_id: str, scheduled_for: str
) -> dict:
    return _ok(
        api_client.create_inspection(
            {
                "well_profile_id": well_profile_id,
                "technician_id": technician_id,
                "scheduled_for": scheduled_for,
            },
            DISPATCHER,
        )
    )


def start_inspection(inspection_id: str, technician_id: str) -> dict:
    return _ok(
        api_client.start_inspection(
            inspection_id, make_technician_headers(technician_id)
        )
    )


def started_inspection(
    well_profile_id: str, technician_id: str, scheduled_for: str
) -> dict:
    inspection = schedule_inspection(well_profile_id, technician_id, scheduled_for)
    start_inspection(inspection["id"], technician_id)
    return inspection


def completed_inspection(
    well_profile_id: str,
    technician_id: str,
    scheduled_for: str = "2026-06-01T10:00:00Z",
    measured_yield_gpm: float = 20.0,
    static_level_feet: float = 50.0,
    observed_drawdown_gallons: float = 6.0,
) -> dict:
    """Schedule, start and complete an inspection as its assigned technician."""
    tech_headers = make_technician_headers(technician_id)
    inspection = schedule_inspection(well_profile_id, technician_id, scheduled_for)
    _ok(api_client.start_inspection(inspection["id"], tech_headers))
    return _ok(
        api_client.complete_inspection(
            inspection["id"],
            {
                "measured_yield_gpm": measured_yield_gpm,
                "static_level_feet": static_level_feet,
                "observed_drawdown_gallons": observed_drawdown_gallons,
            },
            tech_headers,
        )
    )


# --- Water quality -----------------------------------------------------------


def collect_sample(
    well_profile_id: str,
    technician_id: str,
    panel_type: str,
    sample_datetime: str,
    headers=None,
) -> dict:
    return _ok(
        api_client.create_water_test(
            {
                "well_profile_id": well_profile_id,
                "collected_by_technician_id": technician_id,
                "panel_type": panel_type,
                "sample_datetime": sample_datetime,
            },
            headers or make_technician_headers(technician_id),
        )
    )


def record_lab_result(water_test_id: str, payload: dict, officer_id: str = OFFICER_ALPHA):
    return _ok(
        api_client.record_lab_result(
            water_test_id, payload, make_compliance_officer_headers(officer_id)
        )
    )


def chemical_panel(
    well_profile_id: str,
    technician_id: str,
    sample_datetime: str,
    analyzed_at: str,
    officer_id: str = OFFICER_ALPHA,
    **analytes,
) -> dict:
    """A CHEMICAL sample analysed inside its 336-hour hold time."""
    test = collect_sample(well_profile_id, technician_id, "CHEMICAL", sample_datetime)
    payload = {"analyzed_at": analyzed_at}
    payload.update(analytes)
    record_lab_result(test["id"], payload, officer_id)
    return test


def presumptive_positive_panel(
    well_profile_id: str,
    technician_id: str,
    sample_datetime: str,
    analyzed_at: str,
    officer_id: str = OFFICER_ALPHA,
) -> dict:
    """A BACTERIOLOGICAL sample reporting coliform present inside its hold time."""
    test = collect_sample(
        well_profile_id, technician_id, "BACTERIOLOGICAL", sample_datetime
    )
    record_lab_result(
        test["id"], {"analyzed_at": analyzed_at, "coliform_present": True}, officer_id
    )
    return test


def child_water_tests(parent_test_id: str) -> list:
    """The confirmatory child row is discoverable only through this filter."""
    response = api_client.list_water_tests(OFFICER, params={"parent_test_id": parent_test_id})
    return _ok(response)


def well_version(well_profile_id: str) -> int:
    return _ok(api_client.get_well_profile(well_profile_id, ADMIN))["version"]


def create_recommendation(
    well_profile_id: str, water_test_id: str, officer_id: str = OFFICER_ALPHA
) -> dict:
    """Read the well's current version, then found the recommendation on it."""
    version = well_version(well_profile_id)
    return _ok(
        api_client.create_treatment_recommendation(
            well_profile_id,
            {
                "water_test_id": water_test_id,
                "expected_well_profile_version": version,
            },
            make_compliance_officer_headers(officer_id),
        )
    )


def accept_recommendation(recommendation_id: str, account_id: str) -> dict:
    return _ok(
        api_client.accept_treatment_recommendation(
            recommendation_id, make_customer_headers(account_id)
        )
    )


# --- Quotes ------------------------------------------------------------------


def new_quote(
    property_id: str,
    well_profile_id: str,
    inspection_id: str,
    scope: str = "REPAIR",
    estimated_labor_minutes: int = 60,
    estimated_start_at: str = "2026-06-03T09:00:00Z",
    quoted_technician_tier: str = "JOURNEYMAN",
) -> dict:
    return _ok(
        api_client.create_quote(
            {
                "property_id": property_id,
                "well_profile_id": well_profile_id,
                "inspection_id": inspection_id,
                "scope": scope,
                "estimated_labor_minutes": estimated_labor_minutes,
                "estimated_start_at": estimated_start_at,
                "quoted_technician_tier": quoted_technician_tier,
            },
            ESTIMATOR,
        )
    )


def quote_version(quote_id: str) -> int:
    return _ok(api_client.get_quote(quote_id, ESTIMATOR))["version"]


def add_quote_line(quote_id: str, part_catalog_item_id: str, quantity: int) -> dict:
    """Add one line and hand back both the line and the refreshed parent quote.

    The add returns a ``QuoteLine``, never the parent, so a caller adding a
    second line needs the quote re-read to know which version to quote next.
    """
    version = quote_version(quote_id)
    line = _ok(
        api_client.add_quote_line(
            quote_id,
            {
                "part_catalog_item_id": part_catalog_item_id,
                "quantity": quantity,
                "expected_quote_version": version,
            },
            ESTIMATOR,
        )
    )
    return {"line": line, "line_id": line["id"], "quote": _ok(api_client.get_quote(quote_id, ESTIMATOR))}


def price_quote(quote_id: str) -> dict:
    return _ok(api_client.price_quote(quote_id, ESTIMATOR))


def send_quote(quote_id: str) -> dict:
    return _ok(api_client.send_quote(quote_id, ESTIMATOR))


def approve_quote(quote_id: str, account_id: str) -> dict:
    return _ok(api_client.approve_quote(quote_id, make_customer_headers(account_id)))


def priced_and_sent_quote(
    property_id: str,
    well_profile_id: str,
    inspection_id: str,
    part_catalog_item_id: str,
    quantity: int = 1,
    scope: str = "REPAIR",
    estimated_labor_minutes: int = 60,
    estimated_start_at: str = "2026-06-03T09:00:00Z",
    quoted_technician_tier: str = "JOURNEYMAN",
) -> dict:
    quote = new_quote(
        property_id,
        well_profile_id,
        inspection_id,
        scope,
        estimated_labor_minutes,
        estimated_start_at,
        quoted_technician_tier,
    )
    added = add_quote_line(quote["id"], part_catalog_item_id, quantity)
    price_quote(quote["id"])
    sent = send_quote(quote["id"])
    return {"quote": sent, "quote_id": quote["id"], "line_id": added["line_id"]}


# --- Permits -----------------------------------------------------------------


def new_permit(
    well_profile_id: str,
    jurisdiction_code: str,
    scope: str,
    quote_id=None,
    work_order_id=None,
    expedited: bool = False,
    post_hoc: bool = False,
    officer_id: str = OFFICER_ALPHA,
) -> dict:
    payload = {
        "well_profile_id": well_profile_id,
        "jurisdiction_code": jurisdiction_code,
        "scope": scope,
        "expedited": expedited,
        "post_hoc": post_hoc,
    }
    if quote_id is not None:
        payload["quote_id"] = quote_id
    if work_order_id is not None:
        payload["work_order_id"] = work_order_id
    return _ok(
        api_client.create_permit(payload, make_compliance_officer_headers(officer_id))
    )


def file_permit(permit_id: str, officer_id: str = OFFICER_ALPHA) -> dict:
    return _ok(
        api_client.file_permit(permit_id, make_compliance_officer_headers(officer_id))
    )


def approve_permit(permit_id: str, payload=None, officer_id: str = OFFICER_ALPHA) -> dict:
    return _ok(
        api_client.approve_permit(
            permit_id, payload or {}, make_compliance_officer_headers(officer_id)
        )
    )


# --- Emergency pipeline -------------------------------------------------------


def new_emergency_ticket(
    property_id: str,
    well_profile_id: str,
    account_id: str,
    reported_outage_hours: float = 2.0,
) -> dict:
    return _ok(
        api_client.create_emergency_ticket(
            {
                "property_id": property_id,
                "well_profile_id": well_profile_id,
                "account_id": account_id,
                "reported_outage_hours": reported_outage_hours,
            },
            DISPATCHER,
        )
    )


def ticket_on_site(
    property_id: str,
    well_profile_id: str,
    account_id: str,
    technician_id: str,
    reported_outage_hours: float = 2.0,
) -> dict:
    """Intake, triage, dispatch and arrival, leaving the ticket at ON_SITE."""
    ticket = new_emergency_ticket(
        property_id, well_profile_id, account_id, reported_outage_hours
    )
    _ok(api_client.triage_ticket(ticket["id"], DISPATCHER))
    _ok(api_client.dispatch_ticket(ticket["id"], {"technician_id": technician_id}, DISPATCHER))
    return _ok(
        api_client.arrive_ticket(ticket["id"], make_technician_headers(technician_id))
    )


def diagnose_ticket(
    ticket_id: str, technician_id: str, cause_class: str, onsite_estimate_cents: int
) -> dict:
    return _ok(
        api_client.diagnose_ticket(
            ticket_id,
            {
                "cause_class": cause_class,
                "onsite_estimate_cents": onsite_estimate_cents,
            },
            make_technician_headers(technician_id),
        )
    )


def diagnosed_ticket(
    property_id: str,
    well_profile_id: str,
    account_id: str,
    technician_id: str,
    cause_class: str = "CONTROL_FAILURE",
    onsite_estimate_cents: int = 20000,
    reported_outage_hours: float = 2.0,
) -> dict:
    ticket = ticket_on_site(
        property_id, well_profile_id, account_id, technician_id, reported_outage_hours
    )
    return diagnose_ticket(
        ticket["id"], technician_id, cause_class, onsite_estimate_cents
    )


def authorize_ticket(ticket_id: str, account_id: str) -> dict:
    return _ok(
        api_client.authorize_ticket(ticket_id, make_customer_headers(account_id))
    )


# --- Work orders --------------------------------------------------------------


def new_work_order(
    property_id: str,
    well_profile_id: str,
    assigned_technician_id: str,
    scope: str = "REPAIR",
    quote_id=None,
    emergency_ticket_id=None,
) -> dict:
    payload = {
        "property_id": property_id,
        "well_profile_id": well_profile_id,
        "assigned_technician_id": assigned_technician_id,
        "scope": scope,
    }
    if quote_id is not None:
        payload["quote_id"] = quote_id
    if emergency_ticket_id is not None:
        payload["emergency_ticket_id"] = emergency_ticket_id
    return _ok(api_client.create_work_order(payload, DISPATCHER))


def schedule_work_order(
    work_order_id: str, scheduled_start_at: str, scheduled_end_at: str
) -> dict:
    return _ok(
        api_client.schedule_work_order(
            work_order_id,
            {
                "scheduled_start_at": scheduled_start_at,
                "scheduled_end_at": scheduled_end_at,
            },
            DISPATCHER,
        )
    )


def start_work_order(work_order_id: str, technician_id: str) -> dict:
    return _ok(
        api_client.start_work_order(
            work_order_id, make_technician_headers(technician_id)
        )
    )


def post_parts(
    work_order_id: str, technician_id: str, part_catalog_item_id: str, quantity: int
) -> dict:
    return _ok(
        api_client.post_parts_consumption(
            work_order_id,
            {"part_catalog_item_id": part_catalog_item_id, "quantity": quantity},
            make_technician_headers(technician_id),
        )
    )


def complete_work_order(
    work_order_id: str, technician_id: str, actual_labor_minutes: int
) -> dict:
    return _ok(
        api_client.complete_work_order(
            work_order_id,
            {"actual_labor_minutes": actual_labor_minutes},
            make_technician_headers(technician_id),
        )
    )


def emergency_work_order_in_progress(
    world: dict,
    cause_class: str = "CONTROL_FAILURE",
    onsite_estimate_cents: int = 20000,
    reported_outage_hours: float = 2.0,
    scope: str = "REPAIR",
    scheduled_start_at: str = "2026-06-01T12:00:00Z",
    scheduled_end_at: str = "2026-06-01T14:00:00Z",
    start_clock_at: str = "2026-06-01T12:00:00Z",
) -> dict:
    """Diagnosed ticket, work order created, scheduled and started."""
    ticket = diagnosed_ticket(
        world["property_id"],
        world["well_id"],
        world["account_id"],
        world["technician_id"],
        cause_class,
        onsite_estimate_cents,
        reported_outage_hours,
    )
    work_order = new_work_order(
        world["property_id"],
        world["well_id"],
        world["technician_id"],
        scope,
        emergency_ticket_id=ticket["id"],
    )
    schedule_work_order(work_order["id"], scheduled_start_at, scheduled_end_at)
    if start_clock_at:
        set_clock(start_clock_at)
    started = start_work_order(work_order["id"], world["technician_id"])
    return {
        "ticket": ticket,
        "ticket_id": ticket["id"],
        "work_order": started,
        "work_order_id": work_order["id"],
    }


def completed_emergency_work_order(
    world: dict,
    part_id=None,
    quantity: int = 1,
    actual_labor_minutes: int = 60,
    cause_class: str = "CONTROL_FAILURE",
    onsite_estimate_cents: int = 20000,
    reported_outage_hours: float = 2.0,
    scope: str = "REPAIR",
    scheduled_start_at: str = "2026-06-01T12:00:00Z",
    scheduled_end_at: str = "2026-06-01T14:00:00Z",
    start_clock_at: str = "2026-06-01T12:00:00Z",
) -> dict:
    """The whole emergency chain through to COMPLETED / PENDING_INVOICE."""
    stage = emergency_work_order_in_progress(
        world,
        cause_class,
        onsite_estimate_cents,
        reported_outage_hours,
        scope,
        scheduled_start_at,
        scheduled_end_at,
        start_clock_at,
    )
    entry = None
    if part_id is not None:
        entry = post_parts(
            stage["work_order_id"], world["technician_id"], part_id, quantity
        )
    completed = complete_work_order(
        stage["work_order_id"], world["technician_id"], actual_labor_minutes
    )
    stage["work_order"] = completed
    stage["consumption_entry"] = entry
    return stage


# --- Cascade-created children -------------------------------------------------


def invoices_of(work_order_id: str) -> list:
    return _ok(api_client.list_work_order_invoices(work_order_id, BILLING))


def first_invoice_of(work_order_id: str) -> dict:
    rows = invoices_of(work_order_id)
    assert rows, f"Work order {work_order_id} produced no invoice"
    return rows[0]


def coverages_of(work_order_id: str) -> list:
    return _ok(api_client.list_work_order_warranty_coverages(work_order_id, DISPATCHER))


def coverage_of(work_order_id: str, coverage_class: str) -> dict:
    rows = _ok(
        api_client.list_warranty_coverages(
            DISPATCHER,
            params={"work_order_id": work_order_id, "coverage_class": coverage_class},
        )
    )
    assert rows, f"No {coverage_class} coverage on work order {work_order_id}"
    return rows[0]


def visits_of_plan(maintenance_plan_id: str) -> list:
    return _ok(api_client.list_plan_visits(maintenance_plan_id, DISPATCHER))


def visits_of_work_order(work_order_id: str) -> list:
    return _ok(api_client.list_work_order_maintenance_visits(work_order_id, DISPATCHER))


def invoice_lines_of(invoice_id: str) -> list:
    return _ok(api_client.list_invoice_lines_of(invoice_id, BILLING))


# --- Callbacks ----------------------------------------------------------------


def raise_callback_claim(
    work_order_id: str,
    account_id: str,
    warranty_coverage_id: str,
    complaint_class: str,
    description: str,
) -> dict:
    return _ok(
        api_client.create_callback_claim(
            work_order_id,
            {
                "warranty_coverage_id": warranty_coverage_id,
                "complaint_class": complaint_class,
                "description": description,
            },
            make_customer_headers(account_id),
        )
    )


def adjudicate(claim_id: str, technician_id: str, decision: str) -> dict:
    return _ok(
        api_client.adjudicate_callback_claim(
            claim_id, {"decision": decision}, make_technician_headers(technician_id)
        )
    )


def approved_callback_claim(
    work_order_id: str,
    account_id: str,
    warranty_coverage_id: str,
    adjudicating_technician_id: str,
    complaint_class: str = "PART",
    description: str = "Same fault returned",
) -> dict:
    claim = raise_callback_claim(
        work_order_id, account_id, warranty_coverage_id, complaint_class, description
    )
    adjudicate(claim["id"], adjudicating_technician_id, "REVIEW")
    return adjudicate(claim["id"], adjudicating_technician_id, "APPROVE")


def remedy_work_order(
    claim_id: str, assigned_technician_id: str, scope: str = "REPAIR"
) -> dict:
    return _ok(
        api_client.create_remedy_work_order(
            claim_id,
            {"assigned_technician_id": assigned_technician_id, "scope": scope},
            DISPATCHER,
        )
    )


# --- Money --------------------------------------------------------------------


def issue_invoice(invoice_id: str) -> dict:
    return _ok(api_client.issue_invoice(invoice_id, BILLING))


def pay_invoice(invoice_id: str, amount_cents: int, expected_invoice_version: int):
    return _ok(
        api_client.record_payment(
            invoice_id,
            {
                "amount_cents": amount_cents,
                "expected_invoice_version": expected_invoice_version,
            },
            BILLING,
        )
    )


# --- Maintenance plans ---------------------------------------------------------


def plan_version(maintenance_plan_id: str) -> int:
    return _ok(api_client.get_maintenance_plan(maintenance_plan_id, ADMIN))["version"]


def deliver_salt(maintenance_plan_id: str, delivered_lbs: float, headers=None) -> dict:
    """Re-read the plan for its current version, then record the delivery.

    A salt delivery returns the plan, but the version a caller holds from an
    earlier read is spent as soon as any other write touches the plan, so the
    read belongs here rather than in each test.
    """
    version = plan_version(maintenance_plan_id)
    return _ok(
        api_client.record_salt_delivery(
            maintenance_plan_id,
            {
                "delivered_lbs": delivered_lbs,
                "expected_maintenance_plan_version": version,
            },
            headers or DISPATCHER,
        )
    )


def change_filter(maintenance_plan_id: str, headers=None) -> dict:
    return _ok(api_client.record_filter_change(maintenance_plan_id, headers or DISPATCHER))


def evaluate_compliance(maintenance_plan_id: str) -> dict:
    return _ok(api_client.evaluate_plan_compliance(maintenance_plan_id, ADMIN))


# --- Read-back shortcuts -------------------------------------------------------


def get_account(account_id: str) -> dict:
    return _ok(api_client.get_account(account_id, ADMIN))


def get_property(property_id: str) -> dict:
    return _ok(api_client.get_property(property_id, ADMIN))


def get_well(well_profile_id: str) -> dict:
    return _ok(api_client.get_well_profile(well_profile_id, ADMIN))


def get_technician(technician_id: str) -> dict:
    return _ok(api_client.get_technician(technician_id, ADMIN))


def get_part(part_catalog_item_id: str) -> dict:
    return _ok(api_client.get_part_catalog_item(part_catalog_item_id, ADMIN))


def get_inspection(inspection_id: str) -> dict:
    return _ok(api_client.get_inspection(inspection_id, ADMIN))


def get_water_test(water_test_id: str) -> dict:
    return _ok(api_client.get_water_test(water_test_id, ADMIN))


def get_recommendation(recommendation_id: str) -> dict:
    return _ok(api_client.get_treatment_recommendation(recommendation_id, ADMIN))


def get_quote(quote_id: str) -> dict:
    return _ok(api_client.get_quote(quote_id, ESTIMATOR))


def get_quote_line(quote_line_id: str) -> dict:
    return _ok(api_client.get_quote_line(quote_line_id, ESTIMATOR))


def get_ticket(ticket_id: str) -> dict:
    return _ok(api_client.get_emergency_ticket(ticket_id, DISPATCHER))


def get_work_order(work_order_id: str) -> dict:
    return _ok(api_client.get_work_order(work_order_id, DISPATCHER))


def get_permit(permit_id: str) -> dict:
    return _ok(api_client.get_permit(permit_id, ADMIN))


def get_plan(maintenance_plan_id: str) -> dict:
    return _ok(api_client.get_maintenance_plan(maintenance_plan_id, ADMIN))


def get_invoice(invoice_id: str) -> dict:
    return _ok(api_client.get_invoice(invoice_id, BILLING))


def get_coverage(warranty_coverage_id: str) -> dict:
    return _ok(api_client.get_warranty_coverage(warranty_coverage_id, DISPATCHER))


def get_claim(callback_claim_id: str) -> dict:
    return _ok(api_client.get_callback_claim(callback_claim_id, DISPATCHER))


def get_agreement(shared_well_agreement_id: str) -> dict:
    return _ok(api_client.get_shared_well_agreement(shared_well_agreement_id, BILLING))


def get_consumption_entry(parts_consumption_entry_id: str) -> dict:
    return _ok(
        api_client.get_parts_consumption_entry(parts_consumption_entry_id, DISPATCHER)
    )
