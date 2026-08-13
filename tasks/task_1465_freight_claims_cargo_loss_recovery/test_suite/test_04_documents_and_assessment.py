"""Documents and liability assessment: document gating, the provisional
preview vs final assessment pipeline variants, model caps, and lane discount."""
from test_helpers import (
    ApiErrorId,
    assert_assessment,
    create_assessment_payload,
    create_document_payload,
    get_claim,
    get_success_data,
    set_clock,
    setup_claim_acknowledged,
    setup_claim_draft,
    setup_claim_under_review,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

CLERK = TEST_USERS["clerk_headers"]
ADJUSTER = TEST_USERS["adjuster_headers"]

# PER_POUND carrier: $5/lb cap, 100 lb shipment, claim 80_000 of 100_000.
PER_POUND_SETUP = dict(
    carrier_over={
        "liability_model": "PER_POUND",
        "per_pound_cap_cents": 500,
        "max_auto_settle_cents": 50_000,
    },
    shipment_over={
        "declared_value_cents": 100_000,
        "total_weight_lbs": 100,
        "package_count": 10,
    },
    claim_over={"claim_type": "DAMAGE", "claimed_amount_cents": 80_000},
)


class TestDocumentGating:
    def test_verify_rejected_document_rejected(self, api):
        """PRD §3.2: "A `ClaimsAdjuster` then works the queue: verifying requires the document still be `PENDING` (otherwise `ERR_DOCUMENT_INVALID_STATE`) and the claim still be in `DRAFT`, `SUBMITTED`, or `ACKNOWLEDGED` — a claim that has moved further along is locked against document churn and the attempt is `ERR_CLAIM_LOCKED` — while rejecting requires the document be `PENDING` and the request carry a non-empty `rejection_reason` (otherwise `ERR_REJECTION_REASON_REQUIRED`), with that reason persisted on the document only when it lands in `REJECTED`."

        Design: Corner/state_machines/document_verify_from_rejected_rejected
        """
        ctx = setup_claim_draft()
        claim_id = ctx["claim"]["id"]
        doc = get_success_data(
            api.attach_document(
                claim_id, create_document_payload(document_kind="PHOTO"), CLERK
            )
        )
        get_success_data(
            api.reject_document(
                claim_id, doc["id"], {"rejection_reason": "illegible"}, ADJUSTER
            )
        )
        resp = api.verify_document(claim_id, doc["id"], ADJUSTER)
        validate_error(resp, ApiErrorId.ERR_DOCUMENT_INVALID_STATE)

    def test_assessment_with_unverified_documents_rejected(self, api):
        """PRD §3.4: "Once a claim is `ACKNOWLEDGED` and every attached document has reached `VERIFIED` — a single `PENDING` or `REJECTED` straggler blocks the step with `ERR_DOCUMENTS_NOT_VERIFIED` — a `ClaimsAdjuster` commissions a liability assessment."

        Design: Corner/validations/assessment_requires_verified_documents
        """
        # Acknowledged with both required documents still PENDING.
        ctx = setup_claim_acknowledged()
        resp = api.create_assessment(
            ctx["claim"]["id"], create_assessment_payload(), ADJUSTER
        )
        validate_error(resp, ApiErrorId.ERR_DOCUMENTS_NOT_VERIFIED)


class TestProvisionalVsFinalLiability:
    def test_liability_preview_provisional_ignores_negligence(self, api):
        """PRD §3.4: "Against a `DRAFT` claim, the liability-preview capability runs the same pipeline minus the negligence step — no assessment exists yet, so the flag is ignored entirely — taking the basis from `claimed_amount_cents`, applying the model cap and lane discount, and returning a non-persisted estimate with `basis_cents`, `carrier_limit_cents`, `lane_discount_pct`, and `computed_liability_cents`."
        PRD §3.4: "Step two applies the carrier's liability model to produce `carrier_limit_cents`: under `FULL_VALUE` the limit is the basis itself; under `RELEASED_RATE` it is the lesser of the basis and the product of the shipment's `total_weight_lbs` with the carrier's `released_rate_cents_per_lb`; under `PER_PACKAGE` it is the lesser of the basis and the product of `package_count` with `per_package_cap_cents`; under `PER_POUND` it is the lesser of the basis and the product of `total_weight_lbs` with `per_pound_cap_cents`."

        Design: Difficulty/dual_variant_calc/limitation_of_liability_provisional_vs_final
        """
        ctx = setup_claim_draft(**PER_POUND_SETUP)
        resp = api.get_liability_preview(ctx["claim"]["id"], ADJUSTER)
        preview = validate_success(resp, 200)
        # basis = min(80_000, 100_000) = 80_000; cap = min(basis, 100*500) = 50_000;
        # discount 0 -> provisional computed liability 50_000.
        assert preview["basis_cents"] == 80_000
        assert preview["computed_liability_cents"] == 50_000

    def test_final_assessment_applies_negligence_zeroing(self, api):
        """PRD §3.4: "Step four applies negligence: `SHIPPER_FAULT` or `ACT_OF_GOD` collapses the carrier limit to zero; `CARRIER_NEGLIGENT` leaves the cap standing with no relaxation; `THIRD_PARTY` leaves it unchanged because recovery may be pursued separately through subrogation."
        PRD §3.4: "Against a `DRAFT` claim, the liability-preview capability runs the same pipeline minus the negligence step — no assessment exists yet, so the flag is ignored entirely — taking the basis from `claimed_amount_cents`, applying the model cap and lane discount, and returning a non-persisted estimate with `basis_cents`, `carrier_limit_cents`, `lane_discount_pct`, and `computed_liability_cents`."

        Design: Difficulty/dual_variant_calc/limitation_of_liability_provisional_vs_final
        """
        ctx = setup_claim_draft(**PER_POUND_SETUP)
        claim_id = ctx["claim"]["id"]
        # Provisional read on the same inputs (before any assessment exists).
        preview = validate_success(api.get_liability_preview(claim_id, ADJUSTER), 200)
        # Walk to the final variant: docs -> submit -> acknowledge -> verify -> assess.
        get_success_data(
            api.attach_document(
                claim_id, create_document_payload(document_kind="BOL"), CLERK
            )
        )
        get_success_data(
            api.attach_document(
                claim_id,
                create_document_payload(document_kind="COMMERCIAL_INVOICE"),
                CLERK,
            )
        )
        set_clock("2026-06-10T00:00:00Z")
        get_success_data(api.submit_claim(claim_id, CLERK))
        get_success_data(api.acknowledge_claim(claim_id, ADJUSTER))
        docs, _ = validate_paginated(api.list_documents(claim_id, CLERK))
        for doc in docs:
            get_success_data(api.verify_document(claim_id, doc["id"], ADJUSTER))
        assessment = validate_success(
            api.create_assessment(
                claim_id, {"negligence_flag": "SHIPPER_FAULT"}, ADJUSTER
            ),
            201,
        )
        assert_assessment(assessment)
        # SHIPPER_FAULT collapses the carrier limit to zero in the final variant.
        assert assessment["computed_liability_cents"] == 0
        # Same shipment/carrier/lane inputs, different variant outcome.
        assert preview["computed_liability_cents"] == 50_000
        assert preview["computed_liability_cents"] != assessment["computed_liability_cents"]


class TestTieredPipelineWithLaneDiscount:
    def test_released_rate_pipeline_with_lane_discount(self, api):
        """PRD §3.4: "Step one fixes the `limitation_basis_cents` as the lesser of the claim's `claimed_amount_cents` and the shipment's `declared_value_cents`."
        PRD §3.4: "Step two applies the carrier's liability model to produce `carrier_limit_cents`: under `FULL_VALUE` the limit is the basis itself; under `RELEASED_RATE` it is the lesser of the basis and the product of the shipment's `total_weight_lbs` with the carrier's `released_rate_cents_per_lb`; under `PER_PACKAGE` it is the lesser of the basis and the product of `package_count` with `per_package_cap_cents`; under `PER_POUND` it is the lesser of the basis and the product of `total_weight_lbs` with `per_pound_cap_cents`."
        PRD §3.4: "Step three applies the lane discount: the pipeline selects the carrier–lane assignment whose window covers the shipment's `ship_date` — `effective_from` inclusive, `effective_to` exclusive, ties broken in favor of the assignment with the earliest `created_at` — and if that assignment's `contracted_discount_pct` is above zero, the carrier limit is multiplied by one hundred minus the discount percentage and divided by one hundred, rounding down to a whole cent; the applied percentage is recorded as the assessment's `lane_discount_pct`."

        Design: Difficulty/combinatorial_formula/limitation_of_liability_tiered_with_lane_discount
        """
        ctx = setup_claim_under_review(
            carrier_over={
                "liability_model": "RELEASED_RATE",
                "released_rate_cents_per_lb": 250,
                "max_auto_settle_cents": 50_000,
            },
            assignment_over={"contracted_discount_pct": 15},
            shipment_over={
                "declared_value_cents": 100_000,
                "total_weight_lbs": 80,
                "package_count": 8,
            },
            claim_over={"claim_type": "DAMAGE", "claimed_amount_cents": 90_000},
        )
        assessment = ctx["assessment"]
        assert_assessment(assessment)
        # basis = min(90_000, 100_000) = 90_000
        assert assessment["limitation_basis_cents"] == 90_000
        # model cap = min(90_000, 80*250) = 20_000; floor(20_000*85/100) = 17_000
        assert assessment["lane_discount_pct"] == 15
        assert assessment["computed_liability_cents"] == 17_000

    def test_assessment_writes_back_liability_to_claim(self, api):
        """PRD §3.4: "Completion of the pipeline writes back to the claim: `computed_liability_cents` is copied onto the claim, `liability_assessment_id` points at the new assessment, and `net_exposure_cents` is recomputed as the claim's computed liability minus its `salvage_credit_cents`, floored at zero."
        PRD §3.4: "The new assessment is computed immediately, arriving already in `SUBMITTED` state (its `DRAFT` state is traversed at creation), and its arrival drives the claim from `ACKNOWLEDGED` to `UNDER_REVIEW`; commissioning an assessment against a claim in any other state is `ERR_CLAIM_INVALID_STATE`."

        Design: Difficulty/combinatorial_formula/limitation_of_liability_tiered_with_lane_discount
        """
        ctx = setup_claim_under_review(
            carrier_over={
                "liability_model": "RELEASED_RATE",
                "released_rate_cents_per_lb": 250,
                "max_auto_settle_cents": 50_000,
            },
            assignment_over={"contracted_discount_pct": 15},
            shipment_over={
                "declared_value_cents": 100_000,
                "total_weight_lbs": 80,
                "package_count": 8,
            },
            claim_over={"claim_type": "DAMAGE", "claimed_amount_cents": 90_000},
        )
        claim = ctx["claim"]
        assert claim["filing_status"] == "UNDER_REVIEW"
        assert claim["computed_liability_cents"] == 17_000
        assert claim["liability_assessment_id"] == ctx["assessment"]["id"]
        assert claim["net_exposure_cents"] == 17_000
        assert ctx["assessment"]["state"] == "SUBMITTED"


class TestPerPackageCap:
    def test_per_package_cap_limits_liability(self, api):
        """PRD §3.4: "Step two applies the carrier's liability model to produce `carrier_limit_cents`: under `FULL_VALUE` the limit is the basis itself; under `RELEASED_RATE` it is the lesser of the basis and the product of the shipment's `total_weight_lbs` with the carrier's `released_rate_cents_per_lb`; under `PER_PACKAGE` it is the lesser of the basis and the product of `package_count` with `per_package_cap_cents`; under `PER_POUND` it is the lesser of the basis and the product of `total_weight_lbs` with `per_pound_cap_cents`."
        PRD §3.4: "Step one fixes the `limitation_basis_cents` as the lesser of the claim's `claimed_amount_cents` and the shipment's `declared_value_cents`."

        Design: Corner/calculations/limitation_per_package_cap_applies
        """
        ctx = setup_claim_under_review(
            carrier_over={
                "liability_model": "PER_PACKAGE",
                "per_package_cap_cents": 10_000,
            },
            shipment_over={
                "declared_value_cents": 100_000,
                "total_weight_lbs": 50,
                "package_count": 5,
            },
            claim_over={"claim_type": "DAMAGE", "claimed_amount_cents": 80_000},
        )
        assessment = ctx["assessment"]
        # basis = min(80_000, 100_000) = 80_000; cap = min(80_000, 5*10_000) = 50_000;
        # no lane discount -> computed liability 50_000.
        assert assessment["limitation_basis_cents"] == 80_000
        assert assessment["carrier_limit_cents"] == 50_000
        assert assessment["computed_liability_cents"] == 50_000


class TestLiabilityPreview:
    def test_liability_preview_persists_nothing(self, api):
        """PRD §3.4: "Against a `DRAFT` claim, the liability-preview capability runs the same pipeline minus the negligence step — no assessment exists yet, so the flag is ignored entirely — taking the basis from `claimed_amount_cents`, applying the model cap and lane discount, and returning a non-persisted estimate with `basis_cents`, `carrier_limit_cents`, `lane_discount_pct`, and `computed_liability_cents`. Nothing is stored; the preview exists so intake staff can sanity-check a claim's realistic ceiling before filing it."

        Design: Corner/endpoints/liability_preview_is_non_persisting
        """
        ctx = setup_claim_draft(
            shipment_over={"declared_value_cents": 10_000},
            claim_over={"claim_type": "LOSS", "claimed_amount_cents": 5_000},
        )
        claim_id = ctx["claim"]["id"]
        preview = validate_success(api.get_liability_preview(claim_id, ADJUSTER), 200)
        # FULL_VALUE model: basis = min(5_000, 10_000) = 5_000 stands uncapped.
        assert preview["computed_liability_cents"] == 5_000
        assert preview["basis_cents"] == 5_000
        assert preview["lane_discount_pct"] == 0
        _rows, meta = validate_paginated(api.list_assessments(claim_id, CLERK))
        assert meta["total_count"] == 0, "Preview must not persist an assessment"
