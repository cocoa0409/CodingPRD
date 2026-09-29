"""Non-linear paths: a parallel dimension, a cyclic counter, and a branching fork.

None of these machines advances by simply walking a straight line, so each test
pins the path actually taken rather than the destination alone.
"""

from types import SimpleNamespace

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.assertions import (
    assert_importer_rollup,
    assert_money,
    assert_pair_dimensions,
)
from test_helpers.factories import exemption_determination_payload
from test_helpers.test_users import COMPLIANCE_OFFICER_HEADERS, make_qualified_individual_headers

JUICE_BASIS_NOTE = (
    "Importer receives written assurance that the juice HACCP regulation applies to this food"
)
JUICE_DETERMINATION_NOTE = (
    "Juice HACCP exemption confirmed against the product code and process category"
)


# --- The exemption dimension reaches eligibility on its own -----------------
def _claimed_juice_exemption(api: ApiClient) -> SimpleNamespace:
    """A juice pair with a CLAIMED juice-HACCP exemption and nothing else done."""
    fx.set_clock(api, fx.CLOCK_BASE)
    importer = fx.create_importer(api, small_importer_flag=False)
    qi_a = fx.create_qualified_individual(api, importer["id"])
    supplier = fx.create_supplier(api, importer["id"], approve_by_qi_id=None)
    food = fx.create_juice_food(api, importer["id"])
    pair = fx.create_pair(api, importer["id"], supplier["id"], food["id"], qi_a["id"])
    fx.claim_exemption(
        api,
        pair["id"],
        "JUICE_HACCP_CONTROL",
        qi_a["id"],
        basis_note=JUICE_BASIS_NOTE,
    )
    return SimpleNamespace(
        importer_id=importer["id"], qi_a_id=qi_a["id"], pair_id=pair["id"]
    )


def test_exemption_verification_makes_the_pair_eligible_with_verification_still_draft(
    api: ApiClient,
) -> None:
    """Two dimensions move in one request and the third deliberately does not.

    "Verification also moves `entry_eligibility_status` `PENDING -> ELIGIBLE` in
    the same request while deliberately leaving `verification_status` at `DRAFT`:
    a verified exemption makes a combination entry-eligible with no hazard
    analysis and no verification plan whatsoever." The flag
    `modified_requirements_only` "is true exactly when `exemption_status` is
    `VERIFIED` and `exemption_type` is either `US_CUSTOMER_WRITTEN_ASSURANCE` or
    `SMALL_IMPORTER_MODIFIED`", so a juice control leaves it false.

    Design: Difficulty/non_linear_state_machine/pair_exemption_dimension_grants_eligibility_while_verification_stays_draft
    """
    world = _claimed_juice_exemption(api)

    response = api.post_pair_exemption(
        world.pair_id,
        exemption_determination_payload(
            "VERIFY", determination_note=JUICE_DETERMINATION_NOTE
        ),
        COMPLIANCE_OFFICER_HEADERS,
    )

    pair = validate_success(response)
    assert_pair_dimensions(
        pair,
        verification_status="DRAFT",
        entry_eligibility_status="ELIGIBLE",
        exemption_status="VERIFIED",
    )
    assert pair["exemption_type"] == "JUICE_HACCP_CONTROL"
    assert pair["modified_requirements_only"] is False


def test_eligibility_by_exemption_leaves_the_verification_pipeline_empty(
    api: ApiClient,
) -> None:
    """No analysis was ever written, and the programme is still compliant.

    "Not every imported food needs a full verification programme." Because
    `blocked_pair_count` "is the number of that importer's combinations whose
    `entry_eligibility_status` is `BLOCKED`" and the importer has a currently
    trained designated individual, nothing pushes the programme off `COMPLIANT`.

    Design: Difficulty/non_linear_state_machine/pair_exemption_dimension_grants_eligibility_while_verification_stays_draft
    """
    world = _claimed_juice_exemption(api)

    fx.determine_exemption(
        api, world.pair_id, "VERIFY", determination_note=JUICE_DETERMINATION_NOTE
    )

    pair = fx.get_pair(api, world.pair_id)
    assert pair["hazard_analysis_count"] == 0
    assert pair["active_hazard_analysis_id"] is None
    assert_importer_rollup(
        fx.get_importer(api, world.importer_id),
        blocked_pair_count=0,
        program_status="COMPLIANT",
    )


