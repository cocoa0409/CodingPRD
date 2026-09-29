"""
Quality assurance: the revision loop, the churn counter and the escalation flag.

PRD §3.3: "The revision loop `DRAFT → SUBMITTED → IN_QA → DRAFT` may run any
number of times."
"""

from test_helpers import assertions as a
from test_helpers import fixtures as fx


def _submit_claim_and_decide(client, inspection_id, roster, decision):
    """One full pass of the review loop at the field-day clock."""
    fx.set_clock(client, "2026-09-02T12:00:00Z")
    fx.submit_report(client, inspection_id, roster)
    fx.qa_claim(client, inspection_id, roster)
    return fx.qa_decide(client, inspection_id, roster, decision)


def test_a_returned_report_goes_back_to_draft_and_releases_its_claim(
    client, roster, bridge
):
    """
    The first return sends the report back for rework, counts the churn once and
    hands the claim back so any qualified reviewer can pick up the next pass.

    PRD §3.3: "A `RETURN` decision — which may carry an optional `return_note` —
    sends the report from `IN_QA` back to `DRAFT`, increments `returned_count` by
    one, and clears `qa_reviewer_id` back to null so that any qualified reviewer
    may claim the next submission."
    PRD §3.3: "Each return also re-evaluates `qa_escalation_required`, which
    becomes true once `returned_count` has reached 2 or more".

    Design: Difficulty/non_linear_state_machine/inspection_qa_return_revision_cycle_second_pass
    """
    draft = fx.draft_report_with_baseline(client, bridge["id"], roster)

    returned = _submit_claim_and_decide(
        client, draft["inspection"]["id"], roster, "RETURN"
    )

    assert returned["status"] == "DRAFT"
    assert returned["returned_count"] == 1
    assert returned["qa_reviewer_id"] is None
    assert returned["qa_escalation_required"] is False


def test_the_second_return_raises_the_escalation_flag(client, roster, bridge):
    """
    Churn is cumulative: the escalation flag turns on at the second return, not
    the first.

    PRD §3.3: "Each return also re-evaluates `qa_escalation_required`, which
    becomes true once `returned_count` has reached 2 or more; from that point the
    report's acceptance is understood to require district-engineer involvement,
    and the flag exists so that supervision can see which reports have churned."

    Design: Difficulty/non_linear_state_machine/inspection_qa_return_revision_cycle_second_pass
    """
    draft = fx.draft_report_with_baseline(client, bridge["id"], roster)
    inspection_id = draft["inspection"]["id"]

    first = _submit_claim_and_decide(client, inspection_id, roster, "RETURN")
    assert first["returned_count"] == 1
    assert first["qa_escalation_required"] is False

    second = _submit_claim_and_decide(client, inspection_id, roster, "RETURN")

    assert second["status"] == "DRAFT"
    assert second["returned_count"] == 2
    assert second["qa_escalation_required"] is True
    assert second["qa_reviewer_id"] is None


def test_the_churn_counter_survives_the_acceptance_that_ends_the_loop(
    client, roster, bridge
):
    """
    A third pass ending in acceptance closes the report without rewriting its
    history: the return count and the escalation flag both stand.

    PRD §3.3: "An `ACCEPT` decision takes the report from `IN_QA` to `ACCEPTED`,
    stamps `accepted_at` from the logical clock, and triggers the five-hop
    publication cascade that is the structural heart of this system."
    PRD §3.3: "Each return also re-evaluates `qa_escalation_required`, which
    becomes true once `returned_count` has reached 2 or more".

    Design: Difficulty/non_linear_state_machine/inspection_qa_return_revision_cycle_second_pass
    """
    draft = fx.draft_report_with_baseline(client, bridge["id"], roster)
    inspection_id = draft["inspection"]["id"]

    _submit_claim_and_decide(client, inspection_id, roster, "RETURN")
    _submit_claim_and_decide(client, inspection_id, roster, "RETURN")
    accepted = _submit_claim_and_decide(client, inspection_id, roster, "ACCEPT")

    assert accepted["status"] == "ACCEPTED"
    assert accepted["returned_count"] == 2, "the return count is never reset"
    assert accepted["qa_escalation_required"] is True
    a.assert_instant_equals(
        accepted["accepted_at"], "2026-09-02T12:00:00Z", "accepted_at"
    )


