"""Composite state builders and pytest fixtures.

The harness restarts the server before every test, so every precondition is
built from scratch here through the PRD's own endpoints. The builders are
ordinary functions taking an ``OpticsApiClient`` so a test may compose exactly
the state it needs; the pytest fixtures at the bottom wrap the shapes that
recur most.

Every builder accepts ``**overrides`` which are merged into the payload of the
entity it creates, and every setup call is validated leniently through
``get_success_data`` so a broken precondition fails loudly and early.
"""

from typing import Any, Dict, List, Optional, Sequence

import pytest
from prd_bench_local_runner.testing import get_success_data

from .api_client import OpticsApiClient
from .constants import PASSING_SPECTRAL_TRACE
from .factories import (
    build_assembly_component_payload,
    build_assembly_payload,
    build_cement_payload,
    build_certification_payload,
    build_coating_chamber_payload,
    build_coating_run_payload,
    build_complete_run_payload,
    build_document_payload,
    build_documentation_package_payload,
    build_export_classification_payload,
    build_glass_lot_payload,
    build_inspection_record_payload,
    build_instrument_payload,
    build_license_decision_payload,
    build_metrology_report_payload,
    build_mount_payload,
    build_optical_design_payload,
    build_process_run_payload,
    build_review_payload,
    build_spectral_verification_payload,
    build_tolerance_allocation_payload,
    build_work_order_payload,
)
from .test_users import (
    make_export_compliance_officer_headers,
    make_metrology_technician_headers,
    make_optics_engineer_headers,
    make_plant_admin_headers,
    make_process_technician_headers,
    make_procurement_officer_headers,
    make_quality_manager_headers,
    MT_RECORDER,
    MT_SIGNER,
    ECO_CLASSIFIER,
    ECO_DECIDER,
    QM_PRIMARY,
    QM_SECOND,
)
from .types import Payload


# ----------------------------------------------------------------------
# Tier 1: single entities
# ----------------------------------------------------------------------
def create_design(client: OpticsApiClient, **overrides: Any) -> Dict[str, Any]:
    """Lodge one optical design in DRAFT."""
    payload = build_optical_design_payload(**overrides)
    return get_success_data(
        client.create_optical_design(payload, make_optics_engineer_headers())
    )


