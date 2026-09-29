"""The two survey metrics: one walk of a ward, two inclusion sets, and the
per-unit scoping, half-up rounding and empty-denominator escape that decide what
publication writes onto each unit."""
from test_helpers import (
    as_instant,
    assert_two_decimal_places,
    cancel_survey_round_payload,
    create_candidate_nurse,
    create_certified_nurse,
    create_patient,
    create_round,
    create_unit,
    file_observation,
    get_success_data,
    lock_round,
    open_round,
    publish_round,
    validate_success,
)
from test_helpers.test_users import make_director_headers, make_unit_charge_headers


DIRECTOR = make_director_headers()


def _round(api, round_id):
    return get_success_data(api.get_survey_round(round_id, DIRECTOR))


def _unit(api, unit_id):
    return get_success_data(api.get_unit(unit_id, DIRECTOR))


def _report(api, round_id, headers=DIRECTOR):
    return validate_success(api.get_survey_round_unit_report(round_id, headers))


def _row_for(report, unit):
    """The one `unit_rows` entry belonging to `unit`."""
    rows = [row for row in report["unit_rows"] if row["unit_id"] == unit["id"]]
    assert len(rows) == 1, f"expected exactly one report row for {unit['unit_code']}"
    return rows[0]


def test_one_identical_walk_of_a_ward_publishes_two_different_numbers(api):
    """Prevalence 60.00 and incidence 50.00 off the very same five rows.

    PRD §3.7: "For **prevalence**, the numerator is the count of that unit's
    observations in the round whose `injury_present` is true, regardless of
    `classification`, so injuries the patient arrived with are counted; the
    denominator is the count of all of that unit's observations in the round,
    regardless of `at_risk`."
    PRD §3.7: "For **incidence**, the numerator is the count of that unit's
    observations in the round where `injury_present` is true *and* `classification`
    is `HAPI` *and* `onset_at` falls inside the round's closed window from
    `window_start` through `window_end` inclusive, so present-on-admission injuries
    are excluded; and the denominator is the count only of that unit's observations
    whose `at_risk` is true."
    PRD §3.7: "A `PREVALENCE` round writes each unit's `last_prevalence_rate`; an
    `INCIDENCE` round writes each unit's `last_incidence_rate`; each affected unit
    is versioned."

    Design: Difficulty/dual_variant_calc/unit_prevalence_vs_incidence_diverges
    """
    unit = create_unit(
        api,
        unit_code="7W",
        name="Seven West",
        bed_count=24,
        rental_budget_cap_cents=500000,
    )
    observer = create_certified_nurse(unit, api=api, full_name="Nina Stage")
    patients = [
        create_patient(unit, api=api, mrn=mrn, admitted_at="2026-07-30T00:00:00Z")
        for mrn in ("MRN-S1", "MRN-S2", "MRN-S3", "MRN-S4", "MRN-S5")
    ]
    findings = [
        {
            "injury_present": True,
            "classification": "HAPI",
            "observed_stage": "STAGE_2",
            "onset_at": "2026-08-02T00:00:00Z",
            "at_risk": True,
        },
        {
            "injury_present": True,
            "classification": "HAPI",
            "observed_stage": "STAGE_3",
            "onset_at": "2026-08-02T00:00:00Z",
            "at_risk": True,
        },
        {
            "injury_present": True,
            "classification": "POA",
            "observed_stage": "STAGE_2",
            "at_risk": True,
        },
        {"injury_present": False, "classification": "NONE", "at_risk": True},
        {"injury_present": False, "classification": "NONE", "at_risk": False},
    ]
    rounds = {}
    for round_type in ("PREVALENCE", "INCIDENCE"):
        survey_round = open_round(
            create_round(
                [unit["id"]],
                api=api,
                round_type=round_type,
                window_start="2026-08-01T00:00:00Z",
                window_end="2026-08-05T00:00:00Z",
            ),
            api=api,
        )
        for patient, finding in zip(patients, findings):
            file_observation(
                survey_round,
                unit,
                patient,
                observer,
                api=api,
                observed_at="2026-08-02T00:00:00Z",
                **finding,
            )
        rounds[round_type] = lock_round(survey_round, api=api)
    for survey_round in rounds.values():
        assert survey_round["observation_count"] == 5, (
            "both rounds hold the same five findings, so neither answer can be "
            "blamed on a different input set"
        )

    publish_round(rounds["PREVALENCE"], api=api)
    after_prevalence = _unit(api, unit["id"])
    assert after_prevalence["last_prevalence_rate"] == 60.00, (
        "three injury rows, including the present-on-admission one, over all five "
        "observations"
    )
    assert after_prevalence["last_incidence_rate"] is None, (
        "a PREVALENCE round leaves the incidence field alone"
    )

    publish_round(rounds["INCIDENCE"], api=api)
    after_incidence = _unit(api, unit["id"])
    assert after_incidence["last_incidence_rate"] == 50.00, (
        "two in-window HAPI onsets over the four at-risk rows"
    )
    assert after_incidence["last_prevalence_rate"] == 60.00, (
        "the earlier number is not disturbed"
    )
    assert (
        after_incidence["last_incidence_rate"] != after_incidence["last_prevalence_rate"]
    ), (
        "the two metrics disagree because the POA row enters only the prevalence "
        "numerator and the not-at-risk row enters only the prevalence denominator"
    )
    assert_two_decimal_places(after_incidence["last_prevalence_rate"])
    assert_two_decimal_places(after_incidence["last_incidence_rate"])
    for survey_round in rounds.values():
        assert _round(api, survey_round["id"])["status"] == "PUBLISHED"


