"""Composite setup helpers.

Every helper takes the ApiClient as its first argument and builds its
preconditions from scratch using only PRD-declared endpoints, because the
server database is empty at the start of every test. Setup calls use the
lenient get_success_data() validator so setup failures surface clearly.
"""
from prd_bench_local_runner.testing import get_success_data
from .test_users import TEST_USERS, make_customer_headers

_ADMIN = TEST_USERS["admin_headers"]
_INTAKE = TEST_USERS["intake_headers"]
_LAB = TEST_USERS["lab_headers"]
_CLAIMS = TEST_USERS["claims_headers"]

_TYPE_TO_DECLARED = {
    "TAPE": "declared_tape_count",
    "FILM": "declared_film_count",
    "PHOTO": "declared_photo_count",
    "AUDIO": "declared_audio_count",
}

_MACHINE_KIND = {
    "TAPE": "TAPE_DECK",
    "FILM": "FILM_SCANNER",
    "PHOTO": "PHOTO_SCANNER",
    "AUDIO": "AUDIO_DECK",
}


def _counts_from_items(items):
    counts = {}
    for mt in items:
        key = _TYPE_TO_DECLARED[mt]
        counts[key] = counts.get(key, 0) + 1
    return counts


def _scan_payload(media_type, minutes=30, pages=10):
    if media_type == "PHOTO":
        return {"page_count": pages}
    return {"digitized_minutes": minutes}


# ---------------------------------------------------------------------------
# Low-level single-call helpers
# ---------------------------------------------------------------------------
def create_customer(api, email="cust@x.com", full_name="Test Customer", state_code="CA"):
    return get_success_data(
        api.create_customer(
            {"email": email, "full_name": full_name, "state_code": state_code}, _ADMIN
        )
    )


def create_order(
    api,
    customer_id,
    *,
    plan_tier="STANDARD_KIT",
    turnaround="STANDARD",
    output_option="CLOUD",
    protection=False,
    promo=None,
    declared=None,
    is_gift=None,
    gift_recipient_email=None,
    headers=None,
):
    payload = {
        "customer_id": customer_id,
        "plan_tier": plan_tier,
        "turnaround": turnaround,
        "output_option": output_option,
        "lost_damage_protection": protection,
    }
    if promo is not None:
        payload["promo_code"] = promo
    if is_gift is not None:
        payload["is_gift"] = is_gift
    if gift_recipient_email is not None:
        payload["gift_recipient_email"] = gift_recipient_email
    if declared:
        payload.update(declared)
    h = headers if headers is not None else make_customer_headers(customer_id)
    return get_success_data(api.create_order(payload, h))


def authorize_payment(api, order_id, customer_id):
    return get_success_data(api.authorize_payment(order_id, make_customer_headers(customer_id)))


def capture_payment(api, order_id):
    return get_success_data(api.capture_payment(order_id, _ADMIN))


def receive_order(api, order_id):
    return get_success_data(api.receive_order(order_id, _INTAKE))


def create_bin(api, label="Bin-1", capacity=10):
    return get_success_data(
        api.create_storage_bin({"label": label, "capacity": capacity}, _ADMIN)
    )


def create_machine(api, name="Station-1", kind="TAPE_DECK"):
    return get_success_data(api.create_machine({"name": name, "kind": kind}, _ADMIN))


def create_batch(
    api,
    machine_id,
    scheduled_start="2026-03-01T09:00:00Z",
    scheduled_end="2026-03-01T10:00:00Z",
):
    return get_success_data(
        api.create_batch(
            {
                "machine_id": machine_id,
                "scheduled_start": scheduled_start,
                "scheduled_end": scheduled_end,
            },
            _LAB,
        )
    )


def log_media_item(api, order_id, bin_id, media_type="TAPE", barcode=None):
    payload = {"media_type": media_type, "bin_id": bin_id}
    if barcode is not None:
        payload["barcode"] = barcode
    return get_success_data(api.create_media_item(order_id, payload, _INTAKE))


def load_item(api, batch_id, item_id):
    return get_success_data(api.load_batch(batch_id, {"media_item_id": item_id}, _LAB))


def run_batch(api, batch_id):
    return get_success_data(api.run_batch(batch_id, _LAB))


def complete_scan(api, item_id, media_type="TAPE"):
    return get_success_data(api.complete_scan(item_id, _scan_payload(media_type), _LAB))


def qc_pass(api, item_id):
    return get_success_data(api.qc_review(item_id, {"decision": "PASS"}, _LAB))


