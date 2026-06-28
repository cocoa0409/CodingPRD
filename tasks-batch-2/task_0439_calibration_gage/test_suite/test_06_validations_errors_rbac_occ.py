"""Validation rules, error catalogue triggers, RBAC peer-role denials, and
optimistic-concurrency control.

Corner queue: validations, endpoints, errors, rbac, cross_cutting_complexity_layers (OCC).
"""
from test_helpers import validate_success, validate_error, NON_EXISTENT_UUID
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import (
    TECH, QE, MET,
    create_standard,
    create_vendor,
    create_instrument,
    open_event,
    add_point,
    finalize_passing_event,
    finalize_failing_event,
    create_collecting_study,
    get_only_impact,
    current_version,
)
from test_helpers.test_users import (
    make_quality_engineer_headers,
    make_technician_headers,
)


# ===========================================================================
# Corner / validations / corner_duplicate_asset_tag_rejected
# ===========================================================================
def test_duplicate_asset_tag_rejected(api):
    """PRD §3.1: "The asset tag must be unique among instruments whose
    `lifecycle_status` is not `RETIRED`; a collision is rejected with
    `ERR_DUPLICATE_ASSET_TAG`."

    Design: Corner/validations/corner_duplicate_asset_tag_rejected
    """
    create_instrument(asset_tag="DUP-1", nominal_value=10.0, tolerance_plus=0.1,
                      tolerance_minus=0.1, calibration_interval_epochs=30)
    validate_error(api.create_instrument(
        {"asset_tag": "DUP-1", "description": "Second", "nominal_value": 10.0,
         "tolerance_plus": 0.1, "tolerance_minus": 0.1, "measurement_unit": "mm",
         "calibration_interval_epochs": 30, "criticality": "MAJOR"}, QE),
        ApiErrorId.ERR_DUPLICATE_ASSET_TAG.value)


# ===========================================================================
# Corner / validations / corner_traceability_self_reference_cycle_rejected
# ===========================================================================
def test_standard_self_reference_cycle_rejected(api):
    """PRD §2.8: "On registering or updating a standard, if following
    `parent_standard_id` links would form a cycle, would make the standard its own
    ancestor, or would produce a chain deeper than the maximum of 10 links, the
    write is rejected with `ERR_TRACEABILITY_CYCLE` (HTTP 409)."

    Design: Corner/validations/corner_traceability_self_reference_cycle_rejected
    """
    std = create_standard(name="S-CYC", nist_test_number="NIST-CYC", nominal_value=1.0)
    validate_error(api.update_standard(std["id"], {"parent_standard_id": std["id"]}, MET),
                   ApiErrorId.ERR_TRACEABILITY_CYCLE.value)


# ===========================================================================
# Corner / validations / corner_fk_standard_not_found_on_event_create
# ===========================================================================
def test_event_create_with_unknown_standard_fk(api):
    """PRD §2.10: "then body foreign keys such as `standard_id`, `vendor_id`, and
    `parent_standard_id` are confirmed to reference existing rows
    (`ERR_FK_NOT_FOUND`)."

    Design: Corner/validations/corner_fk_standard_not_found_on_event_create
    """
    inst = create_instrument(asset_tag="INST-FK", criticality="MAJOR")
    validate_error(api.create_event(
        inst["id"], {"standard_id": NON_EXISTENT_UUID, "scheduled_epoch": 5,
                     "expected_instrument_version": inst["version"]}, TECH),
        ApiErrorId.ERR_FK_NOT_FOUND.value)


# ===========================================================================
# Corner / validations / corner_vendor_accreditation_number_required_unless_none
# ===========================================================================
def test_vendor_accreditation_number_required_unless_none(api):
    """PRD §2.9: "A vendor's `accreditation_body` is one of `A2LA`, `NVLAP`, `UKAS`,
    or `NONE`, and its `accreditation_number` must be non-empty unless the body is
    `NONE`."

    Design: Corner/validations/corner_vendor_accreditation_number_required_unless_none
    """
    validate_error(api.create_vendor(
        {"name": "V-MISS", "accreditation_body": "UKAS",
         "accredited_through_epoch": 9999}, MET),
        ApiErrorId.ERR_INVALID_REQUEST.value)


