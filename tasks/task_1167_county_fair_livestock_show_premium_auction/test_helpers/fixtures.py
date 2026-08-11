"""Composite setup helpers (PRD §3 workflows).

Every helper builds preconditions from scratch through the public API; each
test runs against a freshly restarted server. Setup calls use the lenient
get_success_data() so failures surface as clear setup errors.

Identity threading: entity-backed roles (Exhibitor, Judge, Buyer) always go
through make_<role>_headers(entity["id"]); opaque roles use TEST_USERS.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_add_on_payload,
    create_affidavit_payload,
    create_buyer_payload,
    create_class_payload,
    create_disposition_payload,
    create_entry_payload,
    create_exhibitor_payload,
    create_fair_payload,
    create_health_inspection_payload,
    create_judge_payload,
    create_ring_slot_payload,
    create_weigh_ticket_payload,
)
from .test_users import (
    TEST_USERS,
    make_admin_headers,
    make_buyer_headers,
    make_exhibitor_headers,
    make_judge_headers,
)

ADMIN = TEST_USERS["admin"]
CLERK = TEST_USERS["show_clerk"]
WEIGHMASTER = TEST_USERS["weigh_master"]
AUCTIONEER = TEST_USERS["auctioneer"]
INSPECTOR = TEST_USERS["health_inspector"]
TREASURER = TEST_USERS["treasurer"]

# Canonical posture order (PRD §2.5).
POSTURE_ORDER = [
    "SETUP", "ENTRIES_OPEN", "ENTRIES_LOCKED", "WEIGH_IN",
    "SHOWING", "AUCTION", "SETTLEMENT", "CLOSED",
]


# ---------------------------------------------------------------------------
# Tier 1: single-call helpers
# ---------------------------------------------------------------------------

def create_fair(**overrides) -> dict:
    resp = api_client.create_fair(create_fair_payload(**overrides), ADMIN)
    return get_success_data(resp)


def advance_posture(fair_id: str, to_posture: str) -> dict:
    resp = api_client.advance_posture(fair_id, to_posture, ADMIN)
    return get_success_data(resp)


def advance_fair_to(fair_id: str, target: str) -> dict:
    """Walk the canonical one-step chain until `target` is reached."""
    fair = get_success_data(api_client.get_fair(fair_id, ADMIN))
    while fair["posture"] != target:
        nxt = POSTURE_ORDER[POSTURE_ORDER.index(fair["posture"]) + 1]
        fair = advance_posture(fair_id, nxt)
    return fair


def create_fair_in_posture(target: str, **fair_overrides) -> dict:
    fair = create_fair(**fair_overrides)
    return advance_fair_to(fair["id"], target)


def get_fair(fair_id: str) -> dict:
    return get_success_data(api_client.get_fair(fair_id, ADMIN))


def set_clock(to_iso8601: str) -> dict:
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_exhibitor(fair_id: str, **overrides) -> dict:
    resp = api_client.create_exhibitor(
        create_exhibitor_payload(fair_id, **overrides), ADMIN
    )
    return get_success_data(resp)


def create_entry(fair_id: str, exhibitor: dict, **overrides) -> dict:
    """Create an entry filed by its owning exhibitor (ownership-safe)."""
    resp = api_client.create_entry(
        create_entry_payload(fair_id, exhibitor["id"], **overrides),
        make_exhibitor_headers(exhibitor["id"]),
    )
    return get_success_data(resp)


def get_entry(entry_id: str) -> dict:
    return get_success_data(api_client.get_entry(entry_id, ADMIN))


def verify_entry(entry_id: str, decision: str = "APPROVE") -> dict:
    resp = api_client.verify_entry(entry_id, decision, ADMIN)
    return get_success_data(resp)


def create_verified_entry(fair_id: str, exhibitor: dict, **overrides) -> dict:
    entry = create_entry(fair_id, exhibitor, **overrides)
    return verify_entry(entry["id"])


def weigh_entry(entry_id: str, weight_lbs, weighed_at: str = None) -> dict:
    """Record a weigh ticket with a fresh OCC version for the entry."""
    entry = get_entry(entry_id)
    payload_kwargs = {}
    if weighed_at is not None:
        payload_kwargs["weighed_at"] = weighed_at
    resp = api_client.create_weigh_ticket(
        create_weigh_ticket_payload(
            entry_id, entry["version"], weight_lbs=weight_lbs, **payload_kwargs
        ),
        WEIGHMASTER,
    )
    return get_success_data(resp)


def create_class(fair_id: str, **overrides) -> dict:
    resp = api_client.create_class(create_class_payload(fair_id, **overrides), ADMIN)
    return get_success_data(resp)


def get_class(class_id: str) -> dict:
    return get_success_data(api_client.get_class(class_id, ADMIN))


def classify_entry(entry_id: str, class_id: str = None) -> dict:
    resp = api_client.classify_entry(entry_id, CLERK, class_id=class_id)
    return get_success_data(resp)


def create_judge(fair_id: str, **overrides) -> dict:
    resp = api_client.create_judge(create_judge_payload(fair_id, **overrides), ADMIN)
    return get_success_data(resp)


def create_ring_slot(fair_id: str, class_id: str, **overrides) -> dict:
    resp = api_client.create_ring_slot(
        create_ring_slot_payload(fair_id, class_id, **overrides), CLERK
    )
    return get_success_data(resp)


def get_ring_slot(slot_id: str) -> dict:
    return get_success_data(api_client.get_ring_slot(slot_id, ADMIN))


def assign_judge(slot_id: str, judge_id: str) -> dict:
    """Assign a judge with a fresh OCC version for the slot."""
    slot = get_ring_slot(slot_id)
    resp = api_client.assign_judge(slot_id, judge_id, slot["version"], CLERK)
    return get_success_data(resp)


def start_slot(slot_id: str) -> dict:
    return get_success_data(api_client.start_slot(slot_id, CLERK))


def submit_placings(slot_id: str, judge_id: str, lines: list) -> dict:
    """Submit placings as the assigned judge. Returns placing/award id lists."""
    resp = api_client.submit_placings(
        slot_id, lines, make_judge_headers(judge_id)
    )
    return get_success_data(resp)


def create_buyer(fair_id: str, **overrides) -> dict:
    resp = api_client.create_buyer(create_buyer_payload(fair_id, **overrides), ADMIN)
    return get_success_data(resp)


def generate_lots(fair_id: str) -> dict:
    return get_success_data(api_client.generate_auction_lots(fair_id, AUCTIONEER))


def get_lot(lot_id: str) -> dict:
    return get_success_data(api_client.get_auction_lot(lot_id, ADMIN))


def open_lot(lot_id: str) -> dict:
    return get_success_data(api_client.open_lot(lot_id, AUCTIONEER))


def close_sold(lot_id: str, buyer_id: str, hammer_price_cents: int) -> dict:
    return get_success_data(
        api_client.close_sold(lot_id, buyer_id, hammer_price_cents, AUCTIONEER)
    )


def close_passed(lot_id: str) -> dict:
    return get_success_data(api_client.close_passed(lot_id, AUCTIONEER))


def reoffer_lot(lot_id: str) -> dict:
    return get_success_data(api_client.reoffer_lot(lot_id, AUCTIONEER))


def no_sale_lot(lot_id: str) -> dict:
    return get_success_data(api_client.no_sale_lot(lot_id, AUCTIONEER))


def create_add_on(lot_id: str, buyer_id: str, amount_cents: int,
                  as_admin: bool = False) -> dict:
    headers = ADMIN if as_admin else make_buyer_headers(buyer_id)
    resp = api_client.create_add_on(
        create_add_on_payload(lot_id, buyer_id, amount_cents=amount_cents), headers
    )
    return get_success_data(resp)


def get_add_on(addon_id: str) -> dict:
    return get_success_data(api_client.get_add_on(addon_id, ADMIN))


def list_invoices() -> list:
    from prd_bench_local_runner.testing import validate_paginated
    data, _meta = validate_paginated(api_client.list_invoices(ADMIN))
    return data


def get_buyer_invoice(buyer_id: str) -> dict:
    """Return the buyer's single invoice (fresh database per test)."""
    for inv in list_invoices():
        if inv["buyer_id"] == buyer_id:
            return inv
    raise AssertionError(f"Setup failed: no invoice found for buyer {buyer_id}")


