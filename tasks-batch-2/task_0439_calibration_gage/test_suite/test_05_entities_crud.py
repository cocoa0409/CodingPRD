"""Entity CRUD surface: creation defaults, not-found, required-field and type
constraints, system-managed fields, the singleton clock, listing, and computed
traceability.

Corner queue: entities section.
"""
from test_helpers import validate_success, validate_error, validate_paginated, NON_EXISTENT_UUID
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import MET, QE
from test_helpers.factories import create_instrument_payload


# ===========================================================================
# Corner / entities / corner_instrument_create_returns_201_with_defaults
# ===========================================================================
def test_instrument_create_returns_201_with_defaults(api):
    """PRD §3.1: "A freshly registered instrument starts with `lifecycle_status` of
    `ACTIVE` and `calibration_status` of `UNCALIBRATED`, and its open-impact counter
    `open_oot_count` begins at 0."
    PRD §2.4: "The `version` field is an integer that begins at its initial value
    and increments by one on every mutation of the resource".

    Design: Corner/entities/corner_instrument_create_returns_201_with_defaults
    """
    data = validate_success(api.create_instrument(
        create_instrument_payload(asset_tag="INST-NEW", nominal_value=10.0,
                                  tolerance_plus=0.1, tolerance_minus=0.1,
                                  calibration_interval_epochs=30), QE), 201)
    assert data["lifecycle_status"] == "ACTIVE", \
        f"expected lifecycle_status ACTIVE, got {data['lifecycle_status']}"
    assert data["calibration_status"] == "UNCALIBRATED", \
        f"expected calibration_status UNCALIBRATED, got {data['calibration_status']}"
    assert data["version"] == 1, f"expected version 1, got {data['version']}"
    assert data["open_oot_count"] == 0, f"expected open_oot_count 0, got {data['open_oot_count']}"


# ===========================================================================
# Corner / entities / corner_instrument_get_not_found
# ===========================================================================
def test_instrument_get_not_found(api):
    """PRD §2.5: "the server validates path identifiers strictly left to right and
    rejects with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not
    resolve."

    Design: Corner/entities/corner_instrument_get_not_found
    """
    validate_error(api.get_instrument(NON_EXISTENT_UUID, QE),
                   ApiErrorId.ERR_NOT_FOUND.value)


# ===========================================================================
# Corner / entities / corner_instrument_missing_required_field
# ===========================================================================
def test_instrument_missing_required_asset_tag(api):
    """PRD §2.10: "After existence comes request well-formedness — required fields
    present and correctly typed, enum members valid, and numeric ranges satisfied
    such as non-negative tolerances and counts within their stated bounds
    (`ERR_INVALID_REQUEST`, HTTP 422)."

    Design: Corner/entities/corner_instrument_missing_required_field
    """
    payload = create_instrument_payload(nominal_value=10.0, tolerance_plus=0.1,
                                        tolerance_minus=0.1, calibration_interval_epochs=30)
    payload.pop("asset_tag")
    validate_error(api.create_instrument(payload, QE), ApiErrorId.ERR_INVALID_REQUEST.value)


# ===========================================================================
# Corner / entities / corner_instrument_invalid_enum_criticality
# ===========================================================================
def test_instrument_invalid_criticality_enum(api):
    """PRD §3.1: "a `criticality` of `CRITICAL`, `MAJOR`, or `MINOR`."
    PRD §2.10: "enum members valid ... (`ERR_INVALID_REQUEST`, HTTP 422)."

    Design: Corner/entities/corner_instrument_invalid_enum_criticality
    """
    validate_error(api.create_instrument(
        create_instrument_payload(asset_tag="INST-BADENUM", nominal_value=10.0,
                                  tolerance_plus=0.1, tolerance_minus=0.1,
                                  calibration_interval_epochs=30, criticality="URGENT"), QE),
        ApiErrorId.ERR_INVALID_REQUEST.value)


