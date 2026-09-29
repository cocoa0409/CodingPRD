"""State-machine transitions and the cascades they trigger."""

from types import SimpleNamespace

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as err
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.assertions import (
    assert_importer_rollup,
    assert_money,
    assert_pair_dimensions,
    assert_supplier_performance,
)
from test_helpers.test_users import (
    COMPLIANCE_OFFICER_HEADERS,
    make_qualified_individual_headers,
)

# --- The world every test below builds from scratch --------------------------
#
# Logical clock 2026-09-01; importer "Northbrook Foods Import LLC"; Ada Ruiz
# (training 2025-06-01) and Ben Osei (training 2025-07-01), both designated;
# supplier "Rio Verde SA" on NO_ADVERSE_FINDINGS; ready-to-eat food for the
# general population.
#
# The single Listeria hazard scores severity 4 x probability 3 x ready-to-eat
# penalty 1.15 x foreign-supplier control factor 1.00 = 13.80, which is at or
# above 12.00 and therefore requires control (PRD §3.3). With a zero supplier
# penalty the pair's gross risk is 13.80, the tier is LOW, the relief base is
# 0.00, composite_hazard_risk is 13.80, required_annual_frequency is 1 and
# required_coverage is 13.80 x 1.5 = 20.70.
#
# The sampling activity weighs 6.0 x min(3, 4) x 1.0 = 18.00, so once APPROVED
# the pair's adequacy_score_planned is 100.00 x 18.00 / 20.70 = 86.96.

CLOCK = "2026-09-01T00:00:00Z"
RECORD_CLOCK = "2026-10-20T00:00:00Z"

LISTERIA = dict(
    hazard_type="BIOLOGICAL",
    hazard_name="Listeria monocytogenes",
    severity=4,
    probability=3,
    control_owner="FOREIGN_SUPPLIER",
)

SAMPLING_SPEC = dict(
    activity_type="SAMPLING_AND_TESTING",
    frequency_per_year=3,
    justification_text=(
        "Three sampling events per year covering the pathogen profile of this "
        "frozen ready to eat fruit"
    ),
    window_start="2026-10-01T00:00:00Z",
    window_end="2026-10-15T00:00:00Z",
)

FAIL_RECORD = dict(
    outcome="FAIL",
    performed_start="2026-10-05T00:00:00Z",
    performed_end="2026-10-06T00:00:00Z",
    findings_count=0,
    document_reference="LAB-2026-1005-A",
)


def _base(
    api: ApiClient,
    evaluate_supplier: bool = True,
    second_individual: bool = True,
    food_builder=fx.create_food,
) -> SimpleNamespace:
    """Clock, importer, designated individuals, supplier, food and one pair."""
    fx.set_clock(api, CLOCK)
    importer = fx.create_importer(api)
    qi_a = fx.create_qualified_individual(api, importer["id"])
    qi_b = (
        fx.create_second_qualified_individual(api, importer["id"])
        if second_individual
        else None
    )
    supplier = fx.create_supplier(
        api,
        importer["id"],
        approve_by_qi_id=qi_a["id"] if evaluate_supplier else None,
    )
    food = food_builder(api, importer["id"])
    pair = fx.create_pair(api, importer["id"], supplier["id"], food["id"], qi_a["id"])
    return SimpleNamespace(
        importer=importer,
        qi_a=qi_a,
        qi_b=qi_b,
        supplier=supplier,
        food=food,
        pair=pair,
    )


def _with_approved_analysis(api: ApiClient, world: SimpleNamespace) -> SimpleNamespace:
    """Open a hazard analysis carrying the single Listeria hazard and approve it."""
    analysis = fx.create_hazard_analysis(api, world.pair["id"], world.qi_a["id"])
    fx.add_hazard(api, analysis["id"], world.qi_a["id"], **LISTERIA)
    world.analysis = fx.approve_analysis(api, analysis["id"], world.qi_a["id"])
    world.analysis_id = analysis["id"]
    return world


def _with_approved_sampling_activity(
    api: ApiClient, world: SimpleNamespace
) -> SimpleNamespace:
    """Propose the sampling activity as Ada and let Ben approve it."""
    activity = fx.create_activity(
        api, world.pair["id"], world.qi_a["id"], world.qi_b["id"], **SAMPLING_SPEC
    )
    fx.review_activity(api, activity["id"], world.qi_b["id"], "APPROVE")
    world.activity = fx.get_activity(api, activity["id"])
    world.activity_id = activity["id"]
    return world


def _read_individual(api: ApiClient, importer_id: str, qi_id: str) -> dict:
    """Read one qualified individual out of its importer's roster."""
    rows, _meta = validate_paginated(
        api.list_importer_qualified_individuals(importer_id, COMPLIANCE_OFFICER_HEADERS)
    )
    matches = [row for row in rows if row["id"] == qi_id]
    assert matches, f"qualified individual {qi_id} missing from the importer roster"
    return matches[0]


