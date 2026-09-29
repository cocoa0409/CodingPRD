"""Masking the registers and passing the gauntlet of gates that starts an injection."""

from test_helpers import (
    ADMIN_HEADERS,
    ERR_CERTIFICATION_EXPIRED,
    ERR_COMBUSTION_SAFETY_REQUIRED,
    ERR_MASKING_INCOMPLETE,
    ERR_TECHNICIAN_NOT_CERTIFIED,
    JOB_INJECTING,
    JOB_MASKING,
    JOB_SCHEDULED,
    SEAL_STATUS_SEAL_PENDING,
    SEAL_STATUS_SEALING,
    VERDICT_MARGINAL,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_success,
)


def test_the_first_masking_call_opens_the_masking_phase(api):
    """`SCHEDULED` becomes `MASKING` on the first call and stays there afterwards.

    PRD 3.5: "The first masking call moves the run from `SCHEDULED` to `MASKING` and
    requires the duct system to be `ELIGIBLE`; every subsequent call leaves the run
    in `MASKING`. Each call bumps the run's `version` by 1."

    Design: Corner/state_machines/first_masks_call_moves_seal_job_scheduled_to_masking
    """
    sc = fx.scenario_scheduled_job(api)
    assert sc.seal_job["status"] == JOB_SCHEDULED
    assert sc.seal_job["masked_register_labels"] == []
    assert sc.seal_job["masked_register_count"] == 0
    assert sc.seal_job["version"] == 1

    first = validate_success(
        api.mask_registers(
            sc.seal_job_id, f.masks_payload(["R1", "R2"]), sc.tech_headers
        )
    )
    assert first["status"] == JOB_MASKING
    assert first["masked_register_labels"] == ["R1", "R2"]
    assert first["masked_register_count"] == 2
    assert first["version"] == 2

    second = validate_success(
        api.mask_registers(sc.seal_job_id, f.masks_payload(["R3"]), sc.tech_headers)
    )
    assert second["status"] == JOB_MASKING
    assert second["masked_register_labels"] == ["R1", "R2", "R3"]
    assert second["masked_register_count"] == 3
    assert second["version"] == 3

    duct_system = sc.read_duct_system()
    assert duct_system["seal_status"] == SEAL_STATUS_SEAL_PENDING
    assert duct_system["active_seal_job_id"] == sc.seal_job_id


def test_masking_is_idempotent_per_label_and_keeps_call_order(api):
    """Labels already masked are ignored rather than duplicated.

    PRD 3.5: "the not-yet-present labels are appended to `masked_register_labels` in
    call order while labels already present are ignored rather than duplicated;
    `masked_register_count` is then recomputed as the length of that list."

    Design: Corner/state_machines/repeated_register_labels_are_appended_once_only
    """
    sc = fx.scenario_scheduled_job(api)
    validate_success(
        api.mask_registers(
            sc.seal_job_id, f.masks_payload(["R1", "R2", "R3"]), sc.tech_headers
        )
    )
    again = validate_success(
        api.mask_registers(
            sc.seal_job_id, f.masks_payload(["R2", "R4", "R1"]), sc.tech_headers
        )
    )
    assert again["masked_register_labels"] == ["R1", "R2", "R3", "R4"]
    assert again["masked_register_count"] == 4
    assert again["version"] == 3
    assert again["status"] == JOB_MASKING


def test_a_partly_masked_system_cannot_start_injecting(api):
    """Every register must be masked before sealant flows.

    PRD 3.5: "`masked_register_count` equals the duct system's
    `total_register_count`, with any shortfall — including the case of no registers
    masked at all — reported as `ERR_MASKING_INCOMPLETE`".

    Design: Corner/state_machines/start_injection_with_partial_masking_returns_masking_incomplete
    """
    sc = fx.scenario_scheduled_job(api)
    total = sc.duct_system["total_register_count"]
    partial = f.register_labels(total)[:-1]
    masked = validate_success(
        api.mask_registers(sc.seal_job_id, f.masks_payload(partial), sc.tech_headers)
    )
    assert masked["masked_register_count"] == total - 1

    validate_error(
        api.start_injection(sc.seal_job_id, None, sc.tech_headers),
        ERR_MASKING_INCOMPLETE,
        422,
    )
    assert sc.read_seal_job()["status"] == JOB_MASKING
    duct_system = sc.read_duct_system()
    assert duct_system["seal_status"] == SEAL_STATUS_SEAL_PENDING

    validate_success(
        api.mask_registers(
            sc.seal_job_id, f.masks_payload([f"R{total}"]), sc.tech_headers
        )
    )
    started = validate_success(api.start_injection(sc.seal_job_id, None, sc.tech_headers))
    assert started["status"] == JOB_INJECTING
    assert sc.read_duct_system()["seal_status"] == SEAL_STATUS_SEALING


