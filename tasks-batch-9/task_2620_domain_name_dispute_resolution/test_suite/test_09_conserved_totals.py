"""Compensating writes: what must move together, and what must stay behind."""
from test_helpers import (
    CASE_MANAGER,
    PROVIDER_ADMIN,
    admit_eligible_panelists,
    api_client,
    assert_honoraria_waterfall,
    file_response,
    fund_case_to_assessment,
    issue_deficiency_notice,
    nominate_seat,
    post_ledger_line,
    read_appointment,
    read_case,
    read_complainant,
    read_domain,
    read_panelist,
    replace_seat,
    screen_seat,
    seat_panelist_cleanly,
    set_clock,
    setup_commenced_case,
    setup_filed_case,
    setup_responded_case,
    run_sweep,
    validate_paginated,
)

CONSERVE_DOCKET = {
    "iana_id": "IANA-2727",
    "domain_name": "conserve.example",
    "legal_name": "Conserve NV",
    "country_code": "FR",
}
SEATS_DOCKET = {
    "iana_id": "IANA-2828",
    "domain_name": "seats.example",
    "legal_name": "Seatcount SARL",
    "country_code": "FR",
}
CHAIR_DOCKET = {
    "iana_id": "IANA-2929",
    "domain_name": "chair.example",
    "legal_name": "Chair AB",
    "country_code": "FR",
}


def _ledger_of(case_id):
    rows, meta = validate_paginated(
        api_client.list_fee_transactions(case_id, CASE_MANAGER, params={"limit": 20, "offset": 0})
    )
    return rows, meta


