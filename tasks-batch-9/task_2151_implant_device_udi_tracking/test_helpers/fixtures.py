"""Composite setup helpers.

The harness relaunches the server before every individual test, so every
fixture below builds its preconditions from scratch using only PRD-declared
endpoints.  All setup calls go through the lenient `get_success_data` validator
so a broken precondition surfaces as a clear "Setup step failed" message.

Version threading: the three optimistic-concurrency guarded writes
(`POST /udi/lots/{lot_id}/device-units`, `POST
/udi/surgical-cases/{case_id}/implant-records` and `POST /udi/vendor-invoices`)
each need the parent's *current* `version`, so the helpers below always re-read
the parent immediately before the write rather than caching a stale number.
"""

from typing import List, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_BASE, TEST_DEFAULTS
from .test_users import (
    CC,
    CC2,
    CO,
    IL,
    RI,
    RT,
    make_vendor_rep_headers,
)

# ─────────────────────────────────────────────────────────────────────────
# Logical clock
# ─────────────────────────────────────────────────────────────────────────

def set_clock(to_iso8601: str, headers: Optional[dict] = None) -> dict:
    """Move the logical clock.  Performs no sweeps."""
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, headers or IL)
    )


# ─────────────────────────────────────────────────────────────────────────
# Tier 1 — single-resource creation and state progression
# ─────────────────────────────────────────────────────────────────────────

def create_vendor(name: str = None, vendor_code: str = None, headers=None) -> dict:
    payload = {
        "name": name or TEST_DEFAULTS["VENDOR_NAME"],
        "vendor_code": vendor_code or TEST_DEFAULTS["VENDOR_CODE"],
    }
    return get_success_data(api_client.create_vendor(payload, headers or IL))


def create_agreement(vendor_id: str, **overrides) -> dict:
    payload = {
        "vendor_id": vendor_id,
        "agreement_code": TEST_DEFAULTS["AGREEMENT_CODE"],
        "billing_trigger": "ON_IMPLANT",
        "reconciliation_method": "UNIT_MATCH",
        "period_start_utc": TEST_DEFAULTS["PERIOD_START_UTC"],
        "period_end_utc": TEST_DEFAULTS["PERIOD_END_UTC"],
        "invoice_tolerance_bps": 150,
    }
    payload.update(overrides)
    return get_success_data(api_client.create_agreement(payload, IL))


def activate_agreement(agreement_id: str) -> dict:
    return get_success_data(api_client.activate_agreement(agreement_id, IL))


def create_active_agreement(vendor_id: str, **overrides) -> dict:
    """Create the agreement in DRAFT and move it to ACTIVE."""
    agreement = create_agreement(vendor_id, **overrides)
    return activate_agreement(agreement["id"])


def record_price_list_revision(agreement_id: str) -> dict:
    return get_success_data(api_client.record_price_list_revision(agreement_id, IL))


def create_catalog_item(vendor_id: str, **overrides) -> dict:
    payload = {
        "vendor_id": vendor_id,
        "device_identifier": TEST_DEFAULTS["DEVICE_IDENTIFIER"],
        "description": TEST_DEFAULTS["DESCRIPTION"],
        "category": "STANDARD_IMPLANT",
        "list_charge_cents": TEST_DEFAULTS["LIST_CHARGE_CENTS"],
        "charge_code": TEST_DEFAULTS["CHARGE_CODE"],
        "shelf_life_days": TEST_DEFAULTS["SHELF_LIFE_DAYS"],
    }
    payload.update(overrides)
    return get_success_data(api_client.create_catalog_item(payload, IL))


def create_lot(catalog_item_id: str, **overrides) -> dict:
    payload = {
        "catalog_item_id": catalog_item_id,
        "lot_number": TEST_DEFAULTS["LOT_NUMBER"],
        "expiration_date": TEST_DEFAULTS["EXPIRATION_DATE"],
    }
    payload.update(overrides)
    return get_success_data(api_client.create_lot(payload, RT))


def lot_version(lot_id: str) -> int:
    return get_success_data(api_client.get_lot(lot_id, RT))["version"]


