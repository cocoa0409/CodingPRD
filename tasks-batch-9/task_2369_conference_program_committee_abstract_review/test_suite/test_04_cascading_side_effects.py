"""Cascading side effects across the program pipeline.

Three chains of consequence are exercised here, each begun by a different act of
conference administration:

* a disclosure that is rejected after it had already been accepted unwinds the
  continuing-education credit it supported — the accreditation is revoked, the
  accrediting body's minutes come back into the pool, and the accredited session
  that was already on the public program falls back to a planning draft;
* a presenter who never appears at their slot has the absence recorded against
  the abstract and against their own conduct record, which moves them onto the
  first rung of the sanction ladder;
* a committee member suspended mid-round has their live reviews voided, their
  workload emptied and the orphaned abstract handed to the best-matching
  reviewer still available.
"""

import pytest

from test_helpers import (
    ADMIN,
    accreditation_validation_payload,
    api_client,
    assert_cme_pool_conserved,
    assert_format_capacity_within_bounds,
    assert_four_decimal_places,
    assert_quarter_credit_step,
    assert_reviewer_load_within_ceiling,
    assert_two_decimal_places,
    add_slot,
    create_accreditation_payload,
    create_active_member,
    create_disclosure_statement_payload,
    create_session,
    disclosure_adjudication_payload,
    get_success_data,
    set_clock,
    setup_abstract_under_review,
    setup_confirmed_abstract,
    setup_scheduled_slot,
    status_transition_payload,
    validate_paginated,
    validate_success,
)

# ─────────────────────────────────────────────────────────────────────────
# Local state builders. Every test calls one of these against an empty
# database, so no state is shared between tests.
# ─────────────────────────────────────────────────────────────────────────


def _published_accredited_session(content_minutes: int = 45, duration_minutes: int = 30):
    """One confirmed oral abstract carrying a validated 45-minute accreditation,
    placed into a CME-designated session that is then published."""
    world = setup_confirmed_abstract(
        decision="ORAL",
        category_overrides={"cme_eligible": True, "min_reviews_required": 2},
    )
    abstract = world["abstracts"][0]
    accreditation = get_success_data(
        api_client.create_accreditation(
            create_accreditation_payload(abstract["id"], content_minutes),
            world["second_chair_headers"],
        )
    )
    disclosure = get_success_data(
        api_client.create_disclosure_statement(
            create_disclosure_statement_payload(
                abstract["id"],
                accreditation["id"],
                world["authors"]["ada"]["id"],
                has_financial_relationship=False,
            ),
            world["author_headers"],
        )
    )
    world["disclosure"] = get_success_data(
        api_client.adjudicate_disclosure_statement(
            disclosure["id"],
            disclosure_adjudication_payload("VALIDATED"),
            world["second_chair_headers"],
        )
    )
    world["accreditation"] = get_success_data(
        api_client.validate_accreditation(
            accreditation["id"],
            accreditation_validation_payload("VALIDATE"),
            world["second_chair_headers"],
        )
    )
    session = create_session(world, chair_key="cho", cme_designated=True)
    add_slot(
        world,
        session,
        abstract["id"],
        world["authors"]["ada"]["id"],
        duration_minutes=duration_minutes,
    )
    world["sessions"][0] = get_success_data(
        api_client.transition_session(
            session["id"], status_transition_payload("PUBLISHED"), world["chair_headers"]
        )
    )
    return world


def _reject_the_validated_disclosure(world):
    return api_client.adjudicate_disclosure_statement(
        world["disclosure"]["id"],
        disclosure_adjudication_payload(
            "REJECTED",
            rejection_reason="undisclosed advisory relationship surfaced after validation",
        ),
        world["second_chair_headers"],
    )


def _published_session_after_its_window_closed():
    """One confirmed oral abstract scheduled into a published session, with the
    clock moved past the session's end so the outcome can be recorded."""
    world = setup_scheduled_slot(
        category_overrides={"cme_eligible": False}, duration_minutes=25
    )
    world["sessions"][0] = get_success_data(
        api_client.transition_session(
            world["sessions"][0]["id"],
            status_transition_payload("PUBLISHED"),
            world["chair_headers"],
        )
    )
    set_clock("2026-09-01T10:05:00Z")
    return world


