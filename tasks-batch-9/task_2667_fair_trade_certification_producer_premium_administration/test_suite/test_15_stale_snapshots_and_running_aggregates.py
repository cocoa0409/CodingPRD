"""Two sequential writes against one shared parent, and the counters that must add up
after every single one of them."""

from test_helpers import (
    CHAIR,
    OFFICER,
    api_errors as E,
    assert_created_at_ascending,
    assert_fund_partition,
    assert_instant,
    assert_ledger_entry,
    assert_money,
    assert_node_position,
    assert_score,
    factories as f,
    validate_error,
    validate_paginated,
    validate_success,
)


def _trade(api, chain, volume_kg, expected_seller_node_version):
    """Record one trade out of the chain's seller node at a pinned node version."""
    return api.create_trade(
        f.trade_payload(
            chain["seller_node_id"], chain["buyer_node_id"], expected_seller_node_version,
            volume_kg, declared_unit_price_cents_per_kg=500,
        ),
        chain["producer_headers"],
    )


class TestStaleSellerNodeSnapshot:
    """The second trade of a pair must carry the version the first one produced."""

    def test_a_second_trade_carrying_the_pre_trade_node_version_is_refused(self, api, clock):
        """Recording 4000 kg bumps the seller node, so a 3000 kg follow-up still quoting the
        old version reserves nothing; requoted against the fresh version it goes through.

        Design: Corner/cross_cutting_complexity_layers/stale_seller_node_version_on_the_second_transaction_returns_412
        """
        chain = f.build_certified_chain(api, harvest_kg=50000)
        version_1 = chain["seller_node_version"]

        first = validate_success(_trade(api, chain, 4000, version_1), 201)
        after_first = f.read_node(api, chain["seller_node_id"])
        assert after_first["version"] == version_1 + 1
        assert_node_position(after_first, reserved_output_kg="4000.000")

        stale = _trade(api, chain, 3000, version_1)

        validate_error(stale, E.ERR_STALE_NODE_VERSION, 412)
        unchanged = f.read_node(api, chain["seller_node_id"])
        assert_node_position(unchanged, reserved_output_kg="4000.000")
        assert unchanged["version"] == version_1 + 1, "the refusal wrote nothing at all"

        version_2 = unchanged["version"]
        second = validate_success(_trade(api, chain, 3000, version_2), 201)
        final = f.read_node(api, chain["seller_node_id"])
        assert_node_position(
            final, reserved_output_kg="7000.000", available_credit_kg="43000.000"
        )
        assert final["version"] == version_2 + 1
        rows, meta = validate_paginated(
            api.list_trades(OFFICER, {"seller_node_id": chain["seller_node_id"]})
        )
        assert meta["total_count"] == 2
        assert [row["id"] for row in rows] == [first["id"], second["id"]]


def _proposal(api, committee_id, expected_fund_version, title, start, end):
    return api.create_proposal(
        f.proposal_payload(
            committee_id, expected_fund_version, 300000, title=title,
            use_category="EDUCATION", use_period_start=start, use_period_end=end,
        ),
        CHAIR,
    )


class TestStaleFundSnapshot:
    """Drafting a proposal bumps the fund, so the next draft needs the new version."""

    def test_a_second_proposal_carrying_the_pre_draft_fund_version_is_refused(self, api, clock):
        """The school roof draft moves the fund on, the teacher stipend quoting the old
        version is turned away without touching a cent, and the retry succeeds.

        Design: Corner/cross_cutting_complexity_layers/stale_fund_version_on_the_second_proposal_returns_412
        """
        chain = f.build_funded_committee(api)
        version_1 = f.read_fund(api, chain["producer_id"])["version"]

        first = validate_success(
            _proposal(
                api, chain["committee_id"], version_1, "School roof",
                "2026-09-01", "2026-10-01",
            ),
            201,
        )
        after_first = f.read_fund(api, chain["producer_id"])
        assert after_first["version"] == version_1 + 1
        assert after_first["pending_proposal_count"] == 1

        stale = _proposal(
            api, chain["committee_id"], version_1, "Teacher stipend",
            "2026-10-01", "2026-11-01",
        )

        validate_error(stale, E.ERR_STALE_FUND_VERSION, 412)
        unchanged = f.read_fund(api, chain["producer_id"])
        assert unchanged["version"] == version_1 + 1
        assert unchanged["pending_proposal_count"] == 1
        assert_fund_partition(
            unchanged, total_accrued_cents=2400000, balance_cents=2400000,
            committed_cents=0, disbursed_cents=0,
        )

        version_2 = unchanged["version"]
        second = validate_success(
            _proposal(
                api, chain["committee_id"], version_2, "Teacher stipend",
                "2026-10-01", "2026-11-01",
            ),
            201,
        )
        final = f.read_fund(api, chain["producer_id"])
        assert final["pending_proposal_count"] == 2
        assert final["version"] == version_2 + 1
        assert f.read_proposal(api, first["id"])["status"] == "DRAFT"
        assert f.read_proposal(api, second["id"])["status"] == "DRAFT"


def _committee_one_lot_short_of_the_threshold(api):
    """A FORMING committee over a fund holding 999920 cents, 80 short of the threshold."""
    chain = f.build_certified_chain(api, harvest_kg=50000)
    committee = f.constitute_committee(api, chain["producer_id"])
    chain["committee_id"] = committee["id"]
    chain["committee_version"] = committee["version"]
    first = f.record_settled_trade(api, chain, 12499)
    chain["first_trade"] = first
    chain["fund_id"] = f.read_fund(api, chain["producer_id"])["id"]
    return chain


