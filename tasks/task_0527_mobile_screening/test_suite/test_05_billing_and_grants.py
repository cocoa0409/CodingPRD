"""Charge lifecycle: provisional vs finalized responsibility, grant burn, OCC, and voids."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId, TEST_USERS,
    fixtures,
)

PM = TEST_USERS["program_manager_headers"]
CS = TEST_USERS["clinical_staff_headers"]
BC = TEST_USERS["billing_clerk_headers"]


def _charge_for(api, appointment_id):
    charges, _ = validate_paginated(api.list_charges(BC, params={"appointment_id": appointment_id}))
    return charges[0]


# ---------------------------------------------------------------------------
# Corner: calculations — self-pay provisional equals list price
# ---------------------------------------------------------------------------
def test_self_pay_provisional_equals_list_price(api):
    """PRD §3.7: "For a `SELF_PAY` participant, `grant_covered_cents` is 0 and the
    provisional patient responsibility equals the full list price."
    PRD §3.7: "captures `list_price_cents` — the gross screening price for the event's
    modality, drawn from the price schedule of 20000 cents for `MAMMOGRAPHY`, 8000 cents
    for `BLOOD_PANEL`, 12000 cents for `BONE_DENSITY`, and 6000 cents for `SKIN`."

    Design: Corner/calculations/self_pay_provisional_equals_list_price
    """
    ctx = fixtures.create_screened_appointment(pay_type="SELF_PAY", modality="SKIN")
    charge = ctx["charge"]
    assert charge["provisional_patient_responsibility_cents"] == 6000, (
        f"expected 6000, got {charge['provisional_patient_responsibility_cents']}"
    )
    assert charge["grant_covered_cents"] == 0, f"expected 0, got {charge['grant_covered_cents']}"


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc — provisional vs finalized (INSURANCE)
# ---------------------------------------------------------------------------
def test_insurance_provisional_vs_final_responsibility(api):
    """PRD §3.7: "For an `INSURANCE` participant, `grant_covered_cents` is 0 and, because the
    payer has not yet adjudicated, the provisional responsibility is an estimate: the list
    price multiplied by a provisional coinsurance rate of 20 percent (0.20), rounded half up
    to whole cents."
    PRD §3.7: "for `INSURANCE`, it equals the list price minus `insurance_allowed_cents`
    (superseding, not adding to, the provisional estimate)"

    Design: Difficulty/dual_variant_calc/patient_responsibility_provisional_vs_final_insurance
    """
    ctx = fixtures.create_screened_appointment(pay_type="INSURANCE", modality="MAMMOGRAPHY",
                                              insurance_member_id="INS-1")
    charge = ctx["charge"]
    # provisional = 20000 * 0.20 = 4000
    assert charge["provisional_patient_responsibility_cents"] == 4000, (
        f"expected provisional 4000, got {charge['provisional_patient_responsibility_cents']}"
    )
    adjudicated = validate_success(api.adjudicate_charge(
        charge["id"], {"expected_charge_version": charge["version"], "insurance_allowed_cents": 15000}, BC))
    # final = 20000 - 15000 = 5000
    assert adjudicated["final_patient_responsibility_cents"] == 5000, (
        f"expected final 5000, got {adjudicated['final_patient_responsibility_cents']}"
    )
    assert adjudicated["status"] == "ADJUDICATED"


def test_insurance_provisional_estimate_is_twenty_percent(api):
    """PRD §3.7: "For an `INSURANCE` participant, `grant_covered_cents` is 0 and, because the
    payer has not yet adjudicated, the provisional responsibility is an estimate: the list
    price multiplied by a provisional coinsurance rate of 20 percent (0.20), rounded half up
    to whole cents."

    Design: Difficulty/dual_variant_calc/patient_responsibility_provisional_vs_final_insurance
    """
    ctx = fixtures.create_screened_appointment(pay_type="INSURANCE", modality="MAMMOGRAPHY",
                                              insurance_member_id="INS-2")
    charge = ctx["charge"]
    assert charge["provisional_patient_responsibility_cents"] == 4000, (
        f"expected provisional 4000 (20% of 20000), got {charge['provisional_patient_responsibility_cents']}"
    )
    assert charge["grant_covered_cents"] == 0


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc — grant estimated vs actual burn
# ---------------------------------------------------------------------------
def test_grant_committed_and_settled_burn(api):
    """PRD §2.8: "its `committed_cents` (the sum of `grant_covered_cents` across all charges
    drawing this grant that are in `DRAFT`, `ADJUDICATED`, or `SETTLED`), and its
    `settled_cents` (the sum of `grant_covered_cents` across only the `SETTLED` charges
    drawing this grant)."
    PRD §3.7: "When the charge is grant-funded, settlement increases the grant's
    `settled_cents` by the charge's `grant_covered_cents` while leaving `committed_cents`
    unchanged — the commitment simply becomes a realized settlement."

    Design: Difficulty/dual_variant_calc/grant_estimated_vs_actual_burn
    """
    # BLOOD_PANEL list price 8000, grant budget 10000 → grant_covered_cents = 8000
    ctx = fixtures.create_screened_appointment(pay_type="GRANT", modality="BLOOD_PANEL",
                                              grant_total_budget_cents=10000)
    charge = ctx["charge"]
    grant = ctx["grant"]
    adj = validate_success(api.adjudicate_charge(
        charge["id"], {"expected_charge_version": charge["version"]}, BC))
    validate_success(api.settle_charge(
        charge["id"], {"expected_charge_version": adj["version"]}, BC))
    g = validate_success(api.get_grant(grant["id"], PM))
    assert g["committed_cents"] == 8000, f"expected committed 8000, got {g['committed_cents']}"
    assert g["settled_cents"] == 8000, f"expected settled 8000, got {g['settled_cents']}"
    assert g["remaining_cents"] == 2000, f"expected remaining 2000, got {g['remaining_cents']}"


def test_grant_committed_before_settlement(api):
    """PRD §2.8: "The estimated burn, driven by `committed_cents` and hence `remaining_cents`
    and `is_depleted`, counts every `DRAFT`, `ADJUDICATED`, and `SETTLED` charge as spent and
    is what blocks new bookings. The actual burn, `settled_cents`, counts only `SETTLED`
    charges and represents realized spend; it is always less than or equal to the estimated
    burn"

    Design: Difficulty/dual_variant_calc/grant_estimated_vs_actual_burn
    """
    ctx = fixtures.create_screened_appointment(pay_type="GRANT", modality="BLOOD_PANEL",
                                              grant_total_budget_cents=10000)
    g = validate_success(api.get_grant(ctx["grant"]["id"], PM))
    # Right after screening (DRAFT charge): committed reflects the commitment, settled is still 0.
    assert g["committed_cents"] == 8000, f"expected committed 8000, got {g['committed_cents']}"
    assert g["settled_cents"] == 0, f"expected settled 0 pre-settle, got {g['settled_cents']}"
    assert g["remaining_cents"] == 2000, f"expected remaining 2000, got {g['remaining_cents']}"


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine — charge DRAFT branch to VOID
# ---------------------------------------------------------------------------
def test_charge_void_from_draft(api):
    """PRD §3.7: "Voiding a charge moves it to `VOID` and is permitted while the charge is in
    `DRAFT` or `ADJUDICATED` (otherwise `ERR_INVALID_STATE`); void takes no version field."
    PRD §3.7: "For a `SELF_PAY` participant, `grant_covered_cents` is 0 and the provisional
    patient responsibility equals the full list price."

    Design: Difficulty/non_linear_state_machine/charge_branch_draft_to_adjudicated_or_void
    """
    ctx = fixtures.create_screened_appointment(pay_type="SELF_PAY", modality="SKIN")
    charge = ctx["charge"]
    assert charge["provisional_patient_responsibility_cents"] == 6000
    voided = validate_success(api.void_charge(charge["id"], BC))
    assert voided["status"] == "VOID", f"expected VOID, got {voided['status']}"


def test_charge_adjudicate_from_draft(api):
    """PRD §3.7: "A `BillingClerk` adjudicates a charge, advancing it from `DRAFT` to
    `ADJUDICATED`."
    PRD §3.7: "for `SELF_PAY`, the final patient responsibility equals the list price"

    Design: Difficulty/non_linear_state_machine/charge_branch_draft_to_adjudicated_or_void
    """
    ctx = fixtures.create_screened_appointment(pay_type="SELF_PAY", modality="SKIN")
    charge = ctx["charge"]
    adjudicated = validate_success(api.adjudicate_charge(
        charge["id"], {"expected_charge_version": charge["version"]}, BC))
    assert adjudicated["status"] == "ADJUDICATED", f"expected ADJUDICATED, got {adjudicated['status']}"
    assert adjudicated["final_patient_responsibility_cents"] == 6000, (
        f"expected final 6000, got {adjudicated['final_patient_responsibility_cents']}"
    )


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check — grant depletion at remaining == 0
# ---------------------------------------------------------------------------
def test_grant_depleted_when_remaining_exactly_zero(api):
    """PRD §2.8: "The grant's `is_depleted` flag is true exactly when `remaining_cents` is at
    or below the depletion floor of zero cents, and false otherwise."

    Design: Difficulty/boundary_precision_check/grant_depletion_boundary_remaining_exactly_zero
    """
    # budget 8000, BLOOD_PANEL list 8000 → remaining 0
    ctx = fixtures.create_screened_appointment(pay_type="GRANT", modality="BLOOD_PANEL",
                                              grant_total_budget_cents=8000)
    g = validate_success(api.get_grant(ctx["grant"]["id"], PM))
    assert g["remaining_cents"] == 0, f"expected remaining 0, got {g['remaining_cents']}"
    assert g["is_depleted"] is True, f"expected is_depleted True at remaining 0, got {g['is_depleted']}"


def test_grant_not_depleted_when_remaining_positive(api):
    """PRD §2.8: "The grant's `is_depleted` flag is true exactly when `remaining_cents` is at
    or below the depletion floor of zero cents, and false otherwise."

    Design: Difficulty/boundary_precision_check/grant_depletion_boundary_remaining_exactly_zero
    """
    # budget 10000, BLOOD_PANEL list 8000 → remaining 2000 > 0
    ctx = fixtures.create_screened_appointment(pay_type="GRANT", modality="BLOOD_PANEL",
                                              grant_total_budget_cents=10000)
    g = validate_success(api.get_grant(ctx["grant"]["id"], PM))
    assert g["remaining_cents"] == 2000, f"expected remaining 2000, got {g['remaining_cents']}"
    assert g["is_depleted"] is False, f"expected is_depleted False, got {g['is_depleted']}"


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant — grant committed conservation on void
# ---------------------------------------------------------------------------
def test_grant_committed_restored_on_void(api):
    """PRD §3.7: "When the voided charge is grant-funded, its `grant_covered_cents` is
    subtracted back from the grant's `committed_cents`, restoring headroom and preserving the
    conservation invariant."
    PRD §2.8: "Its `remaining_cents` is the available headroom, computed as
    `total_budget_cents` minus `committed_cents`"

    Design: Difficulty/compensating_invariant/grant_committed_conservation_on_void
    """
    ctx = fixtures.create_screened_appointment(pay_type="GRANT", modality="BLOOD_PANEL",
                                              grant_total_budget_cents=10000)
    charge = ctx["charge"]
    before = validate_success(api.get_grant(ctx["grant"]["id"], PM))
    assert before["committed_cents"] == 8000, f"setup: expected committed 8000, got {before['committed_cents']}"
    voided = validate_success(api.void_charge(charge["id"], BC))
    assert voided["status"] == "VOID"
    after = validate_success(api.get_grant(ctx["grant"]["id"], PM))
    assert after["committed_cents"] == 0, f"expected committed 0 after void, got {after['committed_cents']}"
    assert after["remaining_cents"] == 10000, f"expected remaining 10000, got {after['remaining_cents']}"


def test_grant_conservation_invariant_holds_across_void(api):
    """PRD §2.8: "Its `remaining_cents` is the available headroom, computed as
    `total_budget_cents` minus `committed_cents`"
    PRD §3.7: "When the voided charge is grant-funded, its `grant_covered_cents` is
    subtracted back from the grant's `committed_cents`, restoring headroom and preserving the
    conservation invariant."

    Design: Difficulty/compensating_invariant/grant_committed_conservation_on_void
    """
    ctx = fixtures.create_screened_appointment(pay_type="GRANT", modality="BLOOD_PANEL",
                                              grant_total_budget_cents=10000)
    charge = ctx["charge"]
    before = validate_success(api.get_grant(ctx["grant"]["id"], PM))
    # invariant before: total == remaining + committed
    assert before["total_budget_cents"] == before["remaining_cents"] + before["committed_cents"], (
        f"pre-void invariant broken: {before}"
    )
    validate_success(api.void_charge(charge["id"], BC))
    after = validate_success(api.get_grant(ctx["grant"]["id"], PM))
    # invariant after: total == remaining + committed, with committed back to 0
    assert after["total_budget_cents"] == after["remaining_cents"] + after["committed_cents"], (
        f"post-void invariant broken: {after}"
    )
    assert after["committed_cents"] == 0, f"expected committed 0 after void, got {after['committed_cents']}"


# ---------------------------------------------------------------------------
# Corner: validations — insurance adjudication out of range
# ---------------------------------------------------------------------------
def test_insurance_adjudication_out_of_range_returns_422(api):
    """PRD §3.7: "when the charge's `pay_type` is `INSURANCE` — the request must supply an
    `insurance_allowed_cents` that is between 0 and the charge's `list_price_cents` inclusive
    (otherwise `ERR_INVALID_ADJUDICATION`)."

    Design: Corner/validations/insurance_adjudication_out_of_range_returns_422
    """
    ctx = fixtures.create_screened_appointment(pay_type="INSURANCE", modality="MAMMOGRAPHY",
                                              insurance_member_id="INS-1")
    charge = ctx["charge"]
    resp = api.adjudicate_charge(
        charge["id"], {"expected_charge_version": charge["version"], "insurance_allowed_cents": 25000}, BC)
    validate_error(resp, ApiErrorId.ERR_INVALID_ADJUDICATION.value)
    reread = validate_success(api.get_charge(charge["id"], BC))
    assert reread["status"] == "DRAFT"


# ---------------------------------------------------------------------------
# Corner: rbac — clinical staff cannot adjudicate
# ---------------------------------------------------------------------------
def test_clinical_staff_cannot_adjudicate_charge(api):
    """PRD §2.1: "A `BillingClerk` owns the billing lifecycle — adjudicating, settling, and
    voiding charges."
    PRD §2.1: "When a caller holds a valid role but that role is not permitted for the
    requested operation, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."

    Design: Corner/rbac/clinical_staff_cannot_adjudicate_charge
    """
    ctx = fixtures.create_screened_appointment(pay_type="INSURANCE", modality="MAMMOGRAPHY",
                                              insurance_member_id="INS-1")
    charge = ctx["charge"]
    resp = api.adjudicate_charge(
        charge["id"], {"expected_charge_version": charge["version"], "insurance_allowed_cents": 15000}, CS)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


# ---------------------------------------------------------------------------
# Corner: cross_cutting — OCC stale version on settle and adjudicate
# ---------------------------------------------------------------------------
def test_settle_with_stale_version_returns_412(api):
    """PRD §2.7: "Settling a charge similarly requires `expected_charge_version` matching the
    charge's current `version`; because the adjudication that moved the charge into
    `ADJUDICATED` already advanced its version, a settle request that still carries the
    pre-adjudication value is stale and is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_settle_stale_version_returns_412
    """
    ctx = fixtures.create_screened_appointment(pay_type="SELF_PAY", modality="SKIN")
    charge = ctx["charge"]
    draft_version = charge["version"]
    validate_success(api.adjudicate_charge(
        charge["id"], {"expected_charge_version": draft_version}, BC))
    # settle still carrying the pre-adjudication (DRAFT-era) version
    resp = api.settle_charge(charge["id"], {"expected_charge_version": draft_version}, BC)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
    reread = validate_success(api.get_charge(charge["id"], BC))
    assert reread["status"] == "ADJUDICATED"


def test_adjudicate_with_stale_version_returns_412(api):
    """PRD §2.7: "Adjudicating a charge requires the request to carry `expected_charge_version`
    matching that charge's current `version`. If another writer has advanced the charge's
    version since the client last observed it — for instance an earlier adjudication attempt
    or a void the client did not see — the adjudication carries a stale
    `expected_charge_version` and is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_adjudicate_stale_version_after_void_returns_412
    """
    ctx = fixtures.create_screened_appointment(pay_type="SELF_PAY", modality="SKIN")
    charge = ctx["charge"]
    # Submit a version one below the actual current version → stale.
    resp = api.adjudicate_charge(
        charge["id"], {"expected_charge_version": charge["version"] - 1}, BC)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
    reread = validate_success(api.get_charge(charge["id"], BC))
    assert reread["status"] == "DRAFT"


# ---------------------------------------------------------------------------
# Corner: endpoints — filtered list charges by grant_id
# ---------------------------------------------------------------------------
def test_filtered_list_charges_by_grant_id(api):
    """PRD §2.5: "charges by `appointment_id`, `participant_id`, `grant_id`, and `status`."

    Design: Corner/endpoints/filtered_list_charges_by_grant_id
    """
    ctx = fixtures.create_screened_appointment(pay_type="GRANT", modality="BLOOD_PANEL",
                                              grant_total_budget_cents=10000)
    grant = ctx["grant"]
    charges, meta = validate_paginated(api.list_charges(BC, params={"grant_id": grant["id"]}))
    assert meta["total_count"] == 1, f"expected 1 charge for grant, got {meta['total_count']}"
    assert charges[0]["grant_id"] == grant["id"], (
        f"expected grant_id {grant['id']}, got {charges[0]['grant_id']}"
    )
