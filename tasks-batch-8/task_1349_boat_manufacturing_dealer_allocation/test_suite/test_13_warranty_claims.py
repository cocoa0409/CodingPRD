"""Warranty claims: variant selection, pinned per-component reimbursement
rounding, adjudication gates, coverage window, and recall linkage mismatch
(PRD §3.8)."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_warranty_claim,
    approve_claim,
    book_order_no_options,
    certify_hull,
    confirm_order,
    create_dealer,
    create_hull,
    create_model,
    create_warranty_claim_payload,
    deliver_hull,
    get_order,
    list_notices,
    make_dealer_principal_headers,
    reject_claim,
    set_clock,
    setup_bookable_world,
    setup_issued_campaign,
    setup_registered_hull,
    submit_claim,
    validate_error,
    validate_success,
)

ANY = TEST_USERS["any_headers"]
WARRANTY_ADMIN = TEST_USERS["warranty_administrator_headers"]


class TestClaimReimbursement:
    def test_standard_variant_tiered_labor_boundary(self, api):
        """PRD §3.8: "Under the `STANDARD` variant, labor pays the first 2.0
        claimed hours (or all of them when fewer) at 9000 cents per hour
        rounded half up, plus any hours beyond 2.0 at 9000 cents times 0.85
        rounded half up, and parts are credited at 0.85 of `parts_cents`
        rounded half up."

        Exactly 2.0 hours sits fully in tier 1: labor rhu(2.0*9000) = 18000,
        parts rhu(50000*0.85) = 42500.

        Design: Corner/calculations/claim_reimbursement_standard_tiered_labor
        """
        world = setup_registered_hull(api, with_options=False)
        claim = submit_claim(
            api, world["registration"]["id"], world["dealer"],
            defect_description="boundary test", labor_hours=2.0, parts_cents=50000,
        )
        assert claim["variant_applied"] == "STANDARD"
        approved = approve_claim(api, claim["id"])
        assert approved["labor_charge_cents"] == 18000
        assert approved["parts_credit_cents"] == 42500
        assert approved["reimbursement_cents"] == 60500
        assert approved["status"] == "APPROVED"
        assert_warranty_claim(approved)

    def test_standard_vs_recall_goodwill_same_inputs_diverge(self, api):
        """PRD §3.8: "The presence of that linkage decides the claim's
        `variant_applied`: `RECALL_GOODWILL` when a notice is linked,
        `STANDARD` otherwise."
        PRD §3.8: "Under the `RECALL_GOODWILL` variant, labor pays flat —
        every claimed hour at 9000 cents, rounded half up, with no tier
        discount — and parts are credited at the full `parts_cents`; the same
        inputs therefore produce a strictly higher total than `STANDARD`
        whenever hours exceed the first tier or parts are nonzero."

        Identical 4.0h / 100000-cent claims: STANDARD reimburses
        18000 + 15300 + 85000 = 118300; RECALL_GOODWILL reimburses
        36000 + 100000 = 136000.

        Design: Difficulty/dual_variant_calc/claim_reimbursement_standard_vs_recall_goodwill
        """
        world = setup_registered_hull(api, with_options=False, sale_date="2026-08-02")
        campaign, notices = setup_issued_campaign(api, world, serial_start=1, serial_end=5)
        assert len(notices) == 1
        notice_id = notices[0]["id"]
        claim_std = submit_claim(
            api, world["registration"]["id"], world["dealer"],
            defect_description="gel coat crazing", labor_hours=4.0,
            parts_cents=100000,
        )
        claim_rg = submit_claim(
            api, world["registration"]["id"], world["dealer"],
            defect_description="recall remedy labor", labor_hours=4.0,
            parts_cents=100000, recall_notice_id=notice_id,
        )
        assert claim_std["variant_applied"] == "STANDARD"
        assert claim_rg["variant_applied"] == "RECALL_GOODWILL"
        approved_std = approve_claim(api, claim_std["id"])
        approved_rg = approve_claim(api, claim_rg["id"])
        assert approved_std["reimbursement_cents"] == 118300, (
            f"STANDARD 118300 expected, got {approved_std['reimbursement_cents']}"
        )
        assert approved_std["labor_charge_cents"] == 33300  # 18000 + rhu(15300)
        assert approved_std["parts_credit_cents"] == 85000
        assert approved_rg["reimbursement_cents"] == 136000, (
            f"RECALL_GOODWILL 136000 expected, got {approved_rg['reimbursement_cents']}"
        )
        assert approved_rg["labor_charge_cents"] == 36000
        assert approved_rg["parts_credit_cents"] == 100000
        assert approved_std["reimbursement_cents"] != approved_rg["reimbursement_cents"]

    def test_standard_vs_recall_goodwill_below_tier_one(self, api):
        """PRD §3.8: "Under the `STANDARD` variant, labor pays the first 2.0
        claimed hours (or all of them when fewer) at 9000 cents per hour
        rounded half up, plus any hours beyond 2.0 at 9000 cents times 0.85
        rounded half up, and parts are credited at 0.85 of `parts_cents`
        rounded half up. Under the `RECALL_GOODWILL` variant, labor pays flat —
        every claimed hour at 9000 cents, rounded half up, with no tier
        discount — and parts are credited at the full `parts_cents`"

        At 1.0h / 5000 cents only the parts factor diverges: STANDARD pays
        9000 + 4250 = 13250; RECALL_GOODWILL pays 9000 + 5000 = 14000.

        Design: Difficulty/dual_variant_calc/claim_reimbursement_standard_vs_recall_goodwill
        """
        world = setup_registered_hull(api, with_options=False, sale_date="2026-08-02")
        campaign, notices = setup_issued_campaign(api, world, serial_start=1, serial_end=5)
        notice_id = notices[0]["id"]
        claim_std = submit_claim(
            api, world["registration"]["id"], world["dealer"],
            defect_description="minor gel coat", labor_hours=1.0, parts_cents=5000,
        )
        claim_rg = submit_claim(
            api, world["registration"]["id"], world["dealer"],
            defect_description="recall parts", labor_hours=1.0, parts_cents=5000,
            recall_notice_id=notice_id,
        )
        approved_std = approve_claim(api, claim_std["id"])
        approved_rg = approve_claim(api, claim_rg["id"])
        assert approved_std["reimbursement_cents"] == 13250  # 9000 + rhu(4250)
        assert approved_rg["reimbursement_cents"] == 14000  # 9000 + 5000
        assert approved_std["variant_applied"] == "STANDARD"
        assert approved_rg["variant_applied"] == "RECALL_GOODWILL"


class TestClaimAdjudicationGates:
    def test_approve_on_already_approved_rejected(self, api):
        """PRD §3.8: "Both approval and rejection require the claim to be
        `SUBMITTED`, anything else drawing `ERR_CLAIM_NOT_SUBMITTED`."

        Design: Corner/state_machines/warranty_claim_approve_on_already_approved_rejected
        """
        world = setup_registered_hull(api, with_options=False)
        claim = submit_claim(
            api, world["registration"]["id"], world["dealer"],
            defect_description="minor gel coat", labor_hours=1.0, parts_cents=5000,
        )
        approve_claim(api, claim["id"])
        resp = api.approve_warranty_claim(claim["id"], WARRANTY_ADMIN)
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_SUBMITTED)

    def test_reject_has_no_financial_side_effects(self, api):
        """PRD §3.8: "Rejection simply moves the claim `SUBMITTED` → `REJECTED`
        with no financial side effects, the three amount fields remaining
        null."
        PRD §3.8: "A new claim is `SUBMITTED`, with `labor_charge_cents`,
        `parts_credit_cents`, and `reimbursement_cents` all null until
        adjudication."

        Design: Corner/state_machines/warranty_claim_reject_has_no_financial_side_effects
        """
        world = setup_registered_hull(api, with_options=False)
        claim = submit_claim(
            api, world["registration"]["id"], world["dealer"],
            defect_description="test", labor_hours=1.0, parts_cents=5000,
        )
        assert claim["status"] == "SUBMITTED"
        assert claim["labor_charge_cents"] is None
        assert claim["parts_credit_cents"] is None
        assert claim["reimbursement_cents"] is None
        rejected = reject_claim(api, claim["id"])
        assert rejected["status"] == "REJECTED"
        assert rejected["labor_charge_cents"] is None
        assert rejected["parts_credit_cents"] is None
        assert rejected["reimbursement_cents"] is None


class TestClaimTemporalAndLinkage:
    def test_coverage_expired_blocks_claim(self, api):
        """PRD §3.8: "Coverage is enforced temporally: a claim submitted after
        the registration's `coverage_end_date` is rejected with
        `ERR_COVERAGE_EXPIRED`, while a recall-linked claim bypasses the
        coverage window entirely (submission on the coverage end date itself
        is still inside coverage)."

        Sale 2026-08-02 -> coverage ends 2029-08-02; a claim at 2029-08-03 is
        outside coverage.

        Design: Corner/validations/coverage_expired_blocks_claim_unless_recall_linked
        """
        world = setup_registered_hull(api, with_options=False, sale_date="2026-08-02")
        assert world["registration"]["coverage_end_date"] == "2029-08-02"
        set_clock(api, "2029-08-03T00:00:00Z")
        resp = api.create_warranty_claim(
            create_warranty_claim_payload(
                world["registration"]["id"], defect_description="late",
                labor_hours=1.0, parts_cents=1000,
            ),
            make_dealer_principal_headers(world["dealer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_COVERAGE_EXPIRED)

    def test_recall_notice_mismatch_rejected(self, api):
        """PRD §3.8: "The linked notice must belong to the same hull as the
        registration — a notice for a different hull draws
        `ERR_RECALL_NOTICE_MISMATCH`"

        Design: Corner/validations/recall_notice_mismatch_rejected_on_claim
        """
        world = setup_bookable_world(api, with_options=False)
        dealer, model, slot = world["dealer"], world["model"], world["slot"]
        hulls = []
        for _ in range(2):
            order = book_order_no_options(api, dealer, model, slot_id=slot["id"])
            order = confirm_order(api, order, dealer)
            hulls.append(create_hull(api, order["id"]))
        for hull in hulls:
            certify_hull(api, hull["id"])
        set_clock(api, "2026-08-02T00:00:00Z")
        for hull in hulls:
            deliver_hull(api, hull["id"])
        # Register only the first hull's sale.
        reg1 = validate_success(
            api.create_warranty_registration(
                {"hull_id": hulls[0]["id"], "dealer_id": dealer["id"],
                 "retail_sale_date": "2026-08-02"},
                make_dealer_principal_headers(dealer["id"]),
            ),
            201,
        )
        # A campaign covering only serial 2 (the second hull).
        campaign, notices = setup_issued_campaign(api, world, serial_start=2,
                                                  serial_end=2)
        assert len(notices) == 1
        assert notices[0]["hull_id"] == hulls[1]["id"]
        resp = api.create_warranty_claim(
            create_warranty_claim_payload(
                reg1["id"], defect_description="x", labor_hours=1.0,
                parts_cents=1000, recall_notice_id=notices[0]["id"],
            ),
            make_dealer_principal_headers(dealer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_RECALL_NOTICE_MISMATCH)


class TestClaimNotFound:
    def test_registration_not_found_on_claim(self, api):
        """PRD §2.9: "Body-referenced foreign keys exist — `model_id`,
        `dealer_id`, `slot_id`, `show_event_id`, `run_id`, `order_id`,
        `hull_id`, `registration_id`, `recall_notice_id`, each element of
        `option_package_ids`, and `incompatible_with_option_id` — otherwise the
        corresponding `ERR_MODEL_NOT_FOUND`, `ERR_DEALER_NOT_FOUND`,
        `ERR_SLOT_NOT_FOUND`, `ERR_SHOW_EVENT_NOT_FOUND`, `ERR_RUN_NOT_FOUND`,
        `ERR_ORDER_NOT_FOUND`, `ERR_HULL_NOT_FOUND`,
        `ERR_REGISTRATION_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`, or
        `ERR_OPTION_NOT_FOUND`."

        Design: Corner/errors/error_registration_not_found_triggerable
        """
        dealer = create_dealer(api)
        resp = api.create_warranty_claim(
            create_warranty_claim_payload(
                NON_EXISTENT_UUID, defect_description="x", labor_hours=1.0,
                parts_cents=100,
            ),
            make_dealer_principal_headers(dealer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REGISTRATION_NOT_FOUND)

    def test_claim_not_found_on_approve(self, api):
        """PRD §2.9: "Path identifiers exist, validated left to right along the
        URL — the first missing resource yields its `ERR_{RESOURCE}_NOT_FOUND`:
        `ERR_DEALER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_HULL_NOT_FOUND`,
        `ERR_CLAIM_NOT_FOUND`, `ERR_CAMPAIGN_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`,
        `ERR_RUN_NOT_FOUND`, or `ERR_MODEL_NOT_FOUND`."

        Design: Corner/errors/error_claim_not_found_triggerable
        """
        resp = api.approve_warranty_claim(NON_EXISTENT_UUID, WARRANTY_ADMIN)
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_FOUND)