def qc_fail(api, item_id):
    return get_success_data(api.qc_review(item_id, {"decision": "FAIL"}, _LAB))


def rescan_item(api, item_id):
    return get_success_data(api.rescan(item_id, _LAB))


def set_clock(api, iso):
    return get_success_data(api.set_clock(iso, _ADMIN))


def get_order_admin(api, order_id):
    return get_success_data(api.get_order(order_id, _ADMIN))


def get_item_admin(api, item_id):
    return get_success_data(api.get_media_item(item_id, _ADMIN))


def get_customer_admin(api, customer_id):
    return get_success_data(api.get_customer(customer_id, _ADMIN))


def file_claim(api, order_id, customer_id, media_item_id, claim_type="LOST",
               declared_value_cents=None):
    payload = {"order_id": order_id, "media_item_id": media_item_id, "claim_type": claim_type}
    if declared_value_cents is not None:
        payload["declared_value_cents"] = declared_value_cents
    return get_success_data(api.create_damage_claim(payload, make_customer_headers(customer_id)))


def approve_claim(api, claim_id):
    return get_success_data(api.review_claim(claim_id, {"decision": "APPROVE"}, _CLAIMS))


def reject_claim(api, claim_id):
    return get_success_data(api.review_claim(claim_id, {"decision": "REJECT"}, _CLAIMS))


def generate_artifact(api, order_id, customer_id, output_type="CLOUD", expected_version=None):
    if expected_version is None:
        expected_version = get_order_admin(api, order_id)["version"]
    return get_success_data(
        api.create_output_artifact(
            order_id,
            {"output_type": output_type, "expected_order_version": expected_version},
            make_customer_headers(customer_id),
        )
    )


def download(api, artifact_id, customer_id):
    return get_success_data(api.download_artifact(artifact_id, make_customer_headers(customer_id)))


# ---------------------------------------------------------------------------
# Composite state-progression fixtures
# ---------------------------------------------------------------------------
def setup_ready_order(
    api,
    *,
    items=("TAPE",),
    declared=None,
    protection=False,
    capture=True,
    turnaround="STANDARD",
    promo=None,
    output_option="CLOUD",
    customer_email="ready@x.com",
):
    """Drive a fresh order to fulfillment READY (every logged item OUTPUT_READY)
    with payment optionally CAPTURED. Returns a dict with the created entities.

    `items` is the sequence of media_types to log (one MediaItem each), all
    passed through the pipeline to OUTPUT_READY. `declared` overrides the
    declared_*_count values on the order (defaults to one per logged item).
    """
    cust = create_customer(api, email=customer_email)
    cid = cust["id"]
    if declared is None:
        declared = _counts_from_items(items)
    order = create_order(
        api,
        cid,
        turnaround=turnaround,
        output_option=output_option,
        protection=protection,
        promo=promo,
        declared=declared,
    )
    oid = order["id"]
    authorize_payment(api, oid, cid)
    if capture:
        capture_payment(api, oid)
    receive_order(api, oid)
    bin_ = create_bin(api, capacity=max(10, len(items)))
    machine = create_machine(api, kind=_MACHINE_KIND[items[0]])
    batch = create_batch(api, machine["id"])
    item_records = []
    for mt in items:
        it = log_media_item(api, oid, bin_["id"], mt)
        load_item(api, batch["id"], it["id"])
        item_records.append((it["id"], mt))
    run_batch(api, batch["id"])
    for iid, mt in item_records:
        complete_scan(api, iid, mt)
        qc_pass(api, iid)
    order = get_order_admin(api, oid)
    items_final = [get_item_admin(api, iid) for iid, _ in item_records]
    return {
        "customer": cust,
        "customer_id": cid,
        "order": order,
        "order_id": oid,
        "bin": bin_,
        "machine": machine,
        "batch": batch,
        "item_ids": [iid for iid, _ in item_records],
        "items": items_final,
    }