def add_unit(
    lot_id: str,
    udi_serial: str,
    acquisition_cost_cents: int = None,
    consignment_agreement_id: Optional[str] = None,
    replaced_unit_id: Optional[str] = None,
    **overrides,
) -> dict:
    """Add one serialized unit, re-reading the lot for a fresh
    `expected_lot_version` first."""
    payload = {
        "udi_serial": udi_serial,
        "acquisition_cost_cents": (
            acquisition_cost_cents
            if acquisition_cost_cents is not None
            else TEST_DEFAULTS["ACQUISITION_COST_CENTS"]
        ),
        "expected_lot_version": lot_version(lot_id),
    }
    if consignment_agreement_id is not None:
        payload["consignment_agreement_id"] = consignment_agreement_id
    if replaced_unit_id is not None:
        payload["replaced_unit_id"] = replaced_unit_id
    payload.update(overrides)
    return get_success_data(api_client.add_device_unit(lot_id, payload, RT))


def release_lot(lot_id: str, headers=None) -> dict:
    """Release a quarantined lot.  Defaults to the InventoryLead identity so
    the acting user always differs from the ReceivingTech that received it."""
    return get_success_data(api_client.release_lot(lot_id, headers or IL))


def create_patient(**overrides) -> dict:
    payload = {
        "mrn": TEST_DEFAULTS["MRN"],
        "display_name": TEST_DEFAULTS["PATIENT_NAME"],
        "registry_consent": "GRANTED",
    }
    payload.update(overrides)
    return get_success_data(api_client.create_patient(payload, CC))


def create_case(patient_id: str, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "case_number": TEST_DEFAULTS["CASE_NUMBER"],
        "or_room_code": TEST_DEFAULTS["OR_ROOM_CODE"],
        "scheduled_start_utc": TEST_DEFAULTS["SCHEDULED_START_UTC"],
        "scheduled_end_utc": TEST_DEFAULTS["SCHEDULED_END_UTC"],
        "surgeon_code": TEST_DEFAULTS["SURGEON_CODE"],
    }
    payload.update(overrides)
    return get_success_data(api_client.create_surgical_case(payload, CC))


def start_case(case_id: str) -> dict:
    return get_success_data(api_client.start_case(case_id, CC))


def case_version(case_id: str) -> int:
    return get_success_data(api_client.get_surgical_case(case_id, CC))["version"]


def agreement_version(agreement_id: str) -> int:
    return get_success_data(api_client.get_agreement(agreement_id, IL))["version"]


def reserve_unit(case_id: str, device_unit_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.create_reservation(
            case_id, {"device_unit_id": device_unit_id}, headers or CC
        )
    )


def reserve_by_catalog(case_id: str, catalog_item_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.create_reservation(
            case_id, {"catalog_item_id": catalog_item_id}, headers or CC
        )
    )


def document_implant(case_id: str, unit: dict, **overrides) -> dict:
    """Document an implant, re-reading the case for a fresh
    `expected_case_version` and transcribing the UDI halves off the unit."""
    payload = {
        "device_unit_id": unit["id"],
        "udi_di": unit["udi_di_snapshot"],
        "udi_pi_serial": unit["udi_serial"],
        "anatomic_site": TEST_DEFAULTS["ANATOMIC_SITE"],
        "laterality": "LEFT",
        "expected_case_version": case_version(case_id),
    }
    payload.update(overrides)
    return get_success_data(api_client.create_implant_record(case_id, payload, CC))


def verify_record(implant_record_id: str, headers=None) -> dict:
    """Verify.  Defaults to the second clinician identity so the acting user
    always differs from the one that documented the record."""
    return get_success_data(
        api_client.verify_implant_record(implant_record_id, headers or CC2)
    )


def amend_record(implant_record_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.amend_implant_record(implant_record_id, headers or CC)
    )


# ─── Charges ──────────────────────────────────────────────────────────────

def create_charge(implant_record_id: str, quantity: int = 1) -> dict:
    return get_success_data(
        api_client.create_charge(implant_record_id, {"quantity": quantity}, RI)
    )


