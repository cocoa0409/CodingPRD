"""Registry & purchases: chronological replay, dup-of, idempotent ingest,
key conflict, FULFILLED cycling, cancel/promote with OCC, compensating
fulfilled_quantity invariant, two-view divergence."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    create_purchase_payload,
    make_couple_headers,
    make_platform_integration_headers,
    set_clock,
    bootstrap_wedding_with_open_registry,
    bootstrap_confirmed_purchase,
)


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty / dual_variant_calc / registry_purchase_aggregation_provisional_vs_settled
# ─────────────────────────────────────────────────────────────────────────────

def test_registry_purchase_aggregation_provisional_vs_settled(api):
    """PRD §3.5: "If the tentative running total is less than or equal to
    `target_quantity`, the new row is classified `CONFIRMED` and the running
    total advances to the tentative value. If the tentative running total
    is strictly greater than `target_quantity` — the boundary is inclusive,
    so hitting `target_quantity` exactly still confirms — the new row is
    classified `PENDING_REVIEW` and its `dup_of_purchase_id` is set to the
    `id` of the earliest `CONFIRMED` purchase such that the cumulative
    running confirmed total was less than or equal to `target_quantity`
    before that purchase and strictly greater after it: the canonical
    purchase that "ate the last slot"."
    PRD §3.5: "After replay, the parent `RegistryItem`'s `fulfilled_quantity`
    is recomputed as the sum of `quantity` across all `CONFIRMED` rows, and
    `pending_quantity` as the sum of `quantity` across all `PENDING_REVIEW`
    rows."

    Design: Difficulty/dual_variant_calc/registry_purchase_aggregation_provisional_vs_settled

    Note: PRD §3.5 also pins "The `RegistryItem` must currently be `OPEN` at
    the moment of ingest". So PENDING_REVIEW via the ingest path is only
    reachable when the first purchase does NOT itself flip the item to
    FULFILLED. We use target=3, p1.qty=2, p2.qty=2: p1 confirms (fulfilled=2,
    item still OPEN), then p2's tentative=4 exceeds target=3 → PENDING_REVIEW.
    """
    set_clock("2027-01-01T00:00:00Z")
    wedding, item = bootstrap_wedding_with_open_registry(
        couple_user_id="couple_w1",
        clock_iso="2027-01-01T00:00:00Z",
        target_quantity=3,
        sku="PLATES_4PC",
    )
    integ = make_platform_integration_headers()
    couple = make_couple_headers("couple_w1")

    p1 = validate_success(api.create_purchase(
        item["id"],
        create_purchase_payload(
            platform_code="STORE_A", external_purchase_id="SA-001",
            purchaser_name="Alice", quantity=2,
            occurred_at="2027-01-02T10:00:00Z",
        ),
        integ,
    ), expected_status=201)
    p2 = validate_success(api.create_purchase(
        item["id"],
        create_purchase_payload(
            platform_code="STORE_B", external_purchase_id="SB-001",
            purchaser_name="Bob", quantity=2,
            occurred_at="2027-01-02T11:00:00Z",
        ),
        integ,
    ), expected_status=201)

    assert p1["status"] == "CONFIRMED"
    assert p2["status"] == "PENDING_REVIEW"
    assert p2["dup_of_purchase_id"] == p1["id"]

    item_after = validate_success(api.get_registry_item(item["id"], couple), expected_status=200)
    assert item_after["fulfilled_quantity"] == 2
    # PRD §3.5: "the per-item purchase list with the `include_pending` query
    # parameter set to true — surfaces every `PENDING_REVIEW` row alongside
    # the `CONFIRMED` ones".
    res_prov = validate_success(
        api.list_registry_item_purchases(
            item["id"], couple, params={"include_pending": True},
        ),
        expected_status=200,
    )
    # Provisional view lists both purchases.
    if isinstance(res_prov, dict):
        rows = res_prov.get("items") or res_prov.get("data") or []
    else:
        rows = res_prov
    statuses = {r["status"] for r in rows}
    assert "CONFIRMED" in statuses and "PENDING_REVIEW" in statuses


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty / non_linear_state_machine / registry_item_cyclic_open_fulfilled
# ─────────────────────────────────────────────────────────────────────────────

def test_registry_item_cyclic_open_fulfilled(api):
    """PRD §3.5: "If `fulfilled_quantity` is greater than or equal to
    `target_quantity`, the registry item's `status` transitions automatically
    from `OPEN` to `FULFILLED`".
    PRD §3.5: "On the `CONFIRMED` to `CANCELLED` path, the parent's
    `fulfilled_quantity` decreases by this purchase's `quantity`, the
    registry item's `version` advances by 1, any `ThankYouNote` on this
    purchase is hard-deleted, and if the registry item was previously
    `FULFILLED` and the new `fulfilled_quantity` drops below
    `target_quantity`, the registry item reverts from `FULFILLED` to `OPEN`."

    Design: Difficulty/non_linear_state_machine/registry_item_cyclic_open_fulfilled
    """
    set_clock("2027-05-01T00:00:00Z")
    wedding, item = bootstrap_wedding_with_open_registry(
        couple_user_id="couple_w6",
        clock_iso="2027-05-01T00:00:00Z",
        target_quantity=1,
        sku="TOASTER",
    )
    couple = make_couple_headers("couple_w6")
    integ = make_platform_integration_headers()
    initial = validate_success(api.get_registry_item(item["id"], couple), expected_status=200)
    assert initial["status"] == "OPEN"

    purchase = validate_success(api.create_purchase(
        item["id"],
        create_purchase_payload(
            platform_code="STORE_A", external_purchase_id="T1",
            purchaser_name="Dan", quantity=1,
            occurred_at="2027-05-02T10:00:00Z",
        ),
        integ,
    ), expected_status=201)
    assert purchase["status"] == "CONFIRMED"
    fulfilled = validate_success(api.get_registry_item(item["id"], couple), expected_status=200)
    assert fulfilled["status"] == "FULFILLED"

    cancelled = validate_success(api.cancel_purchase(
        purchase["id"], fulfilled["version"], couple,
    ), expected_status=200)
    assert cancelled["status"] == "CANCELLED"

    after = validate_success(api.get_registry_item(item["id"], couple), expected_status=200)
    assert after["status"] == "OPEN"
    assert after["fulfilled_quantity"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty / transitive_cascade / purchase_cancel_depth2_recompute_and_notedelete
# ─────────────────────────────────────────────────────────────────────────────

def test_purchase_cancel_depth2_recompute_and_notedelete(api):
    """PRD §3.5: "On the `CONFIRMED` to `CANCELLED` path, the parent's
    `fulfilled_quantity` decreases by this purchase's `quantity`, the
    registry item's `version` advances by 1, any `ThankYouNote` on this
    purchase is hard-deleted, and if the registry item was previously
    `FULFILLED` and the new `fulfilled_quantity` drops below
    `target_quantity`, the registry item reverts from `FULFILLED` to `OPEN`."
    PRD §3.6: "If a parent `Purchase` is cancelled and its `ThankYouNote`
    had previously been created, that note is hard-deleted as part of the
    cancel cascade".

    Design: Difficulty/transitive_cascade/purchase_cancel_depth2_recompute_and_notedelete
    """
    set_clock("2027-07-01T00:00:00Z")
    wedding, item, purchase, note = bootstrap_confirmed_purchase(
        couple_user_id="couple_w8",
        clock_iso="2027-07-01T00:00:00Z",
        target_quantity=1,
        quantity=1,
    )
    couple = make_couple_headers("couple_w8")
    assert purchase["status"] == "CONFIRMED"
    assert note is not None, "ThankYouNote must be auto-created for CONFIRMED purchase"
    fulfilled = validate_success(api.get_registry_item(item["id"], couple), expected_status=200)
    assert fulfilled["status"] == "FULFILLED"

    cancelled = validate_success(api.cancel_purchase(
        purchase["id"], fulfilled["version"], couple,
    ), expected_status=200)
    assert cancelled["status"] == "CANCELLED"

    after_item = validate_success(api.get_registry_item(item["id"], couple), expected_status=200)
    assert after_item["status"] == "OPEN"
    assert after_item["fulfilled_quantity"] == 0

    # The original note must be gone.
    note_lookup = api.list_thank_you_notes(couple, params={"purchase_id": purchase["id"]})
    note_data = validate_success(note_lookup, expected_status=200)
    if isinstance(note_data, dict):
        note_rows = note_data.get("items") or note_data.get("data") or []
    else:
        note_rows = note_data
    assert note_rows == [], f"ThankYouNote must be hard-deleted, got {note_rows!r}"


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty / compensating_invariant / purchase_create_cancel_preserves_fulfilled_quantity
# ─────────────────────────────────────────────────────────────────────────────

def test_purchase_create_cancel_preserves_fulfilled_quantity(api):
    """PRD §3.5: "After replay, the parent `RegistryItem`'s
    `fulfilled_quantity` is recomputed as the sum of `quantity` across all
    `CONFIRMED` rows".
    PRD §3.5: "On the `CONFIRMED` to `CANCELLED` path, the parent's
    `fulfilled_quantity` decreases by this purchase's `quantity`".

    Design: Difficulty/compensating_invariant/purchase_create_cancel_preserves_fulfilled_quantity
    """
    set_clock("2028-04-01T00:00:00Z")
    wedding, item = bootstrap_wedding_with_open_registry(
        couple_user_id="couple_w17",
        clock_iso="2028-04-01T00:00:00Z",
        target_quantity=5,
        sku="TOWELS",
    )
    couple = make_couple_headers("couple_w17")
    integ = make_platform_integration_headers()
    before = validate_success(api.get_registry_item(item["id"], couple), expected_status=200)
    qty_before = before["fulfilled_quantity"]
    assert qty_before == 0

    purchase = validate_success(api.create_purchase(
        item["id"],
        create_purchase_payload(
            platform_code="STORE_A", external_purchase_id="TW1",
            purchaser_name="Gina", quantity=2,
            occurred_at="2028-04-02T10:00:00Z",
        ),
        integ,
    ), expected_status=201)
    mid = validate_success(api.get_registry_item(item["id"], couple), expected_status=200)
    assert mid["fulfilled_quantity"] == 2

    cancelled = validate_success(api.cancel_purchase(
        purchase["id"], mid["version"], couple,
    ), expected_status=200)
    assert cancelled["status"] == "CANCELLED"

    after = validate_success(api.get_registry_item(item["id"], couple), expected_status=200)
    assert after["fulfilled_quantity"] == qty_before, (
        "compensating create+cancel pair must preserve fulfilled_quantity"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Corner / calculations / purchase_aggregation_chronological_tie_break_by_created_at
# ─────────────────────────────────────────────────────────────────────────────

def test_purchase_aggregation_chronological_tie_break_by_created_at(api):
    """PRD §3.5: "The replay is sorted by `occurred_at` ascending as the
    primary key and by each row's `created_at` ascending as the deterministic
    tie-break (the `id` is never used as a tie-break)."

    Design: Corner/calculations/purchase_aggregation_chronological_tie_break_by_created_at

    Note: PRD §3.5 pins "The `RegistryItem` must currently be `OPEN` at the
    moment of ingest", so we use target=2 with two qty=2 purchases sharing
    the same occurred_at: p_first ingests when item is OPEN (fulfilled=2 fills
    target; status flips to FULFILLED in the cascade AFTER the precondition
    check), and p_second must therefore land when item is still OPEN — which
    requires target > p_first.qty. Use target=3, p_first.qty=1, p_second.qty=3
    with identical occurred_at: created_at tie-break makes p_first earlier,
    so p_first CONFIRMED, p_second PENDING_REVIEW pointing at p_first.
    """
    set_clock("2027-01-01T00:00:00Z")
    wedding, item = bootstrap_wedding_with_open_registry(
        couple_user_id="couple_ch",
        clock_iso="2027-01-01T00:00:00Z",
        target_quantity=3,
        sku="MIXER",
    )
    integ = make_platform_integration_headers()
    occurred = "2027-02-02T10:00:00Z"
    p_first = validate_success(api.create_purchase(
        item["id"],
        create_purchase_payload(
            platform_code="STORE_A", external_purchase_id="M1",
            purchaser_name="Hal", quantity=1, occurred_at=occurred,
        ),
        integ,
    ), expected_status=201)
    p_second = validate_success(api.create_purchase(
        item["id"],
        create_purchase_payload(
            platform_code="STORE_B", external_purchase_id="M2",
            purchaser_name="Ivy", quantity=3, occurred_at=occurred,
        ),
        integ,
    ), expected_status=201)
    assert p_first["status"] == "CONFIRMED"
    assert p_second["status"] == "PENDING_REVIEW"
    assert p_second["dup_of_purchase_id"] == p_first["id"]


# ─────────────────────────────────────────────────────────────────────────────
# Corner / calculations / purchase_idempotent_replay_same_quantity
# ─────────────────────────────────────────────────────────────────────────────

def test_purchase_idempotent_replay_same_quantity(api):
    """PRD §3.5: "The pair of `platform_code` and `external_purchase_id` is
    globally unique: a re-ingest of an already-recorded pair is idempotent,
    returning the existing row's `id` with HTTP 200 and without mutating
    any aggregate counters."

    Design: Corner/calculations/purchase_idempotent_replay_same_quantity
    """
    set_clock("2027-01-01T00:00:00Z")
    wedding, item = bootstrap_wedding_with_open_registry(
        couple_user_id="couple_id",
        clock_iso="2027-01-01T00:00:00Z",
        target_quantity=5,
        sku="WOK",
    )
    integ = make_platform_integration_headers()
    couple = make_couple_headers("couple_id")
    payload = create_purchase_payload(
        platform_code="STORE_A", external_purchase_id="W1",
        purchaser_name="Jane", quantity=2,
        occurred_at="2027-01-02T10:00:00Z",
    )
    p_orig = validate_success(api.create_purchase(item["id"], payload, integ),
                              expected_status=201)
    before = validate_success(api.get_registry_item(item["id"], couple), expected_status=200)

    res = api.create_purchase(item["id"], payload, integ)
    # PRD: re-ingest returns "HTTP 200". Cannot pass expected_status=201; use
    # framework validate with explicit 200.
    p_replay = validate_success(res, expected_status=200)
    assert p_replay["id"] == p_orig["id"]
    after = validate_success(api.get_registry_item(item["id"], couple), expected_status=200)
    assert after["fulfilled_quantity"] == before["fulfilled_quantity"]
    assert after["version"] == before["version"]


# ─────────────────────────────────────────────────────────────────────────────
# Corner / calculations / purchase_duplicate_key_conflicting_quantity_rejected
# ─────────────────────────────────────────────────────────────────────────────

def test_purchase_duplicate_key_conflicting_quantity_rejected(api):
    """PRD §3.5: "The narrow exception is when the same key arrives with a
    **different** `quantity`: that is treated as a true conflict and rejected
    with `ERR_DUPLICATE_EXTERNAL_PURCHASE` (HTTP 409)."

    Design: Corner/calculations/purchase_duplicate_key_conflicting_quantity_rejected
    """
    set_clock("2027-01-01T00:00:00Z")
    wedding, item = bootstrap_wedding_with_open_registry(
        couple_user_id="couple_kc",
        clock_iso="2027-01-01T00:00:00Z",
        target_quantity=5,
        sku="PAN",
    )
    integ = make_platform_integration_headers()
    validate_success(api.create_purchase(
        item["id"],
        create_purchase_payload(
            platform_code="STORE_A", external_purchase_id="KC1",
            purchaser_name="Ken", quantity=2,
            occurred_at="2027-01-02T10:00:00Z",
        ),
        integ,
    ), expected_status=201)

    res = api.create_purchase(
        item["id"],
        create_purchase_payload(
            platform_code="STORE_A", external_purchase_id="KC1",
            purchaser_name="Ken", quantity=3,
            occurred_at="2027-01-02T10:00:00Z",
        ),
        integ,
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_EXTERNAL_PURCHASE, expected_status=409)


# ─────────────────────────────────────────────────────────────────────────────
# Corner / errors / error_stale_version_on_cancel_duplicate
# ─────────────────────────────────────────────────────────────────────────────

def test_error_stale_version_on_cancel_duplicate(api):
    """PRD §2.8: "Cancelling or promoting any `Purchase` requires a
    non-optional `expected_registry_item_version` field in the request body.
    The server compares it to the parent `RegistryItem`'s current `version`;
    on mismatch the rejection is again `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/errors/error_stale_version_on_cancel_duplicate
    """
    set_clock("2027-01-01T00:00:00Z")
    wedding, item = bootstrap_wedding_with_open_registry(
        couple_user_id="couple_sv",
        clock_iso="2027-01-01T00:00:00Z",
        target_quantity=2,
        sku="GR",
    )
    couple = make_couple_headers("couple_sv")
    integ = make_platform_integration_headers()
    p_sv = validate_success(api.create_purchase(
        item["id"],
        create_purchase_payload(
            platform_code="STORE_A", external_purchase_id="SV1",
            purchaser_name="Lee", quantity=1,
            occurred_at="2027-01-02T10:00:00Z",
        ),
        integ,
    ), expected_status=201)
    pre = validate_success(api.get_registry_item(item["id"], couple), expected_status=200)
    stale_version = pre["version"]

    # Second purchase lands and bumps the registry-item version.
    validate_success(api.create_purchase(
        item["id"],
        create_purchase_payload(
            platform_code="STORE_B", external_purchase_id="SV2",
            purchaser_name="Mae", quantity=1,
            occurred_at="2027-01-02T11:00:00Z",
        ),
        integ,
    ), expected_status=201)

    res = api.cancel_purchase(p_sv["id"], stale_version, couple)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    after = validate_success(api.get_purchase(p_sv["id"], couple), expected_status=200)
    assert after["status"] == "CONFIRMED", "no transition should have occurred"
