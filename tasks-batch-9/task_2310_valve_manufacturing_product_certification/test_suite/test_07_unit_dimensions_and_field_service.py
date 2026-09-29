"""The unit's three dimensions and the aftermarket loop that exercises the third one.

A valve unit is not one status but three, and the field service dimension is where that
shows: a job can be opened and stocked without the certificate or the build moving at
all. Repair-kit stock is then conserved across a reserve-then-abort pair and permanently
reduced across a reserve-then-complete pair.
"""

from test_helpers import (
    BuildStatus,
    CertStatus,
    ServiceStatus,
    assert_unit_dimensions,
    fixtures,
)


# ─── Driving the service dimension on a certified, packaged unit ───


def _packaged_certified_unit_with_a_kit_stock(
    api,
    *,
    model_code,
    stock_qty,
    serial_number="SN-KIT-1",
    technician_user_id="tech-1",
    quality_manager_user_id="qm-1",
    test_bench_code="BENCH-1",
    **line_overrides,
):
    """A released design carrying repair-kit stock, and one unit off it certified and
    packaged, ready for the field."""
    line_kwargs = dict(
        foundry_code="FDY-05",
        foundry_name="Epsilon Castings",
        country_code="IN",
        heat_number="H-5001",
        mtr_document_ref="MTR-5001",
        model_code=model_code,
        repair_kit_stock_qty=stock_qty,
        license_code="MON-05",
        scope_valve_types=["BALL"],
    )
    line_kwargs.update(line_overrides)
    line = fixtures.build_traceable_line(api, **line_kwargs)
    unit = fixtures.open_unit(
        api,
        line["model"]["id"],
        line["component"]["id"],
        line["license"]["id"],
        serial_number=serial_number,
    )
    fixtures.advance_to_assembled(api, unit["id"], technician_user_id=technician_user_id)
    fixtures.record_test(
        api,
        unit["id"],
        "SHELL",
        test_bench_code=test_bench_code,
        started_at="2026-08-01T08:00:00Z",
        ended_at="2026-08-01T09:00:00Z",
        test_pressure_bar=80.0,
        hold_seconds=60,
        technician_user_id=technician_user_id,
    )
    fixtures.record_test(
        api,
        unit["id"],
        "SEAT",
        test_bench_code=test_bench_code,
        started_at="2026-08-01T09:00:00Z",
        ended_at="2026-08-01T10:00:00Z",
        test_pressure_bar=60.0,
        hold_seconds=60,
        technician_user_id=technician_user_id,
    )
    unit = fixtures.certify_unit(
        api, unit["id"], quality_manager_user_id=quality_manager_user_id
    )
    unit = fixtures.advance_build(
        api, unit["id"], "PACKAGED", technician_user_id=technician_user_id
    )
    return {"line": line, "unit": unit}


def _kit_line(api):
    """The BV-300-KIT design with five repair kits in stock and its unit in the field."""
    return _packaged_certified_unit_with_a_kit_stock(api, model_code="BV-300-KIT", stock_qty=5)


def test_01_opening_a_field_job_moves_only_the_service_dimension(api):
    """A packaged, certified unit takes a service job without its certificate or its build
    progress moving.

    PRD §3.9: "Opening a service job moves `service_status` from `NONE` or `SERVICED` to
    `OPEN` and requires the unit's `build_status` to be `PACKAGED`, `SHIPPED` or `REWORK`,
    otherwise `ERR_STATE_INVALID` — a unit that has not yet been packaged has nothing in the
    field to service." PRD §3.9: "The request carries `engineer_user_id`, which is recorded
    on the unit as `service_engineer_user_id`; that field is null whenever `service_status`
    is `NONE` or `SERVICED`."

    Design: Difficulty/non_linear_state_machine/valve_unit_service_dimension_moves_while_cert_dimension_holds
    """
    scenario = _kit_line(api)

    unit = fixtures.service_action(
        api, scenario["unit"]["id"], "OPEN", engineer_user_id="fse-1", coordinator_user_id="fsc-1"
    )

    assert_unit_dimensions(
        unit,
        build_status=BuildStatus.PACKAGED,
        cert_status=CertStatus.CERTIFIED,
        service_status=ServiceStatus.OPEN,
    )
    assert unit["service_engineer_user_id"] == "fse-1"


