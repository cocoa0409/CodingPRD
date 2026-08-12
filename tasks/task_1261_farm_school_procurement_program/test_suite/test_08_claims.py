"""Reimbursement claims: line gates, OCC, adjudication auto-derivation, the
grant ledger, and the provisional/final match-credit variants."""
from test_helpers import (
    ApiErrorId,
    add_claim_line,
    api_client,
    assert_claim,
    assert_claim_line,
    assert_grant_ledger_conserved,
    assert_invoice,
    create_accepted_delivery,
    create_agreement,
    create_approved_farm,
    create_approved_invoice,
    create_claim,
    create_farm,
    create_forecast_line,
    create_invoice,
    create_kitchen,
    create_product,
    create_program_year,
    create_receiving_window,
    create_verified_offering,
    find_claim_line_for_invoice,
    get_claim,
    make_farm_manager_headers,
    setup_claim_under_review,
    setup_procurement_chain,
    sign_agreement,
    start_claim_review,
    submit_claim,
    upload_liability_insurance,
    upload_safety_cert,
    approve_farm,
    validate_error,
    validate_success,
)
from test_helpers.test_users import (
    TEST_USERS,
    make_admin_headers,
    make_claims_coordinator_headers,
)

ADMIN = TEST_USERS["admin_headers"]
AUDITOR = TEST_USERS["auditor_headers"]
CLAIMS = TEST_USERS["claims_headers"]


def _fulfill_to_accepted(chain, offering, committed, qty, date, number):
    """Agreement -> sign -> delivery -> accept -> APPROVED invoice."""
    agr = validate_success(
        create_agreement(chain.year["id"], offering["id"], committed_quantity=committed),
        201,
    )
    sign_agreement(agr["id"], chain.farm["id"])
    delivery = create_accepted_delivery(
        agr["id"], chain.kitchen["id"], chain.window["id"], chain.farm["id"], date, qty
    )
    invoice = create_approved_invoice(delivery["id"], chain.farm["id"], number)
    return agr, delivery, invoice


def _chain_10200_255():
    """One agreement (committed 200) with ACCEPTED deliveries 40 and 1 and
    APPROVED invoices worth 10200 and 255 cents."""
    chain = setup_procurement_chain(committed_quantity=200, window_capacity=5)
    del1 = create_accepted_delivery(
        chain.agreement["id"], chain.kitchen["id"], chain.window["id"],
        chain.farm["id"], "2026-08-10", 40,
    )
    del2 = create_accepted_delivery(
        chain.agreement["id"], chain.kitchen["id"], chain.window["id"],
        chain.farm["id"], "2026-08-17", 1,
    )
    inv1 = create_approved_invoice(del1["id"], chain.farm["id"], "INV-1")
    inv2 = create_approved_invoice(del2["id"], chain.farm["id"], "INV-2")
    assert inv1["total_cents"] == 10200 and inv2["total_cents"] == 255
    return chain, inv1, inv2


def _chain_153_255():
    """Two offerings (price 150 / 250), two agreements of committed 1, two
    APPROVED invoices worth 153 and 255 cents."""
    chain = setup_procurement_chain(with_agreement=False)
    off_a = create_verified_offering(
        chain.farm["id"], chain.year["id"], chain.product["id"], price_cents_per_unit=150
    )
    off_b = create_verified_offering(
        chain.farm["id"], chain.year["id"], chain.product["id"], price_cents_per_unit=250
    )
    _agr_a, _del_a, inv_a = _fulfill_to_accepted(chain, off_a, 1, 1, "2026-08-10", "INV-A")
    _agr_b, _del_b, inv_b = _fulfill_to_accepted(chain, off_b, 1, 1, "2026-08-10", "INV-B")
    assert inv_a["total_cents"] == 153 and inv_b["total_cents"] == 255
    return chain, inv_a, inv_b


