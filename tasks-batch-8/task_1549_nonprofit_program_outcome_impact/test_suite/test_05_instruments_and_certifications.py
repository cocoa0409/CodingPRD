"""Instruments and certifications: publish/retire cascades, certification
suspend/reinstate, and version-pinning of observations."""
from test_helpers import (
    ApiErrorId,
    get_success_data,
    make_field_collector_headers,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    create_active_program,
    create_certification,
    create_instrument,
    publish_instrument,
    record_observation,
    set_clock,
    setup_observation_world,
)
from test_helpers.test_users import LEAD


class TestInstrumentPublishCascade:
    def test_publish_successor_retires_predecessor_and_stales_certifications(self, api):
        """PRD section 3.3: "Publishing moves an instrument `DRAFT →
        PUBLISHED` and triggers a hand-off: the predecessor revision - the
        instrument with the same program and `code` whose `instrument_version`
        is exactly one less - if currently `PUBLISHED`, transitions to
        `RETIRED`, and every certification pinned to that predecessor that is
        still `CERTIFIED` transitions to `STALE`."

        Design: Difficulty/transitive_cascade/instrument_publish_depth2
        """
        program = create_active_program(name="Nutrition", code="NTR")
        instr1 = create_instrument(program["id"], code="SURV", title="Survey v1")
        publish_instrument(instr1["id"])
        cert = create_certification(instr1["id"], staff_user_id="collector-1")
        assert cert["certified_instrument_version"] == 1

        instr2 = get_success_data(api.new_revision_instrument(instr1["id"], LEAD))
        assert instr2["status"] == "DRAFT"
        assert instr2["instrument_version"] == 2

        get_success_data(api.publish_instrument(instr2["id"], LEAD))

        instr1_after = get_success_data(api.get_instrument(instr1["id"], LEAD))
        assert instr1_after["status"] == "RETIRED"

        instr2_after = get_success_data(api.get_instrument(instr2["id"], LEAD))
        assert instr2_after["status"] == "PUBLISHED"
        assert instr2_after["instrument_version"] == 2

        cert_after = get_success_data(api.get_certification(cert["id"], LEAD))
        assert cert_after["status"] == "STALE"
        assert cert_after["certified_instrument_version"] == 1

    def test_publish_without_predecessor_is_clean(self, api):
        """PRD section 3.3: "Publishing moves an instrument `DRAFT →
        PUBLISHED` and triggers a hand-off: the predecessor revision - the
        instrument with the same program and `code` whose `instrument_version`
        is exactly one less - if currently `PUBLISHED`, transitions to
        `RETIRED`".

        Design: Difficulty/transitive_cascade/instrument_publish_depth2
        """
        program = create_active_program(name="Nutrition2", code="NT2")
        instr = create_instrument(program["id"], code="SURV", title="V1")
        published = get_success_data(api.publish_instrument(instr["id"], LEAD))
        assert published["status"] == "PUBLISHED"
        assert published["instrument_version"] == 1


class TestInstrumentRetireCascade:
    def test_instrument_retire_stales_certifications(self, api):
        """PRD section 3.3: "Retiring a `PUBLISHED` instrument directly
        (`PUBLISHED → RETIRED`, terminal) likewise stales every `CERTIFIED`
        certification pinned to it."

        Design: Corner/state_machines/instrument_retire_stales_certifications
        """
        program = create_active_program(name="Retire", code="RET")
        instr = create_instrument(program["id"], code="SURV", title="Survey")
        publish_instrument(instr["id"])
        cert = create_certification(instr["id"], staff_user_id="collector-1")

        retired = get_success_data(api.retire_instrument(instr["id"], LEAD))
        assert retired["status"] == "RETIRED"

        cert_after = get_success_data(api.get_certification(cert["id"], LEAD))
        assert cert_after["status"] == "STALE"


