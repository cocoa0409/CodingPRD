"""Payload factories — one per entity, input fields only."""


def create_jurisdiction_payload(**overrides) -> dict:
    payload = {
        "name": "Maple County",
        "state_code": "CA",
        "target_district_count": 2,
    }
    payload.update(overrides)
    return payload


def create_census_block_payload(**overrides) -> dict:
    payload = {
        "geoid": "G1",
        "population": 1000,
        "voting_age_population": 800,
        "minority_vap": 200,
        "registered_voters": 600,
    }
    payload.update(overrides)
    return payload


def create_plan_payload(**overrides) -> dict:
    payload = {"name": "Scenario A"}
    payload.update(overrides)
    return payload


def create_district_payload(district_number=1, **overrides) -> dict:
    payload = {"district_number": district_number}
    payload.update(overrides)
    return payload


def create_block_assignment_payload(district_id, census_block_id, expected_plan_version, **overrides) -> dict:
    payload = {
        "district_id": district_id,
        "census_block_id": census_block_id,
        "expected_plan_version": expected_plan_version,
    }
    payload.update(overrides)
    return payload


def create_precinct_payload(**overrides) -> dict:
    payload = {"name": "Precinct 1"}
    payload.update(overrides)
    return payload


def create_polling_place_payload(**overrides) -> dict:
    payload = {
        "name": "Community Gym",
        "address": "1 Main St",
        "capacity": 5000,
    }
    payload.update(overrides)
    return payload


def create_polling_assignment_payload(polling_place_id, ev_start_date, ev_end_date,
                                      expected_precinct_version, **overrides) -> dict:
    payload = {
        "polling_place_id": polling_place_id,
        "ev_start_date": ev_start_date,
        "ev_end_date": ev_end_date,
        "expected_precinct_version": expected_precinct_version,
    }
    payload.update(overrides)
    return payload


def create_venue_payload(**overrides) -> dict:
    payload = {"name": "City Hall", "capacity": 100}
    payload.update(overrides)
    return payload


def create_hearing_payload(venue_id, scheduled_start, scheduled_end, **overrides) -> dict:
    payload = {
        "venue_id": venue_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    payload.update(overrides)
    return payload


def create_comment_payload(**overrides) -> dict:
    payload = {"commenter_name": "Jane Public", "comment_text": "Keep our neighborhood whole."}
    payload.update(overrides)
    return payload


def create_compliance_check_payload(check_type="POPULATION_DEVIATION", **overrides) -> dict:
    payload = {"check_type": check_type}
    payload.update(overrides)
    return payload


def create_export_payload(export_format="GEOJSON", **overrides) -> dict:
    payload = {"export_format": export_format}
    payload.update(overrides)
    return payload


def split_payload(child_a_name, child_a_block_geoids, child_b_name, child_b_block_geoids) -> dict:
    return {
        "child_a_name": child_a_name,
        "child_a_block_geoids": child_a_block_geoids,
        "child_b_name": child_b_name,
        "child_b_block_geoids": child_b_block_geoids,
    }


def merge_payload(target_precinct_id) -> dict:
    return {"target_precinct_id": target_precinct_id}


def disposition_payload(disposition) -> dict:
    return {"disposition": disposition}