def add_allocation(
    client: OpticsApiClient, design_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Add one error contributor to a draft design's tolerance budget."""
    payload = build_tolerance_allocation_payload(**overrides)
    return get_success_data(
        client.create_tolerance_allocation(
            design_id, payload, make_optics_engineer_headers()
        )
    )


def create_glass_lot(client: OpticsApiClient, **overrides: Any) -> Dict[str, Any]:
    """Book one melt lot into quarantine."""
    payload = build_glass_lot_payload(**overrides)
    return get_success_data(
        client.create_glass_lot(payload, make_procurement_officer_headers())
    )


def create_instrument(client: OpticsApiClient, **overrides: Any) -> Dict[str, Any]:
    """Register one metrology station."""
    payload = build_instrument_payload(**overrides)
    return get_success_data(
        client.create_metrology_instrument(payload, make_plant_admin_headers())
    )


def create_chamber(client: OpticsApiClient, **overrides: Any) -> Dict[str, Any]:
    """Register one coating deposition chamber."""
    payload = build_coating_chamber_payload(**overrides)
    return get_success_data(
        client.create_coating_chamber(payload, make_plant_admin_headers())
    )


def set_clock(client: OpticsApiClient, current_utc: str) -> Dict[str, Any]:
    """Move the logical clock forward to an explicit instant."""
    return get_success_data(client.set_clock(current_utc, make_plant_admin_headers()))


# ----------------------------------------------------------------------
# Tier 2: state progression
# ----------------------------------------------------------------------
DEFAULT_ALLOCATION_SPECS: Sequence[Payload] = (
    {
        "contributor_type": "SURFACE_IRREGULARITY",
        "sensitivity_waves_per_unit": 1.5,
        "manufacturing_tolerance_units": 0.0250,
    },
)


def create_toleranced_design(
    client: OpticsApiClient,
    allocation_specs: Optional[Sequence[Payload]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Lodge a design, allocate its budget and run the dual-variant stack-up."""
    design = create_design(client, **overrides)
    specs = (
        DEFAULT_ALLOCATION_SPECS if allocation_specs is None else allocation_specs
    )
    for spec in specs:
        add_allocation(client, design["id"], **spec)
    return get_success_data(
        client.run_tolerance_analysis(design["id"], make_optics_engineer_headers())
    )


def create_released_design(
    client: OpticsApiClient,
    allocation_specs: Optional[Sequence[Payload]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Carry a design all the way from DRAFT to RELEASED."""
    design = create_toleranced_design(client, allocation_specs, **overrides)
    return get_success_data(
        client.release_optical_design(design["id"], make_optics_engineer_headers())
    )


def create_certified_lot(
    client: OpticsApiClient,
    certification_overrides: Optional[Payload] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Book a melt lot in and record its incoming-inspection certificate."""
    lot = create_glass_lot(client, **overrides)
    payload = build_certification_payload(**(certification_overrides or {}))
    return get_success_data(
        client.certify_glass_lot(lot["id"], payload, make_procurement_officer_headers())
    )


def open_work_order(
    client: OpticsApiClient,
    design_id: str,
    glass_lot_id: str,
    expected_glass_lot_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    """Open one fabrication work order, reserving blanks under the lot guard."""
    payload = build_work_order_payload(
        design_id, glass_lot_id, expected_glass_lot_version, **overrides
    )
    return get_success_data(
        client.create_work_order(payload, make_process_technician_headers())
    )


# ----------------------------------------------------------------------
# Tier 3: full-lifecycle shortcuts over the fabrication loop
# ----------------------------------------------------------------------
def setup_work_order(
    client: OpticsApiClient,
    design_overrides: Optional[Payload] = None,
    lot_overrides: Optional[Payload] = None,
    certification_overrides: Optional[Payload] = None,
    allocation_specs: Optional[Sequence[Payload]] = None,
    **work_order_overrides: Any,
) -> Dict[str, Any]:
    """A released design, a certified lot and one work order in BLANKS_RESERVED.

    Returns a context dict with ``design``, ``lot`` and ``work_order``.
    """
    design = create_released_design(
        client, allocation_specs, **(design_overrides or {})
    )
    lot = create_certified_lot(
        client, certification_overrides, **(lot_overrides or {})
    )
    work_order = open_work_order(
        client, design["id"], lot["id"], lot["version"], **work_order_overrides
    )
    return {"design": design, "lot": lot, "work_order": work_order}


def run_stage_pass(
    client: OpticsApiClient,
    work_order_id: str,
    instrument_id: str,
    run_stage: str,
    metrology_window_start_utc: str,
    metrology_window_end_utc: str,
    material_removed_nm: float = 800.0,
    report_overrides: Optional[Payload] = None,
    recorder_id: str = MT_RECORDER,
    signer_id: str = MT_SIGNER,
) -> Dict[str, Any]:
    """Schedule, start, complete, report and sign one machining pass.

    Returns a dict with ``run`` (after signature), ``report`` and ``signed``.
    """
    run = get_success_data(
        client.create_process_run(
            build_process_run_payload(
                work_order_id,
                instrument_id,
                run_stage=run_stage,
                metrology_window_start_utc=metrology_window_start_utc,
                metrology_window_end_utc=metrology_window_end_utc,
            ),
            make_process_technician_headers(),
        )
    )
    get_success_data(
        client.start_process_run(run["id"], make_process_technician_headers())
    )
    get_success_data(
        client.complete_process_run(
            run["id"],
            build_complete_run_payload(material_removed_nm),
            make_process_technician_headers(),
        )
    )
    report = get_success_data(
        client.create_metrology_report(
            build_metrology_report_payload(run["id"], **(report_overrides or {})),
            make_metrology_technician_headers(recorder_id),
        )
    )
    signed = get_success_data(
        client.sign_metrology_report(
            report["id"], make_metrology_technician_headers(signer_id)
        )
    )
    return {"run": run, "report": report, "signed": signed}


def advance_to_figure_accepted(
    client: OpticsApiClient,
    work_order_id: str,
    instrument_id: str,
    polishing_removal_nm: float = 800.0,
    figuring_removal_nm: float = 400.0,
) -> Dict[str, Any]:
    """Drive a work order from BLANKS_RESERVED to FIGURE_ACCEPTED.

    A polishing pass is accepted on figure and roughness, then a figuring pass
    is accepted on figure, roughness and transmitted wavefront.
    """
    polishing = run_stage_pass(
        client,
        work_order_id,
        instrument_id,
        "POLISHING",
        "2026-08-01T08:00:00Z",
        "2026-08-01T10:00:00Z",
        material_removed_nm=polishing_removal_nm,
        report_overrides={"surface_rms_waves": 0.0200, "surface_roughness_nm_rms": 0.8000},
    )
    figuring = run_stage_pass(
        client,
        work_order_id,
        instrument_id,
        "FIGURING",
        "2026-08-01T11:00:00Z",
        "2026-08-01T12:00:00Z",
        material_removed_nm=figuring_removal_nm,
        report_overrides={
            "surface_rms_waves": 0.0200,
            "surface_roughness_nm_rms": 0.8000,
            "transmitted_wavefront_rms_waves": 0.0500,
        },
    )
    return {"polishing": polishing, "figuring": figuring}


def setup_figure_accepted_work_order(
    client: OpticsApiClient,
    design_overrides: Optional[Payload] = None,
    lot_overrides: Optional[Payload] = None,
    instrument_overrides: Optional[Payload] = None,
    allocation_specs: Optional[Sequence[Payload]] = None,
    **work_order_overrides: Any,
) -> Dict[str, Any]:
    """A work order carried to FIGURE_ACCEPTED on a capable, calibrated station."""
    ctx = setup_work_order(
        client,
        design_overrides=design_overrides,
        lot_overrides=lot_overrides,
        allocation_specs=allocation_specs,
        **work_order_overrides,
    )
    ctx["instrument"] = create_instrument(client, **(instrument_overrides or {}))
    ctx["passes"] = advance_to_figure_accepted(
        client, ctx["work_order"]["id"], ctx["instrument"]["id"]
    )
    return ctx


# ----------------------------------------------------------------------
# Tier 3 continued: coating and the compliance dimension
# ----------------------------------------------------------------------
def coat_work_order(
    client: OpticsApiClient,
    work_order_id: str,
    chamber_id: str,
    spectral_samples: Optional[List[Dict[str, Any]]] = None,
    window_start_utc: str = "2026-08-02T08:00:00Z",
    window_end_utc: str = "2026-08-02T12:00:00Z",
) -> Dict[str, Any]:
    """Load a chamber, deposit and verify the spectrum for one work order."""
    coating_run = get_success_data(
        client.create_coating_run(
            build_coating_run_payload(
                work_order_id,
                chamber_id,
                window_start_utc=window_start_utc,
                window_end_utc=window_end_utc,
            ),
            make_process_technician_headers(),
        )
    )
    get_success_data(
        client.deposit_coating_run(coating_run["id"], make_process_technician_headers())
    )
    verified = get_success_data(
        client.verify_coating_spectrum(
            coating_run["id"],
            build_spectral_verification_payload(
                list(PASSING_SPECTRAL_TRACE)
                if spectral_samples is None
                else spectral_samples
            ),
            make_process_technician_headers(),
        )
    )
    return {"coating_run": coating_run, "verified": verified}


def setup_coated_work_order(
    client: OpticsApiClient,
    design_overrides: Optional[Payload] = None,
    lot_overrides: Optional[Payload] = None,
    instrument_overrides: Optional[Payload] = None,
    chamber_overrides: Optional[Payload] = None,
    allocation_specs: Optional[Sequence[Payload]] = None,
    **work_order_overrides: Any,
) -> Dict[str, Any]:
    """A work order carried all the way to COATED with a passing spectrum."""
    ctx = setup_figure_accepted_work_order(
        client,
        design_overrides=design_overrides,
        lot_overrides=lot_overrides,
        instrument_overrides=instrument_overrides,
        allocation_specs=allocation_specs,
        **work_order_overrides,
    )
    ctx["chamber"] = create_chamber(client, **(chamber_overrides or {}))
    ctx["coating"] = coat_work_order(
        client, ctx["work_order"]["id"], ctx["chamber"]["id"]
    )
    return ctx


def classify_design(
    client: OpticsApiClient,
    design_id: str,
    destination_country: str = "DE",
    classifier_id: str = ECO_CLASSIFIER,
    **overrides: Any,
) -> Dict[str, Any]:
    """Classify a design for export control against one destination."""
    return get_success_data(
        client.create_export_classification(
            build_export_classification_payload(
                design_id, destination_country=destination_country, **overrides
            ),
            make_export_compliance_officer_headers(classifier_id),
        )
    )


def clear_compliance(
    client: OpticsApiClient,
    design_id: str,
    work_order_id: str,
    destination_country: str = "DE",
) -> Dict[str, Any]:
    """Classify, screen and licence a work order through to CLEARED."""
    classification = classify_design(
        client, design_id, destination_country=destination_country
    )
    screened = get_success_data(
        client.compliance_screen_work_order(
            work_order_id, make_export_compliance_officer_headers(ECO_CLASSIFIER)
        )
    )
    decided = None
    if classification["classification_status"] == "LICENSE_REQUIRED":
        decided = get_success_data(
            client.record_license_decision(
                classification["id"],
                build_license_decision_payload("APPROVED"),
                make_export_compliance_officer_headers(ECO_DECIDER),
            )
        )
    return {
        "classification": classification,
        "screened": screened,
        "decided": decided,
    }


def setup_released_to_assembly_work_order(
    client: OpticsApiClient,
    destination_country: str = "DE",
    **kwargs: Any,
) -> Dict[str, Any]:
    """A coated, cleared work order released to assembly with blanks consumed."""
    ctx = setup_coated_work_order(client, **kwargs)
    ctx["compliance"] = clear_compliance(
        client,
        ctx["design"]["id"],
        ctx["work_order"]["id"],
        destination_country=destination_country,
    )
    ctx["released"] = get_success_data(
        client.release_work_order_to_assembly(
            ctx["work_order"]["id"], make_process_technician_headers()
        )
    )
    return ctx


# ----------------------------------------------------------------------
# Tier 4: assemblies, kitting and the alignment chain
# ----------------------------------------------------------------------
TWO_ELEMENT_SPECS: Sequence[Payload] = (
    {
        "slot_index": 1,
        "decenter_um": 10.0,
        "tilt_arcmin": 1.0,
        "element_wavefront_rms_waves": 0.0600,
    },
    {
        "slot_index": 2,
        "decenter_um": 10.0,
        "tilt_arcmin": 1.0,
        "element_wavefront_rms_waves": 0.0400,
    },
)

CANONICAL_TWO_ELEMENT_SPECS: Sequence[Payload] = (
    {
        "slot_index": 1,
        "decenter_um": 10.0,
        "tilt_arcmin": 1.0,
        "element_wavefront_rms_waves": 0.0600,
    },
    {
        "slot_index": 2,
        "decenter_um": 12.0,
        "tilt_arcmin": 0.5,
        "element_wavefront_rms_waves": 0.0500,
    },
)


def create_assembly(
    client: OpticsApiClient, design_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Open one assembly build record in KITTED."""
    return get_success_data(
        client.create_assembly(
            build_assembly_payload(design_id, **overrides),
            make_process_technician_headers(),
        )
    )


def kit_component(
    client: OpticsApiClient,
    assembly_id: str,
    work_order_id: str,
    expected_assembly_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    """Kit one finished element into an assembly slot under the version guard."""
    return get_success_data(
        client.create_assembly_component(
            build_assembly_component_payload(
                assembly_id, work_order_id, expected_assembly_version, **overrides
            ),
            make_process_technician_headers(),
        )
    )


def kit_components(
    client: OpticsApiClient,
    assembly_id: str,
    work_order_id: str,
    specs: Sequence[Payload],
    start_version: int = 1,
) -> List[Dict[str, Any]]:
    """Kit several elements in turn, re-reading the version each element produced."""
    components: List[Dict[str, Any]] = []
    version = start_version
    for spec in specs:
        component = kit_component(
            client, assembly_id, work_order_id, version, **spec
        )
        components.append(component)
        assembly = get_success_data(
            client.get_assembly(assembly_id, make_process_technician_headers())
        )
        version = assembly["version"]
    return components


def setup_kitted_assembly(
    client: OpticsApiClient,
    component_specs: Optional[Sequence[Payload]] = None,
    element_count: int = 2,
    **kwargs: Any,
) -> Dict[str, Any]:
    """An assembly in KITTED holding elements drawn from a released work order."""
    ctx = setup_released_to_assembly_work_order(
        client, element_count=element_count, **kwargs
    )
    ctx["assembly"] = create_assembly(client, ctx["design"]["id"])
    specs = TWO_ELEMENT_SPECS if component_specs is None else component_specs
    ctx["components"] = kit_components(
        client, ctx["assembly"]["id"], ctx["work_order"]["id"], specs
    )
    return ctx


def setup_mounted_assembly(client: OpticsApiClient, **kwargs: Any) -> Dict[str, Any]:
    """An assembly cemented and mounted, one alignment pass away from ALIGNED."""
    ctx = setup_kitted_assembly(client, **kwargs)
    get_success_data(
        client.cement_assembly(
            ctx["assembly"]["id"],
            build_cement_payload(),
            make_process_technician_headers(),
        )
    )
    ctx["mounted"] = get_success_data(
        client.mount_assembly(
            ctx["assembly"]["id"],
            build_mount_payload(),
            make_process_technician_headers(),
        )
    )
    return ctx


def setup_aligned_assembly(client: OpticsApiClient, **kwargs: Any) -> Dict[str, Any]:
    """An assembly whose transmitted-wavefront roll-up is inside the budget."""
    ctx = setup_mounted_assembly(client, **kwargs)
    ctx["aligned"] = get_success_data(
        client.align_assembly(
            ctx["assembly"]["id"], make_process_technician_headers()
        )
    )
    return ctx


def record_inspection(
    client: OpticsApiClient,
    assembly_id: str,
    inspector_id: str = MT_RECORDER,
    **overrides: Any,
) -> Dict[str, Any]:
    """Record one cleanroom scratch-dig and particulate inspection."""
    return get_success_data(
        client.create_inspection_record(
            build_inspection_record_payload(assembly_id, **overrides),
            make_metrology_technician_headers(inspector_id),
        )
    )


def setup_sealed_assembly(client: OpticsApiClient, **kwargs: Any) -> Dict[str, Any]:
    """An aligned assembly with a passing inspection, sealed for delivery."""
    ctx = setup_aligned_assembly(client, **kwargs)
    ctx["inspection"] = record_inspection(client, ctx["assembly"]["id"])
    ctx["sealed"] = get_success_data(
        client.seal_assembly(
            ctx["assembly"]["id"], make_quality_manager_headers(QM_PRIMARY)
        )
    )
    return ctx


# ----------------------------------------------------------------------
# Tier 5: the documentation package and terminal release
# ----------------------------------------------------------------------
def open_documentation_package(
    client: OpticsApiClient, assembly_id: str, opener_id: str = QM_PRIMARY
) -> Dict[str, Any]:
    """Open the delivery documentation package for one assembly."""
    return get_success_data(
        client.create_documentation_package(
            build_documentation_package_payload(assembly_id),
            make_quality_manager_headers(opener_id),
        )
    )


def attach_documents(
    client: OpticsApiClient,
    package_id: str,
    document_types: Sequence[str],
    actor_id: str = QM_PRIMARY,
) -> Dict[str, Any]:
    """Attach a sequence of document types, returning the package after the last."""
    package: Dict[str, Any] = {}
    for document_type in document_types:
        package = get_success_data(
            client.attach_document(
                package_id,
                build_document_payload(document_type),
                make_quality_manager_headers(actor_id),
            )
        )
    return package


def complete_documentation_package(
    client: OpticsApiClient,
    package_id: str,
    submitter_id: str = QM_PRIMARY,
    reviewer_id: str = QM_SECOND,
) -> Dict[str, Any]:
    """Attach every required document, submit the package and approve it."""
    package = get_success_data(
        client.get_documentation_package(
            package_id, make_quality_manager_headers(submitter_id)
        )
    )
    attach_documents(
        client, package_id, list(package["required_document_types"]), submitter_id
    )
    submitted = get_success_data(
        client.submit_documentation_package(
            package_id, make_quality_manager_headers(submitter_id)
        )
    )
    approved = get_success_data(
        client.review_documentation_package(
            package_id,
            build_review_payload("APPROVED"),
            make_quality_manager_headers(reviewer_id),
        )
    )
    return {"package": package, "submitted": submitted, "approved": approved}


def setup_releasable_assembly(client: OpticsApiClient, **kwargs: Any) -> Dict[str, Any]:
    """A sealed assembly whose documentation package stands APPROVED."""
    ctx = setup_sealed_assembly(client, **kwargs)
    package = open_documentation_package(client, ctx["assembly"]["id"])
    ctx["package"] = package
    ctx["documentation"] = complete_documentation_package(client, package["id"])
    return ctx


# ----------------------------------------------------------------------
# pytest fixtures
# ----------------------------------------------------------------------
@pytest.fixture
def api() -> OpticsApiClient:
    """A client bound to the base URL the harness exposes."""
    return OpticsApiClient()


@pytest.fixture
def optics_engineer_headers() -> Dict[str, str]:
    """Headers for the optics engineering desk."""
    return make_optics_engineer_headers()


@pytest.fixture
def procurement_headers() -> Dict[str, str]:
    """Headers for the receiving and certification desk."""
    return make_procurement_officer_headers()


@pytest.fixture
def technician_headers() -> Dict[str, str]:
    """Headers for the shop-floor process technician."""
    return make_process_technician_headers()


@pytest.fixture
def metrology_headers() -> Dict[str, str]:
    """Headers for the metrology technician who records measurements."""
    return make_metrology_technician_headers(MT_RECORDER)


@pytest.fixture
def metrology_signer_headers() -> Dict[str, str]:
    """Headers for the second metrology technician who signs them off."""
    return make_metrology_technician_headers(MT_SIGNER)


@pytest.fixture
def quality_headers() -> Dict[str, str]:
    """Headers for the primary quality manager."""
    return make_quality_manager_headers(QM_PRIMARY)


@pytest.fixture
def quality_second_headers() -> Dict[str, str]:
    """Headers for the second quality manager, for segregated approvals."""
    return make_quality_manager_headers(QM_SECOND)


@pytest.fixture
def export_headers() -> Dict[str, str]:
    """Headers for the export compliance officer who classifies."""
    return make_export_compliance_officer_headers(ECO_CLASSIFIER)


@pytest.fixture
def export_decider_headers() -> Dict[str, str]:
    """Headers for the export compliance officer who records decisions."""
    return make_export_compliance_officer_headers(ECO_DECIDER)


@pytest.fixture
def admin_headers() -> Dict[str, str]:
    """Headers for the plant administrator."""
    return make_plant_admin_headers()


@pytest.fixture
def released_design(api: OpticsApiClient) -> Dict[str, Any]:
    """One design carried from DRAFT to RELEASED with a passing stack."""
    return create_released_design(api)


@pytest.fixture
def certified_lot(api: OpticsApiClient) -> Dict[str, Any]:
    """One melt lot of twenty blanks, certified and RELEASED."""
    return create_certified_lot(api)


@pytest.fixture
def work_order_context(api: OpticsApiClient) -> Dict[str, Any]:
    """A released design, a certified lot and a work order in BLANKS_RESERVED."""
    return setup_work_order(api)


@pytest.fixture
def figure_accepted_context(api: OpticsApiClient) -> Dict[str, Any]:
    """A work order carried through polishing and figuring to FIGURE_ACCEPTED."""
    return setup_figure_accepted_work_order(api)


@pytest.fixture
def coated_context(api: OpticsApiClient) -> Dict[str, Any]:
    """A work order whose coating has passed spectral verification."""
    return setup_coated_work_order(api)


@pytest.fixture
def released_to_assembly_context(api: OpticsApiClient) -> Dict[str, Any]:
    """A cleared, coated work order released to assembly."""
    return setup_released_to_assembly_work_order(api)


@pytest.fixture
def aligned_assembly_context(api: OpticsApiClient) -> Dict[str, Any]:
    """A two-element assembly aligned inside its transmitted-wavefront budget."""
    return setup_aligned_assembly(api)


@pytest.fixture
def sealed_assembly_context(api: OpticsApiClient) -> Dict[str, Any]:
    """An aligned assembly sealed behind a passing cleanroom inspection."""
    return setup_sealed_assembly(api)


@pytest.fixture
def releasable_assembly_context(api: OpticsApiClient) -> Dict[str, Any]:
    """A sealed assembly whose documentation package stands APPROVED."""
    return setup_releasable_assembly(api)
