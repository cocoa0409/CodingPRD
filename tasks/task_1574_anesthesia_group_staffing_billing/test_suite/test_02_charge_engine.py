"""Combinatorial charge engine: unit math with PS/emergency branches, the
pinned direction-split rounding order, QK peak sensitivity, and time-unit
round-half-up (PRD §3.7)."""
from test_helpers import (
    SCHED,
    create_case,
    create_crna,
    create_fee_schedule,
    create_physician,
    create_published_roster,
    create_site,
    get_success_data,
    list_claims,
    make_physician_headers,
    propose_and_confirm,
    run_case_clock,
    set_clock,
    setup_case_with_confirmed_primary,
    setup_completed_solo_case,
    setup_directed_case,
    api_client,
)


def _claims_by_provider(api, case_id, provider_id):
    claims = list_claims({"case_id": case_id, "provider_id": provider_id})
    assert len(claims) == 1, f"expected exactly one claim, got {len(claims)}"
    return claims[0]


class TestChargeUnitsMultiInput:
    def test_ps_tier_and_emergency_branch_combine(self, api):
        """PRD §3.7: "The unit count combines four ingredients: the procedure's
        `base_units` from its fee-schedule row; **time units**, computed as the
        anesthesia minutes divided by fifteen and rounded half-up to one
        decimal place (six minutes yields 0.4, seven minutes 0.5, two hours
        exactly 8.0); a physical-status adder from the ASA table — `P1`, `P2`,
        and `P6` add nothing, `P3` adds one unit, `P4` adds two, `P5` adds
        three; and two qualifying units when `emergency_flag` is true, zero
        otherwise."

        Design: Difficulty/combinatorial_formula/charge_units_multi_input_tier_and_emergency_branch
        """
        ctx = setup_case_with_confirmed_primary(
            provider_type="CRNA", procedure_code="P200", base_units=7,
            physical_status="P4", emergency_flag=True,
            scheduled_start_minute=480, scheduled_end_minute=577,
            scheduled_day_end_minute=1200)
        case_id = ctx["case"]["id"]
        # Provisional: scheduled 97 min -> round_half_up(97/15)=6.5; P4 -> +2;
        # emergency -> +2; units 7 + 6.5 + 2 + 2 = 17.5; CRNA solo -> 7500.
        after_accept = get_success_data(api.get_case(case_id, SCHED))
        assert after_accept["provisional_charge_cents"] == 131250, (
            f"provisional must be 17.5 units x 7500 = 131250, got "
            f"{after_accept['provisional_charge_cents']}")
        run_case_clock(case_id, "2026-08-10T08:00:00Z", "2026-08-10T09:37:00Z")
        get_success_data(api.complete_case(case_id, SCHED))
        claim = _claims_by_provider(api, case_id, ctx["provider"]["id"])
        assert claim["units_total"] == 17.5, (
            f"units must be 7 + 6.5 + 2 + 2 = 17.5, got {claim['units_total']}")
        assert claim["modifier_code"] == "QZ"
        assert claim["charge_cents"] == 131250, (
            f"actual minutes == scheduled minutes here, so the final claim "
            f"equals the provisional: got {claim['charge_cents']}")

    def test_units_total_rounded_half_up_to_one_decimal(self, api):
        """PRD §3.7: "The total `units_total` is the sum of those four, rounded
        half-up to one decimal place."

        Design: Difficulty/combinatorial_formula/charge_units_multi_input_tier_and_emergency_branch
        """
        # P3 case (adds 1) with 30 scheduled minutes: 5 + 2.0 + 1 = 8.0 units;
        # MD solo -> 8.0 x 8000 = 64000 provisional.
        ctx = setup_case_with_confirmed_primary(
            provider_type="ANESTHESIOLOGIST", base_units=5,
            physical_status="P3", scheduled_start_minute=540,
            scheduled_end_minute=570)
        after_accept = get_success_data(api.get_case(ctx["case"]["id"], SCHED))
        assert after_accept["provisional_charge_cents"] == 64000, (
            f"P3 30-minute case must yield 8.0 units x 8000 = 64000, got "
            f"{after_accept['provisional_charge_cents']}")


