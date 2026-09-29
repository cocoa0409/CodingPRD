"""Transitive cascades on the Transfer of Development Rights registry.

Two independent four-link chains are exercised here.  The first is driven by a
severance certification: recording the conservation easement forces the parcel
recompute, the parcel recompute forces the sending area's `severed_units_total`
recompute, and only that recomputed total crossing the ordinance cap closes the
area and suspends an unrelated sibling application.  The second is driven by a
monitoring inspection: the easement's compliance move freezes its certificates,
the freeze holds their redemptions, and only the held redemptions leaving
`pending_backed_units` pushes a fully backed receiving-site application into
`BACKING_DEFICIENT`.

Every test builds its own registry state from scratch through the API.
"""
import pytest

from test_helpers import (
    ADMIN_USER_ID,
    ApiErrorId,
    MONITOR_USER_ID,
    REVIEWER_USER_ID,
    api_client,
    assert_certificate,
    assert_certificate_units_conserved,
    assert_conservation_easement,
    assert_same_date,
    assert_same_instant,
    assert_sending_parcel,
    create_active_sending_area,
    certify_application,
    decide_application,
    design_decision,
    enroll_parcel,
    fetch_application,
    fetch_certificate,
    fetch_easement,
    fetch_parcel,
    fetch_receiving_area,
    fetch_receiving_site_application,
    fetch_redemption,
    fetch_sending_area,
    file_severance,
    make_developer_headers,
    record_inspection,
    register_landowner,
    screen_application,
    set_clock,
    setup_backed_receiving_application,
    validate_error,
)

CLOCK = "2026-08-10T00:00:00Z"

# The tight-cap area's ordinance cap equals, to the unit, what the first
# certification severs, so link three's recomputed total lands exactly on it.
TIGHT_AREA_CODE = "SA-TIGHT"
TIGHT_CAP_UNITS = 22
PARCEL_A_APN = "APN-A01"
PARCEL_B_APN = "APN-B01"


def _tight_cap_certification_scenario() -> dict:
    """Landowner, one ACTIVE sending area capped at 22 units, two parcels in it,
    an APPROVED 22-unit application on parcel A and an untouched SUBMITTED
    10-unit application on parcel B.

    Parcel A's geometry yields a 22-unit baseline: (100.00 - 22.00) net acres at
    0.25 units/acre times the PRIME multiplier 1.25 is 24.375, floored to 24,
    less its 2 existing dwelling units.  Parcel B's yields 10: 40.00 acres at
    0.25 units/acre times the LOCAL multiplier 1.00, floored, with no dwellings.
    """
    set_clock(CLOCK)
    landowner = register_landowner(neighborhood_code="NB-EAST")
    area = create_active_sending_area(
        code=TIGHT_AREA_CODE,
        name="Tight Cap Area",
        neighborhood_code="NB-EAST",
        allocation_formula_version="V1_NET_ACRE",
        base_rate_units_per_acre=0.25,
        gross_discount_factor=0.80,
        equity_tier="UNDERSERVED",
        sending_cap_units=TIGHT_CAP_UNITS,
    )
    parcel_a = enroll_parcel(
        landowner["id"], area["id"], apn=PARCEL_A_APN,
        gross_acres=100.00, constrained_acres=22.00,
        soil_class="PRIME", existing_dwelling_units=2,
    )
    parcel_b = enroll_parcel(
        landowner["id"], area["id"], apn=PARCEL_B_APN,
        gross_acres=40.00, constrained_acres=0.00,
        soil_class="LOCAL", existing_dwelling_units=0,
    )
    assert parcel_a["baseline_allocation_units"] == 22, (
        "setup expects a 22-unit baseline on parcel A, got "
        f"{parcel_a['baseline_allocation_units']}"
    )
    assert parcel_b["baseline_allocation_units"] == 10, (
        "setup expects a 10-unit baseline on parcel B, got "
        f"{parcel_b['baseline_allocation_units']}"
    )

    application_b = file_severance(parcel_b["id"], landowner["id"], 10)
    application_a = file_severance(parcel_a["id"], landowner["id"], 22)
    screen_application(application_a["id"], REVIEWER_USER_ID)
    application_a = decide_application(application_a["id"], "APPROVE", REVIEWER_USER_ID)
    assert application_a["allocated_units"] == 22, (
        f"setup expects a 22-unit grant, got {application_a['allocated_units']}"
    )
    return {
        "landowner": landowner,
        "area": area,
        "parcel_a": parcel_a,
        "parcel_b": parcel_b,
        "application_a": application_a,
        "application_b": application_b,
    }


