"""TradeIn / Quote / ShippingKit / InspectionSlot state-machine transitions:
invalid transitions, idempotency, terminal lockdown, valid transitions, side effects.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    find_quote,
    setup_catalog_model_customer,
    create_draft_trade_in,
    create_quoted_trade_in,
    create_received_trade_in,
    setup_requoted_trade_in,
    inspect,
    create_catalog,
    get_quotes,
    get_disposition_records,
    get_shipping_kits,
    api_client,
    make_customer_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["catalog_admin_headers"]
AGENT = TEST_USERS["grading_agent_headers"]
FINANCE = TEST_USERS["finance_operator_headers"]


def test_ship_kit_from_draft_returns_invalid_state(api):
    """PRD §3.5: "Once a trade-in is `QUOTED`, the owning `Customer` requests a
    **shipping kit**, advancing the trade-in from `QUOTED` to `KIT_SENT`."
    PRD §2.4: "State legality ... otherwise `ERR_INVALID_STATE`."

    POST /ship-kit on a DRAFT trade-in (never quoted) is rejected with
    ERR_INVALID_STATE; status stays DRAFT.

    Design: Corner/state_machines/ship_kit_from_draft_returns_invalid_state
    """
    _cat, model, customer = setup_catalog_model_customer()
    ti = create_draft_trade_in(customer, model, declared_grade="GOOD")
    resp = api.ship_kit(ti["id"], make_customer_headers(customer["id"]))
    validate_error(resp, "ERR_INVALID_STATE")
    assert validate_success(api.get_trade_in(ti["id"], ADMIN))["status"] == "DRAFT"


def test_double_quote_returns_invalid_state(api):
    """PRD §3.4: "A `Customer` who owns a `DRAFT` trade-in asks the system to **quote**
    it, advancing it from `DRAFT` to `QUOTED`."
    PRD §2.4: "State legality ... otherwise `ERR_INVALID_STATE`."

    A second /quote on an already-QUOTED trade-in is rejected with ERR_INVALID_STATE;
    status stays QUOTED.

    Design: Corner/state_machines/double_quote_from_quoted_returns_invalid_state
    """
    _cat, model, customer = setup_catalog_model_customer()
    ti = create_quoted_trade_in(customer, model, declared_grade="GOOD")
    resp = api.quote_trade_in(ti["id"], make_customer_headers(customer["id"]))
    validate_error(resp, "ERR_INVALID_STATE")
    assert validate_success(api.get_trade_in(ti["id"], ADMIN))["status"] == "QUOTED"


def test_cancel_from_paid_terminal_returns_invalid_state(api):
    """PRD §3.4: "A `Customer` may **cancel** a trade-in while it is still in `DRAFT`
    or `QUOTED`, moving it to the terminal `CANCELLED` state."
    PRD §2.4: "State legality ... otherwise `ERR_INVALID_STATE`."

    Cancelling a PAID (terminal) trade-in is rejected with ERR_INVALID_STATE; status
    stays PAID.

    Design: Corner/state_machines/cancel_from_paid_terminal_returns_invalid_state
    """
    _cat, model, customer = setup_catalog_model_customer()
    ti = create_received_trade_in(customer, model, declared_grade="FLAWLESS")
    inspect(ti["id"], "FLAWLESS", verified_defects=[])
    validate_success(api.create_payout(ti["id"], {"method": "ACH"}, FINANCE), expected_status=201)

    resp = api.cancel_trade_in(ti["id"], make_customer_headers(customer["id"]))
    validate_error(resp, "ERR_INVALID_STATE")
    assert validate_success(api.get_trade_in(ti["id"], ADMIN))["status"] == "PAID"


def test_accept_requote_happy_path_honors_requote(api):
    """PRD §3.6: "on success it moves the `REQUOTE` quote to `HONORED` and sets
    `final_value_cents` to that quote's amount."
    PRD §3.6: "**accepts** the re-quote, advancing the trade-in from `REQUOTED` to
    `ACCEPTED`".

    Accepting the re-quote (carrying the current version) honors the REQUOTE quote;
    final_value_cents equals the 16000 inspected value.

    Design: Corner/state_machines/accept_requote_happy_path_honors_requote
    """
    _cat, model, customer = setup_catalog_model_customer()
    inspected, version = setup_requoted_trade_in(customer, model)
    ch = make_customer_headers(customer["id"])

    accepted = validate_success(api.accept_requote(inspected["id"], {"expected_trade_in_version": version}, ch))
    assert accepted["status"] == "ACCEPTED"
    assert accepted["final_value_cents"] == 16000
    requote = find_quote(get_quotes(inspected["id"]), kind="REQUOTE")
    assert requote["status"] == "HONORED"


def test_decline_requote_returns_device_and_rejects(api):
    """PRD §3.6: "A decline moves the `REQUOTE` quote to `SUPERSEDED` and creates a
    `DispositionRecord` with `disposition` of `RETURN_TO_CUSTOMER`".
    PRD §3.6: "**declines** it, advancing from `REQUOTED` to the terminal `REJECTED` state."

    Declining the re-quote drives the trade-in to REJECTED, supersedes the REQUOTE
    quote, and creates a RETURN_TO_CUSTOMER disposition record.

    Design: Corner/state_machines/decline_requote_returns_device_and_rejects
    """
    _cat, model, customer = setup_catalog_model_customer()
    inspected, version = setup_requoted_trade_in(customer, model)
    ch = make_customer_headers(customer["id"])

    declined = validate_success(api.decline_requote(inspected["id"], {"expected_trade_in_version": version}, ch))
    assert declined["status"] == "REJECTED"
    requote = find_quote(get_quotes(inspected["id"]), kind="REQUOTE")
    assert requote["status"] == "SUPERSEDED"
    records = get_disposition_records(inspected["id"])
    returns = [r for r in records if r["disposition"] == "RETURN_TO_CUSTOMER"]
    assert len(returns) == 1


def test_cancel_quoted_supersedes_quote(api):
    """PRD §3.4: "cancelling from `QUOTED` also supersedes the locked quote, moving
    that `Quote` to `SUPERSEDED`."

    Cancelling a QUOTED trade-in drives it to CANCELLED and supersedes its locked
    INITIAL quote.

    Design: Corner/state_machines/cancel_quoted_supersedes_quote
    """
    _cat, model, customer = setup_catalog_model_customer()
    ti = create_quoted_trade_in(customer, model, declared_grade="GOOD")
    cancelled = validate_success(api.cancel_trade_in(ti["id"], make_customer_headers(customer["id"])))
    assert cancelled["status"] == "CANCELLED"
    initial = find_quote(get_quotes(ti["id"]), kind="INITIAL")
    assert initial["status"] == "SUPERSEDED"


def test_receive_marks_kit_delivered_to_hub(api):
    """PRD §3.5: "Receiving likewise requires that the locked quote has not expired ...
    and as a side effect it moves the shipping kit's `status` to `DELIVERED_TO_HUB`."

    POST /receive moves the trade-in to RECEIVED and flips the ShippingKit status from
    DISPATCHED to DELIVERED_TO_HUB.

    Design: Corner/state_machines/receive_marks_kit_delivered_to_hub
    """
    _cat, model, customer = setup_catalog_model_customer()
    ti = create_quoted_trade_in(customer, model, declared_grade="GOOD")
    ch = make_customer_headers(customer["id"])
    validate_success(api.ship_kit(ti["id"], ch))
    received = validate_success(api.receive_trade_in(ti["id"], AGENT))
    assert received["status"] == "RECEIVED"
    kits = get_shipping_kits(ti["id"])
    assert len(kits) == 1
    assert kits[0]["status"] == "DELIVERED_TO_HUB"


def test_inspect_unknown_defect_returns_422(api):
    """PRD §3.6: "Every entry in `verified_defects` must be a key present in the model's
    `defect_deductions`, otherwise the submission is rejected with `ERR_UNKNOWN_DEFECT`
    (HTTP 422)."

    POST /inspect with a verified defect not in the model's defect_deductions keys
    returns ERR_UNKNOWN_DEFECT; trade-in stays RECEIVED.

    Design: Corner/state_machines/inspect_unknown_defect_returns_422
    """
    _cat, model, customer = setup_catalog_model_customer()
    ti = create_received_trade_in(customer, model, declared_grade="GOOD")
    resp = api.inspect_trade_in(
        ti["id"], {"verified_grade": "GOOD", "verified_defects": ["SCRATCHED_LENS"], "verified_powers_on": True}, AGENT
    )
    validate_error(resp, "ERR_UNKNOWN_DEFECT")
    assert validate_success(api.get_trade_in(ti["id"], ADMIN))["status"] == "RECEIVED"


def test_slot_release_then_rebook_succeeds(api):
    """PRD §3.8: "releasing moves its `status` to `RELEASED`, after which its interval
    no longer participates in overlap checks for subsequent bookings."

    Releasing a BOOKED slot frees its interval so a previously-conflicting booking on
    the same lane now succeeds; the released slot reads RELEASED.

    Design: Corner/state_machines/slot_release_then_rebook_succeeds
    """
    cat = create_catalog()
    s1 = validate_success(
        api.create_inspection_slot(
            cat["id"],
            {"lane_category": "SMARTPHONE", "slot_start": "2026-06-10T10:00:00Z", "slot_end": "2026-06-10T11:00:00Z"},
            AGENT,
        ),
        expected_status=201,
    )
    validate_success(api.release_inspection_slot(s1["id"], AGENT))

    s2 = validate_success(
        api.create_inspection_slot(
            cat["id"],
            {"lane_category": "SMARTPHONE", "slot_start": "2026-06-10T10:30:00Z", "slot_end": "2026-06-10T11:30:00Z"},
            AGENT,
        ),
        expected_status=201,
    )
    assert s2["status"] == "BOOKED"

    listed, _ = validate_paginated(api.list_inspection_slots(cat["id"], AGENT))
    s1_now = [s for s in listed if s["id"] == s1["id"]][0]
    assert s1_now["status"] == "RELEASED"


def test_reinspect_supersedes_and_mints_new_requote(api):
    """PRD §3.6: "A valid re-inspection creates a second `Inspection`, recomputes
    `inspected_value_cents`, supersedes the current `REQUOTE` quote (moving it to
    `SUPERSEDED`), and mints a new `LOCKED` `REQUOTE` quote at the new inspected value
    with `promo_bonus_cents` of 0 and a refreshed `lock_expires_at`, repointing
    `locked_quote_id`."

    Re-inspecting a REQUOTED trade-in (POOR+BATTERY_DEGRADED+MISSING_PARTS -> 12000,
    a fresh downgrade below the 16000 REQUOTE quote's tolerance band but above the
    recycle floor) supersedes the 16000 REQUOTE quote and mints a new LOCKED REQUOTE
    quote at 12000; the trade-in stays REQUOTED.

    Design: Corner/state_machines/reinspect_supersedes_and_mints_new_requote
    """
    _cat, model, customer = setup_catalog_model_customer()
    inspected, _version = setup_requoted_trade_in(customer, model)

    validate_success(api.reinspect_trade_in(
        inspected["id"], {"verified_grade": "POOR", "verified_defects": ["BATTERY_DEGRADED", "MISSING_PARTS"], "verified_powers_on": True}, AGENT
    ))

    assert validate_success(api.get_trade_in(inspected["id"], ADMIN))["status"] == "REQUOTED"
    quotes = get_quotes(inspected["id"])
    requotes = [q for q in quotes if q["kind"] == "REQUOTE"]
    new_locked = [q for q in requotes if q["status"] == "LOCKED" and q["amount_cents"] == 12000]
    assert len(new_locked) == 1, f"expected one LOCKED REQUOTE at 12000, got {[(q['status'], q['amount_cents']) for q in requotes]}"
    old = [q for q in requotes if q["amount_cents"] == 16000]
    assert len(old) == 1 and old[0]["status"] == "SUPERSEDED"
