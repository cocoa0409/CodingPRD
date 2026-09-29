"""Composite setup helpers.

Every fixture drives the real API through the documented endpoints only, and
uses the lenient ``get_success_data`` so a broken preamble reports "Setup step
failed" instead of a confusing assertion.

The reconditioning pipeline is long — a unit must be registered under a counted
and accepted shipment, identified against a model, torn down, inspected, bench
tested, adjudicated and only then labelled — so most fixtures below return a
``ctx`` dict whose keys are stable:

    ctx["model"]        the ModelSpec every other row hangs off
    ctx["account"]      the CustomerAccount owning the shipment
    ctx["shipment"]     the IntakeShipment
    ctx["units"]        list of EquipmentUnit rows in registration order
    ctx["unit"]         ctx["units"][0], the unit under test
    ctx["bench"]        the TestBench, when one was needed
    ctx["shell_tests"]  list of ShellTest rows in creation order
    ctx["shell_test"]   ctx["shell_tests"][0]
    ctx["labels"]       list of CertificationLabel rows
    ctx["label"]        ctx["labels"][0]
    ctx["part"]         the ApprovedPart, when one was needed
    ctx["repair_order"] the RepairOrder, when one was needed

Impact triples used repeatedly (PRD §3.5 weighting, AMBIENT, POLYCARBONATE):
    (300, 300, 300) -> severity_index 300.0 -> PASS at the inclusive band edge
    (300, 340, 290) -> severity_index 310.0 -> REPAIR
    (400, 600, 900) -> severity_index 450.0 -> CONDEMN (each site term capped)
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_EPOCH, TEST_DEFAULTS
from .factories import (
    accept_shipment_payload,
    billing_hold_payload,
    calibrate_test_bench_payload,
    condemn_unit_payload,
    count_shipment_payload,
    create_approved_part_payload,
    create_certification_label_payload,
    create_customer_account_payload,
    create_equipment_unit_payload,
    create_inspection_payload,
    create_intake_shipment_payload,
    create_loaner_assignment_payload,
    create_loaner_unit_payload,
    create_model_spec_payload,
    create_repair_order_payload,
    create_shell_test_payload,
    create_test_bench_payload,
    determine_payload,
    identify_unit_payload,
    liability_acknowledgment_payload,
    part_line_payload,
    record_impacts_payload,
    release_unit_payload,
    verify_destruction_payload,
    verify_repair_payload,
    void_label_payload,
    witness_destruction_payload,
)
from .test_users import (
    COMPLIANCE_1,
    COMPLIANCE_2,
    INSPECTOR_1,
    INTAKE_CLERK,
    PLANT_MANAGER,
    TECHNICIAN_1,
    TECHNICIAN_2,
)

PASS_IMPACTS = (300, 300, 300)
REPAIR_IMPACTS = (300, 340, 290)
CONDEMN_IMPACTS = (400, 600, 900)


# --------------------------------------------------------------------------
# Tier 0: single-call builders
# --------------------------------------------------------------------------
def set_clock(current_utc=CLOCK_EPOCH):
    """Pin the logical clock. Returns the endpoint's payload."""
    return get_success_data(api_client.set_clock(current_utc, PLANT_MANAGER))


def create_model(**overrides):
    """Create a ModelSpec. Defaults to the reference SF-2026 spec."""
    return get_success_data(
        api_client.create_model_spec(create_model_spec_payload(**overrides), PLANT_MANAGER)
    )


def create_account(waiver=True, waiver_version=None, billing_hold=False, **overrides):
    """Create a CustomerAccount, optionally acknowledging the liability waiver
    and/or placing the account on billing hold."""
    account = get_success_data(
        api_client.create_customer_account(
            create_customer_account_payload(**overrides), PLANT_MANAGER
        )
    )
    if waiver:
        kwargs = {} if waiver_version is None else {"waiver_version": waiver_version}
        account = get_success_data(
            api_client.acknowledge_liability(
                account["id"], liability_acknowledgment_payload(**kwargs), INTAKE_CLERK
            )
        )
    if billing_hold:
        account = get_success_data(
            api_client.set_billing_hold(account["id"], billing_hold_payload(True), PLANT_MANAGER)
        )
    return account


