"""Easement drafting, landowner registration, and recordation gates (PRD §3.1)."""
from test_helpers import (
    ApiErrorId,
    SMALL_MATRIX,
    accept_baseline,
    assert_easement,
    create_baseline,
    create_draft_easement,
    create_easement_payload,
    create_initial_landowner,
    create_recorded_easement,
    get_easement,
    is_valid_uuid,
    make_landowner_headers,
    submit_baseline,
    validate_error,
    validate_success,
)


class TestEasementCreation:
    def test_create_easement_applies_defaults_and_initial_state(self, api, trust_admin_headers):
        """PRD §3.1: "The `monitoring_interval_months` may be supplied to override
        the default of 12; any whole value from 6 to 36 months is acceptable."
        PRD §3.1: "The easement is born in `DRAFT` with `posture` `GOOD_STANDING`
        and `version` 1; `recorded_on`, `last_monitoring_completed_on`, and
        `next_monitoring_due_on` are null, and `open_violation_count` and
        `amendment_count` read zero."
        PRD §2.4: "`id` is a server-minted UUID with no type prefix."

        Design: Corner/entities/create_easement_applies_defaults_and_initial_state
        """
        payload = create_easement_payload(
            easement_name="E-DEF", parcel_acreage=320, permitted_use_matrix=SMALL_MATRIX
        )
        assert "monitoring_interval_months" not in payload
        data = validate_success(api.create_easement(payload, trust_admin_headers), 201)
        assert_easement(data)
        assert is_valid_uuid(data["id"])
        assert data["status"] == "DRAFT"
        assert data["posture"] == "GOOD_STANDING"
        assert data["monitoring_interval_months"] == 12, "default interval must be 12"
        assert data["version"] == 1
        assert data["recorded_on"] is None
        assert data["last_monitoring_completed_on"] is None
        assert data["next_monitoring_due_on"] is None
        assert data["open_violation_count"] == 0
        assert data["amendment_count"] == 0

        fetched = validate_success(api.get_easement(data["id"], trust_admin_headers), 200)
        assert fetched["status"] == "DRAFT"
        assert fetched["posture"] == "GOOD_STANDING"

    def test_create_easement_missing_required_field_returns_400(self, api, trust_admin_headers):
        """PRD §3.1: "A malformed payload — a missing required field, a value of
        the wrong type, an out-of-range interval, an empty matrix, or non-positive
        acreage — is rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/entities/create_easement_missing_required_field_returns_400
        """
        payload = {
            "easement_name": "E-BAD",
            "grantor_name": "G",
            "permitted_use_matrix": {"AGRICULTURE": "PERMITTED"},
        }
        resp = api.create_easement(payload, trust_admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestLandownerRegistration:
    def test_initial_landowner_defaults_active(self, api, trust_admin_headers):
        """PRD §3.1: "The initial landowner is created `ACTIVE` with `acquired_on`
        set to the clock date and `predecessor_landowner_id` null; the easement's
        `current_landowner_id` is set to the new record and the easement's
        `version` advances by one."
        PRD §2.10: "At startup the clock reads exactly 2026-08-01T00:00:00Z, and
        before any explicit set it continues to read that default; it never
        consults the wall clock."

        Design: Corner/entities/initial_landowner_defaults_active
        """
        easement = create_draft_easement(
            name="E-LO", parcel_acreage=100, matrix={"AGRICULTURE": "PERMITTED"}
        )
        landowner = validate_success(
            api.create_landowner(
                {
                    "easement_id": easement["id"],
                    "owner_name": "Owner A",
                    "contact_email": "a@x.com",
                },
                trust_admin_headers,
            ),
            201,
        )
        assert landowner["status"] == "ACTIVE"
        assert landowner["predecessor_landowner_id"] is None
        assert landowner["acquired_on"] == "2026-08-01", "acquired_on is the clock date"

        easement_after = get_easement(easement["id"])
        assert easement_after["current_landowner_id"] == landowner["id"]
        assert easement_after["version"] == easement["version"] + 1


class TestRecordationGates:
    def test_record_rejected_while_baseline_not_accepted(self, api, trust_admin_headers):
        """PRD §3.1: "The easement's baseline report must be `ACCEPTED`, else
        `ERR_BASELINE_NOT_ACCEPTED`."

        Design: Difficulty/cross_entity_state_dependency/easement_record_requires_accepted_baseline
        """
        easement = create_draft_easement(
            name="E-CE1", parcel_acreage=500, matrix=SMALL_MATRIX
        )
        create_initial_landowner(easement["id"])
        create_baseline(easement["id"], prepared_by="staff-prep-1", photo_point_count=5)

        resp = api.record_easement(easement["id"], trust_admin_headers)
        validate_error(resp, ApiErrorId.ERR_BASELINE_NOT_ACCEPTED)
        assert get_easement(easement["id"])["status"] == "DRAFT"

    def test_record_succeeds_after_baseline_accepted(self, api, trust_admin_headers):
        """PRD §3.1: "On success the easement becomes `RECORDED`, `recorded_on` is
        set to the clock date, `next_monitoring_due_on` is computed from the
        recordation date plus `monitoring_interval_months` months under the
        month-end clamping rule of §3.2, posture is computed (`GOOD_STANDING`),
        and `version` advances by one."

        Design: Difficulty/cross_entity_state_dependency/easement_record_requires_accepted_baseline
        """
        easement = create_draft_easement(
            name="E-CE1B", parcel_acreage=500, matrix=SMALL_MATRIX,
            monitoring_interval_months=12,
        )
        create_initial_landowner(easement["id"])
        baseline = create_baseline(easement["id"], prepared_by="staff-prep-1",
                                   photo_point_count=5)
        submit_baseline(baseline["id"])
        accept_baseline(baseline["id"], acceptor_user_id="board-1")

        data = validate_success(api.record_easement(easement["id"], trust_admin_headers), 200)
        assert data["status"] == "RECORDED"
        assert data["recorded_on"] == "2026-08-01", "recorded_on is the default clock date"
        assert data["next_monitoring_due_on"] == "2027-08-01", "recorded 2026-08-01 + 12 months"
        assert data["posture"] == "GOOD_STANDING"

    def test_record_without_landowner_rejected(self, api, trust_admin_headers):
        """PRD §3.1: "And `current_landowner_id` must reference an `ACTIVE`
        landowner, else `ERR_OPEN_OBLIGATIONS_EXIST`."

        Design: Corner/errors/record_without_landowner_rejected
        """
        easement = create_draft_easement(
            name="E-NL", parcel_acreage=100, matrix={"AGRICULTURE": "PERMITTED"}
        )
        baseline = create_baseline(easement["id"], prepared_by="staff-prep-1",
                                   photo_point_count=4)
        submit_baseline(baseline["id"])
        accept_baseline(baseline["id"], acceptor_user_id="board-1")

        resp = api.record_easement(easement["id"], trust_admin_headers)
        validate_error(resp, ApiErrorId.ERR_OPEN_OBLIGATIONS_EXIST)
        assert get_easement(easement["id"])["status"] == "DRAFT"

    def test_child_create_on_draft_easement_rejected(self, api, coordinator_headers):
        """PRD §3.1: "Once `RECORDED`, the easement admits child operational
        records — monitoring visits, violations, amendments, use authorizations,
        succession notices, and appraisals; attempting any of those creates
        against a `DRAFT` easement is rejected with `ERR_EASEMENT_NOT_RECORDED`."

        Design: Corner/errors/child_create_on_draft_easement_rejected
        """
        easement = create_draft_easement(
            name="E-NR", parcel_acreage=100, matrix={"AGRICULTURE": "PERMITTED"}
        )
        create_initial_landowner(easement["id"])
        resp = api.create_monitoring_visit(
            {
                "easement_id": easement["id"],
                "monitor_user_id": "mon-1",
                "window_start_on": "2026-09-01",
                "window_end_on": "2026-09-10",
            },
            coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_EASEMENT_NOT_RECORDED)

    def test_landowner_cannot_record_easement(self, api):
        """PRD §2.1: "A request whose role is not permitted for the target
        endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §4: "POST `/stewardship/easements/{easementId}/record` ... TrustAdmin".

        Design: Corner/validations/landowner_cannot_record_easement
        """
        easement = create_draft_easement(
            name="E-RB", parcel_acreage=100, matrix={"AGRICULTURE": "PERMITTED"}
        )
        landowner = create_initial_landowner(easement["id"])
        resp = api.record_easement(
            easement["id"], make_landowner_headers(landowner["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        assert get_easement(easement["id"])["status"] == "DRAFT"

    def test_record_response_immediately_shows_recorded_state(self, api, trust_admin_headers):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."
        PRD §3.1: "On success the easement becomes `RECORDED`, `recorded_on` is
        set to the clock date, `next_monitoring_due_on` is computed from the
        recordation date plus `monitoring_interval_months` months under the
        month-end clamping rule of §3.2, posture is computed (`GOOD_STANDING`),
        and `version` advances by one."

        Design: Corner/consistency_model/immediate_consistency_mutation_visible_in_response
        """
        ctx = create_recorded_easement(
            name="E-IC", parcel_acreage=100, matrix={"AGRICULTURE": "PERMITTED"},
            monitoring_interval_months=12,
        )
        recorded = ctx["easement"]
        # The record call's own response already carries the mutated resource.
        assert recorded["status"] == "RECORDED"
        assert recorded["recorded_on"] == "2026-08-01"
        assert recorded["next_monitoring_due_on"] == "2027-08-01"

        # And the raw record response uses the fixed success envelope.
        ctx2_easement = create_draft_easement(
            name="E-IC2", parcel_acreage=100, matrix={"AGRICULTURE": "PERMITTED"},
            monitoring_interval_months=12,
        )
        create_initial_landowner(ctx2_easement["id"])
        baseline = create_baseline(ctx2_easement["id"], prepared_by="staff-prep-1",
                                   photo_point_count=4)
        submit_baseline(baseline["id"])
        accept_baseline(baseline["id"], acceptor_user_id="board-1")
        resp = api.record_easement(ctx2_easement["id"], trust_admin_headers)
        data = validate_success(resp, 200)
        body = resp.json()
        assert body["response_type"] == "object"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert data["status"] == "RECORDED"
        assert data["recorded_on"] == "2026-08-01"
        assert data["next_monitoring_due_on"] == "2027-08-01"
