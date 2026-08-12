"""Cruise creation, reconciliation, certification, and volume math (PRD §3.2)."""
from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import (
    ApiErrorId,
    PINE_PLOTS_4,
    PINE_PLOTS_5_HIGH_VAR,
    PINE_PLOTS_6,
    TEST_USERS,
    assert_cruise,
    create_cruise_payload,
    create_forester_payload,
    create_landowner_payload,
    create_prescription_payload,
    create_stand_payload,
    create_tract_payload,
    make_forester_headers,
    setup_reconciled_cruise,
    setup_tract_and_stand,
)

ADMIN = TEST_USERS["admin_headers"]


def test_cruise_initial_state_draft(api):
    """PRD §3.2: "The cruise is born in `DRAFT`, and the system derives
    `n_plots`, the count of distinct plot numbers in the tally."

    Design: Corner/state_machines/cruise_initial_state_draft
    """
    base = setup_tract_and_stand()
    fh = base["forester_headers"]
    cruise = validate_success(api.create_cruise(
        create_cruise_payload(stand_id=base["stand"]["id"],
                              plots=[{"plot_number": 1, "species": "PINE", "volume_bf": 1165}]),
        fh,
    ), 201)
    assert_cruise(cruise)
    assert cruise["status"] == "DRAFT"
    assert cruise["n_plots"] == 1
    assert cruise["certified_volume_bf"] is None
    assert cruise["sampling_error_pct"] is None


def test_certify_from_draft_returns_invalid_transition(api):
    """PRD §3.2: "The cruise must be `RECONCILED`."

    Design: Corner/state_machines/certify_from_draft_returns_invalid_transition
    """
    base = setup_tract_and_stand()
    fh = base["forester_headers"]
    cruise = get_success_data(api.create_cruise(
        create_cruise_payload(stand_id=base["stand"]["id"],
                              plots=[{"plot_number": 1, "species": "PINE", "volume_bf": 1165}]),
        fh,
    ))
    stand = get_success_data(api.get_stand(base["stand"]["id"], fh))
    resp = api.certify_cruise(cruise["id"], {"expected_stand_version": stand["version"]}, fh)
    validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION)


def test_cruise_provisional_vs_certified_volumes(api):
    """PRD §3.2: "The **provisional** estimate, `provisional_volume_bf`, is
    the advertised rough figure: the sum of per-plot totals across *all*
    tallied plots — reconciled or not — multiplied by the `expansion_factor`,
    rounded half up to a whole board foot."
    PRD §3.2: "The `certified_volume_bf` is then the base multiplied by one
    minus the (rounded) sampling error expressed as a fraction — that is,
    base × (1 − `sampling_error_pct`/100) — rounded half up to a whole board
    foot."

    Design: Difficulty/dual_variant_calc/cruise_volume_provisional_vs_certified
    """
    base = setup_reconciled_cruise(plots=PINE_PLOTS_6,
                                   reconciled_plot_numbers=[1, 2, 3, 4, 5, 6])
    cruise = base["cruise"]
    assert cruise["provisional_volume_bf"] == 306250, (
        f"provisional 306250 expected, got {cruise['provisional_volume_bf']}"
    )
    assert cruise["certified_volume_bf"] == 300125, (
        f"certified 300125 expected, got {cruise['certified_volume_bf']}"
    )
    assert cruise["sampling_error_pct"] == 2.00, (
        f"sampling_error 2.00 expected, got {cruise['sampling_error_pct']}"
    )
    assert cruise["certified_volume_bf"] < cruise["provisional_volume_bf"]
    assert cruise["certified_volume_by_species"] == [
        {"species": "PINE", "volume_bf": 300125}
    ]


def test_cruise_provisional_strictly_greater_than_certified(api):
    """PRD §3.2: "Because of the sampling deduction, identical tallies always
    yield a certified volume strictly smaller than the provisional one whenever
    `sampling_error_pct` exceeds zero."

    Design: Difficulty/dual_variant_calc/cruise_volume_provisional_vs_certified
    """
    base = setup_reconciled_cruise(plots=PINE_PLOTS_6,
                                   reconciled_plot_numbers=[1, 2, 3, 4, 5, 6])
    cruise = base["cruise"]
    assert cruise["sampling_error_pct"] > 0
    assert cruise["certified_volume_bf"] < cruise["provisional_volume_bf"]


def test_certify_rejected_when_sampling_error_too_high(api):
    """PRD §3.2: "a `sampling_error_pct` above 10.00 is rejected with
    `ERR_SAMPLING_ERROR_TOO_HIGH` (HTTP 422)."

    Design: Corner/calculations/certify_rejected_when_sampling_error_too_high
    """
    base = setup_reconciled_cruise(plots=PINE_PLOTS_5_HIGH_VAR,
                                   reconciled_plot_numbers=[1, 2, 3, 4, 5])
    fh = base["forester_headers"]
    cruise = base["cruise"]
    assert cruise["sampling_error_pct"] == 48.40
    stand = get_success_data(api.get_stand(base["stand"]["id"], fh))
    resp = api.certify_cruise(cruise["id"], {"expected_stand_version": stand["version"]}, fh)
    validate_error(resp, ApiErrorId.ERR_SAMPLING_ERROR_TOO_HIGH)


def test_certify_rejected_when_min_plots_not_met(api):
    """PRD §3.2: "The number of reconciled plots must be at least 5 — fewer is
    rejected with `ERR_MIN_PLOTS_NOT_MET` (HTTP 422)."

    Design: Corner/calculations/certify_rejected_when_min_plots_not_met
    """
    base = setup_reconciled_cruise(plots=PINE_PLOTS_4,
                                   reconciled_plot_numbers=[1, 2, 3, 4])
    fh = base["forester_headers"]
    cruise = base["cruise"]
    stand = get_success_data(api.get_stand(base["stand"]["id"], fh))
    resp = api.certify_cruise(cruise["id"], {"expected_stand_version": stand["version"]}, fh)
    validate_error(resp, ApiErrorId.ERR_MIN_PLOTS_NOT_MET)
