"""Payload factories — one per write surface, input fields only."""
from .constants import TEST_DEFAULTS


def _merge(defaults: dict, overrides: dict) -> dict:
    """Apply overrides; an override value of OMIT drops the key entirely so
    tests can exercise omitted optional fields, while None is sent as a literal
    JSON null."""
    merged = dict(defaults)
    for key, value in overrides.items():
        if value is _OMIT:
            merged.pop(key, None)
        else:
            merged[key] = value
    return merged


class _Omit:
    """Sentinel: drop this key from the payload."""

    def __repr__(self):  # pragma: no cover - debug aid
        return "OMIT"


_OMIT = _Omit()
OMIT = _OMIT


# --------------------------------------------------------------------- clock

def set_clock_payload(to_iso8601: str, **overrides) -> dict:
    return _merge({"to_iso8601": to_iso8601}, overrides)


# ---------------------------------------------------------------- facilities

def create_facility_payload(**overrides) -> dict:
    return _merge(
        {
            "name": TEST_DEFAULTS["FACILITY_NAME"],
            "state_code": TEST_DEFAULTS["STATE_CODE"],
            "mech_capacity_kg_per_day": TEST_DEFAULTS["MECH_CAPACITY_KG_PER_DAY"],
            "hydro_capacity_kg_per_day": TEST_DEFAULTS["HYDRO_CAPACITY_KG_PER_DAY"],
        },
        overrides,
    )


# ----------------------------------------------------------------- suppliers

def create_supplier_payload(**overrides) -> dict:
    return _merge(
        {
            "legal_name": TEST_DEFAULTS["SUPPLIER_LEGAL_NAME"],
            "channel": TEST_DEFAULTS["SUPPLIER_CHANNEL"],
            "credit_limit_cents": TEST_DEFAULTS["CREDIT_LIMIT_CENTS"],
        },
        overrides,
    )


def create_quality_strike_payload(incident_code: str = "MOISTURE_EXCESS", **overrides) -> dict:
    return _merge({"incident_code": incident_code}, overrides)


# -------------------------------------------------------- metal index prices

def create_metal_index_price_payload(
    metal: str = "NI",
    price_cents_per_kg: int = 1600,
    effective_date: str = "2026-07-01T00:00:00.000Z",
    **overrides,
) -> dict:
    return _merge(
        {
            "metal": metal,
            "effective_date": effective_date,
            "price_cents_per_kg": price_cents_per_kg,
        },
        overrides,
    )


# ------------------------------------------------------------------- intakes

def create_intake_payload(supplier_id: str, facility_id: str, **overrides) -> dict:
    return _merge(
        {
            "supplier_id": supplier_id,
            "facility_id": facility_id,
            "declared_chemistry": TEST_DEFAULTS["DECLARED_CHEMISTRY"],
            "gross_mass_kg": TEST_DEFAULTS["GROSS_MASS_KG"],
            "packaging_tare_kg": TEST_DEFAULTS["PACKAGING_TARE_KG"],
            "declared_ni_pct": TEST_DEFAULTS["DECLARED_NI_PCT"],
        },
        overrides,
    )


def identify_chemistry_payload(identified_chemistry: str = None, **overrides) -> dict:
    return _merge(
        {
            "identified_chemistry": identified_chemistry
            or TEST_DEFAULTS["IDENTIFIED_CHEMISTRY"]
        },
        overrides,
    )


def discharge_payload(soc_pct: float = None, **overrides) -> dict:
    return _merge(
        {"soc_pct": TEST_DEFAULTS["SOC_PCT"] if soc_pct is None else soc_pct}, overrides
    )


def package_payload(packaging_type: str = None, **overrides) -> dict:
    return _merge(
        {"packaging_type": packaging_type or TEST_DEFAULTS["PACKAGING_TYPE"]}, overrides
    )


# ----------------------------------------------------------------- manifests

def submit_manifest_payload(**overrides) -> dict:
    return _merge(
        {
            "un_number": TEST_DEFAULTS["UN_NUMBER"],
            "packing_group": TEST_DEFAULTS["PACKING_GROUP"],
            "transporter_name": TEST_DEFAULTS["TRANSPORTER_NAME"],
        },
        overrides,
    )


def reject_manifest_payload(rejection_reason: str, **overrides) -> dict:
    return _merge({"rejection_reason": rejection_reason}, overrides)


# ------------------------------------------------------------------- modules

def create_module_payload(serial_code: str, expected_intake_version: int, **overrides) -> dict:
    return _merge(
        {
            "serial_code": serial_code,
            "mass_kg": TEST_DEFAULTS["MODULE_MASS_KG"],
            "min_cell_capacity_pct": TEST_DEFAULTS["MODULE_MIN_CELL_CAPACITY_PCT"],
            "mean_cell_capacity_pct": TEST_DEFAULTS["MODULE_MEAN_CELL_CAPACITY_PCT"],
            "cycle_count": TEST_DEFAULTS["MODULE_CYCLE_COUNT"],
            "expected_intake_version": expected_intake_version,
        },
        overrides,
    )


