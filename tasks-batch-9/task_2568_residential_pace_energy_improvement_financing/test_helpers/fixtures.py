"""Composite scenario builders.

Every test in this suite needs a parcel, a catalog, an enrolled contractor and
an application somewhere along the origination path.  Reaching a late state such
as ``ASSESSED`` costs a dozen calls, so those chains live here once.

The builders are layered: each one calls the previous layer and adds one step,
so a test can enter the chain at whatever state it needs.  Every builder accepts
``**overrides`` that are forwarded to the payload it constructs, and each returns
a plain dict of the identifiers and payloads it produced so a test can keep
walking the chain by hand.

Setup calls use the lenient ``get_success_data`` reader: a fixture's job is to
reach a state, not to assert the program's rules — the test does that.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import PaceApiClient
from .test_users import (
    COMPLIANCE_OFFICER,
    COUNTY_OFFICER,
    FUNDING_OFFICER_RELEASER,
    FUNDING_OFFICER_VERIFIER,
    PROGRAM_ADMIN,
    UNDERWRITING_ANALYST,
    contractor_headers,
    owner_headers,
)
from .types import Json

Scenario = Dict[str, Any]


# ---------------------------------------------------------------------------
# Tier 0 - clock
# ---------------------------------------------------------------------------


def move_clock(client: PaceApiClient, current_utc: str) -> Json:
    """Advance the program's logical clock; every date rule reads from it."""
    return get_success_data(client.set_clock(current_utc, PROGRAM_ADMIN))


# ---------------------------------------------------------------------------
# Tier 1 - catalog, contractor, parcel
# ---------------------------------------------------------------------------


def seed_catalog(client: PaceApiClient) -> Scenario:
    """The two-product catalog every origination scenario draws from."""
    solar = get_success_data(
        client.create_product(factories.solar_product_payload(), PROGRAM_ADMIN)
    )
    hvac = get_success_data(
        client.create_product(factories.hvac_product_payload(), PROGRAM_ADMIN)
    )
    return {
        "solar_product_id": solar["id"],
        "solar_product": solar,
        "hvac_product_id": hvac["id"],
        "hvac_product": hvac,
    }


def seed_enrolled_contractor(client: PaceApiClient, **overrides: Any) -> Scenario:
    """Enrolment is two steps: the application, then the program's approval."""
    contractor = get_success_data(
        client.create_contractor(factories.contractor_payload(**overrides), PROGRAM_ADMIN)
    )
    enrolled = get_success_data(
        client.enroll_contractor(contractor["id"], PROGRAM_ADMIN)
    )
    return {
        "contractor_id": contractor["id"],
        "contractor": enrolled,
        "contractor_legal_name": contractor["legal_name"],
    }


def seed_parcel(
    client: PaceApiClient,
    payload: Optional[Json] = None,
    with_senior_lien: bool = True,
    lien_overrides: Optional[Json] = None,
    **overrides: Any
) -> Scenario:
    """Register a parcel and, unless asked otherwise, its senior mortgage."""
    body = payload if payload is not None else factories.property_payload(**overrides)
    parcel = get_success_data(client.register_property(body, PROGRAM_ADMIN))
    out: Scenario = {
        "property_id": parcel["id"],
        "property": parcel,
        "owner_full_name": parcel["owner_full_name"],
        "owner_headers": owner_headers(parcel["id"]),
    }
    if with_senior_lien:
        lien = get_success_data(
            client.record_mortgage_lien(
                factories.mortgage_lien_payload(parcel["id"], **(lien_overrides or {})),
                PROGRAM_ADMIN,
            )
        )
        out["lien_id"] = lien["id"]
        out["lien"] = lien
        # "Recording an active lien immediately recomputes the parcel's
        # senior_lien_balance_cents and equity_ratio_bps", so the snapshot taken
        # at registration is stale the moment the mortgage lands.
        out["property"] = get_success_data(
            client.get_property(parcel["id"], PROGRAM_ADMIN)
        )
    return out


def seed_program(client: PaceApiClient, clock: str = "2026-08-12T00:00:00Z") -> Scenario:
    """Clock, catalog, enrolled contractor and one parcel with a senior lien."""
    move_clock(client, clock)
    world: Scenario = {"clock": clock}
    world.update(seed_catalog(client))
    world.update(seed_enrolled_contractor(client))
    world.update(seed_parcel(client))
    world["contractor_caller"] = contractor_headers(world["contractor_id"])
    return world


# ---------------------------------------------------------------------------
# Tier 2 - application state progression
# ---------------------------------------------------------------------------


