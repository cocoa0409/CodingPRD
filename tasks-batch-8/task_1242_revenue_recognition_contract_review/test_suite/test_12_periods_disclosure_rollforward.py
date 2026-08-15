"""Disclosure assembly, finalization, reopen cascade, rollforward read, and
temporal posting gates (PRD §3.7, §3.9)."""
import pytest

from test_helpers import (
    ApiErrorId, validate_success, validate_error, validate_paginated,
    create_customer, create_contract, create_ssp, add_pob,
    create_invoice_payload, create_period, set_clock, get_period, get_pob,
    setup_active_contract_with_pob, setup_active_contract_with_pobs,
    make_accountant_headers, make_controller_headers,
    assert_disclosure_pack, assert_revenue_entry,
)

CLOCK = "2026-06-15T00:00:00Z"


def _create_pack(api, period_id, accountant_headers):
    return validate_success(api.create_disclosure_pack(period_id, accountant_headers), 201)


class TestTemporalGates:
    def test_cost_entry_into_closed_period_rejected(self, api, accountant_headers, controller_headers):
        """PRD §3.6: "Recording a cost against an input-cost obligation takes an
        `amount_cents` greater than zero, an `incurred_date` that must fall in
        an `OPEN` or `REOPENED` period".
        PRD §3.6: "Every posting must land in a period that is `OPEN` or
        `REOPENED`; a posting date that falls in a `CLOSED` period — or in no
        defined period at all — is rejected with `ERR_PERIOD_CLOSED`."

        Design: Corner/validations/cost_entry_into_closed_period_rejected
        """
        may = create_period(period_code="2026-05", start_date="2026-05-01", end_date="2026-06-01")
        create_period(period_code="2026-06", start_date="2026-06-01", end_date="2026-07-01")
        validate_success(api.close_accounting_period(may["id"], controller_headers))
        set_clock(CLOCK)
        setup = setup_active_contract_with_pob(
            product_code="ICA", with_period=False, clock=None,
            pob_overrides={"recognition_pattern": "OVER_TIME_INPUT_COST",
                           "estimated_total_cost_cents": 40000},
        )
        resp = api.create_cost_entry(
            setup["pob"]["id"], {"amount_cents": 5000, "incurred_date": "2026-05-10"},
            accountant_headers,
        )
        validate_error(resp, ApiErrorId.ERR_PERIOD_CLOSED, 409)

    def test_cost_entry_into_open_period_accepted(self, api, accountant_headers, controller_headers):
        """PRD §3.6: "Recording a cost against an input-cost obligation takes an
        `amount_cents` greater than zero, an `incurred_date` that must fall in
        an `OPEN` or `REOPENED` period" and "The cost is added to
        `costs_incurred_to_date_cents`".

        Design: Corner/validations/cost_entry_into_closed_period_rejected
        """
        may = create_period(period_code="2026-05", start_date="2026-05-01", end_date="2026-06-01")
        create_period(period_code="2026-06", start_date="2026-06-01", end_date="2026-07-01")
        validate_success(api.close_accounting_period(may["id"], controller_headers))
        set_clock(CLOCK)
        setup = setup_active_contract_with_pob(
            product_code="ICA", with_period=False, clock=None,
            pob_overrides={"recognition_pattern": "OVER_TIME_INPUT_COST",
                           "estimated_total_cost_cents": 40000},
        )
        entry = validate_success(api.create_cost_entry(
            setup["pob"]["id"], {"amount_cents": 5000, "incurred_date": "2026-06-10"},
            accountant_headers,
        ), 201)
        assert entry["amount_cents"] == 5000
        assert get_pob(setup["pob"]["id"])["costs_incurred_to_date_cents"] == 5000

    def test_recognize_into_closed_period_rejected(self, api, accountant_headers, controller_headers):
        """PRD §3.6: "Every posting must land in a period that is `OPEN` or
        `REOPENED`; a posting date that falls in a `CLOSED` period — or in no
        defined period at all — is rejected with `ERR_PERIOD_CLOSED`."

        Design: Difficulty/cross_entity_state_dependency/dependency_recognition_requires_open_period
        """
        setup = setup_active_contract_with_pob(
            product_code="SVC",
            pob_overrides={"recognition_pattern": "OVER_TIME_STRAIGHT_LINE",
                           "service_start_date": "2026-06-01",
                           "service_end_date": "2026-07-01"},
        )
        pob, period = setup["pob"], setup["period"]
        validate_success(api.recognize_pob(pob["id"], accountant_headers))
        assert get_pob(pob["id"])["recognized_revenue_cents"] == 46667
        # Advance the clock (target would move to round(100000*19/30) = 63333)
        # but close the June period first so no posting may land there.
        set_clock("2026-06-20T00:00:00Z")
        validate_success(api.close_accounting_period(period["id"], controller_headers))
        resp = api.recognize_pob(pob["id"], accountant_headers)
        validate_error(resp, ApiErrorId.ERR_PERIOD_CLOSED, 409)

    def test_rejected_recognize_posts_nothing(self, api, accountant_headers, controller_headers):
        """PRD §3.6: "a posting date that falls in a `CLOSED` period — or in no
        defined period at all — is rejected with `ERR_PERIOD_CLOSED`."

        Design: Difficulty/cross_entity_state_dependency/dependency_recognition_requires_open_period
        """
        setup = setup_active_contract_with_pob(
            product_code="SVC",
            pob_overrides={"recognition_pattern": "OVER_TIME_STRAIGHT_LINE",
                           "service_start_date": "2026-06-01",
                           "service_end_date": "2026-07-01"},
        )
        pob, period = setup["pob"], setup["period"]
        validate_success(api.recognize_pob(pob["id"], accountant_headers))
        set_clock("2026-06-20T00:00:00Z")
        validate_success(api.close_accounting_period(period["id"], controller_headers))
        validate_error(api.recognize_pob(pob["id"], accountant_headers),
                       ApiErrorId.ERR_PERIOD_CLOSED, 409)
        assert get_pob(pob["id"])["recognized_revenue_cents"] == 46667
        entries = validate_paginated(
            api.list_revenue_entries(accountant_headers, params={"pob_id": pob["id"]})
        )[0]
        assert len(entries) == 1, "no entry may be posted into the closed period"


