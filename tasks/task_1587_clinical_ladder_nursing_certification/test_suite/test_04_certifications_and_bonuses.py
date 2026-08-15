"""Certification integrity rules, renewal windows, and bonus accrual
arithmetic (PRD §3.3)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_budget_line,
    create_certification,
    create_certification_payload,
    create_nurse,
    get_certification,
    list_bonuses,
    run_ops_cycle,
    set_clock,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]


class TestCertificationIntegrity:
    def test_certification_date_order_violation(self, api):
        """PRD §3.3: "The expiry must be strictly later than the grant date,
        else `ERR_CERTIFICATION_DATE_ORDER` (HTTP 422)."

        Design: Corner/validations/certification_date_order_violation
        """
        nurse = create_nurse(employee_code="RN-CD1", full_name="Cd One")
        resp = api.create_certification(
            create_certification_payload(
                nurse_id=nurse["id"], obtained_on="2026-01-01T00:00:00Z",
                expires_on="2026-01-01T00:00:00Z",
            ),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_CERTIFICATION_DATE_ORDER, 422)

    def test_renewal_cross_track_mismatch(self, api):
        """PRD §3.3: "An optional `renewal_of_id` may chain the row to an
        earlier certification of the same nurse, and when supplied it must
        resolve to a certification of the same nurse in the same track, else
        `ERR_RENEWAL_MISMATCH` (HTTP 422)."

        Design: Corner/validations/renewal_cross_track_mismatch
        """
        nurse = create_nurse(employee_code="RN-RM1", full_name="Rm One")
        old = create_certification(
            nurse["id"], track="SPECIALTY", exam_fee_cents=100000,
            obtained_on="2023-01-01T00:00:00Z", expires_on="2026-06-01T00:00:00Z",
        )
        resp = api.create_certification(
            create_certification_payload(
                nurse_id=nurse["id"], track="BASIC",
                obtained_on="2026-07-01T00:00:00Z",
                expires_on="2031-07-01T00:00:00Z", renewal_of_id=old["id"],
            ),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_RENEWAL_MISMATCH, 422)


class TestSameTrackCurrencyWindow:
    def _nurse_with_current_basic(self, api):
        nurse = create_nurse(employee_code="RN-T", full_name="Nurse T")
        cert = create_certification(
            nurse["id"], track="BASIC", exam_fee_cents=40000,
            obtained_on="2024-01-01T00:00:00Z", expires_on="2027-01-01T00:00:00Z",
        )
        return nurse, cert

    def test_overlapping_same_track_current_renewal_rejected(self, api):
        """PRD §3.3: "a renewal chain is permitted only when the renewed
        certification has already lapsed or its expiry falls at or before the
        new grant date. Violations surface `ERR_CERTIFICATION_OVERLAP`
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/certification_renewal_temporal_supersede_same_track
        """
        set_clock("2026-08-01T00:00:00Z")
        nurse, cert = self._nurse_with_current_basic(api)
        resp = api.create_certification(
            create_certification_payload(
                nurse_id=nurse["id"], track="BASIC", exam_fee_cents=45000,
                obtained_on="2026-06-01T00:00:00Z",
                expires_on="2029-06-01T00:00:00Z", renewal_of_id=cert["id"],
            ),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_CERTIFICATION_OVERLAP, 409)

    def test_renewal_accepted_after_original_lapsed(self, api):
        """PRD §3.3: "...a renewal chain is permitted only when the renewed
        certification has already lapsed or its expiry falls at or before the
        new grant date."
        PRD §3.3: "when the ops-run sweep finds a `CURRENT` certification whose
        `expires_on` has been reached by the logical clock, it lapses to
        `LAPSED`..."

        Design: Difficulty/resource_temporal_overlap/certification_renewal_temporal_supersede_same_track
        """
        set_clock("2026-08-01T00:00:00Z")
        nurse, cert = self._nurse_with_current_basic(api)
        set_clock("2027-01-02T00:00:00Z")
        run_ops_cycle()
        lapsed = get_certification(cert["id"])
        assert lapsed["status"] == "LAPSED", (
            "sweep past expires_on must lapse the original certification"
        )
        renewed = validate_success(
            api.create_certification(
                create_certification_payload(
                    nurse_id=nurse["id"], track="BASIC", exam_fee_cents=45000,
                    obtained_on="2027-01-02T00:00:00Z",
                    expires_on="2030-01-02T00:00:00Z", renewal_of_id=cert["id"],
                ),
                ADMIN,
            ),
            201,
        )
        assert renewed["id"], "renewal after lapse of the original must be accepted"
        assert renewed["status"] == "CURRENT"


class TestCertificationBonusAmounts:
    def test_first_time_vs_renewal_multiplier(self, api):
        """PRD §3.3: "The base amount tiers by track: 50,000 cents ($500.00)
        for `BASIC`, 100,000 cents ($1,000.00) for `SPECIALTY`, and 175,000
        cents ($1,750.00) for `ADVANCED`. A first-time credential — one whose
        `renewal_of_id` is null — multiplies the base by one and a half, while
        a renewal applies a multiplier of one. The multiplied base is rounded
        half-up to integer cents first, and only then is a tenure bonus of
        25,000 cents ($250.00) added when the holder's `tenure_years` has
        reached at least 10."

        Design: Difficulty/combinatorial_formula/certification_bonus_nested_rounding_order
        """
        set_clock("2026-08-01T00:00:00Z")
        create_budget_line("ICU-4W", 2027, 9000000)
        nurse_x = create_nurse(employee_code="RN-X", full_name="Nurse X",
                               hire_date="2021-08-01T00:00:00Z",
                               home_unit="ICU-4W")
        nurse_y = create_nurse(employee_code="RN-Y", full_name="Nurse Y",
                               hire_date="2014-08-01T00:00:00Z",
                               home_unit="ICU-4W")
        # X: first-time SPECIALTY, tenure < 10 -> rhu(100000 * 1.5) + 0.
        cert_x = create_certification(
            nurse_x["id"], track="SPECIALTY", exam_fee_cents=100000,
            obtained_on="2026-07-01T00:00:00Z", expires_on="2031-07-01T00:00:00Z",
        )
        bonuses_x = list_bonuses(cert_x["id"])
        assert len(bonuses_x) == 1
        assert bonuses_x[0]["bonus_amount_cents"] == 150000
        assert bonuses_x[0]["status"] == "ACCRUED"
        # Y: renewal SPECIALTY with tenure >= 10 -> rhu(100000 * 1.0) + 25000.
        # Old credential's expiry (2025-01-01) falls before the new grant date,
        # so the renewal chain is permitted (PRD §3.3 adjacency rule).
        old_y = create_certification(
            nurse_y["id"], track="SPECIALTY", exam_fee_cents=100000,
            obtained_on="2020-01-01T00:00:00Z", expires_on="2025-01-01T00:00:00Z",
        )
        cert_y = create_certification(
            nurse_y["id"], track="SPECIALTY", exam_fee_cents=100000,
            obtained_on="2026-07-01T00:00:00Z", expires_on="2031-07-01T00:00:00Z",
            renewal_of_id=old_y["id"],
        )
        bonuses_y = list_bonuses(cert_y["id"])
        assert len(bonuses_y) == 1
        assert bonuses_y[0]["bonus_amount_cents"] == 125000, (
            "renewal multiplier 1.0 plus 25000 tenure bonus -> 125000, got "
            f"{bonuses_y[0]['bonus_amount_cents']}"
        )

    def test_first_time_advanced_with_tenure_bonus(self, api):
        """PRD §3.3: "The multiplied base is rounded half-up to integer cents
        first, and only then is a tenure bonus of 25,000 cents ($250.00) added
        when the holder's `tenure_years` has reached at least 10."

        Design: Difficulty/combinatorial_formula/certification_bonus_nested_rounding_order
        """
        set_clock("2026-08-01T00:00:00Z")
        create_budget_line("ICU-4W", 2027, 9000000)
        nurse_z = create_nurse(employee_code="RN-Z", full_name="Nurse Z",
                               hire_date="2015-08-01T00:00:00Z",
                               home_unit="ICU-4W")
        # Z: first-time ADVANCED, tenure 11 years -> rhu(175000 * 1.5) + 25000.
        cert_z = create_certification(
            nurse_z["id"], track="ADVANCED", exam_fee_cents=200000,
            obtained_on="2026-07-01T00:00:00Z", expires_on="2031-07-01T00:00:00Z",
        )
        bonuses_z = list_bonuses(cert_z["id"])
        assert len(bonuses_z) == 1
        assert bonuses_z[0]["bonus_amount_cents"] == 287500, (
            "first-time ADVANCED with tenure >= 10 -> 262500 + 25000 = 287500, "
            f"got {bonuses_z[0]['bonus_amount_cents']}"
        )
