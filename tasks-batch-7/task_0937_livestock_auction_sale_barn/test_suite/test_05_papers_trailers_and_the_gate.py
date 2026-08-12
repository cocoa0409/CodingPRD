"""Health papers, brand inspection, trailers, the haul charge and the gate."""

from test_helpers import (
    ApiErrorId,
    BARN_ADMIN,
    INSPECTOR,
    YARD_OPERATOR,
    add_lot_to_manifest,
    assert_money,
    assert_same_date,
    assign_pen,
    create_inspection_record_payload,
    create_lot,
    enter_ring,
    hammer_lot,
    load_and_dispatch,
    mark_lot_ready,
    open_manifest,
    read_inspection_record,
    read_load_line,
    read_load_manifest,
    read_lot,
    read_pen,
    read_buyer_invoice,
    record_inspection,
    set_clock,
    setup_checked_in_consignment,
    setup_sold_lot,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
    weigh_lot,
)

KANSAS_PACKER = {
    "legal_name": "Wichita Beef",
    "party_type": "PACKER",
    "origin_state_code": "KS",
    "origin_county": "Sedgwick",
    "tax_id": "48-5555555",
}


def _out_of_state_lot_ready_for_the_gate(cvi_issue_date="2026-05-03"):
    """A Kansas-bound sold lot, papered and dispatched, waiting at the gate."""
    scn = setup_sold_lot(buyer_party_overrides=dict(KANSAS_PACKER))
    scn.brand_record = record_inspection(
        scn.lot["id"],
        "BRAND",
        issue_date="2026-06-01",
        inspected_head=10,
        document_number="BR-9001",
    )
    scn.cvi_record = record_inspection(
        scn.lot["id"],
        "CVI",
        issue_date=cvi_issue_date,
        inspected_head=10,
        document_number="CVI-4432",
        destination_state_code="KS",
    )
    load_and_dispatch(scn, haul_basis="PER_MILE", loaded_miles=40, proration_basis="BY_WEIGHT")
    return scn


def test_release_is_permitted_on_the_exact_day_the_cvi_expires(api):
    """PRD §3.6: "The record opens in `PENDING`, and the server computes
    `valid_through` as the issue date plus the validity period of that document type:
    30 days for a `CVI`, 10 days for a `BRAND` record, 60 days for a `TRICH_TEST` and
    365 days for a `BRUCELLOSIS_TEST`."
    PRD §3.6: "A record satisfies a requirement only when three things hold together:
    its `status` is `CLEARED`, its `valid_through` is on or after the current clock
    date, and its `inspected_head` is at least the lot's `head_count`."
    PRD §2.5: "A certification or inspection document is still good on the exact day it
    expires."

    Design: Difficulty/boundary_precision_check/cvi_valid_through_equal_to_clock_date_still_permits_release
    """
    scn = _out_of_state_lot_ready_for_the_gate()
    assert_same_date(
        read_inspection_record(scn.cvi_record["id"])["valid_through"],
        "2026-06-02",
        "a CVI issued 2026-05-03 is good for 30 days:",
    )
    assert_same_date(
        read_inspection_record(scn.brand_record["id"])["valid_through"],
        "2026-06-11",
        "a brand record issued 2026-06-01 is good for 10 days:",
    )

    set_clock("2026-06-02T09:00:00Z")
    data = validate_success(api.release_lot(scn.lot["id"], YARD_OPERATOR))

    assert data["custody_status"] == "RELEASED"
    lot = read_lot(scn.lot["id"])
    assert lot["released_at"] is not None
    assert lot["sale_status"] == "SOLD"
    assert lot["destination_state_code"] == "KS"


def test_release_at_the_gate_frees_the_pen_and_the_haul_charge_stands(api):
    """PRD §3.9: "On success `released_at` is stamped from the logical clock — ending
    both the lot's pen-occupancy interval and its yardage day count — and the pen
    recomputes `current_head`, flipping `OCCUPIED → AVAILABLE` when it empties."
    PRD §3.9: "On a per-mile manifest the charge is 4.85 dollars per loaded mile,
    rounded half up to two decimal places, floored at a minimum of 250.00; head count is
    irrelevant, and the floor binds on any haul shorter than about fifty-two loaded
    miles."

    Design: Difficulty/boundary_precision_check/cvi_valid_through_equal_to_clock_date_still_permits_release
    """
    scn = _out_of_state_lot_ready_for_the_gate()
    set_clock("2026-06-02T09:00:00Z")
    validate_success(api.release_lot(scn.lot["id"], YARD_OPERATOR))

    pen = read_pen(scn.pen["id"])
    assert pen["current_head"] == 0
    assert pen["status"] == "AVAILABLE"

    manifest = read_load_manifest(scn.manifest["id"])
    assert_money(manifest["haul_charge"], 250.00, "40 loaded miles are floored at the minimum:")
    assert_money(
        read_load_line(scn.load_line["id"])["prorated_haul_amount"],
        250.00,
        "the only line carries the whole charge:",
    )


