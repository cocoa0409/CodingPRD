"""Optimistic concurrency control: stale expected_<parent>_version rejection."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_fund_payload,
    create_share_class_payload,
    create_investor_payload,
    create_subscription_payload,
    create_funding_payload,
    create_nav_period_payload,
    get_fund,
    validate_error,
    validate_success,
)


class TestSubscriptionAcceptStaleFund:
    def test_error_stale_version_triggered(
        self, api, fund_admin_headers, transfer_agent_headers, compliance_officer_headers
    ):
        """PRD §2.8: "accepting a subscription ... requires the request to
        carry expected_fund_version equal to the fund's current version. If
        another writer has advanced the fund's version since the client last
        observed it ... the acceptance is rejected with ERR_STALE_VERSION
        (HTTP 412)."

        Design: Corner/errors/error_stale_version_triggered
        """
        fund = validate_success(api.create_fund(create_fund_payload(), fund_admin_headers), 201)
        cls = validate_success(
            api.create_share_class(fund["id"], create_share_class_payload(), fund_admin_headers),
            201,
        )
        validate_success(
            api.create_nav_period(fund["id"], create_nav_period_payload(), fund_admin_headers),
            201,
        )
        inv1 = validate_success(
            api.create_investor(create_investor_payload(legal_name="A"), fund_admin_headers), 201
        )
        inv2 = validate_success(
            api.create_investor(create_investor_payload(legal_name="B"), fund_admin_headers), 201
        )

        # Bring both subscriptions to FUNDED.
        subs = []
        for inv, amt in ((inv1, 200000), (inv2, 300000)):
            sub = validate_success(
                api.create_subscription(
                    fund["id"],
                    create_subscription_payload(
                        investor_id=inv["id"], share_class_id=cls["id"],
                        commitment_amount_cents=amt, funding_deadline_utc="2026-08-10T00:00:00Z",
                    ),
                    fund_admin_headers,
                ),
                201,
            )
            api.submit_subscription(fund["id"], sub["id"], transfer_agent_headers)
            api.compliance_approve_subscription(fund["id"], sub["id"], compliance_officer_headers)
            api.record_funding(
                fund["id"], sub["id"],
                create_funding_payload(amount_cents=amt, received_at_utc="2026-08-04T00:00:00Z"),
                transfer_agent_headers,
            )
            subs.append(sub)

        # Capture version, then advance it by accepting the first subscription.
        fund_v_pre = get_fund(fund["id"])["version"]
        accept1 = api.accept_subscription(
            fund["id"], subs[0]["id"],
            {"expected_fund_version": fund_v_pre},
            fund_admin_headers,
        )
        validate_success(accept1, 200)

        # Now attempt the second accept with the stale version.
        resp = api.accept_subscription(
            fund["id"], subs[1]["id"],
            {"expected_fund_version": fund_v_pre},
            fund_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestNavFinalizeStaleFund:
    def test_nav_finalize_occ_stale_version(
        self, api, fund_admin_headers, transfer_agent_headers, compliance_officer_headers
    ):
        """PRD §2.8: "finalizing a NAV period requires the request to carry
        expected_fund_version equal to the fund's current version. ... if
        the version has advanced since the client last read the fund, the
        cached total is stale and the finalize is rejected with
        ERR_STALE_VERSION (HTTP 412)."

        Design: Corner/cross_cutting_layers/nav_finalize_occ_stale_version
        """
        fund = validate_success(api.create_fund(create_fund_payload(), fund_admin_headers), 201)
        cls = validate_success(
            api.create_share_class(fund["id"], create_share_class_payload(), fund_admin_headers),
            201,
        )
        period = validate_success(
            api.create_nav_period(fund["id"], create_nav_period_payload(), fund_admin_headers),
            201,
        )
        inv = validate_success(
            api.create_investor(create_investor_payload(), fund_admin_headers), 201
        )
        sub = validate_success(
            api.create_subscription(
                fund["id"],
                create_subscription_payload(
                    investor_id=inv["id"], share_class_id=cls["id"],
                    commitment_amount_cents=200000, funding_deadline_utc="2026-08-10T00:00:00Z",
                ),
                fund_admin_headers,
            ),
            201,
        )
        api.submit_subscription(fund["id"], sub["id"], transfer_agent_headers)
        api.compliance_approve_subscription(fund["id"], sub["id"], compliance_officer_headers)
        api.record_funding(
            fund["id"], sub["id"],
            create_funding_payload(amount_cents=200000, received_at_utc="2026-08-04T00:00:00Z"),
            transfer_agent_headers,
        )

        # Capture the old version, then advance it via subscription accept.
        fv_old = get_fund(fund["id"])["version"]
        api.accept_subscription(
            fund["id"], sub["id"],
            {"expected_fund_version": fv_old},
            fund_admin_headers,
        )

        # Now finalize with the stale version.
        resp = api.finalize_nav_period(
            fund["id"], period["id"],
            {"gross_return_bps": 500, "expected_fund_version": fv_old},
            fund_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
