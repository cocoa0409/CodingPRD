"""Composite setup helpers (PRD §3 workflows).

Every helper builds its preconditions from scratch using only PRD-declared
endpoints; each test starts against an empty database. Setup calls use the
lenient get_success_data() so failures surface as clear "Setup failed" errors.
DELETE returns 204 with no body (PRD §4), so removal is checked by status code.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK_ISO
from .factories import (
    create_account_payload,
    create_batch_payload,
    create_item_payload,
    create_listing_payload,
    create_manifest_payload,
    create_policy_payload,
    create_recycler_payload,
    create_sanitization_payload,
)
from .test_users import (
    TEST_USERS,
    make_account_manager_headers,
    make_compliance_officer_headers,
    make_destruction_technician_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]
INTAKE = TEST_USERS["intake_operator_headers"]
LOGISTICS = TEST_USERS["logistics_coordinator_headers"]


def am_headers(account) -> dict:
    """Ownership-gated AccountManager headers for this account (PRD §2.1)."""
    return make_account_manager_headers(account["id"])


# ---------------------------------------------------------------------------
# Tier 0: single-entity creation
# ---------------------------------------------------------------------------

def set_clock(to_iso8601=DEFAULT_CLOCK_ISO):
    """Advance the logical clock (PRD §2.9)."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def new_account(company_name="Test Co", contact_email="contact@test.example", **overrides):
    return get_success_data(
        api_client.create_account(create_account_payload(company_name, contact_email, **overrides), ADMIN)
    )


def new_active_policy(**overrides):
    """Create a policy with is_active=true (deactivates any previously active one)."""
    return get_success_data(api_client.create_compliance_policy(create_policy_payload(**overrides), ADMIN))


def new_recycler(**overrides):
    return get_success_data(api_client.create_recycler(create_recycler_payload(**overrides), OFFICER))


def new_manifest(
    account,
    mode="DROPOFF",
    declared_item_count=1,
    scheduled_start="2026-06-01T09:00:00Z",
    scheduled_end="2026-06-01T11:00:00Z",
    pickup_route=None,
    **overrides,
):
    payload = create_manifest_payload(
        account["id"],
        mode=mode,
        declared_item_count=declared_item_count,
        scheduled_start=scheduled_start,
        scheduled_end=scheduled_end,
        pickup_route=pickup_route,
        **overrides,
    )
    return get_success_data(api_client.create_manifest(payload, am_headers(account)))


# ---------------------------------------------------------------------------
# Tier 1: state progression
# ---------------------------------------------------------------------------

def schedule_manifest(manifest_id):
    return get_success_data(api_client.schedule_manifest(manifest_id, LOGISTICS))


def receive_manifest(manifest_id):
    return get_success_data(api_client.receive_manifest(manifest_id, INTAKE))


def reconcile_manifest(manifest_id):
    return get_success_data(api_client.reconcile_manifest(manifest_id, INTAKE))


def manifest_in_state(account, state, **kwargs):
    """Walk a manifest to DRAFT, SCHEDULED, or RECEIVED. Returns the manifest."""
    manifest = new_manifest(account, **kwargs)
    if state == "DRAFT":
        return manifest
    manifest = schedule_manifest(manifest["id"])
    if state == "SCHEDULED":
        return manifest
    manifest = receive_manifest(manifest["id"])
    if state == "RECEIVED":
        return manifest
    raise ValueError(f"manifest_in_state cannot reach {state}")


def scan_item(manifest_id, serial_number="SN-1", **item_overrides):
    return get_success_data(
        api_client.add_manifest_item(
            manifest_id, create_item_payload(serial_number=serial_number, **item_overrides), INTAKE
        )
    )


def triage_item(item_id, disposition):
    return get_success_data(api_client.triage_item(item_id, {"disposition": disposition}, INTAKE))


def scan_and_triage(manifest_id, disposition, serial_number="SN-1", **item_overrides):
    """Scan an item into a RECEIVED manifest, then route it. Returns post-triage item."""
    item = scan_item(manifest_id, serial_number=serial_number, **item_overrides)
    return triage_item(item["id"], disposition)


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy
# ---------------------------------------------------------------------------