def _record_the_no_show(world):
    return api_client.transition_session_slot(
        world["slots"][0]["id"],
        status_transition_payload("NO_SHOW_RECORDED", reason="presenter never appeared"),
        world["chair_headers"],
    )


def _panel_with_one_spare_reviewer():
    """An abstract under review with two assigned reviews, plus a third active
    reviewer whose expertise overlaps the abstract's keywords."""
    world = setup_abstract_under_review(
        category_overrides={"cme_eligible": False},
        abstract_overrides={"keywords": ["oncology", "immunotherapy", "imaging"]},
        second_reviewer_keywords=["oncology", "genomics"],
    )
    world["members"]["nadia"] = create_active_member(
        world["conference"]["id"],
        "Nadia Lund",
        "nadia@panel.example",
        member_role="REVIEWER",
        expertise_keywords=["oncology", "immunotherapy"],
        max_review_load=4,
    )
    return world


def _suspend(member_id):
    return api_client.transition_committee_member(
        member_id,
        status_transition_payload("SUSPENDED", reason="unresponsive for four weeks"),
        ADMIN,
    )


# ─────────────────────────────────────────────────────────────────────────
# A rejected disclosure unwinds the credit it once supported
# ─────────────────────────────────────────────────────────────────────────


def test_rejected_disclosure_revokes_the_accreditation_it_supported():
    """Cascade A starts when an already-validated disclosure is later rejected. The disclosure becomes `REJECTED`; the accreditation it supported moves from `VALIDATED` to `REVOKED` and its `awarded_credits` returns to 0.00; the conference's `cme_minutes_allocated` drops by that accreditation's `content_minutes`, `cme_minutes_available` is recomputed and the conference's `version` advances; the session holding a counted slot for that abstract recomputes `accredited_credit_total` and `accreditation_posture`; and if that session is `cme_designated`, its recomputed posture is `NON_COMPLIANT` and it is currently `PUBLISHED`, it drops back to `PLANNED` with its `version` advanced.

    An outcome of `REJECTED` requires a `rejection_reason` and is reachable both from `SUBMITTED` and — as a post-hoc disclosure failure — from `VALIDATED`; the latter path is what triggers Cascade A in full.

    Design: Difficulty/transitive_cascade/disclosure_rejection_cascades_four_links_and_unpublishes_session
    """
    world = _published_accredited_session()

    disclosure = validate_success(_reject_the_validated_disclosure(world))
    assert disclosure["status"] == "REJECTED"

    accreditation = validate_success(
        api_client.get_accreditation(
            world["accreditation"]["id"], world["second_chair_headers"]
        )
    )
    assert accreditation["validation_status"] == "REVOKED"
    assert float(accreditation["awarded_credits"]) == pytest.approx(0.00, abs=0.01)
    assert_quarter_credit_step(accreditation["awarded_credits"])


def test_rejected_disclosure_returns_the_minutes_to_the_conference_pool():
    """Cascade A starts when an already-validated disclosure is later rejected. The disclosure becomes `REJECTED`; the accreditation it supported moves from `VALIDATED` to `REVOKED` and its `awarded_credits` returns to 0.00; the conference's `cme_minutes_allocated` drops by that accreditation's `content_minutes`, `cme_minutes_available` is recomputed and the conference's `version` advances; the session holding a counted slot for that abstract recomputes `accredited_credit_total` and `accreditation_posture`; and if that session is `cme_designated`, its recomputed posture is `NON_COMPLIANT` and it is currently `PUBLISHED`, it drops back to `PLANNED` with its `version` advanced.

    A conference's `cme_minutes_allocated` equals the sum of `content_minutes` over its accreditations whose `validation_status` is `VALIDATED`, and `cme_minutes_available` is always `cme_minutes_pool_total` minus `cme_minutes_allocated`. A revocation returns exactly the same minute count that the matching validation debited.

    Design: Difficulty/transitive_cascade/disclosure_rejection_cascades_four_links_and_unpublishes_session
    """
    world = _published_accredited_session()

    before = validate_success(
        api_client.get_conference(world["conference"]["id"], ADMIN)
    )
    assert before["cme_minutes_allocated"] == 45

    validate_success(_reject_the_validated_disclosure(world))

    after = validate_success(api_client.get_conference(world["conference"]["id"], ADMIN))
    assert after["cme_minutes_allocated"] == 0
    assert after["cme_minutes_available"] == 600
    assert_cme_pool_conserved(after)


