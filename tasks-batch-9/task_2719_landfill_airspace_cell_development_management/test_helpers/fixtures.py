"""Composite setup helpers.

Each helper builds its preconditions from scratch through PRD-declared endpoints
only, so every test starts from an empty database. Setup calls use the lenient
``get_success_data`` validator so a broken precondition surfaces as a setup
failure rather than as a confusing assertion failure.

Identity threading: ``SiteOperator`` and ``ScaleOperator`` carry the acting
``Landfill``'s ``id`` in ``X-User-ID``, so every ownership-gated write below is
issued with headers built from the real landfill id.
"""
from typing import Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_DEFAULT_UTC
from .factories import (
    aerial_survey_payload,
    cell_payload,
    closure_cost_estimate_payload,
    gas_well_payload,
    gas_well_tune_payload,
    host_community_agreement_payload,
    landfill_payload,
    leachate_shipment_payload,
    liner_qa_package_payload,
    operating_day_payload,
    special_waste_approval_payload,
    surface_emission_scan_payload,
    treatment_agreement_payload,
    waste_load_payload,
)
from .test_users import (
    TEST_USERS,
    make_scale_operator_headers,
    make_site_operator_headers,
)

PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]
CQA_ENGINEER = TEST_USERS["cqa_engineer_headers"]
CQA_ENGINEER_ALT = TEST_USERS["cqa_engineer_alt_headers"]
SURVEYOR = TEST_USERS["surveyor_headers"]
ENV_MANAGER = TEST_USERS["environmental_manager_headers"]
AGENCY = TEST_USERS["regulatory_agency_headers"]
FINANCE_FILER = TEST_USERS["finance_filer_headers"]
FINANCE_CERTIFIER = TEST_USERS["finance_certifier_headers"]


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------
def set_clock(current_utc: str) -> dict:
    """Move the logical clock. Every 'now' rule in the system reads it."""
    return get_success_data(api_client.set_current_utc(current_utc, PLATFORM_ADMIN))


def reset_clock() -> dict:
    """Return the logical clock to the instant it reads before any client sets it."""
    return set_clock(CLOCK_DEFAULT_UTC)


# --------------------------------------------------------------------------
# Tier 1 — single-resource creation and simple progressions
# --------------------------------------------------------------------------
def create_landfill(**overrides) -> dict:
    """Register a permitted site. Returns the Landfill row."""
    return get_success_data(
        api_client.create_landfill(landfill_payload(**overrides), PLATFORM_ADMIN)
    )


def read_landfill(landfill_id: str) -> dict:
    return get_success_data(api_client.get_landfill(landfill_id, PLATFORM_ADMIN))


def landfill_version(landfill_id: str) -> int:
    """The landfill version to quote in an ``expected_landfill_version`` field."""
    return int(read_landfill(landfill_id)["version"])


def create_cell(landfill_id: str, **overrides) -> dict:
    """Create a cell in DESIGN under the named site."""
    return get_success_data(
        api_client.create_cell(
            cell_payload(landfill_id, **overrides), make_site_operator_headers(landfill_id)
        )
    )


def begin_construction(landfill_id: str, cell_id: str) -> dict:
    return get_success_data(
        api_client.begin_cell_construction(cell_id, make_site_operator_headers(landfill_id))
    )


def create_cell_under_construction(landfill_id: str, **overrides) -> dict:
    """Create a cell and break ground on it: DESIGN then UNDER_CONSTRUCTION."""
    cell = create_cell(landfill_id, **overrides)
    return begin_construction(landfill_id, cell["id"])


def submit_liner_qa_package(landfill_id: str, cell_id: str, **overrides) -> dict:
    """Submit liner CQA documentation. Defaults score 100.00."""
    return get_success_data(
        api_client.create_liner_qa_package(
            liner_qa_package_payload(cell_id, **overrides),
            make_site_operator_headers(landfill_id),
        )
    )


def begin_liner_review(package_id: str, reviewer_headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.begin_liner_qa_review(package_id, reviewer_headers or CQA_ENGINEER)
    )