# ===========================================================================
# Corner / entities / corner_instrument_negative_tolerance_rejected
# ===========================================================================
def test_instrument_negative_tolerance_rejected(api):
    """PRD §3.1: "the upper and lower tolerance offsets `tolerance_plus` and
    `tolerance_minus` (each of which must be non-negative)".
    PRD §2.10: "numeric ranges satisfied such as non-negative tolerances ...
    (`ERR_INVALID_REQUEST`, HTTP 422)."

    Design: Corner/entities/corner_instrument_negative_tolerance_rejected
    """
    validate_error(api.create_instrument(
        create_instrument_payload(asset_tag="INST-NEGTOL", nominal_value=10.0,
                                  tolerance_plus=-0.1, tolerance_minus=0.1,
                                  calibration_interval_epochs=30), QE),
        ApiErrorId.ERR_INVALID_REQUEST.value)


# ===========================================================================
# Corner / entities / corner_system_fields_input_ignored_on_instrument_create
# ===========================================================================
def test_instrument_create_ignores_client_lifecycle_status(api):
    """PRD §3.1: "A freshly registered instrument starts with `lifecycle_status` of
    `ACTIVE`".

    A client-supplied lifecycle_status is ignored; the server forces ACTIVE.

    Design: Corner/entities/corner_system_fields_input_ignored_on_instrument_create
    """
    payload = create_instrument_payload(asset_tag="INST-IGN", nominal_value=10.0,
                                        tolerance_plus=0.1, tolerance_minus=0.1,
                                        calibration_interval_epochs=30)
    payload["lifecycle_status"] = "RETIRED"
    data = validate_success(api.create_instrument(payload, QE), 201)
    assert data["lifecycle_status"] == "ACTIVE", \
        f"client lifecycle_status must be ignored; expected ACTIVE, got {data['lifecycle_status']}"


# ===========================================================================
# Corner / entities / corner_clockstate_immutable_no_version_field
# ===========================================================================
def test_clock_boots_at_epoch_zero(api):
    """PRD §2.4: "The server boots with `current_epoch` equal to 0, which by
    definition maps to the default instant of 2026-01-01T00:00:00Z UTC."

    Design: Corner/entities/corner_clockstate_immutable_no_version_field
    """
    data = validate_success(api.get_clock(QE))
    assert data["current_epoch"] == 0, \
        f"expected boot current_epoch 0, got {data['current_epoch']}"


# ===========================================================================
# Corner / entities / corner_standard_listing_pagination_envelope
# ===========================================================================
def test_standard_listing_returns_paginated_envelope(api):
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the envelope."

    Design: Corner/entities/corner_standard_listing_pagination_envelope
    """
    validate_success(api.create_standard(
        {"name": "S-LIST", "nist_test_number": "NIST-L1", "nominal_value": 1.0,
         "standard_unit": "mm", "uncertainty": 0.001, "certified_through_epoch": 9999}, MET), 201)
    data, meta = validate_paginated(api.list_standards(MET, params={"limit": 10, "offset": 0}))
    assert isinstance(data, list), "list data must be an array"
    assert isinstance(meta["total_count"], int), "meta must carry total_count"
    assert isinstance(meta["has_more"], bool), "meta must carry has_more"


# ===========================================================================
# Corner / entities / corner_standard_computed_traceability_depth
# ===========================================================================
def test_standard_child_traceability_depth_is_one(api):
    """PRD §2.8: "The computed `traceability_depth` is 0 at the anchor and is one
    greater than the parent's depth at every other node."
    PRD §2.8: "The computed `is_traceable` flag is true only when every standard on
    the path from the leaf up to and including the anchor is in `ACTIVE` status and
    has a `certified_through_epoch` greater than or equal to the clock's
    `current_epoch`."

    Design: Corner/entities/corner_standard_computed_traceability_depth
    """
    anchor = validate_success(api.create_standard(
        {"name": "ANCHOR", "nist_test_number": "NIST-A", "nominal_value": 1.0,
         "standard_unit": "mm", "uncertainty": 0.0005, "certified_through_epoch": 9999}, MET), 201)
    child = validate_success(api.create_standard(
        {"name": "CHILD", "nist_test_number": "", "parent_standard_id": anchor["id"],
         "nominal_value": 1.0, "standard_unit": "mm", "uncertainty": 0.001,
         "certified_through_epoch": 9999}, MET), 201)
    data = validate_success(api.get_standard(child["id"], MET))
    assert data["traceability_depth"] == 1, \
        f"expected traceability_depth 1, got {data['traceability_depth']}"
    assert data["is_traceable"] is True, "child traced to a current anchor must be traceable"
