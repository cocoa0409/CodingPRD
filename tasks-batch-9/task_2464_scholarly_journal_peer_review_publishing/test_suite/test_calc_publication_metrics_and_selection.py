"""Quantities derived at publication, at metrics read time and by the reviewer selector."""

from test_helpers import assertions as a
from test_helpers import fixtures as fx
from test_helpers.constants import CLOCK_EPOCH_MS


def _setup_green_route_ready_to_publish(embargo_months=6):
    """An accepted `GREEN_SELF_ARCHIVE` paper cleared for publication.

    The green licence multiplier is 0.00, so the invoice computes to a
    `total_due_cents` of 0; it is waived so that the manuscript carries no
    invoice left at `ISSUED` when publication is attempted.
    """
    world = fx.setup_in_production(
        journal_overrides={"embargo_months": embargo_months},
        manuscript_overrides={"oa_license": "GREEN_SELF_ARCHIVE"},
    )
    job_id = world["job"]["id"]
    invoice = fx.issue_invoice(
        world["manuscript"]["id"], page_charge_count=0, color_figure_count=0
    )
    fx.waive_invoice(
        invoice["id"], waiver_reason="Green self-archiving route carries no charge."
    )
    world["invoice"] = fx.get_invoice(invoice["id"])
    fx.book_typeset_slot(job_id, "2026-08-20", "2026-08-22")
    fx.advance_content(job_id, "TYPESETTING")
    fx.advance_content(job_id, "PROOF_SENT")
    fx.approve_proof(job_id, world["author_headers"], True)
    fx.record_archival_deposit(job_id)
    world["job"] = fx.get_production_job(job_id)
    return world


def _setup_populated_metrics_journal():
    """One journal holding one accepted manuscript and one desk-rejected one.

    The accepted manuscript is submitted at the clock epoch and decided nine
    days later; it carries two invitations, one delivered and one declined.
    """
    world = fx.setup_under_review_manuscript(
        journal_overrides={"min_completed_reviews_for_decision": 1}
    )
    accepted = world["manuscript"]
    desk_rejected = fx.create_manuscript(
        world["journal"]["id"],
        world["author"],
        world["author_headers"],
        page_count=14,
        figure_count=1,
    )

    delivering, delivering_headers = fx.create_reviewer()
    declining, declining_headers = fx.create_reviewer()
    delivered_invitation = fx.invite_reviewer(
        accepted["id"], world["handling_headers"], reviewer_id=delivering["id"]
    )
    declined_invitation = fx.invite_reviewer(
        accepted["id"], world["handling_headers"], reviewer_id=declining["id"]
    )
    fx.accept_invitation(delivered_invitation["id"], delivering_headers)
    fx.decline_invitation(
        declined_invitation["id"], declining_headers, decline_reason="Outside my area."
    )
    fx.submit_review(delivered_invitation["id"], delivering_headers, "ACCEPT")

    fx.set_clock("2026-08-10T00:00:00Z")
    world["decision"] = fx.issue_decision(accepted["id"], world["handling_headers"])

    fx.file_plagiarism_screening(desk_rejected["id"], 5.0)
    assignment = fx.assign_editor(
        desk_rejected["id"], world["chief_headers"], editor_id=world["handling"]["id"]
    )
    fx.declare_no_conflict(assignment["id"], world["handling_headers"])
    fx.desk_reject(desk_rejected["id"], world["handling_headers"])

    world["accepted"] = fx.get_manuscript(accepted["id"])
    world["desk_rejected"] = fx.get_manuscript(desk_rejected["id"])
    world["metrics"] = fx.get_journal_metrics(world["journal"]["id"])
    return world


def _setup_reliability_ranked_pool(with_open_load_on_the_leader=False):
    """Two reviewers, one with a perfect on-time delivery and one untouched.

    The proven reviewer's rolling score is 100 * (1 * 0.45 + 1 * 0.35 + 1 * 0.20)
    with no lateness penalty, that is 100.00; the untouched reviewer sits at the
    50.00 registration seed. A further manuscript is left open with no
    invitations so that the selector has to rank the pool for it.
    """
    world = fx.setup_under_review_manuscript()
    proven, proven_headers = fx.create_reviewer()
    untouched, untouched_headers = fx.create_reviewer()
    fx.deliver_review(
        world["manuscript"]["id"], world["handling_headers"], proven, "ACCEPT"
    )

    if with_open_load_on_the_leader:
        warm_up = fx.add_manuscript_under_review(world)
        fx.invite_reviewer(
            warm_up["id"], world["handling_headers"], reviewer_id=proven["id"]
        )
        world["warm_up"] = warm_up

    world["target"] = fx.add_manuscript_under_review(world)
    world["proven"] = fx.get_reviewer(proven["id"])
    world["proven_headers"] = proven_headers
    world["untouched"] = fx.get_reviewer(untouched["id"])
    world["untouched_headers"] = untouched_headers
    return world


