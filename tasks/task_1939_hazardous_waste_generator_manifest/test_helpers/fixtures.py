"""Composite setup helpers for multi-step test prerequisites.

All helpers build preconditions from scratch using only PRD-declared endpoints
(the harness restarts the server before every test, so each test starts against
an empty database). Setup calls use get_success_data() so failures surface as
clear "Setup step failed" errors instead of confusing assertion failures.

Default actor ids (all overridable):
  sites/reports/LDR/sign-generator ... EHSManager   "mgr-1" (signer default "mgr-9")
  streams/areas/containers/manifests . WasteCoordinator  creator "wc-1"
  inspections ........................ WasteCoordinator  "wc-2" (must differ from
                                       the container's last_action_user_id)
  partners/audits .................... ComplianceAuditor registrar "aud-1",
                                       approver/auditor "aud-2" (SoD-separated)
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import AUDIT_WINDOW_DEFAULT
from .factories import (
    create_site_payload, create_stream_payload, characterize_payload,
    create_area_payload, create_container_payload, move_container_payload,
    label_container_payload, create_inspection_payload, create_partner_payload,
    partner_status_payload, create_audit_payload, manifest_line_item,
    create_manifest_payload, create_ldr_notification_payload,
    create_biennial_report_payload, set_clock_payload,
)
from .test_users import (
    ehs_headers, wc_headers, ca_headers,
    make_transporter_agent_headers, make_tsdf_agent_headers,
)

DEFAULT_AUDIT_FROM, DEFAULT_AUDIT_TO = AUDIT_WINDOW_DEFAULT


# ─── Clock ───────────────────────────────────────────────────────────────────

def set_clock(to_iso8601, headers=None):
    """Advance the server-held logical clock. Returns the clock payload."""
    return get_success_data(api_client.set_clock(
        set_clock_payload(to_iso8601), headers or ehs_headers()))


# ─── Tier 1: single-resource creation ────────────────────────────────────────

def create_site(name="Site A", epa_id_number="EPA-SITE-A"):
    """Register a generator site. Returns the site."""
    return get_success_data(api_client.create_site(
        create_site_payload(name, epa_id_number), ehs_headers()), 201)


def get_site(site_id):
    return get_success_data(api_client.get_site(site_id, ehs_headers()))


def get_stream(stream_id):
    return get_success_data(api_client.get_stream(stream_id, ehs_headers()))


def create_stream(site_id, name="spent solvent", waste_codes=("D001",),
                  physical_state="LIQUID"):
    """Create a waste stream (DRAFT, characterization_version 0). Returns the stream."""
    return get_success_data(api_client.create_stream(
        create_stream_payload(site_id, name, waste_codes, physical_state),
        wc_headers()), 201)


def characterize(stream, is_hazardous=True, waste_codes=("D001",),
                 ldr_treatment_standard="TLV-01", flash_point_c=21.5, ph=None):
    """Characterize `stream` (dict carrying the currently observed version).
    Returns the CHARACTERIZED stream."""
    return get_success_data(api_client.characterize_stream(
        stream["id"],
        characterize_payload(stream["version"], is_hazardous, waste_codes,
                             ldr_treatment_standard, flash_point_c, ph),
        wc_headers()))


def activate_stream(stream_id):
    """Activate a CHARACTERIZED hazardous stream. Returns the ACTIVE stream."""
    return get_success_data(api_client.activate_stream(stream_id, ehs_headers()))


def create_active_stream(site_id, name="spent solvent", waste_codes=("D001",),
                         physical_state="LIQUID", ldr_treatment_standard="TLV-01",
                         flash_point_c=21.5):
    """Stream walked DRAFT -> CHARACTERIZED -> ACTIVE. Returns the ACTIVE stream
    (carrying its current version)."""
    stream = create_stream(site_id, name, waste_codes, physical_state)
    stream = characterize(stream, True, waste_codes, ldr_treatment_standard,
                          flash_point_c)
    return activate_stream(stream["id"])


def create_area(site_id, name="Central A", area_type="CENTRAL_90DAY"):
    """Create an accumulation area. Returns the area."""
    return get_success_data(api_client.create_area(
        create_area_payload(site_id, name, area_type), wc_headers()), 201)


# ─── Tier 2: site + stream + areas hierarchy ─────────────────────────────────

def setup_site_stream_areas(site_name="Site A", epa_id_number="EPA-SITE-A",
                            waste_codes=("D001",), stream_name="spent solvent",
                            physical_state="LIQUID", ldr_treatment_standard="TLV-01",
                            flash_point_c=21.5, with_central=True,
                            with_satellite=False):
    """Site + ACTIVE waste stream + requested areas.
    Returns dict(site, stream, central, satellite); absent areas are None."""
    site = create_site(site_name, epa_id_number)
    stream = create_active_stream(
        site["id"], stream_name, waste_codes, physical_state,
        ldr_treatment_standard, flash_point_c)
    central = create_area(site["id"], "Central A", "CENTRAL_90DAY") if with_central else None
    satellite = create_area(site["id"], "Booth SAA", "SATELLITE") if with_satellite else None
    return {"site": site, "stream": stream, "central": central, "satellite": satellite}


# ─── Tier 3: containers and their lifecycle ──────────────────────────────────

def create_container(stream_id, area_id, quantity_gallons=10, quantity_kg=100.0,
                     creator="wc-1"):
    """Place a container (initial state depends on the area type). Returns it."""
    return get_success_data(api_client.create_container(
        create_container_payload(stream_id, area_id, quantity_gallons, quantity_kg),
        wc_headers(creator)), 201)


def get_container(container_id):
    return get_success_data(api_client.get_container(container_id, ehs_headers()))


def move_container(container_id, target_area_id, mover="wc-1"):
    return get_success_data(api_client.move_container(
        container_id, move_container_payload(target_area_id), wc_headers(mover)))


def label_container(container, label_text="Hazardous Waste — D001",
                    marked_start=None, labeler=None):
    """Affix the hazardous-waste label. `marked_start` defaults to the container's
    own accumulation_start_date (echoed back verbatim, satisfying the exact-match
    rule); `labeler` defaults to the container's creator."""
    marker = marked_start if marked_start is not None else container["accumulation_start_date"]
    user = labeler if labeler is not None else container["created_by_user_id"]
    return get_success_data(api_client.label_container(
        container["id"], label_container_payload(label_text, marker),
        wc_headers(user)))


