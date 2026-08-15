"""Warranty claims (segregation of duties, credit tiers, reopen cap) and
customer return authorizations (restocking tiers, 30-day window)."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    create_customer, create_part, create_unit, create_aog_request,
    create_quote, make_quote_line, issue_quote, accept_quote_and_get_order,
    allocate_all_lines, clear_order_compliance, create_shipment_payload,
    setup_issued_quote, setup_delivered_order, setup_delivered_multi_line_order,
    create_warranty_claim_payload, create_return_authorization_payload,
    make_customer_headers, make_adjuster_headers, make_approver_headers,
    set_clock, TEST_USERS,
)

AGENT = TEST_USERS["aog_desk_agent_headers"]
WAREHOUSE = TEST_USERS["warehouse_operator_headers"]
FINANCE = TEST_USERS["finance_controller_headers"]


def _delivered_outright(name, list_price=20_000, warranty_months=12):
    return setup_delivered_order(
        sale_type="OUTRIGHT", customer_name=name,
        part_overrides={"list_price_cents": list_price,
                        "warranty_months": warranty_months},
        line_overrides={"unit_price_cents": list_price},
    )


def _file_and_review(api, ctx, adjuster_id, fault_category="DOA",
                     description="fault"):
    claim = validate_success(api.create_warranty_claim(
        create_warranty_claim_payload(
            ctx["customer"]["id"], ctx["lines"][0]["id"],
            fault_category=fault_category, description=description,
        ),
        make_customer_headers(ctx["customer"]["id"]),
    ), 201)
    reviewed = validate_success(api.review_warranty_claim(
        claim["id"], {"review_notes": "verified"}, make_adjuster_headers(adjuster_id),
    ))
    return claim["id"], reviewed


def test_warranty_segregation_of_duties(api):
    """PRD §3.8: "The decision then belongs to a `WarrantyApprover` who must
    not be the reviewer — the same operator id attempting approval or
    rejection is `ERR_SEGREGATION_OF_DUTIES`." Approval: "the claim flows
    `UNDER_REVIEW` → `APPROVED` → `CREDIT_ISSUED` in the one request" and "a
    `WARRANTY_CREDIT` posts with balance recompute". Coverage: "`coverage_pct`
    is one hundred percent at six months or fewer".

    Claim approved at month 0 on a line_total of 20000 credits the full 20000.

    Design: Corner/state_machines/warranty_segregation_of_duties
    """
    ctx = _delivered_outright("WarrAir")
    set_clock("2026-05-15T00:00:00Z")
    claim_id, _ = _file_and_review(api, ctx, "adjuster-7")

    same_user = api.approve_warranty_claim(
        claim_id, make_approver_headers("adjuster-7"),
    )
    validate_error(same_user, "ERR_SEGREGATION_OF_DUTIES", expected_status=403)

    approved = validate_success(api.approve_warranty_claim(
        claim_id, make_approver_headers("approver-2"),
    ))
    assert approved["status"] == "CREDIT_ISSUED"
    assert approved["credit_cents"] == 20_000

    ledger, meta = validate_paginated(
        api.list_ledger_entries(ctx["customer"]["id"], FINANCE)
    )
    assert any(
        e["entry_type"] == "WARRANTY_CREDIT" and e["amount_cents"] == 20_000
        for e in ledger
    )


def test_warranty_reopen_once_then_locked(api):
    """PRD §3.8: "A rejected claim gets exactly one second look: an adjuster
    may reopen it to `UNDER_REVIEW`, incrementing `reopen_count` and
    re-stamping `reviewed_by`, but only while `reopen_count` is still zero —
    a second reopen is refused with `ERR_REOPEN_LIMIT_REACHED`."

    Design: Corner/state_machines/warranty_reopen_once_then_locked
    """
    ctx = _delivered_outright("ReopenAir")
    claim_id, _ = _file_and_review(api, ctx, "adjuster-1",
                                   fault_category="COSMETIC",
                                   description="paint scratch")
    validate_success(api.reject_warranty_claim(
        claim_id, {"fraud_flag": False}, make_approver_headers("approver-1"),
    ))

    reopened = validate_success(api.review_warranty_claim(
        claim_id, {"review_notes": "new evidence"}, make_adjuster_headers("adjuster-2"),
    ))
    assert reopened["status"] == "UNDER_REVIEW"
    assert reopened["reopen_count"] == 1

    validate_success(api.reject_warranty_claim(
        claim_id, {"fraud_flag": False}, make_approver_headers("approver-1"),
    ))
    second = api.review_warranty_claim(
        claim_id, {}, make_adjuster_headers("adjuster-1"),
    )
    validate_error(second, "ERR_REOPEN_LIMIT_REACHED", expected_status=409)


def test_warranty_credit_month_tiers(api):
    """PRD §3.8: "Approval recomputes the claim's coverage fraction
    `coverage_pct` from the calendar at the approval instant: months in
    service is the whole 30-day months from delivery to approval, and
    `coverage_pct` is one hundred percent at six months or fewer, seventy-five
    percent for months seven through twelve, fifty percent for months thirteen
    through twenty-four, and zero beyond twenty-four. The `credit_cents` is
    the line's `line_total_cents` times the coverage fraction, rounded
    half-up".

    Claim A approved at month 0 credits 20000; claim B at 240 days (8 whole
    months) credits 15000 on the identical 20000 line.

    Design: Corner/calculations/warranty_credit_month_tiers
    """
    ctx = setup_delivered_multi_line_order(
        num_lines=2, line_total_each=20_000, customer_name="TierWarr",
        warranty_months=24,
    )
    ln1, ln2 = ctx["lines"][0]["id"], ctx["lines"][1]["id"]

    claim_a = validate_success(api.create_warranty_claim(
        create_warranty_claim_payload(ctx["customer"]["id"], ln1,
                                      fault_category="DOA", description="dead"),
        make_customer_headers(ctx["customer"]["id"]),
    ), 201)
    validate_success(api.review_warranty_claim(
        claim_a["id"], {}, make_adjuster_headers("adj-1"),
    ))
    approved_a = validate_success(api.approve_warranty_claim(
        claim_a["id"], make_approver_headers("app-1"),
    ))
    assert approved_a["months_in_service"] == 0
    assert approved_a["credit_cents"] == 20_000

    set_clock("2026-12-27T00:00:00Z")
    claim_b = validate_success(api.create_warranty_claim(
        create_warranty_claim_payload(ctx["customer"]["id"], ln2,
                                      fault_category="PREMATURE_FAILURE",
                                      description="failed early"),
        make_customer_headers(ctx["customer"]["id"]),
    ), 201)
    validate_success(api.review_warranty_claim(
        claim_b["id"], {}, make_adjuster_headers("adj-1"),
    ))
    approved_b = validate_success(api.approve_warranty_claim(
        claim_b["id"], make_approver_headers("app-2"),
    ))
    assert approved_b["months_in_service"] == 8
    assert approved_b["coverage_pct"] == pytest.approx(0.75)
    assert approved_b["credit_cents"] == 15_000

    ledger, meta = validate_paginated(
        api.list_ledger_entries(ctx["customer"]["id"], FINANCE)
    )
    credits = sorted(
        e["amount_cents"] for e in ledger if e["entry_type"] == "WARRANTY_CREDIT"
    )
    assert credits == [15_000, 20_000]


def test_warranty_window_elapsed_at_boundary(api):
    """PRD §3.8: "Filing must land strictly before the warranty horizon — the
    line's `delivered_at` plus the part's `warranty_months` 30-day months;
    filing at or after that instant is `ERR_WARRANTY_PERIOD_ELAPSED`."

    Delivered 2026-05-01T00:00:00Z with warranty_months 12 -> horizon is
    exactly 2027-04-26T00:00:00Z (360 days); filing at that instant fails.

    Design: Corner/errors/warranty_window_elapsed_at_boundary
    """
    ctx = _delivered_outright("ElapAir")
    set_clock("2027-04-26T00:00:00Z")
    res = api.create_warranty_claim(
        create_warranty_claim_payload(
            ctx["customer"]["id"], ctx["lines"][0]["id"],
            fault_category="PREMATURE_FAILURE", description="too late",
        ),
        make_customer_headers(ctx["customer"]["id"]),
    )
    validate_error(res, "ERR_WARRANTY_PERIOD_ELAPSED", expected_status=422)


class TestRestockingFeeDayTiersAndWindow:
    def test_day_ten_fee_and_day_thirty_window_edge(self, api):
        """PRD §3.8: "the `restock_fee_cents` is ten percent of the line total
        when the return arrives within seven days of delivery or twenty
        percent when it arrives on days eight through thirty — rounded half-up
        either way — and `credit_cents` is the line total minus the fee; a
        `RESTOCK_CREDIT` posts with balance recompute, and the returned unit
        passes through `UNDER_INSPECTION` back to `AVAILABLE`." Also: "it is
        approved automatically as long as the request lands within 30 days of
        the line's delivery".

        Day 10 receipt: fee 4000, credit 16000 on a 20000 line. A filing at
        exactly day 30 is still inside the window.

        Design: Corner/calculations/restocking_fee_day_tiers_and_window
        """
        ctx = setup_delivered_multi_line_order(
            num_lines=2, line_total_each=20_000, customer_name="RetAir",
        )
        ln1, ln2 = ctx["lines"][0]["id"], ctx["lines"][1]["id"]

        set_clock("2026-05-11T00:00:00Z")
        rma1 = validate_success(api.create_return_authorization(
            create_return_authorization_payload(
                ctx["customer"]["id"], ln1, reason="ordered wrong part",
            ),
            make_customer_headers(ctx["customer"]["id"]),
        ), 201)
        received = validate_success(api.receive_return_authorization(
            rma1["id"], {"condition_grade": "RESALEABLE"}, WAREHOUSE,
        ))
        assert received["restock_fee_cents"] == 4_000
        assert received["credit_cents"] == 16_000
        assert received["status"] == "SETTLED"
        unit = validate_success(
            api.get_inventory_unit(ctx["units"][0]["id"], AGENT)
        )
        assert unit["status"] == "AVAILABLE"

        set_clock("2026-05-31T00:00:00Z")
        rma2 = validate_success(api.create_return_authorization(
            create_return_authorization_payload(
                ctx["customer"]["id"], ln2, reason="day 30 edge",
            ),
            make_customer_headers(ctx["customer"]["id"]),
        ), 201)
        assert rma2["status"] == "APPROVED"
        assert rma2["days_since_delivery"] == 30

    def test_day_thirty_one_filing_is_closed(self, api):
        """PRD §3.8: "it is approved automatically as long as the request
        lands within 30 days of the line's delivery — later filings are
        `ERR_RETURN_WINDOW_CLOSED`".

        Design: Corner/calculations/restocking_fee_day_tiers_and_window
        """
        ctx = setup_delivered_multi_line_order(
            num_lines=1, line_total_each=20_000, customer_name="LateRet",
        )
        set_clock("2026-06-01T00:00:00Z")
        res = api.create_return_authorization(
            create_return_authorization_payload(
                ctx["customer"]["id"], ctx["lines"][0]["id"],
                reason="day 31",
            ),
            make_customer_headers(ctx["customer"]["id"]),
        )
        validate_error(res, "ERR_RETURN_WINDOW_CLOSED", expected_status=422)


def test_rma_rejected_before_delivery(api):
    """PRD §3.8: "lines that are not `OUTRIGHT` or have no `delivered_at` yet
    are `ERR_INVALID_REQUEST`".

    Design: Corner/endpoints/rma_rejected_before_delivery
    """
    ctx = setup_issued_quote(
        customer_name="EarlyRet",
        part_overrides={"part_number": "PN-ER", "list_price_cents": 20_000},
        aog_overrides={"aircraft_tail": "N9ER"},
        line_overrides={"unit_price_cents": 20_000},
        with_unit=True, source_search=True,
    )
    accept_quote_and_get_order(ctx)
    allocate_all_lines(ctx, unit_ids=[ctx["unit"]["id"]])

    res = api.create_return_authorization(
        create_return_authorization_payload(
            ctx["customer"]["id"], ctx["lines"][0]["id"], reason="too early",
        ),
        make_customer_headers(ctx["customer"]["id"]),
    )
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)