def test_second_retest_on_a_failed_record_is_refused(api):
    """PRD §3.6: "A `FAILED` record may be reopened for another attempt, `FAILED →
    PENDING`, which increments `retest_count` by one; because the cap is one, a second
    reopening is refused with `ERR_RETEST_LIMIT_EXCEEDED`."
    PRD §3.6: "The record opens in `PENDING`, and the server computes `valid_through`
    as the issue date plus the validity period of that document type: 30 days for a
    `CVI`, 10 days for a `BRAND` record, 60 days for a `TRICH_TEST` and 365 days for a
    `BRUCELLOSIS_TEST`."

    Design: Corner/state_machines/corner_inspection_retest_beyond_cap_is_rejected
    """
    scn = setup_checked_in_consignment(head_received=10, with_pen=False, with_scale=False)
    lot = create_lot(
        scn.consignment["id"],
        head_count=10,
        livestock_class="BREEDING_BULL",
        bid_basis="PER_HEAD",
        opening_bid=2000.00,
        reserve_price=2200.00,
    )
    record = validate_success(
        api.create_inspection_record(
            create_inspection_record_payload(
                lot["id"], "TRICH_TEST", issue_date="2026-06-01", document_number="TR-1"
            ),
            INSPECTOR,
        ),
        201,
    )
    for result in ("FAILED", "RETEST", "FAILED"):
        validate_success(
            api.result_inspection_record(record["id"], {"result": result}, INSPECTOR)
        )

    response = api.result_inspection_record(record["id"], {"result": "RETEST"}, INSPECTOR)
    validate_error(response, ApiErrorId.ERR_RETEST_LIMIT_EXCEEDED.value)

    fresh = read_inspection_record(record["id"])
    assert fresh["retest_count"] == 1
    assert fresh["status"] == "FAILED"
    assert_same_date(
        fresh["valid_through"], "2026-07-31", "a trichomoniasis test is good for 60 days:"
    )


def test_removing_the_last_line_returns_the_manifest_to_planned(api):
    """PRD §3.9: "Pulling a lot back off the trailer deletes the line and answers with
    no body."
    PRD §3.9: "the lot's custody reverts `LOADED → BUYER_PEN`; the pen it returns to
    recomputes `current_head`; and when the removed line was the last one on the
    manifest, the manifest reverts `LOADING → PLANNED` with `loaded_head`,
    `loaded_weight_lb` and `haul_charge` all back to zero."

    Design: Corner/state_machines/corner_load_manifest_reverts_to_planned_when_last_line_removed
    """
    scn = setup_sold_lot()
    open_manifest(scn, haul_basis="PER_MILE", loaded_miles=40)
    scn.load_line = add_lot_to_manifest(scn, scn.lot["id"])

    loading = read_load_manifest(scn.manifest["id"])
    assert loading["status"] == "LOADING", "the first line takes the manifest PLANNED -> LOADING"
    assert_money(loading["haul_charge"], 250.00, "a forty-mile haul is floored:")

    response = api.remove_load_line(
        scn.manifest["id"], scn.load_line["id"], scn.carrier_headers
    )
    assert response.status_code == 204, f"expected 204, got {response.status_code}"

    manifest = read_load_manifest(scn.manifest["id"])
    assert manifest["status"] == "PLANNED"
    assert manifest["loaded_head"] == 0
    assert manifest["loaded_weight_lb"] == 0
    assert_money(manifest["haul_charge"], 0.00, "an empty trailer books nothing:")

    lot = read_lot(scn.lot["id"])
    assert lot["custody_status"] == "BUYER_PEN"
    assert lot["sale_status"] == "SOLD"

    _, meta = validate_paginated(
        api.list_load_lines(BARN_ADMIN, params={"load_manifest_id": scn.manifest["id"]})
    )
    assert meta["total_count"] == 0
    assert read_pen(scn.pen["id"])["current_head"] == 10


