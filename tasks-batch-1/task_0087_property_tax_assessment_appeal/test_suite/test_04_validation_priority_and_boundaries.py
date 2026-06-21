"""Validation precedence conflicts, cross-entity gates, panel scheduling, and boundaries.

Covers difficulty queue instances:
  priority_pair_validation_conflict / state_vs_business_fiscal_finalize_vs_payment_excess
  priority_pair_validation_conflict / existence_vs_business_constraint_approve_missing_vs_ineligible
  boundary_precision_check / certify_empty_assessment_set_zero_count_boundary
  cross_entity_state_dependency / deferral_default_requires_parcel_sold
  resource_temporal_overlap / panel_slot_buffer_overlap_rejected
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    NON_EXISTENT_UUID,
    make_hearing_officer_headers,
    create_owner,
    create_open_roll,
    create_parcel,
    setup_deferral_with_accrual,
    setup_scheduled_hearing,
    get_deferral,
)
from test_helpers import factories as f

ASSESSOR = TEST_USERS["assessor_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]


# ===========================================================================
# priority_pair_validation_conflict / state_vs_business_fiscal_finalize_vs_payment_excess
# ===========================================================================
def test_payment_to_defaulted_deferral_reports_invalid_state_over_excess(api):
    """PRD §3.9: "declaring default while the parcel is not sold is refused with
    `ERR_INVALID_STATE`. Both `SATISFIED` and `DEFAULTED` are terminal."
    PRD §2.8: "Business-referential rules — sale reassessment and prior-roll certification —
    follow, then the business constraints (exemption eligibility, duplicate exemption,
    panel-slot conflict, maximum rounds, settlement range, payment-exceeds-balance)."
    PRD §2.8: "State preconditions follow: the generic transition-allowed check
    (`ERR_INVALID_STATE`), then the roll-open, open-appeal, held-hearing, and
    assessments-final state gates."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_finalize_vs_payment_excess
    """
    # Build a DEFAULTED deferral: principal 200000 + accrued 10000, parcel sold, then default.
    owner, roll, parcel, final, bill, deferral = setup_deferral_with_accrual(
        principal_market=200000, annual_interest_rate=0.05
    )
    buyer = create_owner()
    validate_success(api.record_sale(parcel["id"], {"new_owner_id": buyer["id"]}, ASSESSOR))
    defaulted = validate_success(api.default_deferral(deferral["id"], ASSESSOR))
    assert defaulted["status"] == "DEFAULTED"
    # A payment that also exceeds balance, carrying the current (defaulted) version, must
    # report the state error, not the fiscal error.
    resp = api.create_payment(
        deferral["id"], f.create_payment_payload(999999, defaulted["version"]), ASSESSOR
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    # The rejected fiscal-over-state payment must leave the ledger untouched.
    after = get_deferral(deferral["id"])
    assert after["total_paid_cents"] == 0, \
        f"no payment should be recorded against a DEFAULTED agreement, got {after['total_paid_cents']}"


def test_in_range_payment_to_defaulted_deferral_still_invalid_state(api):
    """PRD §3.9: "Both `SATISFIED` and `DEFAULTED` are terminal."
    PRD §2.8: "State preconditions follow: the generic transition-allowed check
    (`ERR_INVALID_STATE`), then the roll-open, open-appeal, held-hearing, and
    assessments-final state gates."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_finalize_vs_payment_excess
    """
    # Even a within-balance amount is refused once the agreement is terminal (DEFAULTED):
    # the state gate fires regardless of the fiscal check.
    owner, roll, parcel, final, bill, deferral = setup_deferral_with_accrual(
        principal_market=200000, annual_interest_rate=0.05
    )
    buyer = create_owner()
    validate_success(api.record_sale(parcel["id"], {"new_owner_id": buyer["id"]}, ASSESSOR))
    defaulted = validate_success(api.default_deferral(deferral["id"], ASSESSOR))
    resp = api.create_payment(
        deferral["id"], f.create_payment_payload(5000, defaulted["version"]), ASSESSOR
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# ===========================================================================
# priority_pair_validation_conflict / existence_vs_business_constraint_approve_missing_vs_ineligible
# ===========================================================================
def test_approve_missing_exemption_reports_not_found_over_ineligible(api):
    """PRD §2.6: "Any referenced `id` that does not resolve to a stored resource — whether in
    the path or the request body — yields `ERR_NOT_FOUND` (HTTP 404), and existence is always
    checked before any state or business rule."

    Design: Difficulty/priority_pair_validation_conflict/existence_vs_business_constraint_approve_missing_vs_ineligible
    """
    # An OPEN roll and Reviewer exist; the probed exemption id does not.
    create_open_roll()
    resp = api.approve_exemption(NON_EXISTENT_UUID, REVIEWER)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_deny_missing_exemption_reports_not_found(api):
    """PRD §2.6: "Any referenced `id` that does not resolve to a stored resource — whether in
    the path or the request body — yields `ERR_NOT_FOUND` (HTTP 404), and existence is always
    checked before any state or business rule."

    Design: Difficulty/priority_pair_validation_conflict/existence_vs_business_constraint_approve_missing_vs_ineligible
    """
    # The existence check fires before any state/business rule on the deny path too.
    create_open_roll()
    resp = api.deny_exemption(NON_EXISTENT_UUID, REVIEWER)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


# ===========================================================================
# boundary_precision_check / certify_empty_assessment_set_zero_count_boundary
# ===========================================================================
def test_certify_empty_roll_succeeds(api):
    """PRD §3.1: "Certifying a roll is permitted only when every `Assessment` belonging to it
    has reached `FINAL`; if any assessment is not yet final, certification fails with
    `ERR_ASSESSMENTS_NOT_FINAL`."

    Design: Difficulty/boundary_precision_check/certify_empty_assessment_set_zero_count_boundary
    """
    roll = create_open_roll()
    certified = validate_success(api.certify_tax_roll(roll["id"], ASSESSOR))
    assert certified["status"] == "CERTIFIED", \
        f"an OPEN roll with zero assessments vacuously certifies, got {certified['status']}"


def test_empty_roll_certification_persists_on_refetch(api):
    """PRD §3.1: "Certifying a roll is permitted only when every `Assessment` belonging to it
    has reached `FINAL`; if any assessment is not yet final, certification fails with
    `ERR_ASSESSMENTS_NOT_FINAL`."

    Design: Difficulty/boundary_precision_check/certify_empty_assessment_set_zero_count_boundary
    """
    # The all-FINAL quantifier over an empty set is vacuously true, so the certify sticks.
    roll = create_open_roll()
    validate_success(api.certify_tax_roll(roll["id"], ASSESSOR))
    refetched = validate_success(api.get_tax_roll(roll["id"], ASSESSOR))
    assert refetched["status"] == "CERTIFIED", \
        f"certified empty roll must read back CERTIFIED, got {refetched['status']}"


# ===========================================================================
# cross_entity_state_dependency / deferral_default_requires_parcel_sold
# ===========================================================================
def test_default_while_parcel_active_rejected(api):
    """PRD §3.9: "When a parcel under deferral has been sold — its parcel status is `SOLD` —
    the assessor may declare the agreement defaulted, moving it `ACTIVE → DEFAULTED` and
    rendering `outstanding_balance_cents` immediately due; declaring default while the parcel
    is not sold is refused with `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/deferral_default_requires_parcel_sold
    """
    # ACTIVE deferral on a parcel that has not been sold.
    owner = create_owner(birth_date="1950-01-01T00:00:00.000Z")
    parcel = create_parcel(owner["id"], is_primary_residence=True)
    deferral = validate_success(
        api.create_deferral(f.create_deferral_payload(parcel["id"], owner["id"], 0.05), ASSESSOR),
        expected_status=201,
    )
    resp = api.default_deferral(deferral["id"], ASSESSOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = get_deferral(deferral["id"])
    assert after["status"] == "ACTIVE", \
        f"agreement should remain ACTIVE after a rejected default, got {after['status']}"


def test_default_after_parcel_sold_succeeds(api):
    """PRD §3.9: "When a parcel under deferral has been sold — its parcel status is `SOLD` —
    the assessor may declare the agreement defaulted, moving it `ACTIVE → DEFAULTED` and
    rendering `outstanding_balance_cents` immediately due".

    Design: Difficulty/cross_entity_state_dependency/deferral_default_requires_parcel_sold
    """
    # Once the parcel is SOLD the cross-entity gate is satisfied and default succeeds.
    owner, roll, parcel, final, bill, deferral = setup_deferral_with_accrual(
        principal_market=200000, annual_interest_rate=0.05
    )
    buyer = create_owner()
    validate_success(api.record_sale(parcel["id"], {"new_owner_id": buyer["id"]}, ASSESSOR))
    defaulted = validate_success(api.default_deferral(deferral["id"], ASSESSOR))
    assert defaulted["status"] == "DEFAULTED", \
        f"default on a SOLD parcel should succeed, got {defaulted['status']}"


# ===========================================================================
# resource_temporal_overlap / panel_slot_buffer_overlap_rejected
# ===========================================================================
def test_hearing_within_buffer_window_rejected(api):
    """PRD §3.7: "A new slot may not overlap any existing `SCHEDULED` or `HELD` hearing on
    the same panel, where each existing hearing is treated as occupying its half-open window
    from `starts_at` up to `ends_at` plus the panel's `setup_buffer_minutes` of clearance
    afterward; a proposed slot that intrudes on any such occupied-plus-buffer interval is
    rejected with `ERR_PANEL_SLOT_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/panel_slot_buffer_overlap_rejected
    """
    # Existing 10:00-11:00 slot, panel buffer 15 -> occupied through 11:15. A 11:10 start
    # falls inside the buffer and must be rejected.
    owner, roll, parcel, asmt, appeal, panel, hearing, ho_id = setup_scheduled_hearing(
        market_value=100000, panel_overrides={"setup_buffer_minutes": 15},
        starts_at="2026-07-01T10:00:00.000Z", ends_at="2026-07-01T11:00:00.000Z",
    )
    ho = make_hearing_officer_headers(ho_id)
    resp = api.create_hearing(
        f.create_hearing_payload(
            appeal["id"], panel["id"], ho_id,
            "2026-07-01T11:10:00.000Z", "2026-07-01T12:00:00.000Z",
        ),
        ho,
    )
    validate_error(resp, ApiErrorId.ERR_PANEL_SLOT_CONFLICT)


def test_hearing_outside_buffer_window_allowed(api):
    """PRD §3.7: "each existing hearing is treated as occupying its half-open window from
    `starts_at` up to `ends_at` plus the panel's `setup_buffer_minutes` of clearance
    afterward; a proposed slot that intrudes on any such occupied-plus-buffer interval is
    rejected with `ERR_PANEL_SLOT_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/panel_slot_buffer_overlap_rejected
    """
    # Existing 10:00-11:00 slot + buffer 15 -> occupied through 11:15. A slot starting at
    # 11:15 sits exactly at the half-open boundary and does not intrude.
    owner, roll, parcel, asmt, appeal, panel, hearing, ho_id = setup_scheduled_hearing(
        market_value=100000, panel_overrides={"setup_buffer_minutes": 15},
        starts_at="2026-07-01T10:00:00.000Z", ends_at="2026-07-01T11:00:00.000Z",
    )
    ho = make_hearing_officer_headers(ho_id)
    later = validate_success(
        api.create_hearing(
            f.create_hearing_payload(
                appeal["id"], panel["id"], ho_id,
                "2026-07-01T11:15:00.000Z", "2026-07-01T12:00:00.000Z",
            ),
            ho,
        ),
        expected_status=201,
    )
    assert later["status"] == "SCHEDULED"