class TestCertificationSuspendAndReinstate:
    def test_suspend_blocks_recording_and_reinstate_restores(self, api):
        """PRD section 3.6: "Seventh and last, the certification must be in
        `CERTIFIED` status with `expires_at` strictly in the future - a
        suspended, expired, or past-due certification fails - else
        `ERR_CERTIFICATION_EXPIRED` (HTTP 422)."
        PRD section 3.3: "From there a certification can be suspended
        (`CERTIFIED → SUSPENDED`) and later reinstated (`SUSPENDED →
        CERTIFIED`)".

        Design: Corner/state_machines/certification_suspend_blocks_and_reinstate_restores
        """
        world = setup_observation_world(program_name="Susp", program_code="SUS")
        cert = world["certification"]

        get_success_data(api.suspend_certification(cert["id"], LEAD))
        blocked = api.record_observation(
            world["participant"]["id"],
            {"indicator_id": world["indicators"]["I1"]["id"],
             "instrument_id": world["instrument"]["id"],
             "value": 10, "collected_at": "2026-09-05T00:00:00Z"},
            make_field_collector_headers("collector-1"),
        )
        validate_error(blocked, ApiErrorId.ERR_CERTIFICATION_EXPIRED)

        get_success_data(api.reinstate_certification(cert["id"], LEAD))
        ok_resp = api.record_observation(
            world["participant"]["id"],
            {"indicator_id": world["indicators"]["I1"]["id"],
             "instrument_id": world["instrument"]["id"],
             "value": 10, "collected_at": "2026-09-05T00:00:00Z"},
            make_field_collector_headers("collector-1"),
        )
        obs = validate_success(ok_resp, expected_status=201)
        assert obs["review_status"] == "PENDING"

    def test_reinstate_after_version_advance_rejected(self, api):
        """PRD section 3.3: "reinstatement only succeeds while the pinned
        version still matches the instrument's current `instrument_version`;
        once the instrument has advanced past the pinned version,
        reinstatement is rejected with `ERR_CERTIFICATION_STALE` (HTTP 422)."

        Design: Corner/state_machines/certification_reinstate_after_version_advance_rejected
        """
        program = create_active_program(name="StaleCert", code="STC")
        instr1 = create_instrument(program["id"], code="SURV", title="Survey v1")
        publish_instrument(instr1["id"])
        cert = create_certification(instr1["id"], staff_user_id="collector-1")
        get_success_data(api.suspend_certification(cert["id"], LEAD))

        instr2 = get_success_data(api.new_revision_instrument(instr1["id"], LEAD))
        get_success_data(api.publish_instrument(instr2["id"], LEAD))

        reinstate_resp = api.reinstate_certification(cert["id"], LEAD)
        validate_error(reinstate_resp, ApiErrorId.ERR_CERTIFICATION_STALE)

        cert_after = get_success_data(api.get_certification(cert["id"], LEAD))
        assert cert_after["status"] == "SUSPENDED"


class TestObservationVersionPinning:
    def test_observation_pins_instrument_version(self, api):
        """PRD section 3.6: "At record time the server pins
        `instrument_version` to the instrument's current version".
        PRD section 3.3: "Publishing moves an instrument `DRAFT → PUBLISHED`
        and triggers a hand-off: the predecessor revision - the instrument
        with the same program and `code` whose `instrument_version` is exactly
        one less - if currently `PUBLISHED`, transitions to `RETIRED`".

        Design: Corner/cross_cutting_layers/observation_pins_instrument_version
        """
        world = setup_observation_world(program_name="ObsPin", program_code="OPN")
        ind = world["indicators"]["I1"]

        obs = record_observation(
            world["participant"]["id"], ind["id"], world["instrument"]["id"],
            value=10)
        assert obs["instrument_version"] == 1

        instr2 = get_success_data(
            api.new_revision_instrument(world["instrument"]["id"], LEAD))
        get_success_data(api.publish_instrument(instr2["id"], LEAD))

        obs_after = get_success_data(
            api.get_observation(obs["id"],
                                __import__("test_helpers").STEWARD))
        assert obs_after["instrument_version"] == 1, (
            "the observation's pinned instrument_version is immutable"
        )
        assert obs_after["review_status"] == "PENDING", (
            "instrument lifecycle does not touch observations"
        )
