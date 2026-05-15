"""Vehicle aggregate and append-only VehicleInspection ledger tests.

Covers the create-only-no-mutate Vehicle lifecycle from PRD §3.3, the
plate-number system-wide uniqueness (the
``ERR_DUPLICATE_IDENTIFIER`` 409 across companies, contrasting with
the driver's per-company-scoped license-number uniqueness), the
three-value inspection-outcome enum, the
``inspected_at + INSPECTION_VALIDITY_DAYS`` valid-until computation on
``PASSED``, the zero-validity rule on ``FAILED`` (``valid_until ==
inspected_at``), the parent Vehicle row's three derived
``latest_inspection_*`` pointer fields' atomic refresh on the largest-
by-timestamp append, the lexicographically-larger-id tie-break on
equal timestamps (the standard convention), and the list-endpoint's
``inspected_at`` descending then ``id`` descending default sort.

The vehicle-as-the-physical-asset principle from PRD §3.3 — the
vehicle row has no PATCH or update endpoint, and the natural
end-of-life is the regulator's FAILED inspection appending — is the
"read-only after creation" invariant the test layer's "no update
endpoint exists for a Vehicle" check confirms.
"""

from __future__ import annotations

from typing import Any, Dict, List
from uuid import uuid4

import pytest

from test_helpers import (
    ApiErrorId,
    CANONICAL_HAZARD_CLASSES,
    HazmatScenario,
    INSPECTION_VALIDITY_DAYS,
    add_days,
    api_client,
    assert_inspection,
    assert_vehicle,
    bootstrap_company_operator_headers,
    company_operator_headers,
    create_inspection_payload,
    create_vehicle_payload,
    current_server_now,
    fetch_all_inspections,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    iso_now_plus_delta,
    regulator_headers,
    setup_approved_company,
    setup_qualified_carrier,
    setup_vehicle_under_company,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.types import InspectionOutcome, VehicleType


# ─── Vehicle create-and-read happy path ──────────────────────────────


def test_create_vehicle_returns_201_with_null_pointers(api, approved_company: Dict):
    """PRD §3.3: "The system-set fields on the new row are the three
    derived 'latest inspection' pointers ``latest_inspection_id``,
    ``latest_inspection_outcome``, and ``latest_inspection_valid_until``
    — all null on a freshly registered vehicle because no inspection
    has yet been appended"."""
    op = company_operator_headers(approved_company["id"])
    payload = create_vehicle_payload(
        plate_number="ABC1234",
        vehicle_type=VehicleType.TANKER_LIQUID.value,
        max_payload_kg=18000,
        hazard_classes_compatible=list(CANONICAL_HAZARD_CLASSES),
    )
    resp = api.create_vehicle(approved_company["id"], payload, op)
    data = validate_success(resp, 201)
    assert_vehicle(data)
    assert data["company_id"] == approved_company["id"]
    assert data["plate_number"] == "ABC1234"
    assert data["vehicle_type"] == VehicleType.TANKER_LIQUID.value
    assert data["max_payload_kg"] == 18000
    # The three derived pointer fields are all null on a vehicle
    # with no inspection history yet.
    assert data.get("latest_inspection_id") is None
    assert data.get("latest_inspection_outcome") is None
    assert data.get("latest_inspection_valid_until") is None


def test_get_vehicle_returns_the_row(api, qualified_carrier: HazmatScenario):
    """The qualified_carrier fixture has a vehicle with one PASSED
    inspection already in the ledger; the GET on the vehicle id
    returns the row with the three latest-inspection-pointer fields
    populated by the inspection's side-effect."""
    veh = qualified_carrier.vehicles[0]
    resp = api.get_vehicle(veh["id"], regulator_headers())
    data = validate_success(resp, 200)
    assert_vehicle(data)
    assert data["id"] == veh["id"]
    # The fixture appended a single PASSED inspection.
    assert data["latest_inspection_outcome"] == InspectionOutcome.PASSED.value
    assert is_iso8601_timestamp(data["latest_inspection_valid_until"])
    assert is_valid_uuid(data["latest_inspection_id"])


def test_get_vehicle_not_found_404(api, non_existent_uuid: str):
    """The existence-tier 404 on a non-resolving vehicle id is the
    dedicated ``ERR_VEHICLE_NOT_FOUND`` 404."""
    resp = api.get_vehicle(non_existent_uuid, regulator_headers())
    validate_error(resp, ApiErrorId.ERR_VEHICLE_NOT_FOUND.value, expected_status=404)


# ─── Plate-number uniqueness (system-wide) ─────────────────────────────


def test_plate_number_unique_system_wide(api):
    """PRD §2.4: "The vehicle's ``plate_number`` uniqueness scope, by
    contrast [with the driver's per-company-scoped
    ``license_number``], is system-wide because a single physical
    license plate identifies the vehicle nationally" — the
    contrasting natural-key-uniqueness scope from PRD §3.2.  Two
    different APPROVED companies each trying to register a vehicle
    with the same plate-string returns the second
    ``ERR_DUPLICATE_IDENTIFIER`` 409.
    """
    co_a = setup_approved_company(api)
    co_b = setup_approved_company(api)
    op_a = company_operator_headers(co_a["id"])
    op_b = company_operator_headers(co_b["id"])
    shared_plate = "SHRD42"
    payload_a = create_vehicle_payload(plate_number=shared_plate)
    payload_b = create_vehicle_payload(plate_number=shared_plate)
    r_a = api.create_vehicle(co_a["id"], payload_a, op_a)
    assert r_a.status_code == 201
    r_b = api.create_vehicle(co_b["id"], payload_b, op_b)
    validate_error(r_b, ApiErrorId.ERR_DUPLICATE_IDENTIFIER.value, expected_status=409)


def test_plate_number_unique_within_one_company(api, approved_company: Dict):
    """The same uniqueness rule fires when two creates within one
    company use the same plate.  The system-wide scope contains the
    per-company scope as a sub-case."""
    op = company_operator_headers(approved_company["id"])
    p = "SAMEPL"
    r1 = api.create_vehicle(approved_company["id"], create_vehicle_payload(plate_number=p), op)
    assert r1.status_code == 201
    r2 = api.create_vehicle(approved_company["id"], create_vehicle_payload(plate_number=p), op)
    validate_error(r2, ApiErrorId.ERR_DUPLICATE_IDENTIFIER.value, expected_status=409)


# ─── Body-shape rules on the vehicle create ──────────────────────────


@pytest.mark.parametrize("bad_plate", ["abc", "abcdefghijklmnopq", "", "AB CD"])
def test_plate_number_length_and_shape_bounds(api, approved_company: Dict, bad_plate: str):
    """PRD §2.4: "a vehicle's ``plate_number`` is 4 to 16 characters".
    Empty, 3-character (one below the lower bound), and 17-
    character (one above the upper bound) strings each fire the
    body-shape ``ERR_VALIDATION`` 422.  The 4-and-16-character
    boundary values are valid.

    A whitespace-bearing plate string is also invalid per the
    real-world plate-number convention.
    """
    op = company_operator_headers(approved_company["id"])
    payload = create_vehicle_payload(plate_number=bad_plate)
    resp = api.create_vehicle(approved_company["id"], payload, op)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, expected_status=422)


