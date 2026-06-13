"""Collection volume (estimate vs actual), deduplication partition + invariants,
and the cross-entity precondition that gates collection start.

Difficulty queue: dual_variant_calc (collection_volume), compensating_invariant
(dedup conservation), cross_entity_state_dependency (collection start).
Corner queue: dedup matter-wide, document status filtering.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    fixtures as fx,
)


class TestCollectionVolume:
    def test_collection_summary_estimate_zero_actual_three_after_finish(self, api):
        """PRD §3.4: "The forward-looking estimate sums the expected_doc_count of
        scopes still in DEFINED or COLLECTING — that is, the projected volume of
        data not yet collected. The realized actual sums the collected_actual_count
        of scopes in COLLECTED, PROCESSED, or RELEASED — the chronological count of
        what has actually been collected."

        Design: Difficulty/dual_variant_calc/collection_volume_estimate_vs_actual
        """
        fx.set_clock("2026-06-01T00:00:00Z")
        base = fx.setup_matter_with_acknowledged_custodian(
            caption="Acme v. Beta", bates_prefix="ABC",
            email="alice@x.com", ack_deadline="2026-06-10T00:00:00Z",
        )
        m_id = base["matter"]["id"]
        # One scope finished with 3 ingested documents, expected_doc_count=100.
        fx.setup_collected_scope_with_docs(
            m_id, base["custodian"]["id"],
            content_hashes=["aa", "bb", "aa"],
            expected_doc_count=100,
        )
        resp = api.get_collection_summary(m_id, fx.LEGALOPS)
        data = validate_success(resp, 200)
        assert data["estimate_total"] == 0, (
            f"COLLECTED scope contributes 0 to estimate, got {data['estimate_total']}"
        )
        assert data["actual_total"] == 3, (
            f"3 collected docs -> actual_total 3, got {data['actual_total']}"
        )

    def test_collection_summary_estimate_counts_uncollected_scope(self, api):
        """PRD §3.4: "The forward-looking estimate sums the expected_doc_count of
        scopes still in DEFINED or COLLECTING — that is, the projected volume of
        data not yet collected."

        Design: Difficulty/dual_variant_calc/collection_volume_estimate_vs_actual
        """
        base = fx.setup_matter_with_acknowledged_custodian(
            caption="Est Co", bates_prefix="EST", email="e@x.com",
        )
        m_id = base["matter"]["id"]
        # A DEFINED scope (never started) projects expected_doc_count into estimate.
        fx.create_scope(
            m_id, base["custodian"]["id"], source_label="Future",
            range_start="2026-07-01T00:00:00Z", range_end="2026-07-31T00:00:00Z",
            expected_doc_count=42,
        )
        resp = api.get_collection_summary(m_id, fx.LEGALOPS)
        data = validate_success(resp, 200)
        assert data["estimate_total"] == 42, (
            f"DEFINED scope projects 42 into estimate, got {data['estimate_total']}"
        )
        assert data["actual_total"] == 0, (
            f"nothing collected -> actual_total 0, got {data['actual_total']}"
        )


class TestDedupPartition:
    def test_dedup_conserves_unique_plus_duplicate_equals_total(self, api):
        """PRD §3.5: "The job records unique_count as the number of documents it
        promoted to UNIQUE and duplicate_count as the number it marked DUPLICATE."
        PRD §3.5: "on the transition the server snapshots total_input_count as the
        number of COLLECTED documents under the scope at that moment."

        Design: Difficulty/compensating_invariant/dedup_conserves_unique_plus_duplicate_equals_total
        """
        base = fx.setup_matter_with_acknowledged_custodian(
            caption="Ded Co", bates_prefix="DD", email="a@x.com",
        )
        m_id = base["matter"]["id"]
        # 5 docs: hashes A,B,A,C,B -> 3 unique, 2 duplicate.
        scope, _docs = fx.setup_collected_scope_with_docs(
            m_id, base["custodian"]["id"],
            content_hashes=["A", "B", "A", "C", "B"],
            expected_doc_count=5,
        )
        job = fx.create_job(m_id, scope["id"])
        fx.run_job(job["id"])
        completed = fx.complete_job(job["id"])
        assert completed["unique_count"] == 3, f"got {completed['unique_count']}"
        assert completed["duplicate_count"] == 2, f"got {completed['duplicate_count']}"
        assert completed["total_input_count"] == 5, f"got {completed['total_input_count']}"
        assert (
            completed["unique_count"] + completed["duplicate_count"]
            == completed["total_input_count"]
        ), "partition must conserve the collected total"

    def test_dedup_first_seen_promoted_unique_later_duplicate(self, api):
        """PRD §3.5: "For each document in order, if its content_hash has already
        been seen, the document is marked DUPLICATE and its duplicate_of_id is set
        to the id of the first document that exhibited that hash; otherwise it is
        promoted to UNIQUE and its hash is remembered as first-seen."

        Design: Difficulty/compensating_invariant/dedup_conserves_unique_plus_duplicate_equals_total
        """
        base = fx.setup_matter_with_acknowledged_custodian(
            caption="Ded2 Co", bates_prefix="DE", email="a@x.com",
        )
        m_id = base["matter"]["id"]
        scope, docs = fx.setup_collected_scope_with_docs(
            m_id, base["custodian"]["id"],
            content_hashes=["A", "A"],
            expected_doc_count=2,
        )
        fx.process_scope(m_id, scope["id"])
        first = get_success_data(api.get_document(docs[0]["id"], fx.LEGALOPS))
        second = get_success_data(api.get_document(docs[1]["id"], fx.LEGALOPS))
        assert first["status"] == "UNIQUE", f"first-seen -> UNIQUE, got {first['status']}"
        assert second["status"] == "DUPLICATE", f"later -> DUPLICATE, got {second['status']}"
        assert second["duplicate_of_id"] == first["id"], (
            "duplicate_of_id points at the first-seen document"
        )

    def test_dedup_matter_wide_across_scopes(self, api):
        """PRD §3.5: "The deduplication key is matter-wide: a content_hash that was
        already first-seen by an earlier scope's completed job on the same matter
        makes the new document a DUPLICATE across scopes, pointing at that earlier
        first-seen document."

        Design: Corner/calculations/dedup_matter_wide_across_scopes
        """
        base = fx.setup_matter_with_acknowledged_custodian(
            caption="MW Co", bates_prefix="MW", email="a@x.com",
        )
        m_id, c_id = base["matter"]["id"], base["custodian"]["id"]
        # Scope 1: hash X processed.
        scope1, _ = fx.setup_collected_scope_with_docs(
            m_id, c_id, content_hashes=["X"], expected_doc_count=1,
            source_label="Mbx1", range_start="2026-06-01T00:00:00Z",
            range_end="2026-06-15T00:00:00Z",
        )
        fx.process_scope(m_id, scope1["id"])
        # Scope 2: same hash X — its job must report it DUPLICATE.
        scope2, _ = fx.setup_collected_scope_with_docs(
            m_id, c_id, content_hashes=["X"], expected_doc_count=1,
            source_label="Mbx2", range_start="2026-06-15T00:00:00Z",
            range_end="2026-06-30T00:00:00Z",
        )
        job2 = fx.create_job(m_id, scope2["id"])
        fx.run_job(job2["id"])
        completed = fx.complete_job(job2["id"])
        assert completed["unique_count"] == 0, (
            f"matter-wide dedup -> 0 unique in scope2, got {completed['unique_count']}"
        )
        assert completed["duplicate_count"] == 1, (
            f"matter-wide dedup -> 1 duplicate in scope2, got {completed['duplicate_count']}"
        )


class TestCollectionStartPrecondition:
    def test_collection_start_requires_custodian_acknowledged(self, api):
        """PRD §3.4: "collection that begins before its custodian has acknowledged
        the hold is rejected with ERR_CUSTODIAN_NOT_ACKNOWLEDGED."

        Design: Difficulty/cross_entity_state_dependency/collection_start_requires_custodian_acknowledged
        """
        matter = fx.create_matter(caption="Ack2 Co", bates_prefix="AC")
        custodian = fx.create_custodian(matter["id"], email="a@x.com")
        hold = fx.create_hold(matter["id"])
        fx.issue_hold(hold["id"])
        # Custodian never acknowledges; ack_state stays PENDING.
        scope = fx.create_scope(matter["id"], custodian["id"])
        resp = api.start_collection_scope(scope["id"], fx.LEGALOPS)
        validate_error(resp, ApiErrorId.ERR_CUSTODIAN_NOT_ACKNOWLEDGED.value, 409)

    def test_collection_start_succeeds_when_acknowledged(self, api):
        """PRD §3.4: "Starting collection advances a scope from DEFINED to
        COLLECTING. This requires the scope to be in DEFINED, the matter's hold
        axis to be HOLD_ACTIVE, and — critically — the scope's custodian to have
        already reached ack_state ACKNOWLEDGED; collection that begins before its
        custodian has acknowledged the hold is rejected with
        ERR_CUSTODIAN_NOT_ACKNOWLEDGED."

        Design: Difficulty/cross_entity_state_dependency/collection_start_requires_custodian_acknowledged
        """
        base = fx.setup_matter_with_acknowledged_custodian(
            caption="Ack3 Co", bates_prefix="AD", email="a@x.com",
        )
        scope = fx.create_scope(base["matter"]["id"], base["custodian"]["id"])
        resp = api.start_collection_scope(scope["id"], fx.LEGALOPS)
        data = validate_success(resp, 200)
        assert data["status"] == "COLLECTING", f"got {data['status']}"


class TestDocumentListing:
    def test_list_documents_filtered_by_status_unique(self, api):
        """PRD §3.4: "Documents can later be listed and filtered by scope_id,
        matter_id, status, or by the original they duplicate via duplicate_of_id."

        Design: Corner/endpoints/list_documents_filtered_by_status
        """
        base = fx.setup_matter_with_acknowledged_custodian(
            caption="Filt Co", bates_prefix="FL", email="a@x.com",
        )
        m_id, c_id = base["matter"]["id"], base["custodian"]["id"]
        scope, _ = fx.setup_collected_scope_with_docs(
            m_id, c_id, content_hashes=["Z", "Z"], expected_doc_count=2,
        )
        fx.process_scope(m_id, scope["id"])
        resp = api.list_documents(
            fx.LEGALOPS, params={"scope_id": scope["id"], "status": "UNIQUE"}
        )
        data, _meta = validate_paginated(resp)
        assert len(data) == 1, f"exactly 1 UNIQUE doc expected, got {len(data)}"
        assert all(d["status"] == "UNIQUE" for d in data), "all rows must be UNIQUE"
