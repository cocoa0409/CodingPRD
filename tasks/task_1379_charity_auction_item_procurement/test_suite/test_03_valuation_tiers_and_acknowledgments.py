"""Valuation review: disclosure tiering boundaries, segregation of duties,
decide-twice guard, acknowledgment threshold, re-valuation chains, and
as-of-issue versus pinned-at-sale value semantics."""
from test_helpers import (
    ADMIN,
    FO,
    PO,
    VA,
    ApiErrorId,
    api_client,
    assert_acknowledgment,
    approve_valuation,
    create_donor,
    create_event,
    create_pledged_solicitation,
    get_acknowledgment_for_item,
    get_success_data,
    make_procurement_officer_headers,
    make_valuation_approver_headers,
    receive_item,
    setup_sold_scenario,
    setup_valued_item,
    submit_valuation,
    validate_error,
    validate_paginated,
    validate_success,
)


def _item_with_submitted_valuation(fmv_cents=30000, submitter="po_1"):
    """Event SOLICITING; one received item with a SUBMITTED valuation."""
    event = create_event()
    api_client.advance_gala_event(event["id"], ADMIN)
    donor = create_donor()
    sol = create_pledged_solicitation(donor["id"], event["id"])
    item = receive_item(sol["id"])
    item_now = get_success_data(api_client.get_item(item["id"], PO))
    resp = api_client.submit_valuation(
        item["id"],
        {
            "fmv_cents": fmv_cents,
            "fmv_source": "APPRAISAL",
            "expected_item_version": item_now["version"],
        },
        make_procurement_officer_headers(submitter),
    )
    valuation = get_success_data(resp)
    return event, donor, item, valuation


class TestDisclosureTierBoundaries:

    def test_disclosure_tier_boundaries(self):
        """PRD section 3.3: "its `disclosure_tier` is computed: `LOW` when
        the value is below 100000 cents, `MEDIUM` when it is at least
        100000 and at most 500000 cents, and `HIGH` when it exceeds 500000
        cents — so 99999 cents is `LOW`, exactly 100000 is `MEDIUM`,
        exactly 500000 is still `MEDIUM`, and 500001 is `HIGH`."

        Design: Corner/calculations/disclosure_tier_boundaries
        """
        event = create_event()
        api_client.advance_gala_event(event["id"], ADMIN)  # SOLICITING
        cases = [
            (99999, "LOW"),
            (100000, "MEDIUM"),
            (500000, "MEDIUM"),
            (500001, "HIGH"),
        ]
        for fmv, expected_tier in cases:
            part = setup_valued_item(event["id"], fmv)
            item = get_success_data(
                api_client.get_item(part["item"]["id"], ADMIN))
            assert item["current_fmv_cents"] == fmv
            assert item["disclosure_tier"] == expected_tier, (
                f"fmv {fmv} must tier {expected_tier}, "
                f"got {item['disclosure_tier']}")