def hold_account(account_id, reason="unpaid invoice 8841"):
    """Put an existing account on billing hold."""
    return get_success_data(
        api_client.set_billing_hold(
            account_id, billing_hold_payload(True, reason=reason), PLANT_MANAGER
        )
    )


def create_bench(calibrate=True, calibration_valid_until=None, **overrides):
    """Create a TestBench and, by default, calibrate it through 2026-12-31."""
    bench = get_success_data(
        api_client.create_test_bench(create_test_bench_payload(**overrides), PLANT_MANAGER)
    )
    if calibrate:
        kwargs = (
            {}
            if calibration_valid_until is None
            else {"calibration_valid_until": calibration_valid_until}
        )
        bench = get_success_data(
            api_client.calibrate_test_bench(
                bench["id"], calibrate_test_bench_payload(**kwargs), PLANT_MANAGER
            )
        )
    return bench


def create_part(model_spec_id, **overrides):
    """Create an ApprovedPart against a model."""
    return get_success_data(
        api_client.create_approved_part(
            create_approved_part_payload(model_spec_id, **overrides), PLANT_MANAGER
        )
    )


def create_loaner(model_spec_id, **overrides):
    """Create a LoanerUnit against a model."""
    return get_success_data(
        api_client.create_loaner_unit(
            create_loaner_unit_payload(model_spec_id, **overrides), PLANT_MANAGER
        )
    )


def read_unit(unit_id, headers=INSPECTOR_1):
    return get_success_data(api_client.get_equipment_unit(unit_id, headers))


def read_shipment(shipment_id, headers=PLANT_MANAGER):
    return get_success_data(api_client.get_intake_shipment(shipment_id, headers))


def read_account(account_id, headers=PLANT_MANAGER):
    return get_success_data(api_client.get_customer_account(account_id, headers))


def read_shell_test(shell_test_id, headers=INSPECTOR_1):
    return get_success_data(api_client.get_shell_test(shell_test_id, headers))


def read_repair_order(repair_order_id, headers=TECHNICIAN_1):
    return get_success_data(api_client.get_repair_order(repair_order_id, headers))


def read_part(part_id, headers=PLANT_MANAGER):
    return get_success_data(api_client.get_approved_part(part_id, headers))


def read_label(label_id, headers=INSPECTOR_1):
    return get_success_data(api_client.get_certification_label(label_id, headers))


def read_loaner_unit(loaner_unit_id, headers=PLANT_MANAGER):
    return get_success_data(api_client.get_loaner_unit(loaner_unit_id, headers))


def read_loaner_assignment(assignment_id, headers=INTAKE_CLERK):
    return get_success_data(api_client.get_loaner_assignment(assignment_id, headers))


def unit_version(unit_id, headers=INSPECTOR_1) -> int:
    """Current optimistic-concurrency version of a unit, for the two endpoints
    that demand ``expected_equipment_unit_version``."""
    return read_unit(unit_id, headers)["version"]


# --------------------------------------------------------------------------
# Tier 1: shipment intake progression
# --------------------------------------------------------------------------
def setup_reference_data(clock=CLOCK_EPOCH, waiver=True, model_overrides=None,
                         account_overrides=None, billing_hold=False):
    """Clock + one ModelSpec + one CustomerAccount. Returns a ctx dict with
    ``model`` and ``account``."""
    set_clock(clock)
    model = create_model(**(model_overrides or {}))
    account = create_account(
        waiver=waiver, billing_hold=billing_hold, **(account_overrides or {})
    )
    return {"model": model, "account": account}


