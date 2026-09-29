"""Precondition builders.

The database is empty at the start of every test, so every precondition is built
here from published operations only -- there is no back door into storage. The
builders are layered:

* tier 0 -- the logical clock and the identity rows (developer, reviewers,
  property) that every later step needs;
* tier 1 -- an open project on that property;
* tier 2 -- cost line items and part applications, including the review walk
  that carries one part application from DRAFT to APPROVED;
* tier 3 -- a project certified through Part 1, Part 2 or Part 3, optionally
  placed in service;
* tier 4 -- investor interests, filed credit claims, covenants and recapture
  events on top of a certified project.

Every builder re-reads ``GET /projects/{id}`` before any write that carries
``expected_project_version``, because approvals bump the project version behind
the caller's back (PRD §2.7).
"""

from prd_bench_local_runner.testing import get_success_data

from . import constants, factories
from .test_users import (
    PLATFORM_ADMIN,
    make_compliance_monitor_headers,
    make_developer_headers,
    make_investor_admin_headers,
    make_nps_reviewer_headers,
    make_shpo_reviewer_headers,
)

MONITOR = make_compliance_monitor_headers()
ADMIN = PLATFORM_ADMIN


class Cast:
    """The people and the building a project needs before it can exist."""

    def __init__(self, developer, shpo_reviewer, nps_reviewer, property_row):
        self.developer = developer
        self.shpo_reviewer = shpo_reviewer
        self.nps_reviewer = nps_reviewer
        self.property = property_row

    @property
    def developer_id(self):
        return self.developer["id"]

    @property
    def shpo_reviewer_id(self):
        return self.shpo_reviewer["id"]

    @property
    def nps_reviewer_id(self):
        return self.nps_reviewer["id"]

    @property
    def property_id(self):
        return self.property["id"]

    @property
    def developer_headers(self):
        return make_developer_headers(self.developer_id)

    @property
    def shpo_headers(self):
        return make_shpo_reviewer_headers(self.shpo_reviewer_id)

    @property
    def nps_headers(self):
        return make_nps_reviewer_headers(self.nps_reviewer_id)


# ─── Tier 0: clock and identity rows ──────────────────


def set_clock(api, to_iso8601):
    """Move the logical clock forward (PRD §2.4)."""
    return get_success_data(api.set_clock(to_iso8601))


def create_developer(api, **overrides):
    return get_success_data(
        api.create_developer(ADMIN, **factories.developer_payload(**overrides))
    )


def create_reviewer(api, agency="SHPO", **overrides):
    return get_success_data(
        api.create_reviewer(ADMIN, **factories.reviewer_payload(agency, **overrides))
    )


def create_property(api, headers=None, **overrides):
    return get_success_data(
        api.create_property(
            headers or ADMIN, **factories.property_payload(**overrides)
        )
    )


def seed_cast(api, clock=constants.SEED_CLOCK_UTC, **property_overrides):
    """A developer, one reviewer per agency, and a listed property."""
    if clock is not None:
        set_clock(api, clock)
    return Cast(
        developer=create_developer(api),
        shpo_reviewer=create_reviewer(api, "SHPO"),
        nps_reviewer=create_reviewer(api, "NPS"),
        property_row=create_property(api, **property_overrides),
    )


# ─── Tier 1: an open project ──────────────────────────


def open_project(api, cast, property_id=None, **overrides):
    """Open a project on the cast's property (PRD §3.2)."""
    payload = factories.project_payload(
        cast.developer_id, property_id or cast.property_id, **overrides
    )
    return get_success_data(api.create_project(cast.developer_headers, **payload))


def read_project(api, cast, project_id):
    return get_success_data(api.get_project(project_id, cast.developer_headers))


def project_version(api, cast, project_id):
    """The current version, which every guarded write has to quote."""
    return read_project(api, cast, project_id)["version"]


# ─── Tier 2: costs, part applications, the review walk ─


def add_cost(api, cast, project_id, **overrides):
    """Record a cost line item (PRD §3.6)."""
    payload = factories.cost_line_item_payload(project_id, **overrides)
    return get_success_data(api.create_cost_line_item(cast.developer_headers, **payload))


