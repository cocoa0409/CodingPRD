"""Hold-release cascade, clawback conservation, derived responsive_doc_count,
OCC stale-version, and terminal-state lockdown.

Difficulty queue: transitive_cascade (release-hold depth-4), compensating_invariant
(clawback conserves produced+clawed).
Corner / cross-cutting queue: derived responsive_doc_count, stale-version clawback,
dispute keeps item PRODUCED, terminal closed matter lockdown.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    fixtures as fx,
)


class TestReleaseHoldCascade:
    def _setup_processed_matter_in_closing(self, caption, prefix):
        """Matter -> acknowledged custodian -> collect 1 UNIQUE + 1 DUPLICATE doc ->
        process (scope PROCESSED, matter IN_DISCOVERY) -> begin-close (CLOSING).
        Returns dict(matter, custodian, hold, scope, docs)."""
        base = fx.setup_matter_with_acknowledged_custodian(
            caption=caption, bates_prefix=prefix, email="a@x.com",
        )
        m_id, c_id = base["matter"]["id"], base["custodian"]["id"]
        scope, docs, _job = fx.setup_processed_scope(
            m_id, c_id, ["h1", "h1"], expected_doc_count=2,
        )
        get_success_data(fx.api_client.begin_close_matter(m_id, fx.LEGALOPS))
        return {
            "matter": base["matter"], "custodian": base["custodian"],
            "hold": base["hold"], "scope": scope, "docs": docs,
        }

    def test_release_hold_cascades_matter_to_documents(self, api):
        """PRD §2.5: "Releasing a matter's hold (hop 1) drives the matter's active
        hold notice to RELEASED. That hold release (hop 2) drives every collection
        scope on the matter that is in COLLECTED or PROCESSED to RELEASED. Each scope
        release (hop 3) marks every document under that scope that is not already
        PURGEABLE as PURGEABLE and sets the owning custodian's retention_released flag
        to true."

        Design: Difficulty/transitive_cascade/release_hold_cascades_matter_to_documents_depth4
        """
        ctx = self._setup_processed_matter_in_closing("Rel Co", "RL")
        m_id = ctx["matter"]["id"]
        resp = api.release_hold(m_id, fx.LEGALOPS)
        matter = validate_success(resp, 200)
        assert matter["hold_status"] == "HOLD_RELEASED", f"got {matter['hold_status']}"
        # hop 1: legal hold -> RELEASED
        hold = get_success_data(api.get_legal_hold(ctx["hold"]["id"], fx.LEGALOPS))
        assert hold["status"] == "RELEASED", f"hold should be RELEASED, got {hold['status']}"
        # hop 2: scope -> RELEASED
        scope = get_success_data(api.get_collection_scope(ctx["scope"]["id"], fx.LEGALOPS))
        assert scope["status"] == "RELEASED", f"scope should be RELEASED, got {scope['status']}"
        # hop 3: every document -> PURGEABLE
        for d in ctx["docs"]:
            doc = get_success_data(api.get_document(d["id"], fx.LEGALOPS))
            assert doc["status"] == "PURGEABLE", (
                f"doc {d['id']} should be PURGEABLE, got {doc['status']}"
            )

    def test_release_hold_sets_custodian_retention_released(self, api):
        """PRD §2.5: "Each scope release (hop 3) marks every document under that scope
        that is not already PURGEABLE as PURGEABLE and sets the owning custodian's
        retention_released flag to true."

        Design: Difficulty/transitive_cascade/release_hold_cascades_matter_to_documents_depth4
        """
        ctx = self._setup_processed_matter_in_closing("Rel2 Co", "RM")
        m_id = ctx["matter"]["id"]
        api.release_hold(m_id, fx.LEGALOPS)
        custodian = get_success_data(api.get_custodian(ctx["custodian"]["id"], fx.LEGALOPS))
        assert custodian["retention_released"] is True, (
            "custodian.retention_released must be true after the cascade"
        )


class TestClawbackConservation:
    def test_clawback_conserves_produced_plus_clawed_total(self, api):
        """PRD §3.8: "on sequester the server retires the item by moving it from
        PRODUCED to CLAWED_BACK, re-tags the item's document privilege_tag to
        PRIVILEGED, and recomputes the matter's produced_document_count and
        clawed_back_document_count so that the produced-plus-clawed-back total is
        conserved."

        Design: Difficulty/compensating_invariant/clawback_conserves_produced_plus_clawed_total
        """
        bundle = fx.setup_produced_set_from_responsive_docs(
            caption="Inv Co", bates_prefix="IV", num_docs=2,
        )
        m_id = bundle["matter"]["id"]
        ps = bundle["production_set"]
        item_id = bundle["items"][0]["id"]
        cb = fx.file_clawback(m_id, item_id, ps["version"], reason="inadvertent")
        fx.sequester(cb["id"])
        matter = get_success_data(api.get_matter(m_id, fx.LEGALOPS))
        assert matter["produced_document_count"] == 1, (
            f"got {matter['produced_document_count']}"
        )
        assert matter["clawed_back_document_count"] == 1, (
            f"got {matter['clawed_back_document_count']}"
        )
        assert (
            matter["produced_document_count"] + matter["clawed_back_document_count"] == 2
        ), "produced + clawed-back must conserve the 2 ever produced"

    def test_sequester_retires_item_to_clawed_back(self, api):
        """PRD §3.8: "on sequester the server retires the item by moving it from
        PRODUCED to CLAWED_BACK, re-tags the item's document privilege_tag to
        PRIVILEGED, and recomputes the matter's produced_document_count and
        clawed_back_document_count so that the produced-plus-clawed-back total is
        conserved."

        Design: Difficulty/compensating_invariant/clawback_conserves_produced_plus_clawed_total
        """
        bundle = fx.setup_produced_set_from_responsive_docs(
            caption="Inv2 Co", bates_prefix="IW", num_docs=2,
        )
        m_id = bundle["matter"]["id"]
        ps = bundle["production_set"]
        item_id = bundle["items"][0]["id"]
        cb = fx.file_clawback(m_id, item_id, ps["version"], reason="inadvertent")
        fx.sequester(cb["id"])
        item = get_success_data(api.get_production_item(item_id, fx.LEGALOPS))
        assert item["status"] == "CLAWED_BACK", (
            f"sequestered item should be CLAWED_BACK, got {item['status']}"
        )


class TestDerivedResponsiveDocCount:
    def test_responsive_doc_count_after_batch_complete(self, api):
        """PRD §3.6: "Completion then recomputes the matter's responsive_doc_count as
        the number of this matter's UNIQUE documents whose responsiveness_tag is
        RESPONSIVE across all completed batches."

        Design: Corner/cross_cutting_complexity_layers/derived_responsive_doc_count_after_batch_complete
        """
        base = fx.setup_matter_with_acknowledged_custodian(
            caption="Resp Co", bates_prefix="RP", email="a@x.com",
        )
        m_id, c_id = base["matter"]["id"], base["custodian"]["id"]
        scope, docs, _job = fx.setup_processed_scope(
            m_id, c_id, ["r1", "r2"], expected_doc_count=2,
        )
        fx.setup_completed_batch(m_id, docs, ["RESPONSIVE_NOT_PRIV", "RESPONSIVE_NOT_PRIV"])
        matter = get_success_data(api.get_matter(m_id, fx.LEGALOPS))
        assert matter["responsive_doc_count"] == 2, (
            f"both UNIQUE docs responsive -> 2, got {matter['responsive_doc_count']}"
        )


class TestClawbackResolutionAndConcurrency:
    def test_stale_version_clawback_rejected(self, api):
        """PRD §3.8: "The version check is the optimistic-concurrency guard of §2.6:
        if the supplied expected_production_set_version does not match the parent set's
        current version, the filing is rejected with ERR_STALE_VERSION."
        PRD §3.8: "A successful filing creates the clawback in REQUESTED status and
        increments the parent production set's version by one (which is why a second
        clawback filed against a stale view of the same set fails the version check)."

        Design: Corner/errors/stale_version_clawback_excluded
        """
        bundle = fx.setup_produced_set_from_responsive_docs(
            caption="Stale Co", bates_prefix="ST", num_docs=2,
        )
        m_id = bundle["matter"]["id"]
        ps = bundle["production_set"]
        items = bundle["items"]
        observed_version = ps["version"]
        # First clawback succeeds and bumps the set version.
        cb1 = fx.file_clawback(m_id, items[0]["id"], observed_version, reason="first")
        fx.sequester(cb1["id"])
        # Second filing carries the now-stale observed_version.
        resp = api.create_clawback(
            {
                "matter_id": m_id,
                "production_item_id": items[1]["id"],
                "reason": "stale",
                "expected_production_set_version": observed_version,
            },
            fx.PRODUCER,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, 412)

    def test_dispute_clawback_keeps_item_produced(self, api):
        """PRD §3.8: "a LegalOps operator may dispute a requested clawback, advancing
        it from REQUESTED to DISPUTED; the production item then stays PRODUCED."

        Design: Corner/state_machines/dispute_clawback_keeps_item_produced
        """
        bundle = fx.setup_produced_set_from_responsive_docs(
            caption="Disp Co", bates_prefix="DS", num_docs=1,
        )
        m_id = bundle["matter"]["id"]
        ps = bundle["production_set"]
        item_id = bundle["items"][0]["id"]
        cb = fx.file_clawback(m_id, item_id, ps["version"], reason="review")
        disputed = get_success_data(api.dispute_clawback(cb["id"], fx.LEGALOPS))
        assert disputed["status"] == "DISPUTED", f"got {disputed['status']}"
        item = get_success_data(api.get_production_item(item_id, fx.LEGALOPS))
        assert item["status"] == "PRODUCED", (
            f"disputed clawback leaves item PRODUCED, got {item['status']}"
        )


class TestTerminalLockdown:
    def test_terminal_closed_matter_rejects_further_transition(self, api):
        """PRD §3.9: "Closing the matter advances the lifecycle from CLOSING to
        CLOSED, the terminal state."

        Design: Corner/state_machines/terminal_closed_matter_rejects_further_transition
        """
        # Drive a matter all the way to CLOSED.
        base = fx.setup_matter_with_acknowledged_custodian(
            caption="Term Co", bates_prefix="TM", email="a@x.com",
        )
        m_id, c_id = base["matter"]["id"], base["custodian"]["id"]
        scope, _docs = fx.setup_collected_scope_with_docs(
            m_id, c_id, content_hashes=["h1"], expected_doc_count=1,
        )
        fx.process_scope(m_id, scope["id"])  # matter -> IN_DISCOVERY
        get_success_data(api.begin_close_matter(m_id, fx.LEGALOPS))  # CLOSING
        get_success_data(api.release_hold(m_id, fx.LEGALOPS))  # HOLD_RELEASED
        get_success_data(api.close_matter(m_id, fx.LEGALOPS))  # CLOSED
        # begin-close on a CLOSED matter is undefined.
        resp = api.begin_close_matter(m_id, fx.LEGALOPS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
