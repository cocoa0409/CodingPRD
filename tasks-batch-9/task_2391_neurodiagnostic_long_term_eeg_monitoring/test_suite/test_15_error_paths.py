"""
Error paths: the authentication rung of the rejection ladder, the two
path-identifier 404s, and the guard that protects a package a surgical
conference has already decided upon.

Each probe is otherwise well formed, so the rejection under test is genuinely
the first rung the request reaches.
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    assert_case_tallies,
    assert_fields_null,
    assert_instant_equals,
    assert_storage_value,
    assert_unit_storage,
    constants as c,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import (
    ERR_ALERT_NOT_FOUND,
    ERR_EXPORT_IN_DECIDED_CASE,
    ERR_STUDY_NOT_FOUND,
    ERR_UNAUTHENTICATED,
)
from test_helpers.test_users import (
    COORDINATOR,
    NO_AUTH_HEADERS,
    NURSE,
    TECHNOLOGIST,
    as_epileptologist,
)


def test_read_without_identity_headers_is_rejected_as_unauthenticated(api):
    """A read of an existing unit without identity headers fails at authentication.

    PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of the five declared roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/unauthenticated_read_is_rejected_with_401
    """
    unit = fx.create_unit(api, name="EMU Auth", bed_count=1, storage_quota_gb=500.00)

    response = api.get_unit(unit["id"], NO_AUTH_HEADERS)

    validate_error(response, ERR_UNAUTHENTICATED)


def test_reading_an_unknown_study_returns_study_not_found(api):
    """An authenticated, authorized read of an absent study identifier is a 404.

    PRD §2.6: "Every identifier embedded in the URL path resolves to an existing record, validated left to right, otherwise the 404 matching the first unresolvable segment: `ERR_UNIT_NOT_FOUND`, `ERR_BED_NOT_FOUND`, `ERR_SHIFT_NOT_FOUND`, `ERR_PATIENT_NOT_FOUND`, `ERR_AUTHORIZATION_NOT_FOUND`, `ERR_ADMISSION_NOT_FOUND`, `ERR_TAPER_PLAN_NOT_FOUND`, `ERR_STUDY_NOT_FOUND`, `ERR_ALERT_NOT_FOUND`, `ERR_MARKING_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_EXPORT_NOT_FOUND` or `ERR_CASE_NOT_FOUND`."

    Design: Corner/errors/unknown_study_id_on_read_returns_not_found
    """
    fx.create_unit(api, name="EMU Missing Study", bed_count=1, storage_quota_gb=500.00)

    response = api.get_study(NON_EXISTENT_UUID, TECHNOLOGIST)

    validate_error(response, ERR_STUDY_NOT_FOUND)


def test_recording_an_intervention_on_an_unknown_alert_returns_alert_not_found(api):
    """A well-formed intervention against an absent alert resolves as a 404 first.

    PRD §2.10: "The same precedence applies to writes: the parent's existence is settled before any child-level or business-level rule is evaluated."

    Design: Corner/errors/intervention_on_unknown_alert_returns_not_found
    """
    unit = fx.create_unit(
        api, name="EMU Missing Alert", bed_count=1, storage_quota_gb=500.00
    )

    response = api.record_intervention(
        NON_EXISTENT_UUID,
        f.intervention_payload(
            interventions=[c.INTERVENTION_POSITIONING],
            injury_observed=False,
            rescue_med_given=False,
        ),
        NURSE,
    )

    validate_error(response, ERR_ALERT_NOT_FOUND)

    read_unit = validate_success(api.get_unit(unit["id"], COORDINATOR))
    assert read_unit["late_response_count"] == 0, (
        "a rejected intervention leaves the unit's late_response_count untouched, "
        f"got {read_unit['late_response_count']!r}"
    )


def test_revoking_a_package_a_conference_decided_on_is_refused(api):
    """A delivered package cannot be revoked once its case has been decided.

    PRD §3.9: "Revoking a delivered package carries one extra guard: if any surgical conference case referencing that package has reached `CANDIDATE` or `NON_CANDIDATE`, the revocation is refused with `ERR_EXPORT_IN_DECIDED_CASE`, because the decision was made on that data."

    Design: Corner/errors/revoke_export_in_decided_case_is_rejected
    """
    stay = fx.build_admitted_stay(
        api,
        unit_name="EMU Decided",
        bed_count=1,
        storage_quota_gb=500.00,
        planned_days=2,
        target_event_count=3,
        channel_count=32,
    )
    fx.acquire_and_complete(
        api,
        stay.study_id,
        stay.shift_id,
        from_iso="2026-08-02T00:00:00Z",
        to_iso="2026-08-02T02:00:00Z",
    )
    fx.finalized_report(api, stay.study_id, prelim_at="2026-08-02T12:00:00Z")
    package = fx.delivered_export(
        api,
        stay.study_id,
        include_video=True,
        recipient_center="Metro Surgical Center",
    )

    fx.set_clock(api, "2026-08-06T00:00:00Z")
    case = fx.presented_case(
        api,
        admission_id=stay.admission_id,
        export_id=package["id"],
        presenter_user_id="epi-p",
    )
    fx.cast_ballots(
        api,
        case["id"],
        [
            {
                "voter_user_id": "epi-a",
                "specialty": c.SPECIALTY_EPILEPTOLOGY,
                "vote": c.VOTE_CANDIDATE,
            },
            {
                "voter_user_id": "epi-b",
                "specialty": c.SPECIALTY_NEUROSURGERY,
                "vote": c.VOTE_CANDIDATE,
            },
            {
                "voter_user_id": "epi-c",
                "specialty": c.SPECIALTY_NEURORADIOLOGY,
                "vote": c.VOTE_NON_CANDIDATE,
            },
        ],
    )
    decided = validate_success(api.close_vote(case["id"], as_epileptologist("epi-p")))
    assert decided["status"] == c.CASE_CANDIDATE, (
        f"a candidate majority closes the case as CANDIDATE, got {decided['status']!r}"
    )
    assert_case_tallies(
        decided, candidate_votes=2, non_candidate_votes=1, defer_votes=0
    )
    assert_instant_equals(decided["decision_at"], "2026-08-06T00:00:00Z", "decision_at")

    response = api.revoke_export(package["id"], f.revoke_payload(), COORDINATOR)

    validate_error(response, ERR_EXPORT_IN_DECIDED_CASE)

    unchanged = validate_success(api.get_export(package["id"], COORDINATOR))
    assert unchanged["status"] == c.EXPORT_DELIVERED, (
        f"the refused revocation leaves the package DELIVERED, got {unchanged['status']!r}"
    )
    assert_storage_value(unchanged["package_gb"], 3.84, "package_gb")
    assert_fields_null(unchanged, "revocation_reason")

    unit = validate_success(api.get_unit(stay.unit_id, COORDINATOR))
    assert_unit_storage(unit, storage_used_gb=7.68, storage_pressure_pct=1.54)
