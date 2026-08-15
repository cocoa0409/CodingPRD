"""ISIR import: cohort boundary classification, the pinned seven-step EFC
methodology, field constraints, the receipt window, and computed-field
suppression (PRD §2.6, §2.7, §3.3)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_isir_record,
    create_isir_payload,
    import_isir,
    register_student,
    setup_open_aid_year,
    validate_error,
    validate_success,
)

OFFICER = TEST_USERS["aid_officer_headers"]


class TestPriorityDeadlineCohortBoundary:
    def test_received_exactly_on_deadline_is_priority(self, api):
        """PRD §3.3: "The `cohort` is set to `PRIORITY` when `received_at` is on or before the aid year's `priority_deadline` and to `STANDARD` otherwise; it is fixed at import and never recomputed even if the deadline later changes."

        Design: Difficulty/resource_temporal_overlap/priority_deadline_closed_boundary_cohort_assignment
        """
        env = setup_open_aid_year()
        student = register_student("333445555", full_name="On Deadline",
                                   email="t1@example.edu")
        resp = api.create_isir_record(
            create_isir_payload(student["id"], env["aid_year"]["id"],
                                received_at="2026-03-01T00:00:00Z"),
            OFFICER)
        isir = validate_success(resp, 201)
        assert_isir_record(isir)
        assert isir["cohort"] == "PRIORITY"

    def test_received_one_second_after_deadline_is_standard(self, api):
        """PRD §3.3: "The `cohort` is set to `PRIORITY` when `received_at` is on or before the aid year's `priority_deadline` and to `STANDARD` otherwise; it is fixed at import and never recomputed even if the deadline later changes."

        Design: Difficulty/resource_temporal_overlap/priority_deadline_closed_boundary_cohort_assignment
        """
        env = setup_open_aid_year()
        student = register_student("123456789", full_name="One Second Late",
                                   email="t2@example.edu")
        resp = api.create_isir_record(
            create_isir_payload(student["id"], env["aid_year"]["id"],
                                received_at="2026-03-01T00:00:01Z"),
            OFFICER)
        isir = validate_success(resp, 201)
        assert isir["cohort"] == "STANDARD"



class TestEfcTieredMarginalFormula:
    def test_efc_crosses_all_tiers_with_asset_contribution(self, api, aid_officer_headers):
        """PRD §3.3: "Step four applies tiered marginal rates to available income: the first 500,000 cents at 22 percent, the portion above 500,000 up to 1,500,000 cents at 35 percent, and any remainder above 1,500,000 cents at 47 percent — with each tier's product rounded half-up to whole cents before the tiers are summed, that rounding order being pinned."
        PRD §3.3: "Step five derives the asset contribution: when `asset_net_worth_cents` exceeds the asset allowance of 1,000,000 cents, the contribution is the floor of the excess over that allowance multiplied by 5.64 and divided by 100; otherwise the contribution is zero."

        Design: Difficulty/combinatorial_formula/efc_tiered_marginal_with_asset_and_household_mode_a
        """
        env = setup_open_aid_year()
        student = register_student(
            "123456789", full_name="Wealthy Indep", email="w@example.edu",
            residency="OUT_OF_STATE", dependency_status="INDEPENDENT",
            grade_level=3)
        isir = import_isir(student["id"], env["aid_year"]["id"],
                           household_size=2, number_in_college=1,
                           agi_cents=18000000, untaxed_income_cents=500000,
                           asset_net_worth_cents=3000000)
        # INDEPENDENT household 2 -> IPA 2_200_000; AI = 16_300_000;
        # IC = 110_000 + 350_000 + 6_956_000 = 7_416_000; AC = 112_800.
        assert isir["efc_provisional_cents"] == 7528800
        assert isir["efc_official_cents"] == 7528800
        assert isir["efc_verified_cents"] is None

    def test_efc_household_size_shift_changes_result_nonlinearly(self, api, aid_officer_headers):
        """PRD §3.3: "Step two looks up the income protection allowance from two fixed tables, indexed by `dependency_status` and by household size capped at five (a household of five or more uses the fifth entry): for a `DEPENDENT` student the allowance is 1,000,000 cents for a household of one, 1,500,000 for two, 2,000,000 for three, 2,400,000 for four, and 2,800,000 for five or more; for an `INDEPENDENT` student the five entries are 1,700,000, 2,200,000, 2,600,000, 3,000,000, and 3,300,000 cents."
        PRD §3.3: "Step four applies tiered marginal rates to available income: the first 500,000 cents at 22 percent, the portion above 500,000 up to 1,500,000 cents at 35 percent, and any remainder above 1,500,000 cents at 47 percent — with each tier's product rounded half-up to whole cents before the tiers are summed, that rounding order being pinned."

        Design: Difficulty/combinatorial_formula/efc_tiered_marginal_with_asset_and_household_mode_a
        """
        env = setup_open_aid_year()
        student = register_student(
            "333445555", full_name="Wealthy Indep Three", email="w3@example.edu",
            residency="OUT_OF_STATE", dependency_status="INDEPENDENT",
            grade_level=3)
        isir = import_isir(student["id"], env["aid_year"]["id"],
                           household_size=3, number_in_college=1,
                           agi_cents=18000000, untaxed_income_cents=500000,
                           asset_net_worth_cents=3000000)
        # INDEPENDENT household 3 -> IPA 2_600_000; AI = 15_900_000;
        # IC = 110_000 + 350_000 + 6_768_000 = 7_228_000; AC = 112_800.
        assert isir["efc_provisional_cents"] == 7340800
        assert isir["efc_official_cents"] == 7340800


class TestIsirValidation:
    def test_dependent_household_size_below_floor_rejected(self, api, aid_officer_headers):
        """PRD §3.3: "`household_size` must be at least 2 for a `DEPENDENT` student and at least 1 for an `INDEPENDENT` student, `number_in_college` must be at least 1 and no more than `household_size`, and the three money fields must be non-negative — violations fail with `ERR_FIELD_CONSTRAINT`."

        Design: Corner/entities/isir_household_constraint_dependent_minimum
        """
        env = setup_open_aid_year()
        student = register_student("555667777", full_name="Tiny Household",
                                   email="hh@example.edu",
                                   dependency_status="DEPENDENT")
        resp = api.create_isir_record(
            create_isir_payload(student["id"], env["aid_year"]["id"],
                                household_size=1, number_in_college=1),
            aid_officer_headers)
        validate_error(resp, ApiErrorId.ERR_FIELD_CONSTRAINT)

    def test_client_supplied_computed_efc_is_ignored(self, api, aid_officer_headers):
        """PRD §3.3: "The EFC exists in three fields on the record: `efc_provisional_cents`, computed at import from as-reported data; `efc_verified_cents`, which stays null (serializing as null) until verification completes satisfied; and `efc_official_cents`, the figure packaging actually uses — the verified figure once the linked verification case is `COMPLETED_SATISFIED`, and the provisional figure otherwise."
        PRD §2.7: "Every request is validated against an ordered ladder of eighteen checks."

        Design: Corner/entities/computed_field_input_ignored_on_isir
        """
        env = setup_open_aid_year()
        student = register_student("555667777", full_name="Computed",
                                   email="comp@example.edu")
        payload = create_isir_payload(student["id"], env["aid_year"]["id"],
                                      agi_cents=4500000,
                                      asset_net_worth_cents=50000)
        payload["efc_provisional_cents"] = 1  # computed field: must not take
        resp = api.create_isir_record(payload, aid_officer_headers)
        isir = validate_success(resp, 201)
        # Server-computed value for the as-reported data: AI = 2_100_000;
        # IC = 110_000 + 350_000 + 282_000 = 742_000; no asset contribution.
        assert isir["efc_provisional_cents"] == 742000
        assert isir["efc_official_cents"] == 742000

    def test_received_at_in_the_future_rejected(self, api, aid_officer_headers):
        """PRD §2.7 (rung 12): "`received_at` must be at or before the current logical-clock reading and no earlier than one year before the aid year's own `created_at` — otherwise `ERR_RECEIVED_AT_OUT_OF_WINDOW` (422)."
        PRD §2.6: "All notions of "now" in the system — the receipt-window check on ISIR import, the `sent_at` stamp on a notification, the `completed_at` stamp on a verification case — read from a server-held logical clock, never from wall-clock time."

        Design: Corner/validations/isir_future_received_at_rejected
        """
        env = setup_open_aid_year()  # logical clock reads 2026-09-01
        student = register_student("555667777", full_name="Future Dated",
                                   email="fd@example.edu")
        resp = api.create_isir_record(
            create_isir_payload(student["id"], env["aid_year"]["id"],
                                received_at="2027-01-01T00:00:00Z"),
            aid_officer_headers)
        validate_error(resp, ApiErrorId.ERR_RECEIVED_AT_OUT_OF_WINDOW)
