"""Operator designation, training credentialing, and activation gates (PRD §3.7)."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, make_technician_headers, assert_ts_equal,
    set_clock, create_facility, create_technician, create_operator,
    issue_training, create_training_record_payload,
)

OWNER = TEST_USERS["facility_owner_headers"]
ADMIN = TEST_USERS["contractor_admin_headers"]
READER = TEST_USERS["any_headers"]


class TestTrainingIssuance:
    def test_training_class_mismatch_rejected(self, api):
        """PRD §3.7: "The `course_class` must equal the operator's own
        `operator_class` (`ERR_CLASS_MISMATCH`)"

        Design: Corner/validations/training_class_mismatch_rejected
        """
        set_clock("2026-05-01T00:00:00Z")
        facility = create_facility(facility_name="Class Site")
        trainer = create_technician([], trainer=True, full_name="Trainer")
        op = create_operator(facility["id"], "B", full_name="Op B")

        res = api.create_training_record(
            create_training_record_payload(op["id"], "A",
                                           completed_at="2026-04-01T00:00:00Z"),
            make_technician_headers(trainer["id"]))
        validate_error(res, ApiErrorId.ERR_CLASS_MISMATCH)

    def test_instructor_not_trainer_rejected(self, api):
        """PRD §3.7: "Issuing a certificate is a `Technician`-role action that
        requires the calling technician's `trainer` flag to be true
        (`ERR_INSTRUCTOR_NOT_TRAINER`)"

        Design: Corner/validations/instructor_not_trainer_rejected
        """
        set_clock("2026-05-01T00:00:00Z")
        facility = create_facility(facility_name="Trainer Gate")
        not_trainer = create_technician(["CP_TESTER"], trainer=False,
                                        full_name="Not Trainer")
        op = create_operator(facility["id"], "C", full_name="Op C")

        res = api.create_training_record(
            create_training_record_payload(op["id"], "C",
                                           completed_at="2026-04-01T00:00:00Z"),
            make_technician_headers(not_trainer["id"]))
        validate_error(res, ApiErrorId.ERR_INSTRUCTOR_NOT_TRAINER)

    def test_training_expiry_months_per_class(self, api):
        """PRD §3.7: "The certificate's `expires_at` is computed at issuance:
        `completed_at` plus 36 months for class `A`, 36 months for class `B`, and
        12 months for class `C`." and "Training records list by `operator_id`,
        `instructor_technician_id`, and `course_class`."

        Design: Corner/calculations/training_expiry_months_per_class
        """
        set_clock("2026-05-01T00:00:00Z")
        facility = create_facility(facility_name="Expiry Site")
        trainer = create_technician([], trainer=True, full_name="Trainer")
        op_a = create_operator(facility["id"], "A", full_name="Op A")
        op_c = create_operator(facility["id"], "C", full_name="Op C")

        rec_a = issue_training(op_a["id"], "A", "2026-01-10T00:00:00Z", trainer["id"])
        rec_c = issue_training(op_c["id"], "C", "2026-01-10T00:00:00Z", trainer["id"])
        assert_ts_equal(rec_a["expires_at"], "2029-01-10T00:00:00Z",
                        label="class A completed_at + 36 months")
        assert_ts_equal(rec_c["expires_at"], "2027-01-10T00:00:00Z",
                        label="class C completed_at + 12 months")

        data, meta = validate_paginated(
            api.list_training_records(READER, params={"operator_id": op_a["id"]}))
        assert meta["total_count"] == 1
        data, meta = validate_paginated(
            api.list_operators(READER, params={"facility_id": facility["id"]}))
        assert meta["total_count"] == 2


class TestOperatorActivation:
    def _setup_class_c_operator(self):
        set_clock("2026-05-01T00:00:00Z")
        facility = create_facility(facility_name="Training Site")
        op = create_operator(facility["id"], "C", full_name="Op C")
        trainer = create_technician([], trainer=True, full_name="Trainer Tess")
        return facility, op, trainer

    def test_activate_missing_then_expired_training_rejected(self, api):
        """PRD §3.7: "If no record exists for the class, activation fails with
        `ERR_TRAINING_MISSING`; if the selected record's `expires_at` is at or
        before the logical clock, it fails with `ERR_TRAINING_EXPIRED`."

        Design: Difficulty/cross_entity_state_dependency/operator_activate_requires_valid_training
        """
        facility, op, trainer = self._setup_class_c_operator()

        res = api.activate_operator(op["id"], OWNER)
        validate_error(res, ApiErrorId.ERR_TRAINING_MISSING)

        # 2024-04-01 + 12 months = 2025-04-01, at/before clock 2026-05-01.
        issue_training(op["id"], "C", "2024-04-01T00:00:00Z", trainer["id"])
        res = api.activate_operator(op["id"], OWNER)
        validate_error(res, ApiErrorId.ERR_TRAINING_EXPIRED)

    def test_activate_with_fresh_cert_succeeds_latest_wins(self, api):
        """PRD §3.7: "Activation demands a training record matching the operator's
        class; when several exist, the system selects the one with the latest
        `completed_at`, breaking ties by the latest `created_at`." and "A
        successful activation moves the operator to `ACTIVE` and recomputes the
        facility posture."

        Design: Difficulty/cross_entity_state_dependency/operator_activate_requires_valid_training
        """
        facility, op, trainer = self._setup_class_c_operator()
        # Expired record first; the fresh one must be selected over it.
        issue_training(op["id"], "C", "2024-04-01T00:00:00Z", trainer["id"])
        issue_training(op["id"], "C", "2026-04-15T00:00:00Z", trainer["id"])

        activated = validate_success(api.activate_operator(op["id"], OWNER), 200)
        assert activated["status"] == "ACTIVE", (
            "latest record (completed 2026-04-15, expires 2027-04-15) is valid")

    def test_operator_revoke_then_activate_rejected(self, api):
        """PRD §3.7: "The owner may activate an operator in `DESIGNATED` or
        `LAPSED` status (`ERR_OPERATOR_NOT_ACTIVATABLE` otherwise)." and "the owner
        may revoke an operator at any time: revocation from `DESIGNATED`, `ACTIVE`,
        or `LAPSED` always succeeds and moves the operator to the terminal
        `REVOKED` state"

        Design: Corner/state_machines/operator_revoke_then_activate_rejected
        """
        facility = create_facility(facility_name="Op Gate")
        op = create_operator(facility["id"], "B", full_name="Op")
        revoked = validate_success(api.revoke_operator(op["id"], OWNER), 200)
        assert revoked["status"] == "REVOKED"

        res = api.activate_operator(op["id"], OWNER)
        validate_error(res, ApiErrorId.ERR_OPERATOR_NOT_ACTIVATABLE, expected_status=409)
