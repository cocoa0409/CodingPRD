"""Composite setup helpers.

Every fixture builds its state exclusively through PRD-declared endpoints — the
storage is wiped before each test, so nothing may be assumed to pre-exist.

The journeys most tests share:

* **Rental pipeline** — plan -> member (+child) -> subscription -> catalog item
  -> copy -> PLANNED box -> slotted item -> ship -> DELIVERED -> return ->
  RECEIVED -> inspect -> INSPECTED -> close -> CLOSED.  Helpers named
  `setup_planned_box`, `setup_delivered_box`, `setup_received_box`,
  `setup_inspected_box`, `setup_closed_box`.
* **Hold pipeline** — wishlist entry WAITING -> allocation run -> HELD ->
  accept-hold into a PLANNED box.  Helpers named `setup_held_entry`,
  `setup_held_entry_with_box`.
* **Fee pipeline** — delivered box -> report-lost / inspection -> INVOICED fee.
  Helper `setup_loss_fee`.

All helpers use `get_success_data` internally so a setup failure surfaces as a
clear "Setup step failed" instead of a confusing assertion error.  Ownership-
gated calls always go through `make_member_headers(member["id"])`.
"""

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client as api
from .constants import DEFAULT_CHILD_BIRTHDATE
from .factories import (
    create_add_item_payload,
    create_box_create_payload,
    create_catalog_item_payload,
    create_child_payload,
    create_copy_payload,
    create_inspection_payload,
    create_member_payload,
    create_pause_payload,
    create_plan_payload,
    create_report_lost_payload,
    create_shipment_event_payload,
    create_shipment_payload,
    create_subscription_payload,
    create_wallet_adjustment_payload,
    create_wishlist_entry_payload,
    inspection_record,
)
from .test_users import ADMIN, OPS, SUPPORT, ANONYMOUS, make_member_headers

BIG_PAGE = {"limit": 100, "offset": 0}


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------


def set_clock(to_iso8601: str) -> dict:
    """Drive the logical clock.  Before any call it reads 2026-05-01T00:00:00Z."""
    return get_success_data(api.set_clock(to_iso8601, ADMIN))


# ---------------------------------------------------------------------------
# Primitive creators (each returns the created resource's data payload)
# ---------------------------------------------------------------------------


def create_plan(**overrides) -> dict:
    return get_success_data(api.create_plan(create_plan_payload(**overrides), ADMIN))


def register_member(email="m@x.com", full_name="Test Member") -> dict:
    return get_success_data(api.register_member(
        create_member_payload(email=email, full_name=full_name), ANONYMOUS))


def adjust_wallet(member_id, amount_cents, reason="PROMO_CREDIT", note="") -> dict:
    return get_success_data(api.create_wallet_adjustment(
        member_id, create_wallet_adjustment_payload(amount_cents, reason, note), SUPPORT))


def add_child(member_id, name="Kid", birthdate=DEFAULT_CHILD_BIRTHDATE) -> dict:
    return get_success_data(api.create_child(
        member_id, create_child_payload(name=name, birthdate=birthdate),
        make_member_headers(member_id)))


def subscribe(member, plan_id) -> dict:
    return get_success_data(api.create_subscription(
        member["id"], create_subscription_payload(plan_id),
        make_member_headers(member["id"])))


def create_catalog_item(**overrides) -> dict:
    return get_success_data(api.create_catalog_item(
        create_catalog_item_payload(**overrides), ADMIN))


def mint_copy(catalog_item_id, barcode="BC-1", condition_grade="NEW") -> dict:
    return get_success_data(api.mint_copy(
        catalog_item_id,
        create_copy_payload(barcode=barcode, condition_grade=condition_grade),
        ADMIN))


def create_wishlist_entry(member, catalog_item_id, rank=1) -> dict:
    return get_success_data(api.create_wishlist_entry(
        member["id"], create_wishlist_entry_payload(catalog_item_id, rank),
        make_member_headers(member["id"])))


def pause_subscription(subscription_id, member, start_date, duration_days) -> dict:
    return get_success_data(api.pause_subscription(
        subscription_id, create_pause_payload(start_date, duration_days),
        make_member_headers(member["id"])))


def resume_subscription(subscription_id, member) -> dict:
    return get_success_data(api.resume_subscription(
        subscription_id, make_member_headers(member["id"])))


