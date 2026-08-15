"""Substitution acceptance flow and product trials: windows, SoD, conversion."""
import pytest

from test_helpers import (
    ApiErrorId,
    get_order,
    get_release,
    get_standard,
    get_machine,
    make_blanket_order,
    make_contract,
    make_ehs_officer_headers,
    make_machine,
    make_product,
    make_program_admin_headers,
    make_release,
    make_standard,
    make_trial,
    make_trial_in_evaluation,
    submit_results_payload,
    validate_error,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["program_admin_headers"]
AM = TEST_USERS["account_manager_headers"]
EHS = TEST_USERS["ehs_officer_headers"]


def _setup_pending_substitution(api, sku_old="SA-1", sku_new="SA-2",
                                contract_number="C-SA"):
    p1 = make_product(sku=sku_old, name="Subst Old")
    p2 = make_product(sku=sku_new, name="Subst New", max_operating_speed_rpm=6500)
    contract = make_contract(
        [
            {"product_id": p1["id"], "base_unit_price_cents": 9000},
            {"product_id": p2["id"], "base_unit_price_cents": 9500},
        ],
        customer_ref="PLANT-SA", contract_number=contract_number,
    )
    order = make_blanket_order(contract["id"], p1["id"], committed_qty=50)
    release = make_release(order["id"], order["version"], qty=5,
                           scheduled_ship_date="2026-09-01")
    validate_success(
        api.discontinue_product(p1["id"], {"replacement_product_id": p2["id"]}, ADMIN),
        200,
    )
    return p1, p2, contract, order, release


# ---------------------------------------------------------------------------
# Corner / cross_cutting_layers / substitution_accept_repricing_flow
# ---------------------------------------------------------------------------


def test_substitution_accept_swaps_product_and_restamps(api):
    """PRD §3.1: "the order's `product_id` is swapped to the replacement
    product, `substitution_status` becomes `ACCEPTED`, the order's
    `provisional_unit_price_cents` is re-stamped from the replacement product's
    contract line, `provisional_remaining_value_cents` is recomputed
    accordingly, and each of the order's `ON_HOLD` releases returns to
    `SCHEDULED` with its own `provisional_unit_price_cents` re-stamped by
    evaluating the price at its `scheduled_ship_date` against the replacement
    product's line."

    Design: Corner/cross_cutting_layers/substitution_accept_repricing_flow
    """
    p1, p2, contract, order, release = _setup_pending_substitution(api)
    accepted = validate_success(api.accept_substitution(order["id"], AM), 200)

    assert accepted["product_id"] == p2["id"]
    assert accepted["substitution_status"] == "ACCEPTED"
    assert accepted["provisional_unit_price_cents"] == 9500, (
        f"re-stamped from the replacement line: {accepted['provisional_unit_price_cents']}"
    )
    # remaining 45 x 9500 = 427500
    assert accepted["provisional_remaining_value_cents"] == 427500

    release_after = get_release(release["id"])
    assert release_after["status"] == "SCHEDULED", "ON_HOLD release returns to SCHEDULED"
    assert release_after["provisional_unit_price_cents"] == 9500


def test_substitution_accept_reopens_order_to_new_releases(api):
    """PRD §3.1: "`substitution_status` becomes `ACCEPTED`" — and PRD §3.6's
    release gate "the order's `substitution_status` must be `NONE`
    (`ERR_SUBSTITUTION_PENDING`)" no longer blocks a post-acceptance order,
    whose releases re-price from the replacement product's line (PRD §3.6:
    "the release's `provisional_unit_price_cents` is stamped by evaluating the
    price at its `scheduled_ship_date`").

    Design: Corner/cross_cutting_layers/substitution_accept_repricing_flow
    """
    p1, p2, contract, order, release = _setup_pending_substitution(
        api, sku_old="SA-3", sku_new="SA-4", contract_number="C-SA2"
    )
    accepted = validate_success(api.accept_substitution(order["id"], AM), 200)

    new_release = make_release(order["id"], accepted["version"], qty=2,
                               scheduled_ship_date="2026-09-01")
    assert new_release["id"], "new release on the ACCEPTED order succeeds"
    assert new_release["provisional_unit_price_cents"] == 9500, (
        f"new release prices from the replacement line: "
        f"{new_release['provisional_unit_price_cents']}"
    )


# ---------------------------------------------------------------------------
# Difficulty / resource_temporal_overlap / trial_window_buffer_conflict_rule
# ---------------------------------------------------------------------------


def test_trial_window_one_full_day_buffer_allowed(api):
    """PRD §3.8: "the program requires a buffer of at least one full calendar
    day between trials on the same machine — overlapping windows, abutting
    windows, and windows separated by less than one full day are all rejected
    with `ERR_TRIAL_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/trial_window_buffer_conflict_rule
    """
    product = make_product(sku="CB-TW", name="Trial Disc")
    machine = make_machine(customer_ref="PLANT-14", asset_tag="GR-14")
    t1 = make_trial(machine["id"], product["id"],
                    scheduled_start="2026-03-10", scheduled_end="2026-03-12")
    assert t1["status"] == "ACTIVE"

    # Exactly one buffer day (2026-03-13) after T1's closed end 2026-03-12.
    t2 = make_trial(machine["id"], product["id"],
                    scheduled_start="2026-03-14", scheduled_end="2026-03-15")
    assert t2["status"] == "ACTIVE", (
        "one full calendar day of buffer satisfies the rule"
    )


def test_trial_window_zero_day_gap_rejected(api):
    """PRD §3.8: "overlapping windows, abutting windows, and windows separated
    by less than one full day are all rejected with `ERR_TRIAL_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/trial_window_buffer_conflict_rule
    """
    product = make_product(sku="CB-TW2", name="Trial Disc 2")
    machine = make_machine(customer_ref="PLANT-14B", asset_tag="GR-14B")
    make_trial(machine["id"], product["id"],
               scheduled_start="2026-03-10", scheduled_end="2026-03-12")

    # Zero-day gap: 2026-03-13 directly abuts T1's closed end 2026-03-12.
    resp = api.create_trial(
        {
            "machine_id": machine["id"],
            "product_id": product["id"],
            "scheduled_start": "2026-03-13",
            "scheduled_end": "2026-03-14",
        },
        AM,
    )
    validate_error(resp, ApiErrorId.ERR_TRIAL_WINDOW_CONFLICT.value)


# ---------------------------------------------------------------------------
# Corner / state_machines / trial_convert_before_results_rejected
# ---------------------------------------------------------------------------


def test_trial_convert_before_results_rejected(api):
    """PRD §3.8: "Conversion is a `ProgramAdmin` decision on a trial in
    `EVALUATION`" and PRD §2.8 item 6: "trial conversion or rejection only from
    `EVALUATION` ... violations yield `ERR_INVALID_STATE_TRANSITION`, 409".

    Design: Corner/state_machines/trial_convert_before_results_rejected
    """
    product = make_product(sku="TC-1", name="Trial Convert Disc")
    machine = make_machine(customer_ref="PLANT-TC", asset_tag="GR-TC")
    trial = make_trial(machine["id"], product["id"])
    assert trial["status"] == "ACTIVE"

    resp = api.convert_trial(trial["id"], make_program_admin_headers("admin-1"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)


# ---------------------------------------------------------------------------
# Corner / state_machines / trial_double_submit_rejected
# ---------------------------------------------------------------------------


def test_trial_double_submit_rejected(api):
    """PRD §3.8: "Submission requires the trial to be `ACTIVE` (otherwise
    `ERR_INVALID_STATE_TRANSITION`)"

    Design: Corner/state_machines/trial_double_submit_rejected
    """
    ctx = make_trial_in_evaluation(submitter_user_id="ehs-1")
    trial = ctx["trial"]
    assert trial["status"] == "EVALUATION"

    resp = api.submit_trial_results(
        trial["id"],
        submit_results_payload(measured_removal_rate_g_per_min=13.0,
                               parts_per_unit_media=125, cost_per_part_cents=40),
        make_ehs_officer_headers("ehs-1"),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)


# ---------------------------------------------------------------------------
# Corner / rbac / sod_convert_same_user_rejected
# ---------------------------------------------------------------------------


def test_sod_convert_same_user_rejected(api):
    """PRD §3.8: "the converting operator's `X-User-ID` must differ from the
    trial's `results_submitted_by_user_id`; the same person who measured the
    results may not approve the conversion, and an attempt to do so is rejected
    with `ERR_SEPARATION_OF_DUTIES`."

    Design: Corner/rbac/sod_convert_same_user_rejected
    """
    ctx = make_trial_in_evaluation(submitter_user_id="ehs-7")
    trial = ctx["trial"]
    assert trial["status"] == "EVALUATION"
    assert trial["results_submitted_by_user_id"] == "ehs-7"

    # Same person wearing the ProgramAdmin hat.
    resp = api.convert_trial(trial["id"], make_program_admin_headers("ehs-7"))
    validate_error(resp, ApiErrorId.ERR_SEPARATION_OF_DUTIES.value)

    fetched = api.get_trial(trial["id"], ADMIN).json()["data"]
    assert fetched["status"] == "EVALUATION", (
        "rejected conversion must not change the trial's state"
    )


def test_sod_convert_different_user_allowed(api):
    """PRD §3.8: "the converting operator's `X-User-ID` must differ from the
    trial's `results_submitted_by_user_id`" and "A successful conversion moves
    the trial to `CONVERTED`"

    Design: Corner/rbac/sod_convert_same_user_rejected
    """
    ctx = make_trial_in_evaluation(submitter_user_id="ehs-8")
    trial = ctx["trial"]

    converted = validate_success(
        api.convert_trial(trial["id"], make_program_admin_headers("admin-9")), 200
    )
    assert converted["status"] == "CONVERTED"


# ---------------------------------------------------------------------------
# Corner / cross_cutting_layers / conversion_retires_old_standard_creates_new
# ---------------------------------------------------------------------------


def test_conversion_creates_new_standard(api):
    """PRD §3.8: "creates a new usage standard in `ACTIVE` status for the
    trial's `machine_id` and `product_id` with `operation_name` set to
    `TRIAL-CONVERSION`, `standard_qty_per_part` set to 1 divided by the trial's
    `parts_per_unit_media` rounded half-up to 4 decimal places, `effective_from`
    set to the current clock date, and `effective_to` null; points the trial's
    `converted_standard_id` at the new standard"
    PRD §2.4: "At server startup the clock reads exactly `2026-08-01T00:00:00Z`"

    Design: Corner/cross_cutting_layers/conversion_retires_old_standard_creates_new
    """
    product = make_product(sku="CV-1", name="Convert Disc")
    machine = make_machine(customer_ref="PLANT-CV", asset_tag="GR-CV")
    old_standard = make_standard(machine["id"], product["id"],
                                 operation_name="OLD_RATE",
                                 standard_qty_per_part=0.0100,
                                 effective_from="2026-01-01")
    trial = make_trial(machine["id"], product["id"],
                       scheduled_start="2026-09-01", scheduled_end="2026-09-05")
    validate_success(
        api.submit_trial_results(
            trial["id"],
            submit_results_payload(parts_per_unit_media=120),
            make_ehs_officer_headers("ehs-7"),
        ),
        200,
    )

    converted = validate_success(
        api.convert_trial(trial["id"], make_program_admin_headers("admin-1")), 200
    )
    assert converted["status"] == "CONVERTED"
    new_std_id = converted["converted_standard_id"]
    assert new_std_id, "converted_standard_id must be set"

    new_std = get_standard(new_std_id)
    assert new_std["status"] == "ACTIVE"
    # round_half_up(1/120, 4) = 0.0083
    assert new_std["standard_qty_per_part"] == pytest.approx(0.0083, abs=1e-9)
    assert new_std["effective_from"] == "2026-08-01", (
        "effective_from is the current clock date"
    )
    assert new_std["effective_to"] is None
    assert new_std["operation_name"] == "TRIAL-CONVERSION"


def test_conversion_retires_old_standard(api):
    """PRD §3.8: "retires the `ACTIVE` usage standard for the trial's
    machine-and-product pair if one exists, freeing its window"

    Design: Corner/cross_cutting_layers/conversion_retires_old_standard_creates_new
    """
    product = make_product(sku="CV-2", name="Convert Disc 2")
    machine = make_machine(customer_ref="PLANT-CV2", asset_tag="GR-CV2")
    old_standard = make_standard(machine["id"], product["id"],
                                 operation_name="OLD_RATE",
                                 standard_qty_per_part=0.0100,
                                 effective_from="2026-01-01")
    trial = make_trial(machine["id"], product["id"],
                       scheduled_start="2026-09-01", scheduled_end="2026-09-05")
    validate_success(
        api.submit_trial_results(
            trial["id"],
            submit_results_payload(parts_per_unit_media=120),
            make_ehs_officer_headers("ehs-7"),
        ),
        200,
    )

    validate_success(
        api.convert_trial(trial["id"], make_program_admin_headers("admin-1")), 200
    )
    assert get_standard(old_standard["id"])["status"] == "RETIRED", (
        "conversion cascade retires the prior ACTIVE standard"
    )