def post_charge(charge_id: str) -> dict:
    return get_success_data(api_client.post_charge(charge_id, RI))


def finalize_charge(charge_id: str) -> dict:
    return get_success_data(api_client.finalize_charge(charge_id, RI))


def correct_charge(charge_id: str, acknowledged_variance_cents: int) -> dict:
    return get_success_data(
        api_client.correct_charge(
            charge_id, {"acknowledged_variance_cents": acknowledged_variance_cents}, RI
        )
    )


def void_charge(charge_id: str) -> dict:
    return get_success_data(api_client.void_charge(charge_id, RI))


# ─── Registry ─────────────────────────────────────────────────────────────

def submission_for(implant_record_id: str) -> Optional[dict]:
    """Return the registry submission belonging to a record, or None."""
    body = api_client.list_registry_submissions(
        CO, {"implant_record_id": implant_record_id}
    ).json()
    rows = body.get("data") or []
    return rows[0] if rows else None


def submit_registry(submission_id: str, registry_code: str = "AJRR-0001") -> dict:
    return get_success_data(
        api_client.submit_registry_submission(
            submission_id, {"registry_code": registry_code}, CO
        )
    )


def adjudicate_registry(submission_id: str, outcome: str, rejection_reason=None) -> dict:
    payload = {"outcome": outcome}
    if rejection_reason is not None:
        payload["rejection_reason"] = rejection_reason
    return get_success_data(
        api_client.adjudicate_registry_submission(submission_id, payload, CO)
    )


# ─── Field actions ────────────────────────────────────────────────────────

def create_field_action(vendor_id: str, catalog_item_id: str, **overrides) -> dict:
    payload = {
        "vendor_id": vendor_id,
        "catalog_item_id": catalog_item_id,
        "action_code": "FA-2026-001",
        "action_class": "CLASS_II",
        "scope_type": "CATALOG",
        "effective_from_utc": CLOCK_BASE,
    }
    payload.update(overrides)
    return get_success_data(api_client.create_field_action(payload, CO))


def publish_field_action(field_action_id: str) -> dict:
    return get_success_data(api_client.publish_field_action(field_action_id, CO))


def close_field_action(field_action_id: str, on_hand_disposition: str) -> dict:
    return get_success_data(
        api_client.close_field_action(
            field_action_id, {"on_hand_disposition": on_hand_disposition}, CO
        )
    )


def resolve_notification(notification_id: str, outcome: str, outcome_note=None) -> dict:
    payload = {"outcome": outcome}
    if outcome_note is not None:
        payload["outcome_note"] = outcome_note
    return get_success_data(
        api_client.resolve_recall_notification(notification_id, payload, CO)
    )


def notifications_for(field_action_id: str) -> List[dict]:
    body = api_client.list_recall_notifications(
        CO, {"field_action_id": field_action_id}
    ).json()
    return body.get("data") or []


# ─── Vendor invoices ──────────────────────────────────────────────────────

def submit_invoice(
    vendor_id: str,
    agreement_id: str,
    device_unit_ids: Sequence[str],
    submitted_total_cents: int,
    invoice_number: str = "INV-1",
) -> dict:
    """Submit a consignment invoice, re-reading the agreement for a fresh
    `expected_agreement_version` first, and acting as that vendor's rep."""
    payload = {
        "vendor_id": vendor_id,
        "consignment_agreement_id": agreement_id,
        "invoice_number": invoice_number,
        "submitted_total_cents": submitted_total_cents,
        "device_unit_ids": list(device_unit_ids),
        "expected_agreement_version": agreement_version(agreement_id),
    }
    return get_success_data(
        api_client.create_vendor_invoice(payload, make_vendor_rep_headers(vendor_id))
    )


def match_invoice(invoice_id: str, headers=None) -> dict:
    return get_success_data(api_client.match_invoice(invoice_id, headers or RI))


def approve_invoice(invoice_id: str, override_reason=None, headers=None) -> dict:
    """Approve.  Defaults to the ComplianceOfficer identity so the acting user
    always differs from the analyst that matched the invoice."""
    payload = {}
    if override_reason is not None:
        payload["override_reason"] = override_reason
    return get_success_data(
        api_client.approve_invoice(invoice_id, payload, headers or CO)
    )


