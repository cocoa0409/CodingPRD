"""Transitive cascades and audit-trail integrity (PRD §2.7, §2.8, §3.4)."""
from test_helpers import (
    ApiErrorId,
    create_active_phase_i_exemption,
    get_aggregation_for,
    get_single_ctr_for_customer,
    get_success_data,
    list_ctrs_for_customer,
    make_analyst_headers,
    make_officer_headers,
    post_cash_txn,
    set_clock,
    setup_branch_and_customer,
    api_client,
    validate_error,
)


class TestTxnCreateToCtrAmendmentRequiredCascade:
    def test_txn_create_to_ctr_amendment_required_cascade(self, api):
        """PRD §3.4: "Aggregation recompute feeds a second derivation, CTR
        reportability, which may in turn create, void, or flag CTR records
        without any client request."
        PRD §3.4: "when the recomputed totals diverge from the frozen snapshot of
        a CTR in `FILED` or `ACKNOWLEDGED`, that CTR is transitioned to
        `AMENDMENT_REQUIRED`. Each automatic transition appends its own audit
        event with the `SYSTEM_AUTO` action per §2.7."

        Design: Difficulty/transitive_cascade/txn_create_to_ctr_amendment_required_cascade
        """
        set_clock("2026-08-01T12:00:00Z")
        from test_helpers import create_branch, create_customer
        br1 = create_branch(name="Main", branch_code="BR1")
        c1 = create_customer(legal_name="Cascade One", tin="88-8888888")
        post_cash_txn(c1["id"], br1["id"], amount_cents=1_100_000,
                      occurred_at="2026-08-01T10:00:00Z")
        ctr = get_single_ctr_for_customer(c1["id"])
        get_success_data(api_client.validate_ctr(ctr["id"], headers=make_analyst_headers("analyst-x")))
        get_success_data(api_client.file_ctr(
            ctr["id"], {"filing_channel": "EFILE"}, headers=make_officer_headers("officer-y"),
        ))
        set_clock("2026-08-01T15:00:00Z")
        post_cash_txn(c1["id"], br1["id"], amount_cents=250_000,
                      occurred_at="2026-08-01T14:00:00Z")
        agg = get_aggregation_for(c1["id"], "2026-08-01")
        assert agg["total_cash_in_cents"] == 1_350_000
        ctr_after = get_success_data(api_client.get_ctr(ctr["id"], headers=make_officer_headers()))
        assert ctr_after["status"] == "AMENDMENT_REQUIRED"
        # CTR history: auto-create + validate + file + auto-AMENDMENT_REQUIRED = 4 events
        resp = api_client.list_audit_events(
            headers=make_officer_headers(),
            params={"entity_type": "CTR", "entity_id": ctr["id"]},
        )
        assert resp.json()["meta"]["total_count"] == 4
        # Chain integrity holds across the cascade
        chain = get_success_data(api_client.verify_audit_chain(headers=make_officer_headers()))
        assert chain["chain_valid"] is True

    def test_cascade_appends_system_auto_event(self, api):
        """PRD §2.7: "Automatic system mutations append one additional AuditEvent
        each: CTR auto-creation, auto-voiding of a no-longer-required CTR, and
        auto-flagging of a diverged CTR as amendment-required each append an
        event with `actor_role` set to `SYSTEM` and `action` set to `SYSTEM_AUTO`."

        Independent confirmation that the auto-AMENDMENT_REQUIRED cascade emits
        a SYSTEM_AUTO event targeted at the CTR.

        Design: Difficulty/transitive_cascade/txn_create_to_ctr_amendment_required_cascade
        """
        set_clock("2026-08-01T12:00:00Z")
        from test_helpers import create_branch, create_customer
        br1 = create_branch(name="Main", branch_code="BR1")
        c1 = create_customer(legal_name="Cascade Two", tin="88-8888889")
        post_cash_txn(c1["id"], br1["id"], amount_cents=1_100_000,
                      occurred_at="2026-08-01T10:00:00Z")
        ctr = get_single_ctr_for_customer(c1["id"])
        get_success_data(api_client.validate_ctr(ctr["id"], headers=make_analyst_headers("analyst-x")))
        get_success_data(api_client.file_ctr(
            ctr["id"], {"filing_channel": "EFILE"}, headers=make_officer_headers("officer-y"),
        ))
        set_clock("2026-08-01T15:00:00Z")
        post_cash_txn(c1["id"], br1["id"], amount_cents=50_000,
                      occurred_at="2026-08-01T14:00:00Z")
        # Pull all events on this CTR and inspect the auto one
        resp = api_client.list_audit_events(
            headers=make_officer_headers(),
            params={"entity_type": "CTR", "entity_id": ctr["id"]},
        )
        events = resp.json()["data"]
        actions = [e["action"] for e in events]
        assert "SYSTEM_AUTO" in actions, f"expected SYSTEM_AUTO event, got {actions}"
        auto = [e for e in events if e["action"] == "SYSTEM_AUTO"][0]
        assert auto["actor_role"] == "SYSTEM"


