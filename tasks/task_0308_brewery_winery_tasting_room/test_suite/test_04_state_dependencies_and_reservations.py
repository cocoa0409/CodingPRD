"""Cross-entity state dependencies and reservation/release temporal gates.

Translates difficulty queue A (cross_entity_state_dependency,
resource_temporal_overlap) plus the non-stub reservation-state corners.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_member_payload, create_membership_payload, create_shipment_payload,
    create_reservation_payload, create_winery, create_batch, create_product,
    setup_open_release, setup_active_member, setup_active_membership, set_clock,
    create_confirmed_reservation, TEST_USERS,
)

CO = TEST_USERS["compliance_officer_headers"]
CM = TEST_USERS["cellar_manager_headers"]
CLM = TEST_USERS["club_manager_headers"]
TRS = TEST_USERS["tasting_room_staff_headers"]


# ─── cross_entity_state_dependency ─────────────────────

def test_membership_activate_requires_member_active(api):
    """PRD §3.6: "It is activated, transitioning `ENROLLED → ACTIVE`, permitted only
    while the membership is `ENROLLED` and only while the owning member is `ACTIVE`".

    A membership ACTIVATE while its member is still PROSPECT -> ERR_INVALID_STATE.

    Design: Difficulty/cross_entity_state_dependency/membership_activate_requires_member_active
    """
    set_clock("2026-06-15T00:00:00Z")
    winery = create_winery(name="Dep Co", ttb_permit_number="DEP-1")
    member = get_success_data(api.create_member(
        create_member_payload(winery["id"], full_name="Pat Prospect", email="pat@x.com"), CLM))
    membership = get_success_data(api.create_membership(
        create_membership_payload(winery["id"], member["id"], tier="SILVER"), CLM))
    res = api.transition_membership(membership["id"], {"action": "ACTIVATE"}, CLM)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_product_activate_requires_batch_bottling_or_closed(api):
    """PRD §3.4: "A `CellarManager` activates a product, transitioning `DRAFT →
    ACTIVE`, which is permitted only while the product is `DRAFT`, only if its source
    batch is in `BOTTLING` or `CLOSED`".

    A product ACTIVATE while its source batch is only AGING -> ERR_INVALID_STATE.

    Design: Difficulty/cross_entity_state_dependency/product_activate_requires_batch_bottling_or_closed
    """
    winery = create_winery(name="Bat Co", ttb_permit_number="BAT-1")
    batch = create_batch(winery["id"])
    product = get_success_data(api.create_product(
        {"winery_id": winery["id"], "source_batch_id": batch["id"], "sku": "S1",
         "vintage_year": 2024, "bottle_volume_ml": 750, "list_price_cents": 5000}, CM))
    get_success_data(api.transition_batch(batch["id"], {"action": "BEGIN_AGING"}, CM))
    res = api.transition_product(product["id"], {
        "action": "ACTIVATE", "expected_product_version": product["version"]}, CM)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ─── resource_temporal_overlap ─────────────────────────

def test_table_double_booked_half_open_overlap(api):
    """PRD §3.10: "A reservation is confirmed by transitioning `REQUESTED →
    CONFIRMED`, permitted only while the reservation is `REQUESTED` and only if no
    other reservation already in `CONFIRMED` or `SEATED` status occupies an
    overlapping interval on the same `table_code`. The interval is half-open over
    `[starts_at, ends_at)`... a genuine overlap is rejected with
    `ERR_TABLE_DOUBLE_BOOKED`."

    CONFIRM a second T1 reservation 18:30-20:00 overlapping a CONFIRMED 18:00-19:00
    -> ERR_TABLE_DOUBLE_BOOKED.

    Design: Difficulty/resource_temporal_overlap/table_double_booked_half_open_overlap
    """
    winery = create_winery(name="Res Co", ttb_permit_number="RES-1")
    create_confirmed_reservation(winery["id"], table_code="T1",
                                 starts_at="2026-06-20T18:00:00Z",
                                 ends_at="2026-06-20T19:00:00Z")
    res2 = get_success_data(api.create_reservation(
        create_reservation_payload(winery["id"], table_code="T1", party_size=4,
                                   starts_at="2026-06-20T18:30:00Z",
                                   ends_at="2026-06-20T20:00:00Z"), TRS))
    res = api.transition_reservation(res2["id"], {"action": "CONFIRM"}, TRS)
    validate_error(res, "ERR_TABLE_DOUBLE_BOOKED", expected_status=409)


def test_release_window_closed_rejects_schedule(api):
    """PRD §3.7: "Scheduling is allowed only against an `OPEN` release whose claim
    window currently contains the server clock — that is, the current instant is at
    or after `opens_at` (inclusive) and strictly before `closes_at` (exclusive); a
    claim outside that window is rejected with `ERR_RELEASE_WINDOW_CLOSED`."

    Scheduling when now (2026-06-15) is past closes_at (2026-06-10) ->
    ERR_RELEASE_WINDOW_CLOSED.

    Design: Difficulty/resource_temporal_overlap/release_window_closed_aggregate_window
    """
    set_clock("2026-06-15T00:00:00Z")
    winery, product, release = setup_open_release(
        pool_bottles=6, per_member_cap=6, bottled_bottles=20,
        opens_at="2026-06-01T00:00:00Z", closes_at="2026-06-10T00:00:00Z",
        product_overrides={"list_price_cents": 5000})
    member = setup_active_member(winery["id"], ship_to_state_code="CA")
    membership = setup_active_membership(winery["id"], member["id"], tier="SILVER")
    res = api.create_shipment(
        create_shipment_payload(winery["id"], membership["id"], release["id"], 6), CLM)
    validate_error(res, "ERR_RELEASE_WINDOW_CLOSED", expected_status=422)


# ─── Corner: state_machines (non-stub) ─────────────────

def test_confirm_already_completed_reservation_invalid_state(api):
    """PRD §3.10: "A confirmed reservation is seated by transitioning `CONFIRMED →
    SEATED`, and a seated reservation is completed by transitioning `SEATED →
    COMPLETED`... `COMPLETED`, `NO_SHOW`, and `CANCELLED` are terminal."
    PRD §3.10: "A reservation is confirmed by transitioning `REQUESTED → CONFIRMED`,
    permitted only while the reservation is `REQUESTED`".

    CONFIRM on a terminal COMPLETED reservation -> ERR_INVALID_STATE.

    Design: Corner/state_machines/confirm_already_completed_reservation_invalid_state
    """
    winery = create_winery(name="R Co", ttb_permit_number="R-1")
    res = create_confirmed_reservation(winery["id"], table_code="T1")
    get_success_data(api.transition_reservation(res["id"], {"action": "SEAT"}, TRS))
    get_success_data(api.transition_reservation(res["id"], {"action": "COMPLETE"}, TRS))
    bad = api.transition_reservation(res["id"], {"action": "CONFIRM"}, TRS)
    validate_error(bad, "ERR_INVALID_STATE", expected_status=409)
    final = get_success_data(api.get_reservation(res["id"], TRS))
    assert final["status"] == "COMPLETED", final["status"]


def test_no_show_frees_table_for_later_confirm(api):
    """PRD §3.10: "A confirmed reservation may be marked a no-show, transitioning
    `CONFIRMED → NO_SHOW`, which frees the table interval so that a later
    confirmation on the same table and window no longer conflicts — the revert of
    the capacity hold."

    After MARK_NO_SHOW on a CONFIRMED 18:00-19:00 T1 reservation, a later
    overlapping 18:30-19:30 reservation on T1 CONFIRMs successfully.

    Design: Corner/state_machines/no_show_frees_table_for_later_confirm
    """
    winery = create_winery(name="Ns Co", ttb_permit_number="NS-1")
    res1 = create_confirmed_reservation(winery["id"], table_code="T1",
                                        starts_at="2026-06-20T18:00:00Z",
                                        ends_at="2026-06-20T19:00:00Z")
    get_success_data(api.transition_reservation(res1["id"], {"action": "MARK_NO_SHOW"}, TRS))
    res2 = get_success_data(api.create_reservation(
        create_reservation_payload(winery["id"], table_code="T1", party_size=3,
                                   starts_at="2026-06-20T18:30:00Z",
                                   ends_at="2026-06-20T19:30:00Z"), TRS))
    confirmed = validate_success(api.transition_reservation(res2["id"], {"action": "CONFIRM"}, TRS), 200)
    assert confirmed["status"] == "CONFIRMED", confirmed["status"]
