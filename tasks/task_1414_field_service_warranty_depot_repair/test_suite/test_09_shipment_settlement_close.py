"""Shipment gates, containment, settlement tiers, closure, and scrap."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_quote,
    consume_part_ok,
    contain_escalation,
    create_loaner_unit,
    create_manual_escalation,
    create_draft_rma,
    decline_quote,
    diagnose_rma,
    get_product_model,
    get_rma,
    get_reservation,
    get_escalation,
    get_unit,
    list_quotes,
    make_depot_manager_headers,
    make_warranty_admin_headers,
    planned_part_line,
    qa_release,
    receive_rma,
    repair_complete,
    resolve_escalation,
    return_reservation,
    set_clock,
    setup_awaiting_quote_rma,
    setup_catalog,
    setup_shipped_loaner_rma,
    ship_reservation,
    ship_rma,
    triage_rma,
    validate_error,
    validate_success,
    create_reservation,
    create_failure_code,
    create_part,
    create_customer,
    create_model,
    create_unit,
    authorize_rma,
)

TECH2_HEADERS = None  # built lazily in fixtures needing a distinct technician


def _tech2():
    from test_helpers import make_depot_technician_headers
    return make_depot_technician_headers("tech-2")


def _setup_contained_model_with_pending_replacement(service_option=None):
    """Model under containment via a manual escalation on RMA-X; RMA-Y
    diagnosed BER -> REPLACEMENT_PENDING on the same model."""
    model = create_model()
    customer = create_customer()
    unit_x = create_unit(model["id"], customer["id"], serial_number="SN-CX-1")
    unit_y = create_unit(model["id"], customer["id"], serial_number="SN-CY-1")
    fc = create_failure_code(code="F-BAT-09", description="Battery swell",
                             severity="CRITICAL")
    rma_x = create_draft_rma(customer["id"], unit_x["id"], reported_issue="safety")
    esc = create_manual_escalation(rma_x["id"], fc["id"])
    contain_escalation(esc["id"])
    assert get_product_model(model["id"])["containment_flag"] is True

    rma_y = create_draft_rma(customer["id"], unit_y["id"],
                             service_option=service_option)
    authorize_rma(rma_y["id"])
    receive_rma(rma_y["id"], unit_y["serial_number"])
    triage_rma(rma_y["id"], fc["id"])
    rma_y = diagnose_rma(rma_y["id"], labor_minutes_est=30, repairability="BER",
                         planned_parts=[])
    assert rma_y["decision"] == "REPLACE"
    assert rma_y["status"] == "REPLACEMENT_PENDING"
    return {"model": model, "customer": customer, "esc": esc, "rma_y": rma_y}


def test_ship_replacement_blocked_while_contained(api):
    """PRD §3.8: "From `REPLACEMENT_PENDING`, a replacement unit ships, which is
    guarded twice: the unit's model must not be under containment, otherwise the
    ship is rejected with `ERR_MODEL_CONTAINMENT`"
    PRD §3.9: "Activating containment — available from either `OPEN` or
    `ACKNOWLEDGED` — moves it to `CONTAINMENT_ACTIVE` and sets the model's
    `containment_flag` true, which is precisely what blocks replacement shipment
    of that model per §3.8."

    Design: Difficulty/cross_entity_state_dependency/replacement_ship_gated_by_model_containment
    """
    ctx = _setup_contained_model_with_pending_replacement()
    res = api.ship_rma(ctx["rma_y"]["id"],
                       {"carrier": "UPS", "tracking_number": "1Z"},
                       TEST_USERS["depot_technician_headers"])
    validate_error(res, ApiErrorId.ERR_MODEL_CONTAINMENT)
    assert res.status_code == 409
    assert get_rma(ctx["rma_y"]["id"])["status"] == "REPLACEMENT_PENDING"


def test_ship_replacement_allowed_after_containment_released(api):
    """PRD §3.9: "Resolution clears `engineering_review_pending` on every RMA
    sharing the escalation's (model, failure code) pair, and releases the
    model's `containment_flag` — unless another escalation for the same model
    remains in `CONTAINMENT_ACTIVE`."
    PRD §3.8: "Replacement shipment pins `return_reason` to `REPLACED`."

    Design: Difficulty/cross_entity_state_dependency/replacement_ship_gated_by_model_containment
    """
    ctx = _setup_contained_model_with_pending_replacement()
    resolved = resolve_escalation(ctx["esc"]["id"],
                                  note="containment lifted after retrofit")
    assert resolved["status"] == "MONITORING", (
        f"resolve must land in MONITORING, got {resolved['status']}")
    assert get_product_model(ctx["model"]["id"])["containment_flag"] is False

    shipped = ship_rma(ctx["rma_y"]["id"])
    assert shipped["status"] == "SHIPPED"
    assert shipped["return_reason"] == "REPLACED"


def test_containment_error_wins_over_exchange_fulfillment(api):
    """PRD §2.8: "The safety gates come first among them: model containment
    (`ERR_MODEL_CONTAINMENT`), the engineering-review gate
    (`ERR_ENGINEERING_REVIEW_PENDING`), and segregation-of-duties
    (`ERR_SEGREGATION_OF_DUTIES`) are evaluated ahead of the referential and
    constraint rules."
    PRD §2.8: "the advance-exchange fulfillment check
    (`ERR_EXCHANGE_NOT_FULFILLED`); and the outstanding-loaner check
    (`ERR_LOANER_OUTSTANDING`)."

    Design: Difficulty/priority_pair_validation_conflict/containment_beats_exchange_not_fulfilled
    """
    # ADVANCE_EXCHANGE RMA-Y with NO reservation at all: both the containment
    # gate and the exchange-fulfillment check are violated; containment wins.
    ctx = _setup_contained_model_with_pending_replacement(
        service_option="ADVANCE_EXCHANGE")
    res = api.ship_rma(ctx["rma_y"]["id"],
                       {"carrier": "UPS", "tracking_number": "1Z9"},
                       TEST_USERS["depot_technician_headers"])
    validate_error(res, ApiErrorId.ERR_MODEL_CONTAINMENT)
    assert res.status_code == 409


def test_blocked_ship_leaves_replacement_pending_unchanged(api):
    """PRD §3.4: "When the technician's verdict is `BER`, the decision is
    `REPLACE`."
    PRD §3.4: "A `REPLACE` decision routes to `REPLACEMENT_PENDING` regardless
    of coverage."

    Design: Difficulty/priority_pair_validation_conflict/containment_beats_exchange_not_fulfilled
    """
    ctx = _setup_contained_model_with_pending_replacement(
        service_option="ADVANCE_EXCHANGE")
    api.ship_rma(ctx["rma_y"]["id"], {"carrier": "UPS", "tracking_number": "1Z9"},
                 TEST_USERS["depot_technician_headers"])
    after = get_rma(ctx["rma_y"]["id"])
    assert after["status"] == "REPLACEMENT_PENDING", (
        "the rejected ship must leave the RMA in REPLACEMENT_PENDING")
    assert after["decision"] == "REPLACE", (
        "the rejected ship must leave the BER-forced REPLACE decision intact")


def test_close_blocked_by_outstanding_loaner(api):
    """PRD §3.8: "Closure by an `IntakeAgent` or `DepotManager` moves a
    `SHIPPED` RMA to `CLOSED` and is blocked while any of its reservations
    remains in `RESERVED` or `SHIPPED`, surfacing `ERR_LOANER_OUTSTANDING` until
    the loaner is returned, forfeited, or otherwise released."

    Design: Corner/validations/close_blocked_by_outstanding_loaner
    """
    ctx = setup_shipped_loaner_rma()
    blocked = api.close_rma(ctx["rma"]["id"], TEST_USERS["intake_agent_headers"])
    validate_error(blocked, ApiErrorId.ERR_LOANER_OUTSTANDING)
    assert blocked.status_code == 409

    return_reservation(ctx["res"]["id"], condition="OK")
    closed = validate_success(
        api.close_rma(ctx["rma"]["id"], TEST_USERS["intake_agent_headers"]), 200)
    assert closed["status"] == "CLOSED"


def _setup_settlement_scenario():
    """OOW LOANER RMA: approved quote total 44280 (line 4x5000 -> 21000 with
    handling, labor 100 min -> 20000, tax 3280); loaner shipped at 2026-08-01,
    returned 3 days past the 2026-08-11 due date -> late fee 7500."""
    from test_helpers.fixtures import setup_catalog
    model = create_model(loaner_grace_days=10)
    customer = create_customer(credit_limit_cents=100000)
    unit = create_unit(model["id"], customer["id"], purchase_date="2024-01-01",
                       ship_date="2024-01-01")
    fc = create_failure_code()
    part = create_part()
    lu = create_loaner_unit(model["id"])
    rma = create_draft_rma(customer["id"], unit["id"], service_option="LOANER")
    rma = authorize_rma(rma["id"])
    assert rma["coverage_path"] == "OUT_OF_WARRANTY"
    res = create_reservation(rma["id"], lu["id"])
    receive_rma(rma["id"], unit["serial_number"])
    triage_rma(rma["id"], fc["id"])
    rma = diagnose_rma(rma["id"], labor_minutes_est=100,
                       planned_parts=[planned_part_line(part["id"], 4)])
    assert rma["status"] == "AWAITING_QUOTE_APPROVAL"
    quote = list_quotes(rma["id"])[0]
    ship_reservation(res["id"])
    approve_quote(quote["id"], customer["id"], "pay-1")
    version = get_rma(rma["id"])["version"]
    consume_part_ok(rma["id"], part["id"], 4, fc["id"], version)
    repair_complete(rma["id"])
    qa_release(rma["id"], "PASS", tech_headers=_tech2())
    ship_rma(rma["id"], tech_headers=_tech2())
    set_clock("2026-08-14T00:00:00Z")
    returned = return_reservation(res["id"], condition="OK")
    return {"model": model, "customer": customer, "rma_id": rma["id"],
            "res": returned, "quote": quote}


def test_settlement_tier_keyed_on_gross_before_credit(api):
    """PRD §3.8: "The loyalty tier is keyed on that gross before any credit: a
    gross of at least 50000 cents earns ten percent, a gross of at least 20000
    cents but below 50000 earns five percent, and anything below earns nothing."
    PRD §3.8: "The evaluation order is pinned — gross first, tier from gross,
    then credit, then net — and the net is never fed back into tier selection."

    Design: Difficulty/combinatorial_formula/settlement_tier_keyed_on_gross
    """
    ctx = _setup_settlement_scenario()
    closed = validate_success(
        api.close_rma(ctx["rma_id"], TEST_USERS["intake_agent_headers"]), 200)
    # gross = 44280 (approved quote) + 7500 (late fee) = 51780
    assert closed["settlement_gross_cents"] == 51780, (
        f"gross must be 44280 + 7500 = 51780, got {closed['settlement_gross_cents']}")
    # tier keyed on gross 51780 -> 10% -> credit round(5178.0) = 5178
    assert closed["settlement_loyalty_credit_cents"] == 5178, (
        f"credit must be 10% of gross = 5178, got "
        f"{closed['settlement_loyalty_credit_cents']}")
    # net 46602 is itself below the 50000 tier and must NOT be re-evaluated
    assert closed["settlement_total_cents"] == 46602, (
        f"net must be 51780 - 5178 = 46602, got {closed['settlement_total_cents']}")
    assert closed["status"] == "CLOSED"


def test_loaner_late_fee_feeds_settlement_gross(api):
    """PRD §3.8: "The settlement gross — `settlement_gross_cents` — is the
    `total_cents` of the RMA's current `APPROVED` quote (zero when no approved
    quote exists) plus, summed over all of the RMA's loaner reservations, each
    reservation's `late_fee_cents`, `damage_fee_cents`, and
    `forfeit_charge_cents`."
    PRD §3.7: "Past the due date, the days late are the calendar days strictly
    after the `due_date` up to and including the as-of date, and the fee is the
    days late multiplied by 2500 cents, capped at the unit's
    `deposit_value_cents`."

    Design: Difficulty/combinatorial_formula/settlement_tier_keyed_on_gross
    """
    ctx = _setup_settlement_scenario()
    # due_date = ship 2026-08-01 + 10 grace days = 2026-08-11; return at
    # 2026-08-14 -> 3 days late (08-12, 08-13, 08-14) at 2500/day = 7500
    assert ctx["res"]["due_date"][:10] == "2026-08-11"
    assert ctx["res"]["late_fee_cents"] == 7500, (
        f"late fee must be 3 * 2500 = 7500, got {ctx['res']['late_fee_cents']}")

    closed = validate_success(
        api.close_rma(ctx["rma_id"], TEST_USERS["intake_agent_headers"]), 200)
    assert closed["settlement_gross_cents"] == 51780
    assert closed["status"] == "CLOSED"
    assert closed["closed_at"] is not None


def test_scrap_segregated_from_goodwill_grantor(api):
    """PRD §2.9: "A manager scrapping a unit after a declined quote must not be
    the administrator recorded in the RMA's `warranty_override_by`, whenever
    that field is set; when no goodwill grant exists on the RMA, this third
    check does not apply."
    PRD §3.2: "When a `SENT` quote is outstanding on the RMA, the grant
    supersedes it — the old quote becomes `SUPERSEDED` — and creates a
    replacement quote with the next `quote_seq` whose `discount_pct` equals the
    granted `goodwill_pct`, while an RMA waiting on quote approval stays in
    `AWAITING_QUOTE_APPROVAL`."
    PRD §3.5: "Alternatively, a `DepotManager` may scrap the unit, subject to
    the segregation-of-duties rule of §2.9 against `warranty_override_by`: the
    RMA moves from `QUOTE_DECLINED` to `SCRAPPED`, the unit's `disposition`
    becomes `SCRAPPED`, the SLA pause closes, and the settlement fields are
    computed per §3.8 from loaner fees only, since no approved quote exists."

    Design: Corner/validations/scrap_segregated_from_goodwill_grantor
    """
    ctx = setup_awaiting_quote_rma()
    rma = ctx["rma"]
    # Goodwill grant by wa-1 supersedes Q1 and regenerates it with 25% off.
    validate_success(api.warranty_override(
        rma["id"],
        {"override_coverage": "GOODWILL_PARTIAL", "goodwill_pct": 25,
         "reason": "loyalty"},
        make_warranty_admin_headers("wa-1")), 200)
    quotes = list_quotes(rma["id"])
    q2 = [q for q in quotes if q["quote_seq"] == 2][0]
    # subtotal 9250; discount round_half_up(9250*0.25)=2313; taxable 6937;
    # tax round_half_up(6937*0.08)=555; total 7492
    assert q2["discount_pct"] == 25
    assert q2["discount_cents"] == 2313
    assert q2["total_cents"] == 7492, (
        f"goodwill-regenerated quote total must be 7492, got {q2['total_cents']}")

    rma_after = get_rma(rma["id"])
    assert rma_after["coverage_path"] == "GOODWILL_PARTIAL"
    assert rma_after["warranty_override_by"] == "wa-1"
    decline_quote(q2["id"], ctx["customer"]["id"])

    # The goodwill grantor may not scrap the same RMA.
    blocked = api.scrap_rma(rma["id"], make_depot_manager_headers("wa-1"))
    validate_error(blocked, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    assert blocked.status_code == 403

    scrapped = validate_success(
        api.scrap_rma(rma["id"], make_depot_manager_headers("mgr-9")), 200)
    assert scrapped["status"] == "SCRAPPED"
    assert get_unit(ctx["unit"]["id"])["disposition"] == "SCRAPPED"
    # No approved quote and no loaner fees: settlement computes to zero.
    assert scrapped["settlement_gross_cents"] == 0
    assert scrapped["settlement_total_cents"] == 0
