"""Two requests that fail more than one gate at once.

PRD §2.10 fixes the order in which validations fire, so a request that breaks
an early rule and a late rule reports the early one. These tests pin the
reported error against the plausible alternative.
"""
from prd_bench_local_runner.testing import validate_error

from test_helpers import ADJUSTER_HEADERS, ErrorId, PANEL_ADMIN_HEADERS, UNDERWRITER_HEADERS
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.assertions import assert_instant, assert_money, data_of, get_total_count


IRONCLAD = {
    "vendor_name": "Ironclad Forensics",
    "vendor_type": "FORENSICS",
    "pre_approved_hourly_rate_usd": 500,
    "per_record_notification_rate_usd": 0,
    "specialty_sectors": ["HEALTHCARE", "FINANCIAL"],
    "tier": 1,
    "capacity_concurrent_engagements": 1,
}


# ==========================================================================
# Own state (step 9) outranks the hours cap (step 15)
# ==========================================================================
def _completed_engagement_with_five_hours(api):
    """A FORENSICS engagement closed at 5.00 of its 10-hour authorisation."""
    chain = X.bound_policy(
        api,
        account_spec=C.ACCOUNT_AURORA,
        attestations=C.ATTEST_95,
        requested_aggregate_limit_usd=5000000,
        requested_retention_usd=250000,
        coverage_sections=list(C.STANDARD_TOWER),
        findings=[],
    )
    vendor = X.create_vendor(api, IRONCLAD)
    X.set_clock(api, "2026-09-10T00:00:00Z")
    claim = X.confirmed_claim(
        api,
        chain["policy"]["id"],
        incident_type="RANSOMWARE",
        incident_discovered_at="2026-09-05T00:00:00Z",
        outage_start_at="2026-09-05T00:00:00Z",
        outage_end_at="2026-09-08T00:00:00Z",
        covered_section_keys=["FIRST_PARTY_RESPONSE", "BUSINESS_INTERRUPTION"],
        initial_reserve_usd=250000,
    )
    engagement = X.authorize_engagement(
        api,
        claim["id"],
        vendor_type="FORENSICS",
        deployment_start_at="2026-09-10T00:00:00Z",
        deployment_end_at="2026-09-15T00:00:00Z",
        authorized_hours_cap=10,
        panel_vendor_id=vendor["id"],
    )
    X.log_hours(api, engagement["id"], hours=5)
    closed = X.complete_engagement(api, engagement["id"])
    assert closed["status"] == "COMPLETED", closed["status"]
    return chain, vendor, claim, engagement


def test_logging_against_a_closed_engagement_reports_the_state_not_the_cap(api):
    """Twenty hours on a COMPLETED engagement is a 409 on state, not a 422 on the cap.

    PRD §2.10 orders "**Own state** — the addressed row is in a state from which the
    requested transition is declared in §3; terminal states admit no transition at
    all." ahead of "**Money and limit constraints, checked last** (422) —
    `ERR_RATE_EXCEEDS_PRE_APPROVED`, `ERR_AUTHORIZED_HOURS_EXCEEDED`,
    `ERR_SUBLIMIT_EXCEEDS_AGGREGATE`, `ERR_INVALID_LIMIT_INCREMENT`, and
    `ERR_AGGREGATE_LIMIT_EXHAUSTED`." The 20 hours would breach the 10-hour cap, but
    §3.7 settles the state question first: "Logging against an engagement that has
    reached `COMPLETED` or `TERMINATED` is refused with
    `ERR_INVALID_ENGAGEMENT_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/engagement_terminal_state_outranks_hours_cap_returns_409
    """
    _chain, _vendor, _claim, engagement = _completed_engagement_with_five_hours(api)

    response = api.log_engagement_hours(
        engagement["id"], F.log_hours_payload(hours=20), ADJUSTER_HEADERS
    )

    validate_error(response, ErrorId.INVALID_ENGAGEMENT_STATE, 409)


