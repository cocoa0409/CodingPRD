"""State-machine transitions, revision cycles, and cross-entity cascades.

Difficulty queue: non_linear_state_machine, transitive_cascade.
Corner queue: state_machines section + consistency_model.
"""
from test_helpers import validate_success, validate_error
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
    get_only_impact,
    current_version,
    setup_quarantined_instrument,
    setup_analyzed_study,
    GRR_UNACCEPTABLE_MATRIX,
)
from test_helpers.test_users import (
    make_quality_engineer_headers,
    make_technician_headers,
)


# ===========================================================================
# Difficulty / non_linear_state_machine / cal_event_failed_reopen_cycle
# ===========================================================================
def test_failed_event_reopens_after_impact_cancelled(api):
    """PRD §3.4: "Reopening is a `Technician` action permitted only when the
    auto-created impact for this event has reached `CANCELLED` (otherwise
    `ERR_IMPACT_NOT_CANCELLED`) and the owning instrument is `QUARANTINED`
    (otherwise `ERR_INVALID_STATE`); it sets `status` to `IN_PROGRESS`, clears
    `result` back to null, and increments the event's version."

    Design: Difficulty/non_linear_state_machine/cal_event_failed_reopen_cycle
    """
    inst, std, failed, impact = setup_quarantined_instrument(
        asset_tag="INST-RC", criticality="MINOR")
    validate_success(api.cancel_impact(impact["id"], QE))
    data = validate_success(api.reopen_event(failed["id"], TECH))
    assert data["status"] == "IN_PROGRESS", f"expected IN_PROGRESS, got {data['status']}"
    assert data["result"] is None, f"expected result null after reopen, got {data['result']}"


def test_failed_event_reopen_blocked_while_impact_not_cancelled(api):
    """PRD §3.4: "Reopening is a `Technician` action permitted only when the
    auto-created impact for this event has reached `CANCELLED` (otherwise
    `ERR_IMPACT_NOT_CANCELLED`) and the owning instrument is `QUARANTINED`
    (otherwise `ERR_INVALID_STATE`)".

    The impact is still OPEN, so reopen is rejected with ERR_IMPACT_NOT_CANCELLED.

    Design: Difficulty/non_linear_state_machine/cal_event_failed_reopen_cycle
    """
    inst, std, failed, impact = setup_quarantined_instrument(
        asset_tag="INST-RC2", criticality="MINOR")
    validate_error(api.reopen_event(failed["id"], TECH),
                   ApiErrorId.ERR_IMPACT_NOT_CANCELLED.value)


# ===========================================================================
# Difficulty / non_linear_state_machine / gage_rr_rejected_recollect_cycle
# ===========================================================================
def test_gage_rr_reject_resets_metrics_and_loops_to_collecting(api):
    """PRD §3.7: "Rejecting an `ANALYZED` study moves it back to `COLLECTING` for
    re-measurement, permitted only from `ANALYZED` (otherwise `ERR_INVALID_STATE`),
    and resets `ev_repeatability`, `av_reproducibility`, `grr`, `pct_grr`, and
    `acceptability` to null."

    Design: Difficulty/non_linear_state_machine/gage_rr_rejected_recollect_cycle
    """
    inst = create_instrument(asset_tag="INST-GRR2", nominal_value=5.0,
                             tolerance_plus=1.0, tolerance_minus=1.0, criticality="MAJOR")
    study = setup_analyzed_study(inst["id"], inst["version"],
                                 matrix=GRR_UNACCEPTABLE_MATRIX)
    data = validate_success(api.reject_study(study["id"], QE))
    assert data["status"] == "COLLECTING", f"expected COLLECTING, got {data['status']}"
    assert data["pct_grr"] is None, f"expected pct_grr null, got {data['pct_grr']}"
    assert data["acceptability"] is None, \
        f"expected acceptability null, got {data['acceptability']}"