class TestDirectionSplitPinnedOrder:
    def test_odd_gross_cent_physician_rounds_up_primary_takes_remainder(self, api):
        """PRD §3.7: "first round the unit total to one decimal (per the unit
        math above); then multiply by 8,001 cents and round the gross half-up
        to whole cents; then the physician's `charge_cents` is half the gross,
        rounded half-up; finally the primary's `charge_cents` is the gross
        **minus** the physician's half — so when the gross is an odd number of
        cents, the physician's half is the one that rounds up and the primary
        receives one cent less."

        Design: Difficulty/combinatorial_formula/direction_split_odd_gross_cent_remainder_pinned_order
        """
        ctx = setup_directed_case(verify_attestation=True, base_units=5,
                                  procedure_code="P300",
                                  scheduled_start_minute=540,
                                  scheduled_end_minute=660)
        case_id = ctx["case"]["id"]
        run_case_clock(case_id, "2026-08-10T09:00:00Z", "2026-08-10T11:00:00Z")
        completed = get_success_data(api.complete_case(case_id, SCHED))
        # 120 actual min -> 8.0 time units -> 13.0 units; gross =
        # round_half_up(13.0 x 8001) = 104013 (odd).
        phys = _claims_by_provider(api, case_id, ctx["director"]["id"])
        prim = _claims_by_provider(api, case_id, ctx["primary"]["id"])
        assert phys["modifier_code"] == "QY", (
            f"peak directed concurrency is 1 -> QY, got {phys['modifier_code']}")
        assert phys["charge_cents"] == 52007, (
            f"physician half of 104013 rounds up to 52007, got "
            f"{phys['charge_cents']}")
        assert prim["modifier_code"] == "QX"
        assert prim["charge_cents"] == 52006, (
            f"primary receives the remainder 104013 - 52007 = 52006, got "
            f"{prim['charge_cents']}")
        assert phys["charge_cents"] + prim["charge_cents"] == 104013
        assert completed["final_charge_cents"] == 104013

    def test_split_claims_sum_to_final_charge(self, api):
        """PRD §3.6: "The case's `final_charge_cents` is set to the sum of the
        created claims' `charge_cents`."
        PRD §3.7: "Rounding each half independently would double-count the odd
        cent and is explicitly wrong."

        Design: Difficulty/combinatorial_formula/direction_split_odd_gross_cent_remainder_pinned_order
        """
        ctx = setup_directed_case(verify_attestation=True, base_units=5,
                                  procedure_code="P300",
                                  scheduled_start_minute=540,
                                  scheduled_end_minute=660)
        case_id = ctx["case"]["id"]
        run_case_clock(case_id, "2026-08-10T09:00:00Z", "2026-08-10T11:00:00Z")
        completed = get_success_data(api.complete_case(case_id, SCHED))
        claims = list_claims({"case_id": case_id})
        assert len(claims) == 2, f"directed case must yield 2 claims, got {len(claims)}"
        total = sum(c["charge_cents"] for c in claims)
        assert total == completed["final_charge_cents"], (
            f"claim sum {total} must equal final_charge_cents "
            f"{completed['final_charge_cents']}")
        # Odd-gross split: the two halves must differ by exactly one cent.
        halves = sorted(c["charge_cents"] for c in claims)
        assert halves[1] - halves[0] == 1, (
            f"odd gross 104013 must split 52007/52006 (differ by 1), got {halves}")


