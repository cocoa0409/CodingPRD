"""System-sourced fields, referential failures, and the identity a credential keeps."""

import pytest

from test_helpers import NON_EXISTENT_UUID, ApiErrorId
from test_helpers import assertions as ax
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_paginated, validate_success
from test_helpers.test_users import (
    ELIGIBILITY_REVIEWER_1_ID,
    ETHICS_OFFICER_1_ID,
    ITEM_AUTHOR_ID,
    make_eligibility_reviewer_headers,
    make_ethics_officer_headers,
    make_item_specialist_headers,
)

ITEM_SPECIALIST = make_item_specialist_headers(ITEM_AUTHOR_ID)
ELIGIBILITY_REVIEWER = make_eligibility_reviewer_headers(ELIGIBILITY_REVIEWER_1_ID)
ETHICS_OFFICER = make_ethics_officer_headers(ETHICS_OFFICER_1_ID)

SMUGGLED_FIELDS = {"status": "OPERATIONAL", "p_value": 0.5,
                   "author_user_id": "someone-else"}


class TestItemCreationIgnoresSmuggledSystemFields:
    """Authorship and statistics are the server's to write, not the client's."""

    def test_a_body_carrying_status_and_statistics_does_not_steer_the_row(self, api):
        """The item still starts DRAFT with null statistics and an empty approver list,
        and the programme's operational count does not move.

        PRD §3.2: "The new item's `status` is `DRAFT`, its `approver_user_ids` list is
        empty, its `review_round` starts at 1, all twelve of its response accumulators
        start at 0, and its `stat_basis_applied` starts at `INSUFFICIENT_DATA` with both
        `p_value` and `discrimination_index` null."

        PRD §3.1: "Posture is derived, never supplied: `operational_item_count` is the
        number of the program's items whose `status` is `OPERATIONAL`;
        `deficient_domain_codes` is the list of those `domain_code` values from
        `domain_specs` for which the count of the program's `OPERATIONAL` items carrying
        that `domain_code` is strictly less than the row's `min_operational_items`,
        sorted in ascending order for determinism; and `blueprint_posture` is `COMPLETE`
        when `deficient_domain_codes` is empty and `DEFICIENT` otherwise."

        Design: Corner/entities/item_creation_with_status_and_p_value_supplied_leaves_the_input_ignored
        """
        program = fx.active_program(api)

        item = validate_success(api.create_item(
            f.create_item_payload(program["id"], cognitive_level="RECALL",
                                  stem="Smuggled item", **SMUGGLED_FIELDS),
            ITEM_SPECIALIST), 201)

        assert item["status"] == "DRAFT"
        assert item["p_value"] is None
        assert item["discrimination_index"] is None
        assert item["approver_user_ids"] == []
        assert item["review_round"] == 1
        assert fx.read_program(api, program["id"])["operational_item_count"] == 0
        ax.assert_item(item)

    def test_authorship_is_taken_from_the_acting_identity(self, api):
        """The `author_user_id` in the body is discarded in favour of the acting
        `X-User-ID`.

        PRD §3.2: "Authorship is taken from the acting identity, not from the payload:
        `author_user_id` is set to the acting `X-User-ID` and any value a client supplies
        for it is ignored."

        Design: Corner/entities/item_creation_with_status_and_p_value_supplied_leaves_the_input_ignored
        """
        program = fx.active_program(api)

        item = validate_success(api.create_item(
            f.create_item_payload(program["id"], cognitive_level="RECALL",
                                  stem="Smuggled item", **SMUGGLED_FIELDS),
            ITEM_SPECIALIST), 201)

        assert item["author_user_id"] == ITEM_AUTHOR_ID
        assert item["author_user_id"] != "someone-else"


class TestItemCreationAgainstAnUnknownParent:
    """A body-carried foreign key is a referential check, not a shape check."""

    def test_an_unknown_program_id_in_the_body_answers_program_not_found(self, api):
        """The creation is refused with the referenced collection's 404 rather than a 400,
        and no orphan item is written under the real programme.

        PRD §2.7: "**Body-reference existence.** Every foreign identifier carried in a
        request body resolves to a stored record, with the 404 that matches the referenced
        collection. This layer guards item creation, form assembly, application
        submission, registration creation, and disciplinary case opening."

        Design: Corner/entities/item_creation_against_an_unknown_program_id_returns_program_not_found
        """
        program = fx.active_program(api)

        refused = api.create_item(
            f.create_item_payload(NON_EXISTENT_UUID, cognitive_level="RECALL",
                                  stem="Orphan item"),
            ITEM_SPECIALIST)

        error = validate_error(refused, ApiErrorId.ERR_PROGRAM_NOT_FOUND.value, 404)
        assert error["error_id"] != ApiErrorId.ERR_INVALID_REQUEST.value
        assert error["error_id"] != ApiErrorId.ERR_ITEM_DOMAIN_MISMATCH.value
        _rows, meta = validate_paginated(
            api.list_program_items(program["id"], fx.PROGRAM_ADMIN))
        assert meta["total_count"] == 0