def list_premium_awards() -> list:
    from prd_bench_local_runner.testing import validate_paginated
    data, _meta = validate_paginated(api_client.list_premium_awards(ADMIN))
    return data


def list_placings() -> list:
    from prd_bench_local_runner.testing import validate_paginated
    data, _meta = validate_paginated(api_client.list_placings(ADMIN))
    return data


def list_dispositions() -> list:
    from prd_bench_local_runner.testing import validate_paginated
    data, _meta = validate_paginated(api_client.list_dispositions(ADMIN))
    return data


def issue_invoice(invoice_id: str) -> dict:
    return get_success_data(api_client.issue_invoice(invoice_id, TREASURER))


def post_payment(invoice_id: str, amount_cents: int) -> dict:
    return get_success_data(
        api_client.post_payment(invoice_id, amount_cents, TREASURER)
    )


def create_disposition(entry_id: str, creator_headers=None, **overrides) -> dict:
    resp = api_client.create_disposition(
        create_disposition_payload(entry_id, **overrides),
        creator_headers or make_admin_headers("admin-a"),
    )
    return get_success_data(resp)


def get_disposition(order_id: str) -> dict:
    return get_success_data(api_client.get_disposition(order_id, ADMIN))


def approve_disposition(order_id: str, approver_id: str = "admin-b") -> dict:
    return get_success_data(
        api_client.approve_disposition(order_id, make_admin_headers(approver_id))
    )


