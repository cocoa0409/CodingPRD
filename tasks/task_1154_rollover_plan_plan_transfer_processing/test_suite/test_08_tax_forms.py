"""Tax forms: provisional vs corrected 1099-R variants, finalize/correction
lifecycle with OCC, year assignment, and role exclusivity."""
from test_helpers import (
    ApiErrorId,
    api_client,
    build_issued_direct_case,
    build_issued_indirect_case,
    create_redeposit_payload,
    get_case,
    list_case_tax_forms,
    list_participant_5498s,
    make_operations_headers,
    make_processor_headers,
    make_tax_officer_headers,
    set_logical_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

TAX = make_tax_officer_headers()
PROC2 = make_processor_headers("proc-2")


def _only_1099r(case_id):
    forms, meta = list_case_tax_forms(case_id, form_type="FORM_1099_R")
    assert meta["total_count"] == 1, f"exactly one 1099-R per case, got {meta['total_count']}"
    return forms[0]


def test_1099r_provisional_variant_at_issuance(api):
    """PRD §3.7: "An `INDIRECT_ROLLOVER_OUT` issuance drafts the *provisional*
    1099-R: `gross_distribution_cents` equal to the case gross,
    `federal_withholding_cents` equal to the withheld amount, and
    `taxable_amount_cents` equal to the full `taxable_cents`, on the
    conservative assumption that nothing will be redeposited."
    PRD §3.10: "a `distribution_code`: `CODE_G` for a direct rollover (taxable
    zero); otherwise `CODE_7` when the participant's `age_months` at the event
    is at least 714, or `CODE_1` when younger."

    Design: Difficulty/dual_variant_calc/tax_form_1099r_provisional_vs_corrected_after_shortfall
    """
    bundle = build_issued_indirect_case(clock="2026-06-01T00:00:00Z", receiving_plan_type="IRA")
    form = _only_1099r(bundle["case"]["id"])
    # Full-vested indirect: gross 10,800,000; basis 1,300,000; taxable 9,500,000;
    # withholding 1,900,000. The participant (dob 1960-06-15) is >= 714 months at
    # the 2026-06-01 event, so the code is CODE_7.
    assert form["status"] == "DRAFT"
    assert form["gross_distribution_cents"] == 10800000
    assert form["federal_withholding_cents"] == 1900000
    assert form["taxable_amount_cents"] == 9500000, (
        f"provisional variant reports the full taxable_cents, got {form['taxable_amount_cents']}"
    )
    assert form["distribution_code"] == "CODE_7"
    assert form["tax_year"] == 2026


def test_1099r_corrected_variant_after_incomplete_sweep(api):
    """PRD §3.10: "The **corrected** variant applies once the 60-day outcome is
    known — whether the case completed or the sweep marked it `INCOMPLETE`:
    credited dollars are applied to the taxable portion first, so the corrected
    taxable is the original `taxable_cents` minus the smaller of
    `credited_total_cents` and `taxable_cents`."
    PRD §3.11: "Second, it catches lapsed windows: every indirect case whose
    clock date has passed its `rollover_deadline_date` with
    `credited_total_cents` still below `gross_cents` transitions
    `AWAITING_REDEPOSIT → INCOMPLETE`, cascading `SKIPPED` onto its remaining
    `SCHEDULED` notices and recomputing the 1099-R to the corrected variant"

    Design: Difficulty/dual_variant_calc/tax_form_1099r_provisional_vs_corrected_after_shortfall
    """
    bundle = build_issued_indirect_case(clock="2026-06-01T00:00:00Z", receiving_plan_type="IRA")
    case_id = bundle["case"]["id"]
    form = _only_1099r(case_id)
    assert form["taxable_amount_cents"] == 9500000

    # Net-only redeposit: 8,900,000 credited within the window.
    deposit = validate_success(api_client.create_redeposit(
        create_redeposit_payload(
            bundle["receiving_account"]["id"], 8900000, "2026-07-01",
            rollover_case_id=case_id,
        ),
        make_processor_headers("proc-1"),
    ), expected_status=201)
    validate_success(api_client.credit_redeposit(deposit["id"], PROC2))

    # Clock passes the 2026-07-31 deadline with 8.9M < 10.8M credited.
    set_logical_clock("2026-08-01T00:00:00Z")
    sweep = validate_success(api_client.run_daily_sweep(make_operations_headers()))
    assert sweep["cases_marked_incomplete"] == 1, (
        f"exactly one lapsed case must be marked INCOMPLETE, got {sweep}"
    )

    case = get_case(case_id)
    assert case["status"] == "INCOMPLETE", f"case must be INCOMPLETE, got {case['status']}"

    resp = api_client.get_tax_form(form["id"], TAX)
    corrected = validate_success(resp)
    # corrected taxable = 9,500,000 - min(8,900,000, 9,500,000) = 600,000.
    assert corrected["taxable_amount_cents"] == 600000, (
        f"corrected variant must report 600000, got {corrected['taxable_amount_cents']}"
    )
    assert corrected["gross_distribution_cents"] == 10800000, "gross is unchanged by correction"
    assert corrected["federal_withholding_cents"] == 1900000, "withholding is unchanged by correction"


def test_taxform_finalize_then_finalize_rejected(api):
    """PRD §3.10: "A `TaxReportingOfficer` finalizes a `DRAFT` form, moving it
    to `ISSUED` and locking its amounts — draft recomputations stop applying
    from that moment; finalizing anything but a `DRAFT` is
    `ERR_TAX_FORM_INVALID_STATE`."
    PRD §3.7: "A `DIRECT_ROLLOVER_OUT` issuance instead drafts its tax form
    immediately: a `DRAFT` 1099-R with `distribution_code` `CODE_G` and
    `taxable_amount_cents` of zero, reflecting a non-taxable trustee-to-trustee
    movement."

    Design: Corner/state_machines/taxform_finalize_then_finalize_rejected
    """
    bundle = build_issued_direct_case(
        balances=[{"source_type": "PRE_TAX", "balance_cents": 500000,
                   "basis_cents": 0, "vested_pct": 100}],
        clock="2026-06-01T00:00:00Z",
    )
    form = _only_1099r(bundle["case"]["id"])
    assert form["distribution_code"] == "CODE_G"
    assert form["taxable_amount_cents"] == 0

    finalized = validate_success(api_client.finalize_tax_form(form["id"], TAX))
    assert finalized["status"] == "ISSUED"

    resp = api_client.finalize_tax_form(form["id"], TAX)
    validate_error(resp, ApiErrorId.ERR_TAX_FORM_INVALID_STATE, expected_status=409)


def test_taxform_correction_supersedes_chain(api):
    """PRD §3.10: "The correction creates the same supersession chain as the
    automatic one: old row `SUPERSEDED` (its `version` incrementing by 1), new
    row `ISSUED` at the next `revision` with `supersedes_id` set. A form's
    `revision` is zero for the original and increments per correction."
    PRD §4: the tax-form list endpoint is "filterable by participant, case,
    loan, supersedes, tax year, form type, status".

    Design: Corner/endpoints/taxform_correction_supersedes_chain
    """
    bundle = build_issued_direct_case(
        balances=[{"source_type": "PRE_TAX", "balance_cents": 500000,
                   "basis_cents": 0, "vested_pct": 100}],
        clock="2026-06-01T00:00:00Z",
    )
    form = _only_1099r(bundle["case"]["id"])
    finalized = validate_success(api_client.finalize_tax_form(form["id"], TAX))
    current_version = finalized["version"]

    correction = validate_success(api_client.correct_tax_form(
        form["id"],
        {"expected_tax_form_version": current_version,
         "taxable_amount_cents": 0, "distribution_code": "CODE_G"},
        TAX,
    ), expected_status=201)
    assert correction["revision"] == 1, f"correction is revision 1, got {correction['revision']}"
    assert correction["supersedes_id"] == form["id"], "supersedes_id points at the replaced row"
    assert correction["status"] == "ISSUED"

    old = validate_success(api_client.get_tax_form(form["id"], TAX))
    assert old["status"] == "SUPERSEDED", f"old row must be SUPERSEDED, got {old['status']}"

    resp = api_client.list_tax_forms(TAX, params={"supersedes_id": form["id"]})
    chain, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    assert chain[0]["id"] == correction["id"], "the supersedes filter retrieves the correction chain"


def test_occ_taxform_correction_stale_version(api):
    """PRD §2.8: "**Filing a tax-form correction.** A correction request must
    carry `expected_tax_form_version` matching the form's current `version`. A
    correction supersedes the prior revision, so a writer holding a stale
    version must not silently supersede a revision it never saw; the mismatch is
    rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/complexity_layers/occ_taxform_correction_stale_version
    """
    bundle = build_issued_direct_case(
        balances=[{"source_type": "PRE_TAX", "balance_cents": 500000,
                   "basis_cents": 0, "vested_pct": 100}],
        clock="2026-06-01T00:00:00Z",
    )
    form = _only_1099r(bundle["case"]["id"])
    finalized = validate_success(api_client.finalize_tax_form(form["id"], TAX))
    current_version = finalized["version"]

    resp = api_client.correct_tax_form(
        form["id"],
        {"expected_tax_form_version": current_version - 1, "taxable_amount_cents": 0},
        TAX,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    correction = validate_success(api_client.correct_tax_form(
        form["id"],
        {"expected_tax_form_version": current_version, "taxable_amount_cents": 0},
        TAX,
    ), expected_status=201)
    assert correction["revision"] == 1
    assert correction["supersedes_id"] == form["id"]


def test_processor_cannot_finalize_tax_form(api):
    """PRD §2.1: "A request whose role is recognized but not permitted for the
    target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403); the
    full role-to-endpoint mapping is given in §4."
    PRD §4: the tax-form finalize endpoint is authorized for
    `TaxReportingOfficer` only.

    Design: Corner/rbac/processor_cannot_finalize_tax_form
    """
    bundle = build_issued_direct_case(
        balances=[{"source_type": "PRE_TAX", "balance_cents": 500000,
                   "basis_cents": 0, "vested_pct": 100}],
        clock="2026-06-01T00:00:00Z",
    )
    form = _only_1099r(bundle["case"]["id"])

    resp = api_client.finalize_tax_form(form["id"], make_processor_headers("proc-9"))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)

    still = validate_success(api_client.get_tax_form(form["id"], TAX))
    assert still["status"] == "DRAFT", "unauthorized finalize must not mutate the form"


def test_tax_year_spanning_indirect_forms(api):
    """PRD §3.10: "Its `tax_year` is the issue year." (FORM_1099_R)
    PRD §3.10: "Its `tax_year` is the credit year — which may span a year-end
    boundary for indirect rollovers disbursed late in December and redeposited
    in January."
    PRD §3.7: "For indirect cases, `rollover_deadline_date` is computed as
    exactly 60 calendar days after `disbursement_issued_date`."

    Design: Corner/calculations/tax_year_spanning_indirect_forms
    """
    bundle = build_issued_indirect_case(
        balances=[{"source_type": "PRE_TAX", "balance_cents": 500000,
                   "basis_cents": 0, "vested_pct": 100}],
        clock="2026-12-15T00:00:00Z",
        receiving_plan_type="IRA",
    )
    case_id = bundle["case"]["id"]
    case = get_case(case_id)
    # 2026-12-15 + 60 calendar days == 2027-02-13.
    assert case["rollover_deadline_date"] == "2027-02-13", (
        f"deadline must span the year boundary, got {case['rollover_deadline_date']}"
    )

    set_logical_clock("2027-01-10T00:00:00Z")
    deposit = validate_success(api_client.create_redeposit(
        create_redeposit_payload(
            bundle["receiving_account"]["id"], 500000, "2027-01-10",
            rollover_case_id=case_id,
        ),
        make_processor_headers("proc-1"),
    ), expected_status=201)
    credited = validate_success(api_client.credit_redeposit(deposit["id"], PROC2))
    assert credited["status"] == "CREDITED"
    assert get_case(case_id)["status"] == "COMPLETED"

    form = _only_1099r(case_id)
    assert form["tax_year"] == 2026, f"1099-R takes the issue year, got {form['tax_year']}"

    f5498, meta5498 = list_participant_5498s(bundle["participant"]["id"])
    assert meta5498["total_count"] == 1
    assert f5498[0]["tax_year"] == 2027, f"5498 takes the credit year, got {f5498[0]['tax_year']}"
    assert f5498[0]["rollover_contribution_cents"] == 500000