def test_per_head_flat_haul_ignores_the_miles_and_prorates_by_head(api):
    """PRD §3.9: "On a per-head-flat manifest the charge is 12.00 dollars for every
    loaded head, rounded half up to two decimal places, with no floor at all and
    distance irrelevant — so the identical trip books a different charge under the two
    bases."
    PRD §3.9: "on a head basis it is the haul charge multiplied by that line's `head`
    and divided by the manifest's `loaded_head`."
    PRD §3.9: "The first line added takes the manifest `PLANNED → LOADING`, and every
    line add recomputes `loaded_head`, `loaded_weight_lb`, `haul_charge` and every
    line's `prorated_haul_amount`."

    Design: Corner/calculations/corner_haul_per_head_flat_and_proration_by_head
    """
    scn = setup_sold_lot(
        head_received=18,
        head_count=10,
        consignment_overrides={"pencil_shrink_pct": 0},
        gross_weight_lb=6990,
        tare_weight_lb=200,
    )
    lot_b = create_lot(scn.consignment["id"], head_count=8, livestock_class="FEEDER_HEIFER")
    assign_pen(lot_b["id"], scn.pen["id"])
    weigh_lot(lot_b["id"], scn.scale["id"], head_on_draft=8, gross_weight_lb=5200, tare_weight_lb=200)
    mark_lot_ready(lot_b["id"])
    enter_ring(lot_b["id"])
    scn.lot_a = scn.lot
    scn.lot = lot_b
    hammer_lot(scn, unit_price=182.50)

    assert read_lot(scn.lot_a["id"])["settle_weight_lb"] == 6790
    assert read_lot(lot_b["id"])["settle_weight_lb"] == 5000

    open_manifest(scn, haul_basis="PER_HEAD_FLAT", loaded_miles=40, proration_basis="BY_HEAD")
    line_a = add_lot_to_manifest(scn, scn.lot_a["id"])
    line_b = add_lot_to_manifest(scn, lot_b["id"])

    manifest = read_load_manifest(scn.manifest["id"])
    assert manifest["loaded_head"] == 18
    assert manifest["loaded_weight_lb"] == 11790
    assert manifest["status"] == "LOADING"
    assert_money(manifest["haul_charge"], 216.00, "12.00 for every one of 18 loaded head:")

    share_a = read_load_line(line_a["id"])["prorated_haul_amount"]
    share_b = read_load_line(line_b["id"])["prorated_haul_amount"]
    assert_money(share_a, 120.00, "216.00 x 10 / 18:")
    assert_money(share_b, 96.00, "216.00 x 8 / 18:")
    assert_money(share_a + share_b, 216.00, "the shares sum back to the charge:")


def test_release_without_a_brand_record_is_refused_until_one_clears(api):
    """PRD §3.6: "Releasing a lot at the gate requires a cleared, unexpired brand
    record covering the lot's head, plus a cleared certificate of veterinary inspection
    whenever the lot's `destination_state_code` differs from the sale day's
    `barn_state_code` — an in-state buyer needs no CVI, an out-of-state buyer does."
    PRD §3.6: "In both gates the ordering is the same: a missing document, a document
    that is not cleared, or one that covers too few head answers
    `ERR_INSPECTION_NOT_CLEARED`, while a document that is cleared and adequate but
    whose `valid_through` has fallen behind the clock date answers `ERR_CVI_EXPIRED`."

    Design: Corner/validations/corner_release_without_brand_inspection_is_rejected
    """
    scn = setup_sold_lot()
    load_and_dispatch(scn, haul_basis="PER_MILE", loaded_miles=40)

    response = api.release_lot(scn.lot["id"], YARD_OPERATOR)
    validate_error(response, ApiErrorId.ERR_INSPECTION_NOT_CLEARED.value)
    assert read_lot(scn.lot["id"])["custody_status"] == "LOADED"

    brand = record_inspection(
        scn.lot["id"], "BRAND", issue_date="2026-06-01", inspected_head=10,
        document_number="BR-9001",
    )
    assert brand["status"] == "CLEARED"
    assert_same_date(
        brand["valid_through"], "2026-06-11", "a brand record is good for 10 days:"
    )

    data = validate_success(api.release_lot(scn.lot["id"], YARD_OPERATOR))
    assert data["custody_status"] == "RELEASED"
    assert read_pen(scn.pen["id"])["current_head"] == 0