# ---------------------------------------------------------------------------
# QualifiedIndividual designation lifecycle
# ---------------------------------------------------------------------------


def test_designate_proposed_individual_activates_and_flips_program_status(api):
    """PRD §3.1: "Designating a `PROPOSED` individual moves them `PROPOSED →
    ACTIVE`, but only if their `training_valid_until` is at or after the logical
    clock; stale training is refused with `ERR_QI_DESIGNATION_INVALID`. That
    transition recomputes the importer's `qualified_individual_designated` and
    then its `program_status`."
    PRD §2.4: "a qualified individual's `training_valid_until` is the
    individual's `training_completed_at` advanced by 36 calendar months"
    PRD §2.7: "An importer with no combinations at all but one `ACTIVE`
    qualified individual is `COMPLIANT`"

    Design: Corner/state_machines/qi_designation_moves_proposed_to_active_and_flips_program_status
    """
    fx.set_clock(api, CLOCK)
    importer = fx.create_importer(api)
    individual = fx.create_qualified_individual(api, importer["id"], designate=False)
    assert individual["status"] == "PROPOSED", "a proposed individual starts PROPOSED"

    designated = validate_success(
        api.post_designation(
            individual["id"],
            f.designation_payload(
                "DESIGNATE", note="Designated as the FSVP qualified individual of record"
            ),
            COMPLIANCE_OFFICER_HEADERS,
        )
    )

    assert designated["status"] == "ACTIVE", "DESIGNATE moves PROPOSED to ACTIVE"
    # 2025-06-01 advanced by 36 calendar months.
    assert str(designated["training_valid_until"]).startswith("2028-06-01"), (
        f"training_valid_until: expected 2028-06-01, "
        f"got {designated['training_valid_until']}"
    )
    assert_importer_rollup(
        fx.get_importer(api, importer["id"]),
        qualified_individual_designated=True,
        program_status="COMPLIANT",
    )


def test_designate_with_expired_training_returns_designation_invalid(api):
    """PRD §3.1: "Designating a `PROPOSED` individual moves them `PROPOSED →
    ACTIVE`, but only if their `training_valid_until` is at or after the logical
    clock; stale training is refused with `ERR_QI_DESIGNATION_INVALID`."
    PRD §2.7: "an importer with no `ACTIVE` qualified individual is
    `NON_COMPLIANT` no matter how healthy its combinations look, which is why
    lapsing a single designation is enough to flip the programme status."

    Design: Corner/state_machines/qi_designation_with_expired_training_returns_designation_invalid
    """
    fx.set_clock(api, CLOCK)
    importer = fx.create_importer(api)
    # Training finished 2022-01-01, so the 36-month window closed 2025-01-01 --
    # before the logical clock of 2026-09-01.
    individual = fx.create_qualified_individual(
        api,
        importer["id"],
        designate=False,
        full_name="Cal Devereux",
        email="cal@northbrook.example",
        qualification_summary=(
            "Historic PCQI certificate with no refresher training since 2022"
        ),
        training_completed_at="2022-01-01T00:00:00Z",
    )

    validate_error(
        api.post_designation(
            individual["id"],
            f.designation_payload("DESIGNATE"),
            COMPLIANCE_OFFICER_HEADERS,
        ),
        err.ERR_QI_DESIGNATION_INVALID,
    )

    stored = _read_individual(api, importer["id"], individual["id"])
    assert stored["status"] == "PROPOSED", "a refused designation leaves the row PROPOSED"
    assert str(stored["training_valid_until"]).startswith("2025-01-01"), (
        f"training_valid_until: expected 2025-01-01, got {stored['training_valid_until']}"
    )
    assert_importer_rollup(
        fx.get_importer(api, importer["id"]),
        qualified_individual_designated=False,
        program_status="NON_COMPLIANT",
    )


def test_second_designate_on_active_individual_rejected(api):
    """PRD §3.1: "The designation lifecycle is driven entirely by a
    `ComplianceOfficer` supplying an `action` of `DESIGNATE`, `RENEW_TRAINING`,
    `LAPSE` or `REVOKE`, optionally with a free-text `note`."
    PRD §3.1: "Any other combination of current status and requested `action` —
    including any write against `REVOKED` — is refused with
    `ERR_INVALID_STATE_TRANSITION`."

    Design: Corner/state_machines/second_designate_on_active_qi_rejected
    """
    fx.set_clock(api, CLOCK)
    importer = fx.create_importer(api)
    individual = fx.create_qualified_individual(api, importer["id"])
    assert individual["status"] == "ACTIVE", "setup must leave the individual ACTIVE"

    # ACTIVE + DESIGNATE is not one of the documented transitions: only
    # RENEW_TRAINING self-loops on an already-active individual.
    validate_error(
        api.post_designation(
            individual["id"],
            f.designation_payload("DESIGNATE"),
            COMPLIANCE_OFFICER_HEADERS,
        ),
        err.ERR_INVALID_STATE_TRANSITION,
    )

    stored = _read_individual(api, importer["id"], individual["id"])
    assert stored["status"] == "ACTIVE", "the refused replay must not disturb the row"
    assert_importer_rollup(
        fx.get_importer(api, importer["id"]), program_status="COMPLIANT"
    )