class TestDisclosureAssembly:
    def _setup_two_contracts(self, api, accountant_headers):
        set_clock(CLOCK)
        period = create_period()
        create_ssp("SVC", region="US", ssp_cents=100000)
        create_ssp("WIDGET", region="EU", ssp_cents=200000)
        customer = create_customer(legal_name="Disc Co", external_ref="DISC-1")
        from test_helpers.fixtures import walk_contract_to_active
        c_a = create_contract(customer["id"], contract_ref="C-DA")
        pob_a = add_pob(c_a["id"], pob_ref="PA", product_code="SVC", region="US",
                        recognition_pattern="OVER_TIME_STRAIGHT_LINE",
                        service_start_date="2026-06-01", service_end_date="2026-07-01")
        walk_contract_to_active(c_a["id"])
        c_b = create_contract(customer["id"], contract_ref="C-DB", fixed_consideration_cents=200000)
        pob_b = add_pob(c_b["id"], pob_ref="PB", product_code="WIDGET", region="EU",
                        recognition_pattern="OVER_TIME_INPUT_COST",
                        estimated_total_cost_cents=100000)
        walk_contract_to_active(c_b["id"])
        validate_success(api.recognize_pob(pob_a["id"], accountant_headers))
        validate_success(api.create_cost_entry(
            pob_b["id"], {"amount_cents": 50000, "incurred_date": "2026-06-10"},
            accountant_headers,
        ), 201)
        validate_success(api.create_invoice(
            c_a["id"], create_invoice_payload(invoice_ref="INV-A", amount_cents=80000),
            accountant_headers,
        ), 201)
        return period, c_a, pob_a, c_b, pob_b

    def test_assembly_computes_period_figures(self, api, accountant_headers):
        """PRD §3.9: "The entry set is every revenue entry with status `POSTED`
        or `LOCKED` whose `posting_date` falls inside the period's half-open
        window. The `period_revenue_cents` is the signed sum of that set;
        `revenue_by_region` maps each region to the sum over the same set of
        amounts whose obligations carry that `region`, and `revenue_by_product`
        does the same by `product_code`."

        Design: Corner/calculations/disclosure_pack_assembly_aggregates
        """
        period, _, _, _, _ = self._setup_two_contracts(api, accountant_headers)
        pack = _create_pack(api, period["id"], accountant_headers)
        assembled = validate_success(api.assemble_disclosure_pack(pack["id"], accountant_headers))
        assert assembled["status"] == "ASSEMBLED"
        assert assembled["period_revenue_cents"] == 146667
        assert assembled["revenue_by_region"] == {"US": 46667, "EU": 100000}
        assert assembled["revenue_by_product"] == {"SVC": 46667, "WIDGET": 100000}

    def test_assembly_computes_rpo_and_position_totals(self, api, accountant_headers):
        """PRD §3.9: "The remaining-performance-obligation figure `rpo_cents`
        sums, over obligations in `PENDING` or `IN_PROGRESS` whose contracts are
        `ACTIVE` or `ON_HOLD`, each obligation's `allocated_amount_cents` minus
        its `recognized_revenue_cents`. The `contract_asset_total_cents` and
        `deferred_revenue_total_cents` sum the per-contract
        `contract_asset_balance_cents` and `deferred_revenue_balance_cents` over
        contracts in `ACTIVE`, `ON_HOLD`, or `COMPLETED` at assembly time."

        Design: Corner/calculations/disclosure_pack_assembly_aggregates
        """
        period, _, _, _, _ = self._setup_two_contracts(api, accountant_headers)
        pack = _create_pack(api, period["id"], accountant_headers)
        assembled = validate_success(api.assemble_disclosure_pack(pack["id"], accountant_headers))
        # (100000-46667) + (200000-100000) = 153333.
        assert assembled["rpo_cents"] == 153333
        # Contract B asset 100000; contract A deferred 80000-46667 = 33333.
        assert assembled["contract_asset_total_cents"] == 100000
        assert assembled["deferred_revenue_total_cents"] == 33333

    def test_pack_figures_null_until_assembled(self, api, accountant_headers):
        """PRD §3.9: "its six figures — `rpo_cents`, `period_revenue_cents`,
        `revenue_by_region`, `revenue_by_product`, `contract_asset_total_cents`,
        and `deferred_revenue_total_cents` — stay null until assembly."

        Design: Corner/calculations/disclosure_pack_assembly_aggregates
        """
        period = create_period()
        pack = _create_pack(api, period["id"], accountant_headers)
        assert_disclosure_pack(pack)
        assert pack["status"] == "DRAFT"
        for field in ("rpo_cents", "period_revenue_cents", "revenue_by_region",
                      "revenue_by_product", "contract_asset_total_cents",
                      "deferred_revenue_total_cents"):
            assert pack.get(field) is None, f"{field} must be null before assembly"