def setup_received_manifest(account=None, declared_item_count=1, **manifest_kwargs):
    """Account (or the given one) + manifest driven to RECEIVED. Returns (account, manifest)."""
    if account is None:
        account = new_account()
    manifest = manifest_in_state(account, "RECEIVED", declared_item_count=declared_item_count, **manifest_kwargs)
    return account, manifest


def setup_triaged_item(account=None, disposition="RESALE", declared_item_count=1,
                       manifest_kwargs=None, **item_overrides):
    """RECEIVED manifest + one scanned, triaged item. Returns dict(account, manifest, item)."""
    account, manifest = setup_received_manifest(
        account, declared_item_count=declared_item_count, **(manifest_kwargs or {})
    )
    item = scan_and_triage(manifest["id"], disposition, **item_overrides)
    return {"account": account, "manifest": manifest, "item": item}


# ---------------------------------------------------------------------------
# Tier 3: resale lifecycle shortcuts
# ---------------------------------------------------------------------------

def list_item(item_id, asking_price_cents=60000, floor_price_cents=50000, channel="RETAIL"):
    return get_success_data(
        api_client.create_listing(
            create_listing_payload(item_id, asking_price_cents, floor_price_cents, channel), INTAKE
        )
    )


def sell_listing(listing_id, sale_price_cents):
    return get_success_data(api_client.sell_listing(listing_id, {"sale_price_cents": sale_price_cents}, INTAKE))


def setup_sold_item(account=None, sale_price_cents=60000, asking_price_cents=None, floor_price_cents=50000,
                    disposition="RESALE", manifest_kwargs=None, **item_overrides):
    """RECEIVED manifest + item triaged, listed, and sold.
    Returns dict(account, manifest, item, listing)."""
    ctx = setup_triaged_item(account, disposition=disposition,
                             manifest_kwargs=manifest_kwargs, **item_overrides)
    listing = list_item(ctx["item"]["id"], asking_price_cents or sale_price_cents, floor_price_cents)
    listing = sell_listing(listing["id"], sale_price_cents)
    ctx["listing"] = listing
    return ctx


def create_quote_settlement(manifest_id):
    """Read the manifest's current version, then create a QUOTE settlement under OCC."""
    manifest = get_success_data(api_client.get_manifest(manifest_id, INTAKE))
    return get_success_data(
        api_client.create_settlement(manifest_id, {"expected_manifest_version": manifest["version"]}, INTAKE)
    )


def setup_reconciled_sale(account=None, sale_price_cents=60000, manifest_kwargs=None, **item_overrides):
    """Sold item + manifest RECONCILED. Returns dict(account, manifest, item, listing)."""
    ctx = setup_sold_item(account, sale_price_cents=sale_price_cents,
                          manifest_kwargs=manifest_kwargs, **item_overrides)
    ctx["manifest"] = reconcile_manifest(ctx["manifest"]["id"])
    return ctx


def setup_quote_for_sale(account=None, sale_price_cents=60000, manifest_kwargs=None, **item_overrides):
    """Reconciled sale + QUOTE settlement. Adds 'settlement' to the context."""
    ctx = setup_reconciled_sale(account, sale_price_cents=sale_price_cents,
                                manifest_kwargs=manifest_kwargs, **item_overrides)
    ctx["settlement"] = create_quote_settlement(ctx["manifest"]["id"])
    return ctx


def setup_finalized_settlement(account=None, sale_price_cents=60000, manifest_kwargs=None, **item_overrides):
    """Full sale chain through settlement FINALIZED. Adds 'settlement' to the context."""
    ctx = setup_quote_for_sale(account, sale_price_cents=sale_price_cents,
                               manifest_kwargs=manifest_kwargs, **item_overrides)
    ctx["settlement"] = get_success_data(api_client.finalize_settlement(ctx["settlement"]["id"], ADMIN))
    return ctx


def setup_paid_settlement(account=None, sale_price_cents=60000, manifest_kwargs=None, **item_overrides):
    """Full sale chain through settlement PAID."""
    ctx = setup_finalized_settlement(account, sale_price_cents=sale_price_cents,
                                     manifest_kwargs=manifest_kwargs, **item_overrides)
    ctx["settlement"] = get_success_data(api_client.pay_settlement(ctx["settlement"]["id"], ADMIN))
    return ctx