def test_an_onset_before_the_window_counts_as_prevalence_but_not_as_incidence(api):
    """The incidence numerator dates the injury; the prevalence numerator only sees it.

    PRD §3.7: "For **incidence**, the numerator is the count of that unit's
    observations in the round where `injury_present` is true *and* `classification`
    is `HAPI` *and* `onset_at` falls inside the round's closed window from
    `window_start` through `window_end` inclusive, so present-on-admission injuries
    are excluded; and the denominator is the count only of that unit's observations
    whose `at_risk` is true."
    PRD §3.7: "The `observed_at` instant must lie inside the round's closed window,
    and a supplied `onset_at` must be at or before `observed_at`; either failure is
    an `ERR_OBSERVATION_OUTSIDE_WINDOW`."
    PRD §3.7: "In both cases the rate is the numerator divided by the denominator,
    multiplied by 100, and rounded half up to two decimal places."

    Design: Difficulty/dual_variant_calc/unit_prevalence_vs_incidence_diverges
    """
    unit = create_unit(
        api,
        unit_code="7W",
        name="Seven West",
        bed_count=24,
        rental_budget_cap_cents=500000,
    )
    observer = create_certified_nurse(unit, api=api, full_name="Nina Stage")
    older_injury, fresh_injury = (
        create_patient(unit, api=api, mrn=mrn, admitted_at="2026-07-25T00:00:00Z")
        for mrn in ("MRN-S6", "MRN-S7")
    )
    findings = (
        (older_injury, "2026-07-28T00:00:00Z"),
        (fresh_injury, "2026-08-03T00:00:00Z"),
    )
    rounds = {}
    for round_type in ("PREVALENCE", "INCIDENCE"):
        survey_round = open_round(
            create_round(
                [unit["id"]],
                api=api,
                round_type=round_type,
                window_start="2026-08-02T00:00:00Z",
                window_end="2026-08-05T00:00:00Z",
            ),
            api=api,
        )
        for patient, onset_at in findings:
            filed = file_observation(
                survey_round,
                unit,
                patient,
                observer,
                api=api,
                observed_at="2026-08-04T00:00:00Z",
                injury_present=True,
                classification="HAPI",
                observed_stage="STAGE_2",
                onset_at=onset_at,
                at_risk=True,
            )
            assert as_instant(filed["onset_at"]) <= as_instant(filed["observed_at"]), (
                "an onset earlier than the window still satisfies the only temporal "
                "rule the filing gate imposes on it"
            )
        rounds[round_type] = lock_round(survey_round, api=api)

    publish_round(rounds["PREVALENCE"], api=api)
    publish_round(rounds["INCIDENCE"], api=api)
    measured = _unit(api, unit["id"])
    assert measured["last_prevalence_rate"] == 100.00, (
        "both rows carry an injury, and prevalence never asks when it began"
    )
    assert measured["last_incidence_rate"] == 50.00, (
        "only the onset inside the closed window is ward-acquired for this round"
    )
    assert measured["last_incidence_rate"] != 100.00

    report = _report(api, rounds["INCIDENCE"]["id"])
    row = _row_for(report, unit)
    assert row["injury_present_count"] == 2
    assert row["hapi_in_window_count"] == 1, (
        "the classification is HAPI on both rows; only one of the two onsets lands "
        "inside the window"
    )
    assert row["at_risk_count"] == 2


