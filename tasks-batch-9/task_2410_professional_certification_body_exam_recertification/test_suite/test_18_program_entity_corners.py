"""The programme record: echoed inputs, declared defaults, derived counters, and the
shape of a refusal.
"""

import copy

import pytest

from test_helpers import NON_EXISTENT_UUID, ApiErrorId
from test_helpers import assertions as ax
from test_helpers import constants as k
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_paginated, validate_success
from test_helpers.test_users import ITEM_AUTHOR_ID, make_item_specialist_headers

ITEM_SPECIALIST = make_item_specialist_headers(ITEM_AUTHOR_ID)

TWO_DOMAIN_BLUEPRINT = [
    {"domain_code": "D1", "weight_pct": 60, "min_operational_items": 1},
    {"domain_code": "D2", "weight_pct": 40, "min_operational_items": 1},
]
MINIMAL_PROGRAM = {
    "name": "Certified Practitioner X",
    "credential_code": "CPX",
    "jta_version": "JTA-2026.1",
    "domain_specs": TWO_DOMAIN_BLUEPRINT,
    "form_length": 2,
    "accepted_education_credentials": ["BACHELOR", "MASTER"],
}


def _minimal_program(**overrides):
    """A creation body carrying only the six required inputs, so every optional knob
    is left to its declared default.
    """
    payload = copy.deepcopy(MINIMAL_PROGRAM)
    payload.update(overrides)
    return payload


class TestProgramCreationEnvelope:
    """What a creation answers with, and what it computes on the way out."""

    def test_creation_answers_201_with_the_object_envelope_and_echoed_inputs(self, api):
        """Every supplied input comes back verbatim inside a success envelope whose
        `response_type` is `object`.

        PRD §2.10: "Operations that bring a new resource into existence answer with
        **HTTP 201**."

        PRD §3.1: "A `ProgramAdmin` creates it with the credential's `name`, a short
        `credential_code` of between 2 and 12 uppercase characters, the `jta_version`
        label of the analysis that produced the blueprint (for example `JTA-2026.1`), a
        `form_length` of at least 1 giving the exact number of positions every form of
        this program must carry, a non-empty `accepted_education_credentials` list drawn
        from `DIPLOMA`, `ASSOCIATE`, `BACHELOR`, `MASTER`, and `DOCTORATE`, and the
        blueprint itself as `domain_specs`."

        Design: Corner/entities/program_creation_returns_201_with_draft_status_and_echoed_inputs
        """
        response = api.create_program(_minimal_program(), fx.PROGRAM_ADMIN)

        program = validate_success(response, 201)
        body = response.json()
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"]

        assert program["name"] == "Certified Practitioner X"
        assert program["credential_code"] == "CPX"
        assert program["jta_version"] == "JTA-2026.1"
        assert program["form_length"] == 2
        assert program["accepted_education_credentials"] == ["BACHELOR", "MASTER"]
        assert [row["weight_pct"] for row in program["domain_specs"]] == [60, 40]
        assert [row["domain_code"] for row in program["domain_specs"]] == ["D1", "D2"]
        ax.assert_certification_program(program)

    def test_a_fresh_programme_is_draft_at_version_one_with_a_computed_posture(self, api):
        """The counters start at zero and the posture is already computed — a two-row
        blueprint asking for one operational item each reads DEFICIENT, not null.

        PRD §3.1: "Its `operational_item_count` starts at 0, its
        `verified_application_counter` starts at 0, and its `certificants_issued_count`
        starts at 0."

        PRD §3.1: "Its `blueprint_posture` is computed immediately and will therefore
        read `DEFICIENT` unless every row of `domain_specs` asks for zero operational
        items, in which case it reads `COMPLETE`."

        PRD §2.4: "`version` is an integer that starts at 1 when the resource is created
        and increments by 1 on every mutation of that record, including mutations reached
        indirectly through a cascade."

        Design: Corner/entities/program_creation_returns_201_with_draft_status_and_echoed_inputs
        """
        program = validate_success(
            api.create_program(_minimal_program(), fx.PROGRAM_ADMIN), 201)

        assert program["status"] == "DRAFT"
        assert program["version"] == 1
        assert str(program["created_at"]).startswith("2026-08-01T00:00:00")
        assert str(program["updated_at"]).startswith("2026-08-01T00:00:00")
        assert program["operational_item_count"] == 0
        assert program["deficient_domain_codes"] == ["D1", "D2"]
        assert program["blueprint_posture"] == "DEFICIENT"
        assert program["verified_application_counter"] == 0
        assert program["certificants_issued_count"] == 0