def current_version(client: PaceApiClient, world: Scenario) -> int:
    """Re-read the application: every accepted measure addition bumps its version."""
    app = get_success_data(
        client.get_application(world["application_id"], world["owner_headers"])
    )
    world["application"] = app
    return app["version"]


def open_draft_application(
    client: PaceApiClient, world: Scenario, term_years: int = 20, **overrides: Any
) -> Scenario:
    """A DRAFT application on the seeded parcel with the seeded contractor."""
    app = get_success_data(
        client.open_application(
            factories.application_payload(
                world["property_id"], world["contractor_id"], term_years, **overrides
            ),
            world["owner_headers"],
        )
    )
    world["application_id"] = app["id"]
    world["application"] = app
    return world


def add_solar_measure(client: PaceApiClient, world: Scenario, **overrides: Any) -> Scenario:
    measure = get_success_data(
        client.add_measure(
            world["application_id"],
            factories.solar_measure_payload(
                world["solar_product_id"], current_version(client, world), **overrides
            ),
            world["owner_headers"],
        )
    )
    world["solar_measure_id"] = measure["id"]
    world["solar_measure"] = measure
    return world


def add_hvac_measure(client: PaceApiClient, world: Scenario, **overrides: Any) -> Scenario:
    measure = get_success_data(
        client.add_measure(
            world["application_id"],
            factories.hvac_measure_payload(
                world["hvac_product_id"], current_version(client, world), **overrides
            ),
            world["owner_headers"],
        )
    )
    world["hvac_measure_id"] = measure["id"]
    world["hvac_measure"] = measure
    return world


def draft_with_two_measures(
    client: PaceApiClient, world: Optional[Scenario] = None, term_years: int = 20
) -> Scenario:
    """The canonical measure set: a 25-year solar array and an 18-year heat pump."""
    world = world if world is not None else seed_program(client)
    open_draft_application(client, world, term_years)
    add_solar_measure(client, world)
    add_hvac_measure(client, world)
    return world


def submitted_application(
    client: PaceApiClient, world: Optional[Scenario] = None, term_years: int = 20
) -> Scenario:
    """UNDER_REVIEW, with every submit-time figure computed."""
    world = world if world is not None else draft_with_two_measures(client, term_years=term_years)
    world["application"] = get_success_data(
        client.submit_application(world["application_id"], world["owner_headers"])
    )
    return world


def underwritten_application(
    client: PaceApiClient,
    world: Optional[Scenario] = None,
    valuation_basis: str = "ASSESSED",
) -> Scenario:
    """CONSENT_PENDING: every eligibility gate cleared and the lender notified."""
    world = world if world is not None else submitted_application(client)
    world["application"] = get_success_data(
        client.underwrite_application(
            world["application_id"],
            factories.underwrite_proceed_payload(valuation_basis),
            UNDERWRITING_ANALYST,
        )
    )
    return world


def consented_application(
    client: PaceApiClient, world: Optional[Scenario] = None
) -> Scenario:
    """The mortgage holder answers in writing, clearing the consent posture."""
    world = world if world is not None else underwritten_application(client)
    if world.get("lien_id"):
        world["lien"] = get_success_data(
            client.record_consent_response(
                world["lien_id"],
                factories.consent_response_payload(),
                COMPLIANCE_OFFICER,
            )
        )
    return world


def approved_application(
    client: PaceApiClient, world: Optional[Scenario] = None
) -> Scenario:
    """APPROVED, with the approver recorded distinctly from the underwriter."""
    world = world if world is not None else consented_application(client)
    world["application"] = get_success_data(
        client.approve_application(world["application_id"], COMPLIANCE_OFFICER)
    )
    return world


# ---------------------------------------------------------------------------
# Tier 3 - agreement, certificate, disbursement
# ---------------------------------------------------------------------------


def issued_agreement(
    client: PaceApiClient,
    world: Optional[Scenario] = None,
    term_years: int = 20,
    apr_bps: int = 800,
) -> Scenario:
    """ISSUED, with the fee waterfall and the level payment already computed."""
    world = world if world is not None else approved_application(client)
    app = get_success_data(
        client.get_application(world["application_id"], world["owner_headers"])
    )
    world["application"] = app
    agreement = get_success_data(
        client.issue_agreement(
            factories.agreement_payload(
                world["application_id"], app["version"], term_years, apr_bps
            ),
            UNDERWRITING_ANALYST,
        )
    )
    world["agreement_id"] = agreement["id"]
    world["agreement"] = agreement
    return world