def test_a_ward_with_nobody_at_risk_publishes_a_flat_zero(api):
    """A zero denominator is answered with 0.00, while its peer ward gets 100.00.

    PRD §3.7: "When the denominator is 0 the rate is exactly 0.00 and no error is
    raised."
    PRD §3.7: "Publication computes one metric per unit identifier in
    `participating_unit_ids`, and the scope for each computation is precisely the
    observations attached to *this* round and to *that* unit — observations
    attached to other rounds covering the same ward are excluded, and ordering is
    irrelevant because both metrics are pure counts."
    PRD §3.7: "an `observation_total` across the whole round"

    Design: Difficulty/boundary_precision_check/empty_at_risk_denominator_yields_zero_incidence
    """
    nobody_at_risk = create_unit(
        api,
        unit_code="7W",
        name="Seven West",
        bed_count=24,
        rental_budget_cap_cents=500000,
    )
    one_hapi = create_unit(
        api,
        unit_code="8E",
        name="Eight East",
        bed_count=20,
        rental_budget_cap_cents=500000,
    )
    observer = create_certified_nurse(nobody_at_risk, api=api, full_name="Nina Stage")
    unwatched = create_patient(
        nobody_at_risk, api=api, mrn="MRN-Z1", admitted_at="2026-07-30T00:00:00Z"
    )
    injured = create_patient(
        one_hapi, api=api, mrn="MRN-Z2", admitted_at="2026-07-30T00:00:00Z"
    )
    survey_round = open_round(
        create_round(
            [nobody_at_risk["id"], one_hapi["id"]],
            api=api,
            round_type="INCIDENCE",
            window_start="2026-08-01T00:00:00Z",
            window_end="2026-08-05T00:00:00Z",
        ),
        api=api,
    )
    file_observation(
        survey_round,
        nobody_at_risk,
        unwatched,
        observer,
        api=api,
        observed_at="2026-08-03T00:00:00Z",
        at_risk=False,
    )
    file_observation(
        survey_round,
        one_hapi,
        injured,
        observer,
        api=api,
        observed_at="2026-08-03T00:00:00Z",
        injury_present=True,
        classification="HAPI",
        observed_stage="STAGE_2",
        onset_at="2026-08-03T00:00:00Z",
        at_risk=True,
    )
    lock_round(survey_round, api=api)

    published = validate_success(
        api.publish_survey_round(survey_round["id"], {}, DIRECTOR)
    )
    assert published["status"] == "PUBLISHED", (
        "an empty denominator is an answerable case, not a server error"
    )
    assert published["observation_count"] == 2

    empty = _unit(api, nobody_at_risk["id"])
    assert empty["last_incidence_rate"] == 0.00
    assert empty["last_incidence_rate"] is not None, (
        "the empty-denominator answer is a number and not a null"
    )
    assert_two_decimal_places(empty["last_incidence_rate"])
    assert empty["last_prevalence_rate"] is None, (
        "publishing an INCIDENCE round never writes the prevalence field"
    )

    populated = _unit(api, one_hapi["id"])
    assert populated["last_incidence_rate"] == 100.00, "one in-window HAPI over one at-risk row"

    report = _report(api, survey_round["id"])
    assert report["observation_total"] == 2
    assert _row_for(report, nobody_at_risk)["at_risk_count"] == 0, (
        "the denominator the formula divided by really was zero"
    )


