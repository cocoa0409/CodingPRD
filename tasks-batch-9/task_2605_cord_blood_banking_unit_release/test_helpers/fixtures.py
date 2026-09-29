"""Scenario builders.

Every test starts against an empty database, so every precondition here is
built from scratch through the API. The atomic helpers each perform one
declared operation; :func:`build_bank_scenario` chains them and stops at a
named stage so a test can pick up exactly the state it needs.

All builders use ``get_success_data`` so that a broken setup step fails loudly
and distinguishably from the behaviour under test.
"""

from typing import Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_collection_kit_payload,
    create_collection_payload,
    create_consent_payload,
    create_enrollment_payload,
    create_maternal_screening_payload,
    create_processing_run_payload,
    create_quality_test_payload,
    create_registry_listing_payload,
    create_reservation_payload,
    create_run_completion_payload,
    create_storage_account_payload,
    create_storage_invoice_payload,
    create_storage_tank_payload,
)
from .test_users import (
    make_billing_admin_headers,
    make_collection_site_headers,
    make_facilities_engineer_headers,
    make_medical_director_headers,
    make_parent_guardian_headers,
    make_platform_admin_headers,
    make_registry_operator_headers,
    make_technologist_headers,
    make_transplant_center_headers,
)

# The stages a scenario may stop at, in the order the pipeline visits them.
SCENARIO_STAGES = (
    "enrollment",
    "consented",
    "account",
    "kit",
    "screened",
    "collected",
    "received",
    "reduced",
    "tested",
    "determined",
    "cryopreserved",
    "listed",
)


# --- Atomic operations -----------------------------------------------------


def set_clock(current_utc: str) -> dict:
    """Move the logical clock to an explicit instant."""
    return get_success_data(api_client.set_clock(current_utc, make_platform_admin_headers()))


def commission_tank(
    tank_code: str = "TANK-A",
    tank_class: str = "STANDARD",
    capacity_slots: int = 5,
    maintenance_window_start: Optional[str] = None,
    maintenance_window_end: Optional[str] = None,
    **overrides,
) -> dict:
    payload = create_storage_tank_payload(
        tank_code=tank_code, tank_class=tank_class, capacity_slots=capacity_slots, **overrides
    )
    if maintenance_window_start is not None:
        payload["maintenance_window_start"] = maintenance_window_start
    if maintenance_window_end is not None:
        payload["maintenance_window_end"] = maintenance_window_end
    return get_success_data(
        api_client.create_storage_tank(payload, make_facilities_engineer_headers())
    )


def register_enrollment(**overrides) -> dict:
    return get_success_data(
        api_client.create_enrollment(
            create_enrollment_payload(**overrides), _intake_headers()
        )
    )


def _intake_headers():
    from .test_users import make_intake_coordinator_headers

    return make_intake_coordinator_headers()


def sign_consent(enrollment_id: str, consent_document_hash: str = "hash-aaa-v1") -> dict:
    """A family signs its own consent, acting as the guardian of that enrollment."""
    return get_success_data(
        api_client.sign_consent(
            enrollment_id,
            create_consent_payload(consent_document_hash=consent_document_hash),
            make_parent_guardian_headers(enrollment_id),
        )
    )


def open_consent_amendment(enrollment_id: str, **overrides) -> dict:
    from .factories import create_consent_amendment_payload

    return get_success_data(
        api_client.open_consent_amendment(
            enrollment_id,
            create_consent_amendment_payload(**overrides),
            make_parent_guardian_headers(enrollment_id),
        )
    )


def open_storage_account(enrollment_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_storage_account(
            create_storage_account_payload(enrollment_id, **overrides),
            make_billing_admin_headers(),
        )
    )


def dispatch_kit(enrollment_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_collection_kit(
            create_collection_kit_payload(enrollment_id, **overrides), _intake_headers()
        )
    )


