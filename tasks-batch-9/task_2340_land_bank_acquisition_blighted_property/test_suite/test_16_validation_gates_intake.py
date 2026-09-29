"""
The intake-side rejections: the registry key, the adjacency graph, the title
dimension and the owner-of-record feed.

Each test drives one rejection, pins the error identifier the PRD names for it,
and then proves the target row was left exactly as it stood - no second row, no
status move, no version bump.
"""

from test_helpers import (
    ApiErrorId,
    DISP_1,
    INTAKE_1,
    fixtures,
    get_success_data,
    validate_error,
)


# ── the assessor parcel number is the registry's unique key ─────────────────
def test_second_registration_of_the_same_parcel_id_is_refused(api):
    """
    Registering a second parcel under an assessor parcel number already on file is refused, and the first parcel is neither duplicated nor overwritten.

    Registration records the county assessor's parcel number as `parcel_id`, which must be unique across the registry and must read as the letters `APN`, a hyphen, and then four to eight digits; a second registration of the same number is refused with `ERR_PARCEL_ID_DUPLICATE`.

    Design: Corner/validations/duplicate_parcel_id_rejected
    """
    first = fixtures.create_property(
        api,
        parcel_id="APN-203020",
        address="3020 Birch Ct",
        situs_ward=3,
        lot_area_sqft=6000,
        assessed_value_cents=300000,
        structure_present=True,
        structure_condition_grade="C",
        vacancy_months=4,
    )

    # Every other field of the second payload is a valid registration, so the
    # only rule it breaks is the uniqueness of the assessor parcel number.
    response = api.create_property(
        {
            "parcel_id": "APN-203020",
            "address": "9999 Elsewhere Rd",
            "situs_ward": 7,
            "lot_area_sqft": 22000,
            "assessed_value_cents": 10,
            "structure_present": False,
            "structure_condition_grade": "A",
            "vacancy_months": 0,
        },
        INTAKE_1,
    )
    validate_error(response, ApiErrorId.PARCEL_ID_DUPLICATE.value)

    kept = fixtures.read_property(api, first["id"])
    assert kept["address"] == "3020 Birch Ct"
    assert kept["lot_area_sqft"] == 6000
    assert kept["situs_ward"] == 3
    assert kept["version"] == first["version"]

    registry = get_success_data(api.list_properties(INTAKE_1, {"limit": 100}))
    assert [row["id"] for row in registry if row["parcel_id"] == "APN-203020"] == [
        first["id"]
    ]


# ── the two degenerate shapes of an adjacency edge ──────────────────────────
def _two_parcels_with_one_edge(api):
    """Two neighbouring registry parcels with a single recorded shared boundary."""
    parcel_a = fixtures.create_property(
        api,
        parcel_id="APN-203030",
        address="3030 Cedar Ln",
        situs_ward=3,
        lot_area_sqft=5000,
        assessed_value_cents=200000,
        structure_present=False,
        structure_condition_grade="C",
        vacancy_months=1,
    )
    parcel_b = fixtures.create_property(
        api,
        parcel_id="APN-203031",
        address="3031 Cedar Ln",
        situs_ward=3,
        lot_area_sqft=5000,
        assessed_value_cents=200000,
        structure_present=False,
        structure_condition_grade="C",
        vacancy_months=1,
    )
    edge = fixtures.create_adjacency(
        api, parcel_a["id"], parcel_b["id"], shared_boundary_feet=35
    )
    return parcel_a, parcel_b, edge


def test_edge_from_a_parcel_to_itself_is_refused(api):
    """
    An adjacency edge whose two endpoints are the same parcel is refused as a self-loop.

    An edge from a parcel to itself is refused with `ERR_SELF_ADJACENCY`, and a second edge over the same unordered pair of parcels — in either order — is refused with `ERR_ADJACENCY_DUPLICATE`.

    Design: Corner/validations/self_and_duplicate_adjacency_edges_rejected
    """
    parcel_a, _parcel_b, edge = _two_parcels_with_one_edge(api)

    response = api.create_parcel_adjacency(
        {
            "property_id": parcel_a["id"],
            "adjacent_property_id": parcel_a["id"],
            "shared_boundary_feet": 35,
        },
        INTAKE_1,
    )
    validate_error(response, ApiErrorId.SELF_ADJACENCY.value)

    edges = get_success_data(api.list_adjacencies(parcel_a["id"], INTAKE_1))
    assert [row["id"] for row in edges] == [edge["id"]]


def test_repeat_of_an_existing_edge_with_the_endpoints_swapped_is_refused(api):
    """
    Recording the same shared boundary a second time with the two parcels named in the opposite order is refused as a duplicate of the unordered pair.

    An edge from a parcel to itself is refused with `ERR_SELF_ADJACENCY`, and a second edge over the same unordered pair of parcels — in either order — is refused with `ERR_ADJACENCY_DUPLICATE`.

    Design: Corner/validations/self_and_duplicate_adjacency_edges_rejected
    """
    parcel_a, parcel_b, edge = _two_parcels_with_one_edge(api)

    response = api.create_parcel_adjacency(
        {
            "property_id": parcel_b["id"],
            "adjacent_property_id": parcel_a["id"],
            "shared_boundary_feet": 12,
        },
        INTAKE_1,
    )
    validate_error(response, ApiErrorId.ADJACENCY_DUPLICATE.value)

    # The stored edge keeps the boundary length it was filed with; the rejected
    # replay neither added a row nor amended the one on file.
    edges = get_success_data(api.list_adjacencies(parcel_a["id"], INTAKE_1))
    assert [row["id"] for row in edges] == [edge["id"]]
    assert edges[0]["shared_boundary_feet"] == 35