class TestProgramOptionalDefaults:
    """Twenty-one omitted knobs must surface as their declared literals."""

    def test_the_psychometric_and_standard_setting_knobs_take_their_defaults(self, api):
        """Omitting the psychometric, durability and standard-setting knobs yields the
        declared literals rather than nulls.

        PRD §3.1: "The rest of the program record is a bank of tuning knobs, each
        optional at creation and each with a governing default."

        PRD §3.1: "Psychometric behaviour is set by `psychometric_stat_basis`, which is
        either `POOLED` or `OPERATIONAL_ONLY` and defaults to `OPERATIONAL_ONLY`; by
        `min_discrimination`, defaulting to 0.15; by `min_p_value`, defaulting to 0.20;
        by `max_p_value`, defaulting to 0.95; and by `min_responses_for_stats`,
        defaulting to 30."

        PRD §3.1: "Form durability is set by `form_retirement_tolerance_pct`, defaulting
        to 10."

        PRD §3.1: "Standard setting is governed by `min_panelists`, defaulting to 5, by
        `panel_trim_count`, defaulting to 1, and by `cut_score_sem_multiplier`,
        defaulting to 0.5."

        Design: Corner/entities/program_creation_applies_every_optional_default_when_the_input_is_omitted
        """
        program = validate_success(
            api.create_program(_minimal_program(), fx.PROGRAM_ADMIN), 201)

        assert program["psychometric_stat_basis"] == k.PROGRAM_DEFAULTS[
            "psychometric_stat_basis"]
        assert float(program["min_discrimination"]) == pytest.approx(
            k.PROGRAM_DEFAULTS["min_discrimination"], abs=0.0001)
        assert float(program["min_p_value"]) == pytest.approx(
            k.PROGRAM_DEFAULTS["min_p_value"], abs=0.0001)
        assert float(program["max_p_value"]) == pytest.approx(
            k.PROGRAM_DEFAULTS["max_p_value"], abs=0.0001)
        assert program["min_responses_for_stats"] == 30
        assert program["form_retirement_tolerance_pct"] == 10
        assert program["min_panelists"] == 5
        assert program["panel_trim_count"] == 1
        assert float(program["cut_score_sem_multiplier"]) == pytest.approx(0.5, abs=0.0001)

    def test_the_eligibility_commerce_and_recertification_knobs_take_their_defaults(
            self, api):
        """The screening, fee and recertification knobs are likewise populated from the
        governing defaults, including the accrual basis enum.

        PRD §3.1: "Eligibility screening is governed by `education_recency_years`,
        defaulting to 10, by `min_experience_months`, defaulting to 24 — that is, two
        years of qualifying practice — by `audit_every_nth`, defaulting to 3 and never
        below 1, and by `eligibility_valid_days`, defaulting to 365."

        PRD §3.1: "Examination commerce is governed by `exam_fee_cents`, defaulting to
        45000 — a fee of four hundred and fifty dollars — by `max_attempts_per_cycle`,
        defaulting to 3, and by `retake_wait_days`, defaulting to 45."

        PRD §3.1: "Recertification is governed by `cycle_length_months`, defaulting to
        36 — a three-year cycle — by `required_ceu_credits`, defaulting to 60, by
        `ceu_credit_accrual_basis`, which is either `STRICT_CYCLE` or
        `CARRYOVER_ALLOWED` and defaults to `STRICT_CYCLE`, by
        `ceu_carryover_max_credits`, defaulting to 10, and by `recert_grace_days`,
        defaulting to 90 — roughly a quarter's forbearance after a cycle's nominal end."

        Design: Corner/entities/program_creation_applies_every_optional_default_when_the_input_is_omitted
        """
        program = validate_success(
            api.create_program(_minimal_program(), fx.PROGRAM_ADMIN), 201)

        assert program["education_recency_years"] == 10
        assert program["min_experience_months"] == 24
        assert program["audit_every_nth"] == 3
        assert program["eligibility_valid_days"] == 365
        assert program["exam_fee_cents"] == 45000
        assert program["max_attempts_per_cycle"] == 3
        assert program["retake_wait_days"] == 45
        assert program["cycle_length_months"] == 36
        assert program["required_ceu_credits"] == 60
        assert program["ceu_credit_accrual_basis"] == "STRICT_CYCLE"
        assert program["ceu_carryover_max_credits"] == 10
        assert program["recert_grace_days"] == 90
        ax.assert_integer_cents(program["exam_fee_cents"])


