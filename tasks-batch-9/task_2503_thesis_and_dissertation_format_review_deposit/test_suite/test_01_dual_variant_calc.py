"""Two calculations that answer differently from one identical dataset.

The embargo release projection is anchored either on the deposit instant or on
the term's conferral date, and the graduation-clearance projection credits
in-flight evidence or demands terminal evidence, in both cases selected by state
that lives on another entity.
"""

import pytest
from prd_bench_local_runner.testing import get_success_data

from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.assertions import assert_instant, normalize_instant
from test_helpers.test_users import DEAN_TWO_USER_ID, TEST_USERS

REGISTRAR = TEST_USERS["registrar_headers"]
ANALYST_ONE = TEST_USERS["analyst_headers"]

DEPOSIT_INSTANT = "2026-12-08T11:00:00Z"


def _two_candidates_with_decided_embargoes() -> dict:
    """Two accepted documents, one fully approved and one shortened embargo."""
    world = fx.setup_announced_defense(thesis_overrides={"title": "Thesis A"})
    other = fx.add_second_candidate_pipeline(world, title="Thesis B")

    other["defense_event"] = fx.schedule_defense(
        world,
        thesis=other["thesis"],
        scheduled_start="2026-09-28T14:00:00Z",
        scheduled_end="2026-09-28T16:00:00Z",
        headers=other["student_headers"],
    )
    get_success_data(
        fx.api_client.announce_defense_event(other["defense_event"]["id"], ANALYST_ONE)
    )

    fx.set_clock("2026-09-28T16:30:00Z")
    for event in (world["defense_event"], other["defense_event"]):
        get_success_data(
            fx.api_client.record_defense_outcome(
                event["id"], {"outcome": "PASS"}, world["chair_headers"]
            )
        )

    embargo_a = fx.request_embargo(
        world,
        reason_code="PATENT_PENDING",
        requested_months=12,
        justification="Utility patent application pending on the chapter 4 apparatus",
    )
    fx.decide_embargo(world, embargo_a, decision="APPROVE")

    embargo_b = fx.request_embargo(
        other,
        reason_code="SENSITIVE_DATA",
        requested_months=18,
        justification="Field site coordinates must stay closed until the habitat survey concludes",
    )
    fx.decide_embargo(
        world,
        embargo_b,
        decision="PARTIALLY_APPROVE",
        approved_months=12,
        decision_note="Twelve months is sufficient for the survey window",
        dean_user_id=DEAN_TWO_USER_ID,
    )

    fx.set_clock("2026-10-05T09:00:00Z")
    review_a = fx.open_format_cycle(world)
    review_b = fx.open_format_cycle(other)
    fx.record_screening(world, similarity_pct=25.0, excluded_quoted_pct=7.5)
    fx.record_screening(other, similarity_pct=25.0, excluded_quoted_pct=7.5)

    fx.set_clock("2026-10-12T09:00:00Z")
    for review in (review_a, review_b):
        fx.decide_format_review(
            world,
            review,
            decision="ACCEPT",
            critical_defect_count=1,
            major_defect_count=1,
            minor_defect_count=1,
        )

    fx.set_clock(DEPOSIT_INSTANT)
    deposit_a = fx.deposit_thesis(
        world,
        abstract_word_count=200,
        subject_keywords=["graph theory", "compilers", "verification"],
        late_fee_paid_cents=5000,
        advisor_name="Cara Cho",
        department_code="CS",
    )
    deposit_b = fx.deposit_thesis(
        other,
        abstract_word_count=200,
        subject_keywords=["habitat", "survey", "ecology"],
        late_fee_paid_cents=5000,
        advisor_name="Cara Cho",
        department_code="BIO",
    )
    return {
        "world": world,
        "other": other,
        "embargo_a": embargo_a,
        "embargo_b": embargo_b,
        "deposit_a": deposit_a,
        "deposit_b": deposit_b,
    }


def test_full_approval_anchors_release_on_the_deposit_instant(api: ApiClient) -> None:
    """The fully approved embargo counts twelve months from the deposit instant.

    PRD §3.7: "When the governing request was fully `APPROVED`, the release date is the deposit instant advanced by `approved_months` calendar months and `release_anchor` is recorded as `DEPOSIT` — the clock starts the moment the document lands in the repository."

    Design: Difficulty/dual_variant_calc/embargo_release_anchor_diverges_between_full_and_partial_approval
    """
    scenario = _two_candidates_with_decided_embargoes()

    embargo_a = get_success_data(
        api.get_embargo_request(scenario["embargo_a"]["id"], REGISTRAR)
    )
    assert embargo_a["approved_months"] == 12
    assert embargo_a["release_anchor"] == "DEPOSIT"
    assert_instant(embargo_a["release_date"], "2027-12-08T11:00:00Z", "release_date")

    deposit_a = get_success_data(
        api.get_thesis_repository_deposit(
            scenario["world"]["thesis"]["id"], REGISTRAR
        )
    )[0]
    assert_instant(deposit_a["deposited_at"], DEPOSIT_INSTANT, "deposited_at")
    assert_instant(
        deposit_a["embargo_release_date"],
        "2027-12-08T11:00:00Z",
        "embargo_release_date",
    )
    assert deposit_a["access_level"] == "EMBARGOED"
    assert deposit_a["late_fee_cents"] == 5000
    assert deposit_a["metadata_completeness_score"] == pytest.approx(1.0, abs=0.0001)


