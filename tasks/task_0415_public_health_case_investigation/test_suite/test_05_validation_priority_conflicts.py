"""Validation-precedence conflicts: when two checks could both fire on one request, the
PRD's fixed precedence ladder determines the single observable error.

Queue A (Difficulty): priority_pair_validation_conflict.
"""
import pytest

from test_helpers import (
    api_client,
    validate_error,
    get_success_data,
    make_investigator_headers,
    make_tracer_headers,
    make_intake_headers,
    ApiErrorId,
    create_contact_payload,
)
from test_helpers import fixtures as fx

# A well-formed-but-non-existent UUIDv4-shaped token (matches the design index literal).
MISSING_UUID = "00000000-0000-4000-8000-000000000000"


class TestReferential404BeatsScope403:
    """A contact elicitation that BOTH names a non-existent source_case_id AND is issued by a
    tracer scoped to the wrong jurisdiction returns the FK 404, not the scope 403."""

    def test_missing_fk_returns_404_not_scope_403(self, api):
        """PRD §2.6: "Existence of every body foreign key within the program (the relevant
        not-found error) is fourth. The jurisdiction scope check
        (`ERR_JURISDICTION_SCOPE_VIOLATION`) for scoped roles is fifth."
        PRD §2.5: "On any create or resolve operation, the foreign keys it accepts — `program_id`,
        `jurisdiction_id`, `condition_code`, `source_case_id`, `lab_result_id`, `contact_id`,
        `to_jurisdiction_id`, and `case_id` — must each reference an existing row within the same
        program; an unresolved reference yields the corresponding not-found error."

        Design: Difficulty/priority_pair_validation_conflict/referential_404_beats_jurisdiction_scope_403
        """
        program = fx.create_program()
        j1 = fx.create_jurisdiction(program["id"], name="County 1", fips_code="06001")
        j2 = fx.create_jurisdiction(program["id"], name="County 2", fips_code="06002")
        fx.create_condition(program["id"])
        # Tracer scoped to J2 elicits a contact whose source_case_id does not exist and whose
        # monitoring_jurisdiction_id is J1 (outside J2's scope). FK 404 must win.
        res = api.create_contact(
            create_contact_payload(
                program["id"], MISSING_UUID, j1["id"], contact_reference="K-BAD",
                exposure_setting="HOUSEHOLD", proximity_meters=0.5,
                cumulative_exposure_minutes=30, last_exposure_date="2026-03-15T00:00:00.000Z",
            ),
            make_tracer_headers(j2["id"]),
        )
        validate_error(res, ApiErrorId.ERR_CASE_NOT_FOUND.value)

    def test_scope_403_is_the_suppressed_outcome(self, api):
        """PRD §2.6: "The jurisdiction scope check (`ERR_JURISDICTION_SCOPE_VIOLATION`) for
        scoped roles is fifth."
        PRD §2.1: "When `X-User-Role` is `ContactTracer`, `X-User-ID` is the `id` of the acting
        `Jurisdiction`, and the tracer may act only on contacts whose `monitoring_jurisdiction_id`
        equals `X-User-ID`. Any attempt by a scoped role to operate on a resource outside its own
        jurisdiction is denied with `ERR_JURISDICTION_SCOPE_VIOLATION`."

        Design: Difficulty/priority_pair_validation_conflict/referential_404_beats_jurisdiction_scope_403
        """
        # Same wrong-scope elicitation, but now with an EXISTING source_case_id, so the FK 404
        # cannot pre-empt: the fifth-priority scope check is the outcome that the 404 suppressed.
        program = fx.create_program()
        j1 = fx.create_jurisdiction(program["id"], name="County 1", fips_code="06001")
        j2 = fx.create_jurisdiction(program["id"], name="County 2", fips_code="06002")
        fx.create_condition(program["id"])
        ci = fx.open_and_interview_case(program["id"], j1["id"], case_overrides={"patient_reference": "PT-I"})
        res = api.create_contact(
            create_contact_payload(
                program["id"], ci["id"], j1["id"], contact_reference="K-SCOPE",
                exposure_setting="HOUSEHOLD", proximity_meters=0.5,
                cumulative_exposure_minutes=30, last_exposure_date="2026-03-15T00:00:00.000Z",
            ),
            make_tracer_headers(j2["id"]),
        )
        validate_error(res, ApiErrorId.ERR_JURISDICTION_SCOPE_VIOLATION.value)