class TestPartyLedgerConservesToZero:
    def _deficient_case_with_a_write_off(self):
        bundle = setup_filed_case(evidence_count=1, **CONSERVE_DOCKET)
        case_id = bundle["case"]["id"]
        post_ledger_line(case_id, 25000, reference="WIRE-2727-B")
        post_ledger_line(
            case_id, 5000, payer="PROVIDER", kind="WRITE_OFF",
            reference="GOODWILL-2727", headers=PROVIDER_ADMIN,
        )
        bundle["notice"] = issue_deficiency_notice(
            case_id, deficiency_codes=["MUTUAL_JURISDICTION_ABSENT"]
        )
        bundle["case"] = read_case(case_id)
        return bundle

    def test_the_automatic_close_returns_both_party_subtotals_and_keeps_the_write_off(self):
        """PRD §3.3: "Because provider write-offs are counted in `paid_cents` but in
        neither party subtotal, `paid_cents` is always at least the sum of the two
        party subtotals."
        PRD §3.4: "The automatic close always refunds in full, at 100 percent,
        regardless of how far the case had travelled, and its refund lines carry the
        reference `AUTO-CLOSE-REFUND` instead of the withdrawal reference."
        PRD §3.4: "Both party subtotals therefore land on exactly 0, while
        `paid_cents` lands on the sum of any provider write-off lines, which are never
        refunded — so `paid_cents` reaches 0 only on a case that carries no
        write-off."

        Design: Difficulty/compensating_invariant/party_scoped_ledger_conserves_to_zero_while_the_write_off_survives
        """
        bundle = self._deficient_case_with_a_write_off()
        case_id = bundle["case"]["id"]
        before = bundle["case"]
        assert before["complainant_paid_cents"] == 175000
        assert before["respondent_paid_cents"] == 0
        assert before["paid_cents"] == 180000
        assert bundle["notice"]["correction_deadline_at"] == "2026-08-06T00:00:00.000Z"
        assert bundle["notice"]["status"] == "OPEN"
        assert before["status"] == "DEFICIENT"

        set_clock("2026-08-06T00:00:01Z")
        counters = run_sweep()
        assert counters["expired_notice_count"] == 1
        assert counters["closed_case_count"] == 1

        notices, _ = validate_paginated(
            api_client.list_deficiency_notices(case_id, CASE_MANAGER, params={"limit": 10, "offset": 0})
        )
        assert notices[0]["status"] == "EXPIRED"
        closed = read_case(case_id)
        assert closed["status"] == "ADMIN_CLOSED"
        assert closed["closed_at"] == "2026-08-06T00:00:01.000Z"

        rows, meta = _ledger_of(case_id)
        assert meta["total_count"] == 4
        refund = rows[3]
        assert refund["kind"] == "REFUND"
        assert refund["payer"] == "COMPLAINANT"
        assert refund["amount_cents"] == -175000
        assert refund["reference"] == "AUTO-CLOSE-REFUND"
        assert [row["payer"] for row in rows] == [
            "COMPLAINANT", "COMPLAINANT", "PROVIDER", "COMPLAINANT"
        ], "no refund line is minted for a payer who paid nothing"
        assert sum(row["amount_cents"] for row in rows if row["payer"] != "PROVIDER") == 0
        assert [row["amount_cents"] for row in rows[:3]] == [150000, 25000, 5000], (
            "the original lines are immutable and are neither deleted nor negated in place"
        )

        assert closed["complainant_paid_cents"] == 0
        assert closed["respondent_paid_cents"] == 0
        assert closed["paid_cents"] == 5000
        assert read_complainant(bundle["complainant"]["id"])["open_case_count"] == 0
        assert read_domain(bundle["domain"]["id"])["lock_status"] == "UNLOCKED"

    def test_a_second_sweep_at_the_same_instant_compensates_nothing_further(self):
        """PRD §2.4: "It is idempotent — running it twice at the same clock reading
        changes nothing on the second pass and returns all four counters as zero."
        PRD §3.3: "Ledger lines are immutable once written — nothing in the system
        amends or deletes one, and a correction is expressed as a further line."

        Design: Difficulty/compensating_invariant/party_scoped_ledger_conserves_to_zero_while_the_write_off_survives
        """
        bundle = self._deficient_case_with_a_write_off()
        case_id = bundle["case"]["id"]
        set_clock("2026-08-06T00:00:01Z")
        run_sweep()

        again = run_sweep()
        assert again["expired_notice_count"] == 0
        assert again["overdue_verification_count"] == 0
        assert again["defaulted_case_count"] == 0
        assert again["closed_case_count"] == 0

        rows, meta = _ledger_of(case_id)
        assert meta["total_count"] == 4
        assert sum(row["amount_cents"] for row in rows if row["payer"] != "PROVIDER") == 0
        settled = read_case(case_id)
        assert settled["status"] == "ADMIN_CLOSED"
        assert settled["closed_at"] == "2026-08-06T00:00:01.000Z"
        assert settled["paid_cents"] == 5000
        assert settled["complainant_paid_cents"] == 0


