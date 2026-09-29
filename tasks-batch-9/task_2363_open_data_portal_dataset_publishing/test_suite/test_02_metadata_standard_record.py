"""
The metadata standard record: the pinned rounding order behind
`completeness_score`, the acceptance floor, the return-and-revise loop, and the
readiness gate that consumes the acceptance.
"""

from test_helpers import (
    ANONYMOUS_HEADERS,
    PORTAL_ADMIN_HEADERS,
    assert_common_fields,
    assert_component_contributions,
    assert_dataset_states,
    assert_money,
    factories,
    fixtures,
    validate_error,
    validate_success,
)

PERMITS_DATASET = {
    "title": "Building Permits",
    "slug": "building-permits",
    "description": "Building Permits published by the department",
    "public_demand_score": 70,
    "policy_value_score": 70,
}

LIBRARY_DATASET = {
    "title": "Library Circulation Statistics",
    "slug": "library-circulation",
    "description": "Library Circulation Statistics published by the department",
    "public_demand_score": 80,
    "policy_value_score": 80,
}

# 7 of 9 documented columns, 16 of 24 provenance lines, 5 of 6 attribution elements.
THIN_METADATA = {
    "data_dictionary_field_count": 7,
    "provenance_detail_lines": 16,
    "attribution_element_count": 5,
}


def _submitted_thin_record(api):
    """A screening 'building-permits' dataset whose metadata record sits in SUBMITTED."""
    ctx = fixtures.setup_screening_dataset(
        api=api, credit_units=0, dataset_overrides=PERMITS_DATASET
    )
    record = fixtures.draft_metadata_record(
        ctx["dataset_id"], ctx["license_id"], ctx["department_id"], api=api, **THIN_METADATA
    )
    record = fixtures.submit_metadata_record(record["id"], ctx["department_id"], api=api)
    ctx["metadata_record"] = record
    ctx["metadata_record_id"] = record["id"]
    return ctx


def test_acceptance_refused_when_each_contribution_is_rounded_before_the_sum(api):
    """Rounding the six components first leaves the total one hundredth below the floor.

    The PRD: "The metadata completeness score rounds each of its six weighted component
    contributions to 2 decimal places first, stores them in `component_contributions`,
    sums the already-rounded values, and rounds that sum again." and "The six rounded
    results are stored, in exactly the declaration order above — dictionary,
    provenance, contact, frequency, licence, attribution — in
    `component_contributions`."

    With 7 of 9 columns, 16 of 24 provenance lines and 5 of 6 attribution elements the
    stored contributions are 23.33, 13.33, 15.00, 15.00, 10.00 and 8.33, whose sum is
    84.99. The PRD requires that "`completeness_score` must be at least 85.00 under the
    pinned rounding order above, or the record is refused with
    `ERR_METADATA_INCOMPLETE`", so the acceptance fails and the record is unmoved.

    Design: Difficulty/combinatorial_formula/metadata_completeness_round_each_contribution_then_sum_lands_at_8499
    """
    ctx = _submitted_thin_record(api)

    validate_error(
        api.decide_metadata_record(
            ctx["metadata_record_id"], factories.decision_payload("ACCEPT"), PORTAL_ADMIN_HEADERS
        ),
        "ERR_METADATA_INCOMPLETE",
        422,
    )

    record = validate_success(
        api.get_metadata_record(ctx["metadata_record_id"], ANONYMOUS_HEADERS)
    )
    assert record["status"] == "SUBMITTED", (
        f"A refused acceptance must leave the record SUBMITTED, got {record['status']}"
    )
    assert_money(record["completeness_score"], 84.99, "completeness_score")
    assert_component_contributions(record, [23.33, 13.33, 15.00, 15.00, 10.00, 8.33])