def test_lapsing_the_only_active_individual_bubbles_up_to_program_status(api):
    """PRD §3.1: "Lapsing an active individual moves them `ACTIVE → LAPSED` with
    no precondition, recomputing the same two importer fields; critically, a
    lapse does *not* touch the verification activities already assigned to that
    individual — those rows keep whatever `status` they hold, including
    `APPROVED`, and only new operations are gated on currency."
    PRD §2.7: "`qualified_individual_designated` is true exactly when the
    importer has at least one qualified individual whose `status` is `ACTIVE`
    and whose `training_valid_until` is at or after the logical clock."
    PRD §2.7: "The importer is `NON_COMPLIANT` when `blocked_pair_count` is
    greater than zero, or when `qualified_individual_designated` is false, or
    when at least one of its combinations has `verification_status` equal to
    `VERIFICATION_LAPSED`."

    Design: Corner/state_machines/qi_lapse_bubbles_up_to_importer_program_status
    """
    fx.set_clock(api, CLOCK)
    importer = fx.create_importer(api)
    individual = fx.create_qualified_individual(api, importer["id"])

    before = fx.get_importer(api, importer["id"])
    assert_importer_rollup(before, program_status="COMPLIANT")

    lapsed = validate_success(
        api.post_designation(
            individual["id"],
            f.designation_payload(
                "LAPSE", note="Refresher training not completed within the cycle"
            ),
            COMPLIANCE_OFFICER_HEADERS,
        )
    )
    assert lapsed["status"] == "LAPSED", "LAPSE moves ACTIVE to LAPSED"

    after = fx.get_importer(api, importer["id"])
    assert_importer_rollup(
        after,
        blocked_pair_count=0,
        qualified_individual_designated=False,
        program_status="NON_COMPLIANT",
    )


# ---------------------------------------------------------------------------
# ForeignSupplier evaluation
# ---------------------------------------------------------------------------


def test_supplier_evaluation_approve_records_status_and_last_evaluated_at(api):
    """PRD §3.2: "An `UNEVALUATED` supplier moves `UNEVALUATED → APPROVED` on
    `APPROVE`, which additionally requires `regulatory_compliance_status` to be
    exactly `NO_ADVERSE_FINDINGS`; it moves `UNEVALUATED →
    CONDITIONALLY_APPROVED` on `APPROVE_CONDITIONALLY`, which requires
    `regulatory_compliance_status` to be either `NO_ADVERSE_FINDINGS` or
    `WARNING_LETTER`."
    PRD §3.2: "Every accepted evaluation sets `last_evaluated_at` to the logical
    clock and increments the supplier's `version` by one; an evaluation that
    lands on `APPROVED` from `UNEVALUATED` also recomputes both performance
    variants, which are 100.00 while no records exist."

    Design: Corner/state_machines/supplier_evaluation_approve_records_status_and_last_evaluated_at
    """
    fx.set_clock(api, CLOCK)
    importer = fx.create_importer(api)
    qi_a = fx.create_qualified_individual(api, importer["id"])
    supplier = fx.create_supplier(api, importer["id"])
    assert supplier["status"] == "UNEVALUATED", "a new supplier starts UNEVALUATED"
    assert supplier["version"] == 1, "a freshly written row starts at version 1"

    evaluated = validate_success(
        api.post_supplier_evaluation(
            supplier["id"],
            f.evaluation_payload("APPROVE"),
            make_qualified_individual_headers(qi_a["id"]),
        )
    )

    assert_supplier_performance(
        evaluated,
        provisional=100.00,
        final=100.00,
        weight_total=0.00,
        status="APPROVED",
    )
    # last_evaluated_at is stamped from the logical clock, never wall time.
    assert str(evaluated["last_evaluated_at"]).startswith("2026-09-01T00:00:00"), (
        f"last_evaluated_at: expected the logical clock 2026-09-01T00:00:00, "
        f"got {evaluated['last_evaluated_at']}"
    )
    assert evaluated["version"] == 2, "the evaluation increments the version by one"


# ---------------------------------------------------------------------------
# HazardAnalysis lifecycle
# ---------------------------------------------------------------------------


