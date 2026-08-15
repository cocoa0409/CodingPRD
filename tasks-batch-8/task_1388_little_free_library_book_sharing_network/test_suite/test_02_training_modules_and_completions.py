"""Training catalog: prerequisites, pass boundary, module guards, lean records."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_recognition_event,
    assert_training_completion,
    create_training_module_payload,
    ensure_module,
    ensure_orientation_module,
    events_of_type,
    list_recognition_events,
    make_steward_headers,
    pin_clock,
    record_completion,
    register_steward,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


class TestPrerequisiteGate:
    def test_completion_rejected_without_prerequisite_pass(self, api):
        """PRD §3.1: "Three guards protect the record: the module must be active
        (`ERR_MODULE_INACTIVE` otherwise), its prerequisite chain must already
        be fully passed by this steward (`ERR_PREREQUISITE_NOT_MET`), and a
        module already passed by this steward cannot be passed again
        (`ERR_MODULE_ALREADY_PASSED`)."

        Design: Difficulty/cross_entity_state_dependency/completion_rejected_without_prerequisite_pass
        """
        pin_clock()
        orientation = ensure_module("ORIENTATION", "Orientation", 1)
        curation = ensure_module("CURATION", "Curation", 2,
                                 prerequisite_module_id=orientation["id"])
        steward = register_steward(full_name="Sofia Reyes",
                                   email="sofia@example.org", region_code="WA")

        res = api.create_training_completion(
            steward["id"],
            {"module_id": curation["id"], "score": 95},
            make_steward_headers(steward["id"]),
        )
        validate_error(res, ApiErrorId.ERR_PREREQUISITE_NOT_MET.value,
                       expected_status=422)

    def test_completion_succeeds_after_prerequisite_passed(self, api):
        """PRD §3.1: "its prerequisite chain must already be fully passed by
        this steward (`ERR_PREREQUISITE_NOT_MET`)".
        PRD §3.1: "Every `PASSED` completion raises the steward's
        `training_level` — the count of distinct modules passed — and appends
        a `TRAINING_PASSED` recognition event worth +25 points."

        Design: Difficulty/cross_entity_state_dependency/completion_rejected_without_prerequisite_pass
        """
        pin_clock()
        orientation = ensure_module("ORIENTATION", "Orientation", 1)
        curation = ensure_module("CURATION", "Curation", 2,
                                 prerequisite_module_id=orientation["id"])
        steward = register_steward(full_name="Sofia Reyes",
                                   email="sofia2@example.org", region_code="WA")

        record_completion(steward["id"], orientation["id"], score=85)
        completion = validate_success(
            api.create_training_completion(
                steward["id"],
                {"module_id": curation["id"], "score": 95},
                make_steward_headers(steward["id"]),
            ),
            201,
        )
        assert completion["result"] == "PASSED"

        after = validate_success(api.get_steward(steward["id"], ADMIN), 200)
        assert after["training_level"] == 2


class TestPassBoundary:
    def test_training_pass_boundary_79_vs_80(self, api):
        """PRD §3.1: "A score of at least 80 yields a `result` of `PASSED`;
        79 or below yields `FAILED`."
        PRD §3.1: "Every `PASSED` completion raises the steward's
        `training_level` — the count of distinct modules passed."

        Design: Corner/validations/training_pass_boundary_79_vs_80
        """
        pin_clock()
        safety = ensure_module("SAFETY", "Content Safety", 2)
        steward = register_steward(full_name="Boundary Tester",
                                   email="bnd@example.org")

        failed = validate_success(
            api.create_training_completion(
                steward["id"],
                {"module_id": safety["id"], "score": 79},
                make_steward_headers(steward["id"]),
            ),
            201,
        )
        assert failed["result"] == "FAILED"

        passed = validate_success(
            api.create_training_completion(
                steward["id"],
                {"module_id": safety["id"], "score": 80},
                make_steward_headers(steward["id"]),
            ),
            201,
        )
        assert passed["result"] == "PASSED"

        steward_after = validate_success(
            api.get_steward(steward["id"], ADMIN), 200
        )
        assert steward_after["training_level"] == 1


class TestModuleGuards:
    def test_module_already_passed_rejected(self, api):
        """PRD §3.1: "a module already passed by this steward cannot be passed
        again (`ERR_MODULE_ALREADY_PASSED`)".

        Design: Corner/validations/module_already_passed_rejected
        """
        pin_clock()
        orientation = ensure_orientation_module()
        steward = register_steward(full_name="Repeat Tester",
                                   email="repeat@example.org")
        record_completion(steward["id"], orientation["id"], score=90)

        res = api.create_training_completion(
            steward["id"],
            {"module_id": orientation["id"], "score": 100},
            make_steward_headers(steward["id"]),
        )
        validate_error(res, ApiErrorId.ERR_MODULE_ALREADY_PASSED.value,
                       expected_status=422)

    def test_module_inactive_rejected(self, api):
        """PRD §3.1: "the module must be active (`ERR_MODULE_INACTIVE`
        otherwise)".

        Design: Corner/validations/module_inactive_rejected
        """
        pin_clock()
        legacy = validate_success(
            api.create_training_module(
                create_training_module_payload(
                    code="LEGACY", title="Legacy Module", level=1, active=False
                ),
                ADMIN,
            ),
            201,
        )
        steward = register_steward(full_name="Inactive Tester",
                                   email="inact@example.org")

        res = api.create_training_completion(
            steward["id"],
            {"module_id": legacy["id"], "score": 95},
            make_steward_headers(steward["id"]),
        )
        validate_error(res, ApiErrorId.ERR_MODULE_INACTIVE.value,
                       expected_status=422)

    def test_module_cycle_rejected(self, api):
        """PRD §3.1: "The prerequisite chain must remain acyclic — creating or
        editing a module whose `prerequisite_module_id` would close a loop is
        rejected with `ERR_MODULE_CYCLE`, and the referenced module must exist."

        Design: Corner/validations/module_cycle_rejected
        """
        pin_clock()
        orientation = ensure_module("ORIENTATION", "Orientation", 1)
        safety = ensure_module("SAFETY", "Content Safety", 2,
                               prerequisite_module_id=orientation["id"])

        res = api.patch_training_module(
            orientation["id"],
            {"prerequisite_module_id": safety["id"]},
            ADMIN,
        )
        validate_error(res, ApiErrorId.ERR_MODULE_CYCLE.value,
                       expected_status=422)

        after = validate_success(
            api.get_training_module(orientation["id"], ADMIN), 200
        )
        assert after["prerequisite_module_id"] is None


class TestLeanRecords:
    def test_record_entities_carry_no_version_field(self, api):
        """PRD §2.5: "A TrainingCompletion, an InspectionRecord, and a
        RecognitionEvent carry only `id` and `created_at`: they are immutable
        once written, so `updated_at` and `version` are absent from them
        entirely."
        PRD §3.1: "Every `PASSED` completion ... appends a `TRAINING_PASSED`
        recognition event worth +25 points."

        Design: Corner/entities/record_entities_carry_no_version_field
        """
        pin_clock()
        orientation = ensure_orientation_module()
        steward = register_steward(full_name="Record Keeper",
                                   email="rk@example.org")
        completion = record_completion(steward["id"], orientation["id"],
                                       score=90)
        assert_training_completion(completion)

        fetched = validate_success(
            api.get_training_completion(completion["id"], ADMIN), 200
        )
        assert_training_completion(fetched)

        events = list_recognition_events(steward["id"])
        training_events = events_of_type(events, "TRAINING_PASSED")
        assert len(training_events) == 1
        assert_recognition_event(training_events[0])
        assert training_events[0]["points_delta"] == 25

    def test_recognition_event_polymorphic_source_reference(self, api):
        """PRD §2.10: "Each event records the `steward_id` it belongs to, an
        `event_type` drawn from `MAINTENANCE_RESOLVED`, `ALLOCATION_PLACED`,
        `DRIVE_COMPLETED`, `COMPLAINT_UPHELD`, and `TRAINING_PASSED`, a signed
        `points_delta`, and a polymorphic pointer — a `source_type` naming the
        kind of entity that caused the event (`MAINTENANCE_REQUEST`,
        `ALLOCATION`, `BOOK_DRIVE`, `COMPLAINT`, or `TRAINING_COMPLETION`)
        paired with the `source_id` of that entity."

        Design: Corner/entities/recognition_event_polymorphic_source_reference
        """
        pin_clock()
        orientation = ensure_orientation_module()
        steward = register_steward(full_name="Poly Morph",
                                   email="poly@example.org")
        completion = record_completion(steward["id"], orientation["id"],
                                       score=90)

        events = list_recognition_events(steward["id"])
        training_events = events_of_type(events, "TRAINING_PASSED")
        assert len(training_events) == 1
        event = training_events[0]
        assert event["source_type"] == "TRAINING_COMPLETION"
        assert event["source_id"] == completion["id"]
