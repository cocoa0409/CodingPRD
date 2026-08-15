"""Composite setup helpers for multi-step test prerequisites (PRD §3 workflows).

Setup calls use get_success_data() so precondition failures surface as clear
"Setup step failed" errors. Every helper builds its preconditions from scratch —
each test runs against a fresh server with an empty database and the logical
clock at its 2026-08-01T00:00:00Z startup default.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_assessment_payload,
    create_client_payload,
    create_grant_application_payload,
    create_grant_fund_payload,
    create_event_registration_payload,
    create_line_item_payload,
    create_outreach_event_payload,
    create_partner_agency_payload,
    create_pantry_item_payload,
    create_referral_payload,
    create_shelter_bed_payload,
    create_shelter_stay_payload,
    create_staff_payload,
)
from .test_users import (
    TEST_USERS,
    make_benefits_counselor_headers,
    make_client_headers,
    make_grant_reviewer_headers,
    make_hub_admin_headers,
    make_intake_coordinator_headers,
    make_pantry_staff_headers,
    make_shelter_coordinator_headers,
)

ADMIN = TEST_USERS["hub_admin_headers"]
ANON = TEST_USERS["anonymous_headers"]


# ─── Tier 1: atomic entity creation ─────────────────────────────────────────

def create_coordinator(email="coord@hub.test"):
    """Register an INTAKE_COORDINATOR. Returns (staff, headers)."""
    staff = get_success_data(
        api_client.create_staff(
            create_staff_payload(full_name="C Co", email=email,
                                 staff_role="INTAKE_COORDINATOR"),
            ADMIN,
        )
    )
    return staff, make_intake_coordinator_headers(staff["id"])


def create_pantry_staff(email="pantry@hub.test"):
    """Register a PANTRY_STAFF member. Returns (staff, headers)."""
    staff = get_success_data(
        api_client.create_staff(
            create_staff_payload(full_name="P Pa", email=email,
                                 staff_role="PANTRY_STAFF"),
            ADMIN,
        )
    )
    return staff, make_pantry_staff_headers(staff["id"])


def create_counselor(email="bene@hub.test", full_name="B Be"):
    """Register a BENEFITS_COUNSELOR. Returns (staff, headers)."""
    staff = get_success_data(
        api_client.create_staff(
            create_staff_payload(full_name=full_name, email=email,
                                 staff_role="BENEFITS_COUNSELOR"),
            ADMIN,
        )
    )
    return staff, make_benefits_counselor_headers(staff["id"])


def create_reviewer(email="rev@hub.test", full_name="R Re"):
    """Register a GRANT_REVIEWER. Returns (staff, headers)."""
    staff = get_success_data(
        api_client.create_staff(
            create_staff_payload(full_name=full_name, email=email,
                                 staff_role="GRANT_REVIEWER"),
            ADMIN,
        )
    )
    return staff, make_grant_reviewer_headers(staff["id"])


def create_shelter_coordinator(email="shelter@hub.test"):
    """Register a SHELTER_COORDINATOR. Returns (staff, headers)."""
    staff = get_success_data(
        api_client.create_staff(
            create_staff_payload(full_name="S Sh", email=email,
                                 staff_role="SHELTER_COORDINATOR"),
            ADMIN,
        )
    )
    return staff, make_shelter_coordinator_headers(staff["id"])


def register_client(**overrides):
    """Self-register a client via Anonymous. Returns the INTAKE_PENDING client."""
    return get_success_data(
        api_client.create_client(create_client_payload(**overrides), ANON)
    )


# ─── Tier 1b: intake pipeline ────────────────────────────────────────────────

def create_draft_assessment(client_id, coord_headers, **overrides):
    return get_success_data(
        api_client.create_assessment(
            client_id, create_assessment_payload(**overrides), coord_headers
        )
    )


def submit_assessment(client_id, assessment_id, coord_headers):
    return get_success_data(
        api_client.submit_assessment(client_id, assessment_id, coord_headers)
    )


def verify_assessment(client_id, assessment_id, coord_headers, expected_client_version):
    return get_success_data(
        api_client.verify_assessment(
            client_id,
            assessment_id,
            {"expected_client_version": expected_client_version},
            coord_headers,
        )
    )


def create_active_client(coord_headers, assessment_overrides=None, client_overrides=None):
    """Register a client and carry one assessment through DRAFT -> SUBMITTED ->
    VERIFIED. Returns (client, assessment, client_headers) with the client
    re-fetched post-verification (ACTIVE)."""
    client = register_client(**(client_overrides or {}))
    assessment = create_draft_assessment(
        client["id"], coord_headers, **(assessment_overrides or {})
    )
    submit_assessment(client["id"], assessment["id"], coord_headers)
    verify_assessment(
        client["id"], assessment["id"], coord_headers,
        expected_client_version=client["version"],
    )
    refreshed = get_success_data(api_client.get_client(client["id"], coord_headers))
    return refreshed, assessment, make_client_headers(client["id"])


def create_shelter_eligible_client(coord_headers, alias="sh-client", **overrides):
    """ACTIVE client whose VERIFIED assessment is housing-insecure (HOMELESS)."""
    merged = dict(
        household_size=1, monthly_income_cents=0, housing_status="HOMELESS",
        dependents_under_18=0, receives_snap=False, receives_childcare_subsidy=False,
        food_insecurity_score=6, consent_confidential=True,
    )
    merged.update(overrides)
    return create_active_client(
        coord_headers,
        assessment_overrides=merged,
        client_overrides={"alias_name": alias, "contact_channel": "NONE",
                          "population_type": "COMMUNITY_RESIDENT"},
    )


# ─── Tier 2: domain scenario bundles ─────────────────────────────────────────

def create_item(item_name="Test Item", admin_headers=ADMIN, **overrides):
    return get_success_data(
        api_client.create_pantry_item(
            create_pantry_item_payload(item_name=item_name, **overrides),
            admin_headers,
        )
    )


def setup_pantry_scenario(client_alias="pantry-client", assessment_overrides=None,
                          item_name="Pantry Item", item_overrides=None):
    """Coordinator + pantry staff + ACTIVE client (default hh=1, allotment 30)
    + one pantry item. Returns dict of the pieces."""
    _, coord = create_coordinator()
    _, pantry = create_pantry_staff()
    defaults = dict(
        household_size=1, monthly_income_cents=50000, housing_status="STABLE",
        dependents_under_18=0, receives_snap=False, receives_childcare_subsidy=False,
        food_insecurity_score=1, consent_confidential=True,
    )
    defaults.update(assessment_overrides or {})
    client, assessment, client_headers = create_active_client(
        coord, assessment_overrides=defaults,
        client_overrides={"alias_name": client_alias},
    )
    item = create_item(item_name, **(item_overrides or {}))
    return {
        "coord_headers": coord,
        "pantry_headers": pantry,
        "client": client,
        "client_headers": client_headers,
        "assessment": assessment,
        "item": item,
    }


def create_agency(agency_name="Test Agency", **overrides):
    return get_success_data(
        api_client.create_partner_agency(
            create_partner_agency_payload(agency_name=agency_name, **overrides),
            ADMIN,
        )
    )


def create_fund(fund_name="Test Fund", **overrides):
    return get_success_data(
        api_client.create_grant_fund(
            create_grant_fund_payload(fund_name=fund_name, **overrides),
            ADMIN,
        )
    )


def create_bed(shelter_headers, site="Haven", label="B1", **overrides):
    return get_success_data(
        api_client.create_shelter_bed(
            create_shelter_bed_payload(shelter_site=site, bed_label=label, **overrides),
            shelter_headers,
        )
    )


def create_open_event(title="Event", admin_headers=ADMIN, **overrides):
    """Create an event and open it for registration. Returns OPEN event."""
    event = get_success_data(
        api_client.create_outreach_event(
            create_outreach_event_payload(title=title, **overrides),
            admin_headers,
        )
    )
    return get_success_data(api_client.open_event(event["id"], admin_headers))


# ─── Tier 3: lifecycle shortcuts ─────────────────────────────────────────────

def set_clock(to_iso8601):
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    )


def run_sweeps():
    return get_success_data(api_client.run_sweeps(ADMIN))


def checkin_visit_with_line(pantry_headers, client_id, item_id, quantity):
    """Check the client in and add one line of `quantity` units of the item.
    Returns (visit, line_item)."""
    visit = get_success_data(api_client.check_in_pantry_visit(client_id, pantry_headers))
    line = get_success_data(
        api_client.add_line_item(
            visit["id"], create_line_item_payload(item_id, quantity), pantry_headers
        )
    )
    return visit, line


def checkout(pantry_headers, visit_id):
    return get_success_data(api_client.checkout_visit(visit_id, pantry_headers))


def create_draft_grant(client_id, fund_id, creator_headers, **overrides):
    return get_success_data(
        api_client.create_grant_application(
            client_id, create_grant_application_payload(fund_id, **overrides),
            creator_headers,
        )
    )


def submit_grant(grant_id, submitter_headers):
    return get_success_data(api_client.submit_grant_application(grant_id, submitter_headers))


def create_submitted_grant(client, fund, submitter_headers=None, **overrides):
    """DRAFT -> SUBMITTED. Submitter defaults to the client themself."""
    submitter_headers = submitter_headers or make_client_headers(client["id"])
    grant = create_draft_grant(client["id"], fund["id"], submitter_headers, **overrides)
    submitted = submit_grant(grant["id"], submitter_headers)
    return submitted


def create_under_review_grant(client, fund, reviewer_headers, **overrides):
    """SUBMITTED application claimed by the reviewer. Returns the UNDER_REVIEW grant."""
    submitted = create_submitted_grant(client, fund, **overrides)
    return get_success_data(api_client.begin_review(submitted["id"], reviewer_headers))


def create_approved_grant(client, fund, reviewer_headers, **overrides):
    """UNDER_REVIEW -> APPROVED with a current fund version read. Returns
    (approved_grant, fund_after)."""
    under_review = create_under_review_grant(client, fund, reviewer_headers, **overrides)
    fund_now = get_success_data(api_client.get_grant_fund(fund["id"], reviewer_headers))
    approved = get_success_data(
        api_client.approve_grant(
            under_review["id"],
            {"expected_fund_version": fund_now["version"]},
            reviewer_headers,
        )
    )
    fund_after = get_success_data(api_client.get_grant_fund(fund["id"], reviewer_headers))
    return approved, fund_after


def create_disbursed_grant(client, fund, reviewer_headers, admin_headers=None, **overrides):
    """Full pipeline through DISBURSED. admin_headers defaults to an operator id
    distinct from the reviewer's staff id (two-person rule)."""
    admin_headers = admin_headers or make_hub_admin_headers("admin-9")
    approved, _ = create_approved_grant(client, fund, reviewer_headers, **overrides)
    disbursed = get_success_data(api_client.disburse_grant(approved["id"], admin_headers))
    fund_after = get_success_data(api_client.get_grant_fund(fund["id"], reviewer_headers))
    return disbursed, fund_after


