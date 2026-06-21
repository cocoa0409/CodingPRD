"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    "STD_NAME": "GB-Master",
    "NIST_TEST_NUMBER": "NIST-1",
    "STD_NOMINAL": 25.0,
    "STD_UNIT": "mm",
    "STD_UNCERTAINTY": 0.001,
    "CERTIFIED_THROUGH": 9999,
    "VENDOR_NAME": "AccLab",
    "ACCREDITATION_BODY": "A2LA",
    "ACCREDITATION_NUMBER": "A2LA-001",
    "ACCREDITED_THROUGH": 9999,
    "ASSET_TAG": "INST-1",
    "INST_DESCRIPTION": "Test gauge",
    "INST_NOMINAL": 25.0,
    "TOL_PLUS": 0.05,
    "TOL_MINUS": 0.05,
    "MEASUREMENT_UNIT": "mm",
    "INTERVAL": 100,
    "CRITICALITY": "MAJOR",
    "SCHEDULED_EPOCH": 5,
    "POINT_LABEL": "P1",
    "POINT_NOMINAL": 25.0,
    "POINT_TOL_PLUS": 0.05,
    "POINT_TOL_MINUS": 0.05,
    "POINT_AS_FOUND": 25.00,
    "PROCESS_TOLERANCE": 10.0,
    "PRODUCT_SERIAL": "S-1",
}


def create_standard_payload(**overrides) -> dict:
    """CalibrationStandard input: name, nist_test_number, parent_standard_id?,
    nominal_value, standard_unit, uncertainty, certified_through_epoch."""
    payload = {
        "name": DEFAULTS["STD_NAME"],
        "nist_test_number": DEFAULTS["NIST_TEST_NUMBER"],
        "nominal_value": DEFAULTS["STD_NOMINAL"],
        "standard_unit": DEFAULTS["STD_UNIT"],
        "uncertainty": DEFAULTS["STD_UNCERTAINTY"],
        "certified_through_epoch": DEFAULTS["CERTIFIED_THROUGH"],
    }
    payload.update(overrides)
    return payload


def create_vendor_payload(**overrides) -> dict:
    """CalibrationVendor input: name, accreditation_body, accreditation_number?,
    accredited_through_epoch."""
    payload = {
        "name": DEFAULTS["VENDOR_NAME"],
        "accreditation_body": DEFAULTS["ACCREDITATION_BODY"],
        "accreditation_number": DEFAULTS["ACCREDITATION_NUMBER"],
        "accredited_through_epoch": DEFAULTS["ACCREDITED_THROUGH"],
    }
    payload.update(overrides)
    return payload


def create_instrument_payload(**overrides) -> dict:
    """Instrument input: asset_tag, description, nominal_value, tolerance_plus,
    tolerance_minus, measurement_unit, calibration_interval_epochs, criticality."""
    payload = {
        "asset_tag": DEFAULTS["ASSET_TAG"],
        "description": DEFAULTS["INST_DESCRIPTION"],
        "nominal_value": DEFAULTS["INST_NOMINAL"],
        "tolerance_plus": DEFAULTS["TOL_PLUS"],
        "tolerance_minus": DEFAULTS["TOL_MINUS"],
        "measurement_unit": DEFAULTS["MEASUREMENT_UNIT"],
        "calibration_interval_epochs": DEFAULTS["INTERVAL"],
        "criticality": DEFAULTS["CRITICALITY"],
    }
    payload.update(overrides)
    return payload


def create_event_payload(standard_id, expected_instrument_version, **overrides) -> dict:
    """CalibrationEvent input: standard_id, vendor_id?, scheduled_epoch,
    expected_instrument_version."""
    payload = {
        "standard_id": standard_id,
        "scheduled_epoch": DEFAULTS["SCHEDULED_EPOCH"],
        "expected_instrument_version": expected_instrument_version,
    }
    payload.update(overrides)
    return payload


def create_measurement_point_payload(**overrides) -> dict:
    """MeasurementPoint input: point_label, nominal, tol_plus, tol_minus,
    as_found_value, as_left_value?."""
    payload = {
        "point_label": DEFAULTS["POINT_LABEL"],
        "nominal": DEFAULTS["POINT_NOMINAL"],
        "tol_plus": DEFAULTS["POINT_TOL_PLUS"],
        "tol_minus": DEFAULTS["POINT_TOL_MINUS"],
        "as_found_value": DEFAULTS["POINT_AS_FOUND"],
    }
    payload.update(overrides)
    return payload


def create_certificate_payload(vendor_id, certificate_number, issued_epoch, **overrides) -> dict:
    """CalibrationCertificate input: vendor_id, certificate_number, issued_epoch."""
    payload = {
        "vendor_id": vendor_id,
        "certificate_number": certificate_number,
        "issued_epoch": issued_epoch,
    }
    payload.update(overrides)
    return payload


def create_affected_product_payload(product_serial, measured_epoch, **overrides) -> dict:
    """AffectedProduct input: product_serial, measured_epoch."""
    payload = {"product_serial": product_serial, "measured_epoch": measured_epoch}
    payload.update(overrides)
    return payload


def create_study_payload(expected_instrument_version, **overrides) -> dict:
    """GageRRStudy input: operator_count, part_count, trial_count,
    process_tolerance, expected_instrument_version."""
    payload = {
        "operator_count": 2,
        "part_count": 2,
        "trial_count": 2,
        "process_tolerance": DEFAULTS["PROCESS_TOLERANCE"],
        "expected_instrument_version": expected_instrument_version,
    }
    payload.update(overrides)
    return payload


def create_trial_payload(operator_index, part_index, trial_index, measured_value, **overrides) -> dict:
    """GageRRTrial input: operator_index, part_index, trial_index, measured_value."""
    payload = {
        "operator_index": operator_index,
        "part_index": part_index,
        "trial_index": trial_index,
        "measured_value": measured_value,
    }
    payload.update(overrides)
    return payload
