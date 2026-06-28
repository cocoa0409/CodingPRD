"""Session pricing, package pricing, deposit, and client-risk calculations.

Translates queue-A dual-variant and combinatorial calculation instances plus the
queue-B calculation/computed-field corner instances.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    make_technician_headers,
    setup_booking_ready,
    book_initial_appointment,
    setup_completed_appointment,
    create_appointment_payload,
    create_client_payload,
    create_studio_payload,
    create_color_formula_payload,
    create_package_payload,
    create_annual_refresh_payload,
    set_clock,
)

FRONT = TEST_USERS["front_desk_headers"]
ADMIN = TEST_USERS["studio_admin_headers"]


# ─────────────────────────────────────────────────────────────────────────────
# Queue A: dual_variant_calc
# ─────────────────────────────────────────────────────────────────────────────
class TestSessionPriceInitialVsAnnualRefresh:
    """session_price standard_session vs annual_refresh_session divergence."""

    def test_initial_brows_two_pigment_session_price_65000(self, api):
        """PRD §3.4: "a brows procedure has a base of 60000 cents" and "5000
        cents when the count is exactly 2" and "The session price is then the
        base plus the color surcharge plus the corrective uplift."

        Design: Difficulty/dual_variant_calc/dvc_session_price_initial_vs_annual_refresh
        """
        ctx = setup_booking_ready(pigment_count=2, procedure_type="BROWS")
        appt = book_initial_appointment(ctx, scheduled_start="2026-01-06T10:00:00Z")
        assert appt["session_price_cents"] == 65000, (
            f"BROWS base 60000 + 2-pigment surcharge 5000 should be 65000, "
            f"got {appt['session_price_cents']}"
        )

    def test_annual_refresh_session_price_is_half_base(self, api):
        """PRD §3.4: "For an `ANNUAL_REFRESH` appointment the session price is
        simply the base rate multiplied by 0.50 and rounded half-up to whole
        cents, with the color surcharge and corrective uplift both dropped."

        Design: Difficulty/dual_variant_calc/dvc_session_price_initial_vs_annual_refresh
        """
        # Reach a COMPLETED initial appointment, then book an annual refresh >=365d later.
        ctx, completed = setup_completed_appointment(
            scheduled_start="2026-01-06T10:00:00Z", complete_clock="2026-02-01T00:00:00Z"
        )
        set_clock("2027-02-02T00:00:00Z")
        refresh = validate_success(
            api.book_annual_refresh(
                create_annual_refresh_payload(
                    completed["id"],
                    ctx["technician"]["id"],
                    ctx["formula"]["id"],
                    ctx["patch_test"]["id"],
                    scheduled_start="2027-02-05T10:00:00Z",
                    procedure_type="BROWS",
                ),
                FRONT,
            ),
            201,
        )
        assert refresh["session_price_cents"] == 30000, (
            f"ANNUAL_REFRESH BROWS should be round_half_up(60000*0.50)=30000, "
            f"got {refresh['session_price_cents']}"
        )

    def test_annual_refresh_deposit_is_twenty_percent_of_refresh_price(self, api):
        """PRD §3.4: "The deposit required, `deposit_required_cents`, is computed
        immediately after the session price as 20 percent of the session price,
        rounded half-up to whole cents."

        Design: Difficulty/dual_variant_calc/dvc_session_price_initial_vs_annual_refresh
        """
        ctx, completed = setup_completed_appointment(
            scheduled_start="2026-01-06T10:00:00Z", complete_clock="2026-02-01T00:00:00Z"
        )
        set_clock("2027-02-02T00:00:00Z")
        refresh = validate_success(
            api.book_annual_refresh(
                create_annual_refresh_payload(
                    completed["id"],
                    ctx["technician"]["id"],
                    ctx["formula"]["id"],
                    ctx["patch_test"]["id"],
                    scheduled_start="2027-02-05T10:00:00Z",
                    procedure_type="BROWS",
                ),
                FRONT,
            ),
            201,
        )
        assert refresh["deposit_required_cents"] == 6000, (
            f"deposit should be round_half_up(30000*0.20)=6000, "
            f"got {refresh['deposit_required_cents']}"
        )


class TestClientRiskProvisionalVsFinal:
    """client_risk_score provisional (self) vs final (observed) variant."""

    def test_provisional_risk_uses_self_reported_sensitivity(self, api):
        """PRD §3.2: "At intake, before any patch test has been read, the
        provisional variant uses the self-reported grade" and "the medical-flag
        count is weighted by 8, the prior-adverse-reaction count is weighted by
        12, and a sensitivity figure is weighted by 5".

        Design: Difficulty/dual_variant_calc/dvc_client_risk_provisional_vs_final
        """
        studio = get_success_data(
            api.create_studio(create_studio_payload(sterile_kit_total=5), ADMIN)
        )
        client = validate_success(
            api.create_client(
                create_client_payload(
                    studio["id"],
                    full_name="Client R",
                    medical_flag_count=2,
                    prior_adverse_reactions=0,
                    skin_sensitivity_self=2,
                ),
                FRONT,
            ),
            201,
        )
        assert client["risk_score"] == 26, (
            f"provisional 8*2 + 12*0 + 5*2 = 26, got {client['risk_score']}"
        )
        assert client["risk_band"] == "STANDARD"

    def test_final_risk_uses_observed_grade_after_patch_read(self, api):
        """PRD §3.2: "once a patch test is read, the final variant uses the
        observed grade, which overrides the self-report."
        PRD §3.3: "copies the reaction grade onto the client's
        `skin_sensitivity_observed`, recomputes the client's `risk_score` and
        `risk_band` using the final post-patch-test variant".

        Design: Difficulty/dual_variant_calc/dvc_client_risk_provisional_vs_final
        """
        set_clock("2026-01-01T00:00:00Z")
        studio = get_success_data(
            api.create_studio(create_studio_payload(sterile_kit_total=5), ADMIN)
        )
        technician = get_success_data(
            api.create_technician(
                {
                    "studio_id": studio["id"],
                    "full_name": "Tech A",
                    "license_number": "L1",
                    "bbp_cert_expiry": "2030-01-01T00:00:00Z",
                    "license_expiry": "2030-01-01T00:00:00Z",
                },
                ADMIN,
            )
        )
        client = get_success_data(
            api.create_client(
                create_client_payload(
                    studio["id"],
                    full_name="Client R",
                    medical_flag_count=2,
                    prior_adverse_reactions=0,
                    skin_sensitivity_self=2,
                ),
                FRONT,
            )
        )
        pt = get_success_data(api.create_patch_test({"client_id": client["id"]}, TEST_USERS["technician_headers"]))
        set_clock("2026-01-03T01:00:00Z")
        api.read_patch_test(
            pt["id"], {"reaction_grade": 3}, make_technician_headers(technician["id"])
        )
        final = validate_success(api.get_client(client["id"], FRONT), 200)
        assert final["skin_sensitivity_observed"] == 3
        assert final["risk_score"] == 31, (
            f"final 8*2 + 12*0 + 5*3 = 31, got {final['risk_score']}"
        )
        assert final["risk_band"] == "HIGH_RISK"


# ─────────────────────────────────────────────────────────────────────────────
# Queue A: combinatorial_formula
# ─────────────────────────────────────────────────────────────────────────────
class TestPackagePriceRoundingOrder:
    """PAYG round-per-line-then-sum vs BUNDLE sum-then-round-once divergence."""

    def _completed_brows_65000(self, api):
        ctx, completed = setup_completed_appointment(
            pigment_count=2,
            procedure_type="BROWS",
            scheduled_start="2026-01-06T10:00:00Z",
            complete_clock="2026-02-01T00:00:00Z",
        )
        assert completed["session_price_cents"] == 65000
        return ctx, completed

    def test_payg_rounds_each_line_then_sums(self, api):
        """PRD §3.8: "Under the pay-as-you-go mode (`PAYG`, the provisional
        treatment), each touch-up line is rounded half-up individually and then
        those rounded lines are summed: the per-line amount is the per-touch-up
        gross rounded half-up, and the package price is that rounded line
        multiplied by the number of included sessions."

        Design: Difficulty/combinatorial_formula/cf_package_round_per_line_vs_sum_then_round
        """
        ctx, completed = self._completed_brows_65000(api)
        pkg = validate_success(
            api.create_package(
                create_package_payload(
                    ctx["client"]["id"], completed["id"], included_sessions=2, pricing_mode="PAYG"
                ),
                FRONT,
            ),
            201,
        )
        # round_half_up(65000*0.40)=26000 per line; 26000*2 = 52000
        assert pkg["package_price_cents"] == 52000, (
            f"PAYG round-per-line should be 52000, got {pkg['package_price_cents']}"
        )

    def test_bundle_sums_then_rounds_with_discount(self, api):
        """PRD §3.8: "Under the bundle mode (`BUNDLE`, the final discounted
        treatment), the products are summed first and then rounded once: the
        gross is the per-touch-up gross multiplied by the number of included
        sessions, and the package price is that gross multiplied by (1 minus the
        15 percent bundle discount), rounded half-up exactly once."

        Design: Difficulty/combinatorial_formula/cf_package_round_per_line_vs_sum_then_round
        """
        ctx, completed = self._completed_brows_65000(api)
        pkg = validate_success(
            api.create_package(
                create_package_payload(
                    ctx["client"]["id"], completed["id"], included_sessions=2, pricing_mode="BUNDLE"
                ),
                FRONT,
            ),
            201,
        )
        # round_half_up(65000*0.40*2*0.85) = round_half_up(44200.0) = 44200
        assert pkg["package_price_cents"] == 44200, (
            f"BUNDLE sum-then-round should be 44200, got {pkg['package_price_cents']}"
        )


class TestSessionPriceThreeInputNonlinear:
    """session_price tiered surcharge + conditional corrective uplift."""

    def test_eyeliner_three_pigment_corrective_session_price_74500(self, api):
        """PRD §3.4: "an eyeliner procedure 50000 cents" and "12000 cents when
        the count is 3 or more" and "The corrective uplift applies only when
        `is_corrective` is true: it is the base rate multiplied by 0.25 and
        rounded half-up to whole cents".

        Design: Difficulty/combinatorial_formula/cf_session_price_three_input_nonlinear
        """
        ctx = setup_booking_ready(pigment_count=3, procedure_type="EYELINER")
        appt = book_initial_appointment(
            ctx, scheduled_start="2026-01-06T10:00:00Z", is_corrective=True
        )
        # 50000 + 12000 + round_half_up(50000*0.25=12500) = 74500
        assert appt["session_price_cents"] == 74500, (
            f"EYELINER 50000 + 12000 + 12500 should be 74500, "
            f"got {appt['session_price_cents']}"
        )

    def test_eyeliner_three_pigment_corrective_deposit_14900(self, api):
        """PRD §3.4: "The deposit required, `deposit_required_cents`, is computed
        immediately after the session price as 20 percent of the session price,
        rounded half-up to whole cents."

        Design: Difficulty/combinatorial_formula/cf_session_price_three_input_nonlinear
        """
        ctx = setup_booking_ready(pigment_count=3, procedure_type="EYELINER")
        appt = book_initial_appointment(
            ctx, scheduled_start="2026-01-06T10:00:00Z", is_corrective=True
        )
        assert appt["deposit_required_cents"] == 14900, (
            f"deposit round_half_up(74500*0.20)=14900, got {appt['deposit_required_cents']}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Queue B: calculations / computed fields
# ─────────────────────────────────────────────────────────────────────────────
def test_lip_blush_single_pigment_no_surcharge(api):
    """PRD §3.4: "a lip-blush procedure 70000 cents" and "it is 0 when the
    pigment count is 1 or fewer" and "The deposit required ... is computed ...
    as 20 percent of the session price, rounded half-up to whole cents."

    Design: Corner/calculations/calc_lip_blush_single_pigment_no_surcharge
    """
    ctx = setup_booking_ready(pigment_count=1, procedure_type="LIP_BLUSH")
    appt = book_initial_appointment(ctx, scheduled_start="2026-01-06T10:00:00Z")
    assert appt["session_price_cents"] == 70000, (
        f"LIP_BLUSH base 70000 with 1 pigment (no surcharge), got {appt['session_price_cents']}"
    )
    assert appt["deposit_required_cents"] == 14000, (
        f"deposit round_half_up(70000*0.20)=14000, got {appt['deposit_required_cents']}"
    )


def test_procedure_type_must_match_color_formula(api):
    """PRD §3.5: "The well-formedness check requires, among other things, that
    the appointment's `procedure_type` equal the linked color formula's
    procedure type; a mismatch is an `ERR_INVALID_REQUEST`."

    Design: Corner/calculations/calc_procedure_type_must_match_formula
    """
    ctx = setup_booking_ready(pigment_count=2, procedure_type="BROWS")
    payload = create_appointment_payload(
        ctx["client"]["id"],
        ctx["technician"]["id"],
        ctx["formula"]["id"],
        ctx["patch_test"]["id"],
        procedure_type="EYELINER",  # formula is BROWS
        scheduled_start="2026-01-06T10:00:00Z",
    )
    res = api.create_appointment(payload, FRONT)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_client_risk_score_is_server_computed(api):
    """PRD §3.2: "The client's `risk_score` is computed by a weighted sum: the
    medical-flag count is weighted by 8, the prior-adverse-reaction count is
    weighted by 12, and a sensitivity figure is weighted by 5; the three
    weighted terms are summed into an integer with no rounding."

    Design: Corner/entities/entity_client_computed_risk_input_ignored
    """
    studio = get_success_data(
        api.create_studio(create_studio_payload(sterile_kit_total=5), ADMIN)
    )
    client = validate_success(
        api.create_client(
            create_client_payload(
                studio["id"],
                full_name="Calc",
                medical_flag_count=1,
                prior_adverse_reactions=0,
                skin_sensitivity_self=0,
            ),
            FRONT,
        ),
        201,
    )
    assert client["risk_score"] == 8, (
        f"8*1 + 12*0 + 5*0 = 8, got {client['risk_score']}"
    )
    assert client["risk_band"] == "STANDARD"
