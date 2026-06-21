"""Composite setup helpers for multi-step test prerequisites.

The database is empty before every test (the runner restarts the server per
test), so every fixture builds its preconditions from scratch using only
PRD-declared endpoints. Setup calls use get_success_data() (lenient validator)
so a broken setup raises a clear "Setup step failed" error.

Identity threading: the Customer role is entity_backed, so every ownership-gated
call uses make_customer_headers(customer["id"]) — never the shared constant
(PRD §2.1).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_bureau_payload, create_customer_payload, create_material_payload,
    create_machine_payload, create_spool_payload, create_print_file_payload,
    create_order_payload, create_order_line_payload, create_finishing_task_payload,
    create_print_run_payload, create_shipment_payload,
)
from .constants import TEST_DEFAULTS, FILE_A, FILE_B
from .test_users import TEST_USERS, make_customer_headers

ADMIN = TEST_USERS["bureau_admin_headers"]
OPERATOR = TEST_USERS["operator_headers"]
QA = TEST_USERS["qa_reviewer_headers"]


# ─── Tier 0: atomic builders ──────────────────────────

def create_bureau(**overrides):
    """Create a bureau (BureauAdmin)."""
    return get_success_data(api_client.create_bureau(create_bureau_payload(**overrides), ADMIN))


def create_funded_customer(bureau_id, amount_cents=TEST_DEFAULTS["BIG_DEPOSIT_CENTS"],
                           **overrides):
    """Register a customer and deposit `amount_cents` into the wallet.
    Pass amount_cents=0 to skip the deposit."""
    cust = get_success_data(
        api_client.create_customer(create_customer_payload(bureau_id, **overrides), ADMIN))
    if amount_cents and amount_cents > 0:
        cust = get_success_data(
            api_client.deposit(cust["id"], {"amount_cents": amount_cents}, ADMIN))
    return cust


def create_material(bureau_id, **overrides):
    return get_success_data(
        api_client.create_material(create_material_payload(bureau_id, **overrides), ADMIN))


def create_machine(bureau_id, **overrides):
    return get_success_data(
        api_client.create_machine(create_machine_payload(bureau_id, **overrides), ADMIN))


def create_spool(bureau_id, material_id, **overrides):
    return get_success_data(
        api_client.create_spool(create_spool_payload(bureau_id, material_id, **overrides), ADMIN))


def upload_file(bureau_id, customer_id, geometry=None, **overrides):
    """Upload a print file as the owning Customer (entity_backed identity)."""
    return get_success_data(api_client.create_print_file(
        create_print_file_payload(bureau_id, customer_id, geometry=geometry, **overrides),
        make_customer_headers(customer_id)))


def upload_and_check_file(bureau_id, customer_id, material_id, geometry=None, **overrides):
    """Upload a file then run the QAReviewer printability check. Returns the
    checked file (status PRINTABLE/FLAGGED/REJECTED depending on geometry)."""
    f = upload_file(bureau_id, customer_id, geometry=geometry, **overrides)
    checked = get_success_data(
        api_client.check_print_file(f["id"], {"material_id": material_id}, QA))
    return checked


# ─── Tier 1: catalogue base ───────────────────────────

def setup_catalogue(funded=True, deposit=TEST_DEFAULTS["BIG_DEPOSIT_CENTS"],
                    spool_grams=1000, shift_capacity_minutes=None,
                    cooldown_buffer_min=None, with_spool=True, with_machine=True):
    """Bureau + funded customer + SLA material (+ machine + spool).

    Returns a dict with keys: bureau, customer, material, machine (or None),
    spool (or None), cust_headers.
    """
    bkw = {}
    if shift_capacity_minutes is not None:
        bkw["shift_capacity_minutes"] = shift_capacity_minutes
    if cooldown_buffer_min is not None:
        bkw["cooldown_buffer_min"] = cooldown_buffer_min
    bureau = create_bureau(**bkw)
    customer = create_funded_customer(bureau["id"], amount_cents=(deposit if funded else 0))
    material = create_material(bureau["id"])
    machine = create_machine(bureau["id"]) if with_machine else None
    spool = create_spool(bureau["id"], material["id"], grams_total=spool_grams) if with_spool else None
    return {
        "bureau": bureau,
        "customer": customer,
        "material": material,
        "machine": machine,
        "spool": spool,
        "cust_headers": make_customer_headers(customer["id"]),
    }


# ─── Tier 2: order assembly ───────────────────────────

def add_line(env, file_id, layer_height_mm=0.10, quantity=1, **overrides):
    """Attach an order line; the order id is read from env['order']."""
    return get_success_data(api_client.create_order_line(
        create_order_line_payload(env["order"]["id"], file_id, env["material"]["id"],
                                  layer_height_mm=layer_height_mm, quantity=quantity,
                                  **overrides),
        env["cust_headers"]))


def setup_order_with_line(geometry=None, layer_height_mm=0.10, quantity=1,
                          lead_tier="STANDARD", check_file=True, spool_grams=1000,
                          shift_capacity_minutes=None, deposit=TEST_DEFAULTS["BIG_DEPOSIT_CENTS"],
                          funded=True):
    """Catalogue + DRAFT order + one ACTIVE line over a (checked) print file.

    Defaults to File B (qty 1, layer 0.10) unless `geometry` overrides it.
    Returns env dict extended with: file, order, line.
    """
    geo = FILE_B if geometry is None else geometry
    env = setup_catalogue(funded=funded, deposit=deposit, spool_grams=spool_grams,
                          shift_capacity_minutes=shift_capacity_minutes)
    if check_file:
        f = upload_and_check_file(env["bureau"]["id"], env["customer"]["id"],
                                  env["material"]["id"], geometry=geo)
    else:
        f = upload_file(env["bureau"]["id"], env["customer"]["id"], geometry=geo)
    env["file"] = f
    order = get_success_data(api_client.create_order(
        create_order_payload(env["bureau"]["id"], env["customer"]["id"], lead_tier=lead_tier),
        env["cust_headers"]))
    env["order"] = order
    env["line"] = add_line(env, f["id"], layer_height_mm=layer_height_mm, quantity=quantity)
    return env


def quote_order(env):
    """Quote the env order; refresh env['order'] to the quoted snapshot."""
    env["order"] = get_success_data(api_client.quote_order(env["order"]["id"], env["cust_headers"]))
    return env["order"]


def confirm_order(env):
    """Quote (if needed) then confirm with the current version. Refreshes env['order']."""
    order = env["order"]
    if order["fulfillment_status"] == "DRAFT":
        order = quote_order(env)
    confirmed = get_success_data(api_client.confirm_order(
        order["id"], {"expected_order_version": order["version"]}, env["cust_headers"]))
    env["order"] = confirmed
    return confirmed


def setup_confirmed_order(geometry=None, layer_height_mm=0.10, quantity=1,
                          lead_tier="STANDARD", spool_grams=1000,
                          shift_capacity_minutes=None, deposit=TEST_DEFAULTS["BIG_DEPOSIT_CENTS"]):
    """Full path: catalogue + line + quote + confirm (CONFIRMED / ESCROWED).
    Returns env dict with file, order (confirmed), line."""
    env = setup_order_with_line(geometry=geometry, layer_height_mm=layer_height_mm,
                                quantity=quantity, lead_tier=lead_tier,
                                spool_grams=spool_grams,
                                shift_capacity_minutes=shift_capacity_minutes,
                                deposit=deposit)
    confirm_order(env)
    return env


# ─── Tier 3: production / run lifecycle ───────────────

def create_run(env, line=None, start_min=0, duration_min=24, machine=None, spool=None):
    """Create a QUEUED print run for env's line on env's machine+spool."""
    line = line or env["line"]
    machine = machine or env["machine"]
    spool = spool or env["spool"]
    return get_success_data(api_client.create_print_run(
        create_print_run_payload(line["id"], machine["id"], spool["id"],
                                 start_min=start_min, duration_min=duration_min),
        OPERATOR))


def setup_run_queued(geometry=None, layer_height_mm=0.10, quantity=1, duration_min=24,
                     spool_grams=1000, deposit=TEST_DEFAULTS["BIG_DEPOSIT_CENTS"]):
    """Confirmed order + one QUEUED run. Returns env with run."""
    env = setup_confirmed_order(geometry=geometry, layer_height_mm=layer_height_mm,
                                quantity=quantity, spool_grams=spool_grams, deposit=deposit)
    env["run"] = create_run(env, duration_min=duration_min)
    return env


def setup_run_printing(geometry=None, layer_height_mm=0.10, quantity=1, duration_min=24,
                       spool_grams=1000):
    """Confirmed order + QUEUED run started to PRINTING. Returns env with run (printing)."""
    env = setup_run_queued(geometry=geometry, layer_height_mm=layer_height_mm,
                           quantity=quantity, duration_min=duration_min, spool_grams=spool_grams)
    env["run"] = get_success_data(api_client.start_print_run(env["run"]["id"], OPERATOR))
    return env


def setup_run_failed(fail_cause, geometry=None, layer_height_mm=0.10, quantity=1,
                     duration_min=24, spool_grams=1000):
    """Confirmed order + run started + failed with `fail_cause`.
    The FORWARD provisional reprint charge has been applied. Returns env with
    run (FAILED, carrying run['version'])."""
    env = setup_run_printing(geometry=geometry, layer_height_mm=layer_height_mm,
                             quantity=quantity, duration_min=duration_min, spool_grams=spool_grams)
    env["run"] = get_success_data(
        api_client.fail_print_run(env["run"]["id"], {"fail_cause": fail_cause}, OPERATOR))
    return env


def adjudicate_run(env, machine=None, spool=None, start_min=30, duration_min=24):
    """Adjudicate the failed env run with its current version. Refreshes env['run']."""
    machine = machine or env["machine"]
    spool = spool or env["spool"]
    payload = {
        "expected_run_version": env["run"]["version"],
        "machine_id": machine["id"],
        "spool_id": spool["id"],
        "start_min": start_min,
        "duration_min": duration_min,
    }
    env["run"] = get_success_data(api_client.adjudicate_print_run(env["run"]["id"], payload, QA))
    return env["run"]


def get_reprint_line(env, failed_line=None):
    """Fetch the reprint OrderLine spawned for the failed line (reprint_of_line_id)."""
    failed_line = failed_line or env["line"]
    data, _ = _list(api_client.list_order_lines(QA, params={
        "order_id": env["order"]["id"], "reprint_of_line_id": failed_line["id"]}))
    return data[0] if data else None


def _list(response):
    body = response.json()
    return body.get("data", []), body.get("meta", {})


# ─── Tier 4: finishing / shipment ─────────────────────

def add_finishing_task(env, line=None, kind="SUPPORT_REMOVAL", addon_cents=500,
                       station_start_min=0, station_duration_min=10):
    """Attach a finishing task to a line (as Operator)."""
    line = line or env["line"]
    return get_success_data(api_client.create_finishing_task(
        create_finishing_task_payload(line["id"], kind=kind, addon_cents=addon_cents,
                                      station_start_min=station_start_min,
                                      station_duration_min=station_duration_min),
        OPERATOR))


def create_shipment(env, carrier="UPS", tracking_number="1Z999"):
    """Create a CREATED shipment for env's order (as Operator)."""
    return get_success_data(api_client.create_shipment(
        create_shipment_payload(env["order"]["id"], carrier=carrier,
                                tracking_number=tracking_number),
        OPERATOR))