def test_release_with_a_cleared_but_stale_cvi_answers_cvi_expired(api):
    """PRD §3.6: "In both gates the ordering is the same: a missing document, a
    document that is not cleared, or one that covers too few head answers
    `ERR_INSPECTION_NOT_CLEARED`, while a document that is cleared and adequate but
    whose `valid_through` has fallen behind the clock date answers `ERR_CVI_EXPIRED`."
    PRD §3.6: "`valid_through` is the **last valid date, inclusive**."

    Design: Corner/validations/corner_release_with_expired_cvi_is_rejected
    """
    scn = _out_of_state_lot_ready_for_the_gate(cvi_issue_date="2026-04-01")

    response = api.release_lot(scn.lot["id"], YARD_OPERATOR)
    validate_error(response, ApiErrorId.ERR_CVI_EXPIRED.value)

    cvi = read_inspection_record(scn.cvi_record["id"])
    assert_same_date(
        cvi["valid_through"], "2026-05-01", "a CVI issued 2026-04-01 lapsed on 2026-05-01:"
    )
    assert cvi["status"] == "CLEARED"

    lot = read_lot(scn.lot["id"])
    assert lot["destination_state_code"] == "KS"
    assert lot["custody_status"] == "LOADED"


def test_load_line_busting_the_head_capacity_is_refused(api):
    """PRD §3.9: "Two capacity checks apply and they are genuinely independent: the
    manifest's `loaded_head` plus the lot's head must be at most
    `trailer_head_capacity`, or the answer is `ERR_TRAILER_HEAD_CAPACITY_EXCEEDED`"
    PRD §3.9: "A new manifest is `PLANNED` with `loaded_head`, `loaded_weight_lb` and
    `haul_charge` all zero."

    Design: Corner/validations/corner_load_line_exceeding_trailer_head_capacity_is_rejected
    """
    scn = setup_sold_lot()
    open_manifest(scn, trailer_head_capacity=5, trailer_weight_capacity_lb=60000)

    manifest = read_load_manifest(scn.manifest["id"])
    response = api.add_load_line(
        manifest["id"],
        {"lot_id": scn.lot["id"], "expected_load_manifest_version": manifest["version"]},
        scn.carrier_headers,
    )
    validate_error(response, ApiErrorId.ERR_TRAILER_HEAD_CAPACITY_EXCEEDED.value)

    fresh = read_load_manifest(manifest["id"])
    assert fresh["status"] == "PLANNED"
    assert fresh["loaded_head"] == 0
    assert fresh["loaded_weight_lb"] == 0
    assert_money(fresh["haul_charge"], 0.00, "nothing was loaded:")
    assert read_lot(scn.lot["id"])["custody_status"] == "BUYER_PEN"

    _, meta = validate_paginated(
        api.list_load_lines(BARN_ADMIN, params={"load_manifest_id": manifest["id"]})
    )
    assert meta["total_count"] == 0


def test_load_line_inside_head_capacity_but_over_the_payload_is_refused(api):
    """PRD §3.9: "and the manifest's `loaded_weight_lb` plus the lot's settle weight
    must be at most `trailer_weight_capacity_lb`, or the answer is
    `ERR_TRAILER_WEIGHT_CAPACITY_EXCEEDED`. Both comparisons are inclusive, and the head
    check is evaluated first."
    PRD §3.9: "The two limits are independent, and a lot can fit comfortably by head
    while busting the trailer by weight."

    Design: Corner/validations/corner_load_line_within_head_capacity_but_over_weight_capacity_is_rejected
    """
    scn = setup_sold_lot()
    open_manifest(scn, trailer_head_capacity=60, trailer_weight_capacity_lb=5000)

    manifest = read_load_manifest(scn.manifest["id"])
    response = api.add_load_line(
        manifest["id"],
        {"lot_id": scn.lot["id"], "expected_load_manifest_version": manifest["version"]},
        scn.carrier_headers,
    )
    validate_error(response, ApiErrorId.ERR_TRAILER_WEIGHT_CAPACITY_EXCEEDED.value)

    fresh = read_load_manifest(manifest["id"])
    assert fresh["status"] == "PLANNED"
    assert fresh["loaded_weight_lb"] == 0
    assert read_lot(scn.lot["id"])["custody_status"] == "BUYER_PEN"


