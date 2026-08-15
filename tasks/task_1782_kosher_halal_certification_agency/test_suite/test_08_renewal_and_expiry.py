"""Certificate renewal window, risk gate, expiry boundary, overdue fee sweep."""
from test_helpers import (
    ApiErrorId,
    assert_instant_equals,
    find_invoices,
    get_client,
    issue_additional_certificate,
    make_account_manager_headers,
    make_officer_headers,
    parse_instant,
    raise_finding,
    request_holiday_window,
    confirm_window,
    set_clock,
    setup_certified_client,
    start_routine_visit,
    validate_error,
    validate_success,
)


def _officer():
    return make_officer_headers("co-1")


class TestCertificateValidityVariants:
    def test_certificate_valid_until_annual_vs_seasonal_divergence(
            self, api, officer_headers):
        """PRD section 3.7: "an `ANNUAL` certificate is valid for exactly 365
        days from `issued_at`; a `SEASONAL` certificate's `valid_until` is fixed
        to its holiday window's `window_end`, typically far shorter."

        Design: Difficulty/dual_variant_calc/certificate_valid_until_annual_vs_seasonal_divergence
        """
        ctx = setup_certified_client(legal_name="Seasonal Co",
                                     issue_clock="2026-08-15T10:00:00Z")
        annual = ctx["certificate"]
        window = request_holiday_window(
            ctx["client"]["id"], ctx["facility"]["id"], holiday_code="PASSOVER",
            window_start="2026-09-20T00:00:00Z",
            window_end="2026-09-30T23:59:59Z")
        confirm_window(window["id"], "sup-9")
        seasonal = issue_additional_certificate(
            ctx, term_type="SEASONAL", holiday_window_id=window["id"])

        assert seasonal["status"] == "ACTIVE"
        assert_instant_equals(seasonal["issued_at"], "2026-08-15T10:00:00Z",
                              "seasonal issued_at (clock frozen)")
        assert_instant_equals(annual["issued_at"], "2026-08-15T10:00:00Z",
                              "annual issued_at (clock frozen)")
        assert_instant_equals(annual["valid_until"], "2027-08-15T10:00:00Z",
                              "ANNUAL: issued_at + 365 days")
        assert_instant_equals(seasonal["valid_until"],
                              "2026-09-30T23:59:59Z",
                              "SEASONAL: the holiday window end")
        assert parse_instant(annual["valid_until"]) != parse_instant(
            seasonal["valid_until"]), (
                "identical issuance instant, different expiration arithmetic")

    def test_seasonal_valid_until_tracks_the_linked_window_end(
            self, api, officer_headers):
        """PRD section 3.7: "a `SEASONAL` certificate's `valid_until` is fixed
        to its holiday window's `window_end`". PRD section 3.7: "A successful
        issuance sets `issued_at` to the current logical instant".

        Design: Difficulty/dual_variant_calc/certificate_valid_until_annual_vs_seasonal_divergence
        """
        ctx = setup_certified_client(legal_name="Seasonal Co 2",
                                     issue_clock="2026-08-15T10:00:00Z")
        window = request_holiday_window(
            ctx["client"]["id"], ctx["facility"]["id"], holiday_code="PASSOVER",
            window_start="2026-09-20T00:00:00Z",
            window_end="2026-09-25T18:00:00Z")
        confirm_window(window["id"], "sup-9")
        seasonal = issue_additional_certificate(
            ctx, term_type="SEASONAL", holiday_window_id=window["id"])
        assert_instant_equals(seasonal["valid_until"], "2026-09-25T18:00:00Z",
                              "valid_until == linked window_end")
        assert_instant_equals(ctx["certificate"]["valid_until"],
                              "2027-08-15T10:00:00Z",
                              "the ANNUAL sibling keeps its own arithmetic")


