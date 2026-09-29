"""
The three uniqueness scopes, the four remaining not-found families, and the two
refusals that guard who may own a report and who may review it.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import (
    make_bridge_inspector_headers,
    make_qa_reviewer_headers,
    permit_officer_headers,
    program_admin_headers,
)

FIRST_WINDOW_START = "2026-09-02T08:00:00Z"
FIRST_WINDOW_END = "2026-09-02T16:00:00Z"
SECOND_WINDOW_START = "2026-09-10T08:00:00Z"
SECOND_WINDOW_END = "2026-09-10T16:00:00Z"

# A sound deck of 600 square metres, every unit in condition state one, which is
# the row used to prove that `element_key` uniqueness is scoped to one report.
SOUND_DECK = f.element_condition_payload(
    "DECK", "SQM", 600, 600, 0, 0, 0, photo_count=1, defect_notes="Deck sound"
)


def _two_structures_each_holding_a_draft_report(client, roster, bridge):
    """
    Cedar Creek with a `DRAFT` report carrying one deck row, and Willow Slough
    with a `DRAFT` report of its own eight days later, plus a filed permit
    application over Cedar Creek so all three uniqueness scopes are occupied.
    """
    willow = fx.create_bridge(
        client,
        f.bridge_payload(
            "STR-000002",
            name="Willow Slough Bridge",
            structure_type="CULVERT",
            deck_area_sqm=600,
            year_built=1988,
            adt=3000,
            detour_length_km=2.0,
        ),
    )
    fx.receive_permit(
        client,
        "OW-2026-0012",
        [bridge["id"]],
        carrier_name="Northline Heavy Haul",
        axle_loads_tons=[10.0, 10.0, 10.0, 6.0],
        speed_category="NORMAL",
    )
    first = fx.open_inspection(
        client,
        bridge["id"],
        roster,
        field_window_start=FIRST_WINDOW_START,
        field_window_end=FIRST_WINDOW_END,
    )
    second = fx.open_inspection(
        client,
        willow["id"],
        roster,
        field_window_start=SECOND_WINDOW_START,
        field_window_end=SECOND_WINDOW_END,
    )
    fx.add_element(client, first["id"], roster, f.BASELINE_DECK)
    return {"willow": willow, "first": first, "second": second}


def test_the_three_uniqueness_scopes_each_refuse_a_repeat(client, roster, bridge):
    """
    A re-entered structure number, a re-used permit number and a repeated element
    key are three different collisions with three different codes, and all three
    answer 409.

    PRD §2.8: "10. **Uniqueness** — `nbi_structure_number` unique across the
    inventory (`ERR_DUPLICATE_STRUCTURE_NUMBER`), `permit_number` unique across
    permit applications (`ERR_DUPLICATE_PERMIT_NUMBER`), and `element_key` unique
    within one inspection (`ERR_DUPLICATE_ELEMENT_KEY`). All three are HTTP 409, and
    they apply respectively to structure creation, permit-application creation and
    element-condition creation."

    Design: Corner/errors/duplicate_structure_number_permit_number_and_element_key_rejected
    """
    setup = _two_structures_each_holding_a_draft_report(client, roster, bridge)

    duplicate_structure = client.create_bridge(
        f.bridge_payload(
            "STR-000001",
            name="Cedar Creek Bridge (re-entered)",
            owner_agency="Marion County",
            structure_type="TRUSS",
            deck_area_sqm=200,
            year_built=1960,
            adt=400,
            detour_length_km=1.0,
        ),
        program_admin_headers(),
    )
    duplicate_permit = client.create_permit_application(
        f.permit_application_payload(
            "OW-2026-0012",
            [setup["willow"]["id"]],
            carrier_name="Second Carrier",
            axle_loads_tons=[9.0, 9.0],
            speed_category="NORMAL",
        ),
        permit_officer_headers(),
    )
    duplicate_element = client.create_element_condition(
        setup["first"]["id"],
        f.element_condition_payload(
            "DECK",
            "SQM",
            500,
            500,
            0,
            0,
            0,
            photo_count=1,
            defect_notes="Second pass over the same deck",
        ),
        roster.inspector_headers,
    )

    validate_error(duplicate_structure, e.ERR_DUPLICATE_STRUCTURE_NUMBER, 409)
    validate_error(duplicate_permit, e.ERR_DUPLICATE_PERMIT_NUMBER, 409)
    validate_error(duplicate_element, e.ERR_DUPLICATE_ELEMENT_KEY, 409)


def test_none_of_the_three_repeats_left_a_trace(client, roster, bridge):
    """
    The inventory still holds two structures rather than three, the report still
    holds its single deck row with the quantity that row reported, and neither the
    structure nor the report recorded a mutation.

    PRD §3.1: "The `nbi_structure_number` is the National Bridge Inventory structure
    number and must be unique across the whole inventory, between 1 and 15 characters
    long; a collision is reported as `ERR_DUPLICATE_STRUCTURE_NUMBER`."
    PRD §2.5: "a system-managed counter that increments by one on every mutation of
    the resource, including mutations that only touch derived fields."

    Design: Corner/errors/duplicate_structure_number_permit_number_and_element_key_rejected
    """
    setup = _two_structures_each_holding_a_draft_report(client, roster, bridge)
    structure_before = fx.read_bridge(client, bridge["id"])
    report_before = fx.read_inspection(client, setup["first"]["id"])

    validate_error(
        client.create_bridge(
            f.bridge_payload("STR-000001", name="Cedar Creek Bridge (re-entered)"),
            program_admin_headers(),
        ),
        e.ERR_DUPLICATE_STRUCTURE_NUMBER,
        409,
    )
    validate_error(
        client.create_element_condition(
            setup["first"]["id"],
            f.element_condition_payload("DECK", "SQM", 500, 500, 0, 0, 0),
            roster.inspector_headers,
        ),
        e.ERR_DUPLICATE_ELEMENT_KEY,
        409,
    )

    assert validate_paginated(client.list_bridges(program_admin_headers()))[1][
        "total_count"
    ] == 2
    report_after = fx.read_inspection(client, setup["first"]["id"])
    assert report_after["element_count"] == 1
    assert report_after["reported_quantity_total"] == 1000
    a.assert_version_unchanged(
        report_after["version"], report_before["version"], "inspection"
    )
    a.assert_version_unchanged(
        fx.read_bridge(client, bridge["id"])["version"],
        structure_before["version"],
        "bridge",
    )


def test_the_same_element_key_on_a_different_report_is_accepted(client, roster, bridge):
    """
    `DECK` is already taken on the first report and free on the second, because the
    scope of the constraint is one inspection rather than the whole element
    collection — and the accepted row scores a perfect index.

    PRD §3.2: "Each row names an `element_key` from `DECK`, `JOINT`, `RAILING`,
    `GIRDER`, `BEARING`, `PIER_CAP`, `COLUMN` and `ABUTMENT`, and each key may appear
    at most once per report — a repeat is `ERR_DUPLICATE_ELEMENT_KEY`."

    Design: Corner/errors/duplicate_structure_number_permit_number_and_element_key_rejected
    """
    setup = _two_structures_each_holding_a_draft_report(client, roster, bridge)
    validate_error(
        client.create_element_condition(
            setup["first"]["id"],
            f.element_condition_payload("DECK", "SQM", 500, 500, 0, 0, 0),
            roster.inspector_headers,
        ),
        e.ERR_DUPLICATE_ELEMENT_KEY,
        409,
    )

    row = get_success_data(
        client.create_element_condition(
            setup["second"]["id"], SOUND_DECK, roster.inspector_headers
        ),
        201,
    )

    assert row["element_key"] == "DECK"
    assert row["inspection_id"] == setup["second"]["id"]
    a.assert_element_derived_fields(row, 600, 600, 0, 0, 0)
    assert row["element_health_index"] == 100.00
    assert fx.read_inspection(client, setup["second"]["id"])["element_count"] == 1


# ─── The four remaining not-found families ──────────────────────────────────
def _four_unresolvable_references(client, roster, bridge):
    """
    One unresolvable identifier used four ways: as a body foreign key naming a
    person, and as the path identifier of a scour evaluation, a permit application
    and a project candidate.
    """
    return {
        "personnel": client.create_inspection(
            bridge["id"],
            f.inspection_payload(
                NON_EXISTENT_UUID, FIRST_WINDOW_START, FIRST_WINDOW_END
            ),
            roster.inspector_headers,
        ),
        "rating": client.get_scour_evaluation(
            NON_EXISTENT_UUID, roster.engineer_headers
        ),
        "permit": client.get_permit_application(
            NON_EXISTENT_UUID, permit_officer_headers()
        ),
        "program": client.get_project_candidate(
            NON_EXISTENT_UUID, roster.district_headers
        ),
    }


def test_the_family_is_chosen_by_the_kind_of_record_that_is_missing(
    client, roster, bridge
):
    """
    The same unresolvable identifier produces four different codes, one per record
    family: a dangling person in a body, and a missing scour evaluation, permit
    application and project candidate in a path.

    PRD §2.8: "The system uses six family-scoped not-found codes rather than one per
    entity: `ERR_BRIDGE_NOT_FOUND` for a missing structure, `ERR_PERSONNEL_NOT_FOUND`
    for a missing roster entry, `ERR_INSPECTION_RECORD_NOT_FOUND` for a missing
    inspection, element condition, critical finding or notification log,
    `ERR_RATING_RECORD_NOT_FOUND` for a missing load rating, scour evaluation or plan
    of action, `ERR_PERMIT_NOT_FOUND` for a missing permit application or per-bridge
    analysis, and `ERR_PROGRAM_RECORD_NOT_FOUND` for a missing program cycle, project
    candidate or federal submission. Each of these is HTTP 404."

    Design: Corner/errors/unknown_personnel_rating_permit_and_program_ids_not_found
    """
    answers = _four_unresolvable_references(client, roster, bridge)

    validate_error(answers["personnel"], e.ERR_PERSONNEL_NOT_FOUND, 404)
    validate_error(answers["rating"], e.ERR_RATING_RECORD_NOT_FOUND, 404)
    validate_error(answers["permit"], e.ERR_PERMIT_NOT_FOUND, 404)
    validate_error(answers["program"], e.ERR_PROGRAM_RECORD_NOT_FOUND, 404)


def test_the_body_foreign_key_is_reached_because_the_path_resolved(
    client, roster, bridge
):
    """
    The inspection create is a nested create under a structure that does exist, so
    the 404 it earns is about the person the payload named, not about the path — and
    no report was opened by the refusal.

    PRD §2.8: "Foreign keys supplied in a request *body* are validated the same way
    and with the same codes."
    PRD §2.8: "a nested create under a structure that does not exist fails on the
    structure, never on the child."

    Design: Corner/errors/unknown_personnel_rating_permit_and_program_ids_not_found
    """
    answers = _four_unresolvable_references(client, roster, bridge)

    validate_error(answers["personnel"], e.ERR_PERSONNEL_NOT_FOUND, 404)
    assert (
        answers["personnel"].json()["data"]["error_id"] != e.ERR_BRIDGE_NOT_FOUND
    ), "the structure in the path exists, so it cannot be the reported failure"
    reports = fx.inspections_for_bridge(client, bridge["id"])
    assert reports["rows"] == []
    assert reports["meta"]["total_count"] == 0


def test_every_one_of_the_four_answers_is_the_bare_error_envelope(
    client, roster, bridge
):
    """
    None of the four refusals leaks a resource-shaped payload: each `data` object
    carries exactly the machine-readable code and the human-readable message.

    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the
    specific error."
    PRD §2.2: "The `message` provides a human-readable explanation of what went wrong."
    PRD §2.2: "The `meta` object for error responses contains only `api_request_id`
    and `api_request_timestamp`."

    Design: Corner/errors/unknown_personnel_rating_permit_and_program_ids_not_found
    """
    answers = _four_unresolvable_references(client, roster, bridge)

    for label, response in answers.items():
        body = response.json()
        assert response.status_code == 404, label
        assert body["response_type"] == "error", label
        assert set(body["data"].keys()) == {"error_id", "message"}, label
        assert isinstance(body["data"]["message"], str) and body["data"]["message"], label
        assert set(body["meta"].keys()) == {
            "api_request_id",
            "api_request_timestamp",
        }, label


# ─── Naming somebody else as the team leader ─────────────────────────────────
def _a_second_certified_inspector(client):
    """Owen Inspector, as fully certified as Ivy and as current."""
    return fx.create_person(
        client,
        f.personnel_payload(
            "Owen Inspector", fx.CURRENT_REFRESHER, team_leader_certified=True
        ),
    )


def test_filing_a_report_under_another_qualified_inspectors_identifier_is_refused(
    client, roster, bridge
):
    """
    Owen names Ivy as the team leader. Ivy exists and is qualified, so neither a 404
    nor a 422 is available: the refusal is about identity.

    PRD §2.1: "Because these roles are entity-backed, an operation whose payload
    names a person — a `team_leader_id` on a new inspection, an `evaluated_by_id` on a
    scour evaluation, an `approved_by_id` on a plan-of-action decision — must name the
    acting user's own identifier."
    PRD §2.1: "Naming somebody else's identifier is rejected with
    `ERR_IDENTITY_MISMATCH` (HTTP 403): a `BridgeInspector` may not file an inspection
    under another inspector's identifier, and a `RatingEngineer` may not seal a rating
    under another engineer's identifier."

    Design: Corner/errors/inspection_create_naming_another_inspector_returns_403
    """
    owen = _a_second_certified_inspector(client)

    response = client.create_inspection(
        bridge["id"],
        f.inspection_payload(
            roster.inspector_id, FIRST_WINDOW_START, FIRST_WINDOW_END
        ),
        make_bridge_inspector_headers(owen["id"]),
    )

    validate_error(response, e.ERR_IDENTITY_MISMATCH, 403)
    assert fx.read_person(client, roster.inspector_id)["team_leader_certified"] is True
    assert fx.read_person(client, roster.inspector_id)["qualification_status"] == "CURRENT"
    assert fx.inspections_for_bridge(client, bridge["id"])["meta"]["total_count"] == 0


def test_the_identical_window_filed_under_the_callers_own_identifier_opens(
    client, roster, bridge
):
    """
    Only the named identifier was ever wrong: the same window filed by Owen under
    Owen opens a draft owned by him, which leaves the structure holding exactly one
    report after both attempts.

    PRD §2.8: "6. **Self-identity** — an entity-backed role naming a person in the
    payload names itself, else `ERR_IDENTITY_MISMATCH` (403). Applies to inspection
    creation, scour-evaluation creation, and plan-of-action decision."
    PRD §3.2: "a `team_leader_id` naming the certified team leader who will own the
    report".

    Design: Corner/errors/inspection_create_naming_another_inspector_returns_403
    """
    owen = _a_second_certified_inspector(client)
    validate_error(
        client.create_inspection(
            bridge["id"],
            f.inspection_payload(
                roster.inspector_id, FIRST_WINDOW_START, FIRST_WINDOW_END
            ),
            make_bridge_inspector_headers(owen["id"]),
        ),
        e.ERR_IDENTITY_MISMATCH,
        403,
    )

    opened = get_success_data(
        client.create_inspection(
            bridge["id"],
            f.inspection_payload(owen["id"], FIRST_WINDOW_START, FIRST_WINDOW_END),
            make_bridge_inspector_headers(owen["id"]),
        ),
        201,
    )

    assert opened["team_leader_id"] == owen["id"]
    assert opened["status"] == "DRAFT"
    assert fx.inspections_for_bridge(client, bridge["id"])["meta"]["total_count"] == 1


# ─── Who may claim a report for review ───────────────────────────────────────
def _a_submitted_report_and_an_uncertified_reviewer(client, roster, bridge):
    """
    Ivy's own `SUBMITTED` report, plus Nate Novice, who is current but has never
    been certified as a team leader and so may not review one either.
    """
    nate = fx.create_person(
        client,
        f.personnel_payload(
            "Nate Novice", fx.CURRENT_REFRESHER, team_leader_certified=False
        ),
    )
    drafted = fx.draft_report_with_baseline(
        client,
        bridge["id"],
        roster,
        field_window_start=FIRST_WINDOW_START,
        field_window_end=FIRST_WINDOW_END,
    )
    fx.set_clock(client, c.FIELD_DAY_CLOCK)
    submitted = fx.submit_report(client, drafted["inspection"]["id"], roster)
    return {"nate": nate, "inspection": submitted}


def test_the_reports_own_team_leader_may_not_claim_it_for_review(
    client, roster, bridge
):
    """
    Ivy wears the reviewer role and claims her own report. She is certified and
    current, so qualification cannot be the objection — the duties rule is.

    PRD §2.10: "The quality-assurance reviewer of an inspection may not be that
    inspection's team leader."
    PRD §2.8: "11. **Segregation of duties** — `ERR_SEGREGATION_OF_DUTIES` (403),
    detailed in §2.10. Applies to QA claim, QA decision, load-rating approval,
    federal-submission review, and restriction imposition."

    Design: Corner/errors/qa_claim_by_the_own_team_leader_returns_403_and_by_uncertified_reviewer_rejected
    """
    setup = _a_submitted_report_and_an_uncertified_reviewer(client, roster, bridge)

    response = client.qa_claim_inspection(
        setup["inspection"]["id"], make_qa_reviewer_headers(roster.inspector_id)
    )

    validate_error(response, e.ERR_SEGREGATION_OF_DUTIES, 403)
    assert fx.read_person(client, roster.inspector_id)["team_leader_certified"] is True
    assert (
        fx.read_person(client, roster.inspector_id)["qualification_status"] == "CURRENT"
    )


def test_an_uncertified_reviewer_is_refused_after_the_duties_check_has_passed(
    client, roster, bridge
):
    """
    Nate is not the team leader, so the duties rule is satisfied and the next rung is
    reached: he lacks the certificate a reviewer needs, which is a 422 rather than a
    403. After both refusals the report is still waiting with no reviewer attached.

    PRD §2.10: "A QA reviewer who lacks `team_leader_certified` or whose refresher has
    expired is rejected with `ERR_QA_REVIEWER_NOT_QUALIFIED` (HTTP 422) at the moment
    of the claim or of the decision."
    PRD §2.8: "13. **QA reviewer qualification** — `ERR_QA_REVIEWER_NOT_QUALIFIED`
    (422). Applies to QA claim and QA decision."

    Design: Corner/errors/qa_claim_by_the_own_team_leader_returns_403_and_by_uncertified_reviewer_rejected
    """
    setup = _a_submitted_report_and_an_uncertified_reviewer(client, roster, bridge)
    validate_error(
        client.qa_claim_inspection(
            setup["inspection"]["id"], make_qa_reviewer_headers(roster.inspector_id)
        ),
        e.ERR_SEGREGATION_OF_DUTIES,
        403,
    )

    response = client.qa_claim_inspection(
        setup["inspection"]["id"], make_qa_reviewer_headers(setup["nate"]["id"])
    )

    validate_error(response, e.ERR_QA_REVIEWER_NOT_QUALIFIED, 422)
    assert fx.read_person(client, setup["nate"]["id"])["team_leader_certified"] is False
    still_waiting = fx.read_inspection(client, setup["inspection"]["id"])
    assert still_waiting["status"] == "SUBMITTED"
    assert still_waiting["qa_reviewer_id"] is None
    assert still_waiting["qa_claimed_at"] is None


def test_a_third_certified_reviewer_takes_the_report_into_review(
    client, roster, bridge
):
    """
    Quinn is neither the team leader nor uncertified, so the claim lands: the report
    moves into review, records who took it, and stamps the claim from the clock the
    two refusals never advanced.

    PRD §3.3: "A `QaReviewer` claiming a report takes it from `SUBMITTED` to `IN_QA`,
    which sets the report's `qa_reviewer_id` to the claiming user's `X-User-ID` and
    stamps `qa_claimed_at` from the logical clock."

    Design: Corner/errors/qa_claim_by_the_own_team_leader_returns_403_and_by_uncertified_reviewer_rejected
    """
    setup = _a_submitted_report_and_an_uncertified_reviewer(client, roster, bridge)
    validate_error(
        client.qa_claim_inspection(
            setup["inspection"]["id"], make_qa_reviewer_headers(roster.inspector_id)
        ),
        e.ERR_SEGREGATION_OF_DUTIES,
        403,
    )
    validate_error(
        client.qa_claim_inspection(
            setup["inspection"]["id"], make_qa_reviewer_headers(setup["nate"]["id"])
        ),
        e.ERR_QA_REVIEWER_NOT_QUALIFIED,
        422,
    )

    claimed = validate_success(
        client.qa_claim_inspection(
            setup["inspection"]["id"], roster.reviewer_headers
        ),
        200,
    )

    assert claimed["status"] == "IN_QA"
    assert claimed["qa_reviewer_id"] == roster.reviewer_id
    a.assert_instant_equals(
        claimed["qa_claimed_at"], c.FIELD_DAY_CLOCK, "qa_claimed_at"
    )


# ─── Two submit gates reached from the same report, in ladder order ──────────
UNDOCUMENTED_DECK = f.element_condition_payload(
    "DECK",
    "SQM",
    1000,
    600,
    200,
    150,
    50,
    photo_count=0,
    defect_notes="Spalling and delamination in bay 3",
)
SOUND_ABUTMENT = f.element_condition_payload(
    "ABUTMENT", "EA", 4, 3, 1, 0, 0, photo_count=0, defect_notes="Minor map cracking"
)
PHOTOGRAPHED_DECK = f.element_update_payload(
    1000,
    600,
    200,
    150,
    50,
    photo_count=6,
    defect_notes="Spalling and delamination in bay 3, photographed",
)


def _a_report_missing_a_group_and_missing_a_photograph(client, roster, bridge):
    """
    A `DRAFT` routine report covering the deck and the superstructure only, where the
    deck row reports poor and severe quantity with no photographs at all — so two
    different submit gates are broken at once.
    """
    inspection = fx.open_inspection(
        client,
        bridge["id"],
        roster,
        field_window_start=FIRST_WINDOW_START,
        field_window_end=FIRST_WINDOW_END,
    )
    deck = fx.add_element(client, inspection["id"], roster, UNDOCUMENTED_DECK)
    fx.add_element(client, inspection["id"], roster, f.BASELINE_GIRDER)
    fx.set_clock(client, c.FIELD_DAY_CLOCK)
    return {"inspection": inspection, "deck": deck}


def test_the_absent_substructure_group_outranks_the_undocumented_deck(
    client, roster, bridge
):
    """
    Both the coverage gate and the documentation gate are broken, and coverage is the
    earlier rung, so the report is told about the missing group rather than about the
    unphotographed deck.

    PRD §3.3: "Element-group coverage depends on type: a `ROUTINE`, `SPECIAL`, `DAMAGE`
    or `FRACTURE_CRITICAL` report must include at least one row in each of
    `DECK_GROUP`, `SUPERSTRUCTURE` and `SUBSTRUCTURE`, while an `UNDERWATER` report
    needs only at least one `SUBSTRUCTURE` row; a missing group is
    `ERR_ELEMENT_GROUP_MISSING`."
    PRD §3.3: "Six gates guard submission, and they are evaluated in the global
    precedence order of §2.8."

    Design: Corner/errors/submit_missing_substructure_group_then_missing_photos_rejected
    """
    setup = _a_report_missing_a_group_and_missing_a_photograph(client, roster, bridge)

    response = client.submit_inspection(
        setup["inspection"]["id"],
        f.submit_payload(fx.INSPECTION_DATE),
        roster.inspector_headers,
    )

    validate_error(response, e.ERR_ELEMENT_GROUP_MISSING, 422)
    assert (
        response.json()["data"]["error_id"] != e.ERR_PHOTO_DOCUMENTATION_MISSING
    ), "coverage is checked before documentation"
    still_draft = fx.read_inspection(client, setup["inspection"]["id"])
    assert still_draft["status"] == "DRAFT"
    assert still_draft["inspection_date"] is None


def test_supplying_the_missing_group_reveals_the_photograph_gap(
    client, roster, bridge
):
    """
    An abutment row closes the coverage gap and the same call now reports the
    documentation gap. The abutment itself is exempt — it reports nothing poor or
    severe — so the cited row can only be the deck.

    PRD §3.3: "Every element row reporting any poor or severe quantity at all must
    carry a `photo_count` of at least 1 and a non-empty `defect_notes`, else
    `ERR_PHOTO_DOCUMENTATION_MISSING`."
    PRD §2.8: "19. **Photographic documentation** — `ERR_PHOTO_DOCUMENTATION_MISSING`
    (422). Applies to inspection submit."

    Design: Corner/errors/submit_missing_substructure_group_then_missing_photos_rejected
    """
    setup = _a_report_missing_a_group_and_missing_a_photograph(client, roster, bridge)
    validate_error(
        client.submit_inspection(
            setup["inspection"]["id"],
            f.submit_payload(fx.INSPECTION_DATE),
            roster.inspector_headers,
        ),
        e.ERR_ELEMENT_GROUP_MISSING,
        422,
    )
    abutment = fx.add_element(
        client, setup["inspection"]["id"], roster, SOUND_ABUTMENT
    )

    response = client.submit_inspection(
        setup["inspection"]["id"],
        f.submit_payload(fx.INSPECTION_DATE),
        roster.inspector_headers,
    )

    validate_error(response, e.ERR_PHOTO_DOCUMENTATION_MISSING, 422)
    assert abutment["cs3_qty"] + abutment["cs4_qty"] == 0
    assert abutment["photo_count"] == 0
    assert setup["deck"]["cs3_qty"] == 150
    assert setup["deck"]["cs4_qty"] == 50
    assert fx.read_inspection(client, setup["inspection"]["id"])["status"] == "DRAFT"


def test_photographing_the_deck_finally_submits_the_report(client, roster, bridge):
    """
    With the group supplied and the deck photographed, the third attempt at the
    identical call succeeds, and the report's photograph rollup is the sum over its
    three rows — six on the deck, eight on the girder, none on the sound abutment.

    PRD §3.2: "Each element write also refreshes the parent report's rollup counters:
    `element_count` (the number of element rows), `reported_quantity_total` (the sum of
    `total_quantity` across rows), `deficient_quantity_total` (the sum of
    poor-plus-severe quantities across rows), `photo_count_total` (the sum of
    `photo_count` across rows)".
    PRD §3.3: "The submitting inspector supplies `inspection_date`, the instant at
    which the condition data was actually observed, and the report records
    `submitted_at` from the logical clock."

    Design: Corner/errors/submit_missing_substructure_group_then_missing_photos_rejected
    """
    setup = _a_report_missing_a_group_and_missing_a_photograph(client, roster, bridge)
    fx.add_element(client, setup["inspection"]["id"], roster, SOUND_ABUTMENT)
    validate_success(
        client.update_element_condition(
            setup["deck"]["id"], PHOTOGRAPHED_DECK, roster.inspector_headers
        ),
        200,
    )

    submitted = validate_success(
        client.submit_inspection(
            setup["inspection"]["id"],
            f.submit_payload(fx.INSPECTION_DATE),
            roster.inspector_headers,
        ),
        200,
    )

    assert submitted["status"] == "SUBMITTED"
    assert submitted["element_count"] == 3
    assert submitted["photo_count_total"] == 14
    a.assert_instant_equals(
        submitted["submitted_at"], c.FIELD_DAY_CLOCK, "submitted_at"
    )