def test_hazard_added_to_approved_analysis_rejected(api):
    """PRD §3.3: "Hazards may only be added while the analysis is `DRAFT`; an
    attempt against an `APPROVED`, `SUPERSEDED` or `WITHDRAWN` analysis is
    refused with `ERR_ANALYSIS_NOT_DRAFT`."
    PRD §3.3: "The `risk_total` is the sum of the `risk_score` values of every
    hazard in the analysis, whether or not they require control, rounded half up
    to two decimal places."

    Design: Corner/state_machines/hazard_added_to_approved_analysis_rejected
    """
    world = _base(api, evaluate_supplier=False, second_individual=False)
    _with_approved_analysis(api, world)
    assert world.analysis["status"] == "APPROVED", "setup must approve the analysis"

    validate_error(
        api.create_hazard(
            world.analysis_id,
            f.hazard_payload(
                hazard_type="PHYSICAL",
                hazard_name="Stone fragments",
                severity=2,
                probability=2,
                control_owner="FOREIGN_SUPPLIER",
            ),
            make_qualified_individual_headers(world.qi_a["id"]),
        ),
        err.ERR_ANALYSIS_NOT_DRAFT,
    )

    analysis = fx.get_analysis(api, world.analysis_id)
    assert analysis["status"] == "APPROVED", "the refused append must not reopen the row"
    assert analysis["hazard_count"] == 1, "no hazard was appended"
    assert_money(analysis["risk_total"], 13.80, "risk_total")
    assert_money(
        fx.get_pair(api, world.pair["id"])["composite_hazard_risk"],
        13.80,
        "composite_hazard_risk",
    )


def test_analysis_approval_blocked_by_lapsed_authoring_individual(api):
    """PRD §3.3: "The analysis must still be `DRAFT` (`ERR_ANALYSIS_NOT_DRAFT`),
    the acting individual must be `ACTIVE` with current training
    (`ERR_QI_DESIGNATION_INVALID`), and the analysis must contain at least one
    hazard row — an empty analysis documents nothing and is refused with
    `ERR_HAZARD_ANALYSIS_EMPTY`."
    PRD §3.3: "The combination's `active_hazard_analysis_id` is pointed at this
    analysis, and whatever analysis previously held that position moves
    `APPROVED → SUPERSEDED`; a superseded row accepts no further hazards but
    remains readable and available for inspection."
    PRD §3.3: "the hazard load is the sum of the `risk_score` values of only
    those hazards in the active analysis whose `requires_control` is true,
    rounded half up to two decimal places, and it is 0.00 when
    `active_hazard_analysis_id` is null"

    Design: Corner/state_machines/hazard_analysis_approval_blocked_by_lapsed_authoring_qi
    """
    world = _base(api, evaluate_supplier=False, second_individual=False)
    analysis = fx.create_hazard_analysis(api, world.pair["id"], world.qi_a["id"])
    fx.add_hazard(api, analysis["id"], world.qi_a["id"], **LISTERIA)
    # The analysis is a perfectly valid DRAFT; only the author's currency lapses.
    fx.designate_qualified_individual(
        api,
        world.qi_a["id"],
        "LAPSE",
        note="Refresher training not completed within the cycle",
    )

    validate_error(
        api.post_hazard_analysis_approval(
            analysis["id"],
            f.hazard_analysis_approval_payload(),
            make_qualified_individual_headers(world.qi_a["id"]),
        ),
        err.ERR_QI_DESIGNATION_INVALID,
    )

    stored = fx.get_analysis(api, analysis["id"])
    assert stored["status"] == "DRAFT", "the refused approval leaves the analysis DRAFT"
    assert stored.get("approved_at") is None, "approved_at is only set on success"

    pair = fx.get_pair(api, world.pair["id"])
    assert_pair_dimensions(pair, verification_status="DRAFT")
    assert pair.get("active_hazard_analysis_id") is None, (
        "no analysis became active, so active_hazard_analysis_id stays null"
    )
    assert_money(pair["composite_hazard_risk"], 0.00, "composite_hazard_risk")


# ---------------------------------------------------------------------------
# VerificationActivity lifecycle
# ---------------------------------------------------------------------------


