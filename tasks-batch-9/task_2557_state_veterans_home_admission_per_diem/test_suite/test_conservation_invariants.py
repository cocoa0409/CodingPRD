"""Three quantities are conserved by compensation rather than by correction.

Money in a resident's ledger, beds across a home's units and billable days in a
month are all undone by adding an opposing record rather than by editing or
deleting the original, and each of these tests sums the quantity before and after.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import SECOND_BOM_USER, make_business_office_manager_headers


def _funded_resident_with_a_withdrawal(api):
    """A resident whose ledger holds a deposit and a withdrawal, both by one operator.

    No checkpoint has run, so the ledger contains nothing but the two postings the
    test made, and the reversal can be attributed to a second operator as the
    segregation rule requires.
    """
    scenario = fx.admitted_resident(
        api, admission_date="2026-08-01", care_level="NURSING", licensed_bed_count=2
    )
    fx.set_clock(api, "2026-08-05T00:00:00Z")
    deposit = validate_success(
        fx.post_trust_entry(
            api, scenario.resident_id, "DEPOSIT", 50000, "2026-08-05", "family deposit"
        ),
        201,
    )
    fx.set_clock(api, "2026-08-06T00:00:00Z")
    withdrawal = validate_success(
        fx.post_trust_entry(
            api, scenario.resident_id, "WITHDRAWAL", 12000, "2026-08-06", "hearing aid batteries"
        ),
        201,
    )
    return scenario, deposit, withdrawal


def _reverse(api, transaction_id):
    return validate_success(
        api.reverse_trust_fund_transaction(
            transaction_id,
            f.reversal_payload("posted to wrong resident"),
            make_business_office_manager_headers(SECOND_BOM_USER),
        ),
        201,
    )


def test_the_ledger_replays_a_deposit_and_a_withdrawal_by_sign(api):
    """The two postings carry opposite signs and a running balance.

    Per the PRD: "`signed_amount_cents` is therefore the `amount_cents` itself for a
    `DEPOSIT` or `PNA_CREDIT`, the negation of `amount_cents` for a `WITHDRAWAL` or
    `COST_SHARE_DEBIT`, and, for a `REVERSAL`, the negation of the reversed row's own
    `signed_amount_cents`."

    Design: Difficulty/compensating_invariant/trust_fund_reversal_conserves_balance_exactly
    """
    _scenario, deposit, withdrawal = _funded_resident_with_a_withdrawal(api)

    assert deposit["signed_amount_cents"] == 50000
    assert deposit["balance_after_cents"] == 50000
    assert withdrawal["signed_amount_cents"] == -12000
    assert withdrawal["balance_after_cents"] == 38000


def test_reversing_the_withdrawal_restores_the_pre_withdrawal_balance(api):
    """The compensating row carries the opposite sign and lands back on fifty thousand.

    Per the PRD: "The new row's `balance_after_cents` is computed by the same
    replay, the resident's `trust_fund_balance_cents` is refreshed to the resulting
    balance, and the resident's `version` increments; posting a row and then
    reversing it returns the resident's balance to exactly its pre-posting value."

    Design: Difficulty/compensating_invariant/trust_fund_reversal_conserves_balance_exactly
    """
    scenario, _deposit, withdrawal = _funded_resident_with_a_withdrawal(api)

    reversal = _reverse(api, withdrawal["id"])

    assert reversal["txn_type"] == "REVERSAL"
    assert reversal["signed_amount_cents"] == 12000
    assert reversal["balance_after_cents"] == 50000
    assert reversal["reverses_transaction_id"] == withdrawal["id"]
    assert reversal["reversed"] is False
    assert fx.read_resident(api, scenario.resident_id)["trust_fund_balance_cents"] == 50000


def test_the_reversed_row_stays_in_the_ledger_with_its_own_amount(api):
    """Nothing is deleted or rewritten, so the balance is still the sum of every row.

    Per the PRD: "As a standing invariant, `trust_fund_balance_cents` must always
    equal the sum of `signed_amount_cents` across all of the resident's rows,
    including rows that have been reversed — a reversed row stays in the ledger and
    keeps its own `signed_amount_cents`."

    Design: Difficulty/compensating_invariant/trust_fund_reversal_conserves_balance_exactly
    """
    scenario, _deposit, withdrawal = _funded_resident_with_a_withdrawal(api)
    _reverse(api, withdrawal["id"])

    original = fx.read_transaction(api, withdrawal["id"])
    assert original["reversed"] is True
    assert original["amount_cents"] == 12000
    assert original["signed_amount_cents"] == -12000

    rows = fx.read_transactions(api, resident_id=scenario.resident_id)
    assert len(rows) == 3
    assert sum(row["signed_amount_cents"] for row in rows) == 50000
    assert fx.read_resident(api, scenario.resident_id)["trust_fund_balance_cents"] == 50000


def _resident_and_a_sister_unit(api):
    """One resident in unit A of a home that also has an equally sized unit B."""
    scenario = fx.admitted_resident_with_care_plan(
        api,
        admission_date="2026-08-01",
        care_level="NURSING",
        licensed_bed_count=2,
        out_of_service_bed_count=0,
    )
    target = fx.add_unit(
        api, scenario, care_level="NURSING", licensed_bed_count=2, out_of_service_bed_count=0
    )
    fx.set_clock(api, "2026-08-05T00:00:00Z")
    return scenario, target


def _bed_totals(unit):
    return (
        unit["occupied_bed_count"]
        + unit["held_bed_count"]
        + unit["available_bed_count"]
        + unit["out_of_service_bed_count"]
    )


def test_a_bed_hold_moves_a_bed_between_counts_without_freeing_it(api):
    """Hospitalisation trades an occupied bed for a held one and frees nothing.

    Per the PRD: "The unit-side cascade is a compensating pair:
    `occupied_bed_count` falls by 1 while `held_bed_count` rises by 1, so
    `available_bed_count` does not move at all, and the unit's `version` increments
    alongside the resident's."

    Design: Difficulty/compensating_invariant/transfer_conserves_occupied_plus_held_beds
    """
    scenario, _target = _resident_and_a_sister_unit(api)
    before = fx.read_unit(api, scenario.unit_id)
    assert (before["occupied_bed_count"], before["held_bed_count"], before["available_bed_count"]) == (1, 0, 1)

    validate_success(fx.hospitalize(api, scenario.resident_id, "2026-08-05"), 200)

    after = fx.read_unit(api, scenario.unit_id)
    assert (after["occupied_bed_count"], after["held_bed_count"], after["available_bed_count"]) == (0, 1, 1)
    assert _bed_totals(before) == before["licensed_bed_count"]
    assert _bed_totals(after) == after["licensed_bed_count"]


def test_readmission_reverses_the_compensating_pair(api):
    """Coming back trades the held bed for an occupied one, again freeing nothing.

    Per the PRD: "the compensating pair reverses — `held_bed_count` falls by 1 and
    `occupied_bed_count` rises by 1, again leaving `available_bed_count` unchanged
    — with both the unit's and the resident's `version` incrementing."

    Design: Difficulty/compensating_invariant/transfer_conserves_occupied_plus_held_beds
    """
    scenario, _target = _resident_and_a_sister_unit(api)
    validate_success(fx.hospitalize(api, scenario.resident_id, "2026-08-05"), 200)

    validate_success(
        fx.readmit(api, scenario.resident_id, "2026-08-08", clock="2026-08-08T00:00:00Z"), 200
    )

    unit = fx.read_unit(api, scenario.unit_id)
    assert (unit["occupied_bed_count"], unit["held_bed_count"], unit["available_bed_count"]) == (1, 0, 1)
    assert _bed_totals(unit) == unit["licensed_bed_count"]
    assert fx.read_resident(api, scenario.resident_id)["bed_hold_days_used"] == 3


def test_a_transfer_conserves_the_cross_unit_total_of_occupied_and_held_beds(api):
    """The bed migrates between units; the pair of units still holds exactly one resident.

    Per the PRD: "The cross-unit total of occupied plus held beds is conserved
    exactly." Each unit separately still accounts for all four of its licensed beds.

    Design: Difficulty/compensating_invariant/transfer_conserves_occupied_plus_held_beds
    """
    scenario, target = _resident_and_a_sister_unit(api)
    validate_success(fx.hospitalize(api, scenario.resident_id, "2026-08-05"), 200)
    validate_success(
        fx.readmit(api, scenario.resident_id, "2026-08-08", clock="2026-08-08T00:00:00Z"), 200
    )

    validate_success(fx.transfer(api, scenario.resident_id, target["id"], "2026-08-08"), 200)

    source = fx.read_unit(api, scenario.unit_id)
    assert source["occupied_bed_count"] == 0
    assert source["held_bed_count"] == 0
    assert source["available_bed_count"] == 2
    assert source["out_of_service_bed_count"] == 0
    assert source["licensed_bed_count"] == 2

    moved_into = fx.read_unit(api, target["id"])
    assert moved_into["occupied_bed_count"] == 1
    assert moved_into["held_bed_count"] == 0
    assert moved_into["available_bed_count"] == 1

    occupied_plus_held = (
        source["occupied_bed_count"]
        + source["held_bed_count"]
        + moved_into["occupied_bed_count"]
        + moved_into["held_bed_count"]
    )
    assert occupied_plus_held == 1
    assert fx.read_resident(api, scenario.resident_id)["care_unit_id"] == target["id"]


def _submitted_august_claim(api):
    """A materialised August billed by one submitted claim."""
    scenario = fx.billed_month(
        api, admission_date="2026-08-01", through_date="2026-08-31", care_level="NURSING"
    )
    claim = validate_success(
        fx.open_claim(api, scenario.home_id, scenario.unit_id, "2026-08", "AUDITED_BASIS"), 201
    )
    submitted = validate_success(fx.submit_claim(api, claim["id"]), 200)
    return scenario, submitted


def test_submission_consumes_every_day_of_the_month(api):
    """All thirty-one rows are stamped with the claim and flagged claimed.

    Per the PRD: "sets `per_diem_claim_id` on every attributed census day so that
    each row's `claimed` flag becomes true".

    Design: Difficulty/compensating_invariant/claim_rejection_restores_unclaimed_census_days
    """
    scenario, submitted = _submitted_august_claim(api)

    assert submitted["claim_amount_cents"] == 367567

    rows = fx.read_census_days(api, resident_id=scenario.resident_id)
    assert len(rows) == 31
    for row in rows:
        assert row["claimed"] is True
        assert row["per_diem_claim_id"] == submitted["id"]


def test_rejection_releases_both_stamps_on_every_day(api):
    """The claim is refused and each day is handed back to the pool untouched otherwise.

    Per the PRD: "every attributed census day is released with `per_diem_claim_id`
    set back to null and `claimed` back to false, which returns those days to the
    pool."

    Design: Difficulty/compensating_invariant/claim_rejection_restores_unclaimed_census_days
    """
    scenario, submitted = _submitted_august_claim(api)

    rejected = validate_success(
        fx.adjudicate_claim(
            api,
            submitted["id"],
            "REJECTED",
            rejection_code="CENSUS_MISMATCH",
            note="resident roster mismatch",
        ),
        200,
    )

    assert rejected["status"] == "REJECTED"
    assert rejected["paid_amount_cents"] == 0
    assert rejected["rejection_code"] == "CENSUS_MISMATCH"

    rows = fx.read_census_days(
        api,
        resident_id=scenario.resident_id,
        service_date_from="2026-08-01",
        service_date_to="2026-08-31",
    )
    assert len(rows) == 31
    for row in rows:
        assert row["claimed"] is False
        assert row["per_diem_claim_id"] is None


def test_the_released_days_reprice_identically_on_a_fresh_claim(api):
    """A replacement claim finds the same thirty-one days at the same price.

    Per the PRD: "A `REJECTED` or `VOID` month is free, and its days are back in the
    pool." Nothing about the month was lost by the refusal, which is the point of
    releasing rather than deleting.

    Design: Difficulty/compensating_invariant/claim_rejection_restores_unclaimed_census_days
    """
    scenario, submitted = _submitted_august_claim(api)
    validate_success(
        fx.adjudicate_claim(
            api,
            submitted["id"],
            "REJECTED",
            rejection_code="CENSUS_MISMATCH",
            note="resident roster mismatch",
        ),
        200,
    )

    replacement = validate_success(
        fx.open_claim(api, scenario.home_id, scenario.unit_id, "2026-08", "AUDITED_BASIS"), 201
    )

    assert replacement["resident_day_count"] == 31
    assert replacement["claim_amount_cents"] == 367567
    assert replacement["billable_day_count"] == 31
    assert replacement["census_reported_resident_count"] == 1