def file_screening(enrollment_id: str, director_user_id: str = "md-001", **overrides) -> dict:
    return get_success_data(
        api_client.create_maternal_screening(
            create_maternal_screening_payload(enrollment_id, **overrides),
            make_medical_director_headers(director_user_id),
        )
    )


def record_collection(kit_id: str, site_user_id: str = "cs-001", **overrides) -> dict:
    return get_success_data(
        api_client.create_collection(
            create_collection_payload(kit_id, **overrides),
            make_collection_site_headers(site_user_id),
        )
    )


def receive_collection(
    collection_id: str, transport_temp_c: float = 20.0, technologist_user_id: str = "tech-001"
) -> dict:
    return get_success_data(
        api_client.receive_collection(
            collection_id,
            {"transport_temp_c": transport_temp_c},
            make_technologist_headers(technologist_user_id),
        )
    )


def discover_unit(collection_id: str, technologist_user_id: str = "tech-001") -> dict:
    """The only way to find a minted unit is to list the units of its collection."""
    data = get_success_data(
        api_client.list_collection_units(
            collection_id, make_technologist_headers(technologist_user_id)
        )
    )
    rows = data if isinstance(data, list) else data.get("data", [])
    assert rows, f"collection {collection_id} minted no unit"
    return rows[0]


def start_processing_run(unit_id: str, technologist_user_id: str = "tech-001", **overrides) -> dict:
    return get_success_data(
        api_client.create_processing_run(
            create_processing_run_payload(unit_id, **overrides),
            make_technologist_headers(technologist_user_id),
        )
    )


def complete_processing_run(
    run_id: str, technologist_user_id: str = "tech-001", **overrides
) -> dict:
    return get_success_data(
        api_client.complete_processing_run(
            run_id,
            create_run_completion_payload(**overrides),
            make_technologist_headers(technologist_user_id),
        )
    )


def run_processing(
    unit_id: str,
    method: str = "HES_SEDIMENTATION",
    pre_tnc_millions: int = 1100,
    post_volume_ml: float = 25.0,
    post_tnc_millions: int = 1000,
    outcome: str = "COMPLETED",
    technologist_user_id: str = "tech-001",
) -> dict:
    """Open a volume-reduction run and close it in one step."""
    run = start_processing_run(
        unit_id,
        technologist_user_id=technologist_user_id,
        method=method,
        pre_tnc_millions=pre_tnc_millions,
    )
    return complete_processing_run(
        run["id"],
        technologist_user_id=technologist_user_id,
        outcome=outcome,
        post_volume_ml=post_volume_ml,
        post_tnc_millions=post_tnc_millions,
    )


def record_quality_test(unit_id: str, technologist_user_id: str = "tech-001", **overrides) -> dict:
    return get_success_data(
        api_client.create_quality_test(
            create_quality_test_payload(unit_id, **overrides),
            make_technologist_headers(technologist_user_id),
        )
    )


def record_confirmatory_test(
    unit_id: str,
    reservation_id: str,
    tnc_millions: int,
    cd34_thousands: int,
    viability_pct: float,
    volume_ml: float,
    sterility_result: str = "NEGATIVE",
    technologist_user_id: str = "tech-002",
) -> dict:
    return record_quality_test(
        unit_id,
        technologist_user_id=technologist_user_id,
        test_kind="CONFIRMATORY",
        tnc_millions=tnc_millions,
        cd34_thousands=cd34_thousands,
        viability_pct=viability_pct,
        volume_ml=volume_ml,
        sterility_result=sterility_result,
        reservation_id=reservation_id,
    )


def determine_eligibility(unit_id: str, director_user_id: str = "md-001", **overrides) -> dict:
    from .factories import create_eligibility_determination_payload

    return get_success_data(
        api_client.determine_eligibility(
            unit_id,
            create_eligibility_determination_payload(**overrides),
            make_medical_director_headers(director_user_id),
        )
    )


