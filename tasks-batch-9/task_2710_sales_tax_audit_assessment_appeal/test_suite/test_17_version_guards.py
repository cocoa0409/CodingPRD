"""Expected-version guards on shared parents, and cascades that land inside one request."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    agree_agreement_payload,
    api_client,
    close_fieldwork_payload,
    create_assessment_adjustment_payload,
    create_sampling_agreement_payload,
    default_strata,
    draw_sample_unit,
    issue_assessment_payload,
    make_taxpayer_headers,
    read_assessment,
    read_audit,
    record_purchase,
    refer_to_collections,
    set_clock_date,
    setup_draft_assessment,
    setup_issued_assessment,
    setup_proposed_methodology,
    setup_scoped_audit,
    validate_error,
    validate_paginated,
    validate_success,
)

AUDITOR = TEST_USERS["field_auditor_headers"]
SUPERVISOR = TEST_USERS["audit_supervisor_headers"]
COLLECTIONS = TEST_USERS["collections_agent_headers"]

SCOPE_START = "2026-01-01"
SCOPE_END = "2026-06-30"
PURCHASE_DATE = "2026-04-01"
PURCHASE_PRICE_CENTS = 76_192
USE_TAX_CENTS = 4_762
POPULATION_UNITS = 100
PROTEST_DEADLINE = "2026-08-29"

COLLECTION_FEE_CENTS = 476
BALANCE_AFTER_FEE_CENTS = 5_238
TOKEN_PAYMENT_CENTS = 100
ADJUSTMENTS_AFTER_PAYMENT_CENTS = -376
BALANCE_AFTER_PAYMENT_CENTS = 5_138


def _propose(audit_id, expected_version):
    """The same proposal body twice, differing only in the version it claims."""
    return api_client.create_sampling_agreement(
        create_sampling_agreement_payload(
            audit_id,
            expected_version,
            default_strata(SCOPE_START, SCOPE_END),
            methodology="RATIO_ESTIMATION",
            confidence_level_bp=9_500,
            minimum_sample_size=1,
        ),
        AUDITOR,
    )


def _agreements_of(audit_id):
    return validate_paginated(
        api_client.list_sampling_agreements(AUDITOR, params={"audit_id": audit_id})
    )


def _scoped_audit_with_one_purchase():
    """Scoped audit whose version has been advanced once by an untaxed purchase."""
    set_clock_date(SCOPE_END)
    ctx = setup_scoped_audit(
        scope_period_start=SCOPE_START, scope_period_end=SCOPE_END
    )
    ctx["version_at_scope"] = ctx["audit"]["version"]
    ctx["purchase"] = record_purchase(
        ctx["audit"]["id"],
        PURCHASE_DATE,
        PURCHASE_PRICE_CENTS,
        asset_class="CONSUMABLE",
    )
    assert ctx["purchase"]["use_tax_due_cents"] == USE_TAX_CENTS
    return ctx


def test_a_purchase_recorded_behind_the_client_invalidates_the_scope_version():
    """The version read at scope time is stale once an unrelated write touches the audit.

    PRD 2.10: "Proposing a sampling agreement requires `expected_audit_version`
    in the request body. The field is not optional. Its value must equal the
    current `version` of the audit named by `audit_id`; if the audit's `version`
    has advanced since the client last read it, the proposal is rejected with
    `ERR_STALE_AUDIT_VERSION` (HTTP 412)."
    PRD 2.4: "A derived field being recomputed counts as a mutation."
    PRD 3.5: "Recording a purchase sets the audit's `projection_status` to
    `STALE`, which cascades any `DRAFT` assessment of the audit to
    `DRAFT_STALE`."

    Design: Corner/cross_cutting_complexity_layers/a_stale_audit_version_cannot_propose_a_methodology
    """
    ctx = _scoped_audit_with_one_purchase()
    audit_id = ctx["audit"]["id"]

    response = _propose(audit_id, ctx["version_at_scope"])
    validate_error(response, ApiErrorId.ERR_STALE_AUDIT_VERSION.value, 412)

    agreements, meta = _agreements_of(audit_id)
    assert meta["total_count"] == 0
    assert agreements == []

    audit = read_audit(audit_id)
    assert audit["version"] == ctx["version_at_scope"] + 1
    assert audit["use_tax_deficiency_cents"] == USE_TAX_CENTS
    assert audit["projection_status"] == "STALE"


def test_the_same_proposal_succeeds_once_the_client_re_reads_the_audit():
    """Only the claimed version changes, and the accepted proposal advances it again.

    PRD 2.10: "The protection matters because a proposal supersedes whichever
    `PROPOSED` or `COUNTERED` agreement the audit already carries, so a writer
    holding an out-of-date view of the audit would silently discard a methodology
    round it never saw. On success the audit's `version` increments by one."
    PRD 3.3: "The agreement's `population_base_amount_cents` is the sum of the
    strata's `population_base_amount_cents` and is the denominator population for
    ratio estimation; its `population_unit_count` is the sum of the strata's
    `population_unit_count` and is the multiplier for mean-per-unit projection."

    Design: Corner/cross_cutting_complexity_layers/a_stale_audit_version_cannot_propose_a_methodology
    """
    ctx = _scoped_audit_with_one_purchase()
    audit_id = ctx["audit"]["id"]
    current_version = read_audit(audit_id)["version"]

    agreement = validate_success(_propose(audit_id, current_version), 201)
    assert agreement["status"] == "PROPOSED"
    assert agreement["round_number"] == 1
    assert agreement["population_unit_count"] == POPULATION_UNITS

    audit = read_audit(audit_id)
    assert audit["version"] == current_version + 1
    # A proposal nobody has accepted yet does not open fieldwork.
    assert audit["status"] == "SCOPED"


def _referred_small_balance_notice():
    """Issued 4,762-cent notice referred to collections, which charges the 10% fee."""
    ctx = setup_issued_assessment(tax_deficiency_cents=USE_TAX_CENTS)
    ctx["version_at_issue"] = ctx["assessment"]["version"]
    ctx["assessment"] = refer_to_collections(ctx["assessment"]["id"])
    assert ctx["assessment"]["total_adjustments_cents"] == -COLLECTION_FEE_CENTS
    assert ctx["assessment"]["balance_due_cents"] == BALANCE_AFTER_FEE_CENTS
    return ctx


def _post_payment(assessment_id, expected_version, amount_cents):
    return api_client.create_assessment_adjustment(
        create_assessment_adjustment_payload(
            assessment_id, expected_version, amount_cents, kind="PAYMENT"
        ),
        COLLECTIONS,
    )


def _ledger_of(assessment_id):
    return validate_paginated(
        api_client.list_assessment_adjustments(
            COLLECTIONS, params={"assessment_id": assessment_id}
        )
    )


def test_the_referral_fee_makes_the_issue_time_assessment_version_stale():
    """A cascade the client never issued still advances the parent it must quote.

    PRD 2.10: "Posting an assessment adjustment requires
    `expected_assessment_version` in the request body, again non-optional, and
    again it must equal the current `version` of the assessment named by
    `assessment_id`. A mismatch is rejected with `ERR_STALE_ASSESSMENT_VERSION`
    (HTTP 412)."
    PRD 2.4: "This is what makes stale-version protection meaningful: a cascade
    the client never issued still advances the parent's `version`."

    Design: Corner/cross_cutting_complexity_layers/a_stale_assessment_version_cannot_post_to_the_ledger
    """
    ctx = _referred_small_balance_notice()
    assessment_id = ctx["assessment"]["id"]

    response = _post_payment(
        assessment_id, ctx["version_at_issue"], TOKEN_PAYMENT_CENTS
    )
    validate_error(response, ApiErrorId.ERR_STALE_ASSESSMENT_VERSION.value, 412)

    assessment = read_assessment(assessment_id)
    assert assessment["version"] > ctx["version_at_issue"]
    assert assessment["collection_status"] == "REFERRED"
    assert assessment["total_adjustments_cents"] == -COLLECTION_FEE_CENTS
    assert assessment["balance_due_cents"] == BALANCE_AFTER_FEE_CENTS

    _, meta = _ledger_of(assessment_id)
    assert meta["total_count"] == 1


def test_the_re_read_version_posts_the_payment_alongside_the_fee():
    """The token payment lands in the adjustment sum, not in the arrangement cash.

    PRD 3.7: "A successful posting sets `status` to `POSTED` and `source` to
    `MANUAL`, re-derives the assessment's `total_adjustments_cents` and
    `balance_due_cents`, and, when the balance reaches exactly 0, moves the
    collection axis to `SATISFIED`."
    PRD 3.7: "`amount_paid_cents` is a deliberately separate aggregate that
    accumulates only the cash recorded through an arrangement's payments, not the
    ledger's `PAYMENT` rows; a manually posted `PAYMENT` adjustment flows into
    `total_adjustments_cents` instead."

    Design: Corner/cross_cutting_complexity_layers/a_stale_assessment_version_cannot_post_to_the_ledger
    """
    ctx = _referred_small_balance_notice()
    assessment_id = ctx["assessment"]["id"]
    current_version = read_assessment(assessment_id)["version"]

    row = validate_success(
        _post_payment(assessment_id, current_version, TOKEN_PAYMENT_CENTS), 201
    )
    assert row["kind"] == "PAYMENT"
    assert row["amount_cents"] == TOKEN_PAYMENT_CENTS
    assert row["source"] == "MANUAL"
    assert row["status"] == "POSTED"

    assessment = read_assessment(assessment_id)
    assert assessment["total_due_cents"] == USE_TAX_CENTS
    assert assessment["total_adjustments_cents"] == ADJUSTMENTS_AFTER_PAYMENT_CENTS
    assert assessment["amount_paid_cents"] == 0
    assert assessment["balance_due_cents"] == BALANCE_AFTER_PAYMENT_CENTS

    rows, meta = _ledger_of(assessment_id)
    assert meta["total_count"] == 2
    assert sorted(r["kind"] for r in rows) == ["COLLECTION_FEE", "PAYMENT"]


def test_the_acceptance_response_and_the_next_read_already_show_fieldwork():
    """The taxpayer's own acceptance carries the cascade, and the audit read confirms it.

    PRD 3.3: "Acceptance moves the agreement `PROPOSED → AGREED` and cascades:
    the audit's `agreed_agreement_id` is set to that agreement, the audit moves
    `SCOPED → FIELDWORK`, and every other sampling agreement of the same audit
    still in `PROPOSED` or `COUNTERED` moves to `SUPERSEDED`."
    PRD 3.2: "It is `EXPIRING_SOON` when the audit has not expired and the whole
    number of days from the logical clock date to `statute_expiry_date` is 90 or
    fewer — a full calendar quarter of warning. Otherwise it is `PROTECTED`."
    PRD 3.4: "`projected_deficiency_cents` holds the projected population
    deficiency, `examined_unit_count` holds the examined count,
    `projection_method` records the methodology just applied, and
    `projection_status` becomes `CURRENT`. The same run also re-sums the audit's
    other two deficiency components, `certificate_deficiency_cents` and
    `use_tax_deficiency_cents`, so that a successful projection leaves all three
    components mutually consistent."
    PRD 3.4: "The audit moves `FIELDWORK → REVIEW_COMPLETE` and the finding set
    freezes: no sample unit, exemption certificate or use-tax purchase of that
    audit may be created or changed while it remains in `REVIEW_COMPLETE`."

    Design: Corner/consistency_model/every_cascade_is_already_visible_in_the_response_that_caused_it
    """
    set_clock_date(SCOPE_END)
    ctx = setup_proposed_methodology(
        scope_period_start=SCOPE_START,
        scope_period_end=SCOPE_END,
        methodology="RATIO_ESTIMATION",
        confidence_level_bp=9_500,
        minimum_sample_size=1,
    )
    audit_id = ctx["audit"]["id"]
    agreement_id = ctx["agreement"]["id"]

    agreed = validate_success(
        api_client.agree_sampling_agreement(
            agreement_id,
            agree_agreement_payload(agreed_by_name="R. Vance"),
            make_taxpayer_headers(ctx["taxpayer"]["id"]),
        ),
        200,
    )
    assert agreed["status"] == "AGREED"
    assert agreed["agreed_by_name"] == "R. Vance"
    assert agreed["round_number"] == 1

    # No intervening write: the read only reports what the acceptance already did.
    audit = validate_success(api_client.get_audit(audit_id, AUDITOR), 200)
    assert audit["status"] == "FIELDWORK"
    assert audit["agreed_agreement_id"] == agreement_id
    assert audit["projection_status"] == "NOT_RUN"
    assert audit["statute_status"] == "PROTECTED"

    draw_sample_unit(agreement_id, invoice_reference="RT-001", error_class="NO_ERROR")
    record_purchase(
        audit_id, PURCHASE_DATE, PURCHASE_PRICE_CENTS, asset_class="CONSUMABLE"
    )

    projected = validate_success(api_client.project_sample(audit_id, AUDITOR), 200)
    assert projected["projection_status"] == "CURRENT"
    assert projected["projection_method"] == "RATIO_ESTIMATION"
    assert projected["sample_error_rate_bp"] == 0
    assert projected["projected_deficiency_cents"] == 0
    assert projected["use_tax_deficiency_cents"] == USE_TAX_CENTS

    closed = validate_success(
        api_client.close_fieldwork(
            audit_id, close_fieldwork_payload(fraud_indicator=False), SUPERVISOR
        ),
        200,
    )
    assert closed["status"] == "REVIEW_COMPLETE"


def test_the_issue_response_already_carries_the_deadline_and_the_audit_has_moved():
    """Issuance kicks the collection axis and the audit inside the request that mails it.

    PRD 3.6: "Issuance sets `issued_at` to the logical-clock timestamp and
    computes `protest_deadline_date` as `notice_mailed_date` plus 60 calendar
    days, the protest window. It then does two things on other axes: it kicks the
    collection axis once, moving `collection_status` from `NOT_DUE` to `DUE`, and
    it moves the audit from `REVIEW_COMPLETE` to `ASSESSED`."

    Design: Corner/consistency_model/every_cascade_is_already_visible_in_the_response_that_caused_it
    """
    ctx = setup_draft_assessment(tax_deficiency_cents=USE_TAX_CENTS)
    audit_id = ctx["audit"]["id"]
    assert ctx["assessment"]["collection_status"] == "NOT_DUE"
    assert ctx["assessment"]["protest_deadline_date"] is None

    issued = validate_success(
        api_client.issue_assessment(
            ctx["assessment"]["id"], issue_assessment_payload(SCOPE_END), SUPERVISOR
        ),
        200,
    )
    assert issued["status"] == "ISSUED"
    assert issued["collection_status"] == "DUE"
    assert issued["protest_deadline_date"] == PROTEST_DEADLINE
    assert issued["balance_due_cents"] == USE_TAX_CENTS
    assert issued["issued_at"].startswith(SCOPE_END)

    audit = validate_success(api_client.get_audit(audit_id, SUPERVISOR), 200)
    assert audit["status"] == "ASSESSED"
