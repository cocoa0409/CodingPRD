"""Rejection-order conflicts: a state gate that outranks the fiscal gate, and a
registration-eligibility gate that outranks the evidence-mismatch gate."""

from test_helpers import (
    ANALYST,
    ApiErrorId,
    assert_cents,
    assert_sweep_counts,
    create_claim,
    create_listing,
    create_takedown,
    fill_and_seal_package,
    read_brand,
    read_claim,
    read_listing,
    run_sweep,
    screen_listing,
    set_clock,
    setup_claim,
    setup_substantiated_claim,
    substantiate_claim,
    test_buy_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_dismissed_claim_reports_invalid_state_and_never_reaches_the_budget_gate(api):
    """PRD §2.9: "Ordering a test buy against a dismissed claim for a brand whose spend already exhausts its budget returns `ERR_INVALID_STATE` with HTTP 409, not the budget error — state precedes every business rule and the fiscal gate is never reached."
    PRD §2.9: "**Priority 20** — the target row is in a state from which the requested transition exists, including the cross-entity state gates spelled out in §3 (the claim must be substantiated before a notice is filed, the package must be sealed before it is attached, a test buy must be received before it is authenticated, an investigation must have evidence submitted before it may be confirmed as diversion, and the litigation track must be untouched for a no-action closure); else `ERR_INVALID_STATE` (409)."
    PRD §2.9: "**Priority 80** — the brand's enforcement budget can absorb the order, else `ERR_TEST_BUY_BUDGET_EXCEEDED` (402). Applies to ordering a test buy. Fiscal checks run last, after every state and safety gate."
    PRD §2.9: "Evaluation stops there and nothing is persisted — not even a value the server had already computed."

    Design: Difficulty/priority_pair_validation_conflict/dismissed_claim_state_error_outranks_exhausted_budget_on_test_buy
    """
    ctx = setup_claim(api, clock="2026-08-05T08:00:00Z",
                      brand={"enforcement_budget_cents": 5000})
    dismissed = validate_success(
        api.dismiss_claim(ctx["claim"]["id"], "ANALYST_WITHDRAWN", headers=ANALYST), 200)
    assert dismissed["status"] == "DISMISSED", f"got {dismissed['status']}"
    assert dismissed["dismissal_reason_code"] == "ANALYST_WITHDRAWN"

    # A billable total of 5635 cents would also overrun the brand's 5000-cent budget.
    refused = api.create_test_buy(
        ctx["claim"]["id"], test_buy_payload(4200, 700, 0), headers=ANALYST)
    validate_error(refused, ApiErrorId.INVALID_STATE, 409)

    rows, _meta = validate_paginated(
        api.list_test_buys(headers=ANALYST, claim_id=ctx["claim"]["id"]))
    assert rows == [], f"Nothing is persisted by a refused order, got {rows}"
    assert_cents(read_brand(api, ctx["brand"]["id"])["enforcement_spend_cents"], 0,
                 "enforcement_spend_cents")


def test_the_budget_gate_does_fire_once_the_claim_state_is_sound(api):
    """PRD §2.9: "**Priority 80** — the brand's enforcement budget can absorb the order, else `ERR_TEST_BUY_BUDGET_EXCEEDED` (402). Applies to ordering a test buy. Fiscal checks run last, after every state and safety gate."
    PRD §3.6: "If it would, the order is refused with `ERR_TEST_BUY_BUDGET_EXCEEDED` (HTTP 402) and nothing is persisted."
    PRD §3.6: "This fiscal gate is the very last check in the rejection ladder, so an order that is also invalid for a state or safety reason reports that reason instead."
    PRD §3.6: "Otherwise `billable_total_cents` is added to the brand's `enforcement_spend_cents` and the brand's `version` is incremented by 1."

    Design: Difficulty/priority_pair_validation_conflict/dismissed_claim_state_error_outranks_exhausted_budget_on_test_buy
    """
    ctx = setup_claim(api, clock="2026-08-05T08:00:00Z",
                      brand={"enforcement_budget_cents": 5000})
    assert read_claim(api, ctx["claim"]["id"])["status"] == "DRAFT"

    refused = api.create_test_buy(
        ctx["claim"]["id"], test_buy_payload(4200, 700, 0), headers=ANALYST)
    validate_error(refused, ApiErrorId.TEST_BUY_BUDGET_EXCEEDED, 402)

    rows, _meta = validate_paginated(
        api.list_test_buys(headers=ANALYST, claim_id=ctx["claim"]["id"]))
    assert rows == [], f"A refused order persists nothing, got {rows}"
    assert_cents(read_brand(api, ctx["brand"]["id"])["enforcement_spend_cents"], 0,
                 "enforcement_spend_cents")

    # The same order fits inside a subtotal that keeps the billable total at 5000 or below.
    affordable = validate_success(api.create_test_buy(
        ctx["claim"]["id"], test_buy_payload(4000, 0, 0), headers=ANALYST), 201)
    assert_cents(affordable["billable_total_cents"], 4600, "billable_total_cents")
    assert_cents(read_brand(api, ctx["brand"]["id"])["enforcement_spend_cents"], 4600,
                 "enforcement_spend_cents")


def test_lapsed_registration_outranks_the_package_claim_mismatch(api):
    """PRD §2.9: "Drafting a takedown notice that both asserts a lapsed registration and attaches another claim's package returns `ERR_REGISTRATION_NOT_ELIGIBLE` with HTTP 422, not the mismatch error — asserting a dead trademark is the graver defect and its gate sits earlier."
    PRD §2.9: "**Priority 45** — the asserted trademark registration is enforceable, meaning its status is `REGISTERED` rather than `PENDING` or `LAPSED`, and, for enrolment activation, its `nice_class` matches the requested class; else `ERR_REGISTRATION_NOT_ELIGIBLE` (422)."
    PRD §2.9: "**Priority 60** — the evidence package belongs to the same claim as the notice, and on a refiling differs from the package already attached; else `ERR_EVIDENCE_PACKAGE_MISMATCH` (422). Applies to two operations: drafting a takedown notice and refiling one."
    PRD §3.8: "When a single draft request violates both, the registration gate is the one reported."

    Design: Difficulty/priority_pair_validation_conflict/lapsed_registration_safety_error_outranks_package_claim_mismatch
    """
    ctx = setup_substantiated_claim(api, clock="2026-08-05T09:00:00Z",
                                    registration={"expiry_date": "2026-08-31"})
    other_listing = create_listing(api, ctx["brand"]["id"], ctx["seller"]["id"], price_cents=0)
    other_listing = screen_listing(api, other_listing["id"], 1.00, 1.00)
    other_claim = create_claim(api, ctx["brand"]["id"], other_listing["id"],
                              ctx["registration"]["id"])
    other_claim = substantiate_claim(api, other_claim["id"])
    other_package = fill_and_seal_package(api, other_claim["id"], tag="other")

    set_clock(api, "2026-09-01T09:00:00Z")
    sweep = run_sweep(api)
    assert_sweep_counts(sweep, lapsed_registration_count=1, suspended_enrollment_count=1)

    refused = api.create_takedown(
        {"enrollment_id": ctx["enrollment"]["id"], "claim_id": ctx["claim"]["id"],
         "evidence_package_id": other_package["id"]}, headers=ANALYST)
    validate_error(refused, ApiErrorId.REGISTRATION_NOT_ELIGIBLE, 422)

    rows, _meta = validate_paginated(
        api.list_takedowns(headers=ANALYST, claim_id=ctx["claim"]["id"]))
    assert rows == [], f"A refused draft persists no notice, got {rows}"


def test_the_mismatch_gate_is_reported_only_while_the_registration_is_enforceable(api):
    """PRD §3.8: "Two gates apply at draft time. The registration asserted by the claim must be enforceable — `REGISTERED` rather than `PENDING` or `LAPSED` — else `ERR_REGISTRATION_NOT_ELIGIBLE` (HTTP 422). And the supplied evidence package must belong to the same claim as the notice, else `ERR_EVIDENCE_PACKAGE_MISMATCH` (HTTP 422)."
    PRD §3.11: "Step 1 — lapse registrations. Every `REGISTERED` trademark registration whose `expiry_date` has passed moves to `LAPSED`."
    PRD §2.9: "The ladder is normative and complete; a later gate is never reached when an earlier one has already fired."

    Design: Difficulty/priority_pair_validation_conflict/lapsed_registration_safety_error_outranks_package_claim_mismatch
    """
    ctx = setup_substantiated_claim(api, clock="2026-08-05T09:00:00Z",
                                    registration={"expiry_date": "2026-08-31"})
    own_package = fill_and_seal_package(api, ctx["claim"]["id"], tag="own")
    other_listing = create_listing(api, ctx["brand"]["id"], ctx["seller"]["id"], price_cents=0)
    other_listing = screen_listing(api, other_listing["id"], 1.00, 1.00)
    other_claim = create_claim(api, ctx["brand"]["id"], other_listing["id"],
                              ctx["registration"]["id"])
    other_claim = substantiate_claim(api, other_claim["id"])
    other_package = fill_and_seal_package(api, other_claim["id"], tag="other")

    # While the registration is still REGISTERED, the mismatch gate is the one reached.
    mismatch = api.create_takedown(
        {"enrollment_id": ctx["enrollment"]["id"], "claim_id": ctx["claim"]["id"],
         "evidence_package_id": other_package["id"]}, headers=ANALYST)
    validate_error(mismatch, ApiErrorId.EVIDENCE_PACKAGE_MISMATCH, 422)

    drafted = create_takedown(api, ctx["enrollment"]["id"], ctx["claim"]["id"],
                              own_package["id"])
    assert drafted["status"] == "DRAFT", f"got {drafted['status']}"
    assert drafted["round_number"] == 0, (
        f"A drafted notice has filed no round yet, got {drafted['round_number']}")

    set_clock(api, "2026-09-01T09:00:00Z")
    run_sweep(api)

    # With the registration lapsed, even a correctly matched package is refused.
    now_ineligible = api.create_takedown(
        {"enrollment_id": ctx["enrollment"]["id"], "claim_id": ctx["claim"]["id"],
         "evidence_package_id": own_package["id"]}, headers=ANALYST)
    validate_error(now_ineligible, ApiErrorId.REGISTRATION_NOT_ELIGIBLE, 422)
    assert read_listing(api, ctx["listing"]["id"])["enforcement_status"] == "CLAIM_OPEN"