def register_units(shipment_id, count, serial_prefix="SN", model_code=None,
                   start_index=1, **overrides):
    """Register ``count`` units under a counted shipment. Serials run
    SN-0001, SN-0002, ... so they are unique inside the account."""
    units = []
    for offset in range(count):
        serial = f"{serial_prefix}-{start_index + offset:04d}"
        payload = create_equipment_unit_payload(shipment_id, serial_number=serial, **overrides)
        if model_code is not None:
            payload["declared_model_code"] = model_code
        units.append(
            get_success_data(api_client.create_equipment_unit(payload, INTAKE_CLERK))
        )
    return units


def setup_counted_shipment(unit_count=1, service_tier="STANDARD", counted_unit_count=None,
                           register=True, clock=CLOCK_EPOCH, waiver=True,
                           model_overrides=None, account_overrides=None,
                           billing_hold=False, shipment_overrides=None):
    """Reference data + a shipment that has been counted and (by default) has
    all of its units registered, but has NOT been accepted.

    Returns ctx with ``model``, ``account``, ``shipment``, ``units``, ``unit``.
    """
    ctx = setup_reference_data(
        clock=clock,
        waiver=waiver,
        model_overrides=model_overrides,
        account_overrides=account_overrides,
        billing_hold=billing_hold,
    )
    payload = create_intake_shipment_payload(
        ctx["account"]["id"],
        service_tier=service_tier,
        declared_unit_count=unit_count,
        **(shipment_overrides or {}),
    )
    shipment = get_success_data(api_client.create_intake_shipment(payload, INTAKE_CLERK))
    counted = unit_count if counted_unit_count is None else counted_unit_count
    shipment = get_success_data(
        api_client.count_intake_shipment(
            shipment["id"], count_shipment_payload(counted), INTAKE_CLERK
        )
    )
    units = register_units(shipment["id"], counted if register else 0)
    ctx.update({"shipment": shipment, "units": units, "unit": units[0] if units else None})
    return ctx


def accept_shipment(shipment_id, discrepancy_resolution="MATCHED"):
    return get_success_data(
        api_client.accept_intake_shipment(
            shipment_id, accept_shipment_payload(discrepancy_resolution), INTAKE_CLERK
        )
    )


def setup_accepted_shipment(unit_count=1, service_tier="STANDARD",
                            discrepancy_resolution="MATCHED", **kwargs):
    """A counted shipment moved on to ACCEPTED with every unit registered and
    still in RECEIVED. Returns the same ctx as ``setup_counted_shipment``."""
    ctx = setup_counted_shipment(unit_count=unit_count, service_tier=service_tier, **kwargs)
    ctx["shipment"] = accept_shipment(ctx["shipment"]["id"], discrepancy_resolution)
    return ctx


# --------------------------------------------------------------------------
# Tier 2: unit progression
# --------------------------------------------------------------------------
def identify_unit(unit_id, model_spec_id, **overrides):
    return get_success_data(
        api_client.identify_equipment_unit(
            unit_id, identify_unit_payload(model_spec_id, **overrides), INTAKE_CLERK
        )
    )


def disassemble_unit(unit_id, headers=TECHNICIAN_1):
    return get_success_data(api_client.disassemble_equipment_unit(unit_id, headers))


def inspect_component(unit_id, headers=TECHNICIAN_1, **overrides):
    return get_success_data(
        api_client.create_component_inspection(
            unit_id, create_inspection_payload(**overrides), headers
        )
    )


def advance_unit_to_inspected(unit_id, model_spec_id, identify_overrides=None,
                              measurement_value=None, inspect_overrides=None):
    """identify -> disassemble -> one SHELL inspection, which is the model's
    only required component code, so the unit lands in INSPECTED."""
    identify_unit(unit_id, model_spec_id, **(identify_overrides or {}))
    disassemble_unit(unit_id)
    overrides = dict(inspect_overrides or {})
    if measurement_value is not None:
        overrides["measurement_value"] = measurement_value
    inspect_component(unit_id, **overrides)
    return read_unit(unit_id)


