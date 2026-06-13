"""Folio: embark cascade, provisional gratuity, settlement gate, charge reversal."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_folio_charge_payload,
    create_embarked_booking, get_folio_for_booking,
    set_clock,
)

PA = TEST_USERS["port_agent_headers"]


def test_embark_cascade_creates_folio_with_provisional_gratuity(api):
    """PRD 3.7: "Embarkation creates the booking's `Folio` in `OPEN` status with
    `gratuity_mode` of `PROVISIONAL`, and posts the provisional auto-gratuity onto
    it." PRD 3.7: "`gratuity_total_cents` is the gratuity rate of 1800 cents
    multiplied by the booking's `guest_count` and by the sailing's `nights`."

    Design: Corner/state_machines/embark_cascade_creates_folio_with_provisional_gratuity
    """
    set_clock("2026-06-18T16:00:00Z")
    sailing, category, embarked = create_embarked_booking(
        "guest-c6", num_guests=3, num_cabins=1,
    )
    assert embarked["status"] == "EMBARKED"
    folio = get_folio_for_booking(embarked["id"])
    assert folio is not None
    assert folio["status"] == "OPEN"
    assert folio["gratuity_mode"] == "PROVISIONAL"
    assert folio["gratuity_total_cents"] == 37800  # 1800 * 3 * 7


def test_settle_folio_with_outstanding_balance_rejected(api):
    """PRD 3.7: "Settling the folio completes the booking (`EMBARKED → COMPLETED`),
    performed by a `PortAgent`. It requires the folio's `balance_due_cents` to be
    exactly 0; a non-zero balance is rejected with `ERR_FOLIO_OUTSTANDING`."

    Design: Corner/state_machines/settle_folio_with_outstanding_balance_rejected
    """
    set_clock("2026-06-18T16:00:00Z")
    sailing, category, embarked = create_embarked_booking(
        "guest-c5", num_guests=3, num_cabins=1,
    )
    # Provisional gratuity 37800 is unpaid -> balance is non-zero.
    resp = api.settle_folio(embarked["id"], PA)
    validate_error(resp, ApiErrorId.ERR_FOLIO_OUTSTANDING.value)


def test_folio_charge_reverse_recomputes_balance(api):
    """PRD 3.7: "A `PortAgent` may reverse a posted charge (`POSTED → REVERSED`,
    with a repeat reversal rejected as `ERR_INVALID_STATE`), which recomputes the
    folio totals." PRD 3.7: "The folio's `charges_total_cents` is the sum of
    `amount_cents` over the folio's `POSTED` folio charges".

    Design: Corner/endpoints/folio_charge_reverse_recomputes_balance
    """
    set_clock("2026-06-18T16:00:00Z")
    sailing, category, embarked = create_embarked_booking(
        "guest-c13", num_guests=3, num_cabins=1,
    )
    folio = get_folio_for_booking(embarked["id"])
    charge = get_success_data(
        api.post_folio_charge(folio["id"], create_folio_charge_payload("Spa", 5000), PA)
    )
    resp = api.reverse_folio_charge(charge["id"], PA)
    data = validate_success(resp)
    assert data["status"] == "REVERSED"
    after = get_success_data(api.get_folio(folio["id"], PA))
    assert after["charges_total_cents"] == 0
    assert after["balance_due_cents"] == 37800  # gratuity-only
