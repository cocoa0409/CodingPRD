"""Composite setup helpers.

Every test starts against an empty database, so each helper here builds its
preconditions from scratch using only endpoints the PRD declares.  The helpers
use the lenient `get_success_data()` validator so a broken preamble reports as a
setup failure rather than as a confusing assertion error.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import BASE_CLOCK_UTC
from .factories import (
    consignment_payload,
    employee_payload,
    engagement_payload,
    expense_item_payload,
    gob_license_payload,
    inventory_lot_payload,
    jurisdiction_payload,
    lease_disposition_payload,
    markdown_stage_payload,
    sales_day_payload,
    store_payload,
)
from .test_users import (
    TEST_USERS,
    make_compliance_headers,
    make_consultant_headers,
    make_controller_headers,
    make_store_manager_headers,
)

CONSULTANT = TEST_USERS["consultant_headers"]
SECOND_CONSULTANT = TEST_USERS["second_consultant_headers"]
CONTROLLER = TEST_USERS["controller_headers"]
SECOND_CONTROLLER = TEST_USERS["second_controller_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]
SECOND_COMPLIANCE = TEST_USERS["second_compliance_headers"]


# ==========================================================================
# Tier 0: single-step primitives
# ==========================================================================

def pin_clock(current_utc=BASE_CLOCK_UTC):
    """Pin the logical clock. The clock endpoint carries no user headers."""
    return get_success_data(api_client.set_clock(current_utc))


def create_jurisdiction(**overrides):
    return get_success_data(
        api_client.create_jurisdiction(jurisdiction_payload(**overrides), COMPLIANCE)
    )


def create_engagement(**overrides):
    return get_success_data(
        api_client.create_engagement(engagement_payload(**overrides), CONSULTANT)
    )


def add_store(engagement_id, jurisdiction_id, **overrides):
    return get_success_data(
        api_client.create_store(
            engagement_id, store_payload(jurisdiction_id, **overrides), CONSULTANT
        )
    )


def add_inventory_lot(store_id, **overrides):
    return get_success_data(
        api_client.create_inventory_lot(
            store_id, inventory_lot_payload(**overrides), CONSULTANT
        )
    )


def submit_engagement(engagement_id):
    return get_success_data(
        api_client.submit_engagement_for_approval(engagement_id, CONSULTANT)
    )


def approve_engagement(engagement_id, decision="APPROVE", **extra):
    payload = {"decision": decision}
    payload.update(extra)
    return get_success_data(
        api_client.decide_engagement_approval(engagement_id, payload, CONTROLLER)
    )


def apply_for_license(store_id, applied_by=COMPLIANCE, **overrides):
    return get_success_data(
        api_client.create_gob_license(
            store_id, gob_license_payload(**overrides), applied_by
        )
    )


def decide_license(license_id, decision="APPROVE", decided_by=SECOND_COMPLIANCE, **extra):
    payload = {"decision": decision}
    payload.update(extra)
    return get_success_data(
        api_client.decide_gob_license(license_id, payload, decided_by)
    )


def revoke_license(license_id, revoked_reason="signage violation", decided_by=COMPLIANCE):
    return get_success_data(
        api_client.revoke_gob_license(
            license_id, {"revoked_reason": revoked_reason}, decided_by
        )
    )


def read_store(store_id, headers=None):
    return get_success_data(api_client.get_store(store_id, headers or CONSULTANT))


def read_engagement(engagement_id, headers=None):
    return get_success_data(
        api_client.get_engagement(engagement_id, headers or CONSULTANT)
    )


def store_version(store_id):
    """The store's live version, for pinning a markdown-stage author call."""
    return read_store(store_id)["version"]


def engagement_version(engagement_id):
    """The engagement's live version, for pinning a settlement create call."""
    return read_engagement(engagement_id)["version"]


# ==========================================================================
# Tier 1: state progression
# ==========================================================================

def add_markdown_stage(store_id, **overrides):
    """Author the next markdown stage, pinning the store's live version."""
    payload = markdown_stage_payload(store_version(store_id), **overrides)
    return get_success_data(
        api_client.create_markdown_stage(store_id, payload, CONSULTANT)
    )


def activate_markdown_stage(stage_id):
    return get_success_data(api_client.activate_markdown_stage(stage_id, CONSULTANT))


def checkpoint_markdown_stage(stage_id):
    return get_success_data(api_client.checkpoint_markdown_stage(stage_id, CONSULTANT))