def test_release_of_a_lot_that_is_on_no_dispatched_manifest_is_refused(api):
    """PRD §3.9: "It must appear on a line of a manifest that is `DISPATCHED` or
    `DELIVERED`, or the answer is `ERR_LOAD_NOT_ASSIGNED`."
    PRD §3.9: "Release at the gate is the terminal custody transition, `LOADED →
    RELEASED`, performed by a `YardOperator`, and it is the most heavily guarded
    operation in the system."

    Design: Corner/validations/corner_release_without_any_load_assignment_is_rejected
    """
    scn = setup_sold_lot()
    record_inspection(
        scn.lot["id"], "BRAND", issue_date="2026-06-01", inspected_head=10,
        document_number="BR-9001",
    )

    response = api.release_lot(scn.lot["id"], YARD_OPERATOR)
    # The lot sits at BUYER_PEN, so the release is refused either as the missing load
    # assignment of rung 41 or as the state check of rung 16; the PRD does not collapse
    # those two statements into one.
    validate_error_is_one_of(
        response,
        [ApiErrorId.ERR_LOAD_NOT_ASSIGNED.value, ApiErrorId.ERR_INVALID_STATE.value],
    )

    lot = read_lot(scn.lot["id"])
    assert lot["custody_status"] == "BUYER_PEN"
    assert lot["released_at"] is None
    assert read_pen(scn.pen["id"])["current_head"] == 10


def test_unsecured_buyer_with_an_unpaid_invoice_cannot_take_the_lot_home(api):
    """PRD §3.9: "And the money must be settled in one of two ways: either the buying
    registration's `bond_type` is `BONDED`, or the lot's buyer invoice is `PAID`.
    Failing that last condition answers `ERR_FUNDS_NOT_CLEARED`."

    Design: Corner/validations/corner_release_for_unsecured_buyer_with_unpaid_invoice_is_rejected
    """
    scn = setup_sold_lot(bond_type="UNSECURED", credit_limit=50000)
    record_inspection(
        scn.lot["id"], "BRAND", issue_date="2026-06-01", inspected_head=10,
        document_number="BR-9001",
    )
    load_and_dispatch(scn, haul_basis="PER_MILE", loaded_miles=40)

    response = api.release_lot(scn.lot["id"], YARD_OPERATOR)
    validate_error(response, ApiErrorId.ERR_FUNDS_NOT_CLEARED.value)

    assert scn.registration["bond_type"] == "UNSECURED"
    assert read_buyer_invoice(scn.invoice["id"])["status"] == "DRAFT"
    assert read_lot(scn.lot["id"])["custody_status"] == "LOADED"


def test_second_load_line_carrying_the_stale_manifest_version_is_refused(api):
    """PRD §2.8: "Adding a lot to a trailer — `POST
    /sale-barn/load-manifests/{id}/lines` — requires `expected_load_manifest_version`,
    carrying the client's last observed `version` of the `LoadManifest`."
    PRD §2.8: "Each added line changes `loaded_head` and `loaded_weight_lb`, so a
    writer holding a stale view is reasoning about trailer headroom that no longer
    exists."

    Design: Corner/cross_cutting_complexity_layers/corner_occ_load_line_add_with_stale_manifest_version_returns_412
    """
    scn = setup_sold_lot(head_received=15, head_count=10)
    lot_two = create_lot(scn.consignment["id"], head_count=5, livestock_class="FEEDER_HEIFER")
    assign_pen(lot_two["id"], scn.pen["id"])
    weigh_lot(lot_two["id"], scn.scale["id"], head_on_draft=5, gross_weight_lb=3300, tare_weight_lb=200)
    mark_lot_ready(lot_two["id"])
    enter_ring(lot_two["id"])
    scn.lot_one = scn.lot
    scn.lot = lot_two
    hammer_lot(scn, unit_price=182.50)

    open_manifest(scn, trailer_head_capacity=60, trailer_weight_capacity_lb=60000)
    stale_version = read_load_manifest(scn.manifest["id"])["version"]
    add_lot_to_manifest(scn, scn.lot_one["id"])

    response = api.add_load_line(
        scn.manifest["id"],
        {"lot_id": lot_two["id"], "expected_load_manifest_version": stale_version},
        scn.carrier_headers,
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION.value)

    manifest = read_load_manifest(scn.manifest["id"])
    assert manifest["loaded_head"] == 10
    assert manifest["loaded_weight_lb"] == 6790
    assert manifest["status"] == "LOADING"
    assert read_lot(lot_two["id"])["custody_status"] == "BUYER_PEN"

    _, meta = validate_paginated(
        api.list_load_lines(BARN_ADMIN, params={"load_manifest_id": scn.manifest["id"]})
    )
    assert meta["total_count"] == 1
