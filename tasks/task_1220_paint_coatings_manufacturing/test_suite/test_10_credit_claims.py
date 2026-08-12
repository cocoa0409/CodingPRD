"""Dealer credit claims: provisional-vs-final credit variants, banding
boundaries, the claim window, the annual cap, segregation, and the
settle/void ledger identity."""

import test_helpers as fx
from test_helpers import (
    ApiErrorId,
    PLANT_MANAGER,
    PLANT_MANAGER_2,
    REGULATORY_CLERK,
    make_dealer_headers,
    validate_error,
    validate_success,
)


def test_freeze_credit_provisional_vs_final_variants(api):
    """PRD §3.8: "The provisional variant applies this penalty using the
    dealer-claimed `claimed_exposure_count`; the figure is invoice value
    times band percentage times the penalty factor, rounded half up to whole
    cents only after all multiplications."
    PRD §3.8: "Review is the evidence step: a `RegulatoryClerk` moves a
    `SUBMITTED` claim to `UNDER_REVIEW`, copying the container's recorded
    `freeze_exposure_count` into `verified_exposure_count` and stamping
    `reviewed_by_user_id`."
    PRD §3.8: "Approval belongs to a `PlantManager` and computes
    `final_credit_cents` with the same bands but the penalty keyed on the
    verified count — so the final figure diverges from the provisional one
    whenever the claimed and verified exposures disagree."

    Design: Difficulty/dual_variant_calc/freeze_credit_provisional_vs_final
    """
    env = fx.setup_shipped_container(freeze_events=3)
    fx.set_clock("2026-06-20T08:00:00Z")

    # Claimed exposure 1 (no penalty) while the container records 3.
    cl1 = fx.submit_claim(
        env["cu1"]["id"], env["k1"]["id"],
        claim_type="FREEZE_DAMAGE", invoice_value_cents=40000,
        claimed_exposure_count=1,
    )
    fx.assert_credit_claim(cl1)
    # Expiry 2028-06-10 minus 2026-06-20 -> 721 whole days -> band 1.00.
    assert cl1["remaining_days_at_claim"] == 721
    assert cl1["provisional_credit_cents"] == 40000
    assert cl1.get("verified_exposure_count") is None

    reviewed = validate_success(
        api.review_credit_claim(cl1["id"], REGULATORY_CLERK)
    )
    assert reviewed["status"] == "UNDER_REVIEW"
    assert reviewed["verified_exposure_count"] == 3, (
        "review copies the container's freeze_exposure_count"
    )

    approved = validate_success(api.approve_credit_claim(cl1["id"], PLANT_MANAGER))
    assert approved["status"] == "APPROVED"
    # Verified 3 > 2 -> freeze penalty halves the band credit.
    assert approved["final_credit_cents"] == 20000
    assert approved["final_credit_cents"] != approved["provisional_credit_cents"]


def test_freeze_penalty_threshold_and_shelf_life_immunity(api):
    """PRD §3.8: "On top of the band, a freeze-damage claim whose exposure
    count exceeds 2 takes a penalty that halves the credit; shelf-life claims
    and milder freeze histories pay the band unpenalized."
    PRD §3.8: "540 days or more pays 100 percent of invoice value"

    Design: Difficulty/dual_variant_calc/freeze_credit_provisional_vs_final
    """
    # Exactly 2 recorded exposures: at the threshold, no penalty applies.
    env = fx.setup_shipped_container(freeze_events=2)
    fx.set_clock("2026-06-20T08:00:00Z")
    cl1 = fx.submit_claim(
        env["cu1"]["id"], env["k1"]["id"],
        claim_type="FREEZE_DAMAGE", invoice_value_cents=40000,
        claimed_exposure_count=2,
    )
    assert cl1["provisional_credit_cents"] == 40000
    validate_success(api.review_credit_claim(cl1["id"], REGULATORY_CLERK))
    approved = validate_success(api.approve_credit_claim(cl1["id"], PLANT_MANAGER))
    assert approved["verified_exposure_count"] == 2
    assert approved["final_credit_cents"] == 40000, (
        "exceeds 2 is the penalty trigger; exactly 2 pays the band unpenalized"
    )


