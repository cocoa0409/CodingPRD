"""Permit issuance, tiered/dual-variant fees, payment, revocation, slots, and revenue."""
from test_helpers import (
    validate_success, validate_error, NON_EXISTENT_UUID, ApiErrorId,
    make_planner_headers, make_applicant_headers,
    create_parcel, create_applicant, create_submitted_application,
    create_approved_application, create_issued_permit, create_active_permit,
    setup_partial_area_variance_approved, issue_permit, review_application,
    pay_permit, revoke_permit,
)


# ── Dual-variant fee: provisional (requested) vs final (approved) — Difficulty ─
def test_provisional_fee_computed_from_requested_area(api):
    """PRD §3.4: "The **base** is chosen by sign type: 15000 cents for a `WALL` sign,
    25000 cents for a `MONUMENT`, and 50000 cents for a `DIGITAL` sign."
    PRD §3.4: "The first 68 billable square feet — that is, area from 32 up to the
    tier-one cap of 100 square feet — are charged at 200 cents per square foot, and any
    area above 100 square feet is charged at 350 cents per square foot; the sum of these
    two pieces is rounded half up to whole cents to give the area fee."
    PRD §3.4: "The provisional fee computed at submission (`provisional_fee_cents`) uses
    this identical formula over the requested sign type, `requested_area_sqft`, and
    `requested_illumination`".

    Design: Difficulty/dual_variant_calc/permit_fee_provisional_vs_final
    """
    parcel, applicant, app = setup_partial_area_variance_approved(api)
    fetched = validate_success(api.get_application(app["id"], make_planner_headers()))
    assert fetched["provisional_fee_cents"] == 61100


def test_final_fee_computed_from_approved_area(api):
    """PRD §3.4: "the final fee uses `approved_type`, `approved_area_sqft`, and
    `approved_illumination`, so a partially granted AREA variance that reduced
    `approved_area_sqft` below the requested area makes the final charge diverge below
    the provisional estimate."

    Design: Difficulty/dual_variant_calc/permit_fee_provisional_vs_final
    """
    parcel, applicant, app = setup_partial_area_variance_approved(api)
    permit = issue_permit(api, app["id"], app["version"])
    assert permit["fee_charged_cents"] == 43600


# ── Combinatorial tiered fee: straddling both area tiers — Difficulty ─────────
def test_digital_straddle_fee_at_issuance(api):
    """PRD §3.4: "The first 68 billable square feet — that is, area from 32 up to the
    tier-one cap of 100 square feet — are charged at 200 cents per square foot, and any
    area above 100 square feet is charged at 350 cents per square foot; the sum of these
    two pieces is rounded half up to whole cents to give the area fee."
    PRD §3.4: "The **illumination surcharge** adds 0 cents for `NONE`, 5000 cents for
    `EXTERNAL`, and 20000 cents for `DIGITAL_DISPLAY`."

    Design: Difficulty/combinatorial_formula/permit_fee_tiered_nonlinear_straddle
    """
    parcel = create_parcel(api, max_sign_area_sqft=200, allowed_illumination="DIGITAL_DISPLAY")
    _, _, _, permit = create_issued_permit(
        api, parcel, None, sign_type="DIGITAL", requested_area_sqft=150,
        requested_height_ft=30, requested_setback_ft=12, requested_illumination="DIGITAL_DISPLAY")
    assert permit["fee_charged_cents"] == 101100


def test_digital_straddle_fee_persisted_on_read(api):
    """PRD §3.4: "The **base** is chosen by sign type: 15000 cents for a `WALL` sign,
    25000 cents for a `MONUMENT`, and 50000 cents for a `DIGITAL` sign."
    PRD §3.4: "any area above 100 square feet is charged at 350 cents per square foot;
    the sum of these two pieces is rounded half up to whole cents to give the area fee."

    Design: Difficulty/combinatorial_formula/permit_fee_tiered_nonlinear_straddle
    """
    parcel = create_parcel(api, max_sign_area_sqft=200, allowed_illumination="DIGITAL_DISPLAY")
    _, _, _, permit = create_issued_permit(
        api, parcel, None, sign_type="DIGITAL", requested_area_sqft=150,
        requested_height_ft=30, requested_setback_ft=12, requested_illumination="DIGITAL_DISPLAY")
    fetched = validate_success(api.get_permit(permit["id"], make_planner_headers()))
    assert fetched["fee_charged_cents"] == 101100


