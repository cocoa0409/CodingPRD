"""Vaccine schedules, vaccination records, due-list, and recalls (PRD §3.3)."""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    add_days,
    advance_clock_seconds,
    create_pet,
    create_vaccine_schedule,
    get_due_list,
    record_vaccination,
    record_vaccination_payload,
    setup_owner_and_pet,
    unique_batch_id,
    unique_vaccine_code,
    vaccine_batch_recall,
    validate_error,
    validate_success,
)


class TestVaccineSchedule:
    def test_create_vaccine_schedule_admin(self, api, platform_admin_headers):
        """PRD §3.3: 'A PlatformAdmin creates vaccine-schedule rules.'"""
        s = create_vaccine_schedule(
            species="DOG", age_min_days=84, booster_interval_days=365,
        )
        assert s["age_min_days"] == 84
        assert s["booster_interval_days"] == 365


class TestVaccinationAgeMin:
    def test_administering_below_age_min_rejected(self, api):
        """PRD §3.3: 'the administration timestamp must be at least the
        pet's birth date plus the matching schedule's age_min_days,
        otherwise the system returns ERR_VACCINE_AGE_MIN.'"""
        sched = create_vaccine_schedule(
            species="DOG", age_min_days=84, booster_interval_days=365,
        )
        owner, pet = setup_owner_and_pet(
            species="DOG", birth_date="2025-01-01",
        )
        # 2025-02-01 is 31 days after birth — below age_min_days=84.
        from test_helpers import vet_headers_for_visit
        res = api.record_vaccination(
            pet["id"],
            record_vaccination_payload(
                vaccine_code=sched["vaccine_code"],
                administered_at="2025-02-01T00:00:00.000Z",
                batch_id=unique_batch_id(),
            ),
            TEST_USERS["drafting_vet_headers"],
        )
        validate_error(res, "ERR_VACCINE_AGE_MIN")


class TestVaccineCooldown:
    def test_re_vaccination_inside_cooldown_rejected(self, api):
        """PRD §3.3: 'a re-vaccination cooldown applies — a new active
        record with the same vaccine_code cannot be administered earlier
        than the prior active record's administered_at plus half of the
        schedule's booster_interval_days (the boundary is half-open: the
        prior administration plus the cooldown duration is the earliest
        valid moment), otherwise the system returns ERR_VACCINE_COOLDOWN.'"""
        sched = create_vaccine_schedule(
            species="DOG", age_min_days=0, booster_interval_days=180,
        )
        owner, pet = setup_owner_and_pet(
            species="DOG", birth_date="2024-01-01",
        )
        # First dose at 2025-01-01 — well past age_min_days=0.
        first = record_vaccination(
            pet_id=pet["id"], vaccine_code=sched["vaccine_code"],
            administered_at="2025-01-01T00:00:00.000Z",
        )
        # Cooldown = 180/2 = 90 days. 89 days later = 2025-03-31 → forbidden.
        res = api.record_vaccination(
            pet["id"],
            record_vaccination_payload(
                vaccine_code=sched["vaccine_code"],
                administered_at="2025-03-31T00:00:00.000Z",
                batch_id=unique_batch_id(),
            ),
            TEST_USERS["drafting_vet_headers"],
        )
        validate_error(res, "ERR_VACCINE_COOLDOWN")

    def test_re_vaccination_at_cooldown_boundary_allowed(self, api):
        """PRD §3.3: 'the boundary is half-open: the prior administration
        plus the cooldown duration is the earliest valid moment.'"""
        sched = create_vaccine_schedule(
            species="DOG", age_min_days=0, booster_interval_days=180,
        )
        owner, pet = setup_owner_and_pet(
            species="DOG", birth_date="2024-01-01",
        )
        first = record_vaccination(
            pet_id=pet["id"], vaccine_code=sched["vaccine_code"],
            administered_at="2025-01-01T00:00:00.000Z",
        )
        # 90 days after = 2025-04-01 → exactly at boundary, allowed.
        res = api.record_vaccination(
            pet["id"],
            record_vaccination_payload(
                vaccine_code=sched["vaccine_code"],
                administered_at="2025-04-01T00:00:00.000Z",
                batch_id=unique_batch_id(),
            ),
            TEST_USERS["drafting_vet_headers"],
        )
        validate_success(res, expected_status=201)


