"""Lifecycle transitions: birth states, refused transitions and terminal states.

These tests pin the declared state machines of the program's workflow records:
the state a record is born in, the branch that chooses that state, the guards
that refuse a trigger fired from the wrong state, and the ledger-wide side
effects of the transitions that do fire.  A refused transition must change
nothing at all — not the status, not the actor stamps, not the version.

Every test builds its own chain from scratch through the program's own
endpoints, so no test depends on another's residue.
"""
import pytest

from test_helpers import (
    ADMIN_USER_ID,
    ADMIN_USER_ID_ALT,
    CANONICAL_BASELINE_UNITS,
    CANONICAL_PARCEL,
    CLOCK_STARTUP_DEFAULT,
    DESIGN_BOARD_USER_ID,
    MONITOR_USER_ID,
    REVIEWER_USER_ID,
    REVIEWER_USER_ID_ALT,
    TEST_USERS,
    ApiErrorId,
    api_client,
    approve_application,
    assert_certificate_transfer,
    assert_monitoring_inspection,
    assert_receiving_site_application,
    assert_same_date,
    assert_same_instant,
    assert_severance_application,
    certify_application,
    create_active_receiving_area,
    create_active_sending_area,
    create_receiving_site_application_payload,
    designate_sending_area,
    design_review_payload,
    enroll_parcel,
    fetch_application,
    fetch_certificate,
    fetch_easement,
    fetch_inspection,
    fetch_parcel,
    fetch_party,
    fetch_receiving_site_application,
    fetch_sending_area,
    file_severance,
    make_admin_headers,
    make_design_board_headers,
    make_developer_headers,
    make_landowner_headers,
    make_reviewer_headers,
    record_inspection,
    register_developer,
    register_landowner,
    retire_certificate_payload,
    screen_application,
    set_clock,
    setup_certified_severance,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
CLOCK = "2026-08-10T00:00:00Z"
EAST_AREA_CODE = "SA-EAST"
EAST_NEIGHBORHOOD = "NB-EAST"

AREA_TERMS = {
    "neighborhood_code": EAST_NEIGHBORHOOD,
    "equity_tier": "UNDERSERVED",
    "allocation_formula_version": "V1_NET_ACRE",
    "base_rate_units_per_acre": 0.25,
    "gross_discount_factor": 0.80,
    "sending_cap_units": 200,
}


def _east_area():
    """An ACTIVE sending area on the ordinance terms these tests assume."""
    return create_active_sending_area(code=EAST_AREA_CODE, name="East Ridge", **AREA_TERMS)


def _certify_parcel(landowner, area_id, requested_units, **parcel_overrides):
    """Enroll one parcel and carry it all the way through certification.

    Returns {parcel, application, certificate, easement} for the settled chain.
    """
    parcel_kwargs = dict(CANONICAL_PARCEL)
    parcel_kwargs.update(parcel_overrides)
    parcel = enroll_parcel(landowner["id"], area_id, **parcel_kwargs)
    application = approve_application(parcel["id"], landowner["id"], requested_units)
    certificate = certify_application(application["id"])
    return {
        "parcel": fetch_parcel(parcel["id"]),
        "application": fetch_application(application["id"]),
        "certificate": certificate,
        "easement": fetch_easement(certificate["conservation_easement_id"]),
    }


def test_severance_application_is_born_in_submitted_with_a_zeroed_decision_record():
    """A filing opens in SUBMITTED with every review-cycle field still empty.

    PRD §3.4: "An accepted filing opens in `status` `SUBMITTED` with
    `revision_round` at 0 and both `allocated_units` and `residual_units_retained`
    at 0. `applied_formula_version`, `screened_by_user_id`, `decided_by_user_id`,
    `certified_by_user_id`, `decision_note`, and `denial_reason` all begin unset.
    The application's `status` moves only among `SUBMITTED`, `UNDER_REVIEW`,
    `REVISION_REQUESTED`, `APPROVED`, `CERTIFIED`, `DENIED`, and `SUSPENDED`, of
    which `CERTIFIED`, `DENIED`, and `SUSPENDED` are terminal."

    PRD §2.4: "`version` is an integer that starts at 1 when the row is created and
    increases by exactly one on every mutation of that row, including mutations
    reached through a cascade rather than through a direct request."

    PRD §2.5: "Before any administrator sets it, that clock reads exactly
    `2026-08-01T00:00:00Z` — a fixed startup default that is never replaced by real
    time."

    PRD §3.3: "`remaining_units` is always `baseline_allocation_units` less
    `severed_units`, and `severed_units` is always the sum of `allocated_units`
    over the parcel's severance applications that reached `CERTIFIED`."

    Design: Corner/state_machines/severance_application_is_born_in_submitted_with_a_zeroed_decision_record
    """
    landowner = register_landowner(legal_name="Ridge Farm LLC")
    area = _east_area()
    parcel = enroll_parcel(landowner["id"], area["id"], **CANONICAL_PARCEL)

    resp = api_client.create_severance_application(
        {
            "sending_parcel_id": parcel["id"],
            "applicant_party_id": landowner["id"],
            "requested_units": CANONICAL_BASELINE_UNITS,
        },
        make_landowner_headers(landowner["id"]),
    )
    data = validate_success(resp, 201)
    assert_severance_application(data)

    assert data["status"] == "SUBMITTED", (
        f"a filing is born in SUBMITTED, got {data['status']!r}"
    )
    assert data["revision_round"] == 0, (
        f"revision_round opens at 0, got {data['revision_round']}"
    )
    assert data["allocated_units"] == 0, (
        f"allocated_units opens at 0, got {data['allocated_units']}"
    )
    assert data["residual_units_retained"] == 0, (
        f"residual_units_retained opens at 0, got {data['residual_units_retained']}"
    )
    for field in (
        "applied_formula_version", "screened_by_user_id", "decided_by_user_id",
        "certified_by_user_id", "decision_note", "denial_reason",
    ):
        assert data.get(field) is None, (
            f"{field} begins unset on a filing, got {data.get(field)!r}"
        )
    assert data["version"] == 1, f"a new row opens at version 1, got {data['version']}"
    assert_same_instant(data["created_at"], CLOCK_STARTUP_DEFAULT, "SeveranceApplication.created_at")

    settled_parcel = fetch_parcel(parcel["id"])
    assert settled_parcel["severed_units"] == 0, (
        f"filing alone severs nothing, got severed_units {settled_parcel['severed_units']}"
    )
    assert settled_parcel["parcel_status"] == "UNSEVERED", (
        f"filing alone leaves the parcel UNSEVERED, got {settled_parcel['parcel_status']!r}"
    )


def test_screening_an_application_already_under_review_is_rejected():
    """Only a SUBMITTED application may be screened, and a refusal restamps nothing.

    PRD §3.4: "A `SeveranceReviewer` takes a filed application into review, moving
    it `SUBMITTED → UNDER_REVIEW`, optionally recording a `screening_note`, writing
    the acting `X-User-ID` into `screened_by_user_id`, and incrementing the
    application's `version`. Screening requires that the application actually be in
    `SUBMITTED` — otherwise `ERR_APPLICATION_NOT_SCREENABLE` — that the parcel's
    sending area still be `ACTIVE`, and that the parcel's `parcel_status` still not
    be `FULLY_SEVERED`; the area and parcel are re-checked here because either may
    have moved since intake."

    Design: Corner/state_machines/screening_an_application_already_under_review_is_rejected
    """
    set_clock(CLOCK)
    landowner = register_landowner(legal_name="Ridge Farm LLC")
    area = _east_area()
    parcel = enroll_parcel(landowner["id"], area["id"], **CANONICAL_PARCEL)
    application = file_severance(parcel["id"], landowner["id"], CANONICAL_BASELINE_UNITS)

    first = screen_application(application["id"], REVIEWER_USER_ID)
    assert first["status"] == "UNDER_REVIEW", (
        f"the first screening moves the application to UNDER_REVIEW, got {first['status']!r}"
    )
    assert first["screened_by_user_id"] == REVIEWER_USER_ID, (
        "the first screening stamps the acting reviewer"
    )
    assert first["version"] == 2, f"screening increments the version, got {first['version']}"

    resp = api_client.screen_severance_application(
        application["id"], make_reviewer_headers(REVIEWER_USER_ID_ALT)
    )
    validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_SCREENABLE.value)

    settled = fetch_application(application["id"])
    assert settled["status"] == "UNDER_REVIEW", (
        f"the refused screening leaves the status alone, got {settled['status']!r}"
    )
    assert settled["screened_by_user_id"] == REVIEWER_USER_ID, (
        "the refused screening must not restamp screened_by_user_id with the second reviewer"
    )
    assert settled["version"] == 2, (
        f"the refused screening must not bump the version, got {settled['version']}"
    )


