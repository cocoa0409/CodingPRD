"""The three concurrency tokens, each guarding a different parent row, and the compliance band a
location crosses only when its untrained hire is off the payroll.
"""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    assert_same_instant,
    certify_one_server,
    create_draft_course,
    create_employer_account,
    create_jurisdiction,
    dram_shop_document_payload,
    end_assignment,
    enroll_server,
    enrollment_payload,
    get_account,
    get_course_row,
    get_location,
    get_session,
    get_server,
    list_dram_shop_documents_for,
    make_alcohol_server_headers,
    make_employer_admin_headers,
    register_alcohol_server,
    set_clock,
    setup_employer_account,
    setup_training_base,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-03T09:00:00Z"
COMPLETION_CLOCK = "2026-08-10T18:30:00Z"
ONE_LOCATION = [{"location_name": "Alamo Taproom", "annual_premium_cents": 4821734}]
STRICT_TX = {
    "min_passing_score_pct": 70,
    "proctor_separation_required": False,
    "certificate_validity_months": 24,
    "registry_deadline_days": 15,
}


class TestConcurrencyTokens:
    def test_a_seat_claimed_against_a_superseded_roster_revision_is_refused(self, api):
        """PRD §2.5: "Creating an enrollment must carry `expected_class_session_version`, holding
        the client's last observed `version` of the target `ClassSession`. A seat is a finite
        resource: the caller's picture of `enrolled_count` and remaining `capacity` is stale the
        moment any other enrollment, withdrawal or roster transition has advanced the session's
        `version`. If the supplied value does not equal the session's current `version`, the create
        is rejected with `ERR_STALE_SESSION_VERSION` (HTTP 412), and the caller must re-read the
        roster before claiming a seat."
        PRD §3.5: "An accepted enrollment lands in `REGISTERED`, raises the session's
        `enrolled_count` by one and increments the session's `version` by one."

        Design: Corner/cross-cutting complexity layers/occ_enrollment_create_rejects_the_session_version_the_client_last_read
        """
        base = setup_training_base(
            clock=CLOCK, jurisdiction_overrides={"proctor_separation_required": False})
        session_id = base["session"]["id"]
        first_seen_version = base["session"]["version"]

        ari = register_alcohol_server(base["jurisdiction"]["id"])
        bo = register_alcohol_server(base["jurisdiction"]["id"],
                                     full_name="Bo Nakamura", email="bo@example.com")
        bo_headers = make_alcohol_server_headers(bo["id"])

        enroll_server(session_id, ari["id"], expected_class_session_version=first_seen_version,
                      headers=make_alcohol_server_headers(ari["id"]))

        validate_error(api.create_enrollment(
            enrollment_payload(session_id, bo["id"], first_seen_version), bo_headers),
            ApiErrorId.ERR_STALE_SESSION_VERSION, 412)
        held = get_session(session_id)
        assert held["enrolled_count"] == 1, (
            f"the refused claim took no seat, got {held['enrolled_count']}")
        assert held["version"] == first_seen_version + 1, (
            "only the accepted enrollment advanced the roster revision, got "
            f"{held['version']} against {first_seen_version + 1}")

        retried = validate_success(api.create_enrollment(
            enrollment_payload(session_id, bo["id"], held["version"]), bo_headers), 201)
        assert retried["enrollment_state"] == "REGISTERED"

        after = get_session(session_id)
        assert after["version"] == first_seen_version + 2
        assert after["enrolled_count"] == 2

    def test_a_revision_computed_against_the_pre_publication_body_is_refused(self, api):
        """PRD §2.5: "Applying a content revision to a course must carry `expected_course_version`,
        holding the client's last observed `version` of that `Course`. Every accepted revision
        invalidates each `APPROVED` approval of the course, so an edit computed against an earlier
        body would silently re-stale approvals the editor never saw. A mismatch with the course's
        current `version` is rejected with `ERR_STALE_COURSE_VERSION` (HTTP 412)."
        PRD §3.2: "An accepted revision applies the supplied changes, raises
        `content_revision_count` by one and increments the course's `version`."
        PRD §3.2: "A revision may supply any of `title`, `contact_hours` and `question_count`, and
        must supply a `revision_note` recording why."

        Design: Corner/cross-cutting complexity layers/occ_course_revision_rejects_the_version_the_editor_read_before_publication
        """
        set_clock(CLOCK)
        draft = create_draft_course()
        first_seen_version = draft["version"]
        published = validate_success(api.publish_course(draft["id"], ADMIN), 200)
        assert published["version"] == first_seen_version + 1, (
            "publication is itself a mutation of the row, got "
            f"{published['version']} against {first_seen_version + 1}")

        stale_edit = {"expected_course_version": first_seen_version,
                      "revision_note": "clarify the intervention module",
                      "contact_hours": 5}
        validate_error(api.revise_course(draft["id"], stale_edit, ADMIN),
                       ApiErrorId.ERR_STALE_COURSE_VERSION, 412)
        untouched = get_course_row(draft["id"])
        assert untouched["contact_hours"] == 4.00, (
            f"the refused edit changed no content, got {untouched['contact_hours']}")
        assert untouched["content_revision_count"] == 0

        accepted = validate_success(api.revise_course(
            draft["id"], dict(stale_edit, expected_course_version=untouched["version"]),
            ADMIN), 200)
        assert accepted["contact_hours"] == 5.00
        assert accepted["content_revision_count"] == 1
        assert accepted["status"] == "PUBLISHED"
        assert accepted["version"] == first_seen_version + 2, (
            f"publication then revision is two bumps, got {accepted['version']}")

    def test_documentation_read_before_the_location_landed_is_refused_on_the_token_first(
            self, api):
        """PRD §2.5: "Issuing a dram-shop document must carry
        `expected_employer_account_version`, holding the client's last observed `version` of the
        `EmployerAccount`. Issuance supersedes the account's prior issued document and freezes a
        compliance snapshot; if the account's `version` has advanced since the client read it, the
        snapshot the client believes it is certifying no longer matches the account, and the
        issuance is rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412)."
        PRD §3.9: "The account must not be `SUSPENDED`, and its `account_compliance_rate_pct` must
        be at least 80.00 — the documentation floor — with anything below refused as
        `ERR_COMPLIANCE_RATE_TOO_LOW`."
        PRD §3.9: "Note that an account with no live assignment reads 0.00 and is therefore
        rejected by this floor rather than waved through."

        Design: Corner/cross-cutting complexity layers/occ_dram_shop_issuance_rejects_the_account_version_read_before_the_location_was_added
        """
        set_clock(CLOCK)
        jurisdiction = create_jurisdiction()
        account = create_employer_account()
        account_id = account["id"]
        employer_headers = make_employer_admin_headers(account_id)
        first_seen_version = account["version"]

        validate_success(api.create_employer_location(
            account_id,
            {"location_name": "Alamo Taproom", "state_jurisdiction_id": jurisdiction["id"],
             "premise_type": "ON_PREMISE", "annual_premium_cents": 4821734},
            employer_headers), 201)

        validate_error(api.issue_dram_shop_document(
            account_id, dram_shop_document_payload(first_seen_version), employer_headers),
            ApiErrorId.ERR_STALE_ACCOUNT_VERSION, 412)

        current = validate_success(api.get_employer_account(account_id, employer_headers), 200)
        assert current["version"] == first_seen_version + 1, (
            "adding the location advanced the account row, got "
            f"{current['version']} against {first_seen_version + 1}")

        validate_error(api.issue_dram_shop_document(
            account_id, dram_shop_document_payload(current["version"]), employer_headers),
            ApiErrorId.ERR_COMPLIANCE_RATE_TOO_LOW, 422)

        assert list_dram_shop_documents_for(account_id, employer_headers) == [], (
            "neither refusal filed a document")
        assert get_account(account_id)["dram_shop_discount_status"] == "NOT_DOCUMENTED"


