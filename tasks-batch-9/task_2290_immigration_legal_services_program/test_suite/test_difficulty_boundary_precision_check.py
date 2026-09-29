"""Depth tests for two boundaries whose seams are one unit wide.

The indigency ceiling is a two-decimal percentage compared AFTER rounding, so the
seam is one cent of annual income. The facility rules pair an integer per-date
aggregate compared with ``>=`` against a millisecond instant comparison.
"""

from test_helpers import factories
from test_helpers.api_errors import (
    ERR_FACILITY_LEAD_TIME_NOT_MET,
    ERR_FACILITY_VISIT_SLOTS_EXHAUSTED,
    ERR_INDIGENCY_CEILING_EXCEEDED,
)
from test_helpers.assertions import (
    assert_decimal_equals,
    assert_error,
    assert_fields,
    assert_no_rows,
    assert_row_count,
    created,
    ok,
    only_row,
)
from test_helpers.fixtures import accept_intake, minimal_world, new_client
from test_helpers.test_users import program_director_headers

# ---------------------------------------------------------------------------
# indigency_ceiling_compares_rounded_fpl_percent_one_cent_apart
# ---------------------------------------------------------------------------

# The guideline for a single-person household: $15,080.00 in cents. Exactly
# 200.00 percent of it is 3,016,000 cents.
_HH1_GUIDELINE_CENTS = 1508000
_CEILING_CENTS = 2 * _HH1_GUIDELINE_CENTS


def _setup_indigency_seam(api):
    """Three single-person households straddling the 200.00 percent ceiling.

    The third client is registered at the exact ceiling and its income is raised
    by one cent only AFTER its intake row exists, so the recipe never depends on
    whether the ceiling can refuse an intake creation.
    """
    env = minimal_world(
        api,
        clock="2026-09-01T00:00:00.000Z",
        total_case_slots=20,
        reserved_detained_slots=4,
    )
    director = program_director_headers()

    profiles = (
        ("cA_id", "Client Exact", "1980-03-03", _CEILING_CENTS),
        ("cB_id", "Client RoundsDown", "1981-04-04", 3016075),
        ("cC_id", "Client RoundsUp", "1982-05-05", _CEILING_CENTS),
    )
    for key, name, dob, income in profiles:
        env[key] = new_client(
            env,
            full_name=name,
            preferred_language_code="en",
            country_of_birth_code="PH",
            date_of_birth=dob,
            household_size=1,
            annual_household_income_cents=income,
            confidentiality_consent_scope="PROGRAM_ONLY",
        )

    for intake_key, client_key in (
        ("iA_id", "cA_id"),
        ("iB_id", "cB_id"),
        ("iC_id", "cC_id"),
    ):
        intake = created(
            api.create_intake(
                factories.intake_payload(
                    env[client_key],
                    env["cycle_id"],
                    case_type="NATURALIZATION",
                    detained=False,
                    prior_removal_order=False,
                ),
                headers=director,
            )
        )
        env[intake_key] = intake["id"]

    # One cent across the seam, applied after the intake row exists.
    ok(
        api.update_client(
            env["cC_id"], {"annual_household_income_cents": 3016076}, headers=director
        )
    )
    for key in ("iA_id", "iB_id", "iC_id"):
        ok(api.screen_intake(env[key], headers=env.screener))
    return env


def test_the_ceiling_is_inclusive_and_the_comparison_reads_the_rounded_percent(api):
    """3,016,000 and 3,016,075 cents both report 200.00 and both accept.

    The second income has an exact quotient of 200.004973 percent: an
    implementation that compares the raw quotient refuses it, while half-up
    rounding to two places puts it exactly on the inclusive endpoint.

    Design: Difficulty/boundary_precision_check/indigency_ceiling_compares_rounded_fpl_percent_one_cent_apart
    """
    env = _setup_indigency_seam(api)

    assert_decimal_equals(env.client_row(env["cA_id"])["fpl_percent"], "200.00", 2)
    assert_decimal_equals(env.client_row(env["cB_id"])["fpl_percent"], "200.00", 2)
    assert env.intake(env["iA_id"])["legal_eligibility_verdict"] == "ELIGIBLE"
    assert env.intake(env["iB_id"])["legal_eligibility_verdict"] == "ELIGIBLE"

    for key in ("iA_id", "iB_id"):
        decided = ok(
            api.decide_intake(
                env[key],
                {"decision": "ACCEPT", "decision_reason_code": "ACCEPTED_ON_MERIT"},
                headers=env.supervisor,
            )
        )
        assert decided["status"] == "ACCEPTED"

    assert env.cycle()["general_slots_consumed"] == 2