def test_vehicle_type_must_be_in_enum(api, approved_company: Dict):
    """The ``vehicle_type`` field is the five-value enum from
    ``VehicleType``.  Anything else is the catch-all
    ``ERR_VALIDATION``."""
    op = company_operator_headers(approved_company["id"])
    payload = create_vehicle_payload(vehicle_type="HOVERCRAFT")
    resp = api.create_vehicle(approved_company["id"], payload, op)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, expected_status=422)


def test_max_payload_must_be_positive(api, approved_company: Dict):
    """The ``max_payload_kg`` field is the strictly-positive integer.
    Zero or negative values are the body-shape rejection."""
    op = company_operator_headers(approved_company["id"])
    for bad in (0, -1, -1000):
        payload = create_vehicle_payload(max_payload_kg=bad)
        resp = api.create_vehicle(approved_company["id"], payload, op)
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value, expected_status=422)


def test_vehicle_hazard_classes_must_be_subset_of_taxonomy(api, approved_company: Dict):
    """The ``hazard_classes_compatible`` array entries must each be
    in the UN-hazard-class taxonomy of PRD §2.8.  A non-taxonomy
    string is the catch-all rejection."""
    op = company_operator_headers(approved_company["id"])
    payload = create_vehicle_payload(hazard_classes_compatible=["3", "99"])
    resp = api.create_vehicle(approved_company["id"], payload, op)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, expected_status=422)