def add_qre_cost(api, cast, project_id, amount_cents, **overrides):
    """Record a cost already classified as qualified at creation."""
    return add_cost(
        api,
        cast,
        project_id,
        amount_cents=amount_cents,
        classification=overrides.pop("classification", "QRE"),
        **overrides,
    )


def classify_cost(api, cast, cost_id, classification, exclusion_reason=None, headers=None):
    """Reclassify a cost as the developer, or as the monitor if asked."""
    kwargs = {"classification": classification}
    if exclusion_reason is not None:
        kwargs["exclusion_reason"] = exclusion_reason
    return get_success_data(
        api.classify_cost_line_item(cost_id, headers or cast.developer_headers, **kwargs)
    )


def create_part_application(api, cast, project_id, part_number, narrative=None, expected_version=None):
    """Create a part application, quoting the project's current version."""
    version = (
        expected_version
        if expected_version is not None
        else project_version(api, cast, project_id)
    )
    payload = factories.part_application_payload(project_id, part_number, version)
    if narrative is not None:
        payload["narrative"] = narrative
    return get_success_data(
        api.create_part_application(cast.developer_headers, **payload)
    )


def submit_part_application(api, cast, part_application_id, reviewer_id=None):
    return get_success_data(
        api.submit_part_application(
            part_application_id,
            cast.developer_headers,
            shpo_reviewer_id=reviewer_id or cast.shpo_reviewer_id,
        )
    )


def shpo_recommend(api, cast, part_application_id, recommendation="RECOMMEND_APPROVAL", review_note=None):
    kwargs = {"recommendation": recommendation}
    if review_note is not None:
        kwargs["review_note"] = review_note
    return get_success_data(
        api.shpo_recommend(part_application_id, cast.shpo_headers, **kwargs)
    )


def nps_determine(api, cast, part_application_id, determination="APPROVED", waived_finding_ids=None, review_note=None):
    kwargs = {"determination": determination}
    if waived_finding_ids is not None:
        kwargs["waived_finding_ids"] = waived_finding_ids
    if review_note is not None:
        kwargs["review_note"] = review_note
    return get_success_data(
        api.nps_determination(part_application_id, cast.nps_headers, **kwargs)
    )


def add_finding(api, cast, part_application_id, headers=None, **overrides):
    """Raise a Standards finding on an application under review (PRD §3.4)."""
    payload = factories.finding_payload(**overrides)
    return get_success_data(
        api.create_finding(
            part_application_id, headers or cast.shpo_headers, **payload
        )
    )


def walk_part_to_approved(api, cast, project_id, part_number, narrative=None):
    """Create, submit, recommend and approve one part application."""
    part_application = create_part_application(
        api, cast, project_id, part_number, narrative=narrative
    )
    submit_part_application(api, cast, part_application["id"])
    shpo_recommend(api, cast, part_application["id"])
    return nps_determine(api, cast, part_application["id"])


# ─── Tier 3: certified projects ───────────────────────


def part1_certified_project(api, cast=None, **project_overrides):
    """A project whose Part 1 is approved, so the property is certified."""
    cast = cast or seed_cast(api)
    project = open_project(api, cast, **project_overrides)
    part1 = walk_part_to_approved(api, cast, project["id"], 1)
    return {"cast": cast, "project": project, "part1": part1}


def part2_approved_project(api, cast=None, **project_overrides):
    """A project approved through Part 2, ready to be placed in service."""
    scenario = part1_certified_project(api, cast=cast, **project_overrides)
    scenario["part2"] = walk_part_to_approved(
        api, scenario["cast"], scenario["project"]["id"], 2
    )
    return scenario


def declare_in_service(
    api,
    cast,
    project_id,
    placed_in_service_date=None,
    clock=constants.IN_SERVICE_CLOCK_UTC,
):
    """Advance the clock and declare the building placed in service (PRD §3.2)."""
    if clock is not None:
        set_clock(api, clock)
    return get_success_data(
        api.place_in_service(
            project_id,
            cast.developer_headers,
            placed_in_service_date=placed_in_service_date
            or constants.TEST_DEFAULTS["PLACED_IN_SERVICE_DATE"],
        )
    )


