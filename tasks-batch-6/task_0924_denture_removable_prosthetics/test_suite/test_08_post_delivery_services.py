"""Post-delivery services: the chairside/laboratory fork, the included-versus-
chargeable adjustment classification, and the allowance that void restores."""

from test_helpers import (
    ApiErrorId,
    assert_adjustment_allowance_conserved,
    assert_money,
    assert_post_delivery_service,
    assert_same_instant,
    create_service_payload,
    fixtures as fx,
    validate_error,
    validate_success,
)


def _delivered_flexible_partial(name, dob, phone):
    return fx.setup_delivered_prosthesis(
        patient_overrides={"full_name": name, "date_of_birth": dob, "phone": phone}
    )


class TestAdjustmentClassification:
    def test_an_adjustment_inside_the_ninety_day_window_completes_at_no_charge(self, api, prosthodontist_headers):
        """PRD §3.7: "- For an `ADJUSTMENT`, two conditions are tested. The count
        condition is that the appliance's `adjustments_used` is **strictly below 4**;
        the window condition is that the logical clock is **at or before**
        `adjustment_window_ends_at`, which is inclusive of the boundary instant. When
        both hold, `charge_basis` is `INCLUDED` and `charge_amount` is 0.00, and the
        completion consumes one unit of the allowance: `adjustments_used` rises by one
        and `adjustments_remaining` falls by one."
        PRD §3.6: "`adjustment_window_ends_at` is `delivered_at` plus 90 calendar
        days, and it bounds the included-adjustment allowance of §3.7."

        Design: Difficulty/dual_variant_calc/included_vs_chargeable_adjustment_by_window_boundary
        """
        ctx = _delivered_flexible_partial("Bram Ostrowski", "1949-11-02", "555-0177")
        prosthesis_id = ctx["prosthesis"]["id"]
        assert_same_instant(
            ctx["prosthesis"]["adjustment_window_ends_at"],
            "2026-07-30T00:00:00.000Z",
            "Prosthesis.adjustment_window_ends_at",
        )

        service = validate_success(
            api.create_service(
                create_service_payload(
                    prosthesis_id, "ADJUSTMENT", fx.prosthesis_version(prosthesis_id)
                ),
                prosthodontist_headers,
            ),
            201,
        )
        completed = validate_success(
            api.complete_service(service["id"], prosthodontist_headers), 200
        )

        assert_post_delivery_service(completed)
        assert completed["charge_basis"] == "INCLUDED"
        assert_money(completed["charge_amount"], 0.00, "PostDeliveryService.charge_amount")

        prosthesis = fx.read_prosthesis(prosthesis_id)
        assert prosthesis["adjustments_used"] == 1
        assert prosthesis["adjustments_remaining"] == 3
        assert_adjustment_allowance_conserved(prosthesis)

    def test_an_adjustment_after_the_window_closes_is_chargeable_and_moves_no_counter(self, api, prosthodontist_headers):
        """PRD §3.7: "When either fails — the fifth adjustment, or any adjustment
        after the 90-day window closes — `charge_basis` is `CHARGEABLE`,
        `charge_amount` is 85.00, and **neither allowance counter moves**, which is
        what keeps the conservation invariant of §2.13 intact on that path."
        PRD §3.9: "3. The **service total** is the sum of `charge_amount` over the
        case's post-delivery services whose `service_status` is `COMPLETED`, plus the
        sum of `patient_charge_amount` over the case's warranty claims whose
        `claim_status` is `PATIENT_FAULT`."
        PRD §3.9: "4. `billed_amount` is the gross fee plus the rush total plus the
        service total, rounded half up to two decimal places."

        Design: Difficulty/dual_variant_calc/included_vs_chargeable_adjustment_by_window_boundary
        """
        ctx = _delivered_flexible_partial("Bram Ostrowski", "1949-11-02", "555-0177")
        prosthesis_id = ctx["prosthesis"]["id"]

        inside = fx.request_service(prosthesis_id, "ADJUSTMENT")
        inside = fx.complete_service(inside["id"])
        assert inside["charge_basis"] == "INCLUDED"

        fx.set_clock("2026-07-31T00:00:00Z")
        outside = validate_success(
            api.create_service(
                create_service_payload(
                    prosthesis_id, "ADJUSTMENT", fx.prosthesis_version(prosthesis_id)
                ),
                prosthodontist_headers,
            ),
            201,
        )
        outside = validate_success(
            api.complete_service(outside["id"], prosthodontist_headers), 200
        )

        assert outside["charge_basis"] == "CHARGEABLE"
        assert_money(outside["charge_amount"], 85.00, "PostDeliveryService.charge_amount")

        prosthesis = fx.read_prosthesis(prosthesis_id)
        assert prosthesis["adjustments_used"] == 1, "only the INCLUDED completion consumed allowance"
        assert prosthesis["adjustments_remaining"] == 3
        assert_money(
            fx.read_case(ctx["case"]["id"])["billed_amount"],
            1285.00,
            "ProsthesisCase.billed_amount",
        )