def add_and_activate_markdown_stage(store_id, **overrides):
    stage = add_markdown_stage(store_id, **overrides)
    return activate_markdown_stage(stage["id"])


def add_employee(store_id, **overrides):
    return get_success_data(
        api_client.create_employee(store_id, employee_payload(**overrides), CONSULTANT)
    )


def run_employment_action(employee_id, action, headers=None):
    return get_success_data(
        api_client.employment_action(
            employee_id, {"action": action}, headers or CONSULTANT
        )
    )


def file_sales_day(store_id, **overrides):
    return get_success_data(
        api_client.create_sales_day(store_id, sales_day_payload(**overrides), CONSULTANT)
    )


def post_sales_day(store_id, **overrides):
    """File one selling day and have the retailer post it."""
    day = file_sales_day(store_id, **overrides)
    return get_success_data(
        api_client.review_sales_day(day["id"], {"decision": "POST"}, CONTROLLER)
    )


def reject_sales_day(store_id, reject_reason="register mis-key", **overrides):
    day = file_sales_day(store_id, **overrides)
    return get_success_data(
        api_client.review_sales_day(
            day["id"], {"decision": "REJECT", "reject_reason": reject_reason}, CONTROLLER
        )
    )


def submit_expense_item(engagement_id, submitted_by=CONSULTANT, **overrides):
    return get_success_data(
        api_client.create_expense_item(
            engagement_id, expense_item_payload(**overrides), submitted_by
        )
    )


def approve_expense_item(expense_item_id, decided_by=CONTROLLER, **extra):
    payload = {"action": "APPROVE"}
    payload.update(extra)
    return get_success_data(
        api_client.decide_expense_item(expense_item_id, payload, decided_by)
    )


def void_expense_item(expense_item_id, decided_by=CONTROLLER, **extra):
    payload = {"action": "VOID"}
    payload.update(extra)
    return get_success_data(
        api_client.decide_expense_item(expense_item_id, payload, decided_by)
    )


def submit_and_approve_expense(engagement_id, **overrides):
    item = submit_expense_item(engagement_id, **overrides)
    return approve_expense_item(item["id"])


def propose_consignment(store_id, **overrides):
    return get_success_data(
        api_client.create_augmentation_consignment(
            store_id, consignment_payload(**overrides), CONSULTANT
        )
    )


def file_consignment_disclosure(consignment_id, disclosure_reference="NY-DISC-1"):
    return get_success_data(
        api_client.file_consignment_disclosure(
            consignment_id, COMPLIANCE, {"disclosure_reference": disclosure_reference}
        )
    )


def receive_consignment(consignment_id):
    return get_success_data(api_client.receive_consignment(consignment_id, CONSULTANT))


def propose_disclose_and_receive_consignment(store_id, disclosure_reference="NY-DISC-1",
                                             **overrides):
    """Walk a consignment from PROPOSED through DISCLOSURE_FILED to RECEIVED."""
    consignment = propose_consignment(store_id, **overrides)
    file_consignment_disclosure(consignment["id"], disclosure_reference)
    return receive_consignment(consignment["id"])


def close_store(store_id):
    return get_success_data(api_client.close_selling(store_id, CONSULTANT))


def suspend_store(store_id, **payload):
    return get_success_data(
        api_client.suspend_store(store_id, COMPLIANCE, payload or None)
    )


def resume_store(store_id):
    return get_success_data(api_client.resume_store(store_id, COMPLIANCE))


def run_compliance_sweep(engagement_id):
    return get_success_data(
        api_client.run_compliance_sweep(engagement_id, COMPLIANCE)
    )


def wind_down_engagement(engagement_id):
    return get_success_data(api_client.wind_down_engagement(engagement_id, CONSULTANT))


# ==========================================================================
# Tier 2: entity hierarchy
# ==========================================================================

def setup_planned_store(clock=BASE_CLOCK_UTC, jurisdiction_overrides=None,
                        engagement_overrides=None, store_overrides=None,
                        lot_overrides=None):
    """Clock + jurisdiction + DRAFT engagement + one PLANNED store + one lot.

    Returns a dict with the keys ``jurisdiction``, ``engagement``, ``store`` and
    ``lot``.
    """
    pin_clock(clock)
    jurisdiction = create_jurisdiction(**(jurisdiction_overrides or {}))
    engagement = create_engagement(**(engagement_overrides or {}))
    store = add_store(engagement["id"], jurisdiction["id"], **(store_overrides or {}))
    lot = add_inventory_lot(store["id"], **(lot_overrides or {}))
    return {
        "jurisdiction": jurisdiction,
        "engagement": engagement,
        "store": store,
        "lot": lot,
    }


