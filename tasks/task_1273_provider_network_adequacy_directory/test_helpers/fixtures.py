"""Composite setup helpers (PRD §3 workflows).

Every helper builds preconditions from scratch using only PRD-declared endpoints,
because each test runs against a freshly restarted server. Setup calls use the
lenient get_success_data() so failures surface as clear setup errors.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    create_region_payload, create_standard_payload, create_provider_payload,
    create_location_payload, create_listing_payload, create_member_payload,
    create_cycle_payload, create_probe_payload, create_evaluation_payload,
    create_access_plan_request_payload, create_complaint_payload,
)
from .test_users import TEST_USERS, make_provider_rep_headers, make_member_headers

NM = TEST_USERS["network_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]
REG = TEST_USERS["regulator_headers"]


# ---------------------------------------------------------------------------
# Tier 0: primitive validated wrappers
# ---------------------------------------------------------------------------

def set_clock(to_iso: str) -> dict:
    """Advance the logical clock (PRD §2.4)."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso}, NM))


def create_region(**overrides) -> dict:
    return get_success_data(api_client.create_region(create_region_payload(**overrides), NM))


def create_standard(**overrides) -> dict:
    return get_success_data(api_client.create_standard(create_standard_payload(**overrides), NM))


def create_provider(**overrides) -> dict:
    return get_success_data(api_client.create_provider(create_provider_payload(**overrides), NM))


def create_location(provider_id: str, region_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_location(
        create_location_payload(provider_id, region_id, **overrides), NM))


def create_listing(provider_id: str, location_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_listing(
        create_listing_payload(provider_id, location_id, **overrides), NM))


def publish_listing(listing_id: str) -> dict:
    return get_success_data(api_client.publish_listing(listing_id, NM))


def create_member(region_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_member(create_member_payload(region_id, **overrides), NM))


def create_cycle(**overrides) -> dict:
    return get_success_data(api_client.create_cycle(create_cycle_payload(**overrides), NM))


def create_probe(listing_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_probe(create_probe_payload(listing_id, **overrides), NM))


def record_probe(probe_id: str, **overrides) -> dict:
    return get_success_data(api_client.record_probe(probe_id, record_probe_payload_minimal(**overrides), NM))


def record_probe_payload_minimal(**overrides) -> dict:
    return dict(overrides)


def create_evaluation(**overrides) -> dict:
    return get_success_data(api_client.create_evaluation(create_evaluation_payload(**overrides), NM))


def finalize_evaluation(evaluation_id: str) -> dict:
    return get_success_data(api_client.finalize_evaluation(evaluation_id, NM))


def get_listing(listing_id: str) -> dict:
    return get_success_data(api_client.get_listing(listing_id, NM))


def get_cycle(cycle_id: str) -> dict:
    return get_success_data(api_client.get_cycle(cycle_id, NM))


def get_deficiency(deficiency_id: str) -> dict:
    return get_success_data(api_client.get_deficiency(deficiency_id, NM))


def get_evaluation(evaluation_id: str) -> dict:
    return get_success_data(api_client.get_evaluation(evaluation_id, NM))


def list_records(params: dict) -> list:
    data, _meta = validate_paginated(api_client.list_attestation_records(NM, params=params))
    return data


def list_listings(params: dict) -> list:
    params = {"limit": 100, **params}
    data, _meta = validate_paginated(api_client.list_listings(NM, params=params))
    return data


def list_results(params: dict) -> list:
    data, _meta = validate_paginated(api_client.list_results(NM, params=params))
    return data


def list_deficiencies(params: dict) -> list:
    data, _meta = validate_paginated(api_client.list_deficiencies(NM, params=params))
    return data


def get_only_result(evaluation_id: str, region_id: str) -> dict:
    rows = list_results({"evaluation_id": evaluation_id, "region_id": region_id})
    assert len(rows) == 1, f"expected exactly 1 result row, got {len(rows)}"
    return rows[0]


def get_only_deficiency(evaluation_id: str, region_id: str) -> dict:
    rows = list_deficiencies({"evaluation_id": evaluation_id, "region_id": region_id})
    assert len(rows) == 1, f"expected exactly 1 deficiency, got {len(rows)}"
    return rows[0]


# ---------------------------------------------------------------------------
# Tier 1/2: listed-network building blocks
# ---------------------------------------------------------------------------

def setup_listed_network(
    county_fips=None,
    enrolled_member_count=100,
    specialty="CARDIOLOGY",
    geo_class="URBAN",
    standard_overrides=None,
    provider_overrides=None,
    location_overrides=None,
    listing_overrides=None,
    clock="2026-05-01T00:00:00Z",
) -> dict:
    """Region + standard + EFFECTIVE provider + OPEN location + LISTED listing."""
    set_clock(clock)
    region = create_region(
        **({"county_fips": county_fips} if county_fips else {}),
        name="Fixture County", geo_class=geo_class,
        enrolled_member_count=enrolled_member_count,
    )
    std_kwargs = dict(standard_overrides or {})
    standard = create_standard(specialty=specialty, geo_class=geo_class, **std_kwargs)
    provider = create_provider(**(dict(specialty=specialty, **(provider_overrides or {}))))
    location = create_location(provider["id"], region["id"], **(location_overrides or {}))
    listing = create_listing(provider["id"], location["id"],
                             **(dict(specialty=specialty, **(listing_overrides or {}))))
    published = publish_listing(listing["id"])
    return {
        "region": region, "standard": standard, "provider": provider,
        "location": location, "listing": published,
    }