def test_rejected_disclosure_unpublishes_the_accredited_session():
    """Cascade A starts when an already-validated disclosure is later rejected. The disclosure becomes `REJECTED`; the accreditation it supported moves from `VALIDATED` to `REVOKED` and its `awarded_credits` returns to 0.00; the conference's `cme_minutes_allocated` drops by that accreditation's `content_minutes`, `cme_minutes_available` is recomputed and the conference's `version` advances; the session holding a counted slot for that abstract recomputes `accredited_credit_total` and `accreditation_posture`; and if that session is `cme_designated`, its recomputed posture is `NON_COMPLIANT` and it is currently `PUBLISHED`, it drops back to `PLANNED` with its `version` advanced.

    A session's `accredited_credit_total` uses the per-abstract route, summing the credits of its counted slots whose accreditation is `VALIDATED`, at two decimal places. A session's `accreditation_posture` follows from it: `NOT_APPLICABLE` whenever `cme_designated` is false, otherwise `COMPLIANT` when `accredited_credit_total` is at least 0.50 and `NON_COMPLIANT` when it is below that.

    Design: Difficulty/transitive_cascade/disclosure_rejection_cascades_four_links_and_unpublishes_session
    """
    world = _published_accredited_session()
    session_id = world["sessions"][0]["id"]

    before = validate_success(
        api_client.get_session(session_id, world["chair_headers"])
    )
    assert before["status"] == "PUBLISHED"
    assert float(before["accredited_credit_total"]) == pytest.approx(0.75, abs=0.01)
    assert before["accreditation_posture"] == "COMPLIANT"

    validate_success(_reject_the_validated_disclosure(world))

    session = validate_success(api_client.get_session(session_id, world["chair_headers"]))
    assert float(session["accredited_credit_total"]) == pytest.approx(0.00, abs=0.01)
    assert_two_decimal_places(session["accredited_credit_total"])
    assert session["accreditation_posture"] == "NON_COMPLIANT"
    assert session["status"] == "PLANNED"


def test_rejected_disclosure_leaves_the_running_order_intact():
    """Cascade A starts when an already-validated disclosure is later rejected. The disclosure becomes `REJECTED`; the accreditation it supported moves from `VALIDATED` to `REVOKED` and its `awarded_credits` returns to 0.00; the conference's `cme_minutes_allocated` drops by that accreditation's `content_minutes`, `cme_minutes_available` is recomputed and the conference's `version` advances; the session holding a counted slot for that abstract recomputes `accredited_credit_total` and `accreditation_posture`; and if that session is `cme_designated`, its recomputed posture is `NON_COMPLIANT` and it is currently `PUBLISHED`, it drops back to `PLANNED` with its `version` advanced.

    Its counted slots are those whose `status` is `SCHEDULED`, `PRESENTED` or `NO_SHOW_RECORDED`, and `slot_count` is their number.

    Design: Difficulty/transitive_cascade/disclosure_rejection_cascades_four_links_and_unpublishes_session
    """
    world = _published_accredited_session()

    validate_success(_reject_the_validated_disclosure(world))

    slot = validate_success(
        api_client.get_session_slot(world["slots"][0]["id"], world["chair_headers"])
    )
    assert slot["status"] == "SCHEDULED"

    session = validate_success(
        api_client.get_session(world["sessions"][0]["id"], world["chair_headers"])
    )
    assert session["slot_count"] == 1

    abstract = validate_success(
        api_client.get_abstract(world["abstracts"][0]["id"], world["chair_headers"])
    )
    assert abstract["status"] == "SCHEDULED"


# ─────────────────────────────────────────────────────────────────────────
# A recorded no-show strikes the presenting author
# ─────────────────────────────────────────────────────────────────────────


