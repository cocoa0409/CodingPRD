"""Corner queue — calculations section: hourly-appointment rounding precision,
the REACH classification below 0.20, and list_locked staying false when no
SELECTED item is a SAFETY.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    make_counselor_headers,
)
from test_helpers import fixtures as fx
from test_helpers import factories as f


def test_appointment_billed_amount_single_end_rounding(api):
    """PRD §3.8: "`amount_cents` equal to `billed_minutes` divided by 60 and
    multiplied by the contract's `hourly_rate_cents`, rounded half up to a whole
    number of cents in a single final rounding step (never per-minute)."
    PRD §2.8: "the result is rounded half up to a whole number of cents in a
    single rounding step at the end of the calculation, never by rounding
    intermediate factors first."

    Design: Corner/calculations/appointment_billed_amount_rounding_10min
    """
    counselor, student, contract = fx.setup_active_contract(
        billing_model="HOURLY",
        contract_overrides={"hourly_rate_cents": 10000, "retainer_deposit_cents": 5000},
    )
    ch = make_counselor_headers(counselor["id"])
    appt = get_success_data(
        api_client.create_appointment(
            f.create_appointment_payload(student["id"], "2026-05-04T09:00:00Z",
                                         "2026-05-04T09:10:00Z", "CHECK_IN"),
            ch,
        )
    )
    fx.set_clock("2026-05-04T09:30:00Z")
    completed = validate_success(api.complete_appointment(appt["id"], ch))
    assert completed["billed_minutes"] == 10
    contract_after = validate_success(api.get_contract(contract["id"], ch))
    # round_half_up(10/60 * 10000) = round_half_up(1666.66..) = 1667.
    assert contract_after["charged_cents"] == 1667, (
        f"single end-rounding should give 1667, not 1666; got {contract_after['charged_cents']}"
    )
    assert contract_after["retainer_balance_cents"] == 3333


def test_classification_reach_below_020(api):
    """PRD §3.4: "when the gap is −100 or less the multiplier is 0.5."
    PRD §3.2: "if it is 0.60 or greater the item is a `SAFETY`; if it is strictly
    below 0.20 it is a `REACH`; otherwise — that is, from 0.20 up to but not
    including 0.60 — it is a `TARGET`."

    Design: Corner/calculations/classification_reach_below_020
    """
    # gpa 3.5 (gpa_c 35.0), sat 1200 (sat_c 20.0) => academics 55.0; tier3 2x20 => resume 0.16 => 55.16.
    counselor, student = fx.setup_onboarded_student(
        student_overrides={"gpa": 3.5, "sat_total": 1200},
        activity_overrides={"hours_per_week": 2, "weeks_per_year": 20, "tier": 3, "category": "ARTS"},
    )
    ch = make_counselor_headers(counselor["id"])
    # admit_rate 0.08, median_sat 1500, sat 1200 => gap -300 => mult 0.5;
    # strength_bonus = (55.16-50)/100*0.3 = 0.01548; raw = 0.08*0.5 + 0.01548 = 0.05548 -> 0.0555.
    item = validate_success(
        api.create_school_list_item(
            f.create_school_list_item_payload(student["id"], school_name="Reach U",
                                              admit_rate=0.08, median_sat=1500),
            ch,
        ),
        expected_status=201,
    )
    assert item["admit_probability"] == 0.0555, (
        f"admit_probability should be 0.0555; got {item['admit_probability']}"
    )
    assert item["classification"] == "REACH"


def test_list_lock_false_when_no_safety(api):
    """PRD §3.2: "The list is locked — `list_locked` becomes true — exactly when
    there is at least one `SAFETY`, the total selected count is at least 3, and
    the number of `ED` selections is at most 1; otherwise `list_locked` is false."

    Design: Corner/calculations/list_lock_false_when_no_safety
    """
    counselor, student = fx.setup_onboarded_student(
        student_overrides={"gpa": 3.5, "sat_total": 1300}
    )
    ch = make_counselor_headers(counselor["id"])
    version = student["version"]

    def add_and_select(name, admit_rate, median_sat, expected_version):
        item = get_success_data(
            api_client.create_school_list_item(
                f.create_school_list_item_payload(student["id"], school_name=name,
                                                  admit_rate=admit_rate, median_sat=median_sat,
                                                  round="RD"),
                ch,
            )
        )
        get_success_data(
            api_client.select_school_list_item(
                item["id"], {"expected_student_version": expected_version}, ch
            )
        )
        return expected_version + 1

    # Three items, none a SAFETY (all TARGET/REACH): n_total>=3 but n_safety==0 => lock false.
    version = add_and_select("T1", 0.40, 1300, version)
    version = add_and_select("T2", 0.35, 1320, version)
    version = add_and_select("R1", 0.10, 1550, version)

    student_after = validate_success(api.get_student(student["id"], ch))
    assert student_after["list_locked"] is False, (
        "three selected items with no SAFETY must keep list_locked false"
    )
