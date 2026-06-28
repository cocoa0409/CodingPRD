"""Composite setup helpers for the Calibration & Gage Management API.

Each test runs against a freshly restarted, empty server (the harness restarts the
server via start.sh before every pytest test), so every fixture builds its
preconditions from scratch using only PRD-declared endpoints. Fixtures use
get_success_data() (lenient) so a setup failure surfaces as a clear "Setup failed"
error rather than a confusing assertion mismatch.

All three roles are opaque (PRD §2.1): the shared TEST_USERS headers are canonical.
Where a test must control a specific X-User-ID (segregation of duties), the caller
passes explicit headers built with make_*_headers().
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_quality_engineer_headers,
    make_technician_headers,
)

# Role shorthands (opaque identities).
TECH = TEST_USERS["technician_headers"]
QE = TEST_USERS["quality_engineer_headers"]
MET = TEST_USERS["metrologist_headers"]


# ---------------------------------------------------------------------------
# Atomic helpers
# ---------------------------------------------------------------------------
def create_standard(name="GB-Master", nist_test_number="NIST-1", uncertainty=0.001,
                    certified_through_epoch=9999, nominal_value=25.0, standard_unit="mm",
                    parent_standard_id=None, headers=None):
    """Register a CalibrationStandard. Returns the standard object."""
    payload = {
        "name": name,
        "nist_test_number": nist_test_number,
        "nominal_value": nominal_value,
        "standard_unit": standard_unit,
        "uncertainty": uncertainty,
        "certified_through_epoch": certified_through_epoch,
    }
    if parent_standard_id is not None:
        payload["parent_standard_id"] = parent_standard_id
    return get_success_data(api_client.create_standard(payload, headers or MET))


def create_vendor(name="AccLab", accreditation_body="A2LA", accreditation_number="A2LA-001",
                  accredited_through_epoch=9999, headers=None):
    """Register an accredited CalibrationVendor. Returns the vendor object."""
    payload = {
        "name": name,
        "accreditation_body": accreditation_body,
        "accredited_through_epoch": accredited_through_epoch,
    }
    if accreditation_number is not None:
        payload["accreditation_number"] = accreditation_number
    return get_success_data(api_client.create_vendor(payload, headers or MET))


def create_instrument(asset_tag="INST-1", nominal_value=25.0, tolerance_plus=0.05,
                      tolerance_minus=0.05, measurement_unit="mm",
                      calibration_interval_epochs=100, criticality="MAJOR",
                      description="Test gauge", headers=None):
    """Register an ACTIVE / UNCALIBRATED instrument. Returns the instrument object."""
    payload = {
        "asset_tag": asset_tag,
        "description": description,
        "nominal_value": nominal_value,
        "tolerance_plus": tolerance_plus,
        "tolerance_minus": tolerance_minus,
        "measurement_unit": measurement_unit,
        "calibration_interval_epochs": calibration_interval_epochs,
        "criticality": criticality,
    }
    return get_success_data(api_client.create_instrument(payload, headers or QE))


def open_event(instrument_id, standard_id, expected_instrument_version,
               scheduled_epoch=5, vendor_id=None, headers=None):
    """Open a DRAFT calibration event under an instrument (OCC-guarded).
    Returns the event object."""
    payload = {
        "standard_id": standard_id,
        "scheduled_epoch": scheduled_epoch,
        "expected_instrument_version": expected_instrument_version,
    }
    if vendor_id is not None:
        payload["vendor_id"] = vendor_id
    return get_success_data(api_client.create_event(instrument_id, payload, headers or TECH))


def add_point(event_id, point_label="P1", nominal=25.0, tol_plus=0.05, tol_minus=0.05,
              as_found_value=25.00, as_left_value=None, headers=None):
    """Add a measurement point to a DRAFT/IN_PROGRESS event. Returns the point object."""
    payload = {
        "point_label": point_label,
        "nominal": nominal,
        "tol_plus": tol_plus,
        "tol_minus": tol_minus,
        "as_found_value": as_found_value,
    }
    if as_left_value is not None:
        payload["as_left_value"] = as_left_value
    return get_success_data(api_client.add_measurement_point(event_id, payload, headers or TECH))


def current_version(instrument_id, headers=None):
    """Read the instrument's current version (for chaining OCC-guarded creates)."""
    inst = get_success_data(api_client.get_instrument(instrument_id, headers or QE))
    return inst["version"]


# ---------------------------------------------------------------------------
# Tier 1/3: full event lifecycle shortcuts
# ---------------------------------------------------------------------------
def finalize_passing_event(instrument_id, standard_id, expected_instrument_version,
                           scheduled_epoch=5, as_found_value=25.00,
                           tech_headers=None):
    """Open → add one passing point → start → finalize to PASS. Returns the
    finalized event object (result PASS)."""
    th = tech_headers or TECH
    ev = open_event(instrument_id, standard_id, expected_instrument_version,
                    scheduled_epoch=scheduled_epoch, headers=th)
    add_point(ev["id"], as_found_value=as_found_value, headers=th)
    get_success_data(api_client.start_event(ev["id"], th))
    return get_success_data(api_client.finalize_event(ev["id"], th))


