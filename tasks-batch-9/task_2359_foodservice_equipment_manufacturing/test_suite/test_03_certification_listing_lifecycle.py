"""Certification listing lifecycle: submission, the conditions loop, grants and expiry."""

from test_helpers import (
    COMPLIANCE_ENGINEER_USER_ID,
    LISTING_REVIEWER_USER_ID,
    PASSING_TEST_RUNS,
    ApiErrorId,
    approve_configuration,
    certification_listing_payload,
    create_chain_account,
    create_chain_configuration,
    create_equipment_model,
    file_certification_listing,
    grant_certification_listing,
    make_headers,
    read_certification_listing,
    read_chain_configuration,
    read_equipment_model,
    record_agency_decision,
    release_configuration,
    set_clock,
    setup_listed_model,
    setup_passed_validation,
    sign_off_branding,
    submit_certification_listing,
    submit_configuration,
    validate_error,
    validate_paginated,
    validate_success,
)


def _model_with_draft_listing(**listing_kwargs):
    set_clock()
    model = create_equipment_model(supported_controls_packages=["STANDARD_DIAL"])
    listing = file_certification_listing(model["id"], **listing_kwargs)
    return model, listing


def _listing_in_conditions(laps):
    """Drive one AGENCY_GAMMA listing through the given conditions laps."""
    model, listing = _model_with_draft_listing()
    submit_certification_listing(listing["id"])
    for lap, note in enumerate(laps, start=1):
        record_agency_decision(listing["id"], "ACKNOWLEDGE_REVIEW")
        record_agency_decision(listing["id"], "CONDITIONS", conditions_note=note)
        if lap < len(laps):
            submit_certification_listing(listing["id"])
    return model, listing


class TestConditionsRevisionLoop:
    def test_a_fourth_conditions_lap_cannot_be_re_submitted(
        self, api, compliance_engineer
    ):
        """Three conditions laps exhaust the revision budget and the fourth submission is refused.

        PRD §3.1: "The loop is bounded — a re-submission is permitted only while
        `revision` is still below three, so an application may make three round trips
        through conditions and no more; the fourth attempt is rejected with
        `ERR_LISTING_REVISION_LIMIT`."

        Design: Difficulty/non_linear_state_machine/listing_conditions_revision_loop_reenters_submitted_and_caps_at_three
        """
        model, listing = _listing_in_conditions(
            [
                "lap 1: drain slope",
                "lap 2: strain relief",
                "lap 3: bonding lug",
                "lap 4: gasket material",
            ]
        )
        before = read_certification_listing(listing["id"])
        assert before["revision"] == 3, (
            f"three completed conditions laps leave revision at 3, got {before['revision']}"
        )
        assert before["status"] == "CONDITIONS_REQUESTED", (
            f"the listing is waiting on the chain again, got {before['status']}"
        )

        refused = api.submit_certification_listing(listing["id"], {}, compliance_engineer)
        validate_error(refused, ApiErrorId.ERR_LISTING_REVISION_LIMIT.value)

        after = read_certification_listing(listing["id"])
        assert after["status"] == "CONDITIONS_REQUESTED", (
            f"the refused submission leaves the listing where it was, got {after['status']}"
        )
        assert after["revision"] == 3, (
            f"a refused re-submission must not increment revision, got {after['revision']}"
        )
        assert after["conditions_note"] == "lap 4: gasket material", (
            f"the last agency note survives the refusal, got {after['conditions_note']}"
        )
        assert read_equipment_model(model["id"])["certification_posture"] == "UNLISTED", (
            "a listing that never reached LISTED covers nothing, so the model stays UNLISTED"
        )

    def test_only_the_conditions_re_entry_increments_the_revision_counter(self):
        """The DRAFT submission leaves revision at 0 while each re-entry adds one.

        PRD §3.1: "Note the asymmetry between the two submission paths: the `DRAFT →
        SUBMITTED` path does not touch `revision`, while the `CONDITIONS_REQUESTED →
        SUBMITTED` path always increments it."

        Design: Difficulty/non_linear_state_machine/listing_conditions_revision_loop_reenters_submitted_and_caps_at_three
        """
        model, listing = _model_with_draft_listing()

        first = submit_certification_listing(listing["id"])
        assert first["status"] == "SUBMITTED", (
            f"the first submission reaches SUBMITTED, got {first['status']}"
        )
        assert first["revision"] == 0, (
            f"the DRAFT path does not touch revision, got {first['revision']}"
        )

        for expected_revision, note in enumerate(
            ["lap 1: drain slope", "lap 2: strain relief", "lap 3: bonding lug"], start=1
        ):
            record_agency_decision(listing["id"], "ACKNOWLEDGE_REVIEW")
            conditioned = record_agency_decision(
                listing["id"], "CONDITIONS", conditions_note=note
            )
            assert conditioned["status"] == "CONDITIONS_REQUESTED", (
                f"CONDITIONS reopens the application, got {conditioned['status']}"
            )
            assert conditioned["conditions_note"] == note, (
                f"the agency note is stored on the listing, got {conditioned['conditions_note']}"
            )
            resubmitted = submit_certification_listing(listing["id"])
            assert resubmitted["status"] == "SUBMITTED", (
                f"the re-submission revisits SUBMITTED, got {resubmitted['status']}"
            )
            assert resubmitted["revision"] == expected_revision, (
                f"lap {expected_revision} must leave revision at {expected_revision}, "
                f"got {resubmitted['revision']}"
            )
            assert resubmitted["submitted_by_user_id"] == COMPLIANCE_ENGINEER_USER_ID, (
                "every re-submission re-records the acting user, got "
                f"{resubmitted['submitted_by_user_id']}"
            )
        assert read_equipment_model(model["id"])["certification_posture"] == "UNLISTED", (
            "no grant has happened, so the model is still UNLISTED"
        )