def setup_provider_with_n_listings(
    n: int,
    county_fips=None,
    enrolled_member_count=100,
    specialty="CARDIOLOGY",
    geo_class="URBAN",
    standard_overrides=None,
    location_overrides_list=None,
    clock="2026-05-01T00:00:00Z",
) -> dict:
    """One EFFECTIVE provider with n OPEN locations, each hosting a LISTED listing."""
    set_clock(clock)
    region = create_region(
        **({"county_fips": county_fips} if county_fips else {}),
        name="Multi County", geo_class=geo_class,
        enrolled_member_count=enrolled_member_count,
    )
    standard = create_standard(specialty=specialty, geo_class=geo_class,
                               **(standard_overrides or {}))
    provider = create_provider(specialty=specialty)
    locations, listings = [], []
    for i in range(n):
        loc_over = (location_overrides_list[i] if location_overrides_list else {})
        loc = create_location(provider["id"], region["id"],
                              **{"address_line": f"{i + 1} Fixture Ave", **loc_over})
        lst = create_listing(provider["id"], loc["id"], specialty=specialty,
                             display_name=f"Listing {i + 1}", phone=f"555-{1000 + i}")
        listings.append(publish_listing(lst["id"]))
        locations.append(loc)
    return {
        "region": region, "standard": standard, "provider": provider,
        "locations": locations, "listings": listings,
    }


# ---------------------------------------------------------------------------
# Tier 3: attestation cycle setups
# ---------------------------------------------------------------------------

def setup_open_cycle_for_listings(listing_ids=None, **cycle_overrides) -> dict:
    """Create a cycle and advance SCHEDULED -> OPEN (records created for all LISTED listings).
    Clock must already be >= open_date (default 2026-05-01 with default fixture clock)."""
    cycle = create_cycle(**cycle_overrides)
    advanced = get_success_data(api_client.advance_cycle(cycle["id"], NM))
    records = list_records({"cycle_id": cycle["id"], "limit": 100})
    return {"cycle": advanced, "records": records}


def record_for_listing(cycle_id: str, listing_id: str) -> dict:
    rows = list_records({"cycle_id": cycle_id, "listing_id": listing_id})
    assert len(rows) == 1, f"expected exactly 1 record for listing, got {len(rows)}"
    return rows[0]


def respond_record(record_id: str, provider_id: str, data_accurate=True, corrected_payload=None) -> dict:
    payload = {"data_accurate": data_accurate}
    if corrected_payload is not None:
        payload["corrected_payload"] = corrected_payload
    return get_success_data(api_client.respond_attestation_record(
        record_id, payload, make_provider_rep_headers(provider_id)))


# ---------------------------------------------------------------------------
# Tier 4: deficiency / evaluation setups
# ---------------------------------------------------------------------------

def setup_open_deficiency(
    county_fips=None,
    enrolled_member_count=12000,
    specialty="DERMATOLOGY",
    geo_class="URBAN",
    max_members_per_provider=15000,
    period_start_date="2026-06-01",
    period_end_date="2026-06-11",
    measurement_period="E1",
    clock="2026-05-01T00:00:00Z",
) -> dict:
    """Region + standard, zero providers of the specialty: finalize opens an OPEN deficiency."""
    set_clock(clock)
    region = create_region(
        **({"county_fips": county_fips} if county_fips else {}),
        name="Deficiency County", geo_class=geo_class,
        enrolled_member_count=enrolled_member_count,
    )
    standard = create_standard(specialty=specialty, geo_class=geo_class,
                               max_members_per_provider=max_members_per_provider)
    evaluation = create_evaluation(measurement_period=measurement_period,
                                   period_start_date=period_start_date,
                                   period_end_date=period_end_date)
    finalized = finalize_evaluation(evaluation["id"])
    deficiency = get_only_deficiency(evaluation["id"], region["id"])
    return {"region": region, "standard": standard,
            "evaluation": finalized, "deficiency": deficiency}


def create_request_for_deficiency(deficiency: dict, **overrides) -> dict:
    """File an AccessPlanRequest against the deficiency at its current version."""
    fresh = get_deficiency(deficiency["id"])
    payload = create_access_plan_request_payload(fresh["version"], **overrides)
    return get_success_data(api_client.create_access_plan_request(deficiency["id"], payload, NM))


def submit_request(request_id: str) -> dict:
    return get_success_data(api_client.submit_access_plan_request(request_id, NM))


def decide_request(request_id: str, decision: str, notes=None) -> dict:
    payload = {"decision": decision}
    if notes is not None:
        payload["notes"] = notes
    return get_success_data(api_client.decide_access_plan_request(request_id, payload, REG))


# ---------------------------------------------------------------------------
# Tier 5: complaint / correction pipeline setups
# ---------------------------------------------------------------------------

def setup_complaint(region, listing, observed_date="2026-04-25", **overrides):
    """ENROLLED member in the listing's region + OPEN complaint filed by that member."""
    member = create_member(region["id"])
    payload = create_complaint_payload(listing["id"], error_observed_date=observed_date, **overrides)
    complaint = get_success_data(api_client.create_complaint(
        payload, make_member_headers(member["id"])))
    return {"member": member, "complaint": complaint}


def confirm_complaint(complaint_id: str, correction_changes=None, notes=None):
    """Adjudicate CONFIRMED_ERROR; returns (complaint, spawned_correction)."""
    payload = {"outcome": "CONFIRMED_ERROR",
               "correction_changes": correction_changes or {"phone": "555-9999"}}
    if notes is not None:
        payload["notes"] = notes
    complaint = get_success_data(api_client.adjudicate_complaint(complaint_id, payload, CO))
    data, _meta = validate_paginated(api_client.list_corrections(
        CO, params={"complaint_id": complaint_id}))
    assert len(data) == 1, f"expected 1 spawned correction, got {len(data)}"
    return complaint, data[0]