# ===========================================================================
# Corner / endpoints / corner_disposition_recall_conditional_action
# ===========================================================================
def test_recall_disposition_with_no_in_window_product_rejected(api):
    """PRD §3.5: "When the chosen disposition is `RECALL`, there must be at least one
    attached affected product whose `in_suspect_window` is true (otherwise
    `ERR_NO_RECALLABLE_PRODUCT`)."

    The only attached product (measured at epoch 5) is before the prior good cal at
    epoch 10, hence outside window [10,30].

    Design: Corner/endpoints/corner_disposition_recall_conditional_action
    """
    qe1 = make_quality_engineer_headers("qe-1")
    qe2 = make_quality_engineer_headers("qe-2")
    tech = make_technician_headers("tech-7")
    std = create_standard(name="S-NRP", nist_test_number="NIST-NRP")
    inst = create_instrument(asset_tag="INST-NRP", criticality="CRITICAL", headers=qe1)
    finalize_passing_event(inst["id"], std["id"], inst["version"],
                           scheduled_epoch=10, as_found_value=25.00, tech_headers=tech)
    finalize_failing_event(inst["id"], std["id"], current_version(inst["id"], headers=qe1),
                           scheduled_epoch=30, as_found_value=25.40, tech_headers=tech)
    impact = get_only_impact(inst["id"], headers=qe1)
    validate_success(api.add_affected_product(
        impact["id"], {"product_serial": "OUT-5", "measured_epoch": 5}, qe1), 201)
    validate_success(api.investigate_impact(impact["id"], qe2))
    validate_error(api.disposition_impact(impact["id"], {"disposition": "RECALL"}, qe2),
                   ApiErrorId.ERR_NO_RECALLABLE_PRODUCT.value)


# ===========================================================================
# Corner / endpoints / corner_event_list_by_instrument_reverse_reachability
# ===========================================================================
def test_event_list_by_instrument_contains_created_event(api):
    """PRD §4: lists an instrument's calibration events via
    `GET /instruments/{id}/calibration-events`.
    PRD §3.3: "The server stamps the event's `instrument_id` from the path".

    Design: Corner/endpoints/corner_event_list_by_instrument_reverse_reachability
    """
    std = create_standard(name="S-RL", nist_test_number="NIST-RL")
    inst = create_instrument(asset_tag="INST-RL", criticality="MINOR")
    ev = open_event(inst["id"], std["id"], inst["version"], scheduled_epoch=5)
    data = validate_success(api.list_instrument_events(inst["id"], QE))
    assert isinstance(data, list), "event list must be an array"
    assert any(e["id"] == ev["id"] for e in data), \
        f"expected created event {ev['id']} in the instrument's event list"


# ===========================================================================
# Corner / errors / corner_duplicate_certificate_number_rejected
# ===========================================================================
def test_duplicate_certificate_number_rejected(api):
    """PRD §3.6: "A certificate number must be unique among the vendor's
    certificates whose status is not `REJECTED`; a collision is rejected with
    `ERR_DUPLICATE_CERTIFICATE_NUMBER`."

    Design: Corner/errors/corner_duplicate_certificate_number_rejected
    """
    std = create_standard(name="S-DC", nist_test_number="NIST-DC")
    vendor = create_vendor(name="V-DC", accreditation_body="A2LA", accreditation_number="A-DC")
    inst = create_instrument(asset_tag="INST-DC", criticality="MAJOR")
    ev = open_event(inst["id"], std["id"], inst["version"], scheduled_epoch=5,
                    vendor_id=vendor["id"])
    add_point(ev["id"], as_found_value=25.00)
    validate_success(api.start_event(ev["id"], TECH))
    validate_success(api.issue_certificate(
        ev["id"], {"vendor_id": vendor["id"], "certificate_number": "C-DUP",
                   "issued_epoch": 5}, MET), 201)
    validate_error(api.issue_certificate(
        ev["id"], {"vendor_id": vendor["id"], "certificate_number": "C-DUP",
                   "issued_epoch": 5}, MET),
        ApiErrorId.ERR_DUPLICATE_CERTIFICATE_NUMBER.value)


# ===========================================================================
# Corner / errors / corner_vendor_not_eligible_on_start
# ===========================================================================
def test_event_start_with_lapsed_vendor_accreditation_rejected(api):
    """PRD §3.3: "when a `vendor_id` is set, that vendor must be `ACTIVE` with
    `is_accreditation_current` true (otherwise `ERR_VENDOR_NOT_ELIGIBLE`)."
    PRD §2.9: "The computed `is_accreditation_current` flag is true only when the
    body is not `NONE` and the vendor's `accredited_through_epoch` is greater than or
    equal to the clock's `current_epoch`."

    Vendor accredited only through epoch 1; clock advanced to 5.

    Design: Corner/errors/corner_vendor_not_eligible_on_start
    """
    std = create_standard(name="S-VNE", nist_test_number="NIST-VNE")
    vendor = create_vendor(name="V-VNE", accreditation_body="A2LA",
                           accreditation_number="A-VNE", accredited_through_epoch=1)
    inst = create_instrument(asset_tag="INST-VNE", criticality="MAJOR")
    validate_success(api.advance_clock({"by_epochs": 5}, QE))
    ev = open_event(inst["id"], std["id"], current_version(inst["id"]),
                    scheduled_epoch=5, vendor_id=vendor["id"])
    add_point(ev["id"], as_found_value=25.00)
    validate_error(api.start_event(ev["id"], TECH),
                   ApiErrorId.ERR_VENDOR_NOT_ELIGIBLE.value)