def test_activating_an_already_active_sending_area_is_rejected_not_a_no_op():
    """Activation is guarded on DRAFT, so a repeat activation is refused.

    PRD §3.2: "A newly designated sending area opens in `status` `DRAFT` with
    `severed_units_total` and `issued_certificate_count` both at 0. Activation
    moves it `DRAFT → ACTIVE` and increments its `version`; an area that is not in
    `DRAFT` cannot be activated and yields `ERR_AREA_NOT_DRAFT`. Only an `ACTIVE`
    sending area accepts parcel enrollment, severance filing, or certification."

    Design: Corner/state_machines/activating_an_already_active_sending_area_is_rejected_not_a_no_op
    """
    set_clock(CLOCK)
    area = designate_sending_area(code=EAST_AREA_CODE, name="East Ridge", **AREA_TERMS)
    assert area["status"] == "DRAFT", f"a designated area opens in DRAFT, got {area['status']!r}"
    assert area["version"] == 1, f"a designated area opens at version 1, got {area['version']}"

    activated = validate_success(api_client.activate_sending_area(area["id"], ADMIN))
    assert activated["status"] == "ACTIVE", (
        f"the first activation moves the area to ACTIVE, got {activated['status']!r}"
    )
    assert activated["version"] == 2, (
        f"activation increments the version, got {activated['version']}"
    )

    resp = api_client.activate_sending_area(area["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_AREA_NOT_DRAFT.value)

    settled = fetch_sending_area(area["id"])
    assert settled["status"] == "ACTIVE", (
        f"the refused activation leaves the area ACTIVE, got {settled['status']!r}"
    )
    assert settled["version"] == 2, (
        f"the refused activation must not bump the version, got {settled['version']}"
    )


def test_certified_severance_application_accepts_no_further_transition():
    """CERTIFIED is terminal, and each workflow trigger refuses it with its own code.

    PRD §3.4: "The application's `status` moves only among `SUBMITTED`,
    `UNDER_REVIEW`, `REVISION_REQUESTED`, `APPROVED`, `CERTIFIED`, `DENIED`, and
    `SUSPENDED`, of which `CERTIFIED`, `DENIED`, and `SUSPENDED` are terminal."

    PRD §3.4: "Screening requires that the application actually be in `SUBMITTED` —
    otherwise `ERR_APPLICATION_NOT_SCREENABLE` — that the parcel's sending area
    still be `ACTIVE`, and that the parcel's `parcel_status` still not be
    `FULLY_SEVERED`; the area and parcel are re-checked here because either may have
    moved since intake."

    PRD §3.4: "All three branches require the application to be `UNDER_REVIEW`,
    otherwise `ERR_APPLICATION_NOT_IN_REVIEW`, and all three write the acting
    `X-User-ID` into `decided_by_user_id` and increment the application's
    `version`."

    PRD §3.4: "Resubmission requires the application to be in `REVISION_REQUESTED`,
    otherwise `ERR_APPLICATION_NOT_REVISABLE`, requires the acting `X-User-ID` to
    equal `applicant_party_id`, and requires that incrementing `revision_round` not
    carry it past the two-round limit — otherwise `ERR_REVISION_LIMIT_EXCEEDED`."

    PRD §3.5: "The application must be in `APPROVED`, otherwise
    `ERR_APPLICATION_NOT_APPROVED`."

    PRD §3.5: "Alongside the cascade, the same request mints exactly one root
    **Certificate**."

    PRD §3.5: "The sending area's `severed_units_total` is recomputed as the sum of
    `allocated_units` over every `CERTIFIED` application on parcels in the area, and
    its `issued_certificate_count` is incremented by one."

    Design: Corner/state_machines/certified_severance_application_accepts_no_further_transition
    """
    scenario = setup_certified_severance(
        units=CANONICAL_BASELINE_UNITS, clock=CLOCK, equity_tier="UNDERSERVED",
        neighborhood_code=EAST_NEIGHBORHOOD, area_overrides={"code": EAST_AREA_CODE},
    )
    app_id = scenario["application"]["id"]
    landowner = scenario["landowner"]
    area_id = scenario["area"]["id"]
    certificate_id = scenario["certificate"]["id"]
    assert scenario["application"]["status"] == "CERTIFIED", (
        f"the chain must reach CERTIFIED, got {scenario['application']['status']!r}"
    )

    validate_error(
        api_client.screen_severance_application(app_id, make_reviewer_headers(REVIEWER_USER_ID)),
        ApiErrorId.ERR_APPLICATION_NOT_SCREENABLE.value,
    )
    validate_error(
        api_client.review_severance_application(
            app_id, {"decision": "DENY", "denial_reason": "late objection"},
            make_reviewer_headers(REVIEWER_USER_ID),
        ),
        ApiErrorId.ERR_APPLICATION_NOT_IN_REVIEW.value,
    )
    validate_error(
        api_client.resubmit_severance_application(
            app_id, {"requested_units": 10}, make_landowner_headers(landowner["id"]),
        ),
        ApiErrorId.ERR_APPLICATION_NOT_REVISABLE.value,
    )
    # The certifying identity differs from the reviewer who approved, so the
    # segregation-of-duties gate cannot stand in for the state guard here.
    validate_error(
        api_client.certify_severance_application(app_id, make_admin_headers(ADMIN_USER_ID_ALT)),
        ApiErrorId.ERR_APPLICATION_NOT_APPROVED.value,
    )

    settled = fetch_application(app_id)
    assert settled["status"] == "CERTIFIED", (
        f"four refused triggers leave the application CERTIFIED, got {settled['status']!r}"
    )
    assert settled["requested_units"] == CANONICAL_BASELINE_UNITS, (
        f"the refused resubmission must not restate requested_units, got {settled['requested_units']}"
    )
    assert settled.get("denial_reason") is None, (
        f"the refused denial must not record a reason, got {settled.get('denial_reason')!r}"
    )

    certificates, cert_meta = validate_paginated(
        api_client.list_certificates(ADMIN, params={"origin_sending_area_id": area_id})
    )
    assert cert_meta["total_count"] == 1, (
        f"the refused certify must not mint a second certificate, got {cert_meta['total_count']}"
    )
    assert certificates[0]["id"] == certificate_id, "the only certificate is the original one"

    _, transfer_meta = validate_paginated(
        api_client.list_certificate_transfers(ADMIN, params={"certificate_id": certificate_id})
    )
    assert transfer_meta["total_count"] == 1, (
        f"the refused certify appends no chain-of-title row, got {transfer_meta['total_count']}"
    )

    area = fetch_sending_area(area_id)
    assert area["severed_units_total"] == CANONICAL_BASELINE_UNITS, (
        f"the area counts one certification only, got {area['severed_units_total']}"
    )
    assert area["issued_certificate_count"] == 1, (
        f"the area counts one issued certificate only, got {area['issued_certificate_count']}"
    )


def test_certifying_an_application_still_under_review_is_rejected():
    """The APPROVED precondition runs before anything the cascade would do.

    PRD §3.5: "Four preconditions guard it. The application must be in `APPROVED`,
    otherwise `ERR_APPLICATION_NOT_APPROVED`. The acting `X-User-ID` must differ
    from the application's `decided_by_user_id`, otherwise
    `ERR_SEGREGATION_OF_DUTIES` — the operator who certifies may never be the
    reviewer who approved. The parcel's sending area must still be `ACTIVE`,
    otherwise `ERR_SENDING_AREA_NOT_ACTIVE`, which is what makes an `APPROVED`
    application in a closed area permanently uncertifiable. And `allocated_units`
    must be at least one."

    PRD §3.3: "On enrollment the derived ledger fields open at their starting
    values: `remaining_units` equals `baseline_allocation_units`, `severed_units` is
    0, `restricted_acres` is 0, `easement_status` is `NONE`, and `parcel_status` is
    `UNSEVERED`."

    PRD §3.2: "A newly designated sending area opens in `status` `DRAFT` with
    `severed_units_total` and `issued_certificate_count` both at 0."

    Design: Corner/state_machines/certifying_an_application_still_under_review_is_rejected
    """
    set_clock(CLOCK)
    landowner = register_landowner(legal_name="Ridge Farm LLC")
    area = _east_area()
    parcel = enroll_parcel(landowner["id"], area["id"], **CANONICAL_PARCEL)
    application = file_severance(parcel["id"], landowner["id"], CANONICAL_BASELINE_UNITS)
    screened = screen_application(application["id"], REVIEWER_USER_ID)
    assert screened["status"] == "UNDER_REVIEW", (
        f"the application must sit in UNDER_REVIEW, got {screened['status']!r}"
    )

    resp = api_client.certify_severance_application(
        application["id"], make_admin_headers(ADMIN_USER_ID)
    )
    error = validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_APPROVED.value)
    assert error["error_id"] != ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, (
        "an undecided application cannot fail segregation of duties"
    )

    settled = fetch_application(application["id"])
    assert settled["status"] == "UNDER_REVIEW", (
        f"the refused certify leaves the status alone, got {settled['status']!r}"
    )
    assert settled.get("certified_by_user_id") is None, (
        f"the refused certify stamps nobody, got {settled.get('certified_by_user_id')!r}"
    )
    assert settled["allocated_units"] == 0, (
        f"the refused certify grants nothing, got {settled['allocated_units']}"
    )

    _, easement_meta = validate_paginated(
        api_client.list_conservation_easements(ADMIN, params={"sending_parcel_id": parcel["id"]})
    )
    assert easement_meta["total_count"] == 0, (
        f"the refused certify records no easement, got {easement_meta['total_count']}"
    )
    _, cert_meta = validate_paginated(
        api_client.list_certificates(ADMIN, params={"origin_sending_area_id": area["id"]})
    )
    assert cert_meta["total_count"] == 0, (
        f"the refused certify mints no certificate, got {cert_meta['total_count']}"
    )

    settled_parcel = fetch_parcel(parcel["id"])
    assert settled_parcel["severed_units"] == 0, (
        f"the parcel severs nothing, got {settled_parcel['severed_units']}"
    )
    assert settled_parcel["remaining_units"] == CANONICAL_BASELINE_UNITS, (
        f"the parcel keeps its whole baseline, got {settled_parcel['remaining_units']}"
    )
    assert settled_parcel["easement_status"] == "NONE", (
        f"the parcel carries no easement, got {settled_parcel['easement_status']!r}"
    )
    assert settled_parcel["parcel_status"] == "UNSEVERED", (
        f"the parcel stays UNSEVERED, got {settled_parcel['parcel_status']!r}"
    )

    settled_area = fetch_sending_area(area["id"])
    assert settled_area["severed_units_total"] == 0, (
        f"the area counts no severance, got {settled_area['severed_units_total']}"
    )
    assert settled_area["issued_certificate_count"] == 0, (
        f"the area counts no certificate, got {settled_area['issued_certificate_count']}"
    )


def test_intake_branches_on_the_receiving_areas_design_review_flag():
    """The same filing lands in a different state under each area's flag.

    PRD §3.7: "**The intake branch.** A single filing lands in one of two
    different states depending on a configuration flag on the area. When the area
    has `design_review_required` set to true, the application starts `SUBMITTED →
    DESIGN_REVIEW` and must clear a board before it can finalize. When the flag is
    false, it starts `SUBMITTED → DESIGN_APPROVED` and skips the board entirely,
    with `design_review_round` left at 0 and `design_reviewed_by_user_id` left
    unset. Either way the provisional sizing has already run, and `backed_units`,
    `pending_backed_units`, and `allocated_bonus_units` all start at 0."

    PRD §3.7: "First a site tier factor is chosen from `site_acres`: a site of at
    least 10.00 acres takes 1.00, a site of at least 3.00 but under 10.00 acres
    takes 0.90, and anything smaller takes 0.75."

    PRD §3.7: "Second, `base_units` is `site_acres` multiplied by the area's
    `base_density_units_per_acre`, floored to a whole number. Third,
    `max_bonus_units` is the already-floored `base_units` multiplied by the area's
    `max_bonus_pct` and then by the tier factor, floored again."

    PRD §3.7: "`required_backing_units` is then the lesser of
    `requested_bonus_units` and `max_bonus_units` — a developer who asks for more
    density than the area can grant is not rejected at intake, but is only ever
    required to back, and can only ever receive, the area's maximum."

    PRD §3.7: "The provisional variant, used at intake and again on every design
    resubmission, writes `provisional_bonus_units` as the lesser of
    `requested_bonus_units` and half of `max_bonus_units` floored — a release
    fraction of one half."

    PRD §3.7: "A `DesignReviewBoard` actor rules on an application in
    `DESIGN_REVIEW` with a `decision` of `APPROVE`, `REQUIRE_REVISIONS`, or `DENY`
    plus an optional `review_note`; a decision against an application in any other
    state is rejected with `ERR_DESIGN_REVIEW_STATE_INVALID`."

    Design: Corner/state_machines/intake_branches_on_the_receiving_areas_design_review_flag
    """
    developer = register_developer(legal_name="Core Block Partners", neighborhood_code="NB-CORE")
    dev_headers = make_developer_headers(developer["id"])
    area_terms = {
        "neighborhood_code": "NB-CORE",
        "base_density_units_per_acre": 4.00,
        "max_bonus_pct": 0.35,
        "absorption_cap_units": 500,
    }
    review_area = create_active_receiving_area(
        code="RA-REVIEW", name="Core Review District", design_review_required=True, **area_terms
    )
    exempt_area = create_active_receiving_area(
        code="RA-EXEMPT", name="Core Exempt District", design_review_required=False, **area_terms
    )

    filings = {}
    for label, area in (("review", review_area), ("exempt", exempt_area)):
        resp = api_client.create_receiving_site_application(
            create_receiving_site_application_payload(
                developer["id"], area["id"], site_acres=12.00, requested_bonus_units=20,
            ),
            dev_headers,
        )
        filings[label] = validate_success(resp, 201)

    for label, data in filings.items():
        assert_receiving_site_application(data)
        assert data["base_units"] == 48, (
            f"{label}: base_units is floor(12.00 x 4.00) = 48, got {data['base_units']}"
        )
        assert data["max_bonus_units"] == 16, (
            f"{label}: max_bonus_units is floor(48 x 0.35 x 1.00) = 16, got {data['max_bonus_units']}"
        )
        assert data["required_backing_units"] == 16, (
            f"{label}: required backing is capped at the area maximum 16, "
            f"got {data['required_backing_units']}"
        )
        assert data["provisional_bonus_units"] == 8, (
            f"{label}: the provisional figure is floor(16 / 2) = 8, "
            f"got {data['provisional_bonus_units']}"
        )
        for field in ("backed_units", "pending_backed_units", "allocated_bonus_units"):
            assert data[field] == 0, f"{label}: {field} starts at 0, got {data[field]}"

    assert filings["review"]["status"] == "DESIGN_REVIEW", (
        f"a review-required area sends intake to DESIGN_REVIEW, got {filings['review']['status']!r}"
    )
    assert filings["exempt"]["status"] == "DESIGN_APPROVED", (
        f"an exempt area sends intake to DESIGN_APPROVED, got {filings['exempt']['status']!r}"
    )
    assert filings["exempt"]["design_review_round"] == 0, (
        f"an exempt filing leaves the round at 0, got {filings['exempt']['design_review_round']}"
    )
    assert filings["exempt"].get("design_reviewed_by_user_id") is None, (
        "an exempt filing leaves design_reviewed_by_user_id unset, got "
        f"{filings['exempt'].get('design_reviewed_by_user_id')!r}"
    )

    resp = api_client.design_review_decision(
        filings["exempt"]["id"], design_review_payload("APPROVE"),
        make_design_board_headers(DESIGN_BOARD_USER_ID),
    )
    validate_error(resp, ApiErrorId.ERR_DESIGN_REVIEW_STATE_INVALID.value)

    settled = fetch_receiving_site_application(filings["exempt"]["id"])
    assert settled["status"] == "DESIGN_APPROVED", (
        f"the refused decision leaves the status alone, got {settled['status']!r}"
    )
    assert settled.get("design_reviewed_by_user_id") is None, (
        "the refused decision stamps nobody, got "
        f"{settled.get('design_reviewed_by_user_id')!r}"
    )


def test_compliance_sweep_escalates_only_the_cure_whose_deadline_has_passed():
    """The sweep bites strictly after a deadline, and only on that one cure.

    PRD §3.9: "The finding component contributes 0 for `COMPLIANT`, 40 for
    `MINOR_VIOLATION`, and 90 for `MAJOR_VIOLATION`, at a weight of one half. The
    extent component is an acre ratio — `affected_acres` divided by the easement's
    `restricted_acres`, capped at 1 so that damage beyond the restricted area
    cannot push the ratio past whole — expressed as a percentage and taken at a
    weight of three tenths. The history component is the easement's
    `prior_violation_count` multiplied by 25 and capped at 100, taken at a weight
    of two tenths; the count is read as it stands before this inspection increments
    it, so a landowner's first violation carries no history term."

    PRD §3.9: "The rounded score selects a cure band, and the bands are inclusive
    on their lower edge: a score of at least 70.00 gives 30 days, a score of at
    least 45.00 but below 70.00 gives 60 days, and anything lower gives 90 days."

    PRD §3.9: "`cure_deadline` is `inspection_date` advanced by the band's day
    count, and the same deadline is copied onto the easement."

    PRD §3.9: "**Escalation.** Cure deadlines are enforced by an
    administrator-triggered compliance sweep that evaluates every open violation
    against the current logical clock. Every inspection in `CURE_PENDING` whose
    `cure_deadline` is strictly earlier than the clock moves `CURE_PENDING →
    ESCALATED` with `escalated_at` set from the clock, and drives its easement to
    `ESCALATED` from `VIOLATION_NOTICED` or `UNDER_CURE`, incrementing
    `prior_violation_count` again. The comparison is strict: at exactly the
    `cure_deadline` nothing escalates, and only once the clock has moved past it
    does the sweep bite. Certificates remain `FROZEN` and redemptions remain
    `HELD_PENDING_COMPLIANCE` throughout — escalation tightens the record without
    changing the freeze."

    PRD §3.9: "A violation finding moves the easement `COMPLIANT →
    VIOLATION_NOTICED`, or `CURED → VIOLATION_NOTICED` for a repeat offender, and
    sets its `cure_deadline`."

    PRD §3.9: "Second — caused by the first — every certificate whose
    `conservation_easement_id` names this easement and whose `market_status` is
    `HELD` or `UNDER_CONTRACT` moves to `FROZEN`, and any market transaction on
    such a certificate that is still `PROPOSED` moves `PROPOSED → CANCELLED` with
    `reversal_reason` set to the literal `EASEMENT_NONCOMPLIANT`."

    Design: Corner/state_machines/compliance_sweep_escalates_only_the_cure_whose_deadline_has_passed
    """
    set_clock(CLOCK)
    landowner = register_landowner(legal_name="Ridge Farm LLC")
    area = _east_area()
    chain_a = _certify_parcel(landowner, area["id"], CANONICAL_BASELINE_UNITS, apn="APN-A01")
    chain_b = _certify_parcel(
        landowner, area["id"], 10, apn="APN-B01", gross_acres=40.00,
        constrained_acres=0.00, soil_class="LOCAL", existing_dwelling_units=0,
    )
    assert chain_b["easement"]["restricted_acres"] == pytest.approx(40.00, abs=0.01), (
        "the second easement must encumber its whole 40.00 acres, got "
        f"{chain_b['easement']['restricted_acres']}"
    )

    inspection_a = record_inspection(
        chain_a["easement"]["id"], "2026-08-10", "MAJOR_VIOLATION", 12.00, MONITOR_USER_ID
    )
    set_clock("2026-08-20T00:00:00Z")
    inspection_b = record_inspection(
        chain_b["easement"]["id"], "2026-08-20", "MAJOR_VIOLATION", 4.00, MONITOR_USER_ID
    )

    assert_monitoring_inspection(inspection_a)
    assert inspection_a["severity_score"] == pytest.approx(48.60, abs=0.01), (
        "0.5 x 90 plus 0.3 x 12 is 48.60, got "
        f"{inspection_a['severity_score']}"
    )
    assert_same_date(inspection_a["cure_deadline"], "2026-10-09", "inspection A cure_deadline")
    assert inspection_b["severity_score"] == pytest.approx(48.00, abs=0.01), (
        "0.5 x 90 plus 0.3 x 10 is 48.00, got "
        f"{inspection_b['severity_score']}"
    )
    assert_same_date(inspection_b["cure_deadline"], "2026-10-19", "inspection B cure_deadline")
    assert inspection_a["status"] == "CURE_PENDING", (
        f"a violation opens in CURE_PENDING, got {inspection_a['status']!r}"
    )
    assert inspection_b["status"] == "CURE_PENDING", (
        f"a violation opens in CURE_PENDING, got {inspection_b['status']!r}"
    )

    set_clock("2026-10-09T00:00:00Z")
    validate_success(api_client.run_compliance_sweep(ADMIN))

    on_deadline = fetch_inspection(inspection_a["id"])
    assert on_deadline["status"] == "CURE_PENDING", (
        "a sweep landing exactly on the deadline escalates nothing, got "
        f"{on_deadline['status']!r}"
    )
    assert on_deadline.get("escalated_at") is None, (
        f"nothing escalated, so escalated_at stays unset, got {on_deadline.get('escalated_at')!r}"
    )

    set_clock("2026-10-10T00:00:00Z")
    validate_success(api_client.run_compliance_sweep(ADMIN))

    escalated = fetch_inspection(inspection_a["id"])
    assert escalated["status"] == "ESCALATED", (
        f"a sweep past the deadline escalates the cure, got {escalated['status']!r}"
    )
    assert_same_instant(escalated["escalated_at"], "2026-10-10T00:00:00Z", "escalated_at")

    easement_a = fetch_easement(chain_a["easement"]["id"])
    assert easement_a["compliance_status"] == "ESCALATED", (
        f"escalation drives its own easement to ESCALATED, got {easement_a['compliance_status']!r}"
    )

    untouched = fetch_inspection(inspection_b["id"])
    assert untouched["status"] == "CURE_PENDING", (
        "the cure whose deadline is still ahead is left alone, got "
        f"{untouched['status']!r}"
    )
    assert untouched.get("escalated_at") is None, (
        f"the untouched cure has no escalated_at, got {untouched.get('escalated_at')!r}"
    )
    easement_b = fetch_easement(chain_b["easement"]["id"])
    assert easement_b["compliance_status"] == "VIOLATION_NOTICED", (
        "the other easement keeps the posture its own inspection gave it, got "
        f"{easement_b['compliance_status']!r}"
    )

    for label, chain in (("A", chain_a), ("B", chain_b)):
        certificate = fetch_certificate(chain["certificate"]["id"])
        assert certificate["market_status"] == "FROZEN", (
            f"certificate {label} stays FROZEN from its own violation, "
            f"got {certificate['market_status']!r}"
        )


def test_full_retirement_reconciles_the_certificate_easement_and_holder_ledgers():
    """Retiring the whole balance settles the certificate, easement and holder at once.

    PRD §3.6: "**Retirement.** The same set of actors may permanently extinguish
    units from a certificate, supplying `units` and an optional `reason`."

    PRD §3.6: "`units_retired` grows by `units` and `units_remaining` is
    recomputed; when `units_remaining` reaches zero the `lifecycle_status` becomes
    `RETIRED`, and it does so even if redemption also contributed to emptying the
    certificate — retirement outranks redemption when both reduced the same
    certificate to zero."

    PRD §3.6: "A `RETIREMENT` chain-of-title row is appended with no transferee and
    no price, the backing easement's `units_retired` and `units_outstanding` are
    recomputed (leaving `units_issued_total` untouched), the holder's `units_held`
    and `certificates_held_count` are recomputed, and the certificate's `version`
    is incremented."

    PRD §3.6: "Rows carry `seq_no`, a sequence number scoped to a single
    certificate that starts at 1 and increases by exactly one for each row appended
    to that certificate, so the pair of `certificate_id` and `seq_no` is unique."

    PRD §2.11: "For any single party, `units_held` is the sum of `units_remaining`
    across the certificates it holds whose `lifecycle_status` is `ISSUED` or
    `PARTIALLY_REDEEMED`, and `certificates_held_count` is the count of those same
    certificates."

    PRD §3.3: "`remaining_units` is always `baseline_allocation_units` less
    `severed_units`, and `severed_units` is always the sum of `allocated_units`
    over the parcel's severance applications that reached `CERTIFIED`.
    `restricted_acres` on the parcel mirrors the acreage currently encumbered by
    the parcel's conservation easement and stays at 0 until the first
    certification."

    Design: Corner/state_machines/full_retirement_reconciles_the_certificate_easement_and_holder_ledgers
    """
    scenario = setup_certified_severance(
        units=CANONICAL_BASELINE_UNITS, clock=CLOCK, equity_tier="UNDERSERVED",
        neighborhood_code=EAST_NEIGHBORHOOD, area_overrides={"code": EAST_AREA_CODE},
    )
    landowner = scenario["landowner"]
    owner_headers = make_landowner_headers(landowner["id"])
    certificate_id = scenario["certificate"]["id"]
    easement_id = scenario["easement"]["id"]

    resp = api_client.retire_certificate_units(
        certificate_id,
        retire_certificate_payload(
            CANONICAL_BASELINE_UNITS, reason="landowner elects permanent retirement"
        ),
        owner_headers,
    )
    retired = validate_success(resp)
    assert retired["units_retired"] == CANONICAL_BASELINE_UNITS, (
        f"every unit is extinguished, got units_retired {retired['units_retired']}"
    )
    assert retired["units_remaining"] == 0, (
        f"nothing remains after a full retirement, got {retired['units_remaining']}"
    )
    assert retired["lifecycle_status"] == "RETIRED", (
        f"an emptied certificate is RETIRED, got {retired['lifecycle_status']!r}"
    )
    assert retired["market_status"] == "HELD", (
        f"retirement touches only the rights dimension, got {retired['market_status']!r}"
    )

    easement = fetch_easement(easement_id)
    assert easement["units_retired"] == CANONICAL_BASELINE_UNITS, (
        f"the easement records the retirement, got {easement['units_retired']}"
    )
    assert easement["units_outstanding"] == 0, (
        f"no rights remain outstanding against the easement, got {easement['units_outstanding']}"
    )
    assert easement["units_issued_total"] == CANONICAL_BASELINE_UNITS, (
        "issuance history is never rewound by a retirement, got "
        f"{easement['units_issued_total']}"
    )

    holder = fetch_party(landowner["id"])
    assert holder["units_held"] == 0, (
        f"a RETIRED certificate contributes nothing to units_held, got {holder['units_held']}"
    )
    assert holder["certificates_held_count"] == 0, (
        "a RETIRED certificate contributes nothing to certificates_held_count, got "
        f"{holder['certificates_held_count']}"
    )

    rows, meta = validate_paginated(
        api_client.list_certificate_transfers(ADMIN, params={"certificate_id": certificate_id})
    )
    assert meta["total_count"] == 2, (
        f"the issuance and the retirement are two rows, got {meta['total_count']}"
    )
    retirement_rows = [row for row in rows if row["seq_no"] == 2]
    assert len(retirement_rows) == 1, "exactly one row carries seq_no 2"
    row = retirement_rows[0]
    assert_certificate_transfer(row)
    assert row["transfer_type"] == "RETIREMENT", (
        f"the second row is a RETIREMENT, got {row['transfer_type']!r}"
    )
    assert row["units"] == CANONICAL_BASELINE_UNITS, (
        f"the retirement row carries the retired units, got {row['units']}"
    )
    assert row.get("to_party_id") is None, (
        f"a RETIREMENT row has no transferee, got {row.get('to_party_id')!r}"
    )
    assert row.get("price_cents") is None, (
        f"a RETIREMENT row has no price, got {row.get('price_cents')!r}"
    )

    parcel = fetch_parcel(scenario["parcel"]["id"])
    assert parcel["severed_units"] == CANONICAL_BASELINE_UNITS, (
        f"the severance stands, got severed_units {parcel['severed_units']}"
    )
    assert parcel["restricted_acres"] == pytest.approx(100.00, abs=0.01), (
        "retiring rights does not un-preserve land, got restricted_acres "
        f"{parcel['restricted_acres']}"
    )
