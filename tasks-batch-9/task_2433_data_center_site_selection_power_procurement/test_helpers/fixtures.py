"""Composite setup helpers.

Every test starts against an empty database, so all preconditions are built from
scratch here and only ever through endpoints the PRD declares. The module is
organised in layers:

* single-step wrappers (``open_program``, ``screen_site``, ``file_load_study`` …)
  that make one call and return the resulting resource;
* read helpers (``read_site``, ``read_utility`` …) that re-fetch a row so a test
  can observe a cascade the response body did not address;
* composite builders (``setup_studied_application``,
  ``setup_commit_ready_site`` …) that walk a whole preamble and return a dict of
  everything they made.

All helpers use the lenient success reader, so a broken preamble surfaces as a
setup failure rather than as a confusing assertion deep inside a test.
"""

from typing import Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    LOAD_STUDY_BASE,
    OPTION_APN_100,
    OPTION_APN_200,
    SCREEN_AIR_COOLED,
    SCREEN_EVAPORATIVE,
)
from .factories import (
    create_authority_round_payload,
    create_candidate_site_payload,
    create_capacity_revision_payload,
    create_clock_payload,
    create_community_objection_payload,
    create_company_round_payload,
    create_disqualification_payload,
    create_drought_declaration_payload,
    create_energization_commitment_payload,
    create_incentive_negotiation_payload,
    create_interconnection_application_payload,
    create_load_study_payload,
    create_parcel_option_payload,
    create_power_purchase_agreement_payload,
    create_screening_payload,
    create_siting_program_payload,
    create_utility_payload,
    create_water_source_payload,
    create_withdrawal_payload,
    create_zoning_application_payload,
    create_zoning_decision_payload,
)
from .test_users import (
    TEST_USERS,
    make_chair_headers,
    make_utility_planner_headers,
)

ANALYST = TEST_USERS["analyst_headers"]
DIRECTOR = TEST_USERS["director_headers"]
NEGOTIATOR = TEST_USERS["negotiator_headers"]
AUTHORITY = TEST_USERS["authority_headers"]
CHAIR = TEST_USERS["chair_headers"]


# --------------------------------------------------------------------------- #
# the logical clock
# --------------------------------------------------------------------------- #
def set_clock(to_iso8601: str, headers: Optional[dict] = None) -> dict:
    """Reposition the logical clock. §2.6: repositioning "mutates no entity and
    runs no sweep", and the operation "returns no resource in `data`"."""
    return get_success_data(
        api_client.set_clock(create_clock_payload(to_iso8601), headers or DIRECTOR)
    )


# --------------------------------------------------------------------------- #
# programs, utilities and basins
# --------------------------------------------------------------------------- #
def open_program(**overrides) -> dict:
    return get_success_data(
        api_client.create_siting_program(
            create_siting_program_payload(**overrides), DIRECTOR
        )
    )


def read_program(program_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.get_siting_program(program_id, headers or DIRECTOR)
    )


def register_utility(**overrides) -> dict:
    return get_success_data(
        api_client.create_utility(create_utility_payload(**overrides), DIRECTOR)
    )


def read_utility(utility_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_utility(utility_id, headers or DIRECTOR))


def revise_capacity(
    utility_id: str, revised_total_capacity_mw: float, **overrides
) -> dict:
    return get_success_data(
        api_client.create_capacity_revision(
            utility_id,
            create_capacity_revision_payload(revised_total_capacity_mw, **overrides),
            make_utility_planner_headers(utility_id),
        )
    )


def register_water_source(**overrides) -> dict:
    return get_success_data(
        api_client.create_water_source(
            create_water_source_payload(**overrides), AUTHORITY
        )
    )


def read_water_source(water_source_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.get_water_source(water_source_id, headers or AUTHORITY)
    )


def declare_drought(
    water_source_id: str, drought_stage: str, effective_date: str, **overrides
) -> dict:
    return get_success_data(
        api_client.create_drought_declaration(
            water_source_id,
            create_drought_declaration_payload(
                drought_stage, effective_date, **overrides
            ),
            AUTHORITY,
        )
    )


