"""Writes refused because of state that lives on a *different* entity.

In each scenario the target row itself is in a perfectly acceptable state; what
stops the write is the state of a neighbour -- an individual, a plan step, a
supplier, or a record filed on another entity entirely.
"""

from types import SimpleNamespace

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import api_errors as err
from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.assertions import (
    assert_importer_rollup,
    assert_money,
    assert_pair_dimensions,
)
from test_helpers.factories import (
    SMALL_IMPORTER_DNB,
    SMALL_IMPORTER_UFI,
    corrective_action_closure_payload,
    entry_submission_payload,
    record_payload,
    verification_approval_payload,
)
from test_helpers.test_users import (
    COMPLIANCE_OFFICER_HEADERS,
    ENTRY_FILER_HEADERS,
    make_qualified_individual_headers,
)


# --- The pair is ready; its designated individual is not --------------------
def _analyzed_pair_whose_only_individual_lapsed(api: ApiClient) -> SimpleNamespace:
    """A HAZARD_ANALYZED pair whose sole designated individual has lapsed."""
    world = fx.single_qi_program(api)
    analysis = fx.create_hazard_analysis(api, world.pair_id, world.qi_a_id)
    fx.add_hazard(api, analysis["id"], world.qi_a_id, **fx.HAZARD_LISTERIA)
    fx.approve_analysis(api, analysis["id"], world.qi_a_id)
    world.lapsed_individual = fx.designate_qualified_individual(
        api,
        world.qi_a_id,
        "LAPSE",
        note="Training certificate expired during the internal program review",
    )
    return world


def test_verification_approval_is_refused_because_the_designated_individual_lapsed(
    api: ApiClient,
) -> None:
    """Every pair-local precondition holds; the individual's own state does not.

    "Lapsing an active individual moves them `ACTIVE -> LAPSED` with no
    precondition". The approval then fails on the first of the eight substantive
    gates: "The acting individual must be `ACTIVE` with `training_valid_until` at
    or after the logical clock, or `ERR_QI_DESIGNATION_INVALID`."

    Design: Difficulty/cross_entity_state_dependency/pair_approval_blocked_by_lapsed_designated_qi
    """
    world = _analyzed_pair_whose_only_individual_lapsed(api)

    response = api.post_pair_verification_approval(
        world.pair_id,
        verification_approval_payload(
            approval_note=(
                "Approval attempted by the designated but now lapsed qualified individual"
            )
        ),
        make_qualified_individual_headers(world.qi_a_id),
    )

    validate_error(response, err.ERR_QI_DESIGNATION_INVALID, 422)
    assert world.lapsed_individual["status"] == "LAPSED"
    assert_pair_dimensions(
        fx.get_pair(api, world.pair_id),
        verification_status="HAZARD_ANALYZED",
        entry_eligibility_status="PENDING",
    )


def test_the_lapse_alone_already_made_the_program_non_compliant(
    api: ApiClient,
) -> None:
    """The neighbour's state change is visible on the importer as well.

    "`qualified_individual_designated` is true exactly when the importer has at
    least one qualified individual whose `status` is `ACTIVE` and whose
    `training_valid_until` is at or after the logical clock." And "an importer with
    no `ACTIVE` qualified individual is `NON_COMPLIANT` no matter how healthy its
    combinations look, which is why lapsing a single designation is enough to flip
    the programme status."

    Design: Difficulty/cross_entity_state_dependency/pair_approval_blocked_by_lapsed_designated_qi
    """
    world = _analyzed_pair_whose_only_individual_lapsed(api)

    api.post_pair_verification_approval(
        world.pair_id,
        verification_approval_payload(),
        make_qualified_individual_headers(world.qi_a_id),
    )

    assert_importer_rollup(
        fx.get_importer(api, world.importer_id),
        blocked_pair_count=0,
        qualified_individual_designated=False,
        program_status="NON_COMPLIANT",
    )


# --- The record is fine; the plan step it hangs from was never reviewed ------
def _unreviewed_onsite_activity(api: ApiClient) -> SimpleNamespace:
    """An analyzed pair carrying one PROPOSED onsite audit that nobody reviewed."""
    world = fx.analyzed_program(api, hazards=[fx.HAZARD_LISTERIA])
    world.activity = fx.create_activity(
        api, world.pair_id, world.qi_a_id, world.qi_a_id, **fx.ACTIVITY_ONSITE_AUDIT
    )
    world.activity_id = world.activity["id"]
    fx.set_clock(api, "2026-10-20T00:00:00Z")
    return world


