"""Two conserved quantities the API is required to defend exactly.

The first is the sponsor's advance ledger: paying a June claim recovers money out of the sponsor's
outstanding advances through the ordered waterfall, and reopening that paid claim hands every
recovered cent back so the ledger reads identically on both sides of the payment.

The second is a service day's counted meal totals: a miscount is corrected by appending a reversing
entry that contributes negative meals, never by editing or deleting the entry that was wrong, so the
day's published totals stay equal to the signed sum of its immutable entry rows.
"""

from typing import Dict, List

from test_helpers import (
    CLOCK_FIRST_SERVICE_DAY,
    CLOCK_JUNE_CLAIM_WINDOW,
    CLOCK_PROGRAM_INTAKE,
    add_line_item,
    assert_advance_ledger_conserved,
    assert_append_only_row,
    assert_advance_payment,
    assert_day_totals_match_entries,
    assert_meal_claim,
    assert_meal_count_entry,
    assert_meal_service_day,
    assert_sponsor,
    assert_status,
    create_approved_budget,
    create_approved_site,
    create_approved_sponsor,
    create_area_record,
    create_disbursed_advance,
    create_draft_claim,
    create_finalized_day,
    create_meal_count_payload,
    create_open_day,
    create_satisfied_first_week_visit,
    make_site_supervisor_headers,
    make_sponsor_admin_headers,
    make_state_agency_reviewer_headers,
    open_claim_revision,
    pay_claim,
    record_meal_count,
    run_edit_check,
    set_clock,
    setup_program_baseline,
    start_operating,
    submit_claim,
    validate_paginated,
    validate_success,
)

REVIEWER_HEADERS = make_state_agency_reviewer_headers()

# --- The advance-ledger scenario --------------------------------------------------------------

JUNE = "2026-06"
JULY = "2026-07"

# Two disbursed advances, the June one older in request_month than the July one.
JUNE_ADVANCE_CENTS = 30_000
JULY_ADVANCE_CENTS = 25_000
ADVANCE_OUTSTANDING_BEFORE_PAYMENT = 55_000

# One rural SELF_PREP site with a single finalized day of 47 LUNCH first meals.
LUNCH_FIRST_MEALS = 47
CLAIMED_OPERATING_COST_CENTS = 30_000
CLAIMED_ADMIN_COST_CENTS = 6_000

# 47 lunches at the RURAL_OR_SELF_PREP lunch rate, capped operating plus the floored admin cap.
FINAL_REIMBURSEMENT_CENTS = 26_536
JUNE_ADVANCE_OUTSTANDING_AFTER_PAYMENT = 3_464
ADVANCE_OUTSTANDING_AFTER_PAYMENT = 28_464


def _validated_june_claim_over_two_advances() -> dict:
    """An approved sponsor carrying two disbursed advances, whose June claim has passed a clean
    edit check and is waiting to be paid.

    The sponsor's site is approved before either advance is disbursed, because disbursement is
    refused until the sponsor has somewhere to serve meals.
    """
    set_clock(CLOCK_PROGRAM_INTAKE)
    sponsor = create_approved_sponsor()
    create_approved_budget(sponsor["id"])
    area_record = create_area_record()
    site = create_approved_site(sponsor["id"], area_record["id"])

    june_advance = create_disbursed_advance(sponsor["id"], JUNE, JUNE_ADVANCE_CENTS)
    july_advance = create_disbursed_advance(sponsor["id"], JULY, JULY_ADVANCE_CENTS)

    set_clock(CLOCK_FIRST_SERVICE_DAY)
    site = start_operating(site)
    create_finalized_day(site["id"], sponsor["id"], first_meals=LUNCH_FIRST_MEALS)
    create_satisfied_first_week_visit(site["id"])

    set_clock(CLOCK_JUNE_CLAIM_WINDOW)
    claim = create_draft_claim(sponsor["id"], JUNE)
    add_line_item(claim, site["id"])
    claim = submit_claim(
        claim,
        claimed_operating_cost_cents=CLAIMED_OPERATING_COST_CENTS,
        claimed_admin_cost_cents=CLAIMED_ADMIN_COST_CENTS,
    )
    claim = run_edit_check(claim)

    return {
        "sponsor": sponsor,
        "site": site,
        "june_advance": june_advance,
        "july_advance": july_advance,
        "claim": claim,
    }