def cryopreserve(
    unit_id: str,
    tank_id: str,
    slot_code: str = "A-01",
    freeze_at: str = TEST_DEFAULTS["FREEZE_AT"],
    technologist_user_id: str = "tech-001",
) -> dict:
    return get_success_data(
        api_client.cryopreserve_unit(
            unit_id,
            {"tank_id": tank_id, "slot_code": slot_code, "freeze_at": freeze_at},
            make_technologist_headers(technologist_user_id),
        )
    )


def unit_version(unit_id: str, headers: Optional[dict] = None) -> int:
    """Read the unit's current version, as a client must before a guarded write."""
    data = get_success_data(
        api_client.get_unit(unit_id, headers or make_registry_operator_headers())
    )
    return data["version"]


def read_unit(unit_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_unit(unit_id, headers or make_technologist_headers()))


def publish_listing(unit_id: str, operator_user_id: str = "ro-001", **overrides) -> dict:
    headers = make_registry_operator_headers(operator_user_id)
    expected = overrides.pop("expected_unit_version", None)
    if expected is None:
        expected = unit_version(unit_id, headers)
    return get_success_data(
        api_client.create_registry_listing(
            create_registry_listing_payload(unit_id, expected, **overrides), headers
        )
    )


def place_reservation(
    unit_id: str,
    center_user_id: str = "tc-001",
    expected_unit_version: Optional[int] = None,
    **overrides,
) -> dict:
    headers = make_transplant_center_headers(center_user_id)
    expected = (
        expected_unit_version
        if expected_unit_version is not None
        else unit_version(unit_id, headers)
    )
    return get_success_data(
        api_client.create_reservation(
            create_reservation_payload(unit_id, expected, **overrides), headers
        )
    )


def confirm_reservation(
    reservation_id: str,
    intended_transplant_date: str = "2026-09-03",
    center_user_id: str = "tc-001",
) -> dict:
    return get_success_data(
        api_client.confirm_reservation(
            reservation_id,
            {"intended_transplant_date": intended_transplant_date},
            make_transplant_center_headers(center_user_id),
        )
    )


def decline_reservation(
    reservation_id: str, reason_code: str = "ALTERNATIVE_UNIT_SELECTED", center_user_id: str = "tc-001"
) -> dict:
    return get_success_data(
        api_client.decline_reservation(
            reservation_id,
            {"reason_code": reason_code},
            make_transplant_center_headers(center_user_id),
        )
    )


def cancel_reservation(
    reservation_id: str, reason_code: str = "PATIENT_DECEASED", center_user_id: str = "tc-001"
) -> dict:
    return get_success_data(
        api_client.cancel_reservation(
            reservation_id,
            {"reason_code": reason_code},
            make_transplant_center_headers(center_user_id),
        )
    )


def release_reservation(
    reservation_id: str, release_note: str = "release authorised", director_user_id: str = "md-002"
) -> dict:
    return get_success_data(
        api_client.release_reservation(
            reservation_id,
            {"release_note": release_note},
            make_medical_director_headers(director_user_id),
        )
    )


def post_temperature_reading(
    tank_id: str, reading_c: float, reading_at: str, engineer_user_id: str = "fe-001"
) -> dict:
    return get_success_data(
        api_client.record_temperature_reading(
            tank_id,
            {"reading_c": reading_c, "reading_at": reading_at},
            make_facilities_engineer_headers(engineer_user_id),
        )
    )


def latest_excursion(tank_id: str, engineer_user_id: str = "fe-001") -> dict:
    data = get_success_data(
        api_client.list_tank_excursions(tank_id, make_facilities_engineer_headers(engineer_user_id))
    )
    rows = data if isinstance(data, list) else data.get("data", [])
    assert rows, f"tank {tank_id} has no excursion"
    return rows[-1]


def acknowledge_excursion(
    excursion_id: str, acknowledged_at: str, engineer_user_id: str = "fe-001"
) -> dict:
    """Acknowledge at ``acknowledged_at``; the instant is stamped from the clock."""
    set_clock(acknowledged_at)
    return get_success_data(
        api_client.acknowledge_excursion(
            excursion_id,
            {"acknowledgement_note": "engineer on site"},
            make_facilities_engineer_headers(engineer_user_id),
        )
    )