def test_gage_rr_reject_only_from_analyzed(api):
    """PRD §3.7: "Rejecting an `ANALYZED` study moves it back to `COLLECTING` for
    re-measurement, permitted only from `ANALYZED` (otherwise `ERR_INVALID_STATE`)".

    Rejecting a COLLECTING (not yet analyzed) study is ERR_INVALID_STATE.

    Design: Difficulty/non_linear_state_machine/gage_rr_rejected_recollect_cycle
    """
    inst = create_instrument(asset_tag="INST-GRR3", nominal_value=5.0,
                             tolerance_plus=1.0, tolerance_minus=1.0, criticality="MAJOR")
    study = validate_success(api.create_study(
        inst["id"],
        {"operator_count": 2, "part_count": 2, "trial_count": 2,
         "process_tolerance": 10.0, "expected_instrument_version": inst["version"]},
        QE), 201)
    validate_success(api.open_study(study["id"], QE))
    validate_error(api.reject_study(study["id"], QE), ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Difficulty / transitive_cascade / fail_finalize_depth3_cascade
# ===========================================================================
def test_fail_finalize_cascades_quarantine_and_open_impact(api):
    """PRD §3.4: "A `FAIL` result is permitted only while the instrument is `ACTIVE`
    (otherwise `ERR_INSTRUMENT_NOT_ACTIVE`) and triggers a two-hop cascade: the
    event moves to `FAILED`, the instrument's `calibration_status` becomes
    `OUT_OF_TOLERANCE` and its `lifecycle_status` becomes `QUARANTINED`, an
    `OutOfToleranceImpact` is auto-created in `OPEN` with its `triggering_event_id`
    set to this event and its suspect window computed (see §3.5), `open_oot_count`
    is increased by one, and the instrument's version is incremented."

    Design: Difficulty/transitive_cascade/fail_finalize_depth3_cascade
    """
    std = create_standard(name="GB-C3", nist_test_number="NIST-5")
    inst = create_instrument(asset_tag="INST-C3", criticality="CRITICAL")
    failed = finalize_failing_event(inst["id"], std["id"], inst["version"],
                                    scheduled_epoch=5, as_found_value=25.40)
    assert failed["result"] == "FAIL", f"expected FAIL, got {failed['result']}"
    inst_after = validate_success(api.get_instrument(inst["id"], QE))
    assert inst_after["calibration_status"] == "OUT_OF_TOLERANCE", \
        f"expected OUT_OF_TOLERANCE, got {inst_after['calibration_status']}"
    assert inst_after["lifecycle_status"] == "QUARANTINED", \
        f"expected QUARANTINED, got {inst_after['lifecycle_status']}"
    assert inst_after["open_oot_count"] == 1, \
        f"expected open_oot_count 1, got {inst_after['open_oot_count']}"
    impact = get_only_impact(inst["id"])
    assert impact["status"] == "OPEN", f"expected impact OPEN, got {impact['status']}"


def test_fail_finalize_auto_impact_links_triggering_event(api):
    """PRD §3.5: "When a calibration fails, the auto-created `OutOfToleranceImpact`
    is the investigation record for everything the suspect instrument may have
    mismeasured. Its `instrument_id` and `triggering_event_id` are stamped by the
    server."

    Design: Difficulty/transitive_cascade/fail_finalize_depth3_cascade
    """
    std = create_standard(name="GB-C3b", nist_test_number="NIST-5b")
    inst = create_instrument(asset_tag="INST-C3b", criticality="CRITICAL")
    failed = finalize_failing_event(inst["id"], std["id"], inst["version"],
                                    scheduled_epoch=5, as_found_value=25.40)
    impact = get_only_impact(inst["id"])
    assert impact["triggering_event_id"] == failed["id"], \
        f"expected triggering_event_id {failed['id']}, got {impact['triggering_event_id']}"
    assert impact["instrument_id"] == inst["id"], \
        f"expected instrument_id {inst['id']}, got {impact['instrument_id']}"


# ===========================================================================
# Difficulty / transitive_cascade / recall_disposition_depth2_cascade
# ===========================================================================
def test_recall_disposition_recalls_in_window_products(api):
    """PRD §3.5: "A `RECALL` disposition moves every affected product whose
    `in_suspect_window` is true to `RECALLED` and recomputes `recalled_product_count`."

    Two in-window products → both RECALLED, recalled_product_count 2.

    Design: Difficulty/transitive_cascade/recall_disposition_depth2_cascade
    """
    qe1 = make_quality_engineer_headers("qe-1")
    qe2 = make_quality_engineer_headers("qe-2")
    tech = make_technician_headers("tech-1")
    std = create_standard(name="GB-RD", nist_test_number="NIST-6")
    inst = create_instrument(asset_tag="INST-RD", criticality="CRITICAL", headers=qe1)
    failed = finalize_failing_event(inst["id"], std["id"], inst["version"],
                                    scheduled_epoch=5, as_found_value=25.40, tech_headers=tech)
    impact = get_only_impact(inst["id"], headers=qe1)
    for serial, epoch in [("P-A", 2), ("P-B", 4)]:
        validate_success(api.add_affected_product(
            impact["id"], {"product_serial": serial, "measured_epoch": epoch}, qe1), 201)
    validate_success(api.investigate_impact(impact["id"], qe2))
    data = validate_success(api.disposition_impact(impact["id"], {"disposition": "RECALL"}, qe2))
    assert data["status"] == "DISPOSITIONED", f"expected DISPOSITIONED, got {data['status']}"
    assert data["disposition"] == "RECALL", f"expected RECALL, got {data['disposition']}"
    assert data["recalled_product_count"] == 2, \
        f"expected recalled_product_count 2, got {data['recalled_product_count']}"
    products = validate_success(api.list_affected_products(impact["id"], qe1))
    assert all(p["status"] == "RECALLED" for p in products), \
        f"expected all products RECALLED, got {[p['status'] for p in products]}"


def test_recall_disposition_decrements_open_oot_count(api):
    """PRD §3.5: "Disposition records the chosen `disposition`, stamps
    `dispositioned_by_user_id` from the acting identifier, moves the impact to
    `DISPOSITIONED` (terminal), and decrements the instrument's `open_oot_count` by
    one."

    Design: Difficulty/transitive_cascade/recall_disposition_depth2_cascade
    """
    qe1 = make_quality_engineer_headers("qe-1")
    qe2 = make_quality_engineer_headers("qe-2")
    tech = make_technician_headers("tech-1")
    std = create_standard(name="GB-RD2", nist_test_number="NIST-6b")
    inst = create_instrument(asset_tag="INST-RD2", criticality="CRITICAL", headers=qe1)
    finalize_failing_event(inst["id"], std["id"], inst["version"],
                           scheduled_epoch=5, as_found_value=25.40, tech_headers=tech)
    impact = get_only_impact(inst["id"], headers=qe1)
    validate_success(api.add_affected_product(
        impact["id"], {"product_serial": "P-A", "measured_epoch": 2}, qe1), 201)
    validate_success(api.investigate_impact(impact["id"], qe2))
    validate_success(api.disposition_impact(impact["id"], {"disposition": "RECALL"}, qe2))
    inst_after = validate_success(api.get_instrument(inst["id"], qe1))
    assert inst_after["open_oot_count"] == 0, \
        f"expected open_oot_count 0 after disposition, got {inst_after['open_oot_count']}"


# ===========================================================================
# Corner / state_machines / corner_pass_finalize_bubbles_up_instrument_in_tolerance
# ===========================================================================
def test_pass_finalize_bubbles_up_in_tolerance_and_next_due(api):
    """PRD §3.4: "the instrument's `calibration_status` becomes `IN_TOLERANCE` and
    its scheduling fields are recomputed".
    PRD §3.4: "`next_due_epoch` is set to that `last_calibration_epoch` plus the
    instrument's `calibration_interval_epochs`."

    Epoch 5 + interval 100 → next_due 105; last_calibration_epoch 5.

    Design: Corner/state_machines/corner_pass_finalize_bubbles_up_instrument_in_tolerance
    """
    std = create_standard(name="S-BU", nist_test_number="NIST-BU")
    inst = create_instrument(asset_tag="INST-BU", criticality="MAJOR")
    failed = finalize_passing_event(inst["id"], std["id"], inst["version"],
                                    scheduled_epoch=5, as_found_value=25.00)
    assert failed["result"] == "PASS", f"expected PASS, got {failed['result']}"
    data = validate_success(api.get_instrument(inst["id"], QE))
    assert data["calibration_status"] == "IN_TOLERANCE", \
        f"expected IN_TOLERANCE, got {data['calibration_status']}"
    assert data["next_due_epoch"] == 105, \
        f"expected next_due_epoch 105, got {data['next_due_epoch']}"
    assert data["last_calibration_epoch"] == 5, \
        f"expected last_calibration_epoch 5, got {data['last_calibration_epoch']}"


# ===========================================================================
# Corner / state_machines / corner_conditional_pass_when_as_left_recovers
# ===========================================================================
def test_conditional_pass_when_as_left_recovers(api):
    """PRD §3.4: "it is `CONDITIONAL` when at least one point fails as-found but
    every point passes as-left (the instrument was adjusted into tolerance)".
    PRD §3.4: "`as_found_in_tolerance` is true exactly when every measurement point
    has `as_found_pass` true, and `as_left_in_tolerance` is true exactly when every
    point has `as_left_pass` true."

    Design: Corner/state_machines/corner_conditional_pass_when_as_left_recovers
    """
    std = create_standard(name="S-CP", nist_test_number="NIST-CP")
    inst = create_instrument(asset_tag="INST-CP", criticality="MAJOR")
    ev = open_event(inst["id"], std["id"], inst["version"], scheduled_epoch=5)
    add_point(ev["id"], as_found_value=25.10, as_left_value=25.00)
    validate_success(api.start_event(ev["id"], TECH))
    data = validate_success(api.finalize_event(ev["id"], TECH))
    assert data["result"] == "CONDITIONAL", f"expected CONDITIONAL, got {data['result']}"
    assert data["status"] == "CONDITIONAL_PASS", \
        f"expected CONDITIONAL_PASS, got {data['status']}"
    assert data["as_found_in_tolerance"] is False, "as_found should be out of tolerance"
    assert data["as_left_in_tolerance"] is True, "as_left should be in tolerance"


# ===========================================================================
# Corner / state_machines / corner_certificate_reject_then_reissue_revert
# ===========================================================================
def test_certificate_reject_then_reissue_reverts_to_issued(api):
    """PRD §3.6: "From `ISSUED` the metrologist may instead reject the certificate
    to `REJECTED`, permitted only from `ISSUED` (otherwise `ERR_INVALID_STATE`);
    rejection frees the certificate number for reuse. A `REJECTED` certificate may
    be reissued back to `ISSUED`, permitted only from `REJECTED` (otherwise
    `ERR_INVALID_STATE`)".

    Design: Corner/state_machines/corner_certificate_reject_then_reissue_revert
    """
    std = create_standard(name="S-RR", nist_test_number="NIST-RR")
    vendor = create_vendor(name="V-RR", accreditation_body="NVLAP", accreditation_number="NV-1")
    inst = create_instrument(asset_tag="INST-RR", criticality="MAJOR")
    ev = open_event(inst["id"], std["id"], inst["version"], scheduled_epoch=5,
                    vendor_id=vendor["id"])
    add_point(ev["id"], as_found_value=25.00)
    validate_success(api.start_event(ev["id"], TECH))
    cert = validate_success(api.issue_certificate(
        ev["id"], {"vendor_id": vendor["id"], "certificate_number": "C-100",
                   "issued_epoch": 5}, MET), 201)
    validate_success(api.reject_certificate(cert["id"], MET))
    data = validate_success(api.reissue_certificate(cert["id"], {}, MET))
    assert data["status"] == "ISSUED", \
        f"expected status ISSUED after reissue, got {data['status']}"


# ===========================================================================
# Corner / state_machines / corner_terminal_retired_instrument_blocks_event_create
# ===========================================================================
def test_retired_instrument_blocks_event_create(api):
    """PRD §3.1: "Any write directed at a `RETIRED` instrument or its children is
    refused with `ERR_INSTRUMENT_RETIRED`."

    Design: Corner/state_machines/corner_terminal_retired_instrument_blocks_event_create
    """
    std = create_standard(name="S-RET", nist_test_number="NIST-RET")
    inst = create_instrument(asset_tag="INST-RET", criticality="MINOR")
    retired = validate_success(api.retire_instrument(
        inst["id"], {"expected_instrument_version": inst["version"]}, QE))
    validate_error(api.create_event(
        inst["id"], {"standard_id": std["id"], "scheduled_epoch": 5,
                     "expected_instrument_version": retired["version"]}, TECH),
        ApiErrorId.ERR_INSTRUMENT_RETIRED.value)


# ===========================================================================
# Corner / state_machines / corner_release_blocked_while_open_impact_exists
# ===========================================================================
def test_release_blocked_while_open_impact_exists(api):
    """PRD §3.1: "It is permitted only when the instrument is currently
    `QUARANTINED` (otherwise `ERR_INVALID_STATE`), when `open_oot_count` is 0 —
    meaning every out-of-tolerance impact for the instrument has reached
    `DISPOSITIONED` or `CANCELLED` (otherwise `ERR_OPEN_IMPACT_EXISTS`)".

    Design: Corner/state_machines/corner_release_blocked_while_open_impact_exists
    """
    inst, std, failed, impact = setup_quarantined_instrument(
        asset_tag="INST-REL", criticality="CRITICAL")
    inst_v = current_version(inst["id"])
    validate_error(api.release_instrument(
        inst["id"], {"expected_instrument_version": inst_v}, QE),
        ApiErrorId.ERR_OPEN_IMPACT_EXISTS.value)


# ===========================================================================
# Corner / state_machines / corner_cancel_draft_event_then_invalid_state_on_recancel
# ===========================================================================
def test_cancel_already_cancelled_event_is_invalid_state(api):
    """PRD §3.3: "A `DRAFT` event may instead be cancelled by a `Technician`, which
    is permitted only from `DRAFT` (otherwise `ERR_INVALID_STATE`); cancellation
    sets `status` to `CANCELLED`, a terminal state, and increments the event's
    version."

    Design: Corner/state_machines/corner_cancel_draft_event_then_invalid_state_on_recancel
    """
    std = create_standard(name="S-CC", nist_test_number="NIST-CC")
    inst = create_instrument(asset_tag="INST-CC", criticality="MINOR")
    ev = open_event(inst["id"], std["id"], inst["version"], scheduled_epoch=5)
    validate_success(api.cancel_event(ev["id"], TECH))
    validate_error(api.cancel_event(ev["id"], TECH), ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Corner / state_machines / corner_start_event_without_measurement_points
# ===========================================================================
def test_start_event_without_measurement_points_rejected(api):
    """PRD §3.3: "the event must already have at least one measurement point
    (otherwise `ERR_NO_MEASUREMENT_POINTS`)".

    Design: Corner/state_machines/corner_start_event_without_measurement_points
    """
    std = create_standard(name="S-NP", nist_test_number="NIST-NP")
    inst = create_instrument(asset_tag="INST-NP", criticality="MINOR")
    ev = open_event(inst["id"], std["id"], inst["version"], scheduled_epoch=5)
    validate_error(api.start_event(ev["id"], TECH),
                   ApiErrorId.ERR_NO_MEASUREMENT_POINTS.value)


# ===========================================================================
# Corner / consistency_model / corner_immediate_consistency_cascade_visible_in_same_flow
# ===========================================================================
def test_fail_finalize_cascade_immediately_visible(api):
    """PRD §2.5: "For any request whose path names more than one resource".
    PRD §3.4: "the instrument's `calibration_status` becomes `OUT_OF_TOLERANCE` and
    its `lifecycle_status` becomes `QUARANTINED`".

    An immediately-following GET reflects the cascaded instrument state (immediate
    consistency).

    Design: Corner/consistency_model/corner_immediate_consistency_cascade_visible_in_same_flow
    """
    std = create_standard(name="S-IM", nist_test_number="NIST-IM")
    inst = create_instrument(asset_tag="INST-IM", criticality="CRITICAL")
    finalize_failing_event(inst["id"], std["id"], inst["version"],
                           scheduled_epoch=5, as_found_value=25.40)
    data = validate_success(api.get_instrument(inst["id"], QE))
    assert data["lifecycle_status"] == "QUARANTINED", \
        f"expected QUARANTINED, got {data['lifecycle_status']}"
    assert data["calibration_status"] == "OUT_OF_TOLERANCE", \
        f"expected OUT_OF_TOLERANCE, got {data['calibration_status']}"