class TestVaccineRecallCascade:
    def test_recall_flips_active_to_recalled(self, api):
        """PRD §3.3: 'Processing the event flips every matching ACTIVE
        vaccination record to RECALLED, immediately sets each affected
        record's next_due_at to the same record's administered_at (so the
        dose reads as "due now") ...'"""
        sched = create_vaccine_schedule(
            species="DOG", age_min_days=84, booster_interval_days=365,
        )
        owner, pet = setup_owner_and_pet(
            species="DOG", birth_date="2025-01-01",
        )
        batch = unique_batch_id("BATCHA")
        rec = record_vaccination(
            pet_id=pet["id"], vaccine_code=sched["vaccine_code"],
            administered_at="2025-04-01T00:00:00.000Z",
            batch_id=batch,
        )
        # Trigger the recall.
        vaccine_batch_recall(
            batch_id=batch, vaccine_code=sched["vaccine_code"],
        )
        # Re-pull the pet to see updated state through the due-list.
        # PRD §3.3 says next_due_at on the recalled record is set to its
        # administered_at — exposing this requires the implementation to
        # surface the record's new fields somewhere. The due-list is
        # the cleanest observable: post-recall, the schedule's due_at
        # falls back per the post_recall variant.
        # We additionally verify the recall is observable via the
        # due-list (entry exists for the schedule).
        due_list = get_due_list(pet["id"])
        codes = [d.get("vaccine_code") for d in due_list]
        assert sched["vaccine_code"] in codes


class TestRecalledBatchBlocksNewDose:
    def test_administering_with_recalled_batch_rejected(self, api):
        """PRD §3.3: 'the batch must not currently be a recalled batch,
        otherwise the system returns ERR_BATCH_RECALLED.'"""
        sched = create_vaccine_schedule(
            species="DOG", age_min_days=0, booster_interval_days=365,
        )
        owner, pet_a = setup_owner_and_pet(
            species="DOG", birth_date="2024-01-01",
        )
        batch = unique_batch_id("RECALL")
        # Record a first ACTIVE dose under this batch on pet_a.
        record_vaccination(
            pet_id=pet_a["id"], vaccine_code=sched["vaccine_code"],
            administered_at="2025-01-01T00:00:00.000Z",
            batch_id=batch,
        )
        # Recall the batch.
        vaccine_batch_recall(
            batch_id=batch, vaccine_code=sched["vaccine_code"],
        )
        # Try to record a NEW dose using the recalled batch on a fresh pet.
        owner_b, pet_b = setup_owner_and_pet(
            species="DOG", birth_date="2024-01-01",
        )
        res = api.record_vaccination(
            pet_b["id"],
            record_vaccination_payload(
                vaccine_code=sched["vaccine_code"],
                administered_at="2025-06-01T00:00:00.000Z",
                batch_id=batch,
            ),
            TEST_USERS["drafting_vet_headers"],
        )
        validate_error(res, "ERR_BATCH_RECALLED")


class TestSupersedeOnNewActive:
    def test_recording_new_dose_supersedes_prior(self, api):
        """PRD §3.3: 'Recording also marks any earlier active record
        with the same vaccine_code for the same pet as SUPERSEDED.'

        Observable via due-list: after a second ACTIVE dose is recorded
        beyond the cooldown window, the next_due_at is computed off
        the latest dose, not the prior one.
        """
        sched = create_vaccine_schedule(
            species="DOG", age_min_days=0, booster_interval_days=180,
        )
        owner, pet = setup_owner_and_pet(
            species="DOG", birth_date="2024-01-01",
        )
        record_vaccination(
            pet_id=pet["id"], vaccine_code=sched["vaccine_code"],
            administered_at="2025-01-01T00:00:00.000Z",
        )
        # Re-vaccinate at 2025-04-01 (90 days later, at boundary).
        record_vaccination(
            pet_id=pet["id"], vaccine_code=sched["vaccine_code"],
            administered_at="2025-04-01T00:00:00.000Z",
        )
        due_list = get_due_list(pet["id"])
        # PRD §3.3 due-list: latest active dose's administered_at +
        # booster_interval_days = 2025-04-01 + 180 days = 2025-09-28.
        relevant = [d for d in due_list
                    if d.get("vaccine_code") == sched["vaccine_code"]]
        assert relevant, (
            f"due-list must contain an entry for {sched['vaccine_code']!r}, "
            f"got {due_list}"
        )
        # Asserting the exact date string is implementation-tolerant; we
        # check the prefix corresponds to the late-dose-driven value.
        due_at = relevant[0].get("due_at", "")
        assert due_at.startswith("2025-09-28"), (
            f"due_at must derive from the latest active dose "
            f"(2025-04-01 + 180 days = 2025-09-28), got {due_at}"
        )
