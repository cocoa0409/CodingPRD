"""What a single accepted write must already contain by the time it answers.

The deposit is the widest write in the contract: it computes two figures, mints an
identifier, resolves an access level, projects an embargo release date and closes a
clearance. This test reads all of it off the 201 body first, then confirms the stored
rows agree with what the response already claimed.
"""

import pytest
from prd_bench_local_runner.testing import get_success_data

from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.assertions import assert_handle_format, assert_instant
from test_helpers.factories import create_repository_deposit_payload
from test_helpers.test_users import ANALYST_TWO_USER_ID, TEST_USERS

REGISTRAR = TEST_USERS["registrar_headers"]
ANALYST_TWO = TEST_USERS["analyst_two_headers"]


def test_the_deposit_response_already_carries_every_side_effect_of_that_request(
    api: ApiClient,
) -> None:
    """Handle, score, fee, access level, release date and clearance all settle in one call.

    PRD §3.8: "A successful deposit creates the row with `status` `DEPOSITED`, `deposited_at` set to the current logical instant, `depositor_user_id` set to the acting analyst's `X-User-ID`, and the computed `metadata_completeness_score` and `late_fee_cents` stored on it."

    PRD §3.8: "Its `handle` is the citable repository identifier, formed as the term's `code`, a slash, and a five-digit zero-padded sequence number"

    PRD §3.7: "When the governing request was fully `APPROVED`, the release date is the deposit instant advanced by `approved_months` calendar months and `release_anchor` is recorded as `DEPOSIT` — the clock starts the moment the document lands in the repository."

    PRD §3.8: "The document then advances `FORMAT_ACCEPTED → DEPOSITED`, the room and committee counters are untouched, and clearance is recomputed — the deposit item is now satisfied, so if no other outstanding item remains the clearance becomes `CLEARED` with `cleared_at` set to the current logical instant."

    Design: Corner/consistency_model/deposit_response_reflects_every_side_effect_of_the_same_request
    """
    world = fx.setup_passed_defense(
        thesis_overrides={
            "title": "Same Request",
            "page_count": 101,
            "third_party_item_count": 0,
        }
    )
    thesis_id = world["thesis"]["id"]

    embargo = fx.request_embargo(
        world,
        reason_code="PUBLISHER_AGREEMENT",
        requested_months=6,
        justification="Publisher requires a six-month hold.",
    )
    approved = fx.decide_embargo(
        world, embargo, decision="APPROVE", decision_note="Agreement on file."
    )
    assert approved["approved_months"] == 6

    review = fx.open_format_cycle(world, clock="2026-10-05T09:00:00Z")
    fx.record_screening(world, similarity_pct=4.0)
    fx.decide_format_review(world, review, clock="2026-10-12T09:00:00Z")

    fx.set_clock("2026-11-02T10:00:00Z")
    deposit = get_success_data(
        api.create_repository_deposit(
            create_repository_deposit_payload(
                thesis_id,
                abstract_word_count=150,
                subject_keywords=["digital humanities", "archives", "metadata"],
                late_fee_paid_cents=0,
                advisor_name="Cara Cho",
                department_code="CS",
            ),
            ANALYST_TWO,
        ),
        201,
    )

    assert deposit["status"] == "DEPOSITED"
    assert deposit["depositor_user_id"] == ANALYST_TWO_USER_ID
    assert deposit["handle"] == "2026FA/00001"
    assert_handle_format(deposit["handle"], "2026FA", 1)
    assert deposit["metadata_completeness_score"] == pytest.approx(1.0000, abs=0.0001)
    assert deposit["late_fee_cents"] == 0
    assert deposit["access_level"] == "EMBARGOED"
    assert_instant(
        deposit["embargo_release_date"],
        "2027-05-02T10:00:00Z",
        "deposit embargo_release_date",
    )
    assert_instant(deposit["deposited_at"], "2026-11-02T10:00:00Z", "deposited_at")

    stored_embargo = get_success_data(api.get_embargo_request(embargo["id"], REGISTRAR))
    assert stored_embargo["status"] == "APPROVED"
    assert_instant(
        stored_embargo["release_date"], "2027-05-02T10:00:00Z", "embargo release_date"
    )
    assert stored_embargo["release_anchor"] == "DEPOSIT"

    clearance = get_success_data(
        api.list_student_graduation_clearances(world["student"]["id"], REGISTRAR)
    )[0]
    assert clearance["status"] == "CLEARED"
    assert clearance["outstanding_items"] == []
    assert_instant(clearance["cleared_at"], "2026-11-02T10:00:00Z", "cleared_at")

    assert (
        get_success_data(api.get_thesis(thesis_id, REGISTRAR))["workflow_state"]
        == "DEPOSITED"
    )
