"""One envelope for every rejection, and the schema check ahead of everything else.

A 404 on existence, a 400 on schema and a 409 on state all come back in the same
shape, with exactly two keys under data, and none of them writes anything.
"""

from test_helpers import (
    COMPLIANCE_OFFICER_HEADERS,
    EvaluationStatus,
    HoldType,
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_error,
    assert_first_failing_check,
    assert_page,
    create_evaluation,
    create_patient,
    read_evaluation,
)

REJECTED_HOLD_TYPE = "EMERGENCY_14D"
ERROR_DATA_KEYS = {"error_id", "message"}


class TestErrorEnvelopeAcrossFamilies:
    """Existence, schema and state rejections share one envelope and mutate nothing."""

    def test_every_rejection_family_returns_the_same_two_key_error_payload(
        self, api, roster
    ):
        """A 404, a 400 that outranks its own 404, and a 409 on a draft evaluation.

        PRD 2.2: "The `meta` object for error responses contains only `api_request_id`
        and `api_request_timestamp`."

        PRD 2.2: "The `error_id` is a unique, machine-readable string that identifies
        the specific error."

        PRD 2.9: "`ERR_INVALID_REQUEST` — on every endpoint: required body fields
        present, enum members valid, integers within their declared bounds, hearing
        `duration_minutes` equal to either 30 or 60, `hold_type` equal to
        `EMERGENCY_72H` when a hold is initiated, and `requested_hold_type` equal to
        `EXTENSION_14D` when a petition is filed."

        PRD 2.9: "`ERR_EVALUATION_NOT_SIGNED` — the evaluation is in `SIGNED`; on hold
        initiation and admission creation."

        Design: Corner/errors/every_error_family_returns_the_same_envelope_and_declared_status
        """
        patient = create_patient(
            api,
            mrn="MRN-2367-EV",
            legal_name="Envelope Case",
            age_years=44,
            gender_care_category="FEMALE",
        )
        draft = create_evaluation(
            api,
            roster.intake_headers,
            patient["id"],
            danger_to_self=True,
            danger_to_others=False,
            grave_disability=False,
            capacity_present=False,
        )
        assert draft["status"] == EvaluationStatus.DRAFT.value

        missing_unit = assert_error(
            api.get_unit(COMPLIANCE_OFFICER_HEADERS, NON_EXISTENT_UUID),
            ApiErrorId.UNIT_NOT_FOUND,
        )
        assert set(missing_unit) == ERROR_DATA_KEYS
        assert missing_unit["message"].strip() != ""

        bad_schema = api.create_hold(
            roster.intake_headers,
            {
                "patient_id": patient["id"],
                "evaluation_id": NON_EXISTENT_UUID,
                "hold_type": REJECTED_HOLD_TYPE,
            },
        )
        assert_first_failing_check(
            bad_schema,
            ApiErrorId.INVALID_REQUEST,
            (ApiErrorId.EVALUATION_NOT_FOUND,),
        )

        wrong_state = api.create_hold(
            roster.intake_headers,
            {
                "patient_id": patient["id"],
                "evaluation_id": draft["id"],
                "hold_type": HoldType.EMERGENCY_72H.value,
            },
        )
        assert_error(wrong_state, ApiErrorId.EVALUATION_NOT_SIGNED)

        assert_page(
            api.list_holds(COMPLIANCE_OFFICER_HEADERS, patient_id=patient["id"]), 0
        )
        untouched = read_evaluation(api, draft["id"])
        assert untouched["status"] == EvaluationStatus.DRAFT.value
        assert untouched["version"] == draft["version"]
