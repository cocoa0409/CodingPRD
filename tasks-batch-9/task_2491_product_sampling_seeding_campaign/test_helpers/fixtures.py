"""State builders and pytest fixtures.

The builders are grouped in tiers.  Tier 1 pins the logical clock.  Tier 2
creates single rows.  Tier 3 gives one-call shortcuts through the campaign,
wave, shipment, review, syndication and diversion lifecycles.  Tier 4 assembles
the composite worlds that accumulation and threshold checks need.  Tier 5
carries a campaign to a terminal state.

Every builder returns the created or refreshed entity body so a test can chain
on real ids and real versions instead of guessing them.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import SamplingApiClient
from .constants import CANONICAL_SEGMENT_CODE, CLOCK_EPOCH
from .test_users import (
    campaign_manager_headers,
    fulfillment_ops_headers,
    make_panelist_headers,
    moderator_a_headers,
    moderator_b_headers,
    platform_admin_headers,
)


# ===========================================================================
# Tier 1 — logical clock
# ===========================================================================
def pin_clock(api: SamplingApiClient, to_iso8601: str = CLOCK_EPOCH) -> Dict[str, Any]:
    """Place the logical clock at an explicit instant.

    Repositioning the clock mutates no entity, so this is safe to call at any
    point in a setup chain.
    """
    return get_success_data(api.set_clock(platform_admin_headers(), to_iso8601))


def advance_clock(api: SamplingApiClient, to_iso8601: str) -> Dict[str, Any]:
    return pin_clock(api, to_iso8601)


# ===========================================================================
# Tier 2 — single-row creation and refresh
# ===========================================================================
def create_campaign(api: SamplingApiClient, **overrides: Any) -> Dict[str, Any]:
    payload = factories.campaign_payload(**overrides)
    return get_success_data(api.create_campaign(campaign_manager_headers(), **payload))


def get_campaign(api: SamplingApiClient, campaign_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_campaign(campaign_manager_headers(), campaign_id))


def get_cost_summary(api: SamplingApiClient, campaign_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_campaign_cost_summary(campaign_manager_headers(), campaign_id)
    )


def add_kit_line(api: SamplingApiClient, campaign_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = factories.kit_line_payload(campaign_id, **overrides)
    return get_success_data(api.create_kit_line(campaign_manager_headers(), **payload))


def get_kit_line(api: SamplingApiClient, kit_line_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_kit_line(campaign_manager_headers(), kit_line_id))


def receive_units(api: SamplingApiClient, kit_line_id: str, units: int) -> Dict[str, Any]:
    return get_success_data(
        api.record_kit_line_receipt(fulfillment_ops_headers(), kit_line_id, units)
    )


def write_off_units(
    api: SamplingApiClient, kit_line_id: str, units: int, reason: str
) -> Dict[str, Any]:
    return get_success_data(
        api.record_kit_line_write_off(fulfillment_ops_headers(), kit_line_id, units, reason)
    )


def retire_kit_line(api: SamplingApiClient, kit_line_id: str) -> Dict[str, Any]:
    return get_success_data(api.retire_kit_line(campaign_manager_headers(), kit_line_id))


def create_center(api: SamplingApiClient, **overrides: Any) -> Dict[str, Any]:
    payload = factories.fulfillment_center_payload(**overrides)
    return get_success_data(api.create_fulfillment_center(fulfillment_ops_headers(), **payload))


def get_center(api: SamplingApiClient, center_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_fulfillment_center(fulfillment_ops_headers(), center_id))


def create_wave(api: SamplingApiClient, center_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = factories.fulfillment_wave_payload(center_id, **overrides)
    return get_success_data(api.create_fulfillment_wave(fulfillment_ops_headers(), **payload))


def get_wave(api: SamplingApiClient, wave_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_fulfillment_wave(fulfillment_ops_headers(), wave_id))


def create_panelist(api: SamplingApiClient, **overrides: Any) -> Dict[str, Any]:
    """Register a panelist.

    Panel sign-up is shared with PlatformAdmin, so the admin identity is used
    here; the anonymous, header-free form of the call is exercised only by the
    tests that are about the authentication rung itself.
    """
    payload = factories.panelist_payload(**overrides)
    return get_success_data(api.create_panelist(platform_admin_headers(), **payload))


def get_panelist(api: SamplingApiClient, panelist_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_panelist(moderator_a_headers(), panelist_id))


def rescore_panelist(
    api: SamplingApiClient, panelist_id: str, variant: str
) -> Dict[str, Any]:
    return get_success_data(
        api.rescore_panelist_risk(moderator_a_headers(), panelist_id, variant)
    )


def create_enrollment(
    api: SamplingApiClient,
    campaign_id: str,
    panelist_id: str,
    screening_answers: Optional[Dict[str, Any]] = None,
    as_panelist: bool = False,
) -> Dict[str, Any]:
    """Enroll a panelist.

    Enrollment creation is open to both the panelist themselves and a campaign
    manager; the manager identity is the default so that setup never trips the
    panelist ownership check, and ``as_panelist`` switches to the owner's own
    identity when that path is what a test is about.
    """
    answers = screening_answers if screening_answers is not None else factories.screening_answers()
    headers = (
        make_panelist_headers(panelist_id) if as_panelist else campaign_manager_headers()
    )
    return get_success_data(
        api.create_enrollment(headers, campaign_id, panelist_id, answers)
    )


def get_enrollment(api: SamplingApiClient, enrollment_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_enrollment(campaign_manager_headers(), enrollment_id))


def screen_enrollment(api: SamplingApiClient, enrollment_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.screen_enrollment(campaign_manager_headers(), enrollment_id)
    )


def resubmit_screening(
    api: SamplingApiClient,
    enrollment_id: str,
    panelist_id: str,
    screening_answers: Dict[str, Any],
) -> Dict[str, Any]:
    return get_success_data(
        api.resubmit_screening(
            make_panelist_headers(panelist_id), enrollment_id, screening_answers
        )
    )


def create_retailer(api: SamplingApiClient, **overrides: Any) -> Dict[str, Any]:
    payload = factories.retailer_payload(**overrides)
    return get_success_data(api.create_retailer(campaign_manager_headers(), **payload))


def get_retailer(api: SamplingApiClient, retailer_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_retailer(campaign_manager_headers(), retailer_id))


def create_purchase_match(
    api: SamplingApiClient, enrollment_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload = factories.purchase_match_payload(enrollment_id, **overrides)
    return get_success_data(api.create_purchase_match(platform_admin_headers(), **payload))


# ===========================================================================
# Tier 3 — lifecycle shortcuts
# ===========================================================================
def open_screening(api: SamplingApiClient, campaign_id: str) -> Dict[str, Any]:
    return get_success_data(api.open_screening(campaign_manager_headers(), campaign_id))


def activate_sampling(api: SamplingApiClient, campaign_id: str) -> Dict[str, Any]:
    return get_success_data(api.activate_sampling(campaign_manager_headers(), campaign_id))


def suspend_campaign(api: SamplingApiClient, campaign_id: str) -> Dict[str, Any]:
    return get_success_data(api.suspend_campaign(moderator_a_headers(), campaign_id))


def resume_campaign(api: SamplingApiClient, campaign_id: str) -> Dict[str, Any]:
    return get_success_data(api.resume_campaign(moderator_a_headers(), campaign_id))


def open_review_window(api: SamplingApiClient, campaign_id: str) -> Dict[str, Any]:
    return get_success_data(api.open_review_window(campaign_manager_headers(), campaign_id))


def close_campaign(api: SamplingApiClient, campaign_id: str) -> Dict[str, Any]:
    return get_success_data(api.close_campaign(campaign_manager_headers(), campaign_id))


def allocate_shipment(
    api: SamplingApiClient,
    enrollment_id: str,
    wave_id: str,
    surcharge_cents: Optional[int] = None,
    supersedes_shipment_id: Optional[str] = None,
    expected_enrollment_version: Optional[int] = None,
) -> Dict[str, Any]:
    """Allocate a sample shipment, reading the enrollment version if not given."""
    version = expected_enrollment_version
    if version is None:
        version = get_enrollment(api, enrollment_id)["version"]
    return get_success_data(
        api.create_sample_shipment(
            fulfillment_ops_headers(),
            enrollment_id=enrollment_id,
            fulfillment_wave_id=wave_id,
            expected_enrollment_version=version,
            surcharge_cents=surcharge_cents,
            supersedes_shipment_id=supersedes_shipment_id,
        )
    )


def get_shipment(api: SamplingApiClient, shipment_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_sample_shipment(fulfillment_ops_headers(), shipment_id))


def lock_wave(api: SamplingApiClient, wave_id: str) -> Dict[str, Any]:
    return get_success_data(api.lock_fulfillment_wave(fulfillment_ops_headers(), wave_id))


def release_wave(api: SamplingApiClient, wave_id: str) -> Dict[str, Any]:
    return get_success_data(api.release_fulfillment_wave(fulfillment_ops_headers(), wave_id))


def cancel_shipment(api: SamplingApiClient, shipment_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.cancel_sample_shipment(fulfillment_ops_headers(), shipment_id)
    )


def deliver_shipment(api: SamplingApiClient, shipment_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.deliver_sample_shipment(fulfillment_ops_headers(), shipment_id)
    )


def report_shipment_lost(api: SamplingApiClient, shipment_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.report_sample_shipment_lost(fulfillment_ops_headers(), shipment_id)
    )


def ship_and_deliver(api: SamplingApiClient, wave_id: str, shipment_id: str) -> Dict[str, Any]:
    """Lock the wave, release it so the shipment ships, then mark it delivered."""
    lock_wave(api, wave_id)
    release_wave(api, wave_id)
    return deliver_shipment(api, shipment_id)


def create_review(
    api: SamplingApiClient, enrollment_id: str, panelist_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload = factories.review_payload(enrollment_id, **overrides)
    return get_success_data(
        api.create_review_submission(make_panelist_headers(panelist_id), **payload)
    )


def get_review(api: SamplingApiClient, review_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_review_submission(moderator_a_headers(), review_id))


def submit_review(api: SamplingApiClient, review_id: str, panelist_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.submit_review(make_panelist_headers(panelist_id), review_id)
    )


def revise_review(
    api: SamplingApiClient, review_id: str, panelist_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload = factories.review_payload("ignored", **overrides)
    payload.pop("enrollment_id", None)
    return get_success_data(
        api.revise_review(make_panelist_headers(panelist_id), review_id, **payload)
    )


def moderate_review(
    api: SamplingApiClient,
    review_id: str,
    decision: str,
    headers: Optional[Dict[str, str]] = None,
    moderator_note: Optional[str] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.moderate_review(
            headers if headers is not None else moderator_a_headers(),
            review_id,
            decision,
            moderator_note,
        )
    )


def create_syndication(
    api: SamplingApiClient, review_id: str, retailer_id: str
) -> Dict[str, Any]:
    return get_success_data(
        api.create_syndication_record(campaign_manager_headers(), review_id, retailer_id)
    )


def get_syndication(api: SamplingApiClient, record_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_syndication_record(campaign_manager_headers(), record_id)
    )


def dispatch_syndication(api: SamplingApiClient, record_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.dispatch_syndication_record(fulfillment_ops_headers(), record_id)
    )


def open_diversion_case(
    api: SamplingApiClient,
    panelist_id: str,
    shipment_id: str,
    signal_type: str = "RESALE_LISTING",
    evidence_note: str = "Listing found on a resale marketplace",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_diversion_case(
            headers if headers is not None else moderator_a_headers(),
            panelist_id,
            shipment_id,
            signal_type,
            evidence_note,
        )
    )


def get_case(api: SamplingApiClient, case_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_diversion_case(moderator_a_headers(), case_id))


def investigate_case(
    api: SamplingApiClient, case_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api.investigate_diversion_case(
            headers if headers is not None else moderator_a_headers(), case_id
        )
    )


def substantiate_case(
    api: SamplingApiClient, case_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api.substantiate_diversion_case(
            headers if headers is not None else moderator_b_headers(), case_id
        )
    )


def dismiss_case(
    api: SamplingApiClient, case_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api.dismiss_diversion_case(
            headers if headers is not None else moderator_b_headers(), case_id
        )
    )


def reopen_case(
    api: SamplingApiClient, case_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api.reopen_diversion_case(
            headers if headers is not None else moderator_a_headers(), case_id
        )
    )


# ===========================================================================
# Tier 4 — composite worlds
# ===========================================================================
@dataclass
class KitSpec:
    """One kit line plus the units received against it."""

    component_sku: str
    component_role: str
    unit_cost_cents: int
    quantity_per_kit: int
    component_discount_pct: float
    receipt_units: int = 0


CANONICAL_KIT_SPECS: Sequence[KitSpec] = (
    KitSpec("HERO-1", "HERO_PRODUCT", 1417, 1, 0.8, 10),
    KitSpec("ACC-2", "ACCESSORY", 388, 2, 0.85, 20),
    KitSpec("INS-3", "INSERT_CARD", 554, 1, 0.9, 10),
)


def build_kit(
    api: SamplingApiClient,
    campaign_id: str,
    specs: Sequence[KitSpec] = CANONICAL_KIT_SPECS,
) -> List[Dict[str, Any]]:
    """Create each declared kit line and receive its stock."""
    lines: List[Dict[str, Any]] = []
    for spec in specs:
        line = add_kit_line(
            api,
            campaign_id,
            component_sku=spec.component_sku,
            component_role=spec.component_role,
            unit_cost_cents=spec.unit_cost_cents,
            quantity_per_kit=spec.quantity_per_kit,
            component_discount_pct=spec.component_discount_pct,
        )
        if spec.receipt_units:
            line = receive_units(api, line["id"], spec.receipt_units)
        lines.append(line)
    return lines


@dataclass
class ScreeningWorld:
    """A campaign whose kit is stocked and whose screening window is open."""

    campaign: Dict[str, Any]
    kit_lines: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def campaign_id(self) -> str:
        return self.campaign["id"]

    def kit_line_id(self, index: int) -> str:
        return self.kit_lines[index]["id"]


def screening_open_campaign(
    api: SamplingApiClient,
    kit_specs: Sequence[KitSpec] = CANONICAL_KIT_SPECS,
    **campaign_overrides: Any,
) -> ScreeningWorld:
    campaign = create_campaign(api, **campaign_overrides)
    kit_lines = build_kit(api, campaign["id"], kit_specs)
    campaign = open_screening(api, campaign["id"])
    refreshed = [get_kit_line(api, line["id"]) for line in kit_lines]
    return ScreeningWorld(campaign=campaign, kit_lines=refreshed)


@dataclass
class SamplingWorld:
    """A campaign carried to SAMPLING_ACTIVE with panelists already screened.

    ``enrollments`` and ``panelists`` are index-aligned, so ``panelists[0]`` is
    the panelist behind ``enrollments[0]`` and therefore the identity that must
    act on that enrollment's reviews.
    """

    campaign: Dict[str, Any]
    kit_lines: List[Dict[str, Any]] = field(default_factory=list)
    center: Optional[Dict[str, Any]] = None
    waves: List[Dict[str, Any]] = field(default_factory=list)
    panelists: List[Dict[str, Any]] = field(default_factory=list)
    enrollments: List[Dict[str, Any]] = field(default_factory=list)
    shipments: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def campaign_id(self) -> str:
        return self.campaign["id"]

    @property
    def center_id(self) -> str:
        assert self.center is not None
        return self.center["id"]

    @property
    def wave(self) -> Dict[str, Any]:
        return self.waves[0]

    @property
    def wave_id(self) -> str:
        return self.waves[0]["id"]

    def kit_line_id(self, index: int) -> str:
        return self.kit_lines[index]["id"]

    def panelist_id(self, index: int = 0) -> str:
        return self.panelists[index]["id"]

    def enrollment_id(self, index: int = 0) -> str:
        return self.enrollments[index]["id"]

    def shipment_id(self, index: int = 0) -> str:
        return self.shipments[index]["id"]

    def panelist_headers(self, index: int = 0) -> Dict[str, str]:
        return make_panelist_headers(self.panelist_id(index))


def sampling_active_campaign(
    api: SamplingApiClient,
    panelist_count: int = 1,
    kit_specs: Sequence[KitSpec] = CANONICAL_KIT_SPECS,
    center_overrides: Optional[Dict[str, Any]] = None,
    wave_overrides: Optional[Dict[str, Any]] = None,
    with_wave: bool = True,
    **campaign_overrides: Any,
) -> SamplingWorld:
    """Campaign in SAMPLING_ACTIVE with ``panelist_count`` screened enrollments.

    The campaign only reaches SAMPLING_ACTIVE once at least one enrollment has
    passed screening, so every panelist here is created in the campaign's own
    target segment and screened before the activation call.
    """
    world_campaign = create_campaign(api, **campaign_overrides)
    campaign_id = world_campaign["id"]
    segment = world_campaign["target_segment_codes"][0]

    kit_lines = build_kit(api, campaign_id, kit_specs)
    open_screening(api, campaign_id)

    panelists: List[Dict[str, Any]] = []
    enrollments: List[Dict[str, Any]] = []
    for _ in range(panelist_count):
        panelist = create_panelist(api, segment_code=segment)
        enrollment = create_enrollment(api, campaign_id, panelist["id"])
        enrollment = screen_enrollment(api, enrollment["id"])
        panelists.append(panelist)
        enrollments.append(enrollment)

    campaign = activate_sampling(api, campaign_id)

    center = create_center(api, **(center_overrides or {}))
    waves: List[Dict[str, Any]] = []
    if with_wave:
        waves.append(create_wave(api, center["id"], **(wave_overrides or {})))

    return SamplingWorld(
        campaign=campaign,
        kit_lines=[get_kit_line(api, line["id"]) for line in kit_lines],
        center=center,
        waves=waves,
        panelists=panelists,
        enrollments=enrollments,
    )


def allocated_sample_world(
    api: SamplingApiClient,
    panelist_count: int = 1,
    surcharges: Optional[Sequence[Optional[int]]] = None,
    **kwargs: Any,
) -> SamplingWorld:
    """A SAMPLING_ACTIVE campaign with one ALLOCATED shipment per enrollment."""
    world = sampling_active_campaign(api, panelist_count=panelist_count, **kwargs)
    for index in range(len(world.enrollments)):
        surcharge = None
        if surcharges is not None and index < len(surcharges):
            surcharge = surcharges[index]
        world.shipments.append(
            allocate_shipment(
                api, world.enrollment_id(index), world.wave_id, surcharge_cents=surcharge
            )
        )
    return world


def delivered_sample_world(
    api: SamplingApiClient,
    panelist_count: int = 1,
    surcharges: Optional[Sequence[Optional[int]]] = None,
    **kwargs: Any,
) -> SamplingWorld:
    """Every allocated shipment shipped through the wave and then delivered.

    Delivery is what puts the enrollment's obligation axis into ``REVIEW_DUE``,
    which is the precondition for review collection.
    """
    world = allocated_sample_world(
        api, panelist_count=panelist_count, surcharges=surcharges, **kwargs
    )
    lock_wave(api, world.wave_id)
    release_wave(api, world.wave_id)
    delivered: List[Dict[str, Any]] = []
    for shipment in world.shipments:
        delivered.append(deliver_shipment(api, shipment["id"]))
    world.shipments = delivered
    world.enrollments = [
        get_enrollment(api, enrollment["id"]) for enrollment in world.enrollments
    ]
    world.kit_lines = [get_kit_line(api, line["id"]) for line in world.kit_lines]
    world.campaign = get_campaign(api, world.campaign_id)
    return world


def submitted_review_world(
    api: SamplingApiClient, index: int = 0, review_overrides: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """A delivered sample whose panelist has drafted and submitted a review."""
    world = delivered_sample_world(api, **kwargs)
    review = create_review(
        api,
        world.enrollment_id(index),
        world.panelist_id(index),
        **(review_overrides or {}),
    )
    review = submit_review(api, review["id"], world.panelist_id(index))
    return {"world": world, "review": review}


def approved_review_world(
    api: SamplingApiClient,
    index: int = 0,
    review_overrides: Optional[Dict[str, Any]] = None,
    retailer_overrides: Optional[Dict[str, Any]] = None,
    with_retailer: bool = True,
    **kwargs: Any,
) -> Dict[str, Any]:
    """A submitted review approved by one moderator.

    When ``with_retailer`` is set the retailer is created first and registered
    on the campaign, because a syndication target must already be listed on the
    campaign for dispatch to be possible.
    """
    retailer = None
    if with_retailer:
        retailer = create_retailer(api, **(retailer_overrides or {}))
        kwargs["syndication_retailer_ids"] = [retailer["id"]]

    bundle = submitted_review_world(
        api, index=index, review_overrides=review_overrides, **kwargs
    )
    review = moderate_review(
        api,
        bundle["review"]["id"],
        "APPROVE",
        headers=moderator_a_headers(),
        moderator_note="meets the disclosure policy",
    )
    bundle["review"] = review
    bundle["retailer"] = retailer
    bundle["world"].campaign = get_campaign(api, bundle["world"].campaign_id)
    return bundle


def syndicated_review_world(
    api: SamplingApiClient, **kwargs: Any
) -> Dict[str, Any]:
    """An approved review queued to a retailer and dispatched to its feed."""
    bundle = approved_review_world(api, **kwargs)
    record = create_syndication(api, bundle["review"]["id"], bundle["retailer"]["id"])
    record = dispatch_syndication(api, record["id"])
    bundle["syndication"] = record
    bundle["world"].campaign = get_campaign(api, bundle["world"].campaign_id)
    return bundle


def investigating_case_world(
    api: SamplingApiClient,
    signal_type: str = "RESALE_LISTING",
    evidence_note: str = "Listing found on a resale marketplace",
    **kwargs: Any,
) -> Dict[str, Any]:
    """A delivered sample with an open diversion case moved to INVESTIGATING.

    The case is opened and moved by the same moderator, leaving the second
    moderator free to substantiate it without colliding with the rule that the
    opener may not also substantiate.
    """
    bundle = syndicated_review_world(api, **kwargs)
    world: SamplingWorld = bundle["world"]
    case = open_diversion_case(
        api,
        world.panelist_id(0),
        world.shipment_id(0),
        signal_type=signal_type,
        evidence_note=evidence_note,
        headers=moderator_a_headers(),
    )
    case = investigate_case(api, case["id"], headers=moderator_a_headers())
    bundle["case"] = case
    return bundle


def address_cluster_panelists(
    api: SamplingApiClient,
    count: int,
    address_hash: str = "H-CLUSTER",
    account_opened_at: str = "2026-07-25T00:00:00Z",
    segment_code: str = CANONICAL_SEGMENT_CODE,
) -> List[Dict[str, Any]]:
    """``count`` panelists that all share one address hash.

    A shared address is what drives the address-cluster component of the fraud
    risk score, and the audit variant multiplies that component.
    """
    return [
        create_panelist(
            api,
            address_hash=address_hash,
            account_opened_at=account_opened_at,
            segment_code=segment_code,
        )
        for _ in range(count)
    ]


# ===========================================================================
# Tier 5 — terminal states
# ===========================================================================
def review_window_campaign(api: SamplingApiClient, **kwargs: Any) -> SamplingWorld:
    """A campaign advanced from SAMPLING_ACTIVE into REVIEW_WINDOW."""
    world = delivered_sample_world(api, **kwargs)
    world.campaign = open_review_window(api, world.campaign_id)
    return world


def closed_campaign(api: SamplingApiClient, **kwargs: Any) -> SamplingWorld:
    """A campaign carried all the way to CLOSED, its terminal state."""
    world = review_window_campaign(api, **kwargs)
    world.campaign = close_campaign(api, world.campaign_id)
    return world


def frozen_posture_world(api: SamplingApiClient, **kwargs: Any) -> Dict[str, Any]:
    """A campaign whose posture has been driven to FROZEN by substantiation.

    Substantiating the only delivered sample's diversion case gives a
    substantiated rate of one out of one, which clears the frozen rate
    threshold outright.
    """
    bundle = investigating_case_world(api, **kwargs)
    bundle["case"] = substantiate_case(
        api, bundle["case"]["id"], headers=moderator_b_headers()
    )
    world: SamplingWorld = bundle["world"]
    world.campaign = get_campaign(api, world.campaign_id)
    return bundle
