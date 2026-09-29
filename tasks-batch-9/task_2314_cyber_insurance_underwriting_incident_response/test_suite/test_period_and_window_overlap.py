"""Interval collisions: policy periods and buffered vendor deployment windows.

Two intervals in this system are compared under opposite conventions. Policy
periods are half-open, so touching endpoints are allowed (PRD §3.5); buffered
vendor windows are closed, so touching endpoints collide (PRD §3.7).
"""
from prd_bench_local_runner.testing import validate_error

from test_helpers import ADJUSTER_HEADERS, ErrorId, PANEL_ADMIN_HEADERS, UNDERWRITER_2_HEADERS
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
# Half-open policy periods
# ==========================================================================
def _incumbent_and_second_quote(api):
    """One INFORCE policy for 2026-08-01 to 2027-08-01 plus a second quoted application."""
    chain = X.bound_policy(
        api,
        account_spec=C.ACCOUNT_AURORA,
        attestations=C.ATTEST_95,
        requested_aggregate_limit_usd=5000000,
        requested_retention_usd=250000,
        coverage_sections=list(C.STANDARD_TOWER),
        period_start="2026-08-01T00:00:00Z",
        period_end="2027-08-01T00:00:00Z",
        findings=[],
    )
    account_id = chain["account"]["id"]
    second = X.create_application(
        api,
        account_id,
        requested_aggregate_limit_usd=5000000,
        requested_retention_usd=250000,
    )
    X.attest_controls(api, second["id"], C.ATTEST_95)
    X.submit_application(api, second["id"])
    scan = X.order_scan(api, second["id"])
    X.complete_scan(api, scan["id"], findings=[])
    quoted = X.quote_application(api, second["id"])
    assert quoted["status"] == "QUOTED", quoted["status"]
    return chain, quoted


def _bind_second(api, application, period_start, period_end):
    return api.bind_application(
        application["id"],
        F.bind_payload(
            application["version"],
            period_start=period_start,
            period_end=period_end,
            coverage_sections=list(C.STANDARD_TOWER),
        ),
        UNDERWRITER_2_HEADERS,
    )


def test_a_period_landing_inside_the_incumbent_is_refused_as_an_overlap(api):
    """A 2027-01-01 start against an incumbent running to 2027-08-01 genuinely overlaps.

    PRD §3.5: "Before the policy is created the server checks that this insured
    account has no existing policy in `INFORCE` whose period overlaps the requested
    one." Any genuine overlap is refused with `ERR_POLICY_PERIOD_OVERLAP`, and
    because a refused bind writes nothing the application is left `QUOTED` at its
    unchanged `version`.

    Design: Difficulty/resource_temporal_overlap/policy_period_half_open_overlap_rejected_while_adjacent_period_binds
    """
    chain, quoted = _incumbent_and_second_quote(api)

    response = _bind_second(api, quoted, "2027-01-01T00:00:00Z", "2028-01-01T00:00:00Z")

    validate_error(response, ErrorId.POLICY_PERIOD_OVERLAP, 422)

    after = X.read_application(api, quoted["id"])
    assert after["status"] == "QUOTED", after["status"]
    assert after["version"] == quoted["version"], after["version"]

    listed = api.list_policies(
        UNDERWRITER_2_HEADERS, params={"insured_account_id": chain["account"]["id"]}
    )
    assert get_total_count(listed) == 1


def test_a_period_beginning_exactly_at_the_incumbent_end_binds(api):
    """Starting at 2027-08-01, the instant the incumbent stops covering, is allowed.

    PRD §3.5: "Because both periods are half-open, a new period beginning exactly at
    an incumbent's `period_end` does not overlap and is allowed; any genuine overlap
    is refused with `ERR_POLICY_PERIOD_OVERLAP`." The same
    `expected_application_version` that the refused attempt carried is still current,
    so the successful attempt reuses it.

    Design: Difficulty/resource_temporal_overlap/policy_period_half_open_overlap_rejected_while_adjacent_period_binds
    """
    chain, quoted = _incumbent_and_second_quote(api)
    _bind_second(api, quoted, "2027-01-01T00:00:00Z", "2028-01-01T00:00:00Z")

    response = _bind_second(api, quoted, "2027-08-01T00:00:00Z", "2028-08-01T00:00:00Z")

    policy = data_of(response, 201)
    assert policy["lifecycle_status"] == "INFORCE", policy["lifecycle_status"]
    assert_instant(policy["period_start"], "2027-08-01T00:00:00Z", "period_start")
    assert_money(policy["aggregate_limit_remaining_usd"], 5000000.00, "aggregate_limit_remaining_usd")

    bound = X.read_application(api, quoted["id"])
    assert bound["status"] == "BOUND", bound["status"]

    listed = api.list_policies(
        UNDERWRITER_2_HEADERS, params={"insured_account_id": chain["account"]["id"]}
    )
    assert get_total_count(listed) == 2


