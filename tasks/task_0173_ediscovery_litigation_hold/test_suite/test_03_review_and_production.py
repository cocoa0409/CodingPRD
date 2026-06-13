"""Review-batch cycle, validation fork, Bates allocation and production cost.

Difficulty queue: non_linear_state_machine (QC bounce-back, validate fork),
combinatorial_formula (production cost per-doc-then-sum), resource_temporal_overlap
(contiguous Bates ranges), boundary_precision (validate empty set),
cross_entity_state_dependency (validate requires batch COMPLETED).
Corner queue: bates zero-pad label, submit-qc precondition, open-review empty,
privileged doc rejected, non-unique doc rejected.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    fixtures as fx,
)


def _processed_unique_docs(caption, prefix, hashes, page_counts=None, email="a@x.com"):
    """Helper: matter -> acknowledged custodian -> collect+process docs.
    Returns (matter, custodian, scope, [refreshed docs])."""
    base = fx.setup_matter_with_acknowledged_custodian(
        caption=caption, bates_prefix=prefix, email=email,
    )
    m_id, c_id = base["matter"]["id"], base["custodian"]["id"]
    scope, docs, _job = fx.setup_processed_scope(
        m_id, c_id, hashes, page_counts=page_counts, expected_doc_count=len(hashes),
    )
    return base["matter"], base["custodian"], scope, docs


class TestReviewBatchCycle:
    def test_qc_bounce_back_revisits_in_review(self, api):
        """PRD §3.6: "A batch in QC_REVIEW may be reopened back to IN_REVIEW (the
        revision loop, during which reviewers may change their decisions) or
        completed."

        Design: Difficulty/non_linear_state_machine/review_batch_qc_bounce_back_cycle
        """
        matter, _c, _s, docs = _processed_unique_docs("Cyc Co", "CY", ["h1"], page_counts=[2])
        batch = fx.create_batch(matter["id"], name="B1")
        review = fx.add_review(batch["id"], docs[0]["id"])
        fx.open_review(batch["id"])
        fx.decide(review["id"], "RESPONSIVE_NOT_PRIV")
        fx.submit_qc(batch["id"])  # IN_REVIEW -> QC_REVIEW
        # Reopen returns to IN_REVIEW.
        reopened = get_success_data(api.reopen_review(batch["id"], fx.REVIEWLEAD))
        assert reopened["status"] == "IN_REVIEW", (
            f"reopen must return to IN_REVIEW, got {reopened['status']}"
        )

    def test_qc_bounce_back_then_resubmit_returns_to_qc_review(self, api):
        """PRD §3.6: "Submitting the batch to QC advances it from IN_REVIEW to
        QC_REVIEW; this is permitted only when every document has been decided —
        that is, when reviewed_count equals document_count."

        Design: Difficulty/non_linear_state_machine/review_batch_qc_bounce_back_cycle
        """
        matter, _c, _s, docs = _processed_unique_docs("Cyc2 Co", "CZ", ["h1"], page_counts=[2])
        batch = fx.create_batch(matter["id"], name="B1")
        review = fx.add_review(batch["id"], docs[0]["id"])
        fx.open_review(batch["id"])
        fx.decide(review["id"], "RESPONSIVE_NOT_PRIV")
        fx.submit_qc(batch["id"])
        fx.reopen(batch["id"])
        # Second submit-qc back to QC_REVIEW (same row revisits QC_REVIEW).
        resubmitted = get_success_data(api.submit_qc(batch["id"], fx.REVIEWLEAD))
        assert resubmitted["status"] == "QC_REVIEW", (
            f"second submit-qc returns to QC_REVIEW, got {resubmitted['status']}"
        )

    def test_submit_qc_before_all_reviewed_rejected(self, api):
        """PRD §3.6: "Submitting while some documents remain undecided is rejected
        with ERR_BATCH_NOT_FULLY_REVIEWED."

        Design: Corner/state_machines/submit_qc_before_all_reviewed_rejected
        """
        matter, _c, _s, docs = _processed_unique_docs("Sub Co", "SB", ["h1"])
        batch = fx.create_batch(matter["id"], name="B1")
        fx.add_review(batch["id"], docs[0]["id"])
        fx.open_review(batch["id"])
        # No decision recorded; reviewed_count(0) < document_count(1).
        resp = api.submit_qc(batch["id"], fx.REVIEWLEAD)
        validate_error(resp, ApiErrorId.ERR_BATCH_NOT_FULLY_REVIEWED.value, 409)

    def test_open_review_empty_batch_rejected(self, api):
        """PRD §3.6: "an attempt to open an empty batch is rejected with
        ERR_EMPTY_BATCH."

        Design: Corner/state_machines/open_review_empty_batch_rejected
        """
        matter = fx.create_matter(caption="Emp Co", bates_prefix="EB")
        batch = fx.create_batch(matter["id"], name="B1")
        resp = api.open_review(batch["id"], fx.REVIEWLEAD)
        validate_error(resp, ApiErrorId.ERR_EMPTY_BATCH.value, 409)

    def test_review_nonunique_document_rejected(self, api):
        """PRD §3.6: "an attempt to add a non-unique document, or one from a
        different matter, is rejected with ERR_DOCUMENT_NOT_UNIQUE."

        Design: Corner/validations/review_nonunique_document_rejected
        """
        base = fx.setup_matter_with_acknowledged_custodian(
            caption="NU Co", bates_prefix="NU", email="a@x.com",
        )
        m_id, c_id = base["matter"]["id"], base["custodian"]["id"]
        scope, _docs = fx.setup_collected_scope_with_docs(
            m_id, c_id, content_hashes=["DUP", "DUP"], expected_doc_count=2,
        )
        fx.process_scope(m_id, scope["id"])
        # Find the DUPLICATE document.
        dup_list, _ = fx._list(
            api.list_documents(fx.LEGALOPS, params={"scope_id": scope["id"], "status": "DUPLICATE"})
        )
        assert dup_list, "expected a DUPLICATE document"
        batch = fx.create_batch(m_id, name="B1")
        resp = api.add_review(
            batch["id"], {"document_id": dup_list[0]["id"]}, fx.REVIEWLEAD
        )
        validate_error(resp, ApiErrorId.ERR_DOCUMENT_NOT_UNIQUE.value, 422)


class TestValidationFork:
    def test_validate_clean_set_forks_to_staged_with_bates(self, api):
        """PRD §3.7: "If no item's document is PRIVILEGED, the set moves to STAGED,
        and on that clean staging the server allocates Bates numbers and computes
        cost: it sets bates_start to the matter's current next_bates_seq, assigns
        each item a sequential bates_number in ascending document-created_at order,
        sets bates_end to the last number used (the start plus item_count minus one),
        advances the matter's next_bates_seq to one past bates_end, and computes
        produced_page_count via the per-document-then-sum cost rule of §2.7."

        Design: Difficulty/non_linear_state_machine/production_set_validate_fork_blocked_vs_staged
        """
        matter, _c, _s, docs = _processed_unique_docs(
            "Fork Co", "FK", ["h1", "h2"], page_counts=[2, 2],
        )
        # Decide d1 non-priv, d2 RESPONSIVE_PRIV; produce set of only d1 (clean).
        batch, _reviews = fx.setup_completed_batch(
            matter["id"], docs, ["RESPONSIVE_NOT_PRIV", "RESPONSIVE_PRIV"],
        )
        ps = fx.create_production_set(matter["id"], batch["id"])
        fx.add_item(ps["id"], docs[0]["id"])
        validated = get_success_data(api.validate_production_set(ps["id"], fx.PRODUCER))
        assert validated["status"] == "STAGED", (
            f"clean set forks to STAGED, got {validated['status']}"
        )
        assert validated["bates_start"] == 1, (
            f"first staged set starts Bates at 1, got {validated['bates_start']}"
        )

    def test_validate_clean_set_allocates_bates_end_and_advances_counter(self, api):
        """PRD §3.7: "it sets bates_start to the matter's current next_bates_seq,
        assigns each item a sequential bates_number in ascending document-created_at
        order, sets bates_end to the last number used (the start plus item_count minus
        one), advances the matter's next_bates_seq to one past bates_end, and computes
        produced_page_count via the per-document-then-sum cost rule of §2.7."

        Design: Difficulty/non_linear_state_machine/production_set_validate_fork_blocked_vs_staged
        """
        # Clean (no PRIVILEGED item) two-doc set takes the STAGED branch, whose
        # divergent side-effect (Bates allocation) distinguishes it from the BLOCKED
        # branch which performs no allocation.
        matter, _c, _s, docs = _processed_unique_docs(
            "Fork2 Co", "FX", ["h1", "h2"], page_counts=[1, 1],
        )
        batch, _reviews = fx.setup_completed_batch(
            matter["id"], docs, ["RESPONSIVE_NOT_PRIV", "RESPONSIVE_NOT_PRIV"],
        )
        staged = fx.setup_staged_set(matter["id"], batch["id"], [d["id"] for d in docs])
        assert staged["status"] == "STAGED", f"got {staged['status']}"
        assert staged["bates_end"] == 2, (
            f"bates_end = start(1) + item_count(2) - 1 = 2, got {staged['bates_end']}"
        )
        refreshed_matter = get_success_data(api.get_matter(matter["id"], fx.LEGALOPS))
        assert refreshed_matter["next_bates_seq"] == 3, (
            f"next_bates_seq advances to one past bates_end, got "
            f"{refreshed_matter['next_bates_seq']}"
        )

    def test_validate_empty_production_set_rejected(self, api):
        """PRD §3.7: "Validating the set advances it from DRAFT to VALIDATING. This
        requires the set to be DRAFT, to hold at least one item (validating an empty
        set is rejected with ERR_EMPTY_PRODUCTION_SET), and its source batch to be
        COMPLETED (validating against a batch that is not yet completed is rejected
        with ERR_BATCH_NOT_COMPLETED)."

        Design: Difficulty/boundary_precision_check/validate_empty_production_set_rejected
        """
        matter, _c, _s, docs = _processed_unique_docs("EmpP Co", "EP", ["h1"])
        batch, _reviews = fx.setup_completed_batch(
            matter["id"], docs, ["RESPONSIVE_NOT_PRIV"],
        )
        ps = fx.create_production_set(matter["id"], batch["id"])
        # No items added.
        resp = api.validate_production_set(ps["id"], fx.PRODUCER)
        validate_error(resp, ApiErrorId.ERR_EMPTY_PRODUCTION_SET.value, 409)

    def test_validate_requires_batch_completed(self, api):
        """PRD §3.7: "Validating the set advances it from DRAFT to VALIDATING. This
        requires the set to be DRAFT, to hold at least one item (validating an empty
        set is rejected with ERR_EMPTY_PRODUCTION_SET), and its source batch to be
        COMPLETED (validating against a batch that is not yet completed is rejected
        with ERR_BATCH_NOT_COMPLETED)."

        Design: Difficulty/cross_entity_state_dependency/production_validate_requires_batch_completed
        """
        matter, _c, _s, docs = _processed_unique_docs("Dep Co", "DP", ["h1"])
        m_id = matter["id"]
        # Drive the batch only to QC_REVIEW (not COMPLETED).
        batch = fx.create_batch(m_id, name="B1")
        review = fx.add_review(batch["id"], docs[0]["id"])
        fx.open_review(batch["id"])
        fx.decide(review["id"], "RESPONSIVE_NOT_PRIV")
        fx.submit_qc(batch["id"])  # QC_REVIEW
        ps = fx.create_production_set(m_id, batch["id"])
        fx.add_item(ps["id"], docs[0]["id"])
        resp = api.validate_production_set(ps["id"], fx.PRODUCER)
        validate_error(resp, ApiErrorId.ERR_BATCH_NOT_COMPLETED.value, 409)

    def test_validate_non_empty_set_from_completed_batch_succeeds(self, api):
        """PRD §3.7: "Validating the set advances it from DRAFT to VALIDATING. This
        requires the set to be DRAFT, to hold at least one item (validating an empty
        set is rejected with ERR_EMPTY_PRODUCTION_SET), and its source batch to be
        COMPLETED (validating against a batch that is not yet completed is rejected
        with ERR_BATCH_NOT_COMPLETED)."

        Design: Difficulty/boundary_precision_check/validate_empty_production_set_rejected
        """
        # Boundary X+1: a set with exactly one item (non-empty) validates cleanly.
        matter, _c, _s, docs = _processed_unique_docs("NonE Co", "NE", ["h1"])
        batch, _reviews = fx.setup_completed_batch(
            matter["id"], docs, ["RESPONSIVE_NOT_PRIV"],
        )
        ps = fx.create_production_set(matter["id"], batch["id"])
        fx.add_item(ps["id"], docs[0]["id"])  # item_count == 1
        validated = get_success_data(api.validate_production_set(ps["id"], fx.PRODUCER))
        assert validated["status"] == "STAGED", (
            f"a one-item clean set validates to STAGED, got {validated['status']}"
        )

    def test_validate_requires_batch_completed_draft_batch(self, api):
        """PRD §3.7: "Validating the set advances it from DRAFT to VALIDATING. This
        requires the set to be DRAFT, to hold at least one item (validating an empty
        set is rejected with ERR_EMPTY_PRODUCTION_SET), and its source batch to be
        COMPLETED (validating against a batch that is not yet completed is rejected
        with ERR_BATCH_NOT_COMPLETED)."

        Design: Difficulty/cross_entity_state_dependency/production_validate_requires_batch_completed
        """
        # A different not-COMPLETED batch state (DRAFT) also blocks validate.
        matter, _c, _s, docs = _processed_unique_docs("Dep2 Co", "DQ", ["h1"])
        m_id = matter["id"]
        batch = fx.create_batch(m_id, name="B1")
        fx.add_review(batch["id"], docs[0]["id"])  # batch stays DRAFT
        ps = fx.create_production_set(m_id, batch["id"])
        fx.add_item(ps["id"], docs[0]["id"])
        resp = api.validate_production_set(ps["id"], fx.PRODUCER)
        validate_error(resp, ApiErrorId.ERR_BATCH_NOT_COMPLETED.value, 409)

    def test_add_privileged_document_to_production_rejected(self, api):
        """PRD §3.7: "A document already tagged PRIVILEGED may not be added as a
        production item — that attempt is rejected with ERR_PRIVILEGED_DOCUMENT."

        Design: Corner/validations/add_privileged_document_to_production_rejected
        """
        matter, _c, _s, docs = _processed_unique_docs("Priv Co", "PV", ["h1"])
        batch, _reviews = fx.setup_completed_batch(
            matter["id"], docs, ["RESPONSIVE_PRIV"],
        )
        # On complete, d1's privilege_tag is frozen to PRIVILEGED.
        ps = fx.create_production_set(matter["id"], batch["id"])
        resp = api.add_production_item(ps["id"], {"document_id": docs[0]["id"]}, fx.PRODUCER)
        validate_error(resp, ApiErrorId.ERR_PRIVILEGED_DOCUMENT.value, 422)


class TestProductionCost:
    def test_production_cost_round_per_doc_then_sum(self, api):
        """PRD §2.7: "For each document in a staged set, multiply its page_count by
        the per-page rate of 7.3 cents and round that product half-up to a whole
        number of cents; then sum those already-rounded per-document amounts to
        obtain the set's produced_page_count."

        Design: Difficulty/combinatorial_formula/production_cost_round_per_doc_then_sum
        """
        matter, _c, _s, docs = _processed_unique_docs(
            "Cost Co", "CC", ["h1", "h2", "h3"], page_counts=[1, 1, 1],
        )
        batch, _reviews = fx.setup_completed_batch(
            matter["id"], docs, ["RESPONSIVE_NOT_PRIV"] * 3,
        )
        staged = fx.setup_staged_set(matter["id"], batch["id"], [d["id"] for d in docs])
        # round(7.3)=7 per doc * 3 = 21 (NOT round(21.9)=22).
        assert staged["status"] == "STAGED", f"got {staged['status']}"
        assert staged["produced_page_count"] == 21, (
            f"round-per-doc-then-sum must be 21, got {staged['produced_page_count']}"
        )

    def test_production_cost_multi_page_rounds_per_document(self, api):
        """PRD §2.7: "For each document in a staged set, multiply its page_count by
        the per-page rate of 7.3 cents and round that product half-up to a whole
        number of cents; then sum those already-rounded per-document amounts to
        obtain the set's produced_page_count."

        Design: Difficulty/combinatorial_formula/production_cost_round_per_doc_then_sum
        """
        # Two docs, 10 pages and 3 pages: round(73.0)=73, round(21.9)=22 -> 95.
        # Sum-then-round of 73.0 + 21.9 = 94.9 -> 95 here happens to match, so pick
        # page counts where the orders diverge: 1 page (round 7.3->7) and 2 pages
        # (round 14.6->15): per-doc 7+15=22; sum-then-round round(21.9)=22 also.
        # Use 4 docs of 1 page each: per-doc round(7.3)=7 *4 = 28; sum-then-round
        # round(29.2)=29 — divergent. Pin per-document-then-sum == 28.
        matter, _c, _s, docs = _processed_unique_docs(
            "Cost2 Co", "CD", ["h1", "h2", "h3", "h4"], page_counts=[1, 1, 1, 1],
        )
        batch, _reviews = fx.setup_completed_batch(
            matter["id"], docs, ["RESPONSIVE_NOT_PRIV"] * 4,
        )
        staged = fx.setup_staged_set(matter["id"], batch["id"], [d["id"] for d in docs])
        assert staged["produced_page_count"] == 28, (
            f"4 * round(7.3)=4*7=28 (not round(29.2)=29), got "
            f"{staged['produced_page_count']}"
        )


class TestBatesAllocation:
    def test_two_sets_get_contiguous_non_overlapping_bates_ranges(self, api):
        """PRD §2.7: "Each time a production set is staged, it draws its block of
        sequence numbers starting at the matter's current next_bates_seq, and the
        counter advances past the block so that the next set continues exactly where
        this one ended. There are no gaps and no reuse across sets within a matter."

        Design: Difficulty/resource_temporal_overlap/bates_range_contiguous_no_overlap_integer
        """
        base = fx.setup_matter_with_acknowledged_custodian(
            caption="Bat Co", bates_prefix="BT", email="a@x.com",
        )
        m_id, c_id = base["matter"]["id"], base["custodian"]["id"]
        scope, docs, _job = fx.setup_processed_scope(
            m_id, c_id, ["p1", "p2", "p3", "p4"], expected_doc_count=4,
        )
        # Batch 1 over d1,d2 -> set1 staged [1,2].
        batch1, _ = fx.setup_completed_batch(
            m_id, docs[:2], ["RESPONSIVE_NOT_PRIV"] * 2, name="B1",
        )
        set1 = fx.setup_staged_set(m_id, batch1["id"], [docs[0]["id"], docs[1]["id"]])
        # Batch 2 over d3,d4 -> set2 staged [3,4].
        batch2, _ = fx.setup_completed_batch(
            m_id, docs[2:], ["RESPONSIVE_NOT_PRIV"] * 2, name="B2",
        )
        set2 = fx.setup_staged_set(m_id, batch2["id"], [docs[2]["id"], docs[3]["id"]])
        assert set1["bates_start"] == 1 and set1["bates_end"] == 2, (
            f"set1 should be [1,2], got [{set1['bates_start']},{set1['bates_end']}]"
        )
        assert set2["bates_start"] == 3 and set2["bates_end"] == 4, (
            f"set2 should be [3,4] contiguous, got [{set2['bates_start']},{set2['bates_end']}]"
        )
        # Contiguity invariant: no gap and no shared number across the two sets.
        assert set2["bates_start"] == set1["bates_end"] + 1, (
            "second set must start exactly one past the first set's end (no gap)"
        )

    def test_second_set_labels_continue_sequence_without_reuse(self, api):
        """PRD §2.7: "the counter advances past the block so that the next set
        continues exactly where this one ended. There are no gaps and no reuse across
        sets within a matter."

        Design: Difficulty/resource_temporal_overlap/bates_range_contiguous_no_overlap_integer
        """
        base = fx.setup_matter_with_acknowledged_custodian(
            caption="Bat2 Co", bates_prefix="BU", email="a@x.com",
        )
        m_id, c_id = base["matter"]["id"], base["custodian"]["id"]
        scope, docs, _job = fx.setup_processed_scope(
            m_id, c_id, ["p1", "p2"], expected_doc_count=2,
        )
        batch1, _ = fx.setup_completed_batch(m_id, docs[:1], ["RESPONSIVE_NOT_PRIV"], name="B1")
        set1 = fx.setup_staged_set(m_id, batch1["id"], [docs[0]["id"]])
        batch2, _ = fx.setup_completed_batch(m_id, docs[1:], ["RESPONSIVE_NOT_PRIV"], name="B2")
        set2 = fx.setup_staged_set(m_id, batch2["id"], [docs[1]["id"]])
        items1 = fx.list_items_on_set(set1["id"])
        items2 = fx.list_items_on_set(set2["id"])
        # No reuse: the two labels are distinct and consecutive (BU000001, BU000002).
        assert items1[0]["bates_number"] == "BU000001", f"got {items1[0]['bates_number']}"
        assert items2[0]["bates_number"] == "BU000002", f"got {items2[0]['bates_number']}"

    def test_bates_label_zero_padded_six_digits(self, api):
        """PRD §2.7: "Each allocated number is rendered as a label by concatenating
        the matter's bates_prefix with the sequence number zero-padded to six digits
        (for example, prefix ABC and sequence 1 yields ABC000001)."

        Design: Corner/calculations/bates_label_zero_padded_six_digits
        """
        matter, _c, _s, docs = _processed_unique_docs("Lbl Co", "AA", ["h1"])
        batch, _reviews = fx.setup_completed_batch(
            matter["id"], docs, ["RESPONSIVE_NOT_PRIV"],
        )
        staged = fx.setup_staged_set(matter["id"], batch["id"], [docs[0]["id"]])
        items = fx.list_items_on_set(staged["id"])
        first = items[0]
        assert first["bates_number"] == "AA000001", (
            f"first item label must be AA000001, got {first['bates_number']}"
        )