def schedule_shell_test(unit_id, bench_id, window_start="2026-08-01T09:00:00Z",
                        window_end="2026-08-01T10:00:00Z", conditioning="AMBIENT",
                        headers=TECHNICIAN_1):
    return get_success_data(
        api_client.create_shell_test(
            create_shell_test_payload(
                unit_id,
                bench_id,
                window_start=window_start,
                window_end=window_end,
                conditioning=conditioning,
            ),
            headers,
        )
    )


def record_impacts(shell_test_id, impacts=PASS_IMPACTS, headers=TECHNICIAN_1):
    front, side, crown = impacts
    return get_success_data(
        api_client.record_impacts(
            shell_test_id, record_impacts_payload(front, side, crown), headers
        )
    )


def determine(shell_test_id, determination="PASS", override_reason=None,
              headers=INSPECTOR_1):
    payload = determine_payload(determination)
    if override_reason is not None:
        payload["override_reason"] = override_reason
    return get_success_data(api_client.determine_shell_test(shell_test_id, payload, headers))


def issue_label(unit_id, headers=INSPECTOR_1):
    """Read the unit's current version and issue its certification label."""
    version = unit_version(unit_id, headers)
    return get_success_data(
        api_client.create_certification_label(
            create_certification_label_payload(unit_id, version), headers
        )
    )


def void_label(label_id, headers=COMPLIANCE_1, **overrides):
    return get_success_data(
        api_client.void_certification_label(label_id, void_label_payload(**overrides), headers)
    )


def bench_window(index=0, day="2026-08-01", start_hour=9, hours=1):
    """Non-conflicting bench windows two hours apart, so the 45-minute cooldown
    padding on either side never collides."""
    start = start_hour + index * 2
    return (
        f"{day}T{start:02d}:00:00Z",
        f"{day}T{start + hours:02d}:00:00Z",
    )


# --------------------------------------------------------------------------
# Tier 3: full-lifecycle shortcuts
# --------------------------------------------------------------------------
def setup_inspected_units(unit_count=1, service_tier="STANDARD", bench=True,
                          calibration_valid_until=None, identify_overrides=None,
                          measurement_value=None, bench_overrides=None, **kwargs):
    """Accepted shipment whose every unit has been identified, torn down and
    shell-inspected, so each unit sits in INSPECTED. Adds ``bench`` to ctx."""
    ctx = setup_accepted_shipment(unit_count=unit_count, service_tier=service_tier, **kwargs)
    for unit in ctx["units"]:
        advance_unit_to_inspected(
            unit["id"],
            ctx["model"]["id"],
            identify_overrides=identify_overrides,
            measurement_value=measurement_value,
        )
    ctx["units"] = [read_unit(u["id"]) for u in ctx["units"]]
    ctx["unit"] = ctx["units"][0]
    if bench:
        ctx["bench"] = create_bench(
            calibration_valid_until=calibration_valid_until, **(bench_overrides or {})
        )
    return ctx


def setup_tested_units(unit_count=1, impacts=PASS_IMPACTS, conditioning="AMBIENT", **kwargs):
    """Every unit of the shipment bench-tested once, so each unit is TESTED and
    each session COMPLETED with a severity index. Adds ``shell_tests`` /
    ``shell_test`` to ctx."""
    ctx = setup_inspected_units(unit_count=unit_count, **kwargs)
    sessions = []
    for index, unit in enumerate(ctx["units"]):
        window_start, window_end = bench_window(index)
        session = schedule_shell_test(
            unit["id"],
            ctx["bench"]["id"],
            window_start=window_start,
            window_end=window_end,
            conditioning=conditioning,
        )
        sessions.append(record_impacts(session["id"], impacts))
    ctx["shell_tests"] = sessions
    ctx["shell_test"] = sessions[0]
    ctx["units"] = [read_unit(u["id"]) for u in ctx["units"]]
    ctx["unit"] = ctx["units"][0]
    return ctx


