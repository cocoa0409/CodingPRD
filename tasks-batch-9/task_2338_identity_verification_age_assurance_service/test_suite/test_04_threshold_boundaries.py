"""Threshold and window boundaries: the authenticity floor, the liveness band,
the session lapse instant, the selector ladder, review capacity and retention
precedence.

Each test sits one unit either side of a declared boundary so that an
off-by-one reading of the contract is visible.
"""
from datetime import datetime

from test_helpers import (
    FORGED_CAPTURE,
    MANUAL_REVIEWER_USER_ID,
    TEST_USERS,
    ApiErrorId,
    assign_case_payload,
    create_document_capture_payload,
    create_liveness_check_payload,
    create_method_profile_payload,
    finalize_attempt,
    list_session_cases,
    list_session_templates,
    make_client_integrator_headers,
    make_review_manager_headers,
    open_attempt,
    open_session,
    read_attempt,
    read_client,
    read_session,
    record_estimation_result,
    set_clock,
    setup_age_gated_session,
    setup_client_with_published_policy,
    setup_session,
    submit_document_capture,
    submit_liveness_check,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN_HEADERS = TEST_USERS["platform_admin_headers"]

CLEAN_PASSPORT = {
    "document_type": "PASSPORT",
    "required_feature_count": 10,
    "passed_feature_count": 10,
    "tamper_signal_count": 0,
    "mrz_checksum_valid": True,
}

HALF_FEATURED_PERMIT = {
    "document_type": "RESIDENCE_PERMIT",
    "required_feature_count": 10,
    "passed_feature_count": 5,
    "mrz_checksum_valid": True,
}


def assert_same_instant(actual: str, expected: str) -> None:
    """Compare two server timestamps as instants, ignoring fractional form."""
    def parse(value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    assert actual is not None, f"expected an instant equal to {expected}, got null"
    assert parse(actual) == parse(expected), f"expected instant {expected}, got {actual}"


def _session_with_two_permit_attempts() -> dict:
    """One session, one profile, two DOCUMENT_SCAN attempts on the same method."""
    env = setup_session(
        method_codes=("DOCUMENT_SCAN",),
        policy_overrides={"min_assurance_score": 40},
        session_overrides={
            "requested_assurance_tier": "BASIC",
            "external_subject_ref": "subj-floor",
        },
    )
    client_id = env["client"]["id"]
    profile_id = env["profiles"]["DOCUMENT_SCAN"]["id"]
    env["first"] = open_attempt(env["session"]["id"], client_id, profile_id)
    env["second"] = open_attempt(env["session"]["id"], client_id, profile_id)
    return env


class TestDocumentSuspectFloorBoundary:
    """Exactly 5000 basis points is SUSPECT; one tamper penalty below is FORGED."""

    def test_score_at_the_suspect_floor_and_one_penalty_below_it(self, api):
        """PRD §3.4: "A score exactly equal to the floor is `AUTHENTIC`; a score of exactly
        5000 is `SUSPECT` and one basis point lower is `FORGED`."
        PRD §3.4: "Third, `tamper_penalty_bps` is 450 basis points per tamper signal, scaled
        by that tier multiplier: 450 multiplied by `tamper_signal_count`, multiplied by
        `tamper_tier_multiplier_bps`, divided by ten thousand, truncated toward zero."

        Design: Corner/calculations/suspect_floor_boundary_separates_suspect_from_forged_assessments
        """
        env = _session_with_two_permit_attempts()
        client_id = env["client"]["id"]

        at_floor = validate_success(
            api.create_document_capture(
                env["first"]["id"],
                create_document_capture_payload(tamper_signal_count=0, **HALF_FEATURED_PERMIT),
                make_client_integrator_headers(client_id),
            ),
            201,
        )
        assert at_floor["base_score_bps"] == 5000
        assert at_floor["tamper_tier_multiplier_bps"] == 20000
        assert at_floor["tamper_penalty_bps"] == 0
        assert at_floor["authenticity_score_bps"] == 5000
        assert at_floor["assessment"] == "SUSPECT", (
            f"a score of exactly 5000 bps is SUSPECT, got {at_floor['assessment']}"
        )

        below_floor = validate_success(
            api.create_document_capture(
                env["second"]["id"],
                create_document_capture_payload(tamper_signal_count=1, **HALF_FEATURED_PERMIT),
                make_client_integrator_headers(client_id),
            ),
            201,
        )
        assert below_floor["tamper_penalty_bps"] == 900, (
            f"450 * 1 * 20000 / 10000 is 900 bps, got {below_floor['tamper_penalty_bps']}"
        )
        assert below_floor["authenticity_score_bps"] == 4100
        assert below_floor["assessment"] == "FORGED", (
            f"a score below 5000 bps is FORGED, got {below_floor['assessment']}"
        )

    def test_contributions_either_side_of_the_floor_truncate_and_sum(self):
        """PRD §3.4: "The capture's `authenticity_score_bps` becomes the attempt's
        `evidence_quality_bps` verbatim, and the attempt's `contribution_points` is the
        resolved profile's `assurance_weight` multiplied by that quality, divided by ten
        thousand, truncated toward zero."
        PRD §3.3: "Its `retry_index` is the number of attempts that already exist on the same
        session with the same `method_code`, so the first document scan of a session has index
        0 and a second has index 1; this figure matters later for liveness tuning."

        Design: Corner/calculations/suspect_floor_boundary_separates_suspect_from_forged_assessments
        """
        env = _session_with_two_permit_attempts()
        client_id = env["client"]["id"]
        submit_document_capture(
            env["first"]["id"], client_id, tamper_signal_count=0, **HALF_FEATURED_PERMIT
        )
        submit_document_capture(
            env["second"]["id"], client_id, tamper_signal_count=1, **HALF_FEATURED_PERMIT
        )

        suspect = read_attempt(env["first"]["id"], client_id)
        forged = read_attempt(env["second"]["id"], client_id)

        assert suspect["evidence_quality_bps"] == 5000
        assert suspect["contribution_points"] == 22, (
            f"45 * 5000 / 10000 truncates to 22 points, got {suspect['contribution_points']}"
        )
        assert forged["evidence_quality_bps"] == 4100
        assert forged["contribution_points"] == 18, (
            f"45 * 4100 / 10000 truncates to 18 points, got {forged['contribution_points']}"
        )
        assert forged["retry_index"] == 1

        session = read_session(env["session"]["id"], client_id)
        assert session["assurance_score_provisional"] == 40, (
            "both scored attempts still contribute, got "
            f"{session['assurance_score_provisional']}"
        )


class TestLivenessBandBoundary:
    """One basis point below the inconclusive band is an outright FAIL."""

    def test_pad_score_one_point_below_the_inconclusive_band_fails(self, api):
        """PRD §3.5: "The `decision` follows: `PASS` when `pad_score_bps` is at or above
        `effective_threshold_bps`, `INCONCLUSIVE` when `pad_score_bps` is at least 300 basis
        points below that threshold but still short of it, and `FAIL` otherwise."
        PRD §3.5: "Start from the pinned policy's `pad_threshold_bps`. Add a risk bump:
        nothing for a `LOW`-risk session, 300 basis points for `MEDIUM`, 800 basis points for
        `HIGH`. Add 200 basis points for each prior attempt of the same method on this
        session, that is, 200 multiplied by the attempt's `retry_index`. Then subtract a
        relief of 250 basis points when `capture_modality` is `ACTIVE`, and nothing when it is
        `PASSIVE`."
        PRD §3.5: "A `FAIL` records 0, and consequently `contribution_points` of 0 as well."

        Design: Corner/calculations/pad_decision_fails_one_basis_point_below_the_inconclusive_band
        """
        env = setup_session(
            method_codes=("BIOMETRIC_COMPARISON",),
            policy_overrides={"min_assurance_score": 40},
            session_overrides={
                "requested_assurance_tier": "ENHANCED",
                "declared_transaction_value_cents": 25000,
                "biometric_consent": True,
                "external_subject_ref": "subj-pad",
            },
        )
        client_id = env["client"]["id"]
        assert env["session"]["risk_score"] == 70
        assert env["session"]["risk_level"] == "HIGH"

        attempt = open_attempt(
            env["session"]["id"], client_id, env["profiles"]["BIOMETRIC_COMPARISON"]["id"]
        )
        response = api.create_liveness_check(
            attempt["id"],
            create_liveness_check_payload(
                capture_modality="ACTIVE", pad_score_bps=7749, match_score_bps=9500
            ),
            make_client_integrator_headers(client_id),
        )
        check = validate_success(response, 201)

        assert check["effective_threshold_bps"] == 8050, (
            "7500 plus an 800 bps high-risk bump less the 250 bps active relief is 8050, got "
            f"{check['effective_threshold_bps']}"
        )
        assert check["retry_index"] == 0
        assert check["decision"] == "FAIL", (
            "7749 bps is one basis point below the inconclusive band, got "
            f"{check['decision']}"
        )

        scored = read_attempt(attempt["id"], client_id)
        assert scored["state"] == "SCORED"
        assert scored["evidence_quality_bps"] == 0
        assert scored["contribution_points"] == 0
        assert scored["match_score_bps"] == 9500

        _, meta = validate_paginated(api.list_biometric_templates(env["session"]["id"], ADMIN_HEADERS))
        assert meta["total_count"] == 0, "a failed liveness check produces no template"
        assert read_client(client_id)["stored_template_count"] == 0
        assert read_session(env["session"]["id"], client_id)["assurance_score_provisional"] == 0


class TestSessionLapseBoundary:
    """The expiry instant itself is inside the window; a second later is not."""

    def test_capture_at_the_expiry_instant_is_admitted_and_a_second_later_lapses(self, api):
        """PRD §3.2: "A session is treated as lapsed by every mutating endpoint as soon as the
        clock is strictly past `expires_at`, and such requests are rejected with
        `ERR_SESSION_EXPIRED` — even before the operations sweep has materialised the lapse as
        an `EXPIRED` identity state. A clock instant exactly equal to `expires_at` is still
        inside the window."
        PRD §3.2: "`expires_at` is set to the session's `created_at` plus sixty minutes on the
        logical clock."

        Design: Corner/calculations/session_lapse_boundary_admits_the_instant_and_rejects_one_second_later
        """
        env = setup_session(
            method_codes=("DOCUMENT_SCAN",),
            policy_overrides={"min_assurance_score": 40},
            session_overrides={
                "requested_assurance_tier": "BASIC",
                "external_subject_ref": "subj-lapse",
            },
        )
        client_id = env["client"]["id"]
        session_id = env["session"]["id"]
        profile_id = env["profiles"]["DOCUMENT_SCAN"]["id"]
        assert_same_instant(env["session"]["expires_at"], "2026-08-01T01:00:00Z")

        first = open_attempt(session_id, client_id, profile_id)
        second = open_attempt(session_id, client_id, profile_id)

        set_clock("2026-08-01T01:00:00Z")
        admitted = validate_success(
            api.create_document_capture(
                first["id"],
                create_document_capture_payload(**CLEAN_PASSPORT),
                make_client_integrator_headers(client_id),
            ),
            201,
        )
        assert admitted["authenticity_score_bps"] == 10000

        set_clock("2026-08-01T01:00:01Z")
        lapsed = api.create_document_capture(
            second["id"],
            create_document_capture_payload(**CLEAN_PASSPORT),
            make_client_integrator_headers(client_id),
        )
        validate_error(lapsed, ApiErrorId.ERR_SESSION_EXPIRED)

        scored = read_attempt(first["id"], client_id)
        assert scored["state"] == "SCORED"
        assert scored["contribution_points"] == 45

        untouched = read_attempt(second["id"], client_id)
        assert untouched["state"] == "AWAITING_EVIDENCE"
        assert untouched["evidence_quality_bps"] is None
        _, meta = validate_paginated(
            api.list_document_captures(second["id"], make_client_integrator_headers(client_id))
        )
        assert meta["total_count"] == 0, "the lapsed request stored no capture"

        session = read_session(session_id, client_id)
        assert session["identity_state"] == "IN_PROGRESS", (
            "the lapse is not materialised until the sweep runs, got "
            f"{session['identity_state']}"
        )
        assert_same_instant(session["expires_at"], "2026-08-01T01:00:00Z")
        assert session["assurance_score_provisional"] == 45


class TestSelectorLadder:
    """Equal assurance weights are separated by vendor cost, not by identifier."""

    def test_server_selection_breaks_the_weight_tie_on_the_cheaper_vendor(self, api):
        """PRD §3.3: "Candidates are ranked by `assurance_weight` descending, then by
        `cost_cents` ascending, then by `created_at` ascending; identifiers are never used as a
        ranking or tie-break key, and `created_at` ascending is the final arbiter."
        PRD §3.3: "The top-ranked candidate is used and `selection_mode` is recorded as
        `SERVER_SELECTED`."

        Design: Corner/calculations/ladder_selection_breaks_the_weight_tie_on_lower_vendor_cost
        """
        env = setup_client_with_published_policy(
            method_codes=("DOCUMENT_SCAN",),
            policy_overrides={"min_assurance_score": 40},
        )
        client_id = env["client"]["id"]
        expensive = env["profiles"]["DOCUMENT_SCAN"]
        cheaper = validate_success(
            api.create_method_profile(
                create_method_profile_payload(
                    method_code="DOCUMENT_SCAN",
                    vendor_code="docv2",
                    assurance_weight=45,
                    cost_cents=80,
                ),
                ADMIN_HEADERS,
            ),
            201,
        )
        assert expensive["assurance_weight"] == cheaper["assurance_weight"] == 45
        assert expensive["cost_cents"] == 120 and cheaper["cost_cents"] == 80

        session = open_session(
            client_id, external_subject_ref="subj-tie", requested_assurance_tier="BASIC"
        )
        assert session["risk_level"] == "LOW"

        response = api.create_method_attempt(
            session["id"], {}, make_client_integrator_headers(client_id)
        )
        attempt = validate_success(response, 201)

        assert attempt["method_profile_id"] == cheaper["id"], (
            "the tie on assurance weight is broken by the lower cost_cents"
        )
        assert attempt["selection_mode"] == "SERVER_SELECTED"
        assert attempt["method_code"] == "DOCUMENT_SCAN"
        assert attempt["state"] == "AWAITING_EVIDENCE"
        assert attempt["retry_index"] == 0


class TestReviewCapacityBoundary:
    """A one-credit pool admits one assignment and refuses the second."""

    def test_second_assignment_without_an_available_credit_is_refused(self, api):
        """PRD §3.8: "It requires the case to be `QUEUED` and requires the owning client's
        `available_review_credits` to be at least 1, otherwise
        `ERR_REVIEW_CAPACITY_EXHAUSTED`."
        PRD §3.8: "On success the case moves `QUEUED → ASSIGNED`, `assigned_by_user_id`
        records the manager's `X-User-ID`, and one credit is reserved — meaning
        `reserved_review_credits` rises by one and `available_review_credits` falls by one,
        the pool invariant of §2.8 holding throughout."
        PRD §3.8: "Queued cases hold no credit at all, which is deliberate: escalation itself
        can never be blocked by exhausted capacity, only its assignment can."

        Design: Corner/calculations/review_credit_capacity_exhaustion_blocks_the_second_assignment
        """
        env = setup_client_with_published_policy(
            method_codes=("DOCUMENT_SCAN",),
            client_overrides={"granted_review_credits": 1},
            policy_overrides={"min_assurance_score": 60},
        )
        client_id = env["client"]["id"]
        profile_id = env["profiles"]["DOCUMENT_SCAN"]["id"]

        escalated = []
        for subject_ref in ("subj-cap-a", "subj-cap-b"):
            session = open_session(
                client_id, external_subject_ref=subject_ref, requested_assurance_tier="BASIC"
            )
            attempt = open_attempt(session["id"], client_id, profile_id)
            submit_document_capture(attempt["id"], client_id, **FORGED_CAPTURE)
            finalize_attempt(attempt["id"], client_id)
            cases, _ = list_session_cases(session["id"])
            assert len(cases) == 1
            escalated.append({"session_id": session["id"], "case": cases[0]})

        first_case = escalated[0]["case"]
        second_case = escalated[1]["case"]
        assigned = validate_success(
            api.assign_manual_review_case(
                first_case["id"],
                assign_case_payload(MANUAL_REVIEWER_USER_ID),
                make_review_manager_headers(),
            ),
            200,
        )
        assert assigned["state"] == "ASSIGNED"
        assert assigned["assigned_reviewer_user_id"] == MANUAL_REVIEWER_USER_ID

        refused = api.assign_manual_review_case(
            second_case["id"],
            assign_case_payload(MANUAL_REVIEWER_USER_ID),
            make_review_manager_headers(),
        )
        validate_error(refused, ApiErrorId.ERR_REVIEW_CAPACITY_EXHAUSTED)

        remaining, _ = list_session_cases(escalated[1]["session_id"])
        still_queued = remaining[0]
        assert still_queued["state"] == "QUEUED"
        assert still_queued["assigned_reviewer_user_id"] is None
        assert still_queued["assigned_by_user_id"] is None

        client = read_client(client_id)
        assert client["reserved_review_credits"] == 1
        assert client["available_review_credits"] == 0
        assert client["consumed_review_count"] == 0

        for entry in escalated:
            assert read_session(entry["session_id"], client_id)["identity_state"] == "MANUAL_REVIEW"


class TestRetentionPrecedence:
    """Minor protection outranks the configured ninety-day retention."""

    def test_minor_protection_deletes_the_template_despite_retain_ninety_days(self, api):
        """PRD §3.10: "First, if the session's `resolved_age_band` is one of the minor bands
        `U13`, `B13_15` or `B16_17`, the template is deleted immediately with
        `deletion_reason` of `MINOR_PROTECTION`. This rule deliberately outranks everything
        below it, so a client configured for `RETAIN_90_DAYS` still loses a minor's template
        at once."
        PRD §3.8: "When `age_state` is `FAILED`, the session moves `IN_PROGRESS → REJECTED`:
        `assurance_score_final` is written, `disposition_reason` is set to `AGE_GATE_FAILED`,
        `completed_at` is set to the clock, the retention schedule of §3.10 is applied to every
        template of the session still in `STORED`, and an audit event of type
        `SESSION_TERMINAL` is appended."
        PRD §3.7: "`buffer_months` is `mae_months_snapshot` multiplied by the pinned policy's
        `age_buffer_multiplier_bps`, divided by ten thousand, rounded *up* to a whole month."

        Design: Corner/calculations/minor_protection_outranks_the_retain_ninety_days_configuration
        """
        env = setup_age_gated_session(
            required_min_age_years=18,
            age_buffer_multiplier_bps=15000,
            estimation_mae_months=12,
            method_codes=("BIOMETRIC_COMPARISON",),
            client_overrides={"biometric_retention_mode": "RETAIN_90_DAYS"},
            policy_overrides={"min_assurance_score": 20},
            session_overrides={
                "requested_assurance_tier": "BASIC",
                "biometric_consent": True,
                "external_subject_ref": "subj-minor",
            },
        )
        client_id = env["client"]["id"]
        session_id = env["session"]["id"]

        attempt = open_attempt(
            session_id, client_id, env["profiles"]["BIOMETRIC_COMPARISON"]["id"]
        )
        check = submit_liveness_check(
            attempt["id"],
            client_id,
            capture_modality="ACTIVE",
            pad_score_bps=9000,
            match_score_bps=9200,
        )
        assert check["effective_threshold_bps"] == 7250
        assert check["decision"] == "PASS"
        scored = read_attempt(attempt["id"], client_id)
        assert scored["evidence_quality_bps"] == 9120, (
            "the blend of 6000 bps match and 4000 bps liveness weight is 9120, got "
            f"{scored['evidence_quality_bps']}"
        )
        assert scored["contribution_points"] == 31
        assert finalize_attempt(attempt["id"], client_id)["state"] == "ACCEPTED"

        stored, stored_meta = list_session_templates(session_id, state="STORED")
        assert stored_meta["total_count"] == 1
        template_id = stored[0]["id"]

        age_result = record_estimation_result(
            session_id, client_id, env["profiles"]["AGE_ESTIMATION"]["id"], 230
        )
        assert age_result["buffer_months"] == 18, (
            f"12 months of error scaled by 15000 bps rounds up to 18, got "
            f"{age_result['buffer_months']}"
        )
        assert age_result["effective_age_months"] == 212
        assert age_result["resolved_band"] == "B16_17"
        assert age_result["documented_accuracy_bps"] == 9100
        assert age_result["decision"] == "FAILED"

        response = api.complete_session(session_id, make_client_integrator_headers(client_id))
        completed = validate_success(response, 200)

        assert completed["identity_state"] == "REJECTED"
        assert completed["disposition_reason"] == "AGE_GATE_FAILED"
        assert completed["age_state"] == "FAILED"
        assert completed["resolved_age_band"] == "B16_17"
        assert completed["assurance_score_final"] == 31
        assert completed["assurance_score_provisional"] == 31

        templates, meta = list_session_templates(session_id)
        assert meta["total_count"] == 1
        template = templates[0]
        assert template["id"] == template_id
        assert template["state"] == "DELETED"
        assert template["deletion_reason"] == "MINOR_PROTECTION", (
            "the minor band outranks the client's ninety-day retention, got "
            f"{template['deletion_reason']}"
        )
        assert template["retention_expires_at"] is None, (
            "an immediate deletion schedules no expiry"
        )
        assert_same_instant(template["deleted_at"], "2026-08-01T00:00:00Z")
        assert read_client(client_id)["stored_template_count"] == 0