# ── only one title action may be open on a parcel ───────────────────────────
def test_second_title_action_while_the_first_is_unadjudicated_is_refused(api):
    """
    Filing a second title action on a parcel whose first action is still awaiting adjudication is refused.

    Only one action may be open on a parcel at a time: while any action on the parcel is still in `FILED`, another filing is refused with `ERR_TITLE_ACTION_OPEN`.

    Design: Corner/validations/second_open_title_action_rejected
    """
    prop = fixtures.create_property(
        api,
        parcel_id="APN-203040",
        address="3040 Dogwood Ln",
        situs_ward=3,
        lot_area_sqft=6000,
        assessed_value_cents=300000,
        structure_present=True,
        structure_condition_grade="C",
        vacancy_months=4,
    )
    first_action = fixtures.open_title_action(api, prop["id"], "QUIET_TITLE_SUIT")
    before = fixtures.read_property(api, prop["id"])
    assert before["title_status"] == "QUIET_TITLE_FILED"

    response = api.create_title_action(
        prop["id"], {"action_type": "TAX_DEED_CONFIRMATION"}, INTAKE_1
    )
    validate_error(response, ApiErrorId.TITLE_ACTION_OPEN.value)

    actions = get_success_data(api.list_title_actions(prop["id"], INTAKE_1))
    assert [row["id"] for row in actions] == [first_action["id"]]
    assert actions[0]["round_no"] == 1
    assert actions[0]["status"] == "FILED"

    after = fixtures.read_property(api, prop["id"])
    assert after["title_status"] == "QUIET_TITLE_FILED"
    assert after["version"] == before["version"]


# ── the title dimension gates listing independently of custody ──────────────
def test_listing_a_parcel_whose_title_is_still_clouded_is_refused(api):
    """
    A parcel in the authority's hands may not be listed for disposition while its title is still clouded.

    Both routes demand `title_status` of `CLEAR`, refusing anything else with `ERR_TITLE_NOT_CLEAR`; for a reverted parcel this means a fresh title action must have been filed and adjudicated `CLEARED` after the reverter deed re-clouded the title.

    Design: Corner/validations/listing_with_clouded_title_rejected
    """
    funding_source = fixtures.create_acquisition_funding_source(
        api, name="Clouded Title Line"
    )
    bundle = fixtures.acquired_parcel(
        api,
        funding_source=funding_source,
        property_overrides={
            "parcel_id": "APN-203050",
            "address": "3050 Elm Ln",
            "situs_ward": 3,
            "lot_area_sqft": 6000,
            "assessed_value_cents": 300000,
            "structure_present": False,
            "structure_condition_grade": "C",
            "vacancy_months": 4,
        },
        packet_overrides={"donor_name": "Elm Lane Estate"},
    )
    before = bundle["property"]
    # Custody is inventory and no demolition is pending, so the title dimension
    # is the only thing standing in the way of a listing.
    assert before["custody_status"] == "ACQUIRED"
    assert before["title_status"] == "CLOUDED"

    response = api.list_property_for_disposition(before["id"], DISP_1)
    validate_error(response, ApiErrorId.TITLE_NOT_CLEAR.value)

    after = fixtures.read_property(api, before["id"])
    assert after["custody_status"] == "ACQUIRED"
    assert after["title_status"] == "CLOUDED"
    assert after["listed_at"] is None
    assert after["version"] == before["version"]


# ── owner of record is a registry-only fact ─────────────────────────────────
def test_owner_of_record_on_an_acquired_parcel_is_refused(api):
    """
    Recording a private owner of record is refused once the parcel has passed into the land bank's own inventory.

    An `IntakeOfficer` also records the private owner of record by supplying an `applicant_id`; this is permitted only while the parcel is still `PROSPECT`, since ownership of land bank inventory changes only through conveyance, and an attempt on any other parcel is refused with `ERR_PROPERTY_NOT_IN_INVENTORY`.

    Design: Corner/validations/owner_of_record_on_acquired_parcel_rejected
    """
    funding_source = fixtures.create_acquisition_funding_source(
        api, name="Owner Record Line"
    )
    applicant = fixtures.create_applicant(
        api,
        legal_name="Iris Nakamura",
        applicant_type="INDIVIDUAL",
        contact_email="iris@example.com",
    )
    bundle = fixtures.acquired_parcel(
        api,
        funding_source=funding_source,
        property_overrides={
            "parcel_id": "APN-203060",
            "address": "3060 Fir Ln",
            "situs_ward": 3,
            "lot_area_sqft": 6000,
            "assessed_value_cents": 300000,
            "structure_present": False,
            "structure_condition_grade": "C",
            "vacancy_months": 4,
        },
        packet_overrides={"donor_name": "Fir Lane Estate"},
    )
    before = bundle["property"]
    assert before["custody_status"] == "ACQUIRED"

    response = api.set_owner_of_record(
        before["id"], {"applicant_id": applicant["id"]}, INTAKE_1
    )
    validate_error(response, ApiErrorId.PROPERTY_NOT_IN_INVENTORY.value)

    after = fixtures.read_property(api, before["id"])
    assert after["owner_of_record_applicant_id"] is None
    assert after["custody_status"] == "ACQUIRED"
    assert after["version"] == before["version"]

    # The roll-ups a successful recording would have refreshed are untouched.
    buyer = fixtures.read_applicant(api, applicant["id"])
    assert buyer["conveyed_property_count"] == 0
    assert buyer["delinquent_tax_total_cents"] == 0
    assert buyer["version"] == applicant["version"]