class TestProgramRetrievalAndListing:
    """Reads return the stored row, and collections page it."""

    def test_retrieval_after_activation_returns_the_stored_row_with_inputs_intact(
            self, api):
        """Activation advances the status and the version and leaves every input field
        and the creation stamp exactly as they were — and it does not require a complete
        blueprint.

        PRD §3.1: "Activation is the `ProgramAdmin`'s gate, optionally annotated with an
        `activation_note`, and it moves the program `DRAFT → ACTIVE`."

        PRD §3.1: "Activation also recomputes `blueprint_posture`,
        `operational_item_count`, and `deficient_domain_codes` on the newly activated
        program."

        PRD §2.4: "`created_at` and `updated_at` are ISO 8601 UTC timestamps with three
        fractional digits, the former fixed at creation and the latter refreshed on every
        mutation that changes the record."

        Design: Corner/entities/program_retrieval_by_id_returns_the_stored_row_unchanged_by_activation
        """
        created = validate_success(
            api.create_program(_minimal_program(), fx.PROGRAM_ADMIN), 201)
        # `updated_at` is only observably "refreshed" once the instant it is
        # stamped from has moved on from the creation instant, so advance the
        # logical clock between the two mutations.
        fx.set_clock(api, "2026-08-02T00:00:00Z")
        validate_success(api.activate_program(
            created["id"], f.activate_program_payload(), fx.PROGRAM_ADMIN), 200)

        stored = validate_success(api.get_program(created["id"], ITEM_SPECIALIST), 200)

        assert stored["status"] == "ACTIVE"
        assert stored["version"] == 2
        assert stored["credential_code"] == created["credential_code"]
        assert stored["form_length"] == created["form_length"]
        assert stored["domain_specs"] == created["domain_specs"]
        assert stored["created_at"] == created["created_at"]
        assert stored["updated_at"] != created["updated_at"]
        assert stored["blueprint_posture"] == "DEFICIENT"

    def test_three_programmes_page_two_at_a_time_with_a_stable_total(self, api):
        """`total_count` counts the whole filtered set rather than the page, `has_more`
        flips on the last page, and the two pages partition the three rows.

        PRD §2.3: "Every list response echoes `limit`, `offset`, `total_count`, and
        `has_more` inside the `meta` object, where `total_count` is the number of records
        matching the filters before pagination and `has_more` indicates whether records
        remain beyond the current page."

        PRD §2.3: "Unless a specific operation says otherwise, list results are ordered
        by `created_at` ascending."

        Design: Corner/entities/program_listing_pages_three_rows_with_limit_two_and_reports_has_more
        """
        first = validate_success(
            api.create_program(_minimal_program(), fx.PROGRAM_ADMIN), 201)
        second = validate_success(api.create_program(
            _minimal_program(name="Certified Practitioner Y", credential_code="CPY"),
            fx.PROGRAM_ADMIN), 201)
        third = validate_success(api.create_program(
            _minimal_program(name="Certified Practitioner Z", credential_code="CPZ"),
            fx.PROGRAM_ADMIN), 201)

        page_one_response = api.list_programs(fx.PROGRAM_ADMIN, {"limit": 2, "offset": 0})
        page_two_response = api.list_programs(fx.PROGRAM_ADMIN, {"limit": 2, "offset": 2})

        page_one, meta_one = validate_paginated(page_one_response)
        page_two, meta_two = validate_paginated(page_two_response)

        assert len(page_one) == 2
        assert meta_one["total_count"] == 3
        assert meta_one["limit"] == 2
        assert meta_one["offset"] == 0
        assert meta_one["has_more"] is True

        assert len(page_two) == 1
        assert meta_two["total_count"] == 3
        assert meta_two["offset"] == 2
        assert meta_two["has_more"] is False

        paged_ids = [row["id"] for row in page_one] + [row["id"] for row in page_two]
        assert len(set(paged_ids)) == 3
        assert set(paged_ids) == {first["id"], second["id"], third["id"]}
        assert page_one_response.json()["response_type"] == "array"
        assert page_two_response.json()["response_type"] == "array"


