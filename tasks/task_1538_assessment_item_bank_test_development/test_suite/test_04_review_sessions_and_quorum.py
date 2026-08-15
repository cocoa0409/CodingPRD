"""Review sessions: state rules, verdict requirements, quorum tally, SOD."""
from test_helpers import (
    ApiErrorId,
    get_success_data,
    validate_error,
    validate_paginated,
)
from test_helpers.fixtures import (
    CONTENT_REVIEWERS,
    PD_H,
    create_committee,
    create_draft_item,
    create_program,
    create_standard,
    read_item,
    run_review_session,
    submit_item,
)
from test_helpers.factories import create_session_payload, create_verdict_payload
from test_helpers.test_users import (
    make_bias_reviewer_headers,
    make_content_reviewer_headers,
)


def _open_session_with_item(api, program_id, item_id, committee_kind="CONTENT",
                            quorum_size=2):
    """Committee + session (scheduled at the clock's initial instant) + open."""
    committee = create_committee(program_id, committee_kind, quorum_size)
    session = get_success_data(api.create_review_session(
        create_session_payload(committee["id"], [item_id]), PD_H))
    get_success_data(api.open_review_session(session["id"], PD_H))
    return committee, session


class TestSessionStateRules:
    def test_session_close_before_open_returns_invalid_state(self, api):
        """PRD: "Closing a session requires it to be `OPEN`
        (`ERR_SESSION_NOT_OPEN` otherwise)"

        Design: Corner/state_machines/session_close_before_open_returns_invalid_state
        """
        program = create_program()
        standard = create_standard(program["id"])
        item = create_draft_item(program["id"], standard["id"], item_code="I-S")
        committee = create_committee(program["id"], "CONTENT", 2)
        session = get_success_data(api.create_review_session(
            create_session_payload(committee["id"], [item["id"]]), PD_H))
        resp = api.close_review_session(session["id"], PD_H)
        validate_error(resp, ApiErrorId.ERR_SESSION_NOT_OPEN)


class TestVerdictRequirements:
    def test_validation_rationale_required_on_reject(self, api):
        """PRD: "A `REJECT` or `REVISE` verdict must carry a `rationale` of at
        least 20 characters; a missing or too-short rationale is rejected with
        `ERR_RATIONALE_REQUIRED` (HTTP 400), while an `ACCEPT` verdict needs
        none."

        Design: Corner/validations/validation_rationale_required_on_reject
        """
        program = create_program()
        standard = create_standard(program["id"])
        item = create_draft_item(program["id"], standard["id"], item_code="I-R")
        submit_item(item)
        _committee, session = _open_session_with_item(
            api, program["id"], item["id"], "CONTENT")
        resp = api.submit_verdict(
            session["id"],
            create_verdict_payload(item["id"], "REJECT", rationale="short"),
            make_content_reviewer_headers("cr-solo"),
        )
        validate_error(resp, ApiErrorId.ERR_RATIONALE_REQUIRED)


class TestQuorumTally:
    def test_error_no_quorum_reached_on_close(self, api):
        """PRD: "every item must reach quorum as described below
        (`ERR_NO_QUORUM_REACHED`, HTTP 409, aborting the entire close)"
        PRD: "If none of these conditions holds, no quorum exists for that item
        and the close itself is rejected with `ERR_NO_QUORUM_REACHED`."

        Design: Corner/errors/error_no_quorum_reached_on_close
        """
        program = create_program()
        standard = create_standard(program["id"])
        item = create_draft_item(program["id"], standard["id"], item_code="I-NQ")
        submit_item(item)
        _committee, session = _open_session_with_item(
            api, program["id"], item["id"], "CONTENT", quorum_size=3)
        get_success_data(api.submit_verdict(
            session["id"], create_verdict_payload(item["id"], "ACCEPT"),
            make_content_reviewer_headers("cr-only")))
        resp = api.close_review_session(session["id"], PD_H)
        validate_error(resp, ApiErrorId.ERR_NO_QUORUM_REACHED)
        item_after = read_item(program["id"], item["id"])
        assert item_after["status"] == "CONTENT_REVIEW", (
            "the aborted close fires no item transition"
        )

    def test_quorum_accept_takes_priority_over_contested_reject(self, api):
        """PRD: "If the `ACCEPT` count reaches the committee's `quorum_size`,
        the outcome is acceptance. Otherwise, if the `REJECT` count reaches
        quorum and is at least the sum of the `ACCEPT` and `REVISE` counts, the
        outcome is rejection."
        (With quorum 2 and two ACCEPT plus two REJECT verdicts, both branches'
        numeric conditions hold; the `Otherwise` ordering resolves to
        acceptance.)

        Design: Corner/calculations/quorum_accept_takes_priority_over_contested_reject
        """
        program = create_program()
        standard = create_standard(program["id"])
        item = create_draft_item(program["id"], standard["id"], item_code="I-Q")
        submit_item(item)
        session = get_success_data(api.create_review_session(
            create_session_payload(
                create_committee(program["id"], "CONTENT", 2)["id"],
                [item["id"]]),
            PD_H))
        get_success_data(api.open_review_session(session["id"], PD_H))
        verdicts = [("cr-a", "ACCEPT"), ("cr-b", "ACCEPT"),
                    ("cr-c", "REJECT"), ("cr-d", "REJECT")]
        for reviewer, verdict in verdicts:
            payload = create_verdict_payload(item["id"], verdict)
            if verdict != "ACCEPT":
                payload["rationale"] = "Grounds for rejection explained at length."
            get_success_data(api.submit_verdict(
                session["id"], payload, make_content_reviewer_headers(reviewer)))
        get_success_data(api.close_review_session(session["id"], PD_H))
        item_after = read_item(program["id"], item["id"])
        assert item_after["status"] == "BIAS_REVIEW", (
            "ACCEPT at quorum wins over a contested REJECT at quorum"
        )
        assert item_after["content_review_outcome"] == "PASSED"