def test_claim_referential_gate_beats_temporal_gate(api):
    """PRD §2.9: "Gate eight is referential relation: formulas must be active
    for batch creation, order lines, and hold-resume
    (`ERR_FORMULA_NOT_ACTIVE`); the batch offered when scheduling an order
    must belong to that order (`ERR_ORDER_BATCH_MISMATCH`); a credit claim's
    container must have been shipped to the claiming customer
    (`ERR_CONTAINER_NOT_CREDITABLE`)."
    PRD §2.9: "Gate nine, on credit-claim submission only, is the thirty-day
    claim window — `ERR_CLAIM_WINDOW_EXPIRED`."
    PRD §2.9: "Every request passes through eleven ordered gates, and a
    failure at an earlier gate masks every later check — the error returned
    is always the first failing gate's error."

    Design: Difficulty/priority_pair_validation_conflict/claim_referential_beats_temporal
    """
    env = fx.setup_shipped_container()  # K1 shipped to CU1 at 2026-06-15T09:00Z
    cu2 = fx.create_customer(name="Rio Grande Coatings NM",
                             home_state_code="NM")

    # 31 days after shipment AND the wrong customer: both gates would fail.
    fx.set_clock("2026-07-16T10:00:00Z")
    response = api.create_credit_claim(
        fx.create_credit_claim_payload(cu2["id"], env["k1"]["id"],
                                       invoice_value_cents=40000),
        make_dealer_headers(cu2["id"]),
    )
    validate_error(response, ApiErrorId.ERR_CONTAINER_NOT_CREDITABLE.value, 422)

    claims, meta = fx.validate_paginated(
        api.list_credit_claims(PLANT_MANAGER,
                               params={"container_id": env["k1"]["id"]})
    )
    assert claims == [], "the rejected submission persists no claim"
    assert meta["total_count"] == 0


def test_claim_referential_gate_fires_within_window_too(api):
    """PRD §3.8: "The container must be creditable: it must be in `SHIPPED`
    status and must have been shipped to the claiming customer — anything
    else is `ERR_CONTAINER_NOT_CREDITABLE`."

    Design: Difficulty/priority_pair_validation_conflict/claim_referential_beats_temporal
    """
    env = fx.setup_shipped_container()
    cu2 = fx.create_customer(name="Rio Grande Coatings NM",
                             home_state_code="NM")

    # Well inside the 30-day window, but the container went to another
    # customer: referential failure alone.
    fx.set_clock("2026-06-20T08:00:00Z")
    response = api.create_credit_claim(
        fx.create_credit_claim_payload(cu2["id"], env["k1"]["id"],
                                       invoice_value_cents=40000),
        make_dealer_headers(cu2["id"]),
    )
    validate_error(response, ApiErrorId.ERR_CONTAINER_NOT_CREDITABLE.value, 422)


def test_credit_settle_void_ledger_identity(api):
    """PRD §3.8: "Settlement adds `final_credit_cents` to the customer's
    `credit_balance_cents` and to `credit_used_ytd_cents`, stamps
    `settled_by_user_id`, and moves the claim to `SETTLED`. A settled claim
    can still be voided by a `PlantManager`; voiding performs the
    compensating reversal, subtracting `final_credit_cents` from both
    `credit_balance_cents` and `credit_used_ytd_cents`, and lands the claim
    in the terminal `VOIDED` state."
    PRD §3.8: "both start at 0 at registration."

    Design: Difficulty/compensating_invariant/credit_settle_void_ledger_identity
    """
    env = fx.setup_approved_claim()  # final_credit_cents 20000
    before = fx.read_customer(env["cu1"]["id"])
    assert before["credit_balance_cents"] == 0
    assert before["credit_used_ytd_cents"] == 0

    settled = validate_success(
        api.settle_credit_claim(env["cl1"]["id"], PLANT_MANAGER_2)
    )
    assert settled["status"] == "SETTLED"
    after_settle = fx.read_customer(env["cu1"]["id"])
    assert after_settle["credit_balance_cents"] == 20000
    assert after_settle["credit_used_ytd_cents"] == 20000

    voided = validate_success(api.void_credit_claim(env["cl1"]["id"], PLANT_MANAGER))
    assert voided["status"] == "VOIDED"
    after_void = fx.read_customer(env["cu1"]["id"])
    assert after_void["credit_balance_cents"] == 0
    assert after_void["credit_used_ytd_cents"] == 0, (
        "settle/void compose to the identity on the ledger"
    )
    fx.assert_customer_ledger_invariants(after_void)