class TestRenewalRules:
    def test_seasonal_certificate_not_renewable(self, api, officer_headers):
        """PRD section 3.7: "Renewal operates on an `ACTIVE` `ANNUAL`
        certificate only — renewing a `SEASONAL` certificate yields
        `ERR_CERTIFICATE_NOT_RENEWABLE`".

        Design: Corner/validations/seasonal_certificate_not_renewable
        """
        ctx = setup_certified_client(legal_name="SN Co")
        window = request_holiday_window(ctx["client"]["id"],
                                        ctx["facility"]["id"])
        confirm_window(window["id"], "sup-9")
        seasonal = issue_additional_certificate(
            ctx, term_type="SEASONAL", holiday_window_id=window["id"])
        assert seasonal["status"] == "ACTIVE"

        resp = api.renew_certificate(seasonal["id"], officer_headers)
        validate_error(resp, ApiErrorId.ERR_CERTIFICATE_NOT_RENEWABLE)

    def test_renew_twice_rejected_renewal_already_exists(self, api,
                                                         officer_headers):
        """PRD section 3.7: "Renewal is blocked while the client's `risk_tier`
        is `HIGH` (`ERR_CLIENT_HIGH_RISK`, HTTP 403), while any certificate
        entry is `FROZEN`, and while another renewal child of this certificate
        exists in `DRAFT`, `ACTIVE`, or `SUSPENDED`
        (`ERR_RENEWAL_ALREADY_EXISTS`)."

        Design: Corner/validations/renew_twice_rejected_renewal_already_exists
        """
        ctx = setup_certified_client(legal_name="RN Co",
                                     term_start_date="2026-08-01",
                                     issue_clock="2026-08-15T10:00:00Z")
        cert_id = ctx["certificate"]["id"]
        set_clock("2027-07-01T00:00:00Z")
        child = validate_success(api.renew_certificate(cert_id, _officer()),
                                 201)
        assert child["status"] == "DRAFT"
        assert child["renews_certificate_id"] == cert_id

        resp = api.renew_certificate(cert_id, _officer())
        validate_error(resp, ApiErrorId.ERR_RENEWAL_ALREADY_EXISTS)

    def test_renew_before_window_rejected(self, api, officer_headers):
        """PRD section 3.7: "The renewal window is the sixty days before expiry:
        the current instant must be no earlier than `valid_until` minus 60 days
        and no later than `valid_until`, both bounds inclusive; outside the
        window the call is rejected with `ERR_RENEWAL_WINDOW_CLOSED`."

        Design: Corner/validations/renew_before_window_rejected
        """
        ctx = setup_certified_client(legal_name="RW Co",
                                     issue_clock="2026-08-15T10:00:00Z")
        assert_instant_equals(ctx["certificate"]["valid_until"],
                              "2027-08-15T10:00:00Z", "valid_until")
        set_clock("2026-09-01T00:00:00Z")  # window opens 2027-06-16T10:00:00Z
        resp = api.renew_certificate(ctx["certificate"]["id"], _officer())
        validate_error(resp, ApiErrorId.ERR_RENEWAL_WINDOW_CLOSED)


