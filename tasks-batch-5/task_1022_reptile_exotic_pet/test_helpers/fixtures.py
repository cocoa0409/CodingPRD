"""Composite setup helpers.

Every helper takes the ApiClient as its first argument and builds its
preconditions from scratch using only PRD-declared endpoints, because the
server database is empty at the start of each test. Helpers use
get_success_data() (lenient) so setup failures surface as clear errors.

Role-header conventions:
- StoreManager / VetTech / SalesAssociate are opaque; the shared TEST_USERS
  constants are used unless a distinct operator id is needed (four-eyes).
- Customer is entity_backed; ownership-gated calls thread
  make_customer_headers(customer["id"]).
"""
from prd_bench_local_runner.testing import get_success_data
from .test_users import (
    TEST_USERS,
    make_store_manager_headers,
    make_customer_headers,
)
from . import factories as F

_SM = TEST_USERS["store_manager_headers"]
_VET = TEST_USERS["vet_tech_headers"]
_SALES = TEST_USERS["sales_associate_headers"]


# --------------------------------------------------------------------------
# Clock
# --------------------------------------------------------------------------
def set_clock(api, iso_ts):
    """Advance the logical clock (StoreManager only)."""
    return get_success_data(api.set_clock(iso_ts, headers=_SM))


# --------------------------------------------------------------------------
# Species / animals / quarantine
# --------------------------------------------------------------------------
def create_species(api, **overrides):
    """Create a species (StoreManager). Returns the species dict."""
    return get_success_data(api.create_species(F.create_species_payload(**overrides), headers=_SM))


def intake_animal(api, species_id, manager_id="mgr-intake", **overrides):
    """Intake an animal; acquired_by_user_id is stamped with manager_id."""
    headers = make_store_manager_headers(manager_id)
    return get_success_data(
        api.create_animal(F.create_animal_payload(species_id, **overrides), headers=headers)
    )


def make_animal_available(api, species_id, manager_id="mgr-intake", **animal_overrides):
    """Intake -> start-quarantine -> 2 PASS checks -> clear. Returns the
    now-AVAILABLE animal. Requires the species' min_quarantine_days to be
    satisfied by the current clock (default species uses 0)."""
    animal = intake_animal(api, species_id, manager_id=manager_id, **animal_overrides)
    qr = get_success_data(api.start_quarantine(animal["id"], headers=_VET))
    get_success_data(api.add_health_check(qr["id"], {"result": "PASS"}, headers=_VET))
    get_success_data(api.add_health_check(qr["id"], {"result": "PASS"}, headers=_VET))
    get_success_data(api.clear_quarantine(qr["id"], headers=_VET))
    return get_success_data(api.get_animal(animal["id"], headers=_SM))


def setup_available_animal(api, species_overrides=None, animal_overrides=None,
                           manager_id="mgr-intake"):
    """Create a species and an AVAILABLE animal of it. Returns (species, animal)."""
    species = create_species(api, **(species_overrides or {}))
    animal = make_animal_available(
        api, species["id"], manager_id=manager_id, **(animal_overrides or {})
    )
    return species, animal


def start_quarantine_animal(api, species_id, manager_id="mgr-intake", **animal_overrides):
    """Intake an animal and open its quarantine record (no clearance).
    Returns (animal, quarantine_record)."""
    animal = intake_animal(api, species_id, manager_id=manager_id, **animal_overrides)
    qr = get_success_data(api.start_quarantine(animal["id"], headers=_VET))
    return animal, qr


# --------------------------------------------------------------------------
# Customers / permits
# --------------------------------------------------------------------------
def create_customer(api, **overrides):
    """Register a customer (SalesAssociate). Returns the customer dict."""
    return get_success_data(api.create_customer(F.create_customer_payload(**overrides), headers=_SALES))


def create_permit(api, customer_id, **overrides):
    """Attach a permit to a customer (SalesAssociate). Returns the permit dict."""
    return get_success_data(
        api.create_permit(customer_id, F.create_permit_payload(**overrides), headers=_SALES)
    )


def setup_verified_permit(api, customer_id, **overrides):
    """Create and verify a permit. Returns the VERIFIED permit dict."""
    permit = create_permit(api, customer_id, **overrides)
    return get_success_data(api.verify_permit(permit["id"], headers=_SM))


# --------------------------------------------------------------------------
# Sales
# --------------------------------------------------------------------------
def create_draft_sale(api, animal_id, customer_id, **overrides):
    """Draft a sale (SalesAssociate). Returns the DRAFT sale dict."""
    return get_success_data(
        api.create_sale(F.create_sale_payload(animal_id, customer_id, **overrides), headers=_SALES)
    )


def create_confirmed_sale(api, animal_id, customer_id, **overrides):
    """Draft then confirm a sale. Returns the CONFIRMED sale dict."""
    sale = create_draft_sale(api, animal_id, customer_id, **overrides)
    return get_success_data(api.confirm_sale(sale["id"], headers=_SALES))


def create_fulfilled_sale(api, animal_id, customer_id, **overrides):
    """Draft -> confirm -> fulfill a sale. Returns the FULFILLED sale dict."""
    sale = create_confirmed_sale(api, animal_id, customer_id, **overrides)
    return get_success_data(api.fulfill_sale(sale["id"], headers=_SALES))


