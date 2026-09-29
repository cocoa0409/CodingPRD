"""The order of refusal: which rule wins when a request violates several."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import api_errors as err
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.assertions import assert_money, assert_pair_dimensions
from test_helpers.test_users import (
    COMPLIANCE_OFFICER_HEADERS,
    ENTRY_FILER_HEADERS,
    make_qualified_individual_headers,
)


# ---------------------------------------------------------------------------
# Hazard-analysis approval: the at-least-one-hazard rule
# ---------------------------------------------------------------------------


def test_approving_an_empty_hazard_analysis_is_refused(api: ApiClient):
    """PRD 3.3: "The analysis must still be `DRAFT` (`ERR_ANALYSIS_NOT_DRAFT`), the
    acting individual must be `ACTIVE` with current training
    (`ERR_QI_DESIGNATION_INVALID`), and the analysis must contain at least one
    hazard row — an empty analysis documents nothing and is refused with
    `ERR_HAZARD_ANALYSIS_EMPTY`."
    PRD 2.11 rung 30: "The target analysis has `hazard_count` of at least 1 —
    `ERR_HAZARD_ANALYSIS_EMPTY` (422), on analysis approval."
    PRD 3.3: "On success the analysis moves `DRAFT → APPROVED`, its `approved_at`
    is set to the logical clock and its `risk_total` is recomputed."

    The draft belongs to an ACTIVE qualified individual and every earlier rung of
    the refusal ladder is satisfied, so hazard_count == 0 is the only live rule.

    Design: Corner/validations/approval_of_hazard_analysis_with_zero_hazards_returns_hazard_analysis_empty
    """
    world = fx.single_qi_program(api)
    analysis = fx.create_hazard_analysis(api, world.pair_id, world.qi_a_id)
    version_before = fx.get_pair(api, world.pair_id)["version"]

    response = api.post_hazard_analysis_approval(
        analysis["id"],
        f.hazard_analysis_approval_payload(
            approval_note="Nothing identified for this combination"
        ),
        make_qualified_individual_headers(world.qi_a_id),
    )
    validate_error(response, err.ERR_HAZARD_ANALYSIS_EMPTY)

    refused = fx.get_analysis(api, analysis["id"])
    assert refused["status"] == "DRAFT", (
        f"a refused approval must leave the analysis in DRAFT, got {refused['status']}"
    )
    assert refused["approved_at"] is None, (
        f"a refused approval must not set approved_at, got {refused['approved_at']}"
    )

    pair = fx.get_pair(api, world.pair_id)
    assert pair["active_hazard_analysis_id"] is None, (
        "the pair must not point at an analysis whose approval was refused"
    )
    assert pair["version"] == version_before, (
        f"the failed approval wrote nothing, so the pair version must stay "
        f"{version_before}, got {pair['version']}"
    )


def test_approving_an_analysis_with_one_hazard_succeeds(api: ApiClient):
    """PRD 3.3: "On success the analysis moves `DRAFT → APPROVED`, its `approved_at`
    is set to the logical clock and its `risk_total` is recomputed."
    PRD 3.3: "The combination's `active_hazard_analysis_id` is pointed at this
    analysis, and whatever analysis previously held that position moves
    `APPROVED → SUPERSEDED`; a superseded row accepts no further hazards but
    remains readable and available for inspection."
    PRD 3.3: "The combination's `verification_status` advances
    `DRAFT → HAZARD_ANALYZED`, or self-loops `HAZARD_ANALYZED → HAZARD_ANALYZED`
    when a newer analysis replaces an earlier approved one."
    PRD 3.3: "**Step one** derives the hazard load and the gross risk: the hazard
    load is the sum of the `risk_score` values of only those hazards in the active
    analysis whose `requires_control` is true, rounded half up to two decimal
    places, and it is 0.00 when `active_hazard_analysis_id` is null; the gross risk
    is that hazard load plus the supplier penalty selected by the supplier's
    `regulatory_compliance_status` — 0.00 for `NO_ADVERSE_FINDINGS`, 6.00 for
    `WARNING_LETTER`, 15.00 for `IMPORT_ALERT`, and 25.00 for
    `REGISTRATION_SUSPENDED` — again rounded half up to two decimal places."
    PRD 3.3: "**Step four** produces `composite_hazard_risk` as the gross risk
    minus the relief, floored at 0.00 so a negative result becomes 0.00, rounded
    half up to two decimal places."

    Same fixture and same trigger as the empty-analysis refusal, with a single
    Listeria hazard added first: the rule gates on the hazard count, it does not
    reject approvals generally.

    Design: Corner/validations/approval_of_hazard_analysis_with_one_hazard_passes_the_same_rule
    """
    world = fx.single_qi_program(api)
    analysis = fx.create_hazard_analysis(api, world.pair_id, world.qi_a_id)
    fx.add_hazard(api, analysis["id"], world.qi_a_id, **fx.HAZARD_LISTERIA)

    response = api.post_hazard_analysis_approval(
        analysis["id"],
        f.hazard_analysis_approval_payload(
            approval_note="Pathogen hazard identified and assigned to the foreign supplier"
        ),
        make_qualified_individual_headers(world.qi_a_id),
    )
    approved = validate_success(response)

    assert approved["status"] == "APPROVED", (
        f"expected APPROVED, got {approved['status']}"
    )
    assert approved["approved_at"] is not None, "approved_at must be set on approval"
    assert approved["approved_at"].startswith("2026-09-01T00:00:00"), (
        f"approved_at must be the logical clock instant, got {approved['approved_at']}"
    )

    pair = fx.get_pair(api, world.pair_id)
    assert pair["active_hazard_analysis_id"] == analysis["id"], (
        "the approved analysis must become the pair's active analysis"
    )
    assert_pair_dimensions(pair, verification_status="HAZARD_ANALYZED")
    assert_money(pair["composite_hazard_risk"], 13.80, "composite_hazard_risk")


def test_withdrawn_analysis_reports_not_draft_rather_than_empty(api: ApiClient):
    """PRD 2.11: "Rules are evaluated in ascending priority order, the first
    violated rule determines the response, and no later rule is evaluated."
    PRD 2.11 rung 22: "The target hazard analysis has `status` equal to `DRAFT` —
    `ERR_ANALYSIS_NOT_DRAFT` (409), on hazard create and analysis approval."
    PRD 2.11 rung 30: "The target analysis has `hazard_count` of at least 1 —
    `ERR_HAZARD_ANALYSIS_EMPTY` (422), on analysis approval."
    PRD 3.3: "Opening a new analysis is a create-with-supersede: any analysis on
    the same combination that was still `DRAFT` moves `DRAFT → WITHDRAWN`, and no
    further hazards may be added to the withdrawn row."

    The first analysis is both withdrawn and empty; the ladder puts the
    analysis-state check ahead of the empty-analysis check, so the 409 answers.

    Design: Corner/validations/analysis_not_draft_at_priority_twenty_two_masks_empty_analysis_at_priority_thirty
    """
    world = fx.single_qi_program(api)
    first = fx.create_hazard_analysis(
        api,
        world.pair_id,
        world.qi_a_id,
        methodology_note="First pass hazard identification for this combination",
    )
    second = fx.create_hazard_analysis(
        api,
        world.pair_id,
        world.qi_a_id,
        methodology_note="Second pass hazard identification superseding the first draft",
    )

    response = api.post_hazard_analysis_approval(
        first["id"],
        f.hazard_analysis_approval_payload(
            approval_note="Attempting to approve the superseded empty draft"
        ),
        make_qualified_individual_headers(world.qi_a_id),
    )
    error = validate_error(response, err.ERR_ANALYSIS_NOT_DRAFT)
    assert error["error_id"] != err.ERR_HAZARD_ANALYSIS_EMPTY, (
        "the earlier analysis-state rung must mask the empty-analysis rung"
    )

    withdrawn = fx.get_analysis(api, first["id"])
    assert withdrawn["status"] == "WITHDRAWN", (
        f"the superseded draft must be WITHDRAWN, got {withdrawn['status']}"
    )
    assert withdrawn["hazard_count"] == 0, (
        "the withdrawn analysis is empty as well, which is the masked violation"
    )
    assert fx.get_analysis(api, second["id"])["status"] == "DRAFT", (
        "the newly opened analysis must remain DRAFT"
    )


# ---------------------------------------------------------------------------
# Verification approval: the substantive gates
# ---------------------------------------------------------------------------


def test_lone_records_review_falls_below_the_adequacy_floor(api: ApiClient):
    """PRD 3.5: "And `adequacy_score_planned` must be at least the applicable
    adequacy floor — 30.00 when the combination's `modified_requirements_only` is
    true, and 60.00 otherwise — or `ERR_ADEQUACY_BELOW_FLOOR`."
    PRD 3.4: "Concretely, the activity's `coverage_weight` is the type weight for
    its `activity_type` — 10.0 for `ONSITE_AUDIT`, 6.0 for
    `SAMPLING_AND_TESTING`, 3.0 for `RECORDS_REVIEW`, and 2.0 for
    `OTHER_SUPPLIER_EVALUATION` — multiplied by the smaller of its
    `frequency_per_year` and 4, multiplied by a justification factor of 1.0 when
    `justification_text` is at least 40 characters long and 0.5 otherwise, with
    the product rounded half up to two decimal places."
    PRD 3.4: "Divide 100.00 times that sum by the larger of the combination's
    `required_coverage` and 1.00 — the denominator floor of 1.00 keeps a
    zero-coverage combination from dividing by zero."
    PRD 3.3: "and `required_coverage` is `composite_hazard_risk` multiplied by
    1.5, rounded half up to two decimal places."

    One APPROVED records review at frequency 1 satisfies the activity-present gate
    and the frequency gate (1 >= 1 on a LOW-tier pair), so only the 60.00 floor
    can reject the signature.

    Design: Corner/validations/lone_records_review_activity_returns_adequacy_below_floor
    """
    world = fx.analyzed_program(api, hazards=[fx.HAZARD_LISTERIA])
    activity = fx.create_activity(
        api,
        world.pair_id,
        world.qi_a_id,
        world.qi_b_id,
        activity_type="RECORDS_REVIEW",
        frequency_per_year=1,
        justification_text=(
            "Annual review of the supplier pathogen monitoring records was selected "
            "as the sole verification activity"
        ),
        window_start="2026-10-01T00:00:00Z",
        window_end="2026-10-15T00:00:00Z",
    )
    fx.review_activity(api, activity["id"], world.qi_b_id, "APPROVE")

    response = api.post_pair_verification_approval(
        world.pair_id,
        f.verification_approval_payload(
            approval_note="Requesting approval on the records review alone"
        ),
        make_qualified_individual_headers(world.qi_a_id),
    )
    validate_error(response, err.ERR_ADEQUACY_BELOW_FLOOR)

    pair = fx.get_pair(api, world.pair_id)
    assert_money(pair["adequacy_score_planned"], 14.49, "adequacy_score_planned")
    assert pair["modified_requirements_only"] is False, (
        "no exemption was claimed, so the standard 60.00 floor applies"
    )
    assert_pair_dimensions(
        pair,
        verification_status="HAZARD_ANALYZED",
        entry_eligibility_status="PENDING",
    )


def test_moderate_tier_pair_reports_frequency_below_required(api: ApiClient):
    """PRD 3.5: "The sum of `frequency_per_year` across the combination's
    `APPROVED` activities must be at least its `required_annual_frequency`, or
    `ERR_FREQUENCY_BELOW_REQUIRED`."
    PRD 2.11: "And on the same operation the eight substantive gates run in the
    fixed order supplier approval, import suspension, hazard analysis present,
    activity present, onsite audit, frequency, adequacy, reassessment currency —
    so a combination that fails several of them reports the earliest."
    PRD 3.3: "**Step two** fixes `risk_tier` from the gross risk and from nothing
    else: `HIGH` when gross risk is at or above 40.00, otherwise `MODERATE` when
    it is at or above 18.00, otherwise `LOW`."
    PRD 3.3: "**Step five** reads the plan requirements off the tier fixed in step
    two and never re-derives that tier from the composite:
    `required_annual_frequency` is 1 for a `LOW` tier, 2 for `MODERATE`, and 4 for
    `HIGH`; and `required_coverage` is `composite_hazard_risk` multiplied by 1.5,
    rounded half up to two decimal places."
    PRD 3.2: "it moves `UNEVALUATED → CONDITIONALLY_APPROVED` on
    `APPROVE_CONDITIONALLY`, which requires `regulatory_compliance_status` to be
    either `NO_ADVERSE_FINDINGS` or `WARNING_LETTER`."

    A warning-letter supplier pushes the gross risk to exactly 18.00, so the pair
    is MODERATE and needs two visits a year; the lone annual audit fails the
    frequency gate, which the fixed gate order places ahead of the adequacy floor
    the plan also breaches.

    Design: Corner/validations/summed_frequency_below_moderate_requirement_returns_frequency_below_required
    """
    fx.set_clock(api, fx.CLOCK_BASE)
    importer = fx.create_importer(api)
    qi_a = fx.create_qualified_individual(api, importer["id"])
    qi_b = fx.create_second_qualified_individual(api, importer["id"])
    supplier = fx.create_supplier(
        api,
        importer["id"],
        approve_by_qi_id=qi_a["id"],
        decision="APPROVE_CONDITIONALLY",
        name="Andes Grain SAC",
        facility_registration_number="FRN-PE-88002",
        regulatory_compliance_status="WARNING_LETTER",
    )
    food = fx.create_plain_food(
        api,
        importer["id"],
        food_name="Milled quinoa flour",
        fda_product_code="20-QUI-11",
    )
    pair = fx.create_pair(api, importer["id"], supplier["id"], food["id"], qi_a["id"])

    analysis = fx.create_hazard_analysis(
        api,
        pair["id"],
        qi_a["id"],
        methodology_note="Mycotoxin hazard review for milled cereal products",
    )
    fx.add_hazard(
        api,
        analysis["id"],
        qi_a["id"],
        hazard_type="CHEMICAL_INCL_RADIOLOGICAL",
        hazard_name="Ochratoxin A",
        severity=4,
        probability=3,
        control_owner="FOREIGN_SUPPLIER",
    )
    fx.approve_analysis(
        api,
        analysis["id"],
        qi_a["id"],
        approval_note="Mycotoxin control assigned to the foreign supplier",
    )
    activity = fx.create_activity(
        api,
        pair["id"],
        qi_a["id"],
        qi_b["id"],
        activity_type="ONSITE_AUDIT",
        frequency_per_year=1,
        justification_text=(
            "One annual onsite audit of the mill was selected to verify the "
            "mycotoxin control programme"
        ),
        window_start="2026-10-01T00:00:00Z",
        window_end="2026-10-15T00:00:00Z",
    )
    fx.review_activity(api, activity["id"], qi_b["id"], "APPROVE")

    response = api.post_pair_verification_approval(
        pair["id"],
        f.verification_approval_payload(
            approval_note="Requesting approval on a single annual audit"
        ),
        make_qualified_individual_headers(qi_a["id"]),
    )
    error = validate_error(response, err.ERR_FREQUENCY_BELOW_REQUIRED)
    assert error["error_id"] != err.ERR_ADEQUACY_BELOW_FLOOR, (
        "the frequency gate runs ahead of the adequacy floor this plan also fails"
    )

    read_back = fx.get_pair(api, pair["id"])
    assert read_back["risk_tier"] == "MODERATE", (
        f"gross risk 18.00 is the MODERATE boundary, got tier {read_back['risk_tier']}"
    )
    assert read_back["required_annual_frequency"] == 2, (
        f"a MODERATE pair requires 2 visits a year, got "
        f"{read_back['required_annual_frequency']}"
    )
    assert_money(read_back["adequacy_score_planned"], 47.62, "adequacy_score_planned")
    assert fx.get_supplier(api, supplier["id"])["status"] == "CONDITIONALLY_APPROVED", (
        "a warning-letter supplier can only be conditionally approved"
    )


def test_modified_requirements_exemption_lowers_the_adequacy_floor(api: ApiClient):
    """PRD 3.5: "And `adequacy_score_planned` must be at least the applicable
    adequacy floor — 30.00 when the combination's `modified_requirements_only` is
    true, and 60.00 otherwise — or `ERR_ADEQUACY_BELOW_FLOOR`."
    PRD 3.8: "It recomputes `modified_requirements_only`, which is true exactly
    when `exemption_status` is `VERIFIED` and `exemption_type` is either
    `US_CUSTOMER_WRITTEN_ASSURANCE` or `SMALL_IMPORTER_MODIFIED`, and false for
    every other verified exemption type."
    PRD 3.8: "That flag is what lowers the combination's adequacy floor from 60.00
    to 30.00 while keeping supplier-approval gating in force."
    PRD 3.4: "A justification that clears 20 characters but is shorter than 40
    characters is accepted and halves the activity's contribution to coverage."
    PRD 3.5: "A successful approval sets `verification_status` to
    `VERIFICATION_APPROVED`, sets `last_reassessed_at` to the logical clock,
    recomputes `reassessment_due_at` as that instant advanced by 36 calendar
    months, increments the combination's `version` by one, and recomputes the
    importer's `program_status`."

    43.48 is the same score that would fail the standard floor; a verified
    small-importer modified claim makes the applicable floor 30.00, so the
    signature is accepted.

    Design: Corner/validations/modified_requirements_exemption_lowers_the_adequacy_floor_to_thirty
    """
    fx.set_clock(api, fx.CLOCK_BASE)
    importer = fx.create_importer(api, small_importer_flag=True)
    qi_a = fx.create_qualified_individual(api, importer["id"])
    qi_b = fx.create_second_qualified_individual(api, importer["id"])
    supplier = fx.create_supplier(api, importer["id"], approve_by_qi_id=qi_a["id"])
    food = fx.create_food(api, importer["id"])
    pair = fx.create_pair(api, importer["id"], supplier["id"], food["id"], qi_a["id"])

    fx.claim_exemption(
        api,
        pair["id"],
        "SMALL_IMPORTER_MODIFIED",
        qi_a["id"],
        basis_note="Average annual food sales are below the small importer threshold",
    )
    fx.determine_exemption(
        api,
        pair["id"],
        "VERIFY",
        determination_note="Small importer status confirmed from the filed sales figures",
    )

    analysis = fx.create_hazard_analysis(api, pair["id"], qi_a["id"])
    fx.add_hazard(api, analysis["id"], qi_a["id"], **fx.HAZARD_LISTERIA)
    fx.approve_analysis(api, analysis["id"], qi_a["id"])
    activity = fx.create_activity(
        api,
        pair["id"],
        qi_a["id"],
        qi_b["id"],
        activity_type="SAMPLING_AND_TESTING",
        frequency_per_year=3,
        justification_text="Quarterly port sampling ok",
        window_start="2026-10-01T00:00:00Z",
        window_end="2026-10-15T00:00:00Z",
    )
    fx.review_activity(
        api,
        activity["id"],
        qi_b["id"],
        "APPROVE",
        reviewer_note="Modified requirements accepted for this small importer",
    )

    response = api.post_pair_verification_approval(
        pair["id"],
        f.verification_approval_payload(
            approval_note=(
                "Modified verification requirements satisfied for this small importer"
            )
        ),
        make_qualified_individual_headers(qi_a["id"]),
    )
    signed = validate_success(response)

    assert signed["modified_requirements_only"] is True, (
        "a verified SMALL_IMPORTER_MODIFIED exemption sets modified_requirements_only"
    )
    assert_money(signed["adequacy_score_planned"], 43.48, "adequacy_score_planned")
    assert_pair_dimensions(
        signed,
        verification_status="VERIFICATION_APPROVED",
        entry_eligibility_status="ELIGIBLE",
        exemption_status="VERIFIED",
    )


# ---------------------------------------------------------------------------
# Verification records: the temporal rules and the existence rung
# ---------------------------------------------------------------------------


def test_record_performed_after_the_clock_is_refused(api: ApiClient):
    """PRD 3.6: "`performed_end` must be at or before the logical clock, since
    evidence cannot be filed for work that has not happened yet, or
    `ERR_RECORD_IN_FUTURE`."
    PRD 3.6: "Both performance variants share one formula over their own input
    set."
    PRD 3.6: "If the weight total is 0.00 the score is exactly 100.00 — no
    evidence is not bad evidence — and otherwise the score is the weighted sum
    divided by the weight total, rounded half up to two decimal places."

    The performed interval lies wholly inside the activity's October window, so
    the containment rule is satisfied and only the comparison against the logical
    clock of 2026-09-01 can refuse the filing.

    Design: Corner/validations/record_performed_after_the_clock_returns_record_in_future
    """
    world = fx.sampling_only_program(api, frequency_per_year=3)

    response = api.create_verification_record(
        f.record_payload(
            world.activity_id,
            outcome="PASS",
            performed_start="2026-10-05T00:00:00Z",
            performed_end="2026-10-06T00:00:00Z",
            findings_count=0,
            document_reference="LAB-2026-1006",
        ),
        make_qualified_individual_headers(world.qi_b_id),
    )
    validate_error(response, err.ERR_RECORD_IN_FUTURE)

    records = get_success_data(
        api.list_verification_records(
            COMPLIANCE_OFFICER_HEADERS, {"activity_id": world.activity_id}
        )
    )
    assert records == [], f"the refused filing must persist no record, got {records}"

    pair = fx.get_pair(api, world.pair_id)
    assert_money(pair["adequacy_score_realized"], 0.00, "adequacy_score_realized")
    supplier = fx.get_supplier(api, world.supplier_id)
    assert_money(
        supplier["performance_score_provisional"],
        100.00,
        "performance_score_provisional",
    )


def test_record_ending_exactly_at_window_end_is_outside_the_window(api: ApiClient):
    """PRD 3.6: "The record's closed performed interval must lie inside the
    activity's half-open planned window: `performed_start` at or after the
    activity's `window_start`, and `performed_end` strictly before the activity's
    `window_end`; a record that spills past the plan is refused with
    `ERR_RECORD_OUTSIDE_ACTIVITY_WINDOW`."

    The clock is advanced past the window so the future-record rule cannot mask
    the containment failure: performed_end equal to window_end is out, while one
    second earlier is in.

    Design: Corner/validations/record_ending_exactly_at_window_end_returns_record_outside_activity_window
    """
    world = fx.sampling_only_program(api, frequency_per_year=3)
    fx.set_clock(api, "2026-10-20T00:00:00Z")

    response = api.create_verification_record(
        f.record_payload(
            world.activity_id,
            outcome="PASS",
            performed_start="2026-10-14T00:00:00Z",
            performed_end="2026-10-15T00:00:00Z",
            findings_count=0,
            document_reference="LAB-2026-1015",
        ),
        make_qualified_individual_headers(world.qi_b_id),
    )
    validate_error(response, err.ERR_RECORD_OUTSIDE_ACTIVITY_WINDOW)

    records = get_success_data(
        api.list_verification_records(
            COMPLIANCE_OFFICER_HEADERS, {"activity_id": world.activity_id}
        )
    )
    assert records == [], f"the refused filing must persist no record, got {records}"

    accepted = validate_success(
        api.create_verification_record(
            f.record_payload(
                world.activity_id,
                outcome="PASS",
                performed_start="2026-10-14T00:00:00Z",
                performed_end="2026-10-14T23:59:59Z",
                findings_count=0,
                document_reference="LAB-2026-1015",
            ),
            make_qualified_individual_headers(world.qi_b_id),
        ),
        201,
    )
    assert accepted["record_status"] == "RECEIVED", (
        "an interval ending strictly before window_end lies inside the plan"
    )


def test_unknown_activity_id_reports_activity_not_found(api: ApiClient):
    """PRD 2.11 rung 10: "The `{id}` path segment or `activity_id` resolves to a
    `VerificationActivity` — `ERR_ACTIVITY_NOT_FOUND` (404), on the activity read,
    activity revision, activity review and record create."
    PRD 2.11 rung 25: "The activity named by `activity_id` has `status` equal to
    `APPROVED` — `ERR_ACTIVITY_NOT_APPROVED` (409), on record create."
    PRD 3.6: "The named activity's `status` must be `APPROVED`, or the filing is
    refused with `ERR_ACTIVITY_NOT_APPROVED` — evidence may not be filed against a
    plan step that was never approved, nor against one that has been retired."

    Both rungs are live in this world; the existence rung answers first for the
    unknown id, and the same body against the real PROPOSED activity then reaches
    the approval-state rung.

    Design: Corner/validations/unknown_activity_id_returns_activity_not_found_before_activity_not_approved
    """
    world = fx.analyzed_program(api, hazards=[fx.HAZARD_LISTERIA])
    activity = fx.create_activity(
        api,
        world.pair_id,
        world.qi_a_id,
        world.qi_b_id,
        activity_type="SAMPLING_AND_TESTING",
        frequency_per_year=3,
        justification_text=(
            "Three sampling events per year covering the pathogen profile of this "
            "frozen ready to eat fruit"
        ),
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-15T00:00:00Z",
    )

    body = dict(
        outcome="PASS",
        performed_start="2026-08-05T00:00:00Z",
        performed_end="2026-08-06T00:00:00Z",
        findings_count=0,
        document_reference="LAB-2026-0806",
    )

    missing = api.create_verification_record(
        f.record_payload(NON_EXISTENT_UUID, **body),
        make_qualified_individual_headers(world.qi_b_id),
    )
    error = validate_error(missing, err.ERR_ACTIVITY_NOT_FOUND)
    assert error["error_id"] != err.ERR_ACTIVITY_NOT_APPROVED, (
        "the existence rung answers before the approval-state rung"
    )

    unapproved = api.create_verification_record(
        f.record_payload(activity["id"], **body),
        make_qualified_individual_headers(world.qi_b_id),
    )
    validate_error(unapproved, err.ERR_ACTIVITY_NOT_APPROVED)

    assert fx.get_activity(api, activity["id"])["status"] == "PROPOSED", (
        "the activity was never reviewed, so it stays PROPOSED"
    )
    records = get_success_data(api.list_verification_records(COMPLIANCE_OFFICER_HEADERS))
    assert records == [], f"neither refused filing may persist a record, got {records}"


# ---------------------------------------------------------------------------
# Activity create: tenancy, ladder position and the justification minimum
# ---------------------------------------------------------------------------


def test_assigned_qi_from_another_importer_crosses_the_tenancy_boundary(api: ApiClient):
    """PRD 2.10: "Every entity referenced within a single request must belong to
    the same importer: on combination create, the supplier's `importer_id`, the
    food's `importer_id` and the body's `importer_id` must all agree, and the
    named `designated_qi_id` must belong to that same importer; on activity create
    or revision, the `assigned_qi_id` must belong to the combination's importer,
    and the combination's importer must match the acting qualified individual's
    own importer; on hazard-analysis create, the same importer agreement is
    required."
    PRD 2.10: "A crossing of that boundary is rejected with
    `ERR_IMPORTER_SCOPE_MISMATCH` (HTTP 409)."

    The assignee exists and is ACTIVE, so neither the not-found rung nor the
    designation-currency rung fires; only the tenancy boundary does.

    Design: Corner/validations/assigned_qi_from_another_importer_returns_importer_scope_mismatch
    """
    fx.set_clock(api, fx.CLOCK_BASE)
    importer_a = fx.create_importer(api)
    importer_b = fx.create_second_importer(api)
    qi_a = fx.create_qualified_individual(api, importer_a["id"])
    qi_c = fx.create_qualified_individual(
        api,
        importer_b["id"],
        full_name="Cara Lindqvist",
        email="cara@seabright.example",
        qualification_summary=(
            "Qualified individual for the Seabright FSVP programme with audit training"
        ),
        training_completed_at="2025-08-01T00:00:00Z",
    )
    supplier = fx.create_supplier(api, importer_a["id"])
    food = fx.create_food(api, importer_a["id"])
    pair = fx.create_pair(
        api, importer_a["id"], supplier["id"], food["id"], qi_a["id"]
    )
    analysis = fx.create_hazard_analysis(api, pair["id"], qi_a["id"])
    fx.add_hazard(api, analysis["id"], qi_a["id"], **fx.HAZARD_LISTERIA)
    fx.approve_analysis(api, analysis["id"], qi_a["id"])

    response = api.create_verification_activity(
        f.activity_payload(
            pair["id"],
            qi_c["id"],
            activity_type="SAMPLING_AND_TESTING",
            frequency_per_year=3,
            justification_text=(
                "Three sampling events per year covering the pathogen profile of "
                "this frozen ready to eat fruit"
            ),
            window_start="2026-10-01T00:00:00Z",
            window_end="2026-10-15T00:00:00Z",
        ),
        make_qualified_individual_headers(qi_a["id"]),
    )
    validate_error(response, err.ERR_IMPORTER_SCOPE_MISMATCH)

    activities = get_success_data(
        api.list_verification_activities(
            COMPLIANCE_OFFICER_HEADERS, {"pair_id": pair["id"]}
        )
    )
    assert activities == [], (
        f"the refused proposal must persist no activity, got {activities}"
    )

    roster = get_success_data(
        api.list_importer_qualified_individuals(
            importer_b["id"], COMPLIANCE_OFFICER_HEADERS
        )
    )
    foreign_qi = [row for row in roster if row["id"] == qi_c["id"]]
    assert foreign_qi and foreign_qi[0]["status"] == "ACTIVE", (
        "the assignee itself is a perfectly valid ACTIVE individual of the other importer"
    )
    assert_money(
        fx.get_pair(api, pair["id"])["adequacy_score_planned"],
        0.00,
        "adequacy_score_planned",
    )


def test_role_authorisation_precedes_request_shape(api: ApiClient):
    """PRD 2.11: "The ordering below is normative — a request that violates
    several rules always reports the earliest one."
    PRD 2.11 rung 2: "Role authorisation for the target endpoint —
    `ERR_ROLE_NOT_PERMITTED` (403), on every endpoint."
    PRD 2.11 rung 3: "Request shape: required fields present, types correct, enum
    values in range, integers inside their declared bounds, datetimes valid ISO
    8601 UTC, string lengths inside their declared constraints, `limit` between 1
    and 100, `offset` at least 0 — `ERR_INVALID_REQUEST` (400), on every
    endpoint."
    PRD 2.1: "A request whose role is recognised but is not authorised for the
    target operation is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    An entry filer posting a malformed importer body must be refused for the role,
    not for the body; the same body from the compliance office then reaches the
    shape rung.

    Design: Corner/validations/role_check_at_priority_two_precedes_shape_check_at_priority_three
    """
    fx.set_clock(api, fx.CLOCK_BASE)
    malformed = f.importer_payload(
        legal_name="Rogue Filer LLC",
        dnb_number=f.OMIT,
        unique_facility_identifier=f.OMIT,
    )

    refused = api.create_importer(malformed, ENTRY_FILER_HEADERS)
    error = validate_error(refused, err.ERR_ROLE_NOT_PERMITTED)
    assert error["error_id"] != err.ERR_INVALID_REQUEST, (
        "authorising the caller precedes validating the body, so no schema detail leaks"
    )

    validate_error(
        api.create_importer(malformed, COMPLIANCE_OFFICER_HEADERS),
        err.ERR_INVALID_REQUEST,
    )


def test_short_justification_is_refused(api: ApiClient):
    """PRD 3.4: "A `justification_text` shorter than 20 characters is refused
    outright with `ERR_JUSTIFICATION_INSUFFICIENT`."
    PRD 3.4: "A justification that clears 20 characters but is shorter than 40
    characters is accepted and halves the activity's contribution to coverage."
    PRD 3.4: "Concretely, the activity's `coverage_weight` is the type weight for
    its `activity_type` — 10.0 for `ONSITE_AUDIT`, 6.0 for
    `SAMPLING_AND_TESTING`, 3.0 for `RECORDS_REVIEW`, and 2.0 for
    `OTHER_SUPPLIER_EVALUATION` — multiplied by the smaller of its
    `frequency_per_year` and 4, multiplied by a justification factor of 1.0 when
    `justification_text` is at least 40 characters long and 0.5 otherwise, with
    the product rounded half up to two decimal places."

    "Too short" is a well-formed string of the declared type, so the shape rung
    passes and the 20-character programme requirement answers 422; a 26-character
    justification is accepted and scores half coverage.

    Design: Corner/validations/justification_under_twenty_characters_returns_justification_insufficient
    """
    world = fx.analyzed_program(api, hazards=[fx.HAZARD_LISTERIA])

    def proposal(justification_text: str) -> dict:
        return f.activity_payload(
            world.pair_id,
            world.qi_b_id,
            activity_type="SAMPLING_AND_TESTING",
            frequency_per_year=3,
            justification_text=justification_text,
            window_start="2026-10-01T00:00:00Z",
            window_end="2026-10-15T00:00:00Z",
        )

    response = api.create_verification_activity(
        proposal("Too short"), make_qualified_individual_headers(world.qi_a_id)
    )
    validate_error(response, err.ERR_JUSTIFICATION_INSUFFICIENT)

    activities = get_success_data(
        api.list_verification_activities(
            COMPLIANCE_OFFICER_HEADERS, {"pair_id": world.pair_id}
        )
    )
    assert activities == [], (
        f"the refused proposal must persist no activity, got {activities}"
    )

    accepted = validate_success(
        api.create_verification_activity(
            proposal("Quarterly port sampling ok"),
            make_qualified_individual_headers(world.qi_a_id),
        ),
        201,
    )
    assert_money(accepted["coverage_weight"], 9.00, "coverage_weight")
