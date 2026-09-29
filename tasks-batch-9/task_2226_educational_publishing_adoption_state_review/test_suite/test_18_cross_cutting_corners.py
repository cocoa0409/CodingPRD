"""Stale-version protection and content pinning across several records at once.

The two write operations that demand a proven-current view of a parent record —
filing a price and reserving a hearing slot — are exercised here by replaying a
version the client observed one write too early, and then replaying the same
body with the refreshed version. The third test follows one edition into two
states and shows that each state's file pins its own revision, so an editorial
change after the first filing stales exactly one of the two submissions.
"""

import pytest

from test_helpers import (
    EDIT_TYPE_REGIONAL_SUBSTITUTION,
    PRICING_STATUS_PRICE_FILED,
    PROPOSAL_STATUS_FILED,
    PROPOSAL_STATUS_SUPERSEDED,
    REVIEW_STATUS_FILED,
    REVIEW_STATUS_SCHEDULED,
    SLOT_STATUS_RESERVED,
    ApiErrorId,
    factories,
    make_editorial_director_headers,
    make_platform_admin_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    advance_phase,
    approve_content_edit,
    file_submission,
    propose_content_edit,
    seed_cycle,
    seed_draft_submission,
    seed_filed_submission,
    seed_open_cycle,
    seed_panel,
    seed_standard,
    seed_state,
    seed_title,
    set_clock,
)


def test_stale_submission_version_rejects_the_price_filing(api, pricing_manager_headers):
    """PRD 2.8: "Filing a pricing proposal (`POST /pricing-proposals`) requires `expected_submission_version` as a non-optional field of the request body, carrying the client's last observed `version` of the `Submission` named by `submission_id`. If that value does not equal the submission's current `version`, the request is rejected with `ERR_STALE_SUBMISSION_VERSION` (HTTP 412)."

    PRD 2.8: "Every accepted filing increments the submission's `version` by 1, so a client must re-read the submission before filing again."

    A second price filed against the version observed before the first filing is
    refused on the concurrency guard. Re-reading the submission and replaying the
    identical body succeeds and supersedes the earlier proposal, which is what
    proves the refusal came from the stale version and not from the supersede
    rule.

    Design: Corner/cross_cutting_complexity_layers/stale_submission_version_rejects_the_price_filing
    """
    world = seed_filed_submission(api, "MI", subject="MATH", grade=7)
    submission_id = world.submission_id

    version_after_filing = api.read_submission_version(submission_id, pricing_manager_headers)
    first_proposal = validate_success(
        api.create_pricing_proposal(
            factories.pricing_proposal_payload(
                submission_id, version_after_filing, base_price_cents=9000
            ),
            pricing_manager_headers,
        ),
        expected_status=201,
    )

    replayed_body = factories.pricing_proposal_payload(
        submission_id, version_after_filing, base_price_cents=8600
    )
    stale = api.create_pricing_proposal(replayed_body, pricing_manager_headers)
    validate_error(stale, ApiErrorId.ERR_STALE_SUBMISSION_VERSION, expected_status=412)

    refreshed = validate_success(api.get_submission(submission_id, pricing_manager_headers))
    assert refreshed["version"] == version_after_filing + 1

    replayed_body["expected_submission_version"] = refreshed["version"]
    second_proposal = validate_success(
        api.create_pricing_proposal(replayed_body, pricing_manager_headers),
        expected_status=201,
    )
    assert second_proposal["base_price_cents"] == 8600
    assert second_proposal["status"] == PROPOSAL_STATUS_FILED

    superseded = validate_success(
        api.get_pricing_proposal(first_proposal["id"], pricing_manager_headers)
    )
    assert superseded["status"] == PROPOSAL_STATUS_SUPERSEDED

    submission = validate_success(api.get_submission(submission_id, pricing_manager_headers))
    assert submission["pricing_status"] == PRICING_STATUS_PRICE_FILED

    proposals, meta = validate_paginated(
        api.list_pricing_proposals(
            pricing_manager_headers, params={"submission_id": submission_id}
        )
    )
    assert meta["total_count"] == 2
    assert {proposal["id"] for proposal in proposals} == {
        first_proposal["id"],
        second_proposal["id"],
    }