class TestSegregationOfDuties:
    def test_rbac_segregation_of_duties_same_user_both_roles(self, api):
        """PRD: "The same `X-User-ID` may not cast a verdict on the same item
        in both a `CONTENT` committee session and a `BIAS_SENSITIVITY`
        committee session within the same revision cycle; an attempt to do so
        is rejected with `ERR_SOD_REVIEWER_CONFLICT` (HTTP 403)."

        Design: Corner/roles/rbac_segregation_of_duties_same_user_both_roles
        """
        program = create_program()
        standard = create_standard(program["id"])
        item = create_draft_item(program["id"], standard["id"], item_code="I-SOD")
        submit_item(item)
        # User "dual-1" casts an ACCEPT in the CONTENT session.
        run_review_session(program["id"], item["id"], "CONTENT",
                           verdicts=("ACCEPT", "ACCEPT"),
                           reviewers=("dual-1", CONTENT_REVIEWERS[0]))
        # The same user now attempts a verdict in the BIAS_SENSITIVITY session.
        _committee, bias_session = _open_session_with_item(
            api, program["id"], item["id"], "BIAS_SENSITIVITY")
        resp = api.submit_verdict(
            bias_session["id"], create_verdict_payload(item["id"], "ACCEPT"),
            make_bias_reviewer_headers("dual-1"))
        validate_error(resp, ApiErrorId.ERR_SOD_REVIEWER_CONFLICT)

    def test_sod_conflict_vs_rationale_missing_priority(self, api):
        """PRD: "Business-safety gates come after state checks, in this
        sequence: scoped access-grant coverage (`ERR_NO_ACTIVE_GRANT`), then
        reviewer segregation of duties (`ERR_SOD_REVIEWER_CONFLICT`), then the
        bias gate (`ERR_BIAS_GATE_NOT_PASSED`). ... variant-kind consistency
        (`ERR_VARIANT_KIND_MISMATCH`) before the verdict rationale requirement
        (`ERR_RATIONALE_REQUIRED`)"
        (The segregation check is evaluated ahead of the rationale check, so a
        conflicted reviewer casting a rationale-less REJECT gets the SOD
        error.)

        Design: Difficulty/priority_pair_validation_conflict/sod_conflict_vs_rationale_missing_priority
        """
        program = create_program()
        standard = create_standard(program["id"])
        item = create_draft_item(program["id"], standard["id"], item_code="I-SP")
        submit_item(item)
        run_review_session(program["id"], item["id"], "CONTENT",
                           verdicts=("ACCEPT", "ACCEPT"),
                           reviewers=("dual-9", CONTENT_REVIEWERS[1]))
        _committee, bias_session = _open_session_with_item(
            api, program["id"], item["id"], "BIAS_SENSITIVITY")
        # Both violations present: same user across kinds AND no rationale.
        resp = api.submit_verdict(
            bias_session["id"],
            create_verdict_payload(item["id"], "REJECT"),
            make_bias_reviewer_headers("dual-9"))
        validate_error(resp, ApiErrorId.ERR_SOD_REVIEWER_CONFLICT)

    def test_sod_conflict_fires_even_with_valid_rationale(self, api):
        """PRD: "The same `X-User-ID` may not cast a verdict on the same item
        in both a `CONTENT` committee session and a `BIAS_SENSITIVITY`
        committee session within the same revision cycle; an attempt to do so
        is rejected with `ERR_SOD_REVIEWER_CONFLICT` (HTTP 403)."
        (The rationale is well-formed here, so only the segregation rule can
        fire — isolating it from the rationale requirement.)

        Design: Difficulty/priority_pair_validation_conflict/sod_conflict_vs_rationale_missing_priority
        """
        program = create_program()
        standard = create_standard(program["id"])
        item = create_draft_item(program["id"], standard["id"], item_code="I-SP2")
        submit_item(item)
        run_review_session(program["id"], item["id"], "CONTENT",
                           verdicts=("ACCEPT", "ACCEPT"),
                           reviewers=("dual-7", CONTENT_REVIEWERS[0]))
        _committee, bias_session = _open_session_with_item(
            api, program["id"], item["id"], "BIAS_SENSITIVITY")
        resp = api.submit_verdict(
            bias_session["id"],
            create_verdict_payload(item["id"], "REJECT",
                                   rationale="A fully articulated rationale text."),
            make_bias_reviewer_headers("dual-7"))
        validate_error(resp, ApiErrorId.ERR_SOD_REVIEWER_CONFLICT)


