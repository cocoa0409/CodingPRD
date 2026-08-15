"""Security (context headers, RBAC, theater scope, SoD), optimistic
concurrency, version discipline, and list-endpoint envelope/pagination."""
from test_helpers import (
    ApiErrorId, constants, create_advertiser, create_approved_campaign,
    create_campaign, make_auditor_headers, make_network_ops_headers,
    make_sales_manager_headers, make_theater_ops_headers,
    setup_certified_invoice, setup_confirmed_slot, setup_showtime_with_reel,
    setup_theater_screen_feature, validate_error, validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    audit_attendance_payload, create_invoice_payload, create_playlog_payload,
    create_slot_payload, create_theater_payload, review_make_good_payload,
)
from test_helpers.fixtures import (
    AUDITOR_1, AUDITOR_2, SM_APPROVER, SM_CREATOR, approve_make_good,
    create_showtime_with_reel, get_invoice_version, get_reel_version,
    propose_make_good, reserve_slot, set_clock,
)


def create_approved_campaign_helper(name="C1", advertiser_name="AutoCo",
                                    category="AUTOMOTIVE"):
    """Local convenience wrapper so OCC tests stay compact."""
    advertiser = create_advertiser(name=advertiser_name, category=category)
    return create_approved_campaign(advertiser_id=advertiser["id"], name=name)