class TestDisclosureFinalization:
    def test_finalize_before_period_close_rejected(self, api, accountant_headers, controller_headers):
        """PRD §3.9: "the pack's accounting period must be `CLOSED` — failing
        with `ERR_PACK_PERIOD_NOT_CLOSED` (HTTP 409) while the period is
        anything else".

        Design: Corner/errors/pack_finalize_before_period_close_rejected
        """
        set_clock(CLOCK)
        period = create_period()
        pack = _create_pack(api, period["id"], accountant_headers)
        validate_success(api.assemble_disclosure_pack(pack["id"], accountant_headers))
        resp = api.finalize_disclosure_pack(pack["id"], controller_headers)
        validate_error(resp, ApiErrorId.ERR_PACK_PERIOD_NOT_CLOSED, 409)

    def test_pack_stays_assembled_after_rejected_finalize(self, api, accountant_headers, controller_headers):
        """PRD §3.9: "the pack's accounting period must be `CLOSED` — failing
        with `ERR_PACK_PERIOD_NOT_CLOSED` (HTTP 409) while the period is
        anything else".

        Design: Corner/errors/pack_finalize_before_period_close_rejected
        """
        set_clock(CLOCK)
        period = create_period()
        pack = _create_pack(api, period["id"], accountant_headers)
        validate_success(api.assemble_disclosure_pack(pack["id"], accountant_headers))
        validate_error(api.finalize_disclosure_pack(pack["id"], controller_headers),
                       ApiErrorId.ERR_PACK_PERIOD_NOT_CLOSED, 409)
        packs = validate_paginated(
            api.list_disclosure_packs(period["id"], accountant_headers))[0]
        assert packs[0]["status"] == "ASSEMBLED"

    def test_finalize_by_assembler_returns_sod_violation(self, api):
        """PRD §3.9: "the finalizer's `X-User-ID` must differ from
        `assembled_by_user_id`, the segregation-of-duties rule of §2.10, failing
        with `ERR_SOD_VIOLATION`."

        Design: Corner/errors/pack_finalize_by_assembler_returns_sod_violation
        """
        set_clock(CLOCK)
        shared_acct = make_accountant_headers("shared-user")
        period = create_period()
        pack = _create_pack(api, period["id"], shared_acct)
        validate_success(api.assemble_disclosure_pack(pack["id"], shared_acct))
        validate_success(api.close_accounting_period(period["id"], make_controller_headers("ctrl-1")))
        resp = api.finalize_disclosure_pack(pack["id"], make_controller_headers("shared-user"))
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION, 409)

    def test_pack_stays_assembled_after_sod_rejection(self, api):
        """PRD §2.10: "A disclosure pack may not be finalized by the operator
        who assembled it — the finalizer's `X-User-ID` must differ from the
        pack's `assembled_by_user_id`."

        Design: Corner/errors/pack_finalize_by_assembler_returns_sod_violation
        """
        set_clock(CLOCK)
        shared_acct = make_accountant_headers("shared-user")
        period = create_period()
        pack = _create_pack(api, period["id"], shared_acct)
        validate_success(api.assemble_disclosure_pack(pack["id"], shared_acct))
        validate_success(api.close_accounting_period(period["id"], make_controller_headers("ctrl-1")))
        validate_error(api.finalize_disclosure_pack(pack["id"], make_controller_headers("shared-user")),
                       ApiErrorId.ERR_SOD_VIOLATION, 409)
        packs = validate_paginated(api.list_disclosure_packs(period["id"], shared_acct))[0]
        assert packs[0]["status"] == "ASSEMBLED"

    def test_finalize_success_records_finalizer(self, api, accountant_headers, controller_headers):
        """PRD §3.9: "Finalization, by a `Controller`, moves an `ASSEMBLED` pack
        to `FINALIZED` under two guards: the pack's accounting period must be
        `CLOSED` — failing with `ERR_PACK_PERIOD_NOT_CLOSED` (HTTP 409) while
        the period is anything else — and the finalizer's `X-User-ID` must
        differ from `assembled_by_user_id`, the segregation-of-duties rule of
        §2.10, failing with `ERR_SOD_VIOLATION`. Finalization records
        `finalized_by_user_id`."

        Design: Difficulty/transitive_cascade/cascade_period_reopen_supersedes_pack
        """
        set_clock(CLOCK)
        period = create_period()
        pack = _create_pack(api, period["id"], accountant_headers)
        validate_success(api.assemble_disclosure_pack(pack["id"], accountant_headers))
        validate_success(api.close_accounting_period(period["id"], controller_headers))
        finalized = validate_success(api.finalize_disclosure_pack(pack["id"], controller_headers))
        assert finalized["status"] == "FINALIZED"
        assert finalized["finalized_by_user_id"] == "ctrl-1"
        assert finalized["assembled_by_user_id"] == "acct-1"