def cancel_subscription(subscription_id, member, reason=None) -> dict:
    payload = {} if reason is None else {"reason": reason}
    return get_success_data(api.cancel_subscription(
        subscription_id, payload, make_member_headers(member["id"])))


def ops_run() -> dict:
    """POST /toy-rental/ops/allocation-runs as OperationsManager."""
    return get_success_data(api.run_allocation(OPS))


# ---------------------------------------------------------------------------
# Fresh reads (versions drift under OCC, so always re-read before a guarded write)
# ---------------------------------------------------------------------------


def read_member(member_id, headers=None) -> dict:
    return get_success_data(api.get_member(member_id, headers or make_member_headers(member_id)))


def read_subscription(subscription_id, member) -> dict:
    return get_success_data(api.get_subscription(
        subscription_id, make_member_headers(member["id"])))


def read_box(box_id, member) -> dict:
    return get_success_data(api.get_rotation_box(box_id, make_member_headers(member["id"])))


def read_box_as_ops(box_id) -> dict:
    return get_success_data(api.get_rotation_box(box_id, OPS))


def read_copy(copy_id) -> dict:
    return get_success_data(api.get_copy(copy_id, OPS))


def read_box_item(box_item_id, member) -> dict:
    return get_success_data(api.get_box_item(box_item_id, make_member_headers(member["id"])))


def list_box_items(box_id, member) -> list:
    data, _ = validate_paginated(api.list_box_items(
        box_id, make_member_headers(member["id"]), params=BIG_PAGE))
    return data


def list_box_fees(box_id, member) -> list:
    data, _ = validate_paginated(api.list_box_fees(
        box_id, make_member_headers(member["id"]), params=BIG_PAGE))
    return data


def list_item_fees(box_item_id, member) -> list:
    data, _ = validate_paginated(api.list_box_item_fees(
        box_item_id, make_member_headers(member["id"]), params=BIG_PAGE))
    return data


def list_box_shipments(box_id, member) -> list:
    data, _ = validate_paginated(api.list_box_shipments(
        box_id, make_member_headers(member["id"]), params=BIG_PAGE))
    return data


def list_ledger(member_id) -> list:
    data, _ = validate_paginated(api.list_wallet_ledger(
        member_id, make_member_headers(member_id), params=BIG_PAGE))
    return data


def list_wishlist_entries(member) -> list:
    data, _ = validate_paginated(api.list_wishlist_entries(
        member["id"], make_member_headers(member["id"]), params=BIG_PAGE))
    return data


def read_wishlist_entry(member, entry_id) -> dict:
    matches = [e for e in list_wishlist_entries(member) if e["id"] == entry_id]
    assert len(matches) == 1, f"wishlist entry {entry_id} not found for member {member['id']}"
    return matches[0]


def list_subscription_boxes(subscription_id, member) -> list:
    data, _ = validate_paginated(api.list_rotation_boxes(
        subscription_id, make_member_headers(member["id"]), params=BIG_PAGE))
    return data


# ---------------------------------------------------------------------------
# OCC-guarded writers (always re-read the parent version first)
# ---------------------------------------------------------------------------


def create_next_box(member, subscription_id) -> dict:
    sub = read_subscription(subscription_id, member)
    return get_success_data(api.create_rotation_box(
        subscription_id, create_box_create_payload(sub["version"]),
        make_member_headers(member["id"])))


def add_item_to_box(member, box_id, toy_copy_id) -> dict:
    box = read_box(box_id, member)
    return get_success_data(api.add_box_item(
        box_id, create_add_item_payload(toy_copy_id, box["version"]),
        make_member_headers(member["id"])))


# ---------------------------------------------------------------------------
# Shipment journeys
# ---------------------------------------------------------------------------


def ship_box(box_id, carrier="UPS", tracking_number="1Z-OUT") -> dict:
    return get_success_data(api.ship_box(
        box_id, create_shipment_payload(carrier, tracking_number), OPS))


def record_event(shipment_id, event_type, occurred_at) -> dict:
    return get_success_data(api.record_shipment_event(
        shipment_id, create_shipment_event_payload(event_type, occurred_at), OPS))


