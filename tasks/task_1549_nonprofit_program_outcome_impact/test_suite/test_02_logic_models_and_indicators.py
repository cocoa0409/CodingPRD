"""Logic models and indicators: code uniqueness, revision loop, OCC-gated
approval, supersede invariants, and indicator edit lock."""
from test_helpers import (
    ApiErrorId,
    assert_indicator,
    assert_logic_model,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    approve_logic_model,
    create_active_program,
    create_indicator,
    create_logic_model,
)
from test_helpers.test_users import DIRECTOR, LEAD


class TestIndicatorCodeUniqueness:
    def test_indicator_code_uniqueness_scoped_to_model(self, api):
        """PRD section 3.2: "a `code` unique within its logic model
        (`ERR_DUPLICATE_CODE` on a clash)".

        Design: Corner/entities/indicator_code_uniqueness_scoped_to_model
        """
        program = create_active_program(name="Uniq", code="UNQ")
        m1 = create_logic_model(program["id"], title="M1")
        m2 = create_logic_model(program["id"], title="M2")
        create_indicator(m1["id"], code="DUP", target_value=10)

        dup_resp = api.create_indicator(
            m1["id"],
            {"code": "DUP", "level": "OUTCOME", "unit": "COUNT",
             "direction": "HIGHER_IS_BETTER", "baseline_value": 0,
             "target_value": 20, "measurement_frequency": "PER_EVENT"},
            LEAD,
        )
        validate_error(dup_resp, ApiErrorId.ERR_DUPLICATE_CODE)

        ok_resp = api.create_indicator(
            m2["id"],
            {"code": "DUP", "level": "OUTCOME", "unit": "COUNT",
             "direction": "HIGHER_IS_BETTER", "baseline_value": 0,
             "target_value": 20, "measurement_frequency": "PER_EVENT"},
            LEAD,
        )
        data = validate_success(ok_resp, expected_status=201)
        assert_indicator(data)
        assert data["code"] == "DUP"


class TestLogicModelRevisionLoop:
    def test_revision_loop_reopens_indicator_edits(self, api):
        """PRD section 3.2: "Rejection moves `SUBMITTED → REJECTED` and
        accepts an optional `reason`; revision moves `REJECTED → DRAFT`,
        reopening the model and its indicators for editing."
        PRD section 3.2: "While the parent model remains `DRAFT`, an
        `EvaluationLead` may patch any of these input fields; once the model
        leaves `DRAFT`, indicator edits are rejected with `ERR_INVALID_STATE`."

        Design: Difficulty/non_linear_state_machine/logic_model_revision_loop
        """
        program = create_active_program(name="Arts", code="ART")
        model = create_logic_model(program["id"], title="LM1")
        indicator = create_indicator(model["id"], code="I1", target_value=20,
                                     measurement_frequency="MONTHLY")

        get_success_data(api.submit_logic_model(model["id"], LEAD))
        rejected = get_success_data(
            api.reject_logic_model(model["id"], {"reason": "weak outcomes"}, LEAD))
        assert rejected["status"] == "REJECTED"

        revised = get_success_data(api.revise_logic_model(model["id"], LEAD))
        assert revised["status"] == "DRAFT"

        patched = get_success_data(
            api.patch_indicator(indicator["id"], {"target_value": 95}, LEAD))
        assert patched["target_value"] == 95

        get_success_data(api.submit_logic_model(model["id"], LEAD))
        program_now = get_success_data(api.get_program(program["id"], DIRECTOR))
        approved = get_success_data(api.approve_logic_model(
            model["id"], {"expected_program_version": program_now["version"]}, LEAD))
        assert approved["status"] == "APPROVED"

        indicator_after = get_success_data(api.get_indicator(indicator["id"], LEAD))
        assert indicator_after["status"] == "ACTIVE"
        assert indicator_after["target_value"] == 95

    def test_revision_loop_reject_then_patch_blocked_until_revise(self, api):
        """PRD section 3.2: "While the parent model remains `DRAFT`, an
        `EvaluationLead` may patch any of these input fields; once the model
        leaves `DRAFT`, indicator edits are rejected with `ERR_INVALID_STATE`."

        Design: Difficulty/non_linear_state_machine/logic_model_revision_loop
        """
        program = create_active_program(name="Arts2", code="AR2")
        model = create_logic_model(program["id"], title="LM1")
        indicator = create_indicator(model["id"], code="I1", target_value=20,
                                     measurement_frequency="MONTHLY")
        get_success_data(api.submit_logic_model(model["id"], LEAD))
        get_success_data(api.reject_logic_model(model["id"], {}, LEAD))

        blocked = api.patch_indicator(indicator["id"], {"target_value": 77}, LEAD)
        validate_error(blocked, ApiErrorId.ERR_INVALID_STATE)

        get_success_data(api.revise_logic_model(model["id"], LEAD))
        patched = get_success_data(
            api.patch_indicator(indicator["id"], {"target_value": 77}, LEAD))
        assert patched["target_value"] == 77


