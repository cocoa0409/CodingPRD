"""Composite setup helpers for the Studio Operations API.

The harness restarts the server before every test, so each test starts against
an empty database and every prerequisite row has to be created through the
public endpoints. These helpers encapsulate the long, repeatedly-needed setup
chains — reference data, a style whose sample is on the rack, a locked session,
a shooting session, an ingested asset, a submitted retouch task — so that
individual tests only express the step under examination.

Setup calls use the lenient `get_success_data` validator: a setup step that
fails should surface as a clear setup error, not as a confusing assertion about
the behaviour under test.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .test_users import (
    ADMIN,
    CONTENT_OPS,
    COORDINATOR,
    PRODUCER,
    QC_REVIEWER,
    make_photographer_headers,
    make_retoucher_headers,
)


# ─── Primitive single-call wrappers ────────────────────────────────────────

def set_clock(api: ApiClient, current_utc: str) -> Dict[str, Any]:
    """Move the logical studio clock (§2.4)."""
    return get_success_data(api.set_clock(f.clock_payload(current_utc), ADMIN))


def create_vendor(api: ApiClient, **kw: Any) -> Dict[str, Any]:
    return get_success_data(api.create_vendor(f.vendor_payload(**kw), ADMIN))


def create_asset_profile(api: ApiClient, **kw: Any) -> Dict[str, Any]:
    return get_success_data(api.create_asset_profile(f.asset_profile_payload(**kw), ADMIN))


def create_station(api: ApiClient, **kw: Any) -> Dict[str, Any]:
    return get_success_data(api.create_station(f.station_payload(**kw), ADMIN))


def create_talent(api: ApiClient, **kw: Any) -> Dict[str, Any]:
    return get_success_data(api.create_talent_profile(f.talent_payload(**kw), ADMIN))


def create_photographer(api: ApiClient, **kw: Any) -> Dict[str, Any]:
    return get_success_data(api.create_talent_profile(f.photographer_payload(**kw), ADMIN))


def create_retoucher(api: ApiClient, **kw: Any) -> Dict[str, Any]:
    return get_success_data(api.create_talent_profile(f.retoucher_payload(**kw), ADMIN))


def create_model(api: ApiClient, **kw: Any) -> Dict[str, Any]:
    return get_success_data(api.create_talent_profile(f.model_payload(**kw), ADMIN))


def create_stylist(api: ApiClient, **kw: Any) -> Dict[str, Any]:
    return get_success_data(api.create_talent_profile(f.stylist_payload(**kw), ADMIN))


def create_provider(api: ApiClient, **kw: Any) -> Dict[str, Any]:
    return get_success_data(api.create_studio_provider(f.provider_payload(**kw), ADMIN))


def create_outsourced_provider(api: ApiClient, **kw: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_studio_provider(f.outsourced_provider_payload(**kw), ADMIN)
    )


def create_style(
    api: ApiClient, vendor_id: str, asset_profile_id: str, **kw: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_style(f.style_payload(vendor_id, asset_profile_id, **kw), ADMIN)
    )


def create_sample(api: ApiClient, vendor_id: str, **kw: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_sample(f.sample_payload(vendor_id, **kw), COORDINATOR)
    )


def receive_sample(api: ApiClient, sample_id: str) -> Dict[str, Any]:
    return get_success_data(api.receive_sample(sample_id, COORDINATOR))


def match_sample(api: ApiClient, sample_id: str, style_id: str, **kw: Any) -> Dict[str, Any]:
    return get_success_data(
        api.match_sample(sample_id, f.match_payload(style_id, **kw), COORDINATOR)
    )


def custody_move(api: ApiClient, sample_id: str, to_state: str) -> Dict[str, Any]:
    return get_success_data(
        api.custody_move_sample(sample_id, f.custody_move_payload(to_state), COORDINATOR)
    )


def create_release(api: ApiClient, talent_id: str, **kw: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_release_document(f.release_payload(talent_id, **kw), ADMIN)
    )


def sign_release(api: ApiClient, release_id: str) -> Dict[str, Any]:
    return get_success_data(api.sign_release_document(release_id, ADMIN))


def create_session(
    api: ApiClient, station_id: str, provider_id: str, **kw: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_shoot_session(f.session_payload(station_id, provider_id, **kw), PRODUCER)
    )


def style_version(api: ApiClient, style_id: str) -> int:
    """Read the style's current version, as a producer would before a create."""
    return get_success_data(api.get_style(style_id, PRODUCER))["version"]


