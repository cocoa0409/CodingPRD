"""Medical screening arithmetic, the two independent athlete dimensions and the
precedence of the safety gate over eligibility arithmetic."""
from test_helpers import (
    ApiErrorId,
    api_client,
    TEST_USERS,
    MEDICAL_DIRECTOR_USER_ID,
    create_athlete,
    create_entry,
    create_qualifying_result,
    create_sport_event,
    get_athlete,
    get_event,
    make_medical_director_headers,
    medical_screening_payload,
    pay_fees,
    setup_open_edition,
    setup_open_edition_high_contact,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["games_admin_headers"]
OFFICER = TEST_USERS["registration_officer_headers"]
MEDICAL = make_medical_director_headers(MEDICAL_DIRECTOR_USER_ID)

DOB_AGE_68 = "1958-06-15"   # 68 years old on an age_reference_date of 2026-12-31
DOB_AGE_65 = "1961-04-10"   # 65 on the same reference date
DOB_AGE_60 = "1966-03-02"   # 60 on the same reference date


def _screen(athlete_id: str, **vitals):
    return api_client.create_medical_screening(
        medical_screening_payload(athlete_id, MEDICAL_DIRECTOR_USER_ID, **vitals), MEDICAL
    )


def test_risk_score_sums_four_capped_terms_and_lands_in_the_hold_band():
    """PRD §3.4: "`contact_sport_count` snapshots how much high-contact competition the
    athlete is signed up for: it counts the athlete's entries in `SUBMITTED`,
    `UNDER_REVIEW`, `REVISION_REQUESTED`, `WAITLISTED` or `ACCEPTED` whose event belongs
    to a sport whose `contact_class` is `HIGH`."
    PRD §3.4: "**Age points** take the athlete's `age_at_reference` — always the
    reference-date age, whatever the edition's `age_basis` says — subtract the age floor
    of 55, treat any negative result as zero, multiply by one and a half points per
    year, and cap the term at 30 points, which is reached at 75 years of age."
    PRD §3.4: "**Blood-pressure points** contribute nothing while `systolic_bp` is below
    130, contribute 12 points once `systolic_bp` is at least 130 and still below 150,
    and contribute 25 points once `systolic_bp` reaches 150."
    PRD §3.4: "**Heart-rate points** take `resting_hr`, subtract the floor of 70 bpm,
    treat any negative result as zero, and multiply by four tenths of a point per bpm,
    with no cap."
    PRD §3.4: "**Load points** multiply `contact_sport_count` by 7 points per
    high-contact entry and cap the term at 20 points, so a third and fourth high-contact
    entry add nothing beyond the third's partial contribution to the ceiling."
    PRD §3.4: "`recommendation` follows directly from `risk_score`: below 25.0 it is
    `CLEARED`; from 25.0 up to but not including 60.0 it is `CLEARED_WITH_RESTRICTION`;
    at 60.0 and above it is `HOLD_PENDING_PHYSICIAN_REVIEW`."
    PRD §3.4: "A `HOLD_PENDING_PHYSICIAN_REVIEW` recommendation moves the athlete
    `NOT_SCREENED` → `SCREENED_HOLD` and pulls back everything: every entry of that
    athlete currently `ACCEPTED`, regardless of contact class, moves `ACCEPTED` →
    `MEDICAL_HOLD`, and each such move decrements that event's `accepted_entry_count` by
    one, increments that event's `available_slots` by one, and drives the event to
    `UNDERSUBSCRIBED` when `accepted_entry_count` falls below `min_entries_to_stage`."

    A 68-year-old with two high-contact entries, `systolic_bp` 152 and
    `resting_hr` 88 and no cardiac history scores exactly 65.7: age points
    min(30, (68 - 55) x 1.5) = 19.5, blood-pressure points 25 for reaching 150,
    heart-rate points (88 - 70) x 0.4 = 7.2 and load points min(20, 2 x 7) = 14,
    multiplied by 1.0.  At 60.0 and above the recommendation is
    `HOLD_PENDING_PHYSICIAN_REVIEW`, which drives the athlete to
    `SCREENED_HOLD` while the registration dimension is untouched.

    Design: Difficulty/combinatorial_formula/medical_risk_score_nested_min_max_with_tiered_bp_branch
    """
    ctx = setup_open_edition_high_contact(event={"age_group_code": "65-69"})
    second_event = create_sport_event(
        ctx["sport"]["id"], ctx["edition"]["id"],
        event_code="BBFULL", age_group_code="65-69", entry_fee_cents=4000,
    )
    athlete = create_athlete(ctx["edition"]["id"], date_of_birth=DOB_AGE_68)
    create_entry(athlete["id"], ctx["event"]["id"])
    create_entry(athlete["id"], second_event["id"])

    screening = validate_success(
        _screen(athlete["id"], systolic_bp=152, resting_hr=88, prior_cardiac_event=False),
        expected_status=201,
    )

    assert screening["contact_sport_count"] == 2
    assert float(screening["risk_score"]) == 65.7
    assert screening["recommendation"] == "HOLD_PENDING_PHYSICIAN_REVIEW"
    after = get_athlete(athlete["id"])
    assert after["medical_status"] == "SCREENED_HOLD"
    assert after["registration_status"] == "PENDING_PAYMENT"


def test_load_points_are_capped_at_twenty_however_many_high_contact_entries():
    """PRD §3.4: "`contact_sport_count` snapshots how much high-contact competition the
    athlete is signed up for: it counts the athlete's entries in `SUBMITTED`,
    `UNDER_REVIEW`, `REVISION_REQUESTED`, `WAITLISTED` or `ACCEPTED` whose event belongs
    to a sport whose `contact_class` is `HIGH`."
    PRD §3.4: "**Age points** take the athlete's `age_at_reference` — always the
    reference-date age, whatever the edition's `age_basis` says — subtract the age floor
    of 55, treat any negative result as zero, multiply by one and a half points per
    year, and cap the term at 30 points, which is reached at 75 years of age."
    PRD §3.4: "**Blood-pressure points** contribute nothing while `systolic_bp` is below
    130, contribute 12 points once `systolic_bp` is at least 130 and still below 150,
    and contribute 25 points once `systolic_bp` reaches 150."
    PRD §3.4: "**Heart-rate points** take `resting_hr`, subtract the floor of 70 bpm,
    treat any negative result as zero, and multiply by four tenths of a point per bpm,
    with no cap."
    PRD §3.4: "**Load points** multiply `contact_sport_count` by 7 points per
    high-contact entry and cap the term at 20 points, so a third and fourth high-contact
    entry add nothing beyond the third's partial contribution to the ceiling."
    PRD §3.4: "`recommendation` follows directly from `risk_score`: below 25.0 it is
    `CLEARED`; from 25.0 up to but not including 60.0 it is `CLEARED_WITH_RESTRICTION`;
    at 60.0 and above it is `HOLD_PENDING_PHYSICIAN_REVIEW`."

    Load points are `contact_sport_count` x 7 capped at 20, so a third
    high-contact entry adds only the remainder up to the ceiling.  A 60-year-old
    with three high-contact entries, `systolic_bp` 120 and `resting_hr` 70 scores
    7.5 age points, 0 blood-pressure points, 0 heart-rate points and 20 load
    points — 27.5, not the 28.5 an uncapped third entry would give.

    Design: Difficulty/combinatorial_formula/medical_risk_score_nested_min_max_with_tiered_bp_branch
    """
    ctx = setup_open_edition_high_contact()
    athlete = create_athlete(ctx["edition"]["id"], date_of_birth=DOB_AGE_60)
    create_entry(athlete["id"], ctx["event"]["id"])
    for code in ("BBFULL", "BBHALF"):
        event = create_sport_event(
            ctx["sport"]["id"], ctx["edition"]["id"], event_code=code, entry_fee_cents=4000
        )
        create_entry(athlete["id"], event["id"])

    screening = validate_success(
        _screen(athlete["id"], systolic_bp=120, resting_hr=70, prior_cardiac_event=False),
        expected_status=201,
    )

    assert screening["contact_sport_count"] == 3
    assert float(screening["risk_score"]) == 27.5
    assert screening["recommendation"] == "CLEARED_WITH_RESTRICTION"


def test_cardiac_history_multiplies_the_summed_terms_before_the_rounding():
    """PRD §3.4: "The four terms are summed, and the sum is multiplied by 1.6 when
    `prior_cardiac_event` is true and by 1.0 when it is false."
    PRD §3.4: "That product is then clamped so it can never exceed 100.0 and rounded
    half up to one decimal place to give `risk_score`."
    PRD §2.8: "The single non-monetary rounded quantity in the system is the medical
    `risk_score`, which is carried to one decimal place, rounded half up, and clamped so
    it can never exceed 100.0."
    PRD §3.4: "`recommendation` follows directly from `risk_score`: below 25.0 it is
    `CLEARED`; from 25.0 up to but not including 60.0 it is `CLEARED_WITH_RESTRICTION`;
    at 60.0 and above it is `HOLD_PENDING_PHYSICIAN_REVIEW`."

    The cardiac multiplier of 1.6 is applied to the sum of the four terms and
    only then is the product rounded half up to one decimal place.  A 68-year-old
    with `systolic_bp` 152, `resting_hr` 88, cardiac history and no high-contact
    entries sums 19.5 + 25 + 7.2 + 0 = 51.7, which multiplies to 82.72 and is
    reported as 82.7.

    Design: Difficulty/combinatorial_formula/medical_risk_score_nested_min_max_with_tiered_bp_branch
    """
    ctx = setup_open_edition(event={"age_group_code": "65-69"})
    athlete = create_athlete(ctx["edition"]["id"], date_of_birth=DOB_AGE_68)

    screening = validate_success(
        _screen(athlete["id"], systolic_bp=152, resting_hr=88, prior_cardiac_event=True),
        expected_status=201,
    )

    assert screening["contact_sport_count"] == 0
    assert float(screening["risk_score"]) == 82.7
    assert screening["recommendation"] == "HOLD_PENDING_PHYSICIAN_REVIEW"


def _restricted_athlete() -> dict:
    """A 65-year-old whose screening at 140 / 80 with no cardiac history scores
    15 + 12 + 4 + 0 = 31.0 and therefore reads `CLEARED_WITH_RESTRICTION`."""
    ctx = setup_open_edition(event={"age_group_code": "65-69"})
    athlete = create_athlete(ctx["edition"]["id"], date_of_birth=DOB_AGE_65)
    screening = validate_success(
        _screen(athlete["id"], systolic_bp=140, resting_hr=80, prior_cardiac_event=False),
        expected_status=201,
    )
    assert float(screening["risk_score"]) == 31.0
    assert screening["recommendation"] == "CLEARED_WITH_RESTRICTION"
    return get_athlete(athlete["id"])


def test_screening_moves_the_medical_dimension_and_leaves_registration_alone():
    """PRD §3.2: "Athletes carry **two independent status dimensions** that never gate one
    another mechanically."
    PRD §3.2: "`registration_status` tracks the commercial and attendance dimension and
    starts at `PENDING_PAYMENT`, with `REGISTERED`, `CHECKED_IN`, `WITHDRAWN` and
    `EXPIRED` as its other values and the last two terminal."
    PRD §3.4: "`recommendation` follows directly from `risk_score`: below 25.0 it is
    `CLEARED`; from 25.0 up to but not including 60.0 it is `CLEARED_WITH_RESTRICTION`;
    at 60.0 and above it is `HOLD_PENDING_PHYSICIAN_REVIEW`."
    PRD §3.4: "A `CLEARED_WITH_RESTRICTION` recommendation moves the athlete
    `NOT_SCREENED` → `SCREENED_RESTRICTED` and pulls back only their high-contact
    commitments: every entry of that athlete currently `ACCEPTED` whose event belongs to
    a sport whose `contact_class` is `HIGH` moves `ACCEPTED` → `MEDICAL_HOLD`, and each
    such move decrements that event's `accepted_entry_count` by one, increments that
    event's `available_slots` by one, and drives the event to `UNDERSUBSCRIBED` when
    `accepted_entry_count` falls below `min_entries_to_stage`."

    The two status dimensions never gate one another.  A screening that reads
    `CLEARED_WITH_RESTRICTION` drives `medical_status` to `SCREENED_RESTRICTED`
    while `registration_status` is still sitting at its initial
    `PENDING_PAYMENT`.

    Design: Difficulty/non_linear_state_machine/athlete_registration_and_medical_dimensions_advance_independently
    """
    athlete = _restricted_athlete()

    assert athlete["medical_status"] == "SCREENED_RESTRICTED"
    assert athlete["registration_status"] == "PENDING_PAYMENT"


def test_payment_moves_the_registration_dimension_and_leaves_medical_alone():
    """PRD §3.2: "Athletes carry **two independent status dimensions** that never gate one
    another mechanically."
    PRD §3.2: "**Step three** adds the base registration fee — ninety-five dollars, that
    is 9500 cents — to `event_fees_cents` to give `subtotal_cents`."
    PRD §3.2: "**Step five** picks `surcharge_cents` from `discounted_cents`: nothing at
    all below two hundred and fifty dollars, fifteen dollars — 1500 cents — from two
    hundred and fifty dollars up to but not including six hundred dollars, and forty
    dollars — 4000 cents — at six hundred dollars and above."
    PRD §3.2: "On success the recomputed `fee_total_cents` and `fee_breakdown` are
    stored, `fee_paid_cents` is set equal to `fee_total_cents`, and the registration
    dimension advances `PENDING_PAYMENT` → `REGISTERED`."

    Settling the fee advances `registration_status` `PENDING_PAYMENT` →
    `REGISTERED` while `medical_status` stays exactly where the screening left
    it.  With no live entries the settlement is the bare 9500-cent base fee.

    Design: Difficulty/non_linear_state_machine/athlete_registration_and_medical_dimensions_advance_independently
    """
    athlete = _restricted_athlete()

    pay_fees(athlete["id"], 9500)

    after = get_athlete(athlete["id"])
    assert after["registration_status"] == "REGISTERED"
    assert after["medical_status"] == "SCREENED_RESTRICTED"
    assert after["fee_total_cents"] == 9500


def test_a_granted_appeal_moves_only_the_medical_dimension_back():
    """PRD §3.2: "Athletes carry **two independent status dimensions** that never gate one
    another mechanically."
    PRD §3.4: "An athlete who believes a hold or a restriction is wrong may have it
    reviewed, and the `MedicalDirector` rules on the appeal with a `decision` of either
    `GRANT` or `DENY` plus an optional `note`."
    PRD §3.4: "A granted appeal from a restriction moves the athlete
    `SCREENED_RESTRICTED` → `CLEARED_BY_APPEAL`."

    A granted appeal from a restriction moves `medical_status`
    `SCREENED_RESTRICTED` → `CLEARED_BY_APPEAL`, and the registration dimension
    remains `REGISTERED` — the third independent move over the same row.

    Design: Difficulty/non_linear_state_machine/athlete_registration_and_medical_dimensions_advance_independently
    """
    athlete = _restricted_athlete()
    pay_fees(athlete["id"], 9500)

    response = api_client.medical_appeal(
        athlete["id"],
        {"decision": "GRANT", "note": "Cardiology clearance letter on file."},
        MEDICAL,
    )

    appealed = validate_success(response)
    assert appealed["medical_status"] == "CLEARED_BY_APPEAL"
    assert appealed["registration_status"] == "REGISTERED"


def _held_athlete_with_a_bad_citation() -> dict:
    """A 68-year-old on medical hold who also holds a qualifying mark that cannot
    support a `STATE_QUALIFIER` entry, because the meet was only `LOCAL`.

    Returns {"event", "athlete", "qualifying_result"}.
    """
    ctx = setup_open_edition(
        event={"event_code": "T5000M", "age_group_code": "65-69", "entry_fee_cents": 7000}
    )
    athlete = create_athlete(
        ctx["edition"]["id"], full_name="Cy Warden", date_of_birth=DOB_AGE_68
    )
    qualifying = create_qualifying_result(
        athlete["id"], ctx["sport"]["id"],
        event_code="T5000M", mark_value=1284.5, meet_date="2026-06-14", meet_level="LOCAL",
    )
    screening = validate_success(
        _screen(athlete["id"], systolic_bp=140, resting_hr=85, prior_cardiac_event=True),
        expected_status=201,
    )
    assert float(screening["risk_score"]) == 60.0
    assert screening["recommendation"] == "HOLD_PENDING_PHYSICIAN_REVIEW"
    assert screening["contact_sport_count"] == 0
    assert get_athlete(athlete["id"])["medical_status"] == "SCREENED_HOLD"
    return {"event": ctx["event"], "athlete": athlete, "qualifying_result": qualifying}


def test_the_medical_hold_is_reported_ahead_of_the_bad_qualifying_citation():
    """PRD §2.10: "The athlete's medical dimension does not block competition — otherwise
    `ERR_ATHLETE_MEDICAL_HOLD` (HTTP 422)."
    PRD §2.10: "`medical_status` must not be `SCREENED_HOLD` when an entry is submitted
    or reviewed, and must be one of `SCREENED_CLEARED`, `SCREENED_RESTRICTED` or
    `CLEARED_BY_APPEAL` at check-in."
    PRD §2.10: "The cited qualifying mark supports the entry — otherwise
    `ERR_QUALIFYING_RESULT_INVALID` (HTTP 422)."
    PRD §3.3: "And the citation itself must hold together: `qualifying_result_id` must
    be supplied exactly when `qualification_source` is `STATE_QUALIFIER` or
    `LOCAL_QUALIFIER`, and must be absent exactly when it is `AGE_EXEMPT` or
    `ORGANIZER_INVITE`; the cited result must belong to the entering athlete, must have
    been contested in the same sport as the target event, must carry an `event_code`
    equal to the target event's `event_code`, must have `sanctioned` true, and must have
    `meet_level` of `STATE` when the source is `STATE_QUALIFIER` while a
    `LOCAL_QUALIFIER` source accepts either `LOCAL` or `STATE`."

    One entry request breaks two rules at once: the athlete's medical
    dimension is `SCREENED_HOLD` and the cited mark's `meet_level` of `LOCAL`
    cannot support a `STATE_QUALIFIER` source.  The safety gate is decided before
    the citation cluster, so the answer is the medical hold — the two failures
    even share HTTP 422, so only the error identifier distinguishes them — and no
    entry row is written.

    Design: Difficulty/priority_pair_validation_conflict/entry_medical_hold_beats_qualifying_result_invalid
    """
    ctx = _held_athlete_with_a_bad_citation()

    response = api_client.create_sport_entry(
        {
            "athlete_id": ctx["athlete"]["id"],
            "sport_event_id": ctx["event"]["id"],
            "qualification_source": "STATE_QUALIFIER",
            "qualifying_result_id": ctx["qualifying_result"]["id"],
        },
        OFFICER,
    )

    validate_error(response, ApiErrorId.ERR_ATHLETE_MEDICAL_HOLD.value, expected_status=422)
    rows, _meta = validate_paginated(
        api_client.list_sport_entries(OFFICER, {"limit": 100, "offset": 0})
    )
    assert [row for row in rows if row["athlete_id"] == ctx["athlete"]["id"]] == []
    event = get_event(ctx["event"]["id"])
    assert event["accepted_entry_count"] == 0
    assert event["available_slots"] == 8


def test_lifting_the_hold_exposes_the_suppressed_qualifying_failure():
    """PRD §3.4: "A granted appeal from a hold moves the athlete `SCREENED_HOLD` →
    `CLEARED_BY_APPEAL` and requires that at least one screening exists for that
    athlete."
    PRD §2.10: "The athlete's medical dimension does not block competition — otherwise
    `ERR_ATHLETE_MEDICAL_HOLD` (HTTP 422)."
    PRD §3.3: "And the citation itself must hold together: `qualifying_result_id` must
    be supplied exactly when `qualification_source` is `STATE_QUALIFIER` or
    `LOCAL_QUALIFIER`, and must be absent exactly when it is `AGE_EXEMPT` or
    `ORGANIZER_INVITE`; the cited result must belong to the entering athlete, must have
    been contested in the same sport as the target event, must carry an `event_code`
    equal to the target event's `event_code`, must have `sanctioned` true, and must have
    `meet_level` of `STATE` when the source is `STATE_QUALIFIER` while a
    `LOCAL_QUALIFIER` source accepts either `LOCAL` or `STATE`."
    PRD §3.3: "Any failure in that citation cluster is refused with
    `ERR_QUALIFYING_RESULT_INVALID`."

    The citation rule was merely suppressed, not satisfied.  Once a granted
    appeal moves the athlete to `CLEARED_BY_APPEAL` the identical request is
    refused with the citation error instead, which proves the ordering rather
    than the absence of the second defect.

    Design: Difficulty/priority_pair_validation_conflict/entry_medical_hold_beats_qualifying_result_invalid
    """
    ctx = _held_athlete_with_a_bad_citation()
    appealed = validate_success(
        api_client.medical_appeal(ctx["athlete"]["id"], {"decision": "GRANT"}, MEDICAL)
    )
    assert appealed["medical_status"] == "CLEARED_BY_APPEAL"

    response = api_client.create_sport_entry(
        {
            "athlete_id": ctx["athlete"]["id"],
            "sport_event_id": ctx["event"]["id"],
            "qualification_source": "STATE_QUALIFIER",
            "qualifying_result_id": ctx["qualifying_result"]["id"],
        },
        OFFICER,
    )

    validate_error(response, ApiErrorId.ERR_QUALIFYING_RESULT_INVALID.value, expected_status=422)