def setup_determined_units(unit_count=1, determination="PASS", impacts=PASS_IMPACTS,
                           override_reason=None, **kwargs):
    """Every session signed with ``determination``. PASS leaves units in
    TEST_PASSED, REPAIR in REPAIR_PENDING, CONDEMN in CONDEMNED."""
    ctx = setup_tested_units(unit_count=unit_count, impacts=impacts, **kwargs)
    ctx["shell_tests"] = [
        determine(session["id"], determination, override_reason)
        for session in ctx["shell_tests"]
    ]
    ctx["shell_test"] = ctx["shell_tests"][0]
    ctx["units"] = [read_unit(u["id"]) for u in ctx["units"]]
    ctx["unit"] = ctx["units"][0]
    ctx["shipment"] = read_shipment(ctx["shipment"]["id"])
    return ctx


def setup_test_passed_unit(**kwargs):
    """One unit in TEST_PASSED after a PASS determination on 300.0."""
    return setup_determined_units(unit_count=1, determination="PASS", **kwargs)


def setup_repair_pending_unit(**kwargs):
    """One unit in REPAIR_PENDING after a REPAIR determination on 310.0."""
    return setup_determined_units(
        unit_count=1, determination="REPAIR", impacts=REPAIR_IMPACTS, **kwargs
    )


def setup_condemned_unit(**kwargs):
    """One unit CONDEMNED by a CONDEMN determination on 450.0, with the
    destruction record the cascade creates. Adds ``destruction_record``."""
    ctx = setup_determined_units(
        unit_count=1, determination="CONDEMN", impacts=CONDEMN_IMPACTS, **kwargs
    )
    records = list_destruction_records(ctx["unit"]["id"])
    ctx["destruction_records"] = records
    ctx["destruction_record"] = records[0] if records else None
    return ctx


def setup_certified_units(unit_count=1, **kwargs):
    """Every unit taken all the way to CERTIFIED with an ACTIVE label. Adds
    ``labels`` / ``label`` to ctx."""
    ctx = setup_determined_units(unit_count=unit_count, determination="PASS", **kwargs)
    ctx["labels"] = [issue_label(unit["id"]) for unit in ctx["units"]]
    ctx["label"] = ctx["labels"][0]
    ctx["units"] = [read_unit(u["id"]) for u in ctx["units"]]
    ctx["unit"] = ctx["units"][0]
    ctx["shipment"] = read_shipment(ctx["shipment"]["id"])
    ctx["account"] = read_account(ctx["account"]["id"])
    return ctx


def setup_settled_shipment(unit_count=1, service_tier="STANDARD", **kwargs):
    """Every unit certified, the shipment READY_FOR_RETURN and then settled, so
    ``settlement_locked`` is true and ``final_total_cents`` is written."""
    ctx = setup_certified_units(unit_count=unit_count, service_tier=service_tier, **kwargs)
    ctx["shipment"] = get_success_data(
        api_client.settle_intake_shipment(ctx["shipment"]["id"], PLANT_MANAGER)
    )
    return ctx


def stage_unit(unit_id):
    return get_success_data(api_client.stage_return_equipment_unit(unit_id, INTAKE_CLERK))


def release_unit(unit_id, **overrides):
    return get_success_data(
        api_client.release_equipment_unit(unit_id, release_unit_payload(**overrides), INTAKE_CLERK)
    )


def condemn_unit(unit_id, condemn_reason="NOT_RECONDITIONABLE", headers=INSPECTOR_1):
    return get_success_data(
        api_client.condemn_equipment_unit(unit_id, condemn_unit_payload(condemn_reason), headers)
    )