def test_no_show_recording_takes_the_abstract_out_of_the_program():
    """Cascade D starts when a slot is recorded as a no-show. The slot becomes `NO_SHOW_RECORDED`; its abstract moves from `SCHEDULED` to `NO_SHOW` and the presenting author's `no_show_strikes` is recomputed; and that author's `sanction_status` is re-derived from the combined strike count.

    Marking a slot `NO_SHOW_RECORDED` requires the logical clock to be at or after the session's `end_utc`, and it runs Cascade D: the abstract moves from `SCHEDULED` to `NO_SHOW`, the presenting author's `no_show_strikes` is recomputed, and their `sanction_status` is re-derived — `WARNED` at a combined strike count of one, `BARRED` at two or more.

    Design: Difficulty/transitive_cascade/no_show_recording_cascades_three_links_and_warns_the_author
    """
    world = _published_session_after_its_window_closed()

    slot = validate_success(_record_the_no_show(world))
    assert slot["status"] == "NO_SHOW_RECORDED"

    abstract = validate_success(
        api_client.get_abstract(world["abstracts"][0]["id"], world["chair_headers"])
    )
    assert abstract["status"] == "NO_SHOW"


def test_no_show_recording_warns_the_presenting_author():
    """Cascade D starts when a slot is recorded as a no-show. The slot becomes `NO_SHOW_RECORDED`; its abstract moves from `SCHEDULED` to `NO_SHOW` and the presenting author's `no_show_strikes` is recomputed; and that author's `sanction_status` is re-derived from the combined strike count.

    Two kinds of misconduct accumulate against an author. `no_show_strikes` is the number of session slots recorded as `NO_SHOW_RECORDED` whose presenter is this author; `embargo_breach_count` is the number of this author's abstracts whose embargo dimension reached `BREACHED`. The `sanction_status` ladder is derived from their sum: a combined count of zero leaves the author at `NONE`, a combined count of exactly one moves them to `WARNED`, and a combined count of two or more moves them to `BARRED`.

    Design: Difficulty/transitive_cascade/no_show_recording_cascades_three_links_and_warns_the_author
    """
    world = _published_session_after_its_window_closed()
    author_id = world["authors"]["ada"]["id"]

    before = validate_success(api_client.get_author(author_id, ADMIN))
    assert before["no_show_strikes"] == 0
    assert before["sanction_status"] == "NONE"

    validate_success(_record_the_no_show(world))

    author = validate_success(api_client.get_author(author_id, ADMIN))
    assert author["no_show_strikes"] == 1
    assert author["embargo_breach_count"] == 0
    assert author["sanction_status"] == "WARNED"


def test_no_show_recording_keeps_the_committed_oral_slot_spent():
    """A conference's `accepted_oral_count`, `accepted_poster_count` and `accepted_workshop_count` each equal the number of that conference's abstracts whose `decision` is the matching format and whose `status` is one of `ACCEPTED`, `CONFIRMED`, `SCHEDULED`, `PRESENTED` or `NO_SHOW`.

    Cascade D starts when a slot is recorded as a no-show. The slot becomes `NO_SHOW_RECORDED`; its abstract moves from `SCHEDULED` to `NO_SHOW` and the presenting author's `no_show_strikes` is recomputed; and that author's `sanction_status` is re-derived from the combined strike count.

    Design: Difficulty/transitive_cascade/no_show_recording_cascades_three_links_and_warns_the_author
    """
    world = _published_session_after_its_window_closed()

    validate_success(_record_the_no_show(world))

    conference = validate_success(
        api_client.get_conference(world["conference"]["id"], ADMIN)
    )
    assert conference["accepted_oral_count"] == 1
    assert_format_capacity_within_bounds(conference)

    session = validate_success(
        api_client.get_session(world["sessions"][0]["id"], world["chair_headers"])
    )
    assert session["status"] == "PUBLISHED"


# ─────────────────────────────────────────────────────────────────────────
# A suspended committee member's live reviews are voided and reassigned
# ─────────────────────────────────────────────────────────────────────────


