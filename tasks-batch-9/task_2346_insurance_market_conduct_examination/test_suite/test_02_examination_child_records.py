"""Examination and its child records: creation defaults, immutable workpapers
and the cross-parent identifier discipline.

Every expectation here is taken from PRD.md and nothing else.
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    COORDINATOR,
    EIC,
    SUPERVISOR,
    STANDARD_PARTICIPATING_STATES,
    assert_append_only_record,
    assert_collaboration,
    assert_company_response,
    assert_criticism,
    assert_data_call,
    assert_examination,
    assert_fieldwork_activity,
    assert_scope_area,
    collaboration_payload,
    company_response_payload,
    criticism_payload,
    data_call_payload,
    examination_payload,
    is_iso8601_timestamp,
    read_criticism,
    read_examination,
    read_insurer,
    register_insurer,
    scope_area_payload,
    setup_examination_in_criticism,
    setup_locked_examination,
    validate_error,
    validate_paginated,
    validate_success,
)

# The logical clock reads exactly 2026-08-01T00:00:00Z before any client sets it,
# and timestamps are rendered with three fractional digits.
CLOCK_INSTANT_PREFIX = "2026-08-01T00:00:00"
CLOCK_DATE = "2026-08-01"


def test_for_cause_examination_opens_in_scoping_with_zero_counters_and_no_lineage(api):
    """PRD §3.3: "A newly opened examination sits in `SCOPING` with `scope_locked` false, `predecessor_exam_id` unset, and every derived counter at zero — `scope_area_count`, `rejected_data_call_count`, `open_criticism_count`, `sustained_criticism_count`, `pending_restitution_cents`, `aggregate_restitution_cents` and `penalty_units_total`."

    PRD §3.3: "Opening raises the carrier's `open_exam_count` by 1 and, when a `cycle_id` was supplied, raises that cycle's `slots_committed` by 1."

    Design: Corner/entities/examination_creation_defaults_and_null_lineage_fields
    """
    insurer = register_insurer()

    examination = validate_success(
        api.open_examination(
            examination_payload(
                insurer["id"],
                exam_type="TARGETED_EXAM",
                mode="DESK",
                lead_state_code="NV",
                fieldwork_start_date="2026-09-01",
                fieldwork_end_date="2026-11-30",
            ),
            SUPERVISOR,
        ),
        201,
    )
    assert_examination(examination)

    assert examination["status"] == "SCOPING"
    assert examination["scope_locked"] is False
    # No cycle created it and no publication created it, so both lineage links are unset.
    assert examination.get("cycle_id") is None
    assert examination.get("predecessor_exam_id") is None

    for counter in (
        "scope_area_count",
        "rejected_data_call_count",
        "open_criticism_count",
        "sustained_criticism_count",
        "pending_restitution_cents",
        "aggregate_restitution_cents",
        "penalty_units_total",
    ):
        assert examination[counter] == 0, f"{counter} starts at zero"

    assert read_insurer(insurer["id"])["open_exam_count"] == 1


def test_examination_open_rejects_equal_window_bad_state_code_and_unknown_exam_type(api):
    """PRD §3.3: "A `SupervisingExaminer` may open a for-cause or targeted examination directly by supplying the subject `insurer_id`, an `exam_type` of either `MARKET_CONDUCT_EXAM` or `TARGETED_EXAM`, a `mode` of `ON_SITE` or `DESK`, a `lead_state_code` of exactly two uppercase letters, and the fieldwork occupancy window as `fieldwork_start_date` and `fieldwork_end_date`, the latter strictly after the former."

    Design: Corner/entities/examination_fieldwork_dates_must_be_strictly_ordered
    """
    insurer = register_insurer()

    # fieldwork_end_date is the exclusive edge of the window, so equality is malformed.
    validate_error(
        api.open_examination(
            examination_payload(
                insurer["id"],
                fieldwork_start_date="2026-09-01",
                fieldwork_end_date="2026-09-01",
            ),
            SUPERVISOR,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    # lead_state_code must be exactly two uppercase letters.
    validate_error(
        api.open_examination(
            examination_payload(insurer["id"], lead_state_code="NEV"),
            SUPERVISOR,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    # exam_type outside the declared set.
    validate_error(
        api.open_examination(
            examination_payload(insurer["id"], exam_type="SPOT_CHECK"),
            SUPERVISOR,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    items, meta = validate_paginated(
        api.list_examinations(SUPERVISOR, {"insurer_id": insurer["id"]})
    )
    assert meta["total_count"] == 0, "no rejected attempt persisted an examination"
    assert items == []


def test_scope_area_error_tolerance_defaults_come_from_the_per_area_statutory_table(api):
    """PRD §3.3: "An optional `error_tolerance_pct` between 0.00 and 100.00 inclusive overrides the statutory default; when it is omitted the default is read from the per-area statutory table — 7.00 percent for `UNDERWRITING`, 5.00 percent for `RATING`, 3.00 percent for `CLAIMS` and 10.00 percent for `PRODUCER`."

    PRD §3.3: "Each new area starts in `PLANNED`, raises the examination's `scope_area_count` by 1 and increments the examination's `version` by 1."

    Design: Corner/entities/scope_area_tolerance_default_is_per_area_statutory
    """
    insurer = register_insurer()
    examination = validate_success(
        api.open_examination(
            examination_payload(insurer["id"], mode="ON_SITE"), SUPERVISOR
        ),
        201,
    )
    exam_id = examination["id"]

    created = {}
    for area, population_size, extra in (
        ("UNDERWRITING", 4000, {}),
        ("RATING", 500, {}),
        ("CLAIMS", 4000, {}),
        ("PRODUCER", 900, {"error_tolerance_pct": 12.50}),
    ):
        created[area] = validate_success(
            api.create_scope_area(
                exam_id,
                scope_area_payload(
                    area, population_size=population_size, sample_size=10, **extra
                ),
                EIC,
            ),
            201,
        )
        assert_scope_area(created[area])

    assert created["UNDERWRITING"]["error_tolerance_pct"] == 7.00
    assert created["RATING"]["error_tolerance_pct"] == 5.00
    assert created["CLAIMS"]["error_tolerance_pct"] == 3.00
    # The explicit value overrides the 10.00 PRODUCER default on that row alone.
    assert created["PRODUCER"]["error_tolerance_pct"] == 12.50

    for area, area_record in created.items():
        assert area_record["status"] == "PLANNED", f"{area} starts in PLANNED"
        assert area_record["reviewed_sample_count"] == 0
        assert area_record["error_count"] == 0
        assert area_record["material_error_count"] == 0
        assert area_record["error_rate_pct"] == 0.00
        assert area_record["material_error_rate_pct"] == 0.00
        assert area_record["tolerance_breached"] is False
        assert area_record["escalation_required"] is False

    refreshed = read_examination(exam_id)
    assert refreshed["scope_area_count"] == 4
    assert refreshed["status"] == "SCOPING"


def test_data_call_defaults_its_sampling_method_and_stamps_issued_date_from_the_clock(api):
    """PRD §3.4: "An optional `sampling_method` defaults to `SYSTEMATIC_INTERVAL`, which is currently the only methodology the statute recognises."

    PRD §3.4: "The server stamps `issued_date` from the date part of the logical clock and opens the call in `ISSUED` with `records_received` 0, `is_late` false, `days_late` 0, `completeness_pct` 0.00, `effective_completeness_pct` 0.00, `sample_draw_interval` 0 and `samples_drawn_count` 0."

    Design: Corner/entities/data_call_creation_defaults_sampling_method_and_stamps_the_clock
    """
    scenario = setup_locked_examination(areas=(("CLAIMS", 4000, 10),), mode="ON_SITE")

    data_call = validate_success(
        api.create_data_call(
            scenario["scope_area_id"],
            data_call_payload(records_requested=4000, response_due_date="2026-09-15"),
            EIC,
        ),
        201,
    )
    assert_data_call(data_call)

    assert data_call["sampling_method"] == "SYSTEMATIC_INTERVAL"
    assert data_call["status"] == "ISSUED"
    # Not the response_due_date and not wall-clock time: the logical clock's date part.
    assert data_call["issued_date"] == CLOCK_DATE
    assert data_call["records_received"] == 0
    assert data_call["is_late"] is False
    assert data_call["days_late"] == 0
    assert data_call["completeness_pct"] == 0.00
    assert data_call["effective_completeness_pct"] == 0.00
    assert data_call["sample_draw_interval"] == 0
    assert data_call["samples_drawn_count"] == 0

    items, meta = validate_paginated(
        api.list_scope_area_data_calls(scenario["scope_area_id"], EIC)
    )
    assert meta["total_count"] == 1
    assert items[0]["id"] == data_call["id"]
    assert items[0]["scope_area_id"] == scenario["scope_area_id"]


def test_fieldwork_activity_is_append_only_and_derives_documented_from_its_exhibit(api):
    """PRD §3.6: "The server stamps `conducted_at` from the logical clock and computes `documented`, which is true only when the `summary` runs to at least 20 characters **and** an `evidence_ref` is present and non-empty; an activity lacking an exhibit reference is left undocumented."

    PRD §2.4: "Two record types are append-only workpapers and are therefore exempt: a `FieldworkActivity` and a `CompanyResponse` each carry only `id` and `created_at`."

    PRD §3.6: "Workpapers may be listed per examination, filtered optionally by `activity_type` or `area`."

    Design: Corner/entities/fieldwork_activity_is_immutable_and_carries_no_version
    """
    scenario = setup_locked_examination(areas=(("CLAIMS", 4000, 10),), mode="ON_SITE")
    exam_id = scenario["exam_id"]

    walkthrough = validate_success(
        api.create_fieldwork_activity(
            exam_id,
            {
                "activity_type": "SYSTEM_WALKTHROUGH",
                "area": "CLAIMS",
                "participant_name": "R. Vance",
                "participant_title": "VP Claims Operations",
                "summary": "Walked the claims adjudication platform end to end with the carrier.",
                "evidence_ref": "WP-CLM-01",
            },
            EIC,
        ),
        201,
    )
    assert_fieldwork_activity(walkthrough)
    assert walkthrough["documented"] is True

    # evidence_ref omitted entirely: the workpaper is left undocumented.
    no_exhibit = validate_success(
        api.create_fieldwork_activity(
            exam_id,
            {
                "activity_type": "INTERVIEW",
                "area": "CLAIMS",
                "participant_name": "L. Ortiz",
                "participant_title": "Claims Manager",
                "summary": "Interviewed the claims manager on prompt-pay handling and denials.",
            },
            EIC,
        ),
        201,
    )
    assert no_exhibit["documented"] is False

    # The area is matched to a scope area by value rather than by reference, so a
    # RATING workpaper is accepted on an examination whose only area is CLAIMS.
    rating_activity = validate_success(
        api.create_fieldwork_activity(
            exam_id,
            {
                "activity_type": "INTERVIEW",
                "area": "RATING",
                "participant_name": "S. Nakamura",
                "participant_title": "Chief Actuary",
                "summary": "Interviewed the chief actuary on rate filing controls.",
                "evidence_ref": "WP-RT-01",
            },
            EIC,
        ),
        201,
    )
    assert rating_activity["area"] == "RATING"
    assert rating_activity["documented"] is True

    # A summary shorter than 20 characters is a malformed request.
    validate_error(
        api.create_fieldwork_activity(
            exam_id,
            {
                "activity_type": "INTERVIEW",
                "area": "CLAIMS",
                "participant_name": "T. Byrne",
                "participant_title": "Adjuster",
                "summary": "Too short.",
                "evidence_ref": "WP-CLM-03",
            },
            EIC,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    assert is_iso8601_timestamp(walkthrough["conducted_at"])
    assert walkthrough["conducted_at"].startswith(CLOCK_INSTANT_PREFIX)
    assert_append_only_record(walkthrough, "FieldworkActivity")

    items, meta = validate_paginated(
        api.list_fieldwork_activities(exam_id, EIC, {"activity_type": "INTERVIEW"})
    )
    assert meta["total_count"] == 2, "the rejected fourth workpaper persisted nothing"
    for item in items:
        assert item["activity_type"] == "INTERVIEW"
        assert_append_only_record(item, "FieldworkActivity")


def test_company_response_is_append_only_and_numbers_its_own_round(api):
    """PRD §3.7: "Each answer materialises a `CompanyResponse` carrying its `criticism_id`, its `round_number` — one greater than the criticism's `response_round` before the answer, and therefore equal to the criticism's `response_round` immediately afterwards — and a `submitted_at` stamp from the logical clock."

    PRD §3.7: "The answer supplies a `position` of `CONCUR`, `PARTIAL_CONCUR` or `DISPUTE`, a `narrative` of at least 20 characters, and optionally a `remediation_offer_cents` figure naming restitution the carrier offers to pay voluntarily, which defaults to 0 and must be zero or greater."

    Design: Corner/entities/company_response_is_immutable_and_numbers_its_own_round
    """
    scenario = setup_examination_in_criticism()
    criticism = validate_success(
        api.issue_criticism(
            criticism_payload(
                scenario["exam_id"], scenario["scope_area_id"], "MATERIAL", 3
            ),
            EIC,
        ),
        201,
    )
    criticism_id = criticism["id"]

    payload = company_response_payload(
        "PARTIAL_CONCUR",
        narrative="The carrier concurs on one file and disputes the other two.",
    )
    payload.pop("remediation_offer_cents", None)

    response = validate_success(
        api.create_company_response(
            criticism_id, payload, scenario["respondent_headers"]
        ),
        201,
    )
    assert_company_response(response)

    # round_number is computed from the parent criticism, never supplied.
    assert response["round_number"] == 1
    assert response["remediation_offer_cents"] == 0
    assert response["criticism_id"] == criticism_id
    assert is_iso8601_timestamp(response["submitted_at"])
    assert response["submitted_at"].startswith(CLOCK_INSTANT_PREFIX)
    assert_append_only_record(response, "CompanyResponse")

    items, meta = validate_paginated(
        api.list_company_responses(criticism_id, SUPERVISOR, {"position": "PARTIAL_CONCUR"})
    )
    assert meta["total_count"] == 1
    assert items[0]["round_number"] == 1
    assert items[0]["criticism_id"] == criticism_id

    answered = read_criticism(criticism_id)
    assert answered["status"] == "RESPONDED"
    assert answered["response_round"] == 1


def test_criticism_scope_area_must_belong_to_the_examination_named_in_its_body(api):
    """PRD §2.8: "When a criticism is issued, its body carries both an `exam_id` and a `scope_area_id`; an `exam_id` matching no examination is `ERR_EXAMINATION_NOT_FOUND`, and a `scope_area_id` that either matches no scope area **or** matches one whose own `exam_id` differs from the supplied `exam_id` is `ERR_EXAM_RECORD_NOT_FOUND`."

    PRD §3.6: "Under `POPULATION_EXTRAPOLATED`, the summed underpayment is first divided by the reviewed-sample count and **that per-file average is rounded half up to a whole cent**, and only then is the rounded average multiplied by the area's `population_size` to give `restitution_exposure_cents`."

    Design: Corner/entities/criticism_scope_area_must_belong_to_the_named_examination
    """
    # Examination E1: a TESTED CLAIMS area with three MATERIAL errors, in CRITICISM.
    scenario = setup_examination_in_criticism()
    exam_id = scenario["exam_id"]

    # Examination E2 on a second carrier, with its own PLANNED CLAIMS area.
    other = setup_locked_examination(
        areas=(("CLAIMS", 4000, 10),),
        insurer_overrides={"name": "Cedar Indemnity Company", "naic_code": "10003"},
        mode="ON_SITE",
    )
    foreign_area_id = other["scope_area_id"]

    # The scope area exists but hangs off a different examination.
    validate_error(
        api.issue_criticism(
            criticism_payload(exam_id, foreign_area_id, "MATERIAL", 3), EIC
        ),
        ApiErrorId.ERR_EXAM_RECORD_NOT_FOUND.value,
    )

    # A scope area identifier that resolves to nothing at all lands on the same error.
    validate_error(
        api.issue_criticism(
            criticism_payload(exam_id, NON_EXISTENT_UUID, "MATERIAL", 3), EIC
        ),
        ApiErrorId.ERR_EXAM_RECORD_NOT_FOUND.value,
    )

    rejected_state = read_examination(exam_id)
    assert rejected_state["open_criticism_count"] == 0
    assert rejected_state["pending_restitution_cents"] == 0

    criticism = validate_success(
        api.issue_criticism(
            criticism_payload(exam_id, scenario["scope_area_id"], "MATERIAL", 3), EIC
        ),
        201,
    )
    assert_criticism(criticism)
    assert criticism["status"] == "ISSUED"
    assert criticism["restitution_method"] == "POPULATION_EXTRAPOLATED"
    # (25000 + 18000 + 7333) / 10 = 5033.3 -> 5033 cents per file, times 4000 files.
    assert criticism["restitution_exposure_cents"] == 20_132_000

    accepted_state = read_examination(exam_id)
    assert accepted_state["open_criticism_count"] == 1
    assert accepted_state["pending_restitution_cents"] == 20_132_000


def test_collaboration_creation_elects_its_lead_state_and_counts_its_roster(api):
    """PRD §3.9: "The collaboration records `participant_count` as the roster's length, opens in `LEAD_ASSIGNED` with `allocated_total_cents` of 0, and elects its own `lead_state_code`."

    PRD §3.9: "Eligible participants are ranked by `policy_count_in_state` descending, and ties are broken by `state_code` ascending in plain lexicographic order on the two-letter code."

    PRD §3.9: "This selector writes only the collaboration's own `lead_state_code`; the examination's separate `lead_state_code` is left untouched."

    Design: Corner/entities/multistate_collaboration_creation_computes_lead_and_participant_count
    """
    scenario = setup_locked_examination(
        areas=(("CLAIMS", 4000, 10),), mode="ON_SITE", lead_state_code="CA"
    )

    collaboration = validate_success(
        api.open_collaboration(
            scenario["exam_id"],
            collaboration_payload(
                STANDARD_PARTICIPATING_STATES, call_reference="NAIC-CAWG-2026-0117"
            ),
            COORDINATOR,
        ),
        201,
    )
    assert_collaboration(collaboration)

    assert collaboration["status"] == "LEAD_ASSIGNED"
    # NV carries the highest policy_count_in_state among the resourced states; UT
    # has no examiner resources and is therefore ineligible for the election.
    assert collaboration["lead_state_code"] == "NV"
    assert collaboration["participant_count"] == 3
    assert collaboration["allocated_total_cents"] == 0
    for participant in collaboration["participating_states"]:
        assert participant["allocated_cents"] == 0

    assert read_examination(scenario["exam_id"])["lead_state_code"] == "CA"

    items, meta = validate_paginated(
        api.list_collaborations(scenario["exam_id"], COORDINATOR)
    )
    assert meta["total_count"] == 1
    assert items[0]["id"] == collaboration["id"]
    assert items[0]["exam_id"] == scenario["exam_id"]
