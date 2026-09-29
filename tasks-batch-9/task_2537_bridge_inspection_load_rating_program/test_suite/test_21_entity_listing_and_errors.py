"""
Reading collections, and the four ways a request for a resource can be refused
before any state is written: bad page, unknown id, missing field, bad value.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as e
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import permit_officer_headers, program_admin_headers

# The three structures are created an hour apart so that the mandated ascending
# creation order is a total order and paging over them is deterministic.
FIRST_CLOCK = "2026-09-01T00:00:00Z"
SECOND_CLOCK = "2026-09-01T01:00:00Z"
THIRD_CLOCK = "2026-09-01T02:00:00Z"


def _three_structures(client):
    """Three structures in the inventory, in a known creation order."""
    fx.set_clock(client, FIRST_CLOCK)
    cedar = fx.create_bridge(client, f.bridge_payload("STR-000001"))
    fx.set_clock(client, SECOND_CLOCK)
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
    fx.set_clock(client, THIRD_CLOCK)
    granite = fx.create_bridge(
        client,
        f.bridge_payload(
            "STR-000003",
            name="Granite Ridge Overpass",
            owner_agency="Marion County",
            structure_type="ARCH",
            deck_area_sqm=800,
            year_built=1995,
            adt=7000,
            detour_length_km=5.0,
        ),
    )
    return [cedar, willow, granite]


# ─── Paging the inventory ───────────────────────────────────────────────────
def test_the_first_page_of_two_reports_the_full_match_count(client):
    """
    A page of two over three structures returns two rows while `total_count`
    reports the unpaginated match count and `has_more` announces the rest.

    PRD §2.3: "List responses populate four fields in the envelope's `meta` object:
    `limit` (the effective page size applied), `offset` (the effective skip
    applied), `total_count` (the number of records matching the filters before
    pagination), and `has_more` (true when records remain beyond the current page)."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/entities/bridges_list_pagination_and_filter_report_total_count
    """
    _three_structures(client)

    response = client.list_bridges(program_admin_headers(), {"limit": 2, "offset": 0})

    assert response.status_code == 200
    assert response.json()["response_type"] == "array"
    rows, meta = validate_paginated(response)
    assert len(rows) == 2
    assert meta["total_count"] == 3
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assert meta["has_more"] is True


def test_the_second_page_completes_the_inventory_without_repeating_a_row(client):
    """
    Skipping two rows returns the single remaining structure, `has_more` goes false,
    and the two pages together are exactly the inventory with nothing duplicated
    and nothing dropped — in creation order, oldest first.

    PRD §2.3: "`offset` sets how many records to skip before the first returned
    record; when omitted it defaults to 0, and the smallest accepted value is 0."
    PRD §2.3: "Unless a specific endpoint states otherwise, every list endpoint
    returns records sorted by their creation timestamp in ascending order — oldest
    first."

    Design: Corner/entities/bridges_list_pagination_and_filter_report_total_count
    """
    created = _three_structures(client)

    first_rows, _ = validate_paginated(
        client.list_bridges(program_admin_headers(), {"limit": 2, "offset": 0})
    )
    second_rows, second_meta = validate_paginated(
        client.list_bridges(program_admin_headers(), {"limit": 2, "offset": 2})
    )

    assert len(second_rows) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["offset"] == 2
    assert second_meta["has_more"] is False

    paged = [row["id"] for row in first_rows] + [row["id"] for row in second_rows]
    assert len(set(paged)) == 3, "no row may appear on both pages"
    assert set(paged) == {structure["id"] for structure in created}
    assert paged == [structure["id"] for structure in created]


def test_an_unparameterised_listing_applies_the_declared_page_defaults(client):
    """
    With no query parameters at all the effective page is the declared default of
    ten from zero, which is wide enough to hold the whole inventory.

    PRD §2.3: "`limit` sets the maximum number of records returned; when omitted it
    defaults to 10, and the accepted range is a minimum of 1 and a maximum of 100."
    PRD §2.3: "`offset` sets how many records to skip before the first returned
    record; when omitted it defaults to 0".

    Design: Corner/entities/bridges_list_pagination_and_filter_report_total_count
    """
    created = _three_structures(client)

    rows, meta = validate_paginated(client.list_bridges(program_admin_headers()))

    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["total_count"] == 3
    assert meta["has_more"] is False
    assert [row["id"] for row in rows] == [structure["id"] for structure in created]


# ─── An unknown structure id ────────────────────────────────────────────────
def test_reading_an_unknown_structure_returns_the_error_envelope_and_nothing_else(
    client,
):
    """
    One real structure exists, so the failure is id resolution rather than an empty
    inventory: the body is the error envelope, carrying only the machine-readable
    code and a human-readable message.

    PRD §2.2: "The `meta` object for error responses contains only `api_request_id`
    and `api_request_timestamp`."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies
    the specific error."
    PRD §2.2: "The `message` provides a human-readable explanation of what went
    wrong."
    PRD §2.8: "4. **Path existence** — every resource named in the path exists,
    validated left to right, else the matching family-scoped 404 code. Applies to
    every endpoint with a path parameter."

    Design: Corner/entities/bridge_get_unknown_id_not_found_returns_error_envelope
    """
    fx.set_clock(client, FIRST_CLOCK)
    fx.create_bridge(client, f.bridge_payload("STR-000001"))

    response = client.get_bridge(NON_EXISTENT_UUID, program_admin_headers())

    validate_error(response, e.ERR_BRIDGE_NOT_FOUND, 404)
    body = response.json()
    assert body["response_type"] == "error"
    assert set(body["data"].keys()) == {"error_id", "message"}
    assert isinstance(body["data"]["message"], str)
    assert body["data"]["message"].strip() != ""
    assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}


def test_the_failed_read_leaves_the_inventory_exactly_as_it_was(client):
    """
    A read that resolved nothing also created nothing: the inventory still holds the
    one structure that was there before.

    PRD §2.3: "`total_count` (the number of records matching the filters before
    pagination)".
    PRD §2.7: "The system practises **immediate consistency**. Derived fields are
    never left stale for a later sweep to fix; every reconciliation a change implies
    is completed inside the request that caused it, and the response body reflects
    the settled state."

    Design: Corner/entities/bridge_get_unknown_id_not_found_returns_error_envelope
    """
    fx.set_clock(client, FIRST_CLOCK)
    real = fx.create_bridge(client, f.bridge_payload("STR-000001"))

    client.get_bridge(NON_EXISTENT_UUID, program_admin_headers())

    rows, meta = validate_paginated(client.list_bridges(program_admin_headers()))
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [real["id"]]


# ─── A required inventory field left out ────────────────────────────────────
def _payload_without_traffic():
    """The inventory payload of a modern low-traffic structure, minus `adt`."""
    payload = f.bridge_payload("STR-000001", year_built=1995, adt=4000)
    del payload["adt"]
    return payload


def test_omitting_the_traffic_count_is_a_malformed_request(client):
    """
    `adt` is a required physical fact with no declared default, so leaving it out is
    refused outright rather than being read as zero.

    PRD §2.8: "3. **Request well-formedness** — required fields present, enum values
    inside their declared sets, and numeric fields inside their declared ranges".
    PRD §3.1: "`adt` for average daily traffic (at least zero)".

    Design: Corner/entities/bridge_create_missing_required_adt_returns_invalid_request
    """
    fx.set_clock(client, FIRST_CLOCK)

    response = client.create_bridge(_payload_without_traffic(), program_admin_headers())

    validate_error(response, e.ERR_INVALID_REQUEST, 400)
    rows, meta = validate_paginated(client.list_bridges(program_admin_headers()))
    assert rows == []
    assert meta["total_count"] == 0


def test_the_omitted_traffic_count_was_load_bearing_for_the_interval(client):
    """
    The identical payload with a traffic count of 4000 is accepted and earns the
    four-year cycle, which is exactly the decision a defaulted-to-zero traffic count
    would have silently reached.

    PRD §2.11: "Otherwise, if the structure satisfies all three extension tests at
    once — `min_nbi_rating` of at least 7, `year_built` of 1990 or later, and `adt` of
    at most 5000 — the base extends to 48 months, four years between routine
    inspections."
    PRD §2.11: "`next_inspection_due_date` is `last_routine_inspection_date`
    advanced by `inspection_interval_months`; before the first routine acceptance the
    base date is the structure's creation date."

    Design: Corner/entities/bridge_create_missing_required_adt_returns_invalid_request
    """
    fx.set_clock(client, FIRST_CLOCK)
    rejected = _payload_without_traffic()

    validate_error(
        client.create_bridge(rejected, program_admin_headers()),
        e.ERR_INVALID_REQUEST,
        400,
    )
    accepted = dict(rejected, adt=4000)
    structure = get_success_data(
        client.create_bridge(accepted, program_admin_headers()), 201
    )

    assert structure["adt"] == 4000
    assert structure["min_nbi_rating"] == 7
    assert structure["inspection_interval_months"] == 48
    assert structure["next_inspection_due_date"][:10] == "2030-09-01"
    assert validate_paginated(client.list_bridges(program_admin_headers()))[1][
        "total_count"
    ] == 1


# ─── Bad values on a permit application ─────────────────────────────────────
def _one_structure_to_route_over(client):
    """A single water-crossing structure for a heavy-haul route."""
    fx.set_clock(client, FIRST_CLOCK)
    return fx.create_bridge(client, f.bridge_payload("STR-000001", spans_water=True))


def test_an_undeclared_speed_category_and_a_single_axle_are_both_refused(client):
    """
    Neither bad value is coerced: a speed category outside the declared pair and an
    axle array of one entry are each rejected as malformed, and no application is
    filed by either attempt.

    PRD §3.7: "an `axle_loads_tons` array of per-axle loads in tons, which must
    contain at least two entries each strictly positive ... and an optional
    `speed_category` of `NORMAL` or `CRAWL`, defaulting to `NORMAL`."
    PRD §2.8: "3. **Request well-formedness** — required fields present, enum values
    inside their declared sets, and numeric fields inside their declared ranges: ...
    every axle load strictly greater than zero with at least two axles present".

    Design: Corner/entities/permit_application_invalid_enum_speed_category_rejected
    """
    structure = _one_structure_to_route_over(client)

    bad_enum = client.create_permit_application(
        f.permit_application_payload(
            "OW-2026-0009",
            [structure["id"]],
            axle_loads_tons=[10.0, 10.0, 10.0, 6.0],
            speed_category="SLOW",
        ),
        permit_officer_headers(),
    )
    one_axle = client.create_permit_application(
        f.permit_application_payload(
            "OW-2026-0010",
            [structure["id"]],
            axle_loads_tons=[36.0],
            speed_category="NORMAL",
        ),
        permit_officer_headers(),
    )

    validate_error(bad_enum, e.ERR_INVALID_REQUEST, 400)
    validate_error(one_axle, e.ERR_INVALID_REQUEST, 400)
    rows, meta = validate_paginated(
        client.list_permit_applications(permit_officer_headers())
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_the_same_route_with_declared_values_is_filed_and_weighed(client):
    """
    With a declared speed category and four axles the application is received, its
    axle count and gross weight are derived from the array, and it is not yet
    analysed or recommended.

    PRD §3.7: "Two fields are derived from the axle array at filing: `axle_count`,
    the number of entries, and `gross_weight_tons`."
    PRD §3.7: "A newly received application is `RECEIVED`, carries a
    `recommended_decision` of `PENDING` and a null `governing_analysis_min_rf`, and
    has no analysis rows at all."

    Design: Corner/entities/permit_application_invalid_enum_speed_category_rejected
    """
    structure = _one_structure_to_route_over(client)

    permit = fx.receive_permit(
        client,
        "OW-2026-0010",
        [structure["id"]],
        axle_loads_tons=[10.0, 10.0, 10.0, 6.0],
        speed_category="NORMAL",
    )

    assert permit["status"] == "RECEIVED"
    assert permit["speed_category"] == "NORMAL"
    assert permit["axle_count"] == 4
    assert permit["gross_weight_tons"] == 36.0
    assert permit["recommended_decision"] == "PENDING"
    assert permit["governing_analysis_min_rf"] is None
    assert fx.analyses_for_permit(client, permit["id"]) == []


# ─── A child row filed under an unknown parent ──────────────────────────────
def test_an_element_row_cannot_be_filed_under_an_unknown_report(
    client, roster, bridge
):
    """
    The row's parent comes from the path, so an unresolvable report id is refused as
    a path-existence failure in the inspection family rather than producing an
    orphaned row.

    PRD §3.2: "Each row carries an `inspection_id` identifying the report it belongs
    to, taken from the report the row is filed against rather than from the payload".
    PRD §2.8: "4. **Path existence** — every resource named in the path exists,
    validated left to right, else the matching family-scoped 404 code."

    Design: Corner/entities/element_condition_create_under_unknown_inspection_not_found
    """
    real = fx.open_inspection(client, bridge["id"], roster)

    response = client.create_element_condition(
        NON_EXISTENT_UUID, f.BASELINE_DECK, roster.inspector_headers
    )

    validate_error(response, e.ERR_INSPECTION_RECORD_NOT_FOUND, 404)
    rows, meta = validate_paginated(
        client.list_element_conditions(program_admin_headers())
    )
    assert rows == []
    assert meta["total_count"] == 0
    assert fx.read_inspection(client, real["id"])["element_count"] == 0


# ─── One unknown member of a route array ────────────────────────────────────
def _two_structures_on_the_route(client):
    """Two real structures, either end of a heavy-haul movement."""
    fx.set_clock(client, FIRST_CLOCK)
    cedar = fx.create_bridge(client, f.bridge_payload("STR-000001", spans_water=True))
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
    return cedar, willow


def test_one_unknown_structure_in_the_route_array_refuses_the_whole_application(
    client,
):
    """
    The route array is validated member by member: two good entries do not save a
    dangling third, and neither the application nor any per-structure analysis row is
    materialised.

    PRD §2.8: "Foreign keys supplied in a request *body* are validated the same way
    and with the same codes. Every one of ... and each entry of `route_bridge_ids`
    must reference an existing row; ... a dangling structure (including inside the
    route array) yields `ERR_BRIDGE_NOT_FOUND`".
    PRD §2.3: "These filters are the *only* discovery channel for several records
    that the system creates as side effects rather than in response to a direct
    create call — a per-bridge permit analysis row ... reachable only by listing
    their collection with the appropriate parent filter."

    Design: Corner/entities/permit_route_bridge_ids_unknown_member_not_found
    """
    cedar, willow = _two_structures_on_the_route(client)

    response = client.create_permit_application(
        f.permit_application_payload(
            "OW-2026-0011",
            [cedar["id"], NON_EXISTENT_UUID, willow["id"]],
            axle_loads_tons=[10.0, 10.0, 10.0, 6.0],
            speed_category="NORMAL",
        ),
        permit_officer_headers(),
    )

    validate_error(response, e.ERR_BRIDGE_NOT_FOUND, 404)
    applications, app_meta = validate_paginated(
        client.list_permit_applications(permit_officer_headers())
    )
    assert applications == []
    assert app_meta["total_count"] == 0
    analyses, analysis_meta = validate_paginated(
        client.list_permit_bridge_analyses(permit_officer_headers())
    )
    assert analyses == []
    assert analysis_meta["total_count"] == 0


def test_dropping_the_dangling_entry_files_the_two_structure_route(client):
    """
    Only the unresolvable member was ever wrong: the same movement over the two real
    structures is filed with its route preserved in order and its gross weight
    derived from the same axles.

    PRD §3.7: "a `route_bridge_ids` array holding the ordered structures of the
    route, which must contain at least one entry and each of which must name an
    existing structure".
    PRD §3.7: "`gross_weight_tons` is computed by rounding *each* axle load half up
    to one decimal place first, and only then summing those rounded values and
    rounding the total half up to one decimal place."

    Design: Corner/entities/permit_route_bridge_ids_unknown_member_not_found
    """
    cedar, willow = _two_structures_on_the_route(client)
    validate_error(
        client.create_permit_application(
            f.permit_application_payload(
                "OW-2026-0011",
                [cedar["id"], NON_EXISTENT_UUID, willow["id"]],
                axle_loads_tons=[10.0, 10.0, 10.0, 6.0],
                speed_category="NORMAL",
            ),
            permit_officer_headers(),
        ),
        e.ERR_BRIDGE_NOT_FOUND,
        404,
    )

    permit = validate_success(
        client.create_permit_application(
            f.permit_application_payload(
                "OW-2026-0011",
                [cedar["id"], willow["id"]],
                axle_loads_tons=[10.0, 10.0, 10.0, 6.0],
                speed_category="NORMAL",
            ),
            permit_officer_headers(),
        ),
        201,
    )

    assert permit["route_bridge_ids"] == [cedar["id"], willow["id"]]
    assert len(permit["route_bridge_ids"]) == 2
    assert permit["gross_weight_tons"] == 36.0
    assert permit["axle_count"] == 4