def test_02_reserving_parts_draws_the_design_s_stock_down(api):
    """The reservation is recorded on the unit and taken out of the design's stock in one
    motion.

    PRD §3.9: "Reserving parts moves `OPEN → PARTS_RESERVED` and carries a `kit_qty` of at
    least 1 which may not exceed the design's `repair_kit_stock_qty`; an over-draw is refused
    with `ERR_REPAIR_KIT_OUT_OF_STOCK`. A successful reservation decreases the design's
    `repair_kit_stock_qty` by `kit_qty` and records the same number in the unit's
    `reserved_kit_qty`."

    Design: Difficulty/non_linear_state_machine/valve_unit_service_dimension_moves_while_cert_dimension_holds
    """
    scenario = _kit_line(api)
    fixtures.service_action(
        api, scenario["unit"]["id"], "OPEN", engineer_user_id="fse-1", coordinator_user_id="fsc-1"
    )

    unit = fixtures.service_action(
        api, scenario["unit"]["id"], "RESERVE_KIT", kit_qty=2, coordinator_user_id="fsc-1"
    )

    assert unit["service_status"] == ServiceStatus.PARTS_RESERVED
    assert unit["reserved_kit_qty"] == 2
    model = fixtures.read_model(api, scenario["line"]["model"]["id"])
    assert model["repair_kit_stock_qty"] == 3, "Five kits less the two reserved"


def test_03_the_certificate_and_the_build_hold_across_the_whole_service_run_up(api):
    """Two service transitions later the other two dimensions read exactly as they did
    before, which a single-status machine could not represent.

    PRD §3.3: "The three advance largely independently, and the couplings between them are
    named explicitly where they exist." PRD §3.9: "The field service dimension is the
    `FieldServiceCoordinator`'s exclusive territory, and it is deliberately decoupled from
    build and certification except at the two points named below."

    Design: Difficulty/non_linear_state_machine/valve_unit_service_dimension_moves_while_cert_dimension_holds
    """
    scenario = _kit_line(api)
    fixtures.service_action(
        api, scenario["unit"]["id"], "OPEN", engineer_user_id="fse-1", coordinator_user_id="fsc-1"
    )
    fixtures.service_action(
        api, scenario["unit"]["id"], "RESERVE_KIT", kit_qty=2, coordinator_user_id="fsc-1"
    )

    unit = fixtures.read_unit(api, scenario["unit"]["id"])

    assert_unit_dimensions(
        unit,
        build_status=BuildStatus.PACKAGED,
        cert_status=CertStatus.CERTIFIED,
        service_status=ServiceStatus.PARTS_RESERVED,
    )
    assert unit["certified_by_user_id"] == "qm-1"
    assert unit["certified_at"] is not None
    assert unit["decertification_reason"] is None


# ─── Abort versus completion on the same reservation ───


def _reserved_service_job(api):
    """The BV-300-ABORT design with five kits, its unit certified, packaged and holding a
    two-kit reservation against an open field job."""
    scenario = _packaged_certified_unit_with_a_kit_stock(
        api,
        model_code="BV-300-ABORT",
        stock_qty=5,
        foundry_code="FDY-17",
        foundry_name="Rho Castings",
        heat_number="H-1701",
        mtr_document_ref="MTR-1701",
        license_code="MON-17",
        lead_auditor_user_id="aud-6",
        serial_number="SN-ABORT-1",
        technician_user_id="tech-6",
        quality_manager_user_id="qm-4",
        test_bench_code="BENCH-8",
    )
    fixtures.service_action(
        api, scenario["unit"]["id"], "OPEN", engineer_user_id="fse-2", coordinator_user_id="fsc-2"
    )
    fixtures.service_action(
        api, scenario["unit"]["id"], "RESERVE_KIT", kit_qty=2, coordinator_user_id="fsc-2"
    )
    return scenario


