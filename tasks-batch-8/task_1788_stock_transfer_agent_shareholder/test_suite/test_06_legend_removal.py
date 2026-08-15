"""Restricted-stock legend removal: cross-reference vs sufficiency precedence,
the opinion resubmission cycle, the inclusive 180-day holding period, and OCC
on the position version."""
from test_helpers import (
    COMPLIANCE,
    ApiErrorId,
    approve_legend,
    create_account,
    create_issuer,
    create_legend_request,
    flag_legend_deficient,
    get_legend_request,
    get_position,
    legend_request_payload,
    make_shareholder_headers,
    seed_position,
    submit_opinion,
    validate_error,
    validate_success,
)


def _setup_restricted_position():
    """Issuer + two accounts; account A holds 100 book / 100 restricted."""
    issuer = create_issuer(name="Lambda Co", cusip="000000011", ticker="LMDA",
                           shares_outstanding=100)
    acct_a = create_account(holder_name="Noah Owner", state_code="TX",
                            city="Dallas", postal_code="75202",
                            tax_id="606-06-0606", tin_status="CERTIFIED")
    acct_b = create_account(holder_name="Olivia Other", state_code="TX",
                            city="Austin", postal_code="73302",
                            tax_id="707-07-0707", tin_status="CERTIFIED")
    position = seed_position(acct_a["id"], issuer["id"], 100,
                             restricted_shares=100)
    return {"issuer": issuer, "acct_a": acct_a, "acct_b": acct_b,
            "position": position}