def test_verification_activity_starts_in_proposed_with_zero_revisions(api):
    """PRD §3.4: "The new row starts in `status` `PROPOSED` with `revision_count`
    0, `reviewed_by_qi_id` null, and `proposed_by_qi_id` copied from
    `X-User-ID`; its `coverage_weight` is computed immediately, and the assigned
    individual's `active_assignment_count` is recomputed."
    PRD §3.4: "Concretely, the activity's `coverage_weight` is the type weight
    for its `activity_type` — 10.0 for `ONSITE_AUDIT`, 6.0 for
    `SAMPLING_AND_TESTING`, 3.0 for `RECORDS_REVIEW`, and 2.0 for
    `OTHER_SUPPLIER_EVALUATION` — multiplied by the smaller of its
    `frequency_per_year` and 4, multiplied by a justification factor of 1.0 when
    `justification_text` is at least 40 characters long and 0.5 otherwise, with
    the product rounded half up to two decimal places."
    PRD §3.4: "The **PLANNED** variant, surfaced as `adequacy_score_planned`,
    takes as its input set every activity on the combination whose `status` is
    `APPROVED`; it is recomputed whenever an activity's status or fields change,
    when a hazard analysis is approved, and when the supplier's compliance
    status or final performance score moves, and it is the variant that gates
    verification approval."
    PRD §3.1: "A computed `active_assignment_count` — the number of verification
    activities assigned to this individual whose `status` is `PROPOSED`,
    `CHANGES_REQUESTED` or `APPROVED` — starts at 0."

    Design: Corner/state_machines/verification_activity_starts_in_proposed_with_zero_revisions
    """
    world = _base(api, evaluate_supplier=False)
    _with_approved_analysis(api, world)

    activity = validate_success(
        api.create_verification_activity(
            f.activity_payload(world.pair["id"], world.qi_b["id"], **SAMPLING_SPEC),
            make_qualified_individual_headers(world.qi_a["id"]),
        ),
        201,
    )

    assert activity["status"] == "PROPOSED", "a selected activity starts PROPOSED"
    assert activity["revision_count"] == 0, "no review loop has closed yet"
    assert activity.get("reviewed_by_qi_id") is None, "nobody has reviewed it yet"
    assert activity["proposed_by_qi_id"] == world.qi_a["id"]
    assert activity["assigned_qi_id"] == world.qi_b["id"]
    # 6.0 for SAMPLING_AND_TESTING x min(3, 4) x justification factor 1.0.
    assert_money(activity["coverage_weight"], 18.00, "coverage_weight")
    assert activity["version"] == 1, "a freshly written row starts at version 1"

    assignee = _read_individual(api, world.importer["id"], world.qi_b["id"])
    assert assignee["active_assignment_count"] == 1, (
        "the assignee now holds one PROPOSED activity"
    )

    # The weight exists before any review, but only APPROVED activities feed the
    # planned adequacy score.
    assert_money(
        fx.get_pair(api, world.pair["id"])["adequacy_score_planned"],
        0.00,
        "adequacy_score_planned",
    )


def test_activity_review_approve_syncs_pair_adequacy_planned(api):
    """PRD §3.4: "Approving moves the activity `PROPOSED → APPROVED`; it
    additionally requires the reviewer to be `ACTIVE` with current training and
    requires the parent combination not to be `RETIRED`, a stale combination
    being refused with `ERR_INVALID_STATE_TRANSITION`."
    PRD §3.4: "Approval records `reviewed_by_qi_id` as the reviewer's
    `X-User-ID`, recomputes the activity's `coverage_weight`, and recomputes
    both of the combination's adequacy variants."
    PRD §3.4: "Divide 100.00 times that sum by the larger of the combination's
    `required_coverage` and 1.00 — the denominator floor of 1.00 keeps a
    zero-coverage combination from dividing by zero."
    PRD §3.4: "The **REALIZED** variant, surfaced as `adequacy_score_realized`,
    takes as its input set the `APPROVED` activities that have at least one
    verification record with `record_status` `ATTESTED`; it is recomputed on
    record attestation and rescission and is reporting-only — it never blocks a
    write."

    Design: Corner/state_machines/activity_review_approve_syncs_pair_adequacy_planned
    """
    world = _base(api, evaluate_supplier=False)
    _with_approved_analysis(api, world)
    activity = fx.create_activity(
        api, world.pair["id"], world.qi_a["id"], world.qi_b["id"], **SAMPLING_SPEC
    )

    before = fx.get_pair(api, world.pair["id"])
    assert_money(before["adequacy_score_planned"], 0.00, "adequacy_score_planned before")

    reviewed = validate_success(
        api.post_activity_review(
            activity["id"],
            f.activity_review_payload(
                "APPROVE",
                reviewer_note="Sampling plan matches the pathogen profile of the food",
            ),
            make_qualified_individual_headers(world.qi_b["id"]),
        )
    )

    assert reviewed["status"] == "APPROVED", "APPROVE moves PROPOSED to APPROVED"
    assert reviewed["reviewed_by_qi_id"] == world.qi_b["id"]
    assert_money(reviewed["coverage_weight"], 18.00, "coverage_weight")

    after = fx.get_pair(api, world.pair["id"])
    # 100.00 x 18.00 / max(20.70, 1.00) = 86.96.
    assert_money(after["adequacy_score_planned"], 86.96, "adequacy_score_planned after")
    assert_money(after["adequacy_score_realized"], 0.00, "adequacy_score_realized")
    assert_pair_dimensions(after, verification_status="HAZARD_ANALYZED")


# ---------------------------------------------------------------------------
# VerificationRecord lifecycle
# ---------------------------------------------------------------------------


