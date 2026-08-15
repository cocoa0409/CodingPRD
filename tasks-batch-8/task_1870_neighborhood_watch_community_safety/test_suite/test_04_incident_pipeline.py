"""Incident report intake, the cyclic review pipeline, and segregation rules."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_member,
    assert_incident_report,
    corroborate_report,
    create_active_agreement,
    create_incident_report_payload,
    create_officer,
    file_incident,
    make_coordinator_headers,
    make_member_headers,
    make_officer_headers,
    move_report_to_under_review,
    set_clock,
    setup_group_with_member,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]


class TestIncidentIntake:
    def test_new_report_born_submitted(self, api):
        """PRD §3.3: "Reports are born in `review_status` `SUBMITTED` with
        `corroboration_weight` zero and `shared_with_liaison` false."

        Design: Corner/state_machines/incident_report_initial_state_submitted
        """
        set_clock("2026-08-01T09:00:00Z")
        group, block, member = setup_group_with_member("Init Watch", "S01")
        report = validate_success(
            api.create_incident_report(
                create_incident_report_payload(
                    block["id"], member["id"], category="NOISE",
                    occurred_at="2026-08-01T09:00:00Z", severity=1,
                ),
                make_member_headers(member["id"]),
            ),
            201,
        )
        assert_incident_report(report)
        assert report["review_status"] == "SUBMITTED"
        assert report["corroboration_weight"] == 0
        assert report["shared_with_liaison"] is False

    def test_invalid_category_rejected(self, api):
        """PRD §3.3: "supplying the `block_id`, the filing member's
        `reporter_member_id`, a `category` of `SUSPICIOUS_ACTIVITY`,
        `PROPERTY_CRIME`, `VANDALISM`, `NOISE`, `TRAFFIC`, or `OTHER`"
        PRD §2.6: "then field-level request validity (`ERR_INVALID_REQUEST`)"

        Design: Corner/entities/incident_report_invalid_enum_category_rejected
        """
        set_clock("2026-08-02T00:00:00Z")
        group, block, member = setup_group_with_member("Enum Watch", "D05")
        resp = api.create_incident_report(
            create_incident_report_payload(
                block["id"], member["id"], category="WITCHCRAFT",
                occurred_at="2026-08-01T10:00:00Z", severity=2,
            ),
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_severity_out_of_range_rejected(self, api):
        """PRD §3.3: "An `occurred_at` in the future relative to the logical
        clock, or a `severity` outside the 1-to-5 band, fails with
        `ERR_INVALID_REQUEST`."

        Design: Corner/validations/invalid_request_severity_out_of_range
        """
        set_clock("2026-08-02T00:00:00Z")
        group, block, member = setup_group_with_member("Sev Watch", "V08")
        for bad_severity in (6, 0):
            resp = api.create_incident_report(
                create_incident_report_payload(
                    block["id"], member["id"], category="OTHER",
                    occurred_at="2026-08-01T09:00:00Z", severity=bad_severity,
                ),
                make_member_headers(member["id"]),
            )
            validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_clock_default_gates_future_occurred_at(self, api):
        """PRD §2.5: "Before any client sets it, the logical clock reads exactly
        `2026-08-01T00:00:00Z`, and it must never fall back to wall-clock time on
        its own."
        PRD §3.3: "An `occurred_at` in the future relative to the logical clock,
        or a `severity` outside the 1-to-5 band, fails with `ERR_INVALID_REQUEST`."

        Design: Corner/endpoints/clock_default_value_before_any_set
        """
        # No clock-set call: the default reading is 2026-08-01T00:00:00Z.
        group, block, member = setup_group_with_member("Clock Watch", "E02")
        resp = api.create_incident_report(
            create_incident_report_payload(
                block["id"], member["id"], category="OTHER",
                occurred_at="2026-08-01T00:00:01Z", severity=1,
            ),
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        ok = validate_success(
            api.create_incident_report(
                create_incident_report_payload(
                    block["id"], member["id"], category="OTHER",
                    occurred_at="2026-08-01T00:00:00Z", severity=1,
                ),
                make_member_headers(member["id"]),
            ),
            201,
        )
        assert_incident_report(ok)


class TestReviewLoop:
    def _setup_loop_report(self, api):
        group, block, member = setup_group_with_member("Loop Watch", "PCT5")
        other = add_member(group["id"], block["id"], "Rep Two", "EMAIL")
        officer = create_officer("B500", "Officer L", "PCT5")
        create_active_agreement(group["id"], officer,
                                scope="INCIDENT_SUMMARIES")
        report = file_incident(block["id"], member, category="NOISE",
                               occurred_at="2026-07-30T21:00:00Z", severity=1)
        return group, block, member, other, officer, report

    def test_review_loop_reenters_under_review(self, api):
        """PRD §3.3: "While `UNDER_REVIEW`, the coordinator may bounce the report
        to `NEEDS_INFO`, which returns it to the reporter for clarification.
        Resubmission from `NEEDS_INFO` back to `UNDER_REVIEW` is restricted to
        the original reporter"

        Design: Difficulty/non_linear_state_machine/incident_report_review_loop_cycle
        """
        _g, _b, member, _o, officer, report = self._setup_loop_report(api)
        move_report_to_under_review(report["id"])

        bounced = validate_success(api.request_info_incident(report["id"], COORD))
        assert bounced["review_status"] == "NEEDS_INFO"

        resubmitted = validate_success(
            api.resubmit_incident(report["id"], make_member_headers(member["id"]))
        )
        assert resubmitted["review_status"] == "UNDER_REVIEW", (
            "The loop re-enters UNDER_REVIEW after the NEEDS_INFO bounce"
        )

        corroborated = corroborate_report(report["id"], officer)
        assert corroborated["review_status"] == "CORROBORATED"

    def test_review_loop_increments_version_each_transition(self, api):
        """PRD §3.3: "Every one of these transitions increments the report's
        `version`."
        PRD §2.4: "`version` (integer): A system-managed integer that increments
        by one with every modification to the resource."

        Design: Difficulty/non_linear_state_machine/incident_report_review_loop_cycle
        """
        _g, _b, member, _o, officer, report = self._setup_loop_report(api)
        v0 = report["version"]

        under_review = move_report_to_under_review(report["id"])
        assert under_review["version"] == v0 + 1
        bounced = validate_success(api.request_info_incident(report["id"], COORD))
        assert bounced["version"] == v0 + 2
        resubmitted = validate_success(
            api.resubmit_incident(report["id"], make_member_headers(member["id"]))
        )
        assert resubmitted["version"] == v0 + 3
        corroborated = corroborate_report(report["id"], officer)
        assert corroborated["version"] == v0 + 4, (
            "begin-review, request-info, resubmit, corroborate each bump by 1"
        )


class TestTerminalLockdown:
    def test_dismissed_report_rejects_further_actions(self, api):
        """PRD §3.3: "Dismissal by a coordinator — again not the reporter, else
        `ERR_SEGREGATION_OF_DUTIES` — moves it to `DISMISSED`, terminal, with
        `corroboration_weight` staying zero."
        PRD §2.6: "fourth, whether the target resource is in a state from which
        the requested transition exists (`ERR_INVALID_STATE`)"

        Design: Corner/state_machines/terminal_state_lockdown_dismissed_report_rejects_all_actions
        """
        set_clock("2026-08-02T00:00:00Z")
        group, block, member = setup_group_with_member("Term Watch", "S02")
        officer = create_officer("BS02", "Officer T", "S02")
        report = file_incident(block["id"], member, category="OTHER",
                               occurred_at="2026-08-01T09:00:00Z", severity=1)
        move_report_to_under_review(report["id"])
        dismissed = validate_success(api.dismiss_incident(report["id"], COORD))
        assert dismissed["review_status"] == "DISMISSED"
        assert dismissed["corroboration_weight"] == 0

        resp = api.corroborate_incident(
            report["id"], make_officer_headers(officer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        after = validate_success(api.get_incident_report(report["id"], COORD))
        assert after["review_status"] == "DISMISSED"
        assert after["corroboration_weight"] == 0


class TestReporterOnlyResubmission:
    def test_only_original_reporter_may_resubmit(self, api):
        """PRD §3.3: "Resubmission from `NEEDS_INFO` back to `UNDER_REVIEW` is
        restricted to the original reporter — the acting member's id must equal
        `reporter_member_id`, and anyone else is refused with
        `ERR_REPORTER_ONLY` (HTTP 403)."

        Design: Corner/validations/reporter_only_resubmit_enforced
        """
        set_clock("2026-08-02T00:00:00Z")
        group, block, member = setup_group_with_member("RepOnly Watch", "V10")
        other = add_member(group["id"], block["id"], "RO Two", "EMAIL")
        report = file_incident(block["id"], member, category="NOISE",
                               occurred_at="2026-08-01T09:00:00Z", severity=1)
        move_report_to_under_review(report["id"])
        validate_success(api.request_info_incident(report["id"], COORD))

        resp = api.resubmit_incident(report["id"], make_member_headers(other["id"]))
        validate_error(resp, ApiErrorId.ERR_REPORTER_ONLY)

        resubmitted = validate_success(
            api.resubmit_incident(report["id"], make_member_headers(member["id"]))
        )
        assert resubmitted["review_status"] == "UNDER_REVIEW"


class TestSegregationOfDuties:
    def test_reporter_cannot_begin_review_of_own_report(self, api):
        """PRD §2.12: "First, no one may review their own incident report: the
        coordinator who begins review of, or dismisses, a report must not be the
        member who filed it."
        PRD §2.12: "A violation of either rule is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/validations/segregation_of_duties_reporter_cannot_review_own_incident
        """
        set_clock("2026-08-02T00:00:00Z")
        group, block, member = setup_group_with_member("SoD Watch", "V02")
        report = file_incident(block["id"], member, category="OTHER",
                               occurred_at="2026-08-01T09:00:00Z", severity=2)
        # The coordinator's opaque user id pinned equal to the reporter's id.
        resp = api.begin_review_incident(
            report["id"], make_coordinator_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        after = validate_success(api.get_incident_report(report["id"], COORD))
        assert after["review_status"] == "SUBMITTED"


class TestCorroborationDataShareGate:
    def test_corroborate_rejected_without_active_agreement(self, api):
        """PRD §3.3: "Corroboration by a `LiaisonOfficer` moves it to
        `CORROBORATED`, but only when an `ACTIVE` data-sharing agreement of scope
        `INCIDENT_SUMMARIES` or `FULL` covers the report's group; without one the
        transition is rejected with `ERR_DATA_SHARE_REQUIRED`."

        Design: Difficulty/cross_entity_state_dependency/corroborate_requires_active_data_share_agreement
        """
        group, block, member = setup_group_with_member("XDep Watch", "PCT13")
        officer = create_officer("B130", "Officer X", "PCT13")
        # Agreement drafted but never activated (stays PENDING).
        validate_success(
            api.create_data_share_agreement(
                {
                    "watch_group_id": group["id"],
                    "liaison_officer_id": officer["id"],
                    "scope": "INCIDENT_SUMMARIES",
                    "expires_at": "2027-01-01T00:00:00Z",
                },
                COORD,
            ),
            201,
        )
        report = file_incident(block["id"], member, category="OTHER",
                               occurred_at="2026-07-15T10:00:00Z", severity=2)
        move_report_to_under_review(report["id"])

        resp = api.corroborate_incident(
            report["id"], make_officer_headers(officer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DATA_SHARE_REQUIRED)

        after = validate_success(api.get_incident_report(report["id"], COORD))
        assert after["review_status"] == "UNDER_REVIEW", (
            "The failed corroborate leaves the report's state untouched"
        )

    def test_corroborate_succeeds_once_agreement_active(self, api):
        """PRD §3.3: "Corroboration by a `LiaisonOfficer` moves it to
        `CORROBORATED`, but only when an `ACTIVE` data-sharing agreement of scope
        `INCIDENT_SUMMARIES` or `FULL` covers the report's group; without one the
        transition is rejected with `ERR_DATA_SHARE_REQUIRED`."
        PRD §3.3: "When a report reaches `CORROBORATED`, its
        `corroboration_weight` is set per the heat calculation below,
        `shared_with_liaison` flips to true"

        Design: Difficulty/cross_entity_state_dependency/corroborate_requires_active_data_share_agreement
        """
        group, block, member = setup_group_with_member("XDep Watch", "PCT13")
        officer = create_officer("B130", "Officer X", "PCT13")
        create_active_agreement(group["id"], officer, scope="INCIDENT_SUMMARIES")
        report = file_incident(block["id"], member, category="OTHER",
                               occurred_at="2026-07-16T10:00:00Z", severity=2)
        move_report_to_under_review(report["id"])

        corroborated = corroborate_report(report["id"], officer)
        assert corroborated["review_status"] == "CORROBORATED"
        assert corroborated["shared_with_liaison"] is True


class TestLiaisonReadGate:
    def test_liaison_read_of_unshared_report_rejected(self, api):
        """PRD §2.12: "an officer may read an individual report only when the
        report's `shared_with_liaison` flag is true or an `ACTIVE` agreement of
        scope `INCIDENT_SUMMARIES` or `FULL` covers the group; otherwise the read
        is rejected with `ERR_DATA_SHARE_REQUIRED`."

        Design: Corner/errors/err_data_share_required_on_liaison_read
        """
        set_clock("2026-08-02T00:00:00Z")
        group, block, member = setup_group_with_member("NoShare Watch", "X02")
        officer = create_officer("BX02", "Officer NS", "X02")
        report = file_incident(block["id"], member, category="OTHER",
                               occurred_at="2026-08-01T09:00:00Z", severity=1)

        resp = api.get_incident_report(
            report["id"], make_officer_headers(officer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DATA_SHARE_REQUIRED)

        ok = validate_success(api.get_incident_report(report["id"], COORD))
        assert ok["id"] == report["id"]


class TestDerivedLastIncidentAt:
    def test_last_incident_at_tracks_only_corroborated_or_cleared(self, api):
        """PRD §3.3: "`last_incident_at` is updated to reflect the most recent
        corroborated or cleared report on the block"
        PRD §3.1: "`last_incident_at` null until a corroborated or cleared
        incident exists."

        Design: Corner/cross_cutting_layers/derived_field_reconciliation_last_incident_at
        """
        group, block, member = setup_group_with_member("Deriv Watch", "L03")
        officer = create_officer("BL03", "Officer Dv", "L03")
        create_active_agreement(group["id"], officer, scope="FULL")

        before = validate_success(api.get_block(block["id"], COORD))
        assert before["last_incident_at"] is None

        report_a = file_incident(block["id"], member, category="OTHER",
                                 occurred_at="2026-07-10T09:00:00Z", severity=1)
        report_b = file_incident(block["id"], member, category="NOISE",
                                 occurred_at="2026-07-20T09:00:00Z", severity=1)
        move_report_to_under_review(report_a["id"])
        corroborate_report(report_a["id"], officer)
        move_report_to_under_review(report_b["id"])
        dismissed = validate_success(api.dismiss_incident(report_b["id"], COORD))
        assert dismissed["review_status"] == "DISMISSED"

        block_after = validate_success(api.get_block(block["id"], COORD))
        assert block_after["last_incident_at"] is not None
        assert block_after["last_incident_at"].startswith("2026-07-10T09:00:00"), (
            "The dismissed report with the later occurred_at does not move the "
            "derived field — only CORROBORATED/CLEARED reports count"
        )