def deliver_box(box, member, delivered_at="2026-05-03T00:00:00Z",
                in_transit_at="2026-05-02T00:00:00Z", carrier="UPS",
                tracking_number="1Z-OUT") -> dict:
    """Ship a PLANNED box and drive the outbound leg to DELIVERED."""
    outbound = ship_box(box["id"], carrier, tracking_number)
    record_event(outbound["id"], "IN_TRANSIT", in_transit_at)
    record_event(outbound["id"], "DELIVERED", delivered_at)
    return outbound


def return_and_receive(box, member, received_at="2026-05-10T00:00:00Z",
                       in_transit_at="2026-05-09T00:00:00Z", carrier="UPS",
                       tracking_number="1Z-RET") -> dict:
    """Initiate the return of a DELIVERED box and drive it to RECEIVED."""
    ret = get_success_data(api.initiate_return(
        box["id"], create_shipment_payload(carrier, tracking_number),
        make_member_headers(member["id"])))
    record_event(ret["id"], "IN_TRANSIT", in_transit_at)
    record_event(ret["id"], "DELIVERED", received_at)
    return ret


def inspect_box(box_id, records) -> dict:
    """Record one inspection record per item; returns the box payload."""
    return get_success_data(api.inspect_box(box_id, create_inspection_payload(records), OPS))


# ---------------------------------------------------------------------------
# Tier 1/2: member + subscription scaffolding
# ---------------------------------------------------------------------------


def setup_member_with_subscription(plan_overrides=None, member_email="m@x.com",
                                   child_birthdate=DEFAULT_CHILD_BIRTHDATE,
                                   wallet_seed=None, with_child=True) -> dict:
    """Plan + member (+ optional wallet credit) (+ child) + ACTIVE subscription."""
    plan = create_plan(**(plan_overrides or {}))
    member = register_member(email=member_email)
    if wallet_seed is not None:
        reason = "PROMO_CREDIT" if wallet_seed >= 0 else "SUPPORT_ADJUSTMENT"
        adjust_wallet(member["id"], wallet_seed, reason=reason, note="seed")
    child = add_child(member["id"], birthdate=child_birthdate) if with_child else None
    subscription = subscribe(member, plan["id"])
    return {"plan": plan, "member": member, "child": child, "subscription": subscription}


# ---------------------------------------------------------------------------
# Tier 2/3: box journeys
# ---------------------------------------------------------------------------


def setup_planned_box(item_overrides=None, barcode="BC-1", copy_grade="NEW", **kw) -> dict:
    """Member scaffolding + catalog item + one copy + PLANNED box with the copy
    slotted (copy RESERVED to the member)."""
    ctx = setup_member_with_subscription(**kw)
    item = create_catalog_item(**(item_overrides or {}))
    copy = mint_copy(item["id"], barcode=barcode, condition_grade=copy_grade)
    box = create_next_box(ctx["member"], ctx["subscription"]["id"])
    box_item = add_item_to_box(ctx["member"], box["id"], copy["id"])
    ctx.update({"catalog_item": item, "copy": copy, "box": box, "item": box_item})
    return ctx


def setup_delivered_box(delivered_at="2026-05-03T00:00:00Z",
                        in_transit_at="2026-05-02T00:00:00Z", **kw) -> dict:
    """PLANNED box journey driven through ship + outbound DELIVERED.

    The box is DELIVERED with delivered_at/due_date stamped from the carrier
    event instants and every slotted copy OUT_ON_LOAN."""
    ctx = setup_planned_box(**kw)
    outbound = deliver_box(ctx["box"], ctx["member"], delivered_at, in_transit_at)
    ctx["outbound"] = outbound
    ctx["box"] = read_box(ctx["box"]["id"], ctx["member"])
    return ctx


def setup_received_box(received_at="2026-05-10T00:00:00Z",
                       return_in_transit_at="2026-05-09T00:00:00Z", **kw) -> dict:
    """DELIVERED journey + member-initiated return driven to RECEIVED."""
    ctx = setup_delivered_box(**kw)
    ret = return_and_receive(ctx["box"], ctx["member"], received_at, return_in_transit_at)
    ctx["return_shipment"] = ret
    ctx["box"] = read_box(ctx["box"]["id"], ctx["member"])
    return ctx


