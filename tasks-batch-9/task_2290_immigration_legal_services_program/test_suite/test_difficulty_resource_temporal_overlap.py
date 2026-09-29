"""Depth tests for two calendar resources that use opposite interval arithmetic.

The representative resource is half-open and carries a travel buffer that depends
on the location pair; the client resource is fully closed, carries no buffer and
spans every matter of the client. The same touching pair of instants is therefore
legal on one resource and illegal on the other.
"""

from test_helpers import factories
from test_helpers.api_errors import (
    ERR_CLIENT_CALENDAR_CONFLICT,
    ERR_REPRESENTATIVE_CALENDAR_CONFLICT,
)
from test_helpers.assertions import (
    assert_error,
    assert_fields,
    assert_row_count,
    created,
)
from test_helpers.fixtures import accept_intake, minimal_world, new_client

# ---------------------------------------------------------------------------
# representative_half_open_window_with_location_dependent_travel_buffer
# ---------------------------------------------------------------------------

_ANCHOR_END_UTC = "2026-09-10T11:00:00.000Z"
_BUFFERED_END_UTC = "2026-09-10T12:00:00.000Z"
_ONE_MS_INSIDE_UTC = "2026-09-10T11:59:59.999Z"


def _setup_contended_representative(api):
    """Two clients, one representative, and an INDIVIDUAL_HEARING anchor at EOIRA.

    The two matters belong to DIFFERENT clients so the client geometry cannot
    mask the representative geometry, and no candidate is a FACILITY_VISIT so the
    lead-time and slot rules never engage.
    """
    env = minimal_world(
        api,
        clock="2026-09-01T00:00:00.000Z",
        total_case_slots=20,
        reserved_detained_slots=4,
    )
    rep_a = created(
        api.create_representative(
            factories.staff_attorney_payload(
                full_name="Ada Okafor",
                languages=["en"],
                max_case_load=12,
                max_supervisees=3,
            ),
            headers=env.director,
        )
    )

    c1 = new_client(
        env,
        full_name="Marta Reyes",
        preferred_language_code="en",
        country_of_birth_code="MX",
        date_of_birth="1983-11-11",
        household_size=2,
        annual_household_income_cents=2100000,
        confidentiality_consent_scope="PROGRAM_ONLY",
    )
    c2 = new_client(
        env,
        full_name="Yusuf Kaya",
        preferred_language_code="en",
        country_of_birth_code="TR",
        date_of_birth="1984-12-12",
        household_size=1,
        annual_household_income_cents=1900000,
        confidentiality_consent_scope="PROGRAM_ONLY",
    )
    m1 = accept_intake(env, c1, case_type="REMOVAL_DEFENSE_OTHER", detained=False)
    m2 = accept_intake(env, c2, case_type="ADJUSTMENT_OF_STATUS", detained=False)

    anchor = created(
        api.create_event(
            factories.event_payload(
                m1["id"],
                event_type="INDIVIDUAL_HEARING",
                starts_at_utc="2026-09-10T09:00:00.000Z",
                ends_at_utc=_ANCHOR_END_UTC,
                location_code="EOIRA",
                assigned_representative_id=rep_a["id"],
            ),
            headers=env.director,
        )
    )
    env.set(
        c1_id=c1,
        c2_id=c2,
        m1_id=m1["id"],
        m2_id=m2["id"],
        rep_a_id=rep_a["id"],
        x_event_id=anchor["id"],
    )
    return env


def _biometrics(env, starts, ends, location_code, **overrides):
    return factories.event_payload(
        env["m2_id"],
        event_type="BIOMETRICS",
        starts_at_utc=starts,
        ends_at_utc=ends,
        location_code=location_code,
        assigned_representative_id=env["rep_a_id"],
        **overrides
    )


def test_the_buffered_end_is_exclusive_and_one_millisecond_earlier_conflicts(api):
    """A different location adds the EXISTING event's 60-minute buffer, ending at 12:00.

    Starting exactly at the buffered end books, because the representative
    comparison is half-open. One millisecond earlier trips it -- and must report
    the representative conflict even though that same interval also collides with
    the second client's own newly booked 12:00-12:30 event, because the
    representative geometry is evaluated first.

    Design: Difficulty/resource_temporal_overlap/representative_half_open_window_with_location_dependent_travel_buffer
    """
    env = _setup_contended_representative(api)

    assert_fields(
        env.event(env["x_event_id"]), status="SCHEDULED", travel_buffer_minutes=60
    )

    booked = created(
        api.create_event(
            _biometrics(env, _BUFFERED_END_UTC, "2026-09-10T12:30:00.000Z", "USCISB"),
            headers=env.director,
        )
    )
    assert_fields(booked, status="SCHEDULED", travel_buffer_minutes=30)

    refused = api.create_event(
        _biometrics(env, _ONE_MS_INSIDE_UTC, "2026-09-10T12:29:59.999Z", "USCISB"),
        headers=env.director,
    )
    assert_error(refused, ERR_REPRESENTATIVE_CALENDAR_CONFLICT)

    assert_row_count(
        api.list_events(
            params={"assigned_representative_id": env["rep_a_id"]},
            headers=env.director,
        ),
        2,
    )