def approve_liner_package(
    package_id: str,
    certification_reference: str = "CQA-2026-001",
    reviewer_headers: Optional[dict] = None,
) -> dict:
    return get_success_data(
        api_client.approve_liner_qa_package(
            package_id,
            {"certification_reference": certification_reference},
            reviewer_headers or CQA_ENGINEER,
        )
    )


def setup_qa_certified_cell(landfill_id: str, cell_overrides=None, qa_overrides=None) -> dict:
    """Drive one cell from DESIGN to QA_CERTIFIED through the liner CQA cycle.

    Returns ``{"cell": ..., "package": ...}`` with both rows re-read after the
    approval cascade.
    """
    cell = create_cell_under_construction(landfill_id, **(cell_overrides or {}))
    package = submit_liner_qa_package(landfill_id, cell["id"], **(qa_overrides or {}))
    begin_liner_review(package["id"])
    package = approve_liner_package(package["id"])
    cell = get_success_data(api_client.get_cell(cell["id"], PLATFORM_ADMIN))
    return {"cell": cell, "package": package}


# --------------------------------------------------------------------------
# Tier 2 — closure cost, financial assurance and the host agreement
# --------------------------------------------------------------------------
def file_closure_estimate(landfill_id: str, expected_landfill_version=None, **overrides) -> dict:
    """File a DRAFT closure and post-closure cost update against the site.

    The filing carries the landfill version the filer believes is current, so the
    caller may pin a deliberately stale value.
    """
    if expected_landfill_version is None:
        expected_landfill_version = landfill_version(landfill_id)
    payload = closure_cost_estimate_payload(
        landfill_id, expected_landfill_version, **overrides
    )
    return get_success_data(api_client.create_closure_cost_estimate(payload, FINANCE_FILER))


def certify_closure_estimate(estimate_id: str, headers: Optional[dict] = None) -> dict:
    """Certify a filed update. The certifier may not be the filer."""
    return get_success_data(
        api_client.certify_closure_cost_estimate(estimate_id, headers or FINANCE_CERTIFIER)
    )


def post_assurance_instrument(
    estimate_id: str, funded_amount, instrument_type: str = "TRUST_FUND"
) -> dict:
    return get_success_data(
        api_client.fund_assurance(
            estimate_id,
            {"instrument_type": instrument_type, "funded_amount": funded_amount},
            FINANCE_FILER,
        )
    )


def setup_funded_assurance(
    landfill_id: str, instrument_type: str = "TRUST_FUND", estimate_overrides=None
) -> dict:
    """File, certify and fully fund one cost update so the site reads FUNDED.

    The posted instrument matches the certified requirement exactly, which drives
    the shortfall to zero.
    """
    estimate = file_closure_estimate(landfill_id, **(estimate_overrides or {}))
    estimate = certify_closure_estimate(estimate["id"])
    estimate = post_assurance_instrument(
        estimate["id"], estimate["required_assurance_amount"], instrument_type
    )
    return estimate


def draft_host_agreement(landfill_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_host_community_agreement(
            host_community_agreement_payload(landfill_id, **overrides), FINANCE_FILER
        )
    )


def execute_host_agreement(agreement_id: str, landfill_id: str, expected_landfill_version=None) -> dict:
    if expected_landfill_version is None:
        expected_landfill_version = landfill_version(landfill_id)
    return get_success_data(
        api_client.execute_host_community_agreement(
            agreement_id,
            {"expected_landfill_version": expected_landfill_version},
            FINANCE_FILER,
        )
    )


def setup_executed_host_agreement(landfill_id: str, **overrides) -> dict:
    """Draft one agreement and take it live."""
    agreement = draft_host_agreement(landfill_id, **overrides)
    return execute_host_agreement(agreement["id"], landfill_id)


# --------------------------------------------------------------------------
# Tier 3 — the regulatory branch and the working face
# --------------------------------------------------------------------------
def authorize_waste_placement(
    cell_id: str, approval_reference: str = "AGY-2026-001", headers: Optional[dict] = None
) -> dict:
    return get_success_data(
        api_client.authorize_waste_placement(
            cell_id, {"approval_reference": approval_reference}, headers or AGENCY
        )
    )