class TestProgramRefusals:
    """Unknown identifiers and malformed bodies, and what they leave behind."""

    def test_an_unknown_programme_id_answers_the_programme_specific_not_found(self, api):
        """The lookup fails with the programme's own 404 error identifier inside an error
        envelope, and the stored programme is untouched.

        PRD §2.7: "**Path existence.** Every identifier in the URL path resolves to a
        stored record → otherwise the matching 404: `ERR_PROGRAM_NOT_FOUND`,
        `ERR_ITEM_NOT_FOUND`, `ERR_FORM_NOT_FOUND`, `ERR_CANDIDATE_NOT_FOUND`,
        `ERR_APPLICATION_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`,
        `ERR_REGISTRATION_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`,
        `ERR_CERTIFICANT_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND`, `ERR_ACTIVITY_NOT_FOUND`, or
        `ERR_CASE_NOT_FOUND`."

        PRD §2.2: "The `message` provides a human-readable explanation of what went
        wrong."

        Design: Corner/entities/program_lookup_with_an_unknown_id_returns_program_not_found
        """
        incumbent = fx.active_program(api, **_minimal_program())

        refused = api.get_program(NON_EXISTENT_UUID, fx.PROGRAM_ADMIN)

        error = validate_error(refused, ApiErrorId.ERR_PROGRAM_NOT_FOUND.value, 404)
        assert refused.json()["response_type"] == "error"
        assert error["message"].strip()
        assert fx.read_program(api, incumbent["id"])["status"] == "ACTIVE"

    def test_creation_without_a_credential_code_fails_the_shape_check(self, api):
        """A missing required field is a 400 shape failure, not the uniqueness refusal
        that sits below it in the order, and no row survives the attempt.

        PRD §2.7: "**Schema.** All required body fields present, enum values within their
        declared sets, integers non-negative, array sizes within their declared bounds,
        timestamps ISO 8601 → otherwise `ERR_INVALID_REQUEST` (400). Applies to every
        write operation."

        PRD §2.7: "**The first violated rule wins and its error is returned; no later
        rule is evaluated.**"

        Design: Corner/entities/program_creation_without_credential_code_returns_invalid_request
        """
        body = _minimal_program()
        del body["credential_code"]

        refused = api.create_program(body, fx.PROGRAM_ADMIN)

        error = validate_error(refused, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
        assert error["error_id"] != ApiErrorId.ERR_CREDENTIAL_CODE_TAKEN.value
        _rows, meta = validate_paginated(api.list_programs(fx.PROGRAM_ADMIN))
        assert meta["total_count"] == 0

    def test_a_non_integer_form_length_is_rejected_rather_than_coerced(self, api):
        """A string that merely looks like a number does not become a `form_length`, and
        nothing is written.

        PRD §2.7: "**Schema.** All required body fields present, enum values within their
        declared sets, integers non-negative, array sizes within their declared bounds,
        timestamps ISO 8601 → otherwise `ERR_INVALID_REQUEST` (400). Applies to every
        write operation."

        Design: Corner/entities/program_creation_with_a_non_integer_form_length_returns_invalid_request
        """
        refused = api.create_program(_minimal_program(form_length="two"), fx.PROGRAM_ADMIN)

        validate_error(refused, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
        _rows, meta = validate_paginated(api.list_programs(fx.PROGRAM_ADMIN))
        assert meta["total_count"] == 0


class TestProgramComputedCounters:
    """Only the events named by the PRD move the derived counters."""

    def test_the_counters_stay_zero_while_the_item_is_only_a_draft(self, api):
        """A DRAFT item exists in the programme and still contributes nothing: coverage
        counts only OPERATIONAL items, and the application and credential counters have
        had no event at all.

        PRD §3.1: "Posture is derived, never supplied: `operational_item_count` is the
        number of the program's items whose `status` is `OPERATIONAL`;
        `deficient_domain_codes` is the list of those `domain_code` values from
        `domain_specs` for which the count of the program's `OPERATIONAL` items carrying
        that `domain_code` is strictly less than the row's `min_operational_items`,
        sorted in ascending order for determinism; and `blueprint_posture` is `COMPLETE`
        when `deficient_domain_codes` is empty and `DEFICIENT` otherwise."

        PRD §3.2: "The new item's `status` is `DRAFT`, its `approver_user_ids` list is
        empty, its `review_round` starts at 1, all twelve of its response accumulators
        start at 0, and its `stat_basis_applied` starts at `INSUFFICIENT_DATA` with both
        `p_value` and `discrimination_index` null."

        Design: Corner/entities/program_computed_counters_stay_zero_until_the_events_that_move_them
        """
        program = fx.active_program(api, **_minimal_program())
        item = fx.draft_item(api, program["id"], domain_code="D1", stem="Draft item")

        observed = validate_success(api.get_program(program["id"], fx.PSYCHOMETRICIAN), 200)

        assert observed["operational_item_count"] == 0
        assert observed["deficient_domain_codes"] == ["D1", "D2"]
        assert observed["blueprint_posture"] == "DEFICIENT"
        assert observed["verified_application_counter"] == 0
        assert observed["certificants_issued_count"] == 0
        assert fx.read_item(api, item["id"])["status"] == "DRAFT"
        assert fx.read_item(api, item["id"])["p_value"] is None
        ax.assert_blueprint_posture_agrees_with_counts(observed)