# --------------------------------------------------------------------------- #
# candidate sites
# --------------------------------------------------------------------------- #
def add_site(
    program_id: str, utility_id: str, water_source_id: str, **overrides
) -> dict:
    return get_success_data(
        api_client.create_candidate_site(
            create_candidate_site_payload(
                program_id, utility_id, water_source_id, **overrides
            ),
            ANALYST,
        )
    )


def read_site(site_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.get_candidate_site(site_id, headers or ANALYST)
    )


def site_version(site_id: str) -> int:
    """Read the site's current `version` so the next `POST /parcel-options` can
    carry a fresh `expected_site_version` (§2.10)."""
    return read_site(site_id)["version"]


def screen_site(site_id: str, headers: Optional[dict] = None, **overrides) -> dict:
    """File the ten-measurement screening package. The default package is the
    evaporative one; pass ``**SCREEN_AIR_COOLED`` for an air-cooled campus."""
    return get_success_data(
        api_client.screen_candidate_site(
            site_id, create_screening_payload(**overrides), headers or ANALYST
        )
    )


def screen_site_air_cooled(
    site_id: str, headers: Optional[dict] = None, **overrides
) -> dict:
    payload = dict(SCREEN_AIR_COOLED)
    payload.update(overrides)
    return screen_site(site_id, headers, **payload)


def commit_site(site_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.commit_candidate_site(site_id, headers or CHAIR)
    )


def disqualify_site(
    site_id: str, disqualification_reason: str = "TRANSMISSION_RISK"
) -> dict:
    return get_success_data(
        api_client.disqualify_candidate_site(
            site_id, create_disqualification_payload(disqualification_reason), DIRECTOR
        )
    )


def list_sites(params: Optional[Dict] = None, headers: Optional[dict] = None) -> dict:
    """Return the full list envelope so callers can read both data and meta."""
    return api_client.list_candidate_sites(headers or ANALYST, params=params).json()


# --------------------------------------------------------------------------- #
# interconnection applications and load studies
# --------------------------------------------------------------------------- #
def draft_application(site_id: str, utility_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_interconnection_application(
            create_interconnection_application_payload(
                site_id, utility_id, **overrides
            ),
            ANALYST,
        )
    )


def read_application(application_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.get_interconnection_application(application_id, headers or ANALYST)
    )


def submit_application(application_id: str) -> dict:
    return get_success_data(
        api_client.submit_interconnection_application(application_id, ANALYST)
    )


def file_load_study(application_id: str, utility_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_load_study(
            application_id,
            create_load_study_payload(**overrides),
            make_utility_planner_headers(utility_id),
        )
    )


def reserve_capacity(application_id: str, utility_id: str) -> dict:
    return get_success_data(
        api_client.reserve_capacity(
            application_id, make_utility_planner_headers(utility_id)
        )
    )


def commit_energization(
    application_id: str, utility_id: str, committed_energization_date: str
) -> dict:
    return get_success_data(
        api_client.commit_energization(
            application_id,
            create_energization_commitment_payload(committed_energization_date),
            make_utility_planner_headers(utility_id),
        )
    )


def withdraw_application(
    application_id: str, withdrawal_reason: str = "SPONSOR_DEFERRED"
) -> dict:
    return get_success_data(
        api_client.withdraw_interconnection_application(
            application_id, create_withdrawal_payload(withdrawal_reason), ANALYST
        )
    )


def list_applications(
    params: Optional[Dict] = None, headers: Optional[dict] = None
) -> dict:
    return api_client.list_interconnection_applications(
        headers or ANALYST, params=params
    ).json()


def list_load_studies(
    application_id: str, params: Optional[Dict] = None, headers: Optional[dict] = None
) -> dict:
    return api_client.list_load_studies(
        application_id, headers or ANALYST, params=params
    ).json()


# --------------------------------------------------------------------------- #
# zoning
# --------------------------------------------------------------------------- #
def file_zoning(site_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_zoning_application(
            create_zoning_application_payload(site_id, **overrides), ANALYST
        )
    )


