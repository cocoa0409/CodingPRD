"""Composite setup helpers — multi-step preconditions for PRD-state tests.

Every fixture builds its preconditions from scratch via PRD-declared endpoints.
Fixtures use `get_success_data` (lenient validator) so that a setup failure
surfaces as a clear "Setup failed" assertion, not a confusing inner error.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_default_notice_payload,
    create_education_completion_payload,
    create_education_course_payload,
    create_household_payload,
    create_income_certification_payload,
    create_lease_payload,
    create_program_payload,
    create_resale_listing_payload,
    create_unit_payload,
    create_waitlist_entry_payload,
)
from .test_users import TEST_USERS, make_household_headers


# ---------------------------------------------------------------------------
# Role header shortcuts
# ---------------------------------------------------------------------------

def _pa():
    return TEST_USERS["platform_admin_headers"]


def _pga():
    return TEST_USERS["program_admin_headers"]


def _is():
    return TEST_USERS["intake_specialist_headers"]


def _co():
    return TEST_USERS["compliance_officer_headers"]


def _lm():
    return TEST_USERS["lease_manager_headers"]


def _insp():
    return TEST_USERS["inspector_headers"]


# ---------------------------------------------------------------------------
# Tier 1: Single-entity setups
# ---------------------------------------------------------------------------

def setup_program(**overrides) -> dict:
    """Create a program. Returns program dict."""
    resp = api_client.create_program(create_program_payload(**overrides), _pa())
    return get_success_data(resp)


def setup_household(program_id: str, **overrides) -> dict:
    """Create a household in PENDING state. Returns household dict."""
    resp = api_client.create_household(
        program_id, create_household_payload(**overrides), _is()
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: Household certification flows
# ---------------------------------------------------------------------------

def setup_certified_household(
    program_id: str,
    *,
    verified_income_cents: int = 7_000_000,
    household_size: int = 4,
    tax_year: int = 2025,
    legal_name: str = "Buyer",
) -> tuple[dict, dict]:
    """Create household + income cert + move to UNDER_REVIEW + approve.

    Returns (household, approved_cert).
    Post-condition: household.ami_pct is set; eligibility_status re-evaluated
    (ELIGIBLE when AMI fits and education is complete).
    """
    hh = setup_household(
        program_id,
        legal_name=legal_name,
        household_size=household_size,
        annual_gross_income_cents=verified_income_cents,
    )
    cert = get_success_data(
        api_client.create_income_certification(
            program_id,
            hh["id"],
            create_income_certification_payload(
                tax_year=tax_year,
                reported_annual_income_cents=verified_income_cents,
                verified_annual_income_cents=verified_income_cents,
                household_size_at_cert=household_size,
            ),
            _is(),
        )
    )
    get_success_data(
        api_client.start_review_income_certification(
            program_id, hh["id"], cert["id"], _co()
        )
    )
    cert = get_success_data(
        api_client.approve_income_certification(
            program_id, hh["id"], cert["id"], _co()
        )
    )
    hh = get_success_data(api_client.get_household(program_id, hh["id"], _co()))
    return hh, cert


def setup_required_course(program_id: str, **overrides) -> dict:
    """Create a required education course. Returns course dict."""
    resp = api_client.create_education_course(
        program_id,
        create_education_course_payload(is_required=True, **overrides),
        _pga(),
    )
    return get_success_data(resp)


def setup_education_completed_household(
    program_id: str,
    household_id: str,
    course_id: str,
    *,
    completed_at: str = "2026-04-01T00:00:00Z",
    score_pct: float = 0.9,
) -> dict:
    """Record a completion for the household on the given course."""
    resp = api_client.create_education_completion(
        program_id,
        household_id,
        create_education_completion_payload(
            course_id=course_id, completed_at=completed_at, score_pct=score_pct
        ),
        _is(),
    )
    return get_success_data(resp)


def setup_eligible_household(
    program_id: str,
    *,
    verified_income_cents: int = 7_000_000,
    household_size: int = 4,
    legal_name: str = "Buyer",
    course_id: str | None = None,
) -> tuple[dict, dict, dict]:
    """Create household, approve cert, and complete education so the household
    transitions to ELIGIBLE.

    PRD 3.2: at approval time the household must hold an unexpired completion
    for EVERY required EducationCourse in the program, and the activation-time
    education check (PRD 3.3) re-evaluates every required course live. This
    fixture therefore completes every required OFFERED course that exists in
    the program, and only creates a new course when the program has none —
    piling up one new required course per household would leave every other
    household short of the full required set.

    Returns (household, cert, course)."""
    courses = get_success_data(api_client.list_education_courses(program_id, _pga()))
    required = [
        c for c in courses
        if c.get("is_required") and c.get("status") == "OFFERED"
    ]
    if course_id is not None:
        course = get_success_data(
            api_client.get_education_course(program_id, course_id, _pga())
        )
        if all(c["id"] != course["id"] for c in required):
            required.append(course)
    else:
        if not required:
            required = [setup_required_course(program_id)]
        course = required[0]

    # Education completion BEFORE cert approval so that at approval time the
    # household's education is already in place.
    hh = setup_household(
        program_id,
        legal_name=legal_name,
        household_size=household_size,
        annual_gross_income_cents=verified_income_cents,
    )
    for c in required:
        setup_education_completed_household(program_id, hh["id"], c["id"])

    cert = get_success_data(
        api_client.create_income_certification(
            program_id,
            hh["id"],
            create_income_certification_payload(
                reported_annual_income_cents=verified_income_cents,
                verified_annual_income_cents=verified_income_cents,
                household_size_at_cert=household_size,
            ),
            _is(),
        )
    )
    get_success_data(
        api_client.start_review_income_certification(
            program_id, hh["id"], cert["id"], _co()
        )
    )
    cert = get_success_data(
        api_client.approve_income_certification(
            program_id, hh["id"], cert["id"], _co()
        )
    )
    hh = get_success_data(api_client.get_household(program_id, hh["id"], _co()))
    return hh, cert, course


# ---------------------------------------------------------------------------
# Tier 3: Lease activation flows
# ---------------------------------------------------------------------------

def setup_unit(program_id: str, **overrides) -> dict:
    """Create a unit in VACANT status."""
    resp = api_client.create_unit(
        program_id, create_unit_payload(**overrides), _pga()
    )
    return get_success_data(resp)


def setup_draft_lease(
    program_id: str,
    unit_id: str,
    household_id: str,
    *,
    start_date: str = "2026-05-01T00:00:00Z",
    purchase_price_cents: int = 20_000_000,
) -> dict:
    """Create a draft ground lease."""
    resp = api_client.create_lease(
        program_id,
        unit_id,
        create_lease_payload(
            household_id=household_id,
            start_date=start_date,
            purchase_price_cents=purchase_price_cents,
        ),
        _lm(),
    )
    return get_success_data(resp)


def setup_active_lease(
    program_id: str,
    *,
    household_income_cents: int = 7_000_000,
    household_size: int = 4,
    purchase_price_cents: int = 20_000_000,
    start_date: str = "2026-05-01T00:00:00Z",
    unit_overrides: dict | None = None,
) -> tuple[dict, dict, dict, dict]:
    """Build an ACTIVE ground lease.

    Returns (program, unit, household, lease).
    Caller is expected to have already created the program.
    """
    program = get_success_data(api_client.get_program(program_id, _pga()))
    unit = setup_unit(program_id, **(unit_overrides or {}))
    hh, _cert, _course = setup_eligible_household(
        program_id,
        verified_income_cents=household_income_cents,
        household_size=household_size,
    )
    lease = setup_draft_lease(
        program_id,
        unit["id"],
        hh["id"],
        start_date=start_date,
        purchase_price_cents=purchase_price_cents,
    )
    unit_now = get_success_data(api_client.get_unit(program_id, unit["id"], _lm()))
    lease = get_success_data(
        api_client.activate_lease(
            program_id,
            unit["id"],
            lease["id"],
            {"expected_unit_version": unit_now["version"]},
            _lm(),
        )
    )
    hh = get_success_data(api_client.get_household(program_id, hh["id"], _lm()))
    unit = get_success_data(api_client.get_unit(program_id, unit["id"], _lm()))
    return program, unit, hh, lease


def setup_listed_resale(
    program_id: str,
    *,
    appraisal_at_listing_cents: int = 25_000_000,
    seller_income_cents: int = 7_000_000,
    purchase_price_cents: int = 20_000_000,
    unit_overrides: dict | None = None,
) -> tuple[dict, dict, dict, dict, dict]:
    """Seller on ACTIVE lease; opens a resale listing in OPEN.

    Returns (program, unit, seller_household, seller_lease, listing).
    """
    program, unit, hh_s, lease_s = setup_active_lease(
        program_id,
        household_income_cents=seller_income_cents,
        purchase_price_cents=purchase_price_cents,
        unit_overrides=unit_overrides,
    )
    listing = get_success_data(
        api_client.create_resale_listing(
            program_id,
            unit["id"],
            create_resale_listing_payload(
                seller_lease_id=lease_s["id"],
                appraisal_at_listing_cents=appraisal_at_listing_cents,
            ),
            _lm(),
        )
    )
    unit = get_success_data(api_client.get_unit(program_id, unit["id"], _lm()))
    return program, unit, hh_s, lease_s, listing


def setup_matched_resale(
    program_id: str,
    *,
    buyer_income_cents: int = 6_000_000,
    buyer_size: int = 4,
    desired_bedrooms: int = 3,
    max_price_cents: int = 50_000_000,
    **listing_kwargs,
) -> tuple[dict, dict, dict, dict, dict, dict, dict]:
    """Build a MATCHED resale listing.

    Returns (program, unit, seller_hh, seller_lease, listing, buyer_hh, buyer_entry).
    """
    program, unit, hh_s, lease_s, listing = setup_listed_resale(
        program_id, **listing_kwargs
    )
    hh_b, _cert_b, _course = setup_eligible_household(
        program_id,
        verified_income_cents=buyer_income_cents,
        household_size=buyer_size,
        legal_name="Buyer",
    )
    entry = get_success_data(
        api_client.create_waitlist_entry(
            program_id,
            hh_b["id"],
            create_waitlist_entry_payload(
                desired_bedrooms=desired_bedrooms, max_price_cents=max_price_cents
            ),
            _is(),
        )
    )
    # Run matching with the fresh listing version.
    listing_now = get_success_data(
        api_client.get_resale_listing(program_id, unit["id"], listing["id"], _lm())
    )
    listing = get_success_data(
        api_client.run_matching(
            program_id,
            unit["id"],
            listing["id"],
            {"expected_listing_version": listing_now["version"]},
            _lm(),
        )
    )
    entry = get_success_data(
        api_client.get_waitlist_entry(program_id, entry["id"], _lm())
    )
    return program, unit, hh_s, lease_s, listing, hh_b, entry


def setup_under_contract_resale(
    program_id: str, **kwargs
) -> tuple[dict, dict, dict, dict, dict, dict, dict]:
    """Build an UNDER_CONTRACT resale listing.

    Returns (program, unit, seller_hh, seller_lease, listing, buyer_hh, buyer_entry).
    """
    program, unit, hh_s, lease_s, listing, hh_b, entry = setup_matched_resale(
        program_id, **kwargs
    )
    listing_now = get_success_data(
        api_client.get_resale_listing(program_id, unit["id"], listing["id"], _lm())
    )
    listing = get_success_data(
        api_client.open_contract(
            program_id,
            unit["id"],
            listing["id"],
            {"expected_listing_version": listing_now["version"]},
            _lm(),
        )
    )
    return program, unit, hh_s, lease_s, listing, hh_b, entry


def setup_defaulted_lease(
    program_id: str,
    *,
    notice_kind: str = "FEE_ARREARS",
    amount_due_cents: int = 50_000,
    **lease_kwargs,
) -> tuple[dict, dict, dict, dict, dict]:
    """Build an ACTIVE lease and issue one OPEN DefaultNotice against it.

    Returns (program, unit, household, lease, notice).
    After setup: lease.status == IN_DEFAULT, unit.occupancy_status == IN_DEFAULT.
    """
    program, unit, hh, lease = setup_active_lease(program_id, **lease_kwargs)
    notice = get_success_data(
        api_client.create_default_notice(
            program_id,
            unit["id"],
            lease["id"],
            create_default_notice_payload(
                notice_kind=notice_kind, amount_due_cents=amount_due_cents
            ),
            _lm(),
        )
    )
    lease = get_success_data(
        api_client.get_lease(program_id, unit["id"], lease["id"], _lm())
    )
    # Re-fetch the unit too: issuing the notice transitioned it to IN_DEFAULT.
    unit = get_success_data(api_client.get_unit(program_id, unit["id"], _lm()))
    return program, unit, hh, lease, notice


__all__ = [
    "setup_program",
    "setup_household",
    "setup_certified_household",
    "setup_required_course",
    "setup_education_completed_household",
    "setup_eligible_household",
    "setup_unit",
    "setup_draft_lease",
    "setup_active_lease",
    "setup_listed_resale",
    "setup_matched_resale",
    "setup_under_contract_resale",
    "setup_defaulted_lease",
]