class TestCertificationCascadeToAreaClosure:
    """Certifying a severance whose grant lands exactly on the sending cap."""

    def test_certification_records_easement_and_encumbers_the_parcel(self):
        """Links one and two: the register entry is minted and recorded, and the
        encumbrance it causes rewrites both the easement's and the parcel's ledgers.

        PRD §3.5: "That easement is born in `recording_status` `PENDING_RECORDING` and immediately advanced `PENDING_RECORDING → RECORDED` within the same request: `recorded_at` is set to the current logical clock and `recording_reference` is minted deterministically as `EAS-` followed by the parcel's `apn`, a hyphen, and the number 1."
        PRD §3.5: "The easement's `restricted_acres` is recomputed as the parcel's `gross_acres` multiplied by the cumulative severed unit count and divided by the parcel's `baseline_allocation_units`, rounded half up to two decimal places, where the cumulative severed count is the parcel's `severed_units` before this certification plus the `allocated_units` now being certified."
        PRD §3.5: "The easement's `permitted_residual_units` — the buildable envelope left on the preserved parcel — is recomputed as the parcel's `existing_dwelling_units` plus the parcel's `baseline_allocation_units` less that same cumulative severed count."
        PRD §3.5: "The easement's `units_issued_total` grows by `allocated_units` and its `units_outstanding` is recomputed accordingly."
        PRD §3.5: "On the parcel itself, `easement_status` becomes `RECORDED`, `restricted_acres` is set to match the easement's figure, `severed_units` grows by `allocated_units`, `remaining_units` is reduced by the same amount, and `parcel_status` becomes `PARTIALLY_SEVERED` when `remaining_units` is still above zero or `FULLY_SEVERED` when it has reached zero."

        Design: Difficulty/transitive_cascade/certification_cascades_parcel_to_area_closure_to_sibling_suspension
        """
        scenario = _tight_cap_certification_scenario()

        certificate = certify_application(scenario["application_a"]["id"], ADMIN_USER_ID)

        easement = fetch_easement(certificate["conservation_easement_id"])
        assert_conservation_easement(easement)
        assert easement["recording_status"] == "RECORDED", (
            f"link 1: easement must be RECORDED, got {easement['recording_status']}"
        )
        assert easement["recording_reference"] == f"EAS-{PARCEL_A_APN}-1", (
            "link 1: recording_reference must be EAS- plus the apn plus -1, got "
            f"{easement['recording_reference']}"
        )
        assert_same_instant(easement["recorded_at"], CLOCK, "ConservationEasement.recorded_at")

        assert easement["restricted_acres"] == pytest.approx(100.00, abs=0.01), (
            "link 2: 100.00 gross acres times 22 of 22 baseline units must encumber "
            f"the whole parcel, got {easement['restricted_acres']}"
        )
        assert easement["permitted_residual_units"] == 2, (
            "link 2: permitted_residual_units must be 2 + 22 - 22, got "
            f"{easement['permitted_residual_units']}"
        )
        assert easement["units_issued_total"] == 22, (
            f"link 2: units_issued_total must be 22, got {easement['units_issued_total']}"
        )

        parcel = fetch_parcel(scenario["parcel_a"]["id"])
        assert_sending_parcel(parcel)
        assert parcel["severed_units"] == 22, (
            f"link 2: parcel severed_units must be 22, got {parcel['severed_units']}"
        )
        assert parcel["remaining_units"] == 0, (
            f"link 2: parcel remaining_units must be 0, got {parcel['remaining_units']}"
        )
        assert parcel["restricted_acres"] == pytest.approx(100.00, abs=0.01), (
            "link 2: the parcel's restricted_acres must match the easement's figure, got "
            f"{parcel['restricted_acres']}"
        )
        assert parcel["easement_status"] == "RECORDED", (
            f"link 2: parcel easement_status must be RECORDED, got {parcel['easement_status']}"
        )
        assert parcel["parcel_status"] == "FULLY_SEVERED", (
            "link 2: a parcel whose remaining_units reached zero must be FULLY_SEVERED, got "
            f"{parcel['parcel_status']}"
        )

    def test_certification_closes_the_area_at_the_exact_cap_and_suspends_the_sibling(self):
        """Links three and four: the area's recomputed total closes it on an
        inclusive comparison, and only that closure suspends the untouched sibling
        application filed against a different parcel in the same area.

        PRD §3.5: "The sending area's `severed_units_total` is recomputed as the sum of `allocated_units` over every `CERTIFIED` application on parcels in the area, and its `issued_certificate_count` is incremented by one."
        PRD §3.5: "When the recomputed `severed_units_total` is at least the area's `sending_cap_units`, the area takes its `ACTIVE → CLOSED` transition. The comparison is inclusive: reaching the cap exactly closes the area. Closing runs the same suspension cascade described in §3.2 — every `SUBMITTED`, `UNDER_REVIEW`, or `REVISION_REQUESTED` application on the area's parcels moves to `SUSPENDED` with `denial_reason` of `SENDING_AREA_CLOSED`, and the area's `version` plus the `version` of every suspended application are each incremented by one."

        Design: Difficulty/transitive_cascade/certification_cascades_parcel_to_area_closure_to_sibling_suspension
        """
        scenario = _tight_cap_certification_scenario()
        area_version_before = fetch_sending_area(scenario["area"]["id"])["version"]
        sibling_version_before = fetch_application(scenario["application_b"]["id"])["version"]

        certify_application(scenario["application_a"]["id"], ADMIN_USER_ID)

        area = fetch_sending_area(scenario["area"]["id"])
        assert area["severed_units_total"] == 22, (
            f"link 3: severed_units_total must be 22, got {area['severed_units_total']}"
        )
        assert area["issued_certificate_count"] == 1, (
            "link 3: issued_certificate_count must be incremented to 1, got "
            f"{area['issued_certificate_count']}"
        )
        assert area["status"] == "CLOSED", (
            "link 4: 22 severed against a cap of 22 must close the area on an inclusive "
            f"comparison, got {area['status']}"
        )
        assert area["version"] > area_version_before, (
            "link 4: closing the area must increment its version, "
            f"{area_version_before} -> {area['version']}"
        )

        sibling = fetch_application(scenario["application_b"]["id"])
        assert sibling["status"] == "SUSPENDED", (
            "link 4: the SUBMITTED sibling application must be suspended by the closure, got "
            f"{sibling['status']}"
        )
        assert sibling["denial_reason"] == "SENDING_AREA_CLOSED", (
            "link 4: the suspended application's denial_reason must be SENDING_AREA_CLOSED, got "
            f"{sibling['denial_reason']}"
        )
        assert sibling["version"] > sibling_version_before, (
            "link 4: the suspended application's version must be incremented, "
            f"{sibling_version_before} -> {sibling['version']}"
        )

    def test_certification_issues_the_serialized_certificate_and_spares_the_sibling_parcel(self):
        """The mint that rides alongside the cascade, and the sibling parcel's own
        ledger, which the closure never touches.

        PRD §3.5: "Its `units_face` and `units_remaining` both equal `allocated_units`; `holder_party_id` is the application's `applicant_party_id`; `conservation_easement_id` is the easement from link one; `origin_sending_area_id` is the parcel's `sending_area_id`; `origin_neighborhood_code` is a copy of that area's `neighborhood_code`, taken at issuance so the certificate keeps pointing at the right appraisal schedule even if the area is later re-coded; `parent_certificate_id` is unset because this is a root; `generation` is 1; `split_count` is 0; `units_split_out`, `units_encumbered`, `units_redeemed`, and `units_retired` are all 0; `lifecycle_status` is `ISSUED`; `market_status` is `HELD`; and `issued_at` is the current logical clock."
        PRD §3.5: "`serial_number` is minted deterministically as `TDR-`, the area's `code`, a hyphen, and the area's `issued_certificate_count` after its increment rendered as five digits with leading zeros — so the first certificate out of an area coded `SND-01` is `TDR-SND-01-00001`."
        PRD §3.5: "The request then moves the application `APPROVED → CERTIFIED`, writes the acting `X-User-ID` into `certified_by_user_id`, increments the application's `version`, and runs a four-link cascade in order."
        PRD §3.3: "`remaining_units` is always `baseline_allocation_units` less `severed_units`, and `severed_units` is always the sum of `allocated_units` over the parcel's severance applications that reached `CERTIFIED`."
        PRD §3.3: "On enrollment the derived ledger fields open at their starting values: `remaining_units` equals `baseline_allocation_units`, `severed_units` is 0, `restricted_acres` is 0, `easement_status` is `NONE`, and `parcel_status` is `UNSEVERED`."

        Design: Difficulty/transitive_cascade/certification_cascades_parcel_to_area_closure_to_sibling_suspension
        """
        scenario = _tight_cap_certification_scenario()

        certificate = certify_application(scenario["application_a"]["id"], ADMIN_USER_ID)
        assert_certificate(certificate)
        assert certificate["units_face"] == 22, (
            f"units_face must equal the 22 allocated units, got {certificate['units_face']}"
        )
        assert certificate["units_remaining"] == 22, (
            f"units_remaining must equal the 22 allocated units, got {certificate['units_remaining']}"
        )
        assert certificate["serial_number"] == f"TDR-{TIGHT_AREA_CODE}-00001", (
            "the first certificate out of the area must be serialized "
            f"TDR-{TIGHT_AREA_CODE}-00001, got {certificate['serial_number']}"
        )
        assert certificate["holder_party_id"] == scenario["landowner"]["id"], (
            "the certificate must be held by the applicant party"
        )
        assert certificate["lifecycle_status"] == "ISSUED", certificate["lifecycle_status"]
        assert certificate["market_status"] == "HELD", certificate["market_status"]
        assert_same_instant(certificate["issued_at"], CLOCK, "Certificate.issued_at")

        application = fetch_application(scenario["application_a"]["id"])
        assert application["status"] == "CERTIFIED", (
            f"the certified application must be CERTIFIED, got {application['status']}"
        )
        assert application["certified_by_user_id"] == ADMIN_USER_ID, (
            "certified_by_user_id must record the acting administrator, got "
            f"{application['certified_by_user_id']}"
        )

        sibling_parcel = fetch_parcel(scenario["parcel_b"]["id"])
        assert sibling_parcel["severed_units"] == 0, (
            "the sibling parcel has no CERTIFIED application, so severed_units stays 0, got "
            f"{sibling_parcel['severed_units']}"
        )
        assert sibling_parcel["remaining_units"] == 10, (
            "the sibling parcel keeps its whole 10-unit baseline, got "
            f"{sibling_parcel['remaining_units']}"
        )
        assert sibling_parcel["parcel_status"] == "UNSEVERED", (
            "the sibling parcel never severed anything, so it keeps its enrollment "
            f"parcel_status of UNSEVERED, got {sibling_parcel['parcel_status']}"
        )