class TestTimeUnitRoundingHalfUp:
    def test_six_minutes_yields_point_four(self, api):
        """PRD §3.7: "**time units**, computed as the anesthesia minutes
        divided by fifteen and rounded half-up to one decimal place (six
        minutes yields 0.4, seven minutes 0.5, two hours exactly 8.0)".

        Design: Corner/calculations/charge_units_time_unit_rounding_half_up
        """
        # Case A: 6 actual minutes. Base 10 + 0.4 = 10.4 units x 8000 = 83200.
        ctx_a = setup_completed_solo_case(
            provider_type="ANESTHESIOLOGIST", procedure_code="P700",
            base_units=10, scheduled_start_minute=540, scheduled_end_minute=546,
            start_iso="2026-08-10T09:00:00Z", end_iso="2026-08-10T09:06:00Z")
        claim_a = ctx_a["claims"][0]
        assert claim_a["units_total"] == 10.4, (
            f"6 actual minutes must yield 10 + 0.4 = 10.4 units, got "
            f"{claim_a['units_total']}")
        assert claim_a["charge_cents"] == 83200

    def test_seven_minutes_yields_point_five(self, api):
        """PRD §3.7: "**time units**, computed as the anesthesia minutes
        divided by fifteen and rounded half-up to one decimal place (six
        minutes yields 0.4, seven minutes 0.5, two hours exactly 8.0)".

        Design: Corner/calculations/charge_units_time_unit_rounding_half_up
        """
        # Case B: 7 actual minutes. 7/15 = 0.4666... -> 0.5; 10.5 x 8000.
        ctx_b = setup_completed_solo_case(
            provider_type="ANESTHESIOLOGIST", procedure_code="P700",
            base_units=10, scheduled_start_minute=600, scheduled_end_minute=607,
            start_iso="2026-08-10T10:00:00Z", end_iso="2026-08-10T10:07:00Z")
        claim_b = ctx_b["claims"][0]
        assert claim_b["units_total"] == 10.5, (
            f"7 actual minutes must round half-up to 0.5 (10.5 units), got "
            f"{claim_b['units_total']}")
        assert claim_b["charge_cents"] == 84000


class TestModifierQkAtPeakTwo:
    def _build_verified_directed_case(self, api, roster_id, director, peer,
                                      primary, start=540, end=660):
        case = create_case(roster_id, procedure_code="P300",
                           scheduled_start_minute=start, scheduled_end_minute=end)
        propose_and_confirm(case["id"], primary["id"], "CRNA", "CASE_PRIMARY")
        propose_and_confirm(case["id"], director["id"], "ANESTHESIOLOGIST",
                            "CASE_DIRECTING")
        att = get_success_data(api.create_attestation(
            {"case_id": case["id"], "physician_id": director["id"]}, SCHED))
        steps = {
            "step_preanesthetic_exam": True, "step_prescribes_plan": True,
            "step_participates_key_portions": True,
            "step_ensures_qualified_personnel": True, "step_monitors_course": True,
            "step_available_for_emergencies": True,
            "step_post_anesthesia_care": True,
        }
        get_success_data(api.submit_attestation(
            att["id"], steps, make_physician_headers(director["id"])))
        get_success_data(api.verify_attestation(
            att["id"], make_physician_headers(peer["id"])))
        return case

    def test_physician_claim_is_qk_when_peak_directed_concurrency_two(self, api):
        """PRD §3.7: "The physician's claim carries `QY` if the physician's
        peak directed concurrency was exactly one room, or `QK` otherwise —
        where peak counts the physician's `CONFIRMED`-or-`COMPLETED`
        `CASE_DIRECTING` assignments on the same service date whose cases'
        scheduled half-open intervals contain this case's
        `scheduled_start_minute`, this case included."

        Design: Corner/calculations/modifier_qk_when_physician_peak_two_verified
        """
        site = create_site()
        create_fee_schedule("P300", 5)
        roster = create_published_roster(site["id"], required_primary_slots=2,
                                         scheduled_day_end_minute=1200)
        director = create_physician("Dr. Direct")
        peer = create_physician("Dr. Peer")
        c1 = create_crna("Crna One")
        c2 = create_crna("Crna Two")
        k1 = self._build_verified_directed_case(api, roster["id"], director,
                                                peer, c1)
        k2 = self._build_verified_directed_case(api, roster["id"], director,
                                                peer, c2)
        run_case_clock(k1["id"], "2026-08-10T09:00:00Z")
        run_case_clock(k2["id"], "2026-08-10T09:00:00Z")
        set_clock("2026-08-10T11:00:00Z")
        get_success_data(api.complete_case(k1["id"], SCHED))
        get_success_data(api.complete_case(k2["id"], SCHED))
        for case, primary in ((k1, c1), (k2, c2)):
            phys = _claims_by_provider(api, case["id"], director["id"])
            prim = _claims_by_provider(api, case["id"], primary["id"])
            assert phys["modifier_code"] == "QK", (
                f"peak directed concurrency 2 must yield QK, got "
                f"{phys['modifier_code']}")
            assert phys["charge_cents"] == 52007
            assert prim["modifier_code"] == "QX"
            assert prim["charge_cents"] == 52006