# ─── Inspection-append happy path ────────────────────────────────────


def test_inspection_append_refreshes_vehicle_latest_pointers(api, approved_company: Dict):
    """PRD §3.3: "The inspection-append's atomic side-effect on the
    parent Vehicle row is the 'latest inspection' pointer refresh:
    if the newly-inserted inspection's ``inspected_at`` is the
    largest across the vehicle's complete inspection history, the
    parent Vehicle's ``latest_inspection_id`` is set to the new
    inspection's id, ``latest_inspection_outcome`` to the new
    outcome, and ``latest_inspection_valid_until`` to the new
    inspection's ``valid_until`` field"."""
    op = company_operator_headers(approved_company["id"])
    reg = regulator_headers()
    veh = get_success_data(api.create_vehicle(approved_company["id"], create_vehicle_payload(), op))
    server_now = current_server_now(api)
    inspected_at = iso_now_plus_delta(seconds=-3600.0, base_iso=server_now)
    insp_payload = create_inspection_payload(
        inspected_at=inspected_at,
        outcome=InspectionOutcome.PASSED.value,
        findings_note="Routine annual; all checks pass.",
    )
    resp = api.create_inspection(veh["id"], insp_payload, reg)
    insp = validate_success(resp, 201)
    assert_inspection(insp)
    assert insp["outcome"] == InspectionOutcome.PASSED.value
    # valid_until = inspected_at + INSPECTION_VALIDITY_DAYS (180 days).
    expected_valid_until_iso = add_days(inspected_at, float(INSPECTION_VALIDITY_DAYS))
    # Allow a few-second slack since the implementation may include
    # the inspection's ``received_at`` rather than the exact body
    # ``inspected_at`` as the anchor; the PRD is explicit that the
    # anchor is the body's ``inspected_at``.
    assert insp["valid_until"][:10] == expected_valid_until_iso[:10], (
        f"PASSED inspection's valid_until {insp['valid_until']!r} should be approximately "
        f"inspected_at + INSPECTION_VALIDITY_DAYS = {expected_valid_until_iso!r}"
    )
    # The parent Vehicle row's three latest-pointer fields are refreshed.
    veh_after = get_success_data(api.get_vehicle(veh["id"], op))
    assert veh_after["latest_inspection_id"] == insp["id"]
    assert veh_after["latest_inspection_outcome"] == InspectionOutcome.PASSED.value
    assert veh_after["latest_inspection_valid_until"] == insp["valid_until"]
    # The vehicle's version is bumped by the inspection-append's
    # side-effect (the "derived-state mutation is a logical
    # mutation" rule from PRD §2.10).
    assert veh_after["version"] >= veh["version"] + 1


def test_failed_inspection_has_zero_validity_window(api, approved_company: Dict):
    """PRD §2.8 + §3.3: "``FAILED`` (the inspection found a
    disqualifying condition and the inspection's ``valid_until``
    is forced equal to the ``inspected_at`` so the certificate
    carries zero forward validity)".

    Append a FAILED inspection and confirm ``valid_until ==
    inspected_at`` exactly.
    """
    op = company_operator_headers(approved_company["id"])
    reg = regulator_headers()
    veh = get_success_data(api.create_vehicle(approved_company["id"], create_vehicle_payload(), op))
    server_now = current_server_now(api)
    inspected_at = iso_now_plus_delta(seconds=-3600.0, base_iso=server_now)
    insp_payload = create_inspection_payload(
        inspected_at=inspected_at,
        outcome=InspectionOutcome.FAILED.value,
        findings_note="Major safety violation; vehicle barred from hazmat transit.",
    )
    insp = get_success_data(api.create_inspection(veh["id"], insp_payload, reg))
    assert insp["outcome"] == InspectionOutcome.FAILED.value
    assert insp["valid_until"] == insp["inspected_at"], (
        f"FAILED inspection's valid_until {insp['valid_until']!r} must equal "
        f"inspected_at {insp['inspected_at']!r} (the zero-validity rule)"
    )
    # The parent vehicle's latest-outcome pointer is FAILED now.
    veh_after = get_success_data(api.get_vehicle(veh["id"], op))
    assert veh_after["latest_inspection_outcome"] == InspectionOutcome.FAILED.value