# ── Priority: state (6) beats fiscal (11) on pay — Difficulty ─────────────────
def test_pay_active_permit_underpaid_reports_invalid_state(api):
    """PRD §2.8: "the target resource must be in a state from which the requested
    transition is legal, else `ERR_INVALID_STATE`."
    PRD §3.4: "Payment is legal only from `ISSUED`, and the amount must be at least
    `fee_charged_cents`, else `ERR_FEE_NOT_PAID`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_pay
    """
    parcel, applicant, app, permit = create_active_permit(api)
    resp = api.pay_permit(permit["id"], {"amount_cents": 1}, make_applicant_headers(applicant["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_pay_active_permit_underpaid_partial_reports_invalid_state(api):
    """PRD §2.8: "the target resource must be in a state from which the requested
    transition is legal, else `ERR_INVALID_STATE`."
    PRD §3.4: "Payment is legal only from `ISSUED`, and the amount must be at least
    `fee_charged_cents`, else `ERR_FEE_NOT_PAID`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_pay
    """
    parcel, applicant, app, permit = create_active_permit(api)
    resp = api.pay_permit(
        permit["id"], {"amount_cents": 16599}, make_applicant_headers(applicant["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# ── Cross-entity referential state: permit needs APPROVED application — Difficulty ─
def test_issue_permit_on_submitted_application_rejected(api):
    """PRD §3.4: "issuance against an application whose status is not `APPROVED` is refused
    with `ERR_APPLICATION_NOT_APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/permit_issue_requires_application_approved
    """
    parcel, applicant, app = create_submitted_application(api)
    resp = api.create_permit(
        {"application_id": app["id"], "expected_application_version": app["version"]},
        make_planner_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_APPROVED)


def test_issue_permit_on_reviewed_but_undecided_application_rejected(api):
    """PRD §3.4: "issuance against an application whose status is not `APPROVED` is refused
    with `ERR_APPLICATION_NOT_APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/permit_issue_requires_application_approved
    """
    parcel, applicant, app = create_submitted_application(api)
    review_application(api, app["id"], "DIMENSIONAL", "PASS")
    reviewed = review_application(api, app["id"], "OVERLAY", "CLEARED")
    assert reviewed["status"] == "SUBMITTED"
    resp = api.create_permit(
        {"application_id": app["id"], "expected_application_version": reviewed["version"]},
        make_planner_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_APPROVED)


# ── Compensating invariant: permit revenue conserved on issue-then-revoke — Difficulty ─
def test_revoke_marks_revoked_and_keeps_fee_charged(api):
    """PRD §3.4: "Revocation sets `status` to `REVOKED`, refunds the fee by setting
    `fee_refunded_cents` equal to `fee_charged_cents` (restoring net permit revenue to
    its pre-issuance level)".

    Design: Difficulty/compensating_invariant/permit_revenue_conserved_on_issue_then_revoke
    """
    parcel, applicant, app, permit = create_issued_permit(api)
    assert permit["fee_charged_cents"] == 16600
    revoked = revoke_permit(api, permit["id"])
    assert revoked["status"] == "REVOKED"
    assert revoked["fee_charged_cents"] == 16600


def test_revoke_refunds_full_charged_fee(api):
    """PRD §3.4: "Revocation sets `status` to `REVOKED`, refunds the fee by setting
    `fee_refunded_cents` equal to `fee_charged_cents` (restoring net permit revenue to
    its pre-issuance level)".

    Design: Difficulty/compensating_invariant/permit_revenue_conserved_on_issue_then_revoke
    """
    parcel, applicant, app, permit = create_issued_permit(api)
    revoked = revoke_permit(api, permit["id"])
    assert revoked["fee_refunded_cents"] == 16600


# ── Compensating invariant: parcel sign slots conserved — Difficulty ─────────
def test_activation_consumes_one_parcel_slot(api):
    """PRD §3.4: "Activating a permit consumes a slot: the parcel's `active_permit_count`
    increases by one and `available_sign_slots` decreases by one."

    Design: Difficulty/compensating_invariant/parcel_slot_conserved_on_activate_then_revoke
    """
    parcel = create_parcel(api, max_signs=5)
    parcel, applicant, app, permit = create_active_permit(api, parcel, None)
    fetched = validate_success(api.get_parcel(parcel["id"], make_planner_headers()))
    assert fetched["active_permit_count"] == 1
    assert fetched["available_sign_slots"] == 4


def test_revoke_restores_parcel_slot(api):
    """PRD §3.4: "A planner revokes a permit from either `ISSUED` or `ACTIVE`. Revocation
    sets `status` to `REVOKED`, refunds the fee by setting `fee_refunded_cents` equal to
    `fee_charged_cents` (restoring net permit revenue to its pre-issuance level), and, if
    the permit was `ACTIVE` at the time, releases its parcel slot."

    Design: Difficulty/compensating_invariant/parcel_slot_conserved_on_activate_then_revoke
    """
    parcel = create_parcel(api, max_signs=5)
    parcel, applicant, app, permit = create_active_permit(api, parcel, None)
    revoke_permit(api, permit["id"])
    fetched = validate_success(api.get_parcel(parcel["id"], make_planner_headers()))
    assert fetched["active_permit_count"] == 0
    assert fetched["available_sign_slots"] == 5


# ── Corner cases ─────────────────────────────────────────────────────────────
def test_get_unknown_permit_not_found(api):
    """PRD §2.8: "for endpoints keyed on a typed root, a missing root yields the specific
    code `ERR_APPLICATION_NOT_FOUND`, `ERR_PARCEL_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, or
    `ERR_BILLBOARD_NOT_FOUND`."

    Design: Corner/entities/get_permit_not_found
    """
    resp = api.get_permit(NON_EXISTENT_UUID, make_planner_headers())
    validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_FOUND)


def test_pay_issued_permit_insufficient_amount_rejected(api):
    """PRD §3.4: "Payment is legal only from `ISSUED`, and the amount must be at least
    `fee_charged_cents`, else `ERR_FEE_NOT_PAID`."

    Design: Corner/validations/pay_issued_permit_insufficient_amount_fee_not_paid
    """
    parcel, applicant, app, permit = create_issued_permit(api)
    resp = api.pay_permit(permit["id"], {"amount_cents": 100}, make_applicant_headers(applicant["id"]))
    validate_error(resp, ApiErrorId.ERR_FEE_NOT_PAID)


def test_renew_permit_outside_window_rejected(api):
    """PRD §3.4: "An applicant renews an `ACTIVE` or `EXPIRED` permit, provided `fee_paid`
    is already true and the current instant falls within the renewal window — no earlier
    than 30 days before `expires_at` and no later than 30 days after it — else
    `ERR_RENEWAL_WINDOW_CLOSED`."

    Design: Corner/validations/renew_permit_outside_window_rejected
    """
    parcel, applicant, app, permit = create_active_permit(api)
    resp = api.renew_permit(permit["id"], make_applicant_headers(applicant["id"]))
    validate_error(resp, ApiErrorId.ERR_RENEWAL_WINDOW_CLOSED)


def test_activate_permit_exceeding_parcel_slots_rejected(api):
    """PRD §3.4: "Activation is further gated by the parcel's slot quota: if the parcel
    has no available sign slot (`available_sign_slots` would drop below zero), the payment
    is refused with `ERR_SIGN_SLOTS_EXHAUSTED`."

    Design: Corner/validations/activate_permit_exceeding_parcel_slots_rejected
    """
    parcel = create_parcel(api, max_signs=1)
    applicant = create_applicant(api)
    # permit #1 activated — consumes the parcel's only slot
    create_active_permit(api, parcel, applicant)
    # permit #2 issued for a second application on the same parcel, awaiting payment
    _, _, _, permit2 = create_issued_permit(api, parcel, applicant)
    resp = api.pay_permit(permit2["id"], {"amount_cents": 16600}, make_applicant_headers(applicant["id"]))
    validate_error(resp, ApiErrorId.ERR_SIGN_SLOTS_EXHAUSTED)


def test_issue_permit_with_stale_application_version_rejected(api):
    """PRD §2.6: "If that value does not equal the application's current `version` —
    because, for instance, a granted variance or a recorded review advanced the
    application and possibly changed its approved dimensions or fee after the client's
    read — the issuance is rejected with `ERR_STALE_VERSION` (HTTP 412)".

    Design: Corner/cross_cutting_complexity_layers/occ_stale_application_version_on_permit_issue
    """
    parcel, applicant, app = create_approved_application(api)
    resp = api.create_permit(
        {"application_id": app["id"], "expected_application_version": app["version"] - 1},
        make_planner_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_pay_permit_immediately_active(api):
    """PRD §3.4: "On success the permit transitions `ISSUED → ACTIVE`, `fee_paid` is set
    true, `activated_at` is stamped from the clock, and `expires_at` is set to the
    activation instant plus the permit term of 365 days."

    Design: Corner/consistency_model/permit_activation_immediately_visible
    """
    parcel, applicant, app, permit = create_issued_permit(api)
    paid = pay_permit(api, permit["id"], applicant["id"], amount_cents=16600)
    assert paid["status"] == "ACTIVE"
    assert paid["fee_paid"] is True