def signed_agreement(
    client: PaceApiClient, world: Optional[Scenario] = None
) -> Scenario:
    """SIGNED: the rescission clock is running and the parcel exposure is committed."""
    world = world if world is not None else issued_agreement(client)
    world["agreement"] = get_success_data(
        client.sign_agreement(
            world["agreement_id"],
            factories.sign_agreement_payload(world["owner_full_name"]),
            world["owner_headers"],
        )
    )
    return world


def filed_certificate(
    client: PaceApiClient,
    world: Optional[Scenario] = None,
    measure_ids: Optional[List[str]] = None,
    certified_cost_cents: int = 4200000,
) -> Scenario:
    """CONTRACTOR_ATTESTED, listing the measures the contractor claims are done."""
    world = world if world is not None else signed_agreement(client)
    ids = measure_ids
    if ids is None:
        ids = [world["solar_measure_id"], world["hvac_measure_id"]]
    certificate = get_success_data(
        client.file_certificate(
            factories.certificate_payload(
                world["application_id"], ids, certified_cost_cents
            ),
            contractor_headers(world["contractor_id"]),
        )
    )
    world["certificate_id"] = certificate["id"]
    world["certificate"] = certificate
    return world


def countersigned_certificate(
    client: PaceApiClient, world: Optional[Scenario] = None, **kwargs: Any
) -> Scenario:
    """HOMEOWNER_SIGNED: the owner confirms the work the contractor attested to."""
    world = world if world is not None else filed_certificate(client, **kwargs)
    world["certificate"] = get_success_data(
        client.sign_certificate(
            world["certificate_id"],
            factories.sign_certificate_payload(world["owner_full_name"]),
            world["owner_headers"],
        )
    )
    return world


def verified_certificate(
    client: PaceApiClient, world: Optional[Scenario] = None, **kwargs: Any
) -> Scenario:
    """VERIFIED by the funding officer who will not be the one releasing funds."""
    world = world if world is not None else countersigned_certificate(client, **kwargs)
    world["certificate"] = get_success_data(
        client.verify_certificate(
            world["certificate_id"],
            factories.verify_certificate_payload("APPROVE"),
            FUNDING_OFFICER_VERIFIER,
        )
    )
    return world


def requested_disbursement(
    client: PaceApiClient,
    world: Optional[Scenario] = None,
    amount_cents: int = 4200000,
    **kwargs: Any
) -> Scenario:
    """REQUESTED, and the application is FUNDING_PENDING."""
    world = world if world is not None else verified_certificate(client, **kwargs)
    disbursement = get_success_data(
        client.request_disbursement(
            factories.disbursement_payload(
                world["application_id"],
                world["certificate_id"],
                world["contractor_id"],
                amount_cents,
            ),
            FUNDING_OFFICER_VERIFIER,
        )
    )
    world["disbursement_id"] = disbursement["id"]
    world["disbursement"] = disbursement
    return world


def released_disbursement(
    client: PaceApiClient, world: Optional[Scenario] = None, **kwargs: Any
) -> Scenario:
    """RELEASED by the second funding officer; the application becomes FUNDED."""
    world = world if world is not None else requested_disbursement(client, **kwargs)
    world["disbursement"] = get_success_data(
        client.release_disbursement(world["disbursement_id"], FUNDING_OFFICER_RELEASER)
    )
    return world


# ---------------------------------------------------------------------------
# Tier 4 - full lifecycle shortcuts
# ---------------------------------------------------------------------------

# The signing day, chosen so the three-business-day rescission window closes at
# 2026-08-18T00:00:00Z.
SIGNING_CLOCK = "2026-08-12T00:00:00Z"
# The first instant at which the rescission window is closed and funds may move.
RELEASE_CLOCK = "2026-08-18T00:00:00Z"
# A recording day comfortably after funding.
RECORDING_CLOCK = "2026-08-20T00:00:00Z"

CANONICAL_PRINCIPAL_CENTS = 4200000
SOLAR_ONLY_PRINCIPAL_CENTS = 3000000