# ===========================================================================
# Corner / errors / corner_cert_vendor_mismatch_on_verify
# ===========================================================================
def test_certificate_vendor_mismatch_on_verify(api):
    """PRD §3.6: "that the certificate's `vendor_id` equal the owning event's
    `vendor_id` (otherwise `ERR_CERT_VENDOR_MISMATCH`)".

    A PASSED external event uses vendor V1; the certificate names vendor V2.

    Design: Corner/errors/corner_cert_vendor_mismatch_on_verify
    """
    std = create_standard(name="S-VM", nist_test_number="NIST-VM")
    v1 = create_vendor(name="V1", accreditation_body="A2LA", accreditation_number="A-V1")
    v2 = create_vendor(name="V2", accreditation_body="A2LA", accreditation_number="A-V2")
    inst = create_instrument(asset_tag="INST-VM", criticality="MAJOR")
    ev = open_event(inst["id"], std["id"], inst["version"], scheduled_epoch=5, vendor_id=v1["id"])
    add_point(ev["id"], as_found_value=25.00)
    validate_success(api.start_event(ev["id"], TECH))
    validate_success(api.finalize_event(ev["id"], TECH))
    cert = validate_success(api.issue_certificate(
        ev["id"], {"vendor_id": v2["id"], "certificate_number": "C-VM",
                   "issued_epoch": 5}, MET), 201)
    validate_error(api.verify_certificate(cert["id"], MET),
                   ApiErrorId.ERR_CERT_VENDOR_MISMATCH.value)


# ===========================================================================
# Corner / errors / corner_duplicate_trial_cell_rejected
# ===========================================================================
def test_duplicate_trial_cell_rejected(api):
    """PRD §3.7: "Each combination must fall within the study's declared bounds and
    must not already be populated; an out-of-bounds index or a repeated cell is
    rejected with `ERR_DUPLICATE_TRIAL_CELL`."

    Design: Corner/errors/corner_duplicate_trial_cell_rejected
    """
    inst = create_instrument(asset_tag="INST-DT", nominal_value=5.0,
                             tolerance_plus=1.0, tolerance_minus=1.0, criticality="MAJOR")
    study = create_collecting_study(inst["id"], inst["version"])
    validate_success(api.add_trial(
        study["id"], {"operator_index": 1, "part_index": 1, "trial_index": 1,
                      "measured_value": 2.0}, TECH), 201)
    validate_error(api.add_trial(
        study["id"], {"operator_index": 1, "part_index": 1, "trial_index": 1,
                      "measured_value": 2.5}, TECH),
        ApiErrorId.ERR_DUPLICATE_TRIAL_CELL.value)


# ===========================================================================
# Corner / errors / corner_gage_rr_accept_unacceptable_rejected
# ===========================================================================
def test_accept_unacceptable_study_rejected(api):
    """PRD §3.7: "Accepting an `ANALYZED` study moves it to `ACCEPTED` (terminal) and
    requires that its `acceptability` not be `UNACCEPTABLE` (otherwise
    `ERR_GAGE_RR_UNACCEPTABLE`)."

    Design: Corner/errors/corner_gage_rr_accept_unacceptable_rejected
    """
    from test_helpers.fixtures import setup_analyzed_study, GRR_UNACCEPTABLE_MATRIX
    inst = create_instrument(asset_tag="INST-GU", nominal_value=5.0,
                             tolerance_plus=1.0, tolerance_minus=1.0, criticality="MAJOR")
    study = setup_analyzed_study(inst["id"], inst["version"], matrix=GRR_UNACCEPTABLE_MATRIX)
    validate_error(api.accept_study(study["id"], QE),
                   ApiErrorId.ERR_GAGE_RR_UNACCEPTABLE.value)