def test_the_refused_hours_leave_the_engagement_and_claim_ledger_untouched(api):
    """After the refusal the engagement still reads 5.00 hours and 2500.00 incurred.

    PRD §2.10: "Later checks never mask earlier ones." A refused request writes
    nothing, so the closed engagement keeps the figures its completion allocated,
    which the 250,000 retention absorbed in full.

    Design: Difficulty/priority_pair_validation_conflict/engagement_terminal_state_outranks_hours_cap_returns_409
    """
    _chain, vendor, claim, engagement = _completed_engagement_with_five_hours(api)

    api.log_engagement_hours(
        engagement["id"], F.log_hours_payload(hours=20), ADJUSTER_HEADERS
    )

    after = data_of(api.get_vendor_engagement(engagement["id"], ADJUSTER_HEADERS))
    assert after["status"] == "COMPLETED", after["status"]
    assert_money(after["incurred_hours"], 5.00, "incurred_hours")
    assert_money(after["incurred_amount_usd"], 2500.00, "incurred_amount_usd")

    reread_claim = X.read_claim(api, claim["id"])
    assert_money(reread_claim["retention_absorbed_usd"], 2500.00, "retention_absorbed_usd")
    assert_money(reread_claim["paid_total_usd"], 0.00, "paid_total_usd")

    assert X.list_payments_for_claim(api, claim["id"]) == []

    reread_vendor = data_of(api.get_panel_vendor(vendor["id"], PANEL_ADMIN_HEADERS))
    assert reread_vendor["active_engagement_count"] == 0, reread_vendor


# ==========================================================================
# Segregation of duties (step 5) outranks the quote expiry gate (step 12)
# ==========================================================================
def _expired_quote_still_marked_quoted(api):
    """A quote issued at the default clock, read again five weeks later with no sweep."""
    chain = X.quoted_application(
        api,
        account_spec=C.ACCOUNT_AURORA,
        attestations=C.ATTEST_95,
        requested_aggregate_limit_usd=5000000,
        requested_retention_usd=250000,
        findings=[F.scan_finding("EMAIL_FILTERING", "HIGH", "PARTIAL")],
    )
    quoted = chain["application"]
    assert quoted["status"] == "QUOTED", quoted["status"]
    assert_instant(quoted["quote_expires_at"], "2026-08-31T00:00:00Z", "quote_expires_at")
    assert_money(quoted["premium_usd"], 28458.00, "premium_usd")

    X.set_clock(api, "2026-09-15T00:00:00Z")
    return chain


def test_the_quoting_underwriter_is_refused_on_duties_before_the_expiry_is_reached(api):
    """The quoting underwriter binding a stale quote gets 403, not the 422 on expiry.

    PRD §2.11: "Binding an application is refused when `X-User-ID` equals the
    application's `quoted_by_user_id`." PRD §2.10 places "**Segregation of duties** —
    the two rules in §2.11; otherwise `ERR_SEGREGATION_OF_DUTIES` (403)." ahead of
    "**Clock-relative gates** (422) — `ERR_INCIDENT_OUTSIDE_POLICY_PERIOD`,
    `ERR_LATE_NOTIFICATION`, `ERR_WAITING_PERIOD_NOT_SATISFIED`,
    `ERR_RENEWAL_WINDOW_NOT_OPEN`, and `ERR_QUOTE_EXPIRED`."

    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_outranks_quote_expiry_returns_403
    """
    chain = _expired_quote_still_marked_quoted(api)
    application = chain["application"]

    response = api.bind_application(
        application["id"],
        F.bind_payload(application["version"], coverage_sections=list(C.STANDARD_TOWER)),
        UNDERWRITER_HEADERS,
    )

    validate_error(response, ErrorId.SEGREGATION_OF_DUTIES, 403)


def test_no_policy_is_created_and_the_quote_fields_survive_the_refusal(api):
    """The application stays QUOTED at 28458.00 and the account has no policy.

    PRD §2.11: "Both checks precede any state or business validation on those two
    operations, per §2.10." A refused bind writes nothing, so the priced quote is
    exactly as it was and no policy was minted from it.

    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_outranks_quote_expiry_returns_403
    """
    chain = _expired_quote_still_marked_quoted(api)
    application = chain["application"]

    api.bind_application(
        application["id"],
        F.bind_payload(application["version"], coverage_sections=list(C.STANDARD_TOWER)),
        UNDERWRITER_HEADERS,
    )

    after = X.read_application(api, application["id"])
    assert after["status"] == "QUOTED", after["status"]
    assert_money(after["premium_usd"], 28458.00, "premium_usd")
    assert after["quoted_by_user_id"] == "u-underwriter-1", after["quoted_by_user_id"]
    assert_instant(after["quote_expires_at"], "2026-08-31T00:00:00Z", "quote_expires_at")

    listed = api.list_policies(UNDERWRITER_HEADERS, params={"application_id": application["id"]})
    assert get_total_count(listed) == 0
