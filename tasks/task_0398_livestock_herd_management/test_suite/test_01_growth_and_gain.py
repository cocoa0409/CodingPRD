"""Growth-rate calculations: lifetime vs interval ADG, and immutable weight records."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    set_clock,
    create_herd,
    create_animal,
    record_weight,
    assert_weight_record,
    ApiErrorId,
    TEST_USERS,
)

HM = TEST_USERS["herd_manager_headers"]


class TestAverageDailyGain:
    def test_lifetime_adg_uses_birth_baseline_over_age(self, api):
        """PRD §3.4: "The **lifetime** gain, stored on the animal as `lifetime_adg_kg`,
        is the latest recorded weight minus the animal's `birth_weight_kg`, divided by
        the number of whole days between the animal's `birth_date` and the latest
        weighing date."

        Design: Difficulty/dual_variant_calc/adg_lifetime_vs_interval_diverge
        """
        set_clock("2026-04-01T00:00:00Z")
        herd = create_herd(species="CATTLE")
        animal = create_animal(
            herd["id"], sex="FEMALE", birth_date="2026-01-01", birth_weight_kg=38.0
        )
        record_weight(animal["id"], 120.0, "2026-03-02")
        record_weight(animal["id"], 165.0, "2026-04-01")

        data = validate_success(api.get_animal(animal["id"], HM))
        assert data["lifetime_adg_kg"] == 1.411, (
            f"lifetime_adg_kg should be 1.411, got {data['lifetime_adg_kg']}"
        )

    def test_interval_adg_uses_prior_weighing_baseline(self, api):
        """PRD §3.4: "The **interval** gain, stored on each new weight record as
        `interval_adg_kg`, is this record's `weight_kg` minus the weight of the
        immediately prior record, divided by the number of whole days between that
        prior record's `weighed_at` and this record's `weighed_at`".

        Design: Difficulty/dual_variant_calc/adg_lifetime_vs_interval_diverge
        """
        set_clock("2026-04-01T00:00:00Z")
        herd = create_herd(species="CATTLE")
        animal = create_animal(
            herd["id"], sex="FEMALE", birth_date="2026-01-01", birth_weight_kg=38.0
        )
        record_weight(animal["id"], 120.0, "2026-03-02")
        wr2 = validate_success(
            api.create_weight(
                animal["id"], {"weighed_at": "2026-04-01", "weight_kg": 165.0}, HM
            ),
            expected_status=201,
        )
        assert wr2["interval_adg_kg"] == 1.5, (
            f"interval_adg_kg should be 1.5, got {wr2['interval_adg_kg']}"
        )

    def test_lifetime_and_interval_diverge_on_same_weighing(self, api):
        """PRD §3.4: "The **lifetime** gain, stored on the animal as `lifetime_adg_kg`,
        is the latest recorded weight minus the animal's `birth_weight_kg`, divided by
        the number of whole days between the animal's `birth_date` and the latest
        weighing date. The **interval** gain, stored on each new weight record as
        `interval_adg_kg`, is this record's `weight_kg` minus the weight of the
        immediately prior record, divided by the number of whole days between that
        prior record's `weighed_at` and this record's `weighed_at`".

        Design: Difficulty/dual_variant_calc/adg_lifetime_vs_interval_diverge
        """
        set_clock("2026-04-01T00:00:00Z")
        herd = create_herd(species="CATTLE")
        animal = create_animal(
            herd["id"], sex="FEMALE", birth_date="2026-01-01", birth_weight_kg=38.0
        )
        record_weight(animal["id"], 120.0, "2026-03-02")
        wr2 = validate_success(
            api.create_weight(
                animal["id"], {"weighed_at": "2026-04-01", "weight_kg": 165.0}, HM
            ),
            expected_status=201,
        )
        animal_after = validate_success(api.get_animal(animal["id"], HM))
        assert animal_after["lifetime_adg_kg"] == 1.411
        assert wr2["interval_adg_kg"] == 1.5
        assert animal_after["lifetime_adg_kg"] != wr2["interval_adg_kg"], (
            "lifetime and interval ADG must differ on the same weighing"
        )

    def test_first_weight_record_has_null_interval(self, api):
        """PRD §3.4: "For the very first weight record of an animal there is no prior
        record, so its `interval_adg_kg` is null."

        Design: Difficulty/dual_variant_calc/adg_lifetime_vs_interval_diverge
        """
        set_clock("2026-04-01T00:00:00Z")
        herd = create_herd(species="CATTLE")
        animal = create_animal(
            herd["id"], sex="FEMALE", birth_date="2026-01-01", birth_weight_kg=38.0
        )
        wr1 = validate_success(
            api.create_weight(
                animal["id"], {"weighed_at": "2026-03-02", "weight_kg": 120.0}, HM
            ),
            expected_status=201,
        )
        assert wr1["interval_adg_kg"] is None, (
            f"first record interval_adg_kg should be null, got {wr1['interval_adg_kg']}"
        )


class TestWeightRecordImmutability:
    def test_weight_record_has_no_version_field(self, api):
        """PRD §2.4: "a `WeightRecord` and a `TraceEvent` carry only `id` and
        `created_at` — they have no `updated_at` and no `version`, because once
        written they are never modified in place."

        Design: Corner/entities/weight_record_is_immutable_no_version_field
        """
        set_clock("2026-04-01T00:00:00Z")
        herd = create_herd(species="CATTLE")
        animal = create_animal(
            herd["id"], sex="STEER", birth_date="2026-01-01", birth_weight_kg=38.0
        )
        wr = validate_success(
            api.create_weight(
                animal["id"], {"weighed_at": "2026-03-01", "weight_kg": 100.0}, HM
            ),
            expected_status=201,
        )
        assert wr["weight_kg"] == 100.0
        assert_weight_record(wr)


class TestWeighDateValidation:
    def test_weigh_date_before_birth_rejected(self, api):
        """PRD §3.4: "The `weighed_at` date must be strictly after the animal's
        `birth_date` and not in the future relative to the clock; a weighing date that
        is on or before the birth date, or in the future, is rejected with
        `ERR_WEIGH_DATE_INVALID`."

        Design: Corner/validations/weigh_date_before_birth_returns_422
        """
        set_clock("2026-04-01T00:00:00Z")
        herd = create_herd(species="CATTLE")
        animal = create_animal(
            herd["id"], sex="STEER", birth_date="2026-01-01", birth_weight_kg=38.0
        )
        resp = api.create_weight(
            animal["id"], {"weighed_at": "2025-12-15", "weight_kg": 30.0}, HM
        )
        validate_error(resp, ApiErrorId.ERR_WEIGH_DATE_INVALID.value)