def funded_project(
    client: PaceApiClient,
    world: Optional[Scenario] = None,
    principal_cents: int = CANONICAL_PRINCIPAL_CENTS,
    measure_ids: Optional[List[str]] = None,
) -> Scenario:
    """Origination through release: the application ends FUNDED and cash has moved.

    Signature lands on the pinned signing day, the clock then steps to the first
    instant past the rescission window so the release is legal.
    """
    world = world if world is not None else seed_program(client, SIGNING_CLOCK)
    if "application_id" not in world:
        draft_with_two_measures(client, world)
        submitted_application(client, world)
    underwritten_application(client, world)
    consented_application(client, world)
    approved_application(client, world)
    issued_agreement(client, world)
    signed_agreement(client, world)
    move_clock(client, RELEASE_CLOCK)
    world["clock"] = RELEASE_CLOCK
    filed_certificate(
        client, world, measure_ids=measure_ids, certified_cost_cents=principal_cents
    )
    countersigned_certificate(client, world)
    verified_certificate(client, world)
    requested_disbursement(client, world, amount_cents=principal_cents)
    released_disbursement(client, world)
    return world


def assessed_project(
    client: PaceApiClient,
    world: Optional[Scenario] = None,
    first_tax_year: int = 2027,
    recording_clock: str = RECORDING_CLOCK,
    **kwargs: Any
) -> Scenario:
    """A FUNDED project carried onto the county tax roll as an ASSESSED lien."""
    world = world if world is not None else funded_project(client, **kwargs)
    move_clock(client, recording_clock)
    world["clock"] = recording_clock
    assessment = get_success_data(
        client.record_assessment(
            factories.assessment_payload(world["application_id"], first_tax_year),
            COUNTY_OFFICER,
        )
    )
    world["assessment_id"] = assessment["id"]
    world["assessment"] = assessment
    world["first_tax_year"] = first_tax_year
    return world


def schedule_of(client: PaceApiClient, world: Scenario) -> List[Json]:
    """The assessment's amortization schedule, ordered by tax year."""
    response = client.list_installments(
        world["assessment_id"], PROGRAM_ADMIN, {"limit": 100}
    )
    rows = get_success_data(response)
    world["installments"] = rows
    return rows


def solar_only_project(client: PaceApiClient, world: Optional[Scenario] = None) -> Scenario:
    """A single-measure deal: the 25-year solar array alone."""
    world = world if world is not None else seed_program(client, SIGNING_CLOCK)
    open_draft_application(client, world, 20)
    add_solar_measure(client, world)
    submitted_application(client, world)
    return funded_project(
        client,
        world,
        principal_cents=SOLAR_ONLY_PRINCIPAL_CENTS,
        measure_ids=[world["solar_measure_id"]],
    )


def second_parcel(client: PaceApiClient, world: Scenario) -> Scenario:
    """A second parcel in the same county, for cross-parcel and cascade scenarios."""
    extra = seed_parcel(
        client,
        payload=factories.second_property_payload(),
        lien_overrides={"holder_name": "Cascade Mutual Bank", "recorded_on": "2020-08-05"},
    )
    world["second_property_id"] = extra["property_id"]
    world["second_property"] = extra["property"]
    world["second_owner_full_name"] = extra["owner_full_name"]
    world["second_owner_headers"] = extra["owner_headers"]
    world["second_lien_id"] = extra.get("lien_id")
    return world


# ---------------------------------------------------------------------------
# Tier 5 - accumulation and terminal-state targeting
# ---------------------------------------------------------------------------


def billed_first_installment(
    client: PaceApiClient,
    world: Scenario,
    tax_year: Optional[int] = None,
    effective_date: Optional[str] = None,
) -> Scenario:
    """Run the roll for the assessment's first year so its installment is BILLED."""
    year = tax_year if tax_year is not None else world["first_tax_year"]
    effective = effective_date or "{0}-10-01".format(year)
    world["roll_run"] = get_success_data(
        client.run_county_roll(
            world["property"]["county_code"],
            factories.roll_run_payload(year, effective),
            COUNTY_OFFICER,
        )
    )
    world["installments"] = schedule_of(client, world)
    return world


def filed_complaint(
    client: PaceApiClient,
    world: Scenario,
    severity: str = "MINOR",
    category: str = "WORKMANSHIP_DEFECT",
    **overrides: Any
) -> Scenario:
    """File a workmanship complaint against the contractor on a funded project."""
    complaint = get_success_data(
        client.file_complaint(
            factories.complaint_payload(
                world["application_id"],
                world["contractor_id"],
                severity,
                category,
                **overrides
            ),
            world["owner_headers"],
        )
    )
    world["complaint_id"] = complaint["id"]
    world["complaint"] = complaint
    return world


def upheld_complaint(
    client: PaceApiClient,
    world: Scenario,
    remedy_deadline_on: str,
    severity: str = "MINOR",
    category: str = "WORKMANSHIP_DEFECT",
    **overrides: Any
) -> Scenario:
    """File a complaint and uphold it with a remedy order and a deadline."""
    filed_complaint(client, world, severity, category, **overrides)
    world["complaint"] = get_success_data(
        client.adjudicate_complaint(
            world["complaint_id"],
            factories.uphold_payload(remedy_deadline_on),
            COMPLIANCE_OFFICER,
        )
    )
    return world