class TestCredentialIdentitySurvivesACycleClose:
    """Closing a cycle re-issues the period without re-minting the identity."""

    def _satisfied_holder(self, api):
        state = fx.pipeline_through_certificant(api)
        cycle = fx.satisfied_cycle(api, state)
        assert cycle["status"] == "SATISFIED"
        return state

    def test_the_certificate_number_and_issue_date_are_untouched_by_the_close(self, api):
        """Both identity fields read exactly as they did at minting, and the closing cycle
        keeps the credit it counted.

        PRD §3.10: "When the released registration's `outcome` is `PASS` and the candidate
        does not already hold a credential awaiting re-examination, **hop one** mints a
        certificant for the candidate-and-program pair: its `candidate_id` and
        `program_id` are taken from the registration and its application rather than
        supplied by any client, its `status` is `ACTIVE`, its `publication_status` is
        `PUBLISHED`, its `issued_on` is stamped from the logical clock, and its
        `certificate_number` is minted as described below."

        PRD §3.10: "It is composed as the program's `credential_code`, a hyphen, the
        four-digit year of the logical clock at minting, another hyphen, and the program's
        issue sequence zero-padded to five digits — where the sequence is the value of
        `certificants_issued_count` after that counter has been incremented for this
        minting."

        Design: Corner/entities/certificant_certificate_number_and_issued_on_survive_a_cycle_close
        """
        state = self._satisfied_holder(api)
        before = fx.read_certificant(api, state.certificant_id)
        assert before["certificate_number"] == "CPX-2026-00001"
        assert str(before["issued_on"]).startswith("2026-08-10")

        validate_success(api.close_cycle(
            state.cycle_id, f.close_cycle_payload(before["version"]),
            fx.PROGRAM_ADMIN), 200)

        after = fx.read_certificant(api, state.certificant_id)
        assert after["certificate_number"] == before["certificate_number"]
        assert after["issued_on"] == before["issued_on"]
        closed = fx.read_cycle(api, state.cycle_id)
        assert closed["status"] == "CLOSED"
        assert float(closed["credits_applied"]) == pytest.approx(12.00, abs=0.01)

    def test_the_close_advances_the_period_and_repoints_at_a_successor_cycle(self, api):
        """A successor cycle is opened carrying nothing forward under the strict basis,
        the validity date advances by one cycle length, and the credential's version
        increments once.

        PRD §3.11: "**Hop two:** because the cycle closed, the certificant's
        `valid_through` advances by the program's `cycle_length_months` and the
        certificant's `version` increments by 1."

        PRD §3.11: "**Hop three:** because `valid_through` advanced, a successor cycle is
        opened with `cycle_number` one greater than the closing cycle's, `starts_on` equal
        to the closing cycle's `ends_on`, `carryover_credits_in` equal to the closing
        cycle's `carryover_credits_out`, and `required_credits` and
        `accrual_basis_snapshot` freshly re-pinned from the program as it stands now; the
        certificant's `current_cycle_id` is repointed at the successor."

        Design: Corner/entities/certificant_certificate_number_and_issued_on_survive_a_cycle_close
        """
        state = self._satisfied_holder(api)
        before = fx.read_certificant(api, state.certificant_id)

        validate_success(api.close_cycle(
            state.cycle_id, f.close_cycle_payload(before["version"]),
            fx.PROGRAM_ADMIN), 200)

        cycles = fx.read_cycles_of(api, state.certificant_id)
        assert len(cycles) == 2
        successor = [cycle for cycle in cycles if cycle["id"] != state.cycle_id][0]
        assert successor["cycle_number"] == 2
        assert successor["status"] == "OPEN"
        assert float(successor["required_credits"]) == pytest.approx(12.0, abs=0.01)
        assert float(successor["carryover_credits_in"]) == pytest.approx(0.00, abs=0.01)

        after = fx.read_certificant(api, state.certificant_id)
        assert str(after["valid_through"]).startswith("2028-08-10")
        assert after["current_cycle_id"] == successor["id"]
        assert after["status"] == "ACTIVE"
        assert after["version"] == before["version"] + 1


