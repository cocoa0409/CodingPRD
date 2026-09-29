"""Composite setup builders.

The database is empty at the start of every test, so each of these functions
builds the preconditions it needs from scratch through published endpoints only.
They use the lenient success reader so that a broken setup step fails loudly and
early rather than surfacing as a confusing assertion later.
"""

from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, Optional

from prd_bench_local_runner.testing import build_user_headers, get_success_data

from . import factories as f
from .constants import (
    CANONICAL_BATCH_CODE,
    CANONICAL_CODE_DATE,
    CANONICAL_NORMALIZED_BATCH_CODE,
    CANONICAL_UNITS_PRODUCED,
    CLOCK_EPOCH,
    CRACKER_CATEGORY,
    CRACKER_IS_REGULATED,
    CRACKER_NAME,
    CRACKER_PRICE_CENTS,
    CRACKER_SKU,
    CRACKER_UNITS_PER_CASE,
    HEADER_ROLE_FOR_STAFF_ROLE,
    MUG_CATEGORY,
    MUG_IS_REGULATED,
    MUG_NAME,
    MUG_PRICE_CENTS,
    MUG_SKU,
    MUG_UNITS_PER_CASE,
    STAFF_ROLE_CARE_AGENT,
    STAFF_ROLE_CARE_SUPERVISOR,
    STAFF_ROLE_QUALITY_LEAD,
    STAFF_ROLE_REGULATORY_OFFICER,
)
from .test_users import CLOCK_HEADERS, TEST_USERS

# ---------------------------------------------------------------------------
# Instant arithmetic, for expressing the PRD's derived instants in a test
# ---------------------------------------------------------------------------
_FORMATS = ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ")


def parse_instant(value: str) -> datetime:
    for fmt in _FORMATS:
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"unrecognised instant: {value!r}")


def format_instant(moment: datetime) -> str:
    """Render an instant the way the API renders one: millisecond precision."""
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def shift(value: str, *, days: int = 0, hours: int = 0, milliseconds: int = 0) -> str:
    moment = parse_instant(value) + timedelta(
        days=days, hours=hours, milliseconds=milliseconds
    )
    return format_instant(moment)


# ---------------------------------------------------------------------------
# Acting identities
# ---------------------------------------------------------------------------
ADMIN = TEST_USERS["system_admin_headers"]


class Actor:
    """A staff row plus the headers that make it act."""

    def __init__(self, key: str, record: dict):
        self.key = key
        self.record = record
        self.id = record["id"]
        self.staff_code = record["staff_code"]
        self.role = record["role"]
        self.authority_tier = record.get("authority_tier")
        self.headers = build_user_headers(
            self.id, HEADER_ROLE_FOR_STAFF_ROLE[record["role"]]
        )


# key -> (staff_code, full_name, role, authority_tier)
ACTOR_SPECS = {
    "ag1": ("AG1", "Ada Grant", STAFF_ROLE_CARE_AGENT, None),
    "ag2": ("AG2", "Abe Gale", STAFF_ROLE_CARE_AGENT, None),
    "sup1": ("SUP1", "Sam Ruiz", STAFF_ROLE_CARE_SUPERVISOR, "TIER_3"),
    "sup2": ("SUP2", "Sol Vega", STAFF_ROLE_CARE_SUPERVISOR, "TIER_1"),
    "sup3": ("SUP3", "Sun Park", STAFF_ROLE_CARE_SUPERVISOR, "TIER_3"),
    "ql1": ("QL1", "Quinn Li", STAFF_ROLE_QUALITY_LEAD, "TIER_3"),
    "ro1": ("RO1", "Rae Ohm", STAFF_ROLE_REGULATORY_OFFICER, "TIER_3"),
    "ro2": ("RO2", "Rob Oak", STAFF_ROLE_REGULATORY_OFFICER, "TIER_3"),
}

DEFAULT_ACTOR_KEYS = ("ag1", "sup1", "sup2", "sup3", "ql1", "ro1", "ro2")