def inspect_container(container_id, result="PASS", deficiency_note=None,
                      inspector="wc-2"):
    """Record an inspection. `inspector` must differ from the container's
    last_action_user_id (segregation of duties). Returns the inspection."""
    return get_success_data(api_client.create_inspection(
        container_id, create_inspection_payload(result, deficiency_note),
        wc_headers(inspector)), 201)


def stage_container(container_id, stager="wc-1"):
    return get_success_data(api_client.stage_container(
        container_id, wc_headers(stager)))


def create_staged_container(stream_id, area_id, quantity_gallons=10,
                            quantity_kg=100.0, creator="wc-1", inspector="wc-2",
                            label_text="Hazardous Waste — D001"):
    """Central-area container walked create -> label -> inspect(PASS) -> stage.
    Returns the STAGED_FOR_SHIPMENT container."""
    container = create_container(stream_id, area_id, quantity_gallons,
                                 quantity_kg, creator)
    container = label_container(container, label_text, labeler=creator)
    inspect_container(container["id"], "PASS", inspector=inspector)
    return stage_container(container["id"], stager=creator)


# ─── Tier 3: partners and audits ─────────────────────────────────────────────

def create_partner(partner_type, name, epa_id_number,
                   permitted_waste_codes=("D001",), registrar="aud-1"):
    """Register a transporter/TSDF (PENDING, created_by = registrar)."""
    return get_success_data(api_client.create_partner(
        create_partner_payload(partner_type, name, epa_id_number,
                               permitted_waste_codes),
        ca_headers(registrar)), 201)