def resolve_excursion(
    excursion_id: str,
    disposition: str,
    resolved_at: str,
    peak_temperature_c: float = -140.0,
    engineer_user_id: str = "fe-001",
) -> dict:
    """Resolve at ``resolved_at``; the instant is stamped from the clock."""
    set_clock(resolved_at)
    return get_success_data(
        api_client.resolve_excursion(
            excursion_id,
            {"disposition": disposition, "peak_temperature_c": peak_temperature_c},
            make_facilities_engineer_headers(engineer_user_id),
        )
    )


def issue_invoice(account_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_storage_invoice(
            create_storage_invoice_payload(account_id, **overrides), make_billing_admin_headers()
        )
    )


def pay_invoice(
    invoice_id: str, amount_cents: int, payment_reference: str = "WIRE-2027-0001"
) -> dict:
    return get_success_data(
        api_client.pay_storage_invoice(
            invoice_id,
            {"amount_cents": amount_cents, "payment_reference": payment_reference},
            make_billing_admin_headers(),
        )
    )


def dispose_unit(unit_id: str, reason: str = "QUALITY_FAILURE", director_user_id: str = "md-002", **extra) -> dict:
    payload = {"reason": reason}
    payload.update(extra)
    return get_success_data(
        api_client.dispose_unit(unit_id, payload, make_medical_director_headers(director_user_id))
    )


def nightly_run(admin_user_id: str = "admin-001") -> dict:
    return get_success_data(
        api_client.run_nightly_batch({}, make_platform_admin_headers(admin_user_id))
    )


def read_tank(tank_id: str) -> dict:
    return get_success_data(
        api_client.get_storage_tank(tank_id, make_facilities_engineer_headers())
    )


def read_enrollment(enrollment_id: str) -> dict:
    return get_success_data(api_client.get_enrollment(enrollment_id, _intake_headers()))


def read_account(account_id: str) -> dict:
    return get_success_data(
        api_client.get_storage_account(account_id, make_billing_admin_headers())
    )


def read_invoice(invoice_id: str) -> dict:
    return get_success_data(
        api_client.get_storage_invoice(invoice_id, make_billing_admin_headers())
    )


def read_reservation(reservation_id: str, center_user_id: str = "tc-001") -> dict:
    return get_success_data(
        api_client.get_reservation(reservation_id, make_transplant_center_headers(center_user_id))
    )


def read_listing(listing_id: str) -> dict:
    return get_success_data(
        api_client.get_registry_listing(listing_id, make_registry_operator_headers())
    )


def read_collection(collection_id: str) -> dict:
    return get_success_data(
        api_client.get_collection(collection_id, make_technologist_headers())
    )


def read_kit(kit_id: str) -> dict:
    return get_success_data(api_client.get_collection_kit(kit_id, _intake_headers()))


def read_screening(screening_id: str) -> dict:
    return get_success_data(
        api_client.get_maternal_screening(screening_id, make_medical_director_headers())
    )


# --- Composite scenario builder --------------------------------------------


