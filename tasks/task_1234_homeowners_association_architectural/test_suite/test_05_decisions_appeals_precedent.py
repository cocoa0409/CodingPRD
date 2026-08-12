"""Committee decisions, board appeals, variance precedent, conditions amendment (OCC)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    TEST_USERS, ApiErrorId,
    create_variance_payload,
    create_association, register_owner, register_property,
    decide, read_application, read_property, get_single_permit,
    set_logical_clock, setup_review_ready, setup_denied_application,
    make_homeowner_headers, make_committee_member_headers,
    make_board_member_headers,
)

MANAGER = TEST_USERS["manager_headers"]


class TestApprovalCascade:
    """The approving decision mutates the application, creates the permit, recomputes."""

    def test_decision_sets_outcome_conditions_and_permit(self, api):
        """PRD §3.4: "A decision that passes everything moves the application from
        `UNDER_REVIEW` to `APPROVED_WITH_CONDITIONS`: `decision_outcome` becomes
        `APPROVED`, the `conditions` list is taken from the decision payload,
        `decided_at` is stamped, and `version` increments."
        PRD §3.4: "The approval then cascades: a construction permit is created in
        `ACTIVE` status with its `window_start` and `window_end` copied from the
        application's requested window"

        Design: Difficulty/transitive_cascade/approval_cascade_application_to_permit_to_property
        """
        bundle = setup_review_ready()
        app_id = bundle["application"]["id"]
        decided = decide(app_id, conditions=["panels flush-mounted", "conduit hidden"])
        assert decided["status"] == "APPROVED_WITH_CONDITIONS"
        assert decided["decision_outcome"] == "APPROVED"
        assert decided["conditions"] == ["panels flush-mounted", "conduit hidden"]
        assert decided.get("decided_at"), "decided_at must be stamped"

        permit = get_single_permit(app_id)
        assert permit["status"] == "ACTIVE"
        assert permit["window_start"] == "2026-06-01"
        assert permit["window_end"] == "2026-07-15"

    def test_approval_recomputes_open_permit_count(self, api):
        """PRD §2.5: "`open_permit_count` is the number of construction permits in
        `ACTIVE` status linked, through applications, to the property. It is
        recomputed whenever a permit is created or completed."
        PRD §3.4: "The approval then cascades: a construction permit is created in
        `ACTIVE` status with its `window_start` and `window_end` copied from the
        application's requested window, and the property's `open_permit_count` is
        recomputed to reflect the new permit."

        Design: Difficulty/transitive_cascade/approval_cascade_application_to_permit_to_property
        """
        bundle = setup_review_ready()
        prop_id = bundle["property"]["id"]
        before = read_property(prop_id)
        assert before["open_permit_count"] == 0

        decide(bundle["application"]["id"], conditions=[])
        after = read_property(prop_id)
        assert after["open_permit_count"] == 1, (
            f"permit creation must bubble up to the property: {after['open_permit_count']}")


class TestAppeals:
    """Denial -> appeal -> board decision, with segregation of duties."""

    def _file_appeal(self, api, bundle, grounds="neighbor precedent"):
        res = api.file_appeal(
            bundle["application"]["id"], {"grounds": grounds},
            make_homeowner_headers(bundle["applicant"]["id"]))
        return validate_success(res, 201)

    def test_terminal_lockdown_after_appeal_overruled(self, api):
        """After OVERRULED the application is terminally APPEAL_DENIED.

        PRD §3.6: "Overruling the appeal moves the appeal to `OVERRULED` and drives
        the application from `UNDER_APPEAL` to `APPEAL_DENIED`, which is terminal."
        PRD §3.4: "`APPROVED_WITH_CONDITIONS`, `DEEMED_APPROVED`, and `APPEAL_DENIED`
        are terminal: no further transitions are defined from them, and any attempt
        is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/terminal_lockdown_appeal_denied_rejected
        """
        bundle = setup_denied_application(ballots=("APPROVE", "DENY", "DENY"))
        app_id = bundle["application"]["id"]
        appeal = self._file_appeal(api, bundle)
        board_member = register_owner(bundle["association"]["id"],
                                      full_name="Dee D", email="dee.d@x.com")
        decided_appeal = validate_success(api.decide_appeal(
            appeal["id"], {"outcome": "OVERRULED", "board_note": "guideline is unambiguous"},
            make_board_member_headers(board_member["id"])), 200)
        assert decided_appeal["status"] == "OVERRULED"

        res = api.request_revision(
            app_id, {"revision_notes": "try again"},
            make_committee_member_headers(bundle["committee"][0]["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        assert read_application(app_id)["status"] == "APPEAL_DENIED"

    def test_committee_voter_and_applicant_cannot_decide_appeal(self, api):
        """Both segregation-of-duties bars reject the appeal decision; a clean member succeeds.

        PRD §3.6: "Segregation of duties guards this decision from both sides: the
        decider must not be the applicant, and must not have cast a committee ballot
        on the appealed application; either breach is rejected with
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/committee_voter_cannot_decide_appeal
        """
        bundle = setup_denied_application(ballots=("DENY", "DENY", "APPROVE"),
                                          denial_reason="height cap")
        app_id = bundle["application"]["id"]
        appeal = self._file_appeal(api, bundle, grounds="precedent exists")
        voter = bundle["committee"][0]  # cast a committee ballot on this application

        res1 = api.decide_appeal(appeal["id"], {"outcome": "OVERRULED"},
                                 make_board_member_headers(voter["id"]))
        validate_error(res1, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        res2 = api.decide_appeal(appeal["id"], {"outcome": "UPHELD"},
                                 make_board_member_headers(bundle["applicant"]["id"]))
        validate_error(res2, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        clean_member = register_owner(bundle["association"]["id"],
                                      full_name="Dee D", email="dee.d@x.com")
        ok = validate_success(api.decide_appeal(
            appeal["id"], {"outcome": "OVERRULED", "board_note": "affirmed"},
            make_board_member_headers(clean_member["id"])), 200)
        assert ok["status"] == "OVERRULED"
        assert read_application(app_id)["status"] == "APPEAL_DENIED"

    def test_appeal_after_window_expires_rejected(self, api):
        """Filing 31 days after denial exceeds the default 30-day appeal window.

        PRD §3.6: "The filing must come within the appeal window: the whole days
        after the denial's `decided_at` up to and including the filing day must not
        exceed the association's `appeal_window_days`, and a later filing is rejected
        with `ERR_APPEAL_WINDOW_EXPIRED`."
        PRD §3.1: "`appeal_window_days` (default 30, at least 1) sets how long after
        a denial an appeal may be filed."

        Design: Corner/validations/appeal_after_window_expires_rejected
        """
        bundle = setup_denied_application()  # denied at logical 2026-05-01
        app_id = bundle["application"]["id"]
        set_logical_clock("2026-06-01T09:00:00Z")  # 31 whole days after the denial
        res = api.file_appeal(app_id, {"grounds": "too late"},
                              make_homeowner_headers(bundle["applicant"]["id"]))
        validate_error(res, ApiErrorId.ERR_APPEAL_WINDOW_EXPIRED)
        assert read_application(app_id)["status"] == "DENIED"


class TestVariancePrecedent:
    """Variance recording requires an approved precedent application."""

    def test_variance_requires_approved_precedent(self, api):
        """Referencing an UNDER_REVIEW application fails; after approval it records.

        PRD §3.2: "A variance may only reference an application whose status is
        `APPROVED_WITH_CONDITIONS` or `DEEMED_APPROVED`; referencing any other
        application is rejected with `ERR_PRECEDENT_NOT_APPROVED`."

        Design: Corner/validations/variance_requires_approved_precedent_rejected
        """
        bundle = setup_review_ready()
        assoc_id = bundle["association"]["id"]
        app_id = bundle["application"]["id"]
        payload = create_variance_payload(
            app_id, guideline_section="SEC-4.2",
            deviation_description="8ft where 6ft max")

        res = api.create_variance(assoc_id, payload, MANAGER)
        validate_error(res, ApiErrorId.ERR_PRECEDENT_NOT_APPROVED)

        decide(app_id, conditions=["variance granted"])
        recorded = validate_success(api.create_variance(assoc_id, payload, MANAGER), 201)
        assert recorded["application_id"] == app_id
        assert recorded["guideline_section"] == "SEC-4.2"

    def test_variance_search_filters_by_guideline_section(self, api):
        """The precedent registry is searchable by an optional section filter.

        PRD §3.2: "The registry is searchable by any role, with an optional
        `guideline_section` query filter, and the precedents referencing a
        particular application are also listable on that application."

        Design: Corner/endpoints/variance_precedent_search_filters_by_section
        """
        bundle = setup_review_ready()
        assoc_id = bundle["association"]["id"]
        app_id = bundle["application"]["id"]
        decide(app_id, conditions=["variance granted"])
        validate_success(api.create_variance(assoc_id, create_variance_payload(
            app_id, guideline_section="SEC-4.2",
            deviation_description="8ft where 6ft max"), MANAGER), 201)
        validate_success(api.create_variance(assoc_id, create_variance_payload(
            app_id, guideline_section="SEC-7.1",
            deviation_description="dark shingle in light zone"), MANAGER), 201)

        reader = make_committee_member_headers(bundle["committee"][0]["id"])
        filtered = validate_paginated(api.list_variances(
            assoc_id, reader, params={"guideline_section": "SEC-4.2"}))[0]
        assert len(filtered) == 1
        assert filtered[0]["guideline_section"] == "SEC-4.2"
        assert filtered[0]["deviation_description"] == "8ft where 6ft max"

        unfiltered = validate_paginated(api.list_variances(assoc_id, reader))[0]
        assert len(unfiltered) == 2


def test_amend_conditions_stale_version_rejected(api):
    """The conditions amendment is OCC-guarded; a replayed stale version is rejected.

    PRD §2.10: "Amending an application's approval conditions requires the request
    to carry `expected_application_version`, holding the application `version` the
    client last observed. If the application's current `version` no longer matches —
    because another writer has amended the conditions or otherwise legitimately
    advanced the application since the client's last read — the amendment is
    rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from
    overwriting state it has not observed."
    PRD §3.4: "A successful amendment replaces `conditions` with the payload and
    increments `version` by one."

    Design: Corner/cross_cutting_complexity_layers/occ_amend_conditions_stale_version_rejected
    """
    bundle = setup_review_ready()
    app_id = bundle["application"]["id"]
    decided = decide(app_id, conditions=["stain natural"])
    observed_version = decided["version"]
    member = make_committee_member_headers(bundle["committee"][0]["id"])

    first = validate_success(api.amend_conditions(app_id, {
        "conditions": ["stain natural", "inspect post bases"],
        "expected_application_version": observed_version,
    }, member), 200)
    assert first["version"] == observed_version + 1
    assert first["conditions"] == ["stain natural", "inspect post bases"]

    replay = api.amend_conditions(app_id, {
        "conditions": ["stain natural", "inspect post bases", "weekly cleanup"],
        "expected_application_version": observed_version,
    }, member)
    validate_error(replay, ApiErrorId.ERR_STALE_VERSION)
