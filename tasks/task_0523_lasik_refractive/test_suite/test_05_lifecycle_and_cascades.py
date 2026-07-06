"""Cancellation cascade, installment threshold bubble-up, conserved-quantity
invariants, fiscal/referential validations, and the enhancement window boundary.

Translates queue-A difficulty instances under transitive_cascade and
compensating_invariant, plus queue-B fiscal/referential corner instances and the
enhancement-window boundary difficulty instance.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, TEST_USERS, ApiErrorId,
    make_patient_headers,
)
from test_helpers import fixtures as fx

COORD = TEST_USERS["coordinator_headers"]


# ---------------------------------------------------------------------------
# transitive_cascade
# ---------------------------------------------------------------------------
def test_cancel_cascade_releases_and_refunds(api):
    """PRD §3.7: "the case's `clinical_status` becomes `CANCELLED`; every active
    suite booking of the case is released, moving each to `RELEASED`; every
    signed consent form of the case is revoked, moving each to `REVOKED`; and if
    an open financing plan exists it is set to `CANCELLED`, after which the case's
    financial axis is set to `REFUNDED` only if it was `PAID_IN_FULL` and is
    otherwise left unchanged."

    Design: Difficulty/transitive_cascade/cancel_case_cascade_to_financing_and_financial_status
    """
    ctx = fx.setup_scheduled_case(pay_in_full=True)
    case_id = ctx["case"]["id"]
    cancelled = validate_success(api.cancel_case(
        case_id, {"expected_case_version": ctx["case"]["version"]}, COORD,
    ))
    assert cancelled["clinical_status"] == "CANCELLED"
    assert cancelled["financial_status"] == "REFUNDED"
    # Booking released.
    bookings, _ = validate_paginated(api.list_case_bookings(case_id, COORD))
    assert all(b["status"] == "RELEASED" for b in bookings)
    # PRD §3.7: only an *open* financing plan is set to CANCELLED. This case was
    # PAID_IN_FULL, so its plan is already SETTLED (not open) and stays SETTLED;
    # the financial axis is what flips to REFUNDED (asserted above).
    plan = validate_success(api.get_financing(ctx["plan"]["id"], COORD))
    assert plan["status"] == "SETTLED"


def test_cancel_cascade_revokes_signed_consent(api):
    """PRD §3.7: "every signed consent form of the case is revoked, moving each
    to `REVOKED`".
    PRD §3.7: "the case's `clinical_status` becomes `CANCELLED`".

    Design: Difficulty/transitive_cascade/cancel_case_cascade_to_financing_and_financial_status
    """
    ctx = fx.setup_consented_case(pay_in_full=True)
    case_id = ctx["case"]["id"]
    cancelled = validate_success(api.cancel_case(
        case_id, {"expected_case_version": ctx["case"]["version"]}, COORD,
    ))
    assert cancelled["clinical_status"] == "CANCELLED"
    consents, _ = validate_paginated(api.list_case_consent(case_id, COORD))
    assert consents, "expected at least one consent form on the case"
    assert all(c["status"] == "REVOKED" for c in consents)


def test_installment_threshold_bubbles_up_to_paid_in_full(api):
    """PRD §3.4: "Once the running `amount_settled_cents` reaches or exceeds the
    package's `base_price_cents`, the plan flips to `SETTLED` and, bubbling up,
    the case's financial status moves to `PAID_IN_FULL`."

    Design: Difficulty/transitive_cascade/installment_threshold_cascade_to_paid_in_full
    """
    cfg = fx.setup_config()
    case, _ = fx.create_planned_case(cfg["package"]["id"], cfg["optometrist"]["id"], cfg["surgeon"]["id"])
    plan = fx.fund_case_deposit(case["id"], 100000, term_months=12, apr_bps=0)
    updated = validate_success(api.post_installment(
        plan["id"], {"amount_cents": 400000}, COORD,
    ), expected_status=201)
    assert updated["amount_settled_cents"] == 500000
    assert updated["status"] == "SETTLED"
    assert validate_success(api.get_case(case["id"], COORD))["financial_status"] == "PAID_IN_FULL"


def test_installment_settles_plan_and_case(api):
    """PRD §3.4: "Posting an **installment** against an open plan supplies an
    `amount_cents` value that is added to the plan's `amount_settled_cents`."
    PRD §3.4: "Once the running `amount_settled_cents` reaches or exceeds the
    package's `base_price_cents`, the plan flips to `SETTLED` and, bubbling up,
    the case's financial status moves to `PAID_IN_FULL`."

    Design: Difficulty/transitive_cascade/installment_threshold_cascade_to_paid_in_full
    """
    cfg = fx.setup_config()
    case, _ = fx.create_planned_case(cfg["package"]["id"], cfg["optometrist"]["id"], cfg["surgeon"]["id"])
    plan = fx.fund_case_deposit(case["id"], 100000, term_months=12, apr_bps=0)
    validate_success(api.post_installment(plan["id"], {"amount_cents": 400000}, COORD),
                     expected_status=201)
    settled_plan = validate_success(api.get_financing(plan["id"], COORD))
    assert settled_plan["status"] == "SETTLED"


# ---------------------------------------------------------------------------
# compensating_invariant
# ---------------------------------------------------------------------------
def test_cancel_restores_active_booking_count_to_zero(api):
    """PRD §3.5: "A successful booking is created with status `ACTIVE`".
    PRD §3.7: "every active suite booking of the case is released, moving each to
    `RELEASED`".

    Design: Difficulty/compensating_invariant/cancel_restores_active_booking_count_to_zero
    """
    ctx = fx.setup_scheduled_case(pay_in_full=False, down_payment_cents=100000)
    case_id = ctx["case"]["id"]
    before, _ = validate_paginated(api.list_case_bookings(case_id, COORD))
    assert len([b for b in before if b["status"] == "ACTIVE"]) == 1
    validate_success(api.cancel_case(case_id, {"expected_case_version": ctx["case"]["version"]}, COORD))
    after, _ = validate_paginated(api.list_case_bookings(case_id, COORD))
    assert len(after) == 1
    assert len([b for b in after if b["status"] == "ACTIVE"]) == 0
    assert all(b["status"] == "RELEASED" for b in after)


def test_refund_pro_rata_retains_exactly_deposit(api):
    """PRD §3.9: "Under `PRO_RATA`, the payout is the settled amount minus the
    package's non-refundable `deposit_cents`, floored at zero so it is never
    negative."

    Design: Difficulty/compensating_invariant/refund_pro_rata_conserves_retained_deposit
    """
    ctx = fx.setup_healed_with_pending_refund()  # base 500000, deposit 50000, PRO_RATA
    plan = validate_success(api.get_financing(ctx["plan"]["id"], COORD))
    paid = validate_success(api.adjudicate_refund_claim(ctx["claim"]["id"], {"decision": "PAY"}, COORD))
    assert paid["refund_amount_cents"] == 450000
    retained = plan["amount_settled_cents"] - paid["refund_amount_cents"]
    assert retained == 50000
    assert retained == ctx["package"]["deposit_cents"]


def test_cancel_from_planned_releases_no_bookings_but_cancels(api):
    """PRD §3.7: "A `Coordinator` may cancel a case while its clinical status is
    `PLANNED`, `SCHEDULED`, or `CONSENTED`".
    PRD §3.5: "A successful booking is created with status `ACTIVE`".

    Design: Difficulty/compensating_invariant/cancel_restores_active_booking_count_to_zero
    """
    # A PLANNED case that was never booked has zero ACTIVE bookings before and
    # after cancel — the conserved count stays at 0.
    cfg = fx.setup_config()
    case, _ = fx.create_planned_case(cfg["package"]["id"], cfg["optometrist"]["id"], cfg["surgeon"]["id"])
    before, _ = validate_paginated(api.list_case_bookings(case["id"], COORD))
    assert len([b for b in before if b["status"] == "ACTIVE"]) == 0
    validate_success(api.cancel_case(case["id"], {"expected_case_version": case["version"]}, COORD))
    after, _ = validate_paginated(api.list_case_bookings(case["id"], COORD))
    assert len([b for b in after if b["status"] == "ACTIVE"]) == 0


def test_refund_pro_rata_flips_case_to_refunded(api):
    """PRD §3.9: "On a successful pay decision the payout is computed and stored
    in `refund_amount_cents`, the claim moves to `PAID`, and the origin case's
    financial status is set to `REFUNDED`."

    Design: Difficulty/compensating_invariant/refund_pro_rata_conserves_retained_deposit
    """
    ctx = fx.setup_healed_with_pending_refund()  # base 500000, deposit 50000, PRO_RATA
    paid = validate_success(api.adjudicate_refund_claim(ctx["claim"]["id"], {"decision": "PAY"}, COORD))
    assert paid["status"] == "PAID"
    assert paid["refund_amount_cents"] == 450000
    case = validate_success(api.get_case(ctx["case"]["id"], COORD))
    assert case["financial_status"] == "REFUNDED"


# ---------------------------------------------------------------------------
# boundary_precision_check (enhancement window)
# ---------------------------------------------------------------------------
def test_enhancement_at_exact_window_deadline_expired(api):
    """PRD §3.8: "compute the eligibility deadline as the origin case's
    `surgery_completed_at` plus the origin package's `enhancement_window_days`,
    and set `within_window` to true only when the current logical-clock instant
    is strictly before that deadline. The boundary is exclusive — an instant
    exactly equal to the deadline is already expired. A request created outside
    the window is refused with `ERR_ENHANCEMENT_WINDOW_EXPIRED` (HTTP 422)".

    Design: Difficulty/boundary_precision_check/enhancement_window_at_exact_deadline_expired
    """
    # surgery_completed_at is stamped at operate_clock 2026-06-01T12:00:00Z;
    # a 365-day window => deadline exactly 2027-06-01T12:00:00Z.
    ctx = fx.setup_healed_case(
        pay_in_full=True, operate_clock="2026-06-01T12:00:00Z",
        heal_clock="2026-07-02T00:00:00Z",
    )
    fx.set_clock("2027-06-01T12:00:00Z")  # exactly the deadline -> expired
    resp = api.create_enhancement({
        "origin_case_id": ctx["case"]["id"], "patient_id": ctx["patient"]["id"],
        "reason": "regression",
    }, make_patient_headers(ctx["patient"]["id"]))
    validate_error(resp, ApiErrorId.ERR_ENHANCEMENT_WINDOW_EXPIRED)


def test_enhancement_just_before_deadline_within_window(api):
    """PRD §3.8: "set `within_window` to true only when the current logical-clock
    instant is strictly before that deadline. The boundary is exclusive — an
    instant exactly equal to the deadline is already expired."
    PRD §3.8: "A new request begins in `REQUESTED` status with `re_screening_id`
    null."

    Design: Difficulty/boundary_precision_check/enhancement_window_at_exact_deadline_expired
    """
    # surgery_completed_at 2026-06-01T12:00:00Z, 365-day window => deadline
    # 2027-06-01T12:00:00Z. One second earlier is strictly before the deadline.
    ctx = fx.setup_healed_case(
        pay_in_full=True, operate_clock="2026-06-01T12:00:00Z",
        heal_clock="2026-07-02T00:00:00Z",
    )
    fx.set_clock("2027-06-01T11:59:59Z")
    enh = validate_success(api.create_enhancement({
        "origin_case_id": ctx["case"]["id"], "patient_id": ctx["patient"]["id"],
        "reason": "regression",
    }, make_patient_headers(ctx["patient"]["id"])), expected_status=201)
    assert enh["within_window"] is True
    assert enh["status"] == "REQUESTED"


# ---------------------------------------------------------------------------
# queue-B referential / fiscal / constraint corner instances
# ---------------------------------------------------------------------------
def test_create_case_with_unapproved_screening_rejected(api):
    """PRD §3.3: "The referenced screening must be an `APPROVED`
    `CandidacyScreening` that belongs to the same patient; otherwise the case is
    refused with `ERR_SCREENING_NOT_APPROVED` (HTTP 422)."

    Design: Corner/validations/create_case_screening_not_approved
    """
    pkg = fx.create_package()
    od = fx.create_optometrist()
    pat = fx.create_patient()
    scr = fx.create_submitted_screening(od["id"], pat["id"])  # SUBMITTED, not APPROVED
    resp = api.create_case({
        "patient_id": pat["id"], "screening_id": scr["id"], "package_id": pkg["id"],
    }, COORD)
    validate_error(resp, ApiErrorId.ERR_SCREENING_NOT_APPROVED)


def test_consent_drops_not_started_rejected(api):
    """PRD §3.6: "The attestation must be affirmative — if `drops_regimen_started`
    is not true, the signature is refused with `ERR_DROPS_NOT_STARTED`
    (HTTP 422)".

    Design: Corner/validations/consent_drops_not_started
    """
    ctx = fx.setup_scheduled_case(pay_in_full=True)
    resp = api.create_consent(ctx["case"]["id"], {
        "drops_regimen_started": False, "signed_by_patient_id": ctx["patient"]["id"],
    }, make_patient_headers(ctx["patient"]["id"]))
    validate_error(resp, ApiErrorId.ERR_DROPS_NOT_STARTED)


def test_financing_deposit_too_low_rejected(api):
    """PRD §3.4: "The down payment must cover at least the package deposit; a down
    payment below `deposit_cents` is rejected with `ERR_DEPOSIT_TOO_LOW`
    (HTTP 422)."

    Design: Corner/validations/financing_deposit_too_low
    """
    cfg = fx.setup_config()  # deposit 50000
    case, _ = fx.create_planned_case(cfg["package"]["id"], cfg["optometrist"]["id"], cfg["surgeon"]["id"])
    resp = api.create_financing(case["id"], {
        "down_payment_cents": 40000, "term_months": 12, "apr_bps": 0,
    }, COORD)
    validate_error(resp, ApiErrorId.ERR_DEPOSIT_TOO_LOW)


def test_refund_claim_guarantee_not_met_rejected(api):
    """PRD §3.9: "The claim is admissible only when the case is `HEALED` and
    actually missed its guarantee — that is, the case's `final_uncorrected_va` is
    strictly worse than (less than) the package's
    `outcome_guarantee_uncorrected_va`; if the measured acuity met or exceeded
    the guarantee, the claim is refused with `ERR_GUARANTEE_NOT_MET` (HTTP 422)."

    Design: Corner/validations/refund_claim_guarantee_not_met
    """
    # final VA 1.0 == guarantee 1.0 -> not strictly worse -> guarantee met.
    ctx = fx.setup_healed_case(pay_in_full=True, final_uncorrected_va=1.0)
    resp = api.create_refund_claim({"case_id": ctx["case"]["id"]}, COORD)
    validate_error(resp, ApiErrorId.ERR_GUARANTEE_NOT_MET)
