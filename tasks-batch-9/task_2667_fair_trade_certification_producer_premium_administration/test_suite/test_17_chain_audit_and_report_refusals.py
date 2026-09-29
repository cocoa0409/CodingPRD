"""The refusals that guard chain shape, audit windows, corrective action deadlines,
reporting periods and the licence behind an on-pack claim.
"""

from test_helpers import (
    OFFICER,
    api_errors as E,
    assert_created_at_ascending,
    assert_instant,
    assert_money,
    assert_node_position,
    assert_pct,
    assert_score,
    assert_volume,
    factories as f,
    make_brand_licensee_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_HOLDER_ID = "00000000-0000-4000-8000-000000000003"


def _seven_node_physical_chain(api):
    """One cooperative feeding five processors and a brand node, at depths 0 through 6."""
    producer = f.build_certified_producer(api)
    node_ids = [producer["node_id"]]
    for _ in range(5):
        node = f.register_node(
            api, OFFICER, holder_id=producer["holder_id"], node_role="PROCESSOR",
            traceability_mode="PHYSICAL", upstream_node_id=node_ids[-1],
        )
        node_ids.append(node["id"])
    brand_node = f.register_node(
        api, OFFICER, holder_id=producer["holder_id"], node_role="BRAND_NODE",
        traceability_mode="PHYSICAL", upstream_node_id=node_ids[-1],
    )
    node_ids.append(brand_node["id"])
    producer["node_ids"] = node_ids
    return producer


class TestNodeRegistrationChecksItsInputsBeforeItsReferences:
    """A malformed body is answered before the service goes looking for the holder."""

    def test_an_unknown_role_is_reported_before_the_holder_is_even_looked_up(self, api, clock):
        """A warehouse is not a point of custody this standard recognizes, and the same
        request with a real role finally reports the holder that does not exist; a yield
        above one is refused as well, since no process creates certified volume.

        Design: Corner/validations/node_create_with_invalid_enum_outranks_unknown_foreign_key
        """
        producer = f.build_certified_producer(api)

        bad_role = api.create_node(
            f.node_payload(UNKNOWN_HOLDER_ID, node_role="WAREHOUSE"), OFFICER
        )
        validate_error(bad_role, E.ERR_INVALID_REQUEST, 422)

        unknown_holder = api.create_node(f.node_payload(UNKNOWN_HOLDER_ID), OFFICER)
        validate_error(unknown_holder, E.ERR_HOLDER_NOT_FOUND, 404)

        impossible_yield = api.create_node(
            f.node_payload(producer["holder_id"], conversion_ratio=1.5), OFFICER
        )
        validate_error(impossible_yield, E.ERR_INVALID_REQUEST, 422)

        rows, meta = validate_paginated(
            api.list_nodes(OFFICER, {"holder_id": producer["holder_id"]})
        )
        assert meta["total_count"] == 1, "no refusal registered a node"
        assert [row["id"] for row in rows] == [producer["node_id"]]


class TestTheChainDepthCeiling:
    """Six hops from the origin is as far as a certified chain may run."""

    def test_an_eighth_node_on_a_seven_node_chain_is_refused(self, api, clock):
        """The chain already runs from the cooperative to the brand node in six hops, so one
        more processor beyond it cannot be mapped, and the chain stays as it was.

        Design: Corner/validations/eighth_chain_node_exceeds_max_depth_and_is_rejected
        """
        producer = _seven_node_physical_chain(api)
        node_ids = producer["node_ids"]

        response = api.create_node(
            f.node_payload(
                producer["holder_id"], node_role="PROCESSOR",
                upstream_node_id=node_ids[6],
            ),
            OFFICER,
        )

        validate_error(response, E.ERR_SUPPLY_CHAIN_DEPTH_EXCEEDED, 422)
        assert f.read_node(api, node_ids[0])["chain_depth"] == 0
        assert f.read_node(api, node_ids[6])["chain_depth"] == 6
        rows, meta = validate_paginated(
            api.list_nodes(OFFICER, {"holder_id": producer["holder_id"], "limit": 100})
        )
        assert meta["total_count"] == 7 and len(rows) == 7
        summary = validate_success(
            api.get_traceability_summary(producer["holder_id"], OFFICER), 200
        )
        assert summary["chain_node_count"] == 7
        assert summary["brand_node_count"] == 1
        assert summary["physical_node_count"] == 7
        assert summary["mass_balance_node_count"] == 0
        assert summary["chain_mode"] == "ALL_PHYSICAL"


class TestATradeNeedsAMappedLinkBetweenTheTwoNodes:
    """The buyer must sit immediately downstream of the seller in the mapped chain."""

    def test_a_shipment_into_an_unlinked_brand_node_is_refused(self, api, clock):
        """The roaster's second brand node was never joined to the cooperative, so the
        shipment has no certified link to travel along; sent to the linked node instead the
        same volume is priced and reserved exactly once.

        Design: Corner/validations/trade_create_with_an_unlinked_buyer_node_is_rejected
        """
        chain = f.build_certified_chain(api, harvest_kg=50000)
        node_version = chain["seller_node_version"]
        orphan = f.register_node(
            api, chain["brand_headers"], holder_id=chain["brand_id"],
            node_role="BRAND_NODE", traceability_mode="PHYSICAL",
        )

        response = api.create_trade(
            f.trade_payload(chain["seller_node_id"], orphan["id"], node_version, 10000),
            chain["producer_headers"],
        )

        validate_error(response, E.ERR_SUPPLY_CHAIN_LINK_MISSING, 422)
        assert orphan["chain_depth"] == 0
        assert orphan["upstream_node_id"] is None
        assert f.read_node(api, chain["buyer_node_id"])["chain_depth"] == 1

        trade = validate_success(
            api.create_trade(
                f.trade_payload(
                    chain["seller_node_id"], chain["buyer_node_id"], node_version, 10000
                ),
                chain["producer_headers"],
            ),
            201,
        )
        assert_money(trade["premium_cents"], 800000, "premium_cents")
        seller = f.read_node(api, chain["seller_node_id"])
        assert_node_position(
            seller, reserved_output_kg="10000.000", available_credit_kg="40000.000"
        )
        assert seller["version"] == node_version + 1, (
            "the refused create left the seller node untouched"
        )


class TestTheOnSiteWindowMustMakeSense:
    """An audit visit needs at least a day of duration and cannot be booked in the past."""

    def test_a_zero_length_window_and_a_backdated_start_are_both_refused(self, api, clock):
        """Neither a visit that ends the day it starts nor one starting the day before today
        can be scheduled, and only the sane window leaves an audit behind.

        Design: Corner/validations/audit_window_with_no_duration_or_a_past_start_is_rejected
        """
        producer = f.build_certified_producer(api)

        zero_length = api.create_audit(
            f.audit_payload(
                producer["holder_id"], "2026-08-05", "2026-08-05", audit_type="SURVEILLANCE"
            ),
            OFFICER,
        )
        validate_error(zero_length, E.ERR_INVALID_AUDIT_WINDOW, 422)

        backdated = api.create_audit(
            f.audit_payload(
                producer["holder_id"], "2026-07-31", "2026-08-05", audit_type="SURVEILLANCE"
            ),
            OFFICER,
        )
        validate_error(backdated, E.ERR_INVALID_AUDIT_WINDOW, 422)

        scheduled = validate_success(
            api.create_audit(
                f.audit_payload(
                    producer["holder_id"], "2026-08-05", "2026-08-06",
                    audit_type="SURVEILLANCE",
                ),
                OFFICER,
            ),
            201,
        )
        assert scheduled["status"] == "SCHEDULED"
        rows, meta = validate_paginated(
            api.list_holder_audits(producer["holder_id"], OFFICER)
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [scheduled["id"]]


class TestAnAuditClosesOnlyOnceItsFindingsDo:
    """The report cannot be signed off while a nonconformity is still open."""

    def test_the_close_waits_for_the_corrective_action_and_then_succeeds(self, api, clock):
        """The first close is refused with the finding still outstanding; once the plan is
        accepted the same call goes through and finally anchors the audit cadence.

        Design: Corner/validations/audit_close_with_an_open_finding_is_rejected_then_succeeds_once_it_is_closed
        """
        producer = f.build_certified_producer(api)
        audit = f.build_started_audit(api, producer["holder_id"])
        finding = f.raise_finding(api, audit["id"], "MAJOR")

        too_early = api.close_audit(audit["id"], OFFICER)

        validate_error(too_early, E.ERR_AUDIT_HAS_OPEN_NONCONFORMITIES, 409)
        blocked = f.read_audit(api, audit["id"])
        assert blocked["status"] == "REPORT_PENDING"
        assert blocked["open_nonconformity_count"] == 1
        assert blocked["closed_at"] is None

        validate_success(
            api.submit_cap(
                finding["id"], f.cap_payload("Records reconstructed"),
                producer["holder_headers"],
            ),
            201,
        )
        accepted = validate_success(
            api.review_cap(
                finding["id"], f.cap_review_payload("ACCEPT", "Evidence sufficient"), OFFICER
            ),
            200,
        )
        assert accepted["status"] == "CLOSED"
        cleared = f.read_audit(api, audit["id"])
        assert cleared["open_nonconformity_count"] == 0
        assert cleared["nonconformity_count"] == 1, "the finding stays on the record"

        closed = validate_success(api.close_audit(audit["id"], OFFICER), 200)

        assert closed["status"] == "CLOSED"
        assert_instant(closed["closed_at"], clock, "closed_at")
        holder = f.read_holder(api, producer["holder_id"])
        assert_score(holder["compliance_score"], 100)
        assert holder["open_major_count"] == 0
        assert_instant(
            holder["next_audit_due_at"], "2028-08-08T00:00:00Z", "next_audit_due_at"
        )


class TestTheCorrectiveActionDeadline:
    """A plan is welcome up to the deadline instant itself and refused after it."""

    def test_a_plan_filed_the_day_after_the_deadline_is_refused(
        self, api, clock, advance_clock
    ):
        """The reprint submitted at exactly the deadline was accepted and then turned down on
        review; the photographs offered a day later arrive too late to be considered, and the
        finding keeps the narrative it already had.

        Design: Corner/validations/cap_submission_after_the_deadline_is_rejected
        """
        producer = f.build_certified_producer(api)
        audit = f.build_started_audit(api, producer["holder_id"])
        finding = f.raise_finding(api, audit["id"], "MINOR", "3.1.4", "Origin labels missing")
        assert_instant(finding["deadline_at"], "2026-12-14T00:00:00Z", "deadline_at")
        assert finding["escalation_grace_days"] == 14

        advance_clock("2026-12-14T00:00:00Z")
        submitted = validate_success(
            api.submit_cap(
                finding["id"], f.cap_payload("Labels reprinted"), producer["holder_headers"]
            ),
            201,
        )
        assert submitted["cap_round"] == 1, "a submission at the deadline instant is in time"
        assert_instant(submitted["cap_submitted_at"], "2026-12-14T00:00:00Z", "cap_submitted_at")
        rejected = validate_success(
            api.review_cap(
                finding["id"], f.cap_review_payload("REJECT", "Photographs missing"), OFFICER
            ),
            200,
        )
        assert rejected["status"] == "CAP_REJECTED"

        advance_clock("2026-12-15T00:00:00Z")
        response = api.submit_cap(
            finding["id"], f.cap_payload("Photographs attached"), producer["holder_headers"]
        )

        validate_error(response, E.ERR_CAP_DEADLINE_PASSED, 409)
        after = f.read_nonconformity(api, finding["id"])
        assert after["status"] == "CAP_REJECTED", (
            "only a compliance sweep moves a missed finding to OVERDUE"
        )
        assert after["cap_round"] == 1
        assert after["cap_narrative"] == "Labels reprinted"


class TestReportingPeriodsMayTouchButNotOverlap:
    """One filer-and-counterparty pair may not declare the same month twice."""

    def test_an_overlapping_period_is_refused_while_a_touching_one_is_accepted(
        self, api, clock
    ):
        """June is already covered by the first half-year report, so a period reaching back
        into it is refused; a period beginning exactly where that one ends is fine.

        Design: Corner/validations/overlapping_volume_report_period_is_rejected_while_a_touching_period_passes
        """
        chain = f.build_certified_chain(api, harvest_kg=None)
        first = f.file_volume_report(
            api, chain["producer_id"], chain["brand_id"], "2026-01-01", "2026-07-01", 2000
        )

        overlapping = api.create_volume_report(
            f.volume_report_payload(
                chain["producer_id"], chain["brand_id"], "2026-06-01", "2026-09-01", 2000
            ),
            chain["producer_headers"],
        )
        validate_error(overlapping, E.ERR_REPORT_PERIOD_OVERLAP, 409)

        touching = validate_success(
            api.create_volume_report(
                f.volume_report_payload(
                    chain["producer_id"], chain["brand_id"], "2026-07-01", "2026-09-01", 2000
                ),
                chain["producer_headers"],
            ),
            201,
        )
        assert touching["reconciliation_status"] == "SUBMITTED"
        assert_volume(touching["counterparty_volume_kg"], "0.000", "counterparty_volume_kg")
        assert_pct(touching["variance_pct"], "0.00", "variance_pct")
        assert touching["basis"] is None
        rows, meta = validate_paginated(
            api.list_holder_volume_reports(chain["producer_id"], OFFICER)
        )
        assert meta["total_count"] == 2
        assert [row["id"] for row in rows] == [first["id"], touching["id"]]
        assert_created_at_ascending(rows)


class TestTheHardVarianceCap:
    """A discrepancy above a tenth of the counterparty's books cannot be reconciled at all."""

    def test_a_twenty_percent_overdeclaration_is_refused_and_writes_nothing(self, api, clock):
        """The cooperative claims 6000 kg against 5000 kg of settled shipments, which is too
        far apart to reconcile on either basis, so nothing is stored and nobody is suspended.

        Design: Corner/validations/reconcile_beyond_the_hard_variance_cap_is_rejected_and_writes_nothing
        """
        chain = f.build_certified_chain(api, harvest_kg=50000)
        f.record_settled_trade(api, chain, 5000, contract_date="2026-08-01")
        report = f.file_volume_report(
            api, chain["producer_id"], chain["brand_id"], "2026-08-01", "2026-09-01", 6000
        )

        response = api.reconcile_volume_report(
            report["id"], f.reconcile_payload("SELLER_BASIS"), OFFICER
        )

        validate_error(response, E.ERR_VOLUME_VARIANCE_EXCEEDED, 409)
        after = validate_success(api.get_volume_report(report["id"], OFFICER), 200)
        assert after["reconciliation_status"] == "SUBMITTED"
        assert after["basis"] is None
        assert_volume(after["counterparty_volume_kg"], "0.000", "counterparty_volume_kg")
        assert_pct(after["variance_pct"], "0.00", "variance_pct")
        assert after["reconciled_at"] is None
        assert after["version"] == report["version"], "the refusal wrote nothing"
        holder = f.read_holder(api, chain["producer_id"])
        assert holder["certificate_status"] == "CERTIFIED", (
            "only a flagged reconciliation suspends the filer, and this one never landed"
        )
        assert holder["suspension_reason"] == "NONE"
        assert f.read_node(api, chain["seller_node_id"])["status"] == "ACTIVE"


def _certified_brand_without_a_licence(api):
    """A CERTIFIED BRAND holder whose label_license_status is still NONE."""
    brand = f.register_holder(
        api, legal_name="Alpine Chocolate", holder_type="BRAND", country_code="CH",
        product_code="COCOA",
    )
    headers = make_brand_licensee_headers(brand["id"])
    f.register_node(
        api, headers, holder_id=brand["id"], node_role="BRAND_NODE",
        traceability_mode="MASS_BALANCE",
    )
    f.certify(api, brand["id"])
    return {"holder_id": brand["id"], "headers": headers}


class TestTheMarkNeedsALicenceBeforeItNeedsAnything:
    """Artwork cannot even be filed until the brand holds an active mark licence."""

    def test_a_filing_before_the_licence_is_refused_and_lands_once_it_is_issued(
        self, api, clock
    ):
        """The dark chocolate bar's artwork is turned away while the brand has no licence at
        all; the moment the year's licence is issued and priced the same filing is accepted,
        undecided, and the unpaid fee is not yet in the way.

        Design: Corner/validations/mark_usage_request_without_an_active_license_is_rejected
        """
        brand = _certified_brand_without_a_licence(api)
        assert f.read_holder(api, brand["holder_id"])["label_license_status"] == "NONE"
        filing = f.mark_request_payload(
            brand["holder_id"], claim_type="FT_INGREDIENT_MASS_BALANCE",
            sku_code="ALP-DARK-70", artwork_ref="ART-2026-001", requested_volume_kg=20000,
        )

        too_early = api.create_mark_usage_request(filing, brand["headers"])

        validate_error(too_early, E.ERR_LABEL_LICENSE_INACTIVE, 409)
        rows, meta = validate_paginated(
            api.list_holder_mark_usage_requests(brand["holder_id"], OFFICER)
        )
        assert meta["total_count"] == 0 and rows == []

        licensed = f.issue_license(api, brand["holder_id"], 100000)
        assert licensed["label_license_status"] == "ACTIVE"
        assert licensed["license_tier"] == "TIER_1"
        assert_money(licensed["license_fee_cents"], 382950, "license_fee_cents")
        assert licensed["license_fee_settled"] is False

        request = validate_success(
            api.create_mark_usage_request(filing, brand["headers"]), 201
        )
        assert request["status"] == "SUBMITTED"
        assert request["decided_at"] is None
        assert request["decided_by_user_id"] is None
