"""Independence screening: the two standards, and the adverse five-hop cascade."""
from test_helpers import fixtures as X
from test_helpers.assertions import assert_fields_equal
from test_helpers.test_users import make_committee_chair_headers

# Employment that ended on this date lies 1522 days before the default clock date,
# i.e. beyond the three-year lookback but inside the five-year one.
EMPLOYMENT_ENDED_ON = "2022-06-01"

# Issuer revenue is stated so the charitable materiality threshold is a positive
# number (two percent of it) that nil contributions are plainly below; recent
# employment is then the only factor that can fail on either standard.
ISSUER_REVENUE_CENTS = 50000000000

CLEAN_SCREEN = dict(
    payments_to_company_cents=0,
    recipient_gross_revenue_cents=0,
    family_member_employed=False,
    auditor_affiliation=False,
    charitable_contributions_cents=0,
    company_gross_revenue_cents=ISSUER_REVENUE_CENTS,
)


def _proposal_candidate(client, name, email):
    return X.new_candidate(
        client,
        full_name=name,
        email=email,
        birth_date="1972-04-02",
        source_channel="SHAREHOLDER_PROPOSAL",
        shareholder_proponent_name="Meridian Pension Fund",
    )


def test_bright_line_standard_clears_employment_that_ended_beyond_three_years(client):
    """A screen frozen to BRIGHT_LINE decides on bright_line_fail_count, so employment
    that ended 1522 days before the clock date does not disqualify the candidate.

    PRD: "the deciding count is `bright_line_fail_count`: the employment lookback is the three-year figure and charitable materiality is ignored entirely for the decision, although `qualitative_fail_count` is still recorded for the file."

    Design: Difficulty/dual_variant_calc/independence_bright_line_clears_what_enhanced_standard_disqualifies
    """
    X.adopt_policy(client, independence_standard="BRIGHT_LINE")
    chair = X.new_seated_director(
        client, full_name="Dana Chair", email="dana.chair@issuer.example",
        birth_date="1962-03-15", appointed_on="2019-05-01",
    )
    chair_headers = make_committee_chair_headers(chair["id"])
    candidate = _proposal_candidate(client, "Alice Bright", "alice.bright@cand.example")

    screen = X.screen_candidate(
        client,
        candidate["id"],
        chair_headers,
        prior_employment_end_on=EMPLOYMENT_ENDED_ON,
        **CLEAN_SCREEN,
    )

    assert_fields_equal(
        screen,
        {
            "standard_applied": "BRIGHT_LINE",
            "bright_line_fail_count": 0,
            "qualitative_fail_count": 1,
            "determination": "INDEPENDENT",
            "status": "DETERMINED_INDEPENDENT",
            "disqualifying_factor_code": None,
        },
    )
    assert_fields_equal(
        X.get_candidate(client, candidate["id"]),
        {"status": "SCREEN_PASSED", "independence_result": "INDEPENDENT"},
    )


def test_enhanced_standard_disqualifies_the_same_screen_for_recent_employment(client):
    """The identical screen payload frozen to ENHANCED decides on qualitative_fail_count,
    so the same employment end date disqualifies the candidate for RECENT_EMPLOYMENT.

    PRD: "the deciding count is `qualitative_fail_count`: the employment lookback extends to five years and charitable materiality joins the decision."

    Design: Difficulty/dual_variant_calc/independence_bright_line_clears_what_enhanced_standard_disqualifies
    """
    X.adopt_policy(client, independence_standard="ENHANCED")
    chair = X.new_seated_director(
        client, full_name="Dana Chair", email="dana.chair@issuer.example",
        birth_date="1962-03-15", appointed_on="2019-05-01",
    )
    chair_headers = make_committee_chair_headers(chair["id"])
    candidate = _proposal_candidate(client, "Bob Enhanced", "bob.enhanced@cand.example")

    screen = X.screen_candidate(
        client,
        candidate["id"],
        chair_headers,
        prior_employment_end_on=EMPLOYMENT_ENDED_ON,
        **CLEAN_SCREEN,
    )

    assert_fields_equal(
        screen,
        {
            "standard_applied": "ENHANCED",
            "bright_line_fail_count": 0,
            "qualitative_fail_count": 1,
            "determination": "NOT_INDEPENDENT",
            "status": "DETERMINED_NOT_INDEPENDENT",
            "disqualifying_factor_code": "RECENT_EMPLOYMENT",
        },
    )
    assert_fields_equal(
        X.get_candidate(client, candidate["id"]),
        {
            "status": "REJECTED",
            "independence_result": "NOT_INDEPENDENT",
            "rejection_reason_code": "INDEPENDENCE_FAILED",
        },
    )


def test_each_screen_keeps_the_standard_in_force_when_it_was_submitted(client):
    """Two byte-identical screens submitted either side of a superseding policy freeze
    different standards and therefore reach opposite determinations.

    PRD: "On success, `standard_applied` is set to the governing policy's `independence_standard`, `submitted_at` records the logical clock instant"

    Design: Difficulty/dual_variant_calc/independence_bright_line_clears_what_enhanced_standard_disqualifies
    """
    X.adopt_policy(
        client, independence_standard="BRIGHT_LINE", effective_from="2026-01-01T00:00:00Z"
    )
    chair = X.new_seated_director(
        client, full_name="Dana Chair", email="dana.chair@issuer.example",
        birth_date="1962-03-15", appointed_on="2019-05-01",
    )
    chair_headers = make_committee_chair_headers(chair["id"])

    candidate_a = _proposal_candidate(client, "Alice Bright", "alice.bright@cand.example")
    screen_a = X.open_screen(
        client, candidate_a["id"], prior_employment_end_on=EMPLOYMENT_ENDED_ON, **CLEAN_SCREEN
    )
    X.submit_screen(client, screen_a["id"])

    X.adopt_policy(
        client, independence_standard="ENHANCED", effective_from="2026-02-01T00:00:00Z"
    )
    candidate_b = _proposal_candidate(client, "Bob Enhanced", "bob.enhanced@cand.example")
    screen_b = X.open_screen(
        client, candidate_b["id"], prior_employment_end_on=EMPLOYMENT_ENDED_ON, **CLEAN_SCREEN
    )
    X.submit_screen(client, screen_b["id"])

    determined_a = X.determine_screen(client, screen_a["id"], chair_headers)
    determined_b = X.determine_screen(client, screen_b["id"], chair_headers)

    assert_fields_equal(
        determined_a,
        {
            "standard_applied": "BRIGHT_LINE",
            "determination": "INDEPENDENT",
            "qualitative_fail_count": 1,
            "bright_line_fail_count": 0,
        },
    )
    assert_fields_equal(
        determined_b,
        {
            "standard_applied": "ENHANCED",
            "determination": "NOT_INDEPENDENT",
            "qualitative_fail_count": 1,
            "bright_line_fail_count": 0,
        },
    )
    assert X.get_candidate(client, candidate_a["id"])["status"] == "SCREEN_PASSED"
    assert X.get_candidate(client, candidate_b["id"])["status"] == "REJECTED"
