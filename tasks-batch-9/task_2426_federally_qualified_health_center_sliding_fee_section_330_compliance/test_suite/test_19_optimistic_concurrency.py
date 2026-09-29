"""The two version-pinned writes, and the grantee counter that both of them read."""

from test_helpers import (
    ADMIN,
    PROJECT_OFFICER,
    REP,
    TWO_BAND_LADDER,
    ApiErrorId,
    adopt_fee_schedule_payload,
    api_client,
    create_income_verification_payload,
    make_board_chair_headers,
    refresh_fee_schedule,
    refresh_health_center,
    refresh_patient,
    seed_poverty_guidelines,
    setup_baseline_service,
    setup_baseline_site,
    setup_board_seat,
    setup_boot_core,
    setup_draft_fee_schedule,
    setup_grantee,
    setup_income_verification,
    setup_patient,
    validate_error,
    validate_paginated,
    validate_success,
)

CORNER_2026_GUIDELINE = ((2026, 1620000, 570000),)


def test_a_second_verification_must_carry_the_version_the_first_one_produced():
    """The guard is version-based, so the refreshed version admits the same submission.

    PRD 2.11: "Submitting an income verification under a patient — `POST
    /patients/{id}/income-verifications` — requires `expected_patient_version` in the
    body, carrying the `version` the client last observed on that `Patient`. If
    `expected_patient_version` does not equal the patient's current `version`, the
    submission is rejected with `ERR_STALE_PATIENT_VERSION` (HTTP 412)."

    PRD 3.4: "its `expires_at` is set to exactly 365 days after `effective_date` — making
    the verification's closed window run from `effective_date` through `expires_at`
    inclusive — and the patient's `version` increments by one."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_patient_version_on_income_verification_create_rejected
    """
    setup_boot_core()
    patient = setup_patient(mrn="MRN-C01", full_name="Val Osei", household_size=1)
    assert patient["version"] == 1
    setup_income_verification(
        patient,
        declared_annual_income_cents=1000000,
        household_size=1,
        documentation_type="TAX_RETURN",
        effective_date="2026-03-01T00:00:00Z",
    )
    after_first = refresh_patient(patient["id"])
    assert after_first["version"] == 2, (
        f"the first submission moved the patient to version 2, got {after_first['version']}"
    )

    second_body = create_income_verification_payload(
        1,
        declared_annual_income_cents=1100000,
        household_size=1,
        documentation_type="PAY_STUBS",
        effective_date="2026-04-01T00:00:00Z",
    )
    validate_error(
        api_client.create_income_verification(patient["id"], second_body, REP),
        ApiErrorId.ERR_STALE_PATIENT_VERSION.value,
        412,
    )
    _, meta = validate_paginated(
        api_client.list_income_verifications(REP, {"patient_id": patient["id"]})
    )
    assert meta["total_count"] == 1, (
        "the stale submission stored nothing, so only the first row exists"
    )

    accepted = validate_success(
        api_client.create_income_verification(
            patient["id"],
            create_income_verification_payload(
                after_first["version"],
                declared_annual_income_cents=1100000,
                household_size=1,
                documentation_type="PAY_STUBS",
                effective_date="2026-04-01T00:00:00Z",
            ),
            REP,
        ),
        201,
    )
    assert accepted["status"] == "SUBMITTED"
    assert refresh_patient(patient["id"])["version"] == 3, (
        "the accepted submission is the patient's third mutation"
    )


