"""Endpoint-level behaviour: the computed traceability read, the chain-link filter, the
sell-down action, an idle sweep and the eight not-found identities."""

from test_helpers import (
    OFFICER,
    api_errors as E,
    assert_instant,
    factories as f,
    make_brand_licensee_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

PROBES = {
    "00000000-0000-4000-8000-000000000011": E.ERR_COMMITTEE_NOT_FOUND,
    "00000000-0000-4000-8000-000000000012": E.ERR_PROPOSAL_NOT_FOUND,
    "00000000-0000-4000-8000-000000000013": E.ERR_LEDGER_ENTRY_NOT_FOUND,
    "00000000-0000-4000-8000-000000000014": E.ERR_TRANSACTION_NOT_FOUND,
    "00000000-0000-4000-8000-000000000015": E.ERR_VOLUME_REPORT_NOT_FOUND,
    "00000000-0000-4000-8000-000000000016": E.ERR_AUDIT_NOT_FOUND,
    "00000000-0000-4000-8000-000000000017": E.ERR_NONCONFORMITY_NOT_FOUND,
    "00000000-0000-4000-8000-000000000018": E.ERR_MARK_REQUEST_NOT_FOUND,
}


class TestTraceabilitySummary:
    """The summary is a walk of the holder's upstream chain, computed on read."""

    def test_the_brand_sees_its_two_node_chain_while_the_producer_sees_no_chain(
        self, api, clock
    ):
        """A brand node fed by a physical cooperative reports a mixed-mode chain carrying the
        cooperative's whole credit, while the cooperative itself is chain-origin.

        Design: Corner/endpoints/traceability_summary_computed_read_matches_the_chain_walk
        """
        chain = f.build_certified_chain(api, buyer_mode="MASS_BALANCE", harvest_kg=50000)
        seller_before = f.read_node(api, chain["seller_node_id"])
        buyer_before = f.read_node(api, chain["buyer_node_id"])

        brand_summary = validate_success(
            api.get_traceability_summary(chain["brand_id"], OFFICER), 200
        )

        assert brand_summary["holder_id"] == chain["brand_id"]
        assert brand_summary["chain_mode"] == "CONTAINS_MASS_BALANCE"
        assert brand_summary["chain_node_count"] == 2
        assert brand_summary["brand_node_count"] == 1
        assert brand_summary["physical_node_count"] == 1
        assert brand_summary["mass_balance_node_count"] == 1
        producer_summary = validate_success(
            api.get_traceability_summary(chain["producer_id"], OFFICER), 200
        )

        assert producer_summary["chain_mode"] == "NO_CHAIN"
        assert producer_summary["chain_node_count"] == 0
        assert producer_summary["brand_node_count"] == 0
        assert producer_summary["physical_node_count"] == 0
        assert producer_summary["mass_balance_node_count"] == 0
        assert f.read_node(api, chain["seller_node_id"])["version"] == seller_before["version"]
        assert f.read_node(api, chain["buyer_node_id"])["version"] == buyer_before["version"]


class TestChainLinks:
    """A node names one immediate upstream, and the link filter follows exactly one hop."""

    def test_two_further_hops_deepen_the_chain_and_only_the_direct_child_is_filtered(
        self, api, clock
    ):
        """Depth counts up by one per hop, the declared processing yield is stored where it was
        given, and filtering on the cooperative returns only the processor it feeds.

        Design: Corner/endpoints/node_create_links_the_upstream_node_and_is_listable_by_that_link
        """
        producer = f.build_certified_producer(api)
        brand = f.register_holder(
            api, legal_name="Nordic Roasters", holder_type="BRAND", country_code="SE"
        )
        brand_headers = make_brand_licensee_headers(brand["id"])
        f.register_node(api, brand_headers, holder_id=brand["id"], node_role="BRAND_NODE")
        f.certify(api, brand["id"])
        origin = f.read_node(api, producer["node_id"])

        processor = validate_success(
            api.create_node(
                f.node_payload(
                    brand["id"], node_role="PROCESSOR",
                    upstream_node_id=origin["id"], conversion_ratio=0.8,
                ),
                brand_headers,
            ),
            201,
        )
        brand_node = validate_success(
            api.create_node(
                f.node_payload(
                    brand["id"], node_role="BRAND_NODE", upstream_node_id=processor["id"]
                ),
                brand_headers,
            ),
            201,
        )

        assert processor["upstream_node_id"] == origin["id"]
        assert brand_node["upstream_node_id"] == processor["id"]
        assert origin["chain_depth"] == 0
        assert processor["chain_depth"] == 1
        assert brand_node["chain_depth"] == 2
        assert float(processor["conversion_ratio"]) == 0.8
        assert float(brand_node["conversion_ratio"]) == 1.0
        assert processor["status"] == "ACTIVE" and brand_node["status"] == "ACTIVE"

        rows, meta = validate_paginated(
            api.list_nodes(OFFICER, {"upstream_node_id": origin["id"]})
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [processor["id"]], (
            "the filter follows one hop, not the whole chain"
        )


class TestSellDownWindow:
    """The sell-down window is only offered to a suspended holder."""

    def test_a_certified_holder_cannot_be_transitioned_but_a_suspended_one_can(self, api, clock):
        """The action is refused while certification still stands; once suspended, it opens a
        ninety-day window and puts the holder's node back to work.

        Design: Corner/endpoints/transition_action_opens_the_sell_down_window_and_reactivates_the_nodes
        """
        producer = f.build_certified_producer(api)

        too_early = api.transition_holder(producer["holder_id"], OFFICER)

        validate_error(too_early, E.ERR_INVALID_STATE_TRANSITION, 409)
        still_certified = f.read_holder(api, producer["holder_id"])
        assert still_certified["certificate_status"] == "CERTIFIED"
        assert still_certified["transition_deadline_at"] is None

        suspended = validate_success(
            api.suspend_holder(producer["holder_id"], f.reason_payload("MANUAL"), OFFICER), 200
        )
        assert suspended["certificate_status"] == "SUSPENDED"
        assert suspended["suspension_reason"] == "MANUAL"
        assert f.read_node(api, producer["node_id"])["status"] == "SUSPENDED"

        transitioned = validate_success(
            api.transition_holder(producer["holder_id"], OFFICER), 200
        )

        assert transitioned["certificate_status"] == "TRANSITIONING"
        assert_instant(
            transitioned["transition_deadline_at"], "2026-10-30T00:00:00Z",
            "transition_deadline_at",
        )
        assert f.read_node(api, producer["node_id"])["status"] == "ACTIVE", (
            "remaining certified stock has to be sellable during the window"
        )


class TestAnIdleComplianceSweep:
    """A sweep with nothing due reports six zeroes and writes nothing."""

    def test_a_sweep_before_any_deadline_changes_no_row(self, api, clock):
        """With the only finding due in September, an August sweep is a no-op that still stamps
        the instant it ran at.

        Design: Corner/endpoints/compliance_sweep_returns_all_zero_counts_when_nothing_is_due
        """
        producer = f.build_certified_producer(api)
        audit = f.build_started_audit(api, producer["holder_id"])
        finding = f.raise_finding(api, audit["id"], "MAJOR")
        holder_before = f.read_holder(api, producer["holder_id"])
        f.set_clock(api, "2026-08-05T00:00:00Z")

        result = validate_success(api.run_compliance_sweep(OFFICER), 200)

        assert_instant(result["swept_at"], "2026-08-05T00:00:00Z", "swept_at")
        assert result["overdue_count"] == 0
        assert result["escalated_count"] == 0
        assert result["suspended_holder_count"] == 0
        assert result["suspended_node_count"] == 0
        assert result["disputed_transaction_count"] == 0
        assert result["decertified_holder_count"] == 0
        after_finding = f.read_nonconformity(api, finding["id"])
        assert after_finding["status"] == "OPEN"
        assert_instant(after_finding["deadline_at"], "2026-09-15T00:00:00Z", "deadline_at")
        assert after_finding["version"] == finding["version"]
        after_holder = f.read_holder(api, producer["holder_id"])
        assert after_holder["certificate_status"] == "CERTIFIED"
        assert after_holder["version"] == holder_before["version"]


class TestNotFoundIdentities:
    """Each read names the type of the identifier it could not resolve."""

    def test_each_unknown_path_identifier_returns_its_own_not_found_code(self, api, clock):
        """Eight reads against an empty service produce eight distinct 404 identities.

        Design: Corner/errors/unknown_path_ids_each_return_their_own_entity_not_found
        """
        reads = {
            "00000000-0000-4000-8000-000000000011": api.get_committee,
            "00000000-0000-4000-8000-000000000012": api.get_proposal,
            "00000000-0000-4000-8000-000000000013": api.get_ledger_entry,
            "00000000-0000-4000-8000-000000000014": api.get_trade,
            "00000000-0000-4000-8000-000000000015": api.get_volume_report,
            "00000000-0000-4000-8000-000000000016": api.get_audit,
            "00000000-0000-4000-8000-000000000017": api.get_nonconformity,
            "00000000-0000-4000-8000-000000000018": api.get_mark_usage_request,
        }

        for probe_id, read in reads.items():
            error = validate_error(read(probe_id, OFFICER), PROBES[probe_id], 404)
            assert error["message"].strip(), f"{PROBES[probe_id]} carries a message"

        holders, meta = validate_paginated(api.list_holders(OFFICER))
        assert meta["total_count"] == 0 and holders == [], "no probe created a row"
