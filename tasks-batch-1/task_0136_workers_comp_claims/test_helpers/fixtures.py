"""Composite setup helpers.

These encapsulate the multi-step preambles the claims pipeline requires so tests
can focus on the assertion under test. Every step uses get_success_data() (the
lenient validator) so a broken setup surfaces as a clear "Setup step failed".

Identity threading: the Employer role is entity-backed. After an employer is
created, any Employer-role call (worker registration done as Employer, claim
opening done as Employer, all RTW-offer operations) MUST carry that employer's id
via make_employer_headers(employer_id). PlatformAdmin / ClaimsAdjuster /
MedicalReviewer are opaque, so their shared constants are fine except where a test
explicitly needs a controlled operator id for separation-of-duties.
"""
import uuid

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_employer_headers,
    make_claims_adjuster_headers,
    make_medical_reviewer_headers,
)
from . import factories as f

ADMIN = TEST_USERS["platform_admin_headers"]
ADJUSTER = TEST_USERS["claims_adjuster_headers"]
REVIEWER = TEST_USERS["medical_reviewer_headers"]


def _unique_policy_number(prefix="P"):
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


# ─── Clock helper ─────────────────────────────────────

def set_clock(to_iso8601):
    """Set the server's logical 'now' (PlatformAdmin-only test-driving)."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ─── Tier 1/2: base onboarding ────────────────────────

def setup_employer(legal_name="Test Employer", state_code="CA"):
    """Create an employer. Returns the employer dict."""
    return get_success_data(
        api_client.create_employer(
            f.create_employer_payload(legal_name=legal_name, state_code=state_code), ADMIN
        )
    )


def setup_policy(employer_id, manual_premium_cents=5_000_000, **overrides):
    """Create a policy for an employer with a unique policy_number."""
    payload = f.create_policy_payload(
        employer_id,
        policy_number=_unique_policy_number("POL"),
        manual_premium_cents=manual_premium_cents,
        **overrides,
    )
    return get_success_data(api_client.create_policy(payload, ADMIN))


def setup_worker(employer_id, gross_wages_cents=7_800_000, weeks_worked=52, **overrides):
    """Create a worker (AWW computed at creation)."""
    payload = f.create_worker_payload(
        employer_id, gross_wages_cents=gross_wages_cents, weeks_worked=weeks_worked, **overrides
    )
    return get_success_data(api_client.create_worker(payload, ADMIN))


def setup_employer_policy_worker(manual_premium_cents=5_000_000, gross_wages_cents=7_800_000,
                                 weeks_worked=52, state_code="CA"):
    """Active employer + one policy + one worker. Returns (employer, policy, worker)."""
    employer = setup_employer(state_code=state_code)
    policy = setup_policy(employer["id"], manual_premium_cents=manual_premium_cents)
    worker = setup_worker(employer["id"], gross_wages_cents=gross_wages_cents, weeks_worked=weeks_worked)
    return employer, policy, worker


# ─── Claim creation ──────────────────────────────────

def setup_reported_claim(disability_days=None, date_of_injury="2026-02-01T00:00:00Z",
                         gross_wages_cents=7_800_000, weeks_worked=52, manual_premium_cents=5_000_000):
    """Employer/policy/worker + a REPORTED claim.

    Returns a dict with employer, policy, worker, claim, and claim_version (the
    claim's version immediately after creation — the basis for the first OCC write).
    """
    employer, policy, worker = setup_employer_policy_worker(
        manual_premium_cents=manual_premium_cents,
        gross_wages_cents=gross_wages_cents,
        weeks_worked=weeks_worked,
    )
    payload = f.create_claim_payload(policy["id"], worker["id"], date_of_injury=date_of_injury)
    if disability_days is not None:
        payload["disability_days"] = disability_days
    claim = get_success_data(api_client.create_claim(payload, ADJUSTER))
    return {
        "employer": employer,
        "policy": policy,
        "worker": worker,
        "claim": claim,
        "claim_version": claim["version"],
    }


# ─── FROI lifecycle ──────────────────────────────────

def setup_acknowledged_froi(claim_id):
    """Create a FROI for the claim, transmit it, and acknowledge it. Returns the FROI dict."""
    froi = get_success_data(
        api_client.create_injury_report(f.create_injury_report_payload(claim_id, "FROI", "00"), ADJUSTER)
    )
    get_success_data(api_client.transmit_injury_report(froi["id"], ADJUSTER))
    froi = get_success_data(api_client.ack_injury_report(froi["id"], ADMIN))
    return froi


def setup_transmitted_froi(claim_id):
    """Create a FROI and transmit it but do NOT acknowledge. Returns the FROI dict (TRANSMITTED)."""
    froi = get_success_data(
        api_client.create_injury_report(f.create_injury_report_payload(claim_id, "FROI", "00"), ADJUSTER)
    )
    froi = get_success_data(api_client.transmit_injury_report(froi["id"], ADJUSTER))
    return froi


# ─── Wage statement / reserve ────────────────────────

def setup_wage_statement(claim_id, expected_claim_version, average_weekly_wage_cents=150_000):
    """File a wage statement; returns (wage_statement, new_claim_version)."""
    ws = get_success_data(
        api_client.create_wage_statement(
            f.create_wage_statement_payload(
                claim_id, expected_claim_version, average_weekly_wage_cents=average_weekly_wage_cents
            ),
            ADJUSTER,
        )
    )
    new_version = _current_claim_version(claim_id)
    return ws, new_version


def setup_reserve(claim_id, severity_tier="MODERATE", projected_weeks=12, adjuster_headers=ADJUSTER):
    """Create the claim's reserve. adjuster_headers lets a test pin which operator
    set the reserve (separation-of-duties). Returns the reserve dict."""
    return get_success_data(
        api_client.create_reserve(
            f.create_reserve_payload(claim_id, severity_tier=severity_tier, projected_weeks=projected_weeks),
            adjuster_headers,
        )
    )


def _current_claim_version(claim_id):
    claim = get_success_data(api_client.get_claim(claim_id, ADJUSTER))
    return claim["version"]


# ─── Tier 3: LOST_TIME pipelines ─────────────────────

def setup_lost_time_claim(disability_days=10, severity_tier="MODERATE", projected_weeks=12,
                          average_weekly_wage_cents=150_000, with_wage_statement=True,
                          gross_wages_cents=7_800_000, weeks_worked=52, date_of_injury="2026-02-01T00:00:00Z"):
    """Full preamble to an accepted LOST_TIME claim:
      employer/policy/worker -> claim(disability_days) -> FROI ack -> [wage statement]
      -> reserve -> accept(LOST_TIME).

    Returns a dict with employer, policy, worker, claim (the post-accept claim read),
    froi, reserve, wage_statement (or None), and claim_version (current).
    """
    ctx = setup_reported_claim(
        disability_days=disability_days,
        gross_wages_cents=gross_wages_cents,
        weeks_worked=weeks_worked,
        date_of_injury=date_of_injury,
    )
    claim_id = ctx["claim"]["id"]
    froi = setup_acknowledged_froi(claim_id)

    wage_statement = None
    if with_wage_statement:
        wage_statement, _ = setup_wage_statement(
            claim_id, _current_claim_version(claim_id), average_weekly_wage_cents=average_weekly_wage_cents
        )

    reserve = setup_reserve(claim_id, severity_tier=severity_tier, projected_weeks=projected_weeks)

    accepted = get_success_data(
        api_client.accept_claim(claim_id, {"disability_days": disability_days}, ADJUSTER)
    )

    return {
        "employer": ctx["employer"],
        "policy": ctx["policy"],
        "worker": ctx["worker"],
        "claim": accepted,
        "froi": froi,
        "reserve": reserve,
        "wage_statement": wage_statement,
        "claim_version": _current_claim_version(claim_id),
    }


def setup_medical_only_claim(date_of_injury="2026-02-01T00:00:00Z"):
    """Preamble to an accepted MEDICAL_ONLY claim (disability_days==0):
      employer/policy/worker -> claim -> FROI ack -> accept (no disability).

    Returns a dict with employer, policy, worker, claim (post-accept), froi.
    """
    ctx = setup_reported_claim(disability_days=None, date_of_injury=date_of_injury)
    claim_id = ctx["claim"]["id"]
    froi = setup_acknowledged_froi(claim_id)
    accepted = get_success_data(api_client.accept_claim(claim_id, {}, ADJUSTER))
    return {
        "employer": ctx["employer"],
        "policy": ctx["policy"],
        "worker": ctx["worker"],
        "claim": accepted,
        "froi": froi,
    }


# ─── Benefit payments ────────────────────────────────

def post_ttd_payment(claim_id):
    """Post a TTD benefit payment. Returns the payment dict."""
    return get_success_data(
        api_client.create_benefit_payment(f.create_benefit_payment_payload(claim_id, "TTD"), ADJUSTER)
    )


def setup_lost_time_with_posted_ttd(disability_days=10, projected_weeks=12,
                                    average_weekly_wage_cents=150_000):
    """LOST_TIME claim with one POSTED TTD payment already drawn down.

    Returns the setup_lost_time_claim context plus a 'payment' key.
    """
    ctx = setup_lost_time_claim(
        disability_days=disability_days,
        projected_weeks=projected_weeks,
        average_weekly_wage_cents=average_weekly_wage_cents,
    )
    ctx["payment"] = post_ttd_payment(ctx["claim"]["id"])
    return ctx


# ─── Impairment ratings ──────────────────────────────

def setup_proposed_rating(claim_id, whole_body_pct=15, rater_role="TREATING"):
    """Record a PROPOSED impairment rating. Returns the rating dict."""
    return get_success_data(
        api_client.create_impairment_rating(
            f.create_impairment_rating_payload(claim_id, whole_body_pct, rater_role), REVIEWER
        )
    )


def setup_disputed_rating(claim_id, whole_body_pct=15):
    """Record a PROPOSED TREATING rating then dispute it (cascades a SCHEDULED IME).
    Returns (rating, ime_order) where ime_order is the cascaded SCHEDULED IME."""
    rating = setup_proposed_rating(claim_id, whole_body_pct=whole_body_pct, rater_role="TREATING")
    rating = get_success_data(api_client.dispute_impairment_rating(rating["id"], ADJUSTER))
    ime_list, _ = _list_data(api_client.list_claim_ime_orders(claim_id, ADJUSTER))
    ime_order = ime_list[0] if ime_list else None
    return rating, ime_order


def setup_finalized_ime_rating(claim_id, whole_body_pct=15):
    """Record an IME rating and finalize it directly (PROPOSED->FINALIZED, claim->MMI).
    Returns the FINALIZED rating dict."""
    rating = setup_proposed_rating(claim_id, whole_body_pct=whole_body_pct, rater_role="IME")
    rating = get_success_data(api_client.finalize_impairment_rating(rating["id"], REVIEWER))
    return rating


# ─── IME orders ──────────────────────────────────────

def setup_scheduled_ime(claim_id, scheduled_start, scheduled_end, examiner_name="Dr A"):
    """Schedule an IME order. Returns the IME dict."""
    return get_success_data(
        api_client.create_ime_order(
            f.create_ime_order_payload(claim_id, scheduled_start, scheduled_end, examiner_name), ADJUSTER
        )
    )


# ─── RTW offers (entity-backed Employer identity) ─────

def setup_offered_rtw(claim_id, employer_id, light_duty_weekly_cents=90_000,
                      start_date="2026-03-01T00:00:00Z", end_date="2026-03-20T00:00:00Z"):
    """Create an OFFERED RTW offer as the owning Employer. Returns the offer dict."""
    headers = make_employer_headers(employer_id)
    return get_success_data(
        api_client.create_rtw_offer(
            f.create_rtw_offer_payload(claim_id, light_duty_weekly_cents, start_date, end_date), headers
        )
    )


def setup_accepted_rtw(claim_id, employer_id, light_duty_weekly_cents=90_000,
                       start_date="2026-03-01T00:00:00Z", end_date="2026-03-10T00:00:00Z"):
    """Create then accept an RTW offer as the owning Employer (clock must precede
    start_date when this runs). Returns the ACCEPTED offer dict."""
    headers = make_employer_headers(employer_id)
    offer = setup_offered_rtw(
        claim_id, employer_id, light_duty_weekly_cents=light_duty_weekly_cents,
        start_date=start_date, end_date=end_date,
    )
    return get_success_data(api_client.accept_rtw_offer(offer["id"], headers))


# ─── Reads ───────────────────────────────────────────

def _list_data(response):
    """Return (data_list, meta) from a list response, lenient."""
    body = response.json()
    return body.get("data", []), body.get("meta", {})


def read_claim(claim_id):
    return get_success_data(api_client.get_claim(claim_id, ADJUSTER))


def read_reserve(reserve_id):
    return get_success_data(api_client.get_reserve(reserve_id, ADJUSTER))


def read_employer(employer_id):
    return get_success_data(api_client.get_employer(employer_id, ADMIN))


def read_policy(policy_id):
    return get_success_data(api_client.get_policy(policy_id, ADMIN))


def read_rtw_offer(offer_id, employer_id):
    return get_success_data(api_client.get_rtw_offer(offer_id, make_employer_headers(employer_id)))