def test_every_submission_recomputes_the_same_health_index_from_the_same_rows(
    client, roster, bridge
):
    """
    The condition arithmetic is recomputed and frozen on each submission, and
    because the element rows never changed between passes the health index reads
    65.47 every time.

    PRD §3.3: "Submission moves the report from `DRAFT` to `SUBMITTED` and is the
    point at which the report's condition arithmetic is computed and frozen for
    review."
    PRD §3.3: "For a report carrying deck 82.00, girder 40.00, bearing 50.00 and
    abutment 95.00, the weights sum to 0.30 plus 0.25 plus 0.10 plus 0.10, which
    is 0.75; the weighted scores sum to 24.60 plus 10.00 plus 5.00 plus 9.50,
    which is 49.10; and 49.10 divided by 0.75 is 65.4666…, giving 65.47."

    Design: Difficulty/non_linear_state_machine/inspection_qa_return_revision_cycle_second_pass
    """
    draft = fx.draft_report_with_baseline(client, bridge["id"], roster)
    inspection_id = draft["inspection"]["id"]

    fx.set_clock(client, "2026-09-02T12:00:00Z")
    first_submission = fx.submit_report(client, inspection_id, roster)
    assert first_submission["bridge_health_index"] == 65.47
    fx.qa_claim(client, inspection_id, roster)
    fx.qa_decide(client, inspection_id, roster, "RETURN")

    second_submission = fx.submit_report(client, inspection_id, roster)
    assert second_submission["bridge_health_index"] == 65.47
    fx.qa_claim(client, inspection_id, roster)
    fx.qa_decide(client, inspection_id, roster, "RETURN")

    third_submission = fx.submit_report(client, inspection_id, roster)
    assert third_submission["bridge_health_index"] == 65.47
    for submission in (first_submission, second_submission, third_submission):
        assert submission["computed_deck_rating"] == 7
        assert submission["computed_superstructure_rating"] == 3
        assert submission["computed_substructure_rating"] == 8
        a.assert_two_decimals(submission["bridge_health_index"], "bridge_health_index")


def test_a_report_that_churned_twice_still_publishes_its_data_on_acceptance(
    client, roster, bridge
):
    """
    Churn does not degrade the publication: the accepted report writes the same
    component ratings, health index and frequency through to the structure as a
    clean first-pass acceptance would.

    PRD §3.3: "the structure's corresponding component rating — `deck_rating`,
    `superstructure_rating` or `substructure_rating` — is overwritten from the
    report's matching computed rating".
    PRD §3.3: "The structure's `min_nbi_rating` is then recomputed as the smallest
    of the three component ratings, its `bridge_health_index` is copied from the
    report's".
    PRD §3.3: "If the accepted report was `ROUTINE`, the structure's
    `last_routine_inspection_date` is set to the report's `inspection_date` and
    `next_inspection_due_date` becomes that date advanced by the new
    `inspection_interval_months`."

    Design: Difficulty/non_linear_state_machine/inspection_qa_return_revision_cycle_second_pass
    """
    draft = fx.draft_report_with_baseline(client, bridge["id"], roster)
    inspection_id = draft["inspection"]["id"]

    _submit_claim_and_decide(client, inspection_id, roster, "RETURN")
    _submit_claim_and_decide(client, inspection_id, roster, "RETURN")
    _submit_claim_and_decide(client, inspection_id, roster, "ACCEPT")

    structure = fx.read_bridge(client, bridge["id"])
    assert structure["deck_rating"] == 7
    assert structure["superstructure_rating"] == 3
    assert structure["substructure_rating"] == 8
    assert structure["min_nbi_rating"] == 3
    assert structure["bridge_health_index"] == 65.47
    assert structure["inspection_interval_months"] == 12
    a.assert_date_equals(
        structure["last_routine_inspection_date"],
        "2026-09-02",
        "last_routine_inspection_date",
    )
    a.assert_date_equals(
        structure["next_inspection_due_date"], "2027-09-02", "next_inspection_due_date"
    )
