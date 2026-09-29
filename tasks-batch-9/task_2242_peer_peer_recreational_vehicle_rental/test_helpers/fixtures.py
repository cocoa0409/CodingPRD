"""Composite setup helpers.

Every test starts against an empty database, so each helper here rebuilds the
state it needs purely from published endpoints. They are layered:

* configuration and identities (clock, owner, renter, seasons, plan, policy),
* a listing carried from DRAFT through IN_REVIEW to LISTED,
* a booking carried along the trip dimension to REQUESTED / CONFIRMED /
  IN_TRIP / RETURNED / CLOSED,
* accumulation shortcuts that drive a counter straight to a threshold
  (penalty points, driving-record points, exhausted info rounds),
* terminal-state shortcuts (settled bookings, scheduled drop-offs, claims
  parked mid-review).

Setup traffic uses ``get_success_data`` so that a broken precondition surfaces
as a setup failure rather than as a confusing assertion inside the test body.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .constants import DEFAULT_CLOCK_UTC
from .test_users import (
    CLAIMS_ADJUSTER_HEADERS,
    PLATFORM_ADMIN_HEADERS,
    make_owner_headers,
    make_renter_headers,
)
from .types import (
    CauseCode,
    DeliveryOption,
    PhotoPhase,
    QualificationResult,
    Zone,
)

# The five zones a listing must photograph, in the canonical upload order.
_LISTING_ZONES = (
    Zone.EXTERIOR_FRONT,
    Zone.EXTERIOR_REAR,
    Zone.INTERIOR,
    Zone.ROOF,
    Zone.UNDERCARRIAGE,
)

# The four zones a trip must photograph plus the fifth the canonical trip adds.
_TRIP_ZONES = (
    Zone.EXTERIOR_FRONT,
    Zone.EXTERIOR_REAR,
    Zone.INTERIOR,
    Zone.ROOF,
    Zone.UNDERCARRIAGE,
)


# ===========================================================================
# World container
# ===========================================================================
@dataclass
class Marketplace:
    """Identifiers and versions for a seeded marketplace."""

    owner_id: str = ""
    renter_id: str = ""
    plan_id: str = ""
    policy_id: str = ""
    season_ids: Dict[str, str] = field(default_factory=dict)
    listing_id: str = ""
    listing_version: int = 0
    document_ids: Dict[str, str] = field(default_factory=dict)
    campground_id: str = ""
    booking_id: str = ""
    booking_version: int = 0
    assignment_id: str = ""
    claim_id: str = ""

    @property
    def owner_headers(self) -> Dict[str, str]:
        return make_owner_headers(self.owner_id)

    @property
    def renter_headers(self) -> Dict[str, str]:
        return make_renter_headers(self.renter_id)

    @property
    def admin_headers(self) -> Dict[str, str]:
        return PLATFORM_ADMIN_HEADERS

    @property
    def adjuster_headers(self) -> Dict[str, str]:
        return CLAIMS_ADJUSTER_HEADERS


# ===========================================================================
# Tier 1 - clock, identities and configuration rows
# ===========================================================================
def set_clock(api, to_iso8601: str = DEFAULT_CLOCK_UTC) -> Dict[str, Any]:
    """Reposition the logical clock; used both as setup and as a trigger."""
    return get_success_data(api.set_clock(f.clock_payload(to_iso8601), PLATFORM_ADMIN_HEADERS))


def create_owner(api, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_owner(f.owner_payload(**overrides), PLATFORM_ADMIN_HEADERS))


def create_renter(api, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_renter(f.renter_payload(**overrides), PLATFORM_ADMIN_HEADERS)
    )


def create_pricing_seasons(api) -> Dict[str, str]:
    """The canonical PEAK / SHOULDER / OFF calendar."""
    seasons = {}
    for payload in (
        f.peak_season_payload(),
        f.shoulder_season_payload(),
        f.off_season_payload(),
    ):
        row = get_success_data(api.create_pricing_season(payload, PLATFORM_ADMIN_HEADERS))
        seasons[payload["season_code"]] = row["id"]
    return seasons


def create_protection_plan(api, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_protection_plan(f.protection_plan_payload(**overrides), PLATFORM_ADMIN_HEADERS)
    )


def create_cancellation_policy(api, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_cancellation_policy(
            f.cancellation_policy_payload(**overrides), PLATFORM_ADMIN_HEADERS
        )
    )


def add_driving_record_check(
    api,
    renter_id: str,
    violation_points: int = 2,
    result: str = QualificationResult.CLEAR,
    checked_at: str = "2026-07-01T00:00:00Z",
    expires_on: Optional[str] = "2027-07-01",
) -> Dict[str, Any]:
    return get_success_data(
        api.create_renter_qualification(
            f.driving_record_check_payload(
                renter_id,
                result=result,
                violation_points=violation_points,
                checked_at=checked_at,
                expires_on=expires_on,
            ),
            PLATFORM_ADMIN_HEADERS,
        )
    )


def add_towing_experience_check(
    api,
    renter_id: str,
    result: str = QualificationResult.VERIFIED_BASIC,
    checked_at: str = "2026-07-01T00:00:00Z",
    expires_on: Optional[str] = "2027-07-01",
) -> Dict[str, Any]:
    return get_success_data(
        api.create_renter_qualification(
            f.towing_experience_check_payload(
                renter_id, result=result, checked_at=checked_at, expires_on=expires_on
            ),
            PLATFORM_ADMIN_HEADERS,
        )
    )


def fund_renter(api, renter_id: str, amount_cents: int = 800000) -> Dict[str, Any]:
    return get_success_data(
        api.adjust_renter_wallet(
            renter_id,
            f.wallet_adjustment_payload(amount_cents),
            PLATFORM_ADMIN_HEADERS,
        )
    )


def adjust_owner_points(api, owner_id: str, points_delta: int, reason: str) -> Dict[str, Any]:
    return get_success_data(
        api.adjust_owner_penalty_points(
            owner_id, f.penalty_adjustment_payload(points_delta, reason), PLATFORM_ADMIN_HEADERS
        )
    )


def adjust_renter_points(api, renter_id: str, points_delta: int, reason: str) -> Dict[str, Any]:
    return get_success_data(
        api.adjust_renter_penalty_points(
            renter_id, f.penalty_adjustment_payload(points_delta, reason), PLATFORM_ADMIN_HEADERS
        )
    )


def seed_configuration(api, clock: str = DEFAULT_CLOCK_UTC) -> Marketplace:
    """Clock, one owner, one qualified renter, the seasons, plan and policy."""
    set_clock(api, clock)
    owner = create_owner(api)
    renter = create_renter(api)
    seasons = create_pricing_seasons(api)
    plan = create_protection_plan(api)
    policy = create_cancellation_policy(api)
    add_driving_record_check(api, renter["id"])
    add_towing_experience_check(api, renter["id"])
    return Marketplace(
        owner_id=owner["id"],
        renter_id=renter["id"],
        plan_id=plan["id"],
        policy_id=policy["id"],
        season_ids=seasons,
    )


# ===========================================================================
# Tier 2 - a listing from DRAFT to LISTED
# ===========================================================================
def create_draft_listing(api, owner_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_listing(f.listing_payload(owner_id, **overrides), make_owner_headers(owner_id))
    )


def upload_listing_documents(
    api,
    listing_id: str,
    owner_id: str,
    listing_version: int,
    doc_suffix: str = "1",
    inspection_prefix: str = "insp",
    zones: Sequence[str] = _LISTING_ZONES,
) -> Tuple[Dict[str, str], int]:
    """Upload title, registration, insurance and one inspection photo per zone.

    Each upload advances the parent listing's version, so the caller's
    ``expected_listing_version`` has to be threaded forward one step at a time.
    Returns the document identifiers and the listing version after the last
    upload.
    """
    headers = make_owner_headers(owner_id)
    version = listing_version
    documents: Dict[str, str] = {}

    title = get_success_data(
        api.create_vehicle_document(
            f.title_document_payload(
                listing_id, version, image_ref=f"s3://docs/title-{doc_suffix}.pdf"
            ),
            headers,
        )
    )
    documents["TITLE"] = title["id"]
    version += 1

    registration = get_success_data(
        api.create_vehicle_document(
            f.registration_document_payload(
                listing_id, version, image_ref=f"s3://docs/reg-{doc_suffix}.pdf"
            ),
            headers,
        )
    )
    documents["REGISTRATION"] = registration["id"]
    version += 1

    insurance = get_success_data(
        api.create_vehicle_document(
            f.insurance_document_payload(
                listing_id, version, image_ref=f"s3://docs/ins-{doc_suffix}.pdf"
            ),
            headers,
        )
    )
    documents["INSURANCE_POLICY"] = insurance["id"]
    version += 1

    for zone in zones:
        photo = get_success_data(
            api.create_vehicle_document(
                f.inspection_photo_payload(
                    listing_id,
                    zone,
                    version,
                    image_ref=f"s3://{inspection_prefix}/{zone.lower()}.jpg",
                ),
                headers,
            )
        )
        documents[f"INSPECTION_PHOTO:{zone}"] = photo["id"]
        version += 1

    return documents, version


def verify_core_documents(api, document_ids: Dict[str, str]) -> None:
    """Verify the title, registration and insurance policy."""
    for key in ("TITLE", "REGISTRATION", "INSURANCE_POLICY"):
        get_success_data(api.verify_vehicle_document(document_ids[key], PLATFORM_ADMIN_HEADERS))


def submit_listing(api, listing_id: str, owner_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.submit_listing_for_review(listing_id, make_owner_headers(owner_id))
    )


def approve_listing(api, listing_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.decide_listing(listing_id, f.listing_decision_payload("APPROVE"), PLATFORM_ADMIN_HEADERS)
    )


def reject_listing(api, listing_id: str, note: Optional[str] = None) -> Dict[str, Any]:
    payload = f.listing_decision_payload("REJECT")
    if note is not None:
        payload["decision_note"] = note
    return get_success_data(api.decide_listing(listing_id, payload, PLATFORM_ADMIN_HEADERS))


def seed_documented_listing(
    api,
    owner_id: str,
    doc_suffix: str = "1",
    inspection_prefix: str = "insp",
    **listing_overrides: Any,
) -> Tuple[Dict[str, Any], Dict[str, str], int]:
    """A DRAFT listing with every required document uploaded and verified."""
    listing = create_draft_listing(api, owner_id, **listing_overrides)
    documents, version = upload_listing_documents(
        api,
        listing["id"],
        owner_id,
        listing["version"],
        doc_suffix=doc_suffix,
        inspection_prefix=inspection_prefix,
    )
    verify_core_documents(api, documents)
    return listing, documents, version


def seed_listed_listing(
    api,
    owner_id: str,
    doc_suffix: str = "1",
    inspection_prefix: str = "insp",
    **listing_overrides: Any,
) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """A listing all the way to LISTED, with its documents verified."""
    listing, documents, _ = seed_documented_listing(
        api,
        owner_id,
        doc_suffix=doc_suffix,
        inspection_prefix=inspection_prefix,
        **listing_overrides,
    )
    submit_listing(api, listing["id"], owner_id)
    listed = approve_listing(api, listing["id"])
    return listed, documents


def seed_marketplace(
    api,
    fund_cents: int = 800000,
    clock: str = DEFAULT_CLOCK_UTC,
    **listing_overrides: Any,
) -> Marketplace:
    """The canonical marketplace: one LISTED towed trailer, one funded renter."""
    world = seed_configuration(api, clock=clock)
    listing, documents = seed_listed_listing(api, world.owner_id, **listing_overrides)
    world.listing_id = listing["id"]
    world.listing_version = listing["version"]
    world.document_ids = documents
    if fund_cents:
        fund_renter(api, world.renter_id, fund_cents)
    return world


def add_second_listed_listing(
    api, world: Marketplace, **listing_overrides: Any
) -> Dict[str, Any]:
    """A second LISTED listing under the same owner."""
    defaults = {
        "nickname": "Ponderosa 28RL",
        "length_ft": 32,
    }
    defaults.update(listing_overrides)
    listing, _ = seed_listed_listing(
        api,
        world.owner_id,
        doc_suffix="2",
        inspection_prefix="insp2",
        **defaults,
    )
    return listing


# ===========================================================================
# Tier 3 - a booking along the trip dimension
# ===========================================================================
def request_booking(api, world: Marketplace, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_booking(
            f.booking_payload(
                world.listing_id,
                world.renter_id,
                world.plan_id,
                world.policy_id,
                **overrides,
            ),
            world.renter_headers,
        )
    )


def approve_booking(api, world: Marketplace, booking_id: str) -> Dict[str, Any]:
    return get_success_data(api.approve_booking(booking_id, world.owner_headers))


def confirm_booking(api, world: Marketplace, booking_id: str) -> Dict[str, Any]:
    return get_success_data(api.confirm_booking(booking_id, world.renter_headers))


def seed_requested_booking(api, world: Marketplace, **overrides: Any) -> Dict[str, Any]:
    booking = request_booking(api, world, **overrides)
    world.booking_id = booking["id"]
    world.booking_version = booking["version"]
    return booking


def seed_approved_booking(api, world: Marketplace, **overrides: Any) -> Dict[str, Any]:
    booking = seed_requested_booking(api, world, **overrides)
    approved = approve_booking(api, world, booking["id"])
    world.booking_version = approved["version"]
    return approved


def seed_confirmed_booking(api, world: Marketplace, **overrides: Any) -> Dict[str, Any]:
    approved = seed_approved_booking(api, world, **overrides)
    confirmed = confirm_booking(api, world, approved["id"])
    world.booking_version = confirmed["version"]
    return confirmed


def record_meter_reading(
    api,
    world: Marketplace,
    booking_id: str,
    reading_type: str,
    odometer_miles: int,
    generator_hours: float,
    recorded_at: str,
    as_owner: bool = False,
) -> Dict[str, Any]:
    headers = world.owner_headers if as_owner else world.renter_headers
    return get_success_data(
        api.create_meter_reading(
            f.meter_reading_payload(
                booking_id, reading_type, odometer_miles, generator_hours, recorded_at
            ),
            headers,
        )
    )


def record_trip_photo(
    api,
    world: Marketplace,
    booking_id: str,
    phase: str,
    zone: str,
    damage_flagged: bool = False,
    as_owner: bool = False,
    image_ref: Optional[str] = None,
) -> Dict[str, Any]:
    headers = world.owner_headers if as_owner else world.renter_headers
    return get_success_data(
        api.create_trip_photo(
            f.trip_photo_payload(booking_id, phase, zone, damage_flagged, image_ref),
            headers,
        )
    )


def record_pre_trip_evidence(
    api,
    world: Marketplace,
    booking_id: str,
    zones: Sequence[str] = _TRIP_ZONES,
    odometer_miles: int = 42000,
    generator_hours: float = 120.0,
    recorded_at: str = "2026-08-29T15:00:00Z",
    image_prefix: str = "pre",
) -> None:
    """The pre-trip meter reading plus one clean photo per zone."""
    record_meter_reading(
        api,
        world,
        booking_id,
        "PRE_TRIP",
        odometer_miles,
        generator_hours,
        recorded_at,
        as_owner=True,
    )
    for zone in zones:
        record_trip_photo(
            api,
            world,
            booking_id,
            PhotoPhase.PRE_TRIP,
            zone,
            damage_flagged=False,
            as_owner=True,
            image_ref=f"s3://trip/{image_prefix}-{zone.lower()}.jpg",
        )


def record_post_trip_evidence(
    api,
    world: Marketplace,
    booking_id: str,
    zones: Sequence[str] = _TRIP_ZONES,
    damaged_zones: Sequence[str] = (Zone.EXTERIOR_REAR,),
    mid_reading: Optional[Tuple[int, float, str]] = (42260, 130.5, "2026-08-31T15:00:00Z"),
    post_reading: Tuple[int, float, str] = (42400, 132.0, "2026-09-02T11:00:00Z"),
    image_prefix: str = "post",
) -> None:
    """The mid- and post-trip readings plus one photo per requested zone."""
    if mid_reading is not None:
        record_meter_reading(
            api, world, booking_id, "MID_TRIP", mid_reading[0], mid_reading[1], mid_reading[2]
        )
    record_meter_reading(
        api, world, booking_id, "POST_TRIP", post_reading[0], post_reading[1], post_reading[2]
    )
    for zone in zones:
        record_trip_photo(
            api,
            world,
            booking_id,
            PhotoPhase.POST_TRIP,
            zone,
            damage_flagged=zone in damaged_zones,
            as_owner=False,
            image_ref=f"s3://trip/{image_prefix}-{zone.lower()}.jpg",
        )


def start_trip(api, world: Marketplace, booking_id: str) -> Dict[str, Any]:
    return get_success_data(api.start_booking(booking_id, world.owner_headers))


def return_trip(api, world: Marketplace, booking_id: str) -> Dict[str, Any]:
    return get_success_data(api.return_booking(booking_id, world.owner_headers))


def settle_booking(api, booking_id: str) -> Dict[str, Any]:
    return get_success_data(api.settle_booking(booking_id, PLATFORM_ADMIN_HEADERS))


def seed_in_trip_booking(api, world: Marketplace, **overrides: Any) -> Dict[str, Any]:
    """A CONFIRMED booking pushed through handover into IN_TRIP."""
    confirmed = seed_confirmed_booking(api, world, **overrides)
    record_pre_trip_evidence(api, world, confirmed["id"])
    started = start_trip(api, world, confirmed["id"])
    world.booking_version = started["version"]
    return started


def seed_returned_booking(
    api,
    world: Marketplace,
    post_zones: Sequence[str] = _TRIP_ZONES,
    damaged_zones: Sequence[str] = (Zone.EXTERIOR_REAR,),
    **overrides: Any,
) -> Dict[str, Any]:
    """A booking carried to RETURNED / RECONCILING with the canonical meters."""
    started = seed_in_trip_booking(api, world, **overrides)
    record_post_trip_evidence(
        api, world, started["id"], zones=post_zones, damaged_zones=damaged_zones
    )
    returned = return_trip(api, world, started["id"])
    world.booking_version = returned["version"]
    return returned


def seed_settled_booking(api, world: Marketplace, **overrides: Any) -> Dict[str, Any]:
    """A booking carried all the way to CLOSED / SETTLED with four ledger rows."""
    returned = seed_returned_booking(api, world, **overrides)
    settled = settle_booking(api, returned["id"])
    world.booking_version = settled["version"]
    return settled


# ===========================================================================
# Tier 4 - accumulation and threshold shortcuts
# ===========================================================================
def seed_renter_with_driving_history(
    api,
    checks: Sequence[Tuple[int, str]],
    towing_result: Optional[str] = QualificationResult.VERIFIED_BASIC,
    **renter_overrides: Any,
) -> Dict[str, Any]:
    """A renter whose driving-record checks are supplied as (points, checked_at).

    Checks are recorded in the order given, which is also the order that
    decides which one is newest.
    """
    renter = create_renter(api, **renter_overrides)
    for points, checked_at in checks:
        add_driving_record_check(
            api,
            renter["id"],
            violation_points=points,
            result=QualificationResult.MINOR if points else QualificationResult.CLEAR,
            checked_at=checked_at,
        )
    if towing_result is not None:
        add_towing_experience_check(api, renter["id"], result=towing_result)
    return renter


def seed_owner_at_penalty_points(
    api, owner_id: str, points: int, reason: str = "repeated host cancellations"
) -> Dict[str, Any]:
    """Drive an owner's penalty-point counter straight to a chosen total."""
    return adjust_owner_points(api, owner_id, points, reason)