def test_a_ward_acquired_injury_off_the_at_risk_register_still_reads_zero(api):
    """A numerator of one over a denominator of nothing is 0.00, not an overflow.

    PRD §3.7: "For **incidence**, the numerator is the count of that unit's
    observations in the round where `injury_present` is true *and* `classification`
    is `HAPI` *and* `onset_at` falls inside the round's closed window from
    `window_start` through `window_end` inclusive, so present-on-admission injuries
    are excluded; and the denominator is the count only of that unit's observations
    whose `at_risk` is true."
    PRD §3.7: "When the denominator is 0 the rate is exactly 0.00 and no error is
    raised."
    PRD §3.7: "`at_risk` records whether the patient was on the ward's at-risk
    register during the pass and defaults to true when omitted."

    Design: Difficulty/boundary_precision_check/empty_at_risk_denominator_yields_zero_incidence
    """
    off_register = create_unit(
        api,
        unit_code="7W",
        name="Seven West",
        bed_count=24,
        rental_budget_cap_cents=500000,
    )
    on_register = create_unit(
        api,
        unit_code="8E",
        name="Eight East",
        bed_count=20,
        rental_budget_cap_cents=500000,
    )
    observer = create_certified_nurse(off_register, api=api, full_name="Nina Stage")
    unregistered = create_patient(
        off_register, api=api, mrn="MRN-Z3", admitted_at="2026-07-30T00:00:00Z"
    )
    registered = create_patient(
        on_register, api=api, mrn="MRN-Z4", admitted_at="2026-07-30T00:00:00Z"
    )
    survey_round = open_round(
        create_round(
            [off_register["id"], on_register["id"]],
            api=api,
            round_type="INCIDENCE",
            window_start="2026-08-01T00:00:00Z",
            window_end="2026-08-05T00:00:00Z",
        ),
        api=api,
    )
    numerator_only = file_observation(
        survey_round,
        off_register,
        unregistered,
        observer,
        api=api,
        observed_at="2026-08-03T00:00:00Z",
        injury_present=True,
        classification="HAPI",
        observed_stage="STAGE_3",
        onset_at="2026-08-03T00:00:00Z",
        at_risk=False,
    )
    assert numerator_only["at_risk"] is False, (
        "an explicit false must not be replaced by the omission default of true"
    )
    file_observation(
        survey_round,
        on_register,
        registered,
        observer,
        api=api,
        observed_at="2026-08-03T00:00:00Z",
    )
    lock_round(survey_round, api=api)
    published = publish_round(survey_round, api=api)
    assert published["status"] == "PUBLISHED"

    report = _report(api, survey_round["id"])
    numerator_row = _row_for(report, off_register)
    assert numerator_row["hapi_in_window_count"] == 1, "the numerator is not empty"
    assert numerator_row["at_risk_count"] == 0, "the denominator is"

    assert _unit(api, off_register["id"])["last_incidence_rate"] == 0.00, (
        "an empty denominator answers 0.00 whatever the numerator holds"
    )
    assert _unit(api, on_register["id"])["last_incidence_rate"] == 0.00, (
        "the peer ward's single at-risk row records no injury, so its numerator is "
        "an honest zero over a denominator of one"
    )
    assert numerator_row["incidence_rate"] == 0.00
    peer_row = _row_for(report, on_register)
    assert peer_row["at_risk_count"] == 1, "an omitted at_risk counts as at risk"
    assert peer_row["hapi_in_window_count"] == 0
    assert peer_row["incidence_rate"] == 0.00