def dispute_invoice(invoice_id: str) -> dict:
    return get_success_data(api_client.dispute_invoice(invoice_id, RI))


def resubmit_invoice(
    invoice_id: str, vendor_id: str, submitted_total_cents: int, device_unit_ids
) -> dict:
    payload = {
        "submitted_total_cents": submitted_total_cents,
        "device_unit_ids": list(device_unit_ids),
    }
    return get_success_data(
        api_client.resubmit_invoice(
            invoice_id, payload, make_vendor_rep_headers(vendor_id)
        )
    )


# ─── Explants ─────────────────────────────────────────────────────────────

def record_explant(implant_record_id: str, reason: str = "DEVICE_FAILURE", **overrides) -> dict:
    payload = {"reason": reason}
    payload.update(overrides)
    return get_success_data(api_client.create_explant(implant_record_id, payload, CC))


def disposition_explant(
    explant_record_id: str, disposition: str, return_authorization_no=None
) -> dict:
    payload = {"disposition": disposition}
    if return_authorization_no is not None:
        payload["return_authorization_no"] = return_authorization_no
    return get_success_data(
        api_client.disposition_explant(explant_record_id, payload, IL)
    )


def ship_explant(explant_record_id: str) -> dict:
    return get_success_data(api_client.ship_explant(explant_record_id, IL))


def credit_explant(explant_record_id: str, vendor_id: str, credit_issued_cents: int) -> dict:
    return get_success_data(
        api_client.credit_explant(
            explant_record_id,
            {"credit_issued_cents": credit_issued_cents},
            make_vendor_rep_headers(vendor_id),
        )
    )


def ops_run() -> dict:
    return get_success_data(api_client.create_ops_run(IL))


# ─────────────────────────────────────────────────────────────────────────
# Live re-reads — every assertion reads the resource back from the API
# ─────────────────────────────────────────────────────────────────────────

def get_vendor(vendor_id: str) -> dict:
    return get_success_data(api_client.get_vendor(vendor_id, IL))


def get_agreement(agreement_id: str) -> dict:
    return get_success_data(api_client.get_agreement(agreement_id, IL))


def get_catalog_item(catalog_item_id: str) -> dict:
    return get_success_data(api_client.get_catalog_item(catalog_item_id, IL))


def get_lot(lot_id: str) -> dict:
    return get_success_data(api_client.get_lot(lot_id, IL))


def get_unit(device_unit_id: str) -> dict:
    return get_success_data(api_client.get_device_unit(device_unit_id, IL))


def get_patient(patient_id: str) -> dict:
    return get_success_data(api_client.get_patient(patient_id, CC))


def get_case(case_id: str) -> dict:
    return get_success_data(api_client.get_surgical_case(case_id, CC))


def get_readiness(case_id: str) -> dict:
    return get_success_data(api_client.get_case_readiness(case_id, CC))


def get_record(implant_record_id: str) -> dict:
    return get_success_data(api_client.get_implant_record(implant_record_id, CC))


def get_charge(charge_id: str) -> dict:
    return get_success_data(api_client.get_charge(charge_id, RI))


def get_submission(submission_id: str) -> dict:
    return get_success_data(api_client.get_registry_submission(submission_id, CO))


def get_field_action(field_action_id: str) -> dict:
    return get_success_data(api_client.get_field_action(field_action_id, CO))


def get_notification(notification_id: str) -> dict:
    return get_success_data(api_client.get_recall_notification(notification_id, CO))


def get_invoice(invoice_id: str) -> dict:
    return get_success_data(api_client.get_vendor_invoice(invoice_id, RI))


def get_explant(explant_record_id: str) -> dict:
    return get_success_data(api_client.get_explant_record(explant_record_id, IL))


def get_exposure(field_action_id: str) -> dict:
    return get_success_data(api_client.get_field_action_exposure(field_action_id, CO))


# ─────────────────────────────────────────────────────────────────────────
# Tier 2 — entity hierarchy: vendor + terms + catalog + lot + serials
# ─────────────────────────────────────────────────────────────────────────

