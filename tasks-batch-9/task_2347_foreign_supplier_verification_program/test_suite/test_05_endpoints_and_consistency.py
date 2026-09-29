"""Endpoint behaviour: filtered listings, action endpoints, the inspection package.

Also covers the immediate-consistency promise of PRD §2.7 -- a write's own
response, and the very next read, already carry every dependent value.
"""

from datetime import datetime

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as err
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_hazard_scores,
    assert_importer_rollup,
    assert_ids,
    assert_money,
    assert_pair_dimensions,
)
from test_helpers.test_users import (
    COMPLIANCE_OFFICER_HEADERS,
    FDA_INSPECTOR_HEADERS,
    make_qualified_individual_headers,
)

CLOCK_BASE = "2026-09-01T00:00:00Z"

SAMPLING_JUSTIFICATION = (
    "Three sampling events per year covering the pathogen profile of this frozen "
    "ready to eat fruit"
)


def _instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp so two spellings of one instant compare equal."""
    assert value is not None, "expected a timestamp, got null"
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _assert_instant(actual: str, expected: str, label: str) -> None:
    assert _instant(actual) == _instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


# ---------------------------------------------------------------------------
# Endpoint behaviour
# ---------------------------------------------------------------------------


def test_pair_listing_filtered_on_verification_status_reports_matching_total(api):
    """PRD §3.2: "Combinations can be listed with optional filters on `importer_id`,
    `supplier_id`, `food_id`, `designated_qi_id`, `active_hazard_analysis_id`,
    `verification_status`, `entry_eligibility_status`, `exemption_status` and
    `risk_tier`, plus `limit` and `offset`; a single read returns all three
    dimensions, both adequacy variants, the risk fields, the reassessment dates
    and the row's `version`."
    PRD §2.3: "List responses carry `limit`, `offset`, `total_count` and `has_more`
    inside the envelope's `meta` object, where `total_count` is the number of rows
    matching the filter before pagination is applied and `has_more` indicates
    whether rows remain beyond the current page."
    PRD §3.3: "the hazard load is the sum of the `risk_score` values of only those
    hazards in the active analysis whose `requires_control` is true, rounded half
    up to two decimal places, and it is 0.00 when `active_hazard_analysis_id` is
    null"

    Design: Corner/endpoints/pair_listing_filters_on_verification_status_and_reports_total
    """
    fx.set_clock(api, CLOCK_BASE)
    importer = fx.create_importer(api)
    qi_a = fx.create_qualified_individual(api, importer["id"])
    supplier = fx.create_supplier(api, importer["id"])
    food1 = fx.create_food(api, importer["id"])
    food2 = fx.create_food(
        api,
        importer["id"],
        food_name="Whole green plantains",
        fda_product_code="20-PLA-02",
        is_raw_agricultural_commodity=True,
        ready_to_eat=False,
    )
    pair1 = fx.create_pair(api, importer["id"], supplier["id"], food1["id"], qi_a["id"])
    pair2 = fx.create_pair(api, importer["id"], supplier["id"], food2["id"], qi_a["id"])

    # Only the first combination gets an approved hazard analysis, so only it
    # leaves DRAFT for HAZARD_ANALYZED (PRD §3.3).
    analysis = fx.create_hazard_analysis(api, pair1["id"], qi_a["id"], pair1["version"])
    fx.add_hazard(api, analysis["id"], qi_a["id"], **fx.HAZARD_LISTERIA)
    fx.approve_analysis(api, analysis["id"], qi_a["id"])

    rows, meta = validate_paginated(
        api.list_supplier_food_pairs(
            COMPLIANCE_OFFICER_HEADERS,
            {
                "importer_id": importer["id"],
                "verification_status": "HAZARD_ANALYZED",
                "limit": 50,
                "offset": 0,
            },
        )
    )
    assert meta["total_count"] == 1, (
        f"filtered total_count: expected 1, got {meta['total_count']}"
    )
    assert meta["has_more"] is False, "one row on a page of 50 leaves nothing beyond"
    assert_ids(rows, [pair1["id"]])
    assert rows[0]["id"] == pair1["id"]

    all_rows, all_meta = validate_paginated(
        api.list_supplier_food_pairs(
            COMPLIANCE_OFFICER_HEADERS,
            {"importer_id": importer["id"], "limit": 50, "offset": 0},
        )
    )
    assert all_meta["total_count"] == 2, (
        f"unfiltered total_count: expected 2, got {all_meta['total_count']}"
    )
    assert_ids(all_rows, [pair1["id"], pair2["id"]])

    unanalyzed = fx.get_pair(api, pair2["id"])
    assert_pair_dimensions(unanalyzed, verification_status="DRAFT")
    assert_money(
        unanalyzed["composite_hazard_risk"], 0.00, "pair2.composite_hazard_risk"
    )

    analyzed = fx.get_pair(api, pair1["id"])
    assert analyzed["risk_tier"] == "LOW", (
        f"pair1.risk_tier: expected LOW, got {analyzed['risk_tier']}"
    )


def test_reassessment_moves_only_the_verification_dimension(api):
    """PRD §3.5: "Either a `ComplianceOfficer` or a `QualifiedIndividual` may trigger
    it, supplying a `trigger_reason` and an optional `note`, on a combination whose
    `verification_status` is `VERIFICATION_APPROVED`; the combination moves
    `VERIFICATION_APPROVED → REASSESSMENT_REQUIRED`, `last_reassessed_at` is set to
    the logical clock, `reassessment_due_at` is recomputed from it, the
    combination's `version` is incremented by one, and the importer's
    `program_status` is recomputed — landing on `AT_RISK` while any combination sits
    in `REASSESSMENT_REQUIRED`. Its `entry_eligibility_status` is deliberately left
    exactly as it was: a voluntary reassessment of new hazard information does not,
    by itself, stop shipments at the border."
    PRD §2.4: "a supplier-food combination's `reassessment_due_at` is its
    `last_reassessed_at` advanced by 36 calendar months."

    Design: Corner/endpoints/reassessment_action_endpoint_moves_only_the_verification_dimension
    """
    world = fx.base_program(api)
    analysis = fx.create_hazard_analysis(api, world.pair_id, world.qi_a_id)
    fx.add_hazard(api, analysis["id"], world.qi_a_id, **fx.HAZARD_LISTERIA)
    fx.approve_analysis(api, analysis["id"], world.qi_a_id)
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
    fx.review_activity(api, activity["id"], world.qi_b_id, "APPROVE")
    approved = fx.approve_pair_verification(api, world.pair_id, world.qi_a_id)
    assert_pair_dimensions(
        approved,
        verification_status="VERIFICATION_APPROVED",
        entry_eligibility_status="ELIGIBLE",
    )
    version_before = fx.get_pair(api, world.pair_id)["version"]

    fx.set_clock(api, "2027-03-01T00:00:00Z")
    data = validate_success(
        api.post_pair_reassessment(
            world.pair_id,
            f.reassessment_payload(
                "NEW_INFORMATION",
                note="New country-of-origin pathogen surveillance data received",
            ),
            COMPLIANCE_OFFICER_HEADERS,
        )
    )

    assert_pair_dimensions(
        data,
        verification_status="REASSESSMENT_REQUIRED",
        entry_eligibility_status="ELIGIBLE",
    )
    _assert_instant(
        data["last_reassessed_at"], "2027-03-01T00:00:00.000Z", "last_reassessed_at"
    )
    _assert_instant(
        data["reassessment_due_at"], "2030-03-01T00:00:00.000Z", "reassessment_due_at"
    )
    assert data["version"] == version_before + 1, (
        f"version: expected {version_before + 1}, got {data['version']}"
    )

    importer = fx.get_importer(api, world.importer_id)
    assert_importer_rollup(importer, program_status="AT_RISK", blocked_pair_count=0)


def test_hazard_listing_filters_on_requires_control(api):
    """PRD §3.3: "The hazards of one analysis can be listed with optional
    `hazard_type` and `requires_control` filters plus `limit` and `offset`."
    PRD §3.3: "A hazard's `requires_control` flag is true exactly when its
    `risk_score` is at or above 12.00 — the boundary is inclusive, so a hazard
    scoring exactly 12.00 *is* a significant hazard requiring a control."
    PRD §3.3: "Writing a hazard recomputes its analysis's `hazard_count` as the
    number of hazard rows, its `significant_hazard_count` as the number of those
    rows whose `requires_control` is true, and its `risk_total`."

    Design: Corner/endpoints/hazard_subresource_listing_filters_on_requires_control
    """
    world = fx.single_qi_program(api, evaluate_supplier_first=False)
    analysis = fx.create_hazard_analysis(api, world.pair_id, world.qi_a_id)
    # Ready-to-eat GENERAL food: biological 4 x 3 x 1.15 = 13.80 (requires control);
    # chemical 3 x 2 x 0.70 importer control = 4.20 (does not).
    significant = fx.add_hazard(api, analysis["id"], world.qi_a_id, **fx.HAZARD_LISTERIA)
    sub_threshold = fx.add_hazard(
        api, analysis["id"], world.qi_a_id, **fx.HAZARD_PESTICIDE
    )

    rows, meta = validate_paginated(
        api.list_hazards(
            analysis["id"],
            FDA_INSPECTOR_HEADERS,
            {"requires_control": "true", "limit": 50, "offset": 0},
        )
    )
    assert meta["total_count"] == 1, (
        f"requires_control=true total_count: expected 1, got {meta['total_count']}"
    )
    assert meta["has_more"] is False
    assert rows[0]["id"] == significant["id"]
    assert_hazard_scores(rows[0], 13.80, True)

    parent = fx.get_analysis(api, analysis["id"])
    assert parent["hazard_count"] == 2, (
        f"hazard_count: expected 2, got {parent['hazard_count']}"
    )

    other_rows, other_meta = validate_paginated(
        api.list_hazards(
            analysis["id"],
            FDA_INSPECTOR_HEADERS,
            {"requires_control": "false", "limit": 50, "offset": 0},
        )
    )
    assert other_meta["total_count"] == 1, (
        f"requires_control=false total_count: expected 1, got "
        f"{other_meta['total_count']}"
    )
    assert other_rows[0]["id"] == sub_threshold["id"]
    assert_hazard_scores(other_rows[0], 4.20, False)


def test_records_package_partitions_available_and_expired_at_the_supplied_as_of(api):
    """PRD §3.9: "and four counts: `retained_record_count`, the number of records
    regardless of status; `available_for_inspection_count`, the number of
    non-rescinded records whose `retained_until` is at or after the evaluation
    instant; `expired_record_count`, the number of non-rescinded records whose
    `retained_until` is strictly before the evaluation instant; and
    `rescinded_record_count`, the number of records whose `record_status` is
    `RESCINDED`."
    PRD §3.9: "The evaluation instant is the supplied `as_of_iso8601` when one is
    given and the logical clock otherwise."
    PRD §3.9: "Every verification record's `retained_until` is its `performed_end`
    advanced by the importer's `record_retention_months` in calendar months"
    PRD §3.9: "The package performs no writes."

    Design: Corner/endpoints/records_package_partitions_available_and_expired_at_the_supplied_as_of
    """
    world = fx.base_program(api, evaluate_supplier_first=False)
    analysis = fx.create_hazard_analysis(api, world.pair_id, world.qi_a_id)
    fx.add_hazard(api, analysis["id"], world.qi_a_id, **fx.HAZARD_LISTERIA)
    fx.approve_analysis(api, analysis["id"], world.qi_a_id)

    october = fx.create_activity(
        api,
        world.pair_id,
        world.qi_a_id,
        world.qi_b_id,
        activity_type="RECORDS_REVIEW",
        frequency_per_year=1,
        justification_text=(
            "October records review of the supplier pathogen monitoring documentation"
        ),
        window_start="2026-10-01T00:00:00Z",
        window_end="2026-10-15T00:00:00Z",
    )
    fx.review_activity(api, october["id"], world.qi_b_id, "APPROVE")
    november = fx.create_activity(
        api,
        world.pair_id,
        world.qi_a_id,
        world.qi_b_id,
        activity_type="RECORDS_REVIEW",
        frequency_per_year=1,
        justification_text=(
            "November records review of the supplier pathogen monitoring documentation"
        ),
        window_start="2026-11-01T00:00:00Z",
        window_end="2026-11-15T00:00:00Z",
    )
    fx.review_activity(api, november["id"], world.qi_b_id, "APPROVE")

    fx.set_clock(api, "2026-12-01T00:00:00Z")
    record_a = fx.file_record(
        api,
        october["id"],
        world.qi_b_id,
        outcome="PASS",
        performed_start="2026-10-05T00:00:00Z",
        performed_end="2026-10-06T00:00:00Z",
        findings_count=0,
        document_reference="RR-2026-1006",
    )
    record_b = fx.file_record(
        api,
        november["id"],
        world.qi_b_id,
        outcome="PASS",
        performed_start="2026-11-05T00:00:00Z",
        performed_end="2026-11-06T00:00:00Z",
        findings_count=0,
        document_reference="RR-2026-1106",
    )
    pair_version_before = fx.get_pair(api, world.pair_id)["version"]
    record_versions_before = (
        fx.get_record(api, record_a["id"])["version"],
        fx.get_record(api, record_b["id"])["version"],
    )

    # The as_of sits between the two retention boundaries.
    at_as_of = validate_success(
        api.get_records_package(
            world.importer_id,
            FDA_INSPECTOR_HEADERS,
            {"as_of_iso8601": "2028-10-07T00:00:00Z"},
        )
    )
    assert at_as_of["retained_record_count"] == 2, (
        f"retained_record_count: expected 2, got {at_as_of['retained_record_count']}"
    )
    assert at_as_of["available_for_inspection_count"] == 1, (
        "available_for_inspection_count: expected 1, got "
        f"{at_as_of['available_for_inspection_count']}"
    )
    assert at_as_of["expired_record_count"] == 1, (
        f"expired_record_count: expected 1, got {at_as_of['expired_record_count']}"
    )
    assert at_as_of["rescinded_record_count"] == 0, (
        f"rescinded_record_count: expected 0, got {at_as_of['rescinded_record_count']}"
    )
    assert at_as_of["qualified_individual_designated"] is True
    assert at_as_of["program_status"] == "COMPLIANT", (
        f"program_status: expected COMPLIANT, got {at_as_of['program_status']}"
    )

    # Defaulting to the logical clock 2026-12-01 puts both records back inside
    # their retention period.
    at_clock = validate_success(
        api.get_records_package(world.importer_id, FDA_INSPECTOR_HEADERS)
    )
    assert at_clock["available_for_inspection_count"] == 2, (
        "available_for_inspection_count at the clock: expected 2, got "
        f"{at_clock['available_for_inspection_count']}"
    )
    assert at_clock["expired_record_count"] == 0, (
        f"expired_record_count at the clock: expected 0, got "
        f"{at_clock['expired_record_count']}"
    )
    assert at_clock["qualified_individual_designated"] is True
    assert at_clock["program_status"] == "COMPLIANT"

    stored_a = fx.get_record(api, record_a["id"])
    stored_b = fx.get_record(api, record_b["id"])
    _assert_instant(
        stored_a["retained_until"], "2028-10-06T00:00:00.000Z", "recA.retained_until"
    )
    _assert_instant(
        stored_b["retained_until"], "2028-11-06T00:00:00.000Z", "recB.retained_until"
    )

    assert fx.get_pair(api, world.pair_id)["version"] == pair_version_before, (
        "the records package must not write to the combination"
    )
    assert (stored_a["version"], stored_b["version"]) == record_versions_before, (
        "the records package must not write to the verification records"
    )


def test_sahcodha_hazard_makes_verification_approval_demand_an_onsite_audit(api):
    """PRD §3.5: "If the active analysis contains any hazard whose `severity` is 5,
    whose `requires_control` is true, and whose `control_owner` is
    `FOREIGN_SUPPLIER` — a SAHCODHA hazard the supplier itself controls — then the
    combination must also carry an `APPROVED` activity whose `activity_type` is
    `ONSITE_AUDIT` and whose `frequency_per_year` is at least 1; absent that,
    `ERR_ONSITE_AUDIT_REQUIRED`."
    PRD §3.3: "`required_coverage` is `composite_hazard_risk` multiplied by 1.5,
    rounded half up to two decimal places."

    Design: Corner/endpoints/sahcodha_hazard_makes_verification_approval_demand_an_onsite_audit
    """
    world = fx.base_program(api)
    analysis = fx.create_hazard_analysis(api, world.pair_id, world.qi_a_id)
    # Severity 5, probability 3, foreign-supplier controlled, ready-to-eat food.
    sahcodha = fx.add_hazard(
        api, analysis["id"], world.qi_a_id, **fx.HAZARD_SALMONELLA
    )
    fx.approve_analysis(api, analysis["id"], world.qi_a_id)
    sampling = fx.create_activity(
        api,
        world.pair_id,
        world.qi_a_id,
        world.qi_b_id,
        activity_type="SAMPLING_AND_TESTING",
        frequency_per_year=5,
        justification_text=(
            "Five sampling and testing events per year were selected in place of an "
            "onsite audit of the facility"
        ),
        window_start="2026-10-01T00:00:00Z",
        window_end="2026-10-15T00:00:00Z",
    )
    fx.review_activity(api, sampling["id"], world.qi_b_id, "APPROVE")

    response = api.post_pair_verification_approval(
        world.pair_id,
        f.verification_approval_payload(
            approval_note="Requesting approval on sampling alone for a severity five hazard"
        ),
        make_qualified_individual_headers(world.qi_a_id),
    )
    validate_error(response, err.ERR_ONSITE_AUDIT_REQUIRED)

    assert_money(sahcodha["risk_score"], 17.25, "hazard.risk_score")
    pair = fx.get_pair(api, world.pair_id)
    assert_money(pair["required_coverage"], 25.88, "required_coverage")
    assert_money(pair["adequacy_score_planned"], 92.74, "adequacy_score_planned")
    assert pair["required_annual_frequency"] == 1, (
        f"required_annual_frequency: expected 1, got {pair['required_annual_frequency']}"
    )
    assert_pair_dimensions(pair, verification_status="HAZARD_ANALYZED")


# ---------------------------------------------------------------------------
# Immediate consistency
# ---------------------------------------------------------------------------


def test_exemption_verification_response_already_carries_the_eligibility_flip(api):
    """PRD §3.8: "Verification also moves `entry_eligibility_status` `PENDING →
    ELIGIBLE` in the same request while deliberately leaving `verification_status`
    at `DRAFT`: a verified exemption makes a combination entry-eligible with no
    hazard analysis and no verification plan whatsoever."
    PRD §3.8: "It recomputes `modified_requirements_only`, which is true exactly
    when `exemption_status` is `VERIFIED` and `exemption_type` is either
    `US_CUSTOMER_WRITTEN_ASSURANCE` or `SMALL_IMPORTER_MODIFIED`, and false for
    every other verified exemption type."
    PRD §3.8: "Every accepted action increments the combination's `version` by one"
    PRD §2.7: "Consistency in this system is immediate: when a write changes a
    value that another row's specification depends on, the dependent row is updated
    inside the same request, and its own `updated_at` and `version` move
    accordingly."
    PRD §2.2: "Unless otherwise noted, operations that create or modify a resource
    will return the created or updated resource object in the data field."

    Design: Corner/consistency model/exemption_verification_response_already_carries_the_eligibility_flip
    """
    fx.set_clock(api, CLOCK_BASE)
    importer = fx.create_small_importer(api)
    qi_a = fx.create_qualified_individual(api, importer["id"])
    supplier = fx.create_supplier(api, importer["id"])
    food = fx.create_food(api, importer["id"])
    pair = fx.create_pair(api, importer["id"], supplier["id"], food["id"], qi_a["id"])
    fx.claim_exemption(
        api,
        pair["id"],
        "SMALL_IMPORTER_MODIFIED",
        qi_a["id"],
        basis_note=(
            "Very small importer relying on modified requirements for this combination"
        ),
    )

    data = validate_success(
        api.post_pair_exemption(
            pair["id"],
            f.exemption_determination_payload(
                "VERIFY",
                determination_note=(
                    "Small importer status verified from the filed sales records"
                ),
            ),
            COMPLIANCE_OFFICER_HEADERS,
        )
    )

    # The write's own response body already carries both moved dimensions.
    assert_pair_dimensions(
        data,
        verification_status="DRAFT",
        entry_eligibility_status="ELIGIBLE",
        exemption_status="VERIFIED",
    )
    assert data["modified_requirements_only"] is True, (
        "modified_requirements_only must be true for a verified "
        f"SMALL_IMPORTER_MODIFIED claim, got {data['modified_requirements_only']}"
    )
    assert data["version"] == 3, (
        f"version after create + claim + verify: expected 3, got {data['version']}"
    )

    reread = fx.get_pair(api, pair["id"])
    for field in (
        "verification_status",
        "entry_eligibility_status",
        "exemption_status",
        "modified_requirements_only",
        "version",
    ):
        assert reread[field] == data[field], (
            f"{field} differs between the write response and the immediate re-read: "
            f"{data[field]} vs {reread[field]}"
        )

    importer_row = fx.get_importer(api, importer["id"])
    assert_importer_rollup(
        importer_row, program_status="COMPLIANT", blocked_pair_count=0
    )


def test_records_package_reflects_a_just_attested_record_with_no_lag(api):
    """PRD §2.7: "Consistency in this system is immediate: when a write changes a
    value that another row's specification depends on, the dependent row is updated
    inside the same request, and its own `updated_at` and `version` move
    accordingly."
    PRD §3.9: "its `available_for_inspection` flag is true exactly when the record's
    `record_status` is not `RESCINDED` — that is, when it is `RECEIVED` or
    `ATTESTED` — and the evaluation instant is at or before `retained_until`."
    PRD §3.9: "Every verification record's `retained_until` is its `performed_end`
    advanced by the importer's `record_retention_months` in calendar months"
    PRD §3.4: "The **REALIZED** variant, surfaced as `adequacy_score_realized`,
    takes as its input set the `APPROVED` activities that have at least one
    verification record with `record_status` `ATTESTED`; it is recomputed on record
    attestation and rescission and is reporting-only — it never blocks a write."

    Design: Corner/consistency model/records_package_reflects_a_just_attested_record_with_no_lag
    """
    world = fx.base_program(api)
    analysis = fx.create_hazard_analysis(api, world.pair_id, world.qi_a_id)
    fx.add_hazard(api, analysis["id"], world.qi_a_id, **fx.HAZARD_LISTERIA)
    fx.approve_analysis(api, analysis["id"], world.qi_a_id)
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
    fx.review_activity(api, activity["id"], world.qi_b_id, "APPROVE")
    fx.approve_pair_verification(api, world.pair_id, world.qi_a_id)

    fx.set_clock(api, "2026-10-20T00:00:00Z")
    record = fx.file_record(
        api,
        activity["id"],
        world.qi_a_id,
        outcome="PASS",
        performed_start="2026-10-05T00:00:00Z",
        performed_end="2026-10-06T00:00:00Z",
        findings_count=0,
        document_reference="LAB-2026-1006",
    )
    fx.attest_record(
        api,
        record["id"],
        world.qi_b_id,
        attestation_note="Passing sampling result attested after laboratory confirmation",
    )

    # The very next request must already see the attestation.
    package = validate_success(
        api.get_records_package(world.importer_id, FDA_INSPECTOR_HEADERS)
    )
    assert package["retained_record_count"] == 1, (
        f"retained_record_count: expected 1, got {package['retained_record_count']}"
    )
    assert package["available_for_inspection_count"] == 1, (
        "available_for_inspection_count: expected 1, got "
        f"{package['available_for_inspection_count']}"
    )
    assert package["expired_record_count"] == 0, (
        f"expired_record_count: expected 0, got {package['expired_record_count']}"
    )
    assert package["rescinded_record_count"] == 0, (
        f"rescinded_record_count: expected 0, got {package['rescinded_record_count']}"
    )
    assert package["program_status"] == "COMPLIANT", (
        f"program_status: expected COMPLIANT, got {package['program_status']}"
    )

    stored = fx.get_record(api, record["id"])
    _assert_instant(
        stored["retained_until"], "2028-10-06T00:00:00.000Z", "retained_until"
    )

    pair = fx.get_pair(api, world.pair_id)
    assert float(pair["adequacy_score_realized"]) > 0.00, (
        "adequacy_score_realized must have moved off 0.00 once the activity carries "
        f"an attested record, got {pair['adequacy_score_realized']}"
    )