def session_version(api: ApiClient, session_id: str) -> int:
    """Read the session's current version, as a producer would before a create."""
    return get_success_data(api.get_shoot_session(session_id, PRODUCER))["version"]


def create_shot_item(api: ApiClient, style_id: str, **kw: Any) -> Dict[str, Any]:
    """Create a shot-list item, reading the style's current version first."""
    version = kw.pop("expected_style_version", None)
    if version is None:
        version = style_version(api, style_id)
    return get_success_data(
        api.create_shot_list_item(f.shot_item_payload(style_id, version, **kw), PRODUCER)
    )


def assign_item(api: ApiClient, item_id: str, session_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.assign_shot_list_item(item_id, {"session_id": session_id}, PRODUCER)
    )


def waive_item(api: ApiClient, item_id: str, **kw: Any) -> Dict[str, Any]:
    return get_success_data(api.waive_shot_list_item(item_id, PRODUCER, kw or None))


def create_booking(
    api: ApiClient, session_id: str, talent_id: str, **kw: Any
) -> Dict[str, Any]:
    """Hold a person on a session, reading the session's current version first."""
    version = kw.pop("expected_session_version", None)
    if version is None:
        version = session_version(api, session_id)
    return get_success_data(
        api.create_talent_booking(
            f.booking_payload(session_id, talent_id, version, **kw), PRODUCER
        )
    )


def confirm_booking(api: ApiClient, booking_id: str) -> Dict[str, Any]:
    return get_success_data(api.confirm_booking(booking_id, PRODUCER))


def lock_session(api: ApiClient, session_id: str) -> Dict[str, Any]:
    return get_success_data(api.lock_session(session_id, PRODUCER))


def start_session(api: ApiClient, session_id: str, photographer_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.start_session(session_id, make_photographer_headers(photographer_id))
    )


def measure_colour(
    api: ApiClient, session_id: str, photographer_id: str, patch_deltas: List[float]
) -> Dict[str, Any]:
    return get_success_data(
        api.submit_color_measurement(
            session_id,
            f.color_measurement_payload(patch_deltas),
            make_photographer_headers(photographer_id),
        )
    )


def ingest_asset(
    api: ApiClient, item_id: str, photographer_id: str, file_name: str, **kw: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_asset(
            f.asset_payload(item_id, file_name, **kw),
            make_photographer_headers(photographer_id),
        )
    )


def wrap_session(api: ApiClient, session_id: str, photographer_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.wrap_session(session_id, make_photographer_headers(photographer_id))
    )


def create_retouch_task(api: ApiClient, asset_id: str, provider_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.create_retouch_task(f.retouch_task_payload(asset_id, provider_id), CONTENT_OPS)
    )


def claim_next(api: ApiClient, retoucher_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.claim_next_retouch_task(make_retoucher_headers(retoucher_id))
    )


def submit_task(api: ApiClient, task_id: str, retoucher_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.submit_retouch_task(task_id, make_retoucher_headers(retoucher_id))
    )


def qc_approve(api: ApiClient, task_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.qc_decision(task_id, f.qc_decision_payload("APPROVE"), QC_REVIEWER)
    )


def qc_reject(api: ApiClient, task_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.qc_decision(task_id, f.qc_decision_payload("REJECT"), QC_REVIEWER)
    )


def deliver_asset(api: ApiClient, asset_id: str) -> Dict[str, Any]:
    return get_success_data(api.deliver_asset(asset_id, CONTENT_OPS))


# ─── Composite world builders ──────────────────────────────────────────────