def reject_disposition(order_id: str, reason: str,
                       approver_id: str = "admin-b") -> dict:
    return get_success_data(
        api_client.reject_disposition(order_id, reason,
                                      make_admin_headers(approver_id))
    )


def complete_disposition(order_id: str, admin_id: str = "admin-b") -> dict:
    return get_success_data(
        api_client.complete_disposition(order_id, make_admin_headers(admin_id))
    )


def record_health_inspection(entry_id: str, result: str = "PASS",
                             notes: str = None) -> dict:
    payload = create_health_inspection_payload(entry_id, result=result)
    if notes is not None:
        payload["notes"] = notes
    resp = api_client.create_health_inspection(payload, INSPECTOR)
    return get_success_data(resp)


def sign_affidavit(entry_id: str, exhibitor: dict, **overrides) -> dict:
    """Sign the drug-free affidavit as the owning exhibitor."""
    resp = api_client.create_affidavit(
        create_affidavit_payload(entry_id, **overrides),
        make_exhibitor_headers(exhibitor["id"]),
    )
    return get_success_data(resp)


def get_affidavit(affidavit_id: str) -> dict:
    return get_success_data(api_client.get_affidavit(affidavit_id, ADMIN))


def award_for_entry(entry_id: str) -> dict:
    for award in list_premium_awards():
        if award["entry_id"] == entry_id:
            return award
    raise AssertionError(f"Setup failed: no premium award for entry {entry_id}")


def placing_for_entry(entry_id: str) -> dict:
    for placing in list_placings():
        if placing["entry_id"] == entry_id:
            return placing
    raise AssertionError(f"Setup failed: no placing for entry {entry_id}")


# ---------------------------------------------------------------------------
# Tier 2/3: the show pipeline
# ---------------------------------------------------------------------------