def build_bank_scenario(
    *,
    stage: str = "cryopreserved",
    # clock
    set_epoch: bool = True,
    epoch: str = TEST_DEFAULTS["CLOCK_EPOCH"],
    collection_clock: Optional[str] = TEST_DEFAULTS["COLLECTION_CLOCK"],
    receipt_clock: Optional[str] = TEST_DEFAULTS["RECEIPT_CLOCK"],
    # tank
    tank: Optional[dict] = None,
    tank_code: Optional[str] = "TANK-A",
    tank_class: str = "STANDARD",
    capacity_slots: int = 5,
    maintenance_window_start: Optional[str] = None,
    maintenance_window_end: Optional[str] = None,
    # enrollment
    program_type: str = "PRIVATE_FAMILY",
    primary_parent_name: str = "Avery Lin",
    expected_delivery_date: str = TEST_DEFAULTS["EXPECTED_DELIVERY_DATE"],
    collection_site_code: str = "SITE-01",
    research_use_authorized: Optional[bool] = None,
    hla_typing_consent: Optional[bool] = None,
    consent_document_hash: str = "hash-aaa-v1",
    # storage account
    plan_term_years: Optional[int] = None,
    prepaid_through_date: str = TEST_DEFAULTS["PREPAID_THROUGH_DATE"],
    billing_contact_email: str = TEST_DEFAULTS["BILLING_CONTACT_EMAIL"],
    # kit
    kit_lot_code: str = "LOT-2026-A",
    courier_tracking_code: str = "TRK-0001",
    # screening
    screening_collected_at: str = TEST_DEFAULTS["COLLECTED_AT"],
    screening_markers: Optional[dict] = None,
    screening_director: str = "md-001",
    # collection
    collected_at: str = TEST_DEFAULTS["COLLECTED_AT"],
    collection_volume_ml: float = TEST_DEFAULTS["COLLECTION_VOLUME_ML"],
    anticoagulant_volume_ml: float = TEST_DEFAULTS["ANTICOAGULANT_VOLUME_ML"],
    delivery_mode: str = "VAGINAL",
    transport_temp_c: float = TEST_DEFAULTS["TRANSPORT_TEMP_C"],
    # processing run
    run_method: Optional[str] = None,
    pre_tnc_millions: Optional[int] = None,
    post_volume_ml: float = 25.0,
    post_tnc_millions: Optional[int] = None,
    # post-processing quality test
    quality_tnc_millions: Optional[int] = None,
    quality_cd34_thousands: Optional[int] = None,
    quality_viability_pct: Optional[float] = None,
    quality_volume_ml: float = 25.0,
    sterility_result: str = "NEGATIVE",
    technologist_user_id: str = "tech-001",
    director_user_id: str = "md-001",
    # cryopreservation
    slot_code: str = "A-01",
    freeze_at: str = TEST_DEFAULTS["FREEZE_AT"],
    # registry listing
    registry_code: str = TEST_DEFAULTS["REGISTRY_CODE"],
    hla_a: str = TEST_DEFAULTS["HLA_A"],
    hla_b: str = TEST_DEFAULTS["HLA_B"],
    hla_drb1: str = TEST_DEFAULTS["HLA_DRB1"],
    registry_operator_user_id: str = "ro-001",
) -> dict:
    """Drive the banking pipeline from an empty database up to ``stage``.

    Returns a dict of every row created, keyed ``tank``, ``enrollment``,
    ``account``, ``kit``, ``screening``, ``collection``, ``unit``, ``run``,
    ``quality_test`` and ``listing``; keys for stages never reached are ``None``.

    Tier defaults follow the two program types: a private-family unit is
    reduced from 1100 to 1000 million cells and characterised at 1000 million
    cells, 2400 thousand CD34+ cells and 88.0 percent viability, while a
    public-donation unit is reduced from 1650 to 1500 and characterised at
    1500 / 3000 / 92.0.
    """
    assert stage in SCENARIO_STAGES, f"unknown stage {stage!r}"
    public = program_type == "PUBLIC_DONATION"
    run_method = run_method or ("AUTOMATED_SEPARATION" if public else "HES_SEDIMENTATION")
    pre_tnc_millions = pre_tnc_millions if pre_tnc_millions is not None else (1650 if public else 1100)
    post_tnc_millions = post_tnc_millions if post_tnc_millions is not None else (1500 if public else 1000)
    quality_tnc_millions = (
        quality_tnc_millions if quality_tnc_millions is not None else post_tnc_millions
    )
    quality_cd34_thousands = (
        quality_cd34_thousands if quality_cd34_thousands is not None else (3000 if public else 2400)
    )
    quality_viability_pct = (
        quality_viability_pct if quality_viability_pct is not None else (92.0 if public else 88.0)
    )

    out = {
        "tank": tank,
        "enrollment": None,
        "account": None,
        "kit": None,
        "screening": None,
        "collection": None,
        "unit": None,
        "run": None,
        "quality_test": None,
        "listing": None,
    }
    reached = SCENARIO_STAGES.index(stage)

    if set_epoch:
        set_clock(epoch)

    if tank is None and tank_code is not None:
        out["tank"] = commission_tank(
            tank_code=tank_code,
            tank_class=tank_class,
            capacity_slots=capacity_slots,
            maintenance_window_start=maintenance_window_start,
            maintenance_window_end=maintenance_window_end,
        )

    enrollment_overrides = {
        "program_type": program_type,
        "primary_parent_name": primary_parent_name,
        "expected_delivery_date": expected_delivery_date,
        "collection_site_code": collection_site_code,
    }
    if research_use_authorized is not None:
        enrollment_overrides["research_use_authorized"] = research_use_authorized
    if hla_typing_consent is not None:
        enrollment_overrides["hla_typing_consent"] = hla_typing_consent
    out["enrollment"] = register_enrollment(**enrollment_overrides)
    enrollment_id = out["enrollment"]["id"]
    if reached == SCENARIO_STAGES.index("enrollment"):
        return out

    sign_consent(enrollment_id, consent_document_hash=consent_document_hash)
    out["enrollment"] = read_enrollment(enrollment_id)
    if reached == SCENARIO_STAGES.index("consented"):
        return out

    if plan_term_years is not None:
        out["account"] = open_storage_account(
            enrollment_id,
            plan_term_years=plan_term_years,
            prepaid_through_date=prepaid_through_date,
            billing_contact_email=billing_contact_email,
        )
    if reached == SCENARIO_STAGES.index("account"):
        return out

    out["kit"] = dispatch_kit(
        enrollment_id, kit_lot_code=kit_lot_code, courier_tracking_code=courier_tracking_code
    )
    if reached == SCENARIO_STAGES.index("kit"):
        return out

    if collection_clock is not None:
        set_clock(collection_clock)
    screening_payload = {"collected_at": screening_collected_at}
    if screening_markers:
        screening_payload.update(screening_markers)
    out["screening"] = file_screening(
        enrollment_id, director_user_id=screening_director, **screening_payload
    )
    if reached == SCENARIO_STAGES.index("screened"):
        return out

    out["collection"] = record_collection(
        out["kit"]["id"],
        collected_at=collected_at,
        collection_volume_ml=collection_volume_ml,
        anticoagulant_volume_ml=anticoagulant_volume_ml,
        delivery_mode=delivery_mode,
    )
    if reached == SCENARIO_STAGES.index("collected"):
        return out

    if receipt_clock is not None:
        set_clock(receipt_clock)
    out["collection"] = receive_collection(
        out["collection"]["id"],
        transport_temp_c=transport_temp_c,
        technologist_user_id=technologist_user_id,
    )
    out["unit"] = discover_unit(
        out["collection"]["id"], technologist_user_id=technologist_user_id
    )
    unit_id = out["unit"]["id"]
    if reached == SCENARIO_STAGES.index("received"):
        return out

    out["run"] = run_processing(
        unit_id,
        method=run_method,
        pre_tnc_millions=pre_tnc_millions,
        post_volume_ml=post_volume_ml,
        post_tnc_millions=post_tnc_millions,
        technologist_user_id=technologist_user_id,
    )
    out["unit"] = read_unit(unit_id)
    if reached == SCENARIO_STAGES.index("reduced"):
        return out

    out["quality_test"] = record_quality_test(
        unit_id,
        technologist_user_id=technologist_user_id,
        test_kind="POST_PROCESSING",
        tnc_millions=quality_tnc_millions,
        cd34_thousands=quality_cd34_thousands,
        viability_pct=quality_viability_pct,
        volume_ml=quality_volume_ml,
        sterility_result=sterility_result,
    )
    out["unit"] = read_unit(unit_id)
    if reached == SCENARIO_STAGES.index("tested"):
        return out

    determine_eligibility(unit_id, director_user_id=director_user_id)
    out["unit"] = read_unit(unit_id)
    if reached == SCENARIO_STAGES.index("determined"):
        return out

    assert out["tank"] is not None, "cryopreservation needs a tank"
    cryopreserve(
        unit_id,
        out["tank"]["id"],
        slot_code=slot_code,
        freeze_at=freeze_at,
        technologist_user_id=technologist_user_id,
    )
    out["unit"] = read_unit(unit_id)
    out["tank"] = read_tank(out["tank"]["id"])
    if reached == SCENARIO_STAGES.index("cryopreserved"):
        return out

    out["listing"] = publish_listing(
        unit_id,
        operator_user_id=registry_operator_user_id,
        registry_code=registry_code,
        hla_a=hla_a,
        hla_b=hla_b,
        hla_drb1=hla_drb1,
    )
    out["unit"] = read_unit(unit_id)
    return out