def setup_inspected_box(condition_returned="GOOD", damage_severity="NONE",
                        missing_piece_count=0, disposition="RESTOCK", **kw) -> dict:
    """RECEIVED journey + a full inspection of the single slotted item."""
    ctx = setup_received_box(**kw)
    records = [inspection_record(ctx["item"]["id"], condition_returned,
                                 damage_severity, missing_piece_count, disposition)]
    ctx["box"] = inspect_box(ctx["box"]["id"], records)
    return ctx


def setup_closed_box(close_clock=None, **kw) -> dict:
    """Full lifecycle through CLOSED (clean inspection, no fees to settle)."""
    ctx = setup_inspected_box(**kw)
    if close_clock is not None:
        set_clock(close_clock)
    ctx["box"] = get_success_data(api.close_box(ctx["box"]["id"], OPS))
    return ctx


def setup_loss_fee(item_overrides=None, wallet_seed=None, member_email="m.loss@x.com",
                   note="lost", **kw) -> dict:
    """Delivered box whose single item is reported lost: one LOSS fee INVOICED
    for the catalog item's replacement value, FEE_CHARGE appended."""
    ctx = setup_delivered_box(item_overrides=item_overrides,
                              member_email=member_email, wallet_seed=wallet_seed, **kw)
    get_success_data(api.report_lost(ctx["item"]["id"], create_report_lost_payload(note),
                                     make_member_headers(ctx["member"]["id"])))
    fees = list_item_fees(ctx["item"]["id"], ctx["member"])
    assert len(fees) == 1, f"expected exactly one LOSS fee, got {len(fees)}"
    ctx["fee"] = fees[0]
    ctx["item"] = read_box_item(ctx["item"]["id"], ctx["member"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 2 variant: two-item box (fee-aggregation journeys)
# ---------------------------------------------------------------------------


def setup_two_item_received_box(item_specs, received_at="2026-05-10T00:00:00Z",
                                return_in_transit_at="2026-05-09T00:00:00Z",
                                delivered_at="2026-05-03T00:00:00Z",
                                in_transit_at="2026-05-02T00:00:00Z",
                                member_email="m.two@x.com",
                                child_birthdate=DEFAULT_CHILD_BIRTHDATE,
                                plan_overrides=None, wallet_seed=None) -> dict:
    """PLANNED box holding two copies (different catalog items), driven through
    delivery and return receipt.

    item_specs: list of two dicts, each {"barcode": str, "item": {catalog item
    field overrides}}.
    """
    ctx = setup_member_with_subscription(plan_overrides=plan_overrides,
                                         member_email=member_email,
                                         child_birthdate=child_birthdate,
                                         wallet_seed=wallet_seed)
    box = create_next_box(ctx["member"], ctx["subscription"]["id"])
    items, copies, catalog_items = [], [], []
    for spec in item_specs:
        ci = create_catalog_item(**spec.get("item", {}))
        copy = mint_copy(ci["id"], barcode=spec["barcode"])
        bi = add_item_to_box(ctx["member"], box["id"], copy["id"])
        catalog_items.append(ci)
        copies.append(copy)
        items.append(bi)
    outbound = deliver_box(box, ctx["member"], delivered_at, in_transit_at)
    ret = return_and_receive(read_box(box["id"], ctx["member"]), ctx["member"],
                             received_at, return_in_transit_at)
    ctx.update({"catalog_items": catalog_items, "copies": copies, "items": items,
                "box": read_box(box["id"], ctx["member"]),
                "outbound": outbound, "return_shipment": ret})
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: hold pipeline
# ---------------------------------------------------------------------------


def setup_held_entry(member_email="m.hold@x.com", plan_overrides=None,
                     item_overrides=None, barcode="BC-HOLD-1", rank=1,
                     child_birthdate=DEFAULT_CHILD_BIRTHDATE) -> dict:
    """Member scaffolding + catalog item + one AVAILABLE NEW copy + WAITING
    wishlist entry, then one ops run that promotes the entry to HELD on the
    copy (hold_expires_at = promotion clock + 72h)."""
    ctx = setup_member_with_subscription(plan_overrides=plan_overrides,
                                         member_email=member_email,
                                         child_birthdate=child_birthdate)
    item = create_catalog_item(**(item_overrides or {}))
    copy = mint_copy(item["id"], barcode=barcode)
    entry = create_wishlist_entry(ctx["member"], item["id"], rank=rank)
    run = ops_run()
    ctx.update({"catalog_item": item, "copy": copy, "entry_id": entry["id"],
                "run": run,
                "entry": read_wishlist_entry(ctx["member"], entry["id"])})
    return ctx


def setup_held_entry_with_box(**kw) -> dict:
    """setup_held_entry + a fresh PLANNED box belonging to the same member."""
    ctx = setup_held_entry(**kw)
    ctx["box"] = create_next_box(ctx["member"], ctx["subscription"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 4/5: buy-out context with a FAIR-graded copy
# ---------------------------------------------------------------------------


def setup_buyout_context(member_email="m.buy@x.com", wallet_seed=None,
                         delivered_at="2026-06-03T00:00:00Z",
                         in_transit_at="2026-05-31T00:00:00Z",
                         buyout_clock="2026-08-05T00:00:00Z") -> dict:
    """Build the buy-out stage with a copy whose grade is FAIR at buy-out time.

    A minted copy's `last_sanitized_at` is null (PRD 3.2) and only factory-sealed
    NEW copies or copies sanitized within 30 days are slot-valid (PRD 2.10), so
    the FAIR grade is earned the PRD-faithful way: a clean first rental loop
    whose inspection records `condition_returned` FAIR degrades the copy NEW ->
    FAIR (PRD 3.6), then sanitization completes after the 24h buffer and the
    recirculated copy is slotted into the next cycle's box.

    Timeline: first box delivered 2026-05-03, returned received 2026-05-10,
    inspected clean; sanitization completes at clock 2026-05-02 (exactly 24h
    after the 2026-05-01 inspection clock); box 1 closes at 2026-05-02, moving
    the cadence anchor to 2026-05-30; box 2 is created at clock 2026-05-30,
    ships, and is DELIVERED at `delivered_at` (2026-06-03 -> due 2026-07-01);
    the clock then advances to `buyout_clock` (2026-08-05), two whole calendar
    months after delivery.
    """
    ctx = setup_member_with_subscription(member_email=member_email,
                                         wallet_seed=wallet_seed)
    member = ctx["member"]
    item = create_catalog_item(title="Kitchen Set", piece_count=4,
                               retail_value_cents=12000, replacement_value_cents=9000)
    copy = mint_copy(item["id"], barcode="BC-BUY-1", condition_grade="NEW")

    # First rental loop: clean inspection with condition_returned FAIR.
    box1 = create_next_box(member, ctx["subscription"]["id"])
    item1 = add_item_to_box(member, box1["id"], copy["id"])
    deliver_box(box1, member, delivered_at="2026-05-03T00:00:00Z",
                in_transit_at="2026-05-02T00:00:00Z")
    return_and_receive(read_box(box1["id"], member), member,
                       received_at="2026-05-10T00:00:00Z",
                       in_transit_at="2026-05-09T00:00:00Z")
    inspect_box(box1["id"], [inspection_record(item1["id"], condition_returned="FAIR",
                                               damage_severity="NONE",
                                               missing_piece_count=0,
                                               disposition="RESTOCK")])

    # Sanitization: inspection stamped sanitization_started_at at the default
    # clock 2026-05-01T00:00:00Z; exactly 24h later the buffer is satisfied.
    set_clock("2026-05-02T00:00:00Z")
    get_success_data(api.complete_sanitization(copy["id"], OPS))

    # Close box 1: cadence anchor moves to clock + rotation_cadence_days.
    get_success_data(api.close_box(box1["id"], OPS))

    # Second cycle: create the next box once the cadence is due and slot the
    # recirculated FAIR copy (last sanitized 2026-05-02, 28 days before).
    set_clock("2026-05-30T00:00:00Z")
    box2 = create_next_box(member, ctx["subscription"]["id"])
    item2 = add_item_to_box(member, box2["id"], copy["id"])
    outbound2 = deliver_box(box2, member, delivered_at=delivered_at,
                            in_transit_at=in_transit_at)

    set_clock(buyout_clock)
    ctx.update({"catalog_item": item, "copy": read_copy(copy["id"]),
                "box1_id": box1["id"], "box": read_box(box2["id"], member),
                "item": item2, "outbound": outbound2})
    return ctx