def activate_cell(landfill_id: str, cell_id: str) -> dict:
    return get_success_data(
        api_client.activate_cell(cell_id, make_site_operator_headers(landfill_id))
    )


def close_cell(landfill_id: str, cell_id: str, final_cover_reference: str = "FC-2026-01") -> dict:
    return get_success_data(
        api_client.close_cell(
            cell_id,
            {"final_cover_reference": final_cover_reference},
            make_site_operator_headers(landfill_id),
        )
    )


def setup_ready_for_waste_cell(
    landfill_overrides=None,
    cell_overrides=None,
    qa_overrides=None,
    estimate_overrides=None,
    instrument_type: str = "TRUST_FUND",
) -> dict:
    """Build a site whose single cell has cleared CQA, funding and the agency.

    Sequence: register the site, build and certify the cell's liner, then file,
    certify and fully fund the closure cost update — the funding has to follow the
    liner approval, because certifying new airspace is what knocks the assurance
    posture down in the first place — and finally take the agency authorization.
    """
    landfill = create_landfill(**(landfill_overrides or {}))
    certified = setup_qa_certified_cell(landfill["id"], cell_overrides, qa_overrides)
    estimate = setup_funded_assurance(
        landfill["id"], instrument_type=instrument_type, estimate_overrides=estimate_overrides
    )
    cell = authorize_waste_placement(certified["cell"]["id"])
    return {
        "landfill": read_landfill(landfill["id"]),
        "cell": cell,
        "package": certified["package"],
        "estimate": estimate,
        "site_headers": make_site_operator_headers(landfill["id"]),
        "scale_headers": make_scale_operator_headers(landfill["id"]),
    }


def setup_active_site(
    landfill_overrides=None,
    cell_overrides=None,
    qa_overrides=None,
    estimate_overrides=None,
    instrument_type: str = "TRUST_FUND",
    agreement_overrides=None,
    with_host_agreement: bool = True,
) -> dict:
    """A site with one ACTIVE cell, ready to open an operating day.

    When ``with_host_agreement`` is set the site also carries one live host
    community agreement, which is what lets host fees settle on day close.
    """
    site = setup_ready_for_waste_cell(
        landfill_overrides=landfill_overrides,
        cell_overrides=cell_overrides,
        qa_overrides=qa_overrides,
        estimate_overrides=estimate_overrides,
        instrument_type=instrument_type,
    )
    site["cell"] = activate_cell(site["landfill"]["id"], site["cell"]["id"])
    if with_host_agreement:
        site["agreement"] = setup_executed_host_agreement(
            site["landfill"]["id"], **(agreement_overrides or {})
        )
    else:
        site["agreement"] = None
    site["landfill"] = read_landfill(site["landfill"]["id"])
    return site


# --------------------------------------------------------------------------
# Tier 4 — operating days and the scale house
# --------------------------------------------------------------------------
def open_operating_day(landfill_id: str, active_cell_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_operating_day(
            operating_day_payload(landfill_id, active_cell_id, **overrides),
            make_site_operator_headers(landfill_id),
        )
    )


def close_operating_day(landfill_id: str, operating_day_id: str) -> dict:
    """Close the day. The close request carries no body at all."""
    return get_success_data(
        api_client.close_operating_day(
            operating_day_id, make_site_operator_headers(landfill_id)
        )
    )


def amend_operating_day(landfill_id: str, operating_day_id: str, amend_reason: str) -> dict:
    return get_success_data(
        api_client.amend_operating_day(
            operating_day_id,
            {"amend_reason": amend_reason},
            make_site_operator_headers(landfill_id),
        )
    )


def setup_open_day(
    landfill_overrides=None,
    cell_overrides=None,
    qa_overrides=None,
    estimate_overrides=None,
    agreement_overrides=None,
    day_overrides=None,
    with_host_agreement: bool = True,
) -> dict:
    """An active site with one OPEN operating day carrying the working face.

    Returns the ``setup_active_site`` dictionary with a ``day`` key added.
    """
    site = setup_active_site(
        landfill_overrides=landfill_overrides,
        cell_overrides=cell_overrides,
        qa_overrides=qa_overrides,
        estimate_overrides=estimate_overrides,
        agreement_overrides=agreement_overrides,
        with_host_agreement=with_host_agreement,
    )
    site["day"] = open_operating_day(
        site["landfill"]["id"], site["cell"]["id"], **(day_overrides or {})
    )
    return site


