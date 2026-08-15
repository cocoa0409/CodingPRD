"""Release workflow guards: state-gated transitions, cancellation rules,
item-on-quote membership, line filtering, and the release-create OCC guard."""
from test_helpers import (
    BRANCH_MGR,
    CREDIT_MGR,
    DISPATCHER,
    SALES_REP,
    WH_MGR,
    ApiErrorId,
    api_client,
    assert_release,
    cancel_release,
    create_awarded_quote,
    create_contractor,
    create_ea_item,
    create_foot_item,
    create_job_account,
    create_release,
    get_release,
    list_release_lines,
    setup_allocated_release,
    setup_partially_allocated_release,
    setup_requested_release,
    validate_error,
    validate_paginated,
    walk_release,
)


def _releases_on_job(job_account_id):
    data, _meta = validate_paginated(api_client.list_releases(SALES_REP))
    return [r for r in data if r["job_account_id"] == job_account_id]


class TestReleaseStateGates:

    def test_allocate_before_credit_approve_rejected(self):
        """PRD section 3.7: "Once credit-approved, a `WarehouseManager`
        allocates the release against physical stock; attempting allocation
        from any other state yields `ERR_RELEASE_NOT_CREDIT_APPROVED`."

        Design: Corner/validations/allocate_before_credit_approve_rejected
        """
        ctx = setup_requested_release()
        resp = api_client.allocate_release(ctx["release"]["id"], WH_MGR)
        validate_error(resp, ApiErrorId.ERR_RELEASE_NOT_CREDIT_APPROVED)
        assert get_release(ctx["release"]["id"])["status"] == "REQUESTED"

    def test_deliver_requires_scheduled_rejected(self):
        """PRD section 3.8: "When the truck returns, the `Dispatcher` confirms
        delivery; a release that is not `SCHEDULED` yields
        `ERR_RELEASE_NOT_SCHEDULED`."

        Design: Corner/state_machines/deliver_requires_scheduled_rejected
        """
        ctx = setup_allocated_release()
        resp = api_client.deliver_release(ctx["release"]["id"], DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_RELEASE_NOT_SCHEDULED)
        assert get_release(ctx["release"]["id"])["status"] == "ALLOCATED"

    def test_invoice_requires_delivered_rejected(self):
        """PRD section 3.8: "Invoicing is a `CreditManager` action on a
        `DELIVERED` release — from any other state,
        `ERR_RELEASE_NOT_DELIVERED`".

        Design: Corner/state_machines/invoice_requires_delivered_rejected
        """
        ctx = setup_allocated_release()
        walk_release(ctx["release"]["id"], "SCHEDULED")
        resp = api_client.invoice_release(ctx["release"]["id"], CREDIT_MGR)
        validate_error(resp, ApiErrorId.ERR_RELEASE_NOT_DELIVERED)
        assert get_release(ctx["release"]["id"])["status"] == "SCHEDULED"


class TestReleaseCancellation:

    def test_cancel_terminal_release_rejected(self):
        """PRD section 3.6: "A release can be cancelled by a `SalesRep` or by
        the owning `Contractor` — the same ownership rule as creation — from
        `REQUESTED`, `CREDIT_APPROVED`, `PARTIALLY_ALLOCATED`, or `ALLOCATED`;
        from any later state the attempt fails with
        `ERR_RELEASE_NOT_CANCELLABLE`."

        Design: Corner/state_machines/cancel_terminal_release_rejected
        """
        ctx = setup_requested_release()
        cancel_release(ctx["release"]["id"])
        resp = api_client.cancel_release(ctx["release"]["id"], SALES_REP)
        validate_error(resp, ApiErrorId.ERR_RELEASE_NOT_CANCELLABLE)
        assert get_release(ctx["release"]["id"])["status"] == "CANCELLED"

    def test_cancel_partial_release_cancels_backorders(self):
        """PRD section 3.6: "From `PARTIALLY_ALLOCATED` or `ALLOCATED`, each
        line returns its `qty_allocated` to the item's `stock_on_hand`, the
        item's `stock_allocated` decreases by the same amount, each line —
        whether still `OPEN` or already `ALLOCATED` — transitions to
        `CANCELLED`, any `OPEN` backorder allocations of the release move to
        `CANCELLED`, and the committed estimate is released as above."

        Design: Corner/state_machines/cancel_partial_release_cancels_backorders
        """
        ctx = setup_partially_allocated_release(stock_qty=100, request_qty=300)
        cancelled = cancel_release(ctx["release"]["id"])
        assert_release(cancelled)
        assert cancelled["status"] == "CANCELLED"

        line = list_release_lines(ctx["release"]["id"])[0]
        assert line["status"] == "CANCELLED", (
            f"line must be CANCELLED after release cancel, got "
            f"{line['status']}")
        backorder = api_client.get_backorder_allocation(
            ctx["backorder"]["id"], WH_MGR).json()["data"]
        assert backorder["status"] == "CANCELLED", (
            f"open backorder must be CANCELLED, got {backorder['status']}")

        item = api_client.get_catalog_item(ctx["item"]["id"], WH_MGR) \
            .json()["data"]
        assert item["stock_on_hand"] == 100
        assert item["stock_allocated"] == 0
        contractor = api_client.get_contractor(
            ctx["contractor"]["id"], CREDIT_MGR).json()["data"]
        assert contractor["committed_balance_cents"] == 0, (
            "the committed estimate is released when the release is "
            "cancelled")