def test_match_credit_provisional_then_final_post_audit(api):
    """PRD section 3.7: "The `match_provisional_cents` figure applies this
    per-line rounding to claimed amounts and refreshes as lines are added,
    while `match_final_cents` applies it to awarded amounts and remains null
    until adjudication completes."

    Design: Difficulty/dual_variant_calc/match_credit_provisional_vs_final_post_audit
    """
    _chain, inv_a, inv_b = _chain_153_255()
    claim = create_claim(_chain.year["id"], "2026-08")
    line_a = add_claim_line(claim["id"], inv_a["id"])
    line_b = add_claim_line(claim["id"], inv_b["id"])

    claim = submit_claim(claim["id"])
    claim = start_claim_review(claim["id"])
    assert claim["match_provisional_cents"] == 205, (
        "claimed basis pre-audit: 77 + 128"
    )

    # Audit: line B loses 53 cents, line A is allowed in full.
    validate_success(
        api.disallow_claim_line(
            line_b["id"],
            {"disallowed_amount_cents": 53, "reason": "documentation gap"},
            AUDITOR,
        ),
        200,
    )
    validate_success(api.allow_claim_line(line_a["id"], AUDITOR), 200)

    claim = get_claim(claim["id"])
    assert_claim(claim)
    assert claim["status"] == "PARTIALLY_AWARDED"
    # Awarded basis: 153 + (255 - 53) = 355 -> 77 + 101 = 178.
    assert claim["total_awarded_cents"] == 355
    assert claim["match_final_cents"] == 178
    assert claim["match_provisional_cents"] == 205, (
        "the provisional figure stays on the claimed basis"
    )


def test_match_credit_variants_visible_around_audit(api):
    """PRD section 3.7: "The `match_provisional_cents` figure applies this
    per-line rounding to claimed amounts and refreshes as lines are added,
    while `match_final_cents` applies it to awarded amounts and remains null
    until adjudication completes."
    PRD section 3.7: "A claim is born `OPEN` with `total_claimed_cents`,
    `total_awarded_cents`, and `match_provisional_cents` all at zero and
    `match_final_cents` still null."

    Design: Difficulty/dual_variant_calc/match_credit_provisional_vs_final_post_audit
    """
    _chain, inv_a, inv_b = _chain_153_255()
    claim = create_claim(_chain.year["id"], "2026-08")
    assert claim["match_provisional_cents"] == 0
    assert claim["match_final_cents"] is None

    line_a = add_claim_line(claim["id"], inv_a["id"])
    line_b = add_claim_line(claim["id"], inv_b["id"])

    mid = get_claim(claim["id"])
    assert mid["total_claimed_cents"] == 408
    assert mid["match_provisional_cents"] == 205
    assert mid["match_final_cents"] is None, "null until adjudication completes"

    submit_claim(claim["id"])
    start_claim_review(claim["id"])
    validate_success(
        api.disallow_claim_line(
            line_b["id"],
            {"disallowed_amount_cents": 53, "reason": "documentation gap"},
            AUDITOR,
        ),
        200,
    )
    validate_success(api.allow_claim_line(line_a["id"], AUDITOR), 200)
    done = get_claim(claim["id"])
    assert done["match_provisional_cents"] == 205
    assert done["match_final_cents"] == 178
    assert done["status"] == "PARTIALLY_AWARDED"


def test_match_per_line_rounding_two_lines(api):
    """PRD section 3.7: "each line's match is rounded half-up to a whole cent
    first, and only then are the per-line amounts summed — rounding after
    summation is not equivalent and is not permitted. Two lines claiming 153
    and 255 cents contribute 77 and 128 matched cents respectively, totaling
    205; summing first would wrongly yield 204."

    Design: Difficulty/combinatorial_formula/match_per_line_rounding_mode_b
    """
    _chain, inv_a, inv_b = _chain_153_255()
    claim = create_claim(_chain.year["id"], "2026-08")
    add_claim_line(claim["id"], inv_a["id"])
    add_claim_line(claim["id"], inv_b["id"])

    claim = get_claim(claim["id"])
    assert claim["total_claimed_cents"] == 408
    assert claim["match_provisional_cents"] == 205, (
        "per-line round-then-sum: 77 + 128 = 205, not round(408*0.5) = 204"
    )


def test_match_per_line_rounding_single_odd_cent_line(api):
    """PRD section 3.7: "Two lines claiming 153 and 255 cents contribute 77
    and 128 matched cents respectively"
    PRD section 2.7: "Wherever a computation can yield a fraction — the
    geographic incentive credit and the grant match credit — the result is
    rounded half-up to the nearest whole cent at exactly the step the business
    rule specifies, and nowhere else."

    Design: Difficulty/combinatorial_formula/match_per_line_rounding_mode_b
    """
    _chain, inv_a, _inv_b = _chain_153_255()
    claim = create_claim(_chain.year["id"], "2026-08")
    add_claim_line(claim["id"], inv_a["id"])
    claim = get_claim(claim["id"])
    # round_half_up(153 * 0.5) = 77 on the single line.
    assert claim["total_claimed_cents"] == 153
    assert claim["match_provisional_cents"] == 77