def test_member_suspension_voids_the_live_review_and_empties_the_load_ledger():
    """Cascade C starts when a committee member is suspended. Every review of that member whose `status` is `ASSIGNED` becomes `VOIDED`; the member's `current_review_load` is recomputed and therefore falls to zero; and for every abstract that lost an assigned review while its own `status` was `UNDER_REVIEW`, a replacement review is created by the expertise selector with the suspended member excluded.

    Suspension from `ACTIVE` has no preconditions and runs Cascade C.

    Design: Difficulty/transitive_cascade/member_suspension_cascades_three_links_and_reassigns_the_review
    """
    world = _panel_with_one_spare_reviewer()
    abstract_id = world["abstracts"][0]["id"]
    rui_review = world["reviews"][abstract_id][0]

    member = validate_success(_suspend(world["members"]["rui"]["id"]))
    assert member["status"] == "SUSPENDED"

    review = validate_success(
        api_client.get_review(rui_review["id"], world["chair_headers"])
    )
    assert review["status"] == "VOIDED"

    suspended = validate_success(
        api_client.get_committee_member(
            world["members"]["rui"]["id"], world["chair_headers"]
        )
    )
    assert suspended["current_review_load"] == 0
    assert_reviewer_load_within_ceiling(suspended)


def test_member_suspension_reassigns_the_orphaned_review_to_the_best_match():
    """Cascade C starts when a committee member is suspended. Every review of that member whose `status` is `ASSIGNED` becomes `VOIDED`; the member's `current_review_load` is recomputed and therefore falls to zero; and for every abstract that lost an assigned review while its own `status` was `UNDER_REVIEW`, a replacement review is created by the expertise selector with the suspended member excluded.

    The score is twice the number of keywords the two sets share, divided by the sum of the two set sizes, rounded half up to four decimal places.

    Surviving candidates are ranked by match score from highest to lowest; ties are broken by spare capacity, meaning `max_review_load` minus `current_review_load`, from largest to smallest; any remaining tie is broken by `created_at` from earliest to latest. The identifier is never used as a tiebreaker. The single highest-ranked candidate is assigned.

    Design: Difficulty/transitive_cascade/member_suspension_cascades_three_links_and_reassigns_the_review
    """
    world = _panel_with_one_spare_reviewer()
    abstract_id = world["abstracts"][0]["id"]
    nadia_id = world["members"]["nadia"]["id"]

    validate_success(_suspend(world["members"]["rui"]["id"]))

    rows, _meta = validate_paginated(
        api_client.list_reviews(
            world["chair_headers"],
            params={"abstract_id": abstract_id, "reviewer_member_id": nadia_id},
        )
    )
    assert len(rows) == 1, "the suspension should mint exactly one replacement review"
    replacement = rows[0]
    assert replacement["reviewer_member_id"] == nadia_id
    assert replacement["status"] == "ASSIGNED"
    assert float(replacement["expertise_match_score"]) == pytest.approx(
        0.8000, abs=0.0001
    )
    assert_four_decimal_places(replacement["expertise_match_score"])

    nadia = validate_success(
        api_client.get_committee_member(nadia_id, world["chair_headers"])
    )
    assert nadia["current_review_load"] == 1
    assert_reviewer_load_within_ceiling(nadia)


def test_member_suspension_leaves_the_other_reviewers_assignment_alone():
    """Cascade C starts when a committee member is suspended. Every review of that member whose `status` is `ASSIGNED` becomes `VOIDED`; the member's `current_review_load` is recomputed and therefore falls to zero; and for every abstract that lost an assigned review while its own `status` was `UNDER_REVIEW`, a replacement review is created by the expertise selector with the suspended member excluded.

    A committee member's `current_review_load` always equals the number of that member's review rows whose `status` is `ASSIGNED`, and it must never be negative nor exceed that member's `max_review_load`.

    Design: Difficulty/transitive_cascade/member_suspension_cascades_three_links_and_reassigns_the_review
    """
    world = _panel_with_one_spare_reviewer()
    abstract_id = world["abstracts"][0]["id"]
    mei_review = world["reviews"][abstract_id][1]

    validate_success(_suspend(world["members"]["rui"]["id"]))

    review = validate_success(
        api_client.get_review(mei_review["id"], world["chair_headers"])
    )
    assert review["status"] == "ASSIGNED"

    mei = validate_success(
        api_client.get_committee_member(
            world["members"]["mei"]["id"], world["chair_headers"]
        )
    )
    assert mei["current_review_load"] == 1
    assert_reviewer_load_within_ceiling(mei)

    abstract = validate_success(
        api_client.get_abstract(abstract_id, world["chair_headers"])
    )
    assert abstract["status"] == "UNDER_REVIEW"
    assert abstract["submitted_review_count"] == 0