def list_destruction_records(unit_id, headers=COMPLIANCE_1):
    return get_success_data(api_client.list_unit_destruction_records(unit_id, headers))


def list_labels(unit_id, headers=INSPECTOR_1):
    return get_success_data(api_client.list_unit_certification_labels(unit_id, headers))


def list_inspections(unit_id, headers=TECHNICIAN_1):
    return get_success_data(api_client.list_component_inspections(unit_id, headers))


# --------------------------------------------------------------------------
# Tier 4: repair orders and part stock targeting
# --------------------------------------------------------------------------
def open_repair_order(unit_id, headers=TECHNICIAN_1):
    """Open a repair order on a REPAIR_PENDING unit, reading its version first."""
    version = unit_version(unit_id, headers)
    return get_success_data(
        api_client.create_repair_order(
            create_repair_order_payload(unit_id, version), headers
        )
    )


def add_part_line(repair_order_id, approved_part_id, quantity=1, headers=TECHNICIAN_1,
                  **overrides):
    return get_success_data(
        api_client.add_repair_order_part_line(
            repair_order_id,
            part_line_payload(approved_part_id, quantity, **overrides),
            headers,
        )
    )


def submit_repair_order(repair_order_id, headers=TECHNICIAN_1):
    return get_success_data(api_client.submit_repair_order(repair_order_id, headers))


def install_repair_order(repair_order_id, warranty_claim_ref=None, headers=TECHNICIAN_1):
    payload = {} if warranty_claim_ref is None else {"warranty_claim_ref": warranty_claim_ref}
    return get_success_data(api_client.install_repair_order(repair_order_id, payload, headers))


def verify_repair_order(repair_order_id, outcome="PASSED", headers=TECHNICIAN_2, **overrides):
    """Verification must come from a technician other than the installer, so the
    default headers are the second technician."""
    return get_success_data(
        api_client.verify_repair_order(
            repair_order_id, verify_repair_payload(outcome, **overrides), headers
        )
    )


def setup_repair_order(target_status="DRAFT", quantity=1, received_qty=4,
                       part_overrides=None, warranty_claim_ref="WC-1", **kwargs):
    """A REPAIR_PENDING unit plus an ApprovedPart plus a repair order walked to
    ``target_status`` (DRAFT, PARTS_PENDING, INSTALLED, CLOSED or CANCELLED).
    Adds ``part`` and ``repair_order`` to ctx."""
    ctx = setup_repair_pending_unit(**kwargs)
    ctx["part"] = create_part(
        ctx["model"]["id"], received_qty=received_qty, **(part_overrides or {})
    )
    order = open_repair_order(ctx["unit"]["id"])
    if target_status != "DRAFT" or quantity:
        order = add_part_line(order["id"], ctx["part"]["id"], quantity)
    if target_status in ("PARTS_PENDING", "INSTALLED", "CLOSED", "CANCELLED"):
        order = submit_repair_order(order["id"])
    if target_status in ("INSTALLED", "CLOSED"):
        order = install_repair_order(order["id"], warranty_claim_ref)
    if target_status == "CLOSED":
        order = verify_repair_order(order["id"], "PASSED")
    ctx["repair_order"] = read_repair_order(order["id"])
    ctx["part"] = read_part(ctx["part"]["id"])
    ctx["unit"] = read_unit(ctx["unit"]["id"])
    return ctx


def setup_repaired_unit(**kwargs):
    """A unit driven REPAIR_PENDING -> REPAIRED by a PASSED verification."""
    return setup_repair_order(target_status="CLOSED", **kwargs)


def burn_verification_attempts(repair_order_id, attempts=1, installer=TECHNICIAN_1,
                               verifier=TECHNICIAN_2):
    """Fail ``attempts`` verifications, re-installing between each one, leaving
    the order back in INSTALLED and ready for the next verification."""
    order = read_repair_order(repair_order_id)
    for index in range(attempts):
        order = get_success_data(
            api_client.verify_repair_order(
                repair_order_id,
                verify_repair_payload("FAILED", note=f"rework {index + 1} rejected"),
                verifier,
            )
        )
        if order["status"] == "PARTS_PENDING":
            order = get_success_data(api_client.install_repair_order(repair_order_id, {}, installer))
    return order


