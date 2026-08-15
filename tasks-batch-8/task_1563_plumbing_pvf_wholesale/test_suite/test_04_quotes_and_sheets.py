"""Quotes, revision chains, and showroom selection sheets (PRD §3.4, §3.5)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_approved_sheet,
    create_awarded_quote,
    create_presented_sheet,
    create_quoted,
    create_sheet_payload,
    make_account,
    make_branch,
    make_contractor_headers,
    make_product,
    revise_quote,
    set_clock,
    setup_branch_product_account,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)

TEST_SALES = TEST_USERS["sales_headers"]


def _quote_world():
    """Branch + P1 + GOLD account. Returns (branch, product, account)."""
    return setup_branch_product_account()


P1_LINE = lambda product_id, qty=1, price=9000: {  # noqa: E731
    "product_id": product_id, "qty": qty, "unit_price_cents": price,
}


class TestQuoteLifecycle:
    def test_quote_initial_state_draft(self, api):
        """PRD §3.4: "A new quote starts in `DRAFT` with `revision_no` 1, a null
        `supersedes_quote_id`, and null `awarded_at`, and its document totals
        (§3.6) are computed over its lines at creation."

        Design: Corner/state_machines/quote_initial_state_draft
        """
        branch, product, account = _quote_world()
        quote = create_quoted(account["id"], branch["id"], [P1_LINE(product["id"])])
        assert quote["status"] == "DRAFT"
        assert quote["revision_no"] == 1
        assert quote["supersedes_quote_id"] is None
        assert quote["awarded_at"] is None

    def test_award_draft_quote_rejected(self, api, sales_headers):
        """PRD §3.4: "The contractor awards it (`SUBMITTED` to `AWARDED`)" — the
        transition is defined only from `SUBMITTED`.
        PRD §2.7: "State-machine gating — the target entity's current status
        permits the requested transition; otherwise `ERR_INVALID_STATE`."

        Design: Corner/state_machines/award_draft_quote_rejected
        """
        branch, product, account = _quote_world()
        quote = create_quoted(account["id"], branch["id"], [P1_LINE(product["id"])])
        res = api.award_quote(quote["id"], make_contractor_headers(account["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_quote(quote["id"], sales_headers))
        assert after["status"] == "DRAFT"

    def test_quote_expires_via_clock_sweep(self, api, sales_headers):
        """PRD §3.4: "Or time does the work: when the clock advances past
        `valid_until`, the quote auto-transitions from `SUBMITTED` to `EXPIRED`
        (§2.5)."
        PRD §3.4: "awarding also requires freshness, and an award attempted at or
        after `valid_until` is rejected with `ERR_QUOTE_EXPIRED` and the quote
        falls to `EXPIRED` in the same stroke."

        After the sweep the quote reads EXPIRED. A later award is rejected; per
        the PRD's validation pipeline the already-EXPIRED quote may surface
        either the freshness error or the state error, so both are accepted.

        Design: Corner/state_machines/quote_expires_via_clock_sweep
        """
        branch, product, account = _quote_world()
        quote = create_quoted(
            account["id"], branch["id"], [P1_LINE(product["id"])],
            valid_until="2026-08-10T00:00:00Z",
        )
        validate_success(api.submit_quote(quote["id"], TEST_SALES))
        set_clock("2026-08-11T00:00:00Z")

        after = validate_success(api.get_quote(quote["id"], sales_headers))
        assert after["status"] == "EXPIRED", (
            f"clock past valid_until must flip SUBMITTED to EXPIRED, got {after['status']}"
        )

        res = api.award_quote(quote["id"], make_contractor_headers(account["id"]))
        validate_error_is_one_of(
            res, [ApiErrorId.ERR_QUOTE_EXPIRED.value, ApiErrorId.ERR_INVALID_STATE.value]
        )

    def test_lost_quote_cannot_convert(self, api, sales_headers):
        """PRD §3.4: "Alternatively, `InsideSales` marks the bid lost
        (`SUBMITTED` to `LOST`)."
        PRD §3.4: "The new revision may itself be submitted and awarded, so the
        chain forms an award → revise → submit → award loop across successive
        rows, with `REVISED`, `LOST`, `EXPIRED`, and `CONVERTED` all terminal."
        Conversion is defined only for `AWARDED` quotes: "Converting an `AWARDED`
        quote — again `InsideSales` — moves the quote to terminal `CONVERTED`".

        Design: Corner/state_machines/lost_quote_cannot_convert
        """
        branch, product, account = _quote_world()
        quote = create_quoted(account["id"], branch["id"], [P1_LINE(product["id"])])
        validate_success(api.submit_quote(quote["id"], sales_headers))
        validate_success(api.lose_quote(quote["id"], sales_headers))
        res = api.convert_quote(quote["id"], sales_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)


class TestQuoteRevisionCycle:
    def _awarded(self):
        branch, product, account = _quote_world()
        quote = create_awarded_quote(
            account["id"], branch["id"], [P1_LINE(product["id"], qty=2)],
            job_name="JOB-C", valid_until="2026-09-01T00:00:00Z",
        )
        return branch, product, account, quote

    def test_revision_supersedes_awarded_quote(self, api, sales_headers):
        """PRD §3.4: "Creating a revision of an `AWARDED` quote — an `InsideSales` action guarded by the optimistic-concurrency rule of §2.8 via `expected_quote_version`, with staleness rejected as `ERR_STALE_QUOTE_VERSION` — lands the existing quote in its terminal `REVISED` state, bumps that quote's `version`, and creates a fresh quote in `DRAFT` whose `revision_no` is the predecessor's plus one and whose `supersedes_quote_id` points back at the predecessor."

        Design: Difficulty/non_linear_state_machine/quote_award_revise_resubmit_cycle
        """
        _, _, _, q1 = self._awarded()
        q2 = revise_quote(q1["id"], q1["version"], valid_until="2026-12-31T00:00:00Z")
        assert q2["status"] == "DRAFT"
        assert q2["revision_no"] == 2, f"revision_no must be predecessor+1, got {q2['revision_no']}"
        assert q2["supersedes_quote_id"] == q1["id"]

        q1_after = validate_success(api.get_quote(q1["id"], sales_headers))
        assert q1_after["status"] == "REVISED", (
            f"the superseded quote must land in terminal REVISED, got {q1_after['status']}"
        )

    def test_revision_can_be_resubmitted_and_reawarded(self, api, sales_headers):
        """PRD §3.4: "The new revision may itself be submitted and awarded, so
        the chain forms an award → revise → submit → award loop across
        successive rows, with `REVISED`, `LOST`, `EXPIRED`, and `CONVERTED` all
        terminal."

        Design: Difficulty/non_linear_state_machine/quote_award_revise_resubmit_cycle
        """
        _, _, account, q1 = self._awarded()
        q2 = revise_quote(q1["id"], q1["version"], valid_until="2026-12-31T00:00:00Z")
        validate_success(api.submit_quote(q2["id"], sales_headers))
        q2_awarded = validate_success(
            api.award_quote(q2["id"], make_contractor_headers(account["id"]))
        )
        assert q2_awarded["status"] == "AWARDED"
        assert q2_awarded["revision_no"] == 2


class TestQuoteRevisionOcc:
    def test_stale_quote_version_rejected_on_revision(self, api, sales_headers):
        """PRD §2.8: "Creating a superseding revision of an awarded quote
        requires `expected_quote_version` matching the quote's current
        `version`. A mismatch is rejected with `ERR_STALE_QUOTE_VERSION`
        (HTTP 412)".

        The award advanced the quote's version, so the pre-award version is
        stale; the current version succeeds (201), proving the rejection is the
        version check and not the state.

        Design: Corner/cross_cutting_layers/occ_stale_quote_revision_rejected
        """
        _, _, _, q1 = TestQuoteRevisionCycle()._awarded()
        res = api.create_quote_revision(
            q1["id"],
            {"expected_quote_version": q1["version"] - 1, "valid_until": "2027-01-31T00:00:00Z"},
            sales_headers,
        )
        validate_error(res, ApiErrorId.ERR_STALE_QUOTE_VERSION)

        ok = api.create_quote_revision(
            q1["id"],
            {"expected_quote_version": q1["version"], "valid_until": "2027-01-31T00:00:00Z"},
            sales_headers,
        )
        q2 = validate_success(ok, 201)
        assert q2["supersedes_quote_id"] == q1["id"]


class TestSelectionSheets:
    def _sheet_world(self):
        branch = make_branch()
        fixture = make_product(
            sku="PF", description="Freestanding tub", category="FIXTURE",
            list_price_cents=70000, cost_cents=40000, manufacturer_name="BathCo",
            cubes_per_unit=30, is_special_order=True,
        )
        account = make_account()
        return branch, fixture, account

    def test_convert_draft_sheet_rejected(self, api, sales_headers):
        """PRD §3.5: "Converting an `APPROVED` sheet moves it to its terminal
        state `ORDERED`" — conversion is defined only from `APPROVED`.
        PRD §2.7: "State-machine gating — the target entity's current status
        permits the requested transition; otherwise `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/sheet_convert_gated_by_sheet_state
        """
        branch, fixture, account = self._sheet_world()
        sheet = validate_success(api.create_sheet(
            create_sheet_payload(account["id"], branch["id"],
                                 [{"product_id": fixture["id"], "finish": "chrome", "qty": 1}]),
            sales_headers,
        ), 201)
        res = api.convert_sheet(sheet["id"], sales_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    def test_approved_sheet_converts_to_showroom_order(self, api, sales_headers):
        """PRD §3.5: "Converting an `APPROVED` sheet moves it to its terminal
        state `ORDERED` and creates an order in `DRAFT` whose `source` is
        `SHOWROOM`: the order's `sheet_id` points back at the sheet, and each
        selection becomes an order line priced at the product's
        `list_price_cents` with `price_source` `SHOWROOM_LIST` — no contractor
        tier discount and no promotional pricing applies to showroom lines,
        though volume-tier and freight rules still govern the document totals
        (§3.6)."

        A GOLD account still pays list 70000 on the showroom line; total is
        70000 (freight-free at >= 50000 post-discount).

        Design: Difficulty/cross_entity_state_dependency/sheet_convert_gated_by_sheet_state
        """
        branch, fixture, account = self._sheet_world()
        sheet = create_approved_sheet(
            account["id"], branch["id"],
            [{"product_id": fixture["id"], "finish": "chrome", "qty": 1}],
        )
        order = validate_success(api.convert_sheet(sheet["id"], sales_headers), 201)
        assert order["source"] == "SHOWROOM"
        assert order["sheet_id"] == sheet["id"]
        assert order["total_cents"] == 70000, (
            f"SHOWROOM list pricing: 70000 + 0 freight, got {order['total_cents']}"
        )
        lines = validate_success(api.get_order_lines(order["id"], sales_headers))
        rows = lines if isinstance(lines, list) else lines.get("data", [])
        assert len(rows) == 1
        assert rows[0]["unit_price_cents"] == 70000
        assert rows[0]["price_source"] == "SHOWROOM_LIST"

        sheet_after = validate_success(api.get_sheet(sheet["id"], sales_headers))
        assert sheet_after["status"] == "ORDERED"

    def test_sheet_revision_cycle_full_loop(self, api, sales_headers):
        """PRD §3.5: "`InsideSales` may revise an `APPROVED` sheet, which
        replaces `selections` wholesale with the payload's `selections`, clears
        `approved_at` back to null, and returns the sheet to `REVISED` — from
        which it is presented and approved again, an `APPROVED` → `REVISED` →
        `PRESENTED` → `APPROVED` loop."

        Design: Corner/state_machines/sheet_revision_cycle_full_loop
        """
        branch, fixture, account = self._sheet_world()
        faucet = make_product(sku="PF2", description="Faucet", category="FIXTURE",
                              list_price_cents=15000, cost_cents=8000,
                              manufacturer_name="BathCo", cubes_per_unit=5)
        sheet = create_approved_sheet(
            account["id"], branch["id"],
            [{"product_id": fixture["id"], "finish": "chrome", "qty": 1}],
        )
        revised = validate_success(api.revise_sheet(
            sheet["id"],
            {"selections": [{"product_id": faucet["id"], "finish": "nickel", "qty": 2}]},
            sales_headers,
        ))
        assert revised["status"] == "REVISED"
        assert revised["approved_at"] is None, "revise must clear approved_at"
        selections = revised["selections"]
        assert len(selections) == 1 and selections[0]["product_id"] == faucet["id"]

        validate_success(api.present_sheet(sheet["id"], sales_headers))
        reapproved = validate_success(
            api.approve_sheet(sheet["id"], make_contractor_headers(account["id"]))
        )
        assert reapproved["status"] == "APPROVED"
        assert reapproved["approved_at"] is not None, "second approval must re-stamp approved_at"

    def test_contractor_cannot_approve_other_accounts_sheet(self, api, sales_headers):
        """PRD §3.5: "The customer then approves: a `Contractor` whose
        `X-User-ID` equals the sheet's `account_id` moves the sheet from
        `PRESENTED` to `APPROVED` (a foreign contractor is refused with
        `ERR_FORBIDDEN`)".

        Design: Corner/rbac/contractor_cannot_approve_other_accounts_sheet
        """
        branch, fixture, account_a = self._sheet_world()
        account_b = make_account(company_name="B Co")
        sheet = create_presented_sheet(
            account_a["id"], branch["id"],
            [{"product_id": fixture["id"], "finish": "chrome", "qty": 1}],
        )
        res = api.approve_sheet(sheet["id"], make_contractor_headers(account_b["id"]))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)
        after = validate_success(api.get_sheet(sheet["id"], sales_headers))
        assert after["status"] == "PRESENTED"