def setup_fulfilled_sale(api, species_overrides=None, animal_overrides=None,
                         customer_overrides=None, manager_id="mgr-intake"):
    """Full path to a FULFILLED, non-regulated sale.

    Returns a dict with keys: species, animal, customer, sale.
    """
    species, animal = setup_available_animal(
        api, species_overrides, animal_overrides, manager_id=manager_id
    )
    customer = create_customer(api, **(customer_overrides or {}))
    sale = create_fulfilled_sale(api, animal["id"], customer["id"])
    return {"species": species, "animal": animal, "customer": customer, "sale": sale}


def setup_approved_doa_claim(api, sale_price_cents=18000, warranty_days=30,
                             manager_id="mgr-intake", approver_id="mgr-approve",
                             acq_cost_cents=4000):
    """FULFILLED sale -> submit DOA claim -> approve it.

    Approval uses approver_id, distinct from manager_id (the intake actor
    stamped as acquired_by_user_id), satisfying warranty segregation of duties.
    Returns a dict: species, animal, customer, sale, claim.
    """
    ctx = setup_fulfilled_sale(
        api,
        species_overrides={"warranty_days": warranty_days},
        animal_overrides={"list_price_cents": sale_price_cents, "acquisition_cost_cents": acq_cost_cents},
        manager_id=manager_id,
    )
    cust_headers = make_customer_headers(ctx["customer"]["id"])
    claim = get_success_data(
        api.create_warranty_claim(
            ctx["sale"]["id"], F.create_warranty_claim_payload(claim_type="DOA"), headers=cust_headers
        )
    )
    approved = get_success_data(
        api.approve_claim(claim["id"], headers=make_store_manager_headers(approver_id))
    )
    ctx["claim"] = approved
    return ctx


# --------------------------------------------------------------------------
# Feeder inventory / subscriptions / shipments
# --------------------------------------------------------------------------
def create_feeder_batch(api, **overrides):
    """Receive a feeder batch (StoreManager). Returns the batch dict."""
    return get_success_data(api.create_feeder_batch(F.create_feeder_batch_payload(**overrides), headers=_SM))


def create_subscription(api, customer_id, **overrides):
    """Open a feeder subscription (SalesAssociate). Returns the subscription dict."""
    return get_success_data(
        api.create_subscription(F.create_subscription_payload(customer_id, **overrides), headers=_SALES)
    )


def create_shipment(api, sub_id):
    """Run a shipment against a subscription (SalesAssociate). Returns the shipment dict."""
    return get_success_data(api.create_shipment(sub_id, headers=_SALES))


def setup_subscription_with_shipment(api, batch_overrides=None, sub_overrides=None,
                                     customer_overrides=None):
    """One AVAILABLE batch, an ACTIVE subscription matching it, and one SHIPPED
    shipment allocated from that batch.

    Returns a dict: customer, batch, subscription, shipment.
    """
    batch = create_feeder_batch(api, **(batch_overrides or {}))
    customer = create_customer(api, **(customer_overrides or {}))
    sub = create_subscription(api, customer["id"], **(sub_overrides or {}))
    shipment = create_shipment(api, sub["id"])
    return {"customer": customer, "batch": batch, "subscription": sub, "shipment": shipment}


# --------------------------------------------------------------------------
# Habitat builds
# --------------------------------------------------------------------------
def create_habitat_build(api, customer_id, **overrides):
    """Create a QUOTED habitat build (SalesAssociate). Returns the build dict."""
    return get_success_data(
        api.create_habitat_build(F.create_habitat_build_payload(customer_id, **overrides), headers=_SALES)
    )


def setup_habitat_build_in_progress(api, customer=None, quote_cents=100000, **overrides):
    """Create a customer (if not supplied), a build, pay its deposit, and start
    it so it reaches IN_PROGRESS.

    Returns a dict: customer, build (the IN_PROGRESS build).
    """
    if customer is None:
        customer = create_customer(api)
    cust_headers = make_customer_headers(customer["id"])
    build = create_habitat_build(api, customer["id"], quote_cents=quote_cents, **overrides)
    get_success_data(api.pay_deposit(build["id"], headers=cust_headers))
    started = get_success_data(api.start_build(build["id"], headers=_SALES))
    return {"customer": customer, "build": started}


# --------------------------------------------------------------------------
# Expos
# --------------------------------------------------------------------------
def create_expo(api, **overrides):
    """Create a SCHEDULED expo (StoreManager). Returns the expo dict."""
    return get_success_data(api.create_expo(F.create_expo_payload(**overrides), headers=_SM))


def assign_animal_to_expo(api, expo_id, animal_id):
    """Assign an animal to an expo booth (SalesAssociate). Returns the assignment dict."""
    return get_success_data(
        api.create_expo_assignment(expo_id, {"animal_id": animal_id}, headers=_SALES)
    )


# --------------------------------------------------------------------------
# Recalls
# --------------------------------------------------------------------------
def open_recall(api, affected_batch_ids, opener_id="mgr-recall", **overrides):
    """Open a feeder recall stamped with opener_id (StoreManager). Returns the recall dict."""
    return get_success_data(
        api.create_recall(
            F.create_recall_payload(affected_batch_ids, **overrides),
            headers=make_store_manager_headers(opener_id),
        )
    )