class TestReferentialVsFiscalPrecedence:
    def test_legend_create_wrong_account_and_excess_reports_mismatch(self, api):
        """PRD §2.8: "Every request is validated against a fixed cascade of
        checks, evaluated in the following order, and the first failing check
        determines the error returned"
        PRD §2.8: "9. **Cross-reference consistency.** A referenced position or
        certificate that does not belong to the named account — or, for a
        certificated transfer source, to the named issuer — fails with
        `ERR_POSITION_ACCOUNT_MISMATCH`."
        PRD §2.8: "10. **Fund and share sufficiency, always checked last.**"

        Design: Difficulty/priority_pair_validation_conflict/legend_referential_beats_fiscal
        """
        ctx = _setup_restricted_position()
        # Violates BOTH priority 9 (account B does not own the position) and
        # priority 10 (999999 > 100 restricted shares).
        resp = api.create_legend_request(
            legend_request_payload(ctx["position"]["id"], ctx["acct_b"]["id"],
                                   999999, "2024-01-01T00:00:00Z",
                                   expected_position_version=ctx["position"]["version"]),
            make_shareholder_headers(ctx["acct_b"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_POSITION_ACCOUNT_MISMATCH)
        assert resp.json()["data"]["error_id"] != "ERR_INSUFFICIENT_RESTRICTED_SHARES", (
            "priority 9 referential must surface before priority 10 fiscal"
        )
        pos = get_position(ctx["acct_a"]["id"], ctx["issuer"]["id"])
        assert pos["pending_legend_removal_count"] == 0
        assert pos["version"] == ctx["position"]["version"], "no mutation fired"

    def test_legend_create_excess_alone_reports_insufficient(self, api):
        """PRD §3.6: "A `share_quantity` below one is refused with
        `ERR_ZERO_SHARE_QUANTITY`, and one exceeding the position's
        `restricted_shares` is refused with
        `ERR_INSUFFICIENT_RESTRICTED_SHARES`."
        PRD §2.8: "10. **Fund and share sufficiency, always checked last.**"

        Design: Difficulty/priority_pair_validation_conflict/legend_referential_beats_fiscal
        """
        ctx = _setup_restricted_position()
        # Referential passes (owner account), only the fiscal gate fails.
        resp = api.create_legend_request(
            legend_request_payload(ctx["position"]["id"], ctx["acct_a"]["id"],
                                   101, "2024-01-01T00:00:00Z",
                                   expected_position_version=ctx["position"]["version"]),
            make_shareholder_headers(ctx["acct_a"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_RESTRICTED_SHARES)
        pos = get_position(ctx["acct_a"]["id"], ctx["issuer"]["id"])
        assert pos["pending_legend_removal_count"] == 0


class TestOpinionResubmissionCycle:
    def test_legend_deficient_resubmit_cycle_reaches_legend_removed(self, api):
        """PRD §3.6: "Deficiency is curable here as on the transfer desk:
        resubmitting the opinion from `DEFICIENT` returns the request to
        `OPINION_UNDER_REVIEW` with the `deficiency_reason` cleared, and the
        flag-and-resubmit cycle may repeat as often as counsel requires."
        PRD §3.6: "Approval moves the request `OPINION_UNDER_REVIEW` →
        `LEGEND_REMOVED`, reduces the position's `restricted_shares` by the
        request's `share_quantity`, decrements the position's
        `pending_legend_removal_count` by one"

        Design: Corner/state_machines/legend_deficient_resubmit_cycle_reaches_legend_removed
        """
        ctx = _setup_restricted_position()
        request = create_legend_request(ctx["position"]["id"],
                                        ctx["acct_a"]["id"], 40,
                                        "2024-01-01T00:00:00Z")
        rid = request["id"]
        assert request["status"] == "SUBMITTED"

        reviewed = submit_opinion(rid, account_id=ctx["acct_a"]["id"],
                                  counsel_opinion_reference="OP-1")
        assert reviewed["status"] == "OPINION_UNDER_REVIEW"
        flagged = flag_legend_deficient(rid, "opinion letter unsigned")
        assert flagged["status"] == "DEFICIENT"

        resubmitted = submit_opinion(rid, account_id=ctx["acct_a"]["id"],
                                     counsel_opinion_reference="OP-2")
        assert resubmitted["status"] == "OPINION_UNDER_REVIEW", (
            "the DEFICIENT -> OPINION_UNDER_REVIEW resubmission cycle"
        )

        # Default clock 2026-08-01 is well past 2024-01-01 + 180 days.
        approved = approve_legend(rid)
        assert approved["status"] == "LEGEND_REMOVED"
        pos = get_position(ctx["acct_a"]["id"], ctx["issuer"]["id"])
        assert pos["restricted_shares"] == 60, "100 - 40 released"
        assert pos["pending_legend_removal_count"] == 0
        assert pos["book_entry_shares"] == 100, (
            "legend removal frees the restriction, not the shares"
        )


class TestHoldingPeriodBoundary:
    def test_legend_holding_period_inclusive_boundary(self, api):
        """PRD §3.6: "the logical clock must have reached the instant one
        hundred eighty days after the request's `acquisition_date`. The
        boundary is inclusive — a request exactly one hundred eighty days old
        is eligible — while an approval even one second short is refused with
        `ERR_HOLDING_PERIOD_NOT_MET`."

        Design: Corner/validations/legend_holding_period_inclusive_boundary
        """
        issuer = create_issuer(name="Pi Holding", cusip="000000040",
                               ticker="PHOL", shares_outstanding=200)
        acct1 = create_account(holder_name="Early Evan", postal_code="74117",
                               tax_id="382-12-1212")
        acct2 = create_account(holder_name="Late Laura", postal_code="74118",
                               tax_id="392-12-1212")
        pos1 = seed_position(acct1["id"], issuer["id"], 100,
                             restricted_shares=100)
        pos2 = seed_position(acct2["id"], issuer["id"], 100,
                             restricted_shares=100)
        # At the default clock 2026-08-01: acquisition 2026-02-02 + 180 days
        # lands exactly on 2026-08-01; acquisition 2026-02-03 is one day short.
        req1 = create_legend_request(pos1["id"], acct1["id"], 10,
                                     "2026-02-02T00:00:00Z")
        req2 = create_legend_request(pos2["id"], acct2["id"], 10,
                                     "2026-02-03T00:00:00Z")
        submit_opinion(req1["id"], account_id=acct1["id"],
                       counsel_opinion_reference="OP-A")
        submit_opinion(req2["id"], account_id=acct2["id"],
                       counsel_opinion_reference="OP-B")

        approved = approve_legend(req1["id"])
        assert approved["status"] == "LEGEND_REMOVED", (
            "exactly 180 days old satisfies the inclusive boundary"
        )
        assert get_position(acct1["id"], issuer["id"])["restricted_shares"] == 90

        resp = api.approve_legend_request(req2["id"], COMPLIANCE)
        validate_error(resp, ApiErrorId.ERR_HOLDING_PERIOD_NOT_MET)
        assert get_legend_request(req2["id"])["status"] == "OPINION_UNDER_REVIEW"


class TestLegendOptimisticConcurrency:
    def test_occ_stale_position_version_legend_create(self, api):
        """PRD §2.7: "Creating a legend-removal request requires the client to
        supply `expected_position_version`, carrying the `version` of the
        target `Position` as the client last observed it. If the position's
        current `version` no longer matches — for example because an earlier
        legend removal was approved and `restricted_shares` changed, or another
        request was opened against the same position — the creation is rejected
        with `ERR_STALE_POSITION_VERSION` (HTTP 412), and the client must
        re-read the position before resubmitting."
        PRD §3.6: "A valid request enters `SUBMITTED` status, increments the
        position's `pending_legend_removal_count` by one, advances the
        position's `version` by one"

        Design: Corner/cross_cutting_layers/occ_stale_position_version_legend_create
        """
        issuer = create_issuer(name="Theta Occ", cusip="000000051",
                               ticker="TOCC", shares_outstanding=100)
        account = create_account(holder_name="Occ Oscar", postal_code="74136",
                                 tax_id="572-12-1212")
        position = seed_position(account["id"], issuer["id"], 100,
                                 restricted_shares=100)
        observed_version = position["version"]

        first = validate_success(api.create_legend_request(
            legend_request_payload(position["id"], account["id"], 10,
                                   "2024-01-01T00:00:00Z", observed_version),
            make_shareholder_headers(account["id"])), 201)
        assert first["status"] == "SUBMITTED"

        # The first create advanced the position version 1 -> 2.
        resp = api.create_legend_request(
            legend_request_payload(position["id"], account["id"], 5,
                                   "2024-01-01T00:00:00Z", observed_version),
            make_shareholder_headers(account["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_POSITION_VERSION)
        pos = get_position(account["id"], issuer["id"])
        assert pos["pending_legend_removal_count"] == 1, (
            "only the first request was counted"
        )
