"""Census collection, participant screening, and correction-loop tests."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    create_plan,
    create_census_batch,
    add_participants,
    submit_screening,
    lock_census_batch,
    create_locked_census,
    api_client,
)

PLAN_ADMIN = TEST_USERS["plan_admin_headers"]


def _plan(sponsor="Census Co"):
    return create_plan(sponsor_name=sponsor)


class TestParticipantAppend:
    def test_participant_computed_and_system_fields(self, api):
        """PRD §3.2: "The batch begins `UPLOADED`, with `participant_count` and
        `error_count` at zero and `screening_errors` empty."
        PRD §3.2: participant rows "are bulk-appended to a batch in `UPLOADED` or
        `NEEDS_CORRECTION` status"; "posting to a batch in any other status fails
        the generic state gate".

        Design: Corner/entities/participant_computed_and_system_fields
        """
        plan = _plan("Computed Co")
        batch = create_census_batch(plan["id"])
        resp = api.add_participants(
            batch["id"],
            {"participants": [
                {"external_ref": "E1", "date_of_birth": "1966-01-01", "status": "ACTIVE",
                 "years_of_service": 1, "annual_compensation": 50000},
                {"external_ref": "E2", "date_of_birth": "1965-01-01", "status": "RETIREE",
                 "current_annual_benefit": 12000},
            ]},
            PLAN_ADMIN,
        )
        data = validate_success(resp, 200)
        assert data["participant_count"] == 2
        assert data["status"] == "UPLOADED"

    def test_bulk_participant_post_partial_success(self, api):
        """PRD §3.2: "The upload endpoint is deliberately tolerant: per-row
        validation errors are collected rather than aborting the request, valid
        rows are still written, and the response is 200 OK."

        Design: Corner/endpoints/bulk_participant_post_partial_success
        """
        plan = _plan("Bulk Co")
        batch = create_census_batch(plan["id"])
        resp = api.add_participants(
            batch["id"],
            {"participants": [
                {"external_ref": "GOOD", "date_of_birth": "1966-01-01", "status": "ACTIVE",
                 "years_of_service": 1, "annual_compensation": 50000},
                {"external_ref": "BAD", "date_of_birth": "1964-01-01", "status": "RETIREE",
                 "current_annual_benefit": 1000},
            ]},
            PLAN_ADMIN,
        )
        data = validate_success(resp, 200)
        assert data["participant_count"] == 2

        lst, meta = validate_paginated(api.list_participants(batch["id"], PLAN_ADMIN))
        assert len(lst) == 2


class TestParticipantReverseReachability:
    def test_census_participants_subresource_reverse_reachability(self, api):
        """PRD §4: "GET /v1/census-batches/{id}/participants — List participants of
        a census batch".
        PRD §3.2: "Each row names its batch through the path, recorded as
        `census_batch_id`".

        Design: Corner/endpoints/census_participants_subresource_reverse_reachability
        """
        plan = _plan("FK Co")
        batch = create_census_batch(plan["id"])
        add_participants(batch["id"], [
            {"external_ref": "E1", "date_of_birth": "1966-01-01", "status": "ACTIVE",
             "years_of_service": 1, "annual_compensation": 50000},
            {"external_ref": "E2", "date_of_birth": "1965-01-01", "status": "RETIREE",
             "current_annual_benefit": 12000},
        ])
        rows, meta = validate_paginated(api.list_participants(batch["id"], PLAN_ADMIN))
        assert len(rows) == 2
        for r in rows:
            assert r["census_batch_id"] == batch["id"]


class TestCensusScreeningStates:
    def test_census_lock_from_uploaded_is_invalid_state(self, api):
        """PRD §3.2: "Locking moves a `VALIDATED` batch to `LOCKED`, its terminal
        state" — an UPLOADED batch has no lock transition.
        PRD §2.8: the generic from-state validity of the target entity is "rejected
        as `ERR_INVALID_STATE` (HTTP 409)".

        Design: Corner/state_machines/census_lock_from_uploaded_is_invalid_state
        """
        plan = _plan("SM Co")
        batch = create_census_batch(plan["id"])
        add_participants(batch["id"], [
            {"external_ref": "R1", "date_of_birth": "1965-01-01", "status": "RETIREE",
             "current_annual_benefit": 1000},
        ])
        resp = api.lock_census_batch(batch["id"], PLAN_ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_locked_census_is_terminal(self, api):
        """PRD §3.2: "Locking moves a `VALIDATED` batch to `LOCKED`, its terminal
        state, making it immutable reference data for valuation runs."
        PRD §2.8: from-state violations reject as `ERR_INVALID_STATE` (HTTP 409).

        Design: Corner/state_machines/locked_census_is_terminal
        """
        plan = _plan("Terminal Co")
        batch = create_locked_census(plan["id"], [
            {"external_ref": "R1", "date_of_birth": "1965-01-01", "status": "RETIREE",
             "current_annual_benefit": 1000},
        ])
        assert batch["status"] == "LOCKED"
        resp = api.submit_screening(batch["id"], PLAN_ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_screening_empty_batch_rejected(self, api):
        """PRD §3.2: "Submitting an `UPLOADED` batch for screening re-checks every
        row and requires `participant_count` greater than zero; screening an empty
        batch is itself an `ERR_INVALID_PARTICIPANT_DATA` rejection."

        Design: Corner/validations/screening_empty_batch_rejected
        """
        plan = _plan("Empty Co")
        batch = create_census_batch(plan["id"])
        resp = api.submit_screening(batch["id"], PLAN_ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_PARTICIPANT_DATA, 422)

    def test_duplicate_participant_external_ref_rejected(self, api):
        """PRD §3.2: each row "carries the sponsor's employee identifier
        `external_ref` — unique within the batch, with duplicates rejected as
        `ERR_UNIQUENESS_VIOLATION` (HTTP 409)".

        Design: Corner/validations/duplicate_participant_external_ref_rejected
        """
        plan = _plan("DupRef Co")
        batch = create_census_batch(plan["id"])
        add_participants(batch["id"], [
            {"external_ref": "E1", "date_of_birth": "1965-01-01", "status": "RETIREE",
             "current_annual_benefit": 1000},
        ])
        resp = api.add_participants(
            batch["id"],
            {"participants": [
                {"external_ref": "E1", "date_of_birth": "1966-01-01", "status": "ACTIVE",
                 "years_of_service": 2, "annual_compensation": 40000},
            ]},
            PLAN_ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_UNIQUENESS_VIOLATION, 409)

    def test_plan_year_mismatch_on_census_create(self, api):
        """PRD §3.2: "A `PlanAdmin` creates a census batch under a plan, supplying a
        `plan_year` that must equal the owning plan's year — a mismatch is rejected
        with `ERR_PLAN_YEAR_MISMATCH` (HTTP 422)".

        Design: Corner/validations/plan_year_mismatch_on_census_create
        """
        plan = _plan("Mismatch Co")
        resp = api.create_census_batch(
            plan["id"],
            {"plan_year": 2027, "source_label": "wrong-year"},
            PLAN_ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_PLAN_YEAR_MISMATCH, 422)


class TestCensusCorrectionLoop:
    def test_census_batch_correction_loop_screening_errors(self, api):
        """PRD §3.2: "When screening finds one or more row errors, the batch
        transitions `UPLOADED` → `NEEDS_CORRECTION` with `error_count` and
        `screening_errors` populated from the row screening."
        PRD §3.2: attained age "must fall within the pinned mortality domain of 60
        through 63 inclusive".

        Design: Difficulty/non_linear_state_machine/census_batch_correction_loop
        """
        plan = _plan("Census Loop Co")
        batch = create_census_batch(plan["id"])
        add_participants(batch["id"], [
            {"external_ref": "BAD", "date_of_birth": "1964-01-01", "status": "RETIREE",
             "current_annual_benefit": 1000},
            {"external_ref": "OK", "date_of_birth": "1965-01-01", "status": "RETIREE",
             "current_annual_benefit": 2000},
        ])
        resp = api.submit_screening(batch["id"], PLAN_ADMIN)
        data = validate_success(resp, 200)
        assert data["status"] == "NEEDS_CORRECTION"
        assert data["error_count"] == 1

    def test_census_batch_correction_loop_repost_returns_uploaded_then_lock(self, api):
        """PRD §3.2: "Whenever rows are posted to a `NEEDS_CORRECTION` batch, the
        batch returns to `UPLOADED` — the revision loop — with `participant_count`
        recomputed and `screening_errors` cleared to an empty array; newly appended
        rows simply extend the batch."
        PRD §3.2: "When screening finds zero row errors, the batch transitions
        `UPLOADED` → `VALIDATED`"; "Locking moves a `VALIDATED` batch to `LOCKED`".

        Design: Difficulty/non_linear_state_machine/census_batch_correction_loop
        """
        plan = _plan("Census Loop 2 Co")
        batch = create_census_batch(plan["id"])
        add_participants(batch["id"], [
            {"external_ref": "BAD", "date_of_birth": "1964-01-01", "status": "RETIREE",
             "current_annual_benefit": 1000},
            {"external_ref": "OK", "date_of_birth": "1965-01-01", "status": "RETIREE",
             "current_annual_benefit": 2000},
        ])
        submit_screening(batch["id"])

        # Re-post a corrected row: NEEDS_CORRECTION -> UPLOADED
        resp = api.add_participants(
            batch["id"],
            {"participants": [
                {"external_ref": "FIX", "date_of_birth": "1966-01-01", "status": "ACTIVE",
                 "years_of_service": 2, "annual_compensation": 40000},
            ]},
            PLAN_ADMIN,
        )
        data = validate_success(resp, 200)
        assert data["status"] == "UPLOADED"
        assert data["participant_count"] == 3

        # NOTE: the BAD age-64 row is still in the batch, so the second screening
        # finds the same row error again -> NEEDS_CORRECTION. Remove-by-correction
        # is not in the PRD surface; the pinned cycle is the loop re-entry itself.
        # To reach LOCKED we need a clean batch, so walk a fresh one.
        batch2 = create_census_batch(plan["id"], source_label="census-2")
        add_participants(batch2["id"], [
            {"external_ref": "OK", "date_of_birth": "1965-01-01", "status": "RETIREE",
             "current_annual_benefit": 2000},
        ])
        validated = submit_screening(batch2["id"])
        assert validated["status"] == "VALIDATED"
        locked = lock_census_batch(batch2["id"])
        assert locked["status"] == "LOCKED"
