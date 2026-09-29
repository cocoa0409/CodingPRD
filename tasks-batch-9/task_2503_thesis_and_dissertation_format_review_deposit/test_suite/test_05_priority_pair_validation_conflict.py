"""Requests that violate two rules at once, where the admission ladder decides.

A re-announcement is both illegal by state and short on lead, and a deposit is
both short on permissions and wrong on the fee; in each case the earlier stage of
the ladder owns the response and the later error never surfaces.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.assertions import assert_instant
from test_helpers.factories import create_repository_deposit_payload
from test_helpers.test_users import TEST_USERS

REGISTRAR = TEST_USERS["registrar_headers"]
ANALYST_ONE = TEST_USERS["analyst_headers"]
ANALYST_TWO = TEST_USERS["analyst_two_headers"]


def _announced_defense_one_business_day_out() -> dict:
    """An already-announced defense with the clock moved to the day before."""
    world = fx.setup_announced_defense()
    fx.set_clock("2026-09-24T09:00:00Z")
    return world


def test_reannouncing_reports_the_state_error_not_the_short_lead(
    api: ApiClient,
) -> None:
    """The illegal source status is reported ahead of the temporal guard.

    PRD §2.5: "When several rules could reject the same request, the answer the client receives is fixed: rules are evaluated in the order below, and the first one that fails determines the response."

    Design: Difficulty/priority_pair_validation_conflict/state_priority_beats_business_temporal_priority_on_reannounce
    """
    world = _announced_defense_one_business_day_out()

    error = validate_error(
        api.announce_defense_event(world["defense_event"]["id"], ANALYST_ONE),
        "ERR_DEFENSE_STATE_INVALID",
        409,
    )
    assert error["error_id"] != "ERR_ANNOUNCEMENT_LEAD_TOO_SHORT"


def test_refused_reannouncement_leaves_the_frozen_lead_untouched(
    api: ApiClient,
) -> None:
    """The lead computed at the first announcement stays frozen on the event.

    PRD §3.4: "On success the event moves `DRAFT → ANNOUNCED`, `announced_at` is set to the current logical instant, the computed lead is frozen onto the event as `announcement_lead_bdays`, the document advances `DEFENSE_SCHEDULED → DEFENSE_ANNOUNCED`, and clearance is recomputed — an announced but unheld defense satisfies the defense-outcome item under the provisional projection but not under the final one."

    Design: Difficulty/priority_pair_validation_conflict/state_priority_beats_business_temporal_priority_on_reannounce
    """
    world = _announced_defense_one_business_day_out()

    validate_error(
        api.announce_defense_event(world["defense_event"]["id"], ANALYST_ONE),
        "ERR_DEFENSE_STATE_INVALID",
        409,
    )

    event = get_success_data(
        api.get_defense_event(world["defense_event"]["id"], REGISTRAR)
    )
    assert event["status"] == "ANNOUNCED"
    assert event["announcement_lead_bdays"] == 40
    assert_instant(event["announced_at"], "2026-08-01T00:00:00Z", "announced_at")

    thesis = get_success_data(api.get_thesis(world["thesis"]["id"], REGISTRAR))
    assert thesis["workflow_state"] == "DEFENSE_ANNOUNCED"


def _accepted_document_with_one_unreviewed_permission() -> dict:
    """One accepted permission record and one still-submitted second record."""
    world = fx.setup_passed_defense(
        thesis_overrides={
            "title": "Permissions Versus Fee",
            "third_party_item_count": 1,
        }
    )
    world["permission_one"] = fx.document_permission(
        world,
        material_type="FIGURE",
        rights_basis="WRITTEN_PERMISSION",
        page_reference="p. 42",
        document_uri="https://rights.example/grant/0001",
    )
    world["permission_one"] = fx.review_permission(
        world,
        world["permission_one"],
        decision="ACCEPT",
        review_note="Publisher grant on file",
    )
    world["format_review"] = fx.open_format_cycle(world, clock="2026-10-05T09:00:00Z")
    fx.record_screening(world, similarity_pct=25.0, excluded_quoted_pct=7.5)
    world["format_review"] = fx.decide_format_review(
        world,
        world["format_review"],
        decision="ACCEPT",
        critical_defect_count=1,
        major_defect_count=1,
        minor_defect_count=1,
        clock="2026-10-12T09:00:00Z",
    )
    world["permission_two"] = fx.document_permission(
        world,
        material_type="EXCERPT",
        rights_basis="FAIR_USE_ASSERTION",
        page_reference="p. 88",
        excerpt_word_count=250,
    )
    fx.set_clock("2026-12-04T10:00:00Z")
    return world


def _overpaying_deposit_payload(thesis_id: str) -> dict:
    """A deposit tendering 99,999 cents against a computed fee of nothing."""
    payload = create_repository_deposit_payload(
        thesis_id,
        abstract_word_count=200,
        subject_keywords=["figures", "fair use", "rights"],
        late_fee_paid_cents=99999,
    )
    payload["advisor_name"] = "Cara Cho"
    payload["department_code"] = "CS"
    return payload


def test_deposit_reports_incomplete_permissions_not_the_fee_mismatch(
    api: ApiClient,
) -> None:
    """The permission shortfall is reported ahead of the fiscal check.

    PRD §2.5: "**Remaining constraints, in this order**: `ERR_DEFECT_SCORE_REQUIRES_REVISIONS`, `ERR_PERMISSION_EVIDENCE_MISSING`, `ERR_FAIR_USE_LIMIT_EXCEEDED`, `ERR_EMBARGO_DURATION_EXCEEDS_CAP`, `ERR_PERMISSIONS_INCOMPLETE`, `ERR_EMBARGO_UNDECIDED`, `ERR_DEPOSIT_ALREADY_EXISTS`, `ERR_METADATA_INCOMPLETE`, and finally the fiscal check `ERR_LATE_FEE_MISMATCH`."

    Design: Difficulty/priority_pair_validation_conflict/business_referential_priority_beats_business_fiscal_priority_on_deposit
    """
    world = _accepted_document_with_one_unreviewed_permission()

    error = validate_error(
        api.create_repository_deposit(
            _overpaying_deposit_payload(world["thesis"]["id"]), ANALYST_TWO
        ),
        "ERR_PERMISSIONS_INCOMPLETE",
        422,
    )
    assert error["error_id"] != "ERR_LATE_FEE_MISMATCH"

    permission_one = get_success_data(
        api.list_thesis_permission_records(world["thesis"]["id"], REGISTRAR)
    )[0]
    assert permission_one["status"] == "ACCEPTED"
    permission_two = get_success_data(
        api.list_thesis_permission_records(world["thesis"]["id"], REGISTRAR)
    )[1]
    assert permission_two["status"] == "SUBMITTED"

    thesis = get_success_data(api.get_thesis(world["thesis"]["id"], REGISTRAR))
    assert thesis["documented_permission_count"] == 1
    assert thesis["workflow_state"] == "FORMAT_ACCEPTED"


def test_readiness_projection_names_the_same_blocking_error(api: ApiClient) -> None:
    """The rehearsal reports a nil fee and names the permission error as the blocker.

    PRD §3.8: "A read-only readiness projection replays the clearance evaluation and the late-fee arithmetic against the current logical clock and reports `thesis_id`, the current `workflow_state`, the `projection_variant` that would apply, the `outstanding_items` array, the `projected_late_fee_cents` a deposit would incur right now, and `next_blocking_error_id` — the identifier of the error the next deposit attempt would raise, or null when the deposit would succeed."

    Design: Difficulty/priority_pair_validation_conflict/business_referential_priority_beats_business_fiscal_priority_on_deposit
    """
    world = _accepted_document_with_one_unreviewed_permission()

    validate_error(
        api.create_repository_deposit(
            _overpaying_deposit_payload(world["thesis"]["id"]), ANALYST_TWO
        ),
        "ERR_PERMISSIONS_INCOMPLETE",
        422,
    )

    assert (
        get_success_data(
            api.get_thesis_repository_deposit(world["thesis"]["id"], REGISTRAR)
        )
        == []
    )

    readiness = get_success_data(
        api.get_deposit_readiness(world["thesis"]["id"], REGISTRAR)
    )
    assert readiness["projected_late_fee_cents"] == 0
    assert readiness["next_blocking_error_id"] == "ERR_PERMISSIONS_INCOMPLETE"