AUDIT_RECORD = dict(
    outcome="PASS",
    performed_start="2026-09-12T00:00:00Z",
    performed_end="2026-09-14T00:00:00Z",
    findings_count=0,
    document_reference="AUD-2026-0912-RV",
)


def test_record_filing_is_refused_while_the_parent_activity_is_still_proposed(
    api: ApiClient,
) -> None:
    """The window and the outcome are valid; the plan step's status is not.

    "The named activity's `status` must be `APPROVED`, or the filing is refused
    with `ERR_ACTIVITY_NOT_APPROVED` -- evidence may not be filed against a plan
    step that was never approved, nor against one that has been retired."

    Design: Difficulty/cross_entity_state_dependency/record_submission_blocked_by_unreviewed_activity
    """
    world = _unreviewed_onsite_activity(api)

    response = api.create_verification_record(
        record_payload(world.activity_id, **AUDIT_RECORD),
        make_qualified_individual_headers(world.qi_a_id),
    )

    validate_error(response, err.ERR_ACTIVITY_NOT_APPROVED, 409)
    assert fx.get_activity(api, world.activity_id)["status"] == "PROPOSED"


def test_refused_record_filing_moves_neither_the_evidence_set_nor_the_advisory_score(
    api: ApiClient,
) -> None:
    """Nothing was filed, so even the advisory number is untouched.

    "Filing recomputes the supplier's `performance_score_provisional` and leaves
    `performance_score_final` untouched -- a merely received record moves the
    advisory number and has no state effect at all." With no record at all, "If
    the weight total is 0.00 the score is exactly 100.00".

    Design: Difficulty/cross_entity_state_dependency/record_submission_blocked_by_unreviewed_activity
    """
    world = _unreviewed_onsite_activity(api)

    api.create_verification_record(
        record_payload(world.activity_id, **AUDIT_RECORD),
        make_qualified_individual_headers(world.qi_a_id),
    )

    rows, meta = validate_paginated(
        api.list_verification_records(
            COMPLIANCE_OFFICER_HEADERS, {"activity_id": world.activity_id}
        )
    )
    assert rows == []
    assert meta["total_count"] == 0
    supplier = fx.get_supplier(api, world.supplier_id)
    assert_money(
        supplier["performance_score_provisional"],
        100.00,
        "performance_score_provisional",
    )


# --- Eligible by exemption, yet the supplier still gates the filing ----------
MODIFIED_ENTRY = dict(
    entry_number="ENT2026555",
    entry_line_number=1,
    dnb_number_submitted=SMALL_IMPORTER_DNB,
    ufi_submitted=SMALL_IMPORTER_UFI,
    arrival_date="2026-09-20T00:00:00Z",
)


def _modified_requirements_pair_with_unevaluated_supplier(
    api: ApiClient,
) -> SimpleNamespace:
    """A very small importer's eligible pair whose supplier was never evaluated."""
    return fx.exempt_program(
        api,
        exemption_type="SMALL_IMPORTER_MODIFIED",
        small_importer=True,
        evaluate_supplier_first=False,
    )


def test_entry_filing_under_modified_requirements_still_requires_supplier_approval(
    api: ApiClient,
) -> None:
    """Gates one and two pass on the exemption; gate three still bites.

    "Third, supplier approval is required conditionally rather than universally --
    the supplier's `status` must be `APPROVED` or `CONDITIONALLY_APPROVED` when the
    combination's eligibility rests on full verification or on a
    modified-requirements exemption, that is when `modified_requirements_only` is
    true, and the check is skipped entirely for a combination whose
    `exemption_status` is `VERIFIED` with `modified_requirements_only` false; a
    failure reports `ERR_SUPPLIER_NOT_APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/entry_filing_blocked_by_unevaluated_supplier_under_modified_requirements
    """
    world = _modified_requirements_pair_with_unevaluated_supplier(api)

    response = api.create_entry_submission(
        entry_submission_payload(world.pair_id, **MODIFIED_ENTRY), ENTRY_FILER_HEADERS
    )

    validate_error(response, err.ERR_SUPPLIER_NOT_APPROVED, 422)
    assert fx.get_supplier(api, world.supplier_id)["status"] == "UNEVALUATED"