# --- The revision counter tracks closed loops, not edits --------------------
def _activity_after_one_closed_loop(api: ApiClient) -> SimpleNamespace:
    """Propose, request changes, revise (loop 1 closed), then revise again in place."""
    world = fx.analyzed_program(api, hazards=[fx.HAZARD_LISTERIA])
    world.activity = fx.create_activity(
        api, world.pair_id, world.qi_a_id, world.qi_a_id, **fx.ACTIVITY_ONSITE_AUDIT
    )
    world.activity_id = world.activity["id"]
    fx.review_activity(
        api,
        world.activity_id,
        world.qi_b_id,
        "REQUEST_CHANGES",
        reviewer_note="Justify the frequency against the severity five hazard",
    )
    world.after_first_revision = fx.patch_activity(
        api,
        world.activity_id,
        world.qi_a_id,
        justification_text=(
            "Annual onsite audit of the foreign supplier with pathogen environmental "
            "monitoring"
        ),
    )
    world.after_self_loop = fx.patch_activity(
        api, world.activity_id, world.qi_a_id, window_end="2026-09-22T00:00:00Z"
    )
    return world


def test_revision_of_a_proposed_activity_is_a_self_loop_that_does_not_count(
    api: ApiClient,
) -> None:
    """The first loop counts once; editing again in place counts for nothing.

    "Revising an already `PROPOSED` activity is a self-loop `PROPOSED ->
    PROPOSED` that overwrites the fields but leaves `revision_count` untouched,
    because no review loop was closed."

    Design: Difficulty/non_linear_state_machine/activity_revision_cycle_counts_only_closed_review_loops
    """
    world = _activity_after_one_closed_loop(api)

    assert world.after_first_revision["revision_count"] == 1
    assert world.after_self_loop["status"] == "PROPOSED"
    assert world.after_self_loop["revision_count"] == 1
    assert world.after_self_loop["window_end"].startswith("2026-09-22T00:00:00")


def test_second_closed_review_loop_brings_the_revision_count_to_two(
    api: ApiClient,
) -> None:
    """Only the two `CHANGES_REQUESTED` exits are counted, so the total is 2.

    "Revising a `CHANGES_REQUESTED` activity moves it `CHANGES_REQUESTED ->
    PROPOSED` and increments `revision_count` by one, since a review loop was
    closed." A frequency of 2 on an onsite audit whose justification clears the
    length threshold weighs 20.00, and the combination's
    `adequacy_score_planned` stays at 0.00 while no activity is approved.

    Design: Difficulty/non_linear_state_machine/activity_revision_cycle_counts_only_closed_review_loops
    """
    world = _activity_after_one_closed_loop(api)
    fx.review_activity(
        api,
        world.activity_id,
        world.qi_b_id,
        "REQUEST_CHANGES",
        reviewer_note="Widen the audit window to cover the harvest peak",
    )

    response = api.patch_verification_activity(
        world.activity_id,
        {"frequency_per_year": 2, "window_end": "2026-09-25T00:00:00Z"},
        make_qualified_individual_headers(world.qi_a_id),
    )

    activity = validate_success(response)
    assert activity["status"] == "PROPOSED"
    assert activity["revision_count"] == 2
    assert activity["frequency_per_year"] == 2
    assert_money(activity["coverage_weight"], 20.00, "coverage_weight")
    assert activity["reviewed_by_qi_id"] == world.qi_b_id
    assert_money(
        fx.get_pair(api, world.pair_id)["adequacy_score_planned"],
        0.00,
        "adequacy_score_planned",
    )


# --- The decision fork: one branch blocks the whole supplier ----------------
def _suspended_with_exempt_sibling(api: ApiClient) -> SimpleNamespace:
    """A suspended supplier carrying one lapsed pair and one exempt sibling pair."""
    world = fx.verified_program(api)
    juice = fx.create_juice_food(api, world.importer_id)
    sibling = fx.create_pair(
        api, world.importer_id, world.supplier_id, juice["id"], world.qi_a_id
    )
    fx.claim_exemption(
        api,
        sibling["id"],
        "JUICE_HACCP_CONTROL",
        world.qi_a_id,
        basis_note="This juice is subject to the juice HACCP regulation at the processor",
    )
    world.sibling = fx.determine_exemption(
        api,
        sibling["id"],
        "VERIFY",
        determination_note="Exemption confirmed against the product code and process category",
    )
    world.sibling_id = sibling["id"]

    fx.set_clock(api, "2026-10-20T00:00:00Z")
    record = fx.file_record(
        api,
        world.activity_onsite["id"],
        world.qi_a_id,
        outcome="FAIL",
        performed_start="2026-09-12T00:00:00Z",
        performed_end="2026-09-14T00:00:00Z",
        findings_count=2,
        document_reference="AUD-2026-0912-RV",
    )
    fx.attest_record(
        api,
        record["id"],
        world.qi_b_id,
        attestation_note="Audit report reviewed and admitted into the supplier score",
    )
    action = fx.list_corrective_actions(api, supplier_id=world.supplier_id)[0]
    world.corrective_action = action
    world.corrective_action_id = action["id"]
    world.supplier_version = fx.get_supplier(api, world.supplier_id)["version"]
    return world