def _approved_configuration_near_expiry():
    """A configuration approved one second before its listing's 365-day term runs out."""
    set_clock()
    listed = setup_listed_model(
        supported_controls_packages=["STANDARD_DIAL", "TOUCH_PRO"]
    )
    account = create_chain_account()
    config = create_chain_configuration(
        account["id"],
        listed["model"]["id"],
        account["version"],
        option_codes=["SPLIT_TANK"],
        controls_package="TOUCH_PRO",
        branding_kit="LOGO_BADGE",
    )
    setup_passed_validation(
        config["id"],
        PASSING_TEST_RUNS,
        target_throughput_units_per_hour=60.0,
        hold_temp_target_c=175.0,
    )
    submit_configuration(config["id"])
    set_clock("2027-07-31T23:59:59Z")
    approved = approve_configuration(config["id"])
    sign_off_branding(config["id"], account["id"])
    return {
        "model": listed["model"],
        "listing": listed["listing"],
        "config": approved,
        "account": account,
    }


class TestStrictListingExpiry:
    def test_a_clock_reading_equal_to_expires_on_blocks_release(
        self, api, application_engineer
    ):
        """At exactly 2027-08-01T00:00:00Z the model reads UNLISTED and release is refused.

        PRD §2.5: "a certification listing covers its scopes only while the clock is
        strictly earlier than `expires_on`, and a technician certification counts only
        while the clock is strictly earlier than its `expires_on`. In both cases, a clock
        reading exactly equal to `expires_on` no longer counts."

        Design: Difficulty/boundary_precision_check/listing_expiry_is_strict_so_clock_equal_to_expires_on_blocks_release
        """
        state = _approved_configuration_near_expiry()
        assert state["listing"]["expires_on"].startswith("2027-08-01T00:00:00"), (
            "a grant recorded at 2026-08-01 expires one 365-day term later, got "
            f"{state['listing']['expires_on']}"
        )
        assert state["config"]["status"] == "ENG_APPROVED", (
            f"one second inside the term the approval succeeds, got {state['config']['status']}"
        )
        assert state["config"]["pinned_model_version"] == state["model"]["version"], (
            "approval pins the model version it reviewed, got "
            f"{state['config']['pinned_model_version']} against a model version of "
            f"{state['model']['version']}"
        )

        set_clock("2027-08-01T00:00:00Z")

        refused = api.release_chain_configuration(
            state["config"]["id"], {}, application_engineer
        )
        validate_error(refused, ApiErrorId.ERR_MODEL_NOT_LISTED.value)

        listing = read_certification_listing(state["listing"]["id"])
        assert listing["status"] == "LISTED", (
            "the listing row itself is untouched by the clock, only its coverage lapses, "
            f"got {listing['status']}"
        )
        model = read_equipment_model(state["model"]["id"])
        assert model["certification_posture"] == "UNLISTED", (
            "with no listing whose expires_on is still ahead of the clock the posture "
            f"drops to UNLISTED, got {model['certification_posture']}"
        )
        assert model["covered_scopes"] == [], (
            f"covered_scopes is emptied at the boundary, got {model['covered_scopes']}"
        )
        config = read_chain_configuration(state["config"]["id"])
        assert config["status"] == "ENG_APPROVED", (
            f"the refused release leaves the configuration approved, got {config['status']}"
        )
        assert config["firm_unit_price_cents"] is None, (
            f"no firm price is stamped by a refused release, got {config['firm_unit_price_cents']}"
        )

    def test_one_second_inside_the_term_the_same_release_succeeds(self):
        """The strict comparison still admits 2027-07-31T23:59:59Z, so the release goes through.

        PRD §3.1: "`covered_scopes` is the union of the `scopes` arrays of the model's
        certification listings that are currently `LISTED` and whose `expires_on` is
        strictly later than the logical clock, de-duplicated and sorted in that same
        fixed order of `SANITATION`, `GAS`, `ELECTRICAL`."

        Design: Difficulty/boundary_precision_check/listing_expiry_is_strict_so_clock_equal_to_expires_on_blocks_release
        """
        state = _approved_configuration_near_expiry()
        model = read_equipment_model(state["model"]["id"])
        assert model["certification_posture"] == "LISTED", (
            "one second before expiry the coverage still counts, got "
            f"{model['certification_posture']}"
        )
        assert model["covered_scopes"] == ["SANITATION", "ELECTRICAL"], (
            "the AGENCY_GAMMA grant covers both required scopes in the fixed order, got "
            f"{model['covered_scopes']}"
        )

        released = release_configuration(state["config"]["id"])

        assert released["status"] == "RELEASED", (
            f"a release inside the listing term succeeds, got {released['status']}"
        )
        assert released["firm_unit_price_cents"] is not None, (
            "the successful release stamps a firm price, got "
            f"{released['firm_unit_price_cents']}"
        )


