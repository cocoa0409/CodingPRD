"""Program configuration: tracks, providers, memberships, consult intake guards."""
from datetime import datetime, timezone

from test_helpers import (
    ApiErrorId, TEST_USERS,
    assert_clarification_message, assert_consult_request, assert_panel_membership,
    assert_specialty_track, create_membership, create_provider, create_specialist,
    create_track, make_provider_headers, make_specialist_headers, set_clock,
    setup_assigned_consult, validate_error, validate_paginated, validate_success,
)

COORD = TEST_USERS["coordinator_headers"]


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


class TestProgramConfiguration:
    def test_create_specialty_track_persists_config(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data field."
        PRD §2.5: "All time-dependent behavior in the system — SLA deadlines, expiry,
        availability coverage, period attribution — is evaluated against a
        server-maintained logical clock, never against wall-clock time."

        Design: Corner/entities/create_specialty_track_persists_config
        """
        set_clock("2026-06-01T00:00:00Z")
        res = api.create_specialty_track({
            "specialty_code": "CARDIOLOGY",
            "response_time_target_hours": 48,
            "urgent_target_hours": 12,
            "base_response_fee_cents": 10000,
            "conversion_response_fee_cents": 8000,
            "clarification_fee_cents": 2500,
            "late_penalty_cents": 3000,
            "monthly_billing_cap_cents": 1000000,
        }, COORD)
        track = validate_success(res, 201)
        assert_specialty_track(track)
        # Every submitted config field echoes back on the created resource.
        assert track["specialty_code"] == "CARDIOLOGY"
        assert track["response_time_target_hours"] == 48
        assert track["urgent_target_hours"] == 12
        assert track["base_response_fee_cents"] == 10000
        assert track["conversion_response_fee_cents"] == 8000
        assert track["clarification_fee_cents"] == 2500
        assert track["late_penalty_cents"] == 3000
        assert track["monthly_billing_cap_cents"] == 1000000
        # created_at is stamped from the logical clock set to 2026-06-01T00:00:00Z.
        assert _parse(track["created_at"]) == datetime(2026, 6, 1, tzinfo=timezone.utc), (
            f"created_at must come from the logical clock, got {track['created_at']!r}"
        )

    def test_create_consult_missing_required_field_returns_invalid_request(self, api):
        """PRD §2.8: "Request-body schema validation follows — missing required
        fields, wrong types, invalid enum members, and string-length violations
        such as a too-short question or an out-of-range score all yield
        `ERR_INVALID_REQUEST`."
        PRD §3.3: "Consults can be listed with filters on `referring_provider_id`,
        `specialty_track_id`, `assigned_specialist_id`, `assigned_membership_id`, or
        `status`."

        Design: Corner/entities/create_consult_missing_required_field_returns_invalid_request
        """
        set_clock("2026-06-01T00:00:00Z")
        track = create_track("CARDIOLOGY")
        provider = create_provider(npi="1000001001")
        res = api.create_consult_request({
            "patient_ref": "PAT-E1",
            "specialty_track_id": track["id"],
            "icd10_primary": "I10",
            "urgency": "ROUTINE",
        }, make_provider_headers(provider["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)
        # Nothing is persisted: the provider-filtered list is empty.
        data, _meta = validate_paginated(api.list_consult_requests(
            COORD, params={"referring_provider_id": provider["id"]}
        ))
        assert data == [], f"no consult may be persisted, got {data}"

    def test_membership_created_with_computed_defaults(self, api):
        """PRD §3.1: "A new membership starts in `GOOD_STANDING` with a
        `quality_score_bps` of 8500 and every counter zeroed: `reviews_count`,
        `reviews_score_sum`, `responded_count`, `on_time_count`, `rebuke_count`,
        `expired_count`, and `open_consult_count` all begin at zero, and
        `provisional_balance_cents` and `posted_balance_cents` begin at zero as well."
        PRD §3.1: "A `ProgramCoordinator` creates a **panel membership** by supplying
        `specialist_id` and `specialty_track_id`, optionally with `is_accepting`
        (which defaults to `true`)."

        Design: Corner/entities/membership_created_with_computed_defaults
        """
        set_clock("2026-06-01T00:00:00Z")
        track = create_track("CARDIOLOGY")
        specialist = create_specialist(npi="2000001001")
        res = api.create_panel_membership(
            {"specialist_id": specialist["id"], "specialty_track_id": track["id"]}, COORD
        )
        membership = validate_success(res, 201)
        assert_panel_membership(membership)
        assert membership["standing"] == "GOOD_STANDING"
        assert membership["quality_score_bps"] == 8500
        assert membership["reviews_count"] == 0
        assert membership["reviews_score_sum"] == 0
        assert membership["responded_count"] == 0
        assert membership["on_time_count"] == 0
        assert membership["rebuke_count"] == 0
        assert membership["expired_count"] == 0
        assert membership["open_consult_count"] == 0
        assert membership["provisional_balance_cents"] == 0
        assert membership["posted_balance_cents"] == 0
        assert membership["is_accepting"] is True

    def test_clarification_message_is_append_only_without_version(self, api):
        """PRD §2.4: "Two resources are append-only audit records and deliberately
        carry less: a `ClarificationMessage` and a `RoutingDecision` each expose only
        `id` and `created_at`. Neither has `updated_at` nor `version`, because neither
        is ever modified after it is written."
        PRD §3.4: "A successful request appends a `ClarificationMessage` whose
        `author_role` is `SPECIALIST` and whose `sequence_no` is one greater than the
        count of prior messages on the consult"

        Design: Corner/entities/clarification_message_is_append_only_without_version
        """
        scenario = setup_assigned_consult(patient_ref="PAT-E2")
        consult = scenario["consult"]
        specialist = scenario["specialist"]
        res = api.create_clarification(
            consult["id"],
            {"body": "Which comorbidities should I assume beyond the listed asthma?"},
            make_specialist_headers(specialist["id"]),
        )
        message = validate_success(res, 201)
        assert_clarification_message(message)  # asserts NO version / updated_at keys
        assert message["sequence_no"] == 1
        assert message["author_role"] == "SPECIALIST"
        assert message["body"] == "Which comorbidities should I assume beyond the listed asthma?"

    def test_consult_on_empty_pool_initial_state_queued(self, api):
        """PRD §3.2: "When the pool is empty at creation, the consult instead lands in
        `QUEUED` with a decision row whose `candidate_count` is zero and whose
        `selected_membership_id` is null."
        PRD §3.3: "its `billing_status` begins at `UNBILLABLE`"

        Design: Corner/entities/consult_on_empty_pool_initial_state_queued
        """
        set_clock("2026-06-01T00:00:00Z")
        track = create_track("NEUROLOGY")  # no panel memberships at all
        provider = create_provider(npi="1000001003")
        res = api.create_consult_request({
            "patient_ref": "PAT-E3",
            "specialty_track_id": track["id"],
            "question_text": "New absence seizures in teenager; asks about ethosuximide start and EEG urgency.",
            "icd10_primary": "G40",
            "urgency": "ROUTINE",
        }, make_provider_headers(provider["id"]))
        consult = validate_success(res, 201)
        assert_consult_request(consult)
        assert consult["status"] == "QUEUED"
        assert consult["assigned_specialist_id"] is None
        assert consult["assigned_membership_id"] is None
        assert consult["billing_status"] == "UNBILLABLE"
        decisions, meta = validate_paginated(
            api.list_routing_decisions(consult["id"], COORD)
        )
        assert len(decisions) == 1, f"exactly one routing decision, got {len(decisions)}"
        assert decisions[0]["outcome"] == "QUEUED"
        assert decisions[0]["candidate_count"] == 0
        assert decisions[0]["selected_membership_id"] is None

    def test_duplicate_membership_rejected(self, api):
        """PRD §3.1: "The pairing must be unique — the system records a
        `unique_membership` marker over the specialist-and-track pair, and a duplicate
        enrollment is rejected with `ERR_DUPLICATE_MEMBERSHIP`."

        Design: Corner/validations/duplicate_membership_rejected
        """
        set_clock("2026-06-01T00:00:00Z")
        track = create_track("CARDIOLOGY")
        specialist = create_specialist(npi="2000004013")
        create_membership(specialist["id"], track["id"])
        res = api.create_panel_membership(
            {"specialist_id": specialist["id"], "specialty_track_id": track["id"]}, COORD
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_MEMBERSHIP, expected_status=409)

    def test_deactivated_provider_cannot_submit_consult(self, api):
        """PRD §3.3: "The submitting provider must be `ACTIVE`; a submission from a
        `DEACTIVATED` provider is rejected with `ERR_PROVIDER_INACTIVE`."

        Design: Corner/validations/deactivated_provider_cannot_submit_consult
        """
        set_clock("2026-06-01T00:00:00Z")
        track = create_track("CARDIOLOGY")
        provider = create_provider(npi="1000004006", full_name="Dr. Retired Provider",
                                   status="DEACTIVATED")
        res = api.create_consult_request({
            "patient_ref": "PAT-V5",
            "specialty_track_id": track["id"],
            "question_text": "Wants specialist input on lipid management after statin-associated muscle symptoms.",
            "icd10_primary": "E78",
            "urgency": "ROUTINE",
        }, make_provider_headers(provider["id"]))
        validate_error(res, ApiErrorId.ERR_PROVIDER_INACTIVE, expected_status=409)
        # No consult persisted for the deactivated provider.
        data, _meta = validate_paginated(api.list_consult_requests(
            COORD, params={"referring_provider_id": provider["id"]}
        ))
        assert data == []

    def test_duplicate_open_consult_rejected(self, api):
        """PRD §3.3: "At most one non-terminal consult may exist for a given patient
        within a given track: if a consult for the same `patient_ref` and
        `specialty_track_id` pair exists in any status other than `CLOSED`, `EXPIRED`,
        or `CANCELLED`, creation is rejected with `ERR_DUPLICATE_OPEN_CONSULT`."

        Design: Corner/validations/duplicate_open_consult_rejected
        """
        scenario = setup_assigned_consult(
            patient_ref="PAT-DUP", provider_npi="1000004010",
            specialist_npi="2000004012",
            consult_overrides={
                "question_text": "Initial question about antiplatelet choice after TIA with aspirin allergy on file.",
                "icd10_primary": "G45",
            },
        )
        res = api.create_consult_request({
            "patient_ref": "PAT-DUP",
            "specialty_track_id": scenario["track"]["id"],
            "question_text": "Duplicate submission attempt for the same patient and specialty while first is open.",
            "icd10_primary": "G45",
            "urgency": "ROUTINE",
        }, make_provider_headers(scenario["provider"]["id"]))
        validate_error(res, ApiErrorId.ERR_DUPLICATE_OPEN_CONSULT, expected_status=409)

    def test_short_question_returns_invalid_request(self, api):
        """PRD §3.3: the provider submits "a `question_text` of at least 20 characters
        holding the structured clinical question".
        PRD §2.8: "Request-body schema validation follows — missing required fields,
        wrong types, invalid enum members, and string-length violations such as a
        too-short question or an out-of-range score all yield `ERR_INVALID_REQUEST`."

        Design: Corner/validations/short_question_returns_invalid_request
        """
        set_clock("2026-06-01T00:00:00Z")
        track = create_track("CARDIOLOGY")
        provider = create_provider(npi="1000004012")
        res = api.create_consult_request({
            "patient_ref": "PAT-V10",
            "specialty_track_id": track["id"],
            "question_text": "too short",  # 9 characters < 20
            "icd10_primary": "I10",
            "urgency": "ROUTINE",
        }, make_provider_headers(provider["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)
