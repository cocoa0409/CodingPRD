"""Cyclic review rounds and the easement's two independent state dimensions.

The severance review cycle re-enters SUBMITTED twice before its revision counter
terminates it, and a conservation easement's register dimension advances across a
second certification while its stewardship dimension stays where the violation
finding left it.
"""
import pytest

from test_helpers import (
    ADMIN_USER_ID,
    MONITOR_USER_ID,
    REVIEWER_USER_ID,
    ApiErrorId,
    api_client,
    assert_certificate,
    assert_conservation_easement,
    assert_monitoring_inspection,
    assert_same_date,
    assert_same_instant,
    assert_sending_parcel,
    assert_severance_application,
    certify_application,
    create_active_sending_area,
    create_inspection_payload,
    decide_application,
    enroll_parcel,
    fetch_application,
    fetch_certificate,
    fetch_easement,
    fetch_parcel,
    file_severance,
    make_admin_headers,
    make_monitor_headers,
    make_reviewer_headers,
    register_landowner,
    resubmit_application,
    review_decision_payload,
    screen_application,
    set_clock,
    validate_error,
    validate_success,
)

CLOCK = "2026-08-10T00:00:00Z"
INSPECTION_DATE = "2026-08-10"

# 100.00 gross acres of which 22.00 are constrained, PRIME soil, two existing
# dwellings: a baseline endowment of 22 units under V1_NET_ACRE at 0.25/acre.
PARCEL_GEOMETRY = {
    "gross_acres": 100.00,
    "constrained_acres": 22.00,
    "soil_class": "PRIME",
    "existing_dwelling_units": 2,
}


def _landowner_with_enrolled_parcel():
    """Clock, one landowner, one ACTIVE sending area and one enrolled parcel."""
    set_clock(CLOCK)
    owner = register_landowner(neighborhood_code="NB-EAST")
    area = create_active_sending_area(
        name="East Ridge", neighborhood_code="NB-EAST",
        allocation_formula_version="V1_NET_ACRE", base_rate_units_per_acre=0.25,
        gross_discount_factor=0.80, equity_tier="UNDERSERVED", sending_cap_units=200,
    )
    parcel = enroll_parcel(owner["id"], area["id"], **PARCEL_GEOMETRY)
    return owner, area, parcel


def _application_cycled_to_the_revision_limit():
    """An application taken twice around SUBMITTED -> UNDER_REVIEW ->
    REVISION_REQUESTED -> SUBMITTED, then screened a third time so it sits in
    UNDER_REVIEW with `revision_round` at 2."""
    owner, area, parcel = _landowner_with_enrolled_parcel()
    application = file_severance(parcel["id"], owner["id"], 22)
    screen_application(application["id"], REVIEWER_USER_ID)
    decide_application(
        application["id"], "REQUIRE_REVISION", REVIEWER_USER_ID, decision_note="round 1"
    )
    resubmit_application(application["id"], owner["id"], 18)
    screen_application(application["id"], REVIEWER_USER_ID)
    decide_application(
        application["id"], "REQUIRE_REVISION", REVIEWER_USER_ID, decision_note="round 2"
    )
    resubmit_application(application["id"], owner["id"], 15)
    screen_application(application["id"], REVIEWER_USER_ID)
    return {
        "owner": owner,
        "area": area,
        "parcel": parcel,
        "application": fetch_application(application["id"]),
    }


