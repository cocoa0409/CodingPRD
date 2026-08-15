"""Authentication, role-based access control, and segregation of duties."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_amendment,
    create_lease_payload,
    create_option_payload,
    get_success_data,
    make_am_headers,
    make_lc_headers,
    propose_amendment,
    setup_active_lease,
    setup_notice_sent,
    setup_option_on_active_lease,
    setup_portfolio_with_contacts,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


class TestAuthentication:
    def test_missing_auth_headers_returns_401(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role value
        outside that set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_headers_returns_401
        """
        ws = setup_portfolio_with_contacts(name="V5", region="WEST", with_am=False)
        resp = api.get_portfolio(ws["pid"], {})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRoleDenial:
    def test_broker_cannot_create_option(self, api):
        """PRD §2.1: "A request whose authenticated role is not permitted for the
        target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4 (endpoint table): POST /portfolios/{pid}/leases/{lid}/options is
        authorized for AssetManager only.

        Design: Corner/rbac/broker_cannot_create_option
        """
        ws = setup_active_lease(name="R1", region="WEST", with_bk=True)
        payload = create_option_payload(
            option_type="RENEWAL",
            notice_window_open_date="2026-08-01T00:00:00Z",
            notice_window_close_date="2026-12-31T00:00:00Z",
            target_commencement_date="2028-01-01T00:00:00Z",
            extension_years=5,
            rate_determination="FIXED",
            fixed_rent_cents_per_rsf_year=4200,
        )
        resp = api.create_option(ws["pid"], ws["lid"], payload, ws["bk_headers"])
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_landlord_counsel_cannot_deliver_notice(self, api):
        """PRD §2.1: "A request whose authenticated role is not permitted for the
        target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4 (endpoint table): POST .../notices/{nid}/deliver is authorized for
        Broker only.

        Design: Corner/rbac/landlord_counsel_cannot_deliver_notice
        """
        ws = setup_notice_sent(name="R2", region="WEST", with_lc=True)
        resp = api.deliver_notice(
            ws["pid"], ws["lid"], ws["oid"], ws["nid"], ws["lc_headers"])
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        notice = validate_success(api.get_notice(
            ws["pid"], ws["lid"], ws["oid"], ws["nid"], ADMIN))
        assert notice["status"] == "SENT", "Forbidden deliver must not mutate the notice"


class TestSegregationOfDuties:
    def test_sod_agreer_cannot_be_proposer(self, api):
        """PRD §3.7: "Segregation of duties binds the two closing steps: the
        agreeing counsel's `X-User-ID` must differ from the `X-User-ID` of the
        asset manager who most recently moved the amendment to `PROPOSED`, and a
        breach is rejected with `ERR_SOD_VIOLATION` (HTTP 403)."

        Design: Corner/rbac/sod_agreer_cannot_be_proposer
        """
        ws = setup_portfolio_with_contacts(name="R3", region="EAST")
        # DUAL will act as both AssetManager (proposer) and LandlordCounsel (agreer attempt).
        dual = ws["am"]  # an ASSET_MANAGER contact; we will reuse its id with both role headers
        lc2 = ws["lc"] if ws.get("lc") else None
        # Need a distinct LandlordCounsel contact for the successful second agree.
        if lc2 is None:
            from test_helpers import add_contact, make_lc_headers as _mk_lc
            lc2 = add_contact(ws["pid"], "LC R3", "lcr3@x.com", "LANDLORD_COUNSEL")
        lc2_headers = make_lc_headers(lc2["id"])

        dual_am_headers = make_am_headers(dual["id"])
        lease = get_success_data(api.create_lease(
            ws["pid"],
            create_lease_payload(
                premises_label="R3",
                rentable_square_feet=5000,
                base_rent_cents_per_rsf_year=4000,
                commencement_date="2026-01-01T00:00:00Z",
                expiration_date="2027-12-31T00:00:00Z",
                holdover_tier1_pct=150,
                holdover_tier2_pct=200,
            ),
            dual_am_headers,
        ))
        lease = get_success_data(api.activate_lease(
            ws["pid"], lease["id"], {}, dual_am_headers))
        ws["lease"] = lease
        ws["lid"] = lease["id"]
        ws["am_headers"] = dual_am_headers

        amendment = create_amendment(ws, kind="RENEWAL_TERM",
                                     new_expiration_date="2032-12-31T00:00:00Z",
                                     new_base_rent_cents_per_rsf_year=5500)
        propose_amendment(ws, amendment["id"])

        # Same X-User-ID attempts to agree as LandlordCounsel — SoD violation.
        dual_lc_headers = make_lc_headers(dual["id"])
        resp1 = api.agree_amendment(ws["pid"], ws["lid"], amendment["id"], dual_lc_headers)
        validate_error(resp1, ApiErrorId.ERR_SOD_VIOLATION)

        # A different LandlordCounsel contact can agree.
        resp2 = api.agree_amendment(ws["pid"], ws["lid"], amendment["id"], lc2_headers)
        agreed = validate_success(resp2, 200)
        assert agreed["status"] == "AGREED", "A different counsel can agree"