def build_show_state(
    *,
    fair_overrides: dict = None,
    entries: list = (),
    classes: list = (),
    entry_class_map: dict = None,
    judges: list = (),
    slots: list = (),
    placings: list = (),
    advance_to: str = "SHOWING",
    affidavit_entries: list = (),
    exhibitor_names=("Ann A", "Ben B", "Cat C", "Dan D", "Eve E", "Finn F"),
) -> dict:
    """Walk a fair from creation through the show pipeline.

    entries:  [{species, tag_number, weight_lbs, exhibitor_index?, ...}]
    classes:  [{species, class_code, weight_min_lbs, weight_max_lbs, capacity}]
    entry_class_map: {entry_index: class_index} — classify each mapped entry
        into the mapped class (explicit class_id); unmapped entries are not
        classified.
    judges:   [{full_name?, qualified_species}]
    slots:    [{class_index, ring_name, starts_at, ends_at, judge_index}]
    placings: [{slot_index, lines: [{entry_index, rank, award}]}]
    affidavit_entries: entry indexes that get a SIGNED affidavit.
    advance_to: posture to stop at ("WEIGH_IN", "SHOWING", "AUCTION",
        "SETTLEMENT"). Posture advances past SHOWING happen after placings.
    """
    fair = create_fair(**(fair_overrides or {}))
    fair_id = fair["id"]
    advance_posture(fair_id, "ENTRIES_OPEN")

    max_exhibitor = 0
    for spec in entries:
        max_exhibitor = max(max_exhibitor, spec.get("exhibitor_index", 0))
    exhibitors = [
        create_exhibitor(fair_id, full_name=exhibitor_names[i % len(exhibitor_names)])
        for i in range(max_exhibitor + 1)
    ] if entries else []

    entry_objs = []
    for i, spec in enumerate(entries):
        exhibitor = exhibitors[spec.get("exhibitor_index", 0)]
        kwargs = {
            k: v for k, v in spec.items()
            if k in ("species", "tag_number", "ownership_acquired_at",
                     "possession_start_at")
        }
        entry = create_entry(fair_id, exhibitor, **kwargs)
        entry_objs.append(verify_entry(entry["id"]))

    affidavits = {}
    for idx in affidavit_entries:
        spec = entries[idx]
        exhibitor = exhibitors[spec.get("exhibitor_index", 0)]
        aff_kwargs = {}
        if "withdrawal_end_date" in spec:
            aff_kwargs["withdrawal_end_date"] = spec["withdrawal_end_date"]
        affidavits[idx] = sign_affidavit(
            entry_objs[idx]["id"], exhibitor, **aff_kwargs
        )

    advance_fair_to(fair_id, "WEIGH_IN")
    for i, spec in enumerate(entries):
        weigh_entry(
            entry_objs[i]["id"], spec["weight_lbs"],
            weighed_at=spec.get("weighed_at"),
        )
        entry_objs[i] = get_entry(entry_objs[i]["id"])

    class_objs = [create_class(fair_id, **c) for c in classes]
    for entry_idx, class_idx in (entry_class_map or {}).items():
        if class_idx is None:
            entry_objs[entry_idx] = classify_entry(entry_objs[entry_idx]["id"])
        else:
            entry_objs[entry_idx] = classify_entry(
                entry_objs[entry_idx]["id"], class_objs[class_idx]["id"]
            )

    judge_objs = [create_judge(fair_id, **j) for j in judges]

    slot_objs, placing_results = [], []
    if advance_to in ("SHOWING", "AUCTION", "SETTLEMENT"):
        advance_posture(fair_id, "SHOWING")
        for s in slots:
            slot = create_ring_slot(
                fair_id,
                class_objs[s["class_index"]]["id"],
                ring_name=s.get("ring_name", "MAIN"),
                starts_at=s.get("starts_at", "2026-07-10T09:00:00Z"),
                ends_at=s.get("ends_at", "2026-07-10T10:00:00Z"),
            )
            assign_judge(slot["id"], judge_objs[s["judge_index"]]["id"])
            start_slot(slot["id"])
            slot_objs.append(get_ring_slot(slot["id"]))
        for p in placings:
            slot = slot_objs[p["slot_index"]]
            judge_id = judge_objs[slots[p["slot_index"]]["judge_index"]]["id"]
            lines = [
                {
                    "entry_id": entry_objs[line["entry_index"]]["id"],
                    "rank": line["rank"],
                    "award": line.get("award", "NONE"),
                }
                for line in p["lines"]
            ]
            placing_results.append(submit_placings(slot["id"], judge_id, lines))
        for i in range(len(entry_objs)):
            entry_objs[i] = get_entry(entry_objs[i]["id"])

    if advance_to in ("AUCTION", "SETTLEMENT"):
        advance_posture(fair_id, "AUCTION")
    if advance_to == "SETTLEMENT":
        advance_posture(fair_id, "SETTLEMENT")

    return {
        "fair": get_fair(fair_id),
        "exhibitors": exhibitors,
        "entries": entry_objs,
        "classes": [get_class(c["id"]) for c in class_objs],
        "judges": judge_objs,
        "slots": slot_objs,
        "placing_results": placing_results,
        "affidavits": affidavits,
    }


