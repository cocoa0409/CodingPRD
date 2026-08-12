"""Tax receipts: dual valuation paths, appraisal threshold, SoD, OCC amend (PRD §3.3, §2.7)."""
from test_helpers import (
    ApiErrorId,
    create_accepted_offer,
    create_category,
    create_donor,
    draft_receipt,
    issue_receipt,
    setup_issued_receipt,
    setup_offer_with_priced_items,
    validate_error,
    validate_success,
)
from test_helpers.test_users import TEST_USERS, make_intake_staff_headers

INTAKE = TEST_USERS["intake_staff_headers"]
ADMIN = TEST_USERS["warehouse_admin_headers"]


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc / receipt_valuation_guidance_vs_appraisal
# ---------------------------------------------------------------------------

def _setup_cabinets_scenario():
    """6 grade-B UNIT cabinets, each priced 90000 by override; offer RECEIVED by
    staff-recv-1; receipt drafted. Item sum 540000 >= 500000 appraisal threshold."""
    ctx = setup_offer_with_priced_items(
        [90000] * 6,
        receiver_id="staff-recv-1",
        category_overrides={
            "code": "CABINETS", "display_name": "Cabinets",
            "pricing_model": "PER_UNIT", "base_rate_cents": 100000,
        },
        offer_overrides={
            "description_text": "6 cabinets", "estimated_quantity": 6,
            "quantity_unit": "UNIT", "condition_grade": "B",
        },
    )
    ctx["receipt"] = draft_receipt(ctx["offer"]["id"])
    return ctx


class TestReceiptValuationGuidanceVsAppraisal:
    def test_receipt_valuation_three_divergent_figures(self, api):
        """PRD §3.3: "When that item sum is at least $5,000 (500,000 cents) — the
        threshold is inclusive, so a sum of exactly $5,000 crosses it — or when the
        offer's category carries `requires_appraisal_review`, the receipt takes the
        `QUALIFIED_APPRAISAL` path: both `appraisal_reference` and
        `appraisal_value_cents` are mandatory (missing either fails with
        `ERR_APPRAISAL_REQUIRED`), and `valued_total_cents` becomes the appraised
        value verbatim, even though the identical items would sum to a different
        number."

        Design: Difficulty/dual_variant_calc/receipt_valuation_guidance_vs_appraisal
        """
        ctx = _setup_cabinets_scenario()
        offer = ctx["offer"]
        # Provisional ESTIMATED_GUIDANCE at accept: round(100000*6*0.75*0.30) = 135000.
        assert offer["estimated_value_cents"] == 135000, (
            f"provisional guidance figure expected 135000, got {offer['estimated_value_cents']}")

        receipt = issue_receipt(ctx["receipt"]["id"], issuer_id="staff-issue-1",
                                appraisal_reference="APR-100", appraisal_value_cents=600000)
        assert receipt["valuation_method"] == "QUALIFIED_APPRAISAL", (
            "item sum 540000 >= 500000 selects the appraisal path")
        assert receipt["valued_total_cents"] == 600000, (
            f"appraisal value taken verbatim: expected 600000, got {receipt['valued_total_cents']} "
            "(not 540000 item sum, not 135000 provisional)")

    def test_receipt_valuation_issue_ripple_offer_receipted(self, api):
        """PRD §3.3: "Issuing ripples outward: the offer moves from `RECEIVED` to
        `RECEIPTED` and its `final_value_cents` is set to the issued
        `valued_total_cents`, the donor's trailing receipt value and recognition
        tier are recomputed, and the receipt, offer, and donor each bump their
        `version`."

        Design: Difficulty/dual_variant_calc/receipt_valuation_guidance_vs_appraisal
        """
        ctx = _setup_cabinets_scenario()
        issue_receipt(ctx["receipt"]["id"], issuer_id="staff-issue-1",
                      appraisal_reference="APR-100", appraisal_value_cents=600000)
        offer = validate_success(api.get_donation_offer(ctx["offer"]["id"], INTAKE))
        assert offer["status"] == "RECEIPTED"
        assert offer["final_value_cents"] == 600000, (
            f"offer final_value_cents mirrors the issued total: {offer['final_value_cents']}")


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / appraisal_threshold_exact_boundary
# ---------------------------------------------------------------------------

