"""Shipment compliance gates, state shipping limits, boundary precision, and
validation-priority conflicts.

Translates difficulty queue A (boundary_precision_check, priority_pair_validation_
conflict) plus the non-stub validation corners that gate shipment/bottling/POS.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_shipment_payload, create_tasting_order_payload, bottle_line,
    create_release_payload, create_member_payload, create_membership_payload,
    setup_club_ready, setup_scheduled_shipment, setup_active_product,
    setup_open_release, set_clock, create_winery, create_batch_in_bottling,
    create_product, bottle_run, TEST_USERS,
)

CO = TEST_USERS["compliance_officer_headers"]
CM = TEST_USERS["cellar_manager_headers"]
CLM = TEST_USERS["club_manager_headers"]
TRS = TEST_USERS["tasting_room_staff_headers"]


# ─── boundary_precision_check ──────────────────────────

def test_state_limit_passes_at_exact_case_limit(api):
    """PRD §3.8: "If that running total of prior cases plus this shipment's cases is
    strictly greater than the destination state's case limit, the gate fails and the
    shipment is held with reason `STATE_LIMIT`".
    PRD §3.8: "Reaching exactly the limit passes; only strictly exceeding it fails.
    The per-state limits are 24.0 cases for `CA`".

    A CA member with 23 prior cases RELEASED claims 1 more: prior+this == 24 ==
    limit, which PASSES under strict >.

    Design: Difficulty/boundary_precision_check/state_limit_strict_greater_at_exact_case_limit
    """
    set_clock("2026-06-15T00:00:00Z")
    winery, product, release = setup_open_release(
        pool_bottles=288, per_member_cap=288, bottled_bottles=288,
        opens_at="2026-06-01T00:00:00Z", closes_at="2026-07-01T00:00:00Z",
        product_overrides={"list_price_cents": 5000})
    member = get_success_data(api.create_member(
        create_member_payload(winery["id"], ship_to_state_code="CA"), CLM))
    member = get_success_data(api.transition_member(member["id"], {"action": "ACTIVATE"}, CLM))
    membership = get_success_data(api.create_membership(
        create_membership_payload(winery["id"], member["id"], tier="SILVER",
                                  bottles_per_shipment=12), CLM))
    get_success_data(api.transition_membership(membership["id"], {"action": "ACTIVATE"}, CLM))

    sh_prior = get_success_data(api.create_shipment(
        create_shipment_payload(winery["id"], membership["id"], release["id"], 276), CLM))
    validate_success(api.transition_shipment(sh_prior["id"], {"action": "RELEASE"}, CLM), 200)

    sh = get_success_data(api.create_shipment(
        create_shipment_payload(winery["id"], membership["id"], release["id"], 12), CLM))
    released = validate_success(api.transition_shipment(sh["id"], {"action": "RELEASE"}, CLM), 200)
    assert released["status"] == "RELEASED", released["status"]

    rel = get_success_data(api.get_release(release["id"], CM))
    assert rel["committed_bottles"] == 288, rel["committed_bottles"]


def test_empty_line_items_pos_rejected(api):
    """PRD §2.9: "field-level request validity (`ERR_INVALID_REQUEST`)."
    PRD §3.9: "Each entry in `line_items` is an object naming a `product_id`, a
    `kind` of `FLIGHT`, `BOTTLE`, or `GLASS`, a `quantity`, and optionally a
    `unit_price_cents`".

    Opening a tasting order with line_items = [] is rejected ERR_INVALID_REQUEST.

    Design: Difficulty/boundary_precision_check/empty_line_items_zero_quantity_pos_rejected
    """
    winery = create_winery(name="Empty Co", ttb_permit_number="EMP-1")
    res = api.create_tasting_order(
        create_tasting_order_payload(winery["id"], []), TRS)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


# ─── priority_pair_validation_conflict ─────────────────

def test_invalid_state_beats_age_on_shipment_release(api):
    """PRD §2.9: "then, for a transition, whether the target resource is in a state
    that permits the requested transition (`ERR_INVALID_STATE`); then the
    optimistic-concurrency version check ... then the business-safety gates in the
    order age (`ERR_AGE_RESTRICTION`)".

    A RELEASE on an already-RELEASED shipment returns the higher-priority
    ERR_INVALID_STATE rather than any business gate.

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_age_on_shipment_release
    """
    winery, product, release, member, membership, shipment = setup_scheduled_shipment(
        requested_bottles=6, pool_bottles=6, per_member_cap=6, tier="GOLD",
        bottled_bottles=20, list_price_cents=5000)
    validate_success(api.transition_shipment(shipment["id"], {"action": "RELEASE"}, CLM), 200)
    # Second RELEASE on a RELEASED shipment: state check (p6) precedes any gate.
    res = api.transition_shipment(shipment["id"], {"action": "RELEASE"}, CLM)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_age_safety_beats_inventory_on_pos_pay(api):
    """PRD §2.8: "compliance checks take precedence over inventory and fiscal checks
    in evaluation order, so that a compliance failure surfaces as a compliance error
    rather than being masked by a downstream inventory or budget condition."
    PRD §3.9: "if any line is age-restricted, either `guest_age_verified` must be
    true or an attached member must be at least 21 years old (otherwise
    `ERR_AGE_RESTRICTION`)".

    PAY with unverified under-21 guest AND a bottle line exceeding inventory
    returns the safety error ERR_AGE_RESTRICTION before the inventory shortfall.

    Design: Difficulty/priority_pair_validation_conflict/age_safety_beats_inventory_fiscal_on_pos_pay
    """
    set_clock("2026-06-15T00:00:00Z")
    winery, batch, product = setup_active_product(
        bottled_bottles=10, product_overrides={"list_price_cents": 5000})
    order = get_success_data(api.create_tasting_order(
        create_tasting_order_payload(winery["id"], [bottle_line(product["id"], 999)],
                                     guest_age_verified=False), TRS))
    res = api.transition_tasting_order(order["id"], {"action": "PAY"}, TRS)
    validate_error(res, "ERR_AGE_RESTRICTION", expected_status=422)


# ─── Corner: validations (non-stub) ────────────────────

def test_per_member_cap_exceeded_on_schedule(api):
    """PRD §3.7: "Scheduling also enforces the per-member allocation cap: a
    membership's cumulative reserved-plus-committed bottles on a single release must
    not exceed that release's `per_member_cap`, and a claim that would push it past
    the cap is rejected with `ERR_PER_MEMBER_CAP_EXCEEDED`."

    Release per_member_cap=6; scheduling 7 bottles -> ERR_PER_MEMBER_CAP_EXCEEDED.

    Design: Corner/validations/per_member_cap_exceeded_on_schedule
    """
    winery, product, release, member, membership = setup_club_ready(
        pool_bottles=12, per_member_cap=6, tier="SILVER", bottled_bottles=30,
        list_price_cents=5000)
    res = api.create_shipment(
        create_shipment_payload(winery["id"], membership["id"], release["id"], 7), CLM)
    validate_error(res, "ERR_PER_MEMBER_CAP_EXCEEDED", expected_status=422)


def test_pa_state_forbids_any_dtc_shipment(api):
    """PRD §3.8: "The per-state limits are 24.0 cases for `CA`, 36.0 cases for `NY`,
    9.0 cases for `TX`, and 0.0 cases for `PA`... Because the `PA` limit is zero, any
    case at all to Pennsylvania fails the gate."
    PRD §3.7: "the rolling state shipping limit for the shipment's
    `ship_to_state_code` must not be exceeded (otherwise the hold reason is
    `STATE_LIMIT`)".

    A PA member's RELEASE of 1 case diverts to HELD with hold_reason STATE_LIMIT.

    Design: Corner/validations/pa_state_forbids_any_dtc_shipment
    """
    winery, product, release, member, membership, shipment = setup_scheduled_shipment(
        requested_bottles=12, pool_bottles=12, per_member_cap=12, tier="SILVER",
        bottled_bottles=30, list_price_cents=5000, ship_to_state_code="PA")
    held = validate_success(api.transition_shipment(shipment["id"], {"action": "RELEASE"}, CLM), 200)
    assert held["status"] == "HELD", held["status"]
    assert held["hold_reason"] == "STATE_LIMIT", held["hold_reason"]


def test_under_age_member_activate_rejected(api):
    """PRD §3.6: "A `ClubManager` activates the member, transitioning `PROSPECT →
    ACTIVE`, permitted only while the member is `PROSPECT` and only if the member is
    at least 21 years old at the current clock, computed from `date_of_birth`; an
    underage member is rejected with `ERR_AGE_RESTRICTION`."

    Member born 2010-01-01 is 16 at clock 2026-06-15; ACTIVATE -> ERR_AGE_RESTRICTION.

    Design: Corner/validations/under_age_member_activate_rejected
    """
    set_clock("2026-06-15T00:00:00Z")
    winery = create_winery(name="Yo Co", ttb_permit_number="YO-1")
    member = get_success_data(api.create_member(
        create_member_payload(winery["id"], full_name="Minnie Minor", email="min@x.com",
                              date_of_birth="2010-01-01T00:00:00Z"), CLM))
    res = api.transition_member(member["id"], {"action": "ACTIVATE"}, CLM)
    validate_error(res, "ERR_AGE_RESTRICTION", expected_status=422)
    m = get_success_data(api.get_member(member["id"], CLM))
    assert m["status"] == "PROSPECT", m["status"]


def test_winery_suspended_blocks_bottling(api):
    """PRD §2.8: "while it is `SUSPENDED`, every taxable removal is blocked —
    specifically bottling runs, shipment releases, and distribution shipments. An
    attempt to perform any of these three operations while the owning winery is
    `SUSPENDED` is rejected with `ERR_WINERY_SUSPENDED` (HTTP 409)".

    Bottling run on a BOTTLING batch of a SUSPENDED winery -> ERR_WINERY_SUSPENDED.

    Design: Corner/validations/winery_suspended_blocks_bottling
    """
    winery = create_winery(name="Su Co", ttb_permit_number="SU-1")
    batch = create_batch_in_bottling(winery["id"])
    product = create_product(winery["id"], batch["id"], sku="S1")
    # Re-read the winery's current version: batch creation recomputed
    # bulk_volume_gallons, which advances the winery version.
    wv = get_success_data(api.get_winery(winery["id"], CO))["version"]
    get_success_data(api.transition_winery(
        winery["id"], {"action": "SUSPEND", "expected_winery_version": wv}, CO))
    res = api.create_bottling_run(batch["id"], {"product_id": product["id"], "requested_bottles": 10}, CM)
    validate_error(res, "ERR_WINERY_SUSPENDED", expected_status=409)


def test_insufficient_bulk_on_bottling(api):
    """PRD §3.3: "the bulk this run would remove does not exceed the batch's
    `available_bulk_gallons` (otherwise `ERR_INSUFFICIENT_BULK`)."

    A 5-gallon batch cannot bottle 100x750ml (~19.8 gal removal) -> ERR_INSUFFICIENT_BULK.

    Design: Corner/validations/insufficient_bulk_on_bottling
    """
    winery = create_winery(name="Ib Co", ttb_permit_number="IB-1")
    batch = create_batch_in_bottling(winery["id"], batch_overrides={"volume_in_gallons": 5})
    product = create_product(winery["id"], batch["id"], sku="S1")
    res = api.create_bottling_run(batch["id"], {"product_id": product["id"], "requested_bottles": 100}, CM)
    validate_error(res, "ERR_INSUFFICIENT_BULK", expected_status=409)


def test_insufficient_points_on_pos_redeem(api):
    """PRD §3.9: "and `redeem_points` must not exceed the attached membership's
    `loyalty_points` (otherwise `ERR_INSUFFICIENT_POINTS`)."

    A GOLD membership with 0 points paying an order with redeem_points=10 ->
    ERR_INSUFFICIENT_POINTS.

    Design: Corner/validations/insufficient_points_on_pos_redeem
    """
    set_clock("2026-06-15T00:00:00Z")
    winery, batch, product = setup_active_product(
        bottled_bottles=10, product_overrides={"list_price_cents": 5000})
    member = get_success_data(api.create_member(
        create_member_payload(winery["id"], full_name="Gil Gold", email="gil@x.com"), CLM))
    member = get_success_data(api.transition_member(member["id"], {"action": "ACTIVATE"}, CLM))
    membership = get_success_data(api.create_membership(
        create_membership_payload(winery["id"], member["id"], tier="GOLD"), CLM))
    get_success_data(api.transition_membership(membership["id"], {"action": "ACTIVATE"}, CLM))

    order = get_success_data(api.create_tasting_order(
        create_tasting_order_payload(winery["id"], [bottle_line(product["id"], 1)],
                                     member_id=member["id"], guest_age_verified=True,
                                     redeem_points=10), TRS))
    res = api.transition_tasting_order(order["id"], {"action": "PAY"}, TRS)
    validate_error(res, "ERR_INSUFFICIENT_POINTS", expected_status=422)


def test_release_open_insufficient_inventory(api):
    """PRD §3.5: "Opening transitions the release `DRAFT → OPEN` and is permitted
    only while the release is `DRAFT`, only while the product is `ACTIVE`, and only
    if the product's `free_bottles` is at least the `pool_bottles` being set aside
    (otherwise `ERR_INSUFFICIENT_INVENTORY`)".

    A pool of 50 against a product with only 10 free bottles -> ERR_INSUFFICIENT_INVENTORY.

    Design: Corner/validations/release_open_insufficient_inventory
    """
    winery, batch, product = setup_active_product(
        bottled_bottles=10, product_overrides={"list_price_cents": 5000})
    release = get_success_data(api.create_release(
        create_release_payload(winery["id"], product["id"], pool_bottles=50, per_member_cap=12), CM))
    pv = get_success_data(api.get_product(product["id"], CM))["version"]
    res = api.transition_release(release["id"], {
        "action": "OPEN_RELEASE", "expected_release_version": release["version"],
        "expected_product_version": pv}, CM)
    validate_error(res, "ERR_INSUFFICIENT_INVENTORY", expected_status=409)