def test_claim_disallow_depth3_chain(api):
    """PRD section 3.7: "Disallowing requires the same two gates plus a
    `disallowed_amount_cents` between 1 and the line's claimed amount inclusive
    (`ERR_DISALLOWANCE_OUT_OF_RANGE`) and a `reason`, recorded on the line as
    `disallowance_reason`; it moves the line to `DISALLOWED` and awards its
    claimed amount minus the disallowed portion."
    PRD section 3.7: "in all three cases `match_final_cents` is computed on
    awarded amounts"

    Design: Difficulty/transitive_cascade/claim_disallow_depth3_cascade
    """
    chain, inv1, inv2 = _chain_10200_255()
    claim = create_claim(chain.year["id"], "2026-08")
    line1 = add_claim_line(claim["id"], inv1["id"])
    line2 = add_claim_line(claim["id"], inv2["id"])
    submit_claim(claim["id"])
    start_claim_review(claim["id"])

    validate_success(api.allow_claim_line(line1["id"], AUDITOR), 200)
    disallowed = validate_success(
        api.disallow_claim_line(
            line2["id"], {"disallowed_amount_cents": 55, "reason": "price variance"},
            AUDITOR,
        ),
        200,
    )
    assert disallowed["audit_status"] == "DISALLOWED", "link 1: the line flips"
    assert disallowed["disallowance_reason"] == "price variance"

    claim = get_claim(claim["id"])
    # link 2: totals recompute to 10200 + (255 - 55) = 10400.
    assert claim["total_awarded_cents"] == 10400
    # link 3: no PENDING lines remain, awarded > 0, not all allowed.
    assert claim["status"] == "PARTIALLY_AWARDED"
    # match_final = round(10200*0.5) + round(200*0.5) = 5100 + 100.
    assert claim["match_final_cents"] == 5200


def test_claim_disallow_intermediate_state_stays_under_review(api):
    """PRD section 3.7: "Lines still `PENDING` award nothing, so the claim's
    `total_awarded_cents` — the sum over lines of each line's awarded amount —
    grows as adjudication proceeds."
    PRD section 3.7: "When the last `PENDING` line is adjudicated, the claim
    transitions on its own"

    Design: Difficulty/transitive_cascade/claim_disallow_depth3_cascade
    """
    chain, inv1, inv2 = _chain_10200_255()
    claim = create_claim(chain.year["id"], "2026-08")
    line1 = add_claim_line(claim["id"], inv1["id"])
    line2 = add_claim_line(claim["id"], inv2["id"])
    submit_claim(claim["id"])
    start_claim_review(claim["id"])

    validate_success(api.allow_claim_line(line1["id"], AUDITOR), 200)
    mid = get_claim(claim["id"])
    assert mid["total_awarded_cents"] == 10200
    assert mid["status"] == "UNDER_REVIEW", (
        "one PENDING line remains, so the claim has not auto-transitioned yet"
    )

    validate_success(
        api.disallow_claim_line(
            line2["id"], {"disallowed_amount_cents": 55, "reason": "price variance"},
            AUDITOR,
        ),
        200,
    )
    done = get_claim(claim["id"])
    assert done["status"] == "PARTIALLY_AWARDED"
    assert done["total_awarded_cents"] == 10400
    assert done["match_final_cents"] == 5200