class TestAppraisalThresholdExactBoundary:
    def test_appraisal_threshold_exact_boundary_rejected_without_appraisal(self, api):
        """PRD §3.3: "When that item sum is at least $5,000 (500,000 cents) — the
        threshold is inclusive, so a sum of exactly $5,000 crosses it — or when the
        offer's category carries `requires_appraisal_review`, the receipt takes the
        `QUALIFIED_APPRAISAL` path: both `appraisal_reference` and
        `appraisal_value_cents` are mandatory (missing either fails with
        `ERR_APPRAISAL_REQUIRED`), and `valued_total_cents` becomes the appraised
        value verbatim, even though the identical items would sum to a different
        number."

        Design: Difficulty/boundary_precision_check/appraisal_threshold_exact_boundary
        """
        ctx = setup_offer_with_priced_items(
            [100000] * 5,  # item sum exactly 500000 == threshold
            receiver_id="staff-r",
            category_overrides={"code": "LIGHTING", "display_name": "Lighting",
                                "pricing_model": "PER_UNIT", "base_rate_cents": 80000},
            offer_overrides={"description_text": "5 chandeliers", "estimated_quantity": 5},
        )
        receipt = draft_receipt(ctx["offer"]["id"])
        response = api.issue_receipt(receipt["id"], {}, make_intake_staff_headers("staff-i"))
        validate_error(response, ApiErrorId.ERR_APPRAISAL_REQUIRED)

        issued = issue_receipt(receipt["id"], issuer_id="staff-i",
                               appraisal_reference="APR-B1", appraisal_value_cents=500000)
        assert issued["status"] == "ISSUED"
        assert issued["valuation_method"] == "QUALIFIED_APPRAISAL"
        assert issued["valued_total_cents"] == 500000

    def test_appraisal_threshold_under_boundary_issues_without_appraisal(self, api):
        """PRD §3.3: "Below the threshold with no appraisal-review category, the
        receipt takes the `ESTIMATED_GUIDANCE` path and `valued_total_cents` is the
        item sum."
        PRD §3.3: "Let the item sum be the total of `list_price_cents` over all
        items linked to the receipt's offer that are `PRICED` and stand in
        `BACKROOM`, `ON_FLOOR`, `RESERVED`, or `SOLD`; goods that already left the
        stream as `DONATED_OUT`, `RECYCLED`, or `DISPOSED` cannot be valued."

        Design: Difficulty/boundary_precision_check/appraisal_threshold_exact_boundary
        """
        ctx = setup_offer_with_priced_items(
            [200000] * 2,  # item sum 400000 < 500000 threshold
            receiver_id="staff-r",
            category_overrides={"code": "LIGHTING", "display_name": "Lighting",
                                "pricing_model": "PER_UNIT", "base_rate_cents": 80000},
            offer_overrides={"description_text": "2 lamps", "estimated_quantity": 2},
        )
        receipt = draft_receipt(ctx["offer"]["id"])
        issued = issue_receipt(receipt["id"], issuer_id="staff-i")
        assert issued["status"] == "ISSUED"
        assert issued["valuation_method"] == "ESTIMATED_GUIDANCE"
        assert issued["valued_total_cents"] == 400000, (
            f"item-sum path: expected 400000, got {issued['valued_total_cents']}")


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency / receipt_requires_received_offer
# ---------------------------------------------------------------------------

class TestReceiptRequiresReceivedOffer:
    def test_receipt_draft_requires_received_offer_rejected(self, api):
        """PRD §3.3: "Drafting requires the offer to stand in `RECEIVED`
        (`ERR_INVALID_OFFER_STATE`), and an offer may carry at most one non-terminal
        receipt — one standing in `DRAFT`, `ISSUED`, or `VOID_REQUESTED`; drafting
        a second while one stands is refused with `ERR_ACTIVE_RECEIPT_EXISTS`."

        Design: Difficulty/cross_entity_state_dependency/receipt_requires_received_offer
        """
        category = create_category(code="HARDWARE", display_name="Hardware",
                                   base_rate_cents=500)
        donor = create_donor(full_name="D Eight")
        offer = create_accepted_offer(donor["id"], category["id"],
                                      description_text="hinges box", estimated_quantity=10)
        response = api.create_tax_receipt({"offer_id": offer["id"]}, INTAKE)
        validate_error(response, ApiErrorId.ERR_INVALID_OFFER_STATE)

    def test_receipt_draft_after_receive_succeeds(self, api):
        """PRD §3.3: "With goods physically in the building, an intake operator
        drafts a `TaxReceipt` for the offer."
        PRD §3.3: "The draft copies `donor_id` and `received_by_user_id` from the
        offer, leaves `valuation_method` null and `valued_total_cents` at 0 until
        issue pins them"

        Design: Difficulty/cross_entity_state_dependency/receipt_requires_received_offer
        """
        category = create_category(code="HARDWARE", display_name="Hardware",
                                   base_rate_cents=500)
        donor = create_donor(full_name="D Eight")
        offer = create_accepted_offer(donor["id"], category["id"],
                                      description_text="hinges box", estimated_quantity=10)
        offer = validate_success(api.receive_offer(offer["id"], make_intake_staff_headers("staff-r8")))
        assert offer["status"] == "RECEIVED"
        receipt = validate_success(api.create_tax_receipt({"offer_id": offer["id"]}, INTAKE),
                                   expected_status=201)
        assert receipt["status"] == "DRAFT"
        assert receipt["offer_id"] == offer["id"]


# ---------------------------------------------------------------------------
# Corner: state_machines / reject_void_reverts_to_issued
# ---------------------------------------------------------------------------