class TestRiskTierRenewalBoundary:
    def _certified_with_score(self, target_minor_extra=False):
        """Certificate issued 2026-08-15T10:00Z; three OPEN findings (M, M, m)
        -> score 7 / MEDIUM. Returns ctx."""
        ctx = setup_certified_client(legal_name="Risk Co",
                                     term_start_date="2026-08-01",
                                     issue_clock="2026-08-15T10:00:00Z")
        visit = start_routine_visit(ctx["facility"]["id"],
                                    inspector_user_id="sup-2",
                                    start="2026-08-20T09:00:00Z",
                                    end="2026-08-20T12:00:00Z",
                                    clock_into_window="2026-08-20T10:00:00Z")
        deadline = "2027-12-31T00:00:00Z"
        raise_finding(visit["id"], "sup-2", severity="MAJOR",
                      description="label mismatch",
                      remediation_deadline=deadline)
        raise_finding(visit["id"], "sup-2", severity="MAJOR",
                      description="uncleaned shared tank",
                      remediation_deadline=deadline)
        raise_finding(visit["id"], "sup-2", severity="MINOR",
                      description="logbook gap",
                      remediation_deadline=deadline)
        validate_success(_complete(visit))
        return ctx

    def test_risk_tier_score_7_allows_renewal_score_8_blocks(self, api):
        """PRD section 3.6: "`LOW` when the score is at most 2, `MEDIUM` when it
        is from 3 through 7, and `HIGH` when it is 8 or more." PRD section 3.7:
        "Renewal is blocked while the client's `risk_tier` is `HIGH`
        (`ERR_CLIENT_HIGH_RISK`, HTTP 403)".

        Design: Difficulty/boundary_precision_check/risk_tier_score_7_allows_renewal_score_8_blocks
        """
        ctx = self._certified_with_score()
        cert_id = ctx["certificate"]["id"]
        scored = get_client(ctx["client"]["id"])
        assert scored["open_nc_score"] == 7
        assert scored["risk_tier"] == "MEDIUM"

        set_clock("2027-07-01T00:00:00Z")
        child = validate_success(api.renew_certificate(cert_id, _officer()),
                                 201)
        assert child["status"] == "DRAFT"
        assert child["renews_certificate_id"] == cert_id
        renewal_invoices = find_invoices(invoice_type="RENEWAL",
                                         related_certificate_id=child["id"])
        assert len(renewal_invoices) == 1
        assert renewal_invoices[0]["status"] == "ISSUED"

        # One more MINOR finding: 7 + 1 = 8, exactly the HIGH boundary.
        visit = start_routine_visit(ctx["facility"]["id"],
                                    inspector_user_id="sup-3",
                                    start="2027-07-01T13:00:00Z",
                                    end="2027-07-01T15:00:00Z",
                                    clock_into_window="2027-07-01T14:00:00Z")
        raise_finding(visit["id"], "sup-3", severity="MINOR",
                      description="second logbook gap",
                      remediation_deadline="2027-12-31T00:00:00Z")
        boundary = get_client(ctx["client"]["id"])
        assert boundary["open_nc_score"] == 8
        assert boundary["risk_tier"] == "HIGH"

        resp = api.renew_certificate(cert_id, _officer())
        validate_error(resp, ApiErrorId.ERR_CLIENT_HIGH_RISK)

    def test_risk_tier_high_blocks_first_renewal(self, api):
        """PRD section 3.7: "Renewal is blocked while the client's `risk_tier`
        is `HIGH` (`ERR_CLIENT_HIGH_RISK`, HTTP 403)". PRD section 2.8: "Only
        then are entity-state gates evaluated (the family of
        `ERR_*_INVALID_STATE` errors), then business-safety compliance gates
        (documentation, open findings, equipment, segregation, risk), then
        cross-entity referential integrity, then temporal-window rules, then
        uniqueness and cardinality constraints".

        Design: Difficulty/boundary_precision_check/risk_tier_score_7_allows_renewal_score_8_blocks
        """
        ctx = self._certified_with_score()
        visit = start_routine_visit(ctx["facility"]["id"],
                                    inspector_user_id="sup-3",
                                    start="2026-08-21T09:00:00Z",
                                    end="2026-08-21T12:00:00Z",
                                    clock_into_window="2026-08-21T10:00:00Z")
        raise_finding(visit["id"], "sup-3", severity="MINOR",
                      description="second logbook gap",
                      remediation_deadline="2027-12-31T00:00:00Z")
        assert get_client(ctx["client"]["id"])["open_nc_score"] == 8
        assert get_client(ctx["client"]["id"])["risk_tier"] == "HIGH"

        set_clock("2027-07-01T00:00:00Z")
        resp = api.renew_certificate(ctx["certificate"]["id"], _officer())
        validate_error(resp, ApiErrorId.ERR_CLIENT_HIGH_RISK)