def test_a_site_suspension_between_the_read_and_the_vote_defeats_the_adoption():
    """Nothing about the schedule changed; the grantee moved underneath the chair.

    PRD 2.11: "Adopting a fee schedule — `POST /fee-schedules/{id}/adopt` — requires
    `expected_health_center_version` in the body, carrying the `version` the client last
    observed on that schedule's `HealthCenter`. If it does not equal the grantee's current
    `version`, the adoption is rejected with `ERR_STALE_HEALTH_CENTER_VERSION` (HTTP
    412)."

    PRD 3.1: "A `ProjectOfficer` may take an in-scope site out of service after an
    operational visit, moving it `IN_SCOPE → SUSPENDED`; this recomputes the grantee's
    `in_scope_site_count`, recomputes `governance_posture` (because, as section 3.2
    explains, a patient board seat is only qualified by an encounter at an in-scope site)
    and increments the grantee's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_health_center_version_on_fee_schedule_adopt_rejected
    """
    seed_poverty_guidelines(CORNER_2026_GUIDELINE)
    grantee = setup_grantee(
        legal_name="Corner Community Health",
        grant_number="H80CS00500",
        pps_base_rate_cents=20000,
    )
    site = setup_baseline_site(grantee["id"], site_name="Corner Clinic")
    setup_baseline_service(grantee["id"])
    chair = setup_board_seat(grantee["id"])
    draft = setup_draft_fee_schedule(
        grantee["id"],
        fpg_year=2026,
        effective_start="2026-01-01T00:00:00Z",
        effective_end="2028-01-01T00:00:00Z",
        nominal_fee_cents=2500,
        ladder=TWO_BAND_LADDER,
    )
    chair_headers = make_board_chair_headers(chair["id"])
    observed = validate_success(
        api_client.get_health_center(grantee["id"], chair_headers)
    )
    assert observed["version"] == 4, (
        f"the chair's read predates the suspension, got version {observed['version']}"
    )

    validate_success(api_client.suspend_service_site(site["id"], PROJECT_OFFICER))
    assert refresh_health_center(grantee["id"])["version"] == 5

    validate_error(
        api_client.adopt_fee_schedule(
            draft["fee_schedule"]["id"],
            adopt_fee_schedule_payload(observed["version"]),
            chair_headers,
        ),
        ApiErrorId.ERR_STALE_HEALTH_CENTER_VERSION.value,
        412,
    )

    unadopted = refresh_fee_schedule(draft["fee_schedule"]["id"])
    assert unadopted["status"] == "DRAFT"
    assert unadopted["adopted_at"] is None
    assert refresh_health_center(grantee["id"])["in_scope_site_count"] == 0, (
        "the suspended site left the scope count, which is what moved the version"
    )


def test_each_scope_and_governance_write_advances_the_grantee_by_exactly_one():
    """Writes routed through a child resource still count as grantee mutations.

    PRD 2.4: "- `version` (integer): a counter that starts at 1 on creation and
    increments by exactly 1 on every mutation of the row. Recomputation of a derived field
    counts as a mutation: when a grantee's counters, postures or receivable are
    recalculated, its `updated_at` is refreshed and its `version` increments, even though
    no client supplied a value."

    PRD 3.1: "The same officer may reverse it, moving the site `SUSPENDED → IN_SCOPE`,
    which re-stamps `in_scope_since` with the logical clock and again recomputes
    `in_scope_site_count` and `governance_posture` with a `version` increment."

    PRD 3.1: "Locking sets `scope_baseline_locked` to true and increments the grantee's
    `version` by one."

    Design: Corner/cross_cutting_complexity_layers/health_center_version_increments_on_every_scope_and_governance_write
    """
    ctx = setup_boot_core()
    assert refresh_health_center(ctx["health_center_id"])["version"] == 5, (
        "registration, the site, the service, the seating and the adoption are five writes"
    )

    validate_success(api_client.suspend_service_site(ctx["site_id"], PROJECT_OFFICER))
    assert refresh_health_center(ctx["health_center_id"])["version"] == 6

    validate_success(api_client.reinstate_service_site(ctx["site_id"], PROJECT_OFFICER))
    assert refresh_health_center(ctx["health_center_id"])["version"] == 7

    locked = validate_success(
        api_client.lock_scope_baseline(ctx["health_center_id"], ADMIN)
    )
    assert locked["version"] == 8, (
        f"the lock is the eighth mutation, got {locked['version']}"
    )
    assert locked["scope_baseline_locked"] is True
    assert locked["in_scope_site_count"] == 1, (
        "the reinstated site is back in the scope count"
    )