def _read_advance(api, advance_id: str) -> dict:
    return validate_success(api.get_advance_payment(advance_id, REVIEWER_HEADERS))


def _read_sponsor(api, sponsor_id: str) -> dict:
    return validate_success(
        api.get_sponsor(sponsor_id, make_sponsor_admin_headers(sponsor_id))
    )


def _read_advances(api, sponsor_id: str) -> List[dict]:
    advances, _meta = validate_paginated(
        api.list_advance_payments(REVIEWER_HEADERS, params={"sponsor_id": sponsor_id})
    )
    return advances


# --- The meal-count reversal scenario ----------------------------------------------------------


def _open_day_with_one_original_count() -> dict:
    """An operating rural SELF_PREP site with an OPEN 2026-06-08 day carrying one ORIGINAL entry of
    47 LUNCH first meals against production of 150 lunches."""
    scenario = setup_program_baseline()
    day = create_open_day(scenario["site"]["id"])
    original = record_meal_count(
        day, meal_type="LUNCH", first_meals=LUNCH_FIRST_MEALS, second_meals=0, adult_meals=0
    )
    scenario.update({"day": day, "original": original})
    return scenario


def _post_reversal(api, scenario: dict) -> dict:
    payload = create_meal_count_payload(
        meal_type="LUNCH",
        first_meals=LUNCH_FIRST_MEALS,
        second_meals=0,
        adult_meals=0,
        reversal_of_entry_id=scenario["original"]["id"],
    )
    return validate_success(
        api.create_meal_count(
            scenario["day"]["id"], payload,
            make_site_supervisor_headers(scenario["site"]["id"]),
        ),
        201,
    )


def _read_day(api, scenario: dict) -> dict:
    return validate_success(
        api.get_meal_service_day(
            scenario["day"]["id"], make_site_supervisor_headers(scenario["site"]["id"])
        )
    )


def _read_entries(api, scenario: dict) -> tuple:
    return validate_paginated(
        api.list_meal_count_entries(
            make_site_supervisor_headers(scenario["site"]["id"]),
            params={"meal_service_day_id": scenario["day"]["id"]},
        )
    )


