"""Due diligence and retrade defense: the contest loop, per-item and aggregate
caps, the filing deadline boundary, the accept cascade, and rescind parity."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_timestamp_prefix,
    create_approved_statement,
    create_dd_item_payload,
    file_dd_item,
    pipeline_to_dd_active,
    set_clock,
    validate_error,
    validate_success,
)

DM = TEST_USERS["dm_headers"]


def _dd_pipeline():
    """Alpha pipeline to DD_ACTIVE at price 5,000,000,000 (executed at logical
    clock 2026-09-16, dd_period 30 days -> dd_deadline 2026-10-16)."""
    return pipeline_to_dd_active()


class TestContestCycle:
    def test_dd_item_contested_reopen_cycle_statuses(self, api):
        """PRD: "The buyer may supplement a `CONTESTED` item, returning it to
        `OPEN`"
        PRD: "The contest loop may cycle repeatedly until the window closes."

        Design: Difficulty/non_linear_state_machine/dd_item_contested_reopen_cycle
        """
        ws = _dd_pipeline()
        headers = ws["buyer_headers"]
        item = file_dd_item(ws["psa"]["id"], 80_000_000, headers,
                            category="ENVIRONMENTAL", description="soil")

        contested = validate_success(
            api.respond_dd_item(item["id"], "CONTEST", DM))
        assert contested["status"] == "CONTESTED"
        reopened = validate_success(
            api.supplement_dd_item(item["id"], headers,
                                   requested_reduction_cents=70_000_000))
        assert reopened["status"] == "OPEN"
        assert reopened["requested_reduction_cents"] == 70_000_000, \
            "a supplied requested_reduction_cents replaces the prior demand"

        contested2 = validate_success(
            api.respond_dd_item(item["id"], "CONTEST", DM))
        assert contested2["status"] == "CONTESTED"
        reopened2 = validate_success(api.supplement_dd_item(item["id"], headers))
        assert reopened2["status"] == "OPEN"
        assert reopened2["requested_reduction_cents"] == 70_000_000, \
            "an omitted requested_reduction_cents leaves the demand unchanged"

    def test_dd_item_contested_cycle_final_accept_once(self, api):
        """PRD: "On acceptance, the conceded amount `accepted_reduction_cents`
        is the smaller of the item's `requested_reduction_cents` and the
        per-item cap — two hundred basis points of the agreement's current
        `price_cents`, rounded half up."
        PRD: "A successful acceptance subtracts the concession from
        `price_cents`, adds it to `accepted_retrade_total_cents`"

        Design: Difficulty/non_linear_state_machine/dd_item_contested_reopen_cycle
        """
        ws = _dd_pipeline()
        headers = ws["buyer_headers"]
        item = file_dd_item(ws["psa"]["id"], 80_000_000, headers,
                            category="ENVIRONMENTAL", description="soil")
        api.respond_dd_item(item["id"], "CONTEST", DM)
        api.supplement_dd_item(item["id"], headers,
                               requested_reduction_cents=70_000_000)
        api.respond_dd_item(item["id"], "CONTEST", DM)
        api.supplement_dd_item(item["id"], headers)

        accepted = validate_success(api.respond_dd_item(item["id"], "ACCEPT", DM))
        assert accepted["status"] == "ACCEPTED"
        # Per-item cap is 2% of the current 5,000,000,000 price = 100,000,000;
        # the supplemented 70,000,000 demand is below it.
        assert accepted["accepted_reduction_cents"] == 70_000_000

        psa = validate_success(api.get_psa(ws["psa"]["id"], DM))
        assert psa["price_cents"] == 4_930_000_000, \
            "the reduction is applied exactly once despite the loop"
        assert psa["accepted_retrade_total_cents"] == 70_000_000


class TestAggregateCap:
    def test_retrade_aggregate_cap_exact_boundary(self, api):
        """PRD: "Then the aggregate cap is checked: the new
        `accepted_retrade_total_cents` plus this concession must not exceed five
        hundred basis points of `original_price_cents`, rounded half up. If it
        would, the entire acceptance is rejected with
        `ERR_RETRADE_CAP_EXCEEDED` (HTTP 422) — no partial application, and the
        item stays `OPEN`."
        PRD: "On acceptance, the conceded amount `accepted_reduction_cents` is
        the smaller of the item's `requested_reduction_cents` and the per-item
        cap — two hundred basis points of the agreement's current `price_cents`,
        rounded half up."

        Design: Corner/calculations/retrade_aggregate_cap_exact_boundary
        """
        ws = _dd_pipeline()
        headers = ws["buyer_headers"]
        i1 = file_dd_item(ws["psa"]["id"], 100_000_000, headers,
                          category="PHYSICAL", description="i1")
        i2 = file_dd_item(ws["psa"]["id"], 150_000_000, headers,
                          category="FINANCIAL", description="i2")
        i3 = file_dd_item(ws["psa"]["id"], 52_000_000, headers,
                          category="LEGAL", description="i3")
        i4 = file_dd_item(ws["psa"]["id"], 1_000_000, headers,
                          category="TITLE", description="i4")

        a1 = validate_success(api.respond_dd_item(i1["id"], "ACCEPT", DM))
        assert a1["accepted_reduction_cents"] == 100_000_000, \
            "per-item cap (2% of 5,000,000,000) hit exactly"
        a2 = validate_success(api.respond_dd_item(i2["id"], "ACCEPT", DM))
        assert a2["accepted_reduction_cents"] == 98_000_000, \
            "request clipped to 2% of the reduced price 4,900,000,000"
        a3 = validate_success(api.respond_dd_item(i3["id"], "ACCEPT", DM))
        assert a3["accepted_reduction_cents"] == 52_000_000, \
            "aggregate lands exactly on 5% of the original price (inclusive)"

        psa = validate_success(api.get_psa(ws["psa"]["id"], DM))
        assert psa["accepted_retrade_total_cents"] == 250_000_000
        assert psa["price_cents"] == 4_750_000_000

        # The next accept would exceed the aggregate cap: whole accept rejected.
        validate_error(api.respond_dd_item(i4["id"], "ACCEPT", DM),
                       ApiErrorId.ERR_RETRADE_CAP_EXCEEDED)
        items = validate_success(api.list_psa_dd_items(ws["psa"]["id"], DM))
        assert items[3]["id"] == i4["id"]
        assert items[3]["status"] == "OPEN"
        after = validate_success(api.get_psa(ws["psa"]["id"], DM))
        assert after["price_cents"] == 4_750_000_000, "no partial application"


class TestFilingDeadline:
    def test_retrade_window_filing_at_exact_deadline(self, api):
        """PRD: "Filing requires the agreement to be `DD_ACTIVE` and the clock
        to be at or before `dd_deadline`; a filing after the deadline is
        rejected with `ERR_RETRADE_WINDOW_CLOSED` (HTTP 409)."
        PRD: "Execution stamps `executed_at` from the clock, computes
        `dd_deadline` as `executed_at` plus the winning bid's `dd_period_days`
        days"

        Design: Difficulty/boundary_precision_check/retrade_window_exact_deadline
        """
        ws = _dd_pipeline()
        psa = validate_success(api.get_psa(ws["psa"]["id"], DM))
        assert_timestamp_prefix(psa["dd_deadline"], "2026-10-16T00:00:00")

        set_clock("2026-10-16T00:00:00Z")
        item = file_dd_item(ws["psa"]["id"], 1_000_000, ws["buyer_headers"],
                            category="TITLE", description="at exact deadline")
        assert item["status"] == "OPEN", "filing at exactly dd_deadline is allowed"

    def test_retrade_window_one_second_late_rejected(self, api):
        """PRD: "a filing after the deadline is rejected with
        `ERR_RETRADE_WINDOW_CLOSED` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/retrade_window_exact_deadline
        """
        ws = _dd_pipeline()
        set_clock("2026-10-16T00:00:01Z")
        resp = api.create_dd_item(
            create_dd_item_payload(ws["psa"]["id"], 1_000_000, category="TITLE",
                                   description="one second late"),
            ws["buyer_headers"])
        validate_error(resp, ApiErrorId.ERR_RETRADE_WINDOW_CLOSED)
        psa = validate_success(api.get_psa(ws["psa"]["id"], DM))
        assert psa["status"] == "DD_ACTIVE", \
            "the temporal rule fires while the agreement is still DD_ACTIVE"


class TestAcceptCascade:
    def test_retrade_accept_cascade_price_and_commission(self, api):
        """PRD: "A successful acceptance subtracts the concession from
        `price_cents`, adds it to `accepted_retrade_total_cents`, and then
        cascades outward: the engagement's `commission_provisional_cents` is
        recomputed on the reduced price"
        PRD: "`commission_provisional_cents` is computed on the agreement's
        price at execution, remains null until a purchase agreement is
        executed, and is recomputed on every accepted or rescinded retrade so
        it always tracks the live price."

        Design: Difficulty/transitive_cascade/retrade_acceptance_cascade_depth3
        """
        ws = _dd_pipeline()
        engagements = validate_success(
            api.list_asset_engagements(ws["asset"]["id"], DM))
        assert engagements[0]["commission_provisional_cents"] == 72_500_000, \
            "tiered commission on the 5,000,000,000 execution price"

        item = file_dd_item(ws["psa"]["id"], 60_000_000, ws["buyer_headers"],
                            category="PHYSICAL", description="roof")
        accepted = validate_success(api.respond_dd_item(item["id"], "ACCEPT", DM))
        assert accepted["accepted_reduction_cents"] == 60_000_000

        psa = validate_success(api.get_psa(ws["psa"]["id"], DM))
        assert psa["price_cents"] == 4_940_000_000
        assert psa["accepted_retrade_total_cents"] == 60_000_000

        after = validate_success(
            api.list_asset_engagements(ws["asset"]["id"], DM))
        assert after[0]["commission_provisional_cents"] == 71_900_000, \
            "recomputed on the reduced price (30,000,000 + 22,500,000 + 19,400,000)"

    def test_retrade_accept_cascade_statement_stale(self, api):
        """PRD: "any closing statement of this agreement sitting in
        `PENDING_REVIEW` or `APPROVED` flips to `STALE`"
        PRD: "When any of those inputs changes underneath a statement that is
        `PENDING_REVIEW` or `APPROVED` — because a retrade was accepted or
        rescinded on the agreement, or because a payoff quote was confirmed —
        the statement is automatically flipped to `STALE`."

        Design: Difficulty/transitive_cascade/retrade_acceptance_cascade_depth3
        """
        ws = _dd_pipeline()
        statement = create_approved_statement(ws["psa"]["id"])
        assert statement["status"] == "APPROVED"
        assert statement["commission_cents"] == 72_500_000
        assert statement["holdback_cents"] == 25_000_000

        item = file_dd_item(ws["psa"]["id"], 60_000_000, ws["buyer_headers"],
                            category="PHYSICAL", description="roof")
        validate_success(api.respond_dd_item(item["id"], "ACCEPT", DM))

        statements = validate_success(
            api.list_psa_statements(ws["psa"]["id"], DM))
        assert statements[0]["status"] == "STALE", \
            "the price change under an APPROVED statement flips it to STALE"


class TestRescindParity:
    def test_retrade_accept_rescind_price_restored(self, api):
        """PRD: "a `DispositionManager` may rescind an `ACCEPTED` item while the
        agreement is `DD_ACTIVE`, moving it to `RESCINDED`: the exact concession
        is added back to `price_cents` and subtracted from
        `accepted_retrade_total_cents` with no drift"

        Design: Difficulty/compensating_invariant/retrade_accept_rescind_no_drift
        """
        ws = _dd_pipeline()
        item = file_dd_item(ws["psa"]["id"], 60_000_000, ws["buyer_headers"],
                            category="PHYSICAL", description="roof")
        validate_success(api.respond_dd_item(item["id"], "ACCEPT", DM))
        rescinded = validate_success(api.rescind_dd_item(item["id"], DM))
        assert rescinded["status"] == "RESCINDED"

        psa = validate_success(api.get_psa(ws["psa"]["id"], DM))
        assert psa["price_cents"] == 5_000_000_000, "exactly restored"
        assert psa["accepted_retrade_total_cents"] == 0

    def test_retrade_accept_rescind_commission_restored(self, api):
        """PRD: "the provisional commission is recomputed on the restored price"
        PRD: "`commission_provisional_cents` is computed on the agreement's
        price at execution, remains null until a purchase agreement is
        executed, and is recomputed on every accepted or rescinded retrade so
        it always tracks the live price."

        Design: Difficulty/compensating_invariant/retrade_accept_rescind_no_drift
        """
        ws = _dd_pipeline()
        item = file_dd_item(ws["psa"]["id"], 60_000_000, ws["buyer_headers"],
                            category="PHYSICAL", description="roof")
        validate_success(api.respond_dd_item(item["id"], "ACCEPT", DM))
        validate_success(api.rescind_dd_item(item["id"], DM))

        engagements = validate_success(
            api.list_asset_engagements(ws["asset"]["id"], DM))
        assert engagements[0]["commission_provisional_cents"] == 72_500_000, \
            "recomputed on the restored price with no drift"


class TestImmediateConsistency:
    def test_immediate_consistency_after_retrade_accept(self, api):
        """PRD: "every cascade triggered by a single call is applied atomically
        within that request."
        PRD: "A successful acceptance subtracts the concession from
        `price_cents`, adds it to `accepted_retrade_total_cents`, and then
        cascades outward: the engagement's `commission_provisional_cents` is
        recomputed on the reduced price"

        Design: Corner/consistency_model/immediate_consistency_after_retrade_accept
        """
        ws = _dd_pipeline()
        item = file_dd_item(ws["psa"]["id"], 60_000_000, ws["buyer_headers"],
                            category="PHYSICAL", description="roof")
        validate_success(api.respond_dd_item(item["id"], "ACCEPT", DM))

        # Reads issued immediately after the responding call already observe
        # the cascade; no recompute or read-repair call intervenes.
        psa = validate_success(api.get_psa(ws["psa"]["id"], DM))
        assert psa["price_cents"] == 4_940_000_000
        engagements = validate_success(
            api.list_asset_engagements(ws["asset"]["id"], DM))
        assert engagements[0]["commission_provisional_cents"] == 71_900_000