def add_objection(
    zoning_application_id: str,
    objection_type: str = "NOISE",
    commenter_reference: str = "COMMENT-001",
) -> dict:
    return get_success_data(
        api_client.create_community_objection(
            zoning_application_id,
            create_community_objection_payload(objection_type, commenter_reference),
            AUTHORITY,
        )
    )


def decide_zoning(
    zoning_application_id: str,
    outcome: str = "APPROVED_WITH_CONDITIONS",
    decision_note: Optional[str] = "Approved with enclosure conditions.",
) -> dict:
    return get_success_data(
        api_client.decide_zoning_application(
            zoning_application_id,
            create_zoning_decision_payload(outcome, decision_note),
            AUTHORITY,
        )
    )


def list_site_zoning(
    site_id: str, params: Optional[Dict] = None, headers: Optional[dict] = None
) -> dict:
    return api_client.list_site_zoning_applications(
        site_id, headers or ANALYST, params=params
    ).json()


# --------------------------------------------------------------------------- #
# incentive negotiations
# --------------------------------------------------------------------------- #
def open_negotiation(site_id: str, authority_level: str = "STATE", **overrides) -> dict:
    return get_success_data(
        api_client.create_incentive_negotiation(
            create_incentive_negotiation_payload(site_id, authority_level, **overrides),
            NEGOTIATOR,
        )
    )


def file_company_round(negotiation_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_negotiation_round(
            negotiation_id, create_company_round_payload(**overrides), NEGOTIATOR
        )
    )


def file_authority_round(negotiation_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_negotiation_round(
            negotiation_id, create_authority_round_payload(**overrides), AUTHORITY
        )
    )


def sign_negotiation(negotiation_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.sign_incentive_negotiation(negotiation_id, headers or NEGOTIATOR)
    )


def ratify_negotiation(negotiation_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.ratify_incentive_negotiation(negotiation_id, headers or CHAIR)
    )


def list_site_negotiations(
    site_id: str, params: Optional[Dict] = None, headers: Optional[dict] = None
) -> dict:
    return api_client.list_site_incentive_negotiations(
        site_id, headers or NEGOTIATOR, params=params
    ).json()


# --------------------------------------------------------------------------- #
# power purchase agreements
# --------------------------------------------------------------------------- #
def draft_ppa(program_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_power_purchase_agreement(
            create_power_purchase_agreement_payload(program_id, **overrides), DIRECTOR
        )
    )


def execute_ppa(agreement_id: str) -> dict:
    return get_success_data(
        api_client.execute_power_purchase_agreement(agreement_id, DIRECTOR)
    )


def list_program_ppas(
    program_id: str, params: Optional[Dict] = None, headers: Optional[dict] = None
) -> dict:
    return api_client.list_program_power_purchase_agreements(
        program_id, headers or DIRECTOR, params=params
    ).json()


# --------------------------------------------------------------------------- #
# land parcel options
# --------------------------------------------------------------------------- #
def sign_option(site_id: str, expected_site_version: Optional[int] = None, **overrides) -> dict:
    """Sign a land option, reading the site's current `version` for the
    concurrency token when the caller does not pin one explicitly (§2.10)."""
    if expected_site_version is None:
        expected_site_version = site_version(site_id)
    return get_success_data(
        api_client.create_parcel_option(
            create_parcel_option_payload(site_id, expected_site_version, **overrides),
            ANALYST,
        )
    )


def read_option(option_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_parcel_option(option_id, headers or ANALYST))


def exercise_option(option_id: str) -> dict:
    return get_success_data(api_client.exercise_parcel_option(option_id, DIRECTOR))


def run_expiry_sweep(program_id: str) -> dict:
    return get_success_data(api_client.run_option_expiry_sweep(program_id, DIRECTOR))


def list_options(params: Optional[Dict] = None, headers: Optional[dict] = None) -> dict:
    return api_client.list_parcel_options(headers or ANALYST, params=params).json()