class StudioWorld:
    """A bag of rows created during setup, addressed by attribute.

    Every attribute holds the full resource payload as the API returned it, so a
    test can read `world.style["version"]` without another round trip. The `_id`
    convenience properties exist because identifiers are what most calls need.
    """

    def __init__(self, api: ApiClient) -> None:
        self.api = api
        self.vendor: Dict[str, Any] = {}
        self.profile: Dict[str, Any] = {}
        self.station: Dict[str, Any] = {}
        self.provider: Dict[str, Any] = {}
        self.outsourced: Optional[Dict[str, Any]] = None
        self.photographer: Dict[str, Any] = {}
        self.retoucher: Dict[str, Any] = {}
        self.model: Optional[Dict[str, Any]] = None
        self.style: Dict[str, Any] = {}
        self.sample: Dict[str, Any] = {}
        self.session: Dict[str, Any] = {}
        self.items: List[Dict[str, Any]] = []
        self.bookings: List[Dict[str, Any]] = []
        self.assets: List[Dict[str, Any]] = []
        self.tasks: List[Dict[str, Any]] = []

    # Identifier shorthands
    @property
    def vendor_id(self) -> str:
        return self.vendor["id"]

    @property
    def profile_id(self) -> str:
        return self.profile["id"]

    @property
    def station_id(self) -> str:
        return self.station["id"]

    @property
    def provider_id(self) -> str:
        return self.provider["id"]

    @property
    def photographer_id(self) -> str:
        return self.photographer["id"]

    @property
    def retoucher_id(self) -> str:
        return self.retoucher["id"]

    @property
    def style_id(self) -> str:
        return self.style["id"]

    @property
    def sample_id(self) -> str:
        return self.sample["id"]

    @property
    def session_id(self) -> str:
        return self.session["id"]

    @property
    def item(self) -> Dict[str, Any]:
        return self.items[0]

    @property
    def item_id(self) -> str:
        return self.items[0]["id"]

    @property
    def asset(self) -> Dict[str, Any]:
        return self.assets[0]

    @property
    def asset_id(self) -> str:
        return self.assets[0]["id"]

    @property
    def task(self) -> Dict[str, Any]:
        return self.tasks[0]

    @property
    def task_id(self) -> str:
        return self.tasks[0]["id"]

    @property
    def booking(self) -> Dict[str, Any]:
        return self.bookings[0]

    @property
    def booking_id(self) -> str:
        return self.bookings[0]["id"]

    # Fresh reads
    def read_style(self) -> Dict[str, Any]:
        return get_success_data(self.api.get_style(self.style_id, PRODUCER))

    def read_sample(self) -> Dict[str, Any]:
        return get_success_data(self.api.get_sample(self.sample_id, COORDINATOR))

    def read_vendor(self) -> Dict[str, Any]:
        return get_success_data(self.api.get_vendor(self.vendor_id, ADMIN))

    def read_station(self) -> Dict[str, Any]:
        return get_success_data(self.api.get_station(self.station_id, ADMIN))

    def read_session(self) -> Dict[str, Any]:
        return get_success_data(self.api.get_shoot_session(self.session_id, PRODUCER))

    def read_item(self, index: int = 0) -> Dict[str, Any]:
        return get_success_data(
            self.api.get_shot_list_item(self.items[index]["id"], PRODUCER)
        )

    def read_asset(self, index: int = 0) -> Dict[str, Any]:
        return get_success_data(self.api.get_asset(self.assets[index]["id"], CONTENT_OPS))

    def read_task(self, index: int = 0) -> Dict[str, Any]:
        return get_success_data(
            self.api.get_retouch_task(self.tasks[index]["id"], CONTENT_OPS)
        )

    def read_booking(self, index: int = 0) -> Dict[str, Any]:
        return get_success_data(
            self.api.get_talent_booking(self.bookings[index]["id"], PRODUCER)
        )

    def read_talent(self, talent_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_talent_profile(talent_id, ADMIN))

    def read_provider(self, provider_id: Optional[str] = None) -> Dict[str, Any]:
        return get_success_data(
            self.api.get_studio_provider(provider_id or self.provider_id, ADMIN)
        )


