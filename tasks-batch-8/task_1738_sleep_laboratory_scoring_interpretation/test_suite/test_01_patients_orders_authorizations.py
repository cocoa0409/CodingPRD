"""Patient intake, referral orders, insurance authorizations, and the
order-level cascades (decisions, supersession, no-shows, provider review)."""
from test_helpers import (
    ApiErrorId,
    DEFAULT_CLOCK_STAMP,
    TEST_USERS,
    assert_authorization,
    assert_patient,
    assert_referral_order,
    create_authorized_order,
    create_order,
    create_patient,
    create_patient_payload,
    decide_authorization,
    get_order,
    get_success_data,
    schedule_study,
    setup_study_in_progress,
    submit_authorization,
    validate_error,
    validate_paginated,
    validate_success,
)

SCHED = TEST_USERS["scheduler_headers"]
DIRECTOR = TEST_USERS["lab_director_headers"]


class TestPatientIntake:
    def test_create_patient_duplicate_mrn_rejected(self, api):
        """PRD: "The `mrn` must be unique across the laboratory; registering a
        duplicate is rejected with `ERR_DUPLICATE_MRN`."

        Design: Corner/entities/patient_create_duplicate_mrn_rejected
        """
        first = create_patient(mrn="MRN-DUP-01", full_name="Pat Dup")

        resp = api.create_patient(
            create_patient_payload(mrn="MRN-DUP-01", full_name="Pat Dup Two",
                                   date_of_birth="1971-01-01"),
            SCHED,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_MRN)

        reread = validate_success(api.get_patient(first["id"], SCHED))
        assert_patient(reread)
        assert reread["full_name"] == "Pat Dup", (
            "The originally registered patient record must be untouched")

    def test_get_patient_unknown_id_returns_not_found(self, api):
        """PRD: "The first identifier that does not correspond to an existing
        resource rejects the request with `ERR_NOT_FOUND` (HTTP 404), and no
        later validation stage runs."

        Design: Corner/entities/get_patient_unknown_id_returns_not_found
        """
        resp = api.get_patient("11111111-2222-4333-8444-555555555555", SCHED)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)


class TestAuthorizationSubmission:
    def test_auth_window_inverted_rejected(self, api):
        """PRD: "a `window_end` earlier than `window_start` is rejected with
        `ERR_AUTH_WINDOW_INVALID`."

        Design: Corner/validations/auth_window_inverted_rejected
        """
        patient = create_patient()
        order = create_order(patient["id"])

        resp = api.submit_authorization(
            order["id"],
            {
                "payer_name": "Aetna",
                "authorization_number": "AU-INV-1",
                "approved_nights": 1,
                "window_start": "2026-09-30",
                "window_end": "2026-07-01",
                "expected_referral_order_version": order["version"],
            },
            SCHED,
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_WINDOW_INVALID, 400)

    def test_occ_auth_submit_stale_version_rejected(self, api):
        """PRD: "Submitting an insurance authorization against a referral order
        requires `expected_referral_order_version`, carrying the client's last
        observed `version` of the order. If the order's current `version` has
        advanced beyond the supplied value — for example because another
        authorization was created in the interim, legitimately superseding the
        prior one — the request is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/complexity_layers/occ_auth_submit_stale_version_rejected
        """
        patient = create_patient()
        order = create_order(patient["id"])
        observed_version = order["version"]

        auth = submit_authorization(order, authorization_number="AU-SEQ-1")
        assert_authorization(auth)
        assert auth["status"] == "SUBMITTED"

        fresh = get_order(order["id"])
        assert fresh["version"] > observed_version, (
            "A successful authorization submit increments the order's version")

        resp = api.submit_authorization(
            order["id"],
            {
                "payer_name": "UHC",
                "authorization_number": "AU-SEQ-2",
                "approved_nights": 1,
                "window_start": "2026-07-01",
                "window_end": "2026-09-30",
                "expected_referral_order_version": observed_version,
            },
            SCHED,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

        _, meta = validate_paginated(
            api.list_authorizations(SCHED, {"order_id": order["id"]}))
        assert meta["total_count"] == 1, (
            "The stale second submission must not create an authorization")

    def test_auth_submit_on_pending_order_state_not_occ(self, api):
        """PRD: "A `Scheduler` submits an **InsuranceAuthorization** against an
        order whose `status` is `RECEIVED`, `AUTH_DENIED`, or `AUTHORIZED` —
        any other state is rejected with `ERR_ORDER_NOT_AUTHORIZABLE_STATE`."
        PRD: "Within the request evaluation pipeline (§2.9), the stale-version
        check runs after ownership checks and before the entity state
        preconditions." — here the supplied version IS current, so the state
        precondition is the check that fires.

        Design: Corner/validations/auth_submit_on_pending_order_state_not_occ
        """
        patient = create_patient()
        order = create_order(patient["id"])
        submit_authorization(order, authorization_number="AU-PEND-1")

        fresh = get_order(order["id"])
        assert fresh["status"] == "AUTH_IN_PROGRESS"

        resp = api.submit_authorization(
            order["id"],
            {
                "payer_name": "UHC",
                "authorization_number": "AU-PEND-2",
                "approved_nights": 1,
                "window_start": "2026-07-01",
                "window_end": "2026-09-30",
                "expected_referral_order_version": fresh["version"],
            },
            SCHED,
        )
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_AUTHORIZABLE_STATE, 409)