class TestSeatLoadCountersReconcile:
    def _panel_constituted_over_a_conflicted_exit(self):
        bundle = setup_responded_case(requests_three_member_panel=True, **SEATS_DOCKET)
        case_id = bundle["case"]["id"]
        fund_case_to_assessment(case_id)
        chair, refused, heir, co_two, substitute = admit_eligible_panelists(5)
        presiding = seat_panelist_cleanly(case_id, "PRESIDING", chair)
        nominated = nominate_seat(case_id, "CO_PANELIST_1", refused["id"])
        conflicted = screen_seat(
            nominated["id"], refused["id"], disclosed_financial_interest=True
        )
        vacated = replace_seat(
            conflicted["id"], replacement_panelist_id=heir["id"],
            reason="Disqualifying financial interest.",
        )
        seated_heir = screen_seat(vacated["replaced_by_appointment_id"], heir["id"])
        second = seat_panelist_cleanly(case_id, "CO_PANELIST_2", co_two)
        bundle["panelists"] = [chair, refused, heir, co_two, substitute]
        bundle["conflicted"] = conflicted
        bundle["vacated"] = vacated
        bundle["appointments"] = [presiding, seated_heir, second]
        bundle["case"] = read_case(case_id)
        return bundle

    def test_replacing_a_conflicted_seat_gives_back_no_load_because_it_held_none(self):
        """PRD §3.6: "The predecessor's fate depends on where it stood: a seat in
        `NOMINATED` or `WAIVER_PENDING` becomes `DECLINED`, while a seat in
        `CONFLICTED` or `ACCEPTED` becomes `REPLACED`."
        PRD §3.6: "Vacating a seat in `CONFLICTED` takes no load adjustment, because
        a conflicted seat never held any load to begin with, and it leaves the case
        status alone."

        Design: Difficulty/compensating_invariant/seat_load_counters_reconcile_after_a_no_load_exit_and_a_load_taking_exit
        """
        bundle = self._panel_constituted_over_a_conflicted_exit()
        case = bundle["case"]
        chair, refused, heir, co_two, _substitute = bundle["panelists"]
        assert case["required_seat_count"] == 3
        assert case["assessed_fee_cents"] == 400000

        assert float(bundle["conflicted"]["conflict_score"]) == 60.00
        assert bundle["conflicted"]["status"] == "CONFLICTED"
        vacated = read_appointment(bundle["vacated"]["id"])
        assert vacated["status"] == "REPLACED"
        assert vacated["replaced_by_appointment_id"] == bundle["appointments"][1]["id"]
        assert read_panelist(refused["id"])["active_case_load"] == 0, (
            "a seat that never took load has none to give back"
        )

        assert case["status"] == "PANEL_CONSTITUTED"
        assert [seat["status"] for seat in bundle["appointments"]] == [
            "ACCEPTED", "ACCEPTED", "ACCEPTED"
        ]
        loads = [
            read_panelist(panelist["id"])["active_case_load"]
            for panelist in (chair, refused, heir, co_two)
        ]
        assert loads == [1, 0, 1, 1]
        assert sum(loads) == 3, "one unit of load per accepted seat, no more and no less"

        rows, meta = validate_paginated(
            api_client.list_appointments(
                CASE_MANAGER, params={"case_id": case["id"], "limit": 20, "offset": 0}
            )
        )
        assert meta["total_count"] == 4
        assert sorted(row["status"] for row in rows) == [
            "ACCEPTED", "ACCEPTED", "ACCEPTED", "REPLACED"
        ]

    def test_replacing_an_accepted_seat_gives_its_load_back_and_the_sum_still_recounts(self):
        """PRD §3.6: "Vacating a seat that was in `ACCEPTED` unwinds everything that
        acceptance had built: the seat's `honoraria_cents` returns to 0, the neutral's
        `active_case_load` drops by one, the case falls back from `PANEL_CONSTITUTED`
        to `PANEL_APPOINTMENT`, and every decision on the case still in `DRAFT` is
        moved to `VOIDED` with `voided_at` stamped from the clock."
        PRD §3.6: "The other seats' `honoraria_cents` are left as they stand until the
        panel is constituted again, at which point allocation re-runs across the new
        set of accepted seats."
        PRD §3.6: "Seats in `NOMINATED`, `WAIVER_PENDING`, `CONFLICTED`, `DECLINED`,
        `REPLACED` or `DISCHARGED` are never counted toward completeness."

        Design: Difficulty/compensating_invariant/seat_load_counters_reconcile_after_a_no_load_exit_and_a_load_taking_exit
        """
        bundle = self._panel_constituted_over_a_conflicted_exit()
        case_id = bundle["case"]["id"]
        chair, refused, heir, co_two, substitute = bundle["panelists"]
        presiding, seated_heir, second = bundle["appointments"]
        assert read_panelist(co_two["id"])["active_case_load"] == 1

        surrendered = replace_seat(
            second["id"], replacement_panelist_id=substitute["id"],
            reason="The co-panelist withdrew for health reasons.",
        )
        assert surrendered["status"] == "REPLACED"
        assert surrendered["honoraria_cents"] == 0
        assert read_panelist(co_two["id"])["active_case_load"] == 0
        assert read_case(case_id)["status"] == "PANEL_APPOINTMENT"
        assert read_appointment(presiding["id"])["honoraria_cents"] == 112000
        assert read_appointment(seated_heir["id"])["honoraria_cents"] == 84000

        seated_substitute = screen_seat(
            surrendered["replaced_by_appointment_id"], substitute["id"]
        )
        assert seated_substitute["status"] == "ACCEPTED"
        assert seated_substitute["seat"] == "CO_PANELIST_2"
        assert read_case(case_id)["status"] == "PANEL_CONSTITUTED"

        loads = [
            read_panelist(panelist["id"])["active_case_load"]
            for panelist in (chair, refused, heir, co_two, substitute)
        ]
        assert loads == [1, 0, 1, 0, 1]
        assert sum(loads) == 3

        rows, meta = validate_paginated(
            api_client.list_appointments(
                CASE_MANAGER, params={"case_id": case_id, "limit": 20, "offset": 0}
            )
        )
        assert meta["total_count"] == 5
        accepted = [row for row in rows if row["status"] == "ACCEPTED"]
        assert len(accepted) == 3
        assert sorted(row["seat"] for row in accepted) == [
            "CO_PANELIST_1", "CO_PANELIST_2", "PRESIDING"
        ]
        assert sum(row["honoraria_cents"] for row in accepted) == 280000

        audit, audit_meta = validate_paginated(
            api_client.list_appointments(
                CASE_MANAGER, params={"panelist_id": refused["id"], "limit": 10, "offset": 0}
            )
        )
        assert audit_meta["total_count"] == 1
        assert audit[0]["status"] == "REPLACED"


