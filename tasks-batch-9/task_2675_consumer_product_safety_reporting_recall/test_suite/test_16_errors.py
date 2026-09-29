"""The error surface: per-entity state codes on replay and the fixed envelope."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_error_envelope,
    assert_field_values,
    assert_integer_cents,
    assert_pagination_meta,
    assert_unchanged,
    assert_unit_ledger_conserved,
)
from test_helpers.test_users import (
    AUDITOR_HEADERS,
    COUNSEL_HEADERS,
    INTAKE_HEADERS,
    OFFICER_HEADERS,
)

INTAKE_CLOCK = "2026-03-01T00:00:00Z"

# The claim that credits ten of the hundred units in commerce, leaving the
# 30.00 percent participation goal unmet.
TEN_UNIT_CLAIM = {
    "consumer_ref": "C-310",
    "remedy_type": "REFUND",
    "quantity": 10,
    "unit_price_cents": 8999,
    "shipping_cents_per_unit": 700,
}

# A body that fails the shape check twice over: an undeclared intake channel and
# an instant that names no real calendar date.
MALFORMED_INCIDENT = {
    "report_channel": "FAX_MACHINE",
    "incident_date": "2026-13-45T00:00:00Z",
    "narrative": "Unparseable submission.",
}


def _fully_advanced_docket(api):
    """A docket driven until every one of six rows has left its opening state."""
    env = fx.monitoring_recall_env(api)
    fx.acknowledge_notification(api, env["notification_id"], units_on_shelf_reported=0)
    visit = fx.create_audit_visit(api, env["notification_id"])
    env["visit"] = fx.complete_audit_visit(
        api, visit["id"], verdict="PASS", shelf_units_found=0
    )
    env["visit_id"] = visit["id"]
    env["notification"] = fx.verify_notification(api, env["notification_id"])

    claim = fx.fulfilled_claim(api, env["recall_id"], **TEN_UNIT_CLAIM)
    env["claim"] = claim
    env["claim_id"] = claim["id"]

    recall = fx.get_recall(api, env["recall_id"])
    progress_report = fx.accepted_progress_report(
        api,
        env["recall_id"],
        period_start=recall["stop_sale_effective_at"],
        period_end="2026-04-12T00:00:00Z",
        effectiveness_basis="UNITS_BASIS",
    )
    env["progress_report"] = progress_report
    env["progress_report_id"] = progress_report["id"]

    case = fx.create_penalty_case(api, env["report_id"], violation_count=4)
    fx.make_offer(api, case["id"], 5000000, "AGENCY", case["version"])
    env["case"] = fx.resolve_offer(
        api, case["id"], "ACCEPTED", note="Consent agreement executed."
    )
    env["case_id"] = case["id"]
    env["recall"] = fx.get_recall(api, env["recall_id"])
    return env


def _replay_every_advanced_verb(api, env):
    """Re-fire six advanced verbs and return the responses in the same order."""
    return [
        api.submit_plan(env["recall_id"], headers=OFFICER_HEADERS),
        api.complete_audit_visit(
            env["visit_id"], f.complete_visit_payload(), headers=AUDITOR_HEADERS
        ),
        api.release_consumer_notice(env["notice_id"], headers=OFFICER_HEADERS),
        api.approve_claim(env["claim_id"], headers=OFFICER_HEADERS),
        api.submit_progress_report(
            env["progress_report_id"], headers=OFFICER_HEADERS
        ),
        api.resolve_offer(
            env["case_id"],
            f.offer_resolution_payload(resolution="WITHDRAWN"),
            headers=COUNSEL_HEADERS,
        ),
    ]


REPLAY_ERRORS = (
    "ERR_RECALL_PLAN_STATE_INVALID",
    "ERR_VISIT_STATE_INVALID",
    "ERR_NOTICE_STATE_INVALID",
    "ERR_CLAIM_STATE_INVALID",
    "ERR_PROGRESS_REPORT_STATE_INVALID",
    "ERR_PENALTY_CASE_STATE_INVALID",
)


class TestReplayedVerbsNameTheirOwnRow:
    """Six advanced rows, six distinct per-entity state codes."""

    def test_each_replayed_verb_returns_the_state_error_of_its_own_entity(self, api):
        """Six replays across six entities answer six distinct 409 codes.

        The contract states: "Every action operation in this system is a state
        transition and none of them are idempotent: re-firing the same trigger on a
        row that has already advanced returns that entity's state error at step 9
        rather than succeeding silently." Each verb names its own code: "A recall
        whose `plan_status` is not `DRAFT` cannot be submitted and draws
        `ERR_RECALL_PLAN_STATE_INVALID`."; "It requires the visit to be
        `SCHEDULED`, otherwise `ERR_VISIT_STATE_INVALID`"; "The notice must be
        `SCHEDULED`, otherwise `ERR_NOTICE_STATE_INVALID`."; "A claim in any other
        status draws `ERR_CLAIM_STATE_INVALID`."; "A report not in `DRAFT` draws
        `ERR_PROGRESS_REPORT_STATE_INVALID`."; and "Both require the case to be in
        `OFFER_MADE` and additionally require `current_offer_by` to be `AGENCY`; a
        respondent counter is not the office's to withdraw or accept, and either
        failure draws `ERR_PENALTY_CASE_STATE_INVALID`."

        Design: Corner/errors/replaying_an_advanced_verb_returns_that_entity_own_state_error
        """
        env = _fully_advanced_docket(api)
        assert_field_values(env["recall"], plan_status="MONITORING")
        assert_field_values(env["visit"], status="COMPLETED")
        assert_field_values(env["notice"], status="RELEASED")
        assert_field_values(env["claim"], status="FULFILLED")
        assert_field_values(env["progress_report"], status="ACCEPTED")
        assert_field_values(env["case"], status="AGREED")

        responses = _replay_every_advanced_verb(api, env)

        seen = []
        for response, expected_error_id in zip(responses, REPLAY_ERRORS):
            validate_error(response, expected_error_id, 409)
            assert_error_envelope(response.json(), expected_error_id)
            seen.append(response.json()["data"]["error_id"])

        assert len(set(seen)) == len(REPLAY_ERRORS), (
            f"the per-entity state codes collapsed into one another: {seen}"
        )

    def test_a_refused_replay_leaves_every_row_and_the_unit_ledger_untouched(
        self, api
    ):
        """No refused replay advances a version or moves the recall's ledger.

        The contract states: "Evaluation stops at the first failure and no later
        rule is consulted." The ledger it must not touch is conserved: "On a
        recall, the sum of `units_corrected` and `units_outstanding` always equals
        `units_in_commerce`, which is immutable after the recall is created."  And
        the settlement bound by the accepted offer is final: "`ACCEPTED` advances
        the case `OFFER_MADE -> AGREED`, which is terminal, and binds the consent
        agreement."

        Design: Corner/errors/replaying_an_advanced_verb_returns_that_entity_own_state_error
        """
        env = _fully_advanced_docket(api)
        assert_field_values(env["recall"], units_corrected=10, units_outstanding=90)
        assert_field_values(
            env["case"],
            consent_agreement_total_cents=4250000,
            cooperation_credit_tier="TIER_2",
            cooperation_credit_cents=750000,
            cooperation_bonus_applied=False,
        )
        assert_integer_cents(env["case"], "consent_agreement_total_cents")

        for response, expected_error_id in zip(
            _replay_every_advanced_verb(api, env), REPLAY_ERRORS
        ):
            validate_error(response, expected_error_id, 409)

        recall_after = fx.get_recall(api, env["recall_id"])
        assert_field_values(recall_after, units_corrected=10, units_outstanding=90)
        assert_unit_ledger_conserved(recall_after)
        assert_unchanged(
            env["recall"], recall_after, "plan_status", "version", "updated_at"
        )

        assert_unchanged(
            env["visit"],
            fx.get_audit_visit(api, env["visit_id"]),
            "status",
            "verdict",
            "version",
        )
        assert_unchanged(
            env["notice"], fx.get_notice(api, env["notice_id"]), "status", "version"
        )
        assert_unchanged(
            env["claim"],
            fx.get_claim(api, env["claim_id"]),
            "status",
            "fulfilled_at",
            "version",
        )
        assert_unchanged(
            env["progress_report"],
            fx.get_progress_report(api, env["progress_report_id"]),
            "status",
            "version",
        )
        assert_unchanged(
            env["case"],
            fx.get_penalty_case(api, env["case_id"]),
            "status",
            "consent_agreement_total_cents",
            "current_offer_round",
            "version",
        )


def _assert_error_data_carries_only_the_declared_pair(body):
    """The error `data` object carries exactly error_id and message."""
    assert set(body["data"].keys()) == {"error_id", "message"}, body["data"]
    assert isinstance(body["data"]["message"], str) and body["data"]["message"], body


class TestErrorEnvelopeIsFixedAndWritesNothing:
    """Two structurally different failures, one declared envelope."""

    def test_an_unresolvable_identifier_answers_the_declared_error_envelope(self, api):
        """A 404 on a missing incident still carries meta and the error pair.

        The contract states: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`." And of the payload itself:
        "The `error_id` is a unique, machine-readable string that identifies the
        specific error." The code belongs to the entity that owns the failing
        segment: "the not-found error belongs to the entity that owns the failing
        segment, drawn from `ERR_PRODUCT_MODEL_NOT_FOUND`,
        `ERR_INCIDENT_NOT_FOUND`, ... each answered with HTTP 404."

        Design: Corner/errors/every_error_response_carries_the_declared_envelope_and_writes_nothing
        """
        fx.set_clock(api, INTAKE_CLOCK)
        model = fx.create_product_model(api)

        response = api.get_incident(NON_EXISTENT_UUID, headers=INTAKE_HEADERS)
        validate_error(response, "ERR_INCIDENT_NOT_FOUND", 404)

        body = response.json()
        assert_error_envelope(body, "ERR_INCIDENT_NOT_FOUND")
        _assert_error_data_carries_only_the_declared_pair(body)

        assert_unchanged(
            model, fx.get_product_model(api, model["id"]), "version", "updated_at"
        )

    def test_a_malformed_body_answers_the_same_envelope_and_writes_no_row(self, api):
        """A rejected intake body leaves the incident collection empty.

        The contract states: "It requires every non-optional field to be present
        and non-null; every enum-valued field to carry a declared member; every
        integer field to be an integer inside its declared range; every money field
        to be a non-negative integer of cents; every decimal field to respect its
        declared scale; the `remedy_options` array to be non-empty with unique
        members; every timestamp to be a valid ISO 8601 UTC instant" — and a body
        that fails it is rejected: "**Request shape** — the body conforms to the
        endpoint's input contract, else `ERR_INVALID_REQUEST`." Every such failure
        wears the same envelope: "All error API responses (4xx status codes) follow
        this standard envelope format".

        Design: Corner/errors/every_error_response_carries_the_declared_envelope_and_writes_nothing
        """
        fx.set_clock(api, INTAKE_CLOCK)
        model = fx.create_product_model(api)

        response = api.create_incident(
            f.incident_payload(model["id"], **MALFORMED_INCIDENT),
            headers=INTAKE_HEADERS,
        )
        validate_error(response, "ERR_INVALID_REQUEST", 400)

        body = response.json()
        assert_error_envelope(body, "ERR_INVALID_REQUEST")
        _assert_error_data_carries_only_the_declared_pair(body)

        rows, meta = validate_paginated(
            api.list_incidents(
                {"product_model_id": model["id"]}, headers=INTAKE_HEADERS
            )
        )
        assert rows == [], f"a rejected create wrote a row anyway: {rows}"
        assert_pagination_meta(meta, total_count=0, has_more=False)
        assert_unchanged(
            model, fx.get_product_model(api, model["id"]), "version", "updated_at"
        )