def finalize_failing_event(instrument_id, standard_id, expected_instrument_version,
                           scheduled_epoch=5, as_found_value=25.40,
                           tech_headers=None):
    """Open → add one failing point (as_left out of tolerance) → start → finalize
    to FAIL. This quarantines the instrument and auto-creates an OPEN impact.
    Returns the finalized event object (result FAIL)."""
    th = tech_headers or TECH
    ev = open_event(instrument_id, standard_id, expected_instrument_version,
                    scheduled_epoch=scheduled_epoch, headers=th)
    add_point(ev["id"], as_found_value=as_found_value, as_left_value=as_found_value, headers=th)
    get_success_data(api_client.start_event(ev["id"], th))
    return get_success_data(api_client.finalize_event(ev["id"], th))


def get_only_impact(instrument_id, headers=None):
    """Return the (first) auto-created impact for the instrument."""
    data = get_success_data(api_client.list_instrument_impacts(instrument_id, headers or QE))
    assert data, "Setup failed: expected at least one auto-created impact"
    return data[0]


# ---------------------------------------------------------------------------
# Tier 2/3: instrument quarantined via a FAILED event (impact OPEN)
# ---------------------------------------------------------------------------
def setup_quarantined_instrument(asset_tag="INST-Q", scheduled_epoch=5,
                                 criticality="CRITICAL", interval=100,
                                 qe_headers=None, tech_headers=None, met_headers=None):
    """Create a standard + ACTIVE instrument, then run a FAIL finalize so the
    instrument is QUARANTINED / OUT_OF_TOLERANCE with one auto-created OPEN impact.

    Returns (instrument, standard, failed_event, impact). The instrument dict is
    the post-create snapshot; re-GET for the current version when needed.
    """
    met = met_headers or MET
    qe = qe_headers or QE
    th = tech_headers or TECH
    std = create_standard(name=asset_tag + "-STD", nist_test_number="NIST-" + asset_tag,
                          headers=met)
    inst = create_instrument(asset_tag=asset_tag, criticality=criticality,
                             calibration_interval_epochs=interval, headers=qe)
    failed = finalize_failing_event(inst["id"], std["id"], inst["version"],
                                    scheduled_epoch=scheduled_epoch, tech_headers=th)
    impact = get_only_impact(inst["id"], headers=qe)
    return inst, std, failed, impact


# ---------------------------------------------------------------------------
# Tier 4: gage R&R study matrix
# ---------------------------------------------------------------------------
# The 2x2x2 measured-value matrix that yields pct_grr == 32.27 (UNACCEPTABLE):
GRR_UNACCEPTABLE_MATRIX = [
    (1, 1, 1, 2.0), (1, 1, 2, 2.1),
    (1, 2, 1, 3.0), (1, 2, 2, 3.0),
    (2, 1, 1, 2.2), (2, 1, 2, 2.0),
    (2, 2, 1, 3.1), (2, 2, 2, 3.2),
]

# The 2x2x2 matrix with zero variation (identical repeats and operators) that
# yields pct_grr == 0.0 (ACCEPTABLE):
GRR_ZERO_VARIATION_MATRIX = [
    (1, 1, 1, 5.0), (1, 1, 2, 5.0),
    (1, 2, 1, 8.0), (1, 2, 2, 8.0),
    (2, 1, 1, 5.0), (2, 1, 2, 5.0),
    (2, 2, 1, 8.0), (2, 2, 2, 8.0),
]


def create_collecting_study(instrument_id, expected_instrument_version,
                            operator_count=2, part_count=2, trial_count=2,
                            process_tolerance=10.0, qe_headers=None):
    """Create a gage R&R study (OCC-guarded) and open it to COLLECTING.
    Returns the study object."""
    qe = qe_headers or QE
    study = get_success_data(api_client.create_study(
        instrument_id,
        {
            "operator_count": operator_count,
            "part_count": part_count,
            "trial_count": trial_count,
            "process_tolerance": process_tolerance,
            "expected_instrument_version": expected_instrument_version,
        },
        qe,
    ))
    get_success_data(api_client.open_study(study["id"], qe))
    return study


def fill_trials(study_id, matrix, tech_headers=None):
    """Record every (operator,part,trial,value) cell from a matrix list."""
    th = tech_headers or TECH
    for o, p, t, val in matrix:
        get_success_data(api_client.add_trial(
            study_id,
            {"operator_index": o, "part_index": p, "trial_index": t, "measured_value": val},
            th,
        ))


def setup_analyzed_study(instrument_id, expected_instrument_version,
                         matrix=None, process_tolerance=10.0,
                         qe_headers=None, tech_headers=None):
    """Create a COLLECTING study, fill the full 2x2x2 trial matrix, and analyze it.
    Returns the analyzed study object. Default matrix yields pct_grr 32.27.
    """
    qe = qe_headers or QE
    study = create_collecting_study(instrument_id, expected_instrument_version,
                                    process_tolerance=process_tolerance, qe_headers=qe)
    fill_trials(study["id"], matrix if matrix is not None else GRR_UNACCEPTABLE_MATRIX,
                tech_headers=tech_headers)
    return get_success_data(api_client.analyze_study(study["id"], qe))