def test_grant_drawn_remaining_conservation_forward_and_back(api):
    """PRD section 3.1: "The `grant_drawn_cents` figure is the sum of
    `total_awarded_cents` over the year's claims currently in `RECONCILED`
    status — a claim that is later reversed no longer counts toward the draw —
    and `grant_remaining_cents` is always the award minus the drawn amount."
    PRD section 3.7: "On success the claim becomes `RECONCILED`, and the
    year's `grant_drawn_cents` rises while `grant_remaining_cents` falls by
    the awarded total."

    Design: Difficulty/compensating_invariant/grant_drawn_remaining_conservation
    """
    chain, inv1, inv2 = _chain_10200_255()
    claim = create_claim(chain.year["id"], "2026-08")
    line1 = add_claim_line(claim["id"], inv1["id"])
    line2 = add_claim_line(claim["id"], inv2["id"])
    submit_claim(claim["id"])
    start_claim_review(claim["id"])
    validate_success(api.allow_claim_line(line1["id"], AUDITOR), 200)
    validate_success(
        api.disallow_claim_line(
            line2["id"], {"disallowed_amount_cents": 55, "reason": "price variance"},
            AUDITOR,
        ),
        200,
    )

    reconciled = validate_success(api.reconcile_claim(claim["id"], AUDITOR), 200)
    assert reconciled["status"] == "RECONCILED"
    year = validate_success(api.get_program_year(chain.year["id"], AUDITOR), 200)
    assert year["grant_drawn_cents"] == 10400
    assert year["grant_remaining_cents"] == 989600
    assert_grant_ledger_conserved(year)

    reversed_claim = validate_success(api.reverse_claim(claim["id"], AUDITOR), 200)
    assert reversed_claim["status"] == "REVERSED"
    year = validate_success(api.get_program_year(chain.year["id"], AUDITOR), 200)
    assert year["grant_drawn_cents"] == 0
    assert year["grant_remaining_cents"] == 1000000
    assert_grant_ledger_conserved(year)


def test_grant_ledger_conserved_at_each_step(api):
    """PRD section 3.7: "reversing a `RECONCILED` claim
    (`ERR_CLAIM_NOT_RECONCILED` from any other state) moves it to `REVERSED`
    and restores the awarded total to the remaining balance."
    PRD section 3.1: "`grant_remaining_cents` is always the award minus the
    drawn amount."

    Design: Difficulty/compensating_invariant/grant_drawn_remaining_conservation
    """
    chain, inv1, inv2 = _chain_10200_255()
    claim = create_claim(chain.year["id"], "2026-08")
    line1 = add_claim_line(claim["id"], inv1["id"])
    line2 = add_claim_line(claim["id"], inv2["id"])
    submit_claim(claim["id"])
    start_claim_review(claim["id"])
    validate_success(api.allow_claim_line(line1["id"], AUDITOR), 200)
    validate_success(
        api.disallow_claim_line(
            line2["id"], {"disallowed_amount_cents": 55, "reason": "price variance"},
            AUDITOR,
        ),
        200,
    )

    # Before reconcile the ledger is untouched.
    year = validate_success(api.get_program_year(chain.year["id"], AUDITOR), 200)
    assert year["grant_drawn_cents"] == 0
    assert year["grant_remaining_cents"] == 1000000

    validate_success(api.reconcile_claim(claim["id"], AUDITOR), 200)
    year = validate_success(api.get_program_year(chain.year["id"], AUDITOR), 200)
    assert_grant_ledger_conserved(year)

    validate_success(api.reverse_claim(claim["id"], AUDITOR), 200)
    claim_after = get_claim(claim["id"])
    assert claim_after["status"] == "REVERSED"
    year = validate_success(api.get_program_year(chain.year["id"], AUDITOR), 200)
    assert year["grant_drawn_cents"] == 0
    assert year["grant_remaining_cents"] == 1000000


def test_claim_auto_derive_awarded_all_allowed(api):
    """PRD section 3.7: "When the last `PENDING` line is adjudicated, the claim
    transitions on its own: to `AWARDED` when every line stands in `ALLOWED`"
    PRD section 3.7: "in all three cases `match_final_cents` is computed on
    awarded amounts"

    Design: Corner/state_machines/sm_claim_compound_auto_derive_all_allowed
    """
    chain = setup_procurement_chain()
    delivery = create_accepted_delivery(
        chain.agreement["id"], chain.kitchen["id"], chain.window["id"],
        chain.farm["id"], "2026-08-10", 40,
    )
    bundle = setup_claim_under_review(chain, [(delivery, "INV-1")])
    line = bundle.lines[0]

    validate_success(api.allow_claim_line(line["id"], AUDITOR), 200)
    claim = get_claim(bundle.claim["id"])
    assert claim["status"] == "AWARDED"
    assert claim["total_awarded_cents"] == 10200
    assert claim["match_final_cents"] == 5100


