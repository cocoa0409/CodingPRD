"""Version pinning on the two program-critical writes, and the modified-requirements path.

The PRD pins optimistic concurrency control to exactly two endpoints: the hazard-analysis
create (against the combination's ``version``) and the corrective-action decision (against
the supplier's ``version``). Both are exercised here sequentially -- read the parent, let an
intervening write bump the parent's version, then replay the stale value. The last test
covers the importer-level feature flag that unlocks the small-importer modified-requirements
claim.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as err
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.assertions import assert_pair_dimensions
from test_helpers.test_users import COMPLIANCE_OFFICER_HEADERS, make_qualified_individual_headers


def test_second_hazard_analysis_with_stale_expected_pair_version_rejected(api: ApiClient):
    """PRD §2.9: "Creating a hazard analysis — `POST /fsvp/hazard-analyses` — requires a
    non-optional `expected_pair_version` field carrying the client's last observed
    `version` of the target `SupplierFoodPair`. If that value does not equal the
    combination's current `version`, the create is rejected with `ERR_STALE_PAIR_VERSION`
    (HTTP 412)."
    PRD §3.3: "The combination's `hazard_analysis_count` is incremented — it counts every
    analysis ever opened on the combination, withdrawn ones included — and precisely
    because that counter moves, the create increments the combination's `version` by one,
    which is what makes a second create with the same `expected_pair_version` stale."

    Design: Corner/cross-cutting complexity layers/stale_expected_pair_version_on_a_second_hazard_analysis_returns_stale_pair_version
    """
    world = fx.single_qi_program(api)

    # PRD §2.5: `version` "starts at 1 and increments by exactly one on every mutation".
    stale_pair_version = world.pair["version"]
    assert stale_pair_version == 1, (
        f"a freshly created combination must start at version 1, got {stale_pair_version}"
    )

    first_analysis = fx.create_hazard_analysis(
        api,
        world.pair_id,
        world.qi_a_id,
        expected_pair_version=stale_pair_version,
        methodology_note="First pass hazard identification for frozen ready-to-eat fruit",
    )

    # Replaying the now-superseded version is the only guard on a second analysis.
    response = api.create_hazard_analysis(
        f.hazard_analysis_payload(
            world.pair_id,
            stale_pair_version,
            methodology_note=(
                "Second pass hazard identification opened from a stale view of the pair"
            ),
        ),
        make_qualified_individual_headers(world.qi_a_id),
    )
    validate_error(response, err.ERR_STALE_PAIR_VERSION)

    pair = fx.get_pair(api, world.pair_id)
    assert pair["version"] == 2, (
        f"the first analysis create bumps the combination to version 2, got {pair['version']}"
    )
    assert pair["hazard_analysis_count"] == 1, (
        "the refused create must not increment hazard_analysis_count, got "
        f"{pair['hazard_analysis_count']}"
    )

    # No withdrawal happened: the refusal precedes the create-with-supersede.
    analysis = fx.get_analysis(api, first_analysis["id"])
    assert analysis["status"] == "DRAFT", (
        f"the earlier analysis must remain DRAFT, got {analysis['status']}"
    )


def test_second_hazard_analysis_with_refreshed_pair_version_supersedes_the_draft(
    api: ApiClient,
):
    """PRD §2.9: "The accepted value is retained on the analysis as `pair_version_at_create`."
    PRD §3.3: "Opening a new analysis is a create-with-supersede: any analysis on the same
    combination that was still `DRAFT` moves `DRAFT → WITHDRAWN`, and no further hazards
    may be added to the withdrawn row."
    PRD §3.3: "The combination's `hazard_analysis_count` is incremented — it counts every
    analysis ever opened on the combination, withdrawn ones included — and precisely
    because that counter moves, the create increments the combination's `version` by one,
    which is what makes a second create with the same `expected_pair_version` stale."

    Design: Corner/cross-cutting complexity layers/refreshed_pair_version_admits_the_second_hazard_analysis_and_bumps_the_version_again
    """
    world = fx.single_qi_program(api)

    first_pair_version = world.pair["version"]
    first_analysis = fx.create_hazard_analysis(
        api,
        world.pair_id,
        world.qi_a_id,
        expected_pair_version=first_pair_version,
        methodology_note="First pass hazard identification for frozen ready-to-eat fruit",
    )

    # The client re-reads the combination before writing again.
    refreshed_pair_version = fx.get_pair(api, world.pair_id)["version"]
    assert refreshed_pair_version == 2 and first_pair_version == 1, (
        f"expected the combination to move 1 -> 2, got {first_pair_version} -> "
        f"{refreshed_pair_version}"
    )

    # PRD §4: opening a hazard analysis returns 201 Created.
    response = api.create_hazard_analysis(
        f.hazard_analysis_payload(
            world.pair_id,
            refreshed_pair_version,
            methodology_note=(
                "Second pass hazard identification opened from a fresh view of the pair"
            ),
        ),
        make_qualified_individual_headers(world.qi_a_id),
    )
    second_analysis = validate_success(response, 201)

    assert second_analysis["status"] == "DRAFT", (
        f"a new analysis starts in DRAFT, got {second_analysis['status']}"
    )
    assert second_analysis["pair_version_at_create"] == 2, (
        "the accepted expected_pair_version is retained as pair_version_at_create, got "
        f"{second_analysis['pair_version_at_create']}"
    )

    withdrawn = fx.get_analysis(api, first_analysis["id"])
    assert withdrawn["status"] == "WITHDRAWN", (
        f"the superseded DRAFT must be withdrawn, got {withdrawn['status']}"
    )

    pair = fx.get_pair(api, world.pair_id)
    assert pair["version"] == 3, (
        f"two analysis creates leave the combination at version 3, got {pair['version']}"
    )
    assert pair["hazard_analysis_count"] == 2, (
        "hazard_analysis_count counts every analysis ever opened, got "
        f"{pair['hazard_analysis_count']}"
    )


def test_corrective_action_decision_with_stale_expected_supplier_version_rejected(
    api: ApiClient,
):
    """PRD §2.9: "Recording a corrective-action decision — `POST
    /fsvp/corrective-actions/{id}/decision` — requires a non-optional
    `expected_supplier_version` field carrying the officer's last observed `version` of the
    action's `ForeignSupplier`. If that value does not equal the supplier's current
    `version`, the decision is rejected with `ERR_STALE_SUPPLIER_VERSION` (HTTP 412)."
    PRD §3.7: "A mismatched version is refused with `ERR_STALE_SUPPLIER_VERSION` before
    either branch runs."
    PRD §3.7: "Its `status` starts at `OPEN`, and its `decision`, `rationale`, `decided_at`,
    `closed_at` and `supplier_version_at_decision` are all null until the officer acts."

    Design: Corner/cross-cutting complexity layers/stale_expected_supplier_version_on_a_corrective_action_decision_returns_stale_supplier_version
    """
    # A failing attested record suspends the supplier, lapses the combination and
    # synthesises one OPEN corrective action.
    world = fx.suspended_program(api, with_entry=False)
    action_id = world.corrective_action_id
    assert action_id is not None, "the suspension cascade must synthesise a corrective action"

    # The officer reads the supplier, then an import-posture PATCH moves it underneath him.
    observed_supplier_version = fx.get_supplier(api, world.supplier_id)["version"]
    fx.set_supplier_compliance_status(
        api,
        world.supplier_id,
        "WARNING_LETTER",
        source_reference="FDA warning letter dated 2026-10-18",
    )

    response = api.post_corrective_action_decision(
        action_id,
        f.corrective_action_decision_payload(
            "IMPORT_SUSPENSION",
            observed_supplier_version,
            rationale=(
                "Suspending imports on a supplier picture read before the warning letter "
                "was recorded"
            ),
        ),
        COMPLIANCE_OFFICER_HEADERS,
    )
    validate_error(response, err.ERR_STALE_SUPPLIER_VERSION)

    action = fx.get_corrective_action(api, action_id)
    assert action["status"] == "OPEN", (
        f"the refused decision must leave the action OPEN, got {action['status']}"
    )
    assert action["decided_at"] is None, (
        f"decided_at stays null until the officer acts, got {action['decided_at']!r}"
    )
    assert action["supplier_version_at_decision"] is None, (
        "supplier_version_at_decision stays null until the officer acts, got "
        f"{action['supplier_version_at_decision']!r}"
    )

    supplier = fx.get_supplier(api, world.supplier_id)
    assert supplier["status"] == "SUSPENDED_PENDING_REVIEW", (
        f"the supplier keeps its cascade posture, got {supplier['status']}"
    )
    pair = fx.get_pair(api, world.pair_id)
    assert_pair_dimensions(pair, verification_status="VERIFICATION_LAPSED")

    # Re-reading the supplier and replaying the same decision with the fresh version
    # succeeds: PRD §3.7 branch B moves the action OPEN -> IMPORT_SUSPENSION.
    fresh_supplier_version = supplier["version"]
    replay = api.post_corrective_action_decision(
        action_id,
        f.corrective_action_decision_payload(
            "IMPORT_SUSPENSION",
            fresh_supplier_version,
            rationale=(
                "Suspending imports after re-reading the supplier record for this decision"
            ),
        ),
        COMPLIANCE_OFFICER_HEADERS,
    )
    decided = validate_success(replay, 200)
    assert decided["status"] == "IMPORT_SUSPENSION", (
        f"the replayed decision must land in IMPORT_SUSPENSION, got {decided['status']}"
    )


def test_small_importer_flag_unlocks_the_modified_requirements_exemption(api: ApiClient):
    """PRD §3.8: "One further gate applies only to `SMALL_IMPORTER_MODIFIED`: the importer's
    `small_importer_flag` must be true, or the claim is refused with
    `ERR_MODIFIED_REQUIREMENTS_NOT_AVAILABLE`."
    PRD §3.8: "It recomputes `modified_requirements_only`, which is true exactly when
    `exemption_status` is `VERIFIED` and `exemption_type` is either
    `US_CUSTOMER_WRITTEN_ASSURANCE` or `SMALL_IMPORTER_MODIFIED`, and false for every other
    verified exemption type."
    PRD §3.8: "Verification also moves `entry_eligibility_status` `PENDING → ELIGIBLE` in
    the same request while deliberately leaving `verification_status` at `DRAFT`: a verified
    exemption makes a combination entry-eligible with no hazard analysis and no
    verification plan whatsoever."
    PRD §3.8: "Every accepted action increments the combination's `version` by one, and any
    action that does not correspond to a permitted transition out of the current
    `exemption_status` is refused with `ERR_INVALID_STATE_TRANSITION`."

    Design: Corner/cross-cutting complexity layers/small_importer_flag_true_unlocks_the_modified_requirements_path
    """
    fx.set_clock(api, fx.CLOCK_BASE)
    importer = fx.create_small_importer(api, record_retention_months=36)

    # PRD §3.1: `record_retention_months` "is the retention period applied to every
    # verification record the importer ever files."
    assert importer["record_retention_months"] == 36, (
        f"the importer's retention period must be 36, got {importer['record_retention_months']}"
    )

    qi = fx.create_qualified_individual(api, importer["id"])
    supplier = fx.create_supplier(api, importer["id"])
    food = fx.create_food(api, importer["id"])
    pair = fx.create_pair(api, importer["id"], supplier["id"], food["id"], qi["id"])

    fx.claim_exemption(
        api,
        pair["id"],
        "SMALL_IMPORTER_MODIFIED",
        qi["id"],
        basis_note=(
            "Very small importer relying on modified requirements for this combination"
        ),
    )

    # PRD §4: an operation that drives a state machine returns 200 OK.
    response = api.post_pair_exemption(
        pair["id"],
        f.exemption_determination_payload(
            "VERIFY",
            determination_note="Small importer status verified from the filed sales records",
        ),
        COMPLIANCE_OFFICER_HEADERS,
    )
    verified = validate_success(response, 200)

    assert_pair_dimensions(
        verified,
        verification_status="DRAFT",
        entry_eligibility_status="ELIGIBLE",
        exemption_status="VERIFIED",
    )
    assert verified["exemption_type"] == "SMALL_IMPORTER_MODIFIED", (
        f"the claimed exemption_type must be retained, got {verified['exemption_type']}"
    )
    assert verified["modified_requirements_only"] is True, (
        "a verified SMALL_IMPORTER_MODIFIED exemption sets modified_requirements_only true, "
        f"got {verified['modified_requirements_only']!r}"
    )
    assert verified["version"] == 3, (
        f"create 1, CLAIM 2, VERIFY 3 leaves the combination at version 3, got "
        f"{verified['version']}"
    )
