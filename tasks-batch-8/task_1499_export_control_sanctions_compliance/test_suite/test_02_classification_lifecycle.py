"""Classification lifecycle, product version counter, OCC guard, determination pinning (PRD §2.4, §2.7, §3.1, §3.4)."""
from test_helpers import (
    ApiErrorId,
    assert_classification,
    audit_records_for,
    create_classification_payload,
    create_classified_product,
    create_draft_classification,
    create_order,
    create_party,
    create_product,
    get_order,
    get_product,
    get_success_data,
    make_analyst_headers,
    make_manager_headers,
    review_classification,
    submit_classification,
    submit_order,
    validate_error,
    validate_success,
)


class TestInitialStates:
    def test_initial_states_on_creation(self, api, analyst_headers):
        """PRD §3.1: "A successfully created draft is stamped `DRAFT`, receives a per-product monotone `sequence` equal to the product's `classification_count` after that count is incremented (so the first classification of a product bears sequence 1), and its creation increments the product's `version` by 1 while advancing `classification_count` by 1."
        PRD §3.5: "The application starts in `DRAFT` with `license_number` still null."
        PRD §3.9: "The record opens as `IDENTIFIED` with `identified_by_user_id` anchored to the caller and `disclosure_reference` still null."
        PRD §3.8: "A plan begins in `DRAFT`."

        Design: Corner/state_machines/initial_states_on_creation
        """
        product = validate_success(
            api.create_product(
                {"sku": "P-010", "name": "Plate", "controlled_content_pct": 0,
                 "unit_value_cents": 10},
                analyst_headers,
            ),
            201,
        )
        classification = validate_success(
            api.create_classification(
                create_classification_payload(product["id"], product["version"]),
                analyst_headers,
            ),
            201,
        )
        assert classification["status"] == "DRAFT"

        lic = validate_success(
            api.create_license(
                {"product_id": product["id"], "issuing_authority": "BIS",
                 "approved_value_cents": 1000, "approved_quantity": 10,
                 "valid_from": "2026-07-01", "valid_until": "2026-12-31"},
                analyst_headers,
            ),
            201,
        )
        assert lic["status"] == "DRAFT"

        violation = validate_success(
            api.create_violation(
                {"source_type": "OTHER", "source_id": "n/a", "severity": "MINOR",
                 "description": "test"},
                analyst_headers,
            ),
            201,
        )
        assert violation["status"] == "IDENTIFIED"

        tcp = validate_success(
            api.create_tcp(
                {"name": "TCP-X", "enclave_id": "LAB-X", "product_id": product["id"],
                 "segregation_level": "LEVEL_1", "effective_from": "2026-01-01",
                 "effective_to": "2027-01-01"},
                analyst_headers,
            ),
            201,
        )
        assert tcp["status"] == "DRAFT"


class TestSequenceAndVersionCounters:
    def test_classification_sequence_and_count_increment(self, api, analyst_headers):
        """PRD §3.1: "A successfully created draft is stamped `DRAFT`, receives a per-product monotone `sequence` equal to the product's `classification_count` after that count is incremented (so the first classification of a product bears sequence 1), and its creation increments the product's `version` by 1 while advancing `classification_count` by 1."
        PRD §3.1: "The count is monotone and never decremented, even when determinations are rejected or superseded."

        Design: Corner/entities/classification_sequence_and_count_increment
        """
        product = create_product(sku="P-002", name="Gear", controlled_content_pct=5,
                                 unit_value_cents=800)
        c1 = create_draft_classification(product, classification_code="EAR99")
        assert c1["sequence"] == 1, f"first classification must bear sequence 1, got {c1['sequence']}"

        product_v2 = get_product(product["id"])
        assert product_v2["version"] == 2
        c2 = create_draft_classification(product_v2, classification_code="5A002",
                                         determination_basis="CCATS")
        assert c2["sequence"] == 2, f"second classification must bear sequence 2, got {c2['sequence']}"

        product_v3 = get_product(product["id"])
        assert product_v3["classification_count"] == 2
        assert product_v3["version"] == 3, (
            f"each classification create bumps the product version by 1: expected 3, "
            f"got {product_v3['version']}"
        )

    def test_product_version_increments_on_each_mutation(self, api, analyst_headers):
        """PRD §2.4: "`version` (integer): a system-managed counter that starts at creation and increments by exactly 1 on every mutation of the resource, including mutations driven by cascading side effects originating on another resource."
        PRD §3.1: "On `APPROVE`, the classification becomes `ACTIVE`, `reviewed_by_user_id` is anchored, and three cascades fire in one motion: any other classification of the same product currently `ACTIVE` is pushed to `SUPERSEDED`; the product's `active_classification_id` repoints to the newly active record, its `status` becomes `CLASSIFIED`, and its `version` increments by 1; and an audit record of type `CLASSIFICATION_ACTIVATED` is written against the classification."

        Design: Corner/cross_cutting_layers/product_version_increments_on_each_mutation
        """
        product = create_product(sku="P-071", name="Wire", controlled_content_pct=0,
                                 unit_value_cents=10)
        assert product["version"] == 1, f"product version starts at 1, got {product['version']}"

        classification = create_draft_classification(product)
        submit_classification(classification["id"])
        review_classification(classification["id"], "APPROVE")

        final = get_product(product["id"])
        # +1 for the classification create, +1 for the approval repoint cascade.
        assert final["version"] == 3, (
            f"expected version 3 after create-classification and approval-repoint bumps, "
            f"got {final['version']}"
        )