def test_one_more_cent_rounds_to_200_01_and_the_accept_is_refused(api):
    """3,016,076 cents reports 200.01, which is outside the ceiling.

    NATURALIZATION is not a fee-exempt case type, so the screening records
    INELIGIBLE_INCOME and the accept is refused on financial grounds without
    consuming a slot or minting a matter.

    Design: Difficulty/boundary_precision_check/indigency_ceiling_compares_rounded_fpl_percent_one_cent_apart
    """
    env = _setup_indigency_seam(api)

    assert_decimal_equals(env.client_row(env["cC_id"])["fpl_percent"], "200.01", 2)
    assert env.intake(env["iC_id"])["legal_eligibility_verdict"] == "INELIGIBLE_INCOME"

    for key in ("iA_id", "iB_id"):
        ok(
            api.decide_intake(
                env[key],
                {"decision": "ACCEPT", "decision_reason_code": "ACCEPTED_ON_MERIT"},
                headers=env.supervisor,
            )
        )
    refused = api.decide_intake(
        env["iC_id"],
        {"decision": "ACCEPT", "decision_reason_code": "ACCEPTED_ON_MERIT"},
        headers=env.supervisor,
    )
    assert_error(refused, ERR_INDIGENCY_CEILING_EXCEEDED)

    assert env.intake(env["iC_id"])["status"] == "SCREENED"
    assert_no_rows(
        api.list_matters(params={"intake_id": env["iC_id"]}, headers=env.director)
    )
    assert env.cycle()["general_slots_consumed"] == 2


# ---------------------------------------------------------------------------
# facility_slot_aggregate_and_millisecond_lead_time_both_endpoints
# ---------------------------------------------------------------------------

_LEAD_TIME_BOUNDARY_UTC = "2026-09-03T00:00:00.000Z"
_ONE_MILLISECOND_EARLIER_UTC = "2026-09-02T23:59:59.999Z"


def _setup_facility_visits(api):
    """One detained BOND_HEARING matter and two facilities with tiny slot pools.

    F1 allows exactly one visit per UTC date and demands 48 hours of lead time;
    F0 allows none at all. Neither facility requires an access credential, so the
    credential rule in the same paragraph never fires and the only refusals
    available are the lead-time bound and the per-date aggregate. Three separate
    representatives keep the representative geometry out of the way.
    """
    env = minimal_world(
        api,
        clock="2026-09-01T00:00:00.000Z",
        total_case_slots=20,
        reserved_detained_slots=4,
    )
    director = program_director_headers()

    f1 = created(
        api.create_facility(
            factories.facility_payload(
                name="El Paso Service Processing Center",
                jurisdiction_code="TX-ELP",
                visit_lead_time_hours=48,
                max_daily_visit_slots=1,
                expedited_filing_days=30,
                access_credential_required=False,
            ),
            headers=director,
        )
    )
    f0 = created(
        api.create_facility(
            factories.facility_payload(
                name="Eloy Detention Annex",
                jurisdiction_code="AZ-ELO",
                visit_lead_time_hours=24,
                max_daily_visit_slots=0,
                expedited_filing_days=30,
                access_credential_required=False,
            ),
            headers=director,
        )
    )

    for index in (1, 2, 3):
        rep = created(
            api.create_representative(
                factories.staff_attorney_payload(
                    full_name="Visitor Attorney {0}".format(index),
                    languages=["en"],
                    max_case_load=10,
                    max_supervisees=4,
                ),
                headers=director,
            )
        )
        env["rep_v{0}_id".format(index)] = rep["id"]

    client_id = new_client(
        env,
        full_name="Amara Nwosu",
        preferred_language_code="en",
        country_of_birth_code="NG",
        date_of_birth="1990-02-11",
        household_size=3,
        annual_household_income_cents=1200000,
        confidentiality_consent_scope="PROGRAM_ONLY",
    )
    matter = accept_intake(
        env,
        client_id,
        case_type="BOND_HEARING",
        detained=True,
        decision_reason_code="ACCEPTED_DETAINED_PRIORITY",
        facility_id=f1["id"],
    )
    env.set(
        client_id=client_id,
        matter_id=matter["id"],
        f1_id=f1["id"],
        f0_id=f0["id"],
    )
    return env