class TestExpiryBoundary:
    def test_certificate_expiry_strictly_greater_than_valid_until(
            self, api, officer_headers):
        """PRD section 3.7: "A certificate is expired only when the current
        instant is strictly later than `valid_until`; at the exact instant it
        remains `ACTIVE`."

        Design: Difficulty/boundary_precision_check/certificate_expiry_strictly_greater_than_valid_until
        """
        ctx = setup_certified_client(legal_name="Expiry Co",
                                     term_start_date="2026-09-01",
                                     issue_clock="2026-08-15T10:00:00Z")
        cert_id = ctx["certificate"]["id"]

        set_clock("2027-08-15T10:00:00Z")
        at_exact = validate_success(api.get_certificate(cert_id,
                                                        officer_headers))
        assert at_exact["status"] == "ACTIVE", (
            "expiry requires strictly greater than valid_until")

        set_clock("2027-08-15T10:00:01Z")
        past = validate_success(api.get_certificate(cert_id, officer_headers))
        assert past["status"] == "EXPIRED"
        assert get_client(ctx["client"]["id"])["status"] == "SUSPENDED", (
            "zero ACTIVE certificates suspends the client")

        resp = api.renew_certificate(cert_id, _officer())
        validate_error(resp, ApiErrorId.ERR_CERTIFICATE_INVALID_STATE)

    def test_renewal_at_exact_valid_until_succeeds(self, api, officer_headers):
        """PRD section 3.7: "the current instant must be no earlier than
        `valid_until` minus 60 days and no later than `valid_until`, both bounds
        inclusive". PRD section 3.7: "A successful renew creates a
        renewal-child `DRAFT` certificate whose `renews_certificate_id` names
        the parent".

        Design: Difficulty/boundary_precision_check/certificate_expiry_strictly_greater_than_valid_until
        """
        ctx = setup_certified_client(legal_name="Expiry Co 2",
                                     term_start_date="2026-09-01",
                                     issue_clock="2026-08-15T10:00:00Z")
        cert_id = ctx["certificate"]["id"]
        set_clock("2027-08-15T10:00:00Z")  # exactly valid_until, still ACTIVE
        current = validate_success(api.get_certificate(cert_id,
                                                       officer_headers))
        assert current["status"] == "ACTIVE"
        child = validate_success(api.renew_certificate(cert_id, _officer()),
                                 201)
        assert child["status"] == "DRAFT"
        assert child["renews_certificate_id"] == cert_id


class TestOverdueRenewalFeeSweep:
    def test_overdue_renewal_fee_sweep_suspends_and_blocks_reinstate(
            self, api, account_manager_headers, officer_headers):
        """PRD section 2.4: "any `OVERDUE` invoice of type
        `ANNUAL_CERTIFICATION` or `RENEWAL` more than 14 days past its
        `due_date` suspends every `ACTIVE` certificate of that client, then
        recomputes the client". PRD section 3.7: "no `OVERDUE` invoice anywhere
        on the client (`ERR_CERTIFICATION_FEE_UNPAID`)".

        Design: Corner/validations/overdue_renewal_fee_sweep_suspends_and_blocks_reinstate
        """
        ctx = setup_certified_client(legal_name="OV Co",
                                     term_start_date="2026-08-01",
                                     issue_clock="2026-08-15T10:00:00Z")
        cert_id = ctx["certificate"]["id"]

        # Renew at exactly valid_until - 60 days (inclusive lower bound).
        set_clock("2027-06-16T10:00:00Z")
        child = validate_success(api.renew_certificate(cert_id, _officer()),
                                 201)
        renewal = find_invoices(invoice_type="RENEWAL",
                                related_certificate_id=child["id"])
        assert len(renewal) == 1
        renewal_invoice = renewal[0]
        assert renewal_invoice["status"] == "ISSUED"
        assert_instant_equals(renewal_invoice["due_date"],
                              "2027-07-16T10:00:00Z", "issued_at + 30 days")

        # Sweep past due_date + 14-day grace (2027-07-30T10:00:00Z).
        set_clock("2027-07-31T00:00:00Z")
        overdue = validate_success(api.get_invoice(renewal_invoice["id"],
                                                   account_manager_headers))
        assert overdue["status"] == "OVERDUE"
        cert = validate_success(api.get_certificate(cert_id, officer_headers))
        assert cert["status"] == "SUSPENDED", (
            "overdue renewal fee past grace suspends the ACTIVE certificate")
        assert get_client(ctx["client"]["id"])["status"] == "SUSPENDED"

        resp = api.reinstate_certificate(cert_id, _officer())
        validate_error(resp, ApiErrorId.ERR_CERTIFICATION_FEE_UNPAID)

        validate_success(api.record_payment(renewal_invoice["id"],
                                            make_account_manager_headers("am-1")))
        reinstated = validate_success(api.reinstate_certificate(cert_id,
                                                                _officer()))
        assert reinstated["status"] == "ACTIVE"
        assert get_client(ctx["client"]["id"])["status"] == "CERTIFIED"


def _complete(visit):
    """Complete an IN_PROGRESS visit as its assigned inspector."""
    from test_helpers import api_client, make_supervisor_headers
    return api_client.complete_visit(visit["id"], make_supervisor_headers(
        visit["inspector_user_id"]))