def test_returned_record_revised_to_full_documentation_is_then_accepted(api):
    """The return-and-revise loop recomputes the contributions and clears the floor.

    The PRD: "A `RETURN` decision moves the record `SUBMITTED → RETURNED` and requires
    a `returned_reason` in the body, which is stored on the record as the reviewer's
    note." and "A returned record is not dead: the coordinator revising it moves it
    `RETURNED → DRAFT`, which clears `returned_reason` and recomputes the six
    contributions and `completeness_score`."

    Documenting all 9 columns, all 24 provenance lines and all 6 attribution elements
    lifts every contribution to its full weight — 30.00, 20.00, 15.00, 15.00, 10.00 and
    10.00 — so the record scores 100.00 and the second acceptance succeeds.

    Design: Difficulty/combinatorial_formula/metadata_completeness_round_each_contribution_then_sum_lands_at_8499
    """
    ctx = _submitted_thin_record(api)
    record_id = ctx["metadata_record_id"]
    validate_error(
        api.decide_metadata_record(
            record_id, factories.decision_payload("ACCEPT"), PORTAL_ADMIN_HEADERS
        ),
        "ERR_METADATA_INCOMPLETE",
        422,
    )

    returned = fixtures.return_metadata_record(
        record_id, "Data dictionary and provenance below the acceptance floor", api=api
    )
    assert returned["status"] == "RETURNED", (
        f"Expected RETURNED after a RETURN decision, got {returned['status']}"
    )
    assert returned["returned_reason"] == (
        "Data dictionary and provenance below the acceptance floor"
    ), f"The reviewer's note must be stored, got {returned['returned_reason']!r}"

    revised = fixtures.revise_metadata_record(
        record_id,
        ctx["department_id"],
        api=api,
        data_dictionary_field_count=9,
        provenance_detail_lines=24,
        attribution_element_count=6,
    )
    assert revised["status"] == "DRAFT", (
        f"Revising a returned record must return it to DRAFT, got {revised['status']}"
    )
    assert revised["returned_reason"] is None, (
        f"Revising must clear returned_reason, got {revised['returned_reason']!r}"
    )
    assert_money(revised["completeness_score"], 100.00, "completeness_score")
    assert_component_contributions(revised, [30.00, 20.00, 15.00, 15.00, 10.00, 10.00])

    fixtures.submit_metadata_record(record_id, ctx["department_id"], api=api)
    accepted = fixtures.accept_metadata_record(record_id, api=api)
    assert accepted["status"] == "ACCEPTED", (
        f"A record at 100.00 must be acceptable, got {accepted['status']}"
    )
    assert_money(accepted["completeness_score"], 100.00, "completeness_score")


def test_retired_licence_outranks_the_completeness_floor_on_acceptance(api):
    """A record that is both under-documented and licence-retired reports the licence.

    The PRD evaluates its guards in a fixed order: "All validations are evaluated in
    the ascending priority order below". Priority 18 is "Licence still current, on
    `POST /open-data/metadata-records/{metadataRecordId}/decide` and
    `POST /open-data/datasets/{datasetId}/publish`: the backing licence has `retired`
    false — otherwise `ERR_LICENSE_RETIRED` (409)."; the completeness floor only
    arrives at priority 26, as "Metadata acceptance floor, on a metadata decision whose
    `decision` is `ACCEPT`: `ERR_METADATA_INCOMPLETE` (422)."

    This record scores 84.99, so both guards are armed; the answer must be
    `ERR_LICENSE_RETIRED` and not `ERR_METADATA_INCOMPLETE`.

    Design: Difficulty/priority_pair_validation_conflict/metadata_license_referential_outranks_completeness_floor
    """
    ctx = _submitted_thin_record(api)
    fixtures.retire_license(ctx["license_id"], api=api)

    validate_error(
        api.decide_metadata_record(
            ctx["metadata_record_id"], factories.decision_payload("ACCEPT"), PORTAL_ADMIN_HEADERS
        ),
        "ERR_LICENSE_RETIRED",
        409,
    )


def test_retiring_a_licence_leaves_its_class_and_the_submitted_record_intact(api):
    """Retirement is a flag on the licence, not a rewrite of its terms or its records.

    The PRD: "Retiring a licence sets `retired` to true; metadata records already
    accepted against it keep the reference, but no further record may be accepted
    against it and no dataset backed by it may be published." The derived class is
    unaffected — "otherwise, if attribution is required, commercial use is allowed and
    share-alike is not required, the class is `ATTRIBUTION`;" — and the refused record
    stays in `SUBMITTED` carrying the same 84.99 it had before.

    Design: Difficulty/priority_pair_validation_conflict/metadata_license_referential_outranks_completeness_floor
    """
    ctx = _submitted_thin_record(api)
    fixtures.retire_license(ctx["license_id"], api=api)
    validate_error(
        api.decide_metadata_record(
            ctx["metadata_record_id"], factories.decision_payload("ACCEPT"), PORTAL_ADMIN_HEADERS
        ),
        "ERR_LICENSE_RETIRED",
        409,
    )

    license_term = validate_success(api.get_license(ctx["license_id"], ANONYMOUS_HEADERS))
    assert license_term["retired"] is True, (
        f"Expected retired true, got {license_term['retired']!r}"
    )
    assert license_term["reuse_permission_class"] == "ATTRIBUTION", (
        f"Expected reuse_permission_class ATTRIBUTION, got {license_term['reuse_permission_class']}"
    )

    record = validate_success(
        api.get_metadata_record(ctx["metadata_record_id"], ANONYMOUS_HEADERS)
    )
    assert record["status"] == "SUBMITTED", (
        f"The record must remain SUBMITTED, got {record['status']}"
    )
    assert record["license_id"] == ctx["license_id"], "The licence reference must be kept"
    assert_money(record["completeness_score"], 84.99, "completeness_score")


