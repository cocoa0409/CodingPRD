"""Composite precondition builders.

Every test starts against an empty database, so every precondition is built
here from scratch through the published write endpoints. The builders are
layered:

* Tier 0 — the logical clock and the reference tables.
* Tier 1 — state progression: one entity walked to a named status.
* Tier 2 — entity hierarchy: a carrier with its fleet, drivers and application.
* Tier 3 — full lifecycle shortcuts: prepared and filed quarters, issued paper.
* Tier 4 — accumulation and threshold targeting: a carrier positioned at a
  chosen unsubstantiated ratio or risk score.
* Tier 5 — finalization and terminal states: reviewed audits, suspended and
  revoked licensees.

Builders read responses with ``get_success_data`` so that a precondition step
never masquerades as the assertion under test.
"""
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import ApportionmentClient
from .constants import (
    CANONICAL_JURISDICTIONS,
    CLOCK_INITIAL_UTC,
    REGISTRATION_YEAR,
    WEIGHT_GROUP_FEES_W80,
    WEIGHT_GROUP_W80,
)
from .factories import (
    audit_selection_payload,
    carrier_payload,
    distance_schedule_line_payload,
    driver_payload,
    fleet_change_request_payload,
    fuel_purchase_payload,
    fuel_tax_return_payload,
    leg,
    registration_application_payload,
    trip_record_payload,
    vehicle_payload,
    weight_group_fee_payload,
)
from .test_users import (
    ANALYST_1_HEADERS,
    ANALYST_2_HEADERS,
    OFFICER_1_HEADERS,
    OFFICER_2_HEADERS,
    PREPARER_1_HEADERS,
    make_carrier_admin_headers,
)


# ==========================================================================
# Tier 0 — clock and reference tables
# ==========================================================================

def set_clock(client: ApportionmentClient, instant: str = CLOCK_INITIAL_UTC) -> None:
    """Pin the logical clock. Every scenario does this first so that retention,
    reconstruction-window, quarter-window, proration and credential-validity
    rules all read a known instant."""
    client.set_clock(instant, OFFICER_1_HEADERS)


