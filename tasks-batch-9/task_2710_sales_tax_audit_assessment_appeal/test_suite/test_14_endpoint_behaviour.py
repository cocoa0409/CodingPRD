"""Computed reads, bulk runs, in-place recomputes and the parent-scoped listings."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    base_expiry_for,
    create_exemption_certificate_payload,
    create_industry_project,
    cure_certificate,
    draft_assessment,
    draft_waiver,
    draw_sample_unit,
    execute_waiver,
    file_certificate,
    issue_assessment,
    liability_preview,
    list_adjustments,
    list_leads,
    load_information_return,
    pay_arrangement,
    read_agreement,
    read_assessment,
    read_audit,
    read_industry_project,
    read_purchase,
    read_sample_unit,
    read_taxpayer,
    reclassify_purchase,
    reclassify_use_tax_purchase_payload,
    record_purchase,
    refer_to_collections,
    register_taxpayer,
    request_installment_plan,
    request_offer_in_compromise,
    review_certificate,
    run_selection,
    set_clock_date,
    setup_agreed_methodology,
    setup_approved_installment_plan,
    setup_draft_assessment,
    setup_issued_assessment,
    setup_review_complete_audit,
    validate_error,
    validate_paginated,
    validate_success,
)

ANALYST = TEST_USERS["selection_analyst_headers"]
AUDITOR = TEST_USERS["field_auditor_headers"]
SUPERVISOR = TEST_USERS["audit_supervisor_headers"]
COLLECTIONS = TEST_USERS["collections_agent_headers"]

SMALL_BALANCE_TAX_CENTS = 4_762
PREVIEW_FIELDS = (
    "tax_deficiency_cents",
    "penalty_rate_bp",
    "penalty_cents",
    "interest_days",
    "interest_cents",
    "provisional_total_due_cents",
    "penalty_waived_small_balance",
    "total_due_cents",
)


def test_the_liability_preview_returns_the_numbers_the_draft_would_store():
    """The preview runs the same rollup, writes nothing, and moves no version.

    PRD 3.6: "A supervisor or a `FieldAuditor` may also ask what an audit would
    assess right now without creating anything. That computed read returns
    `tax_deficiency_cents`, `penalty_rate_bp`, `penalty_cents`, `interest_days`,
    `interest_cents`, `provisional_total_due_cents`, `penalty_waived_small_balance`
    and `total_due_cents` from the same five-step rollup, together with the audit's
    current `projection_status` so the caller can see whether the preview rests on
    current findings. It creates no assessment, writes nothing and — unlike drafting
    — is not blocked by a `STALE` projection; the returned `projection_status` is the
    caller's warning instead."
    PRD 3.6: "If that provisional total is less than or equal to 5,000 cents — the
    comparison is inclusive, so a provisional total of exactly 5,000 cents is waived —
    then `penalty_waived_small_balance` becomes true, `penalty_cents` is set to 0, and
    `interest_cents` is recomputed from scratch on the bare tax"

    Design: Corner/endpoints/liability_preview_agrees_with_the_assessment_it_would_create
    """
    ctx = setup_review_complete_audit(tax_deficiency_cents=SMALL_BALANCE_TAX_CENTS)
    audit_id = ctx["audit"]["id"]
    set_clock_date(ctx["audit"]["scope_period_end"])
    version_before = read_audit(audit_id)["version"]

    preview = liability_preview(audit_id)
    assert preview["tax_deficiency_cents"] == SMALL_BALANCE_TAX_CENTS
    assert preview["penalty_rate_bp"] == 500
    assert preview["penalty_cents"] == 0
    assert preview["interest_days"] == 0
    assert preview["interest_cents"] == 0
    assert preview["provisional_total_due_cents"] == 5_000
    assert preview["penalty_waived_small_balance"] is True
    assert preview["total_due_cents"] == SMALL_BALANCE_TAX_CENTS
    assert preview["projection_status"] == "CURRENT"

    _, meta = validate_paginated(
        api_client.list_assessments(SUPERVISOR, params={"audit_id": audit_id})
    )
    assert meta["total_count"] == 0

    assessment = draft_assessment(audit_id)
    for field in PREVIEW_FIELDS:
        assert assessment[field] == preview[field], field
    assert assessment["balance_due_cents"] == SMALL_BALANCE_TAX_CENTS
    assert assessment["status"] == "DRAFT"
    assert assessment["collection_status"] == "NOT_DUE"

    audit = read_audit(audit_id)
    assert audit["version"] == version_before
    assert audit["status"] == "REVIEW_COMPLETE"


def test_the_second_installment_completes_the_plan_and_satisfies_the_notice():
    """The first payment leaves the plan running; the second closes the whole matter.

    PRD 3.9: "A payment increments the arrangement's `amount_paid_cents` and
    `payments_made_count`, and increments the assessment's own `amount_paid_cents`,
    which lowers `balance_due_cents`. This is the only route by which the assessment's
    `amount_paid_cents` grows, which is why it can never double-count a manually
    posted `PAYMENT` ledger row."
    PRD 3.9: "An `INSTALLMENT_PLAN` is fully performed when the assessment's
    `balance_due_cents` has reached 0."
    PRD 3.9: "Either way the arrangement moves from `APPROVED` to the terminal
    `COMPLETED`, the assessment's `collection_status` becomes `SATISFIED`, every other
    arrangement of that assessment still in `REQUESTED` or `APPROVED` also moves to
    `COMPLETED`, and the taxpayer's `compliance_status` is recomputed to `COMPLIANT` —
    but only when the taxpayer has no other assessment whose `collection_status` is
    `REFERRED`, since one settled liability does not clear a delinquency elsewhere."

    Design: Corner/endpoints/payments_walk_the_plan_to_completion_and_satisfy_the_notice
    """
    ctx = setup_approved_installment_plan(
        tax_deficiency_cents=SMALL_BALANCE_TAX_CENTS,
        monthly_installment_cents=2_381,
        term_months=2,
    )
    plan_id = ctx["arrangement"]["id"]
    assessment_id = ctx["assessment"]["id"]
    assert ctx["assessment"]["balance_due_cents"] == SMALL_BALANCE_TAX_CENTS

    first = pay_arrangement(plan_id, 2_381)
    assert first["status"] == "APPROVED"
    assert first["amount_paid_cents"] == 2_381
    assert first["payments_made_count"] == 1
    midway = read_assessment(assessment_id)
    assert midway["amount_paid_cents"] == 2_381
    assert midway["balance_due_cents"] == 2_381
    assert midway["collection_status"] == "ARRANGED"

    second = pay_arrangement(plan_id, 2_381)
    assert second["status"] == "COMPLETED"
    assert second["amount_paid_cents"] == SMALL_BALANCE_TAX_CENTS
    assert second["payments_made_count"] == 2
    settled = read_assessment(assessment_id)
    assert settled["amount_paid_cents"] == SMALL_BALANCE_TAX_CENTS
    assert settled["balance_due_cents"] == 0
    assert settled["collection_status"] == "SATISFIED"
    assert read_taxpayer(ctx["taxpayer"]["id"])["compliance_status"] == "COMPLIANT"

    # Arrangement payments are not ledger rows, so nothing was posted.
    assert list_adjustments(assessment_id=assessment_id) == []


def test_referral_charges_the_statutory_fee_as_a_negative_credit():
    """The fee raises the balance, and the conserved-money identity still closes.

    PRD 3.9: "Second, caused by the first, a `SYSTEM` adjustment of kind
    `COLLECTION_FEE` is posted whose `amount_cents` is the negative of
    `balance_due_cents` multiplied by the collection-fee rate of 1,000 basis points,
    divided by 10,000 and rounded half up — ten percent of the balance at the moment
    of referral, charged as a negative credit so that it raises `balance_due_cents`."
    PRD 3.7: "The conserved-money invariant closes the system: after every mutation,
    `balance_due_cents` plus `total_adjustments_cents` plus `amount_paid_cents` equals
    `total_due_cents`."
    PRD 3.9: "Third, caused by the second, the taxpayer's `compliance_status` becomes
    `DELINQUENT`, which is the same flag that later caps any penalty abatement at 50
    percent and that raises the taxpayer's screening risk score."

    Design: Corner/endpoints/collection_referral_posts_the_statutory_fee_and_raises_the_balance
    """
    ctx = setup_issued_assessment(tax_deficiency_cents=SMALL_BALANCE_TAX_CENTS)
    assessment_id = ctx["assessment"]["id"]

    referred = refer_to_collections(assessment_id)
    assert referred["collection_status"] == "REFERRED"
    assert referred["status"] == "ISSUED"

    fees = list_adjustments(assessment_id=assessment_id, kind="COLLECTION_FEE")
    assert len(fees) == 1
    assert fees[0]["amount_cents"] == -476
    assert fees[0]["source"] == "SYSTEM"
    assert fees[0]["status"] == "POSTED"

    assessment = read_assessment(assessment_id)
    assert assessment["total_adjustments_cents"] == -476
    assert assessment["balance_due_cents"] == 5_238
    assert assessment["total_due_cents"] == SMALL_BALANCE_TAX_CENTS
    assert assessment["amount_paid_cents"] == 0
    assert (
        assessment["balance_due_cents"]
        + assessment["total_adjustments_cents"]
        + assessment["amount_paid_cents"]
        == assessment["total_due_cents"]
    )
    assert read_taxpayer(ctx["taxpayer"]["id"])["compliance_status"] == "DELINQUENT"


def _certificates(**params):
    return validate_paginated(
        api_client.list_exemption_certificates(AUDITOR, params=params or None)
    )


def test_the_optional_certificate_link_must_resolve_and_then_becomes_filterable():
    """A ghost sampled invoice is a body foreign key 404; a real one is an association.

    PRD 2.8: "6. **Body foreign keys.** Every foreign key supplied in the body
    resolves to an existing record, producing that entity's 404 from the same
    catalogue as tier 3. Applies to every write endpoint whose body carries a foreign
    key."
    PRD 3.5: "The filing may also name `sample_unit_id`, the sampled invoice this
    certificate supports; when that link is present a rejection flows into the
    population through the linked unit, and when it is absent a rejection is assessed
    directly."
    PRD 2.3: "Beyond pagination, list endpoints accept filter parameters named exactly
    after the field they filter on, and a filter narrows the result set to records
    whose field equals the supplied value."

    Design: Corner/endpoints/certificate_links_to_a_sample_unit_only_when_that_unit_exists
    """
    ctx = setup_agreed_methodology()
    audit_id = ctx["audit"]["id"]
    unit = draw_sample_unit(
        ctx["agreement"]["id"],
        invoice_reference="RT-300",
        invoice_amount_cents=900_000,
        exempt_sale_amount_cents=400_000,
        error_class="NO_ERROR",
    )

    validate_error(
        api_client.create_exemption_certificate(
            create_exemption_certificate_payload(
                audit_id,
                purchaser_name="Ghost Resale Co",
                covered_sale_amount_cents=400_000,
                sample_unit_id=NON_EXISTENT_UUID,
            ),
            AUDITOR,
        ),
        ApiErrorId.ERR_SAMPLE_UNIT_NOT_FOUND.value,
        404,
    )

    linked = validate_success(
        api_client.create_exemption_certificate(
            create_exemption_certificate_payload(
                audit_id,
                purchaser_name="Delta Resale Co",
                covered_sale_amount_cents=400_000,
                sample_unit_id=unit["id"],
            ),
            AUDITOR,
        ),
        201,
    )
    assert linked["sample_unit_id"] == unit["id"]
    assert linked["status"] == "ON_FILE"
    assert linked["good_faith_accepted"] is True

    unlinked = file_certificate(
        audit_id,
        purchaser_name="Orchard Farms LLC",
        claimed_exemption_type="AGRICULTURAL",
        covered_sale_amount_cents=200_000,
    )
    assert unlinked["sample_unit_id"] is None

    by_unit, unit_meta = _certificates(sample_unit_id=unit["id"])
    assert unit_meta["total_count"] == 1
    assert [row["id"] for row in by_unit] == [linked["id"]]

    by_audit, audit_meta = _certificates(audit_id=audit_id)
    assert audit_meta["total_count"] == 2
    assert {row["id"] for row in by_audit} == {linked["id"], unlinked["id"]}


def test_a_replacement_draft_must_name_the_notice_it_supersedes():
    """Naming the live draft retires it in the same call and leaves one live notice.

    PRD 3.6: "An audit carries at most one live notice: if it already has an
    assessment whose `status` is `DRAFT`, `DRAFT_STALE` or `ISSUED`, a second draft is
    refused with `ERR_ASSESSMENT_ALREADY_OPEN` unless the request names that existing
    row in `supersedes_assessment_id`, in which case the named row moves to the
    terminal `SUPERSEDED` state and accepts no further recompute, issue, finalize,
    adjustment or proceeding."

    Design: Corner/endpoints/superseding_draft_replaces_the_open_notice_on_the_same_audit
    """
    ctx = setup_draft_assessment(tax_deficiency_cents=SMALL_BALANCE_TAX_CENTS)
    audit_id = ctx["audit"]["id"]
    first_id = ctx["assessment"]["id"]

    second = draft_assessment(audit_id, supersedes_assessment_id=first_id)
    assert second["status"] == "DRAFT"
    assert second["supersedes_assessment_id"] == first_id
    assert second["tax_deficiency_cents"] == SMALL_BALANCE_TAX_CENTS
    assert second["total_due_cents"] == SMALL_BALANCE_TAX_CENTS
    assert second["balance_due_cents"] == SMALL_BALANCE_TAX_CENTS

    retired = read_assessment(first_id)
    assert retired["status"] == "SUPERSEDED"
    assert retired["total_due_cents"] == SMALL_BALANCE_TAX_CENTS

    rows, meta = validate_paginated(
        api_client.list_assessments(
            SUPERVISOR, params={"audit_id": audit_id, "status": "SUPERSEDED"}
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [first_id]


GROCERY_NAICS = "445110"
GROCERY_ERROR_RATE_BP = 4_200


def _two_grocery_holders():
    """Harbor scores 314 on the full variant and Summit 172, in that created order."""
    harbor = register_taxpayer(
        legal_name="Harbor Foods LLC",
        industry_naics_code=GROCERY_NAICS,
        filing_frequency="MONTHLY",
        gross_receipts_annual_cents=250_000_000,
        delinquent_period_count=2,
    )
    load_information_return(
        harbor["id"],
        source_type="FEDERAL_1099K",
        reported_amount_cents=120_000_000,
        matched_return_amount_cents=90_000_000,
    )
    summit = register_taxpayer(
        legal_name="Summit Market Inc",
        industry_naics_code=GROCERY_NAICS,
        filing_frequency="QUARTERLY",
        gross_receipts_annual_cents=100_000_000,
        delinquent_period_count=1,
    )
    return harbor, summit


def _grocery_project(name, threshold):
    return create_industry_project(
        project_name=name,
        industry_naics_code=GROCERY_NAICS,
        industry_error_rate_bp=GROCERY_ERROR_RATE_BP,
        selection_mode="THRESHOLD",
        selection_threshold_score=threshold,
        selection_quota=5,
    )


def test_one_run_either_partitions_the_whole_industry_or_writes_nothing():
    """The refused run leaves no lead at all; the accepted one classifies both holders.

    PRD 3.1: "A `THRESHOLD` or `HYBRID` run that scored candidates but selected none
    of them, or that found no eligible holder at all, is rejected with
    `ERR_NO_ELIGIBLE_CANDIDATES` and leaves no leads behind at all — the run is
    all-or-nothing."
    PRD 3.1: "A lead the walk does not select moves `SCORED → NOT_SELECTED` when its
    `risk_score` is below `selection_threshold_score`, and otherwise stays in `SCORED`
    as a waitlist entry"
    PRD 3.1: "When the walk finishes, the project records `scored_lead_count`, sets
    `last_run_at` to the run's clock instant, and sets `last_cutoff_score` to the
    `risk_score` of the lowest-ranked lead the run moved to `SELECTED`, or to
    `selection_threshold_score` when the run selected nobody."

    Design: Corner/endpoints/selection_run_partitions_every_lead_or_creates_none
    """
    harbor, summit = _two_grocery_holders()
    strict = _grocery_project("Grocery 2026 strict", 400)
    permissive = _grocery_project("Grocery 2026 open", 200)

    validate_error(
        api_client.create_selection_run(strict["id"], ANALYST),
        ApiErrorId.ERR_NO_ELIGIBLE_CANDIDATES.value,
        422,
    )
    assert list_leads(industry_project_id=strict["id"]) == []
    refused = read_industry_project(strict["id"])
    assert refused["scored_lead_count"] == 0
    assert refused["selections_used"] == 0
    assert refused["last_run_at"] is None

    run_selection(permissive["id"])
    leads = {lead["taxpayer_id"]: lead for lead in list_leads(industry_project_id=permissive["id"])}
    assert len(leads) == 2
    assert leads[harbor["id"]]["risk_score"] == 314
    assert leads[harbor["id"]]["score_variant"] == "FULL"
    assert leads[harbor["id"]]["rank_position"] == 1
    assert leads[harbor["id"]]["status"] == "SELECTED"
    assert leads[summit["id"]]["risk_score"] == 172
    assert leads[summit["id"]]["rank_position"] == 2
    assert leads[summit["id"]]["status"] == "NOT_SELECTED"

    project = read_industry_project(permissive["id"])
    assert project["scored_lead_count"] == 2
    assert project["selections_used"] == 1
    assert project["selections_remaining"] == 4
    assert project["last_cutoff_score"] == 314


WAIVER_TARGET_DATE = "2030-06-29"


def test_every_mid_chain_row_reads_back_with_its_computed_fields():
    """Four single-row reads, each returning what the write derived, not just its inputs.

    PRD 3.2: "On success the audit moves `PLANNED → SCOPED`, and its
    `base_statute_expiry_date` is set to `scope_period_end` advanced by 1,095 calendar
    days — the three-year base limitation period — and fixed there permanently."
    PRD 3.3: "The agreement's `population_base_amount_cents` is the sum of the strata's
    `population_base_amount_cents` and is the denominator population for ratio
    estimation; its `population_unit_count` is the sum of the strata's
    `population_unit_count` and is the multiplier for mean-per-unit projection."
    PRD 3.4: "From these the system computes `error_amount_cents`, which is 0 for both
    `NO_ERROR` and `PENDING`, equals `declared_error_amount_cents` for
    `UNREPORTED_TAXABLE_SALE` and `RATE_ERROR`"
    PRD 3.2: "The draft lands in `DRAFTED`, contributes no days to anything, and
    carries `prior_expiry_date` null and `days_added` 0."

    Design: Corner/endpoints/mid_chain_rows_read_back_exactly_as_stored
    """
    ctx = setup_agreed_methodology()
    audit_id = ctx["audit"]["id"]
    unit = draw_sample_unit(
        ctx["agreement"]["id"],
        invoice_reference="RT-400",
        invoice_date="2026-05-20",
        invoice_amount_cents=250_000,
        error_class="UNREPORTED_TAXABLE_SALE",
        declared_error_amount_cents=15_625,
    )
    waiver = draft_waiver(audit_id, ctx["audit"]["scope_period_end"], WAIVER_TARGET_DATE)

    audit = read_audit(audit_id)
    assert audit["status"] == "FIELDWORK"
    assert audit["agreed_agreement_id"] == ctx["agreement"]["id"]
    assert audit["base_statute_expiry_date"] == base_expiry_for()
    assert audit["statute_status"] == "PROTECTED"
    assert audit["projection_status"] == "STALE"

    agreement = read_agreement(ctx["agreement"]["id"])
    assert agreement["methodology"] == "RATIO_ESTIMATION"
    assert agreement["round_number"] == 1
    assert agreement["status"] == "AGREED"
    assert agreement["population_base_amount_cents"] == 10_000_000
    assert agreement["population_unit_count"] == 100
    assert agreement["minimum_sample_size"] == 1

    stored_unit = read_sample_unit(unit["id"])
    assert stored_unit["stratum_index"] == 0
    assert stored_unit["error_class"] == "UNREPORTED_TAXABLE_SALE"
    assert stored_unit["error_amount_cents"] == 15_625
    assert stored_unit["redetermination_count"] == 0

    stored_waiver = validate_success(
        api_client.get_statute_waiver(waiver["id"], SUPERVISOR), 200
    )
    assert stored_waiver["status"] == "DRAFTED"
    assert stored_waiver["days_added"] == 0
    assert stored_waiver["prior_expiry_date"] is None
    assert stored_waiver["extended_to_date"] == WAIVER_TARGET_DATE


def _purchase_and_defective_certificate():
    """A CONSUMABLE row of 4,000,000 and an unlinked certificate failing on the form."""
    ctx = setup_agreed_methodology()
    ctx["purchase"] = record_purchase(
        ctx["audit"]["id"],
        "2026-02-10",
        4_000_000,
        asset_class="CONSUMABLE",
        in_state_usage_pct_bp=5_000,
        vendor_name="Cascade Machine Co",
    )
    ctx["certificate"] = file_certificate(
        ctx["audit"]["id"],
        purchaser_name="Basin Resale Inc",
        claimed_exemption_type="RESALE",
        covered_sale_amount_cents=2_000_000,
        form_complete=False,
    )
    return ctx


def test_reclassification_recomputes_the_row_while_a_cure_leaves_the_roll_up_alone():
    """One in-place recompute moves the money; the other deliberately does not.

    PRD 3.5: "A `CONSUMABLE` purchase takes `taxable_basis_cents` equal to
    `purchase_price_cents`; apportionment never applies to it, and any
    `in_state_usage_pct_bp` supplied on such a row is ignored by the arithmetic."
    PRD 3.5: "A `FieldAuditor` may also reclassify a purchase, supplying a new
    `asset_class` and any of the same four apportionment inputs plus
    `tax_paid_other_state_cents`; reclassification re-runs the whole computation in
    place, increments `reclassification_count` by one, re-sums the audit total, sets
    `projection_status` to `STALE` and cascades any `DRAFT` assessment to
    `DRAFT_STALE` exactly as a creation does."
    PRD 3.5: "A cure deliberately leaves the linked unit's determination and the
    audit's `certificate_deficiency_cents` untouched until the next review, so the
    money moves only when an auditor determines the cured certificate."
    PRD 3.5: "Certificates that were rejected and later validated after a cure drop
    out of the sum and their `missing_certificate_tax_cents` returns to 0."

    Design: Corner/endpoints/reclassification_and_cure_recompute_the_row_and_the_roll_up
    """
    ctx = _purchase_and_defective_certificate()
    audit_id = ctx["audit"]["id"]
    purchase_id = ctx["purchase"]["id"]
    certificate_id = ctx["certificate"]["id"]

    assert ctx["purchase"]["taxable_basis_cents"] == 4_000_000
    assert ctx["purchase"]["gross_use_tax_cents"] == 250_000
    assert ctx["purchase"]["credit_applied_cents"] == 0
    assert ctx["purchase"]["use_tax_due_cents"] == 250_000
    assert ctx["purchase"]["reclassification_count"] == 0
    assert ctx["certificate"]["good_faith_accepted"] is False
    assert ctx["certificate"]["status"] == "ON_FILE"
    assert ctx["certificate"]["missing_certificate_tax_cents"] == 0

    stepdown = {
        "in_state_usage_pct_bp": 7_500,
        "first_use_outside_state": True,
        "months_used_outside_state": 8,
        "tax_paid_other_state_cents": 200_000,
    }
    validate_error(
        api_client.reclassify_use_tax_purchase(
            purchase_id,
            reclassify_use_tax_purchase_payload("CAPITAL_ASSET", **stepdown),
            AUDITOR,
        ),
        ApiErrorId.ERR_CAPITAL_ASSET_FMV_REQUIRED.value,
        422,
    )
    untouched = read_purchase(purchase_id)
    assert untouched["asset_class"] == "CONSUMABLE"
    assert untouched["use_tax_due_cents"] == 250_000
    assert untouched["reclassification_count"] == 0

    reclassified = reclassify_purchase(
        purchase_id,
        "CAPITAL_ASSET",
        fair_market_value_at_entry_cents=6_000_000,
        **stepdown,
    )
    assert reclassified["taxable_basis_cents"] == 4_500_000
    assert reclassified["gross_use_tax_cents"] == 281_250
    assert reclassified["credit_applied_cents"] == 200_000
    assert reclassified["use_tax_due_cents"] == 81_250
    assert reclassified["reclassification_count"] == 1

    rejected = review_certificate(
        certificate_id, "REJECTED", review_note="Form incomplete"
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["missing_certificate_tax_cents"] == 125_000
    assert rejected["cure_count"] == 0

    cured = cure_certificate(certificate_id, ctx["taxpayer"]["id"], form_complete=True)
    assert cured["status"] == "CURED"
    assert cured["cure_count"] == 1
    assert cured["good_faith_accepted"] is True
    assert cured["form_complete"] is True
    assert cured["missing_certificate_tax_cents"] == 125_000

    audit = read_audit(audit_id)
    assert audit["use_tax_deficiency_cents"] == 81_250
    assert audit["certificate_deficiency_cents"] == 125_000
    assert audit["projection_status"] == "STALE"

    validated = review_certificate(
        certificate_id, "VALIDATED", review_note="Cured form accepted"
    )
    assert validated["status"] == "VALIDATED"
    assert validated["missing_certificate_tax_cents"] == 0
    assert read_audit(audit_id)["certificate_deficiency_cents"] == 0

    rows, meta = _certificates(audit_id=audit_id, status="VALIDATED")
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert [row["id"] for row in rows] == [certificate_id]


EXECUTED_WAIVER_TARGET = "2031-01-01"
DRAFTED_WAIVER_TARGET = "2031-06-01"
EXECUTED_WAIVER_DAYS = 551


def _matter_with_two_rows_in_every_collection():
    """One matter carrying two information returns, two waivers and two arrangements."""
    set_clock_date("2026-06-30")
    ctx = setup_review_complete_audit(
        tax_deficiency_cents=SMALL_BALANCE_TAX_CENTS,
        project_overrides={"selection_quota": 2},
    )
    taxpayer_id = ctx["taxpayer"]["id"]
    audit_id = ctx["audit"]["id"]
    period_end = ctx["audit"]["scope_period_end"]

    ctx["under_reported_return"] = load_information_return(
        taxpayer_id,
        source_type="FEDERAL_1099K",
        reported_amount_cents=120_000_000,
        matched_return_amount_cents=90_000_000,
    )
    ctx["matched_return"] = load_information_return(
        taxpayer_id,
        source_type="WHOLESALER_REPORT",
        reported_amount_cents=400_000,
        matched_return_amount_cents=400_000,
    )
    ctx["other_project"] = create_industry_project(
        project_name="Grocery Sweep 2026",
        industry_naics_code=GROCERY_NAICS,
        industry_error_rate_bp=1_800,
        selection_mode="QUOTA",
        selection_threshold_score=0,
        selection_quota=1,
    )
    ctx["executed_waiver"] = execute_waiver(
        draft_waiver(audit_id, period_end, EXECUTED_WAIVER_TARGET)["id"],
        taxpayer_id,
        "2026-06-30",
    )
    ctx["drafted_waiver"] = draft_waiver(audit_id, period_end, DRAFTED_WAIVER_TARGET)
    ctx["assessment"] = issue_assessment(
        draft_assessment(audit_id)["id"], "2026-06-30"
    )
    assessment_id = ctx["assessment"]["id"]
    ctx["plan"] = request_installment_plan(assessment_id, 2_381, 2)
    ctx["offer"] = request_offer_in_compromise(
        assessment_id, 100, hardship_documented=False
    )
    ctx["audit"] = read_audit(audit_id)
    return ctx


def test_each_parent_scoped_listing_answers_only_for_its_own_parent():
    """Four reverse sub-collections and the project list, each unfiltered then filtered.

    PRD 2.3: "Every list response carries `limit`, `offset`, `total_count` and
    `has_more` inside the `meta` object of the envelope, where `total_count` counts the
    records that match the filters before the limit and offset are applied."
    PRD 2.9: "Nesting appears only in read-only sub-collections that walk a
    relationship backwards: a permit holder's information returns, an audit's statute
    waivers, an audit's use-tax purchases, a sampling agreement's sample units, and an
    assessment's payment arrangements."
    PRD 3.1: "A third computed flag, `in_scoring_window`, is true when the row's
    `period_end` is on or before the logical clock date; it is evaluated when the
    record is read rather than frozen at load time, so moving the clock moves the
    flag."
    PRD 3.1: "Loading computes `variance_cents` as the reported amount minus the
    matched amount, a signed value, and classifies the row in `match_status`:
    `MATCHED` when the variance is exactly zero, `UNDER_REPORTED` when it is positive,
    and `OVER_REPORTED` when it is negative."
    PRD 3.2: "The waiver moves `DRAFTED → EXECUTED`, capturing `prior_expiry_date` as
    the audit's expiry at that moment and `days_added` as the whole number of days from
    that snapshot to `extended_to_date`."

    Design: Corner/endpoints/every_scoped_listing_filters_within_its_own_parent
    """
    ctx = _matter_with_two_rows_in_every_collection()
    taxpayer_id = ctx["taxpayer"]["id"]
    audit_id = ctx["audit"]["id"]
    assessment_id = ctx["assessment"]["id"]

    projects, project_meta = validate_paginated(api_client.list_industry_projects(ANALYST))
    assert project_meta["total_count"] == 2
    assert project_meta["has_more"] is False
    assert {row["id"] for row in projects} == {
        ctx["project"]["id"],
        ctx["other_project"]["id"],
    }

    threshold_only, threshold_meta = validate_paginated(
        api_client.list_industry_projects(ANALYST, params={"selection_mode": "THRESHOLD"})
    )
    assert threshold_meta["total_count"] == 1
    assert threshold_only[0]["id"] == ctx["project"]["id"]
    assert threshold_only[0]["selections_used"] == 1
    assert threshold_only[0]["selections_remaining"] == 1

    returns, returns_meta = validate_paginated(
        api_client.list_taxpayer_information_returns(taxpayer_id, AUDITOR)
    )
    assert returns_meta["total_count"] == 2
    assert all(row["in_scoring_window"] is True for row in returns)

    under, under_meta = validate_paginated(
        api_client.list_taxpayer_information_returns(
            taxpayer_id, AUDITOR, params={"match_status": "UNDER_REPORTED"}
        )
    )
    assert under_meta["total_count"] == 1
    assert under[0]["id"] == ctx["under_reported_return"]["id"]
    assert under[0]["variance_cents"] == 30_000_000
    assert under[0]["match_status"] == "UNDER_REPORTED"
    assert ctx["matched_return"]["variance_cents"] == 0
    assert ctx["matched_return"]["match_status"] == "MATCHED"

    waivers, waiver_meta = validate_paginated(
        api_client.list_audit_statute_waivers(audit_id, AUDITOR)
    )
    assert waiver_meta["total_count"] == 2
    assert waiver_meta["has_more"] is False

    executed, executed_meta = validate_paginated(
        api_client.list_audit_statute_waivers(audit_id, AUDITOR, params={"status": "EXECUTED"})
    )
    assert executed_meta["total_count"] == 1
    assert executed[0]["id"] == ctx["executed_waiver"]["id"]
    assert executed[0]["days_added"] == EXECUTED_WAIVER_DAYS
    assert executed[0]["prior_expiry_date"] == base_expiry_for()
    assert executed[0]["signed_date"] == "2026-06-30"
    assert ctx["drafted_waiver"]["status"] == "DRAFTED"
    assert ctx["drafted_waiver"]["days_added"] == 0

    assert ctx["audit"]["statute_expiry_date"] == EXECUTED_WAIVER_TARGET
    assert ctx["audit"]["waiver_days_added"] == EXECUTED_WAIVER_DAYS
    assert ctx["audit"]["statute_status"] == "PROTECTED"

    arrangements, arrangement_meta = validate_paginated(
        api_client.list_assessment_payment_arrangements(assessment_id, COLLECTIONS)
    )
    assert arrangement_meta["total_count"] == 2
    assert all(row["status"] == "REQUESTED" for row in arrangements)
    assert all(row["payments_made_count"] == 0 for row in arrangements)
    assert all(row["amount_paid_cents"] == 0 for row in arrangements)

    offers, offer_meta = validate_paginated(
        api_client.list_assessment_payment_arrangements(
            assessment_id, COLLECTIONS, params={"arrangement_type": "OFFER_IN_COMPROMISE"}
        )
    )
    assert offer_meta["total_count"] == 1
    assert offers[0]["id"] == ctx["offer"]["id"]
    assert offers[0]["scheduled_total_cents"] == 100
    assert offers[0]["hardship_documented"] is False
    assert ctx["plan"]["scheduled_total_cents"] == SMALL_BALANCE_TAX_CENTS

    assessment = read_assessment(assessment_id)
    assert assessment["total_due_cents"] == SMALL_BALANCE_TAX_CENTS
    assert assessment["balance_due_cents"] == SMALL_BALANCE_TAX_CENTS