def setup_approved_engagement(**kwargs):
    """A one-store engagement carried through retailer approval.

    Where the jurisdiction requires a licence the store lands in
    ``LICENSE_PENDING``; where it does not, the store lands in ``SELLING``.
    """
    scenario = setup_planned_store(**kwargs)
    submit_engagement(scenario["engagement"]["id"])
    scenario["engagement"] = approve_engagement(scenario["engagement"]["id"])
    scenario["store"] = read_store(scenario["store"]["id"])
    return scenario


def setup_selling_store(license_overrides=None, **kwargs):
    """The canonical preamble: one store selling under an approved licence.

    Returns the ``setup_planned_store`` dict plus ``license``, with ``store``
    re-read after the licence approval lifted it to ``SELLING``.
    """
    scenario = setup_approved_engagement(**kwargs)
    store_id = scenario["store"]["id"]
    license_row = apply_for_license(store_id, **(license_overrides or {}))
    scenario["license"] = decide_license(license_row["id"])
    scenario["store"] = read_store(store_id)
    scenario["engagement"] = read_engagement(scenario["engagement"]["id"])
    return scenario


def setup_selling_engagement(store_specs=None, clock=BASE_CLOCK_UTC,
                             jurisdiction_overrides=None, engagement_overrides=None,
                             license_each=True):
    """A multi-store engagement carried to the selling floor.

    ``store_specs`` is a list of dicts, one per store, each optionally carrying
    ``store`` overrides, a ``lots`` list of lot override dicts and ``license``
    overrides.  Returns a dict with ``jurisdiction``, ``engagement``, ``stores``,
    ``lots`` (one list per store) and ``licenses`` (one row per store, or None).
    """
    if store_specs is None:
        store_specs = [{}]
    pin_clock(clock)
    jurisdiction = create_jurisdiction(**(jurisdiction_overrides or {}))
    engagement = create_engagement(**(engagement_overrides or {}))
    stores, lots = [], []
    for index, spec in enumerate(store_specs, start=1):
        store_over = dict(spec.get("store") or {})
        store_over.setdefault("store_code", f"S-{9000 + index}")
        store_over.setdefault("address_line", f"{index} Liquidation Way")
        store = add_store(engagement["id"], jurisdiction["id"], **store_over)
        stores.append(store)
        lot_specs = spec.get("lots")
        if lot_specs is None:
            lot_specs = [{}]
        lots.append([add_inventory_lot(store["id"], **lot_over) for lot_over in lot_specs])
    submit_engagement(engagement["id"])
    engagement = approve_engagement(engagement["id"])
    licenses = []
    for index, (store, spec) in enumerate(zip(stores, store_specs), start=1):
        if not license_each:
            licenses.append(None)
            continue
        license_over = dict(spec.get("license") or {})
        license_over.setdefault("license_number", f"NY-GOB-{7000 + index}")
        license_row = apply_for_license(store["id"], **license_over)
        licenses.append(decide_license(license_row["id"]))
    return {
        "jurisdiction": jurisdiction,
        "engagement": read_engagement(engagement["id"]),
        "stores": [read_store(store["id"]) for store in stores],
        "lots": lots,
        "licenses": licenses,
    }


# ==========================================================================
# Tier 3: full lifecycle shortcuts
# ==========================================================================

def open_lease_disposition(store_id, **overrides):
    return get_success_data(
        api_client.create_lease_disposition(
            store_id, lease_disposition_payload(**overrides), CONSULTANT
        )
    )


def send_lease_offer(disposition_id, offered_surrender_payment_cents):
    return get_success_data(
        api_client.send_lease_offer(
            disposition_id,
            {"offered_surrender_payment_cents": offered_surrender_payment_cents},
            CONSULTANT,
        )
    )


def record_landlord_response(disposition_id, response, **extra):
    payload = {"response": response}
    payload.update(extra)
    return get_success_data(
        api_client.record_landlord_response(disposition_id, payload, CONSULTANT)
    )


def setup_agreed_lease(store_id, offered_surrender_payment_cents=300000, **overrides):
    """Open a disposition, send one offer and record the landlord's acceptance."""
    disposition = open_lease_disposition(store_id, **overrides)
    send_lease_offer(disposition["id"], offered_surrender_payment_cents)
    return record_landlord_response(disposition["id"], "ACCEPT")