def test_04_aborting_the_job_returns_the_reserved_kits_to_the_design(api):
    """Stock is conserved across the reserve-and-abort pair: the design is back to the five
    kits it started with and the unit holds none.

    PRD §3.9: "Aborting is the compensating action, available from `OPEN`, `PARTS_RESERVED`
    or `IN_SERVICE`, and it returns `service_status` to `NONE`: the design's
    `repair_kit_stock_qty` increases by the unit's `reserved_kit_qty`, `reserved_kit_qty`
    returns to 0, and `service_engineer_user_id` is cleared."

    Design: Difficulty/compensating_invariant/service_abort_restores_repair_kit_stock_unlike_completion
    """
    scenario = _reserved_service_job(api)
    reserved = fixtures.read_model(api, scenario["line"]["model"]["id"])
    assert reserved["repair_kit_stock_qty"] == 3

    unit = fixtures.service_action(
        api, scenario["unit"]["id"], "ABORT", coordinator_user_id="fsc-2"
    )

    assert unit["service_status"] == ServiceStatus.NONE
    assert unit["reserved_kit_qty"] == 0
    assert unit["service_engineer_user_id"] is None
    model = fixtures.read_model(api, scenario["line"]["model"]["id"])
    assert model["repair_kit_stock_qty"] == 5, "The stock the design started with"


def test_05_the_abort_leaves_the_certificate_and_the_build_where_they_were(api):
    """The compensating exit unwinds only the service dimension: nothing was opened in the
    field, so nothing was invalidated.

    PRD §3.9: "Starting the job moves `PARTS_RESERVED → IN_SERVICE`, and this is the second
    coupling into the other two dimensions: a unit at `build_status` `ASSEMBLED` or
    `PACKAGED` falls back to `REWORK`, and a unit at `cert_status` `CERTIFIED` is decertified
    with `decertification_reason` `MANUAL`, running the full decertification tail of §3.7
    including the order hold and the documentation void."

    Design: Difficulty/compensating_invariant/service_abort_restores_repair_kit_stock_unlike_completion
    """
    scenario = _reserved_service_job(api)

    fixtures.service_action(api, scenario["unit"]["id"], "ABORT", coordinator_user_id="fsc-2")

    unit = fixtures.read_unit(api, scenario["unit"]["id"])
    assert_unit_dimensions(
        unit,
        build_status=BuildStatus.PACKAGED,
        cert_status=CertStatus.CERTIFIED,
        service_status=ServiceStatus.NONE,
    )
    assert unit["certified_by_user_id"] == "qm-4"


def test_06_completing_the_job_consumes_the_kits_instead_of_returning_them(api):
    """The asymmetry made explicit: the same two reserved kits come back on an abort and
    are gone for good on a completion, and starting the job costs the certificate.

    PRD §3.9: "Repair-kit stock is therefore conserved across a reserve-then-abort pair and
    permanently reduced across a reserve-then-complete pair." PRD §3.9: "Starting the job
    moves `PARTS_RESERVED → IN_SERVICE`, and this is the second coupling into the other two
    dimensions: a unit at `build_status` `ASSEMBLED` or `PACKAGED` falls back to `REWORK`,
    and a unit at `cert_status` `CERTIFIED` is decertified with `decertification_reason`
    `MANUAL`, running the full decertification tail of §3.7 including the order hold and the
    documentation void."

    Design: Difficulty/compensating_invariant/service_abort_restores_repair_kit_stock_unlike_completion
    """
    scenario = _reserved_service_job(api)

    fixtures.service_action(api, scenario["unit"]["id"], "START", coordinator_user_id="fsc-2")
    unit = fixtures.service_action(
        api, scenario["unit"]["id"], "COMPLETE", coordinator_user_id="fsc-2"
    )

    assert unit["service_status"] == ServiceStatus.SERVICED
    assert unit["reserved_kit_qty"] == 0
    model = fixtures.read_model(api, scenario["line"]["model"]["id"])
    assert model["repair_kit_stock_qty"] == 3, (
        "The fitted kits are not returned, unlike the abort path"
    )
    assert_unit_dimensions(
        unit, build_status=BuildStatus.REWORK, cert_status=CertStatus.DECERTIFIED
    )
    assert unit["decertification_reason"] == "MANUAL"
