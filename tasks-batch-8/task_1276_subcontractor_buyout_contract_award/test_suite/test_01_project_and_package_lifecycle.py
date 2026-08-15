"""Project stand-up, trade-package creation, and the publish/close gates."""
import pytest

from test_helpers import (
    BL,
    ADMIN,
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    assert_project,
    assert_trade_package,
    create_open_project,
    create_package,
    create_project,
    create_project_payload,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    place_bid,
    publish_package,
    setup_leveling_package,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestProjectCreation:

    def test_project_create_ignores_client_supplied_system_fields(self):
        """PRD section 3.1: "A new project lands in `SETUP` with its logical
        clock at `2026-05-01T00:00:00Z`."
        PRD section 2.5: "`id` — a server-minted UUID, with no type prefix,
        unique across the system."

        Design: Corner/entities/project_create_system_fields_input_ignored
        """
        supplied_id = "11111111-2222-4333-8444-555555555555"
        resp = api_client.create_project(
            create_project_payload(
                name="P-E1", project_number="E1",
                status="BUYOUT_OPEN", id=supplied_id,
            ),
            ADMIN,
        )
        data = validate_success(resp, expected_status=201)
        assert_project(data)
        assert data["status"] == "SETUP", \
            f"client-supplied status must be ignored, got {data['status']}"
        assert data["current_time_utc"] == "2026-05-01T00:00:00Z", \
            f"logical clock must default to 2026-05-01T00:00:00Z, got {data['current_time_utc']}"
        assert data["version"] == 1
        assert data["id"] != supplied_id, "server must mint its own UUID"
        assert is_valid_uuid(data["id"])

    def test_project_get_not_found_returns_404(self, gc_admin_headers):
        """PRD section 2.9: "the first identifier that fails to resolve yields
        `ERR_NOT_FOUND` (HTTP 404) and no further segment is evaluated."

        Design: Corner/entities/project_get_not_found_returns_404
        """
        resp = api_client.get_project(NON_EXISTENT_UUID, gc_admin_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestTradePackageCreation:

    def test_trade_package_create_computed_defaults(self):
        """PRD section 3.1: "A new package lands in `DRAFT` with
        `awarded_value_cents` at 0".
        PRD section 3.9: "the package's `buyout_posture` is then `FAVORABLE`
        when the savings meet or exceed that target, `NEUTRAL` when the
        savings are zero or better but below target, and `UNFAVORABLE` when
        the savings are negative."

        Design: Corner/entities/trade_package_create_defaults
        """
        proj, proj_v = create_open_project("P-E3", "E3")
        resp = api_client.create_trade_package(
            proj["id"],
            {
                "trade_code": "E3-26", "title": "Mechanical",
                "estimated_budget_cents": 5_000_000,
                "budgeted_contingency_cents": 0,
                "spec_section": "23 00 00",
                "bid_due_at": "2026-05-20T16:00:00Z",
                "bonding_policy": "WAIVED",
                "expected_project_version": proj_v,
            },
            BL,
        )
        data = validate_success(resp, expected_status=201)
        assert_trade_package(data)
        assert data["status"] == "DRAFT"
        assert data["version"] == 1
        assert data["awarded_value_cents"] == 0
        # savings = estimated - awarded - consumed = 5_000_000 - 0 - 0
        assert data["buyout_savings_cents"] == 5_000_000
        # target = round_half_up(0.05 * 5_000_000) = 250_000 <= savings
        assert data["buyout_posture"] == "FAVORABLE"

    def test_package_create_invalid_bonding_policy_rejected(self):
        """PRD section 3.1: "a `bonding_policy` of `REQUIRED`,
        `PER_TRADE_RISK`, or `WAIVED`".

        Design: Corner/entities/package_create_invalid_bonding_policy_rejected
        """
        proj, proj_v = create_open_project("P-E4", "E4")
        resp = api_client.create_trade_package(
            proj["id"],
            {
                "trade_code": "E4-26", "title": "Mechanical",
                "estimated_budget_cents": 5_000_000,
                "budgeted_contingency_cents": 0,
                "bid_due_at": "2026-05-20T16:00:00Z",
                "bonding_policy": "MAYBE",
                "expected_project_version": proj_v,
            },
            BL,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION, expected_status=422)

    def test_occ_stale_package_version_conflict(self):
        """PRD section 2.7: "If the project's current `version` has advanced
        since that read — because another writer opened the project, advanced
        the clock, or created another package, each of which increments
        `Project.version` by 1 — the create is rejected with
        `ERR_STALE_PACKAGE_VERSION` (HTTP 412), forcing the client to re-read
        the project before retrying."

        Design: Corner/validations/occ_stale_package_version_conflict
        """
        proj, proj_v = create_open_project("P-V4", "V4")
        first = create_package(proj["id"], proj_v, name="Pkg A",
                               trade_code="V4-A", budget=5_000_000)
        assert first["status"] == "DRAFT"
        # Package A's creation incremented Project.version; replaying the
        # stale observed version must now be rejected.
        resp = api_client.create_trade_package(
            proj["id"],
            {
                "trade_code": "V4-B", "title": "Pkg B",
                "estimated_budget_cents": 5_000_000,
                "budgeted_contingency_cents": 0,
                "bid_due_at": "2026-05-20T16:00:00Z",
                "bonding_policy": "WAIVED",
                "expected_project_version": proj_v,
            },
            BL,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_PACKAGE_VERSION,
                       expected_status=412)
        data, meta = validate_paginated(
            api_client.list_trade_packages(proj["id"], BL))
        assert len(data) == 1, f"stale create must not persist: {len(data)} packages"
        assert data[0]["trade_code"] == "V4-A"

    def test_list_packages_pagination_envelope(self):
        """PRD section 2.3: "The `limit` parameter caps the number of returned
        items: it defaults to 10 when omitted, accepts a minimum of 1, and
        rejects values above 100. The `offset` parameter skips a number of
        items from the front of the result set and defaults to 0."
        PRD section 2.3: "Paginated list responses populate the `meta` object
        of the envelope with four fields: `limit`, `offset`, `total_count`,
        and `has_more`, so a client can page deterministically through the
        full result set."

        Design: Corner/endpoints/list_packages_pagination_envelope
        """
        proj, proj_v = create_open_project("P-P2", "P2")
        pkg_a = create_package(proj["id"], proj_v, name="Pkg A",
                               trade_code="P2-A", budget=5_000_000)
        proj2 = get_success_data(api_client.get_project(proj["id"], BL))
        pkg_b = create_package(proj["id"], proj2["version"], name="Pkg B",
                               trade_code="P2-B", budget=5_000_000)

        page1, meta1 = validate_paginated(
            api_client.list_trade_packages(
                proj["id"], BL, params={"limit": 1, "offset": 0}))
        assert len(page1) == 1
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True
        assert meta1["limit"] == 1 and meta1["offset"] == 0

        page2, meta2 = validate_paginated(
            api_client.list_trade_packages(
                proj["id"], BL, params={"limit": 1, "offset": 1}))
        assert len(page2) == 1
        assert meta2["total_count"] == 2
        assert meta2["has_more"] is False

        ids = {page1[0]["id"], page2[0]["id"]}
        assert ids == {pkg_a["id"], pkg_b["id"]}, \
            f"pages must partition the two packages, got {ids}"
        # created_at ascending — oldest first
        assert page1[0]["id"] == pkg_a["id"]


class TestPublishAndCloseBidding:

    def test_package_create_before_project_open_rejected(self):
        """PRD section 3.1: "While a project is in `SETUP`, no child mutations
        are possible: any attempt to create or mutate a trade package under it
        is rejected with `ERR_PACKAGE_NOT_OPEN`."

        Design: Corner/state_machines/publish_before_project_open_rejected
        """
        proj = create_project("P-S14", "S14")
        # The package create is itself the gated child mutation: a DRAFT
        # package cannot exist under a SETUP project, so the publish-time
        # ERR_PACKAGE_NOT_OPEN gate is exercised here at creation.
        resp = api_client.create_trade_package(
            proj["id"],
            {
                "trade_code": "S14-26", "title": "Mechanical",
                "estimated_budget_cents": 5_000_000,
                "budgeted_contingency_cents": 0,
                "bid_due_at": "2026-05-20T16:00:00Z",
                "bonding_policy": "WAIVED",
                "expected_project_version": proj["version"],
            },
            BL,
        )
        validate_error(resp, ApiErrorId.ERR_PACKAGE_NOT_OPEN)
        data, meta = validate_paginated(
            api_client.list_trade_packages(proj["id"], BL))
        assert len(data) == 0, \
            f"rejected create must not persist: {len(data)} packages"

    def test_publish_with_past_bid_due_rejected(self):
        """PRD section 3.2: "the package's `bid_due_at` must lie strictly
        after the project's `current_time_utc` (else `ERR_BID_WINDOW_INVALID`).
        A package whose deadline has already passed cannot be opened for
        bidding."

        Design: Corner/state_machines/publish_with_past_bid_due_rejected
        """
        proj, proj_v = create_open_project("P-S15", "S15")
        pkg = create_package(proj["id"], proj_v, name="Mechanical",
                             trade_code="S15-26",
                             bid_due_at="2026-04-30T16:00:00Z")
        resp = api_client.publish_trade_package(pkg["id"], BL)
        validate_error(resp, ApiErrorId.ERR_BID_WINDOW_INVALID)

    def test_close_bidding_without_bids_rejected(self):
        """PRD section 3.2: "Closing the bidding — a `BuyoutLead` action
        moving the package `PUBLISHED → UNDER_LEVELING` — requires that at
        least one bid on the package currently be `PLACED`; otherwise the
        call is rejected with `ERR_NO_BIDS_RECEIVED`."

        Design: Corner/state_machines/close_bidding_without_bids_rejected
        """
        proj, proj_v = create_open_project("P-S1", "S1")
        pkg = create_package(proj["id"], proj_v, name="Mechanical",
                             trade_code="S1-26")
        publish_package(pkg["id"])
        resp = api_client.close_bidding(pkg["id"], BL)
        validate_error(resp, ApiErrorId.ERR_NO_BIDS_RECEIVED)
        after = get_success_data(api_client.get_trade_package(pkg["id"], BL))
        assert after["status"] == "PUBLISHED", \
            f"package must stay PUBLISHED, got {after['status']}"

    def test_subcontract_create_on_published_package_rejected(self):
        """PRD section 3.4: "The package must be `UNDER_LEVELING` and show
        the competitive tension a real buyout requires — at least two bids on
        the package and at least one `WITHDRAWN` bid — otherwise the draft is
        rejected with `ERR_TRADE_PACKAGE_NOT_ACCEPTING_BIDS`."

        Design: Corner/state_machines/subcontract_create_on_published_package_rejected
        """
        proj, proj_v = create_open_project("P-S16", "S16")
        pkg = create_package(proj["id"], proj_v, name="Mechanical",
                             trade_code="S16-26")
        publish_package(pkg["id"])
        bid = place_bid(pkg["id"], "M1", 9_000_000)
        resp = api_client.create_subcontract(
            pkg["id"],
            {
                "subcontractor_name": "M1",
                "source_bid_id": bid["id"],
                "flow_down_terms": "fd",
                "payment_terms": {"retainage_pct": 0.10, "pay_if_paid": True},
                "change_authority_limits": [
                    {"max_value_cents": -1, "max_cumulative_pct": -1,
                     "roles": ["OperationsManager"]},
                ],
            },
            BL,
        )
        validate_error(resp, ApiErrorId.ERR_TRADE_PACKAGE_NOT_ACCEPTING_BIDS)