def setup_order_one_ready_one_pending(api, customer_email="partial@x.com"):
    """Two-tape order (RECEIVED + CAPTURED): first item driven to OUTPUT_READY,
    second item left at QC_PENDING so the order stays PROCESSING."""
    cust = create_customer(api, email=customer_email)
    cid = cust["id"]
    order = create_order(api, cid, declared={"declared_tape_count": 2})
    oid = order["id"]
    authorize_payment(api, oid, cid)
    capture_payment(api, oid)
    receive_order(api, oid)
    bin_ = create_bin(api, capacity=10)
    machine = create_machine(api)
    batch = create_batch(api, machine["id"])
    mi1 = log_media_item(api, oid, bin_["id"], "TAPE")
    mi2 = log_media_item(api, oid, bin_["id"], "TAPE")
    load_item(api, batch["id"], mi1["id"])
    load_item(api, batch["id"], mi2["id"])
    run_batch(api, batch["id"])
    complete_scan(api, mi1["id"], "TAPE")
    qc_pass(api, mi1["id"])
    complete_scan(api, mi2["id"], "TAPE")  # mi2 stops at QC_PENDING (no review)
    order = get_order_admin(api, oid)
    return {
        "customer": cust,
        "customer_id": cid,
        "order": order,
        "order_id": oid,
        "bin": bin_,
        "machine": machine,
        "batch": batch,
        "mi1": mi1["id"],
        "mi2": mi2["id"],
    }


def setup_loaded_batch(api, customer_email="loaded@x.com"):
    """Order RECEIVED (authorized, not captured) with one LOGGED tape item
    loaded into a LOADED batch. The batch has NOT been run yet."""
    cust = create_customer(api, email=customer_email)
    cid = cust["id"]
    order = create_order(api, cid, declared={"declared_tape_count": 1})
    oid = order["id"]
    authorize_payment(api, oid, cid)
    receive_order(api, oid)
    bin_ = create_bin(api, capacity=10)
    machine = create_machine(api)
    batch = create_batch(api, machine["id"])
    mi = log_media_item(api, oid, bin_["id"], "TAPE")
    load_item(api, batch["id"], mi["id"])
    return {
        "customer": cust,
        "customer_id": cid,
        "order": get_order_admin(api, oid),
        "order_id": oid,
        "bin": bin_,
        "machine": machine,
        "batch": batch,
        "item_id": mi["id"],
    }


def setup_item_scanning(api, customer_email="scan@x.com"):
    """One tape item driven to SCANNING (order RECEIVED->PROCESSING via batch run)."""
    base = setup_loaded_batch(api, customer_email=customer_email)
    run_batch(api, base["batch"]["id"])
    base["item"] = get_item_admin(api, base["item_id"])
    return base


def setup_item_qc_failed(api, times=1, customer_email="qcfail@x.com"):
    """One tape item cycled through `times` failing QC reviews. It ends at
    QC_FAIL with qc_attempts == times (a rescan is issued between failures,
    but not after the final one)."""
    base = setup_item_scanning(api, customer_email=customer_email)
    iid = base["item_id"]
    for i in range(times):
        complete_scan(api, iid, "TAPE")
        qc_fail(api, iid)
        if i < times - 1:
            rescan_item(api, iid)
    base["item"] = get_item_admin(api, iid)
    return base


def setup_machine_with_batch(api, machine_kind="TAPE_DECK"):
    """One machine with an existing batch reserving [09:00, 10:00)."""
    machine = create_machine(api, kind=machine_kind)
    batch = create_batch(api, machine["id"])
    return {"machine": machine, "machine_id": machine["id"], "batch": batch}


def setup_bin_with_one_item(api, capacity=1, customer_email="bin@x.com"):
    """Order RECEIVED and a bin of the given capacity already holding one logged
    tape item whose 30-day retention window covers the default clock."""
    cust = create_customer(api, email=customer_email)
    cid = cust["id"]
    order = create_order(api, cid, declared={"declared_tape_count": 2})
    oid = order["id"]
    authorize_payment(api, oid, cid)
    receive_order(api, oid)
    bin_ = create_bin(api, capacity=capacity)
    mi = log_media_item(api, oid, bin_["id"], "TAPE")
    return {
        "customer": cust,
        "customer_id": cid,
        "order_id": oid,
        "bin": bin_,
        "bin_id": bin_["id"],
        "item_id": mi["id"],
    }


def setup_generated_artifact(api, output_type="CLOUD", customer_email="art@x.com"):
    """Order READY + CAPTURED with one OUTPUT_READY tape item and one generated
    artifact of the given type. Returns the stale (pre-generation) order version
    so OCC tests can replay it."""
    ready = setup_ready_order(api, items=("TAPE",), capture=True,
                              output_option=output_type, customer_email=customer_email)
    stale_version = ready["order"]["version"]
    artifact = generate_artifact(
        api, ready["order_id"], ready["customer_id"],
        output_type=output_type, expected_version=stale_version,
    )
    ready["artifact"] = artifact
    ready["artifact_id"] = artifact["id"]
    ready["stale_version"] = stale_version
    return ready