def exhaust_claim_info_rounds(
    api, world: Marketplace, claim_id: str, rounds: int = 2
) -> None:
    """Consume the claim's information rounds, leaving it UNDER_REVIEW."""
    for _ in range(rounds):
        get_success_data(
            api.request_claim_info(claim_id, f.info_request_payload(), CLAIMS_ADJUSTER_HEADERS)
        )
        get_success_data(
            api.respond_to_claim_info(claim_id, f.info_response_payload(), world.owner_headers)
        )


# ===========================================================================
# Tier 5 - campgrounds, drop-offs, claims and terminal states
# ===========================================================================
def seed_campground(api, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_campground(f.campground_payload(**overrides), PLATFORM_ADMIN_HEADERS)
    )


def create_delivery_assignment(
    api,
    world: Marketplace,
    booking_id: str,
    campground_id: str,
    expected_booking_version: int,
    window_start: str = "2026-08-29T14:00:00Z",
    window_end: str = "2026-08-29T16:00:00Z",
    distance_miles: int = 40,
    setup_fee_cents: Optional[int] = 5000,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_delivery_assignment(
            f.delivery_assignment_payload(
                booking_id,
                campground_id,
                window_start,
                window_end,
                distance_miles,
                expected_booking_version,
                setup_fee_cents=setup_fee_cents,
                **overrides,
            ),
            world.owner_headers,
        )
    )