# --------------------------------------------------------------------------
# Tier 5: destruction, retention and terminal custody
# --------------------------------------------------------------------------
def witness_destruction(record_id, headers=COMPLIANCE_1, **overrides):
    return get_success_data(
        api_client.witness_destruction_record(
            record_id, witness_destruction_payload(**overrides), headers
        )
    )


def verify_destruction(record_id, headers=COMPLIANCE_2, **overrides):
    """Verification must come from an officer other than the witness."""
    return get_success_data(
        api_client.verify_destruction_record(
            record_id, verify_destruction_payload(**overrides), headers
        )
    )


def setup_destruction_record(target_status="PENDING", **kwargs):
    """A condemned unit and its destruction record walked to ``target_status``
    (PENDING, WITNESSED or VERIFIED)."""
    ctx = setup_condemned_unit(**kwargs)
    record = ctx["destruction_record"]
    if target_status in ("WITNESSED", "VERIFIED"):
        record = witness_destruction(record["id"])
    if target_status == "VERIFIED":
        record = verify_destruction(record["id"])
    ctx["destruction_record"] = record
    ctx["unit"] = read_unit(ctx["unit"]["id"])
    return ctx


def purge_records(unit_id, headers=COMPLIANCE_1):
    return get_success_data(api_client.purge_equipment_unit_records(unit_id, headers))


# --------------------------------------------------------------------------
# Tier 6: loaner logistics
# --------------------------------------------------------------------------
def setup_loaner_pool(grades=("A",), clock=CLOCK_EPOCH, waiver=True, billing_hold=False,
                      certification_valid_until=None, model_overrides=None,
                      account_overrides=None):
    """Reference data plus one AVAILABLE loaner per entry of ``grades``, tagged
    LN-001, LN-002, ... in creation order. Adds ``loaners`` / ``loaner``."""
    ctx = setup_reference_data(
        clock=clock,
        waiver=waiver,
        billing_hold=billing_hold,
        model_overrides=model_overrides,
        account_overrides=account_overrides,
    )
    loaners = []
    for index, grade in enumerate(grades):
        overrides = {"asset_tag": f"LN-{index + 1:03d}", "condition_grade": grade}
        if certification_valid_until is not None:
            overrides["certification_valid_until"] = certification_valid_until
        loaners.append(create_loaner(ctx["model"]["id"], **overrides))
    ctx["loaners"] = loaners
    ctx["loaner"] = loaners[0] if loaners else None
    return ctx


def book_loaner(account_id, model_spec_id, loaner_unit_id=None, headers=INTAKE_CLERK,
                **overrides):
    payload = create_loaner_assignment_payload(account_id, model_spec_id, **overrides)
    if loaner_unit_id is not None:
        payload["loaner_unit_id"] = loaner_unit_id
    return get_success_data(api_client.create_loaner_assignment(payload, headers))


def setup_loaner_assignment(explicit=True, **kwargs):
    """A booked RESERVED assignment on the first loaner of the pool. Adds
    ``assignment`` to ctx."""
    ctx = setup_loaner_pool(**kwargs)
    ctx["assignment"] = book_loaner(
        ctx["account"]["id"],
        ctx["model"]["id"],
        loaner_unit_id=ctx["loaner"]["id"] if explicit else None,
    )
    ctx["loaner"] = read_loaner_unit(ctx["loaner"]["id"])
    return ctx


def return_loaner(assignment_id, headers=INTAKE_CLERK, note=None):
    payload = {} if note is None else {"return_condition_note": note}
    return get_success_data(api_client.return_loaner_assignment(assignment_id, payload, headers))
