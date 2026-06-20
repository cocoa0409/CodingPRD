"""Validation precedence, cross-entity preconditions, boundaries, and business-rule
violations.

Difficulty queue: priority_pair_validation_conflict, cross_entity_state_dependency,
boundary_precision (credit-score floor 580).
Corner queue: validations, entities (pricing tier).
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    create_lessor,
    create_approved_vendor,
    create_pending_vendor,
    create_approved_lessee,
    create_submitted_application,
    create_lease,
    attach_equipment,
    setup_active_lease,
    bill_line,
    list_scheduled_lines,
    pay_invoice_full,
    TEST_USERS,
)

ANALYST = TEST_USERS["credit_analyst_headers"]      # analyst-1
ANALYST2 = TEST_USERS["credit_analyst_2_headers"]   # analyst-2
OFFICER = TEST_USERS["funding_officer_headers"]
SERVICER = TEST_USERS["servicer_headers"]


# ─── priority_pair / sod_beats_approved_exceeds_requested ─────────────
def test_segregation_of_duties_wins_over_over_approval(api):
    """PRD §3.2: "Approval and decline are both subject to segregation of duties
    (Section 2.10): the acting analyst's `X-User-ID` must differ from
    `submitted_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.2: "Approval carries two further checks evaluated after the segregation
    check: the supplied `approved_amount_cents` must be greater than zero and must
    not exceed `requested_amount_cents` (otherwise `ERR_APPROVED_EXCEEDS_REQUESTED`)".

    An application (requested 500000) submitted by analyst-1, when approved by
    analyst-1 with approved_amount 900000 (both the SoD violation and the
    over-approval hold), returns ERR_SEGREGATION_OF_DUTIES — the check evaluated
    first.

    Design: Difficulty/priority_pair_validation_conflict/sod_beats_approved_exceeds_requested
    """
    lessor_id = create_lessor()["id"]
    app = create_submitted_application(lessor_id, requested_amount_cents=500_000,
                                       credit_score=760, submitter=ANALYST)
    res = api.approve_credit_application(
        lessor_id, app["id"], {"approved_amount_cents": 900_000}, ANALYST)
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


def test_over_approval_alone_returns_approved_exceeds_requested(api):
    """PRD §3.2: "the supplied `approved_amount_cents` must be greater than zero and
    must not exceed `requested_amount_cents` (otherwise
    `ERR_APPROVED_EXCEEDS_REQUESTED`)".

    With segregation of duties satisfied (approver analyst-2 differs from submitter
    analyst-1), approving with approved_amount 900000 over a requested 500000
    isolates the over-approval check, returning ERR_APPROVED_EXCEEDS_REQUESTED.

    Design: Difficulty/priority_pair_validation_conflict/sod_beats_approved_exceeds_requested
    """
    lessor_id = create_lessor()["id"]
    app = create_submitted_application(lessor_id, requested_amount_cents=500_000,
                                       credit_score=760, submitter=ANALYST)
    res = api.approve_credit_application(
        lessor_id, app["id"], {"approved_amount_cents": 900_000}, ANALYST2)
    validate_error(res, ApiErrorId.ERR_APPROVED_EXCEEDS_REQUESTED.value)


# ─── priority_pair / invalid_state_beats_vendor_not_approved_on_fund ──
def test_invalid_state_wins_over_vendor_not_approved_on_refund(api):
    """PRD §2.11: "fifth, that the target resource is in a state from which the
    requested transition is defined (`ERR_INVALID_STATE`) ... Only after all of
    these pass does the system evaluate the operation-specific business rules
    described in Section 3."
    PRD §3.7: "Funding requires the lease to already be in lifecycle `BOOKED`
    (otherwise `ERR_NOT_BOOKED`) and the lease's vendor to be in `APPROVED` status
    (otherwise `ERR_VENDOR_NOT_APPROVED`)."

    A lease already FUNDED (ACTIVE) whose vendor was subsequently suspended: a
    second fund attempt hits the state check (funding_status already FUNDED, an
    undefined transition) before the vendor business rule, returning
    ERR_INVALID_STATE.

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_vendor_not_approved_on_fund
    """
    ctx = setup_active_lease(
        equipment_cost_cents=500_000, term_months=12, monthly_rate_factor_bps=2000,
        serial_number="SN-700")
    lessor_id, lease_id, vendor_id = ctx["lessor_id"], ctx["lease"]["id"], ctx["vendor_id"]
    get_success_data(api.suspend_vendor(lessor_id, vendor_id, OFFICER))
    res = api.fund_lease(lessor_id, lease_id, OFFICER)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_refund_funded_lease_with_approved_vendor_still_invalid_state(api):
    """PRD §2.11: "fifth, that the target resource is in a state from which the
    requested transition is defined (`ERR_INVALID_STATE`) ... Only after all of
    these pass does the system evaluate the operation-specific business rules
    described in Section 3."

    The state check fires regardless of the vendor business rule: re-funding an
    already-FUNDED (ACTIVE) lease whose vendor is STILL APPROVED — so the vendor
    rule would pass — is rejected on the state check with ERR_INVALID_STATE,
    confirming ERR_INVALID_STATE is the operative, precedence-winning error.

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_vendor_not_approved_on_fund
    """
    ctx = setup_active_lease(
        equipment_cost_cents=500_000, term_months=12, monthly_rate_factor_bps=2000,
        serial_number="SN-701")
    lessor_id, lease_id = ctx["lessor_id"], ctx["lease"]["id"]
    # Vendor remains APPROVED; only the funding_status==FUNDED state blocks re-fund.
    res = api.fund_lease(lessor_id, lease_id, OFFICER)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# ─── cross_entity_state_dependency / lease_fund_requires_vendor_approved ─
def test_fund_blocked_when_vendor_pending(api):
    """PRD §3.7: "Funding requires the lease to already be in lifecycle `BOOKED`
    (otherwise `ERR_NOT_BOOKED`) and the lease's vendor to be in `APPROVED` status
    (otherwise `ERR_VENDOR_NOT_APPROVED`)."

    A BOOKED lease whose vendor is still PENDING cannot fund; the attempt returns
    ERR_VENDOR_NOT_APPROVED and funding_status stays PENDING_FUNDING.

    Design: Difficulty/cross_entity_state_dependency/lease_fund_requires_vendor_approved
    """
    lessor_id = create_lessor()["id"]
    vendor_id = create_pending_vendor(lessor_id)["id"]
    lessee_id = create_approved_lessee(lessor_id, approved_amount_cents=1_000_000)["id"]
    lease = create_lease(lessor_id, lessee_id, vendor_id,
                         equipment_cost_cents=500_000, term_months=12,
                         monthly_rate_factor_bps=2000)
    attach_equipment(lessor_id, lease["id"], "SN-900", original_cost_cents=500_000)
    get_success_data(api.book_lease(
        lessor_id, lease["id"], {"expected_lease_version": lease["version"]}, OFFICER))
    res = api.fund_lease(lessor_id, lease["id"], OFFICER)
    validate_error(res, ApiErrorId.ERR_VENDOR_NOT_APPROVED.value)
    lease_after = get_success_data(api.get_lease(lessor_id, lease["id"], OFFICER))
    assert lease_after["funding_status"] == "PENDING_FUNDING", f"got {lease_after['funding_status']}"


def test_fund_blocked_when_vendor_suspended(api):
    """PRD §3.7: "Funding requires the lease to already be in lifecycle `BOOKED`
    (otherwise `ERR_NOT_BOOKED`) and the lease's vendor to be in `APPROVED` status
    (otherwise `ERR_VENDOR_NOT_APPROVED`)."
    PRD §3.1: "An approved vendor may later be moved to `SUSPENDED`".

    The Lease -> Vendor dependency also blocks funding when the vendor has been
    suspended (not APPROVED): a BOOKED lease whose vendor is SUSPENDED returns
    ERR_VENDOR_NOT_APPROVED.

    Design: Difficulty/cross_entity_state_dependency/lease_fund_requires_vendor_approved
    """
    lessor_id = create_lessor()["id"]
    vendor_id = create_approved_vendor(lessor_id)["id"]
    lessee_id = create_approved_lessee(lessor_id, approved_amount_cents=1_000_000)["id"]
    lease = create_lease(lessor_id, lessee_id, vendor_id,
                         equipment_cost_cents=500_000, term_months=12,
                         monthly_rate_factor_bps=2000)
    attach_equipment(lessor_id, lease["id"], "SN-901", original_cost_cents=500_000)
    get_success_data(api.book_lease(
        lessor_id, lease["id"], {"expected_lease_version": lease["version"]}, OFFICER))
    get_success_data(api.suspend_vendor(lessor_id, vendor_id, OFFICER))
    res = api.fund_lease(lessor_id, lease["id"], OFFICER)
    validate_error(res, ApiErrorId.ERR_VENDOR_NOT_APPROVED.value)


# ─── cross_entity_state_dependency / equipment_return_requires_eot ────
def test_return_blocked_when_lease_active(api):
    """PRD §3.12: "A unit is **returned** — moved from `ON_LEASE` to `RETURNED` —
    only when its owning lease is in `lifecycle_status` `END_OF_TERM` (otherwise
    `ERR_LEASE_NOT_END_OF_TERM`)".

    A unit on an ACTIVE lease (never moved to END_OF_TERM) cannot be returned; the
    attempt returns ERR_LEASE_NOT_END_OF_TERM and the unit stays ON_LEASE.

    Design: Difficulty/cross_entity_state_dependency/equipment_return_requires_lease_end_of_term
    """
    ctx = setup_active_lease(
        equipment_cost_cents=500_000, term_months=12, monthly_rate_factor_bps=2000,
        serial_number="SN-1000")
    asset_mgr = TEST_USERS["asset_manager_headers"]
    res = api.return_equipment(ctx["lessor_id"], ctx["unit"]["id"], asset_mgr)
    validate_error(res, ApiErrorId.ERR_LEASE_NOT_END_OF_TERM.value)
    unit = get_success_data(api.get_equipment(ctx["lessor_id"], ctx["unit"]["id"], asset_mgr))
    assert unit["status"] == "ON_LEASE", f"got {unit['status']}"


def test_return_blocked_when_lease_only_booked(api):
    """PRD §3.12: "A unit is **returned** — moved from `ON_LEASE` to `RETURNED` —
    only when its owning lease is in `lifecycle_status` `END_OF_TERM` (otherwise
    `ERR_LEASE_NOT_END_OF_TERM`)".

    The EquipmentUnit -> Lease dependency also blocks return from an earlier
    lifecycle: a unit on a merely BOOKED (not yet funded, not END_OF_TERM) lease
    cannot be returned, returning ERR_LEASE_NOT_END_OF_TERM.

    Design: Difficulty/cross_entity_state_dependency/equipment_return_requires_lease_end_of_term
    """
    lessor_id = create_lessor()["id"]
    vendor_id = create_approved_vendor(lessor_id)["id"]
    lessee_id = create_approved_lessee(lessor_id, approved_amount_cents=1_000_000)["id"]
    lease = create_lease(lessor_id, lessee_id, vendor_id,
                         equipment_cost_cents=500_000, term_months=12,
                         monthly_rate_factor_bps=2000)
    unit = attach_equipment(lessor_id, lease["id"], "SN-1001", original_cost_cents=500_000)
    get_success_data(api.book_lease(
        lessor_id, lease["id"], {"expected_lease_version": lease["version"]}, OFFICER))
    asset_mgr = TEST_USERS["asset_manager_headers"]
    res = api.return_equipment(lessor_id, unit["id"], asset_mgr)
    validate_error(res, ApiErrorId.ERR_LEASE_NOT_END_OF_TERM.value)


# ─── boundary_precision / credit_score_floor_580_inclusive ────────────
def test_credit_score_580_is_approvable_as_subprime(api):
    """PRD §3.2: "the application's `credit_score` must be at least 580 (otherwise
    `ERR_SCORE_BELOW_FLOOR`)".
    PRD §3.2: "a score below 640 (necessarily in the 580-through-639 band, since
    lower scores are rejected by the underwriting floor) yields `SUBPRIME`."

    Score exactly 580 (the inclusive floor) approves and computes SUBPRIME.

    Design: Difficulty/boundary_precision_check/credit_score_floor_580_inclusive
    """
    lessor_id = create_lessor()["id"]
    app = create_submitted_application(lessor_id, requested_amount_cents=500_000,
                                       credit_score=580, submitter=ANALYST)
    approved = validate_success(api.approve_credit_application(
        lessor_id, app["id"], {"approved_amount_cents": 500_000}, ANALYST2), 200)
    assert approved["status"] == "APPROVED", f"got {approved['status']}"
    assert approved["pricing_tier"] == "SUBPRIME", f"got {approved['pricing_tier']}"


def test_credit_score_579_below_floor_rejected(api):
    """PRD §3.2: "the application's `credit_score` must be at least 580 (otherwise
    `ERR_SCORE_BELOW_FLOOR`)".

    Score 579 (one below the inclusive floor) is rejected with ERR_SCORE_BELOW_FLOOR.

    Design: Difficulty/boundary_precision_check/credit_score_floor_580_inclusive
    """
    lessor_id = create_lessor()["id"]
    app = create_submitted_application(lessor_id, requested_amount_cents=500_000,
                                       credit_score=579, submitter=ANALYST)
    res = api.approve_credit_application(
        lessor_id, app["id"], {"approved_amount_cents": 500_000}, ANALYST2)
    validate_error(res, ApiErrorId.ERR_SCORE_BELOW_FLOOR.value)


# ─── Corner: entities / credit_application_pricing_tier_prime_vs_near ─
def test_pricing_tier_prime_at_720_and_near_prime_at_700(api):
    """PRD §3.2: "a score of at least 720 yields `PRIME`".
    PRD §3.2: "a score from 640 up to but not including 720 yields `NEAR_PRIME`".

    Approving a 720-score application yields PRIME; a 700-score application yields
    NEAR_PRIME.

    Design: Corner/entities/credit_application_pricing_tier_prime_vs_near_prime
    """
    lessor_id = create_lessor()["id"]
    app720 = create_submitted_application(lessor_id, requested_amount_cents=500_000,
                                          credit_score=720, submitter=ANALYST)
    app700 = create_submitted_application(lessor_id, requested_amount_cents=500_000,
                                          credit_score=700, submitter=ANALYST)
    a720 = validate_success(api.approve_credit_application(
        lessor_id, app720["id"], {"approved_amount_cents": 500_000}, ANALYST2), 200)
    a700 = validate_success(api.approve_credit_application(
        lessor_id, app700["id"], {"approved_amount_cents": 500_000}, ANALYST2), 200)
    assert a720["pricing_tier"] == "PRIME", f"got {a720['pricing_tier']}"
    assert a700["pricing_tier"] == "NEAR_PRIME", f"got {a700['pricing_tier']}"


# ─── Corner: validations / trac_residual_required_when_type_trac ──────
def test_trac_lease_without_residual_rejected_on_book(api):
    """PRD §3.4: "the TRAC consistency rule — `trac_residual_pct_bps` must be
    present exactly when `lease_type` is `TRAC` and absent otherwise, and when
    present it must be at least 1000 basis points, i.e. at least 10% of cost
    (`ERR_TRAC_RESIDUAL_REQUIRED`)."

    Originating a TRAC lease with no trac_residual_pct_bps and booking it returns
    ERR_TRAC_RESIDUAL_REQUIRED.

    Design: Corner/validations/trac_residual_required_when_type_trac
    """
    lessor_id = create_lessor()["id"]
    vendor_id = create_approved_vendor(lessor_id)["id"]
    lessee_id = create_approved_lessee(lessor_id, approved_amount_cents=1_000_000)["id"]
    # The scaffold's TRAC consistency check is part of booking; some implementations
    # may also reject at create. We exercise the book path which the PRD names.
    create_res = api.create_lease(
        lessor_id, lessee_id,
        {"vendor_id": vendor_id, "lease_type": "TRAC", "equipment_cost_cents": 600_000,
         "term_months": 12, "monthly_rate_factor_bps": 2000}, OFFICER)
    if create_res.status_code >= 400:
        validate_error(create_res, ApiErrorId.ERR_TRAC_RESIDUAL_REQUIRED.value)
        return
    lease = get_success_data(create_res)
    attach_equipment(lessor_id, lease["id"], "TRAC-NORES-1", original_cost_cents=600_000)
    res = api.book_lease(
        lessor_id, lease["id"], {"expected_lease_version": lease["version"]}, OFFICER)
    validate_error(res, ApiErrorId.ERR_TRAC_RESIDUAL_REQUIRED.value)


# ─── Corner: validations / book_no_equipment_rejected ─────────────────
def test_book_without_equipment_rejected(api):
    """PRD §3.4: "Booking enforces a sequence of preconditions: the version check
    first (`ERR_STALE_VERSION`, 412); then the cross-entity credit check that the
    lessee's `available_credit_cents` is at least the lease's computed
    `financed_amount_cents` (`ERR_CREDIT_LIMIT_EXCEEDED`); that at least one
    `EquipmentUnit` is attached (`ERR_NO_EQUIPMENT`)".

    Booking a lease with zero attached units returns ERR_NO_EQUIPMENT.

    Design: Corner/validations/book_no_equipment_rejected
    """
    lessor_id = create_lessor()["id"]
    vendor_id = create_approved_vendor(lessor_id)["id"]
    lessee_id = create_approved_lessee(lessor_id, approved_amount_cents=1_000_000)["id"]
    lease = create_lease(lessor_id, lessee_id, vendor_id,
                         equipment_cost_cents=500_000, term_months=12,
                         monthly_rate_factor_bps=2000)
    res = api.book_lease(
        lessor_id, lease["id"], {"expected_lease_version": lease["version"]}, OFFICER)
    validate_error(res, ApiErrorId.ERR_NO_EQUIPMENT.value)


# ─── Corner: validations / book_credit_limit_exceeded_rejected ────────
def test_book_exceeding_available_credit_rejected(api):
    """PRD §3.4: "the cross-entity credit check that the lessee's
    `available_credit_cents` is at least the lease's computed `financed_amount_cents`
    (`ERR_CREDIT_LIMIT_EXCEEDED`)".

    A lessee approved for 500000 with a lease whose financed_amount is 800000 cannot
    book; the attempt returns ERR_CREDIT_LIMIT_EXCEEDED.

    Design: Corner/validations/book_credit_limit_exceeded_rejected
    """
    lessor_id = create_lessor()["id"]
    vendor_id = create_approved_vendor(lessor_id)["id"]
    lessee_id = create_approved_lessee(lessor_id, approved_amount_cents=500_000)["id"]
    lease = create_lease(lessor_id, lessee_id, vendor_id,
                         equipment_cost_cents=800_000, term_months=12,
                         monthly_rate_factor_bps=2000)
    attach_equipment(lessor_id, lease["id"], "N-SN-1", original_cost_cents=800_000)
    res = api.book_lease(
        lessor_id, lease["id"], {"expected_lease_version": lease["version"]}, OFFICER)
    validate_error(res, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED.value)


# ─── Corner: validations / payment_exceeds_due_rejected ───────────────
def test_payment_exceeding_outstanding_rejected(api):
    """PRD §3.9: "A `Servicer` records a **Payment** against an invoice by supplying
    `amount_cents`, which must be positive and must not exceed the invoice's
    outstanding balance — its `total_due_cents` minus its `amount_paid_cents` — at
    apply time, else `ERR_PAYMENT_EXCEEDS_DUE`."

    A payment of 999999 against a fresh invoice whose total_due is far smaller
    returns ERR_PAYMENT_EXCEEDS_DUE.

    Design: Corner/validations/payment_exceeds_due_rejected
    """
    ctx = setup_active_lease(
        equipment_cost_cents=500_000, term_months=12, monthly_rate_factor_bps=2000,
        serial_number="O-SN-1")
    lessor_id, lease_id = ctx["lessor_id"], ctx["lease"]["id"]
    line = list_scheduled_lines(lessor_id, lease_id)[0]
    inv = bill_line(lessor_id, lease_id, line["id"])
    assert inv["total_due_cents"] < 999_999
    res = api.create_payment(lessor_id, inv["id"], {"amount_cents": 999_999}, SERVICER)
    validate_error(res, ApiErrorId.ERR_PAYMENT_EXCEEDS_DUE.value)


# ─── Corner: validations / duplicate_serial_rejected ──────────────────
def test_duplicate_serial_on_attach_rejected(api):
    """PRD §3.5: "a serial must be unique per lessor across all non-`DISPOSED` units
    at the instant of attachment; attaching a unit whose serial is already held by a
    live (non-disposed) unit is rejected with `ERR_DUPLICATE_SERIAL`."

    Attaching a second unit with a serial already held by a live unit returns
    ERR_DUPLICATE_SERIAL.

    Design: Corner/validations/duplicate_serial_rejected
    """
    lessor_id = create_lessor()["id"]
    vendor_id = create_approved_vendor(lessor_id)["id"]
    lessee_id = create_approved_lessee(lessor_id, approved_amount_cents=1_000_000)["id"]
    lease = create_lease(lessor_id, lessee_id, vendor_id,
                         equipment_cost_cents=500_000, term_months=12,
                         monthly_rate_factor_bps=2000)
    attach_equipment(lessor_id, lease["id"], "DUP-X", original_cost_cents=500_000)
    res = api.attach_equipment(
        lessor_id, lease["id"],
        {"serial_number": "DUP-X", "description": "Press2", "original_cost_cents": 400_000},
        OFFICER)
    validate_error(res, ApiErrorId.ERR_DUPLICATE_SERIAL.value)


# ─── Corner: validations / ucc_wrong_jurisdiction_rejected ────────────
def test_manual_ucc_wrong_jurisdiction_rejected(api):
    """PRD §3.7: "a `FundingOfficer` may **manually file** a continuation against a
    lease by supplying a `jurisdiction_state_code`, which must equal the lessor's
    `home_state_code` (otherwise `ERR_UCC_WRONG_JURISDICTION`)."

    A manual UCC filing with jurisdiction CA against an NY lessor returns
    ERR_UCC_WRONG_JURISDICTION.

    Design: Corner/validations/ucc_wrong_jurisdiction_rejected
    """
    lessor_id = create_lessor(home_state_code="NY")["id"]
    vendor_id = create_approved_vendor(lessor_id)["id"]
    lessee_id = create_approved_lessee(lessor_id, approved_amount_cents=1_000_000)["id"]
    lease = create_lease(lessor_id, lessee_id, vendor_id,
                         equipment_cost_cents=500_000, term_months=12,
                         monthly_rate_factor_bps=2000)
    attach_equipment(lessor_id, lease["id"], "Q-SN-1", original_cost_cents=500_000)
    get_success_data(api.book_lease(
        lessor_id, lease["id"], {"expected_lease_version": lease["version"]}, OFFICER))
    res = api.create_ucc_filing(
        lessor_id, lease["id"], {"jurisdiction_state_code": "CA"}, OFFICER)
    validate_error(res, ApiErrorId.ERR_UCC_WRONG_JURISDICTION.value)


# ─── Corner: validations / invoice_void_with_payments_rejected ────────
def test_void_invoice_with_cleared_payment_rejected(api):
    """PRD §3.9: "A `Servicer` may **void** an `OPEN` invoice, but only when it has
    no cleared payments, that is `amount_paid_cents` equals zero (otherwise
    `ERR_INVOICE_HAS_PAYMENTS`)."

    An invoice with a partial cleared payment cannot be voided; the attempt returns
    ERR_INVOICE_HAS_PAYMENTS.

    Design: Corner/validations/invoice_void_with_payments_rejected
    """
    ctx = setup_active_lease(
        equipment_cost_cents=500_000, term_months=12, monthly_rate_factor_bps=2000,
        serial_number="R-SN-1")
    lessor_id, lease_id = ctx["lessor_id"], ctx["lease"]["id"]
    line = list_scheduled_lines(lessor_id, lease_id)[0]
    inv = bill_line(lessor_id, lease_id, line["id"])
    pay_invoice_full(lessor_id, inv["id"], 50_000)  # partial payment, stays OPEN
    res = api.void_invoice(lessor_id, inv["id"], SERVICER)
    validate_error(res, ApiErrorId.ERR_INVOICE_HAS_PAYMENTS.value)
