"""State-machine valid transitions, invalid-from, terminal lockdown, idempotency.

Corner queue: state_machines section instances.
"""
from test_helpers import validate_success, validate_error
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import (
    publish_price,
    register_seller,
    stage_container,
    open_ticket,
    add_line,
    create_weighed_ticket,
    create_released_ticket,
    WM, PC, YM,
)
from test_helpers.test_users import make_weigh_master_headers


def test_weigh_out_from_draft_to_weighed_freezes_valuation(api):
    """PRD §3.3: "On success the ticket advances `DRAFT → WEIGHED`: the system sets
    `net_weight_lb` to the `gross_weight_lb` minus the `tare_weight_lb` (the
    billable weight, null until now), and freezes `gross_valuation_cents`."

    One 100 lb SHRED_STEEL line @ spot 11, gross 1500/tare 200 -> net 1300, value 1100.

    Design: Corner/state_machines/weigh_out_from_draft_to_weighed_freezes_valuation
    """
    publish_price("SHRED_STEEL", "FERROUS", spot=11, mill=14)
    seller = register_seller(legal_name="VT Co", id_type="STATE_ID", id_number="SID-VT")
    ticket = open_ticket(seller["id"], gross_weight_lb=1500)
    add_line(ticket["id"], "SHRED_STEEL", 100)
    data = validate_success(api.weigh_out(ticket["id"], {"tare_weight_lb": 200}, WM))
    assert data["status"] == "WEIGHED", f"expected WEIGHED, got {data['status']}"
    assert data["net_weight_lb"] == 1300, f"expected net 1300, got {data['net_weight_lb']}"
    assert data["gross_valuation_cents"] == 1100, \
        f"expected gross_valuation_cents 1100, got {data['gross_valuation_cents']}"


def test_release_from_draft_invalid_state(api):
    """PRD §2.8: "if the requested transition is not defined from the resource's
    present state, `ERR_INVALID_STATE` (HTTP 409) is returned."
    PRD §3.4: "If the `WeighMaster` decides the material is legitimate, the ticket is
    released, moving `WEIGHED → RELEASED`."

    Releasing a DRAFT (not WEIGHED) ticket is undefined.

    Design: Corner/state_machines/release_from_draft_invalid_state
    """
    seller = register_seller(legal_name="Inv State", id_type="STATE_ID", id_number="SID-IS")
    container = stage_container("FERROUS", capacity_lb=5000)
    ticket = open_ticket(seller["id"], gross_weight_lb=1500)
    resp = api.release_ticket(ticket["id"], {"container_id": container["id"]}, WM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_report_from_reported_terminal_lockdown(api):
    """PRD §3.4: "If instead the `WeighMaster` concludes the material is stolen, the
    ticket is reported, moving `WEIGHED → REPORTED` — a terminal state."
    PRD §2.8: "if the requested transition is not defined from the resource's
    present state, `ERR_INVALID_STATE` (HTTP 409) is returned."

    A REPORTED (terminal) ticket cannot be reported a second time.

    Design: Corner/state_machines/report_from_reported_terminal_lockdown
    """
    publish_price("CAT_CONV", "NON_FERROUS", spot=50000, mill=52000)
    seller = register_seller(legal_name="Term Co", id_type="PASSPORT", id_number="P-TERM")
    ticket = open_ticket(seller["id"], gross_weight_lb=50)
    add_line(ticket["id"], "CAT_CONV", 5)
    validate_success(api.weigh_out(ticket["id"], {"tare_weight_lb": 10}, WM))
    validate_success(api.report_ticket(ticket["id"], {"reason": "first report"}, WM))
    resp = api.report_ticket(ticket["id"], {"reason": "second report"}, WM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_clear_hold_records_releaser_id(api):
    """PRD §3.4: "Clearing the hold records the acting `WeighMaster`'s `X-User-ID`
    into the ticket's `theft_hold_released_by` field."

    Design: Corner/state_machines/clear_hold_records_releaser_id
    """
    built = create_weighed_ticket(grade_code="SHRED_STEEL", category="FERROUS",
                                  spot=11, mill=14, weight_lb=100)
    validate_success(api.theft_hold(built["ticket"]["id"], WM))
    clearer = make_weigh_master_headers("U_CLEAR_1")
    data = validate_success(api.clear_hold(built["ticket"]["id"], clearer))
    assert data["status"] == "WEIGHED", f"expected WEIGHED, got {data['status']}"
    assert data["theft_hold_released_by"] == "U_CLEAR_1", \
        f"expected theft_hold_released_by U_CLEAR_1, got {data['theft_hold_released_by']}"


def test_new_ticket_starts_in_draft(api):
    """PRD §3.3: "The ticket is created in `DRAFT` with `gross_valuation_cents` at 0."

    Design: Corner/state_machines/new_ticket_starts_in_draft
    """
    seller = register_seller(legal_name="Init Co", id_type="STATE_ID", id_number="SID-INI")
    data = validate_success(
        api.create_ticket({"seller_id": seller["id"], "gross_weight_lb": 100}, WM), 201
    )
    assert data["status"] == "DRAFT", f"expected DRAFT, got {data['status']}"


def test_settle_payout_twice_idempotency_rejected(api):
    """PRD §3.5: "Settling requires the payout to be `PENDING`".
    PRD §2.8: "if the requested transition is not defined from the resource's
    present state, `ERR_INVALID_STATE` (HTTP 409) is returned."

    Settling an already-SETTLED payout is undefined and must not move the ledger twice.

    Design: Corner/state_machines/settle_payout_twice_idempotency_rejected
    """
    publish_price("SHRED_STEEL", "FERROUS", spot=11, mill=14)
    seller = register_seller(legal_name="Idem Co", id_type="STATE_ID", id_number="SID-ID")
    built = create_released_ticket(
        grade_code="SHRED_STEEL", category="FERROUS", spot=11, mill=14,
        weight_lb=100, capacity_lb=5000, seller_id=seller["id"],
    )
    payout = validate_success(
        api.create_payout({"ticket_id": built["ticket"]["id"], "method": "CASH"}, PC), 201
    )
    validate_success(api.settle_payout(payout["id"], PC))
    resp = api.settle_payout(payout["id"], PC)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    seller_after = validate_success(api.get_seller(seller["id"], WM))
    assert seller_after["ytd_cash_paid_cents"] == 1100, \
        f"ledger must not move twice, expected 1100, got {seller_after['ytd_cash_paid_cents']}"


def test_add_line_item_after_weighout_invalid(api):
    """PRD §3.3: "While the ticket is `DRAFT`, and only while it is `DRAFT`, the
    `WeighMaster` records the sort by adding material line items."
    PRD §2.8: "if the requested transition is not defined from the resource's
    present state, `ERR_INVALID_STATE` (HTTP 409) is returned."

    Adding a line to a WEIGHED (no longer DRAFT) ticket is undefined.

    Design: Corner/state_machines/add_line_item_after_weighout_invalid
    """
    built = create_weighed_ticket(grade_code="SHRED_STEEL", category="FERROUS",
                                  spot=11, mill=14, weight_lb=100)
    resp = api.add_line_item(built["ticket"]["id"], {"grade_code": "SHRED_STEEL", "weight_lb": 50}, WM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
