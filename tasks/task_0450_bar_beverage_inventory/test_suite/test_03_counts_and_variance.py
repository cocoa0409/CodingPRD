"""Physical counts: closing-unit resolution, theoretical-vs-actual variance,
OCC version guarding, the half-open count window, and count-line constraints.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_product, create_submitted_po, create_draft_invoice_with_lines,
    create_published_recipe, create_menu_item, record_sales,
    open_count_session, add_count_line, open_session_with_unit_line,
    open_session_with_weight_line, finalize_session, find_count_line_for_product,
    get_product, set_clock,
    INVENTORY_MANAGER, PURCHASING_AGENT, BAR_MANAGER,
)


def test_depletion_theoretical_vs_actual_variance_on_countline(api):
    """PRD §3.7: "Theoretical depletion is built forward from sales: over every active
    menu item that sells a published recipe containing this product, the system sums the
    item's units sold within the window, multiplied by the product's `pour_ml` in that
    recipe, divided by the product's `container_volume_ml`, and rounds the running total
    half-up to four decimal places at the end — this is the line's `theoretical_units`.
    Actual depletion is the prior closing figure plus the received-since figure minus this
    line's `closing_units`. The line's `variance_units` is the actual depletion minus the
    theoretical depletion, rounded half-up to four decimal places."
    PRD §3.7: "The line's `variance_cost_cents` is `variance_units` multiplied by the
    product's `unit_cost_cents`, rounded half-up to a whole cent. The session's
    `total_variance_cost_cents` is the sum of the signed `variance_cost_cents` across all
    of its lines."

    Design: Difficulty/dual_variant_calc/depletion_theoretical_vs_actual_variance_on_countline
    """
    set_clock("2026-03-01T00:00:00Z")
    teq = create_product(sku="TEQ-750", name="Tequila", container_volume_ml=750,
                         unit_cost_cents=2400, empty_container_weight_g=500,
                         density_g_per_ml=0.94, case_pack=12)
    rec = create_published_recipe("Margarita", [{"product_id": teq["id"], "pour_ml": 50}])
    mi = create_menu_item(rec["id"], menu_price_cents=1300)
    # PO/invoice receive 8 units at landed cost 2495.
    po = create_submitted_po([{"product_id": teq["id"], "ordered_qty": 8, "unit_cost_cents": 2495}])
    inv = create_draft_invoice_with_lines(po["id"], [
        {"product_id": teq["id"], "received_qty": 8, "unit_cost_cents": 2495}])
    validate_success(api.post_invoice(inv["id"], PURCHASING_AGENT))
    record_sales(mi["id"], 40, "2026-03-10T00:00:00Z")
    set_clock("2026-03-31T00:00:00Z")
    session = open_count_session("March end", "2026-03-31T00:00:00Z")
    line = add_count_line(session["id"], teq["id"], "UNITS", session["version"], counted_units=4.5)

    data = validate_success(api.finalize_count_session(
        session["id"], {"expected_count_session_version": line["version"]}, INVENTORY_MANAGER))
    assert data["status"] == "FINALIZED"
    assert data["total_variance_cost_cents"] == 2079, \
        f"total variance {data['total_variance_cost_cents']}"

    cl = find_count_line_for_product(session["id"], teq["id"])
    assert cl["theoretical_units"] == 2.6667, f"theoretical {cl['theoretical_units']}"
    assert cl["variance_units"] == 0.8333, f"variance_units {cl['variance_units']}"
    assert cl["variance_cost_cents"] == 2079, f"variance_cost {cl['variance_cost_cents']}"


def test_weight_based_closing_units_resolved_at_finalize(api):
    """PRD §3.7: "For a `WEIGHT` line, the system first computes the net liquid weight as
    `gross_weight_g` minus the product's `empty_container_weight_g`; converts that to
    remaining volume by dividing the net liquid weight by the product's `density_g_per_ml`,
    rounded half-up to one decimal place; and then expresses that as a container fraction
    by dividing the remaining volume by the product's `container_volume_ml`, rounded
    half-up to three decimal places."
    PRD §3.7: "Finalization closes the loop on stock: each counted product's
    `on_hand_units` is overwritten with that line's `closing_units`, making the count the
    authoritative on-hand figure."

    Design: Corner/calculations/weight_based_closing_units_correct
    """
    gin = create_product(sku="GIN-WT", name="Gin", container_volume_ml=750, unit_cost_cents=2000,
                         empty_container_weight_g=500, density_g_per_ml=0.94)
    session, version = open_session_with_weight_line(gin["id"], 980, label="W",
                                                     counted_at="2026-02-10T00:00:00Z")
    finalize_session(session["id"], version)

    cl = find_count_line_for_product(session["id"], gin["id"])
    assert cl["closing_units"] == 0.681, f"closing_units {cl['closing_units']}"
    refreshed = get_product(gin["id"])
    assert refreshed["on_hand_units"] == 0.681, f"on_hand {refreshed['on_hand_units']}"


def test_weight_below_tare_rejected_at_finalize(api):
    """PRD §3.7: "A weight line whose `gross_weight_g` does not exceed the product's
    `empty_container_weight_g` would imply a net liquid weight that is not positive, and
    is rejected with `ERR_WEIGHT_BELOW_TARE` (HTTP 422); this tare check is enforced both
    when the weight line is added and at finalize."

    Design: Corner/validations/weight_below_tare_rejected
    """
    gin = create_product(sku="GIN-BT", name="Gin", container_volume_ml=750, unit_cost_cents=2000,
                         empty_container_weight_g=500, density_g_per_ml=0.94)
    session = open_count_session("BT", "2026-02-10T00:00:00Z")
    # gross 500 == empty 500 -> net liquid 0 (not positive). Tare check fires at add or
    # finalize; assert on whichever surfaces it.
    add_resp = api.add_count_line(session["id"], {
        "product_id": gin["id"], "count_method": "WEIGHT", "gross_weight_g": 500,
        "expected_count_session_version": session["version"]}, INVENTORY_MANAGER)
    if add_resp.status_code >= 400:
        validate_error(add_resp, ApiErrorId.ERR_WEIGHT_BELOW_TARE)
    else:
        line = add_resp.json()["data"]
        validate_error(
            api.finalize_count_session(
                session["id"], {"expected_count_session_version": line["version"]}, INVENTORY_MANAGER),
            ApiErrorId.ERR_WEIGHT_BELOW_TARE)


def test_new_count_session_starts_open_version_one(api):
    """PRD §3.7: "the session is born `OPEN` with a `version` of 1 and a
    `total_variance_cost_cents` of 0."

    Design: Corner/state_machines/new_count_session_starts_open_version_one
    """
    data = validate_success(api.create_count_session(
        {"label": "Fresh", "counted_at": "2026-02-01T00:00:00Z"}, INVENTORY_MANAGER),
        expected_status=201)
    assert data["status"] == "OPEN"
    assert data["version"] == 1


def test_occ_correct_version_add_succeeds_and_increments(api):
    """PRD §2.6: "When a caller adds a count line to a session, the request must include
    `expected_count_session_version` carrying the `version` of the `CountSession` the
    caller last observed."
    PRD §2.4: "an integer `version` that begins at 1 on creation and increments by
    exactly 1 on each subsequent mutation."

    Design: Corner/cross_cutting/occ_correct_version_succeeds_and_increments
    """
    p = create_product(sku="P-OK", name="A", container_volume_ml=750, unit_cost_cents=100)
    session = open_count_session("OK", "2026-02-10T00:00:00Z")
    data = validate_success(api.add_count_line(session["id"], {
        "product_id": p["id"], "count_method": "UNITS", "counted_units": 2,
        "expected_count_session_version": session["version"]}, INVENTORY_MANAGER),
        expected_status=201)
    refreshed = validate_success(api.get_count_session(session["id"], INVENTORY_MANAGER))
    assert refreshed["version"] == 2, "session version 1 -> 2 after add"


def test_occ_stale_version_on_countline_add_rejected(api):
    """PRD §2.6: "If that value does not equal the session's current `version` on the
    server, the add is rejected with `ERR_STALE_VERSION` (HTTP 412). This protects against
    the case where a prior add — or a finalize the caller never saw — has already advanced
    the session and its derived totals, leaving the caller's view stale."

    Design: Corner/cross_cutting/occ_stale_version_on_countline_add_rejected
    """
    pa = create_product(sku="P-ST1", name="A", container_volume_ml=750, unit_cost_cents=100)
    pb = create_product(sku="P-ST2", name="B", container_volume_ml=750, unit_cost_cents=100)
    session = open_count_session("ST", "2026-02-10T00:00:00Z")
    stale_version = session["version"]  # version 1
    # First add bumps session to version 2.
    add_count_line(session["id"], pa["id"], "UNITS", stale_version, counted_units=2)
    # Second add reuses the now-stale version 1.
    validate_error(api.add_count_line(session["id"], {
        "product_id": pb["id"], "count_method": "UNITS", "counted_units": 1,
        "expected_count_session_version": stale_version}, INVENTORY_MANAGER),
        ApiErrorId.ERR_STALE_VERSION)


def test_duplicate_count_line_for_product_rejected(api):
    """PRD §3.7: "A session may hold at most one count line per product; a second line
    for a product already counted in the session is rejected with
    `ERR_DUPLICATE_COUNT_LINE` (HTTP 409)."

    Design: Corner/validations/duplicate_count_line_for_product_rejected
    """
    p = create_product(sku="P-DC", name="A", container_volume_ml=750, unit_cost_cents=100)
    session, version = open_session_with_unit_line(p["id"], 2, label="DC",
                                                   counted_at="2026-02-10T00:00:00Z")
    validate_error(api.add_count_line(session["id"], {
        "product_id": p["id"], "count_method": "UNITS", "counted_units": 3,
        "expected_count_session_version": version}, INVENTORY_MANAGER),
        ApiErrorId.ERR_DUPLICATE_COUNT_LINE)


def test_finalize_already_finalized_session_rejected(api):
    """PRD §3.7: "An `InventoryManager` finalizes a session only when it is `OPEN`, has
    at least one line, every line measures a distinct product, and the supplied
    `expected_count_session_version` still matches the session's `version`."
    PRD §2.5: "state legality before optimistic-concurrency version checks."

    Design: Corner/state_machines/finalize_terminal_count_session_rejected
    """
    p = create_product(sku="P-FT", name="A", container_volume_ml=750, unit_cost_cents=100)
    session, version = open_session_with_unit_line(p["id"], 1, label="C",
                                                   counted_at="2026-02-01T00:00:00Z")
    finalized = finalize_session(session["id"], version)
    # Re-finalize a FINALIZED session: state precondition fails before OCC.
    validate_error(api.finalize_count_session(
        session["id"], {"expected_count_session_version": finalized["version"]}, INVENTORY_MANAGER),
        ApiErrorId.ERR_INVALID_STATE)


def test_count_window_must_be_strictly_after_prior_finalized(api):
    """PRD §3.7: "There is one further temporal precondition: the session's `counted_at`
    must be strictly later than the `counted_at` of the most recent finalized session that
    shares any product with this one, so that the per-product depletion windows — which are
    half-open intervals — neither overlap nor abut at an equal `counted_at`. A finalize
    that violates this ordering is rejected with `ERR_COUNT_WINDOW_OVERLAP` (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/count_window_strict_after_half_open
    """
    set_clock("2026-03-20T00:00:00Z")
    gin = create_product(sku="GIN-O8", name="Gin", container_volume_ml=750, unit_cost_cents=2000)
    s1, v1 = open_session_with_unit_line(gin["id"], 3, label="First",
                                         counted_at="2026-03-15T00:00:00Z")
    finalize_session(s1["id"], v1)
    # Second session shares the product at the exact same counted_at -> abutment forbidden.
    s2, v2 = open_session_with_unit_line(gin["id"], 2, label="Second same instant",
                                         counted_at="2026-03-15T00:00:00Z")
    validate_error(api.finalize_count_session(
        s2["id"], {"expected_count_session_version": v2}, INVENTORY_MANAGER),
        ApiErrorId.ERR_COUNT_WINDOW_OVERLAP)


def test_count_window_strictly_later_counted_at_succeeds(api):
    """PRD §3.7: "the session's `counted_at` must be strictly later than the `counted_at`
    of the most recent finalized session that shares any product with this one, so that the
    per-product depletion windows — which are half-open intervals — neither overlap nor abut
    at an equal `counted_at`."

    Design: Difficulty/resource_temporal_overlap/count_window_strict_after_half_open
    """
    set_clock("2026-03-20T00:00:00Z")
    gin = create_product(sku="GIN-O8B", name="Gin", container_volume_ml=750, unit_cost_cents=2000)
    s1, v1 = open_session_with_unit_line(gin["id"], 3, label="First",
                                         counted_at="2026-03-15T00:00:00Z")
    finalize_session(s1["id"], v1)
    # Second session's counted_at is strictly after the prior -> the ordering precondition holds.
    s2, v2 = open_session_with_unit_line(gin["id"], 2, label="Second later",
                                         counted_at="2026-03-16T00:00:00Z")
    data = validate_success(api.finalize_count_session(
        s2["id"], {"expected_count_session_version": v2}, INVENTORY_MANAGER))
    assert data["status"] == "FINALIZED", "strictly-later counted_at passes the window check"


def test_finalize_overwrites_on_hand_with_closing_units(api):
    """PRD §3.7: "Finalization closes the loop on stock: each counted product's
    `on_hand_units` is overwritten with that line's `closing_units`, making the count the
    authoritative on-hand figure, and each such product recomputes `needs_reorder`."
    PRD §3.7: "For a `UNITS` line, the closing figure is simply the supplied
    `counted_units`."

    Design: Difficulty/dual_variant_calc/depletion_theoretical_vs_actual_variance_on_countline
    """
    # No sales -> theoretical depletion 0; UNITS closing 6 becomes the authoritative on_hand.
    set_clock("2026-04-01T00:00:00Z")
    p = create_product(sku="P-FIN", name="A", container_volume_ml=750, unit_cost_cents=2000)
    session, version = open_session_with_unit_line(p["id"], 6, label="Apr",
                                                   counted_at="2026-04-01T00:00:00Z")
    finalize_session(session["id"], version)
    assert get_product(p["id"])["on_hand_units"] == 6, "finalize overwrites on_hand with closing_units"
    cl = find_count_line_for_product(session["id"], p["id"])
    assert cl["closing_units"] == 6
    assert cl["theoretical_units"] == 0, "no sales in window -> theoretical depletion 0"
