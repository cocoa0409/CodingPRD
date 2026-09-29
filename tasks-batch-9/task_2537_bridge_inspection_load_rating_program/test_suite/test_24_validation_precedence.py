"""
Which rule speaks when several are broken at once, and where the closed intervals of
the observation-date gate actually close.
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
from test_helpers import make_bridge_inspector_headers, program_admin_headers

WINDOW_START = "2026-09-02T08:00:00Z"
WINDOW_END = "2026-09-02T16:00:00Z"
ONE_SECOND_PAST_END = "2026-09-02T16:00:01Z"
ONE_SECOND_BEFORE_START = "2026-09-02T07:59:59Z"
DAY_AFTER = "2026-09-03T00:00:00Z"

UNKNOWN_PERSON_ID = "11111111-1111-1111-1111-111111111111"

# The three groups a ROUTINE report must cover, one member each, so the
# renormalisation of the element weights is visible in the report index.
THREE_GROUPS = (f.BASELINE_DECK, f.BASELINE_GIRDER, f.BASELINE_ABUTMENT)


def _draft_covering_the_three_groups(client, roster, bridge):
    """A balanced, fully documented `DRAFT` report with one row per group."""
    inspection = fx.open_inspection(
        client,
        bridge["id"],
        roster,
        field_window_start=WINDOW_START,
        field_window_end=WINDOW_END,
    )
    for payload in THREE_GROUPS:
        fx.add_element(client, inspection["id"], roster, payload)
    return inspection


# ─── The observation-date gate, one second either side ──────────────────────
def test_an_observation_date_one_second_past_the_window_end_is_refused(
    client, roster, bridge
):
    """
    The report is otherwise perfect — three groups, balanced, documented, the date
    safely in the past — so the only rule left to break is the closed upper bound of
    the reserved window, and breaking it by one second is enough.

    PRD §3.3: "And `inspection_date` must fall inside the reserved field window, at or
    after `field_window_start` and at or before `field_window_end`, and must not be
    later than the logical clock; a violation is `ERR_INSPECTION_DATE_OUT_OF_WINDOW`."
    PRD §2.8: "26. **Observation date plausibility** — `ERR_INSPECTION_DATE_OUT_OF_WINDOW`
    (422). Applies to inspection submit."

    Design: Corner/validations/inspection_date_after_field_window_end_rejected
    """
    inspection = _draft_covering_the_three_groups(client, roster, bridge)
    fx.set_clock(client, DAY_AFTER)

    response = client.submit_inspection(
        inspection["id"],
        f.submit_payload(ONE_SECOND_PAST_END),
        roster.inspector_headers,
    )

    validate_error(response, e.ERR_INSPECTION_DATE_OUT_OF_WINDOW, 422)
    still_draft = fx.read_inspection(client, inspection["id"])
    assert still_draft["status"] == "DRAFT"
    assert still_draft["submitted_at"] is None
    assert still_draft["inspection_date"] is None


def test_the_refused_submission_computed_nothing_at_all(client, roster, bridge):
    """
    Because the gate is evaluated before the arithmetic, none of the submission side
    effects ran: the report's condition fields are still null and the structure has
    not moved.

    PRD §3.2: "The new report is stamped with `returned_count` 0, `element_count` 0, a
    `bridge_id` copied from the structure being inspected, a null `qa_reviewer_id`
    until a reviewer actually claims it, and every derived condition field null."
    PRD §3.3: "Once those gates pass, submission recomputes every element row's
    `element_health_index`, then rolls the element indices up in two stages."

    Design: Corner/validations/inspection_date_after_field_window_end_rejected
    """
    inspection = _draft_covering_the_three_groups(client, roster, bridge)
    fx.set_clock(client, DAY_AFTER)

    validate_error(
        client.submit_inspection(
            inspection["id"],
            f.submit_payload(ONE_SECOND_PAST_END),
            roster.inspector_headers,
        ),
        e.ERR_INSPECTION_DATE_OUT_OF_WINDOW,
        422,
    )

    report = fx.read_inspection(client, inspection["id"])
    for field in (
        "bridge_health_index",
        "deck_group_ehi",
        "superstructure_group_ehi",
        "substructure_group_ehi",
        "computed_deck_rating",
        "computed_superstructure_rating",
        "computed_substructure_rating",
    ):
        assert report[field] is None, f"{field} must still be null on a DRAFT report"

    structure = fx.read_bridge(client, bridge["id"])
    assert structure["version"] == 1
    assert structure["last_routine_inspection_date"] is None


def test_an_observation_date_one_second_before_the_window_start_is_refused_too(
    client, roster, bridge
):
    """
    The lower bound of the window closes the same way: a date one second early is the
    same violation with the same code, and the report is still a draft afterwards.

    PRD §3.3: "And `inspection_date` must fall inside the reserved field window, at or
    after `field_window_start` and at or before `field_window_end`, and must not be
    later than the logical clock; a violation is `ERR_INSPECTION_DATE_OUT_OF_WINDOW`."
    PRD §3.2: "a reserved field-work window bounded by `field_window_start` and
    `field_window_end`, where the end must be strictly later than the start."

    Design: Corner/validations/inspection_date_after_field_window_end_rejected
    """
    inspection = _draft_covering_the_three_groups(client, roster, bridge)
    fx.set_clock(client, DAY_AFTER)

    response = client.submit_inspection(
        inspection["id"],
        f.submit_payload(ONE_SECOND_BEFORE_START),
        roster.inspector_headers,
    )

    validate_error(response, e.ERR_INSPECTION_DATE_OUT_OF_WINDOW, 422)
    assert fx.read_inspection(client, inspection["id"])["status"] == "DRAFT"


def test_an_observation_date_on_the_window_end_and_on_the_clock_submits(
    client, roster, bridge
):
    """
    Both halves of the gate are non-strict, and a date sitting exactly on the window
    end while the clock sits exactly on the same instant satisfies both at once.

    PRD §3.3: "And `inspection_date` must fall inside the reserved field window, at or
    after `field_window_start` and at or before `field_window_end`, and must not be
    later than the logical clock; a violation is `ERR_INSPECTION_DATE_OUT_OF_WINDOW`."
    PRD §3.3: "The submitting inspector supplies `inspection_date`, the instant at
    which the condition data was actually observed, and the report records
    `submitted_at` from the logical clock."

    Design: Corner/validations/inspection_date_exactly_at_window_end_and_clock_passes
    """
    inspection = _draft_covering_the_three_groups(client, roster, bridge)
    fx.set_clock(client, WINDOW_END)

    submitted = validate_success(
        client.submit_inspection(
            inspection["id"], f.submit_payload(WINDOW_END), roster.inspector_headers
        ),
        200,
    )

    assert submitted["status"] == "SUBMITTED"
    a.assert_instant_equals(submitted["inspection_date"], WINDOW_END, "inspection_date")
    a.assert_instant_equals(submitted["submitted_at"], WINDOW_END, "submitted_at")


def test_the_three_group_report_renormalises_over_the_rows_it_has(
    client, roster, bridge
):
    """
    With a bearing row absent, the superstructure group is the girder alone and the
    report index divides by the weights actually present rather than by one, which is
    what stops the missing bearing scoring as zero.

    PRD §3.3: "Second, the report's own `bridge_health_index` is the weighted average
    over *all* element rows on the report, computed exactly the same way as a group
    index but with the weights renormalised across every reported element rather than
    within a group, and rounded half up to two decimals. Renormalisation is what stops
    an inspection that omitted railing from silently scoring railing as zero."
    PRD §3.3: "The element weights are: deck 0.30, girder 0.25, bearing 0.10, pier cap
    0.10, column 0.10, abutment 0.10, joint 0.05 and railing 0.05."

    Design: Corner/validations/inspection_date_exactly_at_window_end_and_clock_passes
    """
    inspection = _draft_covering_the_three_groups(client, roster, bridge)
    fx.set_clock(client, WINDOW_END)

    submitted = validate_success(
        client.submit_inspection(
            inspection["id"], f.submit_payload(WINDOW_END), roster.inspector_headers
        ),
        200,
    )

    assert submitted["deck_group_ehi"] == 82.00
    assert submitted["superstructure_group_ehi"] == 40.00
    assert submitted["substructure_group_ehi"] == 95.00
    assert submitted["computed_deck_rating"] == 7
    assert submitted["computed_superstructure_rating"] == 3
    assert submitted["computed_substructure_rating"] == 8
    assert submitted["bridge_health_index"] == 67.85
    assert submitted["reported_quantity_total"] == 1304
    assert submitted["deficient_quantity_total"] == 400
    assert submitted["quantity_balanced"] is True
    assert fx.read_bridge(client, bridge["id"])["version"] == 1


# ─── Authentication before authorisation before the body ────────────────────
def _bridge_payload_missing_its_traffic_count():
    """A structure payload that is malformed: the required `adt` is absent."""
    payload = f.bridge_payload("STR-000001")
    del payload["adt"]
    return payload


def test_absent_credentials_are_reported_before_the_role_and_the_body(client):
    """
    One request breaks the first three rules at once — no acting-user header, a role
    that may not create structures, and a required field missing — and the answer is
    the authentication failure alone.

    PRD §2.1: "If either header is absent, empty, or if `X-User-Role` names a role the
    system does not recognise, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401) before any other processing occurs."
    PRD §2.8: "1. **Header authentication** — `X-User-ID` and `X-User-Role` both
    present and the role one of the seven declared names, else `ERR_UNAUTHENTICATED`
    (401). Applies to every endpoint."

    Design: Corner/validations/missing_x_user_id_header_outranks_role_and_payload_checks
    """
    fx.set_clock(client, c.BASE_CLOCK)
    anonymous = {
        "X-User-Role": c.ROLE_BRIDGE_INSPECTOR,
        "Content-Type": "application/json",
    }

    response = client.create_bridge(
        _bridge_payload_missing_its_traffic_count(), anonymous
    )

    validate_error(response, e.ERR_UNAUTHENTICATED, 401)
    assert response.json()["data"]["error_id"] != e.ERR_ROLE_NOT_PERMITTED
    assert response.json()["data"]["error_id"] != e.ERR_INVALID_REQUEST
    assert validate_paginated(client.list_bridges(program_admin_headers()))[1][
        "total_count"
    ] == 0


def test_an_unrecognised_role_name_fails_authentication_rather_than_authorisation(
    client,
):
    """
    A present but undeclared role is an authentication failure, not a 403: the system
    recognises exactly seven names and anything else never reaches the endpoint's
    authorised list.

    PRD §2.1: "The system recognises exactly seven roles: `ProgramAdmin`,
    `BridgeInspector`, `QaReviewer`, `RatingEngineer`, `DistrictEngineer`,
    `PermitOfficer`, and `FhwaReviewer`."
    PRD §2.1: "When the headers are well formed but the declared role is not among the
    roles authorised for the requested operation, the response is
    `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/validations/missing_x_user_id_header_outranks_role_and_payload_checks
    """
    fx.set_clock(client, c.BASE_CLOCK)

    response = client.create_bridge(
        _bridge_payload_missing_its_traffic_count(),
        {
            "X-User-ID": "someone",
            "X-User-Role": "NotARole",
            "Content-Type": "application/json",
        },
    )

    validate_error(response, e.ERR_UNAUTHENTICATED, 401)
    assert validate_paginated(client.list_bridges(program_admin_headers()))[1][
        "total_count"
    ] == 0


def test_the_role_gate_speaks_before_the_malformed_body(client, roster):
    """
    Authentication now succeeds, so the next rule in line decides: an authenticated
    inspector posting a malformed structure payload is told about the role, never
    about the payload.

    PRD §2.8: "2. **Role authorisation** — the authenticated role appears in the
    endpoint's authorised list, else `ERR_ROLE_NOT_PERMITTED` (403). Applies to every
    endpoint."
    PRD §2.1: "Read access is broad: every retrieval and listing operation in the API
    is available to all seven roles. Write access is narrow and is enumerated per
    endpoint in §4."

    Design: Corner/validations/role_check_outranks_payload_validation_returns_403
    """
    response = client.create_bridge(
        _bridge_payload_missing_its_traffic_count(),
        make_bridge_inspector_headers(roster.inspector_id),
    )

    validate_error(response, e.ERR_ROLE_NOT_PERMITTED, 403)
    assert response.json()["data"]["error_id"] != e.ERR_INVALID_REQUEST
    assert validate_paginated(client.list_bridges(program_admin_headers()))[1][
        "total_count"
    ] == 0


def test_the_administrator_sees_the_defect_the_role_gate_was_hiding(client, roster):
    """
    The identical body sent by the role that may create structures reports the
    malformed request, which proves the earlier 403 was suppressing a real payload
    defect rather than standing in for one.

    PRD §2.8: "3. **Request well-formedness** — required fields present, enum values
    inside their declared sets, and numeric fields inside their declared ranges".
    PRD §2.1: "A `ProgramAdmin` is the state bridge unit's program administrator: they
    maintain the structure inventory and the personnel roster".

    Design: Corner/validations/role_check_outranks_payload_validation_returns_403
    """
    malformed = _bridge_payload_missing_its_traffic_count()
    validate_error(
        client.create_bridge(
            malformed, make_bridge_inspector_headers(roster.inspector_id)
        ),
        e.ERR_ROLE_NOT_PERMITTED,
        403,
    )

    response = client.create_bridge(malformed, program_admin_headers())

    validate_error(response, e.ERR_INVALID_REQUEST, 400)
    assert validate_paginated(client.list_bridges(program_admin_headers()))[1][
        "total_count"
    ] == 0


# ─── The path is resolved before the body ───────────────────────────────────
def test_the_unknown_structure_in_the_path_outranks_the_unknown_person_in_the_body(
    client, roster, bridge
):
    """
    Both ids are unresolvable and both would be 404s, but the path is checked first,
    so the structure is the one reported and no report is opened.

    PRD §2.8: "4. **Path existence** — every resource named in the path exists,
    validated left to right, else the matching family-scoped 404 code. Applies to
    every endpoint with a path parameter."
    PRD §2.8: "5. **Body referential integrity** — every foreign key in the body
    resolves, else the matching family-scoped 404 code. Applies to inspection
    creation".

    Design: Corner/validations/unknown_path_bridge_outranks_unknown_body_team_leader_not_found
    """
    response = client.create_inspection(
        NON_EXISTENT_UUID,
        f.inspection_payload(UNKNOWN_PERSON_ID, WINDOW_START, WINDOW_END),
        roster.inspector_headers,
    )

    validate_error(response, e.ERR_BRIDGE_NOT_FOUND, 404)
    assert response.json()["data"]["error_id"] != e.ERR_PERSONNEL_NOT_FOUND
    rows, meta = validate_paginated(client.list_inspections(program_admin_headers()))
    assert rows == []
    assert meta["total_count"] == 0


def test_a_real_structure_in_the_path_exposes_the_unresolvable_team_leader(
    client, roster, bridge
):
    """
    With the path resolving, the same unresolvable person in the body is finally
    reported — and named as a personnel failure, which isolates the ordering effect of
    the previous case.

    PRD §2.8: "Every one of `team_leader_id`, `qa_reviewer_id`, `evaluated_by_id`,
    `authorized_by_id`, `approved_by_id`, `bridge_id`, `source_inspection_id`,
    `element_condition_id`, and each entry of `route_bridge_ids` must reference an
    existing row; a dangling person yields `ERR_PERSONNEL_NOT_FOUND`".
    PRD §3.2: "a `team_leader_id` naming the certified team leader who will own the
    report".

    Design: Corner/validations/unknown_path_bridge_outranks_unknown_body_team_leader_not_found
    """
    response = client.create_inspection(
        bridge["id"],
        f.inspection_payload(UNKNOWN_PERSON_ID, WINDOW_START, WINDOW_END),
        roster.inspector_headers,
    )

    validate_error(response, e.ERR_PERSONNEL_NOT_FOUND, 404)
    assert validate_paginated(client.list_inspections(program_admin_headers()))[1][
        "total_count"
    ] == 0

    opened = get_success_data(
        client.create_inspection(
            bridge["id"],
            f.inspection_payload(roster.inspector_id, WINDOW_START, WINDOW_END),
            roster.inspector_headers,
        ),
        201,
    )
    assert opened["team_leader_id"] == roster.inspector_id
    assert opened["status"] == "DRAFT"