def test_green_route_embargo_clamps_to_the_last_day_of_a_shorter_month():
    """A 31 August publication under a six-month embargo lands on 28 February.

    PRD: "For a `GREEN_SELF_ARCHIVE` manuscript, the target month is the `publication_date`'s month advanced by the journal's `embargo_months`, normalised into a calendar year and month, and the `embargo_end_date` is that year and month with the day taken as the smaller of the `publication_date`'s day-of-month and the last calendar day of the target month — so a publication on the 31st clamps down to the last day of a shorter target month rather than spilling into the next one."

    Design: Corner/calculations/green_license_embargo_end_date_clamps_to_end_of_month
    """
    world = _setup_green_route_ready_to_publish(embargo_months=6)

    fx.publish_article(world["job"]["id"], "2026-08-31", issue_label="2026-08")

    manuscript = fx.get_manuscript(world["manuscript"]["id"])
    a.assert_date_only(manuscript["embargo_end_date"])
    a.assert_fields(
        manuscript,
        oa_license="GREEN_SELF_ARCHIVE",
        publication_date="2026-08-31",
        embargo_end_date="2027-02-28",
    )


def test_green_self_archive_invoice_carries_no_article_processing_charge():
    """The 0.00 licence multiplier zeroes the base and therefore the whole invoice.

    PRD: "The multipliers are 1.00 for `CC_BY`, 0.90 for `CC_BY_NC`, 0.85 for `CC_BY_NC_ND` and 0.00 for `GREEN_SELF_ARCHIVE` — the green self-archiving route carries no article processing charge at all."

    Design: Corner/calculations/green_license_embargo_end_date_clamps_to_end_of_month
    """
    world = _setup_green_route_ready_to_publish()

    a.assert_fields(world["invoice"], license_at_issue="GREEN_SELF_ARCHIVE")
    a.assert_invoice_amounts(world["invoice"], base_cents=0, total_due_cents=0)


def test_publication_stores_the_issue_date_and_moves_the_manuscript_to_published():
    """The publication call is what carries the paper out of production.

    PRD: "On success the manuscript moves `IN_PRODUCTION → PUBLISHED`, its `publication_date` is stored, its `doi` is minted as the journal's `doi_prefix`, then a solidus, then the job's `issue_label`, then a full stop, then the manuscript's `journal_sequence_number` left-padded with zeros to four digits, and its `embargo_end_date` is projected."

    Design: Corner/calculations/green_license_embargo_end_date_clamps_to_end_of_month
    """
    world = _setup_green_route_ready_to_publish()

    fx.publish_article(world["job"]["id"], "2026-08-31", issue_label="2026-08")

    a.assert_fields(
        fx.get_manuscript(world["manuscript"]["id"]),
        status="PUBLISHED",
        publication_date="2026-08-31",
    )


def test_publication_indexes_the_job_at_the_current_clock_instant():
    """Indexing is stamped from the logical clock, not from the issue date.

    PRD: "The job's `indexing_status` becomes `INDEXED` and its `published_at` is set to the current clock instant."

    Design: Corner/calculations/green_license_embargo_end_date_clamps_to_end_of_month
    """
    world = _setup_green_route_ready_to_publish()

    fx.publish_article(world["job"]["id"], "2026-08-31", issue_label="2026-08")

    job = fx.get_production_job(world["job"]["id"])
    a.assert_timestamp_with_millis(job["published_at"])
    a.assert_fields(job, indexing_status="INDEXED", published_at=CLOCK_EPOCH_MS)


def test_metrics_count_every_manuscript_of_the_journal_in_any_status():
    """A desk-rejected paper still belongs to the scoring universe.

    PRD: "The scoring universe is every manuscript of that journal, in any status."

    PRD: "`desk_rejected_count` counts those at `DESK_REJECTED`."

    Design: Corner/calculations/journal_metrics_rates_and_median_on_populated_journal
    """
    world = _setup_populated_metrics_journal()

    a.assert_fields(
        world["metrics"],
        submitted_count=2,
        desk_rejected_count=1,
        published_count=0,
        retracted_count=0,
    )


def test_acceptance_rate_divides_the_accepted_set_by_the_decided_set():
    """One in-production paper against one in-production plus one desk-rejected is 50.00.

    PRD: "`acceptance_rate_pct` divides the accepted set — manuscripts at `IN_PRODUCTION`, `PUBLISHED`, `CORRECTED` or `RETRACTED` — by the decided set — manuscripts at `DESK_REJECTED`, `REJECTED`, `IN_PRODUCTION`, `PUBLISHED`, `CORRECTED` or `RETRACTED` — multiplies by 100 and rounds half up to 2 decimal places, yielding 0.00 when the decided set is empty; a retracted article still counts as accepted in both the numerator and the denominator, because it was accepted."

    Design: Corner/calculations/journal_metrics_rates_and_median_on_populated_journal
    """
    world = _setup_populated_metrics_journal()

    assert world["accepted"]["status"] == "IN_PRODUCTION"
    assert world["desk_rejected"]["status"] == "DESK_REJECTED"
    a.assert_score_equals(
        world["metrics"]["acceptance_rate_pct"], 50.00, label="acceptance_rate_pct"
    )