class TestSeveranceReviewCycleTerminatesOnItsRevisionCounter:
    """Two full revision rounds, then the counter refuses a third."""

    def test_third_revision_request_is_refused_and_leaves_the_application_under_review(self):
        """The counter is the only thing that stops the cycle, and the refusal
        mutates nothing.

        "`REQUIRE_REVISION` moves the application `UNDER_REVIEW →
        REVISION_REQUESTED` and stores the `decision_note`. It is permitted only
        while `revision_round` is below the two-round limit; a third revision
        request is rejected with `ERR_REVISION_LIMIT_EXCEEDED`."
        "The effect moves the application `REVISION_REQUESTED → SUBMITTED`,
        increments `revision_round` by one, replaces `requested_units` with the
        resubmitted value, clears both `screened_by_user_id` and
        `decided_by_user_id` back to unset so that the next screening and decision
        are recorded afresh, and increments the application's `version`. This
        closes the review cycle `SUBMITTED → UNDER_REVIEW → REVISION_REQUESTED →
        SUBMITTED`, and it may run at most twice before the limit bites."

        Design: Difficulty/non_linear_state_machine/severance_review_cycle_exhausts_two_revision_rounds
        """
        scenario = _application_cycled_to_the_revision_limit()
        application = scenario["application"]
        assert_severance_application(application)
        assert application["revision_round"] == 2, (
            "two resubmissions have already run, so the counter stands at its "
            f"limit: got {application['revision_round']}"
        )
        assert application["status"] == "UNDER_REVIEW", application["status"]

        validate_error(
            api_client.review_severance_application(
                application["id"],
                review_decision_payload("REQUIRE_REVISION", decision_note="round 3"),
                make_reviewer_headers(REVIEWER_USER_ID),
            ),
            ApiErrorId.ERR_REVISION_LIMIT_EXCEEDED.value,
        )

        after = fetch_application(application["id"])
        assert after["revision_round"] == 2, (
            f"a refused decision leaves the counter untouched: got {after['revision_round']}"
        )
        assert after["status"] == "UNDER_REVIEW", (
            "the application stays in review rather than cycling again: got "
            f"{after['status']}"
        )

    def test_cycle_exits_forward_through_approve_after_the_limit_bites(self):
        """With the loop closed, APPROVE grants against the restated request.

        "`APPROVE` moves the application `UNDER_REVIEW → APPROVED`, but only when
        the parcel's sending area is still `ACTIVE` and only when the grant
        computation below yields at least one unit. It runs that computation,
        writes `allocated_units` and `residual_units_retained`, and pins
        `applied_formula_version` by copying the area's
        `allocation_formula_version` onto the application, so that a later
        ordinance change cannot restate a grant that has already been decided."
        "Otherwise `allocated_units` is the smallest of three quantities: the
        `requested_units` on the application, the parcel bucket, and the area
        bucket."
        "Finally, `residual_units_retained` is the parcel bucket less
        `allocated_units` — the rights the owner keeps and may sever in a future
        application."
        "`severed_units` is always the sum of `allocated_units` over the parcel's
        severance applications that reached `CERTIFIED`."

        Design: Difficulty/non_linear_state_machine/severance_review_cycle_exhausts_two_revision_rounds
        """
        scenario = _application_cycled_to_the_revision_limit()
        application = scenario["application"]
        validate_error(
            api_client.review_severance_application(
                application["id"],
                review_decision_payload("REQUIRE_REVISION", decision_note="round 3"),
                make_reviewer_headers(REVIEWER_USER_ID),
            ),
            ApiErrorId.ERR_REVISION_LIMIT_EXCEEDED.value,
        )

        approved = validate_success(
            api_client.review_severance_application(
                application["id"],
                review_decision_payload("APPROVE"),
                make_reviewer_headers(REVIEWER_USER_ID),
            )
        )
        assert_severance_application(approved)
        assert approved["status"] == "APPROVED", (
            f"the cycle exits forward rather than looping: got {approved['status']}"
        )
        assert approved["allocated_units"] == 15, (
            "the smallest of the 15 units restated on the last resubmission, the "
            "parcel's 22 remaining units and the area's 200 unit bucket: got "
            f"{approved['allocated_units']}"
        )
        assert approved["residual_units_retained"] == 7, (
            "the 22-unit parcel bucket less the 15 units granted: got "
            f"{approved['residual_units_retained']}"
        )
        assert approved["applied_formula_version"] == "V1_NET_ACRE", (
            "the decision pins the area's adopted formula: got "
            f"{approved['applied_formula_version']}"
        )
        parcel = fetch_parcel(scenario["parcel"]["id"])
        assert_sending_parcel(parcel)
        assert parcel["severed_units"] == 0, (
            "approval alone severs nothing, because only a CERTIFIED application "
            f"contributes to severed_units: got {parcel['severed_units']}"
        )


def _first_severance_certified(units=10):
    """One certified severance: a RECORDED, COMPLIANT easement plus its root
    certificate."""
    owner, area, parcel = _landowner_with_enrolled_parcel()
    application = file_severance(parcel["id"], owner["id"], units)
    screen_application(application["id"], REVIEWER_USER_ID)
    decide_application(application["id"], "APPROVE", REVIEWER_USER_ID)
    certificate = certify_application(application["id"], ADMIN_USER_ID)
    easement = fetch_easement(certificate["conservation_easement_id"])
    return {
        "owner": owner,
        "area": area,
        "parcel": fetch_parcel(parcel["id"]),
        "application": fetch_application(application["id"]),
        "certificate": certificate,
        "easement": easement,
    }


def _notice_major_violation(easement_id, affected_acres=12.00):
    """A MAJOR_VIOLATION inspection on the recorded easement."""
    return validate_success(
        api_client.create_inspection(
            easement_id,
            create_inspection_payload(
                INSPECTION_DATE, finding="MAJOR_VIOLATION", affected_acres=affected_acres
            ),
            make_monitor_headers(MONITOR_USER_ID),
        ),
        201,
    )