def test_attestation_on_rescinded_record_rejected(api):
    """PRD §3.6: "A second `QualifiedIndividual` attests the record with an
    `attestation_note`; the record must be `RECEIVED` (otherwise
    `ERR_RECORD_NOT_ATTESTABLE`), the attester must be `ACTIVE` with current
    training (otherwise `ERR_QI_DESIGNATION_INVALID`), and the attester's
    `X-User-ID` must differ from the record's `submitted_by_qi_id` (otherwise
    `ERR_SEGREGATION_OF_DUTIES`)."
    PRD §3.6: "A `QualifiedIndividual` supplies a `reason`; the record's
    `record_status` must be `RECEIVED` or `ATTESTED`, and a record already
    `RESCINDED` is refused with `ERR_RECORD_NOT_ATTESTABLE`."
    PRD §3.2: "A new supplier starts in `status` `UNEVALUATED`, with
    `performance_score_provisional` and `performance_score_final` both at
    100.00, `performance_sample_weight_total` at 0.00, and
    `open_corrective_action_count` at 0."

    Design: Corner/state_machines/attestation_on_rescinded_record_rejected
    """
    world = _base(api)
    _with_approved_analysis(api, world)
    _with_approved_sampling_activity(api, world)

    fx.set_clock(api, RECORD_CLOCK)
    record = fx.file_record(api, world.activity_id, world.qi_a["id"], **FAIL_RECORD)
    fx.rescind_record(
        api,
        record["id"],
        world.qi_a["id"],
        reason="Laboratory reported a chain of custody break and voided the result",
    )

    validate_error(
        api.post_record_attestation(
            record["id"],
            f.attestation_payload(
                attestation_note="Attempting to attest the voided sampling result"
            ),
            make_qualified_individual_headers(world.qi_b["id"]),
        ),
        err.ERR_RECORD_NOT_ATTESTABLE,
    )

    stored = fx.get_record(api, record["id"])
    assert stored["record_status"] == "RESCINDED", "RESCINDED is terminal for a record"
    assert stored.get("attested_by_qi_id") is None, (
        "the refused attestation must not stamp attested_by_qi_id"
    )

    # A rescinded record never enters the FINAL input set, so the weight total
    # stays at zero and the score stays at the no-evidence value.
    assert_supplier_performance(
        fx.get_supplier(api, world.supplier["id"]),
        final=100.00,
        weight_total=0.00,
        status="APPROVED",
    )


def test_rescinding_a_received_record_restores_only_the_provisional_score(api):
    """PRD §3.6: "Rescinding a `RECEIVED` record moves it `RECEIVED → RESCINDED`
    and recomputes only `performance_score_provisional`, since the record was
    never in the final input set; `performance_score_final` is unchanged."
    PRD §3.6: "The **PROVISIONAL** variant, surfaced as
    `performance_score_provisional`, takes every record on the supplier's
    combinations whose `record_status` is `RECEIVED` or `ATTESTED`; it is
    recomputed on filing, attestation and rescission and never gates a state
    transition."
    PRD §3.6: "If the weight total is 0.00 the score is exactly 100.00 — no
    evidence is not bad evidence — and otherwise the score is the weighted sum
    divided by the weight total, rounded half up to two decimal places."
    PRD §3.9: "Every verification record's `retained_until` is its
    `performed_end` advanced by the importer's `record_retention_months` in
    calendar months, and its `available_for_inspection` flag is true exactly
    when the record's `record_status` is not `RESCINDED` — that is, when it is
    `RECEIVED` or `ATTESTED` — and the evaluation instant is at or before
    `retained_until`."

    Design: Corner/state_machines/record_rescission_before_attestation_restores_provisional_score
    """
    world = _base(api)
    _with_approved_analysis(api, world)
    _with_approved_sampling_activity(api, world)

    fx.set_clock(api, RECORD_CLOCK)
    record = fx.file_record(api, world.activity_id, world.qi_a["id"], **FAIL_RECORD)

    # FAIL scores 20 points on a SAMPLING_AND_TESTING weight of 2.0 x recency
    # 1.0, so the merely received record drives the provisional score to 20.00
    # and leaves the final score alone.
    before = fx.get_supplier(api, world.supplier["id"])
    assert_supplier_performance(
        before, provisional=20.00, final=100.00, weight_total=0.00
    )

    rescinded = validate_success(
        api.post_record_rescission(
            record["id"],
            f.rescission_payload(
                reason="Laboratory reported a chain of custody break and voided the result"
            ),
            make_qualified_individual_headers(world.qi_a["id"]),
        )
    )
    assert rescinded["record_status"] == "RESCINDED"

    assert fx.get_record(api, record["id"])["available_for_inspection"] is False, (
        "a rescinded record leaves the availability bucket"
    )

    after = fx.get_supplier(api, world.supplier["id"])
    assert_supplier_performance(
        after,
        provisional=100.00,
        final=100.00,
        weight_total=0.00,
        status="APPROVED",
    )
    assert_money(
        fx.get_pair(api, world.pair["id"])["adequacy_score_realized"],
        0.00,
        "adequacy_score_realized",
    )
    assert_importer_rollup(
        fx.get_importer(api, world.importer["id"]), open_corrective_action_count=0
    )


# ---------------------------------------------------------------------------
# CorrectiveAction decision fork
# ---------------------------------------------------------------------------