def build_private_scenario(**kwargs) -> dict:
    """A private-family unit, stored to its family's own account by default."""
    kwargs.setdefault("program_type", "PRIVATE_FAMILY")
    return build_bank_scenario(**kwargs)


def build_public_scenario(**kwargs) -> dict:
    """A public-donation unit, characterised well above the public floors."""
    kwargs.setdefault("program_type", "PUBLIC_DONATION")
    kwargs.setdefault("hla_typing_consent", True)
    return build_bank_scenario(**kwargs)


def build_listed_public_scenario(**kwargs) -> dict:
    """A public-donation unit already published to a registry."""
    kwargs.setdefault("stage", "listed")
    return build_public_scenario(**kwargs)


def build_reserved_scenario(
    *,
    reservation_clock: Optional[str] = "2026-08-11T03:00:00Z",
    requesting_center_name: str = "Center One",
    patient_weight_kg: float = 35.0,
    patient_hla_match_count: int = 6,
    hold_from: str = "2026-09-01T00:00:00Z",
    hold_until: str = "2026-09-05T00:00:00Z",
    center_user_id: str = "tc-001",
    confirm: bool = False,
    intended_transplant_date: str = "2026-09-03",
    **kwargs,
) -> dict:
    """A listed public unit carrying one hold, optionally already confirmed."""
    scenario = build_listed_public_scenario(**kwargs)
    if reservation_clock is not None:
        set_clock(reservation_clock)
    scenario["reservation"] = place_reservation(
        scenario["unit"]["id"],
        center_user_id=center_user_id,
        requesting_center_name=requesting_center_name,
        patient_weight_kg=patient_weight_kg,
        patient_hla_match_count=patient_hla_match_count,
        hold_from=hold_from,
        hold_until=hold_until,
    )
    if confirm:
        scenario["reservation"] = confirm_reservation(
            scenario["reservation"]["id"],
            intended_transplant_date=intended_transplant_date,
            center_user_id=center_user_id,
        )
    scenario["unit"] = read_unit(scenario["unit"]["id"])
    return scenario


def build_billed_private_scenario(
    *,
    plan_term_years: int = 1,
    invoice_clock: str = "2026-09-01T00:00:00Z",
    billing_period_start: str = "2026-09-01",
    billing_period_end: str = "2027-08-31",
    prorated_days: int = 365,
    **kwargs,
) -> dict:
    """A stored private unit whose family account carries one issued invoice."""
    kwargs.setdefault("stage", "cryopreserved")
    kwargs["plan_term_years"] = plan_term_years
    scenario = build_private_scenario(**kwargs)
    set_clock(invoice_clock)
    scenario["invoice"] = issue_invoice(
        scenario["account"]["id"],
        billing_period_start=billing_period_start,
        billing_period_end=billing_period_end,
        prorated_days=prorated_days,
    )
    scenario["account"] = read_account(scenario["account"]["id"])
    return scenario