def setup_rejected_lease(store_id, offered_surrender_payment_cents=300000, **overrides):
    """Open a disposition and drive it to the terminal REJECTED_FINAL reading."""
    disposition = open_lease_disposition(store_id, **overrides)
    send_lease_offer(disposition["id"], offered_surrender_payment_cents)
    return record_landlord_response(disposition["id"], "REJECT")


def surrender_lease(disposition_id, fixture_sale_price_cents, **extra):
    payload = {"fixture_sale_price_cents": fixture_sale_price_cents}
    payload.update(extra)
    return get_success_data(
        api_client.surrender_lease(disposition_id, payload, CONSULTANT)
    )


def open_settlement(engagement_id, settlement_basis="PROVISIONAL", **extra):
    """Open a worksheet, pinning the engagement's live version."""
    payload = {
        "settlement_basis": settlement_basis,
        "expected_engagement_version": engagement_version(engagement_id),
    }
    payload.update(extra)
    return get_success_data(
        api_client.create_settlement(engagement_id, payload, CONSULTANT)
    )


def propose_settlement(settlement_id):
    return get_success_data(api_client.propose_settlement(settlement_id, CONSULTANT))


def accept_settlement(settlement_id, responder=CONTROLLER):
    return get_success_data(
        api_client.respond_to_settlement(settlement_id, {"response": "ACCEPT"}, responder)
    )


def dispute_settlement(settlement_id, dispute_reason="fee band disputed",
                       responder=CONTROLLER):
    return get_success_data(
        api_client.respond_to_settlement(
            settlement_id,
            {"response": "DISPUTE", "dispute_reason": dispute_reason},
            responder,
        )
    )


def finalize_settlement(settlement_id):
    return get_success_data(api_client.finalize_settlement(settlement_id, CONSULTANT))


def setup_proposed_settlement(engagement_id, settlement_basis="PROVISIONAL", **extra):
    worksheet = open_settlement(engagement_id, settlement_basis, **extra)
    return propose_settlement(worksheet["id"])


def setup_accepted_settlement(engagement_id, settlement_basis="PROVISIONAL", **extra):
    worksheet = setup_proposed_settlement(engagement_id, settlement_basis, **extra)
    return accept_settlement(worksheet["id"])


# ==========================================================================
# Tier 4: accumulation / threshold targeting
# ==========================================================================

def setup_store_with_posted_day(day_overrides=None, **kwargs):
    """A selling store with one posted selling day, so realized figures move."""
    scenario = setup_selling_store(**kwargs)
    scenario["sales_day"] = post_sales_day(
        scenario["store"]["id"], **(day_overrides or {})
    )
    scenario["store"] = read_store(scenario["store"]["id"])
    scenario["engagement"] = read_engagement(scenario["engagement"]["id"])
    return scenario


def setup_store_with_cadence(stage_specs, **kwargs):
    """A selling store carrying an authored markdown cadence.

    ``stage_specs`` is a list of markdown-stage override dicts authored in order.
    Returns the ``setup_selling_store`` dict plus ``stages``.
    """
    scenario = setup_selling_store(**kwargs)
    scenario["stages"] = [
        add_markdown_stage(scenario["store"]["id"], **spec) for spec in stage_specs
    ]
    scenario["store"] = read_store(scenario["store"]["id"])
    return scenario


def setup_engagement_with_strikes(strike_count, selling_store_count=1,
                                  clock=BASE_CLOCK_UTC, jurisdiction_overrides=None,
                                  engagement_overrides=None):
    """An engagement whose compliance strike counter has been driven to a value.

    Each strike is a genuine licence revocation against its own store, so the
    stores whose licences were revoked end up ``SUSPENDED`` while
    ``selling_store_count`` further stores stay on the selling floor.  Returns a
    dict with ``jurisdiction``, ``engagement``, ``selling_stores``,
    ``struck_stores`` and ``licenses``.
    """
    total = strike_count + selling_store_count
    scenario = setup_selling_engagement(
        store_specs=[{} for _ in range(total)],
        clock=clock,
        jurisdiction_overrides=jurisdiction_overrides,
        engagement_overrides=engagement_overrides,
    )
    selling_stores = scenario["stores"][:selling_store_count]
    struck_stores = scenario["stores"][selling_store_count:]
    for index, store in enumerate(struck_stores, start=1):
        license_row = scenario["licenses"][selling_store_count + index - 1]
        revoke_license(license_row["id"], f"signage violation {index}")
    return {
        "jurisdiction": scenario["jurisdiction"],
        "engagement": read_engagement(scenario["engagement"]["id"]),
        "selling_stores": [read_store(store["id"]) for store in selling_stores],
        "struck_stores": [read_store(store["id"]) for store in struck_stores],
        "licenses": scenario["licenses"],
        "lots": scenario["lots"],
    }


