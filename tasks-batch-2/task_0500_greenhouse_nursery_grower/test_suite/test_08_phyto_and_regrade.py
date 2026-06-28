"""Cross-entity state dependencies: a batch regrade gated by order-line state, and
shipment dispatch gated by phytosanitary-certificate state / validity window.

Queue A (difficulty) — cross_entity_state_dependency, resource_temporal_overlap.
Queue B (corner) — errors (phyto destination mismatch).
"""
from test_helpers import (
    validate_success, validate_error,
    TEST_USERS,
    set_clock, create_broker, issue_phyto, create_draft_order, add_line, confirm_order,
    create_shipment, record_grade,
    setup_published_lot, setup_multi_line_order,
)

SC = TEST_USERS["sales_coordinator_headers"]
PT = TEST_USERS["production_tech_headers"]


# ─── A13: SALEABLE regrade gated by a COMMITTED order line ───────────────
def test_saleable_regrade_blocked_by_committed_line(api):
    """PRD 3.6: "only when no order line drawing on this batch's availability entry
    is in the `COMMITTED` state — an outstanding commitment blocks the regrade with
    `ERR_BATCH_HAS_COMMITMENTS`".

    Design: Difficulty/cross_entity_state_dependency/saleable_regrade_blocked_by_committed_orderline
    """
    s = setup_multi_line_order(
        line_specs=[{"quantity": 300, "started": 300, "unit_price_cents": 400}],
        ship_to_state="OR", confirm=True, cultivar_code="DAHN1")
    bid = s["batches"][0]["id"]
    set_clock(api, "2026-02-09T00:00:00Z")
    record_grade(api, bid, 11)  # fresh measurement, so only the commitment can block
    validate_error(api.start_grading(bid, PT), "ERR_BATCH_HAS_COMMITMENTS", expected_status=409)


def test_saleable_regrade_succeeds_after_order_cancelled(api):
    """PRD 3.12: "On cancellation of a confirmed order, each `COMMITTED` line moves
    to `RELEASED`".

    Design: Difficulty/cross_entity_state_dependency/saleable_regrade_blocked_by_committed_orderline
    """
    s = setup_multi_line_order(
        line_specs=[{"quantity": 300, "started": 300, "unit_price_cents": 400}],
        ship_to_state="OR", confirm=True, cultivar_code="DAHN2")
    bid = s["batches"][0]["id"]
    set_clock(api, "2026-02-09T00:00:00Z")
    record_grade(api, bid, 11)
    validate_success(api.cancel_order(s["order"]["id"], SC))
    data = validate_success(api.start_grading(bid, PT))
    assert data["status"] == "GRADING", "regrade must proceed once the line is RELEASED"


# ─── A14: dispatch gated by phyto-certificate VALID/CONSUMED state ───────
def _consumed_cert_scenario(api):
    """Two requires_phyto SALEABLE lots, one broker, one cert consumed by a first
    dispatch, and a second confirmed order+shipment carrying the now-consumed cert."""
    lot1 = setup_published_lot(api, requires_phyto=True, sourced=20, started=20,
                               unit_price_cents=300, cultivar_code="HOLP1")
    lot2 = setup_published_lot(api, requires_phyto=True, sourced=20, started=20,
                               unit_price_cents=300, cultivar_code="HOLP2")
    broker = create_broker(api, ship_to_state="NY")
    cert = issue_phyto(api, broker["id"], certificate_number="PC-1001",
                       valid_until="2026-12-31T00:00:00Z")
    order1 = create_draft_order(api, broker["id"])
    line1 = add_line(api, order1["id"], lot1["entry"]["id"], 20)
    confirm_order(api, order1["id"])
    ship1 = create_shipment(api, order1["id"], [{"order_line_id": line1["id"], "quantity": 20}],
                            phyto_certificate_id=cert["id"])
    validate_success(api.dispatch_shipment(ship1["id"], SC))  # consumes the cert
    order2 = create_draft_order(api, broker["id"])
    line2 = add_line(api, order2["id"], lot2["entry"]["id"], 20)
    confirm_order(api, order2["id"])
    ship2 = create_shipment(api, order2["id"], [{"order_line_id": line2["id"], "quantity": 20}],
                            phyto_certificate_id=cert["id"])
    return {"cert": cert, "ship2": ship2, "batch2": lot2["batch"]}