class TestHonorariaPoolIsConservedAcrossAReseatedChair:
    def _expedited_three_member_panel(self):
        bundle = setup_commenced_case(expedited_requested=True, **CHAIR_DOCKET)
        case_id = bundle["case"]["id"]
        bundle["provisional"] = read_case(case_id)
        bundle["response"] = file_response(bundle, requests_three_member_panel=True)
        bundle["repriced"] = read_case(case_id)
        fund_case_to_assessment(case_id)
        chair, co_one, co_two, substitute = admit_eligible_panelists(4)
        bundle["appointments"] = [
            seat_panelist_cleanly(case_id, "PRESIDING", chair),
            seat_panelist_cleanly(case_id, "CO_PANELIST_1", co_one),
            seat_panelist_cleanly(case_id, "CO_PANELIST_2", co_two),
        ]
        bundle["panelists"] = [chair, co_one, co_two, substitute]
        bundle["case"] = read_case(case_id)
        return bundle

    def test_the_single_remainder_cent_of_an_odd_pool_lands_on_the_chair(self):
        """PRD §3.2: "A standard single-member filing therefore assesses 150000 cents
        entirely to the complainant with a pool of 105000 cents, and an expedited
        single-member filing assesses 168750 cents entirely to the complainant with a
        pool of 118125 cents."
        PRD §3.5: "The 250000-cent three-member supplement now enters
        `assessed_fee_cents`, `respondent_share_cents` becomes half of that supplement
        rounded down, or 125000 cents, and `complainant_share_cents` is the
        remainder."
        PRD §3.6: "On a three-member panel the `PRESIDING` seat is entitled to 40
        percent and each co-panelist to 30 percent; each seat's raw entitlement is
        floored to a whole cent independently, and then the entire rounding remainder
        is handed to the `PRESIDING` seat so that the three `honoraria_cents` values
        sum to the pool exactly."

        Design: Difficulty/compensating_invariant/honoraria_pool_is_conserved_to_the_cent_across_a_reseated_presiding_chair
        """
        bundle = self._expedited_three_member_panel()
        provisional = bundle["provisional"]
        assert provisional["assessed_fee_cents"] == 168750
        assert provisional["honoraria_pool_cents"] == 118125
        assert provisional["fee_variant_applied"] == "PROVISIONAL"

        repriced = bundle["repriced"]
        assert repriced["assessed_fee_cents"] == 418750
        assert repriced["respondent_share_cents"] == 125000
        assert repriced["complainant_share_cents"] == 293750
        assert repriced["honoraria_pool_cents"] == 293125
        assert repriced["fee_variant_applied"] == "FINAL"

        assert bundle["case"]["status"] == "PANEL_CONSTITUTED"
        seats = [read_appointment(seat["id"]) for seat in bundle["appointments"]]
        assert [seat["honoraria_cents"] for seat in seats] == [117251, 87937, 87937]
        assert sum(seat["honoraria_cents"] for seat in seats) == 293125
        assert_honoraria_waterfall(seats, 293125)

    def test_reseating_the_chair_reallocates_the_pool_without_gaining_or_losing_a_cent(self):
        """PRD §3.6: "Only seats in `ACCEPTED` participate; the allocation is re-run
        whenever the panel becomes constituted again after a seat was vacated."
        PRD §3.6: "Vacating a seat that was in `ACCEPTED` unwinds everything that
        acceptance had built: the seat's `honoraria_cents` returns to 0, the neutral's
        `active_case_load` drops by one, the case falls back from `PANEL_CONSTITUTED`
        to `PANEL_APPOINTMENT`, and every decision on the case still in `DRAFT` is
        moved to `VOIDED` with `voided_at` stamped from the clock."
        PRD §3.2: "Finally, `honoraria_pool_cents` is 70 percent of
        `assessed_fee_cents`, rounded half up to a whole cent; the remaining 30
        percent is the provider's administrative retention and is not stored on the
        case."

        Design: Difficulty/compensating_invariant/honoraria_pool_is_conserved_to_the_cent_across_a_reseated_presiding_chair
        """
        bundle = self._expedited_three_member_panel()
        case_id = bundle["case"]["id"]
        presiding, co_one, co_two = bundle["appointments"]
        chair, _co_one_panelist, _co_two_panelist, substitute = bundle["panelists"]

        vacated = replace_seat(
            presiding["id"], replacement_panelist_id=substitute["id"],
            reason="The chair stepped down.",
        )
        assert vacated["status"] == "REPLACED"
        assert vacated["honoraria_cents"] == 0, "no stale entitlement is left on the row"
        assert read_appointment(co_one["id"])["honoraria_cents"] == 87937
        assert read_appointment(co_two["id"])["honoraria_cents"] == 87937
        mid = read_case(case_id)
        assert mid["status"] == "PANEL_APPOINTMENT"
        assert mid["honoraria_pool_cents"] == 293125, (
            "the pool follows the fee assessment alone, not the seating"
        )
        assert read_panelist(chair["id"])["active_case_load"] == 0

        seated = screen_seat(vacated["replaced_by_appointment_id"], substitute["id"])
        assert seated["status"] == "ACCEPTED"
        assert seated["seat"] == "PRESIDING"
        assert seated["honoraria_cents"] == 117251
        assert read_case(case_id)["status"] == "PANEL_CONSTITUTED"
        assert read_panelist(substitute["id"])["active_case_load"] == 1

        rows, meta = validate_paginated(
            api_client.list_appointments(
                CASE_MANAGER, params={"case_id": case_id, "limit": 20, "offset": 0}
            )
        )
        assert meta["total_count"] == 4
        accepted = [row for row in rows if row["status"] == "ACCEPTED"]
        assert len(accepted) == 3
        assert sum(row["honoraria_cents"] for row in accepted) == 293125
        assert sum(row["honoraria_cents"] for row in rows) == 293125, (
            "the vacated row contributes nothing, so the four rows still sum to the pool"
        )
        assert_honoraria_waterfall(accepted, 293125)
