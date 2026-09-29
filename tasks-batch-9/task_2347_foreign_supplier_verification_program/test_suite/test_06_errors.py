"""One test per catalogued refusal: the error id and its HTTP status.

Every test drives the real HTTP API, builds its own world from an empty database
and asserts the refusal the product requirements name for that situation, plus
the state the refusal must leave untouched.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
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
)
from test_helpers.test_users import (
    COMPLIANCE_OFFICER_HEADERS,
    ENTRY_FILER_HEADERS,
    make_qualified_individual_headers,
)

# A frequency justification well past the 40-character full-credit boundary.
SAMPLING_JUSTIFICATION = (
    "Three sampling events per year covering the pathogen profile of this "
    "frozen ready to eat fruit"
)


def _sampling_activity_payload(pair_id: str, assigned_qi_id: str, **overrides):
    """Three-times-a-year sampling in the window [2026-10-01, 2026-10-15)."""
    kwargs = dict(
        activity_type="SAMPLING_AND_TESTING",
        frequency_per_year=3,
        justification_text=SAMPLING_JUSTIFICATION,
        window_start="2026-10-01T00:00:00Z",
        window_end="2026-10-15T00:00:00Z",
    )
    kwargs.update(overrides)
    return f.activity_payload(pair_id, assigned_qi_id, **kwargs)


def _assert_same_instant(actual, expected_prefix: str, label: str) -> None:
    """Assert an instant field carries the expected UTC date and time-of-day."""
    assert actual is not None, f"{label} is missing"
    assert str(actual).startswith(expected_prefix), (
        f"{label}: expected the instant {expected_prefix}, got {actual}"
    )


# ---------------------------------------------------------------------------
# Existence rungs: one distinct 404 code per entity
# ---------------------------------------------------------------------------


def test_get_importer_with_unknown_id_returns_importer_not_found(api: ApiClient):
    """PRD §2.11: "The `importer_id` in path or body resolves to an `Importer` —
    `ERR_IMPORTER_NOT_FOUND` (404), on the importer read, the records package, the
    importer's qualified-individual / supplier / food lists, and on
    qualified-individual, supplier, food and combination creates."

    Design: Corner/errors/get_importer_with_unknown_id_returns_importer_not_found
    """
    fx.set_clock(api, fx.CLOCK_BASE)

    validate_error(
        api.get_importer(NON_EXISTENT_UUID, COMPLIANCE_OFFICER_HEADERS),
        err.ERR_IMPORTER_NOT_FOUND,
    )


def test_designation_on_unknown_qi_returns_qi_not_found(api: ApiClient):
    """PRD §2.11: "The `{id}` path segment, or `designated_qi_id`, or
    `assigned_qi_id`, resolves to a `QualifiedIndividual` — `ERR_QI_NOT_FOUND`
    (404), on designation, combination create, activity create and activity
    revision."
    The body is a valid DESIGNATE action, so the existence rung must answer
    before the transition rung.

    Design: Corner/errors/designation_on_unknown_qi_returns_qi_not_found
    """
    fx.set_clock(api, fx.CLOCK_BASE)

    validate_error(
        api.post_designation(
            NON_EXISTENT_UUID,
            f.designation_payload("DESIGNATE"),
            COMPLIANCE_OFFICER_HEADERS,
        ),
        err.ERR_QI_NOT_FOUND,
    )


def test_get_foreign_supplier_with_unknown_id_returns_supplier_not_found(api: ApiClient):
    """PRD §2.11: "The `{id}` path segment or `supplier_id` resolves to a
    `ForeignSupplier` — `ERR_SUPPLIER_NOT_FOUND` (404), on the supplier read, the
    compliance-status update, supplier evaluation, and combination create."

    Design: Corner/errors/get_foreign_supplier_with_unknown_id_returns_supplier_not_found
    """
    fx.set_clock(api, fx.CLOCK_BASE)

    validate_error(
        api.get_foreign_supplier(NON_EXISTENT_UUID, COMPLIANCE_OFFICER_HEADERS),
        err.ERR_SUPPLIER_NOT_FOUND,
    )


def test_pair_create_with_unknown_food_id_returns_food_not_found(api: ApiClient):
    """PRD §2.11: "`food_id` resolves to a `Food` — `ERR_FOOD_NOT_FOUND` (404), on
    combination create."
    PRD §2.10: "Body-borne foreign keys are resolved in the same fixed order as
    the refusal ladder in §2.11: importer first, then qualified individual, then
    supplier, then food, then combination, then hazard analysis, then verification
    activity, then verification record, then corrective action, then entry
    submission."

    Design: Corner/errors/pair_create_with_unknown_food_id_returns_food_not_found
    """
    fx.set_clock(api, fx.CLOCK_BASE)
    importer = fx.create_importer(api)
    qi_a = fx.create_qualified_individual(api, importer["id"])
    supplier = fx.create_supplier(api, importer["id"])

    validate_error(
        api.create_supplier_food_pair(
            f.pair_payload(
                importer["id"], supplier["id"], NON_EXISTENT_UUID, qi_a["id"]
            ),
            COMPLIANCE_OFFICER_HEADERS,
        ),
        err.ERR_FOOD_NOT_FOUND,
    )

    pairs, meta = validate_paginated(
        api.list_supplier_food_pairs(
            COMPLIANCE_OFFICER_HEADERS, {"importer_id": importer["id"]}
        )
    )
    assert pairs == [], f"no combination may be created, got {pairs}"
    assert meta["total_count"] == 0, (
        f"total_count: expected 0 combinations, got {meta['total_count']}"
    )


def test_get_hazard_analysis_with_unknown_id_returns_hazard_analysis_not_found(
    api: ApiClient,
):
    """PRD §2.11: "The `{id}` path segment resolves to a `HazardAnalysis` —
    `ERR_HAZARD_ANALYSIS_NOT_FOUND` (404), on the analysis read, analysis
    approval, hazard create and hazard list."

    Design: Corner/errors/get_hazard_analysis_with_unknown_id_returns_hazard_analysis_not_found
    """
    fx.set_clock(api, fx.CLOCK_BASE)

    validate_error(
        api.get_hazard_analysis(NON_EXISTENT_UUID, COMPLIANCE_OFFICER_HEADERS),
        err.ERR_HAZARD_ANALYSIS_NOT_FOUND,
    )


def test_get_verification_record_with_unknown_id_returns_record_not_found(api: ApiClient):
    """PRD §2.11: "The `{id}` path segment resolves to a `VerificationRecord` —
    `ERR_RECORD_NOT_FOUND` (404), on the record read, attestation and rescission."
    The read also accepts the availability-recomputation parameter described in
    PRD §3.9 — "The evaluation instant is the supplied `as_of_iso8601` when one is
    given and the logical clock otherwise." — yet a missing row must still 404.

    Design: Corner/errors/get_verification_record_with_unknown_id_returns_record_not_found
    """
    fx.set_clock(api, fx.CLOCK_BASE)

    validate_error(
        api.get_verification_record(
            NON_EXISTENT_UUID,
            COMPLIANCE_OFFICER_HEADERS,
            {"as_of_iso8601": "2027-01-01T00:00:00Z"},
        ),
        err.ERR_RECORD_NOT_FOUND,
    )


def test_get_corrective_action_with_unknown_id_returns_corrective_action_not_found(
    api: ApiClient,
):
    """PRD §2.11: "The `{id}` path segment resolves to a `CorrectiveAction` —
    `ERR_CORRECTIVE_ACTION_NOT_FOUND` (404), on the action read, decision and
    closure."
    PRD §3.7: "Corrective actions are never created directly."

    Design: Corner/errors/get_corrective_action_with_unknown_id_returns_corrective_action_not_found
    """
    fx.set_clock(api, fx.CLOCK_BASE)

    validate_error(
        api.get_corrective_action(NON_EXISTENT_UUID, COMPLIANCE_OFFICER_HEADERS),
        err.ERR_CORRECTIVE_ACTION_NOT_FOUND,
    )


def test_get_entry_submission_with_unknown_id_returns_entry_submission_not_found(
    api: ApiClient,
):
    """PRD §2.11: "The `{id}` path segment resolves to an `EntrySubmission` —
    `ERR_ENTRY_SUBMISSION_NOT_FOUND` (404), on the entry-line read."
    PRD §2.1: "Entry-line reads are available to `ComplianceOfficer`,
    `EntryFiler` and `FdaInspector` — a `QualifiedIndividual` has no read access
    to entry lines."

    Design: Corner/errors/get_entry_submission_with_unknown_id_returns_entry_submission_not_found
    """
    fx.set_clock(api, fx.CLOCK_BASE)

    validate_error(
        api.get_entry_submission(NON_EXISTENT_UUID, ENTRY_FILER_HEADERS),
        err.ERR_ENTRY_SUBMISSION_NOT_FOUND,
    )


# ---------------------------------------------------------------------------
# Uniqueness, window and precondition rungs
# ---------------------------------------------------------------------------


def test_second_importer_with_the_same_dnb_number_returns_duplicate_identifier(
    api: ApiClient,
):
    """PRD §2.10: "Six uniqueness scopes are enforced, all reported as
    `ERR_DUPLICATE_IDENTIFIER` (HTTP 409). An importer's `dnb_number` is unique
    across all importers."
    Only the DUNS number collides: the second registration carries a different
    legal name and a different unique facility identifier.

    Design: Corner/errors/second_importer_with_the_same_dnb_number_returns_duplicate_identifier
    """
    fx.set_clock(api, fx.CLOCK_BASE)
    first = fx.create_importer(api)

    validate_error(
        api.create_importer(
            f.importer_payload(
                legal_name="Northbrook Foods Import LLC of Delaware",
                unique_facility_identifier="UFI-NB-9999",
            ),
            COMPLIANCE_OFFICER_HEADERS,
        ),
        err.ERR_DUPLICATE_IDENTIFIER,
    )

    surviving = validate_success(api.get_importer(first["id"], COMPLIANCE_OFFICER_HEADERS))
    assert surviving["dnb_number"] == f.IMPORTER_DNB, (
        f"the registered importer must keep dnb_number {f.IMPORTER_DNB}, "
        f"got {surviving['dnb_number']}"
    )


def test_activity_window_start_after_window_end_returns_invalid_window(api: ApiClient):
    """PRD §3.4: "First, `window_start` must be strictly earlier than
    `window_end`; an inverted or empty window is refused with
    `ERR_INVALID_WINDOW`."
    Both bounds are well-formed ISO 8601 UTC, so only the inversion can be at
    fault.

    Design: Corner/errors/activity_window_start_after_window_end_returns_invalid_window
    """
    world = fx.analyzed_program(api, hazards=[fx.HAZARD_LISTERIA])

    validate_error(
        api.create_verification_activity(
            _sampling_activity_payload(
                world.pair_id,
                world.qi_b_id,
                window_start="2026-10-15T00:00:00Z",
                window_end="2026-10-01T00:00:00Z",
            ),
            make_qualified_individual_headers(world.qi_a_id),
        ),
        err.ERR_INVALID_WINDOW,
    )

    activities, meta = validate_paginated(
        api.list_verification_activities(
            COMPLIANCE_OFFICER_HEADERS, {"pair_id": world.pair_id}
        )
    )
    assert activities == [], f"no activity may be created, got {activities}"
    assert meta["total_count"] == 0, (
        f"total_count: expected 0 activities, got {meta['total_count']}"
    )


def test_activity_create_before_any_approved_analysis_returns_hazard_analysis_required(
    api: ApiClient,
):
    """PRD §3.4: "The combination must already have a non-null
    `active_hazard_analysis_id`, or the proposal is refused with
    `ERR_HAZARD_ANALYSIS_REQUIRED` — activities cannot be selected before the
    hazards they address are known."
    PRD §3.3: "The combination's `hazard_analysis_count` is incremented — it
    counts every analysis ever opened on the combination, withdrawn ones
    included"

    Design: Corner/errors/activity_create_before_any_approved_analysis_returns_hazard_analysis_required
    """
    world = fx.base_program(api)
    analysis = fx.create_hazard_analysis(api, world.pair_id, world.qi_a_id)
    fx.add_hazard(api, analysis["id"], world.qi_a_id, **fx.HAZARD_LISTERIA)

    validate_error(
        api.create_verification_activity(
            _sampling_activity_payload(world.pair_id, world.qi_b_id),
            make_qualified_individual_headers(world.qi_a_id),
        ),
        err.ERR_HAZARD_ANALYSIS_REQUIRED,
    )

    pair = validate_success(
        api.get_supplier_food_pair(world.pair_id, COMPLIANCE_OFFICER_HEADERS)
    )
    assert pair["active_hazard_analysis_id"] is None, (
        "a DRAFT analysis must not populate active_hazard_analysis_id, "
        f"got {pair['active_hazard_analysis_id']}"
    )
    assert pair["hazard_analysis_count"] == 1, (
        f"hazard_analysis_count: expected 1, got {pair['hazard_analysis_count']}"
    )
    assert_pair_dimensions(pair, verification_status="DRAFT")


def test_verification_approval_with_no_approved_activity_returns_no_verification_activity(
    api: ApiClient,
):
    """PRD §3.5: "At least one activity on the combination must have `status`
    `APPROVED`, or `ERR_NO_VERIFICATION_ACTIVITY`."
    PRD §3.5: "And `adequacy_score_planned` must be at least the applicable
    adequacy floor — 30.00 when the combination's `modified_requirements_only` is
    true, and 60.00 otherwise — or `ERR_ADEQUACY_BELOW_FLOOR`."
    PRD §2.11: "And on the same operation the eight substantive gates run in the
    fixed order supplier approval, import suspension, hazard analysis present,
    activity present, onsite audit, frequency, adequacy, reassessment currency —
    so a combination that fails several of them reports the earliest."
    PRD §3.4: "The **PLANNED** variant, surfaced as `adequacy_score_planned`,
    takes as its input set every activity on the combination whose `status` is
    `APPROVED`"

    Design: Corner/errors/verification_approval_with_no_approved_activity_returns_no_verification_activity
    """
    world = fx.analyzed_program(api, hazards=[fx.HAZARD_LISTERIA])
    activity = fx.create_activity(
        api,
        world.pair_id,
        world.qi_a_id,
        world.qi_b_id,
        activity_type="SAMPLING_AND_TESTING",
        frequency_per_year=3,
        justification_text=SAMPLING_JUSTIFICATION,
        window_start="2026-10-01T00:00:00Z",
        window_end="2026-10-15T00:00:00Z",
    )

    validate_error(
        api.post_pair_verification_approval(
            world.pair_id,
            f.verification_approval_payload(
                approval_note="Requesting approval while the sampling plan is still under review"
            ),
            make_qualified_individual_headers(world.qi_a_id),
        ),
        err.ERR_NO_VERIFICATION_ACTIVITY,
    )

    unreviewed = validate_success(
        api.get_verification_activity(activity["id"], COMPLIANCE_OFFICER_HEADERS)
    )
    assert unreviewed["status"] == "PROPOSED", (
        f"activity.status: expected PROPOSED, got {unreviewed['status']}"
    )
    pair = validate_success(
        api.get_supplier_food_pair(world.pair_id, COMPLIANCE_OFFICER_HEADERS)
    )
    assert_money(pair["adequacy_score_planned"], 0.00, "adequacy_score_planned")
    assert_pair_dimensions(pair, verification_status="HAZARD_ANALYZED")


def test_approve_evaluation_of_an_import_alert_supplier_returns_compliance_status_blocks_approval(
    api: ApiClient,
):
    """PRD §3.2: "An `UNEVALUATED` supplier moves `UNEVALUATED → APPROVED` on
    `APPROVE`, which additionally requires `regulatory_compliance_status` to be
    exactly `NO_ADVERSE_FINDINGS`; it moves `UNEVALUATED → CONDITIONALLY_APPROVED`
    on `APPROVE_CONDITIONALLY`, which requires `regulatory_compliance_status` to
    be either `NO_ADVERSE_FINDINGS` or `WARNING_LETTER`."
    PRD §3.2: "A posture too adverse for the requested decision is refused with
    `ERR_COMPLIANCE_STATUS_BLOCKS_APPROVAL` — so an establishment on
    `IMPORT_ALERT` or `REGISTRATION_SUSPENDED` cannot be approved at all through
    this route."
    PRD §2.5: "`version`, a monotonically increasing integer that starts at 1 and
    increments by exactly one on every mutation of that row"

    Design: Corner/errors/approve_evaluation_of_an_import_alert_supplier_returns_compliance_status_blocks_approval
    """
    fx.set_clock(api, fx.CLOCK_BASE)
    importer = fx.create_importer(api)
    qi_a = fx.create_qualified_individual(api, importer["id"])
    supplier = fx.create_supplier(
        api,
        importer["id"],
        name="Puerto Rojo SAC",
        facility_registration_number="FRN-PE-99003",
        regulatory_compliance_status="IMPORT_ALERT",
    )

    for decision, note in (
        ("APPROVE", "Requesting approval despite the standing import alert"),
        (
            "APPROVE_CONDITIONALLY",
            "Requesting conditional approval despite the standing import alert",
        ),
    ):
        validate_error(
            api.post_supplier_evaluation(
                supplier["id"],
                f.evaluation_payload(decision, performance_basis_note=note),
                make_qualified_individual_headers(qi_a["id"]),
            ),
            err.ERR_COMPLIANCE_STATUS_BLOCKS_APPROVAL,
        )

    unchanged = validate_success(
        api.get_foreign_supplier(supplier["id"], COMPLIANCE_OFFICER_HEADERS)
    )
    assert unchanged["status"] == "UNEVALUATED", (
        f"supplier.status: expected UNEVALUATED, got {unchanged['status']}"
    )
    assert unchanged["version"] == 1, (
        f"supplier.version: expected 1 after two refused evaluations, "
        f"got {unchanged['version']}"
    )


def test_patch_of_an_approved_activity_returns_activity_not_revisable(api: ApiClient):
    """PRD §3.4: "Only a `PROPOSED` or `CHANGES_REQUESTED` activity is revisable;
    an `APPROVED`, `WITHDRAWN` or `RETIRED` row is frozen and reports
    `ERR_ACTIVITY_NOT_REVISABLE`."
    PRD §3.4: "Concretely, the activity's `coverage_weight` is the type weight
    for its `activity_type` — 10.0 for `ONSITE_AUDIT`, 6.0 for
    `SAMPLING_AND_TESTING`, 3.0 for `RECORDS_REVIEW`, and 2.0 for
    `OTHER_SUPPLIER_EVALUATION` — multiplied by the smaller of its
    `frequency_per_year` and 4, multiplied by a justification factor of 1.0 when
    `justification_text` is at least 40 characters long and 0.5 otherwise, with
    the product rounded half up to two decimal places."
    The revision is issued by the activity's own proposer, so the duty separation
    is satisfied and only the frozen `APPROVED` state can refuse it.

    Design: Corner/errors/patch_of_an_approved_activity_returns_activity_not_revisable
    """
    world = fx.sampling_only_program(api, frequency_per_year=3)

    validate_error(
        api.patch_verification_activity(
            world.activity_id,
            {"frequency_per_year": 4},
            make_qualified_individual_headers(world.qi_a_id),
        ),
        err.ERR_ACTIVITY_NOT_REVISABLE,
    )

    frozen = validate_success(
        api.get_verification_activity(world.activity_id, COMPLIANCE_OFFICER_HEADERS)
    )
    assert frozen["frequency_per_year"] == 3, (
        f"frequency_per_year must stay 3, got {frozen['frequency_per_year']}"
    )
    assert_money(frozen["coverage_weight"], 18.00, "coverage_weight")
    assert frozen["revision_count"] == 0, (
        f"revision_count must stay 0, got {frozen['revision_count']}"
    )
    pair = validate_success(
        api.get_supplier_food_pair(world.pair_id, COMPLIANCE_OFFICER_HEADERS)
    )
    assert_money(pair["adequacy_score_planned"], 86.96, "adequacy_score_planned")


def test_undesignated_qi_signing_verification_approval_returns_qi_not_designated_for_pair(
    api: ApiClient,
):
    """PRD §3.5: "Only after all of those does the designation-match check compare
    `X-User-ID` with `designated_qi_id` and, on a mismatch, report
    `ERR_QI_NOT_DESIGNATED_FOR_PAIR`."
    PRD §2.12: "And a combination's verification approval may be signed only by
    the individual named in its `designated_qi_id` — that particular check is
    reported separately as `ERR_QI_NOT_DESIGNATED_FOR_PAIR` (HTTP 403) because it
    is an authorisation failure rather than a duty collision."
    The signer is ACTIVE with current training and every substantive gate is
    satisfied, so only the designation mismatch is left.

    Design: Corner/errors/undesignated_qi_signing_verification_approval_returns_qi_not_designated_for_pair
    """
    world = fx.sampling_only_program(api, frequency_per_year=3)

    validate_error(
        api.post_pair_verification_approval(
            world.pair_id,
            f.verification_approval_payload(
                approval_note=(
                    "Signing on behalf of the programme while the designated "
                    "individual is away"
                )
            ),
            make_qualified_individual_headers(world.qi_b_id),
        ),
        err.ERR_QI_NOT_DESIGNATED_FOR_PAIR,
    )

    pair = validate_success(
        api.get_supplier_food_pair(world.pair_id, COMPLIANCE_OFFICER_HEADERS)
    )
    assert_pair_dimensions(
        pair, verification_status="HAZARD_ANALYZED", entry_eligibility_status="PENDING"
    )
    roster, _ = validate_paginated(
        api.list_importer_qualified_individuals(
            world.importer_id, COMPLIANCE_OFFICER_HEADERS, {"limit": 100}
        )
    )
    signer = next(row for row in roster if row["id"] == world.qi_b_id)
    assert signer["status"] == "ACTIVE", (
        f"the refused signer must stay ACTIVE, got {signer['status']}"
    )


def test_entry_filing_with_a_mismatched_dnb_number_returns_identifier_mismatch(
    api: ApiClient,
):
    """PRD §3.9: "Last of all, the identifiers must match: `dnb_number_submitted`
    must equal the importer's registered `dnb_number` and `ufi_submitted` must
    equal the importer's registered `unique_facility_identifier`."
    PRD §3.9: "The comparison result is persisted as the boolean
    `identifier_match`, and a mismatch on either identifier is refused with
    `ERR_IDENTIFIER_MISMATCH`."
    PRD §3.9: "An entry line is created in `status` `SUBMITTED` and, once every
    validation has passed and `identifier_match` is true against an `ELIGIBLE`
    combination, it auto-advances `SUBMITTED → ACCEPTED` inside the same request —
    the create response already carries `ACCEPTED`, with `held_reason` null."

    Design: Corner/errors/entry_filing_with_a_mismatched_dnb_number_returns_identifier_mismatch
    """
    world = fx.sampling_only_program(api, frequency_per_year=3)
    fx.approve_pair_verification(api, world.pair_id, world.qi_a_id)

    validate_error(
        api.create_entry_submission(
            f.entry_submission_payload(
                world.pair_id,
                dnb_number_submitted="999999999",
                entry_number="ENT-2026-0001",
                arrival_date="2026-09-05T00:00:00Z",
            ),
            ENTRY_FILER_HEADERS,
        ),
        err.ERR_IDENTIFIER_MISMATCH,
    )

    lines, meta = validate_paginated(
        api.list_entry_submissions(ENTRY_FILER_HEADERS, {"pair_id": world.pair_id})
    )
    assert lines == [], f"no entry line may be created, got {lines}"
    assert meta["total_count"] == 0, (
        f"total_count: expected 0 entry lines, got {meta['total_count']}"
    )
    pair = validate_success(
        api.get_supplier_food_pair(world.pair_id, COMPLIANCE_OFFICER_HEADERS)
    )
    assert_pair_dimensions(pair, entry_eligibility_status="ELIGIBLE")

    accepted = validate_success(
        api.create_entry_submission(
            f.entry_submission_payload(
                world.pair_id,
                entry_number="ENT-2026-0001",
                arrival_date="2026-09-05T00:00:00Z",
            ),
            ENTRY_FILER_HEADERS,
        ),
        201,
    )
    assert accepted["status"] == "ACCEPTED", (
        f"a matching filing must land ACCEPTED, got {accepted['status']}"
    )
    assert accepted["identifier_match"] is True, (
        f"identifier_match: expected True, got {accepted['identifier_match']}"
    )


def test_juice_haccp_exemption_on_a_food_without_that_control_returns_exemption_not_applicable(
    api: ApiClient,
):
    """PRD §3.8: "`JUICE_HACCP_CONTROL` requires the food's
    `process_control_category` to be `JUICE_HACCP`"
    PRD §3.8: "A mismatch is refused with `ERR_EXEMPTION_NOT_APPLICABLE`."
    PRD §3.2: "Creation initialises all three dimensions — `verification_status`
    `DRAFT`, `entry_eligibility_status` `PENDING`, `exemption_status` `NONE` — and
    leaves `exemption_type`, `active_hazard_analysis_id`, `last_reassessed_at` and
    `reassessment_due_at` null, `modified_requirements_only` false, and
    `hazard_analysis_count`, `uncontrolled_significant_hazard_count`,
    `adequacy_score_planned` and `adequacy_score_realized` at their zero values."

    Design: Corner/errors/juice_haccp_exemption_on_a_food_without_that_control_returns_exemption_not_applicable
    """
    # The mango food leaves process_control_category at its NONE default.
    world = fx.base_program(api)

    validate_error(
        api.post_pair_exemption(
            world.pair_id,
            f.exemption_claim_payload(
                "JUICE_HACCP_CONTROL",
                basis_note="Claiming the juice HACCP exemption for a frozen fruit product",
            ),
            make_qualified_individual_headers(world.qi_a_id),
        ),
        err.ERR_EXEMPTION_NOT_APPLICABLE,
    )

    pair = validate_success(
        api.get_supplier_food_pair(world.pair_id, COMPLIANCE_OFFICER_HEADERS)
    )
    assert_pair_dimensions(
        pair, exemption_status="NONE", entry_eligibility_status="PENDING"
    )
    assert pair["exemption_type"] is None, (
        f"a refused claim must not record an exemption_type, got {pair['exemption_type']}"
    )


def test_small_importer_exemption_claimed_by_a_large_importer_returns_modified_requirements_not_available(
    api: ApiClient,
):
    """PRD §3.8: "`US_CUSTOMER_WRITTEN_ASSURANCE` and `SMALL_IMPORTER_MODIFIED`
    accept any `process_control_category`."
    PRD §3.8: "One further gate applies only to `SMALL_IMPORTER_MODIFIED`: the
    importer's `small_importer_flag` must be true, or the claim is refused with
    `ERR_MODIFIED_REQUIREMENTS_NOT_AVAILABLE`."
    PRD §3.1: "`small_importer_flag`, which defaults to false and marks an
    importer that qualifies as a very small importer eligible for modified
    requirements"

    Design: Corner/errors/small_importer_exemption_claimed_by_a_large_importer_returns_modified_requirements_not_available
    """
    # The importer is registered without small_importer_flag, so it defaults false.
    world = fx.base_program(api)

    validate_error(
        api.post_pair_exemption(
            world.pair_id,
            f.exemption_claim_payload(
                "SMALL_IMPORTER_MODIFIED",
                basis_note="Claiming modified requirements as a small importer",
            ),
            make_qualified_individual_headers(world.qi_a_id),
        ),
        err.ERR_MODIFIED_REQUIREMENTS_NOT_AVAILABLE,
    )

    pair = validate_success(
        api.get_supplier_food_pair(world.pair_id, COMPLIANCE_OFFICER_HEADERS)
    )
    assert_pair_dimensions(pair, exemption_status="NONE")
    assert pair["modified_requirements_only"] is False, (
        "modified_requirements_only must stay false, "
        f"got {pair['modified_requirements_only']}"
    )


def test_entry_filing_while_a_reassessment_is_pending_returns_pair_verification_incomplete(
    api: ApiClient,
):
    """PRD §3.9: "Second the combination must have an established compliance
    basis: either its `verification_status` is `VERIFICATION_APPROVED` or its
    `exemption_status` is `VERIFIED`; a combination with neither is refused with
    `ERR_PAIR_VERIFICATION_INCOMPLETE`."
    PRD §3.5: "Its `entry_eligibility_status` is deliberately left exactly as it
    was: a voluntary reassessment of new hazard information does not, by itself,
    stop shipments at the border."
    PRD §3.5: "the importer's `program_status` is recomputed — landing on
    `AT_RISK` while any combination sits in `REASSESSMENT_REQUIRED`."

    Design: Corner/errors/entry_filing_while_a_reassessment_is_pending_returns_pair_verification_incomplete
    """
    world = fx.sampling_only_program(api, frequency_per_year=3)
    fx.approve_pair_verification(api, world.pair_id, world.qi_a_id)
    validate_success(
        api.post_pair_reassessment(
            world.pair_id,
            f.reassessment_payload(
                "NEW_INFORMATION",
                note="New pathogen surveillance data requires a fresh look",
            ),
            COMPLIANCE_OFFICER_HEADERS,
        )
    )

    validate_error(
        api.create_entry_submission(
            f.entry_submission_payload(
                world.pair_id,
                entry_number="ENT-2026-0002",
                arrival_date="2026-09-05T00:00:00Z",
            ),
            ENTRY_FILER_HEADERS,
        ),
        err.ERR_PAIR_VERIFICATION_INCOMPLETE,
    )

    pair = validate_success(
        api.get_supplier_food_pair(world.pair_id, COMPLIANCE_OFFICER_HEADERS)
    )
    assert_pair_dimensions(
        pair,
        verification_status="REASSESSMENT_REQUIRED",
        entry_eligibility_status="ELIGIBLE",
        exemption_status="NONE",
    )
    importer = validate_success(
        api.get_importer(world.importer_id, COMPLIANCE_OFFICER_HEADERS)
    )
    assert_importer_rollup(importer, program_status="AT_RISK")


def test_verification_approval_past_the_reassessment_due_date_returns_reassessment_overdue(
    api: ApiClient,
):
    """PRD §3.5: "Finally, the combination's `reassessment_due_at` must be either
    null or at or after the logical clock; a combination past its 36-month
    reassessment date must be reassessed before it can be approved again, and
    otherwise reports `ERR_REASSESSMENT_OVERDUE`."
    PRD §2.4: "Two derived date fields are computed with calendar-month arithmetic
    rather than fixed day counts: a qualified individual's `training_valid_until`
    is the individual's `training_completed_at` advanced by 36 calendar months,
    and a supplier-food combination's `reassessment_due_at` is its
    `last_reassessed_at` advanced by 36 calendar months."
    PRD §3.1: "Renewing training on an already-active individual is a permitted
    self-loop `ACTIVE → ACTIVE` that only requires the submitted
    `training_completed_at` to be at or before the clock; it overwrites
    `training_completed_at` and recomputes `training_valid_until`, moving the
    expiry forward without changing status."

    Design: Corner/errors/verification_approval_past_the_reassessment_due_date_returns_reassessment_overdue
    """
    world = fx.sampling_only_program(api, frequency_per_year=3)
    fx.approve_pair_verification(api, world.pair_id, world.qi_a_id)
    validate_success(
        api.post_pair_reassessment(
            world.pair_id,
            f.reassessment_payload("CYCLE", note="Opening the cyclical reassessment"),
            COMPLIANCE_OFFICER_HEADERS,
        )
    )
    fx.set_clock(api, "2029-10-01T00:00:00Z")
    renewed = fx.designate_qualified_individual(
        api,
        world.qi_a_id,
        "RENEW_TRAINING",
        training_completed_at="2029-09-01T00:00:00Z",
        note="Refresher training completed",
    )

    validate_error(
        api.post_pair_verification_approval(
            world.pair_id,
            f.verification_approval_payload(
                approval_note="Re-signing the verification without documenting the reassessment"
            ),
            make_qualified_individual_headers(world.qi_a_id),
        ),
        err.ERR_REASSESSMENT_OVERDUE,
    )

    pair = validate_success(
        api.get_supplier_food_pair(world.pair_id, COMPLIANCE_OFFICER_HEADERS)
    )
    _assert_same_instant(
        pair["reassessment_due_at"], "2029-09-01T00:00:00", "reassessment_due_at"
    )
    assert_pair_dimensions(pair, verification_status="REASSESSMENT_REQUIRED")
    _assert_same_instant(
        renewed["training_valid_until"], "2032-09-01T00:00:00", "training_valid_until"
    )
    importer = validate_success(
        api.get_importer(world.importer_id, COMPLIANCE_OFFICER_HEADERS)
    )
    assert_importer_rollup(importer, program_status="AT_RISK")


def test_entry_filing_on_an_exempt_pair_of_a_suspended_supplier_returns_import_suspension_active(
    api: ApiClient,
):
    """PRD §3.9: "Fourth, no corrective action on the combination's supplier may
    sit in `status` `IMPORT_SUSPENSION`, or the filing is refused with
    `ERR_IMPORT_SUSPENSION_ACTIVE`."
    PRD §2.11: "The supplier's `status` is `APPROVED` or `CONDITIONALLY_APPROVED`
    — `ERR_SUPPLIER_NOT_APPROVED` (422), on verification approval always, and on
    entry-line create only when the combination's eligibility rests on full
    verification or on a modified-requirements exemption; a combination whose
    `exemption_status` is `VERIFIED` with `modified_requirements_only` false skips
    this check entirely at entry."
    PRD §3.6: "**Hop 4**: because each of those combinations became
    `VERIFICATION_LAPSED`, its `entry_eligibility_status` moves `ELIGIBLE →
    BLOCKED`."
    PRD §3.8: "Verification also moves `entry_eligibility_status` `PENDING →
    ELIGIBLE` in the same request while deliberately leaving `verification_status`
    at `DRAFT`: a verified exemption makes a combination entry-eligible with no
    hazard analysis and no verification plan whatsoever."

    Design: Corner/errors/entry_filing_on_an_exempt_pair_of_a_suspended_supplier_returns_import_suspension_active
    """
    world = fx.sampling_only_program(api, frequency_per_year=3)
    fx.approve_pair_verification(api, world.pair_id, world.qi_a_id)

    # An attested FAIL sampling record drops the supplier's final performance
    # score under the suspension threshold, lapsing and blocking the first pair.
    fx.set_clock(api, "2026-10-20T00:00:00Z")
    record = fx.file_record(
        api,
        world.activity_id,
        world.qi_a_id,
        outcome="FAIL",
        performed_start="2026-10-05T00:00:00Z",
        performed_end="2026-10-06T00:00:00Z",
        findings_count=0,
        document_reference="LAB-2026-1006",
    )
    fx.attest_record(api, record["id"], world.qi_b_id)

    actions, _ = validate_paginated(
        api.list_corrective_actions(
            COMPLIANCE_OFFICER_HEADERS,
            {"supplier_id": world.supplier_id, "status": "OPEN"},
        )
    )
    assert len(actions) == 1, f"expected one synthesised corrective action, got {actions}"
    action_id = actions[0]["id"]
    fx.decide_corrective_action(
        api,
        action_id,
        "IMPORT_SUSPENSION",
        world.supplier_id,
        rationale=(
            "Pathogen finding at the supplier warrants suspending imports pending "
            "remediation"
        ),
    )

    # A second combination on the same supplier becomes eligible purely through a
    # VERIFIED juice-HACCP exemption, which is not a modified-requirements claim.
    juice = fx.create_juice_food(api, world.importer_id)
    exempt_pair = fx.create_pair(
        api, world.importer_id, world.supplier_id, juice["id"], world.qi_a_id
    )
    fx.claim_exemption(
        api,
        exempt_pair["id"],
        "JUICE_HACCP_CONTROL",
        world.qi_a_id,
        basis_note="The juice is produced under a compliant juice HACCP programme",
    )
    fx.determine_exemption(api, exempt_pair["id"], "VERIFY")

    validate_error(
        api.create_entry_submission(
            f.entry_submission_payload(
                exempt_pair["id"],
                entry_number="ENT-2026-0003",
                arrival_date="2026-10-25T00:00:00Z",
            ),
            ENTRY_FILER_HEADERS,
        ),
        err.ERR_IMPORT_SUSPENSION_ACTIVE,
    )

    supplier = validate_success(
        api.get_foreign_supplier(world.supplier_id, COMPLIANCE_OFFICER_HEADERS)
    )
    assert supplier["status"] == "SUSPENDED_PENDING_REVIEW", (
        f"supplier.status: expected SUSPENDED_PENDING_REVIEW, got {supplier['status']}"
    )
    assert_money(supplier["performance_score_final"], 20.00, "performance_score_final")
    action = validate_success(
        api.get_corrective_action(action_id, COMPLIANCE_OFFICER_HEADERS)
    )
    assert action["status"] == "IMPORT_SUSPENSION", (
        f"corrective action status: expected IMPORT_SUSPENSION, got {action['status']}"
    )
    exempt_now = validate_success(
        api.get_supplier_food_pair(exempt_pair["id"], COMPLIANCE_OFFICER_HEADERS)
    )
    assert_pair_dimensions(
        exempt_now, entry_eligibility_status="ELIGIBLE", exemption_status="VERIFIED"
    )
    assert exempt_now["modified_requirements_only"] is False, (
        "the juice exemption is not a modified-requirements claim, "
        f"got modified_requirements_only {exempt_now['modified_requirements_only']}"
    )
    verified_pair = validate_success(
        api.get_supplier_food_pair(world.pair_id, COMPLIANCE_OFFICER_HEADERS)
    )
    assert_pair_dimensions(verified_pair, entry_eligibility_status="BLOCKED")
    lines, meta = validate_paginated(api.list_entry_submissions(ENTRY_FILER_HEADERS))
    assert lines == [], f"no entry line may be created, got {lines}"
    assert meta["total_count"] == 0, (
        f"total_count: expected 0 entry lines, got {meta['total_count']}"
    )
