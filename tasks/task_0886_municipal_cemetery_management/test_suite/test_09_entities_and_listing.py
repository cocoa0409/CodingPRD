"""Entity round-trips, immutability, computed fields, listing and reverse-reach."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    TEST_USERS, create_cemetery, create_plot, create_holder,
    create_decedent_payload, setup_issued_deed,
)

REG = TEST_USERS["registrar_headers"]
DIR = TEST_USERS["cemetery_director_headers"]


# ── Corner: entities / create_and_get_holder_roundtrips ──

def test_create_and_get_holder_roundtrips(api):
    """PRD §3.2: "the buyer must exist as a RightHolder, created by a Registrar with a
    full_name, an email, and an optional phone." PRD §2.4: "Each has an id that is a
    server-minted UUID with no type prefix".

    Design: Corner/entities/create_and_get_holder_roundtrips
    """
    from test_helpers import create_holder_payload
    created = validate_success(api.create_holder(
        create_holder_payload(full_name="Ada Grave", email="ada@x.com", phone="5"), REG), 201)
    fetched = validate_success(api.get_holder(created["id"], REG), 200)
    assert fetched["full_name"] == "Ada Grave"
    assert fetched["id"] == created["id"]


# ── Corner: entities / decedent_immutable_no_version_field ──

def test_decedent_immutable_no_version_field(api):
    """PRD §2.4: "A Decedent is an immutable genealogy record and a Payment and a
    CareFundEntry are append-only events; each of these carries only id and created_at.
    They have no updated_at and no version at all, and once written they are never
    modified in place." PRD §3.2: "On creation the server parses death_year from
    date_of_death".

    Design: Corner/entities/decedent_immutable_no_version_field
    """
    created = validate_success(api.create_decedent(
        create_decedent_payload(full_name="Silent Sam", date_of_death="2025-12-31",
                                date_of_birth="1950-01-01"), REG), 201)
    fetched = validate_success(api.get_decedent(created["id"], REG), 200)
    assert fetched["death_year"] == 2025
    assert "version" not in fetched
    assert "updated_at" not in fetched


# ── Corner: entities / computed_death_year_ignores_client_value ──

def test_computed_death_year_derived_from_date_of_death(api):
    """PRD §3.2: "On creation the server parses death_year from date_of_death; this
    year is the filter key for genealogy lookup".

    Design: Corner/entities/computed_death_year_ignores_client_value
    """
    created = validate_success(api.create_decedent(
        create_decedent_payload(full_name="Rey Cord", date_of_death="2019-08-15"), REG), 201)
    fetched = validate_success(api.get_decedent(created["id"], REG), 200)
    assert fetched["death_year"] == 2019


# ── Corner: endpoints / list_plots_pagination_envelope ──

def test_list_plots_pagination_envelope(api):
    """PRD §2.3: "Every list response includes limit, offset, total_count, and
    has_more in the meta object of the envelope."

    Design: Corner/endpoints/list_plots_pagination_envelope
    """
    cem = create_cemetery()
    create_plot(cem["id"], plot_type="GRAVE", interment_capacity=2, plot_number="1", gis_lng=2.0)
    create_plot(cem["id"], plot_type="NICHE", interment_capacity=1, plot_number="2", gis_lng=2.1)
    data, meta = validate_paginated(api.list_plots(REG, params={"cemetery_id": cem["id"]}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is False


# ── Corner: endpoints / reverse_reach_deeds_by_plot_id ──

def test_reverse_reach_deeds_by_plot_id(api):
    """PRD §3.2: "Deeds can be listed and filtered by plot_id, holder_id,
    pending_new_holder_id, and status".

    Design: Corner/endpoints/reverse_reach_deeds_by_plot_id
    """
    r = setup_issued_deed()
    data, meta = validate_paginated(api.list_deeds(REG, params={"plot_id": r["plot"]["id"]}))
    assert len(data) == 1
    assert data[0]["id"] == r["deed"]["id"]


# ── Corner: endpoints / genealogy_lookup_empty_result_set ──

def test_genealogy_lookup_empty_result_set(api):
    """PRD §3.2: "this year is the filter key for genealogy lookup, which searches
    decedents by full_name and death_year." PRD §2.3: "Every list response includes
    limit, offset, total_count, and has_more in the meta object".

    Design: Corner/endpoints/genealogy_lookup_empty_result_set
    """
    validate_success(api.create_decedent(
        create_decedent_payload(full_name="Modern Person", date_of_death="2026-01-02"), REG), 201)
    data, meta = validate_paginated(api.list_decedents(REG, params={"death_year": 1899}))
    assert meta["total_count"] == 0
    assert len(data) == 0


# ── Corner: state_machines / retire_sold_plot_not_available ──

def test_retire_sold_plot_not_available(api):
    """PRD §3.1: "retirement is permitted only when the plot is AVAILABLE (otherwise
    ERR_PLOT_NOT_AVAILABLE) and its interments_used is exactly 0."

    Design: Corner/state_machines/retire_sold_plot_not_available
    """
    r = setup_issued_deed()  # plot is SOLD
    res = api.retire_plot(r["plot"]["id"], DIR)
    validate_error(res, "ERR_PLOT_NOT_AVAILABLE")