class TestInvalidReviewStates:
    def test_review_draft_classification_rejected_invalid_state(self, api, analyst_headers,
                                                                manager_headers):
        """PRD §3.1: "Review is a `ComplianceManager` decision (`decision` of `APPROVE` or `REJECT`) against a `SUBMITTED` record, and the reviewer's `X-User-ID` must differ from `submitted_by_user_id` under §2.10's segregation rule, else `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/state_machines/review_draft_classification_rejected_invalid_state
        """
        product = create_product(sku="P-011", name="Washer", controlled_content_pct=0,
                                 unit_value_cents=10)
        classification = create_draft_classification(product)

        res = api.review_classification(classification["id"], {"decision": "APPROVE"},
                                        manager_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

        after = get_success_data(api.get_classification(classification["id"], analyst_headers))
        assert after["status"] == "DRAFT", f"classification must stay DRAFT, got {after['status']}"


class TestSegregationAndRbac:
    def test_sod_classification_self_review_rejected(self, api, analyst_headers):
        """PRD §2.10: "a classification's `submitted_by_user_id` cannot equal its reviewer's `X-User-ID`"
        PRD §2.10: "Any breach is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409)."

        Design: Corner/validations/sod_classification_self_review_rejected
        """
        product = create_product(sku="P-032", name="Rod", controlled_content_pct=0,
                                 unit_value_cents=10)
        classification = create_draft_classification(product)
        # Same X-User-ID submits and (wearing the manager role) reviews.
        submit_classification(classification["id"], headers=make_analyst_headers("user-shared"))
        res = api.review_classification(classification["id"], {"decision": "APPROVE"},
                                        make_manager_headers("user-shared"))
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        after = get_success_data(api.get_classification(classification["id"], analyst_headers))
        assert after["status"] == "SUBMITTED"

    def test_analyst_cannot_review_classification_forbidden(self, api, analyst_headers,
                                                            analyst2_headers):
        """PRD §4: "| POST | `/compliance/classifications/{id}/review` | Approve or reject a submitted classification | ComplianceManager |"
        PRD §2.1: "A request whose role is authenticated but not permitted to call the target endpoint per the authorization matrix in §4 is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/analyst_cannot_review_classification_forbidden
        """
        product = create_product(sku="P-060", name="Cap", controlled_content_pct=0,
                                 unit_value_cents=10)
        classification = create_draft_classification(product)
        submit_classification(classification["id"])  # analyst-1

        res = api.review_classification(classification["id"], {"decision": "APPROVE"},
                                        analyst2_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)


class TestOptimisticConcurrency:
    def test_classification_create_stale_version_returns_412(self, api, analyst_headers):
        """PRD §2.7: "If another writer has advanced the product's version since that observation — for example because another classification activated and repointed the product's `active_classification_id` — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), and no draft is persisted."

        Design: Corner/cross_cutting_layers/classification_create_stale_version_returns_412
        """
        product = create_product(sku="P-070", name="Coil", controlled_content_pct=0,
                                 unit_value_cents=10)
        stale_version = product["version"]  # 1
        create_draft_classification(product)  # succeeds; product version now 2

        res = api.create_classification(
            create_classification_payload(product["id"], stale_version,
                                          classification_code="5A002",
                                          determination_basis="CCATS"),
            analyst_headers,
        )
        validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

        after = get_product(product["id"])
        assert after["classification_count"] == 1, (
            f"the rejected create wrote nothing; classification_count must stay 1, "
            f"got {after['classification_count']}"
        )


class TestRevisionLoop:
    def test_rejected_classification_returns_to_draft(self, api, analyst_headers):
        """PRD §3.1: "Rejection is not the end: an analyst may send a `REJECTED` record back to `DRAFT` through the revision loop, edit, and resubmit."

        Design: Difficulty/non_linear_state_machine/classification_reject_revise_resubmit_cycle
        """
        product = create_product(sku="P-500", name="Valve", controlled_content_pct=10,
                                 unit_value_cents=900)
        classification = create_draft_classification(
            product, jurisdiction="ITAR", classification_code="XI",
        )
        submit_classification(classification["id"])
        rejected = review_classification(classification["id"], "REJECT")
        assert rejected["status"] == "REJECTED"

        revised = get_success_data(api.revise_classification(classification["id"], analyst_headers))
        assert revised["status"] == "DRAFT", (
            f"REJECTED -> DRAFT revision loop must reopen the draft, got {revised['status']}"
        )

    def test_resubmitted_classification_activates_and_audits(self, api, analyst_headers):
        """PRD §3.1: "Rejection is not the end: an analyst may send a `REJECTED` record back to `DRAFT` through the revision loop, edit, and resubmit."
        PRD §3.1: "On `APPROVE`, the classification becomes `ACTIVE`, `reviewed_by_user_id` is anchored, and three cascades fire in one motion: any other classification of the same product currently `ACTIVE` is pushed to `SUPERSEDED`; the product's `active_classification_id` repoints to the newly active record, its `status` becomes `CLASSIFIED`, and its `version` increments by 1; and an audit record of type `CLASSIFICATION_ACTIVATED` is written against the classification."

        Design: Difficulty/non_linear_state_machine/classification_reject_revise_resubmit_cycle
        """
        product = create_product(sku="P-500", name="Valve", controlled_content_pct=10,
                                 unit_value_cents=900)
        classification = create_draft_classification(
            product, jurisdiction="ITAR", classification_code="XI",
        )
        submit_classification(classification["id"])
        review_classification(classification["id"], "REJECT")
        get_success_data(api.revise_classification(classification["id"], analyst_headers))

        submit_classification(classification["id"])
        active = review_classification(classification["id"], "APPROVE")
        assert active["status"] == "ACTIVE", (
            f"second review must activate the classification, got {active['status']}"
        )
        assert_classification(active)

        product_after = get_product(product["id"])
        assert product_after["status"] == "CLASSIFIED"
        assert product_after["active_classification_id"] == classification["id"]

        records = audit_records_for("Classification", classification["id"],
                                    event_type="CLASSIFICATION_ACTIVATED")
        assert len(records) == 1, (
            f"exactly one CLASSIFICATION_ACTIVATED record expected, got {len(records)}"
        )


class TestDeterminationVariantsOnReclassification:
    def _setup_order_between_reclassifications(self, api):
        """EAR99 classification active; order created; product reclassified to ECCN 5A002."""
        product = create_product(sku="P-100", name="Oscillator", controlled_content_pct=50,
                                 unit_value_cents=25000)
        c1 = create_draft_classification(product, classification_code="EAR99")
        submit_classification(c1["id"])
        c1 = review_classification(c1["id"], "APPROVE")

        party = create_party(legal_name="Nordic Retail AB", country_code="SWE",
                             city="Stockholm", party_type="END_USER")
        order = create_order(product["id"], party["id"], destination_country="FRA",
                             end_use="CIVILIAN", quantity=2)

        product_now = get_product(product["id"])
        c2 = create_draft_classification(product_now, classification_code="5A002",
                                         determination_basis="CCATS")
        submit_classification(c2["id"])
        c2 = review_classification(c2["id"], "APPROVE")
        return product, c1, c2, party, order

    def test_determination_diverges_after_reclassification(self, api, ops_headers):
        """PRD §3.4: "The provisional variant is frozen against the classification active at creation; later classification changes never retroactively rewrite it, so the provisional and final outcomes can legitimately diverge."
        PRD §3.6: "Second, it re-runs the determination ladder of §3.4 in its **final** variant against the classification active at submit time, pinning both the resulting `determination` and the `determination_classification_sequence` — the `sequence` of the `ACTIVE` classification used — so the decision remains explainable even after that classification is later superseded."

        Design: Difficulty/dual_variant_calc/determination_provisional_vs_final_on_reclassification
        """
        _, c1, c2, _, order = self._setup_order_between_reclassifications(api)

        submitted = get_success_data(api.submit_order(order["id"], ops_headers))
        assert submitted["provisional_determination"] == "NOT_REQUIRED", (
            f"provisional (EAR99 at creation) must stay NOT_REQUIRED, "
            f"got {submitted['provisional_determination']}"
        )
        assert submitted["determination"] == "LICENSE_REQUIRED", (
            f"final (5A002, pct 50 > 25 for FRA) must be LICENSE_REQUIRED, "
            f"got {submitted['determination']}"
        )
        assert submitted["determination_classification_sequence"] == c2["sequence"] == 2
        assert submitted["status"] == "CLEARED", (
            f"clear screening + non-PROHIBITED determination lands CLEARED, "
            f"got {submitted['status']}"
        )
        assert c1["sequence"] == 1

    def test_superseded_classification_after_repoint(self, api, analyst_headers):
        """PRD §3.1: "On `APPROVE`, the classification becomes `ACTIVE`, `reviewed_by_user_id` is anchored, and three cascades fire in one motion: any other classification of the same product currently `ACTIVE` is pushed to `SUPERSEDED`; the product's `active_classification_id` repoints to the newly active record, its `status` becomes `CLASSIFIED`, and its `version` increments by 1; and an audit record of type `CLASSIFICATION_ACTIVATED` is written against the classification."

        Design: Difficulty/dual_variant_calc/determination_provisional_vs_final_on_reclassification
        """
        product, c1, c2, _, _ = self._setup_order_between_reclassifications(api)

        c1_after = get_success_data(api.get_classification(c1["id"], analyst_headers))
        assert c1_after["status"] == "SUPERSEDED", (
            f"prior ACTIVE classification must be SUPERSEDED, got {c1_after['status']}"
        )
        product_after = get_product(product["id"])
        assert product_after["active_classification_id"] == c2["id"]
        assert product_after["status"] == "CLASSIFIED"

    def test_determination_pinning_survives_reclassification(self, api, ops_headers):
        """PRD §3.6: "Second, it re-runs the determination ladder of §3.4 in its **final** variant against the classification active at submit time, pinning both the resulting `determination` and the `determination_classification_sequence` — the `sequence` of the `ACTIVE` classification used — so the decision remains explainable even after that classification is later superseded."

        Design: Corner/cross_cutting_layers/determination_pinning_survives_reclassification
        """
        product, classification = create_classified_product(
            sku="P-074", name="Mesh", controlled_content_pct=50, unit_value_cents=100,
            classification_code="EAR99",
        )
        party = create_party(legal_name="Sofia Textiles AD", country_code="BGR", city="Sofia")
        order = create_order(product["id"], party["id"], destination_country="BGR",
                             end_use="CIVILIAN", quantity=1)
        submitted = submit_order(order["id"])
        assert submitted["determination"] == "NOT_REQUIRED"
        assert submitted["determination_classification_sequence"] == classification["sequence"]

        # Reclassify the product AFTER the submit pinned the determination.
        product_now = get_product(product["id"])
        c2 = create_draft_classification(product_now, classification_code="5A002",
                                         determination_basis="CCATS")
        submit_classification(c2["id"])
        review_classification(c2["id"], "APPROVE")

        order_after = get_order(order["id"])
        assert order_after["determination"] == "NOT_REQUIRED", (
            f"the pinned final determination must survive reclassification, "
            f"got {order_after['determination']}"
        )
        assert order_after["determination_classification_sequence"] == classification["sequence"] == 1