def _serials(count: int, prefix: str = "SN-000") -> List[str]:
    return [f"{prefix}{i + 1}" for i in range(count)]


def setup_stock(
    unit_costs: Sequence[int] = (400_000,),
    *,
    clock: Optional[str] = CLOCK_BASE,
    consigned: bool = False,
    release: bool = True,
    serials: Optional[Sequence[str]] = None,
    serial_prefix: str = "SN-000",
    vendor_code: str = None,
    vendor_name: str = None,
    agreement_overrides: Optional[dict] = None,
    catalog_overrides: Optional[dict] = None,
    lot_overrides: Optional[dict] = None,
) -> dict:
    """Build the standard receiving chain from an empty database.

    clock -> vendor -> (ACTIVE consignment agreement) -> catalog item ->
    lot in QUARANTINE -> one serialized unit per entry in `unit_costs` ->
    quarantine release.

    Returns ``{"vendor", "agreement", "catalog_item", "lot", "units"}`` where
    every value is the freshest representation the API returned.
    """
    if clock:
        set_clock(clock)
    vendor = create_vendor(name=vendor_name, vendor_code=vendor_code)
    agreement = None
    if consigned:
        agreement = create_active_agreement(vendor["id"], **(agreement_overrides or {}))
    catalog_item = create_catalog_item(vendor["id"], **(catalog_overrides or {}))
    lot = create_lot(catalog_item["id"], **(lot_overrides or {}))

    names = list(serials) if serials else _serials(len(unit_costs), serial_prefix)
    units = []
    for serial, cost in zip(names, unit_costs):
        units.append(
            add_unit(
                lot["id"],
                serial,
                cost,
                consignment_agreement_id=agreement["id"] if agreement else None,
            )
        )

    if release:
        lot = release_lot(lot["id"])
        units = [get_unit(u["id"]) for u in units]

    return {
        "vendor": vendor,
        "agreement": agreement,
        "catalog_item": get_catalog_item(catalog_item["id"]),
        "lot": get_lot(lot["id"]),
        "units": units,
    }


def add_lot_to_stock(
    world: dict,
    unit_costs: Sequence[int],
    *,
    lot_number: str,
    expiration_date: str,
    serials: Sequence[str],
    release: bool = True,
    catalog_item_id: Optional[str] = None,
) -> dict:
    """Add a second lot (optionally under a different catalog item) to an
    existing world.  Returns ``{"lot", "units"}``."""
    cat_id = catalog_item_id or world["catalog_item"]["id"]
    lot = create_lot(cat_id, lot_number=lot_number, expiration_date=expiration_date)
    agreement = world.get("agreement")
    units = [
        add_unit(
            lot["id"],
            serial,
            cost,
            consignment_agreement_id=agreement["id"] if agreement else None,
        )
        for serial, cost in zip(serials, unit_costs)
    ]
    if release:
        lot = release_lot(lot["id"])
        units = [get_unit(u["id"]) for u in units]
    return {"lot": get_lot(lot["id"]), "units": units}


# ─────────────────────────────────────────────────────────────────────────
# Tier 3 — case lifecycle shortcuts
# ─────────────────────────────────────────────────────────────────────────

def setup_scheduled_case(patient: Optional[dict] = None, **case_overrides) -> dict:
    """A patient plus one SCHEDULED case.  Returns ``{"patient", "case"}``."""
    patient = patient or create_patient()
    case = create_case(patient["id"], **case_overrides)
    return {"patient": patient, "case": case}


def setup_in_progress_case(patient: Optional[dict] = None, **case_overrides) -> dict:
    """A patient plus one case already moved SCHEDULED -> IN_PROGRESS."""
    built = setup_scheduled_case(patient, **case_overrides)
    built["case"] = start_case(built["case"]["id"])
    return built


def implant_units(case_id: str, units: Sequence[dict], **overrides) -> List[dict]:
    """Document one implant record per unit, in order.  Each documentation
    advances the case version, so the version is re-read every time."""
    return [document_implant(case_id, unit, **overrides) for unit in units]