class TestAuthorizationDecisionCascade:
    def test_auth_approval_flips_order(self, api):
        """PRD: "An `outcome` of `APPROVED` stamps `decided_at` from the
        logical clock, transitions the authorization to `APPROVED`, and flips
        the order from `AUTH_IN_PROGRESS` to `AUTHORIZED`."

        Design: Difficulty/transitive_cascade/auth_approval_flips_order_depth2
        """
        patient = create_patient()
        order = create_order(patient["id"])
        auth = submit_authorization(order)
        assert get_order(order["id"])["status"] == "AUTH_IN_PROGRESS"

        decided = decide_authorization(auth["id"], "APPROVED")
        assert_authorization(decided)
        assert decided["status"] == "APPROVED"
        assert decided["decided_at"] == DEFAULT_CLOCK_STAMP, (
            "decided_at reads the logical clock, still at its startup default")

        flipped = get_order(order["id"])
        assert flipped["status"] == "AUTHORIZED", (
            "The approval mutation on the authorization flips the parent order")

        data, meta = validate_paginated(
            api.list_authorizations(SCHED, {"order_id": order["id"]}))
        assert meta["total_count"] == 1
        assert data[0]["status"] == "APPROVED"

    def test_auth_denial_flips_order(self, api):
        """PRD: "An `outcome` of `DENIED` stamps `decided_at`, transitions the
        authorization to `DENIED`, and flips the order to `AUTH_DENIED`."

        Design: Difficulty/transitive_cascade/auth_approval_flips_order_depth2
        """
        patient = create_patient()
        order = create_order(patient["id"])
        auth = submit_authorization(order)

        decided = decide_authorization(auth["id"], "DENIED")
        assert decided["status"] == "DENIED"
        assert decided["decided_at"] == DEFAULT_CLOCK_STAMP

        flipped = get_order(order["id"])
        assert flipped["status"] == "AUTH_DENIED"

    def test_decision_on_decided_auth_rejected(self, api):
        """PRD: "Recording the payer's decision requires the authorization to
        still be `SUBMITTED` (`ERR_AUTH_NOT_PENDING`)."

        Design: Corner/state_machines/decision_on_decided_auth_rejected
        """
        patient = create_patient()
        order = create_order(patient["id"])
        auth = submit_authorization(order)
        decide_authorization(auth["id"], "APPROVED")

        resp = api.decide_authorization(auth["id"], "DENIED", SCHED)
        validate_error(resp, ApiErrorId.ERR_AUTH_NOT_PENDING, 409)

        reread = get_success_data(api.get_authorization(auth["id"], SCHED))
        assert reread["status"] == "APPROVED", "The recorded decision stands"
        assert get_order(order["id"])["status"] == "AUTHORIZED"

    def test_auth_supersede_cascade_marks_prior_superseded(self, api):
        """PRD: "Submission creates the authorization in `SUBMITTED` status,
        moves the order to `AUTH_IN_PROGRESS`, increments the order's `version`
        by one, and transitions every prior `SUBMITTED` or `APPROVED`
        authorization of the same order to `SUPERSEDED`."
        PRD: "Re-authorizing an `AUTHORIZED` order therefore retires the live
        `APPROVED` authorization; studies already scheduled under it are
        grandfathered and unaffected."

        Design: Corner/complexity_layers/auth_supersede_cascade_marks_prior_superseded
        """
        patient = create_patient()
        booked = create_authorized_order(patient["id"], "HST")
        order, auth1 = booked["order"], booked["auth"]

        auth2 = submit_authorization(
            order, approved_nights=2, window_end="2026-12-31",
            authorization_number="AU-SUP-2")

        prior = get_success_data(api.get_authorization(auth1["id"], SCHED))
        assert prior["status"] == "SUPERSEDED", (
            "The live APPROVED authorization is retired by re-authorization")
        assert auth2["status"] == "SUBMITTED"
        assert get_order(order["id"])["status"] == "AUTH_IN_PROGRESS"


