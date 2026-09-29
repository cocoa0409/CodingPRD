"""State machines that loop and state machines that run on two independent axes.

Both instances here exercise paths a linear happy-path walk never reaches: the
policy review cycle taken twice, and the supply axis moving while the
authorization axis stands still.
"""
from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import BCM_HEADERS, COUNSEL_2_HEADERS, api_client
from test_helpers.assertions import assert_same_instant
from test_helpers.factories import (
    policy_publish_payload,
    policy_review_decision_payload,
    pricing_policy_payload,
)
from test_helpers.fixtures import (
    create_authorized_reseller,
    create_published_policy,
    hold_supply,
    pin_clock,
    read_agreement,
    read_policy,
    read_reseller,
    release_supply,
    run_sweep,
)

CLOCK_AUG_01 = "2026-08-01T00:00:00Z"
FIRST_RETURN_NOTES = "Ladder thresholds need a plain-English gloss."
SECOND_RETURN_NOTES = "Discount attribution cap must be restated in the definition."
APPROVAL_NOTES = "Antitrust review cleared."


def _draft_policy():
    pin_clock(CLOCK_AUG_01)
    return get_success_data(
        api_client.create_pricing_policy(
            pricing_policy_payload(
                cure_window_days=10,
                suspension_points_threshold=6,
                termination_points_threshold=12,
                suspension_cooling_off_days=14,
            ),
            BCM_HEADERS,
        )
    )


def _submit(policy_id):
    return validate_success(api_client.submit_policy_review(policy_id, BCM_HEADERS))


def _return_for_revision(policy_id, notes):
    return validate_success(
        api_client.decide_policy_review(
            policy_id,
            policy_review_decision_payload("RETURN_FOR_REVISION", legal_review_notes=notes),
            COUNSEL_2_HEADERS,
        )
    )


# --------------------------------------------------------------------------- #
# Instance 1 — the legal review cycle taken twice before approval
# --------------------------------------------------------------------------- #
def test_each_return_for_revision_sends_the_draft_back_and_climbs_the_revision_number():
    """The DRAFT to IN_LEGAL_REVIEW to DRAFT loop may be walked repeatedly.

    PRD: "This is a genuine loop — the same document may cycle `DRAFT →
    IN_LEGAL_REVIEW → DRAFT` any number of times, with `revision_number` climbing on
    every return."

    Design: Difficulty/non_linear_state_machine/pricing_policy_legal_review_revision_cycle_twice
    """
    policy = _draft_policy()
    assert policy["status"] == "DRAFT"
    assert policy["revision_number"] == 1
    assert policy["version"] == 1

    in_review = _submit(policy["id"])
    assert in_review["status"] == "IN_LEGAL_REVIEW"
    assert in_review["revision_number"] == 1

    returned = _return_for_revision(policy["id"], FIRST_RETURN_NOTES)
    assert returned["status"] == "DRAFT"
    assert returned["revision_number"] == 2
    assert returned["legal_review_notes"] == FIRST_RETURN_NOTES
    assert returned["reviewed_by_user_id"] == "counsel-2"

    _submit(policy["id"])
    returned_again = _return_for_revision(policy["id"], SECOND_RETURN_NOTES)
    assert returned_again["status"] == "DRAFT"
    assert returned_again["revision_number"] == 3
    assert returned_again["legal_review_notes"] == SECOND_RETURN_NOTES


def test_approval_records_the_notes_without_touching_the_revision_number():
    """Approval is the branch that leaves the revision counter alone.

    PRD: "A decision of `APPROVE_FOR_PUBLICATION` moves the document
    `IN_LEGAL_REVIEW → APPROVED`: it records `legal_review_notes` and
    `reviewed_by_user_id` and advances `version`, but does **not** touch
    `revision_number`."

    Design: Difficulty/non_linear_state_machine/pricing_policy_legal_review_revision_cycle_twice
    """
    policy = _draft_policy()
    _submit(policy["id"])
    _return_for_revision(policy["id"], FIRST_RETURN_NOTES)
    _submit(policy["id"])
    _return_for_revision(policy["id"], SECOND_RETURN_NOTES)
    _submit(policy["id"])

    approved = validate_success(
        api_client.decide_policy_review(
            policy["id"],
            policy_review_decision_payload(
                "APPROVE_FOR_PUBLICATION", legal_review_notes=APPROVAL_NOTES
            ),
            COUNSEL_2_HEADERS,
        )
    )
    assert approved["status"] == "APPROVED"
    assert approved["revision_number"] == 3
    assert approved["legal_review_notes"] == APPROVAL_NOTES
    assert approved["reviewed_by_user_id"] == "counsel-2"


