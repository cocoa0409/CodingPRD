"""Gates whose decisive input lives on a different record than the one addressed."""
from test_helpers import (
    ADMIN,
    ANALYST,
    ApiClient,
    ApiErrorId,
    assert_license_dimensions,
    license_version,
    renewal_application_payload,
    reread_license,
    seed_application,
    seed_board_program_nurse,
    seed_breached_agreement,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
)


def _submitted_application_on_a_withdrawn_program(api: ApiClient):
    """An application still sitting at SUBMITTED whose program has been withdrawn."""
    ctx = seed_board_program_nurse(
        api,
        program_overrides={
            "program_code": "OH-BSN-01",
            "program_name": "Buckeye BSN",
            "degree_level": "BSN",
            "nclex_first_time_pass_rate_bp": 8800,
        },
        nurse_overrides={"full_name": "Halima Serrano", "birth_year": 1996,
                         "ssn_last4": "6543"},
    )
    application = seed_application(api, ctx["nurse_id"], ctx["board_id"], ctx["program_id"])
    ctx["application"] = submit_application(api, application["id"])
    ctx["application_id"] = application["id"]
    ctx["program"] = validate_success(
        api.patch_education_program(ctx["program_id"], {"approval_status": "WITHDRAWN"},
                                    ADMIN)
    )
    return ctx


def test_qualification_verification_fails_on_a_withdrawn_education_program(
    api: ApiClient,
):
    """PRD §3.2: "On the examination route, the referenced program must have an
    `approval_status` of `APPROVED`, `PROVISIONAL`, or `PROBATION` — a
    `WITHDRAWN` program fails, as does any program whose `approval_expires_on` is
    not strictly after the logical clock, and either failure yields
    `ERR_PROGRAM_NOT_APPROVED`."

    PRD §3.1: "A change of posture reaches applications retroactively only in a
    limited sense: an application already past qualification verification is
    unaffected, while an application still sitting at `SUBMITTED` will be judged
    against the new posture when it is verified."

    Design: Difficulty/cross_entity_state_dependency/qualification_verification_blocked_by_withdrawn_education_program
    """
    ctx = _submitted_application_on_a_withdrawn_program(api)
    assert ctx["program"]["approval_status"] == "WITHDRAWN"

    response = api.verify_license_application_qualification(ctx["application_id"], ANALYST)

    validate_error(response, ApiErrorId.ERR_PROGRAM_NOT_APPROVED.value)


def test_blocked_verification_leaves_the_application_unscreened_and_uncredentialled(
    api: ApiClient,
):
    """PRD §3.2: "A new application begins at `DRAFT` with `screening_status`
    `NOT_ORDERED`, `deficiency_cycle_count` 0, `board_decision` `NONE`,
    `prior_license_verified` false, an empty `screening_offense_records` array,
    and both `submitted_at` and `decided_at` null."

    PRD §3.2: "A successful verification passes the application through
    `QUALIFICATION_VERIFIED` and out the other side to `SCREENING_IN_PROGRESS`
    within the same request, setting `screening_status` to `REQUESTED` on the way."

    PRD §3.3: "Once an application stands at `APPROVED`, a `LicensureAnalyst`
    mints the credential."

    Design: Difficulty/cross_entity_state_dependency/qualification_verification_blocked_by_withdrawn_education_program
    """
    ctx = _submitted_application_on_a_withdrawn_program(api)

    validate_error(
        api.verify_license_application_qualification(ctx["application_id"], ANALYST),
        ApiErrorId.ERR_PROGRAM_NOT_APPROVED.value,
    )

    application = validate_success(
        api.get_license_application(ctx["application_id"], ANALYST)
    )
    assert application["status"] == "SUBMITTED", (
        f"The rejected verification left the application where it was, got "
        f"{application['status']}"
    )
    assert application["screening_status"] == "NOT_ORDERED", (
        f"No screening was ordered, got {application['screening_status']}"
    )

    credentials, meta = validate_paginated(
        api.list_licenses(ANALYST, params={"nurse_id": ctx["nurse_id"], "limit": 100})
    )
    assert credentials == [], f"No credential may exist for this nurse, got {credentials}"
    assert meta["total_count"] == 0