class TestAllowanceConservation:
    def test_completing_an_included_adjustment_moves_one_unit_from_remaining_to_used(self, api, prosthodontist_headers):
        """PRD §2.13: "**Adjustment allowance.** On any prosthesis,
        `adjustments_used` plus `adjustments_remaining` always equals 4. Completing an
        included adjustment moves one unit from remaining to used; voiding that
        completed row moves it back. A *chargeable* adjustment — one past the count or
        past the window — must move neither counter, so the sum is untouched on that
        path too."

        Design: Difficulty/compensating_invariant/adjustment_allowance_conserved_across_complete_and_void
        """
        ctx = _delivered_flexible_partial("Ulla Ferrante", "1955-05-05", "555-0433")
        prosthesis_id = ctx["prosthesis"]["id"]

        before = fx.read_prosthesis(prosthesis_id)
        assert before["adjustments_used"] == 0
        assert before["adjustments_remaining"] == 4
        assert_adjustment_allowance_conserved(before)

        service = fx.request_service(prosthesis_id, "ADJUSTMENT")
        validate_success(api.complete_service(service["id"], prosthodontist_headers), 200)

        after = fx.read_prosthesis(prosthesis_id)
        assert after["adjustments_used"] == 1
        assert after["adjustments_remaining"] == 3
        assert_adjustment_allowance_conserved(after)

    def test_voiding_the_completed_adjustment_restores_the_allowance_and_the_case_balance(self, api, front_office_headers):
        """PRD §3.7: "From `COMPLETED` it is the declared **compensating action**:
        when the voided row was an adjustment classified as `INCLUDED`,
        `adjustments_used` falls by one and `adjustments_remaining` rises by one,
        restoring the allowance; the row's `charge_amount` is subtracted from the
        case's `billed_amount` and the case's patient responsibility recomputed;
        `charge_amount` is then set to 0.00; and `voided_at` is stamped."
        PRD §3.7: "`COMPLETED` is deliberately **not** a terminal state of the service
        axis — void is its declared compensating action and must stay reachable.
        `VOIDED` is the only terminal state."

        Design: Difficulty/compensating_invariant/adjustment_allowance_conserved_across_complete_and_void
        """
        ctx = _delivered_flexible_partial("Ulla Ferrante", "1955-05-05", "555-0433")
        prosthesis_id = ctx["prosthesis"]["id"]
        billed_before = fx.read_case(ctx["case"]["id"])["billed_amount"]

        service = fx.request_service(prosthesis_id, "ADJUSTMENT")
        fx.complete_service(service["id"])

        voided = validate_success(api.void_service(service["id"], front_office_headers), 200)

        assert voided["service_status"] == "VOIDED"
        assert_money(voided["charge_amount"], 0.00, "PostDeliveryService.charge_amount")

        restored = fx.read_prosthesis(prosthesis_id)
        assert restored["adjustments_used"] == 0
        assert restored["adjustments_remaining"] == 4
        assert_adjustment_allowance_conserved(restored)
        assert_money(
            fx.read_case(ctx["case"]["id"])["billed_amount"],
            billed_before,
            "ProsthesisCase.billed_amount is exactly its pre-trigger value",
        )
        assert_money(billed_before, 1200.00, "ProsthesisCase.billed_amount before the trigger")