class TestContextHeaders:
    def test_request_missing_auth_header_returns_400(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role
        outside that set, is rejected with
        `ERR_MISSING_OR_INVALID_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/errors/request_missing_auth_header_returns_400
        """
        theater_resp = api.create_theater(create_theater_payload(), make_network_ops_headers())
        theater = validate_success(theater_resp, expected_status=201)
        resp = api.get_theater(theater["id"], headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_CONTEXT_HEADER)


class TestRbacDeny:
    def test_theaterops_cannot_create_advertiser(self, api):
        """PRD §2.1: "A request whose role is valid but not permitted on the
        target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)"

        Design: Corner/rbac/theaterops_cannot_create_advertiser
        """
        theater = validate_success(
            api.create_theater(create_theater_payload(), make_network_ops_headers()),
            expected_status=201)
        resp = api.create_advertiser(
            {"name": "Sneaky", "advertiser_type": "LOCAL", "category": "RETAIL"},
            make_theater_ops_headers(theater["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_auditor_cannot_approve_campaign(self, api):
        """PRD §2.1: "A request whose role is valid but not permitted on the
        target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)"

        Design: Corner/rbac/auditor_cannot_approve_campaign
        """
        advertiser = create_advertiser()
        campaign = create_campaign(advertiser["id"], creator=SM_CREATOR)
        api.submit_campaign(campaign["id"], make_sales_manager_headers(SM_CREATOR))
        resp = api.approve_campaign(campaign["id"], make_auditor_headers(AUDITOR_1))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        resp = api.get_campaign(campaign["id"], make_sales_manager_headers(SM_CREATOR))
        assert validate_success(resp)["campaign_status"] == "SUBMITTED"

    def test_networkops_cannot_certify_invoice(self, api):
        """PRD §2.1: "A request whose role is valid but not permitted on the
        target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)"

        Design: Corner/rbac/networkops_cannot_certify_invoice
        """
        advertiser = create_advertiser()
        campaign = create_campaign(advertiser["id"], creator=SM_CREATOR)
        resp = api.create_invoice(campaign["id"], create_invoice_payload(),
                                  make_sales_manager_headers(SM_CREATOR))
        invoice = validate_success(resp, expected_status=201)
        api.issue_invoice(invoice["id"], make_sales_manager_headers(SM_APPROVER))
        resp = api.certify_invoice(invoice["id"], make_network_ops_headers())
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        resp = api.get_invoice(invoice["id"], make_sales_manager_headers(SM_CREATOR))
        assert validate_success(resp)["audit_status"] == "UNAUDITED"


class TestTheaterScope:
    def test_theater_scope_mismatch_on_playlog(self, api):
        """PRD §2.1: "a caller whose `X-User-ID` does not equal the `id` of the
        theater that owns the target showtime's screen is rejected with
        `ERR_THEATER_SCOPE_MISMATCH` (HTTP 403)."

        Design: Corner/rbac/theater_scope_mismatch_on_playlog
        """
        ctx = setup_confirmed_slot()
        other = validate_success(
            api.create_theater(create_theater_payload(name="OtherPlex", market_tier="REGIONAL"),
                               make_network_ops_headers()), expected_status=201)
        set_clock(constants.AFTER_SHOW_CLOCK)
        resp = api.create_playlog(ctx["slot"]["id"], create_playlog_payload(),
                                  make_theater_ops_headers(other["id"]))
        validate_error(resp, ApiErrorId.ERR_THEATER_SCOPE_MISMATCH)
        resp = api.list_playlogs(ctx["slot"]["id"], make_network_ops_headers())
        assert validate_success(resp) == []


class TestSegregationOfDuties:
    def test_sod_approver_is_creator(self, api):
        """PRD §2.7: "Campaign approval and campaign rejection both require the
        caller's `X-User-ID` to differ from the campaign's
        `created_by_user_id`; an overlap is rejected with
        `ERR_SOD_APPROVER_IS_CREATOR`."

        Design: Corner/rbac/sod_approver_is_creator
        """
        advertiser = create_advertiser()
        campaign = create_campaign(advertiser["id"], creator=SM_CREATOR)
        api.submit_campaign(campaign["id"], make_sales_manager_headers(SM_CREATOR))
        resp = api.approve_campaign(campaign["id"], make_sales_manager_headers(SM_CREATOR))
        validate_error(resp, ApiErrorId.ERR_SOD_APPROVER_IS_CREATOR)
        resp = api.get_campaign(campaign["id"], make_sales_manager_headers(SM_CREATOR))
        assert validate_success(resp)["campaign_status"] == "SUBMITTED"
        resp = api.approve_campaign(campaign["id"], make_sales_manager_headers(SM_APPROVER))
        assert validate_success(resp)["campaign_status"] == "APPROVED"

    def test_sod_certifier_is_issuer(self, api):
        """PRD §2.7: "Invoice certification requires the certifying `Auditor` to
        differ from the invoice's `issued_by_user_id`; an overlap is rejected
        with `ERR_SOD_CERTIFIER_IS_ISSUER`."

        Design: Corner/rbac/sod_certifier_is_issuer
        """
        advertiser = create_advertiser()
        campaign = create_campaign(advertiser["id"], creator=SM_CREATOR)
        resp = api.create_invoice(campaign["id"], create_invoice_payload(),
                                  make_sales_manager_headers(SM_CREATOR))
        invoice = validate_success(resp, expected_status=201)
        # One human holds both desks for this scenario: dual-1 issues, then the
        # same id arrives wearing the Auditor hat.
        api.issue_invoice(invoice["id"], make_sales_manager_headers("dual-1"))
        resp = api.certify_invoice(invoice["id"], make_auditor_headers("dual-1"))
        validate_error(resp, ApiErrorId.ERR_SOD_CERTIFIER_IS_ISSUER)
        resp = api.get_invoice(invoice["id"], make_sales_manager_headers(SM_CREATOR))
        assert validate_success(resp)["audit_status"] == "UNAUDITED"

    def test_sod_auditor_is_reporter(self, api):
        """PRD §2.7: "Attendance audit requires the auditing `Auditor` to differ
        from the report's `reported_by_user_id`; an overlap is rejected with
        `ERR_SOD_AUDITOR_IS_REPORTER`."

        Design: Corner/rbac/sod_auditor_is_reporter
        """
        _, _, _, showtime, _ = setup_showtime_with_reel()
        screen = validate_success(api.get_screen(showtime["screen_id"], make_network_ops_headers()))
        theater_id = screen["theater_id"]
        resp = api.create_attendance_report(showtime["id"], {"reported_attendance": 175},
                                            make_theater_ops_headers(theater_id))
        report = validate_success(resp, expected_status=201)
        api.review_attendance_report(report["id"], {"decision": "ACCEPT"},
                                     make_network_ops_headers())
        # The reporting theater's id arrives wearing the Auditor hat.
        resp = api.audit_attendance_report(report["id"],
                                           audit_attendance_payload(audited_attendance=150),
                                           make_auditor_headers(theater_id))
        validate_error(resp, ApiErrorId.ERR_SOD_AUDITOR_IS_REPORTER)
        resp = api.audit_attendance_report(report["id"],
                                           audit_attendance_payload(audited_attendance=150),
                                           make_auditor_headers(AUDITOR_1))
        audited = validate_success(resp)
        assert audited["report_status"] == "AUDITED"
        assert audited["audited_by_user_id"] == AUDITOR_1

    def test_sod_reviewer_is_proposer(self, api):
        """PRD §2.7: "Make-good review requires the reviewing `Auditor` to
        differ from the credit's `proposed_by_user_id`; an overlap is rejected
        with `ERR_SOD_REVIEWER_IS_PROPOSER`."

        Design: Corner/rbac/sod_reviewer_is_proposer
        """
        ctx = setup_certified_invoice(reported_attendance=940,
                                      contracted_impressions=1000)
        credit = propose_make_good(ctx["invoice"]["id"], proposer=AUDITOR_1)
        resp = api.review_make_good(credit["id"], review_make_good_payload("APPROVE"),
                                    make_auditor_headers(AUDITOR_1))
        validate_error(resp, ApiErrorId.ERR_SOD_REVIEWER_IS_PROPOSER)
        resp = api.review_make_good(credit["id"], review_make_good_payload("APPROVE"),
                                    make_auditor_headers(AUDITOR_2))
        assert validate_success(resp)["credit_status"] == "APPROVED"


class TestOptimisticConcurrency:
    def test_occ_slot_add_stale_reel_version(self, api):
        """PRD §2.8: "Reserving a slot — `POST /network/reels/{reel_id}/slots` —
        requires `expected_reel_version` matching the reel's current `version`.
        If another writer has advanced the reel's version since the client last
        read it — by adding a slot, canceling one, or locking the assembly — the
        reservation is rejected rather than built on a stale view of the reel's
        capacity and offsets."

        Design: Corner/cross_cutting_complexity_layers/occ_slot_add_stale_reel_version
        """
        _, _, _, _, reel = setup_showtime_with_reel()
        c1 = create_approved_campaign_helper(name="C1")
        c2 = create_approved_campaign_helper(name="C2", advertiser_name="BurgerCo",
                                             category="QSR")
        stale_version = reel["version"]
        # First reservation advances the reel's version.
        reserve_slot(reel["id"], c1["id"], reel_version=stale_version)
        resp = api.create_slot(reel["id"], create_slot_payload(
            c2["id"], stale_version, start_offset_seconds=60, duration_seconds=30),
            make_sales_manager_headers(SM_CREATOR))
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        resp = api.get_reel(reel["id"], make_network_ops_headers())
        assert validate_success(resp)["national_used_seconds"] == 60

    def test_occ_reel_lock_stale_version(self, api):
        """PRD §2.8: "Locking a reel — `POST /network/reels/{reel_id}/lock` —
        requires `expected_reel_version` on the same terms, so a client never
        locks an assembly that no longer matches what it reviewed."

        Design: Corner/cross_cutting_complexity_layers/occ_reel_lock_stale_version
        """
        _, _, _, _, reel = setup_showtime_with_reel()
        campaign = create_approved_campaign_helper()
        stale_version = reel["version"]
        reserve_slot(reel["id"], campaign["id"], reel_version=stale_version)
        # The slot reservation advanced the reel's version beyond the observed one.
        resp = api.lock_reel(reel["id"], {"expected_reel_version": stale_version},
                             make_network_ops_headers())
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        resp = api.get_reel(reel["id"], make_network_ops_headers())
        assert validate_success(resp)["reel_status"] == "ASSEMBLING"
        # Re-reading and locking with the fresh version succeeds.
        fresh = get_reel_version(reel["id"])
        resp = api.lock_reel(reel["id"], {"expected_reel_version": fresh},
                             make_network_ops_headers())
        assert validate_success(resp)["reel_status"] == "LOCKED"

    def test_occ_credit_apply_stale_invoice_version(self, api):
        """PRD §2.8: "Applying a make-good — `POST
        /network/make-goods/{make_good_id}/apply` — requires
        `expected_invoice_version` matching the invoice's current `version`, so
        a credit is never posted against a `final_amount_cents` the caller has
        not observed."

        Design: Corner/cross_cutting_complexity_layers/occ_credit_apply_stale_invoice_version
        """
        ctx = setup_certified_invoice(reported_attendance=940,
                                      contracted_impressions=1000)
        invoice = ctx["invoice"]
        mg1 = propose_make_good(invoice["id"], proposer=AUDITOR_1)
        approve_make_good(mg1["id"], reviewer=AUDITOR_2)
        stale_version = get_invoice_version(invoice["id"])
        # Applying credit A bumps the invoice's version.
        api.apply_make_good(mg1["id"], {"expected_invoice_version": stale_version},
                            make_sales_manager_headers(SM_CREATOR))
        # A second credit, applied against the pre-A version, is stale.
        mg2 = propose_make_good(invoice["id"], proposer=AUDITOR_1)
        approve_make_good(mg2["id"], reviewer=AUDITOR_2)
        resp = api.apply_make_good(mg2["id"], {"expected_invoice_version": stale_version},
                                   make_sales_manager_headers(SM_CREATOR))
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        # A fresh read and retry succeeds.
        resp = api.apply_make_good(mg2["id"], {"expected_invoice_version": get_invoice_version(invoice["id"])},
                                   make_sales_manager_headers(SM_CREATOR))
        assert validate_success(resp)["credit_status"] == "APPLIED"
        resp = api.get_invoice(invoice["id"], make_sales_manager_headers(SM_CREATOR))
        after = validate_success(resp)
        assert after["applied_credit_cents"] == 330
        assert after["final_amount_cents"] == 2020


class TestVersionDiscipline:
    def test_version_increments_on_every_mutation(self, api):
        """PRD §2.4: "`version`, a system-managed integer that increments by one
        on every mutation of the resource, including mutations applied as a side
        effect of an operation on some other resource."

        Design: Corner/cross_cutting_complexity_layers/version_increments_on_every_mutation
        """
        advertiser = create_advertiser()
        campaign = create_campaign(advertiser["id"], creator=SM_CREATOR)
        assert campaign["version"] == 1
        resp = api.patch_campaign(campaign["id"], {"name": "C1-renamed"},
                                  make_sales_manager_headers(SM_CREATOR))
        patched = validate_success(resp)
        assert patched["version"] == 2
        assert patched["updated_at"] >= campaign["updated_at"]


class TestListingAndPagination:
    def test_list_envelope_and_pagination_defaults(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned:
        it defaults to 10, and any value from a minimum of 1 to a maximum of 100
        is accepted. The `offset` parameter states how many items to skip and
        defaults to 0."
        PRD §2.3: "The `meta` object of a list response carries the pagination
        fields `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/list_envelope_and_pagination_defaults
        """
        _, screen, feature = setup_theater_screen_feature()
        create_showtime_with_reel(screen["id"], feature["id"], "2026-08-14T19:00:00Z")
        create_showtime_with_reel(screen["id"], feature["id"], "2026-08-15T19:00:00Z")
        resp = api.list_showtimes(make_auditor_headers(AUDITOR_1),
                                  params={"screen_id": screen["id"]})
        data, meta = validate_paginated(resp)
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert len(data) == 2
        for item in data:
            assert item["daypart"] in ("MATINEE", "EVENING")
            assert isinstance(item["forecast_attendance"], int)
            assert "id" in item and "created_at" in item
            assert "updated_at" in item and "version" in item

    def test_slots_filtered_list_by_reel_and_campaign(self, api):
        """PRD §3.3: "Slots can be read back individually, listed with the
        optional query filters `reel_id` and `campaign_id`"

        Design: Corner/endpoints/slots_filtered_list_by_reel_and_campaign
        """
        _, screen, feature = setup_theater_screen_feature()
        _, r1 = create_showtime_with_reel(screen["id"], feature["id"], "2026-08-14T19:00:00Z")
        _, r2 = create_showtime_with_reel(screen["id"], feature["id"], "2026-08-15T19:00:00Z")
        c1 = create_approved_campaign_helper(name="C1")
        c2 = create_approved_campaign_helper(name="C2", advertiser_name="BurgerCo",
                                             category="QSR")
        sl1 = reserve_slot(r1["id"], c1["id"], reel_version=r1["version"])
        sl2 = reserve_slot(r2["id"], c2["id"], duration_seconds=30,
                         reel_version=r2["version"])
        resp = api.list_slots(make_sales_manager_headers(SM_CREATOR),
                              params={"reel_id": r1["id"]})
        by_reel, _ = validate_paginated(resp)
        assert [s["id"] for s in by_reel] == [sl1["id"]]
        assert all(s["reel_id"] == r1["id"] for s in by_reel)
        resp = api.list_slots(make_sales_manager_headers(SM_CREATOR),
                              params={"campaign_id": c2["id"]})
        by_campaign, _ = validate_paginated(resp)
        assert [s["id"] for s in by_campaign] == [sl2["id"]]
        assert all(s["campaign_id"] == c2["id"] for s in by_campaign)