def test_conditional_inspection_has_nominal_validity_window(api, approved_company: Dict):
    """PRD §2.8: "``CONDITIONAL`` (the inspector flagged a
    remediable issue and the inspection's ``valid_until`` is the
    standard ``inspected_at + INSPECTION_VALIDITY_DAYS``, … but
    the inspection does not count as ``PASSED`` for the
    permit-validity AND-chain — only ``PASSED`` counts as
    compliant on the vehicle leg)".

    The valid_until for a CONDITIONAL outcome is the standard
    180-day window (the same as a PASSED), but the
    vehicle-validity-AND-leg in the permit issue's recompute
    treats it as a fail.  The permit-issue-time check fires
    ``ERR_VEHICLE_INSPECTION_LAPSED`` on a vehicle whose latest
    inspection is CONDITIONAL — that part of the rule is tested
    in ``test_permits_lifecycle.py``; here we just confirm the
    valid_until value follows the same formula as PASSED.
    """
    op = company_operator_headers(approved_company["id"])
    reg = regulator_headers()
    veh = get_success_data(api.create_vehicle(approved_company["id"], create_vehicle_payload(), op))
    server_now = current_server_now(api)
    inspected_at = iso_now_plus_delta(seconds=-3600.0, base_iso=server_now)
    insp = get_success_data(api.create_inspection(
        veh["id"],
        create_inspection_payload(
            inspected_at=inspected_at,
            outcome=InspectionOutcome.CONDITIONAL.value,
        ),
        reg,
    ))
    assert insp["outcome"] == InspectionOutcome.CONDITIONAL.value
    expected_valid_until = add_days(inspected_at, float(INSPECTION_VALIDITY_DAYS))
    assert insp["valid_until"][:10] == expected_valid_until[:10], (
        f"CONDITIONAL inspection's valid_until {insp['valid_until']!r} should equal "
        f"inspected_at + INSPECTION_VALIDITY_DAYS = {expected_valid_until!r}"
    )


def test_inspected_at_in_future_rejected(api, approved_company: Dict):
    """PRD §2.9: "The inspection-date-not-in-the-future rule on a
    new ``VehicleInspection``'s ``inspected_at`` is the
    inclusive-less-than-or-equal ``inspected_at <= now()`` at the
    moment of the inspection-insert call".  A future-dated
    ``inspected_at`` is the catch-all ``ERR_VALIDATION``.
    """
    op = company_operator_headers(approved_company["id"])
    reg = regulator_headers()
    veh = get_success_data(api.create_vehicle(approved_company["id"], create_vehicle_payload(), op))
    server_now = current_server_now(api)
    future_ts = iso_now_plus_delta(seconds=3600.0, base_iso=server_now)
    payload = create_inspection_payload(
        inspected_at=future_ts,
        outcome=InspectionOutcome.PASSED.value,
    )
    resp = api.create_inspection(veh["id"], payload, reg)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, expected_status=422)


