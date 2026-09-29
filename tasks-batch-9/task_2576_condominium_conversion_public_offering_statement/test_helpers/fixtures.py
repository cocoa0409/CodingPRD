"""Fixtures and state builders.

The runner relaunches the server before every test, so every test starts from
an empty database and builds all of its own state through the public API.
Nothing here is cached across tests and nothing is seeded server-side.
"""

from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import pytest
from prd_bench_local_runner.testing import get_success_data

from .api_client import ConversionApiClient
from .constants import (
    ENGINEER_USER_ID,
    PEER_USER_ID,
    POS_SECTION_CODES,
    SPONSOR_USER_ID,
)
from .factories import (
    agreement_payload,
    assessment_payload,
    assignment_payload,
    batch_payload,
    budget_payload,
    component_payload,
    household_payload,
    package_payload,
    peer_review_payload,
    pos_payload,
    project_payload,
    report_payload,
    reserve_study_payload,
    section_payload,
    unit_payload,
)
from .test_users import (
    admin_headers,
    engineer_headers,
    escrow_headers,
    peer_headers,
    regulator_headers,
    sponsor_headers,
)
from .types import JsonDict


@pytest.fixture
def api() -> ConversionApiClient:
    """A client bound to the base URL the runner injected."""
    return ConversionApiClient()


# --- logical clock ----------------------------------------------------------
def set_clock(api: ConversionApiClient, instant: str) -> JsonDict:
    """Move the logical clock to an exact instant. Tests never sleep."""
    return get_success_data(api.set_clock(instant, admin_headers()))


def read_clock(api: ConversionApiClient) -> str:
    return get_success_data(api.get_clock(admin_headers()))["current_utc"]


# --- tier 1: bare rows ------------------------------------------------------
def make_project(
    api: ConversionApiClient,
    building_address: str = "44 Cove Lane, Bangor ME",
    year_built: int = 1968,
    total_unit_count: int = 2,
    sponsor_user_id: str = SPONSOR_USER_ID,
    max_overlapping_remediations: Optional[int] = None,
) -> JsonDict:
    return get_success_data(
        api.create_project(
            project_payload(
                building_address,
                year_built,
                total_unit_count,
                sponsor_user_id,
                max_overlapping_remediations,
            ),
            sponsor_headers(sponsor_user_id),
        )
    )


def make_report(
    api: ConversionApiClient,
    project_id: str,
    report_label: str = "ER-1",
    inspection_date: str = "2026-07-10T00:00:00Z",
    engineer_user_id: str = ENGINEER_USER_ID,
) -> JsonDict:
    return get_success_data(
        api.create_report(
            project_id,
            report_payload(report_label, inspection_date, engineer_user_id),
            engineer_headers(engineer_user_id),
        )
    )


def make_component(
    api: ConversionApiClient,
    report_id: str,
    payload: JsonDict,
    engineer_user_id: str = ENGINEER_USER_ID,
) -> JsonDict:
    return get_success_data(
        api.create_component(report_id, payload, engineer_headers(engineer_user_id))
    )


def make_components(
    api: ConversionApiClient,
    report_id: str,
    payloads: Iterable[JsonDict],
    engineer_user_id: str = ENGINEER_USER_ID,
) -> List[JsonDict]:
    return [make_component(api, report_id, p, engineer_user_id) for p in payloads]


def submit_report(
    api: ConversionApiClient, report_id: str, engineer_user_id: str = ENGINEER_USER_ID
) -> JsonDict:
    return get_success_data(api.submit_report(report_id, engineer_headers(engineer_user_id)))


def accept_report(
    api: ConversionApiClient,
    report_id: str,
    reviewer_user_id: str = PEER_USER_ID,
) -> JsonDict:
    return get_success_data(
        api.peer_review(
            report_id,
            peer_review_payload("ACCEPT", reviewer_user_id),
            peer_headers(reviewer_user_id),
        )
    )


def reject_report(
    api: ConversionApiClient,
    report_id: str,
    reviewer_user_id: str = PEER_USER_ID,
    review_note: Optional[str] = None,
) -> JsonDict:
    return get_success_data(
        api.peer_review(
            report_id,
            peer_review_payload("REJECT", reviewer_user_id, review_note),
            peer_headers(reviewer_user_id),
        )
    )


def report_version(api: ConversionApiClient, report_id: str) -> int:
    """The report's current version, read back for the OCC token."""
    return get_success_data(api.get_report(report_id, engineer_headers()))["version"]


def project_version(api: ConversionApiClient, project_id: str) -> int:
    return get_success_data(api.get_project(project_id, sponsor_headers()))["version"]