def setup_closed_manifest(account=None, sale_price_cents=60000, **item_overrides):
    """Full lifecycle: sale settled, settlement PAID, manifest CLOSED."""
    ctx = setup_paid_settlement(account, sale_price_cents=sale_price_cents, **item_overrides)
    ctx["manifest"] = get_success_data(
        api_client.close_manifest(ctx["manifest"]["id"], am_headers(ctx["account"]))
    )
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: sanitization lifecycle
# ---------------------------------------------------------------------------

def log_sanitization(item_id, method="NIST_CLEAR", outcome="PASS", tech_id="tech-1"):
    return get_success_data(
        api_client.create_sanitization(
            item_id, create_sanitization_payload(method, outcome),
            make_destruction_technician_headers(tech_id),
        )
    )


def verify_sanitization_record(sanitization_id, verdict="APPROVE", officer_id="co-1"):
    return get_success_data(
        api_client.verify_sanitization(sanitization_id, {"verdict": verdict},
                                       make_compliance_officer_headers(officer_id))
    )


def setup_verified_data_item(account=None, method="NIST_PURGE", policy_overrides=None,
                             disposition="REFURB", **item_overrides):
    """Policy active + data-bearing item triaged, sanitized PASS, and VERIFIED.
    Returns dict(account, manifest, item, sanitization)."""
    new_active_policy(**(policy_overrides or {}))
    item_overrides.setdefault("data_bearing", True)
    ctx = setup_triaged_item(account, disposition=disposition, **item_overrides)
    record = log_sanitization(ctx["item"]["id"], method=method, outcome="PASS")
    record = verify_sanitization_record(record["id"], verdict="APPROVE")
    ctx["sanitization"] = record
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: recycle-batch lifecycle
# ---------------------------------------------------------------------------

def new_batch(recycler_id=None, scheduled_delivery_date="2026-06-10T00:00:00Z", is_export=False):
    return get_success_data(
        api_client.create_recycle_batch(
            create_batch_payload(scheduled_delivery_date, is_export, recycler_id), LOGISTICS
        )
    )


def add_to_batch(batch_id, item_id):
    return get_success_data(api_client.add_batch_item(batch_id, {"item_id": item_id}, LOGISTICS))


def remove_from_batch(batch_id, item_id):
    response = api_client.remove_batch_item(batch_id, item_id, LOGISTICS)
    assert response.status_code == 204, (
        f"Setup failed: expected 204 on batch item removal, got {response.status_code}: {response.text}"
    )


def ship_batch(batch_id):
    return get_success_data(api_client.ship_batch(batch_id, LOGISTICS))


def deliver_batch(batch_id):
    return get_success_data(api_client.deliver_batch(batch_id, OFFICER))


def process_batch(batch_id):
    return get_success_data(api_client.process_batch(batch_id, OFFICER))


def setup_batched_item(account=None, recycler=None, manifest_kwargs=None, **item_overrides):
    """Recycler + STAGING batch + one recycle-routed item added to the batch.
    Returns dict(account, manifest, item, recycler, batch)."""
    if recycler is None:
        recycler = new_recycler()
    item_overrides.setdefault("category", "OTHER")
    item_overrides.setdefault("declared_grade", "D")
    ctx = setup_triaged_item(account, disposition="RECYCLE",
                             manifest_kwargs=manifest_kwargs, **item_overrides)
    batch = new_batch(recycler_id=recycler["id"])
    batch = add_to_batch(batch["id"], ctx["item"]["id"])
    ctx.update({"recycler": recycler, "batch": batch})
    return ctx


def setup_processed_batch(account=None, recycler=None, item_weight_kg=3.0, **item_overrides):
    """Full downstream chain: item batched, batch shipped, delivered, PROCESSED.
    Returns dict(account, manifest, item, recycler, batch)."""
    ctx = setup_batched_item(account, recycler, weight_kg=item_weight_kg, **item_overrides)
    ship_batch(ctx["batch"]["id"])
    deliver_batch(ctx["batch"]["id"])
    ctx["batch"] = process_batch(ctx["batch"]["id"])
    return ctx