def test_one_publish_writes_a_different_number_to_each_participating_ward(api):
    """Pooling the rows would give both wards 66.67 and be wrong twice.

    PRD §3.7: "Publication computes one metric per unit identifier in
    `participating_unit_ids`, and the scope for each computation is precisely the
    observations attached to *this* round and to *that* unit — observations
    attached to other rounds covering the same ward are excluded, and ordering is
    irrelevant because both metrics are pure counts."
    PRD §3.7: "For **prevalence**, the numerator is the count of that unit's
    observations in the round whose `injury_present` is true, regardless of
    `classification`, so injuries the patient arrived with are counted; the
    denominator is the count of all of that unit's observations in the round,
    regardless of `at_risk`."

    Design: Corner/calculations/survey_metric_scoped_to_each_units_own_observations
    """
    mixed_ward = create_unit(
        api,
        unit_code="3E",
        name="Three East",
        bed_count=18,
        rental_budget_cap_cents=0,
    )
    single_row_ward = create_unit(
        api,
        unit_code="4W",
        name="Four West",
        bed_count=22,
        rental_budget_cap_cents=0,
    )
    observer = create_candidate_nurse(mixed_ward, api=api, full_name="Nina Stage")
    injured, clean = (
        create_patient(mixed_ward, api=api, mrn=mrn, admitted_at="2026-07-31T00:00:00Z")
        for mrn in ("MRN-K1", "MRN-K2")
    )
    elsewhere = create_patient(
        single_row_ward, api=api, mrn="MRN-K3", admitted_at="2026-07-31T00:00:00Z"
    )
    survey_round = open_round(
        create_round(
            [mixed_ward["id"], single_row_ward["id"]],
            api=api,
            round_type="PREVALENCE",
            window_start="2026-08-01T00:00:00Z",
            window_end="2026-08-05T00:00:00Z",
        ),
        api=api,
    )
    file_observation(
        survey_round,
        mixed_ward,
        injured,
        observer,
        api=api,
        observed_at="2026-08-02T00:00:00Z",
        injury_present=True,
        classification="POA",
        observed_stage="STAGE_2",
    )
    file_observation(
        survey_round,
        mixed_ward,
        clean,
        observer,
        api=api,
        observed_at="2026-08-02T00:00:00Z",
    )
    file_observation(
        survey_round,
        single_row_ward,
        elsewhere,
        observer,
        api=api,
        observed_at="2026-08-02T00:00:00Z",
        injury_present=True,
        classification="HAPI",
        observed_stage="STAGE_1",
        onset_at="2026-08-02T00:00:00Z",
    )
    lock_round(survey_round, api=api)

    published = validate_success(
        api.publish_survey_round(survey_round["id"], {}, DIRECTOR)
    )
    assert published["status"] == "PUBLISHED"
    assert published["observation_count"] == 3

    mixed = _unit(api, mixed_ward["id"])
    single = _unit(api, single_row_ward["id"])
    assert mixed["last_prevalence_rate"] == 50.00, "one injury row out of two rows on 3E"
    assert single["last_prevalence_rate"] == 100.00, "one injury row out of one row on 4W"
    assert mixed["last_prevalence_rate"] != 66.67, (
        "66.67 is what pooling all three rows across both wards would produce"
    )
    assert single["last_prevalence_rate"] != 66.67
    assert mixed["last_prevalence_rate"] != 100.00, (
        "dropping the clean row from the denominator would have made 3E 100.00 too"
    )
    assert mixed["last_incidence_rate"] is None
    assert single["last_incidence_rate"] is None, (
        "the 4W row is a HAPI with an in-window onset, and a PREVALENCE round still "
        "writes nothing to the incidence field"
    )


def test_two_injuries_in_three_patients_rounds_up_to_two_decimals(api):
    """66.6666... is stored as 66.67, which pins both the scale and the direction.

    PRD §3.7: "In both cases the rate is the numerator divided by the denominator,
    multiplied by 100, and rounded half up to two decimal places."
    PRD §2.8: "Percentages, rates and scores are decimal numbers with a pinned
    scale."

    Design: Corner/calculations/prevalence_rate_rounds_half_up_to_two_decimals
    """
    unit = create_unit(
        api,
        unit_code="3E",
        name="Three East",
        bed_count=18,
        rental_budget_cap_cents=0,
    )
    observer = create_candidate_nurse(unit, api=api, full_name="Nina Stage")
    patients = [
        create_patient(unit, api=api, mrn=mrn, admitted_at="2026-07-31T00:00:00Z")
        for mrn in ("MRN-K4", "MRN-K5", "MRN-K6")
    ]
    survey_round = open_round(
        create_round(
            [unit["id"]],
            api=api,
            round_type="PREVALENCE",
            window_start="2026-08-01T00:00:00Z",
            window_end="2026-08-05T00:00:00Z",
        ),
        api=api,
    )
    findings = (
        {
            "injury_present": True,
            "classification": "POA",
            "observed_stage": "STAGE_2",
        },
        {
            "injury_present": True,
            "classification": "POA",
            "observed_stage": "STAGE_1",
        },
        {"injury_present": False, "classification": "NONE"},
    )
    for patient, finding in zip(patients, findings):
        file_observation(
            survey_round,
            unit,
            patient,
            observer,
            api=api,
            observed_at="2026-08-02T00:00:00Z",
            at_risk=True,
            **finding,
        )
    lock_round(survey_round, api=api)
    published = publish_round(survey_round, api=api)

    rate = _unit(api, unit["id"])["last_prevalence_rate"]
    assert rate == 66.67, "100 times 2 over 3 is 66.6666..., which rounds half up"
    assert rate != 66.66, "66.66 is truncation rather than rounding"
    assert rate != 66.7, "66.7 is the wrong scale"
    assert_two_decimal_places(rate)

    assert published["observation_count"] == 3
    assert as_instant(published["published_at"]) == as_instant("2026-08-01T00:00:00Z"), (
        "the stamp comes off the logical clock, which no test has repositioned"
    )