# The freeze chain's fixed inputs: a 22-unit certificate off a parcel whose
# easement restricts 100.00 acres, backing a 12.00-acre receiving site.
INSPECTION_DATE = "2026-08-10"
AFFECTED_ACRES = 12.00
EXPECTED_SEVERITY_SCORE = 48.60
EXPECTED_CURE_DEADLINE = "2026-10-09"
BACKING_UNITS = 16


def _design_approved_backed_application() -> dict:
    """A developer holding a settled 22-unit certificate, a DESIGN_APPROVED
    receiving-site application on 12.00 acres requesting 20 bonus units, and a
    16-unit redemption backing it in full.

    12.00 acres takes the 1.00 site tier factor, so `base_units` is 48 and
    `max_bonus_units` is floor(48 x 0.35 x 1.00) = 16, which is also
    `required_backing_units` because 16 is the lesser of it and the 20 requested.
    """
    scenario = setup_backed_receiving_application(
        backing_units=BACKING_UNITS,
        site_acres=12.00,
        requested_bonus_units=20,
        absorption_cap_units=500,
        design_review_required=True,
    )
    design_decision(scenario["rsa"]["id"], "APPROVE")
    rsa = fetch_receiving_site_application(scenario["rsa"]["id"])
    assert rsa["base_units"] == 48, f"setup expects base_units 48, got {rsa['base_units']}"
    assert rsa["max_bonus_units"] == 16, (
        f"setup expects max_bonus_units 16, got {rsa['max_bonus_units']}"
    )
    assert rsa["required_backing_units"] == 16, (
        f"setup expects required_backing_units 16, got {rsa['required_backing_units']}"
    )
    assert rsa["status"] == "DESIGN_APPROVED", (
        f"setup expects a DESIGN_APPROVED application, got {rsa['status']}"
    )
    assert rsa["pending_backed_units"] == BACKING_UNITS, (
        f"setup expects 16 pending backed units, got {rsa['pending_backed_units']}"
    )
    scenario["rsa"] = rsa
    return scenario