def test_claim_state_family_errors(api):
    """PRD section 3.7: "A `StateGrantAuditor` then takes the claim under
    review (`SUBMITTED` → `UNDER_REVIEW`; otherwise `ERR_CLAIM_NOT_SUBMITTED`)."
    PRD section 3.7: "A `StateGrantAuditor` reconciles a claim in `AWARDED` or
    `PARTIALLY_AWARDED` (any other state draws `ERR_CLAIM_NOT_AWARDED`)"
    PRD section 3.7: "reversing a `RECONCILED` claim (`ERR_CLAIM_NOT_RECONCILED`
    from any other state)"
    PRD section 3.7: "adding to a claim in any other state fails with
    `ERR_CLAIM_NOT_OPEN`."
    PRD section 3.7: "Allowing a line requires the claim to be `UNDER_REVIEW`
    (`ERR_CLAIM_NOT_UNDER_REVIEW`) and the line still `PENDING`
    (`ERR_CLAIM_LINE_NOT_PENDING`)"
    PRD section 3.7: "plus a `disallowed_amount_cents` between 1 and the line's
    claimed amount inclusive (`ERR_DISALLOWANCE_OUT_OF_RANGE`)"

    Design: Corner/state_machines/sm_claim_state_family_errors
    """
    chain = setup_procurement_chain(committed_quantity=200, window_capacity=5)
    deliveries = [
        create_accepted_delivery(
            chain.agreement["id"], chain.kitchen["id"], chain.window["id"],
            chain.farm["id"], date, qty,
        )
        for date, qty in (("2026-08-10", 40), ("2026-08-17", 1), ("2026-08-24", 1))
    ]
    invoices = [
        create_approved_invoice(d["id"], chain.farm["id"], f"INV-{i}")
        for i, d in enumerate(deliveries, start=1)
    ]
    claim = create_claim(chain.year["id"], "2026-08")

    # From OPEN: review, reconcile, and reverse all mis-target the state.
    validate_error(api.start_claim_review(claim["id"], AUDITOR), ApiErrorId.ERR_CLAIM_NOT_SUBMITTED)
    validate_error(api.reconcile_claim(claim["id"], AUDITOR), ApiErrorId.ERR_CLAIM_NOT_AWARDED)
    validate_error(api.reverse_claim(claim["id"], AUDITOR), ApiErrorId.ERR_CLAIM_NOT_RECONCILED)

    line1 = add_claim_line(claim["id"], invoices[0]["id"])
    line2 = add_claim_line(claim["id"], invoices[1]["id"])
    submit_claim(claim["id"])

    # Line add after submit fails.
    stale = get_claim(claim["id"])
    resp = api.add_claim_line(
        claim["id"],
        {"invoice_id": invoices[2]["id"], "expected_claim_version": stale["version"]},
        CLAIMS,
    )
    validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_OPEN)

    # Adjudication before start-review fails.
    validate_error(api.allow_claim_line(line1["id"], AUDITOR), ApiErrorId.ERR_CLAIM_NOT_UNDER_REVIEW)

    start_claim_review(claim["id"])
    validate_success(api.allow_claim_line(line1["id"], AUDITOR), 200)
    # Double adjudication fails.
    validate_error(api.allow_claim_line(line1["id"], AUDITOR), ApiErrorId.ERR_CLAIM_LINE_NOT_PENDING)

    # Zero disallowance is out of range; a full disallowance is admitted.
    validate_error(
        api.disallow_claim_line(line2["id"], {"disallowed_amount_cents": 0, "reason": "x"}, AUDITOR),
        ApiErrorId.ERR_DISALLOWANCE_OUT_OF_RANGE,
    )
    validate_success(
        api.disallow_claim_line(
            line2["id"], {"disallowed_amount_cents": 255, "reason": "full denial"}, AUDITOR
        ),
        200,
    )
    claim = get_claim(claim["id"])
    assert claim["status"] == "PARTIALLY_AWARDED"
    assert claim["total_awarded_cents"] == 10200


def test_claim_empty_submit(api):
    """PRD section 3.7: "Submitting the claim (`OPEN` → `SUBMITTED`) requires
    at least one line (`ERR_CLAIM_EMPTY`)"

    Design: Corner/validations/val_claim_empty_submit
    """
    year = create_program_year()
    claim = create_claim(year["id"], "2026-08")
    resp = api.submit_claim(claim["id"], CLAIMS)
    validate_error(resp, ApiErrorId.ERR_CLAIM_EMPTY)