class TestServiceBranchesAndEligibility:
    def test_a_chairside_soft_reline_never_leaves_the_patients_possession(self, api, prosthodontist_headers):
        """PRD §3.7: "- **Chairside**: `ADJUSTMENT`, `SOFT_RELINE_CHAIRSIDE`, and
        `REPAIR`. The service moves immediately from `REQUESTED` to `IN_CHAIR`, and
        the appliance's `in_patient_possession` stays true — the patient keeps the
        denture."
        PRD §3.7: "- Otherwise `charge_basis` is `CHARGEABLE` and `charge_amount` is
        the fee for the service type: 260.00 for a chairside soft reline, 420.00 for a
        laboratory hard reline, 590.00 for a rebase, 180.00 for a repair, 155.00 for a
        tooth addition, and 195.00 for a clasp addition."

        Design: Corner/endpoints/chairside_service_never_leaves_the_patients_possession_and_prices_at_its_own_fee
        """
        ctx = _delivered_flexible_partial("Kirsi Halonen", "1952-03-07", "555-1035")
        prosthesis_id = ctx["prosthesis"]["id"]

        service = validate_success(
            api.create_service(
                create_service_payload(
                    prosthesis_id, "SOFT_RELINE_CHAIRSIDE", fx.prosthesis_version(prosthesis_id)
                ),
                prosthodontist_headers,
            ),
            201,
        )
        assert service["service_status"] == "IN_CHAIR"
        assert service["lab_case_id"] is None, "only the laboratory branch mints a lab case"
        assert fx.read_prosthesis(prosthesis_id)["in_patient_possession"] is True
        assert len(fx.lab_cases_of(ctx["arch"]["id"])) == 1, "the fabrication case only"

        completed = validate_success(
            api.complete_service(service["id"], prosthodontist_headers), 200
        )
        assert completed["charge_basis"] == "CHARGEABLE"
        assert_money(completed["charge_amount"], 260.00, "PostDeliveryService.charge_amount")

        assert fx.read_prosthesis(prosthesis_id)["in_patient_possession"] is True
        assert fx.read_prosthesis(prosthesis_id)["adjustments_used"] == 0, (
            "a reline never touches the adjustment allowance"
        )
        assert_money(
            fx.read_case(ctx["case"]["id"])["billed_amount"],
            1460.00,
            "ProsthesisCase.billed_amount",
        )

    def test_type_eligibility_and_frequency_each_refuse_on_their_own_terms(self, api, prosthodontist_headers):
        """PRD §3.7: "First, **type eligibility**: a `CLASP_ADDITION` is only accepted
        on a partial — that is, on a `CAST_PARTIAL` or a `FLEXIBLE_PARTIAL` — and a
        `REBASE` is refused outright on a `FLEXIBLE_PARTIAL`, both refusals carrying
        `ERR_SERVICE_NOT_ELIGIBLE`."
        PRD §3.7: "A hard reline may be repeated only every 24 months; a chairside
        soft reline only every 6 months; a rebase only every 36 months."
        PRD §3.7: "The boundary is inclusive: exactly 24 months after a hard reline,
        another hard reline is permitted. When no completed service of that type exists
        on the appliance, the request is eligible. A request inside the interval is
        refused with `ERR_SERVICE_FREQUENCY_LIMIT`."

        Design: Corner/endpoints/service_eligibility_and_frequency_rungs_each_reject_independently
        """
        ctx = _delivered_flexible_partial("Lauri Nieminen", "1945-04-08", "555-1036")
        prosthesis_id = ctx["prosthesis"]["id"]

        first_reline = fx.request_service(prosthesis_id, "SOFT_RELINE_CHAIRSIDE")
        fx.complete_service(first_reline["id"])

        fx.set_clock("2026-10-01T00:00:00Z")
        version_now = fx.prosthesis_version(prosthesis_id)

        ineligible = api.create_service(
            create_service_payload(
                prosthesis_id, "REBASE", version_now,
                dental_lab_id=ctx["lab"]["id"], bench_line=2,
            ),
            prosthodontist_headers,
        )
        validate_error(ineligible, ApiErrorId.ERR_SERVICE_NOT_ELIGIBLE.value, 422)

        too_soon = api.create_service(
            create_service_payload(prosthesis_id, "SOFT_RELINE_CHAIRSIDE", version_now),
            prosthodontist_headers,
        )
        validate_error(too_soon, ApiErrorId.ERR_SERVICE_FREQUENCY_LIMIT.value, 422)

        assert len(fx.services_of(prosthesis_id)) == 1, "neither refusal minted a service row"

        fx.set_clock("2026-11-01T00:00:00Z")
        allowed = validate_success(
            api.create_service(
                create_service_payload(
                    prosthesis_id,
                    "SOFT_RELINE_CHAIRSIDE",
                    fx.prosthesis_version(prosthesis_id),
                ),
                prosthodontist_headers,
            ),
            201,
        )
        assert allowed["service_status"] == "IN_CHAIR", (
            "six whole calendar months after the first completion the interval has elapsed"
        )