def payoff_quote(
    client: PaceApiClient,
    world: Scenario,
    closing_date: str,
    mode: str = "ASSUME_WITH_PROPERTY",
    **overrides: Any
) -> Scenario:
    """Raise a payoff quote against the recorded assessment."""
    transfer = get_success_data(
        client.quote_transfer(
            factories.transfer_quote_payload(
                world["assessment_id"], closing_date, mode, **overrides
            ),
            COUNTY_OFFICER,
        )
    )
    world["transfer_id"] = transfer["id"]
    world["transfer"] = transfer
    return world


def refreshed(client: PaceApiClient, world: Scenario) -> Scenario:
    """Re-read every entity the scenario tracks, so assertions see live values."""
    world["property"] = get_success_data(
        client.get_property(world["property_id"], PROGRAM_ADMIN)
    )
    world["contractor"] = get_success_data(
        client.get_contractor(world["contractor_id"], PROGRAM_ADMIN)
    )
    if world.get("application_id"):
        world["application"] = get_success_data(
            client.get_application(world["application_id"], PROGRAM_ADMIN)
        )
    if world.get("agreement_id"):
        world["agreement"] = get_success_data(
            client.get_agreement(world["agreement_id"], PROGRAM_ADMIN)
        )
    if world.get("certificate_id"):
        world["certificate"] = get_success_data(
            client.get_certificate(world["certificate_id"], PROGRAM_ADMIN)
        )
    if world.get("disbursement_id"):
        world["disbursement"] = get_success_data(
            client.get_disbursement(world["disbursement_id"], PROGRAM_ADMIN)
        )
    if world.get("assessment_id"):
        world["assessment"] = get_success_data(
            client.get_assessment(world["assessment_id"], PROGRAM_ADMIN)
        )
    if world.get("complaint_id"):
        world["complaint"] = get_success_data(
            client.get_complaint(world["complaint_id"], PROGRAM_ADMIN)
        )
    if world.get("transfer_id"):
        world["transfer"] = get_success_data(
            client.get_transfer(world["transfer_id"], PROGRAM_ADMIN)
        )
    return world


def read_property(client: PaceApiClient, world: Scenario) -> Json:
    world["property"] = get_success_data(
        client.get_property(world["property_id"], PROGRAM_ADMIN)
    )
    return world["property"]


def read_contractor(client: PaceApiClient, world: Scenario) -> Json:
    world["contractor"] = get_success_data(
        client.get_contractor(world["contractor_id"], PROGRAM_ADMIN)
    )
    return world["contractor"]


def read_application(client: PaceApiClient, world: Scenario) -> Json:
    world["application"] = get_success_data(
        client.get_application(world["application_id"], PROGRAM_ADMIN)
    )
    return world["application"]


def read_measure(client: PaceApiClient, measure_id: str) -> Json:
    return get_success_data(client.get_measure(measure_id, PROGRAM_ADMIN))


def read_assessment(client: PaceApiClient, world: Scenario) -> Json:
    world["assessment"] = get_success_data(
        client.get_assessment(world["assessment_id"], PROGRAM_ADMIN)
    )
    return world["assessment"]


def read_agreement(client: PaceApiClient, world: Scenario) -> Json:
    world["agreement"] = get_success_data(
        client.get_agreement(world["agreement_id"], PROGRAM_ADMIN)
    )
    return world["agreement"]


def read_certificate(client: PaceApiClient, world: Scenario) -> Json:
    world["certificate"] = get_success_data(
        client.get_certificate(world["certificate_id"], PROGRAM_ADMIN)
    )
    return world["certificate"]


def read_disbursement(client: PaceApiClient, world: Scenario) -> Json:
    world["disbursement"] = get_success_data(
        client.get_disbursement(world["disbursement_id"], PROGRAM_ADMIN)
    )
    return world["disbursement"]


def read_complaint(client: PaceApiClient, world: Scenario) -> Json:
    world["complaint"] = get_success_data(
        client.get_complaint(world["complaint_id"], PROGRAM_ADMIN)
    )
    return world["complaint"]


def read_transfer(client: PaceApiClient, world: Scenario) -> Json:
    world["transfer"] = get_success_data(
        client.get_transfer(world["transfer_id"], PROGRAM_ADMIN)
    )
    return world["transfer"]