class TestSessionCancelConservation:
    def _setup_cancelled_session(self, api, program, item):
        """Open a CONTENT session, cast 2 ACCEPT verdicts, cancel it."""
        committee = create_committee(program["id"], "CONTENT", 2)
        session1 = get_success_data(api.create_review_session(
            create_session_payload(committee["id"], [item["id"]]), PD_H))
        get_success_data(api.open_review_session(session1["id"], PD_H))
        for reviewer in ("u-alpha", "u-beta"):
            get_success_data(api.submit_verdict(
                session1["id"], create_verdict_payload(item["id"], "ACCEPT"),
                make_content_reviewer_headers(reviewer)))
        cancelled = get_success_data(
            api.cancel_review_session(session1["id"], PD_H))
        assert cancelled["status"] == "CANCELLED"
        return committee, session1

    def test_cancelled_session_verdicts_do_not_count_toward_quorum(self, api):
        """PRD: "cancelling an `OPEN` session additionally soft-deletes every
        verdict cast in it by setting `soft_deleted`, so those verdicts are
        excluded from the quorum tally of any subsequent session that hears
        the same items."
        PRD: "every item on the agenda must have at least one verdict
        (`ERR_INCOMPLETE_AGENDA`, HTTP 409)"

        Design: Difficulty/compensating_invariant/quorum_tally_verdict_conservation_across_session_cancel
        """
        program = create_program()
        standard = create_standard(program["id"])
        item = create_draft_item(program["id"], standard["id"], item_code="I-Q2")
        submit_item(item)
        committee, _session1 = self._setup_cancelled_session(api, program, item)
        # A fresh session on the same item starts with zero counted verdicts.
        session2 = get_success_data(api.create_review_session(
            create_session_payload(committee["id"], [item["id"]]), PD_H))
        get_success_data(api.open_review_session(session2["id"], PD_H))
        resp = api.close_review_session(session2["id"], PD_H)
        validate_error(resp, ApiErrorId.ERR_INCOMPLETE_AGENDA)
        item_after = read_item(program["id"], item["id"])
        assert item_after["status"] == "CONTENT_REVIEW", (
            "soft-deleted verdicts contribute nothing to the new session"
        )

    def test_cancelled_session_verdicts_are_soft_deleted(self, api):
        """PRD: "cancelling an `OPEN` session additionally soft-deletes every
        verdict cast in it by setting `soft_deleted`"

        Design: Difficulty/compensating_invariant/quorum_tally_verdict_conservation_across_session_cancel
        """
        program = create_program()
        standard = create_standard(program["id"])
        item = create_draft_item(program["id"], standard["id"], item_code="I-Q3")
        submit_item(item)
        _committee, session1 = self._setup_cancelled_session(api, program, item)
        data, meta = validate_paginated(api.list_review_verdicts(
            PD_H, params={"session_id": session1["id"]}))
        assert meta["total_count"] == 2
        assert all(v["soft_deleted"] is True for v in data), (
            "every verdict of the cancelled session is soft-deleted"
        )