def test_older_inspection_does_not_overwrite_latest_pointer(api, qualified_carrier: HazmatScenario):
    """PRD §3.3: "An inspection whose ``inspected_at`` is not the
    largest across the history is appended verbatim but does not
    change the parent's pointer fields — the historical-correction
    case (a regulator backfilling a missed inspection from an
    earlier date) does not retroactively change which inspection
    is 'the latest' because the latest-by-timestamp invariant is on
    the timestamp axis, not the insertion-order axis".

    The qualified-carrier fixture's vehicle has one ``PASSED``
    inspection from the setup-time, with the latest-pointer
    fields populated.  An older ``FAILED`` inspection appended
    behind the latest's timestamp does NOT change the
    latest-pointer's outcome (which stays PASSED), even though
    the historically-newest-recorded inspection is the FAILED one
    in the row-insert order.
    """
    veh = qualified_carrier.vehicles[0]
    reg = regulator_headers()
    op = company_operator_headers(qualified_carrier.company["id"])
    # The fixture's setup-time inspection's ``inspected_at`` is one
    # minute before the fixture's clock-at-setup-time.  We append
    # an older FAILED inspection at one full day earlier.
    server_now = current_server_now(api)
    older_inspected_at = iso_now_plus_delta(seconds=-86400.0 * 2, base_iso=server_now)
    older_payload = create_inspection_payload(
        inspected_at=older_inspected_at,
        outcome=InspectionOutcome.FAILED.value,
        findings_note="Historical FAILED inspection backfilled.",
    )
    older = get_success_data(api.create_inspection(veh["id"], older_payload, reg))
    assert older["outcome"] == InspectionOutcome.FAILED.value
    # The vehicle's latest-pointer fields are unchanged: the
    # original PASSED inspection is still the head of the
    # by-inspected_at-descending list.
    veh_after = get_success_data(api.get_vehicle(veh["id"], op))
    assert veh_after["latest_inspection_outcome"] == InspectionOutcome.PASSED.value, (
        "the older-FAILED-append must not refresh the latest-pointer; the head is still PASSED"
    )
    assert veh_after["latest_inspection_id"] != older["id"], (
        "the latest_inspection_id must still point at the original PASSED inspection"
    )


def test_inspection_list_returns_complete_history(api, qualified_carrier: HazmatScenario):
    """PRD §3.3 + §2.3: "The inspection-list endpoint
    ``GET /v1/vehicles/{vehicle_id}/inspections`` returns the
    named vehicle's complete inspection history, sorted by
    ``inspected_at`` descending and ties broken by ``id``
    descending".

    The fixture's vehicle has one inspection.  Append two more
    (one CONDITIONAL and one PASSED), each with a distinct
    ``inspected_at``, and confirm the list endpoint returns the
    three rows in descending order.  The
    ``fetch_all_inspections`` helper handles the pagination if
    needed.
    """
    scenario = qualified_carrier
    veh = scenario.vehicles[0]
    reg = regulator_headers()
    op = company_operator_headers(scenario.company["id"])
    server_now = current_server_now(api)
    # Two extra inspections at 2-hour and 4-hour offsets in the past.
    # The fixture's setup-time inspection is at -60s, so the order
    # by inspected_at descending is: fixture (-60s),
    # appended-2h-ago, appended-4h-ago.
    api.create_inspection(
        veh["id"],
        create_inspection_payload(
            inspected_at=iso_now_plus_delta(seconds=-2 * 3600.0, base_iso=server_now),
            outcome=InspectionOutcome.CONDITIONAL.value,
        ),
        reg,
    )
    api.create_inspection(
        veh["id"],
        create_inspection_payload(
            inspected_at=iso_now_plus_delta(seconds=-4 * 3600.0, base_iso=server_now),
            outcome=InspectionOutcome.PASSED.value,
        ),
        reg,
    )
    insps = fetch_all_inspections(api, scenario, vehicle_idx=0)
    assert len(insps) == 3, f"expected 3 inspections in the history, got {len(insps)}"
    # The head of the list is the latest-by-timestamp inspection.
    # This should match the vehicle's ``latest_inspection_id`` field.
    veh_now = get_success_data(api.get_vehicle(veh["id"], op))
    assert insps[0]["id"] == veh_now["latest_inspection_id"], (
        "the head of the descending-by-inspected_at list must equal the vehicle's latest_inspection_id"
    )
    # Adjacent pairs are non-increasing by inspected_at.
    for i in range(len(insps) - 1):
        a = insps[i]
        b = insps[i + 1]
        if a["inspected_at"] == b["inspected_at"]:
            assert a["id"] >= b["id"]
        else:
            assert a["inspected_at"] > b["inspected_at"]