def unit_version(api: ConversionApiClient, unit_id: str) -> int:
    return get_success_data(api.get_unit(unit_id, sponsor_headers()))["version"]


def batch_version(api: ConversionApiClient, batch_id: str) -> int:
    return get_success_data(api.get_batch(batch_id, sponsor_headers()))["version"]


def make_assessment(
    api: ConversionApiClient,
    report_id: str,
    variant: str = "AS_INSPECTED",
    actor_user_id: str = PEER_USER_ID,
    expected_version: Optional[int] = None,
) -> JsonDict:
    """Create a suitability assessment, reading the report's version first."""
    version = (
        expected_version
        if expected_version is not None
        else report_version(api, report_id)
    )
    return get_success_data(
        api.create_assessment(
            report_id,
            assessment_payload(variant, version),
            peer_headers(actor_user_id),
        )
    )


# --- tier 2: an accepted report and a passed suitability gate ---------------
def make_accepted_report(
    api: ConversionApiClient,
    project_id: str,
    components: Optional[Sequence[JsonDict]] = None,
    report_label: str = "ER-1",
    engineer_user_id: str = ENGINEER_USER_ID,
    reviewer_user_id: str = PEER_USER_ID,
    accept: bool = True,
) -> Tuple[JsonDict, List[JsonDict]]:
    """Draft a report, inventory it, submit it and have a peer accept it.

    With ``accept`` false the report is left in ``SUBMITTED`` so that a later
    peer decision is still open to the caller.
    """
    payloads = list(
        components
        if components is not None
        else [component_payload("ROOF", 30, 10, 10000000, 0, "EXCELLENT")]
    )
    report = make_report(api, project_id, report_label, engineer_user_id=engineer_user_id)
    rows = make_components(api, report["id"], payloads, engineer_user_id)
    submit_report(api, report["id"], engineer_user_id)
    if accept:
        accept_report(api, report["id"], reviewer_user_id)
    return report, rows


def make_passed_gate(
    api: ConversionApiClient,
    project_id: str,
    components: Optional[Sequence[JsonDict]] = None,
    report_label: str = "ER-1",
    variant: str = "AS_INSPECTED",
    accept: bool = True,
) -> Dict[str, object]:
    """Take a project all the way to `suitability_gate` PASSED."""
    report, rows = make_accepted_report(
        api, project_id, components, report_label, accept=accept
    )
    assessment = make_assessment(api, report["id"], variant)
    return {"report": report, "components": rows, "assessment": assessment}


# --- tier 3: a platted declaration -----------------------------------------
def make_package(
    api: ConversionApiClient,
    project_id: str,
    boundary_convention: str = "CENTERLINE",
    declaration_text_ref: str = "decl/ref-a",
    bylaws_text_ref: str = "bylaws/ref-a",
) -> JsonDict:
    return get_success_data(
        api.create_package(
            project_id,
            package_payload(declaration_text_ref, bylaws_text_ref, boundary_convention),
            sponsor_headers(),
        )
    )


def make_unit(
    api: ConversionApiClient,
    package_id: str,
    unit_number: str,
    base_percentage_interest_bp: int,
    floor_level: int = 1,
    heated_square_feet: int = 900,
    boundary_note: str = "as platted",
) -> JsonDict:
    return get_success_data(
        api.create_unit(
            package_id,
            unit_payload(
                unit_number,
                base_percentage_interest_bp,
                floor_level,
                heated_square_feet,
                boundary_note,
            ),
            sponsor_headers(),
        )
    )


def make_units(
    api: ConversionApiClient, package_id: str, specs: Sequence[Tuple[str, int]]
) -> List[JsonDict]:
    """Create one unit per (unit_number, base_percentage_interest_bp) pair."""
    return [make_unit(api, package_id, number, bp) for number, bp in specs]


def certify_plat(api: ConversionApiClient, package_id: str) -> JsonDict:
    return get_success_data(api.certify_plat(package_id, sponsor_headers()))


def record_package(api: ConversionApiClient, package_id: str) -> JsonDict:
    return get_success_data(api.record_package(package_id, sponsor_headers()))


# --- tier 3b: reserves, budget and adoption ---------------------------------
def make_reserve_study(
    api: ConversionApiClient,
    project_id: str,
    report_id: str,
    method: str = "COMPONENT_METHOD",
    opening_reserve_balance_cents: Optional[int] = None,
) -> JsonDict:
    return get_success_data(
        api.create_reserve_study(
            project_id,
            reserve_study_payload(report_id, method, opening_reserve_balance_cents),
            sponsor_headers(),
        )
    )