def build_reference_data(
    api: ApiClient,
    clock: Optional[str] = "2026-08-03T08:00:00Z",
    station_type: str = "MODEL",
    station_code: str = "MODEL-1",
    station_kw: Optional[Dict[str, Any]] = None,
    profile_kw: Optional[Dict[str, Any]] = None,
    vendor_kw: Optional[Dict[str, Any]] = None,
    provider_kw: Optional[Dict[str, Any]] = None,
    with_outsourced: bool = False,
    outsourced_kw: Optional[Dict[str, Any]] = None,
    with_model: bool = False,
) -> StudioWorld:
    """Stand up the five kinds of reference record plus the studio's own crew.

    Mirrors the order of §3.1: vendor, asset profile, station, talent, provider.
    """
    world = StudioWorld(api)
    if clock is not None:
        set_clock(api, clock)
    world.vendor = create_vendor(api, **(vendor_kw or {}))
    world.profile = create_asset_profile(api, **(profile_kw or {}))
    world.station = create_station(
        api, station_code=station_code, station_type=station_type, **(station_kw or {})
    )
    world.provider = create_provider(api, **(provider_kw or {}))
    if with_outsourced:
        world.outsourced = create_outsourced_provider(api, **(outsourced_kw or {}))
    world.photographer = create_photographer(api)
    world.retoucher = create_retoucher(api)
    if with_model:
        world.model = create_model(api)
    return world


def build_style_on_the_rack(
    api: ApiClient,
    world: StudioWorld,
    style_number: str = "TOP1001",
    barcode: str = "SMP-1001",
    style_kw: Optional[Dict[str, Any]] = None,
) -> StudioWorld:
    """Register a style and walk its sample all the way to the studio rack.

    Pre-advise, receive, match cleanly, then `RECEIVED -> IN_STUDIO`, which is
    the move that advances the style from `NOT_STARTED` to `SAMPLE_READY`.
    """
    world.style = create_style(
        api,
        world.vendor_id,
        world.profile_id,
        style_number=style_number,
        **(style_kw or {}),
    )
    world.sample = create_sample(
        api, world.vendor_id, barcode=barcode, declared_style_number=style_number
    )
    receive_sample(api, world.sample_id)
    match_sample(api, world.sample_id, world.style_id)
    world.sample = custody_move(api, world.sample_id, "IN_STUDIO")
    return world


def build_planned_session(
    api: ApiClient,
    world: StudioWorld,
    item_specs: Optional[List[Dict[str, Any]]] = None,
    session_kw: Optional[Dict[str, Any]] = None,
    with_photographer_booking: bool = True,
    booking_kw: Optional[Dict[str, Any]] = None,
) -> StudioWorld:
    """Define the shot list, book the interval, assign the items, crew the floor.

    Leaves the session `BOOKED` with a `CONFIRMED` photographer booking, which is
    the state every on-set action needs before the call sheet is frozen.
    """
    specs = item_specs if item_specs is not None else [
        {"asset_kind": "ON_MODEL", "angle_code": "FRONT"}
    ]
    for spec in specs:
        world.items.append(create_shot_item(api, world.style_id, **spec))
    world.session = create_session(
        api, world.station_id, world.provider_id, **(session_kw or {})
    )
    for item in world.items:
        assign_item(api, item["id"], world.session_id)
    if with_photographer_booking:
        booking = create_booking(
            api, world.session_id, world.photographer_id, **(booking_kw or {})
        )
        confirm_booking(api, booking["id"])
        world.bookings.append(booking)
    return world


def build_shooting_session(
    api: ApiClient,
    world: StudioWorld,
    start_clock: str = "2026-08-03T09:00:00Z",
) -> StudioWorld:
    """Freeze the call sheet, move the clock to the call time and start shooting."""
    lock_session(api, world.session_id)
    set_clock(api, start_clock)
    world.session = start_session(api, world.session_id, world.photographer_id)
    return world