def in_service_project(api, cast=None, qre_cents=None, **project_overrides):
    """Part 2 approved, one qualified cost recorded, and placed in service."""
    scenario = part1_certified_project(api, cast=cast, **project_overrides)
    cast = scenario["cast"]
    if qre_cents is not None:
        scenario["cost"] = add_qre_cost(api, cast, scenario["project"]["id"], qre_cents)
    scenario["part2"] = walk_part_to_approved(api, cast, scenario["project"]["id"], 2)
    scenario["project"] = declare_in_service(api, cast, scenario["project"]["id"])
    return scenario


def part3_certified_project(api, cast=None, qre_cents=62_500_013, **project_overrides):
    """The full certification walk: Part 1, Part 2, in service, Part 3.

    Leaves the project at PART3_CERTIFIED with its ledger frozen, which is the
    precondition for every claim, covenant and recapture scenario below.
    """
    scenario = in_service_project(api, cast=cast, qre_cents=qre_cents, **project_overrides)
    cast = scenario["cast"]
    scenario["part3"] = walk_part_to_approved(api, cast, scenario["project"]["id"], 3)
    scenario["project"] = read_project(api, cast, scenario["project"]["id"])
    return scenario


# ─── Tier 4: investors, claims, covenants, recapture ──


def admit_direct_partner(api, cast, project_id, **overrides):
    """Admit a direct partner interest (PRD §3.7)."""
    payload = factories.investor_interest_payload(project_id, **overrides)
    return get_success_data(
        api.create_investor_interest(cast.developer_headers, **payload)
    )


def admit_master_lease_lessee(api, cast, project_id, elect=True, **overrides):
    """Admit a master-lease lessee, electing the pass-through unless told not to."""
    payload = factories.master_lease_interest_payload(project_id, **overrides)
    interest = get_success_data(
        api.create_investor_interest(cast.developer_headers, **payload)
    )
    if elect:
        interest = get_success_data(
            api.elect_pass_through(
                interest["id"], make_investor_admin_headers(interest["id"])
            )
        )
    return interest


def investor_headers(interest):
    """Headers for the InvestorAdmin acting as this interest (PRD §2.1)."""
    return make_investor_admin_headers(interest["id"])


def create_claim(api, interest, project_id, tax_year=None):
    """Open a draft credit claim for a tax year (PRD §3.9)."""
    payload = factories.credit_claim_payload(project_id)
    if tax_year is not None:
        payload["tax_year"] = tax_year
    return get_success_data(
        api.create_credit_claim(investor_headers(interest), **payload)
    )


def file_claim(api, interest, claim_id):
    """File a draft claim, settling any outstanding recapture first (PRD §3.9)."""
    return get_success_data(
        api.file_credit_claim(claim_id, investor_headers(interest))
    )


def claim_filed_project(api, cast=None, qre_cents=62_500_013, tax_year=None, **project_overrides):
    """A Part-3 certified project with its first tax year already filed."""
    scenario = part3_certified_project(
        api, cast=cast, qre_cents=qre_cents, **project_overrides
    )
    cast = scenario["cast"]
    project_id = scenario["project"]["id"]
    if scenario["project"]["structure_type"] == "MASTER_LEASE":
        interest = admit_master_lease_lessee(api, cast, project_id)
    else:
        interest = admit_direct_partner(api, cast, project_id)
    claim = create_claim(api, interest, project_id, tax_year=tax_year)
    scenario["interest"] = interest
    scenario["claim"] = file_claim(api, interest, claim["id"])
    scenario["project"] = read_project(api, cast, project_id)
    return scenario


def create_covenant(api, cast, project_id, headers=None, **overrides):
    """Record a compliance covenant window (PRD §3.8)."""
    payload = factories.compliance_covenant_payload(project_id, **overrides)
    return get_success_data(
        api.create_compliance_covenant(headers or cast.developer_headers, **payload)
    )


def attest_covenant(api, cast, covenant_id, period_end_date, outcome, headers=None):
    """Attest to one monitoring period of a covenant (PRD §3.8)."""
    return get_success_data(
        api.attest_covenant(
            covenant_id,
            headers or cast.developer_headers,
            period_end_date=period_end_date,
            outcome=outcome,
        )
    )


def report_recapture_event(api, project_id, event_type, event_date, headers=None):
    """Report a compliance-period event as the monitor (PRD §3.8)."""
    return get_success_data(
        api.create_recapture_event(
            headers or MONITOR,
            project_id=project_id,
            event_type=event_type,
            event_date=event_date,
        )
    )
