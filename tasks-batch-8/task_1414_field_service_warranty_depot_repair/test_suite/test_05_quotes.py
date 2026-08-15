"""Out-of-warranty quoting: pinned rounding, revision chain, approval gates."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_quote,
    decline_quote,
    get_rma,
    list_quotes,
    make_customer_headers,
    revise_quote,
    set_clock,
    setup_awaiting_quote_rma,
    planned_part_line,
    validate_error,
    validate_success,
)


def _setup_rounding_quote(api):
    """OOW RMA whose auto-quote has lines chosen so per-line-round-then-sum
    diverges by one cent from sum-then-round (1045 and 1046 unit costs)."""
    from test_helpers.fixtures import (
        authorize_rma, create_customer, create_failure_code, create_model,
        create_part, create_unit, diagnose_rma, receive_rma, triage_rma,
        create_draft_rma,
    )
    model = create_model()
    customer = create_customer()
    unit = create_unit(model["id"], customer["id"], purchase_date="2024-01-01",
                       ship_date="2024-01-01")
    fc = create_failure_code()
    part_a = create_part(sku="PA-RND", unit_cost_cents=1045, initial_stock=10)
    part_b = create_part(sku="PB-RND", unit_cost_cents=1046, initial_stock=10)
    rma = create_draft_rma(customer["id"], unit["id"])
    authorize_rma(rma["id"])
    receive_rma(rma["id"], unit["serial_number"])
    triage_rma(rma["id"], fc["id"])
    diagnosed = diagnose_rma(rma["id"], labor_minutes_est=0,
                             planned_parts=[planned_part_line(part_a["id"], 1),
                                            planned_part_line(part_b["id"], 1)])
    assert diagnosed["status"] == "AWAITING_QUOTE_APPROVAL"
    quote = list_quotes(rma["id"])[0]
    return {"rma": diagnosed, "quote": quote, "customer": customer}


def test_quote_per_line_rounding_then_sum(api):
    """PRD §3.5: "The totals follow a pinned rounding order — per-line rounding
    first, then summation. Each line's `line_total_cents` is its `quantity`
    multiplied by its snapshot `unit_cost_cents`, increased by a five percent
    handling uplift, rounded half-up to whole cents at creation; the
    `parts_subtotal_cents` is the sum of those already-rounded line totals."

    Design: Difficulty/combinatorial_formula/quote_line_rounding_order_pinned
    """
    ctx = _setup_rounding_quote(api)
    quote = ctx["quote"]
    # per-line: round(1045*1.05)=round(1097.25)=1097; round(1046*1.05)=round(1098.30)=1098
    line_totals = sorted(l["line_total_cents"] for l in quote["lines"])
    assert line_totals == [1097, 1098], (
        f"per-line rounded totals must be [1097, 1098], got {line_totals}")
    # pinned order: 1097 + 1098 = 2195 (sum-then-round would give 2196)
    assert quote["parts_subtotal_cents"] == 2195, (
        f"parts subtotal must be the sum of rounded lines 2195, got "
        f"{quote['parts_subtotal_cents']}")
    assert quote["labor_cents"] == 0


def test_quote_tax_and_total_follow_pinned_order(api):
    """PRD §3.5: "The `taxable_cents` is the subtotal minus the discount, and
    the `tax_cents` is eight percent of the taxable amount, rounded half-up."
    PRD §3.5: "The `total_cents` is the taxable amount plus tax plus the
    expedite fee."
    PRD §3.4: "A `REPAIR` decision with `coverage_path` `OUT_OF_WARRANTY` or
    `GOODWILL_PARTIAL` routes to `AWAITING_QUOTE_APPROVAL` and auto-creates a
    quote in `SENT` with `quote_seq` 1"

    Design: Difficulty/combinatorial_formula/quote_line_rounding_order_pinned
    """
    ctx = _setup_rounding_quote(api)
    quote = ctx["quote"]
    # taxable 2195, tax round_half_up(2195*0.08)=round(175.6)=176, total 2371
    assert quote["taxable_cents"] == 2195
    assert quote["tax_cents"] == 176, (
        f"tax must be round_half_up(2195*0.08)=176, got {quote['tax_cents']}")
    assert quote["total_cents"] == 2371, (
        f"total must be 2195 + 176 + 0 = 2371, got {quote['total_cents']}")
    assert quote["status"] == "SENT"
    assert quote["quote_seq"] == 1
    assert ctx["rma"]["status"] == "AWAITING_QUOTE_APPROVAL"


def test_declined_quote_superseded_by_revision(api):
    """PRD §3.5: "A revision moves the previous latest quote to `SUPERSEDED`,
    creates the new quote in `SENT` with `quote_seq` one greater than its
    predecessor and totals computed by the pinned quote-total rules above,
    increments the RMA's `version` by one, returns a `QUOTE_DECLINED` RMA to
    `AWAITING_QUOTE_APPROVAL` (an RMA already waiting stays waiting), and fires
    a fresh `QUOTE_SENT` notification."

    Design: Difficulty/non_linear_state_machine/rma_quote_decline_revise_cycle
    """
    ctx = setup_awaiting_quote_rma()
    rma, q1 = ctx["rma"], ctx["quote"]
    decline_quote(q1["id"], ctx["customer"]["id"])

    q2 = revise_quote(rma["id"], labor_minutes=50,
                      parts_lines=[planned_part_line(ctx["part"]["id"], 1)],
                      expected_rma_version=get_rma(rma["id"])["version"])
    # line round(1*5000*1.05)=5250, labor 50*200=10000, subtotal 15250,
    # tax round(15250*0.08)=1220, total 16470
    assert q2["quote_seq"] == 2, f"revision must carry quote_seq 2, got {q2['quote_seq']}"
    assert q2["total_cents"] == 16470, (
        f"revised quote total must be 16470, got {q2['total_cents']}")
    assert q2["status"] == "SENT"

    from test_helpers import get_quote
    q1_after = get_quote(q1["id"])
    assert q1_after["status"] == "SUPERSEDED", (
        f"the declined quote must be SUPERSEDED by the revision, got "
        f"{q1_after['status']}")


def test_approve_revised_quote_closes_single_sla_pause(api):
    """PRD §3.5: "Approval moves the quote to `APPROVED`, pins `decided_at` and
    the `payment_reference`, moves the RMA from `AWAITING_QUOTE_APPROVAL` to
    `IN_REPAIR`, closes the open SLA pause interval by appending it to
    `sla_pause_intervals`, and emits a `QUOTE_APPROVED` notification."
    PRD §3.5: "All the while, the RMA's `sla_pause_intervals` accumulate the
    half-open intervals, from opening to closing instant, spent in
    `AWAITING_QUOTE_APPROVAL` or `QUOTE_DECLINED`; they are subtracted from
    elapsed turnaround per §3.9."

    Design: Difficulty/non_linear_state_machine/rma_quote_decline_revise_cycle
    """
    ctx = setup_awaiting_quote_rma()
    rma, q1 = ctx["rma"], ctx["quote"]
    decline_quote(q1["id"], ctx["customer"]["id"])
    q2 = revise_quote(rma["id"], labor_minutes=50,
                      parts_lines=[planned_part_line(ctx["part"]["id"], 1)],
                      expected_rma_version=get_rma(rma["id"])["version"])

    approved = approve_quote(q2["id"], ctx["customer"]["id"], "pay-2")
    assert approved["status"] == "APPROVED"
    assert approved["payment_reference"] == "pay-2"
    assert approved["decided_at"] is not None

    rma_after = get_rma(rma["id"])
    assert rma_after["status"] == "IN_REPAIR", (
        f"approving the current quote must move the RMA to IN_REPAIR, got "
        f"{rma_after['status']}")
    intervals = rma_after["sla_pause_intervals"]
    assert len(intervals) == 1, (
        "the pause opened at diagnose closes exactly once at approve; got "
        f"{len(intervals)} intervals")


def test_repair_complete_blocked_while_quote_sent(api):
    """PRD §3.6: "Success moves the RMA from `IN_REPAIR` to `QA_HOLD` and pins
    the technician's `X-User-ID` as `repair_completed_by`."
    PRD §2.8: "Sixth, state-machine legality — whether the target entity is in a
    state permitting the requested transition — yielding the matching error
    among `ERR_INVALID_RMA_STATE`, `ERR_INVALID_QUOTE_STATE`,
    `ERR_INVALID_RESERVATION_STATE`, `ERR_INVALID_LOANER_STATE`,
    `ERR_INVALID_ESCALATION_STATE`, and `ERR_INVALID_LINE_STATE`."

    Design: Difficulty/cross_entity_state_dependency/rma_repair_gated_by_quote_approval
    """
    ctx = setup_awaiting_quote_rma()
    res = api.repair_complete(ctx["rma"]["id"], TEST_USERS["depot_technician_headers"])
    validate_error(res, ApiErrorId.ERR_INVALID_RMA_STATE)
    assert res.status_code == 409, (
        "repair-complete from AWAITING_QUOTE_APPROVAL must be rejected")


def test_quote_approval_unlocks_in_repair(api):
    """PRD §3.5: "Approval moves the quote to `APPROVED`, pins `decided_at` and
    the `payment_reference`, moves the RMA from `AWAITING_QUOTE_APPROVAL` to
    `IN_REPAIR`, closes the open SLA pause interval by appending it to
    `sla_pause_intervals`, and emits a `QUOTE_APPROVED` notification."

    Design: Difficulty/cross_entity_state_dependency/rma_repair_gated_by_quote_approval
    """
    ctx = setup_awaiting_quote_rma()
    approved = approve_quote(ctx["quote"]["id"], ctx["customer"]["id"], "pay-1")
    assert approved["status"] == "APPROVED"
    rma_after = get_rma(ctx["rma"]["id"])
    assert rma_after["status"] == "IN_REPAIR", (
        f"the quote transition must unlock the RMA to IN_REPAIR, got "
        f"{rma_after['status']}")


def test_quote_double_approve_rejected(api):
    """PRD §3.5: "The quote must resolve (an unresolvable reference is
    `ERR_QUOTE_NOT_FOUND`), must be the RMA's current quote and in `SENT`
    (otherwise `ERR_INVALID_QUOTE_STATE`), and the logical clock must not be
    later than the quote's `expires_at` — approval at or before the expiry
    instant is permitted, approval after it is rejected with
    `ERR_QUOTE_EXPIRED`."

    Design: Corner/state_machines/quote_double_approve_rejected
    """
    ctx = setup_awaiting_quote_rma()
    q1 = ctx["quote"]
    approve_quote(q1["id"], ctx["customer"]["id"], "pay-1")

    res = api.approve_quote(q1["id"], {"payment_reference": "pay-2"},
                            make_customer_headers(ctx["customer"]["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_QUOTE_STATE)
    assert res.status_code == 409

    from test_helpers import get_quote
    q1_after = get_quote(q1["id"])
    assert q1_after["payment_reference"] == "pay-1", (
        "the first approval's payment_reference must be preserved")
    assert q1_after["status"] == "APPROVED"


def test_quote_approve_declined_state_beats_payment(api):
    """PRD §2.8: "Every request is checked against a fixed sequence of
    validation layers, and an earlier failure masks later ones."
    PRD §2.8: "Sixth, state-machine legality — whether the target entity is in a
    state permitting the requested transition — yielding the matching error
    among `ERR_INVALID_RMA_STATE`, `ERR_INVALID_QUOTE_STATE`, ... . Business
    rules follow, in their pinned relative order."
    PRD §2.8: "quote expiry (`ERR_QUOTE_EXPIRED`) before payment presence
    (`ERR_PAYMENT_REQUIRED`)"

    Design: Difficulty/priority_pair_validation_conflict/quote_approve_declined_state_beats_payment
    """
    ctx = setup_awaiting_quote_rma()
    q1 = ctx["quote"]
    decline_quote(q1["id"], ctx["customer"]["id"])
    # Approve the DECLINED quote without a payment_reference: the state layer
    # (sixth) fires ahead of the business-layer payment check.
    res = api.approve_quote(q1["id"], {},
                            make_customer_headers(ctx["customer"]["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_QUOTE_STATE)
    assert res.status_code == 409


def test_declined_quote_approve_leaves_state_unchanged(api):
    """PRD §3.5: "The customer may instead decline a `SENT` quote: the quote
    moves to `DECLINED` with `decided_at` pinned, the RMA moves from
    `AWAITING_QUOTE_APPROVAL` to `QUOTE_DECLINED`, a `QUOTE_DECLINED`
    notification fires, and the SLA pause remains open — the depot's clock is
    stopped while the ball is in the customer's court."

    Design: Difficulty/priority_pair_validation_conflict/quote_approve_declined_state_beats_payment
    """
    from test_helpers import get_quote
    ctx = setup_awaiting_quote_rma()
    q1 = ctx["quote"]
    decline_quote(q1["id"], ctx["customer"]["id"])

    api.approve_quote(q1["id"], {}, make_customer_headers(ctx["customer"]["id"]))
    assert get_quote(q1["id"])["status"] == "DECLINED", (
        "a rejected approve must not move the quote out of DECLINED")
    assert get_rma(ctx["rma"]["id"])["status"] == "QUOTE_DECLINED", (
        "a rejected approve must not move the RMA out of QUOTE_DECLINED")


def test_quote_approve_after_expiry_rejected(api):
    """PRD §3.5: "the logical clock must not be later than the quote's
    `expires_at` — approval at or before the expiry instant is permitted,
    approval after it is rejected with `ERR_QUOTE_EXPIRED`."
    PRD §3.5: "A quote's `sent_at` records when it became `SENT`, and its
    `expires_at` is `sent_at` extended by the model's `quote_valid_days`"

    Design: Corner/validations/quote_approve_after_expiry_rejected
    """
    ctx = setup_awaiting_quote_rma(quote_valid_days=14)
    q1 = ctx["quote"]
    # sent at 2026-08-01, expires 2026-08-15; advance past expiry (no sweep run)
    set_clock("2026-08-16T00:00:00Z")
    res = api.approve_quote(q1["id"], {"payment_reference": "pay-late"},
                            make_customer_headers(ctx["customer"]["id"]))
    validate_error(res, ApiErrorId.ERR_QUOTE_EXPIRED)
    assert res.status_code == 409
    from test_helpers import get_quote
    assert get_quote(q1["id"])["status"] == "SENT", (
        "without a daily-close sweep the quote is still SENT; expiry is evaluated on demand")


def test_quote_approve_missing_payment_rejected(api):
    """PRD §3.5: "The owning `Customer` approves a quote by presenting a
    `payment_reference`; approval without one is rejected with
    `ERR_PAYMENT_REQUIRED`."

    Design: Corner/validations/quote_approve_missing_payment_rejected
    """
    ctx = setup_awaiting_quote_rma()
    q1 = ctx["quote"]
    res = api.approve_quote(q1["id"], {},
                            make_customer_headers(ctx["customer"]["id"]))
    validate_error(res, ApiErrorId.ERR_PAYMENT_REQUIRED)
    assert res.status_code == 402
    from test_helpers import get_quote
    assert get_quote(q1["id"])["status"] == "SENT", (
        "a rejected approve must leave the quote SENT")


def test_occ_quote_revision_stale_version(api):
    """PRD §2.7: "If the supplied value does not match the RMA's current
    `version` — because another write has advanced the version since the client
    last read it — the request is rejected with `ERR_STALE_RMA_VERSION` (HTTP
    412)."
    PRD §3.5: "A `DepotTechnician` may revise the quote chain by submitting
    fresh `labor_minutes`, fresh `parts_lines`, an optional `discount_pct`, and
    an optional `expedite` flag; the request is OCC-guarded per §2.7 and must
    carry `expected_rma_version`, with stale views rejected as
    `ERR_STALE_RMA_VERSION`."

    Design: Corner/complexity_layers/occ_quote_revision_stale_version
    """
    from test_helpers import get_quote
    ctx = setup_awaiting_quote_rma()
    rma, q1 = ctx["rma"], ctx["quote"]
    decline_quote(q1["id"], ctx["customer"]["id"])
    v_now = get_rma(rma["id"])["version"]

    stale = api.create_quote_revision(
        rma["id"],
        {"labor_minutes": 50,
         "parts_lines": [planned_part_line(ctx["part"]["id"], 1)],
         "expected_rma_version": v_now - 1},
        TEST_USERS["depot_technician_headers"])
    validate_error(stale, ApiErrorId.ERR_STALE_RMA_VERSION)
    assert stale.status_code == 412

    q2 = revise_quote(rma["id"], labor_minutes=50,
                      parts_lines=[planned_part_line(ctx["part"]["id"], 1)],
                      expected_rma_version=v_now)
    assert q2["quote_seq"] == 2
    assert q2["status"] == "SENT"
    assert get_quote(q1["id"])["status"] == "SUPERSEDED"
    assert get_rma(rma["id"])["status"] == "AWAITING_QUOTE_APPROVAL"