def get_partner(partner_id):
    return get_success_data(api_client.get_partner(partner_id, ca_headers()))


def approve_partner(partner, approver="aud-2"):
    """PENDING/SUSPENDED -> APPROVED by an auditor other than the registrar."""
    return get_success_data(api_client.set_partner_status(
        partner["id"], partner_status_payload("APPROVED"), ca_headers(approver)))


def audit_partner(partner_id, coverage_from=DEFAULT_AUDIT_FROM,
                  coverage_to=DEFAULT_AUDIT_TO, outcome="PASS", auditor="aud-2"):
    """Record a compliance audit. Returns the audit."""
    return get_success_data(api_client.create_audit(
        partner_id, create_audit_payload(coverage_from, coverage_to, outcome),
        ca_headers(auditor)), 201)


def create_vetted_partner(partner_type, epa_id_number,
                          permitted_waste_codes=("D001",), name=None,
                          coverage_from=DEFAULT_AUDIT_FROM,
                          coverage_to=DEFAULT_AUDIT_TO,
                          registrar="aud-1", approver="aud-2"):
    """Partner registered, APPROVED, and holding a current PASS audit window.
    Returns the partner re-read after the audit (carrying coverage fields)."""
    partner = create_partner(partner_type, name or f"{partner_type} Co",
                             epa_id_number, permitted_waste_codes, registrar)
    partner = approve_partner(partner, approver)
    audit_partner(partner["id"], coverage_from, coverage_to, "PASS", approver)
    return get_partner(partner["id"])


def create_manifest_partners(permitted_waste_codes=("D001",),
                             coverage_from=DEFAULT_AUDIT_FROM,
                             coverage_to=DEFAULT_AUDIT_TO,
                             transporter_epa="EPA-TR-1", tsdf_epa="EPA-TS-1"):
    """One APPROVED + audit-current TRANSPORTER and one ditto TSDF.
    Returns (transporter, tsdf)."""
    transporter = create_vetted_partner(
        "TRANSPORTER", transporter_epa, permitted_waste_codes, "HaulCo",
        coverage_from, coverage_to)
    tsdf = create_vetted_partner(
        "TSDF", tsdf_epa, permitted_waste_codes, "DispCo",
        coverage_from, coverage_to)
    return transporter, tsdf


# ─── Tier 4: manifests and the shipment chain ────────────────────────────────

def create_manifest(site_id, transporter_id, tsdf_id, line_items,
                    tracking_number="MT-1", creator="wc-1"):
    """Draft a manifest. Returns the DRAFT manifest."""
    return get_success_data(api_client.create_manifest(
        create_manifest_payload(site_id, transporter_id, tsdf_id,
                                tracking_number, line_items),
        wc_headers(creator)), 201)


def get_manifest(manifest_id):
    return get_success_data(api_client.get_manifest(manifest_id, ehs_headers()))


def attach_ldr(manifest_id, treatment_standard_codes=("TLV-01",),
               certification_statement="certified"):
    """Attach the land-disposal-restriction notification to a DRAFT manifest."""
    return get_success_data(api_client.create_ldr_notification(
        manifest_id,
        create_ldr_notification_payload(treatment_standard_codes,
                                        certification_statement),
        ehs_headers()), 201)


def sign_manifest_generator(manifest_id, signer="mgr-9"):
    """Generator signature by an EHSManager other than the manifest creator."""
    return get_success_data(api_client.sign_manifest_generator(
        manifest_id, ehs_headers(signer)))


def sign_manifest_transporter(manifest, transporter):
    """Transporter countersignature; X-User-ID is the transporter partner's id."""
    return get_success_data(api_client.sign_manifest_transporter(
        manifest["id"], make_transporter_agent_headers(transporter["id"])))


def receive_manifest(manifest, tsdf):
    """TSDF receipt; X-User-ID is the TSDF partner's id."""
    return get_success_data(api_client.receive_manifest(
        manifest["id"], make_tsdf_agent_headers(tsdf["id"])))


