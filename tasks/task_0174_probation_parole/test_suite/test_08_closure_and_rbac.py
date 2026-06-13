"""Case closure (early termination eligibility, completion balance gate) and
access control (RBAC role denial, authentication, segregation of duties).

Corner queue: endpoints (early-termination grant not-eligible / eligible),
validations (complete with outstanding balance), rbac (officer cannot sustain,
missing auth, segregation filer cannot sustain).
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    make_officer_headers, make_judge_headers,
    setup_active_supervisee, add_obligation, file_violation, file_early_termination,
    set_clock, create_officer_payload,
)


# ─── Corner: endpoints / early_termination_grant_not_eligible_rejected ───
def test_early_termination_grant_not_eligible_rejected(api):
    """PRD §3.9: "A SupervisingJudge grants a SUBMITTED petition only when its
    frozen eligibility.eligible is true and the supervisee is ACTIVE; a grant
    attempted while the petition's eligibility verdict is false is rejected with
    ERR_NOT_ELIGIBLE_FOR_TERMINATION (HTTP 409)."
    PRD §3.9: "percent_served is at least 50 (so exactly half the term served
    qualifies on the time axis)"

    Start 2025-01-01, 24-month term, requested 2025-12-01 -> 11 months -> 45%
    served (< 50): the frozen verdict is false and grant is rejected.

    Design: Corner/endpoints/early_termination_grant_not_eligible_rejected
    """
    officer, sup = setup_active_supervisee(
        level_total=10, ordered_term_months=24,
        supervision_start_date="2025-01-01T00:00:00.000Z",
    )
    oh = make_officer_headers(officer["id"])
    et = file_early_termination(sup["id"], officer["id"], "2025-12-01T00:00:00.000Z")
    assert et["eligibility"]["eligible"] is False

    res = api.grant_early_termination(sup["id"], et["id"], make_judge_headers())
    validate_error(res, "ERR_NOT_ELIGIBLE_FOR_TERMINATION")
    sup_after = validate_success(api.get_supervisee(sup["id"], oh), 200)
    assert sup_after["status"] == "ACTIVE"


# ─── Corner: endpoints / early_termination_grant_eligible_succeeds ───
def test_early_termination_grant_eligible_succeeds(api):
    """PRD §3.9: "A petition is eligible exactly when all three of the following
    hold: percent_served is at least 50 ...; the restitution_balance_cents is
    exactly zero ...; and the count of violations in FILED or APPEALED status is
    zero."
    PRD §3.9: "Granting drives the supervisee from ACTIVE to the terminal
    TERMINATED_EARLY, sets the petition's status to GRANTED"

    Start 2025-01-01, 24-month term, requested 2026-01-01 -> 12 months -> 50%;
    restitution clear; no violations: the petition is eligible and grant succeeds.

    Design: Corner/endpoints/early_termination_grant_eligible_succeeds
    """
    officer, sup = setup_active_supervisee(
        level_total=10, ordered_term_months=24,
        supervision_start_date="2025-01-01T00:00:00.000Z",
    )
    oh = make_officer_headers(officer["id"])
    et = file_early_termination(sup["id"], officer["id"], "2026-01-01T00:00:00.000Z")
    assert et["eligibility"]["eligible"] is True

    granted = validate_success(
        api.grant_early_termination(sup["id"], et["id"], make_judge_headers()), 200
    )
    assert granted["status"] == "GRANTED"
    sup_after = validate_success(api.get_supervisee(sup["id"], oh), 200)
    assert sup_after["status"] == "TERMINATED_EARLY"


# ─── Corner: validations / complete_with_outstanding_balance_rejected ───
def test_complete_with_outstanding_fee_balance_rejected(api):
    """PRD §3.7: "completion requires that the case be fully squared away: both the
    restitution_balance_cents and the fee_balance_cents must be exactly zero ...
    If either balance is non-zero, completion is rejected with
    ERR_OUTSTANDING_BALANCE (HTTP 409)"

    A supervisee with an OPEN 5000 FEE cannot complete; status stays ACTIVE.

    Design: Corner/validations/complete_with_outstanding_balance_rejected
    """
    officer, sup = setup_active_supervisee(level_total=10)
    oh = make_officer_headers(officer["id"])
    add_obligation(sup["id"], officer["id"], "FEE", 5000)
    res = api.complete_supervisee(sup["id"], make_judge_headers())
    validate_error(res, "ERR_OUTSTANDING_BALANCE")
    sup_after = validate_success(api.get_supervisee(sup["id"], oh), 200)
    assert sup_after["status"] == "ACTIVE"


# ─── Corner: rbac / officer_cannot_sustain_violation ───
def test_officer_cannot_sustain_violation(api):
    """PRD §2.1: "When the headers are present but the declared role is not
    permitted to invoke the requested operation, the request is rejected with
    ERR_UNAUTHORIZED (HTTP 403)."
    PRD §3.5: "Adjudication is reserved to the judiciary and is governed by a
    strict separation between filing and finding. A SupervisingJudge may sustain a
    FILED violation"

    Sustain is reserved to the judiciary; an Officer invoking it is denied.

    Design: Corner/rbac/officer_cannot_sustain_violation
    """
    officer, sup = setup_active_supervisee(level_total=10)
    oh = make_officer_headers(officer["id"])
    v = file_violation(sup["id"], officer["id"], "TECHNICAL")
    res = api.sustain_violation(sup["id"], v["id"], oh)
    validate_error(res, "ERR_UNAUTHORIZED")


# ─── Corner: rbac / missing_auth_headers_unauthenticated ───
def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "Every request to the API must be authenticated by two mandatory
    HTTP headers ... If either header is missing or empty, the request is rejected
    with ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    res = api.create_officer(
        create_officer_payload(full_name="NoAuth", badge_number="B-NOAUTH-1",
                               role_type="PROBATION"),
        {},
    )
    validate_error(res, "ERR_UNAUTHENTICATED")


# ─── Corner: rbac / segregation_filer_cannot_sustain ───
def test_segregation_of_duties_filer_cannot_sustain(api):
    """PRD §3.5: "the acting judge — identified by X-User-ID — must differ from the
    violation's filed_by_officer_id. This is the segregation-of-duties rule ... If
    the sustaining actor equals the violation's filed_by_officer_id, the request is
    rejected with ERR_SEGREGATION_OF_DUTIES (HTTP 409)."

    A judge whose X-User-ID equals the filing officer's id cannot sustain.

    Design: Corner/rbac/segregation_filer_cannot_sustain
    """
    officer, sup = setup_active_supervisee(level_total=10)
    v = file_violation(sup["id"], officer["id"], "TECHNICAL")
    # Judge acts with the filing officer's id -> segregation violated.
    res = api.sustain_violation(sup["id"], v["id"], make_judge_headers(officer["id"]))
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES")