def test_stale_panel_version_rejects_the_slot_reservation(api):
    """PRD 2.8: "Reserving a presentation slot (`POST /committee-panels/{id}/slots`) requires `expected_panel_version` as a non-optional field of the request body, carrying the client's last observed `version` of the addressed `CommitteePanel`. If that value does not equal the panel's current `version`, the request is rejected with `ERR_STALE_PANEL_VERSION` (HTTP 412)."

    PRD 2.8: "Every accepted reservation increments the panel's `version` by 1."

    The second reservation asks for a window that is free and clears the panel's
    ten-minute turnover buffer, yet it is refused because the officer's view of
    the panel predates the first reservation. Refreshing the panel version lets
    the identical window through and both submissions hold a hearing.

    Design: Corner/cross_cutting_complexity_layers/stale_panel_version_rejects_the_slot_reservation
    """
    world = seed_open_cycle(api, "NJ", subject="SCIENCE", grade=6)
    title_a = world.title_id
    title_b = seed_title(
        api, world, subject="SCIENCE", grade_low=6, grade_high=6, page_count=305
    )

    submission_a = seed_draft_submission(api, world, title_id=title_a)
    file_submission(api, world, submission_a)
    submission_b = seed_draft_submission(api, world, title_id=title_b)
    file_submission(api, world, submission_b)

    panel_id = seed_panel(api, world, panel_label="NJ SCIENCE Panel A")
    panel_version = api.read_panel_version(panel_id, world.officer)

    slot_a = validate_success(
        api.reserve_slot(
            panel_id,
            factories.slot_payload(
                submission_a,
                panel_version,
                start_at="2026-10-20T14:00:00Z",
                end_at="2026-10-20T14:30:00Z",
            ),
            world.officer,
        ),
        expected_status=201,
    )

    second_window = factories.slot_payload(
        submission_b,
        panel_version,
        start_at="2026-10-20T15:00:00Z",
        end_at="2026-10-20T15:30:00Z",
    )
    stale = api.reserve_slot(panel_id, second_window, world.officer)
    validate_error(stale, ApiErrorId.ERR_STALE_PANEL_VERSION, expected_status=412)

    refreshed = validate_success(api.get_committee_panel(panel_id, world.officer))
    assert refreshed["version"] == panel_version + 1

    second_window["expected_panel_version"] = refreshed["version"]
    slot_b = validate_success(
        api.reserve_slot(panel_id, second_window, world.officer),
        expected_status=201,
    )

    panel = validate_success(api.get_committee_panel(panel_id, world.officer))
    assert panel["reserved_minutes"] == 60

    assert (
        validate_success(api.get_presentation_slot(slot_a["id"], world.officer))["status"]
        == SLOT_STATUS_RESERVED
    )
    assert (
        validate_success(api.get_presentation_slot(slot_b["id"], world.officer))["status"]
        == SLOT_STATUS_RESERVED
    )

    scheduled = validate_success(api.get_submission(submission_b, world.officer))
    assert scheduled["review_status"] == REVIEW_STATUS_SCHEDULED

    cycle = validate_success(api.get_adoption_cycle(world.cycle_id, world.officer))
    assert cycle["scheduled_submission_count"] == 2


def test_two_states_pin_different_content_revisions_of_one_title(
    api, publisher_editor_headers
):
    """PRD 3.5: "A successful filing moves `review_status` from `DRAFT` to `FILED` and performs the **content pin**: `pinned_content_revision` is set to the edition's current `content_revision` and `content_pin_stale` is set to false, capturing exactly which revision of the edition the state is being asked to review."

    PRD 3.3: "Every submission whose `title_id` is this edition, whose `review_status` is `FILED`, `SCHEDULED` or `PRESENTED`, and whose `pinned_content_revision` is strictly less than the edition's new `content_revision`, sets `content_pin_stale` to true, recomputes `prohibited_hit_count`, `missing_required_topic_count` and `compliance_score`, and sets `adoption_blocked` to true."

    PRD 3.7: "Finally, `adoption_blocked` is true when any of three conditions holds: `compliance_score` is strictly below 70, or `prohibited_hit_count` is greater than 0, or `content_pin_stale` is true."

    One edition competes in two states. The state that filed before the regional
    substitution pinned revision 1 and is stale the moment the edit is applied;
    the state that filed afterwards pinned revision 2 and is current. The
    edition itself carries one revision number, not two.

    Design: Corner/cross_cutting_complexity_layers/two_states_pin_different_content_revisions_of_one_title
    """
    admin = make_platform_admin_headers()
    director = make_editorial_director_headers("dir-1")

    carolina = seed_state(api, "SC")
    seed_standard(api, carolina, "SC.M.5.1", subject="MATH", grade_low=5, grade_high=5)
    seed_cycle(api, carolina, subject="MATH", cycle_year=2027)

    new_york = seed_state(api, "NY")
    seed_standard(api, new_york, "NY.M.5.1", subject="MATH", grade_low=5, grade_high=5)
    seed_cycle(api, new_york, subject="MATH", cycle_year=2027)

    title_id = seed_title(api, carolina, subject="MATH", grade_low=5, grade_high=5)
    new_york.title_id = title_id

    set_clock(api, "2026-09-15T00:00:00Z")
    advance_phase(api, carolina)
    advance_phase(api, new_york)

    submission_sc = seed_draft_submission(api, carolina)
    submission_ny = seed_draft_submission(api, new_york)

    filed_sc = validate_success(
        api.file_submission(submission_sc, publisher_editor_headers)
    )
    assert filed_sc["pinned_content_revision"] == 1
    assert filed_sc["content_pin_stale"] is False

    edit_id = propose_content_edit(
        api,
        new_york,
        topic_code="NY_HUDSON_DATA_SET",
        pages_delta=0,
        edit_type=EDIT_TYPE_REGIONAL_SUBSTITUTION,
        rationale="Swaps the sample data set for Hudson River measurements.",
    )
    approve_content_edit(api, new_york, edit_id)
    validate_success(api.apply_content_edit(edit_id, director))

    filed_ny = validate_success(
        api.file_submission(submission_ny, publisher_editor_headers)
    )
    assert filed_ny["pinned_content_revision"] == 2
    assert filed_ny["content_pin_stale"] is False

    title = validate_success(api.get_title(title_id, admin))
    assert title["content_revision"] == 2
    assert title["page_count"] == 300

    stale_side = validate_success(api.get_submission(submission_sc, admin))
    assert stale_side["pinned_content_revision"] == 1
    assert stale_side["content_pin_stale"] is True
    assert stale_side["adoption_blocked"] is True
    assert stale_side["review_status"] == REVIEW_STATUS_FILED

    current_side = validate_success(api.get_submission(submission_ny, admin))
    assert current_side["pinned_content_revision"] == 2
    assert current_side["content_pin_stale"] is False
    assert current_side["adoption_blocked"] is False
    assert current_side["review_status"] == REVIEW_STATUS_FILED