def test_the_same_location_collapses_the_buffer_to_zero(api):
    """At EOIRA the anchor's own end instant is free, so 11:00 books.

    Nothing but the location_code differs from the interval that was refused a
    millisecond inside the buffered window: a representative already standing at
    the location needs no travel time.

    Design: Difficulty/resource_temporal_overlap/representative_half_open_window_with_location_dependent_travel_buffer
    """
    env = _setup_contended_representative(api)

    created(
        api.create_event(
            _biometrics(env, _BUFFERED_END_UTC, "2026-09-10T12:30:00.000Z", "USCISB"),
            headers=env.director,
        )
    )
    same_location = created(
        api.create_event(
            _biometrics(env, _ANCHOR_END_UTC, "2026-09-10T11:30:00.000Z", "EOIRA"),
            headers=env.director,
        )
    )
    assert_fields(same_location, status="SCHEDULED", travel_buffer_minutes=30)

    assert_row_count(
        api.list_events(
            params={"assigned_representative_id": env["rep_a_id"]},
            headers=env.director,
        ),
        3,
    )
    assert_row_count(
        api.list_events(params={"matter_id": env["m2_id"]}, headers=env.director), 2
    )


# ---------------------------------------------------------------------------
# client_closed_interval_across_matters_with_filing_deadline_exemption
# ---------------------------------------------------------------------------

_INTERVIEW_END_UTC = "2026-09-20T11:00:00.000Z"


def _setup_one_client_two_matters(api):
    """One client with two matters and an ASYLUM_INTERVIEW anchor on the first.

    The anchor belongs to rep_a and every candidate to rep_b, so the
    representative geometry is silent throughout and each outcome is attributable
    to the client geometry alone.
    """
    env = minimal_world(
        api,
        clock="2026-09-01T00:00:00.000Z",
        total_case_slots=20,
        reserved_detained_slots=4,
    )
    reps = {}
    for key, name in (("rep_a_id", "Ada Okafor"), ("rep_b_id", "Bram Visser")):
        row = created(
            api.create_representative(
                factories.staff_attorney_payload(
                    full_name=name,
                    languages=["en"],
                    max_case_load=12,
                    max_supervisees=3,
                ),
                headers=env.director,
            )
        )
        reps[key] = row["id"]

    client_id = new_client(
        env,
        full_name="Marta Reyes",
        preferred_language_code="en",
        country_of_birth_code="MX",
        date_of_birth="1983-11-11",
        household_size=2,
        annual_household_income_cents=2100000,
        confidentiality_consent_scope="PROGRAM_ONLY",
    )
    m1 = accept_intake(
        env,
        client_id,
        case_type="ASYLUM_AFFIRMATIVE",
        detained=False,
        one_year_bar_applies=False,
    )
    m2 = accept_intake(env, client_id, case_type="ADJUSTMENT_OF_STATUS", detained=False)

    anchor = created(
        api.create_event(
            factories.event_payload(
                m1["id"],
                event_type="ASYLUM_INTERVIEW",
                starts_at_utc="2026-09-20T09:00:00.000Z",
                ends_at_utc=_INTERVIEW_END_UTC,
                location_code="USCISASO",
                assigned_representative_id=reps["rep_a_id"],
            ),
            headers=env.director,
        )
    )
    env.set(
        client_id=client_id,
        m1_id=m1["id"],
        m2_id=m2["id"],
        x_event_id=anchor["id"],
        **reps
    )
    return env


def _touching_biometrics(env, **overrides):
    return factories.event_payload(
        env["m2_id"],
        event_type="BIOMETRICS",
        starts_at_utc=_INTERVIEW_END_UTC,
        ends_at_utc="2026-09-20T11:30:00.000Z",
        location_code="USCISB",
        assigned_representative_id=env["rep_b_id"],
        **overrides
    )


def test_the_client_interval_is_closed_at_both_ends_and_the_waiver_reopens_it(api):
    """Starting exactly when the client's interview ends conflicts across matters.

    This is the identical touching pair the half-open representative geometry
    accepts, and the two events sit on different matters of the same client, so
    only a client scan that spans matters and includes its endpoints reports it.
    The byte-identical interval then books once client_conflict_waived is true.

    Design: Difficulty/resource_temporal_overlap/client_closed_interval_across_matters_with_filing_deadline_exemption
    """
    env = _setup_one_client_two_matters(api)

    assert_fields(
        env.event(env["x_event_id"]), status="SCHEDULED", travel_buffer_minutes=45
    )

    refused = api.create_event(_touching_biometrics(env), headers=env.director)
    assert_error(refused, ERR_CLIENT_CALENDAR_CONFLICT)

    waived = created(
        api.create_event(
            _touching_biometrics(env, client_conflict_waived=True),
            headers=env.director,
        )
    )
    assert_fields(
        waived,
        status="SCHEDULED",
        client_conflict_waived=True,
        travel_buffer_minutes=30,
    )

    assert_row_count(
        api.list_events(params={"matter_id": env["m2_id"]}, headers=env.director), 1
    )
    assert_row_count(
        api.list_events(params={"matter_id": env["m1_id"]}, headers=env.director), 1
    )


def test_a_filing_deadline_may_sit_wholly_inside_the_clients_own_hearing(api):
    """FILING_DEADLINE is exempt from the client geometry without any waiver.

    The candidate lies entirely inside the 09:00-11:00 interview of the same
    client, which no other event type could do unwaived, and it carries no
    representative at all -- the one event type allowed to omit one -- so the row
    lands with a zero travel buffer and the waiver still false.

    Design: Difficulty/resource_temporal_overlap/client_closed_interval_across_matters_with_filing_deadline_exemption
    """
    env = _setup_one_client_two_matters(api)

    deadline = created(
        api.create_event(
            factories.event_payload(
                env["m2_id"],
                event_type="FILING_DEADLINE",
                starts_at_utc="2026-09-20T10:00:00.000Z",
                ends_at_utc="2026-09-20T10:30:00.000Z",
                location_code="MAIL",
            ),
            headers=env.director,
        )
    )
    assert_fields(
        deadline,
        status="SCHEDULED",
        travel_buffer_minutes=0,
        client_conflict_waived=False,
        assigned_representative_id=None,
    )

    assert_row_count(
        api.list_events(params={"matter_id": env["m2_id"]}, headers=env.director), 1
    )