def test_grant_exhausted_at_reconcile(api):
    """PRD section 3.7: "provided its `total_awarded_cents` fits within the
    program year's `grant_remaining_cents` — an award beyond the remaining
    balance is rejected with `ERR_GRANT_EXHAUSTED` (HTTP 402)."

    Design: Corner/validations/val_grant_exhausted_at_reconcile
    """
    chain = setup_procurement_chain(grant_award_cents=10000)
    delivery = create_accepted_delivery(
        chain.agreement["id"], chain.kitchen["id"], chain.window["id"],
        chain.farm["id"], "2026-08-10", 40,
    )
    bundle = setup_claim_under_review(chain, [(delivery, "INV-1")])
    validate_success(api.allow_claim_line(bundle.lines[0]["id"], AUDITOR), 200)
    claim = get_claim(bundle.claim["id"])
    assert claim["status"] == "AWARDED"
    assert claim["total_awarded_cents"] == 10200

    resp = api.reconcile_claim(claim["id"], AUDITOR)
    validate_error(resp, ApiErrorId.ERR_GRANT_EXHAUSTED)

    claim = get_claim(claim["id"])
    assert claim["status"] == "AWARDED", "a refused draw leaves the claim AWARDED"
    year = validate_success(api.get_program_year(chain.year["id"], AUDITOR), 200)
    assert year["grant_drawn_cents"] == 0


def test_invoice_already_claimed_second_claim(api):
    """PRD section 3.7: "An invoice may appear on at most one claim line
    anywhere in the system (`ERR_INVOICE_ALREADY_CLAIMED`)."

    Design: Corner/validations/val_invoice_already_claimed_second_claim
    """
    chain = setup_procurement_chain()
    delivery = create_accepted_delivery(
        chain.agreement["id"], chain.kitchen["id"], chain.window["id"],
        chain.farm["id"], "2026-08-10", 40,
    )
    invoice = create_approved_invoice(delivery["id"], chain.farm["id"], "INV-1")
    claim1 = create_claim(chain.year["id"], "2026-08")
    add_claim_line(claim1["id"], invoice["id"])

    claim2 = create_claim(chain.year["id"], "2026-08")
    resp = api.add_claim_line(
        claim2["id"],
        {"invoice_id": invoice["id"], "expected_claim_version": claim2["version"]},
        CLAIMS,
    )
    validate_error(resp, ApiErrorId.ERR_INVOICE_ALREADY_CLAIMED)


def test_claim_line_outside_period(api):
    """PRD section 3.7: "The month of the invoice's delivery date must equal
    the claim's `period_month` (`ERR_INVOICE_OUTSIDE_PERIOD`)."

    Design: Corner/validations/val_claim_line_outside_period
    """
    chain = setup_procurement_chain()
    delivery = create_accepted_delivery(
        chain.agreement["id"], chain.kitchen["id"], chain.window["id"],
        chain.farm["id"], "2026-08-10", 40,
    )
    invoice = create_approved_invoice(delivery["id"], chain.farm["id"], "INV-1")

    claim = create_claim(chain.year["id"], "2026-09")
    resp = api.add_claim_line(
        claim["id"],
        {"invoice_id": invoice["id"], "expected_claim_version": claim["version"]},
        CLAIMS,
    )
    validate_error(resp, ApiErrorId.ERR_INVOICE_OUTSIDE_PERIOD)


def test_claim_line_non_local_rejected(api):
    """PRD section 3.7: "The invoice's agreement must be local-eligible, since
    only local purchases are grant-reimbursable (`ERR_LINE_NOT_LOCAL`)."
    PRD section 3.4: "At creation the agreement pins its `unit_price_cents`
    from the offering's `price_cents_per_unit` and its `local_eligible` flag
    from the offering's `is_local_eligible`"

    Design: Corner/validations/val_claim_line_non_local_rejected
    """
    chain = setup_procurement_chain(farm_distance=150)
    agreement = validate_success(
        api.get_planting_agreement(chain.agreement["id"], ADMIN), 200
    )
    assert agreement["local_eligible"] is False, "the pinned snapshot is non-local"

    delivery = create_accepted_delivery(
        chain.agreement["id"], chain.kitchen["id"], chain.window["id"],
        chain.farm["id"], "2026-08-10", 40,
    )
    invoice = create_approved_invoice(delivery["id"], chain.farm["id"], "INV-NL")
    claim = create_claim(chain.year["id"], "2026-08")
    resp = api.add_claim_line(
        claim["id"],
        {"invoice_id": invoice["id"], "expected_claim_version": claim["version"]},
        CLAIMS,
    )
    validate_error(resp, ApiErrorId.ERR_LINE_NOT_LOCAL)


