"""Tier II filing lifecycle, fee assessment, the outstanding-fee ledger, and the SDS repository."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    create_sds_payload,
    make_regulator_headers,
    make_facility_operator_headers,
    register_facility,
    create_chemical,
    upload_sds,
    get_facility,
    setup_facility_with_draft_filing,
    setup_submitted_filing,
    setup_under_review_filing,
    create_draft_filing,
    declare_inventory,
    api_client,
)


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc / filing_provisional_vs_assessed_fee
# ---------------------------------------------------------------------------
def test_provisional_fee_is_flat_per_declared_row(api):
    """PRD §3.4: "a **provisional** fee estimate, `provisional_fee_cents`, is
    computed as a base fee of 5,000 cents plus 2,000 cents for each of the
    facility's `ACTIVE` inventory rows for that reporting year."

    Design: Difficulty/dual_variant_calc/filing_provisional_vs_assessed_fee
    """
    ctx = setup_facility_with_draft_filing()
    # base 5000 + 1 declared row * 2000 = 7000.
    assert ctx["filing"]["provisional_fee_cents"] == 7000


def test_assessed_fee_diverges_from_provisional_on_submit(api):
    """PRD §3.4: "The subtotal is the base fee of 5,000 cents plus the per-chemical
    component plus the EHS surcharge."
    PRD §3.4: "An EHS surcharge of 5,000 cents is then added for each EHS-reportable
    chemical, that is E multiplied by 5,000 cents."

    Design: Difficulty/dual_variant_calc/filing_provisional_vs_assessed_fee
    """
    ctx = setup_facility_with_draft_filing()
    fac_id = ctx["facility"]["id"]
    resp = api.submit_tier_ii_filing(ctx["filing"]["id"], make_facility_operator_headers(fac_id))
    data = validate_success(resp, expected_status=200)
    # N=1 reportable -> per=0; E=1 EHS -> surcharge 5000; subtotal 5000+0+5000=10000; on time.
    assert data["assessed_fee_cents"] == 10000
    assert data["assessed_fee_cents"] != ctx["filing"]["provisional_fee_cents"]


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / filing_revision_cycle_back_edge
# ---------------------------------------------------------------------------
def test_returned_filing_resubmits_to_submitted(api):
    """PRD §3.4: "Submitting a filing (which a `FacilityOperator` also performs for
    its own facility, and which is the same action whether the filing is a first
    submission from `DRAFT` or a resubmission from `RETURNED_FOR_REVISION`)"
    PRD §3.4: "A `RETURN` decision moves a filing from `UNDER_REVIEW` to
    `RETURNED_FOR_REVISION` (valid only from `UNDER_REVIEW`, else
    `ERR_FILING_NOT_REVIEWABLE`); as a compensating action it resets
    `assessed_fee_cents` back to 0 and increments `revision_count` by 1."

    Design: Difficulty/non_linear_state_machine/filing_revision_cycle_back_edge
    """
    ctx = setup_under_review_filing()
    fac_id = ctx["facility"]["id"]
    fil_id = ctx["filing"]["id"]
    validate_success(api.review_tier_ii_filing(fil_id, {"decision": "RETURN"}, make_regulator_headers()))
    resp = api.submit_tier_ii_filing(fil_id, make_facility_operator_headers(fac_id))
    data = validate_success(resp, expected_status=200)
    assert data["status"] == "SUBMITTED"


def test_revision_count_incremented_after_return(api):
    """PRD §3.4: "A `RETURN` decision moves a filing from `UNDER_REVIEW` to
    `RETURNED_FOR_REVISION` (valid only from `UNDER_REVIEW`, else
    `ERR_FILING_NOT_REVIEWABLE`); as a compensating action it resets
    `assessed_fee_cents` back to 0 and increments `revision_count` by 1."

    Design: Difficulty/non_linear_state_machine/filing_revision_cycle_back_edge
    """
    ctx = setup_under_review_filing()
    fac_id = ctx["facility"]["id"]
    fil_id = ctx["filing"]["id"]
    validate_success(api.review_tier_ii_filing(fil_id, {"decision": "RETURN"}, make_regulator_headers()))
    resp = api.submit_tier_ii_filing(fil_id, make_facility_operator_headers(fac_id))
    data = validate_success(resp, expected_status=200)
    assert data["revision_count"] == 1


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / filing_submit_empty_reportable_set_boundary
# ---------------------------------------------------------------------------
def test_submit_with_no_inventory_rejected_empty_reportable_set(api):
    """PRD §3.4: "Third, there must be at least one reportable inventory row for the
    `reporting_year`; an empty reportable set is rejected with
    `ERR_NO_REPORTABLE_CHEMICALS` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/filing_submit_empty_reportable_set_boundary
    """
    facility = register_facility()
    fac_id = facility["id"]
    filing = create_draft_filing(fac_id, reporting_year=2025)
    resp = api.submit_tier_ii_filing(filing["id"], make_facility_operator_headers(fac_id))
    validate_error(resp, ApiErrorId.ERR_NO_REPORTABLE_CHEMICALS.value)


def test_submit_with_only_below_threshold_inventory_rejected(api):
    """PRD §3.4: "Third, there must be at least one reportable inventory row for the
    `reporting_year`; an empty reportable set is rejected with
    `ERR_NO_REPORTABLE_CHEMICALS` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/filing_submit_empty_reportable_set_boundary
    """
    facility = register_facility()
    fac_id = facility["id"]
    chemical = create_chemical(is_ehs=False, rq_lbs=1000, hazard_weight=0.1)
    # 100 lbs < 10,000 non-EHS threshold -> not reportable, so reportable set is empty.
    declare_inventory(
        fac_id, chemical["id"], reporting_year=2025, max_daily_amount_lbs=100,
        average_daily_amount_lbs=50, days_on_site=10, storage_type="DRUM",
    )
    filing = create_draft_filing(fac_id, reporting_year=2025)
    resp = api.submit_tier_ii_filing(filing["id"], make_facility_operator_headers(fac_id))
    validate_error(resp, ApiErrorId.ERR_NO_REPORTABLE_CHEMICALS.value)


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant / fee_ledger_submit_return_conserves_outstanding
# ---------------------------------------------------------------------------
def test_return_zeroes_assessed_fee_and_bumps_revision(api):
    """PRD §3.4: "as a compensating action it resets `assessed_fee_cents` back to 0
    and increments `revision_count` by 1."

    Design: Difficulty/compensating_invariant/fee_ledger_submit_return_conserves_outstanding
    """
    ctx = setup_under_review_filing()
    fil_id = ctx["filing"]["id"]
    resp = api.review_tier_ii_filing(fil_id, {"decision": "RETURN"}, make_regulator_headers())
    data = validate_success(resp, expected_status=200)
    assert data["assessed_fee_cents"] == 0
    assert data["revision_count"] == 1


def test_submit_then_return_restores_outstanding_total(api):
    """PRD §2.8: "submitting a filing adds its assessed-minus-paid amount, and
    returning a filing both removes its contribution and zeroes its assessed fee, so
    that a submit-then-return round trip with no intervening payment restores the
    facility's outstanding total exactly."

    Design: Difficulty/compensating_invariant/fee_ledger_submit_return_conserves_outstanding
    """
    ctx = setup_under_review_filing()
    fac_id = ctx["facility"]["id"]
    fil_id = ctx["filing"]["id"]
    validate_success(api.review_tier_ii_filing(fil_id, {"decision": "RETURN"}, make_regulator_headers()))
    facility_read = get_facility(fac_id)
    assert facility_read["total_outstanding_fee_cents"] == 0


# ---------------------------------------------------------------------------
# Corner: state_machines / filing_review_on_draft_returns_not_reviewable
# ---------------------------------------------------------------------------
def test_review_begin_on_draft_rejected(api):
    """PRD §3.4: "A `BEGIN` decision moves a filing from `SUBMITTED` to
    `UNDER_REVIEW` and has no further effect; it is valid only when the filing is
    `SUBMITTED`, otherwise `ERR_FILING_NOT_REVIEWABLE`."

    Design: Corner/state_machines/filing_review_on_draft_returns_not_reviewable
    """
    facility = register_facility()
    filing = create_draft_filing(facility["id"], reporting_year=2025)
    resp = api.review_tier_ii_filing(filing["id"], {"decision": "BEGIN"}, make_regulator_headers())
    validate_error(resp, ApiErrorId.ERR_FILING_NOT_REVIEWABLE.value)


# ---------------------------------------------------------------------------
# Corner: validations / filing_submit_without_active_sds_rejected
# ---------------------------------------------------------------------------
def test_submit_without_active_sds_rejected(api):
    """PRD §3.4: "Second, every chemical that is reportable for the `reporting_year`
    must have an `ACTIVE` SDS on file at the facility; a missing sheet rejects the
    submission with `ERR_MISSING_SDS`."

    Design: Corner/validations/filing_submit_without_active_sds_rejected
    """
    ctx = setup_facility_with_draft_filing(with_sds=False)
    fac_id = ctx["facility"]["id"]
    resp = api.submit_tier_ii_filing(ctx["filing"]["id"], make_facility_operator_headers(fac_id))
    validate_error(resp, ApiErrorId.ERR_MISSING_SDS.value)


# ---------------------------------------------------------------------------
# Corner: validations / filing_accept_fee_unpaid_returns_402
# ---------------------------------------------------------------------------
def test_accept_with_unpaid_fee_rejected(api):
    """PRD §3.4: "An `ACCEPT` decision moves a filing from `UNDER_REVIEW` to the
    terminal `ACCEPTED` state; it requires the filing to be `UNDER_REVIEW` (else
    `ERR_FILING_NOT_REVIEWABLE`) and requires the fee to be fully paid —
    `fee_paid_cents` must be at least `assessed_fee_cents`, otherwise the acceptance
    is rejected with `ERR_FEE_UNPAID` (HTTP 402)."

    Design: Corner/validations/filing_accept_fee_unpaid_returns_402
    """
    ctx = setup_under_review_filing()
    resp = api.review_tier_ii_filing(ctx["filing"]["id"], {"decision": "ACCEPT"}, make_regulator_headers())
    validate_error(resp, ApiErrorId.ERR_FEE_UNPAID.value)


# ---------------------------------------------------------------------------
# Corner: calculations / filing_late_penalty_applied
# ---------------------------------------------------------------------------
def test_late_submission_applies_ten_percent_penalty(api):
    """PRD §3.4: "Finally, if the filing is late, a late penalty equal to the
    subtotal multiplied by 10 percent, rounded half up to a whole number of cents,
    is added; if the filing is on time the penalty is zero."
    PRD §3.4: "sets `is_late` to `true` exactly when `submitted_at` is strictly
    after the `deadline` (an instant exactly equal to the deadline is on time)."

    Design: Corner/calculations/filing_late_penalty_applied
    """
    from test_helpers import set_clock
    set_clock("2026-03-02T00:00:00Z")  # past the RY2025 deadline of 2026-03-01.
    ctx = setup_facility_with_draft_filing()
    fac_id = ctx["facility"]["id"]
    resp = api.submit_tier_ii_filing(ctx["filing"]["id"], make_facility_operator_headers(fac_id))
    data = validate_success(resp, expected_status=200)
    assert data["is_late"] is True
    # subtotal 10000 + round(10000 * 0.10) = 10000 + 1000 = 11000.
    assert data["assessed_fee_cents"] == 11000


# ---------------------------------------------------------------------------
# Corner: endpoints / filing_pay_reduces_outstanding
# ---------------------------------------------------------------------------
def test_payment_reduces_outstanding_balance(api):
    """PRD §3.4: "Between submission and acceptance a `FacilityOperator` records
    payments against its own facility's filing by supplying an `amount_cents`; each
    payment adds `amount_cents` to the filing's `fee_paid_cents` and reconciles the
    outstanding ledger."

    Design: Corner/endpoints/filing_pay_reduces_outstanding
    """
    ctx = setup_submitted_filing()
    fac_id = ctx["facility"]["id"]
    fil_id = ctx["filing"]["id"]
    resp = api.pay_tier_ii_filing(fil_id, {"amount_cents": 10000}, make_facility_operator_headers(fac_id))
    data = validate_success(resp, expected_status=200)
    assert data["fee_paid_cents"] == 10000
    facility_read = get_facility(fac_id)
    assert facility_read["total_outstanding_fee_cents"] == 0


# ---------------------------------------------------------------------------
# Corner: state_machines / sds_supersede_prior_active_sheet
# ---------------------------------------------------------------------------
def test_new_sds_supersedes_prior_active_sheet(api):
    """PRD §3.2: "if an earlier `ACTIVE` sheet already exists for the same
    `facility_id` and `chemical_id`, that prior sheet is flipped to `SUPERSEDED`, so
    that at most one active sheet exists per facility-and-chemical pair."

    Design: Corner/state_machines/sds_supersede_prior_active_sheet
    """
    facility = register_facility()
    fac_id = facility["id"]
    chemical = create_chemical(is_ehs=False, rq_lbs=1000, hazard_weight=0.1)
    sds1 = upload_sds(fac_id, chemical["id"], facility["version"], document_ref="sds://v1",
                      revision_date="2025-01-01T00:00:00Z")
    facility2 = get_facility(fac_id)
    sds2 = upload_sds(fac_id, chemical["id"], facility2["version"], document_ref="sds://v2",
                      revision_date="2025-06-01T00:00:00Z")
    sds1_read = validate_success(api.get_sds(sds1["id"], make_facility_operator_headers(fac_id)))
    assert sds1_read["status"] == "SUPERSEDED"
    assert sds2["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Corner: cross_cutting / sds_create_stale_facility_version_returns_412
# ---------------------------------------------------------------------------
def test_sds_create_with_stale_facility_version_rejected(api):
    """PRD §2.7: "An SDS upload request must carry an `expected_facility_version`
    field whose value equals the target facility's current `version`. If the
    facility's `version` has advanced since the client last observed it — meaning the
    client is operating on an out-of-date view of the repository — the upload is
    rejected with `ERR_STALE_FACILITY_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting/sds_create_stale_facility_version_returns_412
    """
    facility = register_facility()
    fac_id = facility["id"]
    stale_version = facility["version"]  # version 1
    chemical = create_chemical(is_ehs=True, tpq_lbs=500, rq_lbs=100, hazard_weight=0.3, physical_state="GAS")
    upload_sds(fac_id, chemical["id"], stale_version, document_ref="sds://v1",
               revision_date="2025-01-01T00:00:00Z")  # advances facility version to 2
    payload = create_sds_payload(fac_id, chemical["id"], stale_version, document_ref="sds://v2",
                                 revision_date="2025-06-01T00:00:00Z")
    resp = api.create_sds(payload, make_facility_operator_headers(fac_id))
    validate_error(resp, ApiErrorId.ERR_STALE_FACILITY_VERSION.value)


# ---------------------------------------------------------------------------
# Corner: cross_cutting / sds_create_increments_facility_version
# ---------------------------------------------------------------------------
def test_sds_create_increments_facility_version(api):
    """PRD §3.2: "Because superseding rewrites the facility's SDS repository, a
    successful upload increments the facility's `version` by 1."

    Design: Corner/cross_cutting/sds_create_increments_facility_version
    """
    facility = register_facility()
    fac_id = facility["id"]
    assert facility["version"] == 1
    chemical = create_chemical(is_ehs=True, tpq_lbs=500, rq_lbs=100, hazard_weight=0.3, physical_state="GAS")
    upload_sds(fac_id, chemical["id"], facility["version"], document_ref="sds://v1",
               revision_date="2025-01-01T00:00:00Z")
    facility_read = get_facility(fac_id)
    assert facility_read["version"] == 2
