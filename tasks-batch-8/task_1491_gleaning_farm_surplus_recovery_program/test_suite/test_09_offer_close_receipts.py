"""Offer closing: salvage ratio, donation receipt variants, donor credit, and the
OCC / incident gates (PRD §2.9, §3.4, §3.6)."""
import pytest

from test_helpers import (
    ApiErrorId,
    close_offer,
    coordinator_headers,
    get_farm,
    get_offer,
    get_offer_receipts,
    open_incident,
    resolve_incident,
    setup_closed_offer,
    setup_reconciled_event,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


class TestGrossReceiptVariant:
    def test_close_mints_gross_receipt_when_no_incidents(self, api):
        """PRD §3.6: "When no food-safety incident on any of the offer's events ever
        reached a resolved state, `receipt_lbs` equals `actual_lbs` — the gross
        basis."
        PRD §3.6: "The receipt's `fair_market_value_cents` is the receipt pounds
        multiplied by the per-pound price keyed on the offer's `crop_code` — 33 cents
        for `SWEET_CORN`, 41 for `APPLES`, 74 for `LEAFY_GREENS`, 58 for `TOMATOES`,
        29 for `ROOT_VEG`, and 36 for `WINTER_SQUASH`, with any other crop valued at a
        default of 40 cents per pound — rounded half-up to a whole cent."

        Design: Difficulty/dual_variant_calc/donation_receipt_gross_vs_net_variant
        """
        ctx = setup_closed_offer(
            offer_over={"crop_code": "SWEET_CORN", "estimated_lbs": 250.0},
            lot_specs=[{"gross": 220.0, "cull": 10.0, "verify": True}],  # net 200.0
        )
        assert ctx["offer"]["status"] == "CLOSED"
        receipt = ctx["receipt"]
        assert receipt is not None
        assert receipt["receipt_lbs"] == pytest.approx(200.0)
        assert receipt["fair_market_value_cents"] == 6600, "200.0 lbs * 33 cents"
        assert receipt["farm_id"] == ctx["farm"]["id"]

    def test_close_computes_salvage_ratio_and_credits_farm(self, api):
        """PRD §3.6: "The `salvage_ratio` is computed as `actual_lbs` divided by
        `estimated_lbs`, rounded half-up to four decimal places; the raw ratio always
        uses all verified pounds, including any later condemned."
        PRD §3.6: "The credited pounds then roll into the farm's
        `lifetime_donated_lbs`, bumping the farm's `version` as part of the same
        close."

        Design: Difficulty/dual_variant_calc/donation_receipt_gross_vs_net_variant
        """
        ctx = setup_closed_offer(
            offer_over={"crop_code": "SWEET_CORN", "estimated_lbs": 250.0},
            lot_specs=[{"gross": 220.0, "cull": 10.0, "verify": True}],
        )
        offer = get_offer(ctx["offer"]["id"])
        assert offer["salvage_ratio"] == pytest.approx(0.8, abs=1e-9), "200.0 / 250.0"
        assert offer["actual_lbs"] == pytest.approx(200.0)
        farm = get_farm(ctx["farm"]["id"])
        assert farm["lifetime_donated_lbs"] == pytest.approx(200.0)


class TestNetReceiptVariant:
    def test_resolved_incident_switches_receipt_to_net_basis(self, api):
        """PRD §3.6: "When at least one incident has resolved, `receipt_lbs` is
        `actual_lbs` minus the total `condemned_lbs` of the resolved incidents across
        the offer's events, floored at zero."

        Design: Difficulty/dual_variant_calc/donation_receipt_net_variant_with_incident
        """
        ctx = setup_closed_offer(
            offer_over={"crop_code": "SWEET_CORN", "estimated_lbs": 250.0},
            lot_specs=[{"gross": 220.0, "cull": 10.0, "verify": True}],  # net 200.0
            incident_specs=[{"severity": "MINOR", "condemned_lbs": 40.0,
                             "disposition": "LANDFILL"}],
        )
        receipt = ctx["receipt"]
        assert receipt["receipt_lbs"] == pytest.approx(160.0), "200.0 - 40.0 condemned"
        assert receipt["fair_market_value_cents"] == 5280, "160.0 lbs * 33 cents"

    def test_salvage_ratio_stays_gross_while_farm_credit_is_net(self, api):
        """PRD §3.6: "The `salvage_ratio` is computed as `actual_lbs` divided by
        `estimated_lbs`, rounded half-up to four decimal places; the raw ratio always
        uses all verified pounds, including any later condemned."
        PRD §3.6: "The credited pounds then roll into the farm's
        `lifetime_donated_lbs`, bumping the farm's `version` as part of the same
        close."

        Design: Difficulty/dual_variant_calc/donation_receipt_net_variant_with_incident
        """
        ctx = setup_closed_offer(
            offer_over={"crop_code": "SWEET_CORN", "estimated_lbs": 250.0},
            lot_specs=[{"gross": 220.0, "cull": 10.0, "verify": True}],
            incident_specs=[{"severity": "MINOR", "condemned_lbs": 40.0,
                             "disposition": "LANDFILL"}],
        )
        offer = get_offer(ctx["offer"]["id"])
        assert offer["salvage_ratio"] == pytest.approx(0.8, abs=1e-9), (
            "salvage uses actual_lbs 200.0, NOT the net receipt basis"
        )
        farm = get_farm(ctx["farm"]["id"])
        assert farm["lifetime_donated_lbs"] == pytest.approx(160.0)


class TestReceiptRoundingOrder:
    def test_receipt_pounds_aggregate_before_pricing(self, api):
        """PRD §3.6: "When no food-safety incident on any of the offer's events ever
        reached a resolved state, `receipt_lbs` equals `actual_lbs` — the gross
        basis."
        PRD §3.3: "recomputes the event's `total_harvested_lbs` as the sum of
        `net_lbs` over its `VERIFIED` lots only"

        Design: Difficulty/combinatorial_formula/donation_valuation_nested_rounding_order
        """
        ctx = setup_closed_offer(
            offer_over={"crop_code": "SWEET_CORN", "estimated_lbs": 5.0},
            container_count=2,
            lot_specs=[{"gross": 10.5, "cull": 0.0, "verify": True},
                       {"gross": 10.5, "cull": 0.0, "verify": True}],  # 0.5 + 0.5
        )
        assert ctx["receipt"]["receipt_lbs"] == pytest.approx(1.0), (
            "lot pounds aggregate before pricing"
        )

    def test_fair_market_value_rounds_once_on_aggregate(self, api):
        """PRD §3.6: "The receipt's `fair_market_value_cents` is the receipt pounds
        multiplied by the per-pound price keyed on the offer's `crop_code` — 33 cents
        for `SWEET_CORN`, 41 for `APPLES`, 74 for `LEAFY_GREENS`, 58 for `TOMATOES`,
        29 for `ROOT_VEG`, and 36 for `WINTER_SQUASH`, with any other crop valued at a
        default of 40 cents per pound — rounded half-up to a whole cent."

        Design: Difficulty/combinatorial_formula/donation_valuation_nested_rounding_order
        """
        ctx = setup_closed_offer(
            offer_over={"crop_code": "SWEET_CORN", "estimated_lbs": 5.0},
            container_count=2,
            lot_specs=[{"gross": 10.5, "cull": 0.0, "verify": True},
                       {"gross": 10.5, "cull": 0.0, "verify": True}],
        )
        assert ctx["receipt"]["fair_market_value_cents"] == 33, (
            "round_half_up(1.0 * 33) == 33; per-line rounding would yield 34"
        )


class TestDefaultCropPrice:
    def test_unlisted_crop_uses_default_price(self, api):
        """PRD §3.6: "with any other crop valued at a default of 40 cents per pound —
        rounded half-up to a whole cent."

        Design: Corner/calculations/donation_valuation_default_crop_price
        """
        ctx = setup_closed_offer(
            offer_over={"crop_code": "PARSNIPS", "estimated_lbs": 120.0},
            lot_specs=[{"gross": 110.0, "cull": 0.0, "verify": True}],  # net 100.0
        )
        assert ctx["receipt"]["receipt_lbs"] == pytest.approx(100.0)
        assert ctx["receipt"]["fair_market_value_cents"] == 4000


class TestReceiptEndpoint:
    def test_receipt_listing_is_empty_before_close_and_singleton_after(self, api):
        """PRD §3.6: "Afterward, the receipt for a closed offer can be fetched
        directly — a list of zero or one entries"

        Design: Corner/endpoints/receipt_endpoint_returns_singleton_array
        """
        ctx = setup_reconciled_event(
            offer_over={"crop_code": "SWEET_CORN", "estimated_lbs": 80.0},
            lot_specs=[{"gross": 70.0, "cull": 0.0, "verify": True}],  # net 60.0
        )
        assert get_offer_receipts(ctx["offer"]["id"]) == []
        close_offer(ctx["offer"]["id"])
        receipts = get_offer_receipts(ctx["offer"]["id"])
        assert len(receipts) == 1
        assert receipts[0]["receipt_lbs"] == pytest.approx(60.0)
        assert receipts[0]["fair_market_value_cents"] == 1980
        assert "version" not in receipts[0] and "updated_at" not in receipts[0]


class TestSecondCloseRejected:
    def test_double_close_rejected_and_no_second_receipt(self, api):
        """PRD §3.6: "Closing also mints the donor's **DonationReceipt** — exactly one
        per offer, and a second issuance for the same offer is rejected with
        `ERR_DUPLICATE`."
        PRD §2.6: "20. **Terminal-state lockdown** — any action invoked on a
        resource that has already reached a terminal state is rejected with
        `ERR_ALREADY_TERMINAL` (HTTP 409)."

        Design: Corner/errors/double_close_offer_duplicate_receipt
        """
        ctx = setup_closed_offer(
            lot_specs=[{"gross": 60.0, "cull": 0.0, "verify": True}],
        )
        current = get_offer(ctx["offer"]["id"])
        resp = api.close_offer(
            ctx["offer"]["id"], {"expected_offer_version": current["version"]},
            coordinator_headers(),
        )
        assert resp.status_code == 409
        validate_error_is_one_of(
            resp, [ApiErrorId.ERR_DUPLICATE, ApiErrorId.ERR_INVALID_STATE,
                   ApiErrorId.ERR_ALREADY_TERMINAL]
        )
        assert len(get_offer_receipts(ctx["offer"]["id"])) == 1

    def test_replayed_close_with_stale_version_never_double_mints(self, api):
        """PRD §2.9: "Closing an offer requires `expected_offer_version`, holding the
        client's last observed `version` of the offer. If the offer's current
        `version` has advanced since that observation — for example because a late lot
        verification or an incident resolution has moved it forward — the close is
        rejected with `ERR_STALE_OFFER_VERSION` (HTTP 412)"
        PRD §3.6: "a second issuance for the same offer is rejected with
        `ERR_DUPLICATE`."
        PRD §2.6 orders uniqueness (gate 18) before optimistic-concurrency staleness
        (gate 19) and terminal-state lockdown (gate 20), so a replayed close may be
        reported by any of these gates.

        Design: Corner/cross_cutting_complexity_layers/occ_offer_close_stale_version
        """
        ctx = setup_reconciled_event(
            lot_specs=[{"gross": 60.0, "cull": 0.0, "verify": True}],
        )
        observed = get_offer(ctx["offer"]["id"])["version"]
        first = api.close_offer(ctx["offer"]["id"],
                                {"expected_offer_version": observed},
                                coordinator_headers())
        validate_success(first, 200)
        replay = api.close_offer(ctx["offer"]["id"],
                                 {"expected_offer_version": observed},
                                 coordinator_headers())
        validate_error_is_one_of(
            replay,
            [
                ApiErrorId.ERR_DUPLICATE,
                ApiErrorId.ERR_STALE_OFFER_VERSION,
                ApiErrorId.ERR_INVALID_STATE,
                ApiErrorId.ERR_ALREADY_TERMINAL,
            ],
        )
        assert len(get_offer_receipts(ctx["offer"]["id"])) == 1


class TestCloseBlockedByOpenIncident:
    def _gleaned_offer_then_open_incident(self, api):
        """Event reconciled (offer GLEANED); the incident is opened afterwards so the
        offer sits GLEANED with an OPEN incident on its event."""
        ctx = setup_reconciled_event(
            offer_over={"estimated_lbs": 150.0},
            lot_specs=[{"gross": 110.0, "cull": 0.0, "verify": True}],  # net 100.0
        )
        incident = open_incident(ctx["event"]["id"], ctx["lead"]["id"],
                                 severity="MINOR", condemned_lbs=5.0)
        ctx["incident"] = incident
        return ctx

    def test_close_rejected_while_incident_open(self, api):
        """PRD §3.6: "When every glean event of a `GLEANED` offer has reached
        `RECONCILED` or `CANCELLED` and no food-safety incident on any of those events
        remains `OPEN` (`ERR_INCIDENT_OPEN`), the coordinator closes the offer."

        Design: Difficulty/cross_entity_state_dependency/offer_close_blocked_by_open_incident
        """
        ctx = self._gleaned_offer_then_open_incident(api)
        offer = get_offer(ctx["offer"]["id"])
        assert offer["status"] == "GLEANED"
        resp = api.close_offer(ctx["offer"]["id"],
                               {"expected_offer_version": offer["version"]},
                               coordinator_headers())
        validate_error(resp, ApiErrorId.ERR_INCIDENT_OPEN, 422)
        assert get_offer(ctx["offer"]["id"])["status"] == "GLEANED"

    def test_close_succeeds_after_officer_resolves_incident(self, api):
        """PRD §3.4: "Only a `FoodSafetyOfficer` may resolve an incident, supplying a
        `disposition`: `COMPOST` moves it to `RESOLVED_COMPOST`"
        PRD §3.6: "When at least one incident has resolved, `receipt_lbs` is
        `actual_lbs` minus the total `condemned_lbs` of the resolved incidents across
        the offer's events, floored at zero."

        Design: Difficulty/cross_entity_state_dependency/offer_close_blocked_by_open_incident
        """
        ctx = self._gleaned_offer_then_open_incident(api)
        offer = get_offer(ctx["offer"]["id"])
        blocked = api.close_offer(ctx["offer"]["id"],
                                  {"expected_offer_version": offer["version"]},
                                  coordinator_headers())
        validate_error(blocked, ApiErrorId.ERR_INCIDENT_OPEN, 422)
        resolve_incident(ctx["incident"]["id"], "COMPOST")
        offer = get_offer(ctx["offer"]["id"])
        closed = api.close_offer(ctx["offer"]["id"],
                                 {"expected_offer_version": offer["version"]},
                                 coordinator_headers())
        closed_offer = validate_success(closed, 200)
        assert closed_offer["status"] == "CLOSED"
        receipts = get_offer_receipts(ctx["offer"]["id"])
        assert receipts[0]["receipt_lbs"] == pytest.approx(95.0), "100.0 - 5.0 condemned"
        assert receipts[0]["fair_market_value_cents"] == 2755, "95.0 * 29 cents ROOT_VEG"