def seed_dropoff_booking(api, world: Marketplace, **overrides: Any) -> Dict[str, Any]:
    """A REQUESTED booking that asked for a campground drop-off."""
    overrides.setdefault("delivery_option", DeliveryOption.CAMPGROUND_DROPOFF)
    return seed_requested_booking(api, world, **overrides)


def seed_scheduled_dropoff(
    api,
    world: Marketplace,
    campground_id: Optional[str] = None,
    distance_miles: int = 40,
    setup_fee_cents: Optional[int] = 5000,
    window_start: str = "2026-08-29T14:00:00Z",
    window_end: str = "2026-08-29T16:00:00Z",
    **booking_overrides: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """A drop-off booking plus its first, slot-consuming SCHEDULED assignment."""
    if campground_id is None:
        campground_id = seed_campground(api)["id"]
    world.campground_id = campground_id
    booking = seed_dropoff_booking(api, world, **booking_overrides)
    assignment = create_delivery_assignment(
        api,
        world,
        booking["id"],
        campground_id,
        booking["version"],
        window_start=window_start,
        window_end=window_end,
        distance_miles=distance_miles,
        setup_fee_cents=setup_fee_cents,
    )
    world.assignment_id = assignment["id"]
    return booking, assignment


def file_damage_claim(
    api,
    world: Marketplace,
    booking_id: str,
    cause_code: str = CauseCode.COLLISION,
    damage_zone: str = Zone.EXTERIOR_REAR,
    claimed_amount_cents: int = 220000,
    description: str = "Rear cap cracked and tail light housing shattered.",
) -> Dict[str, Any]:
    claim = get_success_data(
        api.create_damage_claim(
            f.damage_claim_payload(
                booking_id, cause_code, damage_zone, claimed_amount_cents, description
            ),
            world.owner_headers,
        )
    )
    world.claim_id = claim["id"]
    return claim


def start_claim_review(api, claim_id: str) -> Dict[str, Any]:
    return get_success_data(api.start_claim_review(claim_id, CLAIMS_ADJUSTER_HEADERS))


def seed_claim_under_review(
    api,
    world: Marketplace,
    booking_id: str,
    **claim_overrides: Any,
) -> Dict[str, Any]:
    """A filed claim moved into UNDER_REVIEW by the adjuster."""
    claim = file_damage_claim(api, world, booking_id, **claim_overrides)
    return start_claim_review(api, claim["id"])


def seed_returned_booking_with_claim_under_review(
    api, world: Marketplace, **claim_overrides: Any
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """A RETURNED booking whose damage claim is already UNDER_REVIEW."""
    returned = seed_returned_booking(api, world)
    claim = seed_claim_under_review(api, world, returned["id"], **claim_overrides)
    return returned, claim


def collect_ledger_entries(api, booking_id: str) -> List[Dict[str, Any]]:
    """Every ledger row for a booking, read through the operator's view."""
    from prd_bench_local_runner.testing import validate_paginated

    response = api.list_ledger_entries(
        f.page_params(limit=100, booking_id=booking_id), PLATFORM_ADMIN_HEADERS
    )
    rows, _meta = validate_paginated(response)
    return rows