def confirm_manifest_return(manifest_id):
    return get_success_data(api_client.confirm_manifest_return(
        manifest_id, ehs_headers()))


# ─── Tier 5: full scenario composites ────────────────────────────────────────

def setup_shippable_site(quantity_kg=100.0, quantity_gallons=10,
                         waste_codes=("D001",), epa_id_number="EPA-SITE-A",
                         coverage_from=DEFAULT_AUDIT_FROM,
                         coverage_to=DEFAULT_AUDIT_TO,
                         ldr_treatment_standard="TLV-01",
                         transporter_epa="EPA-TR-1", tsdf_epa="EPA-TS-1",
                         creator="wc-1", inspector="wc-2"):
    """Site + ACTIVE stream + central area + one STAGED_FOR_SHIPMENT container +
    vetted transporter/TSDF pair. Returns the whole bundle."""
    env = setup_site_stream_areas(
        epa_id_number=epa_id_number, waste_codes=waste_codes,
        ldr_treatment_standard=ldr_treatment_standard)
    transporter, tsdf = create_manifest_partners(
        waste_codes, coverage_from, coverage_to, transporter_epa, tsdf_epa)
    container = create_staged_container(
        env["stream"]["id"], env["central"]["id"], quantity_gallons,
        quantity_kg, creator, inspector)
    env.update({"transporter": transporter, "tsdf": tsdf, "container": container})
    return env


def create_manifest_chain(quantity_kg=100.0, quantity_gallons=10,
                          waste_codes=("D001",), epa_id_number="EPA-SITE-A",
                          tracking_number="MT-1",
                          coverage_from=DEFAULT_AUDIT_FROM,
                          coverage_to=DEFAULT_AUDIT_TO,
                          transporter_epa="EPA-TR-1", tsdf_epa="EPA-TS-1",
                          through="DRAFT", creator="wc-1", signer="mgr-9",
                          ldr_treatment_standard="TLV-01"):
    """Full shipment pipeline: shippable site + manifest walked to `through`
    (DRAFT | GENERATOR_SIGNED | IN_TRANSIT | DELIVERED | RETURNED).
    Returns dict(site, stream, central, transporter, tsdf, container, manifest)."""
    env = setup_shippable_site(
        quantity_kg, quantity_gallons, waste_codes, epa_id_number,
        coverage_from, coverage_to, ldr_treatment_standard,
        transporter_epa, tsdf_epa, creator)
    line = manifest_line_item(env["stream"]["id"], env["container"]["id"],
                              quantity_kg)
    manifest = create_manifest(
        env["site"]["id"], env["transporter"]["id"], env["tsdf"]["id"],
        [line], tracking_number, creator)
    env["manifest"] = manifest
    if through == "DRAFT":
        return env
    attach_ldr(manifest["id"])
    manifest = sign_manifest_generator(manifest["id"], signer)
    env["manifest"] = manifest
    if through == "GENERATOR_SIGNED":
        return env
    manifest = sign_manifest_transporter(manifest, env["transporter"])
    env["manifest"] = manifest
    if through == "IN_TRANSIT":
        return env
    manifest = receive_manifest(manifest, env["tsdf"])
    env["manifest"] = manifest
    if through == "DELIVERED":
        return env
    manifest = confirm_manifest_return(manifest["id"])
    env["manifest"] = manifest
    return env


# ─── Tier 5: biennial reports ────────────────────────────────────────────────

def create_biennial_report(site_id, report_year=2027):
    return get_success_data(api_client.create_biennial_report(
        create_biennial_report_payload(site_id, report_year), ehs_headers()), 201)


def get_biennial_report(report_id):
    return get_success_data(api_client.get_biennial_report(
        report_id, ehs_headers()))


def submit_biennial_report(report_id):
    return get_success_data(api_client.submit_biennial_report(
        report_id, ehs_headers()))