def seed_jurisdictions(
    client: ApportionmentClient,
    jurisdictions: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Declare the member jurisdictions. Returns them keyed by code."""
    rows = jurisdictions if jurisdictions is not None else CANONICAL_JURISDICTIONS
    created: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        data = get_success_data(client.create_jurisdiction(dict(row), OFFICER_1_HEADERS))
        created[data["jurisdiction_code"]] = data
    return created


def seed_weight_group_fees(
    client: ApportionmentClient,
    fees: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Publish the apportioned-fee chart cells. Returns them keyed by code."""
    rows = fees if fees is not None else WEIGHT_GROUP_FEES_W80
    created: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        data = get_success_data(
            client.create_weight_group_fee(dict(row), OFFICER_1_HEADERS)
        )
        created[data["jurisdiction_code"]] = data
    return created


def seed_reference_data(
    client: ApportionmentClient,
    jurisdictions: Optional[List[Dict[str, Any]]] = None,
    fees: Optional[List[Dict[str, Any]]] = None,
    instant: str = CLOCK_INITIAL_UTC,
) -> Dict[str, Any]:
    """Clock plus both reference tables — the floor every scenario stands on.

    A fee cell may only name a jurisdiction that has already been declared, so
    when a narrower set of jurisdictions is requested the default fee chart is
    narrowed to match.
    """
    set_clock(client, instant)
    declared = seed_jurisdictions(client, jurisdictions)
    if fees is None:
        fees = [
            row
            for row in WEIGHT_GROUP_FEES_W80
            if row["jurisdiction_code"] in declared
        ]
    return {
        "jurisdictions": declared,
        "weight_group_fees": seed_weight_group_fees(client, fees),
    }


def seed_reference_data_il_in_only(
    client: ApportionmentClient, instant: str = CLOCK_INITIAL_UTC
) -> Dict[str, Any]:
    """Only Illinois and Indiana are declared, with the matching two fee cells."""
    jurisdictions = [j for j in CANONICAL_JURISDICTIONS if j["jurisdiction_code"] != "KY"]
    fees = [f for f in WEIGHT_GROUP_FEES_W80 if f["jurisdiction_code"] != "KY"]
    return seed_reference_data(client, jurisdictions, fees, instant)


# ==========================================================================
# Tier 1 — single entities and state progression
# ==========================================================================

def create_carrier(client: ApportionmentClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        client.create_carrier(carrier_payload(**overrides), OFFICER_1_HEADERS)
    )


def read_carrier(client: ApportionmentClient, carrier_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_carrier(carrier_id, OFFICER_1_HEADERS))


def carrier_version(client: ApportionmentClient, carrier_id: str) -> int:
    return read_carrier(client, carrier_id)["version"]


def create_vehicle(
    client: ApportionmentClient, carrier_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        client.create_vehicle(vehicle_payload(carrier_id, **overrides), OFFICER_1_HEADERS)
    )


def read_vehicle(client: ApportionmentClient, vehicle_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_vehicle(vehicle_id, OFFICER_1_HEADERS))


def create_driver(
    client: ApportionmentClient, carrier_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        client.create_driver(driver_payload(carrier_id, **overrides), OFFICER_1_HEADERS)
    )


def capture_trip(
    client: ApportionmentClient,
    carrier_id: str,
    vehicle_id: str,
    trip_start_utc: str,
    trip_end_utc: str,
    start_odometer: float,
    end_odometer: float,
    legs: List[Dict[str, Any]],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Capture one telematics trip. Whether it is born ``CAPTURED`` or
    ``GAP_FLAGGED`` is decided by the server from the odometer gap."""
    payload = trip_record_payload(
        carrier_id,
        vehicle_id,
        trip_start_utc=trip_start_utc,
        trip_end_utc=trip_end_utc,
        start_odometer=start_odometer,
        end_odometer=end_odometer,
        legs=legs,
    )
    return get_success_data(
        client.create_trip_record(payload, headers or ANALYST_1_HEADERS)
    )


def read_trip(client: ApportionmentClient, trip_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_trip_record(trip_id, OFFICER_1_HEADERS))


def trip_legs(
    client: ApportionmentClient, trip_id: str, leg_status: Optional[str] = None
) -> List[Dict[str, Any]]:
    params = {"leg_status": leg_status} if leg_status else None
    response = client.list_trip_mileage_legs(trip_id, OFFICER_1_HEADERS, params=params)
    return response.json()["data"]


def reconstruct_trip(
    client: ApportionmentClient,
    trip_id: str,
    reconstructed_legs: List[Dict[str, Any]],
    supporting_document_reference: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        client.reconstruct_trip_record(
            trip_id,
            headers or ANALYST_1_HEADERS,
            reconstructed_legs=reconstructed_legs,
            supporting_document_reference=supporting_document_reference,
        )
    )


def review_trip(
    client: ApportionmentClient,
    trip_id: str,
    decision: str,
    headers: Optional[Dict[str, str]] = None,
    review_note: Any = ...,
) -> Dict[str, Any]:
    return get_success_data(
        client.review_trip_record(
            trip_id, headers or OFFICER_1_HEADERS, decision=decision, review_note=review_note
        )
    )


def accept_trip(
    client: ApportionmentClient,
    trip_id: str,
    headers: Optional[Dict[str, str]] = None,
    review_note: Any = ...,
) -> Dict[str, Any]:
    return review_trip(client, trip_id, "ACCEPT", headers, review_note=review_note)


def reject_trip(
    client: ApportionmentClient,
    trip_id: str,
    headers: Optional[Dict[str, str]] = None,
    review_note: Any = ...,
) -> Dict[str, Any]:
    return review_trip(client, trip_id, "REJECT", headers, review_note=review_note)


def record_purchase(
    client: ApportionmentClient,
    carrier_id: str,
    vehicle_id: str,
    jurisdiction_code: str,
    purchase_date: str,
    gallons: float,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = fuel_purchase_payload(
        carrier_id,
        vehicle_id,
        jurisdiction_code=jurisdiction_code,
        purchase_date=purchase_date,
        gallons=gallons,
        **overrides,
    )
    return get_success_data(
        client.create_fuel_purchase(payload, headers or ANALYST_1_HEADERS)
    )


def read_purchase(client: ApportionmentClient, purchase_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_fuel_purchase(purchase_id, OFFICER_1_HEADERS))


def open_return(
    client: ApportionmentClient,
    carrier_id: str,
    filing_year: int = REGISTRATION_YEAR,
    filing_quarter: int = 2,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        client.create_fuel_tax_return(
            fuel_tax_return_payload(carrier_id, filing_year, filing_quarter),
            headers or PREPARER_1_HEADERS,
        )
    )


def read_return(client: ApportionmentClient, return_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_fuel_tax_return(return_id, OFFICER_1_HEADERS))


def return_lines(
    client: ApportionmentClient, return_id: str, line_status: Optional[str] = None
) -> List[Dict[str, Any]]:
    params = {"line_status": line_status} if line_status else None
    response = client.list_return_jurisdiction_lines(
        return_id, OFFICER_1_HEADERS, params=params
    )
    return response.json()["data"]


def prepare_return(
    client: ApportionmentClient,
    return_id: str,
    carrier_id: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Compute the quarter on the preparer basis, re-reading the carrier's
    ``version`` immediately beforehand so that the concurrency check passes."""
    version = carrier_version(client, carrier_id)
    return get_success_data(
        client.prepare_fuel_tax_return(
            return_id,
            headers or PREPARER_1_HEADERS,
            expected_carrier_version=version,
        )
    )


def review_return(
    client: ApportionmentClient,
    return_id: str,
    decision: str,
    headers: Optional[Dict[str, str]] = None,
    review_note: Any = ...,
) -> Dict[str, Any]:
    return get_success_data(
        client.review_fuel_tax_return(
            return_id,
            headers or OFFICER_1_HEADERS,
            decision=decision,
            review_note=review_note,
        )
    )


def file_return(
    client: ApportionmentClient, return_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return review_return(client, return_id, "FILE", headers)


def open_application(
    client: ApportionmentClient,
    carrier_id: str,
    registration_year: int = REGISTRATION_YEAR,
    distance_basis: str = "ACTUAL_DISTANCE_BASIS",
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        client.create_registration_application(
            registration_application_payload(
                carrier_id,
                registration_year=registration_year,
                distance_basis=distance_basis,
                **overrides,
            ),
            headers or PREPARER_1_HEADERS,
        )
    )


def read_application(client: ApportionmentClient, application_id: str) -> Dict[str, Any]:
    return get_success_data(
        client.get_registration_application(application_id, OFFICER_1_HEADERS)
    )


def application_version(client: ApportionmentClient, application_id: str) -> int:
    return read_application(client, application_id)["version"]


def add_schedule_lines(
    client: ApportionmentClient,
    application_id: str,
    schedule: List[tuple],
    headers: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """``schedule`` is a list of ``(jurisdiction_code, reported_distance_miles)``."""
    created = []
    for code, miles in schedule:
        created.append(
            get_success_data(
                client.add_distance_schedule_line(
                    application_id,
                    distance_schedule_line_payload(code, miles),
                    headers or PREPARER_1_HEADERS,
                )
            )
        )
    return created


def schedule_lines(
    client: ApportionmentClient, application_id: str, line_status: Optional[str] = None
) -> List[Dict[str, Any]]:
    params = {"line_status": line_status} if line_status else None
    response = client.list_distance_schedule_lines(
        application_id, OFFICER_1_HEADERS, params=params
    )
    return response.json()["data"]


def submit_application(
    client: ApportionmentClient, application_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        client.submit_registration_application(
            application_id, headers or PREPARER_1_HEADERS
        )
    )


def review_application(
    client: ApportionmentClient,
    application_id: str,
    decision: str,
    headers: Optional[Dict[str, str]] = None,
    review_note: Any = ...,
) -> Dict[str, Any]:
    return get_success_data(
        client.review_registration_application(
            application_id,
            headers or OFFICER_1_HEADERS,
            decision=decision,
            review_note=review_note,
        )
    )


def invoice_application(
    client: ApportionmentClient, application_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return review_application(client, application_id, "INVOICE", headers)


def issue_credentials(
    client: ApportionmentClient,
    application_id: str,
    headers: Optional[Dict[str, str]] = None,
    valid_from_date: Any = ...,
    valid_to_date: Any = ...,
) -> Dict[str, Any]:
    return get_success_data(
        client.issue_credentials(
            application_id,
            headers or OFFICER_1_HEADERS,
            valid_from_date=valid_from_date,
            valid_to_date=valid_to_date,
        )
    )


def list_credentials(
    client: ApportionmentClient, **params: Any
) -> List[Dict[str, Any]]:
    response = client.list_credentials(OFFICER_1_HEADERS, params=params or None)
    return response.json()["data"]


def credentials_for_vehicle(
    client: ApportionmentClient, vehicle_id: str
) -> Dict[str, Dict[str, Any]]:
    """The vehicle's credentials keyed by ``credential_type``."""
    rows = list_credentials(client, vehicle_id=vehicle_id)
    return {row["credential_type"]: row for row in rows}


def read_credential(client: ApportionmentClient, credential_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_credential(credential_id, OFFICER_1_HEADERS))


def distribute_credential(
    client: ApportionmentClient,
    credential_id: str,
    driver_id: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        client.distribute_credential(
            credential_id,
            headers or OFFICER_1_HEADERS,
            distributed_to_driver_id=driver_id,
        )
    )


def request_fleet_change(
    client: ApportionmentClient,
    application_id: str,
    vehicle_id: str,
    change_type: str,
    effective_date: str,
    headers: Optional[Dict[str, str]] = None,
    replaced_vehicle_id: Optional[str] = None,
    expected_version: Optional[int] = None,
) -> Dict[str, Any]:
    version = (
        expected_version
        if expected_version is not None
        else application_version(client, application_id)
    )
    payload = fleet_change_request_payload(
        application_id,
        vehicle_id,
        change_type,
        effective_date,
        version,
        replaced_vehicle_id=replaced_vehicle_id,
    )
    return get_success_data(
        client.create_fleet_change_request(payload, headers or PREPARER_1_HEADERS)
    )


def read_fleet_change(client: ApportionmentClient, change_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_fleet_change_request(change_id, OFFICER_1_HEADERS))


def decide_fleet_change(
    client: ApportionmentClient,
    change_id: str,
    decision: str,
    headers: Optional[Dict[str, str]] = None,
    decision_note: Any = ...,
) -> Dict[str, Any]:
    return get_success_data(
        client.decide_fleet_change_request(
            change_id,
            headers or OFFICER_2_HEADERS,
            decision=decision,
            decision_note=decision_note,
        )
    )


def reverse_fleet_change(
    client: ApportionmentClient,
    change_id: str,
    reversal_reason_code: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        client.reverse_fleet_change_request(
            change_id,
            headers or OFFICER_2_HEADERS,
            reversal_reason_code=reversal_reason_code,
        )
    )


def score_audit_selection(
    client: ApportionmentClient,
    carrier_id: str,
    selection_year: int = REGISTRATION_YEAR,
    selection_quarter: int = 2,
    late_filing_count: int = 0,
    retention_deficiency_count: int = 0,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        client.create_audit_selection(
            audit_selection_payload(
                carrier_id,
                selection_year=selection_year,
                selection_quarter=selection_quarter,
                late_filing_count=late_filing_count,
                retention_deficiency_count=retention_deficiency_count,
            ),
            headers or OFFICER_1_HEADERS,
        )
    )


def retention_review(
    client: ApportionmentClient,
    selection_id: str,
    expected_records_count: int,
    records_missing_count: int,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        client.retention_review_audit_selection(
            selection_id,
            headers or OFFICER_2_HEADERS,
            expected_records_count=expected_records_count,
            records_missing_count=records_missing_count,
        )
    )


# ==========================================================================
# Tier 2 — entity hierarchy
# ==========================================================================

def carrier_ready(client: ApportionmentClient, **carrier_overrides: Any) -> Dict[str, Any]:
    """Clock, reference tables and one registered carrier, together with the
    headers that carrier's own back office would use."""
    reference = seed_reference_data(client)
    carrier = create_carrier(client, **carrier_overrides)
    return {
        "jurisdictions": reference["jurisdictions"],
        "weight_group_fees": reference["weight_group_fees"],
        "carrier": carrier,
        "carrier_id": carrier["id"],
        "admin_headers": make_carrier_admin_headers(carrier["id"]),
    }


def carrier_with_vehicle(
    client: ApportionmentClient,
    unit_number: str = "U-101",
    vin: str = "1FUJGLDR0LSAA0101",
    factory_price_amount: float = 160000.00,
    registration_year: int = REGISTRATION_YEAR,
    carrier_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A carrier with exactly one power unit, which starts ``PENDING``."""
    ctx = carrier_ready(client, **(carrier_overrides or {}))
    vehicle = create_vehicle(
        client,
        ctx["carrier_id"],
        unit_number=unit_number,
        vin=vin,
        factory_price_amount=factory_price_amount,
        registration_year=registration_year,
    )
    ctx["vehicle"] = vehicle
    ctx["vehicle_id"] = vehicle["id"]
    return ctx


def carrier_with_fleet(
    client: ApportionmentClient,
    unit_numbers: List[str],
    factory_price_amount: float = 160000.00,
    registration_year: int = REGISTRATION_YEAR,
    carrier_overrides: Optional[Dict[str, Any]] = None,
    driver_names: Optional[List[tuple]] = None,
) -> Dict[str, Any]:
    """A carrier with several power units and, optionally, enrolled drivers.

    ``driver_names`` is a list of ``(full_name, cdl_number)`` pairs.
    """
    ctx = carrier_ready(client, **(carrier_overrides or {}))
    vehicles = []
    for index, unit_number in enumerate(unit_numbers, start=1):
        vehicles.append(
            create_vehicle(
                client,
                ctx["carrier_id"],
                unit_number=unit_number,
                vin=f"1FUJGLDR0LSAA{index:04d}",
                factory_price_amount=factory_price_amount,
                registration_year=registration_year,
            )
        )
    ctx["vehicles"] = vehicles
    drivers = []
    for full_name, cdl_number in driver_names or []:
        drivers.append(
            create_driver(
                client, ctx["carrier_id"], full_name=full_name, cdl_number=cdl_number
            )
        )
    ctx["drivers"] = drivers
    return ctx


# ==========================================================================
# Tier 3 — full lifecycle shortcuts
# ==========================================================================

def accepted_trip(
    client: ApportionmentClient,
    carrier_id: str,
    vehicle_id: str,
    trip_start_utc: str,
    trip_end_utc: str,
    start_odometer: float,
    end_odometer: float,
    legs: List[Dict[str, Any]],
    capture_headers: Optional[Dict[str, str]] = None,
    review_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Capture a clean trip and walk it straight to ``ACCEPTED``."""
    trip = capture_trip(
        client,
        carrier_id,
        vehicle_id,
        trip_start_utc,
        trip_end_utc,
        start_odometer,
        end_odometer,
        legs,
        headers=capture_headers,
    )
    return accept_trip(client, trip["id"], headers=review_headers)


def reconstructed_then_accepted_trip(
    client: ApportionmentClient,
    carrier_id: str,
    vehicle_id: str,
    trip_start_utc: str,
    trip_end_utc: str,
    start_odometer: float,
    end_odometer: float,
    legs: List[Dict[str, Any]],
    reconstructed_legs: List[Dict[str, Any]],
    supporting_document_reference: str,
    analyst_headers: Optional[Dict[str, str]] = None,
    review_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Capture a gapped trip, reconstruct it from a cited document, and accept
    the reconstruction with a different user than the one who reconstructed it."""
    trip = capture_trip(
        client,
        carrier_id,
        vehicle_id,
        trip_start_utc,
        trip_end_utc,
        start_odometer,
        end_odometer,
        legs,
    )
    reconstruct_trip(
        client,
        trip["id"],
        reconstructed_legs,
        supporting_document_reference,
        headers=analyst_headers,
    )
    return accept_trip(client, trip["id"], headers=review_headers)


def prepared_quarter(
    client: ApportionmentClient,
    carrier_id: str,
    filing_year: int = REGISTRATION_YEAR,
    filing_quarter: int = 2,
    preparer_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Open a quarter and compute it on the preparer basis."""
    opened = open_return(
        client, carrier_id, filing_year, filing_quarter, headers=preparer_headers
    )
    return prepare_return(client, opened["id"], carrier_id, headers=preparer_headers)


def filed_quarter(
    client: ApportionmentClient,
    carrier_id: str,
    filing_year: int = REGISTRATION_YEAR,
    filing_quarter: int = 2,
    preparer_headers: Optional[Dict[str, str]] = None,
    officer_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Open, prepare and file a quarter, using different users for the prepare
    and the file so that segregation of duties is satisfied."""
    prepared = prepared_quarter(
        client, carrier_id, filing_year, filing_quarter, preparer_headers
    )
    return file_return(client, prepared["id"], headers=officer_headers)


def invoiced_application(
    client: ApportionmentClient,
    carrier_id: str,
    schedule: List[tuple],
    registration_year: int = REGISTRATION_YEAR,
    distance_basis: str = "ACTUAL_DISTANCE_BASIS",
    preparer_headers: Optional[Dict[str, str]] = None,
    officer_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Open an application, schedule its distances, submit it and invoice it.
    Invoicing is what freezes the apportionment percentages and activates the
    registration year's pending units."""
    application = open_application(
        client,
        carrier_id,
        registration_year=registration_year,
        distance_basis=distance_basis,
        headers=preparer_headers,
    )
    add_schedule_lines(client, application["id"], schedule, headers=preparer_headers)
    submit_application(client, application["id"], headers=preparer_headers)
    return invoice_application(client, application["id"], headers=officer_headers)


def issued_application(
    client: ApportionmentClient,
    carrier_id: str,
    schedule: List[tuple],
    registration_year: int = REGISTRATION_YEAR,
    distance_basis: str = "ACTUAL_DISTANCE_BASIS",
    preparer_headers: Optional[Dict[str, str]] = None,
    officer_headers: Optional[Dict[str, str]] = None,
    valid_from_date: Any = ...,
    valid_to_date: Any = ...,
) -> Dict[str, Any]:
    """Walk an application all the way to ``ISSUED``, minting the three
    credential types for every active unit of the registration year."""
    invoiced = invoiced_application(
        client,
        carrier_id,
        schedule,
        registration_year=registration_year,
        distance_basis=distance_basis,
        preparer_headers=preparer_headers,
        officer_headers=officer_headers,
    )
    return issue_credentials(
        client,
        invoiced["id"],
        headers=officer_headers,
        valid_from_date=valid_from_date,
        valid_to_date=valid_to_date,
    )


CANONICAL_SCHEDULE_100K = [("IL", 60000.0), ("IN", 25000.0), ("KY", 15000.0)]
CANONICAL_SCHEDULE_IL_IN = [("IL", 80000.0), ("IN", 20000.0)]


# ==========================================================================
# Tier 4 — accumulation and threshold targeting
# ==========================================================================

def gapped_trip_after_predecessor(
    client: ApportionmentClient,
    carrier_id: str,
    vehicle_id: str,
    predecessor: Dict[str, Any],
    gap_miles: float,
    trip_start_utc: str,
    trip_end_utc: str,
    distance: float,
    legs: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Capture a trip that begins ``gap_miles`` past where its chronological
    predecessor ended, so that the server computes exactly that gap."""
    start_odometer = predecessor["end_odometer"] + gap_miles
    return capture_trip(
        client,
        carrier_id,
        vehicle_id,
        trip_start_utc,
        trip_end_utc,
        start_odometer,
        start_odometer + distance,
        legs,
    )


def carrier_at_unsubstantiated_ratio(
    client: ApportionmentClient,
    substantiated_miles: float,
    unsubstantiated_miles: float,
    carrier_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Position a carrier at a chosen ``unsubstantiated_mileage_ratio`` by
    accepting one clean trip and leaving a second one gap-flagged.

    The first trip's miles are substantiated; the second trip's odometer delta
    is not, because nobody reconstructed it.
    """
    ctx = carrier_with_vehicle(client, carrier_overrides=carrier_overrides)
    first = capture_trip(
        client,
        ctx["carrier_id"],
        ctx["vehicle_id"],
        "2026-04-10T06:00:00Z",
        "2026-04-10T18:00:00Z",
        100000.0,
        100000.0 + substantiated_miles,
        [leg("IL", substantiated_miles)],
    )
    ctx["accepted_trip"] = accept_trip(client, first["id"])
    gapped = gapped_trip_after_predecessor(
        client,
        ctx["carrier_id"],
        ctx["vehicle_id"],
        ctx["accepted_trip"],
        60.0,
        "2026-05-20T06:00:00Z",
        "2026-05-20T18:00:00Z",
        unsubstantiated_miles - 60.0,
        [leg("IL", unsubstantiated_miles - 60.0)],
    )
    ctx["gap_flagged_trip"] = gapped
    ctx["carrier"] = read_carrier(client, ctx["carrier_id"])
    return ctx


def selected_audit(
    client: ApportionmentClient,
    carrier_id: str,
    selection_year: int = REGISTRATION_YEAR,
    selection_quarter: int = 2,
    late_filing_count: int = 0,
    retention_deficiency_count: int = 4,
) -> Dict[str, Any]:
    """Score a carrier for one filing period. With four retention deficiencies
    the retention component is fully saturated."""
    return score_audit_selection(
        client,
        carrier_id,
        selection_year=selection_year,
        selection_quarter=selection_quarter,
        late_filing_count=late_filing_count,
        retention_deficiency_count=retention_deficiency_count,
    )


# ==========================================================================
# Tier 5 — finalization and terminal states
# ==========================================================================

def reviewed_audit(
    client: ApportionmentClient,
    selection_id: str,
    expected_records_count: int,
    records_missing_count: int,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Complete the retention review, which re-settles the filed quarter on the
    audit basis and re-scores the risk."""
    return retention_review(
        client,
        selection_id,
        expected_records_count,
        records_missing_count,
        headers=headers,
    )


def disallowed_purchase(
    client: ApportionmentClient,
    purchase_id: str,
    disallow_reason_code: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        client.disallow_fuel_purchase(
            purchase_id,
            headers or ANALYST_1_HEADERS,
            disallow_reason_code=disallow_reason_code,
        )
    )


def rejected_trip_record(
    client: ApportionmentClient,
    carrier_id: str,
    vehicle_id: str,
    trip_start_utc: str,
    trip_end_utc: str,
    start_odometer: float,
    end_odometer: float,
    legs: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """A captured trip rejected outright: the terminal ``REJECTED`` status."""
    trip = capture_trip(
        client,
        carrier_id,
        vehicle_id,
        trip_start_utc,
        trip_end_utc,
        start_odometer,
        end_odometer,
        legs,
    )
    return reject_trip(client, trip["id"])
