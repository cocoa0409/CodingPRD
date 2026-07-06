"""Composite setup helpers.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints, because the harness restarts the server (empty DB) before every
test. Fixtures use get_success_data (lenient) so setup failures surface as
clear "Setup failed" errors.

Identity threading: after a Recipient entity is created, every ownership-gated
Recipient call uses make_recipient_headers(recipient_id) — never the shared
TEST_USERS["recipient_headers"] constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS, make_recipient_headers

SO = TEST_USERS["screening_officer_headers"]
LT = TEST_USERS["lab_tech_headers"]
CO = TEST_USERS["compliance_officer_headers"]
CM = TEST_USERS["catalog_manager_headers"]
BC = TEST_USERS["billing_clerk_headers"]


# ---------------------------------------------------------------------------
# Clock helpers
# ---------------------------------------------------------------------------
def set_clock(to_iso8601, headers=None):
    return get_success_data(api_client.set_clock(to_iso8601, headers or CO))


# ---------------------------------------------------------------------------
# Tier 1: State progression — donor through screening lifecycle
# ---------------------------------------------------------------------------
def create_approved_donor(display_code="D-1", blood_type="O_POS", family_limit=10,
                          donor_type="SPERM"):
    """Register a donor and walk its screening application to APPROVED.
    Returns (donor_id, app_id)."""
    donor = get_success_data(api_client.create_donor({
        "display_code": display_code, "full_name": f"{display_code} Name",
        "donor_type": donor_type, "blood_type": blood_type,
        "family_limit": family_limit,
    }, SO))
    donor_id = donor["id"]
    app = get_success_data(api_client.create_screening_application({
        "donor_id": donor_id, "fda_risk_flag": False,
        "genetic_carrier_count": 0, "partner_screening_required": False,
    }, SO))
    app_id = app["id"]
    get_success_data(api_client.start_review(app_id, SO))
    get_success_data(api_client.approve_application(app_id, SO))
    return donor_id, app_id


def create_under_review_application(display_code="D-1", fda_risk_flag=False,
                                    genetic_carrier_count=0,
                                    partner_screening_required=False,
                                    family_limit=10):
    """Register a donor + application and advance the application to UNDER_REVIEW.
    Returns (donor_id, app_id)."""
    donor = get_success_data(api_client.create_donor({
        "display_code": display_code, "full_name": f"{display_code} Name",
        "donor_type": "SPERM", "blood_type": "O_POS", "family_limit": family_limit,
    }, SO))
    donor_id = donor["id"]
    app = get_success_data(api_client.create_screening_application({
        "donor_id": donor_id, "fda_risk_flag": fda_risk_flag,
        "genetic_carrier_count": genetic_carrier_count,
        "partner_screening_required": partner_screening_required,
    }, SO))
    app_id = app["id"]
    get_success_data(api_client.start_review(app_id, SO))
    return donor_id, app_id


# ---------------------------------------------------------------------------
# Tier 2/3: Released, catalog-listed inventory
# ---------------------------------------------------------------------------
def setup_listed_inventory(display_code="D-1", blood_type="O_POS",
                           family_limit=10, initial_vial_count=5,
                           dewar_code="T-1", release_clock="2026-06-01T00:00:00Z"):
    """Approved donor -> specimen -> begin-quarantine -> advance clock ->
    release-quarantine -> read the inventory lot.
    Returns dict: donor_id, app_id, specimen_id, inventory_id, inventory_version.
    Leaves the clock set to release_clock. Donor becomes ACTIVE on release."""
    donor_id, app_id = create_approved_donor(
        display_code=display_code, blood_type=blood_type, family_limit=family_limit)
    specimen = get_success_data(api_client.create_specimen({
        "donor_id": donor_id, "collection_date": "2026-05-01T00:00:00Z",
        "initial_vial_count": initial_vial_count,
        "quarantine_release_date": "2026-06-01T00:00:00Z",
        "retest_negative": True,
    }, LT))
    specimen_id = specimen["id"]
    get_success_data(api_client.begin_quarantine(specimen_id, dewar_code, LT))
    set_clock(release_clock, CO)
    get_success_data(api_client.release_quarantine(specimen_id, CO))
    inv_list = get_success_data(api_client.list_donor_inventories(
        CM, params={"specimen_id": specimen_id}))
    inv = inv_list[0]
    return {
        "donor_id": donor_id, "app_id": app_id, "specimen_id": specimen_id,
        "inventory_id": inv["id"], "inventory_version": inv["version"],
    }


def setup_recipient_with_consent(donor_id, family_name="Fam R",
                                 contact_email="r@x.com"):
    """Register a recipient, draft + sign a consent for the given donor.
    Returns dict: recipient_id, consent_id, headers (recipient-owned)."""
    recipient = get_success_data(api_client.create_recipient({
        "family_name": family_name, "contact_email": contact_email,
    }, CM))
    rcp_id = recipient["id"]
    rcp_headers = make_recipient_headers(rcp_id)
    consent = get_success_data(api_client.create_recipient_consent({
        "recipient_id": rcp_id, "donor_id": donor_id,
        "acknowledges_open_id": True,
    }, rcp_headers))
    con_id = consent["id"]
    get_success_data(api_client.sign_consent(con_id, rcp_headers))
    return {"recipient_id": rcp_id, "consent_id": con_id, "headers": rcp_headers}


def setup_listed_inventory_with_consented_recipient(
        display_code="D-1", blood_type="O_POS", family_limit=10,
        initial_vial_count=5, dewar_code="T-1"):
    """Listed inventory + one recipient with a signed consent.
    Returns dict merging setup_listed_inventory + recipient_id/consent_id/headers.
    Re-reads the inventory version after consent (consent does not touch the
    inventory, so version is unchanged, but we re-read defensively)."""
    inv = setup_listed_inventory(
        display_code=display_code, blood_type=blood_type,
        family_limit=family_limit, initial_vial_count=initial_vial_count,
        dewar_code=dewar_code)
    rcp = setup_recipient_with_consent(inv["donor_id"])
    fresh = get_success_data(api_client.get_donor_inventory(inv["inventory_id"], CM))
    inv["inventory_version"] = fresh["version"]
    inv.update(rcp)
    return inv


# ---------------------------------------------------------------------------
# Tier 3: Reservation lifecycle shortcuts
# ---------------------------------------------------------------------------
def place_hold(inventory_id, recipient_id, recipient_headers, vial_count,
               expected_version):
    """Create a HELD reservation. Returns the reservation dict."""
    return get_success_data(api_client.create_vial_reservation({
        "recipient_id": recipient_id, "inventory_id": inventory_id,
        "vial_count": vial_count, "expected_inventory_version": expected_version,
    }, recipient_headers))


def setup_confirmed_reservation(display_code="D-1", dewar_code="T-1",
                                vial_count=2, family_limit=10,
                                initial_vial_count=5):
    """Listed inventory + consented recipient + a CONFIRMED reservation.
    Returns dict with donor_id, recipient_id, inventory_id, reservation_id, headers."""
    ctx = setup_listed_inventory_with_consented_recipient(
        display_code=display_code, dewar_code=dewar_code,
        family_limit=family_limit, initial_vial_count=initial_vial_count)
    res = place_hold(ctx["inventory_id"], ctx["recipient_id"], ctx["headers"],
                     vial_count, ctx["inventory_version"])
    get_success_data(api_client.confirm_reservation(res["id"], CM))
    ctx["reservation_id"] = res["id"]
    ctx["vial_count"] = vial_count
    return ctx


def setup_preparing_shipment(display_code="D-1", dewar_code="T-1",
                             vial_count=2, ln2_dewar_serial="DS-1"):
    """Confirmed reservation + a PREPARING shipment.
    Returns dict with ...reservation_id, shipment_id."""
    ctx = setup_confirmed_reservation(
        display_code=display_code, dewar_code=dewar_code, vial_count=vial_count)
    ship = get_success_data(api_client.create_shipment({
        "reservation_id": ctx["reservation_id"], "clinic_address": "1 Clinic Way",
        "ln2_dewar_serial": ln2_dewar_serial,
    }, LT))
    ctx["shipment_id"] = ship["id"]
    return ctx


def setup_shipped_reservation(display_code="D-1", dewar_code="T-1",
                              vial_count=2, ln2_dewar_serial="DS-1",
                              ship_clock=None):
    """Confirmed reservation -> shipment -> dispatch, so the reservation is
    SHIPPED and a StorageAccount + period-0 RENEWAL invoice exist.
    If ship_clock is given, the clock is set before dispatch (controls period_start).
    Returns dict with ...reservation_id, shipment_id, storage_account_id."""
    ctx = setup_preparing_shipment(
        display_code=display_code, dewar_code=dewar_code,
        vial_count=vial_count, ln2_dewar_serial=ln2_dewar_serial)
    if ship_clock is not None:
        set_clock(ship_clock, BC)
    get_success_data(api_client.dispatch_shipment(ctx["shipment_id"], LT))
    acct_list = get_success_data(api_client.list_storage_accounts(
        BC, params={"reservation_id": ctx["reservation_id"]}))
    ctx["storage_account_id"] = acct_list[0]["id"]
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: Family-limit / sibling registry targeting
# ---------------------------------------------------------------------------
def confirm_one_family(donor_id, recipient_id, recipient_headers,
                       birth_date="2026-06-05T00:00:00Z"):
    """Report a birth for (donor, recipient) and confirm it (recipient must
    already have a SHIPPED reservation for the donor). Returns the entry id."""
    entry = get_success_data(api_client.create_sibling_registry_entry({
        "donor_id": donor_id, "recipient_id": recipient_id,
        "birth_reported_date": birth_date,
    }, recipient_headers))
    get_success_data(api_client.confirm_sibling_registry(entry["id"], CO))
    return entry["id"]


# ---------------------------------------------------------------------------
# Tier 5: Storage lapse targeting
# ---------------------------------------------------------------------------
def setup_lapsed_account(display_code="D-1", dewar_code="T-1", vial_count=2,
                         ship_clock="2026-06-01T00:00:00Z",
                         lapse_clock="2027-07-01T00:00:00Z"):
    """Shipped reservation (StorageAccount ACTIVE) -> pay the period-0 invoice to
    establish paid_through (period_start + 365 = 2027-06-01 for the default
    ship_clock, per PRD §3.7 "paying an invoice ... advances paid_through by one
    full 365-day billing period") -> advance clock past paid_through+grace ->
    assess-lapse. Returns dict with storage_account_id and lapse_invoice_id (the
    ISSUED LAPSE invoice).

    Paying period-0 first is required because PRD §3.7 gates assess-lapse on
    "the current logical time has reached or passed paid_through plus the grace
    period of 30 days"; paid_through is the end of the period covered by the most
    recent paid invoice, so a lapse cannot be assessed until at least one invoice
    has been paid."""
    ctx = setup_shipped_reservation(
        display_code=display_code, dewar_code=dewar_code,
        vial_count=vial_count, ship_clock=ship_clock)
    invs = get_success_data(api_client.list_storage_invoices(
        BC, params={"storage_account_id": ctx["storage_account_id"]}))
    period0 = next(iv for iv in invs if iv["period_index"] == 0)
    get_success_data(api_client.pay_invoice(period0["id"], BC))
    set_clock(lapse_clock, BC)
    get_success_data(api_client.assess_lapse(ctx["storage_account_id"], BC))
    inv_list = get_success_data(api_client.list_storage_invoices(
        BC, params={"storage_account_id": ctx["storage_account_id"],
                    "billing_mode": "LAPSE"}))
    ctx["lapse_invoice_id"] = inv_list[0]["id"]
    return ctx


# ---------------------------------------------------------------------------
# Tier 2: Deferred donor (frozen inventory) — cascade setups
# ---------------------------------------------------------------------------
def defer_donor_via_second_application(donor_id, display_code="D-1"):
    """Submit a second application on an already-approved donor, start review,
    and defer it — driving the donor to DEFERRED and freezing its inventory /
    cascading cancellations. Returns the deferred app id."""
    app = get_success_data(api_client.create_screening_application({
        "donor_id": donor_id, "fda_risk_flag": False,
        "genetic_carrier_count": 0, "partner_screening_required": False,
    }, SO))
    app_id = app["id"]
    get_success_data(api_client.start_review(app_id, SO))
    get_success_data(api_client.defer_application(app_id, SO))
    return app_id