def test_pre_phase_combustion_coverage_must_reach_the_appliance_count(api):
    """One passing test does not cover two appliances, and `MARGINAL` counts.

    PRD 3.5: "when the project's `gas_appliance_count` is greater than zero, the
    count of `PRE`-phase combustion tests on the project whose verdict is `PASS` or
    `MARGINAL` is at least `gas_appliance_count`. A project with no gas appliances
    needs no combustion coverage to start." PRD 2.12: "Missing coverage is
    `ERR_COMBUSTION_SAFETY_REQUIRED`".

    Design: Corner/validations/pre_combustion_coverage_must_match_gas_appliance_count
    """
    sc = fx.scenario_ready_to_inject(api, project={"gas_appliance_count": 2})
    fx.schedule_seal_job(sc)
    fx.mask_all_registers(sc)
    assert sc.read_project()["gas_appliance_count"] == 2

    validate_error(
        api.start_injection(sc.seal_job_id, None, sc.tech_headers),
        ERR_COMBUSTION_SAFETY_REQUIRED,
        422,
    )

    marginal = fx.add_combustion_test(
        sc, appliance_label="WH-2", spillage_seconds=60, co_ppm_air_free=18.0
    )
    assert marginal["verdict"] == VERDICT_MARGINAL
    started = validate_success(api.start_injection(sc.seal_job_id, None, sc.tech_headers))
    assert started["status"] == JOB_INJECTING

    # A dwelling with no atmospherically vented appliances needs no coverage at all.
    all_electric = fx.scenario_with_baseline(
        api, project={"gas_appliance_count": 0, "address_line": "7 Willow Court"}
    )
    fx.schedule_seal_job(all_electric)
    fx.mask_all_registers(all_electric)
    electric_started = validate_success(
        api.start_injection(
            all_electric.seal_job_id, None, all_electric.tech_headers
        )
    )
    assert electric_started["status"] == JOB_INJECTING


def test_injection_is_blocked_when_the_technicians_certification_has_lapsed(api):
    """The certification is read against the logical clock at the moment of injection.

    PRD 3.5: "the assigned technician's `certification_status` is `ACTIVE` and their
    `certification_expires_at` is strictly after the logical clock". PRD 5 maps that
    failure to `ERR_CERTIFICATION_EXPIRED` (HTTP 422).

    Design: Difficulty/cross_entity_state_dependency/start_injection_blocked_by_expired_technician_certification
    """
    sc = fx.scenario_ready_to_inject(
        api, technician={"certification_expires_at": f.utc(2026, 8, 5)}
    )
    fx.schedule_seal_job(sc)
    masked = fx.mask_all_registers(sc)
    assert masked["masked_register_count"] == sc.duct_system["total_register_count"]

    fx.set_clock(api, f.utc(2026, 8, 6))
    validate_error(
        api.start_injection(sc.seal_job_id, None, sc.tech_headers),
        ERR_CERTIFICATION_EXPIRED,
        422,
    )

    technician = sc.read_technician()
    assert technician["certification_status"] == "ACTIVE"
    assert technician["open_seal_job_count"] == 1

    job = sc.read_seal_job()
    assert job["status"] == JOB_MASKING
    assert job["masked_register_count"] == sc.duct_system["total_register_count"]
    duct_system = sc.read_duct_system()
    assert duct_system["seal_status"] == SEAL_STATUS_SEAL_PENDING
    assert duct_system["active_seal_job_id"] == sc.seal_job_id


def test_an_expiry_landing_exactly_on_the_clock_is_already_expired(api):
    """"Strictly after" makes equality a lapse, and a suspension is a different code.

    PRD 3.5: "the assigned technician's `certification_status` is `ACTIVE` and their
    `certification_expires_at` is strictly after the logical clock"; PRD 3.5 also
    fixes the other branch — "a technician whose `certification_status` is not
    `ACTIVE` yields `ERR_TECHNICIAN_NOT_CERTIFIED`".

    Design: Difficulty/cross_entity_state_dependency/start_injection_blocked_by_expired_technician_certification
    """
    boundary = f.utc(2026, 8, 2, 13, 0)
    sc = fx.scenario_ready_to_inject(
        api, technician={"certification_expires_at": boundary}
    )
    fx.schedule_seal_job(sc)
    fx.mask_all_registers(sc)

    fx.set_clock(api, boundary)
    validate_error(
        api.start_injection(sc.seal_job_id, None, sc.tech_headers),
        ERR_CERTIFICATION_EXPIRED,
        422,
    )

    suspended = validate_success(
        api.record_certification(
            sc.technician_id,
            f.certification_payload(
                certification_status="SUSPENDED",
                certification_expires_at=f.utc(2027, 6, 30),
            ),
            ADMIN_HEADERS,
        )
    )
    assert suspended["certification_status"] == "SUSPENDED"
    validate_error(
        api.start_injection(sc.seal_job_id, None, sc.tech_headers),
        ERR_TECHNICIAN_NOT_CERTIFIED,
        422,
    )

    validate_success(
        api.record_certification(sc.technician_id, f.certification_payload(), ADMIN_HEADERS)
    )
    started = validate_success(api.start_injection(sc.seal_job_id, None, sc.tech_headers))
    assert started["status"] == JOB_INJECTING
    assert sc.read_duct_system()["seal_status"] == SEAL_STATUS_SEALING