def create_triage_decision_payload(
    scoring_variant: str = "CONSERVATIVE", override_disposition=None, **overrides
) -> dict:
    payload = {"scoring_variant": scoring_variant}
    if override_disposition is not None:
        payload["override_disposition"] = override_disposition
    return _merge(payload, overrides)


def ship_module_payload(customer_name: str = "Sierra Storage Systems", **overrides) -> dict:
    return _merge({"customer_name": customer_name}, overrides)


# ----------------------------------------------------------- processing lines

def create_processing_line_payload(facility_id: str, **overrides) -> dict:
    return _merge(
        {
            "facility_id": facility_id,
            "line_code": TEST_DEFAULTS["LINE_CODE"],
            "line_type": TEST_DEFAULTS["LINE_TYPE"],
            "chemistry_family": TEST_DEFAULTS["CHEMISTRY_FAMILY"],
            "throughput_kg_per_hour": TEST_DEFAULTS["THROUGHPUT_KG_PER_HOUR"],
        },
        overrides,
    )


def replumb_payload(chemistry_family: str, **overrides) -> dict:
    return _merge({"chemistry_family": chemistry_family}, overrides)


# ----------------------------------------------------------------- campaigns

def create_campaign_payload(line_id: str, **overrides) -> dict:
    return _merge(
        {
            "line_id": line_id,
            "chemistry_family": TEST_DEFAULTS["CHEMISTRY_FAMILY"],
            "window_start": TEST_DEFAULTS["CAMPAIGN_WINDOW_START"],
            "window_end": TEST_DEFAULTS["CAMPAIGN_WINDOW_END"],
            "planned_input_kg": TEST_DEFAULTS["PLANNED_INPUT_KG"],
        },
        overrides,
    )


def cancel_campaign_payload(cancel_reason: str, **overrides) -> dict:
    return _merge({"cancel_reason": cancel_reason}, overrides)


def create_lot_payload(lot_code: str = None, **overrides) -> dict:
    return _merge({"lot_code": lot_code or TEST_DEFAULTS["LOT_CODE"]}, overrides)


# ---------------------------------------------------------------------- lots

def charge_lot_payload(module_ids, expected_lot_version: int, **overrides) -> dict:
    return _merge(
        {"module_ids": list(module_ids), "expected_lot_version": expected_lot_version},
        overrides,
    )


def create_recovery_output_payload(
    metal: str, recovered_mass_kg: float, assay_purity_pct: float, **overrides
) -> dict:
    return _merge(
        {
            "metal": metal,
            "recovered_mass_kg": recovered_mass_kg,
            "assay_purity_pct": assay_purity_pct,
        },
        overrides,
    )


def finalize_lot_payload(residue_mass_kg: float, **overrides) -> dict:
    return _merge({"residue_mass_kg": residue_mass_kg}, overrides)


def void_lot_payload(void_reason: str, **overrides) -> dict:
    return _merge({"void_reason": void_reason}, overrides)


# ---------------------------------------------------------- permits/discharge

def create_permit_allotment_payload(facility_id: str, **overrides) -> dict:
    return _merge(
        {
            "facility_id": facility_id,
            "medium": TEST_DEFAULTS["PERMIT_MEDIUM"],
            "permit_no": TEST_DEFAULTS["PERMIT_NO"],
            "valid_from": TEST_DEFAULTS["PERMIT_VALID_FROM"],
            "valid_to": TEST_DEFAULTS["PERMIT_VALID_TO"],
            "daily_cap_kg": TEST_DEFAULTS["DAILY_CAP_KG"],
        },
        overrides,
    )


def suspend_permit_payload(suspend_reason: str, **overrides) -> dict:
    return _merge({"suspend_reason": suspend_reason}, overrides)


def create_discharge_event_payload(
    allotment_id: str, event_date: str, mass_kg: float, **overrides
) -> dict:
    return _merge(
        {
            "allotment_id": allotment_id,
            "event_date": event_date,
            "mass_kg": mass_kg,
            "analyte": TEST_DEFAULTS["ANALYTE"],
        },
        overrides,
    )


def void_discharge_event_payload(void_reason: str, **overrides) -> dict:
    return _merge({"void_reason": void_reason}, overrides)


# ----------------------------------------------------------------- passports

def issue_passport_payload(
    passport_code: str = "BP-0001", customer_name: str = "Cathode Works", **overrides
) -> dict:
    return _merge(
        {"passport_code": passport_code, "customer_name": customer_name}, overrides
    )


def revoke_passport_payload(revoked_reason: str, **overrides) -> dict:
    return _merge({"revoked_reason": revoked_reason}, overrides)


# --------------------------------------------------------------- settlements

def dispute_settlement_payload(dispute_reason: str, **overrides) -> dict:
    return _merge({"dispute_reason": dispute_reason}, overrides)


def umpire_assay_payload(metal: str, umpire_contained_kg: float, **overrides) -> dict:
    return _merge({"metal": metal, "umpire_contained_kg": umpire_contained_kg}, overrides)


def settle_settlement_payload(payment_reference: str, **overrides) -> dict:
    return _merge({"payment_reference": payment_reference}, overrides)


def void_settlement_payload(void_reason: str, **overrides) -> dict:
    return _merge({"void_reason": void_reason}, overrides)
