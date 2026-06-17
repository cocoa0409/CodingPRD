"""Duration, contractor billing, and risk-score corner calculations.

Corner queue (B): section calculations.
"""
from test_helpers import (
    validate_success, get_success_data,
    setup_site_floor_host,
    create_visit, screen_visit, create_cleared_visit,
    create_contractor_pass, get_floor_version, set_clock,
    TEST_USERS,
)

SO = TEST_USERS["security_officer_headers"]
LA = TEST_USERS["lobby_attendant_headers"]


def test_visit_duration_91_minutes_rounds_up(api):
    """PRD 3.6: "The system computes `visit_duration_minutes` as the elapsed time from
    `sign_in_at` to `sign_out_at` rounded up to whole minutes: the elapsed number of
    seconds divided by 60 and rounded up to the next whole minute".

    Sign-in 09:00:00, sign-out 10:31:00 (5460 seconds = 91 minutes exactly) ->
    visit_duration_minutes 91.

    Design: Corner/calculations/visit_duration_91_minutes_round_up
    """
    set_clock("2026-06-16T09:00:00Z")
    site, floor, host = setup_site_floor_host(badge_total=5, capacity=5)
    visit = create_cleared_visit(site["id"], host["id"], floor["id"],
                                 visitor_full_name="Dur V", visitor_company="DurCo")
    fv = get_floor_version(floor["id"])
    get_success_data(api.sign_in_visit(visit["id"], {"expected_floor_version": fv}, LA))
    set_clock("2026-06-16T10:31:00Z")
    signed_out = validate_success(api.sign_out_visit(visit["id"], LA))
    assert signed_out["visit_duration_minutes"] == 91, (
        f"expected 91, got {signed_out['visit_duration_minutes']}"
    )


def test_contractor_billing_total_across_two_signed_out_visits(api):
    """PRD 3.7: "For a visit lasting more than 60 minutes but no more than 240 minutes,
    the fee is the number of started hours beyond the free hour — that is, the minutes
    above 60 divided by 60 and rounded up — multiplied by 200 cents per started hour.
    For a visit lasting more than 240 minutes, the fee is the full second tier (the
    180-minute span from minute 61 through minute 240 is three started hours, charged
    at 200 cents each) plus, for the time beyond 240 minutes, the number of started
    hours beyond that point — the minutes above 240 divided by 60 and rounded up —
    multiplied by 500 cents per started hour. The billing read returns the `pass_id`,
    the `billing_total_cents`, and the `covered_signed_out_count` of visits that
    contributed."

    Visit A 91 min -> ceil(31/60)=1 x 200 = 200c; Visit B 300 min -> 3x200 +
    ceil(60/60)=1 x 500 = 600 + 500 = 1100c; total 1300c, covered_signed_out_count 2.

    Design: Corner/calculations/contractor_billing_total_across_two_signed_out_visits
    """
    set_clock("2026-06-16T09:00:00Z")
    site, floor, host = setup_site_floor_host(badge_total=5, capacity=5)
    pass_ = create_contractor_pass(host["id"])

    def make_covered_visit():
        v = create_cleared_visit(
            site["id"], host["id"], floor["id"],
            contractor_pass_id=pass_["id"],
            visitor_full_name="Pat Builder", visitor_company="BuildCo",
            scheduled_start="2026-06-16T09:00:00Z", scheduled_end="2026-06-16T15:00:00Z",
        )
        fv = get_floor_version(floor["id"])
        get_success_data(api.sign_in_visit(v["id"], {"expected_floor_version": fv}, LA))
        return v

    v_a = make_covered_visit()
    v_b = make_covered_visit()

    set_clock("2026-06-16T10:31:00Z")
    get_success_data(api.sign_out_visit(v_a["id"], LA))
    set_clock("2026-06-16T14:00:00Z")
    get_success_data(api.sign_out_visit(v_b["id"], LA))

    billing = validate_success(api.get_contractor_pass_billing(pass_["id"], SO))
    assert billing["billing_total_cents"] == 1300, (
        f"expected 1300, got {billing['billing_total_cents']}"
    )
    assert billing["covered_signed_out_count"] == 2, (
        f"expected covered_signed_out_count 2, got {billing['covered_signed_out_count']}"
    )


def test_risk_score_no_match_missing_photo_id_is_15(api):
    """PRD 3.4: "A no-photo-ID condition holds when the visit's `id_scanned` is
    `false`. The raw score adds 50 for a name hit, 30 for a company hit, and 15 for a
    missing photo ID".
    PRD 3.4: "otherwise the decision is CLEAR."

    No watchlist match but id_scanned false -> risk_score 15 (NO_PHOTO_ID_WEIGHT
    only); decision CLEAR.

    Design: Corner/calculations/risk_score_no_match_id_not_scanned_is_15
    """
    site, floor, host = setup_site_floor_host()
    visit = create_visit(site["id"], host["id"], floor["id"],
                         visitor_full_name="No Id", visitor_company="NoCo",
                         id_scanned=False)
    screened = validate_success(api.screen_visit(visit["id"], LA))
    assert screened["risk_score"] == 15, f"expected 15, got {screened['risk_score']}"
    assert screened["status"] == "CLEARED", f"expected CLEARED, got {screened['status']}"