class TestViolationFreezeCascadeToBackingDeficient:
    """One monitoring inspection, four linked levels of consequence."""

    def test_violation_finding_scores_severity_and_notices_the_easement(self):
        """The trigger itself: the weighted severity score, the cure band it
        selects, and link one — the easement's own compliance move.

        PRD §3.9: "A finding of `MINOR_VIOLATION` or `MAJOR_VIOLATION` opens the inspection in `CURE_PENDING` and is scored from three weighted components. The finding component contributes 0 for `COMPLIANT`, 40 for `MINOR_VIOLATION`, and 90 for `MAJOR_VIOLATION`, at a weight of one half. The extent component is an acre ratio — `affected_acres` divided by the easement's `restricted_acres`, capped at 1 so that damage beyond the restricted area cannot push the ratio past whole — expressed as a percentage and taken at a weight of three tenths. The history component is the easement's `prior_violation_count` multiplied by 25 and capped at 100, taken at a weight of two tenths; the count is read as it stands before this inspection increments it, so a landowner's first violation carries no history term. `severity_score` is the weighted sum rounded half up to two decimal places, with the rounding applied once to the sum and never to individual terms."
        PRD §3.9: "The rounded score selects a cure band, and the bands are inclusive on their lower edge: a score of at least 70.00 gives 30 days, a score of at least 45.00 but below 70.00 gives 60 days, and anything lower gives 90 days."
        PRD §3.9: "`cure_deadline` is `inspection_date` advanced by the band's day count, and the same deadline is copied onto the easement."
        PRD §3.9: "A violation finding moves the easement `COMPLIANT → VIOLATION_NOTICED`, or `CURED → VIOLATION_NOTICED` for a repeat offender, and sets its `cure_deadline`."
        PRD §3.9: "First the easement's `compliance_status` changes and its `prior_violation_count` increments."

        Design: Difficulty/transitive_cascade/inspection_cascades_easement_freeze_to_backing_deficient_application
        """
        scenario = _design_approved_backed_application()

        inspection = record_inspection(
            scenario["easement"]["id"], INSPECTION_DATE, "MAJOR_VIOLATION",
            AFFECTED_ACRES, MONITOR_USER_ID,
        )

        assert inspection["severity_score"] == pytest.approx(EXPECTED_SEVERITY_SCORE, abs=0.01), (
            "90 x 0.5 plus (12.00/100.00 as a percentage) x 0.3 plus 0 x 0.2 is 48.60, got "
            f"{inspection['severity_score']}"
        )
        assert inspection["status"] == "CURE_PENDING", (
            f"a MAJOR_VIOLATION opens the inspection in CURE_PENDING, got {inspection['status']}"
        )
        assert_same_date(
            inspection["cure_deadline"], EXPECTED_CURE_DEADLINE,
            "MonitoringInspection.cure_deadline",
        )

        easement = fetch_easement(scenario["easement"]["id"])
        assert_conservation_easement(easement)
        assert easement["compliance_status"] == "VIOLATION_NOTICED", (
            "link 1: the easement must move COMPLIANT -> VIOLATION_NOTICED, got "
            f"{easement['compliance_status']}"
        )
        assert easement["prior_violation_count"] == 1, (
            f"link 1: prior_violation_count must increment to 1, got {easement['prior_violation_count']}"
        )
        assert_same_date(
            easement["cure_deadline"], EXPECTED_CURE_DEADLINE,
            "ConservationEasement.cure_deadline",
        )

    def test_notice_freezes_the_certificate_and_holds_its_redemption(self):
        """Links two and three: the certificate's tradability dimension flips to
        FROZEN, and the redemption drawn on it leaves ALLOCATED while its units stay
        committed inside the certificate and the receiving area's reserve.

        PRD §3.9: "Second — caused by the first — every certificate whose `conservation_easement_id` names this easement and whose `market_status` is `HELD` or `UNDER_CONTRACT` moves to `FROZEN`, and any market transaction on such a certificate that is still `PROPOSED` moves `PROPOSED → CANCELLED` with `reversal_reason` set to the literal `EASEMENT_NONCOMPLIANT`."
        PRD §3.9: "Third — caused by the second — every redemption in `ALLOCATED` on a just-frozen certificate moves `ALLOCATED → HELD_PENDING_COMPLIANCE`; its units stay inside the certificate's `units_encumbered` and the area's `reserved_units`, but they leave the application's `pending_backed_units`, because held backing no longer counts as backing."

        Design: Difficulty/transitive_cascade/inspection_cascades_easement_freeze_to_backing_deficient_application
        """
        scenario = _design_approved_backed_application()

        record_inspection(
            scenario["easement"]["id"], INSPECTION_DATE, "MAJOR_VIOLATION",
            AFFECTED_ACRES, MONITOR_USER_ID,
        )

        certificate = fetch_certificate(scenario["certificate"]["id"])
        assert_certificate_units_conserved(certificate)
        assert certificate["market_status"] == "FROZEN", (
            "link 2: a certificate on a noticed easement must be FROZEN, got "
            f"{certificate['market_status']}"
        )
        assert certificate["units_encumbered"] == BACKING_UNITS, (
            "link 2: the freeze does not release the encumbrance, so units_encumbered stays "
            f"at 16, got {certificate['units_encumbered']}"
        )

        redemption = fetch_redemption(scenario["redemption"]["id"])
        assert redemption["status"] == "HELD_PENDING_COMPLIANCE", (
            "link 3: the ALLOCATED redemption must move to HELD_PENDING_COMPLIANCE, got "
            f"{redemption['status']}"
        )

        receiving_area = fetch_receiving_area(scenario["receiving_area"]["id"])
        assert receiving_area["reserved_units"] == BACKING_UNITS, (
            "link 3: the held units stay inside the area's reserved_units, got "
            f"{receiving_area['reserved_units']}"
        )
        assert receiving_area["absorbed_units"] == 0, (
            f"nothing has been absorbed yet, got {receiving_area['absorbed_units']}"
        )

    def test_held_backing_pushes_the_application_backing_deficient_and_blocks_finalization(self):
        """Link four, caused by link three alone: the held units leave
        `pending_backed_units`, and only then does the backing shortfall exist and
        push the DESIGN_APPROVED application out of the finalizable state.

        PRD §3.9: "Fourth — caused by the third — every receiving-site application in `DESIGN_APPROVED` whose recomputed `backed_units` plus `pending_backed_units` has fallen below `required_backing_units` moves `DESIGN_APPROVED → BACKING_DEFICIENT`."
        PRD §3.8: "Note that the backing figure the final variant consumes counts redemptions in `ALLOCATED` and `CONFIRMED` only; rows in `HELD_PENDING_COMPLIANCE` and `RELEASED` are excluded from it."
        PRD §3.8: "Only the application's own developer finalizes, and only from `DESIGN_APPROVED` — a `DESIGN_REVIEW`, `REVISIONS_REQUIRED`, or `BACKING_DEFICIENT` application is rejected with `ERR_APPLICATION_NOT_DESIGN_APPROVED`."

        Design: Difficulty/transitive_cascade/inspection_cascades_easement_freeze_to_backing_deficient_application
        """
        scenario = _design_approved_backed_application()

        record_inspection(
            scenario["easement"]["id"], INSPECTION_DATE, "MAJOR_VIOLATION",
            AFFECTED_ACRES, MONITOR_USER_ID,
        )

        rsa = fetch_receiving_site_application(scenario["rsa"]["id"])
        assert rsa["pending_backed_units"] == 0, (
            "link 4: held backing no longer counts, so pending_backed_units must be 0, got "
            f"{rsa['pending_backed_units']}"
        )
        assert rsa["backed_units"] == 0, (
            "link 4: HELD_PENDING_COMPLIANCE rows are excluded from backed_units, got "
            f"{rsa['backed_units']}"
        )
        assert rsa["required_backing_units"] == BACKING_UNITS, (
            "the requirement itself is unchanged by the freeze, got "
            f"{rsa['required_backing_units']}"
        )
        assert rsa["status"] == "BACKING_DEFICIENT", (
            "link 4: an application whose backing fell below the requirement must be "
            f"BACKING_DEFICIENT, got {rsa['status']}"
        )

        resp = api_client.finalize_receiving_site_application(
            rsa["id"], make_developer_headers(scenario["developer"]["id"]), {},
        )
        validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_DESIGN_APPROVED.value)
