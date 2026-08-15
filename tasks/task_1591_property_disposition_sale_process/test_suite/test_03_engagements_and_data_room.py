"""Broker engagement windows, the eight-category data room, listing gates,
withdrawal lockdown, and the relist cooling gap."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_active_engagement,
    create_asset,
    create_asset_payload,
    create_engagement,
    create_engagement_payload,
    create_package,
    create_published_package,
    create_approved_analysis,
    gamma_asset_payload,
    list_asset_for_sale,
    pipeline_through_offers,
    set_clock,
    validate_error,
    validate_success,
    verify_all_categories,
)

DM = TEST_USERS["dm_headers"]
ANALYST = TEST_USERS["analyst_headers"]


class TestEngagementWindows:
    def test_engagement_window_adjacent_create_rejected(self, api):
        """PRD: "Neither a create nor an activate may proceed if another
        engagement of the same asset in `PROPOSED` or `ACTIVE` status has a
        window that overlaps the candidate window under closed-interval rules —
        and adjacency counts as overlap, so a candidate whose `window_start`
        equals a prior window's `window_end` is rejected. The violation surfaces
        as `ERR_ENGAGEMENT_WINDOW_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/engagement_window_closed_interval_overlap
        """
        asset = create_asset(create_asset_payload())
        create_active_engagement(asset["id"], window_start="2026-08-10T00:00:00Z",
                                 window_end="2027-02-10T00:00:00Z")
        adjacent = create_engagement_payload(
            asset["id"], window_start="2027-02-10T00:00:00Z",
            window_end="2027-08-10T00:00:00Z", broker_firm_name="BrokerTwo",
            broker_user_id="broker-2")
        validate_error(api.create_engagement(adjacent, DM),
                       ApiErrorId.ERR_ENGAGEMENT_WINDOW_OVERLAP)

    def test_engagement_window_gapped_activate_succeeds(self, api):
        """PRD: "The window is inclusive at both ends — the broker is engaged
        from the start instant through the end instant — which is why the
        overlap arithmetic below uses closed-interval semantics."
        PRD: "A successful activate moves `PROPOSED` to `ACTIVE`."

        Design: Difficulty/resource_temporal_overlap/engagement_window_closed_interval_overlap
        """
        asset = create_asset(create_asset_payload())
        first = create_active_engagement(asset["id"],
                                         window_start="2026-08-10T00:00:00Z",
                                         window_end="2027-02-10T00:00:00Z")
        assert first["status"] == "ACTIVE"
        # A one-day gap after the prior window's inclusive end does not overlap.
        second = create_engagement(asset["id"],
                                   window_start="2027-02-11T00:00:00Z",
                                   window_end="2027-08-10T00:00:00Z",
                                   broker_firm_name="BrokerTwo",
                                   broker_user_id="broker-2")
        assert second["status"] == "PROPOSED"
        activated = validate_success(api.activate_engagement(second["id"], DM))
        assert activated["status"] == "ACTIVE"

    def test_engagement_window_end_before_start_returns_invalid_request(self, api):
        """PRD: "plus an exclusivity window bounded by `window_start` and
        `window_end`, where the end must be strictly after the start."
        PRD: "Request shape comes fourth: missing required fields, invalid enum
        values, violated integer ranges, a `window_end` that is not after its
        `window_start`, or an amount that must be positive but is not, all yield
        `ERR_INVALID_REQUEST`."

        Design: Corner/validations/engagement_window_end_before_start_returns_invalid_request
        """
        asset = create_asset(create_asset_payload())
        payload = create_engagement_payload(
            asset["id"], window_start="2026-09-01T00:00:00Z",
            window_end="2026-09-01T00:00:00Z")
        validate_error(api.create_engagement(payload, DM),
                       ApiErrorId.ERR_INVALID_REQUEST)

    def test_engagement_auto_expires_via_clock(self, api):
        """PRD: "Setting the clock is not a passive act: it triggers a system
        sweep that applies every clock-driven auto-transition whose condition
        the new position satisfies. Specifically, the sweep moves any `ACTIVE`
        broker engagement whose `window_end` lies before the new clock position
        to `EXPIRED`"

        Design: Corner/state_machines/engagement_auto_expires_via_clock
        """
        asset = create_asset(create_asset_payload())
        engagement = create_active_engagement(
            asset["id"], window_start="2026-08-10T00:00:00Z",
            window_end="2026-09-01T00:00:00Z")
        assert engagement["status"] == "ACTIVE"
        set_clock("2026-09-02T00:00:00Z")
        engagements = validate_success(api.list_asset_engagements(asset["id"], DM))
        assert engagements[0]["status"] == "EXPIRED"


class TestDataRoom:
    def test_package_completeness_partial_then_publish_blocked(self, api):
        """PRD: "`verified_categories_count` counts the distinct categories
        holding at least one `VERIFIED` document, and `completeness_pct` is the
        whole-number floor of that count times one hundred divided by eight"
        PRD: "`completeness_pct` must equal exactly 100 — meaning all eight
        categories hold a verified document — with a shortfall rejected as
        `ERR_PACKAGE_INCOMPLETE` (HTTP 422)."

        Design: Corner/entities/package_completeness_partial_then_publish_blocked
        """
        asset = create_asset(create_asset_payload())
        create_active_engagement(asset["id"])
        package = create_package(asset["id"])
        api.upload_documents(
            package["id"],
            [{"category": "RENT_ROLL", "file_name": "rr.pdf"},
             {"category": "OPERATING_STATEMENTS", "file_name": "os.pdf"},
             {"category": "TITLE_COMMITMENT", "file_name": "tc.pdf"}],
            ANALYST)
        verified = validate_success(
            api.verify_documents(package["id"],
                                 ["RENT_ROLL", "OPERATING_STATEMENTS"], DM))
        assert verified["verified_categories_count"] == 2
        assert verified["completeness_pct"] == 25

        validate_error(api.publish_package(package["id"], DM),
                       ApiErrorId.ERR_PACKAGE_INCOMPLETE)

    def test_document_upload_locked_while_offers_open(self, api):
        """PRD: "The data room locks while a call for offers is live: any
        upload attempted while the asset's `marketing_status` is `OFFERS_OPEN`
        is rejected with `ERR_DATA_ROOM_LOCKED` (HTTP 409)."

        Design: Corner/state_machines/document_upload_locked_while_offers_open
        """
        ws = pipeline_through_offers()
        assert ws["asset"]["marketing_status"] == "OFFERS_OPEN"
        resp = api.upload_documents(
            ws["package"]["id"],
            [{"category": "RENT_ROLL", "file_name": "rr2.pdf"}], ANALYST)
        validate_error(resp, ApiErrorId.ERR_DATA_ROOM_LOCKED)
        packages = validate_success(api.list_asset_packages(ws["asset"]["id"], DM))
        assert packages[0]["status"] == "PUBLISHED"

    def test_document_supersede_reverts_published_package(self, api):
        """PRD: "Within a category, at most one document may be non-superseded
        at a time: appending a document to a category that already holds a
        non-`SUPERSEDED` document flips the prior document to `SUPERSEDED`."
        PRD: "If the superseded document had been `VERIFIED`, and the asset is
        not in `OFFERS_OPEN`, the package itself slides from `PUBLISHED` back to
        `IN_REVIEW` — the data room must be re-published before it again
        satisfies the marketing gate."
        PRD: "`completeness_pct` is the whole-number floor of that count times
        one hundred divided by eight"

        Design: Corner/state_machines/document_supersede_reverts_published_package
        """
        asset = create_asset(create_asset_payload())
        create_approved_analysis(asset["id"], cap_rate_bps=500,
                                 est_sale_price_cents=6_000_000_000,
                                 est_selling_costs_cents=0)
        create_active_engagement(asset["id"])
        package = create_published_package(asset["id"])
        assert package["status"] == "PUBLISHED"
        list_asset_for_sale(asset["id"])

        superseded = validate_success(api.upload_documents(
            package["id"],
            [{"category": "RENT_ROLL", "file_name": "rr-v2.pdf"}], ANALYST))
        assert superseded["status"] == "IN_REVIEW"
        assert superseded["completeness_pct"] == 87, \
            "seven of eight categories still verified"

        verify_all_categories(package["id"], verifier=DM,
                              categories=["RENT_ROLL"])
        republished = validate_success(api.publish_package(package["id"], DM))
        assert republished["status"] == "PUBLISHED"
        assert republished["completeness_pct"] == 100


class TestListingAndWithdrawal:
    def test_err_package_not_published_blocks_open_offers(self, api):
        """PRD: "The deal dimension must be `IDLE`, the asset's OfferingPackage
        must be `PUBLISHED` (`ERR_PACKAGE_NOT_PUBLISHED`), and the caller
        supplies an `offers_deadline` that must lie strictly after the current
        clock (`ERR_INVALID_REQUEST`)"

        Design: Corner/errors/err_package_not_published_blocks_open_offers
        """
        asset = create_asset(gamma_asset_payload())
        create_approved_analysis(asset["id"], cap_rate_bps=500,
                                 est_sale_price_cents=2_200_000_000,
                                 est_selling_costs_cents=0)
        create_active_engagement(asset["id"])
        create_package(asset["id"])  # stays DRAFT: no documents
        listed = list_asset_for_sale(asset["id"])
        assert listed["marketing_status"] == "LISTED"
        validate_error(api.open_asset_offers(asset["id"],
                                             "2026-09-15T00:00:00Z", DM),
                       ApiErrorId.ERR_PACKAGE_NOT_PUBLISHED)

    def test_asset_withdraw_terminal_lockdown(self, api):
        """PRD: "Withdrawal is the marketing dimension's terminal act, reachable
        from `EVALUATION`, `LISTED`, `OFFERS_OPEN`, or `OFFERS_CLOSED` but only
        while `deal_status` is `IDLE`"
        PRD: "the asset's `marketing_status` lands in `WITHDRAWN`, from which
        there is no return."
        PRD: "The generic state-machine guard comes fifth: invoking a transition
        on an entity that is not in one of that transition's from-states —
        including any write aimed at an entity in a terminal state — yields
        `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/asset_withdraw_terminal_lockdown
        """
        asset = create_asset(create_asset_payload())
        create_approved_analysis(asset["id"], cap_rate_bps=500,
                                 est_sale_price_cents=6_000_000_000,
                                 est_selling_costs_cents=0)
        create_active_engagement(asset["id"])
        withdrawn = validate_success(api.withdraw_asset(asset["id"], DM))
        assert withdrawn["marketing_status"] == "WITHDRAWN"
        validate_error(api.list_asset_for_sale(asset["id"], DM),
                       ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_err_relist_cooling_period_boundary(self, api):
        """PRD: "From `OFFERS_CLOSED` back to `LISTED`, the deal dimension must
        be `IDLE` — no live purchase-agreement chain, and a mismatch on either
        state gate is `ERR_INVALID_STATE_TRANSITION` — and a seven-day cooling
        gap must have elapsed: the clock must be at or after
        `last_campaign_closed_at` plus seven days, with an earlier attempt
        rejected as `ERR_RELIST_COOLING_PERIOD` (HTTP 409)."
        PRD: "Closing stamps `last_campaign_closed_at` with the clock"

        Design: Corner/errors/err_relist_cooling_period_boundary
        """
        ws = pipeline_through_offers()
        set_clock("2026-09-16T00:00:00Z")
        closed = validate_success(api.close_asset_offers(ws["asset"]["id"], DM))
        assert closed["marketing_status"] == "OFFERS_CLOSED"

        set_clock("2026-09-20T00:00:00Z")
        validate_error(api.list_asset_for_sale(ws["asset"]["id"], DM),
                       ApiErrorId.ERR_RELIST_COOLING_PERIOD)

        set_clock("2026-09-23T00:00:00Z")
        relisted = validate_success(api.list_asset_for_sale(ws["asset"]["id"], DM))
        assert relisted["marketing_status"] == "LISTED", \
            "at exactly the closed instant plus seven days the relist succeeds"