class TestNoShowProviderReviewCycle:
    def test_no_show_twice_triggers_provider_review_cycle(self, api):
        """PRD: "While the count stays below two, the order falls back from
        `SCHEDULED` to `AUTHORIZED` and may be rebooked. The moment the count
        reaches two, the order leaves `SCHEDULED` for `NEEDS_PROVIDER_REVIEW`,
        and further scheduling is blocked while it sits there."
        PRD: "A `Scheduler` resolves the review with an `action`: `REINSTATE`
        returns the order to `AUTHORIZED` and resets `no_show_count` to zero"

        Design: Corner/state_machines/no_show_twice_triggers_provider_review_cycle
        """
        patient = create_patient()
        booked = create_authorized_order(patient["id"], "HST",
                                         approved_nights=2)
        order = booked["order"]

        study1 = schedule_study(order["id"], patient["id"], "HST",
                                scheduled_date="2026-08-01")
        no_shown = get_success_data(api.no_show_study(study1["id"], SCHED))
        assert no_shown["status"] == "NO_SHOW"

        order = get_order(order["id"])
        assert order["status"] == "AUTHORIZED"
        assert order["no_show_count"] == 1

        study2 = schedule_study(order["id"], patient["id"], "HST",
                                scheduled_date="2026-08-02")
        assert study2["status"] == "SCHEDULED", (
            "With one no-show the order is rebookable")

        get_success_data(api.no_show_study(study2["id"], SCHED))
        order = get_order(order["id"])
        assert order["status"] == "NEEDS_PROVIDER_REVIEW"
        assert order["no_show_count"] == 2

        resolved = get_success_data(
            api.provider_review(order["id"], "REINSTATE", SCHED))
        assert_referral_order(resolved)
        assert resolved["status"] == "AUTHORIZED"
        assert resolved["no_show_count"] == 0

    def test_provider_review_on_authorized_order_rejected(self, api):
        """PRD: "Either action on an order not in `NEEDS_PROVIDER_REVIEW` is
        rejected with `ERR_ORDER_NOT_REVIEWABLE`."

        Design: Corner/validations/provider_review_on_authorized_order_rejected
        """
        patient = create_patient()
        booked = create_authorized_order(patient["id"], "HST")

        resp = api.provider_review(booked["order"]["id"], "REINSTATE", SCHED)
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_REVIEWABLE, 409)


class TestOrderCancellation:
    def test_order_cancel_blocked_by_in_progress_study(self, api):
        """PRD: "From `RECEIVED`, `AUTH_IN_PROGRESS`, `AUTHORIZED`, or
        `SCHEDULED`, cancellation is blocked while a linked study is
        `IN_PROGRESS` (`ERR_ORDER_HAS_ACTIVE_STUDY`)"

        Design: Corner/validations/order_cancel_blocked_by_in_progress_study
        """
        ws = setup_study_in_progress(study_type="HST")
        assert ws["study"]["status"] == "IN_PROGRESS"
        assert get_order(ws["order"]["id"])["status"] == "SCHEDULED"

        resp = api.cancel_referral_order(ws["order"]["id"], SCHED)
        validate_error(resp, ApiErrorId.ERR_ORDER_HAS_ACTIVE_STUDY, 409)

        assert get_order(ws["order"]["id"])["status"] == "SCHEDULED", (
            "The blocked cancellation leaves the order in place")