def receive_load(landfill_id: str, operating_day_id: str, **overrides) -> dict:
    """Weigh a truck in against an open day. Opens PENDING / UNBILLED."""
    return get_success_data(
        api_client.create_waste_load(
            waste_load_payload(operating_day_id, **overrides),
            make_scale_operator_headers(landfill_id),
        )
    )


def clear_screening(landfill_id: str, waste_load_id: str) -> dict:
    """Clear a load for placement, which also prices the manifest tonnage."""
    return get_success_data(
        api_client.clear_screening(
            waste_load_id, None, make_scale_operator_headers(landfill_id)
        )
    )


def flag_load(landfill_id: str, waste_load_id: str, screening_state_reason: str) -> dict:
    return get_success_data(
        api_client.flag_waste_load(
            waste_load_id,
            {"screening_state_reason": screening_state_reason},
            make_scale_operator_headers(landfill_id),
        )
    )


def reject_load(landfill_id: str, waste_load_id: str, screening_state_reason: str) -> dict:
    return get_success_data(
        api_client.reject_waste_load(
            waste_load_id,
            {"screening_state_reason": screening_state_reason},
            make_scale_operator_headers(landfill_id),
        )
    )


def certify_weight(landfill_id: str, waste_load_id: str, certified_net_tons) -> dict:
    return get_success_data(
        api_client.certify_weight(
            waste_load_id,
            {"certified_net_tons": certified_net_tons},
            make_scale_operator_headers(landfill_id),
        )
    )


def place_certified_load(landfill_id: str, operating_day_id: str, certified_net_tons, **overrides) -> dict:
    """Receive, clear and certify one load, leaving it CLEARED / PROVISIONAL.

    This is the shape a day close expects: no load still in screening and every
    cleared load carrying a certified weight.
    """
    load = receive_load(landfill_id, operating_day_id, **overrides)
    clear_screening(landfill_id, load["id"])
    return certify_weight(landfill_id, load["id"], certified_net_tons)


# --------------------------------------------------------------------------
# Tier 4 — special-waste profiles
# --------------------------------------------------------------------------
def request_special_waste_approval(landfill_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_special_waste_approval(
            special_waste_approval_payload(landfill_id, **overrides), ENV_MANAGER
        )
    )


def approve_special_waste_approval(
    approval_id: str, decision_reason: str = "Characterisation accepted"
) -> dict:
    return get_success_data(
        api_client.approve_special_waste_approval(
            approval_id, {"decision_reason": decision_reason}, ENV_MANAGER
        )
    )


def setup_approved_special_waste(landfill_id: str, **overrides) -> dict:
    """Request and approve one profile, so it can back a special-waste load."""
    approval = request_special_waste_approval(landfill_id, **overrides)
    return approve_special_waste_approval(approval["id"])


# --------------------------------------------------------------------------
# Tier 4 — leachate contracts and tanker hauls
# --------------------------------------------------------------------------
def register_treatment_agreement(landfill_id: str, **overrides) -> dict:
    """Register a receiving plant contract. Opens ACTIVE."""
    return get_success_data(
        api_client.create_treatment_agreement(
            treatment_agreement_payload(landfill_id, **overrides), ENV_MANAGER
        )
    )


def suspend_treatment_agreement(agreement_id: str, suspension_reason: str) -> dict:
    return get_success_data(
        api_client.suspend_treatment_agreement(
            agreement_id, {"suspension_reason": suspension_reason}, ENV_MANAGER
        )
    )


def book_shipment(landfill_id: str, treatment_agreement_id: str, **overrides) -> dict:
    """Book a tanker haul against a contract. Opens SCHEDULED."""
    return get_success_data(
        api_client.create_leachate_shipment(
            leachate_shipment_payload(treatment_agreement_id, **overrides),
            make_site_operator_headers(landfill_id),
        )
    )


