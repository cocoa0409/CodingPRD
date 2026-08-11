"""Consignment agreements, consumption reports, settlement, OCC, close guards."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_consignment_units_invariant,
    create_agreement_payload,
    create_distributor,
    create_formulation,
    create_report,
    get_agreement,
    get_stock_row,
    make_distributor_headers,
    set_clock,
    setup_consignment_scenario,
    setup_submitted_report,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestProvisionalVsFinalSettlement:
    """Difficulty instance consignment_provisional_vs_final_settlement."""

    def _setup(self, api):
        ctx = setup_consignment_scenario(
            "PU-SET-1", units_to_dispatch=300, unit_price_cents=2000,
            max_consigned_value_cents=900000, reorder_threshold_units=0, reorder_qty_units=200,
        )
        report = create_report(
            ctx["agreement"]["id"], ctx["distributor"]["id"], ctx["agreement"]["version"],
            period="2026-06", consumed_units=260,
        )
        ctx["report"] = report
        return ctx

    def test_submit_records_flat_gross_provisional(self, api, commercial_manager_headers):
        """PRD §3.10: "On success the report moves to `SUBMITTED` and the provisional settlement is recorded as `consumed_units` times the agreement's `unit_price_cents`, stored in `provisional_settlement_cents`."

        Design: Difficulty/dual_variant_calc/consignment_provisional_vs_final_settlement
        """
        ctx = self._setup(api)
        submitted = validate_success(
            api.submit_report(ctx["report"]["id"], make_distributor_headers(ctx["distributor"]["id"]))
        )
        assert submitted["status"] == "SUBMITTED"
        assert submitted["provisional_settlement_cents"] == 520000  # 260 x 2000, no rebate

        stock = get_stock_row(ctx["agreement"]["id"])
        assert stock["qty_consumed"] == 260
        assert stock["qty_on_hand"] == 40

    def test_settle_applies_tiered_rebate_on_gross(self, api, commercial_manager_headers, qa_manager_headers):
        """PRD §3.10: "A `CommercialManager` settles a `SUBMITTED` report, producing the final figures in a pinned evaluation order: the gross is `consumed_units` times the agreement's `unit_price_cents`; the `rebate_tier` is keyed on that gross — a gross of at least 1000000 cents earns `TIER2` at 10%, a gross of at least 500000 cents earns `TIER1` at 5%, and anything below earns `NONE` at 0%, with both thresholds inclusive (a gross of exactly 500000 cents already earns `TIER1`); `rebate_cents` is the gross multiplied by the tier percentage and divided by 100, rounded half-up to whole cents; and `final_net_settlement_cents` is the gross minus the rebate."
        PRD §3.10: "The provisional figure computed at submit is always the flat list-price gross with no rebate, so it is at least the final net whenever a tier applies."

        Design: Difficulty/dual_variant_calc/consignment_provisional_vs_final_settlement
        """
        ctx = self._setup(api)
        submitted = validate_success(
            api.submit_report(ctx["report"]["id"], make_distributor_headers(ctx["distributor"]["id"]))
        )
        settled = validate_success(api.settle_report(submitted["id"], commercial_manager_headers))
        # gross 520000 >= 500000 -> TIER1 (5%); rebate 26000; net 494000.
        assert settled["rebate_tier"] == "TIER1"
        assert settled["rebate_cents"] == 26000
        assert settled["final_net_settlement_cents"] == 494000
        # Identical consumed_units, different money per variant.
        assert submitted["provisional_settlement_cents"] != settled["final_net_settlement_cents"]


class TestConsumptionReportReplenishmentChain:
    """Difficulty instance consumption_report_stock_replenishment_chain."""

    def _setup(self, api):
        ctx = setup_consignment_scenario(
            "PU-RPL-1", units_to_dispatch=300, unit_price_cents=2000,
            max_consigned_value_cents=900000, reorder_threshold_units=100, reorder_qty_units=200,
        )
        report1 = create_report(
            ctx["agreement"]["id"], ctx["distributor"]["id"], ctx["agreement"]["version"],
            period="2026-06", consumed_units=250,
        )
        ctx["report1"] = report1
        return ctx

    def test_submit_decrements_stock_and_creates_auto_replenishment(self, api, commercial_manager_headers):
        """PRD §3.10: "Submit then applies the stock waterfall: the agreement's `ConsignmentStock` rows with positive `qty_on_hand` are visited in FIFO order — ascending by their lot's `expiry_date`, ties broken by ascending lot `created_at` — and each row yields up to its full `qty_on_hand` toward the reported `consumed_units`, incrementing `qty_consumed` and decrementing `qty_on_hand` by the amount taken, until the reported quantity is fully allocated."
        PRD §3.10: "Submit finishes with the reorder cascade: when the agreement's total `qty_on_hand` has fallen below its `reorder_threshold_units`, and no shipment already exists for this agreement with `auto_replenishment` true in `DRAFT`, `PLANNED`, or `CONFIRMED`, the server creates a replenishment shipment — `shipment_kind` `CONSIGNMENT_REPLENISHMENT`, `auto_replenishment` true, `proposed_units` set to the agreement's `reorder_qty_units`, the distributor taken from the agreement, `transport_mode` `ROAD`, `ship_date` set seven days after the current logical-clock date, and status `DRAFT`."

        Design: Difficulty/transitive_cascade/consumption_report_stock_replenishment_chain
        """
        ctx = self._setup(api)
        validate_success(
            api.submit_report(ctx["report1"]["id"], make_distributor_headers(ctx["distributor"]["id"]))
        )
        stock = get_stock_row(ctx["agreement"]["id"])
        assert stock["qty_consumed"] == 250
        assert stock["qty_on_hand"] == 50

        data, meta = validate_paginated(
            api.list_shipments(
                commercial_manager_headers,
                params={"agreement_id": ctx["agreement"]["id"], "shipment_kind": "CONSIGNMENT_REPLENISHMENT"},
            )
        )
        assert meta["total_count"] == 1
        assert data[0]["status"] == "DRAFT"
        assert data[0]["auto_replenishment"] is True
        assert data[0]["proposed_units"] == 200
        assert data[0]["transport_mode"] == "ROAD"

    def test_second_submit_while_replenishment_open_creates_no_second_draft(self, api, commercial_manager_headers):
        """PRD §3.10: "Submit finishes with the reorder cascade: when the agreement's total `qty_on_hand` has fallen below its `reorder_threshold_units`, and no shipment already exists for this agreement with `auto_replenishment` true in `DRAFT`, `PLANNED`, or `CONFIRMED`, the server creates a replenishment shipment — `shipment_kind` `CONSIGNMENT_REPLENISHMENT`, `auto_replenishment` true, `proposed_units` set to the agreement's `reorder_qty_units`, the distributor taken from the agreement, `transport_mode` `ROAD`, `ship_date` set seven days after the current logical-clock date, and status `DRAFT`."

        Design: Difficulty/transitive_cascade/consumption_report_stock_replenishment_chain
        """
        ctx = self._setup(api)
        dist_headers = make_distributor_headers(ctx["distributor"]["id"])
        validate_success(api.submit_report(ctx["report1"]["id"], dist_headers))

        fresh_version = get_agreement(ctx["agreement"]["id"])["version"]
        report2 = create_report(
            ctx["agreement"]["id"], ctx["distributor"]["id"], fresh_version,
            period="2026-07", consumed_units=10,
        )
        validate_success(api.submit_report(report2["id"], dist_headers))

        data, meta = validate_paginated(
            api.list_shipments(
                commercial_manager_headers,
                params={"agreement_id": ctx["agreement"]["id"], "shipment_kind": "CONSIGNMENT_REPLENISHMENT"},
            )
        )
        assert meta["total_count"] == 1  # still exactly one open auto replenishment

        stock = get_stock_row(ctx["agreement"]["id"])
        assert stock["qty_consumed"] == 260
        assert stock["qty_on_hand"] == 40


class TestResumeDualFailureStateBeatsFiscal:
    """Difficulty instance resume_dual_failure_state_beats_fiscal."""

    def _setup(self, api, commercial_manager_headers):
        distributor = create_distributor(name="Dist CF", credit_limit_cents=1000000, contact_email="c@x.com")
        formulation = create_formulation("EPX-CF-1", activate=False)
        ag1 = validate_success(
            api.create_agreement(
                create_agreement_payload(
                    distributor["id"], formulation["id"],
                    unit_price_cents=1000, max_consigned_value_cents=700000,
                    reorder_threshold_units=10, reorder_qty_units=50,
                ),
                commercial_manager_headers,
            ),
            expected_status=201,
        )
        validate_success(api.activate_agreement(ag1["id"], commercial_manager_headers))
        ag2 = validate_success(
            api.create_agreement(
                create_agreement_payload(
                    distributor["id"], formulation["id"],
                    unit_price_cents=1000, max_consigned_value_cents=400000,
                    reorder_threshold_units=10, reorder_qty_units=50,
                ),
                commercial_manager_headers,
            ),
            expected_status=201,
        )
        return distributor, ag1, ag2

    def test_resume_on_draft_reports_state_error_not_credit_error(self, api, commercial_manager_headers):
        """PRD §2.5: "5. **State preconditions.** Transition from-states and cross-entity state gates (for example `ERR_BATCH_INVALID_STATE`, `ERR_FORMULATION_NOT_EFFECTIVE`, `ERR_AGREEMENT_NOT_ACTIVE`, `ERR_LOT_NOT_SHIPPABLE`, `ERR_LOT_ON_HOLD`, `ERR_SHIPMENT_BLOCKED_LINES`) are enforced; violations carry HTTP 409."
        PRD §2.5: "10. **Fiscal.** The credit limit at agreement activate or resume (`ERR_CREDIT_LIMIT_EXCEEDED`, HTTP 402)."
        PRD §3.8: "Suspension moves `ACTIVE` to `SUSPENDED`, and resume moves `SUSPENDED` back to `ACTIVE` while re-running the same credit check."

        Design: Difficulty/priority_pair_validation_conflict/resume_dual_failure_state_beats_fiscal
        """
        _distributor, _ag1, ag2 = self._setup(api, commercial_manager_headers)
        # 700000 + 400000 = 1100000 > 1000000 also holds, but ag2 is DRAFT so the
        # state precondition fails first.
        resp = api.resume_agreement(ag2["id"], commercial_manager_headers)
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_INVALID_STATE)
        assert resp.json()["data"]["error_id"] != "ERR_CREDIT_LIMIT_EXCEEDED"

    def test_agreement_unchanged_after_dual_failure_resume(self, api, commercial_manager_headers):
        """PRD §3.8: "Suspension moves `ACTIVE` to `SUSPENDED`, and resume moves `SUSPENDED` back to `ACTIVE` while re-running the same credit check."

        Design: Difficulty/priority_pair_validation_conflict/resume_dual_failure_state_beats_fiscal
        """
        _distributor, _ag1, ag2 = self._setup(api, commercial_manager_headers)
        api.resume_agreement(ag2["id"], commercial_manager_headers)
        after = validate_success(api.get_agreement(ag2["id"], commercial_manager_headers))
        assert after["status"] == "DRAFT"


class TestConsignmentUnitsConservation:
    """Difficulty instance consignment_units_conserved_across_dispatch_report_return."""

    def _setup(self, api, commercial_manager_headers):
        ctx = setup_submitted_report(
            "PU-INV-2", consumed_units=260, units_to_dispatch=300,
            unit_price_cents=2000, reorder_threshold_units=0, reorder_qty_units=100,
        )
        stock = get_stock_row(ctx["agreement"]["id"])
        ctx["stock"] = stock
        return ctx

    def test_return_updates_row_and_lot(self, api, commercial_manager_headers, qa_manager_headers):
        """PRD §3.10: "The return is the compensating action of dispatch: it requires the agreement not to be `CLOSED` (else `ERR_AGREEMENT_INVALID_STATE`), requires `units` not to exceed the stock row's `qty_on_hand` (else `ERR_RETURN_EXCEEDS_ON_HAND`), and on success grows the row's `qty_returned` by `units`, shrinks `qty_on_hand` by `units`, and decrements the lot's `units_shipped` by the same amount."

        Design: Difficulty/compensating_invariant/consignment_units_conserved_across_dispatch_report_return
        """
        ctx = self._setup(api, commercial_manager_headers)
        returned = validate_success(
            api.return_stock(
                ctx["stock"]["id"], {"units": 10, "note": "damaged cartridges returned"},
                commercial_manager_headers,
            )
        )
        assert returned["qty_shipped"] == 300
        assert returned["qty_consumed"] == 260
        assert returned["qty_returned"] == 10
        assert returned["qty_on_hand"] == 30
        assert_consignment_units_invariant(returned)

        lot = validate_success(api.get_production_lot(ctx["lot_id"], qa_manager_headers))
        assert lot["units_shipped"] == 290  # 300 dispatched minus 10 returned

    def test_invariant_holds_at_every_step(self, api, commercial_manager_headers):
        """PRD §3.9: "A stock row's `qty_on_hand` is always its `qty_shipped` minus `qty_consumed` minus `qty_returned`, and `qty_consumed` and `qty_returned` start at zero."

        Design: Difficulty/compensating_invariant/consignment_units_conserved_across_dispatch_report_return
        """
        ctx = self._setup(api, commercial_manager_headers)
        # After dispatch + submit (before return): 300 - 260 - 0 == 40.
        stock = get_stock_row(ctx["agreement"]["id"])
        assert stock["qty_shipped"] == 300
        assert stock["qty_consumed"] == 260
        assert stock["qty_on_hand"] == 40
        assert_consignment_units_invariant(stock)

        # After the compensating return of 10: 300 - 260 - 10 == 30.
        validate_success(
            api.return_stock(stock["id"], {"units": 10}, commercial_manager_headers)
        )
        after = validate_success(api.get_consignment_stock(stock["id"], commercial_manager_headers))
        assert_consignment_units_invariant(after)
        assert after["qty_on_hand"] == 30


class TestCreditLimitBoundary:
    def test_credit_limit_equality_passes(self, api, commercial_manager_headers):
        """PRD §3.8: "The boundary is inclusive — a total exactly equal to the limit passes — while a strictly greater total is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`."

        Design: Corner/calculations/credit_limit_equality_passes
        """
        distributor = create_distributor(name="Dist CR", credit_limit_cents=1000000, contact_email="cr@x.com")
        formulation = create_formulation("PU-CR", activate=False)
        ag1 = validate_success(
            api.create_agreement(
                create_agreement_payload(
                    distributor["id"], formulation["id"], unit_price_cents=1000,
                    max_consigned_value_cents=700000, reorder_threshold_units=10, reorder_qty_units=50,
                ),
                commercial_manager_headers,
            ),
            expected_status=201,
        )
        validate_success(api.activate_agreement(ag1["id"], commercial_manager_headers))
        ag2 = validate_success(
            api.create_agreement(
                create_agreement_payload(
                    distributor["id"], formulation["id"], unit_price_cents=1000,
                    max_consigned_value_cents=300000, reorder_threshold_units=10, reorder_qty_units=50,
                ),
                commercial_manager_headers,
            ),
            expected_status=201,
        )
        activated = validate_success(api.activate_agreement(ag2["id"], commercial_manager_headers))
        assert activated["status"] == "ACTIVE"  # 700000 + 300000 == 1000000 == limit passes

    def test_credit_limit_exceeded_when_strictly_greater(self, api, commercial_manager_headers):
        """PRD §3.8: "The boundary is inclusive — a total exactly equal to the limit passes — while a strictly greater total is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`."

        Design: Corner/calculations/credit_limit_exceeded_when_strictly_greater
        """
        distributor = create_distributor(name="Dist CRX", credit_limit_cents=1000000, contact_email="crx@x.com")
        formulation = create_formulation("PU-CRX", activate=False)
        ag1 = validate_success(
            api.create_agreement(
                create_agreement_payload(
                    distributor["id"], formulation["id"], unit_price_cents=1000,
                    max_consigned_value_cents=700000, reorder_threshold_units=10, reorder_qty_units=50,
                ),
                commercial_manager_headers,
            ),
            expected_status=201,
        )
        validate_success(api.activate_agreement(ag1["id"], commercial_manager_headers))
        ag2 = validate_success(
            api.create_agreement(
                create_agreement_payload(
                    distributor["id"], formulation["id"], unit_price_cents=1000,
                    max_consigned_value_cents=300001, reorder_threshold_units=10, reorder_qty_units=50,
                ),
                commercial_manager_headers,
            ),
            expected_status=201,
        )
        resp = api.activate_agreement(ag2["id"], commercial_manager_headers)
        validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)  # 1000001 > 1000000
        after = validate_success(api.get_agreement(ag2["id"], commercial_manager_headers))
        assert after["status"] == "DRAFT"


class TestSettlementTier2Boundary:
    def test_settlement_tier2_inclusive_gross_boundary(self, api, commercial_manager_headers):
        """PRD §3.10: "the `rebate_tier` is keyed on that gross — a gross of at least 1000000 cents earns `TIER2` at 10%, a gross of at least 500000 cents earns `TIER1` at 5%, and anything below earns `NONE` at 0%, with both thresholds inclusive (a gross of exactly 500000 cents already earns `TIER1`)"

        Design: Corner/calculations/settlement_tier2_inclusive_gross_boundary
        """
        ctx = setup_submitted_report(
            "PU-T2", consumed_units=500, units_to_dispatch=500, unit_price_cents=2000,
            reorder_threshold_units=0, reorder_qty_units=100, planned_units=600,
        )
        settled = validate_success(api.settle_report(ctx["report"]["id"], commercial_manager_headers))
        # gross 500 x 2000 == 1000000 >= 1000000 (inclusive) -> TIER2.
        assert settled["rebate_tier"] == "TIER2"
        assert settled["rebate_cents"] == 100000
        assert settled["final_net_settlement_cents"] == 900000


class TestReportLifecycle:
    def test_report_revise_rolls_back_waterfall(self, api, commercial_manager_headers):
        """PRD §3.10: "Revision — a `Distributor` action on a `DISPUTED` report whose owning agreement belongs to the caller — cycles the report back to `DRAFT`, rolls back the submit waterfall row by row (each row's `qty_consumed` decreases and `qty_on_hand` increases by the amount that row had contributed), clears `provisional_settlement_cents` to null, and cancels the linked auto-replenishment shipment when it is still in `DRAFT` (one already `PLANNED` or further is left untouched); a `consumed_units` value supplied in the revise payload replaces the report's figure."

        Design: Corner/state_machines/report_revise_rolls_back_waterfall
        """
        ctx = setup_submitted_report(
            "PU-RVK", consumed_units=250, units_to_dispatch=300,
            unit_price_cents=2000, reorder_threshold_units=0, reorder_qty_units=100,
        )
        validate_success(
            api.dispute_report(ctx["report"]["id"], {"reason": "count mismatch"}, commercial_manager_headers)
        )
        revised = validate_success(
            api.revise_report(ctx["report"]["id"], {}, make_distributor_headers(ctx["distributor"]["id"]))
        )
        assert revised["status"] == "DRAFT"
        assert revised["provisional_settlement_cents"] is None

        stock = get_stock_row(ctx["agreement"]["id"])
        assert stock["qty_consumed"] == 0
        assert stock["qty_on_hand"] == 300  # 250-unit decrement fully reversed

    def test_draft_report_superseded_by_new_create(self, api, commercial_manager_headers):
        """PRD §3.10: "At most one non-`VOID` report may exist per agreement and period: when a non-`DRAFT` report (one in `SUBMITTED`, `SETTLED`, or `DISPUTED`) already exists for the pair, creation is rejected with `ERR_REPORT_PERIOD_DUPLICATE`; when a `DRAFT` report already exists for the pair, the new report legitimately supersedes it and the older `DRAFT` is moved to `VOID`."

        Design: Corner/state_machines/draft_report_superseded_by_new_create
        """
        formulation = create_formulation("PU-SUP", activate=False)
        distributor = create_distributor(name="Dist SUP", contact_email="s@x.com")
        agreement = validate_success(
            api.create_agreement(
                create_agreement_payload(distributor["id"], formulation["id"]),
                commercial_manager_headers,
            ),
            expected_status=201,
        )
        agreement = validate_success(api.activate_agreement(agreement["id"], commercial_manager_headers))
        dist_headers = make_distributor_headers(distributor["id"])
        rep1 = create_report(agreement["id"], distributor["id"], agreement["version"],
                             period="2026-06", consumed_units=5)
        v2 = get_agreement(agreement["id"])["version"]
        rep2 = create_report(agreement["id"], distributor["id"], v2,
                             period="2026-06", consumed_units=7)
        assert rep2["status"] == "DRAFT"
        assert rep2["consumed_units"] == 7
        rep1_after = validate_success(api.get_consumption_report(rep1["id"], commercial_manager_headers))
        assert rep1_after["status"] == "VOID"

    def test_settle_draft_report_returns_409(self, api, commercial_manager_headers):
        """PRD §3.10: "Settlement, dispute, and revision each require the expected from-state, failing with `ERR_REPORT_INVALID_STATE` otherwise."
        PRD §3.10: "A `CommercialManager` settles a `SUBMITTED` report, producing the final figures in a pinned evaluation order: the gross is `consumed_units` times the agreement's `unit_price_cents`; the `rebate_tier` is keyed on that gross — a gross of at least 1000000 cents earns `TIER2` at 10%, a gross of at least 500000 cents earns `TIER1` at 5%, and anything below earns `NONE` at 0%, with both thresholds inclusive (a gross of exactly 500000 cents already earns `TIER1`); `rebate_cents` is the gross multiplied by the tier percentage and divided by 100, rounded half-up to whole cents; and `final_net_settlement_cents` is the gross minus the rebate."

        Design: Corner/errors/settle_draft_report_returns_409
        """
        formulation = create_formulation("PU-STL", activate=False)
        distributor = create_distributor(name="Dist STL", contact_email="st@x.com")
        agreement = validate_success(
            api.create_agreement(
                create_agreement_payload(distributor["id"], formulation["id"]),
                commercial_manager_headers,
            ),
            expected_status=201,
        )
        agreement = validate_success(api.activate_agreement(agreement["id"], commercial_manager_headers))
        report = create_report(agreement["id"], distributor["id"], agreement["version"],
                               period="2026-06", consumed_units=5)
        resp = api.settle_report(report["id"], commercial_manager_headers)
        validate_error(resp, ApiErrorId.ERR_REPORT_INVALID_STATE)

    def test_report_period_duplicate_returns_409(self, api, commercial_manager_headers):
        """PRD §3.10: "At most one non-`VOID` report may exist per agreement and period: when a non-`DRAFT` report (one in `SUBMITTED`, `SETTLED`, or `DISPUTED`) already exists for the pair, creation is rejected with `ERR_REPORT_PERIOD_DUPLICATE`; when a `DRAFT` report already exists for the pair, the new report legitimately supersedes it and the older `DRAFT` is moved to `VOID`."

        Design: Corner/errors/report_period_duplicate_returns_409
        """
        ctx = setup_submitted_report(
            "PU-DUP", consumed_units=50, units_to_dispatch=100,
            unit_price_cents=2000, reorder_threshold_units=0, reorder_qty_units=100,
        )
        v2 = get_agreement(ctx["agreement"]["id"])["version"]
        resp = api.create_consumption_report(
            ctx["agreement"]["id"],
            {"period": "2026-06", "consumed_units": 10, "expected_agreement_version": v2},
            make_distributor_headers(ctx["distributor"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REPORT_PERIOD_DUPLICATE)
        rep1_after = validate_success(
            api.get_consumption_report(ctx["report"]["id"], commercial_manager_headers)
        )
        assert rep1_after["status"] == "SUBMITTED"

    def test_stock_negative_is_atomic_returns_422(self, api, commercial_manager_headers):
        """PRD §3.10: "If the rows collectively cannot cover `consumed_units`, the submit fails with `ERR_STOCK_NEGATIVE` and **no row is modified** — the check is atomic, with no partial application."

        Design: Corner/errors/stock_negative_is_atomic_returns_422
        """
        ctx = setup_consignment_scenario(
            "PU-NEG", units_to_dispatch=40, unit_price_cents=2000,
            max_consigned_value_cents=900000, reorder_threshold_units=0, reorder_qty_units=100,
            volume_ml=200000, planned_units=400,
        )
        report = create_report(
            ctx["agreement"]["id"], ctx["distributor"]["id"], ctx["agreement"]["version"],
            period="2026-06", consumed_units=41,
        )
        resp = api.submit_report(report["id"], make_distributor_headers(ctx["distributor"]["id"]))
        validate_error(resp, ApiErrorId.ERR_STOCK_NEGATIVE)

        stock = get_stock_row(ctx["agreement"]["id"])
        assert stock["qty_on_hand"] == 40
        assert stock["qty_consumed"] == 0  # no partial decrement
        report_after = validate_success(
            api.get_consumption_report(report["id"], commercial_manager_headers)
        )
        assert report_after["status"] == "DRAFT"
        assert report_after["provisional_settlement_cents"] is None

    def test_return_exceeds_on_hand_returns_422(self, api, commercial_manager_headers):
        """PRD §3.10: "The return is the compensating action of dispatch: it requires the agreement not to be `CLOSED` (else `ERR_AGREEMENT_INVALID_STATE`), requires `units` not to exceed the stock row's `qty_on_hand` (else `ERR_RETURN_EXCEEDS_ON_HAND`), and on success grows the row's `qty_returned` by `units`, shrinks `qty_on_hand` by `units`, and decrements the lot's `units_shipped` by the same amount."

        Design: Corner/errors/return_exceeds_on_hand_returns_422
        """
        ctx = setup_submitted_report(
            "PU-RET", consumed_units=60, units_to_dispatch=100,
            unit_price_cents=2000, reorder_threshold_units=0, reorder_qty_units=100,
        )
        stock = get_stock_row(ctx["agreement"]["id"])
        assert stock["qty_on_hand"] == 40

        resp = api.return_stock(stock["id"], {"units": 41}, commercial_manager_headers)
        validate_error(resp, ApiErrorId.ERR_RETURN_EXCEEDS_ON_HAND)

        after = validate_success(api.get_consignment_stock(stock["id"], commercial_manager_headers))
        assert after["qty_shipped"] == 100
        assert after["qty_consumed"] == 60
        assert after["qty_returned"] == 0
        assert after["qty_on_hand"] == 40


class TestAgreementCloseGuards:
    def test_close_blocked_by_open_reports_returns_409(self, api, commercial_manager_headers):
        """PRD §3.8: "Close moves an agreement from `ACTIVE` or `SUSPENDED` to `CLOSED`, but only when no `ConsumptionReport` of the agreement remains in `DRAFT`, `SUBMITTED`, or `DISPUTED` (else `ERR_AGREEMENT_HAS_OPEN_REPORTS`) and every `ConsignmentStock` row of the agreement shows `qty_on_hand` of zero (else `ERR_CONSIGNMENT_STOCK_REMAINING`)."

        Design: Corner/errors/close_blocked_by_open_reports_returns_409
        """
        formulation = create_formulation("PU-CLS1", activate=False)
        distributor = create_distributor(name="Dist CLS1", contact_email="c1@x.com")
        agreement = validate_success(
            api.create_agreement(
                create_agreement_payload(distributor["id"], formulation["id"]),
                commercial_manager_headers,
            ),
            expected_status=201,
        )
        agreement = validate_success(api.activate_agreement(agreement["id"], commercial_manager_headers))
        create_report(agreement["id"], distributor["id"], agreement["version"],
                      period="2026-06", consumed_units=5)

        resp = api.close_agreement(agreement["id"], commercial_manager_headers)
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_HAS_OPEN_REPORTS)
        after = validate_success(api.get_agreement(agreement["id"], commercial_manager_headers))
        assert after["status"] == "ACTIVE"

    def test_close_blocked_by_remaining_stock_returns_409(self, api, commercial_manager_headers):
        """PRD §3.8: "Close moves an agreement from `ACTIVE` or `SUSPENDED` to `CLOSED`, but only when no `ConsumptionReport` of the agreement remains in `DRAFT`, `SUBMITTED`, or `DISPUTED` (else `ERR_AGREEMENT_HAS_OPEN_REPORTS`) and every `ConsignmentStock` row of the agreement shows `qty_on_hand` of zero (else `ERR_CONSIGNMENT_STOCK_REMAINING`)."

        Design: Corner/errors/close_blocked_by_remaining_stock_returns_409
        """
        ctx = setup_consignment_scenario(
            "PU-CLS2", units_to_dispatch=100, unit_price_cents=2000,
            max_consigned_value_cents=900000, reorder_threshold_units=0, reorder_qty_units=100,
        )
        resp = api.close_agreement(ctx["agreement"]["id"], commercial_manager_headers)
        validate_error(resp, ApiErrorId.ERR_CONSIGNMENT_STOCK_REMAINING)  # qty_on_hand 100 > 0


class TestAgreementSuspendResume:
    def test_agreement_suspend_resume_cycle(self, api, commercial_manager_headers):
        """PRD §3.8: "Suspension moves `ACTIVE` to `SUSPENDED`, and resume moves `SUSPENDED` back to `ACTIVE` while re-running the same credit check."
        PRD §3.8: "Successful activation, suspension, resume, close, and patch each increment the agreement's `version` by 1."

        Design: Corner/state_machines/agreement_suspend_resume_cycle
        """
        formulation = create_formulation("PU-CYC", activate=False)
        distributor = create_distributor(name="Dist CYC", credit_limit_cents=1000000, contact_email="cy@x.com")
        agreement = validate_success(
            api.create_agreement(
                create_agreement_payload(
                    distributor["id"], formulation["id"], max_consigned_value_cents=500000,
                ),
                commercial_manager_headers,
            ),
            expected_status=201,
        )
        assert agreement["version"] == 1
        agreement = validate_success(api.activate_agreement(agreement["id"], commercial_manager_headers))
        assert agreement["version"] == 2
        suspended = validate_success(api.suspend_agreement(agreement["id"], commercial_manager_headers))
        assert suspended["status"] == "SUSPENDED"
        assert suspended["version"] == 3
        resumed = validate_success(api.resume_agreement(agreement["id"], commercial_manager_headers))
        assert resumed["status"] == "ACTIVE"
        assert resumed["version"] == 4


class TestOptimisticConcurrency:
    def test_occ_report_create_stale_version_returns_412(self, api, commercial_manager_headers):
        """PRD §2.4: "A `POST /api/consignment-agreements/{agreementId}/consumption-reports` request must carry `expected_agreement_version` matching the target agreement's current `version`."
        PRD §2.4: "In both cases, if the value supplied by the client does not match the agreement's current `version` — for instance because the client last read the agreement before another writer advanced it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.10: "A successful create also advances the agreement's `version` by 1."

        Design: Corner/cross_cutting_layers/occ_report_create_stale_version_returns_412
        """
        formulation = create_formulation("PU-OCC1", activate=False)
        distributor = create_distributor(name="Dist OCC1", contact_email="o1@x.com")
        agreement = validate_success(
            api.create_agreement(
                create_agreement_payload(distributor["id"], formulation["id"]),
                commercial_manager_headers,
            ),
            expected_status=201,
        )
        agreement = validate_success(api.activate_agreement(agreement["id"], commercial_manager_headers))
        observed_version = agreement["version"]  # 2

        dist_headers = make_distributor_headers(distributor["id"])
        rep1 = create_report(agreement["id"], distributor["id"], observed_version,
                             period="2026-06", consumed_units=5)
        assert rep1["status"] == "DRAFT"

        # The first create bumped the agreement to version 3; replaying 2 is stale.
        resp = api.create_consumption_report(
            agreement["id"],
            {"period": "2026-07", "consumed_units": 5, "expected_agreement_version": observed_version},
            dist_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        rep1_after = validate_success(api.get_consumption_report(rep1["id"], commercial_manager_headers))
        assert rep1_after["status"] == "DRAFT"

    def test_occ_agreement_patch_stale_version_returns_412(self, api, commercial_manager_headers):
        """PRD §2.4: "A `PATCH /api/consignment-agreements/{agreementId}` request must likewise carry `expected_agreement_version`."
        PRD §2.4: "In both cases, if the value supplied by the client does not match the agreement's current `version` — for instance because the client last read the agreement before another writer advanced it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_agreement_patch_stale_version_returns_412
        """
        formulation = create_formulation("PU-OCC2", activate=False)
        distributor = create_distributor(name="Dist OCC2", contact_email="o2@x.com")
        agreement = validate_success(
            api.create_agreement(
                create_agreement_payload(
                    distributor["id"], formulation["id"], max_consigned_value_cents=500000,
                ),
                commercial_manager_headers,
            ),
            expected_status=201,
        )
        stale_version = agreement["version"]  # 1

        patched = validate_success(
            api.patch_agreement(
                agreement["id"],
                {"max_consigned_value_cents": 550000, "expected_agreement_version": stale_version},
                commercial_manager_headers,
            )
        )
        assert patched["version"] == 2
        assert patched["max_consigned_value_cents"] == 550000

        resp = api.patch_agreement(
            agreement["id"],
            {"max_consigned_value_cents": 560000, "expected_agreement_version": stale_version},
            commercial_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        after = validate_success(api.get_agreement(agreement["id"], commercial_manager_headers))
        assert after["max_consigned_value_cents"] == 550000  # the losing patch applied nothing