class TestAdvanceLedgerConservedAcrossPaymentAndReversal:
    """A payment that recovers 26536 cents from the older of two advances, then a revision that
    unwinds that recovery to the cent."""

    def test_paying_the_june_claim_recovers_the_oldest_advance_first(self, api):
        """PRD §3.8: "Those candidates are ordered by `request_month` ascending and then, within a month, by `created_at` ascending — never by identifier — so the oldest debt is always recovered first."

        Design: Difficulty/compensating_invariant/advance_recovery_ledger_conserved_across_pay_then_open_revision
        """
        scenario = _validated_june_claim_over_two_advances()
        sponsor_id = scenario["sponsor"]["id"]

        before = _read_sponsor(api, sponsor_id)
        assert before["advance_outstanding_cents"] == ADVANCE_OUTSTANDING_BEFORE_PAYMENT, (
            "the two disbursed advances must leave "
            f"{ADVANCE_OUTSTANDING_BEFORE_PAYMENT} outstanding before the payment, got "
            f"{before['advance_outstanding_cents']}"
        )
        assert before["advance_recovered_cents"] == 0, (
            f"nothing is recovered before the payment, got {before['advance_recovered_cents']}"
        )
        for advance_id in (scenario["june_advance"]["id"], scenario["july_advance"]["id"]):
            advance = _read_advance(api, advance_id)
            assert_status(advance, "DISBURSED")
            assert advance["recovered_amount_cents"] == 0, (
                "a freshly disbursed advance has recovered nothing, got "
                f"{advance['recovered_amount_cents']}"
            )

        paid = pay_claim(scenario["claim"])

        assert_meal_claim(paid)
        assert_status(paid, "PAID")
        assert paid["final_reimbursement_cents"] == FINAL_REIMBURSEMENT_CENTS, (
            f"expected final_reimbursement_cents {FINAL_REIMBURSEMENT_CENTS}, got "
            f"{paid['final_reimbursement_cents']}"
        )
        assert paid["advance_offset_cents"] == FINAL_REIMBURSEMENT_CENTS, (
            "the whole reimbursement is absorbed by the outstanding advances, expected "
            f"advance_offset_cents {FINAL_REIMBURSEMENT_CENTS}, got {paid['advance_offset_cents']}"
        )
        assert paid["net_payable_cents"] == 0, (
            "final reimbursement less an equal offset leaves nothing payable, got "
            f"{paid['net_payable_cents']}"
        )

        june_advance = _read_advance(api, scenario["june_advance"]["id"])
        assert_advance_payment(june_advance)
        assert_status(june_advance, "PARTIALLY_RECOVERED")
        assert june_advance["recovered_amount_cents"] == FINAL_REIMBURSEMENT_CENTS, (
            "the June advance absorbs the whole balance, expected recovered_amount_cents "
            f"{FINAL_REIMBURSEMENT_CENTS}, got {june_advance['recovered_amount_cents']}"
        )
        assert june_advance["outstanding_cents"] == JUNE_ADVANCE_OUTSTANDING_AFTER_PAYMENT, (
            f"expected outstanding_cents {JUNE_ADVANCE_OUTSTANDING_AFTER_PAYMENT} on the partially "
            f"recovered June advance, got {june_advance['outstanding_cents']}"
        )

        july_advance = _read_advance(api, scenario["july_advance"]["id"])
        assert_status(july_advance, "DISBURSED")
        assert july_advance["recovered_amount_cents"] == 0, (
            "allocation stops once the balance is exhausted, so the July advance keeps a "
            f"recovered_amount_cents of 0, got {july_advance['recovered_amount_cents']}"
        )
        assert july_advance["outstanding_cents"] == JULY_ADVANCE_CENTS, (
            f"the untouched July advance still owes {JULY_ADVANCE_CENTS}, got "
            f"{july_advance['outstanding_cents']}"
        )

        sponsor = _read_sponsor(api, sponsor_id)
        assert_sponsor(sponsor)
        assert sponsor["advance_outstanding_cents"] == ADVANCE_OUTSTANDING_AFTER_PAYMENT, (
            f"expected advance_outstanding_cents {ADVANCE_OUTSTANDING_AFTER_PAYMENT} after the "
            f"recovery, got {sponsor['advance_outstanding_cents']}"
        )
        assert sponsor["advance_recovered_cents"] == FINAL_REIMBURSEMENT_CENTS, (
            f"expected advance_recovered_cents {FINAL_REIMBURSEMENT_CENTS}, got "
            f"{sponsor['advance_recovered_cents']}"
        )
        assert sponsor["advance_paid_cents"] == ADVANCE_OUTSTANDING_BEFORE_PAYMENT, (
            "advance_paid_cents is a lifetime total the recovery never reduces, expected "
            f"{ADVANCE_OUTSTANDING_BEFORE_PAYMENT}, got {sponsor['advance_paid_cents']}"
        )
        assert sponsor["reimbursement_paid_cents"] == 0, (
            "a fully offset claim adds nothing to reimbursement_paid_cents, got "
            f"{sponsor['reimbursement_paid_cents']}"
        )

    def test_opening_a_revision_hands_every_recovered_cent_back_to_its_advance(self, api):
        """PRD §3.8: "Every advance this claim recovered from has `recovered_amount_cents` decreased by precisely the amount this claim took from it, applied in the reverse of the allocation order, and each such advance's `status` is recomputed — `DEMAND_ISSUED` when its `demand_issued_at` is not null and its `outstanding_cents` is positive, otherwise `RECOVERED` when `outstanding_cents` has reached 0, otherwise `PARTIALLY_RECOVERED` when `recovered_amount_cents` is still positive, otherwise `DISBURSED`."

        Design: Difficulty/compensating_invariant/advance_recovery_ledger_conserved_across_pay_then_open_revision
        """
        scenario = _validated_june_claim_over_two_advances()
        sponsor_id = scenario["sponsor"]["id"]

        paid = pay_claim(scenario["claim"])
        assert_status(paid, "PAID")

        open_claim_revision(paid, "Post-payment review reopened the June claim for revision.")

        june_advance = _read_advance(api, scenario["june_advance"]["id"])
        assert_advance_payment(june_advance)
        assert june_advance["recovered_amount_cents"] == 0, (
            "the reversal returns every recovered cent, expected recovered_amount_cents 0, got "
            f"{june_advance['recovered_amount_cents']}"
        )
        assert_status(june_advance, "DISBURSED")
        assert june_advance["outstanding_cents"] == JUNE_ADVANCE_CENTS, (
            f"the restored June advance owes its full {JUNE_ADVANCE_CENTS} again, got "
            f"{june_advance['outstanding_cents']}"
        )

        july_advance = _read_advance(api, scenario["july_advance"]["id"])
        assert_status(july_advance, "DISBURSED")
        assert july_advance["recovered_amount_cents"] == 0, (
            "the advance the waterfall never touched is unchanged by the reversal, got "
            f"recovered_amount_cents {july_advance['recovered_amount_cents']}"
        )
        assert july_advance["outstanding_cents"] == JULY_ADVANCE_CENTS, (
            f"expected outstanding_cents {JULY_ADVANCE_CENTS}, got "
            f"{july_advance['outstanding_cents']}"
        )

        sponsor = _read_sponsor(api, sponsor_id)
        assert_sponsor(sponsor)
        assert sponsor["advance_outstanding_cents"] == ADVANCE_OUTSTANDING_BEFORE_PAYMENT, (
            "the reversal restores the ledger with no drift, expected advance_outstanding_cents "
            f"{ADVANCE_OUTSTANDING_BEFORE_PAYMENT}, got {sponsor['advance_outstanding_cents']}"
        )
        assert sponsor["advance_recovered_cents"] == 0, (
            "advance_recovered_cents is reduced by the whole offset, expected 0, got "
            f"{sponsor['advance_recovered_cents']}"
        )
        assert sponsor["reimbursement_paid_cents"] == 0, (
            f"expected reimbursement_paid_cents 0, got {sponsor['reimbursement_paid_cents']}"
        )
        assert sponsor["advance_paid_cents"] == ADVANCE_OUTSTANDING_BEFORE_PAYMENT, (
            "the lifetime disbursed total is untouched by the reversal, expected "
            f"{ADVANCE_OUTSTANDING_BEFORE_PAYMENT}, got {sponsor['advance_paid_cents']}"
        )

    def test_opening_a_revision_clears_the_payment_fields_and_bumps_the_revision_round(self, api):
        """PRD §3.8: "Reopening from `PAID` moves the claim to `REVISION_OPENED`: `revision_round` increases by 1 and every line item resets in exactly the same way, and in addition the payment itself is undone."

        Design: Difficulty/compensating_invariant/advance_recovery_ledger_conserved_across_pay_then_open_revision
        """
        scenario = _validated_june_claim_over_two_advances()

        paid = pay_claim(scenario["claim"])
        assert paid["revision_round"] == 0, (
            f"the claim was never revised before the payment, got {paid['revision_round']}"
        )

        reopened = open_claim_revision(
            paid, "Post-payment review reopened the June claim for revision."
        )

        assert_meal_claim(reopened)
        assert_status(reopened, "REVISION_OPENED")
        assert reopened["revision_round"] == 1, (
            f"reopening a paid claim raises revision_round to 1, got {reopened['revision_round']}"
        )
        for cleared_field in (
            "advance_offset_cents",
            "net_payable_cents",
            "paid_at",
            "final_reimbursement_cents",
        ):
            assert reopened.get(cleared_field) is None, (
                f"{cleared_field} must be cleared to null when the payment is undone, got "
                f"{reopened.get(cleared_field)!r}"
            )

    def test_advance_ledger_invariant_holds_at_every_checkpoint(self, api):
        """PRD §3.8: "The ledger invariant to hold throughout is that the sponsor's `advance_outstanding_cents` equals the sum, over advances in `DISBURSED`, `PARTIALLY_RECOVERED` or `DEMAND_ISSUED`, of each advance's `approved_amount_cents` less its `recovered_amount_cents`."

        Design: Difficulty/compensating_invariant/advance_recovery_ledger_conserved_across_pay_then_open_revision
        """
        scenario = _validated_june_claim_over_two_advances()
        sponsor_id = scenario["sponsor"]["id"]

        assert_advance_ledger_conserved(
            _read_sponsor(api, sponsor_id), _read_advances(api, sponsor_id)
        )

        paid = pay_claim(scenario["claim"])
        after_payment = _read_sponsor(api, sponsor_id)
        assert_advance_ledger_conserved(after_payment, _read_advances(api, sponsor_id))
        assert after_payment["advance_outstanding_cents"] == ADVANCE_OUTSTANDING_AFTER_PAYMENT, (
            f"expected advance_outstanding_cents {ADVANCE_OUTSTANDING_AFTER_PAYMENT} between the "
            f"payment and the revision, got {after_payment['advance_outstanding_cents']}"
        )

        open_claim_revision(paid, "Post-payment review reopened the June claim for revision.")
        after_reversal = _read_sponsor(api, sponsor_id)
        advances = _read_advances(api, sponsor_id)
        assert_advance_ledger_conserved(after_reversal, advances)
        assert after_reversal["advance_outstanding_cents"] == ADVANCE_OUTSTANDING_BEFORE_PAYMENT, (
            "the ledger must read identically before the payment and after the revision, expected "
            f"{ADVANCE_OUTSTANDING_BEFORE_PAYMENT}, got "
            f"{after_reversal['advance_outstanding_cents']}"
        )
        assert sum(advance["recovered_amount_cents"] for advance in advances) == 0, (
            "no orphaned partial recovery may survive the reversal, got recovered amounts "
            f"{[advance['recovered_amount_cents'] for advance in advances]}"
        )


