"""Warranty claims: coverage windows and boundaries, the appeal loop and its
cap, duplicate-claim detection, subject claimability, and decision guards."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, api_client,
    set_clock, create_customer, create_manager,
    setup_delivered_spec, setup_picked_up_ticket, setup_quoted_spec,
    approve_spec, mark_ready,
    customer_headers, staff_headers, create_warranty_claim_payload,
)


def _file_claim_on_spec(spec_id, customer):
    return api_client.create_warranty_claim(
        create_warranty_claim_payload("head rattling", build_spec_id=spec_id),
        customer_headers(customer),
    )


def _file_claim_on_ticket(ticket_id, customer, description="grip slipping"):
    return api_client.create_warranty_claim(
        create_warranty_claim_payload(description, repair_ticket_id=ticket_id),
        customer_headers(customer),
    )


def test_warranty_exactly_90_days_full_coverage(api):
    """PRD §3.7: "For a build spec, coverage is one hundred percent when the
    age is at most 90 days" and "Boundaries are inclusive: exactly 90 days
    yields full coverage on a spec, and exactly 30 days yields full coverage
    on a ticket."

    Design: Difficulty/boundary_precision_check/warranty_exactly_90_days_full_coverage
    """
    ctx = setup_delivered_spec(deliver_clock="2026-05-10T12:00:00Z")
    set_clock("2026-08-08T12:00:00Z")  # exactly 90 days after delivery
    resp = _file_claim_on_spec(ctx["spec"]["id"], ctx["customer"])
    claim = validate_success(resp, expected_status=201)
    assert claim["coverage_pct"] == 100, (
        f"age 90 days is the inclusive full-coverage boundary, got {claim['coverage_pct']}"
    )
    # round_half_up(2300 * 100 / 100) = 2300.
    assert claim["covered_estimate_cents"] == 2_300, (
        f"expected covered estimate 2300, got {claim['covered_estimate_cents']}"
    )


def test_warranty_90_day_claim_subject_price(api):
    """PRD §3.7: "`covered_estimate_cents` is the subject's price —
    `final_price_cents` for a spec, `quoted_total_cents` for a ticket —
    multiplied by the coverage percentage and divided by one hundred, rounded
    half-up." PRD §3.4: "stamping `delivered_at` from the logical clock as the
    warranty anchor".

    Design: Difficulty/boundary_precision_check/warranty_exactly_90_days_full_coverage
    """
    ctx = setup_delivered_spec(deliver_clock="2026-05-10T12:00:00Z")
    spec = ctx["spec"]
    # 8800 unit-cost sum (no tier) + 1000 labor - 7500 rebate = 2300.
    assert spec["final_price_cents"] == 2_300, (
        f"expected final price 2300, got {spec['final_price_cents']}"
    )
    assert spec["delivered_at"] is not None

    set_clock("2026-08-09T12:00:00Z")  # 91 days: one day past full coverage
    resp = _file_claim_on_spec(spec["id"], ctx["customer"])
    claim = validate_success(resp, expected_status=201)
    assert claim["coverage_pct"] == 50, (
        f"age 91 days must fall to the 50% band, got {claim['coverage_pct']}"
    )
    assert claim["covered_estimate_cents"] == 1_150


def test_warranty_partial_coverage_fifty_pct_band(api):
    """PRD §3.7: "fifty percent when the age is at most 365 days" and
    "`covered_estimate_cents` is the subject's price — `final_price_cents`
    for a spec, `quoted_total_cents` for a ticket — multiplied by the coverage
    percentage and divided by one hundred, rounded half-up."

    Design: Corner/calculations/warranty_partial_coverage_fifty_pct_band
    """
    ctx = setup_delivered_spec(deliver_clock="2026-05-10T12:00:00Z")
    set_clock("2026-11-26T12:00:00Z")  # 200 days after delivery
    resp = _file_claim_on_spec(ctx["spec"]["id"], ctx["customer"])
    claim = validate_success(resp, expected_status=201)
    assert claim["coverage_pct"] == 50, (
        f"age 200 days lands in the 91..365 band, got {claim['coverage_pct']}"
    )
    # round_half_up(2300 * 50 / 100) = 1150.
    assert claim["covered_estimate_cents"] == 1_150, (
        f"expected covered estimate 1150, got {claim['covered_estimate_cents']}"
    )


def _setup_denied_claim():
    ctx = setup_picked_up_ticket()
    claim = validate_success(
        _file_claim_on_ticket(ctx["ticket"]["id"], ctx["customer"]),
        expected_status=201,
    )
    manager = create_manager()
    claim = get_success_data(
        api_client.decide_claim(claim["id"],
                                {"decision": "DENIED", "denial_reason": "wear and tear"},
                                staff_headers(manager))
    )
    ctx["claim"] = claim
    ctx["manager"] = manager
    return ctx


def test_warranty_appeal_cycle_and_limit(api):
    """PRD §3.7: "the owning customer may appeal a `DENIED` claim — appealing
    from any other state earns `ERR_CLAIM_NOT_DENIED` — which returns it to
    `SUBMITTED`, increments `appeal_count` by one, and clears the recorded
    `denial_reason`. The appeal loop is hard-capped: appealing when
    `appeal_count` has already reached 2 is rejected with
    `ERR_APPEAL_LIMIT_REACHED` (HTTP 422)."

    Design: Corner/state_machines/warranty_appeal_cycle_and_limit
    """
    ctx = _setup_denied_claim()
    ch = customer_headers(ctx["customer"])
    mh = staff_headers(ctx["manager"])
    claim_id = ctx["claim"]["id"]

    claim = get_success_data(api_client.appeal_claim(claim_id, ch))
    assert claim["status"] == "SUBMITTED" and claim["appeal_count"] == 1
    assert claim["denial_reason"] is None, "appeal clears the recorded denial_reason"

    claim = get_success_data(
        api_client.decide_claim(claim_id, {"decision": "DENIED", "denial_reason": "still wear"}, mh)
    )
    claim = get_success_data(api_client.appeal_claim(claim_id, ch))
    assert claim["status"] == "SUBMITTED" and claim["appeal_count"] == 2

    claim = get_success_data(
        api_client.decide_claim(claim_id, {"decision": "DENIED", "denial_reason": "final"}, mh)
    )
    resp = api_client.appeal_claim(claim_id, ch)
    validate_error(resp, ApiErrorId.ERR_APPEAL_LIMIT_REACHED)
    claim = get_success_data(api_client.get_warranty_claim(claim_id, mh))
    assert claim["status"] == "DENIED"


def test_duplicate_open_claim_rejected(api):
    """PRD §3.7: "the subject must not already carry an open claim: if a claim
    in `SUBMITTED` or `APPROVED` exists for the same subject, the new filing
    is rejected with `ERR_DUPLICATE_CLAIM` (HTTP 409)."

    Design: Corner/validations/duplicate_open_claim_rejected
    """
    ctx = setup_picked_up_ticket()
    first = validate_success(
        _file_claim_on_ticket(ctx["ticket"]["id"], ctx["customer"], "first"),
        expected_status=201,
    )
    assert first["status"] == "SUBMITTED"
    resp = _file_claim_on_ticket(ctx["ticket"]["id"], ctx["customer"], "second")
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_CLAIM)


def test_claim_on_undelivered_spec_rejected(api):
    """PRD §3.7: "The subject must be claimable — the spec in `DELIVERED` or
    the ticket in `PICKED_UP` — or the filing is rejected with
    `ERR_SUBJECT_NOT_CLAIMABLE` (HTTP 409)."

    Design: Corner/validations/claim_on_undelivered_spec_rejected
    """
    ctx = setup_quoted_spec(
        complete_session=True, labor_cents=1_000,
        trio_overrides={
            "head_stock": 1, "shaft_stock": 1, "grip_stock": 1,
            "head_unit": 5_000, "head_msrp": 7_000,
            "shaft_unit": 3_000, "shaft_msrp": 4_000,
            "grip_unit": 800, "grip_msrp": 1_000,
        },
    )
    spec = approve_spec(ctx["spec"], ctx["customer"])
    spec = mark_ready(spec, ctx["technician"])
    assert spec["status"] == "READY", "spec is READY, not DELIVERED"
    resp = _file_claim_on_spec(spec["id"], ctx["customer"])
    validate_error(resp, ApiErrorId.ERR_SUBJECT_NOT_CLAIMABLE)


def test_ticket_claim_window_expired_rejected(api):
    """PRD §3.7: "For a repair ticket, coverage is one hundred percent when
    the age is at most 30 days and nothing beyond — an older ticket earns the
    same `ERR_CLAIM_WINDOW_EXPIRED`."

    Design: Corner/validations/ticket_claim_window_expired_rejected
    """
    ctx = setup_picked_up_ticket()  # picked up at 2026-05-10T09:00:00Z
    set_clock("2026-06-10T09:00:00Z")  # 31 days later
    resp = _file_claim_on_ticket(ctx["ticket"]["id"], ctx["customer"], "too late")
    validate_error(resp, ApiErrorId.ERR_CLAIM_WINDOW_EXPIRED)


def test_decide_twice_rejected(api):
    """PRD §3.7: "A `ShopManager` decides — a decision attempted on a claim
    not in `SUBMITTED` earns `ERR_CLAIM_NOT_SUBMITTED`."

    Design: Corner/validations/decide_twice_rejected
    """
    ctx = setup_picked_up_ticket()
    claim = validate_success(
        _file_claim_on_ticket(ctx["ticket"]["id"], ctx["customer"], "loose ferrule"),
        expected_status=201,
    )
    manager = create_manager()
    mh = staff_headers(manager)
    claim = get_success_data(
        api_client.decide_claim(claim["id"], {"decision": "APPROVED"}, mh)
    )
    assert claim["status"] == "APPROVED"
    resp = api_client.decide_claim(
        claim["id"], {"decision": "DENIED", "denial_reason": "changed mind"}, mh
    )
    validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_SUBMITTED)
    claim = get_success_data(api_client.get_warranty_claim(claim["id"], mh))
    assert claim["status"] == "APPROVED"