def test_claim_line_farm_noncompliant_snapshot(api):
    """PRD section 3.6: "snapshots `farm_compliant_at_delivery` — the farm's
    `compliance_posture` evaluated at the delivery's `delivery_date`, kept as a
    permanent audit trail even if the farm's posture later changes."
    PRD section 3.7: "And the invoice's `farm_compliant_at_delivery` snapshot
    must be true (`ERR_LINE_FARM_NONCOMPLIANT`)."

    Design: Corner/validations/val_claim_line_farm_noncompliant_snapshot
    """
    year = create_program_year()
    product = create_product()
    farm = create_farm()
    cert = upload_safety_cert(farm["id"])
    upload_liability_insurance(farm["id"])
    approve_farm(farm["id"])
    offering = create_verified_offering(farm["id"], year["id"], product["id"])
    create_forecast_line(year["id"], product["id"])
    kitchen = create_kitchen()
    window = create_receiving_window(kitchen["id"])
    agr = validate_success(
        create_agreement(year["id"], offering["id"], committed_quantity=200), 201
    )
    sign_agreement(agr["id"], farm["id"])
    delivery = create_accepted_delivery(
        agr["id"], kitchen["id"], window["id"], farm["id"], "2026-08-10", 40
    )

    # The cert is revoked after acceptance; a revoked document no longer
    # counts, so the posture snapshot taken at invoice creation is false.
    validate_success(api.revoke_compliance_document(cert["id"], AUDITOR), 200)
    invoice = validate_success(
        create_invoice(delivery["id"], farm["id"], "INV-1"), 201
    )
    assert_invoice(invoice)
    assert invoice["farm_compliant_at_delivery"] is False

    validate_success(
        api.submit_invoice(invoice["id"], make_farm_manager_headers(farm["id"])), 200
    )
    validate_success(api.approve_invoice(invoice["id"], make_admin_headers("admin-1")), 200)

    claim = create_claim(year["id"], "2026-08")
    resp = api.add_claim_line(
        claim["id"],
        {"invoice_id": invoice["id"], "expected_claim_version": claim["version"]},
        CLAIMS,
    )
    validate_error(resp, ApiErrorId.ERR_LINE_FARM_NONCOMPLIANT)


def test_occ_claim_line_add_stale_version(api):
    """PRD section 2.9: "Adding a line to a reimbursement claim
    (`POST /f2s/reimbursement-claims/{id}/lines`) likewise requires
    `expected_claim_version`, holding the claim `version` the client last
    observed. In both cases, if the supplied value does not match the parent
    resource's current `version` — because another write has advanced the
    parent since the client read it — the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412), and the client must re-read the parent
    before retrying."

    Design: Corner/complexity_layers/layer_occ_claim_line_add_stale_version
    """
    chain, inv1, inv2 = _chain_10200_255()
    claim = create_claim(chain.year["id"], "2026-08")
    original_version = claim["version"]

    validate_success(
        api.add_claim_line(
            claim["id"],
            {"invoice_id": inv1["id"], "expected_claim_version": original_version},
            CLAIMS,
        ),
        201,
    )
    # The first add bumped the claim version: the stale value is rejected.
    resp = api.add_claim_line(
        claim["id"],
        {"invoice_id": inv2["id"], "expected_claim_version": original_version},
        CLAIMS,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    # Re-read and retry.
    fresh = get_claim(claim["id"])
    line2 = validate_success(
        api.add_claim_line(
            claim["id"],
            {"invoice_id": inv2["id"], "expected_claim_version": fresh["version"]},
            CLAIMS,
        ),
        201,
    )
    assert_claim_line(line2)
    assert line2["invoice_id"] == inv2["id"]