def make_budget(
    api: ConversionApiClient,
    project_id: str,
    reserve_study_id: str,
    annual_operating_expense_cents: int,
    fiscal_year_label: str = "FY2027",
    expected_version: Optional[int] = None,
) -> JsonDict:
    """Create a budget, reading the project's version first for the OCC token."""
    version = (
        expected_version if expected_version is not None else project_version(api, project_id)
    )
    return get_success_data(
        api.create_budget(
            project_id,
            budget_payload(
                reserve_study_id,
                annual_operating_expense_cents,
                version,
                fiscal_year_label,
            ),
            sponsor_headers(),
        )
    )


def adopt_budget(api: ConversionApiClient, budget_id: str) -> JsonDict:
    return get_success_data(api.adopt_budget(budget_id, sponsor_headers()))


# --- tier 4: the public offering statement ----------------------------------
def make_pos(
    api: ConversionApiClient,
    project_id: str,
    package_id: str,
    reserve_study_id: str,
    budget_id: str,
) -> JsonDict:
    return get_success_data(
        api.create_pos(
            project_id,
            pos_payload(package_id, reserve_study_id, budget_id),
            sponsor_headers(),
        )
    )


def write_section(
    api: ConversionApiClient,
    pos_id: str,
    section_code: str,
    body_ref: str,
    word_count: int = 180,
    attested_by_user_id: Optional[str] = SPONSOR_USER_ID,
) -> JsonDict:
    return get_success_data(
        api.put_section(
            pos_id,
            section_code,
            section_payload(body_ref, word_count, attested_by_user_id),
            sponsor_headers(),
        )
    )


def complete_all_sections(
    api: ConversionApiClient,
    pos_id: str,
    body_ref_prefix: str = "s3://pos/sec",
    word_count: int = 180,
    skip: Sequence[str] = (),
) -> None:
    """Write every statutory section as COMPLETE, optionally skipping some."""
    for code in POS_SECTION_CODES:
        if code in skip:
            continue
        write_section(
            api,
            pos_id,
            code,
            "%s-%s" % (body_ref_prefix, code.lower()),
            word_count,
            SPONSOR_USER_ID,
        )


def confer_effectiveness(api: ConversionApiClient, pos_id: str) -> JsonDict:
    return get_success_data(api.confer_effectiveness(pos_id, regulator_headers()))


# --- tier 5: the composite preamble shared by most of the estate ------------
def build_registered_project(
    api: ConversionApiClient,
    building_address: str = "44 Cove Lane, Bangor ME",
    year_built: int = 1968,
    unit_specs: Sequence[Tuple[str, int]] = (("A-1", 10000),),
    components: Optional[Sequence[JsonDict]] = None,
    annual_operating_expense_cents: int = 875000,
    boundary_convention: str = "CENTERLINE",
    reserve_method: str = "COMPONENT_METHOD",
    opening_reserve_balance_cents: Optional[int] = None,
    total_unit_count: Optional[int] = None,
    max_overlapping_remediations: Optional[int] = None,
    section_word_count: int = 180,
    body_ref_prefix: str = "s3://pos/sec",
    with_pos: bool = True,
    confer: bool = True,
    accept: bool = True,
) -> Dict[str, object]:
    """Drive one project from creation to a recorded declaration.

    The chain is the PRD's own order: a peer-accepted engineering report, a
    passing suitability assessment, a platted declaration over the included
    unit set, an adopted budget over an adopted reserve study, the recorded
    declaration, and — unless the caller opts out — a public offering statement
    whose nine sections are complete and which the regulator has made
    effective.
    """
    project = make_project(
        api,
        building_address,
        year_built,
        total_unit_count if total_unit_count is not None else len(unit_specs),
        max_overlapping_remediations=max_overlapping_remediations,
    )
    gate = make_passed_gate(api, project["id"], components, accept=accept)
    package = make_package(api, project["id"], boundary_convention)
    units = make_units(api, package["id"], unit_specs)
    certify_plat(api, package["id"])
    study = make_reserve_study(
        api,
        project["id"],
        gate["report"]["id"],
        reserve_method,
        opening_reserve_balance_cents,
    )
    budget = make_budget(
        api, project["id"], study["id"], annual_operating_expense_cents
    )
    adopt_budget(api, budget["id"])
    record_package(api, package["id"])
    built = {
        "project": project,
        "report": gate["report"],
        "components": gate["components"],
        "assessment": gate["assessment"],
        "package": package,
        "units": units,
        "reserve_study": study,
        "budget": budget,
        "pos": None,
    }
    if not with_pos:
        return built
    pos = make_pos(api, project["id"], package["id"], study["id"], budget["id"])
    complete_all_sections(api, pos["id"], body_ref_prefix, section_word_count)
    if confer:
        confer_effectiveness(api, pos["id"])
    built["pos"] = pos
    return built