def standard_shown_entry(**kwargs) -> dict:
    """One SHOWN MARKET_STEER entry (rank 1, award NONE) in one class.

    kwargs forwarded to build_show_state; extra keys used here:
      weight_lbs, species, tag_number, class overrides, fair_overrides.
    """
    species = kwargs.pop("species", "MARKET_STEER")
    weight = kwargs.pop("weight_lbs", 1200)
    tag = kwargs.pop("tag_number", "S-001")
    class_overrides = kwargs.pop("class_overrides", {})
    class_spec = {
        "species": species,
        "class_code": class_overrides.pop("class_code", "CLS-A"),
        "weight_min_lbs": class_overrides.pop(
            "weight_min_lbs", 1000 if species == "MARKET_STEER" else 60
        ),
        "weight_max_lbs": class_overrides.pop(
            "weight_max_lbs", 1500 if species == "MARKET_STEER" else 140
        ),
        "capacity": class_overrides.pop("capacity", 5),
    }
    return build_show_state(
        entries=[{"species": species, "tag_number": tag, "weight_lbs": weight}],
        classes=[class_spec],
        entry_class_map={0: 0},
        judges=[{"qualified_species": [species]}],
        slots=[{"class_index": 0, "judge_index": 0}],
        placings=[{"slot_index": 0,
                   "lines": [{"entry_index": 0, "rank": 1, "award": "NONE"}]}],
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Tier 3/5: auction and settlement composites
# ---------------------------------------------------------------------------

def setup_sold_lot(*, hammer_price_cents: int = 50000,
                   credit_limit_cents: int = 200000,
                   add_on_amounts: list = (),
                   advance_to_settlement: bool = False,
                   **show_kwargs) -> dict:
    """Full chain: one SHOWN entry -> lot generated -> opened -> SOLD.

    Returns context with fair/entry/lot/buyer/invoice-ready state.
    """
    ctx = standard_shown_entry(advance_to="AUCTION", **show_kwargs)
    fair_id = ctx["fair"]["id"]
    buyer = create_buyer(fair_id, credit_limit_cents=credit_limit_cents)
    gen = generate_lots(fair_id)
    lot_id = gen["lot_ids"][0]
    open_lot(lot_id)
    close_sold(lot_id, buyer["id"], hammer_price_cents)
    addons = [
        create_add_on(lot_id, buyer["id"], amount) for amount in add_on_amounts
    ]
    if advance_to_settlement:
        advance_posture(fair_id, "SETTLEMENT")
        ctx["fair"] = get_fair(fair_id)
    ctx.update({
        "buyer": buyer,
        "lot": get_lot(lot_id),
        "addons": addons,
    })
    return ctx


def setup_not_sold_entry(**show_kwargs) -> dict:
    """One SHOWN entry whose lot is passed and declared no-sale."""
    ctx = standard_shown_entry(advance_to="AUCTION", **show_kwargs)
    fair_id = ctx["fair"]["id"]
    gen = generate_lots(fair_id)
    lot_id = gen["lot_ids"][0]
    open_lot(lot_id)
    close_passed(lot_id)
    lot = no_sale_lot(lot_id)
    ctx["lot"] = lot
    ctx["entry"] = get_entry(ctx["entries"][0]["id"])
    return ctx


def setup_issued_invoice(*, hammer_price_cents: int = 50000,
                         credit_limit_cents: int = 200000,
                         add_on_amounts: list = (),
                         **show_kwargs) -> dict:
    """SOLD lot (+ optional add-ons) -> SETTLEMENT -> invoice ISSUED."""
    ctx = setup_sold_lot(
        hammer_price_cents=hammer_price_cents,
        credit_limit_cents=credit_limit_cents,
        add_on_amounts=add_on_amounts,
        advance_to_settlement=True,
        **show_kwargs,
    )
    invoice = get_buyer_invoice(ctx["buyer"]["id"])
    invoice = issue_invoice(invoice["id"])
    ctx["invoice"] = invoice
    return ctx


def setup_approved_disposition(*, entry_status_path: str = "not_sold",
                               disposition_type: str = "HARVEST",
                               withdrawal_end_date: str = None,
                               scheduled_date: str = None,
                               inspection_result: str = "PASS",
                               **show_kwargs) -> dict:
    """Entry + SIGNED affidavit + APPROVED disposition + health inspection.

    entry_status_path: "not_sold" (NOT_SOLD via pass/no-sale) or "shown".
    inspection_result: None records no inspection at all.
    """
    if entry_status_path == "not_sold":
        ctx = setup_not_sold_entry(**show_kwargs)
    else:
        ctx = standard_shown_entry(advance_to="SHOWING", **show_kwargs)
    entry_id = ctx["entries"][0]["id"]
    exhibitor = ctx["exhibitors"][0]
    aff_kwargs = {}
    if withdrawal_end_date is not None:
        aff_kwargs["withdrawal_end_date"] = withdrawal_end_date
    affidavit = sign_affidavit(entry_id, exhibitor, **aff_kwargs)
    disp_kwargs = {"disposition_type": disposition_type}
    if scheduled_date is not None:
        disp_kwargs["scheduled_date"] = scheduled_date
    order = create_disposition(
        entry_id, creator_headers=make_admin_headers("admin-a"), **disp_kwargs
    )
    order = approve_disposition(order["id"], approver_id="admin-b")
    inspection = None
    if inspection_result is not None:
        inspection = record_health_inspection(entry_id, result=inspection_result)
    ctx.update({
        "affidavit": affidavit,
        "disposition": order,
        "inspection": inspection,
    })
    return ctx