class TestReopenCascade:
    def _setup_finalized_pack(self, api, accountant_headers, controller_headers):
        set_clock(CLOCK)
        period = create_period()
        pack = _create_pack(api, period["id"], accountant_headers)
        validate_success(api.assemble_disclosure_pack(pack["id"], accountant_headers))
        validate_success(api.close_accounting_period(period["id"], controller_headers))
        validate_success(api.finalize_disclosure_pack(pack["id"], controller_headers))
        return period, pack

    def test_reopen_supersedes_finalized_pack(self, api, accountant_headers, controller_headers):
        """PRD §3.9: "Reopening sets `reopened_once` to true and cascades into
        disclosures: every `FINALIZED` disclosure pack of the period becomes
        `SUPERSEDED`".

        Design: Difficulty/transitive_cascade/cascade_period_reopen_supersedes_pack
        """
        period, pack = self._setup_finalized_pack(api, accountant_headers, controller_headers)
        reopened = validate_success(api.reopen_accounting_period(period["id"], controller_headers))
        assert reopened["status"] == "REOPENED"
        assert reopened["reopened_once"] is True
        packs = validate_paginated(api.list_disclosure_packs(period["id"], controller_headers))[0]
        original = next(p for p in packs if p["id"] == pack["id"])
        assert original["status"] == "SUPERSEDED"

    def test_reopen_autocreates_replacement_draft(self, api, accountant_headers, controller_headers):
        """PRD §3.9: "for each pack superseded this way the system auto-creates
        one replacement pack for the same period, starting in `DRAFT`."

        Design: Difficulty/transitive_cascade/cascade_period_reopen_supersedes_pack
        """
        period, pack = self._setup_finalized_pack(api, accountant_headers, controller_headers)
        validate_success(api.reopen_accounting_period(period["id"], controller_headers))
        packs = validate_paginated(api.list_disclosure_packs(period["id"], controller_headers))[0]
        assert len(packs) == 2, "supersession must auto-create a replacement DRAFT pack"
        drafts = [p for p in packs if p["status"] == "DRAFT" and p["id"] != pack["id"]]
        assert len(drafts) == 1
        assert drafts[0]["accounting_period_id"] == period["id"]