def test_suspension_branch_blocks_every_pair_of_the_supplier(api: ApiClient) -> None:
    """The exempt sibling is blocked even though the action never names it.

    "The action moves `OPEN -> IMPORT_SUSPENSION`. The supplier stays in
    `SUSPENDED_PENDING_REVIEW`. Every combination of that supplier whose
    `entry_eligibility_status` is `ELIGIBLE` moves `ELIGIBLE -> BLOCKED` -- every
    one, not only the combination named in the action's `pair_id`."

    Design: Difficulty/non_linear_state_machine/corrective_action_import_suspension_branch_blocks_exempt_sibling_pair
    """
    world = _suspended_with_exempt_sibling(api)

    action = fx.decide_corrective_action(
        api,
        world.corrective_action_id,
        "IMPORT_SUSPENSION",
        world.supplier_id,
        expected_supplier_version=world.supplier_version,
        rationale=(
            "Supplier failed onsite verification and cannot show adequate hazard control"
        ),
    )

    assert action["status"] == "IMPORT_SUSPENSION"
    assert action["decision"] == "IMPORT_SUSPENSION"
    assert action["pre_action_blocked_pair_count"] == 0
    assert action["supplier_version_at_decision"] == world.supplier_version
    assert fx.get_supplier(api, world.supplier_id)["status"] == "SUSPENDED_PENDING_REVIEW"
    assert_pair_dimensions(
        fx.get_pair(api, world.pair_id), entry_eligibility_status="BLOCKED"
    )
    assert_pair_dimensions(
        fx.get_pair(api, world.sibling_id),
        verification_status="DRAFT",
        entry_eligibility_status="BLOCKED",
        exemption_status="VERIFIED",
    )


def test_suspension_branch_drives_the_importer_roll_ups_to_two_blocked_pairs(
    api: ApiClient,
) -> None:
    """Both pairs count, and one non-closed action keeps the programme failing.

    "`blocked_pair_count` is the number of that importer's combinations whose
    `entry_eligibility_status` is `BLOCKED`. `open_corrective_action_count` is
    the number of corrective actions on that importer's suppliers whose `status`
    is `OPEN`, `SUPPLIER_REMEDIATION` or `IMPORT_SUSPENSION`."

    Design: Difficulty/non_linear_state_machine/corrective_action_import_suspension_branch_blocks_exempt_sibling_pair
    """
    world = _suspended_with_exempt_sibling(api)

    fx.decide_corrective_action(
        api,
        world.corrective_action_id,
        "IMPORT_SUSPENSION",
        world.supplier_id,
        expected_supplier_version=world.supplier_version,
    )

    assert_importer_rollup(
        fx.get_importer(api, world.importer_id),
        blocked_pair_count=2,
        open_corrective_action_count=1,
        program_status="NON_COMPLIANT",
    )


def test_remediation_branch_of_the_same_fork_leaves_the_sibling_eligible(
    api: ApiClient,
) -> None:
    """The other branch of the fork touches no eligibility at all.

    "Entry eligibility is deliberately untouched by this branch: no combination
    is blocked and no combination is unblocked, so the importer's
    `blocked_pair_count` does not move at all." The supplier instead "moves
    `SUSPENDED_PENDING_REVIEW -> CONDITIONALLY_APPROVED`".

    Design: Difficulty/non_linear_state_machine/corrective_action_import_suspension_branch_blocks_exempt_sibling_pair
    """
    world = _suspended_with_exempt_sibling(api)

    action = fx.decide_corrective_action(
        api,
        world.corrective_action_id,
        "SUPPLIER_REMEDIATION",
        world.supplier_id,
        expected_supplier_version=world.supplier_version,
    )

    assert action["status"] == "SUPPLIER_REMEDIATION"
    assert fx.get_supplier(api, world.supplier_id)["status"] == "CONDITIONALLY_APPROVED"
    assert_pair_dimensions(
        fx.get_pair(api, world.sibling_id), entry_eligibility_status="ELIGIBLE"
    )
    assert_importer_rollup(
        fx.get_importer(api, world.importer_id),
        blocked_pair_count=1,
        open_corrective_action_count=1,
    )