def test_first_decision_median_reads_only_manuscripts_that_hold_a_decision():
    """Nine elapsed days on the only decided manuscript give a median of 9.

    PRD: "`median_days_to_first_decision` is built from every manuscript of the journal whose `decision_count` is greater than 0: for each, the elapsed milliseconds from the manuscript's `created_at` to the `created_at` of its earliest decision are divided by 86,400,000 and rounded **up** to a whole number of days; those day counts are sorted ascending; with an odd number of entries the median is the middle one, and with an even number it is the mean of the two middle ones rounded half up to 2 decimal places."

    Design: Corner/calculations/journal_metrics_rates_and_median_on_populated_journal
    """
    world = _setup_populated_metrics_journal()

    assert world["accepted"]["created_at"] == CLOCK_EPOCH_MS
    assert world["accepted"]["decision_count"] == 1
    assert world["metrics"]["median_days_to_first_decision"] == 9, (
        "2026-08-01T00:00:00Z to 2026-08-10T00:00:00Z is exactly nine days: "
        f"got {world['metrics']['median_days_to_first_decision']}"
    )


def test_invitation_acceptance_rate_counts_accepted_and_submitted_invitations():
    """One delivered and one declined invitation give 50.00, and nobody is on probation.

    PRD: "`reviewer_invitation_acceptance_rate_pct` takes every invitation belonging to that journal's manuscripts, divides the number in state `ACCEPTED` or `SUBMITTED` by the total, multiplies by 100 and rounds half up to 2 decimal places, yielding 0.00 when there are no invitations."

    PRD: "`reviewers_on_probation_count` counts reviewers whose `status` is `PROBATION` across the entire society database rather than per journal, since the database is shared."

    Design: Corner/calculations/journal_metrics_rates_and_median_on_populated_journal
    """
    world = _setup_populated_metrics_journal()

    a.assert_score_equals(
        world["metrics"]["reviewer_invitation_acceptance_rate_pct"],
        50.00,
        label="reviewer_invitation_acceptance_rate_pct",
    )
    assert world["metrics"]["reviewers_on_probation_count"] == 0, (
        "a single declined invitation is below the three-closed-invitation "
        "minimum-evidence bar for probation"
    )


def test_selector_prefers_the_higher_rolling_reliability_score():
    """A proven reviewer at 100.00 outranks an untouched one at the 50.00 seed.

    PRD: "Candidates are ranked by `reliability_score_rolling` descending, compared at its stored two-decimal precision, then by `open_invitation_count` ascending, then by `created_at` ascending; the first row after sorting wins."

    Design: Corner/calculations/reviewer_selector_ranks_by_reliability_then_open_load
    """
    world = _setup_reliability_ranked_pool()

    a.assert_score_equals(world["proven"]["reliability_score_rolling"], 100.00)
    a.assert_score_equals(world["untouched"]["reliability_score_rolling"], 50.00)

    invitation = fx.invite_reviewer(world["target"]["id"], world["handling_headers"])

    assert invitation["reviewer_id"] == world["proven"]["id"], (
        "the selector must take the 100.00 reviewer, not the 50.00 seeded one"
    )


def test_selector_stamps_its_own_choice_as_selector_at_the_current_round():
    """A server-chosen invitation is born at INVITED, in round 0, marked SELECTOR.

    PRD: "The invitation begins at `INVITED`, records `selected_by` as `EXPLICIT` when the request named a reviewer and `SELECTOR` when the server chose one, and carries `reminder_count` 0, `last_reminder_at` absent, `responded_at` absent, `decline_reason` absent and `closed_reason` absent."

    Design: Corner/calculations/reviewer_selector_ranks_by_reliability_then_open_load
    """
    world = _setup_reliability_ranked_pool()

    invitation = fx.invite_reviewer(world["target"]["id"], world["handling_headers"])

    a.assert_fields(
        invitation, state="INVITED", selected_by="SELECTOR", round=0, reminder_count=0
    )
    assert fx.get_reviewer(world["proven"]["id"])["open_invitation_count"] == 1
    assert fx.get_reviewer(world["untouched"]["id"])["open_invitation_count"] == 0


def test_reliability_outranks_open_invitation_load_in_the_selector():
    """Open load only breaks ties, so a busy 100.00 reviewer still beats an idle 50.00 one.

    PRD: "Candidates are ranked by `reliability_score_rolling` descending, compared at its stored two-decimal precision, then by `open_invitation_count` ascending, then by `created_at` ascending; the first row after sorting wins."

    Design: Corner/calculations/reviewer_selector_ranks_by_reliability_then_open_load
    """
    world = _setup_reliability_ranked_pool(with_open_load_on_the_leader=True)

    assert world["proven"]["open_invitation_count"] == 1
    assert world["untouched"]["open_invitation_count"] == 0

    invitation = fx.invite_reviewer(world["target"]["id"], world["handling_headers"])

    assert invitation["reviewer_id"] == world["proven"]["id"], (
        "reliability is the primary sort key and open load only the tie-breaker"
    )