class TestExemptionRevokeToCtrAutoCreateCascade:
    def test_exemption_revoke_to_ctr_autocreate_cascade(self, api):
        """PRD §3.6: "A `BSAOfficer` may also revoke an `ACTIVE` designation at
        any time with a recorded `reason`, moving it `ACTIVE → REVOKED` with
        `revocation_reason` set to `MANUAL_REVOKE`, clearing the customer's
        `active_exemption_id` to null, and triggering the same trailing-45-date
        recompute that auto-creates `DRAFT` CTRs for newly-required days."

        Design: Difficulty/transitive_cascade/exemption_revoke_to_ctr_autocreate_cascade
        """
        set_clock("2026-08-01T09:00:00Z")
        from test_helpers import create_branch, create_customer
        br1 = create_branch(name="Main", branch_code="BR1")
        c1 = create_customer(
            legal_name="City Water District", tin="99-1111111",
            customer_type="GOVERNMENT_AGENCY", account_opened_date="2020-01-01T00:00:00Z",
        )
        ex = create_active_phase_i_exemption(c1["id"])
        # Three covered deposits (within the trailing-45-day window of the revoke)
        post_cash_txn(c1["id"], br1["id"], amount_cents=1_100_000,
                      occurred_at="2026-07-28T10:00:00Z")
        post_cash_txn(c1["id"], br1["id"], amount_cents=1_100_000,
                      occurred_at="2026-07-29T10:00:00Z")
        post_cash_txn(c1["id"], br1["id"], amount_cents=1_100_000,
                      occurred_at="2026-07-30T10:00:00Z")
        # Covered -> no CTRs
        _, pre_meta = list_ctrs_for_customer(c1["id"])
        assert pre_meta["total_count"] == 0
        # Revoke flips coverage off and auto-creates one DRAFT CTR per newly-required day
        revoked = get_success_data(api_client.revoke_exemption(
            ex["id"], {"reason": "customer request withdrawal"},
            headers=make_officer_headers("officer-b"),
        ))
        assert revoked["status"] == "REVOKED"
        assert revoked["revocation_reason"] == "MANUAL_REVOKE"
        agg = get_aggregation_for(c1["id"], "2026-07-28")
        assert agg["covered_in"] is False
        assert agg["ctr_required"] is True
        data, post_meta = list_ctrs_for_customer(c1["id"], status="DRAFT")
        assert post_meta["total_count"] == 3
        assert data[0]["snapshot_cash_in_cents"] == 1_100_000

    def test_exemption_revoke_clears_active_exemption_id(self, api):
        """PRD §3.6: "A `BSAOfficer` may also revoke an `ACTIVE` designation at
        any time with a recorded `reason`, moving it `ACTIVE → REVOKED` with
        `revocation_reason` set to `MANUAL_REVOKE`, clearing the customer's
        `active_exemption_id` to null".

        Independent confirmation that the customer's `active_exemption_id` is
        cleared by revoke.

        Design: Difficulty/transitive_cascade/exemption_revoke_to_ctr_autocreate_cascade
        """
        set_clock("2026-08-01T09:00:00Z")
        from test_helpers import create_customer
        c1 = create_customer(
            legal_name="City Power", customer_type="GOVERNMENT_AGENCY",
            account_opened_date="2020-01-01T00:00:00Z",
        )
        ex = create_active_phase_i_exemption(c1["id"])
        cust_during = get_success_data(api_client.get_customer(c1["id"], headers=make_officer_headers()))
        assert cust_during["active_exemption_id"] == ex["id"]
        get_success_data(api_client.revoke_exemption(
            ex["id"], {"reason": "program exit"}, headers=make_officer_headers("officer-b"),
        ))
        cust_after = get_success_data(api_client.get_customer(c1["id"], headers=make_officer_headers()))
        assert cust_after["active_exemption_id"] is None


class TestAuditChainGenesis:
    def test_audit_chain_genesis_and_verify(self, api):
        """PRD §2.7: "Each event carries a monotonically increasing `sequence_no`
        that starts at 1 for the genesis event and grows by exactly one per event
        with no gaps".
        PRD §2.7: "each event's `prev_hash` is the `event_hash` of the preceding
        event, with the genesis event using sixty-four `0` characters."
        PRD §2.7: "Every successful mutating call appends exactly one AuditEvent".

        Design: Corner/calculations/audit_chain_genesis_and_verify
        """
        set_clock("2026-08-01T09:00:00Z")
        from test_helpers import create_branch, create_customer
        br1 = create_branch(name="Main", branch_code="BR1")
        c1 = create_customer(legal_name="Audit Amy", tin="22-2222220")
        # one below-threshold deposit: no CTR auto-create, no structuring alert
        post_cash_txn(c1["id"], br1["id"], amount_cents=500_000,
                      occurred_at="2026-08-01T08:00:00Z")
        resp = api_client.list_audit_events(headers=make_officer_headers(), params={})
        body = resp.json()
        assert body["meta"]["total_count"] == 4
        first = body["data"][0]
        assert first["sequence_no"] == 1
        assert first["prev_hash"] == "0" * 64
        chain = get_success_data(api_client.verify_audit_chain(headers=make_officer_headers()))
        assert chain["chain_valid"] is True
        assert chain["events_checked"] == 4
