"""Post-registration maintenance: the three-input §8/§9 grace fee, the timely
fee + cycle increment, the grace->expire terminal sweep, and the OCC stale-version
guard on maintenance-filing creation.

Sources: Difficulty/combinatorial_formula, Corner/calculations,
Corner/state_machines, Corner/cross_cutting_complexity_layers.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    setup_registered_application,
    set_clock,
    examiner_headers,
)
from test_helpers.factories import create_maintenance_filing_payload


class TestMaintenanceFeeGraceCombinatorial:
    """A SECTION_8_AND_9 filing on a 2-class registration in grace = 125000
    (45000 §8 + 60000 §9 + 20000 grace surcharge); in_grace_period == true."""

    def test_section_8_and_9_grace_two_class_fee_is_125000(self, api):
        """PRD §3.5: "The base is 22,500 cents per class for the §8 component; when
        the filing_type is SECTION_8_AND_9, a further 30,000 cents per class for the
        §9 component is added to the base. When the filing is in the grace period, a
        surcharge of 10,000 cents per class is added"

        Design: Difficulty/combinatorial_formula/maintenance_fee_three_input_branch_mode_a
        """
        base = setup_registered_application(
            clock="2026-01-01T00:00:00Z", class_numbers=(9, 25), mark_text="NIMBUS")
        reg = base["registration"]
        # Due 2032-01-01; grace through 2032-06-29. File at 2032-03-01.
        set_clock("2032-03-01T00:00:00Z")
        filing = validate_success(api.create_maintenance_filing(
            create_maintenance_filing_payload(reg["id"], "SECTION_8_AND_9", reg["version"]),
            base["att_headers"]), 201)
        assert filing["fee_cents"] == 125000, (
            f"§8&9 grace 2-class should be 45000+60000+20000=125000, got {filing['fee_cents']}")

    def test_section_8_and_9_grace_in_grace_period_true(self, api):
        """PRD §3.5: "The server derives in_grace_period, true exactly when filed_at
        falls strictly after next_maintenance_due_at and on or before
        next_maintenance_due_at plus the 180-day grace window, which triggers a grace
        surcharge."

        Design: Difficulty/combinatorial_formula/maintenance_fee_three_input_branch_mode_a
        """
        base = setup_registered_application(
            clock="2026-01-01T00:00:00Z", class_numbers=(9, 25), mark_text="NIMBUS2")
        reg = base["registration"]
        set_clock("2032-03-01T00:00:00Z")
        filing = validate_success(api.create_maintenance_filing(
            create_maintenance_filing_payload(reg["id"], "SECTION_8_AND_9", reg["version"]),
            base["att_headers"]), 201)
        assert filing["in_grace_period"] is True


class TestTimelyMaintenanceFee:
    """A SECTION_8 1-class filing inside the open window (opens 2031-01-01, due
    2032-01-01) filed 2031-06-01 has no surcharge (fee 22500); acceptance
    increments maintenance_cycle to 1 and keeps the registration ACTIVE."""

    def _file(self, api, mark):
        base = setup_registered_application(
            clock="2026-01-01T00:00:00Z", class_numbers=(9,), mark_text=mark)
        reg = base["registration"]
        set_clock("2031-06-01T00:00:00Z")
        filing = validate_success(api.create_maintenance_filing(
            create_maintenance_filing_payload(reg["id"], "SECTION_8", reg["version"]),
            base["att_headers"]), 201)
        return base, reg, filing

    def test_timely_section_8_fee_is_22500_no_surcharge(self, api):
        """PRD §3.5: "The base is 22,500 cents per class for the §8 component ... a
        timely (non-grace) filing carries no surcharge. The fee_cents is the base
        plus any surcharge."

        Design: Corner/calculations/timely_maintenance_fee_no_surcharge_and_cycle_increments
        """
        base, reg, filing = self._file(api, "TIMELY")
        assert filing["fee_cents"] == 22500
        assert filing["in_grace_period"] is False

    def test_acceptance_increments_cycle_and_keeps_active(self, api):
        """PRD §3.5: "A timely filing — one whose in_grace_period is false, accepted
        while the registration is ACTIVE and the filing is SUBMITTED — keeps the
        registration ACTIVE."
        PRD §3.5: "acceptance sets the filing's status to ACCEPTED, increments the
        registration's maintenance_cycle by one"

        Design: Corner/calculations/timely_maintenance_fee_no_surcharge_and_cycle_increments
        """
        base, reg, filing = self._file(api, "TIMELY2")
        reg_after = validate_success(api.accept_maintenance_filing(
            filing["id"], examiner_headers()), 200)
        assert reg_after["status"] == "ACTIVE"
        assert reg_after["maintenance_cycle"] == 1


class TestRegistrationGraceThenExpire:
    """A GRACE registration whose grace window elapsed expires to EXPIRED with
    next_maintenance_due_at null."""

    def test_grace_registration_expires_to_terminal(self, api):
        """PRD §3.5: "If the grace window then elapses — the current instant passes
        next_maintenance_due_at plus the 180-day grace window — a further system
        sweep moves the registration from GRACE to the terminal EXPIRED state and
        sets its next_maintenance_due_at to null."

        Design: Corner/state_machines/registration_grace_then_expire_terminal
        """
        base = setup_registered_application(
            clock="2026-01-01T00:00:00Z", class_numbers=(9,), mark_text="LAPSE")
        reg = base["registration"]
        # Due 2032-01-01; advance past due and enter grace.
        set_clock("2032-01-02T00:00:00Z")
        validate_success(api.enter_grace_registration(reg["id"], examiner_headers()), 200)
        # Grace window closes 2032-06-29; advance past it then expire.
        set_clock("2032-07-01T00:00:00Z")
        expired = validate_success(api.expire_registration(reg["id"], examiner_headers()), 200)
        assert expired["status"] == "EXPIRED"
        assert expired["next_maintenance_due_at"] is None


class TestMaintenanceOccStaleVersion:
    """Filing a MaintenanceFiling with expected_registration_version one less than
    current is rejected ERR_STALE_VERSION (412)."""

    def test_stale_registration_version_rejected(self, api):
        """PRD §2.6: "Filing a maintenance filing requires the request to carry
        expected_registration_version, a non-optional field holding the client's last
        observed version of the target Registration. If that value does not equal the
        registration's current version, the create is rejected with ERR_STALE_VERSION
        at HTTP 412."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_maintenance_create_rejected_412
        """
        base = setup_registered_application(
            clock="2026-01-01T00:00:00Z", class_numbers=(9,), mark_text="STALE")
        reg = base["registration"]
        set_clock("2031-06-01T00:00:00Z")  # window open so OCC is the only failing check
        res = api.create_maintenance_filing(
            create_maintenance_filing_payload(reg["id"], "SECTION_8", reg["version"] - 1),
            base["att_headers"])
        validate_error(res, "ERR_STALE_VERSION")
