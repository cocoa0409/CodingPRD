"""Cross-entity gates and contended temporal windows in the TDR program.

Two families of rule live here.

The first is a write on one entity that is refused purely because of a *second*
entity's state: a sending parcel that cannot be enrolled while its sending area
is still `DRAFT`, and a certificate redemption that cannot be allocated while
the easement two hops upstream of the certificate is out of compliance.  In both
cases the byte-identical request succeeds once the other entity moves, which is
what proves the refusal came from the neighbour and not from the payload.

The second is a contended interval: a neighbourhood's appraisal calendar, whose
half-open windows may abut but may not overlap, and a single easement's
inspection slot, which enforces a minimum 90-day separation rather than mere
adjacency.
"""
import pytest

from test_helpers import (
    MONITOR_USER_ID,
    MONITOR_USER_ID_ALT,
    TEST_USERS,
    allocate_redemption_payload,
    api_client,
    ApiErrorId,
    assert_appraisal_schedule,
    assert_certificate,
    assert_certificate_redemption,
    assert_conservation_easement,
    assert_monitoring_inspection,
    assert_same_date,
    assert_same_instant,
    assert_sending_parcel,
    create_appraisal_schedule_payload,
    create_active_receiving_area,
    create_inspection_payload,
    create_sending_parcel_payload,
    designate_sending_area,
    fetch_certificate,
    fetch_easement,
    fetch_inspection,
    fetch_receiving_area,
    fetch_receiving_site_application,
    fetch_sending_area,
    file_receiving_site_application,
    make_developer_headers,
    make_monitor_headers,
    notice_violation,
    publish_appraisal_schedule,
    record_inspection,
    register_landowner,
    set_clock,
    setup_certified_severance,
    setup_developer_holding_certificate,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
CLOCK = "2026-08-10T00:00:00Z"

# The canonical 100.00 / 22.00 / PRIME / 2-dwelling parcel under V1_NET_ACRE at
# 0.25 units per acre: (100.00 - 22.00) x 0.25 x 1.25 = 24.375, floored to 24,
# less the 2 existing dwelling units.
EXPECTED_BASELINE_UNITS = 22


def _draft_area_and_enrollment_payload():
    """Clock, a LANDOWNER party, a still-`DRAFT` sending area, and the parcel
    enrollment payload aimed at it.  Nothing is enrolled yet."""
    set_clock(CLOCK)
    landowner = register_landowner(neighborhood_code="NB-EAST")
    area = designate_sending_area(
        code="SA-DRAFT",
        name="Draft Ridge",
        neighborhood_code="NB-EAST",
        allocation_formula_version="V1_NET_ACRE",
        base_rate_units_per_acre=0.25,
        gross_discount_factor=0.80,
        equity_tier="UNDERSERVED",
        sending_cap_units=200,
    )
    payload = create_sending_parcel_payload(
        landowner["id"], area["id"], apn="APN-0001",
        gross_acres=100.00, constrained_acres=22.00,
        soil_class="PRIME", existing_dwelling_units=2,
    )
    return landowner, area, payload


class TestParcelEnrollmentGatedBySendingAreaStatus:
    """Enrolling a parcel is refused by the *area's* status, not the parcel's payload."""

    def test_enrollment_refused_while_sending_area_is_draft(self):
        """A `DRAFT` sending area accepts no parcel, and the refusal writes nothing.

        PRD §2.10 rung 26: "The `SendingArea` named by the parcel or application
        has `status` of `ACTIVE`; a `DRAFT` or `CLOSED` area accepts nothing, and
        the request is rejected with `ERR_SENDING_AREA_NOT_ACTIVE` (409). Applies
        to parcel enrollment, severance filing, and severance certification."
        PRD §3.2: "A newly designated sending area opens in `status` `DRAFT` with
        `severed_units_total` and `issued_certificate_count` both at 0."
        PRD §3.2: "Only an `ACTIVE` sending area accepts parcel enrollment,
        severance filing, or certification."

        Design: Difficulty/cross_entity_state_dependency/parcel_enrollment_gated_by_sending_area_status
        """
        _landowner, area, payload = _draft_area_and_enrollment_payload()

        assert fetch_sending_area(area["id"])["status"] == "DRAFT", (
            "a freshly designated sending area must open in DRAFT"
        )

        resp = api_client.create_sending_parcel(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_SENDING_AREA_NOT_ACTIVE.value)

        rows, meta = validate_paginated(
            api_client.list_sending_parcels(ADMIN, params={"sending_area_id": area["id"]})
        )
        assert meta["total_count"] == 0, (
            f"a refused enrollment must persist no SendingParcel row, saw {rows}"
        )
        after = fetch_sending_area(area["id"])
        assert after["status"] == "DRAFT", "the refused enrollment must not activate the area"
        assert after["severed_units_total"] == 0, (
            "a refused enrollment severs nothing from the area"
        )

    def test_identical_enrollment_payload_succeeds_once_the_area_is_active(self):
        """The same payload, the same `apn`, admitted after `DRAFT → ACTIVE`.

        PRD §3.3: "the referenced sending area must be `ACTIVE`, or the request is
        rejected with `ERR_SENDING_AREA_NOT_ACTIVE`."
        PRD §2.10 rung 33: "`apn` is unique across all sending parcels; otherwise
        `ERR_DUPLICATE_PARCEL_APN` (409)."
        PRD §3.3: "Fourth, that raw figure is floored to a whole number —
        truncated downward, never rounded — the parcel's `existing_dwelling_units`
        are subtracted from the floored value because each already-built dwelling
        consumes one allocated right, and the result is taken as zero if the
        subtraction would go negative."
        PRD §3.3: "On enrollment the derived ledger fields open at their starting
        values: `remaining_units` equals `baseline_allocation_units`,
        `severed_units` is 0, `restricted_acres` is 0, `easement_status` is
        `NONE`, and `parcel_status` is `UNSEVERED`."

        Design: Difficulty/cross_entity_state_dependency/parcel_enrollment_gated_by_sending_area_status
        """
        _landowner, area, payload = _draft_area_and_enrollment_payload()

        refused = api_client.create_sending_parcel(payload, ADMIN)
        validate_error(refused, ApiErrorId.ERR_SENDING_AREA_NOT_ACTIVE.value)

        activated = validate_success(api_client.activate_sending_area(area["id"], ADMIN))
        assert activated["status"] == "ACTIVE", "activation must move the area DRAFT -> ACTIVE"

        # The refusal left no row behind, so the same apn is still free.
        parcel = validate_success(api_client.create_sending_parcel(payload, ADMIN), 201)
        assert_sending_parcel(parcel)
        assert parcel["baseline_allocation_units"] == EXPECTED_BASELINE_UNITS, (
            "baseline_allocation_units must be the floored raw allocation less the "
            f"existing dwellings: expected {EXPECTED_BASELINE_UNITS}, got "
            f"{parcel['baseline_allocation_units']}"
        )
        assert parcel["remaining_units"] == EXPECTED_BASELINE_UNITS, (
            "remaining_units opens equal to baseline_allocation_units"
        )
        assert parcel["severed_units"] == 0, "severed_units opens at 0"
        assert parcel["restricted_acres"] == pytest.approx(0.00, abs=0.01), (
            "restricted_acres opens at 0.00"
        )
        assert parcel["easement_status"] == "NONE", "easement_status opens at NONE"
        assert parcel["parcel_status"] == "UNSEVERED", "parcel_status opens at UNSEVERED"
        assert fetch_sending_area(area["id"])["severed_units_total"] == 0, (
            "enrollment alone severs nothing from the area"
        )


def _frozen_certificate_with_design_approved_application():
    """A developer holding a 22-unit certificate whose source easement has been
    driven out of compliance, plus a `DESIGN_APPROVED` receiving-site application
    filed *after* the freeze so its `version` is untouched by that cascade."""
    scenario = setup_developer_holding_certificate()
    inspection = notice_violation(
        scenario["easement"]["id"], inspection_date="2026-08-10",
        finding="MAJOR_VIOLATION", affected_acres=12.00,
        monitor_user_id=MONITOR_USER_ID,
    )
    receiving_area = create_active_receiving_area(
        code="RA-CORE",
        name="Core Receiving Area",
        neighborhood_code="NB-CORE",
        base_density_units_per_acre=4.00,
        max_bonus_pct=0.35,
        absorption_cap_units=500,
        design_review_required=False,
        eligible_sending_area_codes=[],
    )
    rsa = file_receiving_site_application(
        scenario["developer"]["id"], receiving_area["id"],
        site_acres=12.00, requested_bonus_units=20,
    )
    scenario.update({
        "inspection": inspection,
        "receiving_area": fetch_receiving_area(receiving_area["id"]),
        "rsa": rsa,
        "certificate": fetch_certificate(scenario["certificate"]["id"]),
        "easement": fetch_easement(scenario["easement"]["id"]),
    })
    return scenario


class TestRedemptionGatedBySourceEasementCompliance:
    """A redemption is refused by the compliance posture of the easement two hops
    upstream of the certificate it names."""

    def test_allocation_refused_while_source_easement_is_violation_noticed(self):
        """`VIOLATION_NOTICED` upstream freezes the rights and the allocation writes nothing.

        PRD §2.10 rung 24: "**Certificate compliance** — the certificate's source
        `ConservationEasement` has `compliance_status` of either `COMPLIANT` or
        `CURED`; a `VIOLATION_NOTICED`, `UNDER_CURE` or `ESCALATED` easement
        freezes its rights and the request is rejected with
        `ERR_CERTIFICATE_FROZEN` (409). Applies to transaction proposal,
        certificate split, and redemption allocation."
        PRD §3.9: "A violation finding moves the easement `COMPLIANT →
        VIOLATION_NOTICED`, or `CURED → VIOLATION_NOTICED` for a repeat offender,
        and sets its `cure_deadline`."
        PRD §3.9: "Second — caused by the first — every certificate whose
        `conservation_easement_id` names this easement and whose `market_status`
        is `HELD` or `UNDER_CONTRACT` moves to `FROZEN`, and any market
        transaction on such a certificate that is still `PROPOSED` moves
        `PROPOSED → CANCELLED` with `reversal_reason` set to the literal
        `EASEMENT_NONCOMPLIANT`."
        PRD §3.8: "When the flag is false, it starts `SUBMITTED → DESIGN_APPROVED`
        and skips the board entirely, with `design_review_round` left at 0 and
        `design_reviewed_by_user_id` left unset."

        Design: Difficulty/cross_entity_state_dependency/redemption_gated_by_source_easement_compliance
        """
        scenario = _frozen_certificate_with_design_approved_application()
        cert, rsa = scenario["certificate"], scenario["rsa"]
        developer = scenario["developer"]

        assert scenario["easement"]["compliance_status"] == "VIOLATION_NOTICED", (
            "the MAJOR_VIOLATION finding must move the easement to VIOLATION_NOTICED"
        )
        assert cert["market_status"] == "FROZEN", (
            "the freeze cascade must move the derived certificate to FROZEN"
        )
        assert rsa["status"] == "DESIGN_APPROVED", (
            "an area with design_review_required false admits the filing straight to "
            "DESIGN_APPROVED"
        )

        resp = api_client.allocate_redemption(
            rsa["id"],
            allocate_redemption_payload(cert["id"], 16, rsa["version"]),
            make_developer_headers(developer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CERTIFICATE_FROZEN.value)

        rows, meta = validate_paginated(
            api_client.list_certificate_redemptions(
                ADMIN, params={"receiving_site_application_id": rsa["id"]}
            )
        )
        assert meta["total_count"] == 0, (
            f"a refused allocation must persist no CertificateRedemption row, saw {rows}"
        )
        after = fetch_receiving_site_application(rsa["id"])
        assert after["status"] == "DESIGN_APPROVED", (
            "the refused allocation must leave the application in DESIGN_APPROVED"
        )
        assert after["pending_backed_units"] == 0, (
            "nothing was committed, so pending_backed_units stays at 0"
        )
        assert fetch_certificate(cert["id"])["units_encumbered"] == 0, (
            "the refused allocation must encumber nothing on the certificate"
        )
        assert fetch_receiving_area(scenario["receiving_area"]["id"])["reserved_units"] == 0, (
            "the refused allocation must reserve nothing in the receiving area"
        )

    def test_allocation_admitted_after_cure_verification_unfreezes_the_certificate(self):
        """The identical allocation — same units, same observed application version —
        is admitted once the upstream easement reaches `CURED`.

        PRD §3.9: "An outcome of `CURED` clears the violation and runs the exact
        compensating cascade, unwinding the freeze level by level. The easement
        moves to `CURED` from whichever of `VIOLATION_NOTICED`, `UNDER_CURE`, or
        `ESCALATED` it currently occupies, and its `cure_deadline` is cleared.
        Every certificate on that easement whose `market_status` is `FROZEN`
        returns to `HELD`."
        PRD §3.9: "The inspection records `cure_verified_at` from the current
        logical clock and `cure_verified_by_user_id` from the acting user, and
        moves to `CURED`; the `version` of every entity touched is incremented."
        PRD §2.4: "`version` is an integer that starts at 1 when the row is
        created and increases by exactly one on every mutation of that row,
        including mutations reached through a cascade rather than through a direct
        request."
        PRD §2.8: "Allocating certificate units to back a receiving-site
        application requires `expected_receiving_site_application_version`,
        carrying the client's last observed `version` of that
        `ReceivingSiteApplication`."
        PRD §3.8: "A successful allocation creates a redemption in `ALLOCATED`
        with `allocated_at` at the current logical clock and `source_easement_id`
        copied from the certificate's `conservation_easement_id` — the link is
        copied at allocation time so that later compliance checks can reach the
        easement directly."
        PRD §3.8: "The certificate's `units_encumbered` grows by `units` and the
        area's `reserved_units` grows by `units`; nothing is consumed yet, only
        committed."

        Design: Difficulty/cross_entity_state_dependency/redemption_gated_by_source_easement_compliance
        """
        scenario = _frozen_certificate_with_design_approved_application()
        cert, rsa = scenario["certificate"], scenario["rsa"]
        developer, easement = scenario["developer"], scenario["easement"]
        observed_version = rsa["version"]

        refused = api_client.allocate_redemption(
            rsa["id"],
            allocate_redemption_payload(cert["id"], 16, observed_version),
            make_developer_headers(developer["id"]),
        )
        validate_error(refused, ApiErrorId.ERR_CERTIFICATE_FROZEN.value)
        assert fetch_receiving_site_application(rsa["id"])["version"] == observed_version, (
            "a refused allocation mutates nothing, so the application's version must "
            "not advance"
        )

        cured = validate_success(
            api_client.verify_cure(
                scenario["inspection"]["id"], {"outcome": "CURED"},
                make_monitor_headers(MONITOR_USER_ID_ALT),
            )
        )
        assert_monitoring_inspection(cured)
        assert cured["status"] == "CURED", "a CURED outcome moves the inspection to CURED"
        assert cured["cure_verified_by_user_id"] == MONITOR_USER_ID_ALT, (
            "cure_verified_by_user_id records the acting verifier"
        )
        easement_after = fetch_easement(easement["id"])
        assert_conservation_easement(easement_after)
        assert easement_after["compliance_status"] == "CURED", (
            "the compensating cascade moves the easement VIOLATION_NOTICED -> CURED"
        )
        assert fetch_certificate(cert["id"])["market_status"] == "HELD", (
            "the compensating cascade returns the frozen certificate to HELD"
        )

        redemption = validate_success(
            api_client.allocate_redemption(
                rsa["id"],
                allocate_redemption_payload(cert["id"], 16, observed_version),
                make_developer_headers(developer["id"]),
            ),
            201,
        )
        assert_certificate_redemption(redemption)
        assert redemption["status"] == "ALLOCATED", "a successful allocation opens in ALLOCATED"
        assert redemption["units"] == 16, "the allocation commits the units requested"
        assert_same_instant(redemption["allocated_at"], CLOCK, "CertificateRedemption.allocated_at")
        assert redemption["source_easement_id"] == easement["id"], (
            "source_easement_id is copied from the certificate's conservation_easement_id"
        )

        rsa_after = fetch_receiving_site_application(rsa["id"])
        assert rsa_after["pending_backed_units"] == 16, (
            "pending_backed_units is recomputed from the ALLOCATED redemption"
        )
        assert rsa_after["status"] == "DESIGN_APPROVED", (
            "the application stays DESIGN_APPROVED across the allocation"
        )
        cert_after = fetch_certificate(cert["id"])
        assert_certificate(cert_after)
        assert cert_after["units_encumbered"] == 16, (
            "the certificate's units_encumbered grows by the allocated units"
        )
        assert fetch_receiving_area(scenario["receiving_area"]["id"])["reserved_units"] == 16, (
            "the receiving area's reserved_units grows by the allocated units"
        )


def _incumbent_nb_east_window():
    """One `ACTIVE` NB-EAST appraisal schedule covering [2026-01-01, 2026-07-01)."""
    set_clock(CLOCK)
    return publish_appraisal_schedule(
        neighborhood_code="NB-EAST",
        per_unit_value_cents=1_000_000,
        equity_adjustment_bps=0,
        effective_from="2026-01-01",
        effective_to="2026-07-01",
    )


def _fetch_schedule(schedule_id: str) -> dict:
    return validate_success(api_client.get_appraisal_schedule(schedule_id, ADMIN))


class TestAppraisalCalendarWindowAdjacency:
    """A neighbourhood's appraisal calendar is a contended resource whose windows
    are half-open: they may touch, they may not overlap."""

    def test_touching_windows_are_both_accepted_on_either_side_of_the_incumbent(self):
        """Adjacency on both endpoints: `effective_to` == `effective_from` is not an overlap.

        PRD §3.7: "Publication is rejected with `ERR_APPRAISAL_PERIOD_OVERLAP`
        when the new window overlaps the window of any other `ACTIVE` schedule for
        the same neighborhood; because the interval includes its start instant and
        excludes its end instant, two windows that merely touch — one window's
        `effective_to` equal to the next window's `effective_from` — do not
        overlap and are both accepted."
        PRD §3.7: "A schedule opens in `status` `ACTIVE`; the only other value is
        `SUPERSEDED`, which is set on an existing row when a new schedule for the
        same `neighborhood_code` declares an `effective_from` equal to that row's
        `effective_from`."

        Design: Difficulty/resource_temporal_overlap/appraisal_calendar_adjacency_allowed_overlap_rejected
        """
        incumbent = _incumbent_nb_east_window()

        after = validate_success(
            api_client.create_appraisal_schedule(
                create_appraisal_schedule_payload(
                    neighborhood_code="NB-EAST",
                    per_unit_value_cents=1_234_567,
                    equity_adjustment_bps=250,
                    effective_from="2026-07-01",
                    effective_to="2027-01-01",
                ),
                ADMIN,
            ),
            201,
        )
        assert_appraisal_schedule(after)

        before = validate_success(
            api_client.create_appraisal_schedule(
                create_appraisal_schedule_payload(
                    neighborhood_code="NB-EAST",
                    per_unit_value_cents=900_000,
                    equity_adjustment_bps=0,
                    effective_from="2025-06-01",
                    effective_to="2026-01-01",
                ),
                ADMIN,
            ),
            201,
        )
        assert_appraisal_schedule(before)

        for label, row in (("incumbent", incumbent), ("abutting-after", after),
                           ("abutting-before", before)):
            assert _fetch_schedule(row["id"])["status"] == "ACTIVE", (
                f"the {label} window must remain ACTIVE: no effective_from collided"
            )

        rows, meta = validate_paginated(
            api_client.list_appraisal_schedules(ADMIN, params={"neighborhood_code": "NB-EAST"})
        )
        assert meta["total_count"] == 3, (
            f"three touching NB-EAST windows must all persist, saw {meta['total_count']}"
        )
        assert {r["id"] for r in rows} == {incumbent["id"], after["id"], before["id"]}, (
            "the NB-EAST calendar must contain exactly the three published windows"
        )

    def test_straddling_window_is_rejected_and_contention_is_scoped_to_the_neighborhood(self):
        """One day of overlap is enough to reject — but only inside the same neighbourhood.

        PRD §2.10 rung 29: "A new appraisal schedule's window does not overlap an
        existing `ACTIVE` window for the same `neighborhood_code`; otherwise
        `ERR_APPRAISAL_PERIOD_OVERLAP` (409)."
        PRD §3.7: "Publication is rejected with `ERR_APPRAISAL_PERIOD_OVERLAP`
        when the new window overlaps the window of any other `ACTIVE` schedule for
        the same neighborhood; because the interval includes its start instant and
        excludes its end instant, two windows that merely touch — one window's
        `effective_to` equal to the next window's `effective_from` — do not
        overlap and are both accepted."

        Design: Difficulty/resource_temporal_overlap/appraisal_calendar_adjacency_allowed_overlap_rejected
        """
        incumbent = _incumbent_nb_east_window()
        after = publish_appraisal_schedule(
            neighborhood_code="NB-EAST", per_unit_value_cents=1_234_567,
            equity_adjustment_bps=250, effective_from="2026-07-01", effective_to="2027-01-01",
        )
        before = publish_appraisal_schedule(
            neighborhood_code="NB-EAST", per_unit_value_cents=900_000,
            equity_adjustment_bps=0, effective_from="2025-06-01", effective_to="2026-01-01",
        )

        straddling = create_appraisal_schedule_payload(
            neighborhood_code="NB-EAST",
            per_unit_value_cents=1_111_111,
            equity_adjustment_bps=0,
            effective_from="2026-06-30",
            effective_to="2026-12-31",
        )
        validate_error(
            api_client.create_appraisal_schedule(straddling, ADMIN),
            ApiErrorId.ERR_APPRAISAL_PERIOD_OVERLAP.value,
        )

        west = dict(straddling, neighborhood_code="NB-WEST")
        west_row = validate_success(api_client.create_appraisal_schedule(west, ADMIN), 201)
        assert_appraisal_schedule(west_row)
        assert west_row["status"] == "ACTIVE", (
            "the same window in an uncontended neighborhood opens ACTIVE"
        )

        east_rows, east_meta = validate_paginated(
            api_client.list_appraisal_schedules(ADMIN, params={"neighborhood_code": "NB-EAST"})
        )
        assert east_meta["total_count"] == 3, (
            "the rejected straddling window must create no row: NB-EAST still holds "
            f"three schedules, saw {east_meta['total_count']}"
        )
        assert {r["id"] for r in east_rows} == {incumbent["id"], after["id"], before["id"]}, (
            "the NB-EAST calendar must be unchanged by the rejected publication"
        )

        west_rows, west_meta = validate_paginated(
            api_client.list_appraisal_schedules(ADMIN, params={"neighborhood_code": "NB-WEST"})
        )
        assert west_meta["total_count"] == 1, (
            f"NB-WEST must hold exactly the one window, saw {west_meta['total_count']}"
        )
        assert [r["id"] for r in west_rows] == [west_row["id"]], (
            "the NB-WEST listing must contain the accepted straddling window"
        )


def _easement_with_one_compliant_inspection():
    """A fully severed parcel's `RECORDED`, `COMPLIANT` easement carrying exactly
    one COMPLIANT inspection dated 2026-08-10, with the clock then moved to
    2026-11-08 — ninety days later to the day."""
    scenario = setup_certified_severance()
    first = record_inspection(
        scenario["easement"]["id"], "2026-08-10", "COMPLIANT", 0.00,
        monitor_user_id=MONITOR_USER_ID,
    )
    set_clock("2026-11-08T00:00:00Z")
    scenario["first_inspection"] = first
    return scenario


def _attempt_inspection(easement_id: str, inspection_date: str):
    return api_client.create_inspection(
        easement_id,
        create_inspection_payload(inspection_date, "COMPLIANT", 0.00),
        make_monitor_headers(MONITOR_USER_ID),
    )


class TestInspectionNinetyDayBuffer:
    """The inspection slot on one easement enforces a minimum separation, and the
    boundary is inclusive at exactly ninety days."""

    def test_eighty_nine_day_gap_is_refused_and_leaves_last_inspection_at_alone(self):
        """89 days after `last_inspection_at` is refused, and the refusal advances nothing.

        PRD §3.9: "The easement must be on the register — `recording_status` of
        `RECORDED` or `AMENDED` — and the inspection must respect a minimum
        interval: `inspection_date` must be at least 90 days after the easement's
        `last_inspection_at`, with a gap of exactly 90 days allowed and 89 days
        rejected with `ERR_INSPECTION_WINDOW_CONFLICT`. Every accepted inspection
        updates `last_inspection_at` to its `inspection_date`."
        PRD §3.9: "A finding of `COMPLIANT` records `severity_score` as 0.00,
        leaves `cure_deadline` unset, and opens the inspection directly in
        `CLOSED`."

        Design: Difficulty/resource_temporal_overlap/inspection_ninety_day_buffer_inclusive_at_the_boundary
        """
        scenario = _easement_with_one_compliant_inspection()
        easement_id = scenario["easement"]["id"]
        first = fetch_inspection(scenario["first_inspection"]["id"])

        assert_monitoring_inspection(first)
        assert first["severity_score"] == pytest.approx(0.00, abs=0.01), (
            "a COMPLIANT finding scores 0.00"
        )
        assert first.get("cure_deadline") is None, (
            "a COMPLIANT finding leaves cure_deadline unset"
        )
        assert first["status"] == "CLOSED", "a COMPLIANT finding opens directly in CLOSED"
        assert_same_date(
            fetch_easement(easement_id)["last_inspection_at"], "2026-08-10",
            "ConservationEasement.last_inspection_at",
        )

        validate_error(
            _attempt_inspection(easement_id, "2026-11-07"),
            ApiErrorId.ERR_INSPECTION_WINDOW_CONFLICT.value,
        )

        rows, meta = validate_paginated(api_client.list_easement_inspections(easement_id, ADMIN))
        assert meta["total_count"] == 1, (
            f"the refused inspection must persist no row, saw {meta['total_count']}: {rows}"
        )
        easement_after = fetch_easement(easement_id)
        assert_same_date(
            easement_after["last_inspection_at"], "2026-08-10",
            "ConservationEasement.last_inspection_at",
        )
        assert easement_after["compliance_status"] == "COMPLIANT", (
            "a refused inspection changes no compliance posture"
        )

    def test_exactly_ninety_day_gap_is_admitted(self):
        """The buffer is inclusive: the same request one day later is accepted.

        PRD §3.9: "The easement must be on the register — `recording_status` of
        `RECORDED` or `AMENDED` — and the inspection must respect a minimum
        interval: `inspection_date` must be at least 90 days after the easement's
        `last_inspection_at`, with a gap of exactly 90 days allowed and 89 days
        rejected with `ERR_INSPECTION_WINDOW_CONFLICT`. Every accepted inspection
        updates `last_inspection_at` to its `inspection_date`."
        PRD §3.9: "A finding of `COMPLIANT` records `severity_score` as 0.00,
        leaves `cure_deadline` unset, and opens the inspection directly in
        `CLOSED`."
        PRD §3.9: "Second — caused by the first — every certificate whose
        `conservation_easement_id` names this easement and whose `market_status`
        is `HELD` or `UNDER_CONTRACT` moves to `FROZEN`, and any market
        transaction on such a certificate that is still `PROPOSED` moves
        `PROPOSED → CANCELLED` with `reversal_reason` set to the literal
        `EASEMENT_NONCOMPLIANT`."

        Design: Difficulty/resource_temporal_overlap/inspection_ninety_day_buffer_inclusive_at_the_boundary
        """
        scenario = _easement_with_one_compliant_inspection()
        easement_id = scenario["easement"]["id"]

        validate_error(
            _attempt_inspection(easement_id, "2026-11-07"),
            ApiErrorId.ERR_INSPECTION_WINDOW_CONFLICT.value,
        )

        second = validate_success(_attempt_inspection(easement_id, "2026-11-08"), 201)
        assert_monitoring_inspection(second)
        assert_same_date(second["inspection_date"], "2026-11-08", "MonitoringInspection.inspection_date")
        assert second["severity_score"] == pytest.approx(0.00, abs=0.01), (
            "a COMPLIANT finding scores 0.00"
        )
        assert second.get("cure_deadline") is None, (
            "a COMPLIANT finding leaves cure_deadline unset"
        )
        assert second["status"] == "CLOSED", "a COMPLIANT finding opens directly in CLOSED"

        easement_after = fetch_easement(easement_id)
        assert_conservation_easement(easement_after)
        assert_same_date(
            easement_after["last_inspection_at"], "2026-11-08",
            "ConservationEasement.last_inspection_at",
        )
        assert easement_after["compliance_status"] == "COMPLIANT", (
            "two COMPLIANT findings leave the easement COMPLIANT"
        )
        assert easement_after["prior_violation_count"] == 0, (
            "a COMPLIANT finding is not a violation, so prior_violation_count stays 0"
        )

        rows, meta = validate_paginated(api_client.list_easement_inspections(easement_id, ADMIN))
        assert meta["total_count"] == 2, (
            f"both accepted inspections must persist, saw {meta['total_count']}: {rows}"
        )
        assert fetch_certificate(scenario["certificate"]["id"])["market_status"] == "HELD", (
            "only a violation finding freezes the rights derived from an easement"
        )