# ==========================================================================
# Closed buffered vendor windows
# ==========================================================================
def _claim_and_single_slot_firm(api):
    """A capacity-1 forensics firm already holding one AUTHORIZED window to 2026-09-12."""
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
    incumbent = X.authorize_engagement(
        api,
        claim["id"],
        vendor_type="FORENSICS",
        deployment_start_at="2026-09-10T00:00:00Z",
        deployment_end_at="2026-09-12T00:00:00Z",
        authorized_hours_cap=40,
        panel_vendor_id=vendor["id"],
    )
    assert incumbent["status"] == "AUTHORIZED", incumbent["status"]
    return chain, vendor, claim, incumbent


def _request_window(api, claim_id, vendor_id, start, end):
    return api.create_vendor_engagement(
        claim_id,
        F.vendor_engagement_payload(
            vendor_type="FORENSICS",
            deployment_start_at=start,
            deployment_end_at=end,
            authorized_hours_cap=40,
            panel_vendor_id=vendor_id,
        ),
        ADJUSTER_HEADERS,
    )


def test_a_window_touching_the_buffered_end_collides_and_is_refused(api):
    """Starting at 2026-09-13T00:00:00Z, exactly where the 24-hour buffer ends, collides.

    PRD §3.7: "A buffered window runs from the engagement's `deployment_start_at` to
    its `deployment_end_at` extended by a changeover buffer of 24 hours, reflecting
    the day a firm needs to stand down one deployment before standing up the next.
    Both the buffered window and the requested window are treated as closed
    intervals, so windows that merely share an endpoint do collide." The firm's
    single slot is therefore already taken, so the authorisation is refused with
    `ERR_VENDOR_WINDOW_CONFLICT`.

    Design: Difficulty/resource_temporal_overlap/vendor_buffered_window_touching_endpoint_rejected_one_second_later_authorized
    """
    _chain, vendor, claim, _incumbent = _claim_and_single_slot_firm(api)

    response = _request_window(
        api, claim["id"], vendor["id"], "2026-09-13T00:00:00Z", "2026-09-14T00:00:00Z"
    )

    validate_error(response, ErrorId.VENDOR_WINDOW_CONFLICT, 422)

    reread = data_of(api.get_panel_vendor(vendor["id"], PANEL_ADMIN_HEADERS))
    assert reread["active_engagement_count"] == 1, reread["active_engagement_count"]

    listed = api.list_vendor_engagements(
        ADJUSTER_HEADERS, params={"panel_vendor_id": vendor["id"]}
    )
    assert get_total_count(listed) == 1


def test_one_second_past_the_buffer_authorizes_and_takes_the_second_slot(api):
    """A 2026-09-13T00:00:01Z start clears the closed buffered interval by one second.

    PRD §3.7: "Two rates are pinned at that instant and never move again:
    `approved_rate_usd` from the chosen firm's `pre_approved_hourly_rate_usd` and
    `approved_per_record_rate_usd` from its `per_record_notification_rate_usd`." The
    firm's `active_engagement_count` is incremented by 1, so the conserved slot count
    reaches 2.

    Design: Difficulty/resource_temporal_overlap/vendor_buffered_window_touching_endpoint_rejected_one_second_later_authorized
    """
    _chain, vendor, claim, _incumbent = _claim_and_single_slot_firm(api)
    _request_window(
        api, claim["id"], vendor["id"], "2026-09-13T00:00:00Z", "2026-09-14T00:00:00Z"
    )

    response = _request_window(
        api, claim["id"], vendor["id"], "2026-09-13T00:00:01Z", "2026-09-14T00:00:00Z"
    )

    engagement = data_of(response, 201)
    assert engagement["status"] == "AUTHORIZED", engagement["status"]
    assert engagement["selection_mode"] == "DIRECTED", engagement["selection_mode"]
    assert_money(engagement["approved_rate_usd"], 500.00, "approved_rate_usd")

    reread = data_of(api.get_panel_vendor(vendor["id"], PANEL_ADMIN_HEADERS))
    assert reread["active_engagement_count"] == 2, reread["active_engagement_count"]

    listed = api.list_vendor_engagements(
        ADJUSTER_HEADERS, params={"panel_vendor_id": vendor["id"]}
    )
    assert get_total_count(listed) == 2