class TestValuationDecisionGuards:

    def test_self_approve_rejected_sod(self):
        """PRD section 3.3: "the approving or rejecting user's `X-User-ID`
        must differ from the valuation's `submitted_by_user_id`, or the
        decision is rejected with `ERR_SOD_VIOLATION`."

        Design: Corner/validations/sod_violation_on_self_approve
        """
        _ev, _dn, _item, valuation = _item_with_submitted_valuation(
            submitter="po_1")
        resp = api_client.approve_valuation(
            valuation["id"], make_valuation_approver_headers("po_1"))
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)

        data, _meta = validate_paginated(
            api_client.list_item_valuations(_item["id"], PO))
        assert data[0]["status"] == "SUBMITTED", \
            "rejected decision leaves the valuation SUBMITTED"

    def test_approve_already_decided_valuation_rejected(self):
        """PRD section 3.3: "Only a `SUBMITTED` valuation can be decided;
        one already `APPROVED`, `REJECTED`, or `SUPERSEDED` rejects the
        attempt with `ERR_VALUATION_ALREADY_DECIDED`."

        Design: Corner/state_machines/approve_already_decided_valuation_rejected
        """
        _ev, _dn, _item, valuation = _item_with_submitted_valuation()
        approve_valuation(valuation["id"])
        resp = api_client.approve_valuation(valuation["id"], VA)
        validate_error(resp, ApiErrorId.ERR_VALUATION_ALREADY_DECIDED)

    def test_procurement_officer_cannot_approve_valuation(self):
        """PRD section 2.1: "A request whose role is not permitted for the
        targeted operation is rejected with `ERR_UNAUTHORIZED_ROLE`
        (HTTP 403)." PRD section 4: POST /valuations/{id}/approve is
        authorized for ValuationApprover only.

        Design: Corner/rbac/procurement_officer_cannot_approve_valuation
        """
        _ev, _dn, _item, valuation = _item_with_submitted_valuation()
        resp = api_client.approve_valuation(
            valuation["id"], make_procurement_officer_headers("po_2"))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    def test_valuation_supersede_stale_item_version(self):
        """PRD section 3.3: "Submission is destructive to pending
        competition: any valuation of the same item still `SUBMITTED`
        immediately transitions to `SUPERSEDED`, and the item's `version`
        increments by one." PRD section 2.7: "`POST
        /items/{id}/valuations` requires `expected_item_version`, matched
        against the item's current `version`."

        Design: Corner/cross_cutting_complexity_layers/occ_valuation_supersede_stale_item
        """
        _ev, _dn, item, va1 = _item_with_submitted_valuation(
            fmv_cents=30000)
        assert item["version"] == 1

        item_v2 = get_success_data(api_client.get_item(item["id"], PO))
        assert item_v2["version"] == 2
        resp = api_client.submit_valuation(
            item["id"],
            {
                "fmv_cents": 31000,
                "fmv_source": "APPRAISAL",
                "expected_item_version": item_v2["version"],
            },
            make_procurement_officer_headers("po_1"),
        )
        va2 = validate_success(resp, expected_status=201)

        stale = api_client.submit_valuation(
            item["id"],
            {
                "fmv_cents": 32000,
                "fmv_source": "COMPARABLE_SALE",
                "expected_item_version": item["version"],
            },
            make_procurement_officer_headers("po_1"),
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        data, _meta = validate_paginated(
            api_client.list_item_valuations(item["id"], PO))
        by_id = {v["id"]: v for v in data}
        assert by_id[va1["id"]]["status"] == "SUPERSEDED"
        assert by_id[va2["id"]]["status"] == "SUBMITTED"


class TestAcknowledgmentThreshold:

    def test_ack_threshold_exact_boundary(self):
        """PRD section 3.9: "A `FinanceOfficer` issues the acknowledgment
        only when its `fmv_cents` reaches at least the event's
        `ack_threshold_cents`; the comparison is inclusive, so a value
        exactly equal to the threshold issues cleanly, and anything below
        it is rejected with `ERR_ACK_THRESHOLD_NOT_MET`."

        Design: Corner/validations/ack_threshold_exact_boundary
        """
        event = create_event()
        api_client.advance_gala_event(event["id"], ADMIN)  # SOLICITING
        below = setup_valued_item(event["id"], 24999)
        exact = setup_valued_item(event["id"], 25000)

        ack_below = get_acknowledgment_for_item(below["item"]["id"])
        ack_exact = get_acknowledgment_for_item(exact["item"]["id"])

        resp = api_client.issue_acknowledgment(ack_below["id"], FO)
        validate_error(resp, ApiErrorId.ERR_ACK_THRESHOLD_NOT_MET)

        issued = validate_success(
            api_client.issue_acknowledgment(ack_exact["id"], FO))
        assert_acknowledgment(issued)
        assert issued["status"] == "ISSUED"
        assert issued["fmv_cents"] == 25000
        assert issued["issued_at"] is not None


class TestRevaluationAcknowledgmentChain:

    def _issued_ack_then_new_valuation(self):
        """Item valued 40000; its acknowledgment ISSUED; a second
        valuation of 46000 submitted and awaiting the approval trigger."""
        event = create_event()
        api_client.advance_gala_event(event["id"], ADMIN)  # SOLICITING
        part = setup_valued_item(event["id"], 40000, title="Clock")
        item = part["item"]
        ack1 = get_acknowledgment_for_item(item["id"])
        validate_success(api_client.issue_acknowledgment(ack1["id"], FO))
        va2 = submit_valuation(item["id"], 46000)
        return event, item, ack1, va2

    def test_revaluation_after_issue_updates_item_and_voids_ack(self):
        """PRD section 3.3: "When a later valuation is approved for an item
        in `VALUED`, `BUNDLED`, `CATALOGED`, `SOLD`, or `UNSOLD`, the
        item's status does not change — a bundled item stays `BUNDLED` —
        but its `current_fmv_cents` and `disclosure_tier` are updated from
        the new approval." PRD section 3.3: "If the acknowledgment was
        already `ISSUED`, it is voided and a fresh `PENDING` acknowledgment
        is created carrying the new value."

        Design: Difficulty/transitive_cascade/valuation_approve_acknowledgment_chain
        """
        _ev, item, ack1, va2 = self._issued_ack_then_new_valuation()
        validate_success(api_client.approve_valuation(va2["id"], VA))

        item_after = get_success_data(api_client.get_item(item["id"], PO))
        assert item_after["current_fmv_cents"] == 46000, \
            "hop 1: approval mutates the item"
        assert item_after["status"] == "VALUED", "self-loop: status unchanged"

        ack1_after = get_success_data(
            api_client.get_acknowledgment(ack1["id"], FO))
        assert ack1_after["status"] == "VOIDED", \
            "hop 2: the ISSUED acknowledgment is voided"

    def test_revaluation_after_issue_creates_fresh_pending_ack(self):
        """PRD section 3.3: "If the acknowledgment was already `ISSUED`,
        it is voided and a fresh `PENDING` acknowledgment is created
        carrying the new value."

        Design: Difficulty/transitive_cascade/valuation_approve_acknowledgment_chain
        """
        _ev, item, ack1, va2 = self._issued_ack_then_new_valuation()
        validate_success(api_client.approve_valuation(va2["id"], VA))

        data, _meta = validate_paginated(api_client.list_acknowledgments(
            FO, params={"item_id": item["id"], "status": "PENDING"}))
        assert len(data) == 1, "hop 3: exactly one fresh PENDING ack"
        fresh = data[0]
        assert fresh["id"] != ack1["id"]
        assert fresh["fmv_cents"] == 46000, "carries the new value"
        assert fresh["disclosure_tier"] == "LOW"
        assert fresh["status"] == "PENDING"


class TestAsOfIssueVsPinnedAtSale:

    def _sold_then_revalued(self):
        """Item valued 40000 sold solo for 50000; then a second valuation
        of 45000 is submitted and approved after the close."""
        ctx = setup_sold_scenario(fmv_cents=40000, bid_amount=50000,
                                  kind="PHYSICAL")
        item = ctx["items"][0]
        va2 = submit_valuation(item["id"], 45000,
                               fmv_source="COMPARABLE_SALE")
        approve_valuation(va2["id"])
        return ctx, item

    def test_pending_acknowledgment_tracks_latest_approval(self):
        """PRD section 3.9: "While an acknowledgment is `PENDING`, its
        `fmv_cents` and `disclosure_tier` track the item's latest
        `APPROVED` valuation — the as-of-issue rule — refreshing with each
        re-valuation."

        Design: Difficulty/dual_variant_calc/acknowledgment_fmv_asof_vs_pinned
        """
        ctx, item = self._sold_then_revalued()
        ack = get_acknowledgment_for_item(item["id"])
        assert ack["status"] == "PENDING"
        assert ack["fmv_cents"] == 45000, \
            "as-of-issue: refreshed to the new approval"

        item_after = get_success_data(api_client.get_item(item["id"], PO))
        assert item_after["current_fmv_cents"] == 45000

    def test_invoice_pinned_fmv_immune_to_revaluation(self):
        """PRD section 3.9: "`pinned_bundle_fmv_cents` is frozen at bundle
        publish and copied to the invoice at close, immune to later
        re-valuation, so when a re-valuation lands after the sale the
        acknowledgment reflects the new value — say 45000 cents — while
        the invoice still reports the pinned 40000 cents."

        Design: Difficulty/dual_variant_calc/acknowledgment_fmv_asof_vs_pinned
        """
        ctx, _item = self._sold_then_revalued()
        invoice = get_success_data(
            api_client.get_invoice(ctx["invoice"]["id"], FO))
        assert invoice["pinned_bundle_fmv_cents"] == 40000, \
            "pinned-at-sale unchanged"
        assert invoice["contribution_portion_cents"] == 10000, \
            "contribution computed from the pinned 40000, not 45000"
        assert invoice["revenue_portion_cents"] == 40000
