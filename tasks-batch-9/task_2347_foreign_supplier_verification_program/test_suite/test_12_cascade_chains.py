"""Two cascades from two different kinds of trigger.

Admitted evidence drives a six-hop chain that ends at a held entry line; a
change of regulatory reference data drives a three-hop chain that deliberately
leaves entry eligibility alone.
"""

from types import SimpleNamespace

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.assertions import (
    assert_importer_rollup,
    assert_money,
    assert_pair_dimensions,
    assert_supplier_performance,
)
from test_helpers.factories import attestation_payload
from test_helpers.test_users import make_qualified_individual_headers

FAIL_ATTESTATION_NOTE = (
    "Audit report reviewed and admitted into the supplier performance score"
)


def _entered_program_with_unattested_fail(api: ApiClient) -> SimpleNamespace:
    """An accepted entry line, and a failed audit filed but not yet attested."""
    world = fx.entered_program(api)
    fx.set_clock(api, "2026-10-20T00:00:00Z")
    world.record = fx.file_record(
        api,
        world.activity_onsite["id"],
        world.qi_a_id,
        outcome="FAIL",
        performed_start="2026-09-12T00:00:00Z",
        performed_end="2026-09-14T00:00:00Z",
        findings_count=2,
        document_reference="AUD-2026-0912-RV",
    )
    world.record_id = world.record["id"]
    return world


def test_attestation_of_a_failed_audit_suspends_the_supplier(api: ApiClient) -> None:
    """Hops 1 and 2: the score is admitted and it breaches the threshold.

    "**Hop 1**: the record moves `RECEIVED -> ATTESTED`, `attested_by_qi_id` is
    set to the attester's `X-User-ID`, and the supplier's
    `performance_score_final` and `performance_sample_weight_total` are
    recomputed over attested records only. **Hop 2**: ... if
    `performance_score_final` is now strictly below 60.00, the supplier moves
    `APPROVED -> SUSPENDED_PENDING_REVIEW`".

    Design: Difficulty/transitive_cascade/fail_attestation_suspension_chain
    """
    world = _entered_program_with_unattested_fail(api)

    response = api.post_record_attestation(
        world.record_id,
        attestation_payload(attestation_note=FAIL_ATTESTATION_NOTE),
        make_qualified_individual_headers(world.qi_b_id),
    )

    record = validate_success(response)
    assert record["record_status"] == "ATTESTED"
    assert_money(record["record_points"], 10.00, "record_points")
    assert_money(record["weight"], 3.00, "weight")
    assert_supplier_performance(
        fx.get_supplier(api, world.supplier_id),
        final=10.00,
        weight_total=3.00,
        status="SUSPENDED_PENDING_REVIEW",
    )


def test_suspension_lapses_the_pair_blocks_it_and_holds_the_entry_line(
    api: ApiClient,
) -> None:
    """Hops 3 to 5: the chain reaches the entry line filed weeks earlier.

    "**Hop 3**: ... each of its combinations whose `verification_status` was
    `VERIFICATION_APPROVED` moves `VERIFICATION_APPROVED -> VERIFICATION_LAPSED`,
    and one corrective action is synthesised for each lapsed combination with
    `status` `OPEN`, `trigger_reason` `PERFORMANCE_SCORE_BREACH`". "**Hop 5**:
    because those combinations became `BLOCKED`, every entry line on them whose
    `status` is `SUBMITTED` or `ACCEPTED` moves to `HELD` with `held_reason`
    `PAIR_BLOCKED`."

    Design: Difficulty/transitive_cascade/fail_attestation_suspension_chain
    """
    world = _entered_program_with_unattested_fail(api)

    fx.attest_record(
        api, world.record_id, world.qi_b_id, attestation_note=FAIL_ATTESTATION_NOTE
    )

    assert_pair_dimensions(
        fx.get_pair(api, world.pair_id),
        verification_status="VERIFICATION_LAPSED",
        entry_eligibility_status="BLOCKED",
    )
    actions = fx.list_corrective_actions(api, supplier_id=world.supplier_id)
    assert len(actions) == 1
    assert actions[0]["status"] == "OPEN"
    assert actions[0]["trigger_reason"] == "PERFORMANCE_SCORE_BREACH"
    assert actions[0]["pre_action_blocked_pair_count"] == 0
    entry = fx.get_entry(api, world.entry_id)
    assert entry["status"] == "HELD"
    assert entry["held_reason"] == "PAIR_BLOCKED"


