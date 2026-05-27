"""ABAWD waiver decisioning: county-unemployment threshold boundary and
per-quarter uniqueness.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    set_clock, create_household, add_member, create_abawd_waiver,
)

CW = TEST_USERS["caseworker_headers"]


# ─── Difficulty / boundary_precision_check / abawd_county_unemployment_at_ten_percent_exactly ──

def test_county_unemployment_exactly_10_pct_approves_waiver(api):
    """county_unemployment_pct=10.00 satisfies `>= 10.00` and PRD §3.3
    allows the Caseworker to APPROVE the waiver even when monthly_work_hours
    is below 80. The boundary is inclusive — `>= 10.00` not `> 10.00`.

    PRD §3.3: "A `Caseworker` can advance a `PENDING` waiver to `APPROVED`
    only if the county-unemployment percentage is at least 10.00 OR the
    member's verified monthly work hours are at least 80; `decision_reason`
    must be non-empty."

    Design: Difficulty/boundary_precision_check/abawd_county_unemployment_at_ten_percent_exactly
    """
    set_clock("2026-09-01T00:00:00Z")
    hh = create_household(case_number="NC-120001", state_code="NC",
                          address_line="11 Tar Rd")
    m = add_member(hh["id"], full_name="Adult", date_of_birth="1996-05-05",
                   relationship="HEAD", disabled=False)
    w = create_abawd_waiver(m["id"], quarter="2026-Q3",
                            county_unemployment_pct=10.00,
                            monthly_work_hours=0)
    resp = api.approve_abawd_waiver(
        w["id"], {"decision_reason": "County at threshold"}, CW,
    )
    approved = validate_success(resp, 200)
    assert approved["status"] == "APPROVED", \
        f"county==10.00 must approve, got status={approved['status']!r}"


def test_county_unemployment_below_10_pct_with_low_hours_rejected_on_approve(api):
    """Complementary negative-side boundary: county=5.00 AND hours=20
    fails both arms. /approve must NOT land in APPROVED. PRD §3.3 says
    "only if" — both arms must fail for the approve to be rejected. We
    assert via the application-level work-requirement gate, which is the
    PRD-exposed enforcement of the waiver eligibility predicate.

    PRD §3.3: "A `Caseworker` can advance a `PENDING` waiver to `APPROVED`
    only if the county-unemployment percentage is at least 10.00 OR the
    member's verified monthly work hours are at least 80; `decision_reason`
    must be non-empty."
    PRD §2.8: "(6) the entity is in a from-state listed for the requested
    transition (`ERR_INVALID_STATE`, HTTP 409)"

    Design: Difficulty/boundary_precision_check/abawd_county_unemployment_at_ten_percent_exactly
    """
    set_clock("2026-09-01T00:00:00Z")
    hh = create_household(case_number="NC-120002", state_code="NC",
                          address_line="12 Tar Rd")
    m = add_member(hh["id"], full_name="Adult", date_of_birth="1996-05-05",
                   relationship="HEAD", disabled=False)
    w = create_abawd_waiver(m["id"], quarter="2026-Q3",
                            county_unemployment_pct=5.00,
                            monthly_work_hours=20)
    resp = api.approve_abawd_waiver(
        w["id"], {"decision_reason": "below threshold"}, CW,
    )
    # PRD §3.3's "only if" gates approval; the response must not be a
    # 200 with APPROVED status. Implementations may surface this as
    # ERR_INVALID_STATE (the from-state precondition arm did not pass
    # because eligibility wasn't met) or another non-success.
    assert resp.status_code >= 400, (
        f"sub-threshold waiver approve must not succeed, got HTTP "
        f"{resp.status_code} with body {resp.text}"
    )


# ─── Corner / validations / duplicate_waiver_quarter_rejected ──

def test_duplicate_waiver_for_same_member_and_quarter_rejected(api):
    """Two ABAWDWaiver creates for the same (household_member_id, quarter)
    pair are rejected on the second with ERR_DUPLICATE_WAIVER_QUARTER.

    PRD §3.3: "the pair `(household_member_id, quarter)` is unique; a
    duplicate is rejected with `ERR_DUPLICATE_WAIVER_QUARTER`"

    Design: Corner/validations/duplicate_waiver_quarter_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    hh = create_household(case_number="CA-130001", state_code="CA",
                          address_line="X")
    m = add_member(hh["id"], full_name="Adult", date_of_birth="1996-01-01",
                   relationship="HEAD")
    create_abawd_waiver(m["id"], quarter="2026-Q3",
                        county_unemployment_pct=8.00,
                        monthly_work_hours=0)
    resp = api.create_abawd_waiver(
        {"household_member_id": m["id"], "quarter": "2026-Q3",
         "county_unemployment_pct": 9.00, "monthly_work_hours": 10},
        CW,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_WAIVER_QUARTER.value)