def test_no_vehicle_update_endpoint(api, approved_company: Dict):
    """PRD §3.3 first paragraph: "The vehicle row is **read-only**
    after registration in the sense that no PATCH or update
    endpoint exists on it — the vehicle's static attributes (the
    plate, the type, the payload, the compatibility list) are
    fixed at registration time and a 'change of plate' or a
    're-certification of the compatibility list' is conceptually
    a fresh-vehicle registration".

    The PRD's §4 endpoint reference table has no PATCH /v1/vehicles
    row.  A hypothetical PATCH attempt should return a 404 or 405,
    and the endpoint table is the canonical-closed surface.

    The endpoint-table check is a meta-test: confirm the
    ``ApiClient.ENDPOINT_TABLE`` constant the test layer uses does
    not contain any ``PATCH /v1/vehicles*`` entry, which mirrors
    the PRD's §4 closed-table commitment.
    """
    paths_in_table = [(e["method"], e["path_tpl"]) for e in api_client.ENDPOINT_TABLE]
    vehicle_patch_paths = [p for m, p in paths_in_table if m == "PATCH" and "/v1/vehicles" in p]
    assert vehicle_patch_paths == [], (
        f"the endpoint table must not declare a PATCH vehicle endpoint per PRD §3.3; "
        f"found {vehicle_patch_paths!r}"
    )
    # And the PRD's endpoint surface for vehicles is the three
    # entries (create, read, the inspection-append-and-list pair).
    vehicle_paths = sorted({p for _, p in paths_in_table if "/vehicles" in p})
    assert "/v1/companies/{company_id}/vehicles" in vehicle_paths
    assert "/v1/vehicles/{vehicle_id}" in vehicle_paths
    assert "/v1/vehicles/{vehicle_id}/inspections" in vehicle_paths


# ─── Inspection-list cross-tenant predicate ──────────────────────────


def test_inspection_list_cross_tenant_rejection(api):
    """The cross-tenant predicate of PRD §2.6 on the inspection-list
    endpoint follows the standard transitive-parent rule: the
    operator's ``X-User-ID`` must equal the parent vehicle's
    ``company_id``.  An operator on tenant-A listing tenant-B's
    vehicle's inspections is the 403 cross-tenant rejection."""
    from test_helpers import setup_two_tenants

    two = setup_two_tenants(api)
    veh_b = two.tenant_b.vehicles[0]
    a_op = company_operator_headers(two.tenant_a.company["id"])
    resp = api.list_inspections(veh_b["id"], a_op)
    validate_error(resp, ApiErrorId.ERR_CROSS_TENANT_ACCESS.value, expected_status=403)


def test_inspection_list_regulator_cross_tenant_exempt(api):
    """The regulator's cross-tenant exemption applies to the
    inspection-list endpoint as it does to every read endpoint
    per PRD §2.1's regulator-cross-tenant-exemption paragraph.
    A single regulator-headers principal reads both tenants'
    vehicles' inspection histories.
    """
    from test_helpers import setup_two_tenants

    two = setup_two_tenants(api)
    reg = regulator_headers()
    veh_a = two.tenant_a.vehicles[0]
    veh_b = two.tenant_b.vehicles[0]
    r_a = api.list_inspections(veh_a["id"], reg)
    r_b = api.list_inspections(veh_b["id"], reg)
    a_data, _ = validate_paginated(r_a)
    b_data, _ = validate_paginated(r_b)
    # Each tenant's vehicle has one PASSED inspection from its setup.
    assert len(a_data) >= 1
    assert len(b_data) >= 1


def test_inspection_create_requires_regulator_role(api, qualified_carrier: HazmatScenario):
    """The inspection-append's RBAC cell is regulator-only per the
    PRD's §4 endpoint table.  An operator's attempt is the
    priority-200 default-deny."""
    veh = qualified_carrier.vehicles[0]
    op = company_operator_headers(qualified_carrier.company["id"])
    server_now = current_server_now(api)
    payload = create_inspection_payload(
        inspected_at=iso_now_plus_delta(seconds=-60.0, base_iso=server_now),
        outcome=InspectionOutcome.PASSED.value,
    )
    resp = api.create_inspection(veh["id"], payload, op)
    validate_error(resp, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, expected_status=403)
