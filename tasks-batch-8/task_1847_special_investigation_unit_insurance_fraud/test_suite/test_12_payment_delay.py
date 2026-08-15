"""Adjuster-driven payment delay under statutory window caps."""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    make_manager_headers,
    create_adjuster, create_investigator, create_claim, create_referral,
    triage_referral, accept_referral, open_case, assign_investigator,
)
from test_helpers.api_client import api_client


class TestDelayWindow:
    def test_delay_beyond_state_cap_rejected(self, api):
        """PRD §3.1: "the requested `delay_until` must not exceed now plus the
        claim state's statutory cap: 30 days for California and New York, 90 days
        for Florida, 60 days for New Jersey, 45 days for Texas, and 30 days for
        every other state. A `delay_until` exactly at the cap is allowed; anything
        later is rejected with `ERR_DELAY_WINDOW_EXCEEDED`."
        Clock 2026-08-01, CA cap 30d → max delay_until = 2026-08-31.
        Request 2026-09-15 (> cap).

        Design: Corner/errors/err_delay_window_exceeded_trigger
        """
        mh = make_manager_headers()
        get_success_data(api_client.set_clock("2026-08-01T00:00:00Z", mh))
        adj, ah = create_adjuster(manager_headers=mh)
        inv, ih = create_investigator(manager_headers=mh)
        claim = create_claim(adj, state_code="CA", claimed_amount_cents=5_000_000)
        ref = create_referral(claim, headers=ah)
        triage_referral(ref, manager_headers=mh)
        case = accept_referral(ref, manager_headers=mh)
        case = open_case(case, manager_headers=mh)
        asg, case = assign_investigator(case, inv, manager_headers=mh)
        resp = api_client.delay_payment(
            claim["id"],
            {"delay_until": "2026-09-15T00:00:00Z", "reason": "need more time"},
            ah)
        validate_error(resp, ApiErrorId.ERR_DELAY_WINDOW_EXCEEDED)