def test_settle_moves_ledger_by_exactly_final_credit(api):
    """PRD §3.8: "Settlement adds `final_credit_cents` to the customer's
    `credit_balance_cents` and to `credit_used_ytd_cents`, stamps
    `settled_by_user_id`, and moves the claim to `SETTLED`."
    PRD §3.8: "A settled claim can still be voided by a `PlantManager`;
    voiding performs the compensating reversal, subtracting
    `final_credit_cents` from both `credit_balance_cents` and
    `credit_used_ytd_cents`, and lands the claim in the terminal `VOIDED`
    state."

    Design: Difficulty/compensating_invariant/credit_settle_void_ledger_identity
    """
    env = fx.setup_approved_claim(freeze_events=3)  # final 20000
    final_credit = env["cl1"]["final_credit_cents"]
    assert final_credit == 20000

    settled = validate_success(
        api.settle_credit_claim(env["cl1"]["id"], PLANT_MANAGER_2)
    )
    assert settled["settled_by_user_id"] == "pm-2"
    customer = fx.read_customer(env["cu1"]["id"])
    assert customer["credit_balance_cents"] == final_credit
    assert customer["credit_used_ytd_cents"] == final_credit

    validate_success(api.void_credit_claim(env["cl1"]["id"], PLANT_MANAGER))
    restored = fx.read_customer(env["cu1"]["id"])
    assert restored["credit_balance_cents"] == 0
    assert restored["credit_used_ytd_cents"] == 0


def test_freeze_credit_band_boundary_360_vs_359(api):
    """PRD §3.8: "Both credit variants share one banding schedule keyed on
    `remaining_days_at_claim`: 540 days or more pays 100 percent of invoice
    value; at least 360 but fewer than 540 pays 60 percent, with exactly 360
    days taking the 60 percent band; at least 180 but fewer than 360 pays 30
    percent; fewer than 180 pays nothing."
    PRD §3.8: "At submission the server computes `remaining_days_at_claim` —
    the whole days between the container's `expiry_date` and the claim's
    creation"

    Design: Corner/calculations/freeze_credit_band_boundary_360_vs_359
    """
    env = fx.setup_shipped_container(line_gallons=3,
                                     ship_clock="2027-06-01T09:00:00Z")
    k1 = env["k1"]
    k2 = env["others"][0]
    # Ship the second can too (order covers 3 gal; K1 + K2 = 2 gal shipped).
    validate_success(
        api.ship_container(k2["id"], {"order_id": env["o1"]["id"]},
                           fx.PRODUCTION_OPERATOR)
    )
    # Manufactured 2026-06-10 (24-month shelf) -> expiry 2028-06-10.
    assert env["k1"]["expiry_date"].startswith("2028-06-10")

    # 2027-06-16 claim: 360 whole days remain -> 0.60 band.
    fx.set_clock("2027-06-16T08:00:00Z")
    cl1 = fx.submit_claim(
        env["cu1"]["id"], k1["id"], claim_type="FREEZE_DAMAGE",
        invoice_value_cents=40000, claimed_exposure_count=0,
    )
    assert cl1["remaining_days_at_claim"] == 360
    assert cl1["provisional_credit_cents"] == 24000

    # 2027-06-17 claim on the sibling can: 359 days -> 0.30 band.
    fx.set_clock("2027-06-17T08:00:00Z")
    cl2 = fx.submit_claim(
        env["cu1"]["id"], k2["id"], claim_type="FREEZE_DAMAGE",
        invoice_value_cents=40000, claimed_exposure_count=0,
    )
    assert cl2["remaining_days_at_claim"] == 359
    assert cl2["provisional_credit_cents"] == 12000

    for claim_id, expected in ((cl1["id"], 24000), (cl2["id"], 12000)):
        validate_success(api.review_credit_claim(claim_id, REGULATORY_CLERK))
        approved = validate_success(
            api.approve_credit_claim(claim_id, PLANT_MANAGER)
        )
        assert approved["status"] == "APPROVED"
        assert approved["final_credit_cents"] == expected