def test_the_refused_filing_leaves_the_eligible_exempt_pair_exactly_as_it_was(
    api: ApiClient,
) -> None:
    """The pair really was eligible, which is what makes the refusal cross-entity.

    "A new supplier starts in `status` `UNEVALUATED`". The flag
    `modified_requirements_only` "is true exactly when `exemption_status` is
    `VERIFIED` and `exemption_type` is either `US_CUSTOMER_WRITTEN_ASSURANCE` or
    `SMALL_IMPORTER_MODIFIED`".

    Design: Difficulty/cross_entity_state_dependency/entry_filing_blocked_by_unevaluated_supplier_under_modified_requirements
    """
    world = _modified_requirements_pair_with_unevaluated_supplier(api)

    api.create_entry_submission(
        entry_submission_payload(world.pair_id, **MODIFIED_ENTRY), ENTRY_FILER_HEADERS
    )

    pair = fx.get_pair(api, world.pair_id)
    assert_pair_dimensions(
        pair, entry_eligibility_status="ELIGIBLE", exemption_status="VERIFIED"
    )
    assert pair["modified_requirements_only"] is True
    rows, meta = validate_paginated(
        api.list_entry_submissions(COMPLIANCE_OFFICER_HEADERS, {"pair_id": world.pair_id})
    )
    assert rows == []
    assert meta["total_count"] == 0


# --- Closure needs evidence that does not exist yet -------------------------
def _remediating_action_without_post_decision_evidence(
    api: ApiClient,
) -> SimpleNamespace:
    """A SUPPLIER_REMEDIATION action whose only PASS-free history predates it."""
    world = fx.suspended_program(api, with_entry=False)
    world.corrective_action = fx.decide_corrective_action(
        api,
        world.corrective_action_id,
        "SUPPLIER_REMEDIATION",
        world.supplier_id,
        rationale="Supplier submitted a remediation plan for the sanitation findings",
    )
    return world


def test_resolved_closure_is_refused_without_a_post_decision_passing_record(
    api: ApiClient,
) -> None:
    """The missing ingredient lives on another entity entirely.

    "There must exist a verification record on an activity of the action's
    `pair_id` whose `record_status` is `ATTESTED`, whose `outcome` is `PASS`, and
    whose `performed_end` is strictly after the action's `decided_at` --
    re-verification performed *after* the decision, not evidence recycled from
    before it. Absent such a record the closure is refused with
    `ERR_REVERIFICATION_MISSING`."

    Design: Difficulty/cross_entity_state_dependency/corrective_action_closure_blocked_by_missing_post_decision_pass_record
    """
    world = _remediating_action_without_post_decision_evidence(api)

    response = api.post_corrective_action_closure(
        world.corrective_action_id,
        corrective_action_closure_payload(
            "CLOSE_RESOLVED",
            closure_note="Closure attempted with only the pre-decision audit history on file",
        ),
        COMPLIANCE_OFFICER_HEADERS,
    )

    validate_error(response, err.ERR_REVERIFICATION_MISSING, 422)
    action = fx.get_corrective_action(api, world.corrective_action_id)
    assert action["status"] == "SUPPLIER_REMEDIATION"
    assert action["closed_at"] is None


def test_the_refused_closure_leaves_the_remediation_posture_in_place(
    api: ApiClient,
) -> None:
    """Nothing of the compensating chain ran, so the block survives the attempt.

    "The supplier moves `SUSPENDED_PENDING_REVIEW -> CONDITIONALLY_APPROVED`,
    because the officer has judged the establishment salvageable. Every combination
    of that supplier whose `verification_status` is `VERIFICATION_LAPSED` moves
    `VERIFICATION_LAPSED -> REASSESSMENT_REQUIRED`". "Entry eligibility is
    deliberately untouched by this branch", so the combination blocked by the
    suspension cascade is still blocked.

    Design: Difficulty/cross_entity_state_dependency/corrective_action_closure_blocked_by_missing_post_decision_pass_record
    """
    world = _remediating_action_without_post_decision_evidence(api)

    api.post_corrective_action_closure(
        world.corrective_action_id,
        corrective_action_closure_payload("CLOSE_RESOLVED"),
        COMPLIANCE_OFFICER_HEADERS,
    )

    assert fx.get_supplier(api, world.supplier_id)["status"] == "CONDITIONALLY_APPROVED"
    assert_pair_dimensions(
        fx.get_pair(api, world.pair_id),
        verification_status="REASSESSMENT_REQUIRED",
        entry_eligibility_status="BLOCKED",
    )
    assert_importer_rollup(
        fx.get_importer(api, world.importer_id),
        blocked_pair_count=1,
        open_corrective_action_count=1,
        program_status="NON_COMPLIANT",
    )