def test_corrective_action_remediation_branch_keeps_the_pair_blocked(api):
    """PRD §3.7: "The action moves `OPEN → SUPPLIER_REMEDIATION`. The supplier
    moves `SUSPENDED_PENDING_REVIEW → CONDITIONALLY_APPROVED`, because the
    officer has judged the establishment salvageable. Every combination of that
    supplier whose `verification_status` is `VERIFICATION_LAPSED` moves
    `VERIFICATION_LAPSED → REASSESSMENT_REQUIRED`, and the importer's
    `program_status` is recomputed. Entry eligibility is deliberately untouched
    by this branch: no combination is blocked and no combination is unblocked,
    so the importer's `blocked_pair_count` does not move at all."
    PRD §3.7: "Both branches record the chosen `decision`, set `decided_at` to
    the logical clock, store the `rationale`, retain the accepted version as
    `supplier_version_at_decision`, and increment the supplier's `version` by
    one."
    PRD §2.7: "`open_corrective_action_count` is the number of corrective
    actions on that importer's suppliers whose `status` is `OPEN`,
    `SUPPLIER_REMEDIATION` or `IMPORT_SUSPENSION`."

    Design: Corner/state_machines/corrective_action_supplier_remediation_branch_keeps_pair_blocked
    """
    world = _base(api)
    _with_approved_analysis(api, world)
    _with_approved_sampling_activity(api, world)
    approved = fx.approve_pair_verification(api, world.pair["id"], world.qi_a["id"])
    assert_pair_dimensions(
        approved,
        verification_status="VERIFICATION_APPROVED",
        entry_eligibility_status="ELIGIBLE",
    )

    # A failed sampling result drives performance_score_final to 20.00, which is
    # strictly below 60.00: the supplier is suspended, the pair lapses and is
    # blocked, and one corrective action is synthesised.
    fx.set_clock(api, RECORD_CLOCK)
    record = fx.file_record(api, world.activity_id, world.qi_b["id"], **FAIL_RECORD)
    fx.attest_record(api, record["id"], world.qi_a["id"])

    actions = fx.list_corrective_actions(
        api, pair_id=world.pair["id"], status="OPEN"
    )
    assert len(actions) == 1, f"expected one open corrective action, got {len(actions)}"
    action_id = actions[0]["id"]
    supplier_version = fx.get_supplier(api, world.supplier["id"])["version"]

    decided = validate_success(
        api.post_corrective_action_decision(
            action_id,
            f.corrective_action_decision_payload(
                "SUPPLIER_REMEDIATION",
                supplier_version,
                rationale=(
                    "Supplier submitted a sanitation remediation plan and "
                    "requested a re-audit"
                ),
            ),
            COMPLIANCE_OFFICER_HEADERS,
        )
    )

    assert decided["status"] == "SUPPLIER_REMEDIATION"
    assert decided["decision"] == "SUPPLIER_REMEDIATION"
    assert str(decided["decided_at"]).startswith("2026-10-20T00:00:00"), (
        f"decided_at: expected the logical clock 2026-10-20T00:00:00, "
        f"got {decided['decided_at']}"
    )
    assert decided["supplier_version_at_decision"] == supplier_version
    assert decided["pre_action_blocked_pair_count"] == 0, (
        "the snapshot is the block count as it stood before the suspension cascade"
    )

    assert_supplier_performance(
        fx.get_supplier(api, world.supplier["id"]),
        final=20.00,
        status="CONDITIONALLY_APPROVED",
    )
    assert_pair_dimensions(
        fx.get_pair(api, world.pair["id"]),
        verification_status="REASSESSMENT_REQUIRED",
        entry_eligibility_status="BLOCKED",
    )
    assert_importer_rollup(
        fx.get_importer(api, world.importer["id"]),
        blocked_pair_count=1,
        open_corrective_action_count=1,
    )


# ---------------------------------------------------------------------------
# The three independent status dimensions of a supplier-food combination
# ---------------------------------------------------------------------------


