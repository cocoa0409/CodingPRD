"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only.

Identity threading: CustomerOperator calls are entity-backed by Customer, so
every customer-side call uses make_customer_operator_headers(customer["id"]).
OCC-guarded calls (agreement activate, format activate, cycle settle) always
re-read the parent's current version immediately before the guarded write.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_agreement_payload,
    create_availability_schedule_payload,
    create_bank_payload,
    create_batch_payload,
    create_customer_payload,
    create_error_credit_request_payload,
    create_image_request_payload,
    create_item_payload,
    create_site_payload,
    create_sla_incident_payload,
    create_transmission_format_payload,
    raise_exception_payload,
)
from .test_users import (
    TEST_USERS,
    make_activator_headers,
    make_customer_operator_headers,
    make_implementer_headers,
    make_lockbox_operator_headers,
)

ADMIN = TEST_USERS["bank_admin_headers"]
IMPLEMENTER = TEST_USERS["implementer_headers"]
ACTIVATOR = TEST_USERS["activator_headers"]
LOCK_OP = TEST_USERS["lockbox_op_headers"]        # lock-op-1
LOCK_OP2 = TEST_USERS["lockbox_op2_headers"]      # lock-op-2 (closer != capturer)
BILLING_SPEC = TEST_USERS["billing_specialist_headers"]
BILLING_APPR = TEST_USERS["billing_approver_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation and simple transitions
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    """Move the server's logical clock (PRD §2.5)."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_bank(**overrides):
    return get_success_data(api_client.create_bank(create_bank_payload(**overrides),
                                                   ADMIN))


def create_customer(bank_id, **overrides):
    return get_success_data(
        api_client.create_customer(bank_id, create_customer_payload(**overrides),
                                   IMPLEMENTER))


def begin_onboarding(bank_id, customer_id):
    return get_success_data(api_client.begin_onboarding(bank_id, customer_id,
                                                        IMPLEMENTER))


def create_agreement(bank_id, customer_id, **overrides):
    return get_success_data(
        api_client.create_agreement(bank_id, customer_id,
                                    create_agreement_payload(**overrides),
                                    IMPLEMENTER))


def implement_agreement(bank_id, customer_id, agreement_id,
                        implementer_id="impl-user-1"):
    return get_success_data(
        api_client.implement_agreement(bank_id, customer_id, agreement_id,
                                       make_implementer_headers(implementer_id)))


def get_agreement(bank_id, customer_id, agreement_id):
    return get_success_data(
        api_client.get_agreement(bank_id, customer_id, agreement_id, ADMIN))


def activate_agreement(bank_id, customer_id, agreement_id, activator_id="act-user-1"):
    """IMPLEMENTED → ACTIVE. Re-reads the agreement version for the OCC token."""
    current = get_agreement(bank_id, customer_id, agreement_id)
    return get_success_data(
        api_client.activate_agreement(bank_id, customer_id, agreement_id,
                                      current["version"],
                                      make_activator_headers(activator_id)))


def create_transmission_format(bank_id, customer_id, agreement_id, **overrides):
    return get_success_data(
        api_client.create_transmission_format(
            bank_id, customer_id, agreement_id,
            create_transmission_format_payload(**overrides), IMPLEMENTER))


def activate_transmission_format(bank_id, customer_id, agreement_id, format_id,
                                 activator_id="act-user-1"):
    """DRAFT → ACTIVE. The parent agreement's version is the OCC token."""
    current = get_agreement(bank_id, customer_id, agreement_id)
    return get_success_data(
        api_client.activate_transmission_format(
            bank_id, customer_id, agreement_id, format_id, current["version"],
            make_activator_headers(activator_id)))


def get_transmission_format(bank_id, customer_id, agreement_id, format_id):
    return get_success_data(
        api_client.get_transmission_format(bank_id, customer_id, agreement_id,
                                           format_id, ADMIN))


def create_site(bank_id, customer_id, agreement_id, **overrides):
    return get_success_data(
        api_client.create_site(bank_id, customer_id, agreement_id,
                               create_site_payload(**overrides), IMPLEMENTER))


def add_availability_schedule(bank_id, customer_id, agreement_id, site_id,
                              **overrides):
    return get_success_data(
        api_client.create_availability_schedule(
            bank_id, customer_id, agreement_id, site_id,
            create_availability_schedule_payload(**overrides), IMPLEMENTER))


def go_live_site(bank_id, customer_id, agreement_id, site_id,
                 activator_id="act-user-1"):
    return get_success_data(
        api_client.go_live_site(bank_id, customer_id, agreement_id, site_id,
                                make_activator_headers(activator_id)))


# ---------------------------------------------------------------------------
# Tier 2: the lockbox workspace (bank → customer → agreement → site)
# ---------------------------------------------------------------------------

def setup_active_agreement(bank_overrides=None, agreement_overrides=None,
                           customer_overrides=None):
    """Bank + customer onboarded + agreement IMPLEMENTED → ACTIVE.

    Activation flips the customer ONBOARDING → ACTIVE. Returns a workspace
    dict: bank, customer, agreement (freshly re-read after activation).
    """
    bank = create_bank(**(bank_overrides or {}))
    customer = create_customer(bank["id"], **(customer_overrides or {}))
    begin_onboarding(bank["id"], customer["id"])
    agreement = create_agreement(bank["id"], customer["id"],
                                 **(agreement_overrides or {}))
    implement_agreement(bank["id"], customer["id"], agreement["id"])
    activate_agreement(bank["id"], customer["id"], agreement["id"])
    agreement = get_agreement(bank["id"], customer["id"], agreement["id"])
    return {"bank": bank, "customer": customer, "agreement": agreement,
            "format": None, "site": None, "schedule": None}


def setup_live_lockbox(bank_overrides=None, agreement_overrides=None,
                       customer_overrides=None, site_overrides=None,
                       schedule_specs=None, with_format=True, with_schedule=True,
                       go_live=True):
    """Active agreement plus (optionally) an ACTIVE transmission format, a
    LockboxSite, ACTIVE availability schedules, and go_live.

    schedule_specs: list of per-schedule override dicts. When None and
    with_schedule is true, one SAME_DAY schedule for pattern '0710' is added.
    Returns a workspace dict.
    """
    ws = setup_active_agreement(bank_overrides=bank_overrides,
                                agreement_overrides=agreement_overrides,
                                customer_overrides=customer_overrides)
    b_id = ws["bank"]["id"]
    c_id = ws["customer"]["id"]
    a_id = ws["agreement"]["id"]

    if with_format:
        fmt = create_transmission_format(b_id, c_id, a_id)
        ws["format"] = activate_transmission_format(b_id, c_id, a_id, fmt["id"])
        ws["agreement"] = get_agreement(b_id, c_id, a_id)

    ws["site"] = create_site(b_id, c_id, a_id, **(site_overrides or {}))
    s_id = ws["site"]["id"]

    if with_schedule:
        specs = schedule_specs if schedule_specs is not None else [{}]
        for spec in specs:
            ws["schedule"] = add_availability_schedule(b_id, c_id, a_id, s_id,
                                                       **spec)

    if go_live:
        ws["site"] = go_live_site(b_id, c_id, a_id, s_id)
    return ws


def ws_ids(ws):
    """(bank_id, customer_id, agreement_id, site_id) shorthand."""
    return (ws["bank"]["id"], ws["customer"]["id"], ws["agreement"]["id"],
            ws["site"]["id"])


def add_live_customer_to_bank(bank, customer_overrides=None,
                              agreement_overrides=None, site_code="LBX-01"):
    """Attach a second full pipeline (customer → ACTIVE agreement → ACTIVE
    format → LIVE site with one SAME_DAY schedule) to an existing bank.
    Returns a workspace dict keyed like setup_live_lockbox's."""
    customer = create_customer(bank["id"], **(customer_overrides or {}))
    begin_onboarding(bank["id"], customer["id"])
    agreement = create_agreement(bank["id"], customer["id"],
                                 **(agreement_overrides or {}))
    implement_agreement(bank["id"], customer["id"], agreement["id"])
    activate_agreement(bank["id"], customer["id"], agreement["id"])
    fmt = create_transmission_format(bank["id"], customer["id"], agreement["id"])
    fmt = activate_transmission_format(bank["id"], customer["id"],
                                       agreement["id"], fmt["id"])
    site = create_site(bank["id"], customer["id"], agreement["id"],
                       site_code=site_code)
    schedule = add_availability_schedule(bank["id"], customer["id"],
                                         agreement["id"], site["id"])
    site = go_live_site(bank["id"], customer["id"], agreement["id"], site["id"])
    return {"bank": bank, "customer": customer,
            "agreement": get_agreement(bank["id"], customer["id"],
                                       agreement["id"]),
            "format": fmt, "site": site, "schedule": schedule}


# ---------------------------------------------------------------------------
# Tier 3: remittance batch lifecycle
# ---------------------------------------------------------------------------

def create_batch(ws, operator_id="lock-op-1", **overrides):
    b_id, c_id, a_id, s_id = ws_ids(ws)
    return get_success_data(
        api_client.create_batch(b_id, c_id, a_id, s_id,
                                create_batch_payload(**overrides),
                                make_lockbox_operator_headers(operator_id)))


def get_batch(ws, batch_id):
    b_id, c_id, a_id, s_id = ws_ids(ws)
    return get_success_data(
        api_client.get_batch(b_id, c_id, a_id, s_id, batch_id, ADMIN))


def begin_capture(ws, batch_id, operator_id="lock-op-1"):
    b_id, c_id, a_id, s_id = ws_ids(ws)
    return get_success_data(
        api_client.begin_capture(b_id, c_id, a_id, s_id, batch_id,
                                 make_lockbox_operator_headers(operator_id)))


def capture_item(ws, batch_id, operator_id="lock-op-1", **overrides):
    b_id, c_id, a_id, s_id = ws_ids(ws)
    return get_success_data(
        api_client.create_item(b_id, c_id, a_id, s_id, batch_id,
                               create_item_payload(**overrides),
                               make_lockbox_operator_headers(operator_id)))


def accept_item(ws, batch_id, item_id, operator_id="lock-op-1"):
    b_id, c_id, a_id, s_id = ws_ids(ws)
    return get_success_data(
        api_client.accept_item(b_id, c_id, a_id, s_id, batch_id, item_id,
                               make_lockbox_operator_headers(operator_id)))


def return_item(ws, batch_id, item_id, operator_id="lock-op-1"):
    b_id, c_id, a_id, s_id = ws_ids(ws)
    return get_success_data(
        api_client.return_item(b_id, c_id, a_id, s_id, batch_id, item_id,
                               make_lockbox_operator_headers(operator_id)))


def raise_exception(ws, batch_id, item_id, operator_id="lock-op-1", **overrides):
    b_id, c_id, a_id, s_id = ws_ids(ws)
    return get_success_data(
        api_client.raise_exception(b_id, c_id, a_id, s_id, batch_id, item_id,
                                   raise_exception_payload(**overrides),
                                   make_lockbox_operator_headers(operator_id)))


def balance_batch(ws, batch_id, operator_id="lock-op-1"):
    b_id, c_id, a_id, s_id = ws_ids(ws)
    return api_client.balance_batch(b_id, c_id, a_id, s_id, batch_id,
                                    make_lockbox_operator_headers(operator_id))


def balance_batch_ok(ws, batch_id, operator_id="lock-op-1"):
    return get_success_data(balance_batch(ws, batch_id, operator_id))


def close_batch(ws, batch_id, operator_id="lock-op-2"):
    """BALANCED → CLOSED. Default closer differs from the default capturer."""
    b_id, c_id, a_id, s_id = ws_ids(ws)
    return get_success_data(
        api_client.close_batch(b_id, c_id, a_id, s_id, batch_id,
                               make_lockbox_operator_headers(operator_id)))


def transmit_batch(ws, batch_id, operator_id="lock-op-1"):
    b_id, c_id, a_id, s_id = ws_ids(ws)
    return get_success_data(
        api_client.transmit_batch(b_id, c_id, a_id, s_id, batch_id,
                                  make_lockbox_operator_headers(operator_id)))


def acknowledge_transmission(ws, batch_id):
    b_id, c_id, a_id, s_id = ws_ids(ws)
    return get_success_data(
        api_client.acknowledge_transmission(
            b_id, c_id, a_id, s_id, batch_id,
            make_customer_operator_headers(c_id)))


def capture_and_accept_items(ws, batch_id, count, amount_cents,
                             routing=TEST_DEFAULTS["PAYER_ROUTING"],
                             check_prefix="chk"):
    """Capture `count` items of `amount_cents` each and accept every one.
    Returns the list of accepted items."""
    accepted = []
    for i in range(count):
        item = capture_item(ws, batch_id,
                            check_number=f"{check_prefix}-{i + 1}",
                            payer_routing_number=routing,
                            amount_cents=amount_cents)
        accepted.append(accept_item(ws, batch_id, item["id"]))
    return accepted


def settle_batch(ws, batch_id):
    """Walk a CLOSED batch through transmission and acknowledgement so the
    business-day close can settle it."""
    transmit_batch(ws, batch_id)
    acknowledge_transmission(ws, batch_id)


# ---------------------------------------------------------------------------
# Tier 3b: exceptions and image requests
# ---------------------------------------------------------------------------

def get_exception(ws, exception_id):
    return get_success_data(
        api_client.get_exception_item(ws["bank"]["id"], ws["customer"]["id"],
                                      exception_id, ADMIN))


def decide_exception(ws, exception_id, decision):
    c_id = ws["customer"]["id"]
    return api_client.decide_exception(ws["bank"]["id"], c_id, exception_id,
                                       decision,
                                       make_customer_operator_headers(c_id))


def decide_exception_ok(ws, exception_id, decision):
    return get_success_data(decide_exception(ws, exception_id, decision))


def escalate_exception(ws, exception_id):
    c_id = ws["customer"]["id"]
    return get_success_data(
        api_client.escalate_exception(ws["bank"]["id"], c_id, exception_id,
                                      make_customer_operator_headers(c_id)))


def create_image_request(ws, item_id, **overrides):
    c_id = ws["customer"]["id"]
    return api_client.create_image_request(
        ws["bank"]["id"], c_id,
        create_image_request_payload(item_id, **overrides),
        make_customer_operator_headers(c_id))


def fulfill_image_request(ws, request_id, operator_id="lock-op-1"):
    return get_success_data(
        api_client.fulfill_image_request(ws["bank"]["id"], ws["customer"]["id"],
                                         request_id,
                                         make_lockbox_operator_headers(operator_id)))


# ---------------------------------------------------------------------------
# Tier 4: business-day / analysis-cycle checkpoints
# ---------------------------------------------------------------------------

def run_close_business_day(ws):
    return get_success_data(
        api_client.close_business_day(ws["bank"]["id"], ADMIN))


def run_close_analysis_cycle(ws, customer_id=None, specialist_id="billing-spec-1"):
    from .test_users import make_billing_specialist_headers
    return get_success_data(
        api_client.close_analysis_cycle(ws["bank"]["id"],
                                        make_billing_specialist_headers(specialist_id),
                                        customer_id=customer_id))


def run_close_analysis_cycle_at_month_end(ws, customer_id=None,
                                          specialist_id="billing-spec-1"):
    """Close the analysis cycle the way PRD §3.7 gates it: a customer's OPEN
    cycle moves to FINALIZED only "when its `cycle_end_date` equals the bank's
    current business date". Advance the business date (one business day per
    close) until that gate holds for every targeted OPEN cycle, then run the
    close. When customer_id is None the advance covers every customer in the
    bank."""
    bank_id = ws["bank"]["id"]
    while True:
        bank = get_success_data(api_client.get_bank(bank_id, ADMIN))
        cur = bank["current_business_date"]
        if customer_id is not None:
            cids = [customer_id]
        else:
            data, _meta = validate_paginated(
                api_client.list_customers(bank_id, ADMIN))
            cids = [c["id"] for c in data]
        pending_end = None
        for cid in cids:
            data, _meta = validate_paginated(
                api_client.list_analysis_cycles(bank_id, cid, ADMIN))
            for cyc in data:
                if cyc["status"] == "OPEN" and cyc["cycle_end_date"] > cur:
                    if pending_end is None or cyc["cycle_end_date"] > pending_end:
                        pending_end = cyc["cycle_end_date"]
        if pending_end is None:
            break
        run_close_business_day({"bank": bank})
    return run_close_analysis_cycle(ws, customer_id=customer_id,
                                    specialist_id=specialist_id)


def list_cycles(ws):
    data, _meta = validate_paginated(
        api_client.list_analysis_cycles(ws["bank"]["id"], ws["customer"]["id"],
                                        BILLING_SPEC))
    return data


def get_cycle(ws, cycle_id):
    return get_success_data(
        api_client.get_analysis_cycle(ws["bank"]["id"], ws["customer"]["id"],
                                      cycle_id, BILLING_SPEC))


def list_line_items(ws, cycle_id):
    data, _meta = validate_paginated(
        api_client.list_line_items(ws["bank"]["id"], ws["customer"]["id"],
                                   cycle_id, BILLING_SPEC))
    return data


def settle_cycle(ws, cycle_id, specialist_id="billing-spec-1"):
    """FINALIZED|DISPUTED → SETTLED. Re-reads the cycle version (OCC)."""
    from .test_users import make_billing_specialist_headers
    current = get_cycle(ws, cycle_id)
    return get_success_data(
        api_client.settle_analysis_cycle(ws["bank"]["id"], ws["customer"]["id"],
                                         cycle_id, current["version"],
                                         make_billing_specialist_headers(specialist_id)))


def report_incident(ws, specialist=False, **overrides):
    c_id = ws["customer"]["id"]
    headers = (TEST_USERS["billing_specialist_headers"] if specialist
               else make_customer_operator_headers(c_id))
    return get_success_data(
        api_client.create_sla_incident(ws["bank"]["id"], c_id,
                                       create_sla_incident_payload(**overrides),
                                       headers))


def confirm_incident(ws, incident_id):
    return get_success_data(
        api_client.confirm_sla_incident(ws["bank"]["id"], ws["customer"]["id"],
                                        incident_id, BILLING_SPEC))


def file_error_credit(ws, cycle_id, **overrides):
    c_id = ws["customer"]["id"]
    return get_success_data(
        api_client.create_error_credit_request(
            ws["bank"]["id"], c_id,
            create_error_credit_request_payload(cycle_id, **overrides),
            make_customer_operator_headers(c_id)))