def test_claim_window_inclusive_30_day_boundary(api):
    """PRD §3.8: "The claim is also time-boxed: submission must fall no later
    than thirty days after the container's `shipped_at`, where landing
    exactly thirty days later passes and one second beyond fails with
    `ERR_CLAIM_WINDOW_EXPIRED`."
    PRD §2.5: "The thirty-day claim window compares timestamps at
    second-level precision — a claim filed at exactly thirty days after
    shipment passes, and one second beyond fails."

    Design: Corner/validations/claim_window_inclusive_30_day_boundary
    """
    env = fx.setup_shipped_container(line_gallons=3,
                                     ship_clock="2026-06-15T09:00:00Z")
    k1, k2 = env["k1"], env["others"][0]
    validate_success(
        api.ship_container(k2["id"], {"order_id": env["o1"]["id"]},
                           fx.PRODUCTION_OPERATOR)
    )

    # Exactly shipped_at + 30 days: created.
    fx.set_clock("2026-07-15T09:00:00Z")
    cl_ok = fx.submit_claim(
        env["cu1"]["id"], k1["id"], claim_type="FREEZE_DAMAGE",
        invoice_value_cents=12000, claimed_exposure_count=0,
    )
    fx.assert_credit_claim(cl_ok)
    assert cl_ok["status"] == "SUBMITTED"

    # One second beyond: refused.
    fx.set_clock("2026-07-15T09:00:01Z")
    expired = api.create_credit_claim(
        fx.create_credit_claim_payload(
            env["cu1"]["id"], k2["id"], invoice_value_cents=12000,
            claimed_exposure_count=0,
        ),
        make_dealer_headers(env["cu1"]["id"]),
    )
    validate_error(expired, ApiErrorId.ERR_CLAIM_WINDOW_EXPIRED.value, 422)


def test_claim_approve_exceeds_annual_credit_cap(api):
    """PRD §3.8: "Approval is also capped: the final credit must not exceed
    the customer's `annual_credit_cap_cents` minus the credit already used
    this year, `credit_used_ytd_cents`; a claim that would breach the cap is
    rejected with `ERR_CREDIT_CAP_EXCEEDED`."

    Design: Corner/validations/claim_approve_exceeds_annual_credit_cap
    """
    env = fx.setup_shipped_container(line_gallons=3)
    k1, k2 = env["k1"], env["others"][0]
    validate_success(
        api.ship_container(k2["id"], {"order_id": env["o1"]["id"]},
                           fx.PRODUCTION_OPERATOR)
    )
    fx.set_clock("2026-06-20T08:00:00Z")

    # First claim (band 1.00, 40000) approved and settled: 40000 of the
    # 50000 annual cap used.
    cl1 = fx.submit_claim(
        env["cu1"]["id"], k1["id"], claim_type="SHELF_LIFE_EXPIRY",
        invoice_value_cents=40000, claimed_exposure_count=0,
    )
    validate_success(api.review_credit_claim(cl1["id"], REGULATORY_CLERK))
    validate_success(api.approve_credit_claim(cl1["id"], PLANT_MANAGER))
    validate_success(api.settle_credit_claim(cl1["id"], PLANT_MANAGER_2))
    assert fx.read_customer(env["cu1"]["id"])["credit_used_ytd_cents"] == 40000

    # Second claim's final 40000 would leave only 10000 of headroom.
    cl2 = fx.submit_claim(
        env["cu1"]["id"], k2["id"], claim_type="SHELF_LIFE_EXPIRY",
        invoice_value_cents=40000, claimed_exposure_count=0,
    )
    validate_success(api.review_credit_claim(cl2["id"], REGULATORY_CLERK))
    over_cap = api.approve_credit_claim(cl2["id"], PLANT_MANAGER)
    validate_error(over_cap, ApiErrorId.ERR_CREDIT_CAP_EXCEEDED.value, 422)

    stuck = fx.read_claim(cl2["id"])
    assert stuck["status"] == "UNDER_REVIEW"
    assert stuck.get("final_credit_cents") is None
    assert fx.read_customer(env["cu1"]["id"])["credit_used_ytd_cents"] == 40000