class TestPostureBands:
    def test_the_location_only_clears_the_compliant_band_once_the_untrained_hire_leaves(
            self, api):
        """PRD §3.8: "At a location whose `training_requirement` is `MANDATED`, a server whose
        `work_eligibility` is `RESTRICTED` is refused outright with `ERR_SERVER_WORK_RESTRICTED`; an
        `UNCERTIFIED` server is accepted and simply starts the new-hire training window."
        PRD §3.8: "Otherwise it is `COMPLIANT` at 95.00 or above, `AT_RISK` at 80.00 or above but
        below 95.00, and `NON_COMPLIANT` below 80.00."
        PRD §3.8: "Both behave identically: `assignment_state` becomes `ENDED` — a terminal state —
        `ended_at` is stamped from the logical clock, the location's `assigned_server_count` falls
        by one, counts and both rates are recomputed and the posture re-thresholded, and stages four
        and five of the recompute chain then run."
        PRD §2.8: "**Stage four — account roll-up.** The owning `EmployerAccount` has its
        `location_count` and `account_compliance_rate_pct` recomputed. If
        `dram_shop_discount_status` is `NOT_DOCUMENTED` and the recomputed
        `account_compliance_rate_pct` is at least 80.00, the status advances to `ELIGIBLE`."

        Design: Corner/cross-cutting complexity layers/posture_band_crosses_the_eighty_floor_only_when_the_uncertified_hire_leaves
        """
        base = setup_training_base(clock=CLOCK, jurisdiction_overrides=STRICT_TX)
        bo = register_alcohol_server(base["jurisdiction"]["id"],
                                     full_name="Bo Nakamura", email="bo@example.com")
        ari = certify_one_server(base)["server"]

        employer = setup_employer_account(base["jurisdiction"]["id"], seat_quantity=0,
                                          location_specs=ONE_LOCATION)
        account_id = employer["account"]["id"]
        employer_headers = employer["employer_headers"]
        location_id = employer["locations"][0]["id"]

        untrained = validate_success(api.create_server_assignment(
            location_id, {"alcohol_server_id": bo["id"], "role_title": "Barback"},
            employer_headers), 201)
        assert get_server(bo["id"])["work_eligibility"] == "UNCERTIFIED"
        assert untrained["assignment_state"] == "ACTIVE", (
            "only a RESTRICTED server is turned away at the door")
        assert_same_instant(untrained["assigned_at"], COMPLETION_CLOCK, "assigned_at")

        alone = get_location(location_id)
        assert (alone["assigned_server_count"], alone["compliant_server_count"]) == (1, 0)
        assert alone["compliance_rate_strict_pct"] == 0.00
        assert alone["compliance_rate_grace_inclusive_pct"] == 0.00
        assert alone["compliance_posture"] == "NON_COMPLIANT"

        trained = validate_success(api.create_server_assignment(
            location_id, {"alcohol_server_id": ari["id"], "role_title": "Bartender"},
            employer_headers), 201)

        halfway = get_location(location_id)
        assert (halfway["assigned_server_count"], halfway["compliant_server_count"]) == (2, 1)
        assert halfway["compliance_rate_strict_pct"] == 50.00
        assert halfway["compliance_rate_grace_inclusive_pct"] == 50.00
        assert halfway["compliance_posture"] == "NON_COMPLIANT", (
            "50.00 sits below the 80.00 floor of the at-risk band, got "
            f"{halfway['compliance_posture']}")
        mid_account = get_account(account_id)
        assert mid_account["account_compliance_rate_pct"] == 50.00
        assert mid_account["dram_shop_discount_status"] == "NOT_DOCUMENTED"

        end_assignment(untrained["id"], employer_headers,
                       end_reason="did not complete training")

        cleared = get_location(location_id)
        assert cleared["assigned_server_count"] == 1
        assert cleared["compliance_rate_strict_pct"] == 100.00
        assert cleared["compliance_rate_grace_inclusive_pct"] == 100.00
        assert cleared["compliance_posture"] == "COMPLIANT", (
            f"100.00 clears the 95.00 band floor, got {cleared['compliance_posture']}")
        final_account = get_account(account_id)
        assert final_account["account_compliance_rate_pct"] == 100.00
        assert final_account["dram_shop_discount_status"] == "ELIGIBLE"

        rows, meta = validate_paginated(api.list_location_server_assignments(
            location_id, employer_headers))
        assert meta["total_count"] == 2, (
            f"the ended row is retained alongside the live one, got {meta['total_count']}")
        assert [row["id"] for row in rows if row["assignment_state"] == "ACTIVE"] == [
            trained["id"]]