def create_sent_referral(client, agency, sender_headers, **overrides):
    """INITIATED -> SENT. Returns the SENT referral."""
    referral = get_success_data(
        api_client.create_referral(
            client["id"], create_referral_payload(agency["id"], **overrides),
            sender_headers,
        )
    )
    return get_success_data(api_client.send_referral(referral["id"], sender_headers))


def create_reserved_stay(client_id, bed_id, shelter_headers, check_in_date="2026-08-10",
                         planned_nights=2):
    return get_success_data(
        api_client.create_shelter_stay(
            client_id,
            create_shelter_stay_payload(
                bed_id, check_in_date=check_in_date, planned_nights=planned_nights
            ),
            shelter_headers,
        )
    )


def register_client_for_event(event_id, client_id, actor_headers=None, **overrides):
    actor_headers = actor_headers or make_client_headers(client_id)
    return get_success_data(
        api_client.register_for_event(
            event_id, create_event_registration_payload(client_id, **overrides),
            actor_headers,
        )
    )


# ─── Tier 4: threshold / accumulation targeting ──────────────────────────────

def setup_exhausted_fund_with_queued_grant(allocated_cents=300000, award_cents=150000):
    """Two ACTIVE clients each approved for half the fund so the fund flips
    EXHAUSTED, plus a third client whose submission parks QUEUED.
    Returns dict with fund, reviewer headers, queued grant, and the two
    approved grant ids."""
    _, coord = create_coordinator()
    _, reviewer = create_reviewer()
    client_a, _, _ = create_active_client(
        coord, client_overrides={"alias_name": "c-a"},
    )
    client_b, _, _ = create_active_client(
        coord,
        assessment_overrides=dict(
            household_size=2, monthly_income_cents=100000, housing_status="STABLE",
            dependents_under_18=1, receives_snap=False, receives_childcare_subsidy=False,
            food_insecurity_score=3, consent_confidential=True,
        ),
        client_overrides={"alias_name": "c-b", "contact_channel": "SMS"},
    )
    fund = create_fund("FY26Q1", allocated_cents=allocated_cents)
    app_a, fund_mid = create_approved_grant(
        client_a, fund, reviewer, category="RENT", requested_cents=award_cents,
        hardship_statement="a",
    )
    app_b, fund_exhausted = create_approved_grant(
        client_b, fund, reviewer, category="MEDICAL", requested_cents=award_cents,
        hardship_statement="b",
    )
    client_c, _, client_c_headers = create_active_client(
        coord,
        assessment_overrides=dict(
            household_size=1, monthly_income_cents=40000, housing_status="UNSTABLE",
            dependents_under_18=0, receives_snap=False, receives_childcare_subsidy=False,
            food_insecurity_score=5, consent_confidential=True,
        ),
        client_overrides={"alias_name": "c-c", "population_type": "ENROLLED_STUDENT",
                          "enrolled_credits": 9},
    )
    grant_c = create_draft_grant(
        client_c["id"], fund["id"], client_c_headers,
        category="FOOD", requested_cents=60000, hardship_statement="c",
    )
    queued_c = submit_grant(grant_c["id"], client_c_headers)
    return {
        "coord_headers": coord,
        "reviewer_headers": reviewer,
        "fund": fund_exhausted,
        "app_a": app_a,
        "app_b": app_b,
        "queued_grant": queued_c,
        "client_c": client_c,
    }