def setup_ready_order_with_shipment(geometry=None, layer_height_mm=0.10, quantity=1,
                                    duration_min=24, spool_grams=1000):
    """Confirmed order, single run started+completed (-> READY, no finishing),
    plus a CREATED shipment. Returns env with run (done), shipment, and a
    refreshed env['order'] (READY/ESCROWED)."""
    env = setup_run_printing(geometry=geometry, layer_height_mm=layer_height_mm,
                             quantity=quantity, duration_min=duration_min, spool_grams=spool_grams)
    env["run"] = get_success_data(api_client.complete_print_run(env["run"]["id"], OPERATOR))
    env["shipment"] = create_shipment(env)
    env["order"] = get_success_data(api_client.get_order(env["order"]["id"], OPERATOR))
    return env


def refresh_order(env, headers=None):
    env["order"] = get_success_data(
        api_client.get_order(env["order"]["id"], headers or OPERATOR))
    return env["order"]


def refresh_customer(env):
    return get_success_data(api_client.get_customer(env["customer"]["id"], ADMIN))


def refresh_spool(env, spool=None):
    spool = spool or env["spool"]
    return get_success_data(api_client.get_spool(spool["id"], OPERATOR))


def refresh_machine(env, machine=None):
    machine = machine or env["machine"]
    return get_success_data(api_client.get_machine(machine["id"], OPERATOR))