# PRD §4: only CareAgent and CareSupervisor may create a consumer record, so a
# world seeded without either of those roles cannot own one.
_CONSUMER_CAPABLE_ROLES = (STAFF_ROLE_CARE_AGENT, STAFF_ROLE_CARE_SUPERVISOR)


def _consumer_capable_actor(actor_keys) -> Optional[str]:
    for key in actor_keys:
        if ACTOR_SPECS[key][2] in _CONSUMER_CAPABLE_ROLES:
            return key
    return None


class World(dict):
    """A bag of seeded records with attribute access for readability."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:  # pragma: no cover - developer error
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value

    def headers(self, actor_key: str) -> dict:
        return self["actors"][actor_key].headers

    def actor(self, actor_key: str) -> Actor:
        return self["actors"][actor_key]


# ---------------------------------------------------------------------------
# Tier 1: clock and reference data
# ---------------------------------------------------------------------------
def set_clock(api, current_utc: str) -> dict:
    return get_success_data(api.set_clock(current_utc, CLOCK_HEADERS))


def seed_actors(api, keys: Iterable[str] = DEFAULT_ACTOR_KEYS) -> Dict[str, Actor]:
    actors: Dict[str, Actor] = {}
    for key in keys:
        staff_code, full_name, role, tier = ACTOR_SPECS[key]
        payload = f.staff_user_payload(staff_code, full_name, role)
        if tier is not None:
            payload["authority_tier"] = tier
        record = get_success_data(api.create_staff_user(payload, ADMIN))
        actors[key] = Actor(key, record)
    return actors


def add_consumer(
    api,
    world: World,
    key: str = "c1",
    *,
    actor: str = "ag1",
    external_ref: Optional[str] = None,
    full_name: Optional[str] = None,
    postal_code: Optional[str] = "60601",
    **overrides,
) -> dict:
    payload = f.consumer_payload(
        external_ref=external_ref or f"C-{len(world['consumers']) + 1}",
        full_name=full_name or "Rin Sato",
        **overrides,
    )
    if postal_code is not None:
        payload.setdefault("postal_code", postal_code)
    record = get_success_data(api.create_consumer(payload, world.headers(actor)))
    world["consumers"][key] = record
    return record


def add_plant(api, world: World, key: str = "p1", **overrides) -> dict:
    payload = f.plant_payload(**overrides)
    record = get_success_data(api.create_plant(payload, ADMIN))
    world["plants"][key] = record
    return record


def add_line(
    api, world: World, key: str = "l1", *, plant_key: str = "p1", **overrides
) -> dict:
    payload = f.production_line_payload(world["plants"][plant_key]["id"], **overrides)
    record = get_success_data(api.create_production_line(payload, ADMIN))
    world["lines"][key] = record
    return record


def add_product(api, world: World, key: str = "cracker", **overrides) -> dict:
    payload = f.product_payload(**overrides)
    record = get_success_data(api.create_product(payload, ADMIN))
    world["products"][key] = record
    return record


def add_cracker(api, world: World, key: str = "cracker", **overrides) -> dict:
    """The regulated food SKU: a triage multiplies its complaints by 1.075."""
    return add_product(
        api,
        world,
        key,
        sku=overrides.pop("sku", CRACKER_SKU),
        name=overrides.pop("name", CRACKER_NAME),
        category=overrides.pop("category", CRACKER_CATEGORY),
        unit_retail_price_cents=overrides.pop(
            "unit_retail_price_cents", CRACKER_PRICE_CENTS
        ),
        units_per_case=overrides.pop("units_per_case", CRACKER_UNITS_PER_CASE),
        is_regulated_food=overrides.pop("is_regulated_food", CRACKER_IS_REGULATED),
        **overrides,
    )


def add_mug(api, world: World, key: str = "mug", **overrides) -> dict:
    """The unregulated SKU: no regulated-food multiplier applies."""
    return add_product(
        api,
        world,
        key,
        sku=overrides.pop("sku", MUG_SKU),
        name=overrides.pop("name", MUG_NAME),
        category=overrides.pop("category", MUG_CATEGORY),
        unit_retail_price_cents=overrides.pop("unit_retail_price_cents", MUG_PRICE_CENTS),
        units_per_case=overrides.pop("units_per_case", MUG_UNITS_PER_CASE),
        is_regulated_food=overrides.pop("is_regulated_food", MUG_IS_REGULATED),
        **overrides,
    )


def add_lot(
    api,
    world: World,
    key: str = "lot1",
    *,
    product_key: str = "cracker",
    line_key: str = "l1",
    actor: Optional[str] = None,
    **overrides,
) -> dict:
    payload = f.production_lot_payload(
        world["products"][product_key]["id"],
        world["lines"][line_key]["id"],
        **overrides,
    )
    headers = world.headers(actor) if actor else ADMIN
    record = get_success_data(api.create_production_lot(payload, headers))
    world["lots"][key] = record
    return record


def seed_base_world(
    api,
    *,
    clock: Optional[str] = CLOCK_EPOCH,
    actor_keys: Iterable[str] = DEFAULT_ACTOR_KEYS,
    consumer: Optional[dict] = None,
    plant: Optional[dict] = None,
    line: Optional[dict] = None,
    product: str = "cracker",
    product_overrides: Optional[dict] = None,
    lot: Optional[dict] = None,
    create_lot: bool = True,
) -> World:
    """Clock, staff, one consumer, one plant, one line, one product, one lot.

    ``product`` selects the regulated ("cracker") or unregulated ("mug") SKU.
    """
    world = World(
        actors={},
        consumers={},
        plants={},
        lines={},
        products={},
        lots={},
        contacts={},
        complaints={},
        kits={},
        remedies={},
        templates={},
        signals={},
        reports={},
    )
    if clock is not None:
        world["clock"] = set_clock(api, clock)["current_utc"]
    actor_keys = tuple(actor_keys)
    world["actors"] = seed_actors(api, actor_keys)
    consumer_kwargs = dict(consumer or {})
    if "actor" not in consumer_kwargs:
        capable = _consumer_capable_actor(actor_keys)
        if capable is not None:
            consumer_kwargs["actor"] = capable
    if "actor" in consumer_kwargs:
        world["consumer"] = add_consumer(api, world, "c1", **consumer_kwargs)
    world["plant"] = add_plant(api, world, "p1", **(plant or {}))
    world["line"] = add_line(api, world, "l1", **(line or {}))
    adder = add_cracker if product == "cracker" else add_mug
    world["product"] = adder(api, world, product, **(product_overrides or {}))
    if create_lot:
        world["lot"] = add_lot(
            api, world, "lot1", product_key=product, line_key="l1", **(lot or {})
        )
    return world


# ---------------------------------------------------------------------------
# Tier 2: intake hierarchy
# ---------------------------------------------------------------------------
def add_contact(
    api,
    world: World,
    key: str = "ct1",
    *,
    consumer_key: str = "c1",
    actor: str = "ag1",
    **overrides,
) -> dict:
    payload = f.contact_payload(world["consumers"][consumer_key]["id"], **overrides)
    record = get_success_data(api.create_contact(payload, world.headers(actor)))
    world["contacts"][key] = record
    return record


def add_complaint(
    api,
    world: World,
    key: str = "cp1",
    *,
    contact_key: str = "ct1",
    actor: str = "ag1",
    **overrides,
) -> dict:
    payload = f.complaint_payload(world["contacts"][contact_key]["id"], **overrides)
    record = get_success_data(api.create_complaint(payload, world.headers(actor)))
    world["complaints"][key] = record
    return record


def triage(
    api, world: World, complaint_id: str, *, actor: str = "sup1", **overrides
) -> dict:
    payload = f.triage_payload(**overrides)
    record = get_success_data(
        api.triage_complaint(complaint_id, payload, world.headers(actor))
    )
    return record


def seed_triaged_complaint(
    api,
    world: World,
    *,
    contact_key: str = "ct1",
    complaint_key: str = "cp1",
    consumer_key: str = "c1",
    contact_overrides: Optional[dict] = None,
    triage_actor: str = "sup1",
    reuse_contact: bool = False,
    **complaint_overrides,
) -> dict:
    """Contact, complaint, triage — the state most downstream work starts from."""
    if not (reuse_contact and contact_key in world["contacts"]):
        add_contact(
            api,
            world,
            contact_key,
            consumer_key=consumer_key,
            **(contact_overrides or {}),
        )
    add_complaint(
        api, world, complaint_key, contact_key=contact_key, **complaint_overrides
    )
    triaged = triage(
        api, world, world["complaints"][complaint_key]["id"], actor=triage_actor
    )
    world["complaints"][complaint_key] = triaged
    return triaged


ILLNESS_S1_COMPLAINT = dict(
    complaint_type="ILLNESS",
    foreign_object_class="SOFT",
    medical_attention_sought=True,
    symptom_codes=["NAUSEA", "CRAMPS"],
)
"""On the regulated SKU this scores 87.00 provisionally and 93.53 adjudicated."""

PACKAGING_S2_COMPLAINT = dict(
    complaint_type="PACKAGING",
    foreign_object_class="HARD_SHARP",
    medical_attention_sought=True,
    symptom_codes=["CUT", "BLEED", "PAIN", "SWELL"],
)
"""Scores 89.00, and on an unregulated SKU the adjudicated score stays 89.00."""


# ---------------------------------------------------------------------------
# Tier 3: sample kits and the custody chain
# ---------------------------------------------------------------------------
def add_kit(
    api,
    world: World,
    complaint_id: str,
    key: str = "k1",
    *,
    kit_code: str = "K-001",
    seal_id_issued: str = "SEAL-001",
    actor: str = "ag1",
    **overrides,
) -> dict:
    payload = f.sample_kit_payload(
        complaint_id, kit_code=kit_code, seal_id_issued=seal_id_issued, **overrides
    )
    record = get_success_data(api.create_sample_kit(payload, world.headers(actor)))
    world["kits"][key] = record
    return record


def ship_kit(api, world: World, kit_id: str, *, actor: str = "ag1", **overrides) -> dict:
    payload = {"carrier_note": "Kit dispatched."}
    payload.update(overrides)
    return get_success_data(api.ship_sample_kit(kit_id, payload, world.headers(actor)))


def append_custody(
    api,
    world: World,
    kit_id: str,
    event_type: str,
    occurred_at: str,
    *,
    actor: str = "ag1",
    actor_label: str = "Chain custodian",
    seal_id_observed: Optional[str] = None,
    version: Optional[int] = None,
) -> dict:
    """Append one event, re-reading the kit version unless one is supplied."""
    headers = world.headers(actor)
    if version is None:
        version = get_success_data(api.get_sample_kit(kit_id, headers))["version"]
    payload = f.custody_event_payload(
        event_type, occurred_at, version, actor_label=actor_label
    )
    if seal_id_observed is not None:
        payload["seal_id_observed"] = seal_id_observed
    return get_success_data(api.append_custody_event(kit_id, payload, headers))


def receive_kit(api, world: World, kit_id: str, *, actor: str = "ql1", **overrides) -> dict:
    return get_success_data(
        api.receive_sample_kit(kit_id, dict(**overrides), world.headers(actor))
    )


def lab_accept_kit(
    api, world: World, kit_id: str, *, actor: str = "ql1", **overrides
) -> dict:
    payload = {"lab_note": "Sample logged."}
    payload.update(overrides)
    return get_success_data(api.lab_accept_sample_kit(kit_id, payload, world.headers(actor)))


def seed_shipped_kit(
    api,
    world: World,
    complaint_id: str,
    key: str = "k1",
    *,
    kit_code: str = "K-001",
    seal_id_issued: str = "SEAL-001",
    actor: str = "ag1",
) -> dict:
    add_kit(
        api,
        world,
        complaint_id,
        key,
        kit_code=kit_code,
        seal_id_issued=seal_id_issued,
        actor=actor,
    )
    shipped = ship_kit(api, world, world["kits"][key]["id"], actor=actor)
    world["kits"][key] = shipped
    return shipped


def seed_lab_accepted_kit(
    api,
    world: World,
    complaint_id: str,
    key: str = "k1",
    *,
    kit_code: str = "K-001",
    seal_id_issued: str = "SEAL-001",
    sealed_at: str = "2026-08-01T02:00:00Z",
    pickup_at: str = "2026-08-01T06:00:00Z",
    lab_received_at: str = "2026-08-05T06:00:00Z",
    lab_opened_at: str = "2026-08-05T07:00:00Z",
    seal_observed_by_consumer: Optional[str] = None,
    seal_observed_by_lab: Optional[str] = None,
    lab_actor: str = "ql1",
    actor: str = "ag1",
) -> dict:
    """Full five-event chain, ending in a lab-accepted kit."""
    seed_shipped_kit(
        api, world, complaint_id, key, kit_code=kit_code, seal_id_issued=seal_id_issued,
        actor=actor,
    )
    kit_id = world["kits"][key]["id"]
    append_custody(
        api,
        world,
        kit_id,
        "CONSUMER_SEALED",
        sealed_at,
        actor=actor,
        actor_label="Consumer",
        seal_id_observed=(
            seal_id_issued if seal_observed_by_consumer is None else seal_observed_by_consumer
        ),
    )
    append_custody(
        api, world, kit_id, "CARRIER_PICKUP", pickup_at, actor=actor, actor_label="Courier"
    )
    append_custody(
        api,
        world,
        kit_id,
        "LAB_RECEIVED",
        lab_received_at,
        actor=lab_actor,
        actor_label="Lab desk",
        seal_id_observed=(
            seal_id_issued if seal_observed_by_lab is None else seal_observed_by_lab
        ),
    )
    receive_kit(api, world, kit_id, actor=lab_actor)
    append_custody(
        api,
        world,
        kit_id,
        "LAB_OPENED",
        lab_opened_at,
        actor=lab_actor,
        actor_label="Analyst",
    )
    accepted = lab_accept_kit(api, world, kit_id, actor=lab_actor)
    world["kits"][key] = accepted
    return accepted


# ---------------------------------------------------------------------------
# Tier 3: goodwill remedies
# ---------------------------------------------------------------------------
def current_complaint_version(api, world: World, complaint_id: str, actor: str = "ag1") -> int:
    return get_success_data(api.get_complaint(complaint_id, world.headers(actor)))["version"]


def add_remedy(
    api,
    world: World,
    complaint_id: str,
    key: str = "rm1",
    *,
    remedy_type: str = "COUPON",
    requested_value_cents: int = 2000,
    actor: str = "ag1",
    expected_complaint_version: Optional[int] = None,
    **overrides,
) -> dict:
    if expected_complaint_version is None:
        expected_complaint_version = current_complaint_version(
            api, world, complaint_id, actor
        )
    payload = f.remedy_payload(
        complaint_id,
        expected_complaint_version,
        remedy_type=remedy_type,
        requested_value_cents=requested_value_cents,
        **overrides,
    )
    record = get_success_data(api.create_remedy(payload, world.headers(actor)))
    world["remedies"][key] = record
    return record


def submit_remedy(
    api, world: World, remedy_id: str, *, actor: str = "ag1", **overrides
) -> dict:
    payload = {"submit_note": "Please review."}
    payload.update(overrides)
    return get_success_data(api.submit_remedy(remedy_id, payload, world.headers(actor)))


def decide_remedy(
    api, world: World, remedy_id: str, decision: str, *, actor: str = "sup1", **overrides
) -> dict:
    decide_kwargs = {"decision_note": "Decision recorded."}
    decide_kwargs.update(overrides)
    payload = f.decide_payload(decision, **decide_kwargs)
    return get_success_data(api.decide_remedy(remedy_id, payload, world.headers(actor)))


def seed_submitted_remedy(
    api,
    world: World,
    complaint_id: str,
    key: str = "rm1",
    *,
    remedy_type: str = "COUPON",
    requested_value_cents: int = 2000,
    author: str = "ag1",
    **overrides,
) -> dict:
    add_remedy(
        api,
        world,
        complaint_id,
        key,
        remedy_type=remedy_type,
        requested_value_cents=requested_value_cents,
        actor=author,
        **overrides,
    )
    submitted = submit_remedy(api, world, world["remedies"][key]["id"], actor=author)
    world["remedies"][key] = submitted
    return submitted


def seed_approved_remedy(
    api,
    world: World,
    complaint_id: str,
    key: str = "rm1",
    *,
    remedy_type: str = "COUPON",
    requested_value_cents: int = 2000,
    author: str = "ag1",
    decider: str = "sup1",
    **overrides,
) -> dict:
    seed_submitted_remedy(
        api,
        world,
        complaint_id,
        key,
        remedy_type=remedy_type,
        requested_value_cents=requested_value_cents,
        author=author,
        **overrides,
    )
    approved = decide_remedy(
        api, world, world["remedies"][key]["id"], "APPROVE", actor=decider
    )
    world["remedies"][key] = approved
    return approved


# ---------------------------------------------------------------------------
# Tier 3: response templates and the closure path
# ---------------------------------------------------------------------------
def add_template(
    api,
    world: World,
    key: str = "t1",
    *,
    template_code: str = "T-ANY",
    applies_to_type: str = "ANY",
    max_band_allowed: str = "S2",
    activate: bool = True,
    actor: str = "sup1",
    **overrides,
) -> dict:
    payload = f.response_template_payload(
        template_code=template_code,
        applies_to_type=applies_to_type,
        max_band_allowed=max_band_allowed,
        **overrides,
    )
    record = get_success_data(api.create_response_template(payload, world.headers(actor)))
    if activate:
        record = get_success_data(
            api.activate_response_template(record["id"], {}, world.headers(actor))
        )
    world["templates"][key] = record
    return record


def respond(
    api, world: World, complaint_id: str, template_id: str, *, actor: str = "ag1"
) -> dict:
    payload = f.respond_payload(template_id)
    return get_success_data(
        api.respond_to_complaint(complaint_id, payload, world.headers(actor))
    )


def seed_responded_complaint(
    api,
    world: World,
    *,
    complaint_key: str = "cp1",
    template_key: str = "t1",
    template_code: str = "T-ANY",
    max_band_allowed: str = "S2",
    **triaged_kwargs,
) -> dict:
    """A triaged complaint that has received its templated response."""
    seed_triaged_complaint(api, world, complaint_key=complaint_key, **triaged_kwargs)
    add_template(
        api,
        world,
        template_key,
        template_code=template_code,
        max_band_allowed=max_band_allowed,
    )
    responded = respond(
        api,
        world,
        world["complaints"][complaint_key]["id"],
        world["templates"][template_key]["id"],
    )
    world["complaints"][complaint_key] = responded
    return responded


# ---------------------------------------------------------------------------
# Tier 3: regulatory reports
# ---------------------------------------------------------------------------
def find_report(api, world: World, complaint_id: str, *, actor: str = "ro1") -> dict:
    data, _meta = _paginate(api.list_regulatory_reports(
        world.headers(actor), {"complaint_id": complaint_id}
    ))
    assert data, f"no regulatory report exists for complaint {complaint_id}"
    return data[0]


def determine_report(
    api,
    world: World,
    report_id: str,
    determination: str,
    *,
    actor: str = "ro1",
    **overrides,
) -> dict:
    determine_kwargs = {"determination_note": "Determination recorded."}
    determine_kwargs.update(overrides)
    payload = f.determine_payload(determination, **determine_kwargs)
    return get_success_data(
        api.determine_regulatory_report(report_id, payload, world.headers(actor))
    )


def submit_report(
    api,
    world: World,
    report_id: str,
    *,
    actor: str = "ro2",
    agency_reference: str = "AG-90001",
) -> dict:
    payload = f.submit_report_payload(agency_reference)
    return get_success_data(
        api.submit_regulatory_report(report_id, payload, world.headers(actor))
    )


def _paginate(response):
    body = response.json()
    assert 200 <= response.status_code < 300, (
        f"Setup listing failed with HTTP {response.status_code}: {response.text}"
    )
    return body["data"], body["meta"]


# ---------------------------------------------------------------------------
# Tier 4: trend signals and the operations checkpoint
# ---------------------------------------------------------------------------
def add_manual_signal(
    api,
    world: World,
    key: str = "sig1",
    *,
    scope_level: str = "LOT",
    plant_key: str = "p1",
    line_key: Optional[str] = "l1",
    lot_key: Optional[str] = "lot1",
    window_start: str = "2026-07-01T00:00:00Z",
    window_end: str = "2026-08-02T00:00:00Z",
    actor: str = "ql1",
    **overrides,
) -> dict:
    payload = f.trend_signal_payload(
        scope_level,
        world["plants"][plant_key]["id"],
        window_start,
        window_end,
        **overrides,
    )
    if scope_level in ("LOT", "LINE") and line_key is not None:
        payload.setdefault("production_line_id", world["lines"][line_key]["id"])
    if scope_level == "LOT" and lot_key is not None:
        payload.setdefault("lot_id", world["lots"][lot_key]["id"])
    record = get_success_data(api.create_trend_signal(payload, world.headers(actor)))
    world["signals"][key] = record
    return record


def open_investigation(
    api, world: World, signal_id: str, *, actor: str = "ql1", **overrides
) -> dict:
    payload = {"investigation_note": "Investigating."}
    payload.update(overrides)
    return get_success_data(
        api.open_signal_investigation(signal_id, payload, world.headers(actor))
    )


def escalate_to_recall_evaluation(
    api, world: World, signal_id: str, *, actor: str = "ql1", **overrides
) -> dict:
    payload = {"escalation_note": "Escalating."}
    payload.update(overrides)
    return get_success_data(
        api.escalate_recall_evaluation(signal_id, payload, world.headers(actor))
    )


def seed_investigated_signal(
    api,
    world: World,
    key: str = "sig1",
    *,
    scope_level: str = "LOT",
    actor: str = "ql1",
    **signal_kwargs,
) -> dict:
    """A manual signal already moved into INVESTIGATION_OPEN."""
    add_manual_signal(api, world, key, scope_level=scope_level, actor=actor, **signal_kwargs)
    opened = open_investigation(api, world, world["signals"][key]["id"], actor=actor)
    world["signals"][key] = opened
    return opened


def run_quality_ops(
    api, world: World, *, dry_run: Optional[bool] = None, actor: str = "ql1"
) -> dict:
    payload = {} if dry_run is None else {"dry_run": dry_run}
    return get_success_data(api.create_quality_ops_run(payload, world.headers(actor)))


# ---------------------------------------------------------------------------
# Tier 5: accumulation targeting
# ---------------------------------------------------------------------------
def seed_firing_lot_scope(
    api,
    world: World,
    *,
    complaint_template: Optional[dict] = None,
    count: int = 3,
    contact_key: str = "ct1",
    consumer_key: str = "c1",
    triage_all: bool = True,
    prefix: str = "cp",
) -> list:
    """N complaints on the same lot, enough weighted volume to clear a LOT gate.

    With the unregulated SKU and the PACKAGING/HARD_SHARP shape each complaint
    carries a severity weight of 2, so three of them reach a weighted count of
    6.00 against a LOT threshold of 25.0 ppm on a 100,000 unit lot.
    """
    template = dict(complaint_template or PACKAGING_S2_COMPLAINT)
    if contact_key not in world["contacts"]:
        add_contact(api, world, contact_key, consumer_key=consumer_key)
    seeded = []
    for index in range(1, count + 1):
        key = f"{prefix}{index}"
        add_complaint(api, world, key, contact_key=contact_key, **template)
        if triage_all:
            world["complaints"][key] = triage(
                api, world, world["complaints"][key]["id"]
            )
        seeded.append(world["complaints"][key])
    return seeded