def test_a_cancelled_round_writes_no_number_and_frees_its_window(api):
    """The observations survive the cancellation; the metric never happens.

    PRD §3.7: "Cancelling an open round retains the observations already filed
    against it as audit records but writes no unit metric whatsoever, so
    `last_prevalence_rate` and `last_incidence_rate` are left exactly as the last
    published round left them."
    PRD §3.7: "A `PREVALENCE` round may not open when any other `PREVALENCE` round
    whose `status` is `OPEN`, `LOCKED` or `PUBLISHED` collides on a shared unit —
    the aggregate capacity for prevalence work on a ward is exactly one round."
    PRD §3.7: "At most one observation may exist for a given combination of
    `survey_round_id` and `patient_id`, and a second attempt is refused with
    `ERR_DUPLICATE_OBSERVATION`."

    Design: Corner/calculations/cancelled_round_writes_no_metric_then_later_round_publishes_zero
    """
    unit = create_unit(
        api,
        unit_code="3E",
        name="Three East",
        bed_count=18,
        rental_budget_cap_cents=0,
    )
    observer = create_candidate_nurse(unit, api=api, full_name="Nina Stage")
    patient = create_patient(
        unit, api=api, mrn="MRN-K7", admitted_at="2026-07-31T00:00:00Z"
    )
    window = {
        "window_start": "2026-08-01T00:00:00Z",
        "window_end": "2026-08-05T00:00:00Z",
    }
    abandoned = open_round(
        create_round([unit["id"]], api=api, round_type="PREVALENCE", **window),
        api=api,
    )
    file_observation(
        survey_round=abandoned,
        unit=unit,
        patient=patient,
        observer=observer,
        api=api,
        observed_at="2026-08-02T00:00:00Z",
        injury_present=True,
        classification="POA",
        observed_stage="STAGE_2",
    )

    cancelled = validate_success(
        api.cancel_survey_round(
            abandoned["id"],
            cancel_survey_round_payload(
                reason="Surveyor pulled to a code; pass incomplete."
            ),
            DIRECTOR,
        )
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["observation_count"] == 1, "the audit rows are retained"
    assert cancelled["published_at"] is None
    assert _unit(api, unit["id"])["last_prevalence_rate"] is None, (
        "the retained row would have published 100.00, and a cancelled round "
        "publishes nothing at all"
    )

    replacement = create_round(
        [unit["id"]], api=api, round_type="PREVALENCE", **window
    )
    assert open_round(replacement, api=api)["status"] == "OPEN", (
        "a CANCELLED round is in none of the three blocking states, so the identical "
        "window is free again"
    )
    file_observation(
        survey_round=replacement,
        unit=unit,
        patient=patient,
        observer=observer,
        api=api,
        observed_at="2026-08-03T00:00:00Z",
    )
    lock_round(replacement, api=api)
    published = publish_round(replacement, api=api)
    assert published["status"] == "PUBLISHED"
    assert published["observation_count"] == 1, (
        "the same patient may be walked once in each round, because the uniqueness "
        "key is the pair"
    )

    assert _unit(api, unit["id"])["last_prevalence_rate"] == 0.00, (
        "zero injuries over one observation is a real division, and it lands on the "
        "same 0.00 the empty-denominator case answers with"
    )


def test_the_unit_report_recomputes_on_read_and_changes_nothing(api):
    """Every field in the report is derived, and reading it moves no version.

    PRD §3.7: "A computed per-unit report is also readable for any round, and it
    is the diagnostic surface for that divergence: it answers with the round's
    `round_id`, its `round_type`, an `observation_total` across the whole round, and
    a `unit_rows` array."
    PRD §3.7: "Each element of `unit_rows` carries that unit's `unit_id` and
    `unit_code`, its `observation_count` within this round, its
    `injury_present_count`, its `hapi_in_window_count`, its `at_risk_count`, and
    both computed figures side by side as `prevalence_rate` and `incidence_rate` —
    so a caller can see both metrics for the same observations regardless of which
    one the round's `round_type` will actually publish."

    Design: Corner/endpoints/unit_report_computed_read_matches_published_unit_metrics
    """
    mixed_ward = create_unit(
        api,
        unit_code="3E",
        name="Three East",
        bed_count=18,
        rental_budget_cap_cents=0,
    )
    single_row_ward = create_unit(
        api,
        unit_code="4W",
        name="Four West",
        bed_count=22,
        rental_budget_cap_cents=0,
    )
    outside_the_round = create_unit(
        api,
        unit_code="5N",
        name="Five North",
        bed_count=16,
        rental_budget_cap_cents=0,
    )
    observer = create_candidate_nurse(mixed_ward, api=api, full_name="Nina Stage")
    injured, clean = (
        create_patient(mixed_ward, api=api, mrn=mrn, admitted_at="2026-07-31T00:00:00Z")
        for mrn in ("MRN-AE1", "MRN-AE2")
    )
    elsewhere = create_patient(
        single_row_ward, api=api, mrn="MRN-AE3", admitted_at="2026-07-31T00:00:00Z"
    )
    survey_round = open_round(
        create_round(
            [mixed_ward["id"], single_row_ward["id"]],
            api=api,
            round_type="PREVALENCE",
            window_start="2026-08-01T00:00:00Z",
            window_end="2026-08-05T00:00:00Z",
        ),
        api=api,
    )
    file_observation(
        survey_round,
        mixed_ward,
        injured,
        observer,
        api=api,
        observed_at="2026-08-02T00:00:00Z",
        injury_present=True,
        classification="POA",
        observed_stage="STAGE_2",
    )
    file_observation(
        survey_round,
        mixed_ward,
        clean,
        observer,
        api=api,
        observed_at="2026-08-02T00:00:00Z",
    )
    file_observation(
        survey_round,
        single_row_ward,
        elsewhere,
        observer,
        api=api,
        observed_at="2026-08-02T00:00:00Z",
        injury_present=True,
        classification="POA",
        observed_stage="STAGE_1",
    )
    lock_round(survey_round, api=api)
    publish_round(survey_round, api=api)
    before_round = _round(api, survey_round["id"])
    before_mixed = _unit(api, mixed_ward["id"])
    before_single = _unit(api, single_row_ward["id"])

    report = _report(api, survey_round["id"])
    assert report["round_id"] == survey_round["id"]
    assert report["round_type"] == "PREVALENCE"
    assert report["observation_total"] == 3
    assert report["observation_total"] == before_round["observation_count"], (
        "the report's total is the round's own counter and not a second tally"
    )
    assert len(report["unit_rows"]) == 2, "one row per participating unit and no more"
    assert {row["unit_id"] for row in report["unit_rows"]} == {
        mixed_ward["id"],
        single_row_ward["id"],
    }
    assert outside_the_round["id"] not in {row["unit_id"] for row in report["unit_rows"]}

    mixed_row = _row_for(report, mixed_ward)
    single_row = _row_for(report, single_row_ward)
    assert mixed_row["unit_code"] == "3E"
    assert mixed_row["observation_count"] == 2
    assert mixed_row["injury_present_count"] == 1
    assert mixed_row["prevalence_rate"] == 50.00
    assert mixed_row["prevalence_rate"] == before_mixed["last_prevalence_rate"], (
        "the computed read reproduces the very number publication wrote"
    )
    assert single_row["unit_code"] == "4W"
    assert single_row["observation_count"] == 1
    assert single_row["prevalence_rate"] == 100.00
    assert single_row["prevalence_rate"] == before_single["last_prevalence_rate"]
    assert mixed_row["hapi_in_window_count"] == 0, (
        "both injuries are present on admission, so the incidence numerator is empty "
        "on a report the round will never publish"
    )
    assert mixed_row["incidence_rate"] == 0.00

    assert _round(api, survey_round["id"])["version"] == before_round["version"], (
        "a computed read mutates nothing"
    )
    assert _unit(api, mixed_ward["id"])["version"] == before_mixed["version"]
    assert _unit(api, single_row_ward["id"])["version"] == before_single["version"]

    as_the_ward = _report(
        api, survey_round["id"], make_unit_charge_headers(mixed_ward["id"])
    )
    assert as_the_ward == report, (
        "the report is readable by a ward that cannot publish it"
    )