class TestEveryReadHasItsOwnNotFound:
    """One unknown uuid, eight endpoints, eight different error identifiers."""

    def test_the_eight_read_endpoints_answer_eight_distinct_not_founds(self, api):
        """No shared generic 404 and no empty success: each read reports the error
        identifier of its own collection, and the eight are pairwise distinct.

        PRD §2.7: "**Path existence.** Every identifier in the URL path resolves to a
        stored record → otherwise the matching 404: `ERR_PROGRAM_NOT_FOUND`,
        `ERR_ITEM_NOT_FOUND`, `ERR_FORM_NOT_FOUND`, `ERR_CANDIDATE_NOT_FOUND`,
        `ERR_APPLICATION_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`,
        `ERR_REGISTRATION_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`,
        `ERR_CERTIFICANT_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND`, `ERR_ACTIVITY_NOT_FOUND`, or
        `ERR_CASE_NOT_FOUND`."

        Design: Corner/entities/reads_with_an_unknown_id_answer_the_entity_specific_not_found
        """
        reads = [
            (api.get_form(NON_EXISTENT_UUID, fx.PSYCHOMETRICIAN),
             ApiErrorId.ERR_FORM_NOT_FOUND.value),
            (api.get_application(NON_EXISTENT_UUID, ELIGIBILITY_REVIEWER),
             ApiErrorId.ERR_APPLICATION_NOT_FOUND.value),
            (api.get_exam_session(NON_EXISTENT_UUID, fx.EXAM_OPERATIONS),
             ApiErrorId.ERR_SESSION_NOT_FOUND.value),
            (api.get_exam_registration(NON_EXISTENT_UUID, fx.EXAM_OPERATIONS),
             ApiErrorId.ERR_REGISTRATION_NOT_FOUND.value),
            (api.get_security_incident(NON_EXISTENT_UUID, fx.EXAM_OPERATIONS),
             ApiErrorId.ERR_INCIDENT_NOT_FOUND.value),
            (api.get_recertification_cycle(NON_EXISTENT_UUID, fx.PROGRAM_ADMIN),
             ApiErrorId.ERR_CYCLE_NOT_FOUND.value),
            (api.get_ceu_activity(NON_EXISTENT_UUID, fx.PROGRAM_ADMIN),
             ApiErrorId.ERR_ACTIVITY_NOT_FOUND.value),
            (api.get_disciplinary_case(NON_EXISTENT_UUID, ETHICS_OFFICER),
             ApiErrorId.ERR_CASE_NOT_FOUND.value),
        ]

        observed = []
        for response, expected_error_id in reads:
            error = validate_error(response, expected_error_id, 404)
            observed.append(error["error_id"])

        assert len(set(observed)) == 8

    def test_each_not_found_body_carries_only_an_error_id_and_a_message(self, api):
        """The error envelope is exactly the declared one — no leaked entity, no extra
        keys under `data`, and a `meta` holding only the two request fields.

        PRD §2.2: "The `meta` object for error responses contains only `api_request_id`
        and `api_request_timestamp`."

        PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the
        specific error."

        Design: Corner/entities/reads_with_an_unknown_id_answer_the_entity_specific_not_found
        """
        responses = [
            api.get_form(NON_EXISTENT_UUID, fx.PSYCHOMETRICIAN),
            api.get_application(NON_EXISTENT_UUID, ELIGIBILITY_REVIEWER),
            api.get_exam_session(NON_EXISTENT_UUID, fx.EXAM_OPERATIONS),
            api.get_exam_registration(NON_EXISTENT_UUID, fx.EXAM_OPERATIONS),
            api.get_security_incident(NON_EXISTENT_UUID, fx.EXAM_OPERATIONS),
            api.get_recertification_cycle(NON_EXISTENT_UUID, fx.PROGRAM_ADMIN),
            api.get_ceu_activity(NON_EXISTENT_UUID, fx.PROGRAM_ADMIN),
            api.get_disciplinary_case(NON_EXISTENT_UUID, ETHICS_OFFICER),
        ]

        for response in responses:
            assert response.status_code == 404
            body = response.json()
            assert body["response_type"] == "error"
            assert set(body["data"].keys()) == {"error_id", "message"}
            assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}
