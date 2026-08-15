"""Cross-cutting concerns: cycle version pinning, OCC on logic-model
approval, and subresource listing scoping."""
from test_helpers import (
    ApiErrorId,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    create_active_program,
    create_cycle,
    create_indicator,
    create_logic_model,
)
from test_helpers.test_users import DIRECTOR, LEAD, PRIVACY


class TestCycleVersionPinning:
    def test_cycle_pins_logic_model_and_consent_version(self, api):
        """PRD section 3.4: "Activation moves `ENROLLING → ACTIVE` and
        performs the system's central act of **version pinning**: the
        cycle's `pinned_logic_model_id` is set to the program's
        `current_logic_model_id`, and `consent_form_version_snapshot`
        captures the program's `current_consent_form_version` at that
        instant. Both pins are immutable thereafter, so a later logic-model
        approval or consent-form change cannot retroactively redefine what
        an in-flight cycle was measuring or which consent edition it was
        operating under."

        Design: Corner/cross_cutting_layers/cycle_pins_logic_model_and_consent_version
        """
        program = create_active_program(name="Pinning", code="PNN")
        m1 = create_logic_model(program["id"], title="M1")
        create_indicator(m1["id"], code="A", measurement_frequency="MONTHLY")
        get_success_data(api.submit_logic_model(m1["id"], LEAD))
        program_now = get_success_data(api.get_program(program["id"], DIRECTOR))
        get_success_data(api.approve_logic_model(
            m1["id"], {"expected_program_version": program_now["version"]}, LEAD))

        cycle = create_cycle(program["id"])
        get_success_data(api.open_enrollment(cycle["id"], DIRECTOR))
        get_success_data(api.activate_cycle(cycle["id"], DIRECTOR))

        # Approve replacement model M2 and bump the consent form.
        m2 = create_logic_model(program["id"], title="M2")
        create_indicator(m2["id"], code="B", level="IMPACT",
                         measurement_frequency="END_OF_CYCLE")
        get_success_data(api.submit_logic_model(m2["id"], LEAD))
        program_now2 = get_success_data(api.get_program(program["id"], DIRECTOR))
        get_success_data(api.approve_logic_model(
            m2["id"], {"expected_program_version": program_now2["version"]}, LEAD))
        get_success_data(api.consent_form_bump(program["id"], PRIVACY))

        cycle_after = get_success_data(api.get_cycle(cycle["id"], DIRECTOR))
        assert cycle_after["pinned_logic_model_id"] == m1["id"], (
            "the cycle keeps its originally pinned logic model"
        )
        assert cycle_after["consent_form_version_snapshot"] == 1

        program_after = get_success_data(api.get_program(program["id"], DIRECTOR))
        assert program_after["current_logic_model_id"] == m2["id"]
        assert program_after["current_consent_form_version"] == 2


class TestLogicModelOcc:
    def test_occ_logic_model_approve_stale(self, api):
        """PRD section 2.8: "Approving a logic model requires the request to
        carry `expected_program_version`, holding the `version` of the parent
        `Program` the client last observed. A mismatch with the program's
        current `version` is rejected with `ERR_STALE_PROGRAM_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_logic_model_approve_stale
        """
        program = create_active_program(name="OCC2", code="OC2")
        m1 = create_logic_model(program["id"], title="M1")
        create_indicator(m1["id"], code="A", measurement_frequency="MONTHLY")
        get_success_data(api.submit_logic_model(m1["id"], LEAD))

        # Capture the version BEFORE the first approval.
        program_before = get_success_data(api.get_program(program["id"], DIRECTOR))
        stale_version = program_before["version"]

        # First approval advances the program version.
        get_success_data(api.approve_logic_model(
            m1["id"], {"expected_program_version": stale_version}, LEAD))

        m2 = create_logic_model(program["id"], title="M2")
        create_indicator(m2["id"], code="B", level="IMPACT",
                         measurement_frequency="END_OF_CYCLE")
        get_success_data(api.submit_logic_model(m2["id"], LEAD))

        # Second approval carrying the stale version is rejected.
        stale_resp = api.approve_logic_model(
            m2["id"], {"expected_program_version": stale_version}, LEAD)
        validate_error(stale_resp, ApiErrorId.ERR_STALE_PROGRAM_VERSION)

        m2_after = get_success_data(api.get_logic_model(m2["id"], LEAD))
        assert m2_after["status"] == "SUBMITTED", (
            "the rejected approval leaves the second model in SUBMITTED"
        )


class TestSubresourceListing:
    def test_subresource_listing_scoped_to_parent(self, api):
        """PRD section 3.4: "Cycles are reachable two ways: the per-program
        list, and a cross-program list that accepts `program_id`,
        `pinned_logic_model_id`, and `status` filters."

        Design: Corner/endpoints/subresource_listing_scoped_to_parent
        """
        program1 = create_active_program(name="Parent1", code="PR1")
        program2 = create_active_program(name="Parent2", code="PR2")
        cycle_k1 = create_cycle(program1["id"], label="K1")
        create_cycle(program2["id"], label="K2")

        page, meta = validate_paginated(
            api.list_program_cycles(program1["id"], DIRECTOR))
        assert meta["total_count"] == 1
        assert page[0]["id"] == cycle_k1["id"]