def setup_store_with_received_consignment(consignment_overrides=None,
                                          disclosure_reference="NY-DISC-1", **kwargs):
    """A selling store holding one received augmentation consignment.

    The jurisdiction's licence declares the augmented-merchandise disclosure
    claim so the receipt's advertising precondition is satisfied.
    """
    kwargs.setdefault("license_overrides", {
        "advertising_claim_codes": [
            "EVERYTHING_MUST_GO", "AUGMENTED_MERCHANDISE_DISCLOSURE",
        ],
    })
    scenario = setup_selling_store(**kwargs)
    scenario["consignment"] = propose_disclose_and_receive_consignment(
        scenario["store"]["id"], disclosure_reference,
        **(consignment_overrides or {})
    )
    scenario["store"] = read_store(scenario["store"]["id"])
    return scenario


# ==========================================================================
# Tier 5: finalization / terminal state
# ==========================================================================

def setup_wind_down_engagement(store_specs=None, **kwargs):
    """An engagement in WIND_DOWN with every store CLOSED.

    Returns the ``setup_selling_engagement`` dict with ``engagement`` and
    ``stores`` re-read after the closures.
    """
    scenario = setup_selling_engagement(store_specs=store_specs, **kwargs)
    for store in scenario["stores"]:
        close_store(store["id"])
    scenario["engagement"] = wind_down_engagement(scenario["engagement"]["id"])
    scenario["stores"] = [read_store(store["id"]) for store in scenario["stores"]]
    return scenario


def setup_lease_disposed_wind_down(store_specs=None, **kwargs):
    """A WIND_DOWN engagement where every store's lease reached REJECTED_FINAL.

    This is the cheapest state satisfying the final settlement's lease-disposal
    precondition, because a rejected negotiation never blocks the close.
    """
    scenario = setup_wind_down_engagement(store_specs=store_specs, **kwargs)
    scenario["dispositions"] = [
        setup_rejected_lease(store["id"]) for store in scenario["stores"]
    ]
    scenario["engagement"] = read_engagement(scenario["engagement"]["id"])
    return scenario


def setup_finalizable_settlement(store_specs=None, **kwargs):
    """A WIND_DOWN engagement carrying an ACCEPTED settlement on a FINAL basis.

    Every store is CLOSED and every lease has reached REJECTED_FINAL, so the only
    thing left is the finalize call itself.
    """
    scenario = setup_lease_disposed_wind_down(store_specs=store_specs, **kwargs)
    scenario["settlement"] = setup_accepted_settlement(
        scenario["engagement"]["id"], "FINAL"
    )
    scenario["engagement"] = read_engagement(scenario["engagement"]["id"])
    return scenario


def setup_surrendered_store(fixture_sale_price_cents=600000, lease_overrides=None,
                            surrender_clock=None, **kwargs):
    """One store carried all the way to SURRENDERED through the waterfall.

    The jurisdiction is created with a zero-day surrender notice so possession
    may be delivered on the very day the landlord accepted.
    """
    jurisdiction_overrides = dict(kwargs.pop("jurisdiction_overrides", None) or {})
    jurisdiction_overrides.setdefault("surrender_notice_days", 0)
    scenario = setup_selling_store(
        jurisdiction_overrides=jurisdiction_overrides, **kwargs
    )
    close_store(scenario["store"]["id"])
    disposition = setup_agreed_lease(
        scenario["store"]["id"], **(lease_overrides or {})
    )
    if surrender_clock is not None:
        pin_clock(surrender_clock)
    scenario["disposition"] = surrender_lease(
        disposition["id"], fixture_sale_price_cents
    )
    scenario["store"] = read_store(scenario["store"]["id"])
    scenario["engagement"] = read_engagement(scenario["engagement"]["id"])
    return scenario


# ==========================================================================
# Store-manager identity threading
# ==========================================================================

def store_manager_headers(store):
    """Headers for the manager of ``store``; accepts a store row or a store id."""
    store_id = store["id"] if isinstance(store, dict) else store
    return make_store_manager_headers(store_id)
