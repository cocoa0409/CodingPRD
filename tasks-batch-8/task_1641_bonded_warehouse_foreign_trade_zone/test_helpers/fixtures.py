"""Composite setup helpers for the bonded-warehouse FTZ domain.

Every fixture builds its preconditions from scratch via PRD-declared endpoints
(each test starts against an empty database). Fixtures use get_success_data()
(lenient) internally so setup failures surface as clear "Setup failed" errors.

Identity threading: the Importer's X-User-ID becomes the importer_ref ownership
anchor on created resources, so ownership-gated follow-up calls thread the SAME
importer id via make_importer_headers(importer_id).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import HTS_RATE_TABLE
from .factories import (
    create_access_badge_payload,
    create_admission_payload,
    create_annual_reconciliation_payload,
    create_manipulation_order_payload,
    create_weekly_entry_payload,
    create_withdrawal_payload,
    create_zone_payload,
)
from .test_users import (
    make_customs_officer_headers,
    make_gate_officer_headers,
    make_importer_headers,
    make_zone_operator_headers,
)

DEFAULT_IMPORTER = "imp-1"


# ---------------------------------------------------------------------------
# Tier 1: State progression — zones, admissions, badges
# ---------------------------------------------------------------------------

def create_zone(bond_coverage_cents=10_000_000_000, name="Test Zone", zone_code="Z-TST"):
    """Create a zone (status ACTIVE, posture NORMAL, zero aggregates)."""
    headers = make_zone_operator_headers()
    resp = api_client.create_zone(
        create_zone_payload(name=name, zone_code=zone_code, bond_coverage_cents=bond_coverage_cents),
        headers,
    )
    return get_success_data(resp)


def suspend_zone(zone_id):
    """Drive an ACTIVE zone to SUSPENDED."""
    headers = make_zone_operator_headers()
    resp = api_client.transition_zone(zone_id, {"to_status": "SUSPENDED"}, headers)
    return get_success_data(resp)


def create_admission(zone_id, importer_id=DEFAULT_IMPORTER, **overrides):
    """Create a DRAFT admission; importer_ref anchored to importer_id."""
    headers = make_importer_headers(importer_id)
    payload = create_admission_payload(zone_id=zone_id, **overrides)
    resp = api_client.create_admission(payload, headers)
    return get_success_data(resp)


def submit_admission(admission_id, importer_id=DEFAULT_IMPORTER):
    """DRAFT -> SUBMITTED as the owning importer."""
    headers = make_importer_headers(importer_id)
    resp = api_client.submit_admission(admission_id, headers)
    return get_success_data(resp)


def admit_admission(admission_id):
    """SUBMITTED -> ADMITTED as customs."""
    headers = make_customs_officer_headers()
    resp = api_client.admit_admission(admission_id, headers)
    return get_success_data(resp)


def create_badge(zone_id, holder_name="Test Holder",
                 valid_from="2026-08-01T00:00:00Z", valid_until="2026-12-31T00:00:00Z",
                 **overrides):
    """Issue an ACTIVE access badge."""
    headers = make_zone_operator_headers()
    payload = create_access_badge_payload(
        zone_id=zone_id, holder_name=holder_name,
        valid_from=valid_from, valid_until=valid_until, **overrides,
    )
    resp = api_client.create_access_badge(payload, headers)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: Entity hierarchy — zone -> admitted admission -> inventory lot
# ---------------------------------------------------------------------------

def setup_zone_with_lot(
    quantity=5,
    unit_value_cents=1000,
    hts_code="0401.10",
    zone_status="NON_PRIVILEGED_FOREIGN",
    bond_coverage_cents=10_000_000_000,
    importer_id=DEFAULT_IMPORTER,
    zone_name="Test Zone",
    zone_code="Z-TST",
):
    """Zone + one ADMITTED admission. Returns (zone, admission, lot).

    The admit transition creates exactly one InventoryLot for the admission.
    """
    zone = create_zone(bond_coverage_cents=bond_coverage_cents, name=zone_name, zone_code=zone_code)
    admission = create_admission(
        zone["id"], importer_id=importer_id,
        quantity=quantity, unit_value_cents=unit_value_cents,
        hts_code=hts_code, zone_status=zone_status,
    )
    submit_admission(admission["id"], importer_id=importer_id)
    admit_admission(admission["id"])
    op_headers = make_zone_operator_headers()
    lots_resp = api_client.list_lots(op_headers, params={"admission_id": admission["id"]})
    lots = get_success_data(lots_resp)
    assert len(lots) == 1, f"Setup failed: expected 1 lot for admission, got {len(lots)}"
    return zone, admission, lots[0]


def get_zone(zone_id):
    """Read a zone fresh."""
    return get_success_data(api_client.get_zone(zone_id, make_zone_operator_headers()))


def get_lot(lot_id):
    """Read a lot fresh."""
    return get_success_data(api_client.get_lot(lot_id, make_zone_operator_headers()))


# ---------------------------------------------------------------------------
# Tier 3: Full lifecycle shortcuts — withdrawals, manipulation orders, entries
# ---------------------------------------------------------------------------

def create_withdrawal(zone_id, lot_id, quantity=1, withdrawal_type="CONSUMPTION",
                      weekly_entry_id=None, importer_id=DEFAULT_IMPORTER):
    """Create a DRAFT withdrawal owned by importer_id."""
    headers = make_importer_headers(importer_id)
    payload = create_withdrawal_payload(
        zone_id=zone_id, lot_id=lot_id, quantity=quantity, withdrawal_type=withdrawal_type,
    )
    if weekly_entry_id is not None:
        payload["weekly_entry_id"] = weekly_entry_id
    resp = api_client.create_withdrawal(payload, headers)
    return get_success_data(resp)


def file_withdrawal(withdrawal_id, importer_id=DEFAULT_IMPORTER):
    """DRAFT -> FILED as the owning importer."""
    headers = make_importer_headers(importer_id)
    resp = api_client.file_withdrawal(withdrawal_id, headers)
    return get_success_data(resp)


def create_filed_withdrawal(zone_id, lot_id, quantity=1, withdrawal_type="CONSUMPTION",
                            weekly_entry_id=None, importer_id=DEFAULT_IMPORTER):
    """Create + file a withdrawal. Returns the FILED withdrawal."""
    w = create_withdrawal(
        zone_id, lot_id, quantity=quantity, withdrawal_type=withdrawal_type,
        weekly_entry_id=weekly_entry_id, importer_id=importer_id,
    )
    return file_withdrawal(w["id"], importer_id=importer_id)


def create_manipulation_order(zone_id, source_lot_id, input_quantity=1,
                              output_hts_code="9503.00", output_quantity=1,
                              value_added_cents=0, output_description="Finished good",
                              importer_id=DEFAULT_IMPORTER):
    """Create a REQUESTED manipulation order owned by importer_id."""
    headers = make_importer_headers(importer_id)
    payload = create_manipulation_order_payload(
        zone_id=zone_id, source_lot_id=source_lot_id, input_quantity=input_quantity,
        output_hts_code=output_hts_code, output_quantity=output_quantity,
        value_added_cents=value_added_cents, output_description=output_description,
    )
    resp = api_client.create_manipulation_order(payload, headers)
    return get_success_data(resp)


def approve_manipulation_order(order_id):
    """REQUESTED -> APPROVED as the zone operator (reserves the input quantity)."""
    headers = make_zone_operator_headers()
    resp = api_client.approve_manipulation_order(order_id, headers)
    return get_success_data(resp)


def complete_manipulation_order(order_id, importer_id=DEFAULT_IMPORTER):
    """APPROVED -> COMPLETED as the owning importer (creates the output lot)."""
    headers = make_importer_headers(importer_id)
    resp = api_client.complete_manipulation_order(order_id, headers)
    return get_success_data(resp)


def create_completed_manipulation(zone_id, source_lot_id, input_quantity,
                                  output_hts_code, output_quantity, value_added_cents,
                                  output_description="Finished good",
                                  importer_id=DEFAULT_IMPORTER):
    """Create -> approve -> complete a manipulation order. Returns (order, output_lot)."""
    order = create_manipulation_order(
        zone_id, source_lot_id, input_quantity=input_quantity,
        output_hts_code=output_hts_code, output_quantity=output_quantity,
        value_added_cents=value_added_cents, output_description=output_description,
        importer_id=importer_id,
    )
    approve_manipulation_order(order["id"])
    completed = complete_manipulation_order(order["id"], importer_id=importer_id)
    op_headers = make_zone_operator_headers()
    lots = get_success_data(
        api_client.list_lots(op_headers, params={"source_manipulation_id": order["id"]})
    )
    assert len(lots) == 1, f"Setup failed: expected 1 output lot, got {len(lots)}"
    return completed, lots[0]


def create_weekly_entry(zone_id, week_start_date="2026-07-27T00:00:00Z",
                        importer_id=DEFAULT_IMPORTER):
    """Create an OPEN weekly entry owned by importer_id."""
    headers = make_importer_headers(importer_id)
    payload = create_weekly_entry_payload(zone_id=zone_id, week_start_date=week_start_date)
    resp = api_client.create_weekly_entry(payload, headers)
    return get_success_data(resp)


def get_weekly_entry(entry_id):
    return get_success_data(api_client.get_weekly_entry(entry_id, make_zone_operator_headers()))


def setup_entry_with_filed_withdrawal(
    quantity=1,
    unit_value_cents=1221,
    hts_code="8708.29",
    lot_quantity=10,
    week_start_date="2026-07-27T00:00:00Z",
    bond_coverage_cents=10_000_000_000,
    importer_id=DEFAULT_IMPORTER,
):
    """Zone + lot + OPEN weekly entry + one attached FILED CONSUMPTION withdrawal.

    The default logical clock (2026-08-01T00:00:00Z) falls inside the default
    week [2026-07-27, 2026-08-03). Returns (zone, lot, entry, withdrawal).
    """
    zone, _admission, lot = setup_zone_with_lot(
        quantity=lot_quantity, unit_value_cents=unit_value_cents, hts_code=hts_code,
        bond_coverage_cents=bond_coverage_cents, importer_id=importer_id,
    )
    entry = create_weekly_entry(zone["id"], week_start_date=week_start_date, importer_id=importer_id)
    withdrawal = create_filed_withdrawal(
        zone["id"], lot["id"], quantity=quantity, withdrawal_type="CONSUMPTION",
        weekly_entry_id=entry["id"], importer_id=importer_id,
    )
    return zone, lot, entry, withdrawal


# ---------------------------------------------------------------------------
# Tier 4: Reconciliation shortcuts (OCC-guarded create)
# ---------------------------------------------------------------------------

def create_reconciliation(zone_id, zone_year=2026, beginning_value_cents=0,
                          physical_ending_value_cents=0):
    """Create a DRAFT AnnualReconciliation, reading the zone's current version
    for the OCC guard first. Returns the created reconciliation."""
    op_headers = make_zone_operator_headers()
    zone = get_success_data(api_client.get_zone(zone_id, op_headers))
    payload = create_annual_reconciliation_payload(
        zone_id=zone_id, zone_year=zone_year,
        beginning_value_cents=beginning_value_cents,
        physical_ending_value_cents=physical_ending_value_cents,
        expected_zone_version=zone["version"],
    )
    resp = api_client.create_annual_reconciliation(payload, op_headers)
    return get_success_data(resp)


def submit_reconciliation(recon_id):
    """DRAFT -> SUBMITTED as the zone operator (computes variance; may flag audit)."""
    headers = make_zone_operator_headers()
    resp = api_client.submit_annual_reconciliation(recon_id, headers)
    return get_success_data(resp)


def accept_reconciliation(recon_id):
    """SUBMITTED -> ACCEPTED as customs (clears an audit hold if set)."""
    headers = make_customs_officer_headers()
    resp = api_client.accept_annual_reconciliation(recon_id, headers)
    return get_success_data(resp)


def setup_zone_in_audit_hold(beginning_value_cents=0, physical_ending_value_cents=1000,
                             admission_quantity=5, admission_unit_value_cents=1000,
                             admission_hts_code="0401.10", importer_id=DEFAULT_IMPORTER):
    """Zone driven into AUDIT_HOLD via a flagged reconciliation submit.

    Default: one ADMITTED admission (book receipts 5000), reconciliation with
    beginning 0 / physical 1000 -> book ending 5000, discrepancy -4000 ->
    discrepancy_pct 80.0 > 0.5 -> flagged. Returns (zone, lot, reconciliation).
    """
    zone, _admission, lot = setup_zone_with_lot(
        quantity=admission_quantity, unit_value_cents=admission_unit_value_cents,
        hts_code=admission_hts_code, importer_id=importer_id,
    )
    recon = create_reconciliation(
        zone["id"], zone_year=2026,
        beginning_value_cents=beginning_value_cents,
        physical_ending_value_cents=physical_ending_value_cents,
    )
    submitted = submit_reconciliation(recon["id"])
    assert submitted["audit_flagged"] is True, (
        f"Setup failed: reconciliation did not flag (pct={submitted.get('discrepancy_pct')})"
    )
    return zone, lot, submitted


# ---------------------------------------------------------------------------
# Tier 5: Clock control
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    """Advance the server's logical clock."""
    headers = make_zone_operator_headers()
    resp = api_client.set_current_utc({"to_iso8601": to_iso8601}, headers)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Expected-value arithmetic helpers (decimal round-half-up, integer cents)
# ---------------------------------------------------------------------------

def expected_duty_cents(quantity, unit_value_cents, duty_rate):
    """round_half_up(quantity x unit_value_cents x duty_rate) in integer cents."""
    from decimal import Decimal, ROUND_HALF_UP
    raw = Decimal(quantity) * Decimal(unit_value_cents) * Decimal(str(duty_rate))
    return int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def expected_lot_exposure_cents(quantity_on_hand, unit_value_cents, duty_rate):
    """A lot's deferred-duty estimate contribution to the zone aggregate."""
    return expected_duty_cents(quantity_on_hand, unit_value_cents, duty_rate)


def hts_rate(hts_code):
    return HTS_RATE_TABLE[hts_code]