class TestCommitteeActivationThreshold:
    """A committee starts governing at exactly one million cents, not a cent earlier."""

    def test_a_fund_eighty_cents_short_leaves_the_committee_forming(self, api, clock):
        """12499 kg of coffee accrues 999920 cents, which is real money but not yet the
        threshold, so the committee has nothing to govern and does not move.

        Design: Corner/cross_cutting_complexity_layers/committee_activates_only_once_the_balance_reaches_exactly_the_threshold
        """
        chain = _committee_one_lot_short_of_the_threshold(api)

        assert_money(chain["first_trade"]["premium_cents"], 999920, "premium_cents")
        assert chain["first_trade"]["premium_basis"] == "PHYSICAL_TRACEABILITY"
        assert_fund_partition(
            f.read_fund(api, chain["producer_id"]),
            total_accrued_cents=999920, balance_cents=999920,
        )
        committee = f.read_committee(api, chain["committee_id"])
        assert committee["status"] == "FORMING"
        assert committee["version"] == chain["committee_version"]

    def test_one_more_kilogram_carries_the_fund_to_the_line_and_activates(self, api, clock):
        """A single further kilogram accrues the last 80 cents; the balance lands exactly on
        the threshold and the committee becomes ACTIVE, with both accruals on the ledger.

        Design: Corner/cross_cutting_complexity_layers/committee_activates_only_once_the_balance_reaches_exactly_the_threshold
        """
        chain = _committee_one_lot_short_of_the_threshold(api)

        second = f.record_settled_trade(api, chain, 1)

        assert_money(second["premium_cents"], 80, "premium_cents")
        assert_fund_partition(
            f.read_fund(api, chain["producer_id"]),
            total_accrued_cents=1000000, balance_cents=1000000,
        )
        committee = f.read_committee(api, chain["committee_id"])
        assert committee["status"] == "ACTIVE"
        assert committee["version"] == chain["committee_version"] + 1
        entries = f.read_ledger_entries(api, fund_id=chain["fund_id"])
        assert len(entries) == 2
        assert_created_at_ascending(entries)
        assert_ledger_entry(entries[0], "ACCRUAL", 999920, balance_after_cents=999920)
        assert_ledger_entry(entries[1], "ACCRUAL", 80, balance_after_cents=1000000)


def _audit_with_two_findings(api):
    """A MAJOR and then a MINOR finding raised against a previously spotless producer."""
    producer = f.build_certified_producer(api)
    audit = f.build_started_audit(api, producer["holder_id"])
    producer["audit_id"] = audit["id"]
    producer["major"] = f.raise_finding(api, audit["id"], "MAJOR")
    producer["holder_after_major"] = f.read_holder(api, producer["holder_id"])
    producer["minor"] = f.raise_finding(
        api, audit["id"], "MINOR", "3.1.4", "Signage missing at store"
    )
    return producer


class TestHolderAggregatesAfterEveryFinding:
    """The score and the three counters are re-derived on every single finding movement."""

    def test_each_finding_lowers_the_score_and_prices_itself_off_the_earlier_one(
        self, api, clock
    ):
        """The major costs 15 points and is priced against a perfect record; the minor that
        follows costs 5 more and is priced against the 85 the major left behind.

        Design: Corner/cross_cutting_complexity_layers/holder_compliance_aggregates_reconcile_after_each_finding_and_closure
        """
        producer = _audit_with_two_findings(api)

        after_major = producer["holder_after_major"]
        assert_score(after_major["compliance_score"], 85)
        assert (after_major["open_critical_count"], after_major["open_major_count"],
                after_major["open_minor_count"]) == (0, 1, 0)
        major = f.read_nonconformity(api, producer["major"]["id"])
        assert_score(major["compliance_score_at_raise"], 100, "compliance_score_at_raise")
        assert major["escalation_grace_days"] == 14
        assert_instant(major["deadline_at"], "2026-09-15T00:00:00Z", "deadline_at")

        after_minor = f.read_holder(api, producer["holder_id"])
        assert_score(after_minor["compliance_score"], 80)
        assert (after_minor["open_major_count"], after_minor["open_minor_count"]) == (1, 1)
        minor = f.read_nonconformity(api, producer["minor"]["id"])
        assert_score(minor["compliance_score_at_raise"], 85, "compliance_score_at_raise")
        assert minor["escalation_grace_days"] == 7
        assert_instant(minor["deadline_at"], "2026-10-30T00:00:00Z", "deadline_at")

    def test_closing_one_finding_gives_back_exactly_the_points_it_cost(self, api, clock):
        """An accepted corrective action closes the major, the score climbs back to 95 with
        the minor still open, and the audit's counters follow it.

        Design: Corner/cross_cutting_complexity_layers/holder_compliance_aggregates_reconcile_after_each_finding_and_closure
        """
        producer = _audit_with_two_findings(api)
        validate_success(
            api.submit_cap(
                producer["major"]["id"],
                f.cap_payload("Payroll rebuilt and archived"),
                producer["holder_headers"],
            ),
            201,
        )

        closed = validate_success(
            api.review_cap(
                producer["major"]["id"],
                f.cap_review_payload("ACCEPT", "Evidence sufficient"),
                OFFICER,
            ),
            200,
        )

        assert closed["status"] == "CLOSED"
        holder = f.read_holder(api, producer["holder_id"])
        assert_score(holder["compliance_score"], 95)
        assert (holder["open_major_count"], holder["open_minor_count"]) == (0, 1)
        assert holder["next_audit_due_at"] is None, (
            "no audit of this holder has closed, so the cadence has no anchor yet"
        )
        audit = f.read_audit(api, producer["audit_id"])
        assert audit["nonconformity_count"] == 2
        assert audit["open_nonconformity_count"] == 1