def setup_documented_implant(
    *,
    unit_cost: int = 400_000,
    consigned: bool = False,
    clock: Optional[str] = CLOCK_BASE,
    agreement_overrides: Optional[dict] = None,
    catalog_overrides: Optional[dict] = None,
    lot_overrides: Optional[dict] = None,
    patient_overrides: Optional[dict] = None,
    case_overrides: Optional[dict] = None,
) -> dict:
    """Full chain from an empty database to one DOCUMENTED implant record.

    Returns the `setup_stock` keys plus ``{"patient", "case", "record",
    "unit"}``.
    """
    world = setup_stock(
        (unit_cost,),
        clock=clock,
        consigned=consigned,
        agreement_overrides=agreement_overrides,
        catalog_overrides=catalog_overrides,
        lot_overrides=lot_overrides,
    )
    patient = create_patient(**(patient_overrides or {}))
    case = create_case(patient["id"], **(case_overrides or {}))
    case = start_case(case["id"])
    record = document_implant(case["id"], world["units"][0])
    world.update(
        {
            "patient": patient,
            "case": get_case(case["id"]),
            "record": record,
            "unit": get_unit(world["units"][0]["id"]),
        }
    )
    return world


def setup_verified_implant(**kwargs) -> dict:
    """`setup_documented_implant` plus verification by a second clinician."""
    world = setup_documented_implant(**kwargs)
    world["record"] = verify_record(world["record"]["id"])
    world["case"] = get_case(world["case"]["id"])
    return world


def setup_posted_charge(quantity: int = 1, **kwargs) -> dict:
    """`setup_verified_implant` plus one charge line moved DRAFT -> POSTED."""
    world = setup_verified_implant(**kwargs)
    charge = create_charge(world["record"]["id"], quantity=quantity)
    world["charge"] = post_charge(charge["id"])
    world["case"] = get_case(world["case"]["id"])
    return world


# ─────────────────────────────────────────────────────────────────────────
# Tier 4 — consignment / billing state targeting
# ─────────────────────────────────────────────────────────────────────────

def setup_billable_units(
    unit_costs: Sequence[int] = (462_500,),
    *,
    agreement_overrides: Optional[dict] = None,
    catalog_overrides: Optional[dict] = None,
    case_overrides: Optional[dict] = None,
    verify: bool = False,
    clock: Optional[str] = CLOCK_BASE,
) -> dict:
    """Consigned units implanted into one IN_PROGRESS case, so every unit is
    BILLABLE with its `contract_price_cents` frozen.

    Returns the `setup_stock` keys plus ``{"patient", "case", "records"}``.
    """
    world = setup_stock(
        unit_costs,
        clock=clock,
        consigned=True,
        agreement_overrides=agreement_overrides,
        catalog_overrides=catalog_overrides,
    )
    patient = create_patient()
    case = create_case(
        patient["id"],
        **({"scheduled_end_utc": "2026-09-10T12:00:00Z"} | (case_overrides or {})),
    )
    case = start_case(case["id"])
    records = implant_units(case["id"], world["units"])
    if verify:
        records = [verify_record(r["id"]) for r in records]
    world.update(
        {
            "patient": patient,
            "case": get_case(case["id"]),
            "records": records,
            "units": [get_unit(u["id"]) for u in world["units"]],
        }
    )
    return world


def setup_submitted_invoice(
    submitted_total_cents: int,
    unit_costs: Sequence[int] = (1_000_000,),
    *,
    invoiced_unit_indexes: Optional[Sequence[int]] = None,
    agreement_overrides: Optional[dict] = None,
    catalog_overrides: Optional[dict] = None,
    invoice_number: str = "INV-1",
    verify: bool = False,
) -> dict:
    """`setup_billable_units` plus one SUBMITTED consignment invoice."""
    world = setup_billable_units(
        unit_costs,
        agreement_overrides=agreement_overrides,
        catalog_overrides=catalog_overrides,
        verify=verify,
    )
    idxs = (
        list(invoiced_unit_indexes)
        if invoiced_unit_indexes is not None
        else list(range(len(world["units"])))
    )
    unit_ids = [world["units"][i]["id"] for i in idxs]
    world["invoice"] = submit_invoice(
        world["vendor"]["id"],
        world["agreement"]["id"],
        unit_ids,
        submitted_total_cents,
        invoice_number=invoice_number,
    )
    world["invoiced_unit_ids"] = unit_ids
    return world