def _visit_payload(env, facility_id, rep_key, starts, ends, location_code, **overrides):
    return factories.event_payload(
        env["matter_id"],
        event_type="FACILITY_VISIT",
        starts_at_utc=starts,
        ends_at_utc=ends,
        location_code=location_code,
        facility_id=facility_id,
        assigned_representative_id=env[rep_key],
        **overrides
    )


def test_the_per_date_aggregate_refuses_at_or_above_the_integer_ceiling(api):
    """One visit fills F1's single daily seat, and F0's ceiling of 0 refuses its first.

    The second attempt is thirteen hours clear of the first, so no interval
    geometry objects -- only the same-UTC-date count does. F0 is the degenerate
    end of the same comparison: the count of 0 is already at the ceiling of 0, so
    a facility with no seats never books.

    Design: Difficulty/boundary_precision_check/facility_slot_aggregate_and_millisecond_lead_time_both_endpoints
    """
    env = _setup_facility_visits(api)

    booked = created(
        api.create_event(
            _visit_payload(
                env,
                env["f1_id"],
                "rep_v1_id",
                _LEAD_TIME_BOUNDARY_UTC,
                "2026-09-03T01:00:00.000Z",
                "ELPFAC",
            ),
            headers=env.director,
        )
    )
    assert_fields(
        booked,
        status="SCHEDULED",
        travel_buffer_minutes=90,
        reschedule_count=0,
        coverage_gap_flag=False,
    )

    same_date = api.create_event(
        _visit_payload(
            env,
            env["f1_id"],
            "rep_v2_id",
            "2026-09-03T14:00:00.000Z",
            "2026-09-03T15:00:00.000Z",
            "ELPFAC",
        ),
        headers=env.director,
    )
    assert_error(same_date, ERR_FACILITY_VISIT_SLOTS_EXHAUSTED)

    zero_seats = api.create_event(
        _visit_payload(
            env,
            env["f0_id"],
            "rep_v2_id",
            "2026-09-05T09:00:00.000Z",
            "2026-09-05T10:00:00.000Z",
            "ELOYFAC",
        ),
        headers=env.director,
    )
    assert_error(zero_seats, ERR_FACILITY_VISIT_SLOTS_EXHAUSTED)

    assert_row_count(api.list_events(params={"facility_id": env["f0_id"]},
                                     headers=env.director), 0)


def test_the_lead_time_bound_is_inclusive_to_the_millisecond(api):
    """Exactly 48 hours out books; one millisecond earlier is refused.

    The refused candidate waives the client scan and belongs to a third
    representative on a date with a free facility seat, so the lead-time rule is
    the only thing standing between it and a 201 -- and it runs before the
    conflict scan, so the 422 is what surfaces.

    Design: Difficulty/boundary_precision_check/facility_slot_aggregate_and_millisecond_lead_time_both_endpoints
    """
    env = _setup_facility_visits(api)

    created(
        api.create_event(
            _visit_payload(
                env,
                env["f1_id"],
                "rep_v1_id",
                _LEAD_TIME_BOUNDARY_UTC,
                "2026-09-03T01:00:00.000Z",
                "ELPFAC",
            ),
            headers=env.director,
        )
    )

    too_early = api.create_event(
        _visit_payload(
            env,
            env["f1_id"],
            "rep_v3_id",
            _ONE_MILLISECOND_EARLIER_UTC,
            "2026-09-03T00:59:59.999Z",
            "ELPFAC",
            client_conflict_waived=True,
        ),
        headers=env.director,
    )
    assert_error(too_early, ERR_FACILITY_LEAD_TIME_NOT_MET)

    surviving = only_row(
        api.list_events(params={"facility_id": env["f1_id"]}, headers=env.director)
    )
    assert surviving["starts_at_utc"] == _LEAD_TIME_BOUNDARY_UTC