def test_shortened_approval_anchors_release_on_the_conferral_date(
    api: ApiClient,
) -> None:
    """The shortened embargo counts the same twelve months from conferral instead.

    PRD §3.7: "When the governing request was only `PARTIALLY_APPROVED`, the release date is instead the term's `degree_conferral_date` advanced by `approved_months` calendar months and `release_anchor` is recorded as `CONFERRAL`, on the reasoning that a shortened embargo is measured from the public conferral date; identical `approved_months` and an identical deposit instant therefore yield a *different* release date under the two branches."

    Design: Difficulty/dual_variant_calc/embargo_release_anchor_diverges_between_full_and_partial_approval
    """
    scenario = _two_candidates_with_decided_embargoes()

    embargo_b = get_success_data(
        api.get_embargo_request(scenario["embargo_b"]["id"], REGISTRAR)
    )
    assert embargo_b["approved_months"] == 12
    assert embargo_b["release_anchor"] == "CONFERRAL"
    assert_instant(embargo_b["release_date"], "2027-12-18T00:00:00Z", "release_date")

    deposit_b = get_success_data(
        api.get_thesis_repository_deposit(scenario["other"]["thesis"]["id"], REGISTRAR)
    )[0]
    assert_instant(deposit_b["deposited_at"], DEPOSIT_INSTANT, "deposited_at")
    assert_instant(
        deposit_b["embargo_release_date"],
        "2027-12-18T00:00:00Z",
        "embargo_release_date",
    )
    assert deposit_b["access_level"] == "EMBARGOED"
    assert deposit_b["late_fee_cents"] == 5000

    deposit_a = get_success_data(
        api.get_thesis_repository_deposit(scenario["world"]["thesis"]["id"], REGISTRAR)
    )[0]
    assert_instant(deposit_a["deposited_at"], DEPOSIT_INSTANT, "deposited_at")
    assert normalize_instant(deposit_a["embargo_release_date"]) != normalize_instant(
        deposit_b["embargo_release_date"]
    ), "identical approved_months and deposit instants must still diverge"

    for student_id in (
        scenario["world"]["student"]["id"],
        scenario["other"]["student"]["id"],
    ):
        clearance = get_success_data(
            api.list_student_graduation_clearances(student_id, REGISTRAR)
        )[0]
        assert clearance["status"] == "CLEARED"


def _announced_defense_only_world() -> dict:
    """An announced but unheld defense with no format, integrity or deposit evidence."""
    return fx.setup_announced_defense(
        thesis_overrides={"title": "Provisional vs Final"}
    )


def test_provisional_projection_credits_the_announced_defense(api: ApiClient) -> None:
    """While the term is open the announced defense and unscreened state count.

    PRD §3.9: "Under `PROVISIONAL`, in-flight evidence is credited: a `SUBMITTED` committee also satisfies `COMMITTEE_APPROVAL`, an `ANNOUNCED` defense also satisfies `DEFENSE_OUTCOME`, permission records still in `SUBMITTED` also count toward the permission total, a `PENDING_REVIEW` format review also satisfies `FORMAT_ACCEPTANCE`, and an `integrity_state` of `NOT_SCREENED` also satisfies `INTEGRITY`."

    Design: Difficulty/dual_variant_calc/clearance_projection_provisional_vs_final_diverge_on_same_data
    """
    world = _announced_defense_only_world()

    clearance = get_success_data(
        api.list_student_graduation_clearances(world["student"]["id"], REGISTRAR)
    )[0]
    assert clearance["projection_variant"] == "PROVISIONAL"
    assert clearance["outstanding_items"] == ["FORMAT_ACCEPTANCE", "DEPOSIT"]
    assert clearance["status"] == "PENDING_ITEMS"

    thesis = get_success_data(api.get_thesis(world["thesis"]["id"], REGISTRAR))
    assert thesis["workflow_state"] == "DEFENSE_ANNOUNCED"
    assert thesis["integrity_state"] == "NOT_SCREENED"


def test_closing_the_window_switches_the_same_data_to_the_final_variant(
    api: ApiClient,
) -> None:
    """Closing the window alone grows the outstanding list to four items.

    PRD §3.9: "The `projection_variant` is `PROVISIONAL` while the term is `OPEN` and `FINAL` once the term is `DEPOSIT_CLOSED` or `CONFERRED`."

    Design: Difficulty/dual_variant_calc/clearance_projection_provisional_vs_final_diverge_on_same_data
    """
    world = _announced_defense_only_world()

    term = get_success_data(
        api.close_term_deposit(world["term"]["id"], REGISTRAR)
    )
    assert term["status"] == "DEPOSIT_CLOSED"

    clearance = get_success_data(
        api.list_student_graduation_clearances(world["student"]["id"], REGISTRAR)
    )[0]
    assert clearance["projection_variant"] == "FINAL"
    assert clearance["outstanding_items"] == [
        "DEFENSE_OUTCOME",
        "FORMAT_ACCEPTANCE",
        "INTEGRITY",
        "DEPOSIT",
    ]
    assert clearance["status"] == "PENDING_ITEMS"

    student = get_success_data(api.get_student(world["student"]["id"], REGISTRAR))
    assert student["graduation_clearance_state"] == "PENDING_ITEMS"

    thesis = get_success_data(api.get_thesis(world["thesis"]["id"], REGISTRAR))
    assert thesis["workflow_state"] == "DEFENSE_ANNOUNCED"
    event = get_success_data(
        api.get_defense_event(world["defense_event"]["id"], REGISTRAR)
    )
    assert event["status"] == "ANNOUNCED"
