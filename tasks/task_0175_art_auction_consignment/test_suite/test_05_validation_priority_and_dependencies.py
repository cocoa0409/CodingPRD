"""Validation-ordering conflicts (the PRD's fixed priority order) and the
cross-entity dependency guards (sale CLOSED for invoice, invoice PAID for
statement).
"""
from test_helpers import validate_error, get_success_data, NON_EXISTENT_UUID
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import (
    setup_sold_lot, setup_open_lot, setup_paid_invoice_lot, setup_base_scene,
    place_bid, ADMIN, AUCTIONEER, FINANCE,
)
from test_helpers.factories import STANDARD_TIERS, FLAT_TIERS


# ===========================================================================
# Queue A — priority_pair_validation_conflict
# ===========================================================================
def test_paid_invoice_zero_payment_returns_invalid_state(api):
    """PRD §2.9: "the system checks the single-entity state precondition for the
    requested transition (`ERR_INVALID_STATE`) ... and finally fiscal limits on
    credit and payment (`ERR_CREDIT_LIMIT_EXCEEDED`)."
    PRD §3.6: "A payment may be recorded only while the invoice is `ISSUED`."

    A zero-amount payment on an already-PAID invoice violates both the state
    precondition (not ISSUED) and the fiscal rule (amount<=0); the
    higher-priority ERR_INVALID_STATE is returned.

    Design: Difficulty/priority_pair_validation_conflict/priority_state_beats_fiscal_on_payment
    """
    scene, paid = setup_paid_invoice_lot(
        hammer_cents=1250000, tiers=STANDARD_TIERS, artist_alive=False)
    paid_now = get_success_data(api.get_invoice(paid["id"], FINANCE))
    assert paid_now["status"] == "PAID"
    resp = api.create_payment(
        paid["id"], {"amount_cents": 0, "expected_invoice_version": paid_now["version"]}, FINANCE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_paid_invoice_overpayment_returns_invalid_state(api):
    """PRD §2.9: "the system checks the single-entity state precondition for the
    requested transition (`ERR_INVALID_STATE`) ... and finally fiscal limits on
    credit and payment (`ERR_CREDIT_LIMIT_EXCEEDED`)."
    PRD §3.6: "A payment may be recorded only while the invoice is `ISSUED`."

    A further payment that would exceed remaining due on an already-PAID
    invoice also trips both the state precondition and the fiscal rule; state
    (priority 7) still wins over fiscal (priority 14).

    Design: Difficulty/priority_pair_validation_conflict/priority_state_beats_fiscal_on_payment
    """
    scene, paid = setup_paid_invoice_lot(
        hammer_cents=1250000, tiers=STANDARD_TIERS, artist_alive=False)
    paid_now = get_success_data(api.get_invoice(paid["id"], FINANCE))
    resp = api.create_payment(
        paid["id"], {"amount_cents": 999999999, "expected_invoice_version": paid_now["version"]},
        FINANCE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_invoice_nonexistent_lot_returns_not_found(api):
    """PRD §2.7: "the system validates them strictly left to right and rejects
    the request with `ERR_NOT_FOUND` at the first identifier that does not
    resolve to an existing resource."
    PRD §2.9: "Existence checks follow: path-referenced resources first,
    validated left to right (`ERR_NOT_FOUND`) ... After that the system checks
    the single-entity state precondition for the requested transition
    (`ERR_INVALID_STATE`)"

    Invoicing a non-existent lot id returns ERR_NOT_FOUND (existence beats the
    state/OCC checks); the supplied version is irrelevant.

    Design: Difficulty/priority_pair_validation_conflict/priority_existence_beats_state_on_invoice
    """
    # Build a real lot to obtain a genuine server-issued version value.
    scene = setup_base_scene(tiers=FLAT_TIERS)
    real_lot = get_success_data(api.get_lot(scene["lot"]["id"], FINANCE))
    resp = api.invoice_lot(
        NON_EXISTENT_UUID, {"expected_lot_version": real_lot["version"]}, FINANCE)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_invoice_nonexistent_lot_ignores_version(api):
    """PRD §2.7: "existence checks on path identifiers precede the body and
    business-rule checks described below."
    PRD §2.9: "Existence checks follow: path-referenced resources first,
    validated left to right (`ERR_NOT_FOUND`) ... then the optimistic-concurrency
    version match (`ERR_STALE_VERSION`)."

    A patently wrong version on a non-existent lot still yields ERR_NOT_FOUND,
    not ERR_STALE_VERSION — existence pre-empts the OCC check.

    Design: Difficulty/priority_pair_validation_conflict/priority_existence_beats_state_on_invoice
    """
    resp = api.invoice_lot(NON_EXISTENT_UUID, {"expected_lot_version": 999}, FINANCE)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ===========================================================================
# Queue A — cross_entity_state_dependency
# ===========================================================================
def test_invoice_requires_sale_closed(api):
    """PRD §3.6: "Issuing the invoice for a sold lot is a `FinanceOfficer`
    action permitted only when the lot's `sale_status` is `SOLD`, its
    `settlement_status` is `NONE`, and the lot's sale is `CLOSED`; ... the
    requirement that the sale be `CLOSED` is a cross-entity dependency reported
    as `ERR_DEPENDENCY_NOT_READY`."

    A SOLD lot whose sale is still LIVE (not yet closed) cannot be invoiced.

    Design: Difficulty/cross_entity_state_dependency/cross_entity_invoice_requires_sale_closed
    """
    # SOLD lot but sale NOT closed: knock down without closing.
    scene = setup_open_lot(tiers=STANDARD_TIERS, reserve_cents=1000000)
    lot_id = scene["lot"]["id"]
    place_bid(lot_id, scene["paddle"]["id"], 1250000)
    lot = get_success_data(api.get_lot(lot_id, AUCTIONEER))
    sold = get_success_data(api.knock_down_lot(
        lot_id, {"expected_lot_version": lot["version"]}, AUCTIONEER))
    assert sold["sale_status"] == "SOLD"
    resp = api.invoice_lot(lot_id, {"expected_lot_version": sold["version"]}, FINANCE)
    validate_error(resp, ApiErrorId.ERR_DEPENDENCY_NOT_READY.value)


def test_invoice_after_close_succeeds(api):
    """PRD §3.6: "Issuing the invoice for a sold lot is a `FinanceOfficer`
    action permitted only when the lot's `sale_status` is `SOLD`, its
    `settlement_status` is `NONE`, and the lot's sale is `CLOSED`"

    The positive counterpart of the same dependency: once the sale is CLOSED
    the very same SOLD lot invoices successfully.

    Design: Difficulty/cross_entity_state_dependency/cross_entity_invoice_requires_sale_closed
    """
    scene = setup_sold_lot(hammer_cents=1250000, tiers=STANDARD_TIERS, artist_alive=False)
    lot_id = scene["lot"]["id"]
    lot = get_success_data(api.get_lot(lot_id, FINANCE))
    invoice = get_success_data(api.invoice_lot(
        lot_id, {"expected_lot_version": lot["version"]}, FINANCE))
    assert invoice["status"] == "ISSUED"
    after = get_success_data(api.get_lot(lot_id, FINANCE))
    assert after["settlement_status"] == "INVOICED"


def test_statement_requires_invoice_paid(api):
    """PRD §3.8: "Generating the seller statement for a lot is a
    `FinanceOfficer` action permitted only when the lot's `settlement_status`
    is `INVOICED` (otherwise `ERR_INVALID_STATE`) and the lot's `Invoice` is
    `PAID` — the buyer has settled in full — a cross-entity guard whose failure
    is reported as `ERR_DEPENDENCY_NOT_READY`."

    With the invoice still ISSUED (unpaid) the statement attempt fails the
    cross-entity guard.

    Design: Difficulty/cross_entity_state_dependency/cross_entity_statement_requires_invoice_paid
    """
    scene = setup_sold_lot(hammer_cents=1250000, tiers=STANDARD_TIERS, artist_alive=False)
    lot_id = scene["lot"]["id"]
    lot = get_success_data(api.get_lot(lot_id, FINANCE))
    get_success_data(api.invoice_lot(lot_id, {"expected_lot_version": lot["version"]}, FINANCE))
    lot2 = get_success_data(api.get_lot(lot_id, FINANCE))
    resp = api.statement_lot(lot_id, {"expected_lot_version": lot2["version"]}, FINANCE)
    validate_error(resp, ApiErrorId.ERR_DEPENDENCY_NOT_READY.value)


def test_statement_after_payment_succeeds(api):
    """PRD §3.8: "Generating the seller statement for a lot ... [is] permitted
    only when the lot's `settlement_status` is `INVOICED` ... and the lot's
    `Invoice` is `PAID` — the buyer has settled in full"
    PRD §3.8: "It then advances the lot's `settlement_status` from `INVOICED` to
    `STATEMENTED` and increments the lot's `version` by 1."

    The positive counterpart: once the invoice is PAID the statement generates
    and the lot advances to STATEMENTED.

    Design: Difficulty/cross_entity_state_dependency/cross_entity_statement_requires_invoice_paid
    """
    scene, paid = setup_paid_invoice_lot(
        hammer_cents=1250000, tiers=STANDARD_TIERS, artist_alive=False)
    lot_id = scene["lot"]["id"]
    lot = get_success_data(api.get_lot(lot_id, FINANCE))
    statement = get_success_data(api.statement_lot(
        lot_id, {"expected_lot_version": lot["version"]}, FINANCE))
    assert statement["status"] == "PENDING"
    after = get_success_data(api.get_lot(lot_id, FINANCE))
    assert after["settlement_status"] == "STATEMENTED"
