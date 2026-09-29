"""The scrubbing train: what the gas dimension permits, the pinned specification screen,
the two-attempt conditioning budget, and the off-spec re-test cascade."""
from test_helpers import (
    OPERATOR,
    SCHEDULER,
    condition_gas,
    confirm_nomination,
    create_nomination,
    setup_closed_day,
    setup_pipeline_spec_day,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_01_reconditioning_without_an_interconnect_does_not_spend_an_attempt(api):
    """With no pipeline specification on file there is nothing to screen against.

    PRD: "A `RECONDITION` pass additionally requires that an `InterconnectAgreement` for the day's facility exists in `ACTIVE` status, or the request is rejected with `ERR_NO_ACTIVE_INTERCONNECT`, and that `conditioning_attempts` is still below two — a third reconditioning pass on the same day is rejected with `ERR_CONDITIONING_ATTEMPTS_EXHAUSTED`."

    Design: Corner/state_machines/sm_condition_gas_without_an_active_interconnect_is_rejected
    """
    plant = setup_closed_day()

    validate_error(
        api.condition_gas(
            plant["ops_day"]["id"],
            {
                "disposition": "RECONDITION",
                "treated_ch4_pct": 96.5,
                "treated_co2_pct": 1.5,
                "treated_h2s_ppm": 3.5,
                "treated_moisture_lb_per_mmscf": 5.0,
            },
            OPERATOR,
        ),
        "ERR_NO_ACTIVE_INTERCONNECT",
        409,
    )

    ops_day = validate_success(api.get_ops_day(plant["ops_day"]["id"], OPERATOR))
    assert ops_day["gas_state"] == "RAW"
    assert ops_day["conditioning_attempts"] == 0
    assert ops_day["pipeline_gas_mmbtu"] == 0.000


def test_02_raw_gas_can_be_neither_flared_nor_nominated(api):
    """The same RAW state blocks the flare stack and the pipeline for different reasons.

    PRD: "Conditioning requires that the day's `gas_state` be `RAW`, `PIPELINE_SPEC` or `OFFSPEC` for a `RECONDITION` disposition, or exactly `OFFSPEC` for a `FLARE` disposition; anything else is rejected with `ERR_GAS_NOT_CONDITIONABLE`."

    Design: Corner/validations/validation_gas_state_gates_flaring_and_nominating
    """
    plant = setup_closed_day(with_interconnect=True)

    validate_error(
        api.condition_gas(plant["ops_day"]["id"], {"disposition": "FLARE"}, OPERATOR),
        "ERR_GAS_NOT_CONDITIONABLE",
        409,
    )
    validate_error(
        api.create_nomination(
            {
                "interconnect_id": plant["interconnect"]["id"],
                "ops_day_id": plant["ops_day"]["id"],
                "window_start_utc": "2026-08-04T06:00:00Z",
                "window_end_utc": "2026-08-04T18:00:00Z",
                "nominated_mmbtu": 50.000,
            },
            SCHEDULER,
        ),
        "ERR_GAS_NOT_PIPELINE_SPEC",
        409,
    )

    ops_day = validate_success(api.get_ops_day(plant["ops_day"]["id"], OPERATOR))
    assert ops_day["gas_state"] == "RAW"
    assert ops_day["conditioning_attempts"] == 0


def test_03_the_first_failing_specification_names_the_offspec_reason(api):
    """Sulfide and carbon dioxide both fail, and only the sulfide is reported.

    PRD: "Second, the specification screen, evaluated against the selected interconnection agreement in a pinned order where the **first** failure wins and no later test is consulted."

    Design: Corner/calculations/calc_offspec_reason_takes_the_first_failure_in_the_pinned_screen_order
    """
    plant = setup_closed_day(with_interconnect=True)

    ops_day = validate_success(
        api.condition_gas(
            plant["ops_day"]["id"],
            {
                "disposition": "RECONDITION",
                "treated_ch4_pct": 96.5,
                "treated_co2_pct": 5.0,
                "treated_h2s_ppm": 6.0,
                "treated_moisture_lb_per_mmscf": 5.0,
            },
            OPERATOR,
        )
    )
    assert ops_day["gas_state"] == "OFFSPEC"
    assert ops_day["offspec_reason"] == "H2S"
    assert ops_day["pipeline_hhv_btu_per_scf"] == 974.65
    assert ops_day["pipeline_gas_mmbtu"] == 0.000
    assert ops_day["conditioning_attempts"] == 1


def test_04_a_failed_re_test_rejects_every_open_nomination_and_suspends_the_pipeline(api):
    """One bad laboratory re-test wipes out the whole day's injection schedule.

    PRD: "Because the day has gone off specification, every `InjectionNomination` drawing on that day whose status is `NOMINATED` or `CONFIRMED` moves to the terminal `REJECTED_OFFSPEC` state."

    Design: Corner/state_machines/sm_offspec_retest_rejects_every_open_nomination_and_suspends_the_interconnect
    """
    plant = setup_pipeline_spec_day()
    first = create_nomination(
        plant["interconnect"]["id"],
        plant["ops_day"]["id"],
        window_start_utc="2026-08-04T06:00:00Z",
        window_end_utc="2026-08-04T18:00:00Z",
        nominated_mmbtu=60.000,
    )
    confirm_nomination(first["id"])
    second = create_nomination(
        plant["interconnect"]["id"],
        plant["ops_day"]["id"],
        window_start_utc="2026-08-04T19:00:00Z",
        window_end_utc="2026-08-04T23:00:00Z",
        nominated_mmbtu=30.000,
    )
    third = create_nomination(
        plant["interconnect"]["id"],
        plant["ops_day"]["id"],
        window_start_utc="2026-08-05T00:00:00Z",
        window_end_utc="2026-08-05T04:00:00Z",
        nominated_mmbtu=30.000,
    )

    ops_day = validate_success(
        api.condition_gas(
            plant["ops_day"]["id"],
            {
                "disposition": "RECONDITION",
                "treated_ch4_pct": 96.5,
                "treated_co2_pct": 1.5,
                "treated_h2s_ppm": 6.0,
                "treated_moisture_lb_per_mmscf": 5.0,
            },
            OPERATOR,
        )
    )
    assert ops_day["gas_state"] == "OFFSPEC"
    assert ops_day["offspec_reason"] == "H2S"
    assert ops_day["pipeline_gas_mmbtu"] == 0.000
    assert ops_day["conditioning_attempts"] == 2

    rows, meta = validate_paginated(
        api.list_nominations(
            SCHEDULER,
            {
                "interconnect_id": plant["interconnect"]["id"],
                "status": "REJECTED_OFFSPEC",
                "limit": 10,
                "offset": 0,
            },
        )
    )
    assert meta["total_count"] == 3
    assert len(rows) == 3
    for nomination_id in (first["id"], second["id"], third["id"]):
        rejected = validate_success(api.get_nomination(nomination_id, SCHEDULER))
        assert rejected["status"] == "REJECTED_OFFSPEC"

    interconnect = validate_success(
        api.get_interconnect(plant["interconnect"]["id"], SCHEDULER)
    )
    assert interconnect["curtailment_count"] == 3
    assert interconnect["status"] == "SUSPENDED"


def test_05_a_third_reconditioning_pass_exhausts_the_attempt_budget(api):
    """Passes are counted, not failures, so even clean gas is refused on the third try.

    PRD: "A `RECONDITION` pass additionally requires that an `InterconnectAgreement` for the day's facility exists in `ACTIVE` status, or the request is rejected with `ERR_NO_ACTIVE_INTERCONNECT`, and that `conditioning_attempts` is still below two — a third reconditioning pass on the same day is rejected with `ERR_CONDITIONING_ATTEMPTS_EXHAUSTED`."

    Design: Corner/validations/validation_third_reconditioning_attempt_exhausts_the_budget
    """
    plant = setup_pipeline_spec_day()
    off_spec = condition_gas(plant["ops_day"]["id"], treated_h2s_ppm=6.0)
    assert off_spec["gas_state"] == "OFFSPEC"
    assert off_spec["conditioning_attempts"] == 2

    validate_error(
        api.condition_gas(
            plant["ops_day"]["id"],
            {
                "disposition": "RECONDITION",
                "treated_ch4_pct": 96.5,
                "treated_co2_pct": 1.5,
                "treated_h2s_ppm": 2.0,
                "treated_moisture_lb_per_mmscf": 4.0,
            },
            OPERATOR,
        ),
        "ERR_CONDITIONING_ATTEMPTS_EXHAUSTED",
        422,
    )

    ops_day = validate_success(api.get_ops_day(plant["ops_day"]["id"], OPERATOR))
    assert ops_day["conditioning_attempts"] == 2
    assert ops_day["gas_state"] == "OFFSPEC"
    assert ops_day["offspec_reason"] == "H2S"
    assert ops_day["pipeline_gas_mmbtu"] == 0.000