def test_dispatch_consumes_phyto_certificate(api):
    """PRD 3.14: "If a certificate was attached, it is consumed: a `VALID`
    certificate moves to `CONSUMED`."

    Design: Difficulty/cross_entity_state_dependency/dispatch_blocked_by_consumed_phyto_then_ok_with_valid
    """
    scn = _consumed_cert_scenario(api)
    cert = validate_success(api.get_phyto_certificate(scn["cert"]["id"], SC))
    assert cert["status"] == "CONSUMED", "first dispatch must consume the cert"


def test_dispatch_with_consumed_cert_rejected(api):
    """PRD 3.14: "a non-`VALID` (already-consumed) certificate with
    `ERR_PHYTO_INVALID`".

    Design: Difficulty/cross_entity_state_dependency/dispatch_blocked_by_consumed_phyto_then_ok_with_valid
    """
    scn = _consumed_cert_scenario(api)
    validate_error(api.dispatch_shipment(scn["ship2"]["id"], SC),
                   "ERR_PHYTO_INVALID", expected_status=409)
    ship = validate_success(api.get_shipment(scn["ship2"]["id"], SC))
    assert ship["status"] == "DRAFT", "rejected dispatch must leave the shipment DRAFT"


# ─── A16: phyto half-open validity window at the dispatch instant ────────
def _expired_window_scenario(api):
    lot = setup_published_lot(api, requires_phyto=True, sourced=20, started=20,
                              unit_price_cents=300, cultivar_code="BOXR1")
    broker = create_broker(api, ship_to_state="NY")
    cert = issue_phyto(api, broker["id"], certificate_number="PC-2002",
                       valid_until="2026-02-10T00:00:00Z")
    order = create_draft_order(api, broker["id"])
    line = add_line(api, order["id"], lot["entry"]["id"], 20)
    confirm_order(api, order["id"])
    ship = create_shipment(api, order["id"], [{"order_line_id": line["id"], "quantity": 20}],
                           phyto_certificate_id=cert["id"])
    set_clock(api, "2026-02-11T00:00:00Z")  # strictly past valid_until
    return {"cert": cert, "ship": ship}


def test_dispatch_past_cert_valid_until_rejected(api):
    """PRD 3.14: "an expired or past-`valid_until` certificate with
    `ERR_PHYTO_EXPIRED`".

    Design: Difficulty/resource_temporal_overlap/phyto_validity_window_expired_at_dispatch_instant
    """
    scn = _expired_window_scenario(api)
    validate_error(api.dispatch_shipment(scn["ship"]["id"], SC),
                   "ERR_PHYTO_EXPIRED", expected_status=409)


def test_dispatch_past_valid_until_leaves_shipment_and_cert_untouched(api):
    """PRD 3.14: "whose `valid_until` is at or after the current logical-clock
    instant".

    Design: Difficulty/resource_temporal_overlap/phyto_validity_window_expired_at_dispatch_instant
    """
    scn = _expired_window_scenario(api)
    api.dispatch_shipment(scn["ship"]["id"], SC)  # rejected
    ship = validate_success(api.get_shipment(scn["ship"]["id"], SC))
    assert ship["status"] == "DRAFT"
    cert = validate_success(api.get_phyto_certificate(scn["cert"]["id"], SC))
    assert cert["status"] != "CONSUMED", "a rejected dispatch must not consume the cert"


# ─── B35: cert destination_state must equal the broker's ship_to_state ───
def test_dispatch_phyto_destination_mismatch_rejected(api):
    """PRD 3.14: "whose `destination_state` equals the broker's `ship_to_state`".

    Design: Corner/errors/phyto_destination_mismatch_excluded
    """
    lot = setup_published_lot(api, requires_phyto=True, sourced=20, started=20,
                              unit_price_cents=300, cultivar_code="DMR1")
    broker_a = create_broker(api, ship_to_state="NY", company_name="A NY")
    broker_b = create_broker(api, ship_to_state="CA", company_name="B CA")
    cert = issue_phyto(api, broker_a["id"], certificate_number="PC-DM",
                       valid_until="2026-12-31T00:00:00Z")  # destination_state copied as NY
    order = create_draft_order(api, broker_b["id"])
    line = add_line(api, order["id"], lot["entry"]["id"], 20)
    confirm_order(api, order["id"])
    ship = create_shipment(api, order["id"], [{"order_line_id": line["id"], "quantity": 20}],
                           phyto_certificate_id=cert["id"])
    validate_error(api.dispatch_shipment(ship["id"], SC),
                   "ERR_PHYTO_DESTINATION_MISMATCH", expected_status=409)