class TestListingStateMachine:
    def test_listing_submission_moves_draft_to_submitted_and_stamps_the_submitter(
        self, api, compliance_engineer
    ):
        """The first submission reaches SUBMITTED, records the submitter and leaves revision at 0.

        PRD §3.1: "The submission records the acting `X-User-ID` in
        `submitted_by_user_id`, which is the value the two-person control in §2.10 later
        reads."

        Design: Corner/state_machines/listing_submission_moves_draft_to_submitted_and_stamps_the_submitter
        """
        model, listing = _model_with_draft_listing()

        submitted = validate_success(
            api.submit_certification_listing(listing["id"], {}, compliance_engineer)
        )

        assert submitted["status"] == "SUBMITTED", (
            f"DRAFT moves to SUBMITTED, got {submitted['status']}"
        )
        assert submitted["revision"] == 0, (
            f"the revision counter only moves on the conditions re-entry, got {submitted['revision']}"
        )
        assert submitted["submitted_by_user_id"] == COMPLIANCE_ENGINEER_USER_ID, (
            f"the acting user is recorded, got {submitted['submitted_by_user_id']}"
        )
        assert read_equipment_model(model["id"])["certification_posture"] == "UNLISTED", (
            "a submitted application contributes no coverage, so the model is UNLISTED"
        )

    def test_second_listing_for_same_model_and_agency_cannot_be_submitted_while_first_is_listed(
        self, api, compliance_engineer
    ):
        """A duplicate AGENCY_GAMMA row may be created but not submitted.

        PRD §3.1: "no other listing of the same model with the same `agency_code` may be
        in `SUBMITTED`, `UNDER_REVIEW`, `CONDITIONS_REQUESTED` or `LISTED` — a competing
        live application is rejected with `ERR_DUPLICATE_LISTING_APPLICATION`."

        Design: Corner/state_machines/second_listing_for_same_model_and_agency_cannot_be_submitted_while_first_is_listed
        """
        model, first = _model_with_draft_listing()
        grant_certification_listing(first["id"])

        second = validate_success(
            api.create_certification_listing(
                certification_listing_payload(
                    model["id"], "AGENCY_GAMMA", ["SANITATION"]
                ),
                compliance_engineer,
            ),
            201,
        )
        assert second["status"] == "DRAFT", (
            f"the duplicate row is created freely in DRAFT, got {second['status']}"
        )

        refused = api.submit_certification_listing(second["id"], {}, compliance_engineer)
        validate_error(refused, ApiErrorId.ERR_DUPLICATE_LISTING_APPLICATION.value)

        blocked = read_certification_listing(second["id"])
        assert blocked["status"] == "DRAFT", (
            f"the blocked row stays in DRAFT, got {blocked['status']}"
        )
        assert blocked["submitted_by_user_id"] is None, (
            "a refused submission records no submitter, got "
            f"{blocked['submitted_by_user_id']}"
        )

    def test_listing_grant_stamps_listed_on_now_and_expires_on_one_listing_term_later(
        self,
    ):
        """A grant recorded after a clock advance dates from the advanced clock.

        PRD §3.1: "`GRANT` takes it `UNDER_REVIEW → LISTED`, stamps `listed_on` with the
        current logical clock and `expires_on` with `listed_on` plus a full listing term
        of 365 days, and re-derives the model's posture and covered scopes."

        Design: Corner/state_machines/listing_grant_stamps_listed_on_now_and_expires_on_one_listing_term_later
        """
        model, listing = _model_with_draft_listing()
        submit_certification_listing(listing["id"])
        record_agency_decision(listing["id"], "ACKNOWLEDGE_REVIEW")
        set_clock("2026-09-15T00:00:00Z")

        granted = record_agency_decision(listing["id"], "GRANT")

        assert granted["status"] == "LISTED", (
            f"GRANT moves UNDER_REVIEW to LISTED, got {granted['status']}"
        )
        assert granted["listed_on"].startswith("2026-09-15T00:00:00"), (
            "listed_on is stamped from the logical clock at grant time, not the row's "
            f"creation time, got {granted['listed_on']}"
        )
        assert granted["expires_on"].startswith("2027-09-15T00:00:00"), (
            "expires_on is exactly 365 days after listed_on, got "
            f"{granted['expires_on']}"
        )
        assert granted["decided_by_user_id"] == LISTING_REVIEWER_USER_ID, (
            f"the deciding reviewer is recorded, got {granted['decided_by_user_id']}"
        )
        assert read_equipment_model(model["id"])["certification_posture"] == "LISTED", (
            "the grant re-derives the model's posture to LISTED"
        )

    def test_grant_on_a_submitted_listing_that_was_never_acknowledged_is_rejected(
        self, api, listing_reviewer
    ):
        """GRANT is only defined out of UNDER_REVIEW, so the acknowledgement cannot be skipped.

        PRD §3.1: "A disposition asked for from a state that does not admit it —
        acknowledging a `DRAFT`, granting a listing that is not `UNDER_REVIEW`,
        suspending one that is not `LISTED`, reinstating one that is not `SUSPENDED` — is
        rejected with `ERR_LISTING_STATE_INVALID`."

        Design: Corner/state_machines/grant_on_a_submitted_listing_that_was_never_acknowledged_is_rejected
        """
        model, listing = _model_with_draft_listing()
        submit_certification_listing(listing["id"])

        refused = api.record_agency_decision(
            listing["id"], {"decision": "GRANT"}, listing_reviewer
        )
        validate_error(refused, ApiErrorId.ERR_LISTING_STATE_INVALID.value)

        row = read_certification_listing(listing["id"])
        assert row["status"] == "SUBMITTED", (
            f"the refused grant leaves the listing SUBMITTED, got {row['status']}"
        )
        assert row["listed_on"] is None, (
            f"no listing date is stamped by a refused grant, got {row['listed_on']}"
        )
        assert read_equipment_model(model["id"])["certification_posture"] == "UNLISTED", (
            "the model gains no coverage from a refused grant"
        )

    def test_rejected_listing_is_terminal_and_admits_no_further_submission(
        self, api, compliance_engineer
    ):
        """REJECTED admits no re-submission, unlike CONDITIONS_REQUESTED.

        PRD §3.1: "`REJECT` takes it `UNDER_REVIEW → REJECTED`, which is terminal."

        Design: Corner/state_machines/rejected_listing_is_terminal_and_admits_no_further_submission
        """
        model, listing = _model_with_draft_listing()
        submit_certification_listing(listing["id"])
        record_agency_decision(listing["id"], "ACKNOWLEDGE_REVIEW")
        rejected = record_agency_decision(listing["id"], "REJECT")
        assert rejected["status"] == "REJECTED", (
            f"REJECT moves UNDER_REVIEW to REJECTED, got {rejected['status']}"
        )

        refused = api.submit_certification_listing(listing["id"], {}, compliance_engineer)
        validate_error(refused, ApiErrorId.ERR_LISTING_STATE_INVALID.value)

        row = read_certification_listing(listing["id"])
        assert row["status"] == "REJECTED", (
            f"the terminal state holds, got {row['status']}"
        )
        assert row["revision"] == 0, (
            f"a refused submission must not increment revision, got {row['revision']}"
        )

    def test_acknowledge_review_replayed_on_an_under_review_listing_is_rejected(
        self, api
    ):
        """The agency-decision endpoint is not idempotent, and the first decider is kept.

        PRD §3.1: "`ACKNOWLEDGE_REVIEW` takes the application `SUBMITTED → UNDER_REVIEW`."

        Design: Corner/state_machines/acknowledge_review_replayed_on_an_under_review_listing_is_rejected
        """
        model, listing = _model_with_draft_listing()
        submit_certification_listing(listing["id"])
        record_agency_decision(listing["id"], "ACKNOWLEDGE_REVIEW")

        replay = api.record_agency_decision(
            listing["id"],
            {"decision": "ACKNOWLEDGE_REVIEW"},
            make_headers("lr-2", "ListingReviewer"),
        )
        validate_error(replay, ApiErrorId.ERR_LISTING_STATE_INVALID.value)

        row = read_certification_listing(listing["id"])
        assert row["status"] == "UNDER_REVIEW", (
            f"the replay leaves the listing UNDER_REVIEW, got {row['status']}"
        )
        assert row["decided_by_user_id"] == LISTING_REVIEWER_USER_ID, (
            "the first decider's identifier is kept, got "
            f"{row['decided_by_user_id']}"
        )