# --- sales side -------------------------------------------------------------
def make_agreement(
    api: ConversionApiClient,
    unit_id: str,
    purchaser_name: str,
    purchaser_tax_id: str,
    purchaser_type: str,
    price_cents: int,
    deposit_cents: int,
    tenant_household_id: Optional[str] = None,
    expected_version: Optional[int] = None,
) -> JsonDict:
    """Sign an agreement on a unit, reading the unit's version for the token."""
    version = (
        expected_version if expected_version is not None else unit_version(api, unit_id)
    )
    return get_success_data(
        api.create_agreement(
            unit_id,
            agreement_payload(
                purchaser_name,
                purchaser_tax_id,
                purchaser_type,
                price_cents,
                deposit_cents,
                version,
                tenant_household_id,
            ),
            sponsor_headers(),
        )
    )


def deliver_pos(api: ConversionApiClient, agreement_id: str) -> JsonDict:
    return get_success_data(api.deliver_pos(agreement_id, sponsor_headers()))


def fund_escrow(api: ConversionApiClient, agreement_id: str, amount_cents: int) -> JsonDict:
    return get_success_data(
        api.deposit_escrow(agreement_id, amount_cents, escrow_headers())
    )


def harden(api: ConversionApiClient, agreement_id: str) -> JsonDict:
    return get_success_data(api.harden_agreement(agreement_id, sponsor_headers()))


def make_batch(
    api: ConversionApiClient,
    project_id: str,
    batch_sequence_no: int,
    window_start_at: str,
    window_end_at: str,
    min_presale_threshold_pct: float = 50.00,
    min_absolute_unit_count: int = 1,
) -> JsonDict:
    return get_success_data(
        api.create_batch(
            project_id,
            batch_payload(
                batch_sequence_no,
                window_start_at,
                window_end_at,
                min_presale_threshold_pct,
                min_absolute_unit_count,
            ),
            sponsor_headers(),
        )
    )


def assign_agreement(
    api: ConversionApiClient,
    batch_id: str,
    agreement_id: str,
    expected_version: Optional[int] = None,
) -> JsonDict:
    """Assign an agreement to a batch, reading the batch's version first."""
    version = (
        expected_version if expected_version is not None else batch_version(api, batch_id)
    )
    return get_success_data(
        api.assign_agreement(
            batch_id, assignment_payload(agreement_id, version), sponsor_headers()
        )
    )


def evaluate_threshold(api: ConversionApiClient, batch_id: str) -> JsonDict:
    return get_success_data(api.evaluate_threshold(batch_id, sponsor_headers()))


def release_batch(api: ConversionApiClient, batch_id: str) -> JsonDict:
    return get_success_data(api.release_batch(batch_id, escrow_headers()))


# --- tenants ----------------------------------------------------------------
def make_household(
    api: ConversionApiClient,
    project_id: str,
    household_label: str,
    tenancy_start_date: str,
    monthly_rent_cents: int,
    protected_class: Optional[str] = None,
    occupied_unit_id: Optional[str] = None,
) -> JsonDict:
    return get_success_data(
        api.create_household(
            project_id,
            household_payload(
                household_label,
                tenancy_start_date,
                monthly_rent_cents,
                protected_class,
                occupied_unit_id,
            ),
            sponsor_headers(),
        )
    )


def serve_notice(api: ConversionApiClient, household_id: str) -> JsonDict:
    return get_success_data(api.serve_notice(household_id, sponsor_headers()))


# --- warranty ---------------------------------------------------------------
def make_claim(
    api: ConversionApiClient,
    project_id: str,
    major_component_id: str,
    defect_description: str,
    claimed_cost_cents: int,
    reported_by_unit_id: Optional[str] = None,
) -> JsonDict:
    from .factories import claim_payload

    return get_success_data(
        api.create_claim(
            project_id,
            claim_payload(
                major_component_id,
                defect_description,
                claimed_cost_cents,
                reported_by_unit_id,
            ),
            sponsor_headers(),
        )
    )


def triage_claim(
    api: ConversionApiClient,
    claim_id: str,
    decision: str,
    triage_note: Optional[str] = None,
) -> JsonDict:
    from .factories import triage_payload

    return get_success_data(
        api.triage_claim(claim_id, triage_payload(decision, triage_note), sponsor_headers())
    )


def schedule_remediation(
    api: ConversionApiClient, claim_id: str, start_at: str, end_at: str
) -> JsonDict:
    from .factories import remediation_payload

    return get_success_data(
        api.schedule_remediation(
            claim_id, remediation_payload(start_at, end_at), sponsor_headers()
        )
    )