class TestRollforward:
    def _setup(self, api, accountant_headers):
        setup = setup_active_contract_with_pob(
            product_code="SVC",
            pob_overrides={"recognition_pattern": "OVER_TIME_STRAIGHT_LINE",
                           "service_start_date": "2026-06-01",
                           "service_end_date": "2026-07-01"},
        )
        validate_success(api.recognize_pob(setup["pob"]["id"], accountant_headers))
        validate_success(api.create_invoice(
            setup["contract"]["id"],
            create_invoice_payload(invoice_ref="INV-RF", amount_cents=80000),
            accountant_headers,
        ), 201)
        return setup

    def test_rollforward_period_movements(self, api, accountant_headers):
        """PRD §3.7: "Movements are attributed by effective date: an invoice
        contributes its amount positively in the period containing its
        `invoice_date`; a void contributes the amount negatively in the period
        containing the void's clock date; each revenue entry contributes its
        signed amount in the period containing its `posting_date`."

        Design: Corner/calculations/rollforward_read_reconciles_movements
        """
        setup = self._setup(api, accountant_headers)
        data = validate_success(api.get_rollforward(
            setup["contract"]["id"], accountant_headers,
            params={"accounting_period_id": setup["period"]["id"]},
        ))
        assert data["contract_id"] == setup["contract"]["id"]
        assert data["accounting_period_id"] == setup["period"]["id"]
        assert data["billed_cents"] == 80000
        assert data["recognized_cents"] == 46667
        assert data["catch_up_cents"] == 0
        assert data["reversal_cents"] == 0

    def test_rollforward_beginning_and_ending_balances(self, api, accountant_headers):
        """PRD §3.7: "The response carries `contract_id` and
        `accounting_period_id`; the beginning balances `beginning_billed_cents`
        and `beginning_recognized_cents`, which accumulate every movement whose
        effective date precedes the period's `start_date`; the period's own
        movements `billed_cents` and `recognized_cents`; the portions of the
        period's recognized movement contributed by catch-up adjustments and
        reversals as `catch_up_cents` and `reversal_cents`; and the ending
        figures `ending_billed_cents`, `ending_recognized_cents`,
        `ending_deferred_revenue_cents`, and `ending_contract_asset_cents`. The
        ending balances combine the beginning balances with the period's
        movements, and the ending deferred-revenue and contract-asset figures
        derive from the ending billed and recognized totals under the same
        floored-difference formulas of §2.11."

        Design: Corner/calculations/rollforward_read_reconciles_movements
        """
        setup = self._setup(api, accountant_headers)
        data = validate_success(api.get_rollforward(
            setup["contract"]["id"], accountant_headers,
            params={"accounting_period_id": setup["period"]["id"]},
        ))
        assert data["beginning_billed_cents"] == 0
        assert data["beginning_recognized_cents"] == 0
        assert data["ending_billed_cents"] == 80000
        assert data["ending_recognized_cents"] == 46667
        assert data["ending_deferred_revenue_cents"] == 33333
        assert data["ending_contract_asset_cents"] == 0