class TestState409BeatsLabConditionMismatch:
    """Linking a mismatched-condition lab to a CLOSED case returns the state error
    ERR_CASE_NOT_LINKABLE, not the condition-mismatch error."""

    def test_closed_case_link_returns_not_linkable_not_condition_mismatch(self, api):
        """PRD §3.2: "The target case must not be `CLOSED`, or the link is rejected with
        `ERR_CASE_NOT_LINKABLE`. Two attribute checks then run in a fixed order: the lab result's
        `condition_code` must equal the case's `condition_code`, checked first and rejected with
        `ERR_LAB_CONDITION_MISMATCH`".

        Design: Difficulty/priority_pair_validation_conflict/state_409_beats_lab_condition_mismatch_409_on_link
        """
        program = fx.create_program()
        j1 = fx.create_jurisdiction(program["id"], fips_code="06001")
        fx.create_condition(program["id"], condition_code="COVID19", requires_lab_confirmation=False)
        fx.create_condition(
            program["id"], condition_code="MEASLES", display_name="Measles",
            presymptomatic_days=4, infectious_tail_days=4, quarantine_days=21,
            test_based_release_days=14, isolation_min_days=4, fever_free_days=0,
            requires_lab_confirmation=False,
        )
        j = j1["id"]
        # COVID19 case, interviewed, classified PROBABLE, then CLOSED.
        cl = fx.open_interview_classify_case(
            program["id"], j, "PROBABLE",
            case_overrides={"patient_reference": "PT-L", "condition_code": "COVID19"},
        )
        validate_get = api.close_case(cl["id"], make_investigator_headers(j))
        get_success_data(validate_get)
        # A RECEIVED MEASLES lab (different condition), unlinked.
        lm = fx.intake_lab(
            program["id"], j, condition_code="MEASLES", patient_reference="PT-OTHER",
            result_value="POSITIVE",
        )
        res = api.link_lab_result(cl["id"], {"lab_result_id": lm["id"]}, make_investigator_headers(j))
        validate_error(res, ApiErrorId.ERR_CASE_NOT_LINKABLE.value)

    def test_condition_mismatch_is_the_suppressed_outcome(self, api):
        """PRD §3.2: "the lab result's `condition_code` must equal the case's `condition_code`,
        checked first and rejected with `ERR_LAB_CONDITION_MISMATCH`".
        PRD §2.6: "The state-legality check for the requested transition (a state-specific
        conflict error) is seventh. Domain-specific temporal and business constraints follow
        after that".

        Design: Difficulty/priority_pair_validation_conflict/state_409_beats_lab_condition_mismatch_409_on_link
        """
        # Same mismatched-condition lab, but the case is NOT closed (UNDER_INVESTIGATION), so the
        # state check cannot pre-empt: the condition-mismatch error is the outcome the CLOSED case
        # suppressed.
        program = fx.create_program()
        j1 = fx.create_jurisdiction(program["id"], fips_code="06001")
        fx.create_condition(program["id"], condition_code="COVID19", requires_lab_confirmation=False)
        fx.create_condition(
            program["id"], condition_code="MEASLES", display_name="Measles",
            presymptomatic_days=4, infectious_tail_days=4, quarantine_days=21,
            test_based_release_days=14, isolation_min_days=4, fever_free_days=0,
            requires_lab_confirmation=False,
        )
        j = j1["id"]
        ci = fx.open_and_interview_case(
            program["id"], j,
            case_overrides={"patient_reference": "PT-L", "condition_code": "COVID19"},
        )
        lm = fx.intake_lab(
            program["id"], j, condition_code="MEASLES", patient_reference="PT-OTHER",
            result_value="POSITIVE",
        )
        res = api.link_lab_result(ci["id"], {"lab_result_id": lm["id"]}, make_investigator_headers(j))
        validate_error(res, ApiErrorId.ERR_LAB_CONDITION_MISMATCH.value)