# --------------------------------------------------------------------------- #
# Tier 1 — the physical environment
# --------------------------------------------------------------------------- #
def setup_environment(
    program: Optional[dict] = None,
    utility: Optional[dict] = None,
    water_source: Optional[dict] = None,
) -> dict:
    """A program, a serving utility and a basin: the three rows every other
    fixture builds on. Each argument is a dict of payload overrides."""
    prog = open_program(**(program or {}))
    util = register_utility(**(utility or {}))
    basin = register_water_source(**(water_source or {}))
    return {"program": prog, "utility": util, "water_source": basin}


# --------------------------------------------------------------------------- #
# Tier 2 — sites on that environment
# --------------------------------------------------------------------------- #
def setup_draft_site(
    program: Optional[dict] = None,
    utility: Optional[dict] = None,
    water_source: Optional[dict] = None,
    site: Optional[dict] = None,
) -> dict:
    env = setup_environment(program, utility, water_source)
    env["site"] = add_site(
        env["program"]["id"],
        env["utility"]["id"],
        env["water_source"]["id"],
        **(site or {}),
    )
    return env


def setup_screened_site(
    program: Optional[dict] = None,
    utility: Optional[dict] = None,
    water_source: Optional[dict] = None,
    site: Optional[dict] = None,
    screening: Optional[dict] = None,
    screener_headers: Optional[dict] = None,
) -> dict:
    """Site Alpha screened with the evaporative package, which scores 83.00 on a
    MODERATE hazard tier against the 300 MW program."""
    env = setup_draft_site(program, utility, water_source, site)
    env["site"] = screen_site(
        env["site"]["id"], screener_headers, **(screening or {})
    )
    return env


def add_sibling_site(
    env: dict,
    site: Optional[dict] = None,
    screening: Optional[dict] = None,
    screen: bool = True,
) -> dict:
    """Add another site to the same program, utility and basin, screening it by
    default so it competes for basin headroom and transmission capacity."""
    sibling = add_site(
        env["program"]["id"],
        env["utility"]["id"],
        env["water_source"]["id"],
        **(site or {"name": "Site Bravo", "county": "Davidson"}),
    )
    if screen:
        sibling = screen_site(sibling["id"], **(screening or {}))
    return sibling


# --------------------------------------------------------------------------- #
# Tier 3 — the interconnection lifecycle
# --------------------------------------------------------------------------- #
def setup_submitted_application(
    application: Optional[dict] = None, **env_overrides
) -> dict:
    """Screened Site Alpha with a SUBMITTED 300 MW application: the study fee of
    360000.00 is struck and the queue position is 1."""
    env = setup_screened_site(**env_overrides)
    env["application"] = draft_application(
        env["site"]["id"], env["utility"]["id"], **(application or {})
    )
    env["application"] = submit_application(env["application"]["id"])
    return env


def setup_studied_application(
    application: Optional[dict] = None,
    load_study: Optional[dict] = None,
    **env_overrides,
) -> dict:
    """…and one load study round, carrying the application to STUDY_COMPLETE with
    a nameplate peak of 318.0 MW and a diversified peak of 293.52 MW."""
    env = setup_submitted_application(application, **env_overrides)
    env["load_study"] = file_load_study(
        env["application"]["id"], env["utility"]["id"], **(load_study or {})
    )
    env["application"] = read_application(env["application"]["id"])
    return env


def setup_reserved_application(
    application: Optional[dict] = None,
    load_study: Optional[dict] = None,
    **env_overrides,
) -> dict:
    """…and a capacity reservation, so the application sits in CAPACITY_RESERVED
    and the utility ledger reads 300.0 reserved against 200.0 available."""
    env = setup_studied_application(application, load_study, **env_overrides)
    env["application"] = reserve_capacity(
        env["application"]["id"], env["utility"]["id"]
    )
    return env


