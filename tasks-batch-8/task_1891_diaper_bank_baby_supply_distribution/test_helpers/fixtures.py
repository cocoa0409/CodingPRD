"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only. Setup calls use get_success_data() so failures
surface as clear "Setup step failed" errors rather than confusing assertions.

Identity threading: AgencyCoordinator calls are entity-backed by PartnerAgency;
any composite that returns an agency also returns coordinator headers built
from the real agency id via make_agency_coordinator_headers.
"""
import math

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import (
    CURRENT_PERIOD,
    DEFAULT_EVENT_ENDS,
    DEFAULT_EVENT_STARTS,
    DEFAULT_SHIFT_ENDS,
    DEFAULT_SHIFT_STARTS,
    UNITS_PER_CHILD_PER_MONTH,
)
from .factories import (
    create_adjustment_payload,
    create_agency_payload,
    create_allocation_run_payload,
    create_event_payload,
    create_grant_payload,
    create_household_payload,
    create_intake_batch_payload,
    create_issuance_payload,
    create_purchase_order_payload,
    create_signup_payload,
    create_volunteer_shift_payload,
    supply_line,
)
from .test_users import TEST_USERS, make_agency_coordinator_headers

ADMIN = TEST_USERS["bank_admin_headers"]
WAREHOUSE = TEST_USERS["warehouse_manager_headers"]
FINANCE = TEST_USERS["finance_manager_headers"]
PRIVACY = TEST_USERS["privacy_officer_headers"]
VOLUNTEER_COORD = TEST_USERS["volunteer_coordinator_headers"]
VOLUNTEER = TEST_USERS["volunteer_headers"]


# ---------------------------------------------------------------------------
# Inventory and intake
# ---------------------------------------------------------------------------

def init_inventory(thresholds=None):
    """Initialize the inventory singleton. Returns the Inventory body."""
    payload = {}
    if thresholds is not None:
        payload["thresholds"] = thresholds
    return get_success_data(api_client.initialize_inventory(payload, WAREHOUSE))


def get_inventory():
    """Read the inventory singleton."""
    return get_success_data(api_client.get_inventory(WAREHOUSE))


def create_donation_batch(lines, donor_name=None):
    """Create a DONATION intake batch (born COUNTED). Returns the batch."""
    return get_success_data(
        api_client.create_intake_batch(
            create_intake_batch_payload(donor_name=donor_name, lines=lines),
            WAREHOUSE,
        ),
        expected_status=201,
    )


def post_donation(lines, donor_name=None):
    """Create a donation batch and post it. Returns the POSTED batch."""
    batch = create_donation_batch(lines, donor_name=donor_name)
    return get_success_data(api_client.post_intake_batch(batch["id"], WAREHOUSE))


# ---------------------------------------------------------------------------
# Partner agencies
# ---------------------------------------------------------------------------

def create_agency(children_served_monthly=300, storage_capacity_units=100000,
                  name=None, agency_code=None, contact_email=None):
    """Create a partner agency (born ACTIVE). Returns the agency."""
    overrides = {
        "children_served_monthly": children_served_monthly,
        "storage_capacity_units": storage_capacity_units,
    }
    if name is not None:
        overrides["name"] = name
    if agency_code is not None:
        overrides["agency_code"] = agency_code
    if contact_email is not None:
        overrides["contact_email"] = contact_email
    return get_success_data(
        api_client.create_agency(create_agency_payload(**overrides), ADMIN),
        expected_status=201,
    )


def get_agency(agency_id):
    return get_success_data(api_client.get_agency(agency_id, ADMIN))


def suspend_agency(agency_id):
    return get_success_data(api_client.suspend_agency(agency_id, ADMIN))


# ---------------------------------------------------------------------------
# Grants and purchase orders
# ---------------------------------------------------------------------------

def create_active_grant(total_amount_cents=100000, restriction=None,
                        funder_name=None, grant_code=None):
    """Create a grant (born ACTIVE). Returns the grant."""
    overrides = {"total_amount_cents": total_amount_cents}
    if restriction is not None:
        overrides["restriction"] = restriction
    if funder_name is not None:
        overrides["funder_name"] = funder_name
    if grant_code is not None:
        overrides["grant_code"] = grant_code
    return get_success_data(
        api_client.create_grant(create_grant_payload(**overrides), FINANCE),
        expected_status=201,
    )


def get_grant(grant_id):
    return get_success_data(api_client.get_grant(grant_id, FINANCE))


def create_draft_po(grant_id, lines=None, discount_pct=None, creator_headers=None):
    """Create a DRAFT purchase order against a grant.

    The creator defaults to the shared WarehouseManager identity (wm-user-1);
    total_cost_cents is computed by the server at creation.
    """
    headers = creator_headers if creator_headers is not None else WAREHOUSE
    return get_success_data(
        api_client.create_purchase_order(
            create_purchase_order_payload(grant_id, lines=lines,
                                          discount_pct=discount_pct),
            headers,
        ),
        expected_status=201,
    )


def get_purchase_order(po_id):
    return get_success_data(api_client.get_purchase_order(po_id, WAREHOUSE))


def submit_po(po_id, submitter_headers=None):
    """Submit a DRAFT order as FinanceManager (fm-user-1 by default, which
    differs from the default creator identity, satisfying segregation of duties)."""
    headers = submitter_headers if submitter_headers is not None else FINANCE
    return get_success_data(api_client.submit_purchase_order(po_id, headers))


def receive_po(po_id, received_lines):
    """Receive a SUBMITTED order. Returns the RECEIVED order."""
    return get_success_data(
        api_client.receive_purchase_order(po_id, {"received_lines": received_lines},
                                          WAREHOUSE))


def cancel_po(po_id, headers):
    return get_success_data(api_client.cancel_purchase_order(po_id, headers))


# ---------------------------------------------------------------------------
# Allocation runs
# ---------------------------------------------------------------------------

def create_run(period=CURRENT_PERIOD, formula_variant=None):
    """Create an allocation run (born DRAFT, computed_at null). Returns the run."""
    return get_success_data(
        api_client.create_allocation_run(
            create_allocation_run_payload(period=period, formula_variant=formula_variant),
            ADMIN,
        ),
        expected_status=201,
    )


def get_run(run_id):
    return get_success_data(api_client.get_allocation_run(run_id, ADMIN))


def compute_run(run_id):
    """Run the allocation formula over a DRAFT run. Returns the recomputed run."""
    return get_success_data(api_client.compute_allocation_run(run_id, ADMIN))


def publish_run(run_id):
    return get_success_data(api_client.publish_allocation_run(run_id, ADMIN))


def get_run_lines(run_id):
    """All lines of a run (sorted size_code ASC, children DESC, created_at ASC)."""
    data, _meta = validate_paginated(api_client.list_allocation_run_lines(run_id, ADMIN))
    return data


def setup_allocation_scenario(size_code="SIZE_1", stock_units=1000,
                              agencies=((300, 100000),), period=CURRENT_PERIOD,
                              formula_variant=None, publish=False,
                              donor_name=None):
    """Inventory + one posted donation + N ACTIVE agencies + a computed run.

    agencies: iterable of (children_served_monthly, storage_capacity_units).
    The single posted donation stocks exactly `stock_units` of `size_code`, so
    that size's pool at compute time is `stock_units` (all other sizes pool 0).
    Returns dict(inventory, batch, agencies, run, lines).
    """
    inventory = init_inventory()
    batch = post_donation([supply_line(size_code, stock_units)], donor_name=donor_name)
    created_agencies = [
        create_agency(children_served_monthly=children, storage_capacity_units=storage)
        for children, storage in agencies
    ]
    run = create_run(period=period, formula_variant=formula_variant)
    run = compute_run(run["id"])
    if publish:
        run = publish_run(run["id"])
    lines = get_run_lines(run["id"])
    return {
        "inventory": inventory,
        "batch": batch,
        "agencies": created_agencies,
        "run": run,
        "lines": lines,
    }


def setup_published_allocation(size_code="SIZE_1", stock_units=500,
                               agency_children=300, agency_storage=100000,
                               period=CURRENT_PERIOD, formula_variant=None):
    """Single-agency published run: the one eligible agency receives the whole
    pool, so the run has exactly one line (agency, size_code) with
    allocated_units == stock_units. Returns dict(inventory, batch, agency, run,
    line, coordinator_headers)."""
    scenario = setup_allocation_scenario(
        size_code=size_code, stock_units=stock_units,
        agencies=((agency_children, agency_storage),),
        period=period, formula_variant=formula_variant, publish=True,
    )
    agency = scenario["agencies"][0]
    line = scenario["lines"][0]
    assert line["allocated_units"] == stock_units, (
        f"Fixture assumption broken: expected the whole pool ({stock_units}) on the "
        f"single line, got {line['allocated_units']}"
    )
    return {
        "inventory": scenario["inventory"],
        "batch": scenario["batch"],
        "agency": agency,
        "run": scenario["run"],
        "line": line,
        "coordinator_headers": make_agency_coordinator_headers(agency["id"]),
    }


# ---------------------------------------------------------------------------
# Client households
# ---------------------------------------------------------------------------

def create_household(children_sizes=("SIZE_1",), consent_on_file=None,
                     privacy_restricted=None, household_code=None):
    """Register a household (born PENDING_REVIEW). Returns the household."""
    return get_success_data(
        api_client.create_household(
            create_household_payload(
                household_code=household_code,
                children_sizes=list(children_sizes),
                consent_on_file=consent_on_file,
                privacy_restricted=privacy_restricted,
            ),
            PRIVACY,
        ),
        expected_status=201,
    )


def create_eligible_household(children_sizes=("SIZE_1",), privacy_restricted=False,
                              household_code=None, reason="verified"):
    """Register a household with consent on file and decide ELIGIBLE."""
    household = create_household(
        children_sizes=children_sizes,
        consent_on_file=True,
        privacy_restricted=privacy_restricted or None,
        household_code=household_code,
    )
    return get_success_data(api_client.patch_household(
        household["id"],
        {"eligibility_status": "ELIGIBLE", "eligibility_reason": reason},
        PRIVACY,
    ))


def get_household(household_id):
    return get_success_data(api_client.get_household(household_id, PRIVACY))


# ---------------------------------------------------------------------------
# Distribution events and issuances
# ---------------------------------------------------------------------------

def create_event(agency_id, site_name="T-Site", starts_at=DEFAULT_EVENT_STARTS,
                 ends_at=DEFAULT_EVENT_ENDS):
    """Schedule a distribution event (born SCHEDULED). Returns the event."""
    return get_success_data(
        api_client.create_distribution_event(
            create_event_payload(agency_id, site_name=site_name,
                                 starts_at=starts_at, ends_at=ends_at),
            ADMIN,
        ),
        expected_status=201,
    )


def get_event(event_id):
    return get_success_data(api_client.get_distribution_event(event_id, ADMIN))


def open_event(event_id):
    return get_success_data(api_client.open_distribution_event(event_id, ADMIN))


def lock_event(event_id):
    return get_success_data(api_client.lock_distribution_event(event_id, ADMIN))


def unlock_event(event_id):
    return get_success_data(api_client.unlock_distribution_event(event_id, ADMIN))


def complete_event(event_id):
    return get_success_data(api_client.complete_distribution_event(event_id, ADMIN))


def record_issuance(event_id, household_id, lines, headers=None):
    """Record an issuance at an OPEN event (PrivacyOfficer by default).
    Returns the RECORDED issuance."""
    recorder = headers if headers is not None else PRIVACY
    return get_success_data(
        api_client.record_issuance(event_id, create_issuance_payload(household_id, lines),
                                   recorder),
        expected_status=201,
    )


def get_event_issuances(event_id):
    data, _meta = validate_paginated(api_client.list_event_issuances(event_id, ADMIN))
    return data


def _default_children_sizes(size_code, issue_quantity):
    """Smallest children_sizes list whose monthly allotment covers the issuance."""
    if not issue_quantity:
        return [size_code]
    children = max(1, math.ceil(issue_quantity / UNITS_PER_CHILD_PER_MONTH))
    return [size_code] * children


def setup_event_with_issuance(size_code="SIZE_1", stock_units=500,
                              issue_quantity=100, children_sizes=None,
                              privacy_restricted=False, period=CURRENT_PERIOD,
                              site_name="T-Site", event_starts=DEFAULT_EVENT_STARTS,
                              event_ends=DEFAULT_EVENT_ENDS,
                              record=True, fulfill=False):
    """Published allocation + eligible household + OPEN event, with an optional
    RECORDED issuance and optional lock/complete fulfillment.

    Chain: initialize inventory -> post donation of `stock_units` -> agency ->
    run `period` computed + published (single line allocated == stock_units) ->
    household (allotment auto-sized to cover the issuance) marked ELIGIBLE ->
    event created + opened -> optional issuance of `issue_quantity` -> optional
    lock + complete. Returns dict(inventory, batch, agency, run, line, household,
    event, issuance, coordinator_headers).
    """
    allocation = setup_published_allocation(
        size_code=size_code, stock_units=stock_units, period=period,
    )
    if children_sizes is None:
        children_sizes = _default_children_sizes(size_code, issue_quantity)
    household = create_eligible_household(
        children_sizes=children_sizes, privacy_restricted=privacy_restricted,
    )
    event = create_event(allocation["agency"]["id"], site_name=site_name,
                         starts_at=event_starts, ends_at=event_ends)
    event = open_event(event["id"])
    issuance = None
    if record:
        issuance = record_issuance(
            event["id"], household["id"],
            [supply_line(size_code, issue_quantity)],
        )
    if fulfill:
        lock_event(event["id"])
        event = complete_event(event["id"])
    return {
        "inventory": allocation["inventory"],
        "batch": allocation["batch"],
        "agency": allocation["agency"],
        "run": allocation["run"],
        "line": allocation["line"],
        "household": household,
        "event": event,
        "issuance": issuance,
        "coordinator_headers": allocation["coordinator_headers"],
    }


def setup_completed_event(size_code="SIZE_1", stock_units=500, issue_quantity=100,
                          children_sizes=None, period=CURRENT_PERIOD,
                          site_name="T-Site", event_starts=DEFAULT_EVENT_STARTS,
                          event_ends=DEFAULT_EVENT_ENDS):
    """setup_event_with_issuance carried through completion: the issuance is
    FULFILLED, inventory debited, and the allocation line credited."""
    return setup_event_with_issuance(
        size_code=size_code, stock_units=stock_units, issue_quantity=issue_quantity,
        children_sizes=children_sizes, period=period, site_name=site_name,
        event_starts=event_starts, event_ends=event_ends, record=True, fulfill=True,
    )


# ---------------------------------------------------------------------------
# Volunteer shifts
# ---------------------------------------------------------------------------

def create_shift(title=None, starts_at=DEFAULT_SHIFT_STARTS,
                 ends_at=DEFAULT_SHIFT_ENDS, capacity=2):
    """Create a volunteer shift (born OPEN). Returns the shift."""
    return get_success_data(
        api_client.create_volunteer_shift(
            create_volunteer_shift_payload(title=title, starts_at=starts_at,
                                           ends_at=ends_at, capacity=capacity),
            VOLUNTEER_COORD,
        ),
        expected_status=201,
    )


def signup_volunteer(shift_id, volunteer_email, volunteer_name="Vol Unteer"):
    """Sign a volunteer up (Volunteer self-signup). Returns the shift."""
    return get_success_data(
        api_client.signup_volunteer(
            shift_id, create_signup_payload(volunteer_email, volunteer_name), VOLUNTEER),
        expected_status=201,
    )