# ===========================================================================
# Corner / rbac / corner_technician_cannot_register_instrument
# ===========================================================================
def test_technician_cannot_register_instrument(api):
    """PRD §2.1: "A `QualityEngineer` owns the asset register and the
    out-of-tolerance impact lifecycle — registering, releasing, and retiring
    instruments".
    PRD §2.1: "When the supplied role is not one of these three, or is one of them
    but is not permitted to perform the requested operation, the request is rejected
    with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/corner_technician_cannot_register_instrument
    """
    validate_error(api.create_instrument(
        {"asset_tag": "INST-RB", "description": "RB gauge", "nominal_value": 10.0,
         "tolerance_plus": 0.1, "tolerance_minus": 0.1, "measurement_unit": "mm",
         "calibration_interval_epochs": 30, "criticality": "MAJOR"}, TECH),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value)


# ===========================================================================
# Corner / rbac / corner_quality_engineer_cannot_register_standard
# ===========================================================================
def test_quality_engineer_cannot_register_standard(api):
    """PRD §2.1: "A `Metrologist` owns reference standards, vendors, and
    certificates — registering and updating standards and vendors".
    PRD §2.1: "is one of them but is not permitted to perform the requested
    operation, the request is rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/corner_quality_engineer_cannot_register_standard
    """
    validate_error(api.create_standard(
        {"name": "S-RB", "nist_test_number": "NIST-RB", "nominal_value": 1.0,
         "standard_unit": "mm", "uncertainty": 0.001, "certified_through_epoch": 9999}, QE),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value)


# ===========================================================================
# Corner / rbac / corner_missing_user_context_header
# ===========================================================================
def test_missing_user_context_header(api):
    """PRD §2.1: "Every request to the API must carry two mandatory headers:
    `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the
    capacity in which they act. If either header is absent or empty, the request is
    rejected with `ERR_MISSING_USER_CONTEXT`."

    Design: Corner/rbac/corner_missing_user_context_header
    """
    validate_error(api.list_instruments({}), ApiErrorId.ERR_MISSING_USER_CONTEXT.value)


# ===========================================================================
# Corner / cross_cutting_complexity_layers / corner_occ_stale_instrument_version_on_event_create
# ===========================================================================
def test_event_create_with_stale_instrument_version_rejected(api):
    """PRD §2.7: "Opening a new calibration event under an instrument requires the
    request body to carry `expected_instrument_version`, and that value must equal
    the target instrument's current `version`. If another writer has advanced the
    instrument's version since the client last observed it — for instance by
    finalizing a prior event, which bumps the instrument's version and changes its
    calibration status and next-due epoch — the create is rejected with
    `ERR_STALE_INSTRUMENT_VERSION` (HTTP 412)".

    Design: Corner/cross_cutting_complexity_layers/corner_occ_stale_instrument_version_on_event_create
    """
    std = create_standard(name="S-OCC", nist_test_number="NIST-OCC")
    inst = create_instrument(asset_tag="INST-OCC", criticality="MAJOR")
    stale_version = inst["version"]
    # First event opened with stale_version bumps the instrument's version; finalize
    # bumps it again — the original captured version is now stale.
    finalize_passing_event(inst["id"], std["id"], stale_version,
                           scheduled_epoch=5, as_found_value=25.00)
    validate_error(api.create_event(
        inst["id"], {"standard_id": std["id"], "scheduled_epoch": 6,
                     "expected_instrument_version": stale_version}, TECH),
        ApiErrorId.ERR_STALE_INSTRUMENT_VERSION.value)


# ===========================================================================
# Corner / cross_cutting_complexity_layers / corner_occ_correct_version_on_gage_rr_create_succeeds
# ===========================================================================
def test_gage_rr_create_with_current_version_succeeds(api):
    """PRD §2.7: "The same guard protects creating a gage R&R study under an
    instrument: the request must carry `expected_instrument_version` matching the
    instrument's current `version`".
    PRD §3.7: "A new study begins in `DRAFT`."

    Design: Corner/cross_cutting_complexity_layers/corner_occ_correct_version_on_gage_rr_create_succeeds
    """
    inst = create_instrument(asset_tag="INST-OCC2", nominal_value=5.0,
                             tolerance_plus=1.0, tolerance_minus=1.0, criticality="MAJOR")
    data = validate_success(api.create_study(
        inst["id"], {"operator_count": 2, "part_count": 2, "trial_count": 2,
                     "process_tolerance": 10.0, "expected_instrument_version": inst["version"]},
        QE), 201)
    assert data["status"] == "DRAFT", f"expected status DRAFT, got {data['status']}"