class TestJobCloseGuard:

    def test_close_job_with_open_release_rejected(self):
        """PRD section 3.3: "Closure is refused with
        `ERR_JOB_HAS_OPEN_RELEASES` while any quote on the account is still
        `DRAFT` or `SUBMITTED`, or any release is still `REQUESTED`,
        `CREDIT_APPROVED`, `PARTIALLY_ALLOCATED`, `ALLOCATED`, `SCHEDULED`, or
        `DELIVERED`."

        Design: Corner/state_machines/close_job_with_open_release_rejected
        """
        ctx = setup_requested_release()
        resp = api_client.close_job_account(ctx["job"]["id"], BRANCH_MGR)
        validate_error(resp, ApiErrorId.ERR_JOB_HAS_OPEN_RELEASES)
        job = api_client.get_job_account(ctx["job"]["id"], SALES_REP) \
            .json()["data"]
        assert job["status"] == "OPEN"


class TestReleaseCreationGuards:

    def test_release_item_not_on_quote_rejected(self):
        """PRD section 3.6: "the quote must be an `AWARDED` quote belonging to
        the same job account, every line's item must appear on that quote
        (`ERR_ITEM_NOT_ON_QUOTE`), and every `FOOT` line's `qty` must be at
        least the item's `min_cut_ft` (`ERR_BELOW_MIN_CUT`)."

        Design: Corner/validations/release_item_not_on_quote_rejected
        """
        contractor = create_contractor("Mismatch Electric", 100_000)
        brk = create_ea_item()
        thhn = create_foot_item()
        job = create_job_account(contractor["id"], "Mismatch Job",
                                 jobsite_address="44 Site Rd")
        quote = create_awarded_quote(job["id"], [(brk["id"], 1, 5000)])
        resp = api_client.create_release(
            {
                "job_account_id": job["id"],
                "quote_id": quote["id"],
                "expected_job_account_version": job["version"],
                "lines": [{"catalog_item_id": thhn["id"], "qty": 100}],
            },
            SALES_REP)
        validate_error(resp, ApiErrorId.ERR_ITEM_NOT_ON_QUOTE)

    def test_release_create_stale_job_version_rejected(self):
        """PRD section 2.8: "Creating a release requires the request to carry
        `expected_job_account_version`, holding the target job account's
        `version` as last observed. A mismatch with the account's current
        `version` is rejected with `ERR_STALE_JOB_ACCOUNT_VERSION`
        (HTTP 412)."
        PRD section 3.6: "Creating the release also increments the job
        account's `version` by 1, which is precisely what a second writer's
        `expected_job_account_version` is measured against."

        Design: Corner/cross_cutting/release_create_stale_job_version_rejected
        """
        contractor = create_contractor("Xray Electric", 100_000)
        item = create_ea_item()
        job = create_job_account(contractor["id"], "OCC Job 2",
                                 jobsite_address="55 Site Rd")
        quote = create_awarded_quote(job["id"], [(item["id"], 5, 5000)])
        stale_version = job["version"]
        first = create_release(job["id"], quote["id"], [(item["id"], 1)],
                               expected_job_account_version=stale_version)
        assert_release(first)

        resp = api_client.create_release(
            {
                "job_account_id": job["id"],
                "quote_id": quote["id"],
                "expected_job_account_version": stale_version,
                "lines": [{"catalog_item_id": item["id"], "qty": 1}],
            },
            SALES_REP)
        validate_error(resp, ApiErrorId.ERR_STALE_JOB_ACCOUNT_VERSION)
        releases = _releases_on_job(job["id"])
        assert len(releases) == 1, (
            f"the stale second create must be refused; expected exactly 1 "
            f"release on the job, got {len(releases)}")


class TestReleaseLineListing:

    def test_release_lines_filtered_by_release(self):
        """PRD section 3.7: "release lines likewise filter by `release_id`,
        `catalog_item_id`, and `status`."
        PRD section 3.6: "Creating the release also increments the job
        account's `version` by 1, which is precisely what a second writer's
        `expected_job_account_version` is measured against."

        Design: Corner/endpoints/release_lines_filtered_by_release
        """
        ctx = setup_requested_release(line_qty=1)
        release = ctx["release"]

        # A second create carrying the pre-first-create version is stale.
        stale_resp = api_client.create_release(
            {
                "job_account_id": ctx["job"]["id"],
                "quote_id": ctx["quote"]["id"],
                "expected_job_account_version": ctx["job"]["version"],
                "lines": [{"catalog_item_id": ctx["item"]["id"], "qty": 1}],
            },
            SALES_REP)
        validate_error(stale_resp, ApiErrorId.ERR_STALE_JOB_ACCOUNT_VERSION)

        data, meta = validate_paginated(api_client.list_release_lines(
            WH_MGR, params={"release_id": release["id"]}))
        assert len(data) == 1, (
            f"filtering by release_id must return exactly that release's "
            f"lines, got {len(data)}")
        assert data[0]["release_id"] == release["id"]
        assert meta["total_count"] == 1