def setup_client_at_lifetime_cap():
    """Client with two DISBURSED 150000 awards (lifetime room exhausted) and a
    third application UNDER_REVIEW requesting 50000 against a fund that still
    holds 200000 committed-basis. Returns dict of the pieces."""
    _, coord = create_coordinator()
    _, reviewer = create_reviewer()
    client, _, _ = create_active_client(coord, client_overrides={"alias_name": "cap"})
    fund = create_fund("FY26-cap", allocated_cents=500000)
    admin = make_hub_admin_headers("admin-9")
    create_disbursed_grant(
        client, fund, reviewer, admin_headers=admin,
        category="RENT", requested_cents=150000, hardship_statement="one",
    )
    create_disbursed_grant(
        client, fund, reviewer, admin_headers=admin,
        category="RENT", requested_cents=150000, hardship_statement="two",
    )
    app3 = create_under_review_grant(
        client, fund, reviewer,
        category="FOOD", requested_cents=50000, hardship_statement="three",
    )
    fund_now = get_success_data(api_client.get_grant_fund(fund["id"], reviewer))
    return {
        "coord_headers": coord,
        "reviewer_headers": reviewer,
        "client": client,
        "fund": fund_now,
        "app3": app3,
    }


# ─── Tier 5: terminal / late-lifecycle states ────────────────────────────────

def setup_disbursed_grant_scenario(allocated_cents=500000, requested_cents=100000,
                                   fund_name="FY26-t"):
    """Application DISBURSED by an admin distinct from the reviewer.
    Returns dict of the pieces."""
    _, coord = create_coordinator()
    _, reviewer = create_reviewer()
    client, _, _ = create_active_client(coord, client_overrides={"alias_name": "td"})
    fund = create_fund(fund_name, allocated_cents=allocated_cents)
    disbursed, fund_after = create_disbursed_grant(
        client, fund, reviewer, admin_headers=make_hub_admin_headers("admin-9"),
        category="MEDICAL", requested_cents=requested_cents, hardship_statement="rx",
    )
    return {
        "coord_headers": coord,
        "reviewer_headers": reviewer,
        "client": client,
        "fund": fund_after,
        "grant": disbursed,
    }
