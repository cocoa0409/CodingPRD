"""Appeals: deadlines, targets, outcome compatibility, officer identity."""
from test_helpers import (
    ApiErrorId,
    appeal_payload,
    assert_instant_equals,
    begin_appeal_review,
    begin_jurisdiction_review,
    create_case,
    decide_appeal,
    dismiss_case,
    drive_case_to_issued,
    file_appeal,
    get_case,
    make_cast,
    make_coordinator_headers,
    make_appeal_officer_headers,
    make_party_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client


class TestAppealDeadlineBoundary:
    def test_dismissal_appeal_at_exact_deadline_instant_accepted(self, api):
        """PRD 2.8: "An issued determination sets its `appeal_deadline` to
        `issued_at` plus 5 days; a dismissal's deadline is the case's `closed_at`
        plus 5 days. An appeal filed at exactly the deadline instant is timely —
        the boundary is inclusive — and a filing strictly after it is rejected
        with `ERR_APPEAL_WINDOW_EXPIRED` (422)."
        PRD 3.6: "Dismissal appeals are the sanctioned exception to the
        terminal-case guard: filing one on a `DISMISSED` case is expressly
        permitted."

        Design: Difficulty/boundary_precision_check/appeal_deadline_inclusive_instant
        """
        cast = make_cast("comp", "resp", "coord")
        case = create_case(cast, categories=["STALKING"], received_via="EMAIL",
                           occurred_at="2026-07-20T22:00:00Z")
        begin_jurisdiction_review(case["id"], cast["coord"]["id"])
        set_clock("2026-08-03T00:00:00Z")
        dismissed = dismiss_case(
            case["id"], cast["coord"]["id"],
            dismissal_reason="DISCRETIONARY_EVIDENCE_UNAVAILABLE", refer_to_conduct=False,
        )
        assert_instant_equals(dismissed["closed_at"], "2026-08-03T00:00:00Z", "closed_at")

        # closed_at + 5 days exactly: the inclusive boundary is timely.
        set_clock("2026-08-08T00:00:00Z")
        appeal = file_appeal(
            case["id"], cast["comp"]["id"], "COMPLAINANT", "DISMISSAL",
            ["PROCEDURAL_IRREGULARITY"], statement="At exact deadline",
        )
        assert appeal["status"] == "FILED"
        assert_instant_equals(appeal["filed_at"], "2026-08-08T00:00:00Z", "filed_at")

    def test_determination_appeal_one_second_late_rejected(self, api):
        """PRD 2.8: "An appeal filed at exactly the deadline instant is timely —
        the boundary is inclusive — and a filing strictly after it is rejected
        with `ERR_APPEAL_WINDOW_EXPIRED` (422)."
        PRD 3.5: "The determination itself moves `DRAFT → ISSUED`, stamps
        `issued_at` from the logical clock, computes `appeal_deadline` as
        `issued_at` plus the 5-day appeal window (filings at exactly that instant
        are timely), and records `issued_by_id` as the decision-maker taken from
        the completed hearing."

        Design: Difficulty/boundary_precision_check/appeal_deadline_inclusive_instant
        """
        cast = make_cast("comp", "resp", "coord", "inv", "dm", "advc", "advr")
        case = create_case(cast, categories=["OTHER_SEX_BASED"])
        stage = drive_case_to_issued(case["id"], cast)
        det = stage["determination"]
        # Issued 2026-09-01T10:00:00Z; appeal_deadline 2026-09-06T10:00:00Z.
        assert_instant_equals(det["appeal_deadline"], "2026-09-06T10:00:00Z", "appeal_deadline")

        set_clock("2026-09-06T10:00:01Z")
        resp = api.file_appeal(
            case["id"],
            appeal_payload(
                "RESPONDENT", "DETERMINATION", ["DISPROPORTIONATE_SANCTION"],
                statement="One second late",
            ),
            make_party_headers(cast["resp"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_APPEAL_WINDOW_EXPIRED)


class TestAppealTargetGating:
    def _dismissed_case(self, cast):
        case = create_case(cast, categories=["STALKING"])
        begin_jurisdiction_review(case["id"], cast["coord"]["id"])
        return dismiss_case(
            case["id"], cast["coord"]["id"],
            dismissal_reason="MANDATORY_NO_JURISDICTION", refer_to_conduct=False,
        )

    def test_appeal_target_requires_issued_determination(self, api):
        """PRD 3.6: "The target must also exist and be appealable: a
        `DETERMINATION` appeal requires a determination in `ISSUED` status on the
        case, and a `DISMISSAL` appeal requires the case in `DISMISSED`;
        `RESOLVED_INFORMAL` cases are never appealable, and determinations
        already `FINAL`, `REVERSED`, or `SUPERSEDED` are not either. Violations
        are `ERR_APPEAL_TARGET_INVALID` (422)."

        Design: Difficulty/cross_entity_state_dependency/appeal_target_requires_issued_determination
        """
        cast = make_cast("comp", "resp", "coord")
        case = self._dismissed_case(cast)
        resp = api.file_appeal(
            case["id"],
            appeal_payload("COMPLAINANT", "DETERMINATION", ["PROCEDURAL_IRREGULARITY"],
                           statement="No determination exists"),
            make_party_headers(cast["comp"]["id"]),
        )
        # No determination exists on this case at all: the DETERMINATION target
        # cannot be satisfied.
        validate_error(resp, ApiErrorId.ERR_APPEAL_TARGET_INVALID)

    def test_dismissal_appeal_accepted_on_same_case(self, api):
        """PRD 3.6: "a `DISMISSAL` appeal requires the case in `DISMISSED`".
        PRD 3.6: "Dismissal appeals are the sanctioned exception to the
        terminal-case guard: filing one on a `DISMISSED` case is expressly
        permitted."

        Design: Difficulty/cross_entity_state_dependency/appeal_target_requires_issued_determination
        """
        cast = make_cast("comp", "resp", "coord")
        case = self._dismissed_case(cast)
        appeal = file_appeal(
            case["id"], cast["comp"]["id"], "COMPLAINANT", "DISMISSAL",
            ["PROCEDURAL_IRREGULARITY"], statement="Dismissal appeal is valid",
        )
        assert appeal["status"] == "FILED"
        assert appeal["appeal_target"] == "DISMISSAL"


class TestSingleAppealGate:
    def test_second_appeal_filing_while_under_review_rejected(self, api):
        """PRD 3.6: "a determination-target filing also moves the case
        `DETERMINATION_ISSUED → APPEAL_REVIEW`."
        PRD 2.11: "**State** — the target entity must be in a from-state from which
        the requested transition exists in its machine, with terminal states
        rejecting all further transitions (`ERR_INVALID_STATE_TRANSITION`, 409)".

        Design: Corner/state_machines/second_appeal_filing_while_under_review_rejected
        """
        cast = make_cast("comp", "resp", "coord", "inv", "dm", "advc", "advr")
        case = create_case(cast, categories=["OTHER_SEX_BASED"], received_via="EMAIL")
        drive_case_to_issued(case["id"], cast)
        first = file_appeal(
            case["id"], cast["resp"]["id"], "RESPONDENT", "DETERMINATION",
            ["PROCEDURAL_IRREGULARITY"], statement="First appeal",
        )
        assert get_case(case["id"], cast["coord"]["id"])["status"] == "APPEAL_REVIEW"

        # The case-level gate is single-shot: from APPEAL_REVIEW no further
        # appeal filing transition exists.
        second = api.file_appeal(
            case["id"],
            appeal_payload("COMPLAINANT", "DETERMINATION", ["DISPROPORTIONATE_SANCTION"],
                           statement="Second appeal"),
            make_party_headers(cast["comp"]["id"]),
        )
        validate_error(second, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

        coord_h = make_coordinator_headers(cast["coord"]["id"])
        appeals, meta = validate_paginated(api.list_case_appeals(case["id"], coord_h))
        assert meta["total_count"] == 1 and len(appeals) == 1
        assert appeals[0]["id"] == first["id"] and appeals[0]["status"] == "FILED"


class TestOutcomeCompatibility:
    def test_dismissal_appeal_reversed_incompatible_then_reinstated(self, api):
        """PRD 3.6: "The decision carries an `outcome`, and compatibility with the
        `appeal_target` is enforced — `AFFIRMED` is allowed for both targets;
        `REVERSED`, `REMANDED`, and `SANCTION_MODIFIED` only for `DETERMINATION`;
        `REINSTATED` only for `DISMISSAL` — failing as
        `ERR_APPEAL_OUTCOME_INCOMPATIBLE` (422)."
        PRD 3.6: "- **REINSTATED** — available only against a dismissal: the case
        moves `DISMISSED → AWAITING_FORMAL_COMPLAINT` with `dismissal_reason` and
        `closed_at` cleared; `APPEAL_DECIDED` and `CASE_RESUMED` are appended."

        Design: Corner/validations/dismissal_appeal_reversed_incompatible_then_reinstated
        """
        cast = make_cast("comp", "resp", "coord", "ao")
        case = create_case(
            cast, categories=["SEXUAL_HARASSMENT"], received_via="EMAIL",
            occurred_in_program_activity=False,
        )
        begin_jurisdiction_review(case["id"], cast["coord"]["id"])
        dismiss_case(case["id"], cast["coord"]["id"],
                     dismissal_reason="MANDATORY_NO_JURISDICTION", refer_to_conduct=False)
        appeal = file_appeal(
            case["id"], cast["comp"]["id"], "COMPLAINANT", "DISMISSAL",
            ["PROCEDURAL_IRREGULARITY"], statement="Review the dismissal",
        )
        begin_appeal_review(appeal["id"], cast["coord"]["id"], cast["ao"]["id"])
        ao_h = make_appeal_officer_headers(cast["ao"]["id"])

        reversed_resp = api.decide_appeal(appeal["id"], {"outcome": "REVERSED"}, ao_h)
        validate_error(reversed_resp, ApiErrorId.ERR_APPEAL_OUTCOME_INCOMPATIBLE)
        still = validate_success(
            api.get_appeal(appeal["id"], make_coordinator_headers(cast["coord"]["id"]))
        )
        assert still["status"] == "UNDER_REVIEW"

        decided = decide_appeal(appeal["id"], cast["ao"]["id"], "REINSTATED")
        assert decided["status"] == "REINSTATED"

        case_after = get_case(case["id"], cast["coord"]["id"])
        assert case_after["status"] == "AWAITING_FORMAL_COMPLAINT"
        assert case_after.get("dismissal_reason") is None
        assert case_after.get("closed_at") is None

    def test_remand_scope_must_match_grounds(self, api):
        """PRD 3.6: "- **REMANDED** — the payload's `remand_scope` must be present
        and ground-compatible: `INVESTIGATION` is required whenever `grounds`
        includes `NEW_EVIDENCE`, and `HEARING_PREPARATION` is allowed only when
        the grounds are a subset of `PROCEDURAL_IRREGULARITY` and
        `CONFLICT_OF_INTEREST`; a mismatch is `ERR_REMAND_SCOPE_MISMATCH` (422)."

        Design: Corner/validations/remand_scope_must_match_grounds
        """
        cast = make_cast("comp", "resp", "coord", "inv", "dm", "ao", "advc", "advr")
        case = create_case(cast, categories=["OTHER_SEX_BASED"], received_via="EMAIL")
        drive_case_to_issued(case["id"], cast)
        appeal = file_appeal(
            case["id"], cast["resp"]["id"], "RESPONDENT", "DETERMINATION",
            ["PROCEDURAL_IRREGULARITY"], statement="Hearing notice was late",
        )
        begin_appeal_review(appeal["id"], cast["coord"]["id"], cast["ao"]["id"])
        ao_h = make_appeal_officer_headers(cast["ao"]["id"])

        # INVESTIGATION scope is reserved for NEW_EVIDENCE grounds.
        mismatch = api.decide_appeal(
            appeal["id"], {"outcome": "REMANDED", "remand_scope": "INVESTIGATION"}, ao_h
        )
        validate_error(mismatch, ApiErrorId.ERR_REMAND_SCOPE_MISMATCH)
        still = validate_success(
            api.get_appeal(appeal["id"], make_coordinator_headers(cast["coord"]["id"]))
        )
        assert still["status"] == "UNDER_REVIEW"

        decided = decide_appeal(
            appeal["id"], cast["ao"]["id"], "REMANDED", remand_scope="HEARING_PREPARATION"
        )
        assert decided["status"] == "REMANDED"
        case_after = get_case(case["id"], cast["coord"]["id"])
        assert case_after["status"] == "REMANDED"
        assert case_after["remand_target"] == "HEARING_PREPARATION"


class TestAssignedOfficerBinding:
    def test_unassigned_appeal_officer_cannot_decide(self, api):
        """PRD 3.6: "Deciding belongs exclusively to the assigned officer: any
        other actor is rejected with `ERR_NOT_ASSIGNED_APPEAL_OFFICER` (422)."

        Design: Corner/validations/unassigned_appeal_officer_cannot_decide
        """
        cast = make_cast("comp", "resp", "coord", "ao", "ao2")
        case = create_case(
            cast, categories=["SEXUAL_HARASSMENT"], received_via="EMAIL",
            occurred_in_program_activity=False,
        )
        begin_jurisdiction_review(case["id"], cast["coord"]["id"])
        dismiss_case(case["id"], cast["coord"]["id"],
                     dismissal_reason="MANDATORY_NO_JURISDICTION", refer_to_conduct=False)
        appeal = file_appeal(
            case["id"], cast["comp"]["id"], "COMPLAINANT", "DISMISSAL",
            ["NEW_EVIDENCE"], statement="We found the campus logs",
        )
        begin_appeal_review(appeal["id"], cast["coord"]["id"], cast["ao"]["id"])

        resp = api.decide_appeal(
            appeal["id"], {"outcome": "AFFIRMED"},
            make_appeal_officer_headers(cast["ao2"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_ASSIGNED_APPEAL_OFFICER)
        still = validate_success(
            api.get_appeal(appeal["id"], make_coordinator_headers(cast["coord"]["id"]))
        )
        assert still["status"] == "UNDER_REVIEW"