def build_ingested_asset(
    api: ApiClient,
    world: StudioWorld,
    item_index: int = 0,
    sequence_number: int = 1,
    metadata_tags: Optional[Dict[str, Any]] = None,
) -> StudioWorld:
    """Ingest one capture against an assigned item, named to the profile pattern."""
    item = world.items[item_index]
    file_name = f.expand_file_name(
        world.style["style_number"], item["angle_code"], sequence_number
    )
    world.assets.append(
        ingest_asset(
            api,
            item["id"],
            world.photographer_id,
            file_name,
            sequence_number=sequence_number,
            metadata_tags=metadata_tags,
        )
    )
    return world


def build_queued_task(
    api: ApiClient, world: StudioWorld, asset_index: int = 0
) -> StudioWorld:
    """Queue an ingested asset for post-production with the in-house provider."""
    world.tasks.append(
        create_retouch_task(api, world.assets[asset_index]["id"], world.provider_id)
    )
    return world


def build_submitted_task(
    api: ApiClient, world: StudioWorld, task_index: int = 0
) -> StudioWorld:
    """Claim the queued task out of the pool and hand it to quality control."""
    claimed = claim_next(api, world.retoucher_id)
    world.tasks[task_index] = submit_task(api, claimed["id"], world.retoucher_id)
    return world


def build_approved_asset(
    api: ApiClient, world: StudioWorld, task_index: int = 0
) -> StudioWorld:
    """Approve the submitted task, which moves its asset `QC_PENDING -> APPROVED`."""
    world.tasks[task_index] = qc_approve(api, world.tasks[task_index]["id"])
    world.assets[task_index] = world.read_asset(task_index)
    return world


def build_full_pipeline(
    api: ApiClient,
    clock: str = "2026-08-03T08:00:00Z",
    item_specs: Optional[List[Dict[str, Any]]] = None,
    session_kw: Optional[Dict[str, Any]] = None,
    station_kw: Optional[Dict[str, Any]] = None,
    style_kw: Optional[Dict[str, Any]] = None,
    profile_kw: Optional[Dict[str, Any]] = None,
    station_type: str = "MODEL",
    with_outsourced: bool = False,
    start_clock: str = "2026-08-03T09:00:00Z",
) -> StudioWorld:
    """Reference data through to one ingested asset on a `SHOOTING` session."""
    world = build_reference_data(
        api,
        clock=clock,
        station_type=station_type,
        station_kw=station_kw,
        profile_kw=profile_kw,
        with_outsourced=with_outsourced,
    )
    build_style_on_the_rack(api, world, style_kw=style_kw)
    build_planned_session(api, world, item_specs=item_specs, session_kw=session_kw)
    build_shooting_session(api, world, start_clock=start_clock)
    build_ingested_asset(api, world)
    return world


# ─── Filtered discovery helpers (§2.10) ────────────────────────────────────

def get_bookings_of_session(api: ApiClient, session_id: str):
    """List the bookings of one session, created_at ascending, with the meta block."""
    from prd_bench_local_runner.testing import validate_paginated

    return validate_paginated(
        api.list_talent_bookings(PRODUCER, {"session_id": session_id})
    )


def get_items_of_style(api: ApiClient, style_id: str):
    """List the shot-list items of one style, created_at ascending, with the meta block."""
    from prd_bench_local_runner.testing import validate_paginated

    return validate_paginated(
        api.list_shot_list_items(PRODUCER, {"style_id": style_id})
    )


def get_samples_of_style(api: ApiClient, style_id: str):
    """List the samples matched to one style, created_at ascending, with the meta block."""
    from prd_bench_local_runner.testing import validate_paginated

    return validate_paginated(
        api.list_samples(COORDINATOR, {"matched_style_id": style_id})
    )


def get_assets_of_item(api: ApiClient, item_id: str):
    """List the assets of one shot-list item, created_at ascending, with the meta block."""
    from prd_bench_local_runner.testing import validate_paginated

    return validate_paginated(
        api.list_assets(CONTENT_OPS, {"shot_list_item_id": item_id})
    )