def setup_energization_committed_application(
    committed_energization_date: str = "2029-06-30T00:00:00Z",
    application: Optional[dict] = None,
    load_study: Optional[dict] = None,
    **env_overrides,
) -> dict:
    """…and an energization commitment on the supplied date, which prices the
    slip against the program's required energization date."""
    env = setup_reserved_application(application, load_study, **env_overrides)
    env["application"] = commit_energization(
        env["application"]["id"], env["utility"]["id"], committed_energization_date
    )
    return env


# --------------------------------------------------------------------------- #
# Tier 3 — the permitting, incentive, land and renewable tracks
# --------------------------------------------------------------------------- #
def setup_approved_zoning(site_id: str, zoning: Optional[dict] = None) -> dict:
    """A docket offering FULL_ENCLOSURE against a 7 dBA excess, approved with
    conditions: mitigation 2975000.00 and escrow 446250.00."""
    docket = file_zoning(site_id, **(zoning or {}))
    return decide_zoning(docket["id"])


def setup_ratified_state_negotiation(
    site_id: str,
    chair_headers: Optional[dict] = None,
    terms: Optional[dict] = None,
) -> dict:
    """A STATE negotiation walked COMPANY round -> AUTHORITY round -> sign ->
    ratify. The site's zoning docket must already stand at
    APPROVED_WITH_CONDITIONS, because ratification is gated on it (§3.7)."""
    negotiation = open_negotiation(site_id, "STATE")
    file_company_round(negotiation["id"], **(terms or {}))
    file_authority_round(negotiation["id"])
    sign_negotiation(negotiation["id"])
    return ratify_negotiation(negotiation["id"], chair_headers or make_chair_headers())


def setup_executed_ppa_at_coverage_floor(
    program_id: str, agreement: Optional[dict] = None
) -> dict:
    """A STORAGE_HYBRID agreement executed under ANNUAL_VOLUMETRIC accounting,
    crediting 1892160.0 MWh — exactly 80.00 percent of a 300 MW program's
    annual load."""
    ppa = draft_ppa(program_id, **(agreement or {}))
    return execute_ppa(ppa["id"])


def assemble_full_land_control(site_id: str) -> List[dict]:
    """Two options on distinct parcels totalling 300 acres, which is the whole
    campus footprint, so land control reaches 100.00 and FULL."""
    first = sign_option(site_id, **OPTION_APN_100)
    second = sign_option(site_id, **OPTION_APN_200)
    return [first, second]


# --------------------------------------------------------------------------- #
# Tier 4 — the commit ladder
# --------------------------------------------------------------------------- #
def setup_commit_ready_site(
    committed_energization_date: Optional[str] = None,
    **env_overrides,
) -> dict:
    """Everything the nine commit gates of §3.10 demand, satisfied at once:
    Site Alpha SCREENED on a MODERATE tier, its docket APPROVED_WITH_CONDITIONS,
    a RATIFIED STATE negotiation, full land control, feasible water, renewable
    coverage at exactly 80.00 percent, and a capital commitment of
    32876386.00 inside the 60000000 ceiling.

    Reserving capacity comes first because exercising land options later
    requires the live application to hold capacity, and the two options are
    signed after the reservation so their premiums land in the ledger.
    """
    env = setup_reserved_application(**env_overrides)
    if committed_energization_date is not None:
        env["application"] = commit_energization(
            env["application"]["id"],
            env["utility"]["id"],
            committed_energization_date,
        )
    env["zoning"] = setup_approved_zoning(env["site"]["id"])
    env["negotiation"] = setup_ratified_state_negotiation(env["site"]["id"])
    env["options"] = assemble_full_land_control(env["site"]["id"])
    env["ppa"] = setup_executed_ppa_at_coverage_floor(env["program"]["id"])
    env["site"] = read_site(env["site"]["id"])
    env["program"] = read_program(env["program"]["id"])
    return env


def setup_committed_site(**kwargs) -> dict:
    """A fully committed program: the commit-ready preamble plus the commit."""
    env = setup_commit_ready_site(**kwargs)
    env["site"] = commit_site(env["site"]["id"])
    env["program"] = read_program(env["program"]["id"])
    return env
