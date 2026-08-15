"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so all preconditions are built here from PRD-declared
endpoints only. Identity threading rule: Generator/Offtaker calls always use
make_generator_headers/make_offtaker_headers with the real entity id.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_characterization_payload,
    create_delivery_payload,
    create_eligibility_payload,
    create_generator_payload,
    create_offtake_commitment_payload,
    create_offtaker_payload,
    create_price_index_payload,
    create_shipment_payload,
    create_state_permit_payload,
    create_storage_facility_payload,
    create_storage_reservation_payload,
    create_stream_payload,
    create_supply_agreement_payload,
)
from .test_users import (
    TEST_USERS,
    make_generator_headers,
    make_offtaker_headers,
)

BROKER = TEST_USERS["broker_ops_headers"]
CO_FILE = TEST_USERS["compliance_officer_file_headers"]
CO_APPR = TEST_USERS["compliance_officer_approve_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-resource creators
# ---------------------------------------------------------------------------

def create_generator(**overrides) -> dict:
    resp = api_client.create_generator(create_generator_payload(**overrides), BROKER)
    return get_success_data(resp)


def create_offtaker(**overrides) -> dict:
    resp = api_client.create_offtaker(create_offtaker_payload(**overrides), BROKER)
    return get_success_data(resp)


def create_stream(generator_id: str, **overrides) -> dict:
    resp = api_client.create_stream(
        create_stream_payload(generator_id, **overrides),
        make_generator_headers(generator_id),
    )
    return get_success_data(resp)


def create_characterization(stream_id: str, generator_id: str, **overrides) -> dict:
    resp = api_client.create_characterization(
        stream_id,
        create_characterization_payload(**overrides),
        make_generator_headers(generator_id),
    )
    return get_success_data(resp)


def verify_characterization(characterization_id: str) -> dict:
    return get_success_data(api_client.verify_characterization(characterization_id, BROKER))


def file_eligibility(stream_id: str, **overrides) -> dict:
    """File a DRAFT determination as the filing officer (co_file)."""
    resp = api_client.create_eligibility_determination(
        stream_id, create_eligibility_payload(**overrides), CO_FILE
    )
    return get_success_data(resp)


def submit_eligibility(determination_id: str) -> dict:
    return get_success_data(api_client.submit_eligibility(determination_id, CO_FILE))


def approve_eligibility(determination_id: str) -> dict:
    """Approve as a different officer than the filer (segregation of duties)."""
    return get_success_data(api_client.approve_eligibility(determination_id, CO_APPR))


def file_and_approve_eligibility(stream_id: str, **overrides) -> dict:
    det = file_eligibility(stream_id, **overrides)
    submit_eligibility(det["id"])
    return approve_eligibility(det["id"])


def create_active_permit(**overrides) -> dict:
    resp = api_client.create_state_permit(create_state_permit_payload(**overrides), CO_FILE)
    permit = get_success_data(resp)
    return get_success_data(api_client.activate_state_permit(permit["id"], CO_FILE))


def create_draft_agreement(generator_id: str, stream_id: str, **overrides) -> dict:
    resp = api_client.create_supply_agreement(
        create_supply_agreement_payload(generator_id, stream_id, **overrides),
        make_generator_headers(generator_id),
    )
    return get_success_data(resp)


def create_active_agreement(generator_id: str, stream_id: str, **overrides) -> dict:
    agreement = create_draft_agreement(generator_id, stream_id, **overrides)
    return get_success_data(api_client.activate_supply_agreement(agreement["id"], BROKER))


def create_draft_commitment(offtaker_id: str, stream_id: str, **overrides) -> dict:
    resp = api_client.create_offtake_commitment(
        create_offtake_commitment_payload(offtaker_id, stream_id, **overrides),
        make_offtaker_headers(offtaker_id),
    )
    return get_success_data(resp)


def create_active_commitment(offtaker_id: str, stream_id: str, **overrides) -> dict:
    commitment = create_draft_commitment(offtaker_id, stream_id, **overrides)
    return get_success_data(api_client.activate_offtake_commitment(commitment["id"], BROKER))


def publish_price_index(**overrides) -> dict:
    resp = api_client.create_price_index_entry(create_price_index_payload(**overrides), BROKER)
    return get_success_data(resp)


def set_logical_clock(to_iso8601: str) -> dict:
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy
# ---------------------------------------------------------------------------

def create_characterized_stream(material_type: str = "FLY_ASH", **stream_overrides) -> dict:
    """Generator + stream + one VERIFIED characterization (stream bubbles to
    CHARACTERIZED). Returns {"generator", "stream", "characterization"}."""
    generator = create_generator()
    stream = create_stream(generator["id"], material_type=material_type, **stream_overrides)
    characterization = create_characterization(stream["id"], generator["id"])
    verify_characterization(characterization["id"])
    stream = get_success_data(
        api_client.get_stream(stream["id"], BROKER)
    )
    return {
        "generator": generator,
        "stream": stream,
        "characterization": characterization,
    }


# ---------------------------------------------------------------------------
# Tier 3: commercial chain (agreement + commitment), booking-ready and
# dispatch-ready variants
# ---------------------------------------------------------------------------

def setup_booking_ready_chain(
    committed_agreement_tons: int = 500,
    committed_commitment_tons: int = 500,
    revenue_share_pct_to_generator: float = 0.6,
    freight_share_pct_to_generator: float = 0.25,
    term_start: str = TEST_DEFAULTS["TERM_START"],
    term_end: str = TEST_DEFAULTS["TERM_END"],
    destination_state_code: str = TEST_DEFAULTS["DESTINATION_STATE"],
    max_moisture_pct: float = TEST_DEFAULTS["MAX_MOISTURE_PCT"],
    max_arsenic_ppm: float = TEST_DEFAULTS["MAX_ARSENIC_PPM"],
    material_type: str = "FLY_ASH",
    index_price_cents_per_ton: int = TEST_DEFAULTS["INDEX_PRICE_CENTS_PER_TON"],
    index_effective_from: str = TEST_DEFAULTS["INDEX_EFFECTIVE_FROM"],
    receiving_state_codes=("PA", "WV"),
    publish_index: bool = True,
) -> dict:
    """Generator + offtaker + CHARACTERIZED stream + ACTIVE agreement +
    ACTIVE commitment + (optionally) one price index entry.

    Booking requires no eligibility determination or permit, so this chain
    supports every booking-gate test. Returns a chain dict.
    """
    base = create_characterized_stream(material_type=material_type)
    generator, stream = base["generator"], base["stream"]
    offtaker = create_offtaker(receiving_state_codes=list(receiving_state_codes))
    agreement = create_active_agreement(
        generator["id"],
        stream["id"],
        committed_monthly_tons=committed_agreement_tons,
        revenue_share_pct_to_generator=revenue_share_pct_to_generator,
        freight_share_pct_to_generator=freight_share_pct_to_generator,
        term_start=term_start,
        term_end=term_end,
    )
    commitment = create_active_commitment(
        offtaker["id"],
        stream["id"],
        destination_state_code=destination_state_code,
        committed_monthly_tons=committed_commitment_tons,
        max_moisture_pct=max_moisture_pct,
        max_arsenic_ppm=max_arsenic_ppm,
    )
    price_entry = (
        publish_price_index(
            material_type=material_type,
            region_code=destination_state_code,
            effective_from=index_effective_from,
            price_cents_per_ton=index_price_cents_per_ton,
        )
        if publish_index
        else None
    )
    return {
        **base,
        "offtaker": offtaker,
        "agreement": agreement,
        "commitment": commitment,
        "price_entry": price_entry,
        "eligibility": None,
        "permit": None,
        "generator_headers": make_generator_headers(generator["id"]),
        "offtaker_headers": make_offtaker_headers(offtaker["id"]),
    }


def setup_dispatch_ready_chain(
    eligibility_valid_from: str = TEST_DEFAULTS["ELIGIBILITY_VALID_FROM"],
    eligibility_valid_until: str = TEST_DEFAULTS["ELIGIBILITY_VALID_UNTIL"],
    eligibility_state_code: str = None,
    use_case: str = "CEMENT_ADDITIVE",
    permit_issued_on: str = TEST_DEFAULTS["PERMIT_ISSUED_ON"],
    permit_expires_on: str = TEST_DEFAULTS["PERMIT_EXPIRES_ON"],
    include_eligibility: bool = True,
    include_permit: bool = True,
    **kwargs,
) -> dict:
    """Booking-ready chain plus an APPROVED eligibility determination and an
    ACTIVE state permit, so shipments can be dispatched."""
    chain = setup_booking_ready_chain(**kwargs)
    destination = chain["commitment"]["destination_state_code"]
    material = chain["stream"]["material_type"]
    if include_eligibility:
        chain["eligibility"] = file_and_approve_eligibility(
            chain["stream"]["id"],
            state_code=eligibility_state_code or destination,
            use_case=use_case,
            valid_from=eligibility_valid_from,
            valid_until=eligibility_valid_until,
        )
    if include_permit:
        chain["permit"] = create_active_permit(
            state_code=destination,
            material_type=material,
            issued_on=permit_issued_on,
            expires_on=permit_expires_on,
        )
    return chain


# ---------------------------------------------------------------------------
# Tier 4: shipment lifecycle shortcuts
# ---------------------------------------------------------------------------

def get_agreement_version(agreement_id: str) -> int:
    return get_success_data(api_client.get_supply_agreement(agreement_id, BROKER))["version"]


def get_agreement(agreement_id: str) -> dict:
    return get_success_data(api_client.get_supply_agreement(agreement_id, BROKER))


def get_commitment(commitment_id: str) -> dict:
    return get_success_data(api_client.get_offtake_commitment(commitment_id, BROKER))


def get_shipment(shipment_id: str) -> dict:
    return get_success_data(api_client.get_shipment(shipment_id, BROKER))


def get_generator(generator_id: str) -> dict:
    return get_success_data(api_client.get_generator(generator_id, BROKER))


def book_shipment(
    chain: dict,
    gross_tons=10,
    pickup_date: str = TEST_DEFAULTS["PICKUP_DATE"],
    distance_miles: int = TEST_DEFAULTS["DISTANCE_MILES"],
    loading_moisture_pct: float = TEST_DEFAULTS["LOADING_MOISTURE_PCT"],
) -> dict:
    """Book a shipment on the chain's agreement+commitment, re-reading the
    agreement version immediately beforehand (OCC). Returns the Shipment."""
    version = get_agreement_version(chain["agreement"]["id"])
    resp = api_client.create_shipment(
        create_shipment_payload(
            chain["agreement"]["id"],
            chain["commitment"]["id"],
            version,
            gross_tons=gross_tons,
            pickup_date=pickup_date,
            distance_miles=distance_miles,
            loading_moisture_pct=loading_moisture_pct,
        ),
        chain["generator_headers"],
    )
    return get_success_data(resp)


def dispatch_shipment(chain: dict, shipment_id: str) -> dict:
    return get_success_data(
        api_client.dispatch_shipment(shipment_id, chain["generator_headers"])
    )


def deliver_shipment(chain: dict, shipment_id: str, **measurement_overrides) -> dict:
    return get_success_data(
        api_client.deliver_shipment(
            shipment_id,
            create_delivery_payload(**measurement_overrides),
            chain["offtaker_headers"],
        )
    )


def dispatch_and_deliver(chain: dict, shipment_id: str, **measurement_overrides) -> dict:
    dispatch_shipment(chain, shipment_id)
    return deliver_shipment(chain, shipment_id, **measurement_overrides)


def accept_shipment(chain: dict, shipment_id: str) -> dict:
    return get_success_data(api_client.accept_shipment(shipment_id, chain["offtaker_headers"]))


def book_dispatch_deliver(
    chain: dict, gross_tons=10, pickup_date: str = TEST_DEFAULTS["PICKUP_DATE"], **measurements
) -> dict:
    """Book + dispatch + deliver. Returns the DELIVERED shipment."""
    shipment = book_shipment(chain, gross_tons=gross_tons, pickup_date=pickup_date)
    return dispatch_and_deliver(chain, shipment["id"], **measurements)


def book_dispatch_deliver_accept(
    chain: dict, gross_tons=10, pickup_date: str = TEST_DEFAULTS["PICKUP_DATE"], **measurements
) -> dict:
    """Full happy path: book + dispatch + deliver + accept. Returns ACCEPTED shipment."""
    delivered = book_dispatch_deliver(
        chain, gross_tons=gross_tons, pickup_date=pickup_date, **measurements
    )
    return accept_shipment(chain, delivered["id"])


# ---------------------------------------------------------------------------
# Tier 5: storage
# ---------------------------------------------------------------------------

def create_facility(**overrides) -> dict:
    resp = api_client.create_storage_facility(create_storage_facility_payload(**overrides), BROKER)
    return get_success_data(resp)


def create_reservation(facility_id: str, stream_id: str, **overrides) -> dict:
    resp = api_client.create_storage_reservation(
        create_storage_reservation_payload(facility_id, stream_id, **overrides), BROKER
    )
    return get_success_data(resp)


def setup_facility_with_stream(capacity_tons: int = 1000, material_types_allowed=("FLY_ASH",)) -> dict:
    """Generator + stream + storage facility. Returns dict with all three."""
    generator = create_generator()
    stream = create_stream(generator["id"])
    facility = create_facility(
        capacity_tons=capacity_tons, material_types_allowed=list(material_types_allowed)
    )
    return {"generator": generator, "stream": stream, "facility": facility}