def test_every_step_of_the_cycle_advances_the_policy_version_by_one():
    """Seven transitions leave the row on version eight.

    PRD: "`version` is an integer that starts at 1 when the row is created and
    increases by exactly 1 on every mutation of that row."

    Design: Difficulty/non_linear_state_machine/pricing_policy_legal_review_revision_cycle_twice
    """
    policy = _draft_policy()
    _submit(policy["id"])
    _return_for_revision(policy["id"], FIRST_RETURN_NOTES)
    _submit(policy["id"])
    _return_for_revision(policy["id"], SECOND_RETURN_NOTES)
    _submit(policy["id"])
    validate_success(
        api_client.decide_policy_review(
            policy["id"],
            policy_review_decision_payload(
                "APPROVE_FOR_PUBLICATION", legal_review_notes=APPROVAL_NOTES
            ),
            COUNSEL_2_HEADERS,
        )
    )
    published = validate_success(
        api_client.publish_policy(
            policy["id"], policy_publish_payload(CLOCK_AUG_01), COUNSEL_2_HEADERS
        )
    )

    assert published["status"] == "PUBLISHED"
    assert published["revision_number"] == 3
    assert published["version"] == 8
    assert published["published_by_user_id"] == "counsel-2"
    assert published["superseded_by_policy_id"] is None
    assert_same_instant(published["effective_from"], CLOCK_AUG_01, "effective_from")

    reread = read_policy(policy["id"])
    assert reread["version"] == 8
    assert reread["legal_review_notes"] == APPROVAL_NOTES


# --------------------------------------------------------------------------- #
# Instance 2 — the supply axis moves while the authorization axis stands still
# --------------------------------------------------------------------------- #
def _setup_expiring_agreement():
    """An authorized reseller whose agreement term ends on the first of September."""
    pin_clock(CLOCK_AUG_01)
    policy = create_published_policy()
    reseller, agreement = create_authorized_reseller(
        policy["id"],
        reseller_overrides={"primary_channel": "OWN_WEBSITE"},
        agreement_overrides={
            "permitted_channels": ["OWN_WEBSITE"],
            "term_ends_at": "2026-09-01T00:00:00Z",
        },
    )
    return {"policy": policy, "reseller": reseller, "agreement": agreement}


def test_a_quality_hold_and_its_release_leave_the_authorization_axis_untouched():
    """A reseller sitting on a warehouse hold is still authorized on paper.

    PRD: "Placing an `OPEN` reseller on hold moves `OPEN → HOLD` with `hold_reason`
    set to `QUALITY_OBLIGATION`, requires the reseller's `authorization_status` not to
    be `TERMINATED`, and advances the reseller's `version`; the authorization axis is
    untouched, so a reseller sitting on a quality hold is still `AUTHORIZED`."

    Design: Difficulty/non_linear_state_machine/reseller_supply_axis_moves_without_authorization_axis
    """
    world = _setup_expiring_agreement()
    assert world["reseller"]["authorization_status"] == "AUTHORIZED"
    assert world["reseller"]["supply_status"] == "OPEN"
    assert world["reseller"]["hold_reason"] == "NONE"

    held = hold_supply(world["reseller"]["id"])
    assert held["supply_status"] == "HOLD"
    assert held["hold_reason"] == "QUALITY_OBLIGATION"
    assert held["authorization_status"] == "AUTHORIZED"

    released = release_supply(world["reseller"]["id"])
    assert released["supply_status"] == "OPEN"
    assert released["hold_reason"] == "NONE"
    assert released["authorization_status"] == "AUTHORIZED"


def test_agreement_expiry_holds_supply_while_leaving_the_reseller_authorized():
    """The sweep pushes supply to hold and deliberately leaves authorization alone.

    PRD: "When the sweep observes that `term_ends_at` is at or before the current
    clock, the agreement moves `ACTIVE → EXPIRED` with `closed_reason` recorded as
    `TERM_EXPIRED` and its `version` advanced, and the reseller's supply axis is
    pushed to `HOLD` with `hold_reason` `AGREEMENT_EXPIRED` while its
    `authorization_status` is left exactly as it was — the clearest demonstration of
    axis independence in the system, since a reseller with a lapsed agreement remains
    `AUTHORIZED` on paper but receives no goods."

    Design: Difficulty/non_linear_state_machine/reseller_supply_axis_moves_without_authorization_axis
    """
    world = _setup_expiring_agreement()
    hold_supply(world["reseller"]["id"])
    release_supply(world["reseller"]["id"])

    pin_clock("2026-09-02T00:00:00Z")
    sweep = run_sweep()
    assert sweep["expired_agreements"] == 1
    assert sweep["reinstated_resellers"] == 0

    agreement = read_agreement(world["agreement"]["id"])
    assert agreement["status"] == "EXPIRED"
    assert agreement["closed_reason"] == "TERM_EXPIRED"

    reseller = read_reseller(world["reseller"]["id"])
    assert reseller["authorization_status"] == "AUTHORIZED"
    assert reseller["supply_status"] == "HOLD"
    assert reseller["hold_reason"] == "AGREEMENT_EXPIRED"
    assert reseller["terminated_at"] is None
    assert reseller["suspension_ends_at"] is None


def test_three_supply_axis_moves_advance_exactly_three_reseller_versions():
    """Hold, release and sweep expiry are three separate mutations of one row.

    PRD: "Whenever a workflow described in §3 says that an operation "bumps" or
    "advances" a row's version, that means the row's `version` increases by 1 and its
    `updated_at` is refreshed to the current logical clock."

    Design: Difficulty/non_linear_state_machine/reseller_supply_axis_moves_without_authorization_axis
    """
    world = _setup_expiring_agreement()
    version_at_activation = read_reseller(world["reseller"]["id"])["version"]

    hold_supply(world["reseller"]["id"])
    release_supply(world["reseller"]["id"])
    pin_clock("2026-09-02T00:00:00Z")
    run_sweep()

    reseller = read_reseller(world["reseller"]["id"])
    assert reseller["version"] == version_at_activation + 3