def _certify_a_second_severance(parcel_id, owner_id, units=12):
    """A second grant certified against the same parcel, amending its easement."""
    application = file_severance(parcel_id, owner_id, units)
    screen_application(application["id"], REVIEWER_USER_ID)
    decide_application(application["id"], "APPROVE", REVIEWER_USER_ID)
    return validate_success(
        api_client.certify_severance_application(
            application["id"], make_admin_headers(ADMIN_USER_ID)
        ),
        201,
    )


class TestEasementRecordingAndComplianceDimensionsAdvanceIndependently:
    """A violation moves stewardship only; a second certification moves the
    register only."""

    def test_violation_finding_moves_only_the_stewardship_dimension(self):
        """The register stays RECORDED while compliance, severity and the freeze
        cascade all move.

        "A `ConservationEasement` has a register dimension, `recording_status`,
        which moves among `PENDING_RECORDING`, `RECORDED` and `AMENDED`, and a
        stewardship dimension, `compliance_status`, which moves among `COMPLIANT`,
        `VIOLATION_NOTICED`, `UNDER_CURE`, `CURED` and `ESCALATED`. Neither
        dimension constrains the other's value: an `AMENDED` easement can be
        `ESCALATED`, and a `RECORDED` easement can be `CURED`."
        "A finding of `MINOR_VIOLATION` or `MAJOR_VIOLATION` opens the inspection
        in `CURE_PENDING` and is scored from three weighted components. The finding
        component contributes 0 for `COMPLIANT`, 40 for `MINOR_VIOLATION`, and 90
        for `MAJOR_VIOLATION`, at a weight of one half. The extent component is an
        acre ratio — `affected_acres` divided by the easement's `restricted_acres`,
        capped at 1 so that damage beyond the restricted area cannot push the ratio
        past whole — expressed as a percentage and taken at a weight of three
        tenths. The history component is the easement's `prior_violation_count`
        multiplied by 25 and capped at 100, taken at a weight of two tenths; the
        count is read as it stands before this inspection increments it, so a
        landowner's first violation carries no history term. `severity_score` is
        the weighted sum rounded half up to two decimal places, with the rounding
        applied once to the sum and never to individual terms."
        "The rounded score selects a cure band, and the bands are inclusive on
        their lower edge: a score of at least 70.00 gives 30 days, a score of at
        least 45.00 but below 70.00 gives 60 days, and anything lower gives 90
        days."
        "`cure_deadline` is `inspection_date` advanced by the band's day count, and
        the same deadline is copied onto the easement."
        "A violation finding moves the easement `COMPLIANT → VIOLATION_NOTICED`, or
        `CURED → VIOLATION_NOTICED` for a repeat offender, and sets its
        `cure_deadline`."
        "First the easement's `compliance_status` changes and its
        `prior_violation_count` increments. Second — caused by the first — every
        certificate whose `conservation_easement_id` names this easement and whose
        `market_status` is `HELD` or `UNDER_CONTRACT` moves to `FROZEN`, and any
        market transaction on such a certificate that is still `PROPOSED` moves
        `PROPOSED → CANCELLED` with `reversal_reason` set to the literal
        `EASEMENT_NONCOMPLIANT`."

        Design: Difficulty/non_linear_state_machine/easement_recording_and_compliance_dimensions_advance_independently
        """
        scenario = _first_severance_certified(units=10)
        before = scenario["easement"]
        assert_conservation_easement(before)
        assert before["recording_status"] == "RECORDED", before["recording_status"]
        assert before["compliance_status"] == "COMPLIANT", before["compliance_status"]
        assert float(before["restricted_acres"]) == pytest.approx(45.45, abs=0.01), (
            "100.00 gross acres times 10 severed units over a 22-unit baseline: got "
            f"{before['restricted_acres']}"
        )

        inspection = _notice_major_violation(before["id"], affected_acres=12.00)
        assert_monitoring_inspection(inspection)
        assert inspection["status"] == "CURE_PENDING", (
            f"a MAJOR_VIOLATION opens in CURE_PENDING: got {inspection['status']}"
        )
        assert float(inspection["severity_score"]) == pytest.approx(52.92, abs=0.01), (
            "0.5 x 90 plus 0.3 x (12.00 / 45.45 as a percentage) plus 0.2 x 0, "
            f"rounded half up once: got {inspection['severity_score']}"
        )
        assert_same_date(
            inspection["cure_deadline"], "2026-10-09",
            "a score in the 45.00-to-70.00 band gives 60 days from 2026-08-10",
        )

        after = fetch_easement(before["id"])
        assert after["recording_status"] == "RECORDED", (
            "the register dimension is untouched by a stewardship event: got "
            f"{after['recording_status']}"
        )
        assert after["compliance_status"] == "VIOLATION_NOTICED", (
            f"the stewardship dimension moves: got {after['compliance_status']}"
        )
        assert after["prior_violation_count"] == 1, (
            f"the violation count increments once: got {after['prior_violation_count']}"
        )
        assert_same_date(
            after["cure_deadline"], "2026-10-09", "the deadline is copied onto the easement"
        )
        assert after["amendment_count"] == 0, (
            f"no amendment has occurred: got {after['amendment_count']}"
        )

        frozen = fetch_certificate(scenario["certificate"]["id"])
        assert_certificate(frozen)
        assert frozen["market_status"] == "FROZEN", (
            "the HELD certificate on the noncompliant easement freezes: got "
            f"{frozen['market_status']}"
        )
        assert frozen["lifecycle_status"] == "ISSUED", (
            "the freeze touches only the tradability dimension: got "
            f"{frozen['lifecycle_status']}"
        )

    def test_second_certification_moves_only_the_register_dimension(self):
        """The easement amends on the register while its stewardship dimension
        stays exactly where the violation left it.

        "If the parcel already has an easement — because rights were severed from
        it before — that existing easement instead takes a `RECORDED → AMENDED`
        transition, its `amendment_count` is incremented by one, and its
        `recording_reference` is re-minted as `EAS-`, the parcel's `apn`, a hyphen,
        and `amendment_count` plus one evaluated after the increment."
        "`recorded_at` is written once at the original recording and is never
        rewritten by an amendment, and `severance_application_id` likewise
        continues to name the application that first created the easement."
        "Neither dimension constrains the other's value: an `AMENDED` easement can
        be `ESCALATED`, and a `RECORDED` easement can be `CURED`."

        Design: Difficulty/non_linear_state_machine/easement_recording_and_compliance_dimensions_advance_independently
        """
        scenario = _first_severance_certified(units=10)
        easement_id = scenario["easement"]["id"]
        parcel = scenario["parcel"]
        _notice_major_violation(easement_id, affected_acres=12.00)

        _certify_a_second_severance(parcel["id"], scenario["owner"]["id"], units=12)

        amended = fetch_easement(easement_id)
        assert_conservation_easement(amended)
        assert amended["recording_status"] == "AMENDED", (
            "the second certification amends the register entry: got "
            f"{amended['recording_status']}"
        )
        assert amended["amendment_count"] == 1, (
            f"one amendment has been recorded: got {amended['amendment_count']}"
        )
        assert amended["recording_reference"] == f"EAS-{parcel['apn']}-2", (
            "the reference is re-minted from the incremented amendment count: got "
            f"{amended['recording_reference']}"
        )
        assert amended["compliance_status"] == "VIOLATION_NOTICED", (
            "an amendment on the register cannot clear a noticed violation: got "
            f"{amended['compliance_status']}"
        )
        assert amended["prior_violation_count"] == 1, (
            "the stewardship counters are untouched by the amendment: got "
            f"{amended['prior_violation_count']}"
        )
        assert amended["severance_application_id"] == scenario["application"]["id"], (
            "the easement keeps naming the application that first created it: got "
            f"{amended['severance_application_id']}"
        )
        assert_same_instant(
            amended["recorded_at"], scenario["easement"]["recorded_at"],
            "recorded_at survives the amendment",
        )

    def test_amendment_recomputes_the_restriction_cumulatively(self):
        """The amended easement re-measures the whole restriction from the parcel's
        cumulative severed count, and the second certificate is a fresh root.

        "The easement's `restricted_acres` is recomputed as the parcel's
        `gross_acres` multiplied by the cumulative severed unit count and divided
        by the parcel's `baseline_allocation_units`, rounded half up to two decimal
        places, where the cumulative severed count is the parcel's `severed_units`
        before this certification plus the `allocated_units` now being certified."
        "The easement's `permitted_residual_units` — the buildable envelope left on
        the preserved parcel — is recomputed as the parcel's
        `existing_dwelling_units` plus the parcel's `baseline_allocation_units` less
        that same cumulative severed count."
        "The easement's `units_issued_total` grows by `allocated_units` and its
        `units_outstanding` is recomputed accordingly."
        "On the parcel itself, `easement_status` becomes `RECORDED`,
        `restricted_acres` is set to match the easement's figure, `severed_units`
        grows by `allocated_units`, `remaining_units` is reduced by the same amount,
        and `parcel_status` becomes `PARTIALLY_SEVERED` when `remaining_units` is
        still above zero or `FULLY_SEVERED` when it has reached zero."
        "For any single easement, `units_issued_total` equals
        `units_redeemed_confirmed` plus `units_retired` plus `units_outstanding` —
        equivalently, `units_outstanding` is the total face value of the root
        issuances backed by that easement, less everything redeemed and everything
        retired across the easement's entire certificate lineage including every
        split child."
        "Its `units_face` and `units_remaining` both equal `allocated_units`;
        `holder_party_id` is the application's `applicant_party_id`;
        `conservation_easement_id` is the easement from link one;
        `origin_sending_area_id` is the parcel's `sending_area_id`;
        `origin_neighborhood_code` is a copy of that area's `neighborhood_code`,
        taken at issuance so the certificate keeps pointing at the right appraisal
        schedule even if the area is later re-coded; `parent_certificate_id` is
        unset because this is a root; `generation` is 1; `split_count` is 0;
        `units_split_out`, `units_encumbered`, `units_redeemed`, and `units_retired`
        are all 0; `lifecycle_status` is `ISSUED`; `market_status` is `HELD`; and
        `issued_at` is the current logical clock."

        Design: Difficulty/non_linear_state_machine/easement_recording_and_compliance_dimensions_advance_independently
        """
        scenario = _first_severance_certified(units=10)
        easement_id = scenario["easement"]["id"]
        parcel = scenario["parcel"]
        assert parcel["parcel_status"] == "PARTIALLY_SEVERED", parcel["parcel_status"]
        _notice_major_violation(easement_id, affected_acres=12.00)

        second_certificate = _certify_a_second_severance(
            parcel["id"], scenario["owner"]["id"], units=12
        )

        amended = fetch_easement(easement_id)
        assert float(amended["restricted_acres"]) == pytest.approx(100.00, abs=0.01), (
            "100.00 gross acres times the cumulative 22 severed units over the "
            f"22-unit baseline: got {amended['restricted_acres']}"
        )
        assert amended["permitted_residual_units"] == 2, (
            "2 existing dwellings plus a 22-unit baseline less 22 cumulative severed "
            f"units: got {amended['permitted_residual_units']}"
        )
        assert amended["units_issued_total"] == 22, (
            f"10 units then 12 more: got {amended['units_issued_total']}"
        )
        assert amended["units_redeemed_confirmed"] == 0, amended["units_redeemed_confirmed"]
        assert amended["units_retired"] == 0, amended["units_retired"]
        assert amended["units_outstanding"] == 22, (
            "nothing has been redeemed or retired, so the whole issuance is "
            f"outstanding: got {amended['units_outstanding']}"
        )

        settled_parcel = fetch_parcel(parcel["id"])
        assert_sending_parcel(settled_parcel)
        assert settled_parcel["severed_units"] == 22, settled_parcel["severed_units"]
        assert settled_parcel["remaining_units"] == 0, settled_parcel["remaining_units"]
        assert settled_parcel["parcel_status"] == "FULLY_SEVERED", (
            "the baseline is exhausted, so the parcel is fully severed: got "
            f"{settled_parcel['parcel_status']}"
        )
        assert settled_parcel["easement_status"] == "RECORDED", (
            f"the parcel still points at a recorded easement: got "
            f"{settled_parcel['easement_status']}"
        )
        assert float(settled_parcel["restricted_acres"]) == pytest.approx(100.00, abs=0.01), (
            f"the parcel mirrors the easement's figure: got {settled_parcel['restricted_acres']}"
        )

        assert_certificate(second_certificate)
        assert second_certificate["units_face"] == 12, second_certificate["units_face"]
        assert second_certificate["units_remaining"] == 12, second_certificate["units_remaining"]
        assert second_certificate["generation"] == 1, (
            "the second certification mints another root, not a split child: got "
            f"{second_certificate['generation']}"
        )
        assert second_certificate["parent_certificate_id"] is None, (
            f"a root has no parent: got {second_certificate['parent_certificate_id']}"
        )
        assert second_certificate["conservation_easement_id"] == easement_id, (
            "both certificates are backed by the parcel's single easement: got "
            f"{second_certificate['conservation_easement_id']}"
        )
        assert second_certificate["holder_party_id"] == scenario["owner"]["id"], (
            f"the applicant holds it: got {second_certificate['holder_party_id']}"
        )
        assert second_certificate["lifecycle_status"] == "ISSUED", (
            f"a freshly minted certificate carries live rights: got "
            f"{second_certificate['lifecycle_status']}"
        )
