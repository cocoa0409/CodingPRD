"""License-suspend cascade, no-show strike block, deposit & kit conservation,
and boundary-precision threshold checks.

Translates queue-A transitive_cascade, compensating_invariant, and
boundary_precision_check instances.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    get_success_data,
    TEST_USERS,
    make_technician_headers,
    setup_booking_ready,
    setup_started_appointment,
    setup_deposited_appointment,
    book_initial_appointment,
    pay_deposit,
    set_clock,
    create_studio_payload,
    create_client_payload,
    assert_studio_kit_conservation,
)

FRONT = TEST_USERS["front_desk_headers"]
ADMIN = TEST_USERS["studio_admin_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
TECH = TEST_USERS["technician_headers"]


# ─────────────────────────────────────────────────────────────────────────────
# Queue A: transitive_cascade
# ─────────────────────────────────────────────────────────────────────────────
class TestLicenseSuspendCascade:
    """suspend -> appointment VOIDED -> kit restore + deposit REFUND + posture
    FROZEN (depth-3)."""

    def _started_single_tech(self, api):
        # The suspension cascade voids only appointments in BOOKED lifecycle (PRD
        # §2.6 / §3.1: "every appointment of that technician currently in BOOKED
        # lifecycle is voided"). A BOOKED + DEPOSIT_PAID appointment therefore
        # exercises the void + deposit-refund branch of the cascade. (A kit is
        # consumed only at /start, which moves the appointment to IN_PROCEDURE — a
        # non-BOOKED lifecycle the cascade does not touch — so kit_consumed stays
        # false here, consistent with the PRD.) sterile_kit_total=3, single
        # technician so suspension drives posture to FROZEN.
        ctx, appt = setup_deposited_appointment(sterile_kit_total=3, scheduled_start="2026-01-06T10:00:00Z")
        return ctx, appt

    def test_suspend_voids_appointment_restores_kit_refunds_deposit(self, api):
        """PRD §2.6: "every appointment of that technician currently in `BOOKED`
        lifecycle is voided (moved to `VOIDED`); for each voided appointment
        whose sterile kit had already been consumed, the kit is restored; for
        each voided appointment whose payment was in `DEPOSIT_PAID`, a deposit
        refund is issued and that appointment's payment moves to `REFUNDED`".

        Design: Difficulty/transitive_cascade/tc_license_suspend_void_kit_deposit_posture_depth3
        """
        ctx, appt = self._started_single_tech(api)
        studio_pre = get_success_data(api.get_studio(ctx["studio"]["id"], ADMIN))
        validate_success(
            api.suspend_license(
                ctx["technician"]["id"],
                {"expected_studio_version": studio_pre["version"]},
                COMPLIANCE,
            ),
            200,
        )
        voided = validate_success(api.get_appointment(appt["id"], COMPLIANCE), 200)
        assert voided["lifecycle_status"] == "VOIDED"
        assert voided["kit_consumed"] is False
        assert voided["payment_status"] == "REFUNDED"

    def test_suspend_recomputes_kit_ledger_and_freezes_posture(self, api):
        """PRD §2.6: "the kit is restored" and "the studio's compliance posture
        is then recomputed".
        PRD §2.10: "it is `FROZEN` when no technician has license status
        `LICENSE_ACTIVE`."

        Design: Difficulty/transitive_cascade/tc_license_suspend_void_kit_deposit_posture_depth3
        """
        ctx, appt = self._started_single_tech(api)
        studio_pre = get_success_data(api.get_studio(ctx["studio"]["id"], ADMIN))
        validate_success(
            api.suspend_license(
                ctx["technician"]["id"],
                {"expected_studio_version": studio_pre["version"]},
                COMPLIANCE,
            ),
            200,
        )
        studio_after = validate_success(api.get_studio(ctx["studio"]["id"], ADMIN), 200)
        assert studio_after["sterile_kit_consumed"] == 0
        assert studio_after["compliance_posture"] == "FROZEN"
        assert_studio_kit_conservation(studio_after)


class TestNoShowStrikeBlock:
    """3rd no-show -> no_show_strikes 3 -> client_status BLOCKED (depth-2)."""

    def _client_with_two_no_shows(self, api):
        ctx = setup_booking_ready(sterile_kit_total=10)
        client_id = ctx["client"]["id"]
        # First two BOOKED appointments deposited then no-showed past scheduled_start.
        for start, noshow_clock in (
            ("2026-01-06T10:00:00Z", "2026-01-06T11:00:00Z"),
            ("2026-01-08T10:00:00Z", "2026-01-08T11:00:00Z"),
        ):
            appt = book_initial_appointment(ctx, scheduled_start=start)
            pay_deposit(appt)
            set_clock(noshow_clock)
            get_success_data(api.no_show(appt["id"], FRONT))
        return ctx

    def test_third_no_show_sets_strikes_to_three(self, api):
        """PRD §3.9: "A no-show emits a `FORFEIT` deposit transaction ...,
        recomputes the client's `no_show_strikes` upward by one ...".
        PRD §3.2: "The derived `no_show_strikes` is the count of this client's
        appointments in lifecycle `NO_SHOW`".

        Design: Difficulty/transitive_cascade/tc_no_show_strike_block_depth2
        """
        ctx = self._client_with_two_no_shows(api)
        appt3 = book_initial_appointment(ctx, scheduled_start="2026-01-10T10:00:00Z")
        pay_deposit(appt3)
        set_clock("2026-01-10T11:00:00Z")
        get_success_data(api.no_show(appt3["id"], FRONT))
        client = validate_success(api.get_client(ctx["client"]["id"], FRONT), 200)
        assert client["no_show_strikes"] == 3

    def test_third_no_show_blocks_client(self, api):
        """PRD §3.2: "the derived `client_status` is `BLOCKED` when the strike
        count is at least 3 and `ACTIVE` when it is below 3."

        Design: Difficulty/transitive_cascade/tc_no_show_strike_block_depth2
        """
        ctx = self._client_with_two_no_shows(api)
        appt3 = book_initial_appointment(ctx, scheduled_start="2026-01-10T10:00:00Z")
        pay_deposit(appt3)
        set_clock("2026-01-10T11:00:00Z")
        get_success_data(api.no_show(appt3["id"], FRONT))
        client = validate_success(api.get_client(ctx["client"]["id"], FRONT), 200)
        assert client["client_status"] == "BLOCKED"


# ─────────────────────────────────────────────────────────────────────────────
# Queue A: compensating_invariant
# ─────────────────────────────────────────────────────────────────────────────
class TestDepositConservationOnVoid:
    """After void, deposit_paid_cents back to 0; ledger sum(CHARGE)-sum(REFUND)==0."""

    def test_void_refunds_deposit_to_zero(self, api):
        """PRD §3.9: "if the payment status was `DEPOSIT_PAID`, a `REFUND`
        deposit transaction is emitted for the `deposit_paid_cents` and the
        payment status moves to `REFUNDED`."

        Design: Difficulty/compensating_invariant/ci_deposit_conservation_on_void
        """
        ctx, appt = setup_deposited_appointment(scheduled_start="2026-01-06T10:00:00Z")
        voided = validate_success(api.void_appointment(appt["id"], COMPLIANCE), 200)
        assert voided["payment_status"] == "REFUNDED"
        assert voided["deposit_paid_cents"] == 0

    def test_void_ledger_holds_charge_and_offsetting_refund(self, api):
        """PRD §3.6: "The appointment's derived `deposit_paid_cents` is the sum
        of `CHARGE` amounts minus the sum of `REFUND` amounts across that
        appointment's transactions".

        Design: Difficulty/compensating_invariant/ci_deposit_conservation_on_void
        """
        ctx, appt = setup_deposited_appointment(scheduled_start="2026-01-06T10:00:00Z")
        validate_success(api.void_appointment(appt["id"], COMPLIANCE), 200)
        txns, _ = validate_paginated(
            api.list_deposit_transactions(COMPLIANCE, params={"appointment_id": appt["id"]})
        )
        charges = sum(t["amount_cents"] for t in txns if t["txn_type"] == "CHARGE")
        refunds = sum(t["amount_cents"] for t in txns if t["txn_type"] == "REFUND")
        assert charges == 13000, f"expected one CHARGE of 13000, got {charges}"
        assert refunds == 13000, f"expected one REFUND of 13000, got {refunds}"
        assert charges - refunds == 0, "deposit conservation: net movement must be 0"


class TestKitConservationOnVoid:
    """Consume 1 kit then void restores it; consumed + available == total."""

    def test_kit_consumed_and_available_mid_procedure(self, api):
        """PRD §2.10: "The derived `sterile_kit_available` is the total minus the
        consumed count" and "consumed plus available always equals total."

        Design: Difficulty/compensating_invariant/ci_kit_conservation_on_void
        """
        ctx, appt = setup_started_appointment(sterile_kit_total=3, scheduled_start="2026-01-06T10:00:00Z")
        studio_mid = validate_success(api.get_studio(ctx["studio"]["id"], ADMIN), 200)
        assert studio_mid["sterile_kit_consumed"] == 1
        assert studio_mid["sterile_kit_available"] == 2
        assert_studio_kit_conservation(studio_mid)

    def test_void_restores_kit_preserving_conservation(self, api):
        """PRD §3.9: "A `ComplianceOfficer` may void a `BOOKED` appointment
        directly ... voiding is permitted only while the lifecycle is `BOOKED`"
        and "preserving kit conservation".
        PRD §2.10: "consumed plus available always equals total."

        The void endpoint only accepts a BOOKED appointment, and a BOOKED
        appointment has never consumed a kit (a kit is consumed only at /start,
        which moves the appointment to IN_PROCEDURE). Voiding therefore leaves the
        kit ledger intact at its conserved values.

        Design: Difficulty/compensating_invariant/ci_kit_conservation_on_void
        """
        ctx, appt = setup_deposited_appointment(sterile_kit_total=3, scheduled_start="2026-01-06T10:00:00Z")
        validate_success(api.void_appointment(appt["id"], COMPLIANCE), 200)
        studio_after = validate_success(api.get_studio(ctx["studio"]["id"], ADMIN), 200)
        assert studio_after["sterile_kit_consumed"] == 0
        assert studio_after["sterile_kit_available"] == 3
        assert_studio_kit_conservation(studio_after)


# ─────────────────────────────────────────────────────────────────────────────
# Queue A: boundary_precision_check
# ─────────────────────────────────────────────────────────────────────────────
class TestRiskThresholdThirtyInclusive:
    """risk_score 30 -> HIGH_RISK (inclusive); 29 -> STANDARD."""

    def test_score_exactly_30_is_high_risk(self, api):
        """PRD §3.2: "it is `HIGH_RISK` when the `risk_score` is at least 30, and
        `STANDARD` when the `risk_score` is below 30."

        Design: Difficulty/boundary_precision_check/bpc_risk_threshold_30_inclusive
        """
        studio = get_success_data(api.create_studio(create_studio_payload(sterile_kit_total=5), ADMIN))
        c30 = validate_success(
            api.create_client(
                create_client_payload(
                    studio["id"],
                    full_name="At30",
                    medical_flag_count=1,
                    prior_adverse_reactions=1,
                    skin_sensitivity_self=2,
                ),
                FRONT,
            ),
            201,
        )
        assert c30["risk_score"] == 30, f"8*1+12*1+5*2=30, got {c30['risk_score']}"
        assert c30["risk_band"] == "HIGH_RISK"

    def test_score_29_is_standard(self, api):
        """PRD §3.2: "it is `HIGH_RISK` when the `risk_score` is at least 30, and
        `STANDARD` when the `risk_score` is below 30."

        Design: Difficulty/boundary_precision_check/bpc_risk_threshold_30_inclusive
        """
        studio = get_success_data(api.create_studio(create_studio_payload(sterile_kit_total=5), ADMIN))
        c29 = validate_success(
            api.create_client(
                create_client_payload(
                    studio["id"],
                    full_name="At29",
                    medical_flag_count=3,
                    prior_adverse_reactions=0,
                    skin_sensitivity_self=1,
                ),
                FRONT,
            ),
            201,
        )
        assert c29["risk_score"] == 29, f"8*3+12*0+5*1=29, got {c29['risk_score']}"
        assert c29["risk_band"] == "STANDARD"


class TestKitAvailableZeroBlocksStart:
    """One kit allows the first start; the second start finds available==0."""

    def _two_deposited_appointments_one_kit(self, api):
        set_clock("2026-01-01T00:00:00Z")
        studio = get_success_data(api.create_studio(create_studio_payload(sterile_kit_total=1), ADMIN))
        tech = get_success_data(
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
        formula = get_success_data(
            api.create_color_formula(
                {"studio_id": studio["id"], "name": "WT", "procedure_type": "BROWS", "pigment_count": 2},
                ADMIN,
            )
        )
        client = get_success_data(api.create_client(create_client_payload(studio["id"]), FRONT))
        get_success_data(
            api.create_consent_record(
                {"client_id": client["id"], "consent_type": "PROCEDURE_CONSENT", "age_verified": True, "signed_by_name": "C"},
                FRONT,
            )
        )
        pt1 = get_success_data(api.create_patch_test({"client_id": client["id"]}, TECH))
        pt2 = get_success_data(api.create_patch_test({"client_id": client["id"]}, TECH))
        set_clock("2026-01-03T01:00:00Z")
        tech_headers = make_technician_headers(tech["id"])
        get_success_data(api.read_patch_test(pt1["id"], {"reaction_grade": 1}, tech_headers))
        get_success_data(api.read_patch_test(pt2["id"], {"reaction_grade": 1}, tech_headers))
        appt1 = get_success_data(
            api.create_appointment(
                {
                    "client_id": client["id"],
                    "technician_id": tech["id"],
                    "color_formula_id": formula["id"],
                    "patch_test_id": pt1["id"],
                    "procedure_type": "BROWS",
                    "scheduled_start": "2026-01-06T10:00:00Z",
                },
                FRONT,
            )
        )
        appt2 = get_success_data(
            api.create_appointment(
                {
                    "client_id": client["id"],
                    "technician_id": tech["id"],
                    "color_formula_id": formula["id"],
                    "patch_test_id": pt2["id"],
                    "procedure_type": "BROWS",
                    "scheduled_start": "2026-01-06T12:00:00Z",
                },
                FRONT,
            )
        )
        pay_deposit(appt1)
        pay_deposit(appt2)
        return studio, tech, appt1, appt2

    def test_first_start_consumes_only_kit_to_zero(self, api):
        """PRD §3.6: "On a successful start the appointment's `kit_consumed` is
        set true, the studio's `sterile_kit_consumed` increases by 1 and
        `sterile_kit_available` is recomputed".

        Design: Difficulty/boundary_precision_check/bpc_kit_available_zero_blocks_start
        """
        studio, tech, appt1, appt2 = self._two_deposited_appointments_one_kit(api)
        validate_success(api.start_appointment(appt1["id"], make_technician_headers(tech["id"])), 200)
        studio_after = validate_success(api.get_studio(studio["id"], ADMIN), 200)
        assert studio_after["sterile_kit_available"] == 0

    def test_second_start_with_no_kit_rejected(self, api):
        """PRD §3.6: "the studio's `compliance_posture` is `OPEN`, at least one
        sterile kit is available ... A license or posture failure at start raises
        `ERR_LICENSE_INVALID`; an absence of an available kit raises
        `ERR_NO_STERILE_KIT`".

        After the first start consumes the only kit, available reaches 0, which is
        BOTH a no-kit condition and (per PRD §2.10) a RESTRICTED posture (no kit but
        a licensed tech remains). The PRD lists the posture-OPEN precondition before
        the kit-available precondition, so a faithful implementation may report the
        posture failure (`ERR_LICENSE_INVALID`) or the kit shortage
        (`ERR_NO_STERILE_KIT`); the PRD does not uniquely pin which of the two
        simultaneously-tripped gates wins.

        Design: Difficulty/boundary_precision_check/bpc_kit_available_zero_blocks_start
        """
        studio, tech, appt1, appt2 = self._two_deposited_appointments_one_kit(api)
        tech_headers = make_technician_headers(tech["id"])
        validate_success(api.start_appointment(appt1["id"], tech_headers), 200)
        res = api.start_appointment(appt2["id"], tech_headers)
        validate_error_is_one_of(res, ["ERR_NO_STERILE_KIT", "ERR_LICENSE_INVALID"])