def _suspended_credential_after_a_broken_agreement(api: ApiClient):
    """A credential suspended by a broken alternative-to-discipline agreement."""
    return seed_breached_agreement(
        api,
        coordinator_user_id="mc-2",
        activation_clock="2026-09-01T00:00:00Z",
        program_overrides={
            "program_code": "OH-BSN-52",
            "program_name": "Sandusky BSN II",
            "degree_level": "BSN",
            "nclex_first_time_pass_rate_bp": 8600,
        },
        nurse_overrides={"full_name": "Bram Achterberg", "birth_year": 1989,
                         "ssn_last4": "7788"},
        complaint_overrides={
            "complainant_type": "SELF_REPORT",
            "violation_category": "SUBSTANCE_USE",
            "incident_date": "2026-07-19T00:00:00Z",
            "employer_custodian_codes": ["MERCY-GEN"],
            "page_count": 18,
            "evidence_overrides": {
                "record_class": "EMPLOYER_PERSONNEL",
                "custodian_code": "MERCY-GEN",
                "hold_start_at": "2026-08-02T00:00:00Z",
                "hold_end_at": "2026-08-25T00:00:00Z",
            },
        },
        start_date="2026-09-01T00:00:00Z",
        end_date="2027-09-01T00:00:00Z",
    )


def test_renewal_creation_on_a_suspended_credential_reports_encumbered(api: ApiClient):
    """PRD §3.4: "Its `encumbrance_status` must be `CLEAR`,
    `INVESTIGATION_PENDING`, or `RESTRICTED`; a `SUSPENDED` or `REVOKED`
    credential cannot be renewed at all, and the attempt is refused with
    `ERR_LICENSE_ENCUMBERED`."

    PRD §2.11: "The credential is not disciplinarily barred from renewal: its
    `encumbrance_status` is `CLEAR`, `INVESTIGATION_PENDING`, or `RESTRICTED`
    when a renewal is created. Otherwise `ERR_LICENSE_ENCUMBERED`."

    PRD §2.8: "Creating a renewal filing requires `expected_license_version` as a
    mandatory input field carrying the `version` of the target credential that
    the client last observed."

    Design: Difficulty/cross_entity_state_dependency/renewal_creation_blocked_by_suspended_license_encumbrance
    """
    ctx = _suspended_credential_after_a_broken_agreement(api)
    credential = reread_license(api, ctx["license_id"])
    assert_license_dimensions(credential, "ACTIVE", "SUSPENDED")

    response = api.create_renewal_application(
        renewal_application_payload(ctx["license_id"], credential["version"],
                                    attested_practice_hours=1200),
        ANALYST,
    )

    validate_error(response, ApiErrorId.ERR_LICENSE_ENCUMBERED.value)


def test_encumbrance_bar_outranks_the_renewability_check_and_writes_nothing(
    api: ApiClient,
):
    """PRD §3.4: "Its `license_status` must be `ACTIVE` or `EXPIRED`, and when
    `EXPIRED` the logical clock must still be at or before `expires_on` plus the
    board's `renewal_grace_period_days`; otherwise the create is refused with
    `ERR_LICENSE_NOT_RENEWABLE`."

    PRD §2.8: "If that value does not equal the credential's current `version`,
    the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    PRD §3.4: "Finally, the credential's `version` is advanced by one."

    Design: Difficulty/cross_entity_state_dependency/renewal_creation_blocked_by_suspended_license_encumbrance
    """
    ctx = _suspended_credential_after_a_broken_agreement(api)
    fresh_version = license_version(api, ctx["license_id"])

    validate_error(
        api.create_renewal_application(
            renewal_application_payload(ctx["license_id"], fresh_version,
                                        attested_practice_hours=1200),
            ANALYST,
        ),
        ApiErrorId.ERR_LICENSE_ENCUMBERED.value,
    )

    filings, meta = validate_paginated(
        api.list_license_renewal_applications(ctx["license_id"], ANALYST,
                                              params={"limit": 100})
    )
    assert filings == [], f"No renewal filing may exist, got {filings}"
    assert meta["total_count"] == 0
    credential = reread_license(api, ctx["license_id"])
    assert credential["version"] == fresh_version, (
        f"A rejected create advances nothing: version moved from {fresh_version} to "
        f"{credential['version']}"
    )
