"""Validation rules: temporal overlaps, duplicate children, compute guards,
priority ordering, existence checks.

Translates difficulty queue A rules resource_temporal_overlap,
priority_pair_validation_conflict; plus corner queue B validation/error instances.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    make_taxpayer_headers,
    efile_payload, acknowledge_payload, create_amended_return_payload,
    create_estimated_tax_payment_payload, create_schedule_payload,
)
from test_helpers import fixtures as FIX
from test_helpers import (
    setup_filed_return, setup_draft_amendment,
    make_irs_gateway_headers,
)


# =====================================================================
# resource_temporal_overlap / estimated_payment_half_open_period_overlap
# =====================================================================

def test_estimated_payment_period_overlap_rejected(api):
    """PRD §3.4: "A new payment's period may not overlap the half-open period of any
    existing payment on the same return; two periods that merely touch at a shared
    endpoint — where an existing payment's `period_end` equals the new payment's
    `period_start` — do not overlap and are allowed, while any genuine overlap is
    rejected with `ERR_PAYMENT_PERIOD_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/estimated_payment_half_open_period_overlap
    """
    taxpayer, tax_return, _doc = FIX.setup_draft_return_with_w2(federal_withholding_cents=0)
    h = make_taxpayer_headers(taxpayer["id"])
    validate_success(api.create_estimated_tax_payment(
        create_estimated_tax_payment_payload(
            tax_return["id"], quarter="Q1", amount_cents=200_000,
            paid_on="2025-04-10T00:00:00Z",
            period_start="2025-01-01T00:00:00Z",
            period_end="2025-04-01T00:00:00Z"), h), 201)
    # Q2 period [2025-03-01, 2025-06-01) overlaps the Q1 period.
    resp = api.create_estimated_tax_payment(
        create_estimated_tax_payment_payload(
            tax_return["id"], quarter="Q2", amount_cents=200_000,
            paid_on="2025-06-10T00:00:00Z",
            period_start="2025-03-01T00:00:00Z",
            period_end="2025-06-01T00:00:00Z"), h)
    validate_error(resp, ApiErrorId.ERR_PAYMENT_PERIOD_OVERLAP.value)


def test_estimated_payment_touching_endpoint_allowed(api):
    """PRD §3.4: "A new payment's period may not overlap the half-open period of any
    existing payment on the same return; two periods that merely touch at a shared
    endpoint — where an existing payment's `period_end` equals the new payment's
    `period_start` — do not overlap and are allowed, while any genuine overlap is
    rejected with `ERR_PAYMENT_PERIOD_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/estimated_payment_half_open_period_overlap
    """
    taxpayer, tax_return, _doc = FIX.setup_draft_return_with_w2(federal_withholding_cents=0)
    h = make_taxpayer_headers(taxpayer["id"])
    validate_success(api.create_estimated_tax_payment(
        create_estimated_tax_payment_payload(
            tax_return["id"], quarter="Q1", amount_cents=200_000,
            paid_on="2025-04-10T00:00:00Z",
            period_start="2025-01-01T00:00:00Z",
            period_end="2025-04-01T00:00:00Z"), h), 201)
    # Q2 starts exactly where Q1 ends -> no overlap, allowed.
    validate_success(api.create_estimated_tax_payment(
        create_estimated_tax_payment_payload(
            tax_return["id"], quarter="Q2", amount_cents=200_000,
            paid_on="2025-06-10T00:00:00Z",
            period_start="2025-04-01T00:00:00Z",
            period_end="2025-07-01T00:00:00Z"), h), 201)


# =====================================================================
# resource_temporal_overlap / amendment_closed_window_adjacency_overlap
# =====================================================================

def test_amendment_window_adjacency_counts_as_overlap(api):
    """PRD §3.7: "Two amendments on the same `original_return_id` may not have correction
    windows that overlap, and because the window is closed, windows that merely touch at
    a shared endpoint — where an existing amendment's end equals the new amendment's
    start — do count as overlap; any such conflict is rejected with
    `ERR_CORRECTION_WINDOW_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/amendment_closed_window_adjacency_overlap
    """
    # First amendment created (DRAFT) covering [2025-01-01, 2025-06-30]; original stays FILED.
    taxpayer, filed, _ef, _amd1 = setup_draft_amendment(
        corrected_balance_due_cents=40_000,
        correction_period_start="2025-01-01T00:00:00Z",
        correction_period_end="2025-06-30T00:00:00Z")
    h = make_taxpayer_headers(taxpayer["id"])
    current = validate_success(api.get_tax_return(filed["id"], h), 200)
    # Second amendment starts exactly on the prior window's end -> overlap (closed interval).
    resp = api.create_amended_return(
        create_amended_return_payload(
            filed["id"], taxpayer["id"], current["version"],
            corrected_balance_due_cents=50_000,
            correction_period_start="2025-06-30T00:00:00Z",
            correction_period_end="2025-12-31T00:00:00Z"),
        h)
    validate_error(resp, ApiErrorId.ERR_CORRECTION_WINDOW_OVERLAP.value)


def test_amendment_disjoint_windows_allowed(api):
    """PRD §3.7: "Two amendments on the same `original_return_id` may not have correction
    windows that overlap, and because the window is closed, windows that merely touch at
    a shared endpoint — where an existing amendment's end equals the new amendment's
    start — do count as overlap; any such conflict is rejected with
    `ERR_CORRECTION_WINDOW_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/amendment_closed_window_adjacency_overlap
    """
    taxpayer, filed, _ef, _amd1 = setup_draft_amendment(
        corrected_balance_due_cents=40_000,
        correction_period_start="2025-01-01T00:00:00Z",
        correction_period_end="2025-06-30T00:00:00Z")
    h = make_taxpayer_headers(taxpayer["id"])
    current = validate_success(api.get_tax_return(filed["id"], h), 200)
    # Strictly disjoint window starting the day after -> allowed.
    validate_success(api.create_amended_return(
        create_amended_return_payload(
            filed["id"], taxpayer["id"], current["version"],
            corrected_balance_due_cents=50_000,
            correction_period_start="2025-07-01T00:00:00Z",
            correction_period_end="2025-12-31T00:00:00Z"),
        h), 201)


# =====================================================================
# priority_pair_validation_conflict / state_before_fiscal_constraint_on_compute
# =====================================================================

def test_compute_on_filed_return_state_error(api):
    """PRD §2.9: "Then state-machine legality of the requested transition
    (`ERR_INVALID_STATE`, HTTP 409). After these, the domain-specific business checks of
    §3 apply — child uniqueness, the income-document and Schedule A requirements for
    compute, the computed-and-current requirement for e-file, the optimistic-concurrency
    version match, the already-filed guard, the original-must-be-filed guard, the
    estimated-payment period overlap, and the correction-window overlap — each surfacing
    its own error as described in the workflow that owns it."
    PRD §3.5: "A compute on a `DRAFT` return advances it to `READY`; a compute on a
    return already in `READY` recomputes in place and leaves it `READY`."

    Design: Difficulty/priority_pair_validation_conflict/state_before_fiscal_constraint_on_compute
    """
    # ITEMIZED return WITH Schedule A, filed; recompute from FILED is undefined -> state wins.
    taxpayer, tax_return = FIX.setup_taxpayer_and_return(
        return_overrides={"filing_status": "SINGLE", "deduction_method": "ITEMIZED"})
    h = make_taxpayer_headers(taxpayer["id"])
    FIX.add_income_document(tax_return["id"], taxpayer["id"],
                            box_amount_cents=8_000_000, federal_withholding_cents=900_000)
    FIX.add_schedule(tax_return["id"], taxpayer["id"], "A", gross_amount_cents=2_500_000)
    computed = validate_success(api.compute_tax_return(tax_return["id"], h), 200)
    efiling = validate_success(api.efile_tax_return(
        tax_return["id"], efile_payload(computed["version"]), h), 201)
    validate_success(api.acknowledge_efiling(
        efiling["id"], acknowledge_payload("ACCEPTED", "A0000"),
        make_irs_gateway_headers()), 200)
    resp = api.compute_tax_return(tax_return["id"], h)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_itemized_constraint_surfaces_only_when_state_legal(api):
    """PRD §2.9: "Then state-machine legality of the requested transition
    (`ERR_INVALID_STATE`, HTTP 409). After these, the domain-specific business checks of
    §3 apply — child uniqueness, the income-document and Schedule A requirements for
    compute, the computed-and-current requirement for e-file, the optimistic-concurrency
    version match, the already-filed guard, the original-must-be-filed guard, the
    estimated-payment period overlap, and the correction-window overlap — each surfacing
    its own error as described in the workflow that owns it."
    PRD §3.5: "When the return's `deduction_method` is `ITEMIZED`, a Schedule A must be
    present at compute time; otherwise the compute is rejected with
    `ERR_ITEMIZED_REQUIRES_SCHEDULE_A` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/state_before_fiscal_constraint_on_compute
    """
    # DRAFT return (state check passes — compute from DRAFT is defined), ITEMIZED with
    # no Schedule A: the lower-priority fiscal constraint is what fires, confirming the
    # conflict test's state error genuinely pre-empts this check.
    taxpayer, tax_return, _doc = FIX.setup_draft_return_with_w2(
        federal_withholding_cents=0,
        return_overrides={"filing_status": "SINGLE", "deduction_method": "ITEMIZED"})
    h = make_taxpayer_headers(taxpayer["id"])
    resp = api.compute_tax_return(tax_return["id"], h)
    validate_error(resp, ApiErrorId.ERR_ITEMIZED_REQUIRES_SCHEDULE_A.value)


# =====================================================================
# priority_pair_validation_conflict / owner_auth_before_state_on_amend_file
# =====================================================================

def test_owner_auth_before_state_on_amend_file(api):
    """PRD §2.9: "Then resource ownership for taxpayer-owned returns and amendments
    (`ERR_NOT_RESOURCE_OWNER`). Then existence of path-referenced resources
    (`ERR_RETURN_NOT_FOUND`), followed by existence of body foreign-key targets
    (`ERR_FK_NOT_FOUND`)."
    PRD §2.1: "For any operation that targets a specific return or amendment owned by a
    taxpayer, if the acting `Taxpayer` or `Preparer` `X-User-ID` does not match the
    owning taxpayer, the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Difficulty/priority_pair_validation_conflict/owner_auth_before_state_on_amend_file
    """
    # Owner has a FILED return + DRAFT amendment; a second taxpayer (non-owner) files it.
    owner, filed, _ef, amendment = setup_draft_amendment(
        corrected_balance_due_cents=40_000,
        correction_period_start="2025-01-01T00:00:00Z",
        correction_period_end="2025-12-31T00:00:00Z")
    other = FIX.create_taxpayer(email="nonowner-amendfile@example.com",
                                full_name="X", filing_status="SINGLE")
    other_h = make_taxpayer_headers(other["id"])
    resp = api.file_amended_return(amendment["id"], other_h)
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


def test_amend_file_state_guard_surfaces_for_owner(api):
    """PRD §2.1: "For any operation that targets a specific return or amendment owned by
    a taxpayer, if the acting `Taxpayer` or `Preparer` `X-User-ID` does not match the
    owning taxpayer, the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."
    PRD §3.7: "Filing the 1040X is again reserved to the `Taxpayer` and is only defined
    when the amendment is in `DRAFT` and the original return is still `FILED` (the
    cross-entity guard reuses `ERR_ORIGINAL_NOT_FILED`)."

    Design: Difficulty/priority_pair_validation_conflict/owner_auth_before_state_on_amend_file
    """
    # The actual owner files the amendment (ownership passes), then files it again. The
    # already-FILED amendment now fails the state guard — confirming that with ownership
    # satisfied the lower-priority state check is reachable, so the non-owner conflict
    # test's ownership error genuinely pre-empts it.
    owner, _filed, _ef, amendment = setup_draft_amendment(
        corrected_balance_due_cents=40_000,
        correction_period_start="2025-01-01T00:00:00Z",
        correction_period_end="2025-12-31T00:00:00Z")
    h = make_taxpayer_headers(owner["id"])
    validate_success(api.file_amended_return(amendment["id"], h), 200)
    resp = api.file_amended_return(amendment["id"], h)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# =====================================================================
# Corner B / validations
# =====================================================================

def test_compute_with_no_income_documents(api):
    """PRD §3.5: "A compute is only permitted when the return holds at least one income
    document; an attempt to compute a return with no income documents is rejected with
    `ERR_NO_INCOME_DOCUMENTS` (HTTP 409)."

    Design: Corner/validations/compute_with_no_income_documents
    """
    taxpayer, tax_return = FIX.setup_taxpayer_and_return()
    h = make_taxpayer_headers(taxpayer["id"])
    resp = api.compute_tax_return(tax_return["id"], h)
    validate_error(resp, ApiErrorId.ERR_NO_INCOME_DOCUMENTS.value)


def test_itemized_compute_without_schedule_a(api):
    """PRD §3.5: "When the return's `deduction_method` is `ITEMIZED`, a Schedule A must
    be present at compute time; otherwise the compute is rejected with
    `ERR_ITEMIZED_REQUIRES_SCHEDULE_A` (HTTP 409)."

    Design: Corner/validations/itemized_compute_without_schedule_a
    """
    taxpayer, tax_return, _doc = FIX.setup_draft_return_with_w2(
        federal_withholding_cents=0,
        return_overrides={"filing_status": "SINGLE", "deduction_method": "ITEMIZED"})
    h = make_taxpayer_headers(taxpayer["id"])
    resp = api.compute_tax_return(tax_return["id"], h)
    validate_error(resp, ApiErrorId.ERR_ITEMIZED_REQUIRES_SCHEDULE_A.value)


def test_duplicate_schedule_type_rejected(api):
    """PRD §3.2: "At most one schedule of each type may exist on a return; attempting to
    add a second schedule of a type already present is rejected with
    `ERR_DUPLICATE_CHILD` (HTTP 409)."

    Design: Corner/validations/duplicate_schedule_type_rejected
    """
    taxpayer, tax_return = FIX.setup_taxpayer_and_return()
    h = make_taxpayer_headers(taxpayer["id"])
    validate_success(api.create_schedule(
        tax_return["id"],
        create_schedule_payload("C", gross_amount_cents=1_000_000,
                                expense_amount_cents=200_000), h), 201)
    resp = api.create_schedule(
        tax_return["id"], create_schedule_payload("C", gross_amount_cents=500_000), h)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_CHILD.value)


def test_duplicate_estimated_payment_quarter_rejected(api):
    """PRD §3.4: "with at most one payment per quarter per return (a second payment for a
    quarter already recorded on the same return is rejected with `ERR_DUPLICATE_CHILD`,
    HTTP 409)".

    Design: Corner/validations/duplicate_estimated_payment_quarter_rejected
    """
    taxpayer, tax_return, _doc = FIX.setup_draft_return_with_w2(federal_withholding_cents=0)
    h = make_taxpayer_headers(taxpayer["id"])
    validate_success(api.create_estimated_tax_payment(
        create_estimated_tax_payment_payload(
            tax_return["id"], quarter="Q1", amount_cents=100_000,
            paid_on="2025-04-10T00:00:00Z",
            period_start="2025-01-01T00:00:00Z",
            period_end="2025-04-01T00:00:00Z"), h), 201)
    # Same quarter, non-overlapping period so duplicate-quarter is what fires.
    resp = api.create_estimated_tax_payment(
        create_estimated_tax_payment_payload(
            tax_return["id"], quarter="Q1", amount_cents=100_000,
            paid_on="2025-05-10T00:00:00Z",
            period_start="2025-04-01T00:00:00Z",
            period_end="2025-07-01T00:00:00Z"), h)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_CHILD.value)


def test_efile_twice_already_efiled(api):
    """PRD §3.6: "A return may not be transmitted twice while a non-`REJECTED`
    submission already exists for it — a second attempt is rejected with
    `ERR_ALREADY_EFILED` (HTTP 409)."

    Design: Corner/validations/efile_twice_already_efiled
    """
    from test_helpers import setup_transmitted_efile
    taxpayer, ret_after_efile, _efiling = setup_transmitted_efile()
    h = make_taxpayer_headers(taxpayer["id"])
    current = validate_success(api.get_tax_return(ret_after_efile["id"], h), 200)
    resp = api.efile_tax_return(
        ret_after_efile["id"], efile_payload(current["version"]), h)
    validate_error(resp, ApiErrorId.ERR_ALREADY_EFILED.value)


def test_existence_before_state_on_unknown_return_compute(api):
    """PRD §2.6: "A path that names a `TaxReturn`, `EFilingSubmission`, or
    `AmendedReturn` id that does not exist is rejected with `ERR_RETURN_NOT_FOUND` (HTTP
    404)."
    PRD §2.9: "Then existence of path-referenced resources (`ERR_RETURN_NOT_FOUND`),
    followed by existence of body foreign-key targets (`ERR_FK_NOT_FOUND`)."

    Design: Corner/validations/existence_before_state_on_compute_unknown_return
    """
    taxpayer = FIX.create_taxpayer(email="exist-before-state@example.com",
                                   full_name="VA6", filing_status="SINGLE")
    h = make_taxpayer_headers(taxpayer["id"])
    resp = api.compute_tax_return("22222222-2222-4222-8222-222222222222", h)
    validate_error(resp, ApiErrorId.ERR_RETURN_NOT_FOUND.value)


# =====================================================================
# Corner B / errors
# =====================================================================

def test_efile_stale_return_version_rejected(api):
    """PRD §2.8: "A transmission request must carry `expected_return_version` equal to
    the target return's current `version`. If a compute or any other writer has advanced
    the return's `version` since the client last read it — which may have changed
    `balance_due_cents`, making the snapshot the e-file would freeze stale — the
    transmission is rejected with `ERR_STALE_RETURN_VERSION` (HTTP 412)."

    Design: Corner/errors/error_stale_return_version_efile
    """
    from test_helpers import setup_computed_return
    taxpayer, computed = setup_computed_return()
    h = make_taxpayer_headers(taxpayer["id"])
    v_stale = computed["version"]
    # Recompute once more so the held version is now stale.
    validate_success(api.compute_tax_return(computed["id"], h), 200)
    resp = api.efile_tax_return(computed["id"], efile_payload(v_stale), h)
    validate_error(resp, ApiErrorId.ERR_STALE_RETURN_VERSION.value)