class TestMealCountReversalConservesDayTotals:
    """A REVERSAL entry mirroring a 47-meal ORIGINAL returns the day's counted totals to zero by
    appending a negative row rather than touching the original."""

    def test_reversing_a_meal_count_returns_the_day_counted_totals_to_zero(self, api):
        """PRD §3.6: "Supplying `reversal_of_entry_id` sets the new entry's `entry_kind` to `REVERSAL` and its three counts are applied to the day as negatives; leaving the field out sets `entry_kind` to `ORIGINAL`."

        Design: Difficulty/compensating_invariant/meal_count_reversal_conserves_day_counted_totals
        """
        scenario = _open_day_with_one_original_count()

        original = scenario["original"]
        assert original["entry_kind"] == "ORIGINAL", (
            f"an entry posted without a reversal target is ORIGINAL, got {original['entry_kind']}"
        )
        before = _read_day(api, scenario)
        assert before["counted_first_meals"] == LUNCH_FIRST_MEALS, (
            f"the day counts {LUNCH_FIRST_MEALS} first meals before the reversal, got "
            f"{before['counted_first_meals']}"
        )

        reversal = _post_reversal(api, scenario)

        assert_meal_count_entry(reversal)
        assert reversal["entry_kind"] == "REVERSAL", (
            f"naming a reversal target sets entry_kind to REVERSAL, got {reversal['entry_kind']}"
        )
        assert reversal["reversal_of_entry_id"] == original["id"], (
            f"expected reversal_of_entry_id {original['id']}, got "
            f"{reversal['reversal_of_entry_id']}"
        )

        after = _read_day(api, scenario)
        assert_meal_service_day(after)
        assert after["counted_first_meals"] == 0, (
            "the reversal's 47 first meals are applied to the day as negatives, so "
            f"counted_first_meals returns to 0, got {after['counted_first_meals']}"
        )
        assert after["counted_second_meals"] == 0, (
            f"expected counted_second_meals 0, got {after['counted_second_meals']}"
        )
        assert after["counted_adult_meals"] == 0, (
            f"expected counted_adult_meals 0, got {after['counted_adult_meals']}"
        )

    def test_reversal_entry_records_the_negative_marginal_contribution(self, api):
        """PRD §3.6: "Each individual entry also records its own contribution, and that contribution is a **marginal delta** rather than an independent computation: the day's totals are computed immediately before the entry is inserted and again immediately after, and the entry stores the differences as `reimbursable_first_meals` and `reimbursable_second_meals`."

        Design: Difficulty/compensating_invariant/meal_count_reversal_conserves_day_counted_totals
        """
        scenario = _open_day_with_one_original_count()

        original = scenario["original"]
        assert original["reimbursable_first_meals"] == LUNCH_FIRST_MEALS, (
            f"the ORIGINAL entry contributed {LUNCH_FIRST_MEALS} reimbursable first meals, got "
            f"{original['reimbursable_first_meals']}"
        )

        reversal = _post_reversal(api, scenario)

        assert reversal["reimbursable_first_meals"] == -LUNCH_FIRST_MEALS, (
            "the reversal takes the day's reimbursable first meals from 47 back to 0, so it stores "
            f"a delta of {-LUNCH_FIRST_MEALS}, got {reversal['reimbursable_first_meals']}"
        )
        assert reversal["reimbursable_second_meals"] == 0, (
            "the day had no reimbursable second meals to give back, expected 0, got "
            f"{reversal['reimbursable_second_meals']}"
        )

        day = _read_day(api, scenario)
        assert_day_totals_match_entries(day, [original, reversal])

    def test_reversal_leaves_the_original_meal_count_entry_immutable(self, api):
        """PRD §2.5: "A correction to a meal count is expressed by writing a new reversing entry, never by editing the original."

        Design: Difficulty/compensating_invariant/meal_count_reversal_conserves_day_counted_totals
        """
        scenario = _open_day_with_one_original_count()
        original = scenario["original"]
        supervisor_headers = make_site_supervisor_headers(scenario["site"]["id"])

        reversal = _post_reversal(api, scenario)

        reread = validate_success(api.get_meal_count_entry(original["id"], supervisor_headers))
        assert_append_only_row(reread)
        assert reread["entry_kind"] == "ORIGINAL", (
            f"the reversed entry stays ORIGINAL, got {reread['entry_kind']}"
        )
        assert reread["first_meals"] == LUNCH_FIRST_MEALS, (
            f"the original's first_meals is never edited, expected {LUNCH_FIRST_MEALS}, got "
            f"{reread['first_meals']}"
        )
        assert reread["reimbursable_first_meals"] == LUNCH_FIRST_MEALS, (
            "the original keeps the contribution it recorded when it was written, expected "
            f"{LUNCH_FIRST_MEALS}, got {reread['reimbursable_first_meals']}"
        )
        assert reread["created_at"] == original["created_at"], (
            f"expected created_at {original['created_at']}, got {reread['created_at']}"
        )

        entries, meta = _read_entries(api, scenario)
        assert meta["total_count"] == 2, (
            "the correction is expressed as a second row beside the original, expected "
            f"total_count 2, got {meta['total_count']}"
        )
        entry_ids = {entry["id"] for entry in entries}
        assert entry_ids == {original["id"], reversal["id"]}, (
            "the day's history holds exactly the original and its reversal, got "
            f"{sorted(entry_ids)}"
        )
        kinds: Dict[str, str] = {entry["id"]: entry["entry_kind"] for entry in entries}
        assert kinds[original["id"]] == "ORIGINAL", (
            f"expected the original row to read ORIGINAL, got {kinds[original['id']]}"
        )
        assert kinds[reversal["id"]] == "REVERSAL", (
            f"expected the appended row to read REVERSAL, got {kinds[reversal['id']]}"
        )