def dispatch_shipment(landfill_id: str, shipment_id: str, hauler_ref: str = "TNK-0001") -> dict:
    return get_success_data(
        api_client.dispatch_leachate_shipment(
            shipment_id, {"hauler_ref": hauler_ref}, make_site_operator_headers(landfill_id)
        )
    )


def accept_shipment(landfill_id: str, shipment_id: str) -> dict:
    """Confirm acceptance at the receiving gate, which writes the invoice total."""
    return get_success_data(
        api_client.confirm_leachate_acceptance(
            shipment_id, make_site_operator_headers(landfill_id)
        )
    )


def setup_dispatched_shipment(landfill_id: str, treatment_agreement_id: str, **overrides) -> dict:
    shipment = book_shipment(landfill_id, treatment_agreement_id, **overrides)
    return dispatch_shipment(landfill_id, shipment["id"])


# --------------------------------------------------------------------------
# Tier 4 — the gas wellfield and surface-emission monitoring
# --------------------------------------------------------------------------
def drill_gas_well(cell_id: str, **overrides) -> dict:
    """Record a new extraction well. Opens DRILLED."""
    return get_success_data(
        api_client.create_gas_well(gas_well_payload(cell_id, **overrides), ENV_MANAGER)
    )


def connect_gas_well(well_id: str) -> dict:
    return get_success_data(api_client.connect_gas_well(well_id, ENV_MANAGER))


def tune_gas_well(well_id: str, **overrides) -> dict:
    """Record a wellhead tuning visit. Defaults are in specification."""
    return get_success_data(
        api_client.tune_gas_well(well_id, gas_well_tune_payload(**overrides), ENV_MANAGER)
    )


def take_gas_well_offline(well_id: str, offline_reason: str = "Valved out") -> dict:
    return get_success_data(
        api_client.take_gas_well_offline(
            well_id, {"offline_reason": offline_reason}, ENV_MANAGER
        )
    )


def setup_connected_well(cell_id: str, **overrides) -> dict:
    """Drill a well and tie it into the header, leaving it CONNECTED."""
    well = drill_gas_well(cell_id, **overrides)
    return connect_gas_well(well["id"])


def setup_online_well(cell_id: str, **overrides) -> dict:
    """Drill, connect and tune a well within specification, leaving it ONLINE."""
    well = setup_connected_well(cell_id, **overrides)
    return tune_gas_well(well["id"])


def record_surface_scan(landfill_id: str, **overrides) -> dict:
    """Record a surface-emission walkover of the site."""
    return get_success_data(
        api_client.create_surface_emission_scan(
            surface_emission_scan_payload(landfill_id, **overrides), ENV_MANAGER
        )
    )


def resolve_surface_scan(scan_id: str, remediation_note: str = "Cover repaired and re-walked") -> dict:
    return get_success_data(
        api_client.resolve_surface_emission_scan(
            scan_id, {"remediation_note": remediation_note}, ENV_MANAGER
        )
    )


# --------------------------------------------------------------------------
# Tier 4 — aerial surveys
# --------------------------------------------------------------------------
def record_aerial_survey(landfill_id: str, **overrides) -> dict:
    """Record a photogrammetric flight reduced against the permitted contours."""
    return get_success_data(
        api_client.create_aerial_survey(
            aerial_survey_payload(landfill_id, **overrides), SURVEYOR
        )
    )


def void_aerial_survey(survey_id: str, void_reason: str = "Reduction error found") -> dict:
    return get_success_data(
        api_client.void_aerial_survey(survey_id, {"void_reason": void_reason}, SURVEYOR)
    )


# --------------------------------------------------------------------------
# Site posture
# --------------------------------------------------------------------------
def set_operating_status(landfill_id: str, operating_status: str) -> dict:
    """Move the site's posture administratively."""
    return get_success_data(
        api_client.set_operating_status(
            landfill_id, {"operating_status": operating_status}, PLATFORM_ADMIN
        )
    )