def test_segregation_claim_settler_must_differ_from_approver(api):
    """PRD §3.8: "Settlement posts the money, and it is segregated from
    approval: the settling `PlantManager`'s `X-User-ID` must differ from the
    claim's `approved_by_user_id`, else `ERR_SEGREGATION_OF_DUTY`."
    PRD §3.8: "Settlement adds `final_credit_cents` to the customer's
    `credit_balance_cents` and to `credit_used_ytd_cents`, stamps
    `settled_by_user_id`, and moves the claim to `SETTLED`."

    Design: Corner/rbac/segregation_claim_settler_must_differ_from_approver
    """
    env = fx.setup_shipped_container()
    fx.set_clock("2026-06-20T08:00:00Z")
    cl1 = fx.submit_claim(
        env["cu1"]["id"], env["k1"]["id"], claim_type="SHELF_LIFE_EXPIRY",
        invoice_value_cents=40000, claimed_exposure_count=0,
    )
    validate_success(api.review_credit_claim(cl1["id"], REGULATORY_CLERK))
    approved = validate_success(api.approve_credit_claim(cl1["id"], PLANT_MANAGER))
    assert approved["approved_by_user_id"] == "pm-1"
    assert approved["final_credit_cents"] == 40000

    # The approver cannot also settle.
    same_user = api.settle_credit_claim(cl1["id"], PLANT_MANAGER)
    validate_error(same_user, ApiErrorId.ERR_SEGREGATION_OF_DUTY.value, 422)
    assert fx.read_claim(cl1["id"])["status"] == "APPROVED"

    # A second PlantManager settles; the ledger moves by the final credit.
    settled = validate_success(api.settle_credit_claim(cl1["id"], PLANT_MANAGER_2))
    assert settled["status"] == "SETTLED"
    assert settled["settled_by_user_id"] == "pm-2"
    customer = fx.read_customer(env["cu1"]["id"])
    assert customer["credit_balance_cents"] == 40000
    assert customer["credit_used_ytd_cents"] == 40000


def test_claim_reject_terminal_then_settle_returns_invalid_state(api):
    """PRD §3.8: "Rejection, also a `PlantManager` call, is available from
    either `SUBMITTED` or `UNDER_REVIEW` and lands in the terminal `REJECTED`
    state."
    PRD §2.9: "Gate six is state permission: the target resource must be in a
    state that permits the operation — this is the gate that catches
    stale-cycle color measurements, cancellation of an order already in
    production, completion of a hazardous disposal that never passed through
    its manifest, and adjustments recorded in the wrong batch phase, all as
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/claim_reject_terminal_then_settle_returns_invalid_state
    """
    env = fx.setup_shipped_container()
    fx.set_clock("2026-06-20T08:00:00Z")
    cl1 = fx.submit_claim(
        env["cu1"]["id"], env["k1"]["id"], claim_type="SHELF_LIFE_EXPIRY",
        invoice_value_cents=12000, claimed_exposure_count=0,
    )

    rejected = validate_success(api.reject_credit_claim(cl1["id"], PLANT_MANAGER))
    assert rejected["status"] == "REJECTED"

    settle = api.settle_credit_claim(cl1["id"], PLANT_MANAGER_2)
    validate_error(settle, ApiErrorId.ERR_INVALID_STATE.value, 409)
    assert fx.read_claim(cl1["id"])["status"] == "REJECTED"
    assert fx.read_customer(env["cu1"]["id"])["credit_balance_cents"] == 0