class TestSingleApprovedModelInvariant:
    def test_second_approval_supersedes_first(self, api):
        """PRD section 3.2: "When approval succeeds, several things happen as
        one atomic act. The previously `APPROVED` model of the same program,
        if any, transitions `APPROVED → SUPERSEDED`. Every `ACTIVE` indicator
        of that superseded model transitions to `RETIRED`. Every `DRAFT`
        indicator of the newly approved model transitions to `ACTIVE`."
        PRD section 3.2: "At most one model per program is ever `APPROVED` at
        a time."

        Design: Difficulty/compensating_invariant/single_approved_model_invariant
        """
        program = create_active_program(name="STEM", code="STM")
        m1 = create_logic_model(program["id"], title="M1")
        ind_x = create_indicator(m1["id"], code="X", measurement_frequency="MONTHLY")
        approve_logic_model(m1["id"], program["id"])

        m2 = create_logic_model(program["id"], title="M2")
        create_indicator(m2["id"], code="Y", level="IMPACT",
                         measurement_frequency="END_OF_CYCLE")
        get_success_data(api.submit_logic_model(m2["id"], LEAD))

        approved_before, _ = get_success_data(
            api.list_logic_models(program["id"], LEAD, params={"status": "APPROVED"}),
        ), None
        # Use paginated validator indirectly via list_logic_models response body
        list_resp = api.list_logic_models(program["id"], LEAD, params={"status": "APPROVED"})
        list_data = get_success_data(list_resp)
        approved_list = list_data if isinstance(list_data, list) else list_data.get("data", [])
        # get_success_data on a list response returns the data list directly.
        assert isinstance(approved_list, list)
        assert len(approved_list) == 1
        assert approved_list[0]["id"] == m1["id"]

        program_now = get_success_data(api.get_program(program["id"], DIRECTOR))
        get_success_data(api.approve_logic_model(
            m2["id"], {"expected_program_version": program_now["version"]}, LEAD))

        list_resp2 = api.list_logic_models(program["id"], LEAD, params={"status": "APPROVED"})
        approved_after = get_success_data(list_resp2)
        assert len(approved_after) == 1
        assert approved_after[0]["id"] == m2["id"]

        m1_after = get_success_data(api.get_logic_model(m1["id"], LEAD))
        assert m1_after["status"] == "SUPERSEDED"

        ind_x_after = get_success_data(api.get_indicator(ind_x["id"], LEAD))
        assert ind_x_after["status"] == "RETIRED"

        program_after = get_success_data(api.get_program(program["id"], DIRECTOR))
        assert program_after["current_logic_model_id"] == m2["id"]

    def test_supersede_conserves_approved_count(self, api):
        """PRD section 3.2: "At most one model per program is ever `APPROVED`
        at a time."
        PRD section 3.2: "The program's `current_logic_model_id` is set to the
        newly approved model, the model's `approved_at` is stamped, and the
        program's own `version` advances by one in addition to the version
        increments on the two models and their indicators."

        Design: Difficulty/compensating_invariant/single_approved_model_invariant
        """
        program = create_active_program(name="STEM2", code="ST2")
        m1 = create_logic_model(program["id"], title="M1")
        create_indicator(m1["id"], code="X")
        approve_logic_model(m1["id"], program["id"])

        m2 = create_logic_model(program["id"], title="M2")
        ind_y = create_indicator(m2["id"], code="Y")
        get_success_data(api.submit_logic_model(m2["id"], LEAD))

        program_now = get_success_data(api.get_program(program["id"], DIRECTOR))
        version_before = program_now["version"]
        approved = get_success_data(api.approve_logic_model(
            m2["id"], {"expected_program_version": version_before}, LEAD))
        assert_logic_model(approved)
        assert approved["status"] == "APPROVED"
        assert approved["approved_at"] is not None

        ind_y_after = get_success_data(api.get_indicator(ind_y["id"], LEAD))
        assert ind_y_after["status"] == "ACTIVE"

        program_after = get_success_data(api.get_program(program["id"], DIRECTOR))
        assert program_after["version"] == version_before + 1, (
            "approval increments the program's own version by one"
        )
        assert program_after["current_logic_model_id"] == m2["id"]


class TestIndicatorEditLock:
    def test_indicator_edit_requires_model_draft(self, api):
        """PRD section 3.2: "While the parent model remains `DRAFT`, an
        `EvaluationLead` may patch any of these input fields; once the model
        leaves `DRAFT`, indicator edits are rejected with `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/indicator_edit_requires_model_draft
        """
        program = create_active_program(name="Mentorship", code="MNT")
        model = create_logic_model(program["id"], title="LM1")
        indicator = create_indicator(model["id"], code="I1", target_value=20,
                                     measurement_frequency="MONTHLY")
        approve_logic_model(model["id"], program["id"])

        patch_resp = api.patch_indicator(indicator["id"], {"target_value": 55}, LEAD)
        validate_error(patch_resp, ApiErrorId.ERR_INVALID_STATE)

        indicator_after = get_success_data(api.get_indicator(indicator["id"], LEAD))
        assert indicator_after["target_value"] == 20, (
            "rejected patch must leave target_value unchanged"
        )

    def test_indicator_edit_under_approved_model_is_locked(self, api):
        """PRD section 3.2: "An `EvaluationLead` creates them only while the
        parent model is `DRAFT` - attempts under a model in any other state
        are rejected with `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/indicator_edit_requires_model_draft
        """
        program = create_active_program(name="Mentor2", code="MN2")
        model = create_logic_model(program["id"], title="LM1")
        create_indicator(model["id"], code="I1")
        approve_logic_model(model["id"], program["id"])

        create_resp = api.create_indicator(
            model["id"],
            {"code": "I2", "level": "OUTCOME", "unit": "SCORE",
             "direction": "HIGHER_IS_BETTER", "baseline_value": 0,
             "target_value": 50, "measurement_frequency": "MONTHLY"},
            LEAD,
        )
        validate_error(create_resp, ApiErrorId.ERR_INVALID_STATE)
