"""Reads, filtered child collections, computed projections and action endpoints."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions, factories as f, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import CLOCK_START_RENDERED, TEST_DEFAULTS
from test_helpers.test_users import (
    MANAGER_A_HEADERS,
    OPTICIAN_A_HEADERS,
    TECHNICIAN_A_HEADERS,
    make_prescriber_headers,
)

MISCLAIMED_NPI = "9999999999"
ATTESTATION_STATEMENT = "I issued this prescription on 2026-03-01 as written."
SELF_PAY_GROSS = 26985


def _two_registered_patients(api):
    """One plan-attached patient and one self-pay patient."""
    fixtures.set_clock(api)
    plan = fixtures.create_basic_plan(api)
    insured = fixtures.create_insured_patient(api, plan["id"])
    self_pay = fixtures.create_self_pay_patient(api)
    return {
        "plan_id": plan["id"],
        "insured_id": insured["id"],
        "self_pay_id": self_pay["id"],
    }


def _prescription_with_a_mistyped_npi_claim(api):
    """The paper prescription claims an NPI the prescriber record does not hold."""
    fixtures.set_clock(api)
    prescriber = fixtures.create_prescriber(api)
    patient = fixtures.create_self_pay_patient(api)
    prescription = validate_success(
        api.create_prescription(
            f.create_prescription_payload(
                patient["id"],
                prescriber["id"],
                prescriber_npi_claimed=MISCLAIMED_NPI,
            ),
            OPTICIAN_A_HEADERS,
        ),
        expected_status=201,
    )
    assert prescriber["npi"] == TEST_DEFAULTS["npi_primary"]
    return {
        "prescriber_id": prescriber["id"],
        "patient_id": patient["id"],
        "prescription_id": prescription["id"],
    }


def _retraced_order(api):
    """A 58.0 mm trace superseded by a 60.0 mm one on a wider frame."""
    scenario = fixtures.stock_layout_ready_order(api)
    assert scenario["layout"]["required_blank_diameter_mm"] == 58.0
    assert scenario["order_version"] == 2
    second = validate_success(
        api.create_frame_layout(
            f.create_frame_layout_payload(
                scenario["order_id"], scenario["order_version"], ed_mm=54.0
            ),
            OPTICIAN_A_HEADERS,
        ),
        expected_status=201,
    )
    scenario["first_layout_id"] = scenario["layout_id"]
    scenario["second_layout"] = second
    scenario["second_layout_id"] = second["id"]
    return scenario


def test_reading_an_insured_patient_echoes_every_registered_field(api):
    """Standing and the rolling consumption are server-initialised, not supplied.

    PRD 3.1: "A new patient begins with `status` of `ACTIVE` — the field admits only
    `ACTIVE` or `INACTIVE` — and with `benefit_used_cents` of 0."

    Design: Corner/endpoints/patient_creation_read_and_listing_round_trip
    """
    scenario = _two_registered_patients(api)

    patient = validate_success(
        api.get_patient(scenario["insured_id"], OPTICIAN_A_HEADERS)
    )

    assert patient["full_name"] == TEST_DEFAULTS["insured_patient_name"]
    assert patient["date_of_birth"] == TEST_DEFAULTS["insured_patient_dob"]
    assert patient["member_number"] == TEST_DEFAULTS["member_number"]
    assert patient["benefit_period_start"] == "2026-01-01"
    assert patient["insurance_plan_id"] == scenario["plan_id"]
    assert patient["status"] == "ACTIVE"
    assert patient["benefit_used_cents"] == 0
    assert patient["version"] == 1
    assert patient["created_at"] == CLOCK_START_RENDERED
    assertions.assert_patient(patient)

    self_pay = validate_success(
        api.get_patient(scenario["self_pay_id"], OPTICIAN_A_HEADERS)
    )
    assert self_pay["insurance_plan_id"] is None
    assert self_pay["member_number"] is None


def test_the_patient_list_reports_the_plan_filter_and_the_pagination_block(api):
    """Two rows, the default page window in meta and one row under the filter.

    PRD 2.3: "Every collection read accepts two query parameters. `limit` controls page
    size: it defaults to 10, may be no smaller than 1 and no larger than 100. `offset`
    controls the starting position: it defaults to 0 and may be no smaller than 0."

    Design: Corner/endpoints/patient_creation_read_and_listing_round_trip
    """
    scenario = _two_registered_patients(api)

    rows, meta = validate_paginated(api.list_patients(OPTICIAN_A_HEADERS))

    assert len(rows) == 2
    assert meta["total_count"] == 2
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["has_more"] is False

    filtered, filtered_meta = validate_paginated(
        api.list_patients(OPTICIAN_A_HEADERS, {"insurance_plan_id": scenario["plan_id"]})
    )
    assert filtered_meta["total_count"] == 1
    assert filtered[0]["id"] == scenario["insured_id"]


def test_optician_verification_is_refused_on_a_mistyped_npi_claim(api):
    """The claimed identity has to match the filed identity digit for digit.

    PRD 3.2: "Fourth, and on optician verification only, the record-match gate: if
    `prescriber_npi_claimed` differs from the prescriber's `npi`, or
    `prescriber_license_state_claimed` differs from the prescriber's `license_state`,
    the request is rejected with `ERR_PRESCRIBER_RECORD_MISMATCH`."

    Design: Corner/endpoints/prescriber_attestation_verifies_despite_a_mismatched_claimed_npi
    """
    scenario = _prescription_with_a_mistyped_npi_claim(api)

    validate_error(
        api.verify_prescription(
            scenario["prescription_id"],
            f.create_verification_payload(),
            OPTICIAN_A_HEADERS,
        ),
        ApiErrorId.PRESCRIBER_RECORD_MISMATCH.value,
        422,
    )

    prescription = fixtures.read_prescription(api, scenario["prescription_id"])
    assert prescription["verification_status"] == "UNVERIFIED"
    assert prescription["verified_at"] is None
    assert fixtures.read_prescriber(api, scenario["prescriber_id"])[
        "verified_rx_count"
    ] == 0


def test_attestation_verifies_the_same_prescription_and_stores_the_statement(api):
    """The prescriber's own word replaces the comparison it would have failed.

    PRD 3.2: "Self-attestation by the `Prescriber` role also advances `UNVERIFIED →
    VERIFIED`, sets `verified_at` to the logical clock, sets `verification_note` to the
    mandatory `attestation_statement` from the request, and likewise recomputes
    `verified_rx_count`; it deliberately skips the NPI and license-state comparison,
    because the acting identity *is* the prescriber record that the comparison would
    consult."

    Design: Corner/endpoints/prescriber_attestation_verifies_despite_a_mismatched_claimed_npi
    """
    scenario = _prescription_with_a_mistyped_npi_claim(api)
    validate_error(
        api.verify_prescription(
            scenario["prescription_id"],
            f.create_verification_payload(),
            OPTICIAN_A_HEADERS,
        ),
        ApiErrorId.PRESCRIBER_RECORD_MISMATCH.value,
        422,
    )

    attested = validate_success(
        api.attest_prescription(
            scenario["prescription_id"],
            {"attestation_statement": ATTESTATION_STATEMENT},
            make_prescriber_headers(scenario["prescriber_id"]),
        )
    )

    assert attested["verification_status"] == "VERIFIED"
    assert attested["verified_at"] == CLOCK_START_RENDERED
    assert attested["verification_note"] == ATTESTATION_STATEMENT
    assert attested["prescriber_npi_claimed"] == MISCLAIMED_NPI
    assert fixtures.read_prescriber(api, scenario["prescriber_id"])[
        "verified_rx_count"
    ] == 1


def test_the_layout_history_returns_the_layout_of_record_first(api):
    """Both traces survive, but only the newest one is still COMPUTED.

    PRD 2.3: "Two reads deviate deliberately and say so in their own description: the
    per-order layout history is returned newest first, so that the layout of record is
    the first row a caller sees, and the per-order money ledger is returned in
    `effective_at` order, oldest movement first, because a ledger read out of sequence
    is useless."

    Design: Corner/endpoints/retrace_supersedes_the_first_layout_and_both_list_under_the_order
    """
    scenario = _retraced_order(api)
    assert scenario["second_layout"]["required_blank_diameter_mm"] == 60.0

    rows, meta = validate_paginated(
        api.list_order_frame_layouts(scenario["order_id"], TECHNICIAN_A_HEADERS)
    )

    assert meta["total_count"] == 2
    assert rows[0]["id"] == scenario["second_layout_id"]
    assert rows[1]["id"] == scenario["first_layout_id"]

    first = fixtures.read_layout(api, scenario["first_layout_id"])
    assert first["layout_status"] == "SUPERSEDED"
    assert first["required_blank_diameter_mm"] == 58.0
    assert scenario["second_layout"]["layout_status"] == "COMPUTED"

    computed, computed_meta = validate_paginated(
        api.list_order_frame_layouts(
            scenario["order_id"], TECHNICIAN_A_HEADERS, {"layout_status": "COMPUTED"}
        )
    )
    assert computed_meta["total_count"] == 1
    assert computed[0]["id"] == scenario["second_layout_id"]

    order = fixtures.read_order(api, scenario["order_id"])
    assert order["version"] == 3
    assert order["fulfillment_status"] == "LAYOUT_READY"


def test_the_charge_summary_recomputes_the_money_block_without_writing(api):
    """The conservation flag is re-derived at read time and the order stands still.

    PRD 2.8: "The per-order charge summary read exposes this directly as
    `invariant_holds`, alongside `gross_charge_cents`, `estimated_benefit_cents`,
    `insurance_benefit_cents`, `patient_portion_cents`, `lab_writeoff_cents`,
    `patient_paid_cents`, `patient_balance_due_cents`, `expedite_fee_cents` and
    `quote_variant`, so that a reconciliation failure is visible without reconstructing
    the arithmetic."

    Design: Corner/endpoints/charge_summary_reports_the_money_block_and_its_conservation_flag
    """
    scenario = fixtures.stock_draft_order(api)

    summary = fixtures.read_charge_summary(api, scenario["order_id"], MANAGER_A_HEADERS)

    assert summary["gross_charge_cents"] == SELF_PAY_GROSS
    assert summary["estimated_benefit_cents"] == 0
    assert summary["insurance_benefit_cents"] == 0
    assert summary["patient_portion_cents"] == SELF_PAY_GROSS
    assert summary["lab_writeoff_cents"] == 0
    assert summary["patient_paid_cents"] == 0
    assert summary["patient_balance_due_cents"] == SELF_PAY_GROSS
    assert summary["expedite_fee_cents"] == 0
    assert summary["quote_variant"] == "PROVISIONAL"
    assert summary["invariant_holds"] is True
    assertions.assert_charge_summary(summary)

    order = fixtures.read_order(api, scenario["order_id"])
    assert order["version"] == scenario["order_version"]
    _, meta = validate_paginated(
        api.list_order_settlement_entries(scenario["order_id"], MANAGER_A_HEADERS)
    )
    assert meta["total_count"] == 0


def test_dispensing_is_refused_while_the_balance_stands(api):
    """The lenses are finished and the quote final, but nothing has been paid.

    PRD 3.9: "The balance gate follows, and a `patient_balance_due_cents` that is not
    exactly 0 yields `ERR_BALANCE_OUTSTANDING` — in either direction, since a positive
    balance is unpaid work and a negative balance means a refund is owed."

    Design: Corner/endpoints/dispense_is_refused_until_the_balance_clears_then_succeeds
    """
    scenario = fixtures.stock_self_pay_final_order(api)
    assert scenario["order"]["billing_status"] == "SELF_PAY_FINAL"
    assert scenario["order"]["patient_balance_due_cents"] == SELF_PAY_GROSS

    validate_error(
        api.dispense_rx_order(scenario["order_id"], OPTICIAN_A_HEADERS),
        ApiErrorId.BALANCE_OUTSTANDING.value,
        409,
    )

    order = fixtures.read_order(api, scenario["order_id"])
    assert order["fulfillment_status"] == "LAB_COMPLETE"
    assert order["billing_status"] == "SELF_PAY_FINAL"


def test_the_identical_dispense_succeeds_once_the_balance_clears(api):
    """One payment for the exact portion flips the same call from refusal to handover.

    PRD 3.9: "A dispensed order moves `LAB_COMPLETE → DISPENSED` and freezes: no
    further fulfillment or billing transition is accepted on it."

    Design: Corner/endpoints/dispense_is_refused_until_the_balance_clears_then_succeeds
    """
    scenario = fixtures.stock_self_pay_final_order(api)
    validate_error(
        api.dispense_rx_order(scenario["order_id"], OPTICIAN_A_HEADERS),
        ApiErrorId.BALANCE_OUTSTANDING.value,
        409,
    )

    paid = validate_success(
        api.settle_patient_portion(
            scenario["order_id"],
            f.create_settlement_payload(SELF_PAY_GROSS),
            OPTICIAN_A_HEADERS,
        )
    )
    assert paid["billing_status"] == "PATIENT_SETTLED"
    assert paid["patient_balance_due_cents"] == 0

    dispensed = validate_success(
        api.dispense_rx_order(scenario["order_id"], OPTICIAN_A_HEADERS)
    )

    assert dispensed["fulfillment_status"] == "DISPENSED"
    assert dispensed["patient_paid_cents"] == SELF_PAY_GROSS
    assert dispensed["insurance_benefit_cents"] == 0
    assert dispensed["lab_writeoff_cents"] == 0

    entries, meta = validate_paginated(
        api.list_order_settlement_entries(scenario["order_id"], OPTICIAN_A_HEADERS)
    )
    assert meta["total_count"] == 2
    assertions.assert_ledger_types_in_order(entries, ["ORDER_CHARGE", "PATIENT_PAYMENT"])