def test_mark_ready_refused_while_the_metadata_record_is_only_submitted(api):
    """Readiness needs an accepted record even when privacy clearance is already in hand.

    The PRD: "The dataset advances `SCREENING → READY` only when exactly one metadata
    record for it sits in `ACCEPTED` and exactly one privacy assessment for it sits in
    `CLEARED`; a missing acceptance is `ERR_METADATA_NOT_ACCEPTED` and a missing
    clearance is `ERR_PRIVACY_CLEARANCE_REQUIRED`."

    The assessment here is `CLEARED`, so only the acceptance is missing. The refusal
    must be `ERR_METADATA_NOT_ACCEPTED`, the dataset must stay in `SCREENING`, and its
    `version` must still be the 2 it reached on screening.

    Design: Difficulty/cross_entity_state_dependency/mark_ready_requires_accepted_metadata_and_cleared_privacy
    """
    ctx = fixtures.setup_screening_dataset(
        api=api, credit_units=0, dataset_overrides=LIBRARY_DATASET
    )
    record = fixtures.draft_metadata_record(
        ctx["dataset_id"], ctx["license_id"], ctx["department_id"], api=api
    )
    fixtures.submit_metadata_record(record["id"], ctx["department_id"], api=api)
    assessment = fixtures.land_cleared_assessment(ctx["dataset_id"], api=api)
    assert assessment["status"] == "CLEARED", (
        f"Setup must leave the assessment CLEARED, got {assessment['status']}"
    )

    validate_error(
        api.mark_dataset_ready(ctx["dataset_id"], ctx["coordinator_headers"]),
        "ERR_METADATA_NOT_ACCEPTED",
        409,
    )

    dataset = fixtures.read_dataset(ctx["dataset_id"], api=api)
    assert_dataset_states(dataset, publication_status="SCREENING")
    assert_common_fields(dataset, expected_version=2)


def test_mark_ready_succeeds_once_the_acceptance_lands_and_bumps_only_the_version(api):
    """Accepting the record satisfies the second half of the gate.

    The PRD: "The transition increments the dataset's `version` and changes nothing
    else." The dataset stood at `version` 2 with the refusal, so the successful
    transition must leave it `READY` at `version` 3, with the clearance that was
    already in place untouched.

    Design: Difficulty/cross_entity_state_dependency/mark_ready_requires_accepted_metadata_and_cleared_privacy
    """
    ctx = fixtures.setup_screening_dataset(
        api=api, credit_units=0, dataset_overrides=LIBRARY_DATASET
    )
    record = fixtures.draft_metadata_record(
        ctx["dataset_id"], ctx["license_id"], ctx["department_id"], api=api
    )
    fixtures.submit_metadata_record(record["id"], ctx["department_id"], api=api)
    assessment = fixtures.land_cleared_assessment(ctx["dataset_id"], api=api)
    validate_error(
        api.mark_dataset_ready(ctx["dataset_id"], ctx["coordinator_headers"]),
        "ERR_METADATA_NOT_ACCEPTED",
        409,
    )

    accepted = fixtures.accept_metadata_record(record["id"], api=api)
    assert accepted["status"] == "ACCEPTED", (
        f"Expected ACCEPTED, got {accepted['status']}"
    )
    assert_money(accepted["completeness_score"], 100.00, "completeness_score")

    dataset = validate_success(
        api.mark_dataset_ready(ctx["dataset_id"], ctx["coordinator_headers"])
    )
    assert_dataset_states(dataset, publication_status="READY")
    assert_common_fields(dataset, expected_version=3)

    still_cleared = validate_success(
        api.get_privacy_assessment(assessment["id"], PORTAL_ADMIN_HEADERS)
    )
    assert still_cleared["status"] == "CLEARED", (
        f"The clearance must be untouched, got {still_cleared['status']}"
    )