def setup_matched_invoice(submitted_total_cents: int, *args, **kwargs) -> dict:
    """`setup_submitted_invoice` plus the reconciliation match, which lands the
    invoice on MATCHED or VARIANCE_HOLD depending on the computed variance.

    Forwards the positional `unit_costs` argument of `setup_submitted_invoice`
    verbatim, so callers may pass it either positionally or by keyword."""
    world = setup_submitted_invoice(submitted_total_cents, *args, **kwargs)
    world["invoice"] = match_invoice(world["invoice"]["id"])
    return world


# ─────────────────────────────────────────────────────────────────────────
# Tier 5 — terminal states: explant / return, recall publication
# ─────────────────────────────────────────────────────────────────────────

def setup_explanted_unit(
    unit_cost: int = 462_500,
    *,
    consigned: bool = True,
    reason: str = "DEVICE_FAILURE",
    explant_clock: Optional[str] = None,
    catalog_overrides: Optional[dict] = None,
    agreement_overrides: Optional[dict] = None,
) -> dict:
    """One consigned unit implanted, verified and explanted, leaving the
    ExplantRecord in RECORDED and the unit in CREDIT_PENDING."""
    world = setup_verified_implant(
        unit_cost=unit_cost,
        consigned=consigned,
        catalog_overrides=catalog_overrides,
        agreement_overrides=agreement_overrides,
    )
    if explant_clock:
        set_clock(explant_clock)
    world["explant"] = record_explant(world["record"]["id"], reason=reason)
    world["record"] = get_record(world["record"]["id"])
    world["unit"] = get_unit(world["unit"]["id"])
    return world


def setup_shipped_explant(unit_cost: int = 462_500, **kwargs) -> dict:
    """`setup_explanted_unit` authorised for return with an RA number and
    shipped, leaving the ExplantRecord in SHIPPED."""
    world = setup_explanted_unit(unit_cost, **kwargs)
    disposition_explant(
        world["explant"]["id"], "RETURN_TO_VENDOR", return_authorization_no="RA-77"
    )
    world["explant"] = ship_explant(world["explant"]["id"])
    world["unit"] = get_unit(world["unit"]["id"])
    return world


def setup_published_field_action(
    *,
    action_class: str = "CLASS_II",
    scope_type: str = "CATALOG",
    unit_costs: Sequence[int] = (400_000, 400_000),
    implant_indexes: Sequence[int] = (1,),
    consigned: bool = False,
    field_action_overrides: Optional[dict] = None,
    catalog_overrides: Optional[dict] = None,
    agreement_overrides: Optional[dict] = None,
) -> dict:
    """Stock, one or more implanted units, then a PUBLISHED field action.

    Returns the `setup_stock` keys plus ``{"patient", "case", "records",
    "field_action", "notifications"}``.
    """
    world = setup_stock(
        unit_costs,
        consigned=consigned,
        catalog_overrides=catalog_overrides,
        agreement_overrides=agreement_overrides,
    )
    patient = create_patient()
    case = create_case(patient["id"], scheduled_end_utc="2026-09-10T12:00:00Z")
    case = start_case(case["id"])
    records = implant_units(
        case["id"], [world["units"][i] for i in implant_indexes]
    )
    action = create_field_action(
        world["vendor"]["id"],
        world["catalog_item"]["id"],
        action_class=action_class,
        scope_type=scope_type,
        **(field_action_overrides or {}),
    )
    action = publish_field_action(action["id"])
    world.update(
        {
            "patient": patient,
            "case": get_case(case["id"]),
            "records": records,
            "field_action": action,
            "notifications": notifications_for(action["id"]),
            "units": [get_unit(u["id"]) for u in world["units"]],
            "lot": get_lot(world["lot"]["id"]),
        }
    )
    return world