def test_verified_exemption_moves_eligibility_while_verification_stays_draft(api):
    """PRD §3.8: "Verification of a claim is the officer's determination and
    moves `CLAIMED → VERIFIED` with no further precondition."
    PRD §3.8: "It recomputes `modified_requirements_only`, which is true exactly
    when `exemption_status` is `VERIFIED` and `exemption_type` is either
    `US_CUSTOMER_WRITTEN_ASSURANCE` or `SMALL_IMPORTER_MODIFIED`, and false for
    every other verified exemption type."
    PRD §3.8: "Verification also moves `entry_eligibility_status` `PENDING →
    ELIGIBLE` in the same request while deliberately leaving
    `verification_status` at `DRAFT`: a verified exemption makes a combination
    entry-eligible with no hazard analysis and no verification plan whatsoever."
    PRD §3.3: "the hazard load is the sum of the `risk_score` values of only
    those hazards in the active analysis whose `requires_control` is true,
    rounded half up to two decimal places, and it is 0.00 when
    `active_hazard_analysis_id` is null"

    Design: Corner/state_machines/pair_dimensions_move_independently_when_exemption_verified
    """
    world = _base(
        api,
        evaluate_supplier=False,
        second_individual=False,
        food_builder=fx.create_juice_food,
    )
    assert_pair_dimensions(
        world.pair,
        verification_status="DRAFT",
        entry_eligibility_status="PENDING",
        exemption_status="NONE",
    )
    fx.claim_exemption(
        api,
        world.pair["id"],
        "JUICE_HACCP_CONTROL",
        world.qi_a["id"],
        basis_note=(
            "Juice is produced under a compliant juice HACCP program at the "
            "processing facility"
        ),
    )

    verified = validate_success(
        api.post_pair_exemption(
            world.pair["id"],
            f.exemption_determination_payload(
                "VERIFY",
                determination_note=(
                    "Juice HACCP records reviewed and the exemption is verified"
                ),
            ),
            COMPLIANCE_OFFICER_HEADERS,
        )
    )

    assert_pair_dimensions(
        verified,
        verification_status="DRAFT",
        entry_eligibility_status="ELIGIBLE",
        exemption_status="VERIFIED",
    )
    assert verified["exemption_type"] == "JUICE_HACCP_CONTROL"
    assert verified.get("active_hazard_analysis_id") is None, (
        "an exempt combination needs no hazard analysis at all"
    )
    assert verified["modified_requirements_only"] is False, (
        "a juice HACCP exemption is not a modified-requirements exemption"
    )
    assert_money(verified["composite_hazard_risk"], 0.00, "composite_hazard_risk")
    assert_importer_rollup(
        fx.get_importer(api, world.importer["id"]), blocked_pair_count=0
    )


def test_exemption_revoke_blocks_only_the_pair_without_independent_verification(api):
    """PRD §3.8: "Revoking a verified exemption is the officer's act and moves
    `VERIFIED → REVOKED`, setting `modified_requirements_only` back to false."
    PRD §3.8: "If its `verification_status` is `VERIFICATION_APPROVED`, the
    combination stands on its own verification and its eligibility is
    untouched."
    PRD §3.8: "If it is anything else, the exemption was the only thing
    supporting eligibility, and a second hop follows: `entry_eligibility_status`
    moves `ELIGIBLE → BLOCKED`."
    PRD §2.7: "`blocked_pair_count` is the number of that importer's
    combinations whose `entry_eligibility_status` is `BLOCKED`."
    PRD §2.7: "The importer is `NON_COMPLIANT` when `blocked_pair_count` is
    greater than zero, or when `qualified_individual_designated` is false, or
    when at least one of its combinations has `verification_status` equal to
    `VERIFICATION_LAPSED`."

    Design: Corner/state_machines/exemption_revoke_blocks_only_the_pair_without_independent_verification
    """
    # Pair one earns its eligibility the long way (full verification) and then
    # also carries a verified written-assurance exemption. Pair two, on a juice
    # food, has nothing but its verified exemption.
    world = _base(api)
    _with_approved_analysis(api, world)
    _with_approved_sampling_activity(api, world)
    fx.approve_pair_verification(api, world.pair["id"], world.qi_a["id"])
    fx.claim_exemption(
        api,
        world.pair["id"],
        "US_CUSTOMER_WRITTEN_ASSURANCE",
        world.qi_a["id"],
        basis_note=(
            "The US customer provided written assurance that it will control the hazard"
        ),
    )
    fx.determine_exemption(api, world.pair["id"], "VERIFY")

    juice_food = fx.create_juice_food(api, world.importer["id"])
    exempt_pair = fx.create_pair(
        api,
        world.importer["id"],
        world.supplier["id"],
        juice_food["id"],
        world.qi_a["id"],
    )
    fx.claim_exemption(
        api,
        exempt_pair["id"],
        "JUICE_HACCP_CONTROL",
        world.qi_a["id"],
        basis_note=(
            "Juice is produced under a compliant juice HACCP program at the "
            "processing facility"
        ),
    )
    fx.determine_exemption(api, exempt_pair["id"], "VERIFY")

    revoked_exempt = validate_success(
        api.post_pair_exemption(
            exempt_pair["id"],
            f.exemption_determination_payload(
                "REVOKE",
                determination_note="Juice HACCP program lapsed at the processing facility",
            ),
            COMPLIANCE_OFFICER_HEADERS,
        )
    )
    revoked_verified = validate_success(
        api.post_pair_exemption(
            world.pair["id"],
            f.exemption_determination_payload(
                "REVOKE",
                determination_note="US customer withdrew its written assurance",
            ),
            COMPLIANCE_OFFICER_HEADERS,
        )
    )

    assert_pair_dimensions(
        revoked_exempt,
        verification_status="DRAFT",
        entry_eligibility_status="BLOCKED",
        exemption_status="REVOKED",
    )
    assert_pair_dimensions(
        revoked_verified,
        verification_status="VERIFICATION_APPROVED",
        entry_eligibility_status="ELIGIBLE",
        exemption_status="REVOKED",
    )
    assert revoked_verified["modified_requirements_only"] is False

    assert_importer_rollup(
        fx.get_importer(api, world.importer["id"]),
        blocked_pair_count=1,
        program_status="NON_COMPLIANT",
    )