class TestAgencyRemitAndRetrieval:
    def test_agency_scope_coverage_is_checked_against_the_agencys_own_accreditation(
        self, api, compliance_engineer
    ):
        """AGENCY_ALPHA cannot be asked for GAS, but the SANITATION-only filing is accepted.

        PRD §3.1: "Three agencies exist and their remits differ: `AGENCY_ALPHA` may grant
        only `SANITATION`, `AGENCY_BETA` may grant `GAS` and `ELECTRICAL`, and
        `AGENCY_GAMMA` may grant all three of `SANITATION`, `GAS` and `ELECTRICAL`."

        Design: Corner/validations/agency_scope_coverage_is_checked_against_the_agencys_own_accreditation
        """
        set_clock()
        model = create_equipment_model(
            model_code="RNG-800",
            name="Gas Griddle 800",
            category="GRIDDLE",
            energy_type="GAS",
            base_price_cents=2200000,
            supported_controls_packages=["STANDARD_DIAL"],
            rated_throughput_units_per_hour=60,
        )
        assert model["certification_posture"] == "UNLISTED", (
            f"a brand-new model is UNLISTED, got {model['certification_posture']}"
        )

        refused = api.create_certification_listing(
            certification_listing_payload(
                model["id"], "AGENCY_ALPHA", ["SANITATION", "GAS"]
            ),
            compliance_engineer,
        )
        validate_error(refused, ApiErrorId.ERR_AGENCY_SCOPE_NOT_COVERED.value)

        accepted = validate_success(
            api.create_certification_listing(
                certification_listing_payload(model["id"], "AGENCY_ALPHA", ["SANITATION"]),
                compliance_engineer,
            ),
            201,
        )
        assert accepted["status"] == "DRAFT", (
            f"the in-remit filing lands in DRAFT, got {accepted['status']}"
        )
        assert accepted["scopes"] == ["SANITATION"], (
            f"the accepted filing keeps its single scope, got {accepted['scopes']}"
        )

        rows, meta = validate_paginated(
            api.list_certification_listings(
                compliance_engineer, params={"equipment_model_id": model["id"]}
            )
        )
        assert meta["total_count"] == 1, (
            "the refused filing must not have created a row, so only one listing exists, "
            f"got {meta['total_count']}"
        )
        assert [row["id"] for row in rows] == [accepted["id"]], (
            f"the only row is the accepted filing, got {[row['id'] for row in rows]}"
        )

    def test_certification_listing_retrieval_returns_stored_row_with_null_decision_fields(
        self, api, listing_reviewer
    ):
        """A DRAFT listing echoes its inputs while every decision field is still null.

        PRD §3.1: "A new application starts in `DRAFT` with `revision` at 0,
        `conditions_note`, `listed_on`, `expires_on`, `submitted_by_user_id` and
        `decided_by_user_id` all null."

        Design: Corner/entities/certification_listing_retrieval_returns_stored_row_with_null_decision_fields
        """
        model, listing = _model_with_draft_listing(
            agency_code="AGENCY_GAMMA", scopes=["SANITATION", "ELECTRICAL"]
        )

        row = validate_success(
            api.get_certification_listing(listing["id"], listing_reviewer)
        )

        assert row["status"] == "DRAFT", (
            f"the row is still a draft application, got {row['status']}"
        )
        assert row["revision"] == 0, f"revision starts at 0, got {row['revision']}"
        assert row["agency_code"] == "AGENCY_GAMMA", (
            f"the agency is echoed exactly as filed, got {row['agency_code']}"
        )
        assert row["scopes"] == ["SANITATION", "ELECTRICAL"], (
            f"the requested scopes are echoed exactly as filed, got {row['scopes']}"
        )
        assert row["equipment_model_id"] == model["id"], (
            f"the listing points at its model, got {row['equipment_model_id']}"
        )
        for field in (
            "listed_on",
            "expires_on",
            "conditions_note",
            "submitted_by_user_id",
            "decided_by_user_id",
        ):
            assert row[field] is None, (
                f"{field} must still be null on a DRAFT listing, got {row[field]}"
            )