def test_reject_void_reverts_to_issued(api):
    """PRD §3.3: "Rejecting the void — the same state gate, the same
    `ERR_RECEIPT_NOT_VOID_REQUESTED` — returns the receipt to `ISSUED` and clears
    the `void_reason`, restoring the pre-request state exactly."
    PRD §3.3: "The issuing side can ask for a void, moving an `ISSUED` receipt to
    `VOID_REQUESTED` with a recorded `void_reason`; from any other state the
    request fails with `ERR_RECEIPT_NOT_ISSUED`."

    Design: Corner/state_machines/reject_void_reverts_to_issued
    """
    ctx = setup_issued_receipt([40000], receiver_id="staff-rv", issuer_id="staff-iv",
                               category_overrides={"code": "RVCAT", "display_name": "Revert Cat",
                                                   "base_rate_cents": 40000})
    receipt = ctx["receipt"]
    assert receipt["status"] == "ISSUED"
    assert receipt["valued_total_cents"] == 40000

    receipt = validate_success(api.request_void_receipt(
        receipt["id"], {"void_reason": "donor dispute"}, INTAKE))
    assert receipt["status"] == "VOID_REQUESTED"

    receipt = validate_success(api.reject_void_receipt(receipt["id"], ADMIN))
    assert receipt["status"] == "ISSUED", "reject-void restores ISSUED"
    assert receipt["valued_total_cents"] == 40000, (
        f"valuation unchanged after the round trip: {receipt['valued_total_cents']}")


# ---------------------------------------------------------------------------
# Corner: errors / active_receipt_per_offer_rejected
# ---------------------------------------------------------------------------

def test_active_receipt_per_offer_rejected(api):
    """PRD §3.3: "Drafting requires the offer to stand in `RECEIVED`
    (`ERR_INVALID_OFFER_STATE`), and an offer may carry at most one non-terminal
    receipt — one standing in `DRAFT`, `ISSUED`, or `VOID_REQUESTED`; drafting a
    second while one stands is refused with `ERR_ACTIVE_RECEIPT_EXISTS`."

    Design: Corner/errors/active_receipt_per_offer_rejected
    """
    ctx = setup_offer_with_priced_items(
        [],  # no items needed for the duplicate-draft gate
        receiver_id="staff-dup-r",
        category_overrides={"code": "DRCAT", "display_name": "Dup R Cat"},
        offer_overrides={"description_text": "dup", "estimated_quantity": 1},
    )
    validate_success(api.create_tax_receipt({"offer_id": ctx["offer"]["id"]}, INTAKE),
                     expected_status=201)
    response = api.create_tax_receipt({"offer_id": ctx["offer"]["id"]}, INTAKE)
    validate_error(response, ApiErrorId.ERR_ACTIVE_RECEIPT_EXISTS)


# ---------------------------------------------------------------------------
# Corner: cross_cutting_layers / receipt_amend_stale_version_rejected
# ---------------------------------------------------------------------------

def test_receipt_amend_stale_version_rejected(api):
    """PRD §2.7: "Amending a tax receipt — `POST /reuse/tax-receipts/{receiptId}/amend`
    — requires `expected_receipt_version`, matching the target receipt's current
    `version`. A successful amendment supersedes the receipt and bumps its version,
    so a client carrying a pre-amendment version holds a stale view; its amendment
    is rejected with `ERR_STALE_RECEIPT_VERSION` (HTTP 412)."
    PRD §3.3: "A successful amendment turns the amended receipt `SUPERSEDED` and
    bumps its `version`, creates the replacement receipt directly in `ISSUED` with
    `supersedes_receipt_id` pointing at the receipt it replaces, values the
    replacement per the same two-path rule, and recomputes the donor's trailing
    value and recognition tier over the replacement chain."

    Design: Corner/cross_cutting_layers/receipt_amend_stale_version_rejected
    """
    ctx = setup_issued_receipt([30000, 30000], receiver_id="staff-occ-r",
                               issuer_id="staff-occ-i",
                               category_overrides={"code": "OCCRCAT", "display_name": "OCC R Cat",
                                                   "base_rate_cents": 30000})
    receipt = ctx["receipt"]
    observed_version = receipt["version"]

    replacement = validate_success(api.amend_receipt(
        receipt["id"], {"expected_receipt_version": observed_version},
        make_intake_staff_headers("staff-occ-i")), expected_status=201)
    assert replacement["status"] == "ISSUED"
    assert replacement["supersedes_receipt_id"] == receipt["id"]

    old = validate_success(api.get_tax_receipt(receipt["id"], INTAKE))
    assert old["status"] == "SUPERSEDED"

    # Replaying the pre-amendment version is stale: OCC (cascade step 6) fires
    # before the ISSUED-state check (step 7) per PRD §2.10's fixed order.
    response = api.amend_receipt(
        receipt["id"], {"expected_receipt_version": observed_version},
        make_intake_staff_headers("staff-occ-i"))
    validate_error(response, ApiErrorId.ERR_STALE_RECEIPT_VERSION)