def test_suspension_cascade_recomputes_the_roll_ups_and_the_coverage_demand(
    api: ApiClient,
) -> None:
    """Hop 6, plus the hop-2 replan the collapsed relief forces.

    "**Hop 6**: the importer's `blocked_pair_count`, `open_corrective_action_count`
    and `program_status` are recomputed -- the programme lands on
    `NON_COMPLIANT`". And because "The relief factor is 1.0 when the supplier's
    `performance_score_final` is at or above 85.00, 0.5 when it is at or above
    70.00, and 0.0 otherwise", the fallen final score removes the relief, raising
    `required_coverage` and depressing the realized adequacy of the one activity
    that has attested evidence.

    Design: Difficulty/transitive_cascade/fail_attestation_suspension_chain
    """
    world = _entered_program_with_unattested_fail(api)

    fx.attest_record(
        api, world.record_id, world.qi_b_id, attestation_note=FAIL_ATTESTATION_NOTE
    )

    assert_importer_rollup(
        fx.get_importer(api, world.importer_id),
        blocked_pair_count=1,
        open_corrective_action_count=1,
        program_status="NON_COMPLIANT",
    )
    pair = fx.get_pair(api, world.pair_id)
    assert_money(pair["required_coverage"], 46.58, "required_coverage")
    assert_money(pair["adequacy_score_realized"], 21.47, "adequacy_score_realized")


def test_import_alert_re_tiers_every_combination_of_the_supplier(
    api: ApiClient,
) -> None:
    """Hop 1: a worsened posture raises the penalty, the tier and the demand.

    "Hop 1 recomputes, for every combination of that supplier,
    `composite_hazard_risk`, `risk_tier`, `required_annual_frequency`,
    `required_coverage`, `adequacy_score_planned` and `adequacy_score_realized`
    -- a worsened posture raises the supplier penalty and can therefore raise the
    tier and the required frequency." The posture write itself is not a
    suspension: it only supplies "a new `regulatory_compliance_status` together
    with a `source_reference` citing where the finding came from".

    Design: Difficulty/transitive_cascade/import_alert_replanning_chain
    """
    world = fx.verified_program(api)

    supplier = fx.set_supplier_compliance_status(
        api,
        world.supplier_id,
        "IMPORT_ALERT",
        source_reference="FDA import alert 99-35 published 2026-08-28",
    )

    assert supplier["regulatory_compliance_status"] == "IMPORT_ALERT"
    assert supplier["status"] == "APPROVED"
    pair = fx.get_pair(api, world.pair_id)
    assert pair["risk_tier"] == "HIGH"
    assert_money(pair["composite_hazard_risk"], 37.05, "composite_hazard_risk")
    assert pair["required_annual_frequency"] == 4
    assert_money(pair["required_coverage"], 55.58, "required_coverage")


def test_import_alert_forces_reassessment_and_sends_the_plan_back(
    api: ApiClient,
) -> None:
    """Hops 2 and 3, with entry eligibility deliberately untouched.

    "Hop 3 follows from hop 2: every activity on a combination that just entered
    `REASSESSMENT_REQUIRED` and whose `status` was `APPROVED` moves `APPROVED ->
    CHANGES_REQUESTED`, because the plan must be re-justified against the new
    frequency; with the approved set now empty, that combination's
    `adequacy_score_planned` recomputes to 0.00. The importer's `program_status`
    is recomputed at the end of the cascade and lands on `AT_RISK` by virtue of
    the combination sitting in `REASSESSMENT_REQUIRED`."

    Design: Difficulty/transitive_cascade/import_alert_replanning_chain
    """
    world = fx.verified_program(api)

    fx.set_supplier_compliance_status(
        api,
        world.supplier_id,
        "IMPORT_ALERT",
        source_reference="FDA import alert 99-35 published 2026-08-28",
    )

    for activity in (
        world.activity_onsite,
        world.activity_sampling,
        world.activity_records,
    ):
        assert fx.get_activity(api, activity["id"])["status"] == "CHANGES_REQUESTED"
    pair = fx.get_pair(api, world.pair_id)
    assert_pair_dimensions(
        pair,
        verification_status="REASSESSMENT_REQUIRED",
        entry_eligibility_status="ELIGIBLE",
    )
    assert_money(pair["adequacy_score_planned"], 0.00, "adequacy_score_planned")
    assert_importer_rollup(
        fx.get_importer(api, world.importer_id),
        blocked_pair_count=0,
        program_status="AT_RISK",
    )
