"""SDOH screening: instrument publication, weighted scoring, the risk bands and
the amendment-versus-fresh anchoring fork."""

from test_helpers import (
    ApiErrorId,
    assert_same_instant,
    assert_score,
    assert_screening,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.factories import create_screening_payload
from test_helpers.test_users import PROGRAM_ADMIN, make_chw_headers


def test_in_cadence_rescreen_folds_into_the_existing_row(api):
    """PRD §3.2: "Under **amendment anchor**, no new row is created. The
    existing row is rewritten in place: `domain_scores` is overwritten,
    `weighted_score` and `risk_tier` are recomputed, `latest_response_at`
    advances to the current logical clock, `amendment_count` increments by 1,
    the row's `version` increments by 1, and its `status` becomes `AMENDED` — a
    row already in `AMENDED` stays in `AMENDED` and simply increments again,
    which is how a patient can be amended repeatedly inside one cadence window."
    PRD §3.2: "The response to an amendment is still HTTP 201, and it carries
    the existing row's `id` with its incremented `amendment_count` and its
    untouched `anchor_screened_at`."

    Design: Difficulty/dual_variant_calc/screening_rescreen_amendment_vs_fresh_anchor
    """
    worker, patient, chw_headers = fx.program_with_patient(
        clock="2026-06-01T00:00:00Z", employee_code="W-001", enroll=False,
        mrn="MRN-001", full_name="Rosa Diaz", household_size=3,
        monthly_income_cents=180_000,
    )
    instrument = fx.published_instrument(rescreen_cadence_days=90)

    first = fx.administer_screening(
        chw_headers, patient["id"], instrument["id"],
        domain_scores={"FOOD": 3, "HOUSING": 2, "TRANSPORT": 1},
    )
    assert_screening(first)
    assert_score(first["weighted_score"], 55.00, "first weighted_score")

    fx.set_clock("2026-08-01T00:00:00Z")
    response = api.administer_screening(
        create_screening_payload(
            patient["id"], instrument["id"], fx.patient_version(patient["id"]),
            domain_scores={"FOOD": 4, "HOUSING": 4, "TRANSPORT": 2},
        ),
        chw_headers,
    )
    second = validate_success(response, 201)

    assert second["id"] == first["id"], (
        "the amendment-anchor variant returns the EXISTING row's id, not a new one"
    )
    assert second["status"] == "AMENDED", (
        f"an in-cadence re-screen moves the row to AMENDED, got {second['status']}"
    )
    assert second["amendment_count"] == 1, (
        f"amendment_count increments to 1, got {second['amendment_count']}"
    )
    assert_same_instant(
        second["anchor_screened_at"], "2026-06-01T00:00:00Z",
        "screening.anchor_screened_at",
    )
    assert_same_instant(
        second["latest_response_at"], "2026-08-01T00:00:00Z",
        "screening.latest_response_at",
    )
    assert_score(second["weighted_score"], 90.00, "amended weighted_score")
    assert second["risk_tier"] == "CRITICAL", (
        f"90.00 sits at or above 75 and is CRITICAL, got {second['risk_tier']}"
    )


def test_an_amendment_does_not_restart_the_patient_coverage_clock(api):
    """PRD §3.2: "Critically, `anchor_screened_at` is **preserved unchanged**,
    and therefore so is the patient's `risk_tier_effective_at`: an amendment
    does not restart the coverage clock."
    PRD §3.2: "Both variants then write the same three fields onto the patient —
    `risk_score` takes the computed `weighted_score`, `risk_tier` takes the
    computed band — and increment the patient's `version` by 1."

    Design: Difficulty/dual_variant_calc/screening_rescreen_amendment_vs_fresh_anchor
    """
    worker, patient, chw_headers = fx.program_with_patient(
        clock="2026-06-01T00:00:00Z", employee_code="W-001B", enroll=False,
        mrn="MRN-001B", full_name="Rosa Diaz",
    )
    instrument = fx.published_instrument(rescreen_cadence_days=90)
    fx.administer_screening(
        chw_headers, patient["id"], instrument["id"],
        domain_scores={"FOOD": 3, "HOUSING": 2, "TRANSPORT": 1},
    )

    fx.set_clock("2026-08-01T00:00:00Z")
    fx.administer_screening(
        chw_headers, patient["id"], instrument["id"],
        domain_scores={"FOOD": 4, "HOUSING": 4, "TRANSPORT": 2},
    )

    reread = fx.read_patient(patient["id"])
    assert_score(reread["risk_score"], 90.00, "patient.risk_score")
    assert reread["risk_tier"] == "CRITICAL"
    assert_same_instant(
        reread["risk_tier_effective_at"], "2026-06-01T00:00:00Z",
        "patient.risk_tier_effective_at",
    )

    _rows, meta = validate_paginated(
        api.list_screenings(chw_headers, params={"patient_id": patient["id"]})
    )
    assert meta["total_count"] == 1, (
        f"the amendment created no second row, got total_count {meta['total_count']}"
    )


def test_rescreen_at_exactly_the_cadence_boundary_mints_a_fresh_row(api):
    """PRD §3.2: "Otherwise, if the elapsed time from the current screening's
    `anchor_screened_at` to the current logical clock is strictly less than the
    instrument's `rescreen_cadence_days` expressed in days, the
    **amendment-anchor** variant applies; and if that elapsed time is equal to
    or greater than the cadence, the fresh-anchor variant applies."
    PRD §3.2: "The cadence window is half-open on its upper end: at exactly the
    cadence boundary the strict comparison is false and the fresh-anchor variant
    takes over."
    PRD §3.2: "Under **fresh anchor**, a new screening row is created with
    `anchor_screened_at` and `latest_response_at` both set to the current
    logical clock and `amendment_count` at 0, and its `status` is `SUBMITTED`."

    Design: Difficulty/boundary_precision_check/rescreen_cadence_exact_boundary_re_anchors
    """
    worker, patient, chw_headers = fx.program_with_patient(
        clock="2026-06-01T00:00:00Z", employee_code="W-016", enroll=False,
        mrn="MRN-150", full_name="Cadence Case", household_size=3,
        monthly_income_cents=130_000,
    )
    instrument = fx.published_instrument(rescreen_cadence_days=90)
    first = fx.administer_screening(
        chw_headers, patient["id"], instrument["id"],
        domain_scores={"FOOD": 3, "HOUSING": 2, "TRANSPORT": 1},
    )

    fx.set_clock("2026-08-30T00:00:00Z")
    response = api.administer_screening(
        create_screening_payload(
            patient["id"], instrument["id"], fx.patient_version(patient["id"]),
            domain_scores={"FOOD": 3, "HOUSING": 2, "TRANSPORT": 1},
        ),
        chw_headers,
    )
    second = validate_success(response, 201)

    assert second["id"] != first["id"], (
        "at exactly the cadence boundary a NEW screening row is minted"
    )
    assert_same_instant(
        second["anchor_screened_at"], "2026-08-30T00:00:00Z",
        "fresh anchor_screened_at",
    )
    assert second["amendment_count"] == 0, (
        f"a freshly anchored row starts at amendment_count 0, got {second['amendment_count']}"
    )
    assert second["status"] == "SUBMITTED"


def test_the_superseded_row_keeps_its_own_anchor_and_the_patient_re_anchors(api):
    """PRD §3.2: "If the patient already had a screening in `SUBMITTED` or
    `AMENDED`, that prior row transitions to `SUPERSEDED` and its `version`
    increments by 1; its own `anchor_screened_at`, `weighted_score` and
    `risk_tier` are frozen as historical record."
    PRD §3.2: "The patient's `risk_tier_effective_at` re-anchors to the new
    instant, which restarts the 365-day screening coverage clock the program
    report uses."

    Design: Difficulty/boundary_precision_check/rescreen_cadence_exact_boundary_re_anchors
    """
    worker, patient, chw_headers = fx.program_with_patient(
        clock="2026-06-01T00:00:00Z", employee_code="W-016B", enroll=False,
        mrn="MRN-150B", full_name="Cadence Case",
    )
    instrument = fx.published_instrument(rescreen_cadence_days=90)
    first = fx.administer_screening(
        chw_headers, patient["id"], instrument["id"],
        domain_scores={"FOOD": 3, "HOUSING": 2, "TRANSPORT": 1},
    )

    fx.set_clock("2026-08-30T00:00:00Z")
    fx.administer_screening(
        chw_headers, patient["id"], instrument["id"],
        domain_scores={"FOOD": 3, "HOUSING": 2, "TRANSPORT": 1},
    )

    superseded = fx.read_screening(first["id"])
    assert superseded["status"] == "SUPERSEDED", (
        f"the prior current row is superseded, got {superseded['status']}"
    )
    assert_same_instant(
        superseded["anchor_screened_at"], "2026-06-01T00:00:00Z",
        "superseded anchor_screened_at",
    )

    reread = fx.read_patient(patient["id"])
    assert_same_instant(
        reread["risk_tier_effective_at"], "2026-08-30T00:00:00Z",
        "patient.risk_tier_effective_at",
    )

    _rows, meta = validate_paginated(
        api.list_screenings(chw_headers, params={"patient_id": patient["id"]})
    )
    assert meta["total_count"] == 2, (
        f"the fresh anchor leaves two screening rows, got {meta['total_count']}"
    )


def test_screening_against_a_draft_instrument_is_refused(api):
    """PRD §3.2: "A screening that names an instrument in `DRAFT` or `RETIRED`
    is rejected at rung 9 with `ERR_INSTRUMENT_NOT_PUBLISHED`."
    PRD §3.2: "An instrument also carries a `rescreen_cadence_days` value of at
    least 1, which defaults to 90 days and which decides — as this subsection
    explains below — whether a re-screen amends the patient's existing record or
    starts a fresh one."

    Design: Difficulty/cross_entity_state_dependency/screening_blocked_while_instrument_unpublished
    """
    worker, patient, chw_headers = fx.program_with_patient(
        clock="2026-06-01T00:00:00Z", employee_code="W-019", enroll=False,
        mrn="MRN-180", full_name="Draft Case",
    )
    instrument = fx.draft_instrument(version_label="v3.0")
    assert instrument["status"] == "DRAFT"
    assert instrument["rescreen_cadence_days"] == 90, (
        "an omitted rescreen_cadence_days defaults to 90 days, got "
        f"{instrument['rescreen_cadence_days']}"
    )

    response = api.administer_screening(
        create_screening_payload(
            patient["id"], instrument["id"], patient["version"],
            domain_scores={"FOOD": 3, "HOUSING": 2, "TRANSPORT": 1},
        ),
        chw_headers,
    )
    validate_error(response, ApiErrorId.ERR_INSTRUMENT_NOT_PUBLISHED.value, 409)


def test_publishing_the_instrument_lets_the_identical_screening_through(api):
    """PRD §3.2: "Publishing it moves `DRAFT` to `PUBLISHED` and increments its
    `version` by 1; retiring it moves `PUBLISHED` to `RETIRED`, again
    incrementing `version`, and leaves every screening already anchored to that
    revision untouched with its historical scores intact."
    PRD §3.2: "Separately, when the patient's `enrollment_status` is
    `PROSPECTIVE` and the computed tier is `MODERATE`, `HIGH` or `CRITICAL`, the
    patient is automatically moved to `ENROLLED` as part of the same request; a
    `LOW` tier leaves them `PROSPECTIVE`."

    Design: Difficulty/cross_entity_state_dependency/screening_blocked_while_instrument_unpublished
    """
    worker, patient, chw_headers = fx.program_with_patient(
        clock="2026-06-01T00:00:00Z", employee_code="W-019B", enroll=False,
        mrn="MRN-180B", full_name="Draft Case",
    )
    instrument = fx.draft_instrument(version_label="v3.0")

    refused = api.administer_screening(
        create_screening_payload(
            patient["id"], instrument["id"], patient["version"],
            domain_scores={"FOOD": 3, "HOUSING": 2, "TRANSPORT": 1},
        ),
        chw_headers,
    )
    validate_error(refused, ApiErrorId.ERR_INSTRUMENT_NOT_PUBLISHED.value, 409)

    published = validate_success(
        api.publish_instrument(instrument["id"], PROGRAM_ADMIN)
    )
    assert published["status"] == "PUBLISHED"

    accepted = validate_success(
        api.administer_screening(
            create_screening_payload(
                patient["id"], instrument["id"], fx.patient_version(patient["id"]),
                domain_scores={"FOOD": 3, "HOUSING": 2, "TRANSPORT": 1},
            ),
            chw_headers,
        ),
        201,
    )
    assert_score(accepted["weighted_score"], 55.00, "weighted_score")
    assert accepted["risk_tier"] == "HIGH", (
        f"55.00 sits at or above 50 and is HIGH, got {accepted['risk_tier']}"
    )

    reread = fx.read_patient(patient["id"])
    assert reread["enrollment_status"] == "ENROLLED", (
        "a HIGH-tier screening auto-enrols a PROSPECTIVE patient"
    )
    assert_same_instant(
        reread["risk_tier_effective_at"], "2026-06-01T00:00:00Z",
        "patient.risk_tier_effective_at",
    )


def test_risk_band_opens_at_exactly_twenty_five(api):
    """PRD §3.2: "The risk band follows from the rounded score by descending
    comparison: a score of at least 75 is `CRITICAL`; otherwise a score of at
    least 50 is `HIGH`; otherwise a score of at least 25 is `MODERATE`;
    otherwise the tier is `LOW`. All three thresholds are inclusive on their
    lower edge — a rounded score of exactly 25.00 is `MODERATE`, exactly 50.00
    is `HIGH`, exactly 75.00 is `CRITICAL`."
    PRD §3.2: "Separately, when the patient's `enrollment_status` is
    `PROSPECTIVE` and the computed tier is `MODERATE`, `HIGH` or `CRITICAL`, the
    patient is automatically moved to `ENROLLED` as part of the same request; a
    `LOW` tier leaves them `PROSPECTIVE`."

    Design: Corner/calculations/risk_tier_band_boundary_at_exactly_twentyfive
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    worker = fx.register_worker(employee_code="C-021")
    chw_headers = make_chw_headers(worker["id"])
    at_band = fx.add_patient(chw_headers, mrn="MRN-C21", full_name="Band Edge")
    below_band = fx.add_patient(chw_headers, mrn="MRN-C22", full_name="Band Below")
    instrument = fx.published_instrument(rescreen_cadence_days=90)

    on_edge = validate_success(
        api.administer_screening(
            create_screening_payload(
                at_band["id"], instrument["id"], at_band["version"],
                domain_scores={"FOOD": 1, "HOUSING": 1, "TRANSPORT": 1},
            ),
            chw_headers,
        ),
        201,
    )
    assert_score(on_edge["weighted_score"], 25.00, "on-edge weighted_score")
    assert on_edge["risk_tier"] == "MODERATE", (
        f"exactly 25.00 is MODERATE, got {on_edge['risk_tier']}"
    )
    assert fx.read_patient(at_band["id"])["enrollment_status"] == "ENROLLED", (
        "a MODERATE tier auto-enrols a PROSPECTIVE patient"
    )

    below = validate_success(
        api.administer_screening(
            create_screening_payload(
                below_band["id"], instrument["id"], below_band["version"],
                domain_scores={"FOOD": 1, "HOUSING": 1, "TRANSPORT": 0},
            ),
            chw_headers,
        ),
        201,
    )
    assert_score(below["weighted_score"], 20.00, "below-edge weighted_score")
    assert below["risk_tier"] == "LOW", (
        f"20.00 falls below 25 and is LOW, got {below['risk_tier']}"
    )
    below_patient = fx.read_patient(below_band["id"])
    assert below_patient["enrollment_status"] == "PROSPECTIVE", (
        "a LOW tier leaves the patient PROSPECTIVE"
    )
    assert below_patient["risk_tier"] == "LOW"


def test_retired_instrument_blocks_new_screenings_but_keeps_historic_scores(api):
    """PRD §3.2: "A screening that names an instrument in `DRAFT` or `RETIRED`
    is rejected at rung 9 with `ERR_INSTRUMENT_NOT_PUBLISHED`."
    PRD §3.2: "Publishing it moves `DRAFT` to `PUBLISHED` and increments its
    `version` by 1; retiring it moves `PUBLISHED` to `RETIRED`, again
    incrementing `version`, and leaves every screening already anchored to that
    revision untouched with its historical scores intact."

    Design: Corner/state_machines/retired_instrument_blocks_new_screenings
    """
    worker, patient, chw_headers = fx.program_with_patient(
        clock="2026-06-01T00:00:00Z", employee_code="C-015", enroll=False,
        mrn="MRN-C15", full_name="Retire Case",
    )
    instrument = fx.published_instrument(version_label="v1.0", rescreen_cadence_days=90)
    first = fx.administer_screening(
        chw_headers, patient["id"], instrument["id"],
        domain_scores={"FOOD": 3, "HOUSING": 2, "TRANSPORT": 1},
    )

    retired = validate_success(api.retire_instrument(instrument["id"], PROGRAM_ADMIN))
    assert retired["status"] == "RETIRED"

    fx.set_clock("2026-09-15T00:00:00Z")
    response = api.administer_screening(
        create_screening_payload(
            patient["id"], instrument["id"], fx.patient_version(patient["id"]),
            domain_scores={"FOOD": 4, "HOUSING": 4, "TRANSPORT": 4},
        ),
        chw_headers,
    )
    validate_error(response, ApiErrorId.ERR_INSTRUMENT_NOT_PUBLISHED.value, 409)

    preserved = fx.read_screening(first["id"])
    assert preserved["status"] == "SUBMITTED", (
        "retiring the instrument leaves the anchored screening untouched"
    )
    assert_score(preserved["weighted_score"], 55.00, "historic weighted_score")


def test_screening_with_a_stale_patient_version_is_rejected(api):
    """PRD §2.7: "Administering a screening requires `expected_patient_version`,
    carrying the client's last observed `version` of the `Patient` named by
    `patient_id`."
    PRD §2.7: "A mismatch is rejected with `ERR_STALE_PATIENT_VERSION` (HTTP
    412)."

    Design: Corner/validations/stale_patient_version_on_screening_rejected
    """
    worker, patient, chw_headers = fx.program_with_patient(
        clock="2026-06-01T00:00:00Z", employee_code="C-035", enroll=False,
        mrn="MRN-C35", full_name="Patient OCC Case",
    )
    observed_version = patient["version"]
    instrument = fx.published_instrument(rescreen_cadence_days=90)

    first = fx.administer_screening(
        chw_headers, patient["id"], instrument["id"],
        domain_scores={"FOOD": 3, "HOUSING": 2, "TRANSPORT": 1},
        expected_patient_version=observed_version,
    )

    fx.set_clock("2026-07-01T00:00:00Z")
    response = api.administer_screening(
        create_screening_payload(
            patient["id"], instrument["id"], observed_version,
            domain_scores={"FOOD": 4, "HOUSING": 4, "TRANSPORT": 4},
        ),
        chw_headers,
    )
    validate_error(response, ApiErrorId.ERR_STALE_PATIENT_VERSION.value, 412)

    unchanged = fx.read_screening(first["id"])
    assert unchanged["amendment_count"] == 0, (
        "the rejected re-screen folded no amendment into the existing row"
    )
    assert_score(unchanged["weighted_score"], 55.00, "weighted_score")
    assert_score(
        fx.read_patient(patient["id"])["risk_score"], 55.00, "patient.risk_score"
    )
